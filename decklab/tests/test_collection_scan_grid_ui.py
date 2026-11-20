"""Grid capture uses oriented source pixels and stages each selected physical slot once."""
import unittest

from decklab.tests import test_collection_scan_ui as scan_ui

GRID_IMAGE = r"""
  const bitmap = {width: 4200, height: 6000, closes: 0, close() { this.closes++; }};
  const decoded = [], drawings = [];
  const file = {type: 'image/jpeg', name: 'synthetic-page.jpg', size: 4096};
  globalThis.createImageBitmap = async (source, options) => {
    decoded.push({source, options}); return bitmap;
  };
  const originalCreate = document.createElement;
  document.createElement = (tag) => {
    const node = originalCreate(tag);
    // The fixture DOM does not otherwise reflect the checkbox's initial checked attribute.
    if (tag === 'input') {
      const setAttribute = node.setAttribute.bind(node);
      node.setAttribute = (name, value) => {
        setAttribute(name, value);
        if (name === 'checked') node.checked = true;
      };
    }
    if (tag === 'canvas') {
      node.getContext = () => ({
        drawImage: (...args) => drawings.push({args, width: node.width, height: node.height}),
        clearRect() {}, strokeRect() {}, fillRect() {}, save() {}, restore() {},
      });
      node.toBlob = (finish) => finish({size: 3, type: 'image/jpeg'});
      node.toDataURL = () => 'data:image/jpeg;base64,QUJD';
    }
    return node;
  };
  globalThis.FileReader = class {
    readAsDataURL() { this.result = 'data:image/jpeg;base64,QUJD'; this.onload(); }
  };
  async function loadGridImage(grid, files = [file]) {
    const input = grid.element.querySelector('input[type="file"]');
    assert(input);
    input.files = files;
    input.fire('change');
    await flush();
  }
  function gridAction(grid, name) {
    const node = button(grid.element, name);
    assert(node, 'Expected grid action ' + name);
    node.click();
  }
"""


