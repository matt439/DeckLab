"""Complete-record unused proof before reversing an accessory insertion."""
import io

from decklab.lib import accessories, inventory

from . import files, rules
from .undo import UndoConflict, _home_products, _known_decks

REFUSED = "The accessory's references cannot be checked safely. Use the normal editor."


def _reference(value, rid):
    if not isinstance(value, str):
        raise ValueError("Unknown reference")
    if " ".join(value.split()) == rid:
        raise ValueError("Referenced accessory")


def _decks(snapshot, rid):
    known = _known_decks(snapshot, "home")
    home = [stored for stored in snapshot.decks.values() if stored.space == "home"]
    if len({stored.id for stored in home}) != len(home):
        raise ValueError("Ambiguous deck")
    for stored in home:
        if stored.error is not None or not isinstance(stored.text, str) or "\0" in stored.text:
            raise ValueError("Unreadable deck")
        stored.text.encode("utf-8", errors="strict")
    for deck in known:
        if not deck.has_decklist:
            raise ValueError("Unknown deck list")
        for key in ("sleeves", "deck box"):
            fields = [field for field in deck.header if field.key.casefold() == key]
            if len(fields) > 1:
                raise ValueError("Ambiguous accessory header")
            for field in fields:
                _reference(field.value, rid)


def _products(snapshot, rid):
    _home_products(snapshot, "home")
    sheet = snapshot.status
    missing = files.status_sheet(None)
    if not snapshot.products and not sheet.exists and not sheet.rows and sheet.columns is None \
            and sheet.path == missing.path and sheet.error is None and sheet.strict_error is None and sheet.csv_error is None \
            and sheet.problems in ((), missing.problems):
        return True
    if not sheet.exists or sheet.error is not None or sheet.strict_error or sheet.csv_error or sheet.problems \
            or tuple(sheet.columns or ()) != tuple(rules.STATUS_FIELDS):
        raise ValueError("Unknown product status")
    seen = set()
    for row in sheet.rows:
        raw = row.as_dict()
        if row.overflow or row.columns() != tuple(rules.STATUS_FIELDS) or set(raw) != set(rules.STATUS_FIELDS) \
                or any(not isinstance(value, str) for value in raw.values()):
            raise ValueError("Unknown status row")
        if raw["file"] in seen:
            raise ValueError("Ambiguous status row")
        seen.add(raw["file"])
        for value in raw.values():
            if "\0" in value:
                raise ValueError("Invalid status text")
            value.encode("utf-8", errors="strict")
        _reference(raw["sleeves"], rid)
        _reference(raw["deck_box"], rid)
    products = set()
    for product in snapshot.products:
        if product.file in products or product.error is not None or product.problems or product.strict_error or product.csv_error:
            raise ValueError("Unknown product")
        products.add(product.file)
        columns = product.columns
        if not columns or len(columns) != len(set(columns)) or not rules.REQUIRED <= set(columns) \
                or set(columns) - (set(rules.FIELDS) | rules.PRODUCT_FIELDS):
            raise ValueError("Unknown product columns")
        for item in product.items:
            if item.overflow or item.columns() != tuple(columns) or any(not isinstance(value, str) for _, value in item.values):
                raise ValueError("Unknown product row")
            for _, value in item.values:
                if "\0" in value:
                    raise ValueError("Invalid product text")
                value.encode("utf-8", errors="strict")
        rules.parse_cards(io.StringIO(files.render_product(product).decode("utf-8"), newline=""), "Accessory Undo")
    if seen != products:
        raise ValueError("Missing product or status")
    return False


def unused(snapshot, rid):
    """Refuse any reference or incomplete holder evidence, without private details."""
    try:
        if not isinstance(rid, str) or not accessories.valid_id(rid):
            raise ValueError("Unknown accessory")
        _decks(snapshot, rid)
        missing_empty_status = _products(snapshot, rid)
        warnings = []
        with inventory.pinned(snapshot):
            found, strays = accessories._scan(warnings)
            listing = accessories.from_sheet(snapshot.accessories, strict=True)
            usage = accessories._usage(found, listing)
        if missing_empty_status and warnings == list(files.status_sheet(None).problems):
            warnings = []  # The fully proved empty product namespace has no physical holder.
        if warnings or not isinstance(found, list) or not isinstance(strays, list) or strays or not isinstance(usage, dict):
            raise ValueError("Unknown holder scan")
        for holder in found:
            for field in ("sleeves", "deck_box"):
                _reference(holder[field], rid)
        for holders in usage.values():
            if not isinstance(holders, list) or not holders \
                    or any(not isinstance(holder, dict) or holder.get("state") != "linked" for holder in holders):
                raise ValueError("Unknown kit identity")
        if usage.get(rid):
            raise ValueError("Held accessory")
    except Exception:
        raise UndoConflict(REFUSED) from None
