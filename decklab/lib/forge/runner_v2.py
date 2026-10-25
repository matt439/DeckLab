"""Numbered-game planning, warm-pool event collection and v2 result records.

runner.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import json
import queue
import time
from copy import deepcopy
from . import cardlog, checkpoints, common, engine, seeds

from . import runner as runtime


def _run_v2(setup, key, eng, fmt, entry_a, entry_b, ordered, games, by, progress, folder, workers, batch,
            seed_base, a_first, save, index, existing, pool, local, exact, hooks=None):
    """run() of the v2 engine, once the matchup is claimed: plan the game numbers
    (lists.plan_v2, or _plan_numbers for run(numbers=...)), play them where pool.place says
    (_play_v2), save one merged batch record (_record_v2), and close a pool of the run's own
    after the save. The job carries each stored side's pilot (the pool gives each seat the
    pilot of the side seeds.deck1_side puts there) and the log tee's folder."""
    hooks = hooks or {"numbers": None, "seeds": None, "kind": None, "extra": {}, "log": None}
    if save:
        checkpoints.recover(existing, eng, ordered)
    if hooks["numbers"] is not None:
        planned = runtime._plan_numbers(hooks["numbers"], existing, hooks["kind"])
    else:
        planned = runtime.plan_v2(games, existing, batch=batch, exact=exact)
    if existing is None:
        if hooks["seeds"] is not None:
            base, stream, flip = hooks["seeds"]["base"], hooks["seeds"]["stream"], hooks["seeds"]["flip"]
        else:
            env_base = runtime._env_seed_base() if seed_base is None else None
            base = int(seed_base) if seed_base is not None else env_base if env_base is not None else seeds.SEED_BASE
            stream = seeds.stream_hex(seeds.stream_of(ordered[0]["card_sha"], ordered[1]["card_sha"]))
            flip = int(bool(a_first) and ordered[0]["card_sha"] != entry_a["card_sha"])
    else:
        record = existing["seeds"]
        base, stream, flip = record["base"], record["stream"], record["flip"]
        if hooks["seeds"] is not None and hooks["seeds"] != {"base": base, "stream": stream, "flip": flip}:
            raise ValueError(f"The result's seeds are base {base}, stream {stream} and flip {flip}: a run of it "
                             f"can't ask for others.")
        if a_first and int(ordered[0]["card_sha"] != entry_a["card_sha"]) != flip:
            common._log(runtime.A_FIRST_IGNORED)
    sides = existing["sides"] if existing else [runtime._side(e) for e in ordered]
    names = [runtime._log_names([n for _, n in runtime._list_lines(e)], index) for e in ordered]
    # Each stored side's pilot as played (engine.played_pilot; stored side i always holds side
    # i's; a result of before wave 3, without one, plays its entry's).
    side_pilots = [engine.played_pilot(side if isinstance(side.get("pilot"), dict) else e, eng)
                   for side, e in zip(sides, ordered)]
    job = {"key": key, "setup": setup, "fmt": fmt, "dck": [runtime._dck_name(e) for e in ordered],
           "names": names, "base": base, "stream": stream, "flip": flip, "ranges": planned["ranges"],
           "batch": batch, "workers": workers, "low": by == "replay", "engine": eng, "pilots": side_pilots,
           "log": hooks["log"]}
    when = runtime._now()
    checkpoint = None
    if save:
        def build_checkpoint(record, fails, stats):
            return runtime._record_v2(
                setup, key, eng, fmt, entry_a, entry_b, ordered, deepcopy(existing), deepcopy(sides),
                planned, when, by, record, fails, common.Stopped(), stats,
                {"base": base, "stream": stream, "flip": flip}, hooks)
        checkpoint = checkpoints.Writer(folder / f"{key}.json", build_checkpoint)
        checkpoint.reserve()
    late = []           # a Ctrl+C once the games are over: raised after the save
    record, fails, stopped, stats = runtime._play_v2(setup, key, job, progress, late, pool, local,
                                                  checkpoint=checkpoint)
    placement = stats.pop("placement", None)
    saved_games = None
    try:
        with runtime._interrupts_held(note=lambda: late.append(True)):
            result = runtime._record_v2(setup, key, eng, fmt, entry_a, entry_b, ordered, existing, sides, planned, when,
                                by, record, fails, stopped, stats, {"base": base, "stream": stream, "flip": flip},
                                hooks)
            if save:
                path = folder / f"{key}.json"
                try:
                    common._write_atomic(path, json.dumps(result, ensure_ascii=False, separators=(",", ":")))
                    saved_games = result["runs"][-1]["played"]
                except OSError as e:
                    common._log(f"A matchup result couldn't be saved as {path}: {e}")
                    if stopped is None:
                        raise runtime.ForgeError(runtime.NOT_SAVED) from None
    finally:
        if placement is not None:
            placement.close(0 if stopped is not None else None)
        if stats.get("tidy"):
            runtime._tidy_user_dir(setup["user_dir"])
    if stopped is None and late:
        stopped = KeyboardInterrupt()
    if stopped is not None:
        try:
            stopped.saved_games = saved_games
        except (AttributeError, TypeError):
            pass
        raise stopped
    error = result["runs"][-1]["error"]
    if error:
        raise runtime.ForgeError(f"No games could be played: {error}.")
    return result


