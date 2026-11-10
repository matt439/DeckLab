"""A sealed product's bonus card (E6-S29): lib/sealed.py's reading of MTGJSON's set files, the
product lists' extras section (rules.product_reads_as_decks, decks._product_lines), the pool
counting a bonus card as on the way, a receipt adding it, the command line's --from-mtgjson and
missing-bonus notes, and GET /api/precons/product.

MTGJSON is never reached: the set file is a small JSON here, handed to sealed._fetch_set.

Run: python scripts/test_fixtures.py decklab.tests.test_sealed
"""
import contextlib
import gzip
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import inventory, precons, sealed
from decklab.lib.inventory import files, receive, rules
from decklab.lib.inventory.model import Product, ProductItem
from decklab.tests import test_inventory_contract as contract
from decklab.tests import test_inventory_orders as fixture


def contents_card(name, number, foil=False, code="tst"):
    item = {"finishes": ["foil" if foil else "nonfoil"], "name": name, "number": number, "set": code,
            "uuid": f"c{number}".ljust(36, "0")}
    if foil:
        item["foil"] = True
    return item


def uuid(n):
    return f"{n:08d}-0000-0000-0000-000000000000"


# A set file: a drop (and its foil edition) with a bonus card, a Commander deck with a random sample
# pack and a deck box, a drop with only a random bonus sheet, a product with no deck, and a deck in
# two editions that don't agree on their fixed cards.
SET_FILE = {"meta": {"date": "2026-11-01"}, "data": {
    "code": "TST",
    "cards": [{"uuid": f"u{n}", "setCode": "TST", "number": str(n)} for n in range(1, 10)],
    "decks": [
        {"name": "Farm Drop", "sealedProductUuids": [uuid(1)],
         "mainBoard": [{"uuid": "u1", "count": 1}, {"uuid": "u2", "count": 1}]},
        {"name": "Farm Drop Foil Edition", "sealedProductUuids": [uuid(2)],
         "mainBoard": [{"uuid": "u1", "count": 1, "isFoil": True}, {"uuid": "u2", "count": 1, "isFoil": True}]},
        {"name": "Dino Deck", "sealedProductUuids": [uuid(3)],
         "commander": [{"uuid": "u3", "count": 1}], "mainBoard": [{"uuid": "u4", "count": 99}]},
        {"name": "Random Drop", "sealedProductUuids": [uuid(4)], "mainBoard": [{"uuid": "u5", "count": 1}]},
        {"name": "Two Editions", "sealedProductUuids": [uuid(6), uuid(7)], "mainBoard": [{"uuid": "u6", "count": 1}]},
        {"name": "Unsold", "sealedProductUuids": [], "mainBoard": [{"uuid": "u7", "count": 1}]},
    ],
    "sealedProduct": [
        {"uuid": uuid(1), "name": "Drop Farm", "contents": {
            "card": [contents_card("Sol Ring", "901")], "deck": [{"name": "Farm Drop", "set": "tst"}]}},
        {"uuid": uuid(2), "name": "Drop Farm Foil", "contents": {
            "card": [contents_card("Sol Ring", "901", foil=True)],
            "deck": [{"name": "Farm Drop Foil Edition", "set": "tst"}]}},
        {"uuid": uuid(3), "name": "Commander Deck Dino", "contents": {
            "deck": [{"name": "Dino Deck", "set": "tst"}],
            "sealed": [{"count": 1, "name": "Test Collector Booster Sample Pack", "set": "tst", "uuid": uuid(9)}],
            "other": [{"name": "Deck Box"}]}},
        {"uuid": uuid(4), "name": "Drop Random", "contents": {
            "deck": [{"name": "Random Drop", "set": "tst"}], "pack": [{"code": "bonus-random-drop", "set": "tst"}]}},
        {"uuid": uuid(5), "name": "A Promo", "contents": {"card": [contents_card("Opt", "950")]}},
        {"uuid": uuid(6), "name": "Edition A", "contents": {
            "card": [contents_card("Sol Ring", "902"), contents_card("Opt", "903")],
            "deck": [{"name": "Two Editions", "set": "tst"}]}},
        {"uuid": uuid(7), "name": "Edition B", "contents": {
            "card": [contents_card("Sol Ring", "902")], "deck": [{"name": "Two Editions", "set": "tst"}],
            "variable": [{"configs": []}]}},
    ]}}


def deck_card(name, number, count=1, foil=False):
    return {"name": name, "setCode": "TST", "number": number, "count": count, "isFoil": foil}


FARM_DROP = {"name": "Farm Drop", "code": "TST", "type": "Secret Lair Drop", "sealedProductUuids": [uuid(1)],
             "mainBoard": [deck_card("Llanowar Elves", "1"), deck_card("Elvish Mystic", "2")]}
DINO_DECK = {"name": "Dino Deck", "code": "TST", "type": "Commander Deck", "sealedProductUuids": [uuid(3)],
             "commander": [deck_card("Ghalta, Primal Hunger", "3")],
             "mainBoard": [deck_card("Forest", "4", 99)],
             "displayCommander": [deck_card("Ghalta, Primal Hunger", "30")]}
