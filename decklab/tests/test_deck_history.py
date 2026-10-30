"""The deck history (the phase 4 design's D5 and R5): the History API on the backends' deck
revisions (int revisions, old git-sha links, first lines only, local dates, kit privacy, the files
backend's empty history), and a history of earlier revisions put into a throwaway database with
pg.write_decks / write_model and read back (they skip without one: db_support.py). Phase 5b
retired the import of the decks' git history and its gate (db/deck_history.py), which these tests
also covered.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_deck_history
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import api, config, inventory
from decklab.lib.api import history
from decklab.lib.inventory import files, rules
from decklab.lib.inventory.model import DeckRevision
from decklab.lib.state import Actor
from decklab.tests import db_support
from decklab.tests.test_api import ApiTestCase, GRUUL

WHEN = datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc)      # 2026-10-06 08:30 at home (UTC+10)
SHA_A, SHA_B = "a" * 40, "b" * 40
MATT_ACTOR = Actor("claude", "migration")
ACCESSORIES = "id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n" \
              "dragon-shield-matte-black,sleeves,matt,Dragon Shield,Matte,black,100,,,,,,\n"


class WithHistory:
    """A backend that is another one (the sandbox's FileInventory) with deck revisions added:
    {deck_id: [DeckRevision with its text], oldest first}, as the database backend gives them."""

    def __init__(self, inner, revisions):
        self.inner, self.revisions = inner, revisions

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def deck_revisions(self, deck_id):
        return [dataclasses.replace(r, text=None) for r in reversed(self.revisions.get(deck_id, []))]

    def deck_revision(self, deck_id, number):
        return next((r for r in self.revisions.get(deck_id, []) if r.revision == int(number)), None)

    def last_revision(self, deck_id):
        found = self.deck_revisions(deck_id)
        return found[0] if found else None


def install(box, revisions):
    """Install WithHistory over the sandbox's inventory until the test ends; returns it."""
    backend = WithHistory(box.inventory, revisions)
    box.stack.callback(inventory.use(backend))
    return backend


def revision(deck_id, n, text, *, actor="matt", message="Edit", op="M", kit=False, commit=None, at=WHEN):
    return DeckRevision(deck_id, n, at, actor, message, op, kit=kit, git_commit=commit, text=text)


class HistoryApiTests(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.deck_id = "casual/gruul-test"
        self.path = self.box.magic / "decks/casual/gruul-test.md"
        self.old = GRUUL
        self.new = GRUUL.replace("4 Llanowar Elves (FDN) 227", "3 Llanowar Elves (FDN) 227")
        self.path.write_text(self.new, encoding="utf-8", newline="\n")
        install(self.box, {self.deck_id: [
            revision(self.deck_id, 1, self.old, op="A", message="Add Gruul\n\nCo-Authored-By: Claude <x>",
                     actor="claude", commit=SHA_A),
            revision(self.deck_id, 2, self.new, message="Deck Lab: save Gruul Test (edited by User1)",
                     actor="user1", at=WHEN + timedelta(days=1))]})

    def test_the_list_newest_first_with_numbers_local_dates_and_first_lines(self):
        data = history.deck_history(self.deck_id)
        self.assertEqual(data["sha256"], api.edit_view(self.deck_id)["sha256"])
        self.assertFalse(data["truncated"])
        first, second = data["revisions"]
        self.assertEqual((first["revision"], first["op"], first["actor"], first["commit"]), (2, "M", "user1", None))
        self.assertEqual((second["revision"], second["op"], second["commit"]), (1, "A", "aaaaaaa"))
        self.assertEqual(second["subject"], "Add Gruul")              # never the body or its trailers
        self.assertEqual(second["author"], "Claude")
        self.assertEqual(datetime.fromisoformat(second["date"]), WHEN)
        self.assertEqual(second["date"], WHEN.astimezone().isoformat(timespec="seconds"))    # this PC's offset

    def test_a_revision_by_number_or_git_commit_compares_without_writing(self):
        before = self.path.read_bytes()
        for named in (1, "1", SHA_A):
            value = history.deck_revision(self.deck_id, named, "target")
            self.assertEqual(value["revision"], 1)
            self.assertEqual(value["sections"]["Deck"][0]["qty"], 4)
            self.assertEqual(value["current"]["lists"]["target"]["Deck"][0]["qty"], 3)
            self.assertEqual(value["current"]["sha256"], api.edit_view(self.deck_id)["sha256"])
            self.assertEqual(value["history"]["subject"], "Add Gruul")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(len(history.deck_revision(self.deck_id, "1", "owned")["sections"]["Deck"]), 1)

    def test_bad_revisions_and_decks(self):
        for bad, status in (("HEAD", 400), ("--all", 400), ("../magic", 400), ("0", 400), ("-1", 400), (0, 400),
                            (True, 400), ("abc", 400), ("1.5", 400), ("0" * 40, 404), (SHA_B, 404), ("3", 404)):
            self.assertApiError(status, history.deck_revision, self.deck_id, bad)
        self.assertApiError(400, history.deck_revision, self.deck_id, "1", "both")
        self.assertApiError(400, history.deck_history, "casual/../gruul-test")
        error = self.assertApiError(400, history.deck_history, "product/fdc-test-precon",
                                    contains="product/fdc-test-precon has no history")
        self.assertIn("a deck saved in Deck Lab", error.message)
        self.assertNotIn("of your own", error.message)  # a partner's or another space's deck has one too
        self.assertApiError(404, history.deck_history, "casual/no-such-deck")

    def test_a_deletion_has_no_list(self):
        backend = inventory.backend()
        backend.revisions[self.deck_id] += [
            revision(self.deck_id, 3, None, op="D", message="Delete"),
            revision(self.deck_id, 4, self.new, op="A", message="Made again")]
        self.assertEqual([r["op"] for r in history.deck_history(self.deck_id)["revisions"]], ["A", "D", "M", "A"])
        self.assertApiError(404, history.deck_revision, self.deck_id, "3")
        self.assertEqual(history.deck_revision(self.deck_id, "4")["revision"], 4)

    def test_a_kit_revision_s_message_is_its_actor_s_alone(self):
        from decklab.lib import access
        backend = inventory.backend()
        backend.revisions[self.deck_id].append(revision(self.deck_id, 3, self.new + "\n", kit=True, actor="user1",
                                                        message="Sleeve it in user1-red"))
        seen = {}
        for who in ("matt", "user1", None):
            identity = None if who is None else {"profile": who, "email": "", "remote": True}
            with access.using(identity):
                seen[who] = history.deck_history(self.deck_id)["revisions"][0]["subject"]
        self.assertEqual(seen, {"matt": None, "user1": "Sleeve it in user1-red", None: "Sleeve it in user1-red"})

    def test_an_unknown_actor_is_someone_unless_the_viewer_sees_everything(self):
        from decklab.lib import access
        backend = inventory.backend()
        backend.revisions[self.deck_id].append(revision(self.deck_id, 3, self.new, actor="zed", message="Tidy"))
        seen = {}
        for who in ("matt", None):
            identity = None if who is None else {"profile": who, "email": "", "remote": True}
            with access.using(identity):
                top = history.deck_history(self.deck_id)["revisions"][0]
                seen[who] = (top["actor"], top["author"])
        self.assertEqual(seen, {"matt": (None, "someone"), None: ("zed", "zed")})

    def test_the_truncated_list(self):
        backend = inventory.backend()
        backend.revisions[self.deck_id] = [revision(self.deck_id, n, self.new) for n in range(1, 103)]
        data = history.deck_history(self.deck_id)
        self.assertTrue(data["truncated"])
        self.assertEqual([r["revision"] for r in data["revisions"][:2]], [102, 101])
        self.assertEqual(len(data["revisions"]), history.MAX_REVISIONS)


class RevisionChangeTests(ApiTestCase):
    """Each revision's change against the revision before it (not against the current list): the cards each
    list gained and lost, the header fields, folded saves, deletions, and the Sleeves and Deck box only for
    those who see the deck's accessories."""

    def setUp(self):
        super().setUp()
        self.deck_id = "casual/gruul-test"
        self.path = self.box.magic / "decks/casual/gruul-test.md"
        self.texts = [GRUUL,
                      GRUUL.replace("4 Llanowar Elves (FDN) 227\n2 Elvish Mystic", "3 Llanowar Elves (FDN) 227\n"
                                    "2 Elvish Mystic\n2 Shock (M19) 156", 1),
                      None]
        self.texts[2] = self.texts[1].replace("- **Status:** building", "- **Status:** built")
        self.texts.append(self.texts[2] + "\n## Notes\n\nPlay it fast.\n")
        self.path.write_text(self.texts[-1], encoding="utf-8", newline="\n")
        install(self.box, {self.deck_id: [revision(self.deck_id, n + 1, text, op="A" if n == 0 else "M",
                                                   at=WHEN + timedelta(hours=n))
                                          for n, text in enumerate(self.texts)]})

    def changes(self):
        with mock.patch.object(history, "_cards_ready", return_value=False):
            return [r["change"] for r in history.deck_history(self.deck_id)["revisions"]]

    def test_each_revision_against_the_one_before(self):
        prose, status, cards, first = self.changes()
        self.assertEqual(prose["kind"], "none")                    # only the write-up: folded on the page
        self.assertEqual((status["kind"], status["fields"]),
                         ("details", [{"key": "Status", "before": "building", "after": "built"}]))
        self.assertEqual(cards["kind"], "cards")
        self.assertEqual(cards["lists"], ["target"])               # the owned-only list's line wasn't touched
        self.assertEqual([(c["list"], c["section"], c["name"], c["delta"], c["printing"]) for c in cards["cards"]],
                         [("target", "Deck", "Shock", 2, False), ("target", "Deck", "Llanowar Elves", -1, False)])
        self.assertEqual(cards["fields"], [])
        self.assertEqual((first["kind"], first["restored"], first["size"]), ("created", False, {"target": 25, "owned": 4}))
        # Against the revision before, never the list today: the first change says -1 even though later
        # revisions changed more.
        self.assertEqual(cards["size"], {"target": 26, "owned": 4})

    def test_a_printing_change_card_data_and_the_cap(self):
        backend = inventory.backend()
        moved = self.texts[-1].replace("1 Opt (FDN) 512", "1 Opt (M19) 65")
        backend.revisions[self.deck_id].append(revision(self.deck_id, 5, moved, at=WHEN + timedelta(days=1)))
        picture = {"name": "Opt", "img_small": "/img/m19/65/small"}
        with mock.patch.object(history, "_cards_ready", return_value=True), \
                mock.patch.object(history, "_lines_json", return_value={"Deck": [{"card": picture}]}):
            change = history.deck_history(self.deck_id)["revisions"][0]["change"]
        self.assertEqual([(c["name"], c["delta"], c["printing"], c["card"]) for c in change["cards"]],
                         [("Opt", 0, True, picture)])
        with mock.patch.object(history, "MAX_CHANGES", 1):
            cards = self.changes()[3]
        self.assertEqual((len(cards["cards"]), cards["more"]), (1, 1))

    def test_deleted_and_made_again(self):
        backend = inventory.backend()
        backend.revisions[self.deck_id] += [revision(self.deck_id, 5, None, op="D", at=WHEN + timedelta(days=1)),
                                            revision(self.deck_id, 6, GRUUL, op="A", at=WHEN + timedelta(days=2))]
        again, deleted = self.changes()[:2]
        self.assertEqual((again["kind"], again["restored"]), ("created", True))
        self.assertEqual(deleted["kind"], "deleted")

    def test_an_unreadable_revision(self):
        backend = inventory.backend()
        backend.revisions[self.deck_id].append(revision(self.deck_id, 5, "not a deck", at=WHEN + timedelta(days=1)))
        self.assertEqual(self.changes()[0]["kind"], "unreadable")

    def test_every_text_is_read_at_once(self):
        backend = inventory.backend()
        reads = []

        def at_once(deck_id, limit):
            reads.append(limit)
            return list(reversed(backend.revisions[deck_id]))[:limit]
        backend.deck_revisions_with_text = at_once
        backend.deck_revision = mock.Mock(side_effect=AssertionError("one revision at a time"))
        self.assertEqual(len(self.changes()), 4)
        self.assertEqual(reads, [history.MAX_REVISIONS + 1])

    def test_an_unreadable_revision_is_passed_over(self):
        backend = inventory.backend()
        backend.revisions[self.deck_id] = [revision(self.deck_id, 1, GRUUL, op="A"),
                                           revision(self.deck_id, 2, "not a deck", at=WHEN + timedelta(hours=1)),
                                           revision(self.deck_id, 3, self.texts[1], at=WHEN + timedelta(hours=2))]
        cards, broken, first = self.changes()
        self.assertEqual((cards["kind"], cards["skipped"]), ("cards", 1))          # against revision 1
        self.assertEqual([(c["name"], c["delta"]) for c in cards["cards"]], [("Shock", 2), ("Llanowar Elves", -1)])
        self.assertEqual(broken["kind"], "unreadable")
        self.assertEqual(first["kind"], "created")
        # Nothing earlier can be read: the readable revision isn't called unreadable.
        backend.revisions[self.deck_id] = [revision(self.deck_id, 1, "not a deck", op="A"),
                                           revision(self.deck_id, 2, GRUUL, at=WHEN + timedelta(hours=1))]
        readable, broken = self.changes()
        self.assertEqual((readable["kind"], readable["size"]["target"]), ("unreadable_before", 25))
        self.assertEqual(broken["kind"], "unreadable")

    def test_more_is_counted_per_list(self):
        backend = inventory.backend()
        both = self.texts[-1].replace("1 Opt (FDN) 512", "2 Opt (FDN) 512")
        backend.revisions[self.deck_id].append(revision(self.deck_id, 5, both, at=WHEN + timedelta(days=1)))
        with mock.patch.object(history, "MAX_CHANGES", 0):
            change = self.changes()[0]
        self.assertEqual(change["cards"], [])
        self.assertEqual(sum(change["more_by_list"].values()), change["more"])
        self.assertEqual(set(change["more_by_list"]), set(change["lists"]))

    def test_sleeves_and_deck_box_only_for_those_who_see_them(self):
        from decklab.lib import access
        mine = [t.replace("- **Played by:** either", "- **Played by:** user") for t in self.texts]
        sleeved = mine[-1].replace("- **Status:** built", "- **Status:** built\n- **Sleeves:** dragon-shield-matte-black")
        backend = inventory.backend()
        backend.revisions[self.deck_id] = [revision(self.deck_id, 1, mine[-1], op="A"),
                                           revision(self.deck_id, 2, sleeved, at=WHEN + timedelta(hours=1))]
        seen = {}
        for who in ("matt", "user1"):
            with access.using({"profile": who, "email": "", "remote": True}):
                seen[who] = self.changes()[0]
        self.assertEqual(seen["matt"]["fields"], [{"key": "Sleeves", "before": None, "after": "dragon-shield-matte-black"}])
        self.assertEqual((seen["user1"]["kind"], seen["user1"]["fields"]), ("none", []))
        self.assertNotIn("dragon-shield", json.dumps(seen["user1"]))


class FilesBackendTests(ApiTestCase):

    def test_the_files_backend_keeps_no_history(self):
        data = history.deck_history("casual/gruul-test")
        self.assertEqual(data["revisions"], [])
        self.assertEqual(data["title"], "Gruul Test")
        self.assertApiError(404, history.deck_revision, "casual/gruul-test", "1")
        self.assertApiError(404, history.deck_revision, "casual/gruul-test", SHA_A)


# ------------------------------------------------------------------ a history in the database

def _deck(title, cards="4 Opt (DOM) 60\n", extra=""):
    return (f"# {title}\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n- **Status:** idea\n{extra}\n"
            f"## Decklist\n\n```\nDeck\n{cards}```\n")


SHAS = {"add": "1" * 40, "save": "2" * 40, "delete": "3" * 40, "person": "4" * 40}
HOME_TZ = timezone(timedelta(hours=10))
ALPHA = "magic/decks/casual/alpha.md"
EXAMPLE_DRAGONS = "magic/people/user2/decks/commander/example-dragons.md"


def small_history():
    """The revisions of three decks, oldest first, as write_decks(history=) takes them: two decks
    added by Claude, a save by User1, a deletion and a person's deck."""
    def item(deck_id, sha, op, text, actor, message, day, minute):
        return {"deck_id": deck_id, "at": datetime(2026, 10, day, 9, minute, tzinfo=HOME_TZ), "actor": actor,
                "message": message, "op": op, "git_commit": SHAS[sha], "text": text, "kit": False}
    add = "Add two decks\n\nLong body.\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>\n"
    return [item("casual/alpha", "add", "A", _deck("Alpha"), "claude", add, 1, 11),
            item("commander/gone", "add", "A", _deck("Gone"), "claude", add, 1, 11),
            item("casual/alpha", "save", "M", _deck("Alpha", "3 Opt (DOM) 60\n"), "user1",
                 "Deck Lab: save Alpha (edited by User1)\n", 2, 12),
            item("commander/gone", "delete", "D", None, "matt", "Retire Gone\n", 6, 21),
            item("user2/commander/example-dragons", "person", "A", _deck("Example Dragons"), "user2",
                 "Deck Lab: new deck Example Dragons (by User2)\n", 7, 14)]


def _snapshot(lists=False):
    """(the deck parts' Inventory small_history() ends with, {picture name: bytes}); lists: with an
    empty status list and watchlist too (an inventory the database can hold)."""
    parts = {ALPHA: _deck("Alpha", "3 Opt (DOM) 60\n").encode(), EXAMPLE_DRAGONS: _deck("Example Dragons").encode()}
    if lists:
        parts["magic/products/status.csv"] = rules.csv_bytes([], rules.STATUS_FIELDS)
        parts["magic/watchlist.csv"] = (b"name,set,collector_number,finish,quantity,for,printing,listed_aud,"
                                        b"listed_at,in_stock,checked,notes,state,source\n")
    return files.build(parts), {}


class _Db(db_support.DbTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        self.pg = pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)

    def import_history(self, model=False):
        """Put small_history() into the database with its decks (write_decks; model: write_model
        with an empty inventory, both at once); returns the history."""
        inv, images = _snapshot(model)
        items = small_history()
        if model:
            self.pg.write_model(inv, MATT_ACTOR, "Import", dbname=self.dbname, decks=True, images=images,
                                history=items)
        else:
            self.pg.write_decks(inv, MATT_ACTOR, "Import the decks", images=images, history=items,
                                dbname=self.dbname)
        return items


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class HistoryDbTests(_Db):

    def test_the_revisions_are_numbered_per_deck(self):
        self.import_history()
        with self.connect() as c:
            rows = c.execute("select deck_id, revision, change_set_id, op, actor, git_commit, kit from deck_revision "
                             "order by deck_id, revision").fetchall()
            current = dict(c.execute("select id, revision from deck").fetchall())
        self.assertEqual(rows, [
            ("casual/alpha", 1, None, "A", "claude", SHAS["add"], False),
            ("casual/alpha", 2, None, "M", "user1", SHAS["save"], False),
            ("commander/gone", 1, None, "A", "claude", SHAS["add"], False),
            ("commander/gone", 2, None, "D", "matt", SHAS["delete"], False),
            ("user2/commander/example-dragons", 1, None, "A", "user2", SHAS["person"], False)])
        self.assertEqual(current, {"casual/alpha": 2, "user2/commander/example-dragons": 1})

    def test_write_model_refuses_a_history_with_replace_or_without_the_decks_up_front(self):
        inv, images = _snapshot(lists=True)
        items = small_history()
        with self.connect() as c:
            before = c.execute("select count(*) from audit.change_set").fetchone()[0]
        for kwargs, words in (({"decks": True, "replace": True}, "not with replace"),
                              ({}, "only with the decks")):
            with self.assertRaisesRegex(ValueError, words):
                self.pg.write_model(inv, MATT_ACTOR, "Import", dbname=self.dbname, images=images, history=items,
                                    **kwargs)
        with self.assertRaisesRegex(ValueError, "not with replace"):
            self.pg.write_decks(inv, MATT_ACTOR, "Import", images=images, history=items, replace=True,
                                dbname=self.dbname)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], before)

    def test_a_text_that_isn_t_the_last_revision_is_refused(self):
        inv, images = _snapshot()
        items = small_history()[:2]                 # only the first commit's
        with self.assertRaisesRegex(ValueError, "isn't its last revision's"):
            self.pg.write_decks(inv, MATT_ACTOR, "Import", images=images, history=items, dbname=self.dbname)

    def test_the_history_api_on_the_database(self):
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        # The fixture profiles' config.json (so user2's space exists whatever this checkout's lists).
        temp = Path(tempfile.mkdtemp(prefix="decklab-history-"))
        self.addCleanup(shutil.rmtree, temp, True)
        (temp / "config.json").write_text(json.dumps({"profiles": FIXTURE_PROFILES}), encoding="utf-8")
        for patch in (mock.patch.object(config, "CONFIG_FILE", temp / "config.json"),
                      mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patch.start()
            self.addCleanup(patch.stop)
        self.import_history(model=True)
        backend = self.pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        with inventory.use(backend), inventory.pinned():
            data = history.deck_history("casual/alpha")
            self.assertEqual([(r["revision"], r["op"], r["actor"], r["commit"]) for r in data["revisions"]],
                             [(2, "M", "user1", SHAS["save"][:7]), (1, "A", "claude", SHAS["add"][:7])])
            self.assertEqual(data["revisions"][1]["subject"], "Add two decks")
            self.assertEqual(datetime.fromisoformat(data["revisions"][1]["date"]),
                             datetime(2026, 10, 1, 9, 11, tzinfo=HOME_TZ))
            self.assertEqual(history._number("casual/alpha", SHAS["add"]), 1)
            # Every text in one query: never a connection per revision.
            with mock.patch.object(backend, "deck_revision", side_effect=AssertionError("one at a time")):
                again = history.deck_history("casual/alpha")
            self.assertEqual(again["revisions"][1]["change"]["kind"], "created")
            self.assertEqual([r.revision for r in backend.deck_revisions_with_text("casual/alpha", 1)], [2])
            self.assertIsNotNone(backend.deck_revisions_with_text("casual/alpha", 1)[0].text)
            self.assertEqual(history.deck_history("user2/commander/example-dragons")["revisions"][0]["actor"], "user2")
            retired = history.deck_history("commander/gone")
            self.assertTrue(retired["retired"])
            self.assertTrue(retired["may_restore"])
            self.assertFalse(retired["may_save"])
            self.assertIsNone(retired["sha256"])
            self.assertEqual(retired["retired_revision"], 2)
            self.assertEqual([row["op"] for row in retired["revisions"]], ["D", "A"])
            self.assertEqual(retired["revisions"][0]["subject"], "Retire Gone")
            self.assertNotIn("Long body.", json.dumps(retired))
            with mock.patch.object(history, "_require_cards"), mock.patch.object(history, "_lines_json", return_value={}):
                saved = history.deck_revision("commander/gone", "1")
            self.assertTrue(saved["retired"])
            self.assertIsNone(saved["current"])

if __name__ == "__main__":
    unittest.main()
