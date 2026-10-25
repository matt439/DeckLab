"""Plans for assembling several physical decks from one card pool,
with the token cards each deck would grab (lib/tokens)."""
from collections import Counter
import csv
import traceback

from decklab.lib import accessories, cards, decks, inventory, pool, spaces, tokens
from . import common
from .assembly_ticks import token_packing_keys
from .carddata import _require_cards
from .common import ApiError, _keys, _parse_body, _public, _scrub
from .library import _deck_sections
from . import assembly_sections
from .opponents import add_usual_opponents, usual_opponent_ids

MAX_DECKS = 12


TOKEN_UNAVAILABLE = "Token data is being rebuilt; refresh in a minute."
TOKEN_FAILED = "Tokens couldn't be worked out; the server log has the details."
TOKEN_NOTE = tokens.NOTE + " Packing ticks don't reserve or change inventory."
TOKEN_PLAN_NOTE = ("Both decks can use these cards. One card shows one face at a time; "
                   "at home keep shared tokens in one pile on the table.")


def _deck_tokens(deck_id, version, sections, inv, inc, held=None):
    """tokens.cached_deck_tokens for one list, as the deck page and the plan
    show it: {"unavailable": ...} while the card index is missing or being
    rebuilt, {"error": ...} (logged) when anything else goes wrong. held is
    what other built decks pack (tokens.reserve.held_elsewhere)."""
    try:
        if held:
            return tokens.cached_deck_tokens(deck_id, version, sections, inv, inc, held)
        return tokens.cached_deck_tokens(deck_id, version, sections, inv, inc)
    except RuntimeError:
        return {"unavailable": TOKEN_UNAVAILABLE}
    except Exception:           # the page still shows; the log has the details
        common._log(f"The tokens of {deck_id} ({version}) couldn't be worked out:\n" + traceback.format_exc())
        return {"error": TOKEN_FAILED}


def held_tokens(inv, space=spaces.HOME):
    """tokens.reserve.holds of a space's built decks, or {} (logged) when they can't be worked out:
    the plan and pages then show every token card as free, as before reservations."""
    try:
        return tokens.reserve.holds(inv, space)
    except Exception:
        common._log("The packed token cards couldn't be worked out:\n" + traceback.format_exc())
        return {}


def _token_plan(participants, inv):
    """[{row, front, back, quantity, wanted_by: [{deck, title, token, side}]}]:
    the owned token cards that two or more of the selected decks would grab
    (a ready or check need's cards, or a differing need's first stand-in, as
    the plan's ticks say), in tokens.csv order. Nothing is shared out."""
    wanted = {}
    for item in participants:
        result = item.get("tokens") or {}
        for need in result.get("needs", []):
            if need["state"] in ("ready", "check"):
                grabbed = need["cards"]
            elif need["state"] == "differs":
                grabbed = [s for s in need["stand_ins"] if not s.get("close")][:1]
            else:
                grabbed = []
            for card in grabbed:
                wanted.setdefault(card["row"], []).append({"deck": item["id"], "title": item["title"],
                                                           "token": need["name"], "side": card["side"]})
    plan = []
    for index in sorted(wanted):
        if len({w["deck"] for w in wanted[index]}) < 2:
            continue
        row = inv.rows[index]
        plan.append({"row": index, "front": row["front"], "back": row["back"],
                     "quantity": int(row["quantity"]), "wanted_by": wanted[index]})
    return plan


def _sleeve_notes(participants):
    """[{"sleeves": label, "decks": [{"id", "title"}], "note"}]: the selected decks (and products)
    that are in one accessory's sleeves, one entry per design two or more different holders share. One
    design may sleeve several decks, so this is a note for the table, never a block: their cards look
    alike from the back. A holder is counted once (its kit's holder and title), so two decks of one
    intact product, which are in its one design of sleeves anyway, are one entry and never a note on
    their own. Only decks whose kit the viewer sees count (their "kit" isn't None)."""
    shared = {}
    for item in participants:
        kit = item.get("kit") or {}
        sleeves = kit.get("sleeves")
        if sleeves and sleeves.get("state") == "linked":
            entry = shared.setdefault(sleeves["id"], {"sleeves": sleeves["label"], "decks": []})
            holder = kit.get("holder") or item["id"]
            if all(d["id"] != holder for d in entry["decks"]):
                entry["decks"].append({"id": holder, "title": kit.get("title") or item["title"]})
    out = []
    for entry in shared.values():
        if len(entry["decks"]) < 2:
            continue
        titles = accessories._and(d["title"] for d in entry["decks"])
        entry["note"] = (f"{titles} are {'both' if len(entry['decks']) == 2 else 'all'} in {entry['sleeves']} "
                         f"sleeves: their cards look the same from the back, so keep each deck's cards together.")
        out.append(entry)
    return out


