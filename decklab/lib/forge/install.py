"""The installed Forge: Java and the newest Forge jar, what a run needs to start Forge
(_setup), the Forge version (each build of the fork is one), the engine release matchups are
keyed by (engine_forge, AI round 1), status() (with whether runs can use the card log), and the
index of Forge's card scripts (the names it knows, and the cards its AI leaves out)."""
import json
import os
import re
import threading
import zipfile
from pathlib import Path

from . import common, simjar
from .common import ForgeError, _decks_dir, _user_dir, forge_name, norm

JAR_GLOB = "forge-gui-desktop-*-jar-with-dependencies.jar"
JAR_RE = re.compile(r"^forge-gui-desktop-(.+)-jar-with-dependencies\.jar$")
SCRIPTS_ZIP = Path("res") / "cardsfolder" / "cardsfolder.zip"
DECKLAB_BUILD = "-decklab-"        # in the build name of Deck Lab's fork of Forge (its decklab/install.py)
VERSION_FILE = "forge-version.txt"  # in DATA_DIR: the last Forge version found (forge_version())
BUILD_FILE = "decklab-build.txt"    # in a fork build's install folder: build=, commit=, base=, scripts_changed=, res_sha256=
DECISION_LOG_MAX = 50               # config's forge_decision_log: at most this many card names


# ============================================================ Forge and Java

def _version_tuple(text):
    return tuple(int(part) if part.isdigit() else 0 for part in re.split(r"[.+_-]", text))


def find_java(setting=None):
    """The java.exe to run Forge with: setting (config forge_java) when given, else the
    newest JDK's in C:\\Program Files\\Java (never the launcher on the PATH). None if
    there's none."""
    if setting:
        path = Path(setting)
        return path if path.is_file() else None
    exe = "java.exe" if os.name == "nt" else "java"
    root = Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "Java"
    found = []
    try:
        for folder in root.glob("jdk-*"):
            if (folder / "bin" / exe).is_file():
                found.append((_version_tuple(folder.name[4:]), folder / "bin" / exe))
    except OSError:
        return None
    return max(found)[1] if found else None


def _find_jar(forge_dir):
    """(jar file name, Forge version) of the newest Forge jar in forge_dir, or (None, None).
    The version is the jar name's release ("2.0.15"), except for a build of Deck Lab's fork of
    Forge (its manifest's Implementation-Version holds DECKLAB_BUILD, like
    "2.0.15-decklab-d84031a6d"): that build is the version, as each commit of the fork can play
    different games, so its matchups are keyed apart and the card log is checked with it."""
    try:
        jars = [(JAR_RE.match(p.name), p) for p in Path(forge_dir).glob(JAR_GLOB)]
    except OSError:
        return None, None
    jars = [(_version_tuple(m[1]), m[1], p.name) for m, p in jars if m]
    if not jars:
        return None, None
    _, version, name = max(jars)
    build = simjar.forge_build(Path(forge_dir) / name)
    if build is not None and DECKLAB_BUILD in build:
        version = build
    return name, version


def release_of(jar_name):
    """The Forge release in a jar's name ("2.0.15"), or None when it isn't Forge's jar name."""
    m = JAR_RE.match(jar_name or "")
    return m[1] if m else None


_build_infos = {}               # {str(path): ((mtime_ns, size), info)}
_build_infos_lock = threading.Lock()


def build_info(forge_dir):
    """The install folder's BUILD_FILE as {key: value} of its "key=value" lines: {} when there's
    none (stock Forge), None when it's there but can't be read. Kept while its time and size
    stay the same."""
    path = Path(forge_dir) / BUILD_FILE
    try:
        stat = path.stat()
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _build_infos_lock:
        known = _build_infos.get(str(path))
    if known and known[0] == stamp:
        return dict(known[1])
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    info = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            info[key.strip()] = value.strip()
    with _build_infos_lock:
        _build_infos[str(path)] = (stamp, info)
    return dict(info)