def _plan_numbers(numbers, existing, kind):
    """plan_v2's answer for run(numbers=...): {"first": the lowest, "end": the highest + 1,
    "ranges": the numbers as ranges cut at seat blocks and gaps (_blocks)}. ValueError for a
    number the result holds, and, for a matchup (kind None), one below its next_game: wave 2
    never plays a stopped run's unplayed numbers later; only paired and experiment results,
    whose games match another result's numbers, may fill those holes."""
    if existing is not None:
        held = {game["g"] for batch in existing.get("batches", []) for game in batch.get("games", [])}
        again = [g for g in numbers if g in held]
        if again:
            raise ValueError(f"The result already holds game {again[0]}" + (f" and {len(again) - 1} more of these numbers"
                                                                             if len(again) > 1 else "") + ".")
        next_game = int(existing.get("next_game") or 0)
        if kind is None and numbers[0] < next_game:
            raise ValueError(f"A matchup plays on from game {next_game}: its earlier numbers aren't played later.")
    return {"first": numbers[0], "end": numbers[-1] + 1, "ranges": runtime._blocks(numbers)}


def _blocks(numbers):
    """Sorted game numbers as [[start, end]] ranges, cut at every seat block (and at gaps)."""
    out = []
    for g in numbers:
        if out and out[-1][1] == g and seeds.block_of(g) == seeds.block_of(out[-1][0]):
            out[-1][1] = g + 1
        else:
            out.append([g, g + 1])
    return out


