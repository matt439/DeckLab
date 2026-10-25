"""Assembly completion saves only sandbox decks and confirms final reservations."""
import json
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import assembly, assembly_completion as completion, settings
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import ops_decks
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


PROFILES = [{"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user"},
            {"id": "user1", "name": "User1", "role": "member", "space": "home", "plays_as": "wife"},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2"}]
TABLE = "| Llanowar Elves | 1 | 0 | 1 | | | Keep this note |\n"


class AssemblyCompletionTests(PreparationCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))

    def request(self, *selected, profile="matt"):
        choices = [{"id": f"casual/{slug}", "version": version} for slug, version in selected]
        plan = assembly.assembly_preview(json.dumps({"profile": profile, "decks": choices}))
        return plan, {"profile": profile, "decks": choices, "confirmed": True,
                      "fingerprint": plan["completion"]["fingerprint"]}

    def mark(self, body):
        return completion.mark_built(json.dumps(body))

    def parsed(self, slug):
        return ops_decks.parsed_deck(inventory.current().deck(f"casual/{slug}"))

    def test_builds_selected_list_preserves_prose_printing_and_other_headers(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves (FDN) 227 *F*\n20 Forest\n",
                  owned="Deck\n4 Elvish Mystic\n20 Forest\n", table=TABLE)
        path = self.magic / "decks/casual/a.md"
        path.write_text(path.read_text().replace("- **Status:** building", "- **Status:** building\n"
                                                "- **Archetype:** Elves\n- **Sleeves:** green")
                        + "\n## Notes\n\nKeep this prose.\n", encoding="utf-8")
        before = self.parsed("a")
        plan, body = self.request(("a", "owned"))
        self.assertTrue(plan["completion"]["can_mark_built"])
        answer = self.mark(body)
        after = self.parsed("a")
        self.assertEqual((after.status, after.built_version, after.sleeves), ("built", "owned", "green"))
        self.assertEqual(after.target, before.target)
        self.assertEqual(after.owned, before.owned)
        self.assertIn("Keep this prose.", after.text)
        self.assertEqual(after.get_field("Archetype"), "Elves")
        self.assertIsNone(after.changed_on)
        self.assertTrue(answer["plan"]["decks"][0]["completion"]["already_built"])
        self.assertEqual(answer["plan"]["completion"]["decks"], [])
        self.assertIsNone(answer["tables"]["error"])

    def test_mutual_transfers_are_one_operation_and_tables_use_final_pool(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n", owned="Deck\n4 Elvish Mystic\n",
                  built_version="owned-only", table=TABLE)
        self.deck("b", "B", "built", "Deck\n4 Elvish Mystic\n", owned="Deck\n4 Llanowar Elves\n",
                  built_version="owned-only", table=TABLE)
        plan, body = self.request(("a", "target"), ("b", "target"))
        self.assertEqual(plan["totals"]["transfers"], 8)
        self.assertTrue(plan["ready"])
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            answer = self.mark(body)
        self.assertEqual(apply.call_count, 1)
        self.assertEqual([self.parsed(s).built_version for s in ("a", "b")], ["target", "target"])
        self.assertEqual({item["id"] for item in answer["tables"]["written"]}, {"casual/a", "casual/b"})
        self.assertFalse(pool.load_pool().warnings)
        self.assertIsNone(answer["tables"]["error"])

    def test_single_list_has_no_unnecessary_built_version_and_repeat_does_not_write(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", table=TABLE)
        _, body = self.request(("a", "target"))
        self.mark(body)
        self.assertIsNone(self.parsed("a").built_version)
        _, again = self.request(("a", "target"))
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            with self.assertRaises(ApiError) as caught:
                self.mark(again)
        self.assertEqual(caught.exception.status, 409)
        apply.assert_not_called()

    def test_unchecked_missing_incoming_and_unconfirmed_plans_cannot_finish(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", table=TABLE)
        _, body = self.request(("a", "target"))
        with self.assertRaises(ApiError) as caught:
            self.mark({**body, "confirmed": False})
        self.assertEqual(caught.exception.status, 400)
        for mode in ("missing", "incoming", "unconfirmed"):
            with self.subTest(mode=mode):
                self.cards_csv("collection.csv")
                if mode == "incoming":
                    self.cards_csv("orders/arrival.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
                elif mode == "unconfirmed":
                    self.cards_csv("collection.csv", ("Unknown Card", "bad", "1", "nonfoil", 1))
                plan, request = self.request(("a", "target"))
                self.assertFalse(plan["completion"]["can_mark_built"])
                with self.assertRaises(ApiError) as refused:
                    self.mark(request)
                self.assertEqual(refused.exception.status, 409)
                self.assertEqual(self.parsed("a").status, "building")

    def test_stale_deck_pool_and_selected_version_are_refused(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", owned="Deck\n4 Elvish Mystic\n",
                  table=TABLE)
        _, body = self.request(("a", "target"))
        for change in ("version", "deck", "pool"):
            with self.subTest(change=change):
                if change == "version":
                    request = {**body, "decks": [{"id": "casual/a", "version": "owned"}]}
                else:
                    request = body
                    if change == "deck":
                        self.deck("a", "Renamed", "building", "Deck\n3 Llanowar Elves\n", table=TABLE)
                    else:
                        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 3))
                with self.assertRaises(ApiError) as caught:
                    self.mark(request)
                self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.parsed("a").status, "building")

    def test_permissions_apply_to_every_changed_deck_and_inventory_reader(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n", table=TABLE)
        for who in ("user1", "user2"):
            with self.subTest(who=who):
                _, request = self.request(("a", "target"))
                with self.assertRaises(ApiError) as caught:
                    self.mark({**request, "profile": who})
                self.assertEqual(caught.exception.status, 403)
        plan, _ = self.request(("a", "target"), profile="user1")
        self.assertFalse(plan["completion"]["can_mark_built"])
        self.assertFalse(plan["decks"][0]["completion"]["editable"])

    def test_lock_checks_inventory_and_separate_database_deck_revisions(self):
        snapshot = inventory.current()
        op = completion._BuildPlan(snapshot, [])
        for changed in (snapshot.replace(revision=snapshot.revision + "new"),
                        snapshot.replace(decks_revision=snapshot.decks_revision + "new")):
            with self.subTest(revision=changed.revision), self.assertRaises(inventory.Conflict):
                op.run(changed)

    def test_race_after_validation_does_not_save_any_participant(self):
        for slug in ("a", "b"):
            self.deck(slug, slug.upper(), "building", "Deck\n2 Llanowar Elves\n", table=TABLE)
        _, body = self.request(("a", "target"), ("b", "target"))
        apply = self.inventory.apply

        def race(*args, **kwargs):
            self.deck("elsewhere", "Elsewhere", "built", "Deck\n4 Llanowar Elves\n", table=TABLE)
            return apply(*args, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=race), self.assertRaises(ApiError) as caught:
            self.mark(body)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual([self.parsed(s).status for s in ("a", "b")], ["building", "building"])

    def test_products_are_read_only_and_optional_tokens_do_not_block(self):
        self.product("test.csv", ("Deck", "Llanowar Elves", 1), column="section")
        self.status(("test.csv", "owned", "yes"))
        self.deck("a", "A", "building", "Deck\n3 Llanowar Elves\n", table=TABLE)
        choices = [{"id": "product/test", "version": "target"}, {"id": "casual/a", "version": "target"}]
        with mock.patch.object(assembly, "_deck_tokens", return_value={"unavailable": "Not available"}):
            plan = assembly.assembly_preview(json.dumps({"profile": "matt", "decks": choices}))
            self.assertFalse(plan["decks"][0]["completion"]["editable"])
            self.assertEqual([d["id"] for d in plan["completion"]["decks"]], ["casual/a"])
            answer = self.mark({"profile": "matt", "decks": choices, "confirmed": True,
                                "fingerprint": plan["completion"]["fingerprint"]})
        self.assertEqual([item["id"] for item in answer["built"]], ["casual/a"])
        self.assertEqual(self.parsed("a").status, "built")
