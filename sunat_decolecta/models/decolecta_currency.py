# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RATE_SOURCES = [
    ('sunat', 'SUNAT (compra / venta)'),
    ('sbs_average', 'SBS promedio'),
    ('sbs_accounting', 'SBS contable'),
]
PRICE_KINDS = [
    ('buy', 'Compra'),
    ('sell', 'Venta'),
    ('average', 'Promedio'),
]


class SunatDecolectaCurrencyService(models.AbstractModel):
    _name = 'sunat.decolecta.currency.service'
    _description = 'Tipo de cambio SUNAT / SBS vía Decolecta'

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    @api.model
    def _get_param(self, key, default=None):
        return self.env['sunat.decolecta.api']._get_param(key, default)

    @api.model
    def _get_source(self):
        return self._get_param('sunat_decolecta.rate_source', 'sunat')

    @api.model
    def _get_price_kind(self):
        return self._get_param('sunat_decolecta.rate_price', 'sell')

    @api.model
    def _get_currency_name(self):
        return (self._get_param('sunat_decolecta.rate_currency', 'USD') or 'USD').upper()

    @api.model
    def _to_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @api.model
    def _select_price(self, buy, sell, price):
        if price == 'buy':
            return buy
        if price == 'average':
            if buy and sell:
                return (buy + sell) / 2.0
            return buy or sell
        return sell

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------
    @api.model
    def _fetch_rate(self, target_date=None, source=None, price=None,
                    currency_name=None):
        """Obtiene el tipo de cambio de Decolecta para una fecha.

        :return: dict con ``value``, ``buy``, ``sell``, ``date``, ``source``,
            ``price`` y ``currency``.
        """
        api = self.env['sunat.decolecta.api']
        source = source or self._get_source()
        if source not in dict(RATE_SOURCES):
            source = 'sunat'
        price = price or self._get_price_kind()
        if price not in dict(PRICE_KINDS):
            price = 'sell'
        currency_name = (currency_name or self._get_currency_name()).upper()
        target_date = target_date or fields.Date.context_today(self)
        params = {'date': fields.Date.to_string(target_date)}
        if source == 'sunat':
            data = api._call('tc_sunat', params)
            buy = self._to_float(data.get('buy_price'))
            sell = self._to_float(data.get('sell_price'))
        else:
            params['currency'] = currency_name
            api_key = 'tc_sbs_average' if source == 'sbs_average' else 'tc_sbs_accounting'
            data = api._call(api_key, params)
            buy = self._to_float(data.get('buy_price'))
            sell = self._to_float(data.get('sell_price'))
            if not buy and not sell:
                buy = sell = self._to_float(data.get('price'))
        value = self._select_price(buy, sell, price)
        if value <= 0:
            raise UserError(_(
                'Decolecta no devolvió un tipo de cambio válido para '
                '%(currency)s al %(date)s.',
                currency=currency_name, date=fields.Date.to_string(target_date)))
        response_date = data.get('date')
        if response_date and response_date != fields.Date.to_string(target_date):
            # Protección: si la API ignora el parámetro de fecha (o devuelve la
            # última disponible), no se registra una tasa en una fecha errónea.
            raise UserError(_(
                'Decolecta devolvió el tipo de cambio del %(returned)s en lugar '
                'del %(requested)s. No se registró la tasa para esa fecha.',
                returned=response_date,
                requested=fields.Date.to_string(target_date)))
        return {
            'value': value,
            'buy': buy,
            'sell': sell,
            'date': response_date or fields.Date.to_string(target_date),
            'source': source,
            'price': price,
            'currency': currency_name,
        }

    # ------------------------------------------------------------------
    # Aplicación en res.currency.rate
    # ------------------------------------------------------------------
    @api.model
    def _get_currency(self, currency_name):
        currency = self.env['res.currency'].sudo().search(
            [('name', '=', currency_name)], limit=1)
        if not currency:
            raise UserError(_('La moneda %s no existe en Odoo.') % currency_name)
        return currency

    @api.model
    def apply_rate(self, target_date=None, force=False, source=None, price=None,
                   currency_name=None, company=None):
        """Crea o actualiza la tasa de cambio de una fecha.

        Odoo guarda en ``res.currency.rate.rate`` las unidades de la moneda
        extranjera por 1 unidad de la compañía, por lo que el valor de SUNAT
        (soles por dólar) se invierte antes de guardarlo. Además las tasas se
        leen siempre de la compañía raíz (``company.root_id``).
        """
        company = (company or self.env.company).sudo()
        root = company.root_id or company
        target_date = target_date or fields.Date.context_today(self)
        currency_name = (currency_name or self._get_currency_name()).upper()
        currency = self._get_currency(currency_name)
        if currency == company.currency_id:
            raise UserError(_(
                'No se puede definir el tipo de cambio de %(currency)s porque es '
                'la moneda de la compañía.', currency=currency.name))
        if root.currency_id.name != 'PEN':
            raise UserError(_(
                'El tipo de cambio SUNAT/SBS se expresa en soles (PEN) y la '
                'compañía %(company)s usa %(currency)s.',
                company=root.name, currency=root.currency_id.name))
        rate_model = self.env['res.currency.rate'].sudo()
        existing = rate_model.search([
            ('currency_id', '=', currency.id),
            ('name', '=', target_date),
            ('company_id', '=', root.id),
        ], limit=1)
        if existing and existing.rate and not force:
            return {
                'status': 'skipped',
                'value': 1.0 / existing.rate,
                'rate': existing.rate,
                'currency': currency.name,
                'date': fields.Date.to_string(target_date),
                'company': root.name,
                'id': existing.id,
            }
        info = self._fetch_rate(target_date, source=source, price=price,
                                currency_name=currency_name)
        rate_value = 1.0 / info['value']
        if existing:
            existing.write({'rate': rate_value})
            record = existing
            info['status'] = 'updated'
        else:
            record = rate_model.create({
                'currency_id': currency.id,
                'name': target_date,
                'company_id': root.id,
                'rate': rate_value,
            })
            info['status'] = 'created'
        info.update({
            'rate': rate_value,
            'company': root.name,
            'id': record.id,
        })
        _logger.info(
            'SUNAT Decolecta: tasa %s %s %s = %s (%s)',
            info['status'], target_date, currency.name, info['value'],
            info['source'])
        return info

    @api.model
    def _conversion_check(self, target_date=None, currency_name=None):
        """Convierte 1 unidad de la moneda extranjera a la moneda de la compañía."""
        company = self.env.company
        currency_name = (currency_name or self._get_currency_name()).upper()
        currency = self._get_currency(currency_name)
        target_date = target_date or fields.Date.context_today(self)
        return currency._convert(1.0, company.currency_id, company, target_date)
