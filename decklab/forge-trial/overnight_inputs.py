"""Input preparation for the combined-run legs: variants, ladders and experiment specs.

Functions that need the caller's settings receive its namespace explicitly, keeping
patches and caches local to each loaded overnight_legs module (including script runs).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def _override_decks(_runtime):
    """[(format, deck id, reference opponent)] for the override experiments: every list of the
    Constructed and Commander fields, each against its ladder reference (LADDER_REFERENCE), else
    Giada's against Finneas, else its format's OTHER_REFERENCE; the ladder decks only when the
    field can't be read."""
    try:
        from decklab.lib.forge import field
        found = []
        for fmt in ("Constructed", "Commander"):
            for entry in field.field_lists(fmt):
                deck = entry["id"]
                found.append((fmt, deck, _runtime['LADDER_REFERENCE'].get(deck) or _runtime['COMMANDER_REFERENCE'].get(deck)
                              or _runtime['OTHER_REFERENCE'][fmt]))
        return found
    except Exception:
        return [("Constructed", deck, reference) for deck, reference in _runtime['LADDER_REFERENCE'].items()]


def _main_cards(entry):
    """The main deck's (copies, name), one per name in list order: a name on two printing lines is
    summed, so taking a copy away or counting a name's copies sees all of them."""
    totals = {}
    for q, n in entry["cards"].get("Main", []):
        totals[n] = totals.get(n, 0) + q
    return [(q, n) for n, q in totals.items()]


def _is_basic(_runtime, name):
    return name in _runtime['BASICS']


