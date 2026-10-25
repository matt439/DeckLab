"""Forge CLI: engine-check (a new build of the fork against the installed one) and decisions (the
decision log's counts). AI round 1, the ai-r1 contract's sections 3.7 and 3.8.

engine-check plays the same seeded games with two Forge installs, the card log on, and compares
them line for line (cli_checks._games_text with the card log's DL| lines kept), so a build whose
changes are all off by default can be shown to play exactly as the installed one before it's
installed. It also says whether the two builds share an engine key (engine.current, the
description's fields): when they do, results saved with the old build stay current. Nothing it
does writes forge-version.txt or engine.json (install._setup and engine.current with remember
False). It reports only: it never installs, records or gates anything."""
import json
from pathlib import Path

from . import cli_checks as checks
from . import cli_shared as shared
from . import decisionlog

ENGINE_CHECK_GAMES = 25                 # Constructed games a pair (--games), at most one seat block
ENGINE_CHECK_COMMANDER_GAMES = 3        # Commander games a pair (--commander-games)
SAME_KEY = "Same engine key: results saved with the old build stay current."
OTHER_KEY = "Different engine key ({what}): saved results will be an earlier engine."
SAME_INSTALL = "Same install: this run shows whether the build repeats its own games with these lists."
DONT_INSTALL = "Don't install this build as it is: it plays differently with its switches off."
# A pair's verdicts, worst last.
IDENTICAL, UNSURE, DIFFERENT = "identical", "can't tell", "different"
EXIT = {IDENTICAL: 0, DIFFERENT: 1, UNSURE: 3}
COULDNT_RUN = 2


class _Refused(Exception):
    """engine-check can't run (exit 2), in a plain sentence."""


# ============================================================ engine-check

def _install(forge_dir, game_patches, switches):
    """One install's {"dir", "setup", "log", "eng"}: its setup (install._setup for that folder,
    noting nothing, with game patches as game_patches says whatever config's knob says), its card
    log (built whatever the checks say, as cardlog-check builds it) and its engine (engine.current,
    noting nothing). The engine is always worked out with game patches on, as real runs play, so
    the key verdict is the one saved results go by even when the games are played with them off.
    _Refused when one can't be had, the card log can't be used (not a fork build), or the build
    lacks one of switches."""
    try:
        setup = shared.install._setup(forge_dir=forge_dir, remember=False)
    except shared.ForgeError as e:
        raise _Refused(f"{forge_dir}: {e}") from None
    setup.pop("game_patches", None)
    log = shared.simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"], checking=True)
    if not log.get("ready"):
        raise _Refused(f"{forge_dir}: {log.get('problem')}")
    setup["card_log"] = log
    try:
        eng = shared.engine.current(setup, log, remember=False)
    except shared.ForgeError as e:
        raise _Refused(f"{forge_dir}: {e}") from None
    if not game_patches:
        setup["game_patches"] = False
    lacking = [s for s in switches if s not in (log.get("pilot_switches") or [])]
    if lacking:
        raise _Refused(f"{forge_dir}: this Forge build doesn't have the switch{'es' if len(lacking) > 1 else ''} "
                       f"{', '.join(lacking)}.")
    return {"dir": Path(forge_dir), "setup": setup, "log": log, "eng": eng}


def _key_fields(eng):
    """What two engines must share for their keys to be the same (the description's fields,
    and the AI profiles' SHA-256s the sides take)."""
    return {**{field: eng[field] for field in shared.engine.ENGINE_FIELDS}, "ai_sha": eng.get("ai_sha")}


def _key_differences(old, new):
    """The fields of the engine key that differ between two engines, in words."""
    a, b = _key_fields(old), _key_fields(new)
    out = []
    for field in sorted(set(a) | set(b)):
        if a.get(field) != b.get(field):
            if field == "ai_sha":
                out.append("the AI profiles")
            else:
                out.append(f"{field} {_words(a.get(field))} -> {_words(b.get(field))}")
    return out


def _words(value):
    if isinstance(value, list):
        return ",".join(map(str, value)) or "none"
    return str(value)


def _pair_ref(ref):
    """(deck id or .dck path, owned?) of a --pair value: "<deck id>", "<deck id>@target" or
    "<deck id>@owned"."""
    deck, at, version = ref.partition("@")
    if at and version not in ("target", "owned"):
        raise _Refused(f"{ref!r} isn't a list: a deck id, or a deck id with @target or @owned.")
    return deck, version == "owned"


