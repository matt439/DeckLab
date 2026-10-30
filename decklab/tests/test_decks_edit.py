"""Tests for decklab.lib.decks.edit (through decks): header fields,
apply_edit, Notes labels and the owned-vs-needed table. The fixtures and
helpers are in test_decks.py (see its docstring).

Run from the repo root:
    python scripts/test_fixtures.py
"""
import copy
import unittest

from decklab.lib import decks
from decklab.lib.decks import DeckLine, PriceStamp, TableRow, TotalRow
from decklab.tests.test_decks import FIXTURE_FILES, FIXTURE_STAMP, new_deck_bytes, parse, prose, read, rerender


class EditTests(unittest.TestCase):
    """Each edit changes only the intended text; prose stays byte for byte."""

    def setUp(self):
        self.deck = read("casual/gruul-ramp")
        self.original = self.deck.text
        self.assertEqual(self.deck.newline, "\n", "the fixture must have LF line endings")

    def check(self, expected):
        text, again = rerender(self.deck)
        self.assertEqual(text, expected)
        self.assertEqual(prose(again), prose(self.deck))
        return again

    def test_change_a_quantity(self):
        self.deck.target["Deck"][0].quantity = 3
        expected = self.original.replace("4 Llanowar Elves (FDN) 227\n", "3 Llanowar Elves (FDN) 227\n", 1)
        again = self.check(expected)
        self.assertEqual(again.owned["Deck"][0].quantity, 4)     # the owned list is untouched

    def test_add_a_card(self):
        self.deck.target["Sideboard"].append(DeckLine(2, "Lovestruck Beast", "eld", "165"))
        old = "1 Obliterating Bolt (FDN) 629\n```"
        self.check(self.original.replace(old, "1 Obliterating Bolt (FDN) 629\n2 Lovestruck Beast (ELD) 165\n```", 1))

    def test_add_a_new_section(self):
        self.deck.target["Companion"] = [DeckLine(1, "Lurrus of the Dream-Den", "iko", "226")]
        self.check(self.original.replace("```\nDeck\n", "```\nCompanion\n1 Lurrus of the Dream-Den (IKO) 226\n\nDeck\n", 1))

    def test_remove_a_card(self):
        self.deck.target["Sideboard"] = [l for l in self.deck.target["Sideboard"] if l.name != "Chaos Warp"]
        self.check(self.original.replace("Sideboard\n1 Chaos Warp (FDC) 146\n", "Sideboard\n", 1))

    def test_edit_the_owned_list(self):
        self.deck.owned["Deck"].pop()         # 7 Mountain
        head, sep, tail = self.original.partition("### Owned-only version")
        self.check(head + sep + tail.replace("9 Forest\n7 Mountain\n", "9 Forest\n", 1))

    def test_change_status(self):
        decks.set_status(self.deck, "built")
        again = self.check(self.original.replace("- **Status:** idea\n", "- **Status:** built\n"))
        self.assertEqual(again.status, "built")
        with self.assertRaises(ValueError):
            decks.set_status(self.deck, "finished")

    def test_change_player_keeps_the_rest_of_the_value(self):
        decks.set_player(self.deck, "wife")
        again = self.check(self.original.replace("- **Played by:** either. Suits", "- **Played by:** wife. Suits"))
        self.assertEqual(again.player, "wife")

    def test_add_and_remove_an_owned_field(self):
        decks.set_field(self.deck, "target bracket", "2 (Core)")
        again = self.check(self.original.replace("- **Status:** idea\n",
                                                 "- **Status:** idea\n- **Target bracket:** 2 (Core)\n"))
        self.assertEqual(again.target_bracket, 2)
        decks.set_field(again, "Target bracket", None)
        self.assertEqual(decks.render_deck_file(again), self.original)

    def test_built_version(self):
        deck = read("commander/gisa-zombies")
        decks.set_built_version(deck, "owned")
        _, again = rerender(deck)
        self.assertEqual([k for k, _ in again.fields][3:6], ["Status", "Built version", "Target bracket"])
        self.assertEqual((again.get_field("Built version"), again.built_version), ("owned-only", "owned"))
        decks.set_built_version(again, "target")
        self.assertEqual(again.built_version, "target")
        decks.set_built_version(again, None)
        self.assertEqual(decks.render_deck_file(again), deck.text)
        with self.assertRaises(ValueError):
            decks.set_built_version(deck, "both")

    def test_sleeves(self):
        decks.set_sleeves(self.deck, "  Dragon Shield matte red ")
        again = self.check(self.original.replace("- **Status:** idea\n",
                                                 "- **Status:** idea\n- **Sleeves:** Dragon Shield matte red\n"))
        self.assertEqual(again.sleeves, "Dragon Shield matte red")
        # In a Commander deck it goes under the other owned fields, Target bracket included.
        deck = read("commander/gisa-zombies")
        decks.set_sleeves(deck, "Black")
        _, gisa = rerender(deck)
        self.assertEqual([k for k, _ in gisa.fields][3:6], ["Status", "Target bracket", "Sleeves"])
        decks.set_sleeves(again, "Blue")
        self.assertEqual(again.get_field("Sleeves"), "Blue")
        decks.set_sleeves(again, None)
        self.assertEqual(decks.render_deck_file(again), self.original)
        for bad in ("", "   ", "Red\n## Injected"):
            with self.subTest(bad), self.assertRaises(ValueError):
                decks.set_sleeves(again, bad)

    def test_deck_box(self):
        # It goes after the other owned fields, and Sleeves added later goes in front of it.
        decks.set_deck_box(self.deck, " ultimate-guard-boulder-100-black ")
        again = self.check(self.original.replace(
            "- **Status:** idea\n", "- **Status:** idea\n- **Deck box:** ultimate-guard-boulder-100-black\n"))
        self.assertEqual(again.deck_box, "ultimate-guard-boulder-100-black")
        decks.set_sleeves(again, "dragon-shield-matte-black")
        _, both = rerender(again)
        keys = [k for k, _ in both.fields]
        self.assertEqual(keys[keys.index("Status"):keys.index("Status") + 3], ["Status", "Sleeves", "Deck box"])
        decks.set_deck_box(both, None)
        decks.set_sleeves(both, None)
        self.assertEqual(decks.render_deck_file(both), self.original)
        self.assertIsNone(both.deck_box)
        for bad in ("", "   ", "Box\n## Injected"):
            with self.subTest(bad), self.assertRaises(ValueError):
                decks.set_deck_box(both, bad)

    def test_non_owned_fields_are_refused(self):
        for key in ("Complexity", "Paired against", "Configuration"):
            with self.assertRaises(ValueError):
                decks.set_field(self.deck, key, "x")

    def test_values_that_would_break_the_file_are_refused(self):
        decks.set_field(self.deck, "Archetype", "Ramp\n## Injected")
        with self.assertRaises(ValueError):
            decks.render_deck_file(self.deck)
        self.deck = read("casual/gruul-ramp")
        for row in [TableRow("Opt | x", 1, 1, 0), TableRow("Opt", 1, 1, 0, notes_cell=" a\nb "),
                    TableRow("", 1, 1, 0), TableRow("Opt", 1, 2, -1)]:
            self.deck.rows = [row]
            with self.subTest(row), self.assertRaises(ValueError):
                decks.render_deck_file(self.deck)

    def test_replace_the_table_rows(self):
        # The list loses Chaos Warp and gains Lovestruck Beast, so the table does too.
        sideboard = self.deck.target["Sideboard"]
        sideboard[:] = [l for l in sideboard if l.name != "Chaos Warp"] + [DeckLine(2, "Lovestruck Beast", "eld", "165")]
        rows = [TableRow(r.card, r.need, r.owned, r.missing, r.aud_each, r.aud_missing)
                for r in self.deck.rows if r.card != "Chaos Warp"]
        thragtusk = next(r for r in rows if r.card == "Thragtusk")
        thragtusk.owned, thragtusk.missing, thragtusk.aud_each, thragtusk.aud_missing = 2, 0, "", ""
        rows.append(TableRow("Lovestruck Beast", 2, 0, 2, decks.format_aud(0.27), decks.format_aud(0.54)))
        decks.set_table(self.deck, decks.sort_table_rows(rows), TotalRow(8, "~$3.18"))
        text, again = rerender(self.deck)

        edited = self.original.replace("Sideboard\n1 Chaos Warp (FDC) 146\n", "Sideboard\n", 1).replace(
            "1 Obliterating Bolt (FDN) 629\n```", "1 Obliterating Bolt (FDN) 629\n2 Lovestruck Beast (ELD) 165\n```", 1)
        start, end = self.deck.spans["table"]
        start += len(edited) - len(self.original)
        new_end = len(text) - (len(self.original) - end)
        self.assertEqual(text[:start], edited[:start])
        self.assertEqual(text[new_end:], self.original[end:])
        table = text[start:new_end].splitlines()
        self.assertEqual(table[:5], [
            "| Cinder Glade | 2 | 0 | **2** | ~$0.40 | ~$0.80 |  |",
            "| Glorybringer | 2 | 0 | **2** | ~$0.46 | ~$0.92 |  |",
            "| Lovestruck Beast | 2 | 0 | **2** | ~$0.27 | ~$0.54 |  |",
            "| Rootbound Crag | 2 | 0 | **2** | ~$0.46 | ~$0.92 |  |",
            "| Aggressive Mammoth | 1 | 1 | 0 | | |  |",
        ])
        self.assertIn("| Thragtusk | 2 | 2 | 0 | | |  |", table)
        self.assertIn("| Eternal Witness | 1 | 1 | 0 | | | |", table)      # its " " notes cell kept
        self.assertNotIn("Chaos Warp", text[start:new_end])
        self.assertEqual(table[-1], "| **Total to buy** | | | **8** | | **~$3.18** | |")
        self.assertEqual(prose(again), prose(self.deck))

    def test_new_prices_update_the_stamp_above_the_table(self):
        self.assertEqual(self.deck.prices, FIXTURE_STAMP)
        decks.set_table(self.deck, self.deck.rows, self.deck.total, FIXTURE_STAMP)
        self.assertEqual(decks.render_deck_file(self.deck), self.original)       # same stamp: no change
        decks.set_table(self.deck, self.deck.rows, self.deck.total, PriceStamp(1.4237, "2026-09-28", "2026-09-29"))
        again = self.check(self.original.replace("1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28",
                                                 "1 USD = 1.4237 AUD (ECB rate of 2026-09-28), pulled 2026-09-29"))
        self.assertEqual(again.prices, PriceStamp(1.4237, "2026-09-28", "2026-09-29"))
        self.deck.prices = None                   # None leaves the stamp as it is
        self.assertEqual(decks.render_deck_file(self.deck), self.original)

    def test_table_notes_follow_their_card(self):
        deck = read("commander/gisa-zombies")
        rows = list(reversed([TableRow(r.card, r.need, r.owned, r.missing, r.aud_each, r.aud_missing)
                              for r in deck.rows]))
        decks.set_table(deck, rows, deck.total)
        _, again = rerender(deck)
        notes = {r.card: r.notes_cell for r in again.rows}
        self.assertEqual(notes, {r.card: r.notes_cell for r in read("commander/gisa-zombies").rows})
        self.assertEqual(again.rows[0].card, "Zul Ashur, Lich Lord")


