"""Pilots: which AI profile and which of Deck Lab's AI switches play each list (simulation wave
3's R16, forge-trial/sim-wave3-contract.md section 5). They're set per list in
decklab/simulation.json, which ships with every list on Forge's Default profile and no
switches until a pilot is adopted. A pilot is {"profile": a name, "switches": [ids, sorted]}.

    SIMULATION_FILE         decklab/simulation.json (section 5.1)
    PROFILES_DIR            Deck Lab's own AI profiles (ai-profiles/*.ai, section 5.3)
    MIRRORS                 ai-profiles in <data>/forge: the profile folders made for Java
    DEFAULT_PILOT           {"profile": "Default", "switches": []}
    SWITCH_WORDS            the page's and the command line's words for each switch
    load()                  simulation.json, read again when its modification time changes:
                            {"default": pilot, "lists": {id: pilot}, "field": ..., "problems": [...]}
    pilot_for(deck_id, version)
                            the list's pilot (a copy of the default one when none is set)
    FORK_SWITCHES           the fork's own AI switches Deck Lab knows (AI round 1)
    check_switches(eng, pilot)
                            ValueError (a sentence) for a switch eng can't play
    profile_folder(setup)   the mirror of Forge's and Deck Lab's profiles, or None
    available()             {"profiles": [...], "switches": [...]}
    problems()              the bad entries of simulation.json (the pilots --check command)
    words(pilot)            "Forge's AI plays it with the Reckless profile and the team-pump fix", or
                            None for the default pilot
    is_default(pilot), deck_lab_profiles(), profile_sha(name)

What's available: profiles are Forge's res/ai/*.ai names (FORGE_PROFILES when its folder can't
be read) and Deck Lab's own; switches are simjar.PILOT_SWITCHES' ids (the jar always holds Deck
Lab's own classes: they compile or the build fails) and FORK_SWITCHES (AI round 1: the fork's own
AI fixes, forge.ai.AiSwitches, each off unless a pilot names it), so nothing here builds the card
log's jar or reads Forge's. A run checks the build it plays has each switch its pilots name
(check_switches, from the card log's "pilot_switches"), so simulation.json may name a fork switch
before the installed build has it.
A bad entry of simulation.json (an unknown profile or switch, an id that isn't a list's, a
value that isn't a pilot) is left out whole, with one log line, and pilot_for gives the default
pilot for that list.

This part comes after overrides.py and before engine.py (forge/__init__'s order): it must not
import engine at module level."""
import copy
import hashlib
import json
import re
import shutil
import threading
from pathlib import Path

from decklab.lib import config

from . import common, deck_identity

SIMULATION_FILE = config.DECKLAB / "simulation.json"
PROFILES_DIR = Path(__file__).resolve().parent / "ai-profiles"
MIRRORS = "ai-profiles"             # in <data>/forge: <sha12>/ folders of profiles for Java
DEFAULT_PROFILE = "Default"
DEFAULT_PILOT = {"profile": DEFAULT_PROFILE, "switches": []}
SWITCH_WORDS = {"team-pump-1": "team-pump fix", "aisim-hybrid-1": "look-ahead AI (experimental)",
                "removal-in-combat-1": "combat-removal fix", "etb-harmless-1": "optional-target fix",
                "prowess-precombat-1": "prowess-first fix (experimental)"}
# The fork's own AI switches (AI round 1, the fork's decklab/ai-switches.txt; a test holds them equal):
# removal-in-combat-1 removes a blocker that would kill the AI's attacker, etb-harmless-1 lets the AI
# cast a card whose optional ETB or trigger has no target, prowess-precombat-1 casts cheap card-draw
# and burn before combat when a prowess creature can attack.
FORK_SWITCHES = ("etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1")
FORGE_PROFILES = ("Default", "Cautious", "Reckless", "Experimental")    # Forge 2.0.15's res/ai
PROFILE_NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")   # no "|", "=" or "," (the DLENGINE line)
LIST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}")
VERSIONS = ("target", "owned")
# team-pump-1 is installed by AiPatches, which runs only with game patches on; the fork's switches are
# always off with them off (forge.ai.AiSwitches).
NEEDS_GAME_PATCHES = ("team-pump-1",) + FORK_SWITCHES

