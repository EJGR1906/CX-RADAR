# CX-Radar Agent Guide

> [!NOTE]
> **Aviso de Migración**: Este repositorio ha sido migrado de PowerShell a Python 3 (Multiplataforma) para soportar ejecuciones universales en Windows, Linux y macOS sin dependencias externas. Para más detalles sobre las decisiones de diseño y equivalencia de archivos, consulte la [Guía de Migración](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/MIGRATION.md).

## Scope

This repository is a cross-platform (Windows, Linux, macOS) QoE monitoring project centered on the synthetic HTTP lane and the probe-scoped QoE metrics emitted by the main probe.

- Runtime and ingestion flow: Python 3 probe -> InfluxDB Cloud -> Grafana Cloud.
- Current implemented measurements: `qoe_http_check`, `qoe_real_metrics`, and `qoe_probe_run`.
- Future dedicated throughput and browser audit work stay separate from the active probe lane.

Architecture details live in [docs/architecture/qoe-architecture.md](docs/architecture/qoe-architecture.md).

## Key Paths

- Probe config: [config/probe-catalog.json](config/probe-catalog.json)
- Probe scripts: [scripts/](scripts)
- Dashboard JSON and Flux examples: [grafana/](grafana)
- Operations and QA runbooks: [docs/operations/task-scheduler-runbook.md](docs/operations/task-scheduler-runbook.md), [docs/qa/validation-runbook.md](docs/qa/validation-runbook.md), [docs/qa/certification-checklist.md](docs/qa/certification-checklist.md)
- Security guidance: [docs/security/hardening.md](docs/security/hardening.md)
- Grafana setup: [docs/observability/grafana-cloud-setup.md](docs/observability/grafana-cloud-setup.md)

## Working Rules

- Run commands from the repository root unless the task explicitly requires another location.
- Keep secrets out of the repo. Use [scripts/set_influx_token.py](scripts/set_influx_token.py) and follow [docs/security/hardening.md](docs/security/hardening.md).
- Treat tags in [config/probe-catalog.json](config/probe-catalog.json) as stable identifiers. Changing values like `service`, `site`, `environment`, or `probeId` creates new time-series in InfluxDB and can fragment Grafana views.
- Do not mix synthetic HTTP work with future LibreSpeed or WebPageTest work in the same measurement, dashboard, or alert logic.
- Prefer linking to the existing docs above instead of re-explaining their content in new customization files.

## Core Commands

Validation and local execution:

```bash
# Validar el entorno
python scripts/validate_qoe_probe.py

# Ejecutar sonda en seco (sin escribir a InfluxDB)
python scripts/qoe_probe.py --skip-influx-write

# Ejecutar sonda completa
python scripts/qoe_probe.py
```

QA checks:

```bash
# Ejecutar suite de humo de certificación
python scripts/run_qoe_certification.py --output-path logs/qoe-certification-smoke.json

# Ejecutar suite de certificación con pruebas de resiliencia
python scripts/run_qoe_certification.py --run-resilience-checks --output-path logs/qoe-certification-resilience.json
```

Scheduled task/daemon registration:

```bash
# Registrar la sonda en el programador nativo de tareas del OS (Task Scheduler, systemd, cron o launchd)
python scripts/register_qoe_task.py
```

## Validation Order

When changing probe, config, or ingestion logic, prefer this order:

1. `validate_qoe_probe.py`
2. `qoe_probe.py --skip-influx-write`
3. `qoe_probe.py`
4. `run_qoe_certification.py`

Use the daily log under `logs/` as the first source of truth when checking runtime behavior.

## Existing Custom Agents

This repo already ships specialized agents under [.github/agents](.github/agents):

- `QoE SRE Backend`: Python 3 probe, InfluxDB write path, native task scheduler/daemon work
- `QoE Visualization and Alerts`: Grafana/Flux/dashboard work
- `QoE SecOps Hardening`: token handling, execution policy, risk controls
- `QoE QA QC Validation`: certification, soak, and resilience testing

Use those when the task is clearly specialized instead of broad repo work.

## Known Pitfalls

- `Share externally` in Grafana does not support dashboards that depend on template variables.
- Some historical logs and QA artifacts may already be tracked in git; `.gitignore` only affects new untracked files.
- Dashboard series duplication usually comes from historical tag changes, not from Grafana bugs.
