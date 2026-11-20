"""Measure Commander starter picks from public precons. Run as python -m scripts.study_commander_starters."""
import argparse
import hashlib
import json
from pathlib import Path

from decklab.lib import cards
from decklab.lib.api.commander_candidates import _rules
from decklab.lib.decks.commander_draft import build
from decklab.lib.decks.role_pool import fits


DECKS = ("TemurRoar_TDC", "PrismariArtistry_SOC", "KeenEngineering_FDC", "SultaiArisen_TDC", "EternalMight_DRC")
DECK_DIR = Path(__file__).resolve().parents[1] / "decklab/data/mtgjson/decks"
GUIDE = "decklab/design/commander-starter-study.md"
# Secondary Temmet measure: six noncreature spells that can make a Zombie army/token for the caster.
ZOMBIE_SUPPLIERS = {"Dread Summons", "Dreadhorde Invasion", "Crowded Crypt", "On Wings of Gold",
                    "Welcome the Dead", "Liliana, Death's Majesty"}
# Each can move a card out of its controller's graveyard, including by paying a cost.
# Manual labels omit incidental mill and opponents' graveyard hate.
REUSE = {
    "Gravecrawler", "Life from the Loam", "Amphin Mutineer", "Junji, the Midnight Sky", "Living Death",
    "Necromantic Selection", "Necropolis Fiend", "Tasigur, the Golden Fang", "Woe Strider", "Conduit of Worlds",
    "Multani, Yavimaya's Avatar", "Shigeki, Jukai Visionary", "Jarad, Golgari Lich Lord", "Meren of Clan Nel Toth",
    "Forbidden Alchemy", "Treasure Cruise", "Phyrexian Reclamation", "Reassembling Skeleton", "Victimize",
    "Grapple with the Past", "Timeless Witness", "Nyx Weaver", "Dig Through Time", "Myr Retriever",
}


def direct(deck, card):
    front = card["type_line"].split(" // ")[0]
    if deck == "TemurRoar_TDC":
        power = card.get("power") or ""
        return "Creature" in front and power.isdecimal() and int(power) >= 4
    if deck == "PrismariArtistry_SOC":
        return "Instant" in front or "Sorcery" in front
    if deck == "KeenEngineering_FDC":
        return "Artifact" in front
    if deck == "SultaiArisen_TDC":
        return card["name"] in REUSE
    return "Creature" in front and "Zombie" in front.split()


def run(details=False):
    boards = {}
    leads = {}
    for deck in DECKS:
        path = DECK_DIR / f"{deck}.json"
        if not path.exists():
            raise SystemExit(f"Missing public deck {path.name}. See {GUIDE} for cache setup.")
        data = json.loads(path.read_bytes())["data"]
        boards[deck] = {c["name"] for c in data["mainBoard"]}
        leads[deck] = data["commander"][0]["name"]
    all_names = set.union(*boards.values())
    if not cards.INDEX_FILE.exists() or not cards.bulk_path("oracle_tags").exists():
        raise SystemExit(f"Missing public Scryfall card index or Oracle tags. See {GUIDE} for cache setup.")
    metadata = {n: cards.card(n) for n in all_names | set(leads.values()) | {"Wastes"}}
    missing = sorted(n for n, c in metadata.items() if not c)
    if missing:
        raise ValueError(f"Public card index is missing {missing}")
    rules = _rules()
    tag = rules.commander.MASS_LAND_DENIAL_TAG
    denial = cards.tag_members([tag], rules.commander.TAG_FILE)[tag]
    digest = hashlib.sha256()
    for deck in DECKS:
        digest.update(json.dumps([deck, leads[deck], sorted(boards[deck])]).encode())
    for name, card in sorted(metadata.items()):
        # Ignore printing-specific art, availability and prices. The draft reads Oracle-level fields.
        record = {k: v for k, v in card.items() if k != "printings"}
        digest.update(json.dumps([name, record, card["oracle_id"] in denial], sort_keys=True).encode())
    print(f"Public input SHA-256 {digest.hexdigest()}")
    for deck in DECKS:
        lead = leads[deck]
        identity = set(metadata[lead]["color_identity"])
        for partition in range(2):
            others = {n for n in all_names - boards[deck] if hashlib.sha256(n.encode()).digest()[0] % 2 == partition}
            pool = sorted(n for n in boards[deck] | others | {lead} if fits(metadata[n], identity))
            draft = build([lead], [], dict.fromkeys(pool, 1), cards.card, rules, denial)
            spells = {r["name"] for r in draft["picks"] if not r["land"]}
            available = {n for n in pool if n != lead and "Land" not in metadata[n]["type_line"].split(" // ")[0]
                         and not metadata[n]["game_changer"] and metadata[n]["oracle_id"] not in denial}
            relevant = {n for n in available if direct(deck, metadata[n])}
            chosen = spells & relevant
            role_gap = sum(max(0, r["target"] - r["count"]) for r in draft["roles"])
            expensive = sum(metadata[n]["cmc"] >= 5 for n in spells)
            print(f"{deck} {partition}: {len(chosen)}/{len(relevant)} direct; {len(spells)}/{len(available)} spells;"
                  f" {len(chosen & others)} direct from other precons; {role_gap} missing role slots;"
                  f" {draft['open_slots']} open slots; {expensive} MV 5+")
            if deck == "EternalMight_DRC":
                print(f"  Selected Zombie suppliers: {len(ZOMBIE_SUPPLIERS & spells)}/{len(ZOMBIE_SUPPLIERS & available)}")
            if details:
                print("  Passed direct cards:", ", ".join(sorted(relevant - chosen)))
                print("  Other picks:", ", ".join(sorted(spells - relevant)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--details", action="store_true")
    run(parser.parse_args().details)