FARM_ENTRY = {"file": "FarmDrop_TST", "name": "Farm Drop", "code": "tst", "type": "Secret Lair Drop",
              "set_name": "", "released": "", "source": ""}
DINO_ENTRY = {"file": "DinoDeck_TST", "name": "Dino Deck", "code": "tst", "type": "Commander Deck",
              "set_name": "", "released": "", "source": ""}


class SealedCase(unittest.TestCase):
    """sealed's cache in a temporary folder, its fetch handing back SET_FILE (counted)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = Path(temp.name)
        self.fetched = []

        def fetch(code):
            self.fetched.append(code)
            return json.loads(json.dumps(SET_FILE))

        for target, name, value in ((sealed, "CACHE", self.cache), (sealed, "_fetch_set", fetch),
                                    (precons, "_failed", {})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class ReadTests(SealedCase):

    def test_the_extract_keeps_products_holding_a_deck_and_their_decks_printings(self):
        kept = sealed.extract("tst")
        self.assertEqual(kept["code"], "TST")
        self.assertEqual(kept["date"], "2026-11-01")
        self.assertNotIn(uuid(5), kept["products"])                  # no deck: a promo, not a box
        self.assertEqual(kept["products"][uuid(1)]["fixed"],
                         [{"name": "Sol Ring", "set": "tst", "number": "901", "finish": "nonfoil", "count": 1}])
        self.assertEqual(kept["products"][uuid(2)]["fixed"][0]["finish"], "foil")
        self.assertEqual(kept["products"][uuid(3)]["random"], ["Test Collector Booster Sample Pack"])
        self.assertEqual(kept["products"][uuid(3)]["other"], ["Deck Box"])
        self.assertEqual(kept["products"][uuid(4)]["random"], ["a random bonus card"])
        farm = next(d for d in kept["decks"] if d["name"] == "Farm Drop")
        self.assertEqual(farm["printings"], [["tst", "1", "nonfoil", 1], ["tst", "2", "nonfoil", 1]])
        foil = next(d for d in kept["decks"] if d["name"] == "Farm Drop Foil Edition")
        self.assertEqual(foil["printings"][0][2], "foil")
        self.assertNotIn("Unsold", [d["name"] for d in kept["decks"]])   # in no product

    def test_the_extract_is_kept_a_week_and_read_without_fetching(self):
        self.assertIsNone(sealed.extract("tst", fetch=False))        # nothing kept, nothing fetched
        sealed.extract("tst")
        sealed.extract("tst")
        self.assertEqual(self.fetched, ["TST"])
        self.assertIsNotNone(sealed.extract("TST", fetch=False))
        path = self.cache / "TST.json"
        old = time.time() - sealed.TTL - 60
        os.utime(path, (old, old))
        sealed.extract("tst")
        self.assertEqual(self.fetched, ["TST", "TST"])

    def test_an_old_extract_is_used_when_mtgjson_cant_be_reached(self):
        sealed.extract("tst")
        path = self.cache / "TST.json"
        old = time.time() - sealed.TTL - 60
        os.utime(path, (old, old))
        with mock.patch.object(sealed, "_fetch_set", side_effect=OSError("offline")):
            self.assertEqual(sealed.extract("tst")["code"], "TST")
        path.unlink()
        precons._failed.clear()
        with mock.patch.object(sealed, "_fetch_set", side_effect=OSError("offline")):
            with self.assertRaises(precons.PreconError):
                sealed.extract("tst")
            with self.assertRaisesRegex(precons.PreconError, "a few minutes ago"):
                sealed.extract("tst")                                # resting: not asked again

    def test_a_kept_extract_without_the_deck_is_fetched_again_once(self):
        older = json.loads(json.dumps(SET_FILE))
        older["data"]["sealedProduct"] = [p for p in older["data"]["sealedProduct"] if p["uuid"] != uuid(1)]
        with mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(older))):
            sealed.extract("tst")                                    # kept before the drop was listed
        found = sealed.contents(FARM_ENTRY, FARM_DROP)
        self.assertEqual(self.fetched, ["TST"])                      # the young extract fetched again
        self.assertEqual([sealed.describe(c) for c in found["fixed"]], ["Sol Ring (TST 901)"])
        self.assertEqual(sealed.contents(FARM_ENTRY, FARM_DROP)["products"], ["Drop Farm"])
        self.assertEqual(self.fetched, ["TST"])                      # now it holds it: not again
        unknown = dict(FARM_ENTRY, name="Not Listed")
        self.assertEqual(sealed.contents(unknown, {"sealedProductUuids": [uuid(99)]})["fixed"], [])
        self.assertEqual(self.fetched, ["TST", "TST"])               # tried once, then nothing to add

    def test_a_hand_written_list_of_a_new_drop_fetches_an_old_extract_again(self):
        older = json.loads(json.dumps(SET_FILE))
        older["data"]["decks"] = [d for d in older["data"]["decks"] if d["name"] != "Farm Drop"]
        with mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(older))):
            sealed.extract("tst")
        hand = [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "nonfoil", "quantity": "1"},
                {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil", "quantity": "1"}]
        self.assertEqual(sealed.missing_cards(hand), [])             # a day old at most: not fetched
        self.assertEqual(self.fetched, [])
        old = time.time() - precons.TTL - 60
        os.utime(self.cache / "TST.json", (old, old))
        self.assertEqual([m["deck"] for m in sealed.missing_cards(hand)], ["Farm Drop"])
        self.assertEqual(self.fetched, ["TST"])

    def test_a_token_listed_as_a_contents_card_is_never_a_bonus_card(self):
        tokened = json.loads(json.dumps(SET_FILE))
        drop = next(p for p in tokened["data"]["sealedProduct"] if p["uuid"] == uuid(1))
        drop["contents"]["card"].append(dict(contents_card("Food", "918"), token=True))
        with mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(tokened))):
            found = sealed.contents(FARM_ENTRY, FARM_DROP)
        self.assertEqual([sealed.describe(c) for c in found["fixed"]], ["Sol Ring (TST 901)"])
        self.assertEqual(found["other"], ["token card: Food"])

    def test_an_unexpected_shape_is_read_as_nothing_there(self):
        odd = json.loads(json.dumps(SET_FILE))
        odd["data"]["decks"] = {"not": "a list"}
        odd["data"]["sealedProduct"][0]["contents"]["card"] = "nope"
        with mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(odd))):
            kept = sealed.extract("tst")
        self.assertEqual((kept["decks"], kept["products"][uuid(1)]["fixed"]), ([], []))

    def test_a_bad_set_code_is_never_fetched(self):
        self.assertIsNone(sealed.extract("../x"))
        self.assertEqual(self.fetched, [])

    def test_a_gzip_set_file_is_read_within_its_limit(self):
        data = gzip.compress(json.dumps(SET_FILE).encode())
        with mock.patch.object(precons, "_fetch", return_value=data), mock.patch.object(sealed, "MAX_JSON_BYTES", 100):
            with self.assertRaisesRegex(precons.PreconError, "bigger than"):
                _real_fetch_set("TST")
        with mock.patch.object(precons, "_fetch", return_value=data):
            self.assertEqual(_real_fetch_set("TST")["data"]["code"], "TST")
        with mock.patch.object(precons, "_fetch", return_value=b"not gzip"):
            with self.assertRaises(ValueError):
                _real_fetch_set("TST")

    def test_contents_of_a_deck_fixed_varies_random_other(self):
        found = sealed.contents(FARM_ENTRY, FARM_DROP)
        self.assertEqual(found["products"], ["Drop Farm"])
        self.assertEqual([sealed.describe(c) for c in found["fixed"]], ["Sol Ring (TST 901)"])
        dino = sealed.contents(DINO_ENTRY, DINO_DECK)
        self.assertEqual((dino["fixed"], dino["random"], dino["other"]),
                         ([], ["Test Collector Booster Sample Pack"], ["Deck Box"]))
        two = sealed.contents(dict(FARM_ENTRY, name="Two Editions"), {"sealedProductUuids": [uuid(6), uuid(7)]})
        self.assertEqual([sealed.describe(c) for c in two["fixed"]], ["Sol Ring (TST 902)"])
        self.assertEqual([sealed.describe(c) for c in two["varies"]], ["Opt (TST 903)"])
        self.assertEqual(two["random"], ["contents that vary from box to box"])
        # A deck file without its product's uuid is matched by its name in the set file.
        self.assertEqual(sealed.contents(FARM_ENTRY, {})["products"], ["Drop Farm"])
        self.assertIsNone(sealed.contents(dict(FARM_ENTRY, code="zzz"), FARM_DROP, fetch=False))


def _real_fetch_set(code):
    """sealed._fetch_set as written (SealedCase patches the module's)."""
    return _ORIGINAL_FETCH_SET(code)


_ORIGINAL_FETCH_SET = sealed._fetch_set


class ProductListTests(SealedCase):

    def test_a_drop_is_cards_only_with_its_bonus_card_in_extras_and_an_arrival_check(self):
        made = sealed.product_list(FARM_ENTRY, FARM_DROP, sealed.contents(FARM_ENTRY, FARM_DROP))
        self.assertEqual(made["columns"], ["name", "set", "collector_number", "finish", "quantity", "section", "notes"])
        self.assertEqual([(r["name"], r["section"]) for r in made["rows"]],
                         [("Llanowar Elves", ""), ("Elvish Mystic", ""), ("Sol Ring", "extras")])
        self.assertEqual(made["rows"][-1]["notes"], "bonus card in Farm Drop")
        self.assertEqual(made["checks"], ["Confirm Sol Ring (TST 901) was in the box: it's the expected bonus card"])
        self.assertEqual((made["name"], made["format"]), ("Farm Drop", "Secret Lair drop (2 cards + 1 extra)"))
        self.assertFalse(rules.product_reads_as_decks(made["columns"], made["rows"]))

    def test_without_its_bonus_card_a_drop_has_no_section_column(self):
        made = sealed.product_list(FARM_ENTRY, FARM_DROP, sealed.contents(FARM_ENTRY, FARM_DROP), include_bonus=False)
        self.assertEqual(made["columns"], ["name", "set", "collector_number", "finish", "quantity"])
        self.assertEqual((len(made["rows"]), made["checks"]), (2, []))
        self.assertEqual([b["words"] for b in made["bonus"]], ["Sol Ring (TST 901)"])   # still named
        self.assertEqual(made["format"], "Secret Lair drop (2 cards)")

    def test_a_deck_keeps_its_sections_and_a_playable_display_commander_goes_in_extras(self):
        found = sealed.contents(DINO_ENTRY, DINO_DECK)
        made = sealed.product_list(DINO_ENTRY, DINO_DECK, found, pickable=lambda line: True)
        self.assertEqual([(r["name"], r["section"], r["quantity"]) for r in made["rows"]],
                         [("Ghalta, Primal Hunger", "commander", "1"), ("Forest", "deck", "99"),
                          ("Ghalta, Primal Hunger", "extras", "1")])
        self.assertTrue(rules.product_reads_as_decks(made["columns"], made["rows"]))
        self.assertEqual(made["random"], ["Test Collector Booster Sample Pack"])
        self.assertEqual(made["format"], "Commander precon (100 cards + 1 extra)")
        oversized = sealed.product_list(DINO_ENTRY, DINO_DECK, found, pickable=lambda line: False)
        self.assertEqual(len(oversized["rows"]), 2)
        self.assertIn("1 display commander (Ghalta, Primal Hunger), not a card to play with", oversized["left_out"])
        self.assertEqual(oversized["format"], "Commander precon (100 cards)")

    def test_a_hand_written_list_without_its_bonus_card_is_warned_about(self):
        hand = [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "nonfoil", "quantity": "1"},
                {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil", "quantity": "1"}]
        warnings = sealed.missing_bonus(hand)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Farm Drop is expected to come with a bonus card, 1 Sol Ring (TST 901)", warnings[0])
        foil = [dict(row, finish="foil") for row in hand]
        self.assertIn("Sol Ring (TST 901, foil)", sealed.missing_bonus(foil)[0])
        listed = hand + [dict(hand[0], name="Sol Ring", collector_number="901", section="extras")]
        self.assertEqual(sealed.missing_bonus(listed), [])
        self.assertEqual(sealed.missing_bonus(hand[:1]), [])         # not the whole deck
        many = [dict(hand[0], set=code) for code in ("aa", "bb", "cc", "dd", "ee")]
        self.assertEqual(sealed.missing_bonus(many), [])             # too many sets to look up
        self.assertEqual(sealed.missing_bonus([dict(hand[0], set="tst", collector_number="4")]), [])   # no bonus

    def test_the_missing_bonus_card_added_in_extras(self):
        hand = [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "nonfoil", "quantity": "1"},
                {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil", "quantity": "1"}]
        missing = sealed.missing_cards(hand)
        self.assertEqual([(m["deck"], sealed.describe(m["card"])) for m in missing], [("Farm Drop", "Sol Ring (TST 901)")])
        columns, rows = sealed.with_bonus(["name", "set", "collector_number", "finish", "quantity"], hand, missing)
        self.assertEqual(columns[-1], "section")
        self.assertEqual([(r["name"], r["section"]) for r in rows],
                         [("Llanowar Elves", ""), ("Elvish Mystic", ""), ("Sol Ring", "extras")])
        self.assertFalse(rules.product_reads_as_decks(columns, rows))       # still cards only
        self.assertEqual(sealed.missing_cards(rows), [])
        noted, rows = sealed.with_bonus(["section", "name", "set", "collector_number", "finish", "quantity", "notes"],
                                        [dict(r, section="deck", notes="") for r in hand], missing)
        self.assertEqual(noted.count("section"), 1)
        self.assertEqual(rows[-1]["notes"], "bonus card in Farm Drop")
        # A list that read as one deck with blank sections stays a deck once its bonus card is in extras.
        blank = ["section", "name", "set", "collector_number", "finish", "quantity"]
        columns, rows = sealed.with_bonus(blank, [dict(r, section="") for r in hand], missing)
        self.assertEqual([r["section"] for r in rows], ["deck", "deck", "extras"])
        self.assertTrue(rules.product_reads_as_decks(columns, rows))

    def test_a_list_matching_both_editions_by_number_proposes_no_finish(self):
        # One row foil, one nonfoil: the nonfoil box and its foil edition match equally well.
        mixed = [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "foil", "quantity": "1"},
                 {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil", "quantity": "1"}]
        self.assertEqual(sealed.missing_cards(mixed), [])
        # Mostly foil with one typo: the foil edition matches more finishes, so its foil bonus card.
        three = json.loads(json.dumps(SET_FILE))
        for deck in three["data"]["decks"][:2]:
            deck["mainBoard"].append(dict(deck["mainBoard"][0], uuid="u8"))
        with mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(three))):
            mostly = [dict(r, finish="foil") for r in mixed] + [
                {"name": "Opt", "set": "tst", "collector_number": "8", "finish": "nonfoil", "quantity": "1"}]
            self.assertEqual([sealed.describe(m["card"]) for m in sealed.missing_cards(mostly)],
                             ["Sol Ring (TST 901, foil)"])

    def test_shoppings_preview_offers_the_list_with_its_bonus_card(self):
        from decklab.lib.api import shopping_orders
        product = {"columns": ["name", "set", "collector_number", "finish", "quantity"],
                   "rows": [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "nonfoil",
                             "quantity": "1"},
                            {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil",
                             "quantity": "1"}]}
        fix = shopping_orders._bonus_fix(product)["bonus_missing"]
        self.assertEqual(fix["cards"], ["Farm Drop: 1 Sol Ring (TST 901)"])
        self.assertEqual(fix["csv"].splitlines(), ["name,set,collector_number,finish,quantity,section",
                                                   "Llanowar Elves,tst,1,nonfoil,1,", "Elvish Mystic,tst,2,nonfoil,1,",
                                                   "Sol Ring,tst,901,nonfoil,1,extras"])
        self.assertEqual(fix["checks"], ["Confirm Sol Ring (TST 901) was in the box: it's the expected bonus card"])
        self.assertEqual(shopping_orders._bonus_fix({"columns": product["columns"], "rows": product["rows"][:1]}), {})
        with mock.patch.object(sealed, "_fetch_set", side_effect=OSError("offline")), \
                mock.patch.object(sealed, "CACHE", self.cache / "empty"):
            self.assertEqual(shopping_orders._bonus_fix(product), {})

    def test_the_order_preview_offers_it_unless_it_was_left_out_on_purpose(self):
        from decklab.lib import access, config
        from decklab.lib.api import shopping_orders
        case = contract.build_tree(fixture.orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        backend = files.FileInventory(case.inventory.root)
        with contextlib.ExitStack() as stack:
            stack.enter_context(contract.fixture_world())
            stack.enter_context(mock.patch.object(sealed, "CACHE", self.cache))
            stack.enter_context(mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(SET_FILE))))
            stack.enter_context(mock.patch.object(config, "REPO", case.inventory.root))
            stack.enter_context(inventory.use(backend))
            stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))
            self.addCleanup(shopping_orders._previews.clear)
            product = {"stem": "farm-drop", "csv": "name,set,collector_number,finish,quantity\n"
                                                   "Llanowar Elves,tst,1,nonfoil,1\nElvish Mystic,tst,2,nonfoil,1\n"}

            def preview(**extra):
                return shopping_orders.preview_order(json.dumps({
                    "profile": "matt", "expect": backend.load().revision,
                    "record": {"id": "2026-11-10-drop"}, "product": dict(product, **extra)}))

            answer = preview()
            self.assertEqual(answer["bonus_missing"]["cards"], ["Farm Drop: 1 Sol Ring (TST 901)"])
            self.assertIn("Sol Ring,tst,901,nonfoil,1,extras", answer["bonus_missing"]["csv"])
            self.assertNotIn("bonus_missing", preview(skip_bonus=True))

    def test_a_save_reads_only_what_is_kept(self):
        hand = [{"name": "Llanowar Elves", "set": "tst", "collector_number": "1", "finish": "nonfoil", "quantity": "1"},
                {"name": "Elvish Mystic", "set": "tst", "collector_number": "2", "finish": "nonfoil", "quantity": "1"}]
        self.assertEqual(sealed.missing_bonus(hand, fetch=False), [])
        self.assertEqual(self.fetched, [])
        with mock.patch.object(sealed, "_fetch_set", side_effect=OSError("offline")):
            self.assertEqual(sealed.missing_bonus(hand), [])          # unreadable: nothing said


