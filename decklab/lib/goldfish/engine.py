"""The goldfish package's game loop: _Engine's lookup tables, built from a
deck model (model.py), exact colour payment (Hall's theorem), the casting
plan, land choice and searches, chosen colours, London mulligans, and
_play_games(), which plays games turn by turn and counts what happens.
"""
import itertools
from collections import Counter

from .common import (ALWAYS_KEEP, ANY_MANA, BIG_SPELL, BOTTOM_LANDS_ABOVE, COLOUR_TURNS, FLOOD_FROM_TURN,
                     FLOOD_GAME_TURNS, FREE_KEEP_LANDS, IF_BASICS, IF_EARLY, IF_FEW, IF_MANY, IF_MANY_TYPE, IF_REVEAL,
                     IF_TYPE, KEEP_LANDS, MISSED_DROP_TURNS, POP, SETUPS, STUCK_TURNS, TAPPED, UNTAPPED, _colour_bits)


# ================================================================ engine

class _Engine:
    """Lookup tables for one deck, built from its model in each worker."""

    def __init__(self, model):
        cs = model["cards"]
        self.NAMES = [c["name"] for c in cs]
        self.deck0 = list(model["deck"])
        self.commanders = list(model["commanders"])
        self.colour_bits = list(model["colours"])
        self.deck_need = 0
        for b in self.colour_bits:
            self.deck_need |= b
        self.basic_mask = model["basic_mask"] or self.deck_need
        n = len(cs)
        self.IS_LAND = [c["kind"] == "land" for c in cs]
        self.IS_MDFC = [c["kind"] == "mdfc" for c in cs]
        self.KEEPLAND = [c["kind"] in ("land", "mdfc") for c in cs]
        self.SPELL = [c["kind"] in ("spell", "mdfc") and bool(c["options"]) for c in cs]
        self.LMASK = [0] * n
        self.LAMT = [0] * n
        self.LMIN = [0] * n
        self.LRULE = [(UNTAPPED, 0, 0)] * n
        self.LSUB = [0] * n
        self.BASIC = [False] * n
        self.UNTAP1 = [True] * n
        self.FETCH = [None] * n
        self.LENTER = [None] * n
        self.CHOICES = [c.get("choices") for c in cs]       # a chosen-colour land's copies, one per colour
        self.BASE = [c.get("variant_of", i) for i, c in enumerate(cs)]     # such a copy's card
        for i, c in enumerate(cs):
            land = c["land"]
            if land:
                (self.LMASK[i], self.LAMT[i], self.LMIN[i], rule, self.LSUB[i], self.BASIC[i],
                 self.UNTAP1[i], fetch, enter, _) = land
                self.LRULE[i] = tuple(rule)
                self.FETCH[i] = tuple(fetch) if fetch else None
                self.LENTER[i] = tuple(enter) if enter else None
        # Payment options: (mana value, generic, pips tuple, mana paid).
        self.OPTS = [tuple((o[0], o[1], tuple(o[2]), o[3]) for o in c["options"]) for c in cs]
        self.NEED = [c["need"] for c in cs]
        self.EFF = [tuple(c["effect"]) if c["effect"] else None for c in cs]
        # The colours the deck can make at all (compile_deck). MINPAID, the least
        # mana a spell can cost, is for the ways to pay it in those colours (a
        # {2/W} spell in a green deck costs its generic price), so colour screw
        # is only counted when the colours could be there.
        makes = model["makes"]
        self.MINPAID = [min((o[3] for o in opts if all(p & makes for p in o[2])),
                            default=min((o[3] for o in opts), default=0)) for opts in self.OPTS]
        # Mana a card adds the turn it's cast: an untapped rock or a hasty mana
        # creature, as (mask, amount, mana its ability costs).
        self.NOW = [None] * n
        for i, e in enumerate(self.EFF):
            if e and ((e[0] == "rock" and not e[3]) or (e[0] == "dork" and e[3])) and e[2]:
                self.NOW[i] = (e[1], e[2], e[4])
        # Spells are tried most expensive first; on a tie, one making mana this turn, then any other
        # mana producer or ramp, then the rest (by name, so the order never depends on the deck).
        producer = [0 if self.NOW[i] else 1 if e is not None else 2 for i, e in enumerate(self.EFF)]
        mv = [max((o[0] for o in opts), default=-1) for opts in self.OPTS]
        order = sorted(range(n), key=lambda i: (-mv[i], producer[i], cs[i]["name"]))
        self.RANK = [0] * n
        for r, i in enumerate(order):
            self.RANK[i] = r
        self.memo = {}          # (pool id, generic, pips) -> payable
        self.pool_ids = {}      # sorted pool -> small int
        self.hall = {}          # pips -> Hall's condition table

    def pool_id(self, pool):
        key = tuple(sorted(pool))
        pid = self.pool_ids.get(key)
        if pid is None:
            if len(self.pool_ids) > 200_000:        # keep memory bounded on long runs
                self.pool_ids.clear()
                self.memo.clear()
            pid = self.pool_ids[key] = len(self.pool_ids)
        return pid

    def payable(self, pool, pid, g, pips):
        key = (pid, g, pips)
        ok = self.memo.get(key)
        if ok is None:
            ok = self.memo[key] = _payable(pool, g, pips, self.hall)
        return ok

    def castable(self, pool, pid, c):
        for o in self.OPTS[c]:
            if self.payable(pool, pid, o[1], o[2]):
                return True
        return False


