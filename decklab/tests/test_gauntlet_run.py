"""Tests for the gauntlet's runs and command line (decklab/design/gauntlet.md section 6):
decklab.lib.forge.gauntlet's entries, plan, run (its own results folder, Stop) and view (the
groups' equal-weight averages, the spread, "one opponent, not a group" and the caveat), and
python -m decklab.lib.forge gauntlet's commands.

They reuse test_forge_field's small magic/ tree and its FakeField (no Forge process starts), with
one FakeField for each results folder, so the gauntlet's games are seen to stay out of the
default folder that Rankings and the Bradley-Terry data read. The catalogue and the sample
choice (decklab/lib/gauntlet) are stand-ins: a hand-written catalogue and the first N decks. No
test makes a network call.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_run
"""
import io
import json
import threading
from pathlib import Path
from unittest import mock

from decklab.lib.forge import cli, common, engine, field, gauntlet, lists, runner, saved
from decklab.tests.test_forge_field import FakeField, FieldTestCase


def _deck(slug, title, identity, style, tier, cards, playable=True, kind="constructed"):
    return {"id": f"gauntlet:forge/duels/{slug}", "title": title, "kind": kind, "card_sha": "c" * 64,
            "source": {"kind": "forge", "file": f"res/quest/duels/{slug}.dck", "fetched": None, "rank": None,
                       "decks": None},
            "tier": tier, "bracket": None, "identity": identity, "colours": identity,
            "style": {"primary": style, "tags": [], "themes": []}, "metrics": {}, "fixes": [],
            "problems": [] if playable else ["Forge can't play its cards"], "playable": playable,
            "cards": {"Commander": [], "Main": cards}}


CATALOGUE = {"format": 1, "kind": "constructed", "built": "2026-11-01T00:00:00+00:00", "card_data": None,
             "sha": "a" * 64, "decks": [
                 _deck("red-burn", "Red Burn", "R", "aggro", "medium", [[4, "Lightning Bolt"], [20, "Mountain"]]),
                 _deck("blue-draw", "Blue Draw", "U", "control", "hard", [[4, "Opt"], [20, "Island"]]),
                 _deck("izzet-spells", "Izzet Spells", "UR", "control", "medium",
                       [[4, "Opt"], [4, "Shock"], [10, "Island"], [10, "Mountain"]]),
                 _deck("green-ramp", "Green Ramp", "G", "ramp", "hard", [[4, "Llanowar Elves"], [20, "Forest"]]),
                 _deck("broken", "Broken", "B", "midrange", "medium", [[4, "Duress"], [20, "Swamp"]],
                       playable=False)]}
IDS = [d["id"] for d in CATALOGUE["decks"][:4]]


class GauntletCase(FieldTestCase):

    def setUp(self):
        super().setUp()
        self.gauntlet_dir = self.root / "gauntlet-results"
        self.fakes = {}
        self.samples = {}

        def fake(results_dir):
            folder = str(Path(results_dir)) if results_dir is not None else "default"
            return self.fakes.setdefault(folder, FakeField() if folder != str(self.results) else self.fake)
        self.fake_for = fake
        self.fake_for(self.results)

        def run(a, b, games, *, results_dir=None, **kwargs):
            return fake(results_dir).run(a, b, games, results_dir=results_dir, **kwargs)
        patches = [(runner, "run", run), (saved, "load", lambda key, results_dir=None: fake(results_dir).load(key)),
                   (saved, "_stored", lambda results_dir=None: fake(results_dir).stored()),
                   (lists, "matchup_key", FakeField.key), (gauntlet, "RESULTS_DIR", self.gauntlet_dir),
                   (gauntlet, "_load_catalogue", lambda fmt: CATALOGUE if fmt == "constructed" else None),
                   (gauntlet, "_choose", lambda decks, size, **kw: [d for d in decks if d["playable"]][:size]),
                   (gauntlet, "_sample_id", lambda sha, filters, size, seed: f"sample:{size:012d}"),
                   (gauntlet, "_save_sample", lambda fmt, found: self.samples.__setitem__(found["id"], found)),
                   (gauntlet, "_load_sample", lambda sample_id: self.samples.get(sample_id))]
        for target, name, value in patches:
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.alpha = self.entry("casual/alpha")
        self.sample = {"id": "sample:000000000004", "format": "constructed", "catalogue_sha": "a" * 64,
                       "filters": {"colours": None, "styles": None, "tiers": ["medium", "hard"]}, "size": 4,
                       "seed": "", "decks": list(IDS)}

    @property
    def gfake(self):
        return self.fake_for(self.gauntlet_dir)

    def opponent(self, deck_id):
        return next(e for e in gauntlet.entries("constructed", IDS) if e["id"] == deck_id)


