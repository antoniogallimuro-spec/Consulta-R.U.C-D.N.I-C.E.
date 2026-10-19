# SUNAT / Decolecta (Odoo 18)

Integración con la localización peruana (`l10n_pe`) y la API de
[Decolecta](https://decolecta.com): consulta de **RUC (SUNAT)** y **DNI
(RENIEC)**, **tipo de cambio SUNAT/SBS**, **comisiones de AFP**, control de
consumo y validación de RUC al facturar.

## Endpoints utilizados

| Función | Endpoint Decolecta | Estado |
|---------|--------------------|--------|
| Datos completos de RUC | `/v1/sunat/ruc/full` | ✅ |
| Datos básicos de RUC | `/v1/sunat/ruc` | ✅ |
| DNI | `/v1/reniec/dni` | ✅ |
| Tipo de cambio SUNAT | `/v1/tipo-cambio/sunat` | ✅ |
| Tipo de cambio SBS promedio | `/v1/tipo-cambio/sbs/average` | ✅ |
| Tipo de cambio SBS contable | `/v1/tipo-cambio/sbs/accounting` | ✅ |
| Comisiones AFP | `/v1/afp/comisiones` | ✅ |
| Carné de Extranjería | `/v1/reniec/ce` | ❌ no existe (404) |

> Decolecta no ofrece consulta de Carné de Extranjería: la API responde
> `404 {"message": "MicroService Not found"}`. El módulo lo informa y pide
> ingresar los datos manualmente.

## Datos que completa el contacto

| Documento | Datos copiados |
|-----------|----------------|
| RUC (11 dígitos) | razón social, nombre comercial, dirección y dirección estructurada, ubigeo, distrito / provincia / departamento (`l10n_pe_district`, `city_id`, `state_id`), estado, condición, tipo de contribuyente, actividad económica, N° de trabajadores, sistema de facturación y contabilidad, comercio exterior, agente de retención, buen contribuyente y locales anexos |
| DNI (8 dígitos) | nombre completo, tipo de documento, país |

El tipo de documento se guarda en `l10n_latam_identification_type_id` (tipos
oficiales de `l10n_pe`), por lo que los datos quedan listos para Factura, Boleta
y Guía de remisión sin campos duplicados.

Campos añadidos a `res.partner`:

* `sunat_decolecta_commercial_name`, `sunat_decolecta_state`,
  `sunat_decolecta_condition`
* `sunat_decolecta_company_type`, `sunat_decolecta_economic_activity`,
  `sunat_decolecta_workers`, `sunat_decolecta_billing_type`,
  `sunat_decolecta_accounting_type`, `sunat_decolecta_foreign_trade`
* `sunat_decolecta_is_withholding_agent`, `sunat_decolecta_is_good_taxpayer`
* `sunat_decolecta_ubigeo`, `sunat_decolecta_address_detail`
* `sunat_decolecta_anexos` (JSON), `sunat_decolecta_anexos_html`,
  `sunat_decolecta_anexos_count`
* `sunat_decolecta_last_query`, `sunat_decolecta_last_query_vat`

Se muestran en la pestaña *Internal Notes* con los grupos **Datos SUNAT** y
**Dirección y anexos SUNAT**, con insignias para *Agente de retención* y *Buen
contribuyente*. El botón **Crear direcciones de entrega** genera un contacto
`type = delivery` por cada anexo (omite los que ya existen).

### Respuesta real de la API (verificada en producción, 19/10/2026)

* `/v1/sunat/ruc` (`ruc_basic`) devuelve: `razon_social`, `numero_documento`,
  `estado`, `condicion`, `direccion`, `ubigeo`, `departamento`, `provincia`,
  `distrito`, `via_tipo`, `via_nombre`, `numero`, `interior`, `kilometro`,
  `manzana`, `lote`, `dpto`, `zona_tipo`, `zona_codigo`,
  `es_buen_contribuyente`, `es_agente_retencion` y `locales_anexos`.
* `/v1/sunat/ruc/full` (`ruc_full`) añade `nombre_comercial`,
  `actividad_economica`, `tipo_de_contribuyente`, `numero_de_trabajadores`,
  `sistema_de_facturacion`, `sistema_de_contabilidad`, `comercio_exterior` y
  `actividad_comercio_exterior`.
* `locales_anexos[i]` trae `direccion`, `ubigeo`, `departamento`, `provincia` y
  `distrito`. La calle del anexo suele venir **sin tipo de vía ni número**
  (`"NRO 495"`), por eso la dirección de la matriz se compone con
  `via_tipo` + `via_nombre` + `numero` + `interior` (`"CAL. MORELLI, Nro. 181,
  Int. P-2"`).
* `/v1/tipo-cambio/sunat` devuelve `buy`, `sell`, `date`, `source`, `price` y
  `currency`. El módulo guarda `1 / sell` en `res.currency.rate` (verificado:
  venta 3.431 → `rate` 0.291460…, `100 USD = 343.1 PEN`).
* `/v1/afp/comisiones` devuelve 4 AFP (HABITAT, INTEGRA, PRIMA, PROFUTURO) con
  `comision_sobre_flujo`, `comision_mixta_sobre_flujo`,
  `comision_mixta_sobre_saldo`, `comision_anual_sobre_saldo`, `prima_de_seguro`,
  `aporte_obligatorio` y `remuneracion_maxima_asegurable` (en porcentaje).
* `/v1/reniec/dni` no se ejecutó en la prueba de humo (para no consumir
  consultas adicionales); su respuesta está cubierta por el mismo
  `_call` y el manejo defensivo de campos.


## Tipo de cambio

* Fuentes: **SUNAT** (compra/venta), **SBS promedio** y **SBS contable**.
* Se guarda en `res.currency.rate` de la compañía raíz con la semántica de Odoo
  (`rate` = unidades de moneda extranjera por 1 unidad de la compañía); el valor
  de SUNAT se invierte antes de guardarlo. Las tasas se leen de
  `company.root_id`, que es lo que usa `res.currency._convert`.
* **Cron diario** (`SUNAT Decolecta: tipo de cambio diario`): registra la tasa
  del día solo si esa fecha aún no tiene tasa, así no consume consultas de más.
  Se puede desactivar en Ajustes (`sunat_decolecta.rate_cron_enabled`).
* **Wizard** *Actualizar tipo de cambio*: permite un rango de fechas, omitir
  fines de semana y sobrescribir tasas existentes. Muestra un resumen y una
  verificación `1 USD = X PEN` al final.

## Comisiones de AFP

* Modelo `sunat.afp.comision` con comisión fija, sobre flujo, mixta (flujo y
  saldo), anual sobre saldo, prima de seguro, aporte obligatorio y remuneración
  máxima asegurable por AFP y periodo.
* Botón **Actualizar comisiones AFP** en Ajustes y cron diario que carga el mes
  anterior solo si aún no está registrado (1 consulta al mes como máximo).
* Menú: *Ajustes > Técnico > SUNAT / Decolecta > Comisiones AFP*.

## Consumo, cuota y caché

* Cada consulta a la API se registra en `sunat.decolecta.log` (servicio,
  documento enmascarado, contacto, usuario, código HTTP, duración y error).
* Ajustes muestra *Consumo del mes* (`N de cuota`) y permite definir la cuota
  mensual (por defecto **1000**, el plan gratuito de Decolecta).
* **Caché**: el botón *Consultar SUNAT* reutiliza los datos si el contacto fue
  consultado hace menos de `sunat_decolecta.cache_days` (30 por defecto) y el
  documento no cambió. El botón **Forzar consulta** ignora la caché.
* La consulta masiva (acción *Consulta masiva SUNAT / RENIEC* en la lista de
  contactos) muestra cuántas consultas se van a consumir y bloquea la ejecución
  si supera la cuota disponible.

## Validación de RUC al publicar comprobantes

`account.move._post` revisa el estado SUNAT guardado en el contacto:

* `off`: no valida.
* `warn` (por defecto): deja una nota en el chatter del comprobante.
* `block`: impide publicar si el RUC está **BAJA DE OFICIO**, **BAJA DEFINITIVA**,
  **SUSPENSION TEMPORAL** o la condición es **NO HABIDO**.

Nunca consulta la API al publicar. Para omitir la validación en un caso puntual:

```python
move.with_context(sunat_decolecta_skip_validation=True)._post()
```

## Configuración

1. Ajustes > **SUNAT / Decolecta**.
2. Pega el **token Bearer** de tu cuenta de Decolecta y usa **Probar token**.
3. Ajusta el detalle de la consulta automática (básico o completo), la caché y
   la cuota mensual.
4. Configura la fuente y el precio del tipo de cambio y, si lo deseas, el cron
   diario.

Parámetros del sistema usados:

* `sunat_decolecta.api_token` — token Bearer.
* `sunat_decolecta.auto_query` — `True`/`False`: consulta en el onchange.
* `sunat_decolecta.auto_query_mode` — `basic`/`full`.
* `sunat_decolecta.cache_days` — días de vigencia de una consulta.
* `sunat_decolecta.monthly_quota` — consultas incluidas en el plan.
* `sunat_decolecta.rate_source` / `rate_price` / `rate_currency` /
  `rate_cron_enabled` — tipo de cambio.
* `sunat_decolecta.invoice_validation` — `off`/`warn`/`block`.


## Uso

* **Automático**: escribe el RUC de 11 dígitos (o selecciona primero el tipo de
  documento RUC/DNI y luego el número). Al completar la longitud se consulta la
  API y se rellenan los campos (modo básico o completo según Ajustes).
* **Manual**: botón **Consultar SUNAT** junto al campo `vat`. Con caché vigente
  reutiliza los datos; **Forzar consulta** vuelve a llamar a la API.
* **Masivo**: en la lista de contactos, acción *Consulta masiva SUNAT / RENIEC*
  (solo administradores). Sin seleccionar contactos toma automáticamente los que
  tienen RUC/DNI y aún no fueron consultados.

La consulta automática nunca bloquea el guardado: si el token es inválido, se
agotó la cuota (429) o hay un error de red, se muestra un aviso y el usuario
decide. El botón manual sí muestra el error como excepción.

## Notas técnicas

* Depende de `requests`, ya incluido en la imagen oficial de Odoo.
* `timeout` de 15 segundos con un reintento ante lentitud.
* El `onchange` se puede silenciar con `with_context(sunat_decolecta_skip=True)`
  (por ejemplo en importaciones o tests).
* No se registra el token ni el número de documento completo: el log guarda el
  documento enmascarado (`20******013`).
* Al publicar comprobantes se puede omitir la validación con
  `with_context(sunat_decolecta_skip_validation=True)`.
* Menú técnico: *Ajustes > Técnico > SUNAT / Decolecta* (consumo de la API y
  comisiones AFP).

## Verificación rápida en el servidor

```bash
# versión instalada y estado
docker exec odoo-db2 psql -U odoo -d tkdb -t -A \
  -c "select latest_version, state from ir_module_module where name='sunat_decolecta'"

# consumo registrado por endpoint
docker exec odoo-db2 psql -U odoo -d tkdb -t -A \
  -c "select endpoint_key, success, status_code, count(*) from sunat_decolecta_log group by 1,2,3"

# crons del módulo
docker exec odoo-db2 psql -U odoo -d tkdb -t -A -F '|' \
  -c "select s.name->>'en_US', c.active, c.interval_type, c.nextcall from ir_cron c join ir_act_server s on s.id = c.ir_actions_server_id where s.name->>'en_US' like 'SUNAT Decolecta%'"
```

## Licencia

LGPL-3.