_lock = threading.Lock()
_loaded = {}                # {str(SIMULATION_FILE): (stamp, answer)}
_logged = set()


def _forge_ai_dir():
    try:
        return Path(common._settings()["forge_dir"]) / "res" / "ai"
    except Exception:           # a bad config.json: as if Forge couldn't be reached
        return None


def forge_profiles(forge_dir=None):
    """The names of Forge's AI profiles (res/ai/*.ai), or FORGE_PROFILES when its folder can't
    be read."""
    folder = Path(forge_dir) / "res" / "ai" if forge_dir is not None else _forge_ai_dir()
    try:
        found = sorted(p.stem for p in folder.glob("*.ai") if p.is_file()) if folder is not None else []
    except OSError:
        found = []
    return found or list(FORGE_PROFILES)


def deck_lab_profiles():
    """The names of Deck Lab's own AI profiles (PROFILES_DIR/*.ai)."""
    try:
        return sorted(p.stem for p in PROFILES_DIR.glob("*.ai") if p.is_file())
    except OSError:
        return []


def profile_sha(name):
    """The SHA-256 of Deck Lab's profile file name.ai (CRLF made LF, as engine._file_sha), or
    None when name isn't one of Deck Lab's."""
    path = PROFILES_DIR / f"{name}.ai"
    try:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    except OSError:
        return None


def _switches():
    from . import simjar            # simjar comes before this part, but only this needs it
    return sorted(set(getattr(simjar, "PILOT_SWITCHES", {}) or {}) | set(FORK_SWITCHES))


def available():
    """{"profiles": the names -a may use (Forge's and Deck Lab's), "switches": the switch ids
    a pilot may name: the card log's jar's (simjar.PILOT_SWITCHES) and the fork's
    (FORK_SWITCHES)}."""
    return {"profiles": sorted(set(forge_profiles()) | set(deck_lab_profiles())), "switches": _switches()}


def _pilot(value, known):
    """(a pilot, None) from simulation.json's value, or (None, why not)."""
    if not isinstance(value, dict) or set(value) - {"profile", "switches"}:
        return None, "isn't {\"profile\": ..., \"switches\": [...]}"
    profile = value.get("profile", DEFAULT_PROFILE)
    switches = value.get("switches", [])
    if not isinstance(profile, str) or not PROFILE_NAME.fullmatch(profile):
        return None, f"has a profile name that can't be used ({profile!r})"
    if profile not in known["profiles"]:
        return None, f"names a profile there's none of: {profile}"
    if not isinstance(switches, list) or not all(isinstance(s, str) for s in switches) \
            or len(set(switches)) != len(switches):
        return None, "has switches that aren't a list of names"
    unknown = [s for s in switches if s not in known["switches"]]
    if unknown:
        return None, f"names a switch there's none of: {', '.join(unknown)}"
    return {"profile": profile, "switches": sorted(switches)}, None


def _list_id(name):
    """Is name a list's id: "<deck id>", "<deck id>@target" or "<deck id>@owned"?"""
    deck, at, version = name.partition("@")
    return bool(LIST_ID.fullmatch(deck)) and (not at or version in VERSIONS)


