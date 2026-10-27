"""Who may change what (HISTORY.md, "Accounts and member collections").

Pure functions: everything they need is passed in (a profile from
lib/profiles.py, the deck facts from a library summary or a DeckFile), so
the server can ask them on every write route and the page can hide what the
server would refuse. Nothing here reads a file except summary(), which asks
lib/spaces.py for the list of spaces when it isn't given (sees_play_record
only asks lib/spaces.py how to split a deck id).

The rules:

- a profile has the same rights wherever it asks from: on the home network
  (the profile the page's chooser names) exactly as through the tunnel (the
  login's), so User1 picked on the shared iPad can't change what she
  couldn't change from outside, and User2 picked there only his own space;
- a script naming nobody may do everything: it has no profile whose
  rights could apply. A script is code outside any request (a job thread,
  a test, the command line) or a request on the home listener from
  loopback that sends X-Deck-Lab-Script: 1 (lib/access.py's script(), which
  lib/api/guard.py passes in as script=). Any other request naming nobody
  (a phone on the Wi-Fi, the PC's browser before a profile is picked) gets
  no profile's rights and sees only what's open to everyone;
- an admin writes only in his own space (E10-S29, private by default): every
  deck there (any Played by), new decks there, its collection and tokens,
  play records with one of its decks, and its decks' tables; with home's
  admin-only actions below when that space is home. The admin role opens
  nothing in another space: Matt asks Claude, and the command line still
  writes every space;
- a member may change:
  - decks in their own space, or (a home member such as User1) home decks
    whose Played by is their plays_as. "either" is the house's, which counts
    as Matt's, so it's never a member's. New decks only in their own space,
    or at home Played by them;
  - the collection and tokens of their own space, home's included for a
    home member (User1 changes home's as Matt can, E10-S43);
  - their own wishlist and settings (an admin those of his own space's profiles too);
  - play records that involve at least one deck they can change;
  - the owned-vs-needed tables of decks they can change;
- accessories: each home profile its own and the shared ones
  (accessory_owners), whatever its role: not even an admin changes
  another's. The route checks the row's owner and the deck's; this only
  says whether the profile has any;
- receipts, products and orders: a home admin only (home's records, which
  never leave home: sees_home_records);
- Commander-night notes: home profiles read them; only a home admin changes them.
  An admin in another space does not override that privacy;
- runs (matchup, field, variant and goldfish): everyone; stopping one ("run.stop": a
  matchup, field run or variant test) requires a visible run that the viewer started
  or that uses a deck from their space. An admin or script may stop any run; the API
  gives an admin only an anonymous system item for a hidden run (E10-S31);
- starting a Forge run ("run.start": a matchup, field run, variant test or its
  "Play more") follows the simulations setting an admin picks
  (lib/api/simulations.py): everyone, admins only, or paused (nobody), by
  the profile's role; only a script naming nobody (a script) passes
  whatever the setting, even paused. Changing that setting
  ("simulations.edit") is an admin's, by role.

Two rules are about seeing rather than changing. The sleeves, deck boxes
and playmats (magic/accessories.csv, its pictures, the decks' Sleeves and
Deck box lines and status.csv's sleeves and deck_box columns) are the
home's, and each row has an owner: a home profile's id or "shared"
(lib/accessories.py). accessory_owners says which owners a profile sees:
its own id and shared for a home profile (Matt sees Matt's and shared, an
admin no more than that), none for a person with their own space, and
everything for a script that names nobody (a request naming nobody
that isn't a script sees none).
sees_accessories is whether that's any at all.

A wishlist is private to its owner (sees_wishlist): only the profile
whose list it is sees it, on its page or on the Activity page. Unlike
accessories, nobody else does: not an admin, not another home profile,
and not a request naming nobody, a script's included (the page before
anyone is chosen has no wishlist to show), since the page always names its
viewer once a profile is chosen. Through the tunnel the viewer is the login's
profile. The PC's command line (python -m decklab.db wishlist, sql) still
reads and changes any list: it doesn't go through these rules.

The inventory is read by space (sees_inventory, E10-S29): a space's
collection and tokens are seen only by the profiles of that space (home's
by Matt and User1, User2's only by User2), whatever their role: the
admin role opens no other space's. Home's records (the orders, products,
watchlist, receipts and packing plan) are sees_home_records': the home
profiles only, and never anyone else even once E10-S28's switches make
home's collection public. A script naming nobody sees all of it, as for
accessories, and any other request naming nobody (the page before anyone is
chosen, a phone on the Wi-Fi, the tunnel without a profile) none. On the home network the viewer is
the profile the page's chooser names, so User2 picked there sees only
his own, as through the tunnel. The Shopping and Receipts pages, the
collection and tokens pages, the packing plan, a precon's preview and the
printing picker's copy counts (lib/api/guard.py has the list) and the
inventory rows on the Activity page all ask this one rule. A deck page
still shows its owned-vs-needed from its own space's pool, to whoever may
see the deck, as its deck file's table does.

The Activity page (lib/api/activity.py) shows the database's audit trail
by activity_scope: everything to an admin (by role, as for the simulations
setting) and to a script naming nobody, except wishlist rows,
which only their owner sees (sees_wishlist); anyone else sees the changes
in their own space (a home profile the home profiles', a person their own;
the inventory's rows by sees_inventory), and through the tunnel with no
profile, or at home a request naming nobody that isn't a script,
nothing.

The Game log's records (real games and sideboard plans, GET /api/play and
the play_record rows on the Activity page) are seen by sees_play_record:
a script naming nobody sees every one; anyone else, an admin included
(E10-S29: the admin role opens no other space), only those with one of
their own space's decks in them (a game's two
sides, a plan's deck only: E10-S32), so Matt and User1 see every game with
a home deck and a member only the games and plans of their own decks,
never the household's (inside a game they see, api/play_records.py names a
side of a deck they may not see only by its space, decision G); a request naming nobody that isn't a script
(at home or through the tunnel) sees none. A deck id that can't be read counts only for those who see every one.

The decks are read by space (sees_deck, E10-S30): a deck is seen only by
the profiles of its own space (home's, product decks and Beginner Box
pairings included, by Matt and User1; User2's only by User2), whatever
their role: the admin role doesn't open another space's decks. A script
naming nobody sees every deck; any other request naming nobody sees none.
A deck that isn't seen answers exactly as a missing one (the routes' 404
"No deck X"), so nothing confirms it exists. E10-S28's decks switches will
add the spaces that made their decks public (the public= argument, empty
until then); an ordered or preordered product's decks never leave home
(home_only=).

Everything else is open to read.

Actions and their targets:

    "deck.edit"        a deck: a mapping with "space" and "player" (a library
                       summary), or a DeckFile (.space, .player)
    "deck.create"      {"space": ..., "player": ...}; a None player means the
                       route fills in the profile's plays_as
    "tables.update"    a deck, as for deck.edit
    "play.record"      the decks of the game (an iterable of decks)
    "collection.edit"  a space id
    "tokens.edit"      a space id
    "wishlist.edit"    a profile id
    "settings.edit"    a profile id
    "accessories.edit"  no target: whether the profile has accessories of its own to change
    "receipts.apply", "products.edit", "orders.edit"   no target: a home admin
    "run"              no target
    "run.stop"         {"visible", "by_id", "spaces"}; original starter id and deck spaces;
                       without a target only an admin or script passes
    "run.start"        the simulations setting's mode: "everyone", "admins" or "paused"
    "simulations.edit" no target
    "commander_night.edit" no target: a home admin, or an unnamed script
    "members.edit"     no target: an explicitly named home admin (private Settings panel)

    from decklab.lib import permissions
    permissions.can(profile, "deck.edit", summary, script=False)
    permissions.reason(profile, "collection.edit", "home")   # None, or why not in plain words
    permissions.accessory_owners(profile, script=False)       # the owners whose accessories it sees (None: all)
    permissions.sees_accessories(profile, script=False)       # may see any sleeves, deck boxes and playmats
    permissions.sees_wishlist(profile, "user1", script=False)  # may see User1's wishlist (only User1)
    permissions.sees_inventory(profile, "home", script=False)  # may see home's collection and tokens
    permissions.sees_home_records(profile, script=False)      # may see home's orders, products, receipts...
    permissions.inventory_spaces(profile, script=False)       # the spaces whose inventory it sees (None: all)
    permissions.summary(profile, script=False)                # for GET /api/me
    permissions.activity_scope(profile, script=False)         # "all", {"space", "profile"}, or None
    permissions.sees_play_record(profile, ["casual/gruul", "user2/casual/elves"], script=False)
    permissions.sees_deck(profile, "home", script=False)      # may see a deck of home's (its space)
    permissions.deck_spaces(profile, script=False)            # the spaces whose decks it sees (None: all)
"""
HOME = "home"
EITHER = "either"               # the house's decks; they count as Matt's

