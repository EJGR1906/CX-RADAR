#!/usr/bin/env python3
"""
CX-Radar: monitor liviano para detectar fallas de la conexión en minutos.

Corre cada minuto (registrar con `register_qoe_task.py --script heartbeat
--interval-minutes 1`). No mide velocidad. En cada corrida:

- Muestrea durante `windowSeconds` (45 s) una conexión TCP cada
  `sampleIntervalSeconds` (5 s) a cada destino: servidores del proveedor,
  destinos externos por nombre y anclas por IP (no dependen del DNS).
- Consulta el DNS del sistema y DNS públicos directamente por UDP.
- Pide una página de verificación (`generate_204`) para saber si internet
  responde de verdad o hay un portal cautivo o proxy en el medio.
- Revisa servicios externos (por ejemplo Outlook) con una petición HTTPS.

Diagnóstico de red (uno por corrida):
- sin_red_local:         el equipo de la sonda no tiene red (cable o Wi-Fi).
- caida_router_local:    no responde el router de la sonda.
- caida_acceso:          no responde ni la red del proveedor ni internet.
- caida_transito:        la red del proveedor responde, internet no.
- falla_dns:             hay conexión por IP pero los nombres no resuelven.
- internet_interceptado: conecta, pero un portal o proxy responde en lugar de internet.
- microcortes:           la conexión se cayó por segundos dentro de la ventana y volvió.
- degradado:             responde con latencia o pérdida fuera de umbral.
- ok

Los servicios externos tienen su propio estado y sus propios avisos, y solo se
evalúan cuando la red de la sonda funciona.

Alertas: una caída avisa tras `failThreshold` corridas seguidas (2), un
`degradado` o `microcortes` tras `degradedFailThreshold` (5) y el incidente se
cierra tras `recoverThreshold` corridas buenas (5). Si la caída impide enviar
el aviso, no se manda atrasado: al volver se envía un solo RECUPERADO con el
diagnóstico, la hora de inicio, la duración y el número de cortes. El aviso en
el momento de la caída lo da Grafana Cloud (`setup_grafana_alert.py`). Las
métricas que no se pudieron escribir en InfluxDB se guardan y se reenvían.

Requisitos: Python >= 3.8, solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import http.client
import json
import os
import random
import re
import socket
import ssl
import struct
import subprocess  # nosec B404 - solo comandos fijos del sistema
import sys
import threading
import time
import traceback
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qoe_config  # noqa: E402
import qoe_probe  # noqa: E402
import qoe_telegram  # noqa: E402
import qoe_throughput  # noqa: E402

DEFAULT_TARGETS = [
    {"name": "cloudflare", "host": "1.1.1.1", "port": 443, "kind": "external"},
    {"name": "google-dns", "host": "8.8.8.8", "port": 443, "kind": "external"},
    {"name": "quad9", "host": "9.9.9.9", "port": 443, "kind": "external"},
    {"name": "google", "host": "www.google.com", "port": 443, "kind": "external"},
]
DEFAULT_DNS_NAMES = ["www.google.com", "www.youtube.com", "www.netflix.com"]
DEFAULT_DNS_SERVERS = [{"name": "cloudflare", "ip": "1.1.1.1"}, {"name": "google", "ip": "8.8.8.8"}]
DEFAULT_CONNECTIVITY_CHECKS = [
    {"url": "http://connectivitycheck.gstatic.com/generate_204", "expectedStatus": 204},
    {"url": "https://www.google.com/generate_204", "expectedStatus": 204},
]
DEFAULT_MAX_LATENCY = {"inter": 40.0, "isp": 40.0, "external": 150.0}
ISP_KINDS = ("inter", "isp")

# Los códigos 0-4 ya están en InfluxDB y en los tableros: no se cambian.
STATUS_CODES = {"ok": 0, "degradado": 1, "caida_transito": 2, "caida_acceso": 3, "caida_router_local": 4,
                "falla_dns": 5, "microcortes": 6, "internet_interceptado": 7, "sin_red_local": 8}
# Gravedad para decidir si un estado "empeora" a otro (independiente del código).
SEVERITY = {"ok": 0, "degradado": 1, "parcial": 1, "microcortes": 2, "caido": 2, "internet_interceptado": 3,
            "falla_dns": 4, "caida_transito": 5, "caida_acceso": 6, "caida_router_local": 7, "sin_red_local": 7}
SOFT_STATUSES = ("degradado", "microcortes")
NO_INTERNET_STATUSES = ("caida_transito", "caida_acceso", "caida_router_local", "sin_red_local", "falla_dns",
                        "internet_interceptado")
_STATUS_TEXT = {
    "ok": "Servicio normal",
    "degradado": "Servicio degradado (latencia o pérdida altas)",
    "microcortes": "Microcortes: la conexión se cayó por segundos y volvió",
    "internet_interceptado": "Hay conexión, pero internet no responde de verdad (portal cautivo, proxy o bloqueo)",
    "falla_dns": "Falla de DNS: hay conexión, pero los nombres de las páginas no resuelven",
    "caida_transito": "Falla de salida a internet: la red de {isp} responde, internet no",
    "caida_acceso": "Caída del acceso: no responde ni la red de {isp} ni internet (PON, OLT, agregación o BNG)",
    "caida_router_local": "No responde el router de la sonda (falla local del punto de medición)",
    "sin_red_local": "El equipo de la sonda no tiene red (cable o Wi-Fi desconectado): falla local, no del proveedor",
}
MAX_BUFFER_LINES = 20000
RECENT_ROUNDS = 3          # rondas finales que definen si un destino responde "ahora"
LOCK_STALE_SECONDS = 150
HARD_DEADLINE_SECONDS = 110
NET_CACHE_SECONDS = 600
INT_STATE_KEYS = ("bad_count", "good_count", "hard_count", "cuts", "bad_since", "last_bad")


def status_text(status: str, isp: str = "") -> str:
    return _STATUS_TEXT.get(status, status).format(isp=isp or "el proveedor")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt_time(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%d/%m %H:%M")


def _fmt_duration(ms: int) -> str:
    minutes = max(1, round(ms / 60000))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


# ---------------------------------------------------------------------------
# Muestreo de destinos
# ---------------------------------------------------------------------------
def addr_from_ip(ip: str, port: int) -> Tuple[int, tuple]:
    return (socket.AF_INET6, (ip, port, 0, 0)) if ":" in ip else (socket.AF_INET, (ip, port))


def resolve_targets(targets: List[Dict[str, Any]], ip_cache: Dict[str, str],
                    resolver: Optional[Callable[..., Optional[tuple]]] = None,
                    timeout_s: float = 3.0) -> List[Dict[str, Any]]:
    """Resuelve cada destino una vez. Si el DNS falla usa la última IP conocida.

    Así un destino por nombre se puede seguir probando con el DNS caído, y la
    falla se diagnostica como DNS y no como caída de la red.
    """
    resolver = resolver or qoe_throughput.resolve_host

    def one(t: Dict[str, Any]) -> Dict[str, Any]:
        host, port = str(t["host"]), int(t.get("port", 443))
        addr = resolver(host, port, timeout_s)
        cached = False
        if addr is None and ip_cache.get(host):
            addr, cached = addr_from_ip(ip_cache[host], port), True
        return {**t, "port": port, "addr": addr, "ip_cached": cached}

    if not targets:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as ex:
        resolved = list(ex.map(one, targets))
    for r in resolved:
        ip = r["addr"][1][0] if r["addr"] is not None else ""
        if ip and not r["ip_cached"] and ip != str(r["host"]):
            ip_cache[str(r["host"])] = ip
    return resolved


def sample_rounds(addrs: Sequence[Optional[tuple]], rounds: int, interval_s: float, timeout_s: float,
                  connect: Optional[Callable[[tuple, float], Optional[float]]] = None,
                  sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic) -> List[List[Optional[float]]]:
    """Una conexión por destino en cada ronda. Devuelve rondas x destinos (ms o None)."""
    connect = connect or qoe_throughput.tcp_connect_ms
    matrix: List[List[Optional[float]]] = []
    if not addrs:
        return matrix
    start = clock()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(addrs)) as ex:
        for i in range(max(1, rounds)):
            wait = start + i * interval_s - clock()
            if wait > 0:
                sleep(wait)
            futures = [ex.submit(connect, a, timeout_s) if a is not None else None for a in addrs]
            matrix.append([f.result() if f is not None else None for f in futures])
    return matrix


def summarize_target(t: Dict[str, Any], samples: Sequence[Optional[float]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    kind = t.get("kind", "external")
    stats = qoe_throughput.summarize_latency(samples)
    max_lat = float(t.get("maxLatencyMs", cfg.get("maxLatencyMs", {}).get(kind, DEFAULT_MAX_LATENCY.get(kind, 150.0))))
    max_loss = float(t.get("maxLossPercentage", cfg.get("maxLossPercentage", 20.0)))
    # "Responde" se decide con las últimas rondas: describe el estado al final de la ventana.
    reachable = any(s is not None for s in list(samples)[-RECENT_ROUNDS:])
    degraded = reachable and (stats["LatencyMs"] > max_lat or stats["LossPercentage"] > max_loss)
    return {"name": t["name"], "host": t.get("host", ""), "kind": kind, "reachable": reachable, "degraded": degraded,
            "latency_ms": stats["LatencyMs"], "p95_ms": stats["P95Ms"], "jitter_ms": stats["JitterMs"],
            "loss_pct": stats["LossPercentage"], "max_latency_ms": max_lat,
            "resolved": t.get("addr") is not None, "ip_cached": bool(t.get("ip_cached"))}


def find_blackouts(matrix: Sequence[Sequence[Optional[float]]], addrs: Sequence[Optional[tuple]]) -> Dict[str, int]:
    """Rondas en las que no respondió ningún destino (con dirección conocida)."""
    usable = [i for i, a in enumerate(addrs) if a is not None]
    total = longest = run = 0
    for row in matrix:
        if usable and all(row[i] is None for i in usable):
            total += 1
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return {"rounds": total, "longest": longest, "all": int(bool(matrix) and total == len(matrix))}


# ---------------------------------------------------------------------------
# Red local, DNS y verificación de internet
# ---------------------------------------------------------------------------
def has_default_route() -> bool:
    """True si el sistema tiene por dónde salir a internet (no envía ningún paquete)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53))
        return not s.getsockname()[0].startswith("127.")
    except OSError:
        return False
    finally:
        s.close()


