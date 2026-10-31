"""The deck pages: GET /api/decks (decks_index) and GET /api/deck
(deck_view: the decklist with card data, its stats from lib/stats/,
imported when first needed, owned vs needed, and the practice and matchup
parts).
"""
import importlib
import json
import re
import traceback
from collections import Counter

from decklab.lib import accessories, decks, inventory, pool, spaces, tokens
from decklab.lib.inventory import paths as inventory_paths
from decklab.lib.state import StateError

from . import common, guard, near_combos
from .opponents import add_usual_opponents, usual_opponent_ids, usual_opponents
from .common import ApiError
from .assembly import TOKEN_FAILED, _deck_tokens, held_tokens
from .card_lookup import _line_json, _owned_json
from .carddata import _require_cards
from .commits import _table_json
from .considering import view as considering_view
from .deck_aliases import metadata
from .common import _jsonable, _public, _scrub, _unique
from .forge_runs import _deck_matchups
from .guide import departed_cards, playing_guide
from .library_played import deck_played, played_extras
from .library import (_deck_sections, _half_title, _load_pool, _named_by_id, _scrub_summary, edited_at, shelf_extras,
                      viewer_decks_revision)
from .practice import _deck_practice
from .swaps import view_swaps


def decks_index():
    """GET /api/decks: every deck file and product deck the viewer may see
    (guard.sees_deck: its own space's, with no admin override; a script
    every one), with how many cards each version is missing, and the
    Beginner Box halves for the pairing picker. halves, usual_opponents,
    aliases and decks_revision (library.viewer_decks_revision) are worked
    out over those decks only, so nothing names or counts a hidden one.

    Each summary is decks.list_decks()'s, plus "missing": {version: cards}
    and "on_the_way": {version: copies this deck counts on that haven't
    arrived yet} (both None for a version that can't be counted), and
    "availability_confirmed". A pairing's id is
    "pairing/<half>+<half>", each half the last part of its id. A deck
    file's "source" is its id (library._named_by_id).

    "kit" is the deck's sleeves and deck box in brief (_brief_kit): {"sleeves":
    {"name", "image_url", "state"} or None, "deck_box": the same, "short":
    sleeves missing}. A product deck shows its product's (status.csv's
    columns, when it's owned and kept intact); None when the accessories
    can't be read. A visitor who may not see the deck's owner's accessories
    (guard.sees_kit: User1's decks only User1, "either" decks and products
    every home profile) gets sleeves, deck_box and kit None.

    "tokens" is tokens.brief() of the list that counts ({kinds, none,
    differs, incoming, opponent, reminders}: the names of the tokens with
    nothing owned, only a different card, or only cards on the way, those
    landing only on the opponent's side apart, and of the emblems and
    reminders among them; see _index_tokens), or None
    for an idea deck, a pairing, or when the tokens can't be worked out.

    "cover", "colors", "revision" and "edited" are library.shelf_extras' (the
    cover card, colour identity, the text's revision and when it was last edited),
    "played" library_played.played_extras' (when it was last played at home and its
    games, from the Game log's games the viewer may see; None when they can't be read).

    A built ordinary deck also has "assembled": its saved physical main/sideboard
    counts and the real Planned cards still outside that build (assembly_intent.project).
    A readable ordinary home built deck has "box_check": {checked_on: ISO date or None}
    only for viewers of home's records and inventory. None means no reliable date
    was recorded; it makes no claim about whether the physical box was checked.

    missing, on_the_way, availability_confirmed, assembled and tokens are left out of a
    deck whose space's inventory the visitor may not see (the phase 4
    design's R6d, guard.sees_inventory), and that space's pool isn't read."""
    _require_cards()
    summaries = [dict(summary) for summary in guard.visible_decks(decks.list_decks())]
    opponents = usual_opponent_ids(summaries)
    add_usual_opponents(summaries, opponents)
    warnings = []
    # Each deck is counted in its own space's pool, read once; home's always for those who see it
    # (its warnings show even with no deck to count).
    pools = {spaces.HOME: _load_pool(warnings)} if guard.sees_inventory(spaces.HOME) else {}
    owners = guard.accessory_readers()
    sees = owners is None or bool(owners)
    kits = _index_kits(summaries) if sees else None
    token_briefs = _index_tokens()
    for summary in summaries:
        summary.pop("box_check", None)  # Always project private metadata afresh for this request.
        space = summary.get("space", spaces.HOME)
        if guard.sees_inventory(space):
            if space not in pools:
                pools[space] = _load_pool(warnings, space)
            _index_counts(summary, pools[space], warnings)
            summary["tokens"] = token_briefs(summary)
        shown = sees and guard.sees_kit(summary, owners)
        summary["kit"] = kits(summary) if shown else None
        if not shown:
            guard.hide_kit(summary)
        _named_by_id(_scrub_summary(summary))
        metadata(summary, summary["id"])
    shelf_extras(summaries)
    played_extras(summaries)
    halves = [{"id": s["id"], "title": _half_title(s)} for s in summaries
              if s["id"].startswith(f"product/{decks.BEGINNER_BOX}/") and not s.get("error")]
    return {"decks": summaries, "halves": halves, "warnings": _unique(_scrub(warnings)),
            "decks_revision": viewer_decks_revision(summaries),
            "usual_opponents": {deck_id: ids for deck_id, ids in opponents.items()
                                if deck_id.startswith("pairing/") and ids}}