def engine_forge(forge_dir, jar_name):
    """The engine release a matchup is keyed by (the engine description's "forge", AI round 1),
    so two builds that play the same games share it:
      - stock Forge (no BUILD_FILE): the jar name's release ("2.0.15");
      - a fork build with res_sha256= (from AI round 1 on): its base= release ("forge-2.0.15"
        gives "2.0.15"; the jar name's without base=), then "+res." and the first 12 hex digits
        of res_sha256 (the forge-gui/res files the fork changed, card scripts included);
      - a fork build without res_sha256= (from before AI round 1): its full build= name, as its
        changes may play other games even with game patches off;
      - None when BUILD_FILE can't be read, or lacks what's needed. Never guessed from the jar
        name then.
    The build's game patches are the description's own field."""
    info = build_info(forge_dir)
    if info is None:
        return None
    if not info:
        return release_of(jar_name)
    sha = info.get("res_sha256")
    if not sha:
        return info.get("build") or None
    base = info.get("base")
    release = base[len("forge-"):] if base and base.startswith("forge-") else base or release_of(jar_name)
    if not release or not re.fullmatch(r"[0-9a-f]{12,64}", sha):
        return None
    return f"{release}+res.{sha[:12]}"


def _decision_log(settings):
    """config's forge_decision_log: a list of card names (ForgeError unless it is one)."""
    names = settings.get("forge_decision_log", [])
    if not isinstance(names, list) or len(names) > DECISION_LOG_MAX \
            or not all(isinstance(n, str) and n.strip() for n in names):
        raise ForgeError("config.json's forge_decision_log must be a list of card names.")
    return list(names)


def _setup(forge_dir=None, remember=True):
    """Everything a run needs to start Forge: paths, version and settings. Raises
    ForgeError (a plain sentence) when Forge or Java can't be found. Wave 3: "performance_mode"
    and "game_patches" (False only when off) from config's knobs, "user_dir" the folder runs
    play in (_run_user_dir), and "aiprofiles" the AI profile folder for DeckLabSim
    (pilots.profile_folder; None when Forge's profiles can't be read). AI round 1:
    "engine_forge" (engine_forge(); None when the build file can't be read) and "decision_log"
    (config's forge_decision_log). forge_dir is another install folder than config's
    (engine-check); with remember False its version isn't noted (VERSION_FILE), so a scratch
    install never becomes the one forge_version() falls back to."""
    settings = common._settings()
    forge_dir = Path(settings["forge_dir"] if forge_dir is None else forge_dir)
    jar, version = _find_jar(forge_dir)
    if jar is None:
        raise ForgeError("Forge isn't installed at the folder config.json names." if remember
                         else f"Forge isn't installed at {forge_dir}.")
    if remember:
        _remember_version(version)
    if not (forge_dir / SCRIPTS_ZIP).is_file():
        raise ForgeError("Forge's card scripts are missing from its folder, so it can't play.")
    java = find_java(settings.get("forge_java"))
    if java is None:
        raise ForgeError("Java wasn't found, so Forge can't run.")
    numbers = {}
    for name in ("forge_workers", "forge_clock_s"):     # not forge_batch_games, which no longer counts
        try:
            numbers[name] = int(settings[name])
        except (TypeError, ValueError):
            numbers[name] = 0
        if numbers[name] < 1:
            raise ForgeError(f"config.json's {name} must be a whole number of 1 or more.")
    performance_mode, game_patches = _knobs(settings)
    setup = {
        "forge_dir": forge_dir, "jar": jar, "version": version, "java": str(java),
        "xmx": settings["forge_xmx"], "clock_s": numbers["forge_clock_s"],
        "workers": numbers["forge_workers"], "decks_dir": _decks_dir(), "user_dir": _run_user_dir(performance_mode),
        "performance_mode": performance_mode, "engine_forge": engine_forge(forge_dir, jar),
        "decision_log": _decision_log(settings),
    }
    if not game_patches:
        setup["game_patches"] = False
    from . import pilots            # pilots.py comes after this part
    setup["aiprofiles"] = pilots.profile_folder(setup)
    return setup


