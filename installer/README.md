# CX-Radar Installer Bootstrap

This folder contains the first implementation slice of the bootstrapper-based installer model.

## What Is Implemented

- A per-user bootstrap install script that materializes a runtime under `%LOCALAPPDATA%\CX-Radar` or a custom root.
- Stable installer state persisted in `state\state.json`.
- Installer-owned templates for `probe-catalog.json` and `speed-test-catalog.json`.
- Payload export that creates a versioned zip archive and `manifest.json` for future updater work.
- A Windows EXE bootstrapper project under `installer\app\CXRadar.Bootstrapper` that wraps the PowerShell bootstrap flow for operator-facing installs.

## Bootstrap Smoke Install

Run this from the repository root to generate a runtime layout without registering scheduled tasks:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\installer\bootstrap\install-cx-radar-bootstrap.ps1 -HubName "My HUB" -SkipTaskRegistration -SkipDryRun
```

Useful switches:

- `-InstallRoot` to install into a temporary or custom per-user root.
- `-SpeedTestCliSourcePath` to seed `speedtest.exe` from a known path when it is not already under `%LOCALAPPDATA%\CX-Radar\tools\ookla-speedtest\speedtest.exe`.
- `-SkipValidation` to bypass validator execution while iterating on packaging.
- `-Force` to explicitly re-enroll an existing installation state.

## Payload Export

Create a payload archive and manifest from the current repo state:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\installer\build\export-cx-radar-payload.ps1
```

The export writes a versioned zip and `manifest.json` under `dist\installer` by default.

## WinExe Project

The operator-facing EXE project lives here:

- `installer\app\CXRadar.Bootstrapper\CXRadar.Bootstrapper.csproj`
- `installer\app\publish-bootstrapper.ps1`

The project copies a `bootstrap-assets` folder next to the built EXE. That asset tree preserves the repo-relative layout required by `install-cx-radar-bootstrap.ps1`, so the EXE can call the existing installer logic without depending on a full repo checkout on the operator machine.

The EXE currently presents:

- HUB name input
- optional Influx token input
- optional `speedtest.exe` picker
- install options for validation, dry runs, and scheduled-task registration

## Publish The EXE

Once the .NET SDK is installed on the build machine, publish the operator bundle with:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
& .\installer\app\publish-bootstrapper.ps1 -SelfContained -ZipOutput
```

The default output path is `dist\operator-bundle\bootstrapper\win-x64`.

If you want the EXE bundle to carry `speedtest.exe`, place it at `installer\assets\ookla-speedtest\speedtest.exe` before publishing. See `installer\assets\README.md`.

## Current Limits

- This slice now includes the C# EXE project, but it has not been built in this repo environment because no .NET SDK is installed locally.
- It does not yet download payloads from a remote manifest or register an updater task.
- Duplicate-HUB replacement workflow still needs backend or enrollment-file orchestration.
- The operator token flow is still local bootstrap logic. It does not yet use enrollment files or a bootstrap API.