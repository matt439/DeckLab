"""Deck Lab's card-script overrides (simulation wave 3's R10, forge-trial/sim-wave3-contract.md
section 6): Forge card scripts with small AI edits, kept in decklab/lib/forge/overrides/ (sets
of them, sets.json) and put in Forge's user folder's custom/cards, which Forge loads over its
own scripts when a JVM starts. Only "adopted" sets go in the real user folder; experiment sets
play in folders of their own (user_dir_for).

    SETS_DIR, SETS_FILE         the repo's sets: overrides/<set>/<card>.txt and sets.json
    MANIFEST                    decklab-manifest.json, in the root of a folder user_dir_for made
    LOCK_FILE                   overrides.lock in <data>/forge: the deploy lock (an OS lock)
    UPSTREAM_FILE               overrides-upstream.json in <data>/forge: Forge's own scripts'
                                SHA-256s per Forge version and build (the upstream check)
    load_sets()                 sets.json, checked: {"version", "forge", "sets": {name: {"status",
                                "why", "files": {file: {"card", "upstream_sha256", "edits",
                                "cast_target"}}}}}
    adopted()                   the names of the "adopted" sets, in sets.json's order
    deployed_hash(user_dir)     the canonical hash of <user_dir>/Forge/custom/cards (section 6.4):
                                wave 2's engine._overrides form, which Java's start-up hash matches
    deployed_index(user_dir)    {card name (the script's Name:): file SHA-256} of that folder
    deployed_scripts(user_dir)  {card name: the script's text} of that folder (ai.py's overlay)
    ensure_deployed(user_dir)   the folder made to hold exactly its intended files, under the lock:
                                {"index", "hash"} (section 6.2)
    deploy(user_dir, sets=None) copy those sets' files in (default: the adopted ones), deleting any
                                other file; {"deployed": [...], "files": {...}, "stale": [...],
                                "unknown": [...], "hash"}
    user_dir_for(sets, *, performance_mode=True)
                                <data>/forge/users/exp-<12 hex>/ with its manifest (section 6.2)
    manifest(user_dir)          a folder's manifest ({"sets", "performance_mode"}), or None
    relevant_hash(deployed, names)
                                the hash of the deployed files whose card is one of names, or
                                "none" (section 4.2); deployed is ensure_deployed's answer
    overlay_index(index)        install.script_index() with the deployed scripts in place of
                                Forge's (section 6.3)
    stale()                     the cards whose override doesn't fit the installed Forge's script
    status()                    {"deployed": [cards], "stale": [cards], "hash"} of the real folder
                                (install.status()'s "overrides")
    make(sets=None)             the sets' files made again from Forge's cardsfolder.zip
    check()                     what's wrong with the sets (the overrides check command), or []

The upstream check: a file whose "upstream_sha256" isn't the installed Forge's script for that
card isn't deployed (a Forge upgrade changed it, so the override might hide a fix). Forge's
scripts are read from cardsfolder.zip once per Forge version and build (UPSTREAM_FILE); while
Forge's folder can't be read, what was read for that version is used, and a card never read at
all is "unknown": then nothing in the folder changes, so keys don't change while Forge's folder
is away. The file SHA in the deployed index is engine._file_sha's (CRLF made LF).

This part comes after lists.py and before pilots.py and engine.py (forge/__init__'s order): it
must not import engine at module level."""
import hashlib
import json
import os
import re
import sys
import threading
import time
import zipfile
import zlib
from pathlib import Path

from . import common

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

SETS_DIR = Path(__file__).resolve().parent / "overrides"
SETS_FILE = SETS_DIR / "sets.json"
MANIFEST = "decklab-manifest.json"
LOCK_FILE = "overrides.lock"
UPSTREAM_FILE = "overrides-upstream.json"
USERS = "users"                                         # <data>/forge/users/exp-<12 hex>/
CUSTOM_CARDS = Path("Forge") / "custom" / "cards"      # in a Forge user folder (engine.OVERRIDES)
NO_OVERRIDES = "none"                                   # engine.NO_OVERRIDES
UNREADABLE = "unreadable"                               # engine.UNREADABLE_OVERRIDES
STATUSES = ("adopted", "experiment")
LOCK_WAIT_S = 30                # the longest ensure_deployed waits for another process's deploy
FILE_NAME = re.compile(r"[a-z0-9_]{1,80}\.txt")
SET_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SHA = re.compile(r"[0-9a-f]{64}")


