"""Tests for the editor's API (Milestone 4): api.edit_view, printings,
parse_list, check_draft, save_deck, create_deck, stale_view and update_tables.

Each test runs in test_api's Sandbox (a temp magic/ tree, the fixture card
index, a mocked exchange rate of 2 AUD per USD, today fixed at 2026-10-05),
whose files backend (inventory.FileInventory) saves each deck as its file
there, so a test reads what a save stored from the file. FrozenSaveTests put
the frozen copies of the 11 real deck files (fixtures/decks/, and CRLF
copies of them) in the sandbox and save each one unchanged and with one card
changed. The same saves on the database backend (revisions, who changed a
deck) are in test_deck_saving_db.py.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
Regression and contract coverage lives in test_editor_contracts.py; shared fixtures,
core editing operations and frozen-file round trips remain here.
"""
import hashlib
import json
import shutil
import unittest
from unittest import mock

from decklab.lib import access, accessories, api, cards, decks, permissions
from decklab.tests.test_api import FIXTURES, ApiTestCase, _write
from decklab.tests.test_decks import prose

TODAY = "2026-10-05"
MARKER = f"*Decklist changed in Deck Lab on {TODAY}; prose sections may be out of date.*"

# A deck with an owned-vs-needed table (hand notes on a row and the total)
# and prose around it. Its table doesn't match the sandbox pool: the intact
# Beginner Box halves hold a Llanowar Elves each and the Elvish Mystic.
TABLE_DECK = """# Table Test

- **Format:** Casual 60-card, 1v1
- **Archetype:** Elves and friends
- **Played by:** wife
- **Status:** building

Some prose about the deck.

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
1 Elvish Mystic (CMM) 648
1 Black Lotus (LEA) 232
20 Forest
```

## Owned vs needed

Prices are estimates, converted at 1 USD = 1.5 AUD (ECB rate of 2026-09-20), pulled 2026-09-21.

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Black Lotus | 1 | 1 | 0 | | |  |
| Elvish Mystic | 1 | 1 | 0 | | |  |
| Llanowar Elves | 4 | 4 | 0 | | | hand note |
| **Total to buy** | | | **0** | | | total note |

## Substitutes

## Notes

Keep this prose.
"""


def lines(sections, section="Deck"):
    return [(l["qty"], l["name"], l["set"], l["number"], l["finish"]) for l in sections[section]]


def sandbox_accessories(case):
    """Point the accessories inventory at the sandbox's magic/ (no file: an empty inventory)."""
    for name, value in (("PATH", case.box.magic / "accessories.csv"),
                        ("IMAGES", case.box.magic / "accessories" / "images")):
        patcher = mock.patch.object(accessories, name, value)
        patcher.start()
        case.addCleanup(patcher.stop)


class EditorTestCase(ApiTestCase):
    """The Sandbox, with TABLE_DECK added."""

    def setUp(self):
        super().setUp()
        sandbox_accessories(self)
        _write(self.box.magic / "decks" / "casual" / "table-test.md", TABLE_DECK)

    def body(self, profile="matt", **data):
        return json.dumps(dict(data, profile=profile) if profile else data).encode("utf-8")

    def path(self, deck_id):
        return self.box.magic / "decks" / f"{deck_id}.md"

    def text(self, deck_id):
        return self.path(deck_id).read_bytes().decode("utf-8")

    def sha(self, deck_id):
        return hashlib.sha256(self.path(deck_id).read_bytes()).hexdigest()

    def edit_lists(self, view):
        """The lists as the page would send them back (card data and all)."""
        return {"target": view["lists"]["target"], "owned": view["lists"]["owned"]}

    def save(self, deck_id, lists=None, fields=None, sha=None, profile="matt"):
        data = {"id": deck_id, "sha256": sha or self.sha(deck_id)}
        if lists is not None:
            data["lists"] = lists
        if fields is not None:
            data["fields"] = fields
        return api.save_deck(self.body(profile, **data))

    def deck_files(self):
        """{path: bytes} of every deck file in the sandbox (what the saves have stored)."""
        return {p.relative_to(self.box.magic).as_posix(): p.read_bytes()
                for p in sorted((self.box.magic / "decks").rglob("*.md"))}


class EditViewTests(EditorTestCase):

    def test_a_deck_file(self):
        view = api.edit_view("casual/gruul-test")
        self.assertEqual(set(view), {"id", "space", "kind", "title", "source", "editable", "why_not", "sha256", "fields",
                                     "field_text", "editable_fields", "sections", "lists", "changed_on", "table", "prose",
                                     "new_deck", "brackets", "other_sleeves", "accessories",
                                     "warnings", "may_save", "why_not_save", "forge_lists"})
        self.assertEqual((view["id"], view["kind"], view["title"], view["editable"], view["why_not"]),
                         ("casual/gruul-test", "casual", "Gruul Test", True, None))
        self.assertEqual(view["source"], "casual/gruul-test")      # the deck's id, never a file
        self.assertEqual(view["sha256"], self.sha("casual/gruul-test"))
        self.assertEqual(view["fields"], {"format": "Casual 60-card, 1v1", "status": "building", "player": "either",
                                          "archetype": None, "built_version": None, "target_bracket": None,
                                          "sleeves": None, "deck_box": None})
        self.assertEqual(view["accessories"], {"sleeves": [], "deck_box": []})
        self.assertEqual(view["field_text"]["Played by"], "either")
        self.assertEqual(view["editable_fields"], ["status", "player", "archetype"])
        self.assertEqual(view["sections"], ["Deck", "Sideboard"])
        self.assertEqual(lines(view["lists"]["owned"]), [(4, "Llanowar Elves", "fdn", "227", "nonfoil")])
        self.assertEqual(view["lists"]["target"]["Deck"][0]["card"]["name"], "Llanowar Elves")
        self.assertEqual(view["table"], {"has_table": False, "stale": False, "changes": [],
                                         "sha256": view["sha256"]})
        json.dumps(view, allow_nan=False)

    def test_a_commander_deck_and_a_stale_table(self):
        view = api.edit_view("commander/elf-commander")
        self.assertEqual(view["sections"], ["Commander", "Deck", "Sideboard"])
        self.assertEqual(view["editable_fields"], ["status", "player", "archetype", "target_bracket"])
        self.assertEqual((view["fields"]["target_bracket"], view["lists"]["owned"]), (2, None))
        # The bracket picker's names come from stats.BRACKETS.
        self.assertEqual([(b["number"], b["name"]) for b in view["brackets"]][:3],
                         [(1, "Exhibition"), (2, "Core"), (3, "Upgraded")])
        self.assertEqual(len(view["brackets"]), 5)
        table = api.edit_view("casual/table-test")["table"]
        self.assertEqual((table["has_table"], table["stale"]), (True, True))
        self.assertEqual([c["card"] for c in table["changes"]], ["Elvish Mystic", "Llanowar Elves"])
        self.assertEqual(table["changes"][1]["was"], {"need": 4, "owned": 4, "missing": 0, "labels": []})
        self.assertEqual(table["changes"][1]["now"]["missing"], 1)

    def test_products_and_pairings_are_read_only_with_new_deck_defaults(self):
        precon = api.edit_view("product/fdc-test-precon")
        self.assertEqual((precon["editable"], precon["sha256"], precon["table"], precon["kind"]),
                         (False, None, None, "commander"))
        self.assertEqual(precon["new_deck"], {"from": "product/fdc-test-precon", "kind": "commander",
                                              "title": "Fdc Test Precon", "slug": "fdc-test-precon", "exists": False})
        self.assertEqual(lines(precon["lists"]["target"], "Commander"),
                         [(1, "Abaddon the Despoiler", "40k", "319", "etched")])
        pairing = api.edit_view("pairing/cats+elves")
        self.assertEqual(pairing["id"], "pairing/elves+cats")        # the library's order
        self.assertEqual(pairing["new_deck"]["title"], "Elves + Cats")
        self.assertEqual((pairing["new_deck"]["kind"], pairing["new_deck"]["slug"]), ("casual", "elves-cats"))
        half = api.edit_view("product/fdn-beginner-box/cats")
        self.assertEqual(half["new_deck"]["title"], "Cats")

    def test_files_deck_lab_cant_save(self):
        broken = api.edit_view("casual/broken")
        self.assertEqual((broken["editable"], broken["sha256"], broken["editable_fields"]), (False, None, []))
        self.assertIn("## Decklist", broken["why_not"])
        _write(self.box.magic / "decks" / "casual" / "Gruul_Copy.md", "# Copy\n\n## Decklist\n\n```\n1 Opt\n```\n")
        copy = api.edit_view("casual/Gruul_Copy")
        self.assertFalse(copy["editable"])
        self.assertIn("make a new deck", copy["why_not"])            # a deck can't be renamed

    def test_errors(self):
        self.assertApiError(404, api.edit_view, "casual/no-such-deck")
        self.assertApiError(400, api.edit_view, "casual/../x")
        with self.box.no_index():
            self.assertApiError(503, api.edit_view, "casual/gruul-test")


