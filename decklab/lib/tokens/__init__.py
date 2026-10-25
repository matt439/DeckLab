"""The token inventory (magic/tokens.csv) and the tokens each deck uses.

Data only: reading and checking the token cards, parsing what a row's
details say, matching owned token cards against the tokens a deck's cards
make (from the card index's links between cards and tokens) and the words
for each need. The rows come from the inventory snapshot
(decklab.lib.inventory.current(): the files under magic/ or the database,
whichever backend is in use), never from a file read here. The Tokens
page's writes are inventory operations (ops.py: tokens.add, tokens.edit,
tokens.remove), applied by lib/api/tokens.py and python -m decklab.db
tokens; receipts write the rest.

Spaces (lib/spaces.py): home's inventory is magic/tokens.csv, and each
person's is magic/people/<id>/tokens.csv, in the same columns (the names
messages use for them, whichever backend holds the rows). A deck is matched
against its own space's inventory; token orders are home's only, so a
person's decks never have tokens on the way.

The CSV has the columns FIELDS (inventory.rules.TOKEN_FIELDS), one row per
kind of physical card; quantity counts cards, not faces. Its rules (front
required, positive quantity, set and finish shapes) are
rules.validate_token_row's, so the page and receipts agree; this module adds
the page's own limits (lengths, one-line details and notes). Rows are kept
in rules.token_sort_key order.

A row's details are free text such as "1/1; green; flying, deathtouch",
"no lifelink" or "colour unconfirmed" (see parse_details). Only details count
when matching a token: notes never lower or raise a match. Deck Lab never
claims how many tokens a game needs (see NOTE).

Parts: rows.py (a CSV row's rules and the file's bytes), names.py (the card
index and Scryfall face names), details.py (parse_details), matching.py (an
owned row against one need, and the describing words), needs.py (building
and wording a need) and ops.py (the writes). This file keeps reading the
inventory and pending orders, deck_tokens, holders and the cache, check and
the CLI: everything a test patches (read, incoming, deck_tokens,
cached_deck_tokens, row_uses) has its one binding here, beside its readers,
and no part reads them. The one exception is _faces_at, which lives only in
names.py; tests patch it there.

Usage:

    from decklab.lib import tokens

    inv = tokens.read()                       # lenient: bad rows go to inv.problems
    inv = tokens.read(space="user2")        # a person's tokens.csv (lib/spaces.py)
    inv, inc, problems = tokens.for_space(space)   # what a deck in that space is matched against
    inv = tokens.read(strict=True)            # TokensError on any bad row (for writes)
    inc, problems = tokens.incoming()         # pending token payloads named by order records
    tokens.deck_tokens(decks.load_deck("casual/x"), inv, inc)   # needs, words, counts
    python -m decklab.lib.tokens --check      # the file's rules, after hand edits (warnings don't fail it)
    python -m decklab.lib.tokens --check --space user2   # a person's tokens.csv
    python -m decklab.lib.tokens commander/gandalf-and-the-valley [--owned]
"""
import argparse
import collections
import copy
import hashlib
import json
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from decklab.lib import cards, config, decks, inventory, pool, spaces
from decklab.lib.decks.decklist import SECTIONS
from decklab.lib.inventory import files as inventory_files
from decklab.lib.inventory import paths as inventory_paths
from decklab.lib.inventory import rules as inventory_rules

from .details import COLOUR_WORDS, KEYWORDS, Facts, Mistake, _keywords, details_mistakes, parse_details
from .matching import _and, _best, _close, _describe, match_face
from .names import NAMES_UNCHECKED, _index, _printing_problem, _ready, _suggest, check_names
from .needs import (COPY_WORDS, _COPY_RE, _UNLISTED, _any_token, _card_text, _covered, _incoming_groups,
                    _made_by, _need, _need_words, _plural, _unresolved_need, brief)
from .rows import (DETAILS_MAX, FIELDS, NAME_MAX, NOTES_MAX, NUMBER_MAX, QTY_MAX, _rules, csv_bytes, label,
                   validate_row)
from . import ops  # noqa: F401,E402  (registers the tokens.* inventory operations)

