#!/usr/bin/env python3
"""
CX-Radar: monitor liviano para detectar fallas en menos de 5 minutos.

Corre cada minuto (registrar con `register_qoe_task.py --script heartbeat
--interval-minutes 1`). No mide velocidad: hace pocas conexiones cortas
(router local, servidores Ookla de Inter, destinos externos y DNS), clasifica
el estado y avisa por Telegram.

Diagnóstico:
- caida_router_local: no responde el router de la sonda (problema local).
- caida_acceso:       no responde nada, ni la red de Inter ni internet
                      (PON, OLT, agregación o BNG).
- caida_transito:     la red de Inter responde pero internet no (salida o tránsito).
- degradado:          responde, pero con latencia o pérdida fuera de umbral.
- ok

Alertas: se avisa cuando el mismo problema se repite `failThreshold` corridas
seguidas (por defecto 2 = 2 minutos) y se avisa la recuperación después de
`recoverThreshold` corridas buenas. Si la caída impide enviar el mensaje, se
guarda y se envía apenas vuelva la conexión, con la hora real de la falla.
Las métricas que no se pudieron escribir en InfluxDB también se guardan y se
reenvían, para que Grafana muestre la ventana completa de la caída.

Requisitos: Python >= 3.8, solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qoe_probe  # noqa: E402
import qoe_telegram  # noqa: E402
import qoe_throughput  # noqa: E402

DEFAULT_TARGETS = [
    {"name": "inter-ookla-bqto", "host": "speedtest.bqto.inter.com.ve", "port": 8080, "kind": "inter"},
    {"name": "inter-ookla-ccs", "host": "speedtest.ccs.inter.com.ve", "port": 8080, "kind": "inter"},
    {"name": "cloudflare", "host": "1.1.1.1", "port": 443, "kind": "external"},
    {"name": "google", "host": "www.google.com", "port": 443, "kind": "external"},
    {"name": "netflix", "host": "fast.com", "port": 443, "kind": "external"},
]
DEFAULT_DNS_NAMES = ["www.google.com", "www.youtube.com", "www.netflix.com"]
DEFAULT_MAX_LATENCY = {"inter": 40.0, "external": 150.0}
STATUS_CODES = {"ok": 0, "degradado": 1, "caida_transito": 2, "caida_acceso": 3, "caida_router_local": 4}
STATUS_TEXT = {
    "ok": "Servicio normal",
    "degradado": "Servicio degradado (latencia o pérdida altas)",
    "caida_transito": "Falla de salida a internet: la red de Inter responde, internet no",
    "caida_acceso": "Caída del acceso: no responde ni la red de Inter ni internet (PON, OLT, agregación o BNG)",
    "caida_router_local": "No responde el router de la sonda (falla local del punto de medición)",
}
MAX_BUFFER_LINES = 20000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt_time(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%d/%m %H:%M")


def _fmt_duration(ms: int) -> str:
    minutes = max(1, round(ms / 60000))
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def check_target(t: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    r = qoe_throughput.measure_tcp_latency(t["host"], int(t.get("port", 443)), count=int(cfg.get("samplesPerTarget", 5)),
                                           timeout_s=float(cfg.get("timeoutSeconds", 2)), interval_s=0.2)
    kind = t.get("kind", "external")
    max_lat = float(t.get("maxLatencyMs", cfg.get("maxLatencyMs", {}).get(kind, DEFAULT_MAX_LATENCY.get(kind, 150.0))))
    max_loss = float(t.get("maxLossPercentage", cfg.get("maxLossPercentage", 20.0)))
    reachable = r["Samples"] > 0
    degraded = reachable and (r["LatencyMs"] > max_lat or r["LossPercentage"] >= max_loss)
    return {**t, "kind": kind, "reachable": reachable, "degraded": degraded,
            "latency_ms": r["LatencyMs"], "jitter_ms": r["JitterMs"], "loss_pct": r["LossPercentage"],
            "max_latency_ms": max_lat}


def check_dns(name: str) -> Dict[str, Any]:
    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
        return {"name": name, "ok": True, "ms": round((time.perf_counter() - t0) * 1000, 2)}
    except OSError:
        return {"name": name, "ok": False, "ms": 0.0}


def classify(gateway: Optional[Dict[str, Any]], checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    inter = [c for c in checks if c["kind"] == "inter"]
    external = [c for c in checks if c["kind"] != "inter"]
    inter_ok = any(c["reachable"] for c in inter) if inter else True
    ext_ok = any(c["reachable"] for c in external) if external else True
    degraded = [c["name"] for c in checks if c["degraded"]]
    unreachable = [c["name"] for c in checks if not c["reachable"]]

    if gateway is not None and not gateway["reachable"] and not inter_ok and not ext_ok:
        status = "caida_router_local"
    elif not inter_ok and not ext_ok:
        status = "caida_acceso"
    elif inter_ok and not ext_ok:
        status = "caida_transito"
    elif degraded or unreachable:
        status = "degradado"
    else:
        status = "ok"
    return {"status": status, "degraded": degraded, "unreachable": unreachable}


def update_alert_state(state: Dict[str, Any], status: str, now_ms: int, fail_threshold: int,
                       recover_threshold: int) -> Optional[str]:
    """Actualiza el estado y devuelve el tipo de mensaje a enviar: 'alert', 'escalate', 'recovery' o None."""
    action = None
    if status != "ok":
        if state.get("bad_count", 0) == 0:
            state["bad_since"] = now_ms
        state["bad_count"] = state.get("bad_count", 0) + 1
        state["good_count"] = 0
        if state["bad_count"] >= fail_threshold:
            if not state.get("alerted"):
                action = "alert"
            elif STATUS_CODES[status] > STATUS_CODES.get(state.get("alert_status", "ok"), 0):
                action = "escalate"
            if action:
                state["alerted"] = True
                state["alert_status"] = status
    else:
        state["good_count"] = state.get("good_count", 0) + 1
        if state.get("alerted") and state["good_count"] >= recover_threshold:
            action = "recovery"
            state["alerted"] = False
            state["alert_status"] = "ok"
        if state["good_count"] >= recover_threshold or not state.get("alerted"):
            state["bad_count"] = 0
    state["last_status"] = status
    return action


def build_message(action: str, probe_id: str, site: str, status: str, summary: Dict[str, Any],
                  checks: List[Dict[str, Any]], state: Dict[str, Any], now_ms: int) -> str:
    header = f"CX-Radar | sonda {probe_id} ({site})"
    if action == "recovery":
        since = state.get("bad_since", now_ms)
        return (f"{header}\nRECUPERADO a las {_fmt_time(now_ms)}\n"
                f"Duración de la falla: {_fmt_duration(now_ms - since)} (desde {_fmt_time(since)})")
    title = "FALLA" if action == "alert" else "EMPEORA"
    lines = [header, f"{title}: {STATUS_TEXT[status]}", f"Detectado: {_fmt_time(state.get('bad_since', now_ms))}"]
    for c in checks:
        if not c["reachable"]:
            lines.append(f"- {c['name']}: sin respuesta")
        elif c["degraded"]:
            lines.append(f"- {c['name']}: {c['latency_ms']} ms (umbral {c['max_latency_ms']:.0f}), pérdida {c['loss_pct']} %")
    return "\n".join(lines)


def flush_pending(state: Dict[str, Any], creds: Dict[str, str]) -> None:
    pending = state.get("pending", [])
    remaining = []
    for msg in pending:
        text = f"(enviado con retraso)\n{msg}"
        if not qoe_telegram.send_message(text, creds):
            remaining.append(msg)
    state["pending"] = remaining[-50:]


def write_influx(lines: List[str], config: Dict[str, Any], config_dir: Path, buffer_path: Path) -> bool:
    buffered: List[str] = []
    if buffer_path.is_file():
        buffered = [ln for ln in buffer_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    payload_lines = buffered + lines
    influx = config.get("influx", {})
    try:
        token = qoe_probe.get_influx_token(influx, config_dir)
        url = (f"{influx['baseUrl'].rstrip('/')}/api/v2/write?org={influx['org']}"
               f"&bucket={influx['bucket']}&precision=ms")
        qoe_probe.write_to_influx(url, token, "\n".join(payload_lines), float(influx.get("writeTimeoutSeconds", 15)))
        if buffer_path.is_file():
            buffer_path.unlink()
        return True
    except Exception as e:
        qoe_probe.log_message(f"Heartbeat: no se pudo escribir en InfluxDB, se guarda para reenviar: {e}", "WARNING")
        buffer_path.write_text("\n".join(payload_lines[-MAX_BUFFER_LINES:]) + "\n", encoding="utf-8")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="CX-Radar heartbeat (cada minuto).")
    parser.add_argument("--config-path", type=str, default="")
    parser.add_argument("--skip-influx-write", action="store_true")
    parser.add_argument("--skip-telegram", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    config_path = Path(args.config_path).resolve() if args.config_path else repo_root / "config" / "probe-catalog.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    hb = config.get("heartbeat", {})
    probe = config.get("probe", {})
    probe_id = probe.get("probeId", "unknown")
    site = probe.get("site", "unknown")

    log_dir = repo_root / config.get("probeRun", {}).get("logDirectory", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    qoe_probe.log_path_global = log_dir / f"qoe-heartbeat-{datetime.date.today().isoformat()}.log"
    state_path = log_dir / "heartbeat-state.json"
    buffer_path = log_dir / "heartbeat-buffer.lp"

    now_ms = _now_ms()
    targets = hb.get("targets", DEFAULT_TARGETS)
    dns_names = hb.get("dnsNames", DEFAULT_DNS_NAMES)

    gw_ip = qoe_probe.get_default_gateway()
    gateway = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets) + len(dns_names) + 1) as ex:
        gw_future = ex.submit(qoe_probe.get_ping_burst_stats, gw_ip, 3, 500) if gw_ip else None
        check_futures = [ex.submit(check_target, t, hb) for t in targets]
        dns_futures = [ex.submit(check_dns, n) for n in dns_names]
        checks = [f.result() for f in check_futures]
        dns = [f.result() for f in dns_futures]
        if gw_future:
            g = gw_future.result()
            gateway = {"reachable": g["SuccessfulReplies"] > 0, "latency_ms": g["LatencyMs"]}

    summary = classify(gateway, checks)
    status = summary["status"]

    tags_base = {"probe_id": probe_id, "site": site, "isp": probe.get("isp", "unknown")}
    lines = []
    for c in checks:
        lines.append(qoe_probe.build_influx_line("qoe_heartbeat", {**tags_base, "check": c["name"], "kind": c["kind"]}, {
            "reachable": c["reachable"], "degraded": c["degraded"], "latency_ms": float(c["latency_ms"]),
            "jitter_ms": float(c["jitter_ms"]), "loss_pct": float(c["loss_pct"]),
        }, now_ms))
    dns_ok = [d for d in dns if d["ok"]]
    lines.append(qoe_probe.build_influx_line("qoe_heartbeat_status", tags_base, {
        "status": status,
        "status_code": STATUS_CODES[status],
        "gateway_reachable": bool(gateway["reachable"]) if gateway else True,
        "gateway_latency_ms": float(gateway["latency_ms"]) if gateway else 0.0,
        "dns_ok_ratio": round(len(dns_ok) / max(1, len(dns)), 2),
        "dns_ms": round(sum(d["ms"] for d in dns_ok) / len(dns_ok), 2) if dns_ok else 0.0,
    }, now_ms))

    if not args.skip_influx_write:
        write_influx(lines, config, config_path.parent, buffer_path)

    state: Dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    action = update_alert_state(state, status, now_ms, int(hb.get("failThreshold", 2)), int(hb.get("recoverThreshold", 2)))

    if not args.skip_telegram:
        creds = qoe_telegram.get_credentials(repo_root / ".env")
        if qoe_telegram.is_configured(creds):
            flush_pending(state, creds)
            if action:
                msg = build_message(action, probe_id, site, status, summary, checks, state, now_ms)
                if not qoe_telegram.send_message(msg, creds):
                    state.setdefault("pending", []).append(msg)

    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    detail = ", ".join(f"{c['name']}={'%sms' % c['latency_ms'] if c['reachable'] else 'X'}" for c in checks)
    qoe_probe.log_message(f"Heartbeat {status} ({detail}){' -> ' + action if action else ''}")


if __name__ == "__main__":
    main()