class PrintingsTests(EditorTestCase):

    def test_owned_printings_first_and_the_default(self):
        answer = api.printings("llanowar elves")
        self.assertEqual((answer["name"], answer["basic"]), ("Llanowar Elves", False))
        self.assertEqual(answer["default"], {"set": "fdn", "number": "227", "finish": "nonfoil", "why": "owned"})
        first = answer["printings"][0]
        self.assertEqual((first["set"], first["number"], first["owned"], first["on_the_way"]), ("fdn", "227", 5, 0))
        self.assertEqual(first["aud"], round(first["usd"] * 2.0, 2))
        # The shared printing picker (web/cards-ui.js pickPrinting) shows the set's name and the big picture.
        self.assertTrue(first["set_name"])
        self.assertEqual((first["img_small"], first["img"]), ("/img/fdn/227/small", "/img/fdn/227/normal"))
        self.assertEqual((answer["rate"], answer["rate_date"], answer["price_date"]), (2.0, "2026-09-28", "2026-09-28"))
        self.assertEqual(answer["total"], len(answer["printings"]))
        # After the ones the pool has: cheapest first.
        rest = [p["usd"] for p in answer["printings"][1:] if p["usd"] is not None]
        self.assertEqual(rest, sorted(rest))
        json.dumps(answer, allow_nan=False)

    def test_on_the_way_counts_and_the_cheapest_default(self):
        # Sol Ring is in the preordered precon: on the way, so it's the default.
        sol = api.printings("Sol Ring")
        self.assertEqual(sol["default"]["why"], "owned")
        self.assertEqual(sol["printings"][0]["on_the_way"], 1)
        poison = api.printings("Pick Your Poison")
        usd, set_code, number, finish = cards.cheapest_usd("Pick Your Poison")
        self.assertEqual(poison["default"], {"set": set_code, "number": number, "finish": finish, "why": "cheapest"})

    def test_basic_lands_get_no_default(self):
        self.assertEqual((api.printings("Forest")["basic"], api.printings("Forest")["default"]), (True, None))

    def test_errors(self):
        self.assertApiError(404, api.printings, "Llanowar Elfs", contains="No card named")
        for bad in ("", "  ", "x" * 151, "Opt\n", None):
            with self.subTest(name=bad):
                self.assertApiError(400, api.printings, bad)


class ParseListTests(EditorTestCase):

    def parse(self, text, **data):
        return api.parse_list(self.body(text=text, **data))

    def test_an_arena_export(self):
        answer = self.parse("About\nName Elf Party\n\nDeck\n4 Llanowar Elves (FDN) 227\n2 elvish mystic\n"
                            "1 Llanowar Elves (FDN) 227\n12 Forest\n\nSideboard\n2 Pick Your Poison (MKM) 170\n")
        self.assertEqual((answer["unknown"], answer["errors"]), ([], []))
        self.assertEqual(lines(answer["sections"]), [
            (5, "Llanowar Elves", "fdn", "227", "nonfoil"),          # the same printing, added up
            (2, "Elvish Mystic", "cmm", "648", "nonfoil"),           # the printing the pool owns
            (12, "Forest", None, None, "nonfoil")])                  # basics keep no set
        self.assertEqual(lines(answer["sections"], "Sideboard"), [(2, "Pick Your Poison", "mkm", "170", "nonfoil")])
        self.assertEqual(answer["count"], {"cards": 21, "lines": 4})
        json.dumps(answer, allow_nan=False)

    def test_unknown_names_and_bad_lines_are_reported_not_kept(self):
        answer = self.parse("4 Llanowar Elfs\nfour Forests\n1 Black Lotus\n100 Forest\n\n1 Sol Ring\n2 Opt\n"
                            "Sideboard\n1 Sol Ring\n")
        self.assertEqual([(u["line"], u["name"], u["qty"], u["section"]) for u in answer["unknown"]],
                         [(1, "Llanowar Elfs", 4, "Deck")])
        self.assertEqual(answer["unknown"][0]["suggestions"][0], "Llanowar Elves")
        self.assertEqual([(e["line"], e["text"]) for e in answer["errors"]],
                         [(2, "four Forests"), (4, "100 Forest"), (6, "1 Sol Ring"), (7, "2 Opt")])
        self.assertIn("blank line", answer["errors"][2]["error"])
        self.assertIn("at most 99", answer["errors"][1]["error"])
        # The cards after the blank line aren't guessed into the deck.
        self.assertEqual([l[1] for l in lines(answer["sections"])], ["Black Lotus"])
        self.assertEqual([l[1] for l in lines(answer["sections"], "Sideboard")], ["Sol Ring"])

    def test_a_printing_that_isnt_the_cards_gets_the_default(self):
        answer = self.parse("1 Llanowar Elves (MKM) 170\n1 Llanowar Elves (ZZZ)\n")
        self.assertEqual(lines(answer["sections"]), [(2, "Llanowar Elves", "fdn", "227", "nonfoil")])
        self.assertEqual(len(answer["warnings"]), 2)
        self.assertIn("isn't a printing of Llanowar Elves; using FDN 227 instead", answer["warnings"][0])

    def test_errors(self):
        self.assertApiError(413, api.parse_list, self.body(text="1 Forest\n" * 8000))
        self.assertApiError(400, api.parse_list, self.body(text=["1 Forest"]))
        self.assertApiError(400, api.parse_list, self.body(text="1 Forest", extra=1))
        self.assertApiError(403, api.parse_list, self.body(profile=None, text="1 Forest"))
        self.assertApiError(403, api.parse_list, self.body(profile="nobody", text="1 Forest"))
        self.assertApiError(400, api.parse_list, b"{nope")


