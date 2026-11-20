"""Tests for the editor's Test this change against popular decks (E3-S30's page half,
decklab/lib/api/variant_page.py): GET /api/variant/estimate?against=gauntlet counts the format's
standard sample (no mirror) and reads the base's games in the gauntlet's results folder; POST
/api/variant/run {"against": "gauntlet"} starts the command line's own test (the same id) in that
folder, leaving a trial's own precon out; GET /api/variant, GET /api/variants, POST /api/variant/stop
and /more find it there; its opponents (public sparring decks) are always shown; and the view keeps
forge.variants.view's "sample", "groups" and "note".

They use test_variant_api's sandbox and run_test stand-in, with test_variant_gauntlet's hand-written
catalogue and sample (no network call, no Forge process).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_variant_gauntlet_api
"""
import unittest
from unittest import mock

from decklab.lib import api
from decklab.lib import forge as real_forge
from decklab.lib.api import variant_page
from decklab.tests.test_variant_api import GREEN_ID, SWAPPED, VariantApiCase, body, editor_list
from decklab.tests.test_variant_gauntlet import CATALOGUE, SAMPLE

AGAINST = "gauntlet:" + SAMPLE["id"]
CUSTOM_ID = "sample:000000000039"
MISSING_ID = "sample:000000000040"
COMMANDER_ID = "sample:000000000041"


