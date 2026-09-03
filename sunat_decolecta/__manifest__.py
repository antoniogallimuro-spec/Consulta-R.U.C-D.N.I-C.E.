# -*- coding: utf-8 -*-
{
    'name': 'Sunat Decolecta Integration',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Consulta RUC, DNI y CE desde Sunat vía Decolecta',
    'description': """
        Módulo para consultar datos de SUNAT (RUC, DNI, CE) 
        usando la API de Decolecta y autocompletar contactos en Odoo.
    """,
    'author': 'Tu Nombre',
    'website': 'https://tusitio.com',
    'depends': ['base', 'base_vat'],
    'data': [
        'views/res_partner_views.xml',
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}