def _hall_table(pips):
    """((union of pip masks, pips needing it), ...) for every group of pip
    kinds: Hall's condition says the pips can each get their own source
    exactly when every group has at least that many sources making one of
    its colours."""
    counts = Counter(pips)
    kinds = list(counts)
    need = {}
    for r in range(1, 1 << len(kinds)):
        union = k = 0
        for i, m in enumerate(kinds):
            if r >> i & 1:
                union |= m
                k += counts[m]
        if k > need.get(union, 0):
            need[union] = k
    return tuple(need.items())


def _payable(pool, g, pips, hall):
    """Can the sources in pool (one colour mask per mana) pay g generic and
    one source per pip (a mask of the colours that pay it)?"""
    if g + len(pips) > len(pool):
        return False
    if not pips:
        return True
    table = hall.get(pips)
    if table is None:
        table = hall[pips] = _hall_table(pips)
    for union, need in table:
        n = 0
        for m in pool:
            if m & union:
                n += 1
        if n < need:
            return False
    return True


def _leftover(pool, g, pips):
    """The sources left after paying g generic and pips (payable), keeping
    the most flexible ones: each pip takes the source with the fewest
    colours that works, generic takes the least flexible of the rest."""
    srcs = sorted(pool, key=lambda m: (POP[m], -m))
    used = [False] * len(srcs)
    order = sorted(pips, key=lambda p: sum(1 for s in srcs if s & p))

    def assign(i):
        if i == len(order):
            return True
        for j, s in enumerate(srcs):
            if not used[j] and s & order[i]:
                used[j] = True
                if assign(i + 1):
                    return True
                used[j] = False
        return False

    assign(0)
    rest = [s for j, s in enumerate(srcs) if not used[j]]
    return rest[g:]


def _leftovers(E, pool, g, pips):
    """Every different set of sources that can be left after paying g
    generic and pips from pool (payable), _leftover's choice first. A
    generator: the others are only worked out if they're wanted."""
    first = _leftover(pool, g, pips)
    yield first
    seen = {tuple(sorted(first))}
    kinds = sorted(set(pool))
    counts = [pool.count(m) for m in kinds]
    k = g + len(pips)
    for take in itertools.product(*(range(n + 1) for n in counts)):
        if sum(take) != k:
            continue
        left = [m for m, n, c in zip(kinds, take, counts) for _ in range(c - n)]
        key = tuple(left)
        if key in seen:
            continue
        paid = [m for m, n in zip(kinds, take) for _ in range(n)]
        if _payable(paid, g, pips, E.hall):
            seen.add(key)
            yield left


def _cast_order_key(casts, spent):
    """How good a turn's casts are: the most expensive spell first, then the
    next (the casting rule), then the mana spent."""
    return tuple(sorted((opt[0] for _, opt in casts), reverse=True)), spent