def _index_counts(summary, p, warnings):
    """Set a library summary's "missing", "on_the_way" and "availability_confirmed" from its
    space's pool p (None when it can't be read: every count None)."""
    missing, waiting, confirmed, intended = {}, {}, {}, None
    for version in summary["versions"]:
        try:
            result = pool.owned_vs_needed(summary["id"], version, pool=p, prices=False) if p else None
        except (decks.DeckNotFound, decks.DeckFileError, OSError) as e:
            warnings.append(f"{inventory_paths.place(summary['source'])}: {_public(e)}")
            result = None
        missing[version] = result["totals"]["missing"] if result else None
        confirmed[version] = bool(result is not None and not result["unresolved"] and not result["warnings"])
        waiting[version] = (sum(qty for r in result["rows"] for _, qty in pool.row_labels(r)["on_the_way"])
                            if result else None)
        if version == "target":
            intended = result
    summary["missing"] = missing
    summary["on_the_way"] = waiting
    summary["availability_confirmed"] = confirmed
    assembled = _assembled_view(summary, p, warnings, result=intended, check_date=True)
    if assembled is not None:
        summary["assembled"] = assembled


def _assembled_view(summary, p, warnings, *, deck=None, result=None, check_date=False):
    """Inventory-only physical build and retained Planned intent; optional when unreadable."""
    if summary.get("status") != "built" or summary.get("error") or summary["id"].startswith(("product/", "pairing/")):
        return None
    try:
        if deck is None:
            from decklab.lib.inventory.ops_decks import parsed_deck
            record = inventory.current().deck(summary["id"])
            deck = parsed_deck(record) if record is not None else None
        # Reuse this already parsed request-snapshot record; public inventory or
        # public decks alone never publish home's historical physical-check date.
        if check_date and deck is not None and deck.space == spaces.HOME and deck.kind in decks.KINDS \
                and deck.status == "built" and guard.sees_home_records() and guard.sees_inventory(spaces.HOME):
            from decklab.lib.decks import boxcheck
            summary["box_check"] = {"checked_on": boxcheck.checked_on(deck)}
        from .assembly_intent import project
        return project(deck, p, result)
    except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError) as error:
        warnings.append(f"The physical build and remaining intended cards couldn't be checked: {_public(error)}")
        return None


_NO_KIT = {"sleeves": None, "deck_box": None, "short": 0}


def _brief(ref):
    return None if ref is None else {"name": ref["label"], "image_url": ref["image_url"], "state": ref["state"]}


def _brief_kit(kit):
    """A library card's part of accessories.kit()."""
    return {"sleeves": _brief(kit["sleeves"]), "deck_box": _brief(kit["deck_box"]), "short": kit["short"]}


