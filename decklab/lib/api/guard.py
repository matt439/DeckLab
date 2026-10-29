"""The permission check every write route makes (lib/permissions.py has the rules).

    profile = guard.writer(data, "accessories.edit")        # settings._writer, then the check
    guard.require(profile, "deck.edit", deck)               # 403 with the reason, or nothing
    guard.allowed(profile, "tables.update", deck)           # True or False
    guard.visitor()                                         # the remote visitor's profile, or None
    guard.viewer()                                          # the login's, or at home the chooser's (None: nobody)
    guard.local()                                           # not through the tunnel (the home listener, or no request)
    guard.script()                                          # a script: naming nobody, it sees and does everything
    guard.sees_accessories()                                # may this request see any sleeves and deck boxes?
    guard.accessory_owners()                                # whose accessories it sees (None: all)
    guard.sees_kit(deck)                                    # may it see this deck's Sleeves and Deck box?
    guard.require_sees_wishlist("user1")                   # 403 unless this request is User1's
    guard.inventory_spaces()                                # the spaces whose inventory it sees (None: all)
    guard.sees_inventory("home")                            # may it see home's collection, tokens, orders...?
    guard.require_sees_inventory("user2")                 # 403 unless it may see User2's collection
    guard.require_space_write(profile, "collection.edit", "user2")   # the read rule, then the permission
    guard.sees_home_records()                               # may it see home's orders, products, receipts...?
    guard.require_sees_home_records()                       # 403 unless it may
    guard.sees_deck(summary, profile)                       # may it see this deck? (its space's; no admin override)
    guard.require_sees_deck(summary)                        # 404 "No deck X", as for a missing deck, unless it may
    guard.no_deck("casual/gruul-ramp")                      # that 404: a missing, retired-elsewhere or hidden deck's
    guard.deck_reader()                                     # sees_deck for this viewer, worked out once
    guard.visible_decks(summaries)                          # the library summaries it may see
    guard.hidden_deck("user2/casual/elves")               # "one of User2's decks", for one it may not

A write names its profile in the body ("profile"; settings._writer refuses
one that doesn't), and that profile's own rights apply wherever the request
comes from: through the tunnel it's the login's (server.py has already made
the body's "profile" the login's, and settings._writer refuses any other);
on the home network it's the profile the page's chooser picked, and when
the X-Deck-Lab-Viewer header names a profile, the body's must be the same
one (settings._writer: "You can only make changes as yourself"). So User1
picked at home is refused what she'd be refused from outside. A profile
outside the home can't be named on the home listener at all (server_http
answers 403 "Sign in through decklab.example.com" to its header, ?profile=,
?viewer= or body "profile"): members come in through the tunnel's login.
Only a script naming nobody (script(): code outside any request, such as a
job thread or a test, or a request on the home listener from loopback with
X-Deck-Lab-Script: 1; permissions.is_admin) passes every check; any other
request naming nobody (a phone on the Wi-Fi, the PC's browser before a
profile is picked) has no rights and sees only what's open to all. A
refusal is ApiError 403 {"error": <the reason in plain words>}, refused
before anything of the change is worked out. The two kit-owner refusals also
carry a fixed reason for guidance after the refusal, without any record or identity.

The routes and what each checks:

    POST /api/decks                               deck.create {"space", "player"}; require_kit_choice
                                                  too when it sets Sleeves or Deck box
    POST /api/deck/save                           deck.edit on the deck as stored and as saved;
                                                  require_kit_choice too when Sleeves or Deck box
                                                  change (accessories_changed), or when Played by
                                                  changes on a built deck holding them (the
                                                  stored owner's kit must be the profile's to see,
                                                  saving._require_kit_moves)
    POST /api/deck/cover                          deck.edit on the deck as stored (as a save of its text)
    POST /api/deck/considering                    as /api/deck/save (it is one): deck.edit on the deck as stored
    POST /api/deck/draft                          the viewer's own draft only (the body's profile must be the
                                                  named viewer; nobody else's, an admin's or a script's), the
                                                  deck seen first, then deck.edit to keep one (a discard needs
                                                  only the deck seen); not audited (api/deck_drafts.py)
    POST /api/deck/token-cards                    deck.edit on the deck as stored (as a save of its text), and
                                                  its space's inventory (require_sees_inventory)
    POST /api/deck/printings                      the same as /api/deck/token-cards (a home deck only)
    POST /api/deck/box-check, /api/deck/box-repair  deck.edit on the home deck as stored, and home's records
                                                  (require_sees_home_records); box-repair's preview writes nothing
    POST /api/tokens/plan                         its space's inventory (require_sees_inventory), and
                                                  deck.edit on every deck whose Token cards line it changes
    POST /api/deck/check, /api/decklist/parse     nothing: dry runs, open to whoever sees the deck ("Try a change";
                                                  GET /api/deck/edit says editable False, with why_not)
    POST /api/deck/swaps                          nothing to write: a dry run, with GET's reading rule (the
                                                  deck's 404, then its space's inventory: require_sees_inventory)
    POST /api/tables/update                       tables.update on each deck (others are skipped)
    POST /api/play/game, /api/play/sideboard      play.record on the record's decks (old and new)
    POST /api/receipt/preview|apply               receipts.apply, and the profile must see home's
                                                  inventory (require_sees_inventory, below)
    POST /api/shopping/check                      orders.edit, and the profile must see home's
                                                  inventory (require_sees_inventory, below)
    POST /api/shopping/queue                      orders.edit, and the profile must see home's
                                                  inventory; exact inventory revision required
    POST /api/shopping/order/preview|apply        orders.edit and home's inventory; apply needs
                                                  the writer's preview and its exact revision
    POST /api/shopping/order/change/preview|apply orders.edit and home's inventory; corrections
                                                  use the same bound-preview checks as a new order
    POST /api/accessories/fetch|save|assign       accessories.edit, then the row's and the
                                                  holder's owner (api/accessories.py); assign
                                                  also deck.edit on the deck and on move_from's
                                                  (E10-S42), a product home's inventory to see
    POST /api/tokens/save                         tokens.edit on the body's "space" (home by default),
                                                  after the read rule (require_space_write)
    POST /api/collection/save|bulk, .../import/*  collection.edit on the body's "space", likewise
    POST /api/precons/add                         collection.edit on the body's "space", likewise, then
                                                  deck.create as POST /api/decks (its fields)
    POST /api/precons/start                       deck.create on the body's "space" as POST /api/decks
                                                  (the space's decks seen first); nothing is added

A space's collection and tokens are changed only by its own profiles: an
admin only his own space's, a home member (User1) home's as Matt can
(E10-S29, E10-S43). The same goes for every deck write: an admin changes
every deck of his own space and none of another's. Matt asks Claude for
upkeep in another space; the command line writes every space.
    POST /api/profiles/<id>/wishlist              wishlist.edit on <id>
    PUT  /api/profiles/<id>/settings              settings.edit on <id>, for the viewer (the body
                                                  names no profile: the login, or the header)
    POST /api/arrivals/dismiss                    settings.edit on the writer's own profile (its arrival
                                                  notices are kept with its settings, E6-S19)
    POST /api/matchup|field|variant/stop          run.stop (an admin, by role, for now: E10-S30)
    POST /api/matchup/run, /api/field/run, /api/variant/run|more
                                                  run.start (require_start: the simulations setting,
                                                  api/simulations.py)
    POST /api/play/sideboard-test                 the plan preview's reading rule (its own space, both
                                                  lists visible), then run.start as /api/variant/run
    PUT  /api/simulations                         simulations.edit (an admin, by role)
    PUT  /api/commander-night                     commander_night.edit (a home admin)
    POST /api/assembly/preview                    run (it writes nothing)
    POST /api/assembly/ticks                      home's inventory; a changes patch requires a real
                                                  home writer, a read-only poll no profile

GET /api/commander-night and its optional home Commander-deck projection use
permissions.sees_commander_night: home viewers only, even when another space's
viewer is an admin. The table's Activity rows and mixed-change words follow it.

One rule is about reading (permissions.accessory_owners): each accessory
is seen only by its owner, a shared one by every home profile, and a
person with their own space (User2, User3, User4) sees none. The
viewer is the tunnel login's profile, or on the home network the profile
the page's chooser names in access.VIEWER_HEADER (none named: everything for
a script, none for anyone else). A deck's sleeves and deck box are seen only by those who
see its owner's (sees_kit: the profile whose plays_as is its Played by, or
shared for "either" decks and products), so another's deck shows no kit;
everywhere else, holders the viewer can't see are named only as "one of
User1's decks" (accessories.hidden_title). GET /api/accessories and
/accessory-img/ answer 403 (require_sees_accessories), and the answers that
carry them leave them out (hide_kit and the like): the library and deck page
(summary sleeves, deck_box, kit, holder_sha256 None; no kit warnings or
info), the editor (fields and field_text of Sleeves and Deck box None, not
in editable_fields, no other_sleeves or accessory rows, also in a save's or
create's "deck"), a deck's history revision, "Try a change" (no sleeve
warnings) and the packing plan (sleeves, kit, sleeves_need None). Such a
visitor can't save a deck that has those lines (they're home decks, or
lines Deck Lab never writes in a person's deck), and the editor only sends
changed fields, so leaving them out can't clear them.

A second rule is about reading wishlists (permissions.sees_wishlist): a
wishlist is seen only by its owner, the viewer found as above. GET
/api/profiles/<id>/wishlist answers 403 (require_sees_wishlist) to anyone
else: an admin, another home profile, a person, and a request naming
nobody, a script's included (the page names its viewer once a profile is chosen, and a page
before that has no wishlist to show). The PC's command line (python -m
decklab.db wishlist, sql) isn't a request and still reads every list.

A third rule is about reading the inventory (permissions.sees_inventory,
the viewer found as above; E10-S29): a space's collection and tokens are
seen only by its own profiles (home's by Matt and User1, User2's only by
User2), whatever their role: the admin role opens no other space's. Home's
records (the orders, products, watchlist, checks, receipts and packing
plan) are sees_home_records': the home profiles only, never anyone else
(require_sees_home_records). A script naming nobody sees everything, as for
accessories; any other request naming nobody (the page before anyone is
chosen) and a login that isn't set up nothing. On the home network the
reads, like the writes, follow the profile the chooser names (home profiles
only). Each route answers 403 for a space it may not see, naming no space
or person (E10-S38): home's records INVENTORY_HIDDEN ("The shopping list,
deliveries and packing plan are private."), and any space's collection and
tokens, one that doesn't exist included (collection.space_param),
COLLECTION_HIDDEN, "That collection isn't public.":

    GET  /api/shopping                            home's records
    GET  /api/receipt                             home's records
    POST /api/receipt/preview|apply               home's records, for the body's profile (after receipts.apply)
    GET  /api/assembly, POST /api/assembly/preview   home's records (the packing plan is the home pool's)
    GET  /api/collection, /api/collection/rows, /api/collection/download    the ?space= (home by default)
    GET  /api/tokens                              the ?space= (home by default)
    GET  /api/precons/preview                     the ?space=, and collection.edit there too
    GET  /api/precons/coverage, .../coverage/deck  the ?space= (home by default)

The collection and tokens writes ask the read rule first
(require_space_write), so a write to a space the writer can't see gets that
same 403 with only {"error"}, before its sha256 is looked at. Inside the
answers, a deck is named only when the viewer may see it (the sixth rule):
the Collection page's holders, the Tokens page's uses and missing decks,
and the held spaces' unknown cards on the Tables out of date list name
another one as "one of the home decks"; the Tokens page's pending token
orders, and home's pool warnings about its order and product files, go
only to whoever sees home's records. These answer for what it may see
instead: /api/collection's "spaces" lists only those spaces; the printing
picker's "owned" and "on_the_way" (GET /api/cards/printings, "have" in
/api/cards/search?detail=1 and a pasted list's printings) count the
viewer's own space's pool (card_lookup._pool_counts; home's for a script),
never another space's; GET /api/deck/find counts its "id" (pool.self_ids)
only for a deck the viewer may see. The Activity page's inventory and deck rows ask
their own-space rule (activity_scope), independently from public readers. Since phase 4 (the design's R6d,
the user's decision) the deck pages follow it too: anyone who may see a deck
sees its list, guide, stats, practice hands and matchups, but GET /api/deck's
"owned", "table" and "tokens", the library's missing and on-the-way counts
and token chips, GET /api/deck/edit's "table", and the decks GET
/api/tables/stale (and a save's "stale_tables") lists are left out for a
space it may not see, and home's pool warnings go only to those who see
home. "Try a change" (POST /api/deck/check) leaves out that space's pool,
and its default printings don't follow that space's copies. Writes to a collection or tokens need collection.edit or
tokens.edit, as above. GET /api/me's "may" carries "see_inventory" (the
spaces, None for all) so the page hides the Shopping, Receipts and packing
plan pages and the spaces it may not see; on the home network the page
works out the whole "may" from the profile chosen (core.js's deriveMay).

A fourth rule is about reading the audit trail (GET /api/activity,
api/activity.py, permissions.activity_scope): the viewer is found the same
way (viewer()). Every named viewer, admins included, sees only their own space's changes;
public visibility never widens Activity. A script naming nobody sees every space, except
wishlist rows, which are always their owner's only. Named viewers see their space's
profile_setting rows (home's for a home profile, only their own for a person), simulation_mode
rows, play_record rows with a deck in their space (the fifth rule's
permissions.sees_play_record; a deck id that can't be read: scripts
only), and the inventory's rows of the spaces it
sees (the third rule: home's collection, tokens, orders, products and
watchlist for a home profile, a person's own collection, tokens and
imports for that person; at most activity.ROW_CAP listed per change), and
the deck rows of those spaces (id, title, status, Played by); an accessory
row is seen only by whoever sees that owner's accessories (the first rule,
admins too), and a change with any accessory row or kit change shows its
message and reason only to whoever made it. Settings rows of a profile config.json doesn't
list are scripts' only. Space, profile and email rows and tables
without a rule yet are admins' system rows, with email rows cut to "An email address changed".
Visibility flips belong to their space (all accessory flips to home). Each row goes out through its table's allow-list of fields,
never raw. A change set with no visible row is left out (one with no rows
at all is an admin's), and its message and reason are None unless Deck
Lab's page wrote them (source "web"), the viewer is an admin, or the viewer
made the change, and every row of the change set is visible to the viewer. This includes
web and command-line changes, even for their actor or an admin; mixed-space Update all
messages cannot name hidden decks. A request naming nobody that isn't a script (or naming a
profile config.json no longer lists) is shown nothing; through the tunnel
with no profile visitor() has already refused it.

A fifth rule is about reading the Game log (permissions.sees_play_record,
the viewer found as above): GET /api/play (api/play_records.py's
play_overview) sends only the games and sideboard plans with a deck of the
viewer's own space in them (a game's two sides, a plan's deck only), so
Matt and User1 see every one with a home deck and a member only those
with one of their own decks; a script naming nobody sees every one, an
admin by role only his own space's (E10-S29), any other request naming
nobody none, and a login that isn't set up gets 403 (visitor()). Inside a
game, a side whose deck the viewer may not see is only "one of the home
decks" with no list, and another space's notes and plans are left out; each
side's space changes only its own side, the date, result and notes only the
recording space, and no save names a deck its writer may not see (decision
G, E10-S32: play_records.py's module docstring). A record that can't be shown is warned about only to
a viewer who may see it. Its "lists" and "decks" hold only the decks the
viewer may see (the sixth rule). The Activity page's play_record rows ask
the same rule.

A sixth rule is about reading the decks (sees_deck over
permissions.sees_deck, E10-S30; the viewer found as above, or the writer
for a write): a deck is seen only in its own space, so home's decks
(product decks and Beginner Box pairings too) only by Matt and User1, and
User2's only by User2; the admin role opens nothing. A script naming
nobody sees every deck, any other request naming nobody none. A deck the
viewer may not see answers exactly as a missing one, 404 "No deck
'casual/gruul-ramp'" (no_deck, require_sees_deck), with nothing else, and
that's checked before anything of the deck is read and before any 403 or
409, so no answer confirms it exists or gives its title:
- GET /api/decks lists only those decks (its halves, usual opponents,
  aliases and decks_revision worked out over them,
  library.viewer_decks_revision), and GET /api/deck, /api/deck/edit,
  /api/deck/cards, /api/deck/opponents, /api/compare/shared (both decks) and the rest that start from
  library._find_summary answer that 404;
- deck_aliases.canonical_id for the history, a revision and a retired deck
  (by its id, which names its former space), and the opponents, rename and
  retirement previews and the variant tests;
- every write route asks it first, then the permission (403), then the
  conflict (409): commits._stored and _conflict for a save, the cover, a
  draft check and a table update, deck_aliases.reject_alias for the rename,
  retirement, restore and opponents writes;
- the Forge answers keep to it coarsely (forge_runs._Seen): GET
  /api/matchups (and ?running=1), /api/matchup, /api/field, /api/variant
  and /api/variants carry only the results, runs and tests whose every
  side the viewer sees, names from other spaces as "someone", and an
  admin's running list the other runs as anonymous items; for now only an
  admin stops a run ("run.stop").
Until E10-S28's switches (public_deck_spaces) a deck is public nowhere.
"""
from decklab.lib import access, permissions

