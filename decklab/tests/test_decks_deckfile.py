"""Tests for decklab.lib.decks.deckfile and .render (through decks): reading
deck files and writing them back, with the frozen fixtures and the real
files, the price stamp, broken files and new deck text. The fixtures and
helpers are in test_decks.py (see its docstring).

Run from the repo root:
    python -m unittest discover -s decklab/tests -t .
"""
import copy
import hashlib
import re
import time
import unittest
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.decks import DeckLine, PriceStamp, TableRow, TotalRow
from decklab.tests import pre_db
from decklab.tests.test_decks import (EXPECTED_DECKS, FIXTURE_DECKS, FIXTURE_FILES, FIXTURE_STAMP, FIXTURES,
                                      NEW_DECK_FIELDS, NEW_DECK_SECTIONS, OWNED_SPANS, add_to_rows, parse,
                                      prose, read, rerender)


class RealDeckFileTests(unittest.TestCase):
    """The real deck files, as the pre-db-decks tag holds them (pre_db: the
    last commit with them; the database holds the decks after the cutover),
    and the frozen fixtures: only what must always be true of them, so
    editing or adding decks never breaks these."""

    def setUp(self):
        installed = pre_db.decks_inventory()
        self.addCleanup(inventory.use(installed))
        real = sorted((d for d in installed.load().decks.values() if d.error is None), key=lambda d: d.id)
        self.assertTrue(real, "no real deck files at the pre-db-decks tag")
        # (label, the file's bytes, slug, kind, space)
        self.files = ([(d.id, d.text.encode("utf-8"), d.slug, d.kind, d.space) for d in real]
                      + [(str(p), p.read_bytes(), p.stem, p.parent.name, None) for p in FIXTURE_FILES])

    def test_round_trip_is_byte_identical(self):
        """PLAN.md: reading and writing each deck file unchanged gives the same bytes."""
        for label, data, slug, kind, space in self.files:
            with self.subTest(label):
                deck = decks.parse_deck(data, slug, kind, space=space)
                self.assertEqual(decks.render_deck_file(deck).encode("utf-8"), data)
                self.assertEqual(deck.sha256, hashlib.sha256(data).hexdigest())

    def test_every_deck_survives_a_full_edit(self):
        """What a save does: change both lists, Status, the table and its price
        stamp, and mark the change. Only the owned parts may change."""
        for label, data, slug, kind, space in self.files:
            with self.subTest(label):
                deck = decks.parse_deck(data, slug, kind, space=space)
                added = DeckLine(1, "Opt", "fdn", "512")
                if "target" in deck.spans:
                    if deck.target:
                        line = next(iter(deck.target.values()))[0]
                        line.quantity += 1
                        added = DeckLine(1, line.name)
                    else:
                        deck.target = {"Deck": [added]}
                if deck.owned:
                    next(iter(deck.owned.values()))[0].quantity += 1
                decks.set_status(deck, "building")
                if deck.rows is not None:
                    stamp = PriceStamp(9.5, "2026-10-04", "2026-10-05") if "prices" in deck.spans else None
                    decks.set_table(deck, add_to_rows(reversed(deck.rows), added), TotalRow(99, "~$1.00"), stamp)
                decks.mark_decklist_changed(deck, "2026-10-05")
                _, again = rerender(deck)
                self.assertEqual(prose(again), prose(deck))
                self.assertEqual(again.target, deck.target)
                self.assertEqual(again.owned, deck.owned)
                self.assertEqual(again.rows, deck.rows)
                self.assertEqual(again.prices, deck.prices)
                self.assertEqual((again.status, again.changed_on), ("building", "2026-10-05"))


