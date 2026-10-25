"""Profiles (the people in config.json, read by lib/profiles.py), each profile's saved settings
(GET and PUT /api/profiles/<id>/settings, kept in the state store: decklab.lib.state's
profile_setting table), and _writer, the profile every write is made by.

The store keeps the values as saved; what each setting may be, and its default, are here
(SETTINGS), so a value that isn't allowed any more is dropped when it's read.
"""
from decklab.lib import access, config, permissions, profiles as profile_list, state

from . import common
from .common import MAX_BODY, ApiError, _load_json, _public, state_errors

# Each setting and the values it may take; the first is the default.
# matchup_games is the number of games a matchup page offers first (forge.GAME_CHOICES).
# matchup_mode and field_budget are wave 3's (forge-trial/sim-wave3-contract.md section 17): how a
# new matchup run plays ("assess", "ahead" or "fixed": matchup_games) and a field run's budget.
SETTINGS = {"theme": ("system", "light", "dark"), "matchup_games": ("800", "200", "400", "1600", "3200"),
            "matchup_mode": ("assess", "ahead", "fixed"), "field_budget": ("standard", "quick", "thorough")}
DEFAULT_SETTINGS = {key: values[0] for key, values in SETTINGS.items()}

# The audit trail's actor for a change at home when the page's chooser names nobody known.
HOME_ACTOR = ("home", "someone at home")

_odd_error_logged = False       # logged an error the store doesn't name (_current_settings)


def _valid_profile_id(profile_id):
    return profile_list.valid_id(profile_id)


def _config_profiles(emails=False):
    """The usable profiles in config.json (profiles.read: entries the page
    couldn't use are skipped), each {id, name, plays_as, role, space}, plus
    "emails" only when emails is true: they're never sent to the page.
    ApiError 500 when config.json can't be read."""
    try:
        listed = profile_list.read(config.load())
    except (OSError, ValueError) as e:
        raise ApiError(500, f"decklab/config.json can't be read: {_public(e)}") from None
    keys = ("id", "name", "plays_as", "role", "space") + (("emails",) if emails else ())
    return [{k: p[k] for k in keys} for p in listed]


def profiles():
    """GET /api/profiles: the roster this request may see (E10-S38, decision C),
    {"profiles": [...], "admins": [names]}, never anyone's emails.

    - A script naming nobody (guard.script()): every profile in config.json,
      each {id, name, plays_as (None for a person space), role, space}.
    - A named viewer (the tunnel's login, or the profile picked at home): the
      profiles of its own space as above (home's two for Matt and User1, only
      himself for User5), then each profile whose space has something public
      (_public_spaces: none until E10-S28's switches) by {id, name} only.
    - The home network naming nobody (the page before "Who are you?"): the
      home profiles the chooser offers, as a home viewer gets them.
    - Anything else (a login that isn't set up): no profiles.

    "admins" is the admins' display names, for "ask Matt" wording (empty in
    an older config where everyone is an admin); it says nothing of their
    role, space or plays_as."""
    from . import guard
    listed = _config_profiles()
    admins = _admin_names(listed)
    if guard.script():
        return {"profiles": listed, "admins": admins}
    try:
        viewer = guard.viewer()
    except ApiError:
        return {"profiles": [], "admins": admins}
    if viewer is None and not guard.local():
        return {"profiles": [], "admins": admins}
    own = (viewer or {}).get("space") or permissions.HOME
    public = _public_spaces() - {own}
    shown = [p for p in listed if _space(p) == own]
    shown += [{"id": p["id"], "name": p["name"]} for p in listed if _space(p) in public]
    return {"profiles": shown, "admins": admins}


def _space(profile):
    return profile.get("space") or permissions.HOME


def _public_spaces():
    """Spaces with public decks, collections, games or accessories: their profiles are
    named, with no role, settings or other private profile fields (E10-S38)."""
    from . import guard
    public = frozenset(guard.public_deck_spaces()) | guard.public_spaces("collection") | guard.public_spaces("games")
    owners = guard.public_owners("accessories")
    return public | {permissions.HOME for owner in owners if owner == "shared"} | {
        _space(profile) for profile in _config_profiles() if profile["id"] in owners}


def _admin_names(listed):
    """The admins' display names, in config.json's order: [] when every profile counts as an
    admin because none has a role (profiles.legacy), so an older config's roster isn't told."""
    try:
        settings = config.load()
    except (OSError, ValueError):
        return []
    if settings.get("access") is None and profile_list.legacy(settings.get("profiles") or []):
        return []
    return [p["name"] for p in listed if p.get("role") == "admin"]


def _require_profile(profile_id):
    """The profile in config.json (as _config_profiles gives it); ApiError 404 when there's none."""
    if _valid_profile_id(profile_id):
        for profile in _config_profiles():
            if profile["id"] == profile_id:
                return profile
    raise ApiError(404, f"No profile {profile_id!r}")


# The 403 for GET /api/profiles/<id>/settings to anyone but that profile (E10-S34), whether or not
# the id is a profile, so it names nobody and tells nothing of who else uses Deck Lab.
SETTINGS_HIDDEN = "You can only see your own settings."


def own_settings_id(profile_id):
    """profile_id when this request may read that profile's settings: its own (the viewer's
    id), or any for a script naming nobody; else None. The matchup and field pages' defaults
    ask it too, so another profile's settings are never read for them."""
    from . import guard
    if guard.script():
        return profile_id
    try:
        viewer = guard.viewer()
    except ApiError:
        return None
    return profile_id if viewer is not None and viewer["id"] == profile_id else None


