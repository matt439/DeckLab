"""The Collection page's "Storage setup…" (E8-S25 slice 4, storage-setup.js), over the real scripts with fixture answers."""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + """
  const rows = [{name: 'Llanowar Elves', set: 'fdn', collector_number: '227', finish: 'nonfoil', quantity: '4',
    condition: 'NM', language: 'en', notes: ''}];
  const BOX = {id: 'box', name: 'Storage box', kind: 'box', capacity: 2400, sections: ['Row 1', 'Row 2', 'Row 3', 'Row 4'],
    order: 'colour-type', sleeved: false};
  const counted = (c, cards) => ({id: c.id, name: c.name, kind: c.kind, capacity: c.capacity, sleeved: c.sleeved, cards,
    over: c.capacity !== null && cards > c.capacity});
  const setupOf = (containers, extra = {}) => ({source: 'saved', default: containers.length ? containers[0].id : null,
    containers, elsewhere: 0, unplaced: 0, not_counted: 0, suggestions: ['Row 1'], ...extra});
  const VIEW = {space: 'home', revision: 0, ready: true, source: 'default', storage: {v: 1, default: 'box', containers: [BOX]},
    can_edit: true, kinds: ['box', 'binder', 'shelf', 'other'], orders: ['colour-type', 'set', 'name', 'none'],
    limits: {containers: 20, sections: 50, name: 40, capacity: 100000}};
  const draw = (data = {}) => { clear(main); as('matt', MAY.admin);
    return drawCollectionRows({space: 'home', sha256: 's1', rows, editable: true,
      storage_setup: setupOf([counted(BOX, 3)]), ...data}, 'home'); };
  const foot = (ctx, action) => ctx.sheet.foot.querySelector(`[data-action="${action}"]`);
  const type = (input, value, event = 'input') => { input.value = value; input.fire(event); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class StorageSetupUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_add_a_binder_preview_then_save_with_the_revision_read(self):
        self.run_js("""
          const cv = draw();
          const gets = [];
          api = async (path) => { gets.push(path); return VIEW; };
          const ctx = await openStorageSetup(cv); await flush();
          same(gets, ['/api/storage?space=home']);
          assert.equal(ctx.edit.querySelectorAll('.storage-container').length, 1);
          assert.equal(ctx.edit.querySelector('.storage-name').value, 'Storage box');
          button(ctx.edit, 'Add a container').click();
          const names = ctx.edit.querySelectorAll('.storage-name');
          assert.equal(names.length, 2);
          type(names[1], 'Binder');
          const binder = ctx.edit.querySelectorAll('.storage-container')[1];
          type(binder.querySelector('textarea'), '3 rows');
          const inputs = binder.querySelectorAll('input');
          type(inputs[1], '360');                                    // Holds (cards)
          inputs[2].checked = true; inputs[2].fire('change');        // kept sleeved
          const writes = [];
          const after = setupOf([counted(BOX, 2), {id: 'binder', name: 'Binder', kind: 'binder', capacity: 360, sleeved: true,
            cards: 1, over: false}], {suggestions: ['Row 1', 'Row 2', 'Row 3', 'Row 4', 'Row 1']});
          const proposed = {v: 1, default: 'box', containers: [BOX, {id: 'binder', name: 'Binder', kind: 'binder', capacity: 360,
            sections: ['Row 1', 'Row 2', 'Row 3'], order: 'none', sleeved: true}]};
          apiWrite = async (path, body, method = 'POST') => { writes.push([path, body, method]);
            if (path === '/api/storage/preview') return {space: 'home', storage: proposed, now: setupOf([counted(BOX, 3)]), after,
              moves: [{from: null, to: 'Binder', locations: 2}], counts_error: null};
            return {...VIEW, revision: 1, source: 'saved', storage: proposed}; };
          foot(ctx, 'preview').click(); await flush();
          same(writes[0], ['/api/storage/preview', {space: 'home', storage: {default: 'box', containers: [
            {id: 'box', name: 'Storage box', kind: 'box', capacity: 2400, sections: ['Row 1', 'Row 2', 'Row 3', 'Row 4'],
             order: 'colour-type', sleeved: false},
            {name: 'Binder', kind: 'binder', capacity: 360, sections: ['Row 1', 'Row 2', 'Row 3'], order: 'none', sleeved: true}]}},
            'POST']);
          const review = ctx.reviewBox.textContent;
          assert(review.includes(`Storage box: about 3 of ${num(2400)} cards`), review);
          assert(review.includes('Binder: about 1 of 360 cards'), review);
          assert(review.includes('2 recorded locations would move from somewhere else to Binder.'), review);
          assert(review.includes('Cards with no location go to Storage box.'), review);
          assert(!ctx.reviewBox.hidden && ctx.edit.hidden);
          foot(ctx, 'save').click(); await flush();
          same(writes[1], ['/api/storage', {profile: 'matt', space: 'home', expect: 0, storage: proposed}, 'PUT']);
          assert(ctx.sheet.closed);
          const lines = main.querySelector('.col-storage-box').querySelectorAll('.col-storage-line').map(s => s.textContent);
          assert.equal(lines[1], 'Binder: about 1 of 360 cards.');
          assert(main.querySelector('.col-message').textContent.includes('Storage setup saved.'));
        """)

    def test_a_missing_name_or_bad_capacity_stops_the_preview(self):
        self.run_js("""
          const cv = draw();
          api = async () => VIEW;
          let previews = 0;
          apiWrite = async () => { previews += 1; return {}; };
          const ctx = await openStorageSetup(cv); await flush();
          button(ctx.edit, 'Add a container').click();
          foot(ctx, 'preview').click(); await flush();
          assert(ctx.message.textContent.includes('Container 2 needs a name.'), ctx.message.textContent);
          type(ctx.edit.querySelectorAll('.storage-name')[1], 'Shelf');
          type(ctx.edit.querySelectorAll('.storage-container')[1].querySelectorAll('input')[1], '0');
          foot(ctx, 'preview').click(); await flush();
          assert(ctx.message.textContent.includes("Shelf's capacity must be a whole number of cards from 1 to"), ctx.message.textContent);
          assert.equal(previews, 0);
        """)

    def test_move_remove_and_the_default_follow_the_draft(self):
        self.run_js("""
          const cv = draw();
          api = async () => ({...VIEW, revision: 4, source: 'saved', storage: {v: 1, default: 'box', containers: [BOX,
            {id: 'binder', name: 'Binder', kind: 'binder', capacity: null, sections: [], order: 'set', sleeved: true}]}});
          const ctx = await openStorageSetup(cv); await flush();
          button(ctx.edit, 'Move down').click();
          same(ctx.edit.querySelectorAll('.storage-name').map(i => i.value), ['Storage box', 'Binder'].reverse());
          const removes = ctx.edit.querySelectorAll('button').filter(b => b.textContent === 'Remove');
          removes[1].click();                                        // the box, now second, was the default
          same(ctx.edit.querySelectorAll('.storage-name').map(i => i.value), ['Binder']);
          same(storageRecord(ctx), {default: null, containers: [{id: 'binder', name: 'Binder', kind: 'binder', capacity: null,
            sections: [], order: 'set', sleeved: true}]});
          same(storageSections('4 rows'), ['Row 1', 'Row 2', 'Row 3', 'Row 4']);
          same(storageSections(' Page 1-20 \\n\\n Page  21-40'), ['Page 1-20', 'Page 21-40']);
        """)

    def test_a_setup_saved_meanwhile_offers_the_latest_and_saves_nothing(self):
        self.run_js("""
          const cv = draw();
          api = async () => VIEW;
          const ctx = await openStorageSetup(cv); await flush();
          const latest = {...VIEW, revision: 2, source: 'saved', storage: {v: 1, default: null, containers: []}};
          apiWrite = async (path) => {
            if (path === '/api/storage/preview') return {space: 'home', storage: VIEW.storage, now: null, after: null, moves: [],
              counts_error: "The collection couldn't be read, so the counts aren't shown."};
            throw new ApiError(409, 'The storage setup changed. Reload it before saving.', {latest}); };
          foot(ctx, 'preview').click(); await flush();
          assert(ctx.reviewBox.textContent.includes("The collection couldn't be read"));
          foot(ctx, 'save').click(); await flush();
          assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes('changed somewhere else while this sheet was open. Nothing was saved.'));
          foot(ctx, 'latest').click(); await flush();
          assert.equal(ctx.revision, 2);
          assert.equal(ctx.edit.querySelectorAll('.storage-container').length, 0);
          assert(ctx.edit.textContent.includes('the built-in storage box is turned off once this is saved'));
        """)

    def test_before_the_migration_and_for_a_reader_nothing_can_be_saved(self):
        self.run_js("""
          let cv = draw();
          api = async () => ({...VIEW, ready: false});
          let ctx = await openStorageSetup(cv); await flush();
          assert(ctx.message.textContent.includes("Deck Lab's database needs updating on the PC"));
          assert.equal(foot(ctx, 'preview'), null);
          ctx.sheet.close();
          cv = draw({editable: false});
          assert.equal(await openStorageSetup(cv), null);            // a reader gets no sheet
          assert.equal(main.querySelector('.col-storage-change'), null);
        """)

    def test_the_count_lines_change_opens_it(self):
        self.run_js("""
          const cv = draw();
          const gets = [];
          api = async (path) => { gets.push(path); return VIEW; };
          const change = main.querySelector('.col-storage-change');
          assert.equal(change.textContent, 'Change…');
          change.click(); await flush();
          same(gets, ['/api/storage?space=home']);
          assert(openDialog().textContent.includes('Storage setup for'));
        """)

if __name__ == "__main__":
    unittest.main()
