import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_qoe_probe

class TestUpdateQoeProbe(unittest.TestCase):
    @patch('update_qoe_probe.download_file', return_value=True)
    @patch.object(Path, 'read_text', return_value="invalid syntax : : :")
    @patch('update_qoe_probe.FILES_TO_UPDATE', ['qoe_probe.py'])
    def test_perform_updates_compile_error(self, mock_read_text, mock_download_file):
        """
        Test that when downloaded python code has invalid syntax (mocked read_text),
        the compile verification fails, the temp file is cleaned up,
        and the update is skipped.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            config_path = temp_dir_path / "probe-catalog.json"
            tmp_path = temp_dir_path / "qoe_probe.py.tmp"

            # Create the file so unlink has something to delete
            tmp_path.touch()

            with patch('sys.stdout', new=MagicMock()):
                updated_count = update_qoe_probe.perform_updates(True, temp_dir_path, config_path)

            # Should be 0 since compilation fails
            self.assertEqual(updated_count, 0)

            # Verify tmp file was unlinked
            self.assertFalse(tmp_path.exists())

            # Verify target file wasn't created/overwritten
            target_path = temp_dir_path / "qoe_probe.py"
            self.assertFalse(target_path.exists())

if __name__ == '__main__':
    unittest.main()
