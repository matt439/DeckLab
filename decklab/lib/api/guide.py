"""Read the playing guide from a deck's existing Notes, without changing it.

Only gameplay topics are selected: purchase recommendations, old simulation
reports and inventory prose belong to their own parts of the deck file. The
browser receives Markdown as data, never HTML. It renders a small safe subset.

departed_cards() names the cards the guide mentions that have left the deck (E2-S27):
cards a former saved revision of the deck itself held in its Planned or Play-now list
(any section) and neither of today's lists holds. Only names from the deck's own history
count, so a card name that is a common word ("Opt", "Shock") is never flagged unless the
deck once played it. A name matches as a whole word, case and all, a double-faced card
also by its front face; like the page's card links, one scan tries the longest name first,
so a current card's longer name ("Snow-Covered Forest", "Shock Troops") is used up whole
and a departed "Forest" or "Shock" inside it isn't flagged. Only the deck's own space (or
a script naming nobody) gets the answer: a public deck's outside readers get None, since
the History gives them only plain summaries of the revisions.
"""
import re
import traceback


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_BOLD_LABEL = re.compile(r"^\*\*([^*]+)\*\*\s*(.*)$")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_TOPIC = re.compile(
    r"^(?:game plan\b|how (?:the deck wins|to play)\b|(?:a good )?opening hand\b|"
    r"mulligans?\b|play tips\b|watch out\b|cards to watch out\b|sideboard\b|"
    r"jargon\b|commander.only notes\b)", re.IGNORECASE)


def playing_guide(deck):
    """A deck file's named gameplay topics and its unmodified stale-prose date.

    Returns None for product decks/pairings (no deck file). Sections may be
    Markdown headings or the older '**Game plan.** First sentence' form.
    Fences are ignored so a sample heading inside code cannot select content.
    An unrecognised sibling heading ends a selected topic; its child headings
    cannot leak historical results or purchasing prose back into the guide.
    """
    if deck is None:
        return None
    sections = []
    current = None
    notes_level = None
    topic_level = None
    fence = None

    def finish():
        nonlocal current
        if current is not None:
            markdown = "\n".join(current.pop("lines")).strip()
            if markdown:
                current["markdown"] = markdown
                sections.append(current)
        current = None

    for line in deck.text.splitlines():
        marker = _FENCE.match(line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        heading = _HEADING.match(line)
        if heading:
            level, title = len(heading[1]), heading[2]
            if notes_level is None:
                if title.casefold() == "notes":
                    notes_level = level
                continue
            if level <= notes_level:
                finish()
                break
            if topic_level is None or level <= topic_level:
                finish()
                topic_level = level
                if _TOPIC.match(title):
                    current = {"title": title, "lines": []}
                continue
        if notes_level is None:
            continue
        # Legacy bold topic labels are at the top level of Notes. Bold phrases
        # inside a heading-based topic remain ordinary paragraph content.
        label = _BOLD_LABEL.match(line) if topic_level is None else None
        if label and _TOPIC.match(label[1]):
            finish()
            current = {"title": label[1].rstrip(".:"), "lines": [label[2]]}
        elif current is not None:
            current["lines"].append(line)
    finish()
    return {"sections": sections, "changed_on": deck.changed_on}


MAX_REVISIONS = 100             # the History's: older revisions aren't read
MAX_DEPARTED = 30               # names sent; "count" says how many there are


def _names(deck):
    """Every card name in a parsed deck's Planned and Play-now lists, any section."""
    found = set()
    for sections in (deck.target if deck.has_decklist else None, deck.owned):
        for lines in (sections or {}).values():
            found.update(line.name for line in lines)
    return found


def _faces(name):
    """A card's names to look for: the whole name, and a double-faced card's front face."""
    return [face for face in [name] + ([name.split(" // ")[0]] if " // " in name else []) if face.strip()]


def _first_mentions(departed, current, text):
    """{departed name: where the guide text first names it}. One scan over every name, the
    longest first, as whole words (the page's cardNamesPattern): a match of a current card's
    name or face is a current card, never a departed one inside it."""
    owners = {}
    for name in departed:
        for face in _faces(name):
            owners.setdefault(face, []).append(name)
    for name in current:
        for face in _faces(name):
            owners[face] = []
    if not any(owners.values()):
        return {}
    faces = sorted(owners, key=len, reverse=True)
    pattern = re.compile(rf"(?<![^\W_])(?:{'|'.join(map(re.escape, faces))})(?![^\W_])")
    first = {}
    for match in pattern.finditer(text):
        for name in owners[match[0]]:
            first.setdefault(name, match.start())
    return first


def departed_cards(guide, deck, deck_id):
    """{"names": the departed cards the guide mentions, in the order it first names them (at
    most MAX_DEPARTED), "count": how many} (the module docstring), or None when it can't be
    told: no guide, a viewer outside the deck's space, or revisions that can't be read."""
    if guide is None or deck is None:
        return None
    from decklab.lib import decks, inventory, permissions
    from . import common, guard
    try:
        space, kind, slug = decks.split_id(deck_id)
    except ValueError:
        return None             # a product's or pairing's list has no saved revisions
    try:
        profile = guard.viewer()
    except common.ApiError:
        return None
    if not permissions.sees_deck(profile, space, script=guard.script()):
        return None             # own space only: no public switch counts here
    text = "\n".join(f"{part['title']}\n{part['markdown']}" for part in guide["sections"])
    if not text:
        return {"names": [], "count": 0}
    try:
        from .history import _revision_deck
        former = set()
        for rev in inventory.deck_revisions_with_text(deck_id, MAX_REVISIONS):
            old = _revision_deck(rev, kind, slug, space)
            if old:
                former |= _names(old)
    except Exception:           # optional: the guide stands without it
        common._log("The guide's departed cards couldn't be worked out:\n" + traceback.format_exc())
        return None
    current = _names(deck)
    first = _first_mentions(former - current, current, text)
    names = sorted(first, key=lambda name: (first[name], name))
    return {"names": names[:MAX_DEPARTED], "count": len(names)}
