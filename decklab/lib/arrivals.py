"""Arrival notices (E6-S19): after a receipt, tell each home player which of their decks it
brought missing cards for, on their next visit.

    found = arrivals.supplied(before, after, ("wife", "either"))  # {home deck id: cards it was brought}
    told = arrivals.record(before, after, "2026-10-07-shop-a", "2026-10-09", actor)
    arrivals.notices("user1")               # [{id, order, received_on, decks: [[id, cards]], more}]
    arrivals.dismiss("user1", ["qwertyuiop:1f2e..."], actor, "User1")

Both receipt paths call record() after their change is saved: the Receipts page's apply
(api/receipts.py) and `python -m decklab.db receive --apply` (db/inv_receive.py). It never
raises: a notice is a courtesy, and the receipt stands without it.

What a deck was brought: for each card of a home deck's planned list (pool.owned_vs_needed,
basic lands left out), the copies here and free for it (owned, less those on the way and those
other built decks hold, at most what it needs) after the receipt, less before it. A deck the
receipt gave nothing to gets no notice, so a built deck whose cards were all here already never
does. Only home's Casual and Commander decks (they have a Played by), each told to the home
profiles whose plays_as is its Played by; an "either" deck to every home player. Within one
player's notice a received copy is counted once: each card's copies that came (the collection's
copies after the receipt, less before) are dealt to that player's decks in turn, built decks
first, then by deck id, so three unbuilt decks wanting the one Lightning Bolt that came show
"1 card" for the first of them only, and the notice never says more cards came than did.

The notices are kept in each profile's own settings (the state store's profile_setting, no
migration). Each receipt's notice has its own random group, so two receipts saved at once (the
page and the command line) never write the same key: its keys are "arrival_<group>_<part>",
part "a" the compact JSON {"o": order, "on": received on, "d": [[deck id, cards]], "x": decks
left out, "t": when}, and parts "b" on {"d": [...]} for the decks that didn't fit in a setting's
MAX_VALUE characters (up to MAX_PARTS parts; only decks past those are left out, counted in "x").
An order id too long to fit is cut short with "…" (it's only shown). Keeping a notice drops the
oldest past MAX_NOTICES in the same change. The settings page never sees them (api/settings.py
keeps only its own keys). A notice's id is its group and the sha256 of its parts' values, so
dismissing removes only the notice the page showed.
"""
import hashlib
import json
import re
import secrets
import time

from decklab.lib import state

KEY = re.compile(r"arrival_([a-z]{10})_([a-z])")
MAX_NOTICES = 8
MAX_PARTS = 6
KINDS = ("casual", "commander")
PLAYERS = ("user", "wife", "either")
MAX_VALUE = 200                     # state.rules.MAX_SETTING
MAX_ORDER = 60                      # characters of the order id kept (it's only shown)


def is_key(key):
    """Whether a setting's key is one of an arrival notice's parts (Activity's wording)."""
    return isinstance(key, str) and KEY.fullmatch(key) is not None


def _here(row):
    """The copies of one owned-vs-needed row here now and free for this deck, up to its need."""
    held = sum(qty for _, qty in row["in_use_elsewhere"])
    return min(row["need"], max(row["owned"] - row["on_the_way"] - held, 0))


def _home_decks():
    """{deck id: (player, built)} of home's Casual and Commander decks with a Played by, from current()."""
    from decklab.lib import decks, spaces
    out = {}
    for summary in decks.list_decks():
        if (summary.get("space") == spaces.HOME and summary.get("kind") in KINDS and not summary.get("error")
                and summary.get("player") in PLAYERS):
            out[summary["id"]] = (summary["player"], summary.get("status") == "built")
    return out


