# -*- coding: utf-8 -*-
from odoo import _, fields, models

from .decolecta_currency import PRICE_KINDS, RATE_SOURCES

AUTO_QUERY_MODES = [
    ('basic', 'Básico (dirección y estado; más económico)'),
    ('full', 'Completo (anexos, actividad económica y trabajadores)'),
]
INVOICE_VALIDATION_MODES = [
    ('off', 'Desactivada'),
    ('warn', 'Solo avisar en el comprobante'),
    ('block', 'Bloquear la publicación'),
]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ------------------------------------------------------------------
    # Conexión
    # ------------------------------------------------------------------
    sunat_decolecta_api_token = fields.Char(
        string='Token de Decolecta',
        config_parameter='sunat_decolecta.api_token',
        groups='base.group_system',
        help='Token Bearer de tu cuenta en https://decolecta.com',
    )
    sunat_decolecta_auto_query = fields.Boolean(
        string='Consultar automáticamente al escribir el documento',
        config_parameter='sunat_decolecta.auto_query',
        help='Desactívalo si prefieres consultar solo con el botón "Consultar SUNAT". '
             'Útil para controlar el consumo de consultas del plan de Decolecta.',
    )
    sunat_decolecta_auto_query_mode = fields.Selection(
        AUTO_QUERY_MODES,
        string='Detalle de la consulta automática',
        config_parameter='sunat_decolecta.auto_query_mode',
        default='basic',
        groups='base.group_system',
        help='El endpoint básico devuelve razón social, dirección y estado. '
             'El completo agrega anexos, actividad económica y trabajadores.',
    )
    sunat_decolecta_cache_days = fields.Integer(
        string='Días de caché de las consultas',
        config_parameter='sunat_decolecta.cache_days',
        default=30,
        groups='base.group_system',
        help='Si el contacto fue consultado hace menos días, el botón principal '
             'reutiliza los datos guardados. Usa 0 para consultar siempre.',
    )
    sunat_decolecta_monthly_quota = fields.Integer(
        string='Cuota mensual de consultas',
        config_parameter='sunat_decolecta.monthly_quota',
        default=1000,
        groups='base.group_system',
        help='Consultas incluidas en tu plan de Decolecta. Se usa para avisar '
             'antes de agotar la cuota (plan gratuito: 1000 al mes).',
    )
    sunat_decolecta_month_usage = fields.Char(
        string='Consumo del mes',
        compute='_compute_sunat_decolecta_month_usage',
        groups='base.group_system',
    )

    # ------------------------------------------------------------------
    # Tipo de cambio
    # ------------------------------------------------------------------
    sunat_decolecta_rate_source = fields.Selection(
        RATE_SOURCES,
        string='Fuente del tipo de cambio',
        config_parameter='sunat_decolecta.rate_source',
        default='sunat',
        groups='base.group_system',
    )
    sunat_decolecta_rate_price = fields.Selection(
        PRICE_KINDS,
        string='Tipo de precio',
        config_parameter='sunat_decolecta.rate_price',
        default='sell',
        groups='base.group_system',
    )
    sunat_decolecta_rate_currency = fields.Char(
        string='Moneda extranjera',
        config_parameter='sunat_decolecta.rate_currency',
        default='USD',
        groups='base.group_system',
        help='Código ISO de la moneda a convertir (USD por defecto).',
    )
    sunat_decolecta_rate_cron_enabled = fields.Boolean(
        string='Registrar el tipo de cambio a diario',
        config_parameter='sunat_decolecta.rate_cron_enabled',
        default=True,
        groups='base.group_system',
        help='Un cron diario crea la tasa de cambio del día en la compañía. '
             'Si la fecha ya tiene tasa, no se consulta la API.',
    )

    # ------------------------------------------------------------------
    # Facturación
    # ------------------------------------------------------------------
    sunat_decolecta_invoice_validation = fields.Selection(
        INVOICE_VALIDATION_MODES,
        string='Validación de RUC al publicar comprobantes',
        config_parameter='sunat_decolecta.invoice_validation',
        default='warn',
        groups='base.group_system',
        help='Usa los datos de SUNAT ya guardados en el contacto (no consume API). '
             '"Solo avisar" deja una nota en el comprobante; "Bloquear" impide '
             'publicar si el RUC está de baja, suspensión temporal o no habido.',
    )

    # ------------------------------------------------------------------
    # Cálculos
    # ------------------------------------------------------------------
    def _compute_sunat_decolecta_month_usage(self):
        usage = self.env['sunat.decolecta.log']._month_usage_display()
        for record in self:
            record.sunat_decolecta_month_usage = usage

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def action_sunat_decolecta_test_token(self):
        """Valida el token con una consulta real de tipo de cambio."""
        data = self.env['sunat.decolecta.api']._test_token()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Token de Decolecta válido'),
                'message': _(
                    'Tipo de cambio SUNAT del %(date)s: compra %(buy)s / venta %(sell)s.',
                    date=data.get('date') or '-',
                    buy=data.get('buy_price') or '-',
                    sell=data.get('sell_price') or '-'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sunat_decolecta_update_rate(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Actualizar tipo de cambio'),
            'res_model': 'sunat.decolecta.rate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_currency_name': self.sunat_decolecta_rate_currency or 'USD',
            },
        }

    def action_sunat_decolecta_update_afp(self):
        result = self.env['sunat.decolecta.afp.service']._update_latest_commissions()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Comisiones AFP actualizadas'),
                'message': _(
                    '%(count)s AFP sincronizadas para el periodo %(period)s.',
                    count=result['count'], period=result['period']),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_sunat_decolecta_open_log(self):
        return self.env['ir.actions.act_window']._for_xml_id(
            'sunat_decolecta.action_sunat_decolecta_log')