def _play_v2(setup, key, job, progress, late, pool, local, checkpoint=None):
    """Play job's game numbers where pool.place puts them, reading the events of its ticket
    (pool.Ticket): every game as it comes (progress after each, at most 4 a second as
    _play's, and at least once a second, so a Stop is noticed), each chunk's start and end.
    A stop (progress raising, Ctrl+C, or an error here) stops the ticket, which closes its
    chunks' readers at once, and the run keeps every game it was sent, without waiting for
    any worker. When the server's pool goes away ("lost"), the games not yet sent are played
    in a pool of the run's own. Returns (the merged batch record or None, failed ranges
    [{"first", "games", "error"}], the exception that stopped it or None, stats)."""
    from . import pool as pools          # pool.py comes after this part
    total = sum(b - a for a, b in job["ranges"])
    chunks = {}                 # (round, cid) -> {"first", "games", "kept": [(game, casts, lands, cards)], ...}
    fails = []
    wins, other, done = [0, 0], 0, 0
    playing = set()
    state = {"most": 0, "recycled": 0, "requeued": 0, "echo": None, "waiting": None, "fallback": None,
             "closed": False, "round": 0}
    began = time.monotonic()
    first_start = None
    last_call = 0.0
    stopped = None
    placement = pools.place(job, pool=pool, local=local)
    ticket, where = placement.ticket, placement.where       # where it started (a lost run ends locally)

    def counts():
        rate = eta = None
        elapsed = time.monotonic() - (first_start or began)
        if done and elapsed > 0 and first_start is not None:
            rate = done / elapsed * 60
            eta = round((total - done) / rate * 60) if rate else None
        return {"wins": list(wins), "other": other, "games_per_min": round(rate, 1) if rate else None,
                "eta_s": eta, "failed_batches": sum(1 for c in chunks.values() if (c["end"] or {}).get("failed")),
                "waiting": state["waiting"] if not playing else None, "fallback": state["fallback"]}

    def report(final=False):
        nonlocal last_call
        now = time.monotonic()
        if progress is not None and (final or now - last_call >= runtime.PROGRESS_GAP):
            last_call = now
            progress(done, total, counts())

    def count(game, sign):
        nonlocal done, other
        done += sign
        if game["w"] is None:
            other += sign
        else:
            wins[game["w"]] += sign

    def handle(event):
        """One ticket event; "done" or "lost" when the ticket is over."""
        nonlocal first_start
        kind, now = event[0], time.monotonic()
        name = (state["round"], event[1]) if len(event) > 1 else None
        if kind == "start":
            _, _, first, games, startup = event
            chunks[name] = {"first": first, "games": games, "kept": [], "end": None, "at": now, "startup_s": startup}
            playing.add(name)
            state["most"] = max(state["most"], len(playing))
            if first_start is None:
                first_start = now
        elif kind == "echo" and state["echo"] is None:
            state["echo"] = event[2]
        elif kind == "game" and name in chunks:
            chunks[name]["kept"].append(tuple(event[2:]))
            count(event[2], 1)
        elif kind == "end" and name in chunks:
            info = event[2]
            entry = chunks[name]
            playing.discard(name)
            entry["end"] = info
            if info.get("startup_s") is not None:       # a one-shot process's, known once it started
                entry["startup_s"] = info["startup_s"]
            if info.get("drop"):
                for kept in entry["kept"]:
                    count(kept[0], -1)
                entry["kept"] = []
            if info.get("failed"):
                fails.append(dict(info["failed"]))
            state["recycled"] += info.get("recycled") or 0
            state["requeued"] += info.get("requeued") or 0
        elif kind == "waiting":
            state["waiting"] = event[1]
        elif kind == "fallback":
            state["fallback"] = event[1]
        elif kind in ("done", "lost"):
            return kind
        return None

    def rest():
        """The game numbers not yet sent, nor failed: what a lost run plays locally."""
        sent = {kept[0]["g"] for c in chunks.values() for kept in c["kept"]}
        gone = [(f["first"], f["first"] + f["games"]) for f in fails]
        return runtime._blocks(g for a, b in job["ranges"] for g in range(a, b)
                       if g not in sent and not any(x <= g < y for x, y in gone))

    def snapshot(completed=False):
        # An end event can invalidate all earlier game events from its chunk.
        # Checkpoints never expose a chunk until that validation has finished.
        selected = {k: c for k, c in chunks.items() if not completed or c["end"] is not None}
        record, stats = _snapshot_v2(selected, state, placement, where, began, first_start,
                                     log_problems=not completed)
        return record, list(fails), stats

    try:
        report(final=True)
        while True:
            try:
                event = ticket.events.get(timeout=runtime.EVENT_POLL_S)
            except queue.Empty:
                event = None
            what = handle(event) if event is not None else None
            if what == "lost":
                common._log(pools.LOST)
                ranges = rest()
                playing.clear()
                state["round"] += 1
                if not ranges:
                    break
                ticket = placement.local(dict(job, ranges=ranges))
            elif what == "done":
                state["closed"] = event[1] == "closed"
                break
            if checkpoint is not None and event is not None and event[0] == "end":
                completed = sum(len(c["kept"]) for c in chunks.values() if c["end"] is not None)
                checkpoint.publish(completed, lambda: snapshot(completed=True))
            if event is None or event[0] in ("game", "end", "waiting", "fallback") \
                    or time.monotonic() - last_call >= runtime.HEARTBEAT:
                report()
        report(final=True)
    except BaseException as e:      # progress raised (Stop, the server stopping), Ctrl+C, or a bug
        stopped = e
        # Nothing interrupts this (a second Ctrl+C is only noted), so the games are saved.
        with runtime._interrupts_held(note=lambda: None):
            ticket.stop()
            while True:             # every game the ticket was sent is in its queue by now
                try:
                    event = ticket.events.get_nowait()
                except queue.Empty:
                    break
                if handle(event) == "done":
                    break
    with runtime._interrupts_held(note=lambda: late.append(True)):     # and so does run(), to the save
        record, fails, stats = snapshot()
    return record, fails, stopped, stats


