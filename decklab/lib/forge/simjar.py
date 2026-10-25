"""The card log (Milestone 8): DeckLabSim, Forge's sim with one event listener added that
logs every card move (java/decklab/DeckLabSim.java; its header says what it prints), built
into a jar by Deck Lab with the JDK's javac and jar. Since wave 2 the jar is built from every
.java file in java/decklab/ (deck_lab_sources(): DeckLabSim's, GameLoop's, Request's, Seeds',
WarmState's and DeckLabServe's, the warm workers' serve mode), and it is also what the warm
pool runs ("DeckLabSim serve").

Deck Lab's changes to Forge's own classes (Forge's AbstractMulligan without its 100 ms sleep
per mulligan; AiController with each AI decision's eval on a virtual thread; AiAttackController
with its forced-attacker checks run in turn, in attacker order; Match building each library in
its .dck's line order, deck-order-1) are in Forge itself: Deck Lab runs its own build of Forge,
from the fork's decklab branch (github.com/matt439/forge, cloned at C:/VSProjects/forge, whose
decklab/install.py builds and installs it in C:/Tools/forge-decklab). Until 2026-10-11 they were
copies compiled into this jar, ahead of Forge's on the class path, used only when Forge's jar
held the very class files they were copied from. Forge's jar lists them (FORGE_PATCH_LIST,
forge_patches()). Most play the same games. Those that don't (an id in the list, named in the
engine id) play Forge's own code when the JVM is started with -Ddecklab.gamePatches=off
(GAME_PATCHES_OFF). Deck Lab's classes use the fork's hooks (forge.ai.AiSignals,
forge.game.LibraryOrder), so a Forge jar without the list (a stock release) gets no card log
(NOT_FORK), and runs go on with plain Forge.

Wave 3 (forge-trial/sim-wave3-contract.md sections 3.1 and 3.6) adds Deck Lab's own classes for
pilots and start-up (OWN_CLASSES: DeckOrder, Pilots, TeamPumpAi, AiPatches, Startup) and the pilot
switches a request may name (PILOT_SWITCHES; the jar lists them as PILOT_SWITCH_LIST, and
card_log() gives their ids). AI round 1 adds the fork's own AI switches, listed in Forge's jar
(FORK_SWITCH_LIST, fork_switches()): card_log()'s "pilot_switches" holds both kinds.

card_log() is what a run calls: it builds the jar when it's missing or out of date and says
how to start it. readiness() is the cheap check status() makes, without building anything.
The card log is only used with a Forge version it was checked against (it copies part of
Forge's sim and relies on Forge's events): CHECKED, plus the versions that
"python -m decklab.lib.forge cardlog-check" found playing the same games as plain Forge,
recorded in data/forge/cardlog/checked.json. A check that failed is recorded too, and
turns the card log off for that version (one in CHECKED too) until a check passes. A
check counts only for the card log's source it checked (CHECKED_SOURCE, and each
checked.json entry's source_sha256: source_sha256(), the SHA-256 of Deck Lab's Java sources
with line endings made LF, so a Windows checkout's CRLF is the same source): after an edit to
any of them, no version is checked until cardlog-check passes with it. The check plays with
game patches off (GAME_PATCHES_OFF), as plain Forge does, so both play Forge's own code.
R14b's in-order loop is played by v2's card-log on/off leg, which runs with game patches on.
It also has to be the Forge build that was checked: Forge's jar name gives only the release
(each build of the fork is a version of its own: install.forge_version() gives its build), so
the build is read from the jar's manifest (Implementation-Version). When a check names a build
and the jar's build can't be read, the version counts as unchecked. When the card log can't
be used, runs play exactly as before, with plain Forge and no card data, and the problem
says why in a plain sentence.

The jar is built from a stamp: the source's SHA-256, the Forge jar's name, size and time,
Deck Lab's changes in it (forge_patches()) and the ids of those that change games, the pilot
switches (PILOT_SWITCHES) and the javac that builds it. It's
data/forge/cardlog/decklab-sim-<Forge version>-<the stamp's hash>.jar (a cache, never in
git; the hash is the first 12 hex digits of the SHA-256 of the stamp as JSON), with the
stamp beside it (the same name, .json, written once the jar is whole). So a change to any
of them builds a new jar under a new name, and a build never replaces a jar a running
batch uses. The other jars of that Forge version are deleted, best effort, when one is
built or first used in a process: not one a run has started with in the last KEEP_UNUSED
seconds (card_log() touches the jar it gives), and not one a Forge process still has open
(Windows won't delete it). Building takes about a second, under a lock
(cardlog/build.lock, an OS lock), so two runs, here or in another process, never build at
once.

When the jar can't be built or used, card_log() remembers the problem with the stamp it
was for (_failed), and readiness() gives it while the source, the Forge jar and javac are
the same, so status() says why runs go without the card log; the next card_log() tries
again, and forgets it when that works. _failed belongs to one process, so readiness()
also passes over a problem once that jar has been built since, in any process (a
cardlog-check in a terminal while the server waits, say): its stamp file matches and was
written after the problem was met."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path

from . import common

V = "2.0.15-decklab-52387e83f"         # the fork's build installed on 2026-10-20, AI fixes round 1 (install.forge_version())
CHECKED = frozenset({V})                # Forge versions the card log was checked against in code
# The Forge build each of CHECKED was checked with: its jar manifest's Implementation-Version.
CHECKED_BUILDS = {V: V}
# The card log's source each of CHECKED was checked with: its source_sha256(). A test in
# test_forge_simjar holds it to the source, so an edit to Deck Lab's Java fails the tests until
# cardlog-check passes with the edit and this is updated.
CHECKED_SOURCE = {V: "7ea9e41b75193f79d871e9f6f732572d69565913c9ed8715cf1040522e147e43"}
del V
MAIN = "decklab.DeckLabSim"
JAVA = Path(__file__).resolve().parent / "java"     # Deck Lab's Java sources, in folders by package
SOURCE = JAVA / "decklab" / "DeckLabSim.java"
# Deck Lab's changes to Forge's own classes live in Forge itself, on its fork's decklab branch
# (github.com/matt439/forge, cloned at C:/VSProjects/forge; its decklab/install.py installs a
# build). Forge's jar lists them in FORGE_PATCH_LIST, "<class file> <id>" a line: the id names a
# change to the games Forge plays for a seed, the name the v2 engine id records it by (engine.py),
# a new one for every change to what it plays; "-" for one that plays the same games, faster,
# which stays out of the engine id. A game-changing one plays Forge's own code when the JVM is
# started with -Ddecklab.gamePatches=off (GAME_PATCHES_OFF: the v2 card-log check's comparison
# with plain Forge, and every plain-Forge run); the wave 2 contract's "Game-changing patches"
# (forge-trial/sim-wave2-contract.md). card_log() gives the ids ("game_patches"); DeckLabSim's
# DLENGINE line says which of them it found loaded (gamepatchids=, java/decklab/GameLoop.java
# gamePatchIds). An id is GAME_PATCH_ID. A Forge jar without the list isn't the fork's build,
# and the card log doesn't run with it (NOT_FORK): Deck Lab's classes use the fork's hooks.
FORGE_PATCH_LIST = "decklab/forge-patches.txt"     # in Forge's jar (GameLoop.FORGE_PATCH_LIST)
NEUTRAL = "-"                                       # its id for a change that plays the same games
GAME_PATCHES_OFF = "-Ddecklab.gamePatches=off"
GAME_PATCH_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
CLASS_FILE = re.compile(r"[A-Za-z0-9_$/]+\.class")
# Deck Lab's own classes a good jar must hold (javac also writes their inner classes).
SIM_CLASSES = ("decklab/DeckLabSim.class", "decklab/DeckLabSim$CardLog.class", "decklab/DeckLabServe.class",
               "decklab/GameLoop.class", "decklab/Request.class", "decklab/Seeds.class",
               "decklab/WarmState.class")
# Wave 3 (forge-trial/sim-wave3-contract.md section 3.6): Deck Lab's own classes a good jar must
# hold beyond SIM_CLASSES (DeckOrder, Pilots, TeamPumpAi, AiPatches, Startup), and the AI switches
# a pilot may name, each with the class file that plays it ({id: class file}; java/decklab/
# Pilots.java's AVAILABLE must list the same ids). A switch is available when its class is in the
# jar, and Deck Lab's own classes always are (they compile or the build fails). The jar lists the
# ids (PILOT_SWITCH_LIST), the stamp records them, and card_log()["pilot_switches"] gives them,
# sorted.
OWN_CLASSES = ("decklab/DeckOrder.class", "decklab/Pilots.class", "decklab/TeamPumpAi.class",
               "decklab/AiPatches.class", "decklab/Startup.class")
PILOT_SWITCHES = {"team-pump-1": "decklab/TeamPumpAi.class", "aisim-hybrid-1": "decklab/GameLoop.class"}
PILOT_SWITCH_LIST = "decklab/pilot-switches.txt"     # in the jar: the switch ids, one a line, sorted
# AI round 1: the fork's own AI switches (forge.ai.AiSwitches), listed in Forge's jar, "<id> <class
# file>..." a line ("#" starts a comment). Each is off unless a seat's pilot names it (-dlpilot), and
# always off with game patches off. fork_switches() gives the ids; an id is PILOT_SWITCH_ID.
FORK_SWITCH_LIST = "decklab/ai-switches.txt"
PILOT_SWITCH_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")    # runner.PILOT_SWITCH
# Every class a built jar must hold: DeckLabSim's and Deck Lab's own.
CLASSES = SIM_CLASSES + OWN_CLASSES
FOLDER = "cardlog"                      # in DATA_DIR: the jars, their stamps, checked.json, the lock
# The latest check of each version: {"versions": {"<version>": {"when", "games", "build",
# "source_sha256", "failed"}}}. build: the Forge build checked (null: not known);
# source_sha256: the card log's source checked (source_sha256()); failed: true when the
# check failed (left out when it passed).
CHECKED_FILE = "checked.json"
LOCK_FILE = "build.lock"
BUILD_TIMEOUT = 120                     # seconds javac or jar may take (each takes about a second)
LOCK_WAIT = 180                         # seconds to wait for another run's build
KEEP_UNUSED = 24 * 3600                 # seconds an old jar is kept after a run last started with it
VERSION_RE = re.compile(r"[\w.+-]{1,64}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
# What follows "decklab-sim-<Forge version>" in a card-log jar's name: the stamp's hash, or
# what earlier builds used (nothing, or the source's first 8 hex digits).
JAR_TAIL = r"(?:-[0-9a-f]{12}|-[0-9a-f]{8})?\.jar"

NO_JAVA = "Java wasn't found, so the card log can't run."
NO_JDK = "The card log needs a full Java JDK (with javac and jar), and the Java that runs Forge doesn't have them."
NO_FORGE = "Forge can't run, so the card log can't either."
NOT_FORK = ("This Forge isn't Deck Lab's own build (its fork's decklab branch), so the card log can't run "
            "(C:/VSProjects/forge's decklab/install.py installs one).")
CANT_BUILD = "The card log couldn't be built for Forge {version}."
CANT_WRITE = "Deck Lab can't write the card log's files in its data folder."
IN_USE = "Another run had the card log's jar open, so it couldn't be built again (the next run tries again)."
BUSY = "Another run was still building the card log."
NO_MANIFEST = "Forge's jar couldn't be read, so the card log can't start."
NO_SOURCE = "The card log's source can't be read, so the card log can't run."
UNEXPECTED = "The card log couldn't be set up ({what})."
NOT_NOTED = "Deck Lab couldn't note that the card log {what} (its data folder can't be written)."

_built = {}             # {jar path: {"stamp", "add_opens"}}: jars this process built or found good
_builds = {}            # {Forge jar path: (size, mtime_ns, build)}: builds read (about 60 ms each)
_failed = {}            # {jar path: (problem, time.time())}: the last card_log() for that jar (so its stamp) failed
_forge_patches = {}     # {Forge jar path: (size, mtime_ns, {class file: game-patch id or None})}: forge_patches()
_fork_switches = {}     # {Forge jar path: (size, mtime_ns, [ids])}: fork_switches()
_lock = threading.Lock()


def _tool(java, name):
    """The JDK tool beside java.exe (javac.exe, jar.exe), or None when it isn't there (a JRE)."""
    path = Path(java).parent / (f"{name}.exe" if os.name == "nt" else name)
    return path if path.is_file() else None