class ExtrasSectionTests(unittest.TestCase):

    def product(self, columns, rows):
        return Product("p", tuple(columns),
                       tuple(ProductItem.make(row, tuple(columns), line=n) for n, row in enumerate(rows, 2)))

    def test_which_lists_read_as_decks(self):
        row = {"name": "Sol Ring", "set": "tst", "collector_number": "1", "finish": "nonfoil", "quantity": "1"}
        base = ["name", "set", "collector_number", "finish", "quantity"]
        cases = [(base, [row], False),
                 (base + ["section"], [dict(row, section="")], True),                 # as before E6-S29
                 (base + ["section"], [dict(row, section=""), dict(row, section="extras")], False),
                 (base + ["section"], [dict(row, section="deck"), dict(row, section="Extras")], True),
                 (base + ["deck"], [dict(row, deck="A")], True),
                 (base + ["deck", "section"], [dict(row, deck="A", section="extras")], True)]
        for columns, rows, decks in cases:
            with self.subTest(columns=columns, rows=rows):
                full = [{c: r.get(c, "") for c in columns} for r in rows]
                self.assertEqual(rules.product_reads_as_decks(columns, full), decks)
                self.assertEqual(self.product(columns, full).is_deck, decks)

    def test_extras_rows_are_never_deck_lines(self):
        from decklab.lib import decks
        columns = ["section", "name", "set", "collector_number", "finish", "quantity"]
        rows = [{"section": "commander", "name": "Ghalta, Primal Hunger", "set": "tst", "collector_number": "3",
                 "finish": "nonfoil", "quantity": "1"},
                {"section": "extras", "name": "Sol Ring", "set": "tst", "collector_number": "901",
                 "finish": "foil", "quantity": "1"}]
        lines = decks._product_lines(self.product(columns, rows))
        self.assertEqual([(section, line.name) for _, section, line in lines], [("Commander", "Ghalta, Primal Hunger")])
        cards_only = [dict(rows[1]), dict(rows[1], section="", collector_number="2", finish="nonfoil")]
        self.assertIsNone(decks._product_lines(self.product(columns, cards_only)))


