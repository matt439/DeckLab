"""The Collection page's Scan cards (E7-S32): POST /api/collection/scan (lib/api/collection_scan.py), in
test_collection_edit's sandbox. A photo is read by a stand-in for the OCR engine (never Windows' own:
CI is Linux) and answered with the printings it may be, from the fixture card index. Nothing is
written: no inventory change, no raw import, and the photo's temporary file is gone afterwards. Only
the space's own people may scan into its collection, as they edit it; a proposal fed to the import
preview as a collection-columns row previews as one card to add.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_collection_scan_api
"""
import base64
import inspect
from unittest import mock

from decklab.lib import scan
from decklab.lib.api import card_lookup
from decklab.lib.api import collection_edit as ce
from decklab.lib.api import collection_scan as cs
from decklab.tests import scan_image
from decklab.tests import test_collection_edit as tce

PNG = scan_image.png(["FDN EN"], scale=2)
PHOTO = base64.b64encode(PNG).decode("ascii")
ELVES = ["Llanowar Elves", "Creature — Elf Druid", "{T}: Add {G}.", "0227 C", "FDN • EN Artist", "1/1"]


class ScanApiTests(tce.CollectionEditTestCase):

    def setUp(self):
        super().setUp()
        self.read = []                  # (path, bytes, exists) of each photo the stand-in OCR read
        self.lines = list(ELVES)

        def fake_ocr(path):
            self.read.append((path, path.read_bytes(), path.exists()))
            if isinstance(self.lines, Exception):
                raise self.lines
            return self.lines
        patcher = mock.patch.object(cs, "OCR", fake_ocr)
        patcher.start()
        self.addCleanup(patcher.stop)

    def scan(self, space="home", profile="matt", **data):
        data.setdefault("photo", PHOTO)
        return self.call(cs.scan_photo, profile, space=space, **data)

    def test_a_photo_is_answered_with_its_printing_and_nothing_is_written(self):
        before = self.magic_files()
        answer = self.scan()
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertFalse(answer["unread"])
        self.assertEqual(answer["space"], "home")
        self.assertEqual(answer["lines"], ELVES)
        self.assertEqual(answer["read"]["name"], "Llanowar Elves")
        self.assertEqual(answer["read"]["numbers"], ["227"])
        first = answer["proposals"][0]
        self.assertEqual({k: first[k] for k in ("name", "set", "collector_number", "finish", "language", "how")},
                         {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                          "language": "en", "how": "name and number"})
        self.assertEqual(first["img_small"], "/img/fdn/227/small")
        self.assertEqual(first["finishes"], ["nonfoil", "foil"])     # the pending row's finish choices
        self.assertEqual(first["owned"], 5)         # the home collection's copies of that printing and finish
        self.assertIn("Llanowar Elves, FDN 227", answer["message"])
        self.assertNotIn("condition", first)        # the person holding the card says

    def test_the_photo_is_kept_only_while_it_is_read(self):
        self.scan()
        (path, data, existed), = self.read
        self.assertEqual(data, PNG)
        self.assertTrue(existed)
        self.assertEqual(path.suffix, ".png")
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        jpeg = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffc0000b080020002001011100"
                             "ffda0008010100003f00d2cf20ffd9")
        self.scan(photo=base64.b64encode(jpeg).decode("ascii"))
        self.assertEqual(self.read[-1][0].suffix, ".jpg")

    def test_owned_copies_are_the_scanning_space_s_own(self):
        with self.as_("user2"):
            answer = self.scan("user2", "user2")
        self.assertEqual(answer["space"], "user2")
        self.assertEqual(answer["proposals"][0]["owned"], 2)
        self.assertEqual(self.writes, [])

    def test_a_pending_card_s_other_printings_count_the_scanning_space_s_own_copies(self):
        # The pending list's "Other printings…" is the shared printing picker (GET /api/cards/printings): its copies
        # are the viewer's own space's, the one they scan into, as the scan's proposals are; never home's for a member.
        def fdn_owned():
            answer = card_lookup.printings("Llanowar Elves")
            return next(p["owned"] for p in answer["printings"] if (p["set"], p["number"], p["finish"]) == ("fdn", "227", "nonfoil"))
        with mock.patch.object(card_lookup.cards, "usd_to_aud", side_effect=RuntimeError("offline")):
            with self.as_("user2"):
                self.assertEqual(fdn_owned(), self.scan("user2", "user2")["proposals"][0]["owned"])
                self.assertEqual(fdn_owned(), 2)
            with self.as_("matt"):
                self.assertEqual(fdn_owned(), 5)
        self.assertEqual(self.writes, [])

    def test_only_the_space_s_own_people_may_scan_into_it(self):
        # As the Collection page's edits: User1 scans into home's, a member only into their own, and Matt,
        # an admin, not into a member's. Each refusal is the hidden collection's words, before OCR runs.
        with self.as_("user1"):
            self.assertTrue(self.scan(profile="user1")["ok"])
        with self.as_("user2"):
            error = self.assertApiError(403, self.scan, "home", "user2")
            self.assertEqual(error.message, "That collection isn't public.")
            self.assertApiError(403, self.scan, "user3", "user2", contains="That collection isn't public.")
            self.assertApiError(403, self.scan, "nobody", "user2", contains="That collection isn't public.")
        self.assertApiError(403, self.scan, "user2", "matt", contains="That collection isn't public.")
        with self.as_("user2"):
            self.assertApiError(403, self.scan, "user2", "user3")       # not as someone else
        self.assertEqual(len(self.read), 1)
        self.assertEqual(self.writes, [])

    def test_an_engine_that_cant_read_is_a_plain_sentence_and_no_proposals(self):
        self.lines = scan.OcrUnavailable("Windows' OCR engine is only on Windows. Tesseract isn't installed. "
                                         "Type the card's name instead.")
        answer = self.scan()
        self.assertTrue(answer["unread"])
        self.assertEqual((answer["proposals"], answer["read"], answer["lines"]), ([], None, []))
        self.assertTrue(answer["message"].endswith("Type the card's name instead."))
        self.assertFalse(self.read[0][0].exists())

    def test_nothing_readable_proposes_nothing(self):
        self.lines = []
        answer = self.scan()
        self.assertFalse(answer["unread"])
        self.assertEqual(answer["proposals"], [])
        self.assertIn("type the card's name", answer["message"])

    def test_only_the_name_offers_its_printings(self):
        self.lines = ["Llanowar Elves", "Creature — Elf Druid"]
        answer = self.scan()
        self.assertTrue(answer["proposals"])
        self.assertTrue(all(p["how"] == "name" and p["name"] == "Llanowar Elves" for p in answer["proposals"]))
        self.assertIn("choose the printing", answer["message"])

    def test_what_was_read_is_bounded(self):
        self.lines = ["x" * 500] * 100
        answer = self.scan()
        self.assertEqual(len(answer["lines"]), cs.MAX_LINES)
        self.assertTrue(all(len(line) == cs.MAX_LINE for line in answer["lines"]))

    def test_bad_photos_are_refused_before_ocr(self):
        webp = b"RIFF" + (26).to_bytes(4, "little") + b"WEBPVP8L" + (10).to_bytes(4, "little") + b"\0" * 10
        for photo, status, words in (
                ("", 400, "photo must be"),
                (5, 400, "photo must be"),
                ("not base64!", 400, "isn't valid base64"),
                (base64.b64encode(b"just text").decode("ascii"), 400, "isn't a JPEG or PNG"),
                (base64.b64encode(webp).decode("ascii"), 400, "isn't a JPEG or PNG"),
                (base64.b64encode(PNG[:-12]).decode("ascii"), 400, "isn't a JPEG or PNG"),
                ("A" * (cs.accessory_upload.MAX_BASE64 + 4), 413, "more than 4 MiB")):
            with self.subTest(words=words, photo=str(photo)[:12]):
                self.assertApiError(status, self.scan, photo=photo, contains=words)
        self.assertApiError(400, self.scan, price=1, contains="Unknown key")
        self.assertApiError(400, lambda: self.call(cs.scan_photo, "matt"), contains="needs photo")
        self.assertEqual(self.read, [])

    def test_a_tiny_picture_is_refused(self):
        tiny = scan_image.png([" "], scale=1, margin=1)     # 8 by 12 pixels
        self.assertApiError(400, self.scan, photo=base64.b64encode(tiny).decode("ascii"), contains="16 to 10,000")

    def test_one_photo_at_a_time(self):
        self.assertTrue(cs._scan_lock.acquire(blocking=False))
        try:
            self.assertApiError(429, self.scan, contains="Another photo")
        finally:
            cs._scan_lock.release()
        self.assertTrue(self.scan()["ok"])

    def test_the_lock_is_released_after_an_engine_failure(self):
        self.lines = OSError("disk full")
        self.assertApiError(500, self.scan, contains="couldn't be read on the PC")
        self.assertTrue(cs._scan_lock.acquire(blocking=False))
        cs._scan_lock.release()

    def test_a_proposal_previews_as_a_collection_columns_import(self):
        # The page's Review: each pending card as a row in the collection's own columns, condition left blank.
        first = self.scan()["proposals"][0]
        text = tce.HEADER + ",".join([first["name"], first["set"], first["collector_number"], first["finish"],
                                      "2", "", first["language"], ""]) + "\n"
        preview = self.call(ce.import_preview, "matt", space="home", filename="scan-2026-10-29.csv", text=text)
        self.assertEqual(preview["format"], "collection")
        self.assertEqual(preview["problems"], [])
        self.assertEqual(preview["adds"], {"rows": 1, "cards": 2})
        self.assertEqual(preview["rows"][0]["condition"], "")
        self.assertEqual(self.writes, [])

    def test_the_route_is_a_write_route_with_its_own_body_limit(self):
        from decklab.lib import feature_routes
        self.assertIn('("collection", "scan"): (collection_scan.scan_photo, collection_scan.MAX_SCAN_BODY)',
                      inspect.getsource(feature_routes.dispatch))
        self.assertGreater(cs.MAX_SCAN_BODY, cs.accessory_upload.MAX_BASE64)
