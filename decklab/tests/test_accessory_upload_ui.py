"""Accessory device-photo drafts, atomic saves and abandoned async work.

Runs the real index-order scripts with synthetic FileReader bytes in the UI fixture:
no photo files, browser, server or database are used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  editor = null;
  const matt = {id: 'matt', name: 'Matt', role: 'admin', space: 'home', plays_as: 'user'};
  const user1 = {id: 'user1', name: 'User1', role: 'member', space: 'home', plays_as: 'wife'};
  state.profiles = [matt, user1]; state.profile = matt; state.remote = false;
  state.may = {accessories: true, see_accessories: true};
  for (const kind of ['localStorage', 'sessionStorage']) {
    const values = new Map();
    window[kind] = {getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key)};
  }
  const requests = [], saved = [], toasts = [], readers = [];
  const flush = async () => { for (let n = 0; n < 12; n++) await Promise.resolve(); };
  const held = () => { let resolve, reject; const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
    return {promise, resolve, reject}; };
  let respond = async () => ({ok: true, changed_id: 'photo', data: {sha256: 'after', items: []}});
  api = async (path, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({path, body}); return respond(path, body);
  };
  toast = text => toasts.push(text);
  globalThis.FileReader = class {
    constructor() { this.readyState = 0; this.result = null; this.events = new Map(); readers.push(this); }
    addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, []); this.events.get(type).push(fn); }
    removeEventListener(type, fn) { this.events.set(type, (this.events.get(type) || []).filter(item => item !== fn)); }
    fire(type) { const event = {target: this}; if (this['on' + type]) this['on' + type](event);
      for (const fn of this.events.get(type) || []) fn(event); }
    readAsDataURL(file) { this.file = file; this.readyState = 1; }
    abort() { this.aborted = true; this.readyState = 2; this.fire('abort'); this.fire('loadend'); }
    finish(result = 'data:image/png;base64,AQID') {
      this.result = result; this.readyState = 2; this.fire('load'); this.fire('loadend');
    }
    fail() { this.error = new Error('Synthetic read failed'); this.readyState = 2; this.fire('error'); this.fire('loadend'); }
  };
  let lastCtx;
  const originalDrawPicture = drawPicture;
  drawPicture = ctx => { lastCtx = ctx; return originalDrawPicture(ctx); };
  const existing = {id: 'old', kind: 'sleeves', owner: 'matt', name: 'Matte', brand: 'Dragon Shield',
    colour: 'black', quantity: 100, capacity: null, image: 'old.png', image_url: '/accessory-img/old.png?v=old',
    crop: '0.1,0.1,0.8,0.8', link: '', image_source: 'https://shop.test/old.png', notes: 'Keep notes',
    label: 'Dragon Shield Matte', used_by: []};
  function opened(options = {}) {
    const sheet = openAccessorySheet({sha256: 's1', owners: [{id: 'matt', name: 'Matt'}, {id: 'shared', name: 'Shared'}],
      onSaved: (...args) => saved.push(args), ...options});
    const ctx = lastCtx;
    if (!options.row) {ctx.inputs.name.value = 'Photo sleeves'; ctx.inputs.quantity.value = '100';}
    return {sheet, ctx};
  }
  const button = (root, words) => root.querySelectorAll('button').find(item =>
    words instanceof RegExp ? words.test(item.textContent) : item.textContent === words);
  const file = (extra = {}) => ({name: 'private-photo.png', webkitRelativePath: 'private/family/photo.png',
    type: 'image/png', size: 3, ...extra});
  function choose(ctx, photo = file()) {
    assert(ctx.photoInput, 'the form exposes its device-photo input');
    ctx.photoInput.files = photo ? [photo] : []; ctx.photoInput.fire('change');
  }
  const posts = () => requests.filter(item => item.path === '/api/accessories/save');
  function isolatePageRendering() {
    noteVisit = () => {}; syncShell = () => {}; drawShell = () => {}; applyTheme = () => {};
    loadSimulations = () => {}; hideShell = () => {}; showLibrary = () => {};
    location.hash = '#/library';
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AccessoryUploadInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_supported_photos_preview_locally_and_save_only_strict_payload(self):
        self.run_js(r"""
          for (const type of ['image/jpeg', 'image/png', 'image/webp']) {
            const {sheet, ctx} = opened();
            assert.equal(ctx.photoInput.getAttribute('type'), 'file');
            const accept = ctx.photoInput.getAttribute('accept');
            assert(accept.includes('image/jpeg') && accept.includes('image/png') && accept.includes('image/webp'));
            assert.equal(ctx.photoInput.getAttribute('capture'), null, 'Photos, Camera and Files remain available');
            const before = requests.length;
            choose(ctx, file({type}));
            readers.at(-1).finish(`data:${type};base64,AQID`); await flush();
            assert.equal(requests.length, before, 'reading and previewing stay on the device');
            assert(ctx.picture.querySelector('img').getAttribute('src').startsWith(`data:${type};base64,`));
            button(sheet.foot, 'Save').click(); await flush();
            const sent = posts().at(-1);
            same(sent.body.image, {upload: 'AQID'});
            assert.equal(sent.body.profile, 'matt'); assert.equal(sent.body.action, 'add');
            assert.equal(sent.body.row.image_source, '');
            assert(!JSON.stringify(sent.body).includes('private-photo'));
            assert(!JSON.stringify(sent.body).includes('private/family'));
            assert(!JSON.stringify(sent.body).includes(type));
            assert(sheet.closed);
          }
          assert.equal(posts().length, 3); assert.equal(saved.length, 3);
        """)

    def test_replacement_crop_and_row_are_saved_in_one_request(self):
        self.run_js(r"""
          const {sheet, ctx} = opened({row: existing});
          choose(ctx); readers.at(-1).finish(); await flush();
          button(ctx.picture, /^Crop/).click();
          const area = ctx.picture.querySelector('.acc-crop-box');
          area.fire('keydown', {key: 'ArrowLeft', shiftKey: true});
          button(ctx.picture, 'Done').click();
          assert(ctx.pic.crop && ctx.pic.crop !== existing.crop);
          const crop = ctx.pic.crop;
          assert.equal(requests.length, 0);
          button(sheet.foot, 'Save').click(); await flush();
          assert.equal(requests.length, 1);
          const body = posts()[0].body;
          same(body.image, {upload: 'AQID'}); assert.equal(body.id, existing.id);
          assert.equal(body.row.crop, crop); assert.equal(body.row.image_source, '');
          assert.equal(body.row.notes, existing.notes); assert.equal(body.sha256, 's1');
        """)

    def test_invalid_empty_and_cancelled_selection_keep_the_prior_picture(self):
        self.run_js(r"""
          const {sheet, ctx} = opened({row: existing});
          const prior = JSON.stringify(ctx.pic);
          choose(ctx, null); await flush();
          assert.equal(JSON.stringify(ctx.pic), prior); assert.equal(readers.length, 0);
          for (const bad of [file({size: 0}), file({size: 4 * 1024 * 1024 + 1}),
                             file({type: 'image/gif'}), file({type: 'application/pdf'})]) {
            choose(ctx, bad); await flush();
            assert.equal(JSON.stringify(ctx.pic), prior);
            assert(ctx.message.textContent.trim(), 'invalid photos explain what to change');
          }
          assert.equal(readers.length, 0); assert.equal(requests.length, 0);
          assert.equal(ctx.picture.querySelector('img').getAttribute('src'), '/accessory-img/old.png?v=old&viewer=matt');
          sheet.close();
        """)

    def test_read_error_and_malformed_payload_do_not_replace_the_saved_picture(self):
        self.run_js(r"""
          const {sheet, ctx} = opened({row: existing});
          const prior = JSON.stringify(ctx.pic);
          choose(ctx); readers.at(-1).fail(); await flush();
          assert.equal(JSON.stringify(ctx.pic), prior); assert(ctx.message.textContent.trim());
          for (const data of ['', 'data:image/png;base64,', 'data:image/png;base64,not base64!']) {
            choose(ctx); readers.at(-1).finish(data); await flush();
            assert.equal(JSON.stringify(ctx.pic), prior); assert(ctx.message.textContent.trim());
          }
          assert.equal(requests.length, 0); sheet.close();
        """)

    def test_pending_read_blocks_find_save_and_another_read(self):
        self.run_js(r"""
          const {sheet, ctx} = opened(); ctx.inputs.link.value = 'https://shop.test/product';
          choose(ctx);
          assert(ctx.photoInput.disabled && ctx.find.disabled && button(sheet.foot, 'Save').disabled);
          await findPicture(ctx); await saveFromSheet(ctx); accReadPhoto(ctx, file({name: 'second.png'}));
          assert.equal(readers.length, 1); assert.equal(requests.length, 0);
          readers[0].finish(); await flush();
          assert(!ctx.photoInput.disabled && !ctx.find.disabled && !button(sheet.foot, 'Save').disabled);
          sheet.close();
        """)

    def test_pending_fetch_and_save_block_device_reads(self):
        self.run_js(r"""
          const fetchAnswer = held(); respond = () => fetchAnswer.promise;
          const {sheet, ctx} = opened(); ctx.inputs.link.value = 'https://shop.test/product';
          const finding = findPicture(ctx); await flush();
          accReadPhoto(ctx, file()); await saveFromSheet(ctx);
          assert.equal(readers.length, 0); assert.equal(requests.length, 1);
          fetchAnswer.resolve({token: 'found', preview_url: '/accessory-img/staged/found', width: 80, height: 100});
          await finding; await flush();
          choose(ctx); readers.at(-1).finish(); await flush();
          const saveAnswer = held(); respond = () => saveAnswer.promise;
          button(sheet.foot, 'Save').click(); await flush();
          accReadPhoto(ctx, file()); await findPicture(ctx); await saveFromSheet(ctx);
          assert.equal(readers.length, 1); assert.equal(posts().length, 1);
          saveAnswer.resolve({ok: true, data: {items: []}}); await flush();
        """)

    def test_cancel_aborts_a_read_and_ignores_its_late_completion(self):
        self.run_js(r"""
          const {sheet, ctx} = opened(); choose(ctx); const reader = readers[0];
          sheet.dialog.querySelector('[aria-label="Close"]').click();
          assert(sheet.closed); assert(reader.aborted);
          reader.finish(); await flush(); await saveFromSheet(ctx);
          assert(!JSON.stringify(ctx.pic).includes('AQID'));
          assert.equal(requests.length, 0); assert.equal(saved.length, 0); assert.equal(toasts.length, 0);
        """)

    def test_cancelling_a_ready_photo_discards_its_payload_without_persistence(self):
        self.run_js(r"""
          const {sheet, ctx} = opened(); choose(ctx); readers[0].finish(); await flush();
          assert(ctx.picture.querySelector('img'));
          button(sheet.foot, 'Cancel').click(); await flush();
          assert(sheet.closed); assert.equal(ctx.pic, null);
          assert.equal(requests.length, 0); assert.equal(saved.length, 0);
        """)

    def test_failed_save_retains_the_photo_crop_and_typed_draft_for_retry(self):
        self.run_js(r"""
          const {sheet, ctx} = opened(); choose(ctx); readers[0].finish(); await flush();
          ctx.inputs.notes.value = 'A note I typed';
          button(ctx.picture, /^Crop/).click();
          ctx.picture.querySelector('.acc-crop-box').fire('keydown', {key: 'ArrowLeft', shiftKey: true});
          button(ctx.picture, 'Done').click();
          respond = async () => {throw new Error('Try the save again');};
          button(sheet.foot, 'Save').click(); await flush();
          assert(!sheet.closed); assert(ctx.message.textContent.includes('Try the save again'));
          assert.equal(ctx.inputs.notes.value, 'A note I typed'); assert(!button(sheet.foot, 'Save').disabled);
          const first = posts()[0].body;
          respond = async () => ({ok: true, data: {items: []}});
          button(sheet.foot, 'Save').click(); await flush();
          same(posts()[1].body.image, first.image); assert.equal(posts()[1].body.row.crop, first.row.crop);
          assert.equal(posts()[1].body.row.notes, first.row.notes); assert.equal(readers.length, 1);
          assert.equal(saved.length, 1); assert(sheet.closed);
        """)

    def test_profile_route_and_away_cleanup_abort_and_drop_drafts(self):
        self.run_js(r"""
          isolatePageRendering(); respond = async () => ({theme: 'system'});
          for (const leave of [async () => {await chooseProfile(user1);}, async () => {route();},
                              async () => {session.set('hiddenAt', String(Date.now() - 31 * 60 * 1000));
                                backFromAway(); await flush();}]) {
            state.profile = matt; state.may = {accessories: true, see_accessories: true};
            const {sheet, ctx} = opened(); choose(ctx); const reader = readers.at(-1);
            await leave(); await flush();
            assert(sheet.closed); assert(reader.aborted);
            reader.finish(); await flush();
            assert(!JSON.stringify(ctx.pic).includes('AQID'));
          }
          assert.equal(posts().length, 0); assert.equal(saved.length, 0);
        """)

    def test_a_sha_lookup_cannot_send_the_upload_after_the_viewer_changes(self):
        self.run_js(r"""
          const lookup = held(); respond = () => lookup.promise;
          const {ctx} = opened({sha256: undefined}); choose(ctx); readers[0].finish(); await flush();
          const saving = saveFromSheet(ctx); await flush();
          assert.equal(requests[0].path, '/api/accessories'); assert.equal(posts().length, 0);
          state.profile = user1;
          lookup.resolve({sha256: 'fresh'}); await saving; await flush();
          assert.equal(posts().length, 0); assert.equal(saved.length, 0); assert.equal(toasts.length, 0);
        """)

    def test_late_save_success_has_no_callback_toast_or_cache_effect(self):
        self.run_js(r"""
          const answer = held(); respond = () => answer.promise;
          const {sheet, ctx} = opened(); choose(ctx); readers[0].finish(); await flush();
          button(sheet.foot, 'Save').click(); await flush(); assert.equal(posts().length, 1);
          state.profile = user1; routeToken += 1; state.library = {currentViewer: 'user1'};
          sheet.close(); answer.resolve({ok: true, data: {items: []}}); await flush();
          assert.equal(saved.length, 0); assert.equal(toasts.length, 0);
          same(state.library, {currentViewer: 'user1'});
        """)

    def test_conflict_reapply_keeps_the_upload_and_rebases_other_fields(self):
        self.run_js(r"""
          const {sheet, ctx} = opened({row: existing}); choose(ctx); readers[0].finish(); await flush();
          const latest = {sha256: 's2', items: [{...existing, quantity: 200}]};
          respond = async () => {const error = new Error('The list changed'); error.status = 409;
            error.data = {latest}; throw error;};
          button(sheet.foot, 'Save').click(); await flush();
          assert(!sheet.closed); assert(sheet.body.textContent.includes('Your changes are still here'));
          respond = async () => ({ok: true, data: latest});
          button(sheet.foot, /re-apply my changes/).click(); await flush();
          assert.equal(posts().length, 2); same(posts()[1].body.image, {upload: 'AQID'});
          assert.equal(posts()[1].body.row.image_source, ''); assert.equal(posts()[1].body.row.quantity, 200);
          assert.equal(posts()[1].body.sha256, 's2'); assert.equal(readers.length, 1);
          assert.equal(saved.length, 1); assert(sheet.closed);
        """)

    def test_nested_kit_add_cleanup_drops_the_photo_and_blocks_late_assignment(self):
        self.run_js(r"""
          isolatePageRendering();
          const picked = [];
          const data = {sha256: 's1', items: [], holders_options: [{id: 'casual/test', owner: 'matt',
            sleeves: '', need: 60, holder_sha256: 'holder'}]};
          for (const leave of [async () => closeAccessorySheets(), async () => route(),
                              async () => chooseProfile(user1)]) {
            state.profile = matt; state.may = {accessories: true, see_accessories: true};
            const answer = held();
            respond = async path => path === '/api/accessories/save' ? answer.promise
              : path === '/api/accessories' ? data : {theme: 'system'};
            const parent = kitPicker({holder: 'casual/test', onPicked: value => picked.push(value)});
            await flush(); button(parent.body, ACC_KINDS.sleeves.add).click();
            const ctx = lastCtx, child = ctx.sheet;
            assert.equal(document.querySelectorAll('dialog').length, 2);
            ctx.inputs.name.value = 'Photo sleeves'; ctx.inputs.quantity.value = '100';
            choose(ctx); readers.at(-1).finish(); await flush();
            button(child.foot, 'Save').click(); await flush();
            const sent = posts().length;
            await leave(); await flush();
            assert(parent.closed && child.closed);
            assert.equal(document.querySelectorAll('dialog').length, 0);
            assert.equal(ctx.pic, null);
            answer.resolve({changed_id: 'new', data: {...data, items: [{...existing, id: 'new'}]}});
            await flush(); await saveFromSheet(ctx);
            assert.equal(posts().length, sent, 'a closed nested draft cannot send another save');
            assert.equal(requests.filter(item => item.path === '/api/accessories/assign').length, 0);
          }
          assert.equal(picked.length, 0); assert.equal(toasts.length, 0);
        """)

    def test_cleanup_closes_kit_share_and_move_confirmations_without_assigning(self):
        self.run_js(r"""
          for (const field of ['sleeves', 'deck_box']) {
            const item = {...existing, id: 'shared-kit', owner: 'shared', kind: field,
              label: 'Shared kit', quantity: field === 'sleeves' ? 100 : 1, capacity: 100,
              used_by: [{holder: 'casual/other', title: 'Other deck'}]};
            const data = {sha256: 's1', items: [item], holders_options: [{id: 'casual/test', owner: 'matt',
              sleeves: '', deck_box: '', need: 60, holder_sha256: 'holder'}]};
            // A move is offered only from a deck the viewer may change (E10-S42): the library says whose.
            state.may = {accessories: true, see_accessories: true, deck_spaces: [], home_player: 'user'};
            state.library = {decks: [{id: 'casual/other', space: 'home', player: 'user'}]};
            respond = async () => data;
            const parent = kitPicker({holder: 'casual/test', field}); await flush();
            button(parent.body, /Shared kit/).click(); await flush();
            const confirmation = document.querySelectorAll('dialog').find(dialog => dialog !== parent.dialog);
            assert(confirmation); assert.equal(document.querySelectorAll('dialog').length, 2);
            const choice = button(confirmation, /^Move (it|them) here$/); assert(choice);
            closeAccessorySheets();
            assert(parent.closed); assert.equal(document.querySelectorAll('dialog').length, 0);
            choice.click(); await flush();
            assert.equal(requests.filter(request => request.path === '/api/accessories/assign').length, 0);
          }
          assert.equal(posts().length, 0); assert.equal(toasts.length, 0);
        """)

    def test_kit_moves_are_offered_only_from_decks_the_viewer_may_change(self):
        self.run_js(r"""
          state.may = {accessories: true, see_accessories: true, deck_spaces: [], home_player: 'wife'};
          state.library = {decks: [{id: 'casual/other', space: 'home', player: 'either'}]};
          const item = {...existing, id: 'shared-kit', owner: 'shared', kind: 'sleeves', label: 'Shared kit',
            quantity: 100, used_by: [{holder: 'casual/other', title: 'Other deck'}]};
          respond = async () => ({sha256: 's1', items: [item], holders_options: [{id: 'casual/test', owner: 'user1',
            sleeves: '', deck_box: '', need: 60, holder_sha256: 'holder'}]});
          const parent = kitPicker({holder: 'casual/test', field: 'sleeves'}); await flush();
          button(parent.body, /Shared kit/).click(); await flush();
          // Warned first (E8-S20, 2026-10-19), but offered only sharing, not a move: User1 can't change
          // an "either" deck.
          assert(!document.body.textContent.includes('Move them here'));
          assert.equal(requests.filter(request => request.path === '/api/accessories/assign').length, 0);
          button(document.body, /^Use them here too$/).click(); await flush();
          const assigns = requests.filter(request => request.path === '/api/accessories/assign');
          assert.equal(assigns.length, 1); assert.equal(assigns[0].body.move_from, undefined);
        """)


if __name__ == "__main__":
    unittest.main()
