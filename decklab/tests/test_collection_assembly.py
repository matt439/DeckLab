"""Collection discovery and physical-copy accounting, entirely in a temp repo."""
import json
from pathlib import Path
from unittest import mock

from decklab.lib import accessories, cards, config, decks, inventory, pool, tokens
from decklab.lib.api import assembly, collection
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import rules
from decklab.tests import household_config
from decklab.tests.test_pool import PoolTestCase, setUpModule, tearDownModule  # noqa: F401
from decklab.tests.test_tokens import HEADER as TOKENS_HEADER, INSECT, MTGMATE, REAL_TOKENS

FIXTURES = Path(__file__).parent / "fixtures"


class PreparationCase(PoolTestCase):
    def setUp(self):
        super().setUp()
        for module in (config,):
            patcher = mock.patch.object(module, "REPO", self.magic.parent)
            patcher.start()
            self.addCleanup(patcher.stop)
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)

    def preview(self, *selections):
        body = {"decks": [{"id": f"casual/{slug}", "version": version}
                          for slug, version in selections]}
        return assembly.assembly_preview(json.dumps(body))


class CollectionTests(PreparationCase):
    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                       ("Aerie Mystics", "con", "1", "nonfoil", 1))
        self.cards_csv("orders/arrival.csv", ("Pick Your Poison", "mkm", "170", "nonfoil", 2))
        self.deck("built", "Built", "built", "Deck\n3 Llanowar Elves\n")

    def test_owned_free_held_and_incoming_are_distinct(self):
        result = collection.collection_view()
        rows = {row["name"]: row for row in result["cards"]}
        elf = rows["Llanowar Elves"]
        self.assertEqual((elf["owned"], elf["free_now"], elf["held"], elf["incoming"]), (4, 1, 3, 0))
        poison = rows["Pick Your Poison"]
        self.assertEqual((poison["owned"], poison["free_now"], poison["incoming"]), (0, 0, 2))
        self.assertEqual(elf["holders"][0]["id"], "casual/built")

    def test_role_rules_colour_type_mana_and_pagination(self):
        answer = collection.collection_view(q="add", color="G", role="ramp", type="Creature", mv="1", limit="1")
        self.assertEqual(answer["total"], 2)
        self.assertEqual(answer["cards"][0]["name"], "Elvish Mystic")
        self.assertEqual(answer["pages"], 2)
        next_page = collection.collection_view(q="add", color="G", role="ramp", type="Creature", mv="1", limit="1", page="2")
        self.assertEqual(next_page["cards"][0]["name"], "Llanowar Elves")
        # A page past the end shows the last page, and says which it is.
        past = collection.collection_view(q="add", color="G", role="ramp", type="Creature", mv="1", limit="1", page="9")
        self.assertEqual((past["page"], past["pages"]), (2, 2))
        self.assertEqual(past["cards"][0]["name"], "Llanowar Elves")
        self.assertEqual(collection.collection_view(color="W", mv="5")["total"], 1)
        self.assertEqual(collection.collection_view(color="C")["total"], 0)

    def test_availability_filters(self):
        self.assertEqual(collection.collection_view(availability="free")["total"], 3)
        self.assertEqual(collection.collection_view(availability="held")["total"], 1)
        self.assertEqual(collection.collection_view(availability="incoming")["cards"][0]["name"], "Pick Your Poison")

    def test_special_basics_shown_without_claiming_allocations(self):
        self.cards_csv("collection.csv", ("Forest", "fdn", "281", "foil", 2))
        row = next(item for item in collection.collection_view()["cards"] if item["name"] == "Forest")
        self.assertEqual(row["owned"], 2)
        self.assertTrue(row["basic"])
        self.assertIsNone(row["free_now"])
        self.assertIsNone(row["held"])

    def test_bad_filters_refused(self):
        for kwargs in ({"page": "0"}, {"limit": "101"}, {"mv": "nan"}, {"mv": "-1"},
                       {"availability": "owned"}, {"color": "X"}, {"q": "bad\nname"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ApiError) as caught:
                collection.collection_view(**kwargs)
            self.assertEqual(caught.exception.status, 400)

    def test_unresolved_inventory_stays_visible_and_warned(self):
        self.cards_csv("collection.csv", ("Unknown Card", "bad", "1", "nonfoil", 1))
        result = collection.collection_view()
        row = next(row for row in result["cards"] if row["name"] == "Unknown Card")
        self.assertFalse(row["resolved"])
        self.assertIsNone(row["card"])
        self.assertTrue(result["warnings"])

    def test_one_request_reads_one_inventory_snapshot(self):
        # No mixed reads: the server pins one snapshot per request, and the pool, the special
        # basics and the deck lists all read it (decklab/lib/inventory).
        with mock.patch.object(self.inventory, "load", wraps=self.inventory.load) as load, inventory.pinned():
            collection.collection_view()
            assembly.assembly_view()
        self.assertEqual(load.call_count, 1)

    def test_an_unreadable_collection_is_a_409(self):
        self.write("collection.csv", "name,set,collector_number,finish,quantity\nOpt,dom,60,nonfoil,lots\n")
        with self.assertRaises(ApiError) as caught:
            collection.collection_view()
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("bad quantity", caught.exception.message)


class AssemblyTests(PreparationCase):
    def test_browser_preview_accepts_profile_envelope(self):
        household_config.use(self)
        result = assembly.assembly_preview(json.dumps({"profile": "matt", "decks": []}).encode())
        self.assertFalse(result["ready"])

    def test_two_building_lists_compete_for_one_pool(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        for slug in ("a", "b"):
            self.deck(slug, slug.upper(), "building", "Deck\n4 Llanowar Elves\n")
        result = self.preview(("a", "target"), ("b", "target"))
        self.assertEqual((result["totals"]["need"], result["totals"]["from_storage"], result["totals"]["missing"]), (8, 4, 4))
        self.assertFalse(result["ready"])

    def test_participant_allocations_kept_once_transferred_and_returned(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        self.deck("a", "A", "built", "Deck\n2 Llanowar Elves\n", owned="Deck\n4 Llanowar Elves\n1 Elvish Mystic\n", built_version="owned-only")
        self.deck("b", "B", "building", "Deck\n2 Llanowar Elves\n")
        result = self.preview(("a", "target"), ("b", "target"))
        self.assertTrue(result["ready"])
        self.assertEqual((result["totals"]["kept"], result["totals"]["transfers"], result["totals"]["from_storage"]), (2, 2, 0))
        self.assertEqual(result["decks"][0]["returns"], [{"name": "Elvish Mystic", "quantity": 1}])
        transfer = result["decks"][1]["steps"][0]["transfers"][0]
        self.assertEqual((transfer["from"], transfer["to"], transfer["quantity"]), ("casual/a", "casual/b", 2))

    def test_the_plan_carries_its_cards_pictures_in_the_lists_printing(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves (FDN) 227\n20 Forest\n")
        result = self.preview(("a", "target"))
        elves = result["cards"]["Llanowar Elves"]
        self.assertEqual((elves["name"], elves["img_small"]), ("Llanowar Elves", "/img/fdn/227/small"))
        self.assertEqual(self.preview()["cards"], {})

    def test_the_plan_carries_land_mana_production_even_without_colour_identity(self):
        self.deck("a", "A", "building", "Deck\n1 City of Brass\n20 Forest\n")
        lands = {
            "City of Brass": {"name": "City of Brass", "type_line": "Land", "mana_cost": "", "cmc": 0,
                              "colors": [], "color_identity": [], "produced_mana": list("WUBRG"),
                              "roles": [], "printings": []},
            "Forest": {"name": "Forest", "type_line": "Basic Land — Forest", "mana_cost": "", "cmc": 0,
                       "colors": [], "color_identity": ["G"], "produced_mana": ["G"],
                       "roles": [], "printings": []},
        }
        with mock.patch.dict(cards._get().data["cards"], lands):
            result = self.preview(("a", "target"))
        rainbow = result["cards"]["City of Brass"]
        self.assertEqual(rainbow["color_identity"], [])
        self.assertEqual(rainbow["produced_mana"], list("WUBRG"))
        self.assertEqual(result["cards"]["Forest"]["produced_mana"], ["G"])

    def test_external_built_deck_remains_reserved(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "built", "Deck\n3 Llanowar Elves\n")
        self.deck("b", "B", "building", "Deck\n3 Llanowar Elves\n")
        result = self.preview(("b", "target"))
        self.assertEqual((result["totals"]["from_storage"], result["totals"]["missing"]), (1, 2))
        self.assertEqual(result["rows"][0]["held_elsewhere"][0]["id"], "casual/a")

    def test_incoming_can_cover_wait_but_never_ready(self):
        self.cards_csv("orders/arrival.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "building", "Deck\n3 Llanowar Elves\n")
        self.deck("b", "B", "building", "Deck\n3 Llanowar Elves\n")
        result = self.preview(("a", "target"), ("b", "target"))
        self.assertEqual((result["totals"]["waiting"], result["totals"]["missing"]), (4, 2))
        self.assertFalse(result["ready"])

    def test_duplicate_lists_cannot_release_allocations_twice(self):
        self.deck("a", "A", "building", "Deck\n1 Llanowar Elves\n", owned="Deck\n1 Elvish Mystic\n")
        with self.assertRaises(ApiError) as caught:
            self.preview(("a", "target"), ("a", "owned"))
        self.assertEqual(caught.exception.status, 400)

    def test_unknown_card_never_means_ready(self):
        self.cards_csv("collection.csv", ("Unknown Card", "bad", "1", "nonfoil", 1))
        self.deck("a", "A", "building", "Deck\n1 Unknown Card\n")
        result = self.preview(("a", "target"))
        self.assertFalse(result["ready"])
        self.assertFalse(result["counts_confirmed"])
        self.assertIn("Unknown Card", result["unresolved"])

    def test_overreserved_inventory_blocks_ready_even_for_kept_cards(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        self.deck("a", "A", "built", "Deck\n2 Llanowar Elves\n")
        result = self.preview(("a", "target"))
        self.assertFalse(result["ready"])
        self.assertTrue(result["warnings"])

    def test_basics_sleeves_and_tokens_preserve_physical_quantities(self):
        self.deck("a", "A", "building", "Deck\n24 Forest\n")
        path = self.magic / "decks/casual/a.md"
        path.write_text(path.read_text().replace("- **Status:** building", "- **Status:** building\n- **Sleeves:** Blue"))
        self.write("tokens.csv", TOKENS_HEADER + "Dog,Beast,,,,,2,,3/3,printing unconfirmed\n")
        result = self.preview(("a", "target"))
        self.assertEqual(result["decks"][0]["sleeves"], "Blue")
        self.assertEqual(result["decks"][0]["basics"], [{"name": "Forest", "quantity": 24}])
        self.assertEqual(result["tokens"][0]["quantity"], 2)
        self.assertEqual(result["tokens"][0]["back_details"], "3/3")
        self.assertEqual(result["tokens"][0]["key"], "2")             # the line it's on
        self.assertEqual((result["token_problems"], result["token_plan"]), ([], []))
        self.assertEqual(result["token_note"], tokens.NOTE + " Packing ticks don't reserve or change inventory.")
        self.assertEqual(result["totals"]["need"], 0)

    def test_an_older_or_bad_token_file_never_stops_the_plan(self):
        self.deck("a", "A", "building", "Deck\n24 Forest\n")
        self.write("tokens.csv", "front,back,quantity,front_details,back_details,notes\n"
                                 "Dog,Beast,2,,3/3,printing unconfirmed\nSpirit,,none,,,\n")
        result = self.preview(("a", "target"))
        self.assertEqual([(t["front"], t["quantity"], t["key"]) for t in result["tokens"]], [("Dog", 2, "2")])
        self.assertEqual(len(result["token_problems"]), 2)
        self.assertIn("The home token cards lack the printing columns; fix the header by hand before the Tokens "
                      "page can save", result["token_problems"])
        self.assertTrue(result["token_problems"][1].startswith("A row after row 1 of the home token cards: "))
        self.assertEqual(assembly.assembly_view()["tokens"][0]["front"], "Dog")

    def test_empty_plan_is_not_ready(self):
        result = self.preview()
        self.assertFalse(result["ready"])

    def test_mutation_like_fields_and_path_traversal_refused(self):
        for payload in ({"decks": [], "apply": True}, {"decks": "a"},
                        {"decks": [{"id": "casual/../secret", "version": "target"}]}):
            with self.subTest(payload=payload), self.assertRaises(ApiError) as caught:
                assembly.assembly_preview(json.dumps(payload))
            self.assertEqual(caught.exception.status, 400)


class AccessoryKitTests(PreparationCase):
    """Each deck in the plan carries its sleeves and deck box (accessories.kit) for the selected version."""

    def setUp(self):
        super().setUp()
        for name, value in (("PATH", self.magic / "accessories.csv"),
                            ("IMAGES", self.magic / "accessories" / "images")):
            patcher = mock.patch.object(accessories, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write("accessories.csv", "id,kind,brand,name,colour,quantity,image,link,image_source,notes\n"
                                      "katana-black,sleeves,KMC,Katana,Black,20,,,,\n"
                                      "boulder-black,deck_box,Ultimate Guard,Boulder 100+,black,1,,,,\n")

    def sleeved(self, slug, sleeves, status="built", **kwargs):
        self.deck(slug, slug.title(), status, **kwargs)
        path = self.magic / f"decks/casual/{slug}.md"
        path.write_text(path.read_text().replace(f"- **Status:** {status}\n",
                                                 f"- **Status:** {status}\n- **Sleeves:** {sleeves}\n"
                                                 f"- **Deck box:** boulder-black\n"), encoding="utf-8")

    def test_a_linked_deck_counts_the_selected_version(self):
        self.sleeved("a", "katana-black", target="Deck\n24 Forest\n", owned="Deck\n12 Forest\n",
                     built_version="target")
        deck = self.preview(("a", "owned"))["decks"][0]
        self.assertEqual(deck["sleeves"], "KMC Katana (Black)")
        self.assertEqual(deck["sleeves_need"], 12)
        self.assertEqual((deck["kit"]["need"], deck["kit"]["short"], deck["kit"]["spare"]), (12, 0, 8))
        self.assertEqual(deck["kit"]["deck_box"]["label"], "Ultimate Guard Boulder 100+ (black)")
        self.assertNotIn("need", deck)          # card counts stay internal, as before
        deck = self.preview(("a", "target"))["decks"][0]
        self.assertEqual((deck["sleeves_need"], deck["kit"]["short"]), (24, 4))
        self.assertTrue(deck["kit"]["warnings"][0].startswith("Not enough sleeves: this deck needs 24"))

    def test_decks_in_the_same_sleeves_get_a_note_not_a_block(self):
        # E8-S20: one design may sleeve several decks; chosen together, the plan notes it.
        self.sleeved("a", "katana-black", target="Deck\n12 Forest\n")
        self.sleeved("b", "katana-black", target="Deck\n14 Forest\n")
        self.sleeved("c", "Blue", target="Deck\n2 Forest\n")
        result = self.preview(("a", "target"), ("b", "target"), ("c", "target"))
        self.assertEqual(result["sleeve_notes"], [{
            "sleeves": "KMC Katana (Black)", "decks": [{"id": "casual/a", "title": "A"}, {"id": "casual/b", "title": "B"}],
            "note": "A and B are both in KMC Katana (Black) sleeves: their cards look the same from the back, so keep "
                    "each deck's cards together."}])
        first, second, _ = result["decks"]
        # Each is checked against the row's 20 on its own (12 and 14, not 26), and sharing is no warning.
        self.assertEqual((first["kit"]["short"], second["kit"]["short"]), (0, 0))
        self.assertEqual(first["kit"]["shared_with"], ["B"])
        self.assertFalse([w for d in result["decks"] for w in d["kit"]["warnings"] if "sleeves" in w.lower()])
        self.assertEqual(self.preview(("a", "target"), ("c", "target"))["sleeve_notes"], [])

    def test_two_decks_of_one_intact_product_are_one_holder(self):
        # A product's decks are all in its one design of sleeves: chosen together, that's no note.
        self.beginner_box()
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "fdn-beginner-box.csv,owned,yes,katana-black,,\n")
        body = {"decks": [{"id": "product/fdn-beginner-box/elves", "version": "target"},
                          {"id": "product/fdn-beginner-box/cats", "version": "target"}]}
        result = assembly.assembly_preview(json.dumps(body))
        self.assertEqual([d["kit"]["holder"] for d in result["decks"]], ["product/fdn-beginner-box"] * 2)
        self.assertEqual(result["sleeve_notes"], [])
        # With another holder in the same sleeves, the product is named once, by its own title.
        self.sleeved("a", "katana-black", target="Deck\n2 Forest\n")
        body["decks"].append({"id": "casual/a", "version": "target"})
        notes = assembly.assembly_preview(json.dumps(body))["sleeve_notes"]
        self.assertEqual(len(notes), 1)
        self.assertEqual([d["id"] for d in notes[0]["decks"]], ["product/fdn-beginner-box", "casual/a"])
        self.assertTrue(notes[0]["note"].endswith("are both in KMC Katana (Black) sleeves: their cards look the "
                                                  "same from the back, so keep each deck's cards together."))

    def test_free_text_and_nothing_recorded(self):
        self.sleeved("a", "Blue", target="Deck\n2 Forest\n")
        self.deck("b", "B", "idea", "Deck\n3 Forest\n")
        first, second = self.preview(("a", "target"), ("b", "target"))["decks"]
        self.assertEqual((first["sleeves"], first["kit"]["sleeves"]["state"]), ("Blue", "text"))
        self.assertEqual(len(first["kit"]["info"]), 1)
        self.assertEqual((second["sleeves"], second["kit"]["sleeves"], second["sleeves_need"]), ("Not recorded", None, 3))

    def test_a_product_uses_its_status_columns_for_the_whole_product(self):
        self.beginner_box()
        body = {"decks": [{"id": "product/fdn-beginner-box/elves", "version": "target"}]}
        deck = assembly.assembly_preview(json.dumps(body))["decks"][0]
        self.assertEqual((deck["sleeves"], deck["sleeves_need"]), ("Not recorded for this product", 26))
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "fdn-beginner-box.csv,owned,yes,katana-black,,\n")
        deck = assembly.assembly_preview(json.dumps(body))["decks"][0]
        self.assertEqual((deck["sleeves"], deck["kit"]["holder"], deck["kit"]["short"]),
                         ("KMC Katana (Black)", "product/fdn-beginner-box", 6))


class AssemblyTokenTests(PreparationCase):
    """Each deck's tokens (tokens.deck_tokens for the selected version) and the
    token cards two or more selected decks would grab, with a card index built
    from fixtures/tokens_cards.jsonl and test_tokens.REAL_TOKENS as tokens.csv."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(cards, "_index", self.loaded)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write("tokens.csv", REAL_TOKENS)
        self.deck("a", "A", "building", "Deck\n1 Hornet Queen\n1 Court of Grace\n")
        self.deck("b", "B", "building", "Deck\n1 Court of Grace\n1 Army of the Damned\n")
        self.deck("c", "C", "building", "Deck\n1 Fountainport\n", owned="Deck\n1 Hare Apparent\n")

    def order(self, rows=MTGMATE, order="2026-10-07-shop-a"):
        rel = f"magic/orders/tokens/{order}.csv"
        path = self.magic.parent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(rules.csv_bytes(rows, rules.TOKEN_FIELDS))
        (self.magic / "orders" / "records").mkdir(parents=True, exist_ok=True)
        self.write(f"orders/records/{order}.json", json.dumps({
            "version": 1, "id": order, "seller": "MTGMate", "ordered_on": "2026-10-07", "sources": [], "notes": "",
            "components": [{"id": "tokens", "kind": "tokens", "path": rel, "status": "pending", "received_on": "",
                            "checks": []}]}))

    def test_each_deck_has_its_tokens_for_the_selected_version(self):
        self.order()
        result = self.preview(("a", "target"), ("c", "owned"))
        inv, (inc, _) = tokens.read(), tokens.incoming()
        first, second = result["decks"]
        undecorated = {**first["tokens"], "needs": [
            {key: value for key, value in need.items() if key != "packing_key"} for need in first["tokens"]["needs"]]}
        self.assertEqual(undecorated, tokens.deck_tokens(decks.load_deck("casual/a", "target"), inv, inc))
        self.assertTrue(all(len(need["packing_key"]) == 64 for need in first["tokens"]["needs"]))
        self.assertEqual([n["name"] for n in second["tokens"]["needs"]], ["Rabbit"])     # the owned-only list
        insect = next(n for n in first["tokens"]["needs"] if n["key"] == INSECT)
        self.assertEqual(insect["state"], "differs")
        json.dumps(result, allow_nan=False)

    def test_shared_tokens_are_only_cards_two_decks_would_grab(self):
        result = self.preview(("a", "target"), ("b", "target"))
        plan = result["token_plan"]
        self.assertTrue(plan)
        self.assertEqual(result["token_plan_note"], assembly.TOKEN_PLAN_NOTE)
        rows = tokens.read().rows
        for item in plan:
            self.assertEqual({w["deck"] for w in item["wanted_by"]}, {"casual/a", "casual/b"})
            row = rows[item["row"]]
            self.assertEqual((item["front"], item["back"], item["quantity"]),
                             (row["front"], row["back"], int(row["quantity"])))
        labels = {f"{i['front']} / {i['back']}" for i in plan}
        # Court of Grace in both: The Monarch, Angels and Spirits.
        self.assertIn("Angel / The Monarch", labels)
        self.assertIn("Zombie / The Monarch", labels)
        # Only A wants the Insect stand-in; only B (Army of the Damned) wants the Zombie / Zombie Knight.
        self.assertNotIn("Insect / ", " ".join(labels))
        self.assertNotIn("Zombie / Zombie Knight", labels)
        monarch = next(i for i in plan if (i["front"], i["back"]) == ("Zombie", "The Monarch"))
        self.assertIn({"deck": "casual/a", "title": "A", "token": "The Monarch", "side": "back"}, monarch["wanted_by"])
        self.assertIn({"deck": "casual/b", "title": "B", "token": "Zombie", "side": "front"}, monarch["wanted_by"])
        self.assertEqual([i["row"] for i in plan], sorted(i["row"] for i in plan))
        self.assertEqual(self.preview(("a", "target"))["token_plan"], [])                # one deck shares nothing

    def test_cards_on_the_way_are_never_shared_out(self):
        self.order([row for row in MTGMATE if row["front"] == "Fish"])
        result = self.preview(("c", "target"), ("b", "target"))
        fish = next(n for n in result["decks"][0]["tokens"]["needs"] if n["name"] == "Fish")
        self.assertEqual((fish["state"], fish["cards"], fish["on_the_way"]), ("incoming", [], 2))
        self.assertNotIn("Fish", [i["front"] for i in result["token_plan"]])

    def test_a_deck_whose_tokens_cant_be_worked_out(self):
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=RuntimeError("no index")):
            result = self.preview(("a", "target"), ("b", "target"))
        self.assertEqual([d["tokens"] for d in result["decks"]], [{"unavailable": assembly.TOKEN_UNAVAILABLE}] * 2)
        self.assertEqual(result["token_plan"], [])
        self.assertEqual(len(result["tokens"]), 24)                 # the inventory list still shows
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=KeyError("oops")), \
                mock.patch.object(assembly.common, "_log") as log:
            result = self.preview(("a", "target"))
        self.assertEqual(result["decks"][0]["tokens"], {"error": assembly.TOKEN_FAILED})
        self.assertIn("KeyError", log.call_args.args[0])
