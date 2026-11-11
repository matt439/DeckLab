"""Explicit CLI controls: isolated unchanged paired arms and independent size changes.

Nothing here is enumerated as a normal matchup, rating, field or per-card result.
No control starts merely by viewing it. Checkpointed arms are reused only by exact identity.
"""
import contextlib
import copy
import hashlib
import json
from pathlib import Path

from . import common, engine, lifecycle, lists, pilots, pool as pools, runner, saved, seqstats, variants
from .common import ForgeError

VERSION = 1
UNPAIRED_MARGIN = 0.05       # separate declared policy, not a measured engine noise floor
MAX_GAMES = 100_000
MAX_CARDS = 1000            # bound the CLI experiment; Forge's Constructed minimum is 60
NOISE_LIMIT = 1024 * 1024


def _folder(results_dir, kind):
    return common._results_dir(results_dir) / "experiments" / kind


def noise_receipts(folder, pairs, outputs, eng, *, same_install, seed, switches, game_patches):
    """Portable same-install repeatability receipts, without paths or list contents."""
    if not same_install or not game_patches:
        return []
    from . import cli_checks
    result = []
    for (fmt, seated, _, _, _), (a, b) in zip(pairs, outputs):
        entries = [lists.entry_from_dck(Path(folder) / (name if name.endswith(".dck") else name + ".dck")) for name in seated]
        for entry in entries:
            entry["pilot"] = {"profile": pilots.DEFAULT_PROFILE, "switches": sorted(switches)}
        first, second = cli_checks._outcomes(a), cli_checks._outcomes(b)
        if not first or len(first) != len(second):
            continue
        result.append({"v": VERSION, "format": fmt, "engine": engine.result_fields(eng),
                       "lists": sorted(entry["card_sha"] for entry in entries), "matchup": engine.key(*entries, eng),
                       "pilot": {"profile": pilots.DEFAULT_PROFILE, "switches": sorted(switches)},
                       "seed": seed, "games": len(first),
                       "different_winners": sum(x[:2] != y[:2] for x, y in zip(first, second)),
                       "different_outcomes": sum(x != y for x, y in zip(first, second))})
    return result


def _noise(path, base, opponents, eng):
    if path is None:
        return {}
    try:
        source = Path(path)
        with source.open("rb") as stream:
            content = stream.read(NOISE_LIMIT + 1)
        if len(content) > NOISE_LIMIT:
            raise ValueError
        report = json.loads(content)
        if not isinstance(report, dict):
            raise ValueError
        receipts = report["noise_floors"]
        if report.get("same_install") is not True or report.get("same_key") is not True or not isinstance(receipts, list):
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("The engine-check noise receipt is missing, too large or invalid; use a same-install engine-check JSON report.") from None
    answer = {}
    for opponent in opponents:
        wanted = sorted([base["card_sha"], opponent["card_sha"]])
        for item in receipts:
            if not isinstance(item, dict) or item.get("v") != VERSION or item.get("engine") != engine.result_fields(eng) or item.get("lists") != wanted or item.get("matchup") != engine.key(base, opponent, eng):
                continue
            pilot = item.get("pilot")
            if any((entry.get("pilot") or pilots.default_pilot()) != pilot for entry in (base, opponent)):
                continue
            n, different, outcomes = (item.get(key) for key in ("games", "different_winners", "different_outcomes"))
            if type(n) is int and n > 0 and type(different) is int and type(outcomes) is int and 0 <= different <= outcomes <= n:
                answer[opponent["card_sha"]] = {"games": n, "different_winners": different,
                                               "different_outcomes": outcomes,
                                               "winner_disagreement": different / n}
    return answer


