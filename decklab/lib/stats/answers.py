"""What a Commander deck's interaction can answer (E9-S35), from Scryfall's oracle tags: for each kind of
thing an opponent's deck leans on (creatures, artifacts, enchantments, planeswalkers, any nonland
permanent, graveyards, spells on the stack) the deck's cards that can deal with it, split into targeted and
mass, and by when they can be used.

Tagger's `removal` tree keeps what a card hits in its child tags (removal-creature, removal-artifact, ...),
which card_index.py merges into the flat removal role; this reads them straight from the tag file with
cards.tag_members (no card-index change). A tag's members include every tag below it, as the roles count
them, so a card that removes any permanent (removal-permanent, below each of the kind tags) counts for every
kind of permanent, and a Naturalize (disenchant-naturalize) for both artifacts and enchantments.

Kinds and their tags (KINDS; TAGS_CHECKED is the day they were compared with the real oracle_tags file):
    creature, artifact, enchantment, planeswalker   removal-<kind>
    nonland                                         removal-nonland or removal-permanent
    graveyard                                       hate-graveyard
    stack                                           counterspell (abilities countered included)
Targeted or mass (SPLITS), for each family of kinds:
    permanents   mass: sweeper (one-sided sweepers and overloads included); targeted: spot-removal or
                 multi-removal. A card in both is listed in both (Vandalblast, Cyclonic Rift); a card in
                 neither is "not split" (the tags don't say).
    graveyard    mass: sweeper-graveyard or graveyard-seal (Rest in Peace, Bojuka Bog); targeted: the rest.
    stack        mass: counterspell-sweeper or counterspell-automatic (counters every such spell); targeted:
                 the rest.
Removal under the removal tag that hits none of the kinds (land removal, equipment, or a card whose target
isn't tagged, such as Krosan Grip) is listed apart as "other" (not worked out while a permanent kind's tag
is missing, since that kind's cards would land there).

Speed is read from the card, not the tags: "instant" for an instant (any face you cast) or a card with flash,
"sorcery" for a sorcery, else "permanent": an ability or an enters trigger, whose timing isn't read.

A tag the file doesn't have makes its kind "not checked" (never zero), and a missing split tag leaves that
family's cards "not split"; no tag file at all makes the whole answer {"checked": False, "reason"}. The
counts only inform: nothing here changes the bracket or blocks a save.
"""
from decklab.lib import cards

from .cardtext import card_list, type_words

TAGS_CHECKED = "2026-11-12"     # the tag names below, compared with Scryfall's oracle_tags bulk file

PERMANENT, GRAVEYARD, STACK = "permanent", "graveyard", "stack"

KINDS = (
    {"kind": "creature", "label": "Creatures", "family": PERMANENT, "tags": ("removal-creature",)},
    {"kind": "artifact", "label": "Artifacts", "family": PERMANENT, "tags": ("removal-artifact",)},
    {"kind": "enchantment", "label": "Enchantments", "family": PERMANENT, "tags": ("removal-enchantment",)},
    {"kind": "planeswalker", "label": "Planeswalkers", "family": PERMANENT, "tags": ("removal-planeswalker",)},
    {"kind": "nonland", "label": "Any nonland permanent", "family": PERMANENT,
     "tags": ("removal-nonland", "removal-permanent")},
    {"kind": "graveyard", "label": "Graveyards", "family": GRAVEYARD, "tags": ("hate-graveyard",)},
    {"kind": "stack", "label": "Spells on the stack", "family": STACK, "tags": ("counterspell",)},
)

# family: (mass tags, targeted tags or None for "every card of the kind that isn't mass")
SPLITS = {
    PERMANENT: (("sweeper",), ("spot-removal", "multi-removal")),
    GRAVEYARD: (("sweeper-graveyard", "graveyard-seal"), None),
    STACK: (("counterspell-sweeper", "counterspell-automatic"), None),
}
REMOVAL_TAG = "removal"

SPEEDS = (
    ("instant", "Instant speed", "instants and cards with flash"),
    ("sorcery", "Sorcery speed", "sorceries"),
    ("permanent", "On a permanent", "an ability or an enters trigger; its timing isn't read"),
)
MODES = (
    ("targeted", "Targeted"),
    ("mass", "Mass"),
    ("unsplit", "Not split"),
)


def all_tags():
    """Every tag slug the answer reads, in a stable order."""
    slugs = [REMOVAL_TAG]
    for kind in KINDS:
        slugs.extend(kind["tags"])
    for mass, targeted in SPLITS.values():
        slugs.extend(mass)
        slugs.extend(targeted or ())
    return list(dict.fromkeys(slugs))


def read_tags(path=None):
    """({slug: frozenset of oracle ids}, [slugs the file doesn't have]) for all_tags(). Raises OSError (and
    ValueError for a file that isn't JSON lines) when the tag file can't be read at all. A slug the file
    lacks is left out (the file is read once either way), so the others still count."""
    slugs = all_tags()
    found = cards.tag_members(slugs, path, missing_ok=True)
    return found, [slug for slug in slugs if slug not in found]


