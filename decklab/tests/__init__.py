"""Deck Lab's tests. Forge's slots (decklab/lib/forge/slots.py), the budget of Forge
processes every Deck Lab checkout on the PC shares, go in a folder of this test run's
own (DECKLAB_FORGE_SLOTS, which the processes the tests start get too): so no test
touches the PC's real slots or waits for a real Forge run, and test runs going at once
in other checkouts don't wait for each other.

The database:
- DECKLAB_DB_LOG sends db.log (decklab.db.conn.log) to a temporary file of the run's own, so no
  test writes the real decklab/data/logs/db.log;
- lib/venv.py puts the repo's .venv packages (psycopg) on sys.path, so the database tests run
  under the system python whenever PostgreSQL is up (they skip, saying why, when it isn't);
- DECKLAB_DB_NAME names a database that doesn't exist, so a test that forgets to use its own
  throwaway database (db_support.DbTestCase) fails rather than reach the real decklab one;
- DECKLAB_STATE_EXPLICIT makes decklab.lib.state.store() refuse (RuntimeError) unless a test
  installed a store with state.use(): test_api's Sandbox installs an in-memory one, and the
  database tests a PgStore. A test that starts a real server process takes it out of that
  process's environment (keeping DECKLAB_DB_NAME), so the server makes its own PgStore and a
  database route answers 503.

The products' display names: files.PRODUCT_NAMES gets pre_db.PRODUCT_NAMES, the names the
pre-database product files went by, so a snapshot built from files names its products as before
(Deck Lab takes them from the database).

The Sandbox's store starts with the simulations setting (lib/api/simulations.py) at
"everyone", so the run routes' tests start runs as any profile whatever the default is."""
import atexit
import os
import shutil
import tempfile

from pathlib import Path

from decklab.lib import venv

venv.activate()

# db.log goes to a file of this run's own, set before decklab.db.conn is imported (it reads
# DECKLAB_DB_LOG then) and passed on to the processes the tests start: no test writes the real
# decklab/data/logs/db.log, which the nightly task and its checks are read from.
_LOGS = tempfile.mkdtemp(prefix="decklab-test-dblog-")
atexit.register(shutil.rmtree, _LOGS, ignore_errors=True)
os.environ["DECKLAB_DB_LOG"] = str(Path(_LOGS) / "db.log")

from decklab.db import conn as _conn  # noqa: E402 (after the venv, though it imports psycopg lazily)

_conn.LOG_FILE = Path(os.environ[_conn.LOG_ENV])    # in case conn was imported before this package
os.environ[_conn.NAME_ENV] = "decklab_tests_must_not_reach_this"
os.environ["DECKLAB_STATE_EXPLICIT"] = "1"

os.environ["DECKLAB_FORGE_SLOTS"] = _SLOTS = tempfile.mkdtemp(prefix="decklab-test-slots-")
atexit.register(shutil.rmtree, _SLOTS, ignore_errors=True)

from decklab.lib.inventory import files as _files  # noqa: E402
from decklab.tests import pre_db as _pre_db  # noqa: E402

_files.PRODUCT_NAMES.update(_pre_db.PRODUCT_NAMES)
