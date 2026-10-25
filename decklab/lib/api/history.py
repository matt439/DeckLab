"""Read-only deck revisions (the phase 4 design's D5): the backend's deck_revision rows, numbered
per deck from 1 (inventory.deck_revisions / deck_revision). Restoring a list uses the existing
guarded editor.

- GET /api/deck/history?id= lists a deck's revisions newest first: revision (int), date (the
  instant in this PC's local offset, as git's %aI was), op ("A", "M", "D"), actor and author
  (its profile id and name only within the actor's space; outsiders and unknown actors read
  None and "someone", except scripts and the reserved actors, as Activity), subject (the
  message's first line only within the deck's own space: never a body or its trailers; None
  for a revision that changed the deck's Sleeves or Deck box, seen by anyone but who saved it,
  DeckRevision.message_for). An outside reader of a public deck gets only a plain summary,
  including "Tables refreshed" for a saved table or generated substitute note. Public deck
  visibility never gives access to Activity's rows or their messages (E10-S34/S37).
  commit (the git commit's first 7 hex for a revision the import brought from git, else None),
  and change: what the revision changed against the
  revision before it (revision_change(): the cards each list gained and lost, with their card
  data for the pictures, and the header fields; the Sleeves and Deck box only for a viewer who
  sees that deck's accessories). The answer's may_save says whether this visitor may save the
  deck (the editor's may_save, by the viewer's own rights: the login through the tunnel, the
  profile the page's chooser names at home; only a script naming nobody may save any
  deck), so the page offers restoring a list only to those who may.
  The texts are read in one query (inventory.deck_revisions_with_text).
- GET /api/deck/revision?id=&revision=&version= gives one revision's list: revision is its number,
  or the full 40-64 hex git commit an imported revision came from (so a link from before the
  database still opens). Its Sleeves and Deck box show as today's rule says, by the old
  revision's Played by (guard.sees_kit).
- Every read asks guard.sees_deck first (deck_aliases.canonical_id, by the id, whose space is a
  retired deck's former space), before a revision is looked up: a deck the viewer may not see
  answers exactly as a missing one, 404 "No deck <id>" (E10-S30).
- A retired saved deck keeps its history and revision reads. Its latest deletion and exact
  preceding stored text identify it; it has no editor state or current text fingerprint.
  The files backend keeps no history: an empty list for an active deck.
"""
import re

from decklab.lib import decks, inventory, permissions, profiles, spaces
from decklab.lib.decks.decklist import SECTIONS
from decklab.lib.inventory import refresh
from . import deck_aliases, guard
from .activity import ACTOR_NAMES, SOMEONE
from .card_lookup import _lines_json
from .carddata import _require_cards
from .common import ApiError, _public
from .editor import edit_view
from .library import _find_summary, check_deck_id

MAX_REVISIONS = 100
MAX_CHANGES = 60                # card changes listed per revision; the rest are counted in "more"
_NUMBER = re.compile(r"[1-9][0-9]{0,8}")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")


def _parts(deck_id):
    """The saved deck's validated space, kind and slug, whether active or retired."""
    check_deck_id(deck_id)
    try:
        space, kind, slug = decks.split_id(deck_id)
    except ValueError:
        raise ApiError(400, f"{deck_id} has no history: only a deck saved in Deck Lab (casual/..., "
                            f"commander/..., or a person's <space>/casual/...) has one, not a product "
                            f"deck or pairing") from None
    if not spaces.exists(space):
        raise guard.no_deck(deck_id)              # as any missing deck
    return space, kind, slug


def _deck(deck_id):
    """(space, kind, slug, the snapshot's Deck) of a deck that exists now; ApiError otherwise."""
    deck_id = deck_aliases.canonical_id(deck_id)
    space, kind, slug = _parts(deck_id)
    found = inventory.current().deck(deck_id)
    if found is None:
        raise guard.no_deck(deck_id)
    return space, kind, slug, found


def _retired_from(deck_id, space, kind, slug, found):
    """Strict retirement identity: the latest D and its immediate preceding stored text."""
    if not found or found[0].op != "D":
        raise guard.no_deck(deck_id)            # as a missing or hidden deck (E10-S30)
    deleted = found[0]
    if (len(found) < 2 or found[1].revision != deleted.revision - 1
            or found[1].op == "D" or found[1].text is None):
        raise ApiError(500, "This retired deck's last stored text cannot be read safely")
    rev = found[1]
    parsed = _parse(rev.text.encode("utf-8"), kind, slug, space, "This retired deck's last stored text")
    if not guard.sees_deck(_holder(parsed)):
        raise guard.no_deck(deck_id)
    return space, kind, slug, rev, parsed, deleted.revision


