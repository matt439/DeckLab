"""Tests for decklab.lib.tokens: reading and checking magic/tokens.csv, parsing
details, matching token cards against the tokens a deck makes, holders,
gaps, row uses, the cache, --check and the deck printout.

Each test builds a small magic/ tree in a temp folder, installs it as the
inventory (inventory.use(FileInventory(root))) and points decks and pool at
it. Tests that need card data build a small index from
fixtures/tokens_cards.jsonl (real Scryfall objects); the rest run with no
card index at all, as on a fresh clone.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_tokens
"""
import ast
import contextlib
import io
import json
import pkgutil
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, config, decks, inventory, pool, tokens
from decklab.lib.decks.decklist import DeckLine
from decklab.lib.inventory import rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.tokens import names as token_names

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = ",".join(tokens.FIELDS) + "\n"

# magic/tokens.csv as it was on 2026-10-09.
REAL_TOKENS = HEADER + """\
Angel,Angel,,,,,1,3/3,4/4,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Angel,Clue,,,,,4,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Angel,Spirit,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed; user wrote sprit; normalized to Spirit
Angel,The Monarch,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Cat,Phyrexian Goblin,,,,,2,lifelink; power/toughness and colour unconfirmed,,User-reported owned 2026-10-07; lifelink confirmed; printing and other characteristics unconfirmed
Cat Beast,Dragon,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Clue,Spirit,,,,,3,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Copy,Human,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Dog,Beast,,,,,1,,3/3,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Dog,Beast,,,,,1,,4/4,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Elf Warrior,Cat,,,,,1,,1/1; no lifelink; colour unconfirmed,User-reported owned 2026-10-07; Cat confirmed 1/1; only the Cat/Phyrexian Goblin Cats were identified as having lifelink; printing unconfirmed
Elf Warrior,Rat,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Food,Treasure,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Goblin,,,,,,1,1/1; printed pink (not a Magic colour),,User-reported owned 2026-10-09; manacat.com.au shop token; artist Chris 'Things' Bryan; single-sided verified (back is a manacat.com.au advertisement)
Insect,Goblin,,,,,1,1/1; flying; no deathtouch; colour unconfirmed,,User-reported owned 2026-10-07; Insect confirmed 1/1 with flying in response to deathtouch check; printing unconfirmed
Otter,Copy,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Rabbit,Rabbit,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed; one physical card represents only one Rabbit at a time
Soldier,Faerie,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Soldier,Rabbit,,,,,1,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Treasure,Goblin,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Zombie,Faerie,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Zombie,Goblin,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Zombie,The Monarch,,,,,2,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
Zombie,Zombie Knight,,,,,8,,,User-reported owned 2026-10-07; unspecified characteristics and printing unconfirmed
"""

RING_FRONT = ("colorless; Emblem; Your Ring-bearer is legendary and can't be blocked by creatures with greater "
              "power. / Whenever your Ring-bearer attacks, draw a card, then discard a card. / Whenever your "
              "Ring-bearer becomes blocked by a creature, that creature's controller sacrifices it at end of "
              "combat. / Whenever your Ring-bearer deals combat damage to a player, each opponent loses 3 life.")
RING_BACK = ("colorless; Card; As the Ring tempts you, you get an emblem named The Ring if you don't have one. "
             "Then your emblem gains its next ability and you choose a creature you control to become or remain "
             "your Ring-bearer. / • The Ring can tempt you even if you don't control a creature. / • The Ring "
             "gains its abilities in order from top to bottom. Once it gains an ability, it has that ability for "
             "the rest of the game. / • Each time the Ring tempts you, you must choose a creature if you control "
             "one. / • Each player can have only one emblem named The Ring and only one Ring-bearer at a time.")
ELEMENTAL = ("0/1; red; Token Creature — Elemental; At the beginning of your upkeep, sacrifice this creature and "
             "return target card named Rekindling Phoenix from your graveyard to the battlefield. It gains haste "
             "until end of turn.")
AXE = ("colorless; Token Artifact — Equipment; Equipped creature gets +1/+0. / Equip {2} ({2}: Attach to target "
       "creatre you control. Equip only as a sorcery.)")
_REVERSE = "reverse face unconfirmed; check physical pairing on arrival"


def _payload_row(front, set_code, number, quantity, details, back="", back_number="", back_details="",
                 notes=_REVERSE):
    return {"front": front, "back": back, "set": set_code, "front_collector_number": number,
            "back_collector_number": back_number, "finish": "nonfoil", "quantity": str(quantity),
            "front_details": details, "back_details": back_details, "notes": notes}


# magic/orders/tokens/2026-10-07-shop-a.csv as it was on 2026-10-09.
MTGMATE = [
    _payload_row("Fish", "tblb", "7", 2, "1/1; blue; Token Creature — Fish"),
    _payload_row("Phyrexian Beast", "tfdc", "11", 2, "4/4; green; Token Creature — Phyrexian Beast"),
    _payload_row("Axe", "thob", "10", 5, AXE),
    _payload_row("Elf", "thob", "8", 3, "1/1; green; Token Creature — Elf"),
    _payload_row("The Ring", "tltr", "H13", 1, RING_FRONT, back="The Ring Tempts You", back_number="H13",
                 back_details=RING_BACK, notes=""),
    _payload_row("Elemental", "tncc", "18", 1, ELEMENTAL),
    _payload_row("Ooze", "tncc", "25", 2, "1/1; green; Token Creature — Ooze"),
    _payload_row("Insect", "ttdc", "23", 2, "1/1; green; Token Creature — Insect; Flying, deathtouch"),
]
ORDER = "2026-10-07-shop-a"
INCOMING = [{"order": ORDER, "component": "tokens", "path": "magic/orders/tokens/2026-10-07-shop-a.csv",
             "rows": MTGMATE}]

# Oracle ids in fixtures/tokens_cards.jsonl.
RABBIT = "fee35fc4-a5b5-4c2c-8c6a-62dad166ea72"
MONARCH = "7c934091-1bc7-4458-acef-fdac62ec3df1"
ANGEL = "40c64f08-ab2f-4933-8e0e-d1a1c729008f"
SPIRIT = "dc4e2134-f0c2-49aa-9ea3-ebf83af1445c"
INSECT = "b4f3e7ab-68fd-4613-ae6d-79ca43343d37"
CAT = "5ae6251d-cef9-4fb7-bdcd-e870a062f042"
LIFELINK_CAT = "65742c00-2809-4085-a950-8f93845c03d2"
ZOMBIE = "ddc8c973-c31e-463f-be45-f3fa7d632362"
ZOMBIE_ROGUE = "b5720338-083d-484c-bf45-cdc64b09be4e"
FISH = "bdb03306-355c-41e5-96bc-f60483e59b2a"
COPY = "88c78601-87f0-45e7-b2e0-e7ffcfb1cb70"
RING = "98737456-ac2a-420d-aa0e-778ba3a22cec"
TREASURE = "3c549374-6c37-42e0-8d88-a8555d46732d"


def deck_md(title, status="building", deck="1 Hornet Queen\n", sideboard="", owned=None, built_version=None):
    lines = [f"# {title}", "", "- **Format:** Casual 60-card, 1v1", "- **Played by:** either",
             f"- **Status:** {status}"]
    if built_version:
        lines.append(f"- **Built version:** {built_version}")
    block = "Deck\n" + deck + (f"\nSideboard\n{sideboard}" if sideboard else "")
    text = "\n".join(lines) + f"\n\n## Decklist\n\n```\n{block}```\n"
    if owned is not None:
        text += f"\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n{owned}```\n"
    return text


