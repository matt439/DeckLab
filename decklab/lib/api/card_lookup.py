"""Cards for the page: a decklist name's exact Scryfall name, which printing
to show (or give a new line), a card's and a decklist line's JSON with its
image URLs, the owned-vs-needed JSON, and the endpoints built on them: the
editor's autocomplete (search), its printing picker (printings) and the
card images (image_file).
"""
import math
import re
import threading
import time
import urllib.error
import urllib.parse
from collections import Counter
from datetime import date

from decklab.lib import cards, decks, pool, spaces

from . import common
from .carddata import _require_cards
from .common import LINE_FINISHES, MAX_NAME, NUMBER_RE, SET_RE, _CONTROL_RE, ApiError, _jsonable, _public, _scrub

SEARCH_LIMIT = (20, 50)         # default and largest number of names
DID_YOU_MEAN = 3                # search() suggests close spellings for fewer matches than this, at most this many
MAX_SEARCH = 100                # characters of search text

# Decklist lines that name no printing (basic lands) show one from these set
# types (the ordinary frame; not Secret Lair, promos or collector sets).
REGULAR_SET_TYPES = ("core", "expansion")

MAX_PRINTINGS = 100             # printings printings() lists
_PRICE_KEYS = {"nonfoil": "usd", "foil": "usd_foil", "etched": "usd_etched"}
MISSING_IMAGE_SECONDS = 6 * 3600    # how long image_file remembers that Scryfall has no such image (its 404)
MAX_MISSING_IMAGES = 2000
_missing_images = {}                # (set, number, size): when Scryfall said 404 (time.monotonic())
_missing_lock = threading.Lock()


def _resolve(name):
    """The exact Scryfall name for a decklist name, or None. Uses pool's
    rules, so the page and the owned-vs-needed counts agree."""
    unresolved = {}
    exact = pool._canonical(name, "decklist", unresolved)
    return None if unresolved else exact


def _showable(p):
    """True for a printing worth showing: paper, not oversized or gold-bordered, with an image."""
    return (not p["digital"] and "paper" in p["games"] and not p["oversized"]
            and p["set_type"] not in cards.UNPLAYABLE_PRICE_SET_TYPES and p["image_normal"])


def _number_key(number):
    """Collector numbers in number order ("9" < "12a" < "280"); ones with no digits last."""
    m = re.match(r"\d+", number)
    return (int(m.group()) if m else math.inf, number)


def _shown_printing(card, prefer=()):
    """The printing to show for a decklist line that names none (or names one
    Scryfall doesn't have): from the first set in prefer that has the card
    (the line's own set, then the deck's sets, most used first), else the
    newest core or expansion set, else the newest set. Within a set it's the
    lowest collector number, the ordinary frame: full-art, borderless and
    showcase versions are numbered after it (Foundations' Forests 280 and 281
    are the regular ones, 290 and 291 full art). So a deck's basic lands look
    like the ones in its set, not a Secret Lair's. Sets not released yet
    (Scryfall has previews) only count when there's nothing else."""
    today = date.today().isoformat()
    by_set, released = {}, {}       # newest set first, as card["printings"] is
    for s, n in card["printings"]:
        p = cards.printing(s, n)
        if p is not None and _showable(p):
            by_set.setdefault(s, []).append((n, p))
            released[s] = released.get(s, False) or (p["released_at"] or "") <= today

    def lowest(s):
        return min(by_set[s], key=lambda item: _number_key(item[0]))[1]

    for s in prefer:
        if s and s in by_set:
            return lowest(s)
    for fits in (lambda s: released[s] and by_set[s][0][1]["set_type"] in REGULAR_SET_TYPES,
                 lambda s: released[s],
                 lambda s: True):
        for s in by_set:
            if fits(s):
                return lowest(s)
    return None


def image_url(set_code, number, size):
    """The server's URL for a printing's image, or None if the printing can't be named in one."""
    if not (isinstance(set_code, str) and SET_RE.fullmatch(set_code)
            and isinstance(number, str) and NUMBER_RE.fullmatch(number)):
        return None
    return f"/img/{set_code}/{urllib.parse.quote(number, safe='')}/{size}"


