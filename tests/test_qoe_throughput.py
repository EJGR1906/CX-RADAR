import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts")))

import qoe_throughput as qt  # noqa: E402

PAYLOAD = b"x" * (2 * 1024 * 1024)


class _Handler(BaseHTTPRequestHandler):
    uploaded = 0

    def log_message(self, *args):  # silenciar el servidor de prueba
        pass

    def do_GET(self):
        body = PAYLOAD
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes=0-"):
            end = int(rng.split("-")[1])
            body = PAYLOAD[: end + 1]
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        remaining = n
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            _Handler.uploaded += len(chunk)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class TestThroughputEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.port}/file"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_download_repeats_requests_until_deadline(self):
        r = qt.measure_download([self.url], connections=2, duration_s=1.2, warmup_s=0.3)
        self.assertGreater(r["Bytes"], len(PAYLOAD))  # archivo pequeño: debe pedirse más de una vez
        self.assertGreater(r["Requests"], 1)
        self.assertGreater(r["Mbps"], 0)
        self.assertEqual(r["Errors"], [])

    def test_download_with_range(self):
        r = qt.measure_download([self.url], connections=1, duration_s=0.6, warmup_s=0.1, request_bytes=1024)
        self.assertGreater(r["Requests"], 1)
        self.assertEqual(r["Bytes"] % 1024, 0)

    def test_upload_counts_sent_bytes(self):
        _Handler.uploaded = 0
        r = qt.measure_upload([self.url], connections=2, duration_s=1.0, warmup_s=0.2, payload_bytes=256 * 1024)
        self.assertGreater(r["Requests"], 0)
        self.assertGreater(r["Mbps"], 0)
        self.assertGreater(_Handler.uploaded, 0)

    def test_download_unreachable_reports_errors(self):
        r = qt.measure_download(["http://127.0.0.1:9/"], connections=1, duration_s=0.5, warmup_s=0.1, timeout_s=0.3)
        self.assertEqual(r["Bytes"], 0)
        self.assertTrue(r["Errors"])

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(ValueError):
            qt.measure_download(["file:///etc/passwd"], duration_s=0.1)

    def test_tcp_latency_local(self):
        r = qt.measure_tcp_latency("127.0.0.1", self.port, count=3, interval_s=0)
        self.assertEqual(r["Samples"], 3)
        self.assertEqual(r["LossPercentage"], 0.0)


class _KeepAliveHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    connections = set()

    def log_message(self, *args):
        pass

    def do_GET(self):
        _KeepAliveHandler.connections.add(self.client_address)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/small")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = b"y" * 100_000
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class TestKeepAlive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _KeepAliveHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _KeepAliveHandler.connections = set()

    def test_small_file_reuses_connection(self):
        r = qt.measure_download([self.base + "/small"], connections=2, duration_s=0.8, warmup_s=0.1)
        self.assertGreater(r["Requests"], 10)
        self.assertLessEqual(len(_KeepAliveHandler.connections), 2)  # una por conexión, no una por pedido

    def test_follows_redirect(self):
        r = qt.measure_download([self.base + "/redirect"], connections=1, duration_s=0.5, warmup_s=0.1)
        self.assertGreater(r["Bytes"], 0)
        self.assertEqual(r["Errors"], [])


class TestHelpers(unittest.TestCase):
    def test_steady_mbps_discards_warmup(self):
        # 0-2 s: 1 MB (arranque lento); 2-4 s: 10 MB (estable)
        samples = [(0.0, 0), (2.0, 1_000_000), (4.0, 11_000_000)]
        self.assertEqual(qt._steady_mbps(samples, 2.0), 40.0)

    def test_steady_mbps_short_transfer_uses_full_window(self):
        samples = [(0.0, 0), (0.4, 5_000_000)]
        self.assertEqual(qt._steady_mbps(samples, 2.0), 100.0)

    def test_fast_range_url(self):
        u = "https://ipv4-c1.oca.nflxvideo.net/speedtest?c=ve&n=21826&v=1"
        self.assertEqual(qt.fast_range_url(u, 100),
                         "https://ipv4-c1.oca.nflxvideo.net/speedtest/range/0-100?c=ve&n=21826&v=1")

    def test_ookla_urls(self):
        u = qt.ookla_urls("speedtest.bqto.inter.com.ve", 8080, "http", 1000)
        self.assertEqual(u["download"], "http://speedtest.bqto.inter.com.ve:8080/download?size=1000")
        self.assertEqual(u["upload"], "http://speedtest.bqto.inter.com.ve:8080/upload")


if __name__ == "__main__":
    unittest.main()
