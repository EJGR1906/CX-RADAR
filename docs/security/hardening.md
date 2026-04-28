# Hardening Notes

## Secret Handling

The probe now supports two token sources, in this order:

1. A user-scoped DPAPI protected credential file referenced by `influx.credentialFilePath`
2. The user or process environment variable named by `influx.tokenEnvVar`

Do not store the token directly in:

1. `qoe-probe.ps1`
2. `probe-catalog.json`
3. Task arguments
4. Plaintext log files

Recommended production path:

1. Store the token with `scripts\set-influx-token.ps1` so the value is encrypted with the current Windows user context via DPAPI.
2. Keep the secret file outside the repo, under `%LOCALAPPDATA%\CX-Radar\secrets\`.
3. Remove the user environment variable after migration unless a temporary rollback path is required.

Example:

```powershell
& .\scripts\set-influx-token.ps1
& .\scripts\set-influx-token.ps1 -ClearUserEnvironmentVariable
```

Credential Manager remains a valid future option, but it would require an extra module or a dedicated native API wrapper. The current repo defaults to DPAPI because it is Windows-native and works without adding new dependencies.

## PowerShell Execution Policy

Use the narrowest workable option in this order:

1. `AllSigned` if you are prepared to sign the probe and helper scripts.
2. `RemoteSigned` for local unsigned scripts on this monitored PC.
3. `Bypass` only as an explicit per-task fallback if a local control blocks the safer options and the exception is documented.

The scheduled-task helper now defaults to `-ExecutionPolicy RemoteSigned`, which is process-scoped for that task invocation and avoids weakening the whole host.

## Least Privilege

The task is registered with limited run level. Avoid administrator context unless a future dependency requires it and the requirement is explicitly documented.

The scheduled task also uses `RunOnlyIfNetworkAvailable` so the probe does not keep generating local failures while the workstation is offline.

## Rate and Reputation Safety

Five GET requests every 5 minutes from one host is still low-volume, but predictable timing and zero spacing make synthetic traffic easier to fingerprint.

The current config adds two guardrails by default:

1. `startJitterSecondsMax = 15` adds a small random delay at the beginning of each run.
2. `targetDelayMilliseconds = 750` spaces requests so the host does not burst all targets back-to-back.

Operational guardrails:

1. Keep one request per target per cycle.
2. Avoid sub-minute schedules for public streaming endpoints.
3. Keep the user agent stable and truthful.
4. Stagger multiple probes instead of launching them on the same wall-clock second.
5. Treat HTTP `403`, `429`, or repeated TLS resets as a signal to back off and review the cadence.

## Logging

The logs intentionally record outcomes and timing, but they should never record tokens, authorization headers, or verbose HTTP traces with secrets.