DECK_ACTIONS = ("deck.edit", "tables.update")
SPACE_ACTIONS = ("collection.edit", "tokens.edit")
OWN_ACTIONS = ("wishlist.edit", "settings.edit")
ADMIN_ACTIONS = ("receipts.apply", "products.edit", "orders.edit")
ACTIONS = (DECK_ACTIONS + SPACE_ACTIONS + OWN_ACTIONS + ADMIN_ACTIONS
           + ("accessories.edit", "deck.create", "play.record", "run", "run.start", "run.stop",
              "simulations.edit", "commander_night.edit", "members.edit"))
RUN_MODES = ("everyone", "admins", "paused")    # the simulations setting (lib/api/simulations.py)
RUNS_PAUSED = "Simulations are paused for now, while the PC is busy. Saved results still show; try again later."
RUNS_ADMINS = "Only an admin can start simulations right now. Saved results still show."
RUNS_STOP_ADMINS = "You can stop a run you started or one using a deck from your own collection."
# Refusals to someone outside the home name no space or person (E10-S38, decision C), and the
# simulations ones above no admin (E10-S34, decision F).
ACCESSORIES_PRIVATE = "The sleeves, deck boxes and playmats are private."
COMMANDER_NIGHT_PRIVATE = "Commander-night notes are private."
SHARED = "shared"               # lib/accessories.py's SHARED: the owner of what every home profile uses

