"""Plan every built deck's Token cards line at once (the Tokens page's "Plan packed token cards").

Each built deck of a space (built_ids) wants one card for
each token its built list makes (deck_tokens' needs, worked out with every row free). The plan gives
each need one card, choosing over all the decks together so the space's rows go as far as they can:

1. As many needs as possible get a card (a minimum-cost maximum flow: needs on one side, rows on the
   other, each row giving at most its quantity).
2. Among those, better matches first: an exact or agreeing card, then one whose details aren't
   recorded (check), then a stand-in that differs (the deck page says to tell the opponent).
3. Then the card the deck already packs, so a re-plan moves as little as it can.
4. Then a single-sided card over a double-sided one, which keeps double-sided cards for decks that
   use both their faces.

Then the spares (Matt, 2026-10-25: "one each, then share spares"): what's left of each row is dealt
out one card at a time, round the decks given that row in id order (or, for a row nobody was given,
the decks it would serve as an exact, agreeing or check card), so a Treasure deck may get 3.

Intact products are fixed holders in this slice. Their recorded copies are left out of both
flow capacities and spare distribution; automatic product planning is still separate work.

plan() only works it out (tokens.plan_token_cards reads what it needs); lib/api/token_plan.py previews it and saves every line as one change.
"""
import collections
import hashlib
import json

from decklab.lib import cards, decks, inventory, spaces

from . import reserve
from .rows import label

_RANK = {"exact": 0, "agrees": 0, "check": 1}
_STAND_IN = 2
_RANK_WEIGHT, _MOVE_WEIGHT, _TWO_SIDED_WEIGHT = 100, 10, 1


def _two_sided(row):
    return bool(row["back"]) and cards.fold(row["back"]) != cards.fold(row["front"])


def _min_cost_flow(n, edges, source, sink):
    """Successive shortest paths (Bellman-Ford as SPFA, so costs may be anything) on a small graph: edges
    [(u, v, capacity, cost)]. Returns the flow on each edge, in edges' order; the flow is maximal,
    and of least cost among maximal flows."""
    graph = [[] for _ in range(n)]
    arcs = []           # [to, capacity left, cost, index of the reverse arc]
    for u, v, cap, cost in edges:
        graph[u].append(len(arcs))
        arcs.append([v, cap, cost, len(arcs) + 1])
        graph[v].append(len(arcs))
        arcs.append([u, 0, -cost, len(arcs) - 1])
    while True:
        dist, back, queued = [None] * n, [None] * n, [False] * n
        dist[source] = 0
        queue = collections.deque([source])
        while queue:
            u = queue.popleft()
            queued[u] = False
            for a in graph[u]:
                v, cap, cost, _ = arcs[a]
                if cap > 0 and (dist[v] is None or dist[u] + cost < dist[v]):
                    dist[v], back[v] = dist[u] + cost, a
                    if not queued[v]:
                        queued[v] = True
                        queue.append(v)
        if dist[sink] is None:
            break
        push, v = None, sink
        while v != source:
            a = back[v]
            push = arcs[a][1] if push is None else min(push, arcs[a][1])
            v = arcs[arcs[a][3]][0]
        v = sink
        while v != source:
            a = back[v]
            arcs[a][1] -= push
            arcs[arcs[a][3]][1] += push
            v = arcs[arcs[a][3]][0]
    return [arcs[2 * i + 1][1] for i in range(len(edges))]


def _candidates(need, inv):
    """[(row, verdict word, rank, side)] a need could use: its cards, then its stand-ins that
    differ (not the close-name hints)."""
    out = [(c["row"], c["verdict"], _RANK[c["verdict"]], c["side"]) for c in need["cards"] if c["verdict"] in _RANK]
    out += [(s["row"], "differs", _STAND_IN, s["side"]) for s in need["stand_ins"] if not s["close"]]
    return [c for c in out if int(inv.rows[c[0]]["quantity"]) > 0]


