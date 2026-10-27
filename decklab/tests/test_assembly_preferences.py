"""Movable-copy priorities conserve physical cards and preserve default packing."""
from collections import Counter
import copy
import json
import random
import unittest
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.api import assembly, assembly_completion, assembly_preferences as preferences, assembly_standins, guard, settings
from decklab.lib.api.common import ApiError
from decklab.lib.decks import standins
from decklab.tests.test_assembly_completion import PROFILES, TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401

ELVES = "Llanowar Elves"
MYSTIC = "Elvish Mystic"


def participant(slug, need, current=0):
    return {"id": f"casual/{slug}", "title": slug.upper(), "need": Counter({ELVES: need}),
            "current": Counter({ELVES: current}), "steps": [], "returns": []}


class PreferenceValidationTests(unittest.TestCase):
    def test_normalized_choices_are_sorted_copied_and_use_canonical_selected_ids(self):
        participants = [participant("a", 1), participant("b", 2)]
        participants[0]["need"][MYSTIC] = 1
        selected = [{"id": "casual/a", "version": "owned", "sideboard": {ELVES: 1}, "prefer": [ELVES, MYSTIC]},
                    {"id": "casual/b", "version": "target"}]
        before = copy.deepcopy(selected)
        normalized, priorities = preferences.normalize(selected, participants)
        self.assertEqual(normalized[0]["prefer"], [MYSTIC, ELVES])
        self.assertEqual(priorities, {ELVES: "casual/a", MYSTIC: "casual/a"})
        self.assertEqual(selected, before)
        normalized[0]["sideboard"][ELVES] = 0
        self.assertEqual(selected[0]["sideboard"][ELVES], 1)

    def test_harmless_preferences_survive_single_demander_or_fully_kept_supply(self):
        for current in (0, 4):
            normalized, priorities = preferences.normalize(
                [{"id": "casual/a", "version": "target", "prefer": [ELVES]}], [participant("a", 4, current)])
            self.assertEqual(normalized[0]["prefer"], [ELVES])
            self.assertEqual(priorities, {ELVES: "casual/a"})

    def test_removed_recipe_name_drops_only_valid_stale_preference(self):
        selected = [{"id": "casual/a", "version": "target", "prefer": [ELVES]}]
        normalized, priorities = preferences.normalize(selected, [participant("a", 0)])
        self.assertEqual(normalized, [{"id": "casual/a", "version": "target"}])
        self.assertEqual(priorities, {})
        self.assertEqual(selected[0]["prefer"], [ELVES])

    def test_malformed_unknown_noncanonical_basic_and_duplicate_names_are_refused(self):
        values = [None, "Llanowar Elves", {}, [None], [False], ["llanowar elves"],
                  ["Not a real fixture card"], ["Forest"], [ELVES, ELVES]]
        for raw in values:
            with self.subTest(raw=raw), self.assertRaises(ApiError) as caught:
                preferences.normalize([{ "id": "casual/a", "version": "target", "prefer": raw}], [participant("a", 0)])
            self.assertEqual(caught.exception.status, 400)
        with self.assertRaises(ApiError):
            preferences.normalize([{"id": f"casual/{slug}", "version": "target", "prefer": [ELVES]}
                                   for slug in ("a", "b")], [participant("a", 1), participant("b", 2)])

    def test_limit_and_all_configured_installed_marker_names_are_guarded(self):
        with mock.patch.object(preferences, "MAX_PREFERENCES", 1), self.assertRaises(ApiError):
            preferences.normalize([{ "id": "casual/a", "version": "target", "prefer": [ELVES, MYSTIC]}],
                                  [participant("a", 1)])
        for source in ("configured", "choices", "raw", "installed", "rows"):
            for row in ({"for": ELVES, "using": None}, {"for": "Other", "using": ELVES}):
                with self.subTest(source=source, row=row), self.assertRaises(ApiError) as caught:
                    preferences.reject_markers({ELVES: "casual/a"}, [{source: [row]}])
                self.assertEqual(caught.exception.status, 400)
        preferences.reject_markers({ELVES: "casual/a"}, [{"choices": [{"for": MYSTIC, "using": None}]}])
        with self.assertRaises(ApiError) as caught:
            preferences.reject_markers({ELVES: "casual/a"}, [{"invalid": True}])
        self.assertEqual(caught.exception.status, 409)
        preferences.reject_markers({}, [{"invalid": True}])


