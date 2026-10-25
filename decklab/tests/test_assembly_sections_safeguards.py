"""Scoped physical builds remain atomic and keep full deck intent, using temp fixtures only."""
from collections import Counter
import json
from unittest import mock

from decklab.lib import decks, inventory, pool, state
from decklab.lib.api import (assembly, assembly_completion as completion, assembly_intent,
                             assembly_standins, saving, settings)
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled, standins
from decklab.lib.inventory import ops_decks
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_assembly_completion import PROFILES, TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


FULL = object()
MAIN = "Deck\n4 Llanowar Elves\n20 Forest\n"
INTENDED = MAIN + "\nSideboard\n3 Elvish Mystic\n"


class AssemblySectionsSafeguardsTests(PreparationCase):
    def setUp(self):
        super().setUp()
        self.store = MemoryStore()
        self.addCleanup(state.use(self.store))
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        self.deck("a", "A", "building", INTENDED, table=TABLE)

    def parsed(self, slug="a"):
        return ops_decks.parsed_deck(inventory.current().deck(f"casual/{slug}"))

    def choice(self, slug="a", sideboard=FULL, version="target"):
        result = {"id": f"casual/{slug}", "version": version}
        if sideboard is not FULL:
            result["sideboard"] = sideboard
        return result

    def request(self, *choices, profile="matt"):
        selected = list(choices) or [self.choice(sideboard={})]
        plan = assembly.assembly_preview(json.dumps({"profile": profile, "decks": selected}))
        return plan, {"profile": profile, "decks": selected, "confirmed": True,
                      "fingerprint": plan["completion"]["fingerprint"]}

    def mark(self, body):
        return completion.mark_built(json.dumps(body))

    def save(self, *, slug="a", **changes):
        record = inventory.current().deck(f"casual/{slug}")
        return saving.save_deck(json.dumps({"profile": "matt", "id": record.id,
                                            "sha256": record.sha256, **changes}))

    def held(self):
        return {item.id: item.cards for item in pool.load_pool().in_use}

    def refused(self, status, body):
        with self.assertRaises(ApiError) as caught:
            self.mark(body)
        self.assertEqual(caught.exception.status, status)

    def test_missing_sideboard_does_not_block_main_but_default_whole_build_still_waits(self):
        full, _ = self.request(self.choice())
        self.assertFalse(full["ready"])
        plan, body = self.request()
        self.assertTrue(plan["ready"])
        self.assertTrue(plan["completion"]["can_mark_built"])
        before = self.parsed()
        answer = self.mark(body)
        deck = self.parsed()
        self.assertEqual((deck.status, deck.target, deck.owned), ("built", before.target, before.owned))
        self.assertEqual(assembled.sections(deck), decks.parse_decklist(MAIN))
        self.assertEqual(self.held(), {"casual/a": Counter({"Llanowar Elves": 4})})
        self.assertEqual(answer["plan"]["decks"][0]["build_scope"]["sideboard_count"], 0)
        self.assertIsNone(answer["tables"]["error"])

    def test_empty_main_is_refused_as_an_input_error_without_a_partial_write(self):
        self.deck("a", "A", "building", "Sideboard\n1 Elvish Mystic\n", table=TABLE)
        _, body = self.request()
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            self.refused(400, body)
            apply.assert_not_called()
        self.assertEqual(self.parsed().status, "building")

    def test_partial_sideboard_reserves_only_selected_copies_and_retains_unselected_intent(self):
        before = self.parsed()
        plan, body = self.request(self.choice(sideboard={"Elvish Mystic": 1}))
        self.assertTrue(plan["ready"])
        self.mark(body)
        deck = self.parsed()
        self.assertEqual(deck.target, before.target)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4, "Elvish Mystic": 1}))
        intent = assembly_intent.project(deck, pool.load_pool())
        row = next(item for item in intent["remaining"] if item["name"] == "Elvish Mystic")
        self.assertEqual((row["intended"], row["assembled"], row["remaining"], row["missing"]), (3, 1, 2, 2))
        _, again = self.request(self.choice(sideboard={"Elvish Mystic": 1}))
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            self.refused(409, again)
            apply.assert_not_called()

    def test_owned_omitted_cards_are_unassembled_without_becoming_purchases_or_wishlist_entries(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 3))
        self.write("watchlist.csv", "name,set,collector_number,finish,quantity,for,printing,listed_aud,"
                   "listed_at,in_stock,checked,notes,state,source\n")
        self.store.seed_wishlist("user1", [{"name": "Pick Your Poison", "set": "", "number": "",
                                            "notes": "Private fixture intent", "source": ""}])
        before_queue = (self.magic / "watchlist.csv").read_bytes()
        before_wishes = self.store.wishlist("user1")
        _, body = self.request()
        self.mark(body)
        intent = assembly_intent.project(self.parsed(), pool.load_pool())
        row = next(item for item in intent["remaining"] if item["name"] == "Elvish Mystic")
        self.assertEqual((row["remaining"], row["missing"], row["on_the_way"]), (3, 0, 0))
        self.assertEqual((self.magic / "watchlist.csv").read_bytes(), before_queue)
        self.assertEqual(self.store.wishlist("user1"), before_wishes)
        self.assertEqual(self.store.activity()["changes"], [])

    def test_main_and_sideboard_copies_of_the_same_card_are_counted_once_each(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 3))
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves\n20 Forest\n\nSideboard\n3 Llanowar Elves\n",
                  table=TABLE)
        plan, body = self.request(self.choice(sideboard={"Llanowar Elves": 1}))
        self.assertEqual((plan["totals"]["need"], plan["totals"]["from_storage"]), (3, 3))
        self.mark(body)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 3}))
        intent = assembly_intent.project(self.parsed(), pool.load_pool())
        self.assertEqual([(row["section"], row["remaining"], row["missing"]) for row in intent["remaining"]],
                         [("Sideboard", 2, 2)])

    def test_selected_incoming_copies_never_complete_a_build_but_omitted_incoming_does_not_block(self):
        self.cards_csv("orders/arrival.csv", ("Elvish Mystic", "m15", "173", "nonfoil", 1))
        plan, body = self.request(self.choice(sideboard={"Elvish Mystic": 2}))
        self.assertFalse(plan["ready"])
        self.assertEqual(plan["totals"]["waiting"], 1)
        self.refused(409, body)
        plan, body = self.request()
        self.assertTrue(plan["ready"])
        self.mark(body)
        self.assertNotIn("Elvish Mystic", self.held()["casual/a"])

    def test_sideboard_scope_cannot_omit_missing_main_cards_or_final_confirmation(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 3))
        plan, body = self.request()
        self.assertFalse(plan["ready"])
        self.refused(409, body)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        _, body = self.request()
        self.refused(400, dict(body, confirmed=False))
        self.assertEqual(self.parsed().status, "building")

    def test_bad_sideboard_quantities_and_names_are_refused_without_writes(self):
        invalid = [None, [], True, {"Unknown Card": 1}, {"Llanowar Elves": 1},
                   {"Elvish Mystic": True}, {"Elvish Mystic": -1}, {"Elvish Mystic": 4},
                   {"Elvish Mystic": "1"}, {"Elvish Mystic": 1.5}]
        for selected in invalid:
            with self.subTest(selected=selected), mock.patch.object(self.inventory, "apply") as apply:
                with self.assertRaises(ApiError) as caught:
                    self.request(self.choice(sideboard=selected))
                self.assertEqual(caught.exception.status, 400)
                apply.assert_not_called()

    def test_changing_only_scope_invalidates_the_final_confirmation(self):
        _, body = self.request()
        self.refused(409, dict(body, decks=[self.choice(sideboard={"Elvish Mystic": 1})]))
        self.assertEqual(self.parsed().status, "building")

    def test_partial_build_permissions_apply_to_every_changed_participant(self):
        _, body = self.request()
        for profile in ("user1", "user2"):
            with self.subTest(profile=profile):
                self.refused(403, dict(body, profile=profile))
        self.assertEqual(self.parsed().status, "building")

    def test_removing_previously_assembled_sideboard_requires_explicit_return_tasks(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 3))
        self.deck("a", "A", "built", INTENDED, table=TABLE)
        plan, body = self.request()
        self.assertTrue(plan["completion"]["can_mark_built"])
        self.assertEqual(plan["decks"][0]["returns"], [{"name": "Elvish Mystic", "quantity": 3}])
        self.assertEqual(plan["decks"][0]["build_scope"]["return_count"], 3)
        self.mark(body)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))
        self.assertEqual(sum(line.quantity for line in self.parsed().target["Sideboard"]), 3)

    def test_omitted_sideboard_basics_also_have_physical_return_tasks(self):
        self.deck("a", "A", "built", MAIN + "\nSideboard\n2 Island\n", table=TABLE)
        plan, _ = self.request()
        self.assertEqual(plan["decks"][0]["returns"], [{"name": "Island", "quantity": 2}])
        self.assertEqual(plan["decks"][0]["build_scope"]["return_count"], 2)

    def test_sideboard_releases_can_transfer_atomically_to_another_selected_main(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 3))
        self.deck("a", "A", "built", INTENDED, table=TABLE)
        self.deck("b", "B", "building", "Deck\n3 Elvish Mystic\n20 Forest\n", table=TABLE)
        plan, body = self.request(self.choice(sideboard={}), self.choice("b", sideboard={}))
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["totals"]["transfers"], 3)
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            self.mark(body)
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(self.held(), {"casual/a": Counter({"Llanowar Elves": 4}),
                                      "casual/b": Counter({"Elvish Mystic": 3})})
        self.assertFalse(pool.load_pool().warnings)

    def test_racing_inventory_reservation_rolls_back_all_scoped_participants(self):
        self.deck("b", "B", "building", "Deck\n1 Elvish Mystic\n20 Forest\n", table=TABLE)
        _, body = self.request(self.choice(sideboard={}), self.choice("b", sideboard={}))
        real_apply = self.inventory.apply

        def raced(*args, **kwargs):
            self.deck("other", "Other", "built", MAIN, table=TABLE)
            return real_apply(*args, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=raced):
            self.refused(409, body)
        self.assertEqual([self.parsed(slug).status for slug in ("a", "b")], ["building", "building"])
        self.assertIsNone(assembled.get(self.parsed()))
        self.assertIsNone(assembled.get(self.parsed("b")))

    def test_list_edits_do_not_change_reserved_physical_copies_until_repacking(self):
        _, body = self.request()
        self.mark(body)
        before = assembled.get(self.parsed())
        self.save(lists={"target": {"Deck": [{"name": "Elvish Mystic", "qty": 1},
                                               {"name": "Forest", "qty": 20}]}})
        self.assertEqual(assembled.get(self.parsed()), before)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))
        plan, body = self.request()
        self.assertTrue(plan["completion"]["can_mark_built"])
        self.assertEqual(plan["decks"][0]["returns"], [{"name": "Llanowar Elves", "quantity": 4}])
        self.mark(body)
        self.assertEqual(self.held()["casual/a"], Counter({"Elvish Mystic": 1}))

    def test_take_apart_clears_only_physical_state_and_rebuild_installs_a_new_generation(self):
        _, body = self.request(self.choice(sideboard={"Elvish Mystic": 1}))
        self.mark(body)
        before = self.parsed()
        first_key = assembled.key(before)
        self.save(fields={"status": "building"})
        after = self.parsed()
        self.assertEqual((after.target, after.owned), (before.target, before.owned))
        self.assertIsNone(assembled.get(after))
        self.assertIsNone(standins.installed_for(after))
        self.assertEqual(self.held(), {})
        self.assertNotEqual(assembled.key(after), first_key)
        plan, body = self.request()
        self.assertTrue(plan["ready"])
        self.mark(body)
        self.assertNotEqual(assembled.key(self.parsed()), first_key)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))

    def test_legacy_take_apart_also_invalidates_old_packing_task_generation(self):
        self.deck("a", "A", "built", MAIN, table=TABLE)
        self.assertIsNone(assembled.key(self.parsed()))
        self.save(fields={"status": "building"})
        self.assertIsNotNone(assembled.key(self.parsed()))
        self.assertEqual(self.held(), {})

    def test_editing_a_legacy_built_list_first_freezes_its_existing_physical_cards(self):
        self.deck("a", "A", "built", MAIN, table=TABLE)
        self.assertIsNone(assembled.get(self.parsed()))
        self.save(lists={"target": {"Deck": [{"name": "Elvish Mystic", "qty": 1},
                                               {"name": "Forest", "qty": 20}]}})
        self.assertEqual(assembled.sections(self.parsed()), decks.parse_decklist(MAIN))
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))
        self.assertEqual(self.parsed().target["Deck"][0].name, "Elvish Mystic")

    def test_old_text_save_cannot_remove_or_replace_an_explicit_physical_snapshot(self):
        _, body = self.request()
        self.mark(body)
        record = inventory.current().deck("casual/a")
        for replacement in (None, decks.parse_decklist("Deck\n1 Elvish Mystic\n20 Forest\n")):
            deck = self.parsed()
            if replacement is None:
                deck.header[:] = [field for field in deck.header if field.key != assembled.FIELD]
            else:
                assembled.install(deck, "target", replacement)
            operation = inventory.Op("deck.save", {"deck_id": record.id, "base_sha256": record.sha256,
                                                   "text": decks.render_deck_file(deck)})
            with self.subTest(replacement=replacement), self.assertRaises(inventory.Conflict):
                inventory.preview(operation)
        self.assertEqual(inventory.current().deck("casual/a").text, record.text)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))

    def test_anonymous_installed_sideboard_markers_have_required_return_tasks_and_keep_desired_choices(self):
        self.deck("a", "A", "built", INTENDED, table=TABLE)
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        rows = [{"for": "Elvish Mystic", "using": None, "qty": 3}]
        standins.install_stand_ins(deck, "target", rows)
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        plan, body = self.request()
        returns = plan["decks"][0]["returns"]
        self.assertEqual(sum(row["quantity"] for row in returns), 3)
        self.assertIn("Elvish Mystic", json.dumps(returns))
        self.assertEqual(plan["decks"][0]["build_scope"]["return_count"], 3)
        self.mark(body)
        self.assertIsNone(standins.installed_for(self.parsed()))
        self.assertEqual(standins.choices_for(self.parsed(), "target"), rows)
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4}))

    def test_marker_only_repacking_advances_physical_generation_even_when_logical_recipe_repeats(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Aerie Mystics", "con", "1", "nonfoil", 1))
        self.deck("a", "A", "built", MAIN + "\nSideboard\n1 Elvish Mystic\n", table=TABLE)
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        original = {"for": "Elvish Mystic", "using": "Aerie Mystics", "qty": 1}
        standins.install_stand_ins(deck, "target", [original])
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        keys = [assembled.key(self.parsed())]
        generations = [assembled.generation(self.parsed())]
        for marker in (None, "Aerie Mystics"):
            record = inventory.current().deck("casual/a")
            row = dict(original, using=marker)
            assembly_standins.save_standins(json.dumps({"profile": "matt", "id": record.id,
                "version": "target", "sha256": record.sha256, "rows": [row]}))
            plan, body = self.request(self.choice(sideboard={"Elvish Mystic": 1}))
            self.assertTrue(plan["completion"]["can_mark_built"])
            self.mark(body)
            keys.append(assembled.key(self.parsed()))
            generations.append(assembled.generation(self.parsed()))
        self.assertEqual(len(set(keys)), 3)
        self.assertLess(generations[0], generations[1])
        self.assertLess(generations[1], generations[2])
        self.assertEqual(standins.installed_for(self.parsed())["cards"], [original])

    def test_full_scope_real_card_repack_retires_selected_marker_choices_without_losing_intent(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 3))
        self.deck("a", "A", "built", INTENDED, table=TABLE)
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        standins.install_stand_ins(deck, "target", [{"for": "Elvish Mystic", "using": None, "qty": 3}])
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        _, body = self.request(self.choice())
        self.mark(body)
        self.assertIsNone(standins.installed_for(self.parsed()))
        self.assertEqual(standins.choices_for(self.parsed(), "target"), [])
        self.assertEqual(self.parsed().target, decks.parse_decklist(INTENDED))
        self.assertEqual(self.held()["casual/a"], Counter({"Llanowar Elves": 4, "Elvish Mystic": 3}))

    def test_one_stand_in_choice_is_not_duplicated_across_selected_main_and_omitted_sideboard(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", MAIN + "1 Elvish Mystic\n\nSideboard\n1 Elvish Mystic\n",
                  table=TABLE)
        deck = self.parsed()
        rows = [{"for": "Elvish Mystic", "using": None, "qty": 1}]
        standins.set_choices(deck, "target", rows)
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        plan, body = self.request()
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["decks"][0]["standins"]["rows"], rows)
        self.assertEqual(plan["decks"][0]["standins"]["choices"], rows)
        self.mark(body)
        self.assertEqual(standins.choices_for(self.parsed(), "target"), rows)
        self.assertEqual(standins.installed_for(self.parsed())["cards"], rows)
