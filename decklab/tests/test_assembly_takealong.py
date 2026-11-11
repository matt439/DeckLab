"""A built-deck take-along list reuses physical, privacy-filtered records and optional ticks."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import accessories, access, decks, inventory
from decklab.lib.api import assembly, assembly_counters, assembly_takealong as takealong
from decklab.lib.inventory import files, ops_decks
from decklab.tests import household_config
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


def built(deck_id="casual/a", digest="a"):
    return {"id": deck_id, "title": "A built deck", "version": "target", "rename_version": 0,
            "completion": {"status": "built", "already_built": True},
            "take_apart": {"available": True, "version": "target", "sha256": digest * 64,
                "tokens_recorded": True, "tokens": [{"quantity": 2, "front": "Dog", "back": "Beast",
                    "set": "tfdn", "number": "12"}],
                "kit": {"sleeves": {"state": "linked", "id": "sleeves", "label": "Shared sleeves"},
                        "deck_box": {"state": "text", "value": "Older box"}}}}


def mat(owner, name, quantity=1):
    return {"id": owner + "-mat", "owner": owner, "kind": "playmat", "brand": "", "name": name,
            "colour": "", "quantity": quantity, "notes": "private unused notes"}


class TakeAlongProjectionTests(unittest.TestCase):
    def project(self, participants=None, counters=None, inv=None):
        plan = {"decks": [built()] if participants is None else participants, "counters": counters or {}}
        with mock.patch.object(takealong.guard, "accessory_owners", return_value={"matt", "shared"}):
            return takealong.project(plan, inv or accessories.Inventory())

    def test_built_details_are_visible_printing_specific_and_read_only(self):
        decks = [built()]
        before = copy.deepcopy(decks)
        result = self.project(decks)
        self.assertTrue(result["available"])
        self.assertEqual(result["decks"][0]["lines"], ["Deck box: Older box", "Sleeves: Shared sleeves",
                                                        "Token cards: 2 Dog / Beast (TFDN) 12"])
        self.assertRegex(result["decks"][0]["context"], r"^[a-f0-9]{64}$")
        self.assertEqual(decks, before)

    def test_historical_goldens_ignore_only_authenticated_empty_additive_projection(self):
        from decklab.tests import golden_packing
        decks = [built()]
        value = self.project(decks, {"needs": [], "note": assembly_counters.NOTE})
        plan = {"decks": decks, "take_along": value}
        self.assertNotIn("take_along", golden_packing.normalise({"assembly": {"a": plan}})["assembly"]["a"])
        for change in ({"playmats": ["Keep this playmat"]}, {"counter_error": "Keep the error"},
                       {"counters": [{"title": "Poison counters"}]}, {"extra": "Keep malformed metadata"}):
            with self.subTest(change=change):
                altered = {**plan, "take_along": {**value, **change}}
                self.assertEqual(golden_packing.normalise({"assembly": {"a": altered}})["assembly"]["a"]["take_along"],
                                 altered["take_along"])

    def test_hidden_null_kit_is_unknown_and_tokens_not_recorded_is_not_empty(self):
        deck = built()
        deck["kit"] = {"sleeves": {"label": "Never read this raw kit"}}
        deck["take_apart"].update(kit=None, tokens_recorded=False, tokens=[])
        result = self.project([deck])
        text = json.dumps(result)
        self.assertIn("Sleeves and deck box details are unavailable", text)
        self.assertIn("Packing not recorded", text)
        self.assertNotIn("Never read", text)
        self.assertNotIn("Not recorded", text)
        deck["take_apart"].update(kit={"sleeves": None, "deck_box": None}, tokens_recorded=True)
        text = json.dumps(self.project([deck]))
        self.assertIn("Sleeves: Not recorded", text)
        self.assertIn("Token cards: None recorded", text)

    def test_only_own_and_shared_positive_playmats_are_reminders(self):
        rows = [mat("matt", "My mat"), mat("shared", "Shared mat"), mat("user1", "Another public mat"),
                mat("user2", "Member mat"), mat("matt", "Used up mat", 0)]
        inv = accessories.Inventory(rows_by_id={str(index): row for index, row in enumerate(rows)})
        result = self.project(inv=inv)
        self.assertEqual(result["playmats"], ["My mat", "Shared mat"])
        self.assertNotIn("private unused notes", json.dumps(result))
        self.assertNotIn("Another public mat", json.dumps(result))
        inv.problems.append("A private owner's malformed row")
        self.assertEqual(self.project(inv=inv), result)

    def test_not_built_product_or_empty_selection_has_no_list(self):
        self.assertIsNone(self.project([]))
        for change in ({"id": "product/precon"}, {"id": "user2/casual/a"},
                       {"completion": {"status": "building", "already_built": False}}):
            with self.subTest(change=change):
                self.assertIsNone(self.project([{**built(), **change}]))

    def test_mismatched_or_unreadable_physical_build_has_guidance(self):
        deck = built()
        deck["completion"]["already_built"] = False
        self.assertEqual(self.project([deck]), {"available": False, "reason": takealong.PHYSICAL_REQUIRED})
        deck["completion"]["already_built"] = True
        deck["take_apart"]["available"] = False
        self.assertEqual(self.project([deck]), {"available": False, "reason": takealong.FAILED})

    def test_receipts_invalidate_their_own_ticks_and_merged_kind_only_once(self):
        a, b = built(), built("casual/b", "b")
        need = {"key": "poison", "name": "Poison counters", "decks": [{"id": a["id"], "title": "A"},
                {"id": b["id"], "title": "B"}], "cover": {"state": "generic", "words": "A generic counter stands in"}}
        counters = {"needs": [need], "note": assembly_counters.NOTE}
        before = self.project([a, b], counters)
        self.assertEqual(len(before["counters"]), 1)
        self.assertNotIn("quantity", before["counters"][0])
        b["take_apart"]["sha256"] = "c" * 64
        after = self.project([a, b], counters)
        self.assertEqual(before["decks"][0], after["decks"][0])
        self.assertNotEqual(before["decks"][1]["context"], after["decks"][1]["context"])
        self.assertNotEqual(before["counters"][0]["context"], after["counters"][0]["context"])
        # Presentation for hidden kit cannot gain a label from an unrelated raw record.
        a["take_apart"]["kit"] = None
        self.assertNotIn("Shared sleeves", json.dumps(self.project([a])))

    def test_optional_failure_is_generic_and_never_an_inventory_write(self):
        with mock.patch.object(takealong, "_playmats", side_effect=ValueError("private details")), \
                mock.patch.object(takealong.common, "_log"):
            self.assertEqual(self.project(), {"available": False, "reason": takealong.FAILED})


class TakeAlongAssemblyTests(PreparationCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        identity = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        identity.__enter__()
        self.addCleanup(identity.__exit__, None, None, None)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "built", "Deck\n2 Llanowar Elves\n", built_version="target",
                  table="| Llanowar Elves | 2 | 2 | 0 | | | |\n")

    def test_ordinary_read_uses_saved_token_packing_and_never_writes(self):
        deck = ops_decks.parsed_deck(inventory.current().deck("casual/a"))
        decks.set_token_cards(deck, [decks.TokenCardLine(2, "Dog", "Beast", "tfdn", "12")])
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(self.inventory, "apply", side_effect=AssertionError("Reads never write")):
            plan = self.preview(("a", "target"))
        self.assertTrue(plan["take_along"]["available"])
        self.assertIn("Token cards: 2 Dog / Beast (TFDN) 12", plan["take_along"]["decks"][0]["lines"])
        self.assertEqual(plan["completion"]["decks"], [])
        self.assertEqual(files.render(inventory.current(), decks=True), before)

