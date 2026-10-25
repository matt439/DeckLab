"""python -m decklab.lib.stats: see the package docstring (decklab/lib/stats/__init__.py)."""
import sys

from decklab.lib.stats import main

if __name__ == "__main__":
    from decklab.lib.inventory import entry
    with entry.command():           # the venv, and one inventory snapshot (products' decks) for the command
        sys.exit(main())
