"""Source-only feature detection follows the split Forge CLI and still rejects stubs."""
import tempfile
import unittest

from decklab.tests.test_overnight import STUBS, fake_tree, overnight


FACADE = """from . import cli_results as results
from . import cli_soak as soak
_OWNERS = {name: part for part, names in (
    (results, ('_cmd_staged_move',)),
    (soak, ('_cmd_soak_probe',)),
) for name in names}
"""


class SplitFeatureTests(unittest.TestCase):
    def features(self, **changes):
        modules = dict(STUBS, cli=FACADE, cli_results="def _cmd_staged_move(args):\n    return 0\n",
                       cli_soak="def _cmd_soak_probe(args):\n    return 0\n")
        modules.update(changes)
        with tempfile.TemporaryDirectory() as tmp:
            return overnight.features(fake_tree(tmp, modules))["H"]

    def test_registered_commands_follow_their_actual_source(self):
        self.assertTrue(self.features()["built"])

    def test_qualified_stub_in_owner_is_still_a_stub(self):
        found = self.features(cli_soak="def _cmd_soak_probe(args):\n    return shared._not_built('soak', 'H')\n")
        self.assertFalse(found["built"])
        self.assertIn("cli._cmd_soak_probe is a stub", found["why"])

    def test_unregistered_command_cannot_be_supplied_by_an_unrelated_file(self):
        found = self.features(cli=FACADE.replace("'_cmd_soak_probe'", "'_other_command'"))
        self.assertFalse(found["built"])
        self.assertIn("cli._cmd_soak_probe is missing", found["why"])

    def test_missing_or_unreadable_owner_is_not_built(self):
        for source in ("", "syntax error"):
            with self.subTest(source=source):
                found = self.features(cli_soak=source)
                self.assertFalse(found["built"])
                self.assertIn("cli._cmd_soak_probe is missing", found["why"])

    def test_direct_stub_takes_precedence_over_a_registered_implementation(self):
        found = self.features(cli=FACADE + "def _cmd_soak_probe(args):\n    raise NotImplementedError('soak')\n")
        self.assertFalse(found["built"])
        self.assertIn("cli._cmd_soak_probe is a stub", found["why"])


if __name__ == "__main__":
    unittest.main()
