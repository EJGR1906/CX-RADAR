// panel-helpers.js — Factory functions for Grafana 13 dashboard panels
const DS = 'dfkh6j26t6gw0c';
const VER = '13.1.0-25153870157';

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
            showPercentChange: false, textMode: opts.textMode || 'value_and_name', wideLayout: true
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
              color: { mode: opts.colorMode || 'palette-classic' },
              custom: {
                axisBorderShow: false, axisCenteredZero: false, axisColorMode: 'text',
                axisLabel: '', axisPlacement: 'auto', barAlignment: 0, barWidthFactor: 0.6,
                drawStyle: opts.drawStyle || 'line', fillOpacity: opts.fillOpacity ?? 15,
                gradientMode: opts.gradientMode || 'opacity',
                hideFrom: { legend: false, tooltip: false, viz: false },
                insertNulls: false, lineInterpolation: opts.interpolation || 'smooth',
                lineWidth: 2, pointSize: 4,
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
              displayMode: 'table', placement: opts.legendPlacement || 'bottom', showLegend: true
            },
            tooltip: { hideZeros: false, mode: 'multi', sort: 'desc' }
          }
        }
      }
    }
  }];
}

function barGaugePanel(id, title, desc, flux, unit, thresholds, opts = {}) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'bargauge', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              color: { mode: 'thresholds' }, decimals: 1,
              max: opts.max ?? 100, min: opts.min ?? 0, unit,
              thresholds: { mode: 'absolute', steps: thresholds }
            }, overrides: []
          },
          options: {
            displayMode: opts.displayMode || 'lcd',
            minVizHeight: 16, minVizWidth: 8,
            namePlacement: 'auto', orientation: 'horizontal',
            reduceOptions: { calcs: ['lastNotNull'], fields: '', values: false },
            showUnfilled: true, sizing: 'auto', valueMode: 'color'
          }
        }
      }
    }
  }];
}

function tablePanel(id, title, desc, flux, overrides = []) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'table', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              color: { mode: 'thresholds' },
              custom: { align: 'center', cellOptions: { type: 'auto' }, footer: { reducers: [] }, inspect: false },
              thresholds: { mode: 'absolute', steps: [{ color: 'green', value: 0 }] }
            }, overrides
          },
          options: { cellHeight: 'sm', showHeader: true, sortBy: [{ displayName: 'Sitio' }] }
        }
      }
    }
  }];
}

function stateTimelinePanel(id, title, desc, flux) {
  return [id, {
    kind: 'Panel', spec: {
      data: { kind: 'QueryGroup', spec: { queries: [query(flux, true)], queryOptions: {}, transformations: [] } },
      description: desc, id, links: [], title,
      vizConfig: {
        group: 'state-timeline', kind: 'VizConfig', version: VER,
        spec: {
          fieldConfig: {
            defaults: {
              color: { mode: 'thresholds' }, custom: { fillOpacity: 80, lineWidth: 1 },
              mappings: [
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
                    size: { fixed: 12 },
                    color: {
                      field: 'EstadoVal',
                      fixed: 'green'
                    },
                    symbol: { fixed: 'circle' }
                  },
                  showLegend: true,
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
              custom: {},
              color: { mode: 'thresholds' },
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

module.exports = { statPanel, tsPanel, barGaugePanel, tablePanel, stateTimelinePanel, geomapPanel, gridItem, DS };

