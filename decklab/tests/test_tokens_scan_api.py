"""The Tokens page's Scan token cards (E7-S32): POST /api/tokens/scan and /api/tokens/scan/add
(lib/api/tokens_scan.py), scan.propose_tokens and the tokens.add_many operation, in
test_collection_edit's sandbox with the token fixture card index (fixtures/tokens_cards.jsonl).

A photo is read by a stand-in for the OCR engine (never Windows' own: CI is Linux) and answered with
the token faces it may be. Nothing is written by a scan, and its temporary photo is gone afterwards.
The reviewed list is added as one change, each row kept apart from a row naming the same card. Only
the space's own people may scan or add to its tokens, as they edit them.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_tokens_scan_api
"""
import base64
import inspect
from unittest import mock

from decklab.lib import cards, inventory, scan, tokens
from decklab.lib.api import collection_scan as cs
from decklab.lib.api import tokens as api_tokens
from decklab.lib.api import tokens_scan as ts
from decklab.lib.state import Conflict, Invalid
from decklab.lib.tokens import ops as token_ops
from decklab.tests import scan_image
from decklab.tests import test_collection_edit as tce
from decklab.tests.test_tokens import FIXTURES

PHOTO = base64.b64encode(scan_image.png(["FDN EN"], scale=2)).decode("ascii")
FISH = ["Fish", "Token Creature — Fish", "1/1", "T 0007", "BLB • EN"]

_loaded = None


def _index():
    global _loaded
    if _loaded is None:
        _loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                   {}, log=lambda *a: None))
    return _loaded


