"""Banco de inyección de fallas del monitor de cada minuto.

Cada prueba simula una falla de red concreta, corre `qoe_heartbeat.run()` completo
(muestreo, diagnóstico, InfluxDB, estado y Telegram) minuto a minuto y exige el
diagnóstico, el número de avisos y el minuto en que se avisa. La tabla de
`docs/qa/detection-matrix.md` se apoya en estas pruebas: lo que el producto
afirma detectar está aquí o no se afirma.
"""

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_heartbeat as hb  # noqa: E402
import qoe_probe  # noqa: E402
import qoe_telegram  # noqa: E402
import qoe_throughput  # noqa: E402

ROUNDS = 10
GATEWAY_IP = "192.168.1.1"
HOST_IPS = {"isp-a.example": "10.0.0.1", "isp-b.example": "10.0.0.2", "www.site.example": "93.0.0.1"}
TARGETS = [
    {"name": "isp-a", "host": "isp-a.example", "port": 8080, "kind": "isp"},
    {"name": "isp-b", "host": "isp-b.example", "port": 8080, "kind": "isp"},
    {"name": "ancla-1", "host": "1.1.1.1", "port": 443, "kind": "external"},
    {"name": "ancla-2", "host": "8.8.8.8", "port": 443, "kind": "external"},
    {"name": "sitio", "host": "www.site.example", "port": 443, "kind": "external"},
]
IP_TO_NAME = {"10.0.0.1": "isp-a", "10.0.0.2": "isp-b", "1.1.1.1": "ancla-1", "8.8.8.8": "ancla-2", "93.0.0.1": "sitio"}
SERVICE_CHECKS = [
    {"service": "Outlook", "name": "outlook-m365", "url": "https://outlook.test/health", "expectedHttpCodes": [200]},
    {"service": "Outlook", "name": "outlook-web", "url": "https://outlook.test/mail", "expectedHttpCodes": [200, 302]},
    {"service": "Teams", "name": "teams-web", "url": "https://teams.test/", "expectedHttpCodes": [200, 302]},
]
CONFIG = {
    "probe": {"probeId": "sonda-prueba", "site": "laboratorio", "isp": "ProveedorX"},
    "influx": {"baseUrl": "https://influx.test", "org": "o", "bucket": "b"},
    "probeRun": {"logDirectory": "logs"},
    "heartbeat": {
        "failThreshold": 2, "degradedFailThreshold": 5, "recoverThreshold": 5,
        "windowSeconds": 0.09, "sampleIntervalSeconds": 0.01, "timeoutSeconds": 0.05,
        "maxLatencyMs": {"isp": 40, "external": 150}, "maxLossPercentage": 20,
        "targets": TARGETS, "dnsNames": ["www.site.example"],
        "dnsServers": [{"name": "publico", "ip": "1.1.1.1"}],
        "connectivityChecks": [{"url": "http://check.test/generate_204", "expectedStatus": 204}],
        "serviceFailThreshold": 3, "serviceRecoverThreshold": 2, "serviceChecks": SERVICE_CHECKS,
    },
}


class Minute:
    """Condiciones de la red durante una corrida (un minuto)."""

    def __init__(self, **kw):
        self.route = kw.get("route", True)
        self.gateway = kw.get("gateway", True)
        self.up = kw.get("up", lambda name, rnd: 10.0)       # ms o None por destino y ronda
        self.dns_system = kw.get("dns_system", True)
        self.dns_public = kw.get("dns_public", True)
        self.web_status = kw.get("web_status", 204)          # respuesta de la página de verificación
        self.services = kw.get("services", {})               # url -> (status, error)
        self.influx = kw.get("influx", True)                 # True, False (sin red) o un código HTTP
        self.telegram = kw.get("telegram", True)


def all_down(name, rnd):
    return None


def total_outage(**kw):
    return Minute(up=all_down, dns_system=False, dns_public=False, web_status=0, influx=False, telegram=False, **kw)


