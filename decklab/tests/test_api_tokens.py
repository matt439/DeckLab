"""Tests for decklab.lib.api.tokens: the Tokens page's view and writes.

Each test builds a small repository in a temp folder (magic/ with a
tokens.csv, a deck or two, an empty status.csv and, where a test needs one,
a pending token order), installs it as the inventory (FileInventory: plain
files, no commits) and points config, decks and pool
at it. Most tests run
with no card index, as on a fresh clone; WithIndex tests build a small one
from fixtures/tokens_cards.jsonl. Nothing touches the real repo, its
decklab/data/ or the network. The same writes on the database backend are
in test_token_ops.py.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_api_tokens
"""
import contextlib
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, config, decks, inventory, pool, tokens
from decklab.lib.api import common
from decklab.lib.api import tokens as api_tok
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import rules
from decklab.lib.inventory.files import FileInventory
from decklab.tests.test_tokens import FIXTURES, HEADER, MTGMATE, deck_md

NOTE = "printing unconfirmed"
ROWS = HEADER + (
    f"Angel,The Monarch,,,,,1,,,{NOTE}\n"
    f"Insect,Goblin,,,,,1,1/1; flying; no deathtouch,,{NOTE}\n"
    f"Zombie,Zombie Knight,,,,,8,,,{NOTE}\n"
)
FISH = {"front": "Fish", "back": "", "set": "tblb", "front_collector_number": "7", "back_collector_number": "",
        "finish": "nonfoil", "quantity": 2, "front_details": "1/1; blue", "back_details": "",
        "notes": "single-sided verified"}
RABBIT = {"front": "Rabbit", "back": "Rabbit", "quantity": 2, "notes": NOTE}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def base(row):
    """A view row as the page sends it back: its ten values as text."""
    return {key: str(row[key]) for key in tokens.FIELDS}


