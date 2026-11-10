"""The page's files kept by the browser and sent compressed (E11-S64): the in-memory copy
keyed on size and modified time, gzip negotiation, and the immutable answer only for a
script or stylesheet stamped with the current web revision."""
import gzip
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import build, server_http
from decklab.tests.test_server import WEB_FILES, ServerTestCase

GZIP = {"Accept-Encoding": "gzip, deflate, br"}
NO_CACHE = "no-cache"


class AcceptsGzipTests(unittest.TestCase):

    def test_named_starred_and_refused(self):
        for header, expected in (
                ("gzip", True), ("gzip, deflate, br", True), ("br;q=1.0, GZIP;q=0.5", True),
                ("x-gzip", True), ("*", True), ("deflate, *;q=0.1", True),
                (None, False), ("", False), ("identity", False), ("br, deflate", False),
                ("gzip;q=0", False), ("gzip;q=0.0, *", False), ("*;q=0", False),
                ("gzip;q=abc", False), ("gzipped", False)):
            with self.subTest(header=header):
                self.assertIs(server_http.accepts_gzip(header), expected)


class CompressionTests(ServerTestCase):

    def test_text_files_are_gzipped_with_vary_and_their_own_etag(self):
        for path, name in (("/", "index.html"), ("/app.js", "app.js"), ("/style.css", "style.css"),
                           ("/manifest.webmanifest", "manifest.webmanifest")):
            with self.subTest(path=path):
                _, plain, body = self.request("GET", path)
                self.assertEqual(body, WEB_FILES[name].encode("utf-8"))
                self.assertIsNone(plain["Content-Encoding"])
                self.assertEqual(plain["Vary"], "Accept-Encoding")
                status, packed, data = self.request("GET", path, headers=GZIP)
                self.assertEqual(status, 200)
                self.assertEqual(packed["Content-Encoding"], "gzip")
                self.assertEqual(packed["Vary"], "Accept-Encoding")
                self.assertEqual(int(packed["Content-Length"]), len(data))
                self.assertEqual(gzip.decompress(data), body)
                self.assertNotEqual(packed["ETag"], plain["ETag"])
                self.assertEqual(packed["Cache-Control"], NO_CACHE)
                self.assertEqual(packed["Content-Type"], plain["Content-Type"])

    def test_fonts_and_pictures_never_are(self):
        for path, name in (("/fonts/figtree.woff2", "fonts/figtree.woff2"), ("/icons/icon-192.png", "icons/icon-192.png")):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path, headers=GZIP)
                self.assertEqual((status, body), (200, WEB_FILES[name].encode("utf-8")))
                self.assertIsNone(headers["Content-Encoding"])
                self.assertIsNone(headers["Vary"])

    def test_each_form_revalidates_only_with_its_own_etag(self):
        _, plain, _ = self.request("GET", "/app.js")
        _, packed, _ = self.request("GET", "/app.js", headers=GZIP)
        status, headers, body = self.request("GET", "/app.js", headers={**GZIP, "If-None-Match": packed["ETag"]})
        self.assertEqual((status, body, headers["ETag"], headers["Vary"]), (304, b"", packed["ETag"], "Accept-Encoding"))
        # A proxy that recompressed the answer hands the ETag back as a weak one.
        status, _, _ = self.request("GET", "/app.js", headers={**GZIP, "If-None-Match": "W/" + packed["ETag"]})
        self.assertEqual(status, 304)
        status, _, body = self.request("GET", "/app.js", headers={**GZIP, "If-None-Match": plain["ETag"]})
        self.assertEqual((status, gzip.decompress(body)), (200, WEB_FILES["app.js"].encode("utf-8")))
        status, _, body = self.request("GET", "/app.js", headers={"If-None-Match": packed["ETag"]})
        self.assertEqual((status, body), (200, WEB_FILES["app.js"].encode("utf-8")))

    def test_head_gives_the_gzipped_length_without_a_body(self):
        _, packed, data = self.request("GET", "/app.js", headers=GZIP)
        status, headers, body = self.request("HEAD", "/app.js", headers=GZIP)
        self.assertEqual((status, body, headers["Content-Encoding"]), (200, b"", "gzip"))
        self.assertEqual(int(headers["Content-Length"]), len(data))
        self.assertEqual(headers["ETag"], packed["ETag"])