def _read():
    """simulation.json read and checked (load()'s answer, without the cache)."""
    try:
        data = json.loads(SIMULATION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"default": copy.deepcopy(DEFAULT_PILOT), "lists": {}, "field": {}, "version": None,
                "problems": [f"decklab/simulation.json can't be read ({type(e).__name__}), so every list plays "
                             "with Forge's Default profile."]}
    known = available()
    problems = []
    pilots = data.get("pilots") if isinstance(data, dict) else None
    pilots = pilots if isinstance(pilots, dict) else {}
    default, why = _pilot(pilots.get("default", DEFAULT_PILOT), known)
    if default is None:
        problems.append(f"The default pilot {why}, so Forge's Default profile is used.")
        default = copy.deepcopy(DEFAULT_PILOT)
    lists = {}
    found = pilots.get("lists", {})
    if not isinstance(found, dict):
        problems.append("The pilots' \"lists\" isn't {list id: pilot}, so every list has the default pilot.")
        found = {}
    for name, value in found.items():
        if not _list_id(name):
            problems.append(f"{name!r} isn't a list's id (<deck id>, or <deck id>@target or @owned).")
            continue
        pilot, why = _pilot(value, known)
        if pilot is None:
            problems.append(f"{name}'s pilot {why}, so it plays with the default pilot.")
            continue
        lists[name] = pilot
    field = data.get("field") if isinstance(data, dict) and isinstance(data.get("field"), dict) else {}
    return {"default": default, "lists": lists, "field": field,
            "version": data.get("version") if isinstance(data, dict) else None, "problems": problems}


def load():
    """decklab/simulation.json, checked (section 5.2): {"default": the default pilot, "lists":
    {list id: pilot}, "field": its field section, "version", "problems": [sentences]}. Read
    again when the file's modification time changes; each bad entry is left out, with one log
    line."""
    try:
        stat = SIMULATION_FILE.stat()
        stamp = (stat.st_mtime_ns, stat.st_size, tuple(available()["switches"]))
    except OSError:
        stamp = None
    with _lock:
        known = _loaded.get(str(SIMULATION_FILE))
        if known and stamp is not None and known[0] == stamp:
            return known[1]
    answer = _read()
    for problem in answer["problems"]:
        if problem not in _logged:
            _logged.add(problem)
            common._log(f"decklab/simulation.json: {problem}")
    with _lock:
        _loaded[str(SIMULATION_FILE)] = (stamp, answer)
    return answer


def pilot_for(deck_id, version):
    """The pilot of a deck's list, including its former ids. Version-specific keys win;
    at equal specificity the current id wins, then former ids in sorted order. Conflicting
    former/current keys are reported by problems(). A copy, so callers may change it."""
    data = load()
    names = deck_identity.lineage(deck_id)
    keys = [f"{name}@{version}" for name in names]
    selected = [key for key in keys if key in data["lists"]]
    selected = selected or [name for name in names if name in data["lists"]]
    found = data["lists"][selected[0]] if selected else data["default"]
    if any(data["lists"][key] != found for key in selected[1:]):
        problem = f"Conflicting pilots for {names[0]}: using {selected[0]} before {', '.join(selected[1:])}."
        if problem not in _logged:
            _logged.add(problem)
            common._log(f"decklab/simulation.json: {problem}")
    return {"profile": found["profile"], "switches": list(found["switches"])}


def default_pilot():
    """The default pilot (simulation.json's "default"), a copy."""
    found = load()["default"]
    return {"profile": found["profile"], "switches": list(found["switches"])}


def problems():
    """simulation.json's bad entries, each a sentence (left out of pilot_for)."""
    data = load()
    answer = list(data["problems"])
    groups = {}
    for key, pilot in data["lists"].items():
        name, at, version = key.partition("@")
        groups.setdefault((deck_identity.canonical(name), version if at else None), []).append((key, pilot))
    for (name, version), found in sorted(groups.items(), key=lambda item: str(item[0])):
        if any(pilot != found[0][1] for _, pilot in found[1:]):
            label = name + (f"@{version}" if version else "")
            answer.append(f"{label} has conflicting pilots under its current/former ids "
                          f"({', '.join(sorted(key for key, _ in found))}); the current id wins, "
                          "then former ids in sorted order.")
    return answer


def is_default(pilot):
    """Is pilot Forge's Default profile with no switches (or missing)?"""
    return not pilot or (pilot.get("profile", DEFAULT_PROFILE) == DEFAULT_PROFILE and not pilot.get("switches"))


