"""The editor's endpoints that don't write: GET /api/deck/edit (edit_view),
POST /api/decklist/parse ("Paste a list", parse_list), POST
/api/deck/check (check_draft: what a save would do) and GET /api/deck/find
(find_cards: the Add panel's search and "My collection").
"""
import re
import traceback

from decklab.lib import accessories, cards, decks, permissions, pool, spaces

from . import common, deck_aliases, drafts, guard
from .card_lookup import (_card_printings, _default_printing, _lines_json, _not_paper, _owned_json, _pickable,
                          _pool_counts, _resolve)
from .carddata import _require_cards
from .commits import _deck_file, _parse_file, _stored, _table_json, _without_own_built_warning
from .card_lookup import DID_YOU_MEAN, MAX_SEARCH as MAX_SEARCH_TEXT, _card_json, _shown_printing
from .common import LINE_FINISHES, _CONTROL_RE
from .common import MAX_QTY, ApiError, _flag, _keys, _lazy, _parse_body, _public, _scrub, _sha, _unique
from .drafts import (MAX_SUGGESTED, _bracket_names, _brackets, _counts, _final, _new_fields, _rule_warnings,
                     _warnings_json)
from .library import _find_summary, _load_pool, _scrub_summary, check_deck_id
from .settings import _writer

MAX_PASTE = 64 * 1024           # bytes of pasted decklist text
# The sections the editor offers for each kind (plus any other a file already has).
EDITOR_SECTIONS = {"casual": ("Deck", "Sideboard"), "commander": ("Commander", "Deck", "Sideboard")}
# Arena exports start with "About" and "Name <deck>"; a pasted list skips them.
_ARENA_ABOUT_RE = re.compile(r"(?i)about|name\s.*")


def _offered_sections(kind, *decklists):
    present = {name for sections in decklists if sections for name in sections}
    return [name for name in decks.SECTIONS if name in EDITOR_SECTIONS[kind] or name in present]


def _forge_lists(deck):
    """Optional playable identities from this exact parsed snapshot; no engine is started."""
    try:
        from decklab.lib.forge.lists import card_sha
        kind = "commander" if deck.kind == "commander" else "constructed"
        return {version: card_sha(sections, kind) if sections is not None and (version == "target" or sections) else None
                for version, sections in (("target", deck.target), ("owned", deck.owned))}
    except Exception:
        common._log(f"The editor's optional Forge identities can't be worked out:\n{traceback.format_exc()}")
        return {}


def _file_edit_json(deck, p, warnings):
    """edit_view()'s answer for a deck file."""
    why_not = None
    if not decks.valid_slug(deck.slug):
        why_not = (f"Deck Lab can't save {spaces.join_deck_id(deck.space, deck.kind, deck.slug)}: only decks "
                   f"named with lowercase letters, digits and hyphens can be saved (make a new deck to edit it "
                   f"here).")
    elif not deck.has_decklist:
        why_not = f"The deck has {decks.NO_DECKLIST}."
    home = deck.space == spaces.HOME
    # A person's deck has no Played by, Sleeves or Deck box (drafts._HOME_ONLY), unless the file has them.
    editable_fields = ["status", "player", "archetype"] if home or deck.get_field("Played by") is not None \
        else ["status", "archetype"]
    # A Built version left on a deck that isn't built (any more) is offered too, so it can be removed.
    if (deck.status == "built" and deck.owned) or deck.built_version is not None:
        editable_fields.append("built_version")
    if deck.kind == "commander":
        editable_fields.append("target_bracket")
    # Sleeves likewise: a built deck's, or one left on a deck that isn't built.
    if (deck.status == "built" and home) or deck.get_field("Sleeves") is not None:
        editable_fields.append("sleeves")
    if (deck.status == "built" and home) or deck.get_field("Deck box") is not None:
        editable_fields.append("deck_box")
    deck_id = deck.deck_id
    answer = {
        "id": deck_id, "space": deck.space, "kind": deck.kind, "title": deck.title, "source": deck_id,
        "editable": why_not is None, "why_not": why_not, "sha256": deck.sha256 if why_not is None else None,
        "fields": {"format": deck.format, "status": deck.status, "player": deck.player,
                   "archetype": deck.get_field("Archetype"), "built_version": deck.built_version,
                   "target_bracket": deck.target_bracket, "sleeves": deck.sleeves, "deck_box": deck.deck_box},
        "field_text": {key: deck.get_field(key) for key in decks.OWNED_FIELDS},
        "editable_fields": editable_fields if why_not is None else [],
        "sections": _offered_sections(deck.kind, deck.target, deck.owned),
        "lists": {"target": _lines_json(deck.target, warnings), "owned": _lines_json(deck.owned or None, warnings),
                  "considering": _lines_json({"Considering": deck.considering or []}, warnings)["Considering"]},
        # These identify only the playable lists, using Forge's exact main/commander semantics.
        # Work from this parsed snapshot rather than loading the deck again after a concurrent save.
        "forge_lists": _forge_lists(deck),
        "changed_on": deck.changed_on,
        "prose": drafts.prose_of(deck.text),
        "new_deck": None,
    }
    if guard.sees_inventory(deck.space):        # the table note shows the space's inventory (R6d)
        answer["table"] = _table_json(deck, p)
        from decklab.lib.decks import assembled
        if deck.status == "built" and assembled.get(deck) is not None and guard.sees_kit(deck):
            answer["assembled_need"] = accessories.sleeve_need(assembled.sections(deck))
    return answer


