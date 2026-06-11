# CX-Radar Flux Query Library

These queries are aligned to the current synthetic HTTP schema:

1. Measurement `qoe_http_check` for per-endpoint probe results
2. Measurement `qoe_probe_run` for one point per script run
3. Stable tags `probe_id`, `site`, `environment`, `service`, `endpoint_name`, `probe_type`, and `probe_version`

Replace these placeholders before using the queries directly in Grafana or InfluxDB Data Explorer:

1. `$bucket`
2. `$environmentRegex`
3. `$siteRegex`
4. `$probeRegex`
5. `$serviceRegex`
6. `$endpointRegex`

## Availability By Service

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r._field == "available")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 100.0 else 0.0 }))
  |> group(columns: ["service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Total Latency By Service

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r._field == "time_total_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["service"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Latency Waterfall Components

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r._field =~ /time_namelookup_ms|time_connect_ms|time_appconnect_ms|time_starttransfer_ms|time_total_ms/)
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["service", "endpoint_name", "_field"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Latest Endpoint Snapshot

```flux
from(bucket: $bucket)
  |> range(start: -30m, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> filter(fn: (r) => r._field =~ /available|http_status|time_total_ms|error_class|curl_exit_code|remote_ip/)
  |> group(columns: ["probe_id", "site", "environment", "service", "endpoint_name", "_field"])
  |> last()
  |> pivot(rowKey: ["probe_id", "site", "environment", "service", "endpoint_name"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["service", "endpoint_name"])
```

## Latest Probe Write State

```flux
from(bucket: $bucket)
  |> range(start: -30m, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "write_succeeded")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  |> group(columns: ["probe_id"])
  |> last()
```

## Failure Count Per Probe Run

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "failure_count")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: last, createEmpty: false)
```

## Probe Run Duration

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Alert Query: Sustained Slowdown

```flux
from(bucket: $bucket)
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r._field == "time_total_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id", "service", "endpoint_name"])
  |> mean()
```

## Alert Query: Reachability Failure Ratio

```flux
from(bucket: $bucket)
  |> range(start: -15m)
  |> filter(fn: (r) => r._measurement == "qoe_http_check")
  |> filter(fn: (r) => r._field == "available")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  |> group(columns: ["probe_id", "service", "endpoint_name"])
  |> mean()
```

## Alert Query: Probe Write Failure

```flux
from(bucket: $bucket)
  |> range(start: -20m)
  |> filter(fn: (r) => r._measurement == "qoe_probe_run")
  |> filter(fn: (r) => r._field == "write_succeeded")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  |> group(columns: ["probe_id"])
  |> last()
```