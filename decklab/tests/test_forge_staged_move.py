"""Tests for staged-move (python -m decklab.lib.forge staged-move; wave 3's package H,
forge-trial/sim-wave3-contract.md section 16 and sim-combined-run.md section 9.2): the combined
run's staged v2 matchup results and field notes move into the real results folder; stale files,
conflicts, held keys, v1 copies, paired/ and experiment results stay.

Results are made by hand as test_forge_replay's are (its save helper, real card_shas), in
test_forge.py's made-up Forge folder.

Run from the repo root: python scripts/test_fixtures.py
"""
import json
from pathlib import Path
from unittest import mock

from decklab.lib import config, decks, forge
from decklab.tests import test_forge, test_forge_replay
from decklab.tests.test_forge import CARD_LOG, GISA, GREEN, RED, sections

BLUE = test_forge_replay.BLUE


def setUpModule():
    test_forge.setUpModule()


def tearDownModule():
    test_forge.tearDownModule()


class StagedMoveTests(test_forge.ForgeCase):

    def setUp(self):
        super().setUp()
        self.lists = {"casual/green": GREEN, "casual/red": RED, "casual/blue": BLUE, "commander/gisa": GISA}
        summaries = {deck_id: {"id": deck_id, "title": deck_id.split("/")[1].title(), "kind": deck_id.split("/")[0],
                               "versions": ["target"]} for deck_id in self.lists}
        for p in (mock.patch.object(decks, "find_summary", side_effect=summaries.get),
                  mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: sections(self.lists[deck_id])),
                  mock.patch.object(forge.simjar, "card_log", return_value=dict(CARD_LOG))):
            p.start()
            self.addCleanup(p.stop)
        self.staged = self.tmp / "staged"
        self.staged.mkdir()
        self.results = self.staged          # the replay helper's save() writes into self.results
        self.real = self.tmp / "real"
        self.real.mkdir()
        self.eng = forge.engine.current(forge.install._setup(), dict(CARD_LOG))

    run_main = test_forge.CommandLineTests.run_main
    entry = test_forge_replay.ReplayTests.entry
    today = test_forge_replay.ReplayTests.today
    save = test_forge_replay.ReplayTests.save

    def v2(self, a, b, games=50, engine=None):
        eng = engine or forge.engine.result_fields(self.eng)["engine"]
        whole = dict(self.eng, **{k: eng[k] for k in eng})
        if engine is not None:
            whole.pop("deployed", None)     # the given "overrides" makes the key, as another deployed set's run did
        key = forge.engine.key(self.entry(a), self.entry(b), whole)
        return self.save(key, a, b, games, engine=eng)

    def move(self, *argv):
        code, out, err = self.run_main("staged-move", "--from", str(self.staged), "--to", str(self.real), "--json",
                                       *argv)
        return code, (json.loads(out) if out.strip() else None), err

    def test_moves_current_results_and_field_notes(self):
        result = self.v2("casual/green", "casual/red")
        (self.staged / "field").mkdir()
        (self.staged / "field" / "abc-Constructed.json").write_text("{}", encoding="utf-8")
        code, found, _ = self.move()
        self.assertEqual(code, 0)
        self.assertEqual([m["key"] for m in found["move"]], [result["key"]])
        self.assertTrue((self.real / f"{result['key']}.json").is_file())
        self.assertFalse((self.staged / f"{result['key']}.json").exists())
        self.assertTrue((self.real / "field" / "abc-Constructed.json").is_file())
        self.assertEqual(json.loads((self.real / f"{result['key']}.json").read_text(encoding="utf-8"))["key"],
                         result["key"])

    def test_stale_key_names_the_field_that_differs(self):
        engine = dict(forge.engine.result_fields(self.eng)["engine"], overrides="0" * 64)
        result = self.v2("casual/green", "casual/red", engine=engine)
        code, found, _ = self.move()
        self.assertEqual(code, 1)
        self.assertEqual([s["key"] for s in found["stale"]], [result["key"]])
        self.assertIn("overrides", found["stale"][0]["differs"])
        self.assertTrue((self.staged / f"{result['key']}.json").exists())
        self.assertFalse((self.real / f"{result['key']}.json").exists())

    def test_stale_names_only_the_fields_that_differ(self):
        # The stored "overrides" is the matchup's (none of these lists' cards has one), so a run with other
        # game patches names game_patches alone, not the whole deployed folder's hash.
        engine = forge.engine.result_fields(self.eng, [self.entry("casual/green"), self.entry("casual/red")])["engine"]
        engine = dict(engine, game_patches="0" * 64)
        result = self.v2("casual/green", "casual/red", engine=engine)
        code, found, _ = self.move("--dry-run")
        self.assertEqual(code, 1)
        self.assertEqual(found["stale"], [{"file": f"{result['key']}.json", "key": result["key"],
                                           "differs": ["game_patches"]}])

    def test_a_side_whose_deck_is_gone_is_stale(self):
        result = self.v2("casual/green", "casual/red")
        path = self.staged / f"{result['key']}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for side in data["sides"]:
            side["pilot"] = {"profile": "Default"}
            side["seen_as"] = side.get("seen_as") or [{"id": "casual/green", "version": "target"}]
        path.write_text(json.dumps(data), encoding="utf-8")
        for error in (KeyError("casual/green"), ValueError("no such version")):
            with mock.patch.object(forge.pilots, "pilot_for", side_effect=error):
                code, found, _ = self.move("--dry-run")
            self.assertEqual(code, 1)
            self.assertEqual(found["stale"], [{"file": path.name, "key": result["key"], "differs": ["sides[0].pilot"]}])
        self.assertTrue(path.exists())

    def test_conflict_is_skipped_and_listed(self):
        result = self.v2("casual/green", "casual/red")
        (self.real / f"{result['key']}.json").write_text('{"mine": true}', encoding="utf-8")
        code, found, _ = self.move()
        self.assertEqual(code, 1)
        self.assertEqual([c["key"] for c in found["conflict"]], [result["key"]])
        self.assertEqual(json.loads((self.real / f"{result['key']}.json").read_text(encoding="utf-8")), {"mine": True})

    def test_never_moves_v1_paired_or_experiment_files(self):
        v1 = self.save("1" * 64, "casual/blue", "casual/red", 30)
        exp = self.v2("casual/green", "casual/blue")
        data = json.loads((self.staged / f"{exp['key']}.json").read_text(encoding="utf-8"))
        data["kind"] = "experiment"
        (self.staged / f"{exp['key']}.json").write_text(json.dumps(data), encoding="utf-8")
        (self.staged / "paired").mkdir()
        (self.staged / "paired" / ("2" * 64 + ".json")).write_text("{}", encoding="utf-8")
        code, found, _ = self.move()
        self.assertEqual(code, 0)
        self.assertEqual(found["move"], [])
        why = {s["file"]: s["why"] for s in found["skipped"]}
        self.assertIn("v1", why[f"{v1['key']}.json"])
        self.assertIn("experiment", why[f"{exp['key']}.json"])
        self.assertTrue((self.staged / "paired" / ("2" * 64 + ".json")).exists())
        self.assertEqual(sorted(p.name for p in self.real.iterdir()), [])

    def test_hold_leaves_listed_keys(self):
        held = self.v2("casual/green", "casual/red")
        moved = self.v2("casual/blue", "casual/red")
        hold = self.tmp / "held.txt"
        hold.write_text(f"# look at this one\n{held['key']}\n", encoding="utf-8")
        code, found, _ = self.move("--hold", str(hold))
        self.assertEqual(code, 0)
        self.assertEqual([h["key"] for h in found["held"]], [held["key"]])
        self.assertEqual([m["key"] for m in found["move"]], [moved["key"]])
        code, found, _ = self.move("--hold", str(self.tmp / "missing.txt"))      # a missing file holds nothing
        self.assertEqual([m["key"] for m in found["move"]], [held["key"]])

    def test_dry_run_lists_exactly_what_the_move_does(self):
        self.v2("casual/green", "casual/red")
        self.v2("casual/blue", "casual/red")
        stale = self.v2("casual/green", "casual/blue",
                        engine=dict(forge.engine.result_fields(self.eng)["engine"], clock_s=1))
        code, dry, _ = self.move("--dry-run")
        self.assertEqual(sorted(p.name for p in self.real.iterdir()), [])
        code, real, _ = self.move()
        for part in ("move", "notes", "stale", "conflict", "held", "skipped"):
            self.assertEqual(dry[part], real[part], part)
        self.assertEqual(sorted(p.name for p in self.real.iterdir()), sorted(m["file"] for m in real["move"]))
        self.assertEqual([s["key"] for s in real["stale"]], [stale["key"]])

    def test_calls_ensure_deployed_first(self):
        order = []
        real_today = forge.engine.today
        with mock.patch.object(forge.overrides, "ensure_deployed", side_effect=lambda d: order.append("deploy")), \
                mock.patch.object(forge.engine, "today", side_effect=lambda *a: order.append("today") or real_today(*a)):
            self.move("--dry-run")
        self.assertEqual(order[:2], ["deploy", "today"])

    def test_refuses_while_a_server_pool_of_this_checkout_runs(self):
        self.v2("casual/green", "casual/red")
        service = {"pid": 1, "port": 1, "token": "t", "checkout": str(config.REPO)}
        with mock.patch.object(forge.pool, "services", return_value=[service]):
            code, found, err = self.move()
        self.assertEqual(code, 1)
        self.assertIn("Stop the server first", err)
        self.assertEqual(sorted(p.name for p in self.real.iterdir()), [])