class PreferredAllocationTests(unittest.TestCase):
    def test_preferred_receives_storage_first_but_incoming_keeps_original_order(self):
        items = [participant("a", 4), participant("b", 4), participant("c", 4)]
        found = preferences.allocate(ELVES, items, 3, 5, "casual/c")
        self.assertEqual([(s["storage"], s["waiting"], s["missing"]) for s in found["steps"]],
                         [(0, 4, 0), (0, 1, 3), (3, 0, 1)])
        self.assertEqual(found["returns"], [0, 0, 0])

    def test_keeps_cannot_be_given_away_and_released_donors_stay_capped(self):
        items = [participant("a", 3, 3), participant("donor", 1, 4), participant("b", 4)]
        found = preferences.allocate(ELVES, items, 1, 0, "casual/b")
        self.assertEqual([(s["keep"], s["storage"], s["missing"]) for s in found["steps"]],
                         [(3, 0, 0), (1, 0, 0), (0, 1, 0)])
        self.assertEqual(found["transfers"], [{"from": "casual/donor", "from_title": "DONOR",
                                             "to": "casual/b", "to_title": "B", "quantity": 3}])
        self.assertEqual(found["returns"], [0, 0, 0])
        no_spare = preferences.allocate(ELVES, [participant("a", 3, 3), participant("b", 3)], 0, 0, "casual/b")
        self.assertEqual([(s["keep"], s["missing"]) for s in no_spare["steps"]], [(3, 0), (0, 3)])

    def test_donor_only_returns_and_transfer_presentation_keep_original_order(self):
        items = [participant("a", 2), participant("b", 1), participant("donor", 0, 5)]
        before = copy.deepcopy(items)
        found = preferences.allocate(ELVES, items, 0, 0, "casual/b")
        self.assertIsNone(found["steps"][2])
        self.assertEqual([t["to"] for t in found["transfers"]], ["casual/a", "casual/b"])
        self.assertEqual(found["returns"], [0, 0, 2])
        self.assertEqual(items, before)

    def test_default_allocation_has_independent_storage_transfer_wait_and_return_expectations(self):
        cases = [
            ([participant("a", 4), participant("b", 4)], 4, 2,
             [(0, 4, [], 0, 0), (0, 0, [], 2, 2)], [0, 0]),
            ([participant("a", 2, 4), participant("b", 3), participant("donor", 0, 1)], 1, 1,
             [(2, 0, [], 0, 0), (0, 1, [("casual/a", 2)], 0, 0), None], [0, 0, 1]),
            ([participant("a", 1), participant("b", 2), participant("c", 3)], 1, 3,
             [(0, 1, [], 0, 0), (0, 0, [], 2, 0), (0, 0, [], 1, 2)], [0, 0, 0]),
            ([participant("a", 0, 2), participant("b", 0)], 3, 4,
             [None, None], [2, 0]),
        ]
        for items, storage, incoming, expected, returned in cases:
            with self.subTest(items=items, storage=storage, incoming=incoming):
                found = preferences.allocate(ELVES, items, storage, incoming)
                facts = [None if step is None else (step["keep"], step["storage"],
                         [(t["from"], t["quantity"]) for t in step["transfers"]], step["waiting"], step["missing"])
                         for step in found["steps"]]
                self.assertEqual(facts, expected)
                self.assertEqual(found["returns"], returned)

    def test_priorities_conserve_copies_and_waits_across_many_three_deck_plans(self):
        rng = random.Random(93017)
        for case in range(240):
            items = [participant(str(i), rng.randrange(6), rng.randrange(6)) for i in range(3)]
            storage, incoming = rng.randrange(7), rng.randrange(7)
            found = preferences.allocate(ELVES, items, storage, incoming, items[case % 3]["id"])
            before = sum(item["current"][ELVES] for item in items) + storage
            real = pulled = waited = 0
            for item, step in zip(items, found["steps"]):
                if step is None:
                    continue
                transferred = sum(t["quantity"] for t in step["transfers"])
                with self.subTest(case=case, deck=item["id"]):
                    self.assertEqual(step["keep"], min(item["need"][ELVES], item["current"][ELVES]))
                    self.assertEqual(step["need"], step["keep"] + step["storage"] + transferred + step["waiting"] + step["missing"])
                real += step["keep"] + step["storage"] + transferred
                pulled += step["storage"]
                waited += step["waiting"]
            self.assertLessEqual(pulled, storage)
            self.assertLessEqual(waited, incoming)
            self.assertEqual(real + sum(found["returns"]) + storage - pulled, before)


