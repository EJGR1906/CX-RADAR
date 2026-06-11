# Configuración de Grafana Cloud para CX-Radar

## Alcance

Esta guía implementa la primera capa de Grafana Cloud para la línea sintética HTTP actual únicamente.

Para la línea genérica de pruebas de velocidad, usa `docs/observability/grafana-speed-test-setup.md` y mantiene sus dashboards y alertas separados de la carpeta HTTP.

Los activos agregados en este repositorio son:

1. `grafana/dashboards/qoe-national-global.json` — Vista Global Nacional (vista nacional multi-sonda con geomapa)
2. `grafana/dashboards/qoe-probe-detail.json` — Detalle por Sonda (drilldown por sonda con métricas completas)
3. `grafana/queries/qoe-http-flux-examples.md`

Están alineados con estas mediciones actuales:

1. `qoe_http_check`
2. `qoe_real_metrics`
3. `qoe_probe_run`

## Conectar InfluxDB Cloud a Grafana Cloud

1. Abre Grafana Cloud.
2. Ve a Connections y luego a Data sources.
3. Elige Add data source.
4. Selecciona InfluxDB.
5. En Query language, elige `Flux`.
6. En URL, usa la URL base de `config/probe-catalog.json`, actualmente `https://us-east-1-1.aws.cloud2.influxdata.com`.
7. Configura Organization con el nombre real de tu organización de Influx.
8. Configura Default bucket a `qoe_metrics`, o a tu bucket final si lo renombraste.
9. Pega un token de API de InfluxDB con acceso de lectura al bucket.
10. Haz clic en Save & test.

Valores predeterminados recomendados para la fuente de datos de Grafana:

1. Min time interval: `5m`
2. HTTP method: `POST`
3. Custom timeout: `30s`

## Importar los paneles

Se proporcionan dos dashboards. Implóralos en orden:

### 1. Vista Global Nacional (`qoe-national-global.json`)

1. En Grafana Cloud, ve a Dashboards.
2. Haz clic en New y luego en Import.
3. Sube `grafana/dashboards/qoe-national-global.json`.
4. Selecciona tu fuente de datos de InfluxDB Cloud cuando se te solicite.
5. Importa.

Este dashboard responde preguntas a nivel nacional:

1. ¿Cuál es la salud actual de cada sonda en Venezuela?
2. ¿Hay patrones regionales en latencia o disponibilidad?
3. ¿Dónde están ubicadas físicamente las sondas (vista geomapa)?

### 2. Detalle por Sonda (`qoe-probe-detail.json`)

1. En Grafana Cloud, ve a Dashboards.
2. Haz clic en New y luego en Import.
3. Sube `grafana/dashboards/qoe-probe-detail.json`.
4. Selecciona tu fuente de datos de InfluxDB Cloud cuando se te solicite.
5. Importa.

Este dashboard responde preguntas de drilldown por sonda:

1. ¿Están los endpoints alcanzables ahora desde esta sonda?
2. ¿Los servicios están más lentos de lo normal?
3. ¿El problema es específico de un servicio, un endpoint o una sonda?
4. ¿La sonda misma está sana y sigue escribiendo en InfluxDB?

> **Nota:** La variable `Sonda` en este dashboard te permite cambiar entre sondas. El dashboard Vista Global Nacional intencionalmente no tiene filtro de sonda; siempre muestra todas las sondas.

## Estructura del dashboard

### Vista Global Nacional (`qoe-national-global.json`)

1. **Mapa de Sondas** (geomap): ubicaciones de las sondas codificadas por color según el estado actual de disponibilidad.
2. **Disponibilidad por Sonda** (bar gauge): % de disponibilidad por sonda.
3. **Latencia por Sonda** (bar gauge): latencia media por sonda.
4. **Velocidad de Descarga por Sonda** (bar gauge): velocidad media de descarga por sonda.
5. **Velocidad de Subida por Sonda** (bar gauge): velocidad media de subida por sonda.
6. **Estado por Sonda** (state timeline): disponibilidad por sonda a lo largo del tiempo.
7. **Latencia a lo largo del tiempo** (time series): tendencia de latencia por sonda.
8. **Tabla Nacional de QoE** (table): captura más reciente de todas las sondas con métricas completas.

### Detalle por Sonda (`qoe-probe-detail.json`)

Filtrado por la variable `Sonda` (`probe_id`).

