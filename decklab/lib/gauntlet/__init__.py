"""The gauntlet: public sparring decks from outside Deck Lab (design in decklab/design/gauntlet.md).

Its files are gitignored, under decklab/data/gauntlet/: the catalogue of each format, the
raw cached sources and the saved samples. Nothing here is ever a deck or inventory row.
"""
from decklab.lib import config

FORMATS = ("commander", "constructed")
DATA = config.DATA / "gauntlet"


def catalogue_path(fmt):
    """The catalogue file of one format ("commander" or "constructed")."""
    return DATA / f"catalogue-{fmt}.json"