def _pairs(args, folder):
    """[(format, the .dck names in seat order, games, label)] for the check's lists and each
    --pair, with their .dck files written in folder, and each pair's seed stream: [(..., v2)]."""
    out = []
    for fmt, decks_, n in checks._check_legs(args.games, args.commander_games):
        if not n:
            continue
        for name, (commander, cards) in decks_.items():
            sections = ([("Commander", commander)] if commander else []) + [("Main", cards)]
            text = f"[metadata]\nName={name}\n" + "".join(f"[{section}]\n" + "\n".join(lines) + "\n"
                                                         for section, lines in sections)
            (folder / f"{name}.dck").write_text(text, encoding="utf-8", newline="\n")
        names, stream = checks._check_sides(decks_, fmt)
        out.append((fmt, checks._seated(names, 0), n, " v ".join(names), stream))
    for i, (ref_a, ref_b) in enumerate(args.pair or [], 1):
        try:
            entries = [shared._cli_entry(*_pair_ref(ref)) for ref in (ref_a, ref_b)]
        except shared._CliError as e:
            raise _Refused(str(e)) from None
        fmts = {shared.lists.fmt_for(e["kind"]) for e in entries}
        if len(fmts) != 1:
            raise _Refused(f"{ref_a} and {ref_b} aren't lists of one format.")
        fmt = fmts.pop()
        n = args.commander_games if fmt == "Commander" else args.games
        if not n:
            continue
        ordered = sorted(zip(entries, "ab"), key=lambda pair: pair[0]["card_sha"])
        names = []
        for e, side in ordered:
            name = f"pair{i}-{side}"
            (folder / f"{name}.dck").write_text(e["dck"], encoding="utf-8", newline="\n")
            names.append(name)
        stream = shared.seeds.stream_of(ordered[0][0]["card_sha"], ordered[1][0]["card_sha"])
        out.append((fmt, checks._seated(names, 0), n, f"{ref_a} v {ref_b}", stream))
    return out


def _compare_pair(fmt, old, new):
    """{"games", "identical", "lines", "first_difference", "verdict"} of one pair's two outputs:
    games compared line for line (the card log's lines kept). A game that differs is "can't
    tell" when it, or one before it in the same process, hit one of Forge's time limits, or (in
    Commander, which plain Forge doesn't repeat line for line) when it has the same winner,
    starter and length; else the pair is different."""
    a = checks._games_text(old, keep_card_log=True)
    b = checks._games_text(new, keep_card_log=True)
    outcomes = (checks._outcomes(old), checks._outcomes(new)) if fmt not in checks.LINE_FOR_LINE else None
    identical, lines, first, verdict = 0, 0, None, IDENTICAL
    for n, (ga, gb) in enumerate(zip(a, b), 1):
        lines += max(len(ga), len(gb))
        if ga == gb:
            identical += 1
            continue
        if first is None:
            where = next((i for i, (la, lb) in enumerate(zip(ga, gb)) if la != lb), None)
            first = (f"game {n}, line {where + 1}: the old build printed {ga[where]!r}, the new {gb[where]!r}"
                     if where is not None else f"game {n}: the old build printed {len(ga)} lines, the new {len(gb)}")
        if checks._time_limit_game(old, new, n) is not None:
            game = UNSURE
        elif outcomes is not None and n <= min(map(len, outcomes)) and outcomes[0][n - 1] == outcomes[1][n - 1]:
            game = UNSURE
        else:
            game = DIFFERENT
        if game == DIFFERENT or verdict == IDENTICAL:
            verdict = game
    if len(a) != len(b):
        verdict = DIFFERENT
        first = first or f"the old build played {len(a)} games, the new {len(b)}"
    return {"games": max(len(a), len(b)), "identical": identical, "lines": lines, "first_difference": first,
            "verdict": verdict}


def _describe(found):
    """An install's build, engine release and game patches, for the report and --json."""
    return {"build": found["setup"]["version"], "forge": found["eng"]["forge"],
            "game_patches": list(found["log"].get("game_patches") or [])}


