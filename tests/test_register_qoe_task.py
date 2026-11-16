import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_heartbeat as hb  # noqa: E402
import register_qoe_task as reg  # noqa: E402


class TestHeartbeatTaskLimits(unittest.TestCase):
    def test_system_limit_is_above_the_heartbeat_watchdog(self):
        # El watchdog tiene que actuar primero: deja el motivo en el log y libera el bloqueo.
        self.assertGreater(reg.execution_limit_minutes(Path("qoe_heartbeat.py")) * 60, hb.HARD_DEADLINE_SECONDS + 30)

    def test_pythonw_is_used_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "python.exe"
            exe.write_text("")
            self.assertEqual(reg.windows_console_free_python(str(exe)), str(exe))
            (Path(tmp) / "pythonw.exe").write_text("")
            self.assertEqual(reg.windows_console_free_python(str(exe)), str(Path(tmp) / "pythonw.exe"))
            self.assertEqual(reg.windows_console_free_python("/usr/bin/python3"), "/usr/bin/python3")


if __name__ == "__main__":
    unittest.main()
