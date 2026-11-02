"""Choosing a gauntlet sweep (lib/gauntlet/sample.py, design decklab/design/gauntlet.md section 5): the
same seed gives the same sample, every colour bucket is covered, the filters, a size larger or
smaller than the bucket count, unplayable decks left out, a stable sample id, and a saved sample
read back from a temporary data folder.

The catalogue entries are hand-written (entry below); no catalogue is built and nothing is fetched.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_sample
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import gauntlet
from decklab.lib.gauntlet import sample


def entry(deck_id, identity, primary="midrange", tier="core", rank=None, decks=None, playable=True):
    """A catalogue entry with the fields a sample reads."""
    return {"id": "gauntlet:edhrec/" + deck_id, "title": deck_id, "kind": "commander", "tier": tier,
            "identity": identity, "colours": identity, "playable": playable,
            "source": {"kind": "edhrec", "rank": rank, "decks": decks},
            "style": {"primary": primary, "tags": [], "themes": []}}


def one_per_bucket():
    """A deck in every colour bucket, ranked in bucket order, styles in turn."""
    out = []
    for i, key in enumerate(sample.BUCKETS):
        identity = "WUBRG" if key == sample.FOUR_PLUS else key
        out.append(entry(f"b{i}-{identity or 'c'}-core", identity, sample.STYLES[i % 5], rank=i + 1))
    return out


class ChooseTests(unittest.TestCase):
    def test_one_deck_per_commander(self):
        core = entry("k-core", "G", tier="upgraded", rank=1)        # a core deck re-tiered to upgraded
        upgraded = entry("k-upgraded", "G", tier="upgraded", rank=1)
        for deck in (core, upgraded):
            deck["cards"] = {"Commander": [[1, "Kodama"]], "Main": []}
        other = entry("other-upgraded", "R", tier="upgraded", rank=2)
        chosen = sample.choose([core, upgraded, other], 5, tiers=["upgraded"])
        self.assertEqual(len(chosen), 2)
        self.assertEqual(sum(d["id"] in (core["id"], upgraded["id"]) for d in chosen), 1)

    def test_one_version_per_duel_title_nearest_the_tiers(self):
        def duel(name, tier):
            made = entry(name, "B", tier=tier)
            made.update(kind="constructed", duel_title="Agent K", source={"kind": "forge"})
            return made
        versions = [duel("k-easy", "easy"), duel("k-medium", "medium"), duel("k-hard", "hard")]
        self.assertEqual([d["tier"] for d in sample.choose(versions, 5, tiers=["easy"])], ["easy"])
        self.assertEqual([d["tier"] for d in sample.choose(versions, 5, tiers=["medium", "hard"])], ["medium"])
        self.assertEqual([d["tier"] for d in sample.choose(versions, 5)], ["medium"])

    def test_buckets(self):
        self.assertEqual(len(sample.BUCKETS), 27)
        self.assertEqual(len(set(sample.BUCKETS)), 27)
        self.assertEqual(sample.bucket("GW"), "WG")
        self.assertEqual(sample.bucket("WUBR"), sample.FOUR_PLUS)
        self.assertEqual(sample.bucket(""), "")
        for key in sample.BUCKETS[5:]:
            if key not in (sample.FOUR_PLUS, ""):
                self.assertEqual(sample.bucket(key), key)       # every bucket is in WUBRG order

    def test_the_same_seed_gives_the_same_sample(self):
        decks = [entry(f"d{i}", "WUBRG"[i % 5], sample.STYLES[i % 5]) for i in range(40)]
        first = [d["id"] for d in sample.choose(decks, 12, seed="a")]
        self.assertEqual(first, [d["id"] for d in sample.choose(list(reversed(decks)), 12, seed="a")])
        seeds = {tuple(d["id"] for d in sample.choose(decks, 12, seed=s)) for s in "abcdef"}
        self.assertGreater(len(seeds), 1)       # with no popularity, the seed breaks the ties

    def test_every_bucket_is_covered(self):
        decks = one_per_bucket() + [entry(f"extra{i}", "W", rank=1) for i in range(10)]
        chosen = sample.choose(decks, 27)
        self.assertEqual({sample.bucket(d["identity"]) for d in chosen}, set(sample.BUCKETS))

    def test_a_size_smaller_than_the_buckets_walks_them_in_order(self):
        chosen = sample.choose(one_per_bucket(), 5)
        self.assertEqual([d["identity"] for d in chosen], list("WUBRG"))

    def test_a_size_larger_than_the_buckets_fills_by_popularity(self):
        extras = [entry(f"extra{i}", "WU", rank=100 + i) for i in range(10)]
        chosen = sample.choose(one_per_bucket() + extras, 30)
        self.assertEqual(len(chosen), 30)
        self.assertEqual([d["id"] for d in chosen[-3:]], [d["id"] for d in extras[:3]])
        self.assertEqual(len(sample.choose(one_per_bucket(), 100)), 27)     # never more than there are

    def test_the_colour_pass_prefers_a_new_style(self):
        decks = [entry("w-aggro", "W", "aggro", rank=1), entry("u-aggro", "U", "aggro", rank=2),
                 entry("u-control", "U", "control", rank=50)]
        self.assertEqual([d["title"] for d in sample.choose(decks, 2)], ["w-aggro", "u-control"])

    def test_the_style_pass_brings_each_style_to_two(self):
        decks = [entry(f"aggro{i}", "WUBRG"[i % 5], "aggro", rank=i + 1) for i in range(10)]
        decks += [entry(f"control{i}", "U", "control", rank=100 + i) for i in range(3)]
        chosen = sample.choose(decks, 8)
        styles = [d["style"]["primary"] for d in chosen]
        self.assertEqual(styles.count("control"), 2)
        self.assertEqual(len(chosen), 8)

    def test_unplayable_decks_are_left_out(self):
        decks = [entry("bad", "W", rank=1, playable=False), entry("good", "W", rank=2),
                 {**entry("unknown", "U", rank=3), "playable": None}]
        self.assertEqual([d["id"] for d in sample.choose(decks, 5)], ["gauntlet:edhrec/good"])

    def test_filters(self):
        decks = one_per_bucket() + [entry("w-up", "W", "aggro", tier="upgraded", rank=1)]
        chosen = sample.choose(decks, 50, colours="uw")
        self.assertEqual({d["identity"] for d in chosen}, {"W", "U", "WU", ""})
        chosen = sample.choose(decks, 50, styles=["control"])
        self.assertTrue(chosen and all(d["style"]["primary"] == "control" for d in chosen))
        chosen = sample.choose(decks, 50, tiers=["upgraded"])
        self.assertEqual([d["id"] for d in chosen], ["gauntlet:edhrec/w-up"])

    def test_popularity(self):
        ranked = entry("r", "W", rank=3, decks=10)
        counted = entry("c", "W", decks=5000)
        tiered = {**entry("t", "W", tier="hard"), "source": {"kind": "forge", "rank": None, "decks": None}}
        precon = {**entry("p", "W", tier="precon"), "source": {"kind": "forge", "rank": None, "decks": None}}
        order = sorted([precon, tiered, counted, ranked], key=sample.popularity)
        self.assertEqual([d["title"] for d in order], ["r", "c", "t", "p"])


class SampleFileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(gauntlet, "DATA", Path(tmp.name) / "gauntlet")
        patch.start()
        self.addCleanup(patch.stop)

    def test_sample_id_is_stable(self):
        filters = {"colours": "UW", "styles": ["control", "aggro"], "tiers": ["core"]}
        sid = sample.sample_id("abc", filters, 20, "")
        self.assertRegex(sid, r"^sample:[0-9a-f]{12}$")
        same = {"colours": "wu", "styles": ["aggro", "control"], "tiers": ["core"]}
        self.assertEqual(sid, sample.sample_id("abc", same, 20, ""))
        self.assertNotEqual(sid, sample.sample_id("abc", filters, 21, ""))
        self.assertNotEqual(sid, sample.sample_id("abc", filters, 20, "x"))
        self.assertNotEqual(sid, sample.sample_id("abd", filters, 20, ""))
        self.assertNotEqual(sid, sample.sample_id("abc", {**filters, "tiers": None}, 20, ""))

    def test_save_and_load(self):
        filters = sample.normalise_filters(tiers=["core"])
        chosen = sample.choose(one_per_bucket(), 20, **filters)
        made = {"id": sample.sample_id("f" * 64, filters, 20, ""), "format": "commander", "catalogue_sha": "f" * 64,
                "filters": filters, "size": 20, "seed": "", "decks": [d["id"] for d in chosen]}
        self.assertEqual(len(made["decks"]), 20)
        path = sample.save_sample("commander", made)
        self.assertEqual(path.parent, gauntlet.DATA / "samples")
        self.assertNotIn(":", path.name)
        self.assertEqual(sample.load_sample(made["id"]), made)
        self.assertEqual(list(path.parent.iterdir()), [path])       # no temporary file left behind

    def test_load_answers_none(self):
        self.assertIsNone(sample.load_sample("sample:000000000000"))
        self.assertIsNone(sample.load_sample("../../etc/passwd"))
        self.assertIsNone(sample.load_sample(None))
        folder = gauntlet.DATA / "samples"
        folder.mkdir(parents=True)
        (folder / "sample-0123456789ab.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(sample.load_sample("sample:0123456789ab"))

    def test_save_refuses(self):
        with self.assertRaises(ValueError):
            sample.save_sample("modern", {"id": "sample:0123456789ab", "decks": []})
        with self.assertRaises(ValueError):
            sample.save_sample("commander", {"id": "nope", "decks": []})


if __name__ == "__main__":
    unittest.main()
