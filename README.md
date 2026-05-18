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

1. **La sonda** es un script de PowerShell que corre en tu equipo con Windows. Cada 10 minutos se conecta a los servicios configurados y mide cuánto tardan en responder, si están disponibles y a qué velocidad se puede descargar o subir contenido.
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
| **Windows** | Sistema operativo donde corre la sonda |
| **PowerShell** | Motor de automatización que ejecuta las mediciones |
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

- Un equipo con **Windows 10 u 11**.
- **Conexión a internet** para descargar las herramientas portables la primera vez y para las mediciones continuas.
- Una cuenta de **InfluxDB Cloud** con un bucket creado y un token de escritura.
- (Opcional) Una cuenta de **Grafana Cloud** para visualizar los dashboards.
- (Opcional) Permisos de administrador si quieres programar la ejecución automática como tarea del sistema.

---

## Guía de instalación paso a paso

### 1. Descargar el proyecto

Clona este repositorio o descárgalo como ZIP y descomprímelo en tu equipo. Luego abre PowerShell en la carpeta raíz del proyecto.

### 2. Descargar las herramientas portables

Este comando descarga automáticamente todas las herramientas necesarias dentro de la carpeta `bin/` del proyecto sin modificar tu sistema:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\setup-portable.ps1 | Format-List
```

### 3. Configurar los servicios a monitorear

Abre el archivo `config/probe-catalog.json` con cualquier editor de texto. Ahí encontrarás:

- **`probe`**: datos que identifican a tu sonda (nombre, ubicación, tipo de conexión).
- **`influx`**: los datos de conexión a InfluxDB Cloud (URL, organización, bucket).
- **`targets`**: la lista de servicios que quieres monitorear. Puedes habilitarlos o deshabilitarlos cambiando `"enabled": true` a `false`.

### 4. Guardar el token de InfluxDB de forma segura

Ejecuta el siguiente comando y pega tu token cuando se solicite. El token se almacena cifrado en tu equipo y nunca se guarda en texto plano dentro del proyecto:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\set-influx-token.ps1
```

### 5. Verificar que todo esté listo

Ejecuta la validación para comprobar que la configuración, las herramientas y el token estén correctos:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List
```

Si todo está bien, verás indicadores en `True` para las herramientas disponibles y el token detectado.

### 6. Hacer una prueba sin enviar datos

Para probar que la sonda funciona sin enviar datos a InfluxDB (ejecución en seco):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

Revisa los logs generados en la carpeta `logs/` para confirmar que las mediciones se realizaron correctamente.

### 7. Ejecutar la sonda con envío real de datos

Una vez que la prueba en seco funcione bien, ejecuta la sonda completa para que envíe métricas a InfluxDB:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1
```

### 8. Programar la ejecución automática (opcional)

Para que la sonda se ejecute sola cada 10 minutos en segundo plano:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1
```

Si estás en un equipo personal sin permisos de administrador, usa esta variante:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1 -RunAsCurrentUser
```

### 9. Ver los resultados

- **Logs locales:** Revisa la carpeta `logs/` donde se genera un archivo diario con el detalle de cada medición.
- **InfluxDB Cloud:** Verifica que las métricas aparezcan en tu bucket configurado.
- **Grafana Cloud:** Importa el dashboard incluido en `grafana/dashboards/qoe-http-overview.json` para ver gráficas interactivas de disponibilidad, latencia y velocidad por servicio.

---

## Estructura del proyecto

```
CX-Radar/
├── bin/                  ← Herramientas portables (node, fast-cli, yt-dlp)
├── config/
│   └── probe-catalog.json  ← Configuración de la sonda y servicios
├── docs/                 ← Documentación técnica detallada
├── grafana/
│   └── dashboards/       ← Definiciones de paneles para Grafana
├── logs/                 ← Logs diarios de cada ejecución
├── scripts/
│   ├── qoe-probe.ps1           ← Script principal de la sonda
│   ├── validate-qoe-probe.ps1  ← Validación del entorno
│   ├── register-qoe-task.ps1   ← Registro de tarea programada
│   ├── set-influx-token.ps1    ← Guardado seguro del token
│   └── setup-portable.ps1      ← Descarga de herramientas portables
└── tmp/                  ← Archivos temporales (se limpian automáticamente)
```

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
