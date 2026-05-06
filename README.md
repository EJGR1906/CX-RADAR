# CX-Radar

## Resumen Ejecutivo

CX-Radar ayuda a detectar caidas, lentitud y degradaciones de servicio antes de que el cliente final o las areas internas las escalen como incidente. Su valor principal es reducir el tiempo de reaccion, dar visibilidad temprana sobre el estado real de servicios criticos y entregar evidencia objetiva para seguimiento operativo y decisiones de negocio.

La herramienta funciona con herramientas portables dentro del propio proyecto, por lo que no requiere instalaciones complejas ni cambios globales en el equipo donde se ejecuta.

## Descripción General

CX-Radar es una sonda de monitoreo de servicios que se ejecuta en Windows y permite evaluar tanto comprobaciones HTTP sintéticas como métricas de Quality of Experience / Calidad de Experiencia (QoE), es decir, indicadores que ayudan a entender como se percibe realmente un servicio desde el entorno donde opera el usuario o el equipo.

En la practica, esto permite responder preguntas simples pero criticas: si un servicio esta disponible, si esta respondiendo con lentitud y si esa lentitud puede convertirse en una mala experiencia para clientes o usuarios internos. El objetivo es transformar comprobaciones tecnicas en informacion clara y util para operacion, seguimiento de proyectos y visibilidad gerencial.

En su estado actual, el proyecto concentra todo el flujo activo en una sola sonda PowerShell capaz de ejecutar objetivos de monitoreo web y pruebas de rendimiento desde un mismo catalogo. Las herramientas necesarias se mantienen dentro del propio proyecto, lo que simplifica la puesta en marcha y evita instalaciones invasivas en el equipo.

El proyecto se centra en una sonda principal para monitoreo de servicios, la escritura de metricas en InfluxDB Cloud y la visualizacion de resultados en dashboards de Grafana Cloud.

## Objetivos y Problema que Resuelve

Este proyecto fue creado para responder una pregunta muy práctica: "¿los servicios que usan los clientes están funcionando bien desde nuestra red?". En muchas organizaciones, los problemas de lentitud o disponibilidad se detectan tarde, de forma manual o solo cuando un usuario ya está afectado.

CX-Radar reduce esa incertidumbre al automatizar mediciones frecuentes sobre endpoints aprobados. Con ello ayuda a:

- Detectar degradaciones de disponibilidad y latencia antes de que escalen.
- Contar con datos objetivos y repetibles sobre tiempos de respuesta.
- Centralizar evidencias en logs, métricas y dashboards.
- Evitar revisiones manuales repetitivas en distintos servicios.
- Facilitar validaciones operativas, QA y seguimiento histórico.

## Tecnologías Utilizadas

- Windows como entorno de ejecución de la sonda.
- PowerShell como motor principal de automatización.
- `curl.exe` o `Invoke-WebRequest` para la ruta HTTP, descargas por ráfagas y uploads controlados a endpoints propios.
- Node.js portable en `./bin/node/` para ejecutar `fast-cli` sin instalación global.
- `fast-cli` para medir throughput contra Fast.com/Netflix.
- `yt-dlp.exe` en `./bin/` para descargar muestras reales desde YouTube y medir velocidad efectiva.
- `ping.exe` para calcular latencia media y jitter a partir de 10 sondas consecutivas.
- `networkquality.exe`, cuando existe y está configurado, para complementar métricas reales de throughput y subida en targets compatibles.
- JSON para definir la identidad de la sonda, parámetros y endpoints objetivo.
- InfluxDB Cloud para almacenar métricas de disponibilidad y latencia.
- Grafana Cloud para consultar, visualizar y comparar resultados.
- Windows Task Scheduler para programar la ejecución automática cada 10 minutos.
- DPAPI mediante archivo protegido local para almacenar el token de InfluxDB de forma más segura.

## Requisitos Previos

Antes de empezar, asegúrate de contar con lo siguiente:

- Un equipo con Windows.
- Conectividad de red para descargar dependencias portables la primera vez.
- Acceso a una cuenta de InfluxDB Cloud con permiso para escribir métricas.
- Un token de InfluxDB Cloud para el bucket configurado.
- Acceso a Grafana Cloud si quieres visualizar dashboards y consultas.
- Permisos para crear una tarea programada si deseas dejar la sonda corriendo en segundo plano.
- Conectividad de red hacia los endpoints definidos en `config/probe-catalog.json`.
- Si quieres subida real para targets no-Fast y no dispones de `networkquality.exe`, un endpoint propio de upload (`uploadUrl`) accesible desde la sonda.

## Cómo Iniciar (Guía de Instalación)

### 1. Obtener el proyecto

- Clona este repositorio o descárgalo en tu equipo.
- Abre PowerShell en la raíz del proyecto.

### 2. Preparar herramientas portables

