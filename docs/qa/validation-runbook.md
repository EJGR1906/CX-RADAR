# Runbook de Validación QoE

## Resumen

Este runbook es la ruta de QA ejecutable para la sonda HTTP sintética actual en Windows 11.

Divide la validación en cuatro capas:

1. Comprobaciones de smoke rápidas para sintaxis, comportamiento de ejecución en seco, completitud de logs y procesos `curl.exe` huérfanos.
2. Comprobaciones de resiliencia automatizadas para fallo DNS, límites de timeout y comportamiento ante una caída de InfluxDB.
3. Comprobaciones de soak manuales para CPU, RAM, crecimiento de procesos y crecimiento de logs a lo largo del tiempo.
4. Comprobaciones de confianza de datos para confirmar que los milisegundos reportados reflejan el comportamiento de la red y no la sobrecarga del script local.

## Validación de Smoke Rápida

Ejecuta esto antes de cada lanzamiento o cambio de configuración:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -OutputPath .\logs\qoe-certification-smoke.json
```

Criterios de aprobación:

1. `overall_passed = true`
2. `smoke.passed = true`
3. `validate.ProbeScriptSyntax = OK`
4. `validate.ConfigFile = OK`
5. `smoke.process.timed_out = false`
6. `smoke.process.exit_code = 0`
7. `smoke.new_curl_process_ids` está vacío
8. `smoke.parsed_log.summary.failure_count = 0`
9. `smoke.distinct_latency_values >= 2`

## Validación de Resiliencia Automatizada

Ejecuta esto al cambiar timeouts, manejo de targets, lógica de escritura a Influx o manejo de errores:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -RunResilienceChecks -OutputPath .\logs\qoe-certification-resilience.json
```

El arnés actualmente ejecuta:

1. `dns_failure`: hostname inválido `.invalid`, `SkipInfluxWrite = true`
2. `timeout_bound`: IP no enrutable con timeouts reducidos, `SkipInfluxWrite = true`
3. `influx_outage`: token ficticio más `baseUrl = http://127.0.0.1:1`, `SkipInfluxWrite = false`

Criterios de aprobación:

1. `dns_failure.passed = true`
2. `timeout_bound.passed = true`
3. `influx_outage.passed = true`
4. Ningún escenario deja `new_curl_process_ids`
5. Ningún escenario establece `process.timed_out = true`

Interpretación:

1. Los escenarios de DNS y timeout deben terminar con `exit_code = 0` porque la sonda registra puntos de fallo pero aún completa la ejecución.
2. El escenario de caída de Influx debe terminar con `exit_code != 0` porque se espera que la falla de ingestión falle de forma ruidosa.

## Validación Manual de TLS

El fallo de TLS depende de un endpoint remoto en vivo, por lo que se mantiene opt-in:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -RunResilienceChecks -IncludeTlsScenario -OutputPath .\logs\qoe-certification-tls.json
```

Criterios de aprobación:

1. `tls_failure.passed = true`
2. El escenario no se agota por timeout
3. No queda ningún proceso `curl.exe` huérfano

Si el endpoint es inaccesible por razones no relacionadas con TLS, marca el resultado como inconcluso en lugar de tratarlo como una regresión.

## Plan de Soak

El repositorio aún no automatiza ejecuciones de soak de varios días. Ejecuta estas comprobaciones en un PC normal después de registrar la tarea programada.

### Soak de 24 horas

Objetivo: detectar fugas obvias o patrones de fallo ruidosos.

Método:

1. Registra la tarea programada con el intervalo normal de 5 minutos.
2. Registra los valores base de working set de `powershell.exe`, recuento de handles y recuento de procesos antes del soak.
3. Registra los mismos valores nuevamente después de 24 horas.
4. Inspecciona `logs\qoe-probe-YYYY-MM-DD.log` en busca de rastros de pila repetidos o crecimiento descontrolado.

Umbrales de aprobación:

1. No hay procesos persistentes `curl.exe` huérfanos
2. No hay crecimiento monótono en el recuento de procesos de PowerShell relacionados con la sonda
3. No hay una tendencia sostenida de crecimiento de handles mayor al 20 por ciento sobre la línea base para el proceso host de programación de larga duración
4. No hay un patrón de crecimiento de logs que sugiera reintentos repetidos o rastros de pila repetidos en cada ciclo

### Soak de 72 horas

Objetivo: detectar regresiones lentas que no aparecen en un día.

Método:

1. Mantén el mismo horario y conjunto de targets.
2. Recolecta instantáneas de CPU, working set y handles al menos cada 12 horas.
3. Verifica que la rotación diaria de logs siga ocurriendo y que los archivos antiguos se mantengan acotados.

Umbrales de aprobación:

1. El impacto promedio de CPU permanece operacionalmente despreciable en un PC normal fuera de los pocos segundos activos de cada ejecución.
2. El working set no muestra una deriva sostenida hacia arriba atribuible a la ejecución de la sonda.
3. El recuento de handles y procesos permanece estable durante la ventana de 72 horas.

## Validación de Confianza de Datos

Ejecuta estas comprobaciones después de una ejecución de smoke exitosa y después de la primera escritura real a Influx.

### Plausibilidad local

Usa la salida JSON de smoke.

Criterios de aprobación:

1. `smoke.parsed_log.target_results` contiene valores `time_total_ms` distintos de cero.
2. Servicios distintos muestran valores de latencia diferentes.
3. El `run_duration_ms` por ejecución es mayor que el target más lento, pero no es exageradamente mayor que la suma de los tiempos de los targets más el pacing.

### Consistencia en Influx

Después de que una escritura real tenga éxito:

1. Consulta `qoe_http_check` para la última ejecución en Grafana o Influx Data Explorer.
2. Compara el `time_total_ms` de al menos un endpoint con el mismo endpoint en el log diario.
3. Compara `qoe_probe_run.failure_count` con el resumen de la ejecución en la misma ventana de logs.

Criterios de aprobación:

1. Los valores en Influx coinciden con los valores del log dentro de diferencias normales por redondeo.
2. Las fallas aparecen como puntos de fallo explícitos en lugar de brechas silenciosas de datos.

## Lista de Verificación de Preparación para Producción

La sonda está lista para avanzar más allá de la validación MVP solo cuando todo lo siguiente sea verdadero:

1. La salida de smoke de `run-qoe-certification.ps1` pasa.
2. `run-qoe-certification.ps1 -RunResilienceChecks` pasa.
3. El almacenamiento de token DPAPI u otra ruta de secretos aprobada está configurado.
4. Al menos una escritura real a InfluxDB tiene éxito en Windows PowerShell 5.1.
5. Al menos una consulta de dashboard de Grafana tiene éxito contra `qoe_http_check`.
6. Un soak de 24 horas se completa sin procesos huérfanos ni deriva sostenida de recursos.
7. Un soak de 72 horas está programado o completado antes del despliegue más amplio.

## Riesgos Restantes y Cambios Recomendados

1. El fallo de TLS sigue dependiendo del entorno y puede necesitar un endpoint interno controlado para una ejecución determinista.
2. El arnés actual valida tiempo de ejecución acotado y falla de ingestión ruidosa, pero todavía no recopila automáticamente contadores de rendimiento de la estación de trabajo.
3. Si escalas a múltiples sondas, agrega validación de escalonamiento de la flota para que los inicios simultáneos de tareas no creen ráfagas sintéticas.
4. Si quieres evidencia repetible de larga duración en forma similar a CI, la siguiente adición útil es un pequeño colector de soak que registre working set, recuento de handles y recuento de procesos secundarios en JSON en cada muestra.
