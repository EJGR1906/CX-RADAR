#!/usr/bin/env python3
"""
Envío de alertas por Telegram (solo biblioteca estándar).

Credenciales (nunca en el repositorio), en variables de entorno o en el `.env`
de la raíz del proyecto:
    TELEGRAM_BOT_TOKEN=<token que entrega @BotFather>
    TELEGRAM_CHAT_ID=<id del chat o grupo que recibe las alertas>

Uso manual para probar la configuración:
    python scripts/qoe_telegram.py --test
    python scripts/qoe_telegram.py --find-chat-id   # después de escribirle al bot
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

TELEGRAM_API = "https://api.telegram.org"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_credentials(env_path: Optional[Path] = None) -> Dict[str, str]:
    env_file = _read_env_file(env_path or (REPO_ROOT / ".env"))
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN") or env_file.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID") or env_file.get("TELEGRAM_CHAT_ID", ""),
    }


def is_configured(creds: Optional[Dict[str, str]] = None) -> bool:
    c = creds or get_credentials()
    return bool(c["token"] and c["chat_id"])


def _call(method: str, token: str, params: Dict[str, str], timeout: float) -> dict:
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - URL fija https
        return json.loads(resp.read().decode("utf-8"))


def send_message(text: str, creds: Optional[Dict[str, str]] = None, timeout: float = 10.0) -> bool:
    """Envía un mensaje. Devuelve False (sin lanzar excepción) si no se pudo."""
    c = creds or get_credentials()
    if not (c["token"] and c["chat_id"]):
        return False
    try:
        result = _call("sendMessage", c["token"], {
            "chat_id": c["chat_id"],
            "text": text[:4000],
            "disable_web_page_preview": "true",
        }, timeout)
        return bool(result.get("ok"))
    except Exception:
        return False


def find_chat_ids(token: str, timeout: float = 10.0) -> List[str]:
    result = _call("getUpdates", token, {}, timeout)
    ids = []
    for upd in result.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat", {})
        if chat.get("id") is not None:
            label = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
            entry = f"{chat['id']} ({label})"
            if entry not in ids:
                ids.append(entry)
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Alertas de CX-Radar por Telegram.")
    parser.add_argument("--test", action="store_true", help="Envía un mensaje de prueba")
    parser.add_argument("--find-chat-id", action="store_true", help="Lista los chats que le escribieron al bot")
    args = parser.parse_args()

    creds = get_credentials()
    if not creds["token"]:
        print("Falta TELEGRAM_BOT_TOKEN en el entorno o en .env", file=sys.stderr)
        sys.exit(1)
    if args.find_chat_id:
        ids = find_chat_ids(creds["token"])
        print("\n".join(ids) if ids else "Sin mensajes: escríbele cualquier cosa al bot y vuelve a correr esto.")
        return
    if args.test:
        ok = send_message("CX-Radar: mensaje de prueba. Las alertas llegarán a este chat.", creds)
        print("Enviado" if ok else "No se pudo enviar (revisa TELEGRAM_CHAT_ID y la conexión)")
        sys.exit(0 if ok else 1)
    parser.print_help()


if __name__ == "__main__":
    main()
