"""Tests for decklab.lib.api.accessories: the Accessories page's writes, each one inventory
operation (lib/inventory/ops_accessories.py) on either backend.

Each test builds a small magic/ tree in a temp folder (deck files, a product and status.csv, and
accessories.csv once a test adds it) and installs a files backend over it (no git: phase 4's
writes never commit), or, in the database tests, imports the tree into a throwaway database and
deletes the deck and accessory files, so every read and write is the database's. Nothing touches
the real repo, its decklab/data/ or the network.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_api_accessories
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, accessories, accessory_fetch, config, decks, inventory
from decklab.lib.api import accessories as api_acc
from decklab.lib.api import common
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, ops_accessories, rules
from decklab.lib.inventory import kit as product_kit
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor
from decklab.tests import db_support
from decklab.tests.test_accessories import PROFILES, STATUS_HEADER, deck_md
from decklab.tests.test_accessory_fetch import jpeg, png

SLEEVES = {"kind": "sleeves", "owner": "shared", "brand": "Dragon Shield", "name": "Matte", "colour": "black", "quantity": 100}
BOX_ROW = {"kind": "deck_box", "owner": "shared", "brand": "Ultimate Guard", "name": "Boulder 100+", "colour": "black",
           "quantity": 1}
BLACK = "dragon-shield-matte-black"
BOX = "ultimate-guard-boulder-100-black"
PRODUCT = "deck,section,name,quantity,finish,set,collector_number\nRed,deck,Lightning Bolt,60,nonfoil,lea,161\n"
NAMES = {p["id"]: p["name"] for p in PROFILES["profiles"]}
BY_ID = {p["id"]: p for p in PROFILES["profiles"]}
CURRENT_STATUS_HEADER = ",".join(rules.STATUS_FIELDS) + "\n"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_version(data):
    from decklab.lib.inventory.model import ImageMeta
    return accessories.image_version(ImageMeta.of("picture.png", data))


class AccessoriesApiTestCase(unittest.TestCase):
    """A temp magic/ tree: casual/otters (built), casual/gruul (built), casual/idea (an idea),
    an intact owned product and no accessories list, over a files backend."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.magic = self.root / "magic"
        self.data = self.root / "decklab" / "data"
        for sub in ("products", "decks/casual", "decks/commander"):
            (self.magic / sub).mkdir(parents=True)
        self.logs = []
        for target, name, value in (
                (config, "REPO", self.root), (config, "DATA", self.data), (config, "MAGIC", self.magic),
                (decks, "DECKS_DIR", self.magic / "decks"),
                (accessories, "PATH", self.magic / "accessories.csv"),
                (accessories, "IMAGES", self.magic / "accessories" / "images"),
                (accessory_fetch, "STAGED", self.data / "accessories" / "staged"),
                (common, "_log", self.logs.append),
                (config, "CONFIG_FILE", self.root / "config.json"),
                (api_acc, "_writer", lambda data: dict(BY_ID[data.get("profile")]))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.root / "config.json").write_text(json.dumps(PROFILES), encoding="utf-8")
        self.write("decks/casual/otters.md", deck_md("Izzet Otters", sideboard="15 Shock\n"))
        self.write("decks/casual/gruul.md", deck_md("Gruul Ramp"))
        self.write("decks/casual/idea.md", deck_md("Idea Deck", status="idea"))
        self.write("decks/casual/hers.md", deck_md("Her Deck", player="wife"))
        self.write("products/test-product.csv", PRODUCT)
        self.write("products/status.csv", STATUS_HEADER + "test-product.csv,owned,yes,,,\n")
        self.install()

    def install(self):
        self.inventory = FileInventory(self.root.resolve())
        self.addCleanup(inventory.use(self.inventory))

    # ---- helpers

    def write(self, rel, text):
        path = self.magic / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return path

    def deck_text(self, slug):
        return inventory.current().deck(f"casual/{slug}").text

    def call(self, function, **data):
        data = {"profile": "matt", **data}
        with inventory.pinned():                # one snapshot per request, as server_http pins it
            return function(json.dumps(data).encode())

    def save(self, **data):
        return self.call(api_acc.save_accessory, **data)

    def view(self, profile="matt"):
        with access.viewing(profile), inventory.pinned():
            return api_acc.accessories_view()

    def add(self, row=None, image=None, profile="matt"):
        return self.save(profile=profile, sha256=self.view(profile)["sha256"], action="add", row=row or SLEEVES,
                         **({"image": image} if image is not None else {}))

    def staged(self, data):
        return {"token": accessory_fetch.stage(data, accessory_fetch.sniff(data))}

    def error(self, function, **data):
        with self.assertRaises(ApiError) as caught:
            self.call(function, **data)
        return caught.exception

    def deck_sha(self, slug):
        return inventory.current().deck(f"casual/{slug}").sha256

    def status_sha(self):
        """A product holder's holder_sha256: status.csv as rendered from the inventory (the API's)."""
        return accessories.status_sha256()

    def assign(self, holder, value, field="sleeves", sha=None, **extra):
        if sha is None:
            sha = self.status_sha() if holder.startswith("product/") else self.deck_sha(holder.split("/")[1])
        return self.call(api_acc.assign_accessory, holder=holder, field=field, id=value, holder_sha256=sha, **extra)

    def applies(self):
        """A mock wrapping inventory.apply, to count the changes a request makes."""
        patcher = mock.patch.object(inventory, "apply", side_effect=inventory.apply)
        found = patcher.start()
        self.addCleanup(patcher.stop)
        return found


