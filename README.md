# CX-Radar

## Descripción General

CX-Radar es una sonda de monitoreo de experiencia de servicio que se ejecuta en Windows 11 y ahora puede medir tanto comprobaciones HTTP sintéticas como métricas QoE más cercanas al usuario real. Su objetivo es convertir comprobaciones técnicas en información simple y útil para saber si un servicio está disponible, lento o presentando fallos.

En su estado actual, el proyecto puede ejecutar targets `http` tradicionales y targets `speedtest` portables desde la misma sonda. Para la parte QoE usa PowerShell, Node.js portable, `fast-cli`, `yt-dlp.exe`, `ping.exe` y, si existe en el host, `networkquality.exe`; cuando este último no está disponible, aplica un fallback por ráfagas HTTP controladas. Todas las herramientas descargables quedan dentro de `./bin/`, sin requerir privilegios de administrador ni modificar el `PATH` global.

## Objetivos y Problema que Resuelve

Este proyecto fue creado para responder una pregunta muy práctica: "¿los servicios que usamos están funcionando bien desde nuestro entorno real de trabajo?". En muchas organizaciones, los problemas de lentitud o disponibilidad se detectan tarde, de forma manual o solo cuando un usuario ya está afectado.

CX-Radar reduce esa incertidumbre al automatizar mediciones frecuentes sobre endpoints aprobados. Con ello ayuda a:

- Detectar degradaciones de disponibilidad y latencia antes de que escalen.
- Contar con datos objetivos y repetibles sobre tiempos de respuesta.
- Centralizar evidencias en logs, métricas y dashboards.
- Evitar revisiones manuales repetitivas en distintos servicios.
- Facilitar validaciones operativas, QA y seguimiento histórico.

## Tecnologías Utilizadas

- Windows 11 como entorno de ejecución de la sonda.
- PowerShell como motor principal de automatización.
- `curl.exe` o `Invoke-WebRequest` para la ruta HTTP y algunos fallbacks controlados.
- Node.js portable en `./bin/node/` para ejecutar `fast-cli` sin instalación global.
- `fast-cli` para medir throughput contra Fast.com/Netflix.
- `yt-dlp.exe` en `./bin/` para descargar muestras reales desde YouTube y medir velocidad efectiva.
- `ping.exe` para calcular latencia media y jitter a partir de 10 sondas consecutivas.
- `networkquality.exe` cuando está disponible, con fallback por ráfaga HTTP si no lo está.
- JSON para definir la identidad de la sonda, parámetros y endpoints objetivo.
- InfluxDB Cloud para almacenar métricas de disponibilidad y latencia.
- Grafana Cloud para consultar, visualizar y comparar resultados.
- Windows Task Scheduler para programar la ejecución automática cada 10 minutos.
- DPAPI mediante archivo protegido local para almacenar el token de InfluxDB de forma más segura.

## Requisitos Previos

Antes de empezar, asegúrate de contar con lo siguiente:

- Un equipo con Windows 11.
- PowerShell disponible en el sistema.
- Sin necesidad de permisos de administrador.
- Conectividad de red para descargar dependencias portables la primera vez.
- Acceso a una cuenta de InfluxDB Cloud con permiso para escribir métricas.
- Un token de InfluxDB Cloud para el bucket configurado.
- Acceso a Grafana Cloud si quieres visualizar dashboards y consultas.
- Permisos para crear una tarea programada si deseas dejar la sonda corriendo en segundo plano.
- Conectividad de red hacia los endpoints definidos en `config/probe-catalog.json`.

## Cómo Iniciar (Guía de Instalación)

### 1. Obtener el proyecto

- Clona este repositorio o descárgalo en tu equipo.
- Abre PowerShell en la raíz del proyecto.

### 2. Revisar la configuración base

- Descarga y organiza los binarios portables dentro de `./bin/`.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\setup-portable.ps1 | Format-List
```

- Este paso deja `node.exe`, `fast-cli`, `yt-dlp.exe` y la caché local de Puppeteer dentro del proyecto, sin tocar el sistema.

### 3. Revisar la configuración base

- Abre `config/probe-catalog.json`.
- Completa o ajusta los datos de la sonda, la configuración de InfluxDB y la lista de `targets` QoE que quieras monitorear.
- Verifica especialmente `probe.isp`, `baseUrl`, `org`, `bucket`, `tokenEnvVar`, `credentialFilePath`, `probeRun.realMetricsMeasurement` y los `targets` habilitados.
- Los ejemplos incluidos cubren Netflix con `fast-cli`, YouTube con `yt-dlp` y Microsoft con `networkquality` o fallback por ráfaga HTTP.

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

### 6. Probar la sonda sin enviar métricas

- Haz una ejecución de prueba para verificar el flujo QoE antes de escribir en InfluxDB.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

- Esta prueba genera logs locales y te permite confirmar que la sonda responde como esperas sin enviar puntos a InfluxDB.

### 7. Ejecutar la sonda con escritura real

- Cuando la validación y la prueba en seco funcionen, ejecuta la sonda completa.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1
```

- En este paso se envían métricas a InfluxDB Cloud. Los targets `speedtest` escriben en `qoe_real_metrics` con los campos `download_speed`, `upload_speed`, `latency`, `jitter` y `rpm_responsiveness`.

### 8. Programar la ejecución automática

- Si quieres que la sonda corra en segundo plano cada 5 minutos, registra la tarea programada.

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
- Abre el dashboard de Grafana en `grafana/dashboards/qoe-http-overview.json` si ya tienes el entorno de observabilidad preparado.

## Contexto adicional

Este proyecto es una solución de automatización operativa orientada al monitoreo de calidad de experiencia sobre servicios web. El alcance actual combina comprobaciones HTTP sintéticas y targets QoE portables bajo la misma sonda; las futuras integraciones con LibreSpeed y WebPageTest siguen documentadas por separado y no se mezclan con el flujo activo.

## Recursos útiles

- Arquitectura general: [docs/architecture/qoe-architecture.md](docs/architecture/qoe-architecture.md)
- Validación y QA: [docs/qa/validation-runbook.md](docs/qa/validation-runbook.md)
- Registro de tarea programada: [docs/operations/task-scheduler-runbook.md](docs/operations/task-scheduler-runbook.md)
- Seguridad y manejo de token: [docs/security/hardening.md](docs/security/hardening.md)
- Configuración de observabilidad: [docs/observability/grafana-cloud-setup.md](docs/observability/grafana-cloud-setup.md)
- Bootstrap installer en implementación: [installer/README.md](installer/README.md)
