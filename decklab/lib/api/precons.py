"""The Collection page's "Add a precon": a published precon's cards added to a
space's collection and a built deck made from its list, in one go
(PLAN.md, "Adding a precon"). Imported when first needed, by
feature_routes.dispatch.

    GET  /api/precons?q=<words>                    precons_view(): paper decks MTGJSON lists, newest first
    GET  /api/precons/preview?file=<f>&space=<id>  precon_preview(): what adding it would do
    POST /api/precons/add                          add_precon(body): add its cards, then make its deck

The lists come from MTGJSON (lib/precons.py), most from Wizards' published
lists. A deck is matched card by card to Scryfall with the Collection page's
import rules (collection_edit.read_upload): its own printing and finish,
condition and language left blank (AGENTS.md: never assumed), plain basics
left out of the collection (kept when MTGJSON says they're full art). A
display commander that's a real card (the foil-etched copy in precons from
2022 to mid-2024) goes into the collection too, but not the deck; an oversized or
thick-stock one is only counted. A precon with any card that can't be
matched (a set Scryfall doesn't have in full yet, or a list MTGJSON hasn't
finished), or whose list breaks a rule every new deck is checked against
(drafts._read_draft: a gold-bordered printing, more than 99 copies on a
line), can't be added: the preview says which.

Adding one is one change (the inventory's precon.add: the collection's
import and the deck's creation together, so either both are saved or
neither is), as Activity shows it:

    import 66 cards into User4's collection from the Keen Engineering precon; new deck Sai: Keen
    Engineering   (by Matt)

The generated rows are kept as one of the space's raw imports
(<date>-<set>-<name>.csv, like any import), and the deck is made with
status built and the list as printed (plain basics as "34 Island", with no
printing). Everything is checked before anything is saved: collection.edit
and deck.create on the space, the collection's sha256 (409 when it
changed), a title whose deck name is free (409), and a deck draft with no
blocks.

A person's space has no products (AGENTS.md, "Spaces"), so a precon there is
cards and a deck. At home it's the same: products bought through a recorded
order still arrive through the Receipts page instead. The precon's token
cards are listed in the preview and in the deck's Notes, never added to
tokens.csv: they need checking by hand first (the Tokens page).

plan_add() is everything an add checks and works out, without saving: the
page's add_precon and the command line's `python -m decklab.db collection
add-precon` (decklab/db/inv_collection.py, E10-S36, which passes no profile:
the command line writes every space) both save what it plans.
"""
import csv
import io
from datetime import date

from decklab.lib import cards, decks, inventory, precons
from decklab.lib.inventory import ops_collection as ops
from decklab.lib.inventory import rules

from . import collection_edit as ce
from . import common, drafts, guard, saving
from .card_lookup import _pickable
from .carddata import _require_cards
from .collection import space_param
from .common import ApiError, _keys, _parse_body, _public
from .settings import _writer

MAX_QUERY = 100
SEARCH_LIMIT = 40


def _added_on():
    """Today's date for the deck's Notes (the tests fix it)."""
    return date.today().isoformat()


def _entry(file):
    if not isinstance(file, str) or not precons.FILE_RE.fullmatch(file):
        raise ApiError(400, "file must be a deck's file name from /api/precons")
    try:
        entry = precons.find(file)
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    if entry is None:
        raise ApiError(404, f"MTGJSON lists no paper deck called {file}")
    return entry


def precons_view(q=None):
    """GET /api/precons?q=<words>: {"date" (MTGJSON's build date), "decks"
    [{"file", "name", "code", "set_name" (MTGJSON's, or ""), "type",
    "released", "source"}], "more" (more match than are shown)}. 502 when
    MTGJSON can't be reached and nothing is cached."""
    if q is not None and (not isinstance(q, str) or len(q) > MAX_QUERY):
        raise ApiError(400, f"q must be at most {MAX_QUERY} characters")
    try:
        found, more, built = precons.search(q, SEARCH_LIMIT)
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    return {"date": built, "decks": found, "more": more}


def _short(name):
    """A commander's name as a deck title starts with it: "Sai" for "Sai, Master Thopterist"."""
    return name.split(" // ")[0].split(",")[0].strip()