class PreferenceApiTests(PreparationCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(settings, "_config_profiles", return_value=PROFILES)
        patch.start()
        self.addCleanup(patch.stop)
        self.cards_csv("collection.csv", (ELVES, "fdn", "227", "nonfoil", 4),
                       (MYSTIC, "cmm", "648", "nonfoil", 1), ("Aerie Mystics", "con", "1", "nonfoil", 2))
        self.deck("a", "A", "building", f"Deck\n4 {ELVES}\n20 Forest\n", table=TABLE)
        self.deck("b", "B", "building", f"Deck\n4 {ELVES}\n20 Forest\n", table=TABLE)
        self.selected = [{"id": f"casual/{slug}", "version": "target"} for slug in ("a", "b")]

    def plan(self, selected=None):
        return assembly.assembly_preview(json.dumps({"profile": "matt", "decks": self.selected if selected is None else selected}))

    def preferred(self, slug="b"):
        return [{**choice, **({"prefer": [ELVES]} if choice["id"] == f"casual/{slug}" else {})} for choice in self.selected]

    def row(self, plan, name=ELVES):
        return next(row for row in plan["rows"] if row["name"] == name)

    def write_markers(self, slug, data):
        path = self.magic / f"decks/casual/{slug}.md"
        parsed = decks.parse_deck(path.read_bytes(), slug, "casual")
        standins.set_stand_ins(parsed, data)
        path.write_text(decks.render_deck_file(parsed), encoding="utf-8")

    def test_preview_moves_free_copies_and_projects_validated_receivers_without_writing(self):
        default = self.plan()
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read-only plan")):
            preferred = self.plan(self.preferred())
        self.assertEqual(self.row(default)["preference_options"], ["casual/a", "casual/b"])
        self.assertIsNone(self.row(default)["preferred"])
        self.assertEqual(self.row(preferred)["preferred"], "casual/b")
        self.assertEqual(preferred["selections"], self.preferred())
        self.assertNotEqual(default["completion"]["fingerprint"], preferred["completion"]["fingerprint"])
        self.assertEqual([deck["steps"][0]["storage"] for deck in preferred["decks"]], [0, 4])
        self.assertEqual([deck["steps"][0]["missing"] for deck in preferred["decks"]], [4, 0])
        self.assertEqual(preferred["totals"], default["totals"])

    def test_kept_unselected_and_intact_reservations_cannot_be_taken_by_priority(self):
        self.deck("a", "A", "built", f"Deck\n2 {ELVES}\n20 Forest\n", table=TABLE)
        self.deck("outside", "Outside", "built", f"Deck\n1 {ELVES}\n", table=TABLE)
        self.product("kept.csv", ("deck", ELVES, 1), column="section")
        self.status(("kept.csv", "owned", "yes"))
        found = self.plan(self.preferred())
        first, second = found["decks"]
        self.assertEqual((first["steps"][0]["keep"], second["steps"][0]["storage"]), (2, 0))
        self.assertEqual(sum(h["quantity"] for h in self.row(found)["held_elsewhere"]), 2)
        self.assertNotIn("preference_options", self.row(found))
        self.assertEqual(found["selections"], self.preferred())

    def test_no_supply_sufficient_supply_and_single_receiver_keep_harmless_choice_without_controls(self):
        for quantity in (0, 8):
            self.cards_csv("collection.csv", *((ELVES, "fdn", "227", "nonfoil", quantity),) if quantity else ())
            found = self.plan(self.preferred())
            self.assertNotIn("preference_options", self.row(found))
            self.assertEqual(found["selections"], self.preferred())
        single = self.plan([self.preferred()[1]])
        self.assertNotIn("preference_options", self.row(single))
        self.assertEqual(single["selections"], [self.preferred()[1]])

    def test_released_copies_and_incoming_follow_separate_priorities_in_real_preview(self):
        self.deck("a", "A", "built", f"Deck\n2 {ELVES}\n20 Forest\n",
                  owned=f"Deck\n4 {ELVES}\n20 Forest\n", built_version="owned-only", table=TABLE)
        self.deck("c", "C", "building", f"Deck\n4 {ELVES}\n20 Forest\n", table=TABLE)
        self.selected.append({"id": "casual/c", "version": "target"})
        self.cards_csv("orders/arrival.csv", (ELVES, "fdn", "227", "foil", 2))
        found = self.plan(self.preferred("c"))
        self.assertTrue(found["counts_confirmed"], found["warnings"])
        a, b, c = [deck["steps"][0] for deck in found["decks"]]
        self.assertEqual((a["keep"], b["waiting"], b["missing"], c["waiting"], c["missing"]), (2, 2, 2, 0, 2))
        self.assertEqual(c["transfers"], [{"from": "casual/a", "from_title": "A", "to": "casual/c",
                                           "to_title": "C", "quantity": 2}])
        self.assertEqual(self.row(found)["preference_options"], ["casual/b", "casual/c"])
        self.assertFalse(found["ready"])

    def test_recipe_change_drops_valid_absent_name_but_refuses_invalid_names(self):
        self.deck("a", "A", "building", f"Deck\n4 {ELVES}\n20 Forest\nSideboard\n1 {MYSTIC}\n", table=TABLE)
        selected = [{**self.selected[0], "sideboard": {}, "prefer": [MYSTIC]}, self.selected[1]]
        found = self.plan(selected)
        self.assertEqual(found["selections"], [{**self.selected[0], "sideboard": {}}, self.selected[1]])
        with self.assertRaises(ApiError) as caught:
            self.plan([{**selected[0], "prefer": ["No such fixture card"]}, selected[1]])
        self.assertEqual(caught.exception.status, 400)

    def test_actual_inactive_and_other_version_marker_choices_hide_controls_and_refuse_preference(self):
        cases = [{"target": [{"for": ELVES, "using": None, "qty": 1}]},
                 {"owned": [{"for": MYSTIC, "using": ELVES, "qty": 1}]}]
        for data in cases:
            self.write_markers("a", data)
            with self.subTest(data=data):
                found = self.plan()
                self.assertEqual(found["decks"][0]["standins"]["rows"], [])
                self.assertNotIn("preference_options", self.row(found))
                self.assertNotIn("configured", json.dumps(found))
                with self.assertRaises(ApiError) as caught:
                    self.plan(self.preferred())
                self.assertEqual(caught.exception.status, 400)

    def test_installed_marker_names_are_excluded_even_after_config_choices_are_cleared(self):
        self.deck("a", "A", "built", f"Deck\n1 {MYSTIC}\n", table=TABLE)
        self.write_markers("a", {"built": {"version": "target", "cards": [{"for": MYSTIC, "using": ELVES, "qty": 1}]}})
        self.deck("c", "C", "building", f"Deck\n4 {ELVES}\n", table=TABLE)
        self.selected.append({"id": "casual/c", "version": "target"})
        found = self.plan()
        self.assertNotIn("preference_options", self.row(found))
        with self.assertRaises(ApiError) as caught:
            self.plan(self.preferred())
        self.assertEqual(caught.exception.status, 400)

    def test_unconfirmed_counts_and_unauthorized_read_never_offer_preferences(self):
        self.deck("outside", "Outside", "built", f"Deck\n9 {ELVES}\n", table=TABLE)
        found = self.plan()
        self.assertFalse(found["counts_confirmed"])
        self.assertNotIn("preference_options", self.row(found))
        with mock.patch.object(guard, "require_sees_home_records", side_effect=ApiError(403, "private")), \
                mock.patch.object(preferences, "normalize", side_effect=AssertionError("privacy first")):
            with self.assertRaises(ApiError) as caught:
                self.plan(self.preferred())
            self.assertEqual(caught.exception.status, 403)

    def test_preferences_bind_completion_receipt_and_survive_built_repreview(self):
        self.cards_csv("collection.csv", (ELVES, "fdn", "227", "nonfoil", 8))
        default, selected = self.plan(), self.preferred()
        preferred = self.plan(selected)
        body = {"profile": "matt", "decks": selected, "confirmed": True,
                "fingerprint": default["completion"]["fingerprint"]}
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("stale receipt cannot write")):
            with self.assertRaises(ApiError) as caught:
                assembly_completion.mark_built(json.dumps(body))
            self.assertEqual(caught.exception.status, 409)
        body["fingerprint"] = preferred["completion"]["fingerprint"]
        saved = assembly_completion.mark_built(json.dumps(body))
        self.assertTrue(saved["saved"])
        self.assertEqual(saved["plan"]["selections"], selected)
        self.assertTrue(all(item["completion"]["already_built"] for item in saved["plan"]["decks"]))

    def test_contextual_standin_save_uses_the_preferred_plan_receipt(self):
        self.deck("a", "A", "building", f"Deck\n4 {ELVES}\n1 Black Lotus\n20 Forest\n", table=TABLE)
        selected = self.preferred()
        default, preferred = self.plan(), self.plan(selected)
        stored = inventory.current().deck("casual/a")
        body = {"profile": "matt", "id": stored.id, "version": "target", "sha256": stored.sha256,
                "rows": [{"for": "Black Lotus", "using": "Aerie Mystics", "qty": 1}], "decks": selected,
                "fingerprint": default["completion"]["fingerprint"]}
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("stale context cannot write")):
            with self.assertRaises(ApiError) as caught:
                assembly_standins.save_standins(json.dumps(body))
            self.assertEqual(caught.exception.status, 409)
        body["fingerprint"] = preferred["completion"]["fingerprint"]
        self.assertTrue(assembly_standins.save_standins(json.dumps(body))["saved"])