class MemoryCopyTests(ServerTestCase):

    def test_an_unchanged_file_is_read_and_hashed_once(self):
        path = self.box.web / "style.css"
        server_http._STATIC_CACHE.pop(str(path), None)
        self.request("GET", "/style.css")
        with mock.patch.object(server_http.Path, "read_bytes", side_effect=AssertionError("read again")), \
                mock.patch.object(server_http.hashlib, "sha256", side_effect=AssertionError("hashed again")), \
                mock.patch.object(server_http.gzip, "compress", wraps=gzip.compress) as compress:
            for _ in range(3):
                status, _, body = self.request("GET", "/style.css")
                self.assertEqual((status, body), (200, WEB_FILES["style.css"].encode("utf-8")))
                status, _, body = self.request("GET", "/style.css", headers=GZIP)
                self.assertEqual((status, gzip.decompress(body)), (200, WEB_FILES["style.css"].encode("utf-8")))
        self.assertEqual(compress.call_count, 1)

    def test_an_edited_or_replaced_file_is_served_without_a_restart(self):
        path = self.box.web / "app.js"
        original = path.read_bytes()
        try:
            _, first, _ = self.request("GET", "/app.js", headers=GZIP)
            path.write_bytes(b"console.log('edited, and longer');")
            status, edited, body = self.request("GET", "/app.js", headers=GZIP)
            self.assertEqual((status, gzip.decompress(body)), (200, b"console.log('edited, and longer');"))
            self.assertNotEqual(edited["ETag"], first["ETag"])
            # The same size, a later modified time (an edit in place).
            stat = path.stat()
            path.write_bytes(b"console.log('EDITED, and longer');")
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
            status, _, body = self.request("GET", "/app.js", headers={"If-None-Match": edited["ETag"]})
            self.assertEqual((status, body), (200, b"console.log('EDITED, and longer');"))
            # Replaced by another file (a git pull's rename over it).
            fresh = path.with_name("app.js.new")
            fresh.write_bytes(b"console.log('pulled');")
            os.replace(fresh, path)
            status, _, body = self.request("GET", "/app.js")
            self.assertEqual((status, body), (200, b"console.log('pulled');"))
        finally:
            path.write_bytes(original)

    def test_a_file_changing_while_it_is_read_is_answered_but_not_remembered(self):
        path = self.box.web / "style.css"
        server_http._STATIC_CACHE.pop(str(path), None)
        keys = iter([(1, 1), (2, 2)])
        with mock.patch.object(server_http, "_stat_key", side_effect=lambda _path: next(keys)):
            _, found = server_http.static_body(path)
        self.assertEqual(found.body, WEB_FILES["style.css"].encode("utf-8"))
        self.assertNotIn(str(path), server_http._STATIC_CACHE)

    def test_the_copies_are_bounded(self):
        with mock.patch.object(server_http, "_STATIC_CACHE", {}) as cache, \
                mock.patch.object(server_http, "STATIC_CACHE_FILES", 2):
            for name in ("app.js", "style.css", "index.html"):
                server_http.static_body(self.box.web / name)
            self.assertEqual(list(cache), [str(self.box.web / "index.html")])


