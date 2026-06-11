# CX-Radar

**Monitoreo automático de la calidad de experiencia en servicios web.**

CX-Radar es una herramienta que revisa de forma continua si los servicios web que importan a tu organización están funcionando correctamente. Cada pocos minutos mide disponibilidad, velocidad de carga y velocidad de descarga en servicios como Netflix, YouTube, Microsoft, Disney+ y Amazon, y guarda los resultados para que puedas verlos en gráficas y recibir alertas si algo falla.

---

## ¿Para qué sirve?

En muchas empresas los problemas de lentitud o caída de un servicio se descubren tarde, generalmente cuando un usuario ya se quejó. CX-Radar resuelve eso al hacer mediciones automáticas y frecuentes desde tu propia red, lo que permite:

- **Detectar problemas antes de que los note el usuario final.** Si un servicio empieza a responder lento o deja de estar disponible, las métricas lo reflejan de inmediato.
- **Tener datos objetivos.** En lugar de "me parece que anda lento", tienes números concretos: latencia en milisegundos, velocidad de descarga/subida en Mbps, porcentaje de disponibilidad.
- **Ver tendencias históricas.** Puedes comparar el rendimiento de hoy contra el de la semana pasada y detectar patrones de degradación.
- **Centralizar todo en un solo lugar.** Los resultados se almacenan en la nube y se visualizan en paneles gráficos interactivos.

---

## ¿Cómo funciona? (Visión general)

```
┌─────────────────┐       ┌──────────────┐       ┌──────────────┐
│  Tu equipo con  │──────▶│  InfluxDB    │──────▶│   Grafana    │
│  Windows        │ mide  │  Cloud       │ lee   │   Cloud      │
│  (la sonda)     │ y     │  (almacena   │ y     │  (muestra    │
│                 │ envía │   métricas)  │ grafica│  dashboards) │
└─────────────────┘       └──────────────┘       └──────────────┘
```

1. **La sonda** es un script de Python 3 que corre en tu equipo (compatible con Windows, Linux o macOS). Cada 10 minutos se conecta a los servicios configurados y mide cuánto tardan en responder, si están disponibles y a qué velocidad se puede descargar o subir contenido.
2. **Los resultados se envían a InfluxDB Cloud**, una base de datos especializada en almacenar métricas con marcas de tiempo.
3. **Grafana Cloud lee esos datos** y los presenta en paneles gráficos (dashboards) donde puedes ver el estado de cada servicio, comparar entre fechas y configurar alertas.

---

## ¿Qué servicios monitorea?

La configuración predeterminada incluye:

| Servicio   | Qué mide                                           |
|------------|-----------------------------------------------------|
| Microsoft  | Descarga de un archivo de prueba real + subida      |
| YouTube    | Descarga de un video en 4K para medir velocidad real|
| Netflix    | Velocidad de descarga usando Fast.com               |
| Disney+    | Descarga de un recurso público del CDN de Disney    |
| Amazon     | Descarga de un archivo multimedia público de Amazon  |

Para todos los servicios se miden además: **latencia** (tiempo de respuesta), **jitter** (variabilidad en el tiempo de respuesta) y **disponibilidad** (si el servicio responde o no).

Puedes agregar, quitar o modificar servicios editando el archivo de configuración `config/probe-catalog.json`.

---

## Tecnologías utilizadas

| Tecnología | Para qué se usa |
|---|---|
| **Windows, Linux o macOS** | Sistemas operativos donde corre la sonda |
| **Python 3** | Motor multiplataforma que ejecuta las mediciones (sólo biblioteca estándar) |
| **curl** | Realiza las peticiones HTTP hacia los servicios |
| **Node.js** (portable) | Ejecuta la herramienta de medición de Netflix |
| **fast-cli** | Mide velocidad de descarga contra los servidores de Netflix/Fast.com |
| **yt-dlp** | Descarga muestras reales de YouTube para medir velocidad |
| **InfluxDB Cloud** | Almacena todas las métricas en la nube |
| **Grafana Cloud** | Presenta los resultados en paneles gráficos interactivos |
| **Task Scheduler** | Programa la sonda para que se ejecute automáticamente cada 10 minutos |

