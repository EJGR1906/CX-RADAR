---
name: "qoe_visualization_alerts"
description: "Grafana Cloud dashboards, Flux queries for InfluxDB, alert rules, latency visualization, and QoE metrics grouping."
---

# QoE Visualization and Alerts Skill

Use this skill when designing or modifying Grafana Cloud dashboards, writing Flux queries for InfluxDB, or setting up alert rules for metric degradation.

## Observability Context
- **Grafana Configs**: [grafana/](file:///c:/Users/Eduar/Documents/CX-RADAR/grafana)
- **Setup Guide**: [docs/observability/grafana-cloud-setup.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/observability/grafana-cloud-setup.md)

## Flux Query Standards
- Read from the `qoe_metrics` bucket (as configured in InfluxDB Cloud).
- Always filter by `_measurement` (`qoe_http_check`, `qoe_real_metrics`, `qoe_probe_run`).
- Group metrics by stable tags like `probeId` or `service` to allow clean dynamic variables in Grafana.
- Use windowing (`aggregateWindow`) properly to manage density and loading times in Grafana.

## Alerting Best Practices
- Focus alerts on sustained degradation rather than single transient latency spikes.
- Set thresholds based on historical baseline (e.g., availability < 99% or latency > 2x baseline for > 15 minutes).