class ImmutableTests(ServerTestCase):
    """A served web/ that is the build's own (root/decklab/web), so a ?v= can be the revision."""

    FILES = {"index.html": '<meta name="decklab-web-revision" content="__DECKLAB_WEB_REVISION__">'
                           '<link href="/base.css" rel="stylesheet"><script src="/app.js"></script>',
             "app.js": "console.log('one');", "base.css": "body { margin: 0 }", "fonts/figtree.woff2": "wOF2",
             "manifest.webmanifest": "{}"}

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.web = self.root / "decklab" / "web"
        for name, text in self.FILES.items():
            path = self.web / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        for target, name, value in ((build, "_root", self.root), (build, "_web_assets", None),
                                    (build, "_web_assets_checked", None), (build, "ASSET_RECHECK_SECONDS", 0.0),
                                    (self.httpd, "web_dir", self.web)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def stamp(self):
        return build.web_revision()[:16]

    def cache(self, path, headers=None):
        status, answer, _ = self.request("GET", path, headers=headers)
        self.assertIn(status, (200, 304))
        return answer["Cache-Control"]

    def test_a_stamped_script_or_stylesheet_is_kept_for_good(self):
        _, _, page = self.request("GET", "/")
        stamp = self.stamp()
        for path in ("/app.js", "/base.css"):
            with self.subTest(path=path):
                self.assertIn(f'"{path}?v={stamp}"'.encode(), page)
                self.assertEqual(self.cache(f"{path}?v={stamp}"), server_http.IMMUTABLE)
                self.assertEqual(self.cache(f"{path}?v={stamp}", GZIP), server_http.IMMUTABLE)
        self.assertEqual(server_http.IMMUTABLE, "private, max-age=31536000, immutable")
        status, headers, body = self.request("GET", f"/app.js?v={stamp}", headers=GZIP)
        self.assertEqual(gzip.decompress(body), b"console.log('one');")
        status, again, body = self.request("GET", f"/app.js?v={stamp}", headers={**GZIP, "If-None-Match": headers["ETag"]})
        self.assertEqual((status, body, again["Cache-Control"]), (304, b"", server_http.IMMUTABLE))

    def test_the_page_fonts_unstamped_and_stale_requests_keep_no_cache(self):
        stamp, full = self.stamp(), build.web_revision()
        for path in ("/", "/index.html", f"/index.html?v={stamp}", f"/?v={stamp}", "/app.js", "/base.css",
                     f"/fonts/figtree.woff2?v={stamp}", f"/manifest.webmanifest?v={stamp}",
                     "/app.js?v=3", "/app.js?v=" + "0" * 16, f"/app.js?v={stamp[:15]}", f"/app.js?v={full[:40]}"):
            with self.subTest(path=path):
                status, headers, _ = self.request("GET", path)
                self.assertEqual((status, headers["Cache-Control"]), (200, NO_CACHE))
                self.assertIn("ETag", headers)

    def test_matching_stamps_cost_no_fingerprint_after_the_page_load(self):
        self.request("GET", "/")
        stamp = build._web_assets[1][:16]
        with mock.patch.object(build, "_fingerprints", side_effect=AssertionError("fingerprinted again")):
            for _ in range(3):
                self.assertEqual(self.cache(f"/app.js?v={stamp}"), server_http.IMMUTABLE)
                self.assertEqual(self.cache(f"/base.css?v={stamp}"), server_http.IMMUTABLE)

    def test_an_edit_makes_the_old_stamp_stale_and_the_new_one_current(self):
        old = self.stamp()
        self.assertEqual(self.cache(f"/app.js?v={old}"), server_http.IMMUTABLE)
        (self.web / "app.js").write_bytes(b"console.log('two, edited');")
        status, headers, body = self.request("GET", f"/app.js?v={old}")
        self.assertEqual((status, body, headers["Cache-Control"]), (200, b"console.log('two, edited');", NO_CACHE))
        # Another file's bytes are still the old revision's, but that revision isn't current.
        self.assertEqual(self.cache(f"/base.css?v={old}"), NO_CACHE)
        new = self.stamp()
        self.assertNotEqual(new, old)
        self.assertEqual(self.cache(f"/app.js?v={new}"), server_http.IMMUTABLE)
        self.assertEqual(self.cache(f"/base.css?v={new}"), server_http.IMMUTABLE)

    def test_a_file_changed_since_the_fingerprint_is_never_kept(self):
        stamp = self.stamp()
        path = self.web / "app.js"
        stat = path.stat()
        path.write_bytes(b"console.log('TWO');")       # the same size
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        # Within the recheck interval the remembered fingerprint is the old one: still not kept.
        with mock.patch.object(build, "ASSET_RECHECK_SECONDS", 3600.0), \
                mock.patch.object(build, "_web_assets_checked", build.time.monotonic()):
            self.assertEqual(self.cache(f"/app.js?v={stamp}"), NO_CACHE)
            self.assertEqual(self.cache(f"/base.css?v={stamp}"), server_http.IMMUTABLE)

    def test_rechecks_are_rate_limited(self):
        self.stamp()
        with mock.patch.object(build, "ASSET_RECHECK_SECONDS", 3600.0), \
                mock.patch.object(build, "_fingerprints", wraps=build._fingerprints) as fingerprints:
            for _ in range(4):
                self.assertEqual(self.cache("/app.js?v=" + "0" * 16), NO_CACHE)
        self.assertEqual(fingerprints.call_count, 1)

    def test_another_web_folder_is_never_kept(self):
        stamp = self.stamp()
        with tempfile.TemporaryDirectory() as other:
            (Path(other) / "app.js").write_bytes(b"console.log('one');")
            stat = (self.web / "app.js").stat()
            os.utime(Path(other) / "app.js", ns=(stat.st_atime_ns, stat.st_mtime_ns))
            with mock.patch.object(self.httpd, "web_dir", Path(other)):
                self.assertEqual(self.cache(f"/app.js?v={stamp}"), NO_CACHE)

    def test_unreadable_web_files_keep_no_cache(self):
        stamp = self.stamp()
        with mock.patch.object(build, "_web_assets", None), \
                mock.patch.object(build, "_fingerprints", side_effect=PermissionError("private local path")):
            self.assertEqual(self.cache(f"/app.js?v={stamp}"), NO_CACHE)


if __name__ == "__main__":
    unittest.main()