def lines(*names, section="Deck"):
    return {section: [DeckLine(1, n) for n in names]}


class TokensTestCase(unittest.TestCase):
    """A temp repo with magic/ (no tokens.csv yet, an empty status.csv, no
    order records), installed as the inventory (self.inventory), and no card
    index."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.root = root
        self.magic = root / "magic"
        for sub in ("products", "decks/casual", "decks/commander", "orders/records", "orders/tokens"):
            (self.magic / sub).mkdir(parents=True)
        self.inventory = FileInventory(root)
        self.addCleanup(inventory.use(self.inventory))
        for target, name, value in (
                (config, "REPO", root),
                (decks, "REPO", root),
                (decks, "DECKS_DIR", self.magic / "decks"),
                (pool, "REPO", root),
                (cards, "INDEX_FILE", root / "no-index.json.gz"),
                (cards, "_index", None)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The pool and the product decks read the inventory (decklab/lib/inventory): this tree's.
        self.addCleanup(inventory.use(FileInventory(root)))
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n")

    def write(self, rel, text):
        path = self.magic / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return path

    def tokens_csv(self, text):
        return self.write("tokens.csv", text)

    def deck(self, slug, *args, kind="casual", **kwargs):
        self.write(f"decks/{kind}/{slug}.md", deck_md(*args, **kwargs))

    def record(self, order=ORDER, status="pending", payload=None, kind="tokens"):
        """An order record with one component, and its payload CSV."""
        folder = "magic/orders/tokens" if kind == "tokens" else "magic/orders"
        if status != "pending":
            folder += f"/{status}"
        rel = f"{folder}/{order}.csv"
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        rows = MTGMATE if payload is None else payload
        if isinstance(rows, str):
            (self.root / rel).write_text(rows, encoding="utf-8")
        else:
            (self.root / rel).write_bytes(rules.csv_bytes(rows, rules.TOKEN_FIELDS))
        record = {"version": 1, "id": order, "seller": "MTGMate", "ordered_on": "2026-10-07", "sources": [],
                  "notes": "", "components": [{"id": kind, "kind": kind, "path": rel, "status": status,
                                               "received_on": "2026-10-08" if status == "received" else "",
                                               "checks": []}]}
        self.write(f"orders/records/{order}.json", json.dumps(record))
        return rel


class IndexTestCase(TokensTestCase):
    """TokensTestCase with a card index built from fixtures/tokens_cards.jsonl."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(cards, "_index", self.loaded)
        patcher.start()
        self.addCleanup(patcher.stop)

    def real(self):
        self.tokens_csv(REAL_TOKENS)
        return tokens.read()

    def need(self, result, key):
        found = [n for n in result["needs"] if n["key"] == key]
        self.assertEqual(len(found), 1, [n["key"] for n in result["needs"]])
        return found[0]

    def makes(self, names, inv=None, incoming=(), section="Deck"):
        inv = self.real() if inv is None else inv
        return tokens.deck_tokens(lines(*names, section=section), inv, list(incoming))


# ------------------------------------------------------------------ reading

class ReadTests(TokensTestCase):
    def test_no_file_is_an_empty_inventory(self):
        inv = tokens.read()
        self.assertEqual((inv.rows, inv.sha256, inv.problems, inv.sorted), ([], None, [], True))
        self.assertEqual(tokens.read(strict=True).rows, [])

    def test_bom_and_crlf_are_read_and_quantity_stays_text(self):
        canonical = HEADER + "Rabbit,Rabbit,,,,,2,,,\nDog,Beast,,,,,1,,3/3,a note\n"
        self.tokens_csv(("﻿" + canonical).replace("\n", "\r\n"))
        inv = tokens.read(strict=True)
        self.assertEqual([(r["front"], r["quantity"], r["back_details"]) for r in inv.rows],
                         [("Rabbit", "2", ""), ("Dog", "1", "3/3")])
        # The sha is the file's as rendered (canonical: no BOM, LF), whichever backend holds it.
        self.assertEqual(inv.sha256, __import__("hashlib").sha256(canonical.encode("utf-8")).hexdigest())
        self.assertEqual(inv.lines, [2, 3])
        self.assertFalse(inv.sorted)
        self.assertEqual(inv.problems, [])

    def test_sorted_follows_the_receipt_sort_key(self):
        self.tokens_csv(HEADER + "Dog,Beast,,,,,1,,,\nRabbit,Rabbit,,,,,2,,,\n")
        self.assertTrue(tokens.read().sorted)
        self.tokens_csv(HEADER + "Axe,,thob,10,,nonfoil,1,,,single-sided verified\nRabbit,Rabbit,,,,,2,,,\n")
        self.assertFalse(tokens.read().sorted)      # a blank set sorts before any set

    def test_the_real_file_reads_strictly_and_sorted(self):
        self.tokens_csv(REAL_TOKENS)
        inv = tokens.read(strict=True)
        self.assertEqual(len(inv.rows), 24)
        self.assertTrue(inv.sorted)
        goblin = next(r for r in inv.rows if r["front"] == "Goblin")
        self.assertEqual(goblin["back"], "")

    def test_columns_in_another_order_are_read_leniently_only(self):
        fields = list(reversed(tokens.FIELDS))
        self.tokens_csv(",".join(fields) + "\n" + "note,,,1,,,,,Rabbit,Rabbit\n")
        inv = tokens.read()
        self.assertEqual((inv.rows[0]["front"], inv.rows[0]["quantity"], inv.rows[0]["notes"]),
                         ("Rabbit", "1", "note"))
        self.assertIn("columns aren't in the standard order", inv.problems[0])
        with self.assertRaises(tokens.TokensError):
            tokens.read(strict=True)

    def test_the_old_six_column_header_reads_leniently_with_a_problem(self):
        self.tokens_csv("front,back,quantity,front_details,back_details,notes\nDog,Beast,2,,3/3,\n")
        inv = tokens.read()
        self.assertEqual(inv.rows, [{**{k: "" for k in tokens.FIELDS}, "front": "Dog", "back": "Beast",
                                     "quantity": "2", "back_details": "3/3"}])
        self.assertEqual(inv.problems, ["The home token cards lack the printing columns; fix the header by hand "
                                        "before the Tokens page can save"])
        with self.assertRaisesRegex(tokens.TokensError, r"^The home token cards' columns must be .*; it can't be "
                                                         r"changed until that's put right$"):
            tokens.read(strict=True)

    def test_an_unknown_header_reads_no_rows(self):
        self.tokens_csv("name,quantity\nDog,1\n")
        inv = tokens.read()
        self.assertEqual(inv.rows, [])
        self.assertIn("The home token cards' columns must be", inv.problems[0])

    def test_bad_rows_are_skipped_with_their_line_or_refused_strictly(self):
        self.tokens_csv(HEADER + "Dog,Beast,,,,,1,,,\n"
                        + "Cat,,,,,,1,,,\"two\nlines\"\n"          # a multi-line note
                        + "\n"
                        + ",Beast,,,,,1,,,\n"
                        + "Rat,,,,,,0,,,\n"
                        + "Elf,,TBLB,1,,,1,,,\n"
                        + "Ooze,,,,,shiny,1,,,\n"
                        + "Too,few\n"
                        + "Zombie,,,,,,1,,,\n")
        inv = tokens.read()
        self.assertEqual([r["front"] for r in inv.rows], ["Dog", "Zombie"])
        self.assertEqual(inv.lines, [2, 11])
        # E11-S12: a row it leaves out is named by the listed row before it (tokens list numbers only
        # the rows it reads), never by the old file's line.
        self.assertEqual(inv.problems, [
            "A row after row 1 of the home token cards: notes must be one line",
            "A row after row 1 of the home token cards: tokens need a front name and positive physical quantity",
            "A row after row 1 of the home token cards: tokens need a front name and positive physical quantity",
            "A row after row 1 of the home token cards: invalid lowercase token set",
            "A row after row 1 of the home token cards: invalid token finish",
            "A row after row 1 of the home token cards: 2 values, not 10"])
        with self.assertRaises(tokens.TokensError) as caught:
            tokens.read(strict=True)
        self.assertEqual(str(caught.exception),
                         "A row after row 1 of the home token cards: notes must be one line; it can't be changed until "
                         "that's put right")

    def test_a_handed_in_file_keeps_its_line_and_the_inventory_its_listed_row(self):
        # E11-S12: a file the user hands in is named with its line, as written; the token cards
        # name the row they leave out by the listed row before it.
        path = self.tokens_csv(HEADER + "Dog,Beast,,,,,1,,,\n,Beast,,,,,1,,,\n")
        with self.assertRaises(ValueError) as theirs:          # how a receipt reads a token payload
            with path.open(encoding="utf-8-sig", newline="") as stream:
                found = rules.parse_csv(stream, rules.TOKEN_FIELDS, str(path))
            with path.open(encoding="utf-8-sig", newline="") as stream:
                for line, row in zip(rules.record_lines(stream), found):
                    rules.validate_token_row(row, f"{path} line {line}")
        with self.assertRaises(tokens.TokensError) as ours:
            tokens.read(strict=True)
        self.assertIn("tokens.csv line 3: tokens need a front name", str(theirs.exception))
        self.assertTrue(str(ours.exception).startswith("A row after row 1 of the home token cards: tokens need a "
                                                       "front name"), str(ours.exception))