def _snapshot_v2(chunks, state, placement, where, began, first_start, log_problems=True):
    """Merge selected chunks using the same accounting for progress and final saves."""
    now = time.monotonic()
    kept = [c for c in chunks.values() if c["kept"]]
    entries = sorted((k for c in kept for k in c["kept"]), key=lambda k: k[0]["g"])
    record = None
    if entries:
        casts, lands, cards = [{}, {}], [{}, {}], None
        for _, game_casts, game_lands, game_cards in entries:
            for side in (0, 1):
                for card, (n, g) in game_casts[side].items():
                    tally = casts[side].setdefault(card, [0, 0])
                    tally[0] += n
                    tally[1] += g
                for card, g in game_lands[side].items():
                    lands[side][card] = lands[side].get(card, 0) + g
            if game_cards is not None:
                cards = deepcopy(game_cards) if cards is None else cardlog.merge_record(cards, game_cards)
        record = {"first": entries[0][0]["g"], "games": [dict(k[0]) for k in entries], "casts": casts,
                  "lands": lands, "chunks": len(kept),
                  "wall_s": round(sum((c["end"] or {}).get("wall_s") or (now - c["at"]) for c in kept), 2)}
        if cards is not None:
            record["cards"] = cards
            if cards["bad"] and log_problems:
                problems = [p for c in kept for p in (c["end"] or {}).get("card_problems") or []]
                shown = problems[:runtime.CARD_PROBLEMS_LOGGED]
                reasons = "; ".join(f"game {n}: {why}" for n, why in shown)
                more = "; ..." if cards["bad"] > len(shown) else ""
                common._log(f"Games {record['first']}-{entries[-1][0]['g']}: the card log of {cards['bad']} of "
                            f"{len(entries)} games failed its checks ({reasons}{more}).")
    starts = [c["startup_s"] for c in chunks.values() if c["startup_s"] is not None]
    stats = {"wall_s": round(now - (first_start or now), 1),
             "startup_s": round(max(starts), 1) if starts else None,
             "waited_s": round((first_start or now) - began, 1), "most_running": state["most"],
             "echo": state["echo"] or [{}, {}], "chunks": len(chunks), "played_batches": len(kept),
             "partial": sum(1 for c in kept if len(c["kept"]) < c["games"]),
             "batch_games": max((c["games"] for c in chunks.values()), default=0),
             "recycled": state["recycled"], "requeued": state["requeued"], "pool": where,
             "xmx": placement.xmx, "fallback": state["fallback"], "closed": state["closed"],
             "tidy": placement.where != "remote", "placement": placement}
    return record, stats


