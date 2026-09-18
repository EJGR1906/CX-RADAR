# Stack Tecnológico de CX-Radar

Este documento define la pila de software, dependencias externas, requisitos del sistema y restricciones de programación para la sonda de calidad de experiencia CX-Radar.

---

## Entorno Principal de Ejecución y Lenguaje

- **Entorno Principal**: **Python 3** (requiere versión 3.8 o superior).
  - **Restricción**: **Biblioteca Estándar Únicamente**. No se permiten paquetes externos de PyPI (`pip install`) para la ejecución regular de la sonda. Esto garantiza una ejecución ligera y despliegues sencillos en servidores heterogéneos.
  - **Sistemas Heredados**: Se requiere Python 3.10.x para sistemas operativos como Windows Server 2012 R2.
- **Depreciación de PowerShell**: Se eliminó todo el código heredado en `.ps1`. Todo el desarrollo se realiza en Python 3.

---

## Herramientas Portables de Terceros

Para ejecutar pruebas que simulan actividades de usuarios reales, la sonda utiliza herramientas portables independientes almacenadas en el directorio `/bin`, las cuales no requieren instalación en el sistema:

| Herramienta / Binario | Entorno de Ejecución | Propósito |
|---|---|---|
| **Node.js** | Binario portable (v20 estándar, v16 para WS 2012 R2) | Ejecuta el paquete de medición de velocidad de Netflix. |
| **fast-cli** | Script empaquetado de Node.js | Realiza pruebas de velocidad contra los servidores de Fast.com / Netflix. |
| **yt-dlp** | Binario portable compilado | Descarga segmentos de video de YouTube para medir la velocidad real de transferencia. |
| **curl** | Binario portable del sistema | Realiza transacciones HTTP de baja latencia. |

---

## Servicios Externos y Flujo de Ingesta

```
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  Sonda Python 3  │ ───> │  InfluxDB Cloud  │ ───> │  Grafana Cloud   │
│ (Servidor Local) │      │ (Base de Datos)  │      │    (Tableros)    │
└──────────────────┘      └──────────────────┘      └──────────────────┘
```

1. **Puerto de Ingesta**: API HTTP de Line Protocol de InfluxDB v2 sobre HTTPS.
2. **Motor de Base de Datos**: InfluxDB Cloud (Almacenamiento por Buckets).
3. **Motor de Visualización**: Grafana Cloud.
4. **Lenguaje de Consulta**: Flux (para extraer métricas desde InfluxDB).

---

## Gestión de Configuración

- **`config/probe-catalog.json`**: Define propiedades de la sonda (`probeId`, `site`, `environment`, `isp`) y el catálogo de objetivos (`targets`) a monitorear.
- **`.env` (Credenciales Locales)**: Almacenado en la raíz del proyecto con permisos de acceso restringidos. Contiene el token de InfluxDB (`INFLUX_TOKEN`). No debe ser incluido en control de versiones.

---

## Esquema de Métricas de Monitoreo

Las métricas se transmiten a InfluxDB bajo tres mediciones principales:
- **`qoe_http_check`**: Latencia, disponibilidad y códigos de respuesta para servicios HTTP regulares.
- **`qoe_real_metrics`**: Velocidades de descarga/subida, jitter, bufferbloat y calidad de conexión para Netflix y YouTube.
- **`qoe_probe_run`**: Metadatos internos sobre la ejecución de la sonda (duración de ciclo, errores).

---

## Flujo de Validación Local

Antes de registrar cambios, los operadores o desarrolladores pueden validar su código mediante la siguiente secuencia:

1. **Verificación de Entorno**:
   ```bash
   python scripts/validate_qoe_probe.py
   ```
2. **Ejecución en Seco (sin escritura en red)**:
   ```bash
   python scripts/qoe_probe.py --skip-influx-write
   ```
3. **Ejecución Completa**:
   ```bash
   python scripts/qoe_probe.py
   ```
4. **Pruebas de Certificación y Resiliencia**:
   ```bash
   python scripts/run_qoe_certification.py --run-resilience-checks
   ```