- Descarga y organiza los binarios portables dentro de `./bin/`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\setup-portable.ps1 | Format-List
```

- Este paso deja `node.exe`, `fast-cli`, `yt-dlp.exe` y la caché local de Puppeteer dentro del proyecto, sin tocar el sistema.
- `setup-portable.ps1` no instala `networkquality.exe`; si quieres usar ese método para complementar la subida real, debes tenerlo disponible en el host o indicar su ruta en `probeRun.portableTools.networkQualityExe`.

### 3. Ajustar el catálogo de targets

- Abre `config/probe-catalog.json`.
- Completa o ajusta los datos de la sonda, la configuración de InfluxDB y la lista de `targets` QoE que quieras monitorear.
- Verifica especialmente `probe.isp`, `baseUrl`, `org`, `bucket`, `tokenEnvVar`, `credentialFilePath`, `probeRun.realMetricsMeasurement`, `probeRun.portableTools.networkQualityExe`, `uploadMeasurementMethod`, `uploadUrl` y los `targets` habilitados.
- La configuración actual cubre Netflix con `fast-cli` y upload nativo, YouTube con `yt-dlp` para descarga real, y Microsoft, Disney+ y Amazon con ráfaga HTTP para descarga real.
- Para targets no-Fast, la subida real es opcional y puede venir de `uploadMeasurementMethod = "networkquality"` o `uploadMeasurementMethod = "upload-url"`.
- Si no hay `networkquality.exe` y tampoco hay `uploadUrl`, la sonda sigue funcionando, pero esos targets dejarán `upload_speed = 0` y registrarán `upload_tool`, `upload_error_class` y `upload_error_detail` para explicar el motivo.

### 4. Configurar el token de InfluxDB

- Guarda el token de forma protegida con el script incluido.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\set-influx-token.ps1
```

### 5. Validar que el entorno esté listo

- Ejecuta la validación local para comprobar sintaxis, configuración, disponibilidad de herramientas portables y acceso al token.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List
```

- El resultado esperado debe indicar que el script y la configuración están correctos, que `PortableNodeAvailable`, `FastCliAvailable`, `YtDlpAvailable` y `SpeedTestTargetsReady` están en `True`, y que el token está disponible.
- Si configuraste subida suplementaria con `networkquality` pero el binario no existe en el host, es normal ver `NetworkQualityCommandAvailable = False` y `UploadMeasurementTargetsReady = False` aunque la medición primaria de descarga siga lista para ejecutarse.

### 6. Probar la sonda sin enviar métricas

- Haz una ejecución de prueba para verificar el flujo QoE antes de escribir en InfluxDB.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

- Esta prueba genera logs locales y te permite confirmar que la sonda responde como esperas sin enviar puntos a InfluxDB.
- Si necesitas revisar el detalle estructurado de una corrida, por ejemplo para depurar suplementos de subida, puedes añadir `-RunReportPath .\tmp\upload-supplement-smoke.json`.

### 7. Ejecutar la sonda con escritura real

- Cuando la validación y la prueba en seco funcionen, ejecuta la sonda completa.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1
```

- En este paso se envían métricas a InfluxDB Cloud. Los targets `speedtest` escriben en `qoe_real_metrics` con los campos `download_speed`, `upload_speed`, `upload_tool`, `upload_error_class`, `upload_error_detail`, `latency`, `jitter` y `rpm_responsiveness`.

### 8. Programar la ejecución automática

- Si quieres que la sonda corra en segundo plano cada 10 minutos, registra la tarea programada.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1
```

- Si estás en un equipo personal y no puedes registrar la tarea con elevación, usa esta variante:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1 -RunAsCurrentUser
```

### 9. Confirmar resultados

- Revisa los logs diarios generados en la carpeta `logs`.
- Verifica que las métricas aparezcan en InfluxDB Cloud.
- Confirma que la medición `qoe_real_metrics` reciba tags `service`, `probe_id` e `isp`.
- Si estás validando subida real en targets no-Fast, revisa también `upload_tool`, `upload_error_class` y `upload_error_detail` para distinguir entre ausencia de soporte, falta de binario y fallos de medición.
- Abre el dashboard de Grafana en `grafana/dashboards/qoe-http-overview.json` si ya tienes el entorno de observabilidad preparado.

## Contexto adicional

Este proyecto es una solución de automatización operativa orientada al monitoreo de calidad de experiencia sobre servicios web. Su alcance actual combina comprobaciones HTTP sintéticas y objetivos de Quality of Experience / Calidad de Experiencia (QoE) bajo una misma sonda, con resultados centralizados en logs, métricas y dashboards.

Los directorios `logs/` y `tmp/` deben tratarse como artefactos operativos locales. Son útiles para diagnóstico, pero no forman parte del flujo normal de publicación del repositorio.

## Recursos útiles

- Arquitectura general: [docs/architecture/qoe-architecture.md](docs/architecture/qoe-architecture.md)
- Validación y QA: [docs/qa/validation-runbook.md](docs/qa/validation-runbook.md)
- Registro de tarea programada: [docs/operations/task-scheduler-runbook.md](docs/operations/task-scheduler-runbook.md)
- Seguridad y manejo de token: [docs/security/hardening.md](docs/security/hardening.md)
- Configuración de observabilidad: [docs/observability/grafana-cloud-setup.md](docs/observability/grafana-cloud-setup.md)
