"""Tests for decklab.lib.accessories: the accessories inventory (magic/accessories.csv),
resolving deck and product values, holders, the enough-sleeves rule and --check.

Each test builds a small magic/ tree in a temp folder (accessories.csv, its
images, deck files, products with status.csv) and points accessories, decks
and pool at it. Nothing needs the card data or the network.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_accessories
"""
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import accessories, config, decks, inventory
from decklab.lib.accessories import FIELDS
from decklab.lib.inventory.files import FileInventory
from decklab.tests import db_support

HEADER = ",".join(FIELDS) + "\n"
BLACK = "dragon-shield-matte-black,sleeves,shared,Dragon Shield,Matte,black,{qty},,,,,,\n"
BOX = "ultimate-guard-boulder-100-black,deck_box,shared,Ultimate Guard,Boulder 100+,black,{qty},,,,,,\n"
STATUS_HEADER = "file,status,intact,sleeves,deck_box,notes\n"
PROFILES = {"profiles": [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2"}]}


def deck_md(title, status="built", deck="60 Lightning Bolt\n", sideboard="", sleeves=None, deck_box=None,
            owned=None, built_version=None, player="either"):
    lines = [f"# {title}", "", "- **Format:** Casual 60-card, 1v1", f"- **Played by:** {player}",
             f"- **Status:** {status}"]
    if built_version:
        lines.append(f"- **Built version:** {built_version}")
    if sleeves:
        lines.append(f"- **Sleeves:** {sleeves}")
    if deck_box:
        lines.append(f"- **Deck box:** {deck_box}")
    block = "Deck\n" + deck + (f"\nSideboard\n{sideboard}" if sideboard else "")
    text = "\n".join(lines) + f"\n\n## Decklist\n\n```\n{block}```\n"
    if owned is not None:
        text += f"\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n{owned}```\n"
    return text


class AccessoriesTestCase(unittest.TestCase):
    """A temp magic/ tree with no accessories.csv and an empty status.csv."""

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        self.root = root
        self.magic = root / "magic"
        for sub in ("products", "decks/casual", "decks/commander", "accessories/images"):
            (self.magic / sub).mkdir(parents=True)
        for target, name, value in (
                (accessories, "PATH", self.magic / "accessories.csv"),
                (accessories, "IMAGES", self.magic / "accessories" / "images"),
                (decks, "DECKS_DIR", self.magic / "decks"),
                (config, "CONFIG_FILE", root / "config.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (root / "config.json").write_text(json.dumps(PROFILES), encoding="utf-8")
        # The products' status rows (their sleeves and deck boxes) come from the inventory.
        self.addCleanup(inventory.use(FileInventory(root)))
        self.status()

    def write(self, rel, text):
        path = self.magic / rel
        path.write_bytes(text.encode("utf-8"))
        return path

    def inventory(self, *rows):
        self.write("accessories.csv", HEADER + "".join(rows))

    def status(self, *rows):
        self.write("products/status.csv", STATUS_HEADER + "".join(rows))

    def deck(self, slug, *args, **kwargs):
        self.write(f"decks/casual/{slug}.md", deck_md(*args, **kwargs))

    def product(self, stem="test-product", decks_=(("Red", 30), ("Blue", 30)), sideboard=0):
        rows = "deck,section,name,quantity,finish,set,collector_number\n"
        for name, qty in decks_:
            rows += f"{name},deck,Lightning Bolt,{qty},nonfoil,lea,161\n"
            if sideboard:
                rows += f"{name},sideboard,Shock,{sideboard},nonfoil,m19,156\n"
        self.write(f"products/{stem}.csv", rows)


# ------------------------------------------------------------------ rows

class RowTests(unittest.TestCase):
    ROW = {"id": "dragon-shield-matte-black", "kind": "sleeves", "owner": "shared", "brand": "Dragon Shield", "name": "Matte",
           "colour": "black", "quantity": "100", "image": "", "link": "", "image_source": "", "notes": ""}

    def row(self, **changes):
        return {**self.ROW, **changes}

    def test_a_good_row_is_cleaned(self):
        row = accessories.validate_row(self.row(brand="  Dragon \u200b Shield ", notes="two\nlines",
                                                quantity=" 60 "))
        self.assertEqual(row["brand"], "Dragon Shield")
        self.assertEqual(row["notes"], "two lines")
        self.assertEqual(row["quantity"], 60)
        self.assertEqual(list(row), FIELDS)

    def test_an_owner_is_a_profile_id_or_shared(self):
        for owner in ("matt", "user1", "shared"):
            self.assertEqual(accessories.validate_row(self.row(owner=f" {owner} "))["owner"], owner)
        for owner in ("", " ", "Matt", "-a", "matt user1", None):
            with self.subTest(owner), self.assertRaisesRegex(ValueError, "owner"):
                accessories.validate_row(self.row(owner=owner))

    def test_bad_columns_are_refused(self):
        for changes in ({"id": "Dragon"}, {"id": "-a"}, {"id": "a-"}, {"id": "a" * 41}, {"id": "con"},
                        {"id": ""}, {"kind": "box"}, {"name": " "}, {"brand": "b" * 41},
                        {"name": "n" * 81}, {"colour": "c" * 41}, {"notes": "n" * 301},
                        {"quantity": "-1"}, {"quantity": "10000"}, {"quantity": "1.5"}, {"quantity": ""},
                        {"image": "other.jpg"}, {"image": "dragon-shield-matte-black.gif"},
                        {"link": "ftp://x"}, {"link": "javascript:alert(1)"},
                        {"link": "https://x/" + "a" * 500}, {"image_source": "file:///c:/x.jpg"}):
            with self.subTest(changes), self.assertRaises(ValueError):
                accessories.validate_row(self.row(**changes))

    def test_limits_that_are_allowed(self):
        row = accessories.validate_row(self.row(id="a" * 40, image="a" * 40 + ".webp", quantity=9999,
                                                link="HTTP://shop.example/p/1"))
        self.assertEqual(row["quantity"], 9999)
        self.assertEqual(accessories.validate_row(self.row(quantity=0))["quantity"], 0)
        from decklab.lib.api import drafts
        self.assertEqual(accessories.MAX_ID, drafts.MAX_SLEEVES)

    def test_capacity_is_a_deck_boxs_and_optional(self):
        box = self.row(kind="deck_box")
        self.assertIsNone(accessories.validate_row(box)["capacity"])
        self.assertEqual(accessories.validate_row({**box, "capacity": " 100 "})["capacity"], 100)
        self.assertEqual(accessories.validate_row({**box, "capacity": 9999})["capacity"], 9999)
        for capacity in ("0", "10000", "1.5", "lots", True):
            with self.subTest(capacity), self.assertRaises(ValueError):
                accessories.validate_row({**box, "capacity": capacity})
        with self.assertRaisesRegex(ValueError, "only for a deck box"):
            accessories.validate_row(self.row(capacity="100"))

    def test_crop(self):
        pictured = self.row(image="dragon-shield-matte-black.jpg")
        self.assertEqual(accessories.validate_row(pictured)["crop"], "")
        for crop, written in (("0.1,0.2,0.5,0.25", "0.1,0.2,0.5,0.25"), (" 0.1000, .2,0.5,0.5 ", "0.1,0.2,0.5,0.5"),
                              ("0,0,1,1", "0,0,1,1"), ("0.5,0.5,0.5,0.5", "0.5,0.5,0.5,0.5")):
            with self.subTest(crop):
                self.assertEqual(accessories.validate_row({**pictured, "crop": crop})["crop"], written)
        for crop in ("0.6,0,0.5,0.5", "1.5,0,0.1,0.1", "0,0,0.01,0.5", "a,b,c,d", "0.12345,0,0.5,0.5", "0,0,1",
                     "-0.1,0,0.5,0.5"):
            with self.subTest(crop), self.assertRaises(ValueError):
                accessories.validate_row({**pictured, "crop": crop})
        with self.assertRaisesRegex(ValueError, "without a picture"):
            accessories.validate_row(self.row(crop="0,0,0.5,0.5"))

    def test_new_id_is_a_slug_of_brand_name_and_colour(self):
        self.assertEqual(accessories.new_id({"brand": "Dragon Shield", "name": "Matte", "colour": "Black"}, []),
                         "dragon-shield-matte-black")
        self.assertEqual(accessories.new_id({"brand": "Ultimate Guard", "name": "Boulder 100+",
                                             "colour": "Ónyx"}, []), "ultimate-guard-boulder-100-onyx")
        self.assertEqual(accessories.new_id({"name": "!!!"}, []), "accessory")

    def test_new_id_adds_a_suffix_on_a_clash(self):
        row = {"brand": "Dragon Shield", "name": "Matte", "colour": "black"}
        self.assertEqual(accessories.new_id(row, ["dragon-shield-matte-black"]), "dragon-shield-matte-black-2")
        self.assertEqual(accessories.new_id(row, ["dragon-shield-matte-black", "dragon-shield-matte-black-2"]),
                         "dragon-shield-matte-black-3")
        self.assertEqual(accessories.new_id({"name": "Con"}, []), "con-2")

    def test_new_id_stays_within_40_characters(self):
        row = {"brand": "Extremely Long Brand Name", "name": "With A Long Product Line", "colour": "blue"}
        first = accessories.new_id(row, [])
        self.assertEqual(len(first), 40)
        self.assertTrue(accessories.valid_id(first))
        second = accessories.new_id(row, [first])
        self.assertLessEqual(len(second), 40)
        self.assertTrue(second.endswith("-2"))
        self.assertTrue(accessories.valid_id(second))
        self.assertNotEqual(first, second)

    def test_csv_bytes_sorts_by_kind_then_id_with_lf_and_no_bom(self):
        rows = [self.row(id="z-mat", kind="playmat", name="Mat"),
                self.row(id="b-box", kind="deck_box", name="Box"),
                self.row(id="z-sleeves"), self.row(id="a-sleeves", notes='say "hi", ok')]
        data = accessories.csv_bytes(rows)
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r", data)
        ids = [line.split(",")[0] for line in data.decode().splitlines()[1:]]
        self.assertEqual(ids, ["a-sleeves", "z-sleeves", "b-box", "z-mat"])
        self.assertTrue(data.startswith(HEADER.encode()))
        self.assertIn(b'"say ""hi"", ok"', data)

    def test_label(self):
        self.assertEqual(accessories.label(self.ROW), "Dragon Shield Matte (black)")
        self.assertEqual(accessories.label({"brand": "", "name": "Matte", "colour": ""}), "Matte")


# ------------------------------------------------------------------ reading

class ReadTests(AccessoriesTestCase):
    def test_no_file_is_an_empty_inventory(self):
        inv = accessories.read(strict=True)
        self.assertEqual((inv.rows_by_id, inv.sha256, inv.problems), ({}, None, []))

    def test_rows_round_trip(self):
        self.inventory(BOX.format(qty=2), BLACK.format(qty=100))
        inv = accessories.read(strict=True)
        self.assertEqual(list(inv.rows_by_id), ["ultimate-guard-boulder-100-black", "dragon-shield-matte-black"])
        self.assertEqual(inv.rows_by_id["dragon-shield-matte-black"]["quantity"], 100)
        self.assertEqual(len(inv.sha256), 64)
        self.assertEqual(accessories.csv_bytes(inv.rows_by_id.values()),
                         (HEADER + BLACK.format(qty=100) + BOX.format(qty=2)).encode())

    def test_crlf_and_a_bom_are_read(self):
        self.write("accessories.csv", "\ufeff" + (HEADER + BLACK.format(qty=100)).replace("\n", "\r\n"))
        self.assertIn("dragon-shield-matte-black", accessories.read(strict=True).rows_by_id)

    def test_lenient_skips_bad_rows_and_strict_refuses_them(self):
        self.inventory(BLACK.format(qty="lots"), BOX.format(qty=1), BOX.format(qty=3), "x,y\n")
        inv = accessories.read()
        self.assertEqual(list(inv.rows_by_id), ["ultimate-guard-boulder-100-black"])
        self.assertEqual(inv.rows_by_id["ultimate-guard-boulder-100-black"]["quantity"], 1)
        self.assertEqual(len(inv.problems), 3)
        self.assertTrue(inv.problems[0].startswith("accessories.csv line 2: quantity"))
        self.assertIn("line 4: the id ultimate-guard-boulder-100-black is listed twice", inv.problems[1])
        self.assertIn("line 5: 2 values", inv.problems[2])
        with self.assertRaisesRegex(accessories.AccessoriesError,
                                    r"^accessories\.csv line 2: .*; it can't be changed until that's put right$"):
            accessories.read(strict=True)

    def test_strict_needs_the_exact_header(self):
        self.write("accessories.csv", "kind,id,owner,brand,name,colour,quantity,capacity,image,crop,link,"
                                      "image_source,notes\n"
                                      "sleeves,a-b,matt,,Matte,,1,,,,,,\n")
        self.assertIn("a-b", accessories.read().rows_by_id)
        self.assertEqual(len(accessories.read().problems), 1)
        with self.assertRaisesRegex(accessories.AccessoriesError, "line 1: the header"):
            accessories.read(strict=True)
        self.write("accessories.csv", "id,name\n")
        self.assertEqual(accessories.read().rows_by_id, {})

    def test_malformed_csv(self):
        self.write("accessories.csv", HEADER + 'a-b,sleeves,shared,"Dragon" Shield,Matte,,1,,,,,,\n')
        with self.assertRaises(accessories.AccessoriesError):
            accessories.read(strict=True)

    def test_a_cropped_image_url_says_its_crop(self):
        self.inventory(BLACK.format(qty=100).replace(",,,,,,", ",,dragon-shield-matte-black.png,\"0.1,0.2,0.5,0.5\",,,"))
        self.write("accessories/images/dragon-shield-matte-black.png", "png")
        url = accessories.image_url(accessories.read().rows_by_id["dragon-shield-matte-black"])
        self.assertRegex(url, r"^/accessory-img/dragon-shield-matte-black\.png\?v=[0-9a-f]{8}#crop=0\.1,0\.2,0\.5,0\.5$")

    def test_image_url_changes_with_the_picture(self):
        self.inventory(BLACK.format(qty=100).replace(",,,,,,", ",,dragon-shield-matte-black.jpg,,,,"))
        row = accessories.read().rows_by_id["dragon-shield-matte-black"]
        self.assertIsNone(accessories.image_url(row))
        self.write("accessories/images/dragon-shield-matte-black.jpg", "one")
        first = accessories.image_url(row)
        self.assertRegex(first, r"^/accessory-img/dragon-shield-matte-black\.jpg\?v=[0-9a-f]{8}$")
        second = self.write("accessories/images/dragon-shield-matte-black.jpg", "two")
        # The files backend hashes a picture again only when its size or mtime changed, and on
        # Windows two writes this close together can share an mtime: date it a second later, as
        # a picture saved again would be.
        mtime = second.stat().st_mtime_ns + 1_000_000_000
        os.utime(second, ns=(mtime, mtime))
        self.assertNotEqual(accessories.image_url(row), first)
        self.assertIsNone(accessories.image_url({"image": ""}))


# ------------------------------------------------------------------ resolving

class ResolveTests(AccessoriesTestCase):
    def setUp(self):
        super().setUp()
        self.inventory(BLACK.format(qty=100), BOX.format(qty=1))
        self.inv = accessories.read()

    def test_an_id_of_the_right_kind_is_linked(self):
        ref = accessories.resolve(" dragon-shield-matte-black ", "sleeves", self.inv)
        self.assertEqual(set(ref), {"value", "id", "kind", "brand", "name", "colour", "quantity", "capacity", "image_url",
                                    "link", "state", "label"})
        self.assertEqual((ref["state"], ref["id"], ref["quantity"], ref["label"]),
                         ("linked", "dragon-shield-matte-black", 100, "Dragon Shield Matte (black)"))

    def test_an_id_of_another_kind_is_a_mismatch(self):
        ref = accessories.resolve("ultimate-guard-boulder-100-black", "sleeves", self.inv)
        self.assertEqual((ref["state"], ref["kind"]), ("kind_mismatch", "deck_box"))

    def test_anything_else_is_text_never_matched_by_name(self):
        for value in ("red", "Dragon Shield Matte (black)", "Dragon-Shield-Matte-Black", "black"):
            ref = accessories.resolve(value, "sleeves", self.inv)
            self.assertEqual((ref["state"], ref["id"], ref["label"]), ("text", None, value))
        self.assertIsNone(accessories.resolve("  ", "sleeves", self.inv))
        self.assertIsNone(accessories.resolve(None, "sleeves", self.inv))


# ------------------------------------------------------------------ holders

class NeedTests(unittest.TestCase):
    def test_every_section_and_basics_count(self):
        sections = decks.parse_decklist("Commander\n1 Lightning Bolt\n\nCompanion\n1 Lurrus of the Dream-Den\n\n"
                                        "Deck\n50 Mountain\n48 Shock\n\nSideboard\n15 Shock\n")
        self.assertEqual(accessories.sleeve_need(sections), 115)
        self.assertEqual(accessories._need_words(sections),
                         " (1 commander, 1 companion, 98 in the deck, 15 in the sideboard)")
        self.assertEqual(accessories._need_words(decks.parse_decklist("Deck\n60 Mountain\n")), "")


class HolderTests(AccessoriesTestCase):
    def test_built_decks_hold_their_built_version(self):
        self.inventory(BLACK.format(qty=100), BOX.format(qty=2))
        self.deck("otters", "Izzet Otters", deck="60 Shock\n", sideboard="15 Shock\n",
                  sleeves="dragon-shield-matte-black", deck_box="ultimate-guard-boulder-100-black",
                  owned="40 Shock\n", built_version="owned-only")
        self.deck("idea", "Idea Deck", status="idea", sleeves="dragon-shield-matte-black")
        self.deck("gruul", "Gruul", sleeves="red")
        usage = accessories.holders()
        self.assertEqual(usage["dragon-shield-matte-black"], [
            {"holder": "casual/otters", "title": "Izzet Otters", "kind": "deck", "owner": "shared", "field": "sleeves", "need": 40,
             "value": "dragon-shield-matte-black", "state": "linked"}])
        self.assertEqual(usage["ultimate-guard-boulder-100-black"][0]["field"], "deck_box")
        self.assertEqual(usage["red"][0]["state"], "text")
        row = accessories.read().rows_by_id["dragon-shield-matte-black"]
        self.assertEqual([h["holder"] for h in accessories.used_by(usage, row)], ["casual/otters"])

    def test_a_built_deck_without_built_version_uses_its_target(self):
        self.deck("otters", "Izzet Otters", deck="60 Shock\n", sideboard="15 Shock\n", sleeves="red")
        self.assertEqual(accessories.holders()["red"][0]["need"], 75)

    def test_owned_intact_products_hold_their_columns(self):
        self.inventory(BLACK.format(qty=100))
        self.product(sideboard=5)
        self.product("broken-product")
        self.status("test-product.csv,owned,yes,dragon-shield-matte-black,,\n",
                    "broken-product.csv,owned,no,,,\n")
        usage = accessories.holders()
        self.assertEqual(usage["dragon-shield-matte-black"], [
            {"holder": "product/test-product", "title": "test-product", "kind": "product", "owner": "shared", "field": "sleeves",
             "need": 70, "value": "dragon-shield-matte-black", "state": "linked"}])


# ------------------------------------------------------------------ owners

class OwnerTests(AccessoriesTestCase):
    def test_a_file_from_before_owners_is_all_shared(self):
        self.write("accessories.csv", ",".join(accessories.LEGACY_HEADERS[0]) + "\n"
                   + BLACK.replace(",shared,", ",").format(qty=100))
        inv = accessories.read(strict=True)
        self.assertEqual(inv.problems, [])
        self.assertEqual(inv.rows_by_id["dragon-shield-matte-black"]["owner"], "shared")
        self.assertTrue(accessories.csv_bytes(inv.rows_by_id.values()).decode().startswith("id,kind,owner,"))

    def test_a_decks_owner_is_its_players(self):
        self.assertEqual(accessories.owner_ids(), ["matt", "user1", "shared"])
        self.assertEqual([accessories.player_owner(p) for p in ("user", "wife", "either", None, "nobody")],
                         ["matt", "user1", "shared", "shared", "shared"])
        self.assertEqual(accessories.owner_name("user1"), "User1")
        self.assertEqual(accessories.hidden_title("user1"), "one of User1's decks")
        self.assertTrue(accessories.visible("user1", None))
        self.assertFalse(accessories.visible("user1", frozenset({"matt", "shared"})))
        self.assertTrue(accessories.usable("shared", "matt"))
        self.assertTrue(accessories.usable("matt", "matt"))
        self.assertFalse(accessories.usable("user1", "matt"))
        self.assertFalse(accessories.usable("matt", "shared"))
        hers = deck_md("Hers", player="wife", sleeves="dragon-shield-matte-black")
        self.write("decks/casual/hers.md", hers)
        self.inventory(BLACK.format(qty=100))
        self.assertEqual(accessories.holders()["dragon-shield-matte-black"][0]["owner"], "user1")

    def test_a_deck_using_anothers_accessory_warns(self):
        self.inventory(BLACK.replace(",shared,", ",user1,").format(qty=100))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.assertEqual(accessories.kit("casual/otters")["warnings"],
                         ["Sleeves Dragon Shield Matte (black) are User1's: this deck uses only shared ones."])
        self.write("decks/casual/mine.md", deck_md("Mine", player="user", sleeves="dragon-shield-matte-black"))
        self.assertIn("Sleeves Dragon Shield Matte (black) are User1's: Matt's deck uses only Matt's or shared "
                      "ones.", accessories.kit("casual/mine")["warnings"])

    def test_another_owners_deck_is_named_only_as_theirs(self):
        # Both in one shared design (E8-S20: fine, so no warning): hers is named only as User1's.
        self.inventory(BLACK.format(qty=100))
        self.write("decks/casual/hers.md", deck_md("Her Secret Deck", player="wife",
                                                   sleeves="dragon-shield-matte-black"))
        self.write("decks/casual/mine.md", deck_md("Mine", player="user", sleeves="dragon-shield-matte-black"))
        k = accessories.kit("casual/mine", owners=frozenset({"matt", "shared"}))
        self.assertEqual((k["warnings"], k["shared_with"]), ([], ["one of User1's decks"]))
        self.assertEqual(accessories.kit("casual/mine")["shared_with"], ["Her Secret Deck"])

    def test_the_command_line_warns_when_sleeves_already_in_use_are_chosen(self):
        # Matt, 2026-10-19: choosing sleeves another holder has is allowed, with a warning.
        self.inventory(BLACK.format(qty=100))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.assertEqual(accessories.sharing_warning("casual/gruul", "dragon-shield-matte-black"),
                         "Warning: Izzet Otters uses Dragon Shield Matte (black) already. Several decks can share "
                         "one design: just don't play two of them against each other.")
        self.assertIsNone(accessories.sharing_warning("casual/otters", "dragon-shield-matte-black"))
        self.assertIsNone(accessories.sharing_warning("casual/gruul", "no-such-row"))
        self.assertIsNone(accessories.sharing_warning("casual/gruul", None))


# ------------------------------------------------------------------ the rule

class KitTests(AccessoriesTestCase):
    def test_enough_sleeves(self):
        self.inventory(BLACK.format(qty=100), BOX.format(qty=1))
        self.deck("otters", "Izzet Otters", deck="60 Shock\n", sideboard="15 Shock\n",
                  sleeves="dragon-shield-matte-black", deck_box="ultimate-guard-boulder-100-black")
        k = accessories.kit("casual/otters")
        self.assertEqual((k["need"], k["short"], k["spare"], k["warnings"], k["info"]), (75, 0, 25, [], []))
        self.assertEqual((k["sleeves"]["state"], k["deck_box"]["state"]), ("linked", "linked"))
        self.assertEqual(k["title"], "Izzet Otters")

    def test_short_wording(self):
        self.inventory(BLACK.format(qty=60))
        self.deck("otters", "Izzet Otters", deck="60 Shock\n", sideboard="15 Shock\n",
                  sleeves="dragon-shield-matte-black")
        k = accessories.kit("casual/otters")
        self.assertEqual(k["short"], 15)
        self.assertEqual(k["warnings"], [
            "Not enough sleeves: this deck needs 75 (60 in the deck, 15 in the sideboard) and Dragon Shield Matte "
            "(black) has 60. Get 15 more of the same sleeves, or fix the count on the Accessories page."])

    def test_sections_and_values_stand_in_for_the_file(self):
        self.inventory(BLACK.format(qty=60))
        self.deck("otters", "Izzet Otters", deck="60 Shock\n")
        k = accessories.kit("casual/otters", decks.parse_decklist("Deck\n70 Shock\n"),
                            values={"sleeves": "dragon-shield-matte-black"})
        self.assertEqual((k["need"], k["short"]), (70, 10))
        new = accessories.kit(None, decks.parse_decklist("Deck\n50 Shock\n"),
                              values={"sleeves": "dragon-shield-matte-black"})
        self.assertEqual((new["need"], new["spare"], new["warnings"]), (50, 10, []))

    def test_shared_design(self):
        # E8-S20: one design may sleeve several decks; it's named (shared_with), never a warning.
        self.inventory(BLACK.format(qty=200))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.deck("gruul", "Gruul Ramp", sleeves="dragon-shield-matte-black")
        k = accessories.kit("casual/gruul")
        self.assertEqual((k["warnings"], k["shared_with"]), ([], ["Izzet Otters"]))
        self.assertEqual(accessories.kit("casual/otters")["shared_with"], ["Gruul Ramp"])

    def test_shared_design_is_counted_per_holder(self):
        # Each holder against the row's quantity on its own, not the sum: 60 + 60 in 100 sleeves is fine,
        # and only a holder that alone needs more than the row has is short.
        self.inventory(BLACK.format(qty=100))
        self.deck("otters", "Izzet Otters", deck="60 Shock\n", sleeves="dragon-shield-matte-black")
        self.deck("gruul", "Gruul Ramp", deck="60 Shock\n", sleeves="dragon-shield-matte-black")
        self.deck("big", "Big Deck", deck="110 Shock\n", sleeves="dragon-shield-matte-black")
        otters = accessories.kit("casual/otters")
        self.assertEqual((otters["short"], otters["spare"], otters["warnings"]), (0, 40, []))
        big = accessories.kit("casual/big")
        self.assertEqual(big["short"], 10)
        self.assertEqual(big["warnings"], [
            "Not enough sleeves: this deck needs 110 and Dragon Shield Matte (black) has 100. Get 10 more of the "
            "same sleeves, or fix the count on the Accessories page."])
        self.assertEqual(accessories.check(self.root),
                         ["Big Deck needs 110 sleeves and Dragon Shield Matte (black) has 100"])

    def test_same_colour_different_design_is_no_warning(self):
        self.inventory(BLACK.format(qty=200))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.deck("gruul", "Gruul Ramp", sleeves="Black ")
        self.deck("elves", "Elves", sleeves="red")
        self.deck("goblins", "Goblins", sleeves="RED")
        self.assertEqual(accessories.kit("casual/gruul")["warnings"], [])
        self.assertEqual(accessories.kit("casual/goblins")["warnings"], [])

    def test_deck_box_over_quantity(self):
        self.inventory(BOX.format(qty=1))
        self.deck("otters", "Izzet Otters", deck_box="ultimate-guard-boulder-100-black")
        self.deck("gruul", "Gruul Ramp", deck_box="ultimate-guard-boulder-100-black")
        self.assertEqual(accessories.kit("casual/gruul")["warnings"],
                         ["2 decks use Ultimate Guard Boulder 100+ (black) but 1 is recorded."])
        self.inventory(BOX.format(qty=2))
        self.assertEqual(accessories.kit("casual/gruul")["warnings"], [])

    def test_deck_box_too_small(self):
        self.inventory(BOX.format(qty=1).replace(",,,,,,", ",60,,,,,"))
        self.deck("otters", "Izzet Otters", deck_box="ultimate-guard-boulder-100-black", sideboard="15 Shock\n")
        kit = accessories.kit("casual/otters")
        self.assertEqual(kit["deck_box"]["capacity"], 60)
        self.assertEqual(kit["warnings"], [
            "Too big for its deck box: this deck has 75 sleeved cards (60 in the deck, 15 in the sideboard) and "
            "Ultimate Guard Boulder 100+ (black) holds 60. Choose a bigger deck box, or fix its capacity on the "
            "Accessories page."])
        self.inventory(BOX.format(qty=1).replace(",,,,,,", ",75,,,,,"))
        self.assertEqual(accessories.kit("casual/otters")["warnings"], [])
        self.inventory(BOX.format(qty=1))           # not known: nothing to check
        self.assertEqual(accessories.kit("casual/otters")["warnings"], [])

    def test_kind_mismatch(self):
        self.inventory(BLACK.format(qty=100), BOX.format(qty=1))
        self.deck("otters", "Izzet Otters", sleeves="ultimate-guard-boulder-100-black",
                  deck_box="dragon-shield-matte-black")
        self.assertEqual(accessories.kit("casual/otters")["warnings"], [
            "Sleeves “ultimate-guard-boulder-100-black” is a deck box in the accessories list, not sleeves.",
            "Deck box “dragon-shield-matte-black” is sleeves in the accessories list, not a deck box."])

    def test_intact_product_without_sleeves(self):
        self.product("challenger-2019-lightning-aggro", (("", 60),))
        self.status("challenger-2019-lightning-aggro.csv,owned,yes,,,\n")
        k = accessories.kit("product/challenger-2019-lightning-aggro")
        self.assertEqual(k["warnings"], ["Lightning Aggro is kept intact: choose its sleeves (it needs 60)."])
        self.status("challenger-2019-lightning-aggro.csv,owned,no,,,\n")
        self.assertEqual(accessories.kit("product/challenger-2019-lightning-aggro")["warnings"], [])

    def test_a_product_deck_counts_its_whole_product(self):
        self.inventory(BLACK.format(qty=50))
        self.product()
        self.status("test-product.csv,owned,yes,dragon-shield-matte-black,,\n")
        k = accessories.kit("product/test-product/red", decks.parse_decklist("Deck\n30 Shock\n"))
        self.assertEqual((k["holder"], k["need"], k["short"]), ("product/test-product", 60, 10))
        self.assertTrue(k["warnings"][0].startswith("Not enough sleeves: this product needs 60 and "))

    def test_free_text_is_info_not_a_warning(self):
        self.deck("otters", "Izzet Otters", sleeves="Dragon Shield red", deck_box="the tin")
        k = accessories.kit("casual/otters")
        self.assertEqual(k["warnings"], [])
        self.assertEqual(k["info"], [
            "“Dragon Shield red” isn't in the accessories list, so Deck Lab can't check there are enough.",
            "“the tin” isn't in the accessories list, so Deck Lab can't check it's free."])
        self.assertEqual((k["short"], k["spare"]), (0, 0))


# ------------------------------------------------------------------ --check

class CheckTests(AccessoriesTestCase):
    def check(self):
        return accessories.check(self.root)

    def test_all_well(self):
        self.inventory(BLACK.format(qty=100).replace(",,,,,,", ",,dragon-shield-matte-black.png,,,,"))
        self.write("accessories/images/dragon-shield-matte-black.png", "png")
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.assertEqual(self.check(), [])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(accessories.main(["--check"]), 0)
        self.assertIn("no problems", out.getvalue())

    def test_a_deck_box_too_small(self):
        self.inventory(BOX.format(qty=1).replace(",,,,,,", ",50,,,,,"))
        self.deck("otters", "Izzet Otters", deck_box="ultimate-guard-boulder-100-black")
        self.assertEqual(self.check(), ["Izzet Otters has 60 sleeved cards and Ultimate Guard Boulder 100+ (black) holds 50"])

    def test_the_header_before_capacity_is_read(self):
        legacy = ",".join(accessories.LEGACY_HEADERS[2]) + "\n"
        old_box = BOX.replace(",shared,", ",")
        self.write("accessories.csv", legacy + old_box.format(qty=2).replace(",,,,,,", ",,,,"))
        inv = accessories.read(strict=True)
        self.assertEqual(inv.problems, [])
        row = inv.rows_by_id["ultimate-guard-boulder-100-black"]
        self.assertEqual((row["quantity"], row["capacity"], row["crop"]), (2, None, ""))
        self.write("accessories.csv", ",".join(accessories.LEGACY_HEADERS[1]) + "\n"
                   + old_box.format(qty=2).replace(",,,,,,", ",100,,,,"))
        self.assertEqual(accessories.read(strict=True).rows_by_id["ultimate-guard-boulder-100-black"]["capacity"], 100)
        self.assertTrue(accessories.csv_bytes(inv.rows_by_id.values()).startswith(HEADER.encode()))

    def test_no_file_and_no_decks(self):
        self.assertEqual(self.check(), [])

    def test_owners(self):
        self.inventory(BLACK.replace(",shared,", ",user1,").format(qty=100),
                       BOX.replace(",shared,", ",user2,").format(qty=1))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.assertEqual(self.check(), [
            "ultimate-guard-boulder-100-black: its owner 'user2' isn't a home profile or shared",
            "Izzet Otters: Sleeves Dragon Shield Matte (black) are User1's: this deck uses only shared ones."])
        self.write("decks/casual/otters.md", deck_md("Izzet Otters", player="wife",
                                                     sleeves="dragon-shield-matte-black"))
        self.assertEqual(len(self.check()), 1)

    def test_problems(self):
        self.inventory(BLACK.format(qty=50).replace(",,,,,,", ",,dragon-shield-matte-black.png,,,,"),
                       BOX.format(qty=1), "bad,row\n")
        self.write("accessories/images/orphan.jpg", "jpg")
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black",
                  deck_box="ultimate-guard-boulder-100-black")
        self.deck("gruul", "Gruul Ramp", sleeves="dragon-shield-matte-black",
                  deck_box="ultimate-guard-boulder-100-black")
        self.deck("idea", "Idea", status="idea", sleeves="red")
        self.deck("typo", "Typo", sleeves="dragon-shield-matte-blak")
        self.deck("mixed", "Mixed", sleeves="ultimate-guard-boulder-100-black")
        self.product()
        self.status("test-product.csv,owned,no,red,,\n")
        problems = self.check()
        expected = [
            "accessories.csv line 4: 2 values, not 13",
            "dragon-shield-matte-black: its picture magic/accessories/images/dragon-shield-matte-black.png "
            "is missing",
            "magic/accessories/images/orphan.jpg isn't the picture of any row in accessories.csv",
            "casual/idea has Sleeves 'red' but isn't built; remove it",
            "products/status.csv (test-product.csv) has Sleeves 'red' but isn't owned and kept intact; remove it",
            "Typo: Sleeves 'dragon-shield-matte-blak' isn't an id in accessories.csv",
            "Mixed: Sleeves “ultimate-guard-boulder-100-black” is a deck box in the accessories list, not sleeves.",
            "Gruul Ramp needs 60 sleeves and Dragon Shield Matte (black) has 50",
            "Izzet Otters needs 60 sleeves and Dragon Shield Matte (black) has 50",
            "2 decks use Ultimate Guard Boulder 100+ (black) but 1 is recorded",
        ]
        self.assertEqual(sorted(problems), sorted(expected))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(accessories.main(["--check"]), 1)

    def test_a_database_that_cant_be_reached(self):
        # Exit 2, not the 1 of "problems found", with the reason and no traceback; a stale
        # snapshot is checked, with a note.
        root = self.root

        class Down:
            name = "db"

            def load(self):
                raise inventory.Unavailable("connection refused")

        class Stale(Down):
            def load(self):
                return FileInventory(root).load().replace(stale="the database was last read at 09:00")
        self.inventory(BLACK.format(qty=100))
        for backend, code, words in ((Down(), 2, "The database isn't available: connection refused"),
                                     (Stale(), 0, "Note: the database was last read at 09:00.")):
            with self.subTest(backend=type(backend).__name__):
                restore = inventory.use(backend)
                try:
                    with contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(io.StringIO()) as err:
                        self.assertEqual(accessories.main(["--check"]), code)
                finally:
                    restore()
                self.assertIn(words, err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())

    def test_shared_design_and_colour_are_no_problem(self):
        # E8-S20: two holders in one design, or in two designs of one colour, aren't reported.
        self.inventory(BLACK.format(qty=100))
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        self.deck("gruul", "Gruul Ramp", sleeves="black")
        self.deck("elves", "Elves", sleeves="dragon-shield-matte-black")
        self.assertEqual(self.check(), [])


# ------------------------------------------------------------------ the database backend

class _ImportedOnLoad:
    """The database backend over a test's tree: every load first imports the tree as it is now
    (its products/status.csv kept in memory, never on disk), so the product rows the readers see
    are the database's."""
    name = "db"

    def __init__(self, case, backend):
        self.case, self.backend = case, backend

    def load(self):
        from decklab.lib import decks, spaces
        from decklab.lib.inventory import files, pg
        from decklab.tests.test_inventory_contract import CLAUDE, adapt
        inv = FileInventory(self.case.root).load()
        inv = inv.replace(status=files.status_sheet(self.case.status_text.encode("utf-8")))
        # The deck parts where the test's patched folders say (the database backend reads none).
        parts = FileInventory(self.case.root, decks_dir=lambda: decks.DECKS_DIR, people_dir=spaces.people_dir,
                              accessories=lambda: accessories.PATH, images=lambda: accessories.IMAGES)
        found = parts.load()
        inv = inv.replace(decks=found.decks, accessories=found.accessories,
                          accessory_images=found.accessory_images, decks_revision=found.decks_revision)
        pg.write_model(adapt(inv), CLAUDE, "Import the test tree", contents={}, replace=True,
                       dbname=self.case.dbname, decks=True,
                       images={name: parts.image(name) for name in found.accessory_images})
        return self.backend.load()

    def reachable(self):
        return True


class DatabaseProductTests(AccessoriesTestCase, db_support.DbTestCase):
    """The product holder tests with the products, their status rows, the decks and the
    accessories in a throwaway database (imported from the test's tree at each load). CheckTests'
    test_problems isn't run here: its broken accessories.csv and missing pictures are what the
    database can't hold."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        (self.magic / "products" / "status.csv").unlink(missing_ok=True)
        backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(_ImportedOnLoad(self, backend)))

    def status(self, *rows):
        self.status_text = STATUS_HEADER + "".join(rows)

    def tearDown(self):
        self.assertFalse((self.magic / "products" / "status.csv").exists())
        super().tearDown()

    test_owned_intact_products_hold_their_columns = HolderTests.test_owned_intact_products_hold_their_columns
    test_intact_product_without_sleeves = KitTests.test_intact_product_without_sleeves
    test_a_product_deck_counts_its_whole_product = KitTests.test_a_product_deck_counts_its_whole_product


if __name__ == "__main__":
    unittest.main()