def retired_record(deck_id):
    """(space, kind, slug, final stored revision, parsed text, latest deletion number).

    Only absent decks whose latest revision is D qualify. Never fall back to an older text
    or owner when the immediate pre-deletion revision is missing or malformed.
    """
    deck_id = deck_aliases.canonical_id(deck_id)
    space, kind, slug = _parts(deck_id)
    if inventory.current().deck(deck_id) is not None:
        raise ApiError(409, "This deck is active; its retired identity cannot be restored")
    return _retired_from(deck_id, space, kind, slug, inventory.deck_revisions_with_text(deck_id, 2))


def _may_restore(parsed):
    """A whole retired text can be restored only by its current owner, without held cards/kit."""
    if not decks.valid_slug(parsed.deck_id.rsplit("/", 1)[-1]):
        return False
    if parsed.status == "built" or any((parsed.get_field(key) or "").strip() for key in ("Sleeves", "Deck box")):
        return False
    viewer, script = guard.viewer(), guard.script()
    return all(permissions.reason(viewer, action, parsed, script=script) is None
               for action in ("deck.edit", "deck.create"))


def _parse(data, kind, slug, space, what):
    try:
        return decks.parse_deck(data, slug, kind, None, space)
    except decks.DeckFileError as e:
        raise ApiError(500, f"{what} can't be read: {_public(e)}") from None


def _viewer():
    """(the viewer's profile id or None, whether this request sees every message: a script
    naming nobody, guard.script(), as Activity's "all")."""
    profile = guard.viewer()
    viewer_id = profile["id"] if profile else None
    return viewer_id, viewer_id is None and guard.script()


def _profiles():
    try:
        return {p["id"]: p for p in profiles.read()}
    except (OSError, ValueError):
        return {}


def _subject(message):
    return None if message is None else message.split("\n", 1)[0].strip()


def revision_json(rev, viewer_id, everything, people, *, space, table_refresh=False):
    """The server's complete message and actor rule, for both history endpoints. A public
    deck exposes no Activity rows to outsiders, so none of its change-set or migrated git
    subjects are theirs to read. Being an admin or the change's actor doesn't widen that.
    Own-space readers keep message_for's existing kit restriction; scripts read everything."""
    viewer = people.get(viewer_id)
    own = (viewer.get("space") or spaces.HOME) if viewer else None
    actor = people.get(rev.actor)
    same_space = actor and own is not None and (actor.get("space") or spaces.HOME) == own
    known = rev.actor in ACTOR_NAMES or bool(actor and (everything or same_space))
    if known:
        author = actor["name"] if actor else ACTOR_NAMES[rev.actor]
    else:
        author = rev.actor if everything else SOMEONE
    if everything or own == space:
        subject = _subject(rev.message_for(viewer_id, everything))
    else:
        subject = "Tables refreshed" if rev.op == "M" and table_refresh else {
            "A": "Created the deck", "D": "Retired the deck"}.get(rev.op, "Saved the deck")
    return {"revision": rev.revision, "date": rev.at.astimezone().isoformat(timespec="seconds"), "op": rev.op,
            "actor": rev.actor if known or everything else None, "author": author,
            "subject": subject,
            "commit": rev.git_commit[:7] if rev.git_commit else None}


def _table_refresh(deck, older):
    """Whether the stored text changed a generated table or substitute availability note.
    Read the actual revisions, never their free-form messages: an order or receipt may have
    any -m subject. These are the only parts inventory.refresh rewrites, and no order id or
    table contents are included in the summary. Unreadable/missing predecessors fail closed
    to the ordinary save summary."""
    if not deck or not older:
        return False

    def generated(parsed):
        table = parsed.spans.get("table")
        heading = refresh.HEADING_RE.search(parsed.text)
        note = refresh.AVAILABILITY_RE.search(parsed.text)
        return (parsed.text[slice(*table)] if table else None,
                heading.group(0) if heading else None, note.group(0) if note else None)

    return generated(deck) != generated(older)


