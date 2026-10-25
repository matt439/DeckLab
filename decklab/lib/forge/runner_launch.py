"""Forge command construction, serve protocol and user-folder preparation.

runner.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import os
from pathlib import Path
from urllib.parse import quote

from . import engine, overrides, pilots, seeds, simjar
from .common import forge_name

from . import runner as runtime


def _preferences(setup):
    """Forge's preferences for a run's user folder (wave 3): PREFERENCES, with PERFORMANCE_MODE
    as setup["performance_mode"] says (config's forge_performance_mode knob; on when missing)."""
    if setup.get("performance_mode", engine.PERFORMANCE_MODE) is not False:
        return runtime.PREFERENCES
    return runtime.PREFERENCES.replace("PERFORMANCE_MODE=true\n", "PERFORMANCE_MODE=false\n")


def request_args(setup, fmt, deck1, deck2, games, seed, v2=None, pilots=None):
    """One request's arguments, from "sim" on: what follows the main class (or Forge's
    -jar) on a batch's command line, and the fields of a serve worker's "play" line
    (request_line). deck1 and deck2 are .dck file names in setup["decks_dir"]. v2 (the v2
    engine, wave 2's contract "The request"): {"stream": the result's seed stream, 16 hex
    digits (seeds.stream_hex), "first": the result's game number of the request's first
    game}, and seed is then the result's base (ValueError below 0); "card_log": False adds
    -dlnocardlog (the v2 card-log check's leg without the listener).
    pilots (wave 3, sim-wave3-contract.md section 3.3): [deck 1's pilot, deck 2's pilot] in the
    request's seat order, each {"profile", "switches"}: -a gets each seat's profile, and a v2
    request "-dlpilot <seat 1> <seat 2>" after -dlgame (each seat's switches joined by "+", or
    "-" for none; only when a seat has a switch, so a request without any is wave 2's). A v1
    request (plain Forge, or DeckLabSim's batches) takes profiles only (ValueError for a
    switch). None plays both seats with AI_PROFILES, as wave 2 does. ValueError for a pilot
    that isn't {"profile": a name, "switches": [ids]}."""
    profiles = list(runtime.AI_PROFILES)
    switches = None
    if pilots is not None:
        profiles, switches = runtime._seat_pilots(pilots)
        if v2 is None and switches is not None:
            raise ValueError("a pilot's switches need the v2 engine's requests (-dlgame)")
    args = ["sim", "-D", str(setup["decks_dir"]), "-d", deck1, deck2, "-n", str(games), "-s", str(seed),
            "-f", fmt, "-c", str(setup["clock_s"]), "-a", *profiles]
    if v2 is not None:
        if int(seed) < 0:
            raise ValueError(f"a v2 request's base must be 0 or more, not {seed}")   # "-s -5" is no -s to Forge
        args += ["-dlgame", seeds.stream_hex(seeds.parse_stream(v2["stream"])), str(int(v2["first"]))]
        if switches is not None:
            args += ["-dlpilot", *switches]
        if v2.get("card_log") is False:
            args.append("-dlnocardlog")
    return args


def _seat_pilots(pilots):
    """([seat 1's profile, seat 2's], [seat 1's -dlpilot value, seat 2's] or None when no seat
    has a switch) for request_args. ValueError for pilots that can't be put on a command line."""
    if not isinstance(pilots, (list, tuple)) or len(pilots) != 2:
        raise ValueError("pilots must be [deck 1's pilot, deck 2's pilot]")
    profiles, switches = [], []
    for pilot in pilots:
        profile = pilot.get("profile") if isinstance(pilot, dict) else None
        ids = (pilot.get("switches") or []) if isinstance(pilot, dict) else None
        if not isinstance(profile, str) or not runtime.PILOT_PROFILE.fullmatch(profile):
            raise ValueError(f"a pilot's profile must be a profile's name, not {profile!r}")
        if not isinstance(ids, list) or not all(isinstance(i, str) and runtime.PILOT_SWITCH.fullmatch(i) for i in ids):
            raise ValueError(f"a pilot's switches must be a list of switch ids, not {ids!r}")
        profiles.append(profile)
        switches.append("+".join(sorted(ids)) or "-")
    return profiles, (switches if any(s != "-" for s in switches) else None)


def _java(setup):
    """The start of every Forge command line: java, the heap, JVM_FLAGS, and
    simjar.GAME_PATCHES_OFF when setup["game_patches"] is False (the v2 card-log check's
    comparison with plain Forge, and wave 3's forge_game_patches knob) or the card log isn't
    ready (plain Forge, whose engine has no game patches: Deck Lab's changes in its fork's
    Forge then play Forge's own code). Wave 3: DeckLabSim's launches (the card log ready) get
    -Ddecklab.aiprofiles=<setup["aiprofiles"]>, the folder of Forge's and Deck Lab's AI
    profiles (pilots.profile_folder), when there is one. AI round 1: with the card log ready and
    setup["decision_log"] naming cards (config's forge_decision_log), DECISION_LOG_FLAG=<their
    Forge names, each escaped (decision_log_value), joined by ";">, so the fork prints a DLAI|
    line for each AI decision about them (decisionlog.py reads them)."""
    ready = (setup.get("card_log") or {}).get("ready")
    flags = [simjar.GAME_PATCHES_OFF] if setup.get("game_patches") is False or not ready else []
    if setup.get("aiprofiles") and ready:
        flags.append(f"{runtime.AIPROFILES_FLAG}={setup['aiprofiles']}")
    if setup.get("decision_log") and ready:
        flags.append(f"{DECISION_LOG_FLAG}={decision_log_value(setup['decision_log'])}")
    return [setup["java"], f"-Xmx{setup['xmx']}", *runtime.JVM_FLAGS, *flags]


DECISION_LOG_FLAG = "-Ddecklab.decisionLog"     # the fork's forge.ai.AiDecisionLog.PROPERTY
DECISION_LOG_SAFE = " !'(),-./:&?*"             # left as they are ("*" alone: every card); "%", ";", "|" and non-ASCII are %XX


def decision_log_value(names):
    """The decision log's property value for these card names: each one's Forge name, %XX-escaped
    as UTF-8 but for DECISION_LOG_SAFE (the fork decodes only "%" escapes), joined by ";"."""
    return ";".join(quote(forge_name(name), safe=DECISION_LOG_SAFE) for name in names)


def _class_path_launch(setup):
    """DeckLabSim's launch: the --add-opens flags Forge's manifest gives -jar, the class path
    (the card-log jar, then Forge's; Deck Lab's changes to Forge's classes are in Forge's jar,
    its fork's build) and the main class. ValueError when the card log
    isn't ready (setup["card_log"], simjar.card_log())."""
    log = setup.get("card_log") or {}
    if not log.get("ready"):
        raise ValueError("DeckLabSim needs the card log's jar")
    return [*log["add_opens"], "-cp", os.pathsep.join([log["jar"], setup["jar"]]), log["main"]]


def serve_command(setup):
    """A warm worker's command line (run in setup["forge_dir"]): DeckLabSim in serve mode
    (java/decklab/DeckLabServe.java; wave 2's contract "Serve protocol"), which reads
    requests (request_line) on stdin. Needs the card log ready (ValueError otherwise). The
    tests replace this with the fake Forge's serve mode."""
    return [*runtime._java(setup), *runtime._class_path_launch(setup), "serve"]


def serve_event(line):
    """A serve worker's protocol line (wave 2's contract "Serve protocol") as a dict, or None
    for any other line (Forge's own output, a request's games):
        {"what": "ready", "protocol": int, "pid": int, "counters": text}
        {"what": "begin", "id": text}
        {"what": "end", "id": text, "status": one of SERVE_STATUSES, "games": int, "ms": int,
         "detail": text (may hold "|"): done or cancelled "heap_mb=<n>" (SERVE_HEAP: the
         worker's heap after its latest GC), recycle one of RECYCLE_REASONS, error why}
        {"what": "bye", "why": "quit" | "eof" | "recycle" | "error"}
        {"what": "bad", "text": text}       a command the worker didn't understand
        {"what": "fail", "why": text}       it can't serve at all
    ValueError for a DLSERVE| line that isn't one of these."""
    line = line.rstrip("\r\n")
    if not line.startswith(runtime.SERVE_PREFIX):
        return None
    what, _, rest = line[len(runtime.SERVE_PREFIX):].partition("|")
    try:
        if what == "ready":
            protocol, pid, counters = rest.split("|", 2)
            return {"what": what, "protocol": int(protocol), "pid": int(pid), "counters": counters}
        if what == "begin" and runtime.REQUEST_ID.fullmatch(rest):
            return {"what": what, "id": rest}
        if what == "end":
            request_id, status, games, ms, detail = rest.split("|", 4)
            if runtime.REQUEST_ID.fullmatch(request_id) and status in runtime.SERVE_STATUSES:
                return {"what": what, "id": request_id, "status": status, "games": int(games), "ms": int(ms),
                        "detail": detail}
        if what == "bye" and rest:
            return {"what": what, "why": rest}
        if what == "bad":
            return {"what": what, "text": rest}
        if what == "fail":
            return {"what": what, "why": rest}
    except ValueError:
        pass
    raise ValueError(f"not a serve protocol line: {line!r}")


def request_line(request_id, args):
    """The "play" line that asks a serve worker to play a request (args: request_args()),
    with its newline. ValueError for an id that isn't REQUEST_ID, or an argument holding a
    tab or a line break (a deck folder's path, say), which the line can't carry."""
    if not runtime.REQUEST_ID.fullmatch(str(request_id)):
        raise ValueError(f"not a request id: {request_id!r}")
    for arg in args:
        if any(ch in arg for ch in "\t\r\n"):
            raise ValueError(f"a serve request can't carry {arg!r}")
    return "\t".join(["play", str(request_id), *args]) + "\n"


def _prepare_user_dir(user_dir):
    """The environment for Forge: its user folder with its preferences (_preferences: lazy card
    loading, and PERFORMANCE_MODE as the folder's manifest says, on for a folder without one:
    overrides.user_dir_for's folders hold the knob's), its card-script overrides deployed
    (overrides.ensure_deployed: the folder's Forge/custom/cards is Deck Lab's, and holds exactly
    the folder's override sets, so a worker started for an experiment's folder keeps that
    folder's files), and the output copies older processes left (forge.<time>.log) deleted.
    Called at every worker start; engine.py hashes custom/cards into the engine id."""
    from . import overrides         # forge/__init__ imports it before engine; runner comes after both
    user_dir = Path(user_dir)
    found = overrides.manifest(user_dir)
    preferences = runtime._preferences({"performance_mode": found["performance_mode"] if found else True})
    prefs = user_dir / "Forge" / "preferences" / "forge.preferences"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    try:
        have = prefs.read_text(encoding="utf-8")
    except OSError:
        have = None
    if have != preferences:
        prefs.write_text(preferences, encoding="utf-8", newline="\n")
    overrides.ensure_deployed(user_dir)
    for old in (user_dir / "Forge").glob("forge.*.log"):
        try:
            old.unlink()
        except OSError:
            pass
    env = dict(os.environ)
    env["APPDATA"] = str(user_dir)
    env["LOCALAPPDATA"] = str(user_dir)
    return env


def _first_use_marker(user_dir, version):
    """The file in Forge's user folder that says this Forge version has started there
    before: until it's there, a run starts one process alone first (_play)."""
    return user_dir / f".started-{version}"