@unittest.skipUnless(scan_ui.NODE, "Node.js is not installed")
class CollectionScanGridTests(unittest.TestCase):
    def run_js(self, scenario):
        scan_ui.CollectionScanUiTests.run_js(self, GRID_IMAGE + scenario)

    def test_grid_slot_coordinates_cover_original_portrait_and_landscape_pages(self):
        self.run_js(r"""
          for (const [cols, rows] of [[2, 2], [3, 3], [4, 3], [3, 4]]) {
            const width = cols * 1150, height = rows * 1600;
            for (let i = 0; i < cols * rows; i++) {
              const rect = gridCropRect(width, height, cols, rows, i);
              same(rect, {x:(i % cols) * 1150, y:Math.floor(i / cols) * 1600, width:1150, height:1600});
            }
          }
          // The binder has a margin on every edge; a middle slot must exclude those margins.
          same(gridCropRect(6000, 4000, 3, 2, 4, {left:5, top:10, right:95, bottom:90}),
               {x:2100, y:2000, width:1800, height:1600});
        """)

    def test_stop_during_decode_closes_the_late_private_bitmap(self):
        self.run_js(r"""
          let finish;
          globalThis.createImageBitmap = () => new Promise(resolve => { finish = resolve; });
          const grid = colScanGrid({isCurrent:()=>true, canScan:()=>true,
                                    onStart:()=>{}, submit:()=>assert.fail('stale image read')});
          main.append(grid.element);
          await loadGridImage(grid);
          assert(finish, 'image decoding started');
          grid.stop();
          finish(bitmap); await flush();
          assert.equal(bitmap.closes, 1);
          assert.equal(grid.active, false);
          assert.equal(drawings.length, 0);
        """)

    def test_binder_layout_offers_each_visible_pocket_and_excludes_an_empty_page(self):
        self.run_js(r"""
          const grid = colScanGrid({isCurrent:()=>true, canScan:()=>true, onStart:()=>{},
                                    submit:()=>assert.fail('all pockets are empty')});
          main.append(grid.element);
          await loadGridImage(grid);
          const layout = grid.element.querySelector('[aria-label="Grid layout"]');
          for (const [id, count] of [['1x1',1],['2x2',4],['3x3',9],['4x3',12],['3x4',12]]) {
            layout.value = id; layout.fire('change');
            assert.equal(grid.element.querySelectorAll('[data-slot]').length, count, id);
          }
          for (const slot of grid.element.querySelectorAll('input[type="checkbox"]')) {
            slot.checked = false; slot.fire('change');
          }
          gridAction(grid, 'Scan selected slots'); await flush();
          gridAction(grid, 'Discard image');
          assert.equal(bitmap.closes, 1);
          assert.equal(grid.active, false);
        """)

    def test_full_resolution_crops_skip_empty_slots_and_only_retry_unstaged_copies(self):
        self.run_js(r"""
          const submitted = [];
          const outcomes = ['added', 'review', 'failed', 'added'];
          const grid = colScanGrid({isCurrent:()=>true, canScan:()=>true, onStart:()=>{},
            submit:async (jpeg, current, source) => {
              assert(current(), 'request belongs to the current image');
              assert.equal(jpeg, 'QUJD');
              submitted.push(source);
              return outcomes.shift();
            }});
          main.append(grid.element);
          await loadGridImage(grid);
          assert.equal(decoded.length, 1);
          assert.equal(decoded[0].options.imageOrientation, 'from-image');
          const slots = grid.element.querySelectorAll('input[type="checkbox"]');
          assert.equal(slots.length, 4);
          slots[1].checked = false; slots[1].fire('change');
          gridAction(grid, 'Scan selected slots');
          await flush(100);
          same(submitted, ['Page 1, row 1, column 1', 'Page 1, row 2, column 1', 'Page 1, row 2, column 2']);
          const statuses = () => grid.element.querySelectorAll('[data-slot]').map(label => label.dataset.state);
          same(statuses(), ['added', 'ready', 'review', 'failed']);
          const crops = drawings.filter(({args}) => args.length === 9 && args[0] === bitmap);
          assert.equal(crops.length, 3, 'each selected pocket is cut from the original bitmap');
          same(crops.map(({args}) => args.slice(1,5)), [[0,0,2100,3000],[0,3000,2100,3000],[2100,3000,2100,3000]]);
          for (const crop of crops) {
            assert(Math.max(crop.width, crop.height) <= 2000);
            same(crop.args.slice(5), [0,0,crop.width,crop.height]);
          }
          gridAction(grid, 'Scan selected slots');
          await flush(100);
          same(submitted.slice(3), ['Page 1, row 2, column 2']);
          same(statuses(), ['added', 'ready', 'review', 'added']);
          grid.stop();
          assert.equal(bitmap.closes, 1);
        """)

    def test_pause_after_current_crop_can_continue_without_replaying_it(self):
        self.run_js(r"""
          let finish;
          const submitted = [];
          const grid = colScanGrid({isCurrent:()=>true, canScan:()=>true, onStart:()=>{},
            submit:async (_jpeg, current, source) => {
              submitted.push(source);
              if (submitted.length === 1) await new Promise(resolve => { finish = resolve; });
              assert(current());
              return 'added';
            }});
          main.append(grid.element);
          await loadGridImage(grid);
          gridAction(grid, 'Scan selected slots'); await flush();
          assert.equal(submitted.length, 1);
          gridAction(grid, 'Stop after this slot');
          finish(); await flush(100);
          assert.equal(submitted.length, 1);
          assert.equal(grid.element.querySelector('[data-slot="1"]').dataset.state, 'added');
          gridAction(grid, 'Scan selected slots'); await flush(100);
          same(submitted, ['Page 1, row 1, column 1', 'Page 1, row 1, column 2',
                           'Page 1, row 2, column 1', 'Page 1, row 2, column 2']);
          grid.stop();
        """)

    def test_source_slot_survives_into_manual_printing_review_and_one_import_preview(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          const answers = [ELVES, GHALTA, ELVES];
          const calls = [];
          apiWrite = async (path, body) => {
            calls.push([path, body]);
            if (path === '/api/collection/scan') return answers.shift();
            assert.equal(path, '/api/collection/import/preview');
            return {token:'a'.repeat(32), format:'collection', rows:[], problems:[],
                    adds:{rows:2,cards:3}, dropped_basics:0, sha256:'s1', repeat_imports:[]};
          };
          await loadGridImage(ctx.grid);
          const absent = ctx.grid.element.querySelector('[data-slot="1"]').querySelector('input');
          absent.checked = false; absent.fire('change');
          gridAction(ctx.grid, 'Scan selected slots'); await flush(100);
          assert.equal(calls.length, 3);
          for (const [path, body] of calls) {
            assert.equal(path, '/api/collection/scan');
            same(body, {space:'home', photo:'QUJD'});
          }
          same(ctx.pending.map(row => [row.name, row.quantity]), [['Llanowar Elves', 2]]);
          assert(ctx.checkList.textContent.includes('Page 1, row 2, column 1'));
          gridAction(ctx.grid, 'Finish page');
          button(ctx.checkList, 'Ghalta, Primal Hunger (RIX 130) · RIX').click();
          assert.equal(ctx.unsure.length, 0);
          foot(ctx, 'review').click(); await flush();
          assert.equal(calls.length, 4);
          assert.equal(calls[3][0], '/api/collection/import/preview');
          const csv = calls[3][1].text;
          assert(csv.includes('Llanowar Elves,fdn,227,nonfoil,2'));
          assert(csv.includes('"Ghalta, Primal Hunger",rix,130,nonfoil,1'));
          assert(!csv.includes('Page 1') && !csv.includes('QUJD'));
        """)

    def test_late_crop_result_cannot_stage_cards_after_profile_switch_or_close(self):
        self.run_js(r"""
          for (const departure of ['switch', 'close']) {
            const ctx = openScanSheet(draw());
            let resolveRequest, calls = 0;
            apiWrite = async (path) => {
              assert.equal(path, '/api/collection/scan'); calls++;
              return new Promise(resolve => { resolveRequest = resolve; });
            };
            await loadGridImage(ctx.grid);
            gridAction(ctx.grid, 'Scan selected slots'); await flush();
            assert.equal(calls, 1);
            if (departure === 'switch') as('user2', MAY.user2);
            else ctx.sheet.close();
            resolveRequest(ELVES); await flush(100);
            assert.equal(calls, 1, 'remaining photos belong to the old context');
            assert.equal(ctx.pending.length, 0);
            assert.equal(ctx.unsure.length, 0);
            ctx.sheet.close();
          }
        """)

    def test_leaving_and_returning_to_tab_requires_a_fresh_read_for_the_interrupted_slot(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          let calls = 0, finish;
          apiWrite = async () => ++calls === 2 ? new Promise(resolve => { finish = resolve; }) : ELVES;
          await loadGridImage(ctx.grid);
          gridAction(ctx.grid, 'Scan selected slots'); await flush();
          assert.equal(calls, 2);
          assert.equal(ctx.pending[0].quantity, 1);
          document.hidden = true; document.fire('visibilitychange');
          document.hidden = false; document.fire('visibilitychange');
          finish(GHALTA); await flush(100);
          assert.equal(calls, 2);
          assert.equal(ctx.unsure.length, 0, 'old response cannot stage a private crop after returning');
          assert.equal(ctx.grid.element.querySelector('[data-slot="2"]').dataset.state, 'ready');
          gridAction(ctx.grid, 'Scan selected slots'); await flush(100);
          assert.equal(calls, 5);
          assert.equal(ctx.pending[0].quantity, 4, 'first completed slot was not counted again');
          ctx.sheet.close();
        """)

    def test_scanner_files_decode_in_natural_order_one_at_a_time_with_retry_for_a_corrupt_file(self):
        self.run_js(r"""
          const files = [10, 3, 1, 2].map(i => ({name:'private-scan' + i + '.jpg', size:1024, type:'image/jpeg'}));
          let failDecode = true, active = 0;
          const images = [], calls = [], releases = [];
          globalThis.createImageBitmap = async (source, options) => {
            assert.equal(active, 0, 'one decoded original at a time');
            assert.equal(options.imageOrientation, 'from-image');
            images.push(source.name);
            if (source === files[1] && failDecode) throw Error('cannot decode');
            active++;
            return {name:source.name, width:1400, height:2000, close() { active--; releases.push(source.name); }};
          };
          const grid = colScanGrid({isCurrent:()=>true, canScan:()=>true, onStart:()=>{},
            submit:async (jpeg, current, label) => {
              assert(current()); assert.equal(jpeg, 'QUJD');
              calls.push(label);
              return label.endsWith('2') ? 'review' : 'added';
            }});
          main.append(grid.element);
          const input = grid.element.querySelector('input[type="file"]');
          assert.notEqual(input.getAttribute('multiple'), null);
          await loadGridImage(grid, files);
          assert.equal(images.length, 0, 'no originals decoded until Scan selected files');
          assert.equal(grid.element.querySelectorAll('[data-slot]').length, 4);
          gridAction(grid, 'Scan selected files'); await flush(150);
          same(images, [1,2,3,10].map(i => 'private-scan' + i + '.jpg'));
          same(calls, ['Batch 1, file 1', 'Batch 1, file 2', 'Batch 1, file 4']);
          const statuses = () => grid.element.querySelectorAll('[data-slot]').map(n => n.dataset.state);
          same(statuses(), ['added','review','failed','added']);
          assert.equal(active, 0);
          failDecode = false;
          gridAction(grid, 'Scan selected files'); await flush(100);
          same(images.slice(4), ['private-scan3.jpg']);
          same(calls.slice(3), ['Batch 1, file 3']);
          same(statuses(), ['added','review','added','added']);
          same(releases, [1,2,10,3].map(i => 'private-scan' + i + '.jpg'));
          const crops = drawings.filter(({args}) => args.length === 9);
          assert.equal(crops.length, 4);
          for (const {args} of crops) same(args.slice(1,5), [0,0,1400,2000]);
          gridAction(grid, 'Finish batch');
          assert.equal(grid.active, false);
        """)

    def test_paused_files_preserve_staged_copies_and_a_failed_file_can_be_skipped(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          const files = [1,2,3].map(i => ({name:'file' + i + '.jpg', size:1024, type:'image/jpeg'}));
          let release, calls = 0;
          apiWrite = async (path, body) => {
            assert.equal(path, '/api/collection/scan');
            same(body, {space:'home', photo:'QUJD'});
            calls++;
            if (calls === 1) return new Promise(resolve => {release = resolve;});
            if (calls === 2) throw new ApiError(429, 'Scanner busy');
            return GHALTA;
          };
          await loadGridImage(ctx.grid, files);
          gridAction(ctx.grid, 'Scan selected files'); await flush();
          gridAction(ctx.grid, 'Stop after this file');
          release(ELVES); await flush(100);
          assert.equal(calls, 1);
          assert.equal(ctx.pending[0].quantity, 1);
          gridAction(ctx.grid, 'Scan selected files'); await flush(100);
          assert.equal(calls, 2, 'request failure pauses the remaining files');
          const failed = ctx.grid.element.querySelector('[data-slot="2"]');
          assert.equal(failed.dataset.state, 'failed');
          const checked = failed.querySelector('input'); checked.checked = false; checked.fire('change');
          gridAction(ctx.grid, 'Scan selected files'); await flush(100);
          assert.equal(calls, 3);
          assert.equal(ctx.pending[0].quantity, 1);
          assert.deepEqual(ctx.unsure.map(entry=>entry.source), ['Batch 1, file 3']);
          gridAction(ctx.grid, 'Finish batch');
          assert.equal(bitmap.closes, 3);
          ctx.sheet.close();
        """)

    def test_old_scanner_file_reply_cannot_reach_a_new_profile(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw()), files = [file, {...file, name:'other.jpg'}];
          let calls = 0, finish;
          apiWrite = () => { calls++; return new Promise(resolve=>{ finish=resolve; }); };
          await loadGridImage(ctx.grid, files);
          gridAction(ctx.grid, 'Scan selected files'); await flush();
          assert.equal(calls, 1);
          ctx.sheet.close();
          as('user2', MAY.user2);
          finish(GHALTA); await flush(100);
          assert.equal(calls, 1);
          assert.equal(ctx.unsure.length, 0);
          assert.equal(ctx.pending.length, 0);
          assert.equal(bitmap.closes, 1);
        """)


if __name__ == "__main__":
    unittest.main()
