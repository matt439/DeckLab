"""Load the complete page in its real script order and exercise feature joins.

Uses an event/DOM double, not a browser or real inventory writes. The Collection, the routes, the
Packing plan, the kit on library cards and the deck page, and History are here; the Sleeves & boxes
page is in test_feature_ui_accessories and the token pieces in test_feature_ui_tokens, which run
their scenarios through FeatureUiTests.run_js.
"""
import json
import subprocess
import unittest
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


@unittest.skipUnless(NODE, "Node.js isn't installed")
class FeatureUiTests(unittest.TestCase):
    def run_js(self, code):
        setup = """
          const featureTicks = new Set();
          const featureApi = apiWrite;
          apiWrite = async (path,body,...rest) => {
            if (path !== '/api/assembly/ticks') return featureApi(path,body,...rest);
            for (const change of body.changes || []) {
              if (change.done) featureTicks.add(change.id); else featureTicks.delete(change.id);
            }
            return {ticks:body.ids.filter(id => featureTicks.has(id))};
          };
          const packingSettle = async () => { for (let i=0;i<32;i++) await null; };
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_scripts_load_and_collection_card_opens_inspector(self):
        self.run_js("""
          clear(main);
          drawCollection({types:['Creature'],roles:['ramp'],total:1,page:1,pages:1,note:'',warnings:[],
            cards:[{name:'Alpha',owned:3,incoming:1,held:1,free_now:2,holders:[],card:alpha}]},new URLSearchParams());
          const card = main.querySelector('.card-tile-open'); assert(card);
          assert.equal(card.getAttribute('data-viewer'), 'collection');
          card.fire('click'); assert.equal(inspections.length,1); assert.equal(changes,0);
          assert(main.textContent.includes('3 owned · 2 free'));
          assert(main.textContent.includes('1 on the way'));
          assert(main.textContent.includes('×3'));
        """)

    def test_card_list_rows_fold_only_the_unusual_facts_on_a_phone(self):
        self.run_js("""
          const cv = {pictures: {}, editable: false};
          const meta = (row) => colRowLine(cv, {name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'nonfoil',
            quantity: 1, notes: '', ...row}).querySelector('.col-cell-meta').textContent;
          assert(!meta({condition: 'NM', language: 'en'}).includes('NM'));
          assert(!meta({condition: 'NM', language: 'en'}).includes('en'));
          assert(meta({condition: 'LP', language: 'en'}).includes('Lightly Played'));
          assert(meta({condition: '', language: ''}).includes('Condition not recorded'));
          assert(meta({condition: '', language: ''}).includes('Language not recorded'));
          // The "not recorded" choice is unticked when its filter is reset (no such rows any more).
          const box = el('input', {type: 'checkbox'}); box.checked = true;
          const rows = {list: el('div'), rows: [{name: 'Alpha', set: 'fdn', collector_number: '1', finish: 'nonfoil',
            quantity: 1, condition: 'NM', language: 'en', notes: ''}], unrecordedLabel: el('span'),
            unrecordedChoice: el('label'), unrecorded: box, count: el('p'), sort: {key: 'name', dir: 1}, page: 1,
            search: '', unrecordedOnly: true, editable: false, pictures: {}, busy: false};
          drawColRowList(rows);
          assert.equal(rows.unrecordedOnly, false); assert.equal(box.checked, false);
        """)

    def test_library_filter_and_feature_routes_are_reachable(self):
        self.run_js("""
          clear(main); state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
          drawLibrary({warnings:[],halves:[],decks:[]},libraryFilters(new URLSearchParams('readiness=ready')));
          // The nine-button row is gone: the shell's nav (core.js's ROUTES) has every page, under one name each.
          for(const name of ['Accessories','Plan decks','Played games','Activity']) assert(!main.textContent.includes(name), name);
          same([...navRoutes('main'), ...navRoutes('more')].map(r => r.label),
            ['Decks','Collection','Shopping','Matchups','Tokens','Sleeves & boxes','Build decks','Game log','Wishlist','Activity']);
          assert.equal(main.querySelector('#filter-readiness').value,'ready');
          let seen=[];
          showCollection=()=>seen.push('collection'); showAssembly=()=>seen.push('assembly');
          showPlay=()=>seen.push('play'); showHistory=()=>seen.push('history'); showReceipt=()=>seen.push('receipt');
          showAccessories=()=>seen.push('accessories'); showTokens=()=>seen.push('tokens');
          showActivity=()=>seen.push('activity');
          editor=null;
          for(const hash of ['#/collection','#/assembly','#/play','#/history?id=casual/a','#/receipt?order=a',
                             '#/accessories','#/tokens','#/activity']) {
            location.hash=hash; route();
          }
          same(seen,['collection','assembly','play','history','receipt','accessories','tokens','activity']);
        """)

    def test_assembly_verified_single_sided_token_label(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const deck = {id:'casual/a',title:'A',version:'target',sleeves:null,kit:null,sleeves_need:null,steps:[],
            basics:[],returns:[],tokens:null};
          drawAssembly({choices:[],decks:[deck],rows:[],ready:false,counts_confirmed:true,unresolved:[],warnings:[],
            note:'',token_note:'',totals:{waiting:0,missing:0},token_plan:[],token_problems:[],
            tokens:[{quantity:1,front:'The Monarch',back:'',notes:'single-sided verified'}]},routeToken);
          assert(main.textContent.includes('single-sided (verified)'));
          assert(!main.textContent.includes('reverse not recorded'));
        """)

    def test_assembly_notes_decks_in_the_same_sleeves(self):
        # E8-S20: decks chosen together in one design of sleeves get a note, never a warning box.
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const deck = (id, title) => ({id, title, version:'target', sleeves:null, kit:null, sleeves_need:null,
            need:{}, current:[], basics:[], steps:[], returns:[], tokens:null});
          const words = 'A and B are both in KMC Katana (Black) sleeves: their cards look the same from the back, '
            + "so keep each deck's cards together.";
          drawAssembly({choices:[],rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],
            note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[],
            sleeve_notes:[{sleeves:'KMC Katana (Black)', decks:[{id:'casual/a',title:'A'},{id:'casual/b',title:'B'}],
              note: words}],
            decks:[deck('casual/a','A'), deck('casual/b','B')]},routeToken);
          const shown = main.querySelector('.pack-sleeve-notes');
          assert(shown); assert.equal(shown.textContent, words);
          assert.equal(shown.querySelectorAll('.box-warn').length, 0);
          assert.equal(main.querySelectorAll('.box-warn').length, 0);
          clear(main);
          drawAssembly({choices:[],rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],
            note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[],sleeve_notes:[],
            decks:[deck('casual/a','A')]},routeToken);
          assert.equal(main.querySelector('.pack-sleeve-notes'), null);
        """)

    def test_assembly_kit_row_ticks_and_short_warning(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const sleeves = {value:'ds-black',id:'ds-black',kind:'sleeves',state:'linked',quantity:60,image_url:null,
            label:'Dragon Shield Matte (black)'};
          const box = {value:'ug-boulder',id:'ug-boulder',kind:'deck_box',state:'linked',quantity:1,image_url:null,
            label:'Ultimate Guard Boulder 100+ (black)'};
          const short = 'Not enough sleeves: this deck needs 75 and Dragon Shield Matte (black) has 60.';
          const deck = (id, title, kit, words) => ({id, title, version:'target', sleeves: words, kit,
            sleeves_need: kit ? kit.need : null, need: {}, current: [], basics: [], steps: [], returns: [], tokens: null});
          drawAssembly({choices:[],rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],
            note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[],
            decks:[deck('casual/otters','Otters',{sleeves,deck_box:box,need:75,short:15,spare:0,warnings:[short],info:[]},
                        'Dragon Shield Matte (black)'),
                   deck('casual/gruul','Gruul',{sleeves:{value:'red',id:null,state:'text',label:'red'},deck_box:null,
                        need:60,short:0,spare:0,warnings:[],info:[]}, 'red'),
                   deck('casual/none','None',null,'Not recorded')]},routeToken);
          const text = main.textContent;
          for (const words of ['Sleeve with Dragon Shield Matte (black): 75 needed, 60 owned', short,
                               'Get out 75 Dragon Shield Matte (black) sleeves',
                               'Pack into Ultimate Guard Boulder 100+ (black)',
                               'Sleeves: “red” (not in the accessories list), 60 needed',
                               'Get out 60 “red” sleeves', 'Sleeves: Not recorded']) {
            assert(text.includes(words), words);
          }
          assert(main.querySelectorAll('a').some(a => a.getAttribute('href') === '#/accessories'));
          assert.equal(main.querySelectorAll('.assembly-kit').flatMap(k => k.querySelectorAll('.box-warn')).length, 1);
          // No sleeves recorded on a deck that isn't built: a way to the deck, not a picker.
          const none = main.querySelectorAll('.assembly-kit')[2];
          assert.equal(none.querySelector('a').getAttribute('href'), '#/deck?id=casual%2Fnone&v=target');
        """)

    def test_assembly_not_recorded_sleeves_on_a_built_deck_open_the_picker(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const picked = [];
          kitPicker = (opts) => { picked.push(opts); };
          const deck = {id:'casual/gruul',title:'Gruul',version:'target',sleeves:'Not recorded',kit:{sleeves:null,deck_box:null,
            need:60,warnings:[]},sleeves_need:60,steps:[],basics:[],returns:[],tokens:null};
          drawAssembly({choices:[{id:'casual/gruul',title:'Gruul',status:'built',versions:['target']}],rows:[],ready:true,
            counts_confirmed:true,unresolved:[],warnings:[],note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],
            token_plan:[],decks:[deck]},routeToken);
          const choose = main.querySelector('.assembly-kit').querySelector('button');
          assert.equal(choose.textContent, 'Choose sleeves');
          choose.click();
          same(picked.map(o => [o.holder, o.field, o.need, o.title]), [['casual/gruul', 'sleeves', 60, 'Gruul']]);
        """)

    def test_packing_plan_steps_tiles_progress_and_shared_ticks(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const saved = {};
          window.localStorage = {getItem: k => (k in saved ? saved[k] : null), setItem: (k, v) => { saved[k] = String(v); },
            removeItem: k => { delete saved[k]; }};
          const card = name => ({name, type_line:'Creature', mana_cost:'', img:`/img/x/${name}/normal`, img_small:`/img/x/${name}/small`});
          const deck = {id:'casual/b',title:'B',version:'target',sleeves:null,kit:null,sleeves_need:null,tokens:null,
            steps:[{name:'Elves',keep:1,storage:2,transfers:[],waiting:0,missing:0},
                   {name:'Bolt',keep:0,storage:0,transfers:[{from:'casual/a',from_title:'A',quantity:1}],waiting:1,missing:1}],
            basics:[{name:'Forest',quantity:20}], returns:[{name:'Old',quantity:1}]};
          const data = {choices:[{id:'casual/a',title:'A',status:'built',versions:['target']},
                                 {id:'casual/b',title:'B',status:'building',versions:['target','owned']}],
            decks:[deck],rows:[],ready:false,counts_confirmed:true,unresolved:[],warnings:[],note:'A plan.',token_note:'',
            totals:{waiting:1,missing:1},tokens:[],token_plan:[],cards:{Elves:card('Elves'),Bolt:card('Bolt'),Forest:card('Forest')}};
          drawAssembly(data, routeToken); await packingSettle();
          const steps = main.querySelectorAll('.pack-step');
          same(steps.map(s => s.querySelector('.pack-step-n').textContent), ['1','2','3','4','5']);
          assert(steps.every(s => s.querySelector('.pack-step-n').getAttribute('aria-hidden') === 'true'));
          same(steps.map(s => s.querySelector('.pack-step-spoken').textContent),
            ['Step 1. ', 'Step 2. ', 'Step 3. ', 'Step 4. ', 'Step 5. ']);
          const titles = ['Sleeves', 'Pull from storage (2 cards)', 'Move from other decks (1 card)',
            'Basic lands (20 cards)', 'Put back (1 card)'];
          assert(steps.every((s, i) => s.querySelector('h3').textContent.endsWith(titles[i])));
          // Kept and still-waiting cards are folded, never ticks.
          const folds = main.querySelectorAll('.pack-fold');
          assert(folds[0].textContent.includes('Already in this deck (1 card)'));
          assert(folds[1].textContent.includes('Wait for 1 × Bolt'));
          assert(folds[1].textContent.includes('Unavailable: 1 × Bolt'));
          // Every tile opens the viewer over the whole plan.
          const tiles = main.querySelectorAll('.card-tile');
          assert.equal(tiles.length, 4);
          assert(tiles.every(t => t.querySelector('.card-tile-open') === null
            || t.querySelector('.card-tile-open').getAttribute('data-viewer') === 'packing' || t.textContent.includes('Old')));
          assert(tiles[1].textContent.includes('From A'));
          // The bar counts copies (short words on a phone, for one line); a tick is kept for this plan and comes
          // back when it's drawn again.
          const progress = () => main.querySelector('.pack-progress-long').textContent;
          assert.equal(progress(), 'Pulled 0 of 24 cards');
          assert.equal(main.querySelector('.pack-copy-figure').textContent, '0 / 24');
          const clearTicks = () => main.querySelector('.pack-clear');
          assert.equal(clearTicks().getAttribute('aria-label'), 'Clear ticks');
          assert.equal(clearTicks().disabled, true);
          tiles[0].querySelector('.pack-tick').click(); await packingSettle();
          assert.equal(tiles[0].querySelector('.pack-tick').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 2 of 24 cards');
          assert.equal(clearTicks().disabled, false);
          assert.equal(featureTicks.size,1); assert.equal(saved['decklab.packing.casual/b:target'],undefined);
          clear(main); drawAssembly(data, routeToken); await packingSettle();
          assert.equal(main.querySelector('.pack-tick').getAttribute('aria-pressed'), 'true');
          assert.equal(progress(), 'Pulled 2 of 24 cards');
          // Clear takes every tick off, with Undo to put them back.
          let undo = null; showToast = (text, opts) => { undo = opts.undo; return {close() {}}; };
          clearTicks().click(); await packingSettle();
          assert.equal(progress(), 'Pulled 0 of 24 cards');
          assert.equal(saved['decklab.packing.casual/b:target'], undefined);
          undo(); await packingSettle();
          assert.equal(progress(), 'Pulled 2 of 24 cards');
          assert.equal(featureTicks.size,1); assert.equal(saved['decklab.packing.casual/b:target'],undefined);
          // Tasks stay unchanged while a different deck choice is being worked out.
          const box = main.querySelectorAll('input').find(b => b.parentNode.textContent === 'A');
          box.checked = true; box.fire('change');
          main.querySelectorAll('.pack-tick')[1].click();
          assert.equal(saved['decklab.packing.casual/a:target,casual/b:target'], undefined);
          assert.equal(featureTicks.size,1);
          // Storage that throws (a private window) never breaks shared progress.
          featureTicks.clear();
          window.localStorage = {getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); },
            removeItem() { throw new Error('blocked'); }};
          clear(main); drawAssembly(data, routeToken); await packingSettle();
          main.querySelector('.pack-tick').click(); await packingSettle();
          assert.equal(progress(), 'Pulled 2 of 24 cards');
        """)

    def test_packing_plan_decks_come_from_a_checklist(self):
        self.run_js("""
          window.matchMedia('(min-width: 1000px)').matches = true;
          clear(main);
          const posts = [];
          apiWrite = async (path, body) => { posts.push([path, body]); return {decks:[],rows:[],ready:false,
            counts_confirmed:true,unresolved:[],warnings:[],note:'',token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[]}; };
          const choices = [{id:'casual/a',title:'A',status:'built',versions:['target']},
            {id:'casual/b',title:'B',status:'building',versions:['target','owned']},
            {id:'casual/c',title:'C',status:'idea',versions:['target']},
            {id:'product/p/x',title:'X',versions:['target']}];
          drawAssembly({choices,decks:[],rows:[],ready:false,counts_confirmed:true,unresolved:[],warnings:[],note:'',
            token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[]},routeToken);
          // Nothing chosen: one line and the one action.
          assert(main.querySelector('.empty').textContent.includes('Choose the decks you want to play.'));
          // Built and being built are open; ideas and products are folded.
          same(main.querySelectorAll('.pack-group').map(g => g.tag), ['div', 'div', 'details', 'details']);
          const chooser = main.querySelector('.pack-choose');
          assert.equal(chooser.tag,'section');assert(!main.querySelector('.pack-show-plan'));
          // On a phone the same chooser moves into a sheet; choosing a preset keeps it open.
          const media=window.matchMedia('(min-width: 1000px)');media.matches=false;media.fire('change');
          main.querySelector('.pack-chooser-launcher').click();
          const sheet=document.body.querySelector('dialog');assert(sheet.contains(chooser));
          chooser.querySelectorAll('button').find(b => b.textContent === 'Built and being built').click();
          assert(sheet.isConnected);assert(sheet.contains(chooser));
          flushTimers(); await null; await null;
          same(posts.at(-1), ['/api/assembly/preview', {decks:[{id:'casual/a',version:'target'},{id:'casual/b',version:'target'}]}]);
          assert(chooser.querySelector('.pack-choose-count').textContent.includes('2 chosen'));
          sheet.querySelector('.pack-show-plan').click();assert(!sheet.isConnected);
          assert(!chooser.isConnected);assert(document.activeElement===main.querySelector('.pack-chooser-launcher'));
          media.matches=true;media.fire('change');assert(main.contains(chooser));
          // A deck with two lists offers them once it's chosen.
          const play = main.querySelectorAll('button').find(b => b.textContent === 'Play-now list');
          play.click(); flushTimers(); await null; await null;
          same(posts.at(-1)[1].decks[1], {id:'casual/b',version:'owned'});
          // Unticking a deck takes it out.
          const boxes = main.querySelectorAll('input');
          boxes[0].checked = false; boxes[0].fire('change'); flushTimers(); await null; await null;
          same(posts.at(-1)[1].decks, [{id:'casual/b',version:'owned'}]);
        """)

    def test_library_cards_show_their_kit(self):
        self.run_js("""
          clear(main); state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
          const kit = {sleeves:{name:'Dragon Shield Matte (black)',image_url:'/accessory-img/ds.jpg?v=1',state:'linked'},
            deck_box:{name:'red box',image_url:null,state:'text'},short:15};
          const product = {sleeves:{name:'Katana (blue)',image_url:null,state:'linked'},deck_box:null,short:0};
          const none = {sleeves:null,deck_box:null,short:0};
          const base = {format:'Casual 60',kind:'casual',player:'user',status:'built',versions:['target'],
            missing:{target:0},on_the_way:{target:0},card_count:60,sideboard_count:0};
          drawLibrary({warnings:[],halves:[],decks:[
            {...base,id:'casual/otters',title:'Otters',kit},
            {...base,id:'casual/gruul',title:'Gruul',kit:none},
            {...base,id:'product/la/lightning-aggro',title:'Lightning Aggro (Challenger 2019)',read_only:true,
             kind:'product',kit:product}]},libraryFilters(new URLSearchParams('all=1')));
          const cards = main.querySelectorAll('.deck-card');
          const otters = cards.find(c => c.textContent.includes('Otters'));
          for (const words of ['Sleeves Dragon Shield Matte (black)','15 sleeves short','Deck box red box'])
            assert(otters.textContent.includes(words), words);
          assert(otters.querySelector('img'));
          assert.equal(cards.find(c => c.textContent.includes('Gruul')).querySelector('.deck-sleeve'), null);
          // A product's kit is on its heading once, not on its deck's card.
          const group = main.querySelectorAll('.product-group')[0];
          assert(group.querySelector('.product-sleeve').textContent.includes('Katana (blue)'));
          assert.equal(group.querySelector('.deck-card').querySelector('.deck-sleeve'), null);
        """)

    def test_deck_page_kit_strip_and_choose(self):
        self.run_js("""
          clear(main); state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
          const settle = async () => { for (let i = 0; i < 30; i++) await null; };
          const info = '“red” isn’t in the accessories list, so Deck Lab can’t check there are enough.';
          const summary = {id:'casual/otters',title:'Otters',format:'Casual 60',kind:'casual',player:'user',
            status:'built',card_count:60,sideboard_count:15,sleeves:'red',holder_sha256:'c'.repeat(64),
            kit:{holder:'casual/otters',title:'Otters',sleeves:{value:'red',id:null,state:'text',label:'red',image_url:null},
              deck_box:null,need:75,short:0,spare:0,warnings:[],info:[info]}};
          const page = {summary, versions:['target'], version:'target', info: [info]};
          let head = deckKit(page); main.append(head);
          const text = head.textContent;
          for (const words of ['Sleeves','“red”','Not in the accessories list','Deck box','None chosen', info])
            assert(text.includes(words), words);
          let opened = null;
          kitPicker = (options) => { opened = options; };
          const labelled = (root, label) => root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === label);
          labelled(head, 'Choose sleeves for Otters').click();
          same([opened.holder, opened.field, opened.need, opened.holderSha, opened.current.value],
               ['casual/otters','sleeves',75,'c'.repeat(64),'red']);
          assert(labelled(head, 'Choose a deck box for Otters'));
          // An unbuilt editable deck explains when kit is chosen (E8-S05).
          clear(main);
          assert(deckKit({...page, summary: {...summary, status: 'building'}}).textContent.includes('Choose sleeves and a deck box when you mark this deck built'));
          // A product gets Choose… once the accessories list says it's kept intact.
          clear(main);
          api = async (path) => { assert.equal(path, '/api/accessories');
            return {holders_options:[{id:'product/la',title:'Lightning Aggro',kind:'product',need:75}]}; };
          const product = {...summary, id:'product/la/lightning-aggro', read_only:true, status:'', holder_sha256:'b'.repeat(64),
            kit:{...summary.kit, holder:'product/la', title:'Lightning Aggro', sleeves:null, info:[]}};
          head = deckKit({...page, summary: product, info: []}); main.append(head);
          assert(!labelled(head, 'Choose sleeves for Lightning Aggro'));
          await settle();
          labelled(head, 'Choose sleeves for Lightning Aggro').click();
          same([opened.holder, opened.holderSha], ['product/la/lightning-aggro', 'b'.repeat(64)]);
        """)

    def test_history_lists_numbered_revisions(self):
        # Each revision says what it changed against the one before it (the server's change), with the changed
        # cards' pictures opening the card viewer; saves without card changes fold; a sheet opens per revision.
        self.run_js("""
          clear(main); state.profile={id:'matt'};
          const shock = {name:'Shock', type_line:'Instant', mana_cost:'{R}', img_small:'/img/m19/156/small'};
          const gnaw = {name:'Rabid Gnaw', type_line:'Instant', mana_cost:'{1}{R}', img_small:'/img/woe/147/small'};
          const none = {kind:'none', cards:[], more:0, fields:[], size:{target:60, owned:null}, lists:[]};
          const data = {id:'casual/a', title:'A', revisions:[
            {revision:5, date:'2026-10-07T08:21:15+10:00', op:'D', actor:'matt', author:'Matt', subject:'Retire A',
             commit:null, change:{...none, kind:'deleted', size:null}},
            {revision:4, date:'2026-10-06T09:00:00+10:00', op:'M', actor:'user1', author:'User1', subject:null,
             commit:null, change:{kind:'cards', more:0, lists:['target'], size:{target:60, owned:null},
               fields:[{key:'Status', before:'building', after:'built'}],
               cards:[{list:'target', section:'Deck', name:'Rabid Gnaw', delta:2, printing:false, card:gnaw},
                      {list:'target', section:'Deck', name:'Shock', delta:-1, printing:false, card:shock}]}},
            {revision:3, date:'2026-10-05T10:00:00+10:00', op:'M', actor:'matt', author:'Matt',
             subject:'receive 2026-10-05-shop-c', commit:null, change:none},
            {revision:2, date:'2026-10-05T09:00:00+10:00', op:'M', actor:'matt', author:'Matt', subject:'Notes',
             commit:null, change:none},
            {revision:1, date:'2026-10-01T09:00:00+10:00', op:'A', actor:'claude', author:'Claude', subject:'Add A',
             commit:'abcdef1', change:{...none, kind:'created'}}]};
          const old = {sections:{Deck:[]}, current:{lists:{target:{Deck:[]}}}, fields:{}, warnings:[]};
          let asked = null;
          const settle = async () => { for (let i = 0; i < 30; i++) await null; };
          load=(path,token,draw)=>draw(data); canBuildDecks=()=>true;
          api = async (path) => { asked = path; return old; };
          showHistory(new URLSearchParams('id=casual/a'), routeToken);
          assert.equal(main.querySelector('h1').textContent, 'History');
          const heads = main.querySelectorAll('.history-headline');
          same(heads.map(h => h.textContent), ['Deleted the deck', 'Changed the planned list and marked it built',
            'Created the deck']);
          assert.equal(heads[0].tag, 'span');                     // a deleted revision has no list to open
          assert(main.textContent.includes('+2 Rabid Gnaw, −1 Shock'));
          assert(main.textContent.includes('Status: building → built'));
          assert(main.textContent.includes('60 cards in the planned list'));
          assert(!main.textContent.includes('(message private)'));
          // The two saves without card changes fold into one line, their messages inside.
          const fold = main.querySelector('.history-fold');
          assert.equal(fold.querySelector('summary').textContent, '2 saves without card changes');
          // Subjects arrive already filtered by the server; the page applies no command mask.
          same(fold.querySelectorAll('.history-folded-row').map(b => b.querySelector('.history-subject').textContent),
            ['receive 2026-10-05-shop-c', 'Notes']);
          assert.equal(historySubject({subject:'Tables refreshed'}), 'Tables refreshed');
          assert.equal(historySubject({subject:'order.add example'}), 'order.add example');
          // The pictures open the viewer over this revision's cards.
          const pics = main.querySelectorAll('.history-pic');
          assert.equal(pics.length, 2);
          assert.equal(pics[0].getAttribute('data-viewer'), 'history-4');
          assert.equal(pics[1].getAttribute('aria-label'), '−1 Shock: show the card');
          pics[1].click();
          assert.equal(inspections.at(-1).card.name, 'Shock');
          // The sheet: every change, the comparison when asked for, and the draft for the planned list.
          heads[2].click(); await settle();
          const sheet = document.body.querySelectorAll('dialog').at(-1);
          assert(sheet.textContent.includes('Revision 1 (git abcdef1)'));
          const compare = sheet.querySelector('details');
          assert.equal(asked, null);                              // nothing fetched until it's opened
          compare.open = true; compare.fire('toggle'); await settle();
          assert(asked.endsWith('&revision=1'));
          assert(sheet.textContent.includes('The cards match the deck now.'));
          const draft = sheet.querySelectorAll('button').find(b => b.textContent === 'Open planned list as a draft');
          assert(draft.getAttribute('class').includes('btn-primary'));
          draft.click();
          assert(location.hash.endsWith('&revision=1'));
          // A phone has the editor too (the Quick edit), so restoring is offered there as well.
          canBuildDecks=()=>false;
          main.querySelectorAll('.history-headline')[1].click();
          const small = document.body.querySelectorAll('dialog').at(-1);
          assert(!small.textContent.includes('open this page on a tablet or computer'));
          assert.equal(small.querySelectorAll('button').filter(b => b.textContent.includes('as a draft')).length, 1);
          assert(small.textContent.includes('+2'));
        """)

    def test_history_moves_badges_more_tiles_and_who_may_restore(self):
        # A card moved between sections reads as one move; pictures mark the sideboard; a strip that can't show every
        # change ends in a "+N" tile opening the sheet; restoring is offered only to someone who may save the deck.
        self.run_js("""
          clear(main); state.profile={id:'user1'};
          const card = (name) => ({name, type_line:'Instant', mana_cost:'{G}', img_small:`/img/x/${name.length}/small`});
          const many = Array.from({length: 10}, (_, i) => ({list:'target', section:'Deck', name:`Card ${i}`, delta:1,
            printing:false, card:card(`Card ${i}`)}));
          const data = {id:'casual/a', title:'A', may_save:false, revisions:[
            {revision:3, date:'2026-10-06T09:00:00+10:00', op:'M', actor:'matt', author:'Matt', subject:'Tune', commit:null,
             change:{kind:'cards', more:0, more_by_list:{}, lists:['target'], size:{target:60, owned:null}, fields:[],
               cards:[{list:'target', section:'Deck', name:'Second Breakfast', delta:-1, printing:false, card:card('Second Breakfast')},
                      {list:'target', section:'Sideboard', name:'Second Breakfast', delta:1, printing:false, card:card('Second Breakfast')},
                      {list:'target', section:'Sideboard', name:'Shock', delta:2, printing:false, card:card('Shock')}]}},
            {revision:2, date:'2026-10-05T09:00:00+10:00', op:'M', actor:'matt', author:'Matt', subject:null, commit:null,
             change:{kind:'cards', more:3, more_by_list:{owned:3}, lists:['target', 'owned'], size:{target:60, owned:50},
               fields:[], cards:many}},
            {revision:1, date:'2026-10-01T09:00:00+10:00', op:'A', actor:'matt', author:'Matt', subject:'Add A', commit:null,
             change:{kind:'unreadable_before', cards:[], more:0, fields:[], lists:[], size:{target:60, owned:null}}}]};
          const settle = async () => { for (let i = 0; i < 30; i++) await null; };
          load=(path,token,draw)=>draw(data); canBuildDecks=()=>true;
          showHistory(new URLSearchParams('id=casual/a'), routeToken);
          const revs = main.querySelectorAll('.history-rev');
          assert(revs[0].textContent.includes('1 Second Breakfast → sideboard, +2 Shock (sideboard)'));
          same(revs[0].querySelectorAll('.history-delta').map(b => b.textContent), ['→SB', '+2 SB']);
          // The planned list's line is whole, and the play-now list's changes past the cap still get a line.
          assert(revs[1].textContent.includes('+1 Card 0'));
          assert(revs[1].textContent.includes('Play-now list: 3 card changes'));
          const tile = revs[1].querySelector('.history-pic-more');
          assert(tile);
          assert.equal(tile.querySelector('.history-more-phone').textContent, '+6 more changes');   // 7 shown on a phone
          assert.equal(revs[1].querySelector('.history-pictures').getAttribute('class').includes('history-pictures-cut'), true);
          assert.equal(revs[1].querySelector('.history-more-wide').textContent, '+3 more changes');  // 10 of 13 shown wider
          tile.click(); await settle();
          let sheet = document.body.querySelectorAll('dialog').at(-1);
          assert(sheet.textContent.includes('Card 9'));
          // Someone who may not save the deck gets neither the draft action nor a note about it.
          assert.equal(sheet.querySelectorAll('button').filter(b => b.textContent.includes('as a draft')).length, 0);
          assert(!sheet.textContent.includes('Restoring a list'));
          canBuildDecks=()=>false;
          revs[0].querySelector('.history-open').click();
          sheet = document.body.querySelectorAll('dialog').at(-1);
          assert(!sheet.textContent.includes('Restoring a list'));
          assert(sheet.textContent.includes('Moved from the main deck to the sideboard'));
          same(main.querySelectorAll('.history-headline').map(h => h.textContent).slice(2),
            ['Saved the deck (the save before it can’t be read)'.replace('’', "'")]);
          // Someone who may: the draft where the editor opens (canBuildDecks, as #/edit's route).
          data.may_save = true; canBuildDecks=()=>true;
          revs[0].querySelector('.history-open').click();
          sheet = document.body.querySelectorAll('dialog').at(-1);
          assert.equal(sheet.querySelectorAll('button').filter(b => b.textContent === 'Open planned list as a draft').length, 1);
        """)

    def test_history_opens_draft_against_current_hash_and_respects_existing_draft(self):
        self.run_js("""
          clear(main); state.profile={id:'matt'};
          const old = {sections:{Deck:[{qty:4,name:'Alpha'}]},current:{editable:true,id:'casual/a',sha256:'current',
            lists:{target:{Deck:[{qty:3,name:'Alpha'}]}},fields:{status:'built'}}};
          let opened=0,saved=0,checked=0;
          load=(path,token,draw)=>draw(old); local.get=()=>null;
          startEditor=opts=>{ opened++; assert.equal(opts.view.sha256,'current'); assert.equal(opts.restoreDraft,false);
            editor={...opts,hasFileList:true,fields:{...opts.view.fields},base:{lists:opts.view.lists.target,fields:opts.view.fields}}; };
          syncSections=()=>{}; isDirty=()=>true; drawEditor=()=>{}; saveDraft=()=>{saved++;}; scheduleCheck=()=>{checked++;}; toast=()=>{};
          apiWrite=()=>{throw new Error('Restoring must not write a deck');};
          showRevisionEditor(new URLSearchParams('id=casual/a&revision=abc'),routeToken);
          assert.equal(opened,1); assert.equal(editor.lists.Deck[0].qty,4); assert.equal(editor.fields.status,'built');
          assert.equal(saved,1); assert.equal(checked,1);
          clear(main); local.get=()=>'{existing draft}';
          showRevisionEditor(new URLSearchParams('id=casual/a&revision=abc'),routeToken);
          assert.equal(opened,1); assert(main.textContent.includes('Keep my existing draft'));
          main.querySelector('button').fire('click'); assert.equal(opened,2);
        """)
