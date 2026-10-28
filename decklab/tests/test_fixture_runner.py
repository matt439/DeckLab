"""Guard-order regressions use only fake projects/connectors/files in disposable subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).absolute().parents[2]


class FixtureRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="decklab-fixture-runner-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("fixture_runtime.py", "test_fixtures.py", "test_shard.py"):
            self.write("scripts/" + name, (ROOT / "scripts" / name).read_text(encoding="utf-8"))
        for name in ("decklab/__init__.py", "decklab/lib/__init__.py"):
            self.write(name, "")
        self.write("decklab/config.json", "FAKE PRIVATE CANARY")
        self.write("home/.pgpass", "FAKE CREDENTIAL CANARY")
        self.write("roaming/postgresql/pgpass.conf", "FAKE WINDOWS CANARY")
        self.write("secrets/pgpass-extra.conf", "FAKE OVERRIDE CANARY")
        self.write("secrets/pg-service.conf", "FAKE SERVICE CANARY")
        self.write("extra.json", "FAKE OVERLAY CANARY")
        self.write("decklab/lib/config.py", "from pathlib import Path\nCONFIG_FILE = Path(__file__).parent.parent / 'config.json'\n")
        self.write("decklab/lib/venv.py", "import os, site, sys\ndef activate():\n"
                   "    path = os.environ['FAKE_PACKAGES']\n"
                   "    if path not in sys.path: site.addsitedir(path)\n")
        self.write("packages/canary.pth", "import os; open(os.environ['PTH_MARKER'], 'w').write('executed')\n")
        self.write("psycopg.py", r"""
            import os
            from pathlib import Path
            class OperationalError(Exception): pass
            def underlying():
                Path(os.environ['CONNECT_MARKER']).write_text('fake connection attempted')
                raise AssertionError('FAKE underlying connector called; never delegates to a server')
            def connect(*args, **kwargs): return underlying()
            class Connection:
                @classmethod
                def connect(cls, *args, **kwargs): return underlying()
            class AsyncConnection:
                @classmethod
                async def connect(cls, *args, **kwargs): return underlying()
            if os.environ.get('BROKEN_DRIVER'):
                raise RuntimeError('Fake driver import failed')
        """)
        self.write("decklab/tests/db_support.py", r"""
            import os, types
            from pathlib import Path
            def fake_socket(*args, **kwargs):
                Path(os.environ['PROBE_MARKER']).write_text('fake probe attempted')
                raise AssertionError('FAKE socket probe; never delegates to a socket')
            socket = types.SimpleNamespace(create_connection=fake_socket)
            def unavailable():
                socket.create_connection(('fixture.invalid', 1))
        """)
        self.write("decklab/tests/__init__.py", r"""
            import os
            from pathlib import Path
            from decklab.lib import config, venv
            assert not config.CONFIG_FILE.exists(), 'private config was visible before test package import'
            assert 'DECKLAB_CONFIG_EXTRA' not in os.environ, 'extra overlay survived'
            assert 'DECKLAB_DECK_EXPORT' not in os.environ, 'export overlay survived'
            assert 'DECKLAB_FORGE_TESTS' not in os.environ, 'real Forge opt-in survived'
            assert all(name not in os.environ for name in ['PGPASSWORD', 'PGPASSFILE', 'PGSERVICE', 'PGSERVICEFILE'])
            venv.activate()
            import psycopg
            try:
                psycopg.connect()
            except psycopg.OperationalError:
                pass
            else:
                raise AssertionError('driver was not guarded before test package import')
            from . import db_support
            assert db_support.unavailable().startswith('Database integration disabled by fixture runner')
            Path(os.environ['IMPORT_MARKER']).write_text('protected package imported')
        """)
        self.write("decklab/tests/test_probe.py", r"""
            import asyncio, builtins, io, os, sys, unittest
            from pathlib import Path
            import psycopg
            from scripts import fixture_runtime as guard
            from decklab.lib import config
            from decklab.tests import db_support
            assert db_support.unavailable().startswith(guard.DATABASE_DISABLED)
            @unittest.skipIf(db_support.unavailable(), db_support.unavailable())
            class IntegrationTests(unittest.TestCase):
                def test_never_runs(self): raise AssertionError('integration was not skipped')
            class UnitTests(unittest.TestCase):
                def test_ordering_and_fakes(self):
                    for connect in [psycopg.connect, psycopg.Connection.connect]:
                        with self.assertRaisesRegex(psycopg.OperationalError, guard.CONNECT_DISABLED): connect()
                    with self.assertRaisesRegex(psycopg.OperationalError, guard.CONNECT_DISABLED):
                        asyncio.run(psycopg.AsyncConnection.connect())
                    before = (builtins.open, io.open, os.open, Path.open, Path.exists, psycopg.connect)
                    guard.install()
                    self.assertEqual(before, (builtins.open, io.open, os.open, Path.open, Path.exists, psycopg.connect))
                    original = psycopg.connect
                    try:
                        psycopg.connect = lambda: 'explicit unit fake'
                        guard.install()
                        self.assertEqual(psycopg.connect(), 'explicit unit fake')
                    finally:
                        psycopg.connect = original
                def test_paths_and_ordinary_temp_config(self):
                    private = config.CONFIG_FILE
                    variants = [private, str(private), os.fsencode(private), private.parent / 'unused' / '..' / private.name,
                                Path('decklab') / 'config.json']
                    if os.name == 'nt':
                        variants.extend([str(private).upper(), '\\\\?\\' + str(private)])
                        self.assertEqual(guard._lexical('\\\\?\\UNC\\fixture.invalid\\share\\config.json'),
                                         guard._lexical('\\\\fixture.invalid\\share\\config.json'))
                    for variant in variants:
                        for opener in [lambda p: builtins.open(file=p), io.open, Path.open,
                                       io.FileIO, lambda p: io.FileIO(p, 'w'),
                                       lambda p: os.open(p, os.O_RDONLY), lambda p: Path(os.fsdecode(p)).read_text(),
                                       lambda p: Path(os.fsdecode(p)).write_text('DO NOT WRITE')]:
                            with self.assertRaises(FileNotFoundError): opener(variant)
                    for operation in [lambda: private.unlink(), lambda: os.replace(private, private.with_name('moved')),
                                      lambda: os.rename(private.with_name('other'), private),
                                      lambda: os.rename('config.json', 'other', src_dir_fd=0),
                                      lambda: os.replace('other', 'config.json', dst_dir_fd=0),
                                      lambda: os.link('other', 'config.json', dst_dir_fd=0)]:
                        with self.assertRaises(FileNotFoundError): operation()
                    self.assertFalse(private.exists()); self.assertFalse(private.is_file())
                    self.assertFalse(os.path.exists(private)); self.assertFalse(os.path.isfile(private))
                    for credential in [Path(os.environ['FAKE_HOME']) / '.pgpass',
                                       Path(os.environ['FAKE_ROAMING']) / 'postgresql' / 'pgpass.conf',
                                       Path(os.environ['FAKE_PASSFILE']), Path(os.environ['FAKE_SERVICEFILE'])]:
                        with self.assertRaises(FileNotFoundError): credential.read_text()
                    fixture = private.parent / 'fixture' / 'config.json'
                    fixture.parent.mkdir()
                    fixture.write_text('temporary configuration')
                    self.assertEqual(fixture.read_text(), 'temporary configuration')
                    with builtins.open(file=fixture, mode='r') as stream: self.assertEqual(stream.read(), 'temporary configuration')
                def test_saved_script_spawn(self):
                    import multiprocessing
                    from fake_worker import worker
                    output = Path(os.environ['WORKER_RESULT'])
                    child = multiprocessing.get_context('spawn').Process(target=worker, args=(str(output),))
                    child.start(); child.join(20)
                    if child.is_alive():
                        child.terminate(); child.join(5)
                        self.fail('disposable fake worker did not finish')
                    self.assertFalse(child.is_alive(), 'fake worker did not finish')
                    self.assertEqual(child.exitcode, 0)
                    self.assertEqual(output.read_text(), '__mp_main__:guarded')
        """)
        self.write("fake_worker.py", r"""
            import sys
            from pathlib import Path
            from scripts import fixture_runtime as guard
            from decklab.lib import config
            from decklab.tests import db_support
            assert guard._installed and not config.CONFIG_FILE.exists()
            assert db_support.unavailable() == guard.DATABASE_DISABLED
            def worker(output):
                main = sys.modules['__main__']
                assert Path(main.__file__).name in {'test_fixtures.py', 'test_shard.py'}
                Path(output).write_text(main.__name__ + ':guarded')
        """)
        for module, cls, method in [
            ("test_homenet_gather", "RealFactsTests", "test_native"),
            ("test_overnight", "CleanupTests", "test_native"),
            ("test_overnight_report_full", "ControllerEndTests", "test_native"),
            ("test_inv_decks", "FreshInterpreterTests", "test_the_write_commands_register_their_operations"),
            ("test_server_lifecycle", "BackgroundServerTests", "test_taskkill_without_f_stops_it_like_the_stop_option")]:
            self.write(f"decklab/tests/{module}.py", f"import unittest\nclass {cls}(unittest.TestCase):\n"
                       "    def setUp(self): raise AssertionError('native setup must not run')\n"
                       f"    def {method}(self): raise AssertionError('native body must not run')\n")
        lifecycle = self.root / "decklab/tests/test_server_lifecycle.py"
        lifecycle.write_text(lifecycle.read_text() +
                             "    def test_native_child(self): raise AssertionError('native child must not start')\n")
        overnight = self.root / "decklab/tests/test_overnight.py"
        overnight.write_text(overnight.read_text() + "class FakeRunTests(unittest.TestCase):\n"
                             "    def setUp(self): raise AssertionError('native monitor must not start')\n"
                             "    def test_fake_child(self): raise AssertionError('native inventory must not run')\n")
        self.write("bootstrap.py", r"""
            import builtins, io, json, os, runpy, socket, sys
            from pathlib import Path
            root = Path(__file__).parent
            sys.path.insert(0, str(root))
            # Sentinels point ONLY at fake TEMP files. Even broken production guard order
            # cannot open a real credential/config or delegate to a real server here.
            private = {os.path.normcase(os.path.abspath(root / 'decklab/config.json')),
                       os.path.normcase(os.path.abspath(root / 'home/.pgpass')),
                       os.path.normcase(os.path.abspath(root / 'roaming/postgresql/pgpass.conf')),
                       os.path.normcase(os.path.abspath(root / 'secrets/pgpass-extra.conf')),
                       os.path.normcase(os.path.abspath(root / 'secrets/pg-service.conf'))}
            def sentry(original):
                def open_file(path=None, *args, **kwargs):
                    if path is None and 'file' in kwargs: path = kwargs.pop('file')
                    if not isinstance(path, int) and os.path.normcase(os.path.abspath(os.fsdecode(path))) in private:
                        (root / 'underlying-open').write_text('FAKE private file open attempted')
                        raise AssertionError('FAKE private open sentry; never delegates')
                    return original(path, *args, **kwargs)
                return open_file
            builtins.open, io.open, os.open = sentry(builtins.open), sentry(io.open), sentry(os.open)
            def no_socket(*args, **kwargs): raise AssertionError('No genuine socket can be attempted by regression')
            socket.create_connection = no_socket
            mode, *args = sys.argv[1:]
            if mode == 'broken_order':
                from scripts import fixture_runtime
                fixture_runtime.install = lambda *args: None
                mode = 'fixtures'
            elif mode == 'blocked_audit':
                def refuse_hook(event, args):
                    if event == 'sys.addaudithook': raise RuntimeError('fake refusal')
                sys.addaudithook(refuse_hook)
                mode = 'fixtures'
            if mode in {'fixtures', 'shard'}:
                entry = root / 'scripts' / ('test_fixtures.py' if mode == 'fixtures' else 'test_shard.py')
                sys.argv = [str(entry), *args]
                runpy.run_path(str(entry), run_name='__main__')
            elif mode == 'mp_metadata':
                for name in ['test_fixtures.py', 'test_shard.py']:
                    metadata = runpy.run_path(str(root / 'scripts' / name), run_name='__mp_main__')
                    assert metadata['__name__'] == '__mp_main__' and metadata['fixture_runtime']._installed
                print('mp metadata guarded')
            elif mode == 'partition':
                from scripts import test_fixtures, test_shard
                full = {case.id() for case in test_shard.tests_of(test_fixtures.load())}
                portions = [[case.id() for case in test_shard.tests_of(test_shard.shard(i, 4)[1])] for i in range(4)]
                joined = [case for part in portions for case in part]
                assert len(joined) == len(set(joined)) and set(joined) == full
                print(json.dumps({'cases': len(full), 'parts': list(map(len, portions))}))
        """)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")

    def run_fake(self, mode, *args, broken_driver=False):
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env.update({"HOME": str(self.root / "home"), "USERPROFILE": str(self.root / "home"),
                    "APPDATA": str(self.root / "roaming"), "FAKE_HOME": str(self.root / "home"),
                    "FAKE_ROAMING": str(self.root / "roaming"), "FAKE_PACKAGES": str(self.root / "packages"),
                    "FAKE_PASSFILE": str(self.root / "secrets/pgpass-extra.conf"),
                    "FAKE_SERVICEFILE": str(self.root / "secrets/pg-service.conf"),
                    "DECKLAB_CONFIG_EXTRA": str(self.root / "extra.json"), "DECKLAB_DECK_EXPORT": str(self.root / "export"),
                    "DECKLAB_FORGE_TESTS": "1",
                    "PGPASSWORD": "fake-disposable-password", "PGPASSFILE": str(self.root / "secrets/pgpass-extra.conf"),
                    "PGSERVICE": "fake-service", "PGSERVICEFILE": str(self.root / "secrets/pg-service.conf"),
                    "PTH_MARKER": str(self.root / "pth-executed"),
                    "CONNECT_MARKER": str(self.root / "underlying-connect"), "PROBE_MARKER": str(self.root / "underlying-probe"),
                    "IMPORT_MARKER": str(self.root / "package-imported"), "WORKER_RESULT": str(self.root / "worker-result")})
        if broken_driver:
            env["BROKEN_DRIVER"] = "1"
        return subprocess.run([sys.executable, str(self.root / "bootstrap.py"), mode, *args], cwd=self.root,
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=40)

    def assert_safe_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for marker in ("underlying-connect", "underlying-probe", "underlying-open", "pth-executed"):
            self.assertFalse((self.root / marker).exists(), marker)
        self.assertEqual((self.root / "decklab/config.json").read_text(), "FAKE PRIVATE CANARY")
        self.assertEqual((self.root / "home/.pgpass").read_text(), "FAKE CREDENTIAL CANARY")
        self.assertEqual((self.root / "roaming/postgresql/pgpass.conf").read_text(), "FAKE WINDOWS CANARY")
        self.assertEqual((self.root / "secrets/pgpass-extra.conf").read_text(), "FAKE OVERRIDE CANARY")
        self.assertEqual((self.root / "secrets/pg-service.conf").read_text(), "FAKE SERVICE CANARY")

    def test_targeted_names_install_before_package_decorators_and_connector_calls(self):
        result = self.run_fake("fixtures", "decklab.tests.test_probe.UnitTests.test_ordering_and_fakes")
        self.assert_safe_success(result)
        self.assertIn("Ran 1 test", result.stderr)

    def test_default_discovery_preserves_fixture_io_and_skips_only_explicit_runtime_and_database_cases(self):
        result = self.run_fake("fixtures")
        self.assert_safe_success(result)
        self.assertIn("skipped=8", result.stderr)

    def test_shard_cli_has_the_same_preimport_guards(self):
        result = self.run_fake("shard", "0", "1")
        self.assert_safe_success(result)
        self.assertIn("Shard 1 of 1", result.stdout)
        self.assertIn("skipped=8", result.stderr)

    def test_programmatic_shards_preserve_exact_discovery_without_duplicates(self):
        result = self.run_fake("partition")
        self.assert_safe_success(result)
        counts = json.loads(result.stdout)
        self.assertEqual(sum(counts["parts"]), counts["cases"])
        self.assertEqual(counts["cases"], 11)

    def test_saved_script_mp_metadata_installs_without_running_main(self):
        result = self.run_fake("mp_metadata")
        self.assert_safe_success(result)
        self.assertIn("mp metadata guarded", result.stdout)

    def test_bad_driver_bootstrap_fails_closed_before_test_package_import(self):
        result = self.run_fake("fixtures", broken_driver=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fake driver import failed", result.stderr)
        self.assertFalse((self.root / "package-imported").exists())
        self.assertFalse((self.root / "underlying-connect").exists())

    def test_rejected_raw_io_guard_fails_closed_before_test_package_import(self):
        result = self.run_fake("blocked_audit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Fixture raw-file guard could not be installed", result.stderr)
        self.assertFalse((self.root / "package-imported").exists())
        self.assertFalse((self.root / "underlying-open").exists())

    def test_guard_order_regression_fails_using_only_fake_resources(self):
        result = self.run_fake("broken_order", "decklab.tests.test_probe.UnitTests.test_ordering_and_fakes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("private config was visible", result.stderr)
        self.assertFalse((self.root / "underlying-connect").exists())
        self.assertFalse((self.root / "underlying-probe").exists())