def _checked(saved):
    """The saved settings over the defaults; values that aren't valid any more are dropped."""
    settings = dict(DEFAULT_SETTINGS)
    for key, allowed in SETTINGS.items():
        if saved.get(key) in allowed:
            settings[key] = saved[key]
    return settings


def _current_settings(profile_id):
    """A profile's settings, as get_settings gives them, for the answers that must work while
    the database is down (the matchup and field pages' defaults): when the store can't be read,
    the values this server last read or wrote, else the defaults. Never raises: an error the
    store doesn't name (a raw database error) falls back the same way, and the log says so (once
    until a read works again: the matchup page asks often)."""
    global _odd_error_logged
    store = state.store()
    try:
        saved = store.settings(profile_id)
        _odd_error_logged = False
    except Exception as e:
        if not isinstance(e, state.StateError) and not _odd_error_logged:
            _odd_error_logged = True
            common._log(f"The settings couldn't be read ({_public(e)}); using the last ones known until they can")
        try:
            saved = store.settings_cached(profile_id)
        except Exception:
            saved = {}
    return _checked(saved)


def get_settings(profile_id):
    """GET /api/profiles/<id>/settings: saved settings, or the defaults. Only the viewer's own
    (E10-S34: an admin's role reads no one else's, User1's included), and any for a script
    naming nobody: ApiError 403 (SETTINGS_HIDDEN) before the id is looked up, so a missing
    profile and someone else's answer alike (the 404 only to a script). ApiError 503 when
    the database can't be read (the page keeps the device's theme)."""
    from . import guard
    if not guard.script() and own_settings_id(profile_id) is None:
        raise ApiError(403, SETTINGS_HIDDEN)
    _require_profile(profile_id)
    with state_errors():
        return _checked(state.store().settings(profile_id))


def _web_actor(profile):
    """The state.Actor a change from the page is made by, for the audit trail: profile (a dict
    from _config_profiles), or "someone at home" for None, with the listener it came through."""
    via = "home" if access.current() is None else "tunnel"
    if profile is None:
        return state.Actor(*HOME_ACTOR, via=via)
    return state.Actor(profile["id"], profile["name"], via=via)


def _parse_settings(body):
    """The settings in a request body: a JSON object of known keys and values."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > MAX_BODY:
        raise ApiError(413, f"The settings are limited to {MAX_BODY} bytes")
    data = _load_json(body, "The settings")
    if not isinstance(data, dict):
        raise ApiError(400, 'The settings must be a JSON object, like {"theme": "dark"}')
    for key, value in data.items():
        if key not in SETTINGS:
            raise ApiError(400, f"Unknown setting {key!r}; the settings are: {', '.join(SETTINGS)}")
        if not isinstance(value, str) or value not in SETTINGS[key]:
            raise ApiError(400, f"{key} must be one of: {', '.join(SETTINGS[key])}")
    return data


def put_settings(profile_id, body):
    """PUT /api/profiles/<id>/settings with a JSON body such as {"theme": "dark"}.

    Only the keys given change (the rest keep their saved values), so a later
    setting can be added without the page resetting it, and nothing is
    written when every value is already as saved. The store decides that
    inside its write, so a value saved meanwhile by something else (an
    import) isn't skipped because of this server's cached read; the message
    names the keys that differ from that read (every key given when none
    do). Returns every setting as saved to a viewer who may read them
    (own_settings_id: their own, or a script naming nobody); an admin changing
    another profile of his space gets back only the keys he sent, as saved
    (E10-S34: a PUT, an empty one too, never reads someone else's settings).
    ApiError 503 when the database can't be used.

    The audit trail names who changed it: through the tunnel the login, at
    home the profile the page's chooser names (guard.viewer()), or "someone
    at home" when it names nobody known. That viewer may change only its own
    settings (settings.edit), at home as through the tunnel; a script
    naming nobody (guard.script()) may change any."""
    from . import guard
    # The permission first, so a profile that doesn't exist is refused as someone else's is.
    guard.require(guard.viewer(), "settings.edit", profile_id)
    profile = _require_profile(profile_id)
    changes = _parse_settings(body)
    store = state.store()
    with state_errors():
        saved = store.settings(profile_id)
        if changes:
            changed = [key for key, value in changes.items() if saved.get(key) != value] or list(changes)
            saved = store.settings_put(profile_id, changes, _web_actor(guard.viewer()),
                                       f"Change {profile['name']}'s settings: {', '.join(changed)}")
    settings = _checked(saved)
    if own_settings_id(profile_id) is None:
        return {key: settings[key] for key in changes}
    return settings


def _writer(data):
    """The profile a write is made by: data["profile"] must be one in
    config.json (ApiError 403 otherwise), and through the tunnel the login's
    own (server.py makes it so; this is the second check). On the home
    network, when the X-Deck-Lab-Viewer header names a profile (the page's
    chooser), the body must name the same one (403 otherwise, as through the
    tunnel); a script sending no header names itself by the body alone. It
    is the change's actor, and its own rights decide what it may change
    (lib/api/guard.py's check), wherever the request comes from."""
    profile_id = data.get("profile")
    identity = access.current()
    if identity is not None and profile_id != identity["profile"]:
        raise ApiError(403, "You can only make changes as yourself")
    named = access.viewer() if identity is None else None
    if named and profile_id != named:
        raise ApiError(403, "You can only make changes as yourself")
    for profile in _config_profiles():
        if profile["id"] == profile_id:
            return profile
    raise ApiError(403, "Choose who you are first: the page didn't say whose change this is, or that person "
                        "isn't in decklab/config.json. Reload the page and pick your name.")
