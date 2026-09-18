# Registro de Avance de CX-Radar

Este documento registra las fases de desarrollo completadas, las líneas de trabajo activas y las tareas proyectadas en la hoja de ruta del proyecto.

---

## Línea de Trabajo Activa: Inicialización y Estabilización Multiplataforma
- **Objetivo**: Garantizar el despliegue universal en servidores corporativos.
- **Tareas**:
  - [x] Recopilar requisitos del proyecto y restricciones desde `README.md` y `AGENTS.md`.
  - [x] Actualizar documentación estratégica del producto (`product.md`).
  - [x] Definir especificaciones de la pila tecnológica (`techstack.md`).
  - [x] Establecer el registro de seguimiento de trabajo (`tracks.md`).
  - [x] Ejecutar verificaciones de validación para comprobar el entorno local.

---

## Fases Completadas

### 1. Migración de PowerShell a Python 3
- **Objetivo**: Migrar los scripts de sonda heredados exclusivamente de Windows en PowerShell a una implementación unificada en Python 3 multiplataforma.
- **Detalles**:
  - Eliminados los scripts heredados `.ps1` y sus pruebas asociadas.
  - Implementado el gestor portable de herramientas (`scripts/setup_portable.py`) para descargar ejecutables compatibles de Node.js, `fast-cli` y `yt-dlp`.
  - Migrada la lógica de la sonda (`scripts/qoe_probe.py`) a Python 3 utilizando únicamente módulos de la biblioteca estándar.
  - Estandarizada la generación e ingesta del protocolo de líneas de InfluxDB.

### 2. Blindaje de Seguridad en Scripts de Sonda
- **Objetivo**: Mitigar posibles vulnerabilidades de inyección de comandos en las ejecuciones del script.
- **Detalles**:
  - Corregida la vulnerabilidad de inyección de comandos en las funciones de limpieza de caché de Puppeteer.
  - Refactorizada la lógica de invocación de procesos hijos (`subprocess`) para pasar argumentos de forma segura como listas, evitando la fragmentación por cadenas en la línea de comandos.

---

## Hoja de Ruta y Pendientes

### 1. Integración de Pruebas Masivas de Ancho de Banda
- **Objetivo**: Añadir mediciones dedicadas de tasa de transferencia utilizando LibreSpeed o WebPageTest.
- **Restricción**: Debe mantenerse separado de la vía sintética HTTP activa (`qoe_http_check`) para evitar la saturación de colas del sistema.

### 2. Ajuste de Alertas en Tableros de Grafana
- **Objetivo**: Optimizar las consultas de alerta en Flux para evitar notificaciones de falsos positivos por desconexiones aisladas de la sonda.
- **Tareas**:
  - Ajustar rangos de alerta por jitter.
  - Introducir parámetros de promedios móviles para suavizar picos de latencia de corta duración.