def unchecked_problem(version):
    """The problem for a Forge version the card log hasn't been checked with."""
    return (f"The card log hasn't been checked with Forge {version} yet "
            f"(python -m decklab.lib.forge cardlog-check does that).")


def failed_problem(version):
    """The problem for a Forge version whose latest check failed: its games differed from
    plain Forge's, or its card logs failed their checks."""
    return (f"The card log failed its last check with Forge {version} "
            f"(python -m decklab.lib.forge cardlog-check checks it again).")


def other_build_problem(version, build, checked):
    """The problem for a Forge jar of a checked version that's another build of it."""
    return (f"This Forge {version} is build {build}, not the {checked} the card log was checked with "
            f"(python -m decklab.lib.forge cardlog-check checks it).")


def unknown_build_problem(version, checked):
    """The problem for a Forge jar of a checked version whose build can't be read."""
    return (f"This Forge {version}'s build can't be read from its jar, so Deck Lab can't tell it's the "
            f"{checked} the card log was checked with (python -m decklab.lib.forge cardlog-check checks it).")


def changed_problem(version):
    """The problem for a Forge version checked with another card-log source."""
    return (f"The card log has changed since it was checked with Forge {version} "
            f"(python -m decklab.lib.forge cardlog-check checks it again).")


def source_sha256(data=None):
    """The SHA-256 (hex) of the card log's source, data (its bytes) or _source_bytes() read
    now, with its line endings made LF first: a Windows checkout or git worktree can have
    CRLF, which javac reads the same. OSError when a source file can't be read."""
    if data is None:
        data = _source_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def deck_lab_sources():
    """Deck Lab's own Java sources: SOURCE (DeckLabSim's) first, then every other .java file
    beside it, by name."""
    others = sorted((path for path in SOURCE.parent.glob("*.java") if path.name != SOURCE.name),
                    key=lambda path: path.name)
    return [SOURCE, *others]