def check_switches(eng, pilot):
    """ValueError, with a sentence, when eng can't play one of pilot's switches: one of
    NEEDS_GAME_PATCHES with game patches off (eng["game_patches_on"] False, the setup's knob;
    for an engine from before AI round 1 without that field, eng["game_patches"] == []: Deck
    Lab's AI patches aren't installed then, and the fork's switches are off, so the switch would
    do nothing), or a switch the build doesn't have (not in eng["switches"], the card log's
    "pilot_switches", when eng says). Plain Forge plays no switches and its sides record none
    (engine.side_list), so it refuses nothing there."""
    if not pilot or eng.get("kind") != "decklab":
        return None
    off = eng["game_patches_on"] is False if "game_patches_on" in eng else not eng.get("game_patches")
    for switch in pilot.get("switches") or []:
        words = SWITCH_WORDS.get(switch, switch)
        if switch in NEEDS_GAME_PATCHES and off:
            raise ValueError(f"The {words} ({switch}) needs Deck Lab's game patches on, so this run wasn't started.")
        if "switches" in eng and switch not in eng["switches"]:
            raise ValueError(f"This Forge build doesn't have the {words} ({switch}), so this run wasn't started.")
    return None


def words(pilot):
    """A pilot in words for the page, or None for the default pilot (section 5.4): "Forge's AI
    plays it with the Reckless profile and the team-pump fix"."""
    if is_default(pilot):
        return None
    profile = pilot.get("profile", DEFAULT_PROFILE)
    parts = []
    if profile != DEFAULT_PROFILE:
        parts.append(f"Deck Lab's {profile} profile" if profile in deck_lab_profiles() else f"the {profile} profile")
    parts += [f"the {SWITCH_WORDS.get(s, s)}" for s in pilot.get("switches") or []]
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"Forge's AI plays it with {joined}"


# ============================================================ the profile folder for Java

_folders = {}               # {stamp of the files: the folder}


def _profile_files(forge_dir):
    """[(name.ai, path)] of Forge's res/ai profiles and Deck Lab's, or None when Forge's can't
    be read. Deck Lab's never take a Forge profile's name."""
    try:
        forge = sorted((p.name, p) for p in (Path(forge_dir) / "res" / "ai").glob("*.ai") if p.is_file())
        mine = sorted((p.name, p) for p in PROFILES_DIR.glob("*.ai") if p.is_file())
    except OSError:
        return None
    if not forge:
        return None
    taken = {name for name, _ in forge}
    return forge + [(name, path) for name, path in mine if name not in taken]


def profile_folder(setup):
    """The AI profile mirror's folder (section 5.3): Forge's res/ai/*.ai and Deck Lab's
    ai-profiles/*.ai copied into <data>/forge/ai-profiles/<sha12>/, a folder named by the hash
    of its sorted file hashes and written once. None when Forge's profiles can't be read (Java
    then gets no folder, and plays Forge's own)."""
    files = _profile_files(setup["forge_dir"])
    if files is None:
        return None
    try:
        stamp = tuple((name, path.stat().st_mtime_ns, path.stat().st_size) for name, path in files)
        with _lock:
            if stamp in _folders and _folders[stamp].is_dir():
                return _folders[stamp]
        shas = [(name, hashlib.sha256(path.read_bytes()).hexdigest()) for name, path in files]
        sha = hashlib.sha256("".join(f"{name}\0{h}\n" for name, h in shas).encode("utf-8")).hexdigest()
        folder = common.DATA_DIR / MIRRORS / sha[:12]
        if not folder.is_dir():
            tmp = folder.with_name(f"{folder.name}.tmp-{threading.get_ident()}")
            shutil.rmtree(tmp, ignore_errors=True)
            tmp.mkdir(parents=True)
            for name, path in files:
                shutil.copyfile(path, tmp / name)
            try:
                tmp.rename(folder)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
                if not folder.is_dir():
                    raise
    except OSError as e:
        common._log(f"The AI profiles couldn't be copied for Forge: {e}")
        return None
    with _lock:
        _folders[stamp] = folder
    return folder
