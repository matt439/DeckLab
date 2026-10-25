"""Human-readable Forge CLI output: card statistics, caveats and matchup summaries."""
from . import cli_shared as shared


def _pct(x, digits=1):
    """A share as a percentage, "52.5%" (digits: decimals), or "-"."""
    return "-" if x is None else f"{100 * x:.{digits}f}%"


# Why Forge's AI misplays a card (ai.WEAK_KINDS), for the audit's list; as on the page (matchups.js).
WEAK_WORDS = {
    "remove_all": "never cast: its card script tells the AI to leave it out",
    "etb": "not cast while its enters ability would do nothing useful",
    "flash": "a flash creature with no enters ability: cast only at the end of the opponent's turn",
    "team_pump": "pumps the whole team, which the AI judges one creature at a time",
    "strict_targets": "the AI only aims it at {targets}",
    "counterspell": "a counterspell: the AI never keeps mana open for it",
}
# Why a list is flagged (ai._pilot's "why").
PILOT_WHY = {
    "commander": "its commander is one Forge's AI never casts or holds back",
    "team_pumps": "{team_pumps} cards pump the whole team ({split})",
    "share": "{copies:g} copies of cards Forge's AI misplays (flagged at {needed:g})",
}


def _weak_words(card):
    """What Forge's AI does wrong with a card of ai._pilot's "cards": its first kind's words."""
    kind = card["why"][0]
    detail = card["detail"].get(kind, "")
    if kind == "etb" and detail == "no_target":
        return "held until its enters ability has a target, unless the AI is in danger"
    if kind == "strict_targets":
        found = shared.re.fullmatch(r"Card\.cmcGE(\d+)", detail)
        return WEAK_WORDS[kind].replace("{targets}", f"mana value {found.group(1)} or more" if found
                                        else f"its card script's targets ({detail})")
    return WEAK_WORDS[kind]


def _pump_split(pilot):
    """ai._pilot's team pumps split into spells and permanents' abilities: "3 spells, 3 permanents'
    abilities" ("4 spells" when there are only spells)."""
    spells = pilot.get("team_pump_spells", 0)
    abilities = pilot["team_pumps"] - spells
    parts = ([f"{spells} spell{'' if spells == 1 else 's'}"] if spells else []) + (
        [f"{abilities} permanent's ability" if abilities == 1 else f"{abilities} permanents' abilities"]
        if abilities else [])
    return ", ".join(parts)


def _print_pilot(pilot):
    """ai._pilot's verdict and the cards behind it, for the audit."""
    if pilot["poor"]:
        why = PILOT_WHY[pilot["why"]].format(**pilot, split=_pump_split(pilot))
        print(f"  Forge pilots this list poorly: {why}")
    elif pilot["cards"]:
        copies = f"{pilot['copies']:g} cop{'y' if pilot['copies'] == 1 else 'ies'}"
        print(f"  Forge pilots this list well enough: {copies} of cards its AI misplays (flagged at {pilot['needed']:g})")
    for c in pilot["cards"]:
        print(f"    {c['qty']} {c['name']}{' (commander)' if c['commander'] else ''}: {_weak_words(c)}")


def _print_limits(title, limits):
    """The audit of one list. Its team pumps come from Forge's card scripts (the pilot's list, spells
    and permanents' abilities); the team pump spells Scryfall's oracle tags name ("team_pump") are
    printed only when those scripts can't be read, so the audit never gives two counts."""
    print(f"{title}:")
    for c in limits["cannot_play"]:
        print(f"  can't play: {c['qty']} {c['name']} ({c['why']})")
    if limits["commander_unplayable"]:
        print("  the AI never casts the commander: results are not meaningful")
    pilot = limits.get("pilot")
    tp = limits["team_pump"] if not pilot else None
    if tp:
        named = ", ".join(f"{c['qty']} {c['name']}" for c in tp["cards"])
        print(f"  team pump spells: {tp['copies']} copies ({named})")
    for c in limits["unknown"]:
        print(f"  unknown to Forge: {c['qty']} {c['name']}")
    if pilot:
        _print_pilot(pilot)
    if limits["problem"]:
        print(f"  ! {limits['problem']}")
    if not (limits["cannot_play"] or tp or limits["unknown"] or limits["problem"] or (pilot and pilot["cards"])):
        print("  nothing to flag")


