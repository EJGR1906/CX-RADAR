// detail-panels.js — Panel definitions for the Detail (Per-Probe) tab
const P = `r.probe_id == "\${probe_id}"`;

const SVC_OVERRIDES = [
  { matcher: { id: 'byRegexp', options: '/.*Netflix.*/' }, properties: [{ id: 'color', value: { fixedColor: '#E50914', mode: 'fixed' } }] },
  { matcher: { id: 'byRegexp', options: '/.*Youtube.*/' }, properties: [{ id: 'color', value: { fixedColor: '#FF4444', mode: 'fixed' } }] },
  { matcher: { id: 'byRegexp', options: '/.*Amazon.*/' }, properties: [{ id: 'color', value: { fixedColor: '#FF9900', mode: 'fixed' } }] },
  { matcher: { id: 'byRegexp', options: '/.*Microsoft.*/' }, properties: [{ id: 'color', value: { fixedColor: '#00A4EF', mode: 'fixed' } }] },
  { matcher: { id: 'byRegexp', options: '/.*Disney\\+.*/' }, properties: [{ id: 'color', value: { fixedColor: '#113CCF', mode: 'fixed' } }] },
];

exports.panels = [
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
    unit: 'percent', max: 100, min: 0, graphMode: 'area',
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
    unit: 'Mbps', decimals: 2, graphMode: 'area',
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
    unit: 'Mbps', decimals: 2,
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
    unit: 'ms', thresholdLines: true,
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
    unit: 'ms', thresholdLines: true, legendPlacement: 'right',
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
    unit: 'Mbps', decimals: 2, fillOpacity: 20,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 2 }, { color: 'green', value: 5 }],
    overrides: SVC_OVERRIDES, legendCalcs: ['lastNotNull', 'mean']
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
    unit: 'Mbps', decimals: 2, fillOpacity: 20,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 3 }],
    overrides: SVC_OVERRIDES, legendCalcs: ['lastNotNull', 'mean']
  }],

  // Table — Snapshot Simple
  ['detail-snapshot-simple', 'table', {
    title: 'Estado de Endpoints', id: 210,
    desc: 'Ultimo estado de los endpoints medidos por la sonda.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => ${P})
  |> filter(fn: (r) => r._field =~ /available|endpoint_name|error_class/)
  |> group(columns: ["probe_id", "service", "_field"])
  |> last()
  |> toString()
  |> pivot(rowKey: ["probe_id", "service"], columnKey: ["_field"], valueColumn: "_value")
  |> map(fn: (r) => ({
      "Estado": if exists r.available and r.available == "true" then "Disponible" else "Caido",
      "Servicio": r.service,
      "URL": if exists r.endpoint_name then r.endpoint_name else "",
      "Error": if exists r.error_class then r.error_class else ""
    }))
  |> group()
  |> sort(columns: ["Servicio"])`,
    overrides: [
      { matcher: { id: 'byName', options: 'Estado' }, properties: [
        { id: 'custom.cellOptions', value: { type: 'color-background' } },
        { id: 'mappings', value: [{ type: 'value', options: { Disponible: { color: 'green', index: 0 }, Caido: { color: 'red', index: 1 } } }] },
        { id: 'custom.width', value: 110 }
      ]},
      { matcher: { id: 'byName', options: 'Servicio' }, properties: [{ id: 'custom.width', value: 140 }] },
      { matcher: { id: 'byName', options: 'Error' }, properties: [{ id: 'custom.width', value: 300 }] }
    ]
  }],

  // Time Series — Run Duration
  ['detail-run-duration', 'timeseries', {
    title: 'Duracion de Ejecucion de Sonda', id: 211,
    desc: 'Tiempo de ejecucion del probe. Picos indican lentitud de red o del sistema.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> filter(fn: (r) => ${P})
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({_time: r._time, _field: "Run Duration", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', thresholdLines: true, fillOpacity: 20,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 10000 }, { color: 'red', value: 20000 }]
  }],

  // Download by Service (Probe specific)
  ['detail-download-by-service', 'stat', {
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
    unit: 'Mbps', decimals: 2, graphMode: 'area',
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 2 }, { color: 'green', value: 5 }]
  }],

  // Upload by Service (Probe specific)
  ['detail-upload-by-service', 'stat', {
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
    unit: 'Mbps', decimals: 2,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 3 }]
  }]
];

// Grid positions for Detail tab
exports.layout = [
  ['detail-kpi-avail',            0,  0,  5, 4],
  ['detail-kpi-download',         5,  0,  5, 4],
  ['detail-kpi-upload',          10,  0,  5, 4],
  ['detail-kpi-latency',         15,  0,  5, 4],
  ['detail-kpi-jitter',          20,  0,  4, 4],
  ['detail-download-by-service',  0,  4, 12, 5],
  ['detail-upload-by-service',   12,  4, 12, 5],
  ['detail-latency-ts',           0,  9, 12, 8],
  ['detail-jitter-ts',           12,  9, 12, 8],
  ['detail-download-ts',          0, 17, 12, 8],
  ['detail-upload-ts',           12, 17, 12, 8],
  ['detail-snapshot-simple',      0, 25, 24, 8],
  ['detail-run-duration',        0, 33, 24, 8],
];

