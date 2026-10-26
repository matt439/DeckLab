"""A box check observes physical rows and saves only a historical date, in temp data."""
import copy
import json
import re
from unittest import mock

from decklab.lib import access, decks, inventory, state
from decklab.lib.api import assembly_takeapart, box_check, deck_page, editor, guard, history
from decklab.lib.api.common import ApiError
from decklab.lib.decks import assembled, boxcheck, standins
from decklab.lib.inventory import Op, files, ops_decks
from decklab.lib.state import Actor
from decklab.lib.state.memory import MemoryStore
from decklab.tests import household_config
from decklab.tests import test_collection_assembly as preparation
from decklab.tests import test_pool as pool_fixture

setUpModule = pool_fixture.setUpModule
tearDownModule = pool_fixture.tearDownModule

ELF = "Llanowar Elves"
MYSTIC = "Elvish Mystic"
POISON = "Pick Your Poison"
WHEN = "2026-10-26"
MAIN = f"Deck\n4 {ELF}\n20 Forest\n\nSideboard\n2 {MYSTIC}\n"


class BoxCheckCase(preparation.PreparationCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.addCleanup(state.use(MemoryStore()))
        active = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        self.cards_csv("collection.csv", (ELF, "fdn", "227", "nonfoil", 8),
                       (MYSTIC, "cmm", "648", "nonfoil", 8), (POISON, "mkm", "170", "nonfoil", 3))
        self.deck("a", "A", "built", MAIN, owned=f"Deck\n2 {MYSTIC}\n20 Forest\n", built_version="target")
        patcher = mock.patch.object(box_check, "_today", return_value=WHEN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def record(self):
        return inventory.current().deck("casual/a")

    def parsed(self):
        return ops_decks.parsed_deck(self.record())

    def write_parsed(self, deck):
        self.write("decks/casual/a.md", decks.render_deck_file(deck))

    def offer(self, version="target"):
        return self.preview(("a", version))["decks"][0]

    def payload(self):
        offer = self.offer()
        return {"profile": "matt", "id": "casual/a", "expect": offer["box_check"]["expect"],
                "recipe_sha256": offer["box_check"]["recipe_sha256"],
                "rows": [{"section": section, "row": index, "quantity": row["quantity"]}
                         for section, rows in offer["take_apart"]["sections"].items() for index, row in enumerate(rows)],
                "extras": []}

    def save(self, data=None, **changes):
        body = self.payload() if data is None else copy.deepcopy(data)
        body.update(changes)
        return box_check.save_box_check(json.dumps(body).encode())

    def refused(self, status, data=None, **changes):
        with self.assertRaises(ApiError) as caught:
            self.save(data, **changes)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        return caught.exception


class BoxCheckApiTests(BoxCheckCase):
    def test_assembly_offer_uses_saved_physical_sections_and_has_no_read_side_effects(self):
        deck = self.parsed()
        physical = decks.parse_decklist(f"Deck\n1 {MYSTIC}\n12 Forest\n\nSideboard\n1 {POISON}\n")
        assembled.install(deck, "owned", physical)
        self.write_parsed(deck)
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(self.inventory, "apply", side_effect=AssertionError("Read wrote data")):
            offer = self.offer()
        info = offer["box_check"]
        self.assertEqual(info, {"expect": self.record().sha256, "checked_on": None, "editable": True, "why_not": None,
                                "recipe_sha256": box_check.recipe_sha256("owned", offer["take_apart"]["sections"])})
        self.assertEqual(offer["take_apart"]["version"], "owned")
        self.assertEqual(offer["take_apart"]["card_count"], 14)
        self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_legacy_save_adds_only_date_without_freezing_or_changing_any_other_data(self):
        deck = self.parsed()
        decks.set_sleeves(deck, "fixture older sleeves")
        decks.set_deck_box(deck, "fixture older box")
        decks.set_token_cards(deck, [decks.TokenCardLine(1, "Dog", "Beast")])
        standins.set_stand_ins(deck, {"target": [], "owned": [], "built": {
            "version": "target", "cards": [{"for": ELF, "using": POISON, "qty": 1}]}})
        self.write_parsed(deck)
        before = self.record().text
        inventory_before = files.render(inventory.current())
        answer = self.save()
        after = self.record()
        self.assertTrue(answer["saved"])
        self.assertEqual((answer["id"], answer["checked_on"], answer["expected_cards"], answer["found_cards"]),
                         ("casual/a", WHEN, 26, 26))
        self.assertEqual((answer["missing"], answer["extra"], answer["sha256"]), ([], [], after.sha256))
        self.assertEqual(re.sub(r"^- \*\*Box checked:\*\* .*\n", "", after.text, flags=re.M), before)
        self.assertIsNone(assembled.get(self.parsed()))
        self.assertEqual(files.render(inventory.current()), inventory_before)

    def test_shortages_overages_and_explicit_extras_are_returned_but_never_persisted(self):
        body = self.payload()
        rows = self.offer()["take_apart"]["sections"]
        elf = next(index for index, row in enumerate(rows["Deck"]) if row["name"] == ELF)
        forest = next(index for index, row in enumerate(rows["Deck"]) if row["name"] == "Forest")
        for row in body["rows"]:
            if row["section"] == "Deck" and row["row"] == elf:
                row["quantity"] -= 1
            if row["section"] == "Deck" and row["row"] == forest:
                row["quantity"] += 1
        body["extras"] = [{"section": "Sideboard", "name": POISON, "quantity": 2}]
        before = self.record().text
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            answer = self.save(body)
        self.assertEqual(answer["missing"], [{"section": "Deck", "kind": "card", "name": ELF, "for": None, "quantity": 1}])
        self.assertEqual(answer["extra"], [{"section": "Deck", "kind": "card", "name": "Forest", "for": None, "quantity": 1},
                                           {"section": "Sideboard", "kind": "card", "name": POISON, "for": None, "quantity": 2}])
        self.assertEqual((answer["expected_cards"], answer["found_cards"]), (26, 28))
        self.assertEqual(re.sub(r"^- \*\*Box checked:\*\* .*\n", "", self.record().text, flags=re.M), before)
        self.assertEqual(apply.call_count, 1)
        op, _, message = apply.call_args.args[:3]
        self.assertEqual(set(op.params), {"deck_id", "text", "base_sha256"})
        self.assertEqual(message, "Record a box check for A")
        self.assertNotIn(POISON, op.params["text"])

    def test_installed_named_and_anonymous_markers_keep_their_roles_and_all_sections(self):
        deck = self.parsed()
        assembled.install(deck, "target", deck.target)
        standins.set_stand_ins(deck, {"target": [{"for": ELF, "using": POISON, "qty": 4}], "owned": [],
                                     "built": {"version": "target", "cards": [
                                         {"for": ELF, "using": POISON, "qty": 1}, {"for": ELF, "using": None, "qty": 1}]}})
        self.write_parsed(deck)
        before = assembled.get(deck), assembled.generation(deck), standins.get_stand_ins(deck)
        offer = self.offer()
        physical = offer["take_apart"]["sections"]
        anonymous = next(index for index, row in enumerate(physical["Deck"]) if row["kind"] == "marker" and row["name"] is None)
        body = self.payload()
        next(row for row in body["rows"] if row["section"] == "Deck" and row["row"] == anonymous)["quantity"] = 0
        body["extras"] = [{"section": "Deck", "name": ELF, "quantity": 1}]
        answer = self.save(body)
        self.assertEqual(answer["missing"], [{"section": "Deck", "kind": "marker", "name": None, "for": ELF, "quantity": 1}])
        self.assertEqual(answer["extra"], [{"section": "Deck", "kind": "card", "name": ELF, "for": None, "quantity": 1}])
        after = self.parsed()
        self.assertEqual((assembled.get(after), assembled.generation(after), standins.get_stand_ins(after)), before)
        self.assertEqual(answer["expected_cards"], 26)
        illustrated = self.preview(("a", "target"))["box_check_cards"]
        self.assertIn(POISON, illustrated)
        self.assertNotIn(None, illustrated)

    def test_incomplete_duplicate_unoffered_and_invalid_counts_refuse_without_writes(self):
        body = self.payload()
        bad = [body["rows"][:-1], body["rows"] + body["rows"][:1], [body["rows"][0]] * len(body["rows"])]
        bad.extend([[dict(body["rows"][0], **change), *body["rows"][1:]] for change in (
            {"quantity": True}, {"quantity": "1"}, {"quantity": -1}, {"quantity": 10000},
            {"row": True}, {"section": "Unknown"}, {"extra": 1})])
        before = files.render(inventory.current(), decks=True)
        for rows in bad:
            with self.subTest(rows=rows):
                self.refused(400, body, rows=rows)
                self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_extra_names_counts_roles_and_shapes_are_strict(self):
        body = self.payload()
        invalid = [{"section": "Deck", "name": name, "quantity": 1} for name in ("Unknown fixture card", ELF.lower(), f" {ELF} ")]
        invalid += [dict(section="Deck", name=POISON, quantity=value) for value in (True, 0, -1, "1", 10000)]
        invalid += [dict(section="Not a section", name=POISON, quantity=1),
                    dict(section="Deck", name=POISON, quantity=1, set="mkm")]
        before = self.record().text
        for extra in invalid:
            with self.subTest(extra=extra):
                self.refused(400, body, extras=[extra])
                self.assertEqual(self.record().text, before)
        self.refused(400, body, extras=[{"section": "Deck", "name": POISON, "quantity": 1}] * 2)

    def test_changed_recipe_receipt_refuses_before_interpreting_any_row(self):
        body = self.payload()
        with mock.patch.object(boxcheck, "compare", side_effect=AssertionError("Stale row indices interpreted")):
            error = self.refused(409, body, recipe_sha256="0" * 64)
        self.assertIn("physical checklist changed", error.message)
        self.assertIsNone(boxcheck.checked_on(self.parsed()))

    def test_changed_canonical_card_names_with_same_text_invalidate_row_meaning(self):
        body = self.payload()
        original = assembly_takeapart._name
        with mock.patch.object(assembly_takeapart, "_name", side_effect=lambda name: POISON if name == ELF else original(name)), \
                mock.patch.object(boxcheck, "compare", side_effect=AssertionError("Changed canonical rows interpreted")):
            self.refused(409, body)
        self.assertEqual(self.record().sha256, body["expect"])

    def test_old_deck_hash_refuses_whole_check_and_never_reuses_observations(self):
        body = self.payload()
        self.write("decks/casual/a.md", self.record().text.replace("# A\n", "# Renamed A\n", 1))
        error = self.refused(409, body)
        self.assertIn("conflict", error.extra)
        self.assertIsNone(boxcheck.checked_on(self.parsed()))

    def test_full_lowercase_hashes_and_strict_request_keys_are_required(self):
        body = self.payload()
        for key in ("expect", "recipe_sha256"):
            for value in (None, 0, True, "a" * 12, "A" * 64):
                with self.subTest(key=key, value=value):
                    self.refused(400, body, **{key: value})
        self.refused(400, body, unexpected=True)

    def test_same_day_recheck_returns_current_differences_without_duplicate_write(self):
        self.save()
        before = self.record().text
        body = self.payload()
        body["extras"] = [{"section": "Deck", "name": POISON, "quantity": 1}]
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            answer = self.save(body)
        self.assertFalse(answer["saved"])
        self.assertEqual(answer["checked_on"], WHEN)
        self.assertEqual(answer["found_cards"], 27)
        self.assertEqual(self.record().text, before)
        self.assertEqual(apply.call_count, 1)  # An unchanged save still checks the receipt under lock.

    def test_unbuilt_product_and_pairing_sources_cannot_save_a_box_date(self):
        body = self.payload()
        self.deck("a", "A", "building", MAIN)
        self.refused(400, body, expect=self.record().sha256)
        self.refused(400, body, id="product/fixture/deck")
        self.refused(400, body, id="pairing/a+b")

    def test_hidden_deck_lookup_precedes_home_or_hash_errors(self):
        body = self.payload()
        for deck_id in ("casual/a", "casual/never-was"):
            with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                    mock.patch.object(boxcheck, "checked_on", side_effect=AssertionError("Hidden metadata read")):
                error = self.refused(404, body, profile="user2", id=deck_id, expect="bad", recipe_sha256="bad")
                self.assertEqual(error.message, f"No deck '{deck_id}'")

    def test_home_reader_without_edit_gets_disabled_metadata_and_cannot_save(self):
        deck = self.parsed()
        decks.set_player(deck, "user")
        self.write_parsed(deck)
        body = self.payload()
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.assertFalse(self.offer()["box_check"]["editable"])
            self.assertTrue(self.offer()["box_check"]["why_not"])
            self.refused(403, body, profile="user1")

    def test_visible_member_deck_is_refused_home_access_before_receipts_or_metadata(self):
        body = self.payload()
        folder = self.magic / "people" / "user2" / "decks" / "casual"
        folder.mkdir(parents=True)
        (folder / "own.md").write_text(self.record().text.replace("- **Played by:** either\n", ""), encoding="utf-8")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                mock.patch.object(boxcheck, "checked_on", side_effect=AssertionError("Member date read")):
            self.refused(403, body, profile="user2", id="user2/casual/own", expect="bad", recipe_sha256="bad")

    def test_recipe_unavailable_for_malformed_assembly_never_falls_back_to_intended(self):
        deck = self.parsed()
        deck.header.append(decks.HeaderField("Assembled", "{bad"))
        self.write_parsed(deck)
        info = box_check.project(deck, self.record(), {"available": False, "reason": "Physical source unavailable"})
        self.assertFalse(info["editable"])
        self.assertIsNone(info["recipe_sha256"])
        self.refused(409, {"profile": "matt", "id": "casual/a", "expect": self.record().sha256,
                           "recipe_sha256": "0" * 64, "rows": [], "extras": []})

    def test_malformed_packed_token_header_disables_ui_and_refuses_date_before_observations(self):
        body = self.payload()
        deck = self.parsed()
        deck.header.append(decks.HeaderField("Token cards", "not a valid quantity"))
        self.write_parsed(deck)
        body["expect"] = self.record().sha256
        info = box_check.project(deck, self.record(), assembly_takeapart.project(deck, self.record(), None))
        self.assertFalse(info["editable"])
        self.assertIsNone(info["recipe_sha256"])
        before = files.render(inventory.current(), decks=True)
        with mock.patch.object(boxcheck, "compare", side_effect=AssertionError("Malformed physical metadata interpreted")):
            self.refused(409, body)
        self.assertEqual(files.render(inventory.current(), decks=True), before)

    def test_late_index_failure_is_static_and_writes_no_date(self):
        body = self.payload()
        with mock.patch.object(assembly_takeapart, "_name", side_effect=RuntimeError("private fixture index path")):
            error = self.refused(503, body)
        self.assertNotIn("private fixture", error.message)
        self.assertIsNone(boxcheck.checked_on(self.parsed()))

    def test_separate_physical_art_map_does_not_change_intended_printing_or_claim_markers_printing(self):
        self.deck("a", "A", "built", f"Deck\n4 {ELF} (FDN) 227 *F*\n20 Forest\n")
        result = self.preview(("a", "target"))
        self.assertEqual(result["cards"][ELF]["img_small"], "/img/fdn/227/small")
        physical = result["decks"][0]["take_apart"]["sections"]
        self.assertTrue(all("finish" not in row and "set" not in row for rows in physical.values() for row in rows))
        self.assertIn(ELF, result["box_check_cards"])
        self.assertLessEqual(set(result["box_check_cards"]), {ELF, "Forest"})

    def test_historical_date_is_private_and_stays_out_of_editor_history_and_prose_fields(self):
        self.save()
        own = deck_page.deck_view("casual/a", omit="matchups")
        self.assertEqual(own["box_checked_on"], WHEN)
        self.assertNotIn("Box checked", editor.edit_view("casual/a")["fields"])
        self.assertNotIn("Box checked", history._fields(self.parsed(), ()))
        state.store().visibility_set("home", "decks", True, Actor("matt", "Matt", source="web"), "Fixture public deck")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertTrue(guard.sees_deck("casual/a"))
            public = deck_page.deck_view("casual/a", omit="matchups")
            self.assertNotIn("box_checked_on", public)
            self.assertNotIn("Box checked", json.dumps(public))
            self.refused(403, {"profile": "user2", "id": "casual/a", "expect": self.record().sha256,
                               "recipe_sha256": "0" * 64, "rows": [], "extras": []})

    def test_write_lock_receipt_preserves_a_concurrent_edit_and_saves_no_date(self):
        body = self.payload()
        original = box_check.apply_op
        def change_then_apply(op, *args, **kwargs):
            held = self.record()
            changed = held.text.replace("# A\n", "# Concurrent A\n", 1)
            inventory.apply(Op("deck.save", {"deck_id": held.id, "text": changed, "base_sha256": held.sha256}),
                            Actor("claude", "Claude", source="cli"), "Fixture concurrent edit")
            return original(op, *args, **kwargs)
        with mock.patch.object(box_check, "apply_op", side_effect=change_then_apply):
            self.refused(409, body)
        self.assertEqual(self.parsed().title, "Concurrent A")
        self.assertIsNone(boxcheck.checked_on(self.parsed()))