from .common import ApiError

KIT_OWNERSHIP = "kit_ownership"


def local():
    """True for a request on the home network (or outside any request): "not
    through the tunnel", which viewer() and the audit trail's "via" ask. It
    says nothing about what naming nobody may see: script() does."""
    return access.current() is None


def script():
    """True for a script (access.script()): code outside any request (a job
    thread, a test), or a request on the home listener from loopback
    (127.0.0.1 or ::1) that sends X-Deck-Lab-Script: 1 and names nobody.
    Naming nobody, it sees and may do everything, as the command line does.
    The tunnel's listener (on 127.0.0.1 too) never makes one."""
    return access.script()


def allowed(profile, action, target=None):
    """True when profile may do action to target (permissions.can). For a
    page's "may this visitor..." answer, pass viewer(), not visitor(): at
    home visitor() is None, which would answer as for nobody."""
    return permissions.can(profile, action, target, script=script())


def require(profile, action, target=None):
    """ApiError 403 with the reason unless profile may do action to target."""
    why = permissions.reason(profile, action, target, script=script())
    if why is not None:
        raise ApiError(403, why)


def require_start(profile):
    """ApiError 403 with the reason unless profile may start a Forge run now
    (permissions' "run.start" under the simulations setting)."""
    from .simulations import mode
    require(profile, "run.start", mode())