class EntryTests(GauntletCase):

    def test_entry_from_cards(self):
        found = lists.entry_from_cards("gauntlet:x/y", "Y", "commander",
                                       {"Commander": [[1, "Giada, Font of Hope"]], "Main": [[2, "Plains"]]},
                                       {"gauntlet": {"kind": "edhrec"}})
        text, sha, count = lists._list_text(found["cards"], "commander")
        self.assertEqual((found["id"], found["version"], found["kind"], found["card_sha"], found["card_count"]),
                         ("gauntlet:x/y", "target", "commander", sha, 3))
        self.assertEqual(found["dck"], lists._dck(text, sha))
        self.assertTrue(found["dck"].startswith("[metadata]\n"))
        self.assertIn("[Commander]\n1 Giada, Font of Hope\n[Main]\n2 Plains", found["dck"])
        self.assertEqual(found["source"], {"gauntlet": {"kind": "edhrec"}})
        self.assertEqual(set(found["pilot"]), {"profile", "switches"})
        # The same lines in another order are the same list.
        again = lists.entry_from_cards("gauntlet:x/z", "Z", "commander",
                                       {"Main": [[2, "Plains"]], "Commander": [[1, "Giada, Font of Hope"]]})
        self.assertEqual(again["card_sha"], sha)

    def test_entries_and_their_problems(self):
        found = gauntlet.entries("constructed", IDS)
        self.assertEqual([e["id"] for e in found], IDS)
        self.assertEqual(found[0]["source"]["gauntlet"]["kind"], "forge")
        with self.assertRaisesRegex(common.ForgeError, "1 of the sample's decks"):
            gauntlet.entries("constructed", IDS + ["gauntlet:forge/duels/broken"])
        with self.assertRaisesRegex(common.ForgeError, "no commander gauntlet"):
            gauntlet.entries("commander", IDS)
        with self.assertRaises(ValueError):
            gauntlet.catalogue("pauper")
        commander_sample = dict(self.sample, format="commander")
        with self.assertRaisesRegex(ValueError, "commander decks"):
            gauntlet.plan(self.alpha, commander_sample)

    def test_draw_uses_the_default_tiers_and_saves(self):
        found = gauntlet.draw("constructed", size=3, colours="rwu", styles=["control", "aggro"])
        self.assertEqual(found["filters"], {"colours": "WUR", "styles": ["aggro", "control"],
                                            "tiers": ["hard", "medium"]})
        self.assertEqual(found["decks"], IDS[:3])
        self.assertEqual(self.samples[found["id"]], found)
        self.assertEqual(gauntlet.draw("constructed")["size"], 24)


