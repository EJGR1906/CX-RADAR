# Resumen Ejecutivo de Cambios Recientes e Historial de Evolución

Este documento resume las principales mejoras, optimizaciones arquitectónicas y evoluciones funcionales incorporadas recientemente a la plataforma CX-Radar.

---

## 1. Migración Universal a Python 3 (Multiplataforma)

- **Descripción del Cambio**: Se eliminaron completamente las dependencias de scripts heredados en PowerShell (`.ps1`), reescribiendo la sonda principal y todos los scripts auxiliares en Python 3 de forma multiplataforma.
- **Beneficio para la Organización**: Permite desplegar la misma solución en servidores con Windows, Linux o macOS de manera unificada.
- **Aislamiento Tecnológico**: La sonda utiliza exclusivamente la biblioteca estándar de Python 3, eliminando la necesidad de instalar paquetes externos adicionales (`pip install`) para la ejecución regular.

---

## 2. Incorporación de Nuevas Métricas de Calidad de Experiencia

Se amplió la suite de mediciones para obtener una visión más precisa del rendimiento de la red:

- **Bufferbloat (Descarga y Subida)**: Medición del incremento de latencia cuando el canal de comunicación opera a su máxima capacidad.
- **Salud del Router Local (Gateway Latency)**: Monitoreo aislado del tiempo de respuesta de la puerta de enlace de la sede para separar problemas locales de fallas del proveedor de internet.
- **Capacidad de Respuesta bajo Carga (RPM)**: Cálculo de respuestas por minuto para medir la agilidad del enlace.
- **Pérdida de Paquetes (%)**: Registro del porcentaje de pérdida de tráfico durante la ejecución de las pruebas sintéticas.

---

## 3. Integración del Generador de Reportes CX (`scripts/cx__report.py`)

- **Descripción del Cambio**: Se desarrolló un procesador inteligente que consolida registros históricos (locales y descargados automáticamente de InfluxDB Cloud) en informes ejecutivos en Excel, CSV o texto.
- **Valor Operativo**: Clasifica las mediciones por marca/modelo de router y tipo de conexión (Wi-Fi o Ethernet), aplicando reglas automáticas de diagnóstico para emitir alertas cualitativas de calidad de experiencia.

---

## 4. Sistema de Actualización Automática y Atómica (`scripts/update_qoe_probe.py`)

- **Descripción del Cambio**: Se incorporó un mecanismo de actualización diaria desatendida.
- **Seguridad**: Compara los códigos de verificación digital (hashes SHA-256) del servidor local contra el repositorio central en GitHub y aplica actualizaciones de forma atómica sin interrumpir las pruebas programadas.

---

## 5. Optimizaciones de Rendimiento y Evasión de Bloqueos

- **Evasión de Restricciones en Fast.com (Netflix)**: Se aplicaron parches para evitar bloqueos por parte de los servidores de medición de Netflix cuando identifican automatización, reduciendo los tiempos de prueba exitosa a pocos segundos.
- **Optimización de Ancho de Banda en Pruebas de Microsoft**: Se implementó el uso de encabezados HTTP por rangos (`Range-requests`). Esto permite verificar la conectividad real con los servidores de Microsoft descargando únicamente una muestra representativa (8 MB) en lugar del archivo completo de 95 MB, reduciendo el consumo de datos de la sede en más de un 90%.

---

## 6. Soporte para Entornos Heredados (Windows Server 2012 R2)

- **Compatibilidad Extendida**: Se añadieron rutinas automáticas que detectan sistemas operativos heredados y ajustan las herramientas portables (descargando versiones compatibles de Node.js como la v16) para garantizar el funcionamiento transparente en servidores de generaciones anteriores.