class SaveTests(AccessoriesApiTestCase):

    def test_add_with_a_picture_is_one_change_of_the_list_and_its_picture(self):
        self.assertEqual(self.view()["exists"], False)
        picture = png()
        applied = self.applies()
        answer = self.add(image=self.staged(picture))
        self.assertEqual(applied.call_count, 1)
        self.assertEqual(applied.call_args.args[0].kind, "accessory.add")
        self.assertEqual(answer["changed_id"], BLACK)
        self.assertNotIn("commit", answer)
        image = self.magic / "accessories" / "images" / f"{BLACK}.png"
        self.assertEqual(image.read_bytes(), picture)
        item = answer["data"]["items"][0]
        self.assertEqual((item["id"], item["quantity"], item["image"]), (BLACK, 100, f"{BLACK}.png"))
        self.assertEqual(item["image_url"], f"/accessory-img/{BLACK}.png?v={image_version(picture)}")
        self.assertEqual(list(accessory_fetch.STAGED.iterdir()), [])
        raw = accessories.PATH.read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(sorted(answer["data"]), ["exists", "holders_options", "items", "owners", "problems",
                                                  "products", "sha256"])

    def test_edit_replaces_the_picture_and_removes_the_old_one(self):
        self.add(image=self.staged(png()))
        view = self.view()
        answer = self.save(sha256=view["sha256"], action="edit", id=BLACK, base=view["items"][0],
                           row={"quantity": 60, "notes": "Loose ones too"}, image=self.staged(jpeg()))
        images = self.magic / "accessories" / "images"
        self.assertEqual(sorted(p.name for p in images.iterdir()), [f"{BLACK}.jpg"])
        self.assertEqual(answer["data"]["items"][0]["quantity"], 60)
        self.assertEqual(answer["data"]["items"][0]["image"], f"{BLACK}.jpg")

    def test_a_deck_box_capacity_is_saved_and_cleared_with_its_kind(self):
        box = {"kind": "deck_box", "brand": "Ultra Pro", "name": "80 Card Deck Box", "colour": "black",
               "quantity": 2, "capacity": "80"}
        rid = self.add(box)["changed_id"]
        item = next(i for i in self.view()["items"] if i["id"] == rid)
        self.assertEqual(item["capacity"], 80)
        self.assertIn(",2,80,", (self.magic / "accessories.csv").read_text(encoding="utf-8"))
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"capacity": None})
        self.assertIsNone(next(i for i in self.view()["items"] if i["id"] == rid)["capacity"])
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"capacity": 100})
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"kind": "playmat"})
        self.assertIsNone(next(i for i in self.view()["items"] if i["id"] == rid)["capacity"])
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="add",
                       row={**SLEEVES, "capacity": 100})
        self.assertEqual(e.status, 400)
        self.assertIn("only for a deck box", str(e))

    def test_a_crop_is_kept_with_its_picture_and_cleared_with_a_new_one(self):
        rid = self.add(image=self.staged(png()))["changed_id"]
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"crop": "0.1,0.1,0.5,0.5"})
        item = self.view()["items"][0]
        self.assertEqual(item["crop"], "0.1,0.1,0.5,0.5")
        self.assertTrue(item["image_url"].endswith("#crop=0.1,0.1,0.5,0.5"))
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"notes": "kept"})
        self.assertEqual(self.view()["items"][0]["crop"], "0.1,0.1,0.5,0.5")
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={}, image=self.staged(jpeg()))
        self.assertEqual(self.view()["items"][0]["crop"], "")
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={"crop": "0,0,0.5,1"},
                  image=self.staged(png()))
        self.assertEqual(self.view()["items"][0]["crop"], "0,0,0.5,1")
        self.save(sha256=self.view()["sha256"], action="edit", id=rid, row={}, image=None)
        self.assertEqual((self.view()["items"][0]["image"], self.view()["items"][0]["crop"]), ("", ""))
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=rid,
                       row={"crop": "0,0,0.5,0.5"})
        self.assertEqual(e.status, 400)

    def test_edit_keeps_or_removes_the_picture(self):
        self.add(image=self.staged(png()))
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={"colour": "black"}, image="keep")
        self.assertTrue((self.magic / "accessories" / "images" / f"{BLACK}.png").exists())
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={}, image=None)
        self.assertFalse((self.magic / "accessories" / "images" / f"{BLACK}.png").exists())
        self.assertEqual(self.view()["items"][0]["image"], "")

    def test_remove_deletes_the_row_and_its_picture(self):
        self.add(image=self.staged(png()))
        answer = self.save(sha256=self.view()["sha256"], action="remove", id=BLACK)
        self.assertEqual(answer["data"]["items"], [])
        self.assertFalse((self.magic / "accessories" / "images" / f"{BLACK}.png").exists())
        # A list with no rows is no list (both backends: the database can't hold a header alone).
        self.assertFalse(accessories.PATH.exists())
        self.assertEqual((answer["data"]["exists"], answer["data"]["sha256"]), (False, None))

    def test_ids_clash_get_a_suffix_and_bad_rows_are_400(self):
        self.add()
        self.assertEqual(self.add()["changed_id"], f"{BLACK}-2")
        for row in ({**SLEEVES, "quantity": -1}, {**SLEEVES, "kind": "box"}, {**SLEEVES, "name": ""},
                    {**SLEEVES, "id": "chosen"}, {**SLEEVES, "link": "javascript:alert(1)"}):
            with self.subTest(row=row), self.assertRaises(ApiError) as caught:
                self.add(row)
            self.assertEqual(caught.exception.status, 400)

    def test_an_expired_picture_is_409(self):
        e = self.error(api_acc.save_accessory, sha256=None, action="add", row=SLEEVES, image={"token": "0" * 32})
        self.assertEqual(e.status, 409)
        self.assertFalse(accessories.PATH.exists())

    def test_a_changed_list_is_409_with_the_latest_view(self):
        self.add()
        old = self.view()["sha256"]
        self.save(sha256=old, action="edit", id=BLACK, row={"quantity": 80})
        e = self.error(api_acc.save_accessory, sha256=old, action="edit", id=BLACK, row={"quantity": 90})
        self.assertEqual(e.status, 409)
        # The files backend keeps no history: who changed it isn't known.
        self.assertEqual(e.extra["conflict"], {"reason": "changed", "by": None, "deck_lab": False, "when": None,
                                               "subject": None})
        self.assertEqual(e.extra["latest"]["items"][0]["quantity"], 80)
        self.assertEqual(e.message, "The accessories list changed after you opened it: it was changed. Your changes "
                                    "weren't saved.")

    def test_the_operation_checks_the_token_again(self):
        # A change between the page's check and the operation's (under the inventory's lock).
        self.add()
        old = self.view()["sha256"]
        real = inventory.apply

        def meanwhile(op, *args, **kwargs):
            with inventory.pinned():
                with mock.patch.object(inventory, "apply", real):
                    real(inventory.Op("accessory.edit", {"id": BLACK, "row": {"quantity": 70}, "sha256": old,
                                                         "owners": None}), Actor("user1", "User1", "home"), "edit")
            return real(op, *args, **kwargs)
        with mock.patch.object(inventory, "apply", side_effect=meanwhile):
            e = self.error(api_acc.save_accessory, sha256=old, action="edit", id=BLACK, row={"quantity": 90})
        self.assertEqual((e.status, e.extra["conflict"]["reason"]), (409, "changed"))
        self.assertEqual(accessories.read().rows_by_id[BLACK]["quantity"], 70)
        # "latest" is the list after the other write, not the request's pinned snapshot, so its
        # token saves at once.
        latest = e.extra["latest"]
        self.assertEqual(latest["items"][0]["quantity"], 70)
        self.assertNotEqual(latest["sha256"], old)
        self.save(sha256=latest["sha256"], action="edit", id=BLACK, row={"quantity": 90})
        self.assertEqual(accessories.read().rows_by_id[BLACK]["quantity"], 90)

    def test_a_row_removed_meanwhile_is_reason_deleted(self):
        self.add()
        self.add({**SLEEVES, "colour": "red"})
        old = self.view()["sha256"]
        self.save(sha256=old, action="remove", id=BLACK)
        e = self.error(api_acc.save_accessory, sha256=old, action="edit", id=BLACK, row={"quantity": 90})
        self.assertEqual((e.status, e.extra["conflict"]["reason"]), (409, "deleted"))
        self.assertEqual([i["id"] for i in e.extra["latest"]["items"]], ["dragon-shield-matte-red"])

    def test_a_row_in_use_cant_be_removed_or_change_kind(self):
        self.add()
        self.assign("casual/otters", BLACK)
        sha256 = self.view()["sha256"]
        e = self.error(api_acc.save_accessory, sha256=sha256, action="remove", id=BLACK)
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["blocks"], [{"id": "casual/otters", "title": "Izzet Otters"}])
        self.assertEqual(e.message, "Izzet Otters uses these sleeves. Choose other sleeves for it first, "
                                    "or set the quantity to 0.")
        e = self.error(api_acc.save_accessory, sha256=sha256, action="edit", id=BLACK, row={"kind": "deck_box"})
        self.assertEqual(e.status, 409)
        self.assertIn(BLACK, accessories.PATH.read_text(encoding="utf-8"))
        # Quantity 0 is allowed: it's kept for history.
        self.save(sha256=sha256, action="edit", id=BLACK, row={"quantity": 0})

    def test_a_refused_save_keeps_the_staged_picture_and_writes_nothing(self):
        self.add()
        self.assign("casual/otters", BLACK)
        before = accessories.PATH.read_bytes()
        image = self.staged(png())
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=BLACK,
                       row={"kind": "playmat"}, image=image)
        self.assertEqual(e.status, 409)
        self.assertEqual(accessories.PATH.read_bytes(), before)
        self.assertFalse((self.magic / "accessories" / "images").exists())
        self.assertEqual(len(list(accessory_fetch.STAGED.iterdir())), 1)

    def test_a_staged_file_that_isnt_a_picture_is_refused(self):
        token = "a" * 32
        accessory_fetch.STAGED.mkdir(parents=True)
        (accessory_fetch.STAGED / f"{token}.png").write_bytes(b"<svg/>")
        e = self.error(api_acc.save_accessory, sha256=None, action="add", row=SLEEVES, image={"token": token})
        self.assertEqual(e.status, 502)
        self.assertFalse(accessories.PATH.exists())

    def test_requests_are_checked(self):
        for data in ({"sha256": None, "action": "rename", "row": SLEEVES},
                     {"sha256": "x", "action": "add", "row": SLEEVES},
                     {"sha256": None, "action": "add", "row": {**SLEEVES, "image": "x.png"}},
                     {"sha256": None, "action": "add"},
                     {"sha256": None, "action": "remove", "id": "Bad Id"},
                     {"sha256": None, "action": "add", "row": SLEEVES, "image": "keep"}):
            with self.subTest(data=data):
                self.assertEqual(self.error(api_acc.save_accessory, **data).status, 400)

    def test_retry_and_commit_are_gone(self):
        from decklab.lib import feature_routes
        self.assertFalse(hasattr(api_acc, "commit_accessories"))
        self.assertFalse(hasattr(api_acc, "ACCESSORIES_PENDING"))
        self.assertNotIn("commit_accessories", Path(feature_routes.__file__).read_text(encoding="utf-8"))


