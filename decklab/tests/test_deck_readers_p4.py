"""Phase 4's readers and views (the phase 4 design, area A): the deck pages, library and editor
hide a space's inventory from those who may not see it (R6d), name a deck by its id (R8), and
Forge provenance names a deck's saved revision from one snapshot (D6).

- PrivacyTests: test_api_permissions' sandbox (Matt an admin, User1 a home member, User2 with
  his own space and deck) through deck_view, decks_index and edit_view, with every space's decks
  public (guard.public_deck_spaces patched, as E10-S28's switches will make them) while each
  space's inventory stays its own: R6d is about a deck the viewer sees in a space whose inventory
  it doesn't. Without that patch a deck is seen only in its own space (E10-S30: test_deck_visibility).
- ProvenanceTests: forge.lists._source over a pinned snapshot (the files backend's revision 0,
  a revision the database names, a preview).
- DatabaseReaderTests: the readers, the library, deck page, editor and the variant draft on the
  database backend with no deck files on disk (a throwaway database: db_support.py; they skip
  without one).

Run from the repo root: python -m unittest decklab.tests.test_deck_readers_p4
"""
import dataclasses
import json
import types
import unittest
from unittest import mock

from decklab.lib import access, api, decks, inventory, pool, tokens
from decklab.lib.api import guard, variant_page
from decklab.lib.forge import lists
from decklab.lib.inventory import ops_decks  # noqa: F401 (registers deck.save)
from decklab.tests import db_support
from decklab.tests.test_api import Sandbox
from decklab.tests import test_inventory_pg_decks as pg_decks_tests
from decklab.tests import test_pool as support
from decklab.tests.test_api_permissions import PermissionTestCase

HIDDEN_PAGE = ("owned", "tokens", "table")
HIDDEN_INDEX = ("missing", "on_the_way", "availability_confirmed", "tokens")


def _as(who):
    return access.using({"profile": who, "email": "", "remote": True})