BONUS_COLUMNS = ["name", "set", "collector_number", "finish", "quantity", "section", "notes"]
BONUS_ROWS = [{"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
               "quantity": "1", "section": "", "notes": ""},
              {"name": "Pick Your Poison", "set": "mkm", "collector_number": "170", "finish": "nonfoil",
               "quantity": "1", "section": "extras", "notes": "bonus card in Farm Drop"}]


class InventoryTests(unittest.TestCase):
    """A product with a bonus card on the files backend: on the way, then received."""

    def setUp(self):
        case = contract.build_tree(fixture.orders_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = files.FileInventory(case.inventory.root)
        stack = contextlib.ExitStack()
        stack.enter_context(contract.fixture_world())
        stack.enter_context(inventory.use(self.backend))
        self.addCleanup(stack.close)
        inventory.apply(inventory.Op("order.add", {
            "record": {"id": "2026-11-10-drop", "seller": "Shop", "ordered_on": "2026-11-10", "sources": [], "notes": ""},
            "product": {"stem": "farm-drop", "columns": BONUS_COLUMNS, "rows": BONUS_ROWS, "name": "Farm Drop",
                        "checks": ["Confirm Pick Your Poison (MKM 170) was in the box: it's the expected bonus card"]},
            "repo": str(case.inventory.root)}), fixture.CLAUDE, "Order a drop")

    def test_the_bonus_card_counts_as_on_the_way_and_the_product_isnt_a_deck(self):
        from decklab.lib import decks, pool
        loaded = pool.load_pool()
        self.assertIn(("farm-drop", 1), [(source.get("product_id"), source["quantity"])
                                         for source in loaded.incoming_sources["Pick Your Poison"]])
        self.assertNotIn("product/farm-drop", [d["id"] for d in decks._product_decks()])
        self.assertFalse(self.backend.load().product("farm-drop").is_deck)

    def test_a_receipt_adds_the_bonus_card_to_the_collection(self):
        inventory.apply(receive.op("2026-11-10-drop", [{"id": "farm-drop", "intact": "no"}], "2026-11-12"),
                        fixture.CLAUDE, "Arrived")
        rows = {r.text("name"): r for r in self.backend.load().collection().rows}
        self.assertEqual(rows["Pick Your Poison"].text("quantity"), "1")
        self.assertEqual((rows["Pick Your Poison"].text("condition"), rows["Pick Your Poison"].text("language")),
                         ("", ""))
        self.assertIn("bonus card in Farm Drop", rows["Pick Your Poison"].text("notes"))

    def test_a_cards_only_product_cant_be_received_intact(self):
        from decklab.lib.state import Invalid
        with self.assertRaisesRegex(Invalid, "no deck lists"):
            inventory.apply(receive.op("2026-11-10-drop", [{"id": "farm-drop", "intact": "yes"}], "2026-11-12"),
                            fixture.CLAUDE, "Arrived")

    def test_every_extras_row_of_a_new_product_gets_its_arrival_check(self):
        inventory.apply(inventory.Op("product.add", {"order": "2026-11-10-drop", "product": {
            "stem": "hand-drop", "columns": BONUS_COLUMNS, "rows": [dict(r) for r in BONUS_ROWS],
            "checks": ["Count the cards"]}}), fixture.CLAUDE, "A hand-written list")
        part = next(c for c in self.backend.load().order("2026-11-10-drop").components if c.id == "hand-drop")
        self.assertEqual(part.checks, ["Count the cards",
                                       "Confirm Pick Your Poison (MKM 170) was in the box: it's the expected bonus card"])
        self.assertEqual(self.backend.load().order("2026-11-10-drop").components[0].checks,
                         ["Confirm Pick Your Poison (MKM 170) was in the box: it's the expected bonus card"])   # once


class CommandLineTests(unittest.TestCase):
    setUp = fixture.CommandLineTests.setUp
    run_cli = fixture.CommandLineTests.run_cli
    file = fixture.CommandLineTests.file

    def published(self, entry=FARM_ENTRY, data=None):
        """MTGJSON as the command line reads it: one listed drop whose bonus card is Pick Your Poison."""
        data = data or dict(FARM_DROP, mainBoard=[{"name": "Llanowar Elves", "setCode": "FDN", "number": "227",
                                                   "count": 1}])
        found = {"products": ["Drop Farm"], "varies": [], "random": ["a random booster (x)"], "other": ["Deck Box"],
                 "fixed": [{"name": "Pick Your Poison", "set": "mkm", "number": "170", "finish": "nonfoil", "count": 1}]}
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(precons, "find", return_value=entry))
        stack.enter_context(mock.patch.object(precons, "deck", return_value=data))
        stack.enter_context(mock.patch.object(sealed, "contents", return_value=found))
        return stack

    def test_order_add_from_mtgjson_lists_the_bonus_card_in_extras_with_its_check(self):
        with self.published():
            code, out, err = self.run_cli("order", "add", "--id", "2026-11-10-drop", "--product", "farm-drop",
                                          "--from-mtgjson", "FarmDrop_TST", "-m", "Order the drop")
        self.assertEqual(code, 0, err)
        self.assertIn("Filled from MTGJSON's Farm Drop (Secret Lair Drop): 2 cards in 2 rows.", out)
        self.assertIn("Bonus card, in the extras section: 1 Pick Your Poison (MKM 170)", out)
        self.assertIn("Random, not added: a random booster (x)", out)
        self.assertIn("Not a card: Deck Box", out)
        inv = self.backend.load()
        product = inv.product("farm-drop")
        self.assertEqual([(r.text("name"), r.text("section")) for r in product.items],
                         [("Llanowar Elves", ""), ("Pick Your Poison", "extras")])
        part = inv.order("2026-11-10-drop").components[0]
        self.assertEqual(part.checks, ["Confirm Pick Your Poison (MKM 170) was in the box: it's the expected bonus card"])

    def test_no_bonus_cards_leaves_it_out(self):
        with self.published():
            code, out, err = self.run_cli("order", "add", "--id", "2026-11-10-drop", "--product", "farm-drop",
                                          "--from-mtgjson", "FarmDrop_TST", "--no-bonus-cards", "--name", "Mine",
                                          "-m", "Order the drop")
        self.assertEqual(code, 0, err)
        self.assertIn("Left out (--no-bonus-cards): 1 Pick Your Poison (MKM 170)", out)
        product = self.backend.load().product("farm-drop")
        self.assertEqual(product.columns, ("name", "set", "collector_number", "finish", "quantity"))
        self.assertEqual(self.backend.load().order("2026-11-10-drop").components[0].checks, [])

    def test_name_and_format_default_to_mtgjsons_and_the_flags_win(self):
        # The files backend keeps no product names, so the operation the command line plans is read.
        from decklab.db import inv_orders
        for extra, expected in (((), ("Farm Drop", "Secret Lair drop (1 cards + 1 extra)")),
                                (("--name", "Mine", "--format", "Drop"), ("Mine", "Drop"))):
            with self.subTest(extra=extra), self.published(), \
                    mock.patch.object(inv_orders, "_run", return_value=0) as run:
                code, _, err = self.run_cli("order", "add", "--id", "2026-11-10-drop", "--product", "farm-drop",
                                            "--from-mtgjson", "FarmDrop_TST", *extra, "-m", "Order the drop")
                self.assertEqual(code, 0, err)
                product = run.call_args.args[1].params["product"]
                self.assertEqual((product["name"], product["format"]), expected)

    def test_product_add_from_mtgjson(self):
        with self.published():
            code, out, err = self.run_cli("product", "add", "farm-drop", "--order", "2026-10-07-shop-a",
                                          "--from-mtgjson", "FarmDrop_TST", "-m", "Add the drop")
        self.assertEqual(code, 0, err)
        inv = self.backend.load()
        self.assertEqual([r.text("section") for r in inv.product("farm-drop").items], ["", "extras"])
        part = next(c for c in inv.order("2026-10-07-shop-a").components if c.id == "farm-drop")
        self.assertEqual(len(part.checks), 1)

    def test_the_options_that_dont_go_together_are_refused(self):
        csv = self.file("p.csv", "name,set,collector_number,finish,quantity\nSol Ring,ecc,57,nonfoil,1\n")
        for args in (("order", "add", "--id", "x", "--product", "p", "--product-csv", csv, "--from-mtgjson", "F"),
                     ("order", "add", "--id", "x", "--product", "p", "--product-csv", csv, "--no-bonus-cards"),
                     ("order", "add", "--id", "x", "--from-mtgjson", "F"),
                     ("product", "add", "p", "--order", "2026-10-07-shop-a"),
                     ("product", "add", "p", "--order", "2026-10-07-shop-a", "--csv", csv, "--from-mtgjson", "F")):
            with self.subTest(args=args):
                code, _, err = self.run_cli(*args, "-m", "x")
                self.assertEqual(code, 1)
                self.assertTrue(err)

    def test_an_unknown_file_is_refused(self):
        with mock.patch.object(precons, "find", return_value=None):
            code, _, err = self.run_cli("order", "add", "--id", "2026-11-10-x", "--product", "p",
                                        "--from-mtgjson", "Nope_TST", "-m", "x")
        self.assertEqual(code, 1)
        self.assertIn("collection precons --products", err)

    def test_a_hand_written_list_without_its_bonus_card_gets_a_note(self):
        csv = self.file("p.csv", "name,set,collector_number,finish,quantity\nLlanowar Elves,fdn,227,nonfoil,1\n")
        words = "Farm Drop is expected to come with a bonus card, 1 Pick Your Poison (MKM 170), ..."
        with mock.patch.object(sealed, "missing_bonus", return_value=[words]) as missing:
            code, _, err = self.run_cli("order", "add", "--id", "2026-11-10-x", "--product", "p",
                                        "--product-csv", csv, "-m", "x", "--dry-run")
            self.assertEqual(code, 0)
            self.assertIn(f"Note: {words}", err)
            self.assertTrue(missing.call_args.kwargs["fetch"])                    # a dry run may fetch
            code, _, err = self.run_cli("order", "add", "--id", "2026-11-10-x", "--product", "p",
                                        "--product-csv", csv, "-m", "x")
            self.assertEqual(code, 0)
            self.assertFalse(missing.call_args.kwargs["fetch"])                   # a save reads what's kept
            for args in (("product", "add", "q", "--order", "2026-10-07-shop-a", "--csv", csv),
                         ("product", "edit", "precon", "--csv", csv)):
                with self.subTest(args=args):
                    code, _, err = self.run_cli(*args, "-m", "x", "--dry-run")
                    self.assertEqual(code, 0, err)
                    self.assertIn(f"Note: {words}", err)
                    self.assertTrue(missing.call_args.kwargs["fetch"])