def _card_rows(_runtime, deck_id, results_dir=None):
    """The rows of `cards <deck> --json` (each {"name", "land", "diff", ...}), read once; [] when there are none."""
    if deck_id not in _runtime['_CARD_ROWS']:
        argv = [sys.executable, "-m", "decklab.lib.forge", "cards", deck_id, "--json"]
        if results_dir:
            argv += ["--results-dir", str(results_dir)]
        try:
            done = subprocess.run(argv, cwd=str(_runtime['TREE']), capture_output=True, text=True, timeout=300)
            found = json.loads(done.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            found = None
        _runtime['_CARD_ROWS'][deck_id] = [r for r in (found or {}).get("rows") or [] if isinstance(r, dict)]
    return _runtime['_CARD_ROWS'][deck_id]


def _is_land(name):
    """Whether the card data's type line (the front face's) says Land; False when it can't tell."""
    try:
        from decklab.lib import cards
        found = cards.card(name)
    except Exception:
        return False
    return "Land" in ((found or {}).get("type_line") or "")


def _land_names(_runtime, entry, results_dir=None):
    """The deck's land names: the card stats' "land" flag, the card data's type line, and the basics."""
    names = {r["name"] for r in _runtime['_card_rows'](entry["id"], results_dir) if r.get("land")}
    return names | {n for _, n in _runtime['_main_cards'](entry) if _runtime['_is_basic'](n) or _runtime['_is_land'](n)}


def _row_score(row):
    """A card stats row's "won more when drawn" estimate: its "shrunk" best estimate, else its
    "diff"'s value ({"value", "low", "high"}); None when it has neither."""
    for value in (row.get("shrunk"), (row.get("diff") or {}).get("value") if isinstance(row.get("diff"), dict)
                  else row.get("diff")):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return None


def _card_scores(_runtime, deck_id, results_dir=None):
    """"Won more when drawn" per card name for deck_id's list, from its saved card stats (_row_score);
    {} when there are none (the order is then by copies, then name)."""
    return {r["name"]: _runtime['_row_score'](r) for r in _runtime['_card_rows'](deck_id, results_dir) if _runtime['_row_score'](r) is not None}


def _decklist(cards, commander=()):
    lines = []
    if commander:
        lines.append("Commander")
        lines += [f"{q} {n}" for q, n in commander]
        lines.append("")
    lines.append("Deck")
    lines += [f"{q} {n}" for q, n in cards if q > 0]
    return "\n".join(lines) + "\n"


def _sets(_runtime):
    """overrides/sets.json's sets ({name: {"status", "files": {file: {"card", ...}}}}), or {}."""
    path = _runtime['TREE'] / "decklab" / "lib" / "forge" / "overrides" / "sets.json"
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    sets = found.get("sets") if isinstance(found, dict) else None
    return sets if isinstance(sets, dict) else {}


def leg_prepare_inputs(_runtime, args):
    """$OUT/inputs: the M4 variants of Gruul Ramp, the ladders, and the experiment specs."""
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = {}
    # M4 variants of Gruul Ramp's target list (section 3)
    gruul = _runtime['_entry']("casual/gruul-ramp")
    lands = _runtime['_land_names'](gruul, args.results_dir)
    main = _runtime['_main_cards'](gruul)
    scores = _runtime['_card_scores']("casual/gruul-ramp", args.results_dir)
    spells = [(q, n) for q, n in main if n not in lands]
    multi = sorted([x for x in spells if x[0] >= 2], key=lambda x: (-scores.get(x[1], 0), -x[0], x[1]))
    if multi and len(spells) >= 2:
        took = multi[0][1]
        added = next(n for q, n in sorted(spells, key=lambda x: (-x[0], x[1])) if n != took)
        v1 = [(q - (n == took) + (n == added), n) for q, n in main]
        basic = max(((q, n) for q, n in main if _runtime['_is_basic'](n)), default=(0, "Forest"))[1]
        two = [n for q, n in sorted(spells, key=lambda x: (-x[0], x[1]))][:2]
        v2 = [(q - (1 if n in two else 0) + (2 if n == basic else 0), n) for q, n in main]
        (out / "variant-1.txt").write_text(_runtime['_decklist'](v1), encoding="utf-8")
        (out / "variant-2.txt").write_text(_runtime['_decklist'](v2), encoding="utf-8")
        made["variants"] = {"deck": "casual/gruul-ramp", "1": {"remove": [[1, took]], "add": [[1, added]]},
                            "2": {"remove": [[1, two[0]], [1, two[1]]], "add": [[2, basic]]}}
        (out / "variants.json").write_text(json.dumps(made["variants"], indent=1), encoding="utf-8")
    # ladders (section 3): the 6 key nonland copies, in pairs, replaced by lands in the basics' proportions
    ladders = {}
    (out / "ladders").mkdir(exist_ok=True)
    for deck, reference in _runtime['LADDER_REFERENCE'].items():
        try:
            entry = _runtime['_entry'](deck)
        except Exception:
            continue
        main = _runtime['_main_cards'](entry)
        lands = _runtime['_land_names'](entry, args.results_dir)
        scores = _runtime['_card_scores'](deck, args.results_dir)
        copies = []
        for q, n in sorted([x for x in main if x[1] not in lands], key=lambda x: (-scores.get(x[1], 0), -x[0], x[1])):
            copies += [n] * q
        key = copies[:6]
        basics = [(q, n) for q, n in main if _runtime['_is_basic'](n)] or [(1, "Forest")]
        total = sum(q for q, _ in basics)
        rungs = []
        for k in (2, 4, 6):
            if len(key) < k:
                break
            cards = dict((n, q) for q, n in main)
            for n in key[:k]:
                cards[n] -= 1
            shares = [(n, q / total * k) for q, n in basics]
            add = {n: int(s) for n, s in shares}
            for n, _ in sorted(shares, key=lambda x: -(x[1] - int(x[1])))[:k - sum(add.values())]:
                add[n] += 1
            for n, a in add.items():
                cards[n] = cards.get(n, 0) + a
            name = f"ladders/{deck.split('/')[-1]}-{k}.txt"
            (out / name).write_text(_runtime['_decklist']([(q, n) for n, q in cards.items()]), encoding="utf-8")
            rungs.append({"k": k, "file": name, "removed": key[:k]})
        if rungs:
            ladders[deck] = {"reference": reference, "rungs": rungs}
    (out / "ladders.json").write_text(json.dumps(ladders, indent=1), encoding="utf-8")
    # experiment specs (CONTRACT-W3.md section 12.1), one per question so each arm plays only its pairs
    specs = {}
    sets = _runtime['_sets']()
    adopted_fiery = isinstance(sets, dict) and (sets.get("fiery") or {}).get("status") == "adopted"
    specs["exp-m4-fiery.json"] = {"name": "m4-fiery", "games": 800, "pairs": [list(_runtime['WORKLOADS']["IG"][::-1])],
                                  "arms": {"none" if adopted_fiery else "fiery":
                                           {"overrides": [], "replace_adopted": True} if adopted_fiery
                                           else {"overrides": ["fiery"]}},
                                  "cards": {"Fiery Annihilation": {"cast_target": 0.5}},
                                  "measures": ["cast", "turn", "win_early", "win_drawn", "matchup", "speed"]}
    specs["exp-m4-shared.json"] = {"name": "m4-shared", "games": 800, "pairs": [list(_runtime['WORKLOADS']["IA"])],
                                   "arms": {"shared": {"seeds": {"stream_from": list(_runtime['WORKLOADS']["IG"]),
                                                                 "seat_of": "casual/izzet-prowess"}}},
                                   "measures": ["matchup"]}
    for name, found in (sets.items() if isinstance(sets, dict) else []):
        if not isinstance(found, dict) or found.get("status") == "adopted":
            continue
        cards = [f.get("card") for f in (found.get("files") or {}).values() if isinstance(f, dict) and f.get("card")]
        pairs = {"Constructed": [], "Commander": []}
        for fmt, deck, reference in _runtime['_override_decks']():
            try:
                entry = _runtime['_entry'](deck)
            except Exception:
                continue
            names = {n for _, n in _runtime['_main_cards'](entry)} | {n for _, n in entry["cards"].get("Commander", [])}
            if names & set(cards) and not any({deck, reference} == set(x) for x in pairs[fmt]):
                pairs[fmt].append([deck, reference])
        # Commander pairs only for a set no Constructed list uses (they're about 5 times slower)
        pairs = pairs["Constructed"] or pairs["Commander"]
        if pairs:
            specs[f"exp-overrides-{name}.json"] = {"name": f"overrides-{name}", "games": 800, "pairs": pairs,
                                                   "arms": {name: {"overrides": [name]}},
                                                   "cards": {c: {"cast_target": 0.5} for c in cards},
                                                   "measures": ["cast", "turn", "win_early", "win_drawn", "own_lost",
                                                                "matchup", "speed"]}
    specs["exp-pump.json"] = {"name": "team-pump", "games": 800, "pairs": [list(_runtime['WORKLOADS']["RV"])],
                              "arms": {"pump": {"pilots": {"casual/selesnya-rabbits": {
                                  "profile": "Default", "switches": ["team-pump-1"]}}}},
                              "measures": ["matchup", "speed"]}
    for builder, arg in ((_runtime['_pilot_specs'], ()), (_runtime['_sensitivity_specs'], (sets,))):
        try:                         # a bug in one builder costs only its own specs
            specs.update(builder(*arg))
        except Exception as e:
            print(f"{builder.__name__} failed ({type(e).__name__}: {e}); its experiments are left out")
    for name, spec in specs.items():
        (out / name).write_text(json.dumps(spec, indent=1), encoding="utf-8")
    m7 = _runtime['_copy_m7_inputs'](out)
    print(f"Wrote {len(specs)} experiment specs, {len(ladders)} ladders"
          + (", the M4 variants" if "variants" in made else ", no M4 variants (Gruul Ramp's list?)")
          + (", the M7 inputs" if m7 else ", no M7 inputs"))
    return 0


def _current_pilot(deck):
    """The target list's pilot as Deck Lab plays it now (simulation.json), {"profile", "switches"}."""
    from decklab.lib.forge import pilots
    try:
        found = pilots.pilot_for(deck, "target") or {}
    except Exception:
        found = {}
    return {"profile": found.get("profile") or "Default", "switches": sorted(found.get("switches") or [])}


def _pilot_specs(_runtime):
    """D2d-p2's specs (sim-combined-run.md section 6, D2d; CONTRACT-W3.md section 12.1):
    exp-profiles.json, the profile mirrors (side a on the profile, 800 games) and the Rabbits
    reference pair; exp-hybrid.json, the hybrid AI's speed part (IG, both lists on the hybrid AI,
    100 games); exp-hybrid-mirror.json, the MBM mirror with side a on the hybrid AI (400 games),
    which the hybrid leg plays only when the speed part allows it. A profile or switch this
    tree's Forge doesn't have, or a list that can't be read, leaves its arm out."""
    from decklab.lib.forge import pilots
    try:
        known = pilots.available()
    except Exception:
        known = {"profiles": list(pilots.FORGE_PROFILES), "switches": []}
    entries = {}

    def entry(deck):
        if deck not in entries:
            try:
                entries[deck] = _runtime['_entry'](deck)
            except Exception:
                entries[deck] = None
        return entries[deck]

    specs, arms, pairs = {}, {}, []
    for deck, profile in _runtime['PROFILE_ARMS']:
        if profile not in known["profiles"] or entry(deck) is None:
            continue
        pilot = dict(_runtime['_current_pilot'](deck), profile=profile)
        arms[f"{deck.split('/')[-1]}-{profile.lower()}"] = {"pilots": {deck: pilot}, "sides": "a"}
        for pair in ([deck, deck], [deck, _runtime['PROFILE_REFERENCE'].get(deck)]):
            if pair[1] and entry(pair[1]) is not None and pair not in pairs:
                pairs.append(pair)
    if arms:
        specs["exp-profiles.json"] = {"name": "profiles", "games": 800, "pairs": pairs, "arms": arms,
                                      "measures": ["matchup", "speed"]}
    if _runtime['HYBRID_SWITCH'] not in known["switches"]:
        return specs
    ig = list(_runtime['WORKLOADS']["IG"])
    if all(entry(d) is not None for d in ig):
        both = {}
        for d in ig:
            cur = _runtime['_current_pilot'](d)
            both[d] = dict(cur, switches=sorted(set(cur["switches"]) | {_runtime['HYBRID_SWITCH']}))
        specs["exp-hybrid.json"] = {"name": "hybrid", "games": 100, "pairs": [ig], "arms": {"hybrid": {"pilots": both}},
                                    "measures": ["matchup", "speed"]}
    if entry(_runtime['HYBRID_MIRROR']) is not None:
        cur = _runtime['_current_pilot'](_runtime['HYBRID_MIRROR'])
        pilot = dict(cur, switches=sorted(set(cur["switches"]) | {_runtime['HYBRID_SWITCH']}))
        specs["exp-hybrid-mirror.json"] = {"name": "hybrid-mirror", "games": 400,
                                           "pairs": [[_runtime['HYBRID_MIRROR'], _runtime['HYBRID_MIRROR']]],
                                           "arms": {"hybrid": {"pilots": {_runtime['HYBRID_MIRROR']: pilot}, "sides": "a"}},
                                           "measures": ["matchup", "speed"]}
    return specs


def _experiment_sets(sets):
    """The override sets the experiments try (every set not adopted, with files), in sets.json's
    order; a set sharing a file with one already taken stays out (two overrides of one card
    script can't both be deployed: etb-flagged after etb)."""
    out, files = [], set()
    for name, found in (sets.items() if isinstance(sets, dict) else []):
        if not isinstance(found, dict) or found.get("status") == "adopted":
            continue
        mine = set(found.get("files") or {})
        if mine and not mine & files:
            out.append(name)
            files |= mine
    return out


def _sensitivity_specs(_runtime, sets):
    """D2e's specs (plan G3; sim-combined-run.md section 6, D2e and section 9.3): every pairing of
    the Constructed field (its current lists, one connected group) at 200 games. (a) is the
    control (staging's results, else played); exp-sensitivity-b.json's arm adds every experiment
    override set; exp-sensitivity-c.json's arm is (b) plus Reckless for Rabbits, on Rabbits'
    pairings. A pairing that no set changes is skipped by the experiment (its (b) is its (a))."""
    try:
        from decklab.lib.forge import field
        decks = [e["id"] for e in field.field_lists("Constructed")]
    except Exception:
        return {}
    exp_sets = _runtime['_experiment_sets'](sets)
    pairs = [[a, b] for i, a in enumerate(decks) for b in decks[i + 1:]]
    specs = {}
    if exp_sets and pairs:
        specs["exp-sensitivity-b.json"] = {"name": "sensitivity-b", "games": _runtime['SENSITIVITY_GAMES'], "pairs": pairs,
                                           "arms": {"overrides": {"overrides": exp_sets}},
                                           "measures": ["matchup", "speed"]}
    if _runtime['SENSITIVITY_DECK'] in decks:
        pilot = dict(_runtime['_current_pilot'](_runtime['SENSITIVITY_DECK']), profile=_runtime['SENSITIVITY_PROFILE'])
        arm = {"pilots": {_runtime['SENSITIVITY_DECK']: pilot}}
        if exp_sets:
            arm["overrides"] = exp_sets
        specs["exp-sensitivity-c.json"] = {
            "name": "sensitivity-c", "games": _runtime['SENSITIVITY_GAMES'],
            "pairs": [[_runtime['SENSITIVITY_DECK'], d] for d in decks if d != _runtime['SENSITIVITY_DECK']],
            "arms": {("overrides-" if exp_sets else "") + _runtime['SENSITIVITY_PROFILE'].lower(): arm},
            "measures": ["matchup", "speed"]}
    return specs


def _copy_m7_inputs(_runtime, out, source=None):
    """Copies D4b's inputs (forge-trial/m7: human.json and the .dck files it names) into <out>/m7; False,
    copying nothing, when they're missing or a deck file human.json names isn't there (M7 is then skipped
    as "no inputs")."""
    source = Path(source or _runtime['M7_INPUTS'])
    try:
        human = json.loads((source / "human.json").read_text(encoding="utf-8"))
        files = [d["file"] for d in human["decks"]]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if len(files) < 2 or not all((source / f).is_file() for f in files):
        return False
    shutil.copytree(source, Path(out) / "m7", dirs_exist_ok=True)
    return True
