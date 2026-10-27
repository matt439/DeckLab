"""Correcting a deck's recorded physical build from a box check, in temp data."""
import copy
import json
from unittest import mock

from decklab.lib import access, decks, inventory, pool
from decklab.lib.api import box_repair
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled, boxcheck, standins
from decklab.lib.inventory import files
from decklab.tests import test_pool as pool_fixture
from decklab.tests.test_box_check_api import ELF, MYSTIC, POISON, WHEN, BoxCheckCase

setUpModule = pool_fixture.setUpModule
tearDownModule = pool_fixture.tearDownModule


class BoxRepairCase(BoxCheckCase):
    def found(self, body, section, name, quantity, kind="card"):
        rows = self.offer()["take_apart"]["sections"][section]
        index = next(i for i, row in enumerate(rows) if row["name"] == name and row["kind"] == kind)
        next(row for row in body["rows"] if row["section"] == section and row["row"] == index)["quantity"] = quantity
        return body

    def repair(self, data, **changes):
        body = copy.deepcopy(data)
        body.update(changes)
        return box_repair.repair_box(json.dumps(body).encode())

    def refused_repair(self, status, data, **changes):
        with self.assertRaises(ApiError) as caught:
            self.repair(data, **changes)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception

    def held(self):
        p = pool.load_pool()
        return next(holder.cards for holder in p.in_use if holder.id == "casual/a")