class CheckTests(EditorTestCase):

    def test_each_list_gets_its_own_shared_pool_availability(self):
        view, lists = self.gruul()
        # The target needs six Elves; the owned list needs four. Two copies are
        # reserved by the intact Beginner Box, so only three of the five are free.
        answer = self.check(id="casual/gruul-test", sha256=view["sha256"], lists=lists)
        def elves(version):
            return next(row for row in answer["availability"][version]["rows"] if row["name"] == "Llanowar Elves")
        self.assertEqual((elves("target")["need"], elves("target")["missing"]), (6, 3))
        self.assertEqual((elves("owned")["need"], elves("owned")["missing"]), (4, 1))
        self.assertEqual(answer["owned"], answer["availability"]["target"])
        # A new draft quantity changes only its own list's availability.
        lists["owned"]["Deck"][0]["qty"] = 2
        answer = self.check(id="casual/gruul-test", lists=lists)
        self.assertEqual((elves("owned")["need"], elves("owned")["missing"]), (2, 0))
        self.assertEqual(elves("target")["missing"], 3)

    def check(self, **data):
        return api.check_draft(self.body(**data))

    def gruul(self):
        view = api.edit_view("casual/gruul-test")
        return view, self.edit_lists(view)

    def test_an_unchanged_draft(self):
        view, lists = self.gruul()
        answer = self.check(id="casual/gruul-test", sha256=view["sha256"], lists=lists, fields=view["fields"])
        self.assertEqual((answer["ok"], answer["blocks"], answer["file_changed"]), (True, [], False))
        self.assertEqual(answer["changes"], {"decklist": False, "fields": [], "prose": [], "marker": False})
        self.assertEqual(answer["counts"]["target"], {"main": 23, "sideboard": 2, "commander": 0, "companion": 0})
        self.assertIn("23 cards; a casual deck has at least 60.", answer["warnings"])
        self.assertEqual(answer["owned"]["rate"], 2.0)
        self.assertEqual(set(answer), {"ok", "blocks", "warnings", "warning_cards", "lists", "counts", "bracket",
                                       "brackets", "owned", "availability", "changes", "file_changed"})
        self.assertEqual(len(answer["warning_cards"]), len(answer["warnings"]))
        about = dict(zip(answer["warnings"], answer["warning_cards"]))
        self.assertEqual(about["6 copies of Llanowar Elves; a deck can have at most 4."], ["Llanowar Elves"])
        self.assertEqual(about["23 cards; a casual deck has at least 60."], [])
        self.assertEqual(answer["brackets"], [])            # a casual deck has no bracket to pick
        json.dumps(answer, allow_nan=False)

    def test_new_lines_get_exact_names_and_printings(self):
        view, lists = self.gruul()
        lists["target"]["Deck"].append({"qty": 1, "name": "aerie mystics"})
        lists["target"]["Deck"].append({"qty": 2, "name": "Pick Your Poison", "set": "MKM", "number": "170"})
        lists["target"]["Deck"].append({"qty": 2, "name": "llanowar elves"})
        lists["target"]["Deck"].append({"qty": 1, "name": "Black Lotus"})     # a line just like one it has
        answer = self.check(id="casual/gruul-test", lists=lists, fields={"status": "built"})
        self.assertEqual(answer["blocks"], [])
        deck = lines(answer["lists"]["target"])
        # The owned printing, added to the line the list already has for it.
        self.assertEqual(deck[0], (6, "Llanowar Elves", "fdn", "227", "nonfoil"))
        _, set_code, number, finish = cards.cheapest_usd("Aerie Mystics")      # none owned: the cheapest
        self.assertIn((1, "Aerie Mystics", set_code, number, finish), deck)
        self.assertIn((2, "Pick Your Poison", "mkm", "170", "nonfoil"), deck)
        # A line just like one the file has stays a line of its own, as files may have that on purpose.
        self.assertEqual(deck.count((1, "Black Lotus", None, None, "nonfoil")), 2)
        self.assertEqual(len(deck), 14)
        self.assertEqual(answer["changes"], {"decklist": True, "fields": ["status"], "prose": [], "marker": False})
        self.assertIsNone(answer["file_changed"])
        self.assertIn("8 copies of Llanowar Elves; a deck can have at most 4.", answer["warnings"])

    def test_blocks(self):
        view, lists = self.gruul()
        deck = lists["target"]["Deck"]
        deck += [{"qty": 1, "name": "Llanowar Elfs"}, {"qty": 0, "name": "Forest"}, {"qty": 100, "name": "Forest"},
                 {"qty": "4", "name": "Forest"}, {"qty": True, "name": "Forest"}, {"qty": 1, "name": ""},
                 {"qty": 1, "name": "Llanowar Elves", "set": "mkm", "number": "170"},
                 {"qty": 1, "name": "Llanowar Elves", "set": "fdn", "number": "227", "finish": "etched"},
                 {"qty": 1, "name": "Llanowar Elves", "number": "227"},
                 {"qty": 1, "name": "Llanowar Elves", "set": "no such set!"},
                 {"qty": 1, "name": "Llanowar Elves", "finish": "shiny"}]
        lists["target"]["Commander"] = [{"qty": 1, "name": "Ghalta, Primal Hunger"}]
        lists["target"]["Maybeboard"] = [{"qty": 1, "name": "Opt"}]
        answer = self.check(id="casual/gruul-test", lists=lists,
                            fields={"status": "done", "player": "nobody", "archetype": "two\nlines",
                                    "target_bracket": 3, "built_version": "target", "sleeves": "x" * 41})
        self.assertFalse(answer["ok"])
        problems = [(b["list"], b["section"], b["index"], b["field"]) for b in answer["blocks"]]
        self.assertEqual(problems, [("target", "Deck", i, None) for i in range(11, 22)] + [
            ("target", "Commander", None, None), ("target", "Maybeboard", None, None),
            (None, None, None, "status"), (None, None, None, "player"), (None, None, None, "archetype"),
            (None, None, None, "target_bracket"), (None, None, None, "sleeves"),
            (None, None, None, "built_version")])
        unknown = answer["blocks"][0]
        self.assertEqual((unknown["name"], unknown["suggestions"][0]), ("Llanowar Elfs", "Llanowar Elves"))
        self.assertIn("Did you mean Llanowar Elves?", unknown["problem"])
        self.assertIn("isn't a printing of Llanowar Elves", answer["blocks"][6]["problem"])
        self.assertIn("doesn't come in etched", answer["blocks"][7]["problem"])

    def test_a_commander_deck(self):
        view = api.edit_view("commander/elf-commander")
        answer = self.check(id="commander/elf-commander", lists=self.edit_lists(view), fields={"target_bracket": 1})
        self.assertTrue(answer["ok"])
        self.assertIn("3 cards with the commander; a Commander deck has exactly 100.", answer["warnings"])
        self.assertEqual(answer["bracket"]["target"], 1)
        self.assertEqual(answer["changes"]["fields"], ["target_bracket"])
        self.assertEqual(answer["brackets"], view["brackets"])

    def test_a_new_deck(self):
        answer = self.check(kind="casual", lists={"target": {"Deck": [{"qty": 4, "name": "Llanowar Elves"}]}})
        self.assertEqual((answer["ok"], answer["changes"]["decklist"]), (True, True))
        from_pairing = self.check(**{"from": "pairing/cats+elves"})
        self.assertEqual(from_pairing["counts"]["target"]["main"], 11)
        self.assertEqual(from_pairing["owned"]["totals"]["cards"], 3)

    def test_file_changed(self):
        view, lists = self.gruul()
        _write(self.path("casual/gruul-test"), self.text("casual/gruul-test") + "\nMore.\n")
        answer = self.check(id="casual/gruul-test", sha256=view["sha256"], lists=lists)
        self.assertTrue(answer["file_changed"])

    def test_malformed_requests(self):
        view, lists = self.gruul()
        for data in ({"id": "casual/gruul-test", "lists": []},
                     {"id": "casual/gruul-test", "lists": {"target": []}},
                     {"id": "casual/gruul-test", "lists": {"target": {"Deck": {}}}},
                     {"id": "casual/gruul-test", "lists": {"target": {"Deck": ["4 Forest"]}}},
                     {"id": "casual/gruul-test", "lists": {"maybe": {}}},
                     {"id": "casual/gruul-test", "fields": {"title": "New"}},
                     {"id": "casual/gruul-test", "fields": []},
                     {"id": "casual/gruul-test", "kind": "casual"},
                     {"id": "casual/gruul-test", "sha256": "abc"},
                     {"id": "product/fdc-test-precon"},
                     {"id": "casual/gruul-test", "surprise": 1},
                     {"kind": "modern"},
                     {"from": "casual/x/y"}):
            with self.subTest(data=data):
                self.assertApiError(400, api.check_draft, self.body(**data))
        self.assertApiError(404, api.check_draft, self.body(id="casual/nothing-here"))
        self.assertApiError(404, api.check_draft, self.body(**{"from": "pairing/cats+nobody"}))
        self.assertApiError(403, api.check_draft, self.body(profile="guest", id="casual/gruul-test"))


