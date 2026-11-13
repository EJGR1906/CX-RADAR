import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_heartbeat as hb  # noqa: E402


def chk(name, kind, reachable=True, degraded=False):
    return {"name": name, "kind": kind, "reachable": reachable, "degraded": degraded,
            "latency_ms": 10.0, "jitter_ms": 1.0, "loss_pct": 0.0, "max_latency_ms": 40.0}


class TestClassify(unittest.TestCase):
    def test_ok(self):
        r = hb.classify({"reachable": True}, [chk("i", "inter"), chk("e", "external")])
        self.assertEqual(r["status"], "ok")

    def test_access_down(self):
        r = hb.classify({"reachable": True}, [chk("i", "inter", False), chk("e", "external", False)])
        self.assertEqual(r["status"], "caida_acceso")

    def test_local_router_down(self):
        r = hb.classify({"reachable": False}, [chk("i", "inter", False), chk("e", "external", False)])
        self.assertEqual(r["status"], "caida_router_local")

    def test_transit_down(self):
        r = hb.classify({"reachable": True}, [chk("i", "inter"), chk("e", "external", False)])
        self.assertEqual(r["status"], "caida_transito")

    def test_degraded(self):
        r = hb.classify(None, [chk("i", "inter", degraded=True), chk("e", "external")])
        self.assertEqual(r["status"], "degradado")
        self.assertEqual(r["degraded"], ["i"])


class TestAlertState(unittest.TestCase):
    def run_seq(self, statuses, fail=2, recover=2):
        state, actions = {}, []
        for i, s in enumerate(statuses):
            actions.append(hb.update_alert_state(state, s, 1000 * 60 * i, fail, recover))
        return state, actions

    def test_single_blip_does_not_alert(self):
        _, actions = self.run_seq(["ok", "caida_acceso", "ok", "ok"])
        self.assertEqual(actions, [None, None, None, None])

    def test_alert_after_two_and_recovery_after_two(self):
        state, actions = self.run_seq(["caida_acceso", "caida_acceso", "caida_acceso", "ok", "ok"])
        self.assertEqual(actions, [None, "alert", None, None, "recovery"])
        self.assertEqual(state["bad_since"], 0)  # la falla empezó en la primera corrida

    def test_escalation(self):
        _, actions = self.run_seq(["degradado", "degradado", "caida_acceso"])
        self.assertEqual(actions, [None, "alert", "escalate"])

    def test_flapping_keeps_original_start(self):
        state, actions = self.run_seq(["caida_acceso", "caida_acceso", "ok", "caida_acceso", "ok", "ok"])
        self.assertEqual(actions, [None, "alert", None, None, None, "recovery"])

    def test_recovery_message_has_duration(self):
        state = {"bad_since": 0}
        msg = hb.build_message("recovery", "p1", "hub", "ok", {}, [], state, 30 * 60 * 1000)
        self.assertIn("30 min", msg)
        self.assertNotIn("Diagnóstico", msg)


class TestNotify(unittest.TestCase):
    """Caso real HUB_BTO 10/11: caída de acceso 14:27-14:33 sin conexión para avisar."""

    def outage(self, telegram_up):
        state, sent = {}, []
        for i, s in enumerate(["caida_acceso", "caida_acceso", "caida_acceso", "ok", "ok"]):
            now = 1000 * 60 * i
            action = hb.update_alert_state(state, s, now, 2, 2)
            hb.notify(action, state,
                      lambda a: hb.build_message(a, "HUB_BTO", "Server-HUB", s, {}, [], state, now),
                      lambda m: (sent.append(m) or True) if telegram_up(s) else False)
        return state, sent

    def test_undelivered_alert_becomes_single_recovery_summary(self):
        state, sent = self.outage(lambda s: s == "ok")
        self.assertEqual(len(sent), 1)
        self.assertIn("RECUPERADO", sent[0])
        self.assertIn("no se pudo avisar", sent[0])
        self.assertIn(hb.status_text("caida_acceso"), sent[0])
        self.assertIn("3 min", sent[0])  # mala en los minutos 0, 1 y 2; estable desde el 3
        self.assertEqual(state.get("pending", []), [])
        self.assertNotIn("alert_undelivered", state)

    def test_delivered_alert_keeps_normal_flow(self):
        _, sent = self.outage(lambda s: True)
        self.assertEqual(len(sent), 2)
        self.assertIn("FALLA", sent[0])
        self.assertNotIn("no se pudo avisar", sent[1])

    def test_recovery_queued_if_telegram_still_down(self):
        state, sent = self.outage(lambda s: False)
        self.assertEqual(sent, [])
        self.assertEqual(len(state["pending"]), 1)
        self.assertIn("RECUPERADO", state["pending"][0])


