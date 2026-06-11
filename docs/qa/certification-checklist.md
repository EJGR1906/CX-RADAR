# Lista de Verificación de Certificación de QA

> [!NOTE]
> **Aviso de Migración**: Esta lista de verificación ha sido actualizada para la nueva implementación en Python 3 (Multiplataforma). Para más detalles sobre las decisiones de diseño y equivalencia de archivos, consulte la [Guía de Migración](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/MIGRATION.md).

## Alcance

Esta lista de verificación es la puerta de lanzamiento mínima para el MVP de HTTP sintético.

Usa `scripts/run_qoe_certification.py` para comprobaciones repetibles de smoke y resiliencia antes de considerar esta lista como aprobada.

## Funcional

1. `validate_qoe_probe.py` devuelve `ProbeScriptSyntax = OK`.
2. `run_qoe_certification.py` devuelve `smoke.passed = True`.
3. La sonda completa una ejecución en seco con `--skip-influx-write` sin terminar con error.
4. El log diario contiene una entrada por target habilitado más un resumen final de ejecución.
5. La sonda escribe en InfluxDB correctamente una vez configurado el token.

## Resiliencia

1. Sin internet: el script sale limpiamente y registra estados de fallo en lugar de quedarse colgado.
2. Fallo DNS: los errores de conexión/curl se capturan y se mapean a `error_class`.
3. Fallo TLS: los errores de conexión/curl se capturan y se mapean a `error_class`.
4. `run_qoe_certification.py --run-resilience-checks` devuelve resultados pasados para `dns_failure`, `timeout_bound` e `influx_outage`.
5. InfluxDB no disponible: el script falla de forma ruidosa y predecible.
6. Ruta de timeout: cada target está acotado por `connectTimeoutSeconds` y `maxTimeSeconds`.

## Impacto en el puesto de trabajo

1. `run_qoe_certification.py` informa que no hay `new_curl_process_ids` después de una ejecución de smoke.
2. Las ejecuciones programadas repetidas no generan crecimiento sostenido de CPU o RAM.
3. Los logs rotan de forma natural por fecha y no explotan en tamaño durante el uso normal.

## Confianza en los datos

1. Los milisegundos medidos no son cero y son plausibles para destinos reales.
2. Servicios distintos generan perfiles de latencia diferentes.
3. Las fallas se representan como puntos de fallo, no como brechas silenciosas.

## Puerta de lanzamiento

El MVP no está listo para producción hasta que:

1. El manejo del token esté configurado.
2. Se observe una escritura exitosa en InfluxDB.
3. Se observe una consulta exitosa en un dashboard.
4. Se complete al menos un periodo de soak después de programar.
5. El runbook de QA en [docs/qa/validation-runbook.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/qa/validation-runbook.md) se haya ejecutado y adjuntado como evidencia de lanzamiento.