def _source_bytes():
    """The card log's source as one run of bytes: DeckLabSim's (SOURCE); then for each other
    source of deck_lab_sources() a NUL, "decklab/<its file name>", a NUL and its source. With no
    other source, DeckLabSim's alone. OSError when a file can't be read."""
    sources = deck_lab_sources()
    data = sources[0].read_bytes()
    for other in sources[1:]:
        data += b"\0" + f"decklab/{other.name}\0".encode("utf-8") + other.read_bytes()
    return data


def _parse_patch_list(text):
    """{class file: game-patch id, or None for a neutral one} from FORGE_PATCH_LIST's text,
    sorted by class file; lines that aren't "<class file> <id>" are passed over ("#" starts a
    comment)."""
    patches = {}
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) != 2 or not CLASS_FILE.fullmatch(parts[0]):
            continue
        if parts[1] == NEUTRAL:
            patches[parts[0]] = None
        elif GAME_PATCH_ID.fullmatch(parts[1]):
            patches[parts[0]] = parts[1]
    return dict(sorted(patches.items()))


def forge_patches(forge_jar):
    """Deck Lab's changes in this Forge jar, from its FORGE_PATCH_LIST: {class file: game-patch
    id, or None for a neutral one}, sorted by class file; {} for a jar without the list (not the
    fork's build), or for one that can't be read, which isn't kept, so the next call reads it
    again. Kept while the jar's size and time stay the same. Never raises."""
    try:
        stat = Path(forge_jar).stat()
    except OSError:
        return {}
    path = str(forge_jar)
    known = _forge_patches.get(path)
    if known is not None and known[:2] == (stat.st_size, stat.st_mtime_ns):
        return dict(known[2])
    try:
        with zipfile.ZipFile(forge_jar) as z:
            try:
                text = z.read(FORGE_PATCH_LIST).decode("utf-8")
            except KeyError:
                text = ""
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as e:
        common._log(f"Deck Lab's changes can't be read from Forge's jar ({forge_jar}): {e!r}")
        return {}
    found = _parse_patch_list(text)
    _forge_patches[path] = (stat.st_size, stat.st_mtime_ns, found)
    return dict(found)