def _index_kits(summaries):
    """kit(summary) -> decks_index's "kit" for that summary. The inventory,
    its holders and status.csv are read once; accessories.kit runs only for
    a summary that records something (a deck file's lines, or its owned
    intact product's columns), once per product."""
    try:
        inv = accessories.read()
        usage = accessories.holders(inv)
        statuses = pool.read_status([])
    except Exception:           # the library still shows; the log has the details
        common._log("The accessories couldn't be read for the library:\n" + traceback.format_exc())
        return lambda summary: None
    cache = {}

    def kits(summary):
        # A person's decks keep no accessories (they're home's).
        if summary.get("error") or summary["id"].startswith("pairing/") \
                or summary.get("space", spaces.HOME) != spaces.HOME:
            return dict(_NO_KIT)
        holder = accessories._holder_id(summary["id"])
        if holder.startswith("product/"):
            status = statuses.get(holder.split("/", 1)[1] + ".csv")
            if status is None or not (status.status == "owned" and status.intact) \
                    or not (status.sleeves or status.deck_box):
                return dict(_NO_KIT)
        elif not ((summary.get("sleeves") or "").strip() or (summary.get("deck_box") or "").strip()):
            return dict(_NO_KIT)
        if holder not in cache:
            try:
                cache[holder] = _brief_kit(accessories.kit(holder, inv=inv, usage=usage))
            except Exception:   # this card shows no kit; the log has the details
                common._log(f"The accessories of {holder} couldn't be worked out:\n" + traceback.format_exc())
                cache[holder] = None
        return cache[holder]
    return kits


def _index_tokens():
    """brief(summary) -> decks_index's "tokens" for that summary. Each
    space's tokens.csv (and home's incoming token orders) is read once, and
    a deck is matched against its own space's (tokens.for_space). A deck file counts its built
    version when it's built and its target list when it's being built; a
    product deck its own list. Idea decks, pairings and summaries with an
    error get None, and so does a deck whose tokens can't be worked out (the
    first such failure is logged) and every deck while the card index is
    missing or being rebuilt."""
    inventories = {}
    unavailable, logged = [], []

    def inventory(space):
        if space not in inventories:
            try:
                inv, inc = _token_pool(space)
                inventories[space] = (inv, inc, held_tokens(inv, space))
            except Exception:   # the library still shows; the log has the details
                whose = "" if space == spaces.HOME else f" of {space}'s space"
                common._log(f"The tokens{whose} couldn't be read for the library:\n" + traceback.format_exc())
                inventories[space] = None
        return inventories[space]

    # Read lazily, a space at a time: decks_index asks only for the spaces the viewer may see (R6d),
    # and a space whose tokens can't be read costs only its own decks their chips.
    def brief(summary):
        deck_id = summary["id"]
        if unavailable or summary.get("error") or deck_id.startswith("pairing/"):
            return None
        found = inventory(summary.get("space", spaces.HOME))
        if found is None:
            return None
        inv, inc, holds = found
        if deck_id.startswith("product/") or summary.get("status") == "building":
            version = "target"
        elif summary.get("status") == "built":
            version = None
        else:
            return None
        try:
            sections = None
            if summary.get("status") == "built" and not deck_id.startswith("product/"):
                from decklab.lib.decks import assembled
                from decklab.lib.inventory.ops_decks import parsed_deck
                from decklab.lib import inventory as inventory_store
                parsed = parsed_deck(inventory_store.current().deck(deck_id))
                if parsed is not None and assembled.get(parsed):
                    sections = assembled.sections(parsed)
                    version = assembled.version(parsed)
            if sections is None:
                version = version or pool._built_version(summary, [])
                sections = decks.load_deck(deck_id, version)
            held = tokens.reserve.held_elsewhere(holds, deck_id)
            result = (tokens.cached_deck_tokens(deck_id, version, sections, inv, inc, held) if held
                      else tokens.cached_deck_tokens(deck_id, version, sections, inv, inc))
        except RuntimeError:    # the card index is missing or being rebuilt
            unavailable.append(deck_id)
            return None
        except Exception:       # this card shows no tokens; the log has the details
            if not logged:
                common._log(f"The tokens of {deck_id} couldn't be worked out for the library:\n"
                            + traceback.format_exc())
            logged.append(deck_id)
            return None
        return tokens.brief(result)
    return brief


# A token cards row the read leaves out, as files._left_out names it (E11-S12: by the listed row before it).
_TOKEN_LINE = re.compile(r"^A row (after row \d+|before row 1) of (?:the home|[a-z0-9-]+'s) token cards:")


