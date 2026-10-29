"""The engine a matchup's games are played with (simulation wave 2, the report's R06): what
decides the games Forge plays for a seed, so results of different engines are never pooled.

An engine is described in canonical JSON (keys sorted, no spaces, ASCII), and a matchup's key
is the SHA-256 of its description (wave 2's contract, forge-trial/sim-wave2-contract.md,
"Engine id"):
    id_version        ID_VERSION: this description's own format
    run_version       common.FORGE_RUN_VERSION (2 since wave 2)
    kind              KIND_DECKLAB: DeckLabSim with the card log (a seed for each game, a coin
                      flip for who starts every game, the warm pool); KIND_PLAIN: Forge's own sim
                      (-jar), which runs fall back to when the card log can't be used (no JDK, a
                      Forge version or build not checked yet, a build problem), so a Forge upgrade
                      never stops runs, and its games are never pooled with the card log's
    forge             the engine release (install.engine_forge(), since id_version 3): stock
                      Forge's release ("2.0.15"); a fork build's base release and the hash of
                      the forge-gui/res files it changed ("2.0.15+res.<12 hex>"); a fork build
                      from before AI round 1, its whole build name. Not the fork's commit, so a
                      build whose changes are all off by default keeps the keys (cardlog-check
                      still gates each build)
    format            "Constructed" or "Commander"
    clock_s           the time limit of a game
    seeds             seeds.SCHEME (decklab) or "batch" (plain: one seed a batch, the loser of
                      each game starting the next)
    performance_mode  PERFORMANCE_MODE: Forge's PERFORMANCE_MODE preference, which
                      runner.PREFERENCES turns on (R08)
    game_patches      the ids of the game-changing copies of Forge's classes built into the card
                      log's jar (simjar.card_log()["game_patches"]: only those that fit Forge's
                      jar); [] for plain Forge
    overrides         NO_OVERRIDES, or the SHA-256 of the files in Forge's user folder's
                      custom/cards (OVERRIDES), which Forge loads over its own card scripts
    sides             [card_sha, AI profile, the profile file's SHA-256] for each side, sorted:
                      each list goes with its own profile (A-Reckless v B-Default is not
                      A-Default v B-Reckless)
A side's own id is the SHA-256 of the same description with "side" (its one triple) in place
of "sides": the same list played with the same engine against any opponent.

Wave 3 (id_version 2, forge-trial/sim-wave3-contract.md section 4): a side is its list's pilot
(pilots.py): [card_sha, profile, the profile file's SHA-256], with a fourth element, the sorted
switch list, only when there are switches (side_list), and the sides are sorted with sorted()
on those lists (an ai_sha None sorts first). "overrides" is per matchup: the deployed override
files (overrides.py) whose card is in either list (overrides.relevant_hash of eng["deployed"],
the run's user folder as overrides.ensure_deployed left it), and a side id's only those of its
own list, so adopting a set re-keys only the lists that hold its cards. performance_mode and
game_patches follow config's battery knobs (install._setup). The plain kind's sides record what
plain Forge plays: the pilot's profile when it's one of Forge's, else Default, never switches.
AI round 1 (id_version 3, the ai-r1 contract's D1): "forge" is the engine release above, not
the build name (install.forge_version(), which cardlog-check, the card-log jar and the pool still
go by): two builds with the same base release, the same changed res files and the same game
patches share keys, as the fork's AI switches are off unless a pilot names them (and a pilot's
switches are in its side). Not in the id,
because they were measured not to change games: lazy card loading, warm or fresh JVMs, APC=2,
pinning to a core, the mulligan copy, R14a, below-normal priority, chunk sizes, which worker
played a game.

A result's "engine" is its description without "format" and "sides" (result_fields): the
result keeps its format, and each side its card_sha, "ai", "ai_sha" and "engine_id"
(side_fields), so describe() can put the whole description back together. Results saved
before wave 2 (run_version 1) have no engine: KIND_V1, never pooled with these.

Keys must not change while Forge's folder can't be reached (the page lists results then), so
what was read from it is remembered per Forge version and build in the data folder
(REMEMBERED, as install remembers the version): the AI profiles' SHA-256s, the game patches
that fit the jar, and the engine release ("engine_forge"). today() uses them when the folder or the jar can't be read, value by value:
an AI profile that can't be read now is its remembered SHA-256, a jar that can't be read (an
antivirus scan, a reinstall going on) its remembered game patches, and what couldn't be read is
never remembered over what was; nor is anything read from a jar whose build can't be read.

Three details the contract's text leaves open: an AI profile's SHA-256 is of the file with its
CRLF line endings made LF (a reinstall's line endings don't change what Forge reads); overrides
is UNREADABLE_OVERRIDES when the folder can't be read; and the sides are sorted by their
canonical JSON.

Two kinds, two sets of ids: which kind a run plays flips whenever the card log becomes usable
or not. Win rates follow the current kind (matchup_key(), today() without a kind), so while the
card log is off the page shows the plain engine's result of two lists, and results of the
other kind are labelled "Earlier engine" (is_current() False) until the card log is usable
again. Per-card data only ever comes from the card log, so per-card consumers
(cardstats.list_cards, ai.list_ai) use today's decklab-kind side id (side_ids()) whatever the
card log's state.

    current(setup, card_log, remember=True)
                                    the engine a run plays now (install._setup()'s setup and
                                    simjar.card_log()'s answer): the description's fields
                                    (ENGINE_FIELDS) without format and sides, with "ai" (the
                                    profiles, AI_PROFILES) and "ai_sha" ({profile: SHA-256}) and
                                    "complete" (everything it needs was known), "switches" (the
                                    switches it can play) and "game_patches_on" (the knob)
    today(kind=None)                the same without Java or a build, for pages: the card log's
                                    readiness gives the kind (install.status()), the folder or
                                    what was remembered the rest
    key(entry_a, entry_b, eng)      the matchup key of two lists played with eng
    matchup_key(entry_a, entry_b)   the key a run of them would save under now (today())
    side_list(entry, eng)           an entry's (or a stored side's) side: [card_sha, profile,
                                    its SHA-256] (+ [switches]); side_order(sides) sorts them
    entry_side_id(entry, fmt=None, eng=None)
                                    a list's own side id (default today()'s engine)
    side_ids(card_sha, list_kind, pilot=None, cards=None)
                                    {kind: that list's side id with today's engine of that kind}
    result_fields(eng, entries=None)
                                    {"engine": ...}: what a new result records (runner._record);
                                    with the two entries, "overrides" is the matchup's
    side_fields(eng, side, echo)    what each side records on every run (runner._record): its
                                    engine_id, ai, ai_sha, and the auto-profile flag the run's
                                    DLENGINE line said (echo: LogReader.engine_by_side()'s)
    check_echo(eng, echo, seat_pilots=None)
                                    None when a chunk's DLENGINE fields (LogReader.engine) say it
                                    was played with eng, else why not, in a plain sentence
    launch_fields(setup, eng)       what a warm worker's launch depends on beyond its command
                                    line (wave 3: the pool's launch and compatibility identities)
    is_current(result)              would a run of its two lists now add to it?
    kind_of(result), words(result)  for the page: its kind (KIND_V1 for an old one), and why it
                                    isn't today's engine in a sentence
    auto_profile_flag(side)         a stored side's auto-profile flag for the page (bool, or None
                                    when not known)
    held()                          a block in which today() is worked out once per kind (a
                                    page listing many results asks for each)
This part comes after lists.py and before processes.py (each part imports only those above it)."""
import hashlib
import json
import threading
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path

