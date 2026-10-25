"""Tests for decklab.lib.forge.simjar, the card log's jar: reading Forge's manifest, when
the jar is built again (under a name of its own) and old ones deleted, the lock around
building it, the Forge versions, builds and DeckLabSim sources it may be used with (and a
failed check turning it off), that CHECKED_SOURCE is the source in the repo, that
readiness() gives the problem the last build met while nothing it's built from changed
and no process has built the jar since, and that card_log() and readiness() never raise.

No Java is needed: a made-up JDK folder (empty java, javac and jar files) passes readiness(),
a made-up Forge jar holds a list of Deck Lab's changes as the fork's build does (PATCH_LIST),
a made-up DeckLabSim source stands in for the real one (CHECKED_SOURCE patched to match it),
and simjar._build is replaced by one that writes a jar holding the right class names. With
DECKLAB_FORGE_TESTS=1, the real JDK (config.json's forge_java, or the newest one found)
builds the real jar against the installed Forge.

Run from the repo root: python -m unittest decklab.tests.test_forge_simjar
"""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decklab.lib import forge

simjar = forge.simjar
REAL_BUILD = simjar._build          # SimjarCase puts a fake in its place
REAL = os.environ.get("DECKLAB_FORGE_TESTS") == "1"
EXE = ".exe" if os.name == "nt" else ""
JAR_NAME = "forge-gui-desktop-2.0.15-jar-with-dependencies.jar"

# A manifest like Forge's: Add-Opens is longer than 72 bytes, so it goes on in
# continuation lines (each starting with one space), which can split a name anywhere.
MANIFEST = ("Manifest-Version: 1.0\r\n"
            "Main-Class: forge.view.Main\r\n"
            "Add-Opens: java.desktop/java.beans java.desktop/javax.swing.border java.\r\n"
            " base/java.util java.base/java.lang\r\n"
            "Created-By: Maven\r\n"
            "\r\n"
            "Name: forge/\r\n"
            "Add-Opens: java.base/java.nowhere\r\n")
FLAGS = ["--add-opens", "java.desktop/java.beans=ALL-UNNAMED", "--add-opens", "java.desktop/javax.swing.border=ALL-UNNAMED",
         "--add-opens", "java.base/java.util=ALL-UNNAMED", "--add-opens", "java.base/java.lang=ALL-UNNAMED"]
# The installed Forge's: a snapshot build under the release's jar name.
SNAPSHOT_MANIFEST = "Manifest-Version: 1.0\r\nImplementation-Version: 2.0.15-SNAPSHOT-09.28\r\n\r\n"
# SimjarCase's Forge jar: MANIFEST, as the build CHECKED_BUILDS names.
FORGE_MANIFEST = MANIFEST.replace("Created-By", "Implementation-Version: 2.0.15-SNAPSHOT-09.28\r\nCreated-By")