def _knobs(settings):
    """(performance_mode, game_patches): config's battery knobs forge_performance_mode and
    forge_game_patches (wave 3, sim-wave3-contract.md section 17), True unless set to false."""
    return (settings.get("forge_performance_mode", True) is not False,
            settings.get("forge_game_patches", True) is not False)


def _run_user_dir(performance_mode=True):
    """The Forge user folder runs play in: the real one (common._user_dir(), with the adopted
    override sets), or, with the forge_performance_mode knob off, a folder of its own with the
    adopted sets and PERFORMANCE_MODE off (overrides.user_dir_for), so a knob never rewrites the
    real folder's forge.preferences, which other launches' workers read when they start."""
    if performance_mode:
        return _user_dir()
    from . import overrides         # overrides.py comes after this part
    try:
        return overrides.user_dir_for(overrides.adopted(), performance_mode=False)
    except (ValueError, OSError) as e:
        raise ForgeError(f"The folder for Forge's PERFORMANCE_MODE knob couldn't be made ({e}).") from None


_known = {}                     # {str(DATA_DIR): the last Forge version found}
_known_lock = threading.Lock()


def _remember_version(version):
    """Note the Forge version found (in memory, and in DATA_DIR's VERSION_FILE), for
    forge_version() while Forge's folder can't be reached."""
    where = str(common.DATA_DIR)
    with _known_lock:
        if _known.get(where) == version:
            return
        _known[where] = version
    path = common.DATA_DIR / VERSION_FILE
    try:
        if path.read_text(encoding="utf-8").strip() == version:
            return
    except OSError:
        pass
    try:
        common._write_atomic(path, version + "\n")
    except OSError as e:
        common._log(f"Forge's version couldn't be noted: {e}")