from . import common, install, overrides, pilots, seeds, simjar
from .common import AI_PROFILES, FORGE_RUN_VERSION, forge_name
from .lists import fmt_for

ID_VERSION = 3                  # AI round 1: "forge" is the engine release (wave 3's was 2, wave 2's 1)
DECK_ORDER = "deck-order-1"     # J3's game patch: the .dck's line order and a load seed (section 3.2)
KIND_DECKLAB = "decklab"        # DeckLabSim, with the card log (v2: per-game seeds, the warm pool)
KIND_PLAIN = "plain"            # Forge's own sim (-jar), when the card log can't be used
KIND_V1 = "v1"                  # a result saved before wave 2 (run_version 1, no engine of its own)
PLAIN_SEEDS = "batch"           # the plain engine's seeds: one a batch, the loser of each game starting the next
PERFORMANCE_MODE = True         # Forge's PERFORMANCE_MODE preference (runner.PREFERENCES), R08
NO_OVERRIDES = "none"
UNREADABLE_OVERRIDES = "unreadable"     # the overrides folder couldn't be read: no key of today's can be told
OVERRIDES = Path("Forge") / "custom" / "cards"      # in Forge's user folder: card scripts loaded over Forge's
AI_FOLDER = Path("res") / "ai"                      # in Forge's folder: <profile>.ai
REMEMBERED = "engine.json"      # in DATA_DIR: what was read from Forge's folder, per version and build
# The description's fields a result keeps as its "engine" (without "format" and "sides").
ENGINE_FIELDS = ("id_version", "run_version", "kind", "forge", "clock_s", "seeds", "performance_mode",
                 "game_patches", "overrides")

V1_WORDS = ("Played with Deck Lab's first engine, before 2026-10-03: one seed for each batch of games, and the "
            "loser of each game went first in the next. Playing more starts a new result with today's engine.")
PLAIN_WORDS = ("Played with plain Forge, as the card log can't be used on this PC now: these games are kept apart "
               "from games played with the card log, and have no per-card numbers.")
EARLIER_WORDS = "Played with an earlier engine ({what}). Playing more starts a new result with today's engine."


def _canonical(value):
    """value as canonical JSON: keys sorted, no spaces, ASCII."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(value):
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _file_sha(path):
    """The SHA-256 of a text file's bytes with CRLF made LF (a reinstall's line endings don't
    change what Forge reads). OSError when it can't be read."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ============================================================ what Forge's folders hold

_lock = threading.Lock()
_ai_cache = {}          # {path: ((mtime_ns, size), sha)}
_override_cache = {}    # {folder: (stamp of its files, sha)}
_jar_cache = {}         # {path: (size, mtime_ns)} of Forge jars read whole
_memory = {}            # {str(DATA_DIR): REMEMBERED's data}


def _ai_sha(forge_dir, name):
    """The SHA-256 of Forge's AI profile <forge_dir>/res/ai/<name>.ai, or None when it can't
    be read (a made-up Forge folder). Kept while the file's time and size stay the same."""
    path = Path(forge_dir) / AI_FOLDER / f"{name}.ai"
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        with _lock:
            known = _ai_cache.get(str(path))
        if known and known[0] == stamp:
            return known[1]
        sha = _file_sha(path)
    except OSError:
        return None
    with _lock:
        _ai_cache[str(path)] = (stamp, sha)
    return sha