def _cast(E, pool, rem, cg, cp):
    """Cast from rem (spells sorted most expensive first) with the sources in
    pool, where cg generic and pips cp are already spoken for: (casts
    [(card, option)], mana spent, mana added by rocks, pool, cg, cp) with
    the pool and costs as they end up."""
    pid = E.pool_id(pool)
    OPTS, NOW, MINPAID = E.OPTS, E.NOW, E.MINPAID
    casts = []
    spent = added = 0
    i = 0
    while i < len(rem):
        c = rem[i]
        chosen = None
        for opt in OPTS[c]:
            g = cg + opt[1]
            p = opt[2]
            if cp:
                p = tuple(sorted(cp + p)) if p else cp
            if E.payable(pool, pid, g, p):
                chosen = opt
                break
        if chosen is None:
            i += 1
            continue
        del rem[i]
        casts.append((c, chosen))
        spent += chosen[3]
        now = NOW[c]
        if now and len(pool) - g - len(p) >= now[2]:
            # Its mana pays for what comes after it, so settle what's been paid so far. Sources
            # can be spent in more than one way; keep the leftover that casts the most after it
            # (the first, _leftover's, unless another does better).
            made = [now[0]] * now[1]
            added += now[1]
            best = None
            room = len(pool) - g - len(p) + now[1]
            for left in _leftovers(E, pool, g, p):
                trial = _cast(E, left + made, list(rem), 0, ())
                if best is None or _cast_order_key(trial[0], trial[1]) > _cast_order_key(best[0], best[1]):
                    best = trial
                cast_now = {x for x, _ in trial[0]}
                if not any(MINPAID[x] <= room for x in rem if x not in cast_now):
                    break       # nothing left in hand could be cast with any leftover
            more, more_spent, more_added, pool, cg, cp = best
            return casts + more, spent + more_spent, added + more_added, pool, cg, cp
        cg, cp = g, p
    return casts, spent, added, pool, cg, cp


def _plan(E, pool, cands, abilities, t):
    """What gets cast this turn: (casts [(card, option)], abilities used,
    mana spent, mana added by rocks). cands are the spells in hand and the
    waiting commander, sorted most expensive first; abilities are ramp
    abilities on the battlefield ([cost, ready turn, ...])."""
    casts, spent, added, pool, cg, cp = _cast(E, pool, list(cands), 0, ())
    used = []
    ready = [a for a in abilities if a[1] <= t]
    for c, _ in casts:
        e = E.EFF[c]
        if e and e[0] == "ability" and not e[2]:
            ready.append([e[1], t] + list(e[3:]) + [c])
    pid = E.pool_id(pool) if ready else None
    for a in ready:
        if E.payable(pool, pid, cg + a[0], cp):
            cg += a[0]
            spent += a[0]
            used.append(a)
    return casts, used, spent, added


def _pick(E, library, ptr, spec, spells, have, later, rng):
    """The land a search would find in the library, or None; changes
    nothing. It's the one that helps most, as for a colour chosen as a land
    enters (_colour_rank: spells, have, later), then one that enters
    untapped; a tie goes at random."""
    basic, types = spec
    best = best_score = None
    IS_LAND, BASIC, LSUB, LMASK, UNTAP1 = E.IS_LAND, E.BASIC, E.LSUB, E.LMASK, E.UNTAP1
    rank = _colour_rank(E, spells, have, later)
    seen = set()
    for i in range(ptr, len(library)):
        c = library[i]
        if c in seen or not IS_LAND[c] or (basic and not BASIC[c]) or (types and not LSUB[c] & types):
            continue
        seen.add(c)
        score = (rank(LMASK[c]), UNTAP1[c], rng.random())
        if best is None or score > best_score:
            best, best_score = c, score
    return best


def _search(E, library, ptr, spec, spells, have, later, rng, draws_left, best=None):
    """Take the land a search finds (best, if it's been picked already, else
    _pick's; a random copy of it) out of the library, shuffle, and return
    it (or None)."""
    if best is None:
        best = _pick(E, library, ptr, spec, spells, have, later, rng)
    if best is None:
        return None
    spots = [i for i in range(ptr, len(library)) if library[i] == best]
    del library[spots[int(rng.random() * len(spots))]]
    n = len(library)
    for i in range(ptr, min(n, ptr + draws_left)):      # "then shuffle": the next draws are random again
        j = i + int(rng.random() * (n - i))
        library[i], library[j] = library[j], library[i]
    return best


def _later_colours(E, hand):
    """The colours the lands in hand make: they come down on later turns.
    A land whose colour is chosen as it enters doesn't count, since it can
    still make any of its colours."""
    later = 0
    for x in hand:
        if E.IS_LAND[x] and not E.CHOICES[x]:
            later |= E.LMASK[x]
    return later


