"""The Stats tab's "What it can answer" panel (E9-S35, deck-answers.js) under Node: each kind with its cards,
targeted and mass and by speed; "Not checked" for a kind whose tag was missing, never 0; the reason when there
was no tag file; and no panel for a 60-card deck (stats.answers null).

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js; nothing is sent to a server.
"""
import json
import subprocess
import unittest
from pathlib import Path

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

FIXTURE = """
  const group = (...names) => ({count: names.length, cards: names.map((name) => ({name, qty: 1}))});
  const empty = group();
  const kind = (key, label, extra = {}) => Object.assign({kind: key, label, family: 'permanent', tags: ['t'],
    checked: true, count: 0, cards: [], split_checked: true, split_reason: null,
    modes: {targeted: empty, mass: empty, unsplit: empty},
    speeds: {instant: empty, sorcery: empty, permanent: empty}}, extra);
  const found = (kinds, extra = {}) => Object.assign({checked: true, tags_date: '2026-11-01', tags_checked: '2026-11-12',
    kinds, gaps: kinds.filter((k) => k.checked && !k.count).map((k) => k.label),
    unchecked: kinds.filter((k) => !k.checked).map((k) => k.label), other: {checked: true, count: 0, cards: []},
    speeds: [{speed: 'instant', label: 'Instant speed', about: ''}, {speed: 'sorcery', label: 'Sorcery speed', about: ''},
      {speed: 'permanent', label: 'On a permanent', about: ''}],
    modes: [{mode: 'targeted', label: 'Targeted'}, {mode: 'mass', label: 'Mass'}, {mode: 'unsplit', label: 'Not split'}]},
    extra);
  const creatures = kind('creature', 'Creatures', {count: 3, cards: group('Swords', 'Wrath', 'Pact').cards,
    modes: {targeted: group('Swords'), mass: group('Wrath'), unsplit: group('Pact')},
    speeds: {instant: group('Swords'), sorcery: group('Wrath'), permanent: group('Pact')}});
  const rowText = (panel, label) => [...panel.querySelector('tbody').querySelectorAll('tr')].find((tr) =>
    tr.querySelector('th').textContent === label);
  const cells = (row) => [...row.querySelectorAll('td')].map((td) => td.textContent);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AnswersUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_each_kind_with_targeted_mass_and_speed(self):
        self.run_js("""
          const panel = answersPanel(found([creatures, kind('artifact', 'Artifacts')]));
          assert.equal(panel.querySelector('h3').textContent, 'What it can answer');
          const heads = [...panel.querySelector('thead').querySelectorAll('th')].map((th) => th.textContent);
          assert.deepEqual(heads, ['Kind', 'Cards', 'Targeted', 'Mass', 'Instant speed', 'Sorcery speed', 'On a permanent']);
          assert.deepEqual(cells(rowText(panel, 'Creatures')), ['3', '1', '1', '1', '1', '1']);
          assert.deepEqual(cells(rowText(panel, 'Artifacts')), ['0', '0', '0', '0', '0', '0']);
          const fold = panel.querySelector('.answer-kind');
          assert.equal(fold.querySelector('summary').textContent, 'Creatures: 3');
          const text = fold.textContent;
          for (const words of ['Targeted: 1', 'Mass: 1', 'Not split: 1', 'Instant speed: 1', 'Sorcery speed: 1',
            'On a permanent: 1', 'Swords', 'Wrath', 'Pact']) assert(text.includes(words), words + ' in ' + text);
          // A kind with no card gets no fold, but the gap is named.
          assert.equal(panel.querySelectorAll('.answer-kind').length, 1);
          assert.equal(panel.querySelector('.answers-gaps').textContent, 'No answer to: Artifacts.');
          assert(panel.textContent.includes("Scryfall's oracle tags of 2026-11-01"), panel.textContent);
        """)

    def test_a_kind_not_checked_never_shows_zero(self):
        self.run_js("""
          const unread = kind('graveyard', 'Graveyards', {checked: false, reason: 'No “hate-graveyard” tag.'});
          delete unread.count;
          const panel = answersPanel(found([creatures, unread]));
          assert.deepEqual(cells(rowText(panel, 'Graveyards')), Array(6).fill('Not checked'));
          assert(panel.textContent.includes('Graveyards: not checked. No “hate-graveyard” tag.'), panel.textContent);
          assert.equal(panel.querySelector('.answers-gaps'), null);
          assert(!panel.textContent.includes('undefined') && !panel.textContent.includes('NaN'));
        """)

    def test_unsplit_family_and_other_removal(self):
        self.run_js("""
          const unsplit = kind('creature', 'Creatures', {count: 1, cards: group('Pact').cards, split_checked: false,
            split_reason: 'No sweeper tag.', modes: {targeted: empty, mass: empty, unsplit: group('Pact')}});
          const panel = answersPanel(found([unsplit], {other: {checked: true, count: 1, cards: group('Stone Rain').cards}}));
          assert.deepEqual(cells(rowText(panel, 'Creatures')).slice(0, 3), ['1', 'Not split', 'Not split']);
          assert(panel.textContent.includes('No sweeper tag.'));
          const folds = [...panel.querySelectorAll('.answer-kind')];
          assert.equal(folds[1].querySelector('summary').textContent, 'Other removal: 1');
          assert(folds[1].textContent.includes('Stone Rain'));
        """)

    def test_no_tag_file_says_why_and_a_sixty_card_deck_gets_nothing(self):
        self.run_js("""
          const panel = answersPanel({checked: false, reason: "Scryfall's oracle tags couldn't be read (gone).", tags_date: null});
          assert.equal(panel.querySelector('.note').textContent, "Scryfall's oracle tags couldn't be read (gone).");
          assert.equal(panel.querySelector('table'), null);
          assert.equal(answersPanel(null), null);
          assert.equal(answersPanel(undefined), null);
        """)

    def test_the_pool_pointer_shows_only_to_inventory_readers(self):
        self.run_js("""
          const words = 'Free cards by role';
          assert(answersPanel(found([creatures]), {owned: {}}).textContent.includes(words));
          assert(!answersPanel(found([creatures]), {owned: null}).textContent.includes(words));
          assert(!answersPanel(found([creatures])).textContent.includes(words));
        """)

    def test_the_stats_tab_draws_it_after_types_and_roles(self):
        source = (Path(WEB) / "stats.js").read_text(encoding="utf-8")
        self.assertIn("compositionPanel(st, data),\n    st.answers ? answersPanel(st.answers, data) : null,", source)


if __name__ == "__main__":
    unittest.main()
