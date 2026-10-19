# -*- coding: utf-8 -*-
import logging
import time

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# URL base de la API de Decolecta (https://decolecta.com)
DECOLECTA_BASE_URL = 'https://api.decolecta.com'

# Endpoints documentados en https://decolecta.gitbook.io/docs
DECOLECTA_ENDPOINTS = {
    'ruc_full': '/v1/sunat/ruc/full',
    'ruc_basic': '/v1/sunat/ruc',
    'dni': '/v1/reniec/dni',
    'ce': '/v1/reniec/ce',
    'tc_sunat': '/v1/tipo-cambio/sunat',
    'tc_sbs_average': '/v1/tipo-cambio/sbs/average',
    'tc_sbs_accounting': '/v1/tipo-cambio/sbs/accounting',
    'afp': '/v1/afp/comisiones',
}

# Decolecta no publica (ni responde) un endpoint de Carné de Extranjería:
# /v1/reniec/ce devuelve 404 "MicroService Not found". Se deja el indicador
# para poder activarlo sin tocar código si el proveedor lo habilita.
DECOLECTA_CE_SUPPORTED = False

DOC_LABELS = {
    'ruc_full': 'RUC',
    'ruc_basic': 'RUC',
    'dni': 'DNI',
    'ce': 'Carné de Extranjería',
}

TIMEOUT = 15