def writer(data, action, target=None):
    """settings._writer(data) (the profile the write is made by), then require()."""
    from .settings import _writer
    profile = _writer(data)
    require(profile, action, target)
    return profile


def deck_after(deck, fields):
    """A deck file as a save of these header fields leaves it, for deck.edit:
    {"space", "player"} (a member can't hand their deck to someone else by
    changing its Played by)."""
    return {"space": deck.space, "player": fields["player"] if "player" in fields else deck.player}


def accessories_changed(deck, fields):
    """True when a save of these header fields changes a deck's Sleeves or
    Deck box (deck: the DeckFile as it is on disk, None for a new deck), so
    the save needs accessories.edit as well: a member may edit their deck
    but not hand out the home's sleeves and boxes. Taking a built deck apart
    (status built -> building or idea) clears both, and that alone doesn't
    count: it frees them rather than choosing them."""
    taken_apart = deck is not None and deck.status == "built" and fields.get("status") not in (None, "built")
    for key in ("sleeves", "deck_box"):
        if key not in fields:
            continue
        value = fields[key].strip() if isinstance(fields[key], str) else fields[key]
        value = value or None
        held = getattr(deck, key) if deck is not None else None
        if value != held and not (value is None and taken_apart):
            return True
    return False


def viewer():
    """The profile this request is answered for: the tunnel login's
    (visitor()), or on the home network the one the page's chooser names
    (access.viewer(); None when it names nobody or nobody in config.json).
    ApiError 403 for a login that isn't set up."""
    if not local():
        return visitor()
    profile_id = access.viewer()
    if not profile_id:
        return None
    from .settings import _config_profiles
    return next((p for p in _config_profiles() if p["id"] == profile_id), None)


