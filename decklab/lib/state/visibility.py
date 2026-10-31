"""The switches' shared value rules; this module never makes a request public.

State stores return {(owner, thing): {by, by_id, since}}. Only Public switches
have entries. Callers take their own copy; an absent key always means Private.
Permissions and readiness belong to the callers, before invoking a write.
"""
import re

from . import Invalid

OWNER = re.compile(r"[a-z0-9_-]{1,64}")
SPACE_THINGS = ("collection", "decks", "games")
SHARED = "shared"               # lib/accessories.py's owner of the kit every home profile uses
THINGS = SPACE_THINGS + ("accessories",)


def _home_profiles():
    """{id: name} of config.json's home profiles; {} when it can't be read (fail closed)."""
    try:
        from decklab.lib import profiles
        return {p["id"]: p["name"] for p in profiles.read() if p["space"] == profiles.HOME}
    except Exception:           # noqa: BLE001 - an unreadable config offers no personal kit owner
        return {}


def kit_owners():
    """The accessory owners a switch may belong to (E11-S48): each home profile and SHARED.
    Reads config.json, so only switch() (every write) checks it, never key(), which readers
    use (the command line's read notices don't read the config); db check checks the rows."""
    return tuple(sorted(_home_profiles())) + (SHARED,)


def key(owner, thing):
    if not isinstance(owner, str) or not OWNER.fullmatch(owner):
        raise Invalid("Bad visibility owner")
    if not isinstance(thing, str) or thing not in THINGS:
        raise Invalid("A visibility switch must be collection, decks, games or accessories")
    return owner, thing


def switch(owner, thing, on):
    pair = key(owner, thing)
    if thing == "accessories" and owner not in kit_owners():
        raise Invalid("An accessories switch must belong to a kit owner")
    if type(on) is not bool:
        raise Invalid("A visibility switch must be Public or Private (true or false)")
    return pair


def message(owner, thing, public):
    """Fixed audit wording, shared by the page and the home-only command line."""
    switch(owner, thing, public)
    state_word = "public" if public else "private"
    if thing == "accessories":
        subject = "the shared" if owner == SHARED else f"{_home_profiles().get(owner, owner)}'s"
        return f"Make {subject} sleeves, deck boxes and playmats {state_word}"
    subject = "the home" if owner == "home" else "my"
    return f"Make {subject} {thing} {state_word}"


def view(rows):
    """Rows (owner, thing, set_by, set_by_name, ISO since) as a switch snapshot."""
    return {(owner, thing): {"by": name, "by_id": actor, "since": since}
            for owner, thing, actor, name, since in rows}
