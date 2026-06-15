import unittest
from qoe_probe import get_target_type

class TestGetTargetType(unittest.TestCase):
    def test_get_target_type_explicit(self):
        self.assertEqual(get_target_type({"type": "SpeedTest"}), "speedtest")
        self.assertEqual(get_target_type({"type": "HTTP"}), "http")
        self.assertEqual(get_target_type({"type": "custom"}), "custom")

    def test_get_target_type_default(self):
        self.assertEqual(get_target_type({}), "http")
        self.assertEqual(get_target_type({"other": "value"}), "http")

    def test_get_target_type_empty_or_none(self):
        self.assertEqual(get_target_type({"type": ""}), "http")
        self.assertEqual(get_target_type({"type": "   "}), "http")
        self.assertEqual(get_target_type({"type": None}), "http")

if __name__ == "__main__":
    unittest.main()
