#!/usr/bin/env python3
"""
CX-Radar: crea en Grafana Cloud la alerta "sonda sin reportar".

Una sonda sin internet no puede avisar por Telegram, así que el aviso en el
momento de la caída lo da Grafana Cloud, que sigue conectado. La regla mira,
por cada sonda, hace cuántos minutos llegó su último `qoe_heartbeat_status` a
InfluxDB. Si pasan más de `--minutes` (3 por defecto) avisa por el mismo bot
de Telegram, y cuando la sonda vuelve a reportar manda el aviso de resuelto.

El script es idempotente (UIDs fijos): crea o actualiza
- el contact point de Telegram `CX-Radar Telegram`,
- la carpeta `CX-Radar` y la regla `cx-radar-sonda-sin-reportar`,
- una ruta hija `app=cx-radar` en la política de notificaciones (la ruta raíz
  y las demás rutas no se tocan).

Credenciales (nunca en el repositorio), en el entorno o en el `.env` de la raíz:
    GRAFANA_TOKEN=<token de una service account con rol Editor o Admin>
    TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (los mismos de qoe_telegram.py)

Uso:
    python scripts/setup_grafana_alert.py --grafana-url https://<stack>.grafana.net --dry-run
    python scripts/setup_grafana_alert.py --grafana-url https://<stack>.grafana.net

Requisitos: Python >= 3.8, solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qoe_config  # noqa: E402
import qoe_telegram  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FOLDER_UID = "cx-radar"
FOLDER_TITLE = "CX-Radar"
RULE_UID = "cx-radar-sonda-sin-reportar"
RULE_GROUP = "cx-radar-sondas"
CONTACT_UID = "cx-radar-telegram"
CONTACT_NAME = "CX-Radar Telegram"
ROUTE_LABEL = ("app", "cx-radar")
# Ventana de búsqueda del último reporte: una sonda apagada más tiempo que esto
# deja de aparecer en la consulta y su alerta se cierra sola.
LOOKBACK = "-7d"

TELEGRAM_MESSAGE = (
    '{{ range .Alerts.Firing }}CX-Radar | sonda {{ .Labels.probe_id }} ({{ .Labels.site }})\n'
    'SIN CONEXIÓN: {{ .Annotations.summary }}\n'
    '{{ .Annotations.description }}\n\n{{ end }}'
    '{{ range .Alerts.Resolved }}CX-Radar | sonda {{ .Labels.probe_id }} ({{ .Labels.site }})\n'
    'La sonda volvió a reportar (aviso de Grafana). El detalle de la falla llega en el mensaje RECUPERADO de la sonda.\n\n{{ end }}'
)


class GrafanaError(RuntimeError):
    pass


def build_flux(bucket: str) -> str:
    """Minutos desde el último heartbeat de cada sonda (una serie por probe_id)."""
    return (
        f'from(bucket: "{bucket}")\n'
        f'  |> range(start: {LOOKBACK})\n'
        '  |> filter(fn: (r) => r._measurement == "qoe_heartbeat_status" and r._field == "status_code")\n'
        '  |> group(columns: ["probe_id", "site"])\n'
        '  |> last()\n'
        '  |> map(fn: (r) => ({_time: r._time, probe_id: r.probe_id, site: r.site,\n'
        '      _value: float(v: int(v: now()) - int(v: r._time)) / 60000000000.0}))'
    )


def build_contact_point(bot_token: str, chat_id: str) -> Dict[str, Any]:
    return {
        "uid": CONTACT_UID,
        "name": CONTACT_NAME,
        "type": "telegram",
        "settings": {"bottoken": bot_token, "chatid": chat_id, "message": TELEGRAM_MESSAGE,
                     "disable_web_page_preview": True},
        "disableResolveMessage": False,
    }


def build_rule(datasource_uid: str, bucket: str, minutes: float) -> Dict[str, Any]:
    return {
        "uid": RULE_UID,
        "title": "CX-Radar: sonda sin reportar",
        "folderUID": FOLDER_UID,
        "ruleGroup": RULE_GROUP,
        "condition": "C",
        "data": [
            {"refId": "A", "relativeTimeRange": {"from": 7 * 24 * 3600, "to": 0}, "datasourceUid": datasource_uid,
             "model": {"refId": "A", "query": build_flux(bucket)}},
            {"refId": "B", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
             "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last",
                       "settings": {"mode": "dropNN"}}},
            {"refId": "C", "relativeTimeRange": {"from": 0, "to": 0}, "datasourceUid": "__expr__",
             "model": {"refId": "C", "type": "threshold", "expression": "B",
                       "conditions": [{"evaluator": {"type": "gt", "params": [minutes]}}]}},
        ],
        # Sin ninguna serie (todas las sondas caídas a la vez) también es una caída.
        "noDataState": "Alerting",
        # Un error de consulta de InfluxDB Cloud no es una caída de la sonda.
        "execErrState": "OK",
        "for": "0s",
        "labels": {ROUTE_LABEL[0]: ROUTE_LABEL[1]},
        "annotations": {
            "summary": "no reporta hace {{ printf \"%.0f\" $values.B.Value }} min. "
                       "Sin internet o equipo apagado.",
            "description": "Cuando vuelva la conexión, la sonda enviará el diagnóstico y la duración.",
        },
        "isPaused": False,
    }


def build_route(group_wait: str = "10s") -> Dict[str, Any]:
    return {
        "receiver": CONTACT_NAME,
        "object_matchers": [[ROUTE_LABEL[0], "=", ROUTE_LABEL[1]]],
        "group_by": ["alertname", "probe_id"],
        "group_wait": group_wait,
        "group_interval": "1m",
        "repeat_interval": "4h",
        "continue": False,
    }


def merge_route(policy: Dict[str, Any], route: Dict[str, Any]) -> Dict[str, Any]:
    """Agrega o reemplaza la ruta de CX-Radar sin tocar el resto del árbol."""
    routes = [r for r in policy.get("routes") or [] if r.get("receiver") != route["receiver"]]
    policy["routes"] = [route] + routes
    return policy


def pick_datasource(datasources: List[Dict[str, Any]]) -> Dict[str, Any]:
    flux = [d for d in datasources if d.get("type") == "influxdb"
            and str((d.get("jsonData") or {}).get("version", "")).lower() == "flux"]
    if len(flux) == 1:
        return flux[0]
    names = ", ".join(f"{d.get('name')} (uid {d.get('uid')})" for d in (flux or datasources))
    raise GrafanaError(f"No se pudo elegir el datasource InfluxDB (Flux). Indica --datasource-uid. Disponibles: {names}")


class Grafana:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0):
        self.base = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[Any] = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Deja los recursos editables desde la interfaz de Grafana.
            "X-Disable-Provenance": "true",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310 - URL indicada por el operador
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:500]
            if e.code == 404:
                return None
            raise GrafanaError(f"{method} {path}: HTTP {e.code} {detail}") from e
        return json.loads(raw) if raw.strip() else {}


def apply(g: Grafana, rule: Dict[str, Any], contact: Dict[str, Any], dry_run: bool) -> List[str]:
    done: List[str] = []

    def step(desc: str, method: str, path: str, body: Any) -> None:
        done.append(f"{method} {path}: {desc}")
        if not dry_run:
            g.request(method, path, body)

    if g.request("GET", f"/api/folders/{FOLDER_UID}") is None:
        step("crear carpeta", "POST", "/api/folders", {"uid": FOLDER_UID, "title": FOLDER_TITLE})

    existing = g.request("GET", "/api/v1/provisioning/contact-points") or []
    same_name = [c for c in existing if c.get("name") == CONTACT_NAME]
    if any(c.get("uid") == CONTACT_UID for c in existing):
        step("actualizar contact point", "PUT", f"/api/v1/provisioning/contact-points/{CONTACT_UID}", contact)
    elif same_name:
        step("actualizar contact point", "PUT", f"/api/v1/provisioning/contact-points/{same_name[0]['uid']}",
             {**contact, "uid": same_name[0]["uid"]})
    else:
        step("crear contact point", "POST", "/api/v1/provisioning/contact-points", contact)

    policy = g.request("GET", "/api/v1/provisioning/policies") or {}
    step("agregar ruta app=cx-radar", "PUT", "/api/v1/provisioning/policies", merge_route(policy, build_route()))

    if g.request("GET", f"/api/v1/provisioning/alert-rules/{RULE_UID}") is None:
        step("crear regla", "POST", "/api/v1/provisioning/alert-rules", rule)
    else:
        step("actualizar regla", "PUT", f"/api/v1/provisioning/alert-rules/{RULE_UID}", rule)

    group = g.request("GET", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{RULE_GROUP}")
    if dry_run and group is None:
        done.append(f"PUT rule-groups/{RULE_GROUP}: evaluar cada 60 s")
    elif group is not None:
        group["interval"] = 60
        step("evaluar cada 60 s", "PUT", f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{RULE_GROUP}", group)
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea la alerta 'sonda sin reportar' en Grafana Cloud.")
    parser.add_argument("--grafana-url", required=True, help="https://<stack>.grafana.net")
    parser.add_argument("--datasource-uid", default="", help="UID del datasource InfluxDB (Flux); se detecta si se omite")
    parser.add_argument("--minutes", type=float, default=3.0, help="Minutos sin reportar para avisar (por defecto 3)")
    parser.add_argument("--config-path", default="")
    parser.add_argument("--dry-run", action="store_true", help="Muestra lo que haría sin cambiar nada")
    args = parser.parse_args()

    env_values = qoe_telegram._read_env_file(REPO_ROOT / ".env")
    token = os.environ.get("GRAFANA_TOKEN") or env_values.get("GRAFANA_TOKEN", "")
    creds = qoe_telegram.get_credentials(REPO_ROOT / ".env")
    if not token:
        sys.exit("Falta GRAFANA_TOKEN en el entorno o en .env")
    if not qoe_telegram.is_configured(creds):
        sys.exit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno o en .env")

    config_path = Path(args.config_path).resolve() if args.config_path else REPO_ROOT / "config" / "probe-catalog.json"
    bucket = qoe_config.load_config(config_path).get("influx", {}).get("bucket", "qoe_metrics")

    g = Grafana(args.grafana_url, token)
    try:
        ds_uid = args.datasource_uid or pick_datasource(g.request("GET", "/api/datasources") or [])["uid"]
        rule = build_rule(ds_uid, bucket, args.minutes)
        contact = build_contact_point(creds["token"], creds["chat_id"])
        for line in apply(g, rule, contact, args.dry_run):
            print(("[dry-run] " if args.dry_run else "") + line)
    except GrafanaError as e:
        sys.exit(str(e))
    print("Listo." if not args.dry_run else "Sin cambios (dry-run).")


if __name__ == "__main__":
    main()
