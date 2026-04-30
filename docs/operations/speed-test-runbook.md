# Speed Test Runbook

## Purpose

This runbook describes how to validate and register the generic speed-test probe so it runs every 20 or 30 minutes in the background.

## Scope

This lane measures node uplink, downlink, latency, and jitter with a third-party speed-test CLI. It does not replace the 5-minute synthetic HTTP lane for Netflix, YouTube, or Disney+.

## Prerequisites

1. `speedtest.exe` or the configured CLI available in `PATH`, or referenced by absolute path in `config/speed-test-catalog.json`.
2. PowerShell able to run local scripts with a process-scoped execution policy such as `RemoteSigned`.
3. `config/speed-test-catalog.json` updated with real InfluxDB values and the intended CLI command.
4. InfluxDB token stored with `scripts\set-influx-token.ps1`, or available temporarily through the configured environment variable.

## Validate Before Scheduling

Run this from PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-speed-test.ps1 | Format-List
```

The expected result today is:

1. `ProbeScriptSyntax = OK`
2. `ConfigFile = OK`
3. `SpeedTestCliAvailable = True` once the CLI is installed or the configured path is valid
4. `InfluxTokenAvailable = True` once the token is configured
5. `InfluxTokenSource = CredentialFile` after DPAPI migration

## Dry Run Without InfluxDB Write

Use this to test the speed-test flow without sending metrics:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-speed-test.ps1 -SkipInfluxWrite
```

Logs are written to `logs\qoe-speed-test-YYYY-MM-DD.log`.

## Register The Scheduled Task

Use the existing helper with a second task name and config path:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1 -TaskName CX-Radar-QoE-SpeedTest -ScriptPath .\scripts\qoe-speed-test.ps1 -ConfigPath .\config\speed-test-catalog.json -IntervalMinutes 30 -TaskDescription "Runs the CX-Radar generic speed-test probe and sends metrics to InfluxDB Cloud."
```

Adjust `-IntervalMinutes` to `20` only after confirming the traffic volume and alert noise are acceptable.

If you sign the scripts, prefer:

```powershell
& .\scripts\register-qoe-task.ps1 -TaskName CX-Radar-QoE-SpeedTest -ScriptPath .\scripts\qoe-speed-test.ps1 -ConfigPath .\config\speed-test-catalog.json -IntervalMinutes 30 -ExecutionPolicy AllSigned
```

## Post-Registration Checks

1. Open Task Scheduler and confirm the speed-test task exists.
2. Run the task once manually.
3. Confirm the speed-test log file updates.
4. Confirm metrics arrive in InfluxDB under `qoe_speed_test` and `qoe_speed_test_run`.
5. Confirm the action arguments show `RemoteSigned` or `AllSigned`, not `Bypass`, unless you deliberately approved the exception.

## Operational Guardrails

1. Keep the speed-test lane at low frequency. It is not part of the 5-minute service-health loop.
2. Stagger the speed-test task away from the HTTP probe so both lanes do not contend at the same minute.
3. Treat repeated CLI errors, missing results, or server-selection anomalies as a reason to review the provider configuration.
4. Do not use this lane as evidence that Netflix, YouTube, or Disney+ are healthy. Use it only as the node baseline.