def _counts(deck_ids):
    """({deck id: {card name: copies here}}, {card name: copies in the collection}) for these decks,
    from current() (one pool)."""
    from decklab.lib import decks, pool
    found = pool.load_pool()
    out, collection = {}, {}
    for deck_id in deck_ids:
        try:
            result = pool.owned_vs_needed(deck_id, "target", pool=found, prices=False)
        except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError):
            continue
        out[deck_id] = {row["name"]: _here(row) for row in result["rows"]}
        for row in result["rows"]:
            collection[row["name"]] = max(row["owned"] - row["on_the_way"], 0)
    return out, collection


def _gains(before, after):
    """({deck id: (player, built, {card name: copies gained})}, {card name: copies that came}) for
    the home decks the change from before to after gave cards to."""
    from decklab.lib import inventory
    with inventory.pinned(after):
        decks = _home_decks()
        now, here = _counts(decks)
    with inventory.pinned(before):
        was, there = _counts(decks)
    gains = {}
    for deck_id, cards in now.items():
        if deck_id not in was:
            continue
        gained = {name: copies - was[deck_id].get(name, 0) for name, copies in cards.items()
                  if copies > was[deck_id].get(name, 0)}
        if gained:
            gains[deck_id] = decks[deck_id] + (gained,)
    came = {name: copies - there.get(name, 0) for name, copies in here.items() if copies > there.get(name, 0)}
    return gains, came


def _deal(gains, came, players):
    """{deck id: cards} for the decks played by one of players: each card's copies that came dealt
    to them in turn (built decks first, then by id), so no copy is counted twice."""
    left = dict(came)
    out = {}
    for deck_id in sorted((d for d in gains if gains[d][0] in players), key=lambda d: (not gains[d][1], d)):
        cards = 0
        for name, copies in sorted(gains[deck_id][2].items()):
            given = min(copies, left.get(name, 0))
            left[name] = left.get(name, 0) - given
            cards += given
        if cards:
            out[deck_id] = cards
    return dict(sorted(out.items()))


def supplied(before, after, players=PLAYERS):
    """{home deck id: cards} that the change from before to after brought the decks played by one
    of players (see the module docstring), each at least 1, in deck id order."""
    gains, came = _gains(before, after)
    return _deal(gains, came, players)


def _players():
    """[(profile id, name, plays_as)] of the home profiles with a plays_as (config.json)."""
    from decklab.lib import permissions, profiles
    return [(p["id"], p["name"], p["plays_as"]) for p in profiles.read()
            if (p.get("space") or permissions.HOME) == permissions.HOME and p.get("plays_as") in ("user", "wife")]


def _dump(data):
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def _values(order, received_on, decks, at):
    """One notice's parts, each at most MAX_VALUE characters: the first {"o", "on", "d", "x", "t"},
    the rest {"d"}; the decks with the most cards first, those past MAX_PARTS parts counted in "x"."""
    if len(order) > MAX_ORDER:
        order = order[:MAX_ORDER - 1] + "…"
    chosen = sorted(decks, key=lambda item: (-item[1], item[0]))
    head = {"o": order, "on": received_on, "d": [], "x": 999, "t": at}     # room for any "x"
    parts = [head]
    for item in chosen:
        if len(_dump(dict(parts[-1], d=parts[-1]["d"] + [item]))) > MAX_VALUE:
            if len(parts) == MAX_PARTS or len(_dump({"d": [item]})) > MAX_VALUE:
                continue                # left out, counted in "x" (a smaller deck may still fit)
            parts.append({"d": []})
        parts[-1]["d"].append(item)
    head["x"] = len(chosen) - sum(len(part["d"]) for part in parts)
    return [_dump(part) for part in parts if part is head or part["d"]]