def _colour_rank(E, spells, have, later):
    """_best_colour's order, as a sort key for a colour mask (ties aside)."""
    NEED, deck_need = E.NEED, E.deck_need
    soon = have | later

    def wanted(m):
        return sum(1 for x in spells if NEED[x] & m) if m else 0

    return lambda m: (wanted(m & ~soon), POP[m & deck_need & ~soon], wanted(m & ~have), POP[m & deck_need & ~have],
                      wanted(m), POP[m & deck_need])


def _best_colour(E, masks, spells, have, later, rng):
    """Of the colour masks a source can be given as it enters (one colour
    chosen), the one that helps most: the colour most of your spells
    (spells: in hand, and a commander waiting to be cast) need that neither
    your permanents (have) nor the lands in your hand (later) make, then
    one the deck needs that they don't make; then the same two with your
    permanents alone; then the colour most of your spells need, then one
    the deck needs. So Uncharted Haven with an Island in hand, in a deck of
    blue and black spells, makes black. A tie goes at random (rng), so no
    colour is favoured: two mirror-image decks get mirror-image numbers."""
    rank = _colour_rank(E, spells, have, later)
    return max(masks, key=lambda m: (rank(m), rng.random()))


def _choose(E, c, spells, have, hand, rng):
    """Land c as it enters: for a land whose colour is chosen then (Uncharted
    Haven, a Pathway's face), its copy making the colour that helps most
    (_best_colour; hand for the lands in it); any other land as it is."""
    choices = E.CHOICES[c]
    if not choices:
        return c
    best = _best_colour(E, [E.LMASK[v] for v in choices], spells, have, _later_colours(E, hand), rng)
    return next(v for v in choices if E.LMASK[v] == best)


def _ranked_choices(E, c, spells, have, hand, rng):
    """Land c's copies, one per colour it can choose as it enters, the one
    that helps most first (_best_colour); [c] for any other land."""
    choices = E.CHOICES[c]
    if not choices:
        return [c]
    rank = _colour_rank(E, spells, have, _later_colours(E, hand))
    return sorted(choices, key=lambda v: (rank(E.LMASK[v]), rng.random()), reverse=True)


def _source_mask(E, e, hand, waiting, lands_bf, perms, rng):
    """The colours a mana creature or rock (effect e) makes once it's on the
    battlefield: for one whose colour is chosen as it enters (Heraldic
    Banner), the colour that helps most then."""
    mask, chosen = e[1], e[5]
    if not chosen:
        return mask
    have = 0
    for l, _ in lands_bf:
        have |= E.LMASK[l]
    for p in perms:
        have |= p[0]
    return _best_colour(E, [mask & ~chosen | bit for bit in _colour_bits(chosen)], hand + waiting, have,
                        _later_colours(E, hand), rng)


def _enters_untapped(E, c, lands_bf, hand, t, multiplayer):
    code, a, b = E.LRULE[c]
    if code == UNTAPPED:
        return True
    if code == TAPPED:
        return False
    if code == IF_TYPE:
        return any(E.LSUB[l] & a for l, _ in lands_bf)
    if code == IF_BASICS:
        return sum(1 for l, _ in lands_bf if E.BASIC[l]) >= a
    if code == IF_FEW:
        return len(lands_bf) <= a
    if code == IF_MANY:
        return len(lands_bf) >= a
    if code == IF_MANY_TYPE:
        return sum(1 for l, _ in lands_bf if E.LSUB[l] & b) >= a
    if code == IF_REVEAL:
        n = sum(1 for x in hand if E.IS_LAND[x] and E.LSUB[x] & a)
        return n - (1 if E.LSUB[c] & a else 0) >= 1
    if code == IF_EARLY:
        return t <= a
    return multiplayer


def _keeps(E, hand, free):
    """Karsten's keep rule for a hand (after bottoming); free: it's the
    multiplayer game's first 7, which costs nothing to throw back."""
    size = len(hand)
    if size <= ALWAYS_KEEP:
        return True
    lands = 0
    for c in hand:
        if E.KEEPLAND[c]:
            lands += 1
    low, high = FREE_KEEP_LANDS if free else KEEP_LANDS[size]
    return low <= lands <= high