def _card_json(card, p):
    def url(size):
        return image_url(p["set"], p["collector_number"], size) if p and p.get("image_" + size) else None
    out = {
        "name": card["name"], "mana_cost": card["mana_cost"], "cmc": card["cmc"],
        "type_line": card["type_line"], "colors": list(card["colors"]),
        "color_identity": list(card["color_identity"]), "roles": list(card["roles"]),
        "img": url("normal"), "img_small": url("small"),
        "oracle_text": card.get("oracle_text", ""),
        **{key: card.get(key) for key in ("power", "toughness", "loyalty", "defense")},
    }
    if card.get("faces"):
        out["faces"] = []
        for i, face in enumerate(card["faces"]):
            # Split/adventure/flip cards share one image; actual double-faced printings have a back.
            back = i == 1 and (card.get("layout") in ("transform", "modal_dfc")
                               or p and p.get("image_normal-back"))
            out["faces"].append({**{key: face.get(key) for key in cards.FACE_FIELDS},
                                 "img": url("normal-back" if back else "normal"),
                                 "img_small": url("small-back" if back else "small")})
    return out


def _line_json(line, section, warnings, deck_sets=()):
    """One decklist line for the page, with its card's data and image.
    deck_sets: the sets the deck's lines name, most used first, for lines that name none."""
    out = {"qty": line.quantity, "name": line.name, "set": line.set, "number": line.number,
           "finish": line.finish, "card": None}
    exact = _resolve(line.name)
    card = cards.card(exact) if exact else None
    if card is None:
        warnings.append(f"{line.name!r} ({section}) isn't a Scryfall card name, so there's no card data for it")
        return out
    shown = None
    if line.set and line.number:
        written = f"{line.name} ({line.set.upper()}) {line.number}"
        p = cards.printing(line.set, line.number)
        printed = cards.printing_card(line.set, line.number) if p else None
        if printed is not None and printed["name"] == card["name"]:
            # An Un-set card printed in several versions has each version's own text.
            card, shown = printed, p
        elif p is None:
            warnings.append(f"{written}: Scryfall has no printing {line.set.upper()} {line.number}")
        else:
            warnings.append(f"{written}: {line.set.upper()} {line.number} is {p['name']}, not {card['name']}")
    if shown is None:
        shown = _shown_printing(card, (line.set, *deck_sets))
    out["card"] = _card_json(card, shown)
    return out


def _owned_json(result, p=None):
    """A pool.compare / owned_vs_needed result for the page. Each row gets
    the labels the deck file's table would get: only the copies this deck
    counts on that are still on the way, and the decks holding a card only
    when they leave this deck short. labels.incoming_sources names each pending
    order/product and its ordered/preordered status, clipped to the same copies
    as labels.on_the_way. Source identity comes from the pool's snapshot, never
    from parsing its human labels; products with equal names stay distinct. p is the
    compared pool: public readers get counts without home's source identities or hidden
    deck titles (inventory_views.owned)."""
    for row in result["rows"]:
        row["labels"] = pool.row_labels(row)
        row["labels"]["incoming_sources"] = [
            dict(source, quantity=qty) for source, (_, qty) in
            zip(row.pop("incoming_sources", []), row["labels"]["on_the_way"])]
    from .inventory_views import owned
    result = owned(result, p)
    result["warnings"] = _scrub(result["warnings"])
    return _jsonable(result)


def _card_printings(exact):
    """[(set, number)] of a card, newest first ([] for a basic land name the
    card data lacks: _resolve passes basic lands through as written)."""
    card = cards.card(exact)
    return card["printings"] if card else []


def _pool_counts():
    """pool.printing_counts() of the pool this request is shown copies of:
    the viewer's own space's (home's for Matt and User1, User3's for
    User3), never another space's even once it can be public (E10-S29),
    so a member's printing picker and pasted list count and pick from their
    own cards; home's for a script naming nobody; none ({}) for anyone else
    (a request naming nobody, a login that isn't set up)."""
    from decklab.lib import permissions
    from . import guard
    try:
        viewer = guard.viewer()
    except ApiError:
        return {}
    if viewer is None:
        return pool.printing_counts() if guard.script() else {}
    own = permissions._space_of(viewer)
    if not guard.sees_inventory(own, viewer):
        return {}
    return pool.printing_counts() if own == spaces.HOME else pool.printing_counts(own)