class RunTests(GauntletCase):

    def test_plan_and_run_use_the_gauntlet_folder_only(self):
        planned = gauntlet.plan(self.alpha, self.sample)
        self.assertEqual((planned["sample"], planned["new_games"]), (self.sample["id"], 400))
        self.assertEqual([p["games"] for p in planned["pairs"]], [100] * 4)
        with mock.patch.object(engine, "is_current", lambda result: True):
            before = field._bt_data("Constructed", None)
        note = gauntlet.run(self.alpha, self.sample, inflight=2, pool=object())
        self.assertEqual((note["played"], note["planned"], note["stopped"], note["budget"]),
                         (400, 400, False, "fixed:100"))
        self.assertEqual(sorted(c[0] for c in self.gfake.calls), sorted(IDS))
        # Nothing reached the house folder: no house game, no house result, no ratings data.
        self.assertEqual((self.fake.calls, self.fake.store), ([], {}))
        self.assertEqual(self.fake_for(None).store, {})
        with mock.patch.object(engine, "is_current", lambda result: True):
            self.assertEqual(field._bt_data("Constructed", None), before)
            self.assertEqual(field._bt_data("Constructed", self.results), {})
        # The note is under the gauntlet's folder; the house field's note is untouched.
        self.assertTrue((self.gauntlet_dir / "field" / f"{self.alpha['card_sha']}-Constructed-home.json").exists())
        self.assertFalse((self.results / "field").exists())
        self.assertEqual(sum(o["games"] for o in field.view(self.alpha, self.results)["opponents"]), 0)
        # Planned again, there's nothing left to play.
        self.assertEqual(gauntlet.plan(self.alpha, self.sample)["new_games"], 0)

    def test_stop(self):
        stop = threading.Event()
        seen = []

        def progress(done, total, detail):
            seen.append(done)
            if done >= 50:
                stop.set()
        with self.assertRaises(common.Stopped) as caught:
            gauntlet.run(self.alpha, self.sample, progress=progress, stop=stop, inflight=1, pool=object())
        note = field.last_note(self.alpha, self.gauntlet_dir)
        self.assertTrue(note["stopped"])
        self.assertLess(note["played"], 400)
        self.assertEqual(caught.exception.saved_games, note["played"])


class ViewTests(GauntletCase):

    def test_the_groups(self):
        rates = {IDS[0]: 0.8, IDS[1]: 0.3, IDS[2]: 0.5, IDS[3]: 0.6}
        for deck_id, rate in rates.items():
            self.gfake.add_games(self.alpha, self.opponent(deck_id), 100, rate=rate)
        found = gauntlet.view(self.alpha, self.sample)
        self.assertEqual(set(found), {"deck", "sample", "format", "opponents", "groups", "games", "note", "notes"})
        self.assertEqual((found["deck"], found["sample"], found["games"]), ("casual/alpha", self.sample["id"], 400))
        self.assertEqual(found["notes"], [])
        self.assertIn("these 4 sampled opponents only", found["note"])
        lows = [o["rate"]["low"] for o in found["opponents"]]
        self.assertEqual(lows, sorted(lows))
        self.assertEqual(found["opponents"][0]["id"], IDS[1])
        value = {o["id"]: o["rate"]["value"] for o in found["opponents"]}
        groups = {name: {g["key"]: g for g in rows} for name, rows in found["groups"].items()}
        self.assertEqual(set(groups), {"colour", "identity_size", "style", "tier"})
        self.assertEqual(list(groups["colour"]), ["U", "R", "G"])
        blue = groups["colour"]["U"]
        self.assertEqual((blue["opponents"], blue["games"]), (2, 200))
        self.assertAlmostEqual(blue["rate"], (value[IDS[1]] + value[IDS[2]]) / 2, places=3)
        self.assertLessEqual(blue["low"], blue["rate"])
        self.assertGreaterEqual(blue["high"], blue["rate"])
        self.assertEqual(blue["spread"], sorted([value[IDS[1]], value[IDS[2]]]))
        self.assertIn("overlapping", blue["note"])
        self.assertEqual(groups["colour"]["G"]["note"].split("; ")[0], gauntlet.ONE)
        self.assertEqual({k: g["opponents"] for k, g in groups["identity_size"].items()}, {"mono": 3, "two": 1})
        self.assertEqual(list(groups["style"]), ["aggro", "control", "ramp"])
        self.assertEqual(groups["style"]["control"]["opponents"], 2)
        self.assertEqual(groups["style"]["aggro"]["note"], gauntlet.ONE)
        self.assertEqual({k: g["opponents"] for k, g in groups["tier"].items()}, {"medium": 2, "hard": 2})
        for rows in found["groups"].values():
            for g in rows:
                self.assertEqual(set(g), {"key", "label", "opponents", "games", "rate", "low", "high", "spread",
                                          "note"})
        json.dumps(found, allow_nan=False)

    def test_a_group_without_games_and_a_changed_catalogue(self):
        self.gfake.add_games(self.alpha, self.opponent(IDS[0]), 100, rate=0.6)
        changed = dict(self.sample, catalogue_sha="b" * 64, decks=IDS + ["gauntlet:forge/duels/broken"])
        found = gauntlet.view(self.alpha, changed)
        self.assertEqual(len(found["notes"]), 2)
        self.assertEqual(len(found["opponents"]), 4)
        groups = {g["key"]: g for g in found["groups"]["colour"]}
        self.assertIsNone(groups["G"]["rate"])
        self.assertIsNone(groups["G"]["spread"])
        self.assertEqual(found["opponents"][-1]["rate"], None)
        # The house field's view never names a gauntlet deck.
        self.assertFalse(any(o["id"].startswith("gauntlet:") for o in field.view(self.alpha, self.results)["opponents"]))


