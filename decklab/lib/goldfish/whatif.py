"""Read-only one-basic trials. Every option replays the same seed/settings as its baseline."""
import json
import re
from dataclasses import replace
from pathlib import Path

from decklab.lib import cards, decks, stats
from . import runs
from .common import TAPPED

MAX_TRIAL_GAMES = 20_000
THRESHOLD = .01
BASICS = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest", "C": "Wastes"}


def choices(sections, kind):
    model, _ = runs.compile_deck(sections, kind)
    colours = set()
    source = sections.get("Commander", []) if kind == "commander" else sections.get("Deck", [])
    for line in source:
        card = cards.card(line.name)
        if card and (kind == "commander" or not stats.is_land(card)):
            colours.update(card.get("color_identity") or [])
    colours = [colour for colour in "WUBRG" if colour in colours]
    names = sorted({name for line in sections.get("Deck", []) if (name := cards.resolve(line.name))})
    tapped = sorted({card["name"] for card in model["cards"] if card["kind"] == "land" and card["land"]
                     and card["land"][3][0] == TAPPED and not card["land"][7] and not card["land"][8]})
    return {"cuts": names, "colours": colours or ["C"], "tapped_cut": next(iter(tapped), None),
            "max_games": MAX_TRIAL_GAMES, "threshold": THRESHOLD}


def _replace(sections, cut, basic):
    answer = {name: list(lines) for name, lines in sections.items()}
    for index, line in enumerate(answer.get("Deck", [])):
        if (cards.resolve(line.name) or line.name) == cut:
            if line.quantity > 1:
                answer["Deck"][index] = replace(line, quantity=line.quantity - 1)
            else:
                del answer["Deck"][index]
            answer["Deck"].append(decks.DeckLine(1, basic))
            return answer
    raise ValueError("Choose one card from this list's Deck section to replace")


def prepare(sections, kind, cut, baseline):
    options = choices(sections, kind)
    cut = cards.resolve(cut) if isinstance(cut, str) else None
    if cut not in options["cuts"]:
        raise ValueError("Choose one card from this list's Deck section to replace")
    settings = {"games": min(baseline["games"], MAX_TRIAL_GAMES), "turns": baseline["turns"],
                "seed": baseline["seed"], "mulligans": baseline["mulligans"]}
    runs._check_settings(settings["games"], settings["turns"])
    variants = []
    for name in dict.fromkeys([cut, options["tapped_cut"]]):
        if name is None:
            continue
        for colour in options["colours"]:
            basic = BASICS[colour]
            if basic == name:
                continue
            card = cards.card(basic)
            if card is None or not stats.is_land(card) or "Basic" not in stats.type_words(card["type_line"]):
                raise ValueError("The card data for a required basic land isn't available")
            variants.append({"id": str(len(variants)), "cut": name, "add": basic,
                             "tapped_land": name == options["tapped_cut"], "sections": _replace(sections, name, basic)})
    if not variants:
        raise ValueError("There is no different basic-land change to compare for that cut")
    key = runs._digest(["land-trials-v1", runs.cache_key(sections, kind, **settings), cut,
                        [[row["cut"], row["add"]] for row in variants], THRESHOLD])[:40]
    return key, settings, variants


def _metrics(result):
    return {setup: {"stuck": row["stuck"]["games"], "colour_screw": row["colours"]["screw_turns"],
                    "colour_waste": row["colours"]["screw_wasted_turns"], "flood": row["flood"]["turns"],
                    "mana_used": row["mana_used"]["share"]} for setup, row in result["results"].items()}


def _deltas(base, changed):
    return {setup: {key: round(value - base[setup][key], 6) if value is not None and base[setup][key] is not None else None
                    for key, value in metrics.items()} for setup, metrics in changed.items()}


def _best(rows, setup):
    eligible = []
    for row in rows:
        delta = row["deltas"][setup]
        if any(delta[key] is None for key in ("stuck", "colour_screw", "flood")):
            continue       # A short replay cannot establish the missing regression checks.
        risks = [delta[key] for key in ("stuck", "colour_screw", "flood") if delta[key] is not None]
        gain = max((-delta[key] for key in ("stuck", "colour_screw") if delta[key] is not None), default=0)
        if gain >= THRESHOLD and all(value <= THRESHOLD for value in risks):
            eligible.append((gain, -sum(risks), row["id"]))
    return max(eligible)[2] if eligible else None


def saved(key, cache_dir=None):
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{40}", key):
        raise ValueError("Bad land-trial cache key")
    folder = Path(cache_dir) if cache_dir is not None else runs.CACHE_DIR
    try:
        value = json.loads((folder / "land-trials" / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(value, dict) and value.get("cache_key") == key and value.get("version") == runs.GOLDFISH_VERSION and value.get("type") == "land-trials":
        return {**value, "cached": True, "saved": True}
    return None


def run(sections, kind, cut, baseline, progress=None, workers=None, cache_dir=None):
    key, settings, variants = prepare(sections, kind, cut, baseline)
    cached = saved(key, cache_dir)
    if cached is not None:
        return cached
    count, total_done = len(variants) + 1, 0
    total = settings["games"] * len(baseline["setups"]) * count

    def replay(changed):
        nonlocal total_done
        def report(done, _total):
            if progress:
                progress(total_done + done, total)
        result = runs.get_or_simulate(changed, kind, **settings, workers=workers, progress=report, cache_dir=cache_dir)
        total_done += settings["games"] * len(baseline["setups"])
        if progress:
            progress(total_done, total)
        return result

    original = _metrics(replay(sections))
    rows = []
    for variant in variants:
        metrics = _metrics(replay(variant["sections"]))
        rows.append({**{name: value for name, value in variant.items() if name != "sections"},
                     "metrics": metrics, "deltas": _deltas(original, metrics)})
    value = {"type": "land-trials", "version": runs.GOLDFISH_VERSION, "cache_key": key, "settings": settings,
             "requested_cut": cut, "baseline": original, "variants": rows,
             "best": {setup: _best(rows, setup) for setup in original}, "threshold": THRESHOLD,
             "note": "A mana-only simulation estimate. Each change replaces one copy and replays the same seed, settings and game count. Changed lists can make different draw and mulligan decisions. A best change needs at least 1 percentage point less stuck or colour screw, with no more than 1 point worse stuck, colour screw or flood. All three measures must be available; short runs can leave a measure unknown. This threshold is a screen, not a significance test or play advice.",
             "warnings": [], "cached": False, "saved": True}
    folder = (Path(cache_dir) if cache_dir is not None else runs.CACHE_DIR) / "land-trials"
    try:
        runs._save(folder, folder / f"{key}.json", value)
    except OSError:
        value["saved"] = False
        value["warnings"].append("These land trials couldn't be saved on the PC; the numbers can still be read here.")
    return value