def _pickable(p):
    """A printing a deck line may name: paper, not oversized or gold-bordered."""
    return (p is not None and not p["digital"] and "paper" in p["games"] and not p["oversized"]
            and p["set_type"] not in cards.UNPLAYABLE_PRICE_SET_TYPES)


def _not_paper(p):
    """What a printing _pickable() refuses is, in a few words."""
    if p["digital"] or "paper" not in p["games"]:
        return "an online-only printing"
    if p["oversized"]:
        return "an oversized card"
    return "a collectors' or memorabilia printing (not a tournament-legal card back)"


def _newest_nonfoil(card):
    """The newest non-foil paper printing of a card that has no price, as
    _shown_printing picks one (a released core or expansion set first), or None."""
    today = date.today().isoformat()
    found = [p for p in (cards.printing(s, n) for s, n in card["printings"])        # newest first
             if _pickable(p) and "nonfoil" in p["finishes"]]
    for fits in (lambda p: (p["released_at"] or "") <= today and p["set_type"] in REGULAR_SET_TYPES,
                 lambda p: (p["released_at"] or "") <= today,
                 lambda p: True):
        for p in found:
            if fits(p):
                return p
    return None


def _default_printing(exact, counts):
    """The printing a new line of this card gets (AGENTS.md, PLAN.md part 2):
    the one the pool has most copies of (owned plus on the way; a tie goes to
    the newer), else the cheapest non-foil paper printing, else the newest
    non-foil paper printing (one with no price yet), and only for a card
    printed in foil alone the cheapest foil, else the newest printing.
    {"set", "number", "finish", "why": "owned" | "cheapest" | "newest"} or None."""
    card = cards.card(exact)
    best = cheapest = None
    for set_code, number in card["printings"]:          # newest first
        p = cards.printing(set_code, number)
        if not _pickable(p):
            continue
        for finish in p["finishes"]:
            have = sum((counts.get((set_code, number, finish)) or {}).values())
            if have and (best is None or have > best[0]):
                best = (have, set_code, number, finish)
        # As cards.cheapest_usd: the first of equal prices, so the newest.
        if p["usd"] is not None and (cheapest is None or p["usd"] < cheapest[0]):
            cheapest = (p["usd"], set_code, number, "nonfoil")
    if best:
        return {"set": best[1], "number": best[2], "finish": best[3], "why": "owned"}
    if cheapest:
        return {"set": cheapest[1], "number": cheapest[2], "finish": "nonfoil", "why": "cheapest"}
    unpriced = _newest_nonfoil(card)
    if unpriced:
        return {"set": unpriced["set"], "number": unpriced["collector_number"], "finish": "nonfoil",
                "why": "newest"}
    cheapest = cards.cheapest_usd(exact)                 # printed in foil (or etched) only
    if cheapest:
        return {"set": cheapest[1], "number": cheapest[2], "finish": cheapest[3], "why": "cheapest"}
    shown = _shown_printing(card)
    if shown:
        finish = "nonfoil" if "nonfoil" in shown["finishes"] else (shown["finishes"] or ["nonfoil"])[0]
        return {"set": shown["set"], "number": shown["collector_number"], "finish": finish, "why": "newest"}
    return None


def _lines_json(sections, warnings):
    """A decklist's lines for the page, as deck_view gives them (None stays None)."""
    if sections is None:
        return None
    sets = Counter()
    for lines in sections.values():
        for line in lines:
            if line.set:
                sets[line.set] += line.quantity
    deck_sets = [s for s, _ in sets.most_common()]
    return {name: [_line_json(line, name, warnings, deck_sets) for line in lines] for name, lines in sections.items()}


