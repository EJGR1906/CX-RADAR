import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_config  # noqa: E402

BASE = {
    "probe": {"probeId": "repo", "site": "home-office", "isp": "Inter"},
    "probeRun": {"verifyTls": True, "portableTools": {"nodeExe": "bin/node"}},
    "targets": [{"service": "A"}, {"service": "B"}],
}


class TestLocalOverride(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "probe-catalog.json"
        self.path.write_text(json.dumps(BASE), encoding="utf-8")

    def test_without_local_file_returns_repo_catalog(self):
        self.assertEqual(qoe_config.load_config(self.path), BASE)

    def test_local_overrides_only_given_keys(self):
        (self.dir / "probe-catalog.local.json").write_text(
            json.dumps({"probe": {"probeId": "HUB_BTO", "connection_type": "ETHERNET"}}), encoding="utf-8")
        c = qoe_config.load_config(self.path)
        self.assertEqual(c["probe"], {"probeId": "HUB_BTO", "site": "home-office", "isp": "Inter",
                                      "connection_type": "ETHERNET"})
        self.assertEqual(c["targets"], BASE["targets"])

    def test_nested_objects_merge_and_lists_replace(self):
        (self.dir / "probe-catalog.local.json").write_text(
            json.dumps({"probeRun": {"portableTools": {"ytDlpExe": "bin/yt"}}, "targets": [{"service": "C"}]}),
            encoding="utf-8")
        c = qoe_config.load_config(self.path)
        self.assertEqual(c["probeRun"]["portableTools"], {"nodeExe": "bin/node", "ytDlpExe": "bin/yt"})
        self.assertTrue(c["probeRun"]["verifyTls"])
        self.assertEqual(c["targets"], [{"service": "C"}])

    def test_invalid_local_file_raises_clear_error(self):
        (self.dir / "probe-catalog.local.json").write_text("{<<<<<<< HEAD", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            qoe_config.load_config(self.path)
        self.assertIn("probe-catalog.local.json", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
