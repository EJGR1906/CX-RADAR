import os
import ssl
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_telegram as tg  # noqa: E402


class TestDescribeError(unittest.TestCase):
    def test_certificate_error_mentions_godaddy_root(self):
        e = urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED self signed certificate in certificate chain"))
        self.assertIn("Go Daddy Root Certificate Authority - G2", tg.describe_error(e))

    def test_bad_token(self):
        e = urllib.error.HTTPError("https://api.telegram.org", 401, "Unauthorized", {}, None)
        self.assertIn("TELEGRAM_BOT_TOKEN", tg.describe_error(e))

    def test_bad_chat(self):
        e = urllib.error.HTTPError("https://api.telegram.org", 400, "Bad Request", {}, None)
        self.assertIn("TELEGRAM_CHAT_ID", tg.describe_error(e))

    def test_missing_chat_id_sets_last_error(self):
        self.assertFalse(tg.send_message("x", {"token": "t", "chat_id": ""}))
        self.assertIn("TELEGRAM_CHAT_ID", tg.LAST_ERROR)


if __name__ == "__main__":
    unittest.main()
