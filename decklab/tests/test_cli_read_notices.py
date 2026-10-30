"""CLI privacy advice with fake visibility and disposable collection data only."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.db import cli_actor, inv_accessories, inv_collection, inv_decks, inv_tokens, read_notices, wishlist_cli
from decklab.lib import config, inventory, permissions, spaces, state, tokens, visibility
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Unavailable

SHA = "a" * 64
COLLECTION = ("name,set,collector_number,finish,quantity,condition,language,notes\n"
              "Fixture Café,fdn,1,nonfoil,2,,,PRIVATE_COLLECTION_NOTE\n")


class ReadNoticeTests(unittest.TestCase):
    def setUp(self):
        self.store = SimpleNamespace(visibility=mock.Mock(return_value={}),
            visibility_cached=mock.Mock(side_effect=AssertionError("Cached grants forbidden")),
            visibility_set=mock.Mock(side_effect=AssertionError("Visibility writes forbidden")))
        self.make = self.enterContext(mock.patch.object(read_notices.pg, "PgStore", return_value=self.store))
        self.exists = self.enterContext(mock.patch.object(spaces, "exists", side_effect=lambda owner: owner in {"home", "user2", "user3"}))
        self.enterContext(mock.patch.object(spaces, "get", return_value=SimpleNamespace(id="user2", name="User2")))
        self.canaries = [self.enterContext(mock.patch.object(target, name, side_effect=AssertionError("Forbidden " + name)))
            for target, name in [(config, "load"), (state, "store"), (visibility, "snapshot"),
                                 (inventory, "apply"), (permissions, "can"), (cli_actor, "resolve")]]
        self.entries = [{"name": "Fixture Card", "set": "fdn", "number": "1", "notes": "PRIVATE_WISHLIST_NOTE", "source": "PRIVATE_SOURCE"}]
        self.token_rows = [{key: "" for key in tokens.FIELDS}]
        self.token_rows[0].update(front="Goblin", quantity="2", set="tfdn", front_collector_number="3", finish="foil", notes="PRIVATE_TOKEN_NOTE")
        self.token_inventory = tokens.Inventory(rows=self.token_rows, sha256=SHA)
        self.rows = [{"id": "sleeves-test", "kind": "sleeves", "owner": "matt", "brand": "DS", "name": "Matte",
                      "colour": "red", "quantity": 100, "capacity": "", "image": "", "notes": "PRIVATE_ACCESSORY_NOTE"},
                     {"id": "box-test", "kind": "deck_box", "owner": "shared", "brand": "UG", "name": "Box",
                      "colour": "black", "quantity": 1, "capacity": 100, "image": "", "notes": "PRIVATE_SHARED_NOTE"}]
        self.accessory_inventory = SimpleNamespace(rows_by_id={row["id"]: row for row in self.rows}, sha256=SHA, problems=[])
        self.deck_rows = [{"id": "user2/casual/test", "title": "PRIVATE_DECK_TITLE", "kind": "casual", "space": "user2",
                           "status": "idea", "player": None, "revision": 7, "sha256": SHA, "marker": None, "stale": True, "error": None}]
        self.enterContext(mock.patch.object(tokens, "read", return_value=self.token_inventory))
        self.enterContext(mock.patch.object(inv_accessories, "listed", return_value=self.accessory_inventory))
        self.enterContext(mock.patch.object(inv_decks, "deck_rows", side_effect=lambda space: copy.deepcopy(self.deck_rows)))

    def tearDown(self):
        self.store.visibility_cached.assert_not_called()
        self.store.visibility_set.assert_not_called()
        for canary in self.canaries:
            canary.assert_not_called()

    def args(self, **changes):
        return SimpleNamespace(**{"json": False, "space": "user2", "dbname": "fixture-db", "action": "list", **changes})

    def capture(self, call):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = call()
        return result, out.getvalue(), err.getvalue()

    def wishlist(self, json_mode=False):
        store = SimpleNamespace(wishlist=mock.Mock(return_value=copy.deepcopy(self.entries)))
        return wishlist_cli._list(store, "user1", "User1", self.args(json=json_mode))

    def check_private(self, notice, owner="user2"):
        self.assertIn("Private", notice)
        self.assertIn(owner, notice)
        self.assertNotIn("Public switch enabled", notice)

    def test_wishlist_text_is_unchanged_and_privacy_never_reads_switches(self):
        code, out, err = self.capture(self.wishlist)
        self.assertEqual((code, out), (0, "User1's wishlist: 1 card.\n  Fixture Card (fdn 1)\n"
                                           "      notes: PRIVATE_WISHLIST_NOTE\n      source: PRIVATE_SOURCE\n"))
        self.assertEqual(err, "Privacy: wishlist is Private to owner user1. Do not relay its contents outside that owner.\n")
        self.make.assert_not_called()

    def test_wishlist_json_schema_and_order_are_unchanged(self):
        code, out, err = self.capture(lambda: self.wishlist(True))
        self.assertEqual((code, out), (0, json.dumps({"version": 1, "entries": self.entries}, ensure_ascii=False, indent=2) + "\n"))
        self.check_private(err, "user1")
        self.make.assert_not_called()

    def test_wishlist_help_forbids_notes_in_audit_messages(self):
        parser = argparse.ArgumentParser()
        wishlist_cli.add_parser(parser.add_subparsers(dest="command"))
        for arguments in (["wishlist", "--help"], ["wishlist", "add", "--help"], ["wishlist", "set", "--help"], ["wishlist", "remove", "--help"]):
            with self.subTest(arguments=arguments), redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as exited:
                parser.parse_args(arguments)
            self.assertEqual(exited.exception.code, 0)
            self.assertIn("never quote wishlist notes", " ".join(out.getvalue().lower().split()))
        self.make.assert_not_called()

    def test_tokens_human_output_and_sha_are_unchanged(self):
        code, out, err = self.capture(lambda: inv_tokens._list("user2", self.args()))
        self.assertEqual((code, out), (0, "User2's token cards: 1 row, 2 cards.\n"
            f"sha {SHA} (give it to edit or remove as --expect)\n   1. Goblin \u00d72  [tfdn 3 foil]\n        notes: PRIVATE_TOKEN_NOTE\n"))
        self.check_private(err)
        self.assertIn("tokens in space user2", err)
        self.store.visibility.assert_called_once_with()

    def test_tokens_json_uses_collection_public_switch_without_changing_data(self):
        self.store.visibility.return_value = {("user2", "collection"): {}}
        before = copy.deepcopy(self.token_rows)
        code, out, err = self.capture(lambda: inv_tokens._list("user2", self.args(json=True)))
        self.assertEqual((code, out), (0, json.dumps({"sha256": SHA, "rows": before}, ensure_ascii=False, indent=2) + "\n"))
        self.assertIn("tokens in space user2: collection Public switch enabled for signed-in profiles, read-only", err)
        self.assertEqual(self.token_rows, before)

    def test_public_decks_do_not_publish_tokens_and_public_collection_does_not_publish_decks(self):
        self.store.visibility.return_value = {("user2", "decks"): {}}
        self.check_private(self.capture(lambda: inv_tokens._list("user2", self.args()))[2])
        self.store.visibility.return_value = {("user2", "collection"): {}}
        self.check_private(self.capture(lambda: inv_decks._list(self.args()))[2])

    def test_deck_human_output_revision_and_table_status_are_unchanged(self):
        code, out, err = self.capture(lambda: inv_decks._list(self.args()))
        self.assertEqual((code, out), (0, "1 deck in user2.\n  user2/casual/test  PRIVATE_DECK_TITLE  (casual, idea, revision 7, table out of date)\n"))
        self.check_private(err)
        self.assertIn("does not publish inventory-derived table status/errors or kit", err)
        self.assertNotIn("PRIVATE_DECK_TITLE", err)

    def test_deck_json_remains_original_schema_with_scope_only_on_stderr(self):
        self.store.visibility.return_value = {("user2", "decks"): {}}
        code, out, err = self.capture(lambda: inv_decks._list(self.args(json=True)))
        self.assertEqual((code, out), (0, json.dumps(self.deck_rows, ensure_ascii=False, indent=2) + "\n"))
        self.assertIn("decks in space user2: decks Public switch enabled", err)
        self.assertIn("keep those Private to their space or accessory owner", err)

    def test_all_decks_get_distinct_scopes_from_one_fresh_read(self):
        self.deck_rows += [{**self.deck_rows[0], "id": "casual/home", "space": "home"}, self.deck_rows[0].copy()]
        self.store.visibility.return_value = {("home", "decks"): {}}
        code, out, err = self.capture(lambda: inv_decks._list(self.args(space=None, json=True)))
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)), 3)
        self.assertEqual(err.count("decks in space user2"), 1)
        self.assertEqual(err.count("decks in space home"), 1)
        self.store.visibility.assert_called_once_with()

    def test_accessories_text_and_sha_remain_unchanged_with_per_row_notices(self):
        code, out, err = self.capture(lambda: inv_accessories._list(self.args()))
        self.assertEqual((code, out), (0, f"2 accessories.\nsha {SHA} (give it to add, edit or remove as --expect)\n"
            "  sleeves-test  DS Matte (red)  (sleeves, owner matt, \u00d7100)\n"
            "  box-test  UG Box (black)  (deck_box, owner shared, \u00d71, holds 100)\n"))
        self.assertIn("accessory row 1, owner matt: Private to that owner", err)
        self.assertIn("accessory row 2, shared home kit: Private to the shared home kit", err)
        self.store.visibility.assert_called_once_with()

    def test_accessories_json_is_unchanged_and_shared_is_not_automatically_public(self):
        self.store.visibility.return_value = {("matt", "accessories"): {}}
        before = copy.deepcopy(self.rows)
        code, out, err = self.capture(lambda: inv_accessories._list(self.args(json=True)))
        self.assertEqual((code, out), (0, json.dumps({"sha256": SHA, "rows": before, "problems": []}, ensure_ascii=False, indent=2) + "\n"))
        self.assertIn("row 1, owner matt: kit Public to signed-in profiles", err)
        self.assertIn("row 2, shared home kit: Private", err)
        self.assertEqual(self.rows, before)

    def test_shared_public_switch_is_independent_of_individual_owners(self):
        self.store.visibility.return_value = {("shared", "accessories"): {}}
        _, _, err = self.capture(lambda: inv_accessories._list(self.args()))
        self.assertIn("row 1, owner matt: Private", err)
        self.assertIn("row 2, shared home kit: kit Public to signed-in profiles, read-only", err)

    def test_reporter_is_lazy_reads_once_and_uses_a_new_store_for_each_command(self):
        reporter = read_notices.Reporter("chosen-fixture-db")
        self.make.assert_not_called()
        self.capture(lambda: (reporter.space("collection", "user2"), reporter.space("decks", "user3"), reporter.accessories(self.rows)))
        self.store.visibility.assert_called_once_with()
        self.assertEqual(self.make.call_args.kwargs["dbname"], "chosen-fixture-db")
        first_breaker = self.make.call_args.kwargs["breaker"]
        self.capture(lambda: read_notices.Reporter("second-db").space("decks", "user2"))
        self.assertEqual(self.make.call_count, 2)
        self.assertEqual(self.make.call_args.kwargs["dbname"], "second-db")
        self.assertIsNot(self.make.call_args.kwargs["breaker"], first_breaker)

    def test_each_listing_passes_requested_database_and_never_reuses_prior_public_snapshot(self):
        self.store.visibility.side_effect = [{("user2", "collection"): {}}, {}]
        first = self.capture(lambda: inv_tokens._list("user2", self.args(dbname="first-db")))
        second = self.capture(lambda: inv_tokens._list("user2", self.args(dbname="second-db")))
        self.assertIn("Public switch enabled", first[2])
        self.check_private(second[2])
        self.assertEqual(first[:2], second[:2])
        self.assertEqual([call.kwargs["dbname"] for call in self.make.call_args_list], ["first-db", "second-db"])

    def test_unavailable_visibility_never_uses_cached_public_or_leaks_error(self):
        self.store.visibility.side_effect = Unavailable("PRIVATE_DB_PASSWORD C:/private/fixture")
        self.store.visibility_cached.return_value = {("user2", "collection"): {}}
        _, out, err = self.capture(lambda: inv_tokens._list("user2", self.args(json=True)))
        self.assertEqual(json.loads(out)["sha256"], SHA)
        self.assertIn("visibility could not be verified; treat this data as Private", err)
        self.assertNotIn("Public", err)
        for secret in ("PRIVATE_DB_PASSWORD", "C:/private", "PRIVATE_TOKEN_NOTE"):
            self.assertNotIn(secret, err)

    def test_malformed_snapshot_and_constructor_failure_are_conservative(self):
        for value in (None, [], "PRIVATE_VALUE"):
            with self.subTest(value=value):
                self.store.visibility.return_value = value
                _, _, err = self.capture(lambda: read_notices.Reporter().space("decks", "user2"))
                self.assertIn("could not be verified", err)
                self.assertNotIn("PRIVATE_VALUE", err)
        self.make.side_effect = RuntimeError("PRIVATE_FACTORY_PATH")
        _, _, err = self.capture(lambda: read_notices.Reporter().space("decks", "user2"))
        self.assertIn("could not be verified", err)
        self.assertNotIn("PRIVATE_FACTORY_PATH", err)

    def test_readiness_and_orphan_switches_never_claim_public(self):
        with mock.patch.object(visibility, "READY_THINGS", frozenset()):
            _, _, err = self.capture(lambda: read_notices.Reporter().space("decks", "user2"))
        self.assertIn("could not be verified", err)
        self.make.assert_not_called()
        self.store.visibility.return_value = {("removed-space", "decks"): {}}
        _, _, err = self.capture(lambda: read_notices.Reporter().space("decks", "removed-space"))
        self.assertIn("could not be verified", err)
        self.assertNotIn("Public switch enabled", err)

    def test_owner_metadata_is_single_line_and_never_echoes_unvalidated_input(self):
        for owner in (None, 4, "bad\nPRIVATE_INJECTED", "\x1b[31mPRIVATE_COLOR", "üser", "x" * 65):
            with self.subTest(owner=owner):
                _, _, err = self.capture(lambda: (read_notices.wishlist(owner), read_notices.Reporter().space("collection", owner),
                                                   read_notices.Reporter().accessories([{"owner": owner, "notes": "PRIVATE_ROW_NOTE"}])))
                self.assertEqual(len(err.splitlines()), 3)
                self.assertIn("unknown", err)
                self.assertNotIn("PRIVATE_", err)
        self.make.assert_not_called()

    def test_notices_do_not_quote_rows_switch_audit_metadata_or_notes(self):
        self.store.visibility.return_value = {("user2", "collection"): {"by": "PRIVATE_SETTER", "since": "PRIVATE_DATE"},
                                              ("matt", "accessories"): {"by": "PRIVATE_SETTER"}}
        _, _, err = self.capture(lambda: (self.wishlist(), inv_tokens._list("user2", self.args()),
                                          inv_accessories._list(self.args()), inv_decks._list(self.args())))
        self.assertNotIn("PRIVATE_", err)
        self.assertNotIn("Fixture Card", err)
        self.assertNotIn("Goblin", err)
        self.assertNotIn("Matte", err)

    def test_closed_or_broken_notice_stream_cannot_fail_other_successful_lists(self):
        calls = [self.wishlist, lambda: inv_tokens._list("user2", self.args()),
                 lambda: inv_decks._list(self.args()), lambda: inv_accessories._list(self.args())]
        for failure in (BrokenPipeError("fixture"), UnicodeError("fixture"), ValueError("closed")):
            for call in calls:
                with self.subTest(failure=type(failure).__name__, call=call), redirect_stdout(io.StringIO()) as out:
                    with redirect_stderr(SimpleNamespace(write=mock.Mock(side_effect=failure))):
                        self.assertEqual(call(), 0)
                    self.assertTrue(out.getvalue())

    def test_missing_stderr_never_redirects_privacy_advice_into_stdout(self):
        for call in (self.wishlist, lambda: inv_tokens._list("user2", self.args(json=True))):
            expected = self.capture(call)[:2]
            with redirect_stdout(io.StringIO()) as out, redirect_stderr(None):
                self.assertEqual(call(), expected[0])
            self.assertEqual(out.getvalue(), expected[1])
            self.assertNotIn("Privacy:", out.getvalue())

    def test_failed_primary_reader_does_not_attempt_visibility_or_replace_the_failure(self):
        failure = Unavailable("FIXTURE_PRIMARY_READER")
        with mock.patch.object(tokens, "read", side_effect=failure), self.assertRaises(Unavailable) as caught:
            inv_tokens._list("user2", self.args())
        self.assertIs(caught.exception, failure)
        self.make.assert_not_called()

    def test_unknown_deck_space_keeps_its_existing_exit_code_before_visibility(self):
        code, out, err = self.capture(lambda: inv_decks._list(self.args(space="missing")))
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "There's no space 'missing' in decklab/config.json.\n")
        self.make.assert_not_called()

    def collection_fixture(self):
        root = Path(tempfile.mkdtemp(prefix="decklab-read-notices-"))
        self.addCleanup(shutil.rmtree, root)
        path = root / "magic" / "people" / "user2" / "collection.csv"
        path.parent.mkdir(parents=True)
        path.write_bytes(COLLECTION.encode("utf-8"))
        self.addCleanup(inventory.use(FileInventory(root)))
        self.enterContext(mock.patch.object(inv_collection, "_space", return_value=SimpleNamespace(name="User2")))

    def test_collection_csv_and_sha_are_exact_with_private_notice_before_sha(self):
        self.collection_fixture()
        code, out, err = self.capture(lambda: inv_collection._list(self.args()))
        self.assertEqual((code, out), (0, COLLECTION))
        self.check_private(err)
        expected_sha = hashlib.sha256(COLLECTION.encode("utf-8")).hexdigest()
        self.assertEqual(err.splitlines()[-1], f"sha {expected_sha} (give it to collection edit or apply as --expect)")
        self.assertNotIn("PRIVATE_COLLECTION_NOTE", err)
        self.store.visibility.assert_called_once_with()

    def test_collection_redirected_csv_keeps_utf8_bytes_and_fresh_public_scope(self):
        self.collection_fixture()
        self.store.visibility.return_value = {("user2", "collection"): {}}
        output = SimpleNamespace(buffer=io.BytesIO(), flush=mock.Mock(), isatty=lambda: False)
        with redirect_stdout(output), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(inv_collection._list(self.args()), 0)
        self.assertEqual(output.buffer.getvalue(), COLLECTION.encode("utf-8"))
        self.assertIn("collection in space user2: collection Public switch enabled", err.getvalue())
        self.assertIn("when checked for this command", err.getvalue())

    def test_collection_notice_failure_preserves_successful_csv_and_existing_sha(self):
        self.collection_fixture()

        class NoticeRejectingStream(io.StringIO):
            def write(self, text):
                if text.startswith("Privacy:"):
                    raise BrokenPipeError("fixture notice rejection")
                return super().write(text)

        with redirect_stdout(io.StringIO()) as out, redirect_stderr(NoticeRejectingStream()) as err:
            self.assertEqual(inv_collection._list(self.args()), 0)
        self.assertEqual(out.getvalue(), COLLECTION)
        self.assertEqual(err.getvalue(), f"sha {hashlib.sha256(COLLECTION.encode('utf-8')).hexdigest()} (give it to collection edit or apply as --expect)\n")
