"""Overnight's script import path remains usable after its controller split."""
import unittest
import subprocess
import sys
from unittest import mock

from decklab.tests.test_overnight import overnight

import overnight_plan


class OvernightModuleTests(unittest.TestCase):
    def test_old_names_have_one_binding(self):
        for name, owner in overnight._OWNERS.items():
            with self.subTest(name=name):
                self.assertNotIn(name, vars(overnight))
                self.assertIs(getattr(overnight, name), getattr(owner, name))
                self.assertIn(name, dir(overnight))

    def test_existing_patch_reaches_controller_and_restores_owner(self):
        controller = overnight.Controller.__new__(overnight.Controller)
        controller.plan = {"soak_min_s": 100}
        controller.session = {"soak_s": 25, "soak_server_s": 10}
        original = overnight.soak_owed
        with mock.patch.object(overnight, "soak_owed", return_value=9) as owed:
            self.assertEqual(controller.filler_owed(), 9)
            owed.assert_called_once_with(100, 25, 10)
            self.assertIs(overnight_plan.soak_owed, owed)
        self.assertIs(overnight.soak_owed, original)
        self.assertIs(overnight_plan.soak_owed, original)

    def test_load_by_path_without_a_prepared_search_path(self):
        code = """import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1]).resolve()
assert str(path.parent) not in sys.path
spec = importlib.util.spec_from_file_location('isolated_overnight', path)
module = importlib.util.module_from_spec(spec)
if sys.argv[2] == 'registered':
    sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert module.TREE == path.parents[2]
assert module.features()['H']['built']
assert module.Controller.__name__ == 'Controller'
assert callable(module.main)
"""
        for registration in ("registered", "unregistered"):
            with self.subTest(registration=registration):
                result = subprocess.run([sys.executable, "-I", "-c", code, overnight.__file__, registration],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
