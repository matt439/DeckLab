"""Deck tables after an inventory change: the saved owned-vs-needed tables and substitute-list
notes in the deck texts, worked out again from the inventory.

    planned = plan_texts()                    # [(deck id, title, text now, text after)]
    planned = plan_refresh()                  # [(path, bytes now, bytes after)]: nothing written
    found = table_blockers()                  # every problem that makes them refuse (never raises)

Both plans read the decks from the inventory's snapshot (inventory.current().decks, phase 4),
never the files. The refresh after an inventory change runs inside the operation (the phase 4
design's R3): an operation kind registered with inventory.register(kind, refresh=True) (the
receipt, order add/edit/split/cancel, product add/set-intact) is run by inventory.apply() and
preview() through in_op(), which plans the tables from the operation's settled result (pinned,
as a preview: nothing caches it) and puts the new texts in the same snapshot, so the inventory
change and its deck tables are saved as one change, and a preview lists the deck files its
change would rewrite. Only the decks of the spaces the change touches are planned (spaces_of:
home's for every registered kind), so a home receipt never rewrites, or fails on, a person's
deck. A plan that fails leaves every deck as it was and the change goes ahead;
Summary.extra["tables"] says what happened: {"written": [{"id", "title"}], "skipped": [{"id",
"title", "why": "changed" (the operation changed that deck itself) or "kit"}], "error": why nothing could be planned, or None}. An operation that changes nothing refreshes
nothing (no "tables" in its Summary).

plan_refresh() reads the pool (pool.load_pool, which reads inventory.current()), so inside
inventory.pinned(snapshot) it plans from that snapshot: a receipt preview shows the deck files
its receipt would change without anything being written. It refuses (ValueError) when any
space's pool has warnings or unknown cards, or a deck file can't be read, has no decklist, no
owned-vs-needed table or unknown cards: tables from an incomplete pool would be wrong. It stops at
the first; table_blockers() lists them all, from the same checks (_read_deck, _list_problems,
_pool_problem), for the Decks page's "Tables out of date" list and the command lines.
"""
import re

from decklab.lib import cards, decks, inventory, pool, spaces

HEADING = "### Substitute version (owned and incoming cards)"
AVAILABILITY_MARKER = "<!-- decklab:substitute-availability -->"
AVAILABILITY_RE = re.compile(re.escape(AVAILABILITY_MARKER) + r"[^\r\n]*")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(?:Owned-only version|Substitute version)[^\r\n]*",
                        re.MULTILINE | re.IGNORECASE)


def substitute_note():
    """Explain the list without adding another inventory snapshot that could become stale."""
    return (f"{AVAILABILITY_MARKER} This substitute list can include cards still on the way. "
            "In Deck Lab, select this version and check its live Owned vs needed section before assembling it. "
            "The table above describes the target list.")


def _pool_problem(space, supply):
    """Why a space's pool is too incomplete to refresh tables from (its warnings or unknown
    cards: _supply's refusal, word for word), or None."""
    if not (supply.warnings or supply.unresolved):
        return None
    details = [*supply.warnings, *(f"Unknown card: {name}" for name in supply.unresolved)]
    where = "" if space == spaces.HOME else f" ({space}'s space)"
    return f"Cannot refresh from an incomplete card pool{where}: " + "; ".join(details)


def _supply(space, supplies):
    """A space's pool (lib/spaces.py: each deck is counted in its own), loaded once. Refuse an unreliable one."""
    if space not in supplies:
        supply = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
        problem = _pool_problem(space, supply)
        if problem:
            raise ValueError(problem)
        supplies[space] = supply
    return supplies[space]


class _Problem:
    """Something that stops one deck's table being refreshed: reason ("unreadable", "no_decklist",
    "no_table" or "unknown_cards"), version ("target", "owned" or None), cards (the unknown names)
    and error, the exception _plan raises for it."""

    def __init__(self, reason, error, version=None, cards=()):
        self.reason, self.error, self.version, self.cards = reason, error, version, list(cards)


def _read_deck(snapshot, space, path):
    """(deck id, the stored deck or None, its DeckFile or None, a _Problem or None): a deck as
    _plan and table_blockers read it."""
    deck_id = spaces.join_deck_id(space, path.parent.name, path.stem)
    try:
        decks._checked_path(path)
    except ValueError as e:
        return deck_id, None, None, _Problem("unreadable", e)
    found = snapshot.decks.get(deck_id)
    if found is None:
        return deck_id, None, None, _Problem("unreadable", FileNotFoundError(f"{deck_id} is missing"))
    if found.error is not None:         # as reading the file would have raised
        error = (decks.DeckFileError if found.error.startswith("not UTF-8") else OSError)(found.error)
        return deck_id, found, None, _Problem("unreadable", error)
    try:
        deck = decks.parse_deck(found.data, path.stem, path.parent.name, path, space)
    except decks.DeckFileError as e:
        return deck_id, found, None, _Problem("unreadable", e)
    return deck_id, found, deck, None