class DeckListTests(unittest.TestCase):

    def test_secret_lair_drops_are_listed_only_for_products(self):
        listed = {"date": "2026-11-01", "decks": [dict(FARM_ENTRY), dict(DINO_ENTRY)]}
        with mock.patch.object(precons, "_load", return_value=listed), mock.patch.object(precons, "_set_names",
                                                                                         return_value={}):
            self.assertEqual([d["file"] for d in precons.deck_list()["decks"]], ["DinoDeck_TST"])
            self.assertEqual([d["file"] for d in precons.deck_list(products=True)["decks"]],
                             ["FarmDrop_TST", "DinoDeck_TST"])
            self.assertIsNone(precons.find("FarmDrop_TST"))
            self.assertEqual(precons.find("FarmDrop_TST", products=True)["name"], "Farm Drop")
            self.assertEqual([d["file"] for d in precons.search("farm", products=True)[0]], ["FarmDrop_TST"])
            self.assertEqual(precons.search("farm")[0], [])

    def test_the_deck_list_reader_keeps_drops(self):
        raw = {"meta": {"date": "d"}, "data": [
            {"code": "SLD", "fileName": "FarmDrop_SLD", "name": "Farm Drop", "type": "Secret Lair Drop"},
            {"code": "TST", "fileName": "Online_TST", "name": "Online", "type": "MTGO Theme Deck"}]}
        self.assertEqual([d["file"] for d in precons._read_deck_list(raw)["decks"]], ["FarmDrop_SLD"])


