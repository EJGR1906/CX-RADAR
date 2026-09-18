# Contexto de Producto CX-Radar

CX-Radar es una solución automatizada de monitoreo de Calidad de Experiencia (QoE) diseñada para ejecutarse de forma continua en sondas de red local. Mide, registra y emite alertas sobre el rendimiento de servicios web clave (Microsoft, YouTube, Netflix, Disney+, Amazon) desde la perspectiva de la infraestructura local.

---

## Objetivos del Producto

1. **Monitoreo y Alertamiento Proactivo**: Detectar latencias de respuesta, caídas en velocidades de descarga/subida e interrupciones de servicio antes de que los usuarios finales las reporten.
2. **Datos Objetivos de Rendimiento**: Capturar indicadores cuantitativos concretos (latencia en milisegundos, jitter y tasas de transferencia en Mbps) para facilitar la verificación de acuerdos de nivel de servicio (SLA) y la resolución de problemas con proveedores de internet (ISP).
3. **Análisis de Tendencias**: Proporcionar registros históricos persistentes para identificar patrones diarios o semanales de degradación del rendimiento.
4. **Cero Contaminación del Sistema Operativo**: Utilizar herramientas portables y aisladas (`node`, `fast-cli`, `yt-dlp`, `curl`) para garantizar que los archivos globales, variables o configuraciones del sistema anfitrión no se modifiquen.
5. **Adaptabilidad Multiplataforma**: Compatible con entornos modernos y heredados (Windows, Windows Server 2012 R2, Linux y macOS) a partir de una única base de código.

---

## Alcance y Exclusiones

- **Pruebas de Ancho de Banda Masivo**: La herramienta está optimizada para el monitoreo sintético de vías HTTP. Las pruebas dedicadas de velocidad masiva (como integraciones con LibreSpeed o WebPageTest) se mantienen separadas del flujo activo de la sonda.
- **Configuración Gráfica de Usuario**: Toda la configuración se gestiona mediante archivos de entrada estructurados (`config/probe-catalog.json`). No se incluye una interfaz gráfica interactiva para la configuración de la sonda.
- **Instaladores Nativos del Sistema**: La instalación se apoya en los planificadores de tareas nativos del sistema operativo (Task Scheduler de Windows, systemd, cron, launchd).

---

## Perfiles de Usuario Destinados

### 1. Operadores de Red (NetOps) e Ingenieros SRE
- **Necesidades**: Sondas estables, precisas y ligeras que no agoten los recursos locales. Requieren métricas estructuradas en una base de datos de series temporales (InfluxDB) y tableros personalizables en Grafana.
- **Puntos de Dolor**: Scripts inestables que fallan sin notificación o dependencias complejas que exigen actualizaciones manuales en múltiples equipos remotos.

### 2. Gerentes de Soporte de TI y Helpdesk
- **Necesidades**: Notificación temprana cuando un servicio principal (como Microsoft Office 365 o YouTube) comienza a responder con lentitud, permitiendo tomar medidas antes de recibir un alto volumen de incidentes.
- **Puntos de Dolor**: Reportes subjetivos de lentitud por parte de usuarios sin datos cuantitativos para determinar si el origen es del proveedor de internet, la red Wi-Fi local o el servicio externo.

---

## Funcionalidades Principales

- **Ejecución de Sonda Multiservicio**: Evaluación continua de latencia, jitter, velocidad de descarga (usando `fast-cli` para Netflix y `yt-dlp` para YouTube) y códigos de estado HTTP.
- **Almacenamiento Seguro de Configuración**: Restricción de permisos en archivos locales de credenciales (`.env`).
- **Arquitectura de Red Resiliente**: Manejo transparente de fallas de DNS, tiempos de espera en base de datos y endpoints no disponibles sin interrumpir el ciclo de prueba.
- **Rutina de Automantenimiento**: Eliminación automática de archivos temporales y rotación de logs para prevenir la saturación del espacio en disco.
- **Actualizador Atómico**: Verificación de firmas digitales SHA-256 contra el repositorio central e instalación atómica de actualizaciones.
