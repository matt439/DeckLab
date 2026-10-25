"""The switches' shared value rules; this module never makes a request public.

State stores return {(owner, thing): {by, by_id, since}}. Only Public switches
have entries. Callers take their own copy; an absent key always means Private.
Permissions and readiness belong to the callers, before invoking a write.
"""
import re

from . import Invalid

OWNER = re.compile(r"[a-z0-9_-]{1,64}")
SPACE_THINGS = ("collection", "decks", "games")
KIT_OWNERS = ("matt", "user1", "shared")
THINGS = SPACE_THINGS + ("accessories",)


def key(owner, thing):
    if not isinstance(owner, str) or not OWNER.fullmatch(owner):
        raise Invalid("Bad visibility owner")
    if not isinstance(thing, str) or thing not in THINGS:
        raise Invalid("A visibility switch must be collection, decks, games or accessories")
    if thing == "accessories" and owner not in KIT_OWNERS:
        raise Invalid("An accessories switch must belong to a kit owner")
    return owner, thing


def switch(owner, thing, on):
    pair = key(owner, thing)
    if type(on) is not bool:
        raise Invalid("A visibility switch must be Public or Private (true or false)")
    return pair


def message(owner, thing, public):
    """Fixed audit wording, shared by the page and the home-only command line."""
    switch(owner, thing, public)
    state_word = "public" if public else "private"
    if thing == "accessories":
        subject = {"matt": "Matt's", "user1": "User1's", "shared": "the shared"}[owner]
        return f"Make {subject} sleeves, deck boxes and playmats {state_word}"
    subject = "the home" if owner == "home" else "my"
    return f"Make {subject} {thing} {state_word}"


def view(rows):
    """Rows (owner, thing, set_by, set_by_name, ISO since) as a switch snapshot."""
    return {(owner, thing): {"by": name, "by_id": actor, "since": since}
            for owner, thing, actor, name, since in rows}
