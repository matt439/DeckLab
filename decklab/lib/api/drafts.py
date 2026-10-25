"""Reading and checking an editor draft (what the page sent for a check or a
save): each line, section and header field, the blocks and warnings found
on the way and the cards each warning is about, the deck-building rules
and a Commander deck's bracket (lib/stats/, imported when first needed),
and the Commander Brackets for the bracket picker.

The editor and saving call drafts._read_draft, so a test that patches it
here reaches both.
"""
import importlib
import re
import traceback

from decklab.lib import accessories, cards, decks, pool, spaces

from . import common, guard
from .card_lookup import _card_printings, _default_printing, _not_paper, _pickable, _resolve
from .common import LINE_FINISHES, MAX_NAME, MAX_QTY, NUMBER_RE, SET_RE, _CONTROL_RE, ApiError, _lazy, _strip_paths

MAX_LINES = 250                 # lines in one section of a list
MAX_ARCHETYPE = 300             # characters in the Archetype field
MAX_SLEEVES = 40                # characters in the Sleeves field (an accessory id, or a colour)
MAX_DECK_BOX = 40               # characters in the Deck box field (an accessory id, or free text)
MAX_SUGGESTED = 20              # unknown names in a pasted list that get suggestions


class _Draft:
    """What the page sent for a check or a save, read and checked: lists
    {"target": sections or None, "owned": ...} (None: not sent), fields, and
    the blocks and warnings found on the way. known holds the (name, set,
    number, finish) lines already in the file (or the deck a new one starts
    from): those are kept as written, even with a name the card data lacks."""

    def __init__(self, kind, known=(), space=spaces.HOME):
        self.kind = kind
        self.space = space
        self.known = set(known)
        self.known_setless = {name for name, set_code, _, _ in self.known if set_code is None}
        self.counts = _lazy(lambda: _visible_counts(space))
        self.lists = {"target": None, "owned": None}
        self.sent = {"target": 0, "owned": 0}   # lines the page sent in each list
        self.fields = {}
        self.blocks = []
        self.warnings = []
        self.about = {}             # warning -> the card names it's about (see _warnings_json)
        self.suggested = 0          # unknown names given "Did you mean" (at most MAX_SUGGESTED)

    def warn(self, text, names=()):
        """Add a warning about these cards (their names as the list has them)."""
        self.warnings.append(text)
        if names:
            known = self.about.setdefault(text, [])
            known.extend(name for name in names if name not in known)

    def block(self, problem, **where):
        where.pop("known", None)
        self.blocks.append({"list": None, "section": None, "index": None, "name": None, "field": None,
                            **where, "problem": problem})


def _visible_counts(space):
    """pool.printing_counts() of space, which picks a new line's default printing, or {} (the
    cheapest or newest printing) for a request that may not see space's inventory: anyone may
    check a draft of any deck, and the printing picked would show which one the space owns or
    has on the way (R6d). Anyone who may save the deck sees it."""
    if not guard.sees_inventory(space):
        return {}
    return pool.printing_counts() if space == spaces.HOME else pool.printing_counts(space)


def _known(*decklists):
    return {(l.name, l.set, l.number, l.finish) for sections in decklists if sections
            for lines in sections.values() for l in lines}


def _checked_line(draft, line, where):
    """line, or None with a block if it couldn't be written and read back."""
    try:
        decks.format_line(line)
    except ValueError:
        draft.block(f"{line.name} can't be written as a decklist line", **where)
        return None
    return line


