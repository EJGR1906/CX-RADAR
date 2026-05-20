# Changelog

All notable changes to CX-Radar are documented here.

## [Unreleased] — 2026-05-20

### Optimizaciones de Rendimiento

#### Speedtest con HTTP Range Headers (`scripts/qoe-probe.ps1`)
- **Problema:** El método de speedtest `burst` descargaba los archivos completos del servidor
  (hasta 95 MB en el caso de Microsoft) sin importar el tamaño de muestra configurado. Esto
  causaba que los ciclos de prueba superaran los 2 minutos, lo que agotaba el timeout del
  smoke test de certificación.
- **Solución:** `Invoke-BurstTrafficMeasurement` ahora construye un encabezado HTTP `Range`
  (`bytes=0-N`) dinámico cuando el target tiene `targetTransferBytes` configurado, de manera
  que cada iteración de descarga solicita exactamente los bytes pendientes para completar la
  muestra objetivo. Esto reduce el volumen de datos transferidos en tests de Microsoft de ~95 MB
  a 8 MB, cortando el tiempo de ejecución del target de ~2 min a ~10-20 s.

#### Límite de Descarga para el Target Microsoft (`config/probe-catalog.json`)
- Se añadieron `"targetTransferBytes": 8388608` (8 MB) y `"maxDownloadIterations": 4` al
  target `microsoft-100mb-test`. Ahora el URL del ejecutable de Microsoft sigue siendo el mismo
  (garantiza conectividad real al CDN de Microsoft), pero solo se descargan los primeros 8 MB
  en una sola iteración Range-request, al igual que el resto de los targets `burst`.

### Mejoras de Confiabilidad

#### Logging Detallado en Fallas de Escritura a InfluxDB (`scripts/qoe-probe.ps1`)
- Las dos llamadas `Invoke-RestMethod` hacia la API de escritura de InfluxDB ahora están
  envueltas en bloques `catch [System.Net.WebException]`. Cuando InfluxDB responde con un
  código de error HTTP (ej. 401 token inválido, 404 bucket no encontrado, 429 rate limit),
  el script extrae el cuerpo de la respuesta HTTP y lo incrusta en el mensaje de excepción
  relanzado. Antes solo se veía el mensaje genérico de .NET sin detalles del error remoto.

#### Limpieza del Directorio Temporal en Certificación (`scripts/run-qoe-certification.ps1`)
- El bloque de ejecución de escenarios fue envuelto en `try-finally`. El bloque `finally`
  elimina recursivamente el directorio temporal (`cx-radar-qa-*`) creado en `$env:TEMP`
  al inicio de cada corrida, tanto si los tests pasan como si fallan. Antes estos directorios
  se acumulaban en `%TEMP%` y debían limpiarse manualmente.

### Limpieza y Ahorro de Espacio

#### Eliminación del Zip de Node.js post-instalación (`scripts/setup-portable.ps1`)
- La lógica de descarga de Node.js fue optimizada:
  - Si el runtime portable ya está correctamente instalado (`Test-PortableNodeRuntime`), no se
    descarga ni descomprime el zip de Node.js (ahorro de tiempo y ~30 MB de descarga).
  - Si la instalación es necesaria y se descarga el zip, este se elimina automáticamente
    después de la extracción exitosa.
- Se eliminó manualmente el zip `bin/_downloads/node-v20.20.2-win-x64.zip` (~29 MB) que
  quedaba residual de la instalación inicial.

#### Eliminación del Dashboard Unificado Legado
- Se eliminó `grafana/dashboards/qoe-http-overview.json` (dashboard unificado anterior),
  reemplazado por los dos dashboards especializados creados en la sesión previa.

### Documentación

#### `docs/observability/grafana-cloud-setup.md`
- Actualizado para reflejar la nueva arquitectura de dashboards divididos:
  - `qoe-national-global.json`: Vista Global Nacional (mapa + métricas agregadas por sonda)
  - `qoe-probe-detail.json`: Detalle por Sonda (drilldown completo por sonda individual)
- Se añadió descripción de todos los paneles en ambos dashboards.
- Se actualizó la sección de mediciones para incluir `qoe_real_metrics`.
- Se actualizó la sección de templating para reflejar el modelo de variables actual
  (solo `probe_id` en el dashboard de detalle; sin variables en el global).

#### `README.md`
- Actualizada la sección "Ver los resultados" para referenciar los dos nuevos dashboards
  en lugar del dashboard unificado eliminado.

---

## Sesión Anterior — 2026-05-20

### Nuevas Funcionalidades

- Creación del dashboard **Vista Global Nacional** (`qoe-national-global.json`) con mapa
  geográfico dark-mode de Venezuela usando CartoDB Dark Matter.
- Creación del dashboard **Detalle por Sonda** (`qoe-probe-detail.json`) con 13 paneles
  y variable de filtrado por `probe_id`.
- Implementación del builder de dashboards en Node.js (`grafana/builders/`) que genera los
  JSON desde definiciones modulares (`panel-helpers.js`, `global-panels.js`, `detail-panels.js`).
- Separación de targets HTTP sintéticos y speedtest en métricas diferenciadas.
- Implementación de la medición `qoe_real_metrics` para datos de velocidad y calidad real.
- Implementación del garbage collector de artefactos y logs en el probe principal.