# ============================================================ how far to trust a matchup (R19)
# The same words as the matchup page's (matchups.js matchupVerdict, starterTile, noiseWords,
# pilotReason and trustPart); test_forge_trust checks they stay the same.

TEMPO_WORDS = ("Forge likely understates going first in tempo and counterspell mirrors: in Deck Lab's "
               "tests going first helped much less in a tempo mirror than in a ramp mirror.")
COMMANDER_WORDS = ("Commander results are indicative only: Forge plays Commander decks one against one here, "
                   "and its Commander games haven't been checked as closely as its 60-card games.")


def _lead_words(lead, titles):
    """views.verdict_words: which deck is ahead, as the page says it."""
    return shared.verdict_words(lead, titles) or "no games yet"


def _starter_words(starter):
    """The starting player's chance of winning (views._starter) in words."""
    if not starter:
        return "starting player: no games yet"
    numbers = f"{_pct(starter['value'])} ({_pct(starter['low'])}-{_pct(starter['high'])})"
    if starter["balanced"]:
        return f"starting player won {numbers}, the average of both decks going first"
    return f"starting player won {numbers} of the games: one deck never went first, so it isn't balanced"


def _noise_words(points, games):
    """How far apart two results of this many games can come out by chance (views._noise_points)."""
    if points is None:
        return None
    if points < 1:
        size = "under 1 point"
    else:
        low = int(points)
        high = low if points == low else low + 1
        size = f"about {low} points" if low == high else f"about {low}-{high} points"
    return (f"Two results of {games:,} games like this one can differ by {size} by chance alone, so treat "
            "smaller differences as noise.")


def _pilot_reason(pilot):
    """Why Forge pilots a list poorly (ai._pilot), or None when it doesn't."""
    if not pilot or not pilot["poor"]:
        return None
    lower = "Its win rates here are probably lower than the real deck's."
    if pilot["why"] == "commander":
        return f"Forge's AI never casts its commander or holds it back. {lower}"
    if pilot["why"] == "team_pumps":
        measured = (" Holding the spells back put a go-wide deck 12 to 15 points too low in Deck Lab's tests."
                    if pilot.get("team_pump_spells") else "")
        return (f"{pilot['team_pumps']} of its cards pump the whole team ({_pump_split(pilot)}), which Forge's AI "
                f"judges one creature at a time, so it uses them too rarely and attacks too little.{measured} {lower}")
    copies = sum(c["qty"] for c in pilot["cards"])
    return f"{copies} of its cards are kinds Forge's AI misplays. {lower}"


def _trust_lines(result, v, titles, sha):
    """How far to trust a matchup's numbers (R19): the noise between results this size, each
    deck Forge pilots poorly, the tempo caveat when both decks hold counterspells, and that
    Commander results are indicative only. v is views.view(result, sha), titles[0] sha's title.
    As on the page (trustPart), a deck whose commander is never cast gets no pilot line when the
    result is not meaningful: the "not meaningful" line already says so."""
    lines = [_noise_words(v["noise_points"], v["games"])]
    p = shared._perspective(result, sha)
    limits = [shared.ai.side_ai(result, side) for side in (p, 1 - p)]     # one binding, for the tests' patch
    pilots = [side["pilot"] for side in limits]
    for side, pilot, title in zip(limits, pilots, titles):
        reason = _pilot_reason(pilot)
        if reason and not (v["not_meaningful"] and side["commander_unplayable"]):
            lines.append(f"Forge pilots {title} poorly: {reason}")
    if all(pilot and pilot["counterspells"] for pilot in pilots):
        lines.append(TEMPO_WORDS)
    if result["format"] == "Commander":
        lines.append(COMMANDER_WORDS)
    return [line for line in lines if line]


