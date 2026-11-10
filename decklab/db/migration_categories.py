"""0027's category-only derived projection backfill, inside the schema transaction.

Never called by reads or startup. The migration owns its transaction; all source
identities are validated before a single category or audit row is written.
"""
from collections import defaultdict


class ProjectionError(ValueError):
    pass


def projection(texts, stored):
    """[(category, deck, version, section, position)] for validated canonical texts."""
    from decklab.lib.inventory import pg_decks
    by_deck = defaultdict(list)
    for row in stored:
        if len(row) != 9:
            raise ProjectionError("A derived deck line has an unexpected shape")
        by_deck[row[0]].append(tuple(row))
    updates, seen = [], set()
    for deck_id, text in texts:
        if deck_id in seen or not isinstance(text, str):
            raise ProjectionError("A saved deck's source text couldn't be confirmed")
        seen.add(deck_id)
        deck = pg_decks.parsed(deck_id, text)
        if deck is None:
            raise ProjectionError("A saved deck's source text couldn't be parsed")
        lines = pg_decks.lines(deck_id, deck, categories=True)
        if sorted(row[:-1] for row in lines) != sorted(by_deck.pop(deck_id, [])):
            raise ProjectionError("A saved deck's derived lines don't match its text")
        updates.extend((row[-1], *row[:4]) for row in lines if row[-1] is not None)
    if by_deck:
        raise ProjectionError("Derived lines have no matching saved deck text")
    return updates


def backfill(cur):
    """All validation precedes writes; outer migration transaction also owns rollback."""
    texts = cur.execute("select deck_id, text from deck_text order by deck_id").fetchall()
    stored = cur.execute("select deck_id, version, section, position, quantity, name, set_code, "
                         "collector_number, finish from deck_line order by deck_id, version, section, position").fetchall()
    updates = projection(texts, stored)
    if not updates:
        return 0
    cur.execute("insert into audit.change_set (actor, source, message) values ('system', 'migration', %s) returning id",
                ("Backfill derived deck-line categories for migration0027; deck texts remain unchanged",))
    change_set = cur.fetchone()[0]
    cur.execute("select set_config('decklab.change_set', %s, true)", (str(change_set),))
    cur.executemany("update deck_line set category = %s where deck_id = %s and version = %s and section = %s and position = %s", updates)
    return len(updates)
