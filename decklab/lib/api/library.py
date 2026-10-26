"""The deck library by id: checking a deck id, finding its summary (a
pairing's halves in either order), reading the card pool with a warning
instead of an error, and _deck_sections, the summary and decklist that the
deck page, practice hands and matchups all start from.

The shelf's extras (shelf_extras for GET /api/decks; _deck_sections and
edited_at for GET /api/deck): each summary's "cover" (deck_cover: the card whose art stands
for the deck, its "Cover card" header line or the automatic one), "colors"
(deck_colors: its colour identity, WUBRG order; None when no card in it could
be read), "revision" (the deck text's revision, 0 when unknown: what
POST /api/deck/cover's "expect" takes) and "edited" (when
its text was last edited, inventory.deck_edited: ISO 8601 in UTC to the
second, or None).
"""
import csv
import traceback
from datetime import timezone

from decklab.lib import cards, decks, inventory, pool, spaces
from decklab.lib.decks.identity import COLOR_ORDER, deck_colors

from . import common, guard
from .carddata import _require_cards
from .common import _CONTROL_RE, ApiError, _public, _scrub, _strip_paths

VERSIONS = ("target", "owned")
DECK_KINDS = ("casual", "commander", "product", "pairing")


def check_deck_id(deck_id):
    """Raise ApiError 400 unless deck_id looks like an id list_decks() gives:
    casual/<file>, commander/<file>, product/<file>[/<deck>],
    pairing/<half>+<half>, or a person's <space>/<casual|commander>/<file>
    (lib/spaces.py) whose space config.json lists. Whether the deck exists
    is decks.load_deck's job. A well-formed id in a space config.json doesn't
    list is that space's 400 only to a script naming nobody; anyone else gets
    the missing deck's 404 (guard.no_deck), as for a hidden space's deck, so
    the answer doesn't tell which spaces exist (E10-S38)."""
    if not isinstance(deck_id, str) or not 3 <= len(deck_id) <= 200:
        raise ApiError(400, "Bad deck id")
    try:
        space, kind, rest = spaces.split_deck_id(deck_id)
    except ValueError:
        raise ApiError(400, f"Bad deck id {deck_id!r}") from None
    _check_parts(deck_id, kind, rest)
    if space != spaces.HOME and not spaces.exists(space):
        if guard.script():
            raise ApiError(400, f"Bad deck id {deck_id!r}: there's no space {space!r}")
        raise guard.no_deck(deck_id)
    return deck_id


def _check_parts(deck_id, kind, rest):
    """check_deck_id's shape checks of an id's kind and file parts (ApiError 400)."""
    parts = rest.split("/")
    if kind not in DECK_KINDS or len(parts) > (2 if kind == "product" else 1):
        raise ApiError(400, f"Bad deck id {deck_id!r}")
    for part in parts:
        # A hand-named deck file (Gruul_Ramp.md) keeps its own name, so allow
        # more than slugs, but never an empty part, "..", a backslash, a
        # drive or stream colon, or a control character.
        if not part or part.startswith(".") or "\\" in part or ":" in part or _CONTROL_RE.search(part):
            raise ApiError(400, f"Bad deck id {deck_id!r}")


def _sort_halves(pair_id):
    return sorted(pair_id.split("/", 1)[1].split("+"))


def _find_summary(deck_id):
    """The library summary of a deck id (a pairing's halves in either order),
    or ApiError 404; for a product deck or pairing, the inventory's own
    refusal (common.state_errors(): 503 while the database can't be reached)
    when it can't be read. A deck the viewer may not see (guard.sees_deck)
    gets exactly the 404 a missing one does, "No deck <id>"."""
    summary = decks.find_summary(deck_id)
    if summary is None:
        if deck_id.startswith(("product/", "pairing/")):
            with common.state_errors():
                inventory.current()
        raise guard.no_deck(deck_id)
    guard.require_sees_deck(summary, deck_id=deck_id)
    return summary