def _kit(summary, sections, inv, usage, owners=None):
    """(sleeves, kit) for a participant: accessories.kit() for the selected
    version's list (a product's for the whole product, as its sleeves cover
    every deck in it; None when it can't be worked out) and its sleeves as
    words: the accessory's label, older free text as written, or "Not
    recorded" ("Not recorded for this product")."""
    missing = "Not recorded" if summary["id"].startswith(("casual/", "commander/")) \
        else "Not recorded for this product"
    try:
        from .accessories import read_kit
        kit = read_kit(summary["id"], sections, inv=inv, usage=usage)
    except Exception:           # the plan still works; the log has the details
        common._log("The assembly plan's accessories couldn't be worked out:\n" + traceback.format_exc())
        return missing, None
    return (kit["sleeves"]["label"] if kit["sleeves"] else missing), kit


def assembly_view(deck=None, version="target"):
    """GET /api/assembly, optionally preselect a deck and version.

    Each deck in the plan has "sleeves" (words for its sleeves), "kit"
    (accessories.kit() for the selected version; a product's covers the whole
    product) and "sleeves_need" (the kit's need; "need" is card counts),
    all three None for a visitor who may not see the deck's owner's
    accessories (guard.sees_kit). "sleeve_notes" (_sleeve_notes) says which
    selected decks share one design of sleeves: a note, not a block.

    Each deck also has "tokens": tokens.deck_tokens for the selected version
    (see _deck_tokens for when it's {"unavailable"} or {"error"}). The answer
    has "token_plan" (_token_plan: token cards two or more selected decks
    would grab) with "token_plan_note", "tokens" (every owned token card, its
    quantity an int and "key" the line it starts on in tokens.csv) with
    "token_note", and "token_problems" (tokens.csv rows that can't be read;
    the plan still works without them).

    "cards" is {name: card JSON} for the cards the plan names (_plan_cards),
    for its pictures and the card viewer. Each deck's "finishes" maps exact
    card names to [{finish, quantity}] from that selected list, including
    basics. These describe the list, not physical copies allocated from
    storage, other decks or returns; allocation remains by card name.

    The plan is the home pool's: 403 for anyone outside the home
    (guard.require_sees_home_records), here and in assembly_preview."""
    from . import guard
    guard.require_sees_home_records()
    _require_cards()
    try:
        # One inventory snapshot: the request's (server_http pins one per request).
        summaries = decks.list_decks()
        opponents = usual_opponent_ids(summaries)
        pairings = {deck_id: ids for deck_id, ids in opponents.items() if deck_id.startswith("pairing/") and ids}
        summaries.extend(item for item in decks.beginner_box_pairings() if item["id"] in pairings)
        add_usual_opponents(summaries, opponents)
        choices = [{key: item.get(key) for key in ("id", "title", "versions", "status", "error", "usual_opponents")}
                   for item in summaries if item.get("space", "home") == "home"]
        for choice in choices:
            choice["sideboards"] = {}
            if choice["id"].startswith(("product/", "pairing/")):
                continue
            for selected_version in choice.get("versions") or []:
                try:
                    choice["sideboards"][selected_version] = assembly_sections.sideboard_choices(
                        decks.load_deck(choice["id"], selected_version))
                except (decks.DeckFileError, decks.DeckNotFound, OSError):
                    pass
        selected = [{"id": deck, "version": version}] if deck else []
        answer = _preview(selected)
        answer["choices"] = choices
        answer["usual_opponents"] = pairings
        return answer
    except (ValueError, OSError, csv.Error) as error:
        raise ApiError(409, f"The assembly plan couldn't be read: {_public(error)}") from None


def assembly_preview(body):
    """POST /api/assembly/preview {decks:[{id,version}]}: no files are written."""
    data = _parse_body(body)
    _keys(data, ("decks",), ("profile",))
    # It writes nothing, so anyone may ask (guard.py's "run"); a profile given must be a real one.
    from . import guard
    from .settings import _writer
    profile = _writer(data) if "profile" in data else guard.viewer()
    guard.require(profile, "run")
    guard.require_sees_home_records()
    _require_cards()
    try:
        return _preview(data["decks"], profile=profile)
    except (ValueError, OSError, csv.Error) as error:
        raise ApiError(409, f"The assembly plan couldn't be read: {_public(error)}") from None