def _read_line(draft, raw, where):
    """One line from the page as a DeckLine, or None with a block. A line the
    file already has is kept as written (where["known"] is set True); a new
    one must name a card in the card data (its exact Scryfall name is used)
    and, if it names a printing, one of that card's, in a finish it comes in;
    a non-basic card with no set gets _default_printing()."""
    name, qty = raw.get("name"), raw.get("qty")
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or _CONTROL_RE.search(name):
        draft.block(f"Every line needs a card name (one line, at most {MAX_NAME} characters)", **where)
        return None
    name = name.strip()
    where["name"] = name
    if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
        draft.block(f"{name}: the number of copies must be a whole number from 1 to {MAX_QTY}", **where)
        return None
    set_code, number, finish = raw.get("set"), raw.get("number"), raw.get("finish") or "nonfoil"
    set_code = None if set_code in (None, "") else set_code
    number = None if number in (None, "") else number
    if set_code is not None and not (isinstance(set_code, str) and SET_RE.fullmatch(set_code.lower())):
        draft.block(f"{name}: {set_code!r} isn't a set code (2-8 letters and digits)", **where)
        return None
    set_code = set_code.lower() if set_code else None
    if number is not None and not (isinstance(number, str) and NUMBER_RE.fullmatch(number)):
        draft.block(f"{name}: {number!r} isn't a collector number", **where)
        return None
    if number is not None and set_code is None:
        draft.block(f"{name}: a collector number needs a set", **where)
        return None
    if finish not in LINE_FINISHES:
        draft.block(f"{name}: the finish must be one of {', '.join(LINE_FINISHES)}", **where)
        return None
    if (name, set_code, number, finish) in draft.known:
        if _resolve(name) is None:
            draft.warn(f"{name!r} isn't a card name in the card data; it was already in the file, "
                       f"so it's kept as written", [name])
        where["known"] = True
        return _checked_line(draft, decks.DeckLine(qty, name, set_code, number, finish), where)

    exact = _resolve(name)
    if exact is None:
        # Looking for close spellings takes a while (about 25 ms a name), so
        # a request full of unknown names gets them for the first few only.
        suggestions = []
        if draft.suggested < MAX_SUGGESTED:
            draft.suggested += 1
            suggestions = cards.close_names(name)
        hint = f" Did you mean {' or '.join(suggestions)}?" if suggestions else ""
        draft.block(f"{name!r} isn't a card name Deck Lab knows.{hint}", suggestions=suggestions, **where)
        return None
    where["name"] = exact
    shown = f"{exact} ({set_code.upper()}) {number}" if set_code and number else exact
    if set_code is None:
        if not decks.is_basic_land(exact) and exact not in draft.known_setless:
            chosen = _default_printing(exact, draft.counts())
            if chosen:
                set_code, number, finish = chosen["set"], chosen["number"], chosen["finish"]
            elif not any(_pickable(cards.printing(s, n)) for s, n in _card_printings(exact)):
                draft.block(f"{exact} has no playable paper printing: choose a physical card", **where)
                return None
    elif number is not None:
        p = cards.printing(set_code, number)
        if p is None or _resolve(p["name"]) != exact:
            draft.block(f"{shown} isn't a printing of {exact}: pick one from its printings", **where)
            return None
        if not _pickable(p):
            draft.block(f"{shown} is {_not_paper(p)}, not a card to play with: pick one from its printings", **where)
            return None
        if finish not in p["finishes"]:
            draft.block(f"{shown} doesn't come in {finish}", **where)
            return None
    else:
        in_set = [cards.printing(s, n) for s, n in _card_printings(exact) if s == set_code]
        if not in_set:
            draft.block(f"{exact} was never printed in {set_code.upper()}", **where)
            return None
        if not any(_pickable(p) for p in in_set):
            draft.block(f"{exact}'s {set_code.upper()} printing is {_not_paper(in_set[0])}, not a card to play "
                        f"with: pick one from its printings", **where)
            return None
    return _checked_line(draft, decks.DeckLine(qty, exact, set_code, number, finish), where)