_ADMIN_WORDS = {"receipts.apply": "receipts", "products.edit": "products", "orders.edit": "orders"}


def _get(target, key, default=None):
    """A deck's fact from a mapping (a library summary) or an object (a DeckFile)."""
    if isinstance(target, dict):
        return target.get(key, default)
    return getattr(target, key, default)


def _space_of(profile):
    return profile.get("space") or HOME


def is_admin(profile, *, script=False):
    """True for an admin profile (by role, wherever it asks from), or for a
    script naming nobody (script: lib/access.py's script()). A profile named on the home
    network has only its own rights there, as through the tunnel."""
    if profile:
        return profile.get("role") == "admin"
    return bool(script)


def sees_commander_night(profile, *, script=False):
    """Household venue notes belong to home, including when an outsider is an admin."""
    return _space_of(profile) == HOME if profile else bool(script)


def accessory_owners(profile, *, script=False):
    """The owners (lib/accessories.py's owner column) whose sleeves, deck
    boxes and playmats profile may change: frozenset({its id, SHARED})
    for a home profile, whatever its role; an empty set for a person with
    their own space; with no profile, None (everything) for a script and
    nothing for any other request (the page before anyone is chosen, the
    tunnel)."""
    if not profile:
        return None if script else frozenset()
    if _space_of(profile) != HOME:
        return frozenset()
    return frozenset({profile["id"], SHARED})


def accessory_readers(profile, *, script=False, public=frozenset()):
    """The owners whose kit may be read: the writable own/shared set plus Public
    owners. Public never adds a write right; a script naming nobody reads all."""
    owners = accessory_owners(profile, script=script)
    return None if owners is None else frozenset(owners) | frozenset(public)


def sees_accessories(profile, *, script=False, public=frozenset()):
    """True when profile reads any own/shared or Public sleeves, boxes or playmats."""
    owners = accessory_readers(profile, script=script, public=public)
    return owners is None or bool(owners)


def sees_wishlist(profile, owner_id, *, script=False):
    """True only when profile is the wishlist's owner (owner_id is its
    profile id): not an admin, not someone else at home, and not a
    request naming nobody, a script's included. script doesn't widen it; it's taken so that the
    callers ask this as they ask the other rules."""
    return bool(profile) and isinstance(owner_id, str) and profile.get("id") == owner_id


