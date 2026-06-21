---
name: "qoe_qa_qc_validation"
description: "Quality assurance, certification, performance testing, fault tolerance simulation, resilience checks, and validation of QoE probe metrics."
---

# QoE QA QC Validation Skill

Use this skill when verifying probe accuracy, running certification checks, performing resilience testing, and doing QA audits before rolling out changes.

## Key Targets & Context
- **Certification Runner**: [run_qoe_certification.py](file:///c:/Users/Eduar/Documents/CX-RADAR/scripts/run_qoe_certification.py)
- **Checklist Guide**: [docs/qa/certification-checklist.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/qa/certification-checklist.md)
- **Validation Runbook**: [docs/qa/validation-runbook.md](file:///c:/Users/Eduar/Documents/CX-RADAR/docs/qa/validation-runbook.md)

## Validation Workflow
When introducing any changes to the probe scripts, configuration, or telemetry path, always perform validation in the following order:
1. Validate environment configuration:
   `python scripts/validate_qoe_probe.py`
2. Run a dry execution of the probe (skips writing to InfluxDB to avoid polluting production data):
   `python scripts/qoe_probe.py --skip-influx-write`
3. Run a complete live execution of the probe:
   `python scripts/qoe_probe.py`
4. Run the full certification suite:
   `python scripts/run_qoe_certification.py --run-resilience-checks --output-path logs/qoe-certification-resilience.json`

## Fault Tolerance Guidelines
- Verify the probe fails gracefully (does not crash or hang indefinitely) during network loss or API endpoint timeouts.
- Standard libraries should enforce explicit timeouts on all HTTP requests (default 10s for connects, 120s max execution).