def _view_tokens(summary, version, sections, info):
    """deck_view's "tokens": tokens.deck_tokens for the version shown (see
    assembly._deck_tokens for {"unavailable"} and {"error"}); None for a
    pairing. Rows of tokens.csv that can't be read go in info, never in
    warnings: a missing or different token isn't a problem at home."""
    if summary["id"].startswith("pairing/"):
        return None
    try:
        inv, inc = _token_pool(summary.get("space", spaces.HOME))
    except Exception:           # the page still shows the deck; the log has the details
        common._log("The token inventory couldn't be read:\n" + traceback.format_exc())
        return {"error": TOKEN_FAILED}
    for problem in inv.problems:
        found = _TOKEN_LINE.match(problem)
        info.append(f"A token cards row {found[1]} couldn't be read; see the Tokens page" if found
                    else _scrub([problem])[0])
    holds = held_tokens(inv, summary.get("space", spaces.HOME))
    result = _deck_tokens(summary["id"], version, sections, inv, inc,
                          tokens.reserve.held_elsewhere(holds, summary["id"]))
    result = _with_shared(_with_examples(result), summary, inv, inc, holds)
    result = _with_dice(result, summary.get("space", spaces.HOME))
    from decklab.lib.tokens import products as product_tokens
    product = product_tokens.for_route(summary["id"]) if guard.sees_home_records() \
        and summary["id"].startswith("product/") else None
    if isinstance(result, dict) and "needs" in result and (product is not None or
            summary.get("status") == "built" and not summary["id"].startswith("product/")):
        packed = _packed(summary, inv, holds, result, product=product)
        if product is not None or packed["written"] or packed["choices"]:
            result = dict(result, packed=packed)
    return result


def _with_dice(result, space):
    """result with whether the space's owned dice and counters cover its counter needs (E7-S24:
    tokens.dice_cover, approximate). Only the Tokens part's readers (the space's inventory
    readers) get here, so the owned counts are told only to them."""
    if not isinstance(result, dict) or not isinstance(result.get("counters"), dict):
        return result
    from decklab.lib import inventory as inventory_store
    from decklab.lib.tokens import dice_cover
    snapshot = inventory_store.current()
    rows = [row.as_dict() for row in snapshot.dice_set(space).rows] if snapshot.dice_set(space).error is None else []
    return dict(result, counters=dice_cover.cover(result["counters"], rows, snapshot.dice_ready))


def _packed(summary, inv, holds, result, product=None):
    """A built deck's packed token cards, for its Tokens part: {"written": whether its text has a
    Token cards line, "lines": [{"text", "quantity", "rows": [{row, front, back, quantity}]}]
    (the line's cards, by the rows that hold them; rows [] for a line no token card matches),
    "choices": [{row, front, back, set, number, quantity, free, packed}] (the token cards the
    sheet offers: those its needs could grab, stand in with or find in use, and those it packs;
    free is what other built decks leave of the row), "expect" (the deck text's sha256) and
    "tokens_sha256" (the token cards' list the rows index), for POST /api/deck/token-cards;
    "error" when the line can't be read}."""
    from decklab.lib.inventory.ops_decks import parsed_deck
    snapshot = inventory.current()
    holder = product["holder"] if product is not None else summary["id"]
    base = {"tokens_sha256": inv.sha256}
    if product is not None:
        from .product_tokens import status_sha256
        receipt = status_sha256(snapshot)
        base.update(expect=receipt, product={"stem": product["product"].stem, "status_sha256": receipt},
                    editable=guard.allowed(guard.viewer(), "products.edit"))
        lines, written = product["lines"], product["written"]
        if product["error"]:
            return {**base, "written": written, "lines": [], "choices": [], "editable": False,
                    "error": product["error"]}
    else:
        stored = snapshot.deck(summary["id"])
        base["expect"] = stored.sha256 if stored is not None else None
        try:
            parsed = parsed_deck(stored)
            lines = decks.token_cards(parsed) if parsed is not None else []
            written = parsed is not None and decks.has_token_cards(parsed)
        except decks.DeckFileError as e:
            return {**base, "written": True, "lines": [], "choices": [], "error": _scrub([str(e)])[0]}
    hold = holds.get(holder, {"rows": {}, "unmatched": []})
    out = []
    for line in lines:
        rows = [i for i in sorted(hold["rows"]) if tokens.reserve.matches(line, inv.rows[i])]
        out.append({"text": line.text(), "quantity": line.quantity,
                    "rows": [{"row": i, "front": inv.rows[i]["front"], "back": inv.rows[i]["back"],
                              "quantity": hold["rows"][i]} for i in rows]})
    elsewhere = tokens.reserve.held_elsewhere(holds, holder)
    # A product shares one box across all its generated deck routes, so its picker
    # may choose any owned token row, even when this subdeck does not make that token.
    offered = set(range(len(inv.rows))) if product is not None else set(hold["rows"])
    for need in result.get("needs", []):
        offered.update(c["row"] for c in need.get("cards", []))
        offered.update(c["row"] for c in need.get("stand_ins", []) if not c.get("close"))
        offered.update(c["row"] for c in need.get("in_use", []))
    choices = []
    for i in sorted(offered):
        if not 0 <= i < len(inv.rows):
            continue
        row, qty = inv.rows[i], int(inv.rows[i]["quantity"])
        choices.append({"row": i, "front": row["front"], "back": row["back"], "set": row["set"],
                        "number": row["front_collector_number"], "quantity": qty,
                        "free": max(qty - sum(h["quantity"] for h in elsewhere.get(i, [])), 0),
                        "packed": hold["rows"].get(i, 0)})
    return {**base, "written": written, "lines": out, "choices": choices}