# ============================================================ per-card stats

def _range(wr):
    """A win rate and its range, "52% (47-57)", or "-"."""
    if wr is None:
        return "-"
    return f"{100 * wr['value']:.0f}% ({100 * wr['low']:.0f}-{100 * wr['high']:.0f})"


VERDICTS = {"more": "won more when {what}", "less": "won less when {what}", "unclear": "no clear difference"}
EARLY = "in hand by turn 3"         # what a row of basis "early" is judged on (cardstats' early split)
LEANS = " (leans with game length)"     # after a "drawn" verdict from a cardstats that also counts EARLY


def _diff(row, what="drawn", compared=0):
    """A win-rate difference in points with its range, best estimate and verdict: "+5 (-3 to
    +13), best +2, no clear difference"; a land's says "no verdict for a land" (cardstats
    never judges one). A range clear of 0 that doesn't stand out among the compared rows (not
    a Benjamini-Hochberg discovery) says it's within chance. A row without a best estimate
    (from an older cardstats) shows none. what is what the verdict is on: "drawn", "cast"
    (a commander) or EARLY (a row of basis "early"). A row judged on when it was drawn by a
    cardstats that also counts EARLY (basis "drawn": its games were kept before that was
    counted) says its "won more" or "won less" leans with game length (LEANS)."""
    d = row.get("diff")
    if d is None:
        return "-"
    if row.get("land") is True:
        verdict = "no verdict for a land"
    else:
        verdict = VERDICTS.get(row.get("verdict"), "not enough games to tell").format(what=what)
        if row.get("basis") == "drawn" and row.get("verdict") in ("more", "less"):
            verdict += LEANS
        if row.get("discovery") is False and compared > 1 and (d["low"] > 0 or d["high"] < 0):
            verdict += f" (range clear of 0, but within chance among {compared} cards)"
    value, low, high = (round(100 * d[k]) for k in ("value", "low", "high"))     # whole points (never "-0")
    best = "" if row.get("shrunk") is None else f", best {round(100 * row['shrunk']):+d}"
    return f"{value:+d} ({low:+d} to {high:+d}){best}, {verdict}"


