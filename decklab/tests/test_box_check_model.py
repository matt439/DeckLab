"""Box checks retain only a strict date and compare complete physical observations."""
import copy
from datetime import date
import unittest
from unittest import mock

from decklab.lib import decks
from decklab.lib.decks import assembled, boxcheck, standins


TEXT = ("# Fixture box\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** either\n- **Status:** built\n"
        "- **Built version:** target\n- **Sleeves:** shared-sleeves\n- **Deck box:** shared-box\n"
        "- **Custom provenance**: preserve this literally\n\n## Decklist\n\n```\nDeck\n"
        "4 Llanowar Elves (FDN) 227 *F*\n20 Forest\n\nSideboard\n1 Pick Your Poison\n```\n"
        "\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n2 Elvish Mystic\n20 Forest\n```\n"
        "\n## Notes\n\nKeep this prose and its spacing.\n")


def parsed(text=TEXT):
    return decks.parse_deck(text.encode("utf-8"), "fixture", "casual", space="home")


def card(name, quantity=1):
    return {"kind": "card", "name": name, "for": None, "quantity": quantity, "basic": name == "Forest"}


def marker(name, target, quantity=1):
    return {"kind": "marker", "name": name, "for": target, "quantity": quantity, "basic": None if name is None else False}


def observations(sections):
    return [{"section": section, "row": index, "quantity": row["quantity"]}
            for section in decks.SECTIONS for index, row in enumerate(sections.get(section, []))]


