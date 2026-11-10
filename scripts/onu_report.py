#!/usr/bin/env python3
"""
CX-Radar: análisis del reporte diario de ONUs (el de las 5 a. m. de la página
de herramientas FTTH).

Lee uno o varios .xlsx (una ciudad o todas), calcula la salud de cada PON,
lo compara con el reporte anterior y avisa por Telegram los PONs que
empeoraron. No consulta las OLTs ni la página: solo usa el archivo descargado.

Qué detecta (por PON):
- ONUs que estaban encendidas en el reporte anterior y hoy están apagadas
  (6 o más, o el 30 % del PON con al menos 4: corte de fibra, splitter o energía).
- Caída de la potencia Rx media que ve el OLT respecto del reporte anterior
  (conector sucio, empalme o fibra degradada, antes de que el cliente llame).
- PONs con la mayoría de sus ONUs apagadas.

Privacidad: solo se leen columnas técnicas (OLT, slot, PON, ONU, serial,
potencias, observaciones y servidor). Nunca se leen ni se guardan el nombre,
el número de abonado ni la dirección.

Salidas:
- logs/onu-snapshots/<fecha>.json: estado por ONU (solo identificadores
  técnicos) para comparar con el día siguiente.
- logs/onu-reports/<fecha>-pon.csv: detalle por PON.
- InfluxDB `onu_olt_health`: resumen por OLT (no por PON, para no superar el
  límite de series de la capa gratuita de InfluxDB Cloud).
- Telegram: resumen con los PONs a revisar.

Uso:
    python scripts/onu_report.py ruta/al/informe.xlsx [otro.xlsx ...]
    python scripts/onu_report.py carpeta_con_xlsx/ --skip-influx-write --skip-telegram

Requisitos: Python >= 3.8, solo biblioteca estándar.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import re
import statistics
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Columnas técnicas que se leen (nombres tal como vienen en el reporte).
COLUMNS = {
    "olt": "OLT", "olt_ip": "IP OLT", "slot": "Slot", "pon": "PON", "onu": "ONU", "sn": "PON SN",
    "rx_onu": "RX ONU (dBm)", "rx_olt": "RX OLT (dBm)", "obs": "Observaciones",
    "updated": "Última actualización", "server": "Servidor",
}
LOW_RX_OLT_DBM = -27.0


# ---------------------------------------------------------------------------
# Lectura de .xlsx con la biblioteca estándar
# ---------------------------------------------------------------------------
def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def iter_xlsx_rows(path: Path) -> Iterator[List[Any]]:
    """Recorre las filas de la primera hoja. Valores: str, float o None."""
    with zipfile.ZipFile(path) as z:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = wb.find("m:sheets/m:sheet", NS)
        rid = first.get(f"{{{NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        sheet_path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"

        with z.open(sheet_path) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != f"{{{NS['m']}}}row":
                    continue
                row: List[Any] = []
                for c in el.findall("m:c", NS):
                    idx = _col_index(c.get("r", "A1"))
                    while len(row) < idx:
                        row.append(None)
                    t = c.get("t")
                    v = c.find("m:v", NS)
                    if t == "s" and v is not None:
                        val: Any = shared[int(v.text)]
                    elif t == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    elif v is not None and v.text is not None:
                        try:
                            val = float(v.text)
                        except ValueError:
                            val = v.text
                    else:
                        val = None
                    row.append(val)
                el.clear()
                yield row


def _num(v: Any) -> Optional[float]:
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            return None
    return None


def _int(v: Any) -> Optional[int]:
    n = _num(v)
    return int(n) if n is not None else None


def city_from_server(server: str) -> str:
    """'G5 BARQUISIMETO' -> 'BARQUISIMETO'."""
    s = (server or "").strip()
    s = re.sub(r"^G\d+\s+", "", s, flags=re.IGNORECASE)
    return s.upper()


def read_report(path: Path) -> List[Dict[str, Any]]:
    rows = iter_xlsx_rows(path)
    header = None
    for r in rows:
        if r and any(isinstance(x, str) and x.strip() == "PON SN" for x in r):
            header = [str(x).strip() if x is not None else "" for x in r]
            break
    if header is None:
        raise ValueError(f"{path.name}: no se encontró la fila de encabezados (columna 'PON SN').")
    idx = {}
    for key, name in COLUMNS.items():
        if name in header:
            idx[key] = header.index(name)
    missing = [COLUMNS[k] for k in ("olt", "slot", "pon", "onu", "sn", "rx_olt") if k not in idx]
    if missing:
        raise ValueError(f"{path.name}: faltan columnas {missing}.")

    out = []
    for r in rows:
        def get(key):
            i = idx.get(key)
            return r[i] if i is not None and i < len(r) else None
        sn = get("sn")
        if not sn:
            continue
        rx_olt, rx_onu = _num(get("rx_olt")), _num(get("rx_onu"))
        out.append({
            "olt": str(get("olt") or "").strip(),
            "slot": _int(get("slot")), "pon": _int(get("pon")), "onu": _int(get("onu")),
            "sn": str(sn).strip(),
            "rx_olt": rx_olt, "rx_onu": rx_onu,
            "online": rx_olt is not None or rx_onu is not None,
            "out_of_range": str(get("obs") or "").strip().lower() == "fuera de rango",
            "city": city_from_server(str(get("server") or "")),
        })
    return out


# ---------------------------------------------------------------------------
# Análisis
# ---------------------------------------------------------------------------
def onu_key(o: Dict[str, Any]) -> str:
    return f"{o['olt']}|{o['slot']}|{o['pon']}|{o['onu']}|{o['sn']}"


def pon_key(o: Dict[str, Any]) -> str:
    return f"{o['olt']}|{o['slot']}/{o['pon']}"


def build_snapshot(onus: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {onu_key(o): {"on": o["online"], "rx": o["rx_olt"]} for o in onus}


def olt_cities(onus: List[Dict[str, Any]]) -> Dict[str, str]:
    """Ciudad de cada OLT: la más frecuente en la columna Servidor (las ONUs sin servidor no cuentan)."""
    votes: Dict[str, Counter] = defaultdict(Counter)
    for o in onus:
        if o["city"]:
            votes[o["olt"]][o["city"]] += 1
    return {olt: c.most_common(1)[0][0] for olt, c in votes.items()}


def analyze(onus: List[Dict[str, Any]], previous: Optional[Dict[str, Any]],
            cfg: Dict[str, Any]) -> Dict[str, Any]:
    cities = olt_cities(onus)
    pons: Dict[str, Dict[str, Any]] = {}
    for o in onus:
        p = pons.setdefault(pon_key(o), {
            "pon": pon_key(o), "olt": o["olt"], "city": cities.get(o["olt"], ""),
            "total": 0, "online": 0, "out_of_range": 0, "low_rx": 0, "rx": [],
            "new_offline": 0, "was_online": 0, "rx_prev": [], "rx_now_same": [],
        })
        p["total"] += 1
        p["online"] += o["online"]
        p["out_of_range"] += o["out_of_range"]
        if o["rx_olt"] is not None:
            p["rx"].append(o["rx_olt"])
            p["low_rx"] += o["rx_olt"] < LOW_RX_OLT_DBM
        if previous is not None:
            prev = previous.get(onu_key(o))
            if prev and prev.get("on"):
                p["was_online"] += 1
                if not o["online"]:
                    p["new_offline"] += 1
            if prev and prev.get("rx") is not None and o["rx_olt"] is not None:
                p["rx_prev"].append(prev["rx"])
                p["rx_now_same"].append(o["rx_olt"])

    min_onus = int(cfg.get("minOnusPerPon", 5))
    new_off_ratio = float(cfg.get("newOfflineRatio", 0.3))
    new_off_min = int(cfg.get("newOfflineMin", 4))
    # Un splitter 1:8 o 1:16 cortado apaga 8 o 16 ONUs aunque sean pocas frente al PON completo.
    new_off_abs = int(cfg.get("newOfflineAbsolute", 6))
    rx_drop_db = float(cfg.get("rxDropDb", 2.0))
    mostly_off = float(cfg.get("mostlyOfflineRatio", 0.5))

    flagged = []
    for p in pons.values():
        p["offline"] = p["total"] - p["online"]
        p["rx_median"] = round(statistics.median(p["rx"]), 2) if p["rx"] else None
        p["rx_delta"] = None
        if len(p["rx_prev"]) >= 3:
            p["rx_delta"] = round(statistics.median(p["rx_now_same"]) - statistics.median(p["rx_prev"]), 2)
        reasons = []
        if p["total"] >= min_onus:
            ratio_hit = p["was_online"] and p["new_offline"] >= new_off_min and p["new_offline"] / p["was_online"] >= new_off_ratio
            if ratio_hit or p["new_offline"] >= new_off_abs:
                reasons.append(f"{p['new_offline']} de {p['was_online']} ONUs se apagaron desde el reporte anterior")
            if p["rx_delta"] is not None and p["rx_delta"] <= -rx_drop_db:
                reasons.append(f"Rx media del OLT bajó {abs(p['rx_delta'])} dB")
            if p["offline"] / p["total"] >= mostly_off:
                reasons.append(f"{p['offline']} de {p['total']} ONUs apagadas")
        p["reasons"] = reasons
        if reasons:
            flagged.append(p)

    # Primero lo nuevo (apagones y caídas de Rx), después lo crónico.
    flagged.sort(key=lambda p: (-(p["new_offline"]), p["rx_delta"] if p["rx_delta"] is not None else 0, -p["offline"]))

    olts: Dict[str, Dict[str, Any]] = {}
    for p in pons.values():
        a = olts.setdefault(p["olt"], {"olt": p["olt"], "city": p["city"], "pons": 0, "total": 0, "online": 0,
                                       "out_of_range": 0, "low_rx": 0, "new_offline": 0, "flagged_pons": 0, "rx": []})
        a["pons"] += 1
        for k in ("total", "online", "out_of_range", "low_rx", "new_offline"):
            a[k] += p[k]
        a["flagged_pons"] += bool(p["reasons"])
        a["rx"].extend(p["rx"])
    for a in olts.values():
        a["rx_median"] = round(statistics.median(a["rx"]), 2) if a["rx"] else None
        del a["rx"]

    return {"pons": list(pons.values()), "flagged": flagged, "olts": list(olts.values()),
            "has_previous": previous is not None}


def build_telegram_summary(result: Dict[str, Any], report_date: str, max_items: int = 15) -> str:
    olts = result["olts"]
    total = sum(a["total"] for a in olts)
    online = sum(a["online"] for a in olts)
    cities = sorted({a["city"] for a in olts if a["city"]})
    lines = [f"CX-Radar | Reporte ONUs {report_date}",
             f"{', '.join(cities) or 'Sin ciudad'}: {len(olts)} OLTs, {total} ONUs, {online} encendidas"]
    if not result["has_previous"]:
        lines.append("Primer reporte: desde mañana se comparan apagones y caídas de Rx contra este.")
    flagged = result["flagged"]
    if not flagged:
        lines.append("Sin PONs para revisar.")
        return "\n".join(lines)
    lines.append(f"PONs para revisar: {len(flagged)}")
    for p in flagged[:max_items]:
        lines.append(f"- {p['pon']}: " + "; ".join(p["reasons"]))
    if len(flagged) > max_items:
        lines.append(f"... y {len(flagged) - max_items} más en el CSV del día.")
    return "\n".join(lines)


def write_pon_csv(result: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["pon", "olt", "city", "total", "online", "offline", "new_offline", "was_online",
              "out_of_range", "low_rx", "rx_median", "rx_delta", "reasons"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in sorted(result["pons"], key=lambda x: x["pon"]):
            w.writerow({**p, "reasons": " | ".join(p["reasons"])})


def influx_lines(result: Dict[str, Any], probe_id: str, ts_ms: int) -> List[str]:
    import qoe_probe
    lines = []
    for a in result["olts"]:
        fields = {k: a[k] for k in ("pons", "total", "online", "out_of_range", "low_rx", "new_offline", "flagged_pons")}
        fields["offline"] = a["total"] - a["online"]
        if a["rx_median"] is not None:
            fields["rx_olt_median_dbm"] = float(a["rx_median"])
        lines.append(qoe_probe.build_influx_line("onu_olt_health",
                                                 {"olt": a["olt"], "city": a["city"] or "desconocida", "source": probe_id},
                                                 fields, ts_ms))
    return lines


def find_previous_snapshot(snap_dir: Path, report_date: str) -> Optional[Dict[str, Any]]:
    if not snap_dir.is_dir():
        return None
    older = sorted(p for p in snap_dir.glob("*.json") if p.stem < report_date)
    if not older:
        return None
    return json.loads(older[-1].read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Análisis del reporte diario de ONUs.")
    parser.add_argument("paths", nargs="+", help="Archivos .xlsx o carpetas que los contienen")
    parser.add_argument("--config-path", type=str, default="")
    parser.add_argument("--date", type=str, default="", help="Fecha del reporte AAAA-MM-DD (por defecto, hoy)")
    parser.add_argument("--skip-influx-write", action="store_true")
    parser.add_argument("--skip-telegram", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    config_path = Path(args.config_path).resolve() if args.config_path else repo_root / "config" / "probe-catalog.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    cfg = config.get("onuReport", {})
    log_dir = repo_root / config.get("probeRun", {}).get("logDirectory", "logs")
    report_date = args.date or datetime.date.today().isoformat()

    files: List[Path] = []
    for raw in args.paths:
        p = Path(raw)
        files.extend(sorted(p.glob("*.xlsx")) if p.is_dir() else [p])
    if not files:
        print("No se encontraron archivos .xlsx", file=sys.stderr)
        sys.exit(1)

    onus: List[Dict[str, Any]] = []
    for f in files:
        rows = read_report(f)
        print(f"{f.name}: {len(rows)} ONUs")
        onus.extend(rows)

    snap_dir = log_dir / "onu-snapshots"
    previous = find_previous_snapshot(snap_dir, report_date)
    result = analyze(onus, previous, cfg)

    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / f"{report_date}.json").write_text(json.dumps(build_snapshot(onus)), encoding="utf-8")
    keep = int(cfg.get("snapshotRetentionDays", 30))
    for old in sorted(snap_dir.glob("*.json"))[:-keep]:
        old.unlink()

    csv_path = log_dir / "onu-reports" / f"{report_date}-pon.csv"
    write_pon_csv(result, csv_path)
    summary = build_telegram_summary(result, report_date, int(cfg.get("maxTelegramItems", 15)))
    print(summary)
    print(f"Detalle por PON: {csv_path}")

    if not args.skip_influx_write:
        import qoe_probe
        influx = config.get("influx", {})
        try:
            token = qoe_probe.get_influx_token(influx, config_path.parent)
            url = (f"{influx['baseUrl'].rstrip('/')}/api/v2/write?org={influx['org']}"
                   f"&bucket={influx['bucket']}&precision=ms")
            qoe_probe.write_to_influx(url, token, "\n".join(
                influx_lines(result, config.get("probe", {}).get("probeId", "unknown"), int(time.time() * 1000))), 30)
            print("Resumen por OLT escrito en InfluxDB (onu_olt_health).")
        except Exception as e:
            print(f"No se pudo escribir en InfluxDB: {e}", file=sys.stderr)

    if not args.skip_telegram:
        import qoe_telegram
        if qoe_telegram.is_configured():
            print("Telegram: enviado" if qoe_telegram.send_message(summary) else "Telegram: no se pudo enviar")


if __name__ == "__main__":
    main()