class ApiTests(SealedCase):
    """GET /api/precons/product: for a home admin who records orders."""

    def setUp(self):
        super().setUp()
        from decklab.lib import access
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        stack.enter_context(mock.patch.object(sealed, "CACHE", self.cache))
        stack.enter_context(mock.patch.object(sealed, "_fetch_set", lambda code: json.loads(json.dumps(SET_FILE))))
        stack.enter_context(mock.patch.object(precons, "find", side_effect=lambda f, products=False:
                                              FARM_ENTRY if f == "FarmDrop_TST" else None))
        stack.enter_context(mock.patch.object(precons, "deck", return_value=FARM_DROP))
        self.access = access

    def view(self, profile="matt", **params):
        from decklab.lib.api import precons as api
        with self.access.using({"profile": profile, "email": "", "remote": True}):
            return api.product_list_view(**params)

    def test_the_list_with_its_bonus_card(self):
        answer = self.view(file="FarmDrop_TST")
        self.assertEqual((answer["stem"], answer["name"]), ("tst-farm-drop", "Farm Drop"))
        self.assertEqual(answer["checks"], ["Confirm Sol Ring (TST 901) was in the box: it's the expected bonus card"])
        self.assertEqual(answer["csv"].splitlines()[0], "name,set,collector_number,finish,quantity,section,notes")
        self.assertIn("Sol Ring,tst,901,nonfoil,1,extras,bonus card in Farm Drop", answer["csv"])
        without = self.view(file="FarmDrop_TST", bonus="0")
        self.assertNotIn("Sol Ring", without["csv"])
        self.assertEqual([b["words"] for b in without["bonus"]], ["Sol Ring (TST 901)"])

    def test_refusals(self):
        from decklab.lib.api.common import ApiError
        for params, status in (({"file": "Nope_TST"}, 404), ({"file": "../x"}, 400),
                               ({"file": "FarmDrop_TST", "bonus": "2"}, 400)):
            with self.subTest(params=params), self.assertRaises(ApiError) as caught:
                self.view(**params)
            self.assertEqual(caught.exception.status, status)
        with self.assertRaises(ApiError) as caught:
            self.view(profile="user2", file="FarmDrop_TST")              # not one who records home's orders
        self.assertEqual(caught.exception.status, 403)


if __name__ == "__main__":
    unittest.main()