class RowTests(unittest.TestCase):
    ROW = {"front": "Zombie", "back": "Zombie Knight", "set": "", "front_collector_number": "",
           "back_collector_number": "", "finish": "", "quantity": "8", "front_details": "",
           "back_details": "", "notes": ""}

    def row(self, **changes):
        return {**self.ROW, **changes}

    def test_a_good_row_is_cleaned(self):
        row = tokens.validate_row(self.row(front="  Zombie ​", notes="two\nlines", quantity=3, set="TLTR",
                                           front_collector_number="H13", finish="Nonfoil", extra="ignored"))
        self.assertEqual(list(row), tokens.FIELDS)
        self.assertEqual((row["front"], row["notes"], row["quantity"], row["set"], row["finish"]),
                         ("Zombie", "two lines", "3", "tltr", "nonfoil"))
        self.assertEqual(tokens.validate_row(self.row(quantity=" 08 "))["quantity"], "8")

    def test_bad_rows_are_refused_with_readable_words(self):
        for changes, words in (
                ({"front": " "}, "Tokens need a front name and positive physical quantity"),
                ({"quantity": 0}, "Quantity 0 must be a whole number from 1 to 9999"),
                ({"quantity": "10000"}, "Quantity '10000' must be"),
                ({"quantity": "1.5"}, "must be a whole number"),
                ({"quantity": True}, "must be a whole number"),
                ({"quantity": None}, "must be a whole number"),
                ({"finish": "shiny"}, "Invalid token finish"),
                ({"set": "t-ltr"}, "Invalid lowercase token set"),
                ({"front_collector_number": "H 13"}, "Invalid token collector number"),
                ({"front": "Z" * 81}, "front is longer than 80 characters"),
                ({"back": "Z" * 81}, "back is longer than 80 characters"),
                ({"front_collector_number": "1" * 17}, "longer than 16"),
                ({"front_details": "d" * 301}, "front_details is longer than 300 characters"),
                ({"notes": "n" * 501}, "notes is longer than 500 characters")):
            with self.subTest(changes=changes), self.assertRaises(ValueError) as caught:
                tokens.validate_row(self.row(**changes))
            self.assertIn(words.lower(), str(caught.exception).lower())
            self.assertNotIn("\0", str(caught.exception))

    def test_csv_bytes_sorts_with_lf_and_no_bom(self):
        rows = [self.row(front="Zombie"), self.row(front="Angel", back="", quantity=1),
                self.row(front="Fish", back="", set="tblb", front_collector_number="7")]
        data = tokens.csv_bytes(rows)
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        text = data.decode("utf-8").splitlines()
        self.assertEqual(text[0], HEADER.strip())
        self.assertEqual([t.split(",")[0] for t in text[1:]], ["Angel", "Zombie", "Fish"])


# ------------------------------------------------------------------ details

class ParseDetailsTests(TokensTestCase):
    """Every details string in tokens.csv and the MTGMate payload on 2026-10-09, and some more."""

    CASES = (
        ("", None, None, set(), set(), set(), []),
        ("3/3", "3/3", None, set(), set(), set(), []),
        ("4/4", "4/4", None, set(), set(), set(), []),
        ("1/1", "1/1", None, set(), set(), set(), []),
        ("lifelink; power/toughness and colour unconfirmed", None, None, {"lifelink"}, set(),
         {"pt", "colors"}, []),
        ("1/1; no lifelink; colour unconfirmed", "1/1", None, set(), {"lifelink"}, {"colors"}, []),
        ("1/1; printed pink (not a Magic colour)", "1/1", None, set(), set(), set(),
         ["printed pink (not a Magic colour)"]),
        ("1/1; flying; no deathtouch; colour unconfirmed", "1/1", None, {"flying"}, {"deathtouch"},
         {"colors"}, []),
        ("1/1; blue; Token Creature — Fish", "1/1", {"blue"}, set(), set(), set(), ["Token Creature — Fish"]),
        ("4/4; green; Token Creature — Phyrexian Beast", "4/4", {"green"}, set(), set(), set(),
         ["Token Creature — Phyrexian Beast"]),
        (AXE, None, set(), set(), set(), set(), ["Token Artifact — Equipment", AXE.split("; ", 2)[2]]),
        ("1/1; green; Token Creature — Elf", "1/1", {"green"}, set(), set(), set(), ["Token Creature — Elf"]),
        (RING_FRONT, None, set(), set(), set(), set(), ["Emblem", RING_FRONT.split("; ", 2)[2]]),
        (RING_BACK, None, set(), set(), set(), set(), ["Card", RING_BACK.split("; ", 2)[2]]),
        # "haste" inside the Elemental's rules text isn't a keyword the token has.
        (ELEMENTAL, "0/1", {"red"}, set(), set(), set(),
         ["Token Creature — Elemental", ELEMENTAL.split("; ", 3)[3]]),
        ("1/1; green; Token Creature — Ooze", "1/1", {"green"}, set(), set(), set(), ["Token Creature — Ooze"]),
        ("1/1; green; Token Creature — Insect; Flying, deathtouch", "1/1", {"green"}, {"flying", "deathtouch"},
         set(), set(), ["Token Creature — Insect"]),
        # Beyond today's files.
        ("*/*; Red and White", "*/*", {"red", "white"}, set(), set(), set(), []),
        ("x/X; white, blue", "X/X", {"white", "blue"}, set(), set(), set(), []),
        ("colourless", None, set(), set(), set(), set(), []),
        ("Colorless", None, set(), set(), set(), set(), []),
        ("First strike, no trample; ward {2}; toxic 1", None, None, {"first strike", "ward", "toxic"},
         {"trample"}, set(), []),
        ("abilities unconfirmed", None, None, set(), set(), {"keywords"}, []),
        ("unknown", None, None, set(), set(), {"pt", "colors", "keywords"}, []),
        ("printing unconfirmed", None, None, set(), set(), set(), ["printing unconfirmed"]),
        ("flying, swims well", None, None, set(), set(), set(), ["flying, swims well"]),
        ("no idea", None, None, set(), set(), set(), ["no idea"]),
    )

    def test_each_string(self):
        for text, pt, colors, has, lacks, unknown, extra in self.CASES:
            with self.subTest(text=text[:40]):
                facts = tokens.parse_details(text)
                self.assertEqual((facts.pt, facts.colors, facts.has, facts.lacks, facts.unknown, facts.extra),
                                 (pt, colors, has, lacks, unknown, extra))

    def test_the_real_strings_are_all_covered(self):
        known = {case[0] for case in self.CASES}
        self.tokens_csv(REAL_TOKENS)
        strings = {r[k] for r in tokens.read().rows + MTGMATE for k in ("front_details", "back_details")}
        self.assertEqual(strings - known, set())


