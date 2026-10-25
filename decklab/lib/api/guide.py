"""Read the playing guide from a deck's existing Notes, without changing it.

Only gameplay topics are selected: purchase recommendations, old simulation
reports and inventory prose belong to their own parts of the deck file. The
browser receives Markdown as data, never HTML. It renders a small safe subset.
"""
import re


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
