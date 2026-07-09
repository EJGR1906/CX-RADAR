#!/usr/bin/env python3
"""CX-Radar QoE Probe.

Cross-platform Python implementation of the QoE main probe script.
Monitors HTTP targets (qoe_http_check) and speedtest targets (qoe_real_metrics),
emitting probe summary metrics (qoe_probe_run) to InfluxDB Cloud.

Requirements: Python >= 3.8, stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import platform
import random
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


# ---------------------------------------------------------------------------
# Global Constants & Logging Setup
# ---------------------------------------------------------------------------
PROBE_VERSION = "0.2.0"

class InsecureRequestWarning(Warning):
    """Warning for unverified TLS requests."""
    pass
log_path_global: Optional[Path] = None

def log_message(message: str, level: str = "INFO") -> None:
    """Write an ISO 8601 timestamped log line to file and stdout."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        try:
            sys.stdout.write(line.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii') + '\n')
            sys.stdout.flush()
        except Exception:
            pass
    if log_path_global:
        try:
            with open(log_path_global, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Platform Helpers
# ---------------------------------------------------------------------------
def is_windows() -> bool:
    return platform.system() == "Windows"


def exe_name(name: str) -> str:
    """Append .exe extension on Windows if not already present."""
    if is_windows() and not name.endswith(".exe"):
        return name + ".exe"
    return name


def resolve_from_base(base: Path, child: str) -> Path:
    """Expand environment variables in path and resolve relative to base."""
    expanded = os.path.expandvars(child)
    p = Path(expanded)
    if p.is_absolute():
        return p.resolve()
    return (base / p).resolve()


# ---------------------------------------------------------------------------
# Configuration Helpers
# ---------------------------------------------------------------------------
def get_optional_str(source: Optional[Dict[str, Any]], key: str, default: str = "") -> str:
    if source is None:
        return default
    val = source.get(key)
    if val is None or str(val).strip() == "":
        return default
    return str(val)


def get_optional_int(source: Optional[Dict[str, Any]], key: str, default: int = 0) -> int:
    if source is None:
        return default
    val = source.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def get_target_type(target: Dict[str, Any]) -> str:
    return get_optional_str(target, "type", "http").lower()


def get_target_host(target: Dict[str, Any]) -> str:
    configured = get_optional_str(target, "host")
    if configured:
        return configured

    for prop in ("downloadUrl", "videoUrl", "url"):
        candidate = get_optional_str(target, prop)
        if candidate:
            try:
                parsed = urllib.parse.urlparse(candidate)
                if parsed.hostname:
                    return parsed.hostname
            except Exception:
                pass
    return ""


def get_target_isp(target: Dict[str, Any], probe_cfg: Dict[str, Any]) -> str:
    t_isp = get_optional_str(target, "isp")
    if t_isp:
        return t_isp
    p_isp = get_optional_str(probe_cfg, "isp")
    if p_isp:
        return p_isp
    return "unknown"


def get_speedtest_timeout(target: Dict[str, Any], probe_run: Dict[str, Any], default: int = 180) -> int:
    timeout = get_optional_int(target, "timeoutSeconds")
    if timeout > 0:
        return timeout
    timeout = get_optional_int(probe_run, "speedTestTimeoutSeconds")
    if timeout > 0:
        return timeout
    return default


def get_mbps_from_bytes_duration(bytes_count: float, duration_ms: float) -> float:
    if duration_ms <= 0 or bytes_count <= 0:
        return 0.0
    # Mbps = (bytes * 8 / 1,000,000) / (duration_ms / 1,000)
    # Mbps = (bytes * 8) / (duration_ms * 1000)
    return round((bytes_count * 8.0) / (duration_ms * 1000.0), 2)


# ---------------------------------------------------------------------------
# InfluxDB Line Protocol Formatting
# ---------------------------------------------------------------------------
def escape_tag(value: str) -> str:
    """Escape backslash, space, comma, and equals sign for InfluxDB tags/keys."""
    val = str(value)
    val = val.replace('\\', '\\\\')
    val = val.replace(' ', '\\ ')
    val = val.replace(',', '\\,')
    val = val.replace('=', '\\=')
    return val


def escape_field_string(value: str) -> str:
    """Escape backslash and double quotes for string field values."""
    val = str(value)
    val = val.replace('\\', '\\\\')
    val = val.replace('"', '\\"')
    return val


# ⚡ Bolt: Extracted to module-level frozenset to prevent O(N) allocation on every metric format call
# Set of fields that must always be represented as floats in Line Protocol (to avoid schema conflicts)
_INFLUX_FLOAT_FIELDS = frozenset({
    "download_speed", "upload_speed", "latency", "jitter", "rpm_responsiveness",
    "time_namelookup_ms", "time_connect_ms", "time_appconnect_ms", "time_starttransfer_ms", "time_total_ms",
    "size_download_bytes", "run_duration_ms", "latency_ms", "jitter_ms", "download_mbps", "upload_mbps",
    "packet_loss_percentage", "gateway_latency_ms", "bufferbloat_download_ms", "bufferbloat_upload_ms"
})

def build_influx_line(measurement: str, tags: Dict[str, Any], fields: Dict[str, Any], timestamp_ms: int) -> str:
    """Construct an InfluxDB Line Protocol string from inputs."""
    tag_pairs = []
    for k in sorted(tags.keys()):
        v = tags[k]
        if v is None or str(v).strip() == "":
            continue
        tag_pairs.append(f"{escape_tag(k)}={escape_tag(str(v))}")

    field_pairs = []
    for k in sorted(fields.keys()):
        v = fields[k]
        if v is None:
            continue

        if k in _INFLUX_FLOAT_FIELDS:
            try:
                v = float(v)
            except (ValueError, TypeError):
                pass

        if isinstance(v, bool):
            encoded = "true" if v else "false"
        elif isinstance(v, float):
            encoded = f"{v}"
        elif isinstance(v, int):
            encoded = f"{v}i"
        else:
            encoded = f'"{escape_field_string(str(v))}"'

        field_pairs.append(f"{escape_tag(k)}={encoded}")

    if not field_pairs:
        raise ValueError("Influx line requires at least one field.")

    meas_part = escape_tag(measurement)
    tags_part = "," + ",".join(tag_pairs) if tag_pairs else ""
    fields_part = ",".join(field_pairs)

    return f"{meas_part}{tags_part} {fields_part} {timestamp_ms}"


# ---------------------------------------------------------------------------
# InfluxDB Token Management
# ---------------------------------------------------------------------------
def read_env_file_var(env_path: Path, var_name: str) -> str:
    """Read a specific key-value pair from a .env file."""
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key == var_name:
                return value
    except Exception:
        pass
    return ""


def get_influx_token(influx_cfg: Dict[str, Any], config_dir: Path) -> str:
    """Resolve the InfluxDB authentication token from env or .env file."""
    token_name = get_optional_str(influx_cfg, "tokenEnvVar", "INFLUXDB_TOKEN")

    # 1. Process Environment
    token = os.environ.get(token_name, "")
    if token:
        log_message(f"Using InfluxDB token from environment variable '{token_name}'.", "INFO")
        return token

    # 2. Local .env files
    # Check parent folder (repo root) or config dir
    for candidate in (config_dir.parent / ".env", config_dir / ".env"):
        if candidate.is_file():
            token = read_env_file_var(candidate, token_name)
            if token:
                log_message(f"Using InfluxDB token from .env file '{candidate}'.", "INFO")
                return token

    raise ValueError(f"InfluxDB token was not found in environment variable '{token_name}' or any .env file.")


# ---------------------------------------------------------------------------
# Garbage Collection
# ---------------------------------------------------------------------------

LOG_PATTERN_PROBE = re.compile(r'^qoe-probe-\d{4}-\d{2}-\d{2}\.log$')
LOG_PATTERN_SPEED = re.compile(r'^qoe-speed-test-\d{4}-\d{2}-\d{2}\.log$')

def run_garbage_collection(repo_root: Path, temp_dir: Path, log_retention_days: int = 7, min_age_minutes: int = 20) -> int:
    """Remove stale log files and temporary artifacts."""
    removed_count = 0
    now = time.time()

    # 1. Temporary Directory GC
    if temp_dir.exists() and temp_dir.is_dir():
        cutoff_temp = now - (min_age_minutes * 60)
        patterns = ['burst-*', 'yt-dlp-*', 'fast-cli-*', 'puppeteer_dev_chrome_profile-*', '*.tmp', '*.bak']
        for pattern in patterns:
            for item in temp_dir.glob(pattern):
                try:
                    mtime = item.stat().st_mtime
                    if mtime <= cutoff_temp:
                        if item.is_file() or item.is_symlink():
                            item.unlink()
                            removed_count += 1
                        elif item.is_dir():
                            shutil.rmtree(item)
                            removed_count += 1
                except Exception:
                    pass

    # 2. Logs Directory GC
    logs_dir = repo_root / "logs"
    if logs_dir.exists() and logs_dir.is_dir():
        cutoff_logs = now - (log_retention_days * 24 * 3600)
        for item in logs_dir.glob("*.log"):
            if LOG_PATTERN_PROBE.match(item.name) or LOG_PATTERN_SPEED.match(item.name):
                try:
                    mtime = item.stat().st_mtime
                    if mtime <= cutoff_logs:
                        item.unlink()
                        removed_count += 1
                except Exception:
                    pass

    return removed_count


# ---------------------------------------------------------------------------
# External Process Invoker
# ---------------------------------------------------------------------------
def run_external_process(
    args: List[str], timeout: float, cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None
) -> Tuple[int, str, str, float, bool]:
    """Execute an external command and return exit_code, stdout, stderr, duration_ms, and timed_out."""
    start_time = time.perf_counter()
    timed_out = False
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    str_args = [str(a) for a in args]

    # Hide console window on Windows if running in background
    startupinfo = None
    if is_windows():
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        proc = subprocess.Popen(
            str_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=proc_env,
            text=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            exit_code = -1
            timed_out = True

    except Exception as e:
        exit_code = -1
        stdout = ""
        stderr = str(e)

    duration_ms = (time.perf_counter() - start_time) * 1000
    return exit_code, stdout, stderr, duration_ms, timed_out


# ---------------------------------------------------------------------------
# Ping Stats implementation
# ---------------------------------------------------------------------------
# Regex matching English and Spanish time: time=12ms, tiempo=12ms, time<1ms, tiempo<1ms
PING_TIME_REGEX = re.compile(r'(?:time|tiempo)\s*[=<]\s*(\d+(?:\.\d+)?)\s*ms', re.IGNORECASE)

IPV4_REGEX = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')

NQ_DOWNLOAD_RX1 = re.compile(r'Download(?:\s+capacity)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', re.I)
NQ_DOWNLOAD_RX2 = re.compile(r'Down(?:link)?(?:\s+bandwidth)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', re.I)

NQ_UPLOAD_RX1 = re.compile(r'Upload(?:\s+capacity)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', re.I)
NQ_UPLOAD_RX2 = re.compile(r'Up(?:link)?(?:\s+bandwidth)?\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z/]+)', re.I)

NQ_LATENCY_RX1 = re.compile(r'(?:Idle\s+)?Latency\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*ms', re.I)
NQ_LATENCY_RX2 = re.compile(r'Round\s*trip\s*latency\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*ms', re.I)

NQ_RPM_RX1 = re.compile(r'Responsiveness\s*:\s*.*?\(([0-9]+(?:\.[0-9]+)?)\s*RPM\)', re.I)
NQ_RPM_RX2 = re.compile(r'RPM(?:\s+Responsiveness)?\s*:\s*([0-9]+(?:\.[0-9]+)?)', re.I)

def get_ping_burst_stats(host: str, count: int = 10, timeout_ms: int = 1000) -> Dict[str, Any]:
    """Compute RTT latency and Mean Absolute Successive Jitter using ping."""
    result = {
        "Host": host,
        "LatencyMs": 0.0,
        "JitterMs": 0.0,
        "SuccessfulReplies": 0,
        "Samples": [],
        "PacketLossPercentage": 0.0
    }

    if not host or host.strip() == "":
        return result

    # Check platform and construct ping arguments
    if is_windows():
        # -n count, -w timeout (ms)
        args = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    elif platform.system() == "Darwin":
        # macOS: -c count, -W wait time in ms
        args = ["ping", "-c", str(count), "-W", str(timeout_ms), host]
    else:
        # Linux: -c count, -W wait time in seconds (minimum 1s)
        args = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), host]

    timeout_seconds = max(10, int(count * (timeout_ms / 1000.0) + 5))
    exit_code, stdout, _, _, _ = run_external_process(args, timeout_seconds)

    samples = []

    lines = stdout.splitlines()
    for line in lines:
        m = PING_TIME_REGEX.search(line)
        if m:
            samples.append(float(m.group(1)))

    if not samples:
        result["PacketLossPercentage"] = 100.0
        return result

    latency_ms = round(sum(samples) / len(samples), 2)
    jitter_ms = 0.0
    if len(samples) > 1:
        delta_sum = sum(abs(samples[i] - samples[i-1]) for i in range(1, len(samples)))
        jitter_ms = round(delta_sum / (len(samples) - 1), 2)

    loss_pct = round(((count - len(samples)) / count) * 100.0, 2) if count > 0 else 0.0

    return {
        "Host": host,
        "LatencyMs": latency_ms,
        "JitterMs": jitter_ms,
        "SuccessfulReplies": len(samples),
        "Samples": samples,
        "PacketLossPercentage": loss_pct
    }


def get_default_gateway() -> str:
    """Retrieve default gateway IP address in a cross-platform way using standard tools."""
    try:
        # Hide command window on Windows
        startupinfo = None
        if is_windows():
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        if is_windows():
            # Try powershell first
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue).NextHop"]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo)
            stdout, _ = proc.communicate(timeout=5)
            if proc.returncode == 0:
                for line in stdout.splitlines():
                    ip = line.strip()
                    if IPV4_REGEX.match(ip):
                        return ip
            
            # Fallback to route print
            proc2 = subprocess.Popen(["route", "print", "0.0.0.0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, startupinfo=startupinfo)
            stdout2, _ = proc2.communicate(timeout=5)
            for line in stdout2.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] == "0.0.0.0":
                    gw = parts[2]
                    if IPV4_REGEX.match(gw):
                        return gw
        elif platform.system() == "Darwin":
            proc = subprocess.Popen(["route", "-n", "get", "default"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, _ = proc.communicate(timeout=5)
            for line in stdout.splitlines():
                if "gateway:" in line.lower():
                    gw = line.split(":")[-1].strip()
                    if IPV4_REGEX.match(gw) or ":" in gw:
                        return gw
        else:
            # Linux: read /proc/net/route or parse ip route
            if os.path.exists("/proc/net/route"):
                with open("/proc/net/route", "r") as f:
                    for line in f.read().splitlines()[1:]:
                        parts = line.split()
                        if len(parts) >= 3 and parts[1] == "00000000":
                            gw_hex = parts[2]
                            if len(gw_hex) == 8:
                                octets = [int(gw_hex[i:i+2], 16) for i in range(6, -1, -2)]
                                return ".".join(map(str, octets))
            proc = subprocess.Popen(["ip", "route", "show", "default"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, _ = proc.communicate(timeout=5)
            for line in stdout.splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "default" and parts[1] == "via":
                    return parts[2]
    except Exception:
        pass
    return ""


class ConcurrentPingCollector:
    """Run a periodic ping in a background thread to measure loaded latency during throughput tests."""
    def __init__(self, host: str, interval_seconds: float = 0.5):
        self.host = host
        self.interval = interval_seconds
        self.latencies = []
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.stop_event.clear()
        self.latencies = []
        self.thread = threading.Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self) -> List[float]:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        return self.latencies

    def _run(self):
        if not self.host or self.host.strip() == "":
            return
        while not self.stop_event.is_set():
            start_time = time.perf_counter()
            stats = get_ping_burst_stats(self.host, count=1, timeout_ms=800)
            if stats["SuccessfulReplies"] > 0 and stats["Samples"]:
                self.latencies.extend(stats["Samples"])
            
            elapsed = time.perf_counter() - start_time
            sleep_time = max(0.01, self.interval - elapsed)
            if self.stop_event.wait(sleep_time):
                break


def get_approximate_rpm(latency_ms: float) -> float:
    if latency_ms <= 0:
        return 0.0
    return round(60000.0 / latency_ms, 2)


# ---------------------------------------------------------------------------
# HTTP Probing: curl Execution
# ---------------------------------------------------------------------------
def run_curl_http_probe(curl_path: Path, target: Dict[str, Any], probe_run: Dict[str, Any]) -> Dict[str, Any]:
    """Perform HTTP probe using curl, capturing write-out stats."""
    write_out_fields = [
        "http_code=%{response_code}",
        "remote_ip=%{remote_ip}",
        "http_version=%{http_version}",
        "num_redirects=%{num_redirects}",
        "time_namelookup=%{time_namelookup}",
        "time_connect=%{time_connect}",
        "time_appconnect=%{time_appconnect}",
        "time_starttransfer=%{time_starttransfer}",
        "time_total=%{time_total}",
        "size_download=%{size_download}",
        "errormsg=%{errormsg}",
        "url_effective=%{url_effective}"
    ]
    write_out_str = "\n".join(write_out_fields)
    null_device = "NUL" if is_windows() else "/dev/null"

    args = [
        str(curl_path),
        "-q",
        "--silent",
        "--show-error",
        "--no-progress-meter",
        "--globoff",
        "--output", null_device
    ]

    if probe_run.get("followRedirects", True):
        args.extend(["--location", "--max-redirs", "5", "--proto-redir", "=http,https"])

    if not probe_run.get("verifyTls", True):
        args.append("--insecure")

    args.extend([
        "--proto", "=http,https",
        "--connect-timeout", str(probe_run.get("connectTimeoutSeconds", 10)),
        "--max-time", str(probe_run.get("maxTimeSeconds", 120)),
        "--retry", str(probe_run.get("retryCount", 1)),
        "--retry-delay", str(probe_run.get("retryDelaySeconds", 2)),
        "--request", target.get("method", "GET"),
        "--user-agent", probe_run.get("userAgent", ""),
        "--write-out", write_out_str,
        target["url"]
    ])

    exit_code, stdout, stderr, _, timed_out = run_external_process(
        args, float(probe_run.get("maxTimeSeconds", 120)) + 10
    )

    parsed = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()

    http_code = int(parsed.get("http_code", "0") or "0")
    expected_codes = target.get("expectedHttpCodes", [200])
    is_expected_http_code = (http_code in expected_codes) if http_code > 0 else False

    def to_ms(sec_str: str) -> float:
        try:
            return round(float(sec_str or "0") * 1000, 2)
        except ValueError:
            return 0.0

    err_msg = parsed.get("errormsg", "")
    if exit_code != 0 and not err_msg:
        err_msg = stderr.strip() if stderr else "Unknown curl error"
    if timed_out:
        err_msg = "curl command timed out."
        exit_code = 28

    err_class = ""
    if exit_code == 0 and not is_expected_http_code:
        err_class = "unexpected_http_status"
    elif exit_code == 6:
        err_class = "dns_resolution"
    elif exit_code == 7:
        err_class = "connect"
    elif exit_code == 22:
        err_class = "http_error"
    elif exit_code == 28:
        err_class = "timeout"
    elif exit_code in (35, 60):
        err_class = "tls"
    elif exit_code != 0:
        err_class = "curl_error"

    return {
        "ExitCode": exit_code,
        "HttpCode": http_code,
        "RemoteIp": parsed.get("remote_ip", ""),
        "HttpVersion": parsed.get("http_version", ""),
        "NumRedirects": int(parsed.get("num_redirects", "0") or "0"),
        "TimeNameLookupMs": to_ms(parsed.get("time_namelookup", "0")),
        "TimeConnectMs": to_ms(parsed.get("time_connect", "0")),
        "TimeAppConnectMs": to_ms(parsed.get("time_appconnect", "0")),
        "TimeStartTransferMs": to_ms(parsed.get("time_starttransfer", "0")),
        "TimeTotalMs": to_ms(parsed.get("time_total", "0")),
        "SizeDownloadBytes": float(parsed.get("size_download", "0") or "0"),
        "ErrorMessage": err_msg,
        "EffectiveUrl": parsed.get("url_effective", target["url"]),
        "IsExpectedHttpCode": is_expected_http_code,
        "ErrorClass": err_class
    }


# ---------------------------------------------------------------------------
# HTTP Probing: Python Fallback
# ---------------------------------------------------------------------------
def run_python_http_probe(target: Dict[str, Any], probe_run: Dict[str, Any]) -> Dict[str, Any]:
    """Perform HTTP probe using stdlib sockets and urllib (fallback)."""
    url = target["url"]
    parsed_url = urllib.parse.urlparse(url)
    host = parsed_url.hostname or ""
    port = parsed_url.port
    if not port:
        port = 443 if parsed_url.scheme == "https" else 80

    connect_timeout = float(probe_run.get("connectTimeoutSeconds", 10))
    max_time = float(probe_run.get("maxTimeSeconds", 120))
    verify_tls = bool(probe_run.get("verifyTls", True))
    follow_redirects = bool(probe_run.get("followRedirects", True))
    user_agent = probe_run.get("userAgent", "")

    dns_ms = 0.0
    tcp_ms = 0.0
    tls_ms = 0.0
    ttfb_ms = 0.0
    total_ms = 0.0
    http_code = 0
    remote_ip = ""
    num_redirects = 0
    size_download = 0
    err_class = ""
    err_detail = ""
    effective_url = url
    http_version = ""

    # Redirect tracking
    class RedirectTracker(urllib.request.HTTPRedirectHandler):
        def __init__(self):
            self.redirect_count = 0
            self.final_url = url

        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.redirect_count += 1
            self.final_url = newurl
            if not follow_redirects or self.redirect_count > 5:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    tracker = RedirectTracker()
    handlers = [tracker]
    ctx = None
    if parsed_url.scheme == "https":
        ctx = ssl.create_default_context()
        if not verify_tls:
            log_message("WARNING: TLS verification is disabled. This is a security risk.", level="WARNING")
            warnings.warn(
                "Unverified HTTPS request is being made. Adding certificate verification is strongly advised.",
                InsecureRequestWarning,
                stacklevel=2,
            )
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # nosec B501
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)

    # 1. Connection-phase timings via sockets
    sock_start = time.perf_counter()
    sock = None
    try:
        # DNS
        dns_start = time.perf_counter()
        addr_info = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        dns_ms = round((time.perf_counter() - dns_start) * 1000, 2)
        remote_ip = addr_info[0][4][0]

        # TCP Connect
        tcp_start = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(connect_timeout)
        sock.connect(addr_info[0][4])
        tcp_ms = round((time.perf_counter() - tcp_start) * 1000, 2)

        # TLS Handshake
        if parsed_url.scheme == "https":
            tls_start = time.perf_counter()
            tls_sock = ctx.wrap_socket(sock, server_hostname=host)
            tls_ms = round((time.perf_counter() - tls_start) * 1000, 2)
            tls_sock.close()
        else:
            sock.close()
            sock = None
    except socket.gaierror as e:
        err_class = "dns_resolution"
        err_detail = f"DNS lookup failed: {e}"
    except (socket.timeout, TimeoutError) as e:
        err_class = "connect"
        err_detail = f"TCP connection timed out: {e}"
    except ConnectionRefusedError as e:
        err_class = "connect"
        err_detail = f"TCP connection refused: {e}"
    except ssl.SSLError as e:
        err_class = "tls"
        err_detail = f"TLS handshake failed: {e}"
    except Exception as e:
        err_class = "connect"
        err_detail = f"Connection phase failed: {e}"
    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    if err_class:
        total_duration = round((time.perf_counter() - sock_start) * 1000, 2)
        return {
            "ExitCode": 1,
            "HttpCode": 0,
            "RemoteIp": remote_ip,
            "HttpVersion": "",
            "NumRedirects": 0,
            "TimeNameLookupMs": dns_ms,
            "TimeConnectMs": tcp_ms,
            "TimeAppConnectMs": tls_ms,
            "TimeStartTransferMs": 0.0,
            "TimeTotalMs": total_duration,
            "SizeDownloadBytes": 0,
            "ErrorMessage": err_detail,
            "EffectiveUrl": url,
            "IsExpectedHttpCode": False,
            "ErrorClass": err_class
        }

    # 2. HTTP Fetch Phase via urllib
    req = urllib.request.Request(url, method=target.get("method", "GET"))
    if user_agent:
        req.add_header("User-Agent", user_agent)

    urllib_start = time.perf_counter()
    try:
        with opener.open(req, timeout=max_time) as resp:
            ttfb_ms = round((time.perf_counter() - urllib_start) * 1000, 2)
            body = resp.read()
            total_ms = round((time.perf_counter() - urllib_start) * 1000, 2)

            http_code = resp.status
            size_download = len(body)
            num_redirects = tracker.redirect_count
            effective_url = tracker.final_url
            version_num = getattr(resp, "version", 11)
            http_version = "1.1" if version_num == 11 else ("1.0" if version_num == 10 else f"{version_num}")
    except urllib.error.HTTPError as e:
        ttfb_ms = round((time.perf_counter() - urllib_start) * 1000, 2)
        total_ms = ttfb_ms
        http_code = e.code
        err_class = "unexpected_http_status"
        err_detail = f"HTTP Error status code: {e.code}"
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        total_ms = round((time.perf_counter() - urllib_start) * 1000, 2)
        if isinstance(getattr(e, "reason", None), socket.timeout) or "timeout" in str(e).lower():
            err_class = "timeout"
        else:
            err_class = "http_error"
        err_detail = f"urllib request failed: {e}"
    except Exception as e:
        total_ms = round((time.perf_counter() - urllib_start) * 1000, 2)
        err_class = "probe_exception"
        err_detail = f"Unexpected error during fetch: {e}"

    expected_codes = target.get("expectedHttpCodes", [200])
    is_expected_http_code = (http_code in expected_codes) if http_code > 0 else False
    if http_code > 0 and not is_expected_http_code and not err_class:
        err_class = "unexpected_http_status"
        err_detail = f"HTTP status code {http_code} not in expected list {expected_codes}"

    total_duration_ms = round((time.perf_counter() - sock_start) * 1000, 2)
    start_transfer_ms = dns_ms + tcp_ms + tls_ms + ttfb_ms

    return {
        "ExitCode": 0 if (is_expected_http_code and not err_class) else 1,
        "HttpCode": http_code,
        "RemoteIp": remote_ip,
        "HttpVersion": http_version,
        "NumRedirects": num_redirects,
        "TimeNameLookupMs": dns_ms,
        "TimeConnectMs": tcp_ms,
        "TimeAppConnectMs": tls_ms,
        "TimeStartTransferMs": start_transfer_ms,
        "TimeTotalMs": total_duration_ms,
        "SizeDownloadBytes": size_download,
        "ErrorMessage": err_detail,
        "EffectiveUrl": effective_url,
        "IsExpectedHttpCode": is_expected_http_code,
        "ErrorClass": err_class
    }


# ---------------------------------------------------------------------------
# HTTP Request & Download Helpers
# ---------------------------------------------------------------------------
def download_url_to_file(
    url: str, output_path: Path, timeout: float, headers: Optional[dict] = None,
    user_agent: Optional[str] = None, verify_tls: bool = True
) -> float:
    """Download a URL directly to output_path using stdlib, measuring time elapsed."""
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, str(v))
    if user_agent:
        req.add_header("User-Agent", user_agent)

    ctx = ssl.create_default_context()
    if not verify_tls:
        log_message("WARNING: TLS verification is disabled. This is a security risk.", level="WARNING")
        warnings.warn(
            "Unverified HTTPS request is being made. Adding certificate verification is strongly advised.",
            InsecureRequestWarning,
            stacklevel=2,
        )
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # nosec B501

    start_time = time.perf_counter()
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
        with open(output_path, "wb") as f:
            # ⚡ Bolt: Increase copy buffer to 1MB to significantly reduce syscall overhead
            # during high-throughput speed test file downloads (default is too small, ~16KB/64KB).
            shutil.copyfileobj(response, f, length=1024 * 1024)

    return (time.perf_counter() - start_time) * 1000


def upload_file_to_url(
    url: str, file_path: Path, method: str, timeout: float,
    user_agent: Optional[str] = None, verify_tls: bool = True
) -> float:
    """Upload a local file content to a URL, measuring time elapsed."""
    start_time = time.perf_counter()
    with open(file_path, "rb") as f:
        data = f.read()

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/octet-stream")
    if user_agent:
        req.add_header("User-Agent", user_agent)

    ctx = ssl.create_default_context()
    if not verify_tls:
        log_message("WARNING: TLS verification is disabled. This is a security risk.", level="WARNING")
        warnings.warn(
            "Unverified HTTPS request is being made. Adding certificate verification is strongly advised.",
            InsecureRequestWarning,
            stacklevel=2,
        )
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # nosec B501

    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
        response.read()

    return (time.perf_counter() - start_time) * 1000


def _wait_for_futures(futures: List[concurrent.futures.Future]) -> List[str]:
    """Wait for futures to complete and collect any raised exceptions as strings."""
    errors = []
    for future in futures:
        try:
            future.result()
        except Exception as e:
            errors.append(str(e))
    return errors


def download_parallel_chunks(
    url: str, transfer_dir: Path, target_bytes: int, num_connections: int,
    timeout: float, user_agent: Optional[str] = None, verify_tls: bool = True,
    ping_host: Optional[str] = None
) -> Tuple[float, float, str, List[float]]:
    """Download chunks of target_bytes in parallel using ThreadPoolExecutor and HTTP Range headers."""
    # Start ping collector if host provided
    collector = None
    if ping_host:
        collector = ConcurrentPingCollector(ping_host, interval_seconds=0.5)
        collector.start()

    # Attempt to resolve the real file content length using a lightweight 1-byte GET request
    file_size = target_bytes
    try:
        req = urllib.request.Request(url)
        req.add_header("Range", "bytes=0-0")
        if user_agent:
            req.add_header("User-Agent", user_agent)
        ctx = ssl.create_default_context()
        if not verify_tls:
            log_message("WARNING: TLS verification is disabled. This is a security risk.", level="WARNING")
            warnings.warn(
                "Unverified HTTPS request is being made. Adding certificate verification is strongly advised.",
                InsecureRequestWarning,
                stacklevel=2,
            )
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE  # nosec B501
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            cr = resp.getheader("Content-Range")
            if cr and "/" in cr:
                file_size = int(cr.split("/")[-1])
            else:
                cl = resp.getheader("Content-Length")
                if cl:
                    file_size = int(cl)
    except Exception:
        pass

    if num_connections <= 1 or file_size <= 0:
        download_file = transfer_dir / "download-single.bin"
        headers = {}
        if file_size > 0:
            headers["Range"] = f"bytes=0-{file_size - 1}"
        try:
            start_time = time.perf_counter()
            dur = download_url_to_file(url, download_file, timeout, headers, user_agent, verify_tls)
            downloaded_bytes = float(download_file.stat().st_size) if download_file.is_file() else 0.0
            if download_file.is_file():
                download_file.unlink()
            latencies = collector.stop() if collector else []
            return dur, downloaded_bytes, "", latencies
        except Exception as e:
            latencies = collector.stop() if collector else []
            return 0.0, 0.0, str(e), latencies

    # Determine if we partition the file or download the full file in parallel across connections.
    # We partition if the file is reasonably large (>= 5MB).
    partition = (file_size >= 5 * 1024 * 1024)

    start_time = time.perf_counter()
    futures = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
        for i in range(num_connections):
            if partition:
                chunk_size = file_size // num_connections
                start_range = i * chunk_size
                if i == num_connections - 1:
                    end_range = file_size - 1
                else:
                    end_range = (i + 1) * chunk_size - 1
            else:
                # Small files (< 5MB) are downloaded completely in parallel across all threads
                start_range = 0
                end_range = file_size - 1

            chunk_file = transfer_dir / f"chunk-{i}.bin"
            headers = {"Range": f"bytes={start_range}-{end_range}"}

            futures.append(
                executor.submit(
                    download_url_to_file,
                    url, chunk_file, timeout, headers, user_agent, verify_tls
                )
            )

        errors = _wait_for_futures(futures)

    end_time = time.perf_counter()
    duration_ms = (end_time - start_time) * 1000

    downloaded_bytes = 0.0
    for i in range(num_connections):
        chunk_file = transfer_dir / f"chunk-{i}.bin"
        if chunk_file.is_file():
            downloaded_bytes += float(chunk_file.stat().st_size)
            try:
                chunk_file.unlink()
            except Exception:
                pass

    error_detail = "; ".join(errors) if errors else ""
    latencies = collector.stop() if collector else []
    return duration_ms, downloaded_bytes, error_detail, latencies


def upload_parallel_chunks(
    url: str, transfer_dir: Path, payload_bytes: int, num_connections: int,
    method: str, timeout: float, user_agent: Optional[str] = None, verify_tls: bool = True,
    ping_host: Optional[str] = None
) -> Tuple[float, float, str, List[float]]:
    """Upload blocks of payload_bytes in parallel using ThreadPoolExecutor."""
    # Start ping collector if host provided
    collector = None
    if ping_host:
        collector = ConcurrentPingCollector(ping_host, interval_seconds=0.5)
        collector.start()

    if num_connections <= 1:
        upload_file = transfer_dir / "upload-single.bin"
        upload_file.write_bytes(os.urandom(payload_bytes))
        try:
            start_time = time.perf_counter()
            dur = upload_file_to_url(url, upload_file, method, timeout, user_agent, verify_tls)
            if upload_file.is_file():
                upload_file.unlink()
            latencies = collector.stop() if collector else []
            return dur, float(payload_bytes), "", latencies
        except Exception as e:
            latencies = collector.stop() if collector else []
            return 0.0, 0.0, str(e), latencies

    start_time = time.perf_counter()
    futures = []
    thread_payload_bytes = max(262144, payload_bytes // num_connections)

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
        for i in range(num_connections):
            chunk_file = transfer_dir / f"upload-chunk-{i}.bin"
            chunk_file.write_bytes(os.urandom(thread_payload_bytes))

            futures.append(
                executor.submit(
                    upload_file_to_url,
                    url, chunk_file, method, timeout, user_agent, verify_tls
                )
            )

        errors = _wait_for_futures(futures)

    end_time = time.perf_counter()
    duration_ms = (end_time - start_time) * 1000

    total_uploaded = 0.0
    for i in range(num_connections):
        chunk_file = transfer_dir / f"upload-chunk-{i}.bin"
        if chunk_file.is_file():
            total_uploaded += float(chunk_file.stat().st_size)
            try:
                chunk_file.unlink()
            except Exception:
                pass

    error_detail = "; ".join(errors) if errors else ""
    latencies = collector.stop() if collector else []
    return duration_ms, total_uploaded, error_detail, latencies


# ---------------------------------------------------------------------------
# Upload Supplement Measurement
# ---------------------------------------------------------------------------
def get_upload_supplement_method(target: Dict[str, Any], probe_run: Dict[str, Any]) -> str:
    m = get_optional_str(target, "uploadMeasurementMethod")
    if m:
        return m.lower()
    return get_optional_str(probe_run, "defaultUploadMeasurementMethod", "none").lower()


def get_upload_supplement_cache_key(target: Dict[str, Any], method: str) -> str:
    service = get_optional_str(target, "service", "").lower()
    endpoint_name = get_optional_str(target, "endpointName", "").lower()
    if method == "networkquality":
        return f"networkquality::{service}::{endpoint_name}"
    elif method == "curl-upload":
        endpoint = get_optional_str(target, "uploadEndpoint", "https://speed.cloudflare.com/__up")
        return f"curl-upload::{service}::{endpoint_name}::{endpoint.lower()}"
    elif method == "upload-url":
        upload_url = get_optional_str(target, "uploadUrl")
        if not upload_url:
            return ""
        return f"upload-url::{service}::{endpoint_name}::{upload_url.lower()}"
    return ""


def run_upload_supplement(
    target: Dict[str, Any], probe_run: Dict[str, Any], tools: Dict[str, Path], cache: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Execute upload supplement if targets lack upload throughput values."""
    method = get_upload_supplement_method(target, probe_run)
    if not method or method == "none":
        return None

    cache_key = get_upload_supplement_cache_key(target, method)
    if cache_key and cache_key in cache:
        return cache[cache_key]

    temp_dir = tools.get("repo_root", Path(".")).resolve() / "bin" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    transfer_dir = temp_dir / f"curl-upload-{get_optional_str(target, 'service')}-{get_optional_str(target, 'endpointName')}-{int(time.time())}"
    transfer_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "Tool": method,
        "UploadMbps": 0.0,
        "ErrorClass": "",
        "ErrorDetail": "",
        "RunDurationMs": 0.0
    }

    try:
        if method == "networkquality":
            # networkquality has upload built-in
            nq_res = run_networkquality_measurement(target, probe_run, tools, disable_burst_fallback=True)
            result["UploadMbps"] = nq_res["UploadMbps"]
            result["ErrorClass"] = nq_res["ErrorClass"]
            result["ErrorDetail"] = nq_res["ErrorDetail"]
            result["RunDurationMs"] = nq_res["RunDurationMs"]

        elif method in ("curl-upload", "upload-url"):
            payload_bytes = max(1, get_optional_int(target, "uploadPayloadBytes", 1048576))
            timeout = get_speedtest_timeout(target, probe_run, 120)
            verify_tls = bool(probe_run.get("verifyTls", True))
            ua = get_optional_str(probe_run, "userAgent")
            num_connections = max(1, get_optional_int(target, "parallelConnections", get_optional_int(probe_run, "parallelConnections", 1)))

            endpoint = ""
            upload_method = "POST"
            if method == "curl-upload":
                endpoint = get_optional_str(target, "uploadEndpoint", "https://speed.cloudflare.com/__up")
            else:
                endpoint = get_optional_str(target, "uploadUrl")
                if not endpoint:
                    raise ValueError("Target is missing uploadUrl.")
                upload_method = get_optional_str(target, "uploadMethod", "POST")

            ref_host = get_optional_str(probe_run, "bufferbloatReferenceHost", "1.1.1.1")
            dur, uploaded_bytes, err_det, ul_latencies = upload_parallel_chunks(
                endpoint, transfer_dir, payload_bytes, num_connections,
                upload_method, timeout, user_agent=ua, verify_tls=verify_tls,
                ping_host=ref_host
            )
            if err_det:
                raise RuntimeError(err_det)

            result["UploadMbps"] = get_mbps_from_bytes_duration(uploaded_bytes, dur)
            result["RunDurationMs"] = dur
            result["Tool"] = f"{method}-{num_connections}x" if num_connections > 1 else method
            result["Latencies"] = ul_latencies

    except Exception as e:
        result["ErrorClass"] = "upload_measurement_error"
        result["ErrorDetail"] = str(e)
    finally:
        if transfer_dir.exists():
            shutil.rmtree(transfer_dir)

    if cache_key:
        cache[cache_key] = result

    return result


# ---------------------------------------------------------------------------
# Puppeteer Chrome Process Killer Helper
# ---------------------------------------------------------------------------
def kill_dangling_chrome(puppeteer_cache_dir: Path) -> None:
    """Kill chrome / chrome-headless-shell instances from the Puppeteer Cache directory."""
    cache_path_str = str(puppeteer_cache_dir).lower()
    if is_windows():
        cmd = [
            "powershell", "-NoProfile", "-Command",
            "Get-Process -Name 'chrome', 'chrome-headless-shell' -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -and $_.Path.StartsWith($env:TARGET_CACHE_PATH) } | "
            "Stop-Process -Force -ErrorAction SilentlyContinue"
        ]
        proc_env = os.environ.copy()
        proc_env["TARGET_CACHE_PATH"] = cache_path_str
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=proc_env)
    else:
        try:
            proc = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) < 2:
                        continue
                    pid_str, cmd_line = parts[0], parts[1]
                    if "chrome" in cmd_line.lower() and cache_path_str in cmd_line.lower():
                        try:
                            os.kill(int(pid_str), 9)
                        except Exception:
                            pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Speed Test: fast-cli
# ---------------------------------------------------------------------------
def run_fast_cli_measurement(target: Dict[str, Any], probe_run: Dict[str, Any], tools: Dict[str, Path]) -> Dict[str, Any]:
    """Execute Puppeteer fast-cli speed test target."""
    node_exe = tools["node_exe"]
    fast_cli_script = tools["fast_cli_script"]

    if not node_exe.is_file():
        raise FileNotFoundError(f"Node.js was not found at '{node_exe}'.")
    if not fast_cli_script.is_file():
        raise FileNotFoundError(f"fast-cli script entrypoint was not found at '{fast_cli_script}'.")

    # Ensure puppeteer cache directory exists
    cache_dir = tools.get("repo_root", Path(".")).resolve() / "bin" / "puppeteer-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    env = {"PUPPETEER_CACHE_DIR": str(cache_dir)}
    timeout = get_speedtest_timeout(target, probe_run, 180)
    attempts = max(1, get_optional_int(target, "fastCliAttemptCount", get_optional_int(probe_run, "fastCliAttemptCount", 2)))

    exit_code = -1
    stdout, stderr = "", ""
    timed_out = False
    duration_ms = 0.0

    ref_host = get_optional_str(probe_run, "bufferbloatReferenceHost", "1.1.1.1")
    ref_base_stats = get_ping_burst_stats(ref_host, count=10, timeout_ms=800)
    ref_base_latency = ref_base_stats["LatencyMs"]
    packet_loss = ref_base_stats["PacketLossPercentage"]

    gw_ip = get_default_gateway()
    gw_latency = 0.0
    if gw_ip:
        gw_stats = get_ping_burst_stats(gw_ip, count=5, timeout_ms=500)
        gw_latency = gw_stats["LatencyMs"]

    collector = ConcurrentPingCollector(ref_host, interval_seconds=0.5)
    collector.start()

    try:
        for attempt in range(1, attempts + 1):
            args = [str(node_exe), str(fast_cli_script), "--upload", "--json"]
            exit_code, stdout, stderr, duration_ms, timed_out = run_external_process(
                args, timeout, cwd=fast_cli_script.parent, env=env
            )
            combined = stderr if stderr else stdout
            is_retryable = (not timed_out) and (exit_code != 0) and ("Navigation timeout" in combined)
            if not is_retryable or attempt == attempts:
                break

        latencies = collector.stop()
        loaded_latency = sum(latencies) / len(latencies) if latencies else 0.0
        bb_combined = max(0.0, round(loaded_latency - ref_base_latency, 2)) if loaded_latency > 0 and ref_base_latency > 0 else 0.0

        err_class = ""
        err_detail = ""
        parsed = {}

        if timed_out:
            err_class = "timeout"
            err_detail = "fast-cli timed out."
        elif exit_code != 0:
            combined = stderr if stderr else stdout
            err_detail = combined.strip()
            if "Navigation timeout" in err_detail:
                err_class = "timeout"
            else:
                err_class = "cli_error"
        else:
            # Parse JSON block
            try:
                start = stdout.index('{')
                end = stdout.rindex('}') + 1
                parsed = json.loads(stdout[start:end])
            except Exception as e:
                err_class = "parse_error"
                err_detail = f"Failed to parse fast-cli JSON output: {e}"

        dl_speed = round(float(parsed.get("downloadSpeed", 0.0)), 2)
        ul_speed = round(float(parsed.get("uploadSpeed", 0.0)), 2)

        host = get_target_host(target)
        ping_stats = get_ping_burst_stats(host)
        latency = round(parsed.get("latency", ping_stats["LatencyMs"]), 2)

        return {
            "Tool": "fast-cli",
            "ExitCode": exit_code,
            "TimedOut": timed_out,
            "DownloadMbps": dl_speed,
            "UploadMbps": ul_speed,
            "LatencyMs": latency,
            "JitterMs": ping_stats["JitterMs"],
            "RpmResponsiveness": get_approximate_rpm(latency),
            "SourceHost": host,
            "ErrorClass": err_class,
            "ErrorDetail": err_detail,
            "RawStdOut": stdout,
            "RawStdErr": stderr,
            "RunDurationMs": duration_ms,
            "Available": (err_class == "" and exit_code == 0),
            "PacketLossPercentage": packet_loss,
            "GatewayLatencyMs": gw_latency,
            "BufferbloatDownloadMs": bb_combined,
            "BufferbloatUploadMs": bb_combined,
            "RefBaseLatencyMs": ref_base_latency
        }
    finally:
        kill_dangling_chrome(cache_dir)


# ---------------------------------------------------------------------------
# Speed Test: yt-dlp
# ---------------------------------------------------------------------------
def run_yt_dlp_measurement(target: Dict[str, Any], probe_run: Dict[str, Any], tools: Dict[str, Path]) -> Dict[str, Any]:
    """Perform yt-dlp video fragment speed test."""
    yt_dlp_exe = tools["yt_dlp_exe"]
    if not yt_dlp_exe.is_file():
        raise FileNotFoundError(f"yt-dlp was not found at '{yt_dlp_exe}'.")

    video_url = get_optional_str(target, "videoUrl", get_optional_str(target, "url"))
    if not video_url:
        raise ValueError("Target requires videoUrl or url.")

    if not (video_url.lower().startswith("http://") or video_url.lower().startswith("https://")):
        raise ValueError("Target videoUrl must start with http:// or https://")

    num_connections = max(1, get_optional_int(target, "parallelConnections", get_optional_int(probe_run, "parallelConnections", 1)))

    temp_dir = tools.get("repo_root", Path(".")).resolve() / "bin" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    transfer_dir = temp_dir / f"yt-dlp-{get_optional_str(target, 'service')}-{get_optional_str(target, 'endpointName')}-{int(time.time())}"
    transfer_dir.mkdir(parents=True, exist_ok=True)

    try:
        timeout = get_speedtest_timeout(target, probe_run, 180)

        # 1. Resolve direct URL via yt-dlp
        args = ["--ignore-config", "--no-update", "--retries", "1", "--socket-timeout", "30"]
        node_exe = tools.get("node_exe")
        if node_exe and node_exe.is_file():
            args.extend(["--no-js-runtimes", "--js-runtimes", f"node:{node_exe}"])

        fmt = get_optional_str(target, "format", "best[protocol^=https][height<=480]/best[height<=480]/best")
        args.extend(["--print", "urls", "--format", fmt, "--", video_url])

        exit_code, stdout, stderr, _, timed_out = run_external_process(
            [str(yt_dlp_exe)] + args, 60, cwd=tools.get("repo_root")
        )

        direct_url = ""
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("http"):
                direct_url = line
                break

        err_class = ""
        err_detail = ""
        download_duration_ms = 0.0
        download_bytes = 0.0
        source_host = ""

        if not direct_url:
            err_class = "resolve_error"
            err_detail = f"yt-dlp failed to resolve direct media URL: {stderr.strip()}"
            source_host = get_target_host(target)
        else:
            try:
                parsed = urllib.parse.urlparse(direct_url)
                source_host = parsed.hostname or ""
            except Exception:
                source_host = get_target_host(target)

            # 2. Fragment Download
            fragment_bytes = max(1, get_optional_int(target, "fragmentBytes", 4194304))
            verify_tls = bool(probe_run.get("verifyTls", True))

            ref_host = get_optional_str(probe_run, "bufferbloatReferenceHost", "1.1.1.1")
            ref_base_stats = get_ping_burst_stats(ref_host, count=10, timeout_ms=800)
            ref_base_latency = ref_base_stats["LatencyMs"]
            packet_loss = ref_base_stats["PacketLossPercentage"]

            gw_ip = get_default_gateway()
            gw_latency = 0.0
            if gw_ip:
                gw_stats = get_ping_burst_stats(gw_ip, count=5, timeout_ms=500)
                gw_latency = gw_stats["LatencyMs"]

            dl_latencies = []
            try:
                download_duration_ms, download_bytes, err_det, dl_latencies = download_parallel_chunks(
                    direct_url, transfer_dir, fragment_bytes, num_connections,
                    timeout, user_agent=get_optional_str(probe_run, "userAgent"), verify_tls=verify_tls,
                    ping_host=ref_host
                )
                if err_det:
                    err_class = "download_error"
                    err_detail = err_det
            except Exception as e:
                err_class = "download_error"
                err_detail = str(e)

        ping_stats = get_ping_burst_stats(source_host)
        download_mbps = get_mbps_from_bytes_duration(download_bytes, download_duration_ms)

        dl_loaded_latency = sum(dl_latencies) / len(dl_latencies) if dl_latencies else 0.0
        bb_dl = max(0.0, round(dl_loaded_latency - ref_base_latency, 2)) if dl_loaded_latency > 0 and ref_base_latency > 0 else 0.0

        if not err_class and download_bytes <= 0:
            err_class = "download_empty"
            err_detail = "Direct media URL resolved but fragment download wrote no bytes."

        return {
            "Tool": f"yt-dlp-{num_connections}x" if num_connections > 1 else "yt-dlp",
            "ExitCode": 0 if not err_class else -1,
            "TimedOut": False,
            "DownloadMbps": download_mbps,
            "UploadMbps": 0.0,
            "LatencyMs": ping_stats["LatencyMs"],
            "JitterMs": ping_stats["JitterMs"],
            "RpmResponsiveness": get_approximate_rpm(ping_stats["LatencyMs"]),
            "SourceHost": source_host,
            "ErrorClass": err_class,
            "ErrorDetail": err_detail,
            "RawStdOut": direct_url,
            "RawStdErr": stderr if not direct_url else "",
            "RunDurationMs": download_duration_ms,
            "Available": (err_class == "" and download_bytes > 0),
            "PacketLossPercentage": packet_loss,
            "GatewayLatencyMs": gw_latency,
            "BufferbloatDownloadMs": bb_dl,
            "BufferbloatUploadMs": 0.0,
            "RefBaseLatencyMs": ref_base_latency
        }

    finally:
        if transfer_dir.exists():
            shutil.rmtree(transfer_dir)


# ---------------------------------------------------------------------------
# Speed Test: networkquality
# ---------------------------------------------------------------------------
def run_networkquality_measurement(
    target: Dict[str, Any], probe_run: Dict[str, Any], tools: Dict[str, Path], disable_burst_fallback: bool = False
) -> Dict[str, Any]:
    """Execute networkquality QoE speed test."""
    nq_exe = tools["network_quality_exe"]

    # Detect if command available
    cmd_found = False
    if nq_exe.is_file():
        cmd_found = True
    elif shutil.which("networkquality") is not None:
        nq_exe = Path("networkquality")
        cmd_found = True

    if not cmd_found:
        if disable_burst_fallback:
            raise FileNotFoundError(f"networkquality command not found for target '{target.get('service')}/{target.get('endpointName')}'")
        log_message("networkquality executable not found, falling back to burst traffic method.", "WARN")
        return run_burst_traffic_measurement(target, probe_run, tools)

    args = []
    # If JSON output is supported natively
    args.append("-j")  # macOS networkquality supports JSON with -j

    # Target specific arguments
    target_args = target.get("arguments")
    if target_args:
        if isinstance(target_args, list):
            args.extend([str(x) for x in target_args])
        else:
            args.append(str(target_args))

    timeout = get_speedtest_timeout(target, probe_run, 180)
    exit_code, stdout, stderr, duration_ms, timed_out = run_external_process(
        [str(nq_exe)] + args, timeout, cwd=tools.get("repo_root")
    )

    err_class = ""
    err_detail = ""
    download_speed = 0.0
    upload_speed = 0.0
    latency = 0.0
    rpm_responsiveness = 0.0

    if timed_out:
        err_class = "timeout"
        err_detail = "networkquality timed out."
    elif exit_code != 0:
        err_class = "cli_error"
        err_detail = stderr.strip() if stderr else stdout.strip()
    else:
        # Try JSON first
        try:
            start = stdout.index('{')
            end = stdout.rindex('}') + 1
            parsed = json.loads(stdout[start:end])
            # macOS JSON structure contains dl_throughput / ul_throughput in bps
            # and responsiveness_muds (RPM)
            # wait, let's also check downloadMbps / uploadMbps
            download_speed = parsed.get("downloadMbps") or parsed.get("dl_throughput", 0) / 1_000_000.0
            upload_speed = parsed.get("uploadMbps") or parsed.get("ul_throughput", 0) / 1_000_000.0
            latency = parsed.get("latencyMs") or parsed.get("idle_latency", 0)
            rpm_responsiveness = parsed.get("rpmResponsiveness") or parsed.get("responsiveness_muds", 0)
        except Exception:
            # Fallback regex parsing on stdout text
            combined = stdout + "\n" + stderr
            # Download
            m_dl = NQ_DOWNLOAD_RX1.search(combined)
            if not m_dl:
                m_dl = NQ_DOWNLOAD_RX2.search(combined)
            if m_dl:
                download_speed = float(m_dl.group(1))

            # Upload
            m_ul = NQ_UPLOAD_RX1.search(combined)
            if not m_ul:
                m_ul = NQ_UPLOAD_RX2.search(combined)
            if m_ul:
                upload_speed = float(m_ul.group(1))

            # Latency
            m_lat = NQ_LATENCY_RX1.search(combined)
            if not m_lat:
                m_lat = NQ_LATENCY_RX2.search(combined)
            if m_lat:
                latency = float(m_lat.group(1))

            # RPM
            m_rpm = NQ_RPM_RX1.search(combined)
            if not m_rpm:
                m_rpm = NQ_RPM_RX2.search(combined)
            if m_rpm:
                rpm_responsiveness = float(m_rpm.group(1))

    host = get_target_host(target)
    ping_stats = get_ping_burst_stats(host)
    if latency <= 0:
        latency = ping_stats["LatencyMs"]
    if rpm_responsiveness <= 0:
        rpm_responsiveness = get_approximate_rpm(latency)

    if not err_class and download_speed <= 0 and upload_speed <= 0:
        err_class = "parse_error"
        err_detail = "networkquality did not report throughput or responsiveness metrics."

    return {
        "Tool": "networkquality",
        "ExitCode": exit_code,
        "TimedOut": timed_out,
        "DownloadMbps": round(download_speed, 2),
        "UploadMbps": round(upload_speed, 2),
        "LatencyMs": round(latency, 2),
        "JitterMs": ping_stats["JitterMs"],
        "RpmResponsiveness": round(rpm_responsiveness, 2),
        "SourceHost": host,
        "ErrorClass": err_class,
        "ErrorDetail": err_detail,
        "RawStdOut": stdout,
        "RawStdErr": stderr,
        "RunDurationMs": duration_ms,
        "Available": (err_class == "" and exit_code == 0)
    }

def log_bufferbloat_diagnostic(
    target: Dict[str, Any],
    download_mbps: float,
    upload_mbps: float,
    base_latency: float,
    dl_latency_increase: float,
    ul_latency_increase: float,
    packet_loss: float,
    gw_latency: float
):
    """Print a beautiful bufferbloat diagnostic report card in Spanish in the logs."""
    max_increase = max(dl_latency_increase, ul_latency_increase)
    
    # Determine grade
    if max_increase < 5.0:
        grade = "A+"
        desc = "Tu latencia casi no aumentó bajo carga."
    elif max_increase < 30.0:
        grade = "A"
        desc = "Tu latencia aumentó ligeramente bajo carga."
    elif max_increase < 60.0:
        grade = "B"
        desc = "Tu latencia aumentó de forma moderada bajo carga."
    elif max_increase < 200.0:
        grade = "C"
        desc = "Tu latencia aumentó de forma notable bajo carga."
    elif max_increase < 400.0:
        grade = "D"
        desc = "Tu latencia aumentó de forma crítica bajo carga."
    else:
        grade = "F"
        desc = "Tu latencia sufre una degradación extrema bajo carga."

    # Loaded latencies
    dl_loaded_latency = base_latency + dl_latency_increase
    ul_loaded_latency = base_latency + ul_latency_increase
    max_loaded_latency = max(dl_loaded_latency, ul_loaded_latency)

    # Connection suitability logic
    # Web Browsing: Download > 2 Mbps, Upload > 100 Kbps (0.1 Mbps), Latency < 500 ms
    web_ideal = download_mbps > 2.0 and upload_mbps > 0.1 and base_latency < 500.0
    web_stress = download_mbps > 2.0 and upload_mbps > 0.1 and max_loaded_latency < 500.0

    # Audio Calls: Download > 100 Kbps (0.1 Mbps), Upload > 100 Kbps (0.1 Mbps), Latency < 400 ms
    audio_ideal = download_mbps > 0.1 and upload_mbps > 0.1 and base_latency < 400.0
    audio_stress = download_mbps > 0.1 and upload_mbps > 0.1 and max_loaded_latency < 400.0

    # 4K Video Streaming: Download > 25 Mbps
    video_4k_ideal = download_mbps > 25.0
    video_4k_stress = download_mbps > 25.0

    # Video Conferencing: Download > 10 Mbps, Upload > 5 Mbps, Latency < 400 ms
    conf_ideal = download_mbps > 10.0 and upload_mbps > 5.0 and base_latency < 400.0
    conf_stress = download_mbps > 10.0 and upload_mbps > 5.0 and max_loaded_latency < 400.0

    # Low Latency Gaming: Download > 10 Mbps, Upload > 3 Mbps, Latency < 40 ms
    gaming_ideal = download_mbps > 10.0 and upload_mbps > 3.0 and base_latency < 40.0
    gaming_stress = download_mbps > 10.0 and upload_mbps > 3.0 and max_loaded_latency < 40.0

    def fmt_check(val):
        return "✅" if val else "❎"

    service_name = target.get("service", "Servicio")
    endpoint_name = target.get("endpointName", "endpoint")

    log_message("============================================================")
    log_message(f"CALIFICACIÓN DE BUFFERBLOAT ({service_name}/{endpoint_name})")
    log_message(f"GRADO: {grade}")
    log_message(desc)
    log_message("")
    log_message("TU CONEXIÓN")
    log_message("Caso de Uso             Ideal   Con Bufferbloat")
    log_message(f"Navegación Web            {fmt_check(web_ideal)}          {fmt_check(web_stress)}")
    log_message(f"Llamadas de Audio         {fmt_check(audio_ideal)}          {fmt_check(audio_stress)}")
    log_message(f"Streaming Video 4K        {fmt_check(video_4k_ideal)}          {fmt_check(video_4k_stress)}")
    log_message(f"Videoconferencias         {fmt_check(conf_ideal)}          {fmt_check(conf_stress)}")
    log_message(f"Juegos Baja Latencia      {fmt_check(gaming_ideal)}          {fmt_check(gaming_stress)}")
    log_message("")
    log_message("LATENCIA")
    log_message(f"Base (Sin Carga): {round(base_latency, 2)} ms")
    log_message(f"Descarga Activa: +{round(dl_latency_increase, 2)} ms (Total: {round(dl_loaded_latency, 2)} ms)")
    log_message(f"Subida Activa:   +{round(ul_latency_increase, 2)} ms (Total: {round(ul_loaded_latency, 2)} ms)")
    log_message(f"Pérdida Paquetes: {round(packet_loss, 2)}%")
    log_message(f"Router (Gateway): {f'{round(gw_latency, 2)} ms' if gw_latency > 0 else 'Desconocido'}")
    log_message("")
    log_message("VELOCIDAD")
    log_message(f"↓ Descarga: {round(download_mbps, 2)} Mbps")
    log_message(f"↑ Subida:   {round(upload_mbps, 2)} Mbps")
    log_message("============================================================")


def run_burst_traffic_measurement(target: Dict[str, Any], probe_run: Dict[str, Any], tools: Dict[str, Path]) -> Dict[str, Any]:
    """Perform burst traffic speed test using standard HTTP Range requests."""
    download_url = get_optional_str(target, "downloadUrl", get_optional_str(target, "url"))
    if not download_url:
        raise ValueError("Burst target requires downloadUrl or url.")

    temp_dir = tools.get("repo_root", Path(".")).resolve() / "bin" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    transfer_dir = temp_dir / f"burst-{get_optional_str(target, 'service')}-{get_optional_str(target, 'endpointName')}-{int(time.time())}"
    transfer_dir.mkdir(parents=True, exist_ok=True)

    try:
        timeout = get_speedtest_timeout(target, probe_run, 120)
        ua = get_optional_str(probe_run, "userAgent")
        target_bytes = max(0, get_optional_int(target, "targetTransferBytes", 0))
        num_connections = max(1, get_optional_int(target, "parallelConnections", get_optional_int(probe_run, "parallelConnections", 1)))
        verify_tls = bool(probe_run.get("verifyTls", True))

        ref_host = get_optional_str(probe_run, "bufferbloatReferenceHost", "1.1.1.1")
        ref_base_stats = get_ping_burst_stats(ref_host, count=10, timeout_ms=800)
        ref_base_latency = ref_base_stats["LatencyMs"]
        packet_loss = ref_base_stats["PacketLossPercentage"]

        gw_ip = get_default_gateway()
        gw_latency = 0.0
        if gw_ip:
            gw_stats = get_ping_burst_stats(gw_ip, count=5, timeout_ms=500)
            gw_latency = gw_stats["LatencyMs"]

        error_class = ""
        error_detail = ""
        download_duration_ms = 0.0
        upload_duration_ms = 0.0
        download_bytes = 0.0
        verify_tls = bool(probe_run.get("verifyTls", True))

        start_time = time.perf_counter()

        dl_latencies = []
        try:
            download_duration_ms, download_bytes, err_det, dl_latencies = download_parallel_chunks(
                download_url, transfer_dir, target_bytes, num_connections,
                timeout, user_agent=ua, verify_tls=verify_tls, ping_host=ref_host
            )
            if err_det:
                error_class = "download_error"
                error_detail = err_det
        except Exception as e:
            error_class = "download_error"
            error_detail = str(e)

        download_mbps = get_mbps_from_bytes_duration(download_bytes, download_duration_ms)
        upload_mbps = 0.0
        ul_latencies = []

        # Upload
        upload_url = get_optional_str(target, "uploadUrl")
        if not error_class and upload_url:
            try:
                payload_bytes = max(1, get_optional_int(target, "uploadPayloadBytes", 1048576))
                upload_method = get_optional_str(target, "uploadMethod", "POST")
                elapsed_seconds = time.perf_counter() - start_time
                remaining_seconds = timeout - elapsed_seconds
                if remaining_seconds <= 0:
                    error_class = "timeout"
                    error_detail = "burst upload timed out before starting."
                else:
                    upload_duration_ms, uploaded_bytes, err_det, ul_latencies = upload_parallel_chunks(
                        upload_url, transfer_dir, payload_bytes, num_connections,
                        upload_method, remaining_seconds, user_agent=ua, verify_tls=verify_tls, ping_host=ref_host
                    )
                    if err_det:
                        error_class = "upload_error"
                        error_detail = err_det
                    else:
                        upload_mbps = get_mbps_from_bytes_duration(uploaded_bytes, upload_duration_ms)
            except Exception as e:
                error_class = "upload_error"
                error_detail = str(e)

        dl_loaded_latency = sum(dl_latencies) / len(dl_latencies) if dl_latencies else 0.0
        ul_loaded_latency = sum(ul_latencies) / len(ul_latencies) if ul_latencies else 0.0

        bb_dl = max(0.0, round(dl_loaded_latency - ref_base_latency, 2)) if dl_loaded_latency > 0 and ref_base_latency > 0 else 0.0
        bb_ul = max(0.0, round(ul_loaded_latency - ref_base_latency, 2)) if ul_loaded_latency > 0 and ref_base_latency > 0 else 0.0

        host = get_target_host(target)
        ping_stats = get_ping_burst_stats(host)
        latency = ping_stats["LatencyMs"]

        return {
            "Tool": f"burst-{num_connections}x" if num_connections > 1 else "burst",
            "ExitCode": 0 if not error_class else -1,
            "TimedOut": False,
            "DownloadMbps": download_mbps,
            "UploadMbps": upload_mbps,
            "LatencyMs": latency,
            "JitterMs": ping_stats["JitterMs"],
            "RpmResponsiveness": get_approximate_rpm(latency),
            "SourceHost": host,
            "ErrorClass": error_class,
            "ErrorDetail": error_detail,
            "RawStdOut": f"download_connections={num_connections};download_bytes={int(download_bytes)};target_transfer_bytes={target_bytes};download_url={download_url}",
            "RawStdErr": "",
            "RunDurationMs": download_duration_ms + upload_duration_ms,
            "Available": (error_class == "" and (download_bytes > 0 or upload_mbps > 0)),
            "PacketLossPercentage": packet_loss,
            "GatewayLatencyMs": gw_latency,
            "BufferbloatDownloadMs": bb_dl,
            "BufferbloatUploadMs": bb_ul,
            "RefBaseLatencyMs": ref_base_latency
        }
    finally:
        if transfer_dir.exists():
            shutil.rmtree(transfer_dir)


# ---------------------------------------------------------------------------
# Combined Speed Test Execution Handler
# ---------------------------------------------------------------------------
def run_speedtest_target_wrapper(
    target: Dict[str, Any], config: Dict[str, Any], tools: Dict[str, Path], upload_cache: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute speedtest target based on speedTestMethod, appending upload supplement if needed."""
    method = get_optional_str(target, "speedTestMethod").lower()
    probe_run = config.get("probeRun", {})

    if method == "fast-cli":
        res = run_fast_cli_measurement(target, probe_run, tools)
    elif method == "yt-dlp":
        res = run_yt_dlp_measurement(target, probe_run, tools)
    elif method == "networkquality":
        res = run_networkquality_measurement(target, probe_run, tools)
    elif method == "burst":
        res = run_burst_traffic_measurement(target, probe_run, tools)
    else:
        raise ValueError(f"Unsupported speedTestMethod '{method}' on target '{target.get('service')}/{target.get('endpointName')}'")

    # Upload supplement if target succeeded but reported 0 upload
    upload_tool = "none"
    upload_err_class = ""
    upload_err_detail = ""

    if res["UploadMbps"] > 0:
        if res["Tool"] == "burst" and get_optional_str(target, "uploadUrl"):
            upload_tool = "upload-url"
        else:
            upload_tool = res["Tool"]
    elif res["Available"]:
        try:
            supp = run_upload_supplement(target, probe_run, tools, upload_cache)
            if supp:
                res["RunDurationMs"] = round(res["RunDurationMs"] + supp["RunDurationMs"], 2)
                upload_tool = supp["Tool"]
                if supp["UploadMbps"] > 0 and not supp["ErrorClass"]:
                    res["UploadMbps"] = supp["UploadMbps"]
                    # Update bufferbloat upload if supplement provided latencies
                    ul_latencies = supp.get("Latencies", [])
                    if ul_latencies:
                        ref_base_latency = res.get("RefBaseLatencyMs", 0.0)
                        ul_loaded_latency = sum(ul_latencies) / len(ul_latencies)
                        res["BufferbloatUploadMs"] = max(0.0, round(ul_loaded_latency - ref_base_latency, 2)) if ref_base_latency > 0 else 0.0
                else:
                    upload_err_class = supp["ErrorClass"] or "upload_unavailable"
                    upload_err_detail = supp["ErrorDetail"] or "Upload supplement did not return throughput."
        except Exception as e:
            upload_tool = get_upload_supplement_method(target, probe_run) or "none"
            upload_err_class = "upload_measurement_error"
            upload_err_detail = str(e)

    isp = get_target_isp(target, config.get("probe", {}))
    measurement_name = get_optional_str(probe_run, "realMetricsMeasurement", "qoe_real_metrics")

    packet_loss = res.get("PacketLossPercentage", 0.0)
    gw_latency = res.get("GatewayLatencyMs", 0.0)
    bb_dl = res.get("BufferbloatDownloadMs", 0.0)
    bb_ul = res.get("BufferbloatUploadMs", 0.0)
    ref_base_latency = res.get("RefBaseLatencyMs", 0.0)

    # Call log_bufferbloat_diagnostic on success
    if res["Available"] and res["ErrorClass"] == "":
        log_bufferbloat_diagnostic(
            target, res["DownloadMbps"], res["UploadMbps"], ref_base_latency, bb_dl, bb_ul, packet_loss, gw_latency
        )

    fields = {
        "download_speed": res["DownloadMbps"],
        "upload_speed": res["UploadMbps"],
        "upload_tool": upload_tool,
        "upload_error_class": upload_err_class,
        "upload_error_detail": upload_err_detail,
        "latency": res["LatencyMs"],
        "jitter": res["JitterMs"],
        "rpm_responsiveness": res["RpmResponsiveness"],
        "endpoint_name": target["endpointName"],
        "target_type": "speedtest",
        "speed_test_method": method,
        "tool": res["Tool"],
        "available": res["Available"],
        "source_host": res["SourceHost"],
        "error_class": res["ErrorClass"],
        "error_detail": res["ErrorDetail"],
        "run_duration_ms": res["RunDurationMs"],
        "packet_loss_percentage": packet_loss,
        "gateway_latency_ms": gw_latency,
        "bufferbloat_download_ms": bb_dl,
        "bufferbloat_upload_ms": bb_ul
    }

    probe_cfg = config.get("probe", {})
    tags = {
        "service": target["service"],
        "probe_id": probe_cfg.get("probeId", "unknown"),
        "isp": isp,
        "router_brand": probe_cfg.get("router_brand", "unknown"),
        "router_model": probe_cfg.get("router_model", "unknown"),
        "connection_type": probe_cfg.get("connection_type", "unknown")
    }

    report = {
        "service": target["service"],
        "endpoint_name": target["endpointName"],
        "type": "speedtest",
        "speed_test_method": method,
        "available": res["Available"],
        "download_mbps": res["DownloadMbps"],
        "upload_mbps": res["UploadMbps"],
        "upload_tool": upload_tool,
        "upload_error_class": upload_err_class,
        "upload_error_detail": upload_err_detail,
        "latency_ms": res["LatencyMs"],
        "jitter_ms": res["JitterMs"],
        "rpm_responsiveness": res["RpmResponsiveness"],
        "isp": isp,
        "source_host": res["SourceHost"],
        "error_class": res["ErrorClass"],
        "error_detail": res["ErrorDetail"],
        "run_duration_ms": res["RunDurationMs"],
        "packet_loss_percentage": packet_loss,
        "gateway_latency_ms": gw_latency,
        "bufferbloat_download_ms": bb_dl,
        "bufferbloat_upload_ms": bb_ul
    }

    # Format log message
    if res["Available"]:
        log_msg = f"Target {target['service']}/{target['endpointName']} completed with download {res['DownloadMbps']} Mbps, upload {res['UploadMbps']} Mbps via {upload_tool}, latency {res['LatencyMs']} ms, jitter {res['JitterMs']} ms, rpm {res['RpmResponsiveness']}, tool {res['Tool']}"
        log_msg += f", loss {packet_loss}%, gateway_latency {gw_latency} ms, bufferbloat_dl {bb_dl} ms, bufferbloat_ul {bb_ul} ms"
        if upload_err_class:
            log_msg += f", upload_error_class {upload_err_class}: {upload_err_detail}"
    else:
        log_msg = f"Target {target['service']}/{target['endpointName']} completed with error_class {res['ErrorClass'] or 'unavailable'}: {res['ErrorDetail'] or 'No additional detail was provided.'}"

    return {
        "Measurement": measurement_name,
        "Tags": tags,
        "Fields": fields,
        "Report": report,
        "Available": res["Available"],
        "LogMessage": log_msg
    }


def get_speedtest_failure_target_result(target: Dict[str, Any], config: Dict[str, Any], error_msg: str, duration_ms: float) -> Dict[str, Any]:
    """Generate speedtest failure target result dictionary when execution throws exception."""
    isp = get_target_isp(target, config.get("probe", {}))
    method = get_optional_str(target, "speedTestMethod", "unknown").lower()
    host = get_target_host(target)
    measurement_name = get_optional_str(config.get("probeRun", {}), "realMetricsMeasurement", "qoe_real_metrics")

    fields = {
        "download_speed": 0.0,
        "upload_speed": 0.0,
        "upload_tool": "none",
        "upload_error_class": "",
        "upload_error_detail": "",
        "latency": 0.0,
        "jitter": 0.0,
        "rpm_responsiveness": 0.0,
        "endpoint_name": target["endpointName"],
        "target_type": "speedtest",
        "speed_test_method": method,
        "tool": method,
        "available": False,
        "source_host": host,
        "error_class": "probe_exception",
        "error_detail": error_msg,
        "run_duration_ms": duration_ms,
        "packet_loss_percentage": 0.0,
        "gateway_latency_ms": 0.0,
        "bufferbloat_download_ms": 0.0,
        "bufferbloat_upload_ms": 0.0
    }

    probe_cfg = config.get("probe", {})
    tags = {
        "service": target["service"],
        "probe_id": probe_cfg.get("probeId", "unknown"),
        "isp": isp,
        "router_brand": probe_cfg.get("router_brand", "unknown"),
        "router_model": probe_cfg.get("router_model", "unknown"),
        "connection_type": probe_cfg.get("connection_type", "unknown")
    }

    report = {
        "service": target["service"],
        "endpoint_name": target["endpointName"],
        "type": "speedtest",
        "speed_test_method": method,
        "available": False,
        "download_mbps": 0.0,
        "upload_mbps": 0.0,
        "upload_tool": "none",
        "upload_error_class": "",
        "upload_error_detail": "",
        "latency_ms": 0.0,
        "jitter_ms": 0.0,
        "rpm_responsiveness": 0.0,
        "isp": isp,
        "source_host": host,
        "error_class": "probe_exception",
        "error_detail": error_msg,
        "run_duration_ms": duration_ms,
        "packet_loss_percentage": 0.0,
        "gateway_latency_ms": 0.0,
        "bufferbloat_download_ms": 0.0,
        "bufferbloat_upload_ms": 0.0
    }

    return {
        "Measurement": measurement_name,
        "Tags": tags,
        "Fields": fields,
        "Report": report,
        "Available": False,
        "LogMessage": f"Target {target['service']}/{target['endpointName']} failed: {error_msg}"
    }


# ---------------------------------------------------------------------------
# InfluxDB HTTP Client
# ---------------------------------------------------------------------------
def write_to_influx(url: str, token: str, payload: str, timeout: float) -> bool:
    """Send line protocol payload to InfluxDB API via HTTP POST request."""
    req = urllib.request.Request(
        url,
        data=payload.encode("utf-8"),
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "text/plain; charset=utf-8"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response.read()
        return True
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            body = ""
        err_msg = f"InfluxDB write failed. Status code: {e.code}. Response body: {body}"
        raise RuntimeError(err_msg) from e
    except Exception as e:
        raise RuntimeError(f"InfluxDB write failed: {e}") from e


# ---------------------------------------------------------------------------
# Main Execution Block
# ---------------------------------------------------------------------------
def main() -> None:
    global log_path_global

    script_start = datetime.datetime.now()
    script_start_perf = time.perf_counter()

    parser = argparse.ArgumentParser(description="CX-Radar QoE Probe (cross-platform).")
    parser.add_argument(
        "--config-path",
        type=str,
        default="",
        help="Path to probe-catalog.json (default: ../config/probe-catalog.json)"
    )
    parser.add_argument(
        "--run-report-path",
        type=str,
        default="",
        help="Optional path to write a JSON run report"
    )
    parser.add_argument(
        "--skip-influx-write",
        action="store_true",
        help="Skip sending metrics to InfluxDB"
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    # Determine config file path
    if args.config_path:
        config_path = Path(args.config_path).resolve()
    else:
        config_path = (repo_root / "config" / "probe-catalog.json").resolve()

    if not config_path.is_file():
        print(f"Error: Config file not found at {config_path}", file=sys.stderr)
        sys.exit(1)

    # Load configuration
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error: Failed to parse configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    probe_run = config.get("probeRun", {})
    probe_cfg = config.get("probe", {})
    influx_cfg = config.get("influx", {})

    # Logging setup
    log_dir_raw = get_optional_str(probe_run, "logDirectory", "logs")
    log_dir = resolve_from_base(config_path.parent, f"../{log_dir_raw}")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path_global = log_dir / f"qoe-probe-{script_start.strftime('%Y-%m-%d')}.log"

    # Resolving tools paths
    pt_cfg = probe_run.get("portableTools", {})
    node_child = get_optional_str(pt_cfg, "nodeExe", str(Path("bin", "node", exe_name("node"))))
    fast_cli_child = get_optional_str(pt_cfg, "fastCliScript", str(Path("bin", "fast-cli", "node_modules", "fast-cli", "distribution", "cli.js")))
    yt_dlp_child = get_optional_str(pt_cfg, "ytDlpExe", str(Path("bin", exe_name("yt-dlp"))))
    tmp_child = get_optional_str(pt_cfg, "temporaryDirectory", str(Path("bin", "tmp")))

    if is_windows():
        nq_default = str(Path(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "networkquality.exe"))
    else:
        nq_default = "networkquality"
    nq_child = get_optional_str(pt_cfg, "networkQualityExe", nq_default)

    fast_cli_path = resolve_from_base(repo_root, fast_cli_child)
    if not fast_cli_path.is_file():
        alt_path = fast_cli_path.parent.parent / "cli.js"
        if alt_path.is_file():
            fast_cli_path = alt_path

    tools = {
        "node_exe": resolve_from_base(repo_root, node_child),
        "fast_cli_script": fast_cli_path,
        "yt_dlp_exe": resolve_from_base(repo_root, yt_dlp_child),
        "network_quality_exe": resolve_from_base(repo_root, nq_child),
        "temporary_directory": resolve_from_base(repo_root, tmp_child),
        "puppeteer_cache_dir": resolve_from_base(repo_root, get_optional_str(pt_cfg, "puppeteerCacheDir", str(Path("bin", "puppeteer-cache")))),
        "repo_root": repo_root
    }

    # Resolve curl path
    curl_path = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "curl.exe"
    portable_curl = repo_root / "bin" / exe_name("curl")
    if portable_curl.is_file():
        curl_path = portable_curl
    elif is_windows() and curl_path.is_file():
        pass
    else:
        which_curl = shutil.which("curl")
        curl_path = Path(which_curl) if which_curl else Path("curl")

    lines: List[str] = []
    success_count = 0
    failure_count = 0
    token_value = ""
    enabled_targets = [t for t in config.get("targets", []) if t.get("enabled")]
    start_jitter_max = get_optional_int(probe_run, "startJitterSecondsMax", 0)
    target_delay_ms = get_optional_int(probe_run, "targetDelayMilliseconds", 0)
    influx_write_timeout = get_optional_int(influx_cfg, "writeTimeoutSeconds", 30)

    run_jitter = 0
    target_reports = []
    write_attempted = not args.skip_influx_write
    write_succeeded = False
    write_uri = ""
    fatal_error_message = ""
    threw = False
    upload_cache = {}

    try:
        log_message(f"Starting QoE probe using config {config_path}")

        # Stale artifacts GC
        gc_removed = run_garbage_collection(repo_root, tools["temporary_directory"])
        if gc_removed > 0:
            log_message(f"Environment GC removed {gc_removed} stale artifact(s) or log(s).")

        # Start jitter
        if start_jitter_max > 0:
            run_jitter = random.randint(0, start_jitter_max)
            if run_jitter > 0:
                log_message(f"Applying start jitter of {run_jitter} second(s) to reduce fixed-schedule burst patterns.")
                time.sleep(run_jitter)

        # Resolve Influx Token
        if write_attempted:
            token_value = get_influx_token(influx_cfg, config_path.parent)

        # Target Probing Loop
        for i, target in enumerate(enabled_targets):
            target_start_perf = time.perf_counter()
            target_type = get_target_type(target)

            # Target Delay
            if target_delay_ms > 0 and i > 0:
                time.sleep(target_delay_ms / 1000.0)

            try:
                if target_type == "speedtest":
                    res = run_speedtest_target_wrapper(target, config, tools, upload_cache)
                    if res["Available"]:
                        success_count += 1
                    else:
                        failure_count += 1

                    timestamp_ms = int(time.time() * 1000)
                    lines.append(build_influx_line(res["Measurement"], res["Tags"], res["Fields"], timestamp_ms))
                    target_reports.append(res["Report"])
                    log_message(res["LogMessage"])
                else:
                    # HTTP Probing
                    # Determine whether we use curl or fallback
                    curl_ready = False
                    if curl_path.name == "curl":
                        curl_ready = shutil.which("curl") is not None
                    else:
                        curl_ready = curl_path.is_file()

                    if curl_ready:
                        res = run_curl_http_probe(curl_path, target, probe_run)
                    else:
                        res = run_python_http_probe(target, probe_run)

                    available = (res["ExitCode"] == 0 and res["IsExpectedHttpCode"])
                    if available:
                        success_count += 1
                    else:
                        failure_count += 1

                    tags = {
                        "probe_id": probe_cfg.get("probeId", "unknown"),
                        "probe_type": probe_cfg.get("probeType", "python"),
                        "site": probe_cfg.get("site", "unknown"),
                        "environment": probe_cfg.get("environment", "unknown"),
                        "service": target["service"],
                        "endpoint_name": target["endpointName"],
                        "probe_version": probe_cfg.get("probeVersion", PROBE_VERSION),
                        "router_brand": probe_cfg.get("router_brand", "unknown"),
                        "router_model": probe_cfg.get("router_model", "unknown"),
                        "connection_type": probe_cfg.get("connection_type", "unknown")
                    }

                    fields = {
                        "available": available,
                        "http_status": res["HttpCode"],
                        "curl_exit_code": res["ExitCode"],
                        "time_namelookup_ms": res["TimeNameLookupMs"],
                        "time_connect_ms": res["TimeConnectMs"],
                        "time_appconnect_ms": res["TimeAppConnectMs"],
                        "time_starttransfer_ms": res["TimeStartTransferMs"],
                        "time_total_ms": res["TimeTotalMs"],
                        "size_download_bytes": res["SizeDownloadBytes"],
                        "num_redirects": res["NumRedirects"],
                        "http_version": res["HttpVersion"],
                        "remote_ip": res["RemoteIp"],
                        "error_class": res["ErrorClass"],
                        "error_detail": res["ErrorMessage"],
                        "effective_url": res["EffectiveUrl"],
                        "run_duration_ms": round((time.perf_counter() - target_start_perf) * 1000, 2)
                    }

                    timestamp_ms = int(time.time() * 1000)
                    lines.append(build_influx_line(probe_run.get("measurement", "qoe_http_check"), tags, fields, timestamp_ms))

                    target_reports.append({
                        "service": target["service"],
                        "endpoint_name": target["endpointName"],
                        "url": target["url"],
                        "type": "http",
                        "available": available,
                        "http_status": res["HttpCode"],
                        "curl_exit_code": res["ExitCode"],
                        "time_namelookup_ms": res["TimeNameLookupMs"],
                        "time_connect_ms": res["TimeConnectMs"],
                        "time_appconnect_ms": res["TimeAppConnectMs"],
                        "time_starttransfer_ms": res["TimeStartTransferMs"],
                        "time_total_ms": res["TimeTotalMs"],
                        "size_download_bytes": res["SizeDownloadBytes"],
                        "num_redirects": res["NumRedirects"],
                        "http_version": res["HttpVersion"],
                        "remote_ip": res["RemoteIp"],
                        "error_class": res["ErrorClass"],
                        "error_detail": res["ErrorMessage"],
                        "effective_url": res["EffectiveUrl"],
                        "run_duration_ms": fields["run_duration_ms"]
                    })

                    log_message(f"Target {target['service']}/{target['endpointName']} completed with HTTP {res['HttpCode']}, curl exit {res['ExitCode']}, total {res['TimeTotalMs']} ms")

            except Exception as e:
                failure_count += 1
                log_message(f"Target {target.get('service')}/{target.get('endpointName')} failed: {e}", "ERROR")

                if target_type == "speedtest":
                    fail_dur = round((time.perf_counter() - target_start_perf) * 1000, 2)
                    fail_res = get_speedtest_failure_target_result(target, config, str(e), fail_dur)
                    timestamp_ms = int(time.time() * 1000)
                    lines.append(build_influx_line(fail_res["Measurement"], fail_res["Tags"], fail_res["Fields"], timestamp_ms))
                    target_reports.append(fail_res["Report"])
                else:
                    tags = {
                        "probe_id": probe_cfg.get("probeId", "unknown"),
                        "probe_type": probe_cfg.get("probeType", "python"),
                        "site": probe_cfg.get("site", "unknown"),
                        "environment": probe_cfg.get("environment", "unknown"),
                        "service": target["service"],
                        "endpoint_name": target["endpointName"],
                        "probe_version": probe_cfg.get("probeVersion", PROBE_VERSION),
                        "router_brand": probe_cfg.get("router_brand", "unknown"),
                        "router_model": probe_cfg.get("router_model", "unknown"),
                        "connection_type": probe_cfg.get("connection_type", "unknown")
                    }
                    fields = {
                        "available": False,
                        "http_status": 0,
                        "curl_exit_code": -1,
                        "time_namelookup_ms": 0.0,
                        "time_connect_ms": 0.0,
                        "time_appconnect_ms": 0.0,
                        "time_starttransfer_ms": 0.0,
                        "time_total_ms": 0.0,
                        "size_download_bytes": 0.0,
                        "num_redirects": 0,
                        "http_version": "",
                        "remote_ip": "",
                        "error_class": "probe_exception",
                        "error_detail": str(e),
                        "effective_url": target["url"],
                        "run_duration_ms": round((time.perf_counter() - target_start_perf) * 1000, 2)
                    }
                    timestamp_ms = int(time.time() * 1000)
                    lines.append(build_influx_line(probe_run.get("measurement", "qoe_http_check"), tags, fields, timestamp_ms))
                    target_reports.append({
                        "service": target["service"],
                        "endpoint_name": target["endpointName"],
                        "url": target["url"],
                        "type": "http",
                        "available": False,
                        "http_status": 0,
                        "curl_exit_code": -1,
                        "time_namelookup_ms": 0.0,
                        "time_connect_ms": 0.0,
                        "time_appconnect_ms": 0.0,
                        "time_starttransfer_ms": 0.0,
                        "time_total_ms": 0.0,
                        "size_download_bytes": 0.0,
                        "num_redirects": 0,
                        "http_version": "",
                        "remote_ip": "",
                        "error_class": "probe_exception",
                        "error_detail": str(e),
                        "effective_url": target["url"],
                        "run_duration_ms": fields["run_duration_ms"]
                    })

        # Write Target Metrics to InfluxDB
        if write_attempted and lines:
            base_url = get_optional_str(influx_cfg, "baseUrl").rstrip('/')
            org = urllib.parse.quote(get_optional_str(influx_cfg, "org"))
            bucket = urllib.parse.quote(get_optional_str(influx_cfg, "bucket"))
            precision = urllib.parse.quote(get_optional_str(influx_cfg, "precision", "ms"))
            write_uri = f"{base_url}/api/v2/write?org={org}&bucket={bucket}&precision={precision}"

            payload = "\n".join(lines)
            write_to_influx(write_uri, token_value, payload, float(influx_write_timeout))
            write_succeeded = True
            log_message(f"Wrote {len(lines)} measurement lines to InfluxDB.")

        elif write_attempted:
            log_message("No target measurements collected. Skipping InfluxDB write.", "WARN")
        else:
            log_message("SkipInfluxWrite flag set. Metrics were not sent to InfluxDB.", "WARN")

        # Build Probe Run Summary Line
        probe_run_duration = round((time.perf_counter() - script_start_perf) * 1000, 2)
        probe_fields = {
            "success_count": success_count,
            "failure_count": failure_count,
            "run_duration_ms": probe_run_duration,
            "write_attempted": write_attempted,
            "write_succeeded": write_succeeded,
            "target_count": len(enabled_targets)
        }
        probe_tags = {
            "probe_id": probe_cfg.get("probeId", "unknown"),
            "probe_type": probe_cfg.get("probeType", "python"),
            "site": probe_cfg.get("site", "unknown"),
            "environment": probe_cfg.get("environment", "unknown"),
            "probe_version": probe_cfg.get("probeVersion", PROBE_VERSION),
            "router_brand": probe_cfg.get("router_brand", "unknown"),
            "router_model": probe_cfg.get("router_model", "unknown"),
            "connection_type": probe_cfg.get("connection_type", "unknown")
        }
        probe_timestamp_ms = int(time.time() * 1000)
        summary_line = build_influx_line(probe_run.get("probeMeasurement", "qoe_probe_run"), probe_tags, probe_fields, probe_timestamp_ms)

        # Write Summary Line to InfluxDB
        if write_attempted and write_succeeded:
            write_to_influx(write_uri, token_value, summary_line, float(influx_write_timeout))

        # Append to line list for local reports
        lines.append(summary_line)

        # InfluxDB line protocol lines are collected and sent directly to InfluxDB; no print loop is required

        log_message(f"QoE probe finished. Success={success_count}, Failure={failure_count}, Duration={probe_run_duration} ms")

    except Exception as e:
        threw = True
        fatal_error_message = str(e)
        log_message(f"Fatal exception: {e}", "ERROR")
        sys.exit(1)

    finally:
        # Write Run Report JSON if path is provided
        if args.run_report_path:
            completed_time = datetime.datetime.utcnow()
            completed_time_str = completed_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            started_time_str = script_start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            report_data = {
                "started_at_utc": started_time_str,
                "completed_at_utc": completed_time_str,
                "config_path": str(config_path),
                "log_path": str(log_path_global) if log_path_global else "",
                "probe_id": probe_cfg.get("probeId", "unknown"),
                "probe_type": probe_cfg.get("probeType", "python"),
                "site": probe_cfg.get("site", "unknown"),
                "environment": probe_cfg.get("environment", "unknown"),
                "measurement": probe_run.get("measurement", "qoe_http_check"),
                "probe_measurement": probe_run.get("probeMeasurement", "qoe_probe_run"),
                "skip_influx_write": args.skip_influx_write,
                "write_attempted": write_attempted,
                "write_succeeded": write_succeeded,
                "write_uri": write_uri,
                "success_count": success_count,
                "failure_count": failure_count,
                "target_count": len(enabled_targets),
                "run_duration_ms": round((time.perf_counter() - script_start_perf) * 1000, 2),
                "start_jitter_seconds": run_jitter,
                "target_delay_milliseconds": target_delay_ms,
                "threw": threw,
                "fatal_error": fatal_error_message,
                "targets": target_reports
            }

            try:
                report_file = resolve_from_base(repo_root, args.run_report_path)
                report_file.parent.mkdir(parents=True, exist_ok=True)
                report_file.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
            except Exception as e:
                log_message(f"Failed to write run report file: {e}", "ERROR")


if __name__ == "__main__":
    main()