def _print_cards(title, stats):
    """cardstats.list_cards' numbers as a table. With "in hand by turn 3" counted (basis
    "early"), the table has its share of games ("by t3") and its win rates, which the
    difference and verdict are on; without it (an earlier card log's games), the drawn
    ones, whose verdicts lean with game length (said once, above the table). A land, never
    judged, shows its drawn rates and difference either way, as the page does. Stats from
    an older cardstats (no basis) read as before. The list's games played with another engine
    than today's ("other_engine_games") are said to be left out; with no games of today's
    engine (or only an earlier card log's), it says how to get some instead of a table of 0s."""
    early = stats.get("basis") == "early"
    other = stats.get("other_engine_games") or 0
    print(f"{title}: card data from {stats['games']:,} of {stats['of']:,} games in {stats['matchups']} "
          f"matchup{'' if stats['matchups'] == 1 else 's'}"
          + (f" ({stats['bad']:,} more had a card log that failed its checks)" if stats["bad"] else ""))
    if other:
        print(f"  {other:,} more of this list's games {'was' if other == 1 else 'were'} played with an earlier engine, "
              f"or without the card log, so {'it is' if other == 1 else 'they are'} left out (replay plays those "
              "matchups again with today's engine)")
    if not stats["games"]:
        if stats.get("old"):
            print(f"  {stats['old']:,} games were logged by an earlier card log, which counted casts differently, so "
                  "they're left out")
        print("  No per-card numbers yet: play more games" + (", or replay those matchups," if other else "")
              + " to get some.")
        return
    if early and stats["early_of"] < stats["games"]:
        print(f"  in hand by turn 3: counted in {stats['early_of']:,} of those games (an earlier card log kept the "
              "rest, and didn't count it)")
    if not stats["enough"]:
        # cardstats' "enough" counts the games the verdicts are on: beside an earlier card log's, early_of.
        print(f"  ! early numbers: fewer than {stats['min_games']} games "
              + ("counting in hand by turn 3" if early and stats["early_of"] < stats["games"] else "with card data"))
    several = ("  Over several matchups the difference is worked out matchup by matchup, so it isn't always the\n"
               "  gap between the two win rates.\n" if stats["matchups"] > 1 else "")
    if early:
        key = ("  drawn: games it reached the hand; by t3: games a copy was in hand by the deck's own turn 3 (the\n"
               "  kept hand, or drawn by then); cast: copies drawn that were cast from the hand (lands: played);\n"
               "  stuck: copies drawn still in hand at the end (a card can be both cast and stuck); turn: the average\n"
               "  turn a copy was first cast or played, counting each player's own turns. won by t3 / not: the win\n"
               "  rates when a copy was in hand by turn 3 and when not, with their ranges (by turn 3 every game has\n"
               "  seen about as many cards, so unlike \"drawn\" this doesn't lean with game length). difference:\n"
               "  by t3 minus not in points, with its 95% range; best: that pulled toward 0, the more so the fewer\n"
               "  the games.\n"
               + several)
    else:
        key = ("  drawn: games it reached the hand; cast: copies drawn that were cast from the hand (lands: played);\n"
               "  stuck: copies drawn still in hand at the end (a card can be both cast and stuck); turn: the average\n"
               "  turn a copy was first cast or played, counting each player's own turns. won drawn / not: the win\n"
               "  rates when it was drawn and when it wasn't, with their ranges (long games draw more cards, so game\n"
               "  length alone can make a card look better or worse). difference: drawn minus not in points, with its\n"
               "  95% range; best: that pulled toward 0, the more so the fewer the games.\n"
               + several
               + ("  These games were kept before the card log counted \"in hand by turn 3\", so the verdicts are on\n"
                  "  \"drawn\", and a \"won more\" or \"won less\" leans with game length.\n"
                  if stats.get("basis") == "drawn" else ""))
    print(key
          + f"  A verdict needs {stats['min_split']} games each way"
          + (f" and must stand out among the {stats['compared']} cards compared\n"
             f"  (Benjamini-Hochberg, {100 * stats['fdr']:.0f}% false discoveries)" if stats.get("compared") else "")
          + ".\n"
          "  A land gets no verdict: the games without a copy of one were mostly games short of lands, or of\n"
          "  its colour, so they say how those games went, not what the land did."
          + ("\n  A land's win rates and difference are when drawn and when not, as on the page." if early else ""))
    for c in stats["commander"]:
        turn = "-" if c["avg_first_turn"] is None else f"{c['avg_first_turn']:.1f}"
        print(f"  commander {c['name']}: cast in {_pct(c['cast_share'], 0)} of games ({c['casts']} casts), first on "
              f"turn {turn}; won when cast {_range(c['wr_cast'])}, not cast {_range(c['wr_not_cast'])}; "
              f"{_diff(c, 'cast', stats.get('compared', 0))}")
    width = max([len(r["name"]) for r in stats["rows"]] + [4])
    for land in (False, True):
        rows = [r for r in stats["rows"] if bool(r["land"]) == land]
        if not rows:
            continue
        print("  lands:" if land else "  spells:")
        # A land is never judged: its rates and cardstats' diff are the drawn ones on either basis.
        on_t3 = early and not land
        print(f"  {'card':<{width}}  qty  drawn  {'by t3  ' if early else ''}{'played' if land else '  cast'}  stuck  "
              f"turn  {'won by t3 / not' if on_t3 else 'won drawn / not':<25} difference")
        for r in rows:
            turn = "-" if r["avg_turn"] is None else f"{r['avg_turn']:.1f}"
            yes, no = (r["wr_early"], r["wr_not_early"]) if on_t3 else (r["wr_drawn"], r["wr_not"])
            won = f"{_range(yes)} / {_range(no)}"
            by_t3 = f"{_pct(r['early_share'], 0):>5}  " if early else ""
            print(f"  {r['name']:<{width}}  {r['qty']:>3}  {_pct(r['drawn_share'], 0):>5}  {by_t3}"
                  f"{_pct(r['cast_share'], 0):>6}  {_pct(r['stuck_share'], 0):>5}  {turn:>4}  {won:<25} "
                  f"{_diff(r, EARLY if on_t3 else 'drawn', stats.get('compared', 0))}")
    other = [r for r in stats["rows"] if r.get("other_casts")]
    if other:
        print("  also cast from anywhere but the hand (the graveyard, exile, the library...): "
              + ", ".join(f"{r['name']} {r['other_casts']:,} times" for r in other))


