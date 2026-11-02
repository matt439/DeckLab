"""The gauntlet's slices together: a catalogue built from the fixtures (lib/gauntlet/catalogue.py,
tagged by tags.py), sampled by sample.py, and played as Forge entries by lib/forge/gauntlet.py.
Nothing is fetched and no Forge game is played."""
import shutil
import unittest

from decklab.lib import edhrec
from decklab.lib.forge import gauntlet as forge_gauntlet
from decklab.lib.forge import lists
from decklab.lib.gauntlet import catalogue, sample, tags
from decklab.tests.gauntlet_sources_support import GAUNTLET, GauntletCase, fake_limits
from decklab.tests.test_gauntlet_sources import QUEST, FakeEdhrec, no_commander_page


class Together(GauntletCase):
    def setUp(self):
        super().setUp()
        self.patch(catalogue, "FORGE_ROOT", QUEST)
        self.patch(catalogue, "LIMITS", fake_limits())
        self.patch(edhrec, "get_json", FakeEdhrec())
        self.patch(edhrec, "fetch", no_commander_page)
        shutil.copytree(GAUNTLET / "mtgjson", self.tmp / "mtgjson")
        self.log = []

    def test_catalogue_entries_are_tagged_by_tags(self):
        built = catalogue.build("commander", top=2, log=self.log.append)
        for deck in built["decks"]:
            tagged = tags.tag("commander", deck["cards"], deck["style"]["themes"])
            self.assertEqual(deck["style"], tagged["style"])
            self.assertEqual(deck["identity"], tagged["identity"])
            self.assertIn(deck["style"]["primary"], tags.STYLES)

    def test_a_built_catalogue_samples_and_plays(self):
        for fmt, tiers in (("commander", ["core", "upgraded", "precon"]), ("constructed", None)):
            built = catalogue.build(fmt, top=2, log=self.log.append)
            playable = [d for d in built["decks"] if d["playable"]]
            self.assertTrue(playable, fmt)
            drawn = forge_gauntlet.draw(fmt, size=3, tiers=tiers or sorted({d["tier"] for d in playable}))
            self.assertTrue(drawn["decks"], fmt)
            self.assertEqual(sample.load_sample(drawn["id"]), drawn)
            self.assertEqual(forge_gauntlet.sample(drawn["id"]), drawn)
            by_id = {d["id"]: d for d in built["decks"]}
            for entry in forge_gauntlet.entries(fmt, drawn["decks"]):
                deck = by_id[entry["id"]]
                self.assertEqual(entry["card_sha"], deck["card_sha"])
                self.assertEqual(entry["kind"], deck["kind"])
                self.assertEqual(forge_gauntlet.format_of(entry), fmt)
                again = lists.entry_from_cards(deck["id"], deck["title"], deck["kind"], deck["cards"])
                self.assertEqual(again["card_sha"], deck["card_sha"])
            self.assertEqual(forge_gauntlet.find(drawn["decks"][0])[0], fmt)


if __name__ == "__main__":
    unittest.main()