OK = Minute


class Lab:
    """Corre el heartbeat real contra una red simulada."""

    def __init__(self, test: unittest.TestCase):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        self.log_dir = self.root / "logs"
        self.log_dir.mkdir()
        self.config_path = self.root / "config" / "probe-catalog.json"
        self.config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.sent, self.influx_lines, self.statuses, self.actions = [], [], [], []
        self.minute_index = 0
        self.state_path = self.log_dir / "heartbeat-state.json"

    def run_minute(self, m: Minute) -> str:
        calls = {}

        def connect(addr, timeout_s):
            name = IP_TO_NAME[addr[1][0]]
            rnd = calls.get(name, 0)
            calls[name] = rnd + 1
            return m.up(name, rnd) if m.route else None

        def resolve(host, port=443, timeout_s=3.0):
            if host in IP_TO_NAME:
                return hb.addr_from_ip(host, port)
            return hb.addr_from_ip(HOST_IPS[host], port) if (m.dns_system and m.route) else None

        def dns(server, name, timeout_s=2.0):
            ok = m.route and (m.dns_system if server == GATEWAY_IP else m.dns_public)
            return {"ok": ok, "ms": 5.0 if ok else 0.0}

        def get(url, timeout_s=8.0, **kw):
            if not m.route:
                return {"status": 0, "error": "connect", "ms": 1.0, "body_len": 0}
            if "check.test" in url:
                return {"status": m.web_status, "error": "" if m.web_status else "timeout", "ms": 1.0, "body_len": 0}
            status, error = m.services.get(url, (200, ""))
            return {"status": status, "error": error, "ms": 20.0, "body_len": 10}

        def influx(url, token, payload, timeout):
            if m.influx is True:
                self.influx_lines.extend(payload.splitlines())
                return True
            if m.influx is False:
                raise RuntimeError("InfluxDB write failed: <urlopen error getaddrinfo failed>")
            raise RuntimeError(f"InfluxDB write failed. Status code: {m.influx}. Response body: bad line")

        def telegram(text, creds=None, timeout=10.0):
            if m.telegram:
                self.sent.append(text)
            return bool(m.telegram)

        now_ms = 1_800_000_000_000 + self.minute_index * 60_000
        self.minute_index += 1
        args = argparse.Namespace(config_path=str(self.config_path), skip_influx_write=False, skip_telegram=False, rounds=0)
        logged = []
        patches = [
            mock.patch.object(hb, "has_default_route", lambda: m.route),
            mock.patch.object(hb, "get_local_network", lambda state, now, force=False: {"gw": GATEWAY_IP, "dns": [GATEWAY_IP]}),
            mock.patch.object(hb, "check_gateway", lambda ip: {"present": True, "reachable": m.gateway, "latency_ms": 1.0}),
            mock.patch.object(hb, "dns_query", dns),
            mock.patch.object(hb, "http_get", get),
            mock.patch.object(hb, "_now_ms", lambda: now_ms),
            mock.patch.object(qoe_throughput, "resolve_host", resolve),
            mock.patch.object(qoe_throughput, "tcp_connect_ms", connect),
            mock.patch.object(qoe_probe, "write_to_influx", influx),
            mock.patch.object(qoe_probe, "get_influx_token", lambda cfg, d, quiet=False: "token"),
            mock.patch.object(qoe_probe, "log_message", lambda msg, level="INFO": logged.append((level, msg))),
            mock.patch.object(qoe_telegram, "send_message", telegram),
            mock.patch.object(qoe_telegram, "get_credentials", lambda p=None: {"token": "t", "chat_id": "c"}),
        ]
        for p in patches:
            p.start()
        try:
            hb.run(args, self.root, self.log_dir)
        finally:
            for p in patches:
                p.stop()
        self.logged = logged
        result = [msg for _, msg in logged if msg.startswith("Heartbeat ") and not msg.startswith("Heartbeat:")][-1]
        status = result.split()[1]
        self.statuses.append(status)
        self.actions.append(result.split(" -> ")[1] if " -> " in result else "")
        return status

    def run_all(self, minutes):
        for m in minutes:
            self.run_minute(m)
        return self.statuses

    def state(self):
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def alerts(self, word="FALLA"):
        return [s for s in self.sent if f"\n{word}" in s]

    def status_line_fields(self, index=-1):
        lines = [ln for ln in self.influx_lines if ln.startswith("qoe_heartbeat_status")]
        return lines[index]