def _read_sections(draft, version, raw):
    """{section: [DeckLine]} from one list the page sent (see _read_line). A
    new line for a printing the section already has is added to that line;
    lines the file already has stay as they are, even when a file lists one
    printing on two lines (some do, on purpose)."""
    out = {}
    for section, lines in raw.items():
        where = {"list": version, "section": section}
        if not isinstance(lines, list):
            raise ApiError(400, f"lists.{version}.{section} must be a list of card lines")
        if not lines:
            continue                # an empty section is dropped, whatever its name
        draft.sent[version] += len(lines)
        if section not in decks.SECTIONS:
            draft.block(f"Unknown section {section!r}: use {', '.join(decks.SECTIONS)}", **where)
            continue
        if section == "Commander" and draft.kind != "commander":
            draft.block("A casual deck can't have a Commander section: move those cards into the Deck", **where)
            continue
        if len(lines) > MAX_LINES:
            draft.block(f"More than {MAX_LINES} lines in one section", **where)
            continue
        kept, first = [], {}
        for index, raw_line in enumerate(lines):
            if not isinstance(raw_line, dict):
                raise ApiError(400, f"lists.{version}.{section}[{index}] must be a JSON object")
            at = dict(where, index=index)
            line = _read_line(draft, raw_line, at)
            if line is None:
                continue
            key = (line.name, line.set, line.number, line.finish)
            if at.get("known") or key not in first:
                first.setdefault(key, len(kept))
                kept.append(line)
                continue
            same = kept[first[key]]
            same.quantity += line.quantity
            if same.quantity > MAX_QTY:
                draft.block(f"{line.name} is listed more than once in the {section}, adding up to more than "
                            f"{MAX_QTY} copies", **dict(where, index=index, name=line.name))
        out[section] = kept
    return {name: out[name] for name in decks.SECTIONS if out.get(name)}


