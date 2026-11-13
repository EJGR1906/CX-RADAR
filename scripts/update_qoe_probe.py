#!/usr/bin/env python3
"""CX-Radar: actualizador de los scripts de la sonda.

Descarga `release-manifest.json` (lista de archivos con su SHA-256) y los
scripts que cambiaron, y los instala todos o ninguno:

1. Cada archivo descargado debe coincidir con el SHA-256 del manifiesto.
2. Cada archivo debe compilar y el conjunto debe poder importarse.
3. Los archivos actuales se respaldan en `scripts/.update-backup/` y, si un
   reemplazo falla a mitad, se restauran.

TLS se verifica siempre (`--no-verify-ssl` ya no tiene efecto): este programa
descarga código que luego se ejecuta.

Alcance real de la verificación: el manifiesto viene del mismo repositorio que
los archivos, así que protege contra descargas cortadas, corruptas o mezcladas,
no contra alguien con permiso de escritura en el repositorio. No es una firma
digital. Para fijar una versión revisada usar `--ref <tag>`.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
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
GITHUB_RAW_ROOT = "https://raw.githubusercontent.com/EJGR1906/CX-RADAR"
DEFAULT_REF = "main"
GITHUB_RAW_BASE = f"{GITHUB_RAW_ROOT}/{DEFAULT_REF}/scripts"
MANIFEST_NAME = "release-manifest.json"
STAGING_DIR = ".update-staging"
BACKUP_DIR = ".update-backup"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_]+\.py$")
FILES_TO_UPDATE = [
    "install.py",
    # Módulos que importa qoe_probe.py: van antes para que nunca quede una sonda
    # nueva sin sus dependencias si una descarga falla a mitad.
    "qoe_throughput.py",
    "qoe_config.py",
    "qoe_telegram.py",
    "qoe_speed_alert.py",
    "qoe_probe.py",
    "qoe_heartbeat.py",
    "onu_report.py",
    "register_qoe_task.py",
    "run_qoe_certification.py",
    "set_influx_token.py",
    "setup_portable.py",
    "setup_grafana_alert.py",
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
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        raise ValueError("URL must start with http:// or https://")

    # TLS siempre verificado: lo descargado se ejecuta. `verify_ssl` se conserva solo por compatibilidad.
    import ssl
    ctx = ssl.create_default_context()

    print(f"Downloading {url} ...")
    
    # Try urllib first
    try:
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
        args = [curl_path, "-fsSL", "--proto", "=https", url, "-o", str(dest_path)]
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

def build_manifest(scripts_dir: Path) -> Dict[str, Any]:
    """Manifiesto de los scripts que se distribuyen (se versiona junto con ellos)."""
    return {"files": {name: compute_sha256(scripts_dir / name) for name in FILES_TO_UPDATE}}


def write_manifest(scripts_dir: Path) -> Path:
    path = scripts_dir / MANIFEST_NAME
    path.write_text(json.dumps(build_manifest(scripts_dir), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_manifest(path: Path) -> Dict[str, str]:
    """Devuelve {archivo: sha256}. Lanza ValueError si el manifiesto no es válido."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"manifiesto ilegible: {e}") from e
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict) or not files:
        raise ValueError("manifiesto sin lista de archivos")
    for name, digest in files.items():
        if not isinstance(name, str) or not SAFE_NAME.match(name):
            raise ValueError(f"nombre de archivo no permitido en el manifiesto: {name!r}")
        if not isinstance(digest, str) or not re.match(r"^[0-9a-f]{64}$", digest):
            raise ValueError(f"SHA-256 inválido para {name}")
    return files


def import_check(staging: Path) -> Tuple[bool, str]:
    """Comprueba en un proceso aparte que el conjunto nuevo se puede importar."""
    modules = ["qoe_throughput", "qoe_config", "qoe_telegram", "qoe_probe", "qoe_heartbeat"]
    present = [m for m in modules if (staging / f"{m}.py").is_file()]
    code = "import sys; sys.path.insert(0, sys.argv[1]); " + "; ".join(f"import {m}" for m in present)
    ret, _, stderr = run_cmd([sys.executable, "-c", code, str(staging)])
    return ret == 0, stderr.strip()[-500:]