class AssignTests(AccessoriesApiTestCase):

    def setUp(self):
        super().setUp()
        self.add()
        self.add(BOX_ROW)

    def test_a_deck_gets_only_its_header_line(self):
        before = self.deck_text("otters")
        applied = self.applies()
        answer = self.assign("casual/otters", BLACK)
        self.assertEqual([c.args[0].kind for c in applied.call_args_list], ["kit.set"])
        self.assertEqual(applied.call_args.args[2], "set sleeves for Izzet Otters")
        after = (self.magic / "decks/casual/otters.md").read_text(encoding="utf-8")
        added = [line for line in after.splitlines() if line not in before.splitlines()]
        self.assertEqual(added, [f"- **Sleeves:** {BLACK}"])
        self.assertEqual(len(after.splitlines()), len(before.splitlines()) + 1)
        kit = answer["holder"]
        self.assertEqual((kit["sleeves"]["id"], kit["need"], kit["spare"]), (BLACK, 75, 25))
        used = answer["data"]["items"][0]["used_by"]
        self.assertEqual(used, [{"holder": "casual/otters", "title": "Izzet Otters", "kind": "deck", "need": 75}])
        self.assertNotIn("commit", answer)

    def test_clearing_removes_the_line(self):
        self.assign("casual/otters", BLACK)
        applied = self.applies()
        self.assign("casual/otters", None)
        self.assertNotIn("Sleeves", self.deck_text("otters"))
        self.assertEqual(applied.call_args.args[2], "clear sleeves for Izzet Otters")

    def test_a_product_gets_its_status_row(self):
        answer = self.assign("product/test-product", BLACK)
        text = (self.magic / "products/status.csv").read_text(encoding="utf-8")
        # Legacy input remains readable; an ordinary write uses the full current schema.
        self.assertEqual(text, CURRENT_STATUS_HEADER + f"test-product.csv,owned,yes,{BLACK},,,\n")
        self.assertEqual(answer["holder"]["need"], 60)
        products = answer["data"]["products"]
        self.assertEqual((products[0]["holder"], products[0]["sleeves"]["id"]), ("product/test-product", BLACK))
        self.assertEqual(products[0]["holder_sha256"], self.status_sha())
        # A product deck's id names the same holder.
        self.assign("product/test-product/red", BOX, field="deck_box")
        self.assertIn(f"{BLACK},{BOX},", (self.magic / "products/status.csv").read_text())

    def test_a_product_that_isnt_intact_cant_take_sleeves(self):
        self.write("products/status.csv", STATUS_HEADER + "test-product.csv,owned,no,,,\n")
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256=self.status_sha())
        self.assertEqual((e.status, e.message), (400, product_kit.CANT_HOLD))

    def test_sleeves_another_deck_has_are_shared_as_they_are(self):
        # E8-S20: one design may sleeve several decks; both keep it, in one change, with no warning about it.
        self.assign("casual/otters", BLACK)
        applied = self.applies()
        answer = self.assign("casual/gruul", BLACK)
        self.assertEqual(applied.call_count, 1)
        self.assertEqual(applied.call_args.args[2], "set sleeves for Gruul Ramp")
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("otters"))
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("gruul"))
        self.assertEqual(answer["holder"]["shared_with"], ["Izzet Otters"])
        self.assertEqual(answer["warnings"], [])
        item = next(i for i in answer["data"]["items"] if i["id"] == BLACK)
        self.assertEqual(sorted(u["holder"] for u in item["used_by"]), ["casual/gruul", "casual/otters"])
        self.assertEqual(item["short"], 0)          # 75 and 60 each against 100, not their sum
        # A product kept intact may share them too.
        self.assign("product/test-product", BLACK)
        self.assertIn(f"test-product.csv,owned,yes,{BLACK},,", (self.magic / "products/status.csv").read_text())

    def test_move_from_clears_the_old_holder_in_the_same_change(self):
        self.assign("casual/otters", BLACK)
        applied = self.applies()
        self.assign("casual/gruul", BLACK, move_from="casual/otters")
        self.assertEqual(applied.call_count, 1)
        self.assertEqual(applied.call_args.args[2], "move sleeves from Izzet Otters to Gruul Ramp")
        self.assertNotIn("Sleeves", self.deck_text("otters"))
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("gruul"))

    def test_move_from_a_deck_to_a_product_and_back_is_one_change_each(self):
        self.assign("casual/otters", BLACK)
        applied = self.applies()
        self.assign("product/test-product", BLACK, move_from="casual/otters")
        self.assertNotIn("Sleeves", self.deck_text("otters"))
        self.assertIn(f"test-product.csv,owned,yes,{BLACK},,", (self.magic / "products/status.csv").read_text())
        self.assign("casual/otters", BLACK, move_from="product/test-product")
        self.assertEqual([c.args[2] for c in applied.call_args_list],
                         ["move sleeves from Izzet Otters to test-product",
                          "move sleeves from test-product to Izzet Otters"])
        self.assertEqual((self.magic / "products/status.csv").read_text(encoding="utf-8"),
                         CURRENT_STATUS_HEADER + "test-product.csv,owned,yes,,,,\n")
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("otters"))

    def test_a_refused_move_changes_neither_holder(self):
        self.assign("casual/otters", BLACK)
        before = (self.magic / "decks/casual/otters.md").read_bytes()
        self.write("products/status.csv", STATUS_HEADER + "test-product.csv,owned,no,,,\n")
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256=self.status_sha(), move_from="casual/otters")
        self.assertEqual(e.status, 400)
        self.assertEqual((self.magic / "decks/casual/otters.md").read_bytes(), before)
        for failure, status in ((inventory.Unavailable("down"), 503), (inventory.Conflict("busy"), 409)):
            with self.subTest(failure=failure), mock.patch.object(inventory, "apply", side_effect=failure):
                e = self.error(api_acc.assign_accessory, holder="casual/gruul", field="sleeves", id=BLACK,
                               holder_sha256=self.deck_sha("gruul"), move_from="casual/otters")
            self.assertEqual(e.status, status)
            self.assertEqual((self.magic / "decks/casual/otters.md").read_bytes(), before)

    def test_a_status_file_changed_since_the_page_loaded_it_is_409(self):
        old = self.status_sha()
        self.assign("product/test-product", BLACK)
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="deck_box", id=BOX,
                       holder_sha256=old)
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["conflict"]["reason"], "changed")
        self.assertTrue(e.message.startswith("The products list changed after you opened it"))

    def test_deck_boxes_are_taken_only_once_all_are_held(self):
        self.assign("casual/otters", BOX, field="deck_box")
        e = self.error(api_acc.assign_accessory, holder="casual/gruul", field="deck_box", id=BOX,
                       holder_sha256=self.deck_sha("gruul"))
        self.assertEqual(e.status, 409)
        self.save(sha256=self.view()["sha256"], action="edit", id=BOX, row={"quantity": 2})
        self.assign("casual/gruul", BOX, field="deck_box")
        self.assertIn(f"Deck box:** {BOX}", self.deck_text("gruul"))

    def test_a_deck_box_with_quantity_0_is_a_clear_409(self):
        self.save(sha256=self.view()["sha256"], action="edit", id=BOX, row={"quantity": 0})
        e = self.error(api_acc.assign_accessory, holder="casual/gruul", field="deck_box", id=BOX,
                       holder_sha256=self.deck_sha("gruul"))
        self.assertEqual(e.status, 409)
        self.assertIn("quantity is 0", e.message)
        e = self.error(api_acc.assign_accessory, holder="casual/gruul", field="deck_box", id=BOX,
                       holder_sha256=self.deck_sha("gruul"), move_from="casual/otters")
        self.assertIn("quantity is 0", e.message)

    def test_a_hand_written_yes_still_holds(self):
        self.write("products/status.csv", STATUS_HEADER + "test-product.csv, Owned ,Yes,,,\n")
        self.assign("product/test-product", BLACK)
        self.assertIn(BLACK, (self.magic / "products/status.csv").read_text(encoding="utf-8"))

    def test_a_deck_that_isnt_built_is_400(self):
        e = self.error(api_acc.assign_accessory, holder="casual/idea", field="sleeves", id=BLACK,
                       holder_sha256=self.deck_sha("idea"))
        self.assertEqual((e.status, e.message),
                         (400, "Only a built deck or a product kept intact has sleeves or a deck box"))

    def test_the_wrong_kind_or_an_unknown_id_is_400(self):
        for value, field in ((BOX, "sleeves"), ("nothing-here", "sleeves"), (BLACK, "playmat")):
            with self.subTest(value=value, field=field):
                e = self.error(api_acc.assign_accessory, holder="casual/otters", field=field, id=value,
                               holder_sha256=self.deck_sha("otters"))
                self.assertEqual(e.status, 400)

    def test_a_changed_deck_is_409_and_its_new_sha_saves(self):
        old = self.deck_sha("otters")
        path = self.magic / "decks/casual/otters.md"
        path.write_bytes(path.read_bytes() + b"\nA note.\n")
        e = self.error(api_acc.assign_accessory, holder="casual/otters", field="sleeves", id=BLACK,
                       holder_sha256=old)
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["conflict"]["reason"], "changed")
        self.assertTrue(e.message.startswith("Izzet Otters changed after you opened it"), e.message)
        self.assign("casual/otters", BLACK)         # nothing to commit first: the deck's text is what's saved
        self.assertTrue(self.deck_text("otters").endswith("A note.\n"))

    def test_a_crlf_deck_keeps_its_line_endings(self):
        path = self.magic / "decks/casual/otters.md"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        self.assign("casual/otters", BLACK)
        raw = path.read_bytes()
        self.assertIn(f"- **Sleeves:** {BLACK}\r\n".encode(), raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_a_changed_status_file_is_409(self):
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256="0" * 64)
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["conflict"]["reason"], "changed")

    def test_a_persons_deck_is_400(self):
        self.write("people/user2/decks/casual/elves.md", deck_md("Elves"))
        e = self.error(api_acc.assign_accessory, holder="user2/casual/elves", field="sleeves", id=BLACK,
                       holder_sha256="0" * 64)
        self.assertEqual(e.status, 400)


