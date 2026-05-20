# Arquitectura QoE de CX-Radar

## Objetivo

CX-Radar comienza con una sola sonda Windows 11 y está diseñado para escalar más adelante a múltiples sondas remotas, incluyendo tipos mixtos de sondas.

La plataforma separa el tráfico de la sonda activa de las futuras líneas especializadas:

1. Canal HTTP sintético: verificaciones frecuentes con curl contra endpoints de servicio aprobados.
2. Métricas QoE con alcance de sonda: comprobaciones portátiles de throughput, latencia, jitter y capacidad de respuesta escritas bajo `qoe_real_metrics` por los objetivos seleccionados en `qoe-probe.ps1`.
3. Canal de auditoría de navegador semanal: comprobaciones más profundas de rendimiento web usando WebPageTest o herramientas similares futuras.

Estas familias de señales deben permanecer separadas en almacenamiento, paneles y alertas.

## Implementación actual

El repositorio implementa actualmente la línea de sonda activa con:

1. `config/probe-catalog.json` para identidad de la sonda, destino de InfluxDB, parámetros de cadencia y endpoints aprobados.
2. `scripts/qoe-probe.ps1` para ejecución mixta de objetivos `http` y `speedtest` portátiles, y generación de la carga para escribir en InfluxDB.
3. `scripts/register-qoe-task.ps1` para el registro en el Programador de tareas de Windows.
4. `scripts/validate-qoe-probe.ps1` para comprobaciones locales de preparación.

## Mediciones

El esquema está preparado intencionalmente para una escala futura:

1. `qoe_http_check`: resultados de comprobaciones HTTP sintéticas por objetivo.
2. `qoe_real_metrics`: resultados portátiles de throughput, latencia, jitter y capacidad de respuesta por objetivo.
3. `qoe_probe_run`: un punto por ejecución del script con contadores de autocontrol.
4. `qoe_page_audit`: reservado para futuros resúmenes de WebPageTest.

## Etiquetas estables

Usa únicamente etiquetas de baja cardinalidad para la comparación entre sondas:

1. `probe_id`
2. `probe_type`
3. `site`
4. `environment`
5. `service`
6. `endpoint_name`
7. `probe_version`

No conviertas URLs, IP remotas, cadenas de redireccionamiento o errores libres en etiquetas.

## Familias de campos

La sonda actual emite campos para:

1. Disponibilidad y resultado HTTP.
2. Código de salida de curl y clase de error.
3. Latencia DNS, de conexión, TLS, de primer byte y total en milisegundos.
4. Tamaño de la respuesta, recuento de redirecciones, URL efectiva, versión HTTP e IP remota.
5. Campos de métricas QoE reales como velocidad de descarga, velocidad de carga, latencia, jitter y capacidad de respuesta.
6. Contadores de autocontrol de la sonda como recuento de aciertos, recuento de fallos, recuento de objetivos y duración de la ejecución.

## Modelo de crecimiento

Al agregar más sondas, solo estos elementos deben variar por host:

1. Valores de identidad de la sonda en `probe-catalog.json`.
2. Método de obtención de secretos.
3. Programación local o wrapper de servicio.
4. Etiquetas de sitio y entorno.

Los nombres de las mediciones y la semántica de los campos deben permanecer estables a menos que se versionen deliberadamente.

Si más adelante vuelve una línea dedicada a throughput, debería usar su propio conjunto de mediciones y permanecer separada de las mediciones de alcance de servicio y auditoría de navegador.