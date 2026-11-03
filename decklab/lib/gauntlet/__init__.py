"""The gauntlet (E3-S28 to E3-S31; decklab/design/gauntlet.md): a fixed, public set of sparring
decks from outside Deck Lab, kept in gitignored files, never in the database.

    Commander     EDHREC's average decks for its top commanders (Bracket 2 "core" and Bracket 3
                  "upgraded"; edhrec_source.py) and Wizards' precons from MTGJSON (precon_source.py).
    60-card       Forge's bundled quest decks: its duels and its precons (forge_source.py).

catalogue.build() fetches them (politely, only from the command line), fixes an average deck to
exactly 100 singleton cards (fixing.py), measures its Commander Bracket, screens out decks Forge's
AI can't play, tags each deck's colours and style (tags.py) and saves the catalogue atomically in
catalogue_path(fmt). Gauntlet decks are never decks, inventory, Rankings or Bradley-Terry data.

Files (all under DATA, config.DATA / "gauntlet"):
    sources/edhrec/                     EDHREC's raw cached fetches (MTGJSON's: lib/precons.py's cache)
    catalogue-<commander|constructed>.json
    samples/<sample-id>.json            saved sweeps (sample.py)
"""
import re
import unicodedata

from decklab.lib import config

FORMATS = ("commander", "constructed")
DATA = config.DATA / "gauntlet"
CATALOGUE_FORMAT = 1                # the catalogue file's "format"
ID_PREFIX = "gauntlet:"


def catalogue_path(fmt):
    """The catalogue file of one format ("commander" or "constructed")."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, not {fmt!r}")
    return DATA / f"catalogue-{fmt}.json"


def sources_dir(kind):
    """The raw cache folder of one source: "edhrec", "mtgjson" or "forge"."""
    return DATA / "sources" / kind


def slug(text):
    """A plain lowercase slug of a title or file stem: "Agent K 1" -> "agent-k-1"."""
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    plain = re.sub(r"['’,.]", "", plain)
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-") or "deck"


def is_gauntlet_id(value):
    """True for a gauntlet deck's id ("gauntlet:edhrec/...", "gauntlet:precon/...", ...)."""
    return isinstance(value, str) and value.startswith(ID_PREFIX)


def precon_id(file):
    """The gauntlet id of an MTGJSON Commander precon: "gauntlet:precon/<file>" (precon_source.py)."""
    return f"{ID_PREFIX}precon/{file}"


def trial_excluded(summary):
    """The gauntlet ids a deck's gauntlet leaves out (E3-S39): a trial deck's own precon
    (decks/trial.py; its catalogue copy may be fixed to a list other than the trial's, so its
    card_sha alone wouldn't find it), as a tuple; () for any other deck or no summary."""
    file = (summary or {}).get("trial")
    return (precon_id(file),) if isinstance(file, str) and file else ()


def without(sample, exclude_ids):
    """A sample (sample.py's dict) without the decks exclude_ids names: the same dict when none of
    them is in it, else a copy with the rest of its "decks" in order (its id and filters kept, so
    its saved games and runs are still found by its id)."""
    exclude = set(exclude_ids or ())
    listed = (sample or {}).get("decks") or []
    if not exclude or not any(deck_id in exclude for deck_id in listed):
        return sample
    return dict(sample, decks=[deck_id for deck_id in listed if deck_id not in exclude])