def stamp_hash(stamp):
    """A jar name's hash: the first 12 hex digits of the SHA-256 of the stamp as JSON."""
    return hashlib.sha256(json.dumps(stamp, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


# The list of Deck Lab's changes a Forge jar of its fork holds (simjar.FORGE_PATCH_LIST), like the
# fork's: two that change games, two that don't, a comment and a line that isn't one.
PATCH_LIST = ("# Deck Lab's changes in this Forge build\r\n"
              "forge/ai/AiAttackController.class attack-requirements-in-order-1\r\n"
              "forge/ai/AiController.class -\r\n"
              "forge/game/Match.class deck-order-1\r\n"
              "forge/game/mulligan/AbstractMulligan.class -\r\n"
              "not a line\r\n")
PATCHES = {"forge/ai/AiAttackController.class": "attack-requirements-in-order-1", "forge/ai/AiController.class": None,
           "forge/game/Match.class": "deck-order-1", "forge/game/mulligan/AbstractMulligan.class": None}


def write_jar(path, manifest=MANIFEST, names=(), patch_list=PATCH_LIST):
    """A zip with META-INF/MANIFEST.MF (None: without one), Deck Lab's list of changes
    (patch_list; None: without one, as in a stock Forge jar) and empty entries names."""
    with zipfile.ZipFile(path, "w") as z:
        if manifest is not None:
            z.writestr("META-INF/MANIFEST.MF", manifest)
        if patch_list is not None:
            z.writestr(simjar.FORGE_PATCH_LIST, patch_list)
        for name in names:
            z.writestr(name, b"")


class SimjarCase(unittest.TestCase):
    """A data folder, a made-up JDK and Forge folder, and a fake build per test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = self.tmp / "data"
        p = mock.patch.object(forge.common, "DATA_DIR", self.data)
        p.start()
        self.addCleanup(p.stop)
        for state in (simjar._built, simjar._failed, simjar._forge_patches, simjar._fork_switches):
            state.clear()
            self.addCleanup(state.clear)
        self.jdk = self.tmp / "jdk" / "bin"
        self.jdk.mkdir(parents=True)
        for tool in ("java", "javac", "jar"):
            (self.jdk / f"{tool}{EXE}").write_bytes(b"")
        self.java = str(self.jdk / f"java{EXE}")
        self.forge_dir = self.tmp / "forge"
        self.forge_dir.mkdir()
        write_jar(self.forge_dir / JAR_NAME, manifest=FORGE_MANIFEST)
        self.source = self.tmp / "DeckLabSim.java"
        self.source.write_text("class DeckLabSim {}\n", encoding="utf-8")
        # The card log's source is DeckLabSim's alone.
        for name, value in (("SOURCE", self.source), ("CHECKED", frozenset({"2.0.15"})),
                            ("CHECKED_BUILDS", {"2.0.15": "2.0.15-SNAPSHOT-09.28"}),
                            ("CHECKED_SOURCE", {"2.0.15": self.sha()})):
            p = mock.patch.object(simjar, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.builds = []
        p = mock.patch.object(simjar, "_build", self.fake_build)
        p.start()
        self.addCleanup(p.stop)
        self.logged = []
        p = mock.patch.object(forge.common, "_log", self.logged.append)
        p.start()
        self.addCleanup(p.stop)

    def fake_build(self, folder, jar, javac, jar_tool, forge_jar, version):
        """simjar._build without a JDK: a jar holding the class names a good one has."""
        self.builds.append(version)
        made = folder / "made.jar"
        write_jar(made, names=simjar.CLASSES)
        os.replace(made, jar)
        return None

    def card_log(self, version="2.0.15", **kwargs):
        return simjar.card_log(self.java, self.forge_dir, JAR_NAME, version, **kwargs)

    def sha(self):
        """The made-up source's SHA-256, as source_sha256() gives it (write_text gives it CRLF
        on Windows)."""
        return hashlib.sha256(self.source.read_bytes().replace(b"\r\n", b"\n")).hexdigest()

    def jar(self, version="2.0.15"):
        """The card-log jar card_log() gives for the Forge jar and source as they are now."""
        forge_jar = self.forge_dir / JAR_NAME
        stamp = {"source_sha256": self.sha(), "javac": str(self.jdk / f"javac{EXE}"),
                 "forge_jar": {"name": JAR_NAME, "size": forge_jar.stat().st_size,
                               "mtime_ns": forge_jar.stat().st_mtime_ns},
                 "patches": sorted(simjar.forge_patches(forge_jar)),
                 "game_patches": simjar.game_patch_ids(simjar.forge_patches(forge_jar)),
                 "pilot_switches": sorted(simjar.PILOT_SWITCHES),
                 "fork_switches": simjar.fork_switches(forge_jar)}
        return self.data / "cardlog" / f"decklab-sim-{version}-{stamp_hash(stamp)}.jar"

    def readiness(self, version="2.0.15"):
        """readiness() as status() asks it: with the Forge jar's path."""
        return simjar.readiness(self.java, version, self.forge_dir / JAR_NAME)


# ============================================================ the manifest

class ManifestTests(unittest.TestCase):

    def test_add_opens_with_continuation_lines(self):
        self.assertEqual(simjar._manifest_add_opens(MANIFEST), FLAGS)
        self.assertEqual(simjar._manifest_add_opens(MANIFEST.replace("\r\n", "\n")), FLAGS)

    def test_only_the_main_section_counts(self):
        self.assertEqual(simjar._manifest_add_opens("Manifest-Version: 1.0\n\nName: x/\nAdd-Opens: a/b\n"), [])

    def test_no_add_opens(self):
        self.assertEqual(simjar._manifest_add_opens("Manifest-Version: 1.0\r\nMain-Class: x\r\n"), [])
        self.assertEqual(simjar._manifest_add_opens(""), [])

    def test_read_from_the_jar(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        write_jar(tmp / "forge.jar")
        self.assertEqual(simjar._add_opens(tmp / "forge.jar"), FLAGS)

    def test_the_main_section(self):
        found = simjar._manifest_main(MANIFEST.replace("Created-By", "Implementation-Version: 2.0.15-SNAPSHOT-09.28\r\n"
                                                                    "Created-By"))
        self.assertEqual(found["implementation-version"], "2.0.15-SNAPSHOT-09.28")
        self.assertEqual(found["manifest-version"], "1.0")
        self.assertEqual(found["add-opens"].split()[2], "java.base/java.util")      # joined across lines
        self.assertNotIn("name", found)                                             # not the main section


class ForgeBuildTests(unittest.TestCase):
    """forge_build(): which Forge build a jar is, from its manifest."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.jar = self.tmp / JAR_NAME
        p = mock.patch.object(forge.common, "_log", lambda *a: None)
        p.start()
        self.addCleanup(p.stop)

    def test_read_from_the_manifest_and_kept(self):
        write_jar(self.jar, manifest=SNAPSHOT_MANIFEST)
        self.assertEqual(simjar.forge_build(self.jar), "2.0.15-SNAPSHOT-09.28")
        with mock.patch.object(simjar, "_manifest", side_effect=AssertionError("read again")):
            self.assertEqual(simjar.forge_build(self.jar), "2.0.15-SNAPSHOT-09.28")     # the same jar: not read again
        mtime = self.jar.stat().st_mtime_ns
        write_jar(self.jar, manifest=SNAPSHOT_MANIFEST.replace("09.28", "10.02"))       # replaced (same size)
        os.utime(self.jar, ns=(mtime + 5_000_000_000, mtime + 5_000_000_000))
        self.assertEqual(simjar.forge_build(self.jar), "2.0.15-SNAPSHOT-10.02")         # read again

    def test_none_when_it_cant_be_read(self):
        self.assertIsNone(simjar.forge_build(self.tmp / "missing.jar"))
        write_jar(self.jar)                                         # no Implementation-Version
        self.assertIsNone(simjar.forge_build(self.jar))
        write_jar(self.jar, manifest=None)                          # no manifest
        self.assertIsNone(simjar.forge_build(self.jar))
        self.jar.write_bytes(b"")                                   # not a zip (the tests' made-up Forge)
        self.assertIsNone(simjar.forge_build(self.jar))
        write_jar(self.jar, manifest="Implementation-Version: ../../x\r\n")
        self.assertIsNone(simjar.forge_build(self.jar))


# ============================================================ building the jar

class BuildTests(SimjarCase):

    def test_built_once_then_reused(self):
        found = self.card_log()
        self.assertEqual(found, {"ready": True, "jar": str(self.jar().resolve()), "main": "decklab.DeckLabSim",
                                 "add_opens": FLAGS, "game_patches": ["attack-requirements-in-order-1", "deck-order-1"],
                                 "pilot_switches": ["aisim-hybrid-1", "team-pump-1"]})
        self.assertEqual(self.builds, ["2.0.15"])
        stamp = json.loads(self.jar().with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(set(stamp), {"source_sha256", "forge_jar", "patches", "game_patches", "pilot_switches",
                                      "fork_switches", "javac"})
        self.assertEqual(stamp["forge_jar"]["name"], JAR_NAME)
        self.assertEqual(stamp["patches"], sorted(PATCHES))          # Deck Lab's changes in Forge's jar
        self.assertEqual(stamp["game_patches"], {"forge/ai/AiAttackController.class": "attack-requirements-in-order-1",
                                                 "forge/game/Match.class": "deck-order-1"})
        self.assertEqual(Path(found["jar"]).name, f"decklab-sim-2.0.15-{stamp_hash(stamp)}.jar")     # named by it
        self.assertEqual(self.card_log(), found)        # remembered in this process
        simjar._built.clear()
        self.assertEqual(self.card_log(), found)        # the stamp beside the jar says it's up to date
        self.assertEqual(self.builds, ["2.0.15"])

    def test_a_changed_source_gets_its_own_jar_once_checked(self):
        first = self.card_log()
        self.source.write_text("class DeckLabSim { int x; }\n", encoding="utf-8")
        self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.changed_problem("2.0.15")})
        self.assertEqual(len(self.builds), 1)               # not built before it's checked
        second = self.card_log(checking=True)               # cardlog-check builds it
        self.assertEqual(len(self.builds), 2)
        self.assertNotEqual(second["jar"], first["jar"])
        self.assertTrue(Path(first["jar"]).is_file())       # a run still using the old one keeps it
        self.assertEqual(Path(second["jar"]), self.jar().resolve())

    def test_a_changed_forge_jar_builds_again(self):
        self.card_log()
        forge_jar = self.forge_dir / JAR_NAME
        stat = forge_jar.stat()
        os.utime(forge_jar, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))       # same size, newer
        self.card_log()
        write_jar(forge_jar, manifest=FORGE_MANIFEST + "X-Other: y\r\n")                    # another size
        self.card_log()
        self.assertEqual(len(self.builds), 3)
        self.assertEqual(len(list((self.data / "cardlog").glob("*.jar"))), 3)                 # each its own jar

    def test_another_jdk_builds_again(self):
        self.card_log()
        other = self.tmp / "jdk-27" / "bin"
        shutil.copytree(self.jdk, other)
        self.assertTrue(simjar.card_log(str(other / f"java{EXE}"), self.forge_dir, JAR_NAME, "2.0.15")["ready"])
        self.assertEqual(len(self.builds), 2)

    def test_a_missing_or_broken_jar_builds_again(self):
        self.card_log()
        self.jar().unlink()
        self.assertTrue(self.card_log()["ready"])
        simjar._built.clear()
        write_jar(self.jar(), names=["decklab/Other.class"])      # not DeckLabSim's
        self.assertTrue(self.card_log()["ready"])
        simjar._built.clear()
        self.jar().with_suffix(".json").write_text("not json", encoding="utf-8")
        self.assertTrue(self.card_log()["ready"])
        self.assertEqual(len(self.builds), 4)

    def test_each_forge_version_has_its_own_jar(self):
        simjar.record_checked("2.0.16")
        self.card_log("2.0.15")
        self.card_log("2.0.16")
        self.assertEqual(sorted(p.name for p in (self.data / "cardlog").glob("*.jar")),
                         [self.jar("2.0.15").name, self.jar("2.0.16").name])
        self.assertRegex(self.jar("2.0.16").name, r"^decklab-sim-2\.0\.16-[0-9a-f]{12}\.jar$")

    def test_old_jars_are_deleted_unless_used_lately_or_open(self):
        folder = self.data / "cardlog"
        folder.mkdir(parents=True)
        day_ago = time.time() - simjar.KEEP_UNUSED - 60
        names = ["decklab-sim-2.0.15.jar", "decklab-sim-2.0.15-3a947807.jar",      # earlier builds' names
                 "decklab-sim-2.0.15-0123456789ab.jar", "decklab-sim-2.0.15-ba9876543210.jar",
                 "decklab-sim-2.0.16-0123456789ab.jar",                            # another Forge version
                 "decklab-sim-2.0.15-1-0123456789ab.jar"]                          # Forge 2.0.15-1's
        for name in names:
            write_jar(folder / name, names=simjar.CLASSES)
            (folder / name).with_suffix(".json").write_text("{}", encoding="utf-8")
            os.utime(folder / name, (day_ago, day_ago))
        lately = folder / "decklab-sim-2.0.15-ba9876543210.jar"
        os.utime(lately, (time.time() - 60, time.time() - 60))           # a run started with it a minute ago
        locked = folder / "decklab-sim-2.0.15-0123456789ab.jar"
        real_unlink = Path.unlink

        def unlink(path, *args, **kwargs):          # as Windows does for a jar a Forge process has open
            if path.name == locked.name:
                raise PermissionError(13, "The process cannot access the file", str(path))
            return real_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", unlink):
            found = self.card_log()
        self.assertTrue(found["ready"])
        left = sorted(p.name for p in folder.iterdir() if p.suffix in (".jar", ".json") and p.name != "checked.json")
        kept = [lately.name, locked.name, "decklab-sim-2.0.16-0123456789ab.jar", "decklab-sim-2.0.15-1-0123456789ab.jar",
                self.jar().name]
        self.assertEqual(left, sorted(kept + [Path(name).with_suffix(".json").name for name in kept]))
        self.assertTrue(any(locked.name in line for line in self.logged))
        # The jar given is marked as used, and an old jar is only tidied when a process first uses one.
        self.assertGreater(self.jar().stat().st_mtime, time.time() - 60)
        os.utime(lately, (day_ago, day_ago))
        self.assertEqual(self.card_log(), found)
        self.assertTrue(lately.is_file())
        simjar._built.clear()                       # another process, say
        self.assertEqual(self.card_log(), found)
        self.assertFalse(lately.exists())
        self.assertEqual(self.builds, ["2.0.15"])

    def test_two_runs_at_once_build_once(self):
        def slow_build(*args):
            time.sleep(0.3)
            return self.fake_build(*args)

        found = []
        with mock.patch.object(simjar, "_build", slow_build):
            threads = [threading.Thread(target=lambda: found.append(self.card_log())) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(self.builds), 1)
        self.assertEqual([f["ready"] for f in found], [True, True, True])

    def test_a_build_another_process_holds_the_lock_for(self):
        folder = self.data / "cardlog"
        folder.mkdir(parents=True)
        fd = os.open(folder / simjar.LOCK_FILE, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o666)
        self.addCleanup(os.close, fd)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with mock.patch.object(simjar, "LOCK_WAIT", 0.3):
            self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.BUSY})
        self.assertEqual(self.builds, [])

    def test_the_lock_is_given_up_before_its_file_is_closed(self):
        # Windows frees a lock left on a closed file only after a while.
        done = []
        real_close = os.close
        with mock.patch.object(simjar.os, "close", lambda fd: (done.append("close"), real_close(fd))):
            if sys.platform == "win32":
                import msvcrt
                real = msvcrt.locking
                with mock.patch.object(msvcrt, "locking", lambda fd, mode, n: (done.append(mode), real(fd, mode, n))):
                    self.assertTrue(self.card_log()["ready"])
                self.assertEqual(done, [msvcrt.LK_NBLCK, msvcrt.LK_UNLCK, "close"])
            else:
                import fcntl
                real = fcntl.flock
                with mock.patch.object(fcntl, "flock", lambda fd, op: (done.append(op), real(fd, op))):
                    self.assertTrue(self.card_log()["ready"])
                self.assertEqual(done, [fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN, "close"])
        self.assertEqual(self.builds, ["2.0.15"])
        # Free at once: another opener gets it without waiting.
        fd = os.open(self.data / "cardlog" / simjar.LOCK_FILE, os.O_RDWR | getattr(os, "O_BINARY", 0))
        self.addCleanup(os.close, fd)
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_leftover_build_folders_are_removed(self):
        folder = self.data / "cardlog"
        (folder / ".build-old" / "classes").mkdir(parents=True)
        with mock.patch.object(simjar, "_build", REAL_BUILD), \
                mock.patch.object(simjar.subprocess, "run", side_effect=OSError("no javac here")):
            self.assertEqual(self.card_log(), {"ready": False, "problem": "The card log couldn't be built for Forge 2.0.15."})
        self.assertEqual(list(folder.glob(".build-*")), [])


# ============================================================ problems, never raised

class ProblemTests(SimjarCase):

    def test_a_failed_build(self):
        with mock.patch.object(simjar, "_build", return_value="The card log couldn't be built for Forge 2.0.15."):
            self.assertEqual(self.card_log(), {"ready": False, "problem": "The card log couldn't be built for Forge 2.0.15."})
        self.assertFalse(self.jar().with_suffix(".json").exists())

    def test_javac_failing_is_logged_not_shown(self):
        failed = mock.Mock(returncode=1, stdout="", stderr=f"{self.source}:1: error: cannot find symbol\n")
        with mock.patch.object(simjar, "_build", REAL_BUILD), \
                mock.patch.object(simjar.subprocess, "run", return_value=failed):
            found = self.card_log()
        self.assertEqual(found, {"ready": False, "problem": "The card log couldn't be built for Forge 2.0.15."})
        self.assertTrue(any("cannot find symbol" in line for line in self.logged))
        self.assertNotIn(str(self.tmp), found["problem"])

    def test_a_jar_a_forge_process_has_open_isnt_replaced(self):
        # Only a jar of the same stamp is ever replaced: one whose stamp file was lost, say.
        self.card_log()
        simjar._built.clear()
        self.jar().with_suffix(".json").unlink()

        def run(argv, **kwargs):                    # javac and jar, as if they'd run
            if "--create" in argv:
                write_jar(Path(argv[argv.index("--file") + 1]), names=simjar.CLASSES)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(simjar, "_build", REAL_BUILD), mock.patch.object(simjar.subprocess, "run", run), \
                mock.patch.object(simjar, "_replace", side_effect=PermissionError(13, "Access is denied")):
            found = self.card_log()
        self.assertEqual(found, {"ready": False, "problem": "Another run had the card log's jar open, so it couldn't "
                                                            "be built again (the next run tries again)."})
        self.assertEqual(self.readiness(), found)
        self.assertTrue(any("Access is denied" in line for line in self.logged))
        self.assertTrue(self.card_log()["ready"])          # once it's closed

    def test_no_forge_jar(self):
        found = simjar.card_log(self.java, self.forge_dir, "forge-gui-desktop-9-jar-with-dependencies.jar", "2.0.15")
        self.assertEqual(found, {"ready": False, "problem": "The card log couldn't be built for Forge 2.0.15."})

    def test_a_forge_jar_without_a_manifest(self):
        write_jar(self.forge_dir / JAR_NAME, manifest=None)
        self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.unknown_build_problem(
            "2.0.15", "2.0.15-SNAPSHOT-09.28")})        # its build can't be read either
        self.assertEqual(self.card_log(checking=True), {"ready": False, "problem": simjar.NO_MANIFEST})

    def test_a_data_folder_that_cant_be_written(self):
        self.data.parent.mkdir(parents=True, exist_ok=True)
        self.data.write_text("a file, not a folder", encoding="utf-8")
        self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.CANT_WRITE})

    def test_never_raises(self):
        with mock.patch.object(simjar, "_build", side_effect=RuntimeError("a bug")):
            self.assertEqual(self.card_log(), {"ready": False,
                                               "problem": "The card log couldn't be set up (RuntimeError)."})
        bad_java = object()             # not a path: Path() raises TypeError
        self.assertEqual(simjar.readiness(bad_java, "2.0.15"),
                         {"ready": False, "problem": "The card log couldn't be set up (TypeError)."})
        self.assertEqual(simjar.card_log(bad_java, self.forge_dir, JAR_NAME, "2.0.15"),
                         {"ready": False, "problem": "The card log couldn't be set up (TypeError)."})
        self.assertEqual(simjar.card_log(self.java, None, JAR_NAME, "2.0.15"),
                         {"ready": False, "problem": "The card log couldn't be set up (TypeError)."})

    def test_a_version_not_checked(self):
        found = self.card_log("2.0.16")
        self.assertEqual(found, {"ready": False, "problem": simjar.unchecked_problem("2.0.16")})
        self.assertEqual(self.builds, [])
        self.assertTrue(self.card_log("2.0.16", checking=True)["ready"])       # cardlog-check builds it anyway
        self.assertEqual(self.builds, ["2.0.16"])
        self.assertFalse(self.card_log("2.0.16")["ready"])                     # and nothing else uses it yet


# ============================================================ readiness and checked versions

class ReadinessTests(SimjarCase):

    def test_ready(self):
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})
        self.assertEqual(self.builds, [])           # nothing is built

    def test_a_jre_has_no_javac_or_jar(self):
        for tool in ("javac", "jar"):
            (self.jdk / f"{tool}{EXE}").unlink()
            self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": False, "problem": simjar.NO_JDK})
            self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.NO_JDK})
            (self.jdk / f"{tool}{EXE}").write_bytes(b"")
        self.assertEqual(self.builds, [])

    def test_no_java(self):
        self.assertEqual(simjar.readiness(None, "2.0.15"), {"ready": False, "problem": simjar.NO_JAVA})

    def test_an_unchecked_version_says_how_to_check_it(self):
        found = simjar.readiness(self.java, "2.0.16")
        self.assertFalse(found["ready"])
        self.assertEqual(found["problem"], "The card log hasn't been checked with Forge 2.0.16 yet "
                                           "(python -m decklab.lib.forge cardlog-check does that).")

    def test_checked_versions(self):
        self.assertEqual(simjar.checked_versions(), {"2.0.15"})
        simjar.record_checked("2.0.16", 20)
        simjar.record_checked("2.0.17")
        self.assertEqual(simjar.checked_versions(), {"2.0.15", "2.0.16", "2.0.17"})
        saved = json.loads((self.data / "cardlog" / "checked.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["versions"]["2.0.16"]["games"], saved["versions"]["2.0.17"]["games"]), (20, None))
        self.assertEqual(simjar.readiness(self.java, "2.0.16"), {"ready": True, "problem": None})

    def test_a_checked_file_that_cant_be_read(self):
        path = self.data / "cardlog" / "checked.json"
        path.parent.mkdir(parents=True)
        for text in ("not json", "[1, 2]", '{"versions": ["2.0.16"]}', '{"versions": {"../x": {}, "2.0.18": {}}}'):
            path.write_text(text, encoding="utf-8")
            self.assertEqual(simjar.checked_versions() - {"2.0.18"}, {"2.0.15"}, text)
        path.write_text("not json", encoding="utf-8")
        simjar.record_checked("2.0.16")             # starts again
        self.assertEqual(simjar.checked_versions(), {"2.0.15", "2.0.16"})

    def test_record_checked_takes_only_a_version(self):
        with self.assertRaises(ValueError):
            simjar.record_checked("../../x")
        with self.assertRaises(ValueError):
            simjar.record_failed("../../x")

    def test_record_checked_that_cant_be_saved(self):
        self.data.parent.mkdir(parents=True, exist_ok=True)
        self.data.write_text("a file, not a folder", encoding="utf-8")
        with self.assertRaises(forge.ForgeError) as caught:
            simjar.record_checked("2.0.16")
        self.assertNotIn(str(self.tmp), str(caught.exception))
        with self.assertRaises(forge.ForgeError) as caught:
            simjar.record_failed("2.0.16")
        self.assertEqual(str(caught.exception), "Deck Lab couldn't note that the card log failed its checks "
                                                "(its data folder can't be written).")

    def test_a_failed_check_turns_a_checked_version_off(self):
        simjar.record_failed("2.0.15", 20, "2.0.15-SNAPSHOT-09.28")         # even one in CHECKED
        problem = ("The card log failed its last check with Forge 2.0.15 "
                   "(python -m decklab.lib.forge cardlog-check checks it again).")
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": False, "problem": problem})
        self.assertEqual(simjar.checked_versions(), set())
        self.assertEqual(self.card_log(), {"ready": False, "problem": problem})
        self.assertEqual(self.builds, [])
        self.assertTrue(self.card_log(checking=True)["ready"])     # cardlog-check builds it to check again
        self.assertFalse(self.card_log()["ready"])                 # which a run still doesn't use
        simjar.record_checked("2.0.15", 20, "2.0.15-SNAPSHOT-09.28")      # a check that passed
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})
        self.assertTrue(self.card_log()["ready"])
        saved = json.loads((self.data / "cardlog" / "checked.json").read_text(encoding="utf-8"))
        self.assertNotIn("failed", saved["versions"]["2.0.15"])

    def test_a_failed_check_of_a_recorded_version(self):
        simjar.record_checked("2.0.16", 20)
        simjar.record_failed("2.0.16", 20)
        self.assertEqual(simjar.checked_versions(), {"2.0.15"})
        self.assertIn("failed its last check", simjar.readiness(self.java, "2.0.16")["problem"])
        saved = json.loads((self.data / "cardlog" / "checked.json").read_text(encoding="utf-8"))
        self.assertEqual(set(saved["versions"]["2.0.16"]), {"when", "games", "build", "source_sha256", "failed"})
        self.assertEqual(saved["versions"]["2.0.16"]["source_sha256"], self.sha())


# ============================================================ a failed build, in readiness()

class FailedBuildTests(SimjarCase):
    """readiness() gives the problem the last card_log() met with the same source, Forge jar
    and javac, so status() says why runs go without the card log, until that jar is built
    (in this process or another)."""

    CANT = "The card log couldn't be built for Forge 2.0.15."
    READY = {"ready": True, "problem": None}

    def fail_build(self, **kwargs):
        with mock.patch.object(simjar, "_build", return_value=self.CANT):
            self.assertEqual(self.card_log(**kwargs), {"ready": False, "problem": self.CANT})

    def test_until_a_build_works(self):
        self.assertEqual(self.readiness(), self.READY)
        self.fail_build()
        self.assertEqual(self.readiness(), {"ready": False, "problem": self.CANT})
        self.assertEqual(self.readiness(), {"ready": False, "problem": self.CANT})      # kept
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), self.READY)            # without the Forge jar: not known
        self.assertEqual(self.readiness("2.0.16"), {"ready": False, "problem": simjar.unchecked_problem("2.0.16")})
        self.assertTrue(self.card_log()["ready"])           # the next run tries again
        self.assertEqual(self.readiness(), self.READY)
        self.assertEqual(self.builds, ["2.0.15"])

    def test_only_while_what_its_built_from_is_the_same(self):
        self.fail_build()
        forge_jar = self.forge_dir / JAR_NAME
        stat = forge_jar.stat()
        os.utime(forge_jar, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))      # another Forge jar
        self.assertEqual(self.readiness(), self.READY)
        os.utime(forge_jar, ns=(stat.st_atime_ns, stat.st_mtime_ns))                      # back
        self.assertEqual(self.readiness()["problem"], self.CANT)
        other = self.tmp / "jdk-27" / "bin"                                                # another JDK's javac
        shutil.copytree(self.jdk, other)
        self.assertEqual(simjar.readiness(str(other / f"java{EXE}"), "2.0.15", forge_jar), self.READY)
        self.source.write_text("class DeckLabSim { int x; }\n", encoding="utf-8")         # another source, checked
        simjar.record_checked("2.0.15", 20, "2.0.15-SNAPSHOT-09.28")
        self.assertEqual(self.readiness(), self.READY)
        self.fail_build(checking=True)                          # cardlog-check's build counts too
        self.assertEqual(self.readiness()["problem"], self.CANT)

    def test_until_another_process_builds_the_jar(self):
        # _failed is this process's own: a server's readiness() learns that a cardlog-check
        # in a terminal built the jar from the jar's stamp file, written after the failure.
        self.fail_build()
        for key, (problem, when) in simjar._failed.items():     # met a while ago (a file's time
            simjar._failed[key] = (problem, when - 10)           # can lag time.time() by a tick)
        failed = dict(simjar._failed)
        self.assertTrue(self.card_log()["ready"])                # the other process builds it...
        simjar._failed.update(failed)                            # ...and this one doesn't hear of it
        self.assertEqual(self.readiness(), self.READY)
        stamp_file = self.jar().with_suffix(".json")
        stamp = stamp_file.read_text(encoding="utf-8")
        stamp_file.write_text("{}", encoding="utf-8")            # a newer stamp file that doesn't match
        self.assertEqual(self.readiness()["problem"], self.CANT)
        stamp_file.write_text("not JSON", encoding="utf-8")
        self.assertEqual(self.readiness()["problem"], self.CANT)
        stamp_file.write_text(stamp, encoding="utf-8")
        self.jar().unlink()                                      # a stamp file without its jar
        self.assertEqual(self.readiness()["problem"], self.CANT)

    def test_a_problem_met_after_the_jar_was_built_stands(self):
        # The jar and a matching stamp file are there, but older than the problem: it stands.
        self.assertTrue(self.card_log()["ready"])
        simjar._built.clear()                                    # as another process would start
        earlier = time.time() - 10
        os.utime(self.jar().with_suffix(".json"), (earlier, earlier))
        with mock.patch.object(simjar, "_add_opens", side_effect=OSError(5, "Access is denied")):
            self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.NO_MANIFEST})
        self.assertEqual(self.readiness(), {"ready": False, "problem": simjar.NO_MANIFEST})
        self.assertTrue(self.card_log()["ready"])                # once Forge's jar can be read
        self.assertEqual(self.readiness(), self.READY)

    def test_a_data_folder_that_cant_be_written(self):
        self.data.parent.mkdir(parents=True, exist_ok=True)
        self.data.write_text("a file, not a folder", encoding="utf-8")
        self.assertEqual(self.card_log()["problem"], simjar.CANT_WRITE)
        self.assertEqual(self.readiness(), {"ready": False, "problem": simjar.CANT_WRITE})

    def test_an_unexpected_error(self):
        with mock.patch.object(simjar, "_build", side_effect=RuntimeError("a bug")):
            self.assertFalse(self.card_log()["ready"])
        self.assertEqual(self.readiness(), {"ready": False, "problem": "The card log couldn't be set up (RuntimeError)."})


# ============================================================ the Forge build checked

class BuildCheckedTests(SimjarCase):
    """A checked version counts only for the Forge build that was checked, when the jar's
    build can be read: Forge's snapshots keep the release's jar name."""

    def forge_jar(self, build):
        """Forge's jar replaced by this build (at a later time, as the size may be the same)."""
        path = self.forge_dir / JAR_NAME
        later = path.stat().st_mtime_ns + 5_000_000_000
        write_jar(path, manifest=MANIFEST.replace("Created-By", f"Implementation-Version: {build}\r\nCreated-By"))
        os.utime(path, ns=(later, later))
        return path

    def test_the_build_checked_in_code(self):
        self.assertEqual(simjar.CHECKED_BUILDS.keys(), simjar.CHECKED)
        forge_jar = self.forge_jar("2.0.15-SNAPSHOT-09.28")
        self.assertEqual(simjar.readiness(self.java, "2.0.15", forge_jar), {"ready": True, "problem": None})
        self.assertTrue(self.card_log()["ready"])

    def test_another_build_under_the_same_name(self):
        forge_jar = self.forge_jar("2.0.15-SNAPSHOT-10.02")
        problem = ("This Forge 2.0.15 is build 2.0.15-SNAPSHOT-10.02, not the 2.0.15-SNAPSHOT-09.28 the card log "
                   "was checked with (python -m decklab.lib.forge cardlog-check checks it).")
        self.assertEqual(simjar.readiness(self.java, "2.0.15", forge_jar), {"ready": False, "problem": problem})
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})    # no jar: version only
        self.assertEqual(self.card_log(), {"ready": False, "problem": problem})
        self.assertEqual(self.builds, [])
        self.assertTrue(self.card_log(checking=True)["ready"])
        simjar.record_checked("2.0.15", 20, simjar.forge_build(forge_jar))      # what cardlog-check notes
        self.assertEqual(simjar.readiness(self.java, "2.0.15", forge_jar), {"ready": True, "problem": None})
        self.assertTrue(self.card_log()["ready"])
        self.forge_jar("2.0.15-SNAPSHOT-09.28")         # the latest check is what counts now
        self.assertIn("is build 2.0.15-SNAPSHOT-09.28, not the 2.0.15-SNAPSHOT-10.02",
                      simjar.readiness(self.java, "2.0.15", forge_jar)["problem"])

    def test_a_recorded_version_without_a_build_takes_any(self):
        simjar.record_checked("2.0.16", 20)
        forge_jar = self.forge_jar("2.0.16-SNAPSHOT-11.01")
        self.assertEqual(simjar.readiness(self.java, "2.0.16", forge_jar), {"ready": True, "problem": None})

    def test_a_jar_whose_build_cant_be_read_is_unchecked_when_a_build_was_checked(self):
        forge_jar = self.forge_dir / JAR_NAME
        later = forge_jar.stat().st_mtime_ns + 5_000_000_000
        write_jar(forge_jar)                                    # no Implementation-Version
        os.utime(forge_jar, ns=(later, later))
        self.assertIsNone(simjar.forge_build(forge_jar))
        problem = ("This Forge 2.0.15's build can't be read from its jar, so Deck Lab can't tell it's the "
                   "2.0.15-SNAPSHOT-09.28 the card log was checked with (python -m decklab.lib.forge cardlog-check "
                   "checks it).")
        self.assertEqual(simjar.readiness(self.java, "2.0.15", forge_jar), {"ready": False, "problem": problem})
        self.assertEqual(self.card_log(), {"ready": False, "problem": problem})
        self.assertEqual(self.builds, [])
        simjar.record_checked("2.0.15", 20, simjar.forge_build(forge_jar))     # a check of this jar: build None
        self.assertEqual(simjar.readiness(self.java, "2.0.15", forge_jar), {"ready": True, "problem": None})
        simjar.record_checked("2.0.16", 20, "2.0.16-SNAPSHOT-11.01")           # and one that names a build
        self.assertEqual(simjar.readiness(self.java, "2.0.16", forge_jar), {"ready": False, "problem":
                         simjar.unknown_build_problem("2.0.16", "2.0.16-SNAPSHOT-11.01")})