# ============================================================ slots

def _print_slots(found):
    """slots.status() as lines: how many slots are in use, and who by."""
    held = [row for row in found["slots"] if row["held"]]
    print(f"Forge processes on this PC: {len(held)} of {found['budget']} slots in use ({found['folder']})")
    if found.get("limit") is not None and found["limit"] < found["budget"]:
        print(f"  limited to {found['limit']} at once for now (Deck Lab's footer: Forge workers)")
    for row in held:
        if row["pid"] is None:
            print(f"  slot {row['id']}: in use (who by can't be read)")
            continue
        parts = [f"process {row['pid']}", row["what"], row["since"] and f"since {row['since']}", row["checkout"]]
        print(f"  slot {row['id']}: " + ", ".join(part for part in parts if part))


def _setup_lines(found=None):
    """status's and list's lines about wave 3's pilots and overrides (sim-wave3-contract.md
    section 5.4): the card-script overrides in Forge's user folder (and those that don't fit
    this Forge), and each list whose AI pilot isn't Forge's Default profile. The contract calls
    this E3's _engine_lines; wave 2's _engine_lines (play's lines) keeps that name. found:
    status()'s answer, when the caller has it."""
    found = shared.status() if found is None else found
    lines = []
    shown = found.get("overrides") or {}
    deployed = shown.get("deployed") or []
    lines.append(f"card-script overrides: {', '.join(deployed)} (hash {str(shown.get('hash'))[:12]})"
                 if deployed else "card-script overrides: none")
    for card in shown.get("stale") or []:
        lines.append(f"! Deck Lab's override for {card} doesn't fit this Forge version yet, so it isn't used.")
    data = shared.pilots.load()
    if not shared.pilots.is_default(data["default"]):
        lines.append(f"pilot of every list: {shared.pilots.words(data['default'])}")
    for name, pilot in sorted(data["lists"].items()):
        if not shared.pilots.is_default(pilot):
            lines.append(f"pilot of {name}: {shared.pilots.words(pilot)}")
    if data["problems"]:
        lines.append(f"! decklab/simulation.json has {len(data['problems'])} bad entr"
                     f"{'y' if len(data['problems']) == 1 else 'ies'} (python -m decklab.lib.forge pilots --check)")
    return lines


def _pool_words(state):
    """A pool's status() in a few words: its workers and what's queued."""
    workers = len(state["workers"])
    if not workers and not state["queued_games"]:
        return f"no workers up (they start with the next run; idle ones quit after {state['idle_s']} s)"
    parts = [f"{workers} of {state['limit']} workers ({state['busy']} playing, {state['idle']} idle, "
             f"{state['starting']} starting)"]
    if state["queued_games"]:
        runs = len(state["runs"])
        parts.append(f"{state['queued_games']:,} games queued for {runs} matchup{'s' if runs != 1 else ''}")
    return "; ".join(parts)


