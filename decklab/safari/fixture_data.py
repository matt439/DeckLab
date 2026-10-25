"""Small invented data for the disposable Safari server; never household data."""
import json

DECK_ID = "casual/safari-fixture"
ORDER_ID = "2000-01-01-safari-fixture"
PROFILE_ID = "matt"
PROFILE_NAME = "Matt"
CONFIG = {"profiles": [{"id": PROFILE_ID, "name": PROFILE_NAME, "role": "admin",
                         "space": "home", "plays_as": "user", "emails": []}],
          "forge_workers": 1, "goldfish_workers": 1}
HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
COLLECTION = HEADER + "Llanowar Elves,sft,1,nonfoil,3,,,Disposable fixture\n"
PAYLOAD = HEADER + """Llanowar Elves,sft,1,nonfoil,1,,,Disposable fixture
Elvish Mystic,sft,2,nonfoil,1,,,Disposable fixture
Opt,sft,3,nonfoil,1,,,Disposable fixture
"""
ORDER = {"version": 1, "id": ORDER_ID, "seller": "Disposable fixture shop", "ordered_on": "2000-01-01",
         "sources": [], "notes": "Synthetic delivery for Safari regression tests only.",
         "components": [{"id": "cards", "kind": "cards", "status": "pending",
                         "path": f"magic/orders/{ORDER_ID}.csv", "received_on": "", "checks": []}]}
DECK = """# Safari Fixture

- **Format:** Casual 60-card, 1v1
- **Archetype:** Disposable Safari test
- **Played by:** user
- **Status:** building

## Decklist

```
Deck
4 Llanowar Elves (SFT) 1
4 Elvish Mystic (SFT) 2
52 Forest
```

## Owned vs needed

Availability only; synthetic test data.

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Elvish Mystic | 4 | 0 | 3 | | | 1 on the way |
| Llanowar Elves | 4 | 3 | 0 | | | 1 on the way |
| **Total to buy** | | | **3** | | | |

## Notes

Disposable Safari regression fixture. Changes are discarded after this configuration.
"""


def card_rows():
    """Scryfall-shaped invented printings of four familiar cards, not a bulk-data read."""
    rows = [("Llanowar Elves", "{G}", "Creature — Elf Druid", ["G"], "{T}: Add {G}."),
            ("Elvish Mystic", "{G}", "Creature — Elf Druid", ["G"], "{T}: Add {G}."),
            ("Opt", "{U}", "Instant", ["U"], "Scry 1. Draw a card."),
            ("Forest", "", "Basic Land — Forest", [], "{T}: Add {G}.")]
    for number, (name, cost, kind, colors, text) in enumerate(rows, 1):
        yield {"id": f"safari-printing-{number}", "oracle_id": f"safari-card-{number}",
               "name": name, "set": "sft", "collector_number": str(number), "layout": "normal",
               "set_type": "expansion", "set_name": "Safari Fixture", "released_at": "2000-01-01",
               "games": ["paper"], "finishes": ["nonfoil"], "mana_cost": cost,
               "cmc": 0 if name == "Forest" else 1, "type_line": kind, "oracle_text": text,
               "colors": colors, "color_identity": ["G"] if name == "Forest" else colors,
               "power": "1" if "Creature" in kind else None,
               "toughness": "1" if "Creature" in kind else None,
               "legalities": {"commander": "legal"}, "prices": {},
               "image_uris": {size: f"https://invalid.example/{size}/fixture.jpg"
                              for size in ("small", "normal")}}


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def seed(root):
    write_text(root / "config.json", json.dumps(CONFIG))
    write_text(root / "magic/collection.csv", COLLECTION)
    write_text(root / "magic/products/status.csv", "file,status,intact,notes\n")
    write_text(root / f"magic/orders/{ORDER_ID}.csv", PAYLOAD)
    write_text(root / f"magic/orders/records/{ORDER_ID}.json", json.dumps(ORDER))
    write_text(root / f"magic/decks/{DECK_ID}.md", DECK)
    write_text(root / "decklab/data/scryfall/cards.jsonl",
               "\n".join(json.dumps(row) for row in card_rows()) + "\n")
    write_text(root / "decklab/data/scryfall/tags.jsonl", "")