# ============================================================ the DeckLabSim source checked

class SourceCheckedTests(SimjarCase):
    """A check counts only for the DeckLabSim source it checked: an edit to the source turns
    the card log off until cardlog-check passes with it."""

    def edit(self, text="class DeckLabSim { int x; }\n"):
        self.source.write_text(text, encoding="utf-8")

    def test_crlf_is_the_same_source(self):
        crlf = simjar.source_sha256(b"class A {\r\n}\r\n")
        self.assertEqual(crlf, simjar.source_sha256(b"class A {\n}\n"))
        self.assertEqual(crlf, hashlib.sha256(b"class A {\n}\n").hexdigest())
        self.source.write_bytes(b"class DeckLabSim {}\r\n")         # a Windows checkout of the same source
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})

    def test_an_edited_source_is_unchecked_until_a_check_passes_with_it(self):
        simjar.record_checked("2.0.16", 20)
        self.assertEqual(simjar.checked_versions(), {"2.0.15", "2.0.16"})
        old = self.sha()
        self.edit()
        for version in ("2.0.15", "2.0.16"):        # CHECKED's and checked.json's
            self.assertEqual(simjar.readiness(self.java, version),
                             {"ready": False, "problem": simjar.changed_problem(version)})
        self.assertEqual(simjar.checked_versions(), set())
        self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.changed_problem("2.0.15")})
        self.assertEqual(self.builds, [])
        simjar.record_checked("2.0.15", 20, "2.0.15-SNAPSHOT-09.28")      # cardlog-check passed with the edit
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})
        self.assertTrue(self.card_log()["ready"])
        self.assertEqual(simjar.checked_versions(), {"2.0.15"})
        saved = json.loads((self.data / "cardlog" / "checked.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["versions"]["2.0.15"]["source_sha256"], saved["versions"]["2.0.16"]["source_sha256"]),
                         (self.sha(), old))
        # Back to the source in CHECKED_SOURCE: its check counts again, whatever checked.json says
        # about the edit.
        self.edit("class DeckLabSim {}\n")
        self.assertEqual(simjar.checked_versions(), {"2.0.15", "2.0.16"})
        simjar.record_failed("2.0.16", 20)
        self.assertEqual(simjar.checked_versions(), {"2.0.15"})

    def test_a_failed_check_of_another_source_doesnt_count(self):
        self.edit()
        simjar.record_failed("2.0.15", 20)
        self.edit("class DeckLabSim {}\n")
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})

    def test_a_check_noted_without_a_source_is_unchecked(self):
        # As in a checked.json written before sources were noted.
        path = self.data / "cardlog" / "checked.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"versions": {"2.0.16": {"when": "x", "games": 20, "build": null}}}', encoding="utf-8")
        self.assertEqual(simjar.readiness(self.java, "2.0.16"),
                         {"ready": False, "problem": simjar.changed_problem("2.0.16")})
        self.assertEqual(simjar.checked_versions(), {"2.0.15"})

    def test_a_source_that_cant_be_read(self):
        self.source.unlink()
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": False, "problem": simjar.NO_SOURCE})
        self.assertEqual(simjar.checked_versions(), set())
        self.assertEqual(self.card_log(), {"ready": False, "problem": "The card log couldn't be built for Forge 2.0.15."})
        with self.assertRaises(forge.ForgeError):
            simjar.record_checked("2.0.15", 20)
        with self.assertRaises(ValueError):
            simjar.record_checked("2.0.15", 20, None, "not a hash")