def _pool_line():
    """status's line about the running server's warm pool (pool.services())."""
    found = shared.pool.services()
    if not found:
        return "no Deck Lab server is running, so runs from here play in pools of their own"
    state = shared.pool.service_status(found[0])
    if state is None:
        return f"the server (process {found[0]['pid']}) didn't answer"
    return f"the server's (process {found[0]['pid']}): {_pool_words(state)}"



# What a look's decision means, for play --until's lines ({leader}: the deck ahead).
LOOK_WORDS = {"ahead": "{leader} is clearly ahead", "slightly_ahead": "{leader} is slightly ahead (by under 5 points)",
              "about_even": "the decks are about even (within 5 points of win rate)",
              "not_settled": "no clear leader", "not_settled_stopped": "not settled: stopped between checks"}


def _look_line(look, next_look=None, leader=""):
    """One look of an adaptive run in words: "Look at 800 games: z = 2.41 < 3.00, going on to
    1,600" (leader: the deck ahead, for a look that decided it)."""
    z, bound = look.get("z"), look.get("bound")
    stopped = " (stopped between checks)" if look.get("stopped") else ""
    head = f"Look at {look['games']:,} games{stopped}: "
    if z is None or bound is None:
        test = "z can't be worked out yet (no decided games on the play or on the draw)"
    else:
        test = f"z = {abs(z):.2f} {'<' if abs(z) < bound else '>='} {bound:.2f}"
    if look.get("decision") == "continue":
        return head + test + (f", going on to {next_look:,}" if next_look else "")
    return head + test + ": " + LOOK_WORDS.get(look.get("decision"), str(look.get("decision"))).format(leader=leader)


def _until_words(until, most):
    goal = ("the win rate is known to within ±3 points" if until == "assess"
            else "one deck is clearly ahead, or they're about even")
    return f"Playing until {goal} (at most {most:,} games)"


def _nothing_played_words(mode, most, v, looked_only):
    """Why an adaptive run played no game (v: view()'s, from A's point of view)."""
    n = v["games"]
    if mode == "ahead":
        if looked_only:
            return (f"No new games: the result's {n:,} games are already at a check, and that look "
                    f"decided.")
        return f"Nothing to play: the result already has {n:,} games, past every check, so the plain numbers stand."
    w = v.get("winrate") or {}
    if w.get("value") is not None and w.get("low") is not None and w.get("high") is not None:
        width = max(w["value"] - w["low"], w["high"] - w["value"])
        if width <= 0.03 + 1e-9:
            return (f"Nothing to play: with {n:,} games, the win rate is already known to within "
                    f"±{100 * width:.1f} points.")
    return (f"Nothing to play: the result already has as many games as this run would play "
            f"({n:,}, at most {most:,}), so the plain numbers stand.")