class ViewTests(AccessoriesApiTestCase):

    def test_an_empty_inventory(self):
        view = self.view()
        self.assertEqual((view["sha256"], view["exists"], view["items"], view["problems"]), (None, False, [], []))
        options = {o["id"]: o for o in view["holders_options"]}
        self.assertEqual(sorted(options), ["casual/gruul", "casual/otters", "product/test-product"])
        self.assertEqual(options["casual/otters"]["need"], 75)
        self.assertEqual(options["casual/otters"]["holder_sha256"],
                         sha((self.magic / "decks/casual/otters.md").read_bytes()))
        self.assertEqual(view["products"][0]["need"], 60)
        for key in ("uncommitted", "commit_pending"):
            self.assertNotIn(key, view)

    def test_a_status_file_the_os_wont_read_is_a_500_that_says_so(self):
        root = self.root

        class Locked:
            name = "files"

            def load(self):
                tree = files.tree_files(root)
                tree["magic/products/status.csv"] = PermissionError("locked by another program")
                return files.build(tree)
        restore = inventory.use(Locked())
        self.addCleanup(restore)
        with self.assertRaises(ApiError) as caught:
            self.view()
        self.assertEqual(caught.exception.status, 500)
        self.assertIn("can't be read", caught.exception.message)
        self.assertIn("locked by another program", caught.exception.message)

    def test_a_missing_status_file_has_no_holder_sha(self):
        (self.magic / "products/status.csv").unlink()
        self.assertIsNone(accessories.status_sha256())

    def test_short_sleeves(self):
        self.add({**SLEEVES, "quantity": 60})
        self.assign("casual/otters", BLACK)
        self.assertEqual(self.view()["items"][0]["short"], 15)

    def test_a_bad_row_is_a_problem_not_an_error(self):
        self.write("accessories.csv", ",".join(accessories.FIELDS) + "\nBad Id,sleeves,,x,,1,,,,,,\n")
        view = self.view()
        self.assertEqual(view["items"], [])
        self.assertTrue(view["problems"])
        e = self.error(api_acc.save_accessory, sha256=view["sha256"], action="add", row=SLEEVES)
        self.assertEqual(e.status, 409)
        self.assertIn("put right", e.message)