class SaveTests(EditorTestCase):

    def test_a_decklist_change(self):
        view = api.edit_view("casual/table-test")
        lists = self.edit_lists(view)
        lists["target"]["Deck"][0]["qty"] = 3
        before = self.box.magic.joinpath("decks", "casual", "table-test.md").read_bytes()
        others = {k: v for k, v in self.deck_files().items() if k != "decks/casual/table-test.md"}
        answer = self.save("casual/table-test", lists)
        self.assertEqual((answer["saved"], answer["changed"], answer["marked"]), (True, True, TODAY))
        self.assertNotIn("commit", answer)
        self.assertEqual(answer["table"], {"rewritten": True, "repriced": True, "note": None})
        self.assertEqual(answer["sha256"], self.sha("casual/table-test"))
        self.assertEqual(answer["deck"]["sha256"], answer["sha256"])
        text = self.text("casual/table-test")
        self.assertIn(f"- **Status:** building\n\n{MARKER}\n\nSome prose about the deck.", text)
        self.assertIn("3 Llanowar Elves (FDN) 227\n", text)
        self.assertIn("converted at 1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-28.", text)
        # The table follows the target list and the pool, and keeps its hand notes.
        self.assertIn("| Llanowar Elves | 3 | 3 | 0 | | | hand note |\n", text)
        self.assertIn("| Elvish Mystic | 1 | 0 | **1** |", text)
        self.assertRegex(text, r"\| \*\*Total to buy\*\* \| \| \| \*\*1\*\* \| \| \*\*~\$[\d.]+\*\* \| total note \|")
        deck = decks.parse_deck(text.encode("utf-8"), "table-test", "casual")
        self.assertEqual(prose(deck), prose(decks.parse_deck(before, "table-test", "casual")))
        # Only this deck changed.
        self.assertEqual({k: v for k, v in self.deck_files().items() if k != "decks/casual/table-test.md"}, others)

    def test_a_header_only_change_has_no_marker(self):
        answer = self.save("casual/table-test", fields={"status": "built", "player": "either"})
        self.assertEqual((answer["changed"], answer["marked"]), (True, None))
        text = self.text("casual/table-test")
        self.assertNotIn("Decklist changed", text)
        self.assertIn("- **Played by:** either\n- **Status:** built\n\nSome prose", text)
        self.assertEqual(answer["table"]["rewritten"], True)            # a save rewrites the table

    def test_fields_keep_the_words_after_them_and_brackets_get_their_name(self):
        path = self.path("casual/gruul-test")
        _write(path, self.text("casual/gruul-test").replace("- **Played by:** either",
                                                            "- **Played by:** either. Whoever likes elves."))
        self.save("casual/gruul-test", fields={"player": "either", "status": "idea", "archetype": " Elves "})
        text = self.text("casual/gruul-test")
        self.assertIn("- **Format:** Casual 60-card, 1v1\n- **Archetype:** Elves\n"
                      "- **Played by:** either. Whoever likes elves.\n- **Status:** idea\n", text)
        self.save("commander/elf-commander", fields={"target_bracket": 3})
        self.assertIn("- **Target bracket:** 3 (Upgraded)\n", self.text("commander/elf-commander"))

    def test_an_unchanged_save_writes_nothing(self):
        view = api.edit_view("casual/gruul-test")
        before = self.path("casual/gruul-test").read_bytes()
        answer = self.save("casual/gruul-test", self.edit_lists(view), view["fields"])
        self.assertEqual((answer["changed"], answer["marked"], answer["sha256"]), (False, None, view["sha256"]))
        self.assertEqual(answer["table"]["rewritten"], False)
        self.assertEqual(self.path("casual/gruul-test").read_bytes(), before)

    def test_starting_an_owned_only_version(self):
        view = api.edit_view("commander/elf-commander")
        target = view["lists"]["target"]
        answer = self.save("commander/elf-commander", {"target": target, "owned": target})
        self.assertEqual(answer["marked"], TODAY)
        text = self.text("commander/elf-commander")
        self.assertTrue(text.endswith("### Substitute version (owned and incoming cards)\n\n```\nCommander\n1 Ghalta, Primal Hunger (RIX) 130\n\n"
                                      "Deck\n1 Llanowar Elves (FDN) 227\n1 Sol Ring (ECC) 57\n```\n"), text[-300:])
        self.assertEqual(answer["deck"]["lists"]["owned"], answer["deck"]["lists"]["target"])
        # ... and it can't be emptied again.
        error = self.assertApiError(400, api.save_deck, self.body(id="commander/elf-commander",
                                                                  sha256=answer["sha256"],
                                                                  lists={"owned": {}}))
        self.assertEqual(error.extra["blocks"][0]["list"], "owned")

    def test_blocks_refuse_the_save(self):
        before = self.path("casual/gruul-test").read_bytes()
        error = self.assertApiError(400, api.save_deck, self.body(
            id="casual/gruul-test", sha256=self.sha("casual/gruul-test"),
            lists={"target": {"Deck": [{"qty": 4, "name": "Llanowar Elfs"}, {"qty": 1, "name": "Opt"}]}}),
            contains="The deck can't be saved yet: 'Llanowar Elfs' isn't a card name")
        self.assertIn("and 1 more problem", error.message)          # Opt isn't in the file as a new line
        self.assertEqual(len(error.extra["blocks"]), 2)
        self.assertEqual(self.path("casual/gruul-test").read_bytes(), before)

    def test_names_the_file_already_has_are_kept_with_a_warning(self):
        view = api.edit_view("casual/gruul-test")          # Opt (FDN) 512 isn't in the fixture card data
        lists = self.edit_lists(view)
        lists["target"]["Deck"][0]["qty"] = 2
        answer = self.save("casual/gruul-test", lists)
        self.assertIn("1 Opt (FDN) 512\n", self.text("casual/gruul-test"))
        self.assertTrue(any("'Opt' isn't a card name in the card data; it was already in the file" in w
                            for w in answer["warnings"]))

    def test_a_rate_worded_differently_isnt_repriced(self):
        path = self.path("casual/table-test")
        _write(path, TABLE_DECK.replace("converted at 1 USD = 1.5 AUD (ECB rate of 2026-09-20), pulled 2026-09-21",
                                        "at 1 USD = 1.42 AUD (ECB, 2026-09-25)")
               .replace("| Llanowar Elves | 4 | 4 | 0 | | |", "| Llanowar Elves | 4 | 3 | **1** | ~$0.30 | ~$0.30 |"))
        answer = self.save("casual/table-test", fields={"status": "built"})
        self.assertEqual((answer["table"]["rewritten"], answer["table"]["repriced"]), (True, False))
        self.assertIn("in its own words", answer["table"]["note"])
        text = self.text("casual/table-test")
        self.assertIn("at 1 USD = 1.42 AUD (ECB, 2026-09-25)", text)
        self.assertIn("| Llanowar Elves | 4 | 3 | **1** | ~$0.30 | ~$0.30 | ", text)    # still applies: kept
        self.assertIn("| Elvish Mystic | 1 | 0 | **1** | | |", text)                     # new: left blank

    def test_a_refused_save_changes_nothing(self):
        before = self.deck_files()
        with mock.patch.object(api.saving.inventory, "apply", side_effect=api.saving.inventory.Unavailable("down")):
            error = self.assertApiError(503, api.save_deck, self.body(
                id="casual/table-test", sha256=self.sha("casual/table-test"), fields={"status": "built"}))
        self.assertEqual(error.extra.get("reason"), "database")
        self.assertEqual(self.deck_files(), before)

    def test_bad_requests(self):
        sha = self.sha("casual/gruul-test")
        for data, status in (({"id": "casual/gruul-test"}, 400),                         # no sha256
                             ({"id": "casual/gruul-test", "sha256": sha.upper()}, 400),
                             ({"id": "product/fdc-test-precon", "sha256": sha}, 400),
                             ({"id": "pairing/cats+elves", "sha256": sha}, 400),
                             ({"id": "casual/Gruul_Copy", "sha256": sha}, 400),
                             ({"id": "casual/../../x", "sha256": sha}, 400),
                             ({"id": "casual/con", "sha256": sha}, 400),
                             ({"id": "casual/gruul-test", "sha256": sha, "lists": {"target": {"Deck": [
                                 {"qty": 1, "name": "Forest"}] * 300}}}, 400),
                             ({"id": "casual/broken", "sha256": self.sha("casual/broken")}, 500)):
            with self.subTest(data=data):
                self.assertApiError(status, api.save_deck, self.body(**data))
        self.assertApiError(413, api.save_deck, b" " * (api.MAX_EDIT_BODY + 1))
        self.assertApiError(403, api.save_deck, self.body(profile=None, id="casual/gruul-test", sha256=sha))


