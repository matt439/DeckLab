"""E10-S28 collection/game readers, through real switches over isolated API fixtures.

No visibility setting, inventory or game in the live database is touched.
"""
import copy
import json
import subprocess
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import access, api, decks, permissions, pool, state
from decklab.lib.api import activity, assembly, card_lookup, collection, collection_edit as ce, commits
from decklab.lib.api import deck_page, drafts, editor, guard, inventory_views, play_records as play, precons, settings
from decklab.lib.api import library
from decklab.lib.api import tokens as api_tokens
from decklab.lib.api import receipts
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import CollectionEditTestCase, USER2
from decklab.tests.test_inventory_privacy import CARD, R_BUILT
from decklab.tests.test_play_records import MixedFixture, encoded
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER

ACTOR = state.Actor("test", "a test", source="test")


def publish(store, owner, thing):
    store.visibility_set(owner, thing, True, ACTOR, "Make fixture public")


class PublicRuleTests(unittest.TestCase):
    def test_collection_and_games_public_readers_do_not_gain_write_rights(self):
        viewer = {"id": "matt", "role": "admin", "space": "home"}
        for profile in (viewer, {"id": "user3", "space": "user3"}, None):
            self.assertTrue(permissions.sees_inventory(profile, "user2", public={"user2"}))
            self.assertTrue(permissions.sees_play_record(profile, ["user2/casual/a"], public={"user2"}))
            self.assertFalse(permissions.sees_inventory(profile, "user2"))
            self.assertFalse(permissions.sees_play_record(profile, ["user2/casual/a"]))
            self.assertFalse(permissions.can(profile, "collection.edit", "user2"))
            self.assertFalse(permissions.can(profile, "tokens.edit", "user2"))
        self.assertEqual(permissions.inventory_spaces(viewer, public={"user2"}), ["home", "user2"])
        self.assertIsNone(permissions.inventory_spaces(None, script=True, public={"user2"}))


class PublicCollectionTests(CollectionEditTestCase):
    def test_public_collection_is_read_only_for_admins_and_members(self):
        publish(self.box.state, "user2", "collection")
        before = self.magic_files()
        for who in ("matt", "user3"):
            with self.as_(who):
                self.assertFalse(collection.collection_view(space="user2")["editable"])
                self.assertFalse(ce.rows_view("user2")["editable"])
                self.assertEqual(api_tokens.tokens_view("user2")["space"], "user2")
                refusals = [
                    lambda: self.call(ce.save_card, who, space="user2", action="add", sha256="0" * 64, row=CARD),
                    lambda: self.call(ce.import_preview, who, space="user2", filename="cards.csv", text=USER2),
                    lambda: self.call(ce.import_apply, who, space="user2", token="bad", sha256="0" * 64),
                    lambda: self.call(api_tokens.save_token, who, space="user2", action="add", sha256="0" * 64,
                                      row={"front": "Treasure", "quantity": 1}),
                    lambda: self.call(precons.add_precon, who, space="user2", file="missing", title="Example",
                                      sha256="0" * 64),
                    lambda: precons.precon_preview("missing", "user2"),
                ]
                for call in refusals:
                    self.assertEqual(self.assertApiError(403, call).extra, {})
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_home_public_collection_keeps_records_private_and_holders_anonymous(self):
        publish(self.box.state, "home", "collection")
        _write(self.box.magic / "decks/casual/private.md", R_BUILT.replace("User2's Elves", "Secret home deck"))
        with self.as_("user2"):
            answer = collection.collection_view(space="home")
            self.assertFalse(answer["editable"])
            self.assertEqual([s["id"] for s in answer["spaces"]], ["home", "user2"])
            holders = next(row["holders"] for row in answer["cards"] if row["name"] == "Llanowar Elves")
            self.assertEqual(holders, [{"id": None, "title": "one of the home decks", "quantity": 4}])
            for call in (api.shopping_overview, receipts.receipt_view, assembly.assembly_view):
                self.assertEqual(self.assertApiError(403, call).extra, {})
            self.assertFalse(guard.sees_home_records())
            self.assertFalse(guard.sees_deck("casual/private"))
        self.assertNotIn("Secret home deck", json.dumps(answer))

    def test_public_tokens_never_read_home_pending_orders(self):
        publish(self.box.state, "home", "collection")
        with self.as_("user2"), mock.patch.object(api_tokens.tokens, "incoming", side_effect=AssertionError("private")):
            answer = api_tokens.tokens_view("home")
            self.assertEqual(answer["incoming"], [])
            deck_page._token_pool("home")

    def test_unreadable_home_orders_do_not_name_their_files_in_public_errors(self):
        publish(self.box.state, "home", "collection")
        with self.as_("user2"), mock.patch.object(pool, "load_pool", side_effect=ValueError("magic/orders/secret.csv: bad")):
            error = self.assertApiError(409, collection.collection_view, space="home")
            self.assertNotIn("secret", error.message)
            warnings = []
            self.assertIsNone(library._load_pool(warnings))
            self.assertNotIn("secret", " ".join(warnings))

    def test_visibility_changes_take_effect_without_widening_activity(self):
        with self.as_("matt"):
            self.assertApiError(403, collection.collection_view, space="user2")
        publish(self.box.state, "user2", "collection")
        with self.as_("matt"):
            self.assertFalse(collection.collection_view(space="user2")["editable"])
            self.assertEqual(activity.activity_view()["changes"], [])
        self.box.state.visibility_set("user2", "collection", False, ACTOR, "Make fixture private")
        with self.as_("matt"):
            self.assertApiError(403, collection.collection_view, space="user2")

    def test_public_collections_do_not_change_own_printing_counts_or_defaults(self):
        publish(self.box.state, "home", "collection")
        publish(self.box.state, "user2", "collection")
        with self.as_("user3"), mock.patch.object(pool, "printing_counts", side_effect=lambda space="home": {space: 1}):
            self.assertEqual(card_lookup._pool_counts(), {"user3": 1})
            self.assertEqual(drafts._visible_counts("user3"), {"user3": 1})

    def test_roster_uses_collection_games_and_accessories_switches(self):
        for thing, owner, profile_id in (("collection", "user2", "user2"), ("games", "user2", "user2"),
                                         ("accessories", "user1", "user1")):
            publish(self.box.state, owner, thing)
            with self.as_("user3"):
                answer = settings.profiles()["profiles"]
                self.assertIn({"id": profile_id, "name": "User1" if profile_id == "user1" else "User2"}, answer)
                self.assertTrue(all(set(p) == {"id", "name"} for p in answer if p["id"] != "user3"))
            self.box.state.visibility_set(owner, thing, False, ACTOR, "Make fixture private")


