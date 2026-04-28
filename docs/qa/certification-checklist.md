# QA Certification Checklist

## Scope

This checklist is the minimum release gate for the synthetic HTTP MVP.

Use `scripts\run-qoe-certification.ps1` for repeatable smoke and resilience checks before treating this checklist as passed.

## Functional

1. `validate-qoe-probe.ps1` returns `ProbeScriptSyntax = OK`.
2. `run-qoe-certification.ps1` returns `smoke.passed = True`.
3. The probe completes one dry run with `-SkipInfluxWrite` without terminating in error.
4. The daily log contains one entry per enabled target plus one final run summary.
5. The probe writes to InfluxDB successfully once the token is configured.

## Resilience

1. No internet: the script exits cleanly and logs failure states instead of hanging.
2. DNS failure: curl errors are captured and mapped to `error_class`.
3. TLS failure: curl errors are captured and mapped to `error_class`.
4. `run-qoe-certification.ps1 -RunResilienceChecks` returns passing results for `dns_failure`, `timeout_bound`, and `influx_outage`.
5. InfluxDB unavailable: the script fails loudly and predictably.
6. Timeout path: each target is bounded by `connectTimeoutSeconds` and `maxTimeSeconds`.

## Workstation Impact

1. `run-qoe-certification.ps1` reports no `new_curl_process_ids` after a smoke run.
2. Repeated scheduled runs do not create sustained CPU or RAM growth.
3. Logs rotate naturally by date and do not explode in size during normal use.

## Data Trust

1. The measured milliseconds are non-zero and plausible for real destinations.
2. Different services produce different latency profiles.
3. Failures are represented as failure points, not silent gaps.

## Release Gate

The MVP is not ready for production until:

1. Token handling is configured.
2. One successful InfluxDB write is observed.
3. One successful dashboard query is observed.
4. At least one soak period is completed after scheduling.
5. The QA runbook in `docs\qa\validation-runbook.md` has been executed and attached to the release evidence.