def _print_play(a, b, result, v):
    """play's lines for a finished run: the numbers from a's point of view (v, view()'s)."""
    w = v["winrate"]
    print(f"{a['title']} won {_pct(w['value'])} ({_pct(w['low'])}-{_pct(w['high'])}, "
          f"{'play/draw balanced' if w['balanced'] else 'raw'}) of {v['games']} games against {b['title']}")
    print(f"  wins {v['wins'][0]}-{v['wins'][1]}, draws {v['draws']}, timeouts {v['timeouts']}, errors {v['errors']}; "
          f"raw {_pct(v['raw']['value'])}; on the play {_pct(v['on_play']['value'])} ({v['on_play']['games']}), "
          f"on the draw {_pct(v['on_draw']['value'])} ({v['on_draw']['games']})")
    print(f"  {_starter_words(v['starter'])}")
    if not v["not_meaningful"]:
        print(f"  lead: {_lead_words(v['lead'], (a['title'], b['title']))}")
    run_ = result["runs"][-1]
    rate = f"{run_['played'] / run_['wall_s'] * 60:.0f}" if run_["wall_s"] else "-"
    if run_["startup_s"] is not None:
        start = f"slowest start-up {run_['startup_s']} s"
    else:           # (one-shot processes, none of which got as far as its header line)
        start = "cold processes" if run_.get("fallback") else "warm workers"
    where = {"server": ", in the server's pool", "remote": ", in the server's pool",
             "local": ", in a pool of its own"}.get(run_.get("pool"), "")
    failed = f"{run_['failed']} failed {'chunks' if run_.get('pool') else 'batches'}"
    print(f"  this run: {run_['played']} of {run_['asked']} games in {run_['wall_s']} s "
          f"({rate} a minute), {run_['workers']} workers{where}, "
          f"{start}, {failed}; AI timeouts {v['ai_timeouts']}")
    if run_.get("fallback"):
        print(f"  ! {run_['fallback']}")
    if v["not_meaningful"]:
        print("  ! not meaningful: the AI never casts a commander")
    summary = v.get("adaptive_last")
    if summary is not None:
        from . import adaptive          # it comes after this part
        p = shared._perspective(result, a["card_sha"])
        sentence = adaptive.words(summary, (a["title"], b["title"]) if p == 0 else (b["title"], a["title"]))
        if sentence:
            print(f"  {sentence}")
        last = (summary.get("looks") or [None])[-1]
        if last and last.get("z") is not None and last.get("bound") is not None:
            print(f"  (z = {abs(last['z']):.2f}; needed {last['bound']:.2f})")
    for line in _trust_lines(result, v, (a["title"], b["title"]), a["card_sha"]) + _engine_lines(result, v, (a, b)):
        print(f"  ! {line}")
    print(f"  key {result['key']}")


# What the page says of a deck Forge's AI plays with its auto-profile on (matchups.js AUTO_PROFILE_WORDS),
# and why Forge does that. Forge's rule (PlayerControllerAi) is Deck.getAverageCMC() > 3, and that average
# counts each different nonland card once (its mana value, not its copies) and rounds down, so it takes an
# average of 4 or more. (Its other reason, "Control" in the deck's name, can't apply: Deck Lab names decks
# by their card_sha.)
AUTO_PROFILE_WORDS = "Forge's AI plays this deck as a slower, non-aggro deck in every game"
AUTO_PROFILE_WHY = ("Forge's auto-profile, for a deck whose nonland cards average 4 mana or more, counting each "
                    "different card once and rounding down")


def _engine_lines(result, v, entries):
    """play's lines about the engine the games were played with (more "!" lines after the
    trust lines; entries: (a, b)): why the games were played with plain Forge and are kept
    apart (v["engine"]'s words, and the card log's problem), and each deck Forge's AI plays as
    a slower, non-aggro deck in every game (the side's "auto_profile": AUTO_PROFILE_WHY, with
    Forge's average for it)."""
    lines = []
    found = v.get("engine") or {}
    if found.get("words"):
        problem = (result.get("runs") or [{}])[-1].get("card_log_problem")
        lines.append(found["words"] + (f" {problem}" if found.get("kind") == shared.engine.KIND_PLAIN and problem else ""))
    said = set()
    for e in entries:
        side = next((s for s in result["sides"] if s["card_sha"] == e["card_sha"]), {})
        profile = side.get("auto_profile")
        if isinstance(profile, dict) and profile.get("flag") is True and e["card_sha"] not in said:
            said.add(e["card_sha"])
            cmc = profile.get("avg_cmc")
            average = "" if cmc is None else f"; Forge's average for it is {cmc}"
            lines.append(f"{AUTO_PROFILE_WORDS.replace('this deck', e['title'])} ({AUTO_PROFILE_WHY}{average}).")
    return lines


def _engine_mark(found):
    """A saved result's engine (views._engine_view) as a mark for list: "" for today's
    card-log engine."""
    if not found:
        return ""
    if found.get("kind") == shared.engine.KIND_V1:
        return "  [earlier engine: v1]"
    if found.get("current") is False:
        return f"  [earlier engine{': plain Forge' if found.get('kind') == shared.engine.KIND_PLAIN else ''}]"
    if found.get("kind") == shared.engine.KIND_PLAIN:
        return "  [plain Forge]"
    return ""
