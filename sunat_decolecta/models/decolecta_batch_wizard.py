# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_partner import EXPECTED_LENGTH


class SunatDecolectaBatchWizard(models.TransientModel):
    _name = 'sunat.decolecta.batch.wizard'
    _description = 'Consulta masiva SUNAT / RENIEC'

    partner_ids = fields.Many2many(
        'res.partner', 'sunat_decolecta_batch_partner_rel', 'wizard_id',
        'partner_id', string='Contactos',
        help='Déjalo vacío para tomar automáticamente los contactos con '
             'RUC/DNI que aún no han sido consultados.')
    only_missing = fields.Boolean(
        string='Solo contactos sin consulta previa', default=True)
    limit = fields.Integer(string='Máximo de contactos', default=50)
    endpoint_mode = fields.Selection(
        [('basic', 'Básico (sin anexos ni actividad económica)'),
         ('full', 'Completo (incluye anexos)')],
        string='Nivel de detalle', default='full', required=True)
    force = fields.Boolean(
        string='Ignorar caché y volver a consultar',
        help='Sin esta opción se omiten los contactos cuya última consulta '
             'sigue vigente según los días de caché configurados.')
    candidate_count = fields.Integer(
        string='Contactos a procesar', compute='_compute_totals')
    query_count = fields.Integer(
        string='Consultas a la API', compute='_compute_totals')
    quota_used = fields.Integer(string='Consumo del mes', compute='_compute_quota')
    quota_total = fields.Integer(string='Cuota mensual', compute='_compute_quota')
    quota_left = fields.Integer(string='Consultas disponibles', compute='_compute_quota')
    state = fields.Selection(
        [('draft', 'Listo'), ('done', 'Resultado')], default='draft')
    ok_count = fields.Integer(string='Consultados', readonly=True)
    skipped_count = fields.Integer(string='Omitidos', readonly=True)
    error_count = fields.Integer(string='Errores', readonly=True)
    result = fields.Text(string='Resultado', readonly=True)

    # ------------------------------------------------------------------
    # Candidatos
    # ------------------------------------------------------------------
    def _get_candidates(self):
        """Contactos con documento válido que se pueden consultar."""
        self.ensure_one()
        Partner = self.env['res.partner']
        if self.partner_ids:
            partners = self.partner_ids
        else:
            partners = Partner.search(
                [('vat', '!=', False)], limit=max(self.limit * 5, 100))
        candidates = Partner
        for partner in partners:
            numero = partner._sunat_decolecta_normalize(partner.vat)
            if not numero:
                continue
            endpoint_key = partner._sunat_decolecta_endpoint_key(numero)
            if endpoint_key not in ('ruc', 'dni'):
                continue
            expected = EXPECTED_LENGTH.get(endpoint_key)
            if expected and len(numero) != expected:
                continue
            if not self.partner_ids and self.only_missing and partner.sunat_decolecta_last_query:
                continue
            candidates |= partner
            if not self.partner_ids and len(candidates) >= max(self.limit, 1):
                break
        return candidates

    def _get_pending(self, candidates=None):
        """Candidatos que realmente consumirán consultas de la API."""
        self.ensure_one()
        candidates = candidates if candidates is not None else self._get_candidates()
        if self.force:
            return candidates
        return candidates.filtered(
            lambda partner: not partner._sunat_decolecta_is_cache_valid(
                partner._sunat_decolecta_normalize(partner.vat)))

    @api.depends('partner_ids', 'only_missing', 'limit', 'force')
    def _compute_totals(self):
        for wizard in self:
            candidates = wizard._get_candidates()
            wizard.candidate_count = len(candidates)
            wizard.query_count = len(wizard._get_pending(candidates))

    @api.depends('query_count')
    def _compute_quota(self):
        api = self.env['sunat.decolecta.api']
        used = api._month_usage()
        total = api._monthly_quota()
        for wizard in self:
            wizard.quota_used = used
            wizard.quota_total = total
            wizard.quota_left = max(total - used, 0)

    # ------------------------------------------------------------------
    # Ejecución
    # ------------------------------------------------------------------
    def action_run(self):
        self.ensure_one()
        candidates = self._get_candidates()
        if not candidates:
            raise UserError(_(
                'No hay contactos con RUC o DNI válidos para consultar.'))
        pending = self._get_pending(candidates)
        if not pending:
            raise UserError(_(
                'Todos los contactos tienen una consulta vigente. Marca '
                '"Ignorar caché y volver a consultar" para actualizarlos.'))
        api = self.env['sunat.decolecta.api']
        quota_left = max(api._monthly_quota() - api._month_usage(), 0)
        if len(pending) > quota_left:
            raise UserError(_(
                'La consulta requiere %(required)s consultas y solo quedan '
                '%(left)s disponibles este mes. Reduce el máximo de contactos '
                'o amplía tu plan de Decolecta.',
                required=len(pending), left=quota_left))
        ok = errors = 0
        lines = []
        for partner in pending:
            try:
                endpoint_key = partner._sunat_decolecta_fetch_and_write(
                    mode=self.endpoint_mode)
            except UserError as error:
                errors += 1
                lines.append('✗ %s: %s' % (partner.display_name, error))
            else:
                ok += 1
                lines.append('✓ %s (%s)' % (
                    partner.display_name, endpoint_key.upper()))
        summary = _(
            'Consultados: %(ok)s · Errores: %(errors)s · Omitidos por caché: %(skipped)s',
            ok=ok, errors=errors, skipped=len(candidates) - len(pending))
        self.write({
            'state': 'done',
            'ok_count': ok,
            'error_count': errors,
            'skipped_count': len(candidates) - len(pending),
            'result': summary + '\n\n' + '\n'.join(lines[:200]),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
