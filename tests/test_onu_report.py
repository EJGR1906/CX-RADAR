import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import onu_report as r  # noqa: E402


def onu(n, online=True, rx=-24.0, pon=1, olt="OLT-A"):
    return {"olt": olt, "slot": 1, "pon": pon, "onu": n, "sn": f"SN{pon:02d}{n:03d}",
            "rx_olt": rx if online else None, "rx_onu": None, "online": online,
            "out_of_range": False, "city": "BARQUISIMETO"}


class TestAnalyze(unittest.TestCase):
    def test_first_report_only_flags_mostly_offline(self):
        onus = [onu(i, online=i < 4) for i in range(10)]
        res = r.analyze(onus, None, {})
        self.assertFalse(res["has_previous"])
        self.assertEqual(len(res["flagged"]), 1)
        self.assertIn("6 de 10 ONUs apagadas", res["flagged"][0]["reasons"][0])

    def test_new_offline_detected_against_previous(self):
        yesterday = [onu(i) for i in range(20)]
        today = [onu(i, online=i >= 8) for i in range(20)]
        res = r.analyze(today, r.build_snapshot(yesterday), {})
        p = res["flagged"][0]
        self.assertEqual(p["new_offline"], 8)
        self.assertIn("8 de 20 ONUs se apagaron", p["reasons"][0])

    def test_splitter_cut_on_large_pon(self):
        yesterday = [onu(i) for i in range(64)]
        today = [onu(i, online=i >= 8) for i in range(64)]  # 8 de 64 = 12,5 %
        res = r.analyze(today, r.build_snapshot(yesterday), {})
        self.assertEqual(len(res["flagged"]), 1)

    def test_few_new_offline_on_large_pon_ignored(self):
        yesterday = [onu(i) for i in range(64)]
        today = [onu(i, online=i >= 3) for i in range(64)]
        self.assertEqual(r.analyze(today, r.build_snapshot(yesterday), {})["flagged"], [])

    def test_already_offline_is_not_new(self):
        yesterday = [onu(i, online=i >= 2) for i in range(20)]
        today = [onu(i, online=i >= 2) for i in range(20)]
        res = r.analyze(today, r.build_snapshot(yesterday), {})
        self.assertEqual(res["flagged"], [])

    def test_rx_drop(self):
        yesterday = [onu(i, rx=-22.0) for i in range(10)]
        today = [onu(i, rx=-25.0) for i in range(10)]
        res = r.analyze(today, r.build_snapshot(yesterday), {})
        self.assertEqual(res["flagged"][0]["rx_delta"], -3.0)

    def test_small_rx_change_ignored(self):
        yesterday = [onu(i, rx=-22.0) for i in range(10)]
        today = [onu(i, rx=-23.0) for i in range(10)]
        self.assertEqual(r.analyze(today, r.build_snapshot(yesterday), {})["flagged"], [])

    def test_olt_summary_and_message(self):
        onus = [onu(i, pon=p) for p in (1, 2) for i in range(10)]
        res = r.analyze(onus, None, {})
        self.assertEqual(res["olts"][0]["total"], 20)
        self.assertEqual(res["olts"][0]["pons"], 2)
        msg = r.build_telegram_summary(res, "2026-11-10")
        self.assertIn("BARQUISIMETO: 1 OLTs, 20 ONUs", msg)
        self.assertIn("Sin PONs para revisar", msg)

    def test_city_from_server(self):
        self.assertEqual(r.city_from_server("G5 BARQUISIMETO"), "BARQUISIMETO")
        self.assertEqual(r.city_from_server("G12 Puerto Ordaz"), "PUERTO ORDAZ")
        self.assertEqual(r.city_from_server(""), "")


if __name__ == "__main__":
    unittest.main()
