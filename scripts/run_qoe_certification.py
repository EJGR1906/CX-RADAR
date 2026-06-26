#!/usr/bin/env python3
"""CX-Radar QoE Probe QA Certification.

Cross-platform Python port of run-qoe-certification.ps1.
Runs automated smoke tests and resilience checks on the QoE probe to certify
production readiness.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def run_process(args: List[str], timeout: float = 120, env: Optional[Dict[str, str]] = None) -> Tuple[int, str, str]:
    """Execute command as subprocess and return exit code, stdout, stderr."""
    str_args = [str(x) for x in args]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    try:
        proc = subprocess.run(
            str_args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=proc_env
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return -1, "", f"Timeout expired after {timeout}s: {e}"
    except Exception as e:
        return -1, "", f"Process execution failed: {e}"


def get_scenario_log_path(config_path: Path, config: Dict[str, Any], run_date: datetime.date) -> Path:
    """Resolve the log file path for a scenario catalog."""
    log_dir_raw = config.get("probeRun", {}).get("logDirectory", "logs")
    # In legacy script: Join-Path (config_path.parent) "..\log_dir_raw"
    log_dir = (config_path.parent / ".." / log_dir_raw).resolve()
    log_file_name = f"qoe-probe-{run_date.strftime('%Y-%m-%d')}.log"
    return log_dir / log_file_name


def convert_from_probe_log(lines: List[str]) -> Dict[str, Any]:
    """Parse log lines and return target results, summaries, and counts."""
    target_results = []
    summary = None
    warning_count = 0
    error_count = 0

    http_success_rx = re.compile(
        r'Target ([^/]+)/([^ ]+) completed with HTTP (\d+), curl exit (-?\d+), total ([\d\.,]+) ms'
    )
    speed_success_rx = re.compile(
        r'Target ([^/]+)/([^ ]+) completed with download ([\d\.,]+) Mbps.*latency ([\d\.,]+) ms'
    )
    speed_fail_rx = re.compile(
        r'Target ([^/]+)/([^ ]+) (?:completed with error_class|failed:)'
    )
    summary_rx = re.compile(
        r'QoE probe finished\. Success=(\d+), Failure=(\d+), Duration=([\d\.,]+) ms'
    )

    for line in lines:
        m_http = http_success_rx.search(line)
        if m_http:
            target_results.append({
                "service": m_http.group(1),
                "endpoint_name": m_http.group(2),
                "http_status": int(m_http.group(3)),
                "curl_exit_code": int(m_http.group(4)),
                "time_total_ms": float(m_http.group(5).replace(",", "."))
            })
            continue

        m_speed = speed_success_rx.search(line)
        if m_speed:
            target_results.append({
                "service": m_speed.group(1),
                "endpoint_name": m_speed.group(2),
                "http_status": 0,
                "curl_exit_code": 0,
                "time_total_ms": float(m_speed.group(4).replace(",", "."))
            })
            continue

        m_speed_fail = speed_fail_rx.search(line)
        if m_speed_fail:
            target_results.append({
                "service": m_speed_fail.group(1),
                "endpoint_name": m_speed_fail.group(2),
                "http_status": 0,
                "curl_exit_code": -1,
                "time_total_ms": 0.0
            })
            continue

        m_sum = summary_rx.search(line)
        if m_sum:
            summary = {
                "success_count": int(m_sum.group(1)),
                "failure_count": int(m_sum.group(2)),
                "run_duration_ms": float(m_sum.group(3).replace(",", "."))
            }
            continue

        if "[WARN]" in line:
            warning_count += 1
            continue

        if "[ERROR]" in line:
            error_count += 1

    return {
        "target_results": target_results,
        "summary": summary,
        "warning_count": warning_count,
        "error_count": error_count,
        "line_count": len(lines)
    }


def write_scenario_config(
    base_config: Dict[str, Any], scenario_root: Path, scenario_name: str,
    targets: List[Dict[str, Any]], probe_run_overrides: Dict[str, Any] = None,
    influx_overrides: Dict[str, Any] = None
) -> Tuple[Path, Dict[str, Any]]:
    """Create scenario-specific catalog directory and write config file."""
    scenario_dir = scenario_root / scenario_name
    scenario_dir.mkdir(parents=True, exist_ok=True)

    config = copy.deepcopy(base_config)
    config["probe"]["probeId"] = f"{base_config.get('probe', {}).get('probeId', 'unknown')}-qa-{scenario_name}"
    config["probeRun"]["startJitterSecondsMax"] = 0
    config["probeRun"]["targetDelayMilliseconds"] = 0
    config["probeRun"]["retryCount"] = 0
    config["probeRun"]["retryDelaySeconds"] = 0
    config["probeRun"]["logDirectory"] = f"logs/{scenario_name}"

    if probe_run_overrides:
        config["probeRun"].update(probe_run_overrides)
    if influx_overrides:
        config["influx"].update(influx_overrides)

    config["targets"] = targets

    config_path = scenario_dir / "probe-catalog.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path, config


def get_parsed_log_failure_count(parsed_log: Dict[str, Any]) -> int:
    sum_obj = parsed_log.get("summary")
    if not sum_obj:
        return -1
    return sum_obj.get("failure_count", -1)


def main() -> None:
    parser = argparse.ArgumentParser(description="CX-Radar QoE Probe QA Certification.")
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json (default: ../config/probe-catalog.json)"
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default="",
        help="Path to write the JSON certification report"
    )
    parser.add_argument(
        "--max-probe-runtime-seconds",
        type=int,
        default=120,
        help="Maximum runtime permitted for the smoke test (default: 120)"
    )
    parser.add_argument(
        "--run-resilience-checks",
        action="store_true",
        help="Run additional fault tolerance scenarios"
    )
    parser.add_argument(
        "--include-tls-scenario",
        action="store_true",
        help="Include expired TLS scenario in resilience checks"
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    # Determine base config
    if args.config_path:
        base_config_path = Path(args.config_path).resolve()
    else:
        base_config_path = (repo_root / "config" / "probe-catalog.json").resolve()

    if not base_config_path.is_file():
        print(f"Error: Base config not found at {base_config_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Starting CX-Radar QoE Probe QA Certification...")
    print(f"Base Configuration: {base_config_path}")

    # 1. Run environment validation script first
    print("\n[Step 1/4] Running Environment Validation...")
    validate_script = script_dir / "validate_qoe_probe.py"
    exit_code, val_stdout, val_stderr = run_process([sys.executable, str(validate_script), "--config-path", str(base_config_path)])
    print(val_stdout)
    if exit_code != 0:
        print(f"Environment validation failed (Exit: {exit_code}). Details:\n{val_stderr}", file=sys.stderr)
        sys.exit(1)

    # Load base config
    try:
        base_cfg = json.loads(base_config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    enabled_targets = [t for t in base_cfg.get("targets", []) if t.get("enabled")]

    # Smoke test only uses HTTP or burst-method targets to avoid external browser timeouts
    smoke_targets = [
        t for t in enabled_targets
        if t.get("type", "http").lower() == "http" or t.get("speedTestMethod", "").lower() == "burst"
    ]
    if not smoke_targets:
        smoke_targets = enabled_targets[:1] if enabled_targets else []

    # Setup temp scenario directory
    scenario_root = repo_root / "bin" / "tmp" / f"cx-radar-qa-{secrets.token_hex(8)}"
    scenario_root.mkdir(parents=True, exist_ok=True)

    scenarios_run = []
    overall_passed = True

    try:
        # 2. Smoke Test Scenario
        print("\n[Step 2/4] Executing Smoke Test Scenario...")
        smoke_config_path, smoke_cfg = write_scenario_config(
            base_cfg, scenario_root, "smoke", smoke_targets,
            probe_run_overrides={"connectTimeoutSeconds": 5, "maxTimeSeconds": 20}
        )

        probe_script = script_dir / "qoe_probe.py"
        smoke_start = time.time()
        smoke_exit, smoke_stdout, smoke_stderr = run_process([
            sys.executable, str(probe_script),
            "--skip-influx-write",
            "--config-path", str(smoke_config_path)
        ], timeout=args.max_probe_runtime_seconds)
        smoke_duration = time.time() - smoke_start

        # Read log file
        smoke_log_path = get_scenario_log_path(smoke_config_path, smoke_cfg, datetime.date.today())
        log_lines = []
        if smoke_log_path.is_file():
            log_lines = smoke_log_path.read_text(encoding="utf-8", errors="replace").splitlines()

        parsed_log = convert_from_probe_log(log_lines)
        latency_values = [r["time_total_ms"] for r in parsed_log["target_results"]]

        smoke_coverage_ok = (
            parsed_log["summary"] is not None and
            len(parsed_log["target_results"]) == len(smoke_targets) and
            parsed_log["line_count"] >= (len(smoke_targets) + 3)
        )

        smoke_passed = (
            smoke_exit == 0 and
            smoke_coverage_ok and
            len(latency_values) > 0 and
            any(l > 0 for l in latency_values)
        )

        failures = []
        if smoke_exit != 0:
            failures.append(f"Exit code non-zero ({smoke_exit})")
        if not smoke_coverage_ok:
            failures.append(f"Log coverage check failed. Configured targets: {len(smoke_targets)}, parsed target results: {len(parsed_log['target_results'])}")
        if not latency_values or not any(l > 0 for l in latency_values):
            failures.append("No positive latency measurements captured.")

        scenarios_run.append({
            "name": "smoke_test",
            "passed": smoke_passed,
            "exit_code": smoke_exit,
            "duration_seconds": round(smoke_duration, 2),
            "targets_configured": len(smoke_targets),
            "targets_logged": len(parsed_log["target_results"]),
            "failures": failures
        })
        print(f"Smoke Test: {'PASSED' if smoke_passed else 'FAILED'}")
        if not smoke_passed:
            print(f"  Reasons: {failures}")
            overall_passed = False

        # 3. Resilience Scenarios
        if args.run_resilience_checks:
            print("\n[Step 3/4] Running Resilience Fault Tolerance Scenarios...")

            # Scenario A: DNS Failure
            print("  Scenario A: DNS Failure...")
            dns_targets = [{
                "service": "qa",
                "endpointName": "dns-failure",
                "url": "https://cx-radar-probe-test.invalid/",
                "method": "GET",
                "expectedHttpCodes": [200],
                "enabled": True
            }]
            dns_config_path, dns_cfg = write_scenario_config(
                base_cfg, scenario_root, "dns-failure", dns_targets,
                probe_run_overrides={"connectTimeoutSeconds": 2, "maxTimeSeconds": 6}
            )
            dns_exit, _, _ = run_process([
                sys.executable, str(probe_script),
                "--skip-influx-write",
                "--config-path", str(dns_config_path)
            ])
            dns_log_path = get_scenario_log_path(dns_config_path, dns_cfg, datetime.date.today())
            dns_lines = []
            if dns_log_path.is_file():
                dns_lines = dns_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            parsed_dns_log = convert_from_probe_log(dns_lines)

            dns_passed = (dns_exit == 0 and get_parsed_log_failure_count(parsed_dns_log) >= 1)
            dns_failures = []
            if dns_exit != 0:
                dns_failures.append(f"Exit code non-zero ({dns_exit})")
            if get_parsed_log_failure_count(parsed_dns_log) < 1:
                dns_failures.append("No logged target failures found in log.")

            scenarios_run.append({
                "name": "dns_failure",
                "passed": dns_passed,
                "exit_code": dns_exit,
                "failures": dns_failures
            })
            print(f"  - DNS Failure handling: {'PASSED' if dns_passed else 'FAILED'}")
            if not dns_passed:
                overall_passed = False

            # Scenario B: Timeout Bound
            print("  Scenario B: Connect Timeout Bound...")
            timeout_targets = [{
                "service": "qa",
                "endpointName": "timeout",
                "url": "http://10.255.255.1/",
                "method": "GET",
                "expectedHttpCodes": [200],
                "enabled": True
            }]
            timeout_config_path, timeout_cfg = write_scenario_config(
                base_cfg, scenario_root, "timeout", timeout_targets,
                probe_run_overrides={"connectTimeoutSeconds": 1, "maxTimeSeconds": 4}
            )
            timeout_start = time.time()
            timeout_exit, _, _ = run_process([
                sys.executable, str(probe_script),
                "--skip-influx-write",
                "--config-path", str(timeout_config_path)
            ], timeout=15)
            timeout_duration_s = time.time() - timeout_start

            timeout_log_path = get_scenario_log_path(timeout_config_path, timeout_cfg, datetime.date.today())
            timeout_lines = []
            if timeout_log_path.is_file():
                timeout_lines = timeout_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            parsed_timeout_log = convert_from_probe_log(timeout_lines)

            timeout_passed = (timeout_exit == 0 and timeout_duration_s <= 15.0 and get_parsed_log_failure_count(parsed_timeout_log) >= 1)
            timeout_failures = []
            if timeout_exit != 0:
                timeout_failures.append(f"Exit code non-zero ({timeout_exit})")
            if timeout_duration_s > 15.0:
                timeout_failures.append(f"Probe exceeded timeout limit: took {round(timeout_duration_s, 2)}s")
            if get_parsed_log_failure_count(parsed_timeout_log) < 1:
                timeout_failures.append("No logged target failures found in log.")

            scenarios_run.append({
                "name": "timeout_bound",
                "passed": timeout_passed,
                "exit_code": timeout_exit,
                "duration_seconds": round(timeout_duration_s, 2),
                "failures": timeout_failures
            })
            print(f"  - Connect Timeout Bound handling: {'PASSED' if timeout_passed else 'FAILED'}")
            if not timeout_passed:
                overall_passed = False

            # Scenario C: InfluxDB Outage Resilience
            print("  Scenario C: InfluxDB Outage Handling...")
            outage_targets = [{
                "service": "qa",
                "endpointName": "influx-outage",
                "url": "https://www.google.com",
                "method": "GET",
                "expectedHttpCodes": [200, 301, 302],
                "enabled": True
            }]
            outage_config_path, outage_cfg = write_scenario_config(
                base_cfg, scenario_root, "influx-outage", outage_targets,
                probe_run_overrides={"connectTimeoutSeconds": 2, "maxTimeSeconds": 6},
                influx_overrides={"baseUrl": "http://127.0.0.1:1"}
            )
            token_env_name = base_cfg.get("influx", {}).get("tokenEnvVar", "INFLUXDB_TOKEN")
            outage_exit, _, _ = run_process([
                sys.executable, str(probe_script),
                "--config-path", str(outage_config_path)
            ], env={token_env_name: "dummy-token"})

            outage_log_path = get_scenario_log_path(outage_config_path, outage_cfg, datetime.date.today())
            outage_lines = []
            if outage_log_path.is_file():
                outage_lines = outage_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            parsed_outage_log = convert_from_probe_log(outage_lines)

            outage_passed = (outage_exit != 0 and parsed_outage_log["error_count"] >= 1)
            outage_failures = []
            if outage_exit == 0:
                outage_failures.append("Probe exited with code 0 despite write failure.")
            if parsed_outage_log["error_count"] < 1:
                outage_failures.append("No errors captured in logs.")

            scenarios_run.append({
                "name": "influx_outage",
                "passed": outage_passed,
                "exit_code": outage_exit,
                "failures": outage_failures
            })
            print(f"  - InfluxDB Outage handling: {'PASSED' if outage_passed else 'FAILED'}")
            if not outage_passed:
                overall_passed = False

            # Scenario D: TLS Failure
            if args.include_tls_scenario:
                print("  Scenario D: TLS Certificate Failure...")
                tls_targets = [{
                    "service": "qa",
                    "endpointName": "tls-failure",
                    "url": "https://expired.badssl.com/",
                    "method": "GET",
                    "expectedHttpCodes": [200],
                    "enabled": True
                }]
                tls_config_path, tls_cfg = write_scenario_config(
                    base_cfg, scenario_root, "tls-failure", tls_targets,
                    probe_run_overrides={"connectTimeoutSeconds": 5, "maxTimeSeconds": 15}
                )
                tls_exit, _, _ = run_process([
                    sys.executable, str(probe_script),
                    "--skip-influx-write",
                    "--config-path", str(tls_config_path)
                ])

                tls_log_path = get_scenario_log_path(tls_config_path, tls_cfg, datetime.date.today())
                tls_lines = []
                if tls_log_path.is_file():
                    tls_lines = tls_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                parsed_tls_log = convert_from_probe_log(tls_lines)

                tls_passed = (tls_exit == 0 and get_parsed_log_failure_count(parsed_tls_log) >= 1)
                tls_failures = []
                if tls_exit != 0:
                    tls_failures.append(f"Exit code non-zero ({tls_exit})")
                if get_parsed_log_failure_count(parsed_tls_log) < 1:
                    tls_failures.append("No logged target failures found in log.")

                scenarios_run.append({
                    "name": "tls_failure",
                    "passed": tls_passed,
                    "exit_code": tls_exit,
                    "failures": tls_failures
                })
                print(f"  - TLS Verification Failure handling: {'PASSED' if tls_passed else 'FAILED'}")
                if not tls_passed:
                    overall_passed = False
        else:
            print("\n[Step 3/4] Resilience Fault Tolerance checks skipped")

        # 4. Report Results
        print("\n[Step 4/4] Writing Certification Report...")
        report = {
            "timestamp_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "os": platform.system(),
            "os_release": platform.release(),
            "python_version": sys.version,
            "overall_passed": overall_passed,
            "scenarios": scenarios_run
        }

        report_json = json.dumps(report, indent=2)
        print("\n" + "=" * 60)
        print(f"QA CERTIFICATION RESULTS: {'PASSED' if overall_passed else 'FAILED'}")
        print("=" * 60)
        print(report_json)

        if args.output_path:
            out_file = Path(args.output_path).resolve()
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(report_json, encoding="utf-8")
            print(f"\nReport written to: {out_file}")

    finally:
        if scenario_root.exists():
            try:
                shutil.rmtree(scenario_root)
            except Exception:
                pass


if __name__ == "__main__":
    main()
