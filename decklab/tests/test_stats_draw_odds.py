"""The Stats tab's "Chance to draw" panel (E3-S24 and E3-S54) over the real page scripts and DOM double.

No network, server, database or card data is needed.
"""
import json
from itertools import combinations
from math import comb
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


def at_least_one(size, hits, seen):
    return 1 - comb(size - hits, seen) / comb(size, seen)


FIXTURE = """
  const land = {type_line: 'Basic Land — Forest', cmc: 0};
  const elf = {type_line: 'Creature — Elf Druid', cmc: 1};
  const bolt = {type_line: 'Instant', cmc: 1};
  const deck = (kind, id, sections) => ({summary: {id, kind}, version: 'target', versions: ['target'], sections});
  const casual = deck('casual', 'casual/elves', {
    Deck: [{qty: 4, name: 'Llanowar Elves', card: elf}, {qty: 2, name: 'Shock', card: bolt},
      {qty: 2, name: 'Shock', card: bolt, set: 'm21'}, {qty: 24, name: 'Forest', card: land},
      {qty: 28, name: 'Grizzly Bears', card: {type_line: 'Creature — Bear', cmc: 2}}],
    Sideboard: [{qty: 15, name: 'Naturalize', card: bolt}]});
  const tick = (panel, name) => {
    const box = panel.querySelectorAll('input').find((i) => i.getAttribute('type') === 'checkbox' && i.value === name);
    box.checked = true; box.fire('change');
  };
  const chance = (panel) => panel.querySelector('.odds-result').querySelector('.value').textContent;
  const button = (panel, text) => panel.querySelectorAll('button').find((b) => b.textContent === text);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DrawOddsTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_chance_is_the_exact_hypergeometric_one(self):
        expected = [at_least_one(60, 4, n) for n in (7, 9, 10, 60)] + [at_least_one(99, 1, 13)]
        self.run_js(f"""
          const got = [chanceOfAtLeastOne(60, 4, 7), chanceOfAtLeastOne(60, 4, 9), chanceOfAtLeastOne(60, 4, 10),
            chanceOfAtLeastOne(60, 4, 60), chanceOfAtLeastOne(99, 1, 13)];
          const want = {json.dumps(expected)};
          got.forEach((g, i) => assert(Math.abs(g - want[i]) < 1e-12, g + ' vs ' + want[i]));
          assert.equal(chanceOfAtLeastOne(60, 0, 10), 0);
          assert.equal(chanceOfAtLeastOne(60, 57, 4), 1);
          // Seven in the opening hand, then a draw a turn, the first skipped on the play.
          same([cardsSeenBy(1, true, 60), cardsSeenBy(1, false, 60), cardsSeenBy(3, true, 60), cardsSeenBy(3, false, 60)],
            [7, 8, 9, 10]);
          assert.equal(cardsSeenBy(20, false, 20), 20);
        """)

    def test_chance_of_both_matches_every_draw_size_from_a_small_library(self):
        library = "AABCCCC"
        expected = []
        for seen in range(len(library) + 1):
            draws = list(combinations(library, seen))
            expected.append(sum("A" in draw and "B" in draw for draw in draws) / len(draws))
        self.run_js(f"""
          const want = {json.dumps(expected)};
          want.forEach((value, n) => {{
            const got = chanceOfBoth(7, 2, 1, n);
            assert(Math.abs(got - value) < 1e-12, got + ' vs ' + value);
          }});
          assert(Math.abs(chanceOfBoth(99, 1, 1, 7) - (7 * 6) / (99 * 98)) < 1e-12);
          assert.equal(chanceOfBoth(99, 0, 1, 7), 0);
        """)

    def test_a_card_and_a_group_by_a_chosen_turn_on_the_play_or_draw(self):
        one = f"{at_least_one(60, 4, 9) * 100:.1f}%"
        draw = f"{at_least_one(60, 4, 10) * 100:.1f}%"
        group = f"{at_least_one(60, 8, 10) * 100:.1f}%"
        turn5 = f"{at_least_one(60, 8, 12) * 100:.1f}%"
        lands = f"{at_least_one(60, 24, 12) * 100:.1f}%"
        self.run_js(f"""
          const panel = drawOddsPanel(casual);
          assert(panel.querySelector('.odds-result').textContent.includes('Tick a card'));
          // Shock's two printings are one line of 4; the sideboard isn't drawn from.
          const names = panel.querySelector('.odds-cards').children.map((li) => li.textContent);
          same(names, ['4Llanowar Elves', '4Shock', '28Grizzly Bears', '24Forest']);
          tick(panel, 'Llanowar Elves');
          assert.equal(chance(panel), {json.dumps(one)});
          assert(panel.textContent.includes('the 4 copies of Llanowar Elves in your first 9 cards'));
          assert(panel.textContent.includes("Mulligans and extra card draw aren't counted"));
          button(panel, 'On the draw').click();
          assert.equal(chance(panel), {json.dumps(draw)});
          tick(panel, 'Shock');
          assert.equal(chance(panel), {json.dumps(group)});
          assert(panel.textContent.includes('the 2 cards ticked (8 copies in all)'));
          assert(panel.textContent.includes('Both cards means seeing Llanowar Elves and Shock'));
          assert.equal(panel.querySelector('.odds-result').querySelectorAll('.value')[1].textContent,
            pct(chanceOfBoth(60, 4, 4, 10)));
          const turn = panel.querySelector('.odds-turn').querySelector('input');
          turn.value = '5'; turn.fire('input');
          assert.equal(chance(panel), {json.dumps(turn5)});
          assert.equal(panel.querySelector('.odds-result').querySelectorAll('.value')[1].textContent,
            pct(chanceOfBoth(60, 4, 4, 12)));
          turn.value = '99'; turn.fire('input'); turn.fire('change');
          assert.equal(turn.value, '5');
          assert.equal(chance(panel), {json.dumps(turn5)});
          const current = panel.querySelector('.odds-table').querySelectorAll('td')[4];
          assert.equal(current.getAttribute('class'), 'is-current');
          tick(panel, 'Grizzly Bears');
          assert(!panel.textContent.includes('Both cards by turn'));
          button(panel, 'All lands').click();
          assert.equal(chance(panel), {json.dumps(lands)});
          button(panel, 'Clear').click();
          assert(panel.querySelector('.odds-result').textContent.includes('Tick a card'));
          assert(panel.textContent.includes('It ignores mulligans'));
        """)

    def test_the_pair_uses_the_displayed_list_and_excludes_non_library_cards(self):
        self.run_js("""
          const build = (version, copies) => ({...deck('commander', 'commander/elves', {
            Commander: [{qty: 1, name: 'Commander card', card: elf}],
            Companion: [{qty: 1, name: 'Companion card', card: elf}],
            Sideboard: [{qty: 1, name: 'Sideboard card', card: elf}],
            Deck: [{qty: 1, name: 'Sol Ring', card: bolt}, {qty: copies, name: 'Forest', card: land},
              {qty: 98 - copies, name: 'Grizzly Bears', card: elf}]}), version, versions: ['target', 'current']});
          const results = [['target', 2], ['current', 1]].map(([version, forest]) => {
            const panel = drawOddsPanel(build(version, forest));
            const nameList = panel.querySelector('.odds-cards').textContent;
            assert(!/Commander card|Companion card|Sideboard card/.test(nameList));
            button(panel, 'On the play').click();
            const turn = panel.querySelector('.odds-turn').querySelector('input');
            turn.value = '1'; turn.fire('input');
            tick(panel, 'Sol Ring');
            tick(panel, 'Forest');
            assert(panel.textContent.includes('in your first 7 cards'));
            return panel.querySelector('.odds-result').querySelectorAll('.value')[1].textContent;
          });
          same(results, ['0.8%', '0.4%']);
        """)

    def test_commander_draws_from_the_99_and_defaults_to_the_draw(self):
        expected = f"{at_least_one(99, 1, 10) * 100:.1f}%"
        self.run_js(f"""
          const k = deck('commander', 'commander/elves', {{
            Commander: [{{qty: 1, name: 'Lathril, Blade of the Elves', card: elf}}],
            Deck: [{{qty: 1, name: 'Sol Ring', card: {{type_line: 'Artifact', cmc: 1}}}},
              {{qty: 98, name: 'Forest', card: land}}]}});
          const panel = drawOddsPanel(k);
          assert(!panel.textContent.includes('Lathril'));
          assert.equal(button(panel, 'On the draw').getAttribute('aria-pressed'), 'true');
          tick(panel, 'Sol Ring');
          assert.equal(chance(panel), {json.dumps(expected)});
          assert(panel.textContent.includes('from 99 cards'));
          assert(panel.textContent.includes('command zone'));
        """)

    def test_no_panel_for_a_beginner_box_half_or_a_tiny_list(self):
        self.run_js("""
          assert.equal(drawOddsPanel(deck('product', BOX_PREFIX + 'cats', casual.sections)), null);
          assert.equal(drawOddsPanel(deck('casual', 'casual/tiny', {Deck: [{qty: 6, name: 'Forest', card: land}]})), null);
          assert.equal(drawOddsPanel({summary: {id: 'casual/x'}}), null);
        """)


if __name__ == "__main__":
    unittest.main()