def get_system_dns_servers() -> List[str]:
    servers: List[str] = []
    try:
        if os.name == "nt":
            out = subprocess.run(  # nosec B603 B607 - comando fijo
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-DnsClientServerAddress -AddressFamily IPv4).ServerAddresses"],
                capture_output=True, text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            servers = [ln.strip() for ln in out.splitlines()]
        else:
            for ln in Path("/etc/resolv.conf").read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = ln.split()
                if len(parts) >= 2 and parts[0] == "nameserver":
                    servers.append(parts[1])
    except Exception:
        return []
    unique: List[str] = []
    for s in servers:
        if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", s) and s not in unique:
            unique.append(s)
    return unique[:3]


def get_local_network(state: Dict[str, Any], now_ms: int, force: bool = False) -> Dict[str, Any]:
    """Puerta de enlace y DNS del sistema, con caché: consultarlos lanza procesos del sistema."""
    net = state.get("net") if isinstance(state.get("net"), dict) else {}
    fresh = net.get("gw") and now_ms - int(net.get("ts", 0)) < NET_CACHE_SECONDS * 1000
    if force or not fresh:
        net = {"gw": qoe_probe.get_default_gateway(), "dns": get_system_dns_servers(), "ts": now_ms}
        state["net"] = net
    return net


def check_gateway(gw_ip: str) -> Dict[str, Any]:
    g = qoe_probe.get_ping_burst_stats(gw_ip, 3, 500)
    return {"present": True, "reachable": g["SuccessfulReplies"] > 0, "latency_ms": g["LatencyMs"]}