def deck_history(deck_id=None):
    requested_id = deck_id
    deck_id = deck_aliases.canonical_id(deck_id)
    space, kind, slug = _parts(deck_id)
    deck = inventory.current().deck(deck_id)
    # The revisions shown with their texts, and the one before the oldest shown, to compare it
    # with: one read (a deck with 100 saves is one query, not 101 connections).
    found = inventory.deck_revisions_with_text(deck_id, MAX_REVISIONS + 1)
    retired = deck is None
    if retired:
        _, _, _, _, parsed, deleted = _retired_from(deck_id, space, kind, slug, found)
    else:
        parsed = _parse(deck.data, kind, slug, space, deck_id)
        deleted = None
    viewer_id, everything = _viewer()
    people = _profiles()
    texts = [_revision_deck(rev, kind, slug, space) for rev in found]
    cards_ready = _cards_ready()
    rows = []
    for i, rev in enumerate(found[:MAX_REVISIONS]):
        immediate = i + 1 < len(found) and found[i + 1].revision == rev.revision - 1
        row = revision_json(rev, viewer_id, everything, people, space=space,
                            table_refresh=_table_refresh(texts[i], texts[i + 1]) if immediate else False)
        # Against the nearest earlier revision that can be read (or a deletion), past any that can't.
        j = i + 1
        while j < len(found) and texts[j] is False:
            j += 1
        if j < len(found):
            older, older_deck = found[j], texts[j]
        elif j > i + 1:
            older, older_deck = rev, False      # nothing earlier that was read can be
        else:
            older, older_deck = None, None      # the first revision
        row["change"] = revision_change(rev, texts[i], older, older_deck, cards_ready, skipped=j - i - 1)
        rows.append(row)
    # The save's own rule, as the editor's may_save: the viewer's (the login through the tunnel, the
    # profile the page's chooser names at home); a script naming nobody may.
    why = permissions.reason(guard.viewer(), "deck.edit", parsed if retired else _find_summary(deck_id),
                             script=guard.script())
    return deck_aliases.metadata({"id": deck_id, "title": parsed.title,
            "sha256": None if retired else deck.sha256, "revisions": rows,
            "truncated": len(found) > MAX_REVISIONS, "may_save": not retired and why is None,
            "retired": retired, "may_restore": retired and _may_restore(parsed), "retired_revision": deleted},
            requested_id, deck_id)


# ------------------------------------------------------------------ what a revision changed

def _cards_ready():
    from .carddata import _index_info
    return _index_info()[0] is not None


def _revision_deck(rev, kind, slug, space):
    """A revision's (read with its text) parsed DeckFile; None for a deletion, False when its
    text can't be read."""
    if rev.op == "D":
        return None
    if rev.text is None:
        return False
    try:
        return decks.parse_deck(rev.text.encode("utf-8"), slug, kind, None, space)
    except decks.DeckFileError:
        return False


def _counts(sections):
    """{(section, name): [copies, {(set, number, finish): copies}, its first line]} of a list."""
    found = {}
    for section, lines in (sections or {}).items():
        for line in lines:
            entry = found.setdefault((section, line.name), [0, {}, line])
            entry[0] += line.quantity
            printing = (line.set, line.number, line.finish)
            entry[1][printing] = entry[1].get(printing, 0) + line.quantity
    return found


def _size(sections):
    return None if sections is None else sum(line.quantity for lines in sections.values() for line in lines)


def _picture(line, section, cards_ready):
    """A line's card data (card_lookup's, as the deck page has it), or None."""
    if not cards_ready:
        return None
    try:
        return _lines_json({section: [line]}, [])[section][0]["card"]
    except (KeyError, TypeError, ValueError, OSError):
        return None


def _list_changes(version, before, after, cards_ready):
    """The cards a list gained and lost: [{list, section, name, delta, printing, card}], printing
    True when the printings it names changed (delta may then be 0). Gains come before losses
    within a section, sections in the decklist's order."""
    old, new = _counts(before), _counts(after)
    out = []
    for key in {**old, **new}:
        was, now = old.get(key), new.get(key)
        delta = (now[0] if now else 0) - (was[0] if was else 0)
        printing = bool(was and now and set(was[1]) != set(now[1]))
        if not delta and not printing:
            continue
        section, name = key
        line = (now or was)[2]
        out.append({"list": version, "section": section, "name": name, "delta": delta, "printing": printing,
                    "card": _picture(line, section, cards_ready)})
    order = {name: i for i, name in enumerate(SECTIONS)}
    out.sort(key=lambda c: (order.get(c["section"], len(SECTIONS)), c["delta"] <= 0, c["name"].casefold()))
    return out


def _fields(deck, hidden):
    values = {"Title": deck.title}
    values.update({key: deck.get_field(key) for key in decks.OWNED_FIELDS if key not in hidden})
    return values


def _holder(deck):
    """A parsed revision as guard.sees_kit reads a holder: its id, space and Played by (a
    DeckFile names its id deck_id, which holder_owner wouldn't find), as the deck page's."""
    return {"id": deck.deck_id, "space": deck.space, "player": deck.player}


def _hidden(*parsed):
    """The header fields this viewer doesn't see: Sleeves and Deck box, unless it sees the
    accessories of each of these revisions' decks (guard.sees_kit, by each one's Played by)."""
    for deck in parsed:
        if not guard.sees_kit(_holder(deck)):
            return ("Sleeves", "Deck box")
    return ()