def forge_version(*, remember=True):
    """The Forge version a matchup is keyed by: the newest Forge jar's in config.json's
    forge_dir (the one run() plays with), else the last one found, so saved results
    are still found while Forge's folder can't be reached. Java doesn't matter here.
    None when Forge was never found. remember=False reads without updating the version cache."""
    try:
        version = _find_jar(Path(common._settings()["forge_dir"]))[1]
    except Exception:           # a bad config.json: status() says so
        version = None
    if version is not None:
        if remember:
            _remember_version(version)
        return version
    with _known_lock:
        known = _known.get(str(common.DATA_DIR))
    if known:
        return known
    try:
        text = (common.DATA_DIR / VERSION_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if re.fullmatch(r"[\w.+-]{1,64}", text) else None


_status = None
_status_lock = threading.Lock()


def status(refresh=False):
    """{"ready": bool, "version": "2.0.15" | None, "problem": None | a plain sentence,
    "card_log": {"ready": bool, "problem": None | a plain sentence}, "pool": the server's warm
    pool's state, pool.status(), or None outside the server} (can runs use the card
    log: simjar.readiness, which builds nothing, and gives the problem this process's last
    try at the card log's jar met, while nothing the jar is built from has changed).
    Never raises. A ready answer is kept while the newest Forge jar is the same version
    (one look at Forge's folder a call); one that isn't ready is checked again next time.
    The card log is looked at every call (a version cardlog-check has just recorded counts
    at once)."""
    global _status
    with _status_lock:
        cached = _status
    forge_jar = None
    if cached is not None and cached["ready"] and not refresh:
        try:
            forge_dir = Path(common._settings()["forge_dir"])
            name, version = _find_jar(forge_dir)
            same = version == cached["version"]
            forge_jar = forge_dir / name
        except Exception:
            same = False
        if same:
            return _with_card_log(cached, forge_jar)
    try:
        setup = _setup()
        found = {"ready": True, "version": setup["version"], "problem": None}
        forge_jar = setup["forge_dir"] / setup["jar"]
    except ForgeError as e:
        version = None
        try:
            version = _find_jar(Path(common._settings()["forge_dir"]))[1]
        except Exception:
            pass
        found = {"ready": False, "version": version, "problem": str(e)}
    except Exception as e:          # a bad config.json, say: status() never raises
        found = {"ready": False, "version": None,
                 "problem": f"Forge's settings couldn't be read ({type(e).__name__})."}
    with _status_lock:
        _status = found
    return _with_card_log(found, forge_jar)


def _with_card_log(found, forge_jar):
    """status()'s answer: found with "card_log" added (forge_jar: the Forge jar's path, so
    its build is checked too), "pool" (_pool_status), and wave 3's "overrides" and
    "pilot_switches" (_overrides_status)."""
    answer = dict(found)
    if not found["ready"]:
        answer["card_log"] = {"ready": False, "problem": simjar.NO_FORGE}
    else:
        try:
            java = find_java(common._settings().get("forge_java"))
        except Exception:           # status() never raises
            java = None
        answer["card_log"] = simjar.readiness(java and str(java), found["version"], forge_jar)
    answer["pool"] = _pool_status()
    answer["overrides"], answer["pilot_switches"] = _overrides_status(answer, forge_jar)
    return answer


def _overrides_status(answer, forge_jar=None):
    """(status()'s "overrides" {"deployed": [cards], "stale": [cards], "hash"}, its
    "pilot_switches" [ids]): the folder runs play in made to hold its intended override files
    first (overrides.ensure_deployed, cheap when nothing changed), so page keys from
    matchup_key follow a sets.json change at once (sim-wave3-contract.md section 6.2). The
    switches are the card log's jar's (simjar.PILOT_SWITCHES) and the AI switches in Forge's
    jar (forge_jar, simjar.fork_switches), sorted; [] while the card log can't be used.
    Never raises: ({"deployed": [], "stale": [], "hash": None}, []) when it can't be told."""
    from . import overrides         # overrides.py comes after this part
    try:
        settings = common._settings()
        user_dir = _run_user_dir(_knobs(settings)[0])
        if answer["ready"]:
            overrides.ensure_deployed(user_dir)
        found = overrides.status(user_dir)
    except Exception as e:          # status() never raises
        common._log(f"Deck Lab's card-script overrides couldn't be read: {e!r}")
        found = {"deployed": [], "stale": [], "hash": None}
    if not answer.get("card_log", {}).get("ready"):
        return found, []
    fork = simjar.fork_switches(forge_jar) if forge_jar is not None else []
    return found, sorted(set(getattr(simjar, "PILOT_SWITCHES", {}) or {}) | set(fork))


def _pool_status():
    """The server's warm pool's state (pool.status(): None outside the server), or None
    when it can't be read (status() never raises)."""
    try:
        from . import pool          # pool.py comes after this part
        return pool.status()
    except Exception as e:
        common._log(f"The warm pool's state couldn't be read: {e!r}")
        return None


# ============================================================ card scripts

SPECIALIZE_FACE = {"WHITE": 2, "BLUE": 3, "BLACK": 4, "RED": 5, "GREEN": 6}


def _read_script(text):
    """(card name, face names, RemoveDeck:All?) from one Forge card script, the way
    Forge's CardRules.Reader names cards (the trial's card_audit.parse_script): "Name:"
    starts a face, "ALTERNATE" and "SPECIALIZE:<colour>" switch faces, and only a Split
    card (AlternateMode:Split) is named "A // B"; every other layout is named after its
    front face."""
    faces, face, split, remove_all = {}, 0, False, False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if key in ("Name", "CopyFaceFrom"):
            faces[face] = value
        elif key == "ALTERNATE":
            face = 1
        elif key.startswith("SPECIALIZE"):
            face = SPECIALIZE_FACE.get(value, face)
        elif key == "AlternateMode":
            split = value.lower() == "split"
        elif key == "AI" and value.startswith("RemoveDeck:") and value.split(":", 1)[1].lower() == "all":
            remove_all = True
    names = [faces[i] for i in sorted(faces) if faces[i]]
    main = faces.get(0)
    if not main:
        return None, names, remove_all
    return (f"{main} // {faces[1]}" if split and faces.get(1) else main), names, remove_all


def _build_index(zip_path):
    """{"scripts", "names": {key: Forge card name}, "faces": {card name: [face names]},
    "remove_all": [card names]} from Forge's cardsfolder.zip. Two scripts with one name
    (a main a-z folder and upcoming/ or rebalanced/): the one in fewer folders wins."""
    best = {}
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        for entry in z.namelist():
            if not entry.endswith(".txt"):
                continue
            count += 1
            name, faces, remove_all = _read_script(z.read(entry).decode("utf-8", "replace"))
            if not name:
                continue
            depth = entry.count("/")
            key = norm(name)
            if key not in best or depth < best[key][0]:
                best[key] = (depth, name, faces, remove_all)
    names, multi, remove = {}, {}, []
    for key, (_, name, faces, remove_all) in best.items():
        names[key] = name
        if remove_all:
            remove.append(name)
        if len(faces) > 1:
            multi[name] = faces
    # Forge also finds a card by any face's name, but a card's own name comes first
    # ("Lightning Bolt" is also the back face of a newer card, and stays Lightning Bolt).
    for name, faces in multi.items():
        for face in faces:
            names.setdefault(norm(face), name)
    return {"scripts": count, "names": names, "faces": multi, "remove_all": sorted(remove)}


_scripts = {}
_scripts_lock = threading.Lock()


def script_index():
    """The index of Forge's card scripts for the installed Forge, read from the cache
    file or built from cardsfolder.zip (about 10 seconds, once per Forge version).
    Raises ForgeError when Forge or its card scripts can't be found."""
    settings = common._settings()
    forge_dir = Path(settings["forge_dir"])
    _, version = _find_jar(forge_dir)
    if version is None:
        raise ForgeError("Forge isn't installed at the folder config.json names.")
    zip_path = forge_dir / SCRIPTS_ZIP
    try:
        stat = zip_path.stat()
    except OSError:
        raise ForgeError("Forge's card scripts are missing from its folder, so it can't play.") from None
    stamp = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    with _scripts_lock:
        index = _scripts.get(version)
        if index is not None and index["zip"] == stamp:
            return index
        cache = common.DATA_DIR / f"cardscripts-{version}.json"
        index = None
        try:
            index = json.loads(cache.read_text(encoding="utf-8"))
            if index.get("zip") != stamp or index.get("version") != version:
                index = None
        except (OSError, ValueError):
            index = None
        if index is None:
            try:
                index = _build_index(zip_path)
            except (OSError, zipfile.BadZipFile) as e:
                raise ForgeError(f"Forge's card scripts can't be read ({type(e).__name__}).") from None
            index.update(version=version, zip=stamp)
            try:
                common._write_atomic(cache, json.dumps(index, ensure_ascii=False))
            except OSError as e:
                common._log(f"Forge's card script index couldn't be saved: {e}")
        index["remove_all_set"] = frozenset(index["remove_all"])
        _scripts.clear()
        _scripts[version] = index
        return index


def _forge_card(name, index):
    """Forge's card name for a Scryfall (or .dck) name, or None if Forge has no script for it."""
    return index["names"].get(norm(forge_name(name)))


def _log_names(dck_names, index):
    """{key: .dck name} for every name Forge may log a list's cards under: the card's
    own name and each face (an adventure cast as its adventure, a modal card's back
    face played as a land)."""
    out = {}
    for dck_name in dck_names:
        out[norm(dck_name)] = dck_name
        card = index["names"].get(norm(dck_name)) if index else None
        if card:
            out.setdefault(norm(card), dck_name)
            for face in index["faces"].get(card, ()):
                out.setdefault(norm(face), dck_name)
    return out