LABEL = inventory_paths.tokens(spaces.HOME)   # how messages name home's tokens.csv
LEGACY_FIELDS = inventory_files.TOKEN_LEGACY_FIELDS
NOTE = ("Worked out from Scryfall's links between cards and tokens, so it's approximate. "
        "Tokens a card makes only through its rules text, and most token copies of other cards, "
        "aren't listed. Some listed tokens appear only in certain modes or for your opponent. "
        "Deck Lab can't tell how many a game needs.")
STATES = ("none", "incoming", "differs", "check", "ready")      # also the sort order
_KIND_ORDER = ("token", "emblem", "reminder")
_SINGLE_SIDED = "single-sided verified"


class TokensError(ValueError):
    """tokens.csv can't be read strictly (bad header or row), so it can't be changed."""


@dataclass
class Inventory:
    """A space's token cards as read: its rows (dicts of FIELDS, every value
    a string, quantity too), the sha256 of its tokens.csv as rendered
    (inventory.files.rendered_sha256: what the Tokens page sends back to say
    which version it edited; None when the space has none), from a lenient
    read the rows left out as text, whether the rows are in
    rules.token_sort_key order, and the line each row starts on (the file's
    lines, or the rendered file's for the database backend)."""
    rows: list = field(default_factory=list)
    sha256: str | None = None
    problems: list = field(default_factory=list)
    sorted: bool = True
    lines: list = field(default_factory=list)



# ------------------------------------------------------------------ reading

def label_for(space=spaces.HOME):
    """How messages name a space's tokens.csv (magic/tokens.csv at home,
    magic/people/<id>/tokens.csv for a person)."""
    return inventory_paths.tokens(space)


def no_problems(space=spaces.HOME):
    """What tokens check prints for a space whose token cards break no rule."""
    return f"Token cards ({space}): no problems"


def _known(space):
    """spaces.SpaceNotFound for a space config.json doesn't list."""
    if space != spaces.HOME:
        spaces.get(space)


def for_space(space=spaces.HOME):
    """(inventory, incoming rows, problems reading the incoming orders) that
    a deck in space is matched against: home's tokens.csv and pending token
    orders, or a person's own tokens.csv and nothing on the way."""
    if space == spaces.HOME:
        inc, problems = incoming()
        return read(), inc, problems
    return read(space=space), [], []


def read(strict=False, space=spaces.HOME):
    """The Inventory of a space's token cards (home's by default) in the
    inventory snapshot; an empty one when the space has none.

    strict (for writes) raises TokensError for a header other than FIELDS,
    malformed CSV or a bad row, worded "magic/tokens.csv line N: ..." and
    inventory_rules.UNTIL_PUT_RIGHT. Otherwise the columns may come in any order, the older
    6-column header (no printing columns) is read with those blank, and bad
    rows are left out and listed in problems. (Only the files backend can
    hold such rows: the snapshot keeps each source's problems as the file
    reader words them, inventory/files.py.)"""
    _known(space)
    sheet = inventory.current().token_set(space)
    if not sheet.exists:
        return Inventory()
    if strict and sheet.strict_error:
        raise TokensError(sheet.strict_error)
    return Inventory(rows=[row.as_dict() for row in sheet.rows], sha256=inventory_files.rendered_sha256(sheet),
                     problems=list(sheet.problems), sorted=sheet.sorted, lines=list(sheet.lines))


def incoming():
    """([{order, component, path, rows}], problems): the rows of every
    pending tokens component in the order records (purchases.read_records,
    which checks every record: one that breaks the rules is one problem and
    no rows), taken from the inventory snapshot. A payload that can't be
    read is a problem, not an exception."""
    from decklab.lib import purchases
    root = Path(config.REPO)
    try:
        records = purchases.read_records()
    except (ValueError, OSError) as e:
        return [], [f"The order records can't be read: {_scrub(str(e), root)}"]
    payloads = inventory.current().payloads
    out, problems = [], []
    for record in records:
        for component in record["components"]:
            if component["kind"] != "tokens" or component["status"] != "pending":
                continue
            rel = component["path"]
            sheet = payloads.get(rel)
            # the old receive_order.token_rows' complaint (incoming=False: unverified notes are fine
            # until the receipt), as the snapshot keeps it.
            problem = (f"[Errno 2] No such file or directory: '{rel}'" if sheet is None
                       else sheet.error if sheet.error is not None else sheet.strict_error)
            if problem is not None:
                problems.append(_scrub(problem, root, root / rel, rel))
                continue
            out.append({"order": record["id"], "component": component["id"],
                        "path": rel, "rows": [row.as_dict() for row in sheet.rows]})
    return out, problems


