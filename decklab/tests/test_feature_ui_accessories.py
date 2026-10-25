"""The Sleeves & boxes page and the kit picker, in the complete page's real script order.

Uses test_feature_ui's runner (its FeatureUiTests.run_js, with the packing plan's tick double)
and an event/DOM double, not a browser or real inventory writes.
"""
import unittest
from decklab.tests import test_feature_ui as feature_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AccessoriesUiTests(unittest.TestCase):
    run_js = feature_ui.FeatureUiTests.run_js

    # The Accessories page's data, as GET /api/accessories gives it, and helpers for its scenarios.
    ACCESSORIES = """
      const settle = async () => { for (let i = 0; i < 30; i++) await null; };
      const sheets = () => document.body.querySelectorAll('dialog');
      const button = (root, text) => root.querySelectorAll('button').find(b => b.textContent === text);
      state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
      document.body.append(el('p', {id: 'toast'}));
      const otterSleeves = {id:'ds-black',kind:'sleeves',brand:'Dragon Shield',name:'Matte',colour:'black',quantity:60,
        image:'',image_url:null,link:'',image_source:'',notes:'',label:'Dragon Shield Matte (black)',
        used_by:[{holder:'casual/izzet-otters',title:'Izzet Otters',kind:'deck',need:75}],short:15};
      const box = {id:'ug-boulder',kind:'deck_box',brand:'Ultimate Guard',name:'Boulder 100+',colour:'',quantity:2,
        image:'',image_url:null,link:'',image_source:'',notes:'',label:'Ultimate Guard Boulder 100+',used_by:[],short:0};
      const data = {sha256:'a'.repeat(64),exists:true,items:[otterSleeves,box],problems:[],
        products:[{file:'la.csv',holder:'product/la',title:'Lightning Aggro',need:75,holder_sha256:'b'.repeat(64),
          sleeves:{value:'red',id:null,state:'text',label:'red'},deck_box:null}],
        holders_options:[{id:'casual/izzet-otters',title:'Izzet Otters',kind:'deck',need:75,sleeves:'ds-black',
          deck_box:null,holder_sha256:'c'.repeat(64)},{id:'casual/gruul',title:'Gruul',kind:'deck',need:60,
          sleeves:null,deck_box:null,holder_sha256:'d'.repeat(64)}]};
    """

    def test_accessories_page_draws_and_goes_busy(self):
        # WP9: click to edit (no Edit/Remove pair on every tile), no "Not in use" chip, a dashed slot for nothing
        # chosen, the built decks without sleeves, and a product's sleeves and box chosen with Choose….
        self.run_js(self.ACCESSORIES + """
          clear(main);
          const view = drawAccessories(data, routeToken);
          const text = main.textContent;
          for (const words of ['60 sleeves', 'Izzet Otters', '15 sleeves short', '2 boxes',
                               'Products kept intact', 'Lightning Aggro', 'None chosen',
                               'Built decks without sleeves (1)', 'Gruul']) {
            assert(text.includes(words), words);
          }
          // Unused is the usual case, so it has no chip.
          for (const words of ['Free', 'Not in use', '“red” (not in the list)']) assert(!text.includes(words), words);
          const labelled = (label) => main.querySelectorAll('button').find(b => b.getAttribute('aria-label') === label);
          assert.equal(main.querySelectorAll('button').filter(b => b.textContent === 'Remove').length, 0);
          assert(labelled('Edit Dragon Shield Matte'));
          // The sleeves in use: the deck a chip linking to it.
          assert(main.querySelectorAll('a').find(a => a.textContent === 'Izzet Otters'));
          // No select saves on change any more.
          assert.equal(main.querySelectorAll('select').length, 0);
          assert(main.querySelectorAll('.acc-slot-none').length >= 2);
          setAccessoriesBusy(view, true);
          assert.equal(view.root.getAttribute('aria-busy'), 'true');
          assert(view.root.querySelectorAll('.acc-mutate').every(c => c.disabled));
          setAccessoriesBusy(view, false);
          // The filter shows one kind.
          button(main, 'Deck boxes').click();
          assert(!main.textContent.includes('60 sleeves · black')); assert(main.textContent.includes('2 boxes'));
          // Remove sits at the bottom of the sheet, disabled with the reason while a deck uses it.
          button(main, 'All').click();
          labelled('Edit Dragon Shield Matte').click();
          let sheet = sheets()[0];
          const remove = sheet.querySelector('[data-action="remove"]');
          assert.equal(remove.disabled, true); assert(remove.getAttribute('aria-describedby'));
          assert(sheet.textContent.includes("In use, so it can't be removed"));
          sheet.querySelector('.sheet-close').click();
          labelled('Edit Ultimate Guard Boulder 100+').click();
          sheet = sheets()[0];
          assert.equal(sheet.querySelector('[data-action="remove"]').disabled, false);
          sheet.querySelector('.sheet-close').click();
          // Choosing a product's deck box opens the kit picker; its pick assigns with status.csv's sha.
          let sent = null;
          api = async () => data;
          apiWrite = async (path, body) => { sent = {path, body}; return {data, holder: {}, warnings: []}; };
          labelled('Choose a deck box for Lightning Aggro').click(); await settle();
          const picker = sheets()[0]; assert(picker.textContent.includes('Choose deck box for Lightning Aggro'));
          picker.querySelectorAll('button').find(b => b.textContent.includes('Ultimate Guard Boulder 100+')).click();
          await settle();
          same(sent, {path: '/api/accessories/assign', body: {holder: 'product/la', field: 'deck_box', id: 'ug-boulder',
            holder_sha256: 'b'.repeat(64)}});
          // A built deck without sleeves: Choose… opens the picker for its sleeves.
          labelled('Choose sleeves for Gruul').click(); await settle();
          assert(sheets()[0].textContent.includes('Choose sleeves for Gruul'));
          sheets()[0].querySelector('.sheet-close').click();
          // A read-only visitor: a tile opens the item's details (notes, shop link, who uses it), with nothing to save.
          const realMay = mayDo;
          mayDo = () => false;
          clear(main);
          drawAccessories({...data, items: [{...otterSleeves, notes: 'Bought at the shop', link: 'https://shop.example/p/1'}, box]}, routeToken);
          mayDo = realMay;
          main.querySelectorAll('button').find(b => b.getAttribute('aria-label') === 'Dragon Shield Matte: details').click();
          const details = sheets()[0];
          assert(details.textContent.includes('Bought at the shop'));
          assert(details.textContent.includes('Shop page'));
          assert(details.textContent.includes('Izzet Otters'));
          assert.equal(details.querySelector('[data-action="save"]'), null);
          assert.equal(details.querySelector('[data-action="remove"]'), null);
        """)

    def test_accessory_edit_conflict_reapplies_onto_the_latest(self):
        self.run_js(self.ACCESSORIES + """
          clear(main);
          drawAccessories(data, routeToken);
          main.querySelectorAll('button').find(b => b.getAttribute('aria-label') === 'Edit Dragon Shield Matte').click();
          const sheet = sheets()[0]; assert(sheet);
          const name = sheet.querySelectorAll('input').find(i => i.id && i.id.startsWith('acc-name'));
          assert.equal(name.value, 'Matte'); name.value = 'Matte Dual';
          const theirs = {...otterSleeves, colour: 'jet black', quantity: 100};
          const latest = {...data, sha256: 'e'.repeat(64), items: [theirs, box]};
          const bodies = [];
          apiWrite = async (path, body) => {
            bodies.push(body);
            if (bodies.length === 1) throw new ApiError(409, 'User1 saved it in Deck Lab at 7:42 pm.',
              {conflict: {reason: 'changed', by: 'User1', when: new Date().toISOString()}, latest});
            return {saved: true, changed_id: 'ds-black', data: latest, warnings: []};
          };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(bodies[0].action, 'edit'); assert.equal(bodies[0].image, null);
          assert(sheet.textContent.includes('User1 changed the accessories list'));
          assert(sheet.textContent.includes('Nothing was saved'));
          button(sheet, 'Load the latest and re-apply my changes').click(); await settle();
          const again = bodies[1];
          assert.equal(again.sha256, 'e'.repeat(64));
          assert.equal(again.row.name, 'Matte Dual');          // mine
          assert.equal(again.row.colour, 'jet black');         // theirs
          assert.equal(again.row.quantity, 100);
          assert.equal(again.image, 'keep');
          assert.equal(sheets().length, 0);
          assert(main.textContent.includes('Dragon Shield Matte Dual saved.'));
        """)

    def test_accessory_conflict_clash_and_removed_row(self):
        self.run_js(self.ACCESSORIES + """
          const out = rebaseAccessory({...accBase(otterSleeves), name: 'Mine'}, accBase(otterSleeves),
            {...accBase(otterSleeves), name: 'Theirs', notes: 'n'});
          assert.equal(out.row.name, 'Mine'); assert.equal(out.row.notes, 'n');
          same(out.clashes, [{key: 'name', mine: 'Mine', theirs: 'Theirs'}]);
          // Removing a row someone else removed first: "Already removed", and the latest list shows.
          clear(main);
          const view = drawAccessories(data, routeToken);
          const latest = {...data, sha256: 'f'.repeat(64), items: [otterSleeves]};
          apiWrite = async () => { throw new ApiError(409, 'Changed.', {conflict: {reason: 'deleted'}, latest}); };
          const done = removeAccessory(view, box); await settle();
          button(sheets()[0], 'Remove').click(); await done;
          assert(main.textContent.includes('Already removed.'));
          assert(!main.textContent.includes('2 boxes'));
        """)

    def test_kit_picker_shares_or_moves_sleeves_and_kit_chip_words(self):
        self.run_js(self.ACCESSORIES + """
          same(kitChip({sleeves: {state: 'text', value: 'red'}}).textContent, 'Not in the accessories list');
          same(kitChip({sleeves: {state: 'linked', quantity: 60}, need: 75, short: 15, spare: 0}).textContent,
            '15 sleeves short');
          same(kitChip({sleeves: {state: 'linked', quantity: 100}, need: 75, short: 0, spare: 25}).textContent,
            '75 needed · 100 owned · 25 spare');
          assert.equal(kitChip({sleeves: null}), null);
          assert.equal(accessoryThumb({label: 'Matte', image_url: '//elsewhere/x.png'}, 32).querySelector('img'), null);
          assert(accessoryThumb({label: 'Matte', image_url: '/accessory-img/x.png?v=1'}, 96).querySelector('img'));
          api = async (path) => { assert.equal(path, '/api/accessories'); return data; };
          let sent = null, picked = null;
          apiWrite = async (path, body) => { sent = {path, body};
            return {data, holder: {}, warnings: []}; };
          const sheet = kitPicker({holder: 'casual/gruul', field: 'sleeves', need: 60, title: 'Gruul',
            onPicked: (answer) => { picked = answer; }});
          await settle();
          // E8-S20: sleeves another deck has can be shared as they are; the tile says who else uses them.
          assert(sheet.dialog.textContent.includes('Also used by Izzet Otters'));
          assert(!sheet.dialog.textContent.includes('In use'));
          assert(sheet.dialog.textContent.includes('60 needed · 60 owned'));
          const tileIn = (s) => s.dialog.querySelectorAll('button')
            .find(b => b.textContent.includes('Dragon Shield Matte (black)'));
          assert.equal(tileIn(sheet).getAttribute('data-taken'), null);
          tileIn(sheet).click(); await settle();
          let askSheet = sheets()[1]; assert(askSheet.textContent.includes('Use Dragon Shield Matte (black) here too?'));
          button(askSheet, 'Use them here too').click(); await settle();
          same(sent, {path: '/api/accessories/assign', body: {holder: 'casual/gruul', field: 'sleeves', id: 'ds-black',
            holder_sha256: 'd'.repeat(64)}});
          assert(picked); assert.equal(sheets().length, 0);
          // Move them here (E8-S08) is still offered beside sharing, for a holder the viewer can see.
          sent = null; picked = null;
          const again = kitPicker({holder: 'casual/gruul', field: 'sleeves', need: 60, title: 'Gruul',
            onPicked: (answer) => { picked = answer; }});
          await settle();
          tileIn(again).click(); await settle();
          askSheet = sheets()[1];
          button(askSheet, 'Move them here').click(); await settle();
          same(sent, {path: '/api/accessories/assign', body: {holder: 'casual/gruul', field: 'sleeves', id: 'ds-black',
            holder_sha256: 'd'.repeat(64), move_from: 'casual/izzet-otters'}});
          assert(picked); assert.equal(sheets().length, 0);
          // Only a holder the viewer can't see: still warned (Matt, 2026-10-19), named only as hers, with no move.
          sent = null;
          otterSleeves.used_by = [{holder: null, title: "one of User1's decks", kind: 'deck', need: 75}];
          const hidden = kitPicker({holder: 'casual/gruul', field: 'sleeves', need: 60, title: 'Gruul'});
          await settle();
          assert(hidden.dialog.textContent.includes("Also used by one of User1's decks"));
          tileIn(hidden).click(); await settle();
          askSheet = sheets()[1];
          assert(askSheet.textContent.includes("one of User1's decks uses these sleeves already"));
          assert.equal(button(askSheet, 'Move them here'), undefined);
          assert.equal(sent, null);
          button(askSheet, 'Cancel').click(); await settle();
          assert.equal(sent, null);
          tileIn(hidden).click(); await settle();
          button(sheets()[1], 'Use them here too').click(); await settle();
          same(sent, {path: '/api/accessories/assign', body: {holder: 'casual/gruul', field: 'sleeves', id: 'ds-black',
            holder_sha256: 'd'.repeat(64)}});
          assert.equal(sheets().length, 0);
        """)
