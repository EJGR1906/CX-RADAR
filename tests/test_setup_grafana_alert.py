import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import setup_grafana_alert as ga  # noqa: E402


class FakeGrafana:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET":
            return self.existing.get(path)
        return {}


class TestBuilders(unittest.TestCase):
    def test_rule_alerts_per_probe_and_on_no_data(self):
        rule = ga.build_rule("ds1", "qoe_metrics", 3)
        self.assertEqual(rule["uid"], ga.RULE_UID)
        self.assertEqual(rule["noDataState"], "Alerting")
        self.assertEqual(rule["labels"], {"app": "cx-radar"})
        flux = rule["data"][0]["model"]["query"]
        self.assertIn('bucket: "qoe_metrics"', flux)
        self.assertIn('group(columns: ["probe_id", "site"])', flux)
        self.assertIn("qoe_heartbeat_status", flux)
        self.assertEqual(rule["data"][2]["model"]["conditions"][0]["evaluator"]["params"], [3])

    def test_no_middle_dot_in_texts(self):
        rule = ga.build_rule("ds1", "b", 3)
        for text in [ga.TELEGRAM_MESSAGE, *rule["annotations"].values()]:
            self.assertNotIn("·", text)

    def test_merge_route_keeps_other_routes(self):
        policy = {"receiver": "default", "routes": [{"receiver": "otro"}, {"receiver": ga.CONTACT_NAME, "x": 1}]}
        merged = ga.merge_route(policy, ga.build_route())
        receivers = [r["receiver"] for r in merged["routes"]]
        self.assertEqual(receivers, [ga.CONTACT_NAME, "otro"])
        self.assertEqual(merged["receiver"], "default")
        self.assertNotIn("x", merged["routes"][0])

    def test_pick_datasource_flux(self):
        ds = [{"uid": "a", "type": "influxdb", "jsonData": {"version": "InfluxQL"}},
              {"uid": "b", "type": "influxdb", "jsonData": {"version": "Flux"}},
              {"uid": "c", "type": "prometheus"}]
        self.assertEqual(ga.pick_datasource(ds)["uid"], "b")
        with self.assertRaises(ga.GrafanaError):
            ga.pick_datasource(ds[:1])


class TestApply(unittest.TestCase):
    def test_dry_run_changes_nothing(self):
        g = FakeGrafana()
        ga.apply(g, ga.build_rule("ds", "b", 3), ga.build_contact_point("t", "c"), dry_run=True)
        self.assertTrue(all(m == "GET" for m, _, _ in g.calls))

    def test_creates_when_missing_and_updates_when_present(self):
        g = FakeGrafana()
        ga.apply(g, ga.build_rule("ds", "b", 3), ga.build_contact_point("t", "c"), dry_run=False)
        writes = [(m, p) for m, p, _ in g.calls if m != "GET"]
        self.assertIn(("POST", "/api/v1/provisioning/alert-rules"), writes)
        self.assertIn(("POST", "/api/v1/provisioning/contact-points"), writes)

        g = FakeGrafana({
            "/api/folders": [{"uid": "ftwbcl", "title": "CX-RADAR"}],
            "/api/v1/provisioning/contact-points": [{"uid": ga.CONTACT_UID, "name": ga.CONTACT_NAME}],
            "/api/v1/provisioning/policies": {"receiver": "default"},
            f"/api/v1/provisioning/alert-rules/{ga.RULE_UID}": {"uid": ga.RULE_UID},
            f"/api/v1/provisioning/folder/ftwbcl/rule-groups/{ga.RULE_GROUP}": {"interval": 300},
        })
        ga.apply(g, ga.build_rule("ds", "b", 3), ga.build_contact_point("t", "c"), dry_run=False)
        writes = {(m, p): b for m, p, b in g.calls if m != "GET"}
        self.assertIn(("PUT", f"/api/v1/provisioning/alert-rules/{ga.RULE_UID}"), writes)
        self.assertIn(("PUT", f"/api/v1/provisioning/contact-points/{ga.CONTACT_UID}"), writes)
        self.assertNotIn(("POST", "/api/folders"), writes)
        self.assertEqual(writes[("PUT", f"/api/v1/provisioning/alert-rules/{ga.RULE_UID}")]["folderUID"], "ftwbcl")
        group = writes[("PUT", f"/api/v1/provisioning/folder/ftwbcl/rule-groups/{ga.RULE_GROUP}")]
        self.assertEqual(group["interval"], 60)


if __name__ == "__main__":
    unittest.main()
