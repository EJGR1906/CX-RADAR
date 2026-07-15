// global-panels.js — Panel definitions for the Global (National) tab
const GREEN = { color: 'green', value: 0 };
const YELLOW_80 = { color: 'yellow', value: 80 };
const RED_200 = { color: 'red', value: 200 };

exports.panels = [
  // 1. Sondas Activas
  ['global-kpi-probes', 'stat', {
    title: 'Sondas Activas', id: 101,
    desc: 'Cantidad de sondas que reportaron en los ultimos 10 minutos.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -10m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> group(columns: ["probe_id"])
  |> last()
  |> group()
  |> count()
  |> map(fn: (r) => ({_time: now(), _field: "Sondas Activas", _value: float(v: r._value)}))
  |> group(columns: ["_field"])`,
    unit: 'short', decimals: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 1 }, { color: 'green', value: 2 }]
  }],

  // 2. Servicios OK
  ['global-kpi-services', 'stat', {
    title: 'Servicios OK', id: 102,
    desc: 'Servicios con disponibilidad >= 95% en los ultimos 30 minutos.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "available")
  |> map(fn: (r) => ({r with _value: if r._value then 1.0 else 0.0}))
  |> group(columns: ["service"])
  |> mean()
  |> map(fn: (r) => ({r with _value: if r._value >= 0.95 then 1.0 else 0.0}))
  |> group()
  |> sum()
  |> map(fn: (r) => ({_time: now(), _field: "Servicios OK", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'short', decimals: 0, max: 5, min: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 4 }, { color: 'green', value: 5 }]
  }],

  // 3. Disponibilidad Nacional
  ['global-kpi-avail', 'stat', {
    title: 'Disponibilidad Nacional', id: 103,
    desc: 'Promedio nacional de disponibilidad de todos los servicios y sondas en los ultimos 30 minutos. Verde >= 99%, Amarillo >= 95%, Rojo < 95%.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "available")
  |> map(fn: (r) => ({r with _value: if r._value then 100.0 else 0.0}))
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Disponibilidad", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'percent', max: 100, min: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 95 }, { color: 'green', value: 99 }]
  }],

  // 4. Latencia Media
  ['global-kpi-latency', 'stat', {
    title: 'Latencia Media Nacional', id: 104,
    desc: 'Latencia promedio nacional de todas las sondas y servicios en los ultimos 30 minutos.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "latency")
  |> group()
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: "Latencia Media", _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'ms', decimals: 0,
    thresholds: [GREEN, YELLOW_80, RED_200]
  }],

  // 5. Fallas Recientes
  ['global-kpi-failures', 'stat', {
    title: 'Fallas Recientes', id: 105,
    desc: 'Suma de fallas reportadas por todas las sondas en los ultimos 30 minutos. Verde = 0, Amarillo >= 1, Rojo >= 3.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "failure_count")
  |> group(columns: ["probe_id"])
  |> last()
  |> group()
  |> sum()
  |> map(fn: (r) => ({_time: now(), _field: "Fallas", _value: float(v: r._value)}))
  |> group(columns: ["_field"])`,
    unit: 'short', decimals: 0,
    thresholds: [{ color: 'green', value: 0 }, { color: 'yellow', value: 1 }, { color: 'red', value: 3 }]
  }],

  // 6. Bar Gauge — Disponibilidad por Servicio
  ['global-avail-bar', 'bargauge', {
    title: 'Disponibilidad por Servicio (ultimos 30m)', id: 106,
    desc: 'Porcentaje de mediciones exitosas por servicio, consolidado de todas las sondas.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -30m)
  |> filter(fn: (r) => r._measurement == "qoe_real_metrics")
  |> filter(fn: (r) => r._field == "available")
  |> map(fn: (r) => ({r with _value: if r._value then 100.0 else 0.0}))
  |> group(columns: ["service"])
  |> mean()
  |> map(fn: (r) => ({_time: now(), _field: r.service, _value: r._value}))
  |> group(columns: ["_field"])`,
    unit: 'percent',
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 95 }, { color: 'green', value: 99 }]
  }],

  // 9. Tabla Estado de Sondas (escala a 50+)
  ['global-probe-table', 'table', {
    title: 'Estado de Sondas QoE', id: 109,
    desc: 'Estado actual de cada sonda. Activa = reporto en los ultimos 10 minutos. Ordenable y filtrable para 50+ sondas.',
    flux: `allProbes = from(bucket: v.defaultBucket)
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 0.0, dur: r._value}))

activeProbes = from(bucket: v.defaultBucket)
  |> range(start: -10m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 1.0, dur: r._value}))

