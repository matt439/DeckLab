"""Separate named triples, exact completed recipes and no counted bracket/early inference."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import cards, combos, decks, stats
from decklab.lib.stats import commander
from decklab.tests.test_combos import ComboTestCase, use, result, variant
from decklab.tests.test_commander_readiness import FixtureStats
from decklab.tests import test_commander_print_ui as print_ui
from decklab.tests.test_workspace_ui import NODE


def export():
    win, mana = [result("Win the game", "S")], [result("Infinite colored mana", "S")]
    return {"timestamp": "2026-11-11T00:00:00+00:00", "version": "fixture", "variants": [
        variant("pair", [use(1, "Alpha"), use(2, "Beta")], mana),
        variant("spare", [use(1, "Alpha"), use(2, "Beta"), use(3, "Spare")], mana),
        variant("payoff", [use(1, "Alpha"), use(2, "Beta"), use(3, "Payoff")], win),
        variant("leader", [use(7, "Leader", zones=("C",)), use(8, "Helper"), use(9, "Other")], win),
        variant("template", [use(1, "Alpha"), use(2, "Beta"), use(4, "X")], win, requires=[{}]),
        variant("duplicate", [use(1, "Alpha"), use(1, "Alpha"), use(4, "X")], win),
        variant("copies", [use(1, "Alpha", quantity=2), use(2, "Beta"), use(4, "X")], win),
        variant("banned", [use(1, "Alpha"), use(2, "Beta"), use(4, "X")], win, commander=False),
    ]}


class ThreeMatchingTests(ComboTestCase):
    def lists(self, source=None):
        self.write_export(source or export())
        combos.reduce_export(log=self.log.append)
        combos.reduce_export(log=self.log.append, pieces=3)

    def test_keeps_only_distinct_complete_named_recipes_and_suppresses_spare_piece(self):
        source = export()
        before = copy.deepcopy(source)
        self.lists(source)
        self.assertEqual([combo["id"] for combo in combos.load(pieces=3)["combos"]], ["spare", "payoff", "leader"])
        found = combos.find_three([], ["oracle-1", "oracle-2", "oracle-3"])
        self.assertEqual([combo["id"] for combo in found["matches"]], ["payoff"])
        self.assertEqual(combos.find_three([], ["oracle-1", "oracle-2"])["matches"], [])
        self.assertEqual(source, before)
        self.assertEqual([combo["id"] for combo in combos.find([], ["oracle-1", "oracle-2"])["matches"]], ["pair"])

    def test_commander_required_piece_and_no_three_card_floor_or_near_search(self):
        self.lists()
        self.assertEqual(combos.find_three([], ["oracle-7", "oracle-8", "oracle-9"])["matches"], [])
        found = combos.find_three(["oracle-7"], ["oracle-8", "oracle-9"])["matches"]
        self.assertEqual([combo["id"] for combo in found], ["leader"])
        for cls in combos.CLASSES:
            self.assertEqual(combos.bracket_floor({**found[0], "class": cls, "standalone": True}), 1)
        with self.assertRaisesRegex(ValueError, "two-card"):
            combos.find([], [], near=True, pieces=3)

    def test_missing_corrupt_and_valid_empty_three_card_lists_are_distinct(self):
        self.lists()
        path = combos.three_path()
        before = combos.TWO_CARD_FILE.read_bytes()
        path.unlink()
        with self.assertRaises(combos.ComboListError):
            combos.find_three([], [])
        path.write_text("{}", encoding="utf-8")
        with self.assertRaises(combos.ComboListError):
            combos.find_three([], [])
        self.lists({**export(), "variants": export()["variants"][:1]})
        self.assertEqual(combos.find_three([], ["oracle-1"])["matches"], [])
        self.assertEqual(combos.TWO_CARD_FILE.read_bytes(), before)

    def test_missing_pair_data_cannot_claim_redundant_triples_were_checked(self):
        self.lists()
        combos.TWO_CARD_FILE.unlink()
        with self.assertRaises(combos.ComboListError):
            combos.find_three([], ["oracle-1", "oracle-2", "oracle-3"])

    def test_existing_cached_export_adds_the_separate_file_without_fetching(self):
        self.write_export(export())
        combos.reduce_export(log=self.log.append)
        cards._write_json(combos.META_FILE, {"downloaded_at": combos._now().isoformat(), "format": combos.FORMAT})
        with mock.patch.object(cards, "_download", side_effect=AssertionError("no fetch")):
            self.assertTrue(combos.update(log=self.log.append))
        self.assertTrue(combos.three_path().exists())
        self.assertEqual(combos.load(pieces=3)["version"], "fixture")


class ThreeStatsTests(FixtureStats):
    def test_triples_are_capped_with_total_and_never_change_the_minimum(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "three_card.json"
        names = ["Finneas, Ace Archer", "Llanowar Elves", "Forest"]
        pieces = [{"oracle_id": cards.card(name)["oracle_id"], "name": name, "must_be_commander": i == 0}
                  for i, name in enumerate(names)]
        records = [{"id": str(i), "url": combos.COMBO_URL.format(id=i), "cards": pieces,
                    "class": "mass_land_denial", "standalone": True, "results": ["Mass Land Denial"]} for i in range(31)]
        path.write_text(json.dumps({"format": combos.FORMAT, "timestamp": "2026-11-11T00:00:00+00:00", "version": "fixture", "combos": records}), encoding="utf-8")
        listed = decks.parse_decklist("Commander\n1 Finneas, Ace Archer\n\nDeck\n1 Llanowar Elves\n98 Forest")
        before = stats.deck_stats(listed, "commander")["commander"]
        with mock.patch.object(commander, "THREE_COMBO_FILE", path):
            after = stats.deck_stats(listed, "commander")["commander"]
            unknown = stats.deck_stats(decks.parse_decklist("Commander\n1 Finneas, Ace Archer\nDeck\n1 Unknown Fictional Card\n98 Forest"), "commander")["commander"]
        self.assertEqual(after["bracket"], before["bracket"])
        self.assertEqual((after["three_card_combos"]["total"], len(after["three_card_combos"]["matches"])), (31, 25))
        self.assertTrue(all(match["floor"] == 1 and match["raises_floor"] is False for match in after["three_card_combos"]["matches"]))
        self.assertFalse(unknown["three_card_combos"]["checked"])
        self.assertFalse(before["three_card_combos"]["checked"])


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ThreeUiTests(FixtureStats):
    run_js = print_ui.CommanderPrintUiTests.run_js

    def test_overview_stats_and_print_are_separate_counted_and_read_only(self):
        full = stats.deck_stats(decks.parse_decklist("Commander\n1 Finneas, Ace Archer\nDeck\n99 Forest"), "commander")
        self.run_js("const data = readinessPage(); data.stats = " + json.dumps(full) + ";" + """
          data.stats.commander.three_card_combos = {checked:true,total:31,list_date:'2026-11-11T00:00:00Z',
            matches:[{names:['Elf','Bolt','Wurm'],results:['Win the game'],class:'win',standalone:true,floor:4,raises_floor:true,url:'https://example.com/combo'}]};
          const before = JSON.stringify(data), overview = showReadiness(data), statsPanel3 = commanderPanel(data.stats,data.summary,data);
          for (const part of [overview,statsPanel3]) {
            const triples = part.querySelector('.commander-three-combos');
            assert(triples.textContent.includes('Three-card combos'));
            assert(triples.textContent.includes('31 complete three-card combos'));
            assert(triples.textContent.includes('never raise the minimum bracket'));
            assert(triples.textContent.includes('Elf + Bolt + Wurm'));
            assert(!triples.textContent.includes('Counts as mass land denial'));
            assert(!triples.textContent.includes('None in Brackets 1-2'));
          }
          fetched = 0;
          const sheet = printSheet(data), triples = sheet.querySelector('.commander-three-combos');
          assert(triples.textContent.includes('Elf + Bolt + Wurm'));
          assert.equal(triples.querySelectorAll('a').length,0);
          assert.equal(triples.querySelectorAll('button').length,0);
          assert.equal(fetched,0); assert.equal(JSON.stringify(data),before);
          delete data.stats.commander.three_card_combos;
          assert(showReadiness(data).textContent.includes("Three-card combos weren't checked"));
          assert(COMMANDER_CHECK_LIMITS.includes('four or more cards'));
        """)