def _scrub(text, root, path=None, rel=None):
    """A message with the repo's absolute paths written relative to it."""
    if path is not None:
        text = text.replace(str(path), rel)
    return text.replace(str(Path(root)) + "\\", "").replace(str(Path(root)) + "/", "")



# ------------------------------------------------------------------ a deck's tokens

def deck_tokens(sections, inv=None, incoming_rows=None):
    """The tokens, emblems and reminders a decklist's cards make, matched
    against the owned token cards (the one place their wording comes from):

        {needs: [{key, name, kind, type_line, pt, colors, keywords, text, image,
                  faces, face_names, made_by: [{name, quantity, section}],
                  sideboard_only, state, words, usable, on_the_way,
                  cards: [{row, front, back, side, quantity, verdict, why, also_for}],
                  stand_ins: [{row, front, back, side, quantity, why, close}],
                  incoming: [{order, front, back, quantity}]}],
         copies, unlisted, note, counts: {kinds, ready, check, differs, incoming, none}}

    sections is {section: [DeckLine]}; inv (read() by default) the owned
    rows, row being an index into inv.rows; incoming_rows incoming()'s list
    (read by default). key is a token's oracle id, or "name:<Name>" when
    Scryfall's link doesn't say which of several tokens it is. state is
    ready, check, differs, incoming or none (see STATES); no count of how many
    a game needs is ever claimed. Raises RuntimeError when the card index
    isn't ready."""
    _index()
    inv = read() if inv is None else inv
    if incoming_rows is None:
        incoming_rows, _ = incoming()
    pending = _incoming_groups(incoming_rows)

    needs, makers, unresolved_cards = {}, [], {}
    for section in SECTIONS:
        for line in sections.get(section, []):
            name = pool._canonical(line.name, "deck", unresolved_cards)
            if decks.is_basic_land(name) or cards.card(name) is None:
                continue
            made, unresolved = cards.tokens_for(name)
            makers.append((name, made, unresolved))
            for entry in made:
                need = needs.setdefault(entry["id"], _need(entry))
                _made_by(need, name, line.quantity, section)
            for part in unresolved:
                need = needs.setdefault(f"name:{part}", _unresolved_need(part))
                _made_by(need, name, line.quantity, section)

    copies, unlisted = [], []
    for name, made, unresolved in makers:
        text = _card_text(cards.card(name))
        makes_copy = any(cards.fold(t["name"]) == "copy" for t in made)
        if _COPY_RE.search(text) and not makes_copy and name not in copies:
            copies.append(name)
        for pattern, test in _UNLISTED:
            if not pattern.search(text):
                continue
            if test is _any_token and (name in copies or makes_copy):
                continue
            if not _covered(made, unresolved, test) and name not in unlisted:
                unlisted.append(name)

    out = []
    for need in needs.values():
        need["sideboard_only"] = all(m["section"] == "Sideboard" for m in need["made_by"])
        need["cards"], need["stand_ins"], need["incoming"] = [], [], []
        missing = []
        for i, row in enumerate(inv.rows):
            best = _best(need, row)
            if best is None:
                continue
            side, face, verdict, why, gaps_ = best
            qty = int(row["quantity"])
            item = {"row": i, "front": row["front"], "back": row["back"], "side": side, "quantity": qty}
            if verdict == "differs":
                need["stand_ins"].append({**item, "why": why, "close": False})
            else:
                need["cards"].append({**item, "verdict": verdict, "why": why, "also_for": []})
                if verdict == "check":
                    missing.extend(a for a in gaps_ if a not in missing)
        for order, row in pending:
            best = _best(need, row)
            if best is not None and best[2] != "differs":
                need["incoming"].append({"order": order, "front": row["front"], "back": row["back"],
                                         "quantity": int(row["quantity"])})
        need["usable"] = sum(c["quantity"] for c in need["cards"])
        need["on_the_way"] = sum(c["quantity"] for c in need["incoming"])
        verdicts = {c["verdict"] for c in need["cards"]}
        if verdicts & {"exact", "agrees"}:
            state = "ready"
        elif "check" in verdicts:
            state = "check"
        elif need["stand_ins"]:
            state = "differs"
        elif need["incoming"]:
            state = "incoming"
        else:
            state = "none"
        need["state"] = state
        if state in ("none", "incoming", "differs"):
            taken = {s["row"] for s in need["stand_ins"]}
            names = [need["name"], *need.get("face_names", [])]
            for i, row in enumerate(inv.rows):
                if i in taken:
                    continue
                for side in ("front", "back"):
                    face = row[side]
                    if face and any(_close(face, n) for n in names):
                        need["stand_ins"].append({
                            "row": i, "front": row["front"], "back": row["back"], "side": side,
                            "quantity": int(row["quantity"]),
                            "why": [f"close name: {face}, not {need['name']}"], "close": True})
                        break
        order = ["P/T", "colour", *(k.lower() for k in need["keywords"])]
        missing.sort(key=lambda a: order.index(a) if a in order else len(order))
        need["words"] = _need_words(need, missing)
        out.append(need)

    # The same physical row serving several needs of this deck.
    serving = collections.defaultdict(list)
    for need in out:
        for c in need["cards"]:
            serving[c["row"]].append(need["name"])
    for need in out:
        for c in need["cards"]:
            c["also_for"] = list(dict.fromkeys(n for n in serving[c["row"]] if n != need["name"]))

    out.sort(key=lambda n: (STATES.index(n["state"]),
                            _KIND_ORDER.index(n["kind"]) if n["kind"] in _KIND_ORDER else len(_KIND_ORDER),
                            cards.fold(n["name"]), n["key"]))
    counts = {"kinds": len(out), **{s: sum(1 for n in out if n["state"] == s) for s in reversed(STATES)}}
    return {"needs": out, "copies": copies, "unlisted": unlisted, "note": NOTE, "counts": counts}