def _list_problems(deck_id, deck):
    """[_Problem] of a readable deck's lists and table, in the order _plan refuses them: no
    decklist, unknown card names in the target and then the substitute list, no table. The
    names are checked against the card index (as pool.compare's unresolved), not a pool."""
    if not deck.has_decklist:
        return [_Problem("no_decklist", ValueError(f"{deck_id}: {decks.NO_DECKLIST}"))]
    found = []
    for version, label, sections in (("target", "target", deck.target), ("owned", "substitute", deck.owned)):
        if sections is None:
            continue
        unresolved = {}
        pool._count_sections(sections, "decklist", unresolved)
        if unresolved:
            names = sorted(unresolved)
            found.append(_Problem("unknown_cards", ValueError(
                f"{deck_id}: unknown cards in {label} list: {', '.join(names)}"), version, names))
    if deck.rows is None:
        found.append(_Problem("no_table", decks.DeckFileError(
            f"{deck_id}: the file has no owned-vs-needed table to write rows into")))
    return found


def _why(deck_id, title, problem):
    """A deck's _Problem in plain words for the command line."""
    name = f"{deck_id} ({title})" if title and title != deck_id else deck_id
    if problem.reason == "unreadable":
        return f"{name} can't be read: {public_error(problem.error)}"
    if problem.reason == "no_decklist":
        return f"{name} has no decklist (a fenced block under a '## Decklist' heading)."
    if problem.reason == "no_table":
        return (f"{name} has no owned-vs-needed table: give it an '## Owned vs needed' heading with the "
                f"table's header and |---| lines.")
    words = "target list" if problem.version == "target" else "substitute list"
    return f"{name} has card names Scryfall doesn't know in its {words}: {', '.join(problem.cards)}."


def table_blockers(given=None, only=None):
    """What stops the owned-vs-needed tables being refreshed (deck tables, and an inventory
    change's refresh, refuse while any of it stands), every problem rather than _plan's first:

        {"decks": [{"id", "title", "space", "reason": "unreadable" | "no_decklist" | "no_table" |
                    "unknown_cards", "version": "target" | "owned" | None, "cards": [names],
                    "why": plain words}],
         "spaces": [{"space", "warnings": [str], "unknown": [{"name", "where": [places]}],
                     "why": plain words}]}

    in library order, from the same checks _plan makes (_read_deck, _list_problems,
    _pool_problem). A space is checked when _plan would load its pool: home's always, a
    person's when it has decks; one whose pool can't be loaded at all is a "spaces" entry too.
    given: a Pool already loaded, used for its own space. only: only these spaces (every one
    when None). Never raises: a failure to work it out at all is one "spaces" entry for home."""
    out = {"decks": [], "spaces": []}
    try:
        if not inventory.is_pinned():
            with inventory.pinned():
                return table_blockers(given, only)
        cards.info()
        snapshot = inventory.current()
        wanted = None if only is None else set(only)
        files = [(space, path) for space, path in decks._space_files() if wanted is None or space in wanted]
        checked = [] if wanted is not None and spaces.HOME not in wanted else [spaces.HOME]
        checked += [space for space in dict.fromkeys(space for space, _ in files) if space not in checked]
        for space in checked:
            try:
                if given is not None and getattr(given, "space", spaces.HOME) == space:
                    supply = given
                else:
                    supply = pool.load_pool() if space == spaces.HOME else pool.load_pool(space)
            except Exception as e:      # noqa: BLE001 - reported, never raised
                out["spaces"].append({"space": space, "warnings": [], "unknown": [],
                                      "why": f"{space}'s card pool can't be read: {public_error(e)}"})
                continue
            problem = _pool_problem(space, supply)
            if problem:
                out["spaces"].append({"space": space, "warnings": list(supply.warnings),
                                      "unknown": [{"name": name, "where": sorted(map(str, where))}
                                                  for name, where in supply.unresolved.items()],
                                      "why": problem})
        for space, path in files:
            deck_id, _, deck, problem = _read_deck(snapshot, space, path)
            problems = [problem] if problem else _list_problems(deck_id, deck)
            title = deck.title if deck is not None else deck_id
            for problem in problems:
                out["decks"].append({"id": deck_id, "title": title, "space": space, "reason": problem.reason,
                                     "version": problem.version, "cards": problem.cards,
                                     "why": _why(deck_id, title, problem)})
    except Exception as e:      # noqa: BLE001 - never raises (its callers only describe)
        out = {"decks": [], "spaces": [{"space": spaces.HOME, "warnings": [], "unknown": [],
                                        "why": f"The owned-vs-needed tables can't be checked: {public_error(e)}"}]}
    return out


def plan_refresh(only=None):
    """Prepare every change before writing any file, in every space (or only in the spaces
    only names). Refuse an unreliable pool.
    The pools and the decks come from the inventory as inventory.current() gives it
    (decklab/lib/inventory): run inside inventory.pinned(snapshot) to plan against another
    snapshot, such as a receipt preview's."""
    return [(path, raw.encode("utf-8"), out.encode("utf-8")) for _, path, _, raw, out in _plan(only)]


def plan_texts(only=None):
    """[(deck id, title, text now, text after)] of every deck whose tables plan_refresh would
    change, in its order; the same refusals (ValueError, DeckFileError). only: only the decks
    (and pools) of these spaces, every space when None."""
    return [(deck_id, title, raw, out) for deck_id, _, title, raw, out in _plan(only)]


