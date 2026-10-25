"""Building Deck Lab's card index from Scryfall's bulk files.

cards.update() downloads the bulk files and calls build_index() here, which
streams a default_cards file and an oracle_tags file (.jsonl or .jsonl.gz) and
returns the index dict that cards writes to disk and loads. This module is a
pure transformation: it keeps no state and knows no file locations, network
addresses or the loaded index, and it imports nothing from decklab.lib.cards.

Its public names (build_index, fold, INDEX_VERSION, ROLE_TAGS, ROLES,
FACE_FIELDS) are re-exported by cards, so callers keep using
cards.build_index, cards.fold and so on. They're owned here: a test that
patches one of them must patch it on card_index, since build_index never sees
a patch on cards. _read_tag_tree and _tag_closure are read through this module
(cards.tag_members uses them) and aren't re-exported, nor is _now, which
cards reads here for its download times.
"""
import gzip
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

INDEX_VERSION = 4       # 3: back-face images, loyalty and defense; 4: tokens and what each card makes

# Objects in default_cards that aren't cards you put in a deck. They keep their
# printing entries, so a (set, number) lookup still finds them, but they never
# get a name in the card index. Without this the Llanowar Elves token (ttsr 12)
# could shadow the real card. Checked against the bulk data on 2026-09-29.
NON_GAME_LAYOUTS = {
    "token", "double_faced_token", "emblem",
    "art_series", "front_card",           # art cards, Jumpstart theme front cards
    "planar", "scheme", "vanguard",       # Planechase, Archenemy and Vanguard cards
    "reversible_card",                    # two-sided printings of a real card, named "X // X"
}
NON_GAME_SET_TYPES = {"token", "minigame"}   # helper cards ("Poison Counter", Role tokens), minigames

# Tokens, emblems and reminder cards. Objects of these layouts are tokens of
# some kind; so is any object whose type line starts with "Token" (Role tokens
# on The List's flip printings, the Mechtitan reversible card), "Card" (The
# Monarch, Poison Counter) or "Dungeon". Checked against the bulk data on 2026-10-09.
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem"}

# Reminder cards that only mark where to put a card: never something a deck
# needs, so links to them are dropped. Checked against the bulk data on
# 2026-10-09: these are every such name there.
HELPER_NAMES = {"On an Adventure", "Foretell", "Plot", "Companion", "Double-Faced Substitute Card"}

# A card's link to a token of its own name is taken for the token printing of
# the card itself (like Llanowar Elves' ttsr 12), unless its text says it makes
# tokens or it has one of these keywords (Coruscation Mage's offspring). A
# safeguard: on 2026-10-09 all 55 such links in the bulk data were kept.
SELF_TOKEN_KEYWORDS = {"Offspring", "Embalm", "Eternalize", "Encore", "Myriad", "Squad"}
_TOKEN_WORD_RE = re.compile(r"\btokens?\b", re.IGNORECASE)
_CHECKLIST_RE = re.compile(r" Checklist( \d+)?$")     # "Innistrad Checklist", "... Checklist 2"

# When different cards share a name (Un-set and playtest cards reuse real names,
# e.g. Pick Your Poison), the card printed outside these set types wins.
SIDE_SET_TYPES = {"funny", "memorabilia"}

# Role -> Scryfall oracle tag slug. A role holds the tag's own cards plus those
# of every tag below it: removal and draw have no cards of their own. Counts are
# oracle cards including child tags, checked 2026-09-29.
ROLE_TAGS = {
    "removal": "removal",             # 6,738 (25 child tags, incl. sweeper and removal-burn)
    "ramp": "ramp",                   # 2,455
    "draw": "draw",                   # 4,540 (itself a child of card-advantage)
    "counterspell": "counterspell",   # 563
    "board wipe": "sweeper",          # 985 (tag aliases: boardwipe, wipe, mass removal)
    "burn": "burn",                   # 3,210
    "lifegain": "lifegain",           # 2,789 (incl. gives-lifelink, drain-life, gainland)
}
ROLES = tuple(ROLE_TAGS)

FACE_FIELDS = ("name", "mana_cost", "type_line", "oracle_text", "colors", "power", "toughness", "loyalty", "defense")


def _now():
    return datetime.now(timezone.utc)


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def fold(text):
    """Loose matching key: lower case, no accents, straight quotes (phones type
    curly ones), single spaces and " // " between faces."""
    text = unicodedata.normalize("NFKD", text.translate(_QUOTES))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s*//\s*", " // ", text)
    return " ".join(text.split()).casefold()


# --- Building the index -----------------------------------------------------