def _deal(E, deck, rng, K, free_mulligan, mulligans):
    """(hand, bottomed, mulligans taken): the London mulligan with the keep
    rules above. deck is shuffled in place (its first K places: all the
    cards a game can draw); its first 7 cards are the last hand drawn."""
    n = len(deck)
    rnd = rng.random
    taken = 0
    while True:
        for i in range(K):
            j = i + int(rnd() * (n - i))
            deck[i], deck[j] = deck[j], deck[i]
        hand = deck[:7]
        if not mulligans:
            return hand, [], 0
        # CR 103.5: bottom one card per mulligan taken; 103.5c: the first is free in multiplayer.
        bottom = taken - (1 if free_mulligan and taken else 0)
        bottomed = []
        if bottom:
            hand, bottomed = _bottom(E, hand, bottom)
        if _keeps(E, hand, free_mulligan and taken == 0):
            return hand, bottomed, taken
        taken += 1


def _bottom(E, hand, k):
    """Karsten's bottoming: k times, a land while there are more than 3,
    else the most expensive spell."""
    hand = list(hand)
    out = []
    for _ in range(k):
        lands = [c for c in hand if E.KEEPLAND[c]]
        need = 0
        for c in hand:
            if not E.KEEPLAND[c]:
                need |= E.NEED[c]
        if len(lands) > BOTTOM_LANDS_ABOVE:
            # Least useful: a plain land before a spell // land card; one whose colours the other
            # lands in hand also make, so the hand's only source of a colour your spells need, then
            # of one the deck needs (a splash), stays; makes fewest colours the spells need; enters
            # tapped. A tie goes by the order of the hand, which is random (not by card, which
            # would favour one colour of a two-colour deck).
            def key(i):
                c = lands[i]
                others = 0
                for j, x in enumerate(lands):
                    if j != i:
                        others |= E.LMASK[x]
                alone = E.LMASK[c] & ~others
                return (E.IS_MDFC[c], POP[alone & need], POP[alone & E.deck_need], POP[E.LMASK[c] & need],
                        E.UNTAP1[c], POP[E.LMASK[c]])
            pick = lands[min(range(len(lands)), key=key)]
        else:
            spells = [c for c in hand if not E.KEEPLAND[c]]
            made = 0
            for c in lands:
                made |= E.LMASK[c]
            pick = max(spells, key=lambda c: (E.MINPAID[c] if E.OPTS[c] else 99, bool(E.NEED[c] & ~made)))
        hand.remove(pick)
        out.append(pick)
    return hand, out


def _new_counts(turns, n_colours):
    z = [0] * (turns + 1)
    return {"games": 0, "mulligan": 0, "free": 0, "kept": [0] * 8,
            "drop": list(z), "mana": list(z), "mana_sum": list(z),
            "stuck": 0, "missed": 0, "flood_turns": 0, "flood_games": 0,
            "colour": [list(z) for _ in range(n_colours)], "screw": 0, "screw_wasted": 0,
            "spent": list(z), "avail": list(z), "all_used": list(z), "had_mana": list(z),
            "big": list(z), "big_never": 0}


def _add_counts(a, b):
    for key, value in b.items():
        if isinstance(value, list):
            if value and isinstance(value[0], list):
                for x, y in zip(a[key], value):
                    for i, v in enumerate(y):
                        x[i] += v
            else:
                for i, v in enumerate(value):
                    a[key][i] += v
        else:
            a[key] += value


