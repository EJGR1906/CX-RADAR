import unittest
from unittest.mock import patch
import sys
import datetime

# Add scripts directory to path to import qoe_probe
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))

from qoe_probe import log_message

class TestLogMessage(unittest.TestCase):
    @patch('sys.stdout.write')
    @patch('sys.stdout.flush')
    @patch('builtins.print')
    def test_log_message_unicode_encode_error_fallback(self, mock_print, mock_flush, mock_write):
        # Configure mock_print to raise UnicodeEncodeError
        mock_print.side_effect = UnicodeEncodeError('ascii', '', 0, 1, 'mock reason')

        # Call the function
        test_message = "Test message with unicode 🚀"
        log_message(test_message)

        # Verify print was called
        self.assertTrue(mock_print.called)

        # Verify fallback logic was executed
        self.assertTrue(mock_write.called)
        self.assertTrue(mock_flush.called)

        # Check that the fallback text contains our message and level
        write_call_args = mock_write.call_args[0][0]
        self.assertIn("INFO", write_call_args)
        # We can't strictly assert the exact encoded/decoded string here easily because
        # it depends on sys.stdout.encoding, but we can check if write was called
        # with some non-empty string.
        self.assertIsInstance(write_call_args, str)
        self.assertTrue(len(write_call_args) > 0)
        self.assertTrue(write_call_args.endswith('\n'))

if __name__ == '__main__':
    unittest.main()