@lifecycle.writing("base_entry", "against")
def run_placebo(base_entry, against, mode, *, results_dir=None, noise_floor=None, **options):
    """Run the actual paired coordinator with identical cards, always below experiments/."""
    if options.get("extend") is not None:
        raise ValueError("Placebo controls use a fresh explicit game count; --more is for ordinary paired tests.")
    mode = variants._mode_value(mode)
    if mode == "ahead":
        raise ValueError("A placebo needs --games N or --quick; it does not stop adaptively on a difference.")
    eng = engine.today()
    opponents = variants._opponent_entries(base_entry, against, options.get("opponents"), options.get("field_options"))
    floors = _noise(noise_floor, base_entry, opponents, eng)
    folder = _folder(results_dir, "placebo")
    summary = variants._claimed_test(base_entry, base_entry["cards"], against, mode, results_dir=folder,
                                     _placebo=True, **options)
    found = variants.view(summary["test"], folder) or {"test": summary}
    found["kind"] = "placebo"
    found["words"] = "Unchanged-list control: observed paired differences and finite ranges follow; this does not judge a card change."
    found["verdict"] = "control_only"
    found["test"] = copy.deepcopy(found["test"])
    found["test"].update(outcome="control_only", decision="control_only")
    for look in found["test"].get("looks") or []:
        look["decision"] = "control_only"
    found["noise_floor"] = floors
    found["control_note"] = ("Unchanged-list paired control, saved only in experiments. Compare the observed difference with this pair's same-install engine-check winner/outcome disagreements. "
                             "Zero disagreements in a finite check are an observed result, never proof of exact zero noise or a validated decision threshold. A missing or mismatched receipt means the noise floor is unknown; no equality is claimed.")
    # Keep the interpreted receipt with the control, never alongside normal paired summaries.
    common._write_atomic(folder / "controls" / (summary["test"] + ".json"), json.dumps(found, ensure_ascii=False))
    return found


def size_entry(base, cards):
    if not isinstance(cards, dict) or not set(cards) <= {"Commander", "Main"}:
        raise ValueError("A size change needs only Commander and Main card sections.")
    for rows in cards.values():
        if (not isinstance(rows, (list, tuple)) or len(rows) > MAX_CARDS
                or any(not isinstance(row, (list, tuple)) or len(row) != 2 or type(row[0]) is not int
                       or not 1 <= row[0] <= MAX_CARDS or not isinstance(row[1], str)
                       or not row[1].strip() or len(row[1]) > 300 or any(ord(char) < 32 for char in row[1]) for row in rows)):
            raise ValueError(f"The changed list needs positive whole card quantities and names, limited to {MAX_CARDS} cards.")
    if variants._canonical_sections(base["cards"], base["kind"])["Commander"] != variants._canonical_sections(cards, base["kind"])["Commander"]:
        raise ValueError("A size-changing test changes Main only; keep the commander section unchanged.")
    text, sha, count = lists._list_text(cards, base["kind"])
    if count == base["card_count"]:
        raise ValueError("A same-size change uses the ordinary paired test; omit --size-change.")
    if base["kind"] == "commander" and count != 100:
        raise ValueError("Forge Commander needs exactly 100 cards including its commander; this size change cannot play.")
    if base["kind"] != "commander" and min(count, base["card_count"]) < 60:
        raise ValueError("Forge Constructed needs at least 60 cards; this size change cannot play.")
    if count > MAX_CARDS:
        raise ValueError(f"A CLI size-change experiment is limited to {MAX_CARDS} cards.")
    return {**copy.deepcopy(base), "id": "unpaired:" + base["id"], "source": None,
            "title": base["title"] + " (size change)", "cards": copy.deepcopy(cards),
            "card_sha": sha, "card_count": count, "dck": lists._dck(text, sha)}


def _engine_same(result, eng, entry, opponent):
    if not isinstance(result, dict) or result.get("engine") != engine.result_fields(eng, [entry, opponent])["engine"]:
        return False
    expected = {engine.entry_side_id(value, eng=eng) for value in (entry, opponent)}
    return {side.get("engine_id") for side in result.get("sides") or []} == expected


def _margin():
    try:
        value = common._settings().get("forge_unpaired_margin", UNPAIRED_MARGIN)
    except Exception:
        value = UNPAIRED_MARGIN
    return float(value) if type(value) in (int, float) and 0 < value < .5 else UNPAIRED_MARGIN


def _identity(entry):
    return {key: copy.deepcopy(entry.get(key)) for key in ("id", "version", "card_sha", "pilot", "dck")}