class BoxCheckedDateTests(unittest.TestCase):
    def test_read_only_strict_date_or_none_and_no_owned_editor_field(self):
        self.assertIsNone(boxcheck.checked_on(parsed()))
        for value in ("2024-02-29", "0001-01-01", "9999-12-31"):
            deck = parsed(TEXT.replace("- **Status:** built", f"- **Status:** built\n- **Box checked:** {value}"))
            self.assertEqual(boxcheck.checked_on(deck), value)
        self.assertNotIn(boxcheck.FIELD, decks.OWNED_FIELDS)
        self.assertNotIn(boxcheck.FIELD, decks.EDIT_FIELDS.values())

    def test_invalid_input_refuses_before_changing_any_header(self):
        deck = parsed()
        before = copy.deepcopy(deck.header)
        for value in (None, True, 20261027, date(2026, 10, 27), "", "20261027", "2026-1-01", "2026-01-1",
                      "2026-02-29", "1900-02-29", "0000-01-01", "2026-13-01", "2026-01-32",
                      "2026-10-27T12:00:00", " 2026-10-27", "2026-10-27\n", "２０２６-１０-２７"):
            with self.subTest(value=value), self.assertRaises(boxcheck.BoxCheckError):
                boxcheck.record_date(deck, value)
            self.assertEqual(deck.header, before)

    def test_malformed_single_header_reads_none_and_is_repaired_explicitly(self):
        deck = parsed(TEXT.replace("- **Status:** built", "- **Status:** built\n- **Box checked:** yesterday"))
        self.assertIsNone(boxcheck.checked_on(deck))
        self.assertTrue(boxcheck.record_date(deck, "2026-10-27"))
        self.assertEqual(boxcheck.checked_on(deck), "2026-10-27")
        self.assertIn("- **Box checked:** 2026-10-27\n", decks.render_deck_file(deck))

    def test_duplicate_headers_assert_no_date_and_refuse_without_mutation(self):
        for other in ("2026-10-27", "2026-10-28", "invalid"):
            deck = parsed(TEXT.replace("- **Status:** built", "- **Status:** built\n- **Box checked:** 2026-10-27\n"
                                       f"- **BOX CHECKED:** {other}"))
            before = copy.deepcopy(deck)
            self.assertIsNone(boxcheck.checked_on(deck))
            with self.assertRaisesRegex(boxcheck.BoxCheckError, "more than one"):
                boxcheck.record_date(deck, "2026-10-29")
            self.assertEqual(deck, before)

    def test_raw_header_is_replaced_and_updates_again_after_parse_render(self):
        text = TEXT.replace("- **Status:** built", "- **Status:** built\n- **BOX CHECKED**: 2026-10-25").replace("\n", "\r\n")
        deck = parsed(text)
        old = next(field for field in deck.header if field.key.casefold() == boxcheck.FIELD.casefold())
        self.assertIsNotNone(old.raw)
        self.assertTrue(boxcheck.record_date(deck, "2026-10-26"))
        replacement = next(field for field in deck.header if field.key == boxcheck.FIELD)
        self.assertIsNone(replacement.raw)
        self.assertEqual(replacement.end, "\r\n")
        written = decks.render_deck_file(deck)
        self.assertEqual(written, text.replace("- **BOX CHECKED**: 2026-10-25", "- **Box checked:** 2026-10-26"))
        again = parsed(written)
        self.assertTrue(boxcheck.record_date(again, "2026-10-27"))
        self.assertEqual(decks.render_deck_file(again), written.replace("2026-10-26", "2026-10-27"))
        self.assertFalse(boxcheck.record_date(again, "2026-10-27"))

    def test_record_changes_only_date_preserving_assembly_standins_tokens_kit_and_prose(self):
        deck = parsed()
        assembled.install(deck, "owned", deck.owned)
        standins.set_stand_ins(deck, {"target": [], "owned": [], "built": {"version": "owned", "cards": [
            {"for": "Elvish Mystic", "using": None, "qty": 1}]}})
        decks.set_token_cards(deck, [decks.TokenCardLine(2, "Dog", "Beast")])
        deck = parsed(decks.render_deck_file(deck))
        before = copy.deepcopy(deck)
        self.assertTrue(boxcheck.record_date(deck, "2026-10-27"))
        self.assertEqual(deck.header[:-1], before.header)
        for attr in ("target", "owned", "rows", "text", "spans", "changed_on"):
            self.assertEqual(getattr(deck, attr), getattr(before, attr))
        self.assertEqual((assembled.get(deck), standins.get_stand_ins(deck), decks.token_cards(deck), deck.sleeves, deck.deck_box),
                         (assembled.get(before), standins.get_stand_ins(before), decks.token_cards(before), before.sleeves, before.deck_box))
        rendered = decks.render_deck_file(deck)
        self.assertEqual(rendered.replace("- **Box checked:** 2026-10-27\n", ""), decks.render_deck_file(before))