def _snapshot_deck(kind, slug, space):
    """The parsed deck file of an id, from the inventory's snapshot (decks.read_deck_file):
    ApiError 404 when there's no such deck, 500 when it can't be read."""
    try:
        return decks.read_deck_file(decks.find_deck_file(kind, slug, space), space=space)
    except (decks.DeckNotFound, FileNotFoundError):
        raise guard.no_deck(spaces.join_deck_id(space, kind, slug)) from None
    except (decks.DeckFileError, OSError) as e:
        raise ApiError(500, f"{spaces.join_deck_id(space, kind, slug)} can't be read: {_public(e)}") from None


def _new_title(summary):
    """A new deck's suggested title: the product deck's without its product
    ("Cats + Vampires (Beginner Box)" -> "Cats + Vampires")."""
    return re.sub(r"\s*\([^()]*\)$", "", summary["title"]).strip() or summary["title"]


def edit_view(deck_id):
    """GET /api/deck/edit?id=<deck id>: a deck as the editor loads it.

    For a deck file (read from the inventory's snapshot): id, kind, title,
    source (its id: the pages name a deck by its id), editable and why_not (a
    hand-named file or one with no "## Decklist" block can't be saved),
    may_save and why_not_save (whether this visitor may save the deck, and
    lib/permissions.py's reason if not; the editor still opens, for "Try a
    change", without Save, and check_draft still answers),
    sha256 (send it back with the save; the conflict check compares it),
    fields (parsed: format, status, player, archetype, built_version "target"
    or "owned", target_bracket 1-5, sleeves; None when absent or unreadable),
    field_text (Deck Lab's header fields as written), editable_fields,
    sections (the ones the editor offers), lists {"target", "owned" (None
    when the file has none)} in deck_view's line format, forge_lists (each saved
    version's playable card_sha, ignoring printings/order/sideboard as Forge does), changed_on (the
    "Decklist changed" date), prose ({"substitutes", "notes"}: the
    write-up's text, each None when the deck has no such section;
    drafts.prose_of), table (the out-of-date note, _table_json; left
    out for a visitor who may not see the deck's space's inventory,
    guard.sees_inventory: the phase 4 design's R6d, and then the pool isn't
    read), new_deck None, brackets ([{"number",
    "name"}] of the Commander Brackets, for the bracket picker) and warnings.
    editable_fields has built_version for a built deck with both lists, and
    for any deck whose file has a Built version (so a stray one can be removed);
    sleeves and deck_box likewise for a built deck or a file with that line
    (fields.sleeves and fields.deck_box are an accessory id, or older free
    text). other_sleeves lists the sleeves other holders use ([{"id",
    "title", "sleeves"}], drafts.built_sleeves), for the Sleeves hint.
    accessories is {"sleeves": [...], "deck_box": [...]}, the rows of each
    kind for the pickers (_accessories_json; both [] when they can't be read):
    only those this deck may take (its owner's or shared, guard.holder_owner).
    Holders the visitor can't see are named only as "one of User1's decks".
    A visitor who may not see the deck's owner's accessories (guard.sees_kit) gets
    none of them (_hide_accessories): fields.sleeves and fields.deck_box and
    their field_text None, neither in editable_fields, other_sleeves [] and
    both pickers empty. The editor sends only the fields it changed, so a
    save from such a visitor leaves the file's lines as they are.

    A product deck, Beginner Box half or pairing is read-only: the same keys,
    with editable False, sha256/table None, and new_deck {"from", "kind"
    ("commander" for a Commander precon, else "casual"), "title", "slug",
    "exists"}: what "Save as a new deck" suggests (create_deck).
    """
    check_deck_id(deck_id)
    _require_cards()
    summary = _scrub_summary(dict(_find_summary(deck_id)))
    space, kind, rest = spaces.split_deck_id(summary["id"])
    warnings = []
    # The space's pool only for those who may see its inventory (R6d): it's read for the table note.
    p = _load_pool(warnings, space) if guard.sees_inventory(space) else None
    if kind in decks.KINDS:
        answer = _file_edit_json(_snapshot_deck(kind, rest, space), p, warnings)
        # A visitor who may not change this deck still gets the editor ("Try a change"), without Save.
        # editable stays about the file itself; may_save says whether this visitor may save it.
        why = permissions.reason(guard.viewer(), "deck.edit", summary, script=guard.script())
        answer["may_save"], answer["why_not_save"] = why is None, why
    else:
        if summary.get("error"):
            raise ApiError(500, f"{summary['source']} can't be read: {summary['error']}")
        try:
            sections = decks.load_deck(summary["id"])
        except decks.DeckNotFound as e:
            raise ApiError(404, _public(e)) from None
        except (decks.DeckFileError, OSError) as e:
            raise ApiError(500, f"{summary['source']} can't be read: {_public(e)}") from None
        new_kind = "commander" if summary["kind"] == "commander" else "casual"
        title = _new_title(summary)
        slug = decks.title_slug(title)
        answer = {
            "id": summary["id"], "space": spaces.HOME, "kind": new_kind, "title": summary["title"],
            "source": summary["source"],
            "editable": False,
            "why_not": "Product decks and Beginner Box pairings stay as they came: changes are saved as a new deck.",
            "sha256": None,
            "fields": {"format": summary["format"], "status": None, "player": None, "archetype": None,
                       "built_version": None, "target_bracket": None, "sleeves": None, "deck_box": None},
            "field_text": {key: None for key in decks.OWNED_FIELDS},
            "editable_fields": [], "sections": _offered_sections(new_kind, sections),
            "lists": {"target": _lines_json(sections, warnings), "owned": None},
            "changed_on": None, "table": None, "prose": None,
            "new_deck": {"from": summary["id"], "kind": new_kind, "title": title, "slug": slug,
                         "exists": bool(slug) and decks.existing_deck_id(slug) is not None},
        }
        if not guard.sees_inventory(space):     # absent, as a deck file's (R6d): None means "can't say"
            del answer["table"]
    answer["brackets"] = _brackets()
    deck_aliases.metadata(answer, deck_id)
    if not guard.sees_kit(summary):
        answer["warnings"] = _unique(_scrub(warnings))
        return _hide_accessories(answer)
    owners = guard.accessory_owners()
    if not guard.sees_kit(summary, owners):
        # Public kit is readable, but none of its fields or choices may be changed.
        answer["editable_fields"] = [f for f in answer["editable_fields"] if f not in ("sleeves", "deck_box")]
        answer["other_sleeves"] = []
        answer["accessories"] = _accessories_json(None, None)
        answer["warnings"] = _unique(_scrub(warnings))
        return answer
    holder_owner = guard.holder_owner(summary)
    try:
        inv = accessories.read()
        usage = accessories.holders(inv)
    except Exception:           # the pickers are empty; the log has the details
        common._log("The accessories couldn't be read:\n" + traceback.format_exc())
        inv = usage = None
    try:
        answer["other_sleeves"] = (drafts.built_sleeves(answer["id"], inv, usage, owners=owners)
                                   if usage is not None else [])
    except (decks.DeckFileError, OSError, ValueError):
        answer["other_sleeves"] = []
    answer["accessories"] = _accessories_json(inv, usage, holder_owner, owners)
    answer["warnings"] = _unique(_scrub(warnings))
    return answer


