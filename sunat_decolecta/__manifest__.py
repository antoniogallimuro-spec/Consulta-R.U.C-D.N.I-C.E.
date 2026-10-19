# -*- coding: utf-8 -*-
{
    'name': 'SUNAT / Decolecta - RUC, DNI, tipo de cambio y AFP',
    'version': '18.0.1.4.0',
    'category': 'Sales/Sales',
    'summary': 'Consulta RUC y DNI, tipo de cambio SUNAT/SBS, comisiones AFP y validación de RUC vía Decolecta',
    'description': """
SUNAT / Decolecta - RUC, DNI, tipo de cambio y AFP
=================================================

Integra la API de Decolecta (https://decolecta.com) con Odoo:

* RUC (SUNAT): razón social, nombre comercial, dirección estructurada, ubigeo,
  distrito / provincia / departamento, estado y condición del contribuyente,
  actividad económica, tipo de contribuyente, trabajadores, sistemas de
  facturación y contabilidad, comercio exterior, agente de retención, buen
  contribuyente y locales anexos (con opción de crear direcciones de entrega).
* DNI (RENIEC): nombre completo del titular.
* Tipo de cambio: SUNAT (compra/venta), SBS promedio y SBS contable. Se registra
  en ``res.currency.rate`` y puede actualizarse a diario con un cron.
* Comisiones de AFP (SBS): comisión sobre flujo, mixta, anual sobre saldo, prima
  de seguro, aporte obligatorio y remuneración máxima asegurable por periodo.
* Control de consumo: registro de cada consulta, cuota mensual configurable y
  caché de consultas para no gastar créditos innecesariamente.
* Validación de RUC al publicar comprobantes (avisar o bloquear) usando los datos
  ya guardados en el contacto, sin consumir consultas.

El Carné de Extranjería no está disponible en la API de Decolecta: el endpoint
``/v1/reniec/ce`` no existe, por lo que la integración informa al usuario y pide
ingresar los datos manualmente.

Configuración: Ajustes > SUNAT / Decolecta (token Bearer de Decolecta). El token
también se puede definir en el parámetro del sistema
``sunat_decolecta.api_token``.
    """,
    'author': 'tk-peru.com',
    'website': 'https://tk-peru.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'base_vat',
        'contacts',
        'l10n_pe',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/decolecta_log_views.xml',
        'views/res_partner_views.xml',
        'views/res_config_settings_views.xml',
        'views/decolecta_rate_wizard_views.xml',
        'views/decolecta_batch_views.xml',
        'views/afp_comision_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