def viewer_decks_revision(summaries, snapshot=None):
    """decks_revision for one viewer (GET /api/decks and GET /api/matchups, which the
    Matchups page compares): a sha256 over the ids, titles and text sha256s of the
    library summaries it may see (guard.visible_decks, already filtered), so a save of a
    deck it can't see doesn't move it. snapshot is the inventory's (current() by default)."""
    import hashlib
    import json
    snapshot = inventory.current() if snapshot is None else snapshot
    parts = []
    for summary in summaries:
        stored = snapshot.deck(summary["id"])
        parts.append([summary["id"], summary.get("title"), stored.sha256 if stored is not None else None])
    parts.sort(key=lambda part: part[0])
    text = json.dumps(parts, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_pool(warnings, space=spaces.HOME):
    """pool.load_pool(space), or None with a warning when the pool can't be read."""
    try:
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
    except (ValueError, OSError, csv.Error, spaces.SpaceNotFound) as e:   # e.g. a bad row in collection.csv
        common._log(f"The card pool can't be read: {type(e).__name__}: {e}")
        if space == spaces.HOME and not guard.sees_home_records():
            warnings.append("Owned vs needed can't be worked out: the collection couldn't be read.")
            return None
        hint = " (is it open in Excel?)" if isinstance(e, PermissionError) else ""
        warnings.append(f"Owned vs needed can't be worked out: {_public(e)}{hint}")
        return None
    warnings.extend(_scrub(visible_warnings(p)))
    return p


def visible_warnings(p, profile=False):
    """The pool p's warnings this request (or profile) may see (E10-S29): one about a deck
    (pool.Pool.warning_decks) only when it may see that deck (guard.sees_deck), and the rest of
    home's pool, about its orders, products and status lines, only when it may see home's
    records (guard.sees_home_records). Whether it sees the pool at all is the caller's
    (guard.sees_inventory)."""
    sees = guard.deck_reader(profile)
    about = getattr(p, "warning_decks", None) or {}
    records = getattr(p, "space", spaces.HOME) != spaces.HOME or guard.sees_home_records(profile)
    return [text for text in p.warnings if (sees(about[text]) if text in about else records)]


def visible_place(where, sees=None, records=None):
    """True when this request may be told a pool's place (an unknown card's "where": a deck id,
    a collection's file, or one of home's order or product files): a deck only when it may see
    it (sees: guard.deck_reader()), home's orders and products only when it sees home's
    records (records: guard.sees_home_records()), a collection's own file always (the caller
    has asked whether it sees that collection)."""
    from decklab.lib.inventory import paths
    where = str(where)
    if where.startswith((paths.ORDERS + "/", paths.PRODUCTS + "/")):
        return guard.sees_home_records() if records is None else records
    try:
        spaces.split_deck_id(where)
    except ValueError:
        return True
    return (guard.deck_reader() if sees is None else sees)(where)


def visible_unresolved(unresolved, sees=None, records=None):
    """{name: [places]} of a pool's unknown card names (pool.Pool.unresolved), keeping only
    the places this request may be told (visible_place) and the names left with any, so no
    card of a deck it can't see is named (E10-S29)."""
    sees = guard.deck_reader() if sees is None else sees
    records = guard.sees_home_records() if records is None else records
    out = {}
    for name, places in unresolved.items():
        shown = sorted(str(w) for w in places if visible_place(w, sees, records))
        if shown:
            out[name] = shown
    return out


def _scrub_summary(summary):
    """A library summary with no absolute path in it: "source" is relative to
    the repo for files inside it (always, in normal use), and error is str(e)."""
    for key in ("source", "error"):
        if isinstance(summary.get(key), str):
            summary[key] = _strip_paths(summary[key])
    return summary


def _named_by_id(summary):
    """A library summary as a page gets it (in place; returns it): a deck
    file's "source" is its deck id, since the pages name a deck by its id,
    never a file (phase 4: decks live in the inventory; the phase 4 design's
    R8). A product deck's stays the products' file. decks.list_decks gives
    the id already (phase 5); this keeps a summary from elsewhere the same."""
    try:
        deck_file = spaces.split_deck_id(summary["id"])[1] in decks.KINDS
    except (KeyError, TypeError, ValueError):
        deck_file = False
    if deck_file:
        summary["source"] = summary["id"]
    return summary


def _half_title(summary):
    """"Cats" for "Cats (Foundations Beginner Box)"."""
    box = inventory.current().product(decks.BEGINNER_BOX)
    product = box.name if box is not None and box.name is not None else ""
    return summary["title"].removesuffix(f" ({product})")


def _deck_sections(deck_id, version):
    """(library summary, decklist) for a deck id and version, as deck_view and
    goldfish both need them: ApiError 400 for a bad id or version, 404 for a
    deck or version that doesn't exist, 500 for a file that can't be read, 503
    until the card data is ready. The summary's id is the library's (a
    pairing's halves in its order); the decklist is decks.load_deck()'s."""
    check_deck_id(deck_id)
    if version not in VERSIONS:
        raise ApiError(400, f"version must be one of: {', '.join(VERSIONS)}")
    _require_cards()
    summary = _scrub_summary(dict(_find_summary(deck_id)))
    if summary.get("error"):
        raise ApiError(500, f"{summary['source']} can't be read: {summary['error']}")
    if version not in summary["versions"]:
        raise ApiError(404, f"{summary['title']} has no {version} list")
    try:
        sections = decks.load_deck(summary["id"], version)
    except decks.DeckNotFound as e:
        raise ApiError(404, _public(e)) from None
    except (decks.DeckFileError, OSError) as e:
        raise ApiError(500, f"{summary['source']} can't be read: {_public(e)}") from None
    try:
        target = sections if version == "target" else decks.load_deck(summary["id"], "target")
    except (decks.DeckNotFound, decks.DeckFileError, OSError):
        target = None
    _shelf(summary, target)
    return summary, sections


def is_half(summary):
    """Is this a Beginner Box half? One is only ever played shuffled with
    another (a pairing), so it gets no practice games of its own."""
    return summary["id"].startswith(f"product/{decks.BEGINNER_BOX}/")


# ---- the shelf: cover cards, colours, revisions, when last edited

def _card_of(name):
    exact = name if decks.is_basic_land(name) else cards.resolve(name)
    return cards.card(exact) if exact else None


def _front_types(card):
    return card["type_line"].split(" // ")[0].split(" — ")[0]


def _is_land(name):
    card = _card_of(name)
    if card is None:
        return decks.is_basic_land(name)
    return "Land" in _front_types(card)


def _is_creature(name):
    card = _card_of(name)
    return card is not None and "Creature" in _front_types(card)


def _cover_json(name, set_code, number, auto, written=None, problem=None):
    """{"name", "set", "number", "auto", "shown_set", "shown_number", "img", "img_small", "art"}
    for a cover card. "set" and "number" are the printing the Cover card line (or, for an
    automatic cover, the list's line) names, None when it names none or names one that isn't
    this card's: what a save would write back. "shown_set" and "shown_number" are the printing
    whose pictures are shown (that one, else the one the deck page would show), and img,
    img_small and art its /img/ addresses (None when it has no picture). "written" (the Cover
    card line's value when it couldn't be used) and "problem" (why) when the line was set aside."""
    from .card_lookup import _shown_printing, image_url
    card = cards.card(name)
    p = None
    if set_code and number:
        p = cards.printing(set_code, number)
        if p is not None and (cards.printing_card(set_code, number) or {}).get("name") != name:
            p = None
    own = p is not None
    if p is None and card is not None:
        p = _shown_printing(card, (set_code,) if set_code else ())
    has = bool(p and p.get("image_normal"))
    s, n = (p["set"], p["collector_number"]) if p else (None, None)
    out = {"name": name, "set": set_code if own else None, "number": number if own else None, "auto": auto,
           "shown_set": s, "shown_number": n,
           "img": image_url(s, n, "normal") if has else None,
           "img_small": image_url(s, n, "small") if p and p.get("image_small") else None,
           "art": image_url(s, n, "art_crop") if has else None}
    if problem:
        out.update(written=written, problem=problem)
    return out


def auto_cover(sections, written=None, problem=None):
    """The automatic cover of a list ({section: [DeckLine]}), as _cover_json gives it, or None
    for an empty list or one with no card Scryfall knows."""
    line = decks.auto_cover_line(sections or {}, _is_land, _is_creature)
    exact = None
    if line is not None:
        exact = cards.resolve(line.name)
        if exact is None and decks.is_basic_land(line.name) and cards.card(line.name):
            exact = line.name
    if exact is None:
        return None
    return _cover_json(exact, line.set, line.number, True, written, problem)


def deck_cover(summary, sections):
    """The deck's cover card (see the module docstring and _cover_json), from its Cover card
    line ("cover_card" in a deck file's summary) when that names a Scryfall card, else automatic
    (auto_cover of sections, the Planned list); None for an empty list or one with no card
    Scryfall knows. A line that can't be used falls back to automatic with "written" and
    "problem" saying why."""
    written, problem = (summary.get("cover_card") or "").strip(), None
    if written:
        cover = decks.parse_cover(written)
        exact = cards.resolve(cover["name"]) if cover else None
        if cover is None:
            problem = "The Cover card line isn't a card name with an optional (SET) and number"
        elif exact is None:
            problem = f"{cover['name']} isn't a Scryfall card name"
        else:
            return _cover_json(exact, cover["set"], cover["number"], False)
    return auto_cover(sections, written if problem else None, problem)


def _revision_of(deck_id):
    """The deck text's revision in the inventory snapshot (0: unknown, the files backend; or not a
    deck text: a product deck or pairing)."""
    try:
        found = inventory.current().deck(deck_id)
    except Exception:           # a read the page goes on without
        return 0
    return found.revision if found is not None else 0


def _shelf(summary, sections):
    """Set a summary's cover, colors and revision (in place)."""
    try:
        summary["cover"] = deck_cover(summary, sections)
        summary["colors"] = deck_colors(sections or {})
    except Exception:           # the shelf still shows; the log has the details
        common._log(f"The cover of {summary.get('id')} couldn't be worked out:\n" + traceback.format_exc())
        summary["cover"], summary["colors"] = None, None
    summary["revision"] = _revision_of(summary["id"])


def _utc(at):
    """A datetime as ISO 8601 in UTC to the second ("2026-10-12T09:06:52+00:00"), so the page can
    compare any two as strings; None for None."""
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return at.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _edited_decks():
    """The latest deck-edit dates, or no dates when that optional read fails."""
    try:
        return inventory.deck_edited()
    except Exception:           # the page shows no date; "Recently changed" falls back to name order
        common._log("When the decks were last edited couldn't be read:\n" + traceback.format_exc())
        return {}


def edited_at(deck_id):
    """One deck's latest edit as ISO UTC seconds from the inventory metadata, or None."""
    return _utc(_edited_decks().get(deck_id))


def shelf_extras(summaries):
    """Add cover, colors, revision and edited to each library summary (in place): GET
    /api/decks. Each deck's Planned list is read once (a product's from one read of the
    products); one that can't be read gets no cover and no colours."""
    products = None
    edited = _edited_decks()
    for summary in summaries:
        sections = None
        if not summary.get("error") and "target" in (summary.get("versions") or []):
            try:
                if summary["id"].startswith("product/"):
                    if products is None:
                        products = {d["id"]: d.get("sections") for d in decks._product_decks()}
                    sections = products.get(summary["id"])
                else:
                    sections = decks.load_deck(summary["id"], "target")
            except (decks.DeckNotFound, decks.DeckFileError, OSError):
                sections = None
        _shelf(summary, sections)
        summary["edited"] = _utc(edited.get(summary["id"]))
    return summaries
