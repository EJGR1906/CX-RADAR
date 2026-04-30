# Grafana Cloud Setup For CX-Radar Speed Tests

## Scope

This guide implements a separate Grafana Cloud layer for the generic speed-test lane only.

The assets added in this repo are:

1. `grafana/queries/qoe-speed-test-flux-examples.md`

They are aligned to these measurements:

1. `qoe_speed_test`
2. `qoe_speed_test_run`

## Dashboard Folder Separation

Keep the speed-test lane in its own dashboard folder. Do not mix `qoe_speed_test` or `qoe_speed_test_run` panels into the HTTP overview folder.

## Suggested Dashboard Variables

Use the same core variables as the HTTP lane where they exist:

1. `environment`
2. `site`
3. `probe_id`
4. `service`
5. `endpoint_name`

## Suggested Panels

Build the first speed-test dashboard around five operator questions:

1. Is node download bandwidth degrading?
2. Is node upload bandwidth degrading?
3. Is latency or jitter worsening on one node or across many nodes?
4. Is the selected speed-test server changing unexpectedly?
5. Is the speed-test probe still running and writing to InfluxDB?

Suggested first panels:

1. `Latest Speed-Test Snapshot`
2. `Download Mbps by Probe`
3. `Upload Mbps by Probe`
4. `Latency and Jitter by Probe`
5. `Speed-Test Run Duration`
6. `Speed-Test Write State`

## Recommended Alerts

Create alerts from the Flux queries in `grafana/queries/qoe-speed-test-flux-examples.md`.

### Alert 1: Node download degradation

Intent: detect a local node or uplink problem before it affects customer traffic.

1. Query: `Alert Query: Download Regression`
2. Group by: `probe_id`
3. Condition: last `download_mbps < 70`
4. For: `30m`
5. Evaluate every: `5m`

Noise control:

1. Start at `70 Mbps` only if that is comfortably below your normal node baseline.
2. Raise or lower it per site once you have at least one week of data.

### Alert 2: Node upload degradation

Intent: detect degraded uplink capacity even when download remains acceptable.

1. Query: `Alert Query: Upload Regression`
2. Group by: `probe_id`
3. Condition: last `upload_mbps < 50`
4. For: `30m`
5. Evaluate every: `5m`

Noise control:

1. Start at `50 Mbps` only if it is safely below your normal uplink baseline.
2. If uplink is naturally bursty at a site, prefer a longer `for` window before lowering the threshold.

### Alert 3: Node latency degradation

Intent: detect a path-quality problem even if throughput remains acceptable.

1. Query: `Alert Query: Latency Regression`
2. Group by: `probe_id`
3. Condition: last `latency_ms > 20`
4. For: `30m`
5. Evaluate every: `5m`

### Alert 4: Node jitter degradation

Intent: detect an unstable access path even if bandwidth remains acceptable.

1. Query: `Alert Query: Jitter Regression`
2. Group by: `probe_id`
3. Condition: last `jitter_ms > 10`
4. For: `30m`
5. Evaluate every: `5m`

### Alert 5: Speed-test write failure

Intent: separate speed-test probe failure from node degradation.

1. Query: `Alert Query: Speed Test Write Failure`
2. Group by: `probe_id`
3. Condition: last `write_succeeded < 1`
4. For: `40m`
5. Evaluate every: `5m`

## Operational Notes

1. Treat speed-test alerts as node-baseline alerts, not service-health alerts.
2. Compare `qoe_speed_test` with `qoe_http_check` before concluding that a public service is degraded.
3. If the provider changes the selected server often, review whether `endpoint_name` should stay fixed while server metadata remains only in fields.

## Server Selection Notes

1. With `serverId` left empty in `config/speed-test-catalog.json`, the Ookla CLI auto-selects the best available server for that run. In practice it is usually a low-latency nearby server, but it is not guaranteed to be the same server every time.
2. If you need strict comparability, pin `targets[].serverId` per site or per probe. That guarantees the probe always measures against the same Speedtest server instead of a changing auto-selected server.
3. If your goal is early detection of node issues, auto-selection is acceptable for a first rollout. If your goal is longitudinal capacity comparison across probes, pinning a server is better.