class PictureTests(AccessoriesApiTestCase):

    def test_only_listed_pictures_are_served(self):
        picture = png()
        self.add(image=self.staged(picture))
        with inventory.pinned():
            self.assertEqual(api_acc.image_file(f"{BLACK}.png", image_version(picture)), (picture, "image/png"))
        images = self.magic / "accessories" / "images"
        (images / "orphan.png").write_bytes(picture)
        v = sha(picture)[:8]
        for name, version in (("orphan.png", v), (f"{BLACK}.jpg", v), ("../accessories.csv", v),
                              (f"{BLACK}.svg", v), ("", v), (f"{BLACK}.PNG", v), (f"{BLACK}.png", None),
                              (f"{BLACK}.png", "00000000"), (f"{BLACK}.png", sha(picture)[:7])):
            with self.subTest(name=name, version=version), self.assertRaises(ApiError) as caught:
                api_acc.image_file(name, version)
            self.assertEqual(caught.exception.status, 404)

    def test_a_picture_whose_bytes_dont_match_its_name_isnt_served(self):
        self.add(image=self.staged(png()))
        (self.magic / "accessories" / "images" / f"{BLACK}.png").write_bytes(b"<svg/>")
        with self.assertRaises(ApiError):
            api_acc.image_file(f"{BLACK}.png", sha(b"<svg/>")[:8])

    def test_staged_pictures(self):
        picture = jpeg()
        token = self.staged(picture)["token"]
        self.assertEqual(api_acc.staged_image(f"{token}.jpg"), (picture, "image/jpeg"))
        for name in (f"{token}.png", f"{token[:-1]}.jpg", "x.jpg", f"{token}.jpg/.."):
            with self.subTest(name=name), self.assertRaises(ApiError):
                api_acc.staged_image(name)

    def test_fetch_answers_with_a_preview_url(self):
        found = {"token": "a" * 32, "bytes": b"", "ext": "png", "width": 200, "height": 100,
                 "final_url": "https://shop.example/p/1", "image_source": "https://cdn.example/1.png",
                 "guess": {"name": "Matte", "brand": "", "kind": "sleeves", "quantity": 100}}
        with mock.patch.object(accessory_fetch, "fetch", return_value=found) as fetch:
            answer = self.call(api_acc.fetch_picture, url="https://shop.example/p/1")
        fetch.assert_called_once_with("https://shop.example/p/1")
        self.assertEqual(answer["preview_url"], f"/accessory-img/staged/{'a' * 32}.png")
        self.assertNotIn("bytes", answer)
        self.assertEqual(self.error(api_acc.fetch_picture, url=5).status, 400)


