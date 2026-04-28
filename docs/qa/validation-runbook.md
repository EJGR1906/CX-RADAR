# QoE Validation Runbook

## Summary

This runbook is the executable QA path for the current synthetic HTTP probe on Windows 11.

It splits validation into four layers:

1. Fast smoke checks for syntax, dry-run behavior, log completeness, and stray `curl.exe` processes.
2. Automated resilience checks for DNS failure, timeout bounds, and InfluxDB outage behavior.
3. Manual soak checks for CPU, RAM, process growth, and log growth over time.
4. Data-trust checks to confirm the reported milliseconds reflect network behavior rather than local script overhead.

## Fast Smoke Validation

Run this before every release or configuration change:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -OutputPath .\logs\qoe-certification-smoke.json
```

Pass criteria:

1. `overall_passed = true`
2. `smoke.passed = true`
3. `validate.ProbeScriptSyntax = OK`
4. `validate.ConfigFile = OK`
5. `smoke.process.timed_out = false`
6. `smoke.process.exit_code = 0`
7. `smoke.new_curl_process_ids` is empty
8. `smoke.parsed_log.summary.failure_count = 0`
9. `smoke.distinct_latency_values >= 2`

## Automated Resilience Validation

Run this when changing timeouts, target handling, Influx write logic, or error handling:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -RunResilienceChecks -OutputPath .\logs\qoe-certification-resilience.json
```

The harness currently exercises:

1. `dns_failure`: invalid `.invalid` hostname, `SkipInfluxWrite = true`
2. `timeout_bound`: unroutable IP with reduced timeouts, `SkipInfluxWrite = true`
3. `influx_outage`: dummy token plus `baseUrl = http://127.0.0.1:1`, `SkipInfluxWrite = false`

Pass criteria:

1. `dns_failure.passed = true`
2. `timeout_bound.passed = true`
3. `influx_outage.passed = true`
4. No scenario leaves `new_curl_process_ids`
5. No scenario sets `process.timed_out = true`

Interpretation:

1. DNS and timeout scenarios should finish with `exit_code = 0` because the probe records failure points but still completes the run.
2. The Influx outage scenario should finish with `exit_code != 0` because ingest failure is expected to fail loudly.

## Manual TLS Validation

TLS failure depends on a live remote endpoint, so it stays opt-in:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\run-qoe-certification.ps1 -RunResilienceChecks -IncludeTlsScenario -OutputPath .\logs\qoe-certification-tls.json
```

Pass criteria:

1. `tls_failure.passed = true`
2. The scenario does not time out
3. No stray `curl.exe` process remains

If the endpoint is unreachable for reasons unrelated to TLS, mark the result inconclusive instead of treating it as a regression.

## Soak Test Plan

The repo does not automate multi-day soak runs yet. Run these checks on a normal work PC after registering the scheduled task.

### 24-hour soak

Objective: detect obvious leaks or noisy failure patterns.

Method:

1. Register the scheduled task at the normal 5-minute interval.
2. Record baseline values for `powershell.exe` working set, handle count, and process count before the soak.
3. Record the same values again after 24 hours.
4. Inspect `logs\qoe-probe-YYYY-MM-DD.log` for repeated stack traces or runaway growth.

Pass thresholds:

1. No persistent orphan `curl.exe` processes
2. No monotonic growth in probe-related PowerShell process count
3. No sustained handle growth trend greater than 20 percent over baseline for the long-lived scheduling host process
4. No log growth pattern that suggests repeated retries or repeated stack traces every cycle

### 72-hour soak

Objective: catch slow regressions that do not appear in one day.

Method:

1. Keep the same schedule and target set.
2. Collect CPU, working set, and handle snapshots at least every 12 hours.
3. Verify that daily log rollover still happens and old files remain bounded.

Pass thresholds:

1. Average CPU impact remains operationally negligible on a normal work PC outside the active few seconds of each run.
2. Working set does not show sustained upward drift attributable to probe execution.
3. Handle count and process count remain stable over the 72-hour window.

## Data-Trust Validation

Run these checks after a successful smoke run and after the first real Influx write.

### Local plausibility

Use the smoke JSON output.

Pass criteria:

1. `smoke.parsed_log.target_results` contains non-zero `time_total_ms` values.
2. Distinct services show different latency values.
3. The per-run `run_duration_ms` is larger than the slowest single target but not wildly larger than the sum of target timings plus pacing.

### Influx consistency

After a real write succeeds:

1. Query `qoe_http_check` for the last run in Grafana or Influx Data Explorer.
2. Compare at least one endpoint's `time_total_ms` with the same endpoint in the daily log.
3. Compare `qoe_probe_run.failure_count` with the run summary in the same log window.

Pass criteria:

1. Influx values match the log values within normal rounding differences.
2. Failures appear as explicit failure points rather than silent data gaps.

## Production Readiness Checklist

The probe is ready to move beyond MVP validation only when all of the following are true:

1. `run-qoe-certification.ps1` smoke output passes.
2. `run-qoe-certification.ps1 -RunResilienceChecks` passes.
3. DPAPI token storage or another approved secret path is configured.
4. At least one real InfluxDB write succeeds on Windows PowerShell 5.1.
5. At least one Grafana dashboard query succeeds against `qoe_http_check`.
6. A 24-hour soak completes without stray processes or sustained resource drift.
7. A 72-hour soak is scheduled or completed before wider rollout.

## Remaining Risks And Recommended Changes

1. TLS failure remains environment-dependent and may need a controlled internal endpoint for deterministic execution.
2. The current harness validates bounded runtime and loud ingest failure, but it does not yet collect workstation perf counters automatically.
3. If you scale to multiple probes, add fleet staggering validation so simultaneous task starts do not create synthetic bursts.
4. If you want repeatable long-run evidence in CI-like form, the next useful addition is a small soak collector that records working set, handle count, and child-process counts to JSON on each sample.