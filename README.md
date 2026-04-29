# CX-Radar

## Descripción General

CX-Radar es una sonda de monitoreo de experiencia de servicio que se ejecuta en Windows 11 y revisa, de forma automática, si distintos sitios web responden correctamente y en cuánto tiempo lo hacen. Su objetivo es convertir comprobaciones técnicas en información simple y útil para saber si un servicio está disponible, lento o presentando fallos.

En su estado actual, el proyecto mide la capa de comprobación HTTP sintética: realiza solicitudes controladas con PowerShell y `curl.exe`, guarda evidencias locales en logs y envía métricas a InfluxDB Cloud para visualizarlas en Grafana Cloud. Esto permite seguir la salud de servicios digitales sin depender únicamente de reportes manuales o percepciones aisladas.

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
- `curl.exe` para realizar las comprobaciones HTTP sintéticas.
- JSON para definir la identidad de la sonda, parámetros y endpoints objetivo.
- InfluxDB Cloud para almacenar métricas de disponibilidad y latencia.
- Grafana Cloud para consultar, visualizar y comparar resultados.
- Windows Task Scheduler para programar la ejecución automática cada 5 minutos.
- DPAPI mediante archivo protegido local para almacenar el token de InfluxDB de forma más segura.

## Requisitos Previos

Antes de empezar, asegúrate de contar con lo siguiente:

- Un equipo con Windows 11.
- PowerShell disponible en el sistema.
- `curl.exe` accesible desde la variable `PATH`.
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

- Abre `config/probe-catalog.json`.
- Completa o ajusta los datos de la sonda, la configuración de InfluxDB y la lista de endpoints que quieras monitorear.
- Verifica especialmente `baseUrl`, `org`, `bucket`, `tokenEnvVar`, `credentialFilePath` y los `targets` habilitados.

### 3. Configurar el token de InfluxDB

- Guarda el token de forma protegida con el script incluido.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\set-influx-token.ps1
```

### 4. Validar que el entorno esté listo

- Ejecuta la validación local para comprobar sintaxis, configuración, disponibilidad de `curl.exe` y acceso al token.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List
```

- El resultado esperado debe indicar que el script y la configuración están correctos y que el token está disponible.

### 5. Probar la sonda sin enviar métricas

- Haz una ejecución de prueba para verificar el flujo HTTP antes de escribir en InfluxDB.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

- Esta prueba genera logs locales y te permite confirmar que la sonda responde como esperas.

### 6. Ejecutar la sonda con escritura real

- Cuando la validación y la prueba en seco funcionen, ejecuta la sonda completa.

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1
```

- En este paso se envían métricas a InfluxDB Cloud.

### 7. Programar la ejecución automática

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

### 8. Confirmar resultados

- Revisa los logs diarios generados en la carpeta `logs`.
- Verifica que las métricas aparezcan en InfluxDB Cloud.
- Abre el dashboard de Grafana en `grafana/dashboards/qoe-http-overview.json` si ya tienes el entorno de observabilidad preparado.

## Contexto adicional

Este proyecto es una solución de automatización operativa orientada al monitoreo de calidad de experiencia sobre servicios web. El alcance actual se centra en la sonda HTTP sintética; las futuras integraciones con LibreSpeed y WebPageTest están documentadas, pero se mantienen separadas del flujo activo.

## Recursos útiles

- Arquitectura general: [docs/architecture/qoe-architecture.md](docs/architecture/qoe-architecture.md)
- Validación y QA: [docs/qa/validation-runbook.md](docs/qa/validation-runbook.md)
- Registro de tarea programada: [docs/operations/task-scheduler-runbook.md](docs/operations/task-scheduler-runbook.md)
- Seguridad y manejo de token: [docs/security/hardening.md](docs/security/hardening.md)
- Configuración de observabilidad: [docs/observability/grafana-cloud-setup.md](docs/observability/grafana-cloud-setup.md)
