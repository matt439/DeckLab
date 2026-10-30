"""Tests for decklab.lib.decks (the package's own file): saving deck files,
slugs and titles, and the product-deck library. The other decks tests are
in test_decks_decklist.py (decklist lines and blocks), test_decks_deckfile.py
(reading deck files and writing them back) and test_decks_edit.py (edits),
which share the fixtures and helpers here.

Run from the repo root:
    python scripts/test_fixtures.py

fixtures/decks/ holds frozen copies of the 11 deck files as they were on
2026-09-29; the tests that check what a file contains, or the exact text an
edit gives, use those, so saving or adding a real deck never breaks them. The
real files in magic/decks/ (whatever is there) are checked only for what must
always hold: an unchanged render gives the same bytes, and a full edit changes
only the owned parts. fixtures/.gitattributes keeps the fixtures' LF line
endings in every clone. The library tests read the real magic/products/ (fixed
lists of sealed products). Nothing here needs the network.
"""
import ast
import copy
import hashlib
import pkgutil
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.decks import DeckLine, PriceStamp, TableRow
from decklab.tests import deck_files, pre_db

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_DECKS = FIXTURES / "decks"
FIXTURE_FILES = sorted(FIXTURE_DECKS.glob("*/*.md"))
EXPECTED_DECKS = {
    "casual/gruul-ramp", "casual/izzet-prowess", "casual/mono-black-midrange",
    "casual/mono-black-zombies", "casual/mono-white-angels", "casual/orzhov-removal",
    "casual/orzhov-vampires", "casual/selesnya-rabbits",
    "commander/finneas-rabbits", "commander/giada-angels", "commander/gisa-zombies",
}
OWNED_SPANS = ("header", "marker", "target", "owned", "table", "prices")
FIXTURE_STAMP = PriceStamp(1.4224, "2026-09-25", "2026-09-28")

# A new deck's header fields and lists: NewDeckTests checks the file
# new_deck_text makes from them, and other tests start from that file.
NEW_DECK_FIELDS = [("Format", "Casual 60-card, 1v1"), ("Archetype", "Mono-red burn"),
                   ("Played by", "wife"), ("Status", "idea")]
NEW_DECK_SECTIONS = {"Deck": [DeckLine(4, "Lightning Bolt", "fdc", "163"), DeckLine(20, "Mountain")],
                     "Sideboard": [DeckLine(2, "Negate", "fdn", "710", "foil")]}


def read(slug):
    """A fresh model of one frozen deck file, e.g. read("casual/gruul-ramp")."""
    return decks.read_deck_file(FIXTURE_DECKS / f"{slug}.md")


def prose(deck):
    """The deck's text with every owned part cut out."""
    text, pos, out = deck.text, 0, []
    for start, end in sorted(deck.spans[k] for k in OWNED_SPANS if k in deck.spans):
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def rerender(deck):
    """Render, re-parse, and return (text, new model)."""
    text = decks.render_deck_file(deck)
    return text, decks.parse_deck(text.encode("utf-8"), deck.slug, deck.kind)


def parse(text, slug="t", kind="casual"):
    return decks.parse_deck(text.encode("utf-8"), slug, kind)


def new_deck_bytes():
    """A new deck file (the template NewDeckTests checks) as bytes."""
    return decks.new_deck_text("Red Burn", "casual", NEW_DECK_FIELDS, NEW_DECK_SECTIONS).encode("utf-8")


def add_to_rows(rows, line):
    """The table rows (copies) after line's copies are added to the list, so
    they still describe it: that card's Need and Owned go up, or it gets a row."""
    rows = [copy.copy(r) for r in rows]
    if not decks.is_basic_land(line.name):
        row = next((r for r in rows if decks._card_key(r.card) == decks._card_key(line.name)), None)
        if row is None:
            rows.append(TableRow(line.name, line.quantity, line.quantity, 0))
        else:
            row.need += line.quantity
            row.owned += line.quantity
    return rows


