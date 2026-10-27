"""Actual product subdecks join one physical token plan, saved once per box."""
import copy
import csv
import io
from unittest import mock

from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.inventory import kit
from decklab.lib.tokens import plan_products, products
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests import test_token_reservation as reservation_fixture

STEM = "opaque-bundle"
HOLDER = f"product/{STEM}"
ARMY = ("Army of the Damned", "c13", "69")
COURT = ("Court of Grace", "cmr", "16")
NO_TOKENS = ("Brazen Borrower // Petty Theft", "sld", "234")


class ProductTokenPlanningTests(token_fixture.TokensApiTestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(token_fixture.FIXTURES / "tokens_cards.jsonl",
                                                      token_fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None))

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        self.status_rows = {}
        self.product()

    def product(self, stem=STEM, *, parts=(("One", ARMY), ("Two", ARMY)), packed="", state="owned", intact="yes"):
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(("deck", "section", "name", "set", "collector_number", "finish", "quantity"))
        for title, (name, set_code, number) in parts:
            writer.writerow((title, "deck", name, set_code, number, "nonfoil", 1))
        self.write(f"products/{stem}.csv", out.getvalue())
        self.status_rows[stem] = (state, intact, packed)
        status = io.StringIO()
        writer = csv.writer(status, lineterminator="\n")
        writer.writerow(("file", "status", "intact", "sleeves", "deck_box", "notes", "token_cards"))
        for key, (current_state, current_intact, value) in sorted(self.status_rows.items()):
            writer.writerow((f"{key}.csv", current_state, current_intact, "", "", "", value))
        self.write("products/status.csv", status.getvalue())

    def built(self, slug="a", *, packed=None, source="1 Army of the Damned\n"):
        self.write(f"decks/casual/{slug}.md", reservation_fixture.built(slug.upper(), deck=source, packed=packed))

    def zombie_copies(self, count):
        self.write("tokens.csv", token_fixture.ROWS.replace("Zombie,Zombie Knight,,,,,8,", f"Zombie,Zombie Knight,,,,,{count},"))

    @staticmethod
    def quantity(value):
        return sum(line.quantity for line in decks.parse_token_cards(value))

    def test_same_need_in_two_subdecks_consumes_two_physical_cards_in_one_box(self):
        self.zombie_copies(2)
        before = self.magic_files()
        result = tokens.plan_token_cards()
        self.assertEqual(result["decks"], [])
        self.assertEqual(len(result["products"]), 1)
        product = result["products"][0]
        self.assertEqual((product["stem"], product["holder"], product["link"]), (STEM, HOLDER, None))
        self.assertEqual(product["after"], "2 Zombie // Zombie Knight")
        self.assertTrue(product["changed"])
        self.assertEqual([item["id"] for item in product["decks"]], [f"{HOLDER}/one", f"{HOLDER}/two"])
        self.assertEqual([len(item["packs"]) for item in product["decks"]], [1, 1])
        self.assertEqual(product["lines"], [{"text": "2 Zombie // Zombie Knight", "sides": []}])
        self.assertEqual(self.magic_files(), before)

    def test_built_decks_and_subdecks_share_flow_and_round_robin_spares(self):
        self.built()
        result = tokens.plan_token_cards()
        ordinary, product = result["decks"][0], result["products"][0]
        self.assertEqual(ordinary["after"], "3 Zombie // Zombie Knight")
        self.assertEqual(product["after"], "5 Zombie // Zombie Knight")
        self.assertEqual(ordinary["spares"], 2)
        self.assertEqual([item["spares"] for item in product["decks"]], [2, 1])
        self.assertEqual(self.quantity(ordinary["after"]) + self.quantity(product["after"]), 8)

    def test_paired_card_capacity_is_shared_across_faces_subdecks_and_ordinary_decks(self):
        self.product(parts=(("One", COURT), ("Two", COURT)))
        self.built(source="1 Court of Grace\n")
        result = tokens.plan_token_cards()
        product = result["products"][0]
        assigned = [*result["decks"], *product["decks"]]
        self.assertEqual(sum(len(item["packs"]) for item in assigned), 1)
        self.assertEqual(sum(len(item["short"]) for item in assigned), 8)
        self.assertEqual(sum(self.quantity(item["after"]) for item in [*result["decks"], product]), 1)
        self.assertTrue(all(not line["sides"] for line in product["lines"]))

    def test_two_sides_need_two_copies_and_box_lines_make_no_sleeving_claim(self):
        self.product(parts=(("One", COURT),))
        self.write("tokens.csv", token_fixture.ROWS.replace("Angel,The Monarch,,,,,1,", "Angel,The Monarch,,,,,2,"))
        product = tokens.plan_token_cards()["products"][0]
        self.assertEqual(product["after"], "2 Angel // The Monarch")
        self.assertEqual({item["side"] for item in product["decks"][0]["packs"]}, {"front", "back"})
        self.assertEqual(product["lines"], [{"text": "2 Angel // The Monarch", "sides": []}])

    def test_existing_product_reservation_is_released_for_planning_and_favored_by_holder(self):
        self.zombie_copies(1)
        self.write("tokens.csv", self.csv_text() + "Zombie,Zombie Knight,tst,9,,nonfoil,1,,,printing unconfirmed\n")
        self.product(parts=(("One", ARMY),), packed="1 Zombie // Zombie Knight (TST) 9")
        self.built()
        result = tokens.plan_token_cards()
        product = result["products"][0]
        self.assertEqual(product["after"], "1 Zombie // Zombie Knight (TST) 9")
        self.assertFalse(product["changed"])
        self.assertEqual(result["decks"][0]["after"], "1 Zombie // Zombie Knight")
        self.assertEqual(product["decks"][0]["short"], [])

    def test_products_share_one_global_capacity_and_each_has_one_save_record(self):
        self.zombie_copies(3)
        self.product("another-box", parts=(("Other", ARMY),))
        result = tokens.plan_token_cards()
        self.assertEqual([item["stem"] for item in result["products"]], ["another-box", STEM])
        self.assertEqual(sum(self.quantity(item["after"]) for item in result["products"]), 3)
        self.assertEqual([self.quantity(item["after"]) for item in result["products"]], [1, 2])

    def test_no_needs_preserves_record_and_hold_including_blank_unknown(self):
        for packed, remaining in (("3 Zombie // Zombie Knight", 5), ("", 8)):
            with self.subTest(packed=packed):
                self.product(parts=(("One", NO_TOKENS),), packed=packed)
                self.built()
                result = tokens.plan_token_cards()
                product = result["products"][0]
                self.assertEqual((product["before"], product["after"], product["changed"]), (packed, packed, False))
                self.assertEqual(product["decks"][0]["packs"], [])
                self.assertEqual(product["decks"][0]["spares"], 0)
                self.assertEqual(self.quantity(result["decks"][0]["after"]), remaining)

    def test_empty_assignment_keeps_blank_unknown_and_reports_actual_shortfalls(self):
        self.write("tokens.csv", token_fixture.HEADER)
        product = tokens.plan_token_cards()["products"][0]
        self.assertEqual((product["before"], product["after"], product["changed"]), ("", "", False))
        self.assertEqual([item["short"] for item in product["decks"]], [["Zombie"], ["Zombie"]])

    def test_unsupported_or_unknown_source_stays_locked_instead_of_releasing_cards(self):
        self.built()
        for source in ("name,set,collector_number,finish,quantity\nArmy of the Damned,c13,69,nonfoil,1\n",
                       "section,name,set,collector_number,finish,quantity\ndeck,Not a fixture card,tst,1,nonfoil,1\n",
                       "section,name,set,collector_number,finish,quantity\ndeck,Army of the Damned,c13,69,bad,1\n"):
            with self.subTest(source=source):
                self.product(packed="3 Zombie // Zombie Knight")
                self.write(f"products/{STEM}.csv", source)
                warnings = []
                result = tokens.plan_token_cards(warnings=warnings)
                self.assertEqual(result["products"], [])
                self.assertEqual(result["decks"][0]["after"], "5 Zombie // Zombie Knight")
                self.assertIn(plan_products.FIXED, warnings)

    def test_incomplete_copy_or_unlisted_needs_keep_whole_box_fixed(self):
        self.product(packed="3 Zombie // Zombie Knight")
        self.built()
        original = tokens.cached_deck_tokens
        for incomplete in ("copies", "unlisted"):
            def needs(*args, **kwargs):
                result = original(*args, **kwargs)
                if args[0].startswith("product/"):
                    result[incomplete] = ["Fixture unresolved token requirement"]
                return result
            with self.subTest(incomplete=incomplete), mock.patch.object(tokens, "cached_deck_tokens", side_effect=needs):
                result = tokens.plan_token_cards()
                self.assertEqual(result["products"], [])
                self.assertEqual(result["decks"][0]["after"], "5 Zombie // Zombie Knight")

    def test_duplicate_or_wrong_producer_routes_cannot_release_a_box(self):
        self.product(packed="3 Zombie // Zombie Knight")
        self.built()
        actual = decks._product_decks()
        for routes in ([*actual, actual[0]], [dict(item, product="wrong") for item in actual],
                       [dict(item, source="magic/products/wrong.csv") for item in actual]):
            with self.subTest(routes=routes), mock.patch.object(decks, "_product_decks", return_value=routes):
                warnings = []
                result = tokens.plan_token_cards(warnings=warnings)
                self.assertEqual(result["products"], [])
                self.assertEqual(result["decks"][0]["after"], "5 Zombie // Zombie Knight")
                self.assertIn(plan_products.FIXED, warnings)

    def test_one_unknown_subdeck_keeps_the_whole_box_fixed(self):
        self.product(parts=(("One", ARMY), ("Two", ("Not a fixture card", "tst", "1"))),
                     packed="3 Zombie // Zombie Knight")
        self.built()
        warnings = []
        result = tokens.plan_token_cards(warnings=warnings)
        self.assertEqual(result["products"], [])
        self.assertEqual(result["decks"][0]["after"], "5 Zombie // Zombie Knight")
        self.assertIn(plan_products.FIXED, warnings)

    def test_route_collision_between_actual_products_keeps_both_boxes_fixed(self):
        self.product(packed="3 Zombie // Zombie Knight")
        self.product("other-box", parts=(("Other", ARMY),), packed="2 Zombie // Zombie Knight")
        self.built()
        routes = copy.deepcopy(decks._product_decks())
        first = next(item for item in routes if item["product"] == STEM)
        next(item for item in routes if item["product"] == "other-box")["id"] = first["id"]
        with mock.patch.object(decks, "_product_decks", return_value=routes):
            result = tokens.plan_token_cards()
        self.assertEqual(result["products"], [])
        self.assertEqual(result["decks"][0]["after"], "3 Zombie // Zombie Knight")

    def test_extra_same_prefix_wrong_source_route_is_not_a_product_participant(self):
        first = tokens.plan_token_cards()
        routes = decks._product_decks()
        decoy = dict(routes[0], id=f"{HOLDER}/decoy", source="magic/products/wrong.csv")
        with mock.patch.object(decks, "_product_decks", return_value=[*routes, decoy]):
            second = tokens.plan_token_cards()
        self.assertEqual(first["products"], second["products"])
        self.assertEqual(first["sha256"], second["sha256"])

    def test_actual_metadata_not_route_prefix_identifies_product_and_receipt(self):
        first = tokens.plan_token_cards()
        actual = decks._product_decks()
        renamed = [dict(item, id=f"product/independent-actual-route-{i}") for i, item in enumerate(actual)]
        with mock.patch.object(decks, "_product_decks", return_value=renamed):
            second = tokens.plan_token_cards()
        self.assertEqual(first["products"][0]["after"], second["products"][0]["after"])
        self.assertEqual(second["products"][0]["holder"], HOLDER)
        self.assertEqual([item["id"] for item in second["products"][0]["decks"]], [item["id"] for item in renamed])
        self.assertEqual(first["inventory_revision"], second["inventory_revision"])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_receipt_binds_actual_sections_even_when_allocations_stay_identical(self):
        first = tokens.plan_token_cards()
        routes = copy.deepcopy(decks._product_decks())
        next(iter(routes[0]["sections"].values()))[0].quantity += 1
        with mock.patch.object(decks, "_product_decks", return_value=routes):
            second = tokens.plan_token_cards()
        self.assertEqual(first["products"][0]["after"], second["products"][0]["after"])
        self.assertEqual(first["inventory_revision"], second["inventory_revision"])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_only_owned_intact_products_participate(self):
        self.built()
        for state, intact in (("ordered", "yes"), ("owned", "no"), ("cancelled", "yes")):
            self.product(state=state, intact=intact)
            result = tokens.plan_token_cards()
            self.assertEqual(result["products"], [])
            self.assertEqual(result["decks"][0]["after"], "8 Zombie // Zombie Knight")

    def test_optional_product_argument_retains_direct_fixed_holder_mode(self):
        self.product(packed="3 Zombie // Zombie Knight")
        self.built()
        inv = tokens.read()
        needs = tokens.deck_tokens(decks.load_deck("casual/a"), inv, [])["needs"]
        result = tokens.optimise.plan(inv, [("casual/a", "A", needs)])
        self.assertEqual(result["products"], [])
        self.assertEqual(result["decks"][0]["after"], "5 Zombie // Zombie Knight")

    def test_member_space_never_gathers_or_receipts_home_product_records(self):
        with mock.patch.object(plan_products, "gather", side_effect=AssertionError("home gather reached")), \
                mock.patch.object(products, "records", side_effect=AssertionError("home records reached")), \
                mock.patch.object(kit, "status_sha256", side_effect=AssertionError("home status receipt reached")):
            result = tokens.plan_token_cards("user2")
        self.assertEqual((result["decks"], result["products"], result["status_sha256"]), ([], [], None))

    def test_direct_plan_uses_one_snapshot_for_membership_rows_and_receipts(self):
        original = self.inventory.load
        with mock.patch.object(self.inventory, "load", wraps=original) as loaded:
            tokens.plan_token_cards()
        self.assertEqual(loaded.call_count, 1)