def _file_sha(path):
    """The SHA-256 of a file's bytes with CRLF made LF (engine._file_sha's rule)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _script_name(text):
    """A script's card name: its first "Name:" line (the front face)."""
    return next((line[5:].strip() for line in text.splitlines() if line.startswith("Name:")), None)


# ============================================================ what a folder holds

def deployed_hash(user_dir):
    """The canonical hash of the folder's custom/cards (section 6.4, wave 2's form): every
    regular file at any depth, by its path from custom/cards written with "/", sorted; the
    SHA-256 of "<path>\\0<file SHA-256, CRLF made LF>\\n" for each, joined. NO_OVERRIDES when
    there's no file, UNREADABLE when the folder can't be read. It equals
    engine._overrides(user_dir)."""
    folder = Path(user_dir) / CUSTOM_CARDS
    try:
        files = sorted((p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()))
        if not files:
            return NO_OVERRIDES
        text = "".join(f"{name}\0{_file_sha(folder / name)}\n" for name in files)
    except OSError:
        return UNREADABLE
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deployed_scripts(user_dir):
    """{card name: the script's text} of the folder's custom/cards .txt files (a file without
    a "Name:" line, or one that can't be read, is left out)."""
    folder = Path(user_dir) / CUSTOM_CARDS
    out = {}
    try:
        paths = sorted(p for p in folder.rglob("*.txt") if p.is_file())
    except OSError:
        return out
    for path in paths:
        try:
            text = path.read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        name = _script_name(text)
        if name:
            out[name] = text
    return out


def deployed_index(user_dir):
    """{card name: file SHA-256} of the folder's custom/cards: each .txt file's card is its
    script's "Name:" line. A file without one, or one that can't be read, is left out."""
    folder = Path(user_dir) / CUSTOM_CARDS
    out = {}
    try:
        paths = sorted(p for p in folder.rglob("*.txt") if p.is_file())
    except OSError:
        return out
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        name = _script_name(text)
        if name:
            try:
                out[name] = _file_sha(path)
            except OSError:
                continue
    return out


def relevant_hash(deployed, names):
    """The hash of the deployed files whose card is one of names (section 4.2): the SHA-256 of
    "<card name>\\n<file SHA-256>\\n" for each, sorted by card name; NO_OVERRIDES when there's
    none. deployed is ensure_deployed's answer (or an engine's "deployed"); names are Forge
    names, matched as Forge finds cards (accents stripped, any case)."""
    index = (deployed or {}).get("index") or {}
    wanted = {common.norm(n) for n in names}
    found = sorted((card, sha) for card, sha in index.items() if common.norm(card) in wanted)
    if not found:
        return NO_OVERRIDES
    return hashlib.sha256("".join(f"{card}\n{sha}\n" for card, sha in found).encode("utf-8")).hexdigest()


# ============================================================ the repo's sets

_sets_cache = {}
_sets_lock = threading.Lock()


def _check_sets(data):
    """sets.json's data checked: ValueError (a sentence) for what doesn't fit section 6.1."""
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("sets"), dict):
        raise ValueError("sets.json must be {\"version\": 1, \"forge\": ..., \"sets\": {...}}.")
    cards = {}
    for name, found in data["sets"].items():
        if not SET_NAME.fullmatch(name) or not isinstance(found, dict):
            raise ValueError(f"sets.json's set {name!r} isn't a set.")
        if found.get("status") not in STATUSES:
            raise ValueError(f"sets.json's set {name} has no status of {' or '.join(STATUSES)}.")
        files = found.get("files")
        if not isinstance(files, dict):
            raise ValueError(f"sets.json's set {name} has no files.")
        for file_name, info in files.items():
            where = f"sets.json's {name}/{file_name}"
            if not FILE_NAME.fullmatch(file_name) or not isinstance(info, dict):
                raise ValueError(f"{where} isn't a card script's file.")
            if not isinstance(info.get("card"), str) or not info["card"].strip():
                raise ValueError(f"{where} names no card.")
            if not (info.get("upstream_sha256") == "" or SHA.fullmatch(str(info.get("upstream_sha256")))):
                raise ValueError(f"{where}'s upstream_sha256 isn't a SHA-256.")
            edits = info.get("edits")
            if not isinstance(edits, list) or not edits or not all(
                    isinstance(e, list) and len(e) == 2 and all(isinstance(s, str) for s in e) and e[0]
                    for e in edits):
                raise ValueError(f"{where}'s edits must be a list of [old text, new text].")
            target = info.get("cast_target")
            if target is not None and not (isinstance(target, (int, float)) and 0 <= target <= 1):
                raise ValueError(f"{where}'s cast_target must be a share from 0 to 1, or null.")
            if cards.setdefault((name, info["card"]), file_name) != file_name:
                raise ValueError(f"sets.json's set {name} holds {info['card']} twice.")
    return data