def _groups(saved):
    """{group: {part letter: value}} of the arrival notices in a profile's settings."""
    out = {}
    for key, value in saved.items():
        found = KEY.fullmatch(key)
        if found and isinstance(value, str):
            out.setdefault(found.group(1), {})[found.group(2)] = value
    return out


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
        gains, came = _gains(before, after)
    except Exception as e:      # noqa: BLE001 - a notice never stops the receipt it follows
        say(f"Arrival notices weren't worked out: {e}")
        return {}
    told = {}
    at = int(time.time())
    for profile_id, name, plays_as in players:
        mine = [[deck_id, cards] for deck_id, cards in _deal(gains, came, (plays_as, "either")).items()]
        if not mine:
            continue
        try:
            store = state.store()
            groups = _groups(store.settings(profile_id))
            # The newest MAX_NOTICES - 1 stay, with this one; a group is random, so a receipt saved
            # meanwhile writes other keys, never these.
            old = sorted(groups, key=lambda group: ((_parse(groups[group].get("a")) or {}).get("t", 0), group))
            changes = {f"arrival_{group}_{part}": None for group in old[:max(len(old) - MAX_NOTICES + 1, 0)]
                       for part in groups[group]}
            group = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(10))
            for part, value in zip("abcdefghijklmnopqrstuvwxyz", _values(order, received_on, mine, at)):
                changes[f"arrival_{group}_{part}"] = value
            store.settings_put(profile_id, changes, actor,
                               f"Arrival notice for {name}: order {order} brought cards for "
                               f"{len(mine)} deck{'s' if len(mine) != 1 else ''}")
        except Exception as e:  # noqa: BLE001 - as above
            say(f"{name}'s arrival notice wasn't kept: {e}")
            continue
        told[profile_id] = {"name": name, "decks": mine}
    return told


def _decks(items):
    return [item for item in items if isinstance(item, list) and len(item) == 2
            and isinstance(item[0], str) and type(item[1]) is int and item[1] > 0]


def _parse(value):
    """A notice's first part as a dict, or None when it isn't one."""
    try:
        data = json.loads(value) if isinstance(value, str) else None
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("o"), str) or not isinstance(data.get("d"), list):
        return None
    return {"o": data["o"], "on": data.get("on") if isinstance(data.get("on"), str) else "", "d": _decks(data["d"]),
            "x": data.get("x") if type(data.get("x")) is int and data.get("x") > 0 else 0,
            "t": data.get("t") if type(data.get("t")) is int else 0}


def _more(value):
    """The decks of a notice's further part ([] when it isn't one)."""
    try:
        data = json.loads(value)
    except ValueError:
        return []
    return _decks(data["d"]) if isinstance(data, dict) and isinstance(data.get("d"), list) else []


def _id(group, parts):
    joined = "\n".join(parts[part] for part in sorted(parts))
    return f"{group}:{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:16]}"


def notices(profile_id, saved=None):
    """The profile's arrival notices, newest first, at most MAX_NOTICES: [{id, order, received_on,
    decks: [[deck id, cards]], more}] (more: decks left out for length). saved: the profile's
    settings, already read (else read from the store: state errors raise)."""
    saved = state.store().settings(profile_id) if saved is None else saved
    out = []
    for group, parts in _groups(saved).items():
        data = _parse(parts.get("a"))
        if data is None:
            continue
        decks = data["d"] + [item for part in sorted(parts) if part != "a" for item in _more(parts[part])]
        out.append((data["t"], group, {"id": _id(group, parts), "order": data["o"], "received_on": data["on"],
                                       "decks": decks, "more": data["x"]}))
    return [notice for _, _, notice in sorted(out, key=lambda item: (-item[0], item[1]))][:MAX_NOTICES]


def dismiss(profile_id, ids, actor, name):
    """Remove the profile's notices with these ids, every part of each (others, and ids no longer
    there, are left alone): one change, none when nothing matches. Returns the notices left."""
    store = state.store()
    saved = store.settings(profile_id)
    wanted = set(ids)
    chosen = [(group, parts) for group, parts in _groups(saved).items() if _id(group, parts) in wanted]
    if chosen:
        saved = store.settings_put(profile_id, {f"arrival_{group}_{part}": None for group, parts in chosen
                                                for part in parts}, actor,
                                   f"{name} dismissed {len(chosen)} arrival notice{'s' if len(chosen) != 1 else ''}")
    return notices(profile_id, saved)