def _parse_switch_list(text):
    """The switch ids in FORK_SWITCH_LIST's text, sorted and distinct: each line's first word, when
    it's PILOT_SWITCH_ID ("#" starts a comment)."""
    ids = set()
    for line in text.splitlines():
        parts = line.split("#", 1)[0].split()
        if parts and PILOT_SWITCH_ID.fullmatch(parts[0]):
            ids.add(parts[0])
    return sorted(ids)


def fork_switches(forge_jar):
    """The fork's AI switches in this Forge jar (FORK_SWITCH_LIST), sorted: [] for a jar without
    the list (a build from before AI round 1, or stock Forge) or one that can't be read, which
    isn't kept, so the next call reads it again. Kept while the jar's size and time stay the
    same. Never raises."""
    try:
        stat = Path(forge_jar).stat()
    except OSError:
        return []
    path = str(forge_jar)
    known = _fork_switches.get(path)
    if known is not None and known[:2] == (stat.st_size, stat.st_mtime_ns):
        return list(known[2])
    try:
        with zipfile.ZipFile(forge_jar) as z:
            try:
                text = z.read(FORK_SWITCH_LIST).decode("utf-8")
            except KeyError:
                text = ""
    except (OSError, EOFError, zipfile.BadZipFile, UnicodeDecodeError) as e:
        common._log(f"The AI switches can't be read from Forge's jar ({forge_jar}): {e!r}")
        return []
    found = _parse_switch_list(text)
    _fork_switches[path] = (stat.st_size, stat.st_mtime_ns, found)
    return list(found)


def game_patch_ids(patches):
    """{class file: id} of the game-changing ones among patches (forge_patches()'s)."""
    return {name: pid for name, pid in sorted(patches.items()) if pid is not None}


def _classes():
    """What a good card-log jar holds: DeckLabSim's classes and Deck Lab's own (CLASSES)."""
    return CLASSES


def pilot_switch_ids():
    """The pilot switches a card-log jar holds, sorted: every one of PILOT_SWITCHES, as each
    plays from one of Deck Lab's own classes (a build without one fails)."""
    return sorted(PILOT_SWITCHES)


def _tools_problem(java):
    """Why the card log can't be built with this java (none, or a JRE), or None."""
    if not java:
        return NO_JAVA
    if _tool(java, "javac") is None or _tool(java, "jar") is None:
        return NO_JDK
    return None


def _checked_problem(version, forge_jar=None, source=None):
    """Why the card log isn't used with this Forge version, or None: it was never checked,
    it was checked with another card-log source (source: the current one's
    source_sha256(); None: read it now), its latest check failed, or (given the Forge
    jar's path) the jar is another build than the one checked, or one whose build can't be
    read when the check names a build."""
    if source is None:
        try:
            source = source_sha256()
        except OSError as e:
            common._log(f"The card log's source can't be read: {e}")
            return NO_SOURCE
    check = _checks(source).get(version)
    if check is None:
        return unchecked_problem(version)
    if check["source"] != source:
        return changed_problem(version)
    if not check["ok"]:
        return failed_problem(version)
    if check["build"] is not None and forge_jar is not None:
        build = forge_build(forge_jar)
        if build is None:
            return unknown_build_problem(version, check["build"])
        if build != check["build"]:
            return other_build_problem(version, build, check["build"])
    return None


