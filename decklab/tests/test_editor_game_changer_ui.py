"""The Game Changer chip on a Commander deck's picker rows (E9-S30, editor-cards.js gameChangerChip) under
Node: the finder, EDHREC ideas, My wishlist and Considering rows mark a card Scryfall flags before it's
added, outside the quantity stepper; with the last check's bracket the chip says when one more Game Changer
would put the deck above its Target bracket, and follows the next check; a 60-card deck shows no chip.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js with invented cards; nothing is sent to
a server and EDHREC is never asked.
"""
import json
import subprocess
import unittest

from decklab.tests import test_editor_edhrec_ui as edhrec_ui
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = edhrec_ui.SETUP + r"""
  const study = {name: 'Study Hall', mana_cost: '{2}{U}', type_line: 'Enchantment', cmc: 3, have: {}, default: null,
    game_changer: true};
  const plain = {...alpha, game_changer: false};
  const bracket = (extra = {}) => ({minimum: 1, label: 'Bracket 1', target: 2, game_changers: [], reasons: [],
    with_game_changer: 3, ...extra});
  const chips = (root) => root.querySelectorAll('.chip-gc').map((chip) => chip.textContent);
  const WOULD = (n) => `Game Changer: would put the deck at Bracket ${n}, above its target`;
  function show(ac, cards = [study, plain]) {
    ac.input.value = 's'; ac.query = 's'; ac.items = cards; ac.active = 0; drawOptions(ac);
    return ac.list.querySelectorAll('.ac-option');
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorGameChangerUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_commander_decks_finder_marks_the_card_outside_the_stepper(self):
        self.run_js(r"""
          const mine = commanderEditor();
          const [first, second] = show(mine);
          same(chips(first), ['Game Changer'], 'no check yet: the plain mark');
          same(chips(second), [], 'a card Scryfall does not flag has no chip');
          const chip = first.querySelector('.chip-gc');
          assert(first.querySelector('.ac-side').contains(chip), 'the chip sits with the result facts');
          assert.equal(first.querySelector('.ac-actions').contains(chip), false, 'never inside the quantity stepper');
          assert(chip.getAttribute('class').includes('chip-outline'));
          // A new Commander deck before its first save has it too; a missing flag is never a chip.
          const fresh = commanderEditor({mode: 'new', id: null, kind: undefined, sha256: undefined});
          same(chips(show(fresh, [study, {...alpha}])[0]), ['Game Changer']);
          assert.equal(fresh.list.querySelectorAll('.chip-gc').length, 1);
        """)

    def test_a_sixty_card_deck_shows_no_chip_anywhere(self):
        self.run_js(r"""
          let other = commanderEditor({kind: 'casual', fields: {kind: 'casual'}, check: {bracket: bracket()}});
          show(other);
          assert.equal(other.list.querySelectorAll('.chip-gc').length, 0, 'a saved 60-card deck');
          other = commanderEditor({mode: 'new', id: null, kind: undefined, fields: {kind: 'casual'}});
          show(other);
          assert.equal(other.list.querySelectorAll('.chip-gc').length, 0, 'a new 60-card deck');
          assert.equal(gameChangerChip(study, other), null);
          assert.equal(gameChangerChip(study, null), null);
        """)

    def test_the_last_checks_bracket_says_when_it_would_pass_the_target(self):
        self.run_js(r"""
          const mine = commanderEditor({check: {bracket: bracket()}});
          let [first] = show(mine);
          same(chips(first), [WOULD(3)]);
          assert(first.querySelector('.chip-gc').getAttribute('class').includes('chip-warn'));
          assert(first.querySelector('.chip-gc').getAttribute('title').includes('The Checks panel decides'));
          // The target allows it, or no target is set: only the plain mark.
          for (const b of [bracket({target: 3}), bracket({target: 4}), bracket({target: null})]) {
            editor.check = {bracket: b}; syncGameChangerChips();
            same(chips(mine.list), ['Game Changer']);
          }
          // Already above the target without passing another limit: nothing new to say.
          editor.check = {bracket: bracket({minimum: 3, with_game_changer: 3, game_changers: [{name: 'Other', qty: 1}]})};
          syncGameChangerChips();
          same(chips(mine.list), ['Game Changer']);
          // The fourth Game Changer passes Bracket 3's limit.
          editor.check = {bracket: bracket({minimum: 3, target: 3, with_game_changer: 4,
            game_changers: ['A', 'B', 'C'].map((name) => ({name, qty: 1}))})};
          syncGameChangerChips();
          same(chips(mine.list), [WOULD(4)]);
          // A card the check already counts isn't one more.
          editor.check = {bracket: bracket({minimum: 3, with_game_changer: 3, game_changers: [{name: 'Study Hall', qty: 1}]})};
          syncGameChangerChips();
          same(chips(mine.list), ['Game Changer']);
          assert(mine.list.querySelector('.chip-gc').getAttribute('title').includes('already counts'));
          // An older server's bracket (no with_game_changer) and the Play-now list (the bracket is the Planned list's).
          editor.check = {bracket: {minimum: 1, target: 2, game_changers: []}}; syncGameChangerChips();
          same(chips(mine.list), ['Game Changer']);
          editor.check = {bracket: bracket()}; editor.version = 'owned'; syncGameChangerChips();
          same(chips(mine.list), ['Game Changer']);
        """)

    def test_a_chip_redraw_keeps_the_row_and_its_stepper(self):
        self.run_js(r"""
          const mine = commanderEditor();
          const [first] = show(mine);
          const actions = first.querySelector('.ac-actions'), add = first.querySelector('.ac-add');
          editor.check = {bracket: bracket()}; syncGameChangerChips();
          assert.equal(mine.list.querySelectorAll('.ac-option')[0], first, 'the row is the same node');
          assert.equal(first.querySelector('.ac-actions'), actions);
          assert.equal(first.querySelector('.ac-add'), add);
          same(chips(first), [WOULD(3)], 'one chip, replaced');
          // Adding it: the row says Added and keeps one chip; drawing again never doubles it.
          add.click();
          assert.equal(editor.lists.Deck.some((line) => line.name === 'Study Hall'), true);
          assert.equal(first.querySelectorAll('.chip-gc').length, 1);
          drawOptions(mine); syncGameChangerChips();
          assert.equal(first.querySelectorAll('.chip-gc').length, 1);
          // The deck becomes a 60-card one (a new deck's kind): the chips go.
          editor.kind = 'casual'; editor.fields.kind = 'casual'; syncGameChangerChips();
          assert.equal(mine.list.querySelectorAll('.chip-gc').length, 0);
        """)

    def test_edhrec_ideas_carry_the_chip_after_their_own_marks(self):
        self.run_js(r"""
          answer = ANSWER();
          for (const group of answer.groups) for (const row of group.cards) if (row.name === 'Elvish Mystic') row.card.game_changer = true;
          const mine = commanderEditor({check: {bracket: bracket()}});
          tick(mine); await settle();
          same(names(mine).slice(0, 2), ['Elvish Mystic', 'Pick Your Poison']);
          const [mystic, poison] = mine.list.querySelectorAll('.ac-option');
          const side = mystic.querySelector('.ac-side');
          same(chips(side), [WOULD(3)]);
          assert(side.textContent.includes('64% of decks'), 'its share of decks is still there');
          assert(side.textContent.includes('2 free'));
          same(chips(poison), []);
          assert.equal(writes.length, 0);
        """)

    def test_wishlist_ideas_carry_the_chip(self):
        self.run_js(r"""
          const row = {name: 'Study Hall', set: 'wot', number: '25', status: 'to_buy', aud_each: 9.5, card: {...study}};
          const item = editorWishlistItem(row, true, {rate: 1.5});
          const mine = commanderEditor({check: {bracket: bracket()}});
          const [first] = show(mine, [item]);
          const side = first.querySelector('.ac-side');
          same(chips(side), [WOULD(3)]);
          assert(side.textContent.includes('WOT 25'), 'the wished printing is still there');
          assert.equal(first.querySelector('.ac-actions').contains(side.querySelector('.chip-gc')), false);
        """)

    def test_considering_rows_carry_the_chip_under_the_row(self):
        self.run_js(r"""
          commanderEditor({check: {bracket: bracket(), blocks: []}, sent: {}, tab: 'cards'});
          const lines = [{uid: 'k1', name: 'Study Hall', qty: 1, card: study}, {uid: 'k2', name: 'Alpha', qty: 1, card: plain},
            {uid: 'k3', name: 'Unknown', qty: 1, card: null}];
          editor.considering = lines;
          const rows = lines.map((line) => el('div', {class: 'editor-considering-row', 'data-considering-uid': line.uid},
            el('div', {class: 'card-row'}), el('div', {class: 'editor-considering-actions'})));
          editor.dom.considering = el('section', {}, rows);
          main.append(editor.dom.considering);
          markEditorConsideringRows();
          same(rows.map(chips), [[WOULD(3)], [], []]);
          const holder = rows[0].querySelector('.editor-considering-gc');
          assert.equal(rows[0].querySelector('.editor-considering-actions').contains(holder), false);
          assert.equal(rows[0].children[rows[0].children.length - 1], holder, 'after the card and the stepper, so neither moves');
          // The next check: one chip, in its new words; a 60-card deck has none.
          editor.check = {bracket: bracket({target: 3}), blocks: []};
          markEditorConsideringRows();
          same(rows.map(chips), [['Game Changer'], [], []]);
          assert.equal(rows[0].querySelectorAll('.editor-considering-gc').length, 1);
          editor.kind = 'casual'; editor.fields.kind = 'casual';
          markEditorConsideringRows();
          same(rows.map(chips), [[], [], []]);
        """)
        css = (WEB / "editor.css").read_text(encoding="utf-8")
        self.assertIn(".editor-considering-category, .editor-considering-gc, .editor-considering-row .edit-block "
                      "{ grid-column: 1 / -1; margin: 0; }", css)

    def test_a_check_answer_redraws_the_chips(self):
        source = (WEB / "editor-save.js").read_text(encoding="utf-8")
        check = source[source.index('await apiWrite("/api/deck/check", body)'):]
        self.assertLess(check.index("markRows();"), check.index("syncGameChangerChips(ed);"))
        self.assertLess(check.index("syncGameChangerChips(ed);"), check.index("return answer;"))


if __name__ == "__main__":
    unittest.main()
