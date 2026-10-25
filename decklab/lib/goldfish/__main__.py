"""python -m decklab.lib.goldfish: the command line (cli.py)."""
import sys

from .cli import main

if __name__ == "__main__":
    from decklab.lib.inventory import entry
    with entry.command():           # the venv, and one inventory snapshot (products' decks) for the command
        sys.exit(main())
