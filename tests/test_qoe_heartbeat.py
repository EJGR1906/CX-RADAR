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
        self.assertIn(hb.STATUS_TEXT["caida_acceso"], sent[0])
        self.assertIn("4 min", sent[0])
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


if __name__ == "__main__":
    unittest.main()