# ------------------------------------------------------------------ holders and the cache

def _holders(warnings, space=spaces.HOME):
    """[(id, title, version, sections, link)] of a space: built decks (their
    built version), decks being built (their target list) and, at home, owned
    products kept intact. link is the deck id a deck page opens for the
    holder: its own id, or None for a product whose CSV names several decks
    (product/<stem> is then no deck; the page links to the product library
    instead)."""
    from decklab.lib import accessories
    found = []
    for summary in decks.list_decks():
        if summary["id"].startswith(("product/", "pairing/")) or summary.get("space", spaces.HOME) != space:
            continue
        status = summary.get("status")
        if status not in ("built", "building"):
            continue
        if summary.get("error"):
            warnings.append(f"{summary['source']} can't be read: {summary['error']}")
            continue
        version, sections = "target", None
        try:
            if status == "built":
                from decklab.lib.decks import assembled
                from decklab.lib.inventory.ops_decks import parsed_deck
                parsed = parsed_deck(inventory.current().deck(summary["id"]))
                if parsed is not None and assembled.get(parsed):
                    sections = assembled.sections(parsed)
                    version = assembled.version(parsed)
            if sections is None:
                version = pool._built_version(summary, warnings) if status == "built" else "target"
                sections = decks.load_deck(summary["id"], version)
        except (decks.DeckNotFound, decks.DeckFileError, OSError) as e:
            warnings.append(f"{summary['source']} can't be read: {e}")
            continue
        found.append((summary["id"], summary["title"], version, sections, summary["id"]))
    if space != spaces.HOME:
        return found
    product_decks = None
    listed = {product.file for product in inventory.current().products}
    for name, status in pool.read_status(warnings).items():
        if not (status.status == "owned" and status.intact) or name not in listed:
            continue
        if product_decks is None:
            product_decks = decks._product_decks()
        stem = Path(name).stem
        holder = f"product/{stem}"
        link = holder if any(d["id"] == holder for d in product_decks) else None
        found.append((holder, pool._product_name(name), "target",
                      accessories._product_sections(stem, product_decks), link))
    return found