def plan(inv, built, space=spaces.HOME, warnings=None):
    """{"decks": [{id, title, before, after, lines: [{text, sides}], changed, packs: [{token, row,
    verdict, side, card}], short: [token], spares, sha256, parsed, stored}], "tokens_sha256",
    "sha256"}: a Token cards line for each built deck of space (see the module docstring), in id
    order. inv is the space's token cards, built [(deck id, title, deck_tokens' needs worked out
    with every row free)] its built decks (tokens.plan_token_cards reads both). before is the
    deck's line as written (None when it has none), after the planned one; packs says which row
    each token gets (verdict exact, agrees, check or differs; side the face it's used for), lines
    each part of after with sides ("both sides used" or "Zombie side only, can be sleeved" for a
    double-sided card), short the tokens no card was left for, spares how many extra cards it got.
    sha256 covers what an apply must find unchanged: each deck's text and its planned line, and
    the rows. Problems go in warnings."""
    from decklab.lib.inventory.ops_decks import parsed_deck
    warnings = [] if warnings is None else warnings
    current = reserve.holds(inv, space, warnings)
    snapshot = inventory.current()
    found = []
    for deck_id, title, needs in built:
        stored = snapshot.deck(deck_id)
        parsed = parsed_deck(stored)
        before = parsed.get_field(decks.TOKEN_CARDS_FIELD) if decks.has_token_cards(parsed) else None
        found.append({"id": deck_id, "title": title, "stored": stored, "parsed": parsed, "before": before,
                      "needs": needs})
    found.sort(key=lambda d: d["id"])

    # Fixed holders outside this plan (intact products) keep their physical cards.
    # An unreadable reservation cannot silently become free stock.
    if any(hold.get("error") for hold in current.values()):
        from .products import FAILED
        raise RuntimeError(FAILED)
    planned = {d["id"] for d in found}
    locked = collections.Counter()
    for holder, hold in current.items():
        if holder not in planned:
            locked.update(hold["rows"])
    capacities = [max(int(row["quantity"]) - locked[i], 0) for i, row in enumerate(inv.rows)]

    # The flow: source -> each need (1) -> each row it could use (rank) -> sink (the row's quantity).
    needs = [(d, need, _candidates(need, inv)) for d in found for need in d["needs"]]
    source, sink = 0, 1 + len(needs) + len(inv.rows)
    edges, uses = [], []
    for n, (deck, need, options) in enumerate(needs):
        edges.append((source, 1 + n, 1, 0))
        packed = current.get(deck["id"], {}).get("rows", {})
        for row, verdict, rank, side in options:
            cost = (rank * _RANK_WEIGHT + (0 if packed.get(row) else _MOVE_WEIGHT)
                    + (_TWO_SIDED_WEIGHT if _two_sided(inv.rows[row]) else 0))
            uses.append((len(edges), n, row, verdict, side))
            edges.append((1 + n, 1 + len(needs) + row, 1, cost))
    for i, row in enumerate(inv.rows):
        edges.append((1 + len(needs) + i, sink, capacities[i], 0))
    flow = _min_cost_flow(sink + 1, edges, source, sink)

    given = {d["id"]: {} for d in found}             # deck -> {row: cards}
    packs = {d["id"]: [] for d in found}
    short = {d["id"]: [] for d in found}
    served = set()
    for edge, n, row, verdict, side in uses:
        if flow[edge]:
            deck, need, _ = needs[n]
            given[deck["id"]][row] = given[deck["id"]].get(row, 0) + 1
            packs[deck["id"]].append({"token": need["name"], "row": row, "verdict": verdict, "side": side,
                                      "card": label(inv.rows[row])})
            served.add(n)
    for n, (deck, need, _) in enumerate(needs):
        if n not in served:
            short[deck["id"]].append(need["name"])

    # The spares, dealt round the decks given each row (or that could use it), in id order.
    spares = {d["id"]: 0 for d in found}
    for i, row in enumerate(inv.rows):
        left = capacities[i] - sum(g.get(i, 0) for g in given.values())
        takers = [d["id"] for d in found if given[d["id"]].get(i)]
        if not takers:
            takers = sorted({deck["id"] for deck, _, options in needs
                             if any(r == i and rank < _STAND_IN for r, _, rank, _ in options)})
        for k in range(max(left, 0) if takers else 0):
            deck_id = takers[k % len(takers)]
            given[deck_id][i] = given[deck_id].get(i, 0) + 1
            spares[deck_id] += 1

    out = []
    for d in found:
        lines, sides = {}, {}
        for i in sorted(given[d["id"]]):
            line = reserve.line_for(inv.rows[i], given[d["id"]][i])
            key = (line.front, line.back, line.set, line.number)
            if key in lines:
                line = decks.TokenCardLine(lines[key].quantity + line.quantity, *key)
            lines[key] = line
            row = inv.rows[i]
            faces = {cards.fold(row[p["side"]]): row[p["side"]] for p in packs[d["id"]] if p["row"] == i}
            if _two_sided(row) and faces:
                sides.setdefault(key, set()).add(
                    "both sides used" if len(faces) > 1 else f"{next(iter(faces.values()))} side only, can be sleeved")
        after = decks.format_token_cards(list(lines.values()))
        out.append({"id": d["id"], "title": d["title"], "before": d["before"], "after": after,
                    "lines": [{"text": line.text(), "sides": sorted(sides.get(key, ()))} for key, line in lines.items()],
                    "changed": d["before"] != after,
                    "packs": sorted(packs[d["id"]], key=lambda p: cards.fold(p["token"])),
                    "short": sorted(short[d["id"]], key=cards.fold), "spares": spares[d["id"]],
                    "sha256": d["stored"].sha256, "parsed": d["parsed"], "stored": d["stored"]})
    digest = hashlib.sha256(json.dumps([inv.sha256, snapshot.revision, snapshot.decks_revision,
                                       [(d["id"], d["sha256"], d["after"]) for d in out]])
                            .encode()).hexdigest()
    return {"decks": out, "tokens_sha256": inv.sha256, "inventory_revision": snapshot.revision,
            "decks_revision": snapshot.decks_revision, "sha256": digest}