def dns_query(server: str, name: str, timeout_s: float = 2.0) -> Dict[str, Any]:
    """Consulta A directa por UDP a un servidor DNS (sin la caché del sistema)."""
    tid = random.randint(0, 0xFFFF)  # nosec B311 - identificador de consulta, no es un secreto
    qname = b"".join(bytes([len(p)]) + p.encode("ascii", "ignore") for p in name.strip(".").split(".")) + b"\x00"
    packet = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)
    sock = socket.socket(socket.AF_INET6 if ":" in server else socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout_s)
    t0 = time.perf_counter()
    try:
        sock.sendto(packet, (server, 53))
        data, _ = sock.recvfrom(1024)
        ms = round((time.perf_counter() - t0) * 1000, 2)
        if len(data) < 12:
            return {"ok": False, "ms": 0.0}
        rid, flags, _, ancount = struct.unpack(">HHHH", data[:8])
        return {"ok": rid == tid and (flags & 0x000F) == 0 and ancount > 0, "ms": ms}
    except OSError:
        return {"ok": False, "ms": 0.0}
    finally:
        sock.close()


def check_dns_server(server: Dict[str, Any], names: Sequence[str], timeout_s: float = 2.0,
                     query: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    query = query or dns_query
    for name in list(names)[:2]:
        r = query(server["ip"], name, timeout_s)
        if r["ok"]:
            return {**server, "ok": True, "ms": r["ms"]}
    return {**server, "ok": False, "ms": 0.0}


def check_dns(name: str, timeout_s: float = 4.0) -> Dict[str, Any]:
    """Resolución por el sistema operativo (la que usan las aplicaciones)."""
    t0 = time.perf_counter()
    ok = qoe_throughput.resolve_host(name, 443, timeout_s) is not None
    return {"name": name, "ok": ok, "ms": round((time.perf_counter() - t0) * 1000, 2) if ok else 0.0}


def summarize_dns(os_checks: List[Dict[str, Any]], servers: List[Dict[str, Any]]) -> Dict[str, Any]:
    system = [s for s in servers if s.get("kind") == "system"]
    public = [s for s in servers if s.get("kind") != "system"]
    os_ok = any(d["ok"] for d in os_checks) if os_checks else None
    direct_ok = any(s["ok"] for s in system) if system else None
    # Se declara falla solo si fallan la consulta directa y la del sistema operativo:
    # evita falsas alarmas con DNS cifrado (DoH) o con un router que no acepta consultas directas.
    if os_ok is None and direct_ok is None:
        system_ok: Optional[bool] = None
    else:
        system_ok = bool(os_ok) or bool(direct_ok)
    return {"system_ok": system_ok, "public_ok": any(s["ok"] for s in public) if public else None,
            "os_ok": os_ok, "servers": servers}


def http_get(url: str, timeout_s: float = 8.0, verify_tls: bool = True, user_agent: str = "CX-Radar/heartbeat") -> Dict[str, Any]:
    """GET sin seguir redirecciones. Devuelve el código y el tipo de error, nunca lanza."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    t0 = time.perf_counter()
    result = {"status": 0, "error": "", "ms": 0.0, "body_len": 0}
    conn: Optional[http.client.HTTPConnection] = None
    try:
        if parts.scheme == "https":
            conn = http.client.HTTPSConnection(host, parts.port or 443, timeout=timeout_s,
                                               context=qoe_throughput._ssl_context(verify_tls))
        elif parts.scheme == "http":
            conn = http.client.HTTPConnection(host, parts.port or 80, timeout=timeout_s)
        else:
            raise ValueError("solo http o https")
        conn.request("GET", path, headers={"User-Agent": user_agent, "Accept": "*/*", "Connection": "close"})
        resp = conn.getresponse()
        result["status"] = resp.status
        result["body_len"] = len(resp.read(4096))
    except socket.gaierror:
        result["error"] = "dns"
    except ssl.SSLError:
        result["error"] = "tls"
    except (socket.timeout, TimeoutError):
        result["error"] = "timeout"
    except (ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected, BrokenPipeError):
        result["error"] = "reset"
    except (OSError, http.client.HTTPException, ValueError):
        result["error"] = "connect"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    result["ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return result


def verify_internet(checks: List[Dict[str, Any]], timeout_s: float = 5.0,
                    get: Optional[Callable[..., Dict[str, Any]]] = None) -> Optional[bool]:
    """True si alguna página de verificación responde lo esperado. None si no hay ninguna configurada."""
    if not checks:
        return None
    get = get or http_get
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(checks)) as ex:
        results = list(ex.map(lambda c: get(c["url"], timeout_s), checks))
    return any(r["status"] == int(c.get("expectedStatus", 204)) and not r["error"] for c, r in zip(checks, results))


# ---------------------------------------------------------------------------
# Servicios externos
# ---------------------------------------------------------------------------
def check_service(check: Dict[str, Any], timeout_s: float = 8.0,
                  get: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    r = (get or http_get)(check["url"], timeout_s)
    expected = [int(c) for c in check.get("expectedHttpCodes", [200])]
    available = not r["error"] and r["status"] in expected
    error = r["error"] or ("" if available else "http_status")
    reason = "" if available else (f"HTTP {r['status']}" if error == "http_status" else
                                   {"dns": "no resuelve el nombre", "tls": "falla de certificado/TLS",
                                    "timeout": "sin respuesta (timeout)", "reset": "conexión cortada",
                                    "connect": "no conecta"}.get(error, error))
    return {"service": check["service"], "name": check["name"], "available": available, "http_status": r["status"],
            "time_total_ms": r["ms"], "error_class": error, "reason": reason}


def classify_services(results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    services: Dict[str, Dict[str, Any]] = {}
    for r in results:
        s = services.setdefault(r["service"], {"total": 0, "failed": []})
        s["total"] += 1
        if not r["available"]:
            s["failed"].append(r)
    for s in services.values():
        s["status"] = "ok" if not s["failed"] else ("caido" if len(s["failed"]) == s["total"] else "parcial")
    return services


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------
def classify(gateway: Optional[Dict[str, Any]], checks: List[Dict[str, Any]], dns: Optional[Dict[str, Any]] = None,
             verified: Optional[bool] = None, blackout: Optional[Dict[str, int]] = None,
             interval_s: float = 5.0) -> Dict[str, Any]:
    isp = [c for c in checks if c["kind"] in ISP_KINDS]
    external = [c for c in checks if c["kind"] not in ISP_KINDS]
    isp_ok = any(c["reachable"] for c in isp) if isp else None
    ext_ok = any(c["reachable"] for c in external) if external else None
    degraded = [c["name"] for c in checks if c["degraded"]]
    unreachable = [c["name"] for c in checks if not c["reachable"]]
    blackout = blackout or {"rounds": 0, "longest": 0, "all": 0}
    notes: List[str] = []
    anything_up = bool(isp_ok) or bool(ext_ok)

    if checks and not anything_up:
        if gateway is not None and gateway.get("present") is False:
            status = "sin_red_local"
        elif gateway is not None and not gateway.get("reachable", True):
            status = "caida_router_local"
        else:
            status = "caida_acceso"
    elif isp_ok and ext_ok is False:
        status = "caida_transito"
    elif dns is not None and dns.get("system_ok") is False:
        status = "falla_dns"
        if dns.get("public_ok"):
            notes.append("Los DNS públicos (1.1.1.1, 8.8.8.8) sí responden: falla el DNS configurado en la sonda.")
        elif dns.get("public_ok") is False:
            notes.append("Tampoco responden los DNS públicos: las consultas DNS no salen.")
    elif verified is False:
        status = "internet_interceptado"
    elif blackout["longest"] >= 2 or blackout["rounds"] >= 2:
        status = "microcortes"
        notes.append(f"Sin respuesta de ningún destino durante ~{int(blackout['rounds'] * interval_s)} s de la ventana.")
    elif degraded or unreachable:
        status = "degradado"
    else:
        status = "ok"
    return {"status": status, "degraded": degraded, "unreachable": unreachable, "notes": notes}


# ---------------------------------------------------------------------------
# Estado de alertas
# ---------------------------------------------------------------------------
def update_alert_state(state: Dict[str, Any], status: str, now_ms: int, fail_threshold: int,
                       recover_threshold: int, soft_fail_threshold: Optional[int] = None) -> Optional[str]:
    """Actualiza el estado y devuelve el mensaje a enviar: 'alert', 'escalate', 'recovery' o None.

    Las caídas avisan tras `fail_threshold` corridas seguidas; los estados leves
    (degradado, microcortes) tras `soft_fail_threshold`. Un incidente ya avisado
    que empeora se avisa de inmediato.
    """
    soft_threshold = soft_fail_threshold or fail_threshold
    sev = lambda s: SEVERITY.get(s, 1)  # noqa: E731
    action = None
    if status != "ok":
        if state.get("bad_count", 0) == 0:
            state["bad_since"] = now_ms
            state["cuts"] = 0
            state["worst"] = status
        state["bad_count"] = state.get("bad_count", 0) + 1
        state["good_count"] = 0
        state["last_bad"] = now_ms
        hard = status not in SOFT_STATUSES
        prev_hard = state.get("hard_count", 0)
        state["hard_count"] = prev_hard + 1 if hard else 0
        if hard and prev_hard == 0:
            state["cuts"] = state.get("cuts", 0) + 1
        if sev(status) > sev(state.get("worst", "ok")):
            state["worst"] = status
        if state.get("alerted"):
            ready = True
        elif hard:
            ready = state["hard_count"] >= fail_threshold
        else:
            ready = state["bad_count"] >= soft_threshold
        if ready:
            if not state.get("alerted"):
                action = "alert"
            elif sev(status) > sev(state.get("alert_status", "ok")):
                action = "escalate"
            if action:
                state["alerted"] = True
                state["alert_status"] = status
    else:
        state["good_count"] = state.get("good_count", 0) + 1
        state["hard_count"] = 0
        if state.get("alerted") and state["good_count"] >= recover_threshold:
            action = "recovery"
            state["recovered_from"] = state.get("worst") or state.get("alert_status", "ok")
            state["alerted"] = False
            state["alert_status"] = "ok"
        if state["good_count"] >= recover_threshold or not state.get("alerted"):
            state["bad_count"] = 0
    state["last_status"] = status
    return action


def _recovery_lines(state: Dict[str, Any], now_ms: int, interval_ms: int = 60000) -> List[str]:
    since = state.get("bad_since", now_ms)
    last_bad = state.get("last_bad")
    if last_bad is None:
        return [f"Duración de la falla: {_fmt_duration(now_ms - since)} (desde {_fmt_time(since)})"]
    lines = [f"Duración de la falla: {_fmt_duration(last_bad - since + interval_ms)} "
             f"(desde {_fmt_time(since)}, estable desde {_fmt_time(last_bad + interval_ms)})"]
    if state.get("cuts", 0) > 1:
        lines.append(f"Cortes durante el incidente: {state['cuts']}")
    return lines


def build_message(action: str, probe_id: str, site: str, status: str, summary: Dict[str, Any],
                  checks: List[Dict[str, Any]], state: Dict[str, Any], now_ms: int, isp: str = "") -> str:
    header = f"CX-Radar | sonda {probe_id} ({site})"
    if action == "recovery":
        lines = [header, f"RECUPERADO a las {_fmt_time(now_ms)}"]
        if state.get("alert_undelivered"):
            diag = status_text(state.get("recovered_from", ""), isp) if state.get("recovered_from") else "no documentado"
            lines += ["La falla no se pudo avisar en el momento: la sonda estaba sin conexión.",
                      f"Diagnóstico: {diag}"]
        elif state.get("recovered_from") and state.get("recovered_from") != state.get("first_alert_status"):
            lines.append(f"Peor estado: {status_text(state['recovered_from'], isp)}")
        return "\n".join(lines + _recovery_lines(state, now_ms))
    title = "FALLA" if action == "alert" else "EMPEORA"
    lines = [header, f"{title}: {status_text(status, isp)}", f"Detectado: {_fmt_time(state.get('bad_since', now_ms))}"]
    lines += summary.get("notes", [])
    for c in checks:
        if not c["reachable"]:
            lines.append(f"- {c['name']}: sin respuesta")
        elif c["degraded"]:
            lines.append(f"- {c['name']}: {c['latency_ms']} ms (umbral {c['max_latency_ms']:.0f}), pérdida {c['loss_pct']} %")
    return "\n".join(lines)


def build_service_message(action: str, probe_id: str, site: str, service: str, info: Dict[str, Any],
                          state: Dict[str, Any], now_ms: int) -> str:
    header = f"CX-Radar | sonda {probe_id} ({site})"
    if action == "recovery":
        return "\n".join([header, f"SERVICIO RECUPERADO: {service} a las {_fmt_time(now_ms)}"] + _recovery_lines(state, now_ms))
    failed, total = info.get("failed", []), info.get("total", 0)
    word = "CAÍDO" if info.get("status") == "caido" else "CON FALLAS"
    lines = [header, f"SERVICIO EXTERNO {word}: {service} ({len(failed)} de {total} pruebas fallan)",
             f"Detectado: {_fmt_time(state.get('bad_since', now_ms))}",
             "La red de la sonda e internet responden normal: la falla es del servicio, no de la conexión."]
    lines += [f"- {f['name']}: {f['reason']}" for f in failed]
    return "\n".join(lines)


def notify(action: Optional[str], state: Dict[str, Any], build: Callable[[str], str],
           send: Callable[[str], bool], pending: Optional[List[str]] = None) -> None:
    """Envía el aviso de la corrida.

    Un aviso de falla que no sale (la sonda está sin conexión) no se guarda para
    mandarlo atrasado: se marca `alert_undelivered` y la recuperación lo resume.
    Solo el mensaje de recuperación queda pendiente si tampoco se puede enviar.
    """
    if not action:
        return
    msg = build(action)
    sent = send(msg)
    if action in ("alert", "escalate"):
        if action == "alert":
            state["first_alert_status"] = state.get("alert_status")
            state["alert_undelivered"] = not sent
        elif sent:
            state["alert_undelivered"] = False
        if not sent:
            qoe_probe.log_message(f"Heartbeat: Telegram no disponible, se resumirá al recuperar: {qoe_telegram.LAST_ERROR}", "WARNING")
        return
    if not sent:
        qoe_probe.log_message(f"Heartbeat: Telegram no disponible, la recuperación queda pendiente: {qoe_telegram.LAST_ERROR}", "WARNING")
        (pending if pending is not None else state.setdefault("pending", [])).append(msg)
    for key in ("alert_undelivered", "recovered_from", "first_alert_status"):
        state.pop(key, None)


def flush_pending(state: Dict[str, Any], creds: Dict[str, str], max_messages: int = 3) -> None:
    pending = state.get("pending", [])
    remaining = []
    for i, msg in enumerate(pending):
        if i >= max_messages or not qoe_telegram.send_message(f"(enviado con retraso)\n{msg}", creds, timeout=5.0):
            remaining.append(msg)
    state["pending"] = remaining[-50:]


# ---------------------------------------------------------------------------
# Persistencia: estado, bloqueo, búfer de InfluxDB, logs
# ---------------------------------------------------------------------------
def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def sanitize_state(raw: Any) -> Dict[str, Any]:
    """Descarta lo que no tenga el tipo esperado: un estado dañado no puede tumbar las alertas."""
    state = dict(raw) if isinstance(raw, dict) else {}
    for key in INT_STATE_KEYS:
        if key in state and (isinstance(state[key], bool) or not isinstance(state[key], int)):
            state.pop(key)
    if "alerted" in state and not isinstance(state["alerted"], bool):
        state.pop("alerted")
    for key in ("alert_status", "worst", "recovered_from", "first_alert_status", "last_status"):
        if key in state and not isinstance(state[key], str):
            state.pop(key)
    state["pending"] = [m for m in state.get("pending", []) if isinstance(m, str)] if isinstance(state.get("pending"), list) else []
    services = state.get("services") if isinstance(state.get("services"), dict) else {}
    state["services"] = {k: sanitize_service_state(v) for k, v in services.items()}
    cache = state.get("ip_cache") if isinstance(state.get("ip_cache"), dict) else {}
    state["ip_cache"] = {k: v for k, v in cache.items() if isinstance(k, str) and isinstance(v, str)}
    if not isinstance(state.get("net"), dict):
        state.pop("net", None)
    return state


def sanitize_service_state(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    s = dict(raw)
    for key in INT_STATE_KEYS:
        if key in s and (isinstance(s[key], bool) or not isinstance(s[key], int)):
            s.pop(key)
    if "alerted" in s and not isinstance(s["alerted"], bool):
        s.pop("alerted")
    return s


def load_state(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return sanitize_state({})
    try:
        return sanitize_state(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:
        qoe_probe.log_message(f"Heartbeat: estado ilegible, se reinicia ({e})", "WARNING")
        return sanitize_state({})


def acquire_lock(path: Path, stale_seconds: float = LOCK_STALE_SECONDS) -> bool:
    """Evita dos corridas a la vez (cron y launchd no lo impiden). Un bloqueo viejo se ignora."""
    for _ in range(2):
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime < stale_seconds:
                    return False
                path.unlink()
            except OSError:
                return False
        except OSError:
            return True  # sin permiso para bloquear: mejor medir que no medir
    return False


def release_lock(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _influx_status(error: Exception) -> int:
    m = re.search(r"Status code: (\d+)", str(error))
    return int(m.group(1)) if m else 0


def write_influx(lines: List[str], config: Dict[str, Any], config_dir: Path, buffer_path: Path,
                 writer: Optional[Callable[[str, str, str, float], Any]] = None,
                 token: Optional[str] = None) -> bool:
    """Escribe las líneas nuevas y reenvía las guardadas.

    Si InfluxDB rechaza las guardadas por contenido (HTTP 400/422) se apartan en
    un archivo `.rejected`: de otro modo una línea mala bloquearía todos los
    envíos siguientes.
    """
    writer = writer or qoe_probe.write_to_influx
    influx = config.get("influx", {})
    timeout = min(float(influx.get("writeTimeoutSeconds", 15)), 8.0)
    buffered: List[str] = []
    if buffer_path.is_file():
        buffered = [ln for ln in buffer_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        if token is None:
            token = qoe_probe.get_influx_token(influx, config_dir, quiet=True)
        url = (f"{influx['baseUrl'].rstrip('/')}/api/v2/write?org={urllib.parse.quote(str(influx['org']))}"
               f"&bucket={urllib.parse.quote(str(influx['bucket']))}&precision=ms")
    except Exception as e:
        qoe_probe.log_message(f"Heartbeat: no se pudo escribir en InfluxDB, se guarda para reenviar: {e}", "WARNING")
        write_atomic(buffer_path, "\n".join((buffered + lines)[-MAX_BUFFER_LINES:]) + "\n")
        return False

    if buffered:
        try:
            writer(url, token, "\n".join(buffered), timeout)
            buffered = []
        except Exception as e:
            if _influx_status(e) in (400, 422):
                rejected = buffer_path.with_name(f"{buffer_path.stem}.rejected-{int(time.time())}{buffer_path.suffix}")
                write_atomic(rejected, "\n".join(buffered) + "\n")
                qoe_probe.log_message(f"Heartbeat: InfluxDB rechazó {len(buffered)} líneas guardadas; se apartan en {rejected.name}: {e}", "ERROR")
                buffered = []
            else:
                qoe_probe.log_message(f"Heartbeat: no se pudo escribir en InfluxDB, se guarda para reenviar: {e}", "WARNING")
                write_atomic(buffer_path, "\n".join((buffered + lines)[-MAX_BUFFER_LINES:]) + "\n")
                return False
    try:
        if lines:
            writer(url, token, "\n".join(lines), timeout)
        if buffer_path.is_file():
            buffer_path.unlink()
        return True
    except Exception as e:
        if _influx_status(e) in (400, 422):
            qoe_probe.log_message(f"Heartbeat: InfluxDB rechazó las líneas de esta corrida (no se reintentan): {e}", "ERROR")
            if buffer_path.is_file():
                buffer_path.unlink()
            return False
        qoe_probe.log_message(f"Heartbeat: no se pudo escribir en InfluxDB, se guarda para reenviar: {e}", "WARNING")
        write_atomic(buffer_path, "\n".join(lines[-MAX_BUFFER_LINES:]) + "\n")
        return False


def rotate_logs(log_dir: Path, retention_days: int = 30) -> int:
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for pattern in ("qoe-heartbeat-*.log", "heartbeat-buffer.rejected-*.lp"):
        for item in log_dir.glob(pattern):
            try:
                if item.stat().st_mtime < cutoff:
                    item.unlink()
                    removed += 1
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace, repo_root: Path, log_dir: Path) -> int:
    config_path = Path(args.config_path).resolve() if args.config_path else repo_root / "config" / "probe-catalog.json"
    config = qoe_config.load_config(config_path)
    hb = config.get("heartbeat", {})
    probe = config.get("probe", {})
    probe_id = probe.get("probeId", "unknown")
    site = probe.get("site", "unknown")
    isp = probe.get("isp", "")

    state_path = log_dir / "heartbeat-state.json"
    buffer_path = log_dir / "heartbeat-buffer.lp"
    started = time.monotonic()
    now_ms = _now_ms()
    state = load_state(state_path)

    targets = hb.get("targets", DEFAULT_TARGETS)
    dns_names = hb.get("dnsNames", DEFAULT_DNS_NAMES)
    interval_s = float(hb.get("sampleIntervalSeconds", 5))
    rounds = args.rounds or int(round(float(hb.get("windowSeconds", 45)) / max(0.001, interval_s))) + 1
    timeout_s = float(hb.get("timeoutSeconds", 2))
    service_cfg = hb.get("serviceChecks", [])
    service_timeout = float(hb.get("serviceTimeoutSeconds", 8))

    route_ok = has_default_route()
    net = get_local_network(state, now_ms) if route_ok else {"gw": "", "dns": []}
    dns_servers = ([{"name": f"sistema-{ip}", "ip": ip, "kind": "system"} for ip in net.get("dns", [])]
                   + [{**s, "kind": "public"} for s in hb.get("dnsServers", DEFAULT_DNS_SERVERS)])
    resolved = resolve_targets(targets, state["ip_cache"])
    addrs = [t["addr"] for t in resolved]

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        gw_future = ex.submit(check_gateway, net["gw"]) if net.get("gw") else None
        os_dns_futures = [ex.submit(check_dns, n) for n in dns_names]
        dns_futures = [ex.submit(check_dns_server, s, dns_names, timeout_s) for s in dns_servers]
        verify_future = ex.submit(verify_internet, hb.get("connectivityChecks", DEFAULT_CONNECTIVITY_CHECKS))
        service_futures = [ex.submit(check_service, c, service_timeout) for c in service_cfg]
        with qoe_throughput.high_res_timer():
            matrix = sample_rounds(addrs, rounds, interval_s, timeout_s)
        os_dns = [f.result() for f in os_dns_futures]
        dns = summarize_dns(os_dns, [f.result() for f in dns_futures])
        verified = verify_future.result()
        service_results = [f.result() for f in service_futures]
        gateway: Optional[Dict[str, Any]] = gw_future.result() if gw_future else None
        if not route_ok:
            gateway = {"present": False, "reachable": False, "latency_ms": 0.0}
        elif gateway is not None and not gateway["reachable"]:
            # La puerta de enlace pudo cambiar (otra red): se vuelve a leer antes de culpar al router.
            fresh = get_local_network(state, now_ms, force=True)
            if fresh.get("gw") and fresh["gw"] != net.get("gw"):
                gateway = check_gateway(fresh["gw"])

    checks = [summarize_target(t, [row[i] for row in matrix], hb) for i, t in enumerate(resolved)]
    blackout = find_blackouts(matrix, addrs)
    summary = classify(gateway, checks, dns, verified, blackout, interval_s)
    status = summary["status"]
    samples_total = sum(1 for i, a in enumerate(addrs) if a is not None for _ in matrix)
    samples_lost = sum(1 for row in matrix for i, a in enumerate(addrs) if a is not None and row[i] is None)
    loss_pct = round(samples_lost * 100.0 / samples_total, 1) if samples_total else 100.0

    evaluate_services = status not in NO_INTERNET_STATUSES
    services = classify_services(service_results) if evaluate_services else {}

    tags_base = {"probe_id": probe_id, "site": site, "isp": probe.get("isp", "unknown")}
    lines = []
    for c in checks:
        lines.append(qoe_probe.build_influx_line("qoe_heartbeat", {**tags_base, "check": c["name"], "kind": c["kind"]}, {
            "reachable": c["reachable"], "degraded": c["degraded"], "latency_ms": float(c["latency_ms"]),
            "jitter_ms": float(c["jitter_ms"]), "loss_pct": float(c["loss_pct"]), "p95_ms": float(c["p95_ms"]),
        }, now_ms))
    dns_ok = [d for d in os_dns if d["ok"]]
    status_fields: Dict[str, Any] = {
        "status": status,
        "status_code": STATUS_CODES[status],
        "gateway_reachable": bool(gateway["reachable"]) if gateway else True,
        "gateway_latency_ms": float(gateway["latency_ms"]) if gateway else 0.0,
        "dns_ok_ratio": round(len(dns_ok) / max(1, len(os_dns)), 2),
        "dns_ms": round(sum(d["ms"] for d in dns_ok) / len(dns_ok), 2) if dns_ok else 0.0,
        "loss_pct": float(loss_pct),
        "blackout_rounds": int(blackout["rounds"]),
        "blackout_s": float(blackout["rounds"] * interval_s),
        "rounds": len(matrix),
    }
    for key, value in (("dns_system_ok", dns["system_ok"]), ("dns_public_ok", dns["public_ok"]), ("internet_verified", verified)):
        if value is not None:
            status_fields[key] = bool(value)
    lines.append(qoe_probe.build_influx_line("qoe_heartbeat_status", tags_base, status_fields, now_ms))
    if evaluate_services:
        for r in service_results:
            lines.append(qoe_probe.build_influx_line(
                "qoe_service_check", {**tags_base, "service": r["service"], "check": r["name"]},
                {"available": r["available"], "http_status": int(r["http_status"]),
                 "time_total_ms": float(r["time_total_ms"]), "error_class": r["error_class"] or "none"}, now_ms))

    if not args.skip_influx_write:
        write_influx(lines, config, config_path.parent, buffer_path)

    action = update_alert_state(state, status, now_ms, int(hb.get("failThreshold", 2)),
                                int(hb.get("recoverThreshold", 5)), int(hb.get("degradedFailThreshold", 5)))
    service_actions: Dict[str, Optional[str]] = {}
    for name, info in services.items():
        s_state = state["services"].setdefault(name, {})
        service_actions[name] = update_alert_state(s_state, info["status"], now_ms,
                                                   int(hb.get("serviceFailThreshold", 3)),
                                                   int(hb.get("serviceRecoverThreshold", 2)))

    if not args.skip_telegram:
        creds = qoe_telegram.get_credentials(repo_root / ".env")
        if qoe_telegram.is_configured(creds):
            send = lambda m: qoe_telegram.send_message(m, creds, timeout=5.0)  # noqa: E731
            flush_pending(state, creds)
            notify(action, state,
                   lambda a: build_message(a, probe_id, site, status, summary, checks, state, now_ms, isp), send)
            for name, s_action in service_actions.items():
                notify(s_action, state["services"][name],
                       lambda a, n=name: build_service_message(a, probe_id, site, n, services[n], state["services"][n], now_ms),
                       send, pending=state["pending"])

    today = datetime.date.today().isoformat()
    if state.get("last_gc_day") != today:
        state["last_gc_day"] = today
        rotate_logs(log_dir, int(hb.get("logRetentionDays", 30)))
    write_atomic(state_path, json.dumps(state, indent=2))

    detail = ", ".join(f"{c['name']}={'%sms' % c['latency_ms'] if c['reachable'] else 'X'}" for c in checks)
    flag = lambda v: "?" if v is None else ("ok" if v else "X")  # noqa: E731
    router = "sin_ruta" if not route_ok else flag(gateway["reachable"] if gateway else None)
    extra = (f" | router={router} dns={flag(dns['system_ok'])}/{flag(dns['public_ok'])} web={flag(verified)} "
             f"perdida={loss_pct}% cortes={int(blackout['rounds'] * interval_s)}s")
    if services:
        extra += " | servicios: " + ", ".join(
            f"{n}={i['status']}" + (f"({len(i['failed'])}/{i['total']})" if i["failed"] else "") for n, i in services.items())
    acts = [a for a in [action] + [f"{n}:{a}" for n, a in service_actions.items() if a] if a]
    took = round(time.monotonic() - started, 1)
    qoe_probe.log_message(f"Heartbeat {status} ({detail}){extra} [{took}s]{' -> ' + ', '.join(acts) if acts else ''}")
    return 0


def report_crash(log_dir: Path, repo_root: Path, error: str, skip_telegram: bool) -> None:
    """Un error interno se registra y se avisa (una vez cada 6 h): la sonda nunca debe morir en silencio."""
    qoe_probe.log_message(f"Heartbeat: error interno, la corrida no terminó:\n{error}", "ERROR")
    if skip_telegram:
        return
    marker = log_dir / "heartbeat-error.json"
    try:
        last = json.loads(marker.read_text(encoding="utf-8")).get("ts", 0) if marker.is_file() else 0
        if time.time() - float(last) < 6 * 3600:
            return
        creds = qoe_telegram.get_credentials(repo_root / ".env")
        if qoe_telegram.is_configured(creds):
            short = error.strip().splitlines()[-1][:300]
            if qoe_telegram.send_message(f"CX-Radar: el monitor de la sonda falló y no está midiendo.\n{short}\nRevisar logs/qoe-heartbeat-*.log", creds, timeout=5.0):
                write_atomic(marker, json.dumps({"ts": time.time()}))
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="CX-Radar heartbeat (cada minuto).")
    parser.add_argument("--config-path", type=str, default="")
    parser.add_argument("--skip-influx-write", action="store_true")
    parser.add_argument("--skip-telegram", action="store_true")
    parser.add_argument("--rounds", type=int, default=0, help="Rondas de muestreo (por defecto, las de la ventana configurada)")
    parser.add_argument("--log-dir", type=str, default="",
                        help="Carpeta de log, estado y bloqueo. Para pruebas: no toca el estado del monitor programado.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    log_dir = repo_root / "logs"
    try:
        cfg_path = Path(args.config_path).resolve() if args.config_path else repo_root / "config" / "probe-catalog.json"
        log_dir = repo_root / qoe_config.load_config(cfg_path).get("probeRun", {}).get("logDirectory", "logs")
    except Exception:
        pass  # el error de configuración se reporta dentro de run()
    if args.log_dir:
        log_dir = Path(args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    qoe_probe.log_path_global = log_dir / f"qoe-heartbeat-{datetime.date.today().isoformat()}.log"

    lock_path = log_dir / "heartbeat.lock"
    if not acquire_lock(lock_path):
        qoe_probe.log_message("Heartbeat: la corrida anterior sigue en curso, esta se omite.", "WARNING")
        return

    def deadline() -> None:
        qoe_probe.log_message(f"Heartbeat: la corrida pasó de {HARD_DEADLINE_SECONDS} s y se detiene.", "ERROR")
        release_lock(lock_path)
        os._exit(3)

    watchdog = threading.Timer(HARD_DEADLINE_SECONDS, deadline)
    watchdog.daemon = True
    watchdog.start()
    code = 0
    try:
        code = run(args, repo_root, log_dir)
    except Exception:
        code = 1
        report_crash(log_dir, repo_root, traceback.format_exc(), args.skip_telegram)
    finally:
        watchdog.cancel()
        release_lock(lock_path)
    sys.exit(code)


if __name__ == "__main__":
    main()