def _overrides(user_dir):
    """NO_OVERRIDES when Forge's user folder has no files in custom/cards (OVERRIDES), else the
    SHA-256 of each file's path (from that folder, with "/") and SHA-256, one per line, in
    path order: Forge loads every one of them over its own card scripts. Deck Lab owns the
    folder (runner._prepare_user_dir); nothing puts files there yet (wave 3's R10 will). A
    folder that can't be listed or read is UNREADABLE_OVERRIDES, so no key claims to know what's
    in it."""
    folder = Path(user_dir) / OVERRIDES
    try:
        files = sorted((p for p in folder.rglob("*") if p.is_file()), key=lambda p: p.relative_to(folder).as_posix())
        stamp = tuple((p.relative_to(folder).as_posix(), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    except OSError:
        return UNREADABLE_OVERRIDES
    if not files:
        return NO_OVERRIDES
    with _lock:
        known = _override_cache.get(str(folder))
    if known and known[0] == stamp:
        return known[1]
    try:
        text = "".join(f"{name}\0{_file_sha(folder / name)}\n" for name, _, _ in stamp)
    except OSError:
        return UNREADABLE_OVERRIDES
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _lock:
        _override_cache[str(folder)] = (stamp, sha)
    return sha


def _jar_readable(jar):
    """Can Forge's jar be read now: its files listed, and its list of Deck Lab's changes
    (simjar.FORGE_PATCH_LIST) read when it has one, as simjar.forge_patches() reads it? Kept while
    the jar's size and time stay the same; a jar that can't be read is tried again next time."""
    path = str(jar)
    try:
        stat = Path(jar).stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
        with _lock:
            if _jar_cache.get(path) == stamp:
                return True
        with zipfile.ZipFile(jar) as z:
            if simjar.FORGE_PATCH_LIST in set(z.namelist()):
                z.read(simjar.FORGE_PATCH_LIST)
    except (OSError, EOFError, zipfile.BadZipFile, zlib.error):
        return False
    with _lock:
        _jar_cache[path] = stamp
    return True


def _jar_patches(jar):
    """The ids of the game-changing changes in Forge's jar (sorted), or None when the jar can't
    be read: simjar.forge_patches() finds none in a jar it can't read, which isn't the same as a
    jar without any (_jar_readable tells them apart)."""
    patches = simjar.forge_patches(jar)
    if not patches:
        if not _jar_readable(jar):
            return None
        patches = simjar.forge_patches(jar)         # again, now that it can be read: none, or it just couldn't
    return sorted(set(simjar.game_patch_ids(patches).values()))     # several classes may share an id


def _remembered():
    """REMEMBERED's data for this data folder: {"versions": {version: {"last": build,
    "builds": {build: {"ai": {profile: sha | None}, "game_patches": [ids], "engine_forge":
    release}}}}}, build being the
    jar's (simjar.forge_build). Read once per process; {"versions": {}} when there's none (or it
    can't be read)."""
    where = str(common.DATA_DIR)
    with _lock:
        if where in _memory:
            return _memory[where]
    try:
        data = json.loads((common.DATA_DIR / REMEMBERED).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
            data = {"versions": {}}
    except (OSError, ValueError):
        data = {"versions": {}}
    with _lock:
        return _memory.setdefault(where, data)


def _recall(version, build=None):
    """What was read from Forge's folder for this version: its build's when that build is
    known, else its last build's: {"ai", "game_patches", "engine_forge"} (any may be missing), or
    {}."""
    entry = _remembered()["versions"].get(version)
    if not isinstance(entry, dict) or not isinstance(entry.get("builds"), dict):
        return {}
    found = entry["builds"].get(build) if build is not None else None
    if not isinstance(found, dict):
        found = entry["builds"].get(entry.get("last"))
    return found if isinstance(found, dict) else {}


def _remember(version, build, ai=None, game_patches=None, engine_forge=None):
    """Note what was read from Forge's folder for this version and build (in memory, and in
    REMEMBERED when it's new), for today() while the folder can't be read. ai is {profile:
    SHA-256 or None}: a None (a profile that couldn't be read) never takes the place of a
    SHA-256 that was read; game_patches None (the jar couldn't be read) leaves the remembered
    ones, and so does engine_forge None (the build file couldn't be read). Nothing is noted for a build that can't be read (build None): the jar may be one
    being replaced, so what it gave isn't one build's for sure."""
    if not version or not build:
        return
    data = _remembered()
    with _lock:
        entry = data["versions"].get(version)
        if not isinstance(entry, dict) or not isinstance(entry.get("builds"), dict):
            entry = data["versions"][version] = {"last": build, "builds": {}}
        known = entry["builds"].get(build)
        if not isinstance(known, dict):
            known = entry["builds"][build] = {}
        before = _canonical([entry.get("last"), known])
        entry["last"] = build
        if ai is not None:
            noted = known.get("ai") if isinstance(known.get("ai"), dict) else {}
            known["ai"] = {**noted, **{name: sha for name, sha in ai.items()
                                       if sha is not None or noted.get(name) is None}}
        if game_patches is not None:
            known["game_patches"] = sorted(game_patches)
        if engine_forge is not None:
            known["engine_forge"] = engine_forge
        changed = _canonical([entry["last"], known]) != before
        text = json.dumps(data, indent=1, sort_keys=True) + "\n" if changed else None
    if text is None:
        return
    try:
        common._write_atomic(common.DATA_DIR / REMEMBERED, text)
    except OSError as e:
        common._log(f"What Forge's folder holds for the matchup keys couldn't be noted: {e}")


# ============================================================ the engine now

def _engine(kind, version, clock_s, game_patches, deployed, ai_sha, complete, performance_mode=PERFORMANCE_MODE):
    """An engine's dict: the description's fields (ENGINE_FIELDS; "overrides" the user folder's
    whole deployed hash, which a matchup's key narrows to its two lists'), "ai" and "ai_sha",
    "complete", and "deployed" ({"user_dir", "index", "hash"}: the user folder's override
    files, which key(), side ids and launch_fields read; not part of the description)."""
    return {"id_version": ID_VERSION, "run_version": FORGE_RUN_VERSION, "kind": kind, "forge": version,
            "clock_s": int(clock_s), "seeds": seeds.SCHEME if kind == KIND_DECKLAB else PLAIN_SEEDS,
            "performance_mode": bool(performance_mode),
            "game_patches": sorted(game_patches) if kind == KIND_DECKLAB else [],
            "overrides": deployed["hash"], "ai": list(AI_PROFILES), "ai_sha": dict(ai_sha), "complete": complete,
            "deployed": deployed}


def _deployed(user_dir, answer=None):
    """eng["deployed"] for a user folder: {"user_dir", "index", "hash"} from answer
    (overrides.ensure_deployed's) or read now. A folder that can't be read is
    UNREADABLE_OVERRIDES, as _overrides() says."""
    if answer is None:
        answer = {"index": _deployed_index(user_dir), "hash": _overrides(user_dir)}
    return {"user_dir": str(user_dir), "index": dict(answer["index"]), "hash": answer["hash"]}


_index_cache = {}       # {folder: (stamp of its files, deployed index)}


def _deployed_index(user_dir):
    """overrides.deployed_index(user_dir), kept while the folder's files (path, time, size)
    stay the same: pages ask for it with every key (matchup_key never deploys)."""
    folder = Path(user_dir) / OVERRIDES
    try:
        stamp = tuple(sorted((p.relative_to(folder).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                             for p in folder.rglob("*") if p.is_file()))
    except OSError:
        return {}
    with _lock:
        known = _index_cache.get(str(folder))
    if known and known[0] == stamp:
        return dict(known[1])
    index = overrides.deployed_index(user_dir)
    with _lock:
        _index_cache[str(folder)] = (stamp, index)
    return dict(index)


def _knobs(settings):
    """(performance_mode, game_patches) from config's battery knobs (forge_performance_mode,
    forge_game_patches): True unless set to false."""
    return settings.get("forge_performance_mode", True) is not False, settings.get("forge_game_patches", True) is not False


def _forge_profile_names(forge_dir):
    """The names of the AI profiles in Forge's res/ai (wave 3: a pilot may name any of them),
    [] when the folder can't be listed."""
    try:
        return [p.stem for p in (Path(forge_dir) / AI_FOLDER).glob("*.ai") if p.is_file()]
    except OSError:
        return []


def _read_ai(forge_dir, known):
    """({profile: SHA-256 or None} as read from Forge's folder now, {profile: SHA-256} for the
    key): a profile that can't be read now is its SHA-256 in known (_recall's), if any. Every
    profile in Forge's res/ai is read (wave 3's pilots), with AI_PROFILES' and those known."""
    noted = known.get("ai") if isinstance(known.get("ai"), dict) else {}
    names = set(AI_PROFILES) | set(_forge_profile_names(forge_dir)) | set(noted)
    read = {name: _ai_sha(forge_dir, name) for name in sorted(names)}
    return read, {name: sha if sha is not None else noted.get(name) for name, sha in read.items()}


def _noted_release(known):
    """The engine release in known (_recall's), or None when none was noted."""
    found = known.get("engine_forge")
    return found if isinstance(found, str) and found else None


CANT_KEY = ("Forge's decklab-build.txt can't be read and Deck Lab doesn't remember this build's engine, so this run "
            "wasn't started.")


def current(setup, card_log, remember=True):
    """The engine a run with this setup (install._setup()) and card log (simjar.card_log()'s
    answer) plays: KIND_DECKLAB when the card log is ready (with its jar's game patches), else
    KIND_PLAIN. What it reads of Forge's folder is remembered (today()); an AI profile it can't
    read is the one remembered for this build.
    AI round 1: "forge" is setup["engine_forge"] (install.engine_forge, worked out here for a
    setup without it), else the one remembered for this version and build; ForgeError (CANT_KEY)
    when neither is known, never the build name cut down. "switches" is what a pilot may name in
    this run (the card log's "pilot_switches"; [] for plain Forge; left out when the card log
    doesn't say), and "game_patches_on" is the forge_game_patches knob (pilots.check_switches).
    remember False (engine-check, playing an install that isn't config's) notes nothing in
    REMEMBERED.
    Wave 3: "performance_mode" is setup's (config's knob), "game_patches" [] when
    setup["game_patches"] is False, and "deployed" is the run's user folder (setup["user_dir"])
    as overrides.ensure_deployed leaves it (which it calls: cheap when nothing changed), so the
    key, the side ids and the launch hash are worked out from what a new worker loads."""
    log = card_log or {}
    kind = KIND_DECKLAB if log.get("ready") else KIND_PLAIN
    forge_dir, version = Path(setup["forge_dir"]), setup["version"]
    build = simjar.forge_build(forge_dir / setup["jar"]) if setup.get("jar") else None
    known = _recall(version, build)
    read, ai = _read_ai(forge_dir, known)
    patches = sorted(set(log.get("game_patches") or [])) if kind == KIND_DECKLAB else []
    if "engine_forge" in setup:
        release = setup["engine_forge"]
    else:
        release = install.engine_forge(forge_dir, setup["jar"]) if setup.get("jar") else None
    if remember:
        _remember(version, build, read, patches if kind == KIND_DECKLAB else None, release)
    if release is None:
        release = _noted_release(known)
        if release is None:
            raise common.ForgeError(CANT_KEY)
    if setup.get("game_patches") is False:      # the forge_game_patches knob: Forge's own code for every copy
        patches = []
    deployed = _deployed(setup["user_dir"], overrides.ensure_deployed(setup["user_dir"]))
    eng = _engine(kind, release, setup["clock_s"], patches, deployed, ai, True,
                  setup.get("performance_mode", PERFORMANCE_MODE) is not False)
    if kind != KIND_DECKLAB:
        eng["switches"] = []
    elif "pilot_switches" in log:
        eng["switches"] = sorted(log["pilot_switches"])
    eng["game_patches_on"] = setup.get("game_patches") is not False
    return eng


_held = threading.local()


@contextmanager
def held():
    """A block in which today() works its answer out once per kind (and the card log's
    readiness once): views.results() lists many results, each asking whether it's today's.
    Only this thread's calls share it; a block inside another one is part of it."""
    if getattr(_held, "memo", None) is not None:
        yield
        return
    _held.memo = {}
    try:
        yield
    finally:
        _held.memo = None


def _noted_patches(known):
    """The game patches in known (_recall's), or None when none were noted."""
    found = known.get("game_patches")
    return found if isinstance(found, list) else None


def _todays_kind():
    """KIND_DECKLAB when runs can use the card log now (install.status(), which builds
    nothing), else KIND_PLAIN."""
    return KIND_DECKLAB if install.status()["card_log"]["ready"] else KIND_PLAIN


def today(kind=None, *, read_only=False):
    """The engine a run would play now (as current() gives it), worked out without Java or a
    build: of kind, or (None) the kind the card log's readiness says (_todays_kind). Forge's
    version is install.forge_version(), and "forge" the engine release (install.engine_forge);
    while Forge's folder can't be read, the AI profiles' SHA-256s, the game patches and the
    engine release are what was last read for that version (REMEMBERED), and "complete" is
    False when nothing was (or no Forge was ever found), or the release isn't known. With the folder there,
    each value that can't be read now (an AI profile, the jar's game patches) is the one
    remembered for the jar's build (or the version's last build), and isn't remembered itself.
    Wave 3: config's knobs give performance_mode and game_patches as install._setup() does, and
    "deployed" is the run user folder's (install._run_user_dir) override files as they are now:
    this never deploys (install.status(), which the kind asks, does).

    read_only=True requires an explicit kind and retains the same engine-release/key
    semantics without remembering metadata or creating/deploying a run folder. An
    unconfirmed existing deployment yields complete=False and identity_problem; it
    never borrows the normal held memo or silently uses the real performance folder.
    """
    if read_only and kind not in (KIND_DECKLAB, KIND_PLAIN):
        raise ValueError("A read-only engine identity needs an explicit engine kind.")
    memo = None if read_only else getattr(_held, "memo", None)
    if memo is not None and kind in memo:
        return memo[kind]
    asked = kind
    if kind is None:
        kind = _todays_kind()
        if memo is not None and kind in memo:
            memo[None] = memo[kind]
            return memo[kind]
    settings = common._settings()
    version = install.forge_version(remember=False) if read_only else install.forge_version()
    try:
        forge_dir = Path(settings["forge_dir"])
        name, found = install._find_jar(forge_dir)
    except Exception:           # a bad forge_dir setting: as if it couldn't be reached
        forge_dir, name, found = None, None, None
    if version is not None and found == version:
        jar = forge_dir / name
        build = simjar.forge_build(jar)
        known = _recall(version, build)
        read, ai = _read_ai(forge_dir, known)
        read_patches = _jar_patches(jar)
        release = install.engine_forge(forge_dir, name)
        if not read_only:
            _remember(version, build, read, read_patches, release)
        patches = read_patches if read_patches is not None else _noted_patches(known)
        release = release if release is not None else _noted_release(known)
        complete = release is not None and (kind != KIND_DECKLAB or patches is not None)
    else:
        known = _recall(version) if version else {}
        ai = known.get("ai") if isinstance(known.get("ai"), dict) else {}
        patches = _noted_patches(known)
        release = _noted_release(known)
        complete = (version is not None and "ai" in known and release is not None
                    and (kind != KIND_DECKLAB or patches is not None))
    performance_mode, patches_on = _knobs(settings)
    if read_only:
        user_dir = _read_only_user_dir(performance_mode)
        deployed = (_deployed(user_dir) if user_dir is not None else
                    {"user_dir": "", "index": {}, "hash": UNREADABLE_OVERRIDES})
        problem = None if complete else "The current Forge engine identity could not be confirmed."
        if user_dir is None:
            problem = "The expected Forge run folder is not available; planning does not create it."
        elif deployed["hash"] == UNREADABLE_OVERRIDES:
            problem = "The deployed card-script overrides could not be read; current engine identity is unknown."
        else:
            problem = overrides.read_only_deployment_problem(user_dir) or problem
        eng = _engine(kind, release, settings["forge_clock_s"], (patches or []) if patches_on else [],
                      deployed, ai, complete and problem is None, performance_mode)
        if problem:
            eng["identity_problem"] = problem
        return eng
    try:
        user_dir = install._run_user_dir(performance_mode)
    except common.ForgeError:
        # The knob's folder couldn't be made (sets.json unreadable): a page key still gets an
        # answer, from the real folder, which holds the same adopted sets.
        user_dir = common._user_dir()
    eng = _engine(kind, release, settings["forge_clock_s"], (patches or []) if patches_on else [],
                  _deployed(user_dir), ai, complete, performance_mode)
    if memo is not None:
        memo[kind] = eng
        memo[asked] = eng
    return eng


def _read_only_user_dir(performance_mode):
    """The existing run folder, never created or deployed while inspecting rankings."""
    if performance_mode:
        folder = common._user_dir()
        return folder if folder.is_dir() else None
    try:
        want = {"sets": overrides.adopted(), "performance_mode": False}
        folder = common.DATA_DIR / overrides.USERS / f"exp-{_sha(want)[:12]}"
        return folder if folder.is_dir() and overrides.manifest(folder) == want else None
    except (OSError, ValueError):
        return None


def read_only_today():
    """Today's actual engine identity without setup, deployment, builds or persistent writes.

    Readiness is inspected directly; install.status() also deploys overrides and is deliberately
    not used. Existing remembered identities may fill unreadable Forge values, but this call
    never updates them. An absent performance-mode folder is unknown, never the real folder.
    """
    settings = common._settings()
    version = install.forge_version(remember=False)
    try:
        forge_dir = Path(settings["forge_dir"])
        name, found = install._find_jar(forge_dir)
    except (OSError, TypeError, ValueError):
        forge_dir, name, found = None, None, None
    jar = forge_dir / name if forge_dir is not None and name and found == version else None
    java = install.find_java(settings.get("forge_java"))
    usable = jar is not None and java is not None and (forge_dir / install.SCRIPTS_ZIP).is_file()
    ready = simjar.readiness(str(java), version, jar).get("ready") if usable else False
    kind = KIND_DECKLAB if ready else KIND_PLAIN
    if jar is not None:
        build = simjar.forge_build(jar)
        known = _recall(version, build)
        _, ai = _read_ai(forge_dir, known)
        read_patches = _jar_patches(jar)
        patches = read_patches if read_patches is not None else _noted_patches(known)
        complete = kind != KIND_DECKLAB or patches is not None
    else:
        known = _recall(version) if version else {}
        ai = known.get("ai") if isinstance(known.get("ai"), dict) else {}
        patches = _noted_patches(known)
        complete = version is not None and "ai" in known and (kind != KIND_DECKLAB or patches is not None)
    performance_mode, patches_on = _knobs(settings)
    folder = _read_only_user_dir(performance_mode)
    deployed = (_deployed(folder) if folder is not None else
                {"user_dir": "", "index": {}, "hash": UNREADABLE_OVERRIDES})
    problem = None if complete else "The current Forge engine's version or game patches could not be confirmed."
    if folder is None:
        problem = "The expected Forge run folder is not available; ranking reads do not create it."
    elif deployed["hash"] == UNREADABLE_OVERRIDES:
        problem = "The deployed card-script overrides could not be read; current engine identity is unknown."
    else:
        problem = overrides.read_only_deployment_problem(folder) or problem
    complete = complete and folder is not None and deployed["hash"] != UNREADABLE_OVERRIDES
    eng = _engine(kind, version, settings["forge_clock_s"], (patches or []) if patches_on else [],
                  deployed, ai, complete and problem is None, performance_mode)
    if problem:
        eng["identity_problem"] = problem
    return eng


# ============================================================ ids

def _pilot(entry_):
    """The pilot a list plays with ({"profile", "switches"}): its own ("pilot", lists.entry's
    from pilots.pilot_for, or a stored side's), else its "ai" profile (wave 2's sides and
    tests), else the default pilot (pilots.py)."""
    found = entry_.get("pilot")
    if isinstance(found, dict) and found.get("profile"):
        return {"profile": found["profile"], "switches": sorted(found.get("switches") or [])}
    if entry_.get("ai"):
        return {"profile": entry_["ai"], "switches": []}
    return pilots.default_pilot()


def _profile(entry_):
    """The AI profile a list plays with: its pilot's (_pilot)."""
    return _pilot(entry_)["profile"]


def _profile_sha(name, eng):
    """The SHA-256 of the profile file the engine loads for name: Forge's (eng["ai_sha"]), else
    Deck Lab's own (pilots.profile_sha: the repo file, always known), else None."""
    if name in eng["ai_sha"]:
        return eng["ai_sha"][name]
    return pilots.profile_sha(name) if eng["kind"] == KIND_DECKLAB else None


def side_list(entry_, eng):
    """An entry's (or a stored side's) side of the description (section 4.1): [card_sha,
    profile, the profile's SHA-256], with a fourth element, its pilot's sorted switches, only
    when there are any. The plain kind plays what plain Forge can: the pilot's profile when
    it's one of Forge's, else Default, and never switches."""
    pilot = _pilot(entry_)
    name, switches = pilot["profile"], pilot["switches"]
    if eng["kind"] != KIND_DECKLAB:
        if name in pilots.deck_lab_profiles() and name not in eng["ai_sha"]:
            name = AI_PROFILES[0]
        switches = []
    side = [entry_["card_sha"], name, _profile_sha(name, eng)]
    return side + [sorted(switches)] if switches else side


def played_pilot(entry_, eng):
    """The pilot ({"profile", "switches"}) a list really plays with under eng: side_list's, so a
    plain-kind run plays Default in place of a Deck Lab profile and never a switch. Build a
    request's -a and -dlpilot (runner.request_args' pilots) and check_echo's seat_pilots from
    this, not from the entry's own "pilot"."""
    played = side_list(entry_, eng)
    return {"profile": played[1], "switches": played[3] if len(played) > 3 else []}


def _side_order(side):
    """sorted()'s order on side lists, with an ai_sha None (not known) before any SHA-256
    instead of a comparison of None with a string; when the first three are equal, the
    shorter list comes first."""
    sha = side[2]
    return (side[0], side[1], (0, "") if sha is None else (1, sha), len(side), side[3:])


def side_order(sides):
    """The sides sorted as the description sorts them (section 4.1)."""
    return sorted(sides, key=_side_order)


def _fields(eng):
    return {field: eng[field] for field in ENGINE_FIELDS}


def _names(entry_):
    """The Forge names (front faces) of a list's Main and Commander cards: from its "cards"
    (entries and stored sides), else its .dck text."""
    listed = entry_.get("cards")
    if isinstance(listed, dict):
        return {forge_name(name) for section in ("Commander", "Main") for _, name in listed.get(section) or []}
    names, section = set(), None
    for raw in (entry_.get("dck") or "").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.lower() in ("[main]", "[commander]")
            continue
        qty, _, name = line.partition(" ")
        if section and qty.isdigit() and name:
            names.add(forge_name(name.split("|", 1)[0].strip()))
    return names


def _matchup_overrides(eng, entries):
    """The description's "overrides" for these lists (section 4.2): the deployed files
    (eng["deployed"]) whose card is in one of them, overrides.relevant_hash; UNREADABLE when the
    folder couldn't be read. An engine without "deployed" (wave 2's, or a test's) has its own."""
    deployed = eng.get("deployed")
    if not isinstance(deployed, dict):
        return eng["overrides"]
    if deployed.get("hash") == UNREADABLE_OVERRIDES:
        return UNREADABLE_OVERRIDES
    return overrides.relevant_hash(deployed, set().union(*(_names(e) for e in entries)))


def describe(eng, fmt, sides, entries=None):
    """The canonical description: eng's fields, the format and the sides (side_list's each),
    sorted (side_order); with entries (the two lists), "overrides" is theirs (section 4.2)."""
    desc = {**_fields(eng), "format": fmt, "sides": side_order(sides)}
    if entries is not None:
        desc["overrides"] = _matchup_overrides(eng, entries)
    return desc


def key(entry_a, entry_b, eng):
    """The matchup key of entry_a and entry_b (entries, or stored sides: "card_sha", "kind",
    "cards" and the "pilot" or "ai" if they have one) played with eng (64 hex digits): the same
    for (a, b) and (b, a)."""
    return _sha(describe(eng, fmt_for(entry_a["kind"]), [side_list(entry_a, eng), side_list(entry_b, eng)],
                         [entry_a, entry_b]))


def side_id(eng, fmt, side, entry_=None):
    """A side's own id: the description with its one side ("side", side_list's) in place of the
    sides, and, with its entry, the overrides of its own list only."""
    desc = {**_fields(eng), "format": fmt, "side": side}
    if entry_ is not None:
        desc["overrides"] = _matchup_overrides(eng, [entry_])
    return _sha(desc)


def entry_side_id(entry_, fmt=None, eng=None):
    """A list's own side id (section 4.3): its side_list with eng (default today()), in fmt
    (default its kind's format), with its own list's overrides. For per-card consumers and the
    Bradley-Terry players."""
    eng = today() if eng is None else eng
    return side_id(eng, fmt or fmt_for(entry_["kind"]), side_list(entry_, eng), entry_)


def matchup_key(entry_a, entry_b):
    """The key a run of entry_a against entry_b would save under now (today(): no Java needed,
    nor Forge's folder once it has been read). The caller has checked the kinds match."""
    return key(entry_a, entry_b, today())


def _dck_text(card_sha):
    """A list's .dck text from the decks folder (runner writes <card_sha>.dck for every list it
    plays), or None."""
    try:
        return (common._decks_dir() / f"{card_sha}.dck").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def side_ids(card_sha, list_kind, pilot=None, cards=None):
    """{KIND_DECKLAB: id, KIND_PLAIN: id}: a list's side ids with today's engine of each kind
    (list_kind "commander" or "constructed"), for consumers that pool a list's sides across
    results: per-card numbers only ever pool the decklab kind's (the card log's), whatever the
    card log's state now. pilot is the list's (None: the default pilot), and cards the list's
    {"Commander", "Main"} for its overrides (None: read from its .dck file in the decks
    folder; a list never played has none, and no result to find either)."""
    side = {"card_sha": card_sha, "kind": list_kind, "pilot": pilot or pilots.default_pilot()}
    if cards is not None:
        side["cards"] = cards
    else:
        side["dck"] = _dck_text(card_sha) or ""
    out = {}
    for kind in (KIND_DECKLAB, KIND_PLAIN):
        out[kind] = entry_side_id(side, fmt_for(list_kind), today(kind))
    return out


# ============================================================ what results record

def result_fields(eng, entries=None):
    """What a new result records of its engine: {"engine": its fields (ENGINE_FIELDS)}. The
    result's "format" and its sides (side_fields) hold the rest of the description. With
    entries (the two lists), "overrides" is the matchup's (section 4.2), as the key has it."""
    found = _fields(eng)
    if entries is not None:
        found["overrides"] = _matchup_overrides(eng, entries)
    return {"engine": found}


def _auto_profile(echo):
    """{"flag": bool, "avg_cmc": int} from a side's DLENGINE fields, or None without them."""
    flag, cmc = echo.get("autoprofile"), echo.get("avgcmc")
    if flag not in ("0", "1"):
        return None
    try:
        avg = int(cmc)
    except (TypeError, ValueError):
        avg = None
    return {"flag": flag == "1", "avg_cmc": avg}


def auto_profile_flag(side):
    """A stored side's auto-profile flag for the page (views._page_side, the api's matchup
    answer): whether Forge's AI played it as a slower, non-aggro deck in every game (its
    "auto_profile" as side_fields recorded it), None when that isn't known (plain Forge doesn't
    say, nor did runs before wave 2)."""
    found = side.get("auto_profile")
    flag = found.get("flag") if isinstance(found, dict) else None
    return flag if isinstance(flag, bool) else None


def side_fields(eng, side, echo):
    """What a side of a result records of its engine on every run: "engine_id" (its side id),
    "ai" and "ai_sha" (its AI profile and that file's SHA-256), "pilot" ({"profile",
    "switches"} as played: side_list's, so a plain-kind side never claims a pilot it didn't
    use), "deckorder" (whether Forge built its library in the .dck's order, as the DLENGINE
    line said; not recorded without one), and "auto_profile" ({"flag": Forge's AI plays it as a
    slower, non-aggro deck in every game, "avg_cmc": its average mana value, truncated}) when
    the run's DLENGINE line said (echo: {"autoprofile": "0" or "1", "avgcmc": "3",
    "deckorder": "1"}; {} without one, as with plain Forge, which leaves what the side had)."""
    played = side_list(side, eng)
    out = {"engine_id": side_id(eng, fmt_for(side["kind"]), played, side), "ai": played[1], "ai_sha": played[2],
           "pilot": played_pilot(side, eng)}
    found = _auto_profile(echo or {})
    if found is not None:
        out["auto_profile"] = found
    if (echo or {}).get("deckorder") in ("0", "1"):
        out["deckorder"] = echo["deckorder"] == "1"
    return out


def _seat_words(seat_pilots):
    """(the -a profiles, the -dlpilot switches) of seat_pilots as the DLENGINE line says them:
    "Default,Reckless" and "-,team-pump-1"."""
    profiles = ",".join(p.get("profile") or AI_PROFILES[0] for p in seat_pilots)
    switches = ",".join("+".join(sorted(p.get("switches") or [])) or "-" for p in seat_pilots)
    return profiles, switches


def check_echo(eng, echo, seat_pilots=None):
    """None when a chunk's DLENGINE fields (LogReader.engine) say it was played with eng: Forge's
    PERFORMANCE_MODE as eng's, a seed for each game, Deck Lab's game patches on and exactly
    eng's loaded (or off when eng has none: the forge_game_patches knob), the card log on, the
    .dck order and the load seed exactly when eng has deck-order-1, and Forge's user folder's
    overrides as eng["deployed"]'s; else why not, in a plain sentence (the chunk fails). The
    plain engine prints no DLENGINE line: nothing to check.
    seat_pilots (wave 3, sim-wave3-contract.md sections 4.3-4.4): [deck 1's pilot, deck 2's
    pilot] in the chunk's seat order, each {"profile", "switches"}: the echo's "ai" and "pilots"
    must be theirs, seat by seat. None (wave 2's callers) skips those two checks."""
    if eng["kind"] != KIND_DECKLAB:
        return None
    if not echo:
        return "Forge didn't say how it played the games (no DLENGINE line), so they can't be counted."
    perf = "true" if eng["performance_mode"] else "false"
    if echo.get("perf") != perf:
        return (f"Forge's PERFORMANCE_MODE was {'off' if perf == 'true' else 'on'} in these games, so they aren't "
                "the engine's and can't be counted.")
    if echo.get("seeds") != "game":
        return "These games weren't played with a seed each, so they aren't the engine's and can't be counted."
    off = echo.get("gamepatches") == "off" and eng["game_patches"] == []
    if echo.get("gamepatches") != "on" and not off:
        return "Deck Lab's game patches were off in these games, so they aren't the engine's and can't be counted."
    loaded = echo.get("gamepatchids", "")
    # With the knob off, Java still lists the copies its jar holds (GameLoop.gamePatchIds): they
    # play Forge's own code then, so the ids don't count.
    if not off and loaded != ",".join(eng["game_patches"]):
        return (f"Forge loaded other game patches ({loaded or 'none'}) than the engine's "
                f"({', '.join(eng['game_patches']) or 'none'}), so these games can't be counted.")
    if echo.get("cardlog") != "on":
        return "The card log was off in these games, so they can't be counted."
    ordered = DECK_ORDER in eng["game_patches"]
    if echo.get("deckorder") != ("1,1" if ordered else "0,0"):
        return ("Forge didn't build the libraries in the deck files' order in these games, so they can't be counted."
                if ordered else
                "Forge built the libraries in an order the engine doesn't play, so these games can't be counted.")
    if echo.get("loadseed") != ("1" if ordered else "0"):
        return "Forge loaded the decks with another seed than the engine's, so these games can't be counted."
    if seat_pilots is not None:
        profiles, switches = _seat_words(seat_pilots)
        if echo.get("ai") != profiles:
            return (f"Forge's AI played these games with other profiles ({echo.get('ai') or 'none said'}) than the "
                    f"decks' pilots ({profiles}), so they can't be counted.")
        if echo.get("pilots") != switches:
            return (f"Forge's AI played these games with other switches ({echo.get('pilots') or 'none said'}) than "
                    f"the decks' pilots ({switches}), so they can't be counted.")
    deployed = eng.get("deployed")
    want = deployed.get("hash") if isinstance(deployed, dict) else eng["overrides"]
    if echo.get("overrides") != want:
        return "The card-script overrides changed while this run was playing: play it again."
    return None


def launch_fields(setup, eng):
    """What a warm worker's launch depends on beyond its command line (wave 3,
    sim-wave3-contract.md section 4.3): {"overrides": the user folder's deployed hash
    (eng["deployed"]), "user_dir", "aiprofiles": the AI profile folder's hash (its name, the
    first 12 hex digits of it; pilots.profile_folder) or None, "performance_mode",
    "game_patches": False with the forge_game_patches knob off, "decision_log": the card names
    config's forge_decision_log gives (sorted; None for none: AI round 1's decision log, which
    Forge reads once a JVM)}, for the pool's launch and compatibility identities (R)."""
    deployed = eng.get("deployed") if isinstance(eng.get("deployed"), dict) else {}
    folder = setup.get("aiprofiles")
    return {"overrides": deployed.get("hash", eng.get("overrides")), "user_dir": str(setup.get("user_dir")),
            "aiprofiles": Path(folder).name if folder else None, "performance_mode": eng.get("performance_mode"),
            "game_patches": setup.get("game_patches") is not False,
            "decision_log": sorted(setup.get("decision_log") or []) or None}


# ============================================================ results and today's engine

def kind_of(result):
    """A stored result's engine kind: KIND_V1 for one saved before wave 2 (run_version 1, or no
    engine), else its engine's."""
    found = result.get("engine")
    if (result.get("run_version") or 1) < 2 or not isinstance(found, dict):
        return KIND_V1
    return found.get("kind") if found.get("kind") in (KIND_DECKLAB, KIND_PLAIN) else KIND_V1


def stored_key(result, eng):
    """The key a stored result's two sides would have with eng."""
    a, b = result["sides"]
    return key(a, b, eng)


def is_current(result):
    """Would a run of a stored result's two lists now add to it (its key is today's for its
    sides: their lists as stored, "cards", with the pilots the stored sides played)? False for
    a result of before wave 2, None when that can't be told (Forge never found, or nothing known
    of its folder), which the field view and variant tests treat as not current."""
    if kind_of(result) == KIND_V1:
        return False
    eng = today()
    if not eng["complete"]:
        return None
    return stored_key(result, eng) == result["key"]


def _differences(result, now):
    """What differs between a stored result's engine and now (an engine of today()), in words."""
    then = result.get("engine") or {}
    out = []
    if then.get("kind") != now["kind"]:
        out.append("plain Forge, while the card log was off" if then.get("kind") == KIND_PLAIN
                   else "Deck Lab's card log, which can't be used on this PC now")
    if then.get("forge") != now["forge"]:
        out.append(f"Forge {then.get('forge')}, not {now['forge']}")
    if then.get("clock_s") != now["clock_s"]:
        out.append(f"a {then.get('clock_s')}-second time limit, not {now['clock_s']}")
    if then.get("kind") == now["kind"] and then.get("game_patches") != now["game_patches"]:
        out.append("other Deck Lab changes to how Forge plays")
    sides = result.get("sides") or []
    overrides_now = _matchup_overrides(now, sides) if len(sides) == 2 else now["overrides"]
    if then.get("overrides") not in (overrides_now, now["overrides"]):    # a result saved before R's runner records the matchup's
        out.append("other card overrides")
    if any(then.get(field) != now[field] for field in ("id_version", "run_version", "seeds", "performance_mode")) \
            and then.get("kind") == now["kind"]:
        out.append("an older version of Deck Lab's engine")
    shas = {side.get("ai"): side.get("ai_sha") for side in result.get("sides", [])}
    if any(name in now["ai_sha"] and sha != now["ai_sha"][name] for name, sha in shas.items()):
        out.append("another version of Forge's AI profile")
    return out


def words(result, current=None):
    """Why a stored result isn't today's engine, in a sentence for the page, or None when it is
    (current: is_current(result), when the caller has it). A plain-kind result of today's
    engine says the card log is off."""
    kind = kind_of(result)
    if kind == KIND_V1:
        return V1_WORDS
    if current is None:
        current = is_current(result)
    if current is None:
        return None
    if current:
        return PLAIN_WORDS if kind == KIND_PLAIN else None
    what = _differences(result, today())
    return EARLIER_WORDS.format(what="; ".join(what) if what else "settings that have changed since")
