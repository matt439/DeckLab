"""Frozen exact lists and bounded, engine-independent cross-check requests.

These receipts are deliberately unrelated to Forge's matchup keys or rankings.
Only the rules engines decide card support; this module never substitutes a card.
"""
import hashlib
import json
import re
from copy import deepcopy

SCHEMA = 1
ENGINES = ("forge", "xmage")
ROLES = ("baseline", "variant", "opponent")
MAX_GAMES = 200
MAX_SEED = (1 << 31) - 201   # XMage's seed API is a signed int; leave room for all game numbers.
MAX_BYTES = 2 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")
LIMITATIONS = [
    "Each simulator's results are kept separate; there is no combined win rate.",
    "Commander is tested one on one, not as a four-player pod.",
    "Agreement is a useful second opinion, not proof of human play or rules correctness.",
    "Missing cards, failed games and timeouts are explicit and excluded from win rates.",
]


class CrosscheckError(ValueError):
    """A bounded request, installation or saved receipt could not be used."""


def canonical(value):
    try:
        data = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise CrosscheckError("The cross-check data is not valid JSON.") from None
    if len(data) > MAX_BYTES:
        raise CrosscheckError("The cross-check data is too large.")
    return data


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise CrosscheckError(f"{name} must be a whole number from {low} to {high}.")
    return value


def text(value, name, maximum=240):
    if (not isinstance(value, str) or not value or len(value) > maximum
            or value != value.strip() or any(ord(c) < 32 for c in value)):
        raise CrosscheckError(f"{name} must be nonblank text of at most {maximum} characters.")
    return value


def listed(cards):
    if not isinstance(cards, dict) or set(cards) - {"Commander", "Main"}:
        raise CrosscheckError("A cross-check list needs Main and Commander sections only.")
    result = {}
    for section in ("Commander", "Main"):
        pairs = cards.get(section, [])
        if not isinstance(pairs, list) or len(pairs) > 1000:
            raise CrosscheckError("A cross-check list has too many card rows.")
        merged = {}
        for pair in pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise CrosscheckError("A card row must contain a quantity and exact card name.")
            quantity = integer(pair[0], "A card quantity", 1, 1000)
            name = text(pair[1], "A card name", 200)
            merged[name] = merged.get(name, 0) + quantity
        result[section] = [[merged[name], name] for name in sorted(merged, key=lambda n: (n.casefold(), n))]
    if not result["Main"] or sum(q for rows in result.values() for q, _ in rows) > 1000:
        raise CrosscheckError("A cross-check list must contain from 1 to 1,000 cards.")
    return result


