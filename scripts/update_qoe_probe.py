#!/usr/bin/env python3
"""CX-Radar QoE Probe Autoupdater.

Cross-platform Python script to download and update qoe_probe.py and
validate_qoe_probe.py from the main GitHub repository safely.
Calculates SHA-256 hashes to prevent unnecessary disk writes and checks
python syntax validity before replacing.
Also supports registering itself as a native daily task (e.g., at 8:00 AM).

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants & Helpers
# ---------------------------------------------------------------------------

UPDATER_VERSION = "0.1.0"
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/EJGR1906/CX-RADAR/main/scripts"
FILES_TO_UPDATE = [
    "install.py",
    "qoe_probe.py",
    "register_qoe_task.py",
    "run_qoe_certification.py",
    "set_influx_token.py",
    "setup_portable.py",
    "test_qoe_probe.py",
    "test_setup_portable.py",
    "test_update_qoe_probe.py",
    "update_qoe_probe.py",
    "validate_qoe_probe.py"
]


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


def compute_sha256(file_path: Path) -> str:
    """Compute the SHA-256 checksum of a file, normalizing CRLF to LF."""
    if not file_path.is_file():
        return ""
    h = hashlib.sha256()
    try:
        content = file_path.read_bytes()
        normalized = content.replace(b"\r\n", b"\n")
        h.update(normalized)
        return h.hexdigest()
    except Exception:
        return ""


def load_config_verify_tls(config_path: Path) -> bool:
    """Read verifyTls setting from config/probe-catalog.json."""
    if not config_path.is_file():
        return True
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return bool(data.get("probeRun", {}).get("verifyTls", True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Downloader with Fallback
# ---------------------------------------------------------------------------

def download_file(
    url: str, dest_path: Path, verify_ssl: bool
) -> bool:
    """Download url to dest_path using urllib, fallback to curl on failure."""
    # Create ssl context
    import ssl
    ctx = ssl.create_default_context()
    if not verify_ssl:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    print(f"Downloading {url} ...")
    
    # Try urllib first
    try:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL scheme in {url}. Only HTTP and HTTPS are allowed.")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"CX-Radar-Updater/{UPDATER_VERSION}"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:  # nosec B310
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(response, f)
        return True
    except Exception as e:
        print(f"  urllib download failed: {e}")
        
    # Fallback to curl
    curl_path = shutil.which("curl") or shutil.which("curl.exe")
    if curl_path:
        print(f"  Attempting fallback with curl...")
        args = [curl_path, "-fsSL", url, "-o", str(dest_path)]
        if not verify_ssl:
            args.append("-k")  # insecure
        code, stdout, stderr = run_cmd(args)
        if code == 0 and dest_path.is_file():
            print(f"  Successfully downloaded via curl.")
            return True
        print(f"  curl download failed (exit {code}): {stderr}")
    else:
        print(f"  curl is not available for fallback.")
        
    return False


# ---------------------------------------------------------------------------
# Update Verification and Replacement
# ---------------------------------------------------------------------------

def perform_updates(verify_ssl: bool, scripts_dir: Path, config_path: Path) -> int:
    """Download and update files. Returns count of files updated."""
    updated_count = 0
    
    for filename in FILES_TO_UPDATE:
        file_path = scripts_dir / filename
        tmp_path = scripts_dir / f"{filename}.tmp"
        url = f"{GITHUB_RAW_BASE}/{filename}"
        
        # Download to tmp file
        success = download_file(url, tmp_path, verify_ssl)
        if not success:
            print(f"Error: Failed to download {filename}. Skipping.")
            if tmp_path.is_file():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            continue
            
        # Verify python syntax by compiling
        try:
            code_content = tmp_path.read_text(encoding="utf-8")
            compile(code_content, str(tmp_path), "exec")
        except Exception as e:
            print(f"Error: Compiled check failed for downloaded {filename}: {e}. Skipping update.")
            try:
                tmp_path.unlink()
            except Exception:
                pass
            continue
            
        # Check hashes
        local_hash = compute_sha256(file_path)
        tmp_hash = compute_sha256(tmp_path)
        
        if local_hash == tmp_hash:
            print(f"No changes detected for {filename}. Up to date.")
            try:
                tmp_path.unlink()
            except Exception:
                pass
        else:
            print(f"Updating {filename} (Hash changed from {local_hash[:8]} to {tmp_hash[:8]})...")
            try:
                # Atomically replace
                os.replace(tmp_path, file_path)
                updated_count += 1
                print(f"Successfully updated {filename}.")
            except Exception as e:
                print(f"Error: Failed to replace {filename}: {e}")
                if tmp_path.is_file():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                        
    return updated_count


# ---------------------------------------------------------------------------
# Task Registration (Platform Native)
# ---------------------------------------------------------------------------

def register_windows(
    task_name: str, script_path: Path, time_str: str,
    run_as_current_user: bool, description: str
) -> bool:
    """Register daily task on Windows using PowerShell ScheduledTask cmdlets."""
    logon_type = "Interactive" if run_as_current_user else "S4U"
    
    ps_script = """
    $ErrorActionPreference = 'Stop'
    $action = New-ScheduledTaskAction -Execute $env:TASK_EXEC -Argument "`"$env:TASK_SCRIPT`""
    $trigger = New-ScheduledTaskTrigger -Daily -At $env:TASK_TIME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RunOnlyIfNetworkAvailable -StartWhenAvailable
    $currentUserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $currentUserName -LogonType $env:TASK_LOGON -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $env:TASK_DESC
    Register-ScheduledTask -TaskName $env:TASK_NAME -InputObject $task -Force | Out-Null
    """
    
    print(f"Registering Windows Scheduled Task '{task_name}' via PowerShell (LogonType: {logon_type}, Daily: {time_str})...")
    
    proc_env = os.environ.copy()
    proc_env["TASK_EXEC"] = sys.executable
    proc_env["TASK_SCRIPT"] = str(script_path)
    proc_env["TASK_TIME"] = time_str
    proc_env["TASK_LOGON"] = logon_type
    proc_env["TASK_DESC"] = description
    proc_env["TASK_NAME"] = task_name

    code, stdout, stderr = run_cmd([
        "powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script
    ], env=proc_env)
    
    if code == 0:
        print(f"Successfully registered Windows Scheduled Task '{task_name}'.")
        return True
        
    print(f"Error: PowerShell task registration failed (Exit: {code}).")
    print(stderr)
    
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


def register_linux_cron(task_name: str, script_path: Path, hour: int, minute: int) -> bool:
    """Register daily cron job on Linux."""
    cron_entry = f"{minute} {hour} * * * {sys.executable} {script_path} > /dev/null 2>&1 # {task_name}"
    print(f"Registering daily cron job: '{cron_entry}'...")
    
    code, stdout, stderr = run_cmd(["crontab", "-l"])
    
    lines = []
    if code == 0:
        lines = stdout.splitlines()
        
    filtered_lines = [l for l in lines if task_name not in l]
    filtered_lines.append(cron_entry)
    
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
    task_name: str, script_path: Path, hour: int, minute: int, description: str
) -> bool:
    """Register daily user-level systemd service and timer on Linux."""
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
ExecStart={sys.executable} {script_path}
"""

    timer_content = f"""[Unit]
Description=Run {task_name} daily

[Trigger]
OnCalendar=*-*-* {hour:02d}:{minute:02d}:00
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
    task_name: str, script_path: Path, hour: int, minute: int, description: str
) -> bool:
    """Register launch agent plist on macOS to run daily."""
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
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>WorkingDirectory</key>
    <string>{script_path.parent.parent}</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/launchd-{label}-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/launchd-{label}-stderr.log</string>
</dict>
</plist>
"""
    print(f"Writing LaunchAgent plist to {plist_path}...")
    try:
        plist_path.write_text(plist_content, encoding="utf-8")
    except Exception as e:
        print(f"Error writing launchd plist: {e}")
        return False
        
    print("Loading LaunchAgent...")
    run_cmd(["launchctl", "unload", str(plist_path)])
    code, _, stderr = run_cmd(["launchctl", "load", str(plist_path)])
    
    if code == 0:
        print(f"Successfully registered LaunchAgent '{label}'.")
        return True
        
    print(f"Error: launchctl load command failed (Exit: {code}).")
    print(stderr)
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="CX-Radar QoE Probe Autoupdater.")
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json (default: ../config/probe-catalog.json)"
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Bypass SSL certificate verification for downloading updates"
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Register autoupdater to run daily at 8:00 AM"
    )
    parser.add_argument(
        "--run-as-current-user",
        action="store_true",
        help="Windows only: registers scheduled task using Interactive logon"
    )
    parser.add_argument(
        "--task-name",
        type=str,
        default="CX-Radar-QoE-Updater",
        help="Scheduled task name (default: CX-Radar-QoE-Updater)"
    )
    parser.add_argument(
        "--time",
        type=str,
        default="08:00",
        help="Time to run daily task in HH:MM format (default: 08:00)"
    )
    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    
    if args.config_path:
        config_path = Path(args.config_path).resolve()
    else:
        config_path = (repo_root / "config" / "probe-catalog.json").resolve()
        
    # Read config TLS settings
    config_verify_tls = load_config_verify_tls(config_path)
    verify_ssl = (not args.no_verify_ssl) and config_verify_tls
    
    if not verify_ssl:
        print("SSL Verification: DISABLED")
    else:
        print("SSL Verification: ENABLED")

    # If register flag is set, handle task registration
    if args.register:
        # Validate time format
        try:
            hour_str, min_str = args.time.split(":")
            hour = int(hour_str)
            minute = int(min_str)
            if not (0 <= hour <= 23) or not (0 <= minute <= 59):
                raise ValueError()
        except ValueError:
            print("Error: --time must be in valid HH:MM format (e.g. 08:00).", file=sys.stderr)
            sys.exit(1)

        task_script_path = Path(__file__).resolve()
        description = "Automatically updates the CX-Radar QoE probe scripts daily."
        
        success = False
        if is_windows():
            success = register_windows(
                args.task_name, task_script_path, args.time,
                args.run_as_current_user, description
            )
        elif is_macos():
            success = register_macos_launchd(
                args.task_name, task_script_path, hour, minute, description
            )
        elif is_linux():
            if shutil.which("systemctl") is not None:
                success = register_linux_systemd(
                    args.task_name, task_script_path, hour, minute, description
                )
            else:
                success = register_linux_cron(args.task_name, task_script_path, hour, minute)
        else:
            print("Error: Unsupported OS for native scheduled task registration.", file=sys.stderr)
            sys.exit(1)

        if success:
            print(f"\nTask registration completed successfully.")
            sys.exit(0)
        else:
            print(f"\nError: Task registration failed.", file=sys.stderr)
            sys.exit(1)

    # Run check and update
    print(f"Checking for updates for scripts in {script_dir}...")
    updated = perform_updates(verify_ssl, script_dir, config_path)
    print(f"Update finished. {updated} files updated.")


if __name__ == "__main__":
    main()