def _read_fields(draft, raw, creating=False, current_archetype=None, current_sleeves=None, current_deck_box=None):
    """The header fields the page sent ({key: value}, see decks.apply_edit);
    a bad value is a block. A new deck can't have Built version yet.
    current_archetype, current_sleeves and current_deck_box: the file's
    Archetype, Sleeves and Deck box as written, if any."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ApiError(400, "fields must be a JSON object")
    allowed = [key for key in decks.EDIT_FIELDS if not (creating and key == "built_version")]
    out = {}
    for key, value in raw.items():
        if key == "format" and not creating:
            continue            # read-only, echoed back from edit_view (_read_draft checks it's unchanged)
        if key not in allowed:
            raise ApiError(400, f"Unknown field {key!r}; {'a new deck takes' if creating else 'the editor changes'}: "
                                f"{', '.join(allowed)}")
        where = {"field": key}
        if key in ("status", "player"):
            options = decks.STATUSES if key == "status" else decks.PLAYERS
            if value is not None and value not in options:
                draft.block(f"{decks.EDIT_FIELDS[key]} must be one of: {', '.join(options)}", **where)
                continue
        elif key == "archetype" and value is not None:
            if isinstance(value, str) and not _CONTROL_RE.search(value):
                # A new value loses invisible characters and extra spaces; the
                # file's own value echoed back stays as written (no change).
                same = current_archetype is not None and value.strip() == current_archetype.strip()
                value = value.strip() if same else decks.clean_title(value)
            if not isinstance(value, str) or _CONTROL_RE.search(value) or not 1 <= len(value) <= MAX_ARCHETYPE:
                draft.block(f"The archetype must be one line of 1-{MAX_ARCHETYPE} characters (a few words on how "
                            f"the deck plays)", **where)
                continue
        elif key in ("sleeves", "deck_box") and value is not None:
            # As the archetype: the file's own value echoed back stays as written (no change).
            # A blank value isn't a colour, even when the file's line is blank too.
            current = current_sleeves if key == "sleeves" else current_deck_box
            same = isinstance(value, str) and current is not None and value.strip() != "" \
                and value.strip() == current.strip()
            if isinstance(value, str) and not _CONTROL_RE.search(value):
                value = value.strip() if same else decks.clean_title(value)
            limit = MAX_SLEEVES if key == "sleeves" else MAX_DECK_BOX
            if not same and (not isinstance(value, str) or _CONTROL_RE.search(value)
                             or not 1 <= len(value) <= limit):
                draft.block(f"Sleeves must be one line of 1-{MAX_SLEEVES} characters (the colour of the deck's "
                            f"sleeves)" if key == "sleeves" else
                            f"Deck box must be one line of 1-{MAX_DECK_BOX} characters (the box the deck is kept in)",
                            **where)
                continue
        elif key == "built_version":
            if value not in (None, *decks.BUILT_VERSIONS):
                draft.block("Built version must be target, owned or null", **where)
                continue
        elif key == "target_bracket":
            if isinstance(value, str) and value.isascii() and value.isdigit():
                value = int(value)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or value not in decks.BRACKET_NUMBERS):
                draft.block("The target bracket must be a whole number from 1 to 5", **where)
                continue
            if value is not None and draft.kind != "commander":
                draft.block("Only Commander decks have a target bracket", **where)
                continue
        out[key] = value
    return out


def _new_space(data, profile=None):
    """The space a new deck goes in: data["space"] (lib/spaces.py), by
    default the profile's own (home for Matt and User1, a person's space for
    the others); ApiError 400 for a value that isn't a space id, 403
    (guard.HIDDEN_SPACE) for one whose decks the request's viewer can't see
    or that config.json doesn't list, and 404 for the latter only to a
    script naming nobody."""
    space = data.get("space")
    if space is None:
        own = (profile or {}).get("space") or spaces.HOME
        return own if spaces.exists(own) else spaces.HOME
    if not isinstance(space, str) or len(space) > 40:
        raise ApiError(400, "space must be home or a person's space id")
    # A space whose decks the request's viewer can't see, and one that doesn't exist, answer
    # alike (E10-S38): the 404 that names it goes only to a script naming nobody. (A save asks
    # the body's profile too: saving.require_sees_space.)
    if not guard.sees_deck({"space": space}):
        raise ApiError(403, guard.HIDDEN_SPACE)
    if not spaces.exists(space):
        raise ApiError(404, f"No space {space!r}")
    return space


def _read_draft(data, kind, deck=None, source=None, space=None):
    """A _Draft of data's lists and fields, for an existing deck file (deck,
    whose own space counts) or a new deck (kind, starting from source's
    sections, in space: home by default)."""
    space = deck.space if deck is not None else (space or spaces.HOME)
    draft = _Draft(kind, _known(deck.target, deck.owned) if deck is not None else _known(source), space)
    raw = data.get("lists")
    versions = ("target", "owned") if deck is not None else ("target",)
    if raw is not None:
        if not isinstance(raw, dict):
            raise ApiError(400, 'lists must be a JSON object like {"target": {"Deck": [...]}}')
        for version in raw:
            if version not in versions:
                raise ApiError(400, f"Unknown list {version!r}; send {' and '.join(versions)}")
        for version in versions:
            sections = raw.get(version)
            if sections is None:
                continue
            if not isinstance(sections, dict):
                raise ApiError(400, f"lists.{version} must be a JSON object of sections")
            draft.lists[version] = _read_sections(draft, version, sections)
    draft.fields = _read_fields(draft, data.get("fields"), creating=deck is None,
                                current_archetype=deck.get_field("Archetype") if deck is not None else None,
                                current_sleeves=deck.get_field("Sleeves") if deck is not None else None,
                                current_deck_box=deck.get_field("Deck box") if deck is not None else None)
    if deck is not None:
        sent = data["fields"].get("format") if isinstance(data.get("fields"), dict) else None
        if sent is not None and sent != deck.format:
            draft.block("The Format field can't be changed here", field="format")
        if draft.lists["owned"] == {} and deck.owned:
            draft.block("The play-now list can't be emptied or removed here", list="owned")
        if draft.lists["target"] == {} and draft.sent["target"] == 0 and deck.target:
            # A page that sent its list before it had loaded would wipe the deck
            # (and its table's hand notes) in one save: only on purpose.
            if data.get("confirm_empty") is True:
                draft.warnings.append("The planned list is empty: this save takes every card out of the deck "
                                      "and every row out of its owned-vs-needed table.")
            else:
                draft.block("The planned list is empty: saving it would take every card out of the deck (and every "
                            "row out of its owned-vs-needed table, hand notes too). Add cards, or confirm that the "
                            "deck should be emptied.", list="target", confirm="confirm_empty")
        value = draft.fields.get("built_version")
        status = draft.fields.get("status") or deck.status
        owned = draft.lists["owned"] if draft.lists["owned"] is not None else deck.owned
        if "built_version" in draft.fields and value is not None and value != deck.built_version \
                and not (status == "built" and owned):
            draft.block("Built version says which list is put together, so it's only for a built deck with both a "
                        "planned list and a play-now list", field="built_version")
        elif status != "built" and deck.built_version is not None and deck.status == "built" \
                and draft.fields.get("built_version", deck.built_version) == deck.built_version:
            # A deck taken apart (built -> building or idea) has no built list:
            # the field goes, or it would silently apply again once it's rebuilt.
            draft.fields["built_version"] = None
        for key, header, held in (("sleeves", "Sleeves", deck.sleeves), ("deck_box", "Deck box", deck.deck_box)):
            value = draft.fields.get(key)
            if key in draft.fields and value is not None and value != held and status != "built":
                draft.block(_BUILT_ONLY[key], field=key)
            elif status != "built" and deck.get_field(header) is not None and deck.status == "built" \
                    and draft.fields.get(key, held) == held:
                # Taken apart, its cards go back into storage unsleeved: the sleeves and box go too.
                draft.fields[key] = None
    else:
        for key in ("sleeves", "deck_box"):
            if draft.fields.get(key) is not None and (draft.fields.get("status") or "idea") != "built":
                draft.block(_BUILT_ONLY[key], field=key)
    if space != spaces.HOME:
        # A person's deck is theirs by where it lives, and accessories are home's:
        # these fields aren't written there (a value already in the file may stay).
        held = {"player": deck.player, "sleeves": deck.sleeves, "deck_box": deck.deck_box} if deck else {}
        for key, words in _HOME_ONLY.items():
            value = draft.fields.get(key)
            if value is not None and value != held.get(key) and not any(b["field"] == key for b in draft.blocks):
                draft.block(words, field=key)
    return draft


# The block for a Sleeves or Deck box value on a deck that isn't built.
_BUILT_ONLY = {"sleeves": "Sleeves is the colour of a built deck's sleeves, so it's only for a built deck",
               "deck_box": "Deck box is the box a built deck is kept in, so it's only for a built deck"}


# The blocks for fields a deck in a person's space doesn't have (lib/spaces.py).
_HOME_ONLY = {
    "player": "A deck in a person's own space has no Played by: it's theirs by where it's kept",
    "sleeves": "Sleeves are recorded only for the home decks (the accessories are home's)",
    "deck_box": "Deck boxes are recorded only for the home decks (the accessories are home's)"}


def _new_fields(draft, kind, profile, space=spaces.HOME):
    """A new deck's header fields: what the page sent over the defaults
    (player: the profile's plays_as at home, none in a person's space;
    status idea and, for Commander, target bracket 2; a null means the
    default). check_draft and create_deck both use them, so the check
    before "Create" warns as the create will."""
    player = (profile or {}).get("plays_as") if space == spaces.HOME else None    # None: a script names nobody
    fields = {**({"player": player} if player else {}), "status": "idea",
              **{k: v for k, v in draft.fields.items() if v is not None}}
    if kind == "commander":
        fields.setdefault("target_bracket", 2)
    return fields


def _final(draft, deck):
    """(target, owned or None): the lists as a save would leave them, for the rules and the preview."""
    target = draft.lists["target"] if draft.lists["target"] is not None else (deck.target if deck else {})
    owned = draft.lists["owned"] if draft.lists["owned"] is not None else (deck.owned if deck else None)
    return target, owned or None


def built_sleeves(exclude=None, inv=None, usage=None, owners=None):
    """[{"id", "title", "sleeves"}]: the sleeves of each holder that records
    some (built deck files, then owned products kept intact as
    "product/<stem>"), except the holder exclude (a deck id). sleeves is the
    accessory's label ("Dragon Shield Matte (black)") for a linked id, else
    the value as written (spaces made one). inv and usage
    (accessories.holders) save reading them again. A holder whose owner
    owners (guard.accessory_owners; None: all) can't see has id None and
    its title only "one of User1's decks", its sleeves only the colour."""
    inv = accessories.read() if inv is None else inv
    usage = accessories.holders(inv) if usage is None else usage
    found = [h for entries in usage.values() for h in entries if h["field"] == "sleeves" and h["holder"] != exclude]
    found.sort(key=lambda h: (h["kind"] == "product", h["holder"]))
    out = []
    for h in found:
        row = inv.rows_by_id[h["value"]] if h["state"] == "linked" else None
        if accessories.visible(h["owner"], owners):
            out.append({"id": h["holder"], "title": h["title"],
                        "sleeves": accessories.label(row) if row else h["value"]})
        else:
            out.append({"id": None, "title": accessories.hidden_title(h["owner"], h["kind"]),
                        "sleeves": (row["colour"] or "unrecorded colour") if row else h["value"]})
    return out


def _built_sections(draft, deck):
    """The list a built deck holds, as the draft would save it (pool._built_version's rule)."""
    if deck is not None and deck.status == "built" and draft.fields.get("status", "built") == "built":
        from decklab.lib.decks import assembled
        if (assembled.get(deck) is not None
                or draft.fields.get("built_version", deck.built_version) == deck.built_version):
            return assembled.sections(deck)
    target, owned = _final(draft, deck)
    version = draft.fields["built_version"] if "built_version" in draft.fields else (
        deck.built_version if deck is not None else None)
    if version is None:
        version = "owned" if owned else "target"
    return owned if version == "owned" and owned else target


def _sleeve_warnings(draft, deck):
    """A built deck's Sleeves and Deck box, as the draft would save them: a
    warning when it has no sleeves, and accessories.kit's for its built list
    (too few sleeves, a deck box used by more decks than there are, an id
    of the wrong kind; sleeves other holders also use are fine)."""
    values = {key: draft.fields[key] if key in draft.fields else (getattr(deck, key) if deck is not None else None)
              for key in ("sleeves", "deck_box")}
    if not values["sleeves"]:
        draft.warnings.append("This deck is built: set Sleeves to the colour of its sleeves")
        if not values["deck_box"]:
            return
    player = draft.fields["player"] if "player" in draft.fields else (deck.player if deck is not None else None)
    try:
        from .accessories import read_kit
        kit = read_kit(deck.deck_id if deck is not None else None,
                              _built_sections(draft, deck), values=values,
                              owner=accessories.player_owner(player))
    except Exception:           # a warning only; the log has the details
        common._log("The other decks' sleeves couldn't be read:\n" + traceback.format_exc())
        return
    draft.warnings.extend(kit["warnings"])


def _rule_warnings(draft, deck):
    """stats.deck_rules for each list as the draft would save it, added to
    draft.warnings ("Play-now list: ..." for that list) with the cards
    each is about (draft.about), and a Commander deck's bracket (None
    otherwise): {"minimum", "label", "target", "game_changers", "reasons"}.
    They never block a save."""
    target, owned = _final(draft, deck)
    bracket_target = (draft.fields["target_bracket"] if "target_bracket" in draft.fields
                      else (deck.target_bracket if deck is not None else None))
    status = draft.fields.get("status") or (deck.status if deck is not None else None)
    built = draft.fields["built_version"] if "built_version" in draft.fields else (
        deck.built_version if deck is not None else None)
    from decklab.lib.decks import assembled
    if (status == "built" and target and owned and built is None
            and (deck is None or assembled.get(deck) is None)):
        draft.warnings.append("This deck is built and has both lists: set Built version to say which one is put "
                              "together (until then its play-now list counts as in use)")
    # Accessories are home's, and a deck's seen only by those who see its owner's (guard.sees_kit):
    # its stored owner's as well as the draft's, so a draft can't change Played by to have the
    # stored Sleeves and Deck box (another owner's) resolved for it.
    player = draft.fields["player"] if "player" in draft.fields else (deck.player if deck is not None else None)
    sees_stored = deck is None or guard.sees_kit({"space": deck.space, "player": deck.player})
    if (status == "built" and draft.space == spaces.HOME and sees_stored
            and guard.sees_kit({"space": draft.space, "player": player})):
        _sleeve_warnings(draft, deck)
    bracket = None
    try:
        module = importlib.import_module("decklab.lib.stats")
        for version, sections in (("target", target), ("owned", owned)):
            if sections is None:
                continue
            rules = module.deck_rules(sections, "commander" if draft.kind == "commander" else "constructed")
            # The page's names for the lists (web/core.js LIST_NAME); editor-save.js OWNED_PREFIX.
            prefix = "Play-now list: " if version == "owned" else ""
            about = list(rules.get("problem_cards") or [])
            for i, problem in enumerate(rules["problems"]):
                draft.warn(prefix + problem, about[i] if i < len(about) else ())
            if version == "target" and rules.get("commander"):
                b = rules["commander"]["bracket"]
                bracket = {"minimum": b["minimum"], "label": b["label"], "target": bracket_target,
                           "game_changers": b["game_changers"], "reasons": b["reasons"]}
                if bracket_target and b["minimum"] > bracket_target:
                    # About every card its reasons name: Game Changers, mass land denial, extra turns.
                    named = [c["name"] for key in ("game_changers", "mass_land_denial", "extra_turns")
                             for c in (b.get(key) or ())]
                    draft.warn(f"The list needs at least Bracket {b['minimum']}, but the target bracket "
                               f"is {bracket_target}: " + "; ".join(b["reasons"]), named)
    except Exception:           # the page still checks and saves; the log has the details
        common._log("The deck rules couldn't be checked:\n" + traceback.format_exc())
        draft.warnings.append("The deck-building rules couldn't be checked (the server log says why)")
    return bracket


def _blocks_error(blocks):
    first = blocks[0]["problem"]
    more = f" (and {len(blocks) - 1} more problem{'s' if len(blocks) > 2 else ''})" if len(blocks) > 1 else ""
    return ApiError(400, f"The deck can't be saved yet: {first}{more}", blocks=blocks)


def _counts(sections):
    if sections is None:
        return None
    return {"main": decks.card_count(sections), "sideboard": decks.card_count(sections, ("Sideboard",)),
            "commander": decks.card_count(sections, ("Commander",)),
            "companion": decks.card_count(sections, ("Companion",))}


def _warnings_json(texts, about=None):
    """(warnings, warning_cards) for an answer: the warnings without repeats
    or absolute paths, and for each the exact card names it's about
    (about: {warning: [names]}, _Draft.about; [] for one about no card), so
    the page can mark those rows."""
    shown, names, where = [], [], {}
    for text in texts:
        plain = _strip_paths(text)
        cards_named = (about or {}).get(text, ())
        if plain not in where:
            where[plain] = len(shown)
            shown.append(plain)
            names.append([])
        known = names[where[plain]]
        known.extend(name for name in cards_named if name not in known)
    return shown, names


def _bracket_names():
    """{number: "Core", ...} from stats.BRACKETS, so a changed Target bracket reads "3 (Upgraded)"."""
    try:
        return {b["number"]: b["name"] for b in getattr(importlib.import_module("decklab.lib.stats"), "BRACKETS", ())}
    except Exception:
        return {}


def _brackets():
    """[{"number", "name"}] of the Commander Brackets (stats.BRACKETS), for the editor's bracket picker."""
    return [{"number": number, "name": name} for number, name in sorted(_bracket_names().items())]


# ---- the write-up (the editor's Notes tab)

# The prose sections a deck's text has that Deck Lab doesn't write: (key, heading). Substitutes ends where
# its substitute list ("### Substitute version ...") starts, since that list is Deck Lab's.
PROSE_SECTIONS = (("substitutes", "Substitutes"), ("notes", "Notes"))
MAX_PROSE = 64 * 1024           # bytes of one prose section
_OWNED_HEADINGS = ("owned-only version", "substitute version")
_PROSE_HEADING_RE = re.compile(r"^#{1,2}(?:\s|$)")
_PROSE_LIST_HEADING_RE = re.compile(r"^#{1,6}\s+(?:owned-only version|substitute version|owned vs|decklist)", re.I)


def _prose_spans(text):
    """{key: (start, stop, text) or None} of each PROSE_SECTIONS section in a deck's text: from just after
    its "## " heading line to the next level-2 (or higher) heading, or for Substitutes to its substitute
    list's heading when that comes first."""
    from decklab.lib.decks import deckfile
    lines = deckfile._lines(text)
    headings = deckfile._headings(lines)
    out = {}
    for key, title in PROSE_SECTIONS:
        found = next((i for i, level, words in headings if i > 0 and level == 2 and words.strip().lower() == title.lower()),
                     None)
        if found is None:
            out[key] = None
            continue
        end = deckfile._section_end(lines, headings, found, 2)
        if key == "substitutes":
            end = next((i for i, _, words in headings if found < i < end and words.lower().startswith(_OWNED_HEADINGS)),
                       end)
        start = lines[found].end
        stop = lines[end].start if end < len(lines) else len(text)
        out[key] = (start, stop, text[start:stop])
    return out


def _plain_prose(text):
    """A prose section as the page shows it: LF line endings, without the blank lines around it."""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def prose_of(text):
    """{"substitutes": text or None, "notes": text or None}: a deck text's write-up, for the Notes tab."""
    return {key: _plain_prose(span[2]) if span else None for key, span in _prose_spans(text).items()}


def _read_prose(data, problems=None):
    """data["prose"] checked: {key: text} (only the sections sent), or {} when there's none. ApiError 400 for
    text that would change more than the write-up (a "#" or "##" heading, a heading of the lists or the table,
    or an unclosed fenced block, all of which would move where the deck's own parts are read; a line inside
    a closed ``` block isn't a heading, as deckfile reads it). With problems (a list), those words are added
    to it and the section is left out instead (check_draft shows them as blocks); a malformed prose is
    still a 400."""
    raw = data.get("prose")
    if raw is None:
        return {}
    keys = [key for key, _ in PROSE_SECTIONS]
    if not isinstance(raw, dict) or any(key not in keys for key in raw):
        raise ApiError(400, f"prose must be a JSON object with any of {', '.join(keys)}")
    out = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise ApiError(400, f"prose.{key} must be text")
        if len(value.encode("utf-8")) > MAX_PROSE:
            raise ApiError(413, f"The write-up's {key} is limited to {MAX_PROSE // 1024} KB")
        value = _plain_prose(value)
        if _CONTROL_RE.search(value.replace("\n", "").replace("\t", "")):
            raise ApiError(400, "The write-up can't contain control characters")
        problem = _prose_problem(value.split("\n"))
        if problem and problems is None:
            raise ApiError(400, problem)
        if problem:
            problems.append(problem)
            continue
        out[key] = value
    return out


def _prose_problem(lines):
    """Why these write-up lines can't be saved, or None. As deckfile._headings reads a deck, a line inside a
    fenced block is never a heading."""
    in_fence, outside = False, []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            outside.append(line)
    if in_fence:
        return "A ``` block in the write-up is never closed"
    if any(_PROSE_HEADING_RE.match(line) for line in outside):
        return "Headings in the write-up start with ### (the deck's own sections use # and ##)"
    if any(_PROSE_LIST_HEADING_RE.match(line) for line in outside):
        return "The write-up can't have a heading named like the deck's lists or its table"
    return None


def with_prose(text, prose, newline="\n"):
    """A deck's text with its write-up sections replaced by prose ({key: text}, as _read_prose gives it). A
    section the text lacks is added (Substitutes before Notes, Notes at the end) unless the new text is empty;
    one that reads the same is left exactly as it was."""
    for key, title in reversed(PROSE_SECTIONS):         # Notes first: it comes later in the text
        if key not in prose:
            continue
        new = prose[key]
        span = _prose_spans(text)[key]
        if span is not None:
            start, stop, old = span
            if _plain_prose(old) == new:
                continue
            body = newline + new.replace("\n", newline) + newline if new else newline
            if stop < len(text):
                body += newline             # a blank line before the heading that follows
            text = text[:start] + body + text[stop:]
            continue
        if not new:
            continue
        block = f"## {title}{newline}{newline}{new.replace(chr(10), newline)}{newline}"
        notes = _prose_spans(text)["notes"] if key == "substitutes" else None
        if notes is not None:
            # Before the Notes heading: the start of the line holding it.
            at = text.rfind("\n", 0, notes[0] - 1) + 1
            text = text[:at] + block + newline + text[at:]
        else:
            text = text.rstrip("\r\n") + newline + newline + block
    return text