def sees_inventory(profile, space, *, script=False, public=frozenset()):
    """True for the viewer's own collection/tokens or a space in public
    (E10-S28); no admin override. A script naming nobody sees every space.
    Home's orders, products, watchlist and receipts remain sees_home_records';
    raw imports are never served by these readers. Activity uses activity_scope
    independently, so public collections never publish their audit trail."""
    spaces = inventory_spaces(profile, script=script, public=public)
    return spaces is None or (isinstance(space, str) and space in spaces)


def inventory_spaces(profile, *, script=False, public=frozenset()):
    """The spaces whose inventory profile sees (sees_inventory): None for
    every space's (a script naming nobody), else a list: the profile's own
    space (an admin's too, E10-S29) plus the supplied public collection spaces.
    A request naming nobody that isn't a script sees only public collections."""
    if not profile:
        return None if script else sorted(public)
    return sorted({_space_of(profile), *public})


def sees_home_records(profile, *, script=False):
    """True when profile may see home's records: the orders, products,
    watchlist, receipts, their checks and the packing plan, and home's pool
    warnings about them (order and product files, status lines). Only a
    home profile (Matt, User1) or a script naming nobody: never anyone
    else, whatever the switches say once home's collection can be public
    (E10-S29)."""
    if not profile:
        return bool(script)
    return _space_of(profile) == HOME


def activity_scope(profile, *, script=False):
    """Which changes of the audit trail the Activity page shows profile:
    "all" only for a script naming nobody; otherwise the viewer's own space
    and profile, with system rows for an admin. Public visibility never widens
    Activity. lib/api/activity.py has each table's rules. None (nothing) for
    any other request naming nobody."""
    if not profile:
        return "all" if script else None
    return {"space": _space_of(profile), "profile": profile["id"], "system": is_admin(profile)}


def sees_play_record(profile, deck_ids, *, script=False, space_of=None, public=frozenset()):
    """True when profile may see a game or sideboard plan whose decks are
    deck_ids (a game's sides, a plan's deck only: E10-S32, a plan belongs
    to its deck's space, so callers pass only its deck): a script naming
    nobody sees every one; anyone else, an admin included, a record naming a
    deck of their own space or a space in public. Callers pass games' public
    switches only for games: sideboard plans and Activity never widen.
    space_of(deck_id) is a deck id's space, None when it
    can't be read (by default lib/spaces.py's split_deck_id); a deck id that
    can't be read, or isn't text, counts only for those who see every one.
    The Game log (GET /api/play) and Activity both use it, with their own scope."""
    if not profile and script:
        return True
    if space_of is None:
        space_of = _deck_space
    seen = set(public)
    if profile:
        seen.add(_space_of(profile))
    return any(isinstance(d, str) and space_of(d) in seen for d in (deck_ids or ()))


def deck_spaces(profile, *, script=False, public=frozenset()):
    """The spaces whose decks profile sees (sees_deck), sorted: None for
    every space's (a script naming nobody); else its own space plus public
    (the spaces whose decks switch is on: E10-S28, none until it ships),
    or for any other request naming nobody only public. No admin branch:
    an admin by role sees his own space's decks, as anyone does."""
    if not profile:
        return None if script else sorted(public)
    return sorted({_space_of(profile), *public})


def sees_deck(profile, space, *, script=False, public=frozenset(), home_only=False):
    """True when profile may see a deck of space (its id's space; home's
    for a product deck or a pairing): a script naming nobody every deck;
    anyone else a deck of their own space, or of a space in public
    (deck_spaces). home_only is for a deck that never leaves home whatever
    the switches say (the decks of an ordered or preordered product): then
    only a home profile, or a script, sees it. A space that can't be read
    (None) counts only for a script. The one rule every deck reader asks
    (lib/api/guard.py's sees_deck)."""
    if not profile and script:
        return True
    if not isinstance(space, str):
        return False
    if home_only and space == HOME and not (profile and _space_of(profile) == HOME):
        return False
    seen = deck_spaces(profile, script=script, public=public)
    return seen is None or space in seen


def _deck_space(deck_id):
    """A deck id's space, or None when it can't be read (lib/spaces.py's
    space_of would say home, showing a record of unknown owner at home)."""
    from decklab.lib import spaces
    try:
        return spaces.split_deck_id(deck_id)[0]
    except ValueError:
        return None


