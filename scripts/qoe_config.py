#!/usr/bin/env python3
"""
Carga del catálogo con ajustes locales por servidor.

`config/probe-catalog.json` está en git y llega con cada `git pull`. Los datos
propios de cada servidor (identidad de la sonda, router, tipo de conexión,
umbrales u objetivos distintos) van en `config/probe-catalog.local.json`, que
está fuera de git. Así un `git pull` nunca choca con los cambios del servidor.

Reglas de combinación del archivo local sobre el del repo:
- Los objetos se combinan clave por clave (solo se escribe lo que cambia).
- Los valores simples y las listas (por ejemplo `targets`) reemplazan al
  valor del repo completo.

Ejemplo de `config/probe-catalog.local.json`:

    {
      "probe": {
        "probeId": "HUB_BTO",
        "site": "Server-HUB",
        "router_brand": "VSOL",
        "router_model": "HG5033-AX30-3G",
        "connection_type": "ETHERNET"
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def local_override_path(config_path: Path) -> Path:
    return config_path.with_name(f"{config_path.stem}.local{config_path.suffix}")


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def merge_text(base_text: str, config_path: Path) -> Dict[str, Any]:
    """Combina el texto del catálogo con el archivo local, si existe."""
    config = json.loads(base_text)
    local = local_override_path(config_path)
    if local.is_file():
        try:
            override = json.loads(local.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"{local.name} no es un JSON válido: {e}") from e
        if not isinstance(override, dict):
            raise ValueError(f"{local.name} debe contener un objeto JSON.")
        config = deep_merge(config, override)
    return config


def load_config(config_path: Path) -> Dict[str, Any]:
    """Lee el catálogo del repo y le aplica `<nombre>.local.json` si existe."""
    return merge_text(Path(config_path).read_text(encoding="utf-8"), Path(config_path))
