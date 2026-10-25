"""GET /sym/<code>.svg (lib/api/symbols.py): Scryfall's card symbols, cached in a temp folder.

The network is never used: cards._get_json (the symbol list) and cards._download (each SVG) are
stand-ins that count their calls, so the tests also check that the list is asked for once and each
picture is downloaded once.
"""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from decklab.lib import cards
from decklab.lib.api import symbols
from decklab.lib.api.common import ApiError
from decklab.tests.test_server import ServerTestCase

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="50"/></svg>'
LIST = {"object": "list", "data": [
    {"symbol": "{T}", "english": "tap this permanent", "svg_uri": "https://svgs.scryfall.io/card-symbols/T.svg"},
    {"symbol": "{W/U}", "english": "one white or blue mana", "svg_uri": "https://svgs.scryfall.io/card-symbols/WU.svg"},
    {"symbol": "{½}", "english": "one-half generic mana", "svg_uri": "https://svgs.scryfall.io/card-symbols/HALF.svg"},
    # Never fetched: an address somewhere else, and a name that isn't a code.
    {"symbol": "{X}", "english": "X", "svg_uri": "https://evil.example/card-symbols/X.svg"},
    {"symbol": "{Y}", "english": "Y", "svg_uri": "https://svgs.scryfall.io/card-symbols/../Y.svg"},
]}


class SymbolCache:
    """symbols.SYMBOLS_DIR in a temp folder, with the network replaced; use with `with`."""

    def __init__(self, listing=LIST, svg=SVG, fail=None):
        self.listing, self.svg, self.fail = listing, svg, fail
        self.lists, self.downloads, self.timeouts = [], [], []

    def get_json(self, url, timeout=60):
        self.lists.append(url)
        self.timeouts.append(timeout)
        if self.fail:
            raise self.fail
        return json.loads(json.dumps(self.listing))

    def download(self, url, dest, accept="*/*", timeout=60):
        self.downloads.append((url, accept))
        self.timeouts.append(timeout)
        if self.fail:
            raise self.fail
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.svg)
        return len(self.svg)

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name) / "symbols"
        self.patches = [mock.patch.object(symbols, "SYMBOLS_DIR", self.dir),
                        mock.patch.object(symbols, "_codes", {}), mock.patch.object(symbols, "_asked", {}),
                        mock.patch.object(symbols, "_failed", {}),
                        mock.patch.object(cards, "_get_json", self.get_json),
                        mock.patch.object(cards, "_download", self.download)]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()