def perform_updates(verify_ssl: bool, scripts_dir: Path, config_path: Path, ref: str = DEFAULT_REF) -> int:
    """Actualiza todos los scripts que cambiaron, o ninguno. Devuelve cuántos se actualizaron."""
    base_url = f"{GITHUB_RAW_ROOT}/{ref}/scripts"
    staging = scripts_dir / STAGING_DIR
    backup = scripts_dir / BACKUP_DIR
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    def abort(reason: str) -> int:
        print(f"Error: {reason}. No se cambió ningún archivo.")
        shutil.rmtree(staging, ignore_errors=True)
        return 0

    manifest_path = staging / MANIFEST_NAME
    if not download_file(f"{base_url}/{MANIFEST_NAME}", manifest_path, True):
        return abort("no se pudo descargar el manifiesto")
    try:
        manifest = load_manifest(manifest_path)
    except ValueError as e:
        return abort(str(e))

    changed: List[str] = []
    for name, expected in sorted(manifest.items()):
        if compute_sha256(scripts_dir / name) == expected:
            continue
        staged = staging / name
        if not download_file(f"{base_url}/{name}", staged, True):
            return abort(f"no se pudo descargar {name}")
        actual = compute_sha256(staged)
        if actual != expected:
            return abort(f"{name} no coincide con el manifiesto (esperado {expected[:12]}, recibido {actual[:12]})")
        try:
            compile(staged.read_text(encoding="utf-8"), str(staged), "exec")
        except Exception as e:
            return abort(f"{name} no compila: {e}")
        changed.append(name)

    if not changed:
        print("Todos los scripts están al día.")
        shutil.rmtree(staging, ignore_errors=True)
        return 0

    # El conjunto completo (lo nuevo más lo que no cambió) debe poder importarse antes de instalarlo.
    for name in manifest:
        if name not in changed and (scripts_dir / name).is_file():
            shutil.copy2(scripts_dir / name, staging / name)
    ok, detail = import_check(staging)
    if not ok:
        return abort(f"el conjunto nuevo no se puede importar: {detail}")

    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True, exist_ok=True)
    replaced: List[str] = []
    try:
        for name in changed:
            target = scripts_dir / name
            if target.is_file():
                shutil.copy2(target, backup / name)
            os.replace(staging / name, target)
            replaced.append(name)
            print(f"Actualizado {name}.")
    except Exception as e:
        for name in replaced:
            if (backup / name).is_file():
                shutil.copy2(backup / name, scripts_dir / name)
            else:
                try:
                    (scripts_dir / name).unlink()
                except OSError:
                    pass
        return abort(f"falló el reemplazo ({e}); se restauró la versión anterior")
    shutil.copy2(manifest_path, scripts_dir / MANIFEST_NAME)
    shutil.rmtree(staging, ignore_errors=True)
    return len(changed)


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
    parser.add_argument("--ref", type=str, default=DEFAULT_REF,
                        help="Rama o tag del repositorio desde donde actualizar (por defecto main)")
    parser.add_argument("--write-manifest", action="store_true",
                        help="Regenera scripts/release-manifest.json (para quien publica cambios)")
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
        
    if args.write_manifest:
        print(f"Manifiesto escrito en {write_manifest(script_dir)}")
        return
    if not re.match(r"^[A-Za-z0-9._/-]+$", args.ref) or ".." in args.ref:
        print("Error: --ref no es un nombre de rama o tag válido.", file=sys.stderr)
        sys.exit(1)

    verify_ssl = True
    if args.no_verify_ssl or not load_config_verify_tls(config_path):
        print("Aviso: el actualizador siempre verifica TLS; --no-verify-ssl y verifyTls=false no aplican aquí.")

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
    updated = perform_updates(verify_ssl, script_dir, config_path, args.ref)
    print(f"Update finished. {updated} files updated.")


if __name__ == "__main__":
    main()