class PublicPoolProjectionTests(CollectionEditTestCase):
    def pool(self):
        return pool.Pool(Counter({"Llanowar Elves": 5}),
            {"Llanowar Elves": [("Secret product", 1), ("order hidden-id", 1)]},
            [pool.InUse("casual/a", "Secret deck", "built", Counter({"Llanowar Elves": 2})),
             pool.InUse("product/secret", "Secret product", "intact", Counter({"Llanowar Elves": 1}))],
            unresolved={"Secret unknown": {"magic/orders/hidden-id.csv"}},
            warnings=["magic/orders/hidden-id.csv: bad"],
            incoming_sources={"Llanowar Elves": [
                {"source": "Secret product", "quantity": 1, "product_id": "secret", "order_id": "hidden-id"},
                {"source": "order hidden-id", "quantity": 1, "order_id": "hidden-id"}]})

    def result(self, p):
        return card_lookup._owned_json(pool.compare({"Deck": [decks.DeckLine(5, "Llanowar Elves")]}, p, prices=False), p)

    def test_owned_rows_conflicts_warnings_and_raw_sources_are_redacted(self):
        p = self.pool()
        with self.as_("user2"):
            answer = self.result(p)
        row = answer["rows"][0]
        self.assertEqual(row["on_the_way"], 2)
        self.assertEqual(row["on_the_way_from"], [[None, 2]])
        self.assertEqual(row["labels"]["on_the_way"], [[None, 2]])
        self.assertEqual(row["labels"]["incoming_sources"], [{"quantity": 2}])
        self.assertEqual(row["in_use_elsewhere"], [["one of the home decks", 3]])
        self.assertEqual(answer["conflicts"][0]["decks"], [["one of the home decks", 3]])
        for private in ("Secret", "hidden-id", "magic/orders", "product/secret"):
            self.assertNotIn(private, json.dumps(answer))
        # The compared pool stays whole for its owner's next answer.
        self.assertIn("Secret product", json.dumps(self.result(p)))

    def test_published_decks_still_do_not_publish_product_source_labels(self):
        publish(self.box.state, "home", "decks")
        with self.as_("user2"):
            answer = self.result(self.pool())
        self.assertEqual(answer["rows"][0]["in_use_elsewhere"],
                         [["Secret deck", 2], ["one of the home decks", 1]])
        self.assertNotIn("Secret product", json.dumps(answer))
        with self.as_("user2"):
            holder = collection._holder(self.pool().in_use[1], 1, guard.deck_reader())
            self.assertIsNone(holder["id"])
            self.assertNotIn("Secret product", json.dumps(holder))
            use = {"deck": "product/fdn-beginner-box", "title": "Secret product", "link": "product/fdn-beginner-box"}
            self.assertIsNone(api_tokens._seen_use(use, guard.deck_reader())["deck"])
            gap = {"decks": [{"id": "product/fdn-beginner-box", "title": "Secret product", "link": None}]}
            self.assertIsNone(api_tokens._seen_gap(gap, guard.deck_reader())["decks"][0]["id"])

    def test_api_deck_and_draft_paths_pass_the_compared_pool_for_redaction(self):
        publish(self.box.state, "home", "collection")
        publish(self.box.state, "home", "decks")
        p = self.pool()
        with self.as_("user2"), mock.patch.object(deck_page, "_load_pool", return_value=p):
            answer = deck_page.deck_view("casual/gruul-test", omit=("matchups",))
        self.assertIn("owned", answer)
        for secret in ("Secret product", "hidden-id", "magic/orders"):
            self.assertNotIn(secret, json.dumps(answer["owned"]))
        elves = next(row for row in answer["owned"]["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual(elves["on_the_way_from"], [[None, 2]])
        with self.as_("user2"), mock.patch.object(editor, "_load_pool", return_value=p):
            draft = editor.check_draft(encoded({"profile": "user2", "id": "casual/gruul-test"}))
        self.assertIsNotNone(draft["owned"])
        for secret in ("Secret product", "hidden-id", "magic/orders"):
            self.assertNotIn(secret, json.dumps(draft["availability"]))

    def test_saved_table_and_stale_table_labels_are_private(self):
        changes = [{"card": "Llanowar Elves", "was": {"owned": 1, "labels": ["order hidden-id"]},
                    "now": {"owned": 2, "labels": ["Secret product"]}}]
        original = copy.deepcopy(changes)
        with self.as_("user2"):
            shown = inventory_views.table_changes(changes, "home")
        self.assertEqual(shown[0]["was"], {"owned": 1, "labels": []})
        self.assertEqual(shown[0]["now"], {"owned": 2, "labels": []})
        self.assertEqual(changes, original)
        publish(self.box.state, "home", "decks")
        publish(self.box.state, "home", "collection")
        path = self.box.magic / "decks/casual/private.md"
        _write(path, R_BUILT.replace("User2's Elves", "Example deck"))
        deck = decks.read_deck_file(path)
        with self.as_("user2"), mock.patch.object(pool, "table_changes", return_value=changes), \
                mock.patch.object(pool, "stale_tables", return_value=[{"id": "casual/private", "changes": changes}]):
            self.assertEqual(commits._table_json(deck, self.pool())["changes"], shown)
            stale = commits._stale_list(self.pool())
            self.assertEqual(stale[0]["changes"], shown)
            self.assertFalse(stale[0]["may_update"])


class PublicGameTests(MixedFixture, ApiTestCase):
    def test_games_publication_is_independent_from_decks_and_sideboard_plans(self):
        publish(self.box.state, "user2", "games")
        with access.viewing("matt"):
            games, plans, answer = self.seen()
        self.assertEqual(games, {self.home, self.mixed, self.members_game})
        self.assertEqual(plans, {self.home_plan})
        public = next(entry for entry in answer["games"] if entry["record"]["id"] == self.members_game)
        self.assertTrue(all(side["hidden"] and "sections" not in side for side in public["record"]["sides"]))
        self.assertEqual(public["can"], {"sides": [False, False], "result": False})
        self.assertEqual(public["record"]["updated_by"], "someone")
        self.assertNotIn("User2 Elves", json.dumps(public))
        self.assertNotIn("User3 Elves", json.dumps(public))
        self.assertNotIn("A private note.", json.dumps(public))

    def test_public_game_is_read_only_before_its_sha_is_checked(self):
        publish(self.box.state, "user2", "games")
        record = self.box.state.play_get("games", self.members_game)
        payload = {"profile": "matt", "id": self.members_game, "sha256": "0" * 64, "preview": True,
                   **{key: record[key] for key in ("date", "sides", "result", "notes")}}
        before = self.box.state.changes()
        with access.viewing("matt"):
            self.assertApiError(403, lambda: play.save_game(encoded(payload)))
        self.assertEqual(self.box.state.changes(), before)

    def test_home_page_naming_nobody_gets_only_public_games(self):
        publish(self.box.state, "user2", "games")
        with access.answering(False), access.viewing(None):
            games, plans, answer = self.seen()
        self.assertEqual(games, {self.mixed, self.members_game})
        self.assertEqual(plans, set())
        self.assertEqual(answer["lists"], [])
        self.assertTrue(all(entry["record"] is not None for entry in answer["games"]))


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PublicIncomingUiTests(unittest.TestCase):
    def test_anonymous_incoming_counts_have_no_dangling_source_words(self):
        code = """
          const row = {labels:{on_the_way:[[null,2]],in_use:[],incoming_sources:[{quantity:2}]}};
          assert.equal(incomingSourceChip({quantity:2}).textContent, '2 on the way');
          assert.equal(incomingBannerSources({rows:[row]}).textContent, 'On the way: 2');
          assert.equal(incomingSourceChip({quantity:1,source:'Example order'}).textContent,
            '1 on the way · Example order');
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
