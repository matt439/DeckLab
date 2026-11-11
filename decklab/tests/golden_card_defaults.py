"""Narrow compatibility for additive intrinsic categories and unavailable triple data.

Old physical/private facts and all counted bracket values still compare. Only
the exact role-derived proposal and exact missing-triple default are omitted;
wrong labels, matched triples, malformed metadata and unknown-card states stay.
"""
PRIORITY = (("board wipe", "Board wipe"), ("counterspell", "Counterspell"),
            ("removal", "Removal"), ("draw", "Draw"), ("ramp", "Ramp"))
UNAVAILABLE = {"checked": False, "reason": "Commander Spellbook's three-card data couldn't be read; three-card combos weren't checked."}
LEGACY_LIMIT = ("Two-card combos (game-enders, lockouts or infinites): none in Brackets 1-2, none before "
    "turn 6 in Bracket 3. Deck Lab looks for Commander Spellbook's two-card combos only: combos "
    "of three or more cards, combos needing a card that isn't named (\"a creature with power 4 or "
    "more\") and your intent aren't checked, how early a combo can win isn't judged, and the "
    "list can miss combos.")
CURRENT_LIMIT = ("Two-card combos (game-enders, lockouts or infinites): none in Brackets 1-2, none before "
    "turn 6 in Bracket 3. Deck Lab lists Commander Spellbook's named two- and three-card combos; "
    "three-card findings never raise this minimum. Combos of four or more cards, combos needing a card that isn't named (\"a creature with power 4 or "
    "more\") and your intent aren't checked, how early a combo can win isn't judged, and the "
    "list can miss combos.")


def normalise(value):
    if isinstance(value, dict):
        if {"name", "type_line", "img", "img_small", "roles"} <= value.keys() and isinstance(value["roles"], list):
            expected = next((label for role, label in PRIORITY if role in value["roles"]), None)
            if expected is not None and value.get("category_suggestion") == expected:
                value.pop("category_suggestion")
        if (value.get("three_card_combos") == UNAVAILABLE and isinstance(value.get("size"), dict)
                and isinstance(value.get("bracket"), dict)):
            limits = value["bracket"].get("not_automatic")
            if isinstance(limits, list):
                value["bracket"]["not_automatic"] = [LEGACY_LIMIT if line == CURRENT_LIMIT else line for line in limits]
            value.pop("three_card_combos")
        for child in value.values():
            normalise(child)
    elif isinstance(value, list):
        for child in value:
            normalise(child)