union(tables: [allProbes, activeProbes])
  |> group(columns: ["probe_id", "site"])
  |> sort(columns: ["_value"], desc: true)
  |> first()
  |> map(fn: (r) => ({
      "Sonda": r.probe_id,
      "Sitio": r.site,
      "Estado": if r._value == 1.0 then "Activa" else "Inactiva",
      "Ultimo Reporte": string(v: r._time),
      "Duracion ms": r.dur
    }))
  |> group()
  |> sort(columns: ["Sitio", "Sonda"])`,
    overrides: [
      { matcher: { id: 'byName', options: 'Estado' }, properties: [
        { id: 'custom.cellOptions', value: { type: 'color-background' } },
        { id: 'mappings', value: [{ type: 'value', options: { Activa: { color: 'green', index: 0, text: 'Activa' }, Inactiva: { color: 'red', index: 1, text: 'Inactiva' } } }] },
        { id: 'custom.width', value: 100 }, { id: 'custom.filterable', value: true }
      ]},
      { matcher: { id: 'byName', options: 'Sonda' }, properties: [{ id: 'custom.width', value: 200 }, { id: 'custom.filterable', value: true }] },
      { matcher: { id: 'byName', options: 'Sitio' }, properties: [{ id: 'custom.width', value: 140 }, { id: 'custom.filterable', value: true }] },
      { matcher: { id: 'byName', options: 'Duracion ms' }, properties: [{ id: 'unit', value: 'ms' }, { id: 'decimals', value: 0 }] }
    ]
  }],

  // 10. Mapa Nacional de Venezuela
  ['global-map', 'geomap', {
    title: 'Mapa de Sondas QoE (Venezuela)', id: 110,
    desc: 'Ubicacion geografica y estado de actividad de las sondas QoE activas (verde) e inactivas (rojo).',
    flux: `allProbes = from(bucket: v.defaultBucket)
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 0.0, dur: r._value}))

activeProbes = from(bucket: v.defaultBucket)
  |> range(start: -10m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 1.0, dur: r._value}))

union(tables: [allProbes, activeProbes])
  |> group(columns: ["probe_id", "site"])
  |> sort(columns: ["_value"], desc: true)
  |> first()
  |> map(fn: (r) => ({
      _time: r._time,
      "Sonda": r.probe_id,
      "Sitio": r.site,
      "EstadoVal": r._value,
      "Estado": if r._value == 1.0 then "Activa" else "Inactiva",
      latitude: if r.probe_id =~ /(?i)barquisimeto/ or r.site =~ /(?i)barquisimeto/ or r.probe_id =~ /(?i)lara/ or r.site =~ /(?i)lara/ or r.probe_id == "eduardo-pc-trabajo" or r.site == "home-office" then 10.067781458959754
           else if r.probe_id =~ /(?i)maracaibo/ or r.site =~ /(?i)maracaibo/ or r.probe_id =~ /(?i)zulia/ or r.site =~ /(?i)zulia/ then 10.6427
           else if r.probe_id =~ /(?i)valencia/ or r.site =~ /(?i)valencia/ or r.probe_id =~ /(?i)carabobo/ or r.site =~ /(?i)carabobo/ then 10.1620
           else if r.probe_id =~ /(?i)caracas/ or r.site =~ /(?i)caracas/ then 10.4806
           else 10.067781458959754,
      longitude: if r.probe_id =~ /(?i)barquisimeto/ or r.site =~ /(?i)barquisimeto/ or r.probe_id =~ /(?i)lara/ or r.site =~ /(?i)lara/ or r.probe_id == "eduardo-pc-trabajo" or r.site == "home-office" then -69.28425410793854
           else if r.probe_id =~ /(?i)maracaibo/ or r.site =~ /(?i)maracaibo/ or r.probe_id =~ /(?i)zulia/ or r.site =~ /(?i)zulia/ then -71.6125
           else if r.probe_id =~ /(?i)valencia/ or r.site =~ /(?i)valencia/ or r.probe_id =~ /(?i)carabobo/ or r.site =~ /(?i)carabobo/ then -68.0077
           else if r.probe_id =~ /(?i)caracas/ or r.site =~ /(?i)caracas/ then -66.9036
           else -69.28425410793854
    }))
  |> group()`
  }]
];

// Grid positions for Global tab
exports.layout = [
  ['global-kpi-probes',   0,  0,  5, 4],
  ['global-kpi-services', 5,  0,  5, 4],
  ['global-kpi-avail',   10,  0,  5, 4],
  ['global-kpi-latency', 15,  0,  5, 4],
  ['global-kpi-failures',20,  0,  4, 4],
  ['global-avail-bar',    0,  4, 24, 6],
  ['global-map',          0, 10, 24, 10],
  ['global-probe-table',  0, 20, 24, 8],
];

