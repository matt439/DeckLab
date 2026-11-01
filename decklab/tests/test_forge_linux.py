"""Forge off Windows: the user folder through -Duser.home and its links, nice, find_java's
search and Java's own tools, pinning's honest off state, the forge_dir default, the slots'
XDG folder and the upgrade plan's folders. Each OS's branch runs on both CI systems (the OS
check is patched); only the live nice check needs a POSIX system."""
import importlib.util
import os
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, forge
from decklab.lib.forge import cli_upgrade, cores, processes, runner_launch, slots
from decklab.tests.test_forge import FAKE, ForgeCase, setUpModule, tearDownModule  # noqa: F401


def can_symlink(folder):
    """Whether this system lets the tests make a folder link in folder (Windows needs a privilege)."""
    probe = Path(folder) / "symlink-probe"
    try:
        os.symlink("target", probe, target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


def load_fake():
    """The fake Forge as a module, in this process."""
    spec = importlib.util.spec_from_file_location("decklab_fake_forge_linux", FAKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UserHomeTests(ForgeCase):
    """runner_launch's user.home: Forge's own rule is APPDATA on Windows and <user.home>/.forge
    elsewhere, so off Windows every launch gets -Duser.home and its links lead back."""

    def setUp(self):
        super().setUp()
        self.user = self.tmp / "user"

    def off_windows(self):
        p = mock.patch.object(runner_launch, "_windows", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def test_every_launch_off_windows_carries_the_user_home(self):
        setup = {"java": "java", "xmx": "1g", "user_dir": self.user}
        with mock.patch.object(runner_launch, "_windows", return_value=True):
            self.assertEqual(forge.runner.user_home_flags(setup), [])
            self.assertFalse(any(a.startswith("-Duser.home=") for a in forge.runner._java(setup)))
        self.off_windows()
        flag = f"-Duser.home={self.user / 'home'}"
        self.assertEqual(forge.runner.user_home_flags(setup), [flag])
        self.assertIn(flag, forge.runner._java(setup))
        self.assertEqual(forge.runner.user_home_flags({"java": "java"}), [])     # no user folder: none

    def test_the_links_lead_to_the_runs_forge_folder(self):
        if not can_symlink(self.tmp):
            self.skipTest("this system doesn't let the tests make links")
        self.off_windows()
        env = forge._prepare_user_dir(self.user)
        self.assertEqual(env["APPDATA"], str(self.user))         # kept: harmless off Windows
        for place, target in runner_launch._home_layout(self.user):
            self.assertTrue(place.is_symlink(), place)
            self.assertFalse(os.path.isabs(os.readlink(place)))   # relative: the folder can move
            self.assertEqual(place.resolve(), target.resolve())
        if sys.platform != "darwin":
            self.assertEqual((self.user / "home" / ".forge").resolve(), (self.user / "Forge").resolve())
            self.assertEqual((self.user / "home" / ".cache" / "forge").resolve(),
                             (self.user / "Forge" / "Cache").resolve())
        prefs = self.user / "home" / ".forge" / "preferences" / "forge.preferences"
        if sys.platform != "darwin":
            self.assertIn("PERFORMANCE_MODE=true", prefs.read_text(encoding="utf-8"))
        # A link that leads elsewhere is put right; one in place is left alone.
        place = runner_launch._home_layout(self.user)[0][0]
        place.unlink()
        os.symlink("elsewhere", place, target_is_directory=True)
        forge._prepare_user_dir(self.user)
        forge._prepare_user_dir(self.user)
        self.assertEqual(place.resolve(), (self.user / "Forge").resolve())

    def test_where_links_cant_be_made_the_folder_is_a_copy(self):
        self.off_windows()
        logged = []
        forge.overrides._logged.clear()
        self.addCleanup(forge.overrides._logged.clear)
        with mock.patch.object(runner_launch.os, "symlink", side_effect=OSError("no links here")), \
                mock.patch.object(forge.common, "_log", logged.append):
            forge._prepare_user_dir(self.user)
            forge._prepare_user_dir(self.user)
        place, target = runner_launch._home_layout(self.user)[0]
        self.assertTrue(place.is_dir() and not place.is_symlink())
        self.assertEqual((place / "preferences" / "forge.preferences").read_bytes(),
                         (target / "preferences" / "forge.preferences").read_bytes())
        self.assertEqual(len([line for line in logged if "can't be linked" in line]), 2)   # once a place
        # Forge's logs in the copy go too, after a run.
        (place / "forge.log").write_text("x", encoding="utf-8")
        forge.runner._tidy_user_dir(self.user)
        self.assertFalse((place / "forge.log").exists())

    def test_a_copy_holds_exactly_the_overrides(self):
        source, copy = self.tmp / "source", self.tmp / "copy"
        cards = source / "custom" / "cards"
        (cards / "a").mkdir(parents=True)
        (cards / "a" / "one.txt").write_bytes(b"Name:One\r\n")
        (source / "preferences").mkdir()
        (source / "preferences" / "forge.preferences").write_text("PERFORMANCE_MODE=true\n", encoding="utf-8")
        (copy / "custom" / "cards").mkdir(parents=True)
        (copy / "custom" / "cards" / "stale.txt").write_text("old", encoding="utf-8")
        runner_launch._mirror(source, copy)
        self.assertEqual((copy / "custom" / "cards" / "a" / "one.txt").read_bytes(), b"Name:One\r\n")
        self.assertFalse((copy / "custom" / "cards" / "stale.txt").exists())
        self.assertEqual((copy / "preferences" / "forge.preferences").read_text(encoding="utf-8"),
                         "PERFORMANCE_MODE=true\n")

    def test_the_fake_forge_follows_forges_rule_for_each_os(self):
        self.off_windows()
        if not can_symlink(self.tmp):
            for p in (mock.patch.object(runner_launch.os, "symlink", side_effect=OSError("no links here")),
                      mock.patch.object(forge.common, "_log", lambda text: None)):
                p.start()
                self.addCleanup(p.stop)
        forge._prepare_user_dir(self.user)
        fake = load_fake()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        system = "darwin" if sys.platform == "darwin" else "linux"
        with mock.patch.dict(os.environ, {"FAKE_FORGE_OS": system, "APPDATA": str(self.user)}):
            fake.PROCESS["user_home"] = str(self.user / "home")
            self.assertEqual(fake.profile_dir(), runner_launch._home_layout(self.user)[0][0])
            self.assertTrue(fake.performance_mode())
            self.assertEqual(fake.overrides_hash(), forge.overrides.deployed_hash(self.user))
            fake.PROCESS["user_home"] = str(elsewhere)        # APPDATA alone doesn't count off Windows
            self.assertFalse(fake.performance_mode())
        with mock.patch.dict(os.environ, {"FAKE_FORGE_OS": "windows", "APPDATA": str(self.user)}):
            self.assertEqual(fake.profile_dir(), self.user / "Forge")
            self.assertTrue(fake.performance_mode())
        with mock.patch.dict(os.environ, {"FAKE_FORGE_OS": "windows"}):
            os.environ.pop("APPDATA", None)
            self.assertEqual(fake.profile_dir(), elsewhere / ".forge" / "Forge")
        # The start-up reads -Duser.home from the command line, and it's no request argument.
        fake.start_process([f"-Duser.home={self.user / 'home'}", "serve"])
        self.assertEqual(fake.PROCESS["user_home"], str(self.user / "home"))


class NiceTests(unittest.TestCase):
    """processes.start_process off Windows: the command starts through nice -n 10."""

    def platform(self, name):
        for p in (mock.patch.object(processes, "sys", types.SimpleNamespace(platform=name)),
                  mock.patch.object(processes, "_nice", None)):
            p.start()
            self.addCleanup(p.stop)

    def test_the_command_line_off_windows(self):
        self.platform("linux")
        which = {"nice": "/usr/bin/nice", "/opt/jdk/bin/java": "/opt/jdk/bin/java"}
        with mock.patch.object(processes.shutil, "which", side_effect=which.get):
            self.assertEqual(processes._niced(["/opt/jdk/bin/java", "-version"]),
                             ["/usr/bin/nice", "-n", "10", "/opt/jdk/bin/java", "-version"])
            with self.assertRaises(FileNotFoundError):         # as Popen says, not nice's exit 127
                processes._niced(["/opt/missing/bin/java"])

    def test_without_nice_it_runs_at_normal_priority(self):
        self.platform("linux")
        logged = []
        with mock.patch.object(processes.shutil, "which", return_value=None), \
                mock.patch.object(processes.common, "_log", logged.append):
            self.assertEqual(processes._niced(["/opt/missing/bin/java"]), ["/opt/missing/bin/java"])
            processes._niced(["java"])
        self.assertEqual(len(logged), 1)
        self.assertIn("normal priority", logged[0])

    def test_windows_keeps_its_command_line(self):
        self.platform("win32")
        with mock.patch.object(processes.shutil, "which", return_value="/usr/bin/nice"):
            self.assertEqual(processes._nice_prefix(), [])
            self.assertEqual(processes._niced(["java.exe"]), ["java.exe"])

    @unittest.skipIf(sys.platform == "win32" or not shutil.which("nice"), "needs a POSIX system with nice")
    def test_a_real_start_is_niced_and_keeps_its_pid(self):
        with mock.patch.object(processes, "_nice", None):
            proc = processes.start_process([sys.executable, "-c", "import os; print(os.getpid(), os.nice(0))"])
            out, _ = proc.communicate(timeout=30)
        pid, niceness = map(int, out.split())
        self.assertEqual(pid, proc.pid)                        # nice ran the program in its own place
        self.assertEqual(niceness, min(19, os.nice(0) + processes.FORGE_NICE))


class FindJavaOffWindowsTests(unittest.TestCase):
    """install.find_java's search off Windows: JAVA_HOME, the usual JDK folders and the PATH's
    java, Java 21 or later first, a JDK before a JRE, then the newest."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "jvm"
        self.root.mkdir()
        self.which = mock.Mock(return_value=None)
        for p in (mock.patch.object(forge.install, "_windows", return_value=False),
                  mock.patch.object(forge.install, "_posix_java_roots", return_value=((self.root, "*"),)),
                  mock.patch.object(forge.install.shutil, "which", self.which),
                  mock.patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("JAVA_HOME", None)

    def jdk(self, name, version, javac=True, root=None):
        home = (root or self.root) / name
        (home / "bin").mkdir(parents=True)
        (home / "bin" / "java").write_bytes(b"")
        if javac:
            (home / "bin" / "javac").write_bytes(b"")
        if version is not None:
            (home / "release").write_text(f'IMPLEMENTOR="Test"\nJAVA_VERSION="{version}"\n', encoding="utf-8")
        return home / "bin" / "java"

    def test_the_newest_jdk_of_java_21_or_later_first(self):
        self.jdk("java-17-openjdk", "17.0.2")
        jre = self.jdk("java-21-jre", "21.0.5", javac=False)
        newest = self.jdk("java-25-openjdk", "25.0.1")
        unknown = self.jdk("custom-jdk", None)
        self.assertEqual(forge.find_java(), newest)
        shutil.rmtree(newest.parent.parent)
        self.assertEqual(forge.find_java(), jre)           # Java 21's JRE before an unknown version
        shutil.rmtree(jre.parent.parent)
        self.assertEqual(forge.find_java(), unknown)       # one without a release file still runs
        shutil.rmtree(unknown.parent.parent)
        self.assertIsNone(forge.find_java())
        problem = forge.install.no_java_problem()
        self.assertIn("Java 21 or later wasn't found, so Forge can't run", problem)
        self.assertIn("Java 17 at", problem)

    def test_java_home_and_the_path_are_searched_too(self):
        elsewhere = self.tmp / "elsewhere"
        home_java = self.jdk("jdk-22", "22", root=elsewhere)
        os.environ["JAVA_HOME"] = str(home_java.parent.parent)
        self.assertEqual(forge.find_java(), home_java)
        os.environ.pop("JAVA_HOME")
        self.which.return_value = str(home_java)
        self.assertEqual(forge.find_java().resolve(), home_java.resolve())
        self.which.return_value = None
        self.assertIsNone(forge.find_java())
        self.assertEqual(forge.install.no_java_problem(), "Java wasn't found, so Forge can't run.")
        self.assertEqual(forge.install.no_java_problem("/configured/java"), "Java wasn't found, so Forge can't run.")

    def test_the_release_file(self):
        for text, version in (('JAVA_VERSION="21"', 21), ('JAVA_VERSION="1.8.0_432"', 8),
                              ('JAVA_VERSION="25.0.1+9"', 25), ('JAVA_VERSION="21"\nJAVA_VERSION="17"', None),
                              ('IMPLEMENTOR="x"', None), ('JAVA_VERSION="abc"', None)):
            with self.subTest(text=text):
                (self.tmp / "release").write_text(text + "\n", encoding="utf-8")
                self.assertEqual(forge.install.java_release(self.tmp), version)
        self.assertIsNone(forge.install.java_release(self.tmp / "missing"))

    @unittest.skipIf(os.name == "nt", "Windows takes java's tools beside it as given")
    def test_the_tools_are_the_linked_javas_own(self):
        real = self.jdk("jdk-21", "21")
        (real.parent / "jar").write_bytes(b"")
        links = self.tmp / "usr-bin"
        links.mkdir()
        os.symlink(real, links / "java")
        (links / "javac").write_bytes(b"")              # another JDK's alternative
        self.assertEqual(forge.simjar._tool(links / "java", "javac"), (real.parent / "javac").resolve())
        self.assertEqual(forge.simjar._tool(links / "java", "jar"), (real.parent / "jar").resolve())


class PinOffWindowsTests(unittest.TestCase):

    def test_pinning_says_once_that_it_works_only_on_windows(self):
        logged = []
        cores._said.clear()
        self.addCleanup(cores._said.clear)
        with mock.patch.object(cores, "sys", types.SimpleNamespace(platform="linux")), \
                mock.patch.object(forge.common, "_settings", return_value={"forge_pin": True}), \
                mock.patch.object(forge.common, "_log", logged.append), \
                mock.patch.dict(os.environ, {}):
            os.environ.pop("DECKLAB_PIN_MODE", None)
            self.assertFalse(cores.pin(os.getpid() + 1, 0))
            self.assertFalse(cores.pin(os.getpid() + 1, 1))
        self.assertEqual(len(logged), 1, logged)
        self.assertIn("works only on Windows", logged[0])


class DefaultsTests(unittest.TestCase):

    def test_the_forge_folders_default_for_each_os(self):
        self.assertEqual(config._default_forge_dir(windows=True), r"C:\Tools\forge-decklab")
        self.assertEqual(config._default_forge_dir(windows=False), str(Path.home() / "tools" / "forge-decklab"))
        self.assertEqual(config.DEFAULTS["forge_dir"], config._default_forge_dir())

    def test_the_slots_folder_ignores_xdg_data_home(self):
        # One folder for every process on the PC: the server's service has no XDG_DATA_HOME even
        # when a login shell sets it, and both must lock the same slots.
        base = Path(__file__).resolve().parent / "xdg-data"      # only worked out: nothing is made
        share = Path(os.path.expanduser("~")) / ".local" / "share" / "DeckLab" / "forge-slots"
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(base)}):
            for name in (slots.ENV, "LOCALAPPDATA"):
                os.environ.pop(name, None)
            self.assertEqual(slots.folder(), share)
            os.environ.pop("XDG_DATA_HOME")
            self.assertEqual(slots.folder(), share)
            os.environ["LOCALAPPDATA"] = str(base / "local")      # Windows' own folder first
            self.assertEqual(slots.folder(), base / "local" / "DeckLab" / "forge-slots")
            os.environ[slots.ENV] = str(base / "named")
            self.assertEqual(slots.folder(), base / "named")


class UpgradePlanTests(unittest.TestCase):

    def test_the_plan_names_each_oss_folders(self):
        windows = cli_upgrade._plan("forge-2.0.16", windows=True)
        for words in ("In C:\\Projects\\forge, rebase", "Maven is at C:\\Tools\\maven",
                      "engine-check --old C:/Tools/forge-decklab", "(it installs C:\\Tools\\forge-decklab)"):
            self.assertIn(words, windows)
        with mock.patch.object(forge.common, "_settings", return_value={"forge_dir": "/home/u/tools/forge-x"}):
            linux = cli_upgrade._plan("forge-2.0.16", "/tmp/stage", windows=False)
        self.assertNotRegex(linux, r"[A-Z]:[\/]")              # no Windows folder
        for words in ("In the fork's clone, rebase", "mvn on the PATH", "engine-check --old /home/u/tools/forge-x "
                      "--new /tmp/stage", "--out /home/u/tools/forge-x there"):
            self.assertIn(words, linux)


if __name__ == "__main__":
    unittest.main()