def _build(entry, space):
    """Everything a preview shows and an add writes, for a listed deck."""
    _require_cards()
    try:
        data = precons.deck(entry["file"])
    except precons.PreconError as e:
        raise ApiError(502, _public(e)) from None
    except LookupError:
        raise ApiError(404, f"MTGJSON lists no paper deck called {entry['file']}") from None
    read = precons.cards_of(data)
    lines, left_out = read["lines"], dict(read["left_out"])
    has_commander = any(line["section"] == "Commander" for line in lines)
    kind = "commander" if entry["type"] == "Commander Deck" and has_commander else "casual"
    note = f"{entry['name']} precon ({entry['set_name'] or entry['code'].upper()})"
    # A display commander is a card for the collection when it's one to play with, else only counted.
    display = [line for line in read["display"] if _pickable(cards.printing(line["set"], line["number"]))]
    shown = sum(line["count"] for line in read["display"] if line not in display)
    if shown:
        left_out["display commander"] = shown
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=ce.FIELDS, lineterminator="\n")
    writer.writeheader()
    for line, extra in [(line, "") for line in lines] + [(line, "; display commander") for line in display]:
        basic = line["name"] in rules.BASIC_LANDS
        writer.writerow({"name": line["name"], "set": line["set"], "collector_number": line["number"],
                         "finish": line["finish"], "quantity": line["count"], "condition": "", "language": "",
                         "notes": note + extra + ("; full art" if basic and line["full_art"] else "")})
    text = out.getvalue()
    existing, sha = ce._read(space)
    _, rows, problems, dropped = ce.read_upload(text, {rules.ident(r) for r in existing})
    problems = [{"line": None, "message": m} for m in read["problems"]] + problems
    good = [r for r in rows if not r["problem"]]

    sections = {}
    for line in lines:
        p = cards.printing(line["set"], line["number"])
        name = cards.resolve(p["name"]) if p else None
        name = name or cards.resolve(line["name"]) or line["name"]
        section = line["section"] if kind == "commander" or line["section"] != "Commander" else "Deck"
        row = {"name": name, "finish": line["finish"], "notes": "; full art" if line["full_art"] else ""}
        if rules.ordinary_basic(row):
            card = {"name": name, "qty": line["count"]}
        else:
            card = {"name": name, "qty": line["count"], "set": line["set"], "number": line["number"],
                    "finish": line["finish"]}
        same = next((c for c in sections.setdefault(section, []) if c.keys() == card.keys()
                     and all(c[k] == card[k] for k in card if k != "qty")), None)
        if same:
            same["qty"] += card["qty"]
        else:
            sections[section].append(card)
    sections = {s: sections[s] for s in decks.SECTIONS if sections.get(s)}
    # The checks every new deck's list gets (plan_new_deck's), so a list the add would refuse isn't offered.
    draft = drafts._read_draft({"lists": {"target": sections}}, kind, space=space)
    deck_problems = [{"line": None, "message": b["problem"]} for b in draft.blocks]

    commanders = [c["name"] for c in sections.get("Commander", [])]
    title = f"{' & '.join(_short(n) for n in commanders)}: {entry['name']}" if commanders else entry["name"]
    return {"entry": entry, "kind": kind, "title": title[:saving.MAX_TITLE], "text": text, "rows": rows,
            "good": good, "problems": problems, "deck_problems": deck_problems, "dropped": dropped,
            "sections": sections, "left_out": left_out, "tokens": read["tokens"], "sha256": sha,
            "csv_name": f"{entry['code']}-{ce._safe_stem(entry['name'])}.csv"}


def _may_add(space):
    profile = guard.viewer()
    return guard.sees_deck({"space": space}, profile) and guard.allowed(profile, "collection.edit", space) and \
        guard.allowed(profile, "deck.create", {"space": space, "player": None})


def _lists_with_cards(sections):
    """The preview's lists with each line's "card" (card_lookup._card_json, with its own printing's picture
    when it names a printing of that card, else the card's usual one; None for a name Scryfall doesn't know), for the
    page's pictures and card viewer. Copies: the sections themselves are what an add saves."""
    from .card_lookup import _card_json, _shown_printing
    out = {}
    for section, lines in sections.items():
        out[section] = []
        for line in lines:
            exact = cards.resolve(line["name"])
            card = cards.card(exact) if exact else None
            shown = None
            if card is not None:
                p = cards.printing(line["set"], line["number"]) if line.get("set") and line.get("number") else None
                # Only a printing of this card: a wrong or shifted collector number in the list would
                # otherwise show another card's picture under this name (as collection_edit._pictures checks).
                printed = cards.printing_card(line["set"], line["number"]) if p else None
                if not printed or printed["name"] != card["name"]:
                    p = None
                shown = _card_json(card, p or _shown_printing(card))
            out[section].append({**line, "card": shown})
    return out