def accessory_owners(profile=False):
    """The owners whose accessories this request may change
    (permissions.accessory_owners; None: all), for profile, or for the
    viewer() when it's left out. A login that isn't set up sees none."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return frozenset()
    return permissions.accessory_owners(profile, script=script())


def accessory_readers(profile=False):
    """The writable owners plus those whose kit is Public, for reads only."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return frozenset()
    return permissions.accessory_readers(profile, script=script(), public=public_owners("accessories"))


def require_kit_choice(profile, deck, fields):
    """For a deck save that changes Sleeves or Deck box (accessories_changed):
    accessories.edit, the deck's owner's accessories must be the profile's
    to choose (sees_kit), and each id chosen must be one it sees that the
    deck may take (its owner's or shared). Older free text isn't checked.
    ApiError 403 or 400 otherwise. deck: {"space", "player"} as saved."""
    from decklab.lib import accessories
    require(profile, "accessories.edit")
    owners = accessory_owners(profile)
    owner = holder_owner(deck)
    if owner is None or not accessories.visible(owner, owners):
        raise ApiError(403, f"This deck's sleeves and deck box are {accessories.owner_name(owner)}'s to choose."
                       if owner else "A deck in a person's own collection has no sleeves or deck box.",
                       **({"reason": KIT_OWNERSHIP} if owner else {}))
    inv = None
    for key in accessories.HOLDER_FIELDS:
        value = fields.get(key)
        value = " ".join(value.split()) if isinstance(value, str) else ""
        if not value:
            continue
        inv = accessories.read() if inv is None else inv
        row = inv.rows_by_id.get(value)
        if row is None:
            continue                    # older free text
        if not accessories.visible(row["owner"], owners):
            raise ApiError(400, f"There's no {'sleeves' if key == 'sleeves' else 'deck box'} {value} in the "
                                f"accessories list")
        if not accessories.usable(row["owner"], owner):
            whose = ("only shared ones" if owner == accessories.SHARED
                     else f"only {accessories.owner_name(owner)}'s or shared ones")
            raise ApiError(400, f"{accessories.label(row)} {'are' if key == 'sleeves' else 'is'} "
                                f"{accessories.owner_name(row['owner'])}'s: this deck uses {whose}.")


