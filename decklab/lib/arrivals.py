"""Arrival notices (E6-S19): after a receipt, tell each home player which of their decks it
brought missing cards for, on their next visit.

    found = arrivals.supplied(before, after)        # {home deck id: cards it now has that it hadn't}
    told = arrivals.record(before, after, "2026-10-07-shop-a", "2026-10-09", actor)
    arrivals.notices("user1")                       # [{id, order, received_on, decks: [[id, cards]], more}]
    arrivals.dismiss("user1", ["arrival_a:1f2e..."], actor)

Both receipt paths call record() after their change is saved: the Receipts page's apply
(api/receipts.py) and `python -m decklab.db receive --apply` (db/inv_receive.py). It never
raises: a notice is a courtesy, and the receipt stands without it.

What a deck was supplied: for each card of a home deck's planned list (pool.owned_vs_needed,
basic lands left out), the copies here and free for it (owned, less those on the way and those
other built decks hold, at most what it needs) after the receipt, less before it. A deck the
receipt gave nothing to gets no notice, so a built deck whose cards were all here already never
does. Only home's Casual and Commander decks (they have a Played by), each told to the home
profiles whose plays_as is its Played by; an "either" deck to every home player.

The notices are kept in each profile's own settings (the state store's profile_setting, no
migration): one key per receipt, SLOTS of them ("arrival_a" ... "arrival_h"), each a compact
JSON {"o": order, "on": received on, "d": [[deck id, cards]], "x": decks left out for length,
"t": when}. A full set drops its oldest. The settings page never sees them (api/settings.py
keeps only its own keys). A notice's id is its key and the sha256 of its value, so dismissing
removes only the notice the page showed: a slot reused since stays.
"""
import hashlib
import json
import time

from decklab.lib import state

SLOTS = tuple(f"arrival_{letter}" for letter in "abcdefgh")
KINDS = ("casual", "commander")
PLAYERS = ("user", "wife", "either")
MAX_VALUE = 200                     # state.rules.MAX_SETTING


def _here(row):
    """The copies of one owned-vs-needed row here now and free for this deck, up to its need."""
    held = sum(qty for _, qty in row["in_use_elsewhere"])
    return min(row["need"], max(row["owned"] - row["on_the_way"] - held, 0))


def _home_decks():
    """{deck id: player} of home's Casual and Commander decks with a Played by, from current()."""
    from decklab.lib import decks, spaces
    out = {}
    for summary in decks.list_decks():
        if (summary.get("space") == spaces.HOME and summary.get("kind") in KINDS and not summary.get("error")
                and summary.get("player") in PLAYERS):
            out[summary["id"]] = summary["player"]
    return out


def _counts(deck_ids):
    """{deck id: {card name: copies here}} for these decks, from current() (one pool)."""
    from decklab.lib import decks, pool
    found = pool.load_pool()
    out = {}
    for deck_id in deck_ids:
        try:
            result = pool.owned_vs_needed(deck_id, "target", pool=found, prices=False)
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
            continue
        out[deck_id] = {row["name"]: _here(row) for row in result["rows"]}
    return out


def supplied(before, after):
    """{home deck id: cards} that the change from before to after supplied (see the module
    docstring), each at least 1, in deck id order; with the player as {id: (cards, player)}."""
    from decklab.lib import inventory
    with inventory.pinned(after):
        players = _home_decks()
        now = _counts(players)
    with inventory.pinned(before):
        was = _counts(players)
    out = {}
    for deck_id in sorted(now):
        if deck_id not in was:
            continue
        gained = sum(max(copies - was[deck_id].get(name, 0), 0) for name, copies in now[deck_id].items())
        if gained:
            out[deck_id] = (gained, players[deck_id])
    return out


def _players():
    """[(profile id, name, plays_as)] of the home profiles with a plays_as (config.json)."""
    from decklab.lib import permissions, profiles
    return [(p["id"], p["name"], p["plays_as"]) for p in profiles.read()
            if (p.get("space") or permissions.HOME) == permissions.HOME and p.get("plays_as") in ("user", "wife")]