def _record_v2(setup, key, eng, fmt, entry_a, entry_b, ordered, existing, sides, planned, when, by, record,
               fails, stopped, stats, seed, hooks=None):
    """The result with a v2 run's merged batch and run record added (wave 2's contract "Saved
    result, v2"). A new result also gets the engine's fields (engine.result_fields), its
    "seeds" (seed: {"base", "stream", "flip"}) and settings; each side, on every run, its own
    engine fields (engine.side_fields, with what the first chunk's DLENGINE line said of it).
    next_game is where the next run plans from: the end of this run's range, whatever it
    played (as v1 never reuses a seed). The run record's xmx is the Java heap its games were
    played with (the server's, when it played in the server's pool).
    Wave 3 (hooks: _hooks()'s): settings.ai is the sides' pilots' profiles, in side order; a new
    result of a kind (paired, experiment) says so ("kind", and a paired one's
    "paired_version"), with extra merged in; a run of numbers records them as "ranges"."""
    hooks = hooks or {"numbers": None, "kind": None, "extra": {}}
    result = existing
    if result is None:
        result = {
            "key": key, "format": fmt, "forge_version": setup["version"], "run_version": runtime.FORGE_RUN_VERSION,
            "settings": {"clock_s": setup["clock_s"], "ai": [runtime._pilot(side)["profile"] for side in sides],
                         "xmx": stats.get("xmx") or setup["xmx"]},
            "seeds": {"scheme": seeds.SCHEME, "base": seed["base"], "stream": seed["stream"],
                      "seat_block": seeds.SEAT_BLOCK, "flip": seed["flip"]},
            "next_game": planned["first"], "sides": sides, "runs": [], "batches": [], "failed": [], "created": when,
            **engine.result_fields(eng, ordered),
        }
        if hooks["kind"] is not None:
            result["kind"] = hooks["kind"]
        if hooks["kind"] == "paired":
            result["paired_version"] = runtime.PAIRED_VERSION
        result.update(deepcopy(hooks["extra"]))
    echo = stats.get("echo") or [{}, {}]
    for i, side in enumerate(result["sides"]):
        side.update(engine.side_fields(eng, side, echo[i]))
    if result["sides"][0]["card_sha"] == result["sides"][1]["card_sha"]:
        runtime._seen(result["sides"][0], ordered[0], when)
        runtime._seen(result["sides"][1], ordered[1], when)
    else:
        for e in (entry_a, entry_b):
            for side in result["sides"]:
                if side["card_sha"] == e["card_sha"]:
                    runtime._seen(side, e, when)
    ordinal = len(result["runs"])
    played = len(record["games"]) if record else 0
    numbers = [g["g"] for g in record["games"]] if record else []
    is_stop = isinstance(stopped, runtime.STOPS) or (stopped is None and bool(stats.get("closed")))
    error = None
    if stopped is not None and not isinstance(stopped, runtime.STOPS):
        error = f"The run stopped because of an error in Deck Lab ({type(stopped).__name__})."
    elif not played and fails and stopped is None:
        error = fails[0]["error"]
    run_record = {
        "when": when, "by": by, "a": entry_a["card_sha"],
        "asked": sum(b - a for a, b in planned["ranges"]), "played": played,
        "batches": stats["chunks"], "played_batches": stats["played_batches"], "partial": stats["partial"],
        "workers": stats["most_running"], "batch_games": stats["batch_games"],
        "seeds": [min(numbers), max(numbers)] if numbers else None,
        "wall_s": stats["wall_s"], "startup_s": stats["startup_s"],
        "waited_s": stats["waited_s"], "most_running": stats["most_running"],
        "stopped": is_stop, "stopped_by": getattr(stopped, "by", None) if is_stop else None,
        "failed": len(fails), "failure": fails[0]["error"] if fails else None, "error": error,
        "card_log": True, "pool": stats["pool"], "chunks": stats["chunks"], "recycled": stats["recycled"],
        "requeued": stats["requeued"], "games_from": planned["first"], "games_to": planned["end"],
        "engine": key, "xmx": stats.get("xmx") or setup["xmx"],
    }
    if stats.get("fallback"):
        run_record["fallback"] = stats["fallback"]
    if hooks["numbers"] is not None:
        run_record["ranges"] = [list(r) for r in planned["ranges"]]        # the numbers it was asked to play
    result["runs"].append(run_record)
    if record is not None:
        result["batches"] = sorted(result["batches"] + [dict(record, n=ordinal)], key=lambda b: (b["n"], b["first"]))
    result["failed"] = sorted(result["failed"] + [dict(f, n=ordinal) for f in fails],
                              key=lambda f: (f["n"], f["first"]))
    result["next_game"] = max(int(result.get("next_game") or 0), planned["end"])
    result["updated"] = runtime._now()
    return result
