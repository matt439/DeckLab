"""Optional one-label proposals from existing role metadata, never a saved category.

Specific disruption wins before general roles. The priority is fixed and public;
unknown metadata has no suggestion and a builder's existing label always wins.
"""
PRIORITY = (("board wipe", "Board wipe"), ("counterspell", "Counterspell"),
            ("removal", "Removal"), ("draw", "Draw"), ("ramp", "Ramp"))


def suggest(card):
    if not isinstance(card, dict) or not isinstance(card.get("roles"), (tuple, list)):
        return None
    return next((label for role, label in PRIORITY if role in card["roles"]), None)
