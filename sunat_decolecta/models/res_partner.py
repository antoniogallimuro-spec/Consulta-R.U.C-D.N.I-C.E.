# -*- coding: utf-8 -*-
import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = 'res.partner'

    document_type = fields.Selection(
        selection=[
            ('ruc', 'RUC'),
            ('dni', 'DNI'),
            ('ce', 'Carné de Extranjería'),
        ],
        string='Tipo de Documento',
        default='dni',
        help='Selecciona el tipo de documento para la consulta'
    )

    def _get_decolecta_token(self):
        """Obtiene el token de Decolecta desde los parámetros del sistema."""
        token = self.env['ir.config_parameter'].sudo().get_param(
            'sunat_decolecta.api_token'
        )
        if not token:
            raise ValidationError(_(
                'No se ha configurado el token de Decolecta. '
                'Ve a Ajustes > Técnico > Parámetros del Sistema y crea '
                'sunat_decolecta.api_token con tu token.'
            ))
        return token

    def _consultar_sunat_decolecta(self, numero, tipo):
        """Consulta la API de Decolecta según el tipo de documento."""
        token = self._get_decolecta_token()
        
        if tipo == 'ruc':
            url = f'https://api.decolecta.com/v1/sunat/ruc?numero={numero}'
        elif tipo == 'dni':
            url = f'https://api.decolecta.com/v1/reniec/dni?numero={numero}'
        elif tipo == 'ce':
            raise ValidationError(_(
                'El endpoint para Carné de Extranjería (CE) no está disponible '
                'en la documentación de Decolecta. Contacta con su soporte.'
            ))
        else:
            raise ValidationError(_('Tipo de documento no soportado.'))

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        }

        try:
            _logger.info(f'Consultando Decolecta: {url}')
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f'Error al consultar Decolecta: {e}')
            raise ValidationError(_(f'Error al consultar la API de Decolecta: {str(e)}'))

    def _actualizar_desde_decolecta(self, data, tipo):
        """Actualiza los campos del contacto con los datos de Decolecta."""
        if tipo == 'ruc':
            self.name = data.get('razon_social', self.name)
            self.vat = data.get('numero_documento', self.vat)
            calle = data.get('dirección', '')
            distrito = data.get('distrito', '')
            provincia = data.get('provincia', '')
            departamento = data.get('departamento', '')
            if calle:
                self.street = calle
            if distrito or provincia or departamento:
                self.city = f"{distrito}, {provincia}, {departamento}".strip(', ')

        elif tipo == 'dni':
            nombres = data.get('first_name', '')
            apellido_paterno = data.get('first_last_name', '')
            apellido_materno = data.get('second_last_name', '')
            nombre_completo = data.get('full_name', '')
            
            if nombre_completo:
                self.name = nombre_completo
            elif apellido_paterno and apellido_materno and nombres:
                self.name = f"{apellido_paterno} {apellido_materno} {nombres}".strip()
            
            self.vat = data.get('document_number', self.vat)

    @api.onchange('vat')
    def _onchange_vat_consulta_sunat(self):
        """Cuando el usuario ingresa un VAT, consulta automáticamente."""
        if not self.vat:
            return
        
        numero = self.vat.strip().replace('-', '').replace(' ', '')
        if not numero:
            return
        
        if len(numero) == 11:
            tipo = 'ruc'
        elif len(numero) == 8:
            tipo = 'dni'
        else:
            tipo = 'ce'
            return {
                'warning': {
                    'title': _('Tipo de documento no reconocido'),
                    'message': _(
                        'El número ingresado no corresponde a un RUC (11 dígitos) '
                        'ni a un DNI (8 dígitos).'
                    ),
                }
            }
        
        try:
            data = self._consultar_sunat_decolecta(numero, tipo)
            if data:
                self._actualizar_desde_decolecta(data, tipo)
                return {
                    'warning': {
                        'title': _('¡Datos cargados!'),
                        'message': _('Los datos de SUNAT se han cargado correctamente.'),
                    }
                }
        except ValidationError as e:
            return {
                'warning': {
                    'title': _('Error en la consulta'),
                    'message': str(e),
                }
            }

    def action_consultar_sunat(self):
        """Acción para el botón de consulta manual."""
        self.ensure_one()
        if not self.vat:
            raise ValidationError(_('Debes ingresar un número de RUC, DNI o CE.'))
        
        numero = self.vat.strip().replace('-', '').replace(' ', '')
        if len(numero) == 11:
            tipo = 'ruc'
        elif len(numero) == 8:
            tipo = 'dni'
        else:
            tipo = 'ce'
        
        data = self._consultar_sunat_decolecta(numero, tipo)
        if data:
            self._actualizar_desde_decolecta(data, tipo)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('¡Éxito!'),
                    'message': _('Datos cargados desde SUNAT correctamente.'),
                    'type': 'success',
                    'sticky': False,
                }
            }