> **Nota:** Todas las herramientas necesarias (Node.js, fast-cli, yt-dlp) vienen incluidas de forma portable dentro del proyecto. No necesitas instalar nada en tu sistema.

---

## Requisitos previos

Antes de empezar necesitas:

- **Python 3 instalado en el sistema**: La sonda requiere Python 3.8 o superior.
  > **¿Por qué Python no está incluido directamente en el repositorio?**
  > 1. **Tamaño y peso del repositorio**: Python completo para cada sistema operativo (Windows, Linux, macOS, arquitecturas x64, ARM64) pesa cientos de megabytes. Subirlos al repositorio Git inflaría el peso del proyecto masivamente de forma innecesaria.
  > 2. **Problema de iniciación (Chicken-and-Egg)**: Para correr el script de descarga y preparación portable (`setup_portable.py`), el equipo ya debe contar con un intérprete de Python para ejecutarlo.
  > 3. **Integración con el OS**: Python requiere registrar extensiones de archivos y variables de entorno (`PATH`) del sistema para una correcta ejecución.
  > 
  > *Nota: Herramientas secundarias (como Node.js, yt-dlp y fast-cli) sí se descargan de forma 100% portable y aislada mediante nuestro script automatizado sin tocar la configuración del sistema.*
- **Conexión a internet** para descargar las herramientas portables la primera vez y para realizar las mediciones continuas.
- Una cuenta de **InfluxDB Cloud** con un bucket creado y un token de escritura.
- (Opcional) Una cuenta de **Grafana Cloud** para visualizar los dashboards.
- (Opcional) Permisos de administrador si quieres programar la ejecución automática como tarea programada del sistema.

---

## Compatibilidad Especial (Entornos Heredados / Windows Server 2012 R2)

Si planeas instalar la sonda en un servidor con **Windows Server 2012** o **Windows Server 2012 R2** totalmente limpio (ISO nueva), debes aplicar los siguientes pasos de preparación del sistema operativo antes de proceder con la instalación común:

1. **Instalar el parche de Windows Update [KB2999226](https://support.microsoft.com/es-es/topic/actualizaci%C3%B3n-para-universal-c-runtime-en-windows-c5963e2e-ad86-2717-47a6-22a6a0259d20) (Universal C Runtime)**: Esto provee las librerías necesarias de C Runtime que Python, Node.js y curl requieren para iniciar. Sin esto, verás el error indicando que falta `api-ms-win-crt-runtime-l1-1-0.dll`.
2. **Habilitar TLS 1.2 en la terminal**: PowerShell nativo en Server 2012 tiene TLS 1.2 deshabilitado por defecto para consultas externas. Si necesitas descargar recursos de GitHub o el instalador de Python, ejecuta primero esto en tu consola de PowerShell:
   ```powershell
   [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
   ```
3. **Instalar la versión correcta de Python**:
   - Las versiones modernas de Python (3.11 en adelante) **no soportan** Windows Server 2012.
   - Debes descargar e instalar **Python 3.10.x** (por ejemplo, Python 3.10.11). Asegúrate de activar la casilla **"Add Python to PATH"** en el instalador gráfico.
4. **Compatibilidad Automática de Node.js**:
   - Nuestro script `setup_portable.py` detectará si estás corriendo sobre Windows Server 2012/R2 y descargará automáticamente **Node.js v16.20.2** (la última versión portable compatible con Server 2012) en lugar de la v20 por defecto.

---

## Guía de instalación paso a paso

### 1. Descargar el proyecto

Clona este repositorio o descárgalo como ZIP y descomprímelo en tu equipo. Abre una terminal (PowerShell, CMD, Bash o Zsh) en la carpeta raíz del proyecto.

### 2. Descargar las herramientas portables

Este comando descarga automáticamente todas las herramientas necesarias (`node`, `yt-dlp` y `fast-cli`) dentro de la carpeta `bin/` del proyecto sin modificar tu sistema (adaptándose a la compatibilidad de tu OS):

```bash
python scripts/setup_portable.py
```

### 3. Configurar los servicios a monitorear

Abre el archivo `config/probe-catalog.json` con cualquier editor de texto. Ahí encontrarás:

- **`probe`**: datos que identifican a tu sonda (nombre, ubicación, tipo de conexión, tipo de sonda: `"python"`).
- **`influx`**: los datos de conexión a InfluxDB Cloud (URL, organización, bucket).
- **`targets`**: la lista de servicios que quieres monitorear. Puedes habilitarlos o deshabilitarlos cambiando `"enabled": true` a `false`.

### 4. Guardar el token de InfluxDB de forma segura

Ejecuta el siguiente comando y escribe tu token cuando se solicite. El token se almacenará en un archivo local `.env` con permisos restringidos:

```bash
python scripts/set_influx_token.py --method file
```

### 5. Verificar que todo esté listo

Ejecuta la validación para comprobar que la configuración, las herramientas y el token estén correctos:

```bash
python scripts/validate_qoe_probe.py
```

Si todo está bien, verás indicadores en `True` para las herramientas disponibles y el token detectado.

### 6. Hacer una prueba sin enviar datos

Para probar que la sonda funciona sin enviar datos a InfluxDB (ejecución en seco):

```bash
python scripts/qoe_probe.py --skip-influx-write
```

Revisa los logs generados en la carpeta `logs/` para confirmar que las mediciones se realizaron correctamente.

### 7. Ejecutar la sonda con envío real de datos

Una vez que la prueba en seco funcione bien, ejecuta la sonda completa para que envíe métricas a InfluxDB:

```bash
python scripts/qoe_probe.py
```

### 8. Programar la ejecución automática (opcional)

Para que la sonda se ejecute sola cada 10 minutos en segundo plano:

```bash
python scripts/register_qoe_task.py
```

Si estás en Windows en un equipo personal sin permisos de administrador, usa esta variante:

```bash
python scripts/register_qoe_task.py --run-as-current-user
```

*(En Linux se utilizará Systemd/Cron, y en macOS LaunchAgents).*

### 9. Ver los resultados

- **Logs locales:** Revisa la carpeta `logs/` donde se genera un archivo diario con el detalle de cada medición.
- **InfluxDB Cloud:** Verifica que las métricas aparezcan en tu bucket configurado.
- **Grafana Cloud:** Importa los dashboards incluidos en `grafana/dashboards/qoe-national-global.json` y `grafana/dashboards/qoe-probe-detail.json`.

---

## Estructura del proyecto

```
CX-Radar/
├── bin/                  ← Herramientas portables (node, fast-cli, yt-dlp)
├── config/
│   └── probe-catalog.json  ← Configuración de la sonda y servicios
├── docs/                 ← Documentación técnica detallada
│   └── MIGRATION.md      ← Detalles específicos sobre la migración a Python
├── grafana/
│   └── dashboards/       ← Definiciones de paneles para Grafana
├── logs/                 ← Logs diarios de cada ejecución
├── orchestration/        ← Plantillas para Systemd, Cron y LaunchAgents
├── scripts/
│   ├── qoe_probe.py            ← Script principal de la sonda (Python)
│   ├── validate_qoe_probe.py  ← Validación del entorno (Python)
│   ├── register_qoe_task.py   ← Registro de tarea programada (Python)
│   ├── set_influx_token.py      ← Guardado seguro del token (Python)
│   ├── setup_portable.py      ← Descarga de herramientas portables (Python)
│   └── run_qoe_certification.py ← Script de Certificación de QA (Python)
└── tmp/                  ← Archivos temporales (se limpian automáticamente)
```

## Referencia de Parámetros de los Scripts

Los scripts de Python admiten los siguientes parámetros de línea de comandos:

### 1. `qoe_probe.py` (Script Principal)
Ejecuta las mediciones y las escribe en InfluxDB.
- **`--config-path <string>`**: Ruta personalizada al archivo de configuración de la sonda (por defecto: `config/probe-catalog.json`).
- **`--run-report-path <string>`**: Ruta donde guardar un reporte JSON estructurado con los resultados completos de la ejecución.
- **`--skip-influx-write`**: Flag para ejecutar la sonda sin enviar las métricas a InfluxDB (modo de ejecución en seco).

### 2. `validate_qoe_probe.py` (Script de Validación)
Verifica sintaxis, dependencias, rutas y credenciales necesarias.
- **`--config-path <string>`**: Ruta al archivo de configuración de catálogo a validar (por defecto: `config/probe-catalog.json`).

### 3. `register_qoe_task.py` (Registro de Tarea)
Registra la sonda en el planificador de tareas nativo del sistema operativo (Task Scheduler, Systemd, Cron, Launchd).
- **`--task-name <string>`**: Nombre de la tarea (por defecto: `CX-Radar-QoE-Probe`).
- **`--interval-minutes <int>`**: Intervalo de ejecución en minutos (por defecto: `10`).
- **`--config-path <string>`**: Ruta al catálogo de configuración (por defecto: `config/probe-catalog.json`).
- **`--method <auto|schtasks|cron|systemd|launchd>`**: Método de registro (por defecto: `auto`).
- **`--run-as-current-user`**: (Windows) Fuerza el registro bajo la sesión interactiva del usuario actual.
- **`--description <string>`**: Descripción de la tarea programada.

### 4. `run_qoe_certification.py` (Script de Certificación de QA)
Ejecuta suites de prueba (smoke y resiliencia) para certificar el estado de la sonda.
- **`--config-path <string>`**: Ruta al catálogo de configuración (por defecto: `config/probe-catalog.json`).
- **`--output-path <string>`**: Ruta donde exportar los resultados detallados en formato JSON.
- **`--max-probe-runtime-seconds <int>`**: Tiempo máximo de ejecución permitido para la sonda durante los tests (por defecto: `120`).
- **`--run-resilience-checks`**: Flag para ejecutar pruebas adicionales de resiliencia (falla DNS, caída de InfluxDB, timeout, etc.).
- **`--include-tls-scenario`**: Flag para incluir el escenario de fallo TLS (requiere conexión activa a badssl.com).

---

## Mantenimiento automático

La sonda incluye una rutina de limpieza automática que se ejecuta al inicio de cada medición. Esta rutina:

- Elimina archivos temporales (`*.tmp`, `*.bak`) que tengan más de 20 minutos de antigüedad.
- Elimina logs diarios que tengan más de 7 días de antigüedad.

No necesitas intervenir manualmente para mantener limpio el entorno.

---

## Preguntas frecuentes

**¿Necesito instalar algo en mi sistema?**
No. Todas las herramientas se descargan dentro del proyecto en la carpeta `bin/`. Tu sistema no se modifica.

**¿Por qué los perfiles temporales de fast-cli/Chromium se guardan en la carpeta temporal del usuario?**
Para prevenir conflictos de bloqueo de archivos en Windows. Si los perfiles de Chromium de Puppeteer se guardaran en la carpeta del repositorio (`bin/tmp`), los antivirus locales, indexadores de búsqueda o software de desarrollo (como VS Code) mantendrían archivos abiertos, provocando fallas e impidiendo que las pruebas completen su ejecución. Usar el directorio temporal estándar del usuario (`AppData/Local/Temp`) asegura un aislamiento óptimo y libre de bloqueos.


**¿Consume muchos recursos?**
No. La sonda se ejecuta unos pocos minutos cada 10 minutos, usa poca memoria y no deja procesos corriendo en segundo plano fuera de su ventana de ejecución.

**¿Puedo agregar otros servicios?**
Sí. Edita el archivo `config/probe-catalog.json` y agrega nuevos objetivos en la sección `targets`. Consulta la documentación de arquitectura para más detalles sobre los tipos soportados.

**¿Qué pasa si un servicio no responde?**
La sonda registra la falla con el detalle del error (tipo de fallo, código de respuesta, tiempo transcurrido). El siguiente servicio en la lista se mide normalmente. Ninguna falla individual detiene el ciclo completo de medición.

---

## Documentación adicional

Para información técnica más detallada, consulta:

- [Arquitectura del sistema](docs/architecture/qoe-architecture.md)
- [Validación y control de calidad](docs/qa/validation-runbook.md)
- [Guía de tarea programada](docs/operations/task-scheduler-runbook.md)
- [Seguridad y manejo de credenciales](docs/security/hardening.md)
- [Configuración de Grafana Cloud](docs/observability/grafana-cloud-setup.md)
- [Changelog de optimización](docs/CHANGELOG.md)