class DeckFileTests(unittest.TestCase):
    """The frozen copies of the 11 deck files."""

    def test_all_eleven_deck_files_are_found(self):
        with mock.patch.object(decks, "DECKS_DIR", FIXTURE_DECKS), inventory.use(pre_db.following(FIXTURES)):
            found = {f"{p.parent.name}/{p.stem}" for p in decks.deck_files()}
        self.assertEqual(found, EXPECTED_DECKS)

    def test_fixtures_have_lf_line_endings(self):
        # If this fails, git converted them: see fixtures/.gitattributes.
        for path in FIXTURE_FILES:
            self.assertNotIn(b"\r\n", path.read_bytes(), path.name)

    def test_owned_parts_are_rebuilt_from_the_model(self):
        """Blank out every owned part of the original text (and the header
        lines' raw copies): the render must still be byte-identical, so the
        header lines, decklist blocks, table rows and price stamp all come
        from the formatters."""
        for path in FIXTURE_FILES:
            with self.subTest(path.name):
                data = path.read_bytes()
                deck = decks.read_deck_file(path)
                text = deck.text
                for key in OWNED_SPANS:
                    if key in deck.spans:
                        start, end = deck.spans[key]
                        text = text[:start] + "\x00" * (end - start) + text[end:]
                self.assertNotEqual(text, deck.text)
                deck.text = text
                for f in deck.header:
                    f.raw = None
                self.assertEqual(decks.render_deck_file(deck).encode("utf-8"), data)

    def test_every_part_is_found(self):
        for path in FIXTURE_FILES:
            with self.subTest(path.name):
                deck = decks.read_deck_file(path)
                self.assertEqual(sorted(deck.spans), ["header", "owned", "prices", "table", "target"])
                self.assertEqual(deck.kind, path.parent.name)
                self.assertEqual(deck.slug, path.stem)
                self.assertEqual(deck.player, "either")
                self.assertEqual(deck.status, "idea")
                self.assertIsNone(deck.built_version)
                self.assertIsNone(deck.changed_on)
                self.assertEqual(deck.prices, FIXTURE_STAMP)
                size = 100 if deck.kind == "commander" else 60
                self.assertEqual(decks.card_count(deck.target), size)
                self.assertEqual(decks.card_count(deck.owned), size)
                if deck.kind == "commander":
                    self.assertEqual(deck.format, "Commander (100 cards)")
                    self.assertEqual(deck.target_bracket, 2)
                    self.assertEqual(decks.card_count(deck.target, ("Commander",)), 1)
                else:
                    self.assertEqual(deck.format, "Casual 60-card, 1v1")
                    self.assertIsNone(deck.target_bracket)
                self.assertTrue(deck.rows)
                self.assertEqual(deck.total.label, "Total to buy")

    def test_header_fields(self):
        deck = read("casual/gruul-ramp")
        self.assertEqual(deck.title, "Gruul Ramp")
        self.assertEqual([k for k, _ in deck.fields],
                         ["Format", "Archetype", "Played by", "Status", "Paired against",
                          "Complexity", "Estimated power", "Configuration"])
        self.assertEqual(deck.get_field("paired against"), "[Izzet Prowess](izzet-prowess.md)")
        self.assertTrue(deck.get_field("Played by").startswith("either. Suits whoever"))
        self.assertTrue(read("casual/mono-black-midrange").get_field("Played by").startswith("either — suits"))
        self.assertEqual(read("commander/gisa-zombies").get_field("Target bracket"), "2 (Core)")
        # The formatter reproduces every header line in every file.
        for path in FIXTURE_FILES:
            for f in decks.read_deck_file(path).header:
                self.assertEqual(decks.format_field(f.key, f.value), f.raw)

    def test_player_and_status_ignore_case(self):
        deck = parse("# T\n\n- **Played by:** Either, whoever\n- **Status:** Built (target list)\n"
                     "- **Built version:** Owned-only\n")
        self.assertEqual((deck.player, deck.status, deck.built_version), ("either", "built", "owned"))
        deck = parse("# T\n\n- **Played by:** nobody\n- **Status:** done\n- **Built version:** both\n")
        self.assertEqual((deck.player, deck.status, deck.built_version), (None, None, None))

    def test_decklists(self):
        deck = read("casual/gruul-ramp")
        self.assertEqual(deck.target["Deck"][0], DeckLine(4, "Llanowar Elves", "fdn", "227"))
        self.assertEqual(deck.target["Deck"][-1], DeckLine(7, "Mountain"))
        self.assertIn(DeckLine(1, "Pelakka Wurm", "fdn", "720", "foil"), deck.target["Deck"])
        self.assertEqual(decks.card_count(deck.target, ("Sideboard",)), 6)
        self.assertIn(DeckLine(1, "Tajuru Pathwarden", "fdn", "558"), deck.owned["Deck"])
        midrange = read("casual/mono-black-midrange")
        self.assertIn(DeckLine(2, "Murderous Rider // Swift End", "plst", "ELD-97"), midrange.target["Deck"])
        # The same printing on two lines stays as two lines.
        throats = [l for l in midrange.target["Deck"] if l.name == "Go for the Throat"]
        self.assertEqual([l.quantity for l in throats], [2, 1])
        gisa = read("commander/gisa-zombies")
        self.assertEqual(gisa.target["Commander"], [DeckLine(1, "Ghoulcaller Gisa", "fdc", "6", "foil")])

    def test_table(self):
        deck = read("casual/gruul-ramp")
        self.assertEqual(deck.rows[0], TableRow("Cinder Glade", 2, 0, 2, "~$0.40", "~$0.80", "  "))
        self.assertEqual(deck.rows[4], TableRow("Aggressive Mammoth", 1, 1, 0, "", "", "  "))
        chaos = next(r for r in deck.rows if r.card == "Chaos Warp")
        self.assertEqual(chaos.notes_cell, " ")
        self.assertEqual(deck.total, TotalRow(8, "~$3.32", "Total to buy", " "))
        precon = next(r for r in read("casual/mono-black-zombies").rows if r.card == "Castle Locthwain")
        self.assertEqual(precon.notes, "on the way (Wretched Ranks precon)")

    def test_row_order_matches_sort_table_rows(self):
        """Every file lists the cards with something missing first, then the
        rest, each group in plain string order ("Angel of Vitality" before
        "Angel of the Ruins")."""
        for path in FIXTURE_FILES:
            with self.subTest(path.name):
                rows = decks.read_deck_file(path).rows
                self.assertEqual(decks.sort_table_rows(rows), rows)
        angels = [r.card for r in read("casual/mono-white-angels").rows]
        self.assertLess(angels.index("Angel of Vitality"), angels.index("Angel of the Ruins"))

    def test_crlf_file_round_trips_and_edits_keep_crlf(self):
        lf = (FIXTURE_DECKS / "casual" / "gruul-ramp.md").read_bytes().replace(b"\r\n", b"\n")
        data = lf.replace(b"\n", b"\r\n")
        deck = decks.parse_deck(data, "gruul-ramp", "casual")
        self.assertEqual(deck.newline, "\r\n")
        self.assertEqual(decks.render_deck_file(deck).encode("utf-8"), data)
        decks.set_status(deck, "built")
        deck.target["Deck"][0].quantity = 3
        rows = add_to_rows(deck.rows, DeckLine(-1, "Llanowar Elves"))
        decks.set_table(deck, rows[1:] + rows[:1], deck.total, PriceStamp(1.5, "2026-10-01", "2026-10-01"))
        decks.mark_decklist_changed(deck, "2026-10-05")
        out = decks.render_deck_file(deck).encode("utf-8")
        self.assertEqual(out.count(b"\n"), out.count(b"\r\n"))
        self.assertIn(b"- **Status:** built\r\n", out)
        self.assertIn(b"\r\n3 Llanowar Elves (FDN) 227\r\n", out)

    def test_bom_is_kept(self):
        data = b"\xef\xbb\xbf" + (FIXTURE_DECKS / "casual" / "izzet-prowess.md").read_bytes()
        deck = decks.parse_deck(data, "izzet-prowess", "casual")
        self.assertEqual(deck.title, "Izzet Prowess")
        self.assertEqual(decks.render_deck_file(deck).encode("utf-8"), data)