def load_sets():
    """sets.json, checked (section 6.1): read again when its modification time changes.
    ValueError (a sentence) when it can't be read or doesn't fit."""
    try:
        stat = SETS_FILE.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        raise ValueError("Deck Lab's overrides/sets.json can't be read.") from None
    with _sets_lock:
        known = _sets_cache.get(str(SETS_FILE))
        if known and known[0] == stamp:
            return known[1]
    try:
        data = json.loads(SETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"Deck Lab's overrides/sets.json can't be read ({type(e).__name__}).") from None
    _check_sets(data)
    with _sets_lock:
        _sets_cache[str(SETS_FILE)] = (stamp, data)
    return data


def adopted():
    """The names of sets.json's "adopted" sets, in its order."""
    return [name for name, found in load_sets()["sets"].items() if found["status"] == "adopted"]


def _chosen(sets):
    """{card: (set, file name, info)} of the given sets' files: when a card is in two of them,
    the later set wins (experiments list their sets after the adopted ones). ValueError for a
    set sets.json doesn't have."""
    known = load_sets()["sets"]
    out = {}
    for name in sets:
        if name not in known:
            raise ValueError(f"There's no override set called {name}.")
        for file_name, info in known[name]["files"].items():
            out.pop(info["card"], None)             # the later set's goes last, as it wins
            out[info["card"]] = (name, file_name, info)
    return out


# ============================================================ Forge's own scripts (the upstream check)

_upstream_lock = threading.Lock()
_upstream_memory = {}           # {str(DATA_DIR): UPSTREAM_FILE's data}


def _forge_now():
    """(version, build, cardsfolder.zip's path) of the installed Forge, any of them None when
    it can't be told."""
    from . import install, simjar          # install comes after this part
    try:
        forge_dir = Path(common._settings()["forge_dir"])
        name, version = install._find_jar(forge_dir)
    except Exception:           # a bad forge_dir setting: as if Forge couldn't be reached
        return None, None, None
    if name is None:
        return None, None, None
    return version, simjar.forge_build(forge_dir / name), forge_dir / install.SCRIPTS_ZIP


