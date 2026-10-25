"""Spaces: whose cards a collection, a token inventory and a deck belong to.

"home" is the shared pool of Matt and User1, today's files, unchanged:
magic/collection.csv, magic/tokens.csv and magic/decks/<kind>/, with the
products, orders, receipts, accessories and watchlist, which only home has.
Each profile whose config "space" is its own id (lib/profiles.py) has a
person space under magic/people/<id>/:

    collection.csv            their cards (collection.csv's columns)
    tokens.csv                their token cards (tokens.csv's columns)
    decks/casual/<slug>.md    their decks, in the deck file format
    decks/commander/<slug>.md
    imports/                  raw scanner/app exports, never hand-edited

None of these is made in advance: a missing collection or tokens file reads
as empty, and a writer makes the folders when it first writes there.

Deck ids: a home deck keeps "<kind>/<slug>" (and "product/...",
"pairing/..."), so saved results, play records and links keep working; a
person's deck is "<space>/<kind>/<slug>". Owned vs needed, cards in use in
other built decks and tokens are worked out within the deck's own space
(pool.py, tokens/).

    from decklab.lib import spaces

    spaces.space_ids()                       # ["home", "user2", ...]
    spaces.get("user2").decks              # Path of magic/people/user2/decks
    spaces.split_deck_id("user2/casual/elves")   # ("user2", "casual", "elves")
    spaces.split_deck_id("casual/elves")           # ("home", "casual", "elves")
    spaces.join_deck_id("home", "casual", "elves") # "casual/elves"

Home's decks folder is read from decks.DECKS_DIR each time, so tests that
patch it patch home here too. A Space names no inventory files: collections,
token cards and raw imports are the inventory's (decklab/lib/inventory, whose
paths.py says where the files backend keeps them). PEOPLE_DIR None means
magic/people beside decks.DECKS_DIR
(so a test's decks folder brings its own people folder); tests may patch it.
"""
from dataclasses import dataclass
from pathlib import Path

from decklab.lib import profiles

HOME = profiles.HOME
HOME_KINDS = ("casual", "commander", "product", "pairing")   # first parts of a home deck id
DECK_KINDS = ("casual", "commander")                         # decks.KINDS: the deck file folders
PEOPLE_DIR = None


class SpaceNotFound(LookupError):
    """No space with that id in config.json."""


@dataclass(frozen=True)
class Space:
    """Where one space's files are. owner is the person's profile id (None for home)."""
    id: str
    name: str
    owner: str | None
    root: Path
    decks: Path         # holds casual/ and commander/

    @property
    def is_home(self):
        return self.id == HOME

    def deck_dir(self, kind):
        if kind not in DECK_KINDS:
            raise ValueError(f"kind must be one of {DECK_KINDS}, not {kind!r}")
        return self.decks / kind


def people_dir():
    """The folder holding every person space (magic/people)."""
    if PEOPLE_DIR is not None:
        return Path(PEOPLE_DIR)
    from decklab.lib import decks
    return Path(decks.DECKS_DIR).parent / "people"


def _people(listed=None):
    """[(id, name)] of the person spaces in config.json; [] when it can't be read
    (the home files still work without it)."""
    try:
        listed = profiles.read() if listed is None else listed
    except (OSError, ValueError):
        return []
    return [(p["id"], p["name"]) for p in listed if p["space"] != HOME]


def space_ids(listed=None):
    """"home", then every person space in config.json's order. listed is
    profiles.read()'s list, when the caller has it."""
    return [HOME] + [space_id for space_id, _ in _people(listed)]


def _home():
    from decklab.lib import decks
    decks_dir = Path(decks.DECKS_DIR)
    return Space(HOME, "Home", None, decks_dir.parent, decks_dir)


def _person(space_id, name):
    root = people_dir() / space_id
    return Space(space_id, name, space_id, root, root / "decks")


def get(space_id, listed=None):
    """The Space with that id; SpaceNotFound for one config.json doesn't list."""
    if space_id == HOME:
        return _home()
    for person, name in _people(listed):
        if person == space_id:
            return _person(person, name)
    raise SpaceNotFound(f"no space {space_id!r}")


def list_spaces(listed=None):
    """Every Space: home first, then the person spaces in config.json's order."""
    return [_home()] + [_person(space_id, name) for space_id, name in _people(listed)]


def exists(space_id, listed=None):
    return space_id in space_ids(listed)


# ------------------------------------------------------------------ deck ids

def split_deck_id(deck_id):
    """(space, kind, rest) of a deck id. Home ids are "<kind>/<rest>" with kind
    casual, commander, product or pairing ("product/fdn-beginner-box/cats" is
    ("home", "product", "fdn-beginner-box/cats")); a person's are
    "<space>/<kind>/<slug>" with kind casual or commander. ValueError for
    anything else. Whether the space or deck exists isn't checked."""
    if not isinstance(deck_id, str):
        raise ValueError(f"bad deck id {deck_id!r}")
    first, _, rest = deck_id.partition("/")
    if first in HOME_KINDS:
        if not rest:
            raise ValueError(f"bad deck id {deck_id!r}")
        return HOME, first, rest
    kind, _, slug = rest.partition("/")
    if not profiles.valid_id(first) or first in profiles.RESERVED_SPACES or kind not in DECK_KINDS \
            or not slug or "/" in slug:
        raise ValueError(f"bad deck id {deck_id!r}")
    return first, kind, slug


def join_deck_id(space, kind, slug):
    """The deck id of a deck file: "<kind>/<slug>" at home, "<space>/<kind>/<slug>" in a person's space."""
    return f"{kind}/{slug}" if space == HOME else f"{space}/{kind}/{slug}"


def space_of(deck_id):
    """The space a deck id belongs to (home for an id that can't be split)."""
    try:
        return split_deck_id(deck_id)[0]
    except ValueError:
        return HOME


def space_of_path(path, listed=None):
    """The space whose deck folder holds a deck file at path, or None when
    it's in none of them."""
    path = Path(path)
    try:
        parent = path.resolve().parent.parent
    except OSError:
        return None
    for space in list_spaces(listed):
        try:
            if parent == space.decks.resolve():
                return space.id
        except OSError:
            continue
    return None
