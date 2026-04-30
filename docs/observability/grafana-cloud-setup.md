# Grafana Cloud Setup For CX-Radar

## Scope

This guide implements the first Grafana Cloud layer for the current synthetic HTTP lane only.

For the generic speed-test lane, use `docs/observability/grafana-speed-test-setup.md` and keep its dashboards and alerts separate from the HTTP folder.

The assets added in this repo are:

1. `grafana/dashboards/qoe-http-overview.json`
2. `grafana/queries/qoe-http-flux-examples.md`

They are aligned to these current measurements:

1. `qoe_http_check`
2. `qoe_probe_run`

## Connect InfluxDB Cloud To Grafana Cloud

1. Open Grafana Cloud.
2. Go to Connections, then Data sources.
3. Choose Add data source.
4. Select InfluxDB.
5. In Query language, choose `Flux`.
6. In URL, use the base URL from `config/probe-catalog.json`, currently `https://us-east-1-1.aws.cloud2.influxdata.com`.
7. Set Organization to your real Influx organization name.
8. Set Default bucket to `qoe_metrics`, or your final bucket if you renamed it.
9. Paste an InfluxDB API token with read access to the bucket.
10. Click Save & test.

Recommended Grafana data source defaults:

1. Min time interval: `5m`
2. HTTP method: `POST`
3. Custom timeout: `30s`

## Import The Dashboard

1. In Grafana Cloud, go to Dashboards.
2. Click New, then Import.
3. Upload `grafana/dashboards/qoe-http-overview.json`.
4. Map the `DS_INFLUXDB` input to your InfluxDB Cloud data source.
5. Import the dashboard.

The dashboard is built around four operator questions:

1. Are endpoints reachable now?
2. Are services slower than normal?
3. Is the problem specific to one service, one endpoint, or one probe?
4. Is the probe itself healthy and still writing to InfluxDB?

## Dashboard Structure

### Summary row

1. `Availability`: current availability percentage over the selected time range.
2. `Last Run Failures`: sum of latest `failure_count` values from `qoe_probe_run`.
3. `Influx Write State`: latest `write_succeeded` state across selected probes.

### Service health row

1. `Availability by Service`: percentage trend from boolean `available`.
2. `Total Latency by Service`: mean `time_total_ms` trend grouped by `service`.

### Drill-down row

1. `Latest Endpoint Snapshot`: table with `available`, `http_status`, `time_total_ms`, `error_class`, `curl_exit_code`, and `remote_ip`.
2. `Probe Failure Count`: failures per run from `qoe_probe_run`.

### Probe health row

1. `Probe Run Duration`: mean `run_duration_ms` trend from `qoe_probe_run`.

## Templating And Filtering

The dashboard includes these variables:

1. `environment`
2. `site`
3. `probe_id`
4. `service`
5. `endpoint_name`

All of them default to `All` and use regex-compatible filtering so the same dashboard scales from one probe to many probes.

## Recommended Alerts

Create these alerts in Grafana Cloud from the Flux queries in `grafana/queries/qoe-http-flux-examples.md`.

### Alert 1: Sustained endpoint slowdown

Intent: detect meaningful latency degradation before outright failures.

1. Query: `Alert Query: Sustained Slowdown`
2. Group by: `probe_id`, `service`, `endpoint_name`
3. Condition: mean `time_total_ms > 2500`
4. For: `15m`
5. Evaluate every: `5m`

Noise control:

1. Use `for 15m` so one slow response does not page.
2. Start at `2500 ms` for public streaming homepages, then tighten after you have baseline data.

### Alert 2: Endpoint reachability degradation

Intent: catch partial or full availability loss without waiting for a complete outage.

1. Query: `Alert Query: Reachability Failure Ratio`
2. Group by: `probe_id`, `service`, `endpoint_name`
3. Condition: mean `available < 0.8`
4. For: `15m`
5. Evaluate every: `5m`

Interpretation:

1. `1.0` means fully healthy in the window.
2. `0.8` means 20 percent of checks failed in the alert window.

### Alert 3: Probe write failure

Intent: separate ingest failure from service degradation.

1. Query: `Alert Query: Probe Write Failure`
2. Group by: `probe_id`
3. Condition: last `write_succeeded < 1`
4. For: `10m`
5. Evaluate every: `5m`

Noise control:

1. Route this alert differently from endpoint alerts because it is an observability pipeline problem.
2. If you later run multiple probes, keep the alert grouped per probe so one host does not mask another.

## Operational Notes

1. Keep the synthetic HTTP lane on its own dashboard folder. Do not mix it with future `qoe_speed_test` or `qoe_page_audit` panels.
2. Avoid alerting on single samples for public internet endpoints.
3. Use the `service` and `endpoint_name` dimensions for drill-down before adding more cardinality.
4. Do not use `remote_ip` as a grouping dimension in alerting. It is useful for inspection, not for routing.

## Current Gaps

1. The repo does not yet include exported Grafana alert-rule JSON because Grafana Cloud rule payloads vary by stack version and contact-point layout.
2. There is not yet real Influx data in the bucket, so panel thresholds are starting values rather than baseline-derived values.
3. The current probe covers only one endpoint per service. Multi-endpoint service dashboards may need additional rows later.