def _iter_jsonl(path):
    """Yield one object per line of a .jsonl or .jsonl.gz file, never holding the whole file."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def _oracle_id(obj):
    # Reversible cards keep their oracle id on each face instead.
    return obj.get("oracle_id") or (obj.get("card_faces") or [{}])[0].get("oracle_id")


def _type_line(obj):
    """The object's type line, or its front face's when it has none of its own (reversible cards)."""
    return obj.get("type_line") or (obj.get("card_faces") or [{}])[0].get("type_line") or ""


def _full_type_line(obj):
    """Every face's type line, joined with " // " as Scryfall's all_parts gives it."""
    if obj.get("type_line"):
        return obj["type_line"]
    return " // ".join(face.get("type_line", "") for face in obj.get("card_faces") or [])


def _is_game_card(obj):
    return (obj["layout"] not in NON_GAME_LAYOUTS
            and obj["set_type"] not in NON_GAME_SET_TYPES
            # "Storm Counter" and friends; Role tokens printed as flip cards on The List
            and not _type_line(obj).startswith(("Card", "Token")))


def _token_kind(obj):
    """"token", "emblem", "reminder" or "helper" for a token-like object, or
    None for anything else (cards, art cards, checklists, minigames)."""
    layout, set_type, name = obj["layout"], obj.get("set_type"), obj["name"]
    type_line = _type_line(obj)
    faces = obj.get("card_faces") or []
    if set_type == "minigame" or layout == "art_series" or _CHECKLIST_RE.search(name):
        return None
    # Memorabilia: Jumpstart front cards (one is named "Treasure"), and World
    # Championship bios, decklists and blank cards, typed "Card".
    if set_type == "memorabilia" and (layout not in TOKEN_LAYOUTS or type_line == "Card"):
        return None
    if name in HELPER_NAMES:
        return "helper"
    if layout == "emblem" or (type_line.startswith("Emblem") and len(faces) < 2):
        return "emblem"
    if (type_line.startswith(("Card", "Dungeon"))
            or (layout == "double_faced_token" and faces
                and all(face.get("type_line", "").startswith(("Emblem", "Card", "Dungeon"))
                        for face in faces))):
        return "reminder"
    if type_line.startswith("Token") or layout in ("token", "double_faced_token"):
        return "token"
    return None


def _card_entry(obj):
    faces = obj.get("card_faces") or []
    front = faces[0] if faces else {}
    # In the library and in hand a multi-face card has only its front face's
    # characteristics (an adventure's creature, the front of a transform,
    # modal or flip card), except a split card, which has both halves'.
    # Scryfall's top-level type_line and mana_cost join the faces with " // ",
    # so those two come from the front face. Checked 2026-09-29: adventure,
    # prepare, flip, transform and modal_dfc all put the front face first.
    front_first = ("type_line", "mana_cost") if faces and obj["layout"] != "split" else ()

    def pick(key, default=None):
        # Transform and modal cards keep some fields (colors, P/T) only on their faces.
        if key in front_first and key in front:
            return front[key]
        value = obj.get(key)
        return front.get(key, default) if value is None else value

    if "oracle_text" in obj:
        text = obj["oracle_text"]
    else:
        text = "\n//\n".join(face.get("oracle_text", "") for face in faces)
    entry = {
        "name": obj["name"],
        "oracle_id": _oracle_id(obj),
        "layout": obj["layout"],
        "mana_cost": pick("mana_cost", ""),
        "cmc": obj.get("cmc", 0.0),
        "type_line": pick("type_line", ""),
        "oracle_text": text,
        "colors": pick("colors", []),
        "color_identity": obj.get("color_identity", []),
        "keywords": obj.get("keywords", []),
        "power": pick("power"),
        "toughness": pick("toughness"),
        "loyalty": pick("loyalty"),
        "defense": pick("defense"),
        "produced_mana": obj.get("produced_mana", []),
        "commander_legality": obj.get("legalities", {}).get("commander", "not_legal"),
        "game_changer": bool(obj.get("game_changer")),
    }
    if faces:
        entry["faces"] = [{k: face[k] for k in FACE_FIELDS if k in face} for face in faces]
    return entry


def _price(value):
    return float(value) if value else None


def _printing_entry(obj):
    prices = obj.get("prices") or {}
    # Double-faced printings have no top-level images; show the front face.
    images = obj.get("image_uris") or (obj.get("card_faces") or [{}])[0].get("image_uris") or {}
    faces = obj.get("card_faces") or []
    back = faces[1].get("image_uris", {}) if len(faces) > 1 else {}
    return {
        "name": obj["name"],
        "oracle_id": _oracle_id(obj),
        "finishes": obj.get("finishes", []),
        "games": obj.get("games", []),
        "digital": obj.get("digital", False),
        "usd": _price(prices.get("usd")),
        "usd_foil": _price(prices.get("usd_foil")),
        "usd_etched": _price(prices.get("usd_etched")),
        "image_small": images.get("small"),
        "image_normal": images.get("normal"),
        "image_small-back": back.get("small"),
        "image_normal-back": back.get("normal"),
        "released_at": obj.get("released_at"),
        "set_type": obj.get("set_type"),
        # The set's name (the Collection page's printing picker, and Deckbox
        # imports, which name the set). An index built before it was added
        # lacks it until the next weekly rebuild: readers use .get().
        "set_name": obj.get("set_name"),
        "oversized": obj.get("oversized", False),
    }


def _token_entry(obj, kind, image):
    """The token table's entry for a token object: its front face's P/T and
    colours (what a token usually shows), every face of a double-faced,
    reversible or flip card, and its picture (a [set, number] or None)."""
    faces = obj.get("card_faces") or []
    front = faces[0] if faces else {}

    def pick(key, default=None):
        value = obj.get(key)
        if value is None:
            value = front.get(key)
        return default if value is None else value

    if obj.get("oracle_text") is not None:
        text = obj["oracle_text"]
    else:
        text = "\n//\n".join(face.get("oracle_text", "") for face in faces)
    many = len(faces) > 1
    return {
        "name": obj["name"],
        "kind": kind,
        "layout": obj["layout"],
        "type_line": _full_type_line(obj),
        "power": pick("power"),
        "toughness": pick("toughness"),
        "colors": pick("colors", []),
        "keywords": obj.get("keywords", []),
        "text": text,
        "faces": [{"name": face.get("name", ""), "type_line": face.get("type_line", ""),
                   "power": face.get("power"), "toughness": face.get("toughness"),
                   "colors": face["colors"] if face.get("colors") is not None else pick("colors", []),
                   "text": face.get("oracle_text", "")} for face in faces] if many else [],
        "face_names": list(dict.fromkeys(face.get("name", "") for face in faces)) if many else [obj["name"]],
        "image": image,
    }


def _token_rank(obj, entry):
    """Sort key choosing a token's representative printing: paper, a token
    set, with a picture, newest; then the lowest set and collector number."""
    released = (entry["released_at"] or "").replace("-", "")
    return (entry["digital"], "paper" not in entry["games"], obj.get("set_type") != "token",
            entry["image_small"] is None, -int(released) if released.isdigit() else 0,
            obj["set"].lower(), obj["collector_number"])


def _read_tag_tree(tags_path):
    """({tag id: (child tag ids, oracle ids tagged directly)}, {slug: tag id})
    from an oracle_tags file."""
    tags = {}
    by_slug = {}
    for tag in _iter_jsonl(tags_path):
        tagged = {t["oracle_id"] for t in tag.get("taggings", [])}
        tags[tag["id"]] = (tag.get("child_ids", []), tagged)
        by_slug[tag["slug"]] = tag["id"]
    return tags, by_slug


def _tag_closure(tags, tag_id):
    """The oracle ids of a tag and of every tag below it (child_ids), since
    parent tags may hold no cards themselves."""
    oracle_ids, seen = set(), set()
    stack = [tag_id]
    while stack:
        tag_id = stack.pop()
        if tag_id in seen or tag_id not in tags:
            continue
        seen.add(tag_id)
        children, tagged = tags[tag_id]
        oracle_ids |= tagged
        stack.extend(children)
    return oracle_ids


def _role_oracle_ids(tags_path, log=print):
    """Return {role: set of oracle ids}, following each role's tag down through
    all its child tags."""
    tags, by_slug = _read_tag_tree(tags_path)
    members = {}
    for role, slug in ROLE_TAGS.items():
        if slug not in by_slug:
            log(f"Warning: oracle tag {slug!r} (role {role}) isn't in the tag file")
            members[role] = set()
        else:
            members[role] = _tag_closure(tags, by_slug[slug])
    return members


def build_index(cards_path, tags_path, bulk_dates=None, log=print):
    """Build the index from a default_cards file and an oracle_tags file
    (.jsonl or .jsonl.gz), streaming both. bulk_dates records each file's
    Scryfall updated_at.

    Each name goes to one oracle card. The few other game cards that share a
    name (Un-set cards printed in several versions, e.g. Very Cryptic Command
    49a-49f) go in "variants" by oracle id; printing_card() finds them."""
    printings = {}     # set -> collector number -> printing entry
    named = {}         # name -> {oracle id: (rank, card entry)}; lower rank wins a shared name
    by_oracle = {}     # oracle id -> [(set, collector number), ...]
    paper = set()      # oracle ids with a non-digital paper printing
    token_by_id = {}   # Scryfall printing id -> token oracle id
    token_best = {}    # token oracle id -> (rank, token entry); lower rank wins
    token_keys = {}    # (fold(name), type line) -> token oracle ids, for links to other printings
    parts = {}         # card oracle id -> {(printing id, name, type line, component)} it links to

    for obj in _iter_jsonl(cards_path):
        set_code, number = obj["set"].lower(), obj["collector_number"]
        entry = _printing_entry(obj)
        printings.setdefault(set_code, {})[number] = entry
        oracle_id = entry["oracle_id"]
        by_oracle.setdefault(oracle_id, []).append((set_code, number))
        if "paper" in entry["games"] and not entry["digital"]:
            paper.add(oracle_id)
        if _is_game_card(obj):
            rank = (obj["set_type"] in SIDE_SET_TYPES, entry["digital"], "paper" not in entry["games"])
            same_name = named.setdefault(obj["name"], {})
            if oracle_id not in same_name or rank < same_name[oracle_id][0]:
                same_name[oracle_id] = (rank, _card_entry(obj))
            # Some printings lack links (Beast Within, Hornet Queen), so every printing's count.
            for part in obj.get("all_parts") or []:
                if (part.get("component") in ("token", "combo_piece") and part.get("id")
                        and part["id"] != obj.get("id")):
                    parts.setdefault(oracle_id, set()).add(
                        (part["id"], part.get("name", ""), part.get("type_line", ""), part["component"]))
            continue
        kind = _token_kind(obj)
        if kind is None:
            continue
        if obj.get("id"):
            token_by_id[obj["id"]] = oracle_id
        token_keys.setdefault((fold(obj["name"]), _full_type_line(obj)), set()).add(oracle_id)
        rank = _token_rank(obj, entry)
        if oracle_id not in token_best or rank < token_best[oracle_id][0]:
            image = [set_code, number] if entry["image_small"] else None
            token_best[oracle_id] = (rank, _token_entry(obj, kind, image))

    role_ids = _role_oracle_ids(tags_path, log)

    def newest_first(oracle_id):
        return sorted(by_oracle.get(oracle_id, []), reverse=True,
                      key=lambda k: (printings[k[0]][k[1]]["released_at"] or "", k))

    tokens = {}
    for oracle_id, (_, entry) in sorted(token_best.items()):
        entry["printings"] = [list(k) for k in newest_first(oracle_id)
                              if "paper" in printings[k[0]][k[1]]["games"]
                              and not printings[k[0]][k[1]]["digital"]]
        tokens[oracle_id] = entry
    unmatched = 0       # links to real cards (combo pieces such as Forest) or to unknown printings

    def made_by(card):
        """(token oracle ids, unresolved part names) for the parts a card links to."""
        nonlocal unmatched
        found, names = set(), set()
        front = card["faces"][0]["name"] if card.get("faces") else card["name"]
        makes_tokens = (bool(_TOKEN_WORD_RE.search(card["oracle_text"] or ""))
                        or bool(SELF_TOKEN_KEYWORDS.intersection(card["keywords"])))
        for part_id, name, type_line, component in sorted(parts.get(card["oracle_id"], ())):
            oracle_id = token_by_id.get(part_id)
            if oracle_id is None:
                # The link lands on a printing that isn't a token: match by name and type line.
                matches = token_keys.get((fold(name), type_line), set())
                if len(matches) > 1:
                    names.add(name)         # several tokens fit; don't guess
                    continue
                if not matches:
                    unmatched += 1
                    continue
                oracle_id = next(iter(matches))
            if tokens[oracle_id]["kind"] == "helper":
                continue
            if component == "token" and fold(name) == fold(front) and not makes_tokens:
                continue                    # the card's own token printing, not something it makes
            found.add(oracle_id)
        return found, names

    def complete(card):
        oracle_id = card["oracle_id"]
        card["printings"] = [list(k) for k in newest_first(oracle_id)]
        card["paper"] = oracle_id in paper
        card["roles"] = [role for role in ROLES if oracle_id in role_ids[role]]
        found, names = made_by(card)
        if found:
            card["tokens"] = sorted(found)          # token oracle ids
        if names:
            card["token_names"] = sorted(names)     # links that fit several tokens
        return card

    cards, variants = {}, {}
    for name in sorted(named):
        # Best rank first; a tie (Un-set variants) goes to the lowest set and
        # collector number, so the choice doesn't depend on the file's order.
        ranked = sorted(named[name].items(), key=lambda item: (item[1][0], min(by_oracle[item[0]])))
        cards[name] = complete(ranked[0][1][1])
        for oracle_id, (_, card) in ranked[1:]:
            variants[oracle_id] = complete(card)
    if unmatched:
        log(f"{unmatched:,} card links matched no token (combo pieces that are real cards, mostly)")

    return {
        "version": INDEX_VERSION,
        "built_at": _now().isoformat(timespec="seconds"),
        "bulk": dict(bulk_dates or {}),
        "roles": {role: {"tag": ROLE_TAGS[role], "oracle_cards": len(role_ids[role])} for role in ROLES},
        "cards": cards,
        "variants": variants,
        "printings": printings,
        "tokens": tokens,
    }