def holders(warnings, space=spaces.HOME):
    """[(id, title, sections)] of every list of a space whose tokens count:
    casual and commander decks that are built (their built version) or being
    built (their target list), and (home's) owned products kept intact (all
    their decks). Idea decks and pairings are left out. Problems go in warnings."""
    return [(i, t, s) for i, t, _, s, _ in _holders(warnings, space)]


def gaps(inv, incoming_rows, warnings, space=spaces.HOME):
    """[{key, name, kind, image, state, decks: [{id, title, link}], on_the_way}]:
    the tokens holders() of space need with nothing owned in inv (state none
    or incoming). link is the deck id to open, or None (see _holders)."""
    out = {}
    for deck_id, title, version, sections, link in _holders(warnings, space):
        result = cached_deck_tokens(deck_id, version, sections, inv, incoming_rows)
        for need in result["needs"]:
            if need["state"] not in ("none", "incoming"):
                continue
            gap = out.setdefault(need["key"], {
                "key": need["key"], "name": need["name"], "kind": need["kind"], "image": need["image"],
                "state": need["state"], "decks": [], "on_the_way": need["on_the_way"]})
            if all(d["id"] != deck_id for d in gap["decks"]):
                gap["decks"].append({"id": deck_id, "title": title, "link": link})
    return sorted(out.values(), key=lambda g: (STATES.index(g["state"]), cards.fold(g["name"]), g["key"]))


_STATE_OF = {"exact": "ready", "agrees": "ready", "check": "check", "differs": "differs"}


def row_uses(inv, incoming_rows, warnings, space=spaces.HOME):
    """{row index: [{deck, title, link, token, side, state}]}: which of
    holders()' needs (space's) each owned row of inv serves (state ready or
    check) or stands in for (differs). link is the deck id to open, or None
    (see _holders). Close-name hints aren't uses."""
    out = collections.defaultdict(list)
    for deck_id, title, version, sections, link in _holders(warnings, space):
        result = cached_deck_tokens(deck_id, version, sections, inv, incoming_rows)
        for need in result["needs"]:
            for c in need["cards"]:
                out[c["row"]].append({"deck": deck_id, "title": title, "link": link, "token": need["name"],
                                      "side": c["side"], "state": _STATE_OF[c["verdict"]]})
            for s in need["stand_ins"]:
                if not s["close"]:
                    out[s["row"]].append({"deck": deck_id, "title": title, "link": link, "token": need["name"],
                                          "side": s["side"], "state": "differs"})
    return dict(out)


def built_ids(space=spaces.HOME):
    """The ids of a space's built decks: the holders of row_uses that pack
    their token cards. Owned products kept intact (product/<stem>) count as
    built too, but aren't listed here: shared_rows counts every product/
    holder as built."""
    return {s["id"] for s in decks.list_decks()
            if s.get("space", spaces.HOME) == space and s.get("status") == "built"
            and not s["id"].startswith(("product/", "pairing/"))}


def _is_built(deck_id, built):
    return deck_id in built or deck_id.startswith("product/")


def shared_rows(inv, uses, built):
    """{row index: [{deck, title, link}]}: the rows of inv whose uses
    (row_uses) name more built holders (built_ids, and intact products) than
    the row has cards, each with those holders in the order uses names them.
    Each built holder is taken to pack at least one card of a row it uses, so
    such a row can't be in all of their boxes at once. A stand-in counts: it
    is packed too. Decks still being built never count."""
    out = {}
    for i, items in uses.items():
        holders = []
        for use in items:
            if _is_built(use["deck"], built) and all(h["deck"] != use["deck"] for h in holders):
                holders.append({"deck": use["deck"], "title": use["title"], "link": use["link"]})
        if i < len(inv.rows) and len(holders) > int(inv.rows[i]["quantity"]):
            out[i] = holders
    return out