class TestNetworkFaults(unittest.TestCase):
    def setUp(self):
        self.lab = Lab(self)

    def test_healthy_network_is_ok_and_silent(self):
        self.assertEqual(self.lab.run_all([OK()] * 3), ["ok"] * 3)
        self.assertEqual(self.lab.sent, [])
        self.assertIn("status_code=0i", self.lab.status_line_fields())

    def test_total_outage_is_access_down_alerted_on_second_minute(self):
        self.lab.run_all([OK()] + [total_outage()] * 4 + [OK()] * 5)
        self.assertEqual(self.lab.statuses[1:5], ["caida_acceso"] * 4)
        self.assertEqual(self.lab.actions[1], "")
        self.assertEqual(self.lab.actions[2], "alert")
        # Sin conexión no hay Telegram: un solo mensaje al volver, con diagnóstico y duración.
        self.assertEqual(len(self.lab.sent), 1)
        self.assertIn("RECUPERADO", self.lab.sent[0])
        self.assertIn("no se pudo avisar", self.lab.sent[0])
        self.assertIn("ProveedorX", self.lab.sent[0])
        self.assertIn("4 min", self.lab.sent[0])

    def test_outage_metrics_are_resent_when_influx_returns(self):
        self.lab.run_all([OK()] + [total_outage()] * 3 + [OK()])
        status_lines = [ln for ln in self.lab.influx_lines if ln.startswith("qoe_heartbeat_status")]
        self.assertEqual(len(status_lines), 5)  # no se pierde ningún minuto de la caída
        self.assertEqual(sum("status_code=3i" in ln for ln in status_lines), 3)
        self.assertFalse((self.lab.log_dir / "heartbeat-buffer.lp").exists())

    def test_dns_outage_is_diagnosed_as_dns_not_as_degraded(self):
        dns_down = Minute(dns_system=False)  # las anclas por IP y los DNS públicos responden
        self.lab.run_all([OK(), dns_down, dns_down])
        self.assertEqual(self.lab.statuses[1:], ["falla_dns", "falla_dns"])
        self.assertEqual(self.lab.actions[2], "alert")
        self.assertIn("Falla de DNS", self.lab.sent[0])
        self.assertIn("DNS públicos", self.lab.sent[0])

    def test_dns_outage_without_cached_ips_is_still_dns(self):
        dns_down = Minute(dns_system=False)
        self.assertEqual(self.lab.run_all([dns_down, dns_down]), ["falla_dns", "falla_dns"])

    def test_transit_outage_isp_answers_internet_does_not(self):
        transit = Minute(up=lambda n, r: 10.0 if n.startswith("isp") else None, dns_public=False, web_status=0)
        self.lab.run_all([OK(), transit, transit])
        self.assertEqual(self.lab.statuses[1:], ["caida_transito"] * 2)
        self.assertIn("la red de ProveedorX responde, internet no", self.lab.sent[0])

    def test_unplugged_cable_is_local_not_the_isp(self):
        self.lab.run_all([OK(), total_outage(route=False), total_outage(route=False), OK(), OK(), OK(), OK(), OK()])
        self.assertEqual(self.lab.statuses[1:3], ["sin_red_local"] * 2)
        self.assertIn("status_code=8i", "\n".join(self.lab.influx_lines))
        self.assertIn("falla local, no del proveedor", self.lab.sent[0])

    def test_router_down_is_local_router(self):
        self.lab.run_all([OK(), total_outage(gateway=False), total_outage(gateway=False)])
        self.assertEqual(self.lab.statuses[1:], ["caida_router_local"] * 2)

    def test_captive_portal_is_not_reported_as_ok(self):
        portal = Minute(web_status=302, services={c["url"]: (302, "") for c in SERVICE_CHECKS})
        self.lab.run_all([OK(), portal, portal])
        self.assertEqual(self.lab.statuses[1:], ["internet_interceptado"] * 2)
        self.assertIn("portal cautivo", self.lab.sent[0])
        # Con internet interceptado no se culpa a los servicios externos.
        self.assertFalse(any("SERVICIO" in s for s in self.lab.sent))

    def test_high_latency_alerts_only_when_sustained_five_minutes(self):
        slow = Minute(up=lambda n, r: 80.0 if n.startswith("isp") else 10.0)
        self.lab.run_all([OK()] + [slow] * 5)
        self.assertEqual(self.lab.statuses[1:], ["degradado"] * 5)
        self.assertEqual(self.lab.actions[1:5], [""] * 4)
        self.assertEqual(self.lab.actions[5], "alert")
        self.assertIn("80.0 ms (umbral 40)", self.lab.sent[0])

    def test_short_latency_blip_does_not_alert(self):
        slow = Minute(up=lambda n, r: 80.0)
        self.lab.run_all([OK(), slow, slow, OK(), slow, OK()])
        self.assertEqual(self.lab.sent, [])

    def test_ten_percent_loss_is_measured_but_not_an_alarm(self):
        lossy = Minute(up=lambda n, r: None if r == 4 else 10.0)  # 1 ronda de 10 perdida, pero no seguida
        self.assertEqual(self.lab.run_minute(lossy), "ok")
        self.assertIn("loss_pct=10.0", self.lab.status_line_fields())

    def test_thirty_percent_loss_on_one_target_is_degraded(self):
        lossy = Minute(up=lambda n, r: None if (n == "isp-a" and r in (1, 4, 6)) else 10.0)
        self.assertEqual(self.lab.run_minute(lossy), "degradado")
        self.assertIn("check=isp-a,", "\n".join(ln for ln in self.lab.influx_lines if "loss_pct=30.0" in ln))

    def test_twenty_second_microcut_is_seen_and_measured(self):
        cut = Minute(up=lambda n, r: None if 3 <= r <= 6 else 10.0)  # 4 rondas seguidas sin respuesta
        self.assertEqual(self.lab.run_all([OK(), cut, OK()]), ["ok", "microcortes", "ok"])
        line = [ln for ln in self.lab.influx_lines if ln.startswith("qoe_heartbeat_status")][1]
        self.assertIn("status_code=6i", line)
        self.assertIn("blackout_rounds=4i", line)
        self.assertEqual(self.lab.sent, [])  # un microcorte aislado se registra, no despierta a nadie

    def test_repeated_microcuts_alert(self):
        cut = Minute(up=lambda n, r: None if 2 <= r <= 4 else 10.0)
        self.lab.run_all([cut] * 5)
        self.assertEqual(self.lab.actions[4], "alert")
        self.assertIn("Microcortes", self.lab.sent[0])

    def test_outage_starting_mid_window_is_already_a_cut(self):
        starts = Minute(up=lambda n, r: 10.0 if r < 5 else None, telegram=False)
        self.assertEqual(self.lab.run_minute(starts), "caida_acceso")

    def test_flapping_is_one_incident_with_cut_count(self):
        down = Minute(up=all_down, dns_system=False, dns_public=False, web_status=0)  # Telegram simulado arriba
        self.lab.run_all([down, down, OK(), OK(), down, down, OK(), OK(), down, down] + [OK()] * 5)
        self.assertEqual(len(self.lab.alerts("FALLA")), 1)
        recoveries = [s for s in self.lab.sent if "RECUPERADO" in s]
        self.assertEqual(len(recoveries), 1)
        self.assertIn("Cortes durante el incidente: 3", recoveries[0])
        self.assertIn("10 min", recoveries[0])

    def test_degraded_then_outage_escalates(self):
        slow = Minute(up=lambda n, r: 80.0)
        down = Minute(up=all_down, dns_system=False, dns_public=False, web_status=0)
        self.lab.run_all([slow] * 5 + [down])
        self.assertEqual(self.lab.actions[4:], ["alert", "escalate"])
        self.assertIn("EMPEORA", self.lab.sent[1])


