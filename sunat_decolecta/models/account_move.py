# -*- coding: utf-8 -*-
import logging

from odoo import _, models
from odoo.exceptions import UserError

from .res_partner import BAD_STATES

_logger = logging.getLogger(__name__)

VALIDATED_MOVE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        self._sunat_decolecta_check_partners()
        return super()._post(soft=soft)

    def _sunat_decolecta_check_partners(self):
        """Avisa o bloquea la publicación si el RUC está observado en SUNAT.

        La validación usa los datos ya guardados en el contacto: nunca consulta
        la API al publicar un comprobante (para no consumir cuota ni bloquear
        la facturación por una caída del proveedor).
        """
        api = self.env['sunat.decolecta.api']
        mode = api._get_param('sunat.decolecta.invoice_validation', 'warn')
        if mode not in ('warn', 'block'):
            return
        if self.env.context.get('sunat_decolecta_skip_validation'):
            return
        for move in self:
            if move.move_type not in VALIDATED_MOVE_TYPES:
                continue
            partner = move.partner_id.commercial_partner_id
            if not partner:
                continue
            vat = partner._sunat_decolecta_normalize(partner.vat)
            if len(vat) != 11:
                continue
            if (partner.country_id.code or 'PE') != 'PE':
                continue
            state = (partner.sunat_decolecta_state or '').strip().upper()
            condition = (partner.sunat_decolecta_condition or '').strip().upper()
            if state not in BAD_STATES and condition != 'NO HABIDO':
                continue
            message = _(
                'SUNAT reporta al RUC %(vat)s de %(partner)s en estado '
                '"%(state)s" y condición "%(condition)s".',
                vat=partner.vat or '',
                partner=partner.display_name,
                state=state or '-',
                condition=condition or '-')
            if mode == 'block':
                raise UserError(message + '\n\n' + _(
                    'Corrige el contacto o publica el comprobante omitiendo la '
                    'validación SUNAT.'))
            _logger.warning('SUNAT Decolecta: %s %s', move.name, message)
            move.message_post(
                body=message + ' ' + _('Revisa el comprobante antes de enviarlo.'),
                subtype_xmlid='mail.mt_note')
