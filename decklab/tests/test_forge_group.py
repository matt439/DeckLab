"""Tests for the group run (E3-S31, closing E3-S19's criterion 2): decklab.lib.forge.group's checks,
its house entries, its run (field.run_field over the chosen decks' opponent_entries into the ordinary
results folder, so the field view and the ratings see its games), its note (left out of the field's
last run) and its view (the gauntlet's overall group), and the command line's field --group.

They run on test_forge_field's small magic/ tree with its FakeField standing in for runner.run,
lists.matchup_key and saved.load, so no Forge process starts.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_group
"""
import json
from unittest import mock

from decklab.lib.forge import field, group
from decklab.tests import test_forge_field as base
from decklab.tests.test_forge_field import FieldTestCase


class GroupTestCase(FieldTestCase):

    def group_run(self, deck_id="casual/alpha", opponents=("casual/beta", "casual/gamma"), budget="fixed:50"):
        return group.run(self.entry(deck_id), [group.house_entry(o) for o in opponents], budget, by="Matt",
                         results_dir=self.results, pool=object(), inflight=1)


class CheckTests(GroupTestCase):

    def test_house_entries_are_the_lists_the_field_plays(self):
        # Beta is built with an owned-only Built version line; Gamma is built without one.
        self.assertEqual(group.house_entry("casual/beta")["version"], "owned")
        self.assertEqual(group.house_entry("casual/gamma")["version"], "target")
        self.assertEqual(group.house_entry("casual/beta", "target")["version"], "target")
        with self.assertRaisesRegex(ValueError, "No deck"):
            group.house_entry("casual/nope")
        with self.assertRaisesRegex(ValueError, "no owned list"):
            group.house_entry("casual/alpha", "owned")

    def test_refusals_name_only_the_decks_given(self):
        a = self.entry("casual/alpha")
        beta, cmdr = group.house_entry("casual/beta"), group.house_entry("commander/cmdr")
        cases = [([], group.NONE), ([a], "Alpha can't be in its own group"),
                 ([dict(beta, id="casual/other", card_sha=a["card_sha"])], "exactly this deck's list"),
                 ([cmdr], "Cmdr plays Commander, but this deck plays Constructed"),
                 ([beta, beta], "Beta is in the group twice")]
        for chosen, words in cases:
            with self.subTest(words=words), self.assertRaises(ValueError) as caught:
                group.check(a, chosen)
            self.assertIn(words, str(caught.exception))
        with mock.patch.object(group, "MAX_OPPONENTS", 1), self.assertRaisesRegex(ValueError, "at most 1"):
            group.check(a, [beta, group.house_entry("casual/gamma")])
        self.assertEqual(group.check(a, [beta]), [beta])


class RunTests(GroupTestCase):

    def test_the_group_plays_only_the_chosen_decks_into_the_ordinary_results(self):
        a = self.entry("casual/alpha")
        planned = group.plan(a, [group.house_entry("casual/beta")], "fixed:50", results_dir=self.results)
        self.assertEqual([p["opponent"]["id"] for p in planned["pairs"]], ["casual/beta"])
        note = self.group_run()
        self.assertEqual(sorted(c[0] for c in self.fake.calls), ["casual/beta", "casual/gamma"])
        self.assertEqual(note["played"], 100)
        self.assertEqual(note["group"], [{"id": "casual/beta", "version": "owned"},
                                         {"id": "casual/gamma", "version": "target"}])
        # Ordinary matchups: the field view (and so the ratings) sees the group's games.
        shown = {o["id"]: o["games"] for o in field.view(a, results_dir=self.results)["opponents"]}
        self.assertEqual((shown["casual/beta"], shown["casual/gamma"], shown["product/aggro"]), (50, 50, 0))

    def test_a_group_note_is_never_the_fields_last_run(self):
        a = self.entry("casual/alpha")
        self.group_run()
        self.assertIsNone(field.last_note(a, self.results))
        whole = self.play(budget="fixed:50")
        self.assertNotIn("group", whole)
        self.group_run(opponents=("casual/gamma",))
        last = field.last_note(a, self.results)
        self.assertEqual((last["when"], last["played"]), (whole["when"], whole["played"]))
        self.assertNotIn("group", last)