def _play_games(E, setup, turns, games, rng, mulligans, trace=None):
    """Play games and count what happened (_new_counts). rng is a
    random.Random. trace, a list, gets one dict per turn of every game
    (for tests and debugging)."""
    S = _new_counts(turns, len(E.colour_bits))
    draw_first = SETUPS[setup]["draw_first"]
    free_mulligan = SETUPS[setup]["free_mulligan"]
    multiplayer = free_mulligan
    deck = list(E.deck0)
    K = min(len(deck), 7 + turns)
    IS_LAND, IS_MDFC, SPELL, LMASK, LAMT, LMIN, FETCH, LENTER = (E.IS_LAND, E.IS_MDFC, E.SPELL, E.LMASK, E.LAMT,
                                                                E.LMIN, E.FETCH, E.LENTER)
    RANK, NEED, EFF, MINPAID = E.RANK, E.NEED, E.EFF, E.MINPAID
    colour_bits, deck_need = E.colour_bits, E.deck_need
    n_colour_turns = min(COLOUR_TURNS, turns)
    drop, mana, mana_sum = S["drop"], S["mana"], S["mana_sum"]
    spent_c, avail_c, all_used, had_mana, big_c = S["spent"], S["avail"], S["all_used"], S["had_mana"], S["big"]
    colour_c = S["colour"]
    for _ in range(games):
        hand, bottomed, taken = _deal(E, deck, rng, K, free_mulligan, mulligans)
        S["kept"][len(hand)] += 1
        if taken:
            S["mulligan"] += 1
            if free_mulligan:
                S["free"] += 1
        library = deck[7:] + bottomed
        ptr = 0
        lands_bf = []           # [land, turn it entered tapped (0: untapped)]
        perms = []              # (mask, amount, first turn it makes mana, mana its ability costs)
        abilities = []          # ramp abilities: [cost, ready turn, lands, to hand, spec, sac, card]
        waiting = list(E.commanders)
        played = missed = flood = 0
        stuck = False
        first_big = 0
        for t in range(1, turns + 1):
            if (t > 1 or draw_first) and ptr < len(library):
                hand.append(library[ptr])
                ptr += 1
            cands = [c for c in hand if SPELL[c]] + waiting
            cands.sort(key=RANK.__getitem__)
            # A bounce land or Lotus Field is only played with the lands it needs to take.
            options = ([c for c in hand if IS_LAND[c] and (not LENTER[c] or _can_enter(E, c, lands_bf))]
                       or [c for c in hand if IS_MDFC[c] and (not LENTER[c] or _can_enter(E, c, lands_bf))])
            after = len(lands_bf) + (1 if options else 0)
            base = []
            have = 0
            for l, _ in lands_bf:
                have |= LMASK[l]
                a = LAMT[l]
                if a and (not LMIN[l] or after >= LMIN[l]):
                    if a == 1:
                        base.append(LMASK[l])
                    else:
                        base.extend([LMASK[l]] * a)
            for m, a, f, k in perms:
                have |= m
                if f <= t and len(base) >= k:      # k: mana its ability costs (a Signet's {1})
                    base.extend([m] * a)
            plan = None
            played_now = False
            played_name = None
            gone = 0            # mana this turn from lands the land drop returned or sacrificed
            if options:
                need = 0
                for c in cands:
                    need |= NEED[c]
                best = best_score = None
                tried = {}
                for c in options:
                    if c in tried:
                        continue
                    fetch = FETCH[c]
                    if fetch is None:
                        untapped = _enters_untapped(E, c, lands_bf, hand, t, multiplayer)
                        # A land whose colour is chosen as it enters: untapped (a Pathway), each colour
                        # is tried, and the one letting you spend the most is used (on a tie, the one
                        # that helps most); tapped (Uncharted Haven), the one that helps most.
                        sources = (_ranked_choices(E, c, cands, have, hand, rng) if untapped
                                   else [_choose(E, c, cands, have, hand, rng)])
                    else:
                        # Sacrificed for the land it finds, which may enter untapped (Prismatic
                        # Vista; Fabled Passage with enough lands) unless that land's own text says
                        # it enters tapped (a Triome): then its mana counts now.
                        untapped = not fetch[3] or (fetch[4] and len(lands_bf) + 1 >= fetch[4])
                        source = (_pick(E, library, ptr, fetch[1:3], cands, have, _later_colours(E, hand), rng)
                                  if untapped else None)
                        untapped = (untapped and source is not None
                                    and _enters_untapped(E, source, lands_bf, hand, t, multiplayer))
                        if untapped:
                            source = _choose(E, source, cands, have, hand, rng)
                        sources = (source,)
                        colours = E.basic_mask
                    own = base
                    if LENTER[c] and LENTER[c][3]:
                        # It returns an untapped land (Coral Atoll), whose mana can't be used first.
                        own = list(base)
                        for i in _takes(E, c, lands_bf, need):
                            l = lands_bf[i][0]
                            if LAMT[l] and (not LMIN[l] or after >= LMIN[l]):
                                for _ in range(LAMT[l]):
                                    own.remove(LMASK[l])
                    pl = None
                    for s in sources:
                        sa = LAMT[s] if untapped and (not LMIN[s] or after >= LMIN[s]) else 0
                        made = LMASK[s] if sa else 0
                        pool = own + [made] * sa if sa else own
                        key = (made, sa, c if IS_MDFC[c] or own is not base else -1)
                        if key in tried:
                            p = tried[key]
                        else:
                            cc = cands
                            if IS_MDFC[c]:
                                cc = list(cands)
                                cc.remove(c)
                            p = tried[key] = (_plan(E, pool, cc, abilities, t), pool, cc)
                        if pl is None or p[0][2] > pl[0][2]:
                            pl, source, a = p, s, sa
                    tried[c] = pl
                    if fetch is None:
                        colours = LMASK[source]
                    # Most mana spent; a colour the hand needs; a tapped land (saving untapped ones);
                    # one making mana now (Temple of the False God waits for 5 lands); a colour the
                    # deck needs and no permanent makes yet; more colours.
                    score = (pl[0][2], POP[colours & need & ~have], not untapped, a > 0,
                             POP[colours & deck_need & ~have], POP[colours])
                    if best is None or score > best_score:
                        best, best_score, best_untapped, best_source = c, score, untapped, source
                chosen = land = best
                plan, pool, cands = tried[land]
                hand.remove(land)
                played += 1
                played_now = True
                played_name = E.NAMES[land]
                if FETCH[land] is not None:
                    spec = FETCH[land]
                    # A land found untapped is the one (and colour) the turn's spells were planned with.
                    land = _search(E, library, ptr, spec[1:3], cands, have, _later_colours(E, hand), rng, turns - t,
                                   E.BASE[best_source] if best_untapped else None)
                    if land is not None:
                        land = best_source if best_untapped else _choose(E, land, cands, have, hand, rng)
                        lands_bf.append([land, 0 if best_untapped else t])
                        if best_untapped:
                            land = None
                elif best_untapped:
                    lands_bf.append([best_source, 0])
                    land = None
                else:
                    land = best_source
                    lands_bf.append([land, t])
                if LENTER[chosen]:
                    gone = _land_enters(E, chosen, lands_bf, hand, need, after)
            else:
                pool = base
                land = None
            if played >= t:
                drop[t] += 1
            # --- where the turn stands after the land drop. A land that entered
            # tapped this turn (land) counts as a source here, not as mana to spend;
            # lands a bounce land took back count as its mana instead of their own.
            avail = len(pool)
            pid = E.pool_id(pool)
            late = LAMT[land] if land is not None and (not LMIN[land] or after >= LMIN[land]) else 0
            if avail + late - gone >= t:
                mana[t] += 1
            mana_sum[t] += avail + late - gone
            if t <= n_colour_turns:
                now = LMASK[land] if late else 0
                for m in pool:
                    now |= m
                for i, bit in enumerate(colour_bits):
                    if now & bit:
                        colour_c[i][t] += 1
            if not played_now and t <= MISSED_DROP_TURNS:
                missed += 1
            flooded = t >= FLOOD_FROM_TURN and not cands
            if flooded:
                flood += 1
            screwed = False
            for c in cands:
                if MINPAID[c] <= avail and not E.castable(pool, pid, c):
                    screwed = True
                    S["screw"] += 1
                    break
            stuck_now = False
            if not played_now and t in STUCK_TURNS:
                more = pool + [ANY_MANA]
                mid = E.pool_id(more)
                for c in cands:
                    if not E.castable(pool, pid, c) and E.castable(more, mid, c):
                        stuck = stuck_now = True
                        break
            # --- cast
            if plan is None:
                plan = _plan(E, pool, cands, abilities, t)
            casts, used, spent, added = plan
            for c, opt in casts:
                if c in waiting:
                    waiting.remove(c)
                else:
                    hand.remove(c)
                if not first_big and opt[0] >= BIG_SPELL:
                    first_big = t
                e = EFF[c]
                if e is None:
                    continue
                kind = e[0]
                if kind == "dork":
                    perms.append((_source_mask(E, e, hand, waiting, lands_bf, perms, rng), e[2], t if e[3] else t + 1,
                                  e[4]))
                elif kind == "rock":
                    perms.append((_source_mask(E, e, hand, waiting, lands_bf, perms, rng), e[2], t + 1 if e[3] else t,
                                  e[4]))
                elif kind == "aura":
                    perms.append((e[1], e[2], t + 1, 0))
                elif kind == "ramp":
                    _ramp(E, e[1], e[2], e[3], e[4], lands_bf, hand, waiting, library, ptr, perms, rng,
                          turns - t, t)
                elif kind == "ability":
                    abilities.append([e[1], t + e[2]] + list(e[3:]) + [c])
            for a in used:
                abilities.remove(a)
                _ramp(E, a[2], a[3], a[4], a[5], lands_bf, hand, waiting, library, ptr, perms, rng, turns - t, t)
            total = avail + added
            spent_c[t] += spent
            avail_c[t] += total
            if total:
                had_mana[t] += 1
                if spent >= total:
                    all_used[t] += 1
            if screwed and spent < total:
                S["screw_wasted"] += 1
            if trace is not None:
                trace.append({
                    "turn": t, "kept": 7 - len(bottomed) if t == 1 else None,
                    "land": played_name, "land_tapped": land is not None,
                    "mana": avail + late - gone, "usable": avail, "added": added, "spent": spent,
                    "cast": [E.NAMES[c] for c, _ in casts], "abilities": [E.NAMES[a[-1]] for a in used],
                    "lands": sorted(E.NAMES[l] for l, _ in lands_bf), "hand": sorted(E.NAMES[c] for c in hand),
                    "flood": flooded, "screw": screwed, "stuck": stuck_now})
        S["missed"] += missed
        S["flood_turns"] += flood
        if flood >= FLOOD_GAME_TURNS:
            S["flood_games"] += 1
        if stuck:
            S["stuck"] += 1
        if first_big:
            big_c[first_big] += 1
        else:
            S["big_never"] += 1
    S["games"] = games
    return S