class GauntletApiCase(VariantApiCase):

    def setUp(self):
        super().setUp()
        self.folder = self.box.data / "gauntlet-results"
        self.folder.mkdir(parents=True)
        self.catalogue = CATALOGUE
        self.samples = {SAMPLE["id"]: SAMPLE}
        self.saved = []
        g = real_forge.gauntlet

        def save(fmt, found):
            self.saved.append(found["id"])
            self.samples[found["id"]] = found
        for name, value in (("RESULTS_DIR", self.folder),
                            ("_load_catalogue", lambda fmt: self.catalogue if fmt == "constructed" else None),
                            ("_load_sample", lambda sid: self.samples.get(sid)),
                            ("_save_sample", save),
                            ("_choose", lambda decks, size, **kw: list(decks)[:size]),
                            ("_sample_id", lambda *a, **kw: SAMPLE["id"])):
            patch = mock.patch.object(g, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def fake_run_test(self, base_entry, variant_cards, against, mode="ahead", *, by, progress=None, results_dir=None,
                      pool=None, local=False, log_dir=None, log_every=1, opponents=None, extend=None,
                      field_options=None):
        """run_test's stand-in for a gauntlet sample: notes the call, resolves the folder as run_test does,
        and writes a tagged summary of the sample's opponents with one look."""
        v = real_forge.variants
        vg = v.gauntlet_tests
        if not vg.is_gauntlet(against):
            return super().fake_run_test(base_entry, variant_cards, against, mode, by=by, progress=progress,
                                         results_dir=results_dir, opponents=opponents, extend=extend,
                                         field_options=field_options)
        if results_dir is None:
            results_dir = vg.results_dir()
        self.calls.append({"base": base_entry["id"], "against": against, "mode": mode, "by": by, "extend": extend,
                           "results_dir": results_dir, "field_options": field_options})
        variant = v.variant_entry(base_entry, variant_cards)
        tid = extend or v.test_id(base_entry, variant, against, mode)
        entries = vg.opponents(base_entry, against, (field_options or {}).get("exclude_ids") or ())
        summary = v.load_summary(tid, results_dir) or vg.tag(
            v._new_summary(tid, base_entry, variant, against, mode, entries, 0.02, by, None))
        self.started.set()
        while not self.gate.wait(0.05):
            pass
        summary["looks"].append({"games_per_opponent": 200 * (len(summary["looks"]) + 1), "delta": 0.03,
                                 "low": 0.01, "high": 0.05, "z": 3.0, "bound": 2.0, "interim": False,
                                 "stopped": False, "decision": "better"})
        summary["outcome"] = "better"
        v._write_summary(summary, results_dir)
        return summary

    def start_popular(self, against="gauntlet", mode="quick", profile="matt"):
        return api.run_variant(body(profile=profile, id=GREEN_ID, version="target", list=editor_list(SWAPPED),
                                    against=against, mode=mode))


class EstimateTests(GauntletApiCase):

    def test_the_standard_sample_without_the_mirror(self):
        loaded = []
        real_load = real_forge.load

        def load(key, results_dir=None):
            loaded.append(results_dir)
            return real_load(key, results_dir)
        with mock.patch.object(real_forge, "load", load):
            answer = api.variant_estimate(GREEN_ID, "target", "gauntlet")
        # Green Mirror plays the base's own list, so the sample's 3 decks are 2 opponents.
        self.assertEqual((answer["against"], answer["available"], answer["problem"], answer["opponents"]),
                         ("gauntlet", True, None, 2))
        self.assertEqual(answer["max"]["ahead"], real_forge.variants._ahead_looks(True)[-1])
        self.assertTrue(loaded and all(d == self.folder for d in loaded), loaded)
        self.assertEqual(self.saved, [])            # an estimate never saves the standard sample

    def test_a_saved_sample_by_id(self):
        answer = api.variant_estimate(GREEN_ID, "target", AGAINST)
        self.assertEqual((answer["against"], answer["available"], answer["opponents"]), (AGAINST, True, 2))

    def test_no_catalogue_or_no_sample(self):
        self.catalogue = None
        answer = api.variant_estimate(GREEN_ID, "target", "gauntlet")
        self.assertEqual((answer["available"], answer["opponents"]), (False, 0))
        self.assertTrue(answer["problem"])
        missing = api.variant_estimate(GREEN_ID, "target", "gauntlet:sample:nothing")
        self.assertEqual(missing["available"], False)
        self.assertIn("no saved gauntlet sample", missing["problem"])

    def test_a_sample_of_the_other_format(self):
        self.samples[COMMANDER_ID] = dict(SAMPLE, id=COMMANDER_ID, format="commander")
        answer = api.variant_estimate(GREEN_ID, "target", "gauntlet:" + COMMANDER_ID)
        self.assertFalse(answer["available"])
        self.assertIn("commander", answer["problem"])

    def test_another_commanders_sample_looks_missing(self):
        self.samples[COMMANDER_ID] = dict(SAMPLE, id=COMMANDER_ID, format="commander",
                                          commander=["Ghalta, Primal Hunger"])
        other = api.variant_estimate(GREEN_ID, "target", "gauntlet:" + COMMANDER_ID)
        missing = api.variant_estimate(GREEN_ID, "target", "gauntlet:" + MISSING_ID)
        self.assertEqual((other["available"], other["opponents"], other["problem"]), (False, 0, missing["problem"]))


class RunTests(GauntletApiCase):
    def test_saved_custom_sample_uses_only_its_opponents_and_keeps_its_id(self):
        self.samples[CUSTOM_ID] = dict(SAMPLE, id=CUSTOM_ID, size=1, decks=["gauntlet:forge/duels/red-burn"])
        against = "gauntlet:" + CUSTOM_ID
        estimate = api.variant_estimate(GREEN_ID, "target", against)
        self.assertEqual((estimate["against"], estimate["available"], estimate["opponents"]), (against, True, 1))
        test = self.start_popular(against)["test"]["test"]
        done = self.wait_done(test)
        self.assertEqual(self.calls[-1]["against"], against)
        self.assertEqual(self.calls[-1]["results_dir"], self.folder)
        self.assertEqual(done["sample"], CUSTOM_ID)
        self.assertEqual([o["title"] for o in done["opponents"]], ["Red Burn"])
        self.assertEqual(self.saved, [])

    def test_refuses_a_changed_or_missing_sample_at_start(self):
        self.samples[CUSTOM_ID] = dict(SAMPLE, id=CUSTOM_ID)
        against = "gauntlet:" + CUSTOM_ID
        self.assertTrue(api.variant_estimate(GREEN_ID, "target", against)["available"])
        self.samples[CUSTOM_ID]["format"] = "commander"
        with self.assertRaises(api.ApiError) as raised:
            self.start_popular(against)
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("commander", str(raised.exception))

        self.samples[CUSTOM_ID]["commander"] = ["Ghalta, Primal Hunger"]
        with self.assertRaises(api.ApiError) as hidden:
            self.start_popular(against)
        del self.samples[CUSTOM_ID]
        with self.assertRaises(api.ApiError) as missing:
            self.start_popular(against)
        self.assertEqual((hidden.exception.status, str(hidden.exception)), (400, str(missing.exception)))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.saved, [])


    def test_a_run_is_the_command_lines_test_in_the_gauntlets_folder(self):
        view = self.start_popular()
        test = view["test"]["test"]
        done = self.wait_done(test)
        call = self.calls[-1]
        self.assertEqual((call["against"], call["mode"], call["results_dir"]), (AGAINST, "quick", self.folder))
        self.assertEqual(call["field_options"], {"exclude_ids": ()})
        self.assertEqual(self.saved, [SAMPLE["id"]])      # the standard sample is saved, as --gauntlet standard
        # The same id the command line gives: no field space in it.
        base = real_forge.variants.base_entry(GREEN_ID)
        cards, _ = variant_page._draft_cards(real_forge, GREEN_ID, "target", editor_list(SWAPPED))
        variant = real_forge.variants.variant_entry(base, cards)
        self.assertEqual(test, real_forge.variants.test_id(base, variant, AGAINST, "quick"))
        # Saved in the gauntlet's folder, never the default one.
        self.assertIsNotNone(real_forge.variants.load_summary(test, self.folder))
        self.assertIsNone(real_forge.variants.load_summary(test))
        # The view: every sparring deck shown, the groups and the caveat.
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["test"]["against"], AGAINST)
        self.assertEqual(sorted(o["title"] for o in done["opponents"]), ["Izzet Shocks", "Red Burn"])
        self.assertEqual(done["sample"], SAMPLE["id"])
        self.assertIn("2 sampled opponents only", done["note"])
        self.assertEqual([g["key"] for g in done["groups"]["colour"]], ["U", "R"])
        self.assertEqual([g["key"] for g in done["groups"]["tier"]], [t for t in real_forge.gauntlet.TIERS if t in ("hard", "medium")])
        self.assertIn("Better against the sampled popular decks", done["words"])

    def test_listed_with_the_decks_other_tests(self):
        test = self.start_popular()["test"]["test"]
        self.wait_done(test)
        other = self.start(mode="quick")["test"]["test"]
        self.wait_done(other)
        listed = {t["test"]: t for t in api.variant_tests(GREEN_ID, "target")["tests"]}
        self.assertEqual(set(listed), {test, other})
        self.assertEqual(listed[test]["against"], "gauntlet")
        self.assertEqual(listed[other]["against"], "Red Test")

    def test_a_running_test_is_listed_and_viewed(self):
        self.gate.clear()
        test = self.start_popular()["test"]["test"]
        self.assertTrue(self.started.wait(5))
        listed = api.variant_tests(GREEN_ID, "target")["tests"]
        self.assertEqual((listed[0]["test"], listed[0]["running"], listed[0]["against"]), (test, True, "gauntlet"))
        view = api.variant_view(test)
        self.assertIn(view["status"], ("queued", "running"))
        self.assertEqual(view["test"]["against"], AGAINST)
        self.gate.set()

    def test_play_more_and_stop_find_it(self):
        test = self.start_popular()["test"]["test"]
        self.wait_done(test)
        api.more_variant(body(profile="matt", test=test))
        self.wait_done(test)
        call = self.calls[-1]
        self.assertEqual((call["extend"], call["against"], call["results_dir"]), (test, AGAINST, self.folder))
        self.assertEqual(call["field_options"], {"exclude_ids": ()})
        stopped = api.stop_variant(body(profile="matt", test=test))
        self.assertEqual(stopped["test"]["test"], test)

    def test_a_trial_leaves_its_own_precon_out(self):
        with mock.patch("decklab.lib.gauntlet.trial_excluded", lambda summary: ("gauntlet:forge/duels/red-burn",)):
            estimate = api.variant_estimate(GREEN_ID, "target", "gauntlet")
            test = self.start_popular()["test"]["test"]
            done = self.wait_done(test)
        self.assertEqual(estimate["opponents"], 1)
        self.assertEqual(self.calls[-1]["field_options"], {"exclude_ids": ("gauntlet:forge/duels/red-burn",)})
        self.assertEqual([o["title"] for o in done["opponents"]], ["Izzet Shocks"])

    def test_refusals(self):
        for against in ("gauntlet:", "gauntlets", ["gauntlet"], {"id": "gauntlet"}):
            with self.subTest(against=against):
                with self.assertRaises(api.ApiError) as raised:
                    self.start_popular(against)
                self.assertIn(raised.exception.status, (400, 404))
        with self.assertRaises(api.ApiError) as raised:
            self.start_popular("gauntlet:sample:nothing")
        self.assertEqual(raised.exception.status, 400)
        self.assertIn("no saved gauntlet sample", str(raised.exception))
        self.catalogue = None
        with self.assertRaises(api.ApiError) as raised:
            self.start_popular()
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.calls, [])

    def test_the_mirror_only_sample_has_no_opponent(self):
        self.catalogue = dict(CATALOGUE, decks=[d for d in CATALOGUE["decks"] if d["title"] == "Green Mirror"])
        self.samples[SAMPLE["id"]] = dict(SAMPLE, decks=[d["id"] for d in self.catalogue["decks"]])
        with self.assertRaises(api.ApiError) as raised:
            self.start_popular(AGAINST)
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(str(raised.exception), real_forge.variants.gauntlet_tests.NO_OPPONENTS)