class HandEditedFixtureTests(unittest.TestCase):

    def setUp(self):
        self.path = FIXTURES / "hand-edited-deck.md"
        self.data = self.path.read_bytes()
        self.deck = decks.read_deck_file(self.path, kind="casual")

    def test_round_trip(self):
        self.assertEqual(decks.render_deck_file(self.deck).encode("utf-8"), self.data)

    def test_parsed_variations(self):
        deck = self.deck
        self.assertEqual(deck.player, "wife")
        self.assertEqual(deck.status, "building")
        self.assertIsNone(deck.owned)
        self.assertIsNone(deck.prices)
        self.assertEqual(list(deck.target), ["Companion", "Deck", "Sideboard"])
        self.assertIn(DeckLine(2, "Borborygmos and Fblthp", "war", "1", "etched"), deck.target["Deck"])
        self.assertIn(DeckLine(1, "Grim Lavamancer", "sld", None), deck.target["Deck"])
        self.assertIn(DeckLine(1, "Marit Lage's Slumber", "mh2", "55★"), deck.target["Deck"])
        self.assertEqual(deck.target["Sideboard"], [DeckLine(1, "Erase (Not the Urza's Legacy One)")])
        self.assertEqual(deck.rows[0].notes, r"any printing \| cheapest first")

    def test_non_owned_header_line_is_kept_verbatim(self):
        decks.set_status(self.deck, "built")
        text = decks.render_deck_file(self.deck)
        self.assertIn("- **Budget:**none, written by hand without the space", text)
        self.assertIn("- **Status:** built (waiting on 3 Lightning Bolt)", text)

    def test_notes_with_a_pipe_survive_new_rows(self):
        rows = [TableRow("Lightning Bolt", 4, 4, 0), TableRow("Fire // Ice", 1, 1, 0)]
        rows += [TableRow(r.card, r.need, r.owned, r.missing) for r in self.deck.rows
                 if r.card not in ("Lightning Bolt", "Fire // Ice")]
        decks.set_table(self.deck, rows, TotalRow(0))
        _, again = rerender(self.deck)
        self.assertEqual(again.rows[0].notes_cell, r" any printing \| cheapest first ")
        self.assertEqual(again.rows[1].notes_cell, " ")
        self.assertEqual(again.total.missing, 0)

    def test_a_price_note_is_added_above_a_table_without_one(self):
        decks.set_table(self.deck, self.deck.rows, self.deck.total, PriceStamp(2.0, "2026-09-28", "2026-09-29"))
        text, again = rerender(self.deck)
        self.assertEqual(text, self.data.decode("utf-8").replace(
            "## Owned vs needed\n\n| Card |",
            "## Owned vs needed\n\nPrices are **estimates in AUD**: Scryfall's cheapest paper non-foil "
            "printing (USD), converted at 1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-29."
            "\n\n| Card |"))
        self.assertEqual(again.prices, PriceStamp(2.0, "2026-09-28", "2026-09-29"))
        self.assertEqual(decks.render_deck_file(again), text)

    def test_adding_an_owned_only_version(self):
        owned = copy.deepcopy(self.deck.target)
        owned["Deck"][0].quantity = 1
        self.deck.owned = owned
        text, again = rerender(self.deck)
        nl = self.deck.newline
        self.assertIn(f"None yet.{nl}{nl}### Substitute version (owned and incoming cards){nl}{nl}```{nl}Companion{nl}", text)
        self.assertIn(f"1 Erase (Not the Urza's Legacy One){nl}```{nl}{nl}## Notes{nl}", text)
        self.assertEqual(again.owned, owned)
        # The only new prose is the heading and fence lines around the list.
        added = f"### Substitute version (owned and incoming cards){nl}{nl}```{nl}```{nl}{nl}"
        self.assertEqual(prose(again).replace(added, "", 1), prose(self.deck))
        self.assertEqual(decks.render_deck_file(again), text)


class MarkerTests(unittest.TestCase):

    def test_mark_adds_the_line_below_the_header(self):
        deck = read("casual/gruul-ramp")
        original = deck.text
        decks.mark_decklist_changed(deck, "2026-10-05")
        text, again = rerender(deck)
        marker = "*Decklist changed in Deck Lab on 2026-10-05; prose sections may be out of date.*"
        self.assertEqual(text, original.replace("(6 shared cards; see Shared-pool conflicts).\n\n",
                                                f"(6 shared cards; see Shared-pool conflicts).\n\n{marker}\n\n", 1))
        self.assertEqual(again.changed_on, "2026-10-05")
        self.assertEqual(decks.render_deck_file(again), text)            # round trip with the line
        self.assertEqual(prose(again), prose(deck))

        decks.mark_decklist_changed(again, "2026-11-01")               # updating replaces it
        self.assertEqual(decks.render_deck_file(again), text.replace("2026-10-05", "2026-11-01"))
        again.changed_on = None                                          # and it can be taken out
        self.assertEqual(decks.render_deck_file(again), original)

    def test_mark_a_file_whose_header_is_added_in_the_same_edit(self):
        deck = parse("# Bare\n\n## Decklist\n\n```\nDeck\n4 Opt\n```\n")
        decks.mark_decklist_changed(deck, "2026-10-05")
        with self.assertRaises(decks.DeckFileError):            # nothing to put it under
            decks.render_deck_file(deck)
        decks.set_status(deck, "idea")
        text, again = rerender(deck)
        self.assertEqual(text, "# Bare\n\n- **Status:** idea\n\n*Decklist changed in Deck Lab on 2026-10-05; "
                               "prose sections may be out of date.*\n\n## Decklist\n\n```\nDeck\n4 Opt\n```\n")
        self.assertEqual((again.status, again.changed_on), ("idea", "2026-10-05"))
        self.assertEqual(decks.render_deck_file(again), text)

    MARK = "*Decklist changed in Deck Lab on {}; prose sections may be out of date.*"

    def test_a_marker_in_another_layout_is_found_and_replaced(self):
        # It used to be found only after exactly one blank line, so a new
        # date added a second line above it.
        for layout in ("# T\n\n- **Status:** idea\n{m}\n\nProse.\n",            # no blank line
                       "# T\n\n- **Status:** idea\n\n\n{m}\n\nProse.\n",        # two
                       "# T\n\n- **Status:** idea\n\n{m}\n\n{m}\n\nProse.\n"):  # two markers (older bug)
            with self.subTest(layout):
                text = layout.format(m=self.MARK.format("2026-09-20"))
                deck = parse(text)
                self.assertEqual(deck.changed_on, "2026-09-20")
                self.assertEqual(decks.render_deck_file(deck), text)             # kept as it was
                decks.mark_decklist_changed(deck, "2026-09-30")
                out = decks.render_deck_file(deck)
                self.assertEqual(out, "# T\n\n- **Status:** idea\n\n" + self.MARK.format("2026-09-30") + "\n\nProse.\n")
                self.assertEqual(parse(out).changed_on, "2026-09-30")

    def test_a_new_marker_above_prose_right_under_the_header(self):
        deck = parse("# T\n\n- **Status:** idea\nSome prose.\n")
        decks.mark_decklist_changed(deck, "2026-09-30")
        out = decks.render_deck_file(deck)
        self.assertEqual(out, "# T\n\n- **Status:** idea\n\n" + self.MARK.format("2026-09-30") + "\n\nSome prose.\n")
        again = parse(out)
        decks.mark_decklist_changed(again, "2026-10-01")
        self.assertEqual(decks.render_deck_file(again), out.replace("2026-09-30", "2026-10-01"))

    def test_bad_date(self):
        deck = read("casual/gruul-ramp")
        for bad in ("5 Oct 2026", "2026-10-5", ""):
            with self.assertRaises(ValueError):
                decks.mark_decklist_changed(deck, bad)


