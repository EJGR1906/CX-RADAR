#!/usr/bin/env python3
"""CX-Radar QoE Probe Task Registration.

Cross-platform Python port of register-qoe-task.ps1.
Registers the QoE probe to run on a recurring schedule (default: 10 minutes)
using platform-native schedulers.

Supports:
- Windows: Task Scheduler (schtasks cmdlets)
- Linux: systemd timers or cron
- macOS: launchd

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def run_cmd(args: List[str], env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def register_windows(
    task_name: str, script_path: Path, config_path: Path, interval_minutes: int,
    run_as_current_user: bool, description: str
) -> bool:
    """Register task on Windows using PowerShell ScheduledTask cmdlets."""
    # Build PowerShell command
    # S4U logon type works in background without prompting for password, but requires LogonType S4U.
    # LogonType Interactive runs when the user is logged in.
    logon_type = "Interactive" if run_as_current_user else "S4U"
    
    ps_script = """
    $ErrorActionPreference = 'Stop'
    $action = New-ScheduledTaskAction -Execute $env:TASK_EXEC -Argument "`"$env:TASK_SCRIPT`" --config-path `"$env:TASK_CONFIG`""
    $trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).Date) -RepetitionInterval (New-TimeSpan -Minutes ([int]$env:TASK_INTERVAL))
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable -StartWhenAvailable
    $currentUserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $currentUserName -LogonType $env:TASK_LOGON -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $env:TASK_DESC
    Register-ScheduledTask -TaskName $env:TASK_NAME -InputObject $task -Force | Out-Null
    """
    
    print(f"Registering Windows Scheduled Task '{task_name}' via PowerShell (LogonType: {logon_type})...")
    
    proc_env = os.environ.copy()
    proc_env["TASK_EXEC"] = sys.executable
    proc_env["TASK_SCRIPT"] = str(script_path)
    proc_env["TASK_CONFIG"] = str(config_path)
    proc_env["TASK_INTERVAL"] = str(interval_minutes)
    proc_env["TASK_LOGON"] = logon_type
    proc_env["TASK_DESC"] = description
    proc_env["TASK_NAME"] = task_name

    # We invoke powershell
    code, stdout, stderr = run_cmd([
        "powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script
    ], env=proc_env)
    
    if code == 0:
        print(f"Successfully registered Windows Scheduled Task '{task_name}'.")
        return True
        
    print(f"Error: PowerShell task registration failed (Exit: {code}).")
    print(stderr)
    
    # If S4U failed, try interactive logon type as fallback
    if logon_type == "S4U":
        print("\nRetrying with interactive logon type (equivalent to --run-as-current-user)...")
        proc_env["TASK_LOGON"] = "Interactive"
        code_retry, _, stderr_retry = run_cmd([
            "powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script
        ], env=proc_env)
        if code_retry == 0:
            print(f"Successfully registered Windows Scheduled Task '{task_name}' (Interactive logon).")
            return True
        print(f"Error: Retry failed.")
        print(stderr_retry)
        
    return False


def register_linux_cron(task_name: str, script_path: Path, config_path: Path, interval_minutes: int) -> bool:
    """Register task on Linux using cron."""
    cron_entry = f"*/{interval_minutes} * * * * {sys.executable} {script_path} --config-path {config_path} > /dev/null 2>&1 # {task_name}"
    print(f"Registering cron job: '{cron_entry}'...")
    
    # Read current crontab
    code, stdout, stderr = run_cmd(["crontab", "-l"])
    
    # If crontab empty, ignore error
    lines = []
    if code == 0:
        lines = stdout.splitlines()
        
    # Remove any existing entries for this task name
    filtered_lines = [l for l in lines if task_name not in l]
    filtered_lines.append(cron_entry)
    
    # Write back
    new_cron = "\n".join(filtered_lines) + "\n"
    proc = subprocess.Popen(["crontab", "-"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(input=new_cron)
    
    if proc.returncode == 0:
        print(f"Successfully registered cron job for '{task_name}'.")
        return True
        
    print(f"Error: Failed to write crontab (Exit: {proc.returncode}).")
    print(err)
    return False


def register_linux_systemd(
    task_name: str, script_path: Path, config_path: Path, interval_minutes: int, description: str
) -> bool:
    """Register user-level systemd service and timer on Linux."""
    safe_name = task_name.lower().replace(" ", "-")
    systemd_user_dir = Path.home() / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)
    
    service_path = systemd_user_dir / f"{safe_name}.service"
    timer_path = systemd_user_dir / f"{safe_name}.timer"
    
    service_content = f"""[Unit]
Description={description}
After=network.target

[Service]
Type=oneshot
WorkingDirectory={script_path.parent.parent}
ExecStart={sys.executable} {script_path} --config-path {config_path}
EnvironmentFile={script_path.parent.parent}/.env
"""

    timer_content = f"""[Unit]
Description=Run {task_name} every {interval_minutes} minutes

[Timer]
OnCalendar=*:0/{interval_minutes}
RandomizedDelaySec=15
Persistent=true