def readiness(java, version, forge_jar=None):
    """{"ready": bool, "problem": str | None}, without building anything: the JDK's javac
    and jar are beside java, and the card log's source as it is now was checked with this
    Forge version; given the Forge jar's path, also with this build of it, and the last
    card_log() in this process for this source, Forge jar and javac didn't fail, or that
    jar has been built since (when one did fail: a stat of the Forge jar, and of the jar
    and its stamp file, which is read when it's newer than the failure). Never raises."""
    try:
        problem = _tools_problem(java)
        if problem is None:
            try:
                source = source_sha256()
            except OSError as e:
                common._log(f"The card log's source can't be read: {e}")
                return {"ready": False, "problem": NO_SOURCE}
            problem = ((NOT_FORK if forge_jar is not None and not forge_patches(forge_jar) else None)
                       or _checked_problem(version, forge_jar, source)
                       or _last_failure(java, version, forge_jar, source))
        return {"ready": problem is None, "problem": problem}
    except Exception as e:      # never raises: status() calls it
        common._log(f"The card log's readiness couldn't be checked: {e!r}")
        return {"ready": False, "problem": UNEXPECTED.format(what=type(e).__name__)}


def _last_failure(java, version, forge_jar, source):
    """The problem the last card_log() in this process met for the jar these would build
    (_failed), or None: none failed, there's no Forge jar path or it can't be read, or that
    jar has been built since, in this process or another (_built_since)."""
    if forge_jar is None or not _failed:
        return None
    try:
        stat = Path(forge_jar).stat()
    except OSError:
        return None
    stamp = _stamp(_tool(java, "javac"), forge_jar, stat, source, forge_patches(forge_jar))
    jar = _jar_path(version, stamp)
    failed = _failed.get(str(jar))
    if failed is None:
        return None
    problem, when = failed
    return None if _built_since(jar, stamp, when) else problem


def _built_since(jar, stamp, when):
    """Was the jar built after when (a time.time())? Its stamp file matches stamp and was
    written after when, and the jar is there: the stamp file is written only once the jar
    is whole. A problem met after the jar was built (Forge's manifest that can't be read,
    say) isn't passed over, as that stamp file is older than the problem. False when
    either file can't be read."""
    stamp_file = jar.with_suffix(".json")
    try:
        if stamp_file.stat().st_mtime <= when or not jar.is_file():
            return False
        return json.loads(stamp_file.read_text(encoding="utf-8")) == stamp
    except (OSError, ValueError):
        return False


