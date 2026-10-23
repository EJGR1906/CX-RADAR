# Visión Detallada de Funcionalidades y Servicios Monitoreados

Este documento describe de forma clara y accesible para ejecutivos las capacidades operativas actuales de la solución CX-Radar, los servicios web que supervisa y los indicadores de desempeño que recopila.

---

## 1. Servicios Web Monitoreados

CX-Radar efectúa pruebas sintéticas periódicas orientadas a simular la navegación y el consumo real de usuarios corporativos. La configuración predeterminada incluye los siguientes destinos clave:

### Microsoft (Herramientas Nube y Productividad)
- **Objetivo**: Evaluar la calidad de conexión con la infraestructura en la nube de Microsoft (incluyendo Office 365 y servicios de Azure).
- **Metodología**: Descarga un archivo de prueba real mediante peticiones por rangos HTTP optimizados y realiza una prueba de subida de datos.
- **Resultado Esperado**: Garantiza que las aplicaciones colaborativas y la transferencia de archivos corporativos funcionen con fluidez.

### YouTube (Reproducción de Video y Contenidos)
- **Objetivo**: Medir la capacidad de la red local para sostener transmisiones de video en alta definición (4K).
- **Metodología**: Utiliza la herramienta portable `yt-dlp` para descargar fragmentos reales de video de YouTube sin almacenar el contenido en disco de forma permanente.
- **Resultado Esperado**: Verifica la tasa de transferencia continua exigida por plataformas educativas y de streaming.

### Netflix (Infraestructura de Entrega de Contenidos CDN)
- **Objetivo**: Determinar el ancho de banda disponible hacia servidores de distribución de contenido de alta exigencia.
- **Metodología**: Ejecuta la herramienta portable `fast-cli` sobre un motor aislado de Node.js que realiza pruebas contra la red de servidores de Fast.com.
- **Resultado Esperado**: Ofrece un indicador independiente de la capacidad de procesamiento del enlace de internet.

### Disney+ (Acceso a Redes de Distribución Multimedia)
- **Objetivo**: Monitorear el tiempo de respuesta e integridad en servicios de transmisión multimedia.
- **Metodología**: Descarga recursos públicos optimizados desde la red de distribución (CDN) de Disney+.
- **Resultado Esperado**: Evalúa la estabilidad y latencia en el acceso a plataformas globales de contenido.

### Amazon AWS (Servicios e Infraestructura en la Nube)
- **Objetivo**: Supervisar la conectividad hacia los centros de datos de Amazon Web Services.
- **Metodología**: Realiza peticiones de baja latencia hacia activos almacenados en Amazon S3/AWS.
- **Resultado Esperado**: Asegura la disponibilidad de aplicaciones empresariales alojadas en la nube de Amazon.

---

## 2. Indicadores de Desempeño Recopilados

La plataforma recopila métricas técnicas y las convierte en indicadores claros sobre el estado de la red:

### Disponibilidad del Servicio (%)
Indica si el destino web respondió correctamente a la prueba. Permite detectar interrupciones parciales o totales de servicios externos de forma inmediata.

### Latencia de Respuesta (Milisegundos - ms)
El tiempo que tarda una señal en ir desde la red local hasta el servidor remoto y regresar. Latencias bajas reflejan una navegación ágil e interactiva, mientras que latencias altas provocan lentitud perceptible.

### Jitter / Variabilidad (Milisegundos - ms)
Mide la inestabilidad o fluctuación en los tiempos de respuesta. Un jitter elevado afecta negativamente las llamadas de voz, videoconferencias y aplicaciones en tiempo real, causando distorsiones o cortes.

### Velocidad de Descarga y Subida (Mbps)
La tasa de datos real transferida por segundo. Refleja la capacidad efectiva del enlace de internet para bajar archivos grandes o subir información a la nube.

### Responsiveness / RPM (Respuestas por Minuto)
Evalúa la agilidad del enlace y la capacidad del router local para gestionar peticiones consecutivas cuando la red se encuentra en uso activo.

### Bufferbloat (Retardo bajo Carga - ms)
Mide cuánto aumenta la latencia de la red cuando se realiza una descarga o subida intensiva. Un valor elevado de bufferbloat indica que las llamadas o la navegación se congelarán cuando alguien en la oficina descargue un archivo pesado.

### Salud del Router Local (Latencia de Gateway - ms)
Mide el tiempo de respuesta del router de la sede (puerta de enlace). Permite discernir si un problema de lentitud se origina en el propio router de la oficina o en la red externa del proveedor de internet.

### Pérdida de Paquetes (%)
Porcentaje de datos que no llegaron a su destino durante la prueba. La pérdida de paquetes es la causa principal de congelamientos en transmisiones y reintentos de conexión.

---

## 3. Capacidades de Automantenimiento y Resiliencia

CX-Radar ha sido diseñado para operar de forma autónoma durante meses sin requerir intervención técnica constante:

- **Limpieza Automática de Disco**: Al inicio de cada ciclo de prueba, la sonda elimina automáticamente archivos temporales (`*.tmp`, `*.bak`) mayores a 20 minutos y gestiona la rotación de logs antiguos, evitando el consumo desmedido de espacio en disco.
- **Tolerancia a Fallas de Red**: Si un servidor web o un servidor DNS externo no responde, la sonda registra el incidente específico y continúa evaluando los demás destinos sin detener la prueba ni colapsar.
- **Aislamiento de Entorno**: Las herramientas auxiliares (`Node.js`, `fast-cli`, `yt-dlp`, `curl`) operan dentro del directorio del proyecto sin modificar el registro del sistema operativo ni requerir permisos especiales de instalación.
- **Actualización Atómica Remota**: El script de actualización verifica firmas digitales de código (SHA-256) contra el repositorio central y aplica mejoras de forma segura sin interrumpir la operación.