class NotesLabelTests(unittest.TestCase):
    """set_table puts pool's labels in place of the old ones and keeps the
    hand-written part of each Notes cell."""

    TEXT = ("# T\n\n## Decklist\n\n```\nDeck\n1 Opt\n```\n\n## Owned vs needed\n\n"
            + decks.TABLE_HEADER + "\n" + decks.TABLE_RULE + "\n| Opt | 1 | 1 | 0 | | |{old_cell}|\n"
            "| **Total to buy** | | | **0** | | |{total_cell}|\n")

    def notes(self, old_cell, labels, saves=1, total_cell=" ", total=None):
        """Opt's Notes cell after `saves` saves with these labels (and the
        total row's cell, when total_cell/total are given)."""
        deck = parse(self.TEXT.format(old_cell=old_cell, total_cell=total_cell))
        for _ in range(saves):
            decks.set_table(deck, [TableRow("Opt", 1, 1, 0, labels=labels)], total or TotalRow(0))
            _, deck = rerender(deck)
        return deck.rows[0].notes_cell if total is None else (deck.rows[0].notes_cell, deck.total.notes_cell)

    def test_labels_replace_old_labels_and_keep_hand_notes(self):
        self.assertEqual(self.notes("  ", ("1 on the way (order x)",)), " 1 on the way (order x) ")
        self.assertEqual(self.notes(" on the way (Wretched Ranks precon) ", ()), "  ")
        self.assertEqual(self.notes(" keep these ", ("2 in use in Deck B",)), " 2 in use in Deck B; keep these ")
        self.assertEqual(self.notes(" 1 on the way (A); keep these ", ("1 on the way (B)",)),
                         " 1 on the way (B); keep these ")
        self.assertEqual(self.notes(" 1 on the way (A);keep  these ", ()), " keep  these ")
        self.assertEqual(self.notes(" 1 on the way (A); 1 in use in B; keep ", ("1 in use in C",)),
                         " 1 in use in C; keep ")

    def test_unchanged_labels_and_no_labels_leave_the_cell_alone(self):
        self.assertEqual(self.notes(" 1 on the way (A);keep these ", ("1 on the way (A)",)),
                         " 1 on the way (A);keep these ")
        self.assertEqual(self.notes(" 1 on the way (A) ", None), " 1 on the way (A) ")
        self.assertEqual(self.notes(r" any printing \| cheapest ", ()), r" any printing \| cheapest ")

    def test_hand_notes_that_look_like_labels_are_kept(self):
        # Only a run of exact labels at the start of the cell is Deck Lab's.
        for hand in ("on the way (eBay order, due 2026-10-05, tracking AB123)",
                     "in use in Finneas Rabbits once that's built, keep 1 spare",
                     "keep these; 1 on the way (order x)"):
            with self.subTest(hand):
                self.assertEqual(self.notes(f" {hand} ", ()), f" {hand} ")
                self.assertEqual(self.notes(f" {hand} ", ("2 in use in B",)), f" 2 in use in B; {hand} ")

    def test_the_rest_of_the_cell_is_kept_byte_for_byte(self):
        self.assertEqual(self.notes(" buy at MTGMate (A$0.30;0.40) ", ("1 on the way (order x)",)),
                         " 1 on the way (order x); buy at MTGMate (A$0.30;0.40) ")
        self.assertEqual(self.notes(" buy the MTGMate copy;in use in Sam's deck until he returns it ",
                                    ("1 on the way (order x)",)),
                         " 1 on the way (order x); buy the MTGMate copy;in use in Sam's deck until he returns it ")

    def test_deck_titles_with_separators_give_stable_labels(self):
        # A ';' or '|' in a deck title would split the cell or end it.
        for saves in (1, 3):
            self.assertEqual(self.notes("  ", ("1 in use in Rabbits; Go Wide",), saves), " 1 in use in Rabbits, Go Wide ")
            self.assertEqual(self.notes("  ", ("1 in use in Rabbits | Birds",), saves), " 1 in use in Rabbits / Birds ")
        with self.assertRaises(ValueError):          # not a form Deck Lab could find again
            decks.clean_label("on the way soon")

    def test_the_total_row_keeps_its_hand_notes(self):
        self.assertEqual(self.notes("  ", (), total_cell=" about A$5 at MTGMate ", total=TotalRow(0)),
                         ("  ", " about A$5 at MTGMate "))
        total = TotalRow(1, "~$1.00", labels=("not counted, no price: Black Lotus",))
        self.assertEqual(self.notes("  ", (), 2, total_cell=" about A$5 at MTGMate ", total=total),
                         ("  ", " not counted, no price: Black Lotus; about A$5 at MTGMate "))
        self.assertEqual(self.notes("  ", (), total_cell=" not counted, no price: Opt; A$5 ", total=TotalRow(0, labels=())),
                         ("  ", " A$5 "))


