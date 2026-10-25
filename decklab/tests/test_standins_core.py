"""Stand-in recipes and physical-copy allocation, with a temporary files backend.

The represented cards remain in the logical lists. Only an explicitly installed
recipe reserves marker cards; suggestions and saved choices are not reservations.
No test reads the live inventory, calls the network, or starts Forge.
"""
import copy
import json
import unittest
from collections import Counter

from decklab.lib import decks, inventory, pool
from decklab.lib.decks import standins
from decklab.tests import deck_files
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


ELF = "Llanowar Elves"
MYSTIC = "Elvish Mystic"
POISON = "Pick Your Poison"


def mapping(target=ELF, marker=MYSTIC, quantity=1):
    return {"for": target, "using": marker, "qty": quantity}


class StandInCase(PreparationCase):
    def read_deck(self, slug="a"):
        return decks.read_deck_file(self.magic / f"decks/casual/{slug}.md")

    def save_deck(self, deck):
        deck_files.write_deck_file(self.magic / f"decks/casual/{deck.slug}.md",
                                   decks.render_deck_file(deck), deck.sha256)

    def save_choices(self, rows, slug="a", version="target"):
        deck = self.read_deck(slug)
        standins.set_choices(deck, version, rows)
        self.save_deck(deck)

    def install(self, rows, slug="a", version="target"):
        deck = self.read_deck(slug)
        standins.install_stand_ins(deck, version, rows)
        self.save_deck(deck)

    def owned(self, *, elves=0, mystics=0, poison=0):
        rows = [(ELF, "fdn", "227", "nonfoil", elves),
                (MYSTIC, "cmm", "648", "nonfoil", mystics),
                (POISON, "mkm", "170", "nonfoil", poison)]
        self.cards_csv("collection.csv", *(row for row in rows if row[-1]))
        inventory.invalidate()

    @staticmethod
    def item(plan, slug="a"):
        return next(item for item in plan["decks"] if item["id"] == f"casual/{slug}")

    @staticmethod
    def holders():
        return {holder.id: dict(holder.cards) for holder in pool.load_pool().in_use}


class StandInHeaderTests(StandInCase):
    def test_generic_header_and_table_edits_preserve_recipe_and_logical_lists(self):
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves (FDN) 227\n20 Forest\n\n"
                  "Sideboard\n1 Pick Your Poison\n", owned="Deck\n1 Llanowar Elves\n20 Forest\n",
                  table="| Llanowar Elves | 2 | 0 | **2** | | | keep this note |\n"
                        "| Pick Your Poison | 1 | 0 | **1** | | | |\n"
                        "| **Total to buy** | | | **3** | | | |\n")
        recipe = {"target": [mapping()], "owned": [mapping(marker=None)], "built": None}
        # Unknown headers keep their formatting through the ordinary editor and
        # table refresh, even if the JSON was not written by set_stand_ins.
        header = "- **Stand-ins:** " + json.dumps(recipe, separators=(", ", ": "))
        path = self.magic / "decks/casual/a.md"
        self.write("decks/casual/a.md", path.read_text(encoding="utf-8").replace(
            "- **Status:** building", "- **Status:** building\n" + header))
        before = self.read_deck()
        lists = copy.deepcopy((before.target, before.owned))

        decks.set_player(before, "user")
        decks.set_table(before, *pool.deck_table(before, prices=False))
        rendered = decks.render_deck_file(before)
        after = decks.parse_deck(rendered.encode("utf-8"), "a", "casual")

        self.assertIn(header + "\n", rendered)
        self.assertEqual(standins.get_stand_ins(after), recipe)
        self.assertEqual((after.target, after.owned), lists)
        self.assertIn("keep this note", rendered)
        self.assertEqual(after.player, "user")

    def test_saving_a_choice_does_not_install_or_reserve_its_marker(self):
        self.owned(mystics=1)
        self.deck("a", "A", "building", "Deck\n1 Llanowar Elves\n")
        before = copy.deepcopy(self.read_deck().target)
        self.save_choices([mapping()])

        self.assertIsNone(standins.installed_for(self.read_deck()))
        self.assertEqual(self.read_deck().target, before)
        self.assertEqual(self.holders(), {})
        plan = self.preview(("a", "target"))
        self.assertTrue(plan["ready"])
        self.assertEqual(self.item(plan)["standins"]["rows"], [mapping()])
        # Preview is read-only too: completion is a separate explicit action.
        self.assertIsNone(standins.installed_for(self.read_deck()))
        self.assertEqual(self.holders(), {})

    def test_list_versions_have_independent_choices(self):
        self.deck("a", "A", "building", "Deck\n1 Llanowar Elves\n",
                  owned="Deck\n1 Pick Your Poison\n")
        self.save_choices([mapping()])
        self.save_choices([mapping(POISON, None)], version="owned")
        self.assertEqual(standins.choices_for(self.read_deck(), "target"), [mapping()])
        self.assertEqual(standins.choices_for(self.read_deck(), "owned"), [mapping(POISON, None)])
        self.assertIsNone(standins.installed_for(self.read_deck()))

    def test_invalid_mappings_cannot_reinterpret_a_card_already_in_the_list(self):
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves\n1 Elvish Mystic\n20 Forest\n")
        deck = self.read_deck()
        original = decks.render_deck_file(deck)
        invalid = ([mapping()], [mapping(marker="Forest")], [mapping(quantity=3)],
                   [mapping(target=POISON)], [mapping(quantity=True)], [mapping(quantity=0)],
                   [mapping(marker="Elvish Mystic\nSideboard")], [mapping(target="Forest", marker=None)])
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(standins.StandInsError):
                standins.set_choices(deck, "target", rows)
            self.assertEqual(decks.render_deck_file(deck), original)