def _preview(selected, profile=False):
    if not isinstance(selected, list) or len(selected) > MAX_DECKS:
        raise ApiError(400, f"Choose up to {MAX_DECKS} decks")
    p, participants, aliases, unresolved = pool.load_pool(), [], set(), {}
    pictured = {}               # a name as a list writes it -> its first line, for the plan's pictures
    selections, recipes = [], {}
    inv = usage = None
    token_inv = tokens.read()
    token_inc, _ = tokens.incoming()
    token_holds = held_tokens(token_inv)
    from . import guard
    owners = guard.accessory_readers()
    sees = owners is None or bool(owners)
    if selected and sees:
        inv = accessories.read()
        usage = accessories.holders(inv)
    for choice in selected:
        if not isinstance(choice, dict):
            raise ApiError(400, "Each selected deck needs an id and version")
        _keys(choice, ("id", "version"), ("sideboard",))
        summary, intended = _deck_sections(choice["id"], choice["version"])
        sections = assembly_sections.recipe(choice, summary, intended)
        normalized = {"id": summary["id"], "version": choice["version"]}
        if "sideboard" in choice:
            normalized["sideboard"] = {name: qty for name, qty in sorted(choice["sideboard"].items()) if qty}
        selections.append(normalized)
        recipes[summary["id"]] = sections
        if summary.get("space", "home") != "home":
            # One plan moves cards within one collection: the home pool's (lib/spaces.py).
            raise ApiError(400, f"{summary['title']} is in a person's own collection: Build decks is for "
                                f"the home decks")
        own_ids = pool.self_ids(summary["id"])
        if aliases & own_ids:
            raise ApiError(400, "A physical deck or product half can be selected only once")
        aliases.update(own_ids)
        need = pool._count_sections(sections, summary["title"], unresolved)
        held = Counter()
        for item in p.in_use:
            if item.id in own_ids:
                held.update(item.cards)
        basics, finishes = Counter(), {}
        stored = inventory.current().deck(summary["id"])
        parsed = None
        current_basics = Counter()
        if stored is not None:
            from decklab.lib.decks import assembled
            parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
            for lines in assembled.sections(parsed).values():
                for line in lines:
                    if decks.is_basic_land(line.name):
                        current_basics[line.name] += line.quantity
        for lines in sections.values():
            for line in lines:
                pictured.setdefault(line.name, line)
                name = line.name if decks.is_basic_land(line.name) else cards.resolve(line.name)
                finishes.setdefault(name or line.name, Counter())[line.finish or ""] += line.quantity
                if name and decks.is_basic_land(name):
                    basics[name] += line.quantity
        shown = sees and guard.sees_kit(summary, owners)
        sleeves, kit = _kit(summary, sections, inv, usage, owners) if shown else (None, None)
        participants.append({"id": summary["id"], "title": summary["title"], "version": choice["version"],
                             "rename_version": stored.rename_version if stored is not None else 0,
                             "assembly_key": assembly_sections.task_key(parsed, normalized, sections),
                             "build_scope": assembly_sections.scope(sections, intended),
                             "basic_returns": [{"name": name, "quantity": qty}
                                               for name, qty in sorted((current_basics - basics).items())],
                             "sleeves": sleeves, "kit": kit, "sleeves_need": kit["need"] if kit else None,
                             "tokens": token_packing_keys(_deck_tokens(
                                 summary["id"], choice["version"], sections, token_inv, token_inc,
                                 tokens.reserve.held_elsewhere(token_holds, summary["id"])), token_inv.rows),
                             "need": need, "current": held,
                             "basics": [{"name": name, "quantity": qty}
                                        for name, qty in sorted((basics - current_basics).items())],
                             "finishes": {name: [{"finish": finish, "quantity": qty} for finish, qty in counts.items()]
                                          for name, counts in finishes.items()},
                             "steps": [], "returns": []})
    from .assembly_markers import plan_standins
    answer = plan_standins(p, participants, aliases, unresolved, profile, plan_counts)
    answer["selections"] = selections
    from .assembly_intent import project
    for item in answer["decks"]:
        item["returns"].extend(item.pop("basic_returns", []))
        item["build_scope"]["return_count"] = sum(row["quantity"] for row in item["returns"])
        stored = inventory.current().deck(item["id"])
        if stored is not None:
            parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
            intent = project(parsed, p, version=item["version"], sections=recipes[item["id"]],
                             standins=item.get("standins", {}).get("rows", []))
            item["remaining_intent"] = intent["remaining"] if intent else []
    answer["rename_versions"] = {item["id"]: item["rename_version"] for item in participants}
    answer["assembly_keys"] = {item["id"]: item["assembly_key"] for item in participants if item.get("assembly_key")}
    answer["cards"] = _plan_cards(answer, answer["decks"], pictured)
    answer["sleeve_notes"] = _sleeve_notes(participants)
    answer["token_plan"] = _token_plan(participants, token_inv)
    answer["token_plan_note"] = TOKEN_PLAN_NOTE
    answer["tokens"] = [{**row, "quantity": int(row["quantity"]), "key": str(line)}
                        for row, line in zip(token_inv.rows, token_inv.lines)]
    answer["token_note"] = TOKEN_NOTE
    answer["token_problems"] = _scrub(token_inv.problems)
    from .assembly_completion import decorate
    return decorate(answer, selections, profile)