def revision_change(rev, deck, older, older_deck, cards_ready=True, skipped=0):
    """What revision rev (deck: its parsed text, None for a deletion, False when unreadable)
    changed against the revision before it (older, with its older_deck; older None for the
    first; skipped: how many unreadable revisions between them were passed over): {kind, cards:
    [_list_changes' entries, the planned list's first], more (changes past MAX_CHANGES) and
    more_by_list ({list: those of its changes}), fields:
    [{key, before, after}] (Title and the header fields), size: {target, owned} (each list's
    cards, None when it has none), lists (the lists that changed, counting changes past
    MAX_CHANGES), restored (a "created" after a deletion), skipped}. kind is "deleted",
    "created" (the first revision, or the first after a deletion), "unreadable" (its own text
    can't be read), "unreadable_before" (it can, but no earlier text to compare it with can),
    "cards" (a list changed), "details" (only the title or header fields) or "none" (only the
    text around them: the write-up or the table)."""
    change = {"kind": "none", "cards": [], "more": 0, "more_by_list": {}, "fields": [], "size": None, "lists": [],
              "restored": False, "skipped": skipped}
    if rev.op == "D" or deck is None:
        return dict(change, kind="deleted")
    if deck is False:
        return dict(change, kind="unreadable")
    change["size"] = {"target": _size(deck.target) if deck.has_decklist else None, "owned": _size(deck.owned)}
    if older is None or older.op == "D" or older_deck is None:
        return dict(change, kind="created", restored=older is not None)
    if older_deck is False:
        return dict(change, kind="unreadable_before")
    cards = _list_changes("target", older_deck.target, deck.target, cards_ready)
    cards += _list_changes("owned", older_deck.owned, deck.owned, cards_ready)
    hidden = _hidden(deck, older_deck)
    before, after = _fields(older_deck, hidden), _fields(deck, hidden)
    fields = [{"key": key, "before": before[key], "after": after[key]} for key in after if before[key] != after[key]]
    past = cards[MAX_CHANGES:]
    change.update(kind="cards" if cards else "details" if fields else "none", cards=cards[:MAX_CHANGES],
                  more=len(past), fields=fields,
                  more_by_list={v: n for v in ("target", "owned") if (n := sum(c["list"] == v for c in past))},
                  lists=[v for v in ("target", "owned") if any(c["list"] == v for c in cards)])
    return change


def _number(deck_id, revision):
    """The revision number a request names: a number, or an imported revision's git commit."""
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1:
        return revision
    if isinstance(revision, str) and _NUMBER.fullmatch(revision):
        return int(revision)
    if isinstance(revision, str) and _COMMIT.fullmatch(revision):
        for rev in inventory.deck_revisions(deck_id):
            if rev.git_commit == revision:
                return rev.revision
        raise ApiError(404, "That git commit isn't a revision of this deck")
    raise ApiError(400, "Choose a revision from this deck's history")


def deck_revision(deck_id=None, revision="", version="target"):
    requested_id = deck_id
    deck_id = deck_aliases.canonical_id(deck_id)
    _require_cards()
    if version not in ("target", "owned"):
        raise ApiError(400, "Choose target or owned")
    space, kind, slug = _parts(deck_id)
    retired = inventory.current().deck(deck_id) is None
    if retired:
        retired_record(deck_id)
    number = _number(deck_id, revision)
    rev = inventory.deck_revision(deck_id, number)
    if rev is None:
        raise ApiError(404, f"This deck has no revision {number}")
    if rev.op == "D" or rev.text is None:
        raise ApiError(404, f"Revision {number} deleted the deck: it has no list")
    raw = rev.text.encode("utf-8")
    if len(raw) > 1024 * 1024:
        raise ApiError(400, "This historical deck text is too large")
    old = _parse(raw, kind, slug, space, f"Revision {number}")
    sections = old.target if version == "target" else old.owned
    if not old.has_decklist or sections is None:
        raise ApiError(404, "This revision has no selected list")
    warnings = []
    # The Sleeves and Deck box lines only for those who see the deck's owner's accessories.
    hidden = () if guard.sees_kit(_holder(old)) else ("Sleeves", "Deck box")
    viewer_id, everything = _viewer()
    # The list already reads adjacent texts at once; a single-revision request needs its
    # immediate predecessor only for an outsider's generated-table summary.
    people = _profiles()
    viewer = people.get(viewer_id)
    own = (viewer.get("space") or spaces.HOME) if viewer else None
    older = inventory.deck_revision(deck_id, number - 1) if not everything and own != space and number > 1 else None
    table_refresh = _table_refresh(old, _revision_deck(older, kind, slug, space)) if older else False
    return deck_aliases.metadata({"id": deck_id, "revision": number, "version": version, "title": old.title,
            "sections": _lines_json(sections, warnings),
            "fields": {key: None if key in hidden else old.get_field(key) for key in decks.OWNED_FIELDS},
            "history": revision_json(rev, viewer_id, everything, people, space=space, table_refresh=table_refresh),
            "current": None if retired else edit_view(deck_id), "retired": retired, "warnings": warnings},
            requested_id, deck_id)