class CheckedSourceTests(unittest.TestCase):

    def test_checked_source_is_the_source_in_the_repo(self):
        """CHECKED_SOURCE must be the card log's source_sha256() as it is now (Deck Lab's Java
        sources). When this fails, one of them was edited: run
        "python -m decklab.lib.forge cardlog-check" with the edit (with real Forge), and when
        it passes, put the new source_sha256() in CHECKED_SOURCE. Until then runs don't use
        the card log, as no check has been made of the edited source."""
        self.assertEqual(simjar.CHECKED_SOURCE.keys(), simjar.CHECKED)
        for version, sha in simjar.CHECKED_SOURCE.items():
            self.assertEqual(sha, simjar.source_sha256(), version)


# ============================================================ wave 3 (J3): deck-order-1, own classes, pilots

OWN = ("decklab/DeckOrder.class", "decklab/Pilots.class", "decklab/TeamPumpAi.class", "decklab/AiPatches.class",
       "decklab/Startup.class")
SWITCHES = {"team-pump-1": "decklab/TeamPumpAi.class", "aisim-hybrid-1": "decklab/GameLoop.class"}


class Wave3ListTests(unittest.TestCase):
    """Deck Lab's own classes and the pilot switches (sim-wave3-contract.md 3.6)."""

    def test_own_classes(self):
        self.assertEqual(simjar.OWN_CLASSES, OWN)
        names = {p.name for p in simjar.deck_lab_sources()}
        for name in OWN:
            self.assertIn(Path(name).stem + ".java", names)
            self.assertIn(name, simjar.CLASSES)
        self.assertEqual(simjar._classes(), simjar.SIM_CLASSES + OWN)

    def test_the_switches_are_javas(self):
        self.assertEqual(simjar.PILOT_SWITCHES, SWITCHES)
        self.assertEqual(simjar.pilot_switch_ids(), ["aisim-hybrid-1", "team-pump-1"])
        for switch, cls in simjar.PILOT_SWITCHES.items():
            self.assertRegex(switch, simjar.GAME_PATCH_ID)
            self.assertIn(cls, simjar.SIM_CLASSES + simjar.OWN_CLASSES)     # Deck Lab's own: always in the jar
        java = (simjar.JAVA / "decklab" / "Pilots.java").read_text(encoding="utf-8")
        m = re.search(r"static final List<String> AVAILABLE = List\.of\(([^)]*)\);", java)
        self.assertIsNotNone(m)
        self.assertEqual(re.findall(r'"([^"]+)"', m[1]), sorted(simjar.PILOT_SWITCHES))
        self.assertIn(f'PILOT_SWITCH_LIST', (simjar.JAVA.parent / "simjar.py").read_text(encoding="utf-8"))

    def test_the_card_logs_source_covers_the_new_files(self):
        data = simjar._source_bytes()
        for name in ("DeckOrder.java", "Pilots.java", "TeamPumpAi.java", "AiPatches.java", "Startup.java"):
            self.assertIn(f"decklab/{name}\0".encode(), data)

    def test_no_copies_of_forges_classes(self):
        """Deck Lab's changes to Forge's classes are in its fork of Forge since 2026-10-11."""
        self.assertFalse((simjar.JAVA / "forge").exists())
        self.assertEqual({p.parent.name for p in simjar.deck_lab_sources()}, {"decklab"})
        for name in simjar.CLASSES:
            self.assertTrue(name.startswith("decklab/"), name)