def _with_shared(result, summary, inv, inc, holds=None):
    """result with "shared" on each card to grab: the other built decks that want that token
    card (tokens.shared_rows), when they want more than it has; [] otherwise
    (and result as it is when no card has any). The page says so beside the card. Decks the
    viewer may not see leave the card's "shared" empty, as the Tokens page does. A copy; the
    cached result is never changed."""
    needs = result.get("needs") if isinstance(result, dict) else None
    if not needs or not any(need.get("cards") for need in needs):
        return result
    space = summary.get("space", spaces.HOME)
    try:
        holds = tokens.reserve.holds(inv, space) if holds is None else holds
        shared = tokens.shared_rows(inv, tokens.row_uses(inv, inc, [], space), tokens.built_ids(space), holds)
    except Exception:           # the deck's tokens still show; the log has the details
        common._log("The shared token cards couldn't be worked out:\n" + traceback.format_exc())
        return result
    from .tokens import _seen_holders
    sees = guard.deck_reader()

    def others(row):
        holders = _seen_holders(shared.get(row, []), sees)
        from decklab.lib.tokens.products import holder_id
        own = holder_id(summary["id"])
        return [h for h in holders if h["deck"] != own] if holders else []
    if not any(others(card["row"]) for need in needs for card in need.get("cards") or []):
        return result
    out = dict(result)
    out["needs"] = [dict(need, cards=[dict(card, shared=others(card["row"])) for card in need.get("cards") or []])
                    for need in needs]
    return out


def _token_pool(space):
    """Pending token orders stay home's records, even beside a public collection/deck."""
    if space == spaces.HOME and not guard.sees_home_records():
        return tokens.read(space=space), []
    inv, incoming, _ = tokens.for_space(space)
    return inv, incoming


def _with_examples(result):
    """result with an "example" picture on each need that has no "image" of its own (a token
    the card index has no picture for, or a name it doesn't know): example art of a token with
    that name (api/tokens._example_image, the Tokens page's), which the page labels as such.
    A copy: the cached result itself is never changed."""
    needs = result.get("needs") if isinstance(result, dict) else None
    if not needs or all(need.get("image") for need in needs):
        return result
    from .tokens import _example_image
    out = dict(result)
    out["needs"] = [need if need.get("image") else dict(need, example=_example_image(need["name"], need.get("pt") or ""))
                    for need in needs]
    return out


def _view_kit(summary, sections, warnings):
    """(kit, holder_sha256) for deck_view: accessories.kit() with the need
    counted from the built version for a built deck file (and a product's
    whole list), else from the version shown ("would need"); and the sha256
    of the file an assign must still match (the deck file, or a product's
    status.csv as rendered from the inventory; None for a pairing). kit is None when it can't be worked
    out, and for a deck in a person's space (accessories are home's), with
    holder_sha None."""
    deck_id = summary["id"]
    holder_sha = None
    if summary.get("space", spaces.HOME) != spaces.HOME:
        return None, None
    try:
        if deck_id.startswith("product/"):
            holder_sha = accessories.status_sha256()        # status.csv as rendered from the inventory
        elif not deck_id.startswith("pairing/"):
            deck = inventory.current().deck(deck_id)        # the deck's text as stored: kit.set's token
            holder_sha = deck.sha256 if deck is not None and deck.error is None else None
    except (decks.DeckNotFound, OSError, StateError):
        pass
    built = summary.get("status") == "built" and not deck_id.startswith(("product/", "pairing/"))
    try:
        from .accessories import read_kit
        kit = read_kit(deck_id, None if built else sections)
        kit["editable"] = guard.sees_kit(summary, guard.accessory_owners())
    except Exception:           # the page still shows the deck; the log has the details
        common._log("The deck's accessories couldn't be worked out:\n" + traceback.format_exc())
        warnings.append("The deck's sleeves and deck box couldn't be checked (the server log says why)")
        return None, holder_sha
    return kit, holder_sha


