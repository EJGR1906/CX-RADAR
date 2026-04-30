# CX-Radar Speed Test Flux Query Library

These queries are aligned to the generic speed-test schema:

1. Measurement `qoe_speed_test` for per-run throughput results
2. Measurement `qoe_speed_test_run` for one point per script run
3. Stable tags `probe_id`, `site`, `environment`, `service`, `endpoint_name`, `probe_type`, and `probe_version`

Replace these placeholders before using the queries directly in Grafana or InfluxDB Data Explorer:

1. `$bucket`
2. `$environmentRegex`
3. `$siteRegex`
4. `$probeRegex`
5. `$serviceRegex`
6. `$endpointRegex`

## Download Mbps By Probe

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "download_mbps")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Upload Mbps By Probe

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "upload_mbps")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Latency And Jitter By Probe

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field =~ /latency_ms|jitter_ms/)
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id", "_field"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Latest Speed-Test Snapshot

```flux
from(bucket: $bucket)
  |> range(start: -2h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> filter(fn: (r) => r._field =~ /available|download_mbps|upload_mbps|latency_ms|jitter_ms|packet_loss_pct|server_name|server_location|error_class|cli_exit_code/)
  |> group(columns: ["probe_id", "site", "environment", "service", "endpoint_name", "_field"])
  |> last()
  |> pivot(rowKey: ["probe_id", "site", "environment", "service", "endpoint_name"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["probe_id", "service", "endpoint_name"])
```

## Speed Test Run Duration

```flux
from(bucket: $bucket)
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test_run")
  |> filter(fn: (r) => r._field == "run_duration_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> group(columns: ["probe_id"])
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
```

## Latest Speed Test Write State

```flux
from(bucket: $bucket)
  |> range(start: -2h, stop: v.timeRangeStop)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test_run")
  |> filter(fn: (r) => r._field == "write_succeeded")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  |> group(columns: ["probe_id"])
  |> last()
```

## Alert Query: Download Regression

```flux
from(bucket: $bucket)
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "download_mbps")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> last()
```

## Alert Query: Upload Regression

```flux
from(bucket: $bucket)
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "upload_mbps")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> last()
```

## Alert Query: Latency Regression

```flux
from(bucket: $bucket)
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "latency_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> last()
```

## Alert Query: Jitter Regression

```flux
from(bucket: $bucket)
  |> range(start: -2h)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test")
  |> filter(fn: (r) => r._field == "jitter_ms")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> filter(fn: (r) => r.service =~ /^$serviceRegex$/)
  |> filter(fn: (r) => r.endpoint_name =~ /^$endpointRegex$/)
  |> group(columns: ["probe_id"])
  |> last()
```

## Alert Query: Speed Test Write Failure

```flux
from(bucket: $bucket)
  |> range(start: -3h)
  |> filter(fn: (r) => r._measurement == "qoe_speed_test_run")
  |> filter(fn: (r) => r._field == "write_succeeded")
  |> filter(fn: (r) => r.environment =~ /^$environmentRegex$/)
  |> filter(fn: (r) => r.site =~ /^$siteRegex$/)
  |> filter(fn: (r) => r.probe_id =~ /^$probeRegex$/)
  |> map(fn: (r) => ({ r with _value: if r._value then 1.0 else 0.0 }))
  |> group(columns: ["probe_id"])
  |> last()
```