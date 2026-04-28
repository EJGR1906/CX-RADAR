# CX-Radar QoE Architecture

## Objective

CX-Radar starts with one Windows 11 probe and is designed to scale later to multiple remote probes, including mixed probe types.

The platform is split into three signal lanes:

1. Synthetic HTTP lane: frequent curl-based checks against approved service endpoints.
2. Internal bandwidth lane: lower-frequency internal throughput and latency checks using LibreSpeed.
3. Weekly browser audit lane: deeper web performance checks using WebPageTest.

These lanes must remain separate in storage, dashboards, and alerts.

## Current MVP

The current MVP implements the synthetic HTTP lane with:

1. `config/probe-catalog.json` for probe identity, InfluxDB target, cadence parameters, and approved endpoints.
2. `scripts/qoe-probe.ps1` for curl-based measurements and InfluxDB write payload generation.
3. `scripts/register-qoe-task.ps1` for Windows Task Scheduler registration.
4. `scripts/validate-qoe-probe.ps1` for local readiness checks.

## Measurements

The schema is intentionally prepared for future scale:

1. `qoe_http_check`: per-target synthetic HTTP check results.
2. `qoe_probe_run`: one point per script run with self-health counters.
3. `qoe_speed_test`: reserved for future LibreSpeed normalization.
4. `qoe_page_audit`: reserved for future WebPageTest summaries.

## Stable Tags

Use only low-cardinality tags for cross-probe comparison:

1. `probe_id`
2. `probe_type`
3. `site`
4. `environment`
5. `service`
6. `endpoint_name`
7. `probe_version`

Do not promote URLs, remote IPs, redirect chains, or freeform errors to tags.

## Field Families

The current probe emits fields for:

1. Availability and HTTP result.
2. curl exit code and error class.
3. DNS, connect, TLS, first-byte, and total latency in milliseconds.
4. Response size, redirect count, effective URL, HTTP version, and remote IP.
5. Probe self-health counters such as success count, failure count, target count, and run duration.

## Growth Model

When adding more probes, only these elements should vary per host:

1. Probe identity values in `probe-catalog.json`.
2. Secret retrieval method.
3. Local scheduling or service wrapper.
4. Site and environment tags.

The measurement names and field semantics should remain stable unless versioned deliberately.