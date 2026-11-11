"""Intrinsic same-tier catalogue role quartiles, never a recommendation or household-data read."""
from collections import Counter
from datetime import datetime
import math

MIN_DECKS = 10
MAX_DECKS = 5000
TIERS = {2: "core", 3: "upgraded"}


def quartile(values, fraction):
    values = sorted(values)
    at = (len(values) - 1) * fraction
    lower, upper = math.floor(at), math.ceil(at)
    return round(values[lower] + (values[upper] - values[lower]) * (at - lower), 1)


def view(catalogue, bracket, roles, card_of):
    """Only complete playable100-card decks count; unavailable never becomes a zero band."""
    missing = {"ready": False, "minimum": MIN_DECKS, "roles": [], "decks": 0}
    tier = TIERS.get(bracket)
    if tier is None:
        return {**missing, "reason": "Comparable catalogue ranges are available for target Brackets 2 and 3 only."}
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("decks"), list):
        return {**missing, "reason": "No readable Commander catalogue is available; no comparable range was calculated."}
    try:
        built = datetime.fromisoformat(catalogue["built"]).isoformat(timespec="seconds")
    except (KeyError, ValueError, TypeError):
        return {**missing, "reason": "The catalogue build date cannot be verified; no comparable range was calculated."}
    if len(catalogue["decks"]) > MAX_DECKS:
        return {**missing, "reason": "The catalogue is too large to count safely on this page."}
    measured, seen = [], set()
    for deck in catalogue["decks"]:
        if not isinstance(deck, dict) or deck.get("playable") is not True or deck.get("tier") != tier or deck.get("kind") != "commander":
            continue
        fingerprint = deck.get("card_sha")
        if not isinstance(fingerprint, str) or not fingerprint or fingerprint in seen:
            continue
        sections = deck.get("cards")
        if (not isinstance(sections, dict) or not sections.get("Commander")
                or sections.get("Main") and sections.get("Deck")
                or any(not isinstance(sections.get(section, []), list) for section in ("Commander", "Companion", "Main", "Deck"))):
            continue
        counts, total, complete = Counter(), 0, True
        for section in ("Commander", "Companion", "Main", "Deck"):
            for row in sections.get(section, []):
                if not isinstance(row, list) or len(row) != 2 or type(row[0]) is not int or not 1 <= row[0] <= 100 or not isinstance(row[1], str):
                    complete = False
                    break
                card = card_of(row[1])
                if (not isinstance(card, dict) or not isinstance(card.get("roles"), (list, tuple))
                        or any(not isinstance(role, str) for role in card["roles"])):
                    complete = False
                    break
                total += row[0]
                counts.update({role: row[0] for role in set(card["roles"]) if role in roles})
            if not complete:
                break
        if complete and total == 100:
            measured.append(counts)
            seen.add(fingerprint)
    if len(measured) < MIN_DECKS:
        return {**missing, "tier": tier, "built": built, "decks": len(measured),
                "reason": f"Too few complete comparable decks: {len(measured)}; at least {MIN_DECKS} are needed."}
    bands = [{"role": role, "low": quartile([row[role] for row in measured], .25),
              "typical": quartile([row[role] for row in measured], .5), "high": quartile([row[role] for row in measured], .75)}
             for role in roles]
    return {"ready": True, "tier": tier, "built": built, "decks": len(measured), "minimum": MIN_DECKS,
            "roles": bands, "note": "A range, not a recipe. Low/typical/high are the 25th/50th/75th percentiles of unique playable same-tier catalogue decks."}
