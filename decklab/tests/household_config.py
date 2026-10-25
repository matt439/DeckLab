"""A made-up household's config.json for tests that need profiles and spaces but no real
settings: decklab/config.json is gitignored, so a test must never depend on it.

    from decklab.tests import household_config
    household_config.use(self)      # in setUp: config.CONFIG_FILE is a temp copy until cleanup
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from decklab.lib import config

PROFILES = [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home",
     "emails": ["matt@example.com"]},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home",
     "emails": ["user1@example.com"]},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2", "emails": ["user2@example.com"]},
    {"id": "user3", "name": "User3", "role": "member", "space": "user3", "emails": ["user3@example.com"]},
    {"id": "user4", "name": "User4", "role": "member", "space": "user4", "emails": ["user4@example.com"]},
    {"id": "user5", "name": "User5", "role": "member", "space": "user5", "emails": ["user5@example.com"]},
]


def use(case, profiles=PROFILES):
    """Point config.CONFIG_FILE at a temp config.json holding profiles, for this test only."""
    folder = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, folder, True)
    path = folder / "config.json"
    path.write_text(json.dumps({"profiles": profiles}), encoding="utf-8")
    patcher = mock.patch.object(config, "CONFIG_FILE", path)
    patcher.start()
    case.addCleanup(patcher.stop)
    return path