class CliTests(GauntletCase):

    def run_cli(self, *argv):
        out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="\n")
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(["gauntlet", *argv])
            out.flush()
        return code, out.buffer.getvalue().decode("utf-8"), err.getvalue()

    def test_list_show_and_sample(self):
        code, out, err = self.run_cli("list", "--format", "constructed")
        self.assertEqual(code, 0, err)
        self.assertIn("4 decks", out)
        self.assertNotIn("Broken", out)
        code, out, _ = self.run_cli("list", "--format", "constructed", "--all", "--styles", "midrange")
        self.assertIn("can't be played", out)
        code, out, _ = self.run_cli("show", IDS[2])
        self.assertEqual(code, 0)
        self.assertIn("Izzet Spells", out)
        self.assertIn("4 Shock", out)
        code, _, err = self.run_cli("show", "gauntlet:nope")
        self.assertEqual(code, 1)
        code, out, _ = self.run_cli("sample", "--format", "constructed", "--size", "3", "--json")
        found = json.loads(out)
        self.assertEqual(found["decks"], IDS[:3])
        self.assertIn(found["id"], self.samples)
        code, _, err = self.run_cli("list", "--format", "commander")
        self.assertEqual(code, 1)
        self.assertIn("no commander gauntlet", err)

    def test_plan_play_and_view(self):
        code, out, err = self.run_cli("plan", "casual/alpha", "--size", "4", "--budget", "50")
        self.assertEqual(code, 0, err)
        self.assertIn("4 opponents, about 200 new games at fixed:50", out)
        self.assertEqual(self.gfake.calls, [])
        code, out, err = self.run_cli("play", "casual/alpha", "--sample", "sample:000000000004", "--budget", "fixed:50",
                                      "--inflight", "2")
        self.assertEqual(code, 0, err)
        self.assertIn("Played 200 games", out)
        self.assertIn("By colour:", out)
        self.assertIn(gauntlet.ONE, out)
        self.assertIn("sampled opponents only", out)
        self.assertEqual(self.fake.calls, [])
        code, out, _ = self.run_cli("view", "casual/alpha", "--size", "4", "--by", "style")
        self.assertIn("By style:", out)
        self.assertNotIn("By colour:", out)
        self.assertIn("Control: ", out)
        self.assertIn("2 opponents; 100 games", out)
        code, out, _ = self.run_cli("view", "casual/alpha", "--size", "4", "--json")
        self.assertEqual(json.loads(out)["games"], 200)
        code, _, err = self.run_cli("view", "casual/alpha", "--sample", "sample:nope")
        self.assertEqual(code, 1)
        self.assertIn("no saved gauntlet sample", err)