def spaces_of(rels):
    """The spaces whose inventory these changed paths touch (paths.classify's space of each;
    home's for the shared parts: orders, products, the watchlist, accessories): the only spaces
    whose deck tables the change can make stale. A home receipt never rewrites a person's deck
    (whose tables may be stale from their own collection edits), nor fails on their pool."""
    from . import paths
    out = set()
    for rel in rels:
        found = paths.classify(rel)
        if found is None:
            continue
        what, detail = found
        if what in ("collection", "tokens"):
            out.add(detail)
        elif what in ("import", "deck"):
            out.add(detail[0])
        else:
            out.add(spaces.HOME)
    return out


def _plan(only=None):
    """[(deck id, path, title, text now, text after)]: plan_refresh's work."""
    if not inventory.is_pinned():
        with inventory.pinned():
            return _plan(only)
    cards.info()                 # load the local index on first use
    snapshot = inventory.current()
    wanted = None if only is None else set(only)
    supplies = {}
    if wanted is None or spaces.HOME in wanted:
        _supply(spaces.HOME, supplies)
    planned = []
    for space, path in decks._space_files():
        if wanted is not None and space not in wanted:
            continue
        deck_id, found, deck, problem = _read_deck(snapshot, space, path)     # table_blockers' checks
        if problem:
            raise problem.error
        supply = _supply(space, supplies)
        problems = _list_problems(deck_id, deck)
        if problems:
            raise problems[0].error
        decks.set_table(deck, *pool.deck_table(deck, supply, prices=False))
        text = decks.render_deck_file(deck)
        if deck.owned is not None:
            match = next(m for m in HEADING_RE.finditer(text) if m.start() > 0)
            heading = match.group(1) + HEADING.removeprefix("###")
            text = text[:match.start()] + heading + text[match.end():]
            note = substitute_note()
            if AVAILABILITY_RE.search(text):
                text = AVAILABILITY_RE.sub(lambda _: note, text, count=1)
            else:
                pos = match.start() + len(heading)
                text = text[:pos] + deck.newline * 2 + note + text[pos:]
        if text != found.text:
            planned.append((deck_id, path, deck.title, found.text, text))
    return planned


def preload():
    """Load the card index before an operation that refreshes the tables takes its lock (a
    failure is the plan's to report)."""
    try:
        cards.info()
    except Exception:           # noqa: BLE001 - in_op() reports it as the plan's error
        pass


def public_error(error):
    """An exception (or its text) as words for an answer: no absolute path (api/common.py's
    _public; kept here so the refresh never needs api/commits.py, which phase 4 deletes)."""
    from decklab.lib.api.common import _public
    return _public(error)


def in_op(before, after, summary):
    """(after with every deck whose tables after makes stale given its refreshed text, summary
    with extra["tables"]): the refresh of an operation registered with refresh=True (see the
    module docstring). before is the snapshot the operation ran on; an operation that changed
    nothing from it is returned as it is, with no "tables". Never raises for a plan
    that fails, whatever it raises: the decks stay as after has them, and "error" says why.
    While the backend can't save deck texts (a database that holds no decks: its
    saves_decks() is False) the decks are left alone and "error" is inventory.DECK_SAVES_PAUSED,
    so the inventory change still goes ahead. A planned text whose Sleeves or Deck box differ
    from the deck's is skipped ("kit": only kit.set changes them)."""
    import dataclasses

    from . import PREVIEW, changes, ops_decks
    changed = changes.changed_paths(before, after)
    if not changed:
        return after, summary               # nothing changed: nothing to refresh
    tables = {"written": [], "skipped": [], "error": None}

    def done():
        return after, dataclasses.replace(summary, extra={**(summary.extra or {}), "tables": tables})

    try:
        saves = inventory.backend().saves_decks()
    except Exception as e:      # noqa: BLE001 - a refresh never stops the change it follows
        tables["error"] = public_error(e)
        return done()
    if not saves:
        tables["error"] = inventory.DECK_SAVES_PAUSED
        return done()
    try:
        settled = changes.reread(before, after, revision=before.revision + PREVIEW)
        with inventory.pinned(settled):
            planned = plan_texts(spaces_of(changed))
    except Exception as e:      # noqa: BLE001 - any failure is the plan's to report (R3)
        tables["error"] = public_error(e)
        planned = []
    for deck_id, title, raw, out in planned:
        deck, had = after.decks.get(deck_id), before.decks.get(deck_id)
        if deck is None or had is None or deck.text != had.text:    # the operation changed it itself
            tables["skipped"].append({"id": deck_id, "title": title, "why": "changed"})
            continue
        if ops_decks.kit_of(ops_decks.parsed_deck(deck)) != ops_decks.kit_of(
                ops_decks.parsed_deck(deck.replace(text=out))):
            tables["skipped"].append({"id": deck_id, "title": title, "why": "kit"})
            continue
        after = after.with_deck(deck.replace(text=out))
        tables["written"].append({"id": deck_id, "title": title})
    return done()


