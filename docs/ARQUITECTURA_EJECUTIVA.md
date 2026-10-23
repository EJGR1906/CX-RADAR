# Arquitectura Ejecutiva del Sistema y Flujo de Información

Este documento describe la estructura arquitectónica de la solución CX-Radar, su diseño de almacenamiento y los principios de seguridad aplicados en la recolección y transmisión de métricas.

---

## 1. Diseño Arquitectónico General

La solución adopta una arquitectura desacoplada de tres capas diseñada para garantizar un impacto mínimo en el servidor anfitrión y una alta disponibilidad en la recolección de datos:

```
┌─────────────────────────────────┐
│     Capa 1: Recolección         │
│  Sonda Local de Medición        │
│  - Intérprete Python 3          │
│  - Herramientas Portables (bin/)│
└─────────────────────────────────┘
                │
                │ Transmisión Segura (HTTPS)
                ▼
┌─────────────────────────────────┐
│     Capa 2: Almacenamiento      │
│  InfluxDB Cloud                 │
│  - Series Temporales            │
│  - Medición por Medidas (Bucket)│
└─────────────────────────────────┘
                │
                │ Consulta (Lenguaje Flux)
                ▼
┌─────────────────────────────────┐
│     Capa 3: Visualización       │
│  Grafana Cloud                  │
│  - Paneles Nacionales y Detalle │
│  - Reglas de Alerta Operativas  │
└─────────────────────────────────┘
```

---

## 2. Descripción de las Capas del Sistema

### Capa 1: Recolección y Procesamiento Local (Sonda)
- **Motor Principal**: Ejecutado por un interprete Python 3. El código fuente está estructurado para depender únicamente de módulos nativos de la biblioteca estándar de Python, evitando la instalación de librerías de terceros.
- **Herramientas Portables Aisladas**: Para realizar las pruebas de navegación sintética hacia los destinos web, la sonda invoca ejecutables portables contenidos de forma aislada en el directorio `bin/`:
  - `curl`: Ejecutable portable para transacciones HTTP de baja latencia.
  - `Node.js` + `fast-cli`: Entorno aislado para ejecutar las pruebas contra servidores de Netflix.
  - `yt-dlp`: Herramienta portable para medir descargas de flujos de video real desde YouTube.

### Capa 2: Almacenamiento en Series Temporales (InfluxDB Cloud)
- Las mediciones recolectadas en cada ciclo se estructuran bajo el protocolo de líneas de InfluxDB y se envían mediante conexiones HTTPS seguras.
- Las métricas se clasifican en tres mediciones principales:
  - `qoe_http_check`: Disponibilidad, tiempos de respuesta y códigos de estado HTTP para endpoints regulares.
  - `qoe_real_metrics`: Velocidades de descarga/subida, latencia, jitter, bufferbloat y latencia de gateway.
  - `qoe_probe_run`: Metadatos de ejecución de la propia sonda (duración de la prueba, estado de ejecución).

### Capa 3: Visualización y Alertas (Grafana Cloud)
- Grafana Cloud realiza consultas continuas a InfluxDB mediante el lenguaje Flux.
- Proporciona dos niveles de tableros ejecutivos:
  - **Nivel Consolidado Nacional**: Muestra el mapa de sedes, estado global de servicios e indicadores de calidad acumulados.
  - **Nivel de Detalle Operativo**: Permite realizar diagnósticos puntuales por servidor, analizando el comportamiento histórico de latencias y velocidades.

---

## 3. Principios Fundamentales de Diseño

- **Cero Contaminación de Infraestructura**: CX-Radar no modifica variables del sistema operativo, ni instala servicios globales ni altera registros del servidor. Todo su funcionamiento está circunscrito a su directorio de instalación.
- **Seguridad y Protección de Credenciales**: El token de acceso a InfluxDB se almacena en el archivo `.env` local con permisos de lectura restringidos a nivel de sistema operativo mediante el script `scripts/set_influx_token.py`.
- **Integración con Planificadores Nativos**: La programación periódica de la sonda no requiere agentes de terceros corriendo de forma continua en memoria; utiliza los planificadores nativos del sistema operativo (Task Scheduler en Windows, systemd o cron en Linux, launchd en macOS).