def _upstream_data():
    where = str(common.DATA_DIR)
    with _upstream_lock:
        if where in _upstream_memory:
            return _upstream_memory[where]
    try:
        data = json.loads((common.DATA_DIR / UPSTREAM_FILE).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
            data = {"versions": {}}
    except (OSError, ValueError):
        data = {"versions": {}}
    with _upstream_lock:
        return _upstream_memory.setdefault(where, data)


def _zip_scripts(zip_path, files):
    """{file name: (card name, raw bytes)} of Forge's scripts with those file names in
    cardsfolder.zip (the one in fewer folders when there are two, as install._build_index
    picks). OSError or BadZipFile when it can't be read."""
    best = {}
    with zipfile.ZipFile(zip_path) as z:
        for entry in z.namelist():
            base = entry.rsplit("/", 1)[-1]
            if base in files and (base not in best or entry.count("/") < best[base].count("/")):
                best[base] = entry
        out = {}
        for base, entry in best.items():
            raw = z.read(entry)
            out[base] = (_script_name(raw.decode("utf-8", "replace")), raw)
    return out


def _upstream(wanted, *, remember=True):
    """{card: SHA-256 of the installed Forge's script for it, or None when Forge has none}
    for wanted ({card: file name}), and the cards it can't tell (Forge's scripts can't be read
    and nothing was read for that version before). remember=False does not update caches."""
    version, build, zip_path = _forge_now()
    data = _upstream_data()
    entry = data["versions"].get(version) if version else None
    builds = entry.get("builds") if isinstance(entry, dict) and isinstance(entry.get("builds"), dict) else {}
    known = builds.get(build) if build else None
    known = known if isinstance(known, dict) else {}
    if not remember:
        known = dict(known)
    missing = {card: f for card, f in wanted.items() if card not in known}
    if missing and build and zip_path is not None:
        try:
            found = _zip_scripts(zip_path, set(missing.values()))
        except (OSError, zipfile.BadZipFile, zlib.error):
            found = None
        if found is not None:
            for card, file_name in missing.items():
                name, raw = found.get(file_name, (None, None))
                known[card] = hashlib.sha256(raw).hexdigest() if raw is not None and name == card else None
            if remember:
                _note_upstream(version, build, known)
            missing = {}
    if missing:                 # Forge's scripts can't be read now: what was read for this version
        last = builds.get(entry.get("last")) if isinstance(entry, dict) else None
        last = last if isinstance(last, dict) else {}
        known = {**{card: last[card] for card in missing if card in last}, **known}
    out = {card: known[card] for card in wanted if card in known}
    return out, sorted(card for card in wanted if card not in known)


def _note_upstream(version, build, known):
    data = _upstream_data()
    with _upstream_lock:
        entry = data["versions"].setdefault(version, {"last": build, "builds": {}})
        if not isinstance(entry.get("builds"), dict):
            entry["builds"] = {}
        entry["last"] = build
        entry["builds"][build] = dict(known)
        text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        common._write_atomic(common.DATA_DIR / UPSTREAM_FILE, text)
    except OSError as e:
        common._log(f"Forge's card scripts for the overrides couldn't be noted: {e}")


def _intended(sets, *, remember=True):
    """(files {file name: (source path, card)}, stale [cards], unknown [cards]) for these sets
    after the upstream check."""
    chosen = _chosen(sets)
    wanted = {card: f for card, (_, f, _) in chosen.items()}
    shas, unknown = _upstream(wanted) if remember else _upstream(wanted, remember=False)
    files, stale = {}, []
    for card, (name, file_name, info) in chosen.items():
        if card in unknown:
            continue
        if not info["upstream_sha256"] or shas.get(card) != info["upstream_sha256"]:
            stale.append(card)
            continue
        files[file_name] = (SETS_DIR / name / file_name, card)
    return files, sorted(stale), unknown


def read_only_deployment_problem(user_dir):
    """Why a run would change this folder's overrides, or their intent cannot be confirmed.

    Compare exact relative filenames and bytes with the same upstream-filtered source files
    deployment would use. Never acquire a deploy lock, create folders, or remember upstream.
    """
    user_dir = Path(user_dir)
    try:
        found = manifest(user_dir)
        files, _, unknown = _intended(found["sets"] if found else adopted(), remember=False)
    except (OSError, ValueError):
        return "The intended card-script override sets could not be read; current engine identity is unknown."
    if unknown:
        return "The intended card-script overrides are unknown because Forge's source scripts could not be confirmed."
    try:
        wanted = {name: source.read_bytes() for name, (source, _) in files.items()}
    except (OSError, ValueError):
        return "The intended card-script override sources could not be read; current engine identity is unknown."
    folder = user_dir / CUSTOM_CARDS
    actual = {}

    def unreadable(error):
        raise error

    try:
        try:
            folder.stat()
            exists = True
        except FileNotFoundError:
            exists = False
        for root, _, names in os.walk(folder, onerror=unreadable) if exists else ():
            for name in names:
                path = Path(root) / name
                if path.is_file():
                    actual[path.relative_to(folder).as_posix()] = path.read_bytes()
    except (OSError, ValueError):
        return "The deployed card-script overrides could not be read; current engine identity is unknown."
    if set(actual) != set(wanted):
        return "The deployed card-script override files differ from the intended sets; a simulation would update them."
    if actual != wanted:
        return "The deployed card-script override contents differ from the intended sets; a simulation would update them."
    return None


# ============================================================ deploying

_deploy_lock = threading.Lock()
_logged = set()


def _log_once(text):
    if text not in _logged:
        _logged.add(text)
        common._log(text)


class _FileLock:
    """The cross-process deploy lock (<data>/forge/overrides.lock): an OS lock on its first
    byte, as the slots' (slots.py), taken by this process's threads one at a time."""

    def __enter__(self):
        # Any exception out of here gives both locks back: a thread left holding _deploy_lock
        # (an interrupt in the wait, say) would make every later deploy in this process wait forever.
        _deploy_lock.acquire()
        self.fd = None
        try:
            common.DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.fd = os.open(common.DATA_DIR / LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    if sys.platform == "win32":
                        os.lseek(self.fd, 0, os.SEEK_SET)
                        msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError("another Deck Lab process held the overrides' lock") from None
                    time.sleep(0.05)
        except BaseException:
            if self.fd is not None:
                os.close(self.fd)
            _deploy_lock.release()
            raise

    def __exit__(self, *exc):
        try:
            if sys.platform == "win32":
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self.fd)
        finally:
            _deploy_lock.release()


def _write(folder, files):
    """Make folder hold exactly files ({file name: (source, card)}): a file is written only when
    it differs, and every other file (at any depth) is deleted, then empty folders."""
    folder.mkdir(parents=True, exist_ok=True)
    for file_name, (source, _) in files.items():
        want = source.read_bytes()
        path = folder / file_name
        try:
            same = path.is_file() and path.read_bytes() == want
        except OSError:
            same = False
        if not same:
            common._write_atomic(path, want.decode("utf-8"))
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        rel = path.relative_to(folder).as_posix()
        if path.is_dir():
            try:
                path.rmdir()            # only when empty
            except OSError:
                pass
        elif rel not in files:
            path.unlink()


def deploy(user_dir, sets=None):
    """Copy the files of sets (default: the adopted ones) into user_dir's custom/cards, deleting
    any other file there (section 6.2), under the lock: {"deployed": [cards], "files": {card:
    "<set>/<file>"}, "stale": [cards left out by the upstream check], "unknown": [cards whose
    upstream couldn't be told], "hash"}. When some card's upstream can't be told (Forge's scripts
    can't be read and never were), nothing in the folder changes. ValueError for a set that
    doesn't exist or a sets.json that can't be read."""
    sets = adopted() if sets is None else list(sets)
    with _FileLock():
        return _deploy(Path(user_dir), sets)


def _deploy(user_dir, sets):
    files, stale, unknown = _intended(sets)
    folder = user_dir / CUSTOM_CARDS
    if unknown:
        _log_once(f"Forge's card scripts can't be read, so Deck Lab's overrides in {folder} were left as they "
                  f"are (not known: {', '.join(unknown)}).")
    else:
        try:
            _write(folder, files)
        except OSError as e:
            common._log(f"Deck Lab's card-script overrides couldn't be put in {folder}: {e}")
    for card in stale:
        _log_once(f"Deck Lab's override for {card} doesn't fit this Forge's script, so it isn't used.")
    chosen = {card: (name, f) for card, (name, f, _) in _chosen(sets).items()}
    return {"deployed": sorted(card for _, card in files.values()),
            "files": {card: f"{chosen[card][0]}/{f}" for f, (_, card) in sorted(files.items())},
            "stale": stale, "unknown": unknown, "hash": deployed_hash(user_dir)}


_ensured = {}                   # {str(user_dir): (the stamp ensure_deployed last left it at, answer)}


def _stamp(user_dir, sets):
    """What ensure_deployed's work depends on: the sets, sets.json, the Forge build and the
    folder's files (path, time, size)."""
    version, build, _ = _forge_now()
    folder = Path(user_dir) / CUSTOM_CARDS
    try:
        stat = SETS_FILE.stat()
        files = tuple(sorted((p.relative_to(folder).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                             for p in folder.rglob("*") if p.is_file()))
    except OSError:
        return None
    return (tuple(sets), stat.st_mtime_ns, stat.st_size, version, build, files)


def ensure_deployed(user_dir):
    """Make user_dir's custom/cards hold exactly its intended files (section 6.2), under the
    cross-process lock, and return {"index": deployed_index, "hash": deployed_hash}. The
    intended files: a folder user_dir_for made (it has a MANIFEST) gets exactly its sets; any
    other folder (the real one, common._user_dir()) gets every adopted set; always after the
    upstream check. It writes only what differs, and does nothing at all while nothing it
    depends on has changed, so it's cheap to call often. When sets.json can't be read or the
    lock can't be had, the folder stays as it is (logged)."""
    user_dir = Path(user_dir)
    try:
        found = manifest(user_dir)
        sets = found["sets"] if found else adopted()
        stamp = _stamp(user_dir, sets)
        known = _ensured.get(str(user_dir))
        if stamp is not None and known and known[0] == stamp:
            return dict(known[1])
        with _FileLock():
            _deploy(user_dir, sets)
            answer = {"index": deployed_index(user_dir), "hash": deployed_hash(user_dir)}
            stamp = _stamp(user_dir, sets)
        if stamp is not None:
            _ensured[str(user_dir)] = (stamp, answer)
        return dict(answer)
    except (ValueError, OSError) as e:
        _log_once(f"Deck Lab's card-script overrides couldn't be checked in {user_dir}: {e}")
        return {"index": deployed_index(user_dir), "hash": deployed_hash(user_dir)}


def manifest(user_dir):
    """The MANIFEST of a folder user_dir_for made ({"sets": [...], "performance_mode": bool}),
    or None for any other folder (or one whose manifest can't be read)."""
    try:
        data = json.loads((Path(user_dir) / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sets"), list) \
            or not all(isinstance(s, str) for s in data["sets"]):
        return None
    return {"sets": list(data["sets"]), "performance_mode": data.get("performance_mode") is not False}


def user_dir_for(sets, *, performance_mode=True):
    """The user folder an experiment arm (or the PERFORMANCE_MODE knob) plays in (section 6.2):
    <data>/forge/users/exp-<12 hex of canonical({"sets", "performance_mode"})>/, with its
    MANIFEST written once (the sets in the order given: a later set wins a card both hold).
    ValueError for a set sets.json doesn't have."""
    sets = list(sets)
    known = load_sets()["sets"]
    for name in sets:
        if name not in known:
            raise ValueError(f"There's no override set called {name}.")
    want = {"sets": sets, "performance_mode": bool(performance_mode)}
    folder = common.DATA_DIR / USERS / f"exp-{hashlib.sha256(_canonical(want).encode('ascii')).hexdigest()[:12]}"
    if manifest(folder) != want:
        folder.mkdir(parents=True, exist_ok=True)
        common._write_atomic(folder / MANIFEST, json.dumps(want, indent=1) + "\n")
    return folder


# ============================================================ where the overrides count

def overlay_index(index, user_dir=None):
    """install.script_index()'s index with the deployed cards' scripts (user_dir's, default the
    real user folder's) in place of Forge's: a deployed script's "AI:RemoveDeck:All" decides
    whether the card is in "remove_all" (so adopting "remove" clears Devout Decree's "never
    cast" flag). The index itself isn't changed: a new dict when anything differs."""
    from . import install          # install comes after this part
    scripts = deployed_scripts(common._user_dir() if user_dir is None else user_dir)
    if not scripts or index is None:
        return index
    remove = set(index["remove_all"])
    for text in scripts.values():
        name, _, remove_all = install._read_script(text)
        if not name:
            continue
        card = index["names"].get(common.norm(name), name)
        if remove_all:
            remove.add(card)
        else:
            remove.discard(card)
    if remove == set(index["remove_all"]):
        return index
    return {**index, "remove_all": sorted(remove), "remove_all_set": frozenset(remove)}


def stale():
    """The cards of the adopted sets whose override's upstream_sha256 isn't the installed
    Forge's script's (they aren't deployed)."""
    try:
        return _intended(adopted())[1]
    except ValueError:
        return []


def status(user_dir=None):
    """{"deployed": [cards in the folder], "stale": stale(), "hash": deployed_hash} of user_dir
    (default the real user folder): install.status()'s "overrides"."""
    folder = common._user_dir() if user_dir is None else user_dir
    return {"deployed": sorted(deployed_index(folder)), "stale": stale(), "hash": deployed_hash(folder)}


# ============================================================ making the files

def _apply(card, text, edits):
    """Forge's script text with the edits applied (exact replacements); ValueError naming the
    card when an edit's old text isn't there exactly once."""
    for old, new in edits:
        count = text.count(old)
        if count != 1:
            raise ValueError(f"{card}: an edit's old text is in Forge's script {count} times, not once "
                             f"({old[:60]!r}).")
        text = text.replace(old, new, 1)
    return text


def _forge_scripts(sets):
    """{file name: (card, raw bytes)} of Forge's scripts for every file of these sets.
    ValueError when Forge's cardsfolder.zip can't be read or a script is missing."""
    known = load_sets()["sets"]
    files = {f: info["card"] for name in sets for f, info in known[name]["files"].items()}
    _, _, zip_path = _forge_now()
    if zip_path is None:
        raise ValueError("Forge isn't installed at the folder config.json names.")
    try:
        found = _zip_scripts(zip_path, set(files))
    except (OSError, zipfile.BadZipFile, zlib.error) as e:
        raise ValueError(f"Forge's card scripts can't be read ({type(e).__name__}).") from None
    for file_name, card in files.items():
        if file_name not in found or found[file_name][0] != card:
            raise ValueError(f"{card}: Forge has no script called {file_name}.")
    return {f: (files[f], found[f][1]) for f in files}


def make(sets=None):
    """Make the sets' files (default: every set) again from the installed Forge's
    cardsfolder.zip (section 6.1): each is Forge's script with its edits applied, written to
    overrides/<set>/<file>, and sets.json's upstream_sha256 becomes that script's SHA-256.
    Returns {set: [files written]}. ValueError naming the card when an edit's old text isn't in
    Forge's script exactly once (nothing is written then)."""
    data = load_sets()
    sets = list(data["sets"]) if sets is None else list(sets)
    for name in sets:
        if name not in data["sets"]:
            raise ValueError(f"There's no override set called {name}.")
    scripts = _forge_scripts(sets)
    made = {}
    for name in sets:
        for file_name, info in data["sets"][name]["files"].items():
            card, raw = scripts[file_name]
            made[(name, file_name)] = (_apply(card, raw.decode("utf-8"), info["edits"]),
                                       hashlib.sha256(raw).hexdigest())
    new = json.loads(json.dumps(data))
    out = {}
    for (name, file_name), (text, sha) in made.items():
        path = SETS_DIR / name / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        new["sets"][name]["files"][file_name]["upstream_sha256"] = sha
        out.setdefault(name, []).append(file_name)
    if new != data:
        common._write_atomic(SETS_FILE, json.dumps(new, indent=1, ensure_ascii=False) + "\n")
    return out


def check():
    """What's wrong with the sets, each a sentence ([] when nothing is): sets.json that doesn't
    fit; a file missing from the repo; a file that isn't Forge's script with its edits applied;
    an upstream_sha256 that isn't the installed Forge's script's."""
    try:
        data = load_sets()
    except ValueError as e:
        return [str(e)]
    problems = []
    try:
        scripts = _forge_scripts(list(data["sets"]))
    except ValueError as e:
        scripts = None
        problems.append(str(e))
    for name, found in data["sets"].items():
        for file_name, info in found["files"].items():
            path = SETS_DIR / name / file_name
            card = info["card"]
            try:
                have = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")    # a CRLF checkout reads the same
            except OSError:
                problems.append(f"{card}: overrides/{name}/{file_name} is missing.")
                continue
            if _script_name(have) != card:
                problems.append(f"{card}: overrides/{name}/{file_name} is another card's script.")
            if scripts is None:
                continue
            raw = scripts[file_name][1]
            if hashlib.sha256(raw).hexdigest() != info["upstream_sha256"]:
                problems.append(f"{card} ({name}): Forge's script isn't the one the override was made from, "
                                "so it isn't used (python -m decklab.lib.forge overrides make makes it again).")
                continue
            try:
                want = _apply(card, raw.decode("utf-8"), info["edits"])
            except ValueError as e:
                problems.append(str(e))
                continue
            if want != have:
                problems.append(f"{card}: overrides/{name}/{file_name} isn't Forge's script with its edits.")
    return problems