class ConflictTests(EditorTestCase):
    """The files backend keeps no revisions, so a 409 can't say who saved the deck since (the
    database's answers, naming them, are in test_deck_saving_db.py)."""

    def test_another_save(self):
        view = api.edit_view("casual/table-test")
        self.save("casual/table-test", fields={"status": "built"}, profile="user1")
        error = self.assertApiError(409, api.save_deck, self.body(
            id="casual/table-test", sha256=view["sha256"], fields={"status": "idea"}))
        self.assertEqual(error.message, "Table Test changed after you opened it: it was saved again since. Your "
                                        "changes weren't saved.")
        self.assertEqual(error.extra["conflict"], {"reason": "changed", "by": None, "deck_lab": False, "when": None,
                                                   "subject": None})
        self.assertIn("- **Status:** built", self.text("casual/table-test"))       # User1's save stands

    def test_a_change_between_reading_and_saving(self):
        # The deck changes after the save read it, before the operation stores it: the operation's
        # own sha256 check refuses, with the same 409.
        view = api.edit_view("casual/table-test")
        real = api.saving.inventory.apply

        def sneaky(op, *args, **kw):
            _write(self.path("casual/table-test"), TABLE_DECK + "\nA hand edit.\n")
            return real(op, *args, **kw)
        with mock.patch.object(api.saving.inventory, "apply", sneaky):
            error = self.assertApiError(409, api.save_deck, self.body(
                id="casual/table-test", sha256=view["sha256"], fields={"status": "built"}))
        self.assertEqual(error.extra["conflict"]["reason"], "changed")
        self.assertTrue(self.text("casual/table-test").endswith("\nA hand edit.\n"))

    def test_a_deleted_deck(self):
        view = api.edit_view("casual/table-test")
        self.path("casual/table-test").unlink()
        self.assertApiError(404, api.save_deck, self.body(id="casual/table-test", sha256=view["sha256"]),
                            contains="No deck 'casual/table-test'")
        self.assertFalse(self.path("casual/table-test").exists())


