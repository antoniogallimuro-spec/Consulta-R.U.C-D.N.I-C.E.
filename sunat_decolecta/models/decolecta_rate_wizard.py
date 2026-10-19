# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .decolecta_currency import PRICE_KINDS, RATE_SOURCES

# Límite de días por ejecución (protege la cuota mensual de Decolecta)
MAX_DAYS = 366

STATUS_LABELS = {
    'created': 'creada',
    'updated': 'actualizada',
    'skipped': 'sin cambios',
}


class SunatDecolectaRateWizard(models.TransientModel):
    _name = 'sunat.decolecta.rate.wizard'
    _description = 'Actualizar tipo de cambio desde Decolecta'

    date_from = fields.Date(
        string='Desde', required=True, default=fields.Date.context_today)
    date_to = fields.Date(
        string='Hasta', required=True, default=fields.Date.context_today)
    source = fields.Selection(
        RATE_SOURCES, string='Fuente', required=True,
        default=lambda self: self._default_param('sunat_decolecta.rate_source', 'sunat'))
    price = fields.Selection(
        PRICE_KINDS, string='Tipo de precio', required=True,
        default=lambda self: self._default_param('sunat_decolecta.rate_price', 'sell'))
    currency_name = fields.Char(
        string='Moneda', required=True, default='USD',
        help='Código ISO de la moneda extranjera (por ejemplo USD).')
    skip_weekends = fields.Boolean(
        string='Omitir sábados y domingos', default=True,
        help='SUNAT no publica tipo de cambio los fines de semana.')
    force = fields.Boolean(
        string='Sobrescribir tasas existentes',
        help='Si se desactiva, las fechas que ya tienen tasa no se consultan.')
    state = fields.Selection(
        [('draft', 'Listo'), ('done', 'Resultado')], default='draft')
    result = fields.Text(string='Resultado', readonly=True)

    @api.model
    def _default_param(self, key, default):
        return self.env['sunat.decolecta.api']._get_param(key, default)

    @api.onchange('source')
    def _onchange_source(self):
        if self.source in ('sbs_average', 'sbs_accounting'):
            self.price = 'average'

    def action_apply(self):
        self.ensure_one()
        if self.date_to < self.date_from:
            raise UserError(_('La fecha final no puede ser anterior a la inicial.'))
        if (self.date_to - self.date_from).days >= MAX_DAYS:
            raise UserError(_(
                'El rango no puede superar %(days)s días por ejecución.',
                days=MAX_DAYS))
        service = self.env['sunat.decolecta.currency.service']
        created = updated = skipped = errors = 0
        lines = []
        day = self.date_from
        while day <= self.date_to:
            if self.skip_weekends and day.weekday() >= 5:
                day += timedelta(days=1)
                continue
            try:
                info = service.apply_rate(
                    day, force=self.force, source=self.source,
                    price=self.price, currency_name=self.currency_name)
            except UserError as error:
                errors += 1
                lines.append(_('%(date)s: ERROR %(error)s',
                               date=fields.Date.to_string(day), error=error))
            else:
                status = info['status']
                if status == 'created':
                    created += 1
                elif status == 'updated':
                    updated += 1
                else:
                    skipped += 1
                lines.append(_('%(date)s: 1 %(currency)s = %(value)s (%(status)s)',
                               date=fields.Date.to_string(day),
                               currency=info['currency'],
                               value=info['value'],
                               status=STATUS_LABELS.get(status, status)))
            day += timedelta(days=1)
        summary = _(
            'Creadas: %(created)s · Actualizadas: %(updated)s · '
            'Sin cambios: %(skipped)s · Errores: %(errors)s',
            created=created, updated=updated, skipped=skipped, errors=errors)
        try:
            conversion = service._conversion_check(
                self.date_to, self.currency_name)
        except Exception:
            conversion = False
        if conversion:
            summary += '\n' + _(
                'Verificación al %(date)s: 1 %(currency)s = %(amount).4f %(company_currency)s',
                date=fields.Date.to_string(self.date_to),
                currency=self.currency_name.upper(),
                amount=conversion,
                company_currency=self.env.company.currency_id.name)
        self.write({
            'state': 'done',
            'result': summary + '\n\n' + '\n'.join(lines),
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
