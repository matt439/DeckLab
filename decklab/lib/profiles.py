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

Local status reports those rejected entries by position, code and static reason. Setup and
config-backed profile sync use read_checked() to refuse a partial list before any change;
read() and parse() remain tolerant request readers and expose no diagnostics.
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
ISSUE_REASONS = {
    "profiles_type": "profiles must be a list.",
    "entry_type": "Each profile entry must be an object.",
    "invalid_id": "id must use lowercase letters, digits and single hyphens, at most 40 characters.",
    "reserved_id": "id is reserved for the audit trail's own actors.",
    "duplicate_id": "id repeats an earlier usable profile entry.",
    "invalid_name": "name must be text.",
    "invalid_space": "space must be home or the profile's own non-reserved id.",
    "invalid_plays_as": "A home profile needs plays_as set to user, wife or either.",
}


class InvalidProfiles(ValueError):
    """A local preflight refusal. Its public message never contains configuration values."""

    def __init__(self, issues):
        self.issues = issues
        super().__init__("Profile configuration has invalid entries. Run python -m decklab.lib.homenet status "
                         "for local diagnostics; fix decklab/config.json before syncing or setup.")


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
    return parse_with_diagnostics(listed, access=access)[0]


def parse_with_diagnostics(listed, access=False):
    """(Usable profiles, rejected-entry diagnostics), without changing parse's normalization.

    Each issue has a one-based index (None for the list itself), a stable code and a static
    reason. No submitted value is copied into a diagnostic. Role and email fallbacks stay
    compatible; only entries the existing parser leaves out are diagnosed here.
    """
    from decklab.lib.decks import PLAYERS
    issues = []

    def reject(index, code):
        issues.append({"index": index, "code": code, "reason": ISSUE_REASONS[code]})

    if not isinstance(listed, list):
        reject(None, "profiles_type")
        return [], issues
    legacy_mode = not access and legacy(listed)
    out, seen = [], set()
    for index, p in enumerate(listed, 1):
        if not isinstance(p, dict):
            reject(index, "entry_type")
            continue
        if not valid_id(p.get("id")):
            reject(index, "invalid_id")
            continue
        if p["id"] in seen:
            reject(index, "duplicate_id")
            continue
        if p["id"] in RESERVED_IDS:
            reject(index, "reserved_id")
            continue
        if not isinstance(p.get("name"), str):
            reject(index, "invalid_name")
            continue
        space = p.get("space", HOME)
        if space == HOME:
            if p.get("plays_as") not in PLAYERS:
                reject(index, "invalid_plays_as")
                continue
            plays_as = p["plays_as"]
        elif space == p["id"] and space not in RESERVED_SPACES:
            plays_as = None
        else:
            reject(index, "invalid_space")
            continue
        role = "admin" if legacy_mode else (p.get("role") if p.get("role") in ROLES else "member")
        out.append({"id": p["id"], "name": p["name"], "role": role, "space": space,
                    "plays_as": plays_as, "emails": _emails(p.get("emails"))})
        seen.add(p["id"])
    return out, issues


def read(settings=None):
    """The profiles from config.json (or from settings, an already loaded config.load()).
    Raises OSError or ValueError when config.json can't be read."""
    if settings is None:
        from decklab.lib import profile_config
        settings = profile_config.read_settings()
    return parse(settings.get("profiles") or [], access=settings.get("access") is not None)


def read_checked(settings=None):
    """Local setup/sync preflight: reject a partial usable list before any side effect.

    Missing profiles is still an empty configuration; an explicitly malformed profiles value
    is diagnosed. Request readers keep using read(), whose tolerant behavior is unchanged.
    """
    if settings is None:
        from decklab.lib import profile_config
        settings = profile_config.read_settings()
    listed, issues = parse_with_diagnostics(settings.get("profiles", []), access=settings.get("access") is not None)
    if issues:
        raise InvalidProfiles(issues)
    return listed


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