def _deck_stats(sections, kind, warnings):
    """decklab.lib.stats.deck_stats(sections, kind), or None with a warning."""
    try:
        stats = importlib.import_module("decklab.lib.stats")
        result = _jsonable(stats.deck_stats(sections, kind))
        json.dumps(result, allow_nan=False)       # fail here, not while sending
        return result
    except Exception:           # the page still shows the deck; the log has the details
        common._log("Deck stats failed:\n" + traceback.format_exc())
        warnings.append("The deck stats couldn't be worked out (the server log says why)")
        return None


# The parts of deck_view's answer a page may ask to leave out (GET /api/deck's omit=, comma separated): the
# deck page asks for its matchups, the answer's slowest part, only when its Matchups tab opens.
OMITTABLE = frozenset({"matchups"})


def parse_omit(text):
    """omit= as a set of deck_view's parts: ApiError 400 for one it can't leave out."""
    parts = {p.strip() for p in (text or "").split(",") if p.strip()}
    unknown = parts - OMITTABLE
    if unknown:
        raise ApiError(400, f"omit can only name: {', '.join(sorted(OMITTABLE))}")
    return frozenset(parts)


def deck_view(deck_id, version="target", omit=()):
    """GET /api/deck?id=<deck id>&version=target|owned[&omit=matchups]: the decklist with card
    data and images, its stats, and owned vs needed.

    omit names parts to leave out (OMITTABLE): with "matchups" the answer has
    no "matchups" key at all (not None, which means they couldn't be loaded),
    and _deck_matchups isn't run.

    Returns summary (as in decks_index, without "missing" and with the full
    kit: accessories.kit(), see _view_kit, and holder_sha256), version, versions,
    sections {section: [line]} (only those present; each line qty, name, set,
    number, finish and card, None for a name that isn't a Scryfall card),
    stats (None if they couldn't be worked out), owned (pool.owned_vs_needed
    with prices, as JSON: pairs such as (source, copies) become 2-item lists;
    each row also has "labels": {"on_the_way": [[source,
    copies]], "in_use": [[deck, copies]], "incoming_sources": [{source,
    quantity, order_id, component_id, product_id, status}]}. The pairs match
    the deck file's Notes cell; incoming_sources names those same copies'
    order/product and ordered/preordered status (ids None for unrecorded
    sources). owned is None if the pool can't be read. Also practice and warnings.

    guide is the existing gameplay prose from the deck file's Notes, grouped
    by topic, with changed_on when a list edit marked that prose stale, and departed
    (guide.departed_cards: the cards it names that former revisions held and today's lists
    don't, for the deck's own space only, else None). It is None for products/pairings,
    and has empty sections when no guide is written.

    swaps is what the saved Play-now list swaps for the Planned list (api/swaps.py view_swaps:
    {"swaps": [{"for", "out_qty", "using", "note", "note_line", "card"}], "unpaired"}), each
    paired with its Substitutes line; None for a deck with no Play-now list, a product or a
    pairing. It comes from the lists and the prose alone, so every viewer of the deck gets it.

    practice is what goldfish() would answer when that needs no run: a saved
    result ({"status": "done", "result"}) or a deck too small to deal from
    ({"status": "error", "error"}), so the page shows the practice-hand part
    whole in the same pass and nothing below it moves later. It's None when
    the games haven't been played yet (the page asks goldfish(), which starts
    them) and for a Beginner Box half, which is only played in a pairing.

    The kit's warnings (too few sleeves, a deck box used too often; sleeves
    other decks also use are fine) are added to warnings; info holds what
    can't be checked (free text, not in the accessories list). A visitor who
    may not see the deck's owner's accessories (guard.sees_kit) gets none of this:
    the summary's sleeves, deck_box, kit and holder_sha256 are None.

    table is the "this table is out of date" note for a deck file (see
    _table_json; None for products and pairings), so the page can offer
    update_tables() for it.

    matchups is this list's part of the Forge matchups (_deck_matchups):
    {"ai": what Forge's AI can't play in it (forge.list_ai: by its card
    scripts, and the cards never cast in all this list's saved games),
    "results": its saved results with this list first, "running": runs of
    it waiting or playing, "forge": forge.status(), "cards": what each card
    did in all this list's saved games with the card log (forge.list_cards;
    None without any, or when it fails on its own)}. It's None for a Beginner Box half, or when the matchup
    code can't be loaded or fails (the server log says why); it never starts
    a run.

    tokens is what the version shown makes (tokens.deck_tokens: needs, each
    matched against the token cards owned, copies, unlisted, note, counts),
    {"unavailable"} while the card index is being rebuilt, {"error"} when it
    can't be worked out, or None for a pairing. It never adds warnings; rows
    of tokens.csv that can't be read go in info. With needs it also has "forge" (E7-S08,
    token_peaks.with_peaks: the saved Forge games its suggested counts come from, or why
    there are none) and each counted need its "forge" (tokens.peaks.annotate).

    standins is this ordinary deck's saved physical-marker mappings, with desired-card pictures,
    separate from sections and their hashes; None for products and pairings. Its own warnings
    describe invalid saved mappings without changing the logical list.

    printings_in_box is a built home deck's Printings in box record (deck_printings.view: what it
    records that can still be true, why the rest is ignored, and its sheet's choices); absent
    otherwise.

    assembled describes a built ordinary deck's physical snapshot and remaining Planned
    intent, independent of the displayed list version (assembly_intent.project). Cards
    outside the build can already be owned, on the way or missing; neither list is edited.

    played is library_played.deck_played's: when the deck was last played at home and how many
    games it has, from the Game log's games this viewer may see (a hidden other side counted,
    never named), with "since", what its list changed after its last game, from the deck's own
    revisions; None when the games can't be read.

    box_label is an owned intact product's box label (product_label.box_label: its name,
    colours, decks and the deck page its QR code opens), only for a viewer who sees home's
    records; absent otherwise.

    The space's inventory only for those who may see it (the phase 4 design's
    R6d, guard.sees_inventory: User2's decks only User2 and an admin,
    home's only Matt and User1): for anyone else the answer has no owned,
    tokens, table, standins, printings_in_box or assembled at all (an absent key, not None, which means "couldn't be
    worked out"), and the space's pool and tokens aren't read, so none of
    their warnings show. The decklist, guide, stats, practice and matchups
    stay.

    considering is the deck text's Considering list (api/considering.py view: its lines, each with
    "free" and "on_the_way" only for a viewer who sees the space's inventory, and the text's sha256),
    None for a product, a pairing or a text that can't be read. It is never in sections, stats,
    owned, tokens or matchups.
    """
    requested_id = deck_id
    summary, sections = _deck_sections(deck_id, version)
    deck_id = summary["id"]             # a pairing's halves in the library's order
    summary["edited"] = edited_at(deck_id)

    warnings = []
    table = None
    space, kind, slug = spaces.split_deck_id(deck_id)
    sees = guard.sees_inventory(space)
    deck_file = None
    if kind in decks.KINDS:
        try:
            deck_file = decks.read_deck_file(decks.find_deck_file(kind, slug, space), space=space)
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError) as e:
            warnings.append(f"The deck can't be read: {_public(e)}" if not sees else
                            f"Whether the owned-vs-needed table is up to date can't be checked: {_public(e)}")
    # Basic lands (lines with no printing) show a printing from the deck's own sets.
    sets = Counter()
    for section in sections.values():
        for line in section:
            if line.set:
                sets[line.set] += line.quantity
    deck_sets = [s for s, _ in sets.most_common()]
    lines = {name: [_line_json(line, name, warnings, deck_sets) for line in section]
             for name, section in sections.items()}
    stats = _deck_stats(sections, decks.engine_kind(summary), warnings)
    if stats and isinstance(stats.get("warnings"), list):
        stats["warnings"] = _scrub(stats["warnings"])
    p = owned = None
    if sees:                # the space's inventory: its pool, owned vs needed and tokens (R6d)
        pool_warnings = []
        p = _load_pool(pool_warnings, space)
        if p is None:
            warnings.extend(pool_warnings)
        else:
            try:
                owned = _owned_json(pool.owned_vs_needed(deck_id, version, pool=p), p)
                from .reprints import enrich
                enrich(owned["rows"])
                _saved_shop_prices(owned, space, requested_id)
            except (decks.DeckNotFound, decks.DeckFileError, OSError) as e:
                warnings.append(f"Owned vs needed can't be worked out: {_public(e)}")
    if guard.sees_kit(summary):
        kit, summary["holder_sha256"] = _view_kit(summary, sections, warnings)
        summary["kit"] = kit
    else:
        kit = None
        guard.hide_kit(summary).update(kit=None, holder_sha256=None)
    if kit is not None:
        warnings.extend(kit["warnings"])
    if deck_file is not None and sees:
        try:
            table = _table_json(deck_file, p)
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError) as e:
            warnings.append(f"Whether the owned-vs-needed table is up to date can't be checked: {_public(e)}")
    info = list(kit["info"]) if kit is not None else []
    answer = {
        "summary": _named_by_id(summary), "version": version, "versions": list(summary["versions"]),
        "sections": lines, "stats": stats, "practice": _deck_practice(summary, sections),
        "guide": playing_guide(deck_file),
        "usual_opponents": usual_opponents(deck_id),
        # When it was last played at home and what its list changed since (E1-S27): the Game log's games.
        "played": deck_played(deck_id),
        "swaps": view_swaps(deck_file),
        # The Considering list (E2-S23): its free counts only for a viewer who sees the inventory.
        "considering": considering_view(deck_file, deck_id, p, sees, warnings),
    }
    if answer["guide"] is not None:     # the cards it names that have left the deck (E2-S27): own space only
        answer["guide"]["departed"] = departed_cards(answer["guide"], deck_file, deck_id)
    # One card away from a two-card combo (E9-S25): prices for all, availability only with the inventory.
    try:
        near_combos.annotate(stats, deck_id, p, sees, answer["considering"])
    except Exception:           # the page still shows the deck and its other stats; the log has the details
        common._log("Near combos failed:\n" + traceback.format_exc())
        bracket = ((stats or {}).get("commander") or {}).get("bracket")
        if isinstance(bracket, dict):
            bracket.pop("near_combos", None)        # never half annotated
        warnings.append("The combos one card away couldn't be worked out (the server log says why)")
    if "matchups" not in omit:
        answer["matchups"] = _deck_matchups(summary, version, sections)
    if summary.get("kind") == "commander" and space == spaces.HOME:
        from .commander_night import projection
        night = projection()
        if night is not None:
            answer["commander_night"] = night
    if sees:
        # E7-S08: each token's suggested count from the list's saved Forge games (token_peaks.py).
        from .token_peaks import with_peaks
        answer.update(owned=owned, tokens=with_peaks(_view_tokens(summary, version, sections, info), summary, sections),
                      table=table)
        if deck_file is not None and space == spaces.HOME and guard.sees_home_records():
            from decklab.lib.decks import boxcheck
            answer["box_checked_on"] = boxcheck.checked_on(deck_file)
        from .assembly_standins import project
        answer["standins"] = project(deck_file, version) if deck_file is not None else None
        if deck_file is not None and space == spaces.HOME:
            from .deck_printings import view as printings_view
            found = printings_view(deck_file, inventory.current().deck(deck_id), p)
            if found is not None:
                answer["printings_in_box"] = found
        assembled = _assembled_view(summary, p, warnings, deck=deck_file, result=owned if version == "target" else None)
        if assembled is not None:
            answer["assembled"] = assembled
    from .product_label import box_label
    label = box_label(deck_id)
    if label is not None:
        answer["box_label"] = label
    answer.update(warnings=_unique(_scrub(warnings)), info=_unique(info))
    return metadata(answer, requested_id, deck_id)


def _saved_shop_prices(owned, space, requested_id):
    """Saved generic nonfoil evidence stays with home's private buying context.

    Public inventory grants counts, not access to household cache coverage. The
    ordinary deck reader has already authorized the resolved deck. The original
    requested id and both home read rules must also allow this optional capture.
    Failed comparisons and fully covered lists have no missing-card lookup intent.
    """
    if (space != spaces.HOME or not guard.sees_deck(requested_id) or not guard.sees_inventory(spaces.HOME) or
            not guard.sees_home_records() or not isinstance(owned, dict)):
        return
    source = owned.get("rows")
    if not isinstance(source, list):
        return
    rows = [row for row in source if isinstance(row, dict) and
            type(row.get("missing")) is int and row["missing"] > 0]
    if not rows:
        return
    from . import shop_missing_prices, shop_prices
    captured = shop_prices.capture()
    shop_missing_prices.enrich_shops(rows, shop_prices.by_shop(captured), shop_prices._loaded_resolver())