def _shown_users(users, owners):
    """A row's holders as the visitor may see them (api/accessories.py's _shown_users)."""
    from .accessories import _shown_users as shown
    return shown(users, owners)


def _hide_accessories(answer):
    """edit_view's answer without the sleeves and deck box, for a visitor
    who may not see the accessories (in place; returns answer)."""
    for key in ("sleeves", "deck_box"):
        answer["fields"][key] = None
    for header in ("Sleeves", "Deck box"):
        if header in answer["field_text"]:
            answer["field_text"][header] = None
    answer["editable_fields"] = [f for f in answer["editable_fields"] if f not in ("sleeves", "deck_box")]
    answer["other_sleeves"] = []
    answer["accessories"] = _accessories_json(None, None)
    return answer


def _accessories_json(inv, usage, holder_owner=None, owners=None):
    """edit_view's "accessories": {"sleeves": [...], "deck_box": [...]}, the
    rows of each kind for the pickers, each {id, label, colour, quantity,
    capacity, image_url, used_by: [{holder, title, kind, need}]}; both [] when the
    inventory can't be read (inv None). Only rows a holder of holder_owner
    may take (accessories.usable; None: any) and owners sees, with the
    holders it can't see named only as "one of User1's decks"."""
    out = {kind: [] for kind in accessories.HOLDER_FIELDS}
    if inv is None:
        return out
    for row in inv.rows_by_id.values():
        if not accessories.visible(row["owner"], owners) or \
                holder_owner is not None and not accessories.usable(row["owner"], holder_owner):
            continue
        if row["kind"] in out:
            out[row["kind"]].append({
                "id": row["id"], "label": accessories.label(row), "colour": row["colour"] or None,
                "quantity": row["quantity"], "capacity": row["capacity"],
                "image_url": accessories.image_url(row),
                "used_by": _shown_users(accessories.used_by(usage, row), owners)})
    for rows in out.values():
        rows.sort(key=lambda r: r["id"])
    return out


