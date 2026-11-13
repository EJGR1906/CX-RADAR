// panel-helpers.js — Factory functions for Grafana 13 dashboard panels
const DS = 'dfkh6j26t6gw0c';
const VER = '13.1.0-25153870157';

// Estados del monitor de cada minuto (status_code de qoe_heartbeat_status).
// Los codigos coinciden con STATUS_CODES de scripts/qoe_heartbeat.py.
const CONNECTION_STATES = [
  [0, 'OK', 'green'],
  [1, 'Degradado', 'yellow'],
  [6, 'Microcortes', 'orange'],
  [7, 'Internet interceptado', 'purple'],
  [5, 'Falla de DNS', 'dark-orange'],
  [2, 'Sin salida a internet', 'red'],
  [3, 'Caida del acceso', 'dark-red'],
  [4, 'Router local caido', 'blue'],
  [8, 'Sonda sin red local', 'dark-blue']
];
const CONNECTION_MAPPINGS = [{
  type: 'value',
  options: Object.fromEntries(CONNECTION_STATES.map(([code, text, color], index) => [String(code), { color, index, text }]))
}];
// Codigos en los que la sonda no tiene internet utilizable.
const NO_INTERNET_CODES = [2, 3, 4, 5, 7, 8];

// Colores fijos por servicio (insensibles a mayusculas: "Youtube" o "YouTube").
const SERVICE_COLORS = [
  ['netflix', '#E50914'],
  ['youtube', '#FF66CC'],
  ['amazon', '#FF9900'],
  ['microsoft', '#00A4EF'],
  ['disney\\+', '#5B7CFA'],
  ['ookla-barquisimeto', '#B877D9'],
  ['ookla-caracas', '#1ABC9C']
];
const SVC_OVERRIDES = SERVICE_COLORS.map(([pattern, color]) => ({
  matcher: { id: 'byRegexp', options: `/.*${pattern}.*/i` },
  properties: [{ id: 'color', value: { fixedColor: color, mode: 'fixed' } }]
}));

function query(flux, range = false) {
  return {
    kind: 'PanelQuery', spec: {
      hidden: false, refId: 'A',
      query: {
        datasource: { name: DS }, group: 'influxdb',
        kind: 'DataQuery', spec: { query: flux, range }, version: 'v0'
      }
    }
  };
}

function statPanel(id, title, desc, flux, unit, thresholds, opts = {}) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'stat', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              color: { mode: 'thresholds' }, decimals: opts.decimals ?? 1,
              unit, thresholds: { mode: 'absolute', steps: thresholds },
              ...(opts.mappings ? { mappings: opts.mappings } : {}),
              ...(opts.max !== undefined ? { max: opts.max, min: opts.min ?? 0 } : {})
            }, overrides: opts.overrides || []
          },
          options: {
            colorMode: 'background', graphMode: opts.graphMode || 'none',
            justifyMode: 'center', orientation: 'auto',
            percentChangeColorMode: 'standard',
            reduceOptions: { calcs: ['lastNotNull'], fields: '', values: false },
            showPercentChange: false, textMode: opts.textMode || 'value', wideLayout: true,
            ...(opts.text ? { text: opts.text } : {})
          }
        }
      }
    }
  }];
}

function tsPanel(id, title, desc, flux, unit, thresholds, opts = {}) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux, true)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'timeseries', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              color: { mode: opts.colorMode || 'palette-classic' },
              custom: {
                axisBorderShow: false, axisCenteredZero: false, axisColorMode: 'text',
                axisLabel: '', axisPlacement: 'auto', barAlignment: 0, barWidthFactor: 0.6,
                drawStyle: opts.drawStyle || 'line', fillOpacity: opts.fillOpacity ?? 0,
                gradientMode: opts.gradientMode || 'opacity',
                hideFrom: { legend: false, tooltip: false, viz: false },
                insertNulls: false, lineInterpolation: opts.interpolation || 'smooth',
                lineWidth: opts.lineWidth ?? 1, pointSize: 4,
                scaleDistribution: { type: 'linear' },
                showPoints: 'auto', showValues: false, spanNulls: false,
                stacking: { group: 'A', mode: opts.stacking || 'none' },
                thresholdsStyle: { mode: opts.thresholdLines ? 'line' : 'off' }
              },
              decimals: opts.decimals ?? 0, unit,
              thresholds: { mode: 'absolute', steps: thresholds }
            }, overrides: opts.overrides || []
          },
          options: {
            annotations: { clustering: -1, multiLane: false },
            legend: {
              calcs: opts.legendCalcs || ['lastNotNull', 'mean', 'max'],
              displayMode: 'table', placement: opts.legendPlacement || 'bottom', showLegend: opts.showLegend ?? true
            },
            tooltip: { hideZeros: false, mode: 'multi', sort: 'desc' }
          }
        }
      }
    }
  }];
}

