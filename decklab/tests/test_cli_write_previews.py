"""Non-writing collection, token and deck-push previews over disposable inventory stores."""
import contextlib
import io
import json
import unittest
from datetime import date
from unittest import mock

from decklab.db import __main__ as cli
from decklab.lib import config, inventory, tokens
from decklab.lib.inventory import ops_collection, rules
from decklab.tests import db_support, test_pool as support


setUpModule = support.setUpModule
tearDownModule = support.tearDownModule
HEADER = ",".join(rules.FIELDS) + "\n"
TEXT = support.deck_md("Preview", "idea", "Deck\n2 Llanowar Elves\n58 Forest\n")
PROFILES = [{"id": "matt", "name": "Matt", "space": "home", "role": "admin", "plays_as": "user", "emails": []},
            {"id": "user2", "name": "User2", "space": "user2", "role": "member", "plays_as": None, "emails": []}]


class _PreviewTree(support.PoolTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.magic.parent
        self.write("decks/casual/preview.md", TEXT)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.write("tokens.csv", ",".join(tokens.FIELDS) + "\nFish,,,,,,2,,,single-sided verified\n")
        patcher = mock.patch.object(config, "load", return_value={"profiles": PROFILES})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Name resolution itself is covered by test_token_ops/test_tokens; these cases exercise the write plan.
        patcher = mock.patch.object(tokens, "check_names", side_effect=lambda row: (dict(row), []))
        patcher.start()
        self.addCleanup(patcher.stop)

    def source(self, name, text):
        path = self.root / name
        path.write_bytes(text.encode("utf-8"))
        return path

    def run_cli(self, *argv, preview=True):
        before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        revision = inventory.current().revision, inventory.current().decks_revision
        out, err = io.StringIO(), io.StringIO()
        block = mock.patch.object(inventory, "apply", side_effect=AssertionError("A preview tried to save"))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), block if preview else contextlib.nullcontext():
            code = cli.main([str(a) for a in argv] + (["--dry-run"] if preview else []))
        if preview:
            after = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
            self.assertEqual(after, before)
            self.assertEqual((inventory.current().revision, inventory.current().decks_revision), revision)
        return code, out.getvalue(), err.getvalue()