class OwnerTests(AccessoriesApiTestCase):
    """Each row is its owner's: Matt and User1 change only their own and the shared ones, and a deck
    takes only its player's or shared ones (casual/hers is Played by wife, so User1's)."""

    def add_as(self, profile, row):
        return self.add(row, profile=profile)["changed_id"]

    def test_a_new_row_is_its_writers(self):
        rid = self.add_as("user1", {k: v for k, v in SLEEVES.items() if k != "owner"})
        self.assertEqual(accessories.read().rows_by_id[rid]["owner"], "user1")

    def test_another_owners_row_is_not_found(self):
        rid = self.add_as("user1", {**SLEEVES, "owner": "user1"})
        sha256 = self.view()["sha256"]
        for action, extra in (("edit", {"row": {"quantity": 5}}), ("remove", {})):
            e = self.error(api_acc.save_accessory, sha256=sha256, action=action, id=rid, **extra)
            self.assertEqual(e.status, 404, action)
        self.assertEqual(accessories.read().rows_by_id[rid]["quantity"], 100)

    def test_another_owners_change_never_refuses_a_save_nor_shows(self):
        self.add()                                  # shared
        mine = self.view("matt")["sha256"]
        self.add_as("user1", {**SLEEVES, "colour": "pink", "owner": "user1"})
        self.assertEqual(self.view("matt")["sha256"], mine)
        self.assertNotEqual(self.view("user1")["sha256"], mine)
        self.save(sha256=mine, action="edit", id=BLACK, row={"quantity": 50})
        self.assertEqual(accessories.read().rows_by_id[BLACK]["quantity"], 50)

    def test_a_row_cant_be_given_to_another(self):
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="add",
                       row={**SLEEVES, "owner": "user1"})
        self.assertEqual(e.status, 403)
        rid = self.add_as("matt", {**SLEEVES, "owner": "matt"})
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=rid,
                       row={"owner": "user1"})
        self.assertEqual(e.status, 403)
        self.assertEqual(accessories.read().rows_by_id[rid]["owner"], "matt")

    def test_an_owner_its_holders_cant_use_is_409(self):
        self.add()                                          # shared
        self.assign("casual/otters", BLACK)                 # an "either" deck: shared ones only
        e = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=BLACK,
                       row={"owner": "matt"})
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["blocks"], [{"id": "casual/otters", "title": "Izzet Otters"}])
        self.assertEqual(accessories.read().rows_by_id[BLACK]["owner"], "shared")

    def test_assign_only_to_your_decks_and_only_what_they_may_take(self):
        mine = self.add_as("matt", {**SLEEVES, "owner": "matt"})
        hers = self.add_as("user1", {**SLEEVES, "colour": "pink", "owner": "user1"})
        self.add()
        e = self.error(api_acc.assign_accessory, holder="casual/hers", field="sleeves", id=BLACK,
                       holder_sha256=self.deck_sha("hers"))
        self.assertEqual(e.status, 403)
        e = self.error(api_acc.assign_accessory, profile="user1", holder="casual/hers", field="sleeves",
                       id=mine, holder_sha256=self.deck_sha("hers"))
        self.assertEqual(e.status, 400)
        # An "either" deck isn't one User1 may edit (E10-S42), so it's refused before its kit is looked at.
        e = self.error(api_acc.assign_accessory, profile="user1", holder="casual/otters", field="sleeves",
                       id=hers, holder_sha256=self.deck_sha("otters"))
        self.assertEqual((e.status, e.message), (403, "You can change the home decks played by you."))
        self.assertNotIn("Sleeves", self.deck_text("otters"))
        self.assign("casual/hers", hers, profile="user1")
        self.assertIn(f"- **Sleeves:** {hers}", self.deck_text("hers"))

    def test_a_deck_she_cant_edit_is_refused_whatever_its_kit(self):
        # E10-S42: choosing or clearing a deck's sleeves or deck box is an edit of that deck (deck.edit), as
        # the deck page's editor save is, even though an "either" deck's kit is shared and so User1's to see.
        self.add()
        self.add(BOX_ROW)
        self.assign("casual/otters", BLACK)
        before = self.deck_text("otters")
        applied = self.applies()
        for field, value in (("sleeves", None), ("sleeves", BLACK), ("deck_box", BOX)):
            with self.subTest(field=field, value=value):
                e = self.error(api_acc.assign_accessory, profile="user1", holder="casual/otters", field=field,
                               id=value, holder_sha256=self.deck_sha("otters"))
                self.assertEqual((e.status, e.message), (403, "You can change the home decks played by you."))
        self.assertEqual(applied.call_count, 0)
        self.assertEqual(self.deck_text("otters"), before)

    def test_moving_sleeves_off_a_deck_she_cant_edit_is_refused(self):
        # The move's source is changed too (its Sleeves line is cleared), so it needs deck.edit as well.
        self.add()
        self.assign("casual/otters", BLACK)
        otters, hers = self.deck_text("otters"), self.deck_text("hers")
        applied = self.applies()
        e = self.error(api_acc.assign_accessory, profile="user1", holder="casual/hers", field="sleeves", id=BLACK,
                       holder_sha256=self.deck_sha("hers"), move_from="casual/otters")
        self.assertEqual((e.status, e.message), (403, "You can change the home decks played by you."))
        self.assertEqual(applied.call_count, 0)
        self.assertEqual((self.deck_text("otters"), self.deck_text("hers")), (otters, hers))
        # Sharing them, without the move, is hers to do.
        self.assign("casual/hers", BLACK, profile="user1")
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("otters"))
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("hers"))
        # Matt, an admin, may move them between any home decks.
        self.assign("casual/gruul", BLACK, move_from="casual/otters")
        self.assertNotIn("Sleeves", self.deck_text("otters"))

    def test_the_operation_checks_deck_edit_again_under_the_lock(self):
        # A move's source isn't sha-checked, so its Played by could change between the route's check and the
        # write: kit.set checks deck.edit itself on every deck holder, for the editor the route passes.
        self.add()
        self.assign("casual/otters", BLACK)
        before = self.deck_text("otters")
        with self.assertRaises(ops_accessories.AccessoryRefused) as caught:
            inventory.apply(inventory.Op("kit.set", {
                "holders": [{"id": "casual/otters", "expected": None},
                            {"id": "casual/hers", "expected": self.deck_sha("hers")}],
                "changes": [{"holder": "casual/otters", "field": "sleeves", "value": None, "expect": BLACK},
                            {"holder": "casual/hers", "field": "sleeves", "value": BLACK}],
                "owners": frozenset({"user1", "shared"}), "editor": dict(BY_ID["user1"])}),
                Actor("user1", "User1"), "move sleeves")
        self.assertEqual((caught.exception.code, str(caught.exception)),
                         (403, "You can change the home decks played by you."))
        self.assertEqual(self.deck_text("otters"), before)
        self.assertNotIn("Sleeves", self.deck_text("hers"))

    def test_a_products_kit_keeps_the_rights_it_had(self):
        # A product kept intact has no Played by: its kit is shared, chosen by either home profile on the
        # Sleeves & boxes page's Products kept intact panel, as before E10-S42.
        self.add()
        self.assign("product/test-product", BLACK, profile="user1")
        self.assertIn(f"test-product.csv,owned,yes,{BLACK},,", (self.magic / "products/status.csv").read_text())
        self.assign("casual/hers", BLACK, profile="user1", move_from="product/test-product")
        self.assertIn("test-product.csv,owned,yes,,,", (self.magic / "products/status.csv").read_text())
        with mock.patch.object(api_acc.guard, "sees_home_records", return_value=False):     # E10-S29
            e = self.error(api_acc.assign_accessory, profile="user1", holder="product/test-product",
                           field="sleeves", id=BLACK, holder_sha256=self.status_sha())
        self.assertEqual(e.status, 403)

    def test_the_view_is_the_viewers(self):
        self.add()                                          # shared, on User1's deck
        self.assign("casual/hers", BLACK, profile="user1")
        self.add_as("user1", {**SLEEVES, "colour": "pink", "owner": "user1"})
        view = self.view("matt")
        self.assertEqual([i["id"] for i in view["items"]], [BLACK])
        self.assertEqual(view["items"][0]["used_by"],
                         [{"holder": None, "title": "one of User1's decks", "kind": "deck", "need": 60}])
        self.assertNotIn("casual/hers", [o["id"] for o in view["holders_options"]])
        self.assertNotIn("Her Deck", json.dumps(view))
        view = self.view("user1")
        self.assertEqual(len(view["items"]), 2)
        self.assertIn("casual/hers", [o["id"] for o in view["holders_options"]])
        self.assertEqual(view["owners"], [{"id": "user1", "name": "User1"}, {"id": "shared", "name": "shared"}])

    def test_shared_sleeves_name_a_hidden_holder_only_as_theirs(self):
        self.add()
        self.assign("casual/hers", BLACK, profile="user1")
        with access.viewing("matt"):
            answer = self.assign("casual/otters", BLACK)
        self.assertEqual(answer["holder"]["shared_with"], ["one of User1's decks"])
        self.assertNotIn("Her Deck", json.dumps(answer))
        self.assertIn(f"Sleeves:** {BLACK}", self.deck_text("hers"))

    def test_a_taken_deck_box_names_a_hidden_holder_only_as_theirs(self):
        self.add(BOX_ROW)
        self.assign("casual/hers", BOX, field="deck_box", profile="user1")
        e = self.error(api_acc.assign_accessory, holder="casual/otters", field="deck_box", id=BOX,
                       holder_sha256=self.deck_sha("otters"))
        self.assertEqual(e.status, 409)
        self.assertEqual(e.extra["taken_by"], [{"holder": None, "title": "one of User1's decks"}])
        self.assertNotIn("Her Deck", str(e))

    def test_a_picture_is_its_owners(self):
        rid = self.add({**SLEEVES, "owner": "user1"}, image=self.staged(png()), profile="user1")["changed_id"]
        name, version = f"{rid}.png", image_version(png())
        with access.viewing("user1"):
            self.assertEqual(api_acc.image_file(name, version)[1], "image/png")
        with access.viewing("matt"):
            with self.assertRaises(ApiError) as caught:
                api_acc.image_file(name, version)
            self.assertEqual(caught.exception.status, 404)

    def test_a_stale_token_never_says_whether_another_owner_has_a_row(self):
        hers = self.add_as("user1", {**SLEEVES, "colour": "pink", "owner": "user1"})
        for rid in (hers, "dragon-shield-matte-nothing"):
            with self.subTest(rid=rid):
                e = self.error(api_acc.save_accessory, sha256="0" * 64, action="edit", id=rid,
                               row={"quantity": 5})
                self.assertEqual((e.status, e.extra["conflict"]["reason"]), (409, "deleted"))
        self.assertEqual(accessories.read().rows_by_id[hers]["quantity"], 100)

    def test_another_owners_first_or_last_row_doesnt_change_the_token(self):
        self.assertEqual((self.view("matt")["sha256"], self.view("matt")["exists"]), (None, False))
        hers = self.add_as("user1", {**SLEEVES, "colour": "pink", "owner": "user1"})
        self.assertEqual((self.view("matt")["sha256"], self.view("matt")["exists"]), (None, False))
        self.assertTrue(self.view("user1")["exists"])
        self.save(sha256=None, action="add", row={**SLEEVES, "owner": "matt"})     # the token Matt's page had
        mine = self.view("matt")["sha256"]
        self.save(profile="user1", sha256=self.view("user1")["sha256"], action="remove", id=hers)
        self.assertEqual((self.view("user1")["sha256"], self.view("user1")["exists"]), (None, False))
        self.assertEqual(self.view("matt")["sha256"], mine)


