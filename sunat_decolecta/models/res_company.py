# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------
    # Crons
    # ------------------------------------------------------------------
    @api.model
    def _cron_sunat_decolecta_rate(self):
        """Registra el tipo de cambio del día (si el cron está habilitado)."""
        api = self.env['sunat.decolecta.api']
        if not api._get_bool_param('sunat_decolecta.rate_cron_enabled', True):
            return
        service = self.env['sunat.decolecta.currency.service']
        today = fields.Date.context_today(self)
        # SUNAT/SBS no publican tipo de cambio los fines de semana: Odoo usa la
        # última tasa anterior, así que no hace falta crear una del sábado.
        if today.weekday() >= 5:
            return
        for company in self.sudo().search([]):
            try:
                service.with_company(company).apply_rate(today)
            except Exception as error:  # el cron nunca debe fallar en bloque
                _logger.warning(
                    'SUNAT Decolecta: no se pudo registrar el tipo de cambio de '
                    '%(company)s: %(error)s',
                    {'company': company.name, 'error': error})

    @api.model
    def _cron_sunat_decolecta_afp(self):
        """Carga las comisiones AFP del mes anterior si aún no están."""
        today = fields.Date.context_today(self)
        # Las comisiones del mes anterior se publican a inicios de mes: se
        # intenta solo los primeros días para no gastar consultas en vano.
        if today.day not in (3, 4, 5):
            return
        previous_end = today.replace(day=1) - timedelta(days=1)

        period = previous_end.strftime('%Y-%m')
        comisiones = self.env['sunat.afp.comision'].sudo()
        if comisiones.search_count([('periodo', '=', period)]):
            return
        try:
            self.env['sunat.decolecta.afp.service']._update_commissions(
                previous_end.year, previous_end.month)
        except Exception as error:  # el cron nunca debe fallar en bloque
            _logger.warning(
                'SUNAT Decolecta: no se pudieron cargar las comisiones AFP '
                '%(period)s: %(error)s', {'period': period, 'error': error})