class NewDeckTests(unittest.TestCase):

    FIELDS = NEW_DECK_FIELDS
    SECTIONS = NEW_DECK_SECTIONS

    def test_template(self):
        text = decks.new_deck_text("Red Burn", "casual", self.FIELDS, self.SECTIONS)
        self.assertEqual(text, (
            "# Red Burn\n\n"
            "- **Format:** Casual 60-card, 1v1\n- **Archetype:** Mono-red burn\n"
            "- **Played by:** wife\n- **Status:** idea\n\n"
            "## Decklist\n\n```\nDeck\n4 Lightning Bolt (FDC) 163\n20 Mountain\n\n"
            "Sideboard\n2 Negate (FDN) 710 *F*\n```\n\n"
            "## Owned vs needed\n\n"
            "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
            "|---|---|---|---|---|---|---|\n\n"
            "## Substitutes\n\n## Notes\n"))
        deck = decks.parse_deck(text.encode("utf-8"), "red-burn", "casual")
        self.assertEqual(deck.fields, self.FIELDS)
        self.assertEqual(deck.target, self.SECTIONS)
        self.assertEqual((deck.rows, deck.total, deck.owned, deck.prices), ([], None, None, None))
        self.assertEqual(decks.render_deck_file(deck), text)

        # pool.py fills the table later; the owned-only list goes under Substitutes.
        decks.set_table(deck, [TableRow("Lightning Bolt", 4, 1, 3, "~$1.20", "~$3.60"),
                               TableRow("Negate", 2, 2, 0)], TotalRow(3, "~$3.60"))
        deck.owned = {"Deck": [DeckLine(1, "Lightning Bolt", "fdc", "163"), DeckLine(23, "Mountain")]}
        text2, again = rerender(deck)
        self.assertIn("|---|---|---|---|---|---|---|\n"
                      "| Lightning Bolt | 4 | 1 | **3** | ~$1.20 | ~$3.60 |  |\n"
                      "| Negate | 2 | 2 | 0 | | |  |\n"
                      "| **Total to buy** | | | **3** | | **~$3.60** | |\n\n## Substitutes\n\n"
                      "### Substitute version (owned and incoming cards)\n\n```\nDeck\n1 Lightning Bolt (FDC) 163\n23 Mountain\n```\n\n"
                      "## Notes\n", text2)
        self.assertEqual(again.owned, deck.owned)
        self.assertEqual(decks.render_deck_file(again), text2)

    def test_commander_template_with_table(self):
        sections = {"Commander": [DeckLine(1, "Ghoulcaller Gisa", "fdc", "6", "foil")],
                    "Deck": [DeckLine(99, "Swamp")]}
        fields = [("Format", "Commander (100 cards)"), ("Played by", "either"),
                  ("Status", "idea"), ("Target bracket", "2 (Core)")]
        rows = [TableRow("Ghoulcaller Gisa", 1, 1, 0)]
        text = decks.new_deck_text("Gisa Test", "commander", fields, sections, rows, TotalRow(0),
                                   price_note="Prices are estimates.", newline="\r\n")
        self.assertNotIn("\n", text.replace("\r\n", ""))
        deck = decks.parse_deck(text.encode("utf-8"), "gisa-test", "commander")
        self.assertEqual((deck.target_bracket, deck.target, deck.rows[0].card, deck.total.missing),
                         (2, sections, "Ghoulcaller Gisa", 0))
        self.assertIn("## Owned vs needed\r\n\r\nPrices are estimates.\r\n\r\n| Card |", text)
        self.assertEqual(decks.render_deck_file(deck), text)

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            decks.new_deck_text("X", "modern", [], {})
        with self.assertRaises(ValueError):
            decks.new_deck_text("Two\nlines", "casual", [], {})


