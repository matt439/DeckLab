"""Commander role targets (E9-S26): how many cards of each kind the Command Zone's deck-building template
asks a Commander deck for, set beside the Stats tab's role counts.

The template is the Command Zone podcast's "Commander Deckbuilding Template for the New Era", episode 658,
published on YouTube on 2025-02-18 (SOURCE; looked up 2026-10-31). The episode page (its show notes and
chapters) names the categories, lands, card advantage, ramp, targeted disruption, mass disruption and plan
cards, but not the numbers, which are said in the episode. The numbers come from three written summaries
of episode 658 (SOURCE["figures_from"]), which all give 38 lands, 10 ramp, 12 card advantage, 12 targeted
disruption and 6 mass disruption. They differ in two places: note.com gives ramp as 10 to 12 (12 for a
commander costing 4 or more; 10 is used here), and for plan cards note.com and farseek give about 30, saying
the categories overlap so they add to more than 100, while the GitHub copy gives about 22, adding to exactly
100. About 30 is used here. The episode's own advice is to treat them as a starting point, not rules (episode 659, "The
Problem with Deckbuilding Templates", is about when to leave them).

Deck Lab's roles (cards.ROLES, from Scryfall's oracle tags) aren't the template's categories, so each
category says what Deck Lab counts for it (CATEGORIES "measure") and how that differs:
    lands                 the deck's lands (front faces), as the Lands panel counts them
    ramp                  the ramp role
    card advantage        the draw role only: narrower than the template's card advantage
    targeted disruption   removal or counterspell cards that aren't board wipes (Scryfall's removal
                          tag holds its sweeper tag, so the removal bar counts board wipes too)
    mass disruption       the board wipe role (Scryfall's sweeper tag) only
    plan                  no Deck Lab role: the deck's own plan, the commander included; not counted

Nothing here is fetched: the figures are fixed until someone looks the template up again (change CHECKED
and the figures together).
"""

SOURCE_ID = "command-zone-658"
CHECKED = "2026-10-31"
EPISODE = 658
EPISODE_DATE = "2025-02-18"

SOURCE = {
    "title": "Commander Deckbuilding Template for the New Era (The Command Zone, episode 658)",
    "date": f"episode of {EPISODE_DATE}; figures checked {CHECKED} against written summaries of it",
    "url": "https://www.youtube.com/watch?v=OSNV6224cHg",
    # The episode's show notes have the categories but not the numbers; these summaries have the numbers.
    # All three agree on lands, card advantage and both disruptions; note.com gives ramp as 10-12, and the
    # GitHub copy gives about 22 plan cards (adding to exactly 100) where the other two give about 30.
    "figures_from": [
        "https://note.com/black777cat/n/n588a5c571b7d",
        "https://github.com/OlliTapio/mtg-deck-optimizer/blob/main/command_zone_template.md",
        "https://farseek.ai/blog/how-to-analyze-your-commander-deck",
    ],
}

# The template's categories in the episode's order of the template. "roles": the Deck Lab roles whose cards
# count (any of them), "except": roles whose cards don't, "lands": count the deck's lands instead; a category
# with neither isn't counted. "role_bar": the Stats role bar the target is drawn on (only where the role is
# the category's whole measure), else None.
CATEGORIES = (
    {"category": "lands", "label": "Lands", "target": 38, "about": False, "lands": True, "roles": (),
     "except": (), "role_bar": None,
     "measure": "Lands in the deck, as the Lands panel counts them (front faces)."},
    {"category": "ramp", "label": "Ramp", "target": 10, "about": False, "lands": False, "roles": ("ramp",),
     "except": (), "role_bar": "ramp",
     "measure": "The Ramp role (Scryfall's ramp tag)."},
    {"category": "card advantage", "label": "Card advantage", "target": 12, "about": False, "lands": False,
     "roles": ("draw",), "except": (), "role_bar": "draw",
     "measure": "The Card draw role only (Scryfall's draw tag), so fewer cards than the template's card "
                "advantage, which counts other ways of getting extra cards too."},
    {"category": "targeted disruption", "label": "Targeted disruption", "target": 12, "about": False,
     "lands": False, "roles": ("removal", "counterspell"), "except": ("board wipe",), "role_bar": None,
     "measure": "Removal or counterspell cards that aren't board wipes. The Removal bar counts board wipes "
                "too, so it isn't this number."},
    {"category": "mass disruption", "label": "Mass disruption", "target": 6, "about": False, "lands": False,
     "roles": ("board wipe",), "except": (), "role_bar": "board wipe",
     "measure": "The Board wipes role only (Scryfall's sweeper tag); the template counts other effects on "
                "many of the other players' cards at once too."},
    {"category": "plan", "label": "Plan cards", "target": 30, "about": True, "lands": False, "roles": (),
     "except": (), "role_bar": None,
     "measure": "No Deck Lab role: the cards for the deck's own plan, the commander included. Not counted."},
)


def status(count, target):
    """"below", "at" or "above" the target, or None when the category isn't counted."""
    if count is None:
        return None
    return "below" if count < target else "at" if count == target else "above"


def role_targets(main, land_count):
    """The template's categories for a Commander deck's main deck (Commander + Companion + Deck entries, as
    the role bars count them): {"source": SOURCE_ID, "episode", "episode_date", "checked", "categories":
    [{"category", "label", "target", "about", "count" (None: not counted), "status", "roles", "except",
    "role_bar", "measure"}], "by_role": {role: category} for the role bars that carry a target}."""
    out = []
    for c in CATEGORIES:
        if c["lands"]:
            count = land_count
        elif c["roles"]:
            count = sum(e.qty for e in main
                        if any(r in e.card.get("roles", []) for r in c["roles"])
                        and not any(r in e.card.get("roles", []) for r in c["except"]))
        else:
            count = None
        out.append({"category": c["category"], "label": c["label"], "target": c["target"], "about": c["about"],
                    "count": count, "status": status(count, c["target"]), "roles": list(c["roles"]),
                    "except": list(c["except"]), "role_bar": c["role_bar"], "measure": c["measure"]})
    return {"source": SOURCE_ID, "episode": EPISODE, "episode_date": EPISODE_DATE, "checked": CHECKED,
            "categories": out,
            "by_role": {c["role_bar"]: c["category"] for c in CATEGORIES if c["role_bar"]}}