def _can_enter(E, c, lands_bf):
    """Is there a land for a bounce land to return (of its type), or two for
    Lotus Field to sacrifice? Without them it isn't played."""
    _, n, types, _ = E.LENTER[c]
    return sum(1 for l, _ in lands_bf if not types or E.LSUB[l] & types) >= n


def _takes(E, c, lands, need):
    """The places in lands (the lands on the battlefield before c) of the
    ones bounce land c returns, or Lotus Field sacrifices: your least useful
    (of the type it names)."""
    _, n, types, _ = E.LENTER[c]
    want = need | E.deck_need
    others = [i for i in range(len(lands)) if not types or E.LSUB[lands[i][0]] & types]
    others.sort(key=lambda i: (E.LAMT[lands[i][0]], POP[E.LMASK[lands[i][0]] & want],
                               POP[E.LMASK[lands[i][0]]], i))
    return others[:n]


def _land_enters(E, c, lands_bf, hand, need, after):
    """What bounce land c (just played, the last of lands_bf) does as it
    enters: return your least useful other land to your hand, or sacrifice
    the least useful ones (Lotus Field). Their mana was used this turn
    first, unless c needs an untapped one (Coral Atoll); returns how much
    mana that was."""
    what, _, _, untapped_only = E.LENTER[c]
    made = 0
    for i in sorted(_takes(E, c, lands_bf[:-1], need), reverse=True):
        l = lands_bf.pop(i)[0]
        if E.LAMT[l] and (not E.LMIN[l] or after >= E.LMIN[l]) and not untapped_only:
            made += E.LAMT[l]
        if what == "return":
            hand.append(E.BASE[l])     # a Pathway or Uncharted Haven can choose again
    return made


