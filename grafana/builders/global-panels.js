// global-panels.js — Panel definitions for the Global (National) tab
const GREEN = { color: 'green', value: 0 };
const YELLOW_80 = { color: 'yellow', value: 80 };
const RED_200 = { color: 'red', value: 200 };

// Una sonda esta activa si el monitor cada minuto (qoe_heartbeat_status) reporto en
// los ultimos 5 minutos, o si la sonda completa corrio en los ultimos 40 minutos
// (se recomienda correrla cada 30). Antes se exigian 10 minutos de qoe_probe_run y
// una sonda cada 30 minutos casi siempre salia inactiva.
const ACTIVE_PROBES = `hb = from(bucket: v.defaultBucket)
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "status_code")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 1.0}))

run = from(bucket: v.defaultBucket)
  |> range(start: -40m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run" and r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 1.0}))

activeProbes = union(tables: [hb, run])
  |> group(columns: ["probe_id", "site"])
  |> last()`;

// Todas las sondas vistas en 24 h (monitor o sonda completa), con la duracion de su ultima corrida.
const KNOWN_PROBES = `allRuns = from(bucket: v.defaultBucket)
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run" and r._field == "run_duration_ms")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 0.0, dur: r._value}))

allHb = from(bucket: v.defaultBucket)
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "status_code")
  |> group(columns: ["probe_id", "site"])
  |> last()
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 0.0, dur: 0.0}))

active = activeProbes
  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site, _value: 1.0, dur: 0.0}))

// _value 1 = activa; dur = duracion de la ultima corrida completa (0 si solo hay monitor)
probes = union(tables: [allRuns, allHb, active])
  |> group(columns: ["probe_id", "site"])
  |> reduce(
      identity: {_time: time(v: 0), _value: 0.0, dur: 0.0},
      fn: (r, accumulator) => ({
        _time: if r._time > accumulator._time then r._time else accumulator._time,
        _value: if r._value > accumulator._value then r._value else accumulator._value,
        dur: if r.dur > accumulator.dur then r.dur else accumulator.dur
      }))`;

exports.panels = [
  // 1. Sondas Activas
  ['global-kpi-probes', 'stat', {
    title: 'Sondas Activas', id: 101,
    desc: 'Sondas con el monitor cada minuto reportando en los ultimos 5 minutos, o con una corrida completa en los ultimos 40 minutos.',
    flux: `${ACTIVE_PROBES}

activeProbes
  |> group()
  |> count()
  |> map(fn: (r) => ({_time: now(), _field: "Sondas Activas", _value: float(v: r._value)}))
  |> group(columns: ["_field"])`,
    unit: 'short', decimals: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'green', value: 1 }]
  }],

  // 2. Servicios OK
  ['global-kpi-services', 'stat', {
    title: 'Servicios OK', id: 102,
    desc: 'Servicios (de 7) con disponibilidad >= 95% en la ultima hora, consolidando todas las sondas.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -1h)
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
    unit: 'short', decimals: 0, max: 7, min: 0,
    thresholds: [{ color: 'red', value: 0 }, { color: 'yellow', value: 6 }, { color: 'green', value: 7 }]
  }],

  // 3. Disponibilidad Nacional
  ['global-kpi-avail', 'stat', {
    title: 'Disponibilidad Nacional', id: 103,
    desc: 'Promedio nacional de disponibilidad de todos los servicios y sondas en la ultima hora. Verde >= 99%, Amarillo >= 95%, Rojo < 95%.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -1h)
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
    desc: 'Latencia promedio nacional de todas las sondas y servicios en la ultima hora.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -1h)
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
    desc: 'Suma de fallas reportadas por todas las sondas en la ultima hora. Verde = 0, Amarillo >= 1, Rojo >= 3.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -1h)
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
    title: 'Disponibilidad por Servicio (ultima hora)', id: 106,
    desc: 'Porcentaje de mediciones exitosas por servicio, consolidado de todas las sondas.',
    flux: `from(bucket: v.defaultBucket)
  |> range(start: -1h)
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
    desc: 'Estado actual de cada sonda. Activa = monitor reportando en los ultimos 5 minutos o corrida completa en los ultimos 40. Ordenable y filtrable para 50+ sondas.',
    flux: `${ACTIVE_PROBES}

${KNOWN_PROBES}

probes
  |> map(fn: (r) => ({
      "Sonda": r.probe_id,
      "Sitio": r.site,
      "Estado": if r._value == 1.0 then "Activa" else "Inactiva",
      "Ultimo Reporte": r._time,
      "Duracion ms": r.dur
    }))
  |> group()
  |> sort(columns: ["Sitio", "Sonda"])`,
    columnOrder: ['Sonda', 'Sitio', 'Estado', 'Ultimo Reporte', 'Duracion ms'],
    overrides: [
      { matcher: { id: 'byName', options: 'Estado' }, properties: [
        { id: 'custom.cellOptions', value: { type: 'color-background' } },
        { id: 'mappings', value: [{ type: 'value', options: { Activa: { color: 'green', index: 0, text: 'Activa' }, Inactiva: { color: 'red', index: 1, text: 'Inactiva' } } }] },
        { id: 'custom.filterable', value: true }
      ]},
      { matcher: { id: 'byName', options: 'Sonda' }, properties: [{ id: 'custom.filterable', value: true }] },
      { matcher: { id: 'byName', options: 'Sitio' }, properties: [{ id: 'custom.filterable', value: true }] },
      { matcher: { id: 'byName', options: 'Ultimo Reporte' }, properties: [{ id: 'unit', value: 'dateTimeFromNow' }] },
      { matcher: { id: 'byName', options: 'Duracion ms' }, properties: [{ id: 'unit', value: 'ms' }, { id: 'decimals', value: 0 }, { id: 'displayName', value: 'Duracion corrida' }] }
    ]
  }],

  // 10. Mapa Nacional de Venezuela
  ['global-map', 'geomap', {
    title: 'Mapa de Sondas QoE (Venezuela)', id: 110,
    desc: 'Ubicacion geografica y estado de actividad de las sondas QoE activas (verde) e inactivas (rojo).',
    flux: `${ACTIVE_PROBES}

${KNOWN_PROBES}

probes
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
  ['global-avail-bar',    0,  4, 24, 7],
  ['global-map',          0, 11, 14, 11],
  ['global-probe-table', 14, 11, 10, 11],
];