class TestClassifyNewStates(unittest.TestCase):
    UP = [chk("i", "inter"), chk("e", "external")]
    DOWN = [chk("i", "inter", False), chk("e", "external", False)]

    def test_no_default_route_is_local(self):
        r = hb.classify({"present": False, "reachable": False}, self.DOWN)
        self.assertEqual(r["status"], "sin_red_local")

    def test_total_outage_without_isp_targets_is_access_not_transit(self):
        r = hb.classify({"present": True, "reachable": True}, [chk("e", "external", False)])
        self.assertEqual(r["status"], "caida_acceso")

    def test_dns_down_with_ip_connectivity(self):
        r = hb.classify({"reachable": True}, self.UP, dns={"system_ok": False, "public_ok": True})
        self.assertEqual(r["status"], "falla_dns")
        self.assertIn("DNS públicos", r["notes"][0])

    def test_unknown_dns_is_not_a_failure(self):
        r = hb.classify({"reachable": True}, self.UP, dns={"system_ok": None, "public_ok": None})
        self.assertEqual(r["status"], "ok")

    def test_intercepted_internet(self):
        self.assertEqual(hb.classify(None, self.UP, verified=False)["status"], "internet_interceptado")

    def test_outage_wins_over_dns_and_portal(self):
        r = hb.classify({"reachable": True}, self.DOWN, dns={"system_ok": False, "public_ok": False}, verified=False)
        self.assertEqual(r["status"], "caida_acceso")

    def test_microcuts(self):
        r = hb.classify(None, self.UP, blackout={"rounds": 3, "longest": 3, "all": 0}, interval_s=5)
        self.assertEqual(r["status"], "microcortes")
        self.assertIn("~15 s", r["notes"][0])

    def test_single_lost_round_is_not_a_microcut(self):
        r = hb.classify(None, self.UP, blackout={"rounds": 1, "longest": 1, "all": 0})
        self.assertEqual(r["status"], "ok")

    def test_every_status_has_code_severity_and_text(self):
        for status in hb.STATUS_CODES:
            self.assertIn(status, hb.SEVERITY)
            self.assertNotEqual(hb.status_text(status, "X"), status)
        self.assertEqual([hb.STATUS_CODES[s] for s in ("ok", "degradado", "caida_transito", "caida_acceso", "caida_router_local")],
                         [0, 1, 2, 3, 4])  # ya están en InfluxDB: no se pueden cambiar


class TestSampling(unittest.TestCase):
    def test_rounds_and_blackouts(self):
        addrs = [("a",), ("b",), None]
        calls = []

        def connect(addr, timeout):
            calls.append(addr)
            rnd = (len(calls) - 1) // 2
            return None if rnd in (1, 2) else 12.5

        matrix = hb.sample_rounds(addrs, 4, 0, 1.0, connect=connect)
        self.assertEqual(len(matrix), 4)
        self.assertEqual(matrix[0], [12.5, 12.5, None])
        self.assertEqual(hb.find_blackouts(matrix, addrs), {"rounds": 2, "longest": 2, "all": 0})

    def test_unresolved_only_targets_never_count_as_blackout(self):
        self.assertEqual(hb.find_blackouts([[None], [None]], [None])["rounds"], 0)

    def test_reachable_reflects_the_end_of_the_window(self):
        t = {"name": "x", "kind": "external", "addr": ("a",)}
        ended_down = hb.summarize_target(t, [10.0] * 7 + [None] * 3, {})
        ended_up = hb.summarize_target(t, [None] * 7 + [10.0] * 3, {})
        self.assertFalse(ended_down["reachable"])
        self.assertTrue(ended_up["reachable"])
        self.assertEqual(ended_up["loss_pct"], 70.0)

    def test_one_lost_sample_of_ten_is_not_degraded(self):
        t = {"name": "x", "kind": "inter", "addr": ("a",)}
        self.assertFalse(hb.summarize_target(t, [10.0] * 9 + [None], {"maxLossPercentage": 20})["degraded"])
        self.assertTrue(hb.summarize_target(t, [None, 10.0, None, 10.0, None] + [10.0] * 5, {"maxLossPercentage": 20})["degraded"])

    def test_cached_ip_is_used_when_dns_fails(self):
        cache = {"a.example": "10.1.1.1"}
        r = hb.resolve_targets([{"name": "a", "host": "a.example", "port": 80}], cache, resolver=lambda h, p, t: None)
        self.assertEqual(r[0]["addr"][1][:2], ("10.1.1.1", 80))
        self.assertTrue(r[0]["ip_cached"])