class CreateTests(EditorTestCase):

    def create(self, profile="matt", **data):
        return api.create_deck(self.body(profile, **data))

    def test_from_scratch(self):
        answer = self.create("user1", title="  Lórien   Elves ", kind="casual",
                             fields={"archetype": "Elf ramp"},
                             lists={"target": {"Deck": [{"qty": 4, "name": "llanowar elves"},
                                                        {"qty": 20, "name": "Forest"}]}})
        self.assertEqual((answer["created"], answer["id"], answer["title"]), (True, "casual/lorien-elves", "Lórien Elves"))
        self.assertNotIn("commit", answer)
        text = self.text("casual/lorien-elves")
        self.assertTrue(text.startswith(
            "# Lórien Elves\n\n- **Format:** Casual 60-card, 1v1\n- **Archetype:** Elf ramp\n"
            "- **Played by:** wife\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves (FDN) 227\n"
            "20 Forest\n```\n\n## Owned vs needed\n\nPrices are **estimates in AUD**: Scryfall's cheapest paper "
            "non-foil printing (USD), converted at 1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-28.\n\n"
            "| Card | Need |"), text[:600])
        self.assertTrue(text.endswith("\n\n## Substitutes\n\n## Notes\n"))
        deck = decks.parse_deck(text.encode("utf-8"), "lorien-elves", "casual")
        self.assertEqual(decks.render_deck_file(deck), text)
        self.assertEqual([r.card for r in deck.rows], ["Llanowar Elves"])
        self.assertEqual(answer["sha256"], self.sha("casual/lorien-elves"))
        self.assertEqual(answer["deck"]["editable"], True)

    def test_a_commander_deck_from_scratch(self):
        self.create(title="Ghalta Stompy", kind="commander",
                    lists={"target": {"Commander": [{"qty": 1, "name": "Ghalta, Primal Hunger"}]}})
        text = self.text("commander/ghalta-stompy")
        self.assertIn("- **Format:** Commander (100 cards)\n- **Played by:** user\n- **Status:** idea\n"
                      "- **Target bracket:** 2 (Core)\n", text)
        self.assertIn("Commander\n1 Ghalta, Primal Hunger (RIX) 130\n", text)

    def test_save_as_a_new_deck_from_a_pairing_and_a_precon(self):
        answer = self.create(title="Elves + Cats", **{"from": "pairing/cats+elves"})
        self.assertEqual(answer["id"], "casual/elves-cats")
        text = self.text("casual/elves-cats")
        self.assertIn("```\nDeck\n2 Llanowar Elves (FDN) 227\n1 Elvish Mystic (CMM) 648\n7 Forest (FDN)\n"
                      "1 Pick Your Poison (MKM) 170\n```", text)
        self.assertTrue(text.endswith("## Notes\n\nStarted in Deck Lab on 2026-10-05 by Matt, from Elves + Cats "
                                      "(Beginner Box).\n"), text[-200:])
        self.assertIn("11 cards; a casual deck has at least 60.", answer["warnings"])
        precon = self.create(title="Abaddon", **{"from": "product/fdc-test-precon"},
                             lists={"target": {"Commander": [{"qty": 1, "name": "Abaddon the Despoiler",
                                                              "set": "40k", "number": "319", "finish": "etched"}],
                                               "Deck": [{"qty": 1, "name": "Sol Ring", "set": "ecc", "number": "57"},
                                                        {"qty": 30, "name": "Swamp", "set": "fdc"}]}})
        self.assertEqual(precon["id"], "commander/abaddon")
        self.assertIn("30 Swamp (FDC)\n", self.text("commander/abaddon"))
        self.assertApiError(400, api.create_deck, self.body(title="X", kind="casual", **{"from": "product/fdc-test-precon"}))

    def test_a_title_that_is_taken_or_unusable(self):
        error = self.assertApiError(409, api.create_deck, self.body(title="Gruul Test!", kind="casual"))
        self.assertEqual(error.extra["conflict"], {"reason": "exists", "id": "casual/gruul-test"})
        error = self.assertApiError(409, api.create_deck, self.body(title="Elf Commander", kind="casual"))
        self.assertEqual(error.extra["conflict"]["id"], "commander/elf-commander")      # the other folder too
        for title in ("!!!", "Con", "", "x" * 101, "Two\nlines", 7):
            with self.subTest(title=title):
                error = self.assertApiError(400, api.create_deck, self.body(title=title, kind="casual"))
                self.assertEqual(error.extra["blocks"][0]["field"], "title")
        for data in ({"title": "Fine"}, {"title": "Fine", "kind": "modern"},
                     {"title": "Fine", "kind": "casual", "fields": {"built_version": "target"}},
                     {"title": "Fine", "kind": "casual", "lists": {"owned": {}}}):
            with self.subTest(data=data):
                self.assertApiError(400, api.create_deck, self.body(**data))
        self.assertFalse(self.path("casual/fine").exists())

    def test_a_name_taken_between_the_check_and_the_save(self):
        # Another save takes the name after create_deck checked it: deck.create refuses inside the change.
        with mock.patch.object(api.saving.decks, "existing_deck_id", return_value=None):
            error = self.assertApiError(409, api.create_deck, self.body(title="Gruul Test", kind="commander"))
        self.assertEqual(error.extra["conflict"], {"reason": "exists", "id": "casual/gruul-test"})
        self.assertFalse(self.path("commander/gruul-test").exists())


class TableTests(EditorTestCase):

    def test_stale_tables_after_a_save_and_updating_them(self):
        stale = api.stale_view()["stale"]
        self.assertEqual([s["id"] for s in stale], ["casual/table-test"])
        self.assertEqual(stale[0]["sha256"], self.sha("casual/table-test"))
        updated = api.update_tables(self.body(decks=[{"id": s["id"], "sha256": s["sha256"]} for s in stale]))
        self.assertEqual([u["id"] for u in updated["updated"]], ["casual/table-test"])
        self.assertEqual((updated["stale_tables"], updated["unchanged"]), ([], []))
        self.assertEqual(updated["updated"][0]["sha256"], self.sha("casual/table-test"))
        self.assertNotIn("commit", updated)
        text = self.text("casual/table-test")
        self.assertNotIn("Decklist changed", text)
        self.assertIn("| Llanowar Elves | 4 | 3 | **1** |", text)
        self.assertIn("hand note |", text)

        # Building Gruul Test's target list takes its Llanowar Elves from the
        # pool, so Table Test's table is out of date again.
        answer = self.save("casual/gruul-test", fields={"status": "built"})
        self.assertEqual([s["id"] for s in answer["stale_tables"]], ["casual/table-test"])
        change = answer["stale_tables"][0]["changes"][0]
        self.assertEqual((change["card"], change["now"]["missing"]), ("Llanowar Elves", 4))
        self.assertEqual(api.edit_view("casual/table-test")["table"]["stale"], True)
        self.assertEqual(api.deck_view("casual/table-test")["table"]["stale"], True)

    def test_the_list_names_the_decks_it_cant_update(self):
        _write(self.box.magic / "decks" / "casual" / "table-two.md",
               TABLE_DECK.replace("# Table Test", "# Table Two").replace("1 Black Lotus (LEA) 232", "1 Not A Card"))
        view = api.stale_view()
        self.assertEqual(set(view), {"stale", "blocked", "held", "warnings"})
        # Table Two's table is out of date too, but deck tables can't update it: it's only in blocked.
        self.assertEqual([(s["id"], s["may_update"]) for s in view["stale"]], [("casual/table-test", True)])
        two = [b for b in view["blocked"] if b["id"] == "casual/table-two"]
        self.assertEqual([(b["reason"], b["version"], b["cards"], b["title"]) for b in two],
                         [("unknown_cards", "target", ["Not A Card"], "Table Two")])
        self.assertIn("Not A Card", two[0]["why"])
        # Gruul Test has no owned-vs-needed table at all.
        self.assertIn(("casual/gruul-test", "no_table"), [(b["id"], b["reason"]) for b in view["blocked"]])

    def test_a_changed_file_stops_the_update(self):
        stale = api.stale_view()["stale"][0]
        _write(self.path("casual/table-test"), TABLE_DECK + "\nEdited.\n")
        error = self.assertApiError(409, api.update_tables, self.body(decks=[
            {"id": stale["id"], "sha256": stale["sha256"]}]))
        self.assertIn("No tables were updated", error.message)
        self.assertEqual(error.extra["conflict"]["decks"][0]["id"], "casual/table-test")
        self.assertEqual(self.text("casual/table-test"), TABLE_DECK + "\nEdited.\n")

    def test_all_or_nothing(self):
        # Two decks: one changes after its table was worked out, so neither table is saved.
        _write(self.box.magic / "decks" / "casual" / "table-two.md", TABLE_DECK.replace("# Table Test", "# Table Two"))
        stale = api.stale_view()["stale"]
        self.assertEqual([s["id"] for s in stale], ["casual/table-test", "casual/table-two"])
        before = self.deck_files()
        real = api.saving.inventory.apply

        def sneaky(op, *args, **kw):
            _write(self.box.magic / "decks" / "casual" / "table-two.md", TABLE_DECK + "\nEdited.\n")
            return real(op, *args, **kw)
        with mock.patch.object(api.saving.inventory, "apply", sneaky):
            error = self.assertApiError(409, api.update_tables, self.body(decks=[
                {"id": s["id"], "sha256": s["sha256"]} for s in stale]))
        self.assertEqual([d["id"] for d in error.extra["conflict"]["decks"]], ["casual/table-two"])
        self.assertEqual(error.extra["conflict"]["decks"][0]["title"], "Table Two")
        self.assertEqual(self.text("casual/table-test"), before["decks/casual/table-test.md"].decode("utf-8"))

    def test_a_deck_deleted_during_the_update(self):
        # The files backend keeps no revisions, so a deck gone since the tables were worked out is
        # "deleted" with no by or when (not _conflict's 404 "No deck ..." inside the 409's words).
        _write(self.box.magic / "decks" / "casual" / "table-two.md", TABLE_DECK.replace("# Table Test", "# Table Two"))
        stale = api.stale_view()["stale"]
        real = api.saving.inventory.apply

        def sneaky(op, *args, **kw):
            (self.box.magic / "decks" / "casual" / "table-two.md").unlink()
            return real(op, *args, **kw)
        with mock.patch.object(api.saving.inventory, "apply", sneaky):
            error = self.assertApiError(409, api.update_tables, self.body(decks=[
                {"id": s["id"], "sha256": s["sha256"]} for s in stale]))
        self.assertTrue(error.message.startswith("Table Two was deleted after you opened it."), error.message)
        self.assertEqual(error.extra["conflict"]["decks"], [{
            "reason": "deleted", "by": None, "deck_lab": False, "when": None, "subject": None,
            "id": "casual/table-two", "title": "Table Two"}])

    def test_an_up_to_date_table_is_left_alone(self):
        sha = self.sha("casual/gruul-test")
        answer = api.update_tables(self.body(decks=[{"id": "casual/gruul-test", "sha256": sha}]))
        self.assertEqual((answer["updated"], answer["unchanged"]), ([], ["casual/gruul-test"]))

    def test_bad_requests(self):
        sha = self.sha("casual/table-test")
        for decks_ in ([], [{"id": "casual/table-test"}], [{"id": "casual/table-test", "sha256": sha}] * 2,
                       [{"id": "product/fdc-test-precon", "sha256": sha}], "casual/table-test",
                       [{"id": f"casual/deck-{i}", "sha256": sha} for i in range(api.saving.MAX_TABLE_DECKS + 1)]):
            with self.subTest(decks=decks_):
                self.assertApiError(400, api.update_tables, self.body(decks=decks_))


