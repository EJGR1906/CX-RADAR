import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import qoe_probe

class TestQoeProbe(unittest.TestCase):
    def test_get_mbps_from_bytes_duration(self):
        # Normal cases
        # 125,000 bytes = 1,000,000 bits. Over 1000 ms (1s), that's 1,000,000 bits/s = 1 Mbps.
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(125000, 1000), 1.0)

        # 1,250,000 bytes = 10,000,000 bits. Over 500 ms (0.5s), that's 20,000,000 bits/s = 20 Mbps.
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(1250000, 500), 20.0)

        # Rounding check
        # 100 bytes = 800 bits. Over 3 ms, that's 266666.66 bits/s = 0.2666 Mbps -> 0.27
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(100, 3), 0.27)

        # Edge cases: zero and negative inputs should return 0.0
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(0, 1000), 0.0)
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(1000, 0), 0.0)
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(-125000, 1000), 0.0)
        self.assertEqual(qoe_probe.get_mbps_from_bytes_duration(125000, -1000), 0.0)

if __name__ == '__main__':
    unittest.main()
