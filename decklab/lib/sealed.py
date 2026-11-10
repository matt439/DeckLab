"""What a sealed product holds beyond its deck list, from MTGJSON's set files (E6-S29).

MTGJSON's deck files (lib/precons.py) are only a deck's fixed list. A product's own
record is in its set's file (https://mtgjson.com/api/v5/<SET>.json.gz), as
data.sealedProduct[].contents: "deck" names the deck lists in the box, "card" lists
the cards it always holds beyond them (a Secret Lair drop's bonus card, a Secret Lair
Commander deck's foil), and "pack", "sealed" and "variable" are random (a bonus
sheet's card, a Collector Booster sample pack, contents that vary), "other" what
isn't a card (a deck box, dice). Each deck file names its products in
sealedProductUuids, and the set file's decks list their cards by uuid.

A set file is big (SLD's was 2.4 MB compressed, 11 MB as JSON on 2026-11-10), so
only a small extract of it is kept (CACHE/<CODE>.json, a week: TTL), and a set file
is fetched only while a preview is being made (fetch=True), never while a page loads
or a change is saved (Matt, 2026-11-10). With fetch=False the extract is read
however old, and None when there's none. When MTGJSON can't be reached, an older
extract is used; with none at all the call is precons.PreconError.

No Wizards source says a bonus card is in every box (some drops since 2024 may swap
in an ultra-rare card), so a bonus card is "expected": a product's list gets it in
its extras section (rules.EXTRAS_SECTION) with an arrival check to confirm it. A
product MTGJSON lists with no bonus card gets no word about one (Matt, 2026-11-10).

    from decklab.lib import precons, sealed
    entry = precons.find("StardewValleyLifeInPelicanTown_SLD", products=True)
    sealed.contents(entry, precons.deck(entry["file"]))   # {"products", "fixed", "varies", "random", "other"}
    sealed.product_list(entry, data, contents)            # {"columns", "rows", "name", "format", "checks", ...}
    sealed.missing_bonus(rows)                            # warnings for a hand-written list
"""
import http.client
import json
import re
import time
import zlib

from decklab.lib import precons
from decklab.lib.inventory import rules

SET_URL = "https://mtgjson.com/api/v5/{}.json.gz"
CACHE = None                        # None: precons' cache / "sealed" (tests patch this)
TTL = 7 * 24 * 60 * 60              # seconds an extract is kept before it's fetched again
MAX_GZ_BYTES = 64 * 1024 * 1024     # SLD.json.gz was 2.4 MB on 2026-11-10
MAX_JSON_BYTES = 512 * 1024 * 1024  # and 11 MB as JSON
VERSION = 1                         # the extract's format; another is fetched again
MAX_SETS = 4                        # set codes a hand-written list is checked against
SET_RE = re.compile(r"[A-Za-z0-9]{2,8}")
UUID_RE = re.compile(r"[0-9a-f-]{36}")
MAX_COUNT = precons.MAX_COUNT

# How a product's format reads when it's filled from MTGJSON ("Commander precon (100 cards)").
FORMAT_WORDS = {"Commander Deck": "Commander precon", "Secret Lair Drop": "Secret Lair drop"}


def _cache_dir():
    return CACHE if CACHE is not None else precons._cache_dir() / "sealed"


def _text(value, limit=200):
    return precons._text(value, limit)