class TestExternalServices(unittest.TestCase):
    OUTLOOK_DOWN = {"https://outlook.test/health": (0, "reset"), "https://outlook.test/mail": (500, "")}

    def setUp(self):
        self.lab = Lab(self)

    def test_outlook_outage_is_reported_as_external_service(self):
        down = Minute(services=self.OUTLOOK_DOWN)
        self.lab.run_all([OK()] + [down] * 3 + [OK(), OK()])
        self.assertEqual(self.lab.statuses, ["ok"] * 6)  # la red está bien
        self.assertEqual(self.lab.actions[1:3], ["", ""])
        self.assertEqual(self.lab.actions[3], "Outlook:alert")
        msg = self.lab.sent[0]
        self.assertIn("SERVICIO EXTERNO CAÍDO: Outlook (2 de 2 pruebas fallan)", msg)
        self.assertIn("la falla es del servicio, no de la conexión", msg)
        self.assertIn("outlook-m365: conexión cortada", msg)
        self.assertIn("outlook-web: HTTP 500", msg)
        self.assertIn("SERVICIO RECUPERADO: Outlook", self.lab.sent[1])
        self.assertFalse(any("Teams" in s for s in self.lab.sent))

    def test_service_checks_are_written_to_influx(self):
        self.lab.run_minute(Minute(services=self.OUTLOOK_DOWN))
        lines = [ln for ln in self.lab.influx_lines if ln.startswith("qoe_service_check")]
        self.assertEqual(len(lines), 3)
        bad = [ln for ln in lines if "check=outlook-web" in ln][0]
        self.assertIn("service=Outlook", bad)
        self.assertIn("available=false", bad)
        self.assertIn("http_status=500i", bad)

    def test_partial_outlook_failure_says_partial(self):
        down = Minute(services={"https://outlook.test/mail": (503, "")})
        self.lab.run_all([down] * 3)
        self.assertIn("SERVICIO EXTERNO CON FALLAS: Outlook (1 de 2 pruebas fallan)", self.lab.sent[0])

    def test_services_are_not_blamed_while_the_network_is_down(self):
        down = Minute(up=all_down, dns_system=False, dns_public=False, web_status=0,
                      services={c["url"]: (0, "connect") for c in SERVICE_CHECKS})
        self.lab.run_all([down] * 4)
        self.assertFalse(any("SERVICIO" in s for s in self.lab.sent))
        self.assertFalse(any(ln.startswith("qoe_service_check") for ln in self.lab.influx_lines))