class TestDnsAndHttp(unittest.TestCase):
    def serve_dns(self, answer=True):
        import socket
        import struct
        import threading
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", 0))
        sock.settimeout(3)
        port = sock.getsockname()[1]

        def loop():
            try:
                data, addr = sock.recvfrom(512)
                tid = data[:2]
                flags = 0x8180 if answer else 0x8183  # 3 = NXDOMAIN
                head = tid + struct.pack(">HHHHH", flags, 1, 1 if answer else 0, 0, 0)
                body = data[12:]
                if answer:
                    body += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + bytes([1, 2, 3, 4])
                sock.sendto(head + body, addr)
            except OSError:
                pass
            finally:
                sock.close()

        threading.Thread(target=loop, daemon=True).start()
        return port

    def query(self, port):
        import socket
        real = socket.socket

        class Redirect(real):
            def sendto(self, data, addr):
                return super().sendto(data, ("127.0.0.1", port))

        from unittest import mock
        with mock.patch.object(socket, "socket", Redirect):
            return hb.dns_query("127.0.0.1", "www.example.com", 1.0)

    def test_dns_answer_is_ok(self):
        self.assertTrue(self.query(self.serve_dns(True))["ok"])

    def test_dns_nxdomain_is_not_ok(self):
        self.assertFalse(self.query(self.serve_dns(False))["ok"])

    def test_dns_no_server_times_out(self):
        self.assertFalse(hb.dns_query("127.0.0.1", "www.example.com", 0.2)["ok"])

    def test_summarize_dns_needs_both_paths_to_fail(self):
        sys_bad = [{"kind": "system", "ok": False}, {"kind": "public", "ok": True}]
        self.assertFalse(hb.summarize_dns([{"ok": False}], sys_bad)["system_ok"])
        self.assertTrue(hb.summarize_dns([{"ok": True}], sys_bad)["system_ok"])  # DoH o router que no acepta consultas directas
        self.assertIsNone(hb.summarize_dns([], [])["system_ok"])

    def http_server(self, status, location=None):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_port}/x"

    def test_http_get_reports_status_without_following_redirects(self):
        self.assertEqual(hb.http_get(self.http_server(204), 2)["status"], 204)
        r = hb.http_get(self.http_server(302, "http://127.0.0.1:1/login"), 2)
        self.assertEqual((r["status"], r["error"]), (302, ""))

    def test_http_get_connection_refused_is_an_error_not_an_exception(self):
        r = hb.http_get("http://127.0.0.1:1/", 1)
        self.assertEqual(r["status"], 0)
        # Linux y macOS rechazan la conexión al instante; Windows reintenta y termina en timeout.
        self.assertIn(r["error"], ("connect", "timeout"))

    def test_verify_internet(self):
        ok = self.http_server(204)
        portal = self.http_server(302, "http://portal/login")
        self.assertTrue(hb.verify_internet([{"url": ok}], 2))
        self.assertFalse(hb.verify_internet([{"url": portal}], 2))
        self.assertTrue(hb.verify_internet([{"url": portal}, {"url": ok}], 2))
        self.assertIsNone(hb.verify_internet([]))

    def test_check_service_expected_codes(self):
        up = hb.check_service({"service": "S", "name": "n", "url": self.http_server(302), "expectedHttpCodes": [200, 302]}, 2)
        down = hb.check_service({"service": "S", "name": "n", "url": self.http_server(503), "expectedHttpCodes": [200]}, 2)
        self.assertTrue(up["available"])
        self.assertEqual((down["available"], down["error_class"], down["reason"]), (False, "http_status", "HTTP 503"))
        self.assertEqual(hb.classify_services([up, down])["S"]["status"], "parcial")


class TestSoftThreshold(unittest.TestCase):
    def seq(self, statuses):
        state, actions = {}, []
        for i, s in enumerate(statuses):
            actions.append(hb.update_alert_state(state, s, 60000 * i, 2, 5, 5))
        return state, actions

    def test_degraded_needs_five_runs(self):
        _, actions = self.seq(["degradado"] * 5)
        self.assertEqual(actions, [None] * 4 + ["alert"])

    def test_outage_after_degraded_still_needs_two_outage_runs(self):
        _, actions = self.seq(["degradado", "degradado", "degradado", "caida_acceso", "caida_acceso"])
        self.assertEqual(actions, [None, None, None, None, "alert"])

    def test_incident_closes_after_five_good_runs(self):
        state, actions = self.seq(["caida_acceso"] * 2 + ["ok"] * 4 + ["caida_acceso"] + ["ok"] * 5)
        self.assertEqual([a for a in actions if a], ["alert", "recovery"])
        self.assertEqual(state["cuts"], 2)


if __name__ == "__main__":
    unittest.main()