# The fork's list of AI switches in a Forge jar (simjar.FORK_SWITCH_LIST, AI round 1), as the fork's
# decklab/ai-switches.txt has it: comments, then "<id> <class file>..." lines.
SWITCH_LIST = ("# Deck Lab's AI switches in this Forge build\r\n"
               "removal-in-combat-1 forge/ai/ComputerUtilCard.class\r\n"
               "etb-harmless-1 forge/ai/ability/ChangeZoneAi.class forge/ai/ability/DestroyAllAi.class\r\n"
               "prowess-precombat-1 forge/ai/ComputerUtil.class forge/ai/ProwessFirst.class\r\n"
               "Not_An_Id forge/ai/X.class\r\n")
FORK = Path(os.environ.get("DECKLAB_FORGE_FORK") or Path(__file__).resolve().parents[2].parent / "forge")


class ForkSwitchTests(SimjarCase):
    """AI round 1: the fork's AI switches in Forge's jar (fork_switches), in card_log()'s "pilot_switches"
    and the stamp, and in status()'s (install._overrides_status)."""

    def with_switches(self, text=SWITCH_LIST, patch_list=PATCH_LIST):
        with zipfile.ZipFile(self.forge_dir / JAR_NAME, "w") as z:
            z.writestr("META-INF/MANIFEST.MF", FORGE_MANIFEST)
            z.writestr(simjar.FORGE_PATCH_LIST, patch_list)
            z.writestr(simjar.FORK_SWITCH_LIST, text)

    def test_fork_switches(self):
        jar = self.forge_dir / JAR_NAME
        self.assertEqual(simjar.fork_switches(jar), [])                     # a build from before AI round 1
        self.with_switches()
        self.assertEqual(simjar.fork_switches(jar), ["etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1"])
        self.assertEqual(simjar.fork_switches(self.tmp / "nowhere.jar"), [])
        (self.tmp / "bad.jar").write_bytes(b"not a zip")
        self.assertEqual(simjar.fork_switches(self.tmp / "bad.jar"), [])
        self.assertEqual(simjar._parse_switch_list("a-1 x.class\na-1 y.class\n# b-2\n  \n"), ["a-1"])

    def test_card_logs_pilot_switches(self):
        self.assertEqual(self.card_log()["pilot_switches"], ["aisim-hybrid-1", "team-pump-1"])
        self.with_switches()
        found = self.card_log()
        self.assertEqual(found["pilot_switches"], ["aisim-hybrid-1", "etb-harmless-1", "prowess-precombat-1",
                                                   "removal-in-combat-1", "team-pump-1"])
        self.assertEqual(Path(found["jar"]), self.jar().resolve())      # the stamp names them: a jar of its own
        stamp = json.loads(self.jar().with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(stamp["fork_switches"], ["etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1"])

    def test_duplicate_game_patch_ids_collapse(self):
        self.with_switches(patch_list=PATCH_LIST + "forge/ai/ComputerUtil.class gisa-bontu-1\r\n"
                                                   "forge/ai/ability/TokenAi.class gisa-bontu-1\r\n")
        self.assertEqual(self.card_log()["game_patches"],
                         ["attack-requirements-in-order-1", "deck-order-1", "gisa-bontu-1"])

    def test_status_lists_the_builds_switches(self):
        self.with_switches()
        jar = self.forge_dir / JAR_NAME
        with mock.patch.object(forge.overrides, "ensure_deployed"), \
                mock.patch.object(forge.overrides, "status", return_value={"deployed": [], "stale": [], "hash": None}):
            _, ready = forge.install._overrides_status({"ready": True, "card_log": {"ready": True}}, jar)
            _, unready = forge.install._overrides_status({"ready": True, "card_log": {"ready": False}}, jar)
        self.assertEqual(ready, ["aisim-hybrid-1", "etb-harmless-1", "prowess-precombat-1", "removal-in-combat-1",
                                 "team-pump-1"])
        self.assertEqual(unready, [])

    def test_the_forks_list_is_deck_labs(self):
        """The fork's decklab/ai-switches.txt (DECKLAB_FORGE_FORK, default C:/VSProjects/forge) names exactly
        pilots.FORK_SWITCHES."""
        path = FORK / "forge-ai" / "src" / "main" / "resources" / "decklab" / "ai-switches.txt"
        if not path.is_file():
            self.skipTest(f"the fork at {FORK} has no {path.name} (DECKLAB_FORGE_FORK)")
        found = simjar._parse_switch_list(path.read_text(encoding="utf-8"))
        self.assertEqual(found, sorted(forge.pilots.FORK_SWITCHES))
        self.assertEqual(sorted(forge.pilots.FORK_SWITCHES), list(forge.pilots.FORK_SWITCHES))
        for switch in found:
            self.assertRegex(switch, simjar.PILOT_SWITCH_ID)
            self.assertIn(switch, forge.pilots.SWITCH_WORDS)


class Wave3BuildTests(SimjarCase):
    """card_log()'s pilot switches and the jar's list of them."""

    def test_card_log_lists_the_switches(self):
        found = self.card_log()
        self.assertEqual(found["pilot_switches"], ["aisim-hybrid-1", "team-pump-1"])
        stamp = json.loads(Path(found["jar"]).with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(stamp["pilot_switches"], ["aisim-hybrid-1", "team-pump-1"])

    def test_the_jar_lists_the_switches(self):
        listed = {}

        def run(argv, **kwargs):
            if "--create" in argv:
                classes = Path(argv[argv.index("-C") + 1])
                listed["switches"] = (classes / simjar.PILOT_SWITCH_LIST).read_text(encoding="utf-8")
                listed["files"] = sorted(str(f.relative_to(classes)).replace("\\", "/")
                                         for f in classes.rglob("*") if f.is_file())
                write_jar(Path(argv[argv.index("--file") + 1]), names=simjar.CLASSES)
            elif "-d" in argv:
                listed["sources"] = [Path(a).name for a in argv if a.endswith(".java")]
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(simjar, "_build", REAL_BUILD), mock.patch.object(simjar.subprocess, "run", run):
            self.assertTrue(self.card_log()["ready"])
        self.assertEqual(listed["switches"], "aisim-hybrid-1\nteam-pump-1\n")
        self.assertEqual(listed["files"], [simjar.PILOT_SWITCH_LIST])       # javac wrote nothing here
        self.assertEqual(listed["sources"], ["DeckLabSim.java"])            # SOURCE alone, no copies


class ForgePatchesTests(SimjarCase):
    """Deck Lab's changes in Forge's jar: its list (FORGE_PATCH_LIST), and a jar without one."""

    def test_the_list_is_read(self):
        jar = self.forge_dir / JAR_NAME
        self.assertEqual(simjar.forge_patches(jar), PATCHES)
        self.assertEqual(list(simjar.forge_patches(jar)), sorted(PATCHES))
        self.assertEqual(simjar.game_patch_ids(simjar.forge_patches(jar)),
                         {"forge/ai/AiAttackController.class": "attack-requirements-in-order-1",
                          "forge/game/Match.class": "deck-order-1"})

    def test_lines_that_arent_a_change_are_passed_over(self):
        text = ("# a comment\nforge/A.class\nforge/B.class two words here\nforge/C.class Not-An-Id\n"
                "notaclass id-1\n  forge/D.class   d-1   # with a comment\nforge/E.class -\n")
        self.assertEqual(simjar._parse_patch_list(text), {"forge/D.class": "d-1", "forge/E.class": None})
        self.assertEqual(simjar._parse_patch_list(""), {})

    def test_kept_until_the_jar_changes(self):
        jar = self.forge_dir / JAR_NAME
        self.assertEqual(simjar.forge_patches(jar), PATCHES)
        with mock.patch.object(simjar.zipfile, "ZipFile", side_effect=AssertionError("read again")):
            self.assertEqual(simjar.forge_patches(jar), PATCHES)
        write_jar(jar, manifest=FORGE_MANIFEST, patch_list="forge/game/Match.class deck-order-2\n")
        os.utime(jar, ns=(time.time_ns(), time.time_ns() + 10**9))
        self.assertEqual(simjar.forge_patches(jar), {"forge/game/Match.class": "deck-order-2"})

    def test_a_jar_that_cant_be_read_has_none_and_isnt_kept(self):
        jar = self.forge_dir / JAR_NAME
        jar.write_bytes(b"not a zip")
        self.assertEqual(simjar.forge_patches(jar), {})
        self.assertNotIn(str(jar), simjar._forge_patches)
        self.assertEqual(simjar.forge_patches(self.forge_dir / "missing.jar"), {})

    def test_a_stock_forge_gets_no_card_log(self):
        write_jar(self.forge_dir / JAR_NAME, manifest=FORGE_MANIFEST, patch_list=None)
        self.assertEqual(simjar.forge_patches(self.forge_dir / JAR_NAME), {})
        self.assertEqual(self.card_log(), {"ready": False, "problem": simjar.NOT_FORK})
        self.assertEqual(self.card_log(checking=True), {"ready": False, "problem": simjar.NOT_FORK})
        self.assertEqual(self.builds, [])
        self.assertEqual(self.readiness(), {"ready": False, "problem": simjar.NOT_FORK})
        # without the jar's path (status() always gives it), readiness() can't tell
        self.assertEqual(simjar.readiness(self.java, "2.0.15"), {"ready": True, "problem": None})

    def test_a_changed_list_builds_another_jar(self):
        first = self.card_log()
        jar = self.forge_dir / JAR_NAME
        write_jar(jar, manifest=FORGE_MANIFEST, patch_list=PATCH_LIST.replace("deck-order-1", "deck-order-2"))
        os.utime(jar, ns=(time.time_ns(), time.time_ns() + 10**9))     # the same size: a new time
        second = self.card_log()
        self.assertTrue(second["ready"])
        self.assertNotEqual(second["jar"], first["jar"])
        self.assertEqual(second["game_patches"], ["attack-requirements-in-order-1", "deck-order-2"])


# ============================================================ the real JDK

@unittest.skipUnless(REAL, "set DECKLAB_FORGE_TESTS=1 to build the card log's jar with the real JDK and Forge")
class RealBuildTests(unittest.TestCase):

    def test_the_real_jar(self):
        settings = forge.common._settings()
        java = forge.find_java(settings.get("forge_java"))
        jar_name, version = forge.install._find_jar(Path(settings["forge_dir"]))
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.object(forge.common, "DATA_DIR", tmp / "data"):
            simjar._built.clear()
            self.addCleanup(simjar._built.clear)
            t0 = time.monotonic()
            found = simjar.card_log(str(java), settings["forge_dir"], jar_name, version, checking=True)
            took = time.monotonic() - t0
            self.assertTrue(found["ready"], found.get("problem"))
            # Every patch's class too, not only those that fit: this fails on purpose once the
            # installed Forge no longer holds a class file a patch was copied from (PATCHES), as
            # a reminder to make that copy again from the new Forge's source.
            with zipfile.ZipFile(found["jar"]) as z:
                self.assertTrue(set(simjar.CLASSES) <= set(z.namelist()))
            self.assertIn("java.desktop/java.beans=ALL-UNNAMED", found["add_opens"])
            self.assertLess(took, 60)
            stamp_file = Path(found["jar"]).with_suffix(".json")
            self.assertEqual(stamp_file.name, f"decklab-sim-{version}-"
                                              f"{stamp_hash(json.loads(stamp_file.read_text(encoding='utf-8')))}.json")
            stamp = stamp_file.stat().st_mtime_ns
            simjar._built.clear()
            self.assertEqual(simjar.card_log(str(java), settings["forge_dir"], jar_name, version, checking=True), found)
            self.assertEqual(stamp_file.stat().st_mtime_ns, stamp)


if __name__ == "__main__":
    unittest.main()