def speed(card):
    """"instant", "sorcery" or "permanent" (see the module docstring)."""
    lines = [card.get("type_line", "")] + [face.get("type_line", "") for face in card.get("faces") or []]
    words = set().union(*(type_words(line) for line in lines))
    if "Instant" in words or "Flash" in (card.get("keywords") or []):
        return "instant"
    if "Sorcery" in words:
        return "sorcery"
    return "permanent"


def _union(tags, slugs):
    return frozenset().union(*(tags[slug] for slug in slugs))


def _group(entries):
    """{"count": distinct cards, "cards": [{name, qty}]}."""
    return {"count": len({e.name for e in entries}), "cards": card_list(entries)}


def _kind_answer(kind, entries, tags, missing):
    absent = [slug for slug in kind["tags"] if slug in missing]
    base = {"kind": kind["kind"], "label": kind["label"], "family": kind["family"], "tags": list(kind["tags"])}
    if absent:
        return {**base, "checked": False, "reason": "Scryfall's oracle tags have no "
                + " or ".join(f"“{slug}”" for slug in absent) + " tag, so this wasn't checked."}
    ids = _union(tags, kind["tags"])
    hits = [e for e in entries if e.card["oracle_id"] in ids]
    mass_tags, targeted_tags = SPLITS[kind["family"]]
    split_missing = [slug for slug in (*mass_tags, *(targeted_tags or ())) if slug in missing]
    modes = {key: [] for key, _ in MODES}
    if split_missing:
        modes["unsplit"] = hits
    else:
        mass = _union(tags, mass_tags)
        targeted = _union(tags, targeted_tags) if targeted_tags else None
        for e in hits:
            oid = e.card["oracle_id"]
            is_mass = oid in mass
            is_targeted = (oid in targeted) if targeted is not None else not is_mass
            if is_mass:
                modes["mass"].append(e)
            if is_targeted:
                modes["targeted"].append(e)
            if not is_mass and not is_targeted:
                modes["unsplit"].append(e)
    speeds = {key: [e for e in hits if speed(e.card) == key] for key, _, _ in SPEEDS}
    return {**base, "checked": True, **_group(hits),
            "split_checked": not split_missing,
            "split_reason": ("Scryfall's oracle tags have no " + ", ".join(f"“{s}”" for s in split_missing)
                             + " tag, so targeted and mass weren't told apart.") if split_missing else None,
            "modes": {key: _group(found) for key, found in modes.items()},
            "speeds": {key: _group(found) for key, found in speeds.items()}}


def answers(entries, path=None, tags_date=None):
    """stats["answers"] for a Commander deck's main-deck entries (Commander, Companion and Deck):

    {"checked": True, "tags_date", "tags_checked": TAGS_CHECKED, "kinds": [kind], "gaps": [labels of
    checked kinds with no card], "unchecked": [labels of kinds not checked], "other": {"checked", "count",
    "cards"} (removal hitting none of the kinds), "speeds": [{"speed", "label", "about"}],
    "modes": [{"mode", "label"}]}
    kind: {"kind", "label", "family", "tags", "checked": False, "reason"} or {"kind", "label", "family",
    "tags", "checked": True, "count", "cards", "split_checked", "split_reason", "modes": {mode: {"count",
    "cards"}}, "speeds": {speed: {"count", "cards"}}}

    or {"checked": False, "reason", "tags_date"} when there's no tag file to read."""
    try:
        tags, missing = read_tags(path)
    except (OSError, ValueError) as error:
        return {"checked": False, "tags_date": tags_date,
                "reason": f"Scryfall's oracle tags couldn't be read ({error}), so what the deck can answer "
                          "wasn't worked out. Updating the card data downloads them."}
    kinds = [_kind_answer(kind, entries, tags, missing) for kind in KINDS]
    permanent_kinds = [k for k in KINDS if k["family"] == PERMANENT]
    if REMOVAL_TAG in missing or any(slug in missing for k in permanent_kinds for slug in k["tags"]):
        other = {"checked": False, "count": 0, "cards": []}       # an unread kind's cards would land here
    else:
        hit = frozenset().union(*(_union(tags, k["tags"]) for k in permanent_kinds))
        others = [e for e in entries if e.card["oracle_id"] in tags[REMOVAL_TAG] and e.card["oracle_id"] not in hit]
        other = {"checked": True, **_group(others)}
    return {"checked": True, "tags_date": tags_date, "tags_checked": TAGS_CHECKED, "kinds": kinds,
            "gaps": [k["label"] for k in kinds if k["checked"] and not k["count"]],
            "unchecked": [k["label"] for k in kinds if not k["checked"]],
            "other": other,
            "speeds": [{"speed": key, "label": label, "about": about} for key, label, about in SPEEDS],
            "modes": [{"mode": key, "label": label} for key, label in MODES]}