class PrivacyTests(PermissionTestCase):
    """R6d: owned/missing/on-the-way counts, token chips, substitute availability and the table
    only for viewers who see the deck's space's inventory (permissions.sees_inventory), for decks
    made public (the module docstring)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home", "user2"}))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_deck_page_hides_another_space_s_inventory(self):
        cases = {("user2", "casual/gruul-test"): False, ("user2", "user2/casual/r-elves"): True,
                 ("user1", "casual/gruul-test"): True, ("user1", "user2/casual/r-elves"): False,
                 ("matt", "user2/casual/r-elves"): False, ("matt", "casual/gruul-test"): True}   # E10-S29
        for (who, deck_id), sees in cases.items():
            with self.subTest(who=who, deck=deck_id), _as(who):
                view = api.deck_view(deck_id)
                for key in HIDDEN_PAGE:
                    self.assertEqual(key in view, sees, key)
                # The decklist, guide, stats, practice and matchups stay for everyone.
                for key in ("sections", "stats", "guide", "practice", "matchups", "warnings", "info"):
                    self.assertIn(key, view)
                self.assertTrue(view["sections"]["Deck"])

    def test_the_substitute_list_s_availability_is_hidden_too(self):
        with _as("user2"):
            view = api.deck_view("casual/gruul-test", "owned")
        self.assertTrue(view["sections"])
        self.assertFalse(set(HIDDEN_PAGE) & set(view))

    def test_a_hidden_space_s_pool_and_tokens_are_never_read(self):
        real = pool.load_pool
        spaces_read = []

        def load_pool(space="home", *args, **kwargs):
            spaces_read.append(space)
            return real(space, *args, **kwargs)
        with mock.patch.object(pool, "load_pool", side_effect=load_pool), \
                mock.patch("decklab.lib.tokens.for_space", side_effect=AssertionError("tokens read")), _as("user2"):
            api.deck_view("casual/gruul-test")
            api.edit_view("casual/gruul-test")
        self.assertNotIn("home", spaces_read)

    def test_a_draft_check_s_default_printing_doesnt_show_a_hidden_space_s_copies(self):
        def picked(who):
            with _as(who):
                answer = api.check_draft(json.dumps({"profile": who, "id": "casual/gruul-test", "lists": {
                    "target": {"Deck": [{"qty": 1, "name": "Llanowar Elves"}]}}}).encode("utf-8"))
            line = answer["lists"]["target"]["Deck"][0]
            return line["set"], line["number"]
        self.assertEqual(picked("matt"), ("fdn", "227"))        # the printing home owns
        self.assertEqual(picked("user1"), ("fdn", "227"))
        self.assertEqual(picked("user2"), ("m19", "314"))     # the cheapest: home's copies are hidden

    def test_updating_a_table_doesnt_show_home_s_pool_warnings(self):
        real = pool.load_pool
        warning = "magic/orders/2026-10-05-secret.csv can't be read"

        def load_pool(*args, **kwargs):
            p = real(*args, **kwargs)
            p.warnings.append(warning)
            return p
        # Each updates a deck of their own space (E10-S29: Matt, an admin, no longer User2's).
        for who, deck_id, sees in (("user2", "user2/casual/r-elves", False), ("matt", "casual/gruul-test", True)):
            with self.subTest(who=who), mock.patch.object(pool, "load_pool", side_effect=load_pool), _as(who):
                sha = api.edit_view(deck_id)["sha256"]
                answer = api.update_tables(json.dumps({"profile": who, "decks": [
                    {"id": deck_id, "sha256": sha}]}).encode("utf-8"))
                self.assertEqual(warning in json.dumps(answer["warnings"]), sees)

    def test_the_library_never_reads_a_hidden_space_s_tokens(self):
        real = tokens.for_space
        read = []

        def for_space(space, *args, **kwargs):
            read.append(space)
            return real(space, *args, **kwargs)
        with mock.patch.object(tokens, "for_space", side_effect=for_space), _as("user2"):
            index = {d["id"]: d for d in api.decks_index()["decks"]}
        self.assertEqual(set(read), {"user2"})
        self.assertIn("tokens", index["user2/casual/r-elves"])

    def test_the_out_of_date_tables_list_only_the_visitor_s_spaces(self):
        listed = [{"id": deck_id, "title": deck_id, "sha256": "0" * 64, "count": 1,
                   "changes": [{"card": "Opt", "was": None, "now": {"need": 1, "missing": 1, "labels": []}}]}
                  for deck_id in ("casual/gruul-test", "user2/casual/r-elves")]
        root = str(api.config.REPO)
        blockers = {"decks": [{"id": f"{space}/casual/{space}-deck".removeprefix("home/"), "title": "T",
                               "space": space, "reason": "no_table", "version": None, "cards": [],
                               "why": f"{space} deck has no table ({root}/x.md)"} for space in ("home", "user2")],
                    "spaces": [{"space": space, "warnings": [f"order {root}/o.json"],
                                "unknown": [{"name": "Opt", "where": [f"{root}/c.csv"]}],
                                "why": f"{space}'s pool is incomplete"} for space in ("home", "user2")]}
        for who, shown in (("user2", ["user2/casual/r-elves"]),
                           ("user1", ["casual/gruul-test"]),
                           ("matt", ["casual/gruul-test"])):             # an admin: his own space (E10-S29)
            spaces_ = {"user2": ["user2"], "user1": ["home"], "matt": ["home"]}[who]
            with self.subTest(who=who), _as(who), \
                    mock.patch.object(pool, "stale_tables", return_value=[dict(e) for e in listed]), \
                    mock.patch.object(pool, "table_blockers", return_value=json.loads(json.dumps(blockers))):
                view = api.stale_view()
                self.assertEqual([e["id"] for e in view["stale"]], shown)
                # What blocks an update, and the pools that hold receipts back, follow the same rule.
                self.assertEqual([e["space"] for e in view["blocked"]], spaces_)
                self.assertEqual([e["space"] for e in view["held"]], spaces_)
                self.assertNotIn(root, json.dumps(view))
                self.assertEqual(view["held"][0]["unknown"], [{"name": "Opt", "where": ["c.csv"]}])

    def test_a_blocked_deck_isn_t_listed_as_one_to_update(self):
        listed = [{"id": "casual/gruul-test", "title": "Gruul Test", "sha256": "0" * 64, "count": 1, "changes": []}]
        blocked = {"decks": [{"id": "casual/gruul-test", "title": "Gruul Test", "space": "home",
                              "reason": "unknown_cards", "version": "owned", "cards": ["Opt"], "why": "w"}],
                   "spaces": []}
        with _as("matt"), mock.patch.object(pool, "stale_tables", return_value=listed), \
                mock.patch.object(pool, "table_blockers", return_value=blocked):
            view = api.stale_view()
        self.assertEqual(view["stale"], [])
        self.assertEqual(view["blocked"], blocked["decks"])

    def test_the_library_hides_counts_and_token_chips(self):
        with _as("user2"):
            index = api.decks_index()
        by_id = {d["id"]: d for d in index["decks"]}
        for deck_id, summary in by_id.items():
            with self.subTest(deck=deck_id):
                sees = summary["space"] == "user2"
                for key in HIDDEN_INDEX:
                    self.assertEqual(key in summary, sees, key)
        with _as("matt"):
            every = {d["id"]: d for d in api.decks_index()["decks"]}
        self.assertEqual(every["casual/gruul-test"]["missing"].keys(), {"target", "owned"})
        self.assertNotIn("missing", every["user2/casual/r-elves"])     # an admin's role opens no space (E10-S29)

    def test_the_editor_hides_the_table_note(self):
        with _as("user2"):
            self.assertNotIn("table", api.edit_view("casual/gruul-test"))
            self.assertIn("table", api.edit_view("user2/casual/r-elves"))
        with _as("user1"):
            self.assertIn("table", api.edit_view("casual/gruul-test"))

    def test_the_views_read_the_snapshot_not_the_files(self):
        inv = inventory.current()
        deck = inv.deck("casual/gruul-test")
        changed = deck.replace(text=deck.text.replace("# Gruul Test", "# Gruul In The Snapshot", 1))
        with inventory.pinned(inv.with_deck(changed)), _as("matt"):
            view = api.edit_view("casual/gruul-test")
            self.assertEqual((view["title"], view["sha256"]), ("Gruul In The Snapshot", changed.sha256))
            self.assertEqual(api.deck_view("casual/gruul-test")["summary"]["title"], "Gruul In The Snapshot")
            self.assertEqual({d["id"]: d["title"] for d in api.decks_index()["decks"]}["casual/gruul-test"],
                             "Gruul In The Snapshot")

    def test_the_pages_name_a_deck_by_its_id(self):
        with _as("matt"):
            index = {d["id"]: d for d in api.decks_index()["decks"]}
            self.assertEqual(api.deck_view("user2/casual/r-elves")["summary"]["source"], "user2/casual/r-elves")
            self.assertEqual(api.edit_view("casual/gruul-test")["source"], "casual/gruul-test")
        self.assertEqual(index["casual/gruul-test"]["source"], "casual/gruul-test")
        self.assertEqual(index["user2/casual/r-elves"]["source"], "user2/casual/r-elves")
        self.assertEqual(index["product/fdc-test-precon"]["source"], "magic/products/fdc-test-precon.csv")
        for view in (api.deck_view("casual/gruul-test"), api.edit_view("casual/gruul-test")):
            self.assertNotIn("uncommitted", view)       # nothing about git (R8)


class ProvenanceTests(support.PoolTestCase):
    """D6: {"deck", "revision"} when the snapshot names the deck's saved revision."""

    def setUp(self):
        super().setUp()
        self.write("decks/casual/test.md", support.deck_md("Test", "idea", "Deck\n4 Opt (DOM) 60\n"))

    def snapshot(self, deck_revision, **changes):
        inv = self.inventory.load()
        deck = inv.deck("casual/test").replace(revision=deck_revision)
        return dataclasses.replace(inv, decks={**inv.decks, deck.id: deck}, **changes)

    def entry(self):
        sections = decks.load_deck("casual/test")
        return lists.entry("casual/test", "target", "Test", "constructed", sections)

    def test_a_saved_revision_is_named(self):
        with inventory.pinned(self.snapshot(3)):
            self.assertEqual(lists._source("casual/test"), {"deck": "casual/test", "revision": 3})
            self.assertEqual(self.entry()["source"], {"deck": "casual/test", "revision": 3})

    def test_no_revision_names_no_deck_revision(self):
        with inventory.pinned(self.snapshot(0)):
            self.assertNotIn("deck", lists._source("casual/test") or {})

    def test_a_preview_names_nothing(self):
        # Not even the file on disk (D6): it doesn't hold the preview's text.
        for snapshot in (self.snapshot(3, revision="x" + inventory.PREVIEW),
                         self.snapshot(0, revision="x" + inventory.PREVIEW),
                         self.snapshot(3, decks_revision="x" + inventory.PREVIEW)):
            with self.subTest(revision=snapshot.revision, decks=snapshot.decks_revision), inventory.pinned(snapshot):
                self.assertIsNone(lists._source("casual/test"))

    def test_products_and_unknown_decks_keep_their_shapes(self):
        with inventory.pinned(self.snapshot(3)):
            self.assertIsNone(lists._source("casual/nothing"))
            self.assertNotIn("deck", lists._source("product/nothing") or {})


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseReaderTests(pg_decks_tests._Db):
    """The readers on the database backend with every deck file gone from disk."""

    def setUp(self):
        super().setUp()
        _, self.backend = self.import_tree()
        for path in (self.case.magic / "decks").rglob("*.md"):
            path.unlink()
        self.addCleanup(inventory.use(self.backend))

    def test_the_decks_and_their_provenance_come_from_the_database(self):
        with inventory.pinned():
            self.assertEqual(decks.load_deck("casual/test", "target")["Deck"][0].name, "Llanowar Elves")
            summary = decks.find_summary("commander/other")
            self.assertEqual((summary["title"], summary["versions"]), ("Other", ["target"]))
            entry = lists.entry("casual/test", "target", "Test", "constructed", decks.load_deck("casual/test"))
        self.assertEqual(entry["source"], {"deck": "casual/test", "revision": 1})
        before = self.backend.load().deck("casual/test")
        inventory.apply(inventory.Op("deck.save", {"deck_id": "casual/test", "text": pg_decks_tests.DECK + "\nMore.\n",
                                                   "base_sha256": before.sha256}), pg_decks_tests.MATT, "save Test")
        with lists.one_snapshot():
            self.assertEqual(lists._source("casual/test"), {"deck": "casual/test", "revision": 2})
            self.assertTrue(decks.read_deck_file(decks.find_deck_id("casual/test")).text.endswith("More.\n"))
        # A preview of a change names no revision: it was never saved.
        preview, _ = inventory.preview(inventory.Op("deck.save", {
            "deck_id": "casual/test", "text": pg_decks_tests.DECK, "base_sha256": self.backend.load().deck("casual/test").sha256}))
        with inventory.pinned(preview):
            self.assertIsNone(lists._source("casual/test"))     # and there's no file to fall back on

    def test_the_pages_read_the_database(self):
        # The library, deck page, editor and "Try a change" with no deck file on disk: test_api's
        # sandbox for the card index, config and stand-ins, with the database as the inventory.
        box = Sandbox().start()
        self.addCleanup(box.stop)
        self.addCleanup(inventory.use(self.backend))
        for path in (box.magic / "decks").rglob("*.md"):
            path.unlink()
        with inventory.pinned(), _as("matt"):
            index = {d["id"]: d for d in api.decks_index()["decks"]}
            view = api.deck_view("casual/test")
            edit = api.edit_view("commander/other")
            cards, sections = variant_page._draft_cards(
                types.SimpleNamespace(lists=lists), "casual/test", "target",
                {"Deck": [{"qty": 2, "name": "Llanowar Elves", "set": "fdn", "number": "227"},
                          {"qty": 58, "name": "Forest"}]})
        self.assertEqual((index["casual/test"]["title"], index["commander/other"]["source"]),
                         ("Test", "commander/other"))
        self.assertIn("missing", index["casual/test"])
        self.assertEqual(view["summary"]["source"], "casual/test")
        self.assertEqual([l["name"] for l in view["sections"]["Deck"]][:1], ["Llanowar Elves"])
        self.assertIn("owned", view)
        self.assertEqual((edit["title"], edit["sha256"]), ("Other", self.backend.load().deck("commander/other").sha256))
        self.assertEqual(sum(l.quantity for l in sections["Deck"]), 60)
        self.assertTrue(cards["Main"])
        with inventory.pinned(), _as("matt"):
            with self.assertRaises(api.ApiError) as caught:
                variant_page._draft_cards(types.SimpleNamespace(lists=lists), "casual/nothing", "target", {})
        self.assertEqual(caught.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