def _engine_check(args):
    """engine-check (the module docstring): the exit code (0 identical, 1 a difference, 2 couldn't
    run, 3 only "can't tell")."""
    switches = sorted(set(args.switch or []))
    game_patches = args.game_patches == "on"
    report = {"old": None, "new": None, "same_key": None, "pairs": [], "verdict": "couldn't run"}
    try:
        if switches and not game_patches:
            raise _Refused("The AI switches are always off with game patches off, so --switch can't be used with "
                           "--game-patches off.")
        unknown = [s for s in switches if not shared.runner.PILOT_SWITCH.fullmatch(s)]
        if unknown:
            raise _Refused(f"{', '.join(unknown)} isn't a switch's id.")
        new_dir = Path(args.new) if args.new else Path(shared.common._settings()["forge_dir"])
        same_install = Path(args.old).resolve() == new_dir.resolve()
        old = _install(Path(args.old), game_patches, switches)
        new = old if same_install else _install(new_dir, game_patches, switches)
        report["old"], report["new"] = _describe(old), _describe(new)
        report["same_key"] = _key_fields(old["eng"]) == _key_fields(new["eng"])
        folder = shared.Path(shared.tempfile.mkdtemp(prefix="decklab-engine-check-"))
        try:
            pairs = _pairs(args, folder)
            if not pairs:
                raise _Refused("There's nothing to play: every list has 0 games.")
            done = _play(args, old, new, same_install, folder, pairs, switches, game_patches)
        finally:
            shared.shutil.rmtree(folder, ignore_errors=True)
            shared.runner._tidy_user_dir(old["setup"]["user_dir"])
    except _Refused as e:
        print(f"engine-check can't run: {e}", file=shared.sys.stderr)
        _write_json(args, dict(report, problem=str(e)))
        return COULDNT_RUN
    except shared._CliError as e:
        print(f"engine-check couldn't play its games: {e}", file=shared.sys.stderr)
        _write_json(args, dict(report, problem=str(e)))
        return COULDNT_RUN
    for which, found in (("old", old), ("new", new)):
        d = report[which]
        print(f"{which}: {found['dir']}: build {d['build']}, engine release {d['forge']}, game patches "
              f"{', '.join(d['game_patches']) or 'none'}")
    print(f"Played with game patches {'on' if game_patches else 'off'}"
          + (f" and the switches {', '.join(switches)} on both seats." if switches else ", no switches."))
    worst = IDENTICAL
    for (fmt, _, n, label, _), (old_out, new_out) in zip(pairs, done):
        found = _compare_pair(fmt, old_out, new_out)
        report["pairs"].append({"decks": label, "format": fmt, "games": found["games"], "identical": found["identical"],
                                "lines": found["lines"], "first_difference": found["first_difference"],
                                "verdict": found["verdict"]})
        print(f"  {label} ({fmt}): {found['identical']} of {found['games']} games identical, {found['lines']} lines "
              f"compared" + (f"; {found['verdict']}: {found['first_difference']}" if found["first_difference"] else ""))
        if EXIT[found["verdict"]] and (worst == IDENTICAL or found["verdict"] == DIFFERENT):
            worst = found["verdict"]
    if same_install:
        print(SAME_INSTALL)
    elif report["same_key"]:
        print(SAME_KEY)
    else:
        print(OTHER_KEY.format(what="; ".join(_key_differences(old["eng"], new["eng"]))))
    if worst != IDENTICAL and report["same_key"] and not same_install:
        print(DONT_INSTALL)
    if worst == UNSURE:
        print("Some games differ in a way that says nothing about the builds (a time limit, or a Commander game "
              "that ended the same way): run it again, and compare with a same-install run of these lists.")
    report["verdict"] = worst
    report["same_install"] = same_install
    _write_json(args, report)
    return EXIT[worst]