class TestProbeResilience(unittest.TestCase):
    def setUp(self):
        self.lab = Lab(self)

    def test_corrupt_state_file_does_not_kill_the_monitor(self):
        for garbage in ('{"bad_count": "x", "alerted": "si", "services": 5, "pending": {"a": 1}}', "{no es json", "[]"):
            self.lab.state_path.write_text(garbage, encoding="utf-8")
            self.assertEqual(self.lab.run_minute(OK()), "ok")
        self.assertEqual(self.lab.state()["bad_count"], 0)

    def test_rejected_buffer_is_set_aside_and_new_data_flows(self):
        (self.lab.log_dir / "heartbeat-buffer.lp").write_text("linea mala\n", encoding="utf-8")
        calls = []

        def writer(url, token, payload, timeout):
            calls.append(payload)
            if "linea mala" in payload:
                raise RuntimeError("InfluxDB write failed. Status code: 400. Response body: unable to parse")
            return True

        with mock.patch.object(qoe_probe, "log_message", lambda *a, **k: None):
            ok = hb.write_influx(["m f=1i 1"], CONFIG, self.lab.root / "config", self.lab.log_dir / "heartbeat-buffer.lp",
                                 writer=writer, token="t")
        self.assertTrue(ok)
        self.assertEqual(calls[-1], "m f=1i 1")
        self.assertFalse((self.lab.log_dir / "heartbeat-buffer.lp").exists())
        self.assertEqual(len(list(self.lab.log_dir.glob("heartbeat-buffer.rejected-*.lp"))), 1)

    def test_recovery_waits_for_telegram_and_is_sent_late(self):
        self.lab.run_all([total_outage()] * 3 + [Minute(telegram=False)] * 5)
        self.assertEqual(self.lab.sent, [])
        self.assertEqual(len(self.lab.state()["pending"]), 1)
        self.lab.run_minute(OK())
        self.assertEqual(len(self.lab.sent), 1)
        self.assertIn("enviado con retraso", self.lab.sent[0])
        self.assertEqual(self.lab.state()["pending"], [])

    def test_only_one_run_at_a_time_and_stale_lock_is_taken(self):
        lock = self.lab.log_dir / "heartbeat.lock"
        self.assertTrue(hb.acquire_lock(lock))
        self.assertFalse(hb.acquire_lock(lock))
        old = lock.stat().st_mtime - hb.LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        self.assertTrue(hb.acquire_lock(lock))
        hb.release_lock(lock)
        self.assertFalse(lock.exists())

    def test_internal_error_is_logged_and_notified_once(self):
        sent, logged = [], []
        with mock.patch.object(qoe_telegram, "send_message", lambda t, c=None, timeout=10.0: sent.append(t) or True), \
                mock.patch.object(qoe_telegram, "get_credentials", lambda p=None: {"token": "t", "chat_id": "c"}), \
                mock.patch.object(qoe_probe, "log_message", lambda msg, level="INFO": logged.append((level, msg))):
            hb.report_crash(self.lab.log_dir, self.lab.root, "Traceback...\nTypeError: boom", False)
            hb.report_crash(self.lab.log_dir, self.lab.root, "Traceback...\nTypeError: boom", False)
        self.assertEqual(len(sent), 1)
        self.assertIn("TypeError: boom", sent[0])
        self.assertEqual([lvl for lvl, _ in logged], ["ERROR", "ERROR"])

    def test_main_survives_an_exception_inside_run(self):
        logged = []
        argv = ["qoe_heartbeat.py", "--config-path", str(self.lab.config_path), "--skip-telegram"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(hb, "run", side_effect=TypeError("boom")), \
                mock.patch.object(qoe_probe, "log_message", lambda msg, level="INFO": logged.append((level, msg))):
            with self.assertRaises(SystemExit) as ctx:
                hb.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(any(lvl == "ERROR" and "boom" in msg for lvl, msg in logged))


class TestRealLogReplay(unittest.TestCase):
    """Log real del 12/11/2026: 13 avisos de FALLA con la lógica anterior, 4 cortes reales."""

    def test_november_12_produces_one_alert_per_real_outage(self):
        fixture = Path(__file__).parent / "fixtures" / "heartbeat-2026-11-12-statuses.txt"
        rows = [ln.split() for ln in fixture.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
        state, alerts = {}, []
        for i, (hhmm, status) in enumerate(rows):
            action = hb.update_alert_state(state, status, i * 60000, 2, 5, 5)
            if action == "alert":
                alerts.append((hhmm, status))
        self.assertEqual([s for _, s in alerts], ["caida_acceso"] * 4)
        self.assertEqual([h[:2] for h, _ in alerts], ["12", "12", "13", "15"])


if __name__ == "__main__":
    unittest.main()