def sees_accessories():
    """True when this request sees any sleeves, deck boxes and playmats
    (accessory_readers isn't empty)."""
    owners = accessory_readers()
    return owners is None or bool(owners)


def holder_owner(target):
    """The owner of a holder's accessories: a deck (a library summary or a
    DeckFile; a product deck's is its product's) or a holder id. SHARED for
    a product, pairing or "either" deck, the profile whose plays_as is a
    home deck's Played by, None for a deck in a person's space (it has none)."""
    from decklab.lib import accessories, spaces
    deck_id = target if isinstance(target, str) else permissions._get(target, "id")
    if isinstance(deck_id, str) and deck_id.startswith(("product/", "pairing/")):
        return accessories.SHARED
    space = (spaces.space_of(target) if isinstance(target, str) else permissions._get(target, "space")) or "home"
    if space != "home":
        return None
    if isinstance(target, str):
        summary = _summary(target)
        player = summary.get("player") if summary else None
    else:
        player = permissions._get(target, "player")
    return accessories.player_owner(player)


def _summary(deck_id):
    from decklab.lib import decks
    return decks.find_summary(deck_id)


def sees_kit(target, owners=False):
    """True when this request (or an explicit reader/write owners set) sees a
    deck's or product's sleeves and deck box: those of its owner
    (holder_owner)."""
    from decklab.lib import accessories
    owners = accessory_readers() if owners is False else owners
    owner = holder_owner(target)
    return owner is not None and accessories.visible(owner, owners)


