"""Tests for a variant test against a saved gauntlet sample (E3-S30, decklab/lib/forge/variants_gauntlet.py
and variants.run_test's against="gauntlet:<sample id>"): the changed list plays the base list's own
gauntlet games (the same seeds and seats) in the gauntlet's results folder, the field's looks and
margin judge it, the view gives the difference overall and by group with the caveat that it covers
those sampled opponents only, and python -m decklab.lib.forge variant --gauntlet.

They reuse test_forge_variants' stand-in for runner.run (no Forge process starts) and a hand-written
catalogue and sample (no network call).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_variant_gauntlet
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import common, engine, gauntlet, runner, variants, variants_gauntlet
from decklab.tests.test_forge import GREEN, RED, entry
from decklab.tests.test_forge_variants import ORDER, CommandLineTests, FakeRuns, changed, seqstats_built

BLUE = RED.replace("4 Lightning Bolt", "4 Shock")


def _deck(slug, title, identity, style, tier, text, playable=True):
    return {"id": f"gauntlet:forge/duels/{slug}", "title": title, "kind": "constructed",
            "source": {"kind": "forge", "file": f"res/quest/duels/{slug}.dck"}, "tier": tier,
            "identity": identity, "colours": identity, "style": {"primary": style, "tags": [], "themes": []},
            "playable": playable, "cards": {"Commander": [], "Main": entry(text)["cards"]["Main"]}}


CATALOGUE = {"kind": "constructed", "sha": "a" * 64, "decks": [
    _deck("red-burn", "Red Burn", "R", "aggro", "medium", RED),
    _deck("izzet-shocks", "Izzet Shocks", "UR", "control", "hard", BLUE),
    _deck("green-mirror", "Green Mirror", "G", "ramp", "hard", GREEN)]}
SAMPLE = {"id": "sample:000000000003", "format": "constructed", "catalogue_sha": "a" * 64,
          "filters": {"colours": None, "styles": None, "tiers": ["hard", "medium"]}, "size": 3, "seed": "",
          "decks": [d["id"] for d in CATALOGUE["decks"]]}
AGAINST = "gauntlet:" + SAMPLE["id"]


class GauntletVariantCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.folder = self.tmp / "gauntlet"
        self.folder.mkdir()
        self.runs = FakeRuns(self.folder)
        self.dirs = []
        self.samples = {SAMPLE["id"]: SAMPLE, "sample:commander000": dict(SAMPLE, id="sample:commander000",
                                                                          format="commander")}

        def run(a, b, games, *, results_dir=None, **kwargs):
            self.dirs.append(Path(results_dir) if results_dir is not None else None)
            return self.runs(a, b, games, results_dir=results_dir, **kwargs)
        settings = {"forge_field_inflight": 2, "forge_variant_margin": 0.02, "forge_variant_margin_one": 0.03}
        for p in (mock.patch.object(runner, "run", run),
                  mock.patch.object(engine, "today", return_value=dict(ORDER, complete=True)),
                  mock.patch.object(variants, "_base_key", lambda a, b: self.runs.key(a, b)),
                  mock.patch.object(common, "_settings", lambda: dict(settings)),
                  mock.patch.object(gauntlet, "RESULTS_DIR", self.folder),
                  mock.patch.object(gauntlet, "_load_catalogue", lambda fmt: CATALOGUE if fmt == "constructed" else None),
                  mock.patch.object(gauntlet, "_load_sample", lambda sid: self.samples.get(sid)),
                  mock.patch.object(gauntlet, "_save_sample", lambda fmt, found: None),
                  mock.patch.object(gauntlet, "_choose", lambda decks, size, **kw: [d for d in decks][:size]),
                  mock.patch.object(gauntlet, "_sample_id", lambda *a, **kw: SAMPLE["id"])):
            p.start()
            self.addCleanup(p.stop)
        self.base = entry(GREEN, "casual/green", title="Green")
        self.cards = changed(GREEN, [(1, "Fiery Annihilation")], [(1, "Shock")])
        self.red, self.blue = gauntlet.entries("constructed", SAMPLE["decks"][:2])

    def run_test(self, against=AGAINST, mode="quick", **kwargs):
        return variants.run_test(self.base, self.cards, against, mode, by="Matt", **kwargs)


class OpponentTests(GauntletVariantCase):

    def test_the_sample_without_a_mirror_or_a_trial_precon(self):
        found = variants._opponent_entries(self.base, AGAINST, None)
        self.assertEqual([e["id"] for e in found], SAMPLE["decks"][:2])     # Green Mirror is the base's list
        found = variants._opponent_entries(self.base, AGAINST, None, {"exclude_ids": [SAMPLE["decks"][0]]})
        self.assertEqual([e["id"] for e in found], [SAMPLE["decks"][1]])

    def test_refusals(self):
        for against, words in (("gauntlet:sample:ffffffffffff", "There's no saved gauntlet sample"),
                               ("gauntlet:sample:commander000", "That sample is of commander decks")):
            with self.assertRaises(common.ForgeError) as caught:
                variants._opponent_entries(self.base, against, None)
            self.assertIn(words, str(caught.exception))
        with self.assertRaises(common.ForgeError) as caught:
            variants._opponent_entries(self.base, AGAINST, None, {"exclude_ids": SAMPLE["decks"][:2]})
        self.assertEqual(str(caught.exception), variants_gauntlet.NO_OPPONENTS)
        self.assertFalse(variants_gauntlet.is_gauntlet("gauntlet:"))
        self.assertFalse(variants_gauntlet.is_gauntlet("field"))

    def test_its_test_id_is_its_own(self):
        variant = variants.variant_entry(self.base, self.cards)
        ids = {variants.test_id(self.base, variant, AGAINST, "quick"),
               variants.test_id(self.base, variant, "gauntlet:sample:000000000004", "quick"),
               variants.test_id(self.base, variant, "field", "quick")}
        self.assertEqual(len(ids), 3)


@unittest.skipUnless(seqstats_built(), "needs seqstats' paired functions (package S)")
class RunTests(GauntletVariantCase):

    def test_the_variant_plays_the_base_lists_own_gauntlet_games(self):
        for opponent in (self.red, self.blue):          # the gauntlet run's own games, before the test
            self.runs(self.base, opponent, 250, by="Matt")
        self.runs.calls.clear()
        summary = self.run_test()
        # Only paired runs: the base's saved gauntlet games are enough, on their seeds and seats.
        self.assertEqual([c["kind"] for c in self.runs.calls], ["paired", "paired"])
        self.assertEqual(set(self.dirs), {self.folder})        # never the default results folder
        variant = variants.variant_entry(self.base, self.cards)
        for call, record in zip(sorted(self.runs.calls, key=lambda c: c["b"]),
                                sorted(summary["opponents"], key=lambda r: r["id"])):
            self.assertEqual(call["numbers"], list(range(200)))
            base = forge.load(record["base_key"], self.folder)
            beta = [s["card_sha"] for s in base["sides"]].index(self.base["card_sha"])
            self.assertEqual(call["seeds"], {"base": base["seeds"]["base"], "stream": base["seeds"]["stream"],
                                             "flip": variants.paired_flip(base["seeds"]["flip"], beta,
                                                                          record["variant_side"])})
            self.assertEqual(record["paired_key"], variants.paired_key(record["base_key"], beta, variant["card_sha"],
                                                                       variant["dck_sha"]))
        self.assertEqual(summary["against"], AGAINST)
        self.assertEqual(summary["margin"], 0.02)               # the field's margin: several opponents
        self.assertEqual(summary["starter_mismatch"]["games"], 0)
        self.assertEqual({r["id"]: r["group"] for r in summary["opponents"]},
                         {SAMPLE["decks"][0]: {"identity": "R", "style": "aggro", "tier": "medium"},
                          SAMPLE["decks"][1]: {"identity": "UR", "style": "control", "tier": "hard"}})
        self.assertTrue((self.folder / "paired" / "tests" / f"{summary['test']}.json").exists())
        self.assertEqual(variants.tests_for("casual/green", "target", self.folder)[0]["test"], summary["test"])

    def test_the_view_by_group_covers_the_sampled_opponents_only(self):
        summary = self.run_test()
        found = variants.view(summary["test"], self.folder)
        self.assertEqual(found["sample"], SAMPLE["id"])
        self.assertIsNotNone(found["field"])                    # the difference over the whole sample
        self.assertIn("the sampled popular decks", found["words"])
        self.assertEqual(found["note"], variants_gauntlet.note(2))
        self.assertIn("these 2 sampled opponents only", found["note"])
        groups = found["groups"]
        self.assertEqual([g["key"] for g in groups["colour"]], ["U", "R"])
        red = next(g for g in groups["colour"] if g["key"] == "R")
        self.assertEqual(red["opponents"], 2)
        self.assertIn(gauntlet.OVERLAP, red["note"])
        self.assertAlmostEqual(red["delta"], found["field"]["delta"])
        blue = next(g for g in groups["colour"] if g["key"] == "U")
        self.assertTrue(blue["note"].startswith(gauntlet.ONE))
        self.assertEqual([g["key"] for g in groups["identity_size"]], ["mono", "two"])
        self.assertEqual([g["key"] for g in groups["style"]], ["aggro", "control"])
        self.assertEqual([g["key"] for g in groups["tier"]], ["medium", "hard"])
        self.assertTrue(all(g["delta"] is not None for g in groups["tier"]))
        # A test against one house deck has no groups.
        other = entry(RED.replace("2 Fire // Ice", "2 Shock"), "casual/red", title="Red")
        house = variants.run_test(self.base, self.cards, other, "quick", by="Matt", results_dir=self.folder)
        self.assertNotIn("groups", variants.view(house["test"], self.folder))


class GroupTests(unittest.TestCase):

    def test_an_untagged_opponent_is_unknown_never_colourless(self):
        rows = [({"id": "a", "group": {"identity": "", "style": "aggro", "tier": "easy"}}, None),
                ({"id": "b"}, None),
                ({"id": "c", "group": {"identity": None, "style": None, "tier": None}}, None)]
        found = variants_gauntlet.groups(rows)
        self.assertEqual([(g["key"], g["opponents"]) for g in found["colour"]], [("C", 1), ("unknown", 2)])
        self.assertEqual([(g["key"], g["opponents"]) for g in found["identity_size"]],
                         [("colourless", 1), ("unknown", 2)])
        self.assertEqual([(g["key"], g["opponents"]) for g in found["style"]], [("aggro", 1), ("unknown", 2)])

    def test_tag_leaves_a_deck_the_catalogue_lacks_untagged(self):
        summary = {"base": {"kind": "casual"}, "opponents": [{"id": "gone"}, {"id": "here"}]}
        cat = {"decks": [{"id": "here", "identity": "", "style": {"primary": "ramp"}, "tier": "easy"}]}
        with mock.patch.object(gauntlet, "catalogue", return_value=cat):
            variants_gauntlet.tag(summary)
        self.assertNotIn("group", summary["opponents"][0])
        self.assertEqual(summary["opponents"][1]["group"], {"identity": "", "style": "ramp", "tier": "easy"})


@unittest.skipUnless(seqstats_built(), "needs seqstats' paired functions (package S)")
class GauntletCommandLineTests(GauntletVariantCase):

    main = CommandLineTests.main
    dck = CommandLineTests.dck

    def test_variant_gauntlet(self):
        green = self.dck("green", GREEN)
        code, out, err = self.main("variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock",
                                   "--gauntlet", SAMPLE["id"], "--quick")
        self.assertEqual(code, 0, err)
        self.assertIn(f"against gauntlet sample {SAMPLE['id']}", err)
        self.assertIn("the sampled popular decks", out)
        self.assertIn("By colour:", out)
        self.assertIn("By tier:", out)
        self.assertIn("sampled opponents only", out)
        self.assertEqual(set(self.dirs), {self.folder})
        test = out.strip().splitlines()[-1].split()[-1]
        # --against gauntlet:<id> is the same test; --more finds it in the gauntlet's folder.
        code, out, err = self.main("variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock",
                                   "--against", AGAINST, "--quick", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["test"]["test"], test)
        code, out, err = self.main("variant", green, "--more", test)
        self.assertEqual(code, 0, err)
        self.assertIn("By style:", out)
        # The standard sample is drawn by its id.
        code, out, err = self.main("variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock",
                                   "--gauntlet", "standard", "--quick", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["test"]["against"], AGAINST)

    def test_mistakes(self):
        green = self.dck("green", GREEN)
        for argv, words in ((["--gauntlet", SAMPLE["id"], "--field"], "not more than one"),
                            (["--gauntlet", "sample:ffffffffffff"], "There's no saved gauntlet sample"),
                            (["--gauntlet", "sample:commander000"], "is a commander sample")):
            code, out, err = self.main("variant", green, "--remove", "1 Fiery Annihilation", "--add", "1 Shock",
                                       "--quick", *argv)
            self.assertEqual(code, 1, (argv, out, err))
            self.assertIn(words, err)


if __name__ == "__main__":
    unittest.main()