def _value(order, received_on, decks, at):
    """The compact JSON of one notice, at most MAX_VALUE characters: the decks with the most cards
    first, those that don't fit counted in "x"."""
    chosen = sorted(decks, key=lambda item: (-item[1], item[0]))
    kept = list(chosen)
    while True:
        value = json.dumps({"o": order, "on": received_on, "d": kept, "x": len(chosen) - len(kept), "t": at},
                           separators=(",", ":"))
        if len(value) <= MAX_VALUE or not kept:
            return value
        kept.pop()


def record(before, after, order, received_on, actor, *, log=None):
    """After a saved receipt (before, after: the inventory snapshots it ran on and saved), keep a
    notice for each home player with a deck it supplied. Returns {profile id: {"name", "decks":
    [[deck id, cards]]}} of the notices kept. Never raises: what goes wrong is passed to log (a
    function of one line of text) and the rest goes ahead."""
    say = log or (lambda text: None)
    try:
        players = _players()
    except (OSError, ValueError):       # no readable config.json: nobody to tell (as on a fresh clone)
        return {}
    if not players:
        return {}
    try:
        found = supplied(before, after)
    except Exception as e:      # noqa: BLE001 - a notice never stops the receipt it follows
        say(f"Arrival notices weren't worked out: {e}")
        return {}
    told = {}
    at = int(time.time())
    for profile_id, name, plays_as in players:
        mine = [[deck_id, cards] for deck_id, (cards, player) in found.items() if player in (plays_as, "either")]
        if not mine:
            continue
        try:
            store = state.store()
            saved = store.settings(profile_id)
            key = next((slot for slot in SLOTS if slot not in saved), None)
            if key is None:         # every slot taken: the oldest goes
                key = min(SLOTS, key=lambda slot: (_parse(saved.get(slot)) or {}).get("t", 0))
            store.settings_put(profile_id, {key: _value(order, received_on, mine, at)}, actor,
                               f"Arrival notice for {name}: order {order} brought cards for "
                               f"{len(mine)} deck{'s' if len(mine) != 1 else ''}")
        except Exception as e:  # noqa: BLE001 - as above
            say(f"{name}'s arrival notice wasn't kept: {e}")
            continue
        told[profile_id] = {"name": name, "decks": mine}
    return told


def _parse(value):
    """One stored notice as a dict, or None when it isn't one."""
    try:
        data = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("o"), str) or not isinstance(data.get("d"), list):
        return None
    decks = [item for item in data["d"] if isinstance(item, list) and len(item) == 2
             and isinstance(item[0], str) and type(item[1]) is int and item[1] > 0]
    return {"o": data["o"], "on": data.get("on") if isinstance(data.get("on"), str) else "", "d": decks,
            "x": data.get("x") if type(data.get("x")) is int and data.get("x") > 0 else 0,
            "t": data.get("t") if type(data.get("t")) is int else 0}


def _id(key, value):
    return f"{key}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def notices(profile_id, saved=None):
    """The profile's arrival notices, newest first: [{id, order, received_on, decks: [[deck id,
    cards]], more}] (more: decks left out for length). saved: the profile's settings, already
    read (else read from the store: state errors raise)."""
    saved = state.store().settings(profile_id) if saved is None else saved
    out = []
    for key in SLOTS:
        data = _parse(saved.get(key))
        if data is not None:
            out.append((data["t"], key, {"id": _id(key, saved[key]), "order": data["o"], "received_on": data["on"],
                                         "decks": data["d"], "more": data["x"]}))
    return [notice for _, _, notice in sorted(out, key=lambda item: (-item[0], item[1]))]


def dismiss(profile_id, ids, actor, name):
    """Remove the profile's notices with these ids (others, and ids no longer there, are left
    alone): one change, none when nothing matches. Returns the notices left."""
    store = state.store()
    saved = store.settings(profile_id)
    gone = {key: None for key in SLOTS if isinstance(saved.get(key), str) and _id(key, saved[key]) in set(ids)}
    if gone:
        saved = store.settings_put(profile_id, gone, actor,
                                   f"{name} dismissed {len(gone)} arrival notice{'s' if len(gone) != 1 else ''}")
    return notices(profile_id, saved)
