"""Tests for the token cards' writes as inventory operations (decklab/lib/tokens/ops.py: tokens.add,
tokens.edit, tokens.remove) on both backends, the Tokens page's API and the token readers on the
database backend, and python -m decklab.db tokens.

The same cases run on the files backend (a temp magic/ tree, no git) and on the database
backend (a throwaway database from db_support, the fixture profiles synced once, the tree
imported per test); the database ones are skipped when PostgreSQL isn't reachable. The git-mode
files backend (production until the cutover) is test_api_tokens.py's.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_token_ops
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.tests import golden_dump as gate
from decklab.lib import cards, config, decks, inventory, pool, tokens
from decklab.lib.api import common
from decklab.lib.api import tokens as api_tok
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import Op, files, model, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor
from decklab.lib.tokens import ops
from decklab.tests import db_support
from decklab.tests.test_tokens import HEADER, deck_md

MATT = Actor("matt", "Matt", "home")
CLAUDE = Actor("claude", "Claude", None, "cli")
NOTE = "printing unconfirmed"
ROWS = HEADER + (
    f"Angel,The Monarch,,,,,1,,,{NOTE}\n"
    f"Insect,Goblin,,,,,1,1/1; flying; no deathtouch,,{NOTE}\n"
    f"Zombie,Zombie Knight,,,,,8,,,{NOTE}\n"
)
FISH = {"front": "Fish", "back": "", "set": "tblb", "front_collector_number": "7", "back_collector_number": "",
        "finish": "nonfoil", "quantity": "2", "front_details": "1/1; blue", "back_details": "",
        "notes": "single-sided verified"}
PROFILES = [{"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user", "emails": []},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2", "plays_as": None,
             "emails": []}]


def row(**values):
    return {**{k: "" for k in tokens.FIELDS}, **values}


class Cases:
    """The operations' cases, run on self.backend (set by each backend's setUp)."""

    def apply(self, kind, actor=MATT, message="a token change", reason=None, **params):
        return inventory.apply(Op(kind, params), actor, message, reason=reason)

    def sha(self, space="home"):
        return tokens.read(space=space).sha256

    def fronts(self, space="home"):
        return [r["front"] for r in tokens.read(space=space).rows]

    def test_an_add_keeps_the_rows_sorted_and_says_where_it_went(self):
        after, summary = self.apply("tokens.add", space="home", sha256=self.sha(),
                                    row=row(front="Rabbit", back="Rabbit", quantity="2", notes=NOTE))
        self.assertEqual(self.fronts(), ["Angel", "Insect", "Rabbit", "Zombie"])
        self.assertEqual(summary.extra["index"], 2)
        self.assertEqual(summary.text, "Added Rabbit / Rabbit ×2 to the home token cards")
        self.assertEqual(summary.counts, {"cards": 12})
        self.assertEqual(after.token_set().rows[2].front, "Rabbit")

    def test_an_edit_changes_that_row_only(self):
        before = tokens.read()
        ids = [r.id for r in inventory.current().token_set().rows]
        zombie = before.rows[2]
        _, summary = self.apply("tokens.edit", space="home", sha256=before.sha256, base=zombie,
                                row={**zombie, "quantity": "7"})
        after = tokens.read()
        self.assertEqual([r["quantity"] for r in after.rows], ["1", "1", "7"])
        self.assertEqual(after.rows[:2], before.rows[:2])
        self.assertEqual([r.id for r in inventory.current().token_set().rows], ids)    # the same rows
        self.assertEqual(summary.text, "Changed Zombie / Zombie Knight ×7 in the home token cards")

    def test_removing_every_row_leaves_no_token_cards(self):
        for _ in range(3):
            inv = tokens.read()
            self.apply("tokens.remove", space="home", sha256=inv.sha256, base=inv.rows[0], reason="traded")
        inv = tokens.read()
        self.assertEqual((inv.rows, inv.sha256), ([], None))
        self.assertFalse(inventory.current().token_set().exists)
        self.apply("tokens.add", space="home", sha256=None, row=row(front="Goblin", quantity="1",
                                                                     notes="single-sided verified"))
        self.assertEqual(self.fronts(), ["Goblin"])

    def test_a_stale_list_or_a_missing_row_is_refused_with_the_list_it_saw(self):
        old = tokens.read()
        insect = old.rows[1]
        self.apply("tokens.edit", space="home", sha256=old.sha256, base=insect, row={**insect, "quantity": "2"})
        with self.assertRaises(ops.Stale) as caught:
            self.apply("tokens.edit", space="home", sha256=old.sha256, base=insect, row={**insect, "quantity": "3"})
        self.assertEqual(caught.exception.inv.token_set().rows[1].quantity, "2")
        with self.assertRaises(ops.Stale):
            self.apply("tokens.remove", space="home", sha256=self.sha(), base={**insect, "quantity": "9"})
        self.assertEqual([r["quantity"] for r in tokens.read().rows], ["1", "2", "8"])

    def test_rows_are_never_merged(self):
        zombie = tokens.read().rows[2]
        with self.assertRaises(ops.SameRow) as caught:
            self.apply("tokens.add", space="home", sha256=self.sha(), row={**zombie, "quantity": "2"})
        self.assertEqual(str(caught.exception), "That card is already listed (Zombie / Zombie Knight ×8). "
                                                "Add to its quantity instead?")
        self.assertEqual(caught.exception.same_row, {"index": 2, "row": {**zombie, "quantity": 8},
                                                     "separate_allowed": True})
        # Unverified rows may be kept apart.
        self.apply("tokens.add", space="home", sha256=self.sha(), row={**zombie, "quantity": "2"}, separate=True)
        self.assertEqual([r["quantity"] for r in tokens.read().rows if r["front"] == "Zombie"], ["8", "2"])
        # Known ones can't.
        self.apply("tokens.add", space="home", sha256=self.sha(), row=FISH)
        with self.assertRaises(ops.SameRow) as caught:
            self.apply("tokens.add", space="home", sha256=self.sha(), row={**FISH, "quantity": "1"})
        self.assertFalse(caught.exception.same_row["separate_allowed"])
        with self.assertRaisesRegex(inventory.Conflict, "the same card; change its quantity instead"):
            self.apply("tokens.add", space="home", sha256=self.sha(), row={**FISH, "quantity": "1"}, separate=True)

    def test_a_row_breaking_the_rules_is_invalid(self):
        with self.assertRaisesRegex(inventory.Invalid, "must be a whole number from 1 to 9999"):
            self.apply("tokens.add", space="home", sha256=self.sha(), row=row(front="Rat", quantity="0"))
        self.assertEqual(self.fronts(), ["Angel", "Insect", "Zombie"])

    def test_a_persons_token_cards_are_their_own(self):
        self.apply("tokens.add", space="user2", sha256=None, row=row(front="Elf Warrior", quantity="2",
                                                                        notes="single-sided verified"))
        self.assertEqual(self.fronts("user2"), ["Elf Warrior"])
        self.assertEqual(self.fronts(), ["Angel", "Insect", "Zombie"])


class Tree:
    """A temp repo: ROWS as magic/tokens.csv, an empty status.csv, a building deck
    (casual/queen: Hornet Queen), User2's space, no card index."""

    def make_tree(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.magic = self.root / "magic"
        for sub in ("products", "decks/casual", "decks/commander", "orders/records", "orders/tokens",
                    "people/user2"):
            (self.magic / sub).mkdir(parents=True)
        (self.magic / "tokens.csv").write_text(ROWS, encoding="utf-8", newline="\n")
        (self.magic / "products/status.csv").write_bytes(rules.csv_bytes((), rules.STATUS_FIELDS))
        (self.magic / "watchlist.csv").write_text(",".join(model.QUEUE_FIELDS) + "\n", encoding="utf-8",
                                                  newline="\n")
        (self.magic / "decks/casual/queen.md").write_text(deck_md("Queen Deck", deck="1 Hornet Queen\n"),
                                                          encoding="utf-8", newline="\n")
        (self.root / "config.json").write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        self.logs = []
        for target, name, value in (
                (config, "REPO", self.root), (config, "CONFIG_FILE", self.root / "config.json"),
                (decks, "REPO", self.root), (pool, "REPO", self.root),
                (decks, "DECKS_DIR", self.magic / "decks"),
                (cards, "INDEX_FILE", self.root / "no-index.json.gz"), (cards, "_index", None),
                (common, "_log", self.logs.append),
                (api_tok, "_writer", lambda data: {"id": data.get("profile"), "name": "Matt", "role": "admin"})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)


class FileOpsTests(Tree, Cases, unittest.TestCase):

    def setUp(self):
        self.make_tree()
        self.backend = FileInventory(self.root)
        self.addCleanup(inventory.use(self.backend))

    def test_the_file_is_written_sorted_and_canonical(self):
        self.apply("tokens.add", space="home", sha256=self.sha(), row=FISH)
        text = (self.magic / "tokens.csv").read_bytes().decode("utf-8")
        self.assertEqual(text, ROWS + "Fish,,tblb,7,,nonfoil,2,1/1; blue,,single-sided verified\n")
        self.assertEqual(self.sha(), hashlib.sha256(text.encode()).hexdigest())

    def test_rows_a_strict_read_refuses_stop_every_write(self):
        (self.magic / "tokens.csv").write_text(ROWS + "Bad,,,,,,0,,,\n", encoding="utf-8", newline="\n")
        with self.assertRaisesRegex(inventory.Conflict,
                                    r"^magic/tokens.csv line 5: .*; it can't be changed until that's put right$"):
            self.apply("tokens.add", space="home", sha256=self.sha(), row=FISH)

    def test_an_unsorted_file_is_sorted_and_said_so(self):
        lines = ROWS.splitlines(keepends=True)
        (self.magic / "tokens.csv").write_text("".join([lines[0], lines[3], lines[1], lines[2]]), encoding="utf-8")
        self.assertFalse(tokens.read().sorted)
        inv = tokens.read()
        _, summary = self.apply("tokens.edit", space="home", sha256=inv.sha256, base=inv.rows[1],
                                row={**inv.rows[1], "quantity": "2"})
        self.assertEqual((summary.extra["resorted"], summary.extra["body"]), (True, [ops.RESORTED]))
        self.assertEqual(self.fronts(), ["Angel", "Insect", "Zombie"])
        self.assertTrue(tokens.read().sorted)


class Cli:
    """Runs python -m decklab.db tokens in this process."""

    def run_cli(self, *argv):
        from decklab.db import __main__ as cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["tokens", *argv])
        return code, out.getvalue(), err.getvalue()

    def listed_sha(self, space="home"):
        """The sha tokens list --json gives, as --expect takes it."""
        code, out, err = self.run_cli("list", "--json", "--space", space)
        self.assertEqual(code, 0, err)
        return json.loads(out)["sha256"]


