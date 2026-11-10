"""Rules-only counter suggestions for visible list choices; no inventory, state or fetches."""
from decklab.lib import cards
from decklab.lib.tokens import counters

KINDS = ("poison", "energy", "experience", "monarch", "initiative")


def suggestions(snapshot):
    """Kinds are advisory presentation metadata, never part of a captured game's list hash."""
    try:
        played = [(line["name"], line["qty"], section)
                  for section, lines in snapshot["sections"].items() for line in lines]
        kinds = {need["key"] for need in counters.deck_counters(played)["needs"]}
        for name, _, _ in played:
            made, unresolved = cards.tokens_for(name)
            reminders = {cards.fold(entry["name"]) for entry in made} | {cards.fold(name) for name in unresolved}
            card = cards.card(name) or {}
            text = " ".join(part.get("oracle_text") or "" for part in [card, *card.get("faces", [])]).casefold()
            if "the monarch" in reminders or "become the monarch" in text:
                kinds.add("monarch")
            if "the initiative" in reminders or "take the initiative" in text:
                kinds.add("initiative")
        return [kind for kind in KINDS if kind in kinds]
    except (KeyError, TypeError, *cards.INDEX_ERRORS):
        return []  # Optional suggestions never prevent counting; markers can be enabled by hand.