class ApplyEditTests(unittest.TestCase):
    """decks.apply_edit: what a save from the editor does to the model."""

    def test_the_same_lists_and_fields_change_nothing(self):
        for path in FIXTURE_FILES:
            with self.subTest(path.stem):
                deck = decks.read_deck_file(path)
                fields = {"status": deck.status, "player": deck.player, "archetype": deck.get_field("Archetype"),
                          "built_version": deck.built_version, "target_bracket": deck.target_bracket}
                if deck.kind != "commander":
                    fields.pop("target_bracket")
                changes = decks.apply_edit(deck, copy.deepcopy(deck.target), copy.deepcopy(deck.owned), fields,
                                           "2026-10-05")
                self.assertEqual(changes, {"decklist": False, "fields": []})
                self.assertEqual(decks.render_deck_file(deck), path.read_bytes().decode("utf-8"))

    def test_a_list_change_marks_the_file(self):
        deck = read("casual/gruul-ramp")
        target = copy.deepcopy(deck.target)
        target["Deck"][0].quantity = 3
        changes = decks.apply_edit(deck, target, None, {"status": "building"}, "2026-10-05")
        self.assertEqual(changes, {"decklist": True, "fields": ["status"]})
        self.assertEqual((deck.changed_on, deck.status, deck.target["Deck"][0].quantity), ("2026-10-05", "building", 3))
        # Header-only edits don't mark it.
        deck = read("casual/gruul-ramp")
        decks.apply_edit(deck, None, None, {"status": "built", "built_version": "owned"}, "2026-10-05")
        self.assertEqual((deck.changed_on, deck.get_field("Built version")), (None, "owned-only"))

    def test_sleeves_are_set_changed_and_removed(self):
        deck = read("casual/gruul-ramp")
        self.assertEqual(decks.apply_edit(deck, fields={"sleeves": None}), {"decklist": False, "fields": []})
        self.assertEqual(decks.apply_edit(deck, fields={"status": "built", "sleeves": "Red"}),
                         {"decklist": False, "fields": ["status", "sleeves"]})
        self.assertEqual((deck.get_field("Sleeves"), deck.changed_on), ("Red", None))
        # The same colour (spaces aside) is no change; another one is.
        self.assertEqual(decks.apply_edit(deck, fields={"sleeves": " Red "})["fields"], [])
        self.assertEqual(decks.apply_edit(deck, fields={"sleeves": "Blue"})["fields"], ["sleeves"])
        self.assertEqual(decks.apply_edit(deck, fields={"sleeves": None})["fields"], ["sleeves"])
        self.assertIsNone(deck.get_field("Sleeves"))
        with self.assertRaises(ValueError):
            decks.apply_edit(deck, fields={"sleeves": "Red\nGreen"})
        with self.assertRaises(ValueError):
            decks.apply_edit(deck, fields={"colour": "Red"})

    def test_deck_box_is_set_changed_and_removed(self):
        deck = read("casual/gruul-ramp")
        self.assertEqual(decks.apply_edit(deck, fields={"deck_box": None}), {"decklist": False, "fields": []})
        self.assertEqual(decks.apply_edit(deck, fields={"status": "built", "sleeves": "red", "deck_box": "Box"}),
                         {"decklist": False, "fields": ["status", "sleeves", "deck_box"]})
        self.assertEqual((deck.get_field("Deck box"), deck.changed_on), ("Box", None))
        self.assertEqual(decks.apply_edit(deck, fields={"deck_box": " Box "})["fields"], [])
        self.assertEqual(decks.apply_edit(deck, fields={"deck_box": "Other"})["fields"], ["deck_box"])
        self.assertEqual(decks.apply_edit(deck, fields={"deck_box": None})["fields"], ["deck_box"])
        self.assertEqual((deck.get_field("Deck box"), deck.get_field("Sleeves")), (None, "red"))
        with self.assertRaises(ValueError):
            decks.apply_edit(deck, fields={"deck_box": "Box\nGreen"})
        self.assertEqual(decks.EDIT_FIELDS["deck_box"], "Deck box")

    def test_fields_keep_their_extra_words(self):
        deck = read("casual/gruul-ramp")
        self.assertTrue(deck.get_field("Played by").startswith("either. Suits"))
        self.assertEqual(decks.apply_edit(deck, fields={"player": "either"}), {"decklist": False, "fields": []})
        decks.apply_edit(deck, fields={"player": "wife", "archetype": deck.get_field("Archetype") + " "})
        self.assertTrue(deck.get_field("Played by").startswith("wife. Suits"))
        self.assertEqual(decks.apply_edit(deck, fields={"archetype": "Big green"})["fields"], ["archetype"])
        self.assertEqual(deck.get_field("Archetype"), "Big green")

    def test_target_bracket(self):
        deck = read("commander/giada-angels")
        self.assertEqual(deck.get_field("Target bracket"), "2 (Core)")
        self.assertEqual(decks.apply_edit(deck, fields={"target_bracket": 2})["fields"], [])
        decks.apply_edit(deck, fields={"target_bracket": 3}, bracket_names={3: "Upgraded"})
        self.assertEqual(deck.get_field("Target bracket"), "3 (Upgraded)")
        decks.apply_edit(deck, fields={"target_bracket": None})
        self.assertIsNone(deck.get_field("Target bracket"))
        with self.assertRaises(ValueError):
            decks.set_target_bracket(deck, 6)
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), fields={"target_bracket": 2})

    def test_owned_only_version(self):
        deck = decks.parse_deck(new_deck_bytes(), "red-burn", "casual")
        self.assertIsNone(deck.owned)
        self.assertEqual(decks.apply_edit(deck, owned={})["decklist"], False)       # nothing to start
        self.assertEqual(decks.apply_edit(deck, owned=copy.deepcopy(deck.target), date="2026-10-05")["decklist"], True)
        self.assertIn("### Substitute version (owned and incoming cards)", decks.render_deck_file(deck))
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), owned={})

    def test_refused_edits(self):
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), {"Commander": [DeckLine(1, "Ghalta, Primal Hunger")]})
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), {"Maybeboard": [DeckLine(1, "Opt")]})
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), fields={"title": "New"})
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), fields={"archetype": "two\nlines"})
        with self.assertRaises(ValueError):
            decks.apply_edit(read("casual/gruul-ramp"), fields={"status": "done"})


