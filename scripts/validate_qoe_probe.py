#!/usr/bin/env python3
"""Validate QoE probe environment.

Cross-platform Python port of validate-qoe-probe.ps1.
Checks configuration, tool availability, and token readiness then prints
an ordered key=value report identical in structure to the PowerShell version.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qoe_probe import is_windows, resolve_from_base, exe_name, read_env_file_var


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _optional_str(source: Optional[Dict[str, Any]], key: str, default: str = "") -> str:
    """Return a non-blank string value from *source* or *default*."""
    if source is None:
        return default
    val = source.get(key)
    if val is None or str(val).strip() == "":
        return default
    return str(val)


def _get_target_type(target: Dict[str, Any]) -> str:
    return _optional_str(target, "type", "http").lower()


def _portable_tool_prop(
    portable_tools_cfg: Optional[Dict[str, Any]], key: str, default: str
) -> str:
    if portable_tools_cfg is None:
        return default
    val = portable_tools_cfg.get(key)
    if val is None or str(val).strip() == "":
        return default
    return str(val)


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def _test_curl(repo_root: Path) -> bool:
    """Check for curl in bin/, system path, or PATH."""
    portable = repo_root / "bin" / exe_name("curl")
    if portable.is_file():
        return True

    if is_windows():
        sys_root = os.environ.get("SystemRoot", r"C:\Windows")
        system_curl = Path(sys_root) / "System32" / "curl.exe"
        if system_curl.is_file():
            return True
        return shutil.which("curl.exe") is not None

    # Linux / macOS — just check PATH
    return shutil.which("curl") is not None


def _get_portable_tools(
    probe_run: Dict[str, Any], repo_root: Path
) -> Dict[str, Path]:
    """Return resolved paths for each portable tool."""
    pt_cfg = probe_run.get("portableTools")

    node_child = _portable_tool_prop(
        pt_cfg, "nodeExe",
        str(Path("bin", "node", exe_name("node"))),
    )
    fast_cli_child = _portable_tool_prop(
        pt_cfg, "fastCliScript",
        str(Path("bin", "fast-cli", "node_modules", "fast-cli", "distribution", "cli.js")),
    )
    yt_dlp_child = _portable_tool_prop(
        pt_cfg, "ytDlpExe",
        str(Path("bin", exe_name("yt-dlp"))),
    )

    if is_windows():
        nq_default = str(Path(os.environ.get("SystemRoot", r"C:\Windows"),
                              "System32", "networkquality.exe"))
    else:
        nq_default = "networkquality"

    nq_child = _portable_tool_prop(pt_cfg, "networkQualityExe", nq_default)

    fast_cli_path = resolve_from_base(repo_root, fast_cli_child)
    if not fast_cli_path.is_file():
        alt_path = fast_cli_path.parent.parent / "cli.js"
        if alt_path.is_file():
            fast_cli_path = alt_path

    return {
        "node_exe": resolve_from_base(repo_root, node_child),
        "fast_cli_script": fast_cli_path,
        "yt_dlp_exe": resolve_from_base(repo_root, yt_dlp_child),
        "network_quality_exe": resolve_from_base(repo_root, nq_child),
        "repo_root": repo_root,
    }


def _test_configured_path(repo_root: Path, candidate: Optional[str]) -> bool:
    if not candidate or candidate.strip() == "":
        return False
    p = Path(os.path.expandvars(candidate))
    if p.is_absolute():
        return p.is_file()
    return (repo_root / p).resolve().is_file()


def _test_nq_for_target(
    target: Dict[str, Any], tools: Dict[str, Path]
) -> bool:
    cmd_path = _optional_str(target, "commandPath", "")
    if cmd_path:
        return _test_configured_path(tools["repo_root"], cmd_path)
    return tools["network_quality_exe"].is_file() or shutil.which("networkquality") is not None


def _test_speed_fallback_ready(target: Dict[str, Any]) -> bool:
    download_url = _optional_str(target, "downloadUrl",
                                 _optional_str(target, "url"))
    return download_url != ""


def _get_upload_method(target: Dict[str, Any], probe_run: Dict[str, Any]) -> str:
    m = _optional_str(target, "uploadMeasurementMethod")
    if m:
        return m.lower()
    return _optional_str(probe_run, "defaultUploadMeasurementMethod", "none").lower()


def _test_upload_url_ready(target: Dict[str, Any]) -> bool:
    return _optional_str(target, "uploadUrl") != ""


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def _get_config_issues(config: Dict[str, Any]) -> List[str]:
    issues: List[str] = []

    probe = config.get("probe", {})
    influx = config.get("influx", {})
    targets = config.get("targets", [])
    probe_run = config.get("probeRun", {})

    if not _optional_str(probe, "probeId"):
        issues.append("probe.probeId is required.")
    if not _optional_str(influx, "baseUrl"):
        issues.append("influx.baseUrl is required.")
    if not _optional_str(influx, "bucket"):
        issues.append("influx.bucket is required.")
    if not _optional_str(influx, "tokenEnvVar"):
        issues.append("influx.tokenEnvVar is required.")
    if not targets:
        issues.append("At least one enabled target is required.")

    for t in targets:
        if not t.get("enabled"):
            continue

        if not _optional_str(t, "service"):
            issues.append("Enabled target is missing service.")
        if not _optional_str(t, "endpointName"):
            issues.append(
                f"Target '{_optional_str(t, 'service')}' is enabled but has no endpointName."
            )

        ttype = _get_target_type(t)
        svc_ep = f"{_optional_str(t, 'service')}/{_optional_str(t, 'endpointName')}"

        if ttype == "http":
            if not _optional_str(t, "url"):
                issues.append(
                    f"HTTP target '{svc_ep}' is enabled but has no URL."
                )

        elif ttype == "speedtest":
            stm = _optional_str(t, "speedTestMethod").lower()
            if not stm:
                issues.append(
                    f"Speed-test target '{svc_ep}' is missing speedTestMethod."
                )
            elif stm == "fast-cli":
                pass
            elif stm == "yt-dlp":
                video_url = _optional_str(t, "videoUrl", _optional_str(t, "url"))
                if not video_url:
                    issues.append(
                        f"yt-dlp target '{svc_ep}' requires videoUrl or url."
                    )
            elif stm == "networkquality":
                if (not _test_speed_fallback_ready(t)
                        and not _optional_str(t, "commandPath")):
                    issues.append(
                        f"networkquality target '{svc_ep}' requires downloadUrl/url for burst fallback or an explicit commandPath."
                    )
            elif stm == "burst":
                if not _test_speed_fallback_ready(t):
                    issues.append(
                        f"Burst target '{svc_ep}' requires downloadUrl or url."
                    )
            else:
                issues.append(
                    f"Target '{svc_ep}' uses unsupported speedTestMethod '{stm}'."
                )

            # upload measurement validation
            um = _get_upload_method(t, probe_run)
            if um in ("none", "networkquality", "curl-upload"):
                pass
            elif um == "upload-url":
                if not _test_upload_url_ready(t):
                    issues.append(
                        f"Target '{svc_ep}' requires uploadUrl when uploadMeasurementMethod is 'upload-url'."
                    )
            else:
                issues.append(
                    f"Target '{svc_ep}' uses unsupported uploadMeasurementMethod '{um}'."
                )

        else:
            issues.append(
                f"Target '{svc_ep}' uses unsupported type '{ttype}'."
            )

    return issues


# ---------------------------------------------------------------------------
# InfluxDB token detection
# ---------------------------------------------------------------------------

def _get_influx_token_status(
    influx_cfg: Dict[str, Any], config_dir: Path
) -> Dict[str, Any]:
    """Check for an available InfluxDB token (env-var or .env file)."""
    credential_file_path = ""
    credential_file_exists = False

    cred_path_raw = _optional_str(influx_cfg, "credentialFilePath")
    if cred_path_raw:
        credential_file_path = str(resolve_from_base(config_dir, cred_path_raw))
        credential_file_exists = Path(credential_file_path).is_file()
        # Note: Python cannot read PowerShell CliXml credential files, so we
        # skip the credential-file-based token source on non-Windows or when
        # running from Python.  We still report whether the file exists.

    token_var = str(influx_cfg.get("tokenEnvVar", ""))
    token_value = ""

    # Check process-level env first
    token_value = os.environ.get(token_var, "")

    # Also check .env files alongside the config
    if not token_value:
        for candidate in (config_dir.parent / ".env", config_dir / ".env"):
            if candidate.is_file():
                token_value = read_env_file_var(candidate, token_var)
                if token_value:
                    break

    available = bool(token_value.strip())
    source = "EnvironmentVariable" if available else "None"

    return {
        "Available": available,
        "Source": source,
        "CredentialFilePath": credential_file_path,
        "CredentialFileExists": credential_file_exists,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _build_report(config_path: Path) -> Dict[str, Any]:
    # --- Load and validate config ---
    config_text = config_path.read_text(encoding="utf-8")
    config: Dict[str, Any] = json.loads(config_text)
    config_dir = config_path.parent

    issues = _get_config_issues(config)
    if issues:
        raise SystemExit("Configuration errors:\n" + "\n".join(issues))

    # --- Derived paths ---
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    probe_run = config.get("probeRun", {})
    tools = _get_portable_tools(probe_run, repo_root)

    # --- Classify enabled targets ---
    all_targets: List[Dict[str, Any]] = config.get("targets", [])
    enabled = [t for t in all_targets if t.get("enabled")]
    enabled_http = [t for t in enabled if _get_target_type(t) == "http"]
    enabled_speed = [t for t in enabled if _get_target_type(t) == "speedtest"]

    fast_cli_targets = [
        t for t in enabled_speed
        if _optional_str(t, "speedTestMethod").lower() == "fast-cli"
    ]
    yt_dlp_targets = [
        t for t in enabled_speed
        if _optional_str(t, "speedTestMethod").lower() == "yt-dlp"
    ]
    nq_targets = [
        t for t in enabled_speed
        if _optional_str(t, "speedTestMethod").lower() == "networkquality"
    ]
    burst_targets = [
        t for t in enabled_speed
        if _optional_str(t, "speedTestMethod").lower() == "burst"
    ]

    upload_nq_targets = [
        t for t in enabled_speed
        if _get_upload_method(t, probe_run) == "networkquality"
    ]
    upload_url_targets = [
        t for t in enabled_speed
        if _get_upload_method(t, probe_run) == "upload-url"
    ]
    upload_curl_targets = [
        t for t in enabled_speed
        if _get_upload_method(t, probe_run) == "curl-upload"
    ]

    # --- Tool availability (skip check when no targets need the tool) ---
    curl_available = (
        _test_curl(repo_root) if enabled_http else True
    )
    portable_node_available = (
        tools["node_exe"].is_file() if fast_cli_targets else True
    )
    fast_cli_available = (
        tools["fast_cli_script"].is_file() if fast_cli_targets else True
    )
    yt_dlp_available = (
        tools["yt_dlp_exe"].is_file() if yt_dlp_targets else True
    )

    all_nq_targets_list = list({id(t): t for t in nq_targets + upload_nq_targets}.values())

    nq_command_available = (
        all(
            _test_nq_for_target(t, tools) for t in all_nq_targets_list
        )
        if all_nq_targets_list
        else True
    )
    nq_fallback_ready = (
        all(_test_speed_fallback_ready(t) for t in nq_targets)
        if nq_targets
        else True
    )
    burst_targets_ready = (
        all(_test_speed_fallback_ready(t) for t in burst_targets)
        if burst_targets
        else True
    )
    upload_url_ready = (
        all(_test_upload_url_ready(t) for t in upload_url_targets)
        if upload_url_targets
        else True
    )
    curl_upload_ready = True

    upload_nq_ready = nq_command_available if upload_nq_targets else True
    upload_targets_ready = upload_nq_ready and upload_url_ready and curl_upload_ready

    isp_configured = (
        bool(_optional_str(config.get("probe", {}), "isp"))
        if enabled_speed
        else True
    )

    speed_ready = (
        portable_node_available
        and fast_cli_available
        and yt_dlp_available
        and (nq_command_available or nq_fallback_ready)
        and burst_targets_ready
        and upload_url_ready
        and curl_upload_ready
    )

    # --- InfluxDB token ---
    token_status = _get_influx_token_status(
        config.get("influx", {}), config_dir
    )

    # --- Build ordered report ---
    report: Dict[str, Any] = {}
    report["ConfigFile"] = "OK"
    report["CurlAvailable"] = curl_available
    report["PortableNodeAvailable"] = portable_node_available
    report["FastCliAvailable"] = fast_cli_available
    report["YtDlpAvailable"] = yt_dlp_available
    report["NetworkQualityCommandAvailable"] = nq_command_available
    report["NetworkQualityFallbackReady"] = nq_fallback_ready
    report["BurstTargetsReady"] = burst_targets_ready
    report["UploadUrlTargetsReady"] = upload_url_ready
    report["CurlUploadTargetsReady"] = curl_upload_ready
    report["UploadMeasurementTargetsReady"] = upload_targets_ready
    report["ProbeIspConfigured"] = isp_configured
    report["SpeedTestTargetsReady"] = speed_ready
    report["InfluxTokenAvailable"] = token_status["Available"]
    report["InfluxTokenSource"] = token_status["Source"]
    report["InfluxCredentialFilePath"] = token_status["CredentialFilePath"]
    report["InfluxCredentialFileExists"] = token_status["CredentialFileExists"]
    report["EnabledTargets"] = len(enabled)
    report["EnabledHttpTargets"] = len(enabled_http)
    report["EnabledSpeedTestTargets"] = len(enabled_speed)

    return report


def _format_value(v: Any) -> str:
    """Format a Python value to match PowerShell's Format-List output."""
    if isinstance(v, bool):
        return str(v)
    return str(v)


def _print_report(report: Dict[str, Any]) -> None:
    max_key_len = max(len(k) for k in report)
    for key, value in report.items():
        print(f"{key:<{max_key_len}} : {_format_value(value)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate QoE probe environment (cross-platform)."
    )
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json (default: ../config/probe-catalog.json relative to this script)",
    )
    args = parser.parse_args()

    if args.config_path:
        config_path = Path(args.config_path).resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        config_path = (script_dir / ".." / "config" / "probe-catalog.json").resolve()

    if not config_path.is_file():
        raise SystemExit(f"Config file not found: {config_path}")

    report = _build_report(config_path)
    _print_report(report)


if __name__ == "__main__":
    main()