def require_sees_wishlist(owner_id):
    """ApiError 403 unless this request's viewer() is the wishlist's owner
    (permissions.sees_wishlist)."""
    if not permissions.sees_wishlist(viewer(), owner_id, script=script()):
        raise ApiError(403, WISHLIST_HIDDEN)


# The 403 for GET /api/profiles/<id>/wishlist, for anyone but its owner.
WISHLIST_HIDDEN = "A wishlist is private: only its owner can see it. Choose your own profile to see yours."


def inventory_spaces(profile=False):
    """The spaces whose inventory this request sees (permissions.inventory_spaces;
    None: every space's), for profile, or for the viewer() when it's left
    out. A login that isn't set up sees none."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return []
    return permissions.inventory_spaces(profile, script=script(), public=public_spaces("collection"))


def sees_inventory(space, profile=False):
    """True when this request (or profile, as inventory_spaces) may see
    space's collection and tokens (permissions.sees_inventory), including public
    collections. Home's orders, products, watchlist and receipts have their own rule."""
    seen = inventory_spaces(profile)
    return seen is None or (isinstance(space, str) and space in seen)


def visibility():
    """This request's pinned Public switches; an unreadable store fails closed."""
    from decklab.lib import visibility as switches
    return switches.snapshot()


def public_owners(thing):
    """Owners with a Public switch for thing, from this request's one snapshot."""
    return frozenset(owner for (owner, kind) in visibility() if kind == thing)


