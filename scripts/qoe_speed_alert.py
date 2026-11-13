#!/usr/bin/env python3
"""
CX-Radar: aviso de velocidad por debajo del plan contratado.

Lo llama la sonda completa (`qoe_probe.py`) al terminar cada corrida. Solo
funciona si el catálogo (o `probe-catalog.local.json`) declara el plan:

    "probe": { "planDownMbps": 600, "planUpMbps": 600 }

Se toma la mejor descarga y la mejor subida de la corrida entre todos los
destinos disponibles: si hasta el destino más rápido queda por debajo de
`speedAlert.minPercent` (50 %) del plan, el problema es de la conexión y no de
un servidor lento. Avisa tras `failThreshold` corridas seguidas (2) y avisa la
recuperación tras `recoverThreshold` (2). Una corrida sin ninguna medición
(sin internet) no cuenta: las caídas las avisa el monitor de cada minuto.

Requisitos: Python >= 3.8, solo biblioteca estándar.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qoe_telegram  # noqa: E402

STATE_FILE = "speed-alert-state.json"


def evaluate(reports: List[Dict[str, Any]], probe: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compara la mejor medición con el plan. None si no hay plan o no hubo mediciones."""
    plan_down = float(probe.get("planDownMbps") or 0)
    plan_up = float(probe.get("planUpMbps") or 0)
    if plan_down <= 0 and plan_up <= 0:
        return None
    ok = [r for r in reports if r.get("type") == "speedtest" and r.get("available")]
    downs = [(float(r.get("download_mbps") or 0), r.get("service", "")) for r in ok if float(r.get("download_mbps") or 0) > 0]
    ups = [(float(r.get("upload_mbps") or 0), r.get("service", "")) for r in ok if float(r.get("upload_mbps") or 0) > 0]
    if not downs:
        return None
    min_percent = float(cfg.get("minPercent", 50))
    best_down, down_service = max(downs)
    best_up, up_service = max(ups) if ups else (0.0, "")
    low: List[str] = []
    if plan_down > 0 and best_down < plan_down * min_percent / 100.0:
        low.append(f"Descarga: {best_down:.0f} Mbps de {plan_down:.0f} contratados ({best_down * 100 / plan_down:.0f} %), mejor destino {down_service}")
    if plan_up > 0 and ups and best_up < plan_up * min_percent / 100.0:
        low.append(f"Subida: {best_up:.0f} Mbps de {plan_up:.0f} contratados ({best_up * 100 / plan_up:.0f} %), mejor destino {up_service}")
    return {"status": "velocidad_baja" if low else "ok", "low": low, "best_down": best_down, "best_up": best_up,
            "measured": len(downs), "min_percent": min_percent}


def update_state(state: Dict[str, Any], status: str, fail_threshold: int, recover_threshold: int) -> Optional[str]:
    """Devuelve 'alert', 'recovery' o None."""
    if status != "ok":
        state["bad_count"] = int(state.get("bad_count", 0)) + 1
        state["good_count"] = 0
        if state["bad_count"] >= fail_threshold and not state.get("alerted"):
            state["alerted"] = True
            return "alert"
        return None
    state["good_count"] = int(state.get("good_count", 0)) + 1
    if state.get("alerted"):
        if state["good_count"] >= recover_threshold:
            state["alerted"] = False
            state["bad_count"] = 0
            return "recovery"
        return None
    state["bad_count"] = 0
    return None


def build_message(action: str, probe: Dict[str, Any], result: Dict[str, Any]) -> str:
    header = f"CX-Radar | sonda {probe.get('probeId', 'unknown')} ({probe.get('site', 'unknown')})"
    if action == "recovery":
        return (f"{header}\nVELOCIDAD RECUPERADA: mejor descarga {result['best_down']:.0f} Mbps, "
                f"mejor subida {result['best_up']:.0f} Mbps")
    lines = [header, f"VELOCIDAD BAJA: por debajo del {result['min_percent']:.0f} % del plan en corridas seguidas"]
    lines += [f"- {item}" for item in result["low"]]
    lines.append(f"Destinos medidos en la corrida: {result['measured']}. Es la mejor medición, no el promedio.")
    return "\n".join(lines)


def process(config: Dict[str, Any], reports: List[Dict[str, Any]], log_dir: Path, repo_root: Path,
            send: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """Evalúa la corrida, actualiza el estado y envía el aviso si corresponde. Nunca lanza."""
    try:
        probe = config.get("probe", {})
        cfg = config.get("speedAlert", {})
        result = evaluate(reports, probe, cfg)
        if result is None:
            return None
        state_path = log_dir / STATE_FILE
        try:
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
            if not isinstance(state, dict):
                state = {}
        except Exception:
            state = {}
        action = update_state(state, result["status"], int(cfg.get("failThreshold", 2)), int(cfg.get("recoverThreshold", 2)))
        if action:
            if send is None:
                creds = qoe_telegram.get_credentials(repo_root / ".env")
                send = (lambda m: qoe_telegram.send_message(m, creds)) if qoe_telegram.is_configured(creds) else (lambda m: False)
            if not send(build_message(action, probe, result)):
                # Sin Telegram se deja el estado como estaba para reintentar en la próxima corrida.
                if action == "alert":
                    state["alerted"] = False
                else:
                    state["alerted"] = True
        tmp = state_path.with_name(state_path.name + ".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, state_path)
        return action
    except Exception:
        return None