def _paste_line(line, exact, warnings, counts):
    """A pasted line with its exact name and a printing: the one written when
    it's that card's, else _default_printing (basic lands may have none)."""
    written = f"{exact} ({line.set.upper()})" + (f" {line.number}" if line.number else "") if line.set else exact
    if line.set and line.number:
        p = cards.printing(line.set, line.number)
        if p is not None and _pickable(p) and _resolve(p["name"]) == exact:
            finish = line.finish
            if finish not in p["finishes"] and p["finishes"]:
                finish = "nonfoil" if "nonfoil" in p["finishes"] else p["finishes"][0]
                warnings.append(f"{written} doesn't come in {line.finish}; using {finish}")
            return decks.DeckLine(line.quantity, exact, line.set, line.number, finish)
        if p is not None and _resolve(p["name"]) == exact:
            problem = f"{written} is {_not_paper(p)}"
        else:
            problem = f"{written} isn't a printing of {exact}"
    elif line.set:
        in_set = [cards.printing(s, n) for s, n in _card_printings(exact) if s == line.set]
        if any(_pickable(p) for p in in_set):
            return decks.DeckLine(line.quantity, exact, line.set, None, line.finish)
        problem = (f"{written} is {_not_paper(in_set[0])}" if in_set
                   else f"{exact} was never printed in {line.set.upper()}")
    else:
        problem = None
    if decks.is_basic_land(exact):
        if problem:
            warnings.append(f"{problem}; left without a set")
        return decks.DeckLine(line.quantity, exact)
    chosen = _default_printing(exact, counts())
    if chosen is None:
        if not any(_pickable(cards.printing(s, n)) for s, n in _card_printings(exact)):
            raise decks.DecklistError(f"{exact} has no playable paper printing: choose a physical card")
        return decks.DeckLine(line.quantity, exact)
    if problem:
        warnings.append(f"{problem}; using {chosen['set'].upper()} {chosen['number']} instead")
    return decks.DeckLine(line.quantity, exact, chosen["set"], chosen["number"], chosen["finish"])


def parse_list(body):
    """POST /api/decklist/parse {"profile", "text"}: "Paste a list".

    Reads Arena/MTGO text the way decks.parse_decklist does (the same line
    parser and section headers, and a card straight after a blank line with
    no header is an error), but reports every bad line instead of stopping at
    the first, and skips Arena's "About" / "Name <deck>" lines at the top.
    Returns sections (lines with known names only, with exact names and
    printings, in deck_view's format), unknown [{"line", "text", "name",
    "qty", "section", "suggestions"}] (never saved), errors [{"line", "text",
    "error"}], warnings and count {"cards", "lines"}."""
    data = _parse_body(body)
    _writer(data)       # a dry run: anyone may paste a list (guard.py)
    _keys(data, ("profile", "text"))
    text = data["text"]
    if not isinstance(text, str):
        raise ApiError(400, "text must be the pasted list, as a string")
    if len(text.encode("utf-8")) > MAX_PASTE:
        raise ApiError(413, f"A pasted list is limited to {MAX_PASTE // 1024} KB")
    _require_cards()
    counts = _lazy(_pool_counts)       # the pool search and the printing picker pick from too
    sections, unknown, errors, warnings = {}, [], [], []
    current, after_blank, orphan, started = None, False, None, False
    for number, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        shown = raw.strip()[:200]
        if not raw.strip():
            after_blank = True
            continue
        header = decks.section_header(raw)
        if header:
            current, after_blank, orphan, started = header, False, None, True
            continue
        if not started and _ARENA_ABOUT_RE.fullmatch(raw.strip()):
            continue
        started = True
        if after_blank and current is not None and orphan is None:
            orphan = number
        after_blank = False
        if orphan is not None:
            # Some exports mark the sideboard with a blank line alone and others
            # don't, so these cards could belong to either: never guess.
            errors.append({"line": number, "text": shown, "error": (
                f"a card after a blank line with no section header (from line {orphan}): put a 'Sideboard' "
                f"(or 'Deck') line above line {orphan}, or remove the blank line")})
            continue
        try:
            line = decks.parse_line(raw.replace("\t", " "))
        except decks.DecklistError as e:
            errors.append({"line": number, "text": shown, "error": str(e)})
            continue
        current = current or "Deck"
        if line.quantity > MAX_QTY:
            errors.append({"line": number, "text": shown, "error": f"at most {MAX_QTY} copies on one line"})
            continue
        exact = _resolve(line.name)
        if exact is None:
            unknown.append({"line": number, "text": shown, "name": line.name, "qty": line.quantity,
                            "section": current,
                            "suggestions": cards.close_names(line.name) if len(unknown) < MAX_SUGGESTED else []})
            continue
        try:
            found = _paste_line(line, exact, warnings, counts)
        except decks.DecklistError as e:
            errors.append({"line": number, "text": shown, "error": str(e)})
            continue
        found.category = line.category      # a pasted " #Ramp" (Moxfield's tags) stays the line's category
        if decks.tag_count(raw) > 1:
            warnings.append(f"{found.name}: kept its first category, {line.category}; a card line holds one")
        merged = sections.setdefault(current, {})
        key = (found.name, found.set, found.number, found.finish)
        if key in merged:
            merged[key].quantity += found.quantity
            merged[key].category = merged[key].category or found.category
        else:
            merged[key] = found
    ordered = {name: list(sections[name].values()) for name in decks.SECTIONS if sections.get(name)}
    lines = _lines_json(ordered, warnings)
    return {"sections": lines, "unknown": unknown, "errors": errors, "warnings": _unique(_scrub(warnings)),
            "count": {"cards": sum(l.quantity for s in ordered.values() for l in s),
                      "lines": sum(len(s) for s in ordered.values())}}


