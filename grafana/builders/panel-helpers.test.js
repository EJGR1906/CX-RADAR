const test = require('node:test');
const assert = require('node:assert');
const { query, DS } = require('./panel-helpers');

test('query function returns correct object structure without range parameter', () => {
  const flux = 'from(bucket: "my-bucket") |> range(start: v.timeRangeStart, stop: v.timeRangeStop)';
  const result = query(flux);

  assert.deepStrictEqual(result, {
    kind: 'PanelQuery',
    spec: {
      hidden: false,
      refId: 'A',
      query: {
        datasource: { name: DS },
        group: 'influxdb',
        kind: 'DataQuery',
        spec: { query: flux, range: false },
        version: 'v0'
      }
    }
  });
});

test('query function returns correct object structure with range parameter true', () => {
  const flux = 'from(bucket: "my-bucket") |> range(start: v.timeRangeStart, stop: v.timeRangeStop) |> yield(name: "mean")';
  const result = query(flux, true);

  assert.deepStrictEqual(result, {
    kind: 'PanelQuery',
    spec: {
      hidden: false,
      refId: 'A',
      query: {
        datasource: { name: DS },
        group: 'influxdb',
        kind: 'DataQuery',
        spec: { query: flux, range: true },
        version: 'v0'
      }
    }
  });
});
