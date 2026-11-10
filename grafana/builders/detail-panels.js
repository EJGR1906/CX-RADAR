// detail-panels.js — Panel definitions for the Detail (Per-Probe) tab
const P = `r.probe_id == "\${probe_id}"`;

const { SVC_OVERRIDES } = require('./panel-helpers');

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
exports.layout = [
  ['detail-kpi-avail',            0,  0,  5, 4],
  ['detail-kpi-download',         5,  0,  5, 4],
  ['detail-kpi-upload',          10,  0,  5, 4],
  ['detail-kpi-latency',         15,  0,  5, 4],
  ['detail-kpi-jitter',          20,  0,  4, 4],
  ['detail-download-by-service',  0,  4, 12, 7],
  ['detail-upload-by-service',   12,  4, 12, 7],
  ['detail-latency-ts',           0, 11, 12, 9],
  ['detail-jitter-ts',           12, 11, 12, 9],
  ['detail-download-ts',          0, 20, 12, 9],
  ['detail-upload-ts',           12, 20, 12, 9],
  ['detail-snapshot-simple',      0, 29, 12, 9],
  ['detail-run-duration',        12, 29, 12, 9],
];