class BrokenFileTests(unittest.TestCase):

    def test_errors(self):
        good = (FIXTURES / "hand-edited-deck.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        cases = {
            "no title": good.replace("# Hand-Edited Fixture\n", "Hand-Edited Fixture\n"),
            "bad decklist line": good.replace("4 Lightning Bolt (2X2) 117", "four Lightning Bolt"),
            "unclosed block": good.split("## Owned vs needed")[0].replace("```\n\n", "\n\n"),
            "bad number": good.replace("| Lightning Bolt | 4 |", "| Lightning Bolt | four |"),
            "short row": good.replace("| Fire // Ice | 1 | 1 | 0 | | | |", "| Fire // Ice | 1 | 1 | 0 |"),
            "two totals": good.replace("| **Total to buy** | | | **3** | | **~$3.60** | |",
                                       "| **Total to buy** | | | **3** | | | |\n| **Total** | | | **3** | | | |"),
            "row after total": good.replace("| **Total to buy** | | | **3** | | **~$3.60** | |",
                                            "| **Total to buy** | | | **3** | | | |\n| Opt | 1 | 1 | 0 | | | |"),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(decks.DeckFileError):
                parse(text)
        with self.assertRaises(decks.DeckFileError):
            decks.parse_deck(b"# T\n\xff\n", "broken", "casual")
        with self.assertRaises(decks.DeckFileError):
            decks.parse_deck(b"# T\n", "broken", "modern")

    def test_missing_parts(self):
        deck = parse("# Bare\n\n- **Status:** idea\n\nJust prose.\n")
        self.assertEqual((deck.target, deck.owned, deck.rows, deck.total), ({}, None, None, None))
        self.assertEqual(decks.render_deck_file(deck), "# Bare\n\n- **Status:** idea\n\nJust prose.\n")
        deck.rows = [TableRow("Opt", 1, 1, 0)]
        with self.assertRaises(decks.DeckFileError):
            decks.render_deck_file(deck)
        deck.rows, deck.target = None, {"Deck": [DeckLine(1, "Opt")]}
        with self.assertRaises(decks.DeckFileError):
            decks.render_deck_file(deck)

    def test_decklist_section_without_its_own_block(self):
        # The owned-only list under it isn't the target...
        text = ("# T\n\n- **Status:** idea\n\n## Decklist\n\nSee below.\n\n"
                "### Owned-only version\n\n```\nDeck\n4 Opt\n```\n")
        deck = parse(text)
        self.assertEqual((deck.target, deck.owned), ({}, {"Deck": [DeckLine(4, "Opt")]}))
        self.assertNotIn("target", deck.spans)
        self.assertEqual(decks.render_deck_file(deck), text)
        # ...and neither is a block in the next section.
        deck = parse("# T\n\n## Decklist\n\nNone yet.\n\n## Notes\n\n```\nDeck\n4 Opt\n```\n")
        self.assertEqual(deck.target, {})
        self.assertNotIn("target", deck.spans)

    def test_headings_inside_fenced_blocks_are_ignored(self):
        text = ("# T\n\nAn example of the layout:\n\n```\n## Decklist\n```\n\n"
                "## Decklist\n\n```\nDeck\n4 Opt\n```\n")
        deck = parse(text)
        self.assertEqual(deck.target, {"Deck": [DeckLine(4, "Opt")]})
        self.assertEqual(decks.render_deck_file(deck), text)

    def test_the_title_is_never_the_owned_only_heading(self):
        # "# Owned-only version of Elves" used to hide the real
        # "### Owned-only version", so every save added another one.
        text = decks.new_deck_text("Owned-only version of Elves", "casual", [("Status", "idea")],
                                   {"Deck": [DeckLine(4, "Llanowar Elves"), DeckLine(20, "Forest")]})
        deck = parse(text)
        self.assertIsNone(deck.owned)
        owned = {"Deck": [DeckLine(3, "Llanowar Elves", "fdn", "227"), DeckLine(20, "Forest")]}
        decks.apply_edit(deck, owned=copy.deepcopy(owned), date="2026-09-30")
        text2, again = rerender(deck)
        self.assertEqual(again.owned, owned)
        decks.apply_edit(again, owned=copy.deepcopy(owned), date="2026-10-01")
        self.assertEqual(decks.render_deck_file(again).count("### Substitute version"), 1)

    def test_header_is_added_to_a_file_without_one(self):
        deck = parse("# Bare\n\nJust prose.\n")
        decks.set_status(deck, "idea")
        self.assertEqual(decks.render_deck_file(deck), "# Bare\n\n- **Status:** idea\n\nJust prose.\n")

    def test_header_is_added_to_a_title_with_no_final_newline(self):
        deck = decks.parse_deck(b"# Title only", "t", "casual")
        decks.set_status(deck, "idea")
        text, again = rerender(deck)
        self.assertEqual(text, "# Title only\n\n- **Status:** idea\n")
        self.assertEqual((again.title, again.status), ("Title only", "idea"))

    def test_owned_field_lines_are_kept_until_changed(self):
        text = "# T\n\n- **Status:**idea\n- **Complexity:**2/5\n\nProse.\n"
        deck = parse(text)
        self.assertEqual(deck.status, "idea")
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_status(deck, "built")
        self.assertEqual(decks.render_deck_file(deck), "# T\n\n- **Status:** built\n- **Complexity:**2/5\n\nProse.\n")

    def test_a_colon_outside_the_bold_still_reads_as_a_field(self):
        # "- **Built version**: target" used to end the header, dropping every field after it.
        text = "# T\n\n- **Played by:** wife\n- **Built version**: `target`\n- **Status:** built\n\nProse.\n"
        deck = parse(text)
        self.assertEqual([k for k, _ in deck.fields], ["Played by", "Built version", "Status"])
        self.assertEqual((deck.status, deck.built_version), ("built", "target"))
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_status(deck, "idea")
        self.assertEqual(decks.render_deck_file(deck), text.replace("built\n\n", "idea\n\n"))
        decks.set_built_version(deck, "owned")
        self.assertIn("- **Built version:** owned-only\n", decks.render_deck_file(deck))

    def test_a_sleeves_line_is_read_and_kept(self):
        text = "# T\n\n- **Status:** built\n- **Sleeves:**  Matte  black \n- **Complexity:** 2/5\n\nProse.\n"
        deck = parse(text)
        self.assertEqual([k for k, _ in deck.fields], ["Status", "Sleeves", "Complexity"])
        self.assertEqual(deck.sleeves, "Matte  black")
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_sleeves(deck, "Matte  black")             # the same colour: the line stays as written
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_sleeves(deck, "Red")
        self.assertEqual(decks.render_deck_file(deck), text.replace("**Sleeves:**  Matte  black ", "**Sleeves:** Red"))
        self.assertIsNone(parse("# T\n\n- **Status:** built\n- **Sleeves:**\n").sleeves)

    def test_a_deck_box_line_is_read_and_kept(self):
        text = "# T\n\n- **Status:** built\n- **Sleeves:** red\n- **Deck box:**  Boulder  \n\nProse.\n"
        deck = parse(text)
        self.assertEqual([k for k, _ in deck.fields], ["Status", "Sleeves", "Deck box"])
        self.assertEqual(deck.deck_box, "Boulder")
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_deck_box(deck, "Boulder")                # the same value: the line stays as written
        self.assertEqual(decks.render_deck_file(deck), text)
        self.assertIsNone(parse("# T\n\n- **Status:** built\n- **Deck box:**\n").deck_box)
        self.assertEqual(decks.OWNED_FIELDS[-2:], ("Sleeves", "Deck box"))

    def test_backticks_around_a_value_are_ignored(self):
        deck = parse("# T\n\n- **Status:** `built`\n- **Built version:** `owned-only`\n")
        self.assertEqual((deck.status, deck.built_version), ("built", "owned"))
        decks.set_status(deck, "idea")
        self.assertIn("- **Status:** `idea`\n", decks.render_deck_file(deck))


class PriceStampTests(unittest.TestCase):
    """The stamp above the table: written only in a form the next read finds."""

    def test_a_stamp_that_would_not_read_back_is_refused(self):
        self.assertEqual(PriceStamp(1.4237, "2026-09-28", "2026-09-29").text(),
                         "1 USD = 1.4237 AUD (ECB rate of 2026-09-28), pulled 2026-09-29")
        for bad in (PriceStamp(1.4237, "2026-09-28", "unknown"), PriceStamp(1.4237, "", "2026-09-28"),
                    PriceStamp(1.4237, "2026-09-28", None), PriceStamp(0, "2026-09-28", "2026-09-28"),
                    PriceStamp(1e-05, "2026-09-28", "2026-09-28"), PriceStamp(float("nan"), "2026-09-28", "2026-09-28")):
            with self.subTest(bad), self.assertRaises(ValueError):
                bad.text()

    def test_a_bad_stamp_never_reaches_the_file(self):
        # It used to write "pulled unknown", which the next read didn't find,
        # so every later save added another rate paragraph.
        deck = read("casual/gruul-ramp")
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.4237, "2026-09-28", "unknown"))
        with self.assertRaises(ValueError):
            decks.render_deck_file(deck)
        deck = read("casual/gruul-ramp")
        for _ in range(3):
            decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.4237, "2026-09-28", "2026-09-29"))
            text, deck = rerender(deck)
        self.assertEqual(text.count("Prices are **estimates in AUD**"), 1)
        self.assertEqual(deck.prices, PriceStamp(1.4237, "2026-09-28", "2026-09-29"))

    def test_a_rate_in_other_words_is_never_contradicted(self):
        # Adding PRICE_NOTE under it would leave two rates above the table.
        original = read("casual/izzet-prowess").text.replace(
            "(ECB rate of 2026-09-25), pulled 2026-09-28.", "(rate dated 2026-09-25), pulled 2026-09-28.", 1)
        for wording in (original, original.replace("1 USD = 1.4224 AUD", "USD→AUD 1.4224", 1)):
            deck = decks.parse_deck(wording.encode(), "izzet-prowess", "casual")
            self.assertEqual((deck.prices, "prices" in deck.spans, "prices_insert" in deck.spans), (None, False, False))
            self.assertEqual(decks.render_deck_file(deck), wording)
            decks.set_table(deck, deck.rows, deck.total)               # no new prices: fine
            decks.set_status(deck, "building")
            self.assertEqual(decks.render_deck_file(deck), wording.replace("**Status:** idea", "**Status:** building"))
            decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.5012, "2026-10-04", "2026-10-05"))
            with self.assertRaisesRegex(decks.DeckFileError, "reword it as"):
                decks.render_deck_file(deck)

    STAMPED = "converted at 1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28."
    PARAGRAPH = re.compile(r"^Prices are \*\*estimates in AUD\*\*.*$", re.MULTILINE)

    def blocked(self, text, found, where):
        """text's table can't be repriced, other_rate() quotes found, and
        nothing changes until new prices would."""
        deck = decks.parse_deck(text.encode(), "izzet-prowess", "casual")
        self.assertIn("prices_other", deck.spans)
        self.assertNotIn("prices_insert", deck.spans)
        other = decks.other_rate(deck)
        self.assertEqual((other["found"], other["where"]), (found, where))
        self.assertEqual(other["stamp"], None if where == "alone" else FIXTURE_STAMP.text())
        self.assertEqual(decks.render_deck_file(deck), text)
        decks.set_status(deck, "building")                         # no new prices: fine
        decks.set_table(deck, deck.rows, deck.total)
        self.assertEqual(decks.render_deck_file(deck), text.replace("**Status:** idea", "**Status:** building", 1))
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.4277, "2026-09-29", "2026-09-30"))
        fix = "reword it as" if where == "alone" else "take it out, leaving only the stamp"
        with self.assertRaisesRegex(decks.DeckFileError, rf"exchange rate in other words \({re.escape(repr(found))}, "
                                                         rf"in the paragraph that starts ['\"].+['\"]\).*{fix}"):
            decks.render_deck_file(deck)
        return other

    def test_every_other_wording_blocks_repricing(self):
        # Findings 0 and 28: a rate in any other wording used to get a second
        # PRICE_NOTE paragraph with the new rate under it.
        original = read("casual/izzet-prowess").text
        self.assertIn(self.STAMPED, original)
        for wording, found in (
                ("converted at USD 1 = AUD 1.4224 (ECB, 2026-09-25), pulled 2026-09-28.",
                 "converted at USD 1 = AUD 1.4224"),
                ("converted at 1.4224 AUD per USD (ECB rate of 2026-09-25), pulled 2026-09-28.",
                 "converted at 1.4224 AUD per USD"),
                ("converted at 1 USD ≈ 1.42 AUD (ECB 2026-09-25).", "converted at 1 USD ≈ 1.42 AUD"),
                ("converted at US$1 = A$1.42 (ECB 2026-09-25).", "converted at US$1 = A$1.42"),
                ("converted at 1 US dollar = 1.4224 Australian dollars.",
                 "converted at 1 US dollar = 1.4224 Australian dollars"),
                ("converted at an exchange rate of 1.4224.", "at an exchange rate of 1.4224"),
                ("converted at a rate of 1.4224 (2026-09-25).", "converted at a rate of 1.4224"),
                ("converted at 1 USD = A$1.4224 (ECB rate of 2026-09-25).", "converted at 1 USD = A$1.4224"),
                ("converted at 1 USD = 1.4224 AUD (rate dated 2026-09-25), pulled 2026-09-28.",
                 "converted at 1 USD = 1.4224 AUD"),
                ("converted at USD→AUD 1.4224.", "converted at USD→AUD 1.4224"),
                ("converted at 1 EUR = 1.6512 AUD (ECB, 2026-09-25).", "converted at 1 EUR = 1.6512 AUD")):
            with self.subTest(wording):
                self.blocked(original.replace(self.STAMPED, wording, 1), found, "alone")

    def test_a_whole_paragraph_in_other_words_blocks_repricing(self):
        # The recheck's wordings: EUR prices, AUD alone, no currency at all,
        # a multiplication, lower-case symbols, and a rate named by its date.
        original = read("casual/izzet-prowess").text
        for paragraph, found, starts in (
                ("Prices are **estimates in AUD**: Scryfall's cheapest paper non-foil printing (EUR), converted at "
                 "1 EUR = 1.6512 AUD (ECB, 2026-09-25).", "converted at 1 EUR = 1.6512 AUD",
                 "Prices are estimates in AUD: Scryfall's cheapest paper..."),
                ("Prices are **estimates in AUD**, converted from Scryfall at 1.4224 (ECB, 2026-09-25).",
                 "from Scryfall at 1.4224", "Prices are estimates in AUD, converted from Scryfall at..."),
                ("Prices are estimates from Scryfall, converted at 1.4224 (ECB, 2026-09-25).",
                 "converted at 1.4224", "Prices are estimates from Scryfall, converted at 1.4224..."),
                ("Prices are estimates: Scryfall price × 1.4224.", "Scryfall price × 1.4224",
                 "Prices are estimates: Scryfall price × 1.4224."),
                ("Prices are estimates: Scryfall price * 1.4224.", "Scryfall price * 1.4224",
                 "Prices are estimates: Scryfall price * 1.4224."),
                ("Prices are Scryfall's times a multiplier of 1.4224 (ECB).", "Scryfall's times a multiplier of 1.4224",
                 "Prices are Scryfall's times a multiplier of 1.4224 (ECB)."),
                ("Prices: us$1 = a$1.42.", "us$1 = a$1.42", "Prices: us$1 = a$1.42."),
                ("Prices use the ECB rate of 2026-09-25.", "use the ECB rate of 2026-09-25",
                 "Prices use the ECB rate of 2026-09-25.")):
            with self.subTest(paragraph):
                text = self.PARAGRAPH.sub(lambda m: paragraph, original, 1)
                self.assertNotEqual(text, original)
                self.assertEqual(self.blocked(text, found, "alone")["paragraph"], starts)

    def test_a_second_rate_beside_the_stamp_or_in_another_paragraph_blocks_it_too(self):
        original = read("casual/izzet-prowess").text
        for extra, found, where in (
                (" Earlier prices used USD 1 = AUD 1.40.", "Earlier prices used USD 1 = AUD 1.40", "beside_stamp"),
                (" Last month the rate was 1.41.", "Last month the rate was 1.41", "beside_stamp"),
                (" Earlier it was at a rate of 1.41.", "was at a rate of 1.41", "beside_stamp"),
                (" " + self.STAMPED.replace("1.4224", "1.4100"), "converted at 1 USD = 1.4100 AUD", "beside_stamp"),
                ("\n\nThe buylist used 1.39 AUD per USD.", "The buylist used 1.39 AUD per USD", "other_paragraph"),
                ("\n\nOlder notes: 1 USD = 1.41 AUD.", "1 USD = 1.41 AUD", "other_paragraph")):
            with self.subTest(extra):
                text = original.replace(self.STAMPED, self.STAMPED + extra, 1)
                deck = decks.parse_deck(text.encode(), "izzet-prowess", "casual")
                self.assertEqual(deck.prices, FIXTURE_STAMP)
                decks.set_table(deck, deck.rows, deck.total, FIXTURE_STAMP)           # the same stamp: fine
                self.assertEqual(decks.render_deck_file(deck), text)
                self.blocked(text, found, where)
        # A rate in a paragraph before the stamp's.
        text = original.replace("Prices are **estimates in AUD**",
                                "Rate: 1 USD = 1.41 AUD.\n\nPrices are **estimates in AUD**", 1)
        self.assertEqual(self.blocked(text, "1 USD = 1.41 AUD", "other_paragraph")["paragraph"],
                         "Rate: 1 USD = 1.41 AUD.")

    def test_amounts_and_currency_names_are_not_rates(self):
        # A later check blocked repricing for these, and the note blamed a
        # stamp that was already in the right form.
        original = read("casual/izzet-prowess").text
        for extra in (" The missing cards come to about A$45.", " Missing cards: 45 AUD.",
                      " Cards under 1 USD are not listed.", " Missing cards: A$45.50, or 45.50 AUD.",
                      " The cheapest missing card is ~$0.40.", " Cards from 1 USD to 5 USD are listed.",
                      " Missing cards come to **45.50 AUD** (**A$45.50**).",
                      " Retail is often 12.50% higher.", " Checked 25.09.2026.",
                      "\n\nScryfall lists prices in USD; this table shows AUD.",
                      "\n\nPrices in USD are Scryfall's; AUD ones are estimates.",
                      "\n\nAll prices are in Australian dollars, from US dollar prices.",
                      "\n\nScryfall's USD prices are converted from USD to AUD at the ECB rate."):
            with self.subTest(extra):
                text = original.replace(self.STAMPED, self.STAMPED + extra, 1)
                deck = decks.parse_deck(text.encode(), "izzet-prowess", "casual")
                self.assertEqual((deck.prices, "prices_other" in deck.spans, decks.other_rate(deck)),
                                 (FIXTURE_STAMP, False, None))
                decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.4277, "2026-09-29", "2026-09-30"))
                self.assertEqual(decks.render_deck_file(deck),
                                 text.replace("1 USD = 1.4224 AUD (ECB rate of 2026-09-25), pulled 2026-09-28",
                                              "1 USD = 1.4277 AUD (ECB rate of 2026-09-29), pulled 2026-09-30", 1))
        # With no stamp, such a paragraph gets PRICE_NOTE under it.
        text = self.PARAGRAPH.sub(lambda m: "Scryfall lists prices in USD; this table shows AUD.", original, 1)
        deck = parse(text)
        self.assertEqual(("prices_insert" in deck.spans, "prices_other" in deck.spans), (True, False))
        decks.set_table(deck, deck.rows, deck.total, PriceStamp(1.4277, "2026-09-29", "2026-09-30"))
        self.assertIn("this table shows AUD.\n\nPrices are **estimates in AUD**: Scryfall's cheapest paper non-foil "
                      "printing (USD), converted at 1 USD = 1.4277 AUD (ECB rate of 2026-09-29), pulled 2026-09-30.\n\n"
                      + decks.TABLE_HEADER, decks.render_deck_file(deck))

    @staticmethod
    def fastest(fn, *args):
        """The quickest of three runs, in seconds (a busy PC only slows some)."""
        times = []
        for _ in range(3):
            start = time.perf_counter()
            fn(*args)
            times.append(time.perf_counter() - start)
        return min(times)

    def test_the_rate_patterns_take_linear_time(self):
        # The paragraph is anyone's text. 10,000 digits in a row took the "per"
        # form 5.6 s, and spaces after "USD to AUD rate" as long: each start in
        # the run was tried against all the rest of it.
        n = 10_000
        runs = ["1" * n, "1." + "1" * n, "$" + "1" * n, "USD " + "1" * n, "1" * n + " AUD", "rate of " + "1" * n,
                "multiplier " + "1" * n, " * " + "1" * n + " AUD", "×" + "1" * n, "1" * n + " per USD",
                "USD to AUD rate" + " " * n + "!", "USD/AUD" + " " * n + "x", "rate" + " " * n + "1",
                "multiplier" + " " * n + "x", "1 USD =" + " " * n + "x", "1.42 AUD per" + " " * n + "x",
                "US" + " " * n + "dollar", "1 " * (n // 2), "$ " * (n // 2), "1/" * (n // 2), "1.11 " * (n // 5),
                "exchange" + "1.11 " * (n // 5), "rate of " * (n // 8), "us " * (n // 3), "about " * (n // 6)]
        for text in runs:
            with self.subTest(text=text[:24]):
                self.assertLess(self.fastest(decks._rate_in, text), 0.05)
                for form, regex, _ in decks.RATE_FORMS:
                    self.assertLess(self.fastest(lambda t: list(regex.finditer(t)), text), 0.05, form)
        # And a deck file with such a paragraph above its table (it used to take seconds to open).
        original = read("casual/izzet-prowess").text
        for extra in (" " + "1" * n, " rate of" + " " * n + "x"):
            text = original.replace(self.STAMPED, self.STAMPED + extra, 1).encode()
            self.assertLess(self.fastest(decks.parse_deck, text, "izzet-prowess", "casual"), 0.05)

    def test_the_real_files_and_the_template_can_be_repriced(self):
        # Their paragraph names USD and AUD around the stamp, which is fine.
        for path in FIXTURE_FILES:
            with self.subTest(path.stem):
                deck = decks.read_deck_file(path)
                self.assertEqual((deck.prices, "prices_other" in deck.spans), (FIXTURE_STAMP, False))
        note = decks.PRICE_NOTE.format(stamp=FIXTURE_STAMP.text())
        text = decks.new_deck_text("X", "casual", [("Status", "idea")], {}, price_note=note)
        deck = parse(text)
        self.assertEqual((deck.prices, "prices_other" in deck.spans), (FIXTURE_STAMP, False))
        decks.set_table(deck, [], None, PriceStamp(1.4277, "2026-09-29", "2026-09-30"))
        self.assertIn("1 USD = 1.4277 AUD (ECB rate of 2026-09-29), pulled 2026-09-30", decks.render_deck_file(deck))


class KeepHandFormattingTests(unittest.TestCase):
    """An owned part that didn't change is written back exactly as it was read."""

    TEXT = ("# Edge\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Opt (FDN) 512  \n2 Negate\n\nSideboard\n```\n\n"
            "## Owned vs needed\n\nConverted at 1 USD = 1.4200 AUD (ECB rate of 2026-09-25), pulled 2026-09-28.\n\n"
            + decks.TABLE_HEADER + "\n" + decks.TABLE_RULE + "\n"
            "| Opt | 4 | 4 | 0 | | |  |   \n| Negate | 2 | 1 | 1 | | | |\n"
            "| **Total to buy** | | | **1** | | | |\n\n## Notes\n")

    def setUp(self):
        self.deck = parse(self.TEXT)

    def test_unchanged_render_keeps_everything(self):
        self.assertEqual(decks.render_deck_file(self.deck), self.TEXT)

    def test_a_status_edit_changes_only_the_status_line(self):
        decks.set_status(self.deck, "built")
        self.assertEqual(decks.render_deck_file(self.deck), self.TEXT.replace("**Status:** idea", "**Status:** built"))

    def test_equal_rows_and_stamp_from_set_table_are_kept(self):
        decks.set_table(self.deck, [TableRow("Opt", 4, 4, 0), TableRow("Negate", 2, 1, 1)],
                        TotalRow(1), PriceStamp(1.42, "2026-09-25", "2026-09-28"))
        self.assertEqual(decks.render_deck_file(self.deck), self.TEXT)

    def test_changed_parts_are_rebuilt(self):
        self.deck.target["Deck"][0].quantity = 3
        decks.set_table(self.deck, [TableRow("Opt", 3, 3, 0), TableRow("Negate", 2, 2, 0)],
                        TotalRow(0), PriceStamp(1.4237, "2026-09-28", "2026-09-28"))
        self.assertEqual(decks.render_deck_file(self.deck), self.TEXT
                         .replace("Deck\n4 Opt (FDN) 512  \n2 Negate\n\nSideboard\n", "Deck\n3 Opt (FDN) 512\n2 Negate\n")
                         .replace("| Opt | 4 | 4 | 0 | | |  |   \n", "| Opt | 3 | 3 | 0 | | |  |\n")
                         .replace("1.4200 AUD (ECB rate of 2026-09-25)", "1.4237 AUD (ECB rate of 2026-09-28)")
                         .replace("| Negate | 2 | 1 | 1 | | | |\n| **Total to buy** | | | **1** | | | |",
                                  "| Negate | 2 | 2 | 0 | | | |\n| **Total to buy** | | | **0** | | | |"))

    def test_an_empty_section_in_the_model_is_the_same_list(self):
        # An editor may send every section, empty ones included.
        self.deck.target["Sideboard"] = []
        self.deck.target["Companion"] = []
        decks.set_status(self.deck, "built")
        self.assertEqual(decks.render_deck_file(self.deck), self.TEXT.replace("**Status:** idea", "**Status:** built"))

    def test_line_endings_are_kept_line_by_line(self):
        # The last line of the file with no line break, and a stray CRLF line
        # in an LF file, come back as they were.
        table = self.TEXT[self.TEXT.index("## Owned vs needed"):self.TEXT.index("\n\n## Notes")]
        for text in (self.TEXT[:self.TEXT.index("## Owned vs needed")] + table,
                     "# T\n\n- **Status:** idea",
                     self.TEXT.replace("- **Status:** idea\n", "- **Format:** Casual\r\n- **Status:** idea\n")
                     .replace("| Negate | 2 | 1 | 1 | | | |\n", "| Negate | 2 | 1 | 1 | | | |\r\n")):
            with self.subTest(text[-30:]):
                deck = parse(text)
                self.assertEqual(decks.render_deck_file(deck), text)
                decks.set_status(deck, "built")          # only the changed line is rebuilt
                self.assertEqual(decks.render_deck_file(deck), text.replace("**Status:** idea", "**Status:** built"))
        # A new line after one that ended the file gets a line break first.
        deck = parse("# T\n\n- **Status:** idea")
        decks.set_field(deck, "Target bracket", "2")
        self.assertEqual(decks.render_deck_file(deck), "# T\n\n- **Status:** idea\n- **Target bracket:** 2\n")
        deck = parse(self.TEXT[:self.TEXT.index("## Owned vs needed")] + table)
        decks.set_table(deck, list(reversed(deck.rows)), deck.total)
        self.assertEqual(decks.render_deck_file(deck), self.TEXT[:self.TEXT.index("## Owned vs needed")] + table.replace(
            "| Opt | 4 | 4 | 0 | | |  |   \n| Negate | 2 | 1 | 1 | | | |\n",
            "| Negate | 2 | 1 | 1 | | | |\n| Opt | 4 | 4 | 0 | | |  |   \n"))

    def test_rows_added_under_a_rule_that_ends_the_file(self):
        text = self.TEXT[:self.TEXT.index("| Opt |")].rstrip("\n")          # ends "|---|...|---|"
        deck = parse(text)
        self.assertEqual((deck.rows, decks.render_deck_file(deck)), ([], text))
        decks.set_table(deck, [TableRow("Opt", 4, 4, 0), TableRow("Negate", 2, 1, 1)], TotalRow(1))
        out, again = rerender(deck)
        self.assertEqual(out, text + "\n| Opt | 4 | 4 | 0 | | |  |\n| Negate | 2 | 1 | **1** | | |  |\n"
                                     "| **Total to buy** | | | **1** | | | |\n")
        self.assertEqual([r.card for r in again.rows], ["Opt", "Negate"])


if __name__ == "__main__":
    unittest.main()