def _play(args, old, new, same_install, folder, pairs, switches, game_patches):
    """Play each pair with each install (one DeckLabSim process each, cardlog-check's slots and
    Ctrl+C): [(old output, new output)] in pairs' order. With the same install for both, each
    pair is still played twice."""
    pilots = [{"profile": shared.pilots.DEFAULT_PROFILE, "switches": switches}] * 2 if switches else None
    installs = (("old", old), ("new", new))
    envs = {which: shared._prepare_user_dir(found["setup"]["user_dir"]) for which, found in installs}
    markers = [shared.runner._first_use_marker(found["setup"]["user_dir"], found["setup"]["version"])
               for _, found in installs]
    runs = {}
    for i, (fmt, seated, n, _, stream) in enumerate(pairs):
        v2 = {"stream": shared.seeds.stream_hex(stream), "first": 0}
        for which, found in installs:
            options = checks.RunOptions(setup=found["setup"], env=envs[which], pilots=pilots)
            runs[i, which] = (fmt, seated, n, found["log"], args.seed, v2, game_patches, options)
    print(f"Playing {len(pairs)} pairs with each build ({'one install, twice' if same_install else 'two installs'})...",
          file=shared.sys.stderr)
    done = checks._play_check_runs(new["setup"], folder, envs["new"], runs, not all(m.exists() for m in markers))
    for marker in markers:
        try:
            marker.touch()
        except OSError:
            pass
    return [(done[i, "old"][0], done[i, "new"][0]) for i in range(len(pairs))]


def _write_json(args, report):
    if args.json:
        try:
            Path(args.json).write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as e:
            print(f"The summary couldn't be written to {args.json} ({shared._os_reason(e)}).", file=shared.sys.stderr)


def _engine_check_args(sub):
    check = sub.add_parser("engine-check", help="check a new build of Forge plays the same games as the installed one")
    check.add_argument("--old", required=True, help="the installed Forge's folder (C:/Tools/forge-decklab)")
    check.add_argument("--new", help="the new build's folder (default: config.json's forge_dir)")
    check.add_argument("--games", type=_games, default=ENGINE_CHECK_GAMES,
                       help=f"Constructed games a pair (0 to {checks.CHECK_MAX_GAMES})")
    check.add_argument("--commander-games", type=_games, default=ENGINE_CHECK_COMMANDER_GAMES,
                       help=f"Commander games a pair (0 to {checks.CHECK_MAX_GAMES})")
    check.add_argument("--pair", nargs=2, action="append", metavar="DECK",
                       help="two lists to play as well (deck ids, @owned allowed, or .dck files)")
    check.add_argument("--switch", action="append", help="an AI switch on for both seats (repeat for more)")
    check.add_argument("--game-patches", choices=("on", "off"), default="on")
    check.add_argument("--seed", type=int, default=checks.CHECK_SEED, help="the seed base")
    check.add_argument("--json", metavar="FILE", help="write a summary as JSON")


def _games(text):
    """argparse's type for engine-check's games: 0 to one seat block."""
    try:
        number = int(text)
    except ValueError:
        number = -1
    if not 0 <= number <= checks.CHECK_MAX_GAMES:
        raise shared.argparse.ArgumentTypeError(f"must be a whole number from 0 to {checks.CHECK_MAX_GAMES}, "
                                                f"not {text!r}")
    return number


def _cmd_engine_check(args):
    return _engine_check(args)


# ============================================================ decisions

def _decisions_args(sub):
    found = sub.add_parser("decisions", help="the decision log's counts in a folder of game logs")
    found.add_argument("folder", help="a tee folder: <logs>/<arm or control>/<matchup key>")
    found.add_argument("--card", action="append", help="only this card (repeat for more)")
    found.add_argument("--json", action="store_true")


def _cmd_decisions(args):
    games = decisionlog.read_folder(args.folder, args.card)
    totals = decisionlog.summary(games)
    if args.json:
        print(json.dumps({"games": len(games), "cards": totals}, indent=1, ensure_ascii=False, sort_keys=True))
        return 0
    if not totals:
        print(f"No decision-log lines in {len(games)} games in {args.folder} (forge_decision_log names the cards, "
              "and needs --local).")
        return 0
    print(f"{len(games)} games in {args.folder}")
    for card, t in sorted(totals.items()):
        print(f"{card}: an opportunity in {t['games']} games; {t['opportunities']} opportunities, {t['taken']} taken")
        declined = sorted(t["declined"].items(), key=lambda kv: (-kv[1], kv[0]))
        if declined:
            print("  declined: " + ", ".join(f"{d} {n}" for d, n in declined))
        for key, label in (("by_phase", "phase"), ("by_seat", "seat")):
            parts = sorted(t[key].items(), key=lambda kv: (-kv[1]["opportunities"], kv[0]))
            if parts:
                print(f"  by {label}: " + ", ".join(f"{name} {p['taken']}/{p['opportunities']}" for name, p in parts))
    return 0
