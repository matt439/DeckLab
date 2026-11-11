"""Loopback-only stalled/overloaded wake-gate sockets; no actual Wake-on-LAN packets."""
import http.client
from pathlib import Path
import socket
import threading
import time
import unittest

from decklab.tests.test_wakegate import make_gate, wg


class WakeGateLimitTests(unittest.TestCase):
    def server(self, timeout=.1, maximum=2):
        gate, sent, pc = make_gate()
        server = wg.make_server(gate, "127.0.0.1", 0, connection_timeout=timeout, max_connections=maximum)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1], sent, pc

    def socket(self, port):
        connection = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.addCleanup(connection.close)
        return connection

    def closed(self, connection):
        try:
            return connection.recv(1) == b""
        except ConnectionResetError:
            return True

    def status(self, port):
        deadline = time.monotonic() + 2
        while True:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            try:
                connection.request("GET", "/__status")
                response = connection.getresponse()
                response.read()
                return response.status
            except (OSError, http.client.HTTPException):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.01)
            finally:
                connection.close()

    def test_silent_partial_header_and_stalled_body_connections_expire_and_release_the_slot(self):
        port, sent, pc = self.server(maximum=1)
        for data in (b"", b"GET /__status HTTP/1.1\r\nHost:",
                     b"POST /__wake HTTP/1.1\r\nHost: local\r\nContent-Length: 3\r\n\r\na"):
            with self.subTest(kind=data[:10]):
                connection = self.socket(port)
                if data:
                    connection.sendall(data)
                self.assertTrue(self.closed(connection))
                self.assertEqual(self.status(port), 200)
        self.assertEqual(sent, [])

    def test_connection_cap_closes_excess_connections_and_recovers_after_a_slot_is_freed(self):
        port, sent, _ = self.server(timeout=5, maximum=2)
        first, second = self.socket(port), self.socket(port)
        excess = self.socket(port)
        self.assertTrue(self.closed(excess))
        first.close()
        self.assertEqual(self.status(port), 200)
        second.close()
        self.assertEqual(sent, [])

    def test_default_limits_and_container_privileges_match_the_hardening_contract(self):
        self.assertEqual((wg.CONNECTION_TIMEOUT, wg.MAX_CONNECTIONS), (10, 32))
        text = (Path(__file__).resolve().parents[1] / "wakegate" / "compose.yaml").read_text(encoding="utf-8")
        gate = text.split("  wakegate:", 1)[1].split("  cloudflared:", 1)[0]
        for setting in ('user: "65534:65534"', 'read_only: true', 'cap_drop: ["ALL"]',
                        'security_opt: ["no-new-privileges:true"]'):
            self.assertIn(setting, gate)
