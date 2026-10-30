"""Tests for phase 4's accessory, picture and kit operations (lib/inventory/ops_accessories.py:
accessory.add/edit/remove, image.put/remove and kit.set; the phase 4 design's R4 and R6), run the
same way on both backends: a files backend over a small magic/ tree, and the database backend over
that tree imported into a throwaway database (decks and accessories included, the files then
deleted). The pages' answers are test_api_accessories.py's.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inventory_accessories
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import accessories, config, decks, inventory
from decklab.lib.inventory import Op, kit, ops_accessories, ops_decks  # noqa: F401 (registers the operations)
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor, Invalid
from decklab.tests import db_support
from decklab.tests.test_accessories import PROFILES, STATUS_HEADER, deck_md
from decklab.tests.test_accessory_fetch import jpeg, png

MATT = Actor("matt", "Matt", "home")
HEADER = ",".join(accessories.FIELDS) + "\n"
ACCESSORIES = (HEADER
               + "a-sleeves,sleeves,matt,DS,Matte,red,100,,a-sleeves.jpg,,,,\n"
               + "c-sleeves,sleeves,shared,DS,Matte,blue,100,,,,,,\n"
               + "d-sleeves,sleeves,user1,DS,Matte,pink,100,,,,,,\n"
               + "b-box,deck_box,shared,UG,Boulder,black,1,100,,,,,\n"
               + "e-box,deck_box,shared,UG,Empty,grey,0,,,,,,\n")
PRODUCT = "deck,section,name,quantity,finish,set,collector_number\nRed,deck,Lightning Bolt,60,nonfoil,lea,161\n"
MATT_OWNERS = frozenset({"matt", "shared"})


class _Ops:
    """The operations on one backend (install() makes it); the tree: casual/mine (built, Played by
    user: Matt's), casual/either (built, shared), casual/hers (built, User1's), casual/idea (an
    idea), an owned intact product, and accessories.csv with one picture."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.magic = self.root / "magic"
        for target, name, value in ((decks, "DECKS_DIR", self.magic / "decks"),
                                    (accessories, "PATH", self.magic / "accessories.csv"),
                                    (accessories, "IMAGES", self.magic / "accessories" / "images"),
                                    (config, "CONFIG_FILE", self.root / "config.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.root / "config.json").write_text(json.dumps(PROFILES), encoding="utf-8")
        self.picture = jpeg()
        for rel, text in (("decks/casual/mine.md", deck_md("Mine", player="user")),
                          ("decks/casual/either.md", deck_md("Either")),
                          ("decks/casual/hers.md", deck_md("Hers", player="wife")),
                          ("decks/casual/idea.md", deck_md("Idea", status="idea")),
                          ("products/test-product.csv", PRODUCT),
                          ("products/status.csv", STATUS_HEADER + "test-product.csv,owned,yes,,,\n"),
                          ("collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
                                             "Plains,fdn,272,nonfoil,1,,,\n"),
                          ("accessories.csv", ACCESSORIES),
                          ("accessories/images/a-sleeves.jpg", self.picture)):
            path = self.magic / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        self.install()

    def install(self):
        self.backend = FileInventory(self.root)
        self.addCleanup(inventory.use(self.backend))

    def apply(self, kind, **params):
        return inventory.apply(Op(kind, params), MATT, kind)

    def token(self, owners=None):
        return accessories.view_sha256(accessories.read(), owners)

    def rows(self):
        return accessories.read().rows_by_id

    def text(self, deck_id):
        return inventory.current().deck(deck_id).text

    def refused(self, kind, code, reason=None, **params):
        with self.assertRaises(ops_accessories.AccessoryRefused) as caught:
            self.apply(kind, **params)
        self.assertEqual((caught.exception.code, caught.exception.reason), (code, reason), str(caught.exception))
        return caught.exception

    def holder(self, deck_id):
        return {"id": deck_id, "expected": inventory.current().deck(deck_id).sha256}

    # ---- the rows

    def test_add_edit_and_remove_with_pictures(self):
        after, summary = self.apply("accessory.add", row={"kind": "playmat", "owner": "matt", "name": "Mat", "quantity": 1},
                                    sha256=self.token(MATT_OWNERS), owners=MATT_OWNERS, image=png())
        self.assertEqual(summary.extra["id"], "mat")
        self.assertEqual(self.rows()["mat"]["image"], "mat.png")
        self.assertEqual(inventory.image("mat.png"), png())
        self.apply("accessory.edit", id="mat", row={"quantity": 2}, sha256=self.token(MATT_OWNERS),
                   owners=MATT_OWNERS, image=jpeg())
        self.assertIsNone(inventory.current().image_meta("mat.png"))
        self.assertEqual(inventory.image("mat.jpg"), jpeg())
        self.apply("accessory.remove", id="mat", sha256=self.token(MATT_OWNERS), owners=MATT_OWNERS)
        self.assertNotIn("mat", self.rows())
        self.assertIsNone(inventory.current().image_meta("mat.jpg"))

    def test_a_token_is_the_viewers_and_a_stale_one_refuses(self):
        user1 = frozenset({"user1", "shared"})
        mine = self.token(MATT_OWNERS)
        self.apply("accessory.edit", id="d-sleeves", row={"quantity": 50}, sha256=self.token(user1), owners=user1)
        self.assertEqual(self.token(MATT_OWNERS), mine)          # her row: nothing Matt sees changed
        self.apply("accessory.edit", id="c-sleeves", row={"quantity": 90}, sha256=mine, owners=MATT_OWNERS)
        self.refused("accessory.edit", 409, "changed", id="c-sleeves", row={"quantity": 80}, sha256=mine,
                     owners=MATT_OWNERS)
        self.refused("accessory.edit", 409, "deleted", id="d-sleeves", row={"quantity": 80}, sha256=mine,
                     owners=MATT_OWNERS)
        self.refused("accessory.edit", 404, id="d-sleeves", row={"quantity": 80}, sha256=self.token(MATT_OWNERS),
                     owners=MATT_OWNERS)
        with self.assertRaises(Invalid):
            self.apply("accessory.add", row={"kind": "sleeves", "name": "X", "image": "x.png"},
                       sha256=self.token(None), owners=None)

    def test_a_picture_must_be_a_picture(self):
        for content in (b"<svg/>", "text", b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)):
            with self.subTest(content=content[:8]), self.assertRaises(Invalid):
                self.apply("accessory.add", row={"kind": "playmat", "owner": "matt", "name": "Mat", "quantity": 1},
                           sha256=self.token(None), owners=None, image=content)

    # ---- pictures

    def test_image_put_and_remove(self):
        self.apply("image.put", name="c-sleeves.png", content=png())
        self.assertEqual(self.rows()["c-sleeves"]["image"], "c-sleeves.png")
        self.apply("image.put", name="c-sleeves.jpg", content=jpeg())
        self.assertIsNone(inventory.current().image_meta("c-sleeves.png"))
        self.assertEqual(self.rows()["c-sleeves"]["image"], "c-sleeves.jpg")
        self.apply("image.remove", name="c-sleeves.jpg")
        self.assertEqual(self.rows()["c-sleeves"]["image"], "")
        self.assertIsNone(inventory.current().image_meta("c-sleeves.jpg"))
        for name, content in (("c-sleeves.png", jpeg()), ("Bad.png", png()), ("c-sleeves.gif", png())):
            with self.subTest(name=name), self.assertRaises(Invalid):
                self.apply("image.put", name=name, content=content)
        self.refused("image.put", 404, name="nobody.png", content=png())
        self.refused("image.remove", 404, name="nobody.png")

    # ---- kit.set

    def test_kit_set_moves_between_a_deck_and_a_product_in_one_change(self):
        status = kit.status_sha256(inventory.current())
        self.apply("kit.set", holders=[self.holder("casual/mine"), {"id": "product/test-product", "expected": status}],
                   changes=[{"holder": "casual/mine", "field": "sleeves", "value": "a-sleeves"},
                            {"holder": "product/test-product", "field": "deck_box", "value": "b-box"}],
                   owners=MATT_OWNERS)
        self.assertIn("- **Sleeves:** a-sleeves\n", self.text("casual/mine"))
        self.assertEqual(inventory.current().status.rows[0].text("deck_box"), "b-box")
        # A move: taken from the product only while it still has it, and given to the deck.
        self.apply("kit.set", holders=[self.holder("casual/either"), {"id": "product/test-product", "expected": None}],
                   changes=[{"holder": "product/test-product", "field": "deck_box", "value": None, "expect": "b-box"},
                            {"holder": "casual/either", "field": "deck_box", "value": "b-box"}],
                   owners=MATT_OWNERS)
        self.assertEqual(inventory.current().status.rows[0].text("deck_box"), "")
        self.assertIn("- **Deck box:** b-box\n", self.text("casual/either"))

    def test_kit_set_refusals(self):
        mine = self.holder("casual/mine")
        cases = [
            ({"holders": [{"id": "casual/nope", "expected": None}], "changes": []}, 404, None),
            ({"holders": [{**mine, "expected": "0" * 64}], "changes": []}, 409, "changed"),
            ({"holders": [self.holder("casual/hers")],
              "changes": [{"holder": "casual/hers", "field": "sleeves", "value": "c-sleeves"}]}, 403, None),
            ({"holders": [mine], "changes": [{"holder": "casual/mine", "field": "sleeves", "value": "d-sleeves"}]},
             400, None),                                        # User1's: Matt doesn't see it
            ({"holders": [self.holder("casual/either")],
              "changes": [{"holder": "casual/either", "field": "sleeves", "value": "a-sleeves"}]}, 400, None),
            ({"holders": [mine], "changes": [{"holder": "casual/mine", "field": "sleeves", "value": "b-box"}]},
             400, None),                                        # the wrong kind
            ({"holders": [self.holder("casual/idea")],
              "changes": [{"holder": "casual/idea", "field": "sleeves", "value": "c-sleeves"}]}, 400, None),
            ({"holders": [mine], "changes": [{"holder": "casual/mine", "field": "deck_box", "value": "e-box"}]},
             409, None),                                        # quantity 0
        ]
        for n, (params, code, reason) in enumerate(cases):
            with self.subTest(n=n):
                self.refused("kit.set", code, reason, owners=MATT_OWNERS, **params)
        for params in ({"holders": [mine], "changes": [{"holder": "casual/other", "field": "sleeves", "value": None}]},
                       {"holders": [mine], "changes": [{"holder": "casual/mine", "field": "colour", "value": None}]},
                       {"holders": [mine, mine], "changes": []},
                       # Unchecked only for a holder whose every change has expect.
                       {"holders": [{**mine, "expected": None}],
                        "changes": [{"holder": "casual/mine", "field": "sleeves", "value": "a-sleeves"}]},
                       {"holders": [{**mine, "expected": None}],
                        "changes": [{"holder": "casual/mine", "field": "sleeves", "value": None, "expect": ""},
                                    {"holder": "casual/mine", "field": "deck_box", "value": "b-box"}]}):
            with self.subTest(params=params), self.assertRaises(Invalid):
                self.apply("kit.set", owners=MATT_OWNERS, **params)

    def test_taken_sleeves_and_deck_boxes(self):
        self.apply("kit.set", holders=[self.holder("casual/mine")],
                   changes=[{"holder": "casual/mine", "field": "deck_box", "value": "b-box"},
                            {"holder": "casual/mine", "field": "sleeves", "value": "c-sleeves"}], owners=None)
        either = self.holder("casual/either")
        # A deck box every one of which is held is taken; sleeves another holder has never are (E8-S20).
        e = self.refused("kit.set", 409, "taken", holders=[either], owners=frozenset({"user1", "shared"}),
                         changes=[{"holder": "casual/either", "field": "deck_box", "value": "b-box"}])
        self.assertEqual(e.extra["taken_by"], [{"holder": None, "title": "one of Matt's decks"}])
        self.apply("kit.set", holders=[either], owners=frozenset({"user1", "shared"}),
                   changes=[{"holder": "casual/either", "field": "sleeves", "value": "c-sleeves"}])
        self.assertIn("- **Sleeves:** c-sleeves\n", self.text("casual/either"))
        self.assertIn("- **Sleeves:** c-sleeves\n", self.text("casual/mine"))
        # An intact product may share them too.
        product = {"id": "product/test-product", "expected": kit.status_sha256(inventory.current())}
        self.apply("kit.set", holders=[product], owners=None,
                   changes=[{"holder": "product/test-product", "field": "sleeves", "value": "c-sleeves"}])
        users = accessories.used_by(accessories.holders(), self.rows()["c-sleeves"])
        self.assertEqual(sorted(h["holder"] for h in users), ["casual/either", "casual/mine", "product/test-product"])
        # Clearing works on any deck, and asking again for what a holder has takes nothing new.
        self.apply("kit.set", holders=[self.holder("casual/idea")],
                   changes=[{"holder": "casual/idea", "field": "sleeves", "value": None}], owners=None)
        self.apply("kit.set", holders=[self.holder("casual/mine")],
                   changes=[{"holder": "casual/mine", "field": "sleeves", "value": "c-sleeves"}], owners=None)

    def test_a_loose_change_is_checked_as_a_deck_save_is(self):
        # The editor's header values: free text kept, shared sleeves and the wrong kind left to warnings.
        self.apply("kit.set", holders=[self.holder("casual/mine")],
                   changes=[{"holder": "casual/mine", "field": "sleeves", "value": "c-sleeves"}], owners=None)
        either = self.holder("casual/either")
        self.apply("kit.set", holders=[either], owners=MATT_OWNERS, changes=[
            {"holder": "casual/either", "field": "sleeves", "value": "c-sleeves", "loose": True},
            {"holder": "casual/either", "field": "deck_box", "value": "Old red box", "loose": True}])
        self.assertIn("- **Sleeves:** c-sleeves\n", self.text("casual/either"))
        self.assertIn("- **Deck box:** Old red box\n", self.text("casual/either"))
        self.apply("kit.set", holders=[self.holder("casual/mine")], owners=MATT_OWNERS, changes=[
            {"holder": "casual/mine", "field": "deck_box", "value": "a-sleeves", "loose": True}])
        # Still refused: an id the asker doesn't see, one the deck may not use, a deck that isn't built.
        for holder, value, code in (("casual/mine", "d-sleeves", 400), ("casual/either", "a-sleeves", 400),
                                    ("casual/idea", "Green", 400)):
            with self.subTest(holder=holder, value=value):
                self.refused("kit.set", code, holders=[self.holder(holder)], owners=MATT_OWNERS, changes=[
                    {"holder": holder, "field": "sleeves", "value": value, "loose": True}])

    def test_a_used_row_cant_be_removed_change_kind_or_owner(self):
        self.apply("kit.set", holders=[self.holder("casual/either")],
                   changes=[{"holder": "casual/either", "field": "sleeves", "value": "c-sleeves"}], owners=None)
        token = self.token(None)
        for kind, params in (("accessory.remove", {}), ("accessory.edit", {"row": {"kind": "playmat"}}),
                             ("accessory.edit", {"row": {"owner": "matt"}})):
            with self.subTest(kind=kind, params=params):
                e = self.refused(kind, 409, "blocks", id="c-sleeves", sha256=token, owners=None, **params)
                self.assertEqual(e.extra["blocks"], [{"id": "casual/either", "title": "Either"}])

    def test_a_preview_writes_nothing(self):
        before = self.text("casual/mine")
        after, _ = inventory.preview(Op("kit.set", {"holders": [self.holder("casual/mine")], "changes": [
            {"holder": "casual/mine", "field": "sleeves", "value": "a-sleeves"}], "owners": None}))
        self.assertIn("Sleeves", after.deck("casual/mine").text)
        self.assertEqual(self.text("casual/mine"), before)


class FileOpsTests(_Ops, unittest.TestCase):
    """The operations on the files backend."""


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseOpsTests(_Ops, db_support.DbTestCase):
    """The operations on the database backend, the tree imported and its files deleted."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def install(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import CLAUDE, adapt
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(adapt(FileInventory(self.root).load()), CLAUDE, "Import the inventory", contents={},
                       dbname=self.dbname, decks=True, images={"a-sleeves.jpg": self.picture})
        for rel in ("decks", "accessories"):
            shutil.rmtree(self.magic / rel)
        (self.magic / "accessories.csv").unlink()
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def test_nothing_reaches_the_files(self):
        self.apply("image.put", name="c-sleeves.png", content=png())
        self.assertFalse((self.magic / "accessories").exists())
        self.assertFalse((self.magic / "accessories.csv").exists())
        with self.connect() as c:
            self.assertEqual(sorted(r[0] for r in c.execute("select file_name from accessory_image").fetchall()),
                             ["a-sleeves.jpg", "c-sleeves.png"])


if __name__ == "__main__":
    unittest.main()
