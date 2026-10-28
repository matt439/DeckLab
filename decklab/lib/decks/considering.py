"""A deck's Considering list (E2-S23): cards that might go in, kept with the deck but outside its
Planned and Play-now lists, like Moxfield's maybeboard.

    ## Considering

    ```
    2 Llanowar Elves (FDN) 227
    1 Elvish Mystic
    ```

It is its own "## Considering" section with one fenced block of card lines in the decklist
format, and no section headers. deckfile.parse_deck reads it into DeckFile.considering (a list of
DeckLine, None when the text has no such block), never into target or owned, so nothing that
reads a deck's lists (the owned-vs-needed table, the pool's needed, missing and in use, packing,
sleeve counts, stats, tokens, Forge, printing and box checks, deck_line rows) sees its cards.
render.render_deck_file writes it back; a deck without one gets the section after its Decklist.
"""
from .decklist import DecklistError, format_line, parse_decklist

HEADING = "Considering"


def parse_considering(text):
    """[DeckLine] from the Considering block's text. Raises DecklistError for a line that isn't a
    decklist line, or a section header (the list has none: its cards are only ideas)."""
    try:
        sections = parse_decklist(text)
    except DecklistError as e:
        raise DecklistError(f"Considering list: {e}") from None
    if set(sections) - {"Deck"} or any(line.strip().rstrip(":").lower() == "deck"
                                       for line in text.split("\n")):
        raise DecklistError("Considering list: card lines only, no section headers")
    return list(sections.get("Deck", []))


def format_considering(lines, newline="\n"):
    """The block's text: one card line each, ending with a newline ('' when empty)."""
    return "".join(format_line(line) + newline for line in lines)


def section_text(lines, newline="\n"):
    """A whole new "## Considering" section, for a deck that has none yet."""
    return f"## {HEADING}{newline}{newline}```{newline}{format_considering(lines, newline)}```{newline}"


def merged(lines):
    """lines with the same printing (name, set, number, finish) added into the first, in order;
    the first category given among them stays (E2-S24)."""
    out, first = [], {}
    for line in lines:
        key = (line.name, line.set, line.number, line.finish)
        if key in first:
            out[first[key]].quantity += line.quantity
            out[first[key]].category = out[first[key]].category or line.category
        else:
            first[key] = len(out)
            out.append(type(line)(line.quantity, line.name, line.set, line.number, line.finish, line.category))
    return out