1. **Disponibilidad** (stat): % de disponibilidad actual para la sonda seleccionada.
2. **Últimas Fallas** (stat): recuento de fallas más reciente de `qoe_probe_run`.
3. **Estado de Escritura Influx** (stat): estado más reciente de `write_succeeded`.
4. **Disponibilidad por Servicio** (time series): tendencia de disponibilidad agrupada por servicio.
5. **Latencia Total por Servicio** (time series): latencia media por servicio.
6. **Velocidad de Descarga** (time series): Mbps de descarga por servicio a lo largo del tiempo.
7. **Velocidad de Subida** (time series): Mbps de subida por servicio a lo largo del tiempo.
8. **Snapshot de Endpoints** (table): lectura más reciente por endpoint con campos completos.
9. **Fallas por Ciclo** (time series): recuento de fallas por ejecución de sonda.
10. **Duración de Ciclo** (time series): tendencia de duración de ejecución de `qoe_probe_run`.
11. **RPM Promedio** (bar gauge): solicitudes por minuto por servicio.
12. **Disponibilidad por Servicio (barra)** (bar gauge): % de disponibilidad actual por servicio.
13. **Timeline de Estado** (state timeline): disponibilidad por servicio a lo largo del tiempo.

## Plantillas y filtrado

El dashboard **Vista Global** no tiene variables de plantilla; siempre muestra todas las sondas.

El dashboard **Detalle por Sonda** incluye:

1. `probe_id` — selecciona una sola sonda; poblado desde `qoe_probe_run`.

El filtrado multidimensional se logra usando `filter()` de Flux dentro de las consultas en lugar de variables de Grafana para evitar problemas de cardinalidad.

## Alertas recomendadas

Crea estas alertas en Grafana Cloud a partir de las consultas Flux en `grafana/queries/qoe-http-flux-examples.md`.

### Alerta 1: Lentitud sostenida de endpoint

Objetivo: detectar una degradación significativa de latencia antes de fallos totales.

1. Query: `Alert Query: Sustained Slowdown`
2. Agrupar por: `probe_id`, `service`, `endpoint_name`
3. Condición: mean `time_total_ms > 2500`
4. For: `15m`
5. Evaluate every: `5m`

Control de ruido:

1. Usa `for 15m` para que una respuesta lenta no genere un paging inmediato.
2. Empieza en `2500 ms` para páginas de inicio de streaming público, luego ajusta tras tener datos de línea base.

### Alerta 2: Degradación de alcanzabilidad de endpoint

Objetivo: detectar pérdida parcial o total de disponibilidad sin esperar un corte completo.

1. Query: `Alert Query: Reachability Failure Ratio`
2. Agrupar por: `probe_id`, `service`, `endpoint_name`
3. Condición: mean `available < 0.8`
4. For: `15m`
5. Evaluate every: `5m`

Interpretación:

1. `1.0` significa totalmente sano en la ventana.
2. `0.8` significa que el 20 por ciento de las comprobaciones fallaron en la ventana de alerta.

### Alerta 3: Falla de escritura de la sonda

Objetivo: separar la falla de ingestión de la degradación del servicio.

1. Query: `Alert Query: Probe Write Failure`
2. Agrupar por: `probe_id`
3. Condición: last `write_succeeded < 1`
4. For: `10m`
5. Evaluate every: `5m`

Control de ruido:

1. Enruta esta alerta de forma diferente a las alertas de endpoint porque es un problema de pipeline de observabilidad.
2. Si más adelante ejecutas múltiples sondas, mantén la alerta agrupada por sonda para que un host no enmascare a otro.

## Notas operativas

1. Mantén la línea HTTP sintética en su propia carpeta de dashboards. No la mezcles con futuros paneles dedicados de throughput o `qoe_page_audit`.
2. Evita alertar sobre muestras individuales para endpoints de internet público.
3. Usa las dimensiones `service` y `endpoint_name` para el drill-down antes de agregar más cardinalidad.
4. No uses `remote_ip` como dimensión de agrupación en alertas. Es útil para inspección, no para enrutamiento.

## Brechas actuales

1. El repositorio aún no incluye JSON exportado de reglas de alerta de Grafana porque los payloads de reglas de Grafana Cloud varían según la versión de stack y la disposición de contact points.
2. Todavía no hay datos reales de Influx en el bucket, por lo que los umbrales de los paneles son valores iniciales en lugar de valores derivados de la línea base.
3. La sonda actual cubre solo un endpoint por servicio. Los dashboards de servicios con múltiples endpoints pueden necesitar filas adicionales más adelante.
