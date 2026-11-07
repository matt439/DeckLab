"""Invented populated deck/library records for rendered composition comparisons."""
import copy
import shutil

COMMANDER = "commander/woodland-council"
LONG = "casual/river-research"
EMPTY = "casual/unfinished-idea"


def card_rows(original):
    rows = list(original())
    additions = [
        ("Marwyn, the Nurturer", "{2}{G}", 3, "Legendary Creature — Elf Druid", "Whenever another Elf enters, put a +1/+1 counter on Marwyn. {T}: Add green mana equal to Marwyn's power."),
        ("Llanowar Visionary", "{2}{G}", 3, "Creature — Elf Druid", "When this creature enters, draw a card. {T}: Add {G}."),
        ("Beast Whisperer", "{2}{G}{G}", 4, "Creature — Elf Druid", "Whenever you cast a creature spell, draw a card."),
        ("Reclamation Sage", "{2}{G}", 3, "Creature — Elf Shaman", "When this creature enters, you may destroy target artifact or enchantment."),
        ("Harmonize", "{2}{G}{G}", 4, "Sorcery", "Draw three cards."),
        ("Overrun", "{2}{G}{G}{G}", 5, "Sorcery", "Creatures you control get +3/+3 and gain trample until end of turn."),
    ]
    for number, (name, cost, cmc, kind, text) in enumerate(additions, 5):
        row = copy.deepcopy(rows[0])
        row.update(id=f"review-printing-{number}", oracle_id=f"review-card-{number}", name=name,
                   collector_number=str(number), mana_cost=cost, cmc=cmc, type_line=kind, oracle_text=text,
                   power="1" if "Creature" in kind else None, toughness="1" if "Creature" in kind else None)
        rows.append(row)
    return rows


def seed(fixture, casual_text):
    from decklab.lib import cards
    from decklab.lib.api import play_records
    from decklab.lib.state import Actor

    commander = """# Woodland council — mana, cards and a carefully timed finish

- **Format:** Commander, 1v1
- **Archetype:** Elf mana and creatures
- **Played by:** user
- **Status:** built

## Decklist

```
Commander
1 Marwyn, the Nurturer (SFT) 5
Deck
1 Llanowar Elves (SFT) 1
1 Elvish Mystic (SFT) 2
1 Llanowar Visionary (SFT) 6
1 Beast Whisperer (SFT) 7
1 Reclamation Sage (SFT) 8
1 Harmonize (SFT) 9
1 Overrun (SFT) 10
92 Forest
```

## Notes

### Game plan

Develop mana with [Llanowar Elves] and Marwyn, then turn that mana into more cards. Keep enough creatures to make the eventual Overrun count.

### Opening hand

Look for lands, an early mana creature and a way to keep drawing. *A hand with only expensive spells needs another look.*

### Playing the middle turns

Beast Whisperer keeps the creatures coming. Reclamation Sage answers an awkward artifact or enchantment; do not spend it without a reason.

### Finishing a game

Cast Overrun when the board can make good use of it. Keep the table's interaction in mind before committing every creature.
"""
    long_text = casual_text.replace("# Synthetic home woodland deck", "# River research — patient setup, small advantages and a longer title", 1)
    long_text = long_text.replace("- **Status:** building", "- **Status:** idea", 1)
    empty = """# An unfinished idea

- **Format:** Casual 60-card, 1v1
- **Played by:** user
- **Status:** idea

## Decklist

```
Deck
```

## Notes

An empty local idea for rendered-state qualification.
"""
    for deck_id, body in ((COMMANDER, commander), (LONG, long_text), (EMPTY, empty)):
        path = fixture.root / f"magic/decks/{deck_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        fixture.inventory._remember(deck_id, body, "matt", "Seed synthetic composition deck", "A")
    image = fixture.root / "decklab/data/images/normal/sft/1.jpg"
    for size in ("small", "normal", "large", "art_crop"):
        for number in range(5, 11):
            target = cards.IMAGES_DIR / size / "sft" / f"{number}.jpg"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image, target)
    # Valid snapshots pass the ordinary Game log reader, rather than adapting /api/deck.
    sides = [dict(play_records._snapshot(deck_id, "target"), player="Matt", mulligans=0)
             for deck_id in (COMMANDER, LONG)]
    for n, day in enumerate(("2000-01-02", "2000-01-03", "2000-01-05"), 1):
        fixture.state.play_put("games", {"version": 1, "kind": "games", "id": f"{n:032x}", "revision": 1,
            "created_on": f"{day}T01:00:00+00:00", "updated_on": f"{day}T01:00:00+00:00",
            "updated_by": "Matt", "date": day, "result": "a" if n != 2 else "b", "notes": "",
            "space": "home", "sides": sides}, None, Actor("matt", "Matt"), "Seed synthetic played history")
