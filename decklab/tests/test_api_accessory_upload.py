"""Local accessory pictures: isolated file-backed saves, privacy, validation and HTTP limits."""
import base64
import hashlib
import json
import shutil
import struct
from unittest import mock
import zlib

from decklab.lib import access, accessories, accessory_fetch, api, inventory
from decklab.lib.api import accessories as api_acc
from decklab.lib.api.common import ApiError
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor
from decklab.tests import db_support
from decklab.tests.test_accessory_fetch import AVIF, GIF, SVG, jpeg, webp_vp8, webp_vp8l, webp_vp8x
from decklab.tests.test_api_accessories import AccessoriesApiTestCase, BLACK, PROFILES, SLEEVES
from decklab.tests.test_server import ServerTestCase, WRITE


# Generated once from a synthetic 32x24 gradient and decoded with Pillow when created.
# The tests use only these embedded bytes and the standard library.
PROGRESSIVE_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEEx"
    "NDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7"
    "Ozs7Ozs7Ozs7Ozs7Ozv/wgARCAAYACADASIAAhEBAxEB/8QAFwABAQEBAAAAAAAAAAAAAAAABAADBv/EABgBAAIDAAAAAAAA"
    "AAAAAAAAAAMFAgQG/9oADAMBAAIQAxAAAAHmVMTAY1MSdvimlmOUmrDf/8QAFhAAAwAAAAAAAAAAAAAAAAAAAAID/9oACAEB"
    "AAEFAlmLMWYsxZizFmLMWYsxZizP/8QAGBEAAgMAAAAAAAAAAAAAAAAAAAMBAgT/2gAIAQMBAT8BToE6BN5E3k//xAAWEQEB"
    "AQAAAAAAAAAAAAAAAAACAAH/2gAIAQIBAT8BLi47Hb//xAAUEAEAAAAAAAAAAAAAAAAAAAAw/9oACAEBAAY/Ak//xAAWEAEB"
    "AQAAAAAAAAAAAAAAAABhABD/2gAIAQEAAT8hHEYYYcRxGHH/2gAMAwEAAgADAAAAEJJnnP/EABYRAQEBAAAAAAAAAAAAAAAA"
    "ACEAMf/aAAgBAwEBPxDBsGCwW//EABYRAQEBAAAAAAAAAAAAAAAAAAABEP/aAAgBAgEBPxDFqq//xAAWEAEBAQAAAAAAAAAA"
    "AAAAAAAAMSH/2gAIAQEAAT8QgQxAgQIEMQIYgQIY/9k="
)
EXTENDED_WEBP = base64.b64decode(
    "UklGRpIAAABXRUJQVlA4WAoAAAAYAAAAHwAAFwAAVlA4TDIAAAAvH8AFELkKRPQ/FmLB5M8fdQo5DH30P1UzEE3b1Pf/o6vG"
    "3CAMglgwxbvyKmGuqnnifkVYSUY6AAAATU0AKgAAAAgAAQEOAAIAAAAgAAAAGgAAAABTeW50aGV0aWMgRGVjayBMYWIgdGVz"
    "dCBwYXR0ZXJuAA=="
)


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width=32, height=24):
    """An actual RGB PNG with bounded chunks, a compressed scan and its end marker."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = (b"\0" + b"\x49\x90\xc8" * width) * height
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(pixels)) + _chunk(b"IEND", b"")


def complete_jpeg(width=32, height=24, length=None):
    picture = jpeg(width, height) + b"\xff\xd9"
    if length is not None:
        picture = picture[:-2] + b"\0" * (length - len(picture)) + picture[-2:]
    return picture


def complete_webp(lossless=False):
    picture = webp_vp8l() if lossless else webp_vp8()
    # RIFF stores a padding byte after odd-sized chunks; its size includes that padding.
    if len(picture) % 2:
        picture += b"\0"
        picture = picture[:4] + struct.pack("<I", len(picture) - 8) + picture[8:]
    return picture


def uploaded(data):
    return {"upload": base64.b64encode(data).decode("ascii")}


def version(data):
    from decklab.tests.test_api_accessories import image_version
    return image_version(data)


class AccessoryUploadTests(AccessoriesApiTestCase):
    def setUp(self):
        super().setUp()
        profiles = {profile["id"]: profile for profile in PROFILES["profiles"]}
        patcher = mock.patch.object(api_acc, "_writer", side_effect=lambda data: dict(profiles[data["profile"]]))
        patcher.start()
        self.addCleanup(patcher.stop)

    def files(self):
        return {path.relative_to(self.root).as_posix(): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def assert_refused(self, status, image, **extra):
        before = self.files()
        with mock.patch.object(inventory, "apply") as apply:
            error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="add",
                               row=SLEEVES, image=image, **extra)
        self.assertEqual(error.status, status, error.message)
        apply.assert_not_called()
        self.assertEqual(self.files(), before)
        return error

    def test_supported_containers_are_saved_and_served_by_bytes_in_one_operation(self):
        for picture, ext, content_type in ((png(), "png", "image/png"),
                                           (complete_jpeg(), "jpg", "image/jpeg"),
                                           (complete_webp(), "webp", "image/webp"),
                                           (complete_webp(lossless=True), "webp", "image/webp")):
            with self.subTest(ext=ext), mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply, \
                    mock.patch.object(accessory_fetch, "stage", side_effect=AssertionError("upload must not stage")), \
                    mock.patch.object(accessory_fetch, "fetch", side_effect=AssertionError("upload must not fetch")):
                answer = self.add(image=uploaded(picture))
            rid = answer["changed_id"]
            operation = apply.call_args.args[0]
            self.assertEqual((apply.call_count, operation.kind, operation.params["image"]),
                             (1, "accessory.add", picture))
            item = next(row for row in answer["data"]["items"] if row["id"] == rid)
            self.assertEqual((item["image"], item["image_source"]), (f"{rid}.{ext}", ""))
            self.assertEqual(item["image_url"], f"/accessory-img/{rid}.{ext}?v={version(picture)}")
            self.assertEqual(api_acc.image_file(f"{rid}.{ext}", version(picture)), (picture, content_type))
            self.assertFalse(accessory_fetch.STAGED.exists())

    def test_decodable_progressive_jpeg_and_extended_webp_are_accepted(self):
        self.assertIn(b"\xff\xc2", PROGRESSIVE_JPEG)
        self.assertEqual(EXTENDED_WEBP[12:16], b"VP8X")
        self.assertIn(b"EXIF", EXTENDED_WEBP)
        for picture, ext in ((PROGRESSIVE_JPEG, "jpg"), (EXTENDED_WEBP, "webp")):
            with self.subTest(ext=ext):
                answer = self.add(image=uploaded(picture))
                rid = answer["changed_id"]
                item = next(row for row in answer["data"]["items"] if row["id"] == rid)
                self.assertEqual(item["image"], f"{rid}.{ext}")
                self.assertEqual(inventory.image(item["image"]), picture)

    def test_upload_edit_replaces_extension_and_keeps_explicit_crop_then_later_keep(self):
        self.add(image=uploaded(png()))
        view = self.view()
        replacement = complete_jpeg()
        crop = "0.1,0.2,0.6,0.7"
        applied = self.applies()
        answer = self.save(sha256=view["sha256"], action="edit", id=BLACK,
                           row={"quantity": 80, "crop": crop}, image=uploaded(replacement))
        self.assertEqual((applied.call_count, applied.call_args.args[0].kind), (1, "accessory.edit"))
        images = self.magic / "accessories" / "images"
        self.assertEqual([path.name for path in images.iterdir()], [f"{BLACK}.jpg"])
        self.assertEqual((images / f"{BLACK}.jpg").read_bytes(), replacement)
        item = next(row for row in answer["data"]["items"] if row["id"] == BLACK)
        self.assertEqual((item["quantity"], item["crop"]), (80, crop))
        self.assertTrue(item["image_url"].endswith("#crop=" + crop))
        for image in ({}, {"image": "keep"}):
            self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={"notes": "keep the crop"}, **image)
            self.assertEqual(self.view()["items"][0]["crop"], crop)
            self.assertEqual((images / f"{BLACK}.jpg").read_bytes(), replacement)

    def test_existing_token_keep_and_null_image_modes_remain_compatible(self):
        self.add(image=self.staged(png()))
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={}, image=uploaded(complete_jpeg()))
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={}, image="keep")
        self.assertEqual(self.view()["items"][0]["image"], f"{BLACK}.jpg")
        self.save(sha256=self.view()["sha256"], action="edit", id=BLACK, row={}, image=None)
        self.assertEqual(self.view()["items"][0]["image"], "")
        self.assertFalse(any((self.magic / "accessories" / "images").iterdir()))

    def test_upload_has_only_strict_base64_without_filename_mime_path_or_token(self):
        valid = uploaded(png())["upload"]
        invalid = [True, [], {"bytes": valid}, {"upload": valid, "name": "photo.png"},
                   {"upload": valid, "mime": "image/png"}, {"upload": valid, "path": "C:/photo.png"},
                   {"upload": valid, "token": "a" * 32}, "data:image/png;base64," + valid]
        invalid += [{"upload": value} for value in (None, 1, True, [], {}, "", "%%%", "a", "SGVsbG8",
                                                      "SGVsbG8===", "SGVsbG8=trailer", "é", valid + "\n",
                                                      "data:image/png;base64," + valid)]
        for image in invalid:
            with self.subTest(image=str(image)[:60]):
                self.assert_refused(400, image)

    def test_nonpicture_and_unsupported_types_are_local_input_errors(self):
        for picture in (GIF, SVG, AVIF, b"<!doctype html><html>no picture</html>", b"random bytes"):
            with self.subTest(picture=picture[:12]):
                self.assert_refused(400, uploaded(picture))

    def test_incomplete_or_out_of_bounds_containers_are_refused(self):
        picture = png()
        damaged_crc = picture[:29] + bytes([picture[29] ^ 1]) + picture[30:]
        without_scan = picture[:33] + _chunk(b"IEND", b"")
        invalid = [picture[:-12], picture[:-1], damaged_crc, without_scan, b"\x89PNG\r\n\x1a\n",
                   picture[:33] + struct.pack(">I", 0xffffffff) + b"IDAT\0\0\0\0",
                   jpeg(), complete_jpeg()[:-1], b"\xff\xd8\xff\xd9",
                   complete_webp()[:-1], webp_vp8x(), b"RIFF\xff\xff\xff\xffWEBP"]
        for data in invalid:
            with self.subTest(data=data[:16]):
                self.assert_refused(400, uploaded(data))

    def test_dimension_limits_are_inclusive(self):
        for width, height in ((16, 16), (6000, 16), (16, 6000)):
            with self.subTest(width=width, height=height):
                self.assertTrue(self.add(image=uploaded(png(width, height)))["saved"])
        for width, height in ((15, 16), (16, 15), (6001, 16), (16, 6001)):
            with self.subTest(width=width, height=height):
                self.assert_refused(400, uploaded(png(width, height)))

    def test_decoded_four_mebibyte_limit_is_inclusive(self):
        picture = complete_jpeg(length=accessory_fetch.MAX_IMAGE)
        self.assertEqual(len(picture), 4 * 1024 * 1024)
        self.assertTrue(self.add(image=uploaded(picture))["saved"])
        self.assertEqual(inventory.image(f"{BLACK}.jpg"), picture)
        self.assert_refused(413, uploaded(complete_jpeg(length=accessory_fetch.MAX_IMAGE + 1)))

    def test_upload_allowance_does_not_expand_the_row_metadata_limit(self):
        before = self.files()
        with mock.patch.object(inventory, "apply") as apply:
            error = self.error(api_acc.save_accessory, sha256=None, action="add",
                               row={**SLEEVES, "notes": "x" * (16 * 1024 + 1)}, image=uploaded(png()))
        self.assertEqual(error.status, 413)
        apply.assert_not_called()
        self.assertEqual(self.files(), before)

    def test_invalid_crop_conflict_and_refused_operation_leave_old_picture_intact(self):
        picture = png()
        self.add(image=uploaded(picture))
        before = self.files()
        error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=BLACK,
                           row={"crop": "0,0,2,1"}, image=uploaded(complete_jpeg()))
        self.assertEqual(error.status, 400)
        self.assertEqual(self.files(), before)
        error = self.error(api_acc.save_accessory, sha256="0" * 64, action="edit", id=BLACK,
                           row={}, image=uploaded(complete_jpeg()))
        self.assertEqual(error.status, 409)
        self.assertEqual(self.files(), before)
        self.assign("casual/otters", BLACK)
        before = self.files()
        error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=BLACK,
                           row={"kind": "playmat"}, image=uploaded(complete_jpeg()))
        self.assertEqual(error.status, 409)
        self.assertEqual(self.files(), before)
        self.assertEqual(inventory.image(f"{BLACK}.png"), picture)
        self.assertFalse(accessory_fetch.STAGED.exists())

    def test_concurrent_row_edit_refuses_upload_and_preserves_old_picture_and_latest_row(self):
        picture = png()
        self.add(image=uploaded(picture))
        old = self.view()["sha256"]
        real = inventory.apply

        def meanwhile(operation, *args, **kwargs):
            with inventory.pinned():
                real(inventory.Op("accessory.edit", {"id": BLACK, "row": {"notes": "Concurrent note"},
                                                      "sha256": old, "owners": None}),
                     Actor("user1", "User1", "home"), "edit the shared sleeves note")
            return real(operation, *args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=meanwhile):
            error = self.error(api_acc.save_accessory, sha256=old, action="edit", id=BLACK,
                               row={"notes": "Stale upload note"}, image=uploaded(complete_jpeg()))
        self.assertEqual((error.status, error.extra["conflict"]["reason"]), (409, "changed"))
        latest = error.extra["latest"]
        self.assertNotEqual(latest["sha256"], old)
        self.assertEqual((latest["items"][0]["notes"], latest["items"][0]["image"]),
                         ("Concurrent note", f"{BLACK}.png"))
        self.assertEqual(accessories.read().rows_by_id[BLACK]["notes"], "Concurrent note")
        self.assertEqual(inventory.image(f"{BLACK}.png"), picture)
        images = self.magic / "accessories" / "images"
        self.assertEqual([path.name for path in images.iterdir()], [f"{BLACK}.png"])
        self.assertFalse(accessory_fetch.STAGED.exists())
        # The conflict returns a token that can be used immediately, without another reload.
        self.save(sha256=latest["sha256"], action="edit", id=BLACK, row={"quantity": 90}, image="keep")
        self.assertEqual((accessories.read().rows_by_id[BLACK]["notes"],
                          accessories.read().rows_by_id[BLACK]["quantity"]), ("Concurrent note", 90))
        self.assertEqual(inventory.image(f"{BLACK}.png"), picture)

    def test_nonhome_and_hidden_owner_checks_happen_before_decoding(self):
        picture = png()
        hers = self.add({**SLEEVES, "owner": "user1"}, image=uploaded(picture), profile="user1")["changed_id"]
        before = self.files()
        with mock.patch.object(base64, "b64decode", side_effect=AssertionError("permission before decode")):
            error = self.error(api_acc.save_accessory, profile="user2", sha256=None, action="add",
                               row=SLEEVES, image={"upload": "%%%"})
            self.assertEqual(error.status, 403)
            error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=hers,
                               row={}, image={"upload": "%%%"})
            self.assertEqual(error.status, 404)
            error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="add",
                               row={**SLEEVES, "owner": "user1"}, image={"upload": "%%%"})
            self.assertEqual(error.status, 403)
        self.assertEqual(self.files(), before)
        with access.viewing("matt"), self.assertRaises(ApiError) as hidden:
            api_acc.image_file(f"{hers}.png", version(picture))
        self.assertEqual(hidden.exception.status, 404)
        with access.viewing("user1"):
            self.assertEqual(api_acc.image_file(f"{hers}.png", version(picture)), (picture, "image/png"))


class AccessoryUploadHttpTests(ServerTestCase):
    def test_save_route_accepts_upload_body_larger_than_editor_limit(self):
        picture = complete_jpeg(length=api.MAX_EDIT_BODY)
        body = json.dumps({"profile": "matt", "action": "add", "sha256": None,
                           "row": SLEEVES, "image": uploaded(picture)}).encode("utf-8")
        self.assertGreater(len(body), api.MAX_EDIT_BODY)
        self.assertLess(len(body), api_acc.MAX_SAVE_BODY)
        with mock.patch.object(api_acc, "save_accessory", return_value={"accepted": True}) as save:
            answer = self.get_json("/api/accessories/save", method="POST", body=body,
                                   headers=dict(WRITE, Origin=f"http://127.0.0.1:{self.port}"))
        self.assertEqual(answer, {"accepted": True})
        save.assert_called_once_with(body)

    def test_http_body_cap_refuses_before_the_save_handler(self):
        request = (f"POST /api/accessories/save HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                   "Content-Type: application/json\r\nX-Deck-Lab: 1\r\nConnection: close\r\n"
                   f"Content-Length: {api_acc.MAX_SAVE_BODY + 1}\r\n\r\n").encode("ascii")
        with mock.patch.object(api_acc, "save_accessory") as save:
            answer = self.raw(request)
        self.assertIn(b" 413 ", answer.split(b"\r\n", 1)[0])
        save.assert_not_called()

    def test_larger_accessory_limit_does_not_expand_editor_body_limit(self):
        body = b"{}" + b" " * api.MAX_EDIT_BODY
        with mock.patch.object(api, "save_deck") as save:
            self.assertError("/api/deck/save", 413, method="POST", body=body)
        save.assert_not_called()


class AccessoryUploadDatabaseTests(AccessoriesApiTestCase, db_support.DbTestCase):
    """One upload on the disposable PostgreSQL backend; never the user's database."""

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
        pg.write_model(adapt(FileInventory(self.root).load()), CLAUDE, "Import the upload fixture", contents={},
                       dbname=self.dbname, decks=True, images={})
        shutil.rmtree(self.magic / "decks")
        (self.magic / "products/status.csv").unlink()
        self.inventory = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.inventory))

    def stored(self):
        with self.connect() as connection:
            changes = connection.execute("select count(*) from audit.change_set").fetchone()[0]
            rows = connection.execute("select id, image, crop from accessory order by id").fetchall()
            images = connection.execute("select file_name, content from accessory_image order by file_name").fetchall()
        return changes, [tuple(row) for row in rows], [(name, bytes(data)) for name, data in images]

    def test_api_upload_saves_row_picture_and_crop_in_one_audited_change(self):
        baseline, _, _ = self.stored()
        picture = png()
        crop = "0.1,0.2,0.6,0.7"
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.add({**SLEEVES, "crop": crop}, image=uploaded(picture))
        self.assertTrue(answer["saved"])
        self.assertEqual((apply.call_count, apply.call_args.args[0].kind), (1, "accessory.add"))
        saved = self.stored()
        self.assertEqual(saved, (baseline + 1, [(BLACK, f"{BLACK}.png", crop)], [(f"{BLACK}.png", picture)]))
        self.assertFalse(accessories.PATH.exists())
        self.assertFalse((self.magic / "accessories").exists())
        self.assertFalse(accessory_fetch.STAGED.exists())
        with inventory.pinned():
            self.assertEqual(api_acc.image_file(f"{BLACK}.png", version(picture)), (picture, "image/png"))
        with mock.patch.object(inventory, "apply") as apply:
            error = self.error(api_acc.save_accessory, sha256=self.view()["sha256"], action="edit", id=BLACK,
                               row={"crop": "0,0,1,1"}, image=uploaded(picture[:-12]))
        self.assertEqual(error.status, 400)
        apply.assert_not_called()
        self.assertEqual(self.stored(), saved)
