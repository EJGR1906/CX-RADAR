#!/usr/bin/env node
// build-dashboard.js — Assembles the CX-Radar QoE dashboards
// Usage: node grafana/builders/build-dashboard.js
const fs = require('fs');
const path = require('path');
const { statPanel, tsPanel, barGaugePanel, tablePanel, stateTimelinePanel, geomapPanel, gridItem, DS } = require('./panel-helpers');
const globalDef = require('./global-panels');
const detailDef = require('./detail-panels');

// --- Build panel elements from definitions ---
function buildElement(def) {
  const [name, type, cfg] = def;
  switch (type) {
    case 'stat':
      return statPanel(cfg.id, cfg.title, cfg.desc, cfg.flux, cfg.unit, cfg.thresholds, cfg);
    case 'timeseries':
      return tsPanel(cfg.id, cfg.title, cfg.desc, cfg.flux, cfg.unit, cfg.thresholds, cfg);
    case 'bargauge':
      return barGaugePanel(cfg.id, cfg.title, cfg.desc, cfg.flux, cfg.unit, cfg.thresholds, cfg);
    case 'table':
      return tablePanel(cfg.id, cfg.title, cfg.desc, cfg.flux, cfg.overrides || []);
    case 'state-timeline':
      return stateTimelinePanel(cfg.id, cfg.title, cfg.desc, cfg.flux);
    case 'geomap':
      return geomapPanel(cfg.id, cfg.title, cfg.desc, cfg.flux);
    default:
      throw new Error(`Unknown panel type: ${type}`);
  }
}

// Build helper to extract elements for a set of panels
function buildElementsMap(panelsList) {
  const map = {};
  panelsList.forEach(def => {
    const [name, , ] = def;
    const [, panel] = buildElement(def);
    map[name] = panel;
  });
  return map;
}

// --- Grid Layout Builder ---
function buildGrid(layoutDef) {
  return layoutDef.map(([name, x, y, w, h]) => gridItem(name, x, y, w, h));
}

// --- Variables ---
function queryVar(name, label, flux, deps = {}) {
  const multi = deps.multi !== undefined ? deps.multi : true;
  const includeAll = deps.includeAll !== undefined ? deps.includeAll : true;
  
  return {
    kind: 'QueryVariable',
    spec: {
      allValue: '.*', allowCustomValue: true,
      current: { text: '', value: '' },
      definition: flux, hide: 'dontHide', includeAll: includeAll,
      label, multi: multi, name, options: [],
      query: {
        datasource: { name: DS }, group: 'influxdb',
        kind: 'DataQuery', spec: { __legacyStringValue: flux }, version: 'v0'
      },
      refresh: 'onDashboardLoad', regex: '', regexApplyTo: 'value',
      skipUrlSync: false, sort: 'alphabeticalAsc'
    }
  };
}

const variables = [
  queryVar('probe_id', 'Sonda',
    `import "influxdata/influxdb/schema"\nschema.tagValues(bucket: v.defaultBucket, tag: "probe_id", predicate: (r) => r._measurement == "qoe_probe_run", start: -30d)`, { multi: false, includeAll: false })
];

// --- Templates ---
const annotations = [{
  kind: 'AnnotationQuery', spec: {
    builtIn: true, enable: true, hide: true,
    iconColor: 'rgba(0, 211, 255, 1)', name: 'Annotations & Alerts',
    query: {
      datasource: { name: '-- Grafana --' }, group: 'grafana',
      kind: 'DataQuery', spec: { limit: 100, matchAny: false, tags: [], type: 'dashboard' }, version: 'v0'
    }
  }
}];

const baseDashboard = (title, desc, elements, layout, vars = []) => ({
  annotations,
  cursorSync: 'Crosshair',
  description: desc,
  editable: true,
  elements,
  layout,
  links: [],
  liveNow: false,
  preload: false,
  tags: ['cx-radar', 'qoe', 'real-metrics', 'influxdb'],
  timeSettings: {
    autoRefresh: '1m',
    autoRefreshIntervals: ['5s', '10s', '30s', '1m', '5m', '15m', '30m', '1h', '2h', '1d'],
    fiscalYearStartMonth: 0, from: 'now-1h', hideTimepicker: false, timezone: 'browser', to: 'now'
  },
  title,
  variables: vars
});

// --- Write output dashboards ---
const dashboardsDir = path.join(__dirname, '..', 'dashboards');
fs.mkdirSync(dashboardsDir, { recursive: true });

// 1. Vista Global Nacional Dashboard
const globalElements = buildElementsMap(globalDef.panels);
const globalLayout = {
  kind: 'GridLayout',
  spec: { items: buildGrid(globalDef.layout) }
};
const globalDashboard = baseDashboard(
  'CX-Radar — Vista Global Nacional',
  'Vista Global (nacional) de QoE para CX-Radar con mapa de ubicaciones de sondas en Venezuela.',
  globalElements,
  globalLayout,
  [] // No Sonda variable for global view
);
const globalPath = path.join(dashboardsDir, 'qoe-national-global.json');
fs.writeFileSync(globalPath, JSON.stringify(globalDashboard, null, 2), 'utf8');
console.log(`Global Dashboard written to: ${globalPath}`);
console.log(`  Elements: ${Object.keys(globalElements).length} panels`);

// 2. Detalle por Sonda Dashboard
const detailElements = buildElementsMap(detailDef.panels);
const detailLayout = {
  kind: 'GridLayout',
  spec: { items: buildGrid(detailDef.layout) }
};
const detailDashboard = baseDashboard(
  'CX-Radar — Detalle por Sonda',
  'Vista Detallada por sonda de QoE para CX-Radar. Permite analizar el rendimiento especifico de una sonda.',
  detailElements,
  detailLayout,
  variables // probe_id variable is enabled here
);
const detailPath = path.join(dashboardsDir, 'qoe-probe-detail.json');
fs.writeFileSync(detailPath, JSON.stringify(detailDashboard, null, 2), 'utf8');
console.log(`Detail Dashboard written to: ${detailPath}`);
console.log(`  Elements: ${Object.keys(detailElements).length} panels`);

// 3. Cleanup old unified dashboard if it exists
const oldPath = path.join(dashboardsDir, 'qoe-drilldown-national.json');
if (fs.existsSync(oldPath)) {
  fs.unlinkSync(oldPath);
  console.log(`Cleaned up old unified dashboard: ${oldPath}`);
}