def _deck_reason(profile, deck):
    """None when profile may change deck (deck.edit, tables.update, a play record's side):
    a deck of its own space; at home, an admin any home deck and a member those Played by
    them. An admin's role opens no other space's decks (E10-S29)."""
    space = _get(deck, "space") or HOME
    own = _space_of(profile)
    if space != HOME:
        return None if space == own else "That deck is in someone else's collection."
    if own != HOME:
        return "That's one of the home decks; you can change the decks in your own collection."
    if profile.get("role") == "admin":
        return None
    player = _get(deck, "player")
    plays_as = profile.get("plays_as")
    if plays_as and plays_as != EITHER and player == plays_as:
        return None
    return "You can change the home decks played by you."


def _by_role(profile, action, target, script):
    """reason() for "run.start" and "simulations.edit": by the profile's role, as every rule is,
    except that a script naming nobody passes even while runs are paused (the module
    docstring)."""
    if not profile:
        return None if script else "Choose who you are first."
    admin = profile.get("role") == "admin"
    if action == "simulations.edit":
        return None if admin else "Only an admin can change the simulations setting."
    if target not in RUN_MODES:
        raise ValueError(f"unknown simulations mode {target!r}")
    if target == "paused":
        return RUNS_PAUSED
    if target == "admins" and not admin:
        return RUNS_ADMINS
    return None


def reason(profile, action, target=None, *, script=False):
    """None when profile may do action to target, else why not, in plain
    words. ValueError for an action that isn't in ACTIONS (a mistake in the
    caller, never a refusal)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if action == "members.edit":
        return None if profile and profile.get("id") and profile.get("role") == "admin" \
            and _space_of(profile) == HOME else "Member settings are private to a home admin."
    if action == "commander_night.edit":
        if not sees_commander_night(profile, script=script):
            return COMMANDER_NIGHT_PRIVATE
        return None if is_admin(profile, script=script) else "Only a home admin can change Commander-night notes."
    if action == "accessories.edit":
        owners = accessory_owners(profile, script=script)
        if owners is None or owners:
            return None
        if not profile:
            return "Choose who you are first."
        return ACCESSORIES_PRIVATE
    if action in ("run.start", "simulations.edit"):
        return _by_role(profile, action, target, script)
    if action == "run.stop":
        if is_admin(profile, script=script):
            return None
        if profile and isinstance(target, dict) and target.get("visible") and (
                target.get("by_id") == profile.get("id") or _space_of(profile) in (target.get("spaces") or [])):
            return None
        return RUNS_STOP_ADMINS if profile else "Choose who you are first."
    if action == "run":
        return None
    if not profile:
        return None if script else "Choose who you are first."
    # A named profile: its own rights, an admin's only in his own space (E10-S29).
    admin = profile.get("role") == "admin"
    if action in ADMIN_ACTIONS:
        if admin and _space_of(profile) == HOME:
            return None
        return f"Only an admin can change the {_ADMIN_WORDS[action]}."
    if action in DECK_ACTIONS:
        return _deck_reason(profile, target)
    if action == "deck.create":
        space = _get(target, "space") or HOME
        player = _get(target, "player")
        if space != HOME:
            return None if space == _space_of(profile) else "You can only add decks to your own collection."
        if _space_of(profile) != HOME:
            return "You can only add decks to your own collection."
        if admin:
            return None
        plays_as = profile.get("plays_as")
        if plays_as and plays_as != EITHER and player in (None, plays_as):
            return None
        return "A home deck you add is played by you."
    if action == "play.record":
        decks_ = list(target or ())
        if any(_deck_reason(profile, d) is None for d in decks_):
            return None
        return "A game you record needs one of your decks in it."
    if action in SPACE_ACTIONS:
        # Its own space's, home's for a home member too (E10-S43); an admin no other (E10-S29).
        what = "collection" if action == "collection.edit" else "tokens"
        if target == _space_of(profile):
            return None
        return f"You can only change your own {what}."
    # OWN_ACTIONS: one's own; an admin's also those of his own space's profiles (E10-S29)
    if target == profile.get("id") or admin and _profile_space(target) == _space_of(profile):
        return None
    return "You can only change your own " + ("wishlist." if action == "wishlist.edit" else "settings.")


def _profile_space(profile_id):
    """The space of the config.json profile profile_id names (lib/profiles.py), None when there's
    no such profile or config.json can't be read (so it matches no space)."""
    from decklab.lib import profiles
    try:
        found = profiles.find(profile_id)
    except (OSError, ValueError):
        return None
    return _space_of(found) if found else None