def precon_preview(file=None, space=None):
    """GET /api/precons/preview?file=<f>&space=<id>: what adding it would do,
    without changing anything. {"deck" (its /api/precons entry), "kind"
    (commander or casual), "title" (a suggested one), "exists" (the deck id
    already using that title's file name, or None; always None in a space
    whose decks the visitor can't see, E10-S30), "lists" ({section:
    [{"qty", "name", "set"?, "number"?, "finish"?, "card"}]}: card is the
    card's data with that printing's picture, _lists_with_cards), "counts" ({section:
    cards}), "rows" (the collection rows, as an import preview's, with
    problems), "problems" (cards that can't be matched), "deck_problems"
    (what stops its list being made into a deck), "adds" {"rows", "cards"},
    "dropped_basics", "left_out" ({"display commander": 1, ...}: cards not
    added), "tokens" ([{"name", "count"}], the token cards it comes with),
    "ready" (neither kind of problem), "sha256" (the collection's now),
    "editable" (may this visitor add it here: never in a space whose decks
    it can't see)}. 403 for a space whose
    inventory the visitor may not see (guard.require_sees_inventory), and for
    one whose collection it may not change (collection.edit: E10-S29, so an
    admin can't preview a precon in a member's space and no deck id there is
    probed; guard.require_space_write)."""
    space = space_param(space)
    guard.require_space_write(guard.viewer(), "collection.edit", space)
    built = _build(_entry(file), space)
    slug = decks.title_slug(built["title"])
    return {"deck": built["entry"], "kind": built["kind"], "title": built["title"],
            "exists": (decks.existing_deck_id(slug, space)
                       if decks.valid_slug(slug) and guard.sees_deck({"space": space}) else None),
            "lists": _lists_with_cards(built["sections"]),
            "counts": {s: sum(c["qty"] for c in lines) for s, lines in built["sections"].items()},
            "rows": built["rows"], "problems": built["problems"], "deck_problems": built["deck_problems"],
            "adds": {"rows": len(built["good"]), "cards": sum(int(r["quantity"]) for r in built["good"])},
            "dropped_basics": built["dropped"], "left_out": built["left_out"], "tokens": built["tokens"],
            "ready": not built["problems"] and not built["deck_problems"], "sha256": built["sha256"],
            "editable": _may_add(space)}


def _notes(built, author):
    entry = built["entry"]
    released = f", released {entry['released']}" if entry["released"] else ""
    source = entry["source"]
    text = (f"Added in Deck Lab on {_added_on()} by {author} from the {entry['name']} precon "
            f"({entry['set_name'] or entry['code'].upper()}, {entry['type']}{released}). The list is MTGJSON's"
            + ((f", from Wizards' published list: {source}" if precons.from_wizards(source) else f", from {source}")
               if source else "") + ".")
    if built["tokens"]:
        text += (" It comes with these token cards (MTGJSON's list; check the cards themselves before "
                 "recording them on the Tokens page): "
                 + ", ".join(f"{t['count']} {t['name']}" for t in built["tokens"]) + ".")
    return text