def _new_source(data):
    """(kind, starting sections, source summary or None) for a new deck:
    from data["from"] (a library id; a Commander precon gives a commander
    deck, anything else casual) or data["kind"]."""
    from_id = data.get("from")
    if from_id is None:
        if data.get("kind") not in decks.KINDS:
            raise ApiError(400, "kind must be casual or commander")
        return data["kind"], {}, None
    check_deck_id(from_id)
    summary = _scrub_summary(dict(_find_summary(from_id)))
    if summary.get("error"):
        raise ApiError(500, f"{summary['source']} can't be read: {summary['error']}")
    try:
        sections = decks.load_deck(summary["id"])
    except decks.DeckNotFound as e:
        raise ApiError(404, _public(e)) from None
    except (decks.DeckFileError, OSError) as e:
        raise ApiError(500, f"{summary['source']} can't be read: {_public(e)}") from None
    kind = "commander" if summary["kind"] == "commander" else "casual"
    if data.get("kind") not in (None, kind):
        raise ApiError(400, f"{summary['title']} becomes a {kind} deck, not {data['kind']}")
    return kind, sections, summary


def check_draft(body):
    """POST /api/deck/check: what a save would do, without saving.

    body {"profile", "lists", "fields"?} plus, for a deck file, "id" (and
    "sha256" to learn whether it changed since it was loaded), or for a new
    deck "kind" or "from", and "space" (see create_deck). Returns ok (no blocks), blocks,
    warnings (the deck-building rules and anything kept as written), lists
    as they'd be saved (exact names, printings filled in, repeated printings
    merged; a saved deck's considering is a flat list), counts of the playable
    lists, bracket (Commander), owned (pool.compare of the target
    list, as deck_view's "owned"; None when the pool can't be read or is a
    space whose inventory the visitor may not see, guard.sees_inventory), changes
    {"decklist", "considering" (when sent), "fields", "prose" (the write-up sections a save would
    change), "marker" (whether it takes the "Decklist changed" line off)},
    file_changed, and brackets (as edit_view's, for a
    Commander deck; [] otherwise). warning_cards has, for each warning, the
    names of the cards it's about ([] for none), so the page can mark rows.

    changes is the real difference from the file even while there are
    blocks: a blocked line counts as a list change, a blocked field as a
    changed field. A deck deleted since the page loaded it is ApiError 409
    with the "conflict" a save would get (commits._conflict: reason
    "deleted"), not 404.

    An empty target list for a deck file that has cards is a block (its
    "confirm" is "confirm_empty") unless the body has "confirm_empty": true,
    as for save_deck. prose and mark_current are save_deck's (a saved deck
    only). A new deck is checked with the header fields
    create_deck would give it (_new_fields: Target bracket 2 by default)."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile",), ("lists", "fields", "id", "sha256", "kind", "from", "space", "confirm_empty",
                               "prose", "mark_current"))
    _flag(data, "confirm_empty")
    _flag(data, "mark_current")
    prose_problems = []
    prose = drafts._read_prose(data, prose_problems)
    deck = source = deck_id = file_changed = None
    if data.get("id") is not None:
        if data.get("kind") is not None or data.get("from") is not None or data.get("space") is not None:
            raise ApiError(400, "Send id for a saved deck, or kind or from (and space) for a new deck, not both")
        kind, slug, path = _deck_file(data["id"])
        sha = _sha(data["sha256"]) if data.get("sha256") is not None else None
        deck_id = data["id"]
        _require_cards()
        # Deleted since it was loaded: the 409 a save would get (404 if it never existed).
        deck = _parse_file(_stored(deck_id, viewer=profile).data, kind, slug, path, deck_id)
        space = deck.space
        if sha is not None:
            file_changed = sha != deck.sha256
    else:
        space = drafts._new_space(data, profile)
        _require_cards()
        kind, source, _ = _new_source(data)
    draft = drafts._read_draft(data, kind, deck, source, space)
    if deck is None:
        if draft.lists["target"] is None:
            draft.lists["target"] = decks.clean_sections(source)      # as create_deck would start it
        draft.fields = _new_fields(draft, kind, profile, space)
    # A dry run: anyone may check a draft of any deck ("Try a change"); save and create check permissions.
    bracket = _rule_warnings(draft, deck)
    target, owned = _final(draft, deck)
    changes = {"decklist": deck is None and bool(target), "fields": sorted(draft.fields) if deck is None else []}
    if deck is None and (prose or prose_problems or data.get("mark_current")):
        raise ApiError(400, "A new deck's write-up is written after it's created: send prose and mark_current "
                            "with a saved deck's id")
    if deck is not None:
        blocked = bool(draft.blocks)
        trial = decks.parse_deck(deck.text.encode("utf-8"), deck.slug, deck.kind, deck.path, deck.space)
        try:
            changes = decks.apply_edit(trial, draft.lists["target"], draft.lists["owned"], draft.fields,
                                       bracket_names=_bracket_names(), considering=draft.lists["considering"])
        except ValueError as e:
            if not blocked:
                draft.block(f"{str(e)[:1].upper()}{str(e)[1:]}")
        else:
            # The write-up as a save would write it: saving._with_prose's refusals are blocks here.
            if prose and not draft.blocks:
                from .saving import _with_prose
                if data.get("mark_current"):
                    trial.changed_on = None
                try:
                    _with_prose(decks.render_deck_file(trial), prose, trial, deck.slug, deck.kind, deck.path)
                except ApiError as e:
                    draft.block(e.message, field="prose")
                except (decks.DeckFileError, ValueError):
                    pass                    # the save says why
        for problem in prose_problems:
            draft.block(problem, field="prose")
    # A blocked line or field is left out of the lists and fields read, but
    # it's still a change the page has made (once fixed, the save makes it).
    if any(b["list"] in ("target", "owned") for b in draft.blocks):
        changes["decklist"] = True
    if any(b["list"] == "considering" for b in draft.blocks):
        changes["considering"] = True
    changes["fields"] = sorted(set(changes["fields"]) | {b["field"] for b in draft.blocks if b["field"] and b["field"] != "prose"})
    # The write-up: what a save would change in it (prose sections that read differently, or the
    # "Decklist changed" line taken off).
    current = drafts.prose_of(deck.text) if deck is not None else {}
    changes["prose"] = sorted(key for key, text in prose.items() if (current.get(key) or "") != text)
    changes["marker"] = bool(deck is not None and data.get("mark_current") and deck.changed_on)
    warnings = []
    lines = {"target": _lines_json(target, warnings), "owned": _lines_json(owned, warnings)}
    if deck is not None:
        considering = draft.lists["considering"]
        if considering is None:
            considering = deck.considering or []
        lines["considering"] = _lines_json({"Considering": considering}, warnings)["Considering"]
    # Only a pool this request may see (guard.sees_inventory): the draft's list is the page's,
    # so comparing it with another space's pool would count any cards there (owned, missing,
    # on the way, in use) for whoever pastes them. Otherwise owned and availability are None.
    p = _load_pool(warnings, space) if guard.sees_inventory(space) else None
    if deck is not None:
        # The pool names a deck by its id (decks.list_decks' source).
        warnings = _without_own_built_warning(warnings, deck_id)
    preview = None
    availability = {"target": None, "owned": None}
    if p is not None:
        preview = _owned_json(pool.compare(target, p, pool.self_ids(deck_id) if deck_id else ()), p)
        availability["target"] = preview
        if owned is not None:
            availability["owned"] = _owned_json(pool.compare(owned, p, pool.self_ids(deck_id) if deck_id else ()), p)
    shown, about = _warnings_json(draft.warnings + warnings, draft.about)
    return {"ok": not draft.blocks, "blocks": draft.blocks, "warnings": shown, "warning_cards": about,
            "lists": lines, "counts": {"target": _counts(target), "owned": _counts(owned)},
            "bracket": bracket, "brackets": _brackets() if kind == "commander" else [],
            "owned": preview, "availability": availability, "changes": changes, "file_changed": file_changed}


# ---- the editor's card finder

FIND_TYPES = ("creature", "instant", "sorcery", "artifact", "enchantment", "planeswalker", "land", "battle")
FIND_LIMIT = (12, 60)           # default and largest number of cards in one answer
FIND_NAMES = 100000             # names the name search looks through before the filters (all of them)


def _find_int(value, name, default, low, high):
    if value in (None, ""):
        return default
    if not (isinstance(value, str) and value.isdigit() and low <= int(value) <= high):
        raise ApiError(400, f"{name} must be a whole number from {low} to {high}")
    return int(value)


FIND_TERMS = {"o": "o", "oracle": "o", "t": "t", "type": "t"}     # Scryfall's keys the finder knows (E2-S25)
# A term: a key, a colon and a value, quoted ("o:\"draw a card\"", a quote left open running to the end, as
# while it's typed) or up to the next space; it starts the text or follows a space.
_TERM_RE = re.compile(r'(?<!\S)([A-Za-z]+):("[^"]*"?|\S*)')
_CURLY_DOUBLE = str.maketrans({"\u201c": '"', "\u201d": '"', "\u201e": '"'})   # phones' quotes


def _find_terms(q):
    """The finder's text split into the name words and the Scryfall-style terms (E2-S25): o: (or oracle:)
    for rules text, t: (or type:) for the type line, each a word or a quoted phrase, all of them to match.
    Returns (the name text, [(key "o" or "t", the folded value)]); a term with nothing after its colon (still
    being typed) counts for nothing. A colon after any other word is a term the finder doesn't know: an
    ApiError 400 naming it, unless the text with it is a card name's ("Circle of Protection: Red"), when
    it stays name text."""
    q = q.translate(_CURLY_DOUBLE)
    terms, rest, unknown = [], [], None
    last = 0
    for m in _TERM_RE.finditer(q):
        key = FIND_TERMS.get(m.group(1).lower())
        if key is None:
            unknown = unknown or m.group(0)
            continue
        rest.append(q[last:m.start()])
        last = m.end()
        value = cards.fold(m.group(2).strip('"'))
        if value:
            terms.append((key, value))
    rest.append(q[last:])
    name = " ".join("".join(rest).split())
    if unknown and not cards.search_names(name, 1):
        raise ApiError(400, f"The search doesn't know the term {unknown}. It knows o: for rules text and t: "
                            "for the type line, such as o:treasure t:creature or o:\"draw a card\".",
                       reason="term", term=unknown)
    return name, terms


def _term_fits(card, terms):
    """Whether a card matches every term (_find_terms): t: in its type line (every face's), o: in its rules
    text (every face's), loosely (cards.fold) and anywhere in it, as Scryfall matches them ("t:legend" finds
    Legendary). A ~ in an o: term stands for the card's own name, as on Scryfall ("o:\"~ deals\"")."""
    if not terms:
        return True
    faces = card.get("faces") or []
    types = cards.fold(" // ".join(f.get("type_line", "") for f in faces) if faces else card["type_line"])
    text = cards.fold(card.get("oracle_text") or "")
    named = None
    for key, value in terms:
        if key == "t":
            if value not in types:
                return False
            continue
        if "~" in value:
            if named is None:
                named = text
                for own in sorted({card["name"], *(f.get("name", "") for f in faces)} - {""}, key=len,
                                  reverse=True):
                    named = named.replace(cards.fold(own), "~")
            if value not in named:
                return False
        elif value not in text:
            return False
    return True


def _fits(card, colors, type_, mv, terms=()):
    """Whether a card passes the finder's filters: its colour identity within colors (a set of WUBRG letters;
    None: any; colourless always fits), its front face's type line naming type_, its mana value mv (7:
    7 or more) and every rules-text and type-line term (_term_fits)."""
    if card is None:
        return False
    if colors is not None and not set(card["color_identity"]) <= colors:
        return False
    if type_ and type_ not in card["type_line"].split(" // ")[0].lower().split():
        return False
    if mv is not None and (card["cmc"] < 7 if mv == 7 else card["cmc"] != mv):
        return False
    return _term_fits(card, terms)


def _name_rank(name, q):
    """How well a card name matches the typed text, lower first: 0 the name itself, 1 the text as a whole
    word ("bolt" in Lightning Bolt and in Bolt Bend), 2 anything else search_names found."""
    folded, key = cards.fold(name), cards.fold(q)
    if folded == key:
        return 0
    return 1 if re.search(rf"(?<![\w']){re.escape(key)}(?![\w'])", folded) else 2


def find_cards(q=None, scope=None, colors=None, type=None, mv=None, deck_id=None, space=None, limit=None,
               page=None):
    """GET /api/deck/find?q=&scope=all|owned&colors=&type=&mv=&id=|space=&limit=&page=: the editor's card
    finder.

    q may hold Scryfall-style terms besides the name words (_find_terms: o: rules text, t: type line, all of
    them to match, E2-S25); the name search and "did you mean" use only the name words, and a term the
    finder doesn't know is a 400 naming it (with reason "term" and the term).

    scope "all" (the default) searches every paper card's name (cards.search_names), keeps the ones that pass
    the filters, and puts the name typed first, then the deck's space's cards (owned or on the way), then
    the names with the text as a whole word ("bolt": Lightning Bolt before Boltwing Marauder), each group
    most-printed first (a stand-in for how much a card is played). With no q, the filters browse every paper
    card the same way (nothing without a filter either); did_you_mean, as /api/cards/search has it, comes
    only when no name is the text itself. scope "owned" lists the space's pool ("My collection"): only cards
    with a copy free for this deck (owned, on the way included, less the copies other built decks and intact
    products hold; the deck's own built copies count as free), named with every word of q, sorted by name;
    basic lands are left out. It's 403 for a space whose inventory the visitor may not see
    (guard.require_sees_inventory), as the Collection page is. colors (WUBRG letters) keeps cards whose
    colour identity is within them, type one of FIND_TYPES, mv a mana value 0-6, or 7 for 7 or more. The
    space is the deck's (id), else space (home by default); an id of a deck the visitor may not see
    (guard.sees_deck) counts as no id at all (E10-S29).

    Returns {"cards": [card (_card_json) + "default" (the printing a new line gets, _default_printing; None
    for basic lands), "have" {"owned", "on_the_way"} (copies of any printing in the space, all zero for a
    visitor who may not see its inventory), "free" (scope owned only), "aud" (cards.price_aud's estimate
    of the cheapest paper printing, or None)], "total", "page", "pages", "did_you_mean", "price_date",
    "rate", "rate_date"}."""
    from .collection import space_param
    q = (q or "").strip()
    if len(q) > MAX_SEARCH_TEXT or _CONTROL_RE.search(q):
        raise ApiError(400, f"q must be at most {MAX_SEARCH_TEXT} characters, with no control characters")
    scope = scope or "all"
    if scope not in ("all", "owned"):
        raise ApiError(400, "scope must be all or owned")
    colors = colors or ""
    if not (isinstance(colors, str) and re.fullmatch(r"[WUBRG]{0,5}", colors) and len(set(colors)) == len(colors)):
        raise ApiError(400, "colors must be some of the letters W, U, B, R and G")
    type_ = (type or "").lower()
    if type_ and type_ not in FIND_TYPES:
        raise ApiError(400, f"type must be one of {', '.join(FIND_TYPES)}")
    mv = _find_int(mv, "mv", None, 0, 7)
    n = _find_int(limit, "limit", FIND_LIMIT[0], 1, FIND_LIMIT[1])
    page = _find_int(page, "page", 1, 1, 1000)
    if deck_id is not None:
        check_deck_id(deck_id)
        if not guard.sees_deck(deck_id):
            # A deck the viewer may not see counts for nothing (E10-S29): not its space, and not
            # its copies (pool.self_ids), which would tell how many it holds.
            deck_id = None
    if deck_id is not None:
        space = spaces.split_deck_id(deck_id)[0]
    elif space in (None, ""):
        space = space_param(space)
    else:
        # A space named outright answers as a missing one does unless the viewer sees its
        # inventory (E10-S29): never a 200 with no counts that tells it exists.
        space = space_param(space)
        guard.require_sees_inventory(space)
    wanted = set(colors) if colors else None
    _require_cards()
    q, terms = _find_terms(q)
    counts = drafts._visible_counts(space)

    def have_of(card):
        have = {"owned": 0, "on_the_way": 0}
        for set_code, number in card["printings"]:
            for finish in LINE_FINISHES:
                for key, qty in (counts.get((set_code, number, finish)) or {}).items():
                    have[key] += qty
        return have

    did_you_mean, free = [], {}
    if scope == "owned":
        guard.require_sees_inventory(space)
        p = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        spares = pool.free_copies(p, pool.self_ids(deck_id) if deck_id else ())
        words = q.casefold().split()
        names = []
        for name in sorted(spares, key=str.casefold):
            if not all(w in name.casefold() for w in words):
                continue
            spare = spares[name]
            if _fits(cards.card(name), wanted, type_, mv, terms):
                names.append(name)
                free[name] = spare
    elif q or terms or wanted is not None or type_ or mv is not None:
        found = cards.search_names(q, FIND_NAMES) if q else cards.card_names()
        if q and len(found) < DID_YOU_MEAN and not any(cards.fold(name) == cards.fold(q) for name in found):
            did_you_mean = [name for name in cards.close_names(q, len(found) + DID_YOU_MEAN)
                            if name not in found][:DID_YOU_MEAN]
        names = [name for name in found if _fits(cards.card(name), wanted, type_, mv, terms)]
        # The space's cards (any printing owned or on the way), from its counts: no card is looked through.
        space_names = set()
        for (set_code, number, _), have in counts.items():
            printed = cards.printing(set_code, number) if any(have.values()) else None
            exact = printed and cards.resolve(printed["name"])
            if exact:
                space_names.add(exact)
        order = {name: i for i, name in enumerate(found)}
        names.sort(key=lambda name: (_name_rank(name, q) != 0 if q else False, name not in space_names,
                                     _name_rank(name, q) if q else 0, -len(cards.card(name)["printings"]),
                                     order[name]))
    else:
        names = []
    shown = names[(page - 1) * n:page * n]
    out = []
    for name in shown:
        card = cards.card(name)
        chosen = None if decks.is_basic_land(name) else _default_printing(name, counts)
        printing = cards.printing(chosen["set"], chosen["number"]) if chosen else None
        price = cards.price_aud(name)
        entry = dict(_card_json(card, printing or _shown_printing(card)), default=chosen, have=have_of(card),
                     aud=price.aud if price else None)
        if scope == "owned":
            entry["free"] = free[name]
        out.append(entry)
    try:
        rate, rate_date = cards.usd_to_aud()
        price_date = cards.price_date()
    except RuntimeError:
        rate = rate_date = price_date = None
    return {"cards": out, "total": len(names), "page": page, "pages": max(1, -(-len(names) // n)),
            "did_you_mean": did_you_mean, "price_date": price_date, "rate": rate, "rate_date": rate_date}