def _count(item):
    count = item.get("count", 1) if isinstance(item, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= MAX_COUNT else None


def _finish(item):
    """A contents card's finish: MTGJSON says foil with "foil": true, else by its only finish."""
    if item.get("foil") is True or item.get("isFoil") is True:
        return "foil"
    if item.get("isEtched") is True or item.get("etched") is True:
        return "etched"
    finishes = item.get("finishes")
    if isinstance(finishes, list) and len(finishes) == 1 and finishes[0] in rules.FINISHES:
        return finishes[0]
    return "nonfoil"


def _list(value):
    """value when it's a list, else [] (a set file's unexpected shape is read as nothing there)."""
    return value if isinstance(value, list) else []


def _token(item):
    """Whether a contents card is a token (MTGJSON's "token": true): a token card, never a playable one."""
    return isinstance(item, dict) and item.get("token") is True


def _card(item):
    """{"name", "set", "number", "finish", "count"} of a contents card, or None when any of it can't be
    read or it's a token (_other names those)."""
    if not isinstance(item, dict) or _token(item):
        return None
    name, code, number, count = _text(item.get("name")), item.get("set"), item.get("number"), _count(item)
    if not (name and isinstance(code, str) and SET_RE.fullmatch(code) and isinstance(number, str)
            and precons.NUMBER_RE.fullmatch(number) and count):
        return None
    return {"name": name, "set": code.lower(), "number": number, "finish": _finish(item), "count": count}


def _random(contents):
    """Words for a product's random contents, never added as cards."""
    words = []
    for item in _list(contents.get("pack")):
        code = _text(item.get("code"), 120) if isinstance(item, dict) else None
        if code and code.startswith("bonus"):
            words.append("a random bonus card")
        elif code:
            words.append(f"a random booster ({code})")
    for item in _list(contents.get("sealed")):
        name = _text(item.get("name")) if isinstance(item, dict) else None
        if name:
            count = _count(item) or 1
            words.append(f"{count} {name}" if count > 1 else name)
    if contents.get("variable"):
        words.append("contents that vary from box to box")
    return words


def _other(contents):
    """Words for what isn't a playable card: the other contents, and token cards listed as cards."""
    names = [_text(item.get("name")) for item in _list(contents.get("other")) if isinstance(item, dict)]
    tokens = [_text(item.get("name")) for item in _list(contents.get("card")) if _token(item)]
    return [name for name in names if name] + [f"token card: {name}" for name in tokens if name]


def _deck_card(item, cards_by_uuid):
    """[set, number, finish, count] of a set file's deck entry, or None when its card isn't in the set."""
    if not isinstance(item, dict) or not isinstance(item.get("uuid"), str):
        return None
    card, count = cards_by_uuid.get(item["uuid"]), _count(item)
    if card is None or count is None:
        return None
    return [card[0], card[1], _finish(item), count]


def _read_set(raw):
    """The extract kept of a set file's JSON: {"version", "code", "date", "products" {uuid: {"name",
    "decks", "fixed", "random", "other"}} (only products holding a deck), "decks" [{"name", "products",
    "printings" [[set, number, finish, count]]}]}."""
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise ValueError("not a set file")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    products = {}
    for item in _list(data.get("sealedProduct")):
        if not isinstance(item, dict) or not isinstance(item.get("uuid"), str) or not UUID_RE.fullmatch(item["uuid"]):
            continue
        contents = item.get("contents") if isinstance(item.get("contents"), dict) else {}
        decks = [_text(d.get("name")) for d in _list(contents.get("deck")) if isinstance(d, dict)]
        decks = [d for d in decks if d]
        if not decks:
            continue
        products[item["uuid"]] = {"name": _text(item.get("name")) or "", "decks": decks,
                                  "fixed": [c for c in map(_card, _list(contents.get("card"))) if c],
                                  "random": _random(contents), "other": _other(contents)}
    cards_by_uuid = {}
    for card in _list(data.get("cards")):
        if isinstance(card, dict) and isinstance(card.get("uuid"), str) and isinstance(card.get("setCode"), str) \
                and SET_RE.fullmatch(card["setCode"]) and isinstance(card.get("number"), str) \
                and precons.NUMBER_RE.fullmatch(card["number"]):
            cards_by_uuid[card["uuid"]] = (card["setCode"].lower(), card["number"])
    decks = []
    for deck in _list(data.get("decks")):
        if not isinstance(deck, dict) or not _text(deck.get("name")):
            continue
        linked = [u for u in _list(deck.get("sealedProductUuids")) if isinstance(u, str) and u in products]
        if not linked:
            continue
        printings = [p for board in ("commander", "mainBoard", "sideBoard")
                     for p in (_deck_card(item, cards_by_uuid) for item in _list(deck.get(board))) if p]
        decks.append({"name": deck["name"].strip(), "products": linked, "printings": printings})
    code = data.get("code") if isinstance(data.get("code"), str) else ""
    return {"version": VERSION, "code": code.upper(), "date": meta.get("date") if isinstance(meta.get("date"), str) else "",
            "products": products, "decks": decks}


def _fetch_set(code):
    data = precons._fetch(SET_URL.format(code), MAX_GZ_BYTES)
    unzip = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        text = unzip.decompress(data, MAX_JSON_BYTES + 1)
    except zlib.error as e:
        raise ValueError(f"not gzip: {e}") from None
    if len(text) > MAX_JSON_BYTES or unzip.unconsumed_tail:
        raise precons.PreconError(f"{code}.json is bigger than {MAX_JSON_BYTES // (1024 * 1024)} MB")
    return json.loads(text)


def _kept(path):
    """The extract at path, or None when it isn't there or isn't one this version reads."""
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(kept, dict) or kept.get("version") != VERSION or not isinstance(kept.get("products"), dict) \
            or not isinstance(kept.get("decks"), list):
        return None
    return kept


def extract(code, fetch=True, refresh=False):
    """The set's extract (_read_set), kept a week. fetch=False: only what's kept, however old (None
    when nothing is). refresh: fetched again however young the kept one is (one that lacks a deck
    MTGJSON's list now has: _holding), still not within RETRY_AFTER of a failed fetch.
    precons.PreconError when it must be fetched, can't be, and nothing is kept."""
    if not isinstance(code, str) or not SET_RE.fullmatch(code):
        return None
    code = code.upper()
    path = _cache_dir() / f"{code}.json"
    kept = _kept(path)
    if not fetch:
        return kept
    url = SET_URL.format(code)
    with precons._lock:
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = None
        failed = precons._failed.get(url)
        resting = failed is not None and time.monotonic() - failed < precons.RETRY_AFTER
        if kept is not None and age is not None and ((age < TTL and not refresh) or resting):
            return kept
        if resting:
            raise precons.PreconError(f"MTGJSON's {code} set file couldn't be fetched a few minutes ago; try again later.")
        try:
            made = _read_set(_fetch_set(code))
        except (OSError, ValueError, TypeError, AttributeError, precons.PreconError, http.client.HTTPException) as e:
            precons._failed[url] = time.monotonic()
            if kept is not None:
                return kept
            raise precons.PreconError(f"MTGJSON's {code} set file couldn't be fetched ({e}); try again later.") from None
        precons._failed.pop(url, None)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(made, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass                            # used now, fetched again next time
        return made


def _key(card):
    return (card["set"], card["number"], card["finish"])


def _together(products):
    """(fixed, varies) over a deck's products: the cards every one of them holds (the fewest copies
    any holds), and those only some hold (the deck in a foil and a nonfoil box, say)."""
    if not products:
        return [], []
    counts = []
    for product in products:
        found = {}
        for card in product["fixed"]:
            if _key(card) in found:
                found[_key(card)]["count"] += card["count"]
            else:
                found[_key(card)] = dict(card)
        counts.append(found)
    keys = list(dict.fromkeys(k for found in counts for k in found))
    fixed, varies = [], []
    for k in keys:
        if all(k in found for found in counts):
            fixed.append(dict(counts[0][k], count=min(found[k]["count"] for found in counts)))
        else:
            varies.append(next(found[k] for found in counts if k in found))
    return fixed, varies


def _holding(kept, uuids, name):
    """The extract's product uuids holding the deck: those its deck file names, else those of its
    decks of that name; [] when the extract has neither."""
    found = [u for u in dict.fromkeys(uuids) if u in kept["products"]]
    if not found:
        found = list(dict.fromkeys(u for deck in kept["decks"] if deck["name"] == name for u in deck["products"]
                                   if u in kept["products"]))
    return found


def contents(entry, data, fetch=True):
    """What the deck's products hold beyond its list: {"products" [names], "fixed" [{"name", "set",
    "number", "finish", "count"}] (in every box: a bonus card), "varies" [those only some of its
    products hold], "random" [words], "other" [words]}; None when the set's extract isn't kept and
    fetch is False. entry is a precons.find(..., products=True) entry, data its deck file."""
    kept = extract(entry["code"], fetch)
    if kept is None:
        return None
    given = [u for u in _list(data.get("sealedProductUuids")) if isinstance(u, str)] if isinstance(data, dict) else []
    uuids = _holding(kept, given, entry["name"])
    if not uuids and fetch:
        # A deck MTGJSON's daily list has but the week-old extract doesn't (a new drop): fetch it again once.
        try:
            kept = extract(entry["code"], fetch, refresh=True) or kept
        except precons.PreconError:
            pass
        uuids = _holding(kept, given, entry["name"])
    products = [kept["products"][u] for u in uuids]
    fixed, varies = _together(products)
    return {"products": [p["name"] for p in products], "fixed": fixed, "varies": varies,
            "random": list(dict.fromkeys(w for p in products for w in p["random"])),
            "other": list(dict.fromkeys(w for p in products for w in p["other"]))}


def describe(card):
    """"Sylvan Caryatid (SLD 7189)", with its finish when it isn't nonfoil."""
    finish = "" if card["finish"] == "nonfoil" else f", {card['finish']}"
    return f"{card['name']} ({card['set'].upper()} {card['number']}{finish})"


def check_text(card):
    """The arrival check a bonus card's row gets."""
    return f"Confirm {describe(card)} was in the box: it's the expected bonus card"


def product_list(entry, data, found, include_bonus=True, pickable=None):
    """A product's card list filled from a deck file and its contents: {"columns", "rows" (dicts of
    strings), "name", "format", "checks", "bonus" (the fixed cards, each {"card", "words"}), "random",
    "other", "left_out" (problems and cards not listed)}. A Secret Lair drop's cards have no section
    (cards only, not a deck); a deck's are in its commander, deck and sideboard sections. Each fixed
    card goes in the extras section when include_bonus, with an arrival check. A display commander
    is listed in extras too when pickable(line) says it's a card to play with (the foil-etched copy),
    else only named in left_out."""
    read = precons.cards_of(data)
    cards_only = entry["type"] in precons.PRODUCT_TYPES
    extras, checks, left_out = [], [], list(read["problems"])
    bonus = (found or {}).get("fixed") or []
    product_name = entry["name"]
    for card in bonus if include_bonus else ():
        extras.append({"name": card["name"], "set": card["set"], "collector_number": card["number"],
                       "finish": card["finish"], "quantity": str(card["count"]), "section": rules.EXTRAS_SECTION,
                       "notes": f"bonus card in {product_name}"})
        checks.append(check_text(card))
    for line in read["display"]:
        if pickable is not None and pickable(line):
            extras.append({"name": line["name"], "set": line["set"], "collector_number": line["number"],
                           "finish": line["finish"], "quantity": str(line["count"]), "section": rules.EXTRAS_SECTION,
                           "notes": "display commander"})
        else:
            left_out.append(f"{line['count']} display commander ({line['name']}), not a card to play with")
    rows = []
    for line in read["lines"]:
        section = "" if cards_only else line["section"].lower()
        notes = "full art" if line["name"] in rules.BASIC_LANDS and line["full_art"] else ""
        rows.append({"name": line["name"], "set": line["set"], "collector_number": line["number"],
                     "finish": line["finish"], "quantity": str(line["count"]), "section": section, "notes": notes})
    for words in (f"{n} {kind}{'s' if n > 1 else ''}" for kind, n in read["left_out"].items()):
        left_out.append(f"{words}, not playable cards")
    columns = ["name", "set", "collector_number", "finish", "quantity"]
    if not cards_only or extras:
        columns.append("section")
    if any(row["notes"] for row in rows + extras):
        columns.append("notes")
    rows = [{k: row[k] for k in columns} for row in rows + extras]
    total = sum(line["count"] for line in read["lines"])
    extra_count = sum(int(row["quantity"]) for row in extras)
    words = FORMAT_WORDS.get(entry["type"], entry["type"])
    fmt = f"{words} ({total} cards" + (f" + {extra_count} extra" if extra_count else "") + ")"
    return {"columns": columns, "rows": rows, "name": product_name, "format": fmt, "checks": checks,
            "bonus": [{"card": card, "words": describe(card)} for card in bonus],
            "varies": [describe(card) for card in (found or {}).get("varies") or []],
            "random": list((found or {}).get("random") or []), "other": list((found or {}).get("other") or []),
            "left_out": left_out}


def _row_keys(rows):
    keys, loose = set(), set()
    for row in rows:
        code, number, finish = (row.get("set") or "").lower(), row.get("collector_number") or "", row.get("finish") or ""
        if code and number:
            keys.add((code, number, finish))
            loose.add((code, number))
    return keys, loose


def missing_bonus(rows, fetch=True):
    """Warnings for a hand-written product list (rows as dicts) holding every printing of a published
    deck but not the bonus card its products always hold, each saying what to add (missing_cards)."""
    return [f"{item['deck']} is expected to come with a bonus card, {item['card']['count']} "
            f"{describe(item['card'])}, that this list doesn't have: add it as a row in the extras "
            "section, so decks count it as on the way and it's added when the product arrives."
            for item in missing_cards(rows, fetch)]


def with_bonus(columns, rows, missing):
    """(columns, rows) of a product list with each missing bonus card (missing_cards) added in the
    extras section: a section column is added when the list has none, its other rows' left blank (so
    a cards-only list stays cards only); a list that read as decks with blank sections gets them
    written as deck, so the extras row doesn't make it cards only (rules.product_reads_as_decks)."""
    decks = rules.product_reads_as_decks(columns, rows)
    columns = list(columns)
    if "section" not in columns:
        columns.append("section")
    out = [{key: row.get(key, "") for key in columns} for row in rows]
    if decks:
        for row in out:
            if not (row["section"] or "").strip():
                row["section"] = "deck"
    for item in missing:
        card = item["card"]
        row = {key: "" for key in columns}
        row.update({"name": card["name"], "set": card["set"], "collector_number": card["number"],
                    "finish": card["finish"], "quantity": str(card["count"]), "section": rules.EXTRAS_SECTION})
        if "notes" in columns:
            row["notes"] = f"bonus card in {item['deck']}"
        out.append(row)
    return columns, out


def missing_cards(rows, fetch=True):
    """[{"deck", "card"}] for a hand-written product list (rows as dicts) holding every printing of a
    published deck but not the bonus card its products always hold. Never more than MAX_SETS set
    codes are looked up; a set whose extract can't be had is passed over (fetch as extract()). A
    deck whose bonus card is listed, or whose products hold none, gets nothing."""
    keys, loose = _row_keys(rows)
    codes = sorted({code for code, _, _ in keys})
    if not codes or len(codes) > MAX_SETS:
        return []
    said, found = set(), []
    for code in codes:
        try:
            kept = extract(code, fetch)
            matched = _matching(kept, keys, loose) if kept is not None else []
            if not matched and kept is not None and fetch and _age(code) > precons.TTL:
                # Perhaps a deck newer than the kept extract (MTGJSON's deck list is a day old at most).
                kept = extract(code, fetch, refresh=True) or kept
                matched = _matching(kept, keys, loose)
        except precons.PreconError:
            continue
        proposed = {}
        for deck in matched:
            products = [kept["products"][u] for u in deck["products"] if u in kept["products"]]
            fixed, _ = _together(products)
            for card in fixed:
                if (card["set"], card["number"]) not in loose:
                    proposed.setdefault((card["set"], card["number"]), []).append((deck["name"], card))
        for at, items in proposed.items():
            # A nonfoil box and its foil edition both matching a list whose finishes don't settle which
            # it is: the bonus card's finish can't be told, so none is proposed.
            if at in said or len({card["finish"] for _, card in items}) > 1:
                continue
            said.add(at)
            found.append({"deck": items[0][0], "card": items[0][1]})
    return found


def _matching(kept, keys, loose):
    """The extract's decks whose every printing the list holds: those matching each printing's finish
    too; else, by set and number only, the ones matching the most finishes (none when no finish
    matches: a nonfoil list isn't its foil edition's)."""
    decks = [d for d in kept["decks"] if d["printings"]]
    exact = [d for d in decks if all((p[0], p[1], p[2]) in keys for p in d["printings"])]
    if exact:
        return exact
    near = [d for d in decks if all((p[0], p[1]) in loose for p in d["printings"])]
    if not near:
        return []
    score = {id(d): sum((p[0], p[1], p[2]) in keys for p in d["printings"]) for d in near}
    best = max(score.values())
    return [d for d in near if score[id(d)] == best] if best else []


def _age(code):
    """Seconds since the set's extract was kept (infinite when it isn't)."""
    try:
        return time.time() - (_cache_dir() / f"{code.upper()}.json").stat().st_mtime
    except OSError:
        return float("inf")