class PersonSpaceTests(EditorTestCase):
    """A deck in User2's own space (lib/spaces.py): magic/people/user2/."""

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps({"profiles": [
            {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"},
            {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member"},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2",
             "emails": ["user2@example.com"]}]}))
        self.people = self.box.magic / "people" / "user2"
        _write(self.people / "collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
                                               "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n")

    def create_user2s(self, **data):
        return api.create_deck(self.body("user2", title="User2 Elves", kind="casual", space="user2",
                                         lists={"target": {"Deck": [{"qty": 4, "name": "Llanowar Elves"}]}},
                                         **data))

    def test_profiles_carry_role_and_space_but_never_emails(self):
        listed = api.profiles()["profiles"]
        self.assertEqual(listed[2], {"id": "user2", "name": "User2", "plays_as": None, "role": "member",
                                     "space": "user2"})
        self.assertNotIn("example.com", json.dumps(listed))

    def test_a_new_deck_in_a_person_space(self):
        answer = self.create_user2s()
        self.assertEqual(answer["id"], "user2/casual/user2-elves")
        self.assertNotIn("commit", answer)
        text = (self.people / "decks" / "casual" / "user2-elves.md").read_text(encoding="utf-8")
        self.assertIn("- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n", text)
        self.assertNotIn("Played by", text)
        self.assertIn("| Llanowar Elves | 4 | 1 | **3** |", text)        # User2's one copy, not the home five
        self.assertEqual((answer["deck"]["space"], answer["deck"]["editable"]), ("user2", True))
        self.assertNotIn("player", answer["deck"]["editable_fields"])
        # The same title at home is another deck.
        self.assertEqual(api.create_deck(self.body(title="User2 Elves", kind="casual"))["id"],
                         "casual/user2-elves")
        error = self.assertApiError(409, self.create_user2s)
        self.assertEqual(error.extra["conflict"]["id"], "user2/casual/user2-elves")

    def test_person_decks_in_the_library_and_deck_page(self):
        self.create_user2s()
        index = {d["id"]: d for d in api.decks_index()["decks"]}
        self.assertEqual(index["user2/casual/user2-elves"]["space"], "user2")
        self.assertEqual(index["user2/casual/user2-elves"]["missing"], {"target": 3})
        self.assertEqual(index["casual/gruul-test"]["space"], "home")
        view = api.deck_view("user2/casual/user2-elves")
        self.assertEqual(view["owned"]["totals"]["missing"], 3)
        self.assertIsNone(view["summary"]["kit"])
        self.assertIs(view["table"]["stale"], False)            # worked out in User2's pool
        self.assertEqual(api.edit_view("user2/casual/user2-elves")["id"], "user2/casual/user2-elves")

    def test_saving_and_refused_fields(self):
        self.create_user2s()
        deck_id = "user2/casual/user2-elves"
        path = self.people / "decks" / "casual" / "user2-elves.md"
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        saved = api.save_deck(self.body("user2", id=deck_id, sha256=sha,
                                        lists={"target": {"Deck": [{"qty": 2, "name": "Llanowar Elves"}]}}))
        self.assertEqual((saved["id"], saved["changed"]), (deck_id, True))
        self.assertIn("| Llanowar Elves | 2 | 1 | **1** |", path.read_text(encoding="utf-8"))
        error = self.assertApiError(400, api.save_deck, self.body(
            "user2", id=deck_id, sha256=saved["sha256"], fields={"player": "user"}))
        self.assertIn("player", {b["field"] for b in error.extra["blocks"]})
        # Sleeves and deck boxes are the home's: a person may not set them at all (permissions), and the
        # refusal names no space (E10-S38).
        self.assertApiError(403, api.save_deck, self.body(
            "user2", id=deck_id, sha256=saved["sha256"], fields={"status": "built", "sleeves": "red"}),
            contains=permissions.ACCESSORIES_PRIVATE)
        error = self.assertApiError(400, lambda: self.create_user2s(fields={"player": "wife"}))
        self.assertEqual(error.extra["blocks"][0]["field"], "player")
        self.assertApiError(404, api.create_deck, self.body(title="X", kind="casual", space="user3"))
        self.assertApiError(400, api.create_deck, self.body(title="X", kind="casual", space=7))

    def test_who_changed_a_deck_is_told_only_to_someone_who_may_edit_it(self):
        # User2 may not see a home deck (E10-S30): a stale sha256 gets the 404 a missing deck gets, not a
        # 403 or a 409 naming who saved it.
        with access.using({"profile": "user2", "email": "", "remote": True}):
            error = self.assertApiError(404, api.save_deck, self.body("user2", id="casual/gruul-test",
                                                                      sha256="0" * 64))
            self.assertEqual((error.message, error.extra), ("No deck 'casual/gruul-test'", {}))
            self.assertApiError(404, api.update_tables, self.body("user2", decks=[
                {"id": "casual/table-test", "sha256": "0" * 64}]), contains="No deck 'casual/table-test'")

    def test_check_draft_counts_the_person_pool(self):
        answer = api.check_draft(self.body("user2", kind="casual", space="user2",
                                           lists={"target": {"Deck": [{"qty": 4, "name": "Llanowar Elves"}]}}))
        self.assertEqual(answer["owned"]["totals"]["missing"], 3)
        home = api.check_draft(self.body(kind="casual", lists={"target": {"Deck": [{"qty": 4,
                                                                                    "name": "Llanowar Elves"}]}}))
        self.assertLess(home["owned"]["totals"]["missing"], 3)       # home's five copies count there

    def test_a_person_deck_gets_no_accessories(self):
        self.create_user2s()
        from decklab.lib.api import accessories as accessories_api
        self.assertApiError(400, accessories_api._holder_id, "user2/casual/user2-elves", "holder")

    def test_a_person_wishlist_counts_their_own_collection(self):
        self.box.state.seed_wishlist("user2", [{"name": "Llanowar Elves", "set": "", "number": ""}])
        with access.viewing("user2"):                 # a wishlist is its owner's only
            entries = api.get_wishlist("user2")["entries"]
        self.assertEqual(entries[0]["have"], {"owned": 1, "on_the_way": 0})


