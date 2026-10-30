"""Tests for decklab.lib.accessory_fetch. No network: socket.getaddrinfo is
patched to a made-up address book and the opener's HTTP and HTTPS handlers are
replaced by ones that answer from a dict, so redirects, error statuses and
Content-Length still go through urllib's real handlers.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_accessory_fetch
"""
import email.message
import io
import os
import socket
import socketserver
import threading
import struct
import tempfile
import time
import unittest
import urllib.request
import urllib.response
from pathlib import Path
from unittest import mock

from decklab.lib import accessory_fetch as af
from decklab.lib.api.common import ApiError


# --- Made-up pictures --------------------------------------------------------

def png(width=200, height=100):
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0\0\0\0" + b"\0" * 32


def jpeg(width=300, height=150, sof=0xC0):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0"
    frame = b"\xff" + bytes([sof]) + struct.pack(">HBHHB", 17, 8, height, width, 3) + b"\0" * 9
    return b"\xff\xd8" + app0 + b"\xff\xff" + frame + b"\xff\xda\0\x08" + b"\0" * 64


def webp_vp8(width=400, height=250):
    frame = b"\0\0\0" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\0" * 16
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(frame)) + b"WEBP" + b"VP8 " + struct.pack("<I", len(frame)) + frame


def webp_vp8l(width=123, height=45):
    bits = (width - 1) | ((height - 1) << 14)
    data = b"\x2f" + struct.pack("<I", bits) + b"\0" * 16
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"WEBP" + b"VP8L" + struct.pack("<I", len(data)) + data


def webp_vp8x(width=5000, height=17):
    data = b"\0\0\0\0" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"WEBP" + b"VP8X" + struct.pack("<I", len(data)) + data


GIF = b"GIF89a" + b"\x10\0\x10\0" + b"\0" * 40
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'
AVIF = b"\0\0\0\x1cftypavif" + b"\0" * 40


# --- A fake internet ---------------------------------------------------------

ADDRESSES = {
    "shop.example": ["93.184.216.34"],
    "cdn.example": ["93.184.216.35", "2606:2800:220:1::1"],
    "router.example": ["192.168.1.1"],
    "loop.example": ["127.0.0.1"],
    "link.example": ["169.254.169.254"],
    "ula.example": ["fd00::1"],
    "mapped.example": ["::ffff:10.0.0.1"],
    "mixed.example": ["93.184.216.36", "10.0.0.5"],
    "zero.example": ["0.0.0.0"],
    "multi.example": ["224.0.0.1"],
}


def fake_getaddrinfo(host, port, *args, **kwargs):
    if host in ADDRESSES:
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
                for a in ADDRESSES[host]]
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in host else socket.AF_INET, host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]
    except OSError:
        raise socket.gaierror("unknown host") from None


class Answer:
    """One canned response: status, headers and a body (bytes or a reader)."""

    def __init__(self, body=b"", status=200, headers=None, reader=None):
        self.body, self.status, self.headers, self.reader = body, status, dict(headers or {}), reader


