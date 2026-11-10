"""Resource caps and pinned picture transports use fake sockets and disposable files only."""
import base64
import http.client
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
import zlib

from decklab.lib import accessory_fetch as af, scan
from decklab.lib.api import collection_scan as cs
from decklab.lib.api.common import ApiError


PUBLIC = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
PRIVATE = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))


class PinnedTransportTests(unittest.TestCase):
    def test_changed_resolver_is_never_used_after_the_public_address_check(self):
        sock = mock.Mock()
        watch = mock.Mock()
        watch.add.side_effect = lambda value: value
        watch.socket_timeout.return_value = 2
        with mock.patch.object(socket, "getaddrinfo", side_effect=[[PUBLIC], [PRIVATE]]) as resolve, \
                mock.patch.object(socket, "create_connection", side_effect=AssertionError("Second hostname lookup")), \
                mock.patch.object(socket, "socket", return_value=sock):
            connection = af._watched(http.client.HTTPConnection, watch)("shop.example", 443)
            connection.connect()
        self.assertEqual(resolve.call_count, 1)
        sock.connect.assert_called_once_with(PUBLIC[4])
        self.assertEqual(connection.host, "shop.example")

    def test_https_keeps_original_tls_hostname_and_tracks_the_wrapped_socket(self):
        raw, wrapped = mock.Mock(), mock.Mock()
        watch = mock.Mock()
        watch.add.side_effect = lambda value: value
        watch.socket_timeout.return_value = 2
        context = ssl.create_default_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        with mock.patch.object(socket, "getaddrinfo", return_value=[PUBLIC]), \
                mock.patch.object(socket, "socket", return_value=raw), \
                mock.patch.object(context, "wrap_socket", return_value=wrapped) as wrap:
            connection = af._watched(http.client.HTTPSConnection, watch)("shop.example", context=context)
            connection.connect()
        raw.connect.assert_called_once_with(PUBLIC[4])
        wrap.assert_called_once_with(raw, server_hostname="shop.example")
        self.assertEqual(watch.add.call_args_list, [mock.call(raw), mock.call(wrapped)])

    def test_a_mixed_public_private_answer_never_opens_a_socket(self):
        with mock.patch.object(socket, "getaddrinfo", return_value=[PUBLIC, PRIVATE]), \
                mock.patch.object(socket, "socket") as opened, self.assertRaises(ApiError) as refused:
            af._connect_checked(("shop.example", 443), 2)
        opened.assert_not_called()
        self.assertEqual((refused.exception.status, refused.exception.message), (400, af.HOME_NETWORK))


class PictureResourceTests(unittest.TestCase):
    def test_fetch_slots_refuse_overload_and_release_after_success_or_failure(self):
        started, finish = threading.Event(), threading.Event()
        result = []
        def work(url):
            started.set()
            self.assertTrue(finish.wait(2))
            return {"url": url}
        with mock.patch.object(af, "_fetch_slots", threading.BoundedSemaphore(1)), \
                mock.patch.object(af, "_fetch", side_effect=work):
            thread = threading.Thread(target=lambda: result.append(af.fetch("first")))
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                with self.assertRaises(ApiError) as busy:
                    af.fetch("second")
                self.assertEqual(busy.exception.status, 429)
            finally:
                finish.set()
                thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result, [{"url": "first"}])
            with mock.patch.object(af, "_fetch", side_effect=ApiError(400, "Synthetic refusal")), self.assertRaises(ApiError):
                af.fetch("refused")
            with mock.patch.object(af, "_fetch", return_value={"ok": True}):
                self.assertEqual(af.fetch("third"), {"ok": True})

    def test_staging_prunes_oldest_by_count_and_bytes_and_keeps_unrelated_files(self):
        for count, size in ((2, 100), (64, 12)):
            with self.subTest(count=count, size=size), tempfile.TemporaryDirectory() as folder, \
                    mock.patch.object(af, "STAGED", Path(folder)), mock.patch.object(af, "STAGE_MAX_COUNT", count), \
                    mock.patch.object(af, "STAGE_MAX_BYTES", size), mock.patch.object(af.time, "time", return_value=1000):
                unrelated = Path(folder) / "notes.txt"
                unrelated.write_text("Never a staged picture")
                first = af.stage(b"1" * 6, "png")
                os.utime(Path(folder) / f"{first}.png", (900, 900))
                second = af.stage(b"2" * 6, "png")
                os.utime(Path(folder) / f"{second}.png", (901, 901))
                latest = af.stage(b"3" * 6, "png")
                self.assertIsNone(af.staged_file(first))
                self.assertIsNotNone(af.staged_file(second))
                self.assertIsNotNone(af.staged_file(latest))
                self.assertEqual(unrelated.read_text(), "Never a staged picture")


def photo(width, height=16):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"\0" * ((width * 3 + 1) * height)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class ScanResourceTests(unittest.TestCase):
    def test_4000_pixel_cap_is_checked_before_any_ocr_or_temporary_file(self):
        self.assertEqual(cs.MAX_SIDE, 4000)
        with mock.patch.object(cs, "_read_photo", side_effect=AssertionError("OCR started")):
            accepted = photo(4000)
            self.assertEqual(cs._photo(base64.b64encode(accepted).decode())[0], accepted)
            with self.assertRaises(ApiError) as refused:
                cs._photo(base64.b64encode(photo(4001)).decode())
        self.assertEqual(refused.exception.status, 400)
        self.assertIn("4,000", refused.exception.message)

    def test_linux_tesseract_has_an_address_space_limit_without_preexec_in_server_threads(self):
        completed = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
        with mock.patch.object(scan.sys, "platform", "linux"), \
                mock.patch.object(scan.shutil, "which", return_value="/usr/bin/prlimit"), \
                mock.patch.object(scan.subprocess, "run", return_value=completed) as run:
            self.assertEqual(scan._run(["/usr/bin/tesseract", "photo.png", "stdout"], memory_limit=scan.TESSERACT_MEMORY), "")
        self.assertEqual(run.call_args.args[0][:3], ["/usr/bin/prlimit", "--as=536870912", "--"])
        self.assertNotIn("preexec_fn", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["timeout"], scan.OCR_TIMEOUT)
        with mock.patch.object(scan.sys, "platform", "linux"), mock.patch.object(scan.shutil, "which", return_value=None), \
                mock.patch.object(scan.subprocess, "run") as unbounded, self.assertRaises(scan.OcrUnavailable):
            scan._run(["/usr/bin/tesseract", "photo.png", "stdout"], memory_limit=scan.TESSERACT_MEMORY)
        unbounded.assert_not_called()