@lifecycle.writing("base", "against", "opponents")
def run_unpaired(base, cards, against, games, *, by, results_dir=None, pool=None, local=False,
                 progress=None, opponents=None, field_options=None, log_dir=None, log_every=1):
    """Fixed-count, independent seeds per arm; checkpointed in its own kind and directory."""
    if type(games) is not int or not 1 <= games <= MAX_GAMES:
        raise ValueError(f"A size-change comparison needs --games N, from 1 to {MAX_GAMES}.")
    variant = size_entry(base, cards)
    eng = engine.today()
    if eng.get("kind") != engine.KIND_DECKLAB or eng.get("complete") is not True:
        raise ForgeError(runner.NEEDS_V2)
    chosen = variants._opponent_entries(base, against, opponents, field_options)
    if any(opponent.get("kind") != base["kind"] for opponent in chosen):
        raise ForgeError(common.MIXED_KINDS)
    margin = _margin()
    tid = engine._sha({"v": VERSION, "kind": "unpaired", "base": _identity(base), "variant": _identity(variant),
                       "opponents": [_identity(opponent) for opponent in chosen], "games": games,
                       "engine": engine.result_fields(eng), "margin": margin,
                       "keys": [[engine.key(entry, opponent, eng) for entry in (base, variant)] for opponent in chosen]})
    folder = _folder(results_dir, "unpaired") / tid
    summary = {"v": VERSION, "kind": "unpaired", "test": tid, "games_per_arm": games,
               "base": {"id": base["id"], "card_count": base["card_count"]},
               "variant": {"card_count": variant["card_count"], "card_sha": variant["card_sha"]},
               "engine": engine.result_fields(eng), "margin": margin, "opponents": [], "created": common._now(),
               "note": "Not paired: independent samples with a fixed final look and a separate equivalence margin. The range is wide; many more games are needed than for a paired swap. These games never enter normal matchups, field, Rankings, ratings or per-card figures."}
    lock = runner._claim(folder, "summary")
    try:
        with pools.session(local=local) if pool is None else contextlib.nullcontext(pool) as session:
            for opponent in chosen:
                arms = []
                for label, entry in (("base", base), ("variant", variant)):
                    if engine.key(entry, opponent, engine.today()) != engine.key(entry, opponent, eng):
                        raise ForgeError(variants.ENGINE_CHANGED)
                    key = engine._sha({"unpaired": tid, "opponent": _identity(opponent), "arm": label})
                    prior = saved.load(key, folder)
                    have = variants._games(prior)
                    if prior is not None and (prior.get("kind") != "unpaired" or not _engine_same(prior, eng, entry, opponent)):
                        raise ForgeError(variants.ENGINE_CHANGED)
                    if len(have) < games:
                        # Independent streams even if the lists happen to have identical content.
                        stream = hashlib.sha256((tid + opponent["card_sha"] + label).encode()).hexdigest()[:16]
                        kw = {"by": by, "results_dir": folder, "pool": session, "local": local, "exact": True,
                              "seeds": {"base": 1, "stream": stream, "flip": 0}, "key": key, "kind": "unpaired",
                              "extra": {"unpaired": {"test": tid, "arm": label}}, "progress": progress}
                        if log_dir is not None:
                            kw.update(log_dir=log_dir, log_every=log_every)
                        prior = runner.run(entry, opponent, games - len(have), **kw)
                    if not _engine_same(prior, eng, entry, opponent):
                        raise ForgeError(variants.ENGINE_CHANGED)
                    side = variants._variant_index(entry, opponent)
                    arms.append((variants._games(prior)[:games], side, key))
                diff = seqstats.unpaired_diff(arms[0][0], arms[1][0], arms[0][1], arms[1][1])
                summary["opponents"].append({"id": opponent["id"], "title": opponent.get("title"),
                                              "base_key": arms[0][2], "variant_key": arms[1][2], "difference": diff,
                                              "verdict": seqstats.paired_verdict(diff["low"], diff["high"], margin)})
                common._write_atomic(folder / "summary.json", json.dumps(summary, ensure_ascii=False))
    finally:
        runner._release(lock, folder / "summary.lock")
    return summary
