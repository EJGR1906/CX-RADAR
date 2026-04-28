# Task Scheduler Runbook

## Purpose

This runbook describes how to validate and register the Windows 11 probe so it runs every 5 minutes in the background.

## Prerequisites

1. `curl.exe` available in `PATH`.
2. PowerShell able to run local scripts with a process-scoped execution policy such as `RemoteSigned`.
3. `config/probe-catalog.json` updated with real InfluxDB values.
4. InfluxDB token stored with `scripts\set-influx-token.ps1`, or available temporarily through the configured environment variable.

## Provision the Token

Preferred path:

```powershell
& .\scripts\set-influx-token.ps1
```

If you are migrating away from a user environment variable and do not need the rollback path:

```powershell
& .\scripts\set-influx-token.ps1 -ClearUserEnvironmentVariable
```

## Validate Before Scheduling

Run this from PowerShell:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\validate-qoe-probe.ps1 | Format-List
```

The expected result today is:

1. `ProbeScriptSyntax = OK`
2. `ConfigFile = OK`
3. `CurlAvailable = True`
4. `InfluxTokenAvailable = True` once the token is configured
5. `InfluxTokenSource = CredentialFile` after DPAPI migration

## Dry Run Without InfluxDB Write

Use this to test the HTTP measurement flow without sending metrics:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\qoe-probe.ps1 -SkipInfluxWrite
```

Logs are written to `logs\qoe-probe-YYYY-MM-DD.log`.

## Register the Scheduled Task

Use the helper script:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\scripts\register-qoe-task.ps1
```

By default the task name is `CX-Radar-QoE-Probe` and the interval is 5 minutes.

If you sign the scripts, prefer:

```powershell
& .\scripts\register-qoe-task.ps1 -ExecutionPolicy AllSigned
```

Use `Bypass` only as an explicit exception:

```powershell
& .\scripts\register-qoe-task.ps1 -ExecutionPolicy Bypass
```

## Post-Registration Checks

1. Open Task Scheduler and confirm the task exists.
2. Run the task once manually.
3. Confirm the log file updates.
4. Confirm metrics arrive in InfluxDB once the token is configured.
5. Confirm the action arguments show `RemoteSigned` or `AllSigned`, not `Bypass`, unless you deliberately approved the exception.

## Recovery

If the task exists but is not running correctly:

1. Run `scripts\validate-qoe-probe.ps1` again.
2. Check the daily log file in `logs\`.
3. Confirm the configured user can decrypt the DPAPI credential file or still has the temporary environment variable.
4. Re-register the task with the intended execution policy by rerunning `register-qoe-task.ps1`.