[Install]
WantedBy=timers.target
"""
    print(f"Writing systemd units to {systemd_user_dir}...")
    try:
        service_path.write_text(service_content, encoding="utf-8")
        timer_path.write_text(timer_content, encoding="utf-8")
    except Exception as e:
        print(f"Error writing systemd units: {e}")
        return False
        
    # Reload and enable
    print("Reloading systemd user daemon and enabling timer...")
    run_cmd(["systemctl", "--user", "daemon-reload"])
    code, _, stderr = run_cmd(["systemctl", "--user", "enable", "--now", f"{safe_name}.timer"])
    
    if code == 0:
        print(f"Successfully enabled systemd timer '{safe_name}.timer'.")
        return True
        
    print(f"Error: systemctl command failed (Exit: {code}).")
    print(stderr)
    return False


def register_macos_launchd(
    task_name: str, script_path: Path, config_path: Path, interval_minutes: int, description: str
) -> bool:
    """Register launch agent plist on macOS."""
    label = f"com.cx-radar.{task_name.lower().replace(' ', '-')}"
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    
    plist_path = agents_dir / f"{label}.plist"
    log_dir = script_path.parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{sys.executable}</string>
        <string>{script_path}</string>
        <string>--config-path</string>
        <string>{config_path}</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_minutes * 60}</integer>
    <key>WorkingDirectory</key>
    <string>{script_path.parent.parent}</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/launchd-{label}-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/launchd-{label}-stderr.log</string>
    <!-- Note: EnvironmentVariables is intentionally omitted. qoe_probe.py natively resolves INFLUXDB_TOKEN from the local .env file. -->
</dict>
</plist>
"""
    print(f"Writing LaunchAgent plist to {plist_path}...")
    try:
        plist_path.write_text(plist_content, encoding="utf-8")
    except Exception as e:
        print(f"Error writing launchd plist: {e}")
        return False
        
    # Unload if already loaded, then load
    print("Loading LaunchAgent...")
    run_cmd(["launchctl", "unload", str(plist_path)])
    code, _, stderr = run_cmd(["launchctl", "load", str(plist_path)])
    
    if code == 0:
        print(f"Successfully registered LaunchAgent '{label}'.")
        return True
        
    print(f"Error: launchctl load command failed (Exit: {code}).")
    print(stderr)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="CX-Radar QoE Probe Task Registration (cross-platform).")
    parser.add_argument(
        "--task-name",
        type=str,
        default="CX-Radar-QoE-Probe",
        help="Name of scheduled task / timer / agent (default: CX-Radar-QoE-Probe)"
    )
    parser.add_argument(
        "--interval-minutes",
        type=int,
        default=10,
        help="Recurrent execution interval in minutes (default: 10, range: 1-1440)"
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json"
    )
    parser.add_argument(
        "--method",
        type=str,
        choices=["auto", "schtasks", "cron", "systemd", "launchd"],
        default="auto",
        help="Scheduling method (default: auto)"
    )
    parser.add_argument(
        "--run-as-current-user",
        action="store_true",
        help="Windows only: registers task using Interactive logon instead of S4U"
    )
    parser.add_argument(
        "--description",
        type=str,
        default="Runs the CX-Radar QoE probe and sends metrics to InfluxDB Cloud.",
        help="Task description"
    )
    args = parser.parse_args()

    if args.interval_minutes < 1 or args.interval_minutes > 1440:
        print("Error: --interval-minutes must be between 1 and 1440.", file=sys.stderr)
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    probe_script_path = (script_dir / "qoe_probe.py").resolve()

    if args.config_path:
        config_path = Path(args.config_path).resolve()
    else:
        config_path = (repo_root / "config" / "probe-catalog.json").resolve()

    if not probe_script_path.is_file():
        print(f"Error: Main probe script not found at {probe_script_path}", file=sys.stderr)
        sys.exit(1)
        
    if not config_path.is_file():
        print(f"Error: Configuration catalog file not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    method = args.method
    if method == "auto":
        if is_windows():
            method = "schtasks"
        elif is_macos():
            method = "launchd"
        elif is_linux():
            # Check systemd user units support or default to cron
            if shutil.which("systemctl") is not None:
                method = "systemd"
            else:
                method = "cron"
        else:
            print("Error: Unsupported operating system for automatic scheduler registration.", file=sys.stderr)
            sys.exit(1)

    success = False
    if method == "schtasks":
        if not is_windows():
            print("Error: schtasks scheduling method is Windows only.", file=sys.stderr)
            sys.exit(1)
        success = register_windows(
            args.task_name, probe_script_path, config_path, args.interval_minutes,
            args.run_as_current_user, args.description
        )
    elif method == "cron":
        if is_windows():
            print("Error: cron scheduling method is not supported on Windows.", file=sys.stderr)
            sys.exit(1)
        success = register_linux_cron(args.task_name, probe_script_path, config_path, args.interval_minutes)
    elif method == "systemd":
        if not is_linux():
            print("Error: systemd scheduling method is Linux only.", file=sys.stderr)
            sys.exit(1)
        success = register_linux_systemd(
            args.task_name, probe_script_path, config_path, args.interval_minutes, args.description
        )
    elif method == "launchd":
        if not is_macos():
            print("Error: launchd scheduling method is macOS only.", file=sys.stderr)
            sys.exit(1)
        success = register_macos_launchd(
            args.task_name, probe_script_path, config_path, args.interval_minutes, args.description
        )

    if success:
        print(f"\nTask registration completed successfully using '{method}' method.")
    else:
        print(f"\nError: Task registration failed using '{method}' method.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
