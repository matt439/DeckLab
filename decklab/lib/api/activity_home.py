"""Pure home-space audit visibility and summary helpers."""
from decklab.lib import permissions


def own_space(scope, profiles, me):
    """Name a member's space as theirs; home remains shared."""
    if scope == "all":
        space = (profiles.get(me) or {}).get("space") if me else None
    else:
        space = scope.get("space")
    return space if isinstance(space, str) and space and space != permissions.HOME else None


def home_viewer(scope, profiles, me):
    """Existing kit/packing visibility, including an unnamed local script."""
    if scope == "all":
        return me is None or ((profiles.get(me) or {}).get("space") or permissions.HOME) == permissions.HOME
    return scope["space"] == permissions.HOME


def commander_night_row(row, scope, profiles, me):
    """Only a home viewer sees that household notes changed, never their raw content."""
    if scope == "all":
        allowed = me is None or (me in profiles and permissions.sees_commander_night(profiles[me]))
    else:
        allowed = scope.get("space") == permissions.HOME
    if not allowed:
        return None
    after = row.get("after")
    cleared = row.get("op") == "DELETE" or (isinstance(after, dict) and after.get("content") is None)
    return {"table": "commander_night", "op": row.get("op"),
            "summary": "Commander-night notes cleared" if cleared else "Commander-night notes updated"}


def visibility_row(row, scope, profiles, me):
    """A switch's audit words belong only to its space; accessory flips belong to home.
    Public switches never make their own Activity rows public."""
    records = [r for r in (row.get("before"), row.get("after")) if isinstance(r, dict) and r]
    if not records:
        return None
    for record in records:
        owner, thing = record.get("owner"), record.get("thing")
        if not isinstance(owner, str) or thing not in ("collection", "decks", "games", "accessories"):
            return None
        space = permissions.HOME if thing == "accessories" else owner
        if scope != "all" and scope["space"] != space:
            return None
    record = records[-1]
    owner, thing = record["owner"], record["thing"]
    if thing == "accessories":
        who = "the shared" if owner == "shared" else f"{(profiles.get(owner) or {}).get('name', owner)}'s"
        target = f"{who} sleeves, deck boxes and playmats"
    else:
        who = "the home" if owner == permissions.HOME else "your"
        if owner != permissions.HOME and owner != own_space(scope, profiles, me):
            name = next((p["name"] for p in profiles.values() if p.get("space") == owner), owner)
            who = f"{name}'s"
        target = f"{who} {thing}"
    state = "private" if row.get("op") == "DELETE" else "public"
    return f"Made {target} {state}"
