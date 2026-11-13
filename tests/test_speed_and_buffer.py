"""Aviso de velocidad bajo el plan, búfer de reenvío de la sonda completa y resumen diario."""

import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_heartbeat as hb  # noqa: E402
import qoe_probe  # noqa: E402
import qoe_speed_alert as sa  # noqa: E402


def report(service, down, up=300.0, available=True):
    return {"type": "speedtest", "service": service, "available": available, "download_mbps": down, "upload_mbps": up}


PROBE = {"probeId": "p1", "site": "hub", "planDownMbps": 600, "planUpMbps": 600}


class TestSpeedAlert(unittest.TestCase):
    def test_no_plan_no_evaluation(self):
        self.assertIsNone(sa.evaluate([report("A", 10)], {"probeId": "p1"}, {}))

    def test_no_measurements_is_not_low_speed(self):
        self.assertIsNone(sa.evaluate([report("A", 0, available=False)], PROBE, {}))

    def test_one_slow_server_does_not_blame_the_line(self):
        r = sa.evaluate([report("Lento", 40), report("Rapido", 580)], PROBE, {})
        self.assertEqual(r["status"], "ok")

    def test_all_targets_below_half_plan_is_low(self):
        r = sa.evaluate([report("A", 120, 500), report("B", 250, 520)], PROBE, {})
        self.assertEqual(r["status"], "velocidad_baja")
        self.assertIn("250 Mbps de 600 contratados (42 %)", r["low"][0])
        self.assertEqual(len(r["low"]), 1)  # la subida está bien

    def test_alert_on_second_low_run_and_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            send = lambda m: sent.append(m) or True  # noqa: E731
            cfg = {"probe": PROBE}
            low, good = [report("A", 100, 100)], [report("A", 590, 580)]
            actions = [sa.process(cfg, r, Path(d), Path(d), send) for r in (low, low, low, good, good)]
            self.assertEqual(actions, [None, "alert", None, None, "recovery"])
            self.assertIn("VELOCIDAD BAJA", sent[0])
            self.assertIn("Subida: 100 Mbps de 600", sent[0])
            self.assertIn("VELOCIDAD RECUPERADA", sent[1])

    def test_alert_is_retried_if_telegram_fails(self):
        with tempfile.TemporaryDirectory() as d:
            sent = []
            cfg = {"probe": PROBE}
            low = [report("A", 100)]
            sa.process(cfg, low, Path(d), Path(d), lambda m: False)
            sa.process(cfg, low, Path(d), Path(d), lambda m: False)
            sa.process(cfg, low, Path(d), Path(d), lambda m: sent.append(m) or True)
            self.assertEqual(len(sent), 1)

    def test_outage_run_does_not_count(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sa.process({"probe": PROBE}, [report("A", 0, available=False)], Path(d), Path(d), lambda m: True))
            self.assertFalse((Path(d) / sa.STATE_FILE).exists())


class TestProbeBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.buffer = Path(self.tmp.name) / "probe-buffer.lp"
        self.written = []
        self._log = qoe_probe.log_message
        qoe_probe.log_message = lambda *a, **k: None
        self.addCleanup(lambda: setattr(qoe_probe, "log_message", self._log))

    def down(self, url, token, payload, timeout):
        raise RuntimeError("InfluxDB write failed: <urlopen error timed out>")

    def up(self, url, token, payload, timeout):
        self.written.extend(payload.splitlines())

    def test_failed_write_is_kept_and_resent_in_order(self):
        with self.assertRaises(RuntimeError):
            qoe_probe.write_lines_with_buffer("u", "t", ["a 1", "b 1"], 1, self.buffer, writer=self.down)
        with self.assertRaises(RuntimeError):
            qoe_probe.write_lines_with_buffer("u", "t", ["c 1"], 1, self.buffer, writer=self.down)
        qoe_probe.append_to_buffer(self.buffer, ["resumen 1"])
        qoe_probe.write_lines_with_buffer("u", "t", ["d 1"], 1, self.buffer, writer=self.up)
        self.assertEqual(self.written, ["a 1", "b 1", "c 1", "resumen 1", "d 1"])
        self.assertFalse(self.buffer.exists())

    def test_rejected_new_lines_are_not_buffered(self):
        def reject(url, token, payload, timeout):
            raise RuntimeError("InfluxDB write failed. Status code: 422. Response body: x")
        with self.assertRaises(RuntimeError):
            qoe_probe.write_lines_with_buffer("u", "t", ["mala"], 1, self.buffer, writer=reject)
        self.assertFalse(self.buffer.exists())

    def test_buffer_is_capped(self):
        with self.assertRaises(RuntimeError):
            qoe_probe.write_lines_with_buffer("u", "t", [f"l {i}" for i in range(50)], 1, self.buffer, writer=self.down, max_lines=10)
        self.assertEqual(len(self.buffer.read_text(encoding="utf-8").splitlines()), 10)


