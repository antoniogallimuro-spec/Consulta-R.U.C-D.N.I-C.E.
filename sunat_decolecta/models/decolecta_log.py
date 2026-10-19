# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class SunatDecolectaLog(models.Model):
    _name = 'sunat.decolecta.log'
    _description = 'Consumo de la API de Decolecta'
    _order = 'request_datetime desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Endpoint', readonly=True)
    endpoint_key = fields.Char(string='Servicio', readonly=True)
    document_type = fields.Char(string='Tipo de documento', readonly=True)
    document_number = fields.Char(string='Documento', readonly=True,
                                  help='Número enmascarado (no se guarda completo).')
    partner_id = fields.Many2one('res.partner', string='Contacto', readonly=True,
                                 ondelete='set null')
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True)
    user_id = fields.Many2one('res.users', string='Usuario', readonly=True)
    request_datetime = fields.Datetime(
        string='Fecha', readonly=True, default=fields.Datetime.now)
    month = fields.Char(string='Mes', compute='_compute_month', store=True,
                        readonly=True, index=True)
    status_code = fields.Integer(string='Código HTTP', readonly=True)
    success = fields.Boolean(string='Correcta', readonly=True)
    duration_ms = fields.Integer(string='Duración (ms)', readonly=True)
    error_message = fields.Text(string='Error', readonly=True)

    @api.depends('request_datetime')
    def _compute_month(self):
        for log in self:
            log.month = log.request_datetime.strftime('%Y-%m') if log.request_datetime else False

    @api.model
    def _current_month(self):
        return fields.Datetime.now().strftime('%Y-%m')

    @api.model
    def _month_usage(self):
        """Cantidad de consultas registradas en el mes en curso."""
        return self.sudo().search_count([('month', '=', self._current_month())])

    @api.model
    def _month_usage_display(self):
        quota = self.env['sunat.decolecta.api']._monthly_quota()
        used = self._month_usage()
        return _('%(used)s de %(quota)s consultas usadas este mes',
                 used=used, quota=quota)
