"""What a Commander deck can answer (E9-S35, decklab/lib/stats/answers.py): each kind its interaction can
hit, targeted or mass, by speed, from Scryfall's oracle tags; "not checked" for a kind whose tag is missing
and a reason when there's no tag file; and deck_stats' "answers" (None for 60-card decks).

The tag trees are made up here with the real slugs (answers.TAGS_CHECKED records when those were compared
with the real oracle_tags file); the cards are trimmed dicts. No card data, network or database.
Run: python scripts/test_fixtures.py decklab.tests.test_stats_answers
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, decks, stats
from decklab.lib.stats import answers
from decklab.lib.stats import commander as stats_commander
from decklab.lib.stats.cardtext import Entry

FIXTURES = Path(__file__).parent / "fixtures"

# name: (type line, keywords, faces' type lines or None)
CARDS = {
    "Swords to Plowshares": ("Instant", [], None),
    "Wrath of God": ("Sorcery", [], None),
    "Beast Within": ("Instant", [], None),
    "Naturalize": ("Instant", [], None),
    "Cyclonic Rift": ("Instant", ["Overload"], None),
    "Vandalblast": ("Sorcery", ["Overload"], None),
    "Stone Rain": ("Sorcery", [], None),
    "Scavenging Ooze": ("Creature — Ooze", [], None),
    "Bojuka Bog": ("Land", [], None),
    "Rest in Peace": ("Enchantment", [], None),
    "Counterspell": ("Instant", [], None),
    "Lavinia, Azorius Renegade": ("Legendary Creature — Human Soldier", [], None),
    "Grave Pact": ("Enchantment", [], None),
    "Bonecrusher Giant // Stomp": ("Creature — Giant", [], ["Creature — Giant", "Instant — Adventure"]),
    "Brazen Borrower // Petty Theft": ("Creature — Faerie Rogue", ["Flash", "Flying"],
                                       ["Creature — Faerie Rogue", "Instant — Adventure"]),
    "Grizzly Bears": ("Creature — Bear", [], None),
}


def oid(name):
    return "oid-" + name.split(" //")[0].lower().replace(" ", "-").replace(",", "")


def card(name):
    type_line, keywords, faces = CARDS[name]
    found = {"name": name, "oracle_id": oid(name), "type_line": type_line, "keywords": keywords}
    if faces:
        found["faces"] = [{"type_line": line} for line in faces]
    return found


def entries(*names):
    return [Entry(1, name, "Deck", card(name)) for name in names]


# slug: (child slugs, tagged card names)
TREE = {
    "removal": (["removal-creature", "removal-artifact", "removal-enchantment", "removal-planeswalker",
                 "removal-land", "spot-removal", "multi-removal", "sweeper"], []),
    "removal-creature": (["removal-nonland", "removal-permanent"],
                         ["Swords to Plowshares", "Wrath of God", "Grave Pact", "Bonecrusher Giant // Stomp"]),
    "removal-artifact": (["removal-nonland", "removal-permanent", "disenchant-naturalize"], ["Vandalblast"]),
    "removal-enchantment": (["removal-nonland", "removal-permanent", "disenchant-naturalize"], []),
    "removal-planeswalker": (["removal-nonland", "removal-permanent"], []),
    "disenchant-naturalize": ([], ["Naturalize"]),
    "removal-nonland": ([], ["Cyclonic Rift"]),
    "removal-permanent": ([], ["Beast Within"]),
    "removal-land": ([], ["Stone Rain"]),
    "spot-removal": ([], ["Swords to Plowshares", "Beast Within", "Naturalize", "Cyclonic Rift", "Vandalblast",
                          "Stone Rain", "Bonecrusher Giant // Stomp"]),
    "multi-removal": ([], []),
    "sweeper": (["sweeper-one-sided"], ["Wrath of God"]),
    "sweeper-one-sided": ([], ["Cyclonic Rift", "Vandalblast"]),
    "hate-graveyard": (["sweeper-graveyard", "graveyard-seal"], ["Scavenging Ooze"]),
    "sweeper-graveyard": ([], ["Bojuka Bog", "Rest in Peace"]),
    "graveyard-seal": ([], ["Rest in Peace"]),
    "counterspell": (["counterspell-sweeper", "counterspell-automatic"], ["Counterspell"]),
    "counterspell-sweeper": ([], []),
    "counterspell-automatic": ([], ["Lavinia, Azorius Renegade"]),
}

EVERYTHING = tuple(name for name in CARDS if name != "Grizzly Bears")


def write_tags(folder, tree, name="tags.jsonl"):
    path = Path(folder) / name
    with path.open("w", encoding="utf-8") as out:
        for slug, (children, tagged) in tree.items():
            out.write(json.dumps({"object": "tag", "id": "id-" + slug, "slug": slug, "type": "oracle",
                                  "child_ids": ["id-" + child for child in children],
                                  "taggings": [{"oracle_id": oid(name)} for name in tagged]}) + "\n")
    return path


def without(*slugs):
    return {slug: value for slug, value in TREE.items() if slug not in slugs}


def names(group):
    return [c["name"] for c in group["cards"]]


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.folder = self.enterContext(tempfile.TemporaryDirectory())
        self.addCleanup(cards._tag_cache.clear)

    def answer(self, tree=TREE, deck=EVERYTHING):
        return answers.answers(entries(*deck), write_tags(self.folder, tree), "2026-11-01")

    def kind(self, found, key):
        return next(k for k in found["kinds"] if k["kind"] == key)

    def test_each_kind_lists_its_cards_split_targeted_and_mass(self):
        found = self.answer()
        self.assertTrue(found["checked"])
        self.assertEqual(found["tags_date"], "2026-11-01")
        self.assertEqual(found["tags_checked"], answers.TAGS_CHECKED)
        self.assertEqual([k["kind"] for k in found["kinds"]],
                         ["creature", "artifact", "enchantment", "planeswalker", "nonland", "graveyard", "stack"])
        creature = self.kind(found, "creature")
        # Removal of any nonland permanent or any permanent is below removal-creature, so it counts here too.
        self.assertEqual(names(creature), ["Beast Within", "Bonecrusher Giant // Stomp", "Cyclonic Rift",
                                           "Grave Pact", "Swords to Plowshares", "Wrath of God"])
        self.assertEqual(creature["count"], 6)
        self.assertEqual(names(creature["modes"]["targeted"]), ["Beast Within", "Bonecrusher Giant // Stomp",
                                                                "Cyclonic Rift", "Swords to Plowshares"])
        self.assertEqual(names(creature["modes"]["mass"]), ["Cyclonic Rift", "Wrath of God"])
        self.assertEqual(names(creature["modes"]["unsplit"]), ["Grave Pact"])       # neither tag says
        self.assertTrue(creature["split_checked"])
        self.assertIsNone(creature["split_reason"])
        artifact = self.kind(found, "artifact")
        self.assertEqual(names(artifact), ["Beast Within", "Cyclonic Rift", "Naturalize", "Vandalblast"])
        self.assertEqual(names(artifact["modes"]["mass"]), ["Cyclonic Rift", "Vandalblast"])
        self.assertEqual(names(self.kind(found, "enchantment")), ["Beast Within", "Cyclonic Rift", "Naturalize"])
        self.assertEqual(names(self.kind(found, "planeswalker")), ["Beast Within", "Cyclonic Rift"])
        self.assertEqual(names(self.kind(found, "nonland")), ["Beast Within", "Cyclonic Rift"])

    def test_graveyard_and_stack_mass_is_their_own_tags_and_targeted_the_rest(self):
        found = self.answer()
        graveyard = self.kind(found, "graveyard")
        self.assertEqual(names(graveyard["modes"]["mass"]), ["Bojuka Bog", "Rest in Peace"])
        self.assertEqual(names(graveyard["modes"]["targeted"]), ["Scavenging Ooze"])
        self.assertEqual(graveyard["modes"]["unsplit"]["count"], 0)
        stack = self.kind(found, "stack")
        self.assertEqual(names(stack["modes"]["targeted"]), ["Counterspell"])
        self.assertEqual(names(stack["modes"]["mass"]), ["Lavinia, Azorius Renegade"])

    def test_speed_instants_and_flash_sorceries_and_permanents(self):
        found = self.answer()
        creature = self.kind(found, "creature")["speeds"]
        # An adventure whose spell is an instant counts as instant speed.
        self.assertEqual(names(creature["instant"]), ["Beast Within", "Bonecrusher Giant // Stomp",
                                                      "Cyclonic Rift", "Swords to Plowshares"])
        self.assertEqual(names(creature["sorcery"]), ["Wrath of God"])
        self.assertEqual(names(creature["permanent"]), ["Grave Pact"])
        self.assertEqual(self.kind(found, "graveyard")["speeds"]["permanent"]["count"], 3)
        self.assertEqual(answers.speed(card("Brazen Borrower // Petty Theft")), "instant")
        self.assertEqual(answers.speed(card("Lavinia, Azorius Renegade")), "permanent")
        self.assertEqual(answers.speed(card("Bojuka Bog")), "permanent")
        self.assertEqual([s["speed"] for s in found["speeds"]], ["instant", "sorcery", "permanent"])
        self.assertEqual([m["mode"] for m in found["modes"]], ["targeted", "mass", "unsplit"])

    def test_removal_hitting_no_kind_is_other(self):
        found = self.answer()
        self.assertEqual(found["other"], {"checked": True, "count": 1, "cards": [{"name": "Stone Rain", "qty": 1}]})
        self.assertEqual(found["gaps"], [])
        self.assertEqual(found["unchecked"], [])

    def test_gaps_name_the_checked_kinds_with_no_card(self):
        found = self.answer(deck=("Swords to Plowshares", "Grizzly Bears"))
        self.assertEqual(found["gaps"], ["Artifacts", "Enchantments", "Planeswalkers", "Any nonland permanent",
                                         "Graveyards", "Spells on the stack"])
        artifact = self.kind(found, "artifact")
        self.assertEqual((artifact["checked"], artifact["count"]), (True, 0))

    def test_a_kind_whose_tag_is_missing_is_not_checked_never_zero(self):
        found = self.answer(without("hate-graveyard", "sweeper-graveyard", "graveyard-seal"))
        graveyard = self.kind(found, "graveyard")
        self.assertFalse(graveyard["checked"])
        self.assertNotIn("count", graveyard)
        self.assertIn("hate-graveyard", graveyard["reason"])
        self.assertIn("wasn't checked", graveyard["reason"])
        self.assertEqual(found["unchecked"], ["Graveyards"])
        self.assertNotIn("Graveyards", found["gaps"])
        self.assertTrue(self.kind(found, "creature")["checked"])          # the others still count
        self.assertEqual(self.kind(found, "stack")["count"], 2)

    def test_a_missing_permanent_kind_leaves_other_unworked(self):
        tree = without("removal-artifact")
        tree["removal"] = ([c for c in TREE["removal"][0] if c != "removal-artifact"], [])
        found = self.answer(tree)
        self.assertFalse(self.kind(found, "artifact")["checked"])
        self.assertEqual(found["other"], {"checked": False, "count": 0, "cards": []})

    def test_a_missing_split_tag_leaves_the_family_not_split(self):
        found = self.answer(without("sweeper", "sweeper-one-sided"))
        creature = self.kind(found, "creature")
        self.assertTrue(creature["checked"])
        self.assertFalse(creature["split_checked"])
        self.assertIn("sweeper", creature["split_reason"])
        self.assertEqual(creature["modes"]["unsplit"]["count"], creature["count"])
        self.assertEqual(creature["modes"]["mass"]["count"], 0)
        self.assertTrue(self.kind(found, "stack")["split_checked"])      # its own family still splits

    def test_no_tag_file_says_why(self):
        found = answers.answers(entries(*EVERYTHING), Path(self.folder) / "missing.jsonl", None)
        self.assertFalse(found["checked"])
        self.assertIn("couldn't be read", found["reason"])
        self.assertIsNone(found["tags_date"])
        bad = Path(self.folder) / "bad.jsonl"
        bad.write_text("not json\n", encoding="utf-8")
        self.assertFalse(answers.answers(entries(*EVERYTHING), bad, None)["checked"])

    def test_the_result_is_json(self):
        json.dumps(self.answer())

    def test_every_tag_it_reads_is_named_once(self):
        slugs = answers.all_tags()
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(set(slugs), set(TREE) - {"disenchant-naturalize", "removal-land", "sweeper-one-sided"})




class DeckStatsTests(unittest.TestCase):
    """deck_stats' "answers": a Commander deck gets it, a 60-card deck None."""

    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp())
        index = cards.build_index(FIXTURES / "stats_cards.jsonl", FIXTURES / "stats_tags.jsonl",
                                  {"default_cards": "2026-09-28"}, log=lambda *a: None)
        cards.write_index(index, cls.folder / "index.json.gz")
        cards.load(cls.folder / "index.json.gz")
        cls.patches = [mock.patch.object(stats_commander, "TAG_FILE", FIXTURES / "stats_tags.jsonl"),
                       mock.patch.object(stats_commander, "COMBO_FILE", FIXTURES / "stats_combos.json"),
                       mock.patch.object(stats_commander, "OFFICIAL_FILE", FIXTURES / "stats_official_lists.json")]
        for patch in cls.patches:
            patch.start()

    @classmethod
    def tearDownClass(cls):
        for patch in cls.patches:
            patch.stop()
        cards._index = None
        cards._tag_cache.clear()
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_a_sixty_card_deck_has_none(self):
        result = stats.deck_stats(decks.parse_decklist("Deck\n4 Grizzly Bears\n56 Forest\n"), "constructed")
        self.assertIn("answers", result)
        self.assertIsNone(result["answers"])

    def test_a_commander_deck_has_them_and_the_fixture_tags_lack_most_kinds(self):
        result = stats.deck_stats(decks.parse_decklist("Commander\n1 Grizzly Bears\n\nDeck\n99 Forest\n"),
                                  "commander")
        found = result["answers"]
        self.assertTrue(found["checked"])
        self.assertEqual(found["tags_date"], result["commander"]["bracket"]["data"]["tags_date"])
        by_kind = {k["kind"]: k for k in found["kinds"]}
        # stats_tags.jsonl has counterspell (no cards) but none of the removal-<kind> or graveyard tags.
        self.assertFalse(by_kind["creature"]["checked"])
        self.assertFalse(by_kind["graveyard"]["checked"])
        self.assertTrue(by_kind["stack"]["checked"])
        self.assertEqual(found["gaps"], ["Spells on the stack"])
        self.assertFalse(by_kind["stack"]["split_checked"])       # no counterspell-sweeper tag in it either
        json.dumps(result)

    def test_no_tag_file_gives_a_reason_not_zeroes(self):
        with mock.patch.object(stats_commander, "TAG_FILE", self.folder / "no-tags.jsonl"):
            found = stats.deck_stats(decks.parse_decklist("Commander\n1 Grizzly Bears\n\nDeck\n99 Forest\n"),
                                     "commander")["answers"]
        self.assertEqual(set(found), {"checked", "reason", "tags_date"})
        self.assertFalse(found["checked"])


if __name__ == "__main__":
    unittest.main()
