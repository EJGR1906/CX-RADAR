"""Actualizador: todo o nada, verificado contra el manifiesto."""

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))
import update_qoe_probe as up  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Remote:
    """Repositorio remoto simulado: {nombre: contenido}."""

    def __init__(self, files, manifest=None, fail=()):
        self.files = dict(files)
        self.manifest = manifest if manifest is not None else {"files": {n: sha(c) for n, c in files.items()}}
        self.fail = set(fail)
        self.urls = []

    def download(self, url, dest, verify_ssl):
        self.urls.append(url)
        name = url.rsplit("/", 1)[1]
        if name in self.fail:
            return False
        if name == up.MANIFEST_NAME:
            text = self.manifest if isinstance(self.manifest, str) else json.dumps(self.manifest)
        elif name in self.files:
            text = self.files[name]
        else:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        return True


class TestPerformUpdates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.local = {"qoe_config.py": "A = 1\n", "qoe_probe.py": "import qoe_config\nB = 1\n"}
        for name, text in self.local.items():
            (self.dir / name).write_text(text, encoding="utf-8")

    def update(self, remote, **kw):
        with patch.object(up, "download_file", remote.download), patch("sys.stdout", new=MagicMock()):
            return up.perform_updates(True, self.dir, self.dir / "cfg.json", **kw)

    def read(self, name):
        return (self.dir / name).read_text(encoding="utf-8")

    def assert_unchanged(self):
        for name, text in self.local.items():
            self.assertEqual(self.read(name), text)
        self.assertFalse((self.dir / up.STAGING_DIR).exists())

    def test_updates_changed_files_and_keeps_backup(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": self.local["qoe_probe.py"], "qoe_nuevo.py": "C = 3\n"})
        self.assertEqual(self.update(remote), 2)
        self.assertEqual(self.read("qoe_config.py"), "A = 2\n")
        self.assertEqual(self.read("qoe_nuevo.py"), "C = 3\n")  # un módulo nuevo llega por el manifiesto
        self.assertEqual((self.dir / up.BACKUP_DIR / "qoe_config.py").read_text(encoding="utf-8"), "A = 1\n")
        self.assertFalse(any(u.endswith("/qoe_probe.py") for u in remote.urls))  # lo que no cambió no se descarga

    def test_up_to_date_changes_nothing(self):
        self.assertEqual(self.update(Remote(self.local)), 0)
        self.assert_unchanged()

    def test_hash_mismatch_aborts_everything(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": "B = 2\n"})
        remote.files["qoe_probe.py"] = "B = 666\n"  # contenido distinto al del manifiesto
        self.assertEqual(self.update(remote), 0)
        self.assert_unchanged()

    def test_failed_download_of_one_file_aborts_everything(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": "B = 2\n"}, fail=["qoe_probe.py"])
        self.assertEqual(self.update(remote), 0)
        self.assert_unchanged()

    def test_syntax_error_aborts_everything(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": "esto no es : : python\n"})
        self.assertEqual(self.update(remote), 0)
        self.assert_unchanged()

    def test_set_that_cannot_be_imported_aborts(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": "import modulo_que_no_existe\n"})
        self.assertEqual(self.update(remote), 0)
        self.assert_unchanged()

    def test_missing_or_invalid_manifest_aborts(self):
        for manifest in ("{no json", {"files": {}}, {"files": {"../evil.py": "0" * 64}}, {"files": {"a.py": "corto"}},
                         {"files": {"a.sh": "0" * 64}}):
            self.assertEqual(self.update(Remote({"qoe_config.py": "A = 2\n"}, manifest=manifest)), 0)
            self.assert_unchanged()
        self.assertEqual(self.update(Remote({}, fail=[up.MANIFEST_NAME])), 0)

    def test_replace_failure_rolls_back(self):
        remote = Remote({"qoe_config.py": "A = 2\n", "qoe_probe.py": "import qoe_config\nB = 2\n"})
        real = os.replace
        calls = []

        def flaky(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise OSError("disco lleno")
            return real(src, dst)

        with patch.object(up.os, "replace", flaky):
            self.assertEqual(self.update(remote), 0)
        self.assert_unchanged()

    def test_ref_selects_the_download_location(self):
        remote = Remote(self.local)
        self.update(remote, ref="v1.2.3")
        self.assertTrue(all("/v1.2.3/scripts/" in u for u in remote.urls))


class TestManifest(unittest.TestCase):
    def test_committed_manifest_matches_the_scripts(self):
        """Si falla: correr `python scripts/update_qoe_probe.py --write-manifest` y versionar el resultado."""
        committed = up.load_manifest(SCRIPTS / up.MANIFEST_NAME)
        self.assertEqual(committed, up.build_manifest(SCRIPTS)["files"])

    def test_every_distributed_file_exists(self):
        for name in up.FILES_TO_UPDATE:
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_every_imported_module_is_distributed(self):
        """Un módulo local que un script importa y no se distribuye rompería las sondas al actualizar."""
        import re
        local = {p.stem for p in SCRIPTS.glob("*.py")}
        for name in up.FILES_TO_UPDATE:
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            for mod in re.findall(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M):
                if mod in local:
                    self.assertIn(f"{mod}.py", up.FILES_TO_UPDATE, f"{name} importa {mod}")

    def test_hash_ignores_windows_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.py", Path(d) / "b.py"
            a.write_bytes(b"x = 1\ny = 2\n")
            b.write_bytes(b"x = 1\r\ny = 2\r\n")
            self.assertEqual(up.compute_sha256(a), up.compute_sha256(b))

    def test_downloader_never_disables_tls(self):
        source = (SCRIPTS / "update_qoe_probe.py").read_text(encoding="utf-8")
        self.assertNotIn("CERT_NONE", source)
        self.assertNotIn('"-k"', source)


if __name__ == "__main__":
    unittest.main()
