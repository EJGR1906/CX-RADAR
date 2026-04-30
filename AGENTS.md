# CX-Radar Agent Guide

## Scope

This repository is a Windows 11 QoE monitoring project centered on the synthetic HTTP lane, with a separate throughput lane.

- Runtime and ingestion flow: PowerShell probe -> InfluxDB Cloud -> Grafana Cloud.
- Current implemented measurements: `qoe_http_check`, `qoe_probe_run`, `qoe_speed_test`, and `qoe_speed_test_run`.
- Future browser audit work stays separate under `qoe_page_audit`.

Architecture details live in [docs/architecture/qoe-architecture.md](docs/architecture/qoe-architecture.md).

## Key Paths

- Probe config: [config/probe-catalog.json](config/probe-catalog.json)
- Speed-test config: [config/speed-test-catalog.json](config/speed-test-catalog.json)
- Probe scripts: [scripts/](scripts)
- Dashboard JSON and Flux examples: [grafana/](grafana)
- Operations and QA runbooks: [docs/operations/task-scheduler-runbook.md](docs/operations/task-scheduler-runbook.md), [docs/qa/validation-runbook.md](docs/qa/validation-runbook.md), [docs/qa/certification-checklist.md](docs/qa/certification-checklist.md)
- Security guidance: [docs/security/hardening.md](docs/security/hardening.md)
- Grafana setup: [docs/observability/grafana-cloud-setup.md](docs/observability/grafana-cloud-setup.md)

## Working Rules

- Run commands from the repository root unless the task explicitly requires another location.
- Keep secrets out of the repo. Use [scripts/set-influx-token.ps1](scripts/set-influx-token.ps1) and follow [docs/security/hardening.md](docs/security/hardening.md).
- Treat tags in [config/probe-catalog.json](config/probe-catalog.json) as stable identifiers. Changing values like `service`, `site`, `environment`, or `probeId` creates new time-series in InfluxDB and can fragment Grafana views.
- Do not mix synthetic HTTP work with future LibreSpeed or WebPageTest work in the same measurement, dashboard, or alert logic.
- Prefer linking to the existing docs above instead of re-explaining their content in new customization files.

## Core Commands

Validation and local execution:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-speed-test.ps1 | Format-List

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-speed-test.ps1 -SkipInfluxWrite

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-speed-test.ps1
```

QA checks:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -OutputPath .\logs\qoe-certification-smoke.json

Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -RunResilienceChecks -OutputPath .\logs\qoe-certification-resilience.json
```

Scheduled task registration:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1
```

If task registration fails with access denied on a non-elevated personal machine, retry with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1 -RunAsCurrentUser
```

## Validation Order

When changing probe, config, or ingestion logic, prefer this order:

1. `validate-qoe-probe.ps1`
2. `qoe-probe.ps1 -SkipInfluxWrite`
3. `qoe-probe.ps1`
4. `run-qoe-certification.ps1`

For the speed-test lane, prefer this order:

1. `validate-qoe-speed-test.ps1`
2. `qoe-speed-test.ps1 -SkipInfluxWrite`
3. `qoe-speed-test.ps1`

Use the daily log under `logs/` as the first source of truth when checking runtime behavior.

## Existing Custom Agents

This repo already ships specialized agents under [.github/agents](.github/agents):

- `QoE SRE Backend`: PowerShell probe, InfluxDB write path, Task Scheduler work
- `QoE Visualization and Alerts`: Grafana/Flux/dashboard work
- `QoE SecOps Hardening`: token handling, execution policy, risk controls
- `QoE QA QC Validation`: certification, soak, and resilience testing

Use those when the task is clearly specialized instead of broad repo work.

## Known Pitfalls

- `Share externally` in Grafana does not support dashboards that depend on template variables.
- Some historical logs and QA artifacts may already be tracked in git; `.gitignore` only affects new untracked files.
- Dashboard series duplication usually comes from historical tag changes, not from Grafana bugs.
