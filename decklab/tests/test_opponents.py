"""Usual-opponent metadata, reciprocal visibility, permissioned saves and API responses."""
import json
import unittest
from unittest import mock

from decklab.lib import access, api, config, decks, inventory
from decklab.lib.api import assembly, guard, opponents
from decklab.tests import db_support
from decklab.tests import test_api_permissions as permission_tests
from decklab.tests import test_collection_edit as collection_tests
from decklab.tests import test_collection_reduction_api as reduction_tests
from decklab.tests import test_editor as editor_tests
from decklab.tests import test_server as server_tests
from decklab.tests.test_api import Sandbox, _write
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, adapt, import_contents

OWN = "casual/table-test"
OTHER = "commander/elf-commander"
SECOND = "casual/gruul-test"
PAIR = "pairing/elves+cats"
FIELD = "- **Usual opponents:** "


def parsed(text):
    return decks.parse_deck(text.encode("utf-8"), "table-test", "casual")


class OpponentHeaderTests(unittest.TestCase):
    def test_reading_keeps_order_and_removes_duplicate_ids(self):
        self.assertEqual(decks.parse_usual_opponents(f" {OTHER}, {SECOND}, {OTHER}, "), [OTHER, SECOND])
        self.assertEqual(decks.parse_usual_opponents(None), [])

    def test_set_clear_and_no_op_change_only_this_header(self):
        before = editor_tests.TABLE_DECK
        deck = parsed(before)
        decks.set_usual_opponents(deck, [OTHER, SECOND])
        text = decks.render_deck_file(deck)
        expected = before.replace("- **Status:** building\n", "- **Status:** building\n" + FIELD + f"{OTHER}, {SECOND}\n")
        self.assertEqual(text, expected)
        same = parsed(text.replace(FIELD, "- **usual opponents**:   "))
        original = decks.render_deck_file(same)
        decks.set_usual_opponents(same, [OTHER, SECOND])
        self.assertEqual(decks.render_deck_file(same), original)
        decks.set_usual_opponents(deck, [])
        self.assertEqual(decks.render_deck_file(deck), before)

    def test_crlf_and_a_header_without_other_fields_are_preserved(self):
        before = editor_tests.TABLE_DECK.replace("\n", "\r\n")
        deck = parsed(before)
        decks.set_usual_opponents(deck, [OTHER])
        self.assertEqual(decks.render_deck_file(deck), before.replace(
            "- **Status:** building\r\n", "- **Status:** building\r\n" + FIELD + OTHER + "\r\n"))
        bare = "# Bare\n\n## Decklist\n\n```\nDeck\n1 Opt\n```\n"
        deck = parsed(bare)
        decks.set_usual_opponents(deck, [OTHER])
        self.assertEqual(decks.render_deck_file(deck), bare.replace("# Bare\n\n", "# Bare\n\n" + FIELD + OTHER + "\n\n"))

    def test_generic_header_and_table_updates_keep_the_line_verbatim(self):
        before = editor_tests.TABLE_DECK.replace("- **Status:** building\n",
                                               "- **Status:** building\n- **usual opponents**:  " + OTHER + " \n")
        deck = parsed(before)
        decks.apply_edit(deck, fields={"status": "built"})
        self.assertEqual(decks.render_deck_file(deck), before.replace("Status:** building", "Status:** built"))
        deck = parsed(before)
        decks.set_table(deck, deck.rows, deck.total)
        self.assertIn("- **usual opponents**:  " + OTHER + " \n", decks.render_deck_file(deck))

    def test_empty_or_duplicate_headers_are_removed_or_canonicalised(self):
        before = editor_tests.TABLE_DECK.replace("- **Status:** building\n", "- **Status:** building\n" + FIELD + "\n")
        deck = parsed(before)
        decks.set_usual_opponents(deck, [])
        self.assertEqual(decks.render_deck_file(deck), editor_tests.TABLE_DECK)
        before = before.replace(FIELD + "\n", FIELD + OTHER + "\n" + FIELD + SECOND + "\n")
        deck = parsed(before)
        decks.set_usual_opponents(deck, [SECOND])
        self.assertEqual(decks.render_deck_file(deck).count("**Usual opponents:**"), 1)

    def test_values_that_cannot_round_trip_in_one_header_are_refused(self):
        for value in ("abc", [None], [""], ["casual/a, casual/b"], ["casual/a\nnew line"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decks.set_usual_opponents(parsed(editor_tests.TABLE_DECK), value)


class OpponentApiTests(editor_tests.EditorTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(collection_tests.ROLES))
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", permission_tests.R_DECK)
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-other.md",
               permission_tests.R_DECK.replace("User2 Elves", "User2 Other"))
        patcher = mock.patch.object(config, "REPO", self.box.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def choose(self, ids, deck_id=OWN, profile="matt", sha256=None):
        sha256 = opponents.opponents_view(deck_id)["sha256"] if sha256 is None else sha256
        return opponents.save_opponents(self.body(profile, id=deck_id, sha256=sha256, opponents=ids))

    def ids(self, deck_id):
        return [item["id"] for item in opponents.usual_opponents(deck_id)]

    def test_choose_is_one_deck_save_and_does_not_touch_a_counterpart(self):
        before = self.deck_files()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.choose([OTHER, SECOND, OTHER])
        self.assertEqual(apply.call_count, 1)
        operation, actor, message = apply.call_args.args
        self.assertEqual((operation.kind, actor.id, message),
                         ("deck.save", "matt", "choose the usual opponents of Table Test"))
        after = self.deck_files()
        self.assertEqual([key for key in before if before[key] != after[key]], ["decks/casual/table-test.md"])
        self.assertTrue(answer["ok"] and answer["saved"])
        self.assertEqual(answer["sha256"], self.sha(OWN))
        self.assertEqual([item["id"] for item in answer["usual_opponents"]], [OTHER, SECOND])
        self.assertEqual(self.text(OWN), editor_tests.TABLE_DECK.replace(
            "- **Status:** building\n", "- **Status:** building\n" + FIELD + f"{OTHER}, {SECOND}\n"))

    def test_reciprocal_links_are_derived_without_a_second_declaration(self):
        self.choose([OTHER])
        self.assertEqual(self.ids(OTHER), [OWN])
        view = opponents.opponents_view(OTHER)
        self.assertEqual(view["opponents"], [])
        self.assertEqual(view["inherited"], [{"id": OWN, "title": "Table Test"}])
        self.assertNotIn("Usual opponents", self.text(OTHER))

    def test_no_op_has_no_audit_write_and_clear_removes_the_header(self):
        self.choose([OTHER])
        with mock.patch.object(inventory, "apply") as apply:
            answer = self.choose([OTHER])
        self.assertFalse(answer["saved"])
        apply.assert_not_called()
        self.assertEqual(self.choose([])["usual_opponents"], [])
        self.assertEqual(self.text(OWN), editor_tests.TABLE_DECK)

    def test_mutual_choices_are_explained_even_when_one_side_clears_its_choice(self):
        self.choose([OTHER])
        self.choose([OWN], deck_id=OTHER)
        self.assertEqual(opponents.opponents_view(OWN)["inherited"], [{"id": OTHER, "title": "Elf Commander"}])
        self.assertEqual([item["id"] for item in self.choose([])["usual_opponents"]], [OTHER])
        view = opponents.opponents_view(OWN)
        self.assertEqual(view["opponents"], [])
        self.assertEqual([item["id"] for item in view["inherited"]], [OTHER])

    def test_deck_detail_library_and_packing_share_the_reciprocal_ids(self):
        self.choose([OTHER])
        detail = api.deck_view(OWN, omit=("matchups",))
        self.assertEqual([item["id"] for item in detail["usual_opponents"]], [OTHER])
        index = {item["id"]: item for item in api.decks_index()["decks"]}
        self.assertEqual(index[OWN]["usual_opponents"], [OTHER])
        self.assertEqual(index[OTHER]["usual_opponents"], [OWN])
        plan = assembly.assembly_view()
        choices = {item["id"]: item for item in plan["choices"]}
        self.assertEqual(choices[OWN]["usual_opponents"], [OTHER])
        self.assertEqual(choices[OTHER]["usual_opponents"], [OWN])

    def test_linked_pairings_are_sparse_packing_choices_and_have_a_library_lookup(self):
        self.assertNotIn(PAIR, {item["id"] for item in assembly.assembly_view()["choices"]})
        self.choose(["pairing/cats+elves"])
        self.assertEqual(opponents.opponents_view(OWN)["opponents"], [PAIR])
        library = api.decks_index()
        self.assertEqual(library["usual_opponents"], {PAIR: [OWN]})
        self.assertNotIn(PAIR, {item["id"] for item in library["decks"]})
        plan = assembly.assembly_view()
        pairs = [item for item in plan["choices"] if item["id"].startswith("pairing/")]
        self.assertEqual([(item["id"], item["usual_opponents"]) for item in pairs], [(PAIR, [OWN])])
        self.assertEqual(plan["usual_opponents"], {PAIR: [OWN]})
        self.assertEqual(self.ids(PAIR), [OWN])

    def test_choices_include_complete_products_and_pairs_but_no_halves_or_self(self):
        choices = {item["id"] for item in opponents.opponents_view(OWN)["choices"]}
        self.assertIn("product/fdc-test-precon", choices)
        self.assertIn(PAIR, choices)
        self.assertNotIn("product/fdn-beginner-box/elves", choices)
        self.assertNotIn(OWN, choices)
        self.assertNotIn("user2/casual/r-elves", choices)
        self.assertNotIn("casual/broken", choices)

    def test_products_receive_reciprocal_links_but_cannot_be_edited(self):
        self.choose(["product/fdc-test-precon"])
        view = opponents.opponents_view("product/fdc-test-precon")
        self.assertFalse(view["editable"])
        self.assertIsNone(view["sha256"])
        self.assertEqual([item["id"] for item in view["inherited"]], [OWN])
        self.assertApiError(400, opponents.save_opponents,
                            self.body(id="product/fdc-test-precon", sha256="0" * 64, opponents=[OWN]))

    def test_person_spaces_have_only_their_own_choices_and_reciprocal_links(self):
        own, other = "user2/casual/r-elves", "user2/casual/r-other"
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.choose([other], deck_id=own, profile="user2")
            self.assertEqual(self.ids(other), [own])
            self.assertEqual({item["id"] for item in opponents.opponents_view(own)["choices"]}, {other})
            self.assertApiError(400, lambda: self.choose([OWN], deck_id=own, profile="user2"))
        self.assertEqual(self.ids(OWN), [])

    def test_hidden_endpoints_are_omitted_from_links_declarations_and_choices(self):
        self.choose([OTHER, SECOND])
        self.choose([OWN], deck_id=OTHER)
        with mock.patch.object(guard, "sees_deck", side_effect=lambda item, profile=False:
                               (item["id"] if isinstance(item, dict) else item) != OTHER):
            view = opponents.opponents_view(OWN)
            self.assertNotIn(OTHER, json.dumps(view))
            self.assertEqual(view["opponents"], [SECOND])
            self.assertEqual(self.ids(OWN), [SECOND])
            self.assertEqual(self.ids(OTHER), [])
            self.assertApiError(404, opponents.opponents_view, OTHER)
            self.assertApiError(400, lambda: self.choose([OTHER]))
            index = {item["id"]: item for item in api.decks_index()["decks"]}
            self.assertEqual(index[OWN]["usual_opponents"], [SECOND])
            self.assertNotIn(OTHER, index)          # a hidden deck isn't in the library at all (E10-S30)

    def test_a_visible_only_save_preserves_hidden_declarations_without_exposing_them(self):
        self.choose([OTHER, SECOND])
        with mock.patch.object(guard, "sees_deck", side_effect=lambda item, profile=False:
                               (item["id"] if isinstance(item, dict) else item) != OTHER):
            answer = self.choose([])
            self.assertNotIn(OTHER, json.dumps(answer))
            self.assertEqual(opponents.opponents_view(OWN)["opponents"], [])
        self.assertEqual(opponents.opponents_view(OWN)["opponents"], [OTHER])
        self.assertEqual(self.ids(SECOND), [])

    def test_deleted_opponents_and_deleted_declarers_never_leave_a_broken_link(self):
        self.choose([OTHER, SECOND])
        self.path(OTHER).unlink()
        self.assertEqual(opponents.opponents_view(OWN)["opponents"], [SECOND])
        self.assertEqual(self.ids(OWN), [SECOND])
        self.choose([SECOND])
        self.assertNotIn(OTHER, self.text(OWN))
        self.path(OWN).unlink()
        self.assertEqual(self.ids(SECOND), [])

    def test_metadata_reads_and_saves_do_not_require_card_data(self):
        with self.box.no_index():
            self.assertTrue(opponents.opponents_view(OWN)["editable"])
            self.assertTrue(self.choose([OTHER])["saved"])

    def test_stale_sha_and_a_race_at_apply_both_keep_the_current_text(self):
        stale = self.sha(OWN)
        self.choose([OTHER])
        error = self.assertApiError(409, lambda: self.choose([SECOND], sha256=stale))
        self.assertEqual(error.extra["conflict"]["reason"], "changed")
        current = self.text(OWN)
        real = inventory.apply

        def raced(*args, **kwargs):
            _write(self.path(OWN), current + "\nConcurrent fixture note.\n")
            return real(*args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=raced):
            self.assertApiError(409, lambda: self.choose([SECOND]))
        self.assertEqual(self.text(OWN), current + "\nConcurrent fixture note.\n")

    def test_an_opponent_deleted_during_save_is_omitted_from_the_saved_result(self):
        real = inventory.apply

        def raced(*args, **kwargs):
            self.path(OTHER).unlink()
            return real(*args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=raced):
            answer = self.choose([OTHER])
        self.assertTrue(answer["saved"])
        self.assertEqual(answer["usual_opponents"], [])
        self.assertEqual(self.ids(OWN), [])

    def test_invalid_choices_and_hashes_never_apply(self):
        for choices in (None, "casual/foo", [123], [OWN], ["casual/deleted"],
                        ["user2/casual/r-elves"], ["product/fdn-beginner-box/elves"], [OTHER] * 65):
            with self.subTest(choices=choices), mock.patch.object(inventory, "apply") as apply:
                self.assertApiError(400, lambda: self.choose(choices))
                apply.assert_not_called()
        for sha in (True, 123, "wrong", "g" * 64):
            with self.subTest(sha=sha):
                self.assertApiError(400, lambda: self.choose([OTHER], sha256=sha))

    def test_permission_is_checked_before_invalid_hash_or_choices(self):
        with access.using({"profile": "user1", "email": "", "remote": True}), \
                mock.patch.object(opponents, "_catalog", side_effect=AssertionError("permission first")):
            self.assertApiError(403, opponents.save_opponents,
                                self.body("user1", id=SECOND, sha256="bad", opponents=["not a deck"]))

    def test_one_may_choose_a_readable_opponent_without_editing_that_opponent(self):
        original = self.text(SECOND)
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertTrue(opponents.opponents_view(OTHER)["editable"])
            self.assertFalse(opponents.opponents_view(SECOND)["editable"])
            self.assertTrue(self.choose([SECOND], deck_id=OTHER, profile="user1")["saved"])
        self.assertEqual(self.text(SECOND), original)
        self.assertEqual(self.ids(SECOND), [OTHER])

    def test_generic_editor_save_and_table_refresh_keep_the_metadata(self):
        self.choose([OTHER])
        line = FIELD + OTHER + "\n"
        self.save(OWN, fields={"status": "idea"})
        self.assertIn(line, self.text(OWN))
        api.update_tables(self.body(decks=[{"id": OWN, "sha256": self.sha(OWN)}]))
        self.assertIn(line, self.text(OWN))


class OpponentHttpTests(server_tests.ServerTestCase):
    def test_the_same_path_serves_get_head_and_post(self):
        with mock.patch.object(opponents, "opponents_view", return_value={"read": True}) as read:
            self.assertEqual(self.get_json("/api/deck/opponents?id=casual%2Fgruul-test"), {"read": True})
            read.assert_called_once_with(deck_id=SECOND)
            code, _, body = self.request("HEAD", "/api/deck/opponents?id=casual%2Fgruul-test")
            self.assertEqual((code, body), (200, b""))
        body = b'{"profile":"matt","fixture":true}'
        with mock.patch.object(opponents, "save_opponents", return_value={"saved": True}) as save:
            answer = self.get_json("/api/deck/opponents", method="POST", body=body,
                                   headers=dict(server_tests.WRITE, Origin=f"http://127.0.0.1:{self.port}"))
            self.assertEqual(answer, {"saved": True})
            save.assert_called_once_with(body)

    def test_shared_route_keeps_query_method_and_write_origin_guards(self):
        with mock.patch.object(opponents, "save_opponents") as save:
            self.assertError("/api/deck/opponents?extra=yes", 400, method="POST", body=b"{}",
                             headers=dict(server_tests.WRITE, Origin=f"http://127.0.0.1:{self.port}"))
            self.assertError("/api/deck/opponents", 403, method="POST", body=b"{}",
                             headers={"Content-Type": "application/json"})
            self.assertError("/api/deck/opponents", 403, method="POST", body=b"{}",
                             headers=dict(server_tests.WRITE, Origin="http://untrusted.example"))
            save.assert_not_called()
        self.assertError("/api/deck/opponents?extra=yes", 400)
        self.assertError("/api/deck/opponents", 405, method="DELETE")


class PgOpponentTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        _write(self.box.root / "config.json", json.dumps(collection_tests.ROLES))
        reduction_tests.prepare(self.box)
        _write(self.box.magic / "decks" / "casual" / "table-test.md", editor_tests.TABLE_DECK)
        patcher = mock.patch.object(config, "REPO", self.box.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        pg.write_model(adapt(self.box.inventory.load()), CLAUDE, "Import opponent fixtures",
                       contents=import_contents(self.box.root), dbname=self.dbname, decks=True)
        self.addCleanup(inventory.use(pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())))

    def test_one_audit_change_and_one_own_revision_with_counterpart_unchanged(self):
        before = inventory.current()
        own, other = before.deck(OWN), before.deck(OTHER)
        with self.connect() as conn:
            count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        answer = opponents.save_opponents(json.dumps({"profile": "matt", "id": OWN, "sha256": own.sha256,
                                                      "opponents": [OTHER]}).encode("utf-8"))
        after = inventory.current()
        self.assertTrue(answer["saved"])
        self.assertEqual(after.deck(OWN).revision, own.revision + 1)
        self.assertEqual(after.deck(OTHER), other)
        self.assertEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)
            self.assertEqual(conn.execute("select actor, message from audit.change_set order by id desc limit 1").fetchone(),
                             ("matt", "choose the usual opponents of Table Test"))
        same = opponents.save_opponents(json.dumps({"profile": "matt", "id": OWN,
                                                    "sha256": after.deck(OWN).sha256, "opponents": [OTHER]}).encode("utf-8"))
        self.assertFalse(same["saved"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)
