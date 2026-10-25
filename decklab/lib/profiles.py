"""The people in decklab/config.json's "profiles", read and checked once for every module.

Each profile is a dict:

    {"id": "user1", "name": "User1", "role": "member", "space": "home",
     "plays_as": "wife", "emails": ["someone@example.com"]}

- id: a deck slug of at most 40 characters, unique;
- name: shown on the page and in the change history;
- role: "admin" (edits everything) or "member" (edits only what's theirs:
  lib/permissions.py). A config where no profile names a role is an older
  one, written before roles existed: every profile is then an admin, so it
  keeps working as before on the home network ("legacy mode"). Once any
  profile has a role, or the config has an "access" block (the tunnel's
  logins: lib/access.py), a profile without one, or with a value that isn't
  admin or member, is a member (the safer reading of a typo). Logins through
  the tunnel are refused while legacy() holds (access.Verifier), so a
  config that forgot its roles never hands an outside visitor everything;
- space: "home" (the shared collection: magic/collection.csv and friends),
  or the profile's own id for a person's space under magic/people/<id>/
  (lib/spaces.py). Default "home". Any other value, or a person space whose
  id lib/spaces.py reserves (home, casual, commander, product, pairing,
  people), leaves the profile out;
- plays_as: which home deck's "Played by" is theirs (user, wife or either).
  Required for a home profile, as before; None for a person space, whose
  decks are theirs by where they live;
- emails: the lowercase addresses Cloudflare Access may sign for this
  person (for picking the profile of a request over the tunnel). Only ASCII
  addresses are kept, compared after ASCII lowercasing (email_key): an
  address with other characters is left out, never matched. Never sent to
  the page: public() leaves them out.

config.json is written by hand, so entries the page couldn't use are left
out rather than failing every request: a bad or repeated id, an id the
database's audit trail keeps for its own actors (RESERVED_IDS: claude,
system, test and home, "someone at home"), no name, or a home profile
without a valid plays_as.
"""
from decklab.lib import config

ROLES = ("admin", "member")
HOME = "home"
# Person-space ids that would clash with a deck id's first part or the people folder.
RESERVED_SPACES = frozenset({HOME, "casual", "commander", "product", "pairing", "people"})
MAX_ID = 40
# Actors the audit trail names that aren't profiles (decklab.lib.state.Actor): a profile with
# one of these ids would be mistaken for them.
RESERVED_IDS = frozenset({"claude", "system", "test", HOME})


def valid_id(profile_id):
    """True for a profile id: lowercase letters, digits and single hyphens, at most MAX_ID long."""
    from decklab.lib import decks
    return isinstance(profile_id, str) and len(profile_id) <= MAX_ID and decks.valid_slug(profile_id)


def email_key(value):
    """An email address as Deck Lab compares it: trimmed and ASCII-lowercased,
    or None for one that's blank, not text or not all ASCII (an address
    with other characters could be told apart from a listed one only by
    Unicode rules, so it's never matched)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or not value.isascii():
        return None
    return value.lower()


def _emails(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        key = email_key(item)
        if key is not None and key not in out:
            out.append(key)
    return out


def legacy(listed):
    """True for an older config's "profiles" where no profile names a role
    (every profile is then an admin on the home network)."""
    return not any(isinstance(p, dict) and "role" in p for p in listed or [])


def parse(listed, access=False):
    """The usable profiles in config.json's "profiles" value, in its order (see
    the module docstring). access: the config has an "access" block, so a
    missing role means member even when no profile names one."""
    from decklab.lib.decks import PLAYERS
    if not isinstance(listed, list):
        return []
    legacy_mode = not access and legacy(listed)
    out, seen = [], set()
    for p in listed:
        if not (isinstance(p, dict) and valid_id(p.get("id")) and p["id"] not in seen
                and p["id"] not in RESERVED_IDS and isinstance(p.get("name"), str)):
            continue
        space = p.get("space", HOME)
        if space == HOME:
            if p.get("plays_as") not in PLAYERS:
                continue
            plays_as = p["plays_as"]
        elif space == p["id"] and space not in RESERVED_SPACES:
            plays_as = None
        else:
            continue
        role = "admin" if legacy_mode else (p.get("role") if p.get("role") in ROLES else "member")
        out.append({"id": p["id"], "name": p["name"], "role": role, "space": space,
                    "plays_as": plays_as, "emails": _emails(p.get("emails"))})
        seen.add(p["id"])
    return out


def read(settings=None):
    """The profiles from config.json (or from settings, an already loaded config.load()).
    Raises OSError or ValueError when config.json can't be read."""
    settings = config.load() if settings is None else settings
    return parse(settings.get("profiles") or [], access=settings.get("access") is not None)


def public(profile):
    """A profile as the page may see it: everything but its emails."""
    return {k: v for k, v in profile.items() if k != "emails"}


def find(profile_id, listed=None):
    """The profile with that id, or None."""
    listed = read() if listed is None else listed
    return next((p for p in listed if p["id"] == profile_id), None)


def for_email(email, listed=None):
    """The one profile listing email (compared without case), or None when none
    or more than one does."""
    email = email_key(email)
    if email is None:
        return None
    listed = read() if listed is None else listed
    found = [p for p in listed if email in p["emails"]]
    return found[0] if len(found) == 1 else None
