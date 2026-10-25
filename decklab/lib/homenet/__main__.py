"""python -m decklab.lib.homenet: the command line (the package's
docstring says what each command does)."""
import sys

from decklab.lib.homenet.commands import main


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
