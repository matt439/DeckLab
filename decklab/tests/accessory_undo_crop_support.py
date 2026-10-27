"""Synthetic crop/photo fixtures whose actual byte reader is independent of ImageMeta."""
import copy

from decklab.lib import accessories
from decklab.tests import accessory_undo_support as support
from decklab.tests import test_accessory_fetch as pictures
from decklab.tests import test_accessory_undo_api as api_support

CONTENTS = {"jpg": pictures.jpeg, "png": pictures.png, "webp": pictures.webp_vp8}


class PhotoReader:
    def accessory_undo_photo(self, name, sha256, size):
        """Deliberately do not validate arguments or bytes: the kernel must prove them."""
        self.photo_calls.append((name, sha256, size))
        return self.photo_bytes.get(name)


class PhotoInventory(PhotoReader, support.AuditAccessoryInventory):
    pass


class CropAuditAccessories(PhotoReader, api_support.AuditAccessories):
    pass


def seed_crop(store, *, ext="jpg", kind="sleeves", owner="matt", quantity="100", current="0.1,0.1,0.8,0.8",
              historical="", held=False):
    """One crop-only audited edit with valid current bytes, never a historical photo."""
    from dataclasses import replace
    name, content = "a-sleeves." + ext, CONTENTS[ext]()
    new = support.row(kind=kind, owner=owner, quantity=quantity, image=name, crop=current,
                      capacity="100" if kind == "deck_box" else "")
    old = {**new, "crop": historical}
    rows = [new if row.accessory_id == "a-sleeves" else row.as_dict() for row in support.build_snapshot().accessories.rows]
    snapshot = support.build_snapshot(rows).with_image(name, content)
    if ext != "jpg":
        snapshot = snapshot.without_image("a-sleeves.jpg")
    private = pictures.jpeg(width=302)
    snapshot = snapshot.with_image("c-hidden.jpg", private)
    deck = snapshot.deck("casual/fixture")
    line = ("- **Deck box:** a-sleeves\n" if kind == "deck_box" else "- **Sleeves:** a-sleeves\n") if held and kind != "playmat" else ""
    snapshot = snapshot.with_deck(replace(deck, text=deck.text.replace("- **Sleeves:** a-sleeves\n", line)))
    store.snapshot = snapshot
    store.audit = {support.CHANGE_ID: [{"id": support.ROW_ID, "table": "accessory", "op": "UPDATE",
                    "key": {"id": new["id"]}, "before": copy.deepcopy(old), "after": copy.deepcopy(new)}]}
    store.latest = support.ROW_ID
    store.photo_bytes = {name: content, "c-hidden.jpg": private}
    store.photo_calls = []
    store.writes.clear()
    if hasattr(store, "calls"):
        store.calls.clear()
    if hasattr(store, "fail_after_commit"):
        store.fail_after_commit = False
    return new, old


def photo(store, name=None):
    name = next(iter(store.photo_bytes)) if name is None else name
    meta = store.snapshot.image_meta(name)
    return {"name": meta.name, "size": meta.size, "sha256": meta.sha256, "version": accessories.image_version(meta)}


def replace_photo(store, content, name=None, *, update_meta=True):
    name = next(iter(store.photo_bytes)) if name is None else name
    store.photo_bytes[name] = content
    if update_meta:
        store.snapshot = store.snapshot.with_image(name, content)