def printings(name):
    """GET /api/cards/printings?name=<name>: the editor's printing picker.

    Returns name (exact), basic, default (_default_printing; None for basic
    lands, whose lines name no set), printings (one per paper printing and
    finish: set, number, finish, released, set_type, set_name (the code in
    capitals when the card data has no name), usd, aud (an estimate), owned,
    on_the_way, img_small and img (the normal picture); the ones the pool has first, then cheapest,
    then newest; at most MAX_PRINTINGS; owned and on_the_way count home's
    pool, or for a visitor outside the home their own space's: _pool_counts), total, and rate, rate_date,
    price_date and price_error, which go with every AUD figure."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        raise ApiError(400, f"Give a card name of at most {MAX_NAME} characters")
    _require_cards()
    exact = _resolve(name.strip())
    if exact is None:
        raise ApiError(404, f"No card named {name.strip()!r}")
    counts = _pool_counts()
    answer = {"name": exact, "basic": decks.is_basic_land(exact), "default": None, "printings": [], "total": 0,
              "rate": None, "rate_date": None, "price_date": None, "price_error": None}
    rate = None
    try:
        rate, rate_date = cards.usd_to_aud()
        answer.update(rate=rate, rate_date=rate_date, price_date=cards.price_date() or None)
    except RuntimeError as e:          # offline with no cached rate
        answer["price_error"] = _public(e)
    found = []
    for set_code, number in _card_printings(exact):
        p = cards.printing(set_code, number)
        if not _pickable(p):
            continue
        for finish in p["finishes"]:
            if finish not in LINE_FINISHES:
                continue
            usd = p[_PRICE_KEYS[finish]]
            have = counts.get((set_code, number, finish)) or {}
            found.append({"set": set_code, "number": number, "finish": finish, "released": p["released_at"],
                          "set_type": p["set_type"], "usd": usd,
                          "aud": round(usd * rate, 2) if usd is not None and rate else None,
                          "owned": have.get("owned", 0), "on_the_way": have.get("on_the_way", 0),
                          "set_name": p.get("set_name") or set_code.upper(),
                          "img_small": image_url(set_code, number, "small") if p["image_small"] else None,
                          "img": image_url(set_code, number, "normal") if p.get("image_normal") else None})
    found.sort(key=lambda e: e["released"] or "", reverse=True)
    found.sort(key=lambda e: (-(e["owned"] + e["on_the_way"]), e["usd"] is None, e["usd"] or 0))
    answer.update(printings=found[:MAX_PRINTINGS], total=len(found),
                  default=None if answer["basic"] else _default_printing(exact, counts))
    return answer


def search(q, limit=None, detail=None):
    """GET /api/cards/search?q=&limit=[&detail=1]: card names for the editor's autocomplete.

    Returns {"names": [...], "did_you_mean": [...]}. names are the matches
    (cards.search_names: the text at the start of a name, at the start of a
    word, typed words starting the name's words in order as in "llan elv",
    then anywhere). did_you_mean is always there: when the text matches
    fewer than 3 names, up to 3 close spellings that aren't among them
    (cards.close_names: "lightnig bolt" -> Lightning Bolt), else [].
    With detail "1" it also has "cards", one per
    name in the same order: the card as a decklist line's "card" is
    (_card_json: name, mana_cost, cmc, type_line, colors, color_identity,
    roles, img, img_small, Oracle text and face details), pictured by the printing a new line gets, plus
    "default" (that printing, _default_printing; None for basic lands, whose
    lines name no set) and "have" {"owned", "on_the_way"}: copies of any
    printing in the pool (home's, or a visitor's own outside the home:
    _pool_counts), so the suggestions can say what's already there."""
    q = (q or "").strip()
    if len(q) > MAX_SEARCH or _CONTROL_RE.search(q):
        raise ApiError(400, f"The search text must be at most {MAX_SEARCH} characters, with no control characters")
    default, largest = SEARCH_LIMIT
    if limit is None or limit == "":
        n = default
    elif isinstance(limit, int) or (isinstance(limit, str) and re.fullmatch(r"\d{1,3}", limit)):
        n = int(limit)
    else:
        n = 0
    if not 1 <= n <= largest:
        raise ApiError(400, f"limit must be a whole number from 1 to {largest}")
    if detail not in (None, "", "0", "1"):
        raise ApiError(400, "detail must be 1 (or 0)")
    _require_cards()
    names = cards.search_names(q, n) if q else []
    did_you_mean = []
    if q:
        matches = names if n >= DID_YOU_MEAN else cards.search_names(q, DID_YOU_MEAN)
        if len(matches) < DID_YOU_MEAN:
            # close_names gives the matches first, then close spellings (difflib, 20-60 ms).
            did_you_mean = [name for name in cards.close_names(q, len(matches) + DID_YOU_MEAN)
                            if name not in matches][:DID_YOU_MEAN]
    if detail != "1":
        return {"names": names, "did_you_mean": did_you_mean}
    counts = _pool_counts()
    found = []
    for name in names:
        card = cards.card(name)
        chosen = None if decks.is_basic_land(name) else _default_printing(name, counts)
        shown = cards.printing(chosen["set"], chosen["number"]) if chosen else None
        have = {"owned": 0, "on_the_way": 0}
        for set_code, number in card["printings"]:
            for finish in LINE_FINISHES:
                for key, qty in (counts.get((set_code, number, finish)) or {}).items():
                    have[key] += qty
        found.append(dict(_card_json(card, shown or _shown_printing(card)), default=chosen, have=have))
    return {"names": names, "did_you_mean": did_you_mean, "cards": found}