class TableChangesTests(unittest.TestCase):

    def test_only_counts_and_labels_count(self):
        deck = read("casual/gruul-ramp")
        rows = [copy.copy(r) for r in deck.rows]
        for r in rows:
            r.aud_each, r.aud_missing, r.labels = "~$9.99", "~$9.99", None      # prices and notes: no change
        self.assertEqual(decks.table_changes(deck, rows), [])
        rows[0].owned, rows[0].missing = 2, 0
        rows[1].labels = ("2 on the way (order 2026-09-29-shop-b)",)
        extra = TableRow("Opt", 1, 1, 0, labels=())
        changes = decks.table_changes(deck, rows[:-1] + [extra])
        self.assertEqual([c["card"] for c in changes],
                         ["Cinder Glade", "Glorybringer", "Opt", deck.rows[-1].card])
        self.assertEqual(changes[0], {"card": "Cinder Glade",
                                      "was": {"need": 2, "owned": 0, "missing": 2, "labels": []},
                                      "now": {"need": 2, "owned": 2, "missing": 0, "labels": []}})
        self.assertEqual(changes[1]["now"]["labels"], ["2 on the way (order 2026-09-29-shop-b)"])
        self.assertEqual((changes[2]["was"], changes[3]["now"]), (None, None))
        no_table = decks.parse_deck(new_deck_bytes().replace(b"## Owned vs needed", b"## Other"),
                                    "red-burn", "casual")
        self.assertEqual(decks.table_changes(no_table, []), [])


if __name__ == "__main__":
    unittest.main()