class ProposeTokensTests(tce.CollectionEditTestCase):
    """scan.propose_tokens over the token fixture index."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(cards, "_index", _index())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_face_and_its_printing_read_agree(self):
        answer = scan.propose_tokens(FISH)
        self.assertEqual(answer["read"]["name"], "Fish")
        self.assertEqual(answer["proposals"], [{"front": "Fish", "faces": ["Fish"], "set": "tblb", "collector_number": "7",
                                                "set_name": "TBLB", "how": "name and number"}])
        self.assertEqual(answer["message"], "Read Fish, TBLB 7.")

    def test_only_the_name_proposes_no_printing(self):
        answer = scan.propose_tokens(["Treasure", "Token Artifact — Treasure"])
        self.assertEqual([(p["front"], p["set"], p["how"]) for p in answer["proposals"]], [("Treasure", "", "name")])
        self.assertIn("none is recorded unless you choose one", answer["message"])

    def test_a_misread_name_is_matched_closely(self):
        self.assertEqual(scan.propose_tokens(["Fsh"])["proposals"][0]["front"], "Fish")
        self.assertEqual(scan.propose_tokens(["Qwxzv"])["proposals"], [])

    def test_a_printing_without_the_face_read_is_offered_not_taken(self):
        answer = scan.propose_tokens(["Rabbit", "T 0007", "BLB • EN"])
        self.assertEqual([(p["front"], p["set"], p["how"]) for p in answer["proposals"]],
                         [("Rabbit", "", "name"), ("Fish", "tblb", "number")])
        self.assertIn("name another token", answer["message"])
        answer = scan.propose_tokens(["T 0005", "FDN • EN"])        # no name: the printing, to check
        self.assertEqual([(p["front"], p["set"], p["how"]) for p in answer["proposals"]], [("Rabbit", "tfdn", "number")])

    def test_a_double_faced_name_gives_its_first_face_and_never_a_back(self):
        answer = scan.propose_tokens(["The Ring // The Ring Tempts You"])
        self.assertEqual(answer["proposals"], [{"front": "The Ring", "faces": ["The Ring"], "set": "", "collector_number": "",
                                                "set_name": "", "how": "name"}])
        self.assertNotIn("back", answer["proposals"][0])

    def test_nothing_readable_says_to_type_the_name(self):
        self.assertIn("type the token's name", scan.propose_tokens([])["message"])
        self.assertIn("names no token printing", scan.propose_tokens(["T 0999", "BLB • EN"])["message"])


class TokenScanTestCase(tce.CollectionEditTestCase):

    def setUp(self):
        super().setUp()
        self.read = []
        self.lines = list(FISH)

        def fake_ocr(path):
            self.read.append((path, path.exists()))
            if isinstance(self.lines, Exception):
                raise self.lines
            return self.lines
        for target, name, value in ((ts, "OCR", fake_ocr), (cards, "_index", _index())):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)

    def scan(self, space="home", profile="matt", **data):
        data.setdefault("photo", PHOTO)
        return self.call(ts.scan_token, profile, space=space, **data)

    def sha(self, space="home"):
        return tokens.read(space=space).sha256

    def add(self, rows, space="home", profile="matt", **data):
        data.setdefault("sha256", self.sha(space))
        return self.call(ts.add_scanned, profile, space=space, rows=rows, **data)

    def token_rows(self, space="home"):
        return tokens.read(space=space).rows


class ScanTests(TokenScanTestCase):

    def test_a_photo_is_answered_with_token_faces_and_nothing_is_written(self):
        before = self.magic_files()
        answer = self.scan()
        self.assertEqual((self.magic_files(), self.writes), (before, []))
        self.assertFalse(answer["unread"])
        self.assertEqual(answer["lines"], FISH)
        first = answer["proposals"][0]
        self.assertEqual({k: first[k] for k in ("front", "faces", "set", "collector_number", "how", "img_small")},
                         {"front": "Fish", "faces": ["Fish"], "set": "tblb", "collector_number": "7",
                          "how": "name and number", "img_small": "/img/tblb/7/small"})
        self.assertNotIn("back", first)
        (path, existed), = self.read
        self.assertTrue(existed)
        self.assertFalse(path.exists())         # the photo is kept only while it's read

    def test_only_the_space_s_own_people_may_scan_its_tokens(self):
        with self.as_("user1"):
            self.assertTrue(self.scan(profile="user1")["ok"])
        with self.as_("user2"):
            self.assertTrue(self.scan("user2", "user2")["ok"])
            self.assertApiError(403, self.scan, "home", "user2", contains="That collection isn't public.")
            self.assertApiError(403, self.scan, "user3", "user2", contains="That collection isn't public.")
            self.assertApiError(403, self.scan, "nobody", "user2", contains="That collection isn't public.")
        self.assertApiError(403, self.scan, "user2", "matt", contains="That collection isn't public.")
        self.assertEqual(len(self.read), 2)         # no refusal read the photo
        self.assertEqual(self.writes, [])

    def test_an_engine_that_cant_read_says_to_type_the_token_s_name(self):
        self.lines = scan.OcrUnavailable("Tesseract isn't installed. Type the card's name instead.")
        answer = self.scan()
        self.assertTrue(answer["unread"])
        self.assertEqual((answer["proposals"], answer["read"]), ([], None))
        self.assertTrue(answer["message"].endswith("Type the token's name instead."))

    def test_one_photo_at_a_time_with_the_collection_s_scanner(self):
        self.assertTrue(cs._scan_lock.acquire(blocking=False))
        try:
            self.assertApiError(429, self.scan, contains="Another photo")
        finally:
            cs._scan_lock.release()
        self.lines = OSError("disk full")
        self.assertApiError(500, self.scan, contains="couldn't be read on the PC")
        self.assertTrue(cs._scan_lock.acquire(blocking=False))
        cs._scan_lock.release()

    def test_bad_requests_are_refused_before_ocr(self):
        self.assertApiError(400, self.scan, photo="not base64!", contains="isn't valid base64")
        self.assertApiError(400, self.scan, rows=[], contains="Unknown key")
        self.assertEqual(self.read, [])

    def test_the_routes_are_write_routes_with_their_own_body_limits(self):
        from decklab.lib import feature_routes
        source = inspect.getsource(feature_routes.dispatch)
        self.assertIn('("tokens", "scan"): (tokens_scan.scan_token, collection_scan.MAX_SCAN_BODY)', source)
        self.assertIn('("tokens", "scan", "add"): (tokens_scan.add_scanned, tokens_scan.MAX_ADD_BODY)', source)


class AddTests(TokenScanTestCase):

    def test_the_scanned_list_is_added_as_one_change(self):
        rows = [{"front": "fish", "set": "tblb", "front_collector_number": "7", "quantity": 2},
                {"front": "Treasure", "quantity": "1", "single_sided": True},
                {"front": "The Ring", "back": "The Ring Tempts You", "set": "tltr", "front_collector_number": "H13",
                 "back_collector_number": "H13", "quantity": 1}]
        answer = self.add(rows)
        self.assertEqual(answer["added"], {"rows": 3, "cards": 4})
        self.assertEqual(len(self.writes), 1)
        message, actor, reason, summary = self.writes[0]
        self.assertEqual((message, actor.name, reason), ("add 4 scanned token cards", "Matt", None))
        self.assertEqual(summary.counts["added_rows"], 3)
        added = {row["front"]: row for row in self.token_rows()}
        self.assertEqual({k: added["Fish"][k] for k in ("back", "set", "front_collector_number", "finish", "quantity",
                                                        "front_details", "notes")},
                         {"back": "", "set": "tblb", "front_collector_number": "7", "finish": "", "quantity": "2",
                          "front_details": "", "notes": "Added from a scan; reverse face unconfirmed"})
        self.assertEqual(added["Treasure"]["notes"], "Added from a scan; single-sided verified")
        self.assertEqual((added["The Ring"]["back"], added["The Ring"]["notes"]), ("The Ring Tempts You", "Added from a scan"))
        self.assertEqual(answer["warnings"], [ts.BLANK_BACKS.format(n=1)])
        self.assertEqual(len(answer["data"]["rows"]), len(self.token_rows()))

    def test_a_card_already_listed_is_kept_as_a_row_of_its_own(self):
        self.add([{"front": "Fish", "quantity": 1}])
        self.add([{"front": "Fish", "quantity": 2}])
        self.assertEqual(sorted(row["quantity"] for row in self.token_rows() if row["front"] == "Fish"), ["1", "2"])
        self.assertEqual(len(self.writes), 2)

    def test_a_member_adds_to_their_own_tokens_only(self):
        with self.as_("user2"):
            self.assertIsNone(self.sha("user2"))
            self.add([{"front": "Rabbit", "quantity": 3}], "user2", "user2", sha256=None)
            self.assertEqual(self.last_write(), ("add 3 scanned token cards (User2's tokens)", "User2"))
            self.assertApiError(403, self.add, [{"front": "Fish", "quantity": 1}], "home", "user2",
                                contains="That collection isn't public.")
        self.assertApiError(403, self.add, [{"front": "Fish", "quantity": 1}], "user2", "matt", sha256="0" * 64,
                            contains="That collection isn't public.")
        self.assertEqual(len(self.writes), 1)

    def test_rows_are_checked_and_nothing_is_saved_when_one_is_wrong(self):
        before = self.magic_files()
        fish = {"front": "Fish", "quantity": 1}
        for rows, words in (
                ([{"front": "Fishh", "quantity": 1}], "Did you mean Fish?"),
                ([fish, {"front": "Fish", "set": "tfdn", "front_collector_number": "5", "quantity": 1}], "tfdn 5 is Rabbit"),
                ([fish, {"front": "Fish", "quantity": 2}], "Token cards 1 and 2 are the same card"),
                ([{"front": "Fish", "quantity": 1, "finish": "foil"}], "unknown key 'finish'"),
                ([{"front": "Fish", "quantity": 1, "front_details": "1/1"}], "unknown key 'front_details'"),
                ([{"front": "Rabbit", "back": "Rabbit", "quantity": 1, "single_sided": True}], "isn't single-sided"),
                ([{"front": "Fish", "quantity": 0}], "Quantity"),
                ([{"front": "Fish"}], "needs its front name and quantity"),
                ([], "rows must list 1 to 50"),
                ([{"front": "Fish", "quantity": 1, "back": f"x{i}"} for i in range(51)], "rows must list 1 to 50")):
            with self.subTest(words=words):
                self.assertApiError(400, self.add, rows, contains=words)
        self.assertEqual((self.magic_files(), self.writes), (before, []))

    def test_a_list_changed_since_answers_with_the_latest(self):
        stale = self.sha()
        self.add([{"front": "Fish", "quantity": 1}])
        error = self.assertApiError(409, self.add, [{"front": "Treasure", "quantity": 1}], sha256=stale)
        self.assertEqual(error.extra["latest"]["sha256"], self.sha())
        self.assertEqual(len(self.writes), 1)


class AddManyOperationTests(TokenScanTestCase):
    """token_ops.add_many on the sandbox's inventory, without saving."""

    def test_two_fully_known_rows_are_refused_naming_the_row(self):
        known = {"front": "Fish", "back": "", "set": "tblb", "front_collector_number": "7", "back_collector_number": "",
                 "finish": "nonfoil", "quantity": "1", "front_details": "", "back_details": "", "notes": "single-sided verified"}
        inv = inventory.current()
        inv, _ = token_ops.add_many(inv, space="home", sha256=self.sha(), rows=[known])
        sha = api_tokens.inventory_files.rendered_sha256(inv.token_set("home"))
        with self.assertRaises(Conflict) as caught:
            token_ops.add_many(inv, space="home", sha256=sha, rows=[{**known, "front": "Treasure", "set": ""}, known])
        self.assertTrue(str(caught.exception).startswith("Token card 2: "), str(caught.exception))
        with self.assertRaises(Invalid):
            token_ops.add_many(inv, space="home", sha256=sha, rows=[])
        with self.assertRaises(token_ops.Stale):
            token_ops.add_many(inv, space="home", sha256="0" * 64, rows=[known])
        self.assertEqual(self.writes, [])
