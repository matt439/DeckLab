"""Intact products reserve token cards once; fixed-holder plans protect those copies."""
import csv
import io
import json
from unittest import mock

from decklab.lib import access, cards, decks, inventory, tokens
from decklab.lib.api import deck_page, guard, token_plan
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import Op, ops_decks
from decklab.lib.state import Actor
from decklab.lib.tokens import plan_products, products
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests import test_token_reservation as reservation_fixture


STEM = "opaque-bundle"
HOLDER = f"product/{STEM}"
FIELDS = ["file", "status", "intact", "sleeves", "deck_box", "notes", "token_cards"]


class ProductTokenReservationsTests(token_fixture.TokensApiTestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(token_fixture.FIXTURES / "tokens_cards.jsonl",
                                                      token_fixture.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *a: None))

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        self.write(f"products/{STEM}.csv", "deck,section,name,set,collector_number,finish,quantity\n"
                   "One,deck,Army of the Damned,c13,69,nonfoil,1\nTwo,deck,Army of the Damned,c13,69,nonfoil,1\n")
        self.status("3 Zombie // Zombie Knight")

    def status(self, packed, *, state="owned", intact="yes", extra=(), notes=""):
        rows = [{"file": f"{STEM}.csv", "status": state, "intact": intact, "token_cards": packed, "notes": notes}, *extra]
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        self.write("products/status.csv", output.getvalue())

    def zombie(self, inv=None):
        inv = inv or tokens.read()
        return next(i for i, row in enumerate(inv.rows) if row["front"] == "Zombie" and row["back"] == "Zombie Knight" and not row["set"])

    def built(self, slug, *, packed=None, source="1 Army of the Damned\n"):
        self.write(f"decks/casual/{slug}.md", reservation_fixture.built(slug.upper(), deck=source, packed=packed))

    def fixed_plan(self):
        """Explicit ordinary-only optimise mode keeps product reservations fixed."""
        inv = tokens.read()
        built = tokens.built_ids()
        found = [(deck_id, title, tokens.cached_deck_tokens(deck_id, version, sections, inv, [])["needs"])
                 for deck_id, title, version, sections, _ in tokens._holders([], include_products=False) if deck_id in built]
        return tokens.optimise.plan(inv, found)

    def test_multi_deck_product_holds_once_under_actual_canonical_producer(self):
        inv = tokens.read()
        holds = tokens.reserve.holds(inv)
        self.assertEqual(set(holds), {HOLDER})
        self.assertEqual(holds[HOLDER]["rows"], {self.zombie(inv): 3})
        self.assertEqual(holds[HOLDER]["unmatched"], [])
        self.assertIsNone(holds[HOLDER]["link"])
        routes = [route["id"] for route in decks._product_decks() if route.get("product") == STEM]
        self.assertEqual(set(routes), {f"{HOLDER}/one", f"{HOLDER}/two"})
        for route in routes:
            self.assertEqual(products.for_route(route)["holder"], HOLDER)
        self.assertIsNone(products.for_route(f"{HOLDER}/not-a-real-subdeck"))

    def test_own_subdeck_excludes_whole_product_but_a_guessed_prefix_does_not(self):
        self.built("a", packed="1 Zombie // Zombie Knight")
        inv = tokens.read()
        holds = tokens.reserve.holds(inv)
        own = tokens.reserve.held_elsewhere(holds, f"{HOLDER}/one")
        self.assertEqual([item["deck"] for item in own[self.zombie(inv)]], ["casual/a"])
        guessed = tokens.reserve.held_elsewhere(holds, f"{HOLDER}/not-a-real-subdeck")
        self.assertIn(HOLDER, [item["deck"] for item in guessed[self.zombie(inv)]])
        other = tokens.reserve.held_elsewhere(holds, "casual/a")
        self.assertEqual([(item["deck"], item["quantity"]) for item in other[self.zombie(inv)]], [(HOLDER, 3)])

    def test_single_deck_product_links_to_its_actual_root_route(self):
        self.write(f"products/{STEM}.csv", "section,name,set,collector_number,finish,quantity\ndeck,Army of the Damned,c13,69,nonfoil,1\n")
        hold = tokens.reserve.holds(tokens.read())[HOLDER]
        self.assertEqual(hold["link"], HOLDER)
        self.assertEqual(products.for_route(HOLDER)["holder"], HOLDER)

    def test_duplicate_or_wrong_producer_route_metadata_never_identifies_a_box(self):
        route_id = f"{HOLDER}/one"
        actual = next(route for route in decks._product_decks() if route["id"] == route_id)
        for routes in ([actual, dict(actual)], [dict(actual, product="different-actual-product")],
                       [dict(actual, source="magic/products/different-actual-product.csv")],
                       [dict(actual, error="Unusable generated route")]):
            with mock.patch.object(decks, "_product_decks", return_value=routes):
                self.assertIsNone(products.for_route(route_id))

    def test_only_owned_intact_written_reservations_hold_cards(self):
        for state, intact in (("owned", "no"), ("ordered", "yes"), ("preordered", "yes"), ("cancelled", "yes")):
            self.status("3 Zombie // Zombie Knight", state=state, intact=intact)
            self.assertNotIn(HOLDER, tokens.reserve.holds(tokens.read()), (state, intact))
        self.status("")
        self.assertNotIn(HOLDER, tokens.reserve.holds(tokens.read()))
        record = products.records()[HOLDER]
        self.assertFalse(record["written"])
        self.assertEqual(record["lines"], [])

    def test_exact_printing_and_face_pairing_are_preserved_without_counting_faces_twice(self):
        self.write("tokens.csv", self.csv_text() + "Zombie,Zombie Knight,tst,9,,nonfoil,2,,,printing unconfirmed\n")
        self.status("2 Zombie // Zombie Knight (TST) 9")
        inv = tokens.read()
        printed = next(i for i, row in enumerate(inv.rows) if row["set"] == "tst")
        self.assertEqual(tokens.reserve.holds(inv)[HOLDER]["rows"], {printed: 2})
        self.status("2 Zombie Knight // Zombie (TST) 9")
        hold = tokens.reserve.holds(inv)[HOLDER]
        self.assertEqual(hold["rows"], {})
        self.assertEqual(len(hold["unmatched"]), 1)

    def test_planner_subtracts_product_locks_from_flow_and_every_spare(self):
        self.built("a")
        self.built("b", packed="8 Zombie // Zombie Knight")
        status_before = (self.magic / "products/status.csv").read_bytes()
        result = self.fixed_plan()
        self.assertEqual([item["id"] for item in result["decks"]], ["casual/a", "casual/b"])
        self.assertEqual([item["after"] for item in result["decks"]], ["3 Zombie // Zombie Knight", "2 Zombie // Zombie Knight"])
        self.assertEqual(sum(item["spares"] for item in result["decks"]), 3)
        self.assertEqual((self.magic / "products/status.csv").read_bytes(), status_before)
        self.assertEqual(tokens.reserve.holds(tokens.read())[HOLDER]["rows"], {self.zombie(): 3})

    def test_overcommitted_product_exhausts_capacity_without_negative_or_freed_spares(self):
        self.status("10 Zombie // Zombie Knight")
        self.built("a")
        self.built("b")
        result = self.fixed_plan()
        self.assertTrue(all(item["after"] == "" and item["spares"] == 0 for item in result["decks"]))
        self.assertTrue(all(item["short"] == ["Zombie"] for item in result["decks"]))
        self.assertEqual(tokens.reserve.holds(tokens.read())[HOLDER]["rows"], {self.zombie(): 10})

    def test_fixed_mode_save_changes_only_decks_and_keeps_product_reservation(self):
        self.built("a")
        self.built("b")
        status_before = (self.magic / "products/status.csv").read_bytes()
        with mock.patch.object(plan_products, "gather", return_value=[]):
            preview = token_plan.plan_view()
            answer = self.call(token_plan.apply_plan, sha256=preview["sha256"])
        self.assertEqual(answer, {"saved": 2, "decks": ["casual/a", "casual/b"]})
        self.assertEqual((self.magic / "products/status.csv").read_bytes(), status_before)
        holds = tokens.reserve.holds(tokens.read())
        self.assertEqual(holds[HOLDER]["rows"], {self.zombie(): 3})
        self.assertEqual(sum(hold["rows"].get(self.zombie(), 0) for hold in holds.values()), 8)

    def test_malformed_or_duplicate_product_records_fail_closed_in_planning(self):
        self.built("a")
        for packed, extra in (("not a token packing line", ()),
                              ("3 Zombie // Zombie Knight", ({"file": f"{STEM}.csv", "status": "owned", "intact": "no"},))):
            self.status(packed, extra=extra)
            before = self.magic_files()
            warnings = []
            holds = tokens.reserve.holds(tokens.read(), warnings=warnings)
            self.assertTrue(warnings)
            self.assertTrue(any(hold.get("error") for hold in holds.values()))
            with self.assertRaises(RuntimeError):
                tokens.plan_token_cards()
            self.assertEqual(self.magic_files(), before)

    def test_orphan_nonempty_status_reservation_cannot_silently_become_free(self):
        self.status("", extra=({"file": "missing-product.csv", "status": "owned", "intact": "yes",
                                 "token_cards": "8 Zombie // Zombie Knight"},))
        self.built("a")
        warnings = []
        holds = tokens.reserve.holds(tokens.read(), warnings=warnings)
        self.assertTrue(warnings)
        self.assertTrue(any(hold.get("error") for hold in holds.values()))
        with self.assertRaises(RuntimeError):
            tokens.plan_token_cards()

    def test_receipt_changes_with_product_storage_even_if_deck_lines_do_not(self):
        self.built("a", source="1 Hornet Queen\n")
        first = tokens.plan_token_cards()
        self.status("4 Zombie // Zombie Knight")
        second = tokens.plan_token_cards()
        self.assertEqual(first["tokens_sha256"], second["tokens_sha256"])
        self.assertEqual([item["after"] for item in first["decks"]], [item["after"] for item in second["decks"]])
        self.assertNotEqual(first["sha256"], second["sha256"])

    def test_under_write_inventory_guard_refuses_product_change_after_preflight(self):
        self.built("a")
        result = tokens.plan_token_cards()
        items = []
        for item in result["decks"]:
            if not item["changed"]:
                continue
            parsed = item["parsed"]
            decks.set_token_cards(parsed, decks.parse_token_cards(item["after"]))
            items.append({"id": item["id"], "text": decks.render_deck_file(parsed), "base_sha256": item["sha256"]})
        self.status("4 Zombie // Zombie Knight")
        before = self.magic_files()
        with self.assertRaises(ops_decks.DeckRefused) as caught:
            inventory.apply(Op("deck.token_cards", {"items": items, "expected_inventory_revision": result["inventory_revision"]}),
                            Actor("matt", "Matt", "home"), "Stale fixture token plan")
        self.assertEqual(caught.exception.reason, "changed")
        self.assertEqual(self.magic_files(), before)

    def test_member_space_never_reads_home_product_reservations(self):
        with mock.patch.object(products, "records", side_effect=AssertionError("home product records read in member space")):
            self.assertEqual(tokens.reserve.holds(tokens.read(space="user2"), space="user2"), {})
            result = tokens.plan_token_cards("user2")
        self.assertEqual(result["decks"], [])

    def test_product_subdeck_projection_excludes_own_box_and_offers_every_owned_row(self):
        self.built("a", packed="1 Zombie // Zombie Knight")
        summary, sections = deck_page._deck_sections(f"{HOLDER}/one", "target")
        projected = deck_page._view_tokens(summary, "target", sections, [])
        packed = projected["packed"]
        self.assertEqual(packed["product"]["stem"], STEM)
        self.assertEqual(packed["product"]["status_sha256"], packed["expect"])
        self.assertEqual(len(packed["expect"]), 64)
        self.assertEqual(len(packed["choices"]), len(tokens.read().rows))
        zombie = next(row for row in packed["choices"] if row["front"] == "Zombie")
        self.assertEqual((zombie["quantity"], zombie["free"], zombie["packed"]), (8, 7, 3))
        need = next(need for need in projected["needs"] if need["name"] == "Zombie")
        self.assertEqual(need["cards"][0]["quantity"], 7)
        self.assertNotIn("in_use", need)

    def test_product_with_no_token_needs_still_exposes_its_actual_box_choices(self):
        self.write(f"products/{STEM}.csv", "section,name,set,collector_number,finish,quantity\n"
                   "deck,Llanowar Elves,fdn,227,nonfoil,1\n")
        summary, sections = deck_page._deck_sections(HOLDER, "target")
        projected = deck_page._view_tokens(summary, "target", sections, [])
        self.assertEqual(projected["needs"], [])
        self.assertEqual(projected["packed"]["product"]["stem"], STEM)
        self.assertEqual(len(projected["packed"]["choices"]), len(tokens.read().rows))

    def test_public_product_view_without_inventory_never_projects_packed_metadata(self):
        with access.using({"profile": "user2", "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", return_value=frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_view_tokens", side_effect=AssertionError("private token projection reached")), \
                mock.patch.object(products, "records", side_effect=AssertionError("private product reservation reached")), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            answer = deck_page.deck_view(f"{HOLDER}/one", omit=("matchups",))
        self.assertNotIn("tokens", answer)
        self.assertNotIn("owned", answer)
        serialized = json.dumps(answer)
        for private in ("tokens_sha256", "status_sha256", "3 Zombie // Zombie Knight"):
            self.assertNotIn(private, serialized)

    def test_public_collection_does_not_publish_private_product_packing_controls_or_receipts(self):
        with access.using({"profile": "user2", "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", side_effect=lambda thing: frozenset({"home"}) if thing == "collection" else frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            answer = deck_page.deck_view(f"{HOLDER}/one", omit=("matchups",))
        self.assertIn("tokens", answer)
        self.assertNotIn("packed", answer["tokens"])
        serialized = json.dumps(answer["tokens"])
        for private in ("tokens_sha256", "status_sha256", "3 Zombie // Zombie Knight"):
            self.assertNotIn(private, serialized)

    def test_public_collection_keeps_product_held_counts_but_redacts_holder_identity(self):
        self.status("8 Zombie // Zombie Knight")
        self.built("a")
        with access.using({"profile": "user2", "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", side_effect=lambda thing: frozenset({"home"}) if thing == "collection" else frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            answer = deck_page.deck_view("casual/a", omit=("matchups",))
            token_view = token_fixture.api_tok.tokens_view("home")
        need = next(need for need in answer["tokens"]["needs"] if need["name"] == "Zombie")
        self.assertEqual(sum(row["quantity"] for row in need["in_use"]), 8)
        self.assertTrue(all(row["decks"] == ["one of the home decks"] for row in need["in_use"]))
        serialized = json.dumps([answer["tokens"], token_view])
        for private in (HOLDER, "Opaque Bundle", "status_sha256", "8 Zombie // Zombie Knight"):
            self.assertNotIn(private, serialized)

    def test_public_collection_does_not_authorize_private_whole_space_token_plan(self):
        self.built("hidden-home", packed="1 Zombie // Zombie Knight")
        with access.using({"profile": "user2", "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset()), \
                mock.patch.object(guard, "public_spaces", side_effect=lambda thing: frozenset({"home"}) if thing == "collection" else frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(token_plan, "_plan", side_effect=AssertionError("private whole-space plan reached")):
            for call in (lambda: token_plan.plan_view("home"),
                         lambda: self.call(token_plan.apply_plan, profile="user2", space="home", sha256="0" * 64)):
                with self.assertRaises(ApiError) as caught:
                    call()
                self.assertEqual(caught.exception.status, 403)
