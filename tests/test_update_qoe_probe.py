import unittest
import subprocess
from unittest.mock import patch
import sys
import os

# Add scripts directory to path to import update_qoe_probe
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from update_qoe_probe import run_cmd

class TestRunCmd(unittest.TestCase):
    def test_run_cmd_success(self):
        # We test echo
        ret, stdout, stderr = run_cmd(['echo', 'hello'])
        self.assertEqual(ret, 0)
        self.assertEqual(stdout, 'hello')
        self.assertEqual(stderr, '')

    @patch('subprocess.run')
    def test_run_cmd_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("No such file or directory")
        ret, stdout, stderr = run_cmd(['nonexistent_command'])
        self.assertEqual(ret, -1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "No such file or directory")

    @patch('subprocess.run')
    def test_run_cmd_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='cmd', timeout=10)
        ret, stdout, stderr = run_cmd(['cmd'])
        self.assertEqual(ret, -1)
        self.assertEqual(stdout, "")
        self.assertTrue("Command 'cmd' timed out after 10 seconds" in stderr)

if __name__ == '__main__':
    unittest.main()