class DatabaseTests(AccessoriesApiTestCase, db_support.DbTestCase):
    """The same page with every deck, accessory and inventory row in a throwaway database: the
    fixture tree imported (decks and accessories too), then its deck and accessory files and
    status.csv deleted, so every read and write is the database's."""

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
                       dbname=self.dbname, decks=True, images={})
        shutil.rmtree(self.magic / "decks")
        (self.magic / "products/status.csv").unlink()
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        self.inventory = self.backend

    def trail(self):
        with self.connect() as c:
            return [tuple(r) for r in c.execute("select actor, message from audit.change_set where source = 'web' "
                                                "order by id").fetchall()]

    def test_saves_and_pictures_are_the_databases(self):
        picture = png()
        self.add(image=self.staged(picture))
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={"quantity": 60},
                  image=self.staged(jpeg()))
        self.assertFalse(accessories.PATH.exists())
        self.assertFalse((self.magic / "accessories").exists())
        with self.connect() as c:
            self.assertEqual([r[0] for r in c.execute("select file_name from accessory_image").fetchall()],
                             [f"{BLACK}.jpg"])
            self.assertEqual(c.execute("select quantity from accessory where id = %s", (BLACK,)).fetchone()[0],
                             "60")
        self.assertEqual(self.trail(), [("matt", "add sleeves Dragon Shield Matte (black)"),
                                        ("matt", "edit sleeves Dragon Shield Matte (black)")])
        item = self.view()["items"][0]
        data = jpeg()
        self.assertEqual(item["image_url"], f"/accessory-img/{BLACK}.jpg?v={image_version(data)}")
        with inventory.pinned():
            self.assertEqual(api_acc.image_file(f"{BLACK}.jpg", image_version(data)), (data, "image/jpeg"))
        self.save(sha256=self.view()["sha256"], action="remove", id=BLACK)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from accessory_image").fetchone()[0], 0)

    def test_a_kit_change_is_one_change_set_on_the_deck(self):
        self.add()
        self.assign("casual/otters", BLACK)
        self.assertFalse((self.magic / "decks").exists())
        self.assertIn(f"- **Sleeves:** {BLACK}", self.deck_text("otters"))
        rev = inventory.last_revision("casual/otters")
        self.assertEqual((rev.revision, rev.actor, rev.kit, rev.message), (2, "matt", True,
                                                                         "set sleeves for Izzet Otters"))
        self.assertEqual(rev.message_for("user1"), None)
        self.assign("product/test-product", BLACK, move_from="casual/otters")
        self.assertEqual(self.trail()[-1], ("matt", "move sleeves from Izzet Otters to test-product"))
        self.assertNotIn("Sleeves", self.deck_text("otters"))
        self.assertEqual(inventory.current().status.rows[0].text("sleeves"), BLACK)

    def test_a_changed_list_names_who_changed_a_row_the_viewer_sees_without_its_words(self):
        self.add()
        old = self.view("matt")["sha256"]
        self.save(profile="user1", sha256=self.view("user1")["sha256"], action="edit", id=BLACK,
                  row={"quantity": 80})
        e = self.error(api_acc.save_accessory, sha256=old, action="edit", id=BLACK, row={"quantity": 90})
        conflict = e.extra["conflict"]
        self.assertEqual((conflict["reason"], conflict["by"], conflict["deck_lab"], conflict["subject"]),
                         ("changed", "User1", True, None))
        self.assertIsNotNone(conflict["when"])
        self.assertTrue(e.message.startswith("The accessories list changed after you opened it: User1 saved it in "
                                             "Deck Lab "), e.message)
        # Her own rows are hers: changing one refuses nothing of Matt's, and names nothing.
        now = self.view("matt")["sha256"]
        self.add({**SLEEVES, "colour": "pink", "owner": "user1"}, profile="user1")
        self.save(sha256=now, action="edit", id=BLACK, row={"quantity": 70})

    def test_a_changed_deck_names_its_last_revision(self):
        old = self.deck_sha("otters")
        deck = inventory.current().deck("casual/otters")
        inventory.apply(inventory.Op("deck.save", {"deck_id": "casual/otters", "text": deck.text + "\nA note.\n",
                                                   "base_sha256": old}), Actor("user1", "User1", "home"),
                        "save Izzet Otters")
        self.add()
        e = self.error(api_acc.assign_accessory, holder="casual/otters", field="sleeves", id=BLACK,
                       holder_sha256=old)
        self.assertEqual(e.status, 409)
        conflict = e.extra["conflict"]
        self.assertEqual((conflict["by"], conflict["deck_lab"], conflict["subject"]),
                         ("User1", True, "save Izzet Otters"))

    def test_a_deck_changed_from_the_command_line_isnt_said_to_be_deck_labs(self):
        old = self.deck_sha("otters")
        deck = inventory.current().deck("casual/otters")
        inventory.apply(inventory.Op("deck.save", {"deck_id": "casual/otters", "text": deck.text + "\nA note.\n",
                                                   "base_sha256": old}), Actor("claude", "Claude", source="cli"),
                        "push Izzet Otters")
        self.add()
        e = self.error(api_acc.assign_accessory, holder="casual/otters", field="sleeves", id=BLACK,
                       holder_sha256=old)
        conflict = e.extra["conflict"]
        self.assertEqual((conflict["deck_lab"], conflict["subject"]), (False, "push Izzet Otters"))
        self.assertNotIn("Deck Lab", e.message)

    def test_a_changed_product_names_the_audit_trails_last_change(self):
        self.add(BOX_ROW)
        old = self.status_sha()
        inventory.apply(inventory.Op(product_kit.KIND, {"changes": [
            {"stem": "test-product", "field": "deck_box", "value": BOX}]}),
            Actor("user1", "User1", "home"), "set deck box for test-product")
        self.add()
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256=old)
        self.assertEqual(e.status, 409)
        conflict = e.extra["conflict"]
        # A kit change's words are its actor's alone.
        self.assertEqual((conflict["reason"], conflict["by"], conflict["deck_lab"], conflict["subject"]),
                         ("changed", "User1", True, None))

    def test_a_product_never_changed_since_the_import_names_the_import(self):
        self.add()
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256="0" * 64)
        conflict = e.extra["conflict"]
        self.assertEqual((conflict["by"], conflict["deck_lab"], conflict["subject"]),
                         ("Claude", False, "Import the inventory"))

    def test_a_database_that_cant_be_reached_changes_nothing(self):
        self.add()
        self.assign("casual/otters", BLACK)
        sha256 = self.status_sha()
        self.backend.breaker.trip("the database is down")
        e = self.error(api_acc.assign_accessory, holder="product/test-product", field="sleeves", id=BLACK,
                       holder_sha256=sha256, move_from="casual/otters")
        self.assertEqual((e.status, e.extra.get("reason")), (503, "database"))
        self.backend.breaker.reset()
        self.assertIn("Sleeves", self.deck_text("otters"))
        self.assertEqual(inventory.current().status.rows[0].text("sleeves"), "")

    def test_activity_shows_accessory_and_kit_changes_to_their_owners_only(self):
        from decklab.lib import state
        from decklab.lib.api import activity, settings
        from decklab.lib.state import pg as state_pg
        self.addCleanup(state.use(state_pg.PgStore(dbname=self.dbname, breaker=state_pg.Breaker())))
        patcher = mock.patch.object(settings, "_config_profiles", return_value=[dict(p) for p in PROFILES["profiles"]])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.add({**SLEEVES, "colour": "pink", "owner": "user1"}, profile="user1")
        self.assign("casual/hers", "dragon-shield-matte-pink", profile="user1")
        with access.viewing("matt"):
            seen = activity.activity_view()
        with access.viewing("user1"):
            user1 = json.dumps(activity.activity_view())
        matt = json.dumps(seen)
        # Matt (an admin) sees neither her accessory nor what her kit change was: only that her deck
        # (home's, so his to see) changed, with no words.
        for words in ("pink", "Dragon Shield", "set sleeves"):
            self.assertNotIn(words, matt)
        kit = [c for c in seen["changes"] if c["actor"] == "user1"]
        self.assertEqual([(c["message"], [r["table"] for r in c["rows"]]) for c in kit], [(None, ["deck"])])
        self.assertIn("add sleeves Dragon Shield Matte (pink)", user1)
        self.assertIn("set sleeves for Her Deck", user1)


if __name__ == "__main__":
    unittest.main()