class ViewTests(GroupTestCase):

    def test_the_view_gives_the_groups_average(self):
        a = self.entry("casual/alpha")
        chosen = [group.house_entry("casual/beta"), group.house_entry("casual/gamma")]
        before = group.view(a, chosen, results_dir=self.results)
        self.assertEqual((before["played"], before["of"], before["games"], before["updated"]), (0, 2, 0, None))
        self.assertIsNone(before["overall"]["rate"])
        self.fake.rates.update({"casual/beta": 0.8, "casual/gamma": 0.3})
        self.group_run(budget="fixed:200")
        found = group.view(a, chosen, results_dir=self.results)
        self.assertEqual((found["played"], found["of"], found["games"]), (2, 2, 400))
        # Hardest first: Gamma (Alpha wins about 30%) before Beta (about 80%).
        self.assertEqual([o["id"] for o in found["opponents"]], ["casual/gamma", "casual/beta"])
        overall = found["overall"]
        self.assertEqual((overall["key"], overall["label"], overall["opponents"], overall["games"]),
                         ("all", group.LABEL, 2, 400))
        rates = [o["rate"]["value"] for o in found["opponents"]]
        self.assertAlmostEqual(overall["rate"], sum(rates) / 2, places=3)
        self.assertEqual(overall["spread"], [min(rates), max(rates)])
        self.assertIn("2 chosen decks only", found["note"])
        self.assertEqual(sum(found["tally"].values()), 2)
        self.assertEqual(found["deck"]["id"], "casual/alpha")
        json.dumps(found, allow_nan=False)
        one = group.view(a, chosen[:1], results_dir=self.results)
        self.assertIn("not a group", one["overall"]["note"])

    def test_keep_leaves_out_saved_results(self):
        a = self.entry("casual/alpha")
        self.group_run()
        found = group.view(a, [group.house_entry("casual/beta")], results_dir=self.results, keep=lambda r: False)
        self.assertEqual((found["games"], found["played"]), (0, 0))


class GroupCliTests(GroupTestCase):

    run_cli = base.CliTests.run_cli

    def test_group_dry_run_show_and_play(self):
        code, out, err = self.run_cli("casual/alpha", "--group", "casual/beta,casual/gamma@owned", "--dry-run",
                                      "--json", "--fixed", "50", "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        planned = json.loads(out)
        self.assertEqual([(p["id"], p["version"]) for p in planned["pairs"]],
                         [("casual/beta", "owned"), ("casual/gamma", "owned")])
        self.assertEqual(planned["new_games"], 100)
        code, out, err = self.run_cli("casual/alpha", "--group", "casual/beta", "--fixed", "50",
                                      "--results-dir", str(self.results))
        self.assertEqual(code, 0, err)
        self.assertEqual([c[0] for c in self.fake.calls], ["casual/beta"])
        self.assertIn("Played 50 games", out)
        self.assertIn("against a group of 1 Constructed decks", out)
        code, out, _ = self.run_cli("casual/alpha", "--group", "casual/beta", "--show", "--json",
                                    "--results-dir", str(self.results))
        self.assertEqual(json.loads(out)["games"], 50)

    def test_group_refusals(self):
        for argv, words in ((("--group", "casual/beta", "--opponents", "casual/gamma"), "one of them"),
                            (("--group", "casual/nope"), "No deck"),
                            (("--group", "casual/beta@built"), "@target or @owned"),
                            (("--group", "casual/alpha"), "its own group"),
                            (("--group", ""), group.NONE)):
            with self.subTest(argv=argv):
                code, _, err = self.run_cli("casual/alpha", *argv, "--dry-run", "--results-dir", str(self.results))
                self.assertEqual(code, 1)
                self.assertIn(words, err)
        self.assertEqual(self.fake.calls, [])