def image_file(set_code, number, size):
    """GET /img/<set>/<number>/<size>: the local path of a printing's image,
    downloaded from Scryfall the first time (size one of cards.IMAGE_SIZES:
    small, normal, large, art_crop, and the -back ones). ApiError 404 for a
    malformed or unknown printing or size, or one Scryfall has no image for
    (its own 404 included); 503 when the download fails (Scryfall's other
    errors and the network's); 500 when the PC can't save it."""
    if size not in cards.IMAGE_SIZES:
        raise ApiError(404, f"No image size {size!r}; use {' or '.join(cards.IMAGE_SIZES)}")
    if not (isinstance(set_code, str) and SET_RE.fullmatch(set_code)):
        raise ApiError(404, "No such printing: set codes are 2-8 lowercase letters and digits")
    if not (isinstance(number, str) and NUMBER_RE.fullmatch(number)):
        raise ApiError(404, "No such printing: bad collector number")
    _require_cards()
    key = (set_code, number, size)
    with _missing_lock:
        said = _missing_images.get(key)
        if said is not None and time.monotonic() - said > MISSING_IMAGE_SECONDS:
            del _missing_images[key]
            said = None
    if said is not None:
        raise ApiError(404, f"Scryfall has no {size} image of {set_code} {number}")
    try:
        path = cards.image_path(set_code, number, size)
    except KeyError:
        raise ApiError(404, f"No printing {set_code} {number}") from None
    except urllib.error.HTTPError as e:
        # An OSError whose filename is the URL: Scryfall's answer, not the PC's disk. A 404 is an image
        # Scryfall doesn't have (an art crop of a card with none), remembered for a while so each page
        # doesn't ask again; anything else is the network's. The answer's body is closed either way.
        code, words = e.code, _public(e)
        e.close()
        if code == 404:
            with _missing_lock:
                if len(_missing_images) >= MAX_MISSING_IMAGES:
                    _missing_images.clear()
                _missing_images[key] = time.monotonic()
            raise ApiError(404, f"Scryfall has no {size} image of {set_code} {number}") from None
        raise ApiError(503, f"Couldn't download the image from Scryfall: {words}") from None
    except urllib.error.URLError as e:
        raise ApiError(503, f"Couldn't download the image from Scryfall: {_public(e)}") from None
    except OSError as e:
        if e.filename:          # the image cache on the PC, not the network
            common._log(f"Can't save {set_code} {number} in the image cache: {type(e).__name__}: {e}")
            raise ApiError(500, "The image couldn't be saved on the PC (the server log says why)") from None
        raise ApiError(503, f"Couldn't download the image from Scryfall: {_public(e)}") from None
    except cards.NETWORK_ERRORS as e:
        raise ApiError(503, f"Couldn't download the image from Scryfall: {_public(e)}") from None
    if path is None:
        raise ApiError(404, f"Scryfall has no {size} image of {set_code} {number}")
    return path