class ViewerTests(GauntletApiCase):
    """Signed-in viewers: the sparring decks are always shown to the base's own space, and a test of a
    deck another space can't see is a missing test, popular decks or not."""

    def setUp(self):
        super().setUp()
        import json
        from decklab.lib import inventory, state
        from decklab.lib.inventory.files import FileInventory
        from decklab.lib.state.memory import MemoryStore
        from decklab.tests.test_api import _write
        from decklab.tests.test_collection_edit import ROLES
        _write(self.box.root / "config.json", json.dumps(ROLES))
        self.addCleanup(inventory.use(FileInventory(self.box.root)))
        self.addCleanup(state.use(MemoryStore(mode="everyone")))

    def test_the_bases_space_sees_every_sparring_deck_and_another_space_nothing(self):
        from decklab.tests.test_deck_privacy_readers import _as
        with _as("matt"):
            test = self.start_popular()["test"]["test"]
            self.wait_done(test)
            seen = api.variant_view(test)
            listed = api.variant_tests(GREEN_ID, "target")["tests"]
        self.assertEqual(sorted(o["title"] for o in seen["opponents"]), ["Izzet Shocks", "Red Burn"])
        self.assertIn("Better against the sampled popular decks", seen["words"])
        self.assertEqual([g["key"] for g in seen["groups"]["colour"]], ["U", "R"])
        self.assertEqual(([t["test"] for t in listed], listed[0]["against"]), ([test], "gauntlet"))
        with _as("user2"):
            with self.assertRaises(api.ApiError) as raised:
                api.variant_view(test)
            self.assertEqual(raised.exception.status, 404)
            with self.assertRaises(api.ApiError) as raised:
                api.stop_variant(body(profile="user2", test=test))
            self.assertEqual(raised.exception.status, 404)

    def test_the_queue_review_finds_it(self):
        from decklab.lib.api import variant_queue
        test = self.start_popular()["test"]["test"]
        self.wait_done(test)
        profile = {"id": "matt", "name": "Matt", "role": "admin", "space": "home"}
        self.assertEqual(variant_queue._saved(test, profile)["test"], test)


if __name__ == "__main__":
    unittest.main()