class KitOrderTests(EditorTestCase):
    """The order of deck.save and kit.set in one save (saving._KitThenSave), with a stand-in kit.set
    that, like the real one, gives sleeves or a deck box only to a built deck."""

    def setUp(self):
        super().setUp()
        from decklab.lib import inventory
        from decklab.lib.inventory import ops_decks
        self.calls = []

        def kit_set(inv, *, holders, changes, owners=frozenset()):
            deck = inv.deck(holders[0]["id"])
            if holders[0]["expected"] is not None and deck.sha256 != holders[0]["expected"]:
                raise ops_decks.DeckRefused("changed", 409, "changed", [deck.id])
            parsed = ops_decks.parsed_deck(deck)
            self.calls.append(("kit.set", parsed.status, [(c["field"], c["value"]) for c in changes]))
            for change in changes:
                if change["value"] is not None and parsed.status != "built":
                    raise ops_decks.DeckRefused("Only a built deck has sleeves or a deck box", 400, "kit", [deck.id])
                (decks.set_sleeves if change["field"] == "sleeves" else decks.set_deck_box)(parsed, change["value"])
            return inv.with_deck(deck.replace(text=decks.render_deck_file(parsed))), inventory.Summary("kit")

        save = inventory._OPS["deck.save"]

        def deck_save(inv, **params):
            self.calls.append(("deck.save",))
            return save(inv, **params)
        patcher = mock.patch.dict(inventory._OPS, {"kit.set": kit_set, "deck.save": deck_save})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_making_a_deck_built_saves_it_then_chooses_its_kit(self):
        answer = self.save("casual/gruul-test", fields={"status": "built", "built_version": "owned",
                                                        "sleeves": "Green"})
        self.assertEqual(self.calls, [("deck.save",), ("kit.set", "built", [("sleeves", "Green")])])
        text = self.text("casual/gruul-test")
        self.assertIn("- **Status:** built", text)
        self.assertIn("- **Sleeves:** Green", text)
        self.assertEqual(answer["sha256"], self.sha("casual/gruul-test"))      # as stored

    def test_taking_a_deck_apart_clears_its_kit_first(self):
        self.save("casual/gruul-test", fields={"status": "built", "built_version": "owned", "sleeves": "Green"})
        self.calls.clear()
        answer = self.save("casual/gruul-test", fields={"status": "building"})
        self.assertEqual(self.calls, [("kit.set", "built", [("sleeves", None)]), ("deck.save",)])
        self.assertNotIn("Sleeves", self.text("casual/gruul-test"))
        self.assertEqual(answer["sha256"], self.sha("casual/gruul-test"))

    def test_a_kit_refusal_keeps_its_status(self):
        from decklab.lib.inventory import ops_decks

        def refuses(inv, **params):
            raise ops_decks.AccessoryRefusedLike("Those sleeves are User1's", 403, "kit", ["casual/gruul-test"])
        ops_decks.AccessoryRefusedLike = type("AccessoryRefusedLike", (ops_decks.DeckRefused,), {})
        self.addCleanup(delattr, ops_decks, "AccessoryRefusedLike")
        from decklab.lib import inventory
        with mock.patch.dict(inventory._OPS, {"kit.set": refuses}):
            self.assertApiError(403, lambda: self.save("casual/gruul-test", fields={
                "status": "built", "built_version": "owned", "sleeves": "Green"}), contains="User1's")


class FrozenSaveTests(ApiTestCase):
    """Every frozen copy of the real deck files, LF and CRLF, saved through
    the API: unchanged it stays byte for byte the same; with one card
    changed, only Deck Lab's parts change, the line endings stay, and the
    "Decklist changed" line appears. Each save that changes the deck is one
    deck.save; one that changes nothing saves nothing."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.box.magic / "decks")
        shutil.copytree(FIXTURES / "decks", self.box.magic / "decks")
        self.saves = []
        real = api.saving.inventory.apply

        def counted(op, *args, **kw):
            self.saves.append((op.kind, op.params["deck_id"]))
            return real(op, *args, **kw)

        # The other-decks check is covered above; these tests are about the deck's text.
        for patcher in (mock.patch.object(api.saving.inventory, "apply", side_effect=counted),
                        mock.patch.object(api.saving, "_stale_after", return_value=[])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def each(self, crlf):
        for path in sorted((self.box.magic / "decks").glob("*/*.md")):
            if crlf:
                path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
            yield f"{path.parent.name}/{path.stem}", path

    def save(self, deck_id, view, lists):
        fields = view["fields"]
        return api.save_deck(json.dumps({"profile": "matt", "id": deck_id, "sha256": view["sha256"],
                                         "lists": lists, "fields": fields}).encode("utf-8"))

    def check_both(self, crlf):
        found = 0
        for deck_id, path in self.each(crlf):
            found += 1
            with self.subTest(deck=deck_id, crlf=crlf):
                before = path.read_bytes()
                view = api.edit_view(deck_id)
                lists = {"target": view["lists"]["target"], "owned": view["lists"]["owned"]}
                answer = self.save(deck_id, view, lists)
                self.assertEqual((answer["changed"], answer["marked"]), (False, None))
                self.assertEqual(path.read_bytes(), before)

                line = lists["target"]["Deck"][0]
                line["qty"] = line["qty"] + 1 if line["qty"] < 99 else line["qty"] - 1
                answer = self.save(deck_id, view, lists)
                self.assertEqual((answer["changed"], answer["marked"]), (True, TODAY))
                after = path.read_bytes()
                if crlf:
                    self.assertNotIn(b"\n", after.replace(b"\r\n", b""))
                else:
                    self.assertNotIn(b"\r", after)
                old = decks.parse_deck(before, path.stem, path.parent.name)
                new = decks.parse_deck(after, path.stem, path.parent.name)
                self.assertEqual(prose(new), prose(old))
                self.assertEqual(new.changed_on, TODAY)
                self.assertEqual(new.fields, old.fields)
                self.assertEqual(new.owned, old.owned)
                expected = {s: [(l.quantity, l.name) for l in ls] for s, ls in old.target.items()}
                expected["Deck"][0] = (line["qty"], expected["Deck"][0][1])
                self.assertEqual({s: [(l.quantity, l.name) for l in ls] for s, ls in new.target.items()}, expected)
                self.assertEqual(sum(r.need for r in new.rows),
                                 sum(l.quantity for ls in new.target.values() for l in ls
                                     if not decks.is_basic_land(l.name)))
        self.assertEqual(found, 11)
        # Each save that changes its deck is one deck.save of it; one that changes nothing saves nothing.
        self.assertEqual(len(self.saves), 11)
        self.assertEqual({kind for kind, _ in self.saves}, {"deck.save"})
        self.assertEqual(len({deck_id for _, deck_id in self.saves}), 11)

    def test_lf_files(self):
        self.check_both(crlf=False)

    def test_crlf_files(self):
        self.check_both(crlf=True)


if __name__ == "__main__":
    unittest.main()