LOG = """[2026-11-12T00:00:21] [INFO] Heartbeat ok (a=1.0ms) | router=ok dns=ok/ok web=ok perdida=0.0% cortes=0s | servicios: Outlook=ok, Teams=ok [45.2s]
[2026-11-12T00:01:21] [INFO] Heartbeat microcortes (a=1.0ms) | router=ok dns=ok/ok web=ok perdida=20.0% cortes=15s | servicios: Outlook=caido(3/3), Teams=ok [45.2s]
[2026-11-12T00:02:21] [WARNING] Heartbeat: no se pudo escribir en InfluxDB, se guarda para reenviar: x
[2026-11-12T00:02:21] [INFO] Heartbeat caida_acceso (a=X) | router=ok dns=X/X web=X perdida=100.0% cortes=45s [50.1s]
[2026-11-12T00:03:21] [INFO] Heartbeat caida_acceso (a=X) | router=ok dns=X/X web=X perdida=100.0% cortes=45s [50.1s] -> alert
[2026-11-12T00:04:21] [INFO] Heartbeat ok (a=1.0ms) | router=ok dns=ok/ok web=ok perdida=0.0% cortes=0s | servicios: Outlook=parcial(1/3), Teams=ok [45.2s]
[2026-11-12T00:05:21] [INFO] Heartbeat falla_dns (a=1.0ms) | router=ok dns=X/ok web=ok perdida=0.0% cortes=0s [45.2s]
[2026-11-12T00:06:21] [INFO] Heartbeat degradado (a=90.0ms)
""".splitlines()


class TestDailySummary(unittest.TestCase):
    def test_counts(self):
        s = hb.summarize_day(LOG)
        self.assertEqual((s["runs"], s["down_minutes"], s["cuts"], s["blackout_s"], s["degraded_minutes"]), (7, 3, 2, 15, 2))
        self.assertEqual(s["services"], {"Outlook": 2})
        self.assertEqual(s["uptime_pct"], 57.14)

    def test_empty_log(self):
        self.assertIsNone(hb.summarize_day(["cualquier cosa"]))

    def test_sent_once_per_day_after_the_hour(self):
        with tempfile.TemporaryDirectory() as d:
            log_dir = Path(d)
            (log_dir / "qoe-heartbeat-2026-11-12.log").write_text("\n".join(LOG), encoding="utf-8")
            sent, state = [], {}
            send = lambda m: sent.append(m) or True  # noqa: E731
            early = datetime.datetime(2026, 11, 13, 7, 59)
            late = datetime.datetime(2026, 11, 13, 8, 1)
            self.assertFalse(hb.maybe_send_daily_summary(state, {}, log_dir, "p1", "hub", send, early))
            self.assertTrue(hb.maybe_send_daily_summary(state, {}, log_dir, "p1", "hub", send, late))
            self.assertFalse(hb.maybe_send_daily_summary(state, {}, log_dir, "p1", "hub", send, late))
            self.assertEqual(len(sent), 1)
            self.assertIn("RESUMEN del 12/11/2026", sent[0])
            self.assertIn("Cortes: 2 (3 min sin internet)", sent[0])
            self.assertIn("Servicio Outlook: 2 min con fallas", sent[0])
            self.assertIn("Minutos sin medición: 1433", sent[0])

    def test_disabled_with_negative_hour(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(hb.maybe_send_daily_summary({}, {"dailySummaryHour": -1}, Path(d), "p", "s", lambda m: True))

    def test_retry_if_telegram_fails(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "qoe-heartbeat-2026-11-12.log").write_text("\n".join(LOG), encoding="utf-8")
            state = {}
            now = datetime.datetime(2026, 11, 13, 9, 0)
            self.assertFalse(hb.maybe_send_daily_summary(state, {}, Path(d), "p", "s", lambda m: False, now))
            self.assertTrue(hb.maybe_send_daily_summary(state, {}, Path(d), "p", "s", lambda m: True, now))


if __name__ == "__main__":
    unittest.main()