class FakeWeb:
    """Answers requests from routes {url: Answer}; records each request."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def answer(self, req):
        url = req.full_url
        self.requests.append(req)
        if url not in self.routes:
            raise AssertionError(f"unexpected request {url}")
        answer = self.routes[url]
        headers = email.message.Message()
        for key, value in answer.headers.items():
            headers[key] = value
        reader = answer.reader or io.BytesIO(answer.body)
        response = urllib.response.addinfourl(reader, headers, url, answer.status)
        response.msg = "OK" if answer.status == 200 else "Moved"
        return response

    def opener(self, watch=None):
        web = self

        class Http(urllib.request.HTTPHandler):
            def http_open(self, req):
                return web.answer(req)

        class Https(urllib.request.HTTPSHandler):
            def https_open(self, req):
                return web.answer(req)

        return urllib.request.build_opener(urllib.request.ProxyHandler({}), af.SafeRedirect(), Http(), Https())


class FetchCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.staged = Path(tmp.name) / "staged"
        for patcher in (mock.patch.object(af, "STAGED", self.staged),
                        mock.patch("socket.getaddrinfo", side_effect=fake_getaddrinfo)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def web(self, routes):
        web = FakeWeb(routes)
        patcher = mock.patch.object(af, "_opener", web.opener)
        patcher.start()
        self.addCleanup(patcher.stop)
        return web

    def refused(self, url, status=None, contains=None):
        with self.assertRaises(ApiError) as caught:
            af.fetch(url)
        if status is not None:
            self.assertEqual(caught.exception.status, status)
        if contains is not None:
            self.assertIn(contains, caught.exception.message)
        return caught.exception


# --- Links -------------------------------------------------------------------

class UrlRuleTests(FetchCase):
    def test_refuses_other_schemes(self):
        for url in ("ftp://shop.example/a.png", "file:///C:/Windows/win.ini", "javascript:alert(1)",
                    "data:image/png;base64,AAAA", "shop.example/a.png", "", "   "):
            with self.subTest(url=url):
                self.refused(url, 400)

    def test_refuses_userinfo(self):
        self.refused("https://user:pw@shop.example/p", 400, "user name")
        self.refused("https://user@shop.example/p", 400)

    def test_refuses_ports_other_than_80_and_443(self):
        self.refused("http://shop.example:8642/p", 400, "port")
        self.refused("https://shop.example:8080/p", 400)
        self.refused("https://shop.example:99999/p", 400)

    def test_allows_the_standard_ports(self):
        self.web({"https://shop.example:443/a.png": Answer(png())})
        self.assertEqual(af.fetch("https://shop.example:443/a.png")["ext"], "png")

    def test_refuses_long_links(self):
        self.refused("https://shop.example/" + "a" * 500, 400, "longer than 500")

    def test_refuses_control_characters(self):
        self.refused("https://shop.example/a\r\nX-Evil: 1", 400)

    def test_unknown_host(self):
        self.refused("https://nowhere.invalid/p", 400, "couldn't find that website")


class AddressTests(FetchCase):
    def test_refuses_home_network_addresses(self):
        for host in ("router.example", "loop.example", "link.example", "ula.example", "mapped.example",
                     "mixed.example", "zero.example", "multi.example", "127.0.0.1", "[::1]", "10.1.2.3"):
            with self.subTest(host=host):
                self.refused(f"http://{host}/p", 400, af.HOME_NETWORK)

    def test_public_addresses_pass(self):
        self.assertEqual(af.check_url("https://cdn.example/a.png"), "cdn.example")
        self.assertTrue(af._public("93.184.216.34"))
        self.assertTrue(af._public("2606:2800:220:1::1"))
        for address in ("192.168.0.1", "172.16.0.1", "100.64.0.1", "fe80::1%eth0", "::", "255.255.255.255", "nonsense"):
            with self.subTest(address=address):
                self.assertFalse(af._public(address))

    def test_redirect_to_home_network_is_refused(self):
        web = self.web({"https://shop.example/p": Answer(status=302, headers={"Location": "http://router.example/admin"})})
        self.refused("https://shop.example/p", 400, af.HOME_NETWORK)
        self.assertEqual([r.full_url for r in web.requests], ["https://shop.example/p"])

    def test_redirect_to_a_literal_private_address_is_refused(self):
        self.web({"https://shop.example/p": Answer(status=301, headers={"Location": "http://10.0.0.1/"})})
        self.refused("https://shop.example/p", 400, af.HOME_NETWORK)

    def test_redirect_to_ftp_is_not_followed(self):
        web = self.web({"https://shop.example/p": Answer(status=302, headers={"Location": "ftp://cdn.example/a.png"})})
        with self.assertRaises(ApiError) as caught:
            af.fetch("https://shop.example/p")
        self.assertIn(caught.exception.status, (400, 502))
        self.assertEqual(len(web.requests), 1)

    def test_redirect_to_a_port_is_refused(self):
        self.web({"https://shop.example/p": Answer(status=302, headers={"Location": "http://cdn.example:8642/x"})})
        self.refused("https://shop.example/p", 400, "port")

    def test_follows_public_redirects(self):
        self.web({"https://shop.example/p": Answer(status=302, headers={"Location": "/q"}),
                  "https://shop.example/q": Answer(status=301, headers={"Location": "https://cdn.example/a.png"}),
                  "https://cdn.example/a.png": Answer(png(), headers={"Content-Type": "image/png"})})
        found = af.fetch("https://shop.example/p")
        self.assertEqual(found["final_url"], "https://cdn.example/a.png")
        self.assertEqual(found["image_source"], "https://cdn.example/a.png")

    def test_hop_limit(self):
        routes = {f"https://shop.example/{i}": Answer(status=302, headers={"Location": f"/{i + 1}"}) for i in range(6)}
        routes["https://shop.example/5"] = Answer(png())
        self.web(dict(routes))
        self.assertEqual(af.fetch("https://shop.example/0")["ext"], "png")        # 5 hops are fine
        routes = {f"https://shop.example/{i}": Answer(status=302, headers={"Location": f"/{i + 1}"}) for i in range(7)}
        routes["https://shop.example/6"] = Answer(png())
        web = self.web(routes)
        self.refused("https://shop.example/0", 502, "didn't let Deck Lab")        # the 6th isn't followed
        self.assertNotIn("https://shop.example/6", [r.full_url for r in web.requests])

    def test_no_proxy_and_own_user_agent(self):
        web = self.web({"https://shop.example/a.png": Answer(png())})
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://10.0.0.1:3128"}):
            af.fetch("https://shop.example/a.png")
        self.assertEqual(web.requests[0].host, "shop.example")                  # not sent to the proxy
        self.assertEqual(web.requests[0].get_header("User-agent"), af.USER_AGENT)
        self.assertTrue(af.USER_AGENT.endswith(" product image fetch"))
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://10.0.0.1:3128", "HTTP_PROXY": "http://10.0.0.1:3128"}):
            handlers = af._opener().handlers
        self.assertFalse([h for h in handlers if getattr(h, "proxies", None)])
        self.assertTrue(any(isinstance(h, af.SafeRedirect) for h in handlers))


# --- Sizes and time ----------------------------------------------------------

class Trickle(io.RawIOBase):
    """A body that never ends, a chunk at a time."""

    def readable(self):
        return True

    def readinto(self, buffer):
        buffer[:1] = b"x"
        return 1


class CountingReader(io.BytesIO):
    """A body that remembers how many bytes were read from it."""
    taken = 0

    def read(self, size=-1):
        data = super().read(size)
        self.taken += len(data)
        return data

    def read1(self, size=-1):
        data = super().read1(size)
        self.taken += len(data)
        return data


class LimitTests(FetchCase):
    def test_declared_length_over_the_cap_is_refused_unread(self):
        reader = CountingReader(png())
        self.web({"https://shop.example/a.png": Answer(headers={"Content-Type": "image/png",
                                                                  "Content-Length": str(af.MAX_IMAGE + 1)},
                                                         reader=reader)})
        self.refused("https://shop.example/a.png", 502, "larger than 4 MB")
        self.assertEqual(reader.taken, 0)

    def test_page_cap_is_2_mb(self):
        self.web({"https://shop.example/p": Answer(headers={"Content-Type": "text/html",
                                                            "Content-Length": str(af.MAX_PAGE + 1)})})
        self.refused("https://shop.example/p", 502, "larger than 2 MB")

    def test_undeclared_length_stops_at_cap_plus_one(self):
        body = png() + b"\0" * af.MAX_IMAGE
        reader = CountingReader(body)
        self.web({"https://shop.example/a.png": Answer(headers={"Content-Type": "image/png"}, reader=reader)})
        self.refused("https://shop.example/a.png", 502, "larger than 4 MB")
        self.assertEqual(reader.taken, af.MAX_IMAGE + 1)

    def test_image_exactly_at_cap_is_fine(self):
        body = png()
        body += b"\0" * (af.MAX_IMAGE - len(body))
        self.web({"https://shop.example/a.png": Answer(body, headers={"Content-Type": "image/png"})})
        self.assertEqual(len(af.fetch("https://shop.example/a.png")["bytes"]), af.MAX_IMAGE)

    def test_total_deadline(self):
        clock = iter(range(0, 1000, 3))
        self.web({"https://shop.example/a.png": Answer(reader=io.BufferedReader(Trickle()))})
        with mock.patch.object(af, "_now", lambda: next(clock)):
            self.refused("https://shop.example/a.png", 502, "too long")

    def test_socket_timeout(self):
        web = self.web({})
        with mock.patch.object(web, "answer", side_effect=urllib.error.URLError(TimeoutError("timed out"))):
            self.refused("https://shop.example/a.png", 502)
        with mock.patch.object(web, "answer", side_effect=TimeoutError("timed out")):
            self.refused("https://shop.example/a.png", 502, "too long")

    def test_http_errors_say_the_shop_blocked_it(self):
        self.web({"https://shop.example/p": Answer(b"denied", status=403)})
        error = self.refused("https://shop.example/p", 502)
        self.assertEqual(error.message, af.BLOCKED)


class _TrickleHandler(socketserver.BaseRequestHandler):
    """Sends its prefix, then one byte every 0.1 s until the client goes (or 30 s)."""

    def handle(self):
        server = self.server
        try:
            self.request.sendall(server.prefix)
            end = time.monotonic() + 30
            while time.monotonic() < end and not server.stopping.is_set():
                self.request.sendall(server.drip)
                time.sleep(0.1)
        except OSError:
            pass


class RealSocketDeadlineTests(unittest.TestCase):
    """A local server that trickles: the deadline must hold below read(), in the
    headers and in the body alike (a BufferedReader read waits for a whole chunk)."""

    def serve(self, prefix, drip=b"x"):
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _TrickleHandler)
        server.daemon_threads = True
        server.prefix, server.drip, server.stopping = prefix, drip, threading.Event()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.stopping.set()
            server.shutdown()
            server.server_close()
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_address[1]}/a.png"

    def timed_refusal(self, url):
        started = time.monotonic()
        with self.assertRaises(ApiError) as caught:
            af._download(url, af.IMAGE_ACCEPT, af._now() + 1.0, image_only=True)
        took = time.monotonic() - started
        self.assertEqual(caught.exception.message, af.TOO_SLOW)
        self.assertLess(took, 4.0)

    def test_trickled_body_stops_at_the_deadline(self):
        self.timed_refusal(self.serve(b"HTTP/1.0 200 OK\r\nContent-Type: image/png\r\n\r\n"))

    def test_trickled_headers_stop_at_the_deadline(self):
        self.timed_refusal(self.serve(b"HTTP/1.0 200 OK\r\nX-Slow: ", drip=b"a"))

    def test_past_deadline_never_connects(self):
        opener = mock.Mock()
        with mock.patch.object(af, "_opener", lambda watch=None: opener):
            with self.assertRaises(ApiError) as caught:
                af._download("http://127.0.0.1:1/a.png", af.IMAGE_ACCEPT, af._now() - 1, image_only=True)
        self.assertEqual(caught.exception.message, af.TOO_SLOW)
        opener.open.assert_not_called()


# --- Pictures ----------------------------------------------------------------

class PictureTests(unittest.TestCase):
    def test_sniff(self):
        self.assertEqual(af.sniff(png()), "png")
        self.assertEqual(af.sniff(jpeg()), "jpg")
        self.assertEqual(af.sniff(webp_vp8()), "webp")
        for data in (GIF, SVG, AVIF, b"<!doctype html><html></html>", b"", b"RIFF\0\0\0\0WAVE"):
            with self.subTest(data=data[:12]):
                self.assertIsNone(af.sniff(data))

    def test_dimensions(self):
        cases = [(png(200, 100), "png", (200, 100)),
                 (jpeg(300, 150, 0xC0), "jpg", (300, 150)),
                 (jpeg(640, 480, 0xC2), "jpg", (640, 480)),
                 (webp_vp8(400, 250), "webp", (400, 250)),
                 (webp_vp8l(123, 45), "webp", (123, 45)),
                 (webp_vp8x(5000, 17), "webp", (5000, 17))]
        for data, ext, size in cases:
            with self.subTest(ext=ext, size=size):
                self.assertEqual(af.dimensions(data, ext), size)

    def test_damaged_headers(self):
        self.assertIsNone(af.dimensions(png()[:20], "png"))
        self.assertIsNone(af.dimensions(b"\xff\xd8\xff\xda\0\x08", "jpg"))
        self.assertIsNone(af.dimensions(b"\xff\xd8\x00\x00", "jpg"))
        self.assertIsNone(af.dimensions(b"RIFF\0\0\0\0WEBPVP8Z", "webp"))
        self.assertIsNone(af.dimensions(b"\xff\xd8\xff\xe0\x00", "jpg"))

    def test_check_image_refuses_other_types(self):
        for data, word in ((GIF, "GIF"), (SVG, "SVG"), (AVIF, "AVIF"), (b"<!doctype html><p>", "web page")):
            with self.subTest(word=word):
                with self.assertRaises(ApiError) as caught:
                    af.check_image(data)
                self.assertEqual(caught.exception.status, 502)
                self.assertIn(word, caught.exception.message)

    def test_check_image_sizes(self):
        self.assertEqual(af.check_image(png(16, 6000)), ("png", 16, 6000))
        for size in ((15, 100), (100, 6001), (0, 0)):
            with self.subTest(size=size):
                with self.assertRaises(ApiError):
                    af.check_image(png(*size))


class RefusedTypeFetchTests(FetchCase):
    def test_direct_links_to_refused_types(self):
        for name, body, ctype, word in (("a.gif", GIF, "image/gif", "GIF"),
                                         ("a.svg", SVG, "image/svg+xml", "SVG"),
                                         ("a.avif", AVIF, "image/avif", "AVIF"),
                                         ("a.bin", b"\0\1\2\3", "application/octet-stream", "not a picture")):
            with self.subTest(name=name):
                self.web({f"https://cdn.example/{name}": Answer(body, headers={"Content-Type": ctype})})
                self.refused(f"https://cdn.example/{name}", 502, word)

    def test_magic_bytes_win_over_the_name_and_type(self):
        self.web({"https://cdn.example/a.gif": Answer(jpeg(), headers={"Content-Type": "text/plain"})})
        found = af.fetch("https://cdn.example/a.gif")
        self.assertEqual((found["ext"], found["width"], found["height"]), ("jpg", 300, 150))

    def test_page_whose_picture_is_a_page(self):
        page = b'<html><head><meta property="og:image" content="/pic"></head></html>'
        self.web({"https://shop.example/p": Answer(page, headers={"Content-Type": "text/html"}),
                  "https://shop.example/pic": Answer(b"<!doctype html><html>", headers={"Content-Type": "text/html"})})
        self.refused("https://shop.example/p", 502, "web page")


# --- Product pages -----------------------------------------------------------

PAGE = """<!doctype html><html><head>
<title>Ignored &amp; title</title>
<meta property="og:site_name" content="Card Shop">
<meta property="og:title" content="Dragon Shield Matte Sleeves &ndash; Black (100 ct) | Card Shop">
<meta property="product:brand" content="Dragon Shield">
<meta property="og:image" content="/images/ds-black.png?v=2">
<meta name="twitter:image" content="https://cdn.example/twitter.png">
</head><body><p>Hi</p></body></html>"""


class PageTests(FetchCase):
    def test_og_image_relative_url_and_guesses(self):
        web = self.web({"https://shop.example/p/1": Answer(PAGE.encode(), headers={"Content-Type": "text/html; charset=utf-8"}),
                        "https://shop.example/images/ds-black.png?v=2": Answer(png(500, 500), headers={"Content-Type": "image/png"})})
        found = af.fetch("https://shop.example/p/1")
        self.assertEqual(found["final_url"], "https://shop.example/p/1")
        self.assertEqual(found["image_source"], "https://shop.example/images/ds-black.png?v=2")
        self.assertEqual((found["ext"], found["width"], found["height"]), ("png", 500, 500))
        self.assertEqual(found["guess"], {"name": "Matte Sleeves \u2013 Black (100 ct)", "brand": "Dragon Shield",
                                          "kind": "sleeves", "quantity": 100})
        self.assertEqual(len(web.requests), 2)
        self.assertTrue(web.requests[1].get_header("Accept").startswith("image/"))

    def test_preference_order(self):
        def picture(head):
            return af.parse_page(f"<html><head>{head}</head></html>".encode()).picture()
        self.assertEqual(picture('<meta property="og:image:secure_url" content="a"><meta name="twitter:image" content="b">'), "a")
        self.assertEqual(picture('<meta name="twitter:image" content="b"><link rel="image_src" href="c">'), "b")
        self.assertEqual(picture('<link rel="image_src" href="c"><script type="application/ld+json">{"image":"d"}</script>'), "c")
        self.assertEqual(picture('<script type="application/ld+json">{"image":"d"}</script>'), "d")
        self.assertIsNone(picture("<title>none</title>"))

    def test_json_ld(self):
        page = b"""<html><head><script type="application/ld+json">not json</script>
        <script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},
        {"@type":"Product","name":"Boulder 100+","brand":{"@type":"Brand","name":"Ultimate Guard"},
        "image":[{"@type":"ImageObject","url":"//cdn.example/boulder.webp"}]}]}</script>
        <meta property="og:title" content="Ultimate Guard Boulder 100+ Deck Case Black"></head></html>"""
        self.web({"https://shop.example/b": Answer(page, headers={"Content-Type": "text/html"}),
                  "https://cdn.example/boulder.webp": Answer(webp_vp8x(800, 800))})
        found = af.fetch("https://shop.example/b")
        self.assertEqual(found["image_source"], "https://cdn.example/boulder.webp")
        self.assertEqual(found["ext"], "webp")
        self.assertEqual(found["guess"], {"name": "Boulder 100+ Deck Case Black", "brand": "Ultimate Guard",
                                          "kind": "deck_box", "quantity": None})

    def test_page_without_a_picture(self):
        self.web({"https://shop.example/p": Answer(b"<html><head><title>x</title></head></html>",
                                                   headers={"Content-Type": "text/html"})})
        error = self.refused("https://shop.example/p", 502)
        self.assertEqual(error.message, af.NO_PICTURE)

    def test_page_picture_on_home_network_is_refused(self):
        page = b'<html><head><meta property="og:image" content="http://192.168.1.1/x.png"></head></html>'
        web = self.web({"https://shop.example/p": Answer(page, headers={"Content-Type": "text/html"})})
        self.refused("https://shop.example/p", 400, af.HOME_NETWORK)
        self.assertEqual(len(web.requests), 1)

    def test_page_picture_with_bad_scheme_is_refused(self):
        page = b'<html><head><meta property="og:image" content="file:///etc/passwd"></head></html>'
        self.web({"https://shop.example/p": Answer(page, headers={"Content-Type": "text/html"})})
        self.refused("https://shop.example/p", 400)

    def test_at_most_two_downloads(self):
        page = b'<html><head><meta property="og:image" content="/second"></head></html>'
        web = self.web({"https://shop.example/p": Answer(page, headers={"Content-Type": "text/html"}),
                        "https://shop.example/second": Answer(page, headers={"Content-Type": "text/html"})})
        self.refused("https://shop.example/p", 502)
        self.assertEqual(len(web.requests), 2)

    def test_html_sniffed_without_content_type(self):
        page = b'  <!DOCTYPE html><html><head><meta property="og:image" content="a.png"></head></html>'
        self.web({"https://shop.example/dir/p": Answer(page),
                  "https://shop.example/dir/a.png": Answer(png())})
        self.assertEqual(af.fetch("https://shop.example/dir/p")["image_source"], "https://shop.example/dir/a.png")


class GuessTests(unittest.TestCase):
    def guess(self, head, url=""):
        return af.guess(af.parse_page(f"<html><head>{head}</head></html>".encode()), url)

    def test_site_name_and_brand_removed(self):
        g = self.guess('<meta property="og:site_name" content="Good Games">'
                       '<meta property="og:title" content="Good Games - Dragon Shield Matte Sleeves Jet (100)">'
                       '<meta property="product:brand" content="Dragon Shield">')
        self.assertEqual(g["name"], "Matte Sleeves Jet (100)")
        self.assertEqual(g["brand"], "Dragon Shield")
        self.assertEqual(g["kind"], "sleeves")
        self.assertIsNone(g["quantity"])

    def test_title_tag_fallback_drops_shop_suffix(self):
        g = self.guess("<title>KMC Hyper Matte Sleeves 80-count | Some Shop</title>")
        self.assertEqual(g["name"], "KMC Hyper Matte Sleeves 80-count")
        self.assertEqual(g["quantity"], 80)

    def test_kinds(self):
        for title, kind in (("Ultimate Guard Boulder 100+", "deck_box"),
                            ("Deck Box for 100 sleeved cards", "deck_box"),
                            ("Stitched Playmat - Forest", "playmat"),
                            ("Dragon Shield Sleeves 60 pack", "sleeves"),
                            ("Dice Bag", "")):
            with self.subTest(title=title):
                self.assertEqual(self.guess(f'<meta property="og:title" content="{title}">')["kind"], kind)

    def test_quantity_only_for_sleeves(self):
        self.assertEqual(self.guess('<meta property="og:title" content="Matte Sleeves 100 Sleeves">')["quantity"], 100)
        self.assertEqual(self.guess('<meta property="og:title" content="Sleeves (60ct)">')["quantity"], 60)
        self.assertIsNone(self.guess('<meta property="og:title" content="Boulder 100 count deck box">')["quantity"])

    def test_kind_from_the_link(self):
        self.assertEqual(self.guess("", "https://shop.example/products/matte-sleeves-black")["kind"], "sleeves")

    def test_lengths_and_controls(self):
        g = self.guess(f'<meta property="og:title" content="{"x" * 200}"><meta property="product:brand" content="{"b" * 60}">')
        self.assertEqual(len(g["name"]), 80)
        self.assertEqual(len(g["brand"]), 40)
        self.assertNotIn("\n", self.guess("<title>a\n\tb</title>")["name"])

    def test_non_utf8_charset(self):
        page = af.parse_page("<title>Écran</title>".encode("latin-1"), "text/html; charset=ISO-8859-1")
        self.assertEqual(page.title, "Écran")
        page = af.parse_page(b"<title>x</title>", "text/html; charset=bogus-charset")
        self.assertEqual(page.title, "x")


# --- Staging -----------------------------------------------------------------

class StagingTests(FetchCase):
    def test_fetch_stages_the_picture(self):
        self.web({"https://cdn.example/a.png": Answer(png())})
        found = af.fetch("https://cdn.example/a.png")
        self.assertRegex(found["token"], r"^[0-9a-f]{32}$")
        path = af.staged_file(found["token"])
        self.assertEqual(path, self.staged / f"{found['token']}.png")
        self.assertEqual(path.read_bytes(), png())
        self.assertTrue(af.STAGED_NAME_RE.fullmatch(path.name))
        self.assertEqual([p.name for p in self.staged.iterdir()], [path.name])   # no temp files left

    def test_refused_fetch_stages_nothing(self):
        self.web({"https://cdn.example/a.gif": Answer(GIF)})
        self.refused("https://cdn.example/a.gif", 502)
        self.assertFalse(self.staged.exists() and any(self.staged.iterdir()))

    def test_old_files_are_pruned_on_fetch(self):
        self.staged.mkdir(parents=True)
        old = self.staged / ("a" * 32 + ".jpg")
        part = self.staged / ".tmp123.part"
        fresh = self.staged / ("b" * 32 + ".png")
        for path in (old, part, fresh):
            path.write_bytes(b"x")
        two_hours_ago = time.time() - 7200
        os.utime(old, (two_hours_ago, two_hours_ago))
        os.utime(part, (two_hours_ago, two_hours_ago))
        self.web({"https://cdn.example/a.png": Answer(png())})
        af.fetch("https://cdn.example/a.png")
        self.assertFalse(old.exists())
        self.assertFalse(part.exists())
        self.assertTrue(fresh.exists())

    def test_staged_file_lookup(self):
        token = af.stage(png(), "png")
        self.assertIsNotNone(af.staged_file(token))
        for bad in ("../" + token, token.upper(), token[:-1], token + ".png", "", None, 5):
            with self.subTest(bad=bad):
                self.assertIsNone(af.staged_file(bad))
        self.assertIsNone(af.staged_file("c" * 32))
        path = af.staged_file(token)
        two_hours_ago = time.time() - 7200
        os.utime(path, (two_hours_ago, two_hours_ago))
        self.assertIsNone(af.staged_file(token))

    def test_stage_refuses_other_extensions(self):
        with self.assertRaises(ValueError):
            af.stage(SVG, "svg")

    def test_prune_without_a_folder(self):
        af.prune_staged()       # nothing staged yet: no error
        self.assertFalse(self.staged.exists())


if __name__ == "__main__":
    unittest.main()
