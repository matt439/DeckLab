"""What every command line that reads the inventory does first (the phase 3 design, Q4):

    from decklab.lib.inventory import entry
    with entry.command():
        ...                 # one pinned snapshot for the whole command

command() activates the repo's .venv (lib/venv.py: the database backend needs psycopg, which
the system python only finds that way), pins one inventory snapshot for the block (loaded on
first use, so a command that never reads the inventory loads nothing), and on the way out prints
the database backend's stale-snapshot note to stderr ("Note: inventory as of ...: the database
isn't reachable."), as python -m decklab.db does. A command catches inventory.Unavailable itself
(the database can't be used, or the inventory hasn't been imported yet) and exits 2.
"""
import contextlib
import sys


@contextlib.contextmanager
def command():
    from decklab.lib import inventory, venv
    venv.activate()
    with inventory.pinned():
        try:
            yield
        finally:
            stale = inventory.pinned_stale()
            if stale:
                print(f"Note: {stale}.", file=sys.stderr)
