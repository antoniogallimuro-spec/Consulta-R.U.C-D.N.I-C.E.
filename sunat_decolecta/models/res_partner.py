# -*- coding: utf-8 -*-
import json
import logging
from datetime import timedelta
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .decolecta_api import DECOLECTA_BASE_URL, DECOLECTA_ENDPOINTS

_logger = logging.getLogger(__name__)

# Códigos de la localización peruana (l10n_latam.identification.type.l10n_pe_vat_code)
DOC_CODE_TO_ENDPOINT = {'1': 'dni', '6': 'ruc', '4': 'ce'}
LENGTH_TO_DOC_CODE = {8: '1', 11: '6'}
EXPECTED_LENGTH = {'dni': 8, 'ruc': 11}
DOC_LABEL = {'ruc': 'RUC', 'dni': 'DNI', 'ce': 'Carné de Extranjería'}

# Estados de SUNAT que impiden emitir comprobantes con normalidad
BAD_STATES = ('BAJA DE OFICIO', 'BAJA DEFINITIVA', 'SUSPENSION TEMPORAL')



class ResPartner(models.Model):
    _inherit = 'res.partner'

    sunat_decolecta_commercial_name = fields.Char(string='Nombre Comercial (SUNAT)')
    sunat_decolecta_state = fields.Char(string='Estado Contribuyente', readonly=True)
    sunat_decolecta_condition = fields.Char(string='Condición Domicilio', readonly=True)
    sunat_decolecta_company_type = fields.Char(
        string='Tipo de Contribuyente', readonly=True,
        help='Tipo de persona/empresa según SUNAT (S.A.C., E.I.R.L., persona natural, etc.).')
    sunat_decolecta_economic_activity = fields.Char(
        string='Actividad Económica', readonly=True)
    sunat_decolecta_workers = fields.Char(
        string='N° de Trabajadores', readonly=True)
    sunat_decolecta_billing_type = fields.Char(
        string='Sistema de Facturación', readonly=True)
    sunat_decolecta_accounting_type = fields.Char(
        string='Sistema de Contabilidad', readonly=True)
    sunat_decolecta_foreign_trade = fields.Char(
        string='Comercio Exterior', readonly=True)
    sunat_decolecta_is_withholding_agent = fields.Boolean(
        string='Agente de Retención', readonly=True)
    sunat_decolecta_is_good_taxpayer = fields.Boolean(
        string='Buen Contribuyente', readonly=True)
    sunat_decolecta_ubigeo = fields.Char(string='Ubigeo', readonly=True)
    sunat_decolecta_address_detail = fields.Char(
        string='Dirección Estructurada (SUNAT)', readonly=True,
        help='Vía, zona, número, interior, lote, departamento, manzana y kilómetro.')
    sunat_decolecta_anexos = fields.Text(
        string='Anexos SUNAT', readonly=True,
        help='Locales anexos devueltos por SUNAT en formato JSON.')
    sunat_decolecta_anexos_html = fields.Html(
        string='Anexos SUNAT', compute='_compute_sunat_decolecta_anexos_html')
    sunat_decolecta_anexos_count = fields.Integer(
        string='N° de Anexos', compute='_compute_sunat_decolecta_anexos_count')
    sunat_decolecta_last_query = fields.Datetime(
        string='Última consulta SUNAT', readonly=True)
    sunat_decolecta_last_query_vat = fields.Char(
        string='Documento consultado', readonly=True,
        help='Documento con el que se obtuvo la última respuesta de SUNAT/RENIEC.')

    @api.depends('sunat_decolecta_anexos')
    def _compute_sunat_decolecta_anexos_count(self):
        for partner in self:
            partner.sunat_decolecta_anexos_count = len(
                partner._sunat_decolecta_get_anexos())

    @api.depends('sunat_decolecta_anexos')
    def _compute_sunat_decolecta_anexos_html(self):
        for partner in self:
            rows = partner._sunat_decolecta_parse_anexos(
                partner.sunat_decolecta_anexos)
            if not rows:
                partner.sunat_decolecta_anexos_html = False
                continue
            items = []
            for row in rows:
                location = ', '.join(part for part in (
                    row.get('distrito'), row.get('provincia'),
                    row.get('departamento')) if part)
                items.append('<li>%s <span class="text-muted">(%s)</span></li>' % (
                    escape(row.get('direccion') or ''),
                    escape(location)))
            partner.sunat_decolecta_anexos_html = (
                '<ul class="mb-0">%s</ul>' % ''.join(items))



    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    @api.model
    def _sunat_decolecta_get_token(self):
        """Devuelve el token Bearer configurado en Ajustes o en parámetros."""
        return self.env['sunat.decolecta.api']._get_token()

    @api.model
    def _sunat_decolecta_api(self):
        return self.env['sunat.decolecta.api']

    @api.model
    def _sunat_decolecta_auto_query(self):
        """Indica si la consulta automática (onchange) está habilitada."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'sunat_decolecta.auto_query', default='True')
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    @api.model
    def _sunat_decolecta_auto_query_mode(self):
        """Modo de la consulta automática: ``basic`` (económico) o ``full``."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            'sunat_decolecta.auto_query_mode', default='basic')
        return 'full' if str(value).strip().lower() == 'full' else 'basic'

    @api.model
    def _sunat_decolecta_cache_days(self):
        """Días de vigencia de una consulta previa (0 desactiva la caché)."""
        return self._sunat_decolecta_api()._get_int_param(
            'sunat_decolecta.cache_days', 30)


    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @api.model
    def _sunat_decolecta_normalize(self, numero):
        """Deja el número de documento en mayúsculas y sin separadores."""
        if not numero:
            return ''
        return ''.join(char for char in str(numero) if char.isalnum()).upper()

    def _sunat_decolecta_endpoint_key(self, numero=None):
        """Devuelve 'ruc', 'dni' o 'ce' según el tipo de documento o su longitud."""
        self.ensure_one()
        if numero is None:
            numero = self._sunat_decolecta_normalize(self.vat)
        ident_type = self.l10n_latam_identification_type_id
        code = ident_type.l10n_pe_vat_code if ident_type else False
        endpoint_key = DOC_CODE_TO_ENDPOINT.get(code)
        if not endpoint_key:
            endpoint_key = DOC_CODE_TO_ENDPOINT.get(LENGTH_TO_DOC_CODE.get(len(numero)))
        return endpoint_key

    def _sunat_decolecta_guess_doc_type(self, numero):
        """Tipo de documento peruano (RUC/DNI) deducido por la longitud."""
        code = LENGTH_TO_DOC_CODE.get(len(numero))
        if not code:
            return self.env['l10n_latam.identification.type']
        ident_types = self.env['l10n_latam.identification.type'].search(
            [('l10n_pe_vat_code', '=', code)])
        peru = self.env['res.country'].search([('code', '=', 'PE')], limit=1)
        if peru:
            ident_types = ident_types.filtered(
                lambda rec: rec.country_id == peru) or ident_types
        return ident_types[:1]

    @api.model
    def _sunat_decolecta_check_length(self, numero, endpoint_key):
        """Valida que el número tenga la longitud esperada para su tipo."""
        expected = EXPECTED_LENGTH.get(endpoint_key)
        if expected and len(numero) != expected:
            raise UserError(_(
                'El %s debe tener %s dígitos (se ingresaron %s).'
            ) % (DOC_LABEL.get(endpoint_key, 'documento'), expected, len(numero)))
        return True

    @api.model
    def _sunat_decolecta_find_district(self, data):
        """Busca el distrito de l10n_pe por ubigeo o por nombres."""
        District = self.env['l10n_pe.res.city.district']
        ubigeo = (data.get('ubigeo') or '').strip()
        if len(ubigeo) == 6:
            district = District.search([('code', '=', ubigeo)], limit=1)
            if district:
                return district
        distrito = (data.get('distrito') or '').strip()
        if not distrito:
            return District
        provincia = (data.get('provincia') or '').strip()
        departamento = (data.get('departamento') or '').strip()
        cities = self.env['res.city']
        if provincia:
            city_domain = [('name', '=ilike', provincia)]
            if departamento:
                state = self.env['res.country.state'].search([
                    ('name', '=ilike', departamento),
                    ('country_id.code', '=', 'PE'),
                ], limit=1)
                if state:
                    city_domain.append(('state_id', '=', state.id))
            cities = self.env['res.city'].search(city_domain)
        domain = [('name', '=ilike', distrito)]
        if cities:
            domain.append(('city_id', 'in', cities.ids))
        district = District.search(domain, limit=1)
        if not district:
            district = District.search([('name', '=ilike', distrito)], limit=1)
        return district

    # ------------------------------------------------------------------
    # API Decolecta
    # ------------------------------------------------------------------
    @api.model
    def _sunat_decolecta_request(self, numero, endpoint_key, mode='full'):
        """Consulta la API de Decolecta y devuelve el JSON de la respuesta.

        :param endpoint_key: ``ruc``, ``dni`` o ``ce``.
        :param mode: ``full`` (datos completos de SUNAT) o ``basic``
            (endpoint económico, sin anexos ni actividad económica).
        """
        if endpoint_key == 'ruc':
            api_key = 'ruc_basic' if mode == 'basic' else 'ruc_full'
        else:
            api_key = endpoint_key
        _logger.info('SUNAT Decolecta: consultando %s para %s',
                     api_key, self._sunat_decolecta_api()._mask_document(numero))
        return self.env['sunat.decolecta.api']._call(
            api_key, {'numero': numero}, document_number=numero,
            partner=self if self.id else None)


    # ------------------------------------------------------------------
    # Preparación de valores
    # ------------------------------------------------------------------
    @api.model
    def _sunat_decolecta_prepare_vals(self, data, endpoint_key):
        """Convierte la respuesta de Decolecta en valores de ``res.partner``."""
        vals = {'sunat_decolecta_last_query': fields.Datetime.now()}
        peru = self.env['res.country'].search([('code', '=', 'PE')], limit=1)

        if endpoint_key == 'ruc':
            razon_social = (data.get('razon_social') or '').strip()
            if razon_social:
                vals['name'] = razon_social
            numero = (data.get('numero_documento') or '').strip()
            if numero:
                vals['vat'] = numero
                vals['sunat_decolecta_last_query_vat'] = numero
            # Ojo: la clave de la API es "direccion" (sin tilde). El código
            # anterior leía "dirección" y por eso nunca copiaba la dirección.
            direccion = (data.get('direccion') or data.get('dirección') or '').strip()
            detalle = self._sunat_decolecta_address_detail(data)
            if direccion:
                vals['street'] = direccion
            elif detalle:
                vals['street'] = detalle
            if detalle:
                vals['sunat_decolecta_address_detail'] = detalle
            comercial = (data.get('nombre_comercial') or '').strip()
            if comercial:
                vals['sunat_decolecta_commercial_name'] = comercial
            estado = (data.get('estado') or '').strip()
            if estado:
                vals['sunat_decolecta_state'] = estado
            condicion = (data.get('condicion') or '').strip()
            if condicion:
                vals['sunat_decolecta_condition'] = condicion
            vals['company_type'] = 'company'
            # Datos adicionales del endpoint /v1/sunat/ruc/full. Solo se
            # escriben si vienen en la respuesta (el endpoint básico devuelve
            # menos campos y no debe borrar lo ya consultado).
            extras = {
                'tipo': 'sunat_decolecta_company_type',
                'actividad_economica': 'sunat_decolecta_economic_activity',
                'numero_trabajadores': 'sunat_decolecta_workers',
                'tipo_facturacion': 'sunat_decolecta_billing_type',
                'tipo_contabilidad': 'sunat_decolecta_accounting_type',
                'comercio_exterior': 'sunat_decolecta_foreign_trade',
                'ubigeo': 'sunat_decolecta_ubigeo',
            }
            for key, field_name in extras.items():
                if key in data:
                    value = data.get(key)
                    vals[field_name] = (
                        str(value).strip() if value not in (None, False) else '') or False
            for key, field_name in (
                    ('es_agente_retencion', 'sunat_decolecta_is_withholding_agent'),
                    ('es_buen_contribuyente', 'sunat_decolecta_is_good_taxpayer')):
                if key in data:
                    vals[field_name] = bool(data.get(key))
            anexos = data.get('locales_anexos')
            if anexos is not None:
                vals['sunat_decolecta_anexos'] = (
                    json.dumps(anexos, ensure_ascii=False) if anexos else False)
            district = self._sunat_decolecta_find_district(data)

            if district:
                vals['l10n_pe_district'] = district.id
                city = district.city_id
                if city:
                    vals['city_id'] = city.id
                    if city.state_id:
                        vals['state_id'] = city.state_id.id
                        if city.state_id.country_id:
                            vals['country_id'] = city.state_id.country_id.id
            if peru and not vals.get('country_id'):
                vals['country_id'] = peru.id
            return vals

        nombre = (data.get('full_name') or '').strip()
        if not nombre:
            parts = [
                (data.get('first_last_name') or '').strip(),
                (data.get('second_last_name') or '').strip(),
                (data.get('first_name') or '').strip(),
            ]
            nombre = ' '.join(part for part in parts if part)
        if nombre:
            vals['name'] = nombre
        numero = (data.get('document_number') or '').strip()
        if numero:
            vals['sunat_decolecta_last_query_vat'] = numero
        vals['company_type'] = 'person'
        if peru:
            vals['country_id'] = peru.id
        return vals

    @api.model
    def _sunat_decolecta_address_detail(self, data):
        """Compone la dirección estructurada que devuelve SUNAT."""
        parts = []
        via_tipo = (data.get('via_tipo') or '').strip()
        via_nombre = (data.get('via_nombre') or '').strip()
        if via_nombre:
            parts.append(('%s %s' % (via_tipo, via_nombre)).strip())
        zona_tipo = (data.get('zona_tipo') or '').strip()
        zona_codigo = (data.get('zona_codigo') or '').strip()
        if zona_tipo and zona_tipo != '-':
            parts.append(('%s %s' % (zona_codigo, zona_tipo)).strip())
        for key, label in (
                ('numero', 'Nro.'), ('interior', 'Int.'), ('lote', 'Lote'),
                ('dpto', 'Dpto.'), ('manzana', 'Mz.'), ('kilometro', 'Km.')):
            value = (data.get(key) or '').strip()
            if value and value != '-':
                parts.append('%s %s' % (label, value))
        return ', '.join(part for part in parts if part and part.strip() != '-')

    @api.model
    def _sunat_decolecta_parse_anexos(self, raw):
        """Devuelve la lista de anexos guardada en el campo JSON."""
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def _sunat_decolecta_get_anexos(self):
        self.ensure_one()
        return self._sunat_decolecta_parse_anexos(self.sunat_decolecta_anexos)

    def _sunat_decolecta_assign_vals(self, vals):
        """Aplica valores a un registro virtual (contexto ``onchange``)."""
        for name, value in vals.items():
            field = self._fields.get(name)
            if not field:
                continue
            if field.type == 'many2one' and isinstance(value, int):
                value = self.env[field.comodel_name].browse(value)
            setattr(self, name, value)
        return True

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _sunat_decolecta_is_cache_valid(self, numero):
        """Indica si la última consulta sigue vigente para este documento."""
        self.ensure_one()
        cache_days = self._sunat_decolecta_cache_days()
        if cache_days <= 0 or not self.sunat_decolecta_last_query:
            return False
        if (self.sunat_decolecta_last_query_vat or '') != numero:
            return False
        deadline = fields.Datetime.now() - timedelta(days=cache_days)
        return self.sunat_decolecta_last_query >= deadline

    def _sunat_decolecta_fetch_and_write(self, mode='full'):
        """Consulta la API y guarda el resultado en el contacto.

        :return: clave del tipo de documento consultado (``ruc``, ``dni``...).
        """
        self.ensure_one()
        numero = self._sunat_decolecta_normalize(self.vat)
        if not numero:
            raise UserError(_(
                'Ingresa el número de RUC, DNI o Carné de Extranjería antes de consultar.'))
        endpoint_key = self._sunat_decolecta_endpoint_key(numero)
        if not endpoint_key:
            raise UserError(_(
                'No se pudo determinar el tipo de documento. Selecciona "Tipo de '
                'documento" (RUC, DNI o Carné de Extranjería) o ingresa un número '
                'de 11 (RUC) u 8 (DNI) dígitos.'))
        self._sunat_decolecta_check_length(numero, endpoint_key)
        data = self._sunat_decolecta_request(numero, endpoint_key, mode=mode)
        vals = self._sunat_decolecta_prepare_vals(data, endpoint_key)
        if not self.l10n_latam_identification_type_id:
            doc_type = self._sunat_decolecta_guess_doc_type(numero)
            if doc_type:
                vals['l10n_latam_identification_type_id'] = doc_type.id
        self.write(vals)
        return endpoint_key

    def action_consultar_sunat(self):
        """Botón "Consultar SUNAT": consulta y guarda los datos del contacto."""
        self.ensure_one()
        numero = self._sunat_decolecta_normalize(self.vat)
        force = bool(self.env.context.get('sunat_decolecta_force'))
        if numero and not force and self._sunat_decolecta_is_cache_valid(numero):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Consulta reciente'),
                    'message': _(
                        'Los datos se consultaron el %(date)s. Usa "Forzar consulta" '
                        'si necesitas actualizarlos desde SUNAT.',
                        date=fields.Datetime.to_string(self.sunat_decolecta_last_query)),
                    'type': 'info',
                    'sticky': False,
                },
            }
        endpoint_key = self._sunat_decolecta_fetch_and_write(mode='full')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Consulta SUNAT realizada'),
                'message': _('Datos de %s cargados desde %s.') % (
                    DOC_LABEL.get(endpoint_key, 'documento'),
                    'SUNAT' if endpoint_key == 'ruc' else 'RENIEC'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_forzar_consulta_sunat(self):
        """Consulta ignorando la caché de consultas recientes."""
        self.ensure_one()
        return self.with_context(
            sunat_decolecta_force=True).action_consultar_sunat()

    def action_crear_direcciones_entrega(self):
        """Crea una dirección de entrega por cada anexo devuelto por SUNAT."""
        self.ensure_one()
        anexos = self._sunat_decolecta_get_anexos()
        if not anexos:
            raise UserError(_('Este contacto no tiene anexos de SUNAT para crear.'))
        peru = self.env['res.country'].search([('code', '=', 'PE')], limit=1)
        country = self.country_id or peru
        existing = {(child.street or '').strip().upper()
                    for child in self.child_ids if child.street}
        created = 0
        for anexo in anexos:
            direccion = (anexo.get('direccion') or '').strip()
            if not direccion or direccion.upper() in existing:
                continue
            district = self._sunat_decolecta_find_district(anexo)
            vals = {
                'parent_id': self.id,
                'type': 'delivery',
                'name': _('Anexo %s') % direccion[:60],
                'street': direccion,
                'country_id': country.id if country else False,
                'company_type': 'company' if self.is_company else 'person',
            }
            if district:
                vals['l10n_pe_district'] = district.id
                city = district.city_id
                if city:
                    vals['city_id'] = city.id
                    if city.state_id:
                        vals['state_id'] = city.state_id.id
            self.env['res.partner'].create(vals)
            existing.add(direccion.upper())
            created += 1
        if created:
            message = _('Se crearon %(count)s direcciones de entrega.', count=created)
        else:
            message = _('Todas las direcciones de entrega ya existían.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Anexos SUNAT'),
                'message': message,
                'type': 'success' if created else 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }


    @api.onchange('vat', 'l10n_latam_identification_type_id')
    def _onchange_vat_sunat_decolecta(self):
        """Autocompleta el contacto al escribir el número de documento."""
        numero = self._sunat_decolecta_normalize(self.vat)
        if len(numero) < 8:
            return
        if not self.l10n_latam_identification_type_id:
            # Solo inferimos el tipo cuando el número ya es inequívoco (RUC de
            # 11 dígitos). Para DNI/CE el usuario elige el tipo de documento,
            # así no se consulta RENIEC mientras se escribe un RUC.
            if len(numero) != 11:
                return
            doc_type = self._sunat_decolecta_guess_doc_type(numero)
            if doc_type:
                self.l10n_latam_identification_type_id = doc_type
        endpoint_key = self._sunat_decolecta_endpoint_key(numero)
        if not endpoint_key:
            return
        expected = EXPECTED_LENGTH.get(endpoint_key)
        if expected and len(numero) != expected:
            return
        if not self._sunat_decolecta_auto_query():
            return
        if self.env.context.get('sunat_decolecta_skip'):
            return
        mode = self._sunat_decolecta_auto_query_mode() if endpoint_key == 'ruc' else 'full'
        try:
            data = self._sunat_decolecta_request(numero, endpoint_key, mode=mode)
            vals = self._sunat_decolecta_prepare_vals(data, endpoint_key)
            self._sunat_decolecta_assign_vals(vals)
        except UserError as error:
            return {
                'warning': {
                    'title': _('No se pudo consultar SUNAT'),
                    'message': str(error),
                },
            }
        return {'warning': {
            'title': _('Datos cargados desde %s') % (
                'SUNAT' if endpoint_key == 'ruc' else 'RENIEC'),
            'message': _('Revisa la información antes de guardar el contacto.'),
        }}
