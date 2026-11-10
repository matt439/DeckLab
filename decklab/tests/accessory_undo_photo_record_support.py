"""Combined crop/fact fixtures retain one independently verified current photo."""
from decklab.lib.inventory import accessory_undo as undo
from decklab.tests import accessory_undo_crop_support as crop
from decklab.tests import accessory_undo_support as support


def seed(store, restored=None, *, held=False):
    new, old = crop.seed_crop(store, kind="deck_box", quantity="2", held=held)
    old.update({"notes": "Historical <img src=x> Literal note"} if restored is None else restored)
    store.audit[support.CHANGE_ID][0]["before"] = dict(old)
    return new, old


def options():
    return {"confirm_record": True, "confirm_photo": True}


def actual(plan):
    return support.actual_source(plan)


def fields(new, old):
    return [{"field": field, "before": new[field], "after": old[field]}
            for field in undo.UPDATE_FIELDS["accessory_photo_record_update"] if new[field] != old[field]]
