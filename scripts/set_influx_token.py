#!/usr/bin/env python3
"""Set the InfluxDB Cloud API token for the QoE probe.

Cross-platform Python port of set-influx-token.ps1.
Supports two storage methods:
  • file  – write to a .env file with restricted OS permissions (default)
  • env   – persist via ``setx`` (Windows) or shell-rc export (Linux/macOS)

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_windows() -> bool:
    return platform.system() == "Windows"


def _resolve_from_base(base: Path, child: str) -> Path:
    expanded = os.path.expandvars(child)
    p = Path(expanded)
    if p.is_absolute():
        return p.resolve()
    return (base / p).resolve()


def _load_config(config_path: Path) -> dict:
    return json.loads(config_path.read_text(encoding="utf-8"))


def _get_token_env_var(config: dict) -> str:
    return str(config.get("influx", {}).get("tokenEnvVar", "INFLUXDB_TOKEN"))


# ---------------------------------------------------------------------------
# .env file storage
# ---------------------------------------------------------------------------

def _read_env_lines(env_path: Path) -> list:
    """Return existing lines (preserving order) or empty list."""
    if not env_path.is_file():
        return []
    return env_path.read_text(encoding="utf-8").splitlines()


def _upsert_env_line(lines: list, var_name: str, var_value: str) -> list:
    """Replace or append a KEY=VALUE pair in the line list."""
    new_line = f"{var_name}={var_value}"
    found = False
    result = []
    for line in lines:
        stripped = line.strip()
        # Match bare KEY=… or export KEY=…
        bare = stripped
        if bare.startswith("export "):
            bare = bare[len("export "):]
        key, _, _ = bare.partition("=")
        if key.strip() == var_name:
            result.append(new_line)
            found = True
        else:
            result.append(line)
    if not found:
        result.append(new_line)
    return result


def _restrict_file_permissions(path: Path) -> None:
    """Best-effort OS-level permission restriction (owner-only)."""
    if _is_windows():
        try:
            user = os.environ.get("USERNAME", "")
            if user:
                # Remove inherited ACLs, grant only current user full control
                subprocess.run(
                    ["icacls", str(path), "/inheritance:r",
                     "/grant:r", f"{user}:(F)"],
                    check=False,
                    capture_output=True,
                )
        except FileNotFoundError:
            pass  # icacls not available (unlikely on Windows)
    else:
        try:
            path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except OSError:
            pass


def _write_env_file(
    env_path: Path, var_name: str, token: str, force: bool
) -> None:
    lines = _read_env_lines(env_path)

    # Check if variable already exists
    already_set = any(
        (l.strip().startswith(f"{var_name}=")
         or l.strip().startswith(f"export {var_name}="))
        for l in lines
    )
    if already_set and not force:
        raise SystemExit(
            f"Variable '{var_name}' already exists in {env_path}. "
            f"Use --force to overwrite."
        )

    lines = _upsert_env_line(lines, var_name, token)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restrict_file_permissions(env_path)

    print(f"Token written to {env_path}")
    print(f"  Variable : {var_name}")
    print(f"  Method   : file (.env)")


# ---------------------------------------------------------------------------
# Persistent environment variable
# ---------------------------------------------------------------------------

def _detect_shell_rc() -> Path:
    """Return the preferred shell rc file for the current user."""
    shell = os.environ.get("SHELL", "")
    home = Path.home()
    if "zsh" in shell:
        return home / ".zshrc"
    return home / ".bashrc"


def _set_env_persistent(var_name: str, token: str, force: bool) -> None:
    if _is_windows():
        # setx persists to the user environment on Windows
        result = subprocess.run(
            ["setx", var_name, token],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit(
                f"setx failed (exit {result.returncode}): {result.stderr.strip()}"
            )
        print(f"Token set via setx for current user.")
        print(f"  Variable : {var_name}")
        print(f"  Method   : env (setx)")
        print(f"  Note     : Open a new terminal for the change to take effect.")
    else:
        rc_file = _detect_shell_rc()
        export_line = f'export {var_name}="{token}"'
        existing = ""
        if rc_file.is_file():
            existing = rc_file.read_text(encoding="utf-8")

        # Check if already present
        if f"export {var_name}=" in existing:
            if not force:
                raise SystemExit(
                    f"Variable '{var_name}' already exported in {rc_file}. "
                    f"Use --force to overwrite."
                )
            # Replace existing line
            new_lines = []
            for line in existing.splitlines():
                if line.strip().startswith(f"export {var_name}="):
                    new_lines.append(export_line)
                else:
                    new_lines.append(line)
            rc_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        else:
            with rc_file.open("a", encoding="utf-8") as f:
                f.write(f"\n# CX-Radar InfluxDB token\n{export_line}\n")

        print(f"Token appended to {rc_file}")
        print(f"  Variable : {var_name}")
        print(f"  Method   : env (shell rc)")
        print(f"  Note     : Run 'source {rc_file}' or open a new terminal.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set the InfluxDB Cloud API token for the QoE probe (cross-platform)."
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json (default: ../config/probe-catalog.json)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="InfluxDB token value. Prompted securely if omitted.",
    )
    parser.add_argument(
        "--method",
        choices=["env", "file"],
        default="file",
        help="Storage method: 'file' (default) writes a .env file; 'env' sets a persistent environment variable.",
    )
    parser.add_argument(
        "--env-file-path",
        type=str,
        default="",
        help="Path for the .env file (default: .env in repo root).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite if the variable already exists.",
    )
    args = parser.parse_args()

    # --- Resolve config path ---
    if args.config_path:
        config_path = Path(args.config_path).resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        config_path = (script_dir / ".." / "config" / "probe-catalog.json").resolve()

    if not config_path.is_file():
        raise SystemExit(f"Config file not found: {config_path}")

    config = _load_config(config_path)
    var_name = _get_token_env_var(config)

    # --- Obtain token ---
    token = args.token
    if not token:
        token = getpass.getpass(prompt=f"Enter InfluxDB Cloud API token ({var_name}): ")
    if not token.strip():
        raise SystemExit("Token must not be empty.")

    # --- Store ---
    if args.method == "file":
        if args.env_file_path:
            env_path = Path(args.env_file_path).resolve()
        else:
            repo_root = config_path.parent.parent
            env_path = repo_root / ".env"
        _write_env_file(env_path, var_name, token, args.force)
    else:
        _set_env_persistent(var_name, token, args.force)

    # --- Summary ---
    print()
    print(f"TokenEnvironmentVariable          : {var_name}")
    print(f"Method                            : {args.method}")


if __name__ == "__main__":
    main()
