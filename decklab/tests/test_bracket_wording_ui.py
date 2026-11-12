"""The bracket wording (E9-S38) under Node: the editor's Checks panel bracket box says "No Game Changers" once,
gives the target its own sentence with no nested brackets, and Compare's In brief bracket row carries
"today's lists" in its heading, never appended to a side's label.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js with invented decks; nothing is sent to a
server.
"""
import json
import subprocess
import unittest

from decklab.tests import test_compare_ui as compare_ui
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

BOX = r"""
  const LABEL = 'Bracket 1 or 2 (theme and intent decide)';
  const box = (extra = {}) => bracketBox({minimum: 1, label: LABEL, target: 2, game_changers: [],
    reasons: ['No Game Changers, mass land denial or extra turns.'], ...extra});
  const lines = (node) => node.querySelectorAll('p').map((p) => p.textContent);
  const count = (texts, word) => texts.join(' ').split(word).length - 1;
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class BracketWordingUiTests(unittest.TestCase):
    def run_js(self, scenario, setup=compare_ui.SETUP):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + BOX + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_game_changers_is_said_once(self):
        self.run_js(r"""
          // The server's reason already says it (with or without tag data): the box adds nothing.
          for (const reason of ['No Game Changers, mass land denial or extra turns.', 'No Game Changers.']) {
            const texts = lines(box({reasons: [reason]}));
            assert.equal(count(texts, 'No Game Changers'), 1, texts.join(' | '));
          }
          // A reason that doesn't say it: the box says it, once.
          const texts = lines(box({reasons: ['Holds an extra-turn card: Time Warp']}));
          assert.equal(count(texts, 'No Game Changers'), 1);
          assert(texts.includes('No Game Changers.'));
          // With Game Changers, they're listed and "No Game Changers" never shows.
          const some = lines(box({game_changers: [{name: 'Rhystic Study', qty: 1}], reasons: ['Holds 1 Game Changer.']}));
          assert(some.includes('Game Changers (1): Rhystic Study.'));
          assert.equal(count(some, 'No Game Changers'), 0);
        """)

    def test_the_target_is_its_own_sentence_without_nested_brackets(self):
        self.run_js(r"""
          let first = lines(box())[0];
          assert.equal(first, `The list fits: ${LABEL}. Target: Bracket 2.`);
          assert.equal(first.includes(') ('), false);
          assert.equal(first.includes('(the target'), false);
          // A label without its own brackets, or one ending in a full stop, still reads as one sentence each.
          assert.equal(lines(box({label: 'Bracket 3 or higher', target: 3}))[0],
            'The list fits: Bracket 3 or higher. Target: Bracket 3.');
          assert.equal(lines(box({label: 'Bracket 2 or higher.', target: null}))[0],
            'The list fits: Bracket 2 or higher.');
          assert.equal(lines(box({label: '', target: 4}))[0], 'The list fits: Unknown. Target: Bracket 4.');
        """)

    def test_compares_bracket_row_heading_says_todays_lists(self):
        self.run_js(r"""
          const bracketed = (deck, label) => { deck.stats.commander = {bracket: {label}}; deck.stats_kind = 'commander';
            return deck; };
          const brief = (sides) => compareBrief(sides, ['A', 'B']).querySelector('table').querySelector('tbody')
            .children.map((tr) => [tr.querySelector('th').textContent, ...tr.querySelectorAll('td').map((td) => td.textContent)])
            .find((row) => row[0].startsWith('Bracket'));
          // A revision baseline: the heading carries it, each label stays as the server wrote it.
          const old = bracketed(deckA(), LABEL); old.comparison = {kind: 'revision', revision: 3, date: '2026-11-01'};
          same(brief([bracketed(deckB(), 'Bracket 3 or higher'), old]),
            ["Bracket (today's lists)", 'Bracket 3 or higher', LABEL]);
          // A published precon too.
          const precon = bracketed(deckA(), LABEL); precon.comparison = {kind: 'precon', label: 'Published precon: X'};
          same(brief([precon, bracketed(deckB(), LABEL)])[0], "Bracket (today's lists)");
          // Two saved decks: a plain heading, no "today's lists" anywhere in the row, and no nested brackets.
          const plain = brief([bracketed(deckA(), LABEL), bracketed(deckB(), 'Bracket 2 or higher')]);
          same(plain, ['Bracket', LABEL, 'Bracket 2 or higher']);
          assert.equal(plain.join(' ').includes(') ('), false);
        """)


if __name__ == "__main__":
    unittest.main()