class WriteTests(unittest.TestCase):

    def setUp(self):
        # DECKS_DIR is a level down in the test's own folder, so even a '..'
        # escape the guard missed would land somewhere this test cleans up.
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.tmp = self.root / "decks"
        for kind in decks.KINDS:
            (self.tmp / kind).mkdir(parents=True)
        patcher = mock.patch.object(decks, "DECKS_DIR", self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(inventory.use(pre_db.following(self.root)))     # the decks come from the inventory
        self.text = decks.new_deck_text("Test", "casual", [("Status", "idea")], {"Deck": [DeckLine(4, "Opt")]})

    def test_create_then_update(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        self.assertEqual(path.read_bytes(), self.text.encode("utf-8"))
        self.assertEqual(sha, hashlib.sha256(path.read_bytes()).hexdigest())
        deck = decks.read_deck_file(path)
        self.assertEqual(deck.sha256, sha)
        decks.set_status(deck, "built")
        sha2 = deck_files.write_deck_file(path, decks.render_deck_file(deck), deck.sha256)
        self.assertEqual(decks.read_deck_file(path).status, "built")
        self.assertNotEqual(sha, sha2)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["test-deck.md"])   # no temp files

    def test_conflicts(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        with self.assertRaises(deck_files.ConflictError):
            deck_files.write_deck_file(path, self.text, None)                     # already exists
        path.write_bytes(self.text.encode("utf-8") + b"edited by someone else\n")
        with self.assertRaises(deck_files.ConflictError):
            deck_files.write_deck_file(path, "mine\n", sha)                       # changed on disk
        self.assertTrue(path.read_bytes().endswith(b"edited by someone else\n"))
        path.unlink()
        with self.assertRaises(deck_files.ConflictError):
            deck_files.write_deck_file(path, "mine\n", sha)                       # deleted

    def test_a_failed_write_leaves_the_file_and_no_temp_file(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        with mock.patch("os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            deck_files.write_deck_file(path, "# New\n", sha)
        self.assertEqual(path.read_bytes(), self.text.encode("utf-8"))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["test-deck.md"])

    def test_a_file_open_for_a_moment_is_replaced_after_a_retry(self):
        # Windows refuses to replace a file while any handle to it is open
        # (the server's own threads reading it for another page, a scanner).
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        real, tries = deck_files.os.replace, []

        def busy_twice(src, dst):
            tries.append(dst)
            if len(tries) <= 2:
                raise PermissionError(13, "Access is denied", str(dst))
            real(src, dst)
        with mock.patch.object(deck_files.os, "replace", side_effect=busy_twice), \
                mock.patch.object(decks, "REPLACE_WAITS", (0, 0, 0)):
            deck_files.write_deck_file(path, "# New\n", sha)
        self.assertEqual((path.read_bytes(), len(tries)), (b"# New\n", 3))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["test-deck.md"])

    def test_a_file_that_stays_open_gives_a_plain_error(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        denied = PermissionError(13, "Access is denied", str(path.with_name(".test-deck.md.123.tmp")))
        with mock.patch.object(deck_files.os, "replace", side_effect=denied), \
                mock.patch.object(decks, "REPLACE_WAITS", (0, 0)), \
                self.assertRaises(deck_files.FileBusyError) as caught:
            deck_files.write_deck_file(path, "# New\n", sha)
        self.assertIsInstance(caught.exception, OSError)
        self.assertEqual(str(caught.exception), "test-deck.md is open in another program, so it couldn't be saved "
                                                "(nothing was changed); close it or wait a moment, then save again")
        self.assertIsNone(caught.exception.filename)                     # no temp path to show
        self.assertEqual(path.read_bytes(), self.text.encode("utf-8"))
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["test-deck.md"])

    def test_a_change_while_waiting_is_a_conflict(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)

        def someone_saves(seconds):
            path.write_bytes(b"# Theirs\n")
        denied = PermissionError(13, "Access is denied")
        with mock.patch.object(deck_files.os, "replace", side_effect=denied), \
                mock.patch.object(deck_files.time, "sleep", side_effect=someone_saves), \
                self.assertRaises(deck_files.ConflictError):
            deck_files.write_deck_file(path, "# Mine\n", sha)
        self.assertEqual(path.read_bytes(), b"# Theirs\n")

    @unittest.skipUnless(sys.platform == "win32", "only Windows refuses to replace an open file")
    def test_a_real_open_handle_on_windows(self):
        path = decks.deck_path("casual", "test-deck")
        sha = deck_files.write_deck_file(path, self.text, None)
        reader = open(path, "rb")
        threading.Timer(0.3, reader.close).start()
        started = time.monotonic()
        deck_files.write_deck_file(path, "# New\n", sha)
        self.assertGreater(time.monotonic() - started, 0.25)
        self.assertEqual(path.read_bytes(), b"# New\n")
        with open(path, "rb"), mock.patch.object(decks, "REPLACE_WAITS", (0.01, 0.01)), \
                self.assertRaises(deck_files.FileBusyError):
            deck_files.write_deck_file(path, "# Newer\n", hashlib.sha256(b"# New\n").hexdigest())
        self.assertEqual(path.read_bytes(), b"# New\n")

    def test_bytes_are_written_exactly(self):
        path = decks.deck_path("commander", "crlf-deck")
        data = self.text.replace("\n", "\r\n").encode("utf-8")
        deck_files.write_deck_file(path, data.decode("utf-8"), None)
        self.assertEqual(path.read_bytes(), data)

    def test_paths_outside_the_deck_folders_are_refused(self):
        bad = [self.tmp / "loose.md", self.tmp / "casual" / "notes.txt",
               self.tmp / "casual" / ".." / ".." / "escape.md", self.tmp / "casual" / "Bad Name.md",
               self.tmp / "other" / "deck.md", Path("magic/collection.csv")]
        for path in bad:
            with self.subTest(str(path)), self.assertRaises(ValueError):
                deck_files.write_deck_file(path, self.text, None)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["decks"])

    def test_slugs(self):
        self.assertEqual(decks.deck_path("casual", "gruul-ramp-2"), self.tmp / "casual" / "gruul-ramp-2.md")
        for slug in ("Gruul", "gruul--ramp", "-gruul", "gruul-", "a/b", "../x", "", "gruul ramp", "é", None):
            with self.subTest(slug), self.assertRaises(ValueError):
                decks.deck_path("casual", slug)
        with self.assertRaises(ValueError):
            decks.deck_path("modern", "gruul")

    def test_windows_device_names_are_refused(self):
        # Windows lets you write aux.md, but git can't add it.
        for slug in ("con", "prn", "aux", "nul", "com1", "lpt9", "com0"):
            with self.subTest(slug):
                self.assertFalse(decks.valid_slug(slug))
                with self.assertRaisesRegex(ValueError, "device name"):
                    decks.deck_path("casual", slug)
                with self.assertRaises(ValueError):
                    deck_files.write_deck_file(self.tmp / "casual" / f"{slug}.md", self.text, None)
        self.assertEqual(list((self.tmp / "casual").iterdir()), [])
        for slug in ("conflux", "aux-deck", "com10", "nul2"):
            self.assertTrue(decks.valid_slug(slug), slug)
        deck_files.write_deck_file(decks.deck_path("casual", "conflux"), self.text, None)


class NewDeckHelperTests(unittest.TestCase):

    def test_title_slug(self):
        for title, slug in (("Lórien Elves", "lorien-elves"), ("Cats + Vampires", "cats-vampires"),
                            ("  Æther Hub!! ", "aether-hub"), ("Giada, Font of Hope: Angels", "giada-font-of-hope-angels"),
                            ("!!!", ""), ("日本", ""), ("x" * 80, "x" * decks.MAX_SLUG),
                            ("a " * 40, ("a-" * 30).rstrip("-"))):
            with self.subTest(title=title):
                self.assertEqual(decks.title_slug(title), slug)
                if slug:
                    self.assertTrue(decks.valid_slug(slug))

    def test_phone_punctuation_gives_the_same_file_name(self):
        # A curly apostrophe or a dash used to vanish, so the same title typed
        # on a phone escaped the duplicate check.
        for a, b in (("Ajani's Pride", "Ajani\u2019s Pride"), ("Cats-Vampires", "Cats\u2013Vampires"),
                     ("Cats - Vampires", "Cats \u2014 Vampires"), ("Zero Width", "Zero\u00a0Width")):
            with self.subTest(b):
                self.assertEqual(decks.title_slug(b), decks.title_slug(a))
        self.assertEqual(decks.title_slug("Cats\u2013Vampires"), "cats-vampires")
        # Apostrophes of every kind are dropped, so a possessive stays one word.
        for title in ("Ajani's Pride", "Ajani\u2019s Pride", "Ajani\u2018s Pride", "Ajani\u02bcs Pride",
                      "Ajani`s Pride", "Ajani\u00b4s Pride", "Ajani\uff07s Pride", "AJANI'S PRIDE"):
            with self.subTest(title):
                self.assertEqual(decks.title_slug(title), "ajanis-pride")
        self.assertEqual(decks.title_slug("Gisa's Zombies"), "gisas-zombies")
        self.assertEqual(decks.title_slug("'Tis the Season"), "tis-the-season")
        self.assertEqual(decks.title_slug("Rock 'n' Roll"), "rock-n-roll")
        # Other punctuation still separates words.
        self.assertEqual(decks.title_slug("Ajani\u2019s \u201cPride\u201d"), "ajanis-pride")
        self.assertEqual(decks.title_slug("Cats/Vampires"), "cats-vampires")
        # Invisible format characters are dropped, not made separators.
        self.assertEqual(decks.title_slug("Zero\u200bWidth"), "zerowidth")
        self.assertEqual(decks.title_slug("Evil\u202eslived"), "evilslived")
        self.assertEqual(decks.title_slug("Ele\u00adphant"), "elephant")

    def test_clean_title(self):
        self.assertEqual(decks.clean_title("  Evil\u202eslived\u200b  Deck\u00a0\u2028Two "), "Evilslived Deck Two")
        self.assertEqual(decks.clean_title("Ajani\u2019s Pride"), "Ajani\u2019s Pride")          # visible: kept
        self.assertEqual(decks.clean_title("L\u00f3rien \u00c6ther"), "L\u00f3rien \u00c6ther")

    def test_existing_deck_id(self):
        with mock.patch.object(decks, "DECKS_DIR", FIXTURE_DECKS), inventory.use(pre_db.following(FIXTURES)):
            self.assertEqual(decks.existing_deck_id("gruul-ramp"), "casual/gruul-ramp")
            self.assertEqual(decks.existing_deck_id("GIADA-ANGELS"), "commander/giada-angels")
            self.assertIsNone(decks.existing_deck_id("new-deck"))

    def test_notes_in_the_template(self):
        text = decks.new_deck_text("X", "casual", [], {}, notes="Started from Cats.")
        self.assertTrue(text.endswith("## Substitutes\n\n## Notes\n\nStarted from Cats.\n"))
        with self.assertRaises(ValueError):
            decks.new_deck_text("X", "casual", [], {}, notes="two\nlines")

    def test_section_header_and_clean_sections(self):
        self.assertEqual([decks.section_header(t) for t in ("Sideboard", "sideboard:", "4 Opt", "")],
                         ["Sideboard", "Sideboard", None, None])
        line = DeckLine(1, "Opt")
        self.assertEqual(list(decks.clean_sections({"Sideboard": [line], "Deck": [line], "Commander": []})),
                         ["Deck", "Sideboard"])
        with self.assertRaises(ValueError):
            decks.clean_sections({"Maybe": [line]})


class LibraryTests(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(decks, "DECKS_DIR", FIXTURE_DECKS)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The product decks are the inventory's: the real product lists, through the files backend
        # over the inventory files at tag pre-db-inventory (the database holds them since the cutover).
        # The deck files are the inventory's too, wherever each test points DECKS_DIR.
        self.addCleanup(inventory.use(pre_db.following()))

    def temp_products(self):
        """A temp folder: magic/products in a temp tree (see products_in)."""
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        products = tmp / "magic" / "products"
        products.mkdir(parents=True)
        return products

    def products_in(self, products):
        """The inventory of the temp tree whose magic/products is products, installed for a with block."""
        return inventory.use(pre_db.following(products.parent.parent))

    def test_list_decks(self):
        summaries = decks.list_decks()
        ids = [s["id"] for s in summaries]
        self.assertEqual(len(ids), len(set(ids)))
        by_id = {s["id"]: s for s in summaries}
        self.assertEqual({i for i in ids if not i.startswith("product/")}, EXPECTED_DECKS)

        gruul = by_id["casual/gruul-ramp"]
        self.assertEqual((gruul["title"], gruul["kind"], gruul["player"], gruul["status"], gruul["built_version"],
                          gruul["read_only"], gruul["card_count"], gruul["sideboard_count"], gruul["versions"],
                          gruul["source"]),
                         ("Gruul Ramp", "casual", "either", "idea", None, False, 60, 6, ["target", "owned"],
                          "casual/gruul-ramp"))
        self.assertEqual(by_id["commander/giada-angels"]["target_bracket"], 2)

        # The real product lists (fixed lists of sealed products).
        halves = [i for i in ids if i.startswith("product/fdn-beginner-box/")]
        self.assertEqual(len(halves), 10)
        for deck_id in halves:
            self.assertEqual(by_id[deck_id]["card_count"], 20)
        for s in summaries:
            if s["id"].startswith("product/"):
                self.assertTrue(s["read_only"])
                self.assertEqual(s["versions"], ["target"])
                self.assertNotIn("error", s)
        self.assertEqual(by_id["product/blb-starter-kit/hare-raising"]["card_count"], 60)
        self.assertEqual(by_id["product/blb-starter-kit/otter-limits"]["card_count"], 60)
        challenger = by_id["product/challenger-2019-lightning-aggro"]
        self.assertEqual((challenger["card_count"], challenger["sideboard_count"]), (60, 15))
        for precon in ("product/fdc-calling-all-angels", "product/fdc-wretched-ranks"):
            self.assertEqual((by_id[precon]["kind"], by_id[precon]["card_count"]), ("commander", 100))
        self.assertNotIn("product/fdn-starter-collection", by_id)
        for drop in ("sld-welcome-to-stardew-valley", "sld-life-in-pelican-town",
                     "sld-a-flicker-in-the-deep"):
            self.assertNotIn(f"product/{drop}", by_id)

    def test_product_lines_keep_their_printing(self):
        hare = decks.load_deck("product/blb-starter-kit/hare-raising")["Deck"]
        self.assertIn(DeckLine(1, "Byrke, Long Ear of the Law", "blb", "380", "foil"), hare)
        self.assertIn(DeckLine(11, "Forest", "blb", None), hare)
        aggro = decks.load_deck("product/challenger-2019-lightning-aggro")
        self.assertIn(DeckLine(22, "Mountain", "rna", "263"), aggro["Deck"])
        self.assertEqual(decks.card_count(aggro, ("Sideboard",)), 15)
        angels = decks.load_deck("product/fdc-calling-all-angels")
        self.assertEqual(angels["Commander"], [DeckLine(1, "Giada, Font of Hope", "fdc", "4", "foil")])
        self.assertEqual(decks.format_line(hare[-1]), "12 Plains (BLB)")

    def test_beginner_box_pairings(self):
        pairs = decks.beginner_box_pairings()
        self.assertEqual(len(pairs), 45)
        self.assertEqual(len({p["id"] for p in pairs}), 45)
        for p in pairs:
            self.assertEqual((p["card_count"], p["read_only"], len(p["halves"])), (40, True, 2))
        cats_vamps = decks.load_deck("pairing/cats+vampires")
        self.assertEqual(decks.load_deck("pairing/vampires+cats"), cats_vamps)
        haven = [l for l in cats_vamps["Deck"] if l.name == "Uncharted Haven"]
        self.assertEqual(haven, [DeckLine(2, "Uncharted Haven", "fdn", "564")])
        plains = [l for l in decks.load_deck("pairing/cats+healing")["Deck"] if l.name == "Plains"]
        self.assertEqual(plains, [DeckLine(14, "Plains", "fdn", None)])
        # Merging doesn't change the halves themselves.
        self.assertIn(DeckLine(1, "Uncharted Haven", "fdn", "564"), decks.load_deck("product/fdn-beginner-box/cats")["Deck"])

    def test_load_deck(self):
        self.assertEqual(decks.load_deck("casual/gruul-ramp"), read("casual/gruul-ramp").target)
        self.assertEqual(decks.load_deck("commander/gisa-zombies", "owned"), read("commander/gisa-zombies").owned)
        for deck_id, version in [("casual/no-such-deck", "target"), ("casual/../collection", "target"),
                                 ("casual/../casual/gruul-ramp", "target"), ("casual/con", "target"),
                                 ("product/fdn-beginner-box/cats", "owned"), ("product/nope", "target"),
                                 ("pairing/cats+cats", "target"), ("pairing/cats", "target"),
                                 ("casual/gruul-ramp", "sideboard"), ("nonsense", "target")]:
            with self.subTest(deck_id), self.assertRaises(decks.DeckNotFound):
                decks.load_deck(deck_id, version)

    def test_a_hand_named_deck_file_is_read_only_but_opens(self):
        tmp = self.temp_products()
        (tmp / "casual").mkdir()
        shutil.copy(FIXTURE_DECKS / "casual" / "gruul-ramp.md", tmp / "casual" / "Gruul_Ramp.md")
        with mock.patch.object(decks, "DECKS_DIR", tmp):
            listed = [s for s in decks.list_decks() if not s["id"].startswith("product/")]
            self.assertEqual([(s["id"], s["read_only"], s["card_count"]) for s in listed],
                             [("casual/Gruul_Ramp", True, 60)])
            self.assertEqual(decks.load_deck("casual/Gruul_Ramp"), read("casual/gruul-ramp").target)
            self.assertEqual(decks.load_deck("casual/Gruul_Ramp", "owned"), read("casual/gruul-ramp").owned)
            with self.assertRaises(decks.DeckNotFound):
                decks.load_deck("casual/gruul_ramp")
            with self.assertRaises(ValueError):          # but it can't be saved
                deck_files.write_deck_file(tmp / "casual" / "Gruul_Ramp.md", "# x\n", None)

    def test_product_csv_variations(self):
        """A CSV with both deck and section columns, a BOM, CRLF line endings
        and capital set codes; status.csv and card-pool CSVs are skipped."""
        tmp = self.temp_products()
        for path in (FIXTURES / "products").glob("*.csv"):
            shutil.copy(path, tmp / path.name)
        data = (FIXTURES / "products" / "two-decks.csv").read_bytes().replace(b"\r\n", b"\n")
        data = data.replace(b",fdn,", b",FDN,")
        (tmp / "two-decks-crlf.csv").write_bytes(b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n"))
        with self.products_in(tmp):
            by_id = {s["id"]: s for s in decks.list_decks() if s["id"].startswith("product/")}
            self.assertEqual(sorted(by_id), ["product/two-decks-crlf/alpha-team", "product/two-decks-crlf/beta",
                                             "product/two-decks/alpha-team", "product/two-decks/beta"])
            for stem in ("two-decks", "two-decks-crlf"):
                alpha = decks.load_deck(f"product/{stem}/alpha-team")
                self.assertEqual(alpha, {"Deck": [DeckLine(4, "Llanowar Elves", "fdn", "227"),
                                                  DeckLine(1, "Ruby, Daring Tracker", "fdn", "245"),
                                                  DeckLine(15, "Forest", "fdn", None)],
                                         "Sideboard": [DeckLine(2, "Bite Down", "fdn", "212")]})
                self.assertEqual(by_id[f"product/{stem}/beta"]["kind"], "commander")
                self.assertEqual(by_id[f"product/{stem}/beta"]["card_count"], 100)
            self.assertEqual(by_id["product/two-decks/alpha-team"]["title"], "Alpha Team (Two Decks)")
            self.assertEqual(decks.beginner_box_pairings(), [])

    def test_a_bad_product_csv_is_listed_with_its_error(self):
        tmp = self.temp_products()
        shutil.copy(FIXTURES / "products" / "two-decks.csv", tmp)
        head = "section,name,set,collector_number,finish,quantity\n"
        (tmp / "bad-section.csv").write_text(head + "maybeboard,Opt,fdn,512,nonfoil,1\n", encoding="utf-8")
        (tmp / "bad-finish.csv").write_text(head + "deck,Opt,fdn,512,,1\n", encoding="utf-8")
        (tmp / "no-name.csv").write_text("section,set,collector_number,finish,quantity\ndeck,fdn,512,nonfoil,1\n",
                                         encoding="utf-8")
        with self.products_in(tmp):
            by_id = {s["id"]: s for s in decks.list_decks() if s["id"].startswith("product/")}
            for deck_id, error in (("product/bad-section", "unknown section"), ("product/bad-finish", "bad finish"),
                                   ("product/no-name", "no 'name' column")):
                self.assertIn(error, by_id[deck_id]["error"])
                self.assertEqual((by_id[deck_id]["versions"], by_id[deck_id]["card_count"]), ([], 0))
                with self.assertRaisesRegex(decks.DeckFileError, error):
                    decks.load_deck(deck_id)
            self.assertIn("product/two-decks/alpha-team", by_id)          # the rest are still listed
            self.assertNotIn("error", by_id["product/two-decks/alpha-team"])

    def test_a_broken_deck_file_is_listed_with_an_error(self):
        tmp = self.temp_products()
        (tmp / "casual").mkdir()
        (tmp / "casual" / "broken.md").write_text("no title\n", encoding="utf-8")
        shutil.copy(FIXTURES / "hand-edited-deck.md", tmp / "casual" / "hand-edited.md")
        with mock.patch.object(decks, "DECKS_DIR", tmp):
            by_id = {s["id"]: s for s in decks.list_decks()}
        self.assertIn("error", by_id["casual/broken"])
        self.assertEqual(by_id["casual/broken"]["versions"], [])
        hand = by_id["casual/hand-edited"]
        self.assertEqual((hand["player"], hand["status"], hand["versions"], hand["card_count"]),
                         ("wife", "building", ["target"], 13))

    def test_find_summary_and_engine_kind(self):
        # Milestone 7: the deck-id helpers api, forge, goldfish, stats and pool each had a copy of.
        find = decks.find_summary
        self.assertEqual(find("casual/gruul-ramp")["title"], "Gruul Ramp")
        self.assertEqual(find("product/fdn-beginner-box/cats")["id"], "product/fdn-beginner-box/cats")
        for deck_id in ("pairing/cats+vampires", "pairing/vampires+cats"):
            pairing = find(deck_id)
            self.assertEqual(pairing["id"], "pairing/cats+vampires")      # the library's order
            self.assertEqual(sorted(pairing["halves"]), ["product/fdn-beginner-box/cats",
                                                         "product/fdn-beginner-box/vampires"])
        for deck_id in ("casual/nope", "pairing/cats+cats", "pairing/cats+dragons", "pairing/cats",
                        "product/fdn-beginner-box"):
            self.assertIsNone(find(deck_id), deck_id)
        tmp = self.temp_products()
        (tmp / "casual").mkdir()
        (tmp / "casual" / "broken.md").write_text("no title\n", encoding="utf-8")
        with mock.patch.object(decks, "DECKS_DIR", tmp):
            self.assertIn("error", find("casual/broken"))                  # found, with its error

        kind = decks.engine_kind
        self.assertEqual(kind(find("commander/giada-angels")), "commander")
        self.assertEqual(kind(find("product/fdc-calling-all-angels")), "commander")   # a precon
        for deck_id in ("casual/gruul-ramp", "product/fdn-beginner-box/cats", "pairing/cats+vampires",
                        "product/blb-starter-kit/hare-raising"):
            self.assertEqual(kind(find(deck_id)), "constructed", deck_id)

    def test_a_decklist_under_another_heading_is_an_error_not_an_empty_deck(self):
        tmp = self.temp_products()
        (tmp / "casual").mkdir()
        good = (FIXTURE_DECKS / "casual" / "gruul-ramp.md").read_text(encoding="utf-8")
        for slug, heading in (("a", "## Deck list"), ("b", "## Main deck"), ("c", "### Decklist")):
            (tmp / "casual" / f"{slug}.md").write_text(good.replace("## Decklist\n", heading + "\n", 1),
                                                       encoding="utf-8", newline="\n")
        with mock.patch.object(decks, "DECKS_DIR", tmp):
            summaries = decks.list_decks()
            for s in summaries[:3]:
                with self.subTest(s["id"]):
                    self.assertIn("no fenced decklist block under a '## Decklist' heading", s["error"])
                    self.assertEqual((s["title"], s["versions"], s["card_count"]), ("Gruul Ramp", [], 0))
                    with self.assertRaises(decks.DeckFileError):
                        decks.load_deck(s["id"])
            self.assertEqual(decks.load_deck("casual/a", "owned"), read("casual/gruul-ramp").owned)


class PatchedNamesTests(unittest.TestCase):
    """Tests patch these names on decks (mock.patch.object(decks, ...)), so
    each must have its one binding in decks itself, beside everything that
    reads it. A copy in one of decks' submodules, or a submodule reading it
    there, would be out of reach of the patch: sandboxed tests would then
    read and write the real magic/decks and magic/products folders."""

    PATCHED = ("DECKS_DIR", "REPLACE_WAITS", "list_decks",
               "beginner_box_pairings", "load_deck")

    def test_patched_names_are_only_in_the_package_file(self):
        submodules = [info.name for info in pkgutil.iter_modules(decks.__path__)]
        self.assertTrue(submodules)
        for name in self.PATCHED:
            self.assertIn(name, vars(decks))
            value = getattr(decks, name)
            if callable(value):
                self.assertEqual(value.__module__, decks.__name__, name)
            for sub in submodules:
                module = getattr(decks, sub)
                self.assertNotIn(name, vars(module), f"decks.{sub} has its own {name}")
                tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
                used = {n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(tree)
                        if isinstance(n, (ast.Name, ast.Attribute))}
                self.assertFalse(name in used, f"decks.{sub} reads {name}")


if __name__ == "__main__":
    unittest.main()