def public_spaces(thing):
    """Configured spaces with that Public switch; orphan rows confer no read rights."""
    from decklab.lib import spaces
    return public_owners(thing) & frozenset(spaces.space_ids())


def public_deck_spaces():
    """The configured spaces whose decks are Public (the common deck-reader hook)."""
    return public_spaces("decks")


def _target_deck(target):
    """(deck id or None, space or None) of a deck target: a deck id, a
    library summary or a DeckFile-like object ("id" and/or "space"; the
    id's space wins, so a product deck or pairing is home's)."""
    if isinstance(target, str):
        deck_id = target
    else:
        deck_id = (permissions._get(target, "id") or permissions._get(target, "deck_id")) if target is not None else None
    if isinstance(deck_id, str):
        space = permissions._deck_space(deck_id)
        if space is not None:
            return deck_id, space
    space = permissions._get(target, "space") if target is not None and not isinstance(target, str) else None
    return (deck_id if isinstance(deck_id, str) else None), (space if isinstance(space, str) else None)


def _home_only(deck_id):
    """True for the decks of an ordered or preordered product (and a
    Beginner Box pairing while the box is): they never leave home
    (permissions.sees_deck's home_only). Read only when it could matter."""
    if not isinstance(deck_id, str) or not deck_id.startswith(("product/", "pairing/")):
        return False
    from decklab.lib import decks, inventory
    stem = decks.BEGINNER_BOX if deck_id.startswith("pairing/") else deck_id.split("/")[1]
    try:
        rows = inventory.current().status.rows
    except Exception:           # can't tell: keep it home's
        return True
    for row in rows:
        if row.text("file") == f"{stem}.csv":
            return row.text("status").strip().lower() in ("ordered", "preordered")
    return False