def can(profile, action, target=None, *, script=False):
    """True when profile may do action to target (see reason)."""
    return reason(profile, action, target, script=script) is None


def visibility_controls(profile, *, vis=None, ready=()):
    """Only this profile's ready switches; an admin has no ownership override.
    A script naming nobody has no personal switches to offer through the page."""
    from decklab.lib.state.visibility import SPACE_THINGS
    if not profile:
        return []
    vis = vis or {}
    own = _space_of(profile)
    keys = [(own, thing) for thing in SPACE_THINGS if thing in ready]
    if "accessories" in ready:
        keys += [(owner, "accessories") for owner in sorted(accessory_owners(profile))]
    return [{"owner": owner, "thing": thing, "public": (owner, thing) in vis} for owner, thing in keys]


def summary(profile, *, script=False, space_ids=None, vis=None, ready=()):
    """What profile may change, as JSON for the page (GET /api/me):

        {"admin": bool, "spaces": [space ids whose collection and tokens it
         may change], "deck_spaces": [space ids where it may change every
         deck], "home_player": the Played by of the home decks it may change
         (a home member's plays_as) or None, "create": [{"space", "player"}]
         where it may add decks (player None: any; only in a space whose
         decks it sees, as POST /api/decks checks, E10-S30), "receipts", "products",
         "orders": bool, "accessories": whether it has accessories to change
         (accessories.edit), "runs": True, "see_accessories": whether it may
         see any sleeves, deck boxes and playmats (sees_accessories),
         "accessory_owners": the owners it may change, sorted (None:
         all; accessory_owners), "accessory_readers": its own/shared and Public kit owners,
         "visibility": its own ready Public/Private controls, "see_inventory": the spaces whose
         collection and tokens it may see, sorted (None: all;
         inventory_spaces), "see_home_records": whether it may see the
         shopping, receipts and packing plan (sees_home_records)}

    A named profile gets the same answer with script false (its own
    rights, wherever it asks from), an admin's only in his own space
    (E10-S29); only a script naming nobody may change every space.
    space_ids is every space (spaces.space_ids() when not given). vis is the request's complete
    Public-switch snapshot; ready is the set of categories whose publication controls are built.
    Public read rights never change the writable spaces, owners or create choices."""
    if space_ids is None:
        from decklab.lib import spaces
        space_ids = spaces.space_ids()
    space_ids = list(space_ids)
    vis = vis or {}
    public = lambda thing: {owner for owner, kind in vis if kind == thing and owner in space_ids}
    admin = is_admin(profile, script=script)
    owners = accessory_owners(profile, script=script)
    readers = accessory_readers(profile, script=script,
                                public={owner for owner, kind in vis if kind == "accessories"})
    seen = inventory_spaces(profile, script=script, public=public("collection"))
    out = {"admin": admin, "runs": True, "see_accessories": readers is None or bool(readers),
           "accessories": can(profile, "accessories.edit", script=script),
           "accessory_owners": None if owners is None else sorted(owners),
           "accessory_readers": None if readers is None else sorted(readers),
           "visibility": visibility_controls(profile, vis=vis, ready=ready),
           "see_inventory": None if seen is None else sorted(seen),
           "see_home_records": sees_home_records(profile, script=script),
           **{key: can(profile, action, script=script) for key, action in
              (("receipts", "receipts.apply"), ("products", "products.edit"), ("orders", "orders.edit"))}}
    if not profile:
        if not script:
            return {**out, "spaces": [], "deck_spaces": [], "home_player": None, "create": []}
        return {**out, "spaces": space_ids, "deck_spaces": space_ids, "home_player": None,
                "create": [{"space": s, "player": None} for s in space_ids]}
    own = _space_of(profile)
    mine = [own] if own == HOME or own in space_ids else []
    if own != HOME or admin:
        return {**out, "spaces": mine, "deck_spaces": mine, "home_player": None,
                "create": [{"space": own, "player": None}] if mine else []}
    plays_as = profile.get("plays_as")
    player = plays_as if plays_as and plays_as != EITHER else None
    return {**out, "spaces": mine, "deck_spaces": [], "home_player": player,
            "create": [{"space": HOME, "player": player}] if player else []}
