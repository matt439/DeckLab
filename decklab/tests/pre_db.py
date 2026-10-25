"""The real inventory files as they were before the phase 3 cutover, for tests about real data
(the product lists, products/status.csv, the Beginner Box pairings, ...). The cutover deleted
the inventory files from the working tree (the database holds them now); tag pre-db-inventory
marks the last commit that had them. tree() writes that commit's magic/ folder from git's
blobs (golden_dump.materialize) into a temporary folder once per process and returns it, so
FileInventory(tree()) reads them as the files backend did. A clone without the tag skips.

decks_tree() / decks_inventory() add the deck files and accessories as the pre-db-decks tag
(phase 4's cutover: the last commit with them) holds them, for tests about the real decks (the
playing guide, ...). A clone without either tag skips.

PRODUCT_NAMES are the display names and formats the pre-database product files went by (the
product CSVs never held them): decklab/tests/__init__.py puts them in files.PRODUCT_NAMES, so a
snapshot the tests build from files names its products as the files backend did before the
database. Deck Lab itself takes them from the database.

discover doesn't collect this module: its name doesn't start with test_.
"""
import atexit
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from decklab.lib import config

REV = "pre-db-inventory"
DECKS_REV = "pre-db-decks"

PRODUCT_NAMES = {
    "fdn-beginner-box": ("Foundations Beginner Box", "Beginner Box half (20 cards)"),
    "blb-starter-kit": ("Bloomburrow Starter Kit", "Starter Kit deck (60 cards)"),
    "challenger-2019-lightning-aggro": ("Lightning Aggro (Challenger Deck 2019)",
                                        "Challenger deck (60 cards + 15 sideboard)"),
    "fdc-calling-all-angels": ("Calling All Angels (Foundations Commander)",
                               "Commander precon (100 cards)"),
    "fdc-wretched-ranks": ("Wretched Ranks (Foundations Commander)",
                           "Commander precon (100 cards)"),
    "sld-welcome-to-stardew-valley": ("Welcome to Stardew Valley (Secret Lair)",
                                      "Secret Lair drop (7 cards)"),
    "sld-life-in-pelican-town": ("Life in Pelican Town (Secret Lair)",
                                 "Secret Lair drop (5 cards)"),
    "sld-a-flicker-in-the-deep": ("A Flicker in the Deep (Secret Lair)",
                                  "Secret Lair drop (5 cards)"),
}

_lock = threading.Lock()
_root = None
_decks_root = None


def _has_rev(rev=REV):
    done = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{rev}^{{commit}}"], cwd=config.REPO,
                          capture_output=True)
    return done.returncode == 0


def tree():
    """A temporary folder holding magic/ at REV (removed when the process exits). Raises
    unittest.SkipTest when the repo has no such tag."""
    global _root
    with _lock:
        if _root is None:
            if not _has_rev():
                raise unittest.SkipTest(f"the repo has no {REV} tag (the last commit with the inventory files)")
            from decklab.tests import golden_dump as gate
            root = Path(tempfile.mkdtemp(prefix="decklab-pre-db-"))
            atexit.register(shutil.rmtree, root, True)
            gate.materialize(REV, root)
            _root = root
        return _root


def inventory():
    """A FileInventory over tree()."""
    from decklab.lib.inventory.files import FileInventory
    return FileInventory(tree())


def following(root=None, accessories=False):
    """A FileInventory over root (tree() by default) whose deck files are wherever decks.DECKS_DIR
    points at each load (and the people's beside it, as spaces.people_dir() says): for the tests
    that patch DECKS_DIR to a folder of their own (phase 4 reads the decks from the inventory's
    snapshot). accessories: accessories.csv and its pictures likewise follow accessories.PATH and
    accessories.IMAGES (for the tests that patch those)."""
    from decklab.lib import decks
    from decklab.lib import accessories as kit
    from decklab.lib.inventory.files import FileInventory
    extra = {"accessories": lambda: kit.PATH, "images": lambda: kit.IMAGES} if accessories else {}
    return FileInventory(tree() if root is None else root, decks_dir=lambda: decks.DECKS_DIR, **extra)


def decks_tree():
    """A temporary folder holding magic/ at REV with the deck files, accessories.csv and its
    pictures at DECKS_REV, removed when the process exits. Raises unittest.SkipTest when the repo
    has no REV or DECKS_REV tag (HEAD has no deck files since phase 4's cutover)."""
    global _decks_root
    with _lock:
        if _decks_root is None:
            if not _has_rev():
                raise unittest.SkipTest(f"the repo has no {REV} tag (the last commit with the inventory files)")
            if not _has_rev(DECKS_REV):
                raise unittest.SkipTest(f"the repo has no {DECKS_REV} tag (the last commit with the deck files)")
            from decklab.tests import golden_dump as gate
            root = Path(tempfile.mkdtemp(prefix="decklab-pre-db-decks-"))
            atexit.register(shutil.rmtree, root, True)
            gate.materialize(REV, root, decks_rev=DECKS_REV)
            _decks_root = root
        return _decks_root


def decks_inventory():
    """A FileInventory over decks_tree()."""
    from decklab.lib.inventory.files import FileInventory
    return FileInventory(decks_tree())