def shared_words(row, holders):
    """"Only 2 cards, used by 3 built decks: A, B and C": the warning for a
    row of shared_rows."""
    cards_ = int(row["quantity"])
    return (f"Only {_plural(cards_, 'card')}, used by {len(holders)} built decks: "
            f"{_and([h['title'] for h in holders])}")


CACHE_SIZE = 64
_cache = collections.OrderedDict()
_cache_lock = threading.Lock()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8")).hexdigest()


def _sections_key(sections):
    return _fingerprint({s: [[l.quantity, l.name, l.set, l.number, l.finish] for l in lines]
                         for s, lines in sections.items()})


def cached_deck_tokens(deck_id, version, sections, inv, incoming_rows):
    """deck_tokens(sections, inv, incoming_rows), kept for the 64 lists asked
    for most recently. The key is the deck and version, the list's own lines,
    the tokens file's sha256, the incoming payloads and the card index, so
    any change to them works it out again. Returns a copy."""
    data = _index().data
    key = (deck_id, version, _sections_key(sections), inv.sha256, _fingerprint(inv.rows),
           _fingerprint(incoming_rows or []), data.get("built_at"), id(data))
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return copy.deepcopy(_cache[key])
    result = deck_tokens(sections, inv, incoming_rows or [])
    with _cache_lock:
        _cache[key] = result
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return copy.deepcopy(result)


def clear_cache():
    """Forget every cached deck_tokens result (for tests)."""
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------------ checking

def check(notes=None, space=spaces.HOME, warnings=None):
    """Every broken rule of a space's token cards (home's by default) and,
    at home, of the pending token payloads, as text; [] when all is well.
    Notes (the name checks being skipped while the card index isn't ready)
    are appended to notes, not returned. Warnings, details parts that look
    like mistakes (details_mistakes: "4/4 white flying", "whte"), are
    appended to warnings: they never fail the check."""
    notes = [] if notes is None else notes
    wants_warnings = warnings is not None
    warnings = [] if warnings is None else warnings
    file_label = label_for(space)
    problems = []
    try:
        read(strict=True, space=space)
    except TokensError as e:
        problems.append(str(e))
    inv = read(space=space)
    seen = {p.removesuffix(inventory_rules.UNTIL_PUT_RIGHT) for p in problems}
    problems.extend(p for p in inv.problems if p not in seen)
    if not inv.sorted:
        problems.append(f"{file_label}: not in the standard order; the next Tokens page save sorts it")
    ready = _ready()
    if not ready and inv.rows:
        notes.append("Names weren't checked: the card data isn't loaded "
                     "(python -m decklab.lib.cards update)")
    for n, row in zip(inv.lines, inv.rows):
        where = f"{file_label} line {n}"
        if ready:
            for side in ("front", "back"):
                name = row[side]
                if name and cards.token_face(name) is None:
                    hint = _suggest(name)
                    problems.append(f"{where}: '{name}' isn't a Scryfall token, emblem or reminder name"
                                    + (f" (did you mean {hint}?)" if hint else ""))
            for side in ("front", "back"):
                if row[side] and cards.token_face(row[side]) is not None:
                    problem = _printing_problem(row, side)
                    if problem:
                        problems.append(f"{where}: {problem}")
        single = _SINGLE_SIDED in row["notes"].lower()
        if not row["back"] and not single:
            problems.append(f"{where}: a blank back needs '{_SINGLE_SIDED}' in notes")
        if row["back"] and single:
            problems.append(f"{where}: notes say {_SINGLE_SIDED} but a back is recorded")
        for side in ("front", "back"):
            for mistake in details_mistakes(row[f"{side}_details"]):
                warnings.append(f"{where}: {side} details '{mistake.part}' aren't read: {mistake.message}")
    if space == spaces.HOME:
        _, payload_problems = incoming()
        problems.extend(payload_problems)
    if wants_warnings and ready and inv.rows:
        warnings.extend(_shared_warnings(inv, space, file_label))
    return problems