def _stamp(javac, forge_jar, stat, source, patches):
    """What a card-log jar is built from: the card log's source (its source_sha256()),
    the Forge jar (its name, and stat's size and time), Deck Lab's changes in it
    (forge_patches()) and the ids of those that change games (game_patch_ids()), the pilot
    switches (pilot_switch_ids(): listed as PILOT_SWITCH_LIST), the fork's AI switches in
    Forge's jar (fork_switches()) and javac. The changes are named, though the jar's size and
    time would do, so a jar's stamp says what it plays."""
    return {"source_sha256": source,
            "forge_jar": {"name": Path(forge_jar).name, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
            "patches": sorted(patches),
            "game_patches": game_patch_ids(patches),
            "pilot_switches": pilot_switch_ids(),
            "fork_switches": fork_switches(forge_jar),
            "javac": str(javac)}


def jar_file(version, stamp):
    """The card-log jar's file name for a Forge version and a _stamp(): its hash is the
    first 12 hex digits of the SHA-256 of the stamp as JSON (keys sorted)."""
    text = json.dumps(stamp, sort_keys=True, separators=(",", ":"))
    return f"decklab-sim-{version}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}.jar"


def _jar_path(version, stamp):
    """Where the card-log jar for a Forge version and a _stamp() goes."""
    return common.DATA_DIR / FOLDER / jar_file(version, stamp)


def card_log(java, forge_dir, jar_name, version, *, checking=False):
    """How to start Forge with the card log: {"ready": True, "jar": the card-log jar's
    absolute path, "main": MAIN, "add_opens": ["--add-opens", "<module/package>=ALL-UNNAMED",
    ...], "game_patches": [the ids of the game-changing changes in Forge's jar, sorted:
    those in Forge's jar's FORGE_PATCH_LIST, each once; what the v2 engine id records],
    "pilot_switches": [the pilot switches the jar holds and the fork's AI switches in Forge's
    jar, sorted]}, building
    the jar first when it's missing or out of date; or {"ready": False,
    "problem": a plain sentence} when it can't be used. checking (cardlog-check) builds it
    whatever the checks of this Forge version, build and source say. A problem met building
    or using the jar is remembered for readiness() (_failed) until a call for the same jar
    works; readiness() passes over it once that jar has been built since, here or in
    another process. Never raises: details are logged."""
    jar = None
    try:
        forge_jar = Path(forge_dir) / jar_name
        problem = _tools_problem(java)
        if problem:
            return {"ready": False, "problem": problem}
        javac, jar_tool = _tool(java, "javac"), _tool(java, "jar")
        try:
            stat = forge_jar.stat()
            source = source_sha256()
        except OSError as e:
            common._log(f"The card log's source or Forge's jar can't be read: {e}")
            return {"ready": False, "problem": CANT_BUILD.format(version=version)}
        patches = forge_patches(forge_jar)
        if not patches:
            return {"ready": False, "problem": NOT_FORK}
        problem = None if checking else _checked_problem(version, forge_jar, source)
        if problem:
            return {"ready": False, "problem": problem}
        stamp = _stamp(javac, forge_jar, stat, source, patches)
        jar = _jar_path(version, stamp)
        known = _built.get(str(jar))
        if known is None or known["stamp"] != stamp or not jar.is_file():
            known = _built_or_build(jar.parent, jar, stamp, javac, jar_tool, forge_jar, version)
            if "problem" in known:
                _failed[str(jar)] = (known["problem"], time.time())
                return {"ready": False, "problem": known["problem"]}
        _failed.pop(str(jar), None)
        try:
            os.utime(jar)               # a run started with it now: kept KEEP_UNUSED from now
        except OSError as e:
            common._log(f"The card log's jar couldn't be marked as used ({jar.name}): {e}")
        return {"ready": True, "jar": str(jar.resolve()), "main": MAIN, "add_opens": list(known["add_opens"]),
                "game_patches": sorted(set(stamp["game_patches"].values())),
                "pilot_switches": sorted(set(stamp["pilot_switches"]) | set(stamp["fork_switches"]))}
    except Exception as e:      # never raises: a run goes on with plain Forge
        common._log(f"The card log couldn't be set up: {e!r}")
        problem = UNEXPECTED.format(what=type(e).__name__)
        if jar is not None:
            _failed[str(jar)] = (problem, time.time())
        return {"ready": False, "problem": problem}


def _built_or_build(folder, jar, stamp, javac, jar_tool, forge_jar, version):
    """Under the build lock: the jar's {"stamp", "add_opens"} when its stamp file matches
    and it holds DeckLabSim's classes and Deck Lab's own, else after
    building it, with the version's other jars tidied away (_remove_old_jars); {"problem"}
    when that fails."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with _build_lock(folder):
            stamp_file = jar.with_suffix(".json")
            try:
                same = (json.loads(stamp_file.read_text(encoding="utf-8")) == stamp
                        and _good_jar(jar, _classes()))
            except (OSError, ValueError):
                same = False
            if not same:
                problem = _build(folder, jar, javac, jar_tool, forge_jar, version)
                if problem:
                    return {"problem": problem}
                common._write_atomic(stamp_file, json.dumps(stamp, indent=1) + "\n")
                common._log(f"Built the card log for Forge {version}: {jar}")
            try:
                add_opens = _add_opens(forge_jar)
            except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
                common._log(f"Forge's jar manifest can't be read ({forge_jar}): {e!r}")
                return {"problem": NO_MANIFEST}
            _remove_old_jars(folder, jar, version)
            known = {"stamp": stamp, "add_opens": add_opens}
            _built[str(jar)] = known
            return known
    except TimeoutError:
        return {"problem": BUSY}
    except OSError as e:
        common._log(f"The card log's files can't be written in {folder}: {e}")
        return {"problem": CANT_WRITE}


def _remove_old_jars(folder, jar, version):
    """Delete this Forge version's card-log jars other than jar, with their stamps, best
    effort: not one a run has started with in the last KEEP_UNUSED seconds (it may still be
    playing batches), nor one that can't be deleted (a Forge process has it open, which
    Windows won't allow), which the next build, or the next process to use a jar, tries
    again."""
    name = re.compile(re.escape(f"decklab-sim-{version}") + JAR_TAIL)
    now = time.time()
    try:
        old_jars = [p for p in folder.glob("decklab-sim-*.jar") if p.name != jar.name and name.fullmatch(p.name)]
    except OSError as e:
        common._log(f"The card log's old jars can't be listed: {e}")
        return
    for old in old_jars:
        try:
            if now - old.stat().st_mtime < KEEP_UNUSED:
                continue
            old.unlink()
            old.with_suffix(".json").unlink(missing_ok=True)
        except OSError as e:
            common._log(f"An old card-log jar wasn't deleted ({old.name}): {e}")


def _good_jar(jar, classes):
    """Does the jar hold these classes (_classes(): DeckLabSim's and Deck Lab's own)?"""
    try:
        with zipfile.ZipFile(jar) as z:
            names = set(z.namelist())
    except (OSError, zipfile.BadZipFile):
        return False
    return all(name in names for name in classes)


def _build(folder, jar, javac, jar_tool, forge_jar, version):
    """javac Deck Lab's sources (deck_lab_sources()) against Forge's jar, then jar the classes,
    with the list of the pilot switches (PILOT_SWITCH_LIST), as jar (replaced whole: only a jar
    of the same stamp whose own stamp file is missing or wrong, or that lacks one of those
    classes, is ever there already). None when done, else the problem (the details are
    logged): IN_USE when a Forge process has that jar open. Runs under the build lock, so a
    build folder already there was left by a process that died."""
    for old in folder.glob(".build-*"):
        shutil.rmtree(old, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(dir=folder, prefix=".build-"))
    try:
        classes = tmp / "classes"
        made = tmp / jar.name
        sources = [str(path) for path in deck_lab_sources()]
        steps = (
            ("javac", [str(javac), "-encoding", "UTF-8", "-cp", str(forge_jar), "-d", str(classes), *sources]),
            ("jar", [str(jar_tool), "--create", "--file", str(made), "-C", str(classes), "."]),
        )
        for what, argv in steps:
            if what == "jar":
                (classes / PILOT_SWITCH_LIST).parent.mkdir(parents=True, exist_ok=True)
                (classes / PILOT_SWITCH_LIST).write_text("".join(f"{sid}\n" for sid in pilot_switch_ids()),
                                                         encoding="utf-8", newline="\n")
            try:
                done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      timeout=BUILD_TIMEOUT, stdin=subprocess.DEVNULL,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired) as e:
                common._log(f"The card log's {what} couldn't run: {e!r}")
                return CANT_BUILD.format(version=version)
            if done.returncode != 0:
                output = (done.stdout + done.stderr).strip().splitlines()
                common._log(f"The card log's {what} stopped with exit code {done.returncode}:\n"
                            + "\n".join(output[-40:]))
                return CANT_BUILD.format(version=version)
        if not _good_jar(made, _classes()):
            common._log(f"The card log's jar was built without DeckLabSim's classes or Deck Lab's own: {made}")
            return CANT_BUILD.format(version=version)
        try:
            _replace(made, jar)
        except PermissionError as e:
            common._log(f"The card log's jar couldn't be replaced: {e}")
            return IN_USE
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _replace(made, jar):
    """os.replace, tried again for a moment while something has the old jar open (a Forge
    process of another run, a virus scanner); PermissionError if it stays open."""
    for wait in (0.1, 0.25, 0.5, 1, 2, None):
        try:
            os.replace(made, jar)
            return
        except PermissionError:
            if wait is None:
                raise
        time.sleep(wait)


@contextmanager
def _build_lock(folder):
    """Hold the card log's build lock: this process's threads, then an OS lock on
    folder/LOCK_FILE (gone with the process however it ends) for other processes.
    TimeoutError after LOCK_WAIT seconds."""
    deadline = time.monotonic() + LOCK_WAIT
    if not _lock.acquire(timeout=LOCK_WAIT):
        raise TimeoutError
    try:
        fd = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
        locked = False
        try:
            while True:
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)      # the file's first byte
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError from None
                    time.sleep(0.1)
            yield
        finally:
            # Given up before closing: Windows frees a lock left on a closed file only after
            # a while, which could keep the next build waiting for nobody, or report BUSY.
            if locked:
                try:
                    if sys.platform == "win32":
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError as e:        # closing gives it up anyway
                    common._log(f"The card log's build lock couldn't be given up before closing: {e!r}")
            os.close(fd)
    finally:
        _lock.release()


def _manifest_main(text):
    """A jar manifest's main section: {attribute name in lower case: value}. A manifest
    line is at most 72 bytes, so a long value goes on in continuation lines that start
    with one space."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith(" ") and lines:
            lines[-1] += line[1:]
        elif not line:
            break                   # the end of the main section
        else:
            lines.append(line)
    attributes = {}
    for line in lines:
        name, sep, value = line.partition(":")
        if sep:
            attributes.setdefault(name.strip().lower(), value.strip())
    return attributes


def _manifest_add_opens(text):
    """The --add-opens flags for a jar manifest's Add-Opens attribute (main section):
    ["--add-opens", "java.desktop/java.beans=ALL-UNNAMED", ...]."""
    value = _manifest_main(text).get("add-opens", "")
    return [flag for module in value.split() for flag in ("--add-opens", f"{module}=ALL-UNNAMED")]


def _manifest(forge_jar):
    """The text of a jar's manifest: OSError, zipfile.BadZipFile, KeyError (none) or
    UnicodeDecodeError when it can't be read."""
    with zipfile.ZipFile(forge_jar) as z:
        return z.read("META-INF/MANIFEST.MF").decode("utf-8")


def _add_opens(forge_jar):
    """The --add-opens flags Forge's jar asks for. java applies a manifest's Add-Opens only
    to the jar it starts with -jar; the card log starts with -cp, so they go on the
    command line instead."""
    return _manifest_add_opens(_manifest(forge_jar))


def forge_build(forge_jar):
    """Which Forge build a jar is: its manifest's Implementation-Version, like
    "2.0.15-SNAPSHOT-09.28", or None when that can't be read. Kept while the jar's size
    and time stay the same (reading it takes about 60 ms, and status() asks on every
    page load). Never raises for a jar that can't be read."""
    try:
        stat = Path(forge_jar).stat()
    except OSError:
        return None
    path = str(forge_jar)
    known = _builds.get(path)
    if known is not None and known[:2] == (stat.st_size, stat.st_mtime_ns):
        return known[2]
    try:
        build = _manifest_main(_manifest(forge_jar)).get("implementation-version")
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as e:
        common._log(f"Forge's build can't be read from its jar's manifest ({forge_jar}): {e!r}")
        build = None
    if build is not None and not VERSION_RE.fullmatch(build):
        build = None
    _builds[path] = (stat.st_size, stat.st_mtime_ns, build)
    return build


def _checks(source):
    """{version: {"ok": bool, "build": str | None, "source": str | None}}: the latest check
    of each Forge version, CHECKED's with checked.json's over them, except that a check of
    another source never takes the place of one of source (the current source_sha256()).
    ok: the check passed; build: the Forge build checked (None: any build of that
    version); source: the card log's source checked (None: not known, as in a checked.json
    written before sources were noted). A checked.json that can't be read adds nothing."""
    checks = {version: {"ok": True, "build": CHECKED_BUILDS.get(version), "source": CHECKED_SOURCE.get(version)}
              for version in CHECKED}
    path = common.DATA_DIR / FOLDER / CHECKED_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return checks
    except (OSError, ValueError) as e:
        common._log(f"The card log's checked versions can't be read ({path}): {e}")
        return checks
    found = data.get("versions") if isinstance(data, dict) else None
    if isinstance(found, dict):
        for version, check in found.items():
            if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
                continue
            check = check if isinstance(check, dict) else {}
            build, sha = check.get("build"), check.get("source_sha256")
            found_check = {"ok": check.get("failed") is not True,
                           "build": build if isinstance(build, str) and VERSION_RE.fullmatch(build) else None,
                           "source": sha if isinstance(sha, str) and SHA_RE.fullmatch(sha) else None}
            if found_check["source"] == source or checks.get(version, {}).get("source") != source:
                checks[version] = found_check
    return checks


def checked_versions():
    """Every Forge version the card log may be used with: CHECKED and those cardlog-check
    found playing the same games, with the current source, less any whose latest check
    failed."""
    try:
        source = source_sha256()
    except OSError:
        return set()
    return {version for version, check in _checks(source).items() if check["ok"] and check["source"] == source}


def record_checked(version, games=None, build=None, source=None):
    """Note that cardlog-check found the card log plays the same games as plain Forge on
    this Forge version (games: how many it compared; build: the Forge jar's, from
    forge_build(); source: the card log's source checked, its source_sha256(), None: the
    source now). It takes the place of a failed check. ForgeError (a plain sentence) when
    it can't be written."""
    _record(version, {"when": common._now(), "games": games, "build": build}, source, "was checked")


def record_failed(version, games=None, build=None, source=None):
    """Note that cardlog-check found the card log didn't play the same games as plain
    Forge on this Forge version, or that a card log failed its checks, which turns it off
    for that version (one in CHECKED too) until a check passes. ForgeError (a plain
    sentence) when it can't be written."""
    _record(version, {"when": common._now(), "games": games, "build": build, "failed": True}, source,
            "failed its checks")


def _record(version, check, source, what):
    """Write check, with the source checked (None: the source now), as version's latest in
    checked.json (what the card log did: for the error)."""
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise ValueError(f"not a Forge version: {version!r}")
    if source is None:
        try:
            source = source_sha256()
        except OSError as e:
            common._log(f"The card log's source can't be read: {e}")
            raise common.ForgeError(NOT_NOTED.format(what=what)) from None
    if not isinstance(source, str) or not SHA_RE.fullmatch(source):
        raise ValueError(f"not a source SHA-256: {source!r}")
    check["source_sha256"] = source
    path = common.DATA_DIR / FOLDER / CHECKED_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("versions"), dict):
            data = {"versions": {}}
    except (OSError, ValueError):
        data = {"versions": {}}
    data["versions"][version] = check
    try:
        common._write_atomic(path, json.dumps(data, indent=1, sort_keys=True) + "\n")
    except OSError as e:
        common._log(f"The card log's checked versions can't be saved as {path}: {e}")
        raise common.ForgeError(NOT_NOTED.format(what=what)) from None
