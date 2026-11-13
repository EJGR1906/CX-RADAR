#!/usr/bin/env python3
"""CX-Radar Unified Probe Installer.

Automates the entire installation and configuration process for CX-Radar
probes on Windows, Linux, and macOS. Supports interactive console inputs
as well as fully silent, unattended command-line deployments.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import subprocess
import sys
from pathlib import Path


def _is_windows() -> bool:
    return platform.system() == "Windows"


def load_catalog(config_path: Path) -> dict:
    if not config_path.is_file():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Failed to load config catalog from {config_path}: {e}")
        return {}


def save_catalog(config_path: Path, data: dict) -> None:
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Updated configuration catalog at {config_path}")
    except Exception as e:
        print(f"Error: Failed to save config catalog: {e}", file=sys.stderr)
        sys.exit(1)


def check_existing_token(repo_root: Path, var_name: str) -> bool:
    if os.environ.get(var_name):
        return True
    env_file = repo_root / ".env"
    if env_file.is_file():
        try:
            content = env_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith(f"{var_name}=") or line.startswith(f"export {var_name}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return True
        except Exception:
            pass
    return False


def build_local_override(base: dict, local: dict, values: dict) -> dict:
    """Ajustes propios de este servidor: solo lo que difiere del catálogo versionado.

    `config/probe-catalog.json` llega con cada actualización y no se debe editar
    en el servidor; lo propio va en `probe-catalog.local.json` (ver qoe_config.py).
    """
    result = json.loads(json.dumps(local)) if isinstance(local, dict) else {}
    for section, items in values.items():
        for key, value in items.items():
            if value is None or value == "":
                continue
            if base.get(section, {}).get(key) == value:
                result.get(section, {}).pop(key, None)
            else:
                result.setdefault(section, {})[key] = value
        if section in result and not result[section]:
            del result[section]
    return result


def upsert_env(env_path: Path, values: dict) -> None:
    """Escribe credenciales en `.env` con permisos solo para el usuario actual."""
    import set_influx_token as tok
    lines = tok._read_env_lines(env_path)
    for key, value in values.items():
        if value:
            lines = tok._upsert_env_line(lines, key, value)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tok._restrict_file_permissions(env_path)


def run_step(name: str, args: list[str], cwd: Path, env: dict | None = None, required: bool = True) -> bool:
    print(f"\n>>> Running Step: {name}...")
    print(f"    Command: {' '.join(args)}")
    if not required:
        code = subprocess.run(args, cwd=str(cwd), env=env).returncode
        print(f"[OK] Step '{name}' completed successfully." if code == 0
              else f"[AVISO] El paso '{name}' terminó con código {code}; la instalación continúa.")
        return code == 0
    try:
        # Run directly without capturing so the user gets real-time progress/interactive prompts
        result = subprocess.run(args, cwd=str(cwd), check=True, env=env)
        if result.returncode == 0:
            print(f"[OK] Step '{name}' completed successfully.")
            return True
        else:
            print(f"[ERROR] Step '{name}' failed with code {result.returncode}.", file=sys.stderr)
            sys.exit(result.returncode)
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Step '{name}' failed: {e}", file=sys.stderr)
        sys.exit(e.returncode if e.returncode is not None else 1)
    except Exception as e:
        print(f"[ERROR] Step '{name}' failed to execute: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    config_path = repo_root / "config" / "probe-catalog.json"

    print("==================================================")
    print("      CX-Radar Unified Probe Installer            ")
    print("==================================================")

    # 1. Parse CLI Arguments
    parser = argparse.ArgumentParser(
        description="Unified installation and setup tool for CX-Radar QoE probes."
    )
    
    # Probe metadata config
    parser.add_argument("--probe-id", type=str, help="Unique identifier for the probe.")
    parser.add_argument("--site", type=str, help="Location/site of the probe.")
    parser.add_argument("--environment", type=str, choices=["production", "staging", "development"], help="Target environment.")
    parser.add_argument("--isp", type=str, help="ISP or connection medium (e.g., home-fiber, starlink).")
    
    # InfluxDB config
    parser.add_argument("--influx-token", type=str, help="InfluxDB API token (write path permissions).")
    parser.add_argument("--influx-url", type=str, help="InfluxDB Cloud Base URL.")
    parser.add_argument("--influx-org", type=str, help="InfluxDB Organization name.")
    parser.add_argument("--influx-bucket", type=str, help="InfluxDB Bucket name.")
    
    # Installer settings
    # Alertas y plan contratado
    parser.add_argument("--telegram-bot-token", type=str, help="Token del bot de Telegram para las alertas (opcional).")
    parser.add_argument("--telegram-chat-id", type=str, help="Chat de Telegram que recibe las alertas (opcional).")
    parser.add_argument("--plan-down-mbps", type=float, help="Velocidad de bajada contratada, para el aviso de velocidad baja (opcional).")
    parser.add_argument("--plan-up-mbps", type=float, help="Velocidad de subida contratada (opcional).")

    parser.add_argument("--interval-minutes", type=int, default=30,
                        help="Cada cuántos minutos corre la sonda completa de velocidad (por defecto 30; cada corrida consume datos).")
    parser.add_argument("--run-as-current-user", action="store_true", help="Windows Task Scheduler: run as interactive logged-in user.")
    parser.add_argument("--no-verify-ssl", action="store_true", help="Bypass SSL verification for legacy systems.")
    parser.add_argument("--force-tools", action="store_true", help="Force downloading and extraction of portable tools.")
    parser.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting if settings are missing.")
    
    args = parser.parse_args()

    # Load current configuration defaults (catálogo versionado + ajustes locales ya existentes)
    sys.path.insert(0, str(script_dir))
    import qoe_config
    base_catalog = load_catalog(config_path)
    local_path = qoe_config.local_override_path(config_path)
    local_catalog = load_catalog(local_path)
    catalog = qoe_config.deep_merge(base_catalog, local_catalog)
    probe_cfg = catalog.setdefault("probe", {})
    influx_cfg = catalog.setdefault("influx", {})
    var_name = influx_cfg.get("tokenEnvVar", "INFLUXDB_TOKEN")

    # Determine interactive prompts if needed
    is_interactive = not args.non_interactive

    if is_interactive:
        print("\n[Configuration Setup] Press Enter to accept the defaults in brackets.")

    # Probe configuration gathering
    probe_id = args.probe_id
    if not probe_id:
        default_id = probe_cfg.get("probeId") or platform.node().lower()
        if is_interactive:
            probe_id = input(f"  Probe ID [{default_id}]: ").strip() or default_id
        else:
            probe_id = default_id

    site = args.site
    if not site:
        default_site = probe_cfg.get("site") or "home-office"
        if is_interactive:
            site = input(f"  Probe Site [{default_site}]: ").strip() or default_site
        else:
            site = default_site

    environment = args.environment
    if not environment:
        default_env = probe_cfg.get("environment") or "production"
        if is_interactive:
            environment = input(f"  Probe Environment [{default_env}]: ").strip() or default_env
        else:
            environment = default_env

    isp = args.isp
    if not isp:
        default_isp = probe_cfg.get("isp") or "home-fiber"
        if is_interactive:
            isp = input(f"  Probe ISP [{default_isp}]: ").strip() or default_isp
        else:
            isp = default_isp

    # InfluxDB configuration gathering
    influx_url = args.influx_url
    if not influx_url:
        default_url = influx_cfg.get("baseUrl") or "https://us-east-1-1.aws.cloud2.influxdata.com"
        if is_interactive:
            influx_url = input(f"  InfluxDB URL [{default_url}]: ").strip() or default_url
        else:
            influx_url = default_url

    influx_org = args.influx_org
    if not influx_org:
        default_org = influx_cfg.get("org") or "cx-radar"
        if is_interactive:
            influx_org = input(f"  InfluxDB Org [{default_org}]: ").strip() or default_org
        else:
            influx_org = default_org

    influx_bucket = args.influx_bucket
    if not influx_bucket:
        default_bucket = influx_cfg.get("bucket") or "qoe_metrics"
        if is_interactive:
            influx_bucket = input(f"  InfluxDB Bucket [{default_bucket}]: ").strip() or default_bucket
        else:
            influx_bucket = default_bucket

    # Gather token
    token = args.influx_token
    token_exists = check_existing_token(repo_root, var_name)
    if not token:
        if is_interactive:
            prompt_msg = f"  Enter InfluxDB API Token ({var_name}): "
            if token_exists:
                prompt_msg = f"  Enter InfluxDB API Token (leave empty to keep existing): "
            token = getpass.getpass(prompt_msg).strip()
        
        if not token and not token_exists:
            print(f"Error: InfluxDB Token is required to initialize the probe.", file=sys.stderr)
            sys.exit(1)

    # Telegram y plan contratado (opcionales)
    env_creds = {}
    try:
        import qoe_telegram
        env_creds = qoe_telegram.get_credentials(repo_root / ".env")
    except Exception:
        env_creds = {"token": "", "chat_id": ""}
    tg_token = args.telegram_bot_token or ""
    tg_chat = args.telegram_chat_id or ""
    plan_down, plan_up = args.plan_down_mbps, args.plan_up_mbps
    if is_interactive:
        print("\n[Alertas por Telegram] Sin esto la sonda mide pero no avisa. Enter para dejarlo como está.")
        if not tg_token:
            state = "ya configurado" if env_creds.get("token") else "sin configurar"
            tg_token = getpass.getpass(f"  Token del bot de Telegram ({state}): ").strip()
        if not tg_chat:
            tg_chat = input(f"  Chat ID de Telegram [{env_creds.get('chat_id') or 'sin configurar'}]: ").strip()
        print("\n[Plan contratado] Para avisar cuando la velocidad baje del 50 % del plan. Enter para omitir.")
        if plan_down is None:
            raw = input(f"  Bajada contratada en Mbps [{probe_cfg.get('planDownMbps', 'sin definir')}]: ").strip()
            plan_down = float(raw) if raw.replace(".", "", 1).isdigit() else None
        if plan_up is None:
            raw = input(f"  Subida contratada en Mbps [{probe_cfg.get('planUpMbps', 'sin definir')}]: ").strip()
            plan_up = float(raw) if raw.replace(".", "", 1).isdigit() else None

    # 2. Guardar los ajustes de este servidor en probe-catalog.local.json (el catálogo versionado no se toca)
    override = build_local_override(base_catalog, local_catalog, {
        "probe": {"probeId": probe_id, "site": site, "environment": environment, "isp": isp,
                  "planDownMbps": plan_down, "planUpMbps": plan_up},
        "influx": {"baseUrl": influx_url, "org": influx_org, "bucket": influx_bucket},
    })
    save_catalog(local_path, override)

    # 3. Store Token if provided (por variable de entorno: no queda en la línea de comandos ni en pantalla)
    if token:
        token_cmd = [
            sys.executable,
            str(script_dir / "set_influx_token.py"),
            "--method", "file",
            "--force"
        ]
        run_step("Store InfluxDB Token", token_cmd, repo_root, env={**os.environ, "CX_RADAR_PROVISIONING_TOKEN": token})
    else:
        print("\n[OK] Keeping existing InfluxDB token.")

    if tg_token or tg_chat:
        upsert_env(repo_root / ".env", {"TELEGRAM_BOT_TOKEN": tg_token, "TELEGRAM_CHAT_ID": tg_chat})
        print("[OK] Credenciales de Telegram guardadas en .env")

    # 4. Install Portable Tools
    tools_cmd = [
        sys.executable,
        str(script_dir / "setup_portable.py")
    ]
    if args.force_tools:
        tools_cmd.append("--force")
    run_step("Install Portable Tools", tools_cmd, repo_root)

    # 5. Register Task Schedulers
    # QoE Probe Task
    register_cmd = [
        sys.executable,
        str(script_dir / "register_qoe_task.py"),
        "--interval-minutes", str(args.interval_minutes)
    ]
    if args.run_as_current_user:
        register_cmd.append("--run-as-current-user")
    run_step("Register Scheduled QoE Task", register_cmd, repo_root)

    # Monitor de cada minuto: es el que detecta y avisa las fallas de conexión
    heartbeat_cmd = [
        sys.executable,
        str(script_dir / "register_qoe_task.py"),
        "--script", "heartbeat",
        "--task-name", "CX-Radar-Heartbeat",
        "--interval-minutes", "1",
        "--description", "CX-Radar: monitor de la conexión cada minuto y alertas."
    ]
    if args.run_as_current_user:
        heartbeat_cmd.append("--run-as-current-user")
    run_step("Register Heartbeat Task (every minute)", heartbeat_cmd, repo_root)

    # QoE Probe Auto-Updater Task
    updater_cmd = [
        sys.executable,
        str(script_dir / "update_qoe_probe.py"),
        "--register"
    ]
    if args.run_as_current_user:
        updater_cmd.append("--run-as-current-user")
    if args.no_verify_ssl:
        updater_cmd.append("--no-verify-ssl")
    run_step("Register Scheduled Auto-Updater Task", updater_cmd, repo_root)

    # 6. Validation
    validate_cmd = [
        sys.executable,
        str(script_dir / "validate_qoe_probe.py")
    ]
    run_step("Validate Environment Check", validate_cmd, repo_root)

    # 7. Smoke Dry-Run Check
    smoke_cmd = [
        sys.executable,
        str(script_dir / "qoe_probe.py"),
        "--skip-influx-write"
    ]
    run_step("Perform Dry-Run Smoke Test", smoke_cmd, repo_root)

    # 8. Monitor de cada minuto: una corrida corta real y mensaje de prueba por Telegram
    run_step("Heartbeat Test Run", [
        sys.executable, str(script_dir / "qoe_heartbeat.py"),
        "--skip-influx-write", "--skip-telegram", "--rounds", "2"
    ], repo_root)
    import qoe_telegram
    telegram_ready = qoe_telegram.is_configured(qoe_telegram.get_credentials(repo_root / ".env"))
    if telegram_ready:
        telegram_ready = run_step("Telegram Test Message", [sys.executable, str(script_dir / "qoe_telegram.py"), "--test"],
                                  repo_root, required=False)

    print("\n==================================================")
    if not telegram_ready:
        print(" AVISO: Telegram no quedó configurado o no respondió.")
        print(" La sonda mide, pero NO avisará las fallas hasta     ")
        print(" completar TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en  ")
        print(" .env (ver docs/operations/medicion-real-y-alertas.md).")
    print(" El aviso durante una caída total lo da Grafana Cloud:")
    print("   python scripts/setup_grafana_alert.py --grafana-url https://<stack>.grafana.net")
    print("==================================================")
    print("      Installation Completed Successfully!        ")
    print("==================================================")
    print(" Your CX-Radar probe has been configured, verified, ")
    print(" and scheduled to run in the background.            ")
    print("==================================================")


if __name__ == "__main__":
    main()
