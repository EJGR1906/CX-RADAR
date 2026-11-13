"""Instalador: los ajustes del servidor van al catálogo local y las credenciales a .env."""

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import install  # noqa: E402
import qoe_config  # noqa: E402
import qoe_telegram  # noqa: E402

BASE = {"probe": {"probeId": "repo", "site": "home-office", "isp": "Inter"},
        "influx": {"baseUrl": "https://x", "org": "cx-radar", "bucket": "qoe_metrics"}}


class TestLocalOverride(unittest.TestCase):
    def values(self, **probe):
        return {"probe": {"probeId": "HUB", "site": "home-office", "isp": "Inter", **probe},
                "influx": {"baseUrl": "https://x", "org": "cx-radar", "bucket": "qoe_metrics"}}

    def test_only_differences_are_written(self):
        self.assertEqual(install.build_local_override(BASE, {}, self.values()), {"probe": {"probeId": "HUB"}})

    def test_existing_local_keys_are_kept(self):
        local = {"probe": {"router_brand": "VSOL", "probeId": "VIEJO"}, "heartbeat": {"failThreshold": 3}}
        out = install.build_local_override(BASE, local, self.values(planDownMbps=600.0, planUpMbps=None))
        self.assertEqual(out, {"probe": {"router_brand": "VSOL", "probeId": "HUB", "planDownMbps": 600.0},
                               "heartbeat": {"failThreshold": 3}})
        self.assertEqual(local["probe"]["probeId"], "VIEJO")  # no modifica la entrada

    def test_value_back_to_default_is_removed(self):
        out = install.build_local_override(BASE, {"probe": {"probeId": "HUB"}},
                                           {"probe": {"probeId": "repo"}, "influx": {}})
        self.assertEqual(out, {})

    def test_merged_result_is_what_the_probe_reads(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "probe-catalog.json"
            install.save_catalog(cfg, BASE)
            install.save_catalog(qoe_config.local_override_path(cfg),
                                 install.build_local_override(BASE, {}, self.values(planDownMbps=300.0)))
            merged = qoe_config.load_config(cfg)
            self.assertEqual((merged["probe"]["probeId"], merged["probe"]["planDownMbps"], merged["probe"]["isp"]),
                             ("HUB", 300.0, "Inter"))


class TestEnvFile(unittest.TestCase):
    def test_telegram_credentials_are_added_without_touching_the_rest(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("INFLUXDB_TOKEN=abc\nTELEGRAM_CHAT_ID=1\n", encoding="utf-8")
            install.upsert_env(env, {"TELEGRAM_BOT_TOKEN": "123:XYZ", "TELEGRAM_CHAT_ID": ""})
            self.assertEqual(env.read_text(encoding="utf-8").splitlines(),
                             ["INFLUXDB_TOKEN=abc", "TELEGRAM_CHAT_ID=1", "TELEGRAM_BOT_TOKEN=123:XYZ"])
            self.assertEqual(qoe_telegram.get_credentials(env)["token"] or os.environ.get("TELEGRAM_BOT_TOKEN"), "123:XYZ")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
