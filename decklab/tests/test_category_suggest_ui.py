"""Category proposals and remembered labels use ordinary editor Undo/save and strict sheet scope."""
import unittest

from decklab.tests import test_editor_ui as fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CategorySuggestUiTests(unittest.TestCase):
    run_js = fixture.EditorPageTests.run_js

    def categories_js(self, scenario):
        self.run_js("""
          location.hash = '#/edit?id=casual/gruul';
          edit(); editor.space = 'home';
          editor.lists.Deck[0].card = {...editor.lists.Deck[0].card, roles: ['ramp', 'draw']};
          editor.lists.Deck[1].card = {...editor.lists.Deck[1].card, roles: ['removal', 'board wipe']};
          editor.snap = snapshot(editor); drawEditor();
          // The shared runner stubs changed(); retain the real history/Undo model here.
          changed = options => {editor.dirty = isDirty(); if (!options || options.history !== false) recordHistory(editor);};
          const ed = editor, tick = async () => {for (let n = 0; n < 5; n++) await null;};
          const action = (sheet, text) => sheet.foot.querySelectorAll('button').find(button => button.textContent === text);
          const writes = []; apiWrite = async (...args) => {writes.push(args); throw new Error('Must not save');};
        """ + scenario)

    def test_one_role_per_untagged_line_can_be_unticked_and_applies_as_one_undo_step(self):
        self.categories_js("""
          const original = keepList(ed.lists), sheet = openCategorySuggestions();
          assert(sheet.body.textContent.includes('Board wipe, Counterspell, Removal, Draw, then Ramp'));
          const boxes = sheet.body.querySelectorAll('input'); assert.equal(boxes.length, 2); assert(boxes.every(box => box.checked));
          boxes[1].checked = false; action(sheet, 'Apply selected categories').click();
          assert.equal(ed.lists.Deck[0].category, 'Draw'); assert.equal(ed.lists.Deck[1].category, null);
          assert.equal(ed.history.length, 1); assert.equal(writes.length, 0); assert.equal(undoLast(), true);
          same(keepList(ed.lists), original); assert.equal(ed.history.length, 0);
          ed.lists.Deck[0].category = 'My role'; const again = openCategorySuggestions();
          assert.equal(again.body.querySelectorAll('input').length, 1);
          action(again, 'Apply selected categories').click(); assert.equal(ed.lists.Deck[0].category, 'My role');
          assert.equal(ed.lists.Deck[1].category, 'Board wipe');
        """)

    def test_changed_list_detached_origin_nested_sheet_or_profile_change_never_applies_old_review(self):
        self.categories_js("""
          const sheet = openCategorySuggestions(), apply = action(sheet, 'Apply selected categories');
          const nested = openSheet('Another sheet'); apply.click(); assert.equal(ed.history.length, 0); nested.close();
          state.profile = {id: 'user1'}; apply.click(); assert.equal(ed.history.length, 0); state.profile = {id: 'matt'};
          ed.lists.Deck[0].qty += 1; apply.click(); assert.equal(ed.history.length, 0);
          assert(sheet.body.textContent.includes('list changed')); ed.lists.Deck[0].qty -= 1;
          apply.remove(); apply.click(); assert.equal(ed.history.length, 0);
          sheet.close(); ed.readOnly = true; assert.equal(openCategorySuggestions(), null);
        """)

    def test_remembered_choices_are_read_on_demand_without_replacing_typed_value_and_keep_one_undo(self):
        self.categories_js("""
          const reads = []; let finish;
          api = path => {reads.push(path); return new Promise(resolve => {finish = resolve;});};
          const line = ed.lists.Deck[0], sheet = openCategorySheet(line.uid), input = sheet.body.querySelector('input');
          input.value = 'Typed while loading'; finish({categories: ['Ramp', 'Other label', 'bad#label']}); await tick();
          assert.equal(input.value, 'Typed while loading'); assert.equal(reads.length, 1);
          const query = new URLSearchParams(reads[0].split('?')[1]);
          assert.equal(query.get('name'), line.name); assert.equal(query.get('space'), 'home'); assert.equal(query.get('exclude'), 'casual/gruul');
          same(sheet.body.querySelectorAll('option').map(option => option.value), ['Ramp', 'Other label']);
          input.value = 'ramp'; action(sheet, 'Set category').click();
          assert.equal(line.category, 'Ramp'); assert.equal(ed.history.length, 1); assert.equal(writes.length, 0);
        """)

    def test_late_choices_and_old_category_controls_stay_in_their_original_editor_frame(self):
        self.categories_js("""
          let finish; api = () => new Promise(resolve => {finish = resolve;});
          const line = ed.lists.Deck[0], sheet = openCategorySheet(line.uid), set = action(sheet, 'Set category');
          const input = sheet.body.querySelector('input'); input.value = 'Ramp';
          ed.space = 'user2'; finish({categories: ['Private old space label']}); await tick(); set.click();
          assert.equal(line.category, null); assert.equal(sheet.body.querySelectorAll('option').length, 0);
          ed.space = 'home'; set.remove(); set.click(); assert.equal(line.category, null);
          sheet.close();
          api = async () => {throw new ApiError(503, 'Unavailable');};
          const failed = openCategorySheet(line.uid); await tick();
          assert(failed.body.textContent.includes("couldn't load")); const typed = failed.body.querySelector('input'); typed.value = 'My label';
          action(failed, 'Set category').click(); assert.equal(line.category, 'My label');
        """)
