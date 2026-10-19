# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Campos numéricos devueltos por /v1/afp/comisiones
AFP_FLOAT_FIELDS = (
    'comision_fija',
    'comision_sobre_flujo',
    'comision_mixta_sobre_flujo',
    'comision_mixta_sobre_saldo',
    'comision_anual_sobre_saldo',
    'prima_de_seguro',
    'aporte_obligatorio',
    'remuneracion_maxima_asegurable',
)


class SunatAfpComision(models.Model):
    _name = 'sunat.afp.comision'
    _description = 'Comisiones de AFP (SBS vía Decolecta)'
    _order = 'periodo desc, afp asc'
    _rec_name = 'afp'

    afp = fields.Char(string='AFP', required=True, readonly=True)
    periodo = fields.Char(string='Periodo', required=True, readonly=True,
                          index=True, help='Periodo en formato AAAA-MM.')
    comision_fija = fields.Float(
        string='Comisión fija (%)', digits=(16, 4), readonly=True)
    comision_sobre_flujo = fields.Float(
        string='Comisión sobre flujo (%)', digits=(16, 4), readonly=True)
    comision_mixta_sobre_flujo = fields.Float(
        string='Comisión mixta sobre flujo (%)', digits=(16, 4), readonly=True)
    comision_mixta_sobre_saldo = fields.Float(
        string='Comisión mixta sobre saldo (%)', digits=(16, 4), readonly=True)
    comision_anual_sobre_saldo = fields.Float(
        string='Comisión anual sobre saldo (%)', digits=(16, 4), readonly=True)
    prima_de_seguro = fields.Float(
        string='Prima de seguro (%)', digits=(16, 4), readonly=True)
    aporte_obligatorio = fields.Float(
        string='Aporte obligatorio (%)', digits=(16, 4), readonly=True)
    remuneracion_maxima_asegurable = fields.Float(
        string='Remuneración máxima asegurable', digits=(16, 2), readonly=True)

    _sql_constraints = [
        ('afp_periodo_uniq', 'unique (afp, periodo)',
         'Ya existe la comisión de esta AFP para el periodo.'),
    ]


class SunatDecolectaAfpService(models.AbstractModel):
    _name = 'sunat.decolecta.afp.service'
    _description = 'Comisiones de AFP vía Decolecta'

    @api.model
    def _to_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _update_commissions(self, year=None, month=None):
        """Sincroniza las comisiones de AFP de un periodo.

        :return: dict con ``count`` (filas procesadas) y ``period``.
        """
        today = fields.Date.context_today(self)
        year = int(year or today.year)
        month = int(month or today.month)
        period = '%04d-%02d' % (year, month)
        data = self.env['sunat.decolecta.api']._call(
            'afp', {'year': year, 'month': month})
        if not isinstance(data, list):
            raise UserError(_(
                'Decolecta devolvió un formato inesperado para las comisiones '
                'de AFP.'))
        comisiones = self.env['sunat.afp.comision'].sudo()
        count = 0
        for row in data:
            if not isinstance(row, dict):
                continue
            afp = (row.get('afp') or '').strip().upper()
            if not afp:
                continue
            row_period = (row.get('periodo') or period).strip()
            vals = {'afp': afp, 'periodo': row_period}
            for field_name in AFP_FLOAT_FIELDS:
                vals[field_name] = self._to_float(row.get(field_name))
            record = comisiones.search(
                [('afp', '=', afp), ('periodo', '=', row_period)], limit=1)
            if record:
                record.write(vals)
            else:
                comisiones.create(vals)
            count += 1
        _logger.info('SUNAT Decolecta: %s comisiones AFP sincronizadas (%s)',
                     count, period)
        return {'count': count, 'period': period}

    @api.model
    def _update_latest_commissions(self):
        """Intenta con el mes en curso y, si no hay datos, con el anterior."""
        today = fields.Date.context_today(self)
        previous_end = today.replace(day=1) - timedelta(days=1)
        attempts = [(today.year, today.month), (previous_end.year, previous_end.month)]
        last_error = None
        for year, month in attempts:
            try:
                result = self._update_commissions(year, month)
            except UserError as error:
                last_error = error
                continue
            if result['count']:
                return result
        if last_error:
            raise last_error
        raise UserError(_(
            'Decolecta no devolvió comisiones de AFP para los últimos periodos.'))