def _ramp(E, n_bf, n_hand, spec, sac_land, lands_bf, hand, waiting, library, ptr, perms, rng, draws_left, t):
    """Carry out a land search: sacrifice a land if it says so, then put
    n_bf lands onto the battlefield tapped and n_hand into your hand."""
    need = 0
    for c in hand + waiting:
        need |= E.NEED[c]
    have = 0
    for l, _ in lands_bf:
        have |= E.LMASK[l]
    for perm in perms:
        have |= perm[0]
    if sac_land and lands_bf:
        worst = min(range(len(lands_bf)), key=lambda i: (POP[E.LMASK[lands_bf[i][0]] & (need | E.deck_need)],
                                                          POP[E.LMASK[lands_bf[i][0]]], i))
        del lands_bf[worst]
    for _ in range(n_bf):
        got = _search(E, library, ptr, spec, hand + waiting, have, _later_colours(E, hand), rng, draws_left)
        if got is None:
            return
        got = _choose(E, got, hand + waiting, have, hand, rng)
        lands_bf.append([got, t])
        have |= E.LMASK[got]
    for _ in range(n_hand):
        got = _search(E, library, ptr, spec, hand + waiting, have, _later_colours(E, hand), rng, draws_left)
        if got is None:
            return
        hand.append(got)