class CliWritePreviewTests(_PreviewTree):
    def test_merge_reports_deltas_skipped_basics_and_exact_raw_import_without_writing(self):
        raw = HEADER + "Llanowar Elves,fdn,227,nonfoil,3,,,Gift\r\nForest,fdn,280,nonfoil,7,,,\r\n"
        source = self.source("gift.csv", raw)
        code, out, err = self.run_cli("collection", "merge", source, "-m", "Add the gift")
        self.assertEqual(code, 0, err)
        self.assertIn("Would merge 3 cards", out)
        self.assertIn("+3 Llanowar Elves (fdn 227 nonfoil): 2 -> 5 copies", out)
        self.assertIn("Would omit 7 ordinary basic lands", out)
        self.assertIn(f"Would keep unchanged raw import magic/imports/{date.today().isoformat()}-gift.csv", out)
        self.assertIn("Nothing saved (--dry-run)", out)
        code, out, err = self.run_cli("collection", "merge", source, "-m", "Add the gift", preview=False)
        self.assertEqual(code, 0, err)
        self.assertEqual(next(r.qty for r in inventory.current().collection().rows), 5)
        self.assertEqual((self.magic / "imports" / f"{date.today().isoformat()}-gift.csv").read_bytes(), raw.encode())

    def test_merge_preview_checks_names_message_actor_quota_and_duplicate_imports(self):
        source = self.source("gift.csv", HEADER + "Llanowar Elves,fdn,227,nonfoil,1,,,\n")
        for extra, expected in [(["-m", " "], "-m needs a message"),
                                (["-m", "Gift", "--actor", "unknown"], "Unknown"),
                                (["-m", "Gift"], "over the limit")]:
            with self.subTest(extra=extra), mock.patch.object(ops_collection, "MAX_IMPORTS", 1):
                code, _, err = self.run_cli("collection", "merge", source, *extra)
                self.assertEqual(code, 1, err)
                self.assertIn(expected.lower(), err.lower())
        bad = self.source("bad.csv", HEADER + "Definitely Not A Card,fdn,227,nonfoil,1,,,\n")
        code, _, err = self.run_cli("collection", "merge", bad, "-m", "Bad")
        self.assertEqual(code, 1, err)
        self.assertIn("exact Scryfall name", err)
        self.assertEqual(self.run_cli("collection", "merge", source, "-m", "Gift", preview=False)[0], 0)
        code, out, err = self.run_cli("collection", "merge", source, source, "-m", "Repeat")
        self.assertEqual(code, 0, err)
        self.assertIn("already imported", err)
        self.assertIn("more than once", err)
        self.assertIn(f"{date.today().isoformat()}-gift-2.csv", out)
        self.assertIn(f"{date.today().isoformat()}-gift-3.csv", out)

    def test_token_previews_show_complete_before_and_after_rows(self):
        sha = tokens.read().sha256
        code, out, err = self.run_cli("tokens", "add", "--front", "Rabbit", "--quantity", "3", "--expect", sha,
                                      "--notes", "single-sided verified", "-m", "Gift")
        self.assertEqual(code, 0, err)
        self.assertIn("Before: (no row)", out)
        self.assertIn('"front": "Rabbit"', out)
        self.assertIn('"quantity": "3"', out)
        code, out, err = self.run_cli("tokens", "edit", "1", "--quantity", "4", "--expect", sha, "-m", "Correct")
        self.assertEqual(code, 0, err)
        rows = [json.loads(line.split(": ", 1)[1]) for line in out.splitlines() if line.startswith(("Before:", "After:"))]
        self.assertEqual([r["quantity"] for r in rows], ["2", "4"])
        self.assertEqual(rows[0]["notes"], rows[1]["notes"])
        code, out, err = self.run_cli("tokens", "remove", "1", "--expect", sha, "-m", "Remove", "--reason", "Duplicate")
        self.assertEqual(code, 0, err)
        self.assertIn('"front": "Fish"', out)
        self.assertIn("After: (no row)", out)

    def test_token_previews_keep_stale_duplicate_quantity_message_and_reason_checks(self):
        sha = tokens.read().sha256
        cases = [(("edit", "1", "--expect", "0" * 12, "-m", "Edit"), "changed since"),
                 (("edit", "2", "--expect", sha, "-m", "Edit"), "no row 2"),
                 (("edit", "1", "--expect", sha, "--quantity", "0", "-m", "Edit"), "from 1 to 9999"),
                 (("edit", "1", "--expect", sha, "-m", " "), "-m needs"),
                 (("remove", "1", "--expect", sha, "-m", "Remove", "--reason", " "), "--reason needs"),
                 (("add", "--front", "Fish", "--quantity", "1", "-m", "Add"), "already listed")]
        for argv, message in cases:
            with self.subTest(argv=argv):
                code, _, err = self.run_cli("tokens", *argv)
                self.assertEqual(code, 1, err)
                self.assertIn(message, err)

    def test_push_preview_shows_diff_and_checks_the_proposed_list(self):
        source = self.source("deck.md", TEXT.replace("2 Llanowar Elves", "3 Llanowar Elves"))
        sha = inventory.current().deck("casual/preview").sha256
        code, out, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "One more")
        self.assertEqual(code, 0, err)
        for text in ("--- casual/preview (current)", "+++ casual/preview (proposed)",
                     "-2 Llanowar Elves", "+3 Llanowar Elves", "Card names:", "Owned-vs-needed table:",
                     "Tokens:", "Accessories:", "Nothing saved (--dry-run)"):
            self.assertIn(text, out)
        self.assertEqual(inventory.current().deck("casual/preview").text, TEXT)
        code, _, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "One more", preview=False)
        self.assertEqual(code, 0, err)
        self.assertIn("3 Llanowar Elves", inventory.current().deck("casual/preview").text)

    def test_push_preview_reports_unknown_names_and_no_diff_and_refuses_stale_or_bad_text(self):
        sha = inventory.current().deck("casual/preview").sha256
        source = self.source("deck.md", TEXT)
        code, out, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Same")
        self.assertEqual(code, 0, err)
        self.assertIn("No text differences", out)
        source.write_text(TEXT.replace("Llanowar Elves", "Definitely Not A Card"), encoding="utf-8")
        code, out, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Check names")
        self.assertEqual(code, 0, err)
        self.assertIn("Not Scryfall card names: Definitely Not A Card", out)
        code, _, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", "0" * 12, "-m", "Stale")
        self.assertEqual(code, 1, err)
        self.assertIn("saved since", err)
        source.write_text("# Not a deck\n", encoding="utf-8")
        code, _, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Bad")
        self.assertEqual(code, 1, err)
        self.assertIn("no fenced decklist", err)

    def test_push_reports_unknown_names_in_the_considering_list(self):
        # E2-S23: a Considering card never counts, but one moved into the Planned list keeps its name.
        sha = inventory.current().deck("casual/preview").sha256
        source = self.source("deck.md", TEXT + "\n## Considering\n\n```\n1 Definitely Not A Card\n```\n")
        code, out, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Consider")
        self.assertEqual(code, 0, err)
        self.assertIn("Not Scryfall card names in the Considering list: Definitely Not A Card", out)
        self.assertNotIn("Card names: all checked names resolve", out)

    def test_push_preview_runs_the_real_kit_validation(self):
        source = self.source("deck.md", TEXT.replace("Status:** idea", "Status:** built\n- **Sleeves:** missing-kit"))
        sha = inventory.current().deck("casual/preview").sha256
        code, _, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Build")
        self.assertEqual(code, 1, err)
        self.assertIn("accessor", err.lower())

    def test_push_preview_can_build_with_valid_kit_without_saving(self):
        self.write("accessories.csv", "id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n"
                   "blue-sleeves,sleeves,shared,DS,Matte,blue,100,,,,,,\n")
        proposed = TEXT.replace("Status:** idea", "Status:** built\n- **Sleeves:** blue-sleeves")
        source = self.source("deck.md", proposed)
        sha = inventory.current().deck("casual/preview").sha256
        code, out, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Build")
        self.assertEqual(code, 0, err)
        self.assertIn("+- **Sleeves:** blue-sleeves", out)
        self.assertIn("Accessories: no problems found", out)
        self.assertEqual(inventory.current().deck("casual/preview").text, TEXT)

    def test_push_preview_refuses_unavailable_deck_storage(self):
        source = self.source("deck.md", TEXT + "\nNew note.\n")
        sha = inventory.current().deck("casual/preview").sha256
        with mock.patch.object(self.inventory, "saves_decks", return_value=False):
            code, _, err = self.run_cli("deck", "push", "casual/preview", source, "--expect", sha, "-m", "Edit")
        self.assertEqual(code, 2, err)
        self.assertIn("database holds no decks", err)