class TokensApiTestCase(unittest.TestCase):
    """A temp repository with ROWS as magic/tokens.csv and a building deck
    (casual/queen: Hornet Queen) and no card index, installed as the
    inventory (self.inventory)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.magic = self.root / "magic"
        self.data = self.root / "decklab" / "data"
        self.path = self.magic / "tokens.csv"
        self.pending = self.data / "inventory-pending.json"     # the old git mode's record: never written now
        for sub in ("products", "decks/casual", "decks/commander", "orders/records", "orders/tokens"):
            (self.magic / sub).mkdir(parents=True)
        self.logs = []
        for target, name, value in (
                (config, "REPO", self.root), (config, "DATA", self.data), (config, "MAGIC", self.magic),
                (decks, "REPO", self.root), (pool, "REPO", self.root),
                (decks, "DECKS_DIR", self.magic / "decks"),
                (cards, "INDEX_FILE", self.root / "no-index.json.gz"), (cards, "_index", self.index()),
                (common, "_log", self.logs.append),
                (api_tok, "_writer", lambda data: {"id": data.get("profile"), "name": "Matt", "role": "admin"})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)
        self.inventory = FileInventory(self.root)
        self.addCleanup(inventory.use(self.inventory))
        self.write("tokens.csv", ROWS)
        self.write("decks/casual/queen.md", deck_md("Queen Deck", deck="1 Hornet Queen\n"))
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n")

    def index(self):
        return None

    # ---- helpers

    def write(self, rel, text):
        path = self.magic / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return path

    def magic_files(self):
        """{path under magic/: bytes} of every file there."""
        return {p.relative_to(self.magic).as_posix(): p.read_bytes() for p in self.magic.rglob("*") if p.is_file()}

    def csv_text(self):
        return self.path.read_bytes().decode("utf-8")

    def call(self, function, **data):
        # One snapshot per request, as server_http pins it (unless the test pins its own).
        with inventory.pinned() if not inventory.is_pinned() else contextlib.nullcontext():
            return function(json.dumps({"profile": "matt", **data}).encode())

    def save(self, **data):
        if "sha256" not in data:
            data["sha256"] = self.view()["sha256"]
        return self.call(api_tok.save_token, **data)

    def view(self):
        return api_tok.tokens_view()

    def row(self, front, back=None):
        """A view row by its faces."""
        return next(r for r in self.view()["rows"] if r["front"] == front and (back is None or r["back"] == back))

    def error(self, **data):
        if "sha256" not in data:
            data["sha256"] = self.view()["sha256"]
        with self.assertRaises(ApiError) as caught:
            self.call(api_tok.save_token, **data)
        return caught.exception


class ViewTests(TokensApiTestCase):

    def test_rows_without_card_data(self):
        view = self.view()
        self.assertEqual((view["exists"], view["sorted"], view["index_ready"], view["cards"]), (True, True, False, 10))
        self.assertEqual(view["sha256"], sha(self.path.read_bytes()))
        zombie = view["rows"][2]
        self.assertEqual((zombie["key"], zombie["index"], zombie["quantity"]), ("r2", 2, 8))
        self.assertEqual(zombie["faces"], [
            {"side": "front", "name": "Zombie", "details": "", "known": None, "image": None, "example": None},
            {"side": "back", "name": "Zombie Knight", "details": "", "known": None, "image": None, "example": None}])
        self.assertEqual((zombie["single_sided"], zombie["unconfirmed"], zombie["uses"]), (False, True, []))
        self.assertEqual((view["missing"], view["face_names"], view["problems"]), ([], [], []))
        self.assertIn(tokens.NAMES_UNCHECKED, view["info"])
        self.assertNotIn("uncommitted", view)              # nothing is committed to git
        self.assertNotIn("commit_pending", view)

    def test_a_missing_file_and_a_bad_row(self):
        self.path.unlink()
        view = self.view()
        self.assertEqual((view["exists"], view["sha256"], view["rows"], view["cards"]), (False, None, [], 0))
        self.write("tokens.csv", ROWS + "Bad,,,,,,0,,,\n")
        view = self.view()
        self.assertEqual(len(view["rows"]), 3)
        self.assertEqual(view["problems"], ["magic/tokens.csv line 5: tokens need a front name and positive "
                                            "physical quantity"])

    def test_incoming_orders_are_listed(self):
        rel = "magic/orders/tokens/2026-10-07-shop-a.csv"
        (self.root / rel).write_bytes(rules.csv_bytes(MTGMATE, rules.TOKEN_FIELDS))
        self.write("orders/records/2026-10-07-shop-a.json", json.dumps({
            "version": 1, "id": "2026-10-07-shop-a", "seller": "MTGMate", "ordered_on": "2026-10-07",
            "sources": [], "notes": "", "components": [{"id": "tokens", "kind": "tokens", "path": rel,
                                                        "status": "pending", "received_on": "", "checks": []}]}))
        incoming = self.view()["incoming"]
        self.assertEqual([(i["order"], i["component"], i["path"], i["cards"]) for i in incoming],
                         [("2026-10-07-shop-a", "tokens", rel, 18)])
        self.assertEqual(incoming[0]["rows"][0], {"front": "Fish", "back": "", "quantity": 2,
                                                  "front_details": "1/1; blue; Token Creature — Fish",
                                                  "back_details": ""})


class SaveTests(TokensApiTestCase):

    def test_add_edit_and_remove_write_sorted_lf_files(self):
        before = self.csv_text().splitlines()
        answer = self.save(action="add", row=RABBIT)
        self.assertNotIn("commit", answer)
        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", raw)
        after = self.csv_text().splitlines()
        self.assertEqual(after, [*before[:3], f"Rabbit,Rabbit,,,,,2,,,{NOTE}", before[3]])    # sorted by name
        self.assertEqual(answer["index"], 2)
        self.assertEqual(answer["data"]["rows"][2]["front"], "Rabbit")

        zombie = self.row("Zombie")
        answer = self.save(action="edit", base=base(zombie), row={**base(zombie), "quantity": 7})
        self.assertEqual(self.csv_text().splitlines()[:-1], after[:-1])       # untouched rows, byte for byte
        self.assertEqual(self.csv_text().splitlines()[-1], f"Zombie,Zombie Knight,,,,,7,,,{NOTE}")

        answer = self.save(action="remove", base=base(self.row("Rabbit")), reason="Traded to User1")
        self.assertIsNone(answer["index"])
        self.assertNotIn("Rabbit", self.csv_text())
        self.assertEqual(answer["warnings"], [])

    def test_names_are_saved_unchecked_with_a_warning_without_card_data(self):
        answer = self.save(action="add", row={"front": "Sprit", "quantity": "1"})
        self.assertEqual(answer["warnings"], [tokens.NAMES_UNCHECKED, api_tok.BLANK_BACK])
        self.assertIn("Sprit,,,,,,1,,,", self.csv_text())

    def test_a_single_sided_card_with_its_note_has_no_warning(self):
        answer = self.save(action="add", row=FISH)
        self.assertEqual(answer["warnings"], [tokens.NAMES_UNCHECKED])
        fish = self.row("Fish")
        self.assertEqual((fish["single_sided"], fish["unconfirmed"], fish["quantity"]), (True, False, 2))
        self.assertEqual([f["side"] for f in fish["faces"]], ["front"])
        self.assertEqual(self.csv_text().splitlines()[-1], "Fish,,tblb,7,,nonfoil,2,1/1; blue,,single-sided verified")

    def test_an_edit_keeps_the_columns_left_out(self):
        insect = self.row("Insect")
        self.save(action="edit", base=base(insect), row={"quantity": "3"})
        self.assertIn(f"Insect,Goblin,,,,,3,1/1; flying; no deathtouch,,{NOTE}", self.csv_text())

    def test_the_same_card_asks_first(self):
        e = self.error(action="add", row={**base(self.row("Zombie")), "quantity": 2})
        self.assertEqual(e.status, 409)
        self.assertEqual(e.message, "That card is already listed (Zombie / Zombie Knight ×8). "
                                    "Add to its quantity instead?")
        self.assertEqual(e.extra["same_row"], {"index": 2, "separate_allowed": True, "row": {
            **base(self.row("Zombie")), "quantity": 8}})
        # Unverified rows may be kept apart, as receipts keep them.
        self.save(action="add", row={**base(self.row("Zombie")), "quantity": 2}, separate=True)
        self.assertEqual([r["quantity"] for r in self.view()["rows"] if r["front"] == "Zombie"], [8, 2])
        # Two rows already kept apart: an edit of one that keeps its card isn't asked about.
        second = self.view()["rows"][3]
        self.save(action="edit", base=base(second), row={"quantity": 3})
        self.assertEqual([r["quantity"] for r in self.view()["rows"] if r["front"] == "Zombie"], [8, 3])

    def test_known_cards_cant_be_kept_apart(self):
        self.save(action="add", row=FISH)
        e = self.error(action="add", row={**FISH, "quantity": 1, "notes": "single-sided verified; from a box"})
        self.assertEqual((e.status, e.extra["same_row"]["separate_allowed"]), (409, False))
        e = self.error(action="add", row={**FISH, "quantity": 1}, separate=True)
        self.assertEqual((e.status, e.message), (409, "Those are the same card; change its quantity instead."))
        # An edit into another known card is asked about too.
        self.save(action="add", row={**FISH, "front_collector_number": "8"})
        e = self.error(action="edit", base=base(self.row("Fish")), row={"front_collector_number": "8"})
        self.assertEqual(e.status, 409)
        self.assertIn("same_row", e.extra)
        # The edit sheet has no "Add to that card" button, so an edit isn't asked that.
        self.assertTrue(e.message.startswith("That card is already listed ("))
        self.assertNotIn("Add to its quantity", e.message)

    def test_every_row_naming_the_card_counts_when_keeping_it_apart(self):
        known = {**FISH, "notes": "single-sided verified; from a box"}
        unsure = {**FISH, "notes": "single-sided verified; printing unconfirmed"}
        self.save(action="add", row=known)
        self.save(action="add", row=unsure, separate=True)
        fish = [r for r in self.view()["rows"] if r["front"] == "Fish"]
        self.assertEqual([r["unconfirmed"] for r in fish], [False, True])
        # A third, known copy: the unsure row doesn't make it allowed, and the
        # 409 names the known row it would duplicate.
        e = self.error(action="add", row=FISH)
        self.assertEqual(e.extra["same_row"]["separate_allowed"], False)
        self.assertEqual(e.extra["same_row"]["row"]["notes"], known["notes"])
        e = self.error(action="add", row=FISH, separate=True)
        self.assertEqual((e.status, e.message), (409, "Those are the same card; change its quantity instead."))
        # An edit that makes the unsure row known, keeping its card, is asked about too.
        unsure_row = next(r for r in self.view()["rows"] if r["unconfirmed"] and r["front"] == "Fish")
        e = self.error(action="edit", base=base(unsure_row), row={"notes": "single-sided verified"})
        self.assertEqual((e.status, e.extra["same_row"]["separate_allowed"]), (409, False))
        e = self.error(action="edit", base=base(unsure_row), row={"notes": "single-sided verified"}, separate=True)
        self.assertEqual(e.message, "Those are the same card; change its quantity instead.")
        # An edit that keeps it unsure isn't.
        self.save(action="edit", base=base(unsure_row), row={"quantity": 5})
        self.assertEqual(sorted(r["quantity"] for r in self.view()["rows"] if r["front"] == "Fish"), [2, 5])

    def test_a_quantity_written_with_a_leading_zero_can_be_edited_and_removed(self):
        lines = ROWS.splitlines(keepends=True)
        lines[3] = lines[3].replace(",8,", ",08,")
        self.write("tokens.csv", "".join(lines))
        zombie = self.row("Zombie")
        self.assertEqual(zombie["quantity"], 8)
        self.save(action="edit", base=base(zombie), row={"quantity": 7})
        self.assertIn(f"Zombie,Zombie Knight,,,,,7,,,{NOTE}", self.csv_text())
        self.write("tokens.csv", "".join(lines))
        self.save(action="remove", base=base(self.row("Zombie")))
        self.assertNotIn("Zombie", self.csv_text())

    def test_a_save_whose_view_fails_afterwards_is_still_saved(self):
        for failure in (ApiError(409, "The tokens list can't be read: please retry"), RuntimeError("boom")):
            with self.subTest(failure=type(failure).__name__):
                sha256 = self.view()["sha256"]
                quantity = self.row("Insect")["quantity"] + 1
                insect = base(self.row("Insect"))
                with mock.patch.object(api_tok, "_tokens_view", side_effect=failure):
                    answer = self.call(api_tok.save_token, sha256=sha256, action="edit", base=insect,
                                       row={"quantity": quantity})
                self.assertEqual((answer["saved"], answer["data"]), (True, None))
                self.assertTrue(answer["warnings"][-1].startswith(api_tok.VIEW_FAILED), answer["warnings"])
                self.assertEqual(self.row("Insect")["quantity"], quantity)

    def test_the_save_runs_under_the_save_lock(self):
        # So it queues behind another page's save in this server rather than answering BUSY.
        held, real = [], self.inventory.apply

        def apply(*args, **kwargs):
            held.append(api_tok.saving._save_lock.locked())
            return real(*args, **kwargs)
        with mock.patch.object(self.inventory, "apply", side_effect=apply):
            self.save(action="add", row=RABBIT)
        self.assertEqual(held, [True])
        self.assertFalse(api_tok.saving._save_lock.locked())

    def test_the_answer_is_the_snapshot_after_the_save(self):
        # As the server runs it: one pinned snapshot per request, which the apply re-pins.
        with inventory.pinned():
            sha256 = self.view()["sha256"]
            answer = self.call(api_tok.save_token, sha256=sha256, action="add", row=RABBIT)
            pinned = inventory.current()
        self.assertIn("Rabbit", [r["front"] for r in answer["data"]["rows"]])
        self.assertEqual(answer["data"]["sha256"], sha(self.path.read_bytes()))
        self.assertEqual(pinned.revision, self.inventory.load().revision)

    def test_an_unsorted_file_is_sorted_by_the_next_save_and_said_so(self):
        lines = ROWS.splitlines(keepends=True)
        self.write("tokens.csv", "".join([lines[0], lines[3], lines[1], lines[2]]))
        self.assertFalse(self.view()["sorted"])
        answer = self.save(action="edit", base=base(self.row("Insect")), row={"quantity": 2})
        self.assertTrue(any("sorted it" in w for w in answer["warnings"]))
        self.assertEqual(self.csv_text().splitlines()[1:],
                         [f"Angel,The Monarch,,,,,1,,,{NOTE}", f"Insect,Goblin,,,,,2,1/1; flying; no deathtouch,,{NOTE}",
                          f"Zombie,Zombie Knight,,,,,8,,,{NOTE}"])
        self.assertTrue(answer["data"]["sorted"])

    def test_a_save_changes_the_inventory_revision(self):
        # So a receipt previewed before it has to be previewed again.
        before = self.inventory.revision()
        self.save(action="add", row=RABBIT)
        added = self.inventory.revision()
        self.assertNotEqual(added, before)
        self.save(action="edit", base=base(self.row("Rabbit")), row={"quantity": 3})
        self.assertNotEqual(self.inventory.revision(), added)

    def test_an_unchanged_save_writes_nothing(self):
        zombie = self.row("Zombie")
        before = self.path.read_bytes()
        self.save(action="edit", base=base(zombie), row=base(zombie))
        self.assertEqual(self.path.read_bytes(), before)


class ConflictTests(TokensApiTestCase):

    def test_a_changed_list_is_409_with_the_latest_view(self):
        old = self.view()["sha256"]
        insect = self.row("Insect")
        self.save(action="edit", base=base(insect), row={"quantity": 2})
        e = self.error(sha256=old, action="edit", base=base(insect), row={"quantity": 3})
        self.assertEqual(e.status, 409)
        conflict = e.extra["conflict"]
        # The files backend keeps no history, so who changed it isn't said (the database's audit
        # trail says, test_token_ops).
        self.assertEqual((conflict["reason"], conflict["by"], conflict["deck_lab"]), ("changed", None, False))
        self.assertNotIn("committed", conflict)
        self.assertIn("The tokens list changed after you opened it: someone changed it", e.message)
        self.assertEqual(e.extra["latest"]["rows"][1]["quantity"], 2)
        # The row itself was changed: the page is told which row it is now.
        self.assertEqual(conflict["base_state"], "changed")
        self.assertEqual(conflict["current"], {"index": 1, "row": {**base(insect), "quantity": 2}})

    def test_a_conflict_says_where_the_row_is_now(self):
        old = self.view()["sha256"]
        insect, angel, zombie = base(self.row("Insect")), base(self.row("Angel")), base(self.row("Zombie"))
        self.save(action="edit", base=insect, row={"front_details": "1/1; flying", "notes": "printing unknown"})
        self.save(action="remove", base=zombie)
        for row, state, reason, index in ((angel, "unchanged", "changed", 0),        # another row changed
                                          (insect, "changed", "changed", 1),         # details and notes changed
                                          (zombie, "deleted", "deleted", None)):
            with self.subTest(state=state):
                e = self.error(sha256=old, action="edit", base=row, row={"quantity": 3})
                conflict = e.extra["conflict"]
                self.assertEqual((e.status, conflict["base_state"], conflict["reason"]), (409, state, reason))
                self.assertEqual(None if conflict["current"] is None else conflict["current"]["index"], index)
                self.assertIn("The tokens list changed after you opened it", e.message)

    def test_a_row_removed_meanwhile_is_reason_deleted(self):
        insect = self.row("Insect")
        self.save(action="remove", base=base(insect))
        e = self.error(action="edit", base=base(insect), row={"quantity": 3})
        self.assertEqual((e.status, e.extra["conflict"]["reason"]), (409, "deleted"))
        self.assertEqual((e.extra["conflict"]["base_state"], e.extra["conflict"]["current"]), ("deleted", None))
        self.assertEqual(len(e.extra["latest"]["rows"]), 2)
        # The sha matched, so the message doesn't claim the file changed.
        self.assertEqual(e.message, api_tok.NOT_LISTED)

    def test_a_base_that_was_never_listed_isnt_called_a_change(self):
        zombie = base(self.row("Zombie"))
        e = self.error(action="edit", base={**zombie, "quantity": "5"}, row={"quantity": 3})
        conflict = e.extra["conflict"]
        self.assertEqual((e.status, e.message), (409, api_tok.NOT_AS_SENT))
        self.assertEqual((conflict["reason"], conflict["base_state"], conflict["current"]["index"]),
                         ("changed", "changed", 2))

    def test_a_row_that_cant_be_read_strictly_is_409(self):
        self.write("tokens.csv", ROWS + "Bad,,,,,,0,,,\n")
        e = self.error(action="add", row=FISH)
        self.assertEqual(e.status, 409)
        self.assertTrue(e.message.startswith("magic/tokens.csv line 5: "), e.message)
        self.assertTrue(e.message.endswith("; it can't be changed until that's put right"))

    def test_requests_are_checked(self):
        before = self.magic_files()
        zombie = base(self.row("Zombie"))
        for data in ({"action": "rename", "row": RABBIT},
                     {"action": "add", "row": RABBIT, "sha256": "x"},
                     {"action": "add"},
                     {"action": "add", "row": {**RABBIT, "colour": "white"}},
                     {"action": "add", "row": {**RABBIT, "quantity": True}},
                     {"action": "add", "row": {**RABBIT, "quantity": 0}},
                     {"action": "add", "row": {**RABBIT, "quantity": 10000}},
                     {"action": "add", "row": {**RABBIT, "front": 3}},
                     {"action": "add", "row": {**RABBIT, "front": ""}},
                     {"action": "add", "row": {**RABBIT, "set": "BAD SET"}},
                     {"action": "add", "row": {**RABBIT, "finish": "shiny"}},
                     {"action": "add", "row": RABBIT, "separate": "yes"},
                     {"action": "add", "row": RABBIT, "reason": "no"},
                     {"action": "add", "row": RABBIT, "base": zombie},
                     {"action": "edit", "row": RABBIT},
                     {"action": "edit", "base": {"front": "Zombie"}, "row": RABBIT},
                     {"action": "edit", "base": [], "row": RABBIT},
                     {"action": "remove", "base": zombie, "reason": "x" * 201},
                     {"action": "remove", "base": zombie, "row": RABBIT}):
            with self.subTest(data=data):
                self.assertEqual(self.error(**data).status, 400)
        self.assertEqual(self.magic_files(), before)


class WithIndexTests(TokensApiTestCase):
    """The card index built from fixtures/tokens_cards.jsonl."""

    loaded = None

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def index(self):
        return self.loaded

    def test_the_view_has_names_pictures_uses_and_missing_tokens(self):
        self.save(action="add", row=FISH)
        view = self.view()
        self.assertTrue(view["index_ready"])
        self.assertIn("The Ring // The Ring Tempts You", view["face_names"])
        fish = self.row("Fish")
        self.assertEqual(fish["faces"], [{"side": "front", "name": "Fish", "details": "1/1; blue", "known": True,
                                          "image": "/img/tblb/7/small", "example": None}])   # its own printing
        zombie = self.row("Zombie")
        self.assertEqual([f["known"] for f in zombie["faces"]], [True, False])     # no Zombie Knight in the fixture
        # A row with no printing: an example picture of a token with that face name, never its "image" (which is
        # only ever the row's own printing); none for a name Scryfall's tokens don't have.
        self.assertIsNone(zombie["faces"][0]["image"])
        self.assertTrue(zombie["faces"][0]["example"].startswith("/img/"))
        self.assertIsNone(zombie["faces"][1]["example"])
        insect = self.row("Insect")
        self.assertEqual(insect["uses"], [{"deck": "casual/queen", "title": "Queen Deck", "link": "casual/queen", "token": "Insect",
                                           "side": "front", "state": "differs"}])
        self.write("decks/casual/queen.md", deck_md("Queen Deck", deck="1 Hornet Queen\n1 Gisa, the Hellraiser\n"))
        missing = self.view()["missing"]
        self.assertEqual([(m["name"], m["state"], m["decks"]) for m in missing],
                         [("Zombie Rogue", "none", [{"id": "casual/queen", "title": "Queen Deck", "link": "casual/queen"}])])
        self.assertTrue(missing[0]["image"].startswith("/img/"))
        self.assertNotIn(tokens.NAMES_UNCHECKED, view["info"])

    def test_a_row_too_few_built_decks_can_share_is_named(self):
        self.assertEqual(self.row("Insect")["shared"], [])                 # Queen Deck is only being built
        self.write("decks/casual/queen.md", deck_md("Queen Deck", status="built"))
        self.assertEqual(self.row("Insect")["shared"], [])                 # one card, one built deck
        self.write("decks/casual/hive.md", deck_md("Hive Deck", status="built"))
        self.assertEqual(self.row("Insect")["shared"],
                         [{"deck": "casual/hive", "title": "Hive Deck", "link": "casual/hive", "quantity": 1},
                          {"deck": "casual/queen", "title": "Queen Deck", "link": "casual/queen", "quantity": 1}])
        notes, warnings = [], []
        tokens.check(notes=notes, warnings=warnings)
        self.assertIn("Only 1 card, used by 2 built decks: Hive Deck and Queen Deck",
                      "\n".join(warnings))
        # The deck page names the other built decks beside a card to grab from that row.
        from decklab.lib.api import deck_page
        inv = tokens.read()
        insect = next(i for i, r in enumerate(inv.rows) if r["front"] == "Insect")
        result = {"needs": [{"name": "Insect", "cards": [{"row": insect}]}]}
        shown = deck_page._with_shared(result, {"id": "casual/queen", "space": "home"}, inv, [])
        self.assertEqual(shown["needs"][0]["cards"][0]["shared"],
                         [{"deck": "casual/hive", "title": "Hive Deck", "link": "casual/hive", "quantity": 1}])
        self.assertNotIn("shared", result["needs"][0]["cards"][0])         # the cached result is left alone

    def test_names_are_checked_and_fixed(self):
        answer = self.save(action="add", row={**RABBIT, "front": "rabbit"})
        self.assertEqual(answer["warnings"], [])
        self.assertIn(f"Rabbit,Rabbit,,,,,2,,,{NOTE}", self.csv_text())
        e = self.error(action="add", row={**RABBIT, "front": "Rabbitt"})
        self.assertEqual(e.status, 400)
        self.assertIn("'Rabbitt' isn't a token, emblem or reminder name on Scryfall. Did you mean Rabbit?", e.message)
        e = self.error(action="add", row={**FISH, "front": "Angel"})
        self.assertEqual((e.status, e.message), (400, "The token card can't be saved: tblb 7 is Fish, not Angel"))

    def test_deck_trouble_is_info_not_an_error(self):
        with mock.patch.object(tokens, "row_uses", side_effect=KeyError("boom")):
            view = self.view()
        self.assertTrue(any("token uses couldn't be worked out" in i for i in view["info"]))
        self.assertTrue(any("boom" in line for line in self.logs))
        self.assertEqual(len(view["rows"]), 3)

    # Example art for a face name (lib/api/tokens.py _example_image).
    def test_the_example_matches_the_details_power_and_toughness_when_it_can(self):
        from decklab.lib.api import tokens as tokens_api
        found = tokens_api._example_entries()
        name, entries = next(((k, v) for k, v in found.items() if len(v) > 1
                              and len({(e.get("power"), e.get("toughness")) for e in v}) > 1), (None, None))
        if name is None:
            self.skipTest("the fixture has no token name with two sizes")
        second = entries[1]
        details = f"{second['power']}/{second['toughness']}; green"
        url = tokens_api._example_image(second["name"], details)
        self.assertEqual(url, tokens_api.image_url(*second["image"], "small"))
        self.assertIsNone(tokens_api._example_image("No Such Token Name", ""))

    def test_the_deck_page_gives_needs_without_a_picture_example_art(self):
        # deck_page._with_examples: a copy with "example" on the needs that have no picture of their own.
        from decklab.lib.api import deck_page, tokens as tokens_api
        result = {"needs": [{"name": "Zombie", "pt": "2/2", "image": "/img/tm/1/small"},
                            {"name": "Ooze", "pt": "3/3", "image": None}], "counts": {}}
        with mock.patch.object(tokens_api, "_example_image", return_value="/img/tx/9/small") as example:
            out = deck_page._with_examples(result)
        example.assert_called_once_with("Ooze", "3/3")
        self.assertNotIn("example", out["needs"][0])
        self.assertEqual(out["needs"][1]["example"], "/img/tx/9/small")
        self.assertNotIn("example", result["needs"][1])             # the cached answer is left alone
        every = {"needs": [result["needs"][0]]}
        self.assertIs(deck_page._with_examples(every), every)
        self.assertEqual(deck_page._with_examples({"error": "x"}), {"error": "x"})


if __name__ == "__main__":
    unittest.main()