class DetailsMistakesTests(TokensTestCase):
    """The parts parse_details doesn't read that look like mistakes, and the notes it must leave alone."""

    CASES = (
        ("4/4 white flying", [("4/4 white flying", "separate them with ';' (4/4; white; flying)",
                               "4/4; white; flying")]),
        ("white 4/4", [("white 4/4", "separate them with ';' (4/4; white)", "4/4; white")]),
        ("white, flying", [("white, flying", "separate them with ';' (white; flying)", "white; flying")]),
        ("4/4 green and blue", [("4/4 green and blue", "separate them with ';' (4/4; blue and green)",
                                 "4/4; blue and green")]),
        ("white, no lifelink 2/2", [("white, no lifelink 2/2", "separate them with ';' (2/2; white; no lifelink)",
                                     "2/2; white; no lifelink")]),
        ("1/1 white flying elf", [("1/1 white flying elf", "separate them with ';'", None)]),
        ("whte", [("whte", "did you mean white?", "white")]),
        ("flyng", [("flyng", "did you mean flying?", "flying")]),
        ("deathtuch", [("deathtuch", "did you mean deathtouch?", "deathtouch")]),
        ("frist strike", [("frist strike", "did you mean first strike?", "first strike")]),
        ("4/4; whte; flyng", [("whte", "did you mean white?", "white"), ("flyng", "did you mean flying?", "flying")]),
        ("4/4 whte flyng", [("4/4 whte flyng", "did you mean 4/4; white; flying?", "4/4; white; flying")]),
        ("no deathtuch", [("no deathtuch", "did you mean no deathtouch?", "no deathtouch")]),
        ("flying trample", [("flying trample", "list them with commas (flying, trample)", "flying, trample")]),
        ("4/4.", [("4/4.", "write it as 4/4", "4/4")]),
        # Read already, or notes that are meant to be kept.
        ("blank", []),
        ("while", []),
        ("frist", []),          # half of a keyword isn't one
        ("４/４", []),           # only ASCII digits are a P/T, as on the page
        ("4/4; white; flying", []),
        ("4/4; White; Flying", []),
        ("Token Creature — Phyrexian Beast", []),
        ("Token Artifact — Food", []),
        ("printed pink (not a Magic colour)", []),
        ("single-sided verified", []),
        ("Card", []),
        ("Clue", []),
        ("Emblem", []),
        ("flying, swims well", []),
        ("no idea", []),
        ("printing unconfirmed", []),
        ("Flying. When this creature dies, draw a card.", []),
    )

    def test_each_string(self):
        for text, expected in self.CASES:
            with self.subTest(text=text):
                self.assertEqual([(m.part, m.message, m.rewrite) for m in tokens.details_mistakes(text)], expected)

    def test_the_real_strings_have_none(self):
        self.tokens_csv(REAL_TOKENS)
        strings = {r[k] for r in tokens.read().rows + MTGMATE for k in ("front_details", "back_details")}
        strings |= {case[0] for case in ParseDetailsTests.CASES}
        self.assertEqual({s: tokens.details_mistakes(s) for s in strings if tokens.details_mistakes(s)}, {})

    def test_parse_details_is_unchanged(self):
        self.assertEqual(tokens.parse_details("4/4 white flying").extra, ["4/4 white flying"])
        self.assertEqual(tokens.parse_details("4/4; whte").pt, "4/4")


class IndexKeywordTests(IndexTestCase):
    def test_token_keywords_from_the_index_count_too(self):
        # Coruscation Mage's offspring token text isn't a keyword; the Spirit's Flying is, and is
        # in the fixed list anyway. With the index, keywords of tokens are added.
        self.assertIn("flying", tokens._keywords())
        self.assertEqual(tokens.parse_details("Flying").has, {"flying"})


# ------------------------------------------------------------------ names

class CheckNamesTests(IndexTestCase):
    ROW = RowTests.ROW

    def test_names_are_made_exact(self):
        row, warnings = tokens.check_names({**self.ROW, "front": "the monarch", "back": "SPIRIT"})
        self.assertEqual((row["front"], row["back"], warnings), ("The Monarch", "Spirit", []))
        row, _ = tokens.check_names({**self.ROW, "front": "the ring // the ring tempts you", "back": ""})
        self.assertEqual(row["front"], "The Ring // The Ring Tempts You")

    def test_an_unknown_name_suggests_one(self):
        with self.assertRaises(ValueError) as caught:
            tokens.check_names({**self.ROW, "front": "Sprit", "back": ""})
        self.assertEqual(str(caught.exception),
                         "'Sprit' isn't a token, emblem or reminder name on Scryfall. Did you mean Spirit?")
        with self.assertRaisesRegex(ValueError, r"^'Qwxzv' isn't a token, emblem or reminder name on Scryfall\.$"):
            tokens.check_names({**self.ROW, "front": "Qwxzv", "back": ""})

    def test_a_printing_must_have_the_face(self):
        ring = {**self.ROW, "front": "The Ring", "back": "The Ring Tempts You", "set": "tltr",
                "front_collector_number": "H13", "back_collector_number": "H13"}
        self.assertEqual(tokens.check_names(ring)[0]["front"], "The Ring")
        with self.assertRaisesRegex(ValueError, r"^tltr H13 is The Ring, not Spirit$"):
            tokens.check_names({**ring, "front": "Spirit"})
        with self.assertRaisesRegex(ValueError, r"^tltr H13 is The Ring Tempts You, not Angel$"):
            tokens.check_names({**ring, "back": "Angel"})
        with self.assertRaisesRegex(ValueError, r"^tblb 7 is Fish, not Angel$"):
            tokens.check_names({**self.ROW, "front": "Angel", "back": "", "set": "tblb",
                                "front_collector_number": "7"})
        with self.assertRaisesRegex(ValueError, "isn't a token, emblem or reminder printing"):
            tokens.check_names({**self.ROW, "front": "Fish", "back": "", "set": "fdn",
                                "front_collector_number": "15"})


class NoIndexTests(TokensTestCase):
    def test_names_are_unchecked_without_card_data(self):
        row = {**RowTests.ROW, "front": "Sprit"}
        self.assertEqual(tokens.check_names(row), (row, [tokens.NAMES_UNCHECKED]))

    def test_deck_tokens_needs_the_card_data(self):
        with self.assertRaises(RuntimeError):
            tokens.deck_tokens(lines("Hornet Queen"), tokens.read(), [])
        with self.assertRaises(RuntimeError):
            tokens.cached_deck_tokens("casual/x", "target", lines("Hornet Queen"), tokens.read(), [])

    def test_an_older_index_is_reported_as_runtime_error(self):
        with mock.patch.object(cards, "_get", side_effect=RuntimeError("older index format")):
            with self.assertRaisesRegex(RuntimeError, "older"):
                tokens.deck_tokens(lines("Hornet Queen"), tokens.read(), [])


