# CX-Radar

**Solución Automatizada de Monitoreo de Calidad de Experiencia (QoE) en Servicios Web**

CX-Radar es una plataforma corporativa diseñada para evaluar de forma continua y objetiva la calidad de los servicios web críticos para la organización (como Microsoft, YouTube, Netflix, Disney+ y Amazon) desde la perspectiva de la red local.

---

## 1. Propósito Ejecutivo

En entornos corporativos e industriales, los problemas de lentitud o degradación de servicios digitales suelen identificarse de forma reactiva, cuando los usuarios finales ya experimentan impactos en su productividad. 

CX-Radar resuelve este desafío realizando mediciones automáticas y frecuentes directamente desde la infraestructura local, ofreciendo los siguientes beneficios estratégicos:

- **Detección Temprana de Incidentes**: Identifica ralentizaciones, caídas de velocidad o interrupciones de servicio antes de que afecten a la operación de los usuarios.
- **Métricas Objetivas para SLAs**: Reemplaza apreciaciones subjetivas ("la red está lenta") por indicadores cuantitativos precisos (latencia en milisegundos, variabilidad de respuesta y velocidades reales de transferencia en Mbps).
- **Análisis de Tendencias y Patrones**: Conserva registros históricos que permiten comparar el comportamiento de la red entre distintos horarios, días o proveedores de internet (ISP).
- **Cero Impacto en la Infraestructura**: Funciona de forma aislada sin modificar variables globales ni instalar componentes permanentes en el sistema operativo anfitrión.

---

## 2. Visión General del Funcionamiento

El flujo de información se estructura en tres capas principales:

```
┌───────────────────────────┐      ┌───────────────────────────┐      ┌───────────────────────────┐
│     Sonda Local           │ ───> │     InfluxDB Cloud        │ ───> │     Grafana Cloud         │
│  (Ejecución en servidor)  │      │  (Base de datos temporal) │      │  (Paneles y alertas)      │
└───────────────────────────┘      └───────────────────────────┘      └───────────────────────────┘
```

1. **Sonda Local de Medición**: Un componente ligero en Python 3 que se ejecuta periódicamente en el servidor de la sede. Realiza pruebas de conexión, velocidad y latencia hacia los puntos finales configurados.
2. **Almacenamiento Centralizado en la Nube**: Las mediciones se transmiten de forma segura mediante HTTPS a InfluxDB Cloud, donde se consolidan en series temporales protegidas.
3. **Visualización y Alertas en Tiempo Real**: Grafana Cloud consulta estos datos para presentar paneles ejecutivos consolidados, mapas de estado y alertas automáticas ante anomalías.

---

## 3. Servicios Monitoreados y Métricas Clave

La configuración estándar de CX-Radar evalúa los principales canales de contenido y plataformas de productividad:

| Servicio / Destino | Objeto de la Prueba | Métricas Evaluadas |
|---|---|---|
| **Microsoft** | Descarga e interacción con almacenamiento en la nube de Microsoft | Latencia, velocidad de subida/bajada y estabilidad bajo carga |
| **YouTube** | Descarga directa de segmentos de video de alta definición (4K) | Velocidad de transferencia real y tasa de respuesta |
| **Netflix** | Medición de rendimiento contra servidores de entrega Fast.com | Rendimiento de descarga extremo a extremo |
| **Disney+** | Acceso a recursos multimedia del CDN global de Disney | Disponibilidad y tiempo de respuesta inicial |
| **Amazon (AWS)** | Descarga de activos en la nube de Amazon Web Services | Latencia, tasa de transferencia y verificación de ruta TCP |

Para todos los objetivos, la sonda calcula adicionalmente: **Disponibilidad** (porcentaje de respuesta exitosa), **Latencia** (tiempo de respuesta en milisegundos), **Jitter** (variación del tiempo de respuesta) y **Bufferbloat** (comportamiento de la latencia bajo tráfico intenso).

---

## 4. Estructura de la Documentación Ejecutiva

La documentación del proyecto se encuentra organizada en archivos especializados para facilitar la consulta según la perspectiva requerida:

- **[Visión Detallada de Funcionalidades](docs/FUNCIONALIDADES.md)**: Descripción accesible de cada funcionalidad, servicios monitoreados y rutina de automantenimiento.
- **[Guía de Instalación y Operación](docs/GUIA_DE_USO.md)**: Manual paso a paso para el despliegue mediante el instalador automatizado o métodos personalizados.
- **[Resumen Ejecutivo de Cambios Recientes](docs/CAMBIOS_RECIENTES.md)**: Evolución del proyecto, migración multiplataforma a Python 3 e incorporación de nuevas métricas.
- **[Arquitectura Ejecutiva del Sistema](docs/ARQUITECTURA_EJECUTIVA.md)**: Estructura técnica detallada, aislamiento de componentes y seguridad de datos.
- **Reporte de Experiencia del Cliente (CX)**: Documentación de métricas y operabilidad del script procesador de reportes (`docs/REPORTE_CX_CONFIDENCIAL.md`, mantenido en estricta confidencialidad local).

---

## 5. Inicio Rápido para Operadores

Para poner en marcha la sonda en cualquier servidor (compatible con Windows, Linux o macOS):

1. **Verificar Requisitos**: El equipo debe contar con **Python 3.8 o superior** instalado y acceso a internet.
2. **Ejecutar el Instalador Automatizado**:
   Abra una terminal en la carpeta del proyecto y ejecute:
   ```bash
   python scripts/install.py
   ```
   El instalador solicitará de forma interactiva la identificación de la sede, credenciales de InfluxDB y el intervalo de ejecución deseado, configurando automáticamente las herramientas portables y la tarea programada del sistema operativo.

3. **Verificar el Estado**:
   Puede validar en cualquier momento que la sonda esté lista ejecutando:
   ```bash
   python scripts/validate_qoe_probe.py
   ```

---

## 6. Mantenimiento Automático y Compatibilidad

- **Sin Alteraciones al Sistema**: Todas las herramientas de prueba adicionales se descargan de forma portable dentro del directorio `bin/` del proyecto.
- **Limpieza Automática**: Al inicio de cada ciclo de prueba, la sonda elimina archivos temporales antiguos y gestiona la rotación de logs de forma autónoma.
- **Soporte Multiplataforma y Servidores Heredados**: Compatible de forma nativa con Windows 10/11, Windows Server (incluyendo versión 2012 R2), Linux y macOS.