def sees_deck(target, profile=False):
    """True when this request (or profile: the viewer profile dict, None for
    nobody) may see a deck (permissions.sees_deck, E10-S30): target is a
    deck id, a library summary or a DeckFile (its id's space, else its
    "space"). A deck is seen in its own space only (home's, products and
    pairings included, by home's profiles), with no admin override, plus
    the spaces whose decks are public (public_deck_spaces: none until
    E10-S28); a script naming nobody sees every one. With profile left out
    it's the viewer(); a login that isn't set up sees none. A hidden deck
    must answer exactly as a missing one (require_sees_deck), and before
    any 403 or 409."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return False
    deck_id, space = _target_deck(target)
    public = public_deck_spaces()
    home_only = False
    if space == permissions.HOME and space in public and not (profile and permissions._space_of(profile) == space):
        home_only = _home_only(deck_id)
    return permissions.sees_deck(profile, space, script=script(), public=public, home_only=home_only)


def no_deck(deck_id):
    """The 404 for a deck id, "No deck 'casual/gruul-ramp'": the same for a deck that's
    missing, retired from another space or hidden (E10-S30), so none of them tells which
    it is. Every reader and write answers a missing or hidden deck with it."""
    return ApiError(404, f"No deck {deck_id!r}")


def require_sees_deck(target, profile=False, deck_id=None):
    """ApiError 404 "No deck <id>" (no_deck: the missing deck's answer) unless
    this request (or profile) may see the deck (sees_deck). deck_id is the id the
    request named (the target's own by default)."""
    if not sees_deck(target, profile):
        raise no_deck(deck_id if deck_id is not None else _target_deck(target)[0])


def hidden_deck(target):
    """How a deck the viewer may not see is named, without its id or title: "one of
    the home decks" or "one of User2's decks" (its space's name), "a deck" when its
    space can't be read."""
    space = _target_deck(target)[1]
    if space == permissions.HOME:
        return "one of the home decks"
    from decklab.lib import spaces
    try:
        return f"one of {spaces.get(space).name}'s decks" if space else "a deck"
    except (spaces.SpaceNotFound, OSError, ValueError):
        return "a deck"


def deck_reader(profile=False):
    """sees_deck for one viewer, worked out once: a function of a deck id or deck, for
    filtering a list (rankings, matchups, opponents, the stale tables) without finding
    the viewer per item. A login that isn't set up sees none."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return lambda target: False
    return lambda target: sees_deck(target, profile)


def visible_decks(summaries, profile=False):
    """The library summaries (or ids) this request (or profile) may see, in order (deck_reader)."""
    sees = deck_reader(profile)
    return [item for item in summaries if sees(item)]


def require_sees_inventory(space, profile=False):
    """ApiError 403 unless this request (or profile) may see space's inventory (sees_inventory)."""
    if not sees_inventory(space, profile):
        raise ApiError(403, inventory_hidden(space))


def require_space_write(profile, action, space):
    """For a write to a space's collection or tokens ("collection.edit", "tokens.edit"): first
    the read rule (require_sees_inventory: the same 403 a hidden or missing space gets, so the
    refusal names no space and tells nothing of it), then the permission (require). Both before
    anything of the write is read, so a stale sha256 changes nothing (E10-S29)."""
    require_sees_inventory(space, profile)
    require(profile, action, space)


def sees_home_records(profile=False):
    """True when this request (or profile, as inventory_spaces) may see home's records: the
    orders, products, watchlist, receipts and packing plan (permissions.sees_home_records: the
    home profiles and a script only, whatever the switches say)."""
    if profile is False:
        try:
            profile = viewer()
        except ApiError:
            return False
    return permissions.sees_home_records(profile, script=script())


def require_sees_home_records(profile=False):
    """ApiError 403 (INVENTORY_HIDDEN) unless this request (or profile) may see home's records."""
    if not sees_home_records(profile):
        raise ApiError(403, INVENTORY_HIDDEN)


def inventory_hidden(space):
    """The 403 for a space's inventory, in plain words. Home's, a person's space, one
    config.json doesn't list and one that doesn't exist all get COLLECTION_HIDDEN, word for
    word, so the answer names no space or person and doesn't tell which it is (E10-S29,
    E10-S38, decision C). space is taken so the callers say whose they asked about."""
    return COLLECTION_HIDDEN


# The 403 for home's records (the shopping list, deliveries and packing plan), to anyone outside
# the home: it names no space (E10-S38).
INVENTORY_HIDDEN = "The shopping list, deliveries and packing plan are private."
# The 403 for any space's collection and tokens (or a space that doesn't exist), to anyone outside it.
COLLECTION_HIDDEN = "That collection isn't public."
# The 403 for a new deck in a space whose decks its maker can't see, or one that doesn't exist.
HIDDEN_SPACE = "Decks can be made only in a space whose decks you can see."


def require_sees_accessories():
    """ApiError 403 unless this request may see the accessories (sees_accessories)."""
    if not sees_accessories():
        raise ApiError(403, ACCESSORIES_HIDDEN)


# The 403 for GET /api/accessories and an accessory's picture, for someone who may not see them.
ACCESSORIES_HIDDEN = permissions.ACCESSORIES_PRIVATE      # names no space (E10-S38)


def hide_kit(summary):
    """Take the sleeves and deck box out of a library or deck page summary
    (in place, kept as None so the page's shape stays), for a visitor who
    may not see them. Returns summary."""
    for key in ("sleeves", "deck_box", "kit", "holder_sha256"):
        if key in summary:
            summary[key] = None
    return summary


def visitor():
    """The profile of the remote visitor making this request (a dict from
    settings._config_profiles), or None on the home network."""
    identity = access.current()
    if identity is None:
        return None
    from .settings import _config_profiles
    found = next((p for p in _config_profiles() if p["id"] == identity["profile"]), None)
    if found is None:
        raise ApiError(403, "Your login isn't set up in Deck Lab's config.json")
    return found