class CommandLineTests(Tree, Cli, unittest.TestCase):
    """python -m decklab.db tokens, on the files backend."""

    def setUp(self):
        self.make_tree()
        self.addCleanup(inventory.use(FileInventory(self.root)))

    def test_list_and_json(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("The home token cards: 3 rows, 10 cards.", out)
        self.assertIn(f"sha {tokens.read().sha256} (give it to edit or remove as --expect)", out)
        self.assertIn("   3. Zombie / Zombie Knight ×8", out)
        code, out, _ = self.run_cli("list", "--json")
        listed = json.loads(out)
        self.assertEqual([r["front"] for r in listed["rows"]], ["Angel", "Insect", "Zombie"])
        self.assertEqual(listed["sha256"], tokens.read().sha256)
        code, out, _ = self.run_cli("list", "--space", "user2")
        self.assertIn("User2's token cards: 0 rows, 0 cards.", out)
        self.assertIn("sha none ", out)
        code, _, err = self.run_cli("list", "--space", "nobody")
        self.assertEqual(code, 1)
        self.assertIn("no space 'nobody'", err)

    def test_add_edit_and_remove(self):
        code, out, err = self.run_cli("add", "--front", "Fish", "--set", "tblb", "--front-number", "7",
                                      "--finish", "nonfoil", "--quantity", "2", "--notes", "single-sided verified",
                                      "-m", "Add the Fish from the MTGMate order")
        self.assertEqual(code, 0, err)
        self.assertIn("Added Fish ×2 to the home token cards.", out)
        self.assertIn("Note: " + tokens.NAMES_UNCHECKED, err)
        code, out, err = self.run_cli("edit", "4", "--expect", self.listed_sha(), "--quantity", "3",
                                      "-m", "Found another Fish")
        self.assertEqual(code, 0, err)
        self.assertEqual([r["quantity"] for r in tokens.read().rows], ["1", "1", "8", "3"])
        code, out, err = self.run_cli("remove", "1", "--expect", self.listed_sha()[:12], "-m", "Traded the Angel",
                                      "--reason", "traded to User1")
        self.assertEqual(code, 0, err)
        self.assertEqual([r["front"] for r in tokens.read().rows], ["Insect", "Zombie", "Fish"])
        code, out, err = self.run_cli("add", "--front", "Fish", "--quantity", "1", "--expect", "none",
                                      "--notes", "single-sided verified", "--space", "user2", "-m", "x")
        self.assertEqual(code, 0, err)

    def test_a_stale_expect_in_a_persons_space_names_the_listing_to_run_again(self):
        # E11-S12: the database's words and the command to run, never magic/people/<id>/tokens.csv.
        sha = self.listed_sha("user2") or "none"    # user2 has no token cards yet
        self.run_cli("add", "--front", "Ally", "--quantity", "1", "--notes", "single-sided verified",
                     "--space", "user2", "-m", "x")
        code, _, err = self.run_cli("edit", "1", "--expect", sha, "--quantity", "2", "--space", "user2", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("User2's token cards have changed since that listing: run tokens list --space user2 "
                      "again and retry with its sha.", err)
        self.assertNotIn("tokens.csv", err)

    def test_a_row_number_is_refused_once_the_list_has_moved_on(self):
        # Rows listed, then a page save adds a row before them: row 1 is no longer the Angel.
        sha = self.listed_sha()
        self.run_cli("add", "--front", "Ally", "--quantity", "1", "--notes", "single-sided verified", "-m", "x")
        before = (self.magic / "tokens.csv").read_bytes()
        code, _, err = self.run_cli("remove", "1", "--expect", sha, "-m", "Traded the Angel", "--reason", "traded")
        self.assertEqual(code, 1)
        self.assertIn("The home token cards have changed since that listing: run tokens list again and retry "
                      "with its sha.", err)
        self.assertNotIn("tokens.csv", err)
        self.assertEqual((self.magic / "tokens.csv").read_bytes(), before)
        code, _, err = self.run_cli("remove", "9", "--expect", self.listed_sha(), "-m", "x", "--reason", "y")
        self.assertEqual(code, 1)
        self.assertIn("There's no row 9: the home token cards have 4 (tokens list numbers them).", err)
        for expect in ("abc", "none", "x" * 64):
            code, _, err = self.run_cli("edit", "1", "--expect", expect, "--quantity", "2", "-m", "x")
            self.assertEqual(code, 1, expect)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_cli("edit", "1", "--quantity", "2", "-m", "x")        # --expect is required

    def test_refusals(self):
        code, _, err = self.run_cli("add", "--front", "Zombie", "--back", "Zombie Knight", "--quantity", "1",
                                    "--notes", NOTE, "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("That card is already listed (Zombie / Zombie Knight ×8). Pass --separate", err)
        code, _, err = self.run_cli("add", "--front", "Zombie", "--back", "Zombie Knight", "--quantity", "1",
                                    "--notes", NOTE, "--separate", "-m", "x")
        self.assertEqual(code, 0, err)
        sha = self.listed_sha()
        code, _, err = self.run_cli("edit", "9", "--expect", sha, "--quantity", "2", "-m", "x")
        self.assertEqual((code, "There's no row 9" in err), (1, True))
        code, _, err = self.run_cli("edit", "1", "--expect", sha, "--quantity", "0", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("The token card can't be saved", err)
        code, _, err = self.run_cli("remove", "1", "--expect", sha, "-m", "x", "--reason", " ")
        self.assertEqual(code, 1)

    def test_a_broken_result_is_said_not_a_traceback(self):
        with mock.patch.object(ops, "_guard", side_effect=ops.Broken("The tokens list Deck Lab made is wrong")):
            code, _, err = self.run_cli("add", "--front", "Ally", "--quantity", "1",
                                        "--notes", "single-sided verified", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("The tokens list Deck Lab made is wrong (a bug in Deck Lab", err)
        self.assertNotIn("Traceback", err)

    def test_check(self):
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        self.assertIn("Token cards (home): no problems", out)
        (self.magic / "tokens.csv").write_text(ROWS + "Bad,,,,,,0,,,\n", encoding="utf-8")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("magic/tokens.csv line 5", out)

    def test_check_warns_about_mistyped_details_without_failing(self):
        (self.magic / "tokens.csv").write_text(ROWS.replace("1/1; flying; no deathtouch", "1/1 flying"),
                                               encoding="utf-8", newline="\n")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Row 2 of the home token cards: front details '1/1 flying' aren't read: "
                                   "separate them with ';' (1/1; flying)")
        self.assertEqual(lines[-1], "Token cards (home): no problems")
        (self.magic / "tokens.csv").write_text(ROWS.replace("1/1; flying; no deathtouch", "1/1; flyng")
                                               + "Bad,,,,,,0,,,\n", encoding="utf-8", newline="\n")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        lines = out.splitlines()
        self.assertIn("magic/tokens.csv line 5", lines[0])
        self.assertIn("Row 2 of the home token cards: front details 'flyng' aren't read: did you mean flying?", lines)


class PgOpsTests(Tree, Cases, Cli, db_support.DbTestCase):
    """The same cases on the database backend, plus what only the database has: the audit trail,
    and the Tokens page's 409 saying who changed the list from it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.make_tree()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(FileInventory(self.root).load(), CLAUDE, "Import the inventory", contents={},
                       dbname=self.dbname)
        (self.magic / "tokens.csv").unlink()            # nothing may read the file now
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def trail(self):
        with self.connect() as c:
            sets = c.execute("select id, actor, source, message, reason from audit.change_set order by id").fetchall()
            rows = c.execute("select change_set_id, table_name, op from audit.row_change order by id").fetchall()
        return [{"actor": s[1], "source": s[2], "message": s[3], "reason": s[4],
                 "rows": [r[1:] for r in rows if r[0] == s[0]]} for s in sets]

    def test_each_write_is_one_change_set(self):
        inv = tokens.read()
        self.apply("tokens.edit", message="edit token Zombie // Zombie Knight", sha256=inv.sha256, space="home",
                   base=inv.rows[2], row={**inv.rows[2], "quantity": "7"})
        self.apply("tokens.remove", message="remove token Angel // The Monarch", reason="traded", space="home",
                   sha256=self.sha(), base=tokens.read().rows[0])
        last, edit = self.trail()[-1], self.trail()[-2]
        self.assertEqual((edit["actor"], edit["source"], edit["message"]),
                         ("matt", "web", "edit token Zombie // Zombie Knight"))
        self.assertEqual(edit["rows"], [("token_card", "UPDATE")])
        self.assertEqual((last["message"], last["reason"], last["rows"]),
                         ("remove token Angel // The Monarch", "traded", [("token_card", "DELETE")]))

    def test_the_page_saves_to_the_database_and_names_who_got_in_the_way(self):
        view = api_tok.tokens_view()
        self.assertEqual(("uncommitted" in view, "commit_pending" in view, view["exists"]), (False, False, True))
        call = lambda **data: api_tok.save_token(json.dumps({"profile": "matt", **data}).encode())   # noqa: E731
        insect = {k: str(v) for k, v in view["rows"][1].items() if k in tokens.FIELDS}
        answer = call(sha256=view["sha256"], action="edit", base=insect, row={"quantity": 2})
        self.assertEqual(("commit" in answer, answer["index"], answer["data"]["rows"][1]["quantity"]), (False, 1, 2))
        self.assertEqual(self.trail()[-1]["message"], "edit token Insect // Goblin")
        with self.assertRaises(ApiError) as caught:
            call(sha256=view["sha256"], action="edit", base=insect, row={"quantity": 3})
        e = caught.exception
        self.assertEqual(e.status, 409)
        self.assertIn("The tokens list changed after you opened it: Matt saved it in Deck Lab", e.message)
        conflict = e.extra["conflict"]
        self.assertEqual((conflict["by"], conflict["deck_lab"], conflict["subject"], conflict["base_state"]),
                         ("Matt", True, "edit token Insect // Goblin", "changed"))
        self.assertEqual(e.extra["latest"]["rows"][1]["quantity"], 2)

    def test_the_command_line_writes_to_the_database(self):
        code, out, err = self.run_cli("add", "--front", "Fish", "--quantity", "2", "--notes", "single-sided verified",
                                      "-m", "Add the Fish")
        self.assertEqual(code, 0, err)
        sha = self.listed_sha()
        self.assertEqual(sha, tokens.read().sha256)
        code, out, err = self.run_cli("edit", "2", "--expect", sha, "--quantity", "3", "-m", "Another Fish")
        self.assertEqual(code, 0, err)
        code, _, err = self.run_cli("remove", "1", "--expect", sha, "-m", "x", "--reason", "y")
        self.assertEqual(code, 1)                   # the list moved on since that sha
        self.assertIn("has changed since that listing", err)
        code, out, err = self.run_cli("remove", "1", "--expect", self.listed_sha(), "-m", "Traded the Angel",
                                      "--reason", "traded")
        self.assertEqual(code, 0, err)
        self.assertEqual([(r["front"], r["quantity"]) for r in tokens.read().rows],
                         [("Fish", "3"), ("Insect", "1"), ("Zombie", "8")])
        trail = self.trail()[-3:]
        self.assertEqual([(t["actor"], t["source"], t["message"], t["reason"]) for t in trail],
                         [("claude", "cli", "Add the Fish", None), ("claude", "cli", "Another Fish", None),
                          ("claude", "cli", "Traded the Angel", "traded")])


class PgReaderGoldenTests(db_support.DbTestCase):
    """The token readers on the database backend give the scenario goldens' token items (the
    inventory files deleted, so nothing can read them): every space's tokens.read(), and a
    person space's tokens.check(). (Home's check, the holders, uses and gaps also need the
    order records and products from the database: test_inventory_contract's PORTED "tokens"
    covers them once those readers are ported.)"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests import test_inventory_contract as contract
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def test_token_reads_match_the_goldens(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests import test_inventory_contract as contract
        for name, builder in contract.SCENARIOS.items():
            if name in contract.FILE_ONLY:
                continue
            with self.subTest(scenario=name):
                db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
                golden = contract.load_golden(name, adapted=True)["tokens"]["spaces"]
                with contract.scenario(builder, adapted=True) as case:
                    root = case.inventory.root
                    pg.write_model(case.inventory.load(), CLAUDE, "Import", contents=contract.import_contents(root),
                                   dbname=self.dbname)
                    for rel in files.tree_files(root):
                        (root / rel).unlink()
                    backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
                    with gate.pointed(root), inventory.use(backend), inventory.pinned():
                        for space, items in golden.items():
                            got = gate._plain(gate._capture(root, lambda: tokens.read(space=space)), root)
                            found = gate.first_difference(items["read"], got, f"$[{space!r}].read")
                            self.assertIsNone(found, found)
                            if space != "home":
                                got = gate._capture(root, lambda: tokens.check(space=space))
                                found = gate.first_difference(items["check"], got, f"$[{space!r}].check")
                                self.assertIsNone(found, found)


if __name__ == "__main__":
    unittest.main()