class PgCliWritePreviewTests(_PreviewTree, db_support.DbTestCase):
    """The same commands leave raw imports, saved revisions, history and audit rows untouched."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import Actor
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import adapt
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(adapt(self.inventory.load()), Actor("claude", "Claude", None, "cli"), "Fixture import",
                       contents={}, dbname=self.dbname, decks=True)
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))

    def evidence(self):
        tables = ("inventory_revision", "decks_revision", "collection_card", "collection_import",
                  "collection_import_content", "token_card", "deck", "deck_text", "deck_revision",
                  "audit.change_set", "audit.row_change")
        with self.connect() as connection:
            return {table: sorted(connection.execute("select * from " + table).fetchall(), key=repr)
                    for table in tables}

    def test_valid_and_refused_previews_leave_database_evidence_unchanged(self):
        source = self.source("gift.csv", HEADER + "Llanowar Elves,fdn,227,nonfoil,3,,,\n")
        proposed = self.source("deck.md", TEXT.replace("2 Llanowar Elves", "3 Llanowar Elves"))
        invalid = self.source("bad-deck.md", "# No list\n")
        deck_sha = inventory.current().deck("casual/preview").sha256
        token_sha = tokens.read().sha256
        before = self.evidence()
        cases = [(("collection", "merge", source, "-m", "Gift"), 0),
                 (("tokens", "add", "--front", "Rabbit", "--quantity", "3", "-m", "Gift"), 0),
                 (("tokens", "edit", "1", "--expect", token_sha, "--quantity", "3", "-m", "Edit"), 0),
                 (("tokens", "remove", "1", "--expect", token_sha, "-m", "Remove", "--reason", "Duplicate"), 0),
                 (("deck", "push", "casual/preview", proposed, "--expect", deck_sha, "-m", "Edit"), 0),
                 (("deck", "push", "casual/preview", invalid, "--expect", deck_sha, "-m", "Bad"), 1),
                 (("tokens", "edit", "1", "--expect", "0" * 12, "-m", "Stale"), 1)]
        for argv, expected in cases:
            with self.subTest(argv=argv):
                code, _, err = self.run_cli(*argv)
                self.assertEqual(code, expected, err)
                self.assertEqual(self.evidence(), before)