# ------------------------------------------------------------------ matching

class MatchFaceTests(IndexTestCase):
    def need(self, oracle_id, maker="Maker"):
        need = tokens._need(cards.token(oracle_id))
        need["made_by"] = [{"name": maker, "quantity": 1, "section": "Deck"}]
        return need

    def row(self, front, back="", details="", back_details="", **changes):
        return {**RowTests.ROW, "front": front, "back": back, "front_details": details,
                "back_details": back_details, **changes}

    def test_a_known_printing_comes_first(self):
        fish = self.need(FISH)
        row = self.row("Fish", details="3/3; red", set="tblb", front_collector_number="7")
        self.assertEqual(tokens.match_face(fish, "Fish", "3/3; red", row), ("exact", []))
        insect = self.need(INSECT, "Hornet Queen")
        row = self.row("Insect", set="tblb", front_collector_number="7")
        self.assertEqual(tokens.match_face(insect, "Insect", "", row),
                         ("differs", ["tblb 7 is a 1/1 blue Fish; this Insect is 1/1 green with deathtouch, "
                                      "flying"]))

    def test_pt_colour_and_keywords_that_differ(self):
        insect = self.need(INSECT, "Hornet Queen")
        cases = (
            ("3/3; green; flying, deathtouch", ["recorded 3/3; this token is 1/1"]),
            ("1/1; colourless; flying, deathtouch", ["recorded colourless; this token is green"]),
            ("1/1; green; flying; no deathtouch", ["your card says no deathtouch; Hornet Queen's Insect has deathtouch"]),
            ("1/1; green; flying, deathtouch, lifelink",
             ["recorded lifelink; Hornet Queen's Insect has deathtouch, flying"]),
        )
        for details, why in cases:
            with self.subTest(details=details):
                self.assertEqual(tokens.match_face(insect, "Insect", details, self.row("Insect")),
                                 ("differs", why))
        cat = self.need(CAT, "Prideful Parent")
        self.assertEqual(tokens.match_face(cat, "Cat", "lifelink", self.row("Cat")),
                         ("differs", ["recorded lifelink; Prideful Parent's Cat has none"]))

    def test_agrees_only_when_every_aspect_is_recorded(self):
        insect = self.need(INSECT)
        self.assertEqual(tokens.match_face(insect, "Insect", "1/1; green; flying, deathtouch", self.row("Insect")),
                         ("agrees", []))
        self.assertEqual(tokens.match_face(insect, "Insect", "1/1; flying", self.row("Insect")),
                         ("check", ["colour and deathtouch not recorded"]))
        self.assertEqual(tokens.match_face(insect, "Insect", "1/1; green; flying, deathtouch; colour unconfirmed",
                                           self.row("Insect")), ("check", ["colour not recorded"]))
        treasure = self.need(TREASURE)     # no P/T: never compared
        self.assertEqual(tokens.match_face(treasure, "Treasure", "colourless", self.row("Treasure")),
                         ("agrees", []))
        self.assertEqual(tokens.match_face(treasure, "Treasure", "3/3", self.row("Treasure")),
                         ("check", ["colour not recorded"]))

    def test_notes_never_change_the_verdict(self):
        insect = self.need(INSECT)
        row = self.row("Insect", notes="printing unconfirmed; unspecified characteristics")
        self.assertEqual(tokens.match_face(insect, "Insect", "1/1; green; flying, deathtouch", row), ("agrees", []))

    def two_tokens(self, faces, keywords):
        """Patch in a printing "set 1" that carries two different tokens, with its own oracle id."""
        entry = {"name": " // ".join(f["name"] for f in faces), "kind": "token", "layout": "double_faced_token",
                 "power": faces[0]["power"], "toughness": faces[0]["toughness"], "colors": faces[0]["colors"],
                 "keywords": keywords, "faces": faces, "face_names": [f["name"] for f in faces], "id": "two"}
        real_token, real_at = cards.token, token_names._faces_at
        for target, name, value in (
                (cards, "token", lambda oracle_id: dict(entry) if oracle_id == "two" else real_token(oracle_id)),
                (token_names, "_faces_at", lambda s, n: ("two", entry["face_names"], entry["name"])
                 if (s, n) == ("set", "1") else real_at(s, n))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_printing_of_two_tokens_matches_by_its_face(self):
        treasure_face = {"name": "Treasure", "type_line": "Token Artifact — Treasure", "power": None,
                         "toughness": None, "colors": [], "text": "{T}, Sacrifice this token: Add one mana of any color."}
        self.two_tokens([{"name": "Vampire", "type_line": "Token Creature — Vampire", "power": "1",
                          "toughness": "1", "colors": ["W"], "text": "Lifelink"}, treasure_face], ["Lifelink"])
        row = self.row("Vampire", "Treasure", "1/1; white; lifelink", "colourless", set="set",
                       front_collector_number="1", back_collector_number="1")
        self.assertEqual(tokens.match_face(self.need(TREASURE), "Treasure", "colourless", row), ("agrees", []))
        self.assertEqual(tokens._best(self.need(TREASURE), row)[:3], ("back", "Treasure", "agrees"))

    def test_a_printing_of_two_tokens_differs_by_its_face(self):
        self.two_tokens([{"name": "Insect", "type_line": "Token Creature — Insect", "power": "1", "toughness": "1",
                          "colors": ["G"], "text": "Flying"},
                         {"name": "Treasure", "type_line": "Token Artifact — Treasure", "power": None,
                          "toughness": None, "colors": [], "text": ""}], ["Flying"])
        row = self.row("Insect", "Treasure", set="set", front_collector_number="1", back_collector_number="1")
        self.assertEqual(tokens.match_face(self.need(INSECT, "Hornet Queen"), "Insect", "", row),
                         ("differs", ["the Insect on set 1 is a 1/1 green Insect with flying; this Insect is "
                                      "1/1 green with deathtouch, flying"]))

    def test_a_back_face_of_a_double_faced_need(self):
        ring = self.need(RING)
        row = self.row("The Ring", "The Ring Tempts You", "colourless", "colourless")
        self.assertEqual(tokens.match_face(ring, "The Ring Tempts You", "colourless", row), ("agrees", []))


class DeckTokensTests(IndexTestCase):
    """The worked examples in the plan, against today's tokens.csv and the MTGMate payload."""

    def test_hornet_queens_insect_differs_and_has_two_on_the_way(self):
        result = self.makes(["Hornet Queen"], incoming=INCOMING)
        insect = self.need(result, INSECT)
        self.assertEqual(insect["state"], "differs")
        self.assertEqual(insect["words"], "Different token: your card says no deathtouch; Hornet Queen's Insect "
                                          "has deathtouch · 2 on the way")
        self.assertEqual(insect["cards"], [])
        self.assertEqual([(s["front"], s["back"], s["side"], s["quantity"]) for s in insect["stand_ins"]],
                         [("Insect", "Goblin", "front", 1)])
        self.assertEqual(insect["incoming"], [{"order": ORDER, "front": "Insect", "back": "", "quantity": 2}])
        self.assertEqual((insect["usable"], insect["on_the_way"]), (0, 2))
        self.assertEqual((insect["pt"], insect["colors"], insect["image"]), ("1/1", ["G"], "/img/tc20/13/small"))
        self.assertEqual(insect["made_by"], [{"name": "Hornet Queen", "quantity": 1, "section": "Deck"}])
        without = self.need(self.makes(["Hornet Queen"]), INSECT)
        self.assertNotIn("on the way", without["words"])

    def test_prideful_parents_cat_is_check(self):
        cat = self.need(self.makes(["Prideful Parent"]), CAT)
        self.assertEqual(cat["state"], "check")
        self.assertEqual([(c["front"], c["back"], c["side"], c["verdict"], c["why"]) for c in cat["cards"]],
                         [("Elf Warrior", "Cat", "back", "check", ["colour not recorded"])])
        self.assertEqual([(s["front"], s["why"]) for s in cat["stand_ins"]],
                         [("Cat", ["recorded lifelink; Prideful Parent's Cat has none"])])
        self.assertEqual(cat["words"], "Have 1 card with a Cat face; colour not recorded")

    def test_regal_caracals_cat_has_lifelink(self):
        cat = self.need(self.makes(["Regal Caracal"]), LIFELINK_CAT)
        self.assertEqual(cat["state"], "check")
        self.assertEqual([(c["front"], c["verdict"], c["why"]) for c in cat["cards"]],
                         [("Cat", "check", ["P/T and colour not recorded"])])
        self.assertEqual(cat["words"], "Have 2 cards with a Cat face; P/T and colour not recorded")

    def test_a_double_sided_card_counts_once(self):
        self.tokens_csv(HEADER + "Rabbit,Rabbit,,,,,2,,,\n")
        rabbit = self.need(self.makes(["Hare Apparent"], tokens.read()), RABBIT)
        self.assertEqual((rabbit["usable"], len(rabbit["cards"])), (2, 1))
        self.assertEqual(rabbit["words"], "Have 2 cards with a Rabbit face; P/T and colour not recorded")

    def test_court_of_grace_and_the_monarch_shared_with_a_zombie(self):
        result = self.makes(["Court of Grace", "Army of the Damned"])
        monarch = self.need(result, MONARCH)
        self.assertEqual(monarch["kind"], "reminder")
        self.assertEqual(monarch["state"], "check")
        self.assertEqual([(c["front"], c["back"], c["side"], c["also_for"]) for c in monarch["cards"]],
                         [("Angel", "The Monarch", "back", ["Angel"]),
                          ("Zombie", "The Monarch", "back", ["Zombie"])])
        self.assertEqual(monarch["words"], "Have 3 cards with The Monarch face; colour not recorded")
        self.assertEqual(self.need(result, ANGEL)["state"], "check")
        self.assertEqual(self.need(result, SPIRIT)["state"], "check")
        # Reminders sort after tokens in the same state.
        checks = [n["kind"] for n in result["needs"] if n["state"] == "check"]
        self.assertEqual(checks, sorted(checks, key=lambda k: ("token", "emblem", "reminder").index(k)))

    def test_gisas_zombie_rogue_has_none_and_the_closest_zombie(self):
        rogue = self.need(self.makes(["Gisa, the Hellraiser"]), ZOMBIE_ROGUE)
        self.assertEqual(rogue["state"], "none")
        self.assertEqual(rogue["words"], "None owned · closest: Zombie / Zombie Knight ×8")
        self.assertTrue(all(s["close"] for s in rogue["stand_ins"]))
        self.assertEqual(rogue["colors"], ["B", "U"])

    def test_fish_only_on_the_way(self):
        result = self.makes(["Fountainport"], incoming=INCOMING)
        fish = self.need(result, FISH)
        self.assertEqual(fish["state"], "incoming")
        self.assertEqual(fish["words"], f"None owned yet: 2 on the way (order {ORDER})")
        self.assertEqual(self.need(result, TREASURE)["state"], "check")

    def test_copy_says_what_to_do(self):
        copy = self.need(self.makes(["Gandalf, Westward Voyager"]), COPY)
        self.assertEqual(copy["state"], "check")
        self.assertEqual(sorted((c["front"], c["back"], c["side"]) for c in copy["cards"]),
                         [("Copy", "Human", "front"), ("Otter", "Copy", "back")])
        self.assertTrue(copy["words"].endswith("Use it for any copy; say what it copies."))

    def test_the_ring_matches_its_two_faces_or_full_name(self):
        result = self.makes(["Galadriel, Elven-Queen"], incoming=INCOMING)
        ring = self.need(result, RING)
        self.assertEqual((ring["state"], ring["on_the_way"]), ("incoming", 1))
        self.tokens_csv(HEADER + "The Ring Tempts You,The Ring,,,,,1,,,\n"
                        + "The Ring // The Ring Tempts You,,,,,,1,,,single-sided verified\n"
                        + "The Ring,Zombie,,,,,1,,,\n")
        ring = self.need(self.makes(["Galadriel, Elven-Queen"], tokens.read()), RING)
        self.assertEqual([(c["front"], c["side"]) for c in ring["cards"]],
                         [("The Ring Tempts You", "front"), ("The Ring // The Ring Tempts You", "front")])

    def test_unresolved_parts_are_needs_by_name(self):
        result = self.makes(["Kaya the Inexorable"])
        spirit = self.need(result, "name:Spirit")
        self.assertEqual((spirit["state"], spirit["colors"], spirit["pt"]), ("check", None, None))
        self.assertEqual(spirit["words"], "Have 4 cards named Spirit; Scryfall's link doesn't say which Spirit")

    def test_sideboard_only_needs(self):
        result = tokens.deck_tokens({"Deck": [DeckLine(1, "Hare Apparent")],
                                     "Sideboard": [DeckLine(2, "Hornet Queen"), DeckLine(1, "Hare Apparent")]},
                                    self.real(), [])
        self.assertTrue(self.need(result, INSECT)["sideboard_only"])
        rabbit = self.need(result, RABBIT)
        self.assertFalse(rabbit["sideboard_only"])
        self.assertEqual(rabbit["made_by"], [{"name": "Hare Apparent", "quantity": 1, "section": "Deck"},
                                             {"name": "Hare Apparent", "quantity": 1, "section": "Sideboard"}])

    def test_helpers_basics_and_unknown_cards_make_nothing(self):
        result = self.makes(["Brazen Borrower", "Forest", "Not A Card", "Llanowar Elves"])
        self.assertEqual(result["needs"], [])
        self.assertEqual(result["counts"], {"kinds": 0, "ready": 0, "check": 0, "differs": 0, "incoming": 0,
                                            "none": 0})
        self.assertEqual(result["note"], tokens.NOTE)

    def test_copies_and_unlisted(self):
        result = self.makes(["Gandalf, Westward Voyager", "Coruscation Mage", "Kaya the Inexorable",
                             "Shortcut Seeker"])
        self.assertEqual(result["copies"], ["Coruscation Mage"])          # offspring: "a copy of"
        self.assertNotIn("Gandalf, Westward Voyager", result["copies"])     # links to Copy
        self.assertNotIn("Shortcut Seeker", result["unlisted"])            # its dungeons are linked
        with mock.patch.object(cards, "tokens_for", return_value=([], [])):
            result = self.makes(["Court of Grace", "Shortcut Seeker", "Hornet Queen"])
        self.assertEqual(result["unlisted"], ["Court of Grace", "Shortcut Seeker", "Hornet Queen"])

    def test_a_known_printing_row_is_ready(self):
        self.tokens_csv(HEADER + "Fish,,tblb,7,,nonfoil,2,,,single-sided verified\n")
        fish = self.need(self.makes(["Fountainport"], tokens.read()), FISH)
        self.assertEqual((fish["state"], fish["words"], fish["usable"]), ("ready", "Have it: 2 cards", 2))
        self.assertEqual(fish["cards"][0]["verdict"], "exact")

    def test_states_sort_none_first(self):
        result = self.makes(["Gisa, the Hellraiser", "Hornet Queen", "Hare Apparent", "Fountainport"],
                            incoming=INCOMING)
        states = [n["state"] for n in result["needs"]]
        self.assertEqual(states, sorted(states, key=tokens.STATES.index))
        self.assertEqual(result["counts"], {"kinds": 5, "ready": 0, "check": 2, "differs": 1, "incoming": 1,
                                            "none": 1})
        self.assertEqual(tokens.brief(result), {"kinds": 5, "none": ["Zombie Rogue"], "differs": ["Insect"],
                                                "incoming": ["Fish"], "reminders": []})


# ------------------------------------------------------------------ incoming

class IncomingTests(TokensTestCase):
    def test_pending_token_components_are_read_from_records(self):
        rel = self.record()
        self.record("2026-10-01-old", status="received", payload=MTGMATE[:1])
        (self.magic / "orders/tokens/stray.csv").write_text(HEADER + "Rat,,,,,,1,,,\n", encoding="utf-8")
        found, problems = tokens.incoming()
        self.assertEqual(problems, [])
        self.assertEqual([(f["order"], f["component"], f["path"], len(f["rows"])) for f in found],
                         [(ORDER, "tokens", rel, 8)])

    def test_a_bad_payload_is_a_problem(self):
        self.record(payload=HEADER + ",Beast,,,,,1,,,\n")
        found, problems = tokens.incoming()
        self.assertEqual(found, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("Row 1 of order 2026-10-07-shop-a's token cards: tokens need a front name", problems[0])
        self.assertNotIn(str(self.root), problems[0])

    def test_unreadable_records_are_a_problem(self):
        self.write("orders/records/bad.json", "{")
        found, problems = tokens.incoming()
        self.assertEqual(found, [])
        self.assertTrue(problems[0].startswith("The order records can't be read"))


# ------------------------------------------------------------------ holders, gaps, uses, cache

class HolderTests(IndexTestCase):
    def setUp(self):
        super().setUp()
        self.tokens_csv(REAL_TOKENS)
        self.deck("queen", "Queen Deck", deck="1 Hornet Queen\n1 Gisa, the Hellraiser\n")
        self.deck("built", "Built Deck", status="built", deck="1 Fountainport\n", owned="1 Army of the Damned\n",
                  built_version="owned-only")
        self.deck("idea", "Idea Deck", status="idea", deck="1 Prideful Parent\n")
        self.write("products/test-product.csv", "deck,section,name,quantity,finish,set,collector_number\n"
                                                ",deck,\"Gisa, the Hellraiser\",1,nonfoil,potj,89s\n")
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "test-product.csv,owned,yes,,,\n")

    def test_holders_are_built_building_and_intact_products(self):
        warnings = []
        found = tokens.holders(warnings)
        self.assertEqual([(i, t) for i, t, _ in found],
                         [("casual/built", "Built Deck"), ("casual/queen", "Queen Deck"),
                          ("product/test-product", "test-product")])
        self.assertEqual([l.name for l in found[0][2]["Deck"]], ["Army of the Damned"])    # its built version
        self.assertEqual(warnings, [])

    def test_gaps_list_what_holders_have_none_of(self):
        gaps = tokens.gaps(tokens.read(), INCOMING, [])
        self.assertEqual([(g["name"], g["state"], [d["id"] for d in g["decks"]], g["on_the_way"]) for g in gaps],
                         [("Zombie Rogue", "none", ["casual/queen", "product/test-product"], 0)])
        self.assertEqual([d["link"] for d in gaps[0]["decks"]], ["casual/queen", "product/test-product"])
        self.assertEqual(gaps[0]["key"], ZOMBIE_ROGUE)
        self.write("decks/casual/built.md", deck_md("Built Deck", deck="1 Fountainport\n"))
        gaps = tokens.gaps(tokens.read(), INCOMING, [])
        self.assertIn(("Fish", "incoming", 2), [(g["name"], g["state"], g["on_the_way"]) for g in gaps])

    def test_row_uses(self):
        inv = tokens.read()
        uses = tokens.row_uses(inv, [], [])
        zombie_knight = next(i for i, r in enumerate(inv.rows) if r["back"] == "Zombie Knight")
        self.assertEqual(uses[zombie_knight], [{"deck": "casual/built", "title": "Built Deck",
                                                "link": "casual/built", "token": "Zombie",
                                                "side": "front", "state": "check"}])
        insect = next(i for i, r in enumerate(inv.rows) if r["front"] == "Insect")
        self.assertEqual(uses[insect], [{"deck": "casual/queen", "title": "Queen Deck", "link": "casual/queen",
                                         "token": "Insect", "side": "front", "state": "differs"}])
        self.assertTrue(all(u["token"] != "Zombie Rogue" for us in uses.values() for u in us))   # hints aren't uses

    def test_built_ids_are_the_built_decks(self):
        self.assertEqual(tokens.built_ids(), {"casual/built"})

    def test_shared_rows_need_more_built_holders_than_cards(self):
        inv = tokens.read()
        row = next(i for i, r in enumerate(inv.rows) if r["back"] == "Zombie Knight")
        cards_ = int(inv.rows[row]["quantity"])

        def use(deck, state="ready"):
            return {"deck": deck, "title": deck.split("/")[-1], "link": deck, "token": "Zombie",
                    "side": "front", "state": state}
        built = {f"casual/b{n}" for n in range(cards_ + 1)}
        enough = {row: [use(f"casual/b{n}") for n in range(cards_)] + [use("casual/building")]}
        self.assertEqual(tokens.shared_rows(inv, enough, built), {})      # a deck being built never counts
        twice = {row: [use("casual/b0"), use("casual/b0", "differs")] * (cards_ + 1)}
        self.assertEqual(tokens.shared_rows(inv, twice, built), {})       # one deck counts once
        over = {row: [use(f"casual/b{n}") for n in range(cards_)] + [use("product/kit", "differs")]}
        shared = tokens.shared_rows(inv, over, built)                     # an intact product and a stand-in count
        self.assertEqual([h["deck"] for h in shared[row]], [f"casual/b{n}" for n in range(cards_)] + ["product/kit"])
        self.assertTrue(tokens.shared_words(inv.rows[row], shared[row]).startswith(
            f"Only {cards_} card{'' if cards_ == 1 else 's'}, used by {cards_ + 1} built decks: b0"))

    def test_a_product_with_named_decks_has_no_deck_link(self):
        self.write("products/test-product.csv", "deck,section,name,quantity,finish,set,collector_number\n"
                                                "Gisa,deck,\"Gisa, the Hellraiser\",1,nonfoil,potj,89s\n"
                                                "Other,deck,Hornet Queen,1,nonfoil,pip,878\n")
        self.assertIsNone(decks.find_summary("product/test-product"))
        gaps = tokens.gaps(tokens.read(), [], [])
        rogue = next(g for g in gaps if g["name"] == "Zombie Rogue")
        self.assertIn({"id": "product/test-product", "title": "test-product", "link": None}, rogue["decks"])
        inv = tokens.read()
        uses = [u for us in tokens.row_uses(inv, [], []).values() for u in us if u["deck"] == "product/test-product"]
        self.assertTrue(uses)
        self.assertTrue(all(u["link"] is None for u in uses))

    def test_the_cache_key_follows_the_tokens_file(self):
        sections = lines("Hornet Queen")
        calls = []
        real = tokens.deck_tokens

        def counting(*args):
            calls.append(1)
            return real(*args)

        with mock.patch.object(tokens, "deck_tokens", counting):
            first = tokens.cached_deck_tokens("casual/queen", "target", sections, tokens.read(), [])
            again = tokens.cached_deck_tokens("casual/queen", "target", sections, tokens.read(), [])
            self.assertEqual(len(calls), 1)
            self.assertEqual(first, again)
            again["needs"].clear()                      # a copy: the cache is untouched
            self.assertTrue(tokens.cached_deck_tokens("casual/queen", "target", sections, tokens.read(), [])["needs"])
            self.assertEqual(len(calls), 1)
            self.tokens_csv(REAL_TOKENS.replace("no deathtouch", "deathtouch"))
            changed = tokens.cached_deck_tokens("casual/queen", "target", sections, tokens.read(), [])
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(changed["needs"][0]["state"], first["needs"][0]["state"])
            tokens.cached_deck_tokens("casual/queen", "target", sections, tokens.read(), INCOMING)
            tokens.cached_deck_tokens("casual/queen", "target", lines("Hornet Queen", "Fountainport"),
                                      tokens.read(), INCOMING)
            self.assertEqual(len(calls), 4)


# ------------------------------------------------------------------ --check and the printout

class CheckTests(IndexTestCase):
    def any_name(self):
        """The fixture index has only some token names; accept every name as written."""
        return mock.patch.object(cards, "token_face", lambda name: name)

    def test_the_real_file_has_no_problems(self):
        self.tokens_csv(REAL_TOKENS)
        self.record()
        notes = []
        warnings = []
        with self.any_name():
            self.assertEqual(tokens.check(notes, warnings=warnings), [])
        self.assertEqual(notes, [])
        self.assertEqual(warnings, [])

    def test_mistyped_details_are_warnings(self):
        self.tokens_csv(HEADER + "Angel,Spirit,,,,,1,4/4 white flying,1/1; whte,\n")
        warnings = []
        with self.any_name():
            self.assertEqual(tokens.check(warnings=warnings), [])
        self.assertEqual(warnings, [
            "Row 1 of the home token cards: front details '4/4 white flying' aren't read: "
            "separate them with ';' (4/4; white; flying)",
            "Row 1 of the home token cards: back details 'whte' aren't read: did you mean white?"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.any_name():
            self.assertEqual(tokens.main(["--check"]), 0)
        self.assertEqual(out.getvalue().splitlines(), warnings + ["Token cards (home): no problems"])
        self.tokens_csv(HEADER + "Angel,Sprit,,,,,1,,1/1; whte,\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["--check"]), 1)
        lines = out.getvalue().splitlines()
        self.assertIn("'Sprit' isn't a Scryfall token", lines[0])
        self.assertEqual(lines[-1], "Row 1 of the home token cards: back details 'whte' aren't read: did you mean white?")

    def test_each_message(self):
        self.tokens_csv(HEADER
                        + "Angel,Spirit,,,,,1,,,\n"
                        + "Sprit,,,,,,1,,,\n"
                        + "Ring,,tltr,H13,,,1,,,single-sided verified\n"
                        + "Angel,Clue,,,,,1,,,single-sided verified\n"
                        + ",Beast,,,,,1,,,\n"
                        + "Angel,Angel,,,,,1,,,\n")
        self.record(payload=HEADER + "Fish,,tblb,7,,shiny,1,,,\n")
        self.assertEqual(tokens.check(), [
            "A row after row 4 of the home token cards: tokens need a front name and positive physical quantity; "
            "it can't be changed until that's put right",
            "The home token cards aren't in the standard order; the next Tokens page save sorts them",
            "Row 2 of the home token cards: 'Sprit' isn't a Scryfall token, emblem or reminder name (did you mean Spirit?)",
            "Row 2 of the home token cards: a blank back needs 'single-sided verified' in notes",
            "Row 3 of the home token cards: 'Ring' isn't a Scryfall token, emblem or reminder name (did you mean The Ring?)",
            "Row 4 of the home token cards: notes say single-sided verified but a back is recorded",
            "Row 1 of order 2026-10-07-shop-a's token cards: invalid token finish"])

    def test_a_wrong_printing(self):
        self.tokens_csv(HEADER + "Spirit,,tltr,H13,,,1,,,single-sided verified\n")
        self.assertEqual(tokens.check(), ["Row 1 of the home token cards: tltr H13 is The Ring, not Spirit"])

    def test_main_exit_codes(self):
        self.tokens_csv(REAL_TOKENS)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.any_name():
            self.assertEqual(tokens.main(["--check"]), 0)
        self.assertEqual(out.getvalue(), "Token cards (home): no problems\n")
        self.tokens_csv(HEADER + "Sprit,Spirit,,,,,1,,,\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["--check"]), 1)
        self.assertIn("'Sprit' isn't a Scryfall token", out.getvalue())

    def test_main_prints_a_decks_needs(self):
        self.tokens_csv(REAL_TOKENS)
        self.record()
        self.deck("queen", "Queen Deck", deck="1 Hornet Queen\n1 Court of Grace\n", owned="1 Fountainport\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/queen"]), 0)
        text = out.getvalue()
        self.assertIn("Queen Deck: 4 kinds of token", text)
        self.assertIn("Different token: your card says no deathtouch; Hornet Queen's Insect has deathtouch "
                      "· 2 on the way", text)
        self.assertIn("Grab Angel / The Monarch ×1, The Monarch side (same card as for Angel)", text)
        self.assertIn(tokens.NOTE, text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/queen", "--owned"]), 0)
        self.assertIn("None owned yet: 2 on the way (order 2026-10-07-shop-a)", out.getvalue())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/nothing"]), 1)


class CheckWithoutIndexTests(TokensTestCase):
    def test_names_are_skipped_with_a_note(self):
        self.tokens_csv(HEADER + "Sprit,Spirit,,,,,1,,,\n")
        notes = []
        self.assertEqual(tokens.check(notes), [])
        self.assertEqual(len(notes), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["--check"]), 0)
        self.assertIn("Names weren't checked", out.getvalue())
        out = io.StringIO()
        self.deck("queen", "Queen Deck")
        with contextlib.redirect_stdout(out):
            self.assertEqual(tokens.main(["casual/queen"]), 1)
        self.assertIn("The card data isn't ready", out.getvalue())


class PatchedNamesTests(unittest.TestCase):
    """Tests patch these names on tokens (mock.patch.object(tokens, ...)), so
    each must have its one binding in tokens itself, beside everything that
    reads it. A copy in one of tokens' parts, or a part reading it there,
    would be out of reach of the patch. _faces_at is the other way round:
    tests patch it on tokens.names, which matching reads it through, so the
    package must not have a copy of its own."""

    PATCHED = ("read", "incoming", "deck_tokens", "cached_deck_tokens", "row_uses")

    def test_patched_names_are_only_in_the_package_file(self):
        submodules = [info.name for info in pkgutil.iter_modules(tokens.__path__)]
        self.assertTrue(submodules)
        for name in self.PATCHED:
            self.assertIn(name, vars(tokens))
            value = getattr(tokens, name)
            if callable(value):
                self.assertEqual(value.__module__, tokens.__name__, name)
            for sub in submodules:
                if sub == "__main__":
                    continue
                module = getattr(tokens, sub)
                self.assertNotIn(name, vars(module), f"tokens.{sub} has its own {name}")
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                used = {n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(tree)
                        if isinstance(n, (ast.Name, ast.Attribute))}
                self.assertFalse(name in used, f"tokens.{sub} reads {name}")

    def test_faces_at_lives_only_in_names(self):
        self.assertNotIn("_faces_at", vars(tokens))
        for sub in (info.name for info in pkgutil.iter_modules(tokens.__path__)):
            if sub in ("__main__", "names"):
                continue
            self.assertNotIn("_faces_at", vars(getattr(tokens, sub)), f"tokens.{sub} has its own _faces_at")
        self.assertEqual(token_names._faces_at.__module__, token_names.__name__)


if __name__ == "__main__":
    unittest.main()