class SymbolCacheTests(unittest.TestCase):

    def test_downloads_each_symbol_once_and_the_list_once(self):
        with SymbolCache() as box:
            self.assertEqual(symbols.symbol_svg("T.svg"), SVG)
            self.assertEqual(symbols.symbol_svg("WU.svg"), SVG)
            self.assertEqual(symbols.symbol_svg("T.svg"), SVG)
            self.assertEqual(box.lists, [symbols.SYMBOLOGY_URL])
            self.assertEqual(box.downloads, [("https://svgs.scryfall.io/card-symbols/T.svg", "image/svg+xml"),
                                             ("https://svgs.scryfall.io/card-symbols/WU.svg", "image/svg+xml")])
            self.assertTrue((box.dir / "T.svg").exists())
            self.assertEqual(set(box.timeouts), {symbols.FETCH_TIMEOUT})
            saved = json.loads((box.dir / symbols.LIST_NAME).read_text(encoding="utf-8"))
            self.assertEqual([s["symbol"] for s in saved["data"]], ["{T}", "{W/U}", "{½}"])

    def test_a_saved_list_is_read_not_fetched(self):
        with SymbolCache() as box:
            box.dir.mkdir(parents=True)
            (box.dir / symbols.LIST_NAME).write_text(json.dumps(LIST), encoding="utf-8")
            self.assertEqual(symbols.symbol_svg("HALF.svg"), SVG)
            self.assertEqual(box.lists, [])

    def test_unknown_and_malformed_codes_are_404_and_fetch_nothing_else(self):
        with SymbolCache() as box:
            for name in ("ZZ.svg", "X.svg", "Y.svg"):
                with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                    symbols.symbol_svg(name)
                self.assertEqual(caught.exception.status, 404)
            # An unknown code asks for the list again only once in RELIST_AFTER.
            self.assertEqual(box.lists, [symbols.SYMBOLOGY_URL])
            for name in ("t.svg", "T", "T.png", "../T.svg", "T.svg.svg", "", "A" * 13 + ".svg", "W/U.svg", None):
                with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                    symbols.symbol_svg(name)
                self.assertEqual(caught.exception.status, 404)
            self.assertEqual(box.downloads, [])

    def test_offline_is_503_and_nothing_is_left_behind(self):
        with SymbolCache(fail=urllib.error.URLError("no network")) as box:
            with self.assertRaises(ApiError) as caught:
                symbols.symbol_svg("T.svg")
            self.assertEqual(caught.exception.status, 503)
            self.assertIn("Scryfall", caught.exception.message)
            self.assertFalse((box.dir / "T.svg").exists())
        with SymbolCache() as box:
            box.dir.mkdir(parents=True)
            (box.dir / symbols.LIST_NAME).write_text(json.dumps(LIST), encoding="utf-8")
            box.fail = urllib.error.HTTPError("https://svgs.scryfall.io/card-symbols/T.svg", 500, "down", {}, None)
            with self.assertRaises(ApiError) as caught:
                symbols.symbol_svg("T.svg")
            self.assertEqual(caught.exception.status, 503)

    def test_a_failed_fetch_pauses_asking_scryfall(self):
        # No saved list and no network: the first request asks once, the next ones answer 503 at once
        # (no queue of slow failures, no request to Scryfall each time) until NETWORK_PAUSE has passed.
        clock = [1000.0]
        with SymbolCache(fail=urllib.error.URLError("no network")) as box, \
                mock.patch.object(symbols.time, "monotonic", lambda: clock[0]):
            for name in ("T.svg", "WU.svg", "T.svg"):
                with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                    symbols.symbol_svg(name)
                self.assertEqual(caught.exception.status, 503)
            self.assertEqual(box.lists, [symbols.SYMBOLOGY_URL])
            clock[0] += symbols.NETWORK_PAUSE + 1
            box.fail = None
            self.assertEqual(symbols.symbol_svg("T.svg"), SVG)
            self.assertEqual(box.lists, [symbols.SYMBOLOGY_URL] * 2)
        # A picture's download failing pauses the others too.
        with SymbolCache() as box, mock.patch.object(symbols.time, "monotonic", lambda: clock[0]):
            box.dir.mkdir(parents=True)
            (box.dir / symbols.LIST_NAME).write_text(json.dumps(LIST), encoding="utf-8")
            box.fail = urllib.error.URLError("timed out")
            for name in ("T.svg", "WU.svg"):
                with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                    symbols.symbol_svg(name)
                self.assertEqual(caught.exception.status, 503)
            self.assertEqual(len(box.downloads), 1)

    def test_something_that_isnt_an_svg_is_refused(self):
        with SymbolCache(svg=b"<html><script>alert(1)</script></html>") as box:
            with self.assertRaises(ApiError) as caught:
                symbols.symbol_svg("T.svg")
            self.assertEqual(caught.exception.status, 503)
            self.assertFalse((box.dir / "T.svg").exists())


class SymbolEndpointTests(ServerTestCase):

    def test_symbol_route(self):
        with SymbolCache() as box:
            status, headers, body = self.request("GET", "/sym/WU.svg")
            self.assertEqual((status, body), (200, SVG))
            self.assertEqual(headers["Content-Type"], "image/svg+xml")
            self.assertEqual(headers["Cache-Control"], "public, max-age=604800")
            self.assertIn("sandbox", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(self.request("HEAD", "/sym/T.svg")[:3:2], (200, b""))
            self.assertEqual(len(box.downloads), 2)

    def test_bad_symbol_paths(self):
        with SymbolCache() as box:
            for path in ("/sym/ZZ.svg", "/sym/wu.svg", "/sym/WU", "/sym/..%2fconfig.json", "/sym/%2e%2e",
                         "/sym/WU.svg/x", "/sym/", "/sym"):
                with self.subTest(path=path):
                    self.assertError(path, 404)
            self.assertError("/sym/WU.svg?v=1", 400)
            self.assertError("/sym/WU.svg", 405, "PUT", b"x")
            self.assertEqual(box.downloads, [])

    def test_offline_symbol_is_503(self):
        with SymbolCache(fail=urllib.error.URLError("no network")):
            self.assertIn("Scryfall", self.assertError("/sym/T.svg", 503))


if __name__ == "__main__":
    unittest.main()
