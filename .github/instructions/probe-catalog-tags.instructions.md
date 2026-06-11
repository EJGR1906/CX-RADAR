---
description: "Use when editing config/probe-catalog.json, Grafana dashboards, or Flux queries that touch probe identity fields, service names, endpoint names, or Influx-facing tags. Covers tag stability, measurement boundaries, display-name handling, and secret-handling constraints."
name: "Probe Catalog Tag Stability"
applyTo: "{config/probe-catalog.json,grafana/**}"
---
# Probe Catalog Tag Stability

- Treat `probe.probeId`, `probe.site`, `probe.environment`, `targets[].service`, and `targets[].endpointName` as stable identifiers, not presentation labels.
- Do not rename those values just to make Grafana look nicer. A new tag value creates a new InfluxDB time series and can fragment dashboards, alerts, and historical comparisons.
- When editing Grafana assets, keep the stored tag stable and change the legend, panel title, display name, value mapping, or table formatting instead of changing the catalog value.
- Keep this file scoped to the synthetic HTTP lane. Do not introduce LibreSpeed or WebPageTest measurements or tags here.
- Never place tokens or secrets in this file. Keep using `influx.tokenEnvVar` and `influx.credentialFilePath` for secret retrieval.
- Treat tag renames as blocked by default. Only proceed if the user explicitly approves the historical series split or asks for a deliberate migration plan.
- If a tag rename is truly required, call out the migration impact explicitly and link to [docs/architecture/qoe-architecture.md](../../docs/architecture/qoe-architecture.md) and [docs/observability/grafana-cloud-setup.md](../../docs/observability/grafana-cloud-setup.md).