def add_precon(body):
    """POST /api/precons/add {"profile", "file", "title", "sha256", "space"?,
    "fields"?}: add the precon's cards to the space's collection and make
    its deck (title; fields as POST /api/decks takes them, status built by
    default), in one change (precon.add). sha256 is the collection's, as the
    preview gave it. Returns {"collection": import/apply's answer without
    its rows, or None when only plain basics were left to add,
    "deck": POST /api/decks's answer}. 400 with "problems" for a precon that
    can't be added as it is; 409 for a changed collection ({error, sha256,
    rows}) or a taken title ({error, conflict}); 403 without collection.edit
    and deck.create. Nothing is saved when anything is refused."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "file", "title", "sha256"), ("space", "fields"))
    space = space_param(data.get("space"))
    guard.require_space_write(profile, "collection.edit", space)
    sha = ce._request_sha(data["sha256"])
    fields = data.get("fields")
    if fields is not None and not isinstance(fields, dict):
        raise ApiError(400, "fields must be a JSON object")
    made = plan_add(space, data["file"], data["title"], fields, profile, profile["name"], sha=sha)
    try:
        after, summary = saving.apply_op(made["op"], profile, made["message"], made["refused"])
    except ValueError as e:     # the files backend: an upload's name already taken on disk (nothing saved)
        raise ApiError(409, _public(e)) from None
    added = None
    if made["built"]["good"]:
        _, now = ce._view(after.collection(space))
        counts = summary.counts
        added = {"ok": True, "sha256": now, "added": {"rows": counts["added_rows"], "cards": counts["cards"]},
                 "skipped": 0, "raw": summary.extra["raw"][0]}
    return {"collection": added,
            "deck": saving.created_answer(made["plan"], made["deck_id"], made["table"], made["text"])}


def plan_add(space, file, title, fields, profile, author, sha=None):
    """Everything adding a precon checks and works out before anything is saved, for the page's
    add_precon and the command line's collection add-precon (decklab/db/inv_collection.py):
    {"built" (_build's), "plan" (saving.plan_new_deck's), "whose", "deck_id", "table", "text"
    (the deck's, its table worked out against the collection as the import leaves it), "op"
    (the precon.add operation to apply), "message" (the page's words for the change),
    "refused" (_precon_refused, for saving.apply_op)}. profile: whose rights the checks are
    made with (None: a script naming nobody, such as the command line, which may do
    everything); title: the deck's (None: the preview's suggestion); author: the name in the
    deck's Notes ("by Matt"); sha: the collection's
    sha256 the add is made against (None: as it is now). ApiError for a refusal: a precon that
    can't be added as it is (400 with "problems"), a taken title (409 with "conflict", naming
    the deck that has it), a changed collection (409). Nothing is written."""
    built = _build(_entry(file), space)
    name = built["entry"]["name"]
    if built["problems"]:
        raise ApiError(400, f"{name} can't be added yet: Deck Lab can't match "
                            f"{len(built['problems'])} of its cards to Scryfall's data.", problems=built["problems"])
    if built["deck_problems"]:
        raise ApiError(400, f"{name} can't be added: its list can't be made into a deck "
                            f"({built['deck_problems'][0]['message']}).", problems=built["deck_problems"])
    request = {"title": built["title"] if title is None else title, "kind": built["kind"], "space": space,
               "fields": {"status": "built", **(fields or {})}, "lists": {"target": built["sections"]}}
    plan = saving.plan_new_deck(request, profile, notes=_notes(built, author))
    saving.check_free(plan)
    whose = ce._whose(space)
    record = {"filename": built["csv_name"], "text": built["text"], "format": "collection",
              "good": built["good"], "problems": [], "dropped_basics": built["dropped"]}
    collection = ce.import_params(space, built["sha256"] if sha is None else sha, record,
                                  message=f"import {{cards}} cards into {whose} from the {name} precon")
    with common.state_errors():
        cards_words = ops.message(inventory.current(), "collection.import", collection)
    refused = _precon_refused(space, whose, plan)
    # The deck's table counts the cards this precon adds: worked out against the collection as
    # the import would leave it (nothing is written; precon.add still saves both as one change).
    if built["good"]:
        try:
            merged, _ = inventory.preview(inventory.Op("collection.import", collection), refresh=False)
        except (inventory.Invalid, inventory.Conflict, inventory.Unavailable) as e:    # as precon.add would be
            raise (refused(e) or saving._refused(e)) from None
        except ValueError as e:
            raise ApiError(409, _public(e)) from None
        with inventory.pinned(merged):
            deck_id, table, text = saving.new_deck_text(plan)
    else:
        deck_id, table, text = saving.new_deck_text(plan)
    op = inventory.Op("precon.add", {"space": space, "kind": plan["kind"], "slug": plan["slug"], "text": text,
                                     "collection": collection, "owners": guard.accessory_owners(profile)})
    message = (f"{cards_words}; new deck {plan['title']}" if built["good"]
               else f"add the {name} precon's deck {plan['title']} to {whose}")
    return {"built": built, "plan": plan, "whose": whose, "deck_id": deck_id, "table": table, "text": text,
            "op": op, "message": message, "refused": refused}


def _precon_refused(space, whose, plan):
    """saving.apply_op's refused for precon.add: the collection's refusals as the Collection
    page answers them (a changed collection 409 with its rows, a full imports folder 413), a
    deck name taken meanwhile 409."""
    taken = saving.new_deck_refused(plan)

    def refused(e):
        if isinstance(e, ops.Stale):
            return ce._stale(space)
        if isinstance(e, ops.Missing):
            rows, now = ce._read(space, fresh=True)
            return ApiError(409, str(e), sha256=now, rows=ce._rows_json(rows))
        if isinstance(e, ops.TooLarge):
            return ApiError(413, f"The imports folder of {whose} holds {ce._mb(e.held)}, and this precon's list "
                                 f"({ce._mb(e.size)}) would take it over its limit of {e.limit // (1024 * 1024)} MB: "
                                 f"ask an admin to tidy {ops.paths.imports_dir(space)} first.")
        return taken(e)
    return refused