class BoxRepairApiTests(BoxRepairCase):
    def test_preview_writes_nothing_and_shows_the_corrected_build(self):
        body = self.found(self.payload(), "Deck", ELF, 3)
        body["extras"] = [{"section": "Deck", "name": POISON, "quantity": 1}]
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(self.inventory, "apply", side_effect=AssertionError("Preview wrote data")):
            answer = self.repair(body)
        self.assertTrue(answer["preview"])
        self.assertEqual(files.render(inventory.current(), decks=True), before)
        deck_rows = {row["name"]: row["quantity"] for row in answer["sections"]["Deck"]}
        self.assertEqual(deck_rows, {ELF: 3, "Forest": 20, POISON: 1})
        self.assertEqual(answer["freed"], [{"name": ELF, "quantity": 1}])
        self.assertEqual([(row["name"], row["quantity"], row["short"]) for row in answer["held"]], [(POISON, 1, 0)])
        self.assertEqual(answer["card_count"], 26)
        self.assertEqual(len(answer["result_sha256"]), 64)

    def test_confirm_saves_build_and_date_keeping_lists_tokens_and_kit(self):
        deck = self.parsed()
        decks.set_token_cards(deck, [decks.TokenCardLine(1, "Dog", "Beast")])
        self.write_parsed(deck)
        target, owned = self.parsed().target, self.parsed().owned
        body = self.found(self.payload(), "Deck", ELF, 3)
        body["extras"] = [{"section": "Sideboard", "name": POISON, "quantity": 2}]
        preview = self.repair(body)
        self.assertEqual(preview["tokens"]["cards"], ["1 Dog // Beast"])
        answer = self.repair(body, confirm=True, result_sha256=preview["result_sha256"])
        self.assertTrue(answer["saved"])
        self.assertEqual(answer["checked_on"], WHEN)
        after = self.parsed()
        self.assertEqual((after.target, after.owned), (target, owned))
        self.assertEqual(boxcheck.checked_on(after), WHEN)
        self.assertEqual([line.text() for line in decks.token_cards(after)], ["1 Dog // Beast"])
        physical = assembled.get(after)
        self.assertEqual(physical["version"], "target")
        self.assertEqual({line.name: line.quantity for line in physical["sections"]["Deck"]}, {ELF: 3, "Forest": 20})
        self.assertEqual({line.name: line.quantity for line in physical["sections"]["Sideboard"]}, {MYSTIC: 2, POISON: 2})
        self.assertEqual(assembled.generation(after), 1)
        held = self.held()
        self.assertEqual((held[ELF], held[POISON], held[MYSTIC]), (3, 2, 2))

    def test_recorded_printings_are_kept_and_new_copies_have_none(self):
        self.deck("a", "A", "built", f"Deck\n4 {ELF} (FDN) 227\n20 Forest\n")
        body = self.found(self.payload(), "Deck", ELF, 6)
        preview = self.repair(body)
        self.repair(body, confirm=True, result_sha256=preview["result_sha256"])
        lines = [line for line in assembled.get(self.parsed())["sections"]["Deck"] if line.name == ELF]
        self.assertEqual([(line.quantity, line.set, line.number) for line in lines], [(4, "fdn", "227"), (2, None, None)])
        body = self.found(self.payload(), "Deck", ELF, 3)
        preview = self.repair(body)
        self.repair(body, confirm=True, result_sha256=preview["result_sha256"])
        lines = [line for line in assembled.get(self.parsed())["sections"]["Deck"] if line.name == ELF]
        self.assertEqual([(line.quantity, line.set) for line in lines], [(3, "fdn")])

    def test_missing_stand_in_marker_is_dropped_from_the_installed_recipe(self):
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        standins.set_stand_ins(deck, {"target": [{"for": ELF, "using": POISON, "qty": 2}], "owned": [],
                                     "built": {"version": "target", "cards": [{"for": ELF, "using": POISON, "qty": 2}]}})
        self.write_parsed(deck)
        body = self.found(self.payload(), "Deck", POISON, 1, kind="marker")
        preview = self.repair(body)
        self.assertEqual(preview["freed"], [{"name": POISON, "quantity": 1}])
        self.repair(body, confirm=True, result_sha256=preview["result_sha256"])
        after = self.parsed()
        data = standins.get_stand_ins(after)
        self.assertEqual(data["built"]["cards"], [{"for": ELF, "using": POISON, "qty": 1}])
        self.assertEqual(data["target"], [{"for": ELF, "using": POISON, "qty": 2}])  # the choice stays as written
        self.assertEqual({line.name: line.quantity for line in assembled.get(after)["sections"]["Deck"]}, {ELF: 3, "Forest": 20})
        held = self.held()
        self.assertEqual((held[ELF], held[POISON]), (2, 1))

    def test_collection_shortfall_is_reported_but_not_blocking(self):
        body = self.payload()
        body["extras"] = [{"section": "Deck", "name": POISON, "quantity": 5}]
        preview = self.repair(body)
        self.assertEqual([(row["name"], row["owned"], row["short"]) for row in preview["held"]], [(POISON, 3, 2)])

    def test_other_decks_tables_go_out_of_date_and_are_returned(self):
        self.deck("b", "B", "building", f"Deck\n4 {MYSTIC}\n",
                  table=f"| {MYSTIC} | 4 | 0 | 4 |  |  | 2 in use in A |\n")
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 8),
                       (MYSTIC, "cmm", "648", "nonfoil", 2), (POISON, "mkm", "170", "nonfoil", 3))
        self.assertNotIn("casual/b", [entry["id"] for entry in pool.stale_tables()])
        body = self.found(self.payload(), "Sideboard", MYSTIC, 0)
        preview = self.repair(body)
        answer = self.repair(body, confirm=True, result_sha256=preview["result_sha256"])
        self.assertIn("casual/b", [entry["id"] for entry in answer["stale_tables"]])

    def test_matching_box_changed_preview_and_empty_main_refuse(self):
        before = self.record().text
        self.refused_repair(400, self.payload())
        body = self.found(self.payload(), "Deck", ELF, 3)
        self.refused_repair(409, body, confirm=True, result_sha256="0" * 64)
        self.refused_repair(400, body, confirm=True)
        empty = self.found(self.found(self.payload(), "Deck", ELF, 0), "Deck", "Forest", 0)
        self.assertIn("take the deck apart", self.refused_repair(400, empty).message)
        self.assertEqual(self.record().text, before)

    def test_stale_deck_and_reader_without_edit_refuse(self):
        body = self.found(self.payload(), "Deck", ELF, 3)
        self.write("decks/casual/a.md", self.record().text.replace("# A\n", "# Renamed A\n", 1))
        self.refused_repair(409, body)
        deck = self.parsed()
        decks.set_player(deck, "user")
        self.write_parsed(deck)
        body = self.found(self.payload(), "Deck", ELF, 3)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.refused_repair(403, body, profile="user1")

    def test_extra_card_named_like_an_installed_stand_in_refuses_without_writes(self):
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        standins.set_stand_ins(deck, {"target": [], "owned": [],
                                     "built": {"version": "target", "cards": [{"for": ELF, "using": POISON, "qty": 1}]}})
        self.write_parsed(deck)
        before = self.record().text
        body = self.payload()
        body["extras"] = [{"section": "Deck", "name": POISON, "quantity": 1}]
        self.assertIn("stand-ins", self.refused_repair(400, body).message)
        self.assertEqual(self.record().text, before)