def snapshot(entry):
    from decklab.lib.forge import lists
    if not isinstance(entry, dict):
        raise CrosscheckError("A saved deck list is required.")
    kind = entry.get("kind")
    if kind not in ("commander", "constructed"):
        raise CrosscheckError("Only Commander and casual constructed lists can be cross-checked.")
    cards = listed(entry.get("cards"))
    if kind != "commander" and cards["Commander"]:
        raise CrosscheckError("A casual list cannot have a separate Commander section.")
    count = sum(q for rows in cards.values() for q, _ in rows)
    if (kind == "commander" and (count != 100 or not 1 <= sum(q for q, _ in cards["Commander"]) <= 2)):
        raise CrosscheckError("Commander cross-checks need the exact 100-card list and its commander.")
    if kind == "constructed" and count < 60:
        raise CrosscheckError("Casual cross-checks need at least 60 cards.")
    card_sha = lists._list_text(cards, kind)[1]
    if entry.get("card_sha") != card_sha:
        raise CrosscheckError("The deck list does not match its captured card fingerprint.")
    version = entry.get("version", "target")
    if version not in ("target", "owned"):
        raise CrosscheckError("The list version must be target or owned.")
    result = {"id": text(entry.get("id"), "A deck id"), "title": text(entry.get("title"), "A deck title"),
              "version": version, "kind": kind, "cards": cards, "card_count": count, "card_sha": card_sha,
              "list_sha256": digest(cards), "source": deepcopy(entry.get("source")),
              "pilot": deepcopy(entry.get("pilot") or {"profile": "Default", "switches": []})}
    canonical(result)
    pilot = result["pilot"]
    if (not isinstance(pilot, dict) or set(pilot) - {"profile", "switches"}
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", str(pilot.get("profile", "")))
            or not isinstance(pilot.get("switches"), list) or len(pilot["switches"]) > 50
            or any(not isinstance(s, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", s)
                   for s in pilot["switches"])):
        raise CrosscheckError("The captured Forge pilot is invalid.")
    return result


def changes(values):
    if isinstance(values, str) or not isinstance(values, (tuple, list)) or len(values) > 100:
        raise CrosscheckError("Card changes must be a list of at most 100 rows.")
    pairs = []
    for value in values:
        if isinstance(value, str):
            match = re.fullmatch(r"(?:(\d+)\s+)?(.+)", value.strip())
            if not match:
                raise CrosscheckError("A card change must name a card.")
            pair = [int(match[1] or 1), match[2]]
        else:
            pair = value
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise CrosscheckError("A card change needs a quantity and card name.")
        pairs.append([integer(pair[0], "A change quantity", 1, 1000), text(pair[1], "A card name", 200)])
    return pairs


def variant(baseline, remove, add):
    from decklab.lib.forge import lists
    removed, added = changes(remove), changes(add)
    if sum(q for q, _ in removed) != sum(q for q, _ in added) or not removed:
        raise CrosscheckError("A change must remove and add the same nonzero number of cards.")
    result = deepcopy(baseline)
    main = {n: q for q, n in result["cards"]["Main"]}
    for quantity, name in removed:
        if main.get(name, 0) < quantity:
            raise CrosscheckError("A removed card is not present in that quantity in the main list.")
        main[name] -= quantity
    for quantity, name in added:
        main[name] = main.get(name, 0) + quantity
    result["cards"]["Main"] = [[q, n] for n, q in main.items() if q]
    result["cards"] = listed(result["cards"])
    result["card_sha"] = lists._list_text(result["cards"], result["kind"])[1]
    result["list_sha256"] = digest(result["cards"])
    if result["list_sha256"] == baseline["list_sha256"]:
        raise CrosscheckError("The proposed change leaves the list unchanged.")
    return result


def validate_plan(value):
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != SCHEMA:
        raise CrosscheckError("This cross-check plan has an unsupported schema.")
    result = deepcopy(value)
    found = result.pop("id", None)
    if not isinstance(found, str) or not HASH.fullmatch(found) or digest(result) != found:
        raise CrosscheckError("The cross-check plan fingerprint does not match its contents.")
    integer(result.get("games"), "Games per list", 1, MAX_GAMES)
    integer(result.get("seed"), "The seed", 0, MAX_SEED)
    integer(result.get("timeout_seconds"), "The game time limit", 5, 600)
    if result.get("format") not in ("casual", "commander") or result.get("mode") != "one-on-one":
        raise CrosscheckError("The cross-check format is invalid.")
    engines = result.get("engines")
    if (not isinstance(engines, list) or not engines or len(engines) > 2
            or any(not isinstance(e, str) or e not in ENGINES for e in engines)
            or len(set(engines)) != len(engines)):
        raise CrosscheckError("Choose Forge, XMage, or both once each.")
    decks = result.get("decks")
    if not isinstance(decks, dict) or not {"baseline", "opponent"} <= set(decks) or set(decks) - set(ROLES):
        raise CrosscheckError("A cross-check requires a baseline and an opponent.")
    for entry in decks.values():
        captured = snapshot(entry)
        if captured != entry:
            raise CrosscheckError("The saved cross-check list is not canonical.")
        if (captured["kind"] == "commander") != (result["format"] == "commander"):
            raise CrosscheckError("Both lists must use the same format.")
    identities = result.get("engine_identities")
    if (not isinstance(identities, dict) or set(identities) != set(engines)
            or any(v is not None and (not isinstance(v, str) or not HASH.fullmatch(v))
                   for v in identities.values())):
        raise CrosscheckError("The captured engine identities are invalid.")
    result["id"] = found
    return result


def request(plan, arm, number):
    decks = []
    for role in (arm, "opponent"):
        cards = plan["decks"][role]["cards"]
        decks.append({"id": role, "main": [{"name": n, "quantity": q} for q, n in cards["Main"]],
                      "commander": [{"name": n, "quantity": q} for q, n in cards["Commander"]]})
    return {"schema": SCHEMA, "format": plan["format"], "seed": plan["seed"] + number - 1,
            "games": 1, "game_number": number, "starting_player": (number - 1) % 2,
            "timeout_seconds": plan["timeout_seconds"], "decks": decks}


def engine_request(plan, name, arm, number):
    result = request(plan, arm, number)
    if name == "forge":
        # Forge seeds a coin flip for the actual first player. Its alternating
        # deck-seat assignment is a different fact from XMage's requested start.
        result["seat_assignment"] = result.pop("starting_player")
        result.update(engine_sha256=plan["engine_identities"][name],
                      forge_stream=digest([plan["decks"]["baseline"]["card_sha"],
                                           plan["decks"]["opponent"]["card_sha"]])[:16],
                      pilots={r: plan["decks"][r]["pilot"] for r in (arm, "opponent")})
    return result