class BoxCheckComparisonTests(unittest.TestCase):
    def setUp(self):
        self.sections = {"Commander": [card("Aerie Mystics")], "Companion": [card("Pick Your Poison")],
                         "Deck": [card("Forest", 20), card("Llanowar Elves", 2), marker("Elvish Mystic", "Llanowar Elves"),
                                  marker(None, "Pick Your Poison", 2)], "Sideboard": [card("Llanowar Elves")]}

    def compare(self, rows=None, extras=None, sections=None):
        sections = self.sections if sections is None else sections
        return boxcheck.compare(sections, observations(sections) if rows is None else rows,
                                [] if extras is None else extras, canonical_name=lambda name: {"opt": "Opt"}.get(name, name))

    def test_every_section_basics_and_markers_count_once_without_printing_claims(self):
        self.assertEqual(self.compare(), {"expected_cards": 28, "found_cards": 28, "missing": [], "extra": []})
        rows = observations(self.sections)
        rows.reverse()
        self.assertEqual(self.compare(rows), self.compare())

    def test_partial_found_excess_and_explicit_extras_have_conserving_section_aware_differences(self):
        rows = observations(self.sections)
        for row in rows:
            row["quantity"] += {("Commander", 0): -1, ("Deck", 0): -2, ("Deck", 2): -1,
                                ("Deck", 3): -1, ("Sideboard", 0): 2}.get((row["section"], row["row"]), 0)
        result = self.compare(rows, [{"section": "Deck", "name": "opt", "quantity": 2},
                                     {"section": "Sideboard", "name": "Forest", "quantity": 1}])
        self.assertEqual(result["missing"], [
            {"section": "Commander", "kind": "card", "name": "Aerie Mystics", "for": None, "quantity": 1},
            {"section": "Deck", "kind": "card", "name": "Forest", "for": None, "quantity": 2},
            {"section": "Deck", "kind": "marker", "name": "Elvish Mystic", "for": "Llanowar Elves", "quantity": 1},
            {"section": "Deck", "kind": "marker", "name": None, "for": "Pick Your Poison", "quantity": 1}])
        self.assertEqual(result["extra"], [
            {"section": "Sideboard", "kind": "card", "name": "Llanowar Elves", "for": None, "quantity": 2},
            {"section": "Deck", "kind": "card", "name": "Opt", "for": None, "quantity": 2},
            {"section": "Sideboard", "kind": "card", "name": "Forest", "for": None, "quantity": 1}])
        self.assertEqual((result["expected_cards"], result["found_cards"]), (28, 28))
        self.assertEqual(result["found_cards"], result["expected_cards"] - sum(row["quantity"] for row in result["missing"])
                         + sum(row["quantity"] for row in result["extra"]))
        self.assertTrue(all(set(row) == {"section", "kind", "name", "for", "quantity"}
                            for row in result["missing"] + result["extra"]))

    def test_same_card_in_another_section_does_not_hide_a_missing_copy(self):
        sections = {"Deck": [card("Forest")], "Sideboard": [card("Forest")]}
        result = self.compare([{"section": "Deck", "row": 0, "quantity": 0},
                               {"section": "Sideboard", "row": 0, "quantity": 2}], sections=sections)
        self.assertEqual(result["missing"][0]["section"], "Deck")
        self.assertEqual(result["extra"][0]["section"], "Sideboard")

    def test_found_real_card_never_nets_a_missing_named_or_anonymous_marker(self):
        for name in ("Elvish Mystic", None):
            sections = {"Deck": [marker(name, "Llanowar Elves", 2)]}
            result = self.compare([{"section": "Deck", "row": 0, "quantity": 0}],
                                  [{"section": "Deck", "name": "Elvish Mystic", "quantity": 2}], sections)
            self.assertEqual(result["missing"], [{"section": "Deck", "kind": "marker", "name": name,
                                                  "for": "Llanowar Elves", "quantity": 2}])
            self.assertEqual(result["extra"][0]["kind"], "card")
            self.assertIsNone(result["extra"][0]["for"])

    def test_excess_markers_keep_their_honest_role_and_target(self):
        sections = {"Deck": [marker(None, "Llanowar Elves")]}
        result = self.compare([{"section": "Deck", "row": 0, "quantity": 3}], sections=sections)
        self.assertEqual(result["extra"], [{"section": "Deck", "kind": "marker", "name": None,
                                           "for": "Llanowar Elves", "quantity": 2}])

    def test_explicit_extra_and_overfound_same_name_remain_independent_observations(self):
        result = self.compare([{"section": "Deck", "row": 0, "quantity": 2}],
                              [{"section": "Deck", "name": "Forest", "quantity": 2}], {"Deck": [card("Forest")]})
        self.assertEqual([row["quantity"] for row in result["extra"]], [1, 2])
        self.assertEqual((result["expected_cards"], result["found_cards"]), (1, 4))

    def test_missing_blank_duplicate_invalid_or_unreviewed_rows_refuse(self):
        sections = {"Deck": [card("Forest"), card("Opt")]}
        first, second = observations(sections)
        invalid = (None, [], [first], [first, first], [first, {**second, "row": 2}],
                   [first, {**second, "row": True}], [first, {**second, "row": "1"}],
                   [first, {**second, "section": "Sideboard"}], [first, {**second, "extra": 1}],
                   [first, {"section": "Deck", "row": 1}])
        for rows in invalid:
            with self.subTest(rows=rows), self.assertRaises(boxcheck.BoxCheckError):
                boxcheck.compare(sections, rows, [], canonical_name=lambda name: name)
        for value in (None, "", "1", 1.5, True, False, -1, 10000):
            with self.subTest(quantity=value), self.assertRaises(boxcheck.BoxCheckError):
                self.compare([first, {**second, "quantity": value}], sections=sections)

    def test_zero_and_upper_quantity_bound_are_explicit_integer_observations(self):
        sections = {"Deck": [card("Forest")]}
        self.assertEqual(self.compare([{"section": "Deck", "row": 0, "quantity": 0}], sections=sections)["found_cards"], 0)
        self.assertEqual(self.compare([{"section": "Deck", "row": 0, "quantity": 9999}],
                                     [{"section": "Deck", "name": "Opt", "quantity": 9999}], sections)["found_cards"], 19998)

    def test_extra_schema_positive_quantities_names_and_canonical_duplicates_are_checked(self):
        valid = {"section": "Deck", "name": "Opt", "quantity": 1}
        for extras in (None, {}, [None], [{**valid, "section": "Invalid"}], [{**valid, "name": None}],
                       [{**valid, "name": ""}], [{**valid, "name": "x" * 201}], [{**valid, "name": "Opt\n"}], [{**valid, "name": " Opt "}],
                       [{**valid, "quantity": 0}], [{**valid, "quantity": True}], [{**valid, "quantity": 10000}],
                       [{**valid, "quantity": "1"}], [{**valid, "extra": True}], [valid] * (boxcheck.MAX_EXTRAS + 1),
                       [valid, {**valid, "name": "opt"}]):
            with self.subTest(extras=extras), self.assertRaises(boxcheck.BoxCheckError):
                boxcheck.compare(self.sections, observations(self.sections), extras,
                                 canonical_name=lambda name: "Opt")
        result = self.compare(extras=[valid, {**valid, "section": "Sideboard"}])
        self.assertEqual(len(result["extra"]), 2)
        with self.assertRaisesRegex(boxcheck.BoxCheckError, "cannot be checked"):
            boxcheck.compare(self.sections, observations(self.sections), [valid], canonical_name=mock.Mock(side_effect=ValueError("Unknown")))

    def test_invalid_or_duplicate_authoritative_rows_fail_closed(self):
        for sections in (None, {}, {"Sideboard": [card("Forest")]}, {"Deck": []},
                         {"Deck": [card("Forest"), card("Forest")]}, {"Deck": [card(None)]},
                         {"Deck": [marker("Opt", None)]}, {"Deck": [card("Forest", True)]},
                         {"Deck": [{**card("Forest"), "kind": "invented"}]},
                         {"Deck": [card(f"Card {i}") for i in range(boxcheck.MAX_ROWS + 1)]}):
            with self.subTest(sections=sections), self.assertRaises(boxcheck.BoxCheckError):
                boxcheck.compare(sections, [], [], canonical_name=lambda name: name)

    def test_maximum_bounded_rows_and_extras_work_without_mutating_any_input(self):
        sections = {"Deck": [card(f"Fixture {i}") for i in range(boxcheck.MAX_ROWS)]}
        rows = observations(sections)
        extras = [{"section": "Sideboard", "name": f"Extra {i}", "quantity": 1} for i in range(boxcheck.MAX_EXTRAS)]
        before = copy.deepcopy((sections, rows, extras))
        result = self.compare(rows, extras, sections)
        self.assertEqual((result["expected_cards"], result["found_cards"]), (boxcheck.MAX_ROWS, boxcheck.MAX_ROWS + boxcheck.MAX_EXTRAS))
        self.assertEqual((sections, rows, extras), before)
