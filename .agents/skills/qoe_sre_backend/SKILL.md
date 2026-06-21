---
name: "qoe_sre_backend"
description: "Automation, configuration, and execution of the Python 3 QoE probe, InfluxDB Line Protocol ingestion, and system scheduled tasks (crontab, systemd, Windows Task Scheduler)."
---

# QoE SRE Backend Skill

Use this skill when modifying probe logic, ingestion flow, configuration parsing, or registry/daemon setup on the host system.

## Key Targets & Context
- **Primary Script**: [qoe_probe.py](file:///c:/Users/Eduar/Documents/CX-RADAR/scripts/qoe_probe.py)
- **Configuration File**: [probe-catalog.json](file:///c:/Users/Eduar/Documents/CX-RADAR/config/probe-catalog.json)
- **Native Daemons**:
  - Windows: [register_qoe_task.py](file:///c:/Users/Eduar/Documents/CX-RADAR/scripts/register_qoe_task.py)
  - Linux Systemd: [cx-radar-qoe-probe.service](file:///c:/Users/Eduar/Documents/CX-RADAR/orchestration/cx-radar-qoe-probe.service)
  - macOS: [com.cx-radar.qoe-probe.plist](file:///c:/Users/Eduar/Documents/CX-RADAR/orchestration/com.cx-radar.qoe-probe.plist)

## InfluxDB Line Protocol Guidelines
When writing or formatting metrics for InfluxDB Cloud:
- Measurements: `qoe_http_check` (HTTP probes), `qoe_real_metrics` (speedtests), `qoe_probe_run` (runtime logs/metadata).
- Low-cardinality tags: `probeId`, `probeType` (must be `python`), `site`, `environment`, `service`, `endpointName`, `isp`.
- Standard timestamp: Nanosecond or millisecond resolution as configured.
- Avoid introducing random or high-cardinality values as tags (e.g., raw milliseconds, error messages). Keep tags stable.

## Operating System Scheduler Registration
- To register or update the scheduled task on Windows:
  `python scripts/register_qoe_task.py`
- On Linux, use Systemd Timer or Crontab (see [docs/operations/task-scheduler-runbook.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/operations/task-scheduler-runbook.md)).