class SunatDecolectaApi(models.AbstractModel):
    _name = 'sunat.decolecta.api'
    _description = 'Cliente de la API de Decolecta'

    # ------------------------------------------------------------------
    # Parámetros
    # ------------------------------------------------------------------
    @api.model
    def _get_param(self, key, default=None):
        value = self.env['ir.config_parameter'].sudo().get_param(key)
        if value is None or value is False or value == '':
            return default
        return value

    @api.model
    def _get_int_param(self, key, default=0):
        value = self._get_param(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @api.model
    def _get_bool_param(self, key, default=False):
        value = self._get_param(key, default)
        return str(value).strip().lower() in ('1', 'true', 'yes', 'on')

    @api.model
    def _get_token(self, raise_if_missing=True):
        """Devuelve el token Bearer configurado en Ajustes o en parámetros."""
        token = (self._get_param('sunat_decolecta.api_token', '') or '').strip()
        if not token and raise_if_missing:
            raise UserError(_(
                'No se ha configurado el token de Decolecta.\n'
                'Ve a Ajustes > SUNAT / Decolecta y pega tu token '
                '(o define el parámetro del sistema "sunat_decolecta.api_token").'
            ))
        return token

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------
    @api.model
    def _mask_document(self, numero):
        """Enmascara el número de documento para el registro de consumo."""
        numero = (numero or '').strip()
        if not numero:
            return ''
        if len(numero) <= 4:
            return '*' * len(numero)
        return '%s%s%s' % (numero[:2], '*' * (len(numero) - 5), numero[-3:])

    @api.model
    def _build_url(self, endpoint_key):
        path = DECOLECTA_ENDPOINTS.get(endpoint_key)
        if not path:
            raise UserError(_(
                'El servicio "%s" no está soportado por la integración.'
            ) % endpoint_key)
        return DECOLECTA_BASE_URL + path

    @api.model
    def _error_message(self, endpoint_key, status, body, raw_text):
        message = ''
        if isinstance(body, dict):
            message = body.get('message') or body.get('error') or ''
        if status == 401:
            return _(
                'Decolecta rechazó el token (401). Verifícalo en '
                'Ajustes > SUNAT / Decolecta.')
        if status == 403:
            return _('Tu plan de Decolecta no permite esta consulta (403).')
        if status == 404:
            if endpoint_key == 'ce':
                return _(
                    'Decolecta no ofrece consulta de Carné de Extranjería '
                    '(el servicio no existe en la API). Ingresa los nombres y '
                    'apellidos manualmente.')
            return _('El documento no fue encontrado en %s (404).') % (
                'SUNAT' if endpoint_key.startswith('ruc') else 'RENIEC')
        if status == 422:
            return _('Decolecta: %s') % (message or _('documento no válido'))
        if status == 429:
            return _(
                'Se agotó la cuota de consultas de Decolecta (429). Revisa tu '
                'plan o desactiva la consulta automática en '
                'Ajustes > SUNAT / Decolecta.')
        if status >= 500:
            return _(
                'Decolecta no está disponible en este momento (error %s). '
                'Inténtalo más tarde.') % status
        if status >= 400:
            if message:
                return _('Decolecta: %s (error %s)') % (message, status)
            return _('Decolecta devolvió el error %s: %s') % (
                status, (raw_text or '')[:200])
        return _('Respuesta inesperada de Decolecta (error %s).') % status

    # ------------------------------------------------------------------
    # Registro de consumo
    # ------------------------------------------------------------------
    @api.model
    def _log_call(self, endpoint_key, status, success, duration_ms,
                  document_number=None, partner=None, error_message=None):
        try:
            partner_id = partner.id if partner and isinstance(partner.id, int) else False
            self.env['sunat.decolecta.log'].sudo().create({
                'name': DECOLECTA_ENDPOINTS.get(endpoint_key, endpoint_key),
                'endpoint_key': endpoint_key,
                'document_type': DOC_LABELS.get(endpoint_key, endpoint_key),
                'document_number': self._mask_document(document_number),
                'partner_id': partner_id or False,
                'company_id': self.env.company.id,
                'user_id': self.env.uid,
                'status_code': status,
                'success': success,
                'duration_ms': duration_ms,
                'error_message': error_message or False,
            })
        except Exception:  # pragma: no cover - el log nunca debe romper la consulta
            _logger.exception('SUNAT Decolecta: no se pudo registrar el consumo')

    # ------------------------------------------------------------------
    # Llamada HTTP
    # ------------------------------------------------------------------
    @api.model
    def _call(self, endpoint_key, params=None, document_number=None,
              partner=None, log=True):
        """Consulta un endpoint de Decolecta y devuelve el JSON de respuesta.

        :param endpoint_key: clave de ``DECOLECTA_ENDPOINTS``.
        :param params: querystring de la consulta.
        :param document_number: documento consultado (para el log).
        :param partner: ``res.partner`` relacionado (para el log).
        :param log: si es ``False`` no registra la llamada en el log.
        :raises UserError: ante token inválido, cuota agotada, documento no
            encontrado o cualquier error de red/servidor.
        """
        if endpoint_key == 'ce' and not DECOLECTA_CE_SUPPORTED:
            raise UserError(_(
                'Decolecta no ofrece consulta de Carné de Extranjería: la API '
                'no tiene ese servicio. Ingresa los nombres y apellidos del '
                'contacto manualmente.'))

        token = self._get_token()
        url = self._build_url(endpoint_key)
        headers = {
            'Authorization': 'Bearer %s' % token,
            'Accept': 'application/json',
        }
        params = params or {}

        started = time.monotonic()
        try:
            try:
                response = requests.get(url, params=params, headers=headers,
                                        timeout=TIMEOUT)
            except requests.exceptions.Timeout:
                # Un único reintento ante lentitud puntual del proveedor.
                _logger.warning('SUNAT Decolecta: timeout en %s, reintentando',
                                endpoint_key)
                response = requests.get(url, params=params, headers=headers,
                                        timeout=TIMEOUT * 2)
        except requests.exceptions.Timeout:
            duration_ms = int((time.monotonic() - started) * 1000)
            if log:
                self._log_call(endpoint_key, 0, False, duration_ms,
                               document_number, partner, 'timeout')
            raise UserError(_(
                'Tiempo de espera agotado al consultar Decolecta. '
                'Inténtalo nuevamente.'))
        except requests.exceptions.RequestException as error:
            duration_ms = int((time.monotonic() - started) * 1000)
            if log:
                self._log_call(endpoint_key, 0, False, duration_ms,
                               document_number, partner, str(error))
            raise UserError(_('No se pudo conectar con Decolecta: %s') % error)

        duration_ms = int((time.monotonic() - started) * 1000)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
        success = 200 <= status < 300 and isinstance(body, (dict, list))
        error_message = False
        if not success:
            error_message = self._error_message(
                endpoint_key, status, body, response.text)
        if log:
            self._log_call(endpoint_key, status, success, duration_ms,
                           document_number, partner, error_message)

        if not success:
            raise UserError(error_message)
        if isinstance(body, dict) and body.get('error') and not body.get('razon_social'):
            raise UserError(_('Decolecta: %s') % (
                body.get('message') or body.get('error')))
        return body

    # ------------------------------------------------------------------
    # Diagnóstico
    # ------------------------------------------------------------------
    @api.model
    def _test_token(self):
        """Valida el token con una consulta liviana de tipo de cambio."""
        data = self._call('tc_sunat', {})
        if not isinstance(data, dict) or not data.get('sell_price'):
            raise UserError(_('Decolecta respondió sin tipo de cambio.'))
        return data

    @api.model
    def _month_usage(self):
        return self.env['sunat.decolecta.log'].sudo()._month_usage()

    @api.model
    def _monthly_quota(self):
        return self._get_int_param('sunat_decolecta.monthly_quota', 1000)
