// detail-panels.js — Panel definitions for the Detail (Per-Probe) tab
const P = `r.probe_id == "\${probe_id}"`;

const { SVC_OVERRIDES, CONNECTION_MAPPINGS, NO_INTERNET_CODES } = require('./panel-helpers');

// Monitor de cada minuto (qoe_heartbeat_status): 1.0 si en ese minuto no habia internet.
const HB = `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "status_code")
  |> filter(fn: (r) => ${P})
  |> group()
  |> sort(columns: ["_time"])`;
const DOWN = `|> map(fn: (r) => ({_time: r._time, _value: if contains(value: int(v: r._value), set: [${NO_INTERNET_CODES.join(', ')}]) then 1.0 else 0.0}))`;
const hbSeries = (field) => `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat" and r._field == "${field}")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["check"])
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.check, _value: r._value}))
  |> group(columns: ["_field"])`;

exports.panels = [
  // --- Conexion: monitor de cada minuto ---
  ['detail-conn-uptime', 'stat', {
    title: 'Internet Disponible', id: 214,
    desc: 'Porcentaje de minutos del rango en que la sonda tuvo internet (segun el monitor de cada minuto). Degradado y microcortes cuentan como disponible. Los minutos en que la sonda no reporto no se cuentan.',
    flux: `${HB}
  ${DOWN}
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Internet disponible", _value: (1.0 - r._value) * 100.0}))
  |> group(columns: ["_field"])`,
    unit: 'percent', max: 100, min: 0, decimals: 2,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 99 }, { color: 'green', value: 99.9 }]
  }],

  ['detail-conn-down-minutes', 'stat', {
    title: 'Minutos sin Internet', id: 215,
    desc: 'Minutos del rango en que el monitor diagnostico caida de acceso, de transito, de router, de red local, de DNS o internet interceptado.',
    flux: `${HB}
  ${DOWN}
  |> sum()
  |> map(fn: (r) => ({_time: now(), _field: "Minutos sin internet", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'none', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 1 }, { color: 'red', value: 10 }]
  }],

  ['detail-conn-cuts', 'stat', {
    title: 'Cortes', id: 216,
    desc: 'Numero de veces que la conexion paso de funcionar a no tener internet en el rango.',
    flux: `${HB}
  ${DOWN}
  |> difference(nonNegative: false)
  |> map(fn: (r) => ({_time: r._time, _value: if r._value > 0.0 then 1.0 else 0.0}))
  |> sum()
  |> map(fn: (r) => ({_time: now(), _field: "Cortes", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'none', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 1 }, { color: 'red', value: 5 }]
  }],

  ['detail-conn-blackout', 'stat', {
    title: 'Segundos en Microcortes', id: 217,
    desc: 'Suma de los segundos en que no respondio ningun destino dentro de las ventanas de 45 s del monitor (resolucion de 5 s).',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "blackout_s")
  |> filter(fn: (r) => ${P})
  |> group()
  |> sum()
  |> map(fn: (r) => ({_time: now(), _field: "Segundos sin respuesta", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 's', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 10 }, { color: 'red', value: 120 }]
  }],

  ['detail-conn-timeline', 'state-timeline', {
    title: 'Estado de la Conexion (cada minuto)', id: 218,
    desc: 'Diagnostico del monitor de cada minuto. Si el rango agrupa varios minutos se muestra el codigo mas alto del grupo. Los huecos son minutos sin reporte (equipo apagado o datos aun no reenviados).',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "status_code")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: max, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: "Conexion", _value: r._value}))
  |> group(columns: ["_field"])`,
    mappings: CONNECTION_MAPPINGS
  }],

  ['detail-services-timeline', 'state-timeline', {
    title: 'Servicios Externos (Outlook, Microsoft 365, Teams)', id: 219,
    desc: 'Resultado de cada prueba HTTPS de servicios externos del monitor de cada minuto. Solo se evaluan cuando la red de la sonda funciona: un hueco significa que la sonda no tenia internet.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_service_check" and r._field == "available")
  |> filter(fn: (r) => ${P})
  |> map(fn: (r) => ({r with _value: if r._value then 1 else 0}))
  |> group(columns: ["service", "check"])
  |> aggregateWindow(every: v.windowPeriod, fn: min, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.service + " / " + r.check, _value: r._value}))
  |> group(columns: ["_field"])`
  }],

  ['detail-hb-latency', 'timeseries', {
    title: 'Latencia por Destino (monitor)', id: 220,
    desc: 'Latencia de conexion TCP (mediana de la ventana) hacia cada destino del monitor de cada minuto. Se muestra el maximo de cada intervalo.',
    flux: hbSeries('latency_ms'),
    unit: 'ms', decimals: 1, lineWidth: 1, interpolation: 'linear',
    thresholds: [{ color: 'green', value: 0 }]
  }],

  ['detail-hb-loss', 'timeseries', {
    title: 'Perdida por Destino (monitor)', id: 221,
    desc: 'Porcentaje de conexiones sin respuesta hacia cada destino en la ventana del monitor (10 muestras por minuto). Se muestra el maximo de cada intervalo.',
    flux: hbSeries('loss_pct'),
    unit: 'percent', decimals: 0, drawStyle: 'bars', fillOpacity: 60, interpolation: 'linear',
    thresholds: [{ color: 'green', value: 0 }]
  }],

  // KPI Row
  ['detail-kpi-avail', 'stat', {
    title: 'Disponibilidad', id: 201,
    desc: 'Disponibilidad promedio de la sonda seleccionada.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "available")
  |> filter(fn: (r) => ${P})
  |> map(fn: (r) => ({r with _value: if r._value then 100.0 else 0.0}))
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Disponibilidad", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'percent', max: 100, min: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 95 }, { color: 'green', value: 99 }]
  }],

  ['detail-kpi-download', 'stat', {
    title: 'Download Promedio', id: 202,
    desc: 'Velocidad de descarga promedio de la sonda seleccionada.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -6h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "download_speed")
  |> filter(fn: (r) => ${P})
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Download", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 1,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 2 }, { color: 'green', value: 5 }]
  }],

  ['detail-kpi-upload', 'stat', {
    title: 'Upload Promedio', id: 203,
    desc: 'Velocidad de subida promedio de la sonda seleccionada.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -6h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "upload_speed")
  |> filter(fn: (r) => ${P})
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Upload", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 1,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 3 }]
  }],

  ['detail-kpi-latency', 'stat', {
    title: 'Latencia', id: 204,
    desc: 'Latencia promedio de la sonda seleccionada en el rango de tiempo.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "latency")
  |> filter(fn: (r) => ${P})
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Latencia", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 80 }, { color: 'red', value: 200 }]
  }],

  ['detail-kpi-jitter', 'stat', {
    title: 'Jitter', id: 205,
    desc: 'Jitter promedio de la sonda seleccionada en el rango de tiempo.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "jitter")
  |> filter(fn: (r) => ${P})
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Jitter", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 20 }, { color: 'red', value: 50 }]
  }],

  // Time Series — Latencia
  ['detail-latency-ts', 'timeseries', {
    title: 'Tendencia de Latencia por Servicio', id: 206,
    desc: 'Latencia promedio por servicio. Lineas horizontales marcan umbrales de 80ms (amarillo) y 200ms (rojo).',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "latency")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id", "service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', thresholdLines: true, legendPlacement: 'right', legendCalcs: ['mean', 'max'],
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 80 }, { color: 'red', value: 200 }],
    overrides: SVC_OVERRIDES
  }],

  // Time Series — Jitter
  ['detail-jitter-ts', 'timeseries', {
    title: 'Tendencia de Jitter por Servicio', id: 207,
    desc: 'Jitter promedio por servicio. Umbrales en 20ms y 50ms.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "jitter")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id", "service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', thresholdLines: true, legendPlacement: 'right', legendCalcs: ['mean', 'max'],
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 20 }, { color: 'red', value: 50 }],
    overrides: SVC_OVERRIDES
  }],

  // Time Series — Download
  ['detail-download-ts', 'timeseries', {
    title: 'Tendencia de Download por Servicio', id: 208,
    desc: 'Velocidad de descarga por servicio en el tiempo.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "download_speed")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id", "service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 2,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 2 }, { color: 'green', value: 5 }],
    overrides: SVC_OVERRIDES, legendPlacement: 'right', legendCalcs: ['lastNotNull', 'mean']
  }],

  // Time Series — Upload
  ['detail-upload-ts', 'timeseries', {
    title: 'Tendencia de Upload por Servicio', id: 209,
    desc: 'Velocidad de subida por servicio en el tiempo.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "upload_speed")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id", "service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 2,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 3 }],
    overrides: SVC_OVERRIDES, legendPlacement: 'right', legendCalcs: ['lastNotNull', 'mean']
  }],

  // Table — Snapshot Simple
  ['detail-snapshot-simple', 'table', {
    title: 'Estado de Endpoints', id: 210,
    desc: 'Ultimo estado de los endpoints medidos por la sonda. Detalle muestra el motivo exacto del fallo (clic en la celda para verlo completo).',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => ${P})
  |> filter(fn: (r) => r._field =~ /^(available|endpoint_name|error_class|error_detail)$/)
  |> group(columns: ["probe_id", "service", "_field"])
  |> last()
  |> toString()
  |> pivot(rowKey: ["probe_id", "service"], columnKey: ["_field"], valueColumn: "_value")
  |> map(fn: (r) => ({
      "Estado": if exists r.available and r.available == "true" then "Disponible" else "Caido",
      "Servicio": r.service,
      "URL": if exists r.endpoint_name then r.endpoint_name else "",
      "Error": if exists r.error_class then r.error_class else "",
      "Detalle": if exists r.error_detail then r.error_detail else ""
    }))
  |> group()
  |> sort(columns: ["Servicio"])`,
    columnOrder: ['Servicio', 'Estado', 'URL', 'Error', 'Detalle'],
    overrides: [
      { matcher: { id: 'byName', options: 'Estado' }, properties: [
        { id: 'custom.cellOptions', value: { type: 'color-background' } },
        { id: 'mappings', value: [{ type: 'value', options: { Disponible: { color: 'green', index: 0 }, Caido: { color: 'red', index: 1 } } }] },
        { id: 'custom.filterable', value: true }
      ]},
      { matcher: { id: 'byName', options: 'Servicio' }, properties: [{ id: 'custom.filterable', value: true }] },
      { matcher: { id: 'byName', options: 'Error' }, properties: [{ id: 'noValue', value: '-' }] },
      // Motivo exacto que guarda la sonda (error_detail); puede ser largo: clic para verlo completo.
      { matcher: { id: 'byName', options: 'Detalle' }, properties: [{ id: 'noValue', value: '-' }, { id: 'custom.inspect', value: true }, { id: 'custom.align', value: 'left' }] }
    ]
  }],

  // Time Series — Run Duration
  ['detail-run-duration', 'timeseries', {
    title: 'Duracion de Ejecucion de Sonda', id: 211,
    desc: 'Tiempo de ejecucion de cada corrida completa. Amarillo sobre 10 min, rojo sobre 20 min (la sonda corre cada 30).',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: "Run Duration", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', thresholdLines: true, fillOpacity: 20, lineWidth: 2, showLegend: false,
    // Desde la medicion por tiempo una corrida dura ~4 min: 10 s / 20 s quedaban
    // por debajo del eje. Amarillo a 10 min, rojo a 20 min (la sonda corre cada 30).
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 600000 }, { color: 'red', value: 1200000 }]
  }],

  // Download by Service (Probe specific)
  ['detail-download-by-service', 'bargauge', {
    title: 'Download por Servicio', id: 212,
    desc: 'Ultima velocidad de descarga reportada por servicio para la sonda seleccionada.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -6h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "download_speed")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["service"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 1, max: null,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 2 }, { color: 'green', value: 5 }]
  }],

  // Upload by Service (Probe specific)
  ['detail-upload-by-service', 'bargauge', {
    title: 'Upload por Servicio', id: 213,
    desc: 'Ultima velocidad de subida reportada por servicio para la sonda seleccionada.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -6h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "upload_speed")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["service"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'Mbps', decimals: 1, max: null,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 3 }]
  }]
];

// Grid positions for Detail tab
// La conexion va primero: es lo que el producto promete detectar.
exports.layout = [
  ['detail-conn-uptime',          0,  0,  6, 4],
  ['detail-conn-down-minutes',    6,  0,  6, 4],
  ['detail-conn-cuts',           12,  0,  6, 4],
  ['detail-conn-blackout',       18,  0,  6, 4],
  ['detail-conn-timeline',        0,  4, 24, 4],
  ['detail-services-timeline',    0,  8, 24, 8],
  ['detail-hb-latency',           0, 16, 12, 10],
  ['detail-hb-loss',             12, 16, 12, 10],
  ['detail-kpi-avail', 0, 26, 5, 4],
  ['detail-kpi-download', 5, 26, 5, 4],
  ['detail-kpi-upload', 10, 26, 5, 4],
  ['detail-kpi-latency', 15, 26, 5, 4],
  ['detail-kpi-jitter', 20, 26, 4, 4],
  ['detail-download-by-service', 0, 30, 12, 7],
  ['detail-upload-by-service', 12, 30, 12, 7],
  ['detail-latency-ts', 0, 37, 12, 9],
  ['detail-jitter-ts', 12, 37, 12, 9],
  ['detail-download-ts', 0, 46, 12, 9],
  ['detail-upload-ts', 12, 46, 12, 9],
  ['detail-snapshot-simple', 0, 55, 12, 9],
  ['detail-run-duration', 12, 55, 12, 9],
];