def _plan_cards(answer, participants, pictured):
    """{name: card JSON} (card_lookup._line_json's "card") for every card the plan names (its rows,
    each deck's returns and basics), in the printing the first list naming it gives, so the packing
    plan can show pictures and open them in the card viewer. A name with no card data is left out."""
    from .card_lookup import _line_json
    by_name = {}
    for written, line in pictured.items():
        exact = cards.resolve(written) or written
        by_name.setdefault(exact, line)
        by_name.setdefault(written, line)
    names = {row["name"] for row in answer["rows"]}
    for item in participants:
        names.update(r["name"] for r in item["returns"])
        names.update(b["name"] for b in item["basics"])
        names.update(row["for"] for row in item.get("standins", {}).get("needs", []))
    out = {}
    for name in sorted(names):
        line = by_name.get(name) or decks.DeckLine(1, name)
        try:
            card = _line_json(line, "Deck", [])["card"]
            if card:
                indexed = cards.card(card["name"])
                # Lands are stored by the mana they make: rainbow lands can have no colour identity.
                card["produced_mana"] = list((indexed or {}).get("produced_mana", []))
        except Exception:       # a picture is never worth failing the plan for
            card = None
        if card:
            out[name] = card
    return out


def plan_counts(p, participants, aliases, unresolved):
    """Allocate each physical copy once, keeping existing participant copies first.

    Nonparticipants remain reserved. Released participant cards can move between
    selected decks; leftovers are returned to storage. Incoming copies can only
    cover a wait step, never make a plan ready to assemble now.
    """
    names = set()
    for participant in participants:
        names.update(participant["need"])
        names.update(participant["current"])
    rows, warnings = [], list(p.warnings)
    unknown = set(p.unresolved) | set(unresolved)
    for name in sorted(names):
        incoming = sum(qty for _, qty in p.on_the_way.get(name, []))
        owned = max(0, p.owned[name] - incoming)
        holders = [item for item in p.in_use if item.cards[name]]
        all_held = sum(item.cards[name] for item in holders)
        elsewhere = [{"id": item.id, "title": item.title, "quantity": item.cards[name]}
                     for item in holders if item.id not in aliases]
        if all_held > owned:
            warnings.append(f"{name}: built allocations need {all_held} copies but only {owned} are physically owned")
        if not cards.card(name):
            unknown.add(name)
        storage = max(0, owned - all_held)
        remaining_incoming = incoming
        released = [{"deck": item, "quantity": max(0, item["current"][name] - item["need"][name])}
                    for item in participants]
        aggregate = {"name": name, "need": 0, "owned_now": owned, "kept": 0, "from_storage": 0,
                     "transfers": [], "waiting": 0, "missing": 0, "held_elsewhere": elsewhere,
                     "incoming_from": [{"source": source, "quantity": qty}
                                       for source, qty in p.on_the_way.get(name, [])]}
        for item in participants:
            needed = item["need"][name]
            if not needed:
                continue
            keep = min(needed, item["current"][name])
            need = needed - keep
            pull = min(need, storage)
            storage -= pull
            need -= pull
            transfers = []
            for donor in released:
                moved = min(need, donor["quantity"])
                if moved:
                    donor["quantity"] -= moved
                    need -= moved
                    transfer = {"from": donor["deck"]["id"], "from_title": donor["deck"]["title"],
                                "to": item["id"], "to_title": item["title"], "quantity": moved}
                    transfers.append(transfer)
                    aggregate["transfers"].append(transfer)
            wait = min(need, remaining_incoming)
            remaining_incoming -= wait
            need -= wait
            item["steps"].append({"name": name, "need": needed, "keep": keep, "storage": pull,
                                  "transfers": transfers, "waiting": wait, "missing": need,
                                  "resolved": name not in unknown})
            for key, qty in (("need", needed), ("kept", keep), ("from_storage", pull), ("waiting", wait), ("missing", need)):
                aggregate[key] += qty
        for donor in released:
            if donor["quantity"]:
                donor["deck"]["returns"].append({"name": name, "quantity": donor["quantity"]})
        if aggregate["need"]:
            rows.append(aggregate)
    totals = {key: sum(row[key] for row in rows) for key in ("need", "kept", "from_storage", "waiting", "missing")}
    totals["transfers"] = sum(transfer["quantity"] for row in rows for transfer in row["transfers"])
    confirmed = not unknown and not warnings
    return {"decks": [{key: value for key, value in item.items() if key not in ("need", "current")}
                       for item in participants], "rows": rows, "totals": totals,
            "ready": bool(participants) and confirmed and not totals["waiting"] and not totals["missing"],
            "counts_confirmed": confirmed, "unresolved": sorted(unknown), "warnings": _scrub(warnings),
            "note": "Checking cards saves shared progress. Mark as built saves the assembled lists; "
                    "other built decks stay reserved."}
