# CX-Radar Customization Rules & Workflows

This document establishes the workflows and rules for the Antigravity agent and its subagents when working on the CX-Radar workspace.

## Systemic Workflows

### 1. Backend Probe Modification Workflow
When a task involves editing probe collection logic or configuration parameters in `config/probe-catalog.json`:
1. **Trigger Skill**: Load the `qoe_sre_backend` skill to align with probe guidelines.
2. **Implement changes**: Edit relevant Python files (e.g., `scripts/qoe_probe.py`).
3. **Trigger validation**: Load the `qoe_qa_qc_validation` skill and run the sequential validation order:
   - `python scripts/validate_qoe_probe.py`
   - `python scripts/qoe_probe.py --skip-influx-write`
   - `python scripts/run_qoe_certification.py --run-resilience-checks`

### 2. Observability & Dashboard Workflows
When a task involves creating or modifying Grafana dashboard files or Flux metrics queries:
1. **Trigger Skill**: Load the `qoe_visualization_alerts` skill.
2. **Maintain Consistency**: Check `config/probe-catalog.json` to ensure measurement names (`qoe_http_check`, `qoe_real_metrics`, `qoe_probe_run`) match.
3. **Verify Queries**: Verify Flux syntax is correct and includes aggregation windowing to prevent overloading InfluxDB/Grafana.

### 3. Credential & Telemetry Hardening Workflows
When a task touches secrets, tokens, system permissions, or network rate limiting:
1. **Trigger Skill**: Load the `qoe_secops_hardening` skill.
2. **Enforce Isolation**: Verify that tokens are only written via `scripts/set_influx_token.py` and stored in process environment variables or the `.env` file (never checked into git).
3. **Run Validation**: Validate the environment using `python scripts/validate_qoe_probe.py`.

## Core Guardrails
- **Cross-platform**: All Python code must remain cross-platform (compatible with Windows, Linux, macOS) and use standard library (stdlib) imports only.
- **Zero External Dependencies**: Do not introduce packages requiring `pip install` unless explicitly instructed.
- **Do Not Mix Tasks**: Do not mix synthetic HTTP lane work with LibreSpeed/WebPageTest work in the same files/metrics.