def _shared_warnings(inv, space, file_label):
    """check's warnings for rows more built decks use than the row has
    cards (shared_rows), or one line saying why they couldn't be worked out."""
    try:
        found = incoming()[0] if space == spaces.HOME else []
        uses = row_uses(inv, found, [], space)
        shared = shared_rows(inv, uses, built_ids(space))
    except Exception as e:      # a deck that can't be read: the check itself still stands
        return [f"{file_label}: which built decks share token cards couldn't be worked out ({e})"]
    return [f"{file_label} line {inv.lines[i]}: {shared_words(inv.rows[i], holders)}"
            for i, holders in sorted(shared.items())]



def _print_deck(deck_id, owned):
    summary = decks.find_summary(deck_id)
    if summary is None:
        print(f"No deck {deck_id!r}.")
        return 1
    sections = decks.load_deck(deck_id, "owned" if owned else "target")
    inv, inc, inc_problems = for_space(summary.get("space", spaces.HOME))
    result = deck_tokens(sections, inv, inc)
    c = result["counts"]
    print(f"{summary['title']}{' (owned-only list)' if owned else ''}: "
          f"{_plural(c['kinds'], 'kind')} of token · {c['ready']} ready · {c['check']} to check · "
          f"{c['differs']} different · {c['incoming']} on the way · {c['none']} none owned")
    for problem in inv.problems + inc_problems:
        print(f"  ! {problem}")
    for need in result["needs"]:
        traits = _describe(need["name"], need["kind"], need["pt"], need["colors"], need["keywords"])
        kind = "" if need["kind"] == "token" else f" ({need['kind']})"
        print(f"\n{traits}{kind}{' [sideboard only]' if need['sideboard_only'] else ''}")
        print(f"  {need['words']}")
        print("  Made by " + ", ".join(f"{m['name']}" + (" (sideboard)" if m["section"] == "Sideboard" else "")
                                      for m in need["made_by"]))
        for card in need["cards"]:
            face = card["back"] if card["side"] == "back" else card["front"]
            also = f" (same card as for {_and(card['also_for'])})" if card["also_for"] else ""
            why = f": {'; '.join(card['why'])}" if card["why"] else ""
            print(f"  Grab {label(card)} ×{card['quantity']}, {face} side{also}{why}")
        for s in need["stand_ins"]:
            print(f"  Stand-in: {label(s)} ×{s['quantity']} ({'; '.join(s['why'])})")
        for i in need["incoming"]:
            print(f"  On the way: {label(i)} ×{i['quantity']} (order {i['order']})")
    if result["copies"]:
        print(f"\nMakes copies: {', '.join(result['copies'])}")
    if result["unlisted"]:
        print(f"May also make things Scryfall doesn't link: {', '.join(result['unlisted'])}")
    print(f"\n{NOTE}")
    return 0


def main(argv=None):
    from decklab.lib import venv
    venv.activate()             # the database backend needs .venv's psycopg (lib/venv.py)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.tokens",
                                     description="Check the token inventory, or show a deck's tokens.")
    parser.add_argument("deck", nargs="?", help="a deck id, such as commander/gandalf-and-the-valley "
                                                "or user2/casual/elves")
    parser.add_argument("--owned", action="store_true", help="the deck's owned-only list")
    parser.add_argument("--check", action="store_true", help="report broken rules; exit 1 if there are any")
    parser.add_argument("--space", default=spaces.HOME, help="with --check: whose token cards (default home)")
    args = parser.parse_args(argv)
    with inventory.pinned():    # one snapshot for the whole command
        code = _main(parser, args)
        stale = inventory.pinned_stale()
    if stale:                   # the database's last good snapshot, as python -m decklab.db says
        print(f"Note: {stale}.", file=sys.stderr)
    return code


def _main(parser, args):
    if args.check:
        notes, warnings = [], []
        try:
            problems = check(notes=notes, space=args.space, warnings=warnings)
        except spaces.SpaceNotFound as e:
            print(e)
            return 1
        for text in problems + warnings + notes:
            print(text)
        if not problems:
            print(no_problems(args.space))
        return 1 if problems else 0
    if not args.deck:
        parser.print_help()
        return 0
    try:
        return _print_deck(args.deck, args.owned)
    except RuntimeError as e:
        print(f"The card data isn't ready: {e}")
        return 1
    except (decks.DeckNotFound, decks.DeckFileError) as e:
        print(e)
        return 1
