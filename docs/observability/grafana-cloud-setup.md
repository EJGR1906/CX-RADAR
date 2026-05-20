# Grafana Cloud Setup For CX-Radar

## Scope

This guide implements the first Grafana Cloud layer for the current synthetic HTTP lane only.

For the generic speed-test lane, use `docs/observability/grafana-speed-test-setup.md` and keep its dashboards and alerts separate from the HTTP folder.

The assets added in this repo are:

1. `grafana/dashboards/qoe-national-global.json` — Vista Global Nacional (multi-probe national view with geomap)
2. `grafana/dashboards/qoe-probe-detail.json` — Detalle por Sonda (per-probe drilldown with full metrics)
3. `grafana/queries/qoe-http-flux-examples.md`

They are aligned to these current measurements:

1. `qoe_http_check`
2. `qoe_real_metrics`
3. `qoe_probe_run`

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

## Import The Dashboards

Two dashboards are provided. Import them in order:

### 1. Vista Global Nacional (`qoe-national-global.json`)

1. In Grafana Cloud, go to Dashboards.
2. Click New, then Import.
3. Upload `grafana/dashboards/qoe-national-global.json`.
4. Select your InfluxDB Cloud data source when prompted.
5. Import.

This dashboard answers national-level questions:

1. What is the current health of each probe across Venezuela?
2. Are there regional patterns in latency or availability?
3. Where are the probes physically located (geomap view)?

### 2. Detalle por Sonda (`qoe-probe-detail.json`)

1. In Grafana Cloud, go to Dashboards.
2. Click New, then Import.
3. Upload `grafana/dashboards/qoe-probe-detail.json`.
4. Select your InfluxDB Cloud data source when prompted.
5. Import.

This dashboard answers per-probe drilldown questions:

1. Are endpoints reachable now from this probe?
2. Are services slower than normal?
3. Is the problem specific to one service, one endpoint, or one probe?
4. Is the probe itself healthy and still writing to InfluxDB?

> **Note:** The `Sonda` variable in this dashboard lets you switch between probes. The Vista Global Nacional dashboard intentionally has no probe filter — it always shows all probes.

## Dashboard Structure

### Vista Global Nacional (`qoe-national-global.json`)

1. **Mapa de Sondas** (geomap): probe locations color-coded by current availability state.
2. **Disponibilidad por Sonda** (bar gauge): availability % per probe.
3. **Latencia por Sonda** (bar gauge): mean latency per probe.
4. **Velocidad de Descarga por Sonda** (bar gauge): mean download speed per probe.
5. **Velocidad de Subida por Sonda** (bar gauge): mean upload speed per probe.
6. **Estado por Sonda** (state timeline): per-probe availability over time.
7. **Latencia a lo largo del tiempo** (time series): latency trend per probe.
8. **Tabla Nacional de QoE** (table): latest snapshot of all probes with full metrics.

### Detalle por Sonda (`qoe-probe-detail.json`)

Filtered by the `Sonda` (`probe_id`) variable.

1. **Disponibilidad** (stat): current availability % for the selected probe.
2. **Últimas Fallas** (stat): latest failure count from `qoe_probe_run`.
3. **Estado de Escritura Influx** (stat): latest `write_succeeded` state.
4. **Disponibilidad por Servicio** (time series): availability trend grouped by service.
5. **Latencia Total por Servicio** (time series): mean latency per service.
6. **Velocidad de Descarga** (time series): download Mbps per service over time.
7. **Velocidad de Subida** (time series): upload Mbps per service over time.
8. **Snapshot de Endpoints** (table): latest per-endpoint reading with full fields.
9. **Fallas por Ciclo** (time series): failure count per probe run.
10. **Duración de Ciclo** (time series): run duration trend from `qoe_probe_run`.
11. **RPM Promedio** (bar gauge): requests per minute per service.
12. **Disponibilidad por Servicio (barra)** (bar gauge): current availability % per service.
13. **Timeline de Estado** (state timeline): per-service availability over time.

## Templating And Filtering

The **Vista Global** dashboard has no template variables — it always shows all probes.

The **Detalle por Sonda** dashboard includes:

1. `probe_id` — selects a single probe; populated from `qoe_probe_run`.

Multi-dimensional filtering is achieved by using Flux's `filter()` inside queries rather than Grafana variables to avoid cardinality issues.

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

1. Keep the synthetic HTTP lane on its own dashboard folder. Do not mix it with future dedicated throughput or `qoe_page_audit` panels.
2. Avoid alerting on single samples for public internet endpoints.
3. Use the `service` and `endpoint_name` dimensions for drill-down before adding more cardinality.
4. Do not use `remote_ip` as a grouping dimension in alerting. It is useful for inspection, not for routing.

## Current Gaps

1. The repo does not yet include exported Grafana alert-rule JSON because Grafana Cloud rule payloads vary by stack version and contact-point layout.
2. There is not yet real Influx data in the bucket, so panel thresholds are starting values rather than baseline-derived values.
3. The current probe covers only one endpoint per service. Multi-endpoint service dashboards may need additional rows later.