class InstalledStandInTests(StandInCase):
    def test_editing_a_built_decks_choice_does_not_change_its_installed_recipe(self):
        self.owned(mystics=1, poison=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        self.install([mapping()])
        self.save_choices([mapping(marker=POISON)])

        data = standins.get_stand_ins(self.read_deck())
        self.assertEqual(data["target"], [mapping(marker=POISON)])
        self.assertEqual(data["built"], {"version": "target", "cards": [mapping()]})
        self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})
        plan = self.preview(("a", "target"))
        self.assertEqual(self.item(plan)["standins"]["rows"], [mapping(marker=POISON)])
        self.assertEqual(self.item(plan)["returns"], [{"name": MYSTIC, "quantity": 1}])
        self.assertTrue(standins.needs_install(self.read_deck(), self.item(plan)))
        self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})

    def test_installed_marker_stays_reserved_when_the_represented_card_arrives(self):
        self.owned(mystics=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        self.install([mapping()])
        self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})

        # A receipt adds the real card to storage. It does not perform the
        # physical swap in the already sleeved deck.
        self.owned(elves=1, mystics=1)
        self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})
        self.deck("b", "B", "building", "Deck\n1 Elvish Mystic\n")
        blocked = self.preview(("b", "target"))
        self.assertFalse(blocked["ready"])
        row = next(row for row in blocked["rows"] if row["name"] == MYSTIC)
        self.assertEqual(row["held_elsewhere"], [{"id": "casual/a", "title": "A", "quantity": 1}])

    def test_repack_uses_new_real_card_returns_marker_and_retires_choice(self):
        self.owned(mystics=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        self.install([mapping()])
        installed_sha = self.read_deck().sha256
        self.owned(elves=1, mystics=1)

        plan = self.preview(("a", "target"))
        item = self.item(plan)
        self.assertTrue(plan["ready"])
        self.assertEqual(item["standins"]["rows"], [])
        self.assertEqual(item["returns"], [{"name": MYSTIC, "quantity": 1}])
        self.assertEqual(item["standins"]["retired"], [{**mapping(), "reason": "real_available"}])
        self.assertTrue(item["completion"]["repack"])
        # Looking at the proposal has not silently swapped the sleeved cards.
        self.assertEqual(self.read_deck().sha256, installed_sha)
        self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})

    def test_real_card_held_in_another_deck_does_not_retire_the_marker(self):
        self.owned(elves=1, mystics=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        self.install([mapping()])
        self.deck("b", "B", "built", "Deck\n1 Llanowar Elves\n")

        plan = self.preview(("a", "target"))
        item = self.item(plan)
        self.assertTrue(plan["ready"])
        self.assertEqual(item["standins"]["rows"], [mapping()])
        self.assertEqual(item["standins"]["retired"], [])
        self.assertEqual(item["returns"], [])
        self.assertEqual(plan["logical_totals"]["missing"], 1)
        self.assertEqual(plan["totals"]["missing"], 0)
        self.assertEqual(item["steps"][0]["name"], MYSTIC)
        self.assertEqual(item["steps"][0]["keep"], 1)

    def test_nonselected_holder_version_mismatch_still_blocks_confirmation(self):
        self.owned(mystics=1, poison=1)
        self.deck("a", "A", "built", "Deck\n1 Pick Your Poison\n",
                  owned="Deck\n1 Llanowar Elves\n", built_version="target")
        self.install([mapping()], version="owned")
        self.deck("b", "B", "building", "Deck\n20 Forest\n")

        plan = self.preview(("b", "target"))
        self.assertFalse(plan["counts_confirmed"])
        self.assertFalse(plan["ready"])
        self.assertTrue(any("another list version" in warning for warning in plan["warnings"]))
        # Even inconsistent metadata must keep the physical marker held.
        self.assertEqual(self.holders()["casual/a"].get(MYSTIC), 1)

    def test_repacking_selected_holder_repairs_a_removed_target_and_returns_marker(self):
        self.owned(mystics=1, poison=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        self.install([mapping()])
        edited = self.read_deck()
        decks.apply_edit(edited, target=decks.parse_decklist("Deck\n1 Pick Your Poison\n"),
                         date="2026-10-15")
        self.save_deck(edited)
        before = self.read_deck().sha256

        p = pool.load_pool()
        self.assertEqual(self.holders()["casual/a"].get(MYSTIC), 1)
        self.assertTrue(any("installed stand-ins no longer fit" in warning for warning in p.warnings))
        plan = self.preview(("a", "target"))
        item = self.item(plan)
        self.assertTrue(plan["counts_confirmed"])
        self.assertTrue(plan["ready"])
        self.assertEqual(item["standins"]["rows"], [])
        self.assertEqual(item["standins"]["retired"], [{**mapping(), "reason": "list_changed"}])
        self.assertEqual(item["returns"], [{"name": MYSTIC, "quantity": 1}])
        self.assertTrue(standins.needs_install(self.read_deck(), item))
        self.assertTrue(item["completion"]["repack"])
        self.assertEqual(self.read_deck().sha256, before)

        # The repair is safe only when that physical holder participates.
        self.deck("b", "B", "building", "Deck\n20 Forest\n")
        unrelated = self.preview(("b", "target"))
        self.assertFalse(unrelated["counts_confirmed"])
        self.assertFalse(unrelated["ready"])
        self.assertTrue(any("installed stand-ins no longer fit" in warning
                            for warning in unrelated["warnings"]))

    def test_repair_does_not_hide_an_overreserved_physical_marker(self):
        self.owned(mystics=1, poison=1)
        self.deck("a", "A", "built", "Deck\n2 Llanowar Elves\n")
        self.install([mapping(quantity=2)])
        edited = self.read_deck()
        decks.apply_edit(edited, target=decks.parse_decklist("Deck\n1 Pick Your Poison\n"))
        self.save_deck(edited)

        plan = self.preview(("a", "target"))
        self.assertFalse(plan["counts_confirmed"])
        self.assertFalse(plan["ready"])
        self.assertTrue(any("only 1 are physically owned" in warning for warning in plan["warnings"]))

    def test_marker_added_to_logical_list_fails_closed_then_recovers_by_explicit_rebuild(self):
        from unittest import mock
        from decklab.lib import accessories, config
        from decklab.lib.api import assembly_completion, saving, settings
        from decklab.lib.api.common import ApiError
        from decklab.tests.test_assembly_completion import PROFILES, TABLE

        profile_path = self.magic.parent / "config.json"
        profile_path.write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        self.write("accessories.csv", ",".join(accessories.FIELDS) + "\n"
                   "sleeves,sleeves,shared,DS,Matte,blue,100,,,,,,\n"
                   "box,deck_box,shared,UG,Boulder,black,1,100,,,,,\n")
        with mock.patch.object(settings, "_config_profiles", return_value=PROFILES), \
                mock.patch.object(config, "CONFIG_FILE", profile_path):
            for keep_target in (False, True):
                with self.subTest(keep_target=keep_target):
                    self.owned(mystics=1)
                    self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n59 Forest\n", table=TABLE)
                    self.install([mapping()])
                    edited = self.read_deck()
                    decks.set_sleeves(edited, "sleeves")
                    decks.set_deck_box(edited, "box")
                    logical = "Deck\n1 Elvish Mystic\n58 Forest\n" + (
                        "1 Llanowar Elves\n" if keep_target else "1 Forest\n")
                    decks.apply_edit(edited, target=decks.parse_decklist(logical), date="2026-10-15")
                    self.save_deck(edited)
                    rows = [mapping(marker=None)] if keep_target else []
                    self.save_choices(rows)
                    selected = [{"id": "casual/a", "version": "target"}]
                    blocked = self.preview(("a", "target"))
                    self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 2}})
                    self.assertFalse(blocked["counts_confirmed"])
                    self.assertFalse(blocked["completion"]["can_mark_built"])
                    self.assertTrue(any("only 1 are physically owned" in warning
                                        for warning in blocked["warnings"]))
                    with self.assertRaises(ApiError) as caught:
                        assembly_completion.mark_built(json.dumps({"profile": "matt", "decks": selected,
                            "confirmed": True, "fingerprint": blocked["completion"]["fingerprint"]}))
                    self.assertEqual(caught.exception.status, 409)

                    # Taking the deck apart is an explicit physical action: all
                    # its reservations and kit go, before a fresh packing plan.
                    saving.save_deck(json.dumps({"profile": "matt", "id": "casual/a",
                        "sha256": self.read_deck().sha256, "fields": {"status": "building"}}))
                    apart = self.read_deck()
                    self.assertEqual((apart.status, apart.sleeves, apart.deck_box), ("building", None, None))
                    self.assertEqual(self.holders(), {})
                    self.save_choices(rows)
                    fresh = self.preview(("a", "target"))
                    self.assertTrue(fresh["completion"]["can_mark_built"], fresh["warnings"])
                    self.assertEqual(self.item(fresh)["returns"], [])
                    self.assertEqual([(step["name"], step["storage"]) for step in self.item(fresh)["steps"]],
                                     [(MYSTIC, 1)])
                    assembly_completion.mark_built(json.dumps({"profile": "matt", "decks": selected,
                        "confirmed": True, "fingerprint": fresh["completion"]["fingerprint"],
                        "kit": {"casual/a": {"sleeves": "sleeves", "deck_box": "box"}}}))
                    rebuilt = self.read_deck()
                    self.assertEqual((rebuilt.status, rebuilt.sleeves, rebuilt.deck_box), ("built", "sleeves", "box"))
                    self.assertEqual(self.holders(), {"casual/a": {MYSTIC: 1}})
                    expected = {"version": "target", "cards": rows} if rows else None
                    self.assertEqual(standins.installed_for(rebuilt), expected)
                    self.assertEqual(self.item(self.preview(("a", "target")))["returns"], [])

    def test_malformed_header_never_makes_a_plan_ready(self):
        self.owned(elves=1)
        self.deck("a", "A", "built", "Deck\n1 Llanowar Elves\n")
        path = self.magic / "decks/casual/a.md"
        self.write("decks/casual/a.md", path.read_text(encoding="utf-8").replace(
            "- **Status:** built", '- **Status:** built\n- **Stand-ins:** {"built":'))

        plan = self.preview(("a", "target"))
        self.assertFalse(plan["counts_confirmed"])
        self.assertFalse(plan["ready"])
        self.assertTrue(plan["warnings"])
        self.assertEqual(self.item(plan)["standins"]["rows"], [])


class StandInAllocationTests(StandInCase):
    def test_an_invalid_later_target_cannot_consume_an_already_reserved_marker(self):
        warnings = []
        held = standins.physical_counts(Counter({ELF: 1}),
                                       [mapping(), mapping(MYSTIC, POISON)], warnings)
        self.assertEqual(held, Counter({MYSTIC: 1, POISON: 1}))
        self.assertTrue(warnings)

    def test_real_cards_allocate_to_all_selected_decks_before_saved_markers(self):
        self.owned(mystics=1)
        self.deck("a", "A", "building", "Deck\n1 Llanowar Elves\n")
        self.save_choices([mapping()])
        self.deck("b", "B", "building", "Deck\n1 Elvish Mystic\n")

        for selections in ((("a", "target"), ("b", "target")),
                           (("b", "target"), ("a", "target"))):
            with self.subTest(selections=selections):
                plan = self.preview(*selections)
                self.assertFalse(plan["ready"])
                self.assertEqual(self.item(plan, "a")["standins"]["rows"], [])
                self.assertEqual(self.item(plan, "b")["steps"][0]["storage"], 1)
                self.assertEqual(plan["totals"]["missing"], 1)

    def test_two_saved_mappings_cannot_consume_one_named_marker_twice(self):
        self.owned(mystics=1)
        for slug in ("a", "b"):
            self.deck(slug, slug.upper(), "building", "Deck\n1 Llanowar Elves\n")
            self.save_choices([mapping()], slug)

        plan = self.preview(("a", "target"), ("b", "target"))
        allocated = [row for item in plan["decks"] for row in item["standins"]["rows"]]
        self.assertEqual(allocated, [mapping()])
        self.assertEqual(plan["totals"]["from_storage"], 1)
        self.assertEqual(plan["totals"]["missing"], 1)
        self.assertEqual(plan["logical_totals"]["missing"], 2)
        self.assertTrue(self.item(plan, "b")["standins"]["warnings"])
        self.assertFalse(plan["ready"])

    def test_saved_marker_covers_waiting_and_missing_but_preserves_logical_shortage(self):
        self.owned(mystics=2)
        self.cards_csv("orders/arrival.csv", (ELF, "fdn", "227", "nonfoil", 1))
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves\n")
        self.save_choices([mapping(quantity=2)])

        plan = self.preview(("a", "target"))
        self.assertTrue(plan["ready"])
        self.assertEqual((plan["logical_totals"]["waiting"], plan["logical_totals"]["missing"]), (1, 1))
        self.assertEqual((plan["totals"]["waiting"], plan["totals"]["missing"]), (0, 0))
        self.assertEqual(self.item(plan)["logical_shortages"], [{"name": ELF, "waiting": 1, "missing": 1}])
        self.assertEqual([(step["name"], step["need"]) for step in self.item(plan)["steps"]], [(MYSTIC, 2)])

    def test_incoming_only_card_is_not_a_candidate_or_an_usable_saved_marker(self):
        self.cards_csv("orders/arrival.csv", (MYSTIC, "cmm", "648", "nonfoil", 2))
        self.deck("a", "A", "building", "Deck\n1 Llanowar Elves\n")
        unsaved = self.preview(("a", "target"))
        self.assertEqual(self.item(unsaved)["standins"]["candidates"], [])
        self.assertEqual(self.item(unsaved)["standins"]["needs"], [{"for": ELF, "qty": 1, "suggestion": None}])
        self.save_choices([mapping()])
        saved = self.preview(("a", "target"))
        self.assertEqual(self.item(saved)["standins"]["rows"], [])
        self.assertFalse(saved["ready"])
        self.assertEqual(saved["totals"]["missing"], 1)

    def test_unsaved_suggestions_are_deterministic_and_do_not_double_book(self):
        self.owned(mystics=1)
        for slug in ("a", "b"):
            self.deck(slug, slug.upper(), "building", "Deck\n1 Llanowar Elves\n")
        before = {slug: self.read_deck(slug).sha256 for slug in ("a", "b")}

        first = self.preview(("a", "target"), ("b", "target"))
        second = self.preview(("a", "target"), ("b", "target"))
        needs = [item["standins"]["needs"] for item in first["decks"]]
        self.assertEqual(needs, [[{"for": ELF, "qty": 1, "suggestion": MYSTIC}],
                                 [{"for": ELF, "qty": 1, "suggestion": None}]])
        self.assertEqual(needs, [item["standins"]["needs"] for item in second["decks"]])
        self.assertTrue(all(item["standins"]["rows"] == [] for item in first["decks"]))
        self.assertEqual((first["totals"]["missing"], first["totals"]["from_storage"]), (2, 0))
        self.assertFalse(first["ready"])
        self.assertEqual({slug: self.read_deck(slug).sha256 for slug in before}, before)

    def test_generic_spare_choice_covers_shortage_without_inventing_owned_cards(self):
        self.deck("a", "A", "building", "Deck\n2 Llanowar Elves\n20 Forest\n")
        self.save_choices([mapping(marker=None, quantity=2)])

        plan = self.preview(("a", "target"))
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["rows"], [])
        self.assertEqual(plan["logical_totals"]["missing"], 2)
        self.assertEqual(plan["totals"]["need"], 0)
        self.assertEqual(self.item(plan)["standins"]["rows"], [mapping(marker=None, quantity=2)])
        self.assertEqual(self.item(plan)["basics"], [{"name": "Forest", "quantity": 20}])
        self.assertEqual(dict(pool.load_pool().owned), {})


if __name__ == "__main__":
    unittest.main()