function barGaugePanel(id, title, desc, flux, unit, thresholds, opts = {}) {
  // max: null deja la escala automatica (velocidades); por defecto 0-100 (porcentajes).
  const max = opts.max === undefined ? 100 : opts.max;
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'bargauge', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              color: { mode: 'thresholds' }, decimals: opts.decimals ?? 1,
              ...(max !== null ? { max } : {}), min: opts.min ?? 0, unit,
              thresholds: { mode: 'absolute', steps: thresholds }
            }, overrides: opts.overrides || []
          },
          options: {
            // "lcd" pinta cada celda con el color de su tramo: una barra al 100 % se
            // veia casi toda roja. "basic" pinta la barra entera con el color del valor.
            displayMode: opts.displayMode || 'basic',
            minVizHeight: 16, minVizWidth: 8, maxVizHeight: 300,
            namePlacement: 'left', orientation: 'horizontal',
            reduceOptions: { calcs: ['lastNotNull'], fields: '', values: false },
            showUnfilled: true, sizing: 'auto', valueMode: 'color',
            text: opts.text || { titleSize: 14, valueSize: 16 }
          }
        }
      }
    }
  }];
}

function tablePanel(id, title, desc, flux, overrides = [], columnOrder = null) {
  // InfluxDB devuelve las columnas en orden alfabetico ("Duracion ms" quedaba
  // primero); la transformacion organize fija el orden de lectura.
  const transformations = columnOrder ? [{
    kind: 'Transformation', group: 'organize',
    spec: { id: 'organize', options: { indexByName: Object.fromEntries(columnOrder.map((c, i) => [c, i])) } }
  }] : [];
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'table', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              color: { mode: 'thresholds' },
              custom: { align: 'center', cellOptions: { type: 'auto' }, footer: { reducers: [] }, inspect: false },
              thresholds: { mode: 'absolute', steps: [{ color: 'green', value: 0 }] }
            }, overrides
          },
          options: { cellHeight: 'sm', showHeader: true }
        }
      }
    }
  }];
}

function stateTimelinePanel(id, title, desc, flux, opts = {}) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux, true)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'state-timeline', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              color: { mode: 'thresholds' }, custom: { fillOpacity: 80, lineWidth: 1 },
              mappings: opts.mappings || [
                { options: { '1': { color: 'green', index: 0, text: 'Disponible' }, '0': { color: 'red', index: 1, text: 'Caído' } }, type: 'value' }
              ],
              thresholds: { mode: 'absolute', steps: [{ color: 'green', value: 0 }] }
            }, overrides: []
          },
          options: {
            alignValue: 'center', legend: { displayMode: 'list', placement: 'bottom', showLegend: false },
            mergeValues: true, rowHeight: 0.8, showValue: 'auto',
            tooltip: { hideZeros: true, mode: 'multi', sort: 'none' }
          }
        }
      }
    }
  }];
}

function geomapPanel(id, title, desc, flux) {
  return [id, {
    kind: 'Panel',
    spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'geomap', kind: 'VizConfig', version: VER,
        spec: {
          options: {
            basemap: {
              config: {
                theme: 'dark'
              },
              name: 'CartoDB Dark Matter',
              type: 'carto'
            },
            view: {
              id: 'coords',
              lat: 8.5,
              lon: -66.0,
              zoom: 6
            },
            layers: [
              {
                type: 'markers',
                name: 'Sondas QoE',
                config: {
                  style: {
                    size: { fixed: 18 },
                    opacity: 0.9,
                    color: {
                      field: 'EstadoVal',
                      fixed: 'green'
                    },
                    symbol: { fixed: 'circle' }
                  },
                  showLegend: false,
                  tooltip: true
                },
                location: {
                  mode: 'coords',
                  latitude: 'latitude',
                  longitude: 'longitude'
                }
              }
            ],
            controls: {
              showZoom: true,
              showAttribution: true,
              showScale: false,
              showDebug: false
            }
          },
          fieldConfig: {
            defaults: {
              noValue: 'Sin datos',
              custom: {},
              color: { mode: 'thresholds' },
              mappings: [{ type: 'value', options: { '0': { text: 'Inactiva', color: 'red', index: 0 }, '1': { text: 'Activa', color: 'green', index: 1 } } }],
              thresholds: {
                mode: 'absolute',
                steps: [
                  { color: 'red', value: 0 },
                  { color: 'green', value: 1 }
                ]
              }
            },
            overrides: []
          }
        }
      }
    }
  }];
}

function gridItem(name, x, y, w, h) {
  return { kind: 'GridLayoutItem', spec: { element: { kind: 'ElementReference', name }, x, y, width: w, height: h } };
}

module.exports = { SVC_OVERRIDES, query, statPanel, tsPanel, barGaugePanel, tablePanel, stateTimelinePanel, geomapPanel, gridItem, DS, CONNECTION_MAPPINGS, NO_INTERNET_CODES };

