"""The Receipts page's check-off board (receipts.js, decklab/UI-REVIEW.md WP6) in a small DOM double: nothing is
received on open, ticks earn "Confirm: all N checked" (verified), the preview and the apply are separate and an
edit after the preview stops the apply, late answers are dropped, splits keep the order's totals, a token's back
must be confirmed, a product needs its choice, the check survives a reload, members see it read only, the tiles
open the card viewer as a group, and the success view says where the cards go."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

FIELDS = "['name','set','collector_number','finish','quantity','condition','language','notes']"
TOKEN_FIELDS = ("['front','back','set','front_collector_number','back_collector_number','finish','quantity',"
                "'front_details','back_details','notes']")


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ReceiptBoardTests(unittest.TestCase):
    def run_js(self, scenario, draw=True):
        setup = f"""
          clear(main); state.profile = {{id:'matt',name:'Matt'}}; state.may = null;
          const store = new Map();
          window.localStorage = {{ get length() {{ return store.size; }}, key: (i) => [...store.keys()][i] ?? null,
            getItem: (k) => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v)),
            removeItem: (k) => store.delete(k) }};
          const alphaCard = {{name:'Alpha',mana_cost:'{{G}}',type_line:'Creature',img:'/img/tst/1/normal',img_small:'/img/tst/1/small'}};
          const betaCard = {{name:'Beta',mana_cost:'{{U}}',type_line:'Instant',img:'/img/tst/2/normal',img_small:'/img/tst/2/small'}};
          const delivery = () => ({{order:'test',seller:'Fixture shop',ordered_on:'2026-10-01',notes:'',fingerprint:'a'.repeat(64),
            today:'2026-10-08',kits:{{'casual/a':{{sleeves:'Black matte'}}}},face_names:['Bird','Golem','Ooze'],
            components:[{{id:'cards',kind:'cards',status:'pending',checks:['Verify actual condition'],
              fields:{FIELDS},
              rows:[{{name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'2',condition:'',language:'',
                      notes:'condition and language not recorded; check on arrival'}},
                    {{name:'Beta',set:'tst',collector_number:'2',finish:'foil',quantity:'1',condition:'NM',language:'en',notes:''}}],
              pictures:[{{card:alphaCard,exact:true,why:null,set_name:'Test Set',finishes:['nonfoil','foil']}},
                        {{card:betaCard,exact:false,why:'not recorded',set_name:null,finishes:[]}}],
              decks:[[{{id:'casual/a',title:'Alpha Deck',status:'built',uses:1,waiting:1}}],[]]}}]}});
          const ready = {{ready:true,preview:'b'.repeat(32),components:['cards'],received_on:'2026-10-08',
            changes:["Home's collection"],totals:[['playable cards',{{cards:3,added_rows:2,bumped_rows:0}}]],
            tables:{{written:[{{id:'casual/a',title:'Alpha Deck'}}],skipped:[],error:null}}}};
          const body = () => document.body.textContent;
          const closeSheets = () => document.body.querySelectorAll('dialog').forEach((d) => d.remove());
          function tickAll(view) {{
            for (const comp of view.comps) {{ for (const row of comp.rows) rcptTick(view, comp, row, true);
              comp.checks = comp.checks.map(() => true); }}
            rcptSync(view);
          }}
          {"const view = drawReceipt(delivery(), routeToken);" if draw else ""}
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), setup + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_nothing_is_received_on_open_and_unticked_cards_block_the_preview(self):
        self.run_js("""
          let calls=0;apiWrite=async()=>{calls++;throw new Error('no write');};
          assert.equal(view.comps.length,1);assert(view.comps[0].selected);   // one part: chosen, no "This arrived" box
          assert(!main.textContent.includes('This arrived'));
          assert.equal(view.primary.textContent,'Preview');
          assert(main.textContent.includes('0/3 ✓'));assert(main.textContent.includes('1 check left'));
          await previewDelivery(view);assert.equal(calls,0);
          assert(body().includes('tick at least one card that arrived'));assert(body().includes('Check not ticked: Verify actual condition'));
          const at=body().indexOf('null');assert(at<0, body().slice(Math.max(0,at-80),at+40));
        """)

    def test_row_badges_stay_distinct_from_unequal_copy_progress_and_do_not_narrow_bulk_scope(self):
        self.run_js("""
          const d=delivery();d.components[0].rows[0].quantity='8';
          const v=drawReceipt(d,routeToken),comp=v.comps[0];
          assert(v.headProgress.textContent.includes('0 of 9 card copies checked'));
          assert.equal(comp.fillButton.textContent,'Apply to 1 row');
          const attention=comp.filterButtons.find(b=>b.getAttribute('data-filter')==='attention');
          assert.equal(attention.children[0].textContent,'Needs attention (2 rows)');
          assert.equal(attention.children[1].textContent,'Attention (2 rows)');
          const before=rcptRequestKey(v),rows=JSON.stringify(comp.rows.map(r=>r.values));
          rcptToolbarCounts(v,comp);rcptTools(v,comp,true);
          assert.equal(rcptRequestKey(v),before);assert.equal(JSON.stringify(comp.rows.map(r=>r.values)),rows);
          rcptTick(v,comp,comp.rows[0],true);v.filter='todo';rcptRefreshAll(v);
          assert(v.headProgress.textContent.includes('8 of 9 card copies checked'));
          assert(comp.rows[0].tile.hidden);assert.equal(comp.fillButton.textContent,'Apply to 1 row');
          rcptFillBlanks(v,comp,'LP','ja');
          assert.equal(comp.rows[0].values.condition,'LP');assert.equal(comp.rows[0].values.language,'ja');
          assert.equal(comp.rows[0].values.quantity,'8');assert.equal(comp.rows[1].values.quantity,'1');
          assert.equal(comp.rows[1].values.condition,'NM');assert.equal(comp.rows[1].values.language,'en');
          const selected=rcptRequest(v).components[0];same(selected.take,[{row:1}]);
          same(selected.rows.map(r=>[r.quantity,r.condition,r.language]),[['8','LP','ja'],['1','NM','en']]);
          assert(v.headProgress.textContent.includes('8 of 9 card copies checked'));
        """,draw=False)

    def test_the_board_shows_pictures_chips_and_the_tiles_open_the_viewer_as_a_group(self):
        self.run_js("""
          const tiles=main.querySelectorAll('.card-tile');assert.equal(tiles.length,2);
          const text=main.textContent;
          // What isn't set yet is one chip, not two; while no card has either, a line above the grid says it once.
          assert(text.includes('Condition, language ?'));assert(!text.includes('Language ?'));assert(text.includes('NM · EN'));
          assert(!main.querySelector('.rcpt-all-blank'));
          assert(rcptAllBlank({kind:'cards',rows:[{values:{}},{values:{condition:'',language:''}}]}));
          assert(!rcptAllBlank({kind:'cards',rows:[{values:{}},{values:{condition:'NM',language:''}}]}));
          assert(!rcptAllBlank({kind:'tokens',rows:[{values:{}},{values:{}}]}));
          assert(text.includes('TST 1 · Nonfoil'));assert(text.includes('Foil'));
          assert(text.includes('Default picture: printing not recorded'));
          assert(text.includes('For Alpha Deck ×1'));
          assert(main.querySelectorAll('[data-viewer=receipt-0]').length,2);
          assert.equal(main.querySelectorAll('.rcpt-tick').length,2);
          // A tap opens the sheet; its picture opens the viewer over the whole grid at this card.
          let opened=null;openCardViewer=(items,start,opts)=>{opened={items,start,opts};};
          view.comps[0].rows[1].open.click();
          assert(view.sheet);assert(body().includes('Different printing…'));
          document.body.querySelector('.rcpt-sheet-pic').click();
          assert.equal(opened.items.length,2);assert.equal(opened.start,1);assert.equal(opened.items[0].card.name,'Alpha');
        """)

    def test_inspection_picture_area_has_navigation_and_swipes_from_the_margin(self):
        self.run_js("""
          const comp = view.comps[0];
          comp.rows[0].open.click();
          const top = () => document.body.querySelector('.rcpt-sheet-top');
          const nav = () => document.body.querySelector('.rcpt-sheet-nav');
          assert.equal(nav().querySelectorAll('button')[0].disabled, true);
          assert.equal(document.body.querySelector('.rcpt-sheet-count').textContent, '1 / 2');
          assert(body().includes('Swipe left or right'));
          // Guidance must appear before the tall picture, within the sheet's initial viewport.
          assert.equal(top().children[0], nav());
          assert.equal(top().children[1], top().querySelector('.rcpt-sheet-hint'));
          assert.equal(top().children[2], top().querySelector('.rcpt-sheet-pic'));
          const gesture = (dx, dy, cancelled = false) => {
            const area = top();
            area.fire('pointerdown', {target: area, pointerId: 1, clientX: 200, clientY: 100, button: 0});
            area.fire('pointermove', {target: area, pointerId: 1, clientX: 200 + dx, clientY: 100 + dy});
            area.fire(cancelled ? 'pointercancel' : 'pointerup', {target: area, pointerId: 1, clientX: 200 + dx, clientY: 100 + dy});
          };
          gesture(-100, 0);
          assert.equal(view.sheet.row, comp.rows[1]);
          assert.equal(document.body.querySelector('.rcpt-sheet-count').textContent, '2 / 2');
          assert.equal(nav().querySelectorAll('button')[1].disabled, true);
          gesture(-100, 0); // at the end, keep this card
          assert.equal(view.sheet.row, comp.rows[1]);
          gesture(100, 0, true); // cancelled gestures do not navigate
          assert.equal(view.sheet.row, comp.rows[1]);
          gesture(0, 100); // vertical scrolling does not navigate
          assert.equal(view.sheet.row, comp.rows[1]);
          nav().querySelectorAll('button')[0].click();
          assert.equal(view.sheet.row, comp.rows[0]);
          nav().querySelectorAll('button')[1].click();
          assert.equal(view.sheet.row, comp.rows[1]);
          assert(comp.rows.every(r => !r.ticked), 'browsing never receives or ticks cards');
        """)

    def test_ticks_earn_confirm_and_send_verified_rows_without_the_pictures(self):
        self.run_js("""
          const calls=[];apiWrite=async(path,b)=>{calls.push([path,b]);return ready;};
          tickAll(view);
          // Every tile ticked, but Alpha's condition and language are still blank: not "all checked" yet, and the
          // note that says so stays (only the "check on arrival" part goes with the tick).
          assert.equal(view.primary.textContent,'Preview');
          assert(!view.blanks.hidden);assert(main.textContent.includes('2 with no condition or language'));
          assert.equal(view.comps[0].rows[0].values.notes,'condition and language not recorded');
          await previewDelivery(view);
          let sent=calls[0][1];
          assert.equal(sent.components[0].rows[0].notes,'condition and language not recorded');
          assert.equal(sent.components[0].rows[0].condition,'');                // nothing assumed
          assert(body().includes('2 cards go in with no condition or language recorded: they stay blank.'));
          closeSheets();
          view.blanks.click();assert.equal(view.filter,'attention');
          rcptFillBlanks(view,view.comps[0],'NM','en');
          assert.equal(view.comps[0].rows[0].values.notes,'');                  // true no more, so it goes too
          assert(view.blanks.hidden);
          assert.equal(view.primary.textContent,'Confirm: all 3 checked');
          await previewDelivery(view);
          assert.equal(calls.length,2);assert.equal(calls[1][0],'/api/receipt/preview');
          sent=calls[1][1];assert.equal(sent.received_on,'2026-10-08');assert.equal(sent.fingerprint,'a'.repeat(64));
          assert.equal(sent.components[0].verified,true);
          same(Object.keys(sent.components[0].rows[0]),['name','set','collector_number','finish','quantity','condition','language','notes']);
          assert.equal(sent.components[0].rows[0].notes,'');
          assert(!body().includes('no condition or language recorded'));
          assert(body().includes('3 cards go into your collection (2 new to it)'));
          assert(body().includes("These decks' tables update: Alpha Deck"));
          assert(body().includes('Record arrival'));
          assert(body().includes("Recording it adds these to your collection, marks them arrived and updates those decks' tables, all in one change."));
        """)

    def test_the_preview_words_follow_its_answer_and_show_no_file_paths(self):
        self.run_js("""
          tickAll(view);rcptFillBlanks(view,view.comps[0],'NM','en');
          apiWrite=async()=>({...ready,changes:["Home's collection",'Order test','Deck Alpha Deck (casual/a)']});
          await previewDelivery(view);
          assert(body().includes('What this changes (3)'));assert(body().includes('Deck Alpha Deck (casual/a)'));
          assert(!/files|magic[/]/.test(body()));
          closeSheets();
          apiWrite=async()=>({...ready,tables:{written:[],skipped:[],error:null}});
          await previewDelivery(view);
          assert(body().includes("No deck's table needs updating."));
          assert(body().includes('Recording it adds these to your collection, marks them arrived, all in one change.'));
          assert(!body().includes("updates those decks' tables"));
        """)

    def test_an_edit_after_the_preview_stops_the_apply(self):
        self.run_js("""
          tickAll(view);const calls=[];apiWrite=async(path,b)=>{calls.push(path);return ready;};
          await previewDelivery(view);assert(view.preview);
          rcptFillBlanks(view,view.comps[0],'NM','en');
          assert(main.textContent.includes('Changed since preview, preview again'));
          await applyDelivery(view);same(calls,['/api/receipt/preview']);
          assert(main.textContent.includes('Changed since preview, preview again'));
          assert(main.textContent.includes('NM · EN'));
        """)

    def test_navigation_discards_a_late_preview(self):
        self.run_js("""
          tickAll(view);let finish;apiWrite=()=>new Promise(resolve=>{finish=resolve;});
          const pending=previewDelivery(view);routeToken++;clear(main).append(el('p',{text:'Another page'}));
          finish(ready);await pending;assert.equal(main.textContent,'Another page');
          assert.equal(view.preview,null);assert(!body().includes('Record arrival'));
        """)

    def test_a_change_of_profile_discards_a_late_result(self):
        self.run_js("""
          tickAll(view);let finish;apiWrite=()=>new Promise(resolve=>{finish=resolve;});
          const pending=previewDelivery(view);state.profile={id:'user1',name:'User1'};
          finish(ready);await pending;assert.equal(view.preview,null);assert(!body().includes('Record arrival'));
        """)

    def test_success_says_where_the_cards_go_and_offers_no_second_receipt(self):
        self.run_js("""
          tickAll(view);apiWrite=async()=>ready;await previewDelivery(view);
          const calls=[];apiWrite=async(path)=>{calls.push(path);return {received:true,totals:ready.totals,
            tables:{written:[{id:'casual/a',title:'Alpha Deck'}],skipped:[{id:'casual/b',title:'Beta Deck',why:'changed'},
                      {id:'casual/c',title:'Gamma Deck',why:'kit'}],error:null}};};
          await applyDelivery(view);assert.equal(view.preview,null);assert(view.done);
          const text=main.textContent;
          assert.equal(main.querySelector('h1').textContent,'Arrival recorded');
          assert(text.includes('3 cards added.'));assert(!text.includes('Arrival recorded.'));   // the box says what changed
          assert(!text.includes('Retry'));assert(text.includes('Where these go'));
          assert(text.includes('Sleeve them in Black matte'));assert(text.includes('1 × Alpha'));
          assert(text.includes('To storage'));assert(text.includes('1 × Beta'));
          assert(!/git|commit/i.test(text));
          assert(text.includes('Deck tables updated: Alpha Deck.'));
          assert(text.includes('Not updated: Beta Deck (the receipt changes it itself), Gamma Deck (its Sleeves or Deck box would change).'));
          // The skipped tables wait on the Decks page's list, which exists: a link to it, not words about a button.
          assert(text.includes("They're on the Decks page's Tables out of date list, where Update all refreshes them."));
          const later=main.querySelectorAll('a').filter((a)=>a.textContent==='Tables out of date');
          assert.equal(later.length,1);assert.equal(later[0].getAttribute('href'),'#/library?tables=1');
          assert(!text.includes('Update their tables'));
          assert(!main.querySelector('.rcpt-tick'));
          await applyDelivery(view);await previewDelivery(view);same(calls,['/api/receipt/apply']);
          assert.equal(window.localStorage.getItem('decklab.receipt:matt:test:'+'a'.repeat(64)),null);   // the draft is gone
        """)

    def test_a_refresh_that_failed_points_to_the_decks_page(self):
        self.run_js("""
          tickAll(view);apiWrite=async()=>ready;await previewDelivery(view);
          apiWrite=async()=>({received:true,totals:ready.totals,
            tables:{written:[],skipped:[],error:'Cannot refresh from an incomplete card pool'}});
          await applyDelivery(view);
          assert(main.textContent.includes("The deck tables weren't updated: Cannot refresh"));
          assert(main.textContent.includes("They're on the Decks page's Tables out of date list"));
          assert.equal(main.querySelectorAll('a').find((a)=>a.textContent==='Tables out of date').getAttribute('href'),
                       '#/library?tables=1');
        """)

    def test_an_apply_that_fails_keeps_the_board_and_asks_for_a_new_preview(self):
        self.run_js("""
          tickAll(view);apiWrite=async()=>ready;await previewDelivery(view);
          apiWrite=async()=>{throw new ApiError(409,'Inventory or delivery records changed since this preview.');};
          await applyDelivery(view);
          assert.equal(view.preview,null);assert(!view.done);
          assert(body().includes('Inventory or delivery records changed'));assert(body().includes('Reload the delivery'));
        """)

    def test_split_copies_keep_the_totals_and_merge_back(self):
        self.run_js("""
          const comp=view.comps[0],alpha=comp.rows[0];
          rcptSplit(view,comp,alpha,1);
          assert.equal(comp.rows.length,3);same(comp.rows.map(r=>r.values.quantity),['1','1','1']);
          assert(main.textContent.includes('Split 1 of 2'));assert(main.textContent.includes('Split 2 of 2'));
          comp.rows[1].values.condition='LP';
          const rows=rcptRequest(view).components[0].rows;
          assert.equal(rows.filter(r=>r.name==='Alpha').reduce((n,r)=>n+Number(r.quantity),0),2);
          // The parts differ (LP on one copy): merging asks first, and Cancel keeps them.
          const asked=[];askReceiptChoice=async(v,title)=>{asked.push(title);return null;};
          await rcptMerge(view,comp,comp.rows[1]);
          same(asked,['Merge parts that differ?']);assert.equal(comp.rows.length,3);
          askReceiptChoice=async()=>'yes';
          await rcptMerge(view,comp,comp.rows[1]);
          assert.equal(comp.rows.length,2);assert.equal(comp.rows[0].values.quantity,'2');
          assert(!main.textContent.includes('Split 1 of 2'));
          // Undo puts the parts back, the LP copy included.
          document.querySelector('#toast-undo').querySelector('button').click();
          assert.equal(comp.rows.length,3);same(comp.rows.map(r=>[r.values.quantity,r.values.condition]),[['1',''],['1','LP'],['1','NM']]);
        """)

    def test_fill_blanks_has_undo_and_ticking_alone_marks_nothing_edited(self):
        self.run_js("""
          const comp=view.comps[0];
          rcptTick(view,comp,comp.rows[0],true);assert(!main.textContent.includes('Edited'));
          rcptFillBlanks(view,comp,'NM','en');
          same(comp.rows.map(r=>[r.values.condition,r.values.language]),[['NM','en'],['NM','en']]);
          assert(!main.textContent.includes('Edited'));
          document.querySelector('#toast-undo').querySelector('button').click();
          same(comp.rows.map(r=>[r.values.condition,r.values.language]),[['',''],['NM','en']]);
          comp.rows[1].values.finish='nonfoil';rcptDrawGrid(view,comp);assert(main.textContent.includes('Edited'));
        """)

    def test_the_check_is_kept_and_offered_back_after_a_reload(self):
        self.run_js("""
          const comp=view.comps[0];rcptTick(view,comp,comp.rows[0],true);
          const key='decklab.receipt:matt:test:'+'a'.repeat(64);
          assert(window.localStorage.getItem(key));
          window.localStorage.setItem('decklab.receipt:matt:test:'+'c'.repeat(64),'{}');     // an older revision's
          window.localStorage.setItem('decklab.receipt:test:'+'c'.repeat(64),'{}');          // a key without a profile
          window.localStorage.setItem('decklab.receipt:user1:test:'+'a'.repeat(64),'{}');   // another profile's
          clear(main);const again=drawReceipt(delivery(),routeToken);
          assert.equal(window.localStorage.getItem('decklab.receipt:matt:test:'+'c'.repeat(64)),null);
          assert.equal(window.localStorage.getItem('decklab.receipt:test:'+'c'.repeat(64)),null);
          assert.equal(window.localStorage.getItem('decklab.receipt:user1:test:'+'a'.repeat(64)),'{}');
          assert(main.textContent.includes('2 of 3 ticked'));
          assert(!again.comps[0].rows[0].ticked);
          main.querySelector('.rcpt-resume-box').querySelector('button').click();
          assert(again.comps[0].rows[0].ticked);
          assert.equal(again.comps[0].rows[0].values.notes,'condition and language not recorded');
          // User1 on the same device isn't offered Matt's check.
          state.profile={id:'user1',name:'User1'};clear(main);drawReceipt(delivery(),routeToken);
          assert(!main.textContent.includes('ticked)'));state.profile={id:'matt',name:'Matt'};
          assert(!main.textContent.includes('2 of 3 ticked'));
          // A draft that no longer fits the delivery (other quantities) isn't offered.
          window.localStorage.setItem(key,JSON.stringify({v:1,comps:{cards:{selected:true,intact:'',checks:[false],
            rows:[{orig:0,values:{...delivery().components[0].rows[0],quantity:'5'},ticked:true}]}}}));
          clear(main);drawReceipt(delivery(),routeToken);assert(!main.textContent.includes('ticked)'));
        """)

    def test_a_tokens_back_must_be_confirmed_and_can_be_swapped(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + TOKEN_FIELDS + """,
            rows:[{front:'Ooze',back:'',set:'tm11',front_collector_number:'5',back_collector_number:'',finish:'nonfoil',quantity:'2',
                   front_details:'2/2; green',back_details:'',notes:'listed as Ooze Token (A); reverse face unconfirmed; check physical pairing on arrival'},
                  {front:'Bird',back:'Golem',set:'teoc',front_collector_number:'3',back_collector_number:'12',finish:'nonfoil',quantity:'1',
                   front_details:'2/2; blue',back_details:'3/3',notes:'listing shows this pairing; verify physical pairing on arrival'}],
            pictures:[{img:'/img/tm11/5/normal',img_small:'/img/tm11/5/small',back_img:null,back_img_small:null,exact:true,why:null},
                      {img:'/img/teoc/3/normal',img_small:'/img/teoc/3/small',back_img:'/img/teoc/12/normal',back_img_small:'/img/teoc/12/small',exact:true,why:null}],
            decks:null}];
          clear(main);let v=drawReceipt(d,routeToken);let comp=v.comps[0];
          assert(main.textContent.includes('3 token cards'));assert(!main.textContent.includes('· part'));
          assert(main.textContent.includes('TM11 5 · 2/2'));assert(main.textContent.includes('TEOC 3/12 · 2/2'));
          assert(main.textContent.includes('Back ?'));
          // ⚑ only for the exception: Bird // Golem's pairing check names it; Ooze's back is Back ?'s, and
          // "listed as ..." is provenance.
          assert.equal(main.querySelectorAll('.rcpt-flag').length,0);
          assert.equal(rcptFlag(comp,comp.rows[0]),'');
          d.components[0].checks=['Verify the pairing of Golem // Bird and whether the Ooze is single-sided.'];
          clear(main);const w=drawReceipt(d,routeToken);
          assert.equal(rcptFlag(w.comps[0],w.comps[0].rows[0]),'');assert(rcptFlag(w.comps[0],w.comps[0].rows[1]));
          w.comps[0].checks=[true];assert.equal(rcptFlag(w.comps[0],w.comps[0].rows[1]),'');
          let title=null;askReceiptChoice=async(v,t)=>{title=t;return null;};await rcptTickAll(w,w.comps[0]);
          assert.equal(title,'Tick all 3 token cards?');
          d.components[0].checks=[];clear(main);v=drawReceipt(d,routeToken);comp=v.comps[0];
          tickAll(v);
          assert.equal(comp.rows[1].values.notes,'');                     // the pairing shown was confirmed
          let calls=0;apiWrite=async()=>{calls++;return ready;};
          await previewDelivery(v);assert.equal(calls,0);assert(body().includes("Ooze (TM11 5): say what its back is, or that it's blank."));
          closeSheets();
          rcptOpenSheet(v,comp,comp.rows[0]);
          const blank=document.body.querySelector('.rcpt-blank').querySelector('input');blank.checked=true;blank.fire('change');
          assert.equal(comp.rows[0].values.notes,'listed as Ooze Token (A); single-sided verified');
          assert(!rcptBackOpen(comp.rows[0]));
          rcptOpenSheet(v,comp,comp.rows[1]);
          [...document.body.querySelectorAll('button')].find(b=>b.textContent==='Swap front and back').click();
          same([comp.rows[1].values.front,comp.rows[1].values.back,comp.rows[1].values.front_collector_number],['Golem','Bird','12']);
          assert.equal(rcptPicture(comp,comp.rows[1]).img,'/img/teoc/12/normal');
          assert(rcptPicture(comp,comp.rows[1]).exact);
          await previewDelivery(v);assert.equal(calls,1);
          assert(body().includes('Recording it adds these to your token cards, marks them arrived'));
          closeSheets();
          // A face renamed to something else: no picture (not the old face's), and a ribbon that says why.
          rcptOpenSheet(v,comp,comp.rows[1]);
          const front=v.sheet.sheet.body.querySelector('[aria-label="Front token name"]');front.value='Golem Construct';front.fire('change');
          const pic=rcptPicture(comp,comp.rows[1]);
          assert.equal(pic.img,null);assert(!pic.exact);assert.equal(pic.back_img,'/img/teoc/3/normal');
          assert.equal(rcptUnrecorded(comp,comp.rows[1]),'No picture for this name');
          assert(!main.textContent.includes('printing not recorded'));
          front.value='Golem';front.fire('change');
          assert.equal(rcptPicture(comp,comp.rows[1]).img,'/img/teoc/12/normal');assert(rcptPicture(comp,comp.rows[1]).exact);
          // A back typed with its traits: the note says it isn't a name and one tap splits it into name and details.
          const back=v.sheet.sheet.body.querySelector('[aria-label="Back token name"]');back.value='Green bird 1/1 flying';back.fire('change');
          const sheetText=()=>v.sheet.sheet.body.textContent;assert(sheetText().includes("'Green bird 1/1 flying' isn't a token name on Scryfall."));
          [...v.sheet.sheet.body.querySelectorAll('button')].find(b=>b.textContent==='Use Bird, with "1/1; green; flying" in Back details').click();
          same([comp.rows[1].values.back,comp.rows[1].values.back_details],['Bird','1/1; green; flying']);
          assert(!sheetText().includes("isn't a token name on Scryfall"));
        """)

    def test_token_details_say_how_they_are_read_as_they_are_typed(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + TOKEN_FIELDS + """,
            rows:[{front:'Ooze',back:'Bird',set:'tm11',front_collector_number:'5',back_collector_number:'6',finish:'nonfoil',quantity:'1',
                   front_details:'2/2; green',back_details:'Token Creature — Bird',notes:''}],
            pictures:[{img:null,img_small:null,back_img:null,back_img_small:null,exact:false,why:'not recorded'}],decks:null}];
          clear(main);const v=drawReceipt(d,routeToken);const comp=v.comps[0];
          rcptOpenSheet(v,comp,comp.rows[0]);
          const sb=v.sheet.sheet.body;const lines=()=>sb.querySelectorAll('.tok-reading');
          assert.equal(lines().length,2);
          assert.equal(lines()[0].textContent,'Read as: 2/2 · green');
          assert(lines()[1].textContent.includes("'Token Creature — Bird' is kept but not compared."));
          assert.equal(lines()[1].querySelectorAll('.note-warn').length,0);
          // Typing: only the line redraws (the same field stays, focused), with a warning and a one-tap fix.
          const front=sb.querySelector('[aria-label="Front details"]');front.focus();
          front.value='4/4 whte flyng';front.fire('input');
          assert.equal(sb.querySelector('[aria-label="Front details"]'),front);assert.equal(document.activeElement,front);
          assert.equal(comp.rows[0].values.front_details,'4/4 whte flyng');
          assert(lines()[0].textContent.includes("'4/4 whte flyng' isn't read: did you mean 4/4; white; flying?"));
          assert(lines()[0].textContent.includes('Nothing here is read yet.'));
          front.value='4/4; whte; flying';front.fire('input');
          assert(lines()[0].textContent.startsWith('Read as: 4/4 · flying'));
          assert(lines()[0].textContent.includes("'whte' isn't read: did you mean white?"));
          lines()[0].querySelectorAll('button').find(b=>b.textContent==='Use 4/4; white; flying').click();
          assert.equal(comp.rows[0].values.front_details,'4/4; white; flying');
          const again=v.sheet.sheet.body.querySelectorAll('.tok-reading')[0];
          assert.equal(again.textContent,'Read as: 4/4 · white · flying');
          // Blank details: no line at all.
          const back=v.sheet.sheet.body.querySelector('[aria-label="Back details"]');back.value='';back.fire('input');
          assert.equal(v.sheet.sheet.body.querySelectorAll('.tok-reading')[1].textContent,'');
        """)

    def test_a_product_needs_its_choice_and_shows_its_cards(self):
        self.run_js("""
          const d=delivery();d.components=[{id:'kit',kind:'product',status:'pending',checks:['Record the tokens'],fields:[],rows:[],
            product:{name:'Wretched Ranks',format:'Commander'},
            items:[{name:'Gisa',set:'fdc',collector_number:'1',finish:'foil',quantity:'1',section:'commander',deck:''},
                   {name:'Alpha',set:'tst',collector_number:'1',finish:'nonfoil',quantity:'1',section:'deck',deck:''},
                   {name:'Swamp',set:'fdc',collector_number:'90',finish:'nonfoil',quantity:'30',section:'deck',deck:''}],
            pictures:[null,{card:alphaCard,exact:true,why:null,set_name:'Test',finishes:['nonfoil']},null],decks:null}];
          clear(main);const v=drawReceipt(d,routeToken);
          const text=main.textContent;
          assert(text.includes('Wretched Ranks (product)'));assert(text.includes('Keep it as its own deck(s)'));
          assert(text.includes('Break it up into storage'));assert(text.includes('Tokens page'));
          assert(text.indexOf('Commander (1)')<text.indexOf('Deck (31)'));assert(text.includes('30 basic lands'));
          assert(!main.querySelector('.rcpt-tick'));
          let calls=[];apiWrite=async(p,b)=>{calls.push(b);return ready;};
          await previewDelivery(v);assert.equal(calls.length,0);assert(body().includes('choose whether to keep it'));
          closeSheets();
          [...main.querySelectorAll('button')].find(b=>b.getAttribute('data-intact')==='no').click();
          await previewDelivery(v);assert.equal(calls.length,1);
          same(calls[0].components,[{id:'kit',verified:false,intact:'no'}]);
        """)

    def test_several_parts_ask_what_arrived(self):
        self.run_js("""
          const d=delivery();d.components.push({id:'cards-2',kind:'cards',status:'pending',checks:[],fields:""" + FIELDS + """,
            rows:[{name:'Beta',set:'tst',collector_number:'2',finish:'nonfoil',quantity:'1',condition:'',language:'',notes:''}],
            pictures:null,decks:null});
          clear(main);const v=drawReceipt(d,routeToken);
          assert(!v.comps.some(c=>c.selected));assert.equal(main.querySelectorAll('.rcpt-arrived').length,2);
          assert(main.textContent.includes('1 card from Fixture shop · part cards-2'));
          // Each part's cards show before it's chosen (dimmed, no ticks); a tap opens the viewer, not the sheet.
          assert.equal(main.querySelectorAll('.card-tile').length,3);assert(!main.querySelector('.rcpt-tick'));
          assert(v.comps[0].section.classList.contains('is-off'));
          v.comps[0].rows[0].open.click();assert.equal(inspections.length,1);assert(!v.sheet);
          let calls=0;apiWrite=async()=>{calls++;return ready;};
          await previewDelivery(v);assert.equal(calls,0);assert(main.textContent.includes('This arrived'));
          const second=main.querySelectorAll('.rcpt-arrived')[1].querySelector('input');second.checked=true;second.fire('change');
          assert(v.comps[1].selected);assert(!v.comps[1].section.classList.contains('is-off'));
          assert.equal(main.querySelectorAll('.rcpt-tick').length,1);
          await previewDelivery(v);assert.equal(calls,0);              // no tile ticked: nothing is received
          closeSheets();rcptTick(v,v.comps[1],v.comps[1].rows[0],true);
          await previewDelivery(v);assert.equal(calls,1);
        """)

    def test_a_member_sees_the_tiles_read_only(self):
        self.run_js("""
          state.profile={id:'user1',name:'User1'};state.may={admin:false,receipts:false};
          clear(main);const v=drawReceipt(delivery(),routeToken);
          assert(main.textContent.includes('read only'));assert(!main.querySelector('.rcpt-tick'));
          assert(!main.textContent.includes('Preview'));
          // The same chips as the board: condition and language, and the deck counting on it.
          assert(main.textContent.includes('Condition, language ?'));assert(main.textContent.includes('NM · EN'));
          assert(main.textContent.includes('For Alpha Deck ×1'));
          const open=main.querySelectorAll('[data-viewer=receipt-0]');assert.equal(open.length,2);
          open[0].click();assert.equal(inspections.length,1);assert.equal(inspections[0].card.name,'Alpha');
        """)

    def test_the_arrival_date_defaults_to_today_and_offers_yesterday(self):
        self.run_js("""
          assert.equal(view.date.value,'2026-10-08');
          view.dateSelect.value='yesterday';view.dateSelect.fire('change');assert.equal(view.date.value,'2026-10-07');
          view.dateSelect.value='other';view.dateSelect.fire('change');assert(!view.dateInput.hidden);
          view.dateInput.value='2026-09-01';view.dateInput.fire('change');
          tickAll(view);let calls=0;apiWrite=async()=>{calls++;return ready;};
          await previewDelivery(view);assert.equal(calls,0);assert(body().includes("can't have arrived before it was ordered"));
        """)

    def test_a_date_blocker_switches_to_another_date_so_the_draft_keeps_it(self):
        self.run_js("""
          const d=delivery();d.ordered_on='2026-10-08';clear(main);const v=drawReceipt(d,routeToken);
          v.dateSelect.value='yesterday';v.dateSelect.fire('change');assert.equal(v.date.value,'2026-10-07');
          tickAll(v);rcptFillBlanks(v,v.comps[0],'NM','en');apiWrite=async()=>{throw new Error('no write');};
          await previewDelivery(v);
          [...document.body.querySelectorAll('.rcpt-blocker')].find(b=>b.textContent.includes('before it was ordered')).click();
          assert.equal(v.date.mode,'other');assert.equal(v.dateSelect.value,'other');assert(!v.dateInput.hidden);
          assert.equal(v.dateInput.value,'2026-10-07');assert.equal(document.activeElement,v.dateInput);
          v.dateInput.value='2026-10-08';v.dateInput.fire('change');
          const saved=JSON.parse(window.localStorage.getItem('decklab.receipt:matt:test:'+'a'.repeat(64)));
          same(saved.date,{mode:'other',value:'2026-10-08'});
        """)

    def test_a_server_blocker_focuses_its_section(self):
        self.run_js("""
          tickAll(view);rcptFillBlanks(view,view.comps[0],'NM','en');
          apiWrite=async()=>({ready:false,blockers:['cards: inspect it again']});
          await previewDelivery(view);
          const link=[...document.body.querySelectorAll('.rcpt-blocker')].find(b=>b.textContent.includes('inspect it again'));
          assert(link.textContent.startsWith('3 cards from Fixture shop:'));
          link.click();
          assert.equal(view.comps[0].section.getAttribute('tabindex'),'-1');assert.equal(document.activeElement,view.comps[0].section);
        """)

    def test_ticking_under_not_checked_moves_the_focus_on_and_ends_with_show_all(self):
        self.run_js("""
          const comp=view.comps[0];
          view.filter='todo';rcptRefreshAll(view);
          const first=comp.rows[0].tile.querySelector('.rcpt-tick');
          assert.equal(first.getAttribute('aria-label'),'Check off 2 copies of Alpha');
          first.focus();first.checked=true;first.fire('change');
          assert(comp.rows[0].tile.hidden);
          assert.equal(document.activeElement,comp.rows[1].tile.querySelector('.rcpt-tick'));
          document.activeElement.checked=true;document.activeElement.fire('change');
          assert(main.textContent.includes('Everything here is checked.'));
          const show=comp.grid.querySelector('.rcpt-none').querySelector('button');
          assert.equal(document.activeElement,show);
          show.click();assert.equal(view.filter,'all');assert(!comp.rows[0].tile.hidden);
        """)

    def test_a_changed_printing_keeps_its_picture_through_a_reload(self):
        self.run_js("""
          const comp=view.comps[0],alpha=comp.rows[0];
          pickPrinting=async()=>({set:'abc',number:'7',finish:'nonfoil',set_name:'Another Set',
            img:'/img/abc/7/normal',img_small:'/img/abc/7/small'});
          api=async()=>({printings:[{set:'abc',number:'7',finish:'nonfoil',set_name:'Another Set',img:'/img/abc/7/normal',img_small:'/img/abc/7/small'},
                                    {set:'abc',number:'7',finish:'foil',set_name:'Another Set',img:'/img/abc/7/normal',img_small:'/img/abc/7/small'}]});
          rcptOpenSheet(view,comp,alpha);
          const settle=async()=>{for(let i=0;i<30;i++) await Promise.resolve();};
          [...document.body.querySelectorAll('button')].find(b=>b.textContent==='Different printing…').fire('click');
          await settle();
          assert.equal(rcptPicture(comp,alpha).card.img_small,'/img/abc/7/small');closeSheets();
          // A reload, then Resume: the new printing's picture, set name and finishes, not the ordered one's.
          clear(main);const again=drawReceipt(delivery(),routeToken);
          main.querySelector('.rcpt-resume-box').querySelector('button').click();
          const row=again.comps[0].rows[0];const pic=rcptPicture(again.comps[0],row);
          same([row.values.set,row.values.collector_number],['abc','7']);
          assert.equal(pic.card.img_small,'/img/abc/7/small');assert(pic.exact);assert.equal(pic.set_name,'Another Set');
          same(pic.finishes,['nonfoil','foil']);
          assert(main.textContent.includes('ABC 7 · Nonfoil'));
          // A draft without the picture (or a bad one) doesn't show the ordered printing as exact: it looks it up again.
          const key='decklab.receipt:matt:test:'+'a'.repeat(64);const draft=JSON.parse(window.localStorage.getItem(key));
          draft.comps.cards.rows[0].pic={card:{name:'Alpha',img:'https://elsewhere.example/x.jpg',img_small:null}};
          window.localStorage.setItem(key,JSON.stringify(draft));
          clear(main);const third=drawReceipt(delivery(),routeToken);
          main.querySelector('.rcpt-resume-box').querySelector('button').click();
          const r3=third.comps[0].rows[0];
          assert(!rcptPicture(third.comps[0],r3).exact);assert.equal(rcptPicture(third.comps[0],r3).card.img_small,null);
          await settle();
          assert(rcptPicture(third.comps[0],r3).exact);assert.equal(rcptPicture(third.comps[0],r3).card.img_small,'/img/abc/7/small');
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class NoInventoryCrumbTests(unittest.TestCase):
    def test_a_receipt_refused_to_someone_outside_the_home_points_back_to_the_decks(self):
        scenario = """
          location.hash='#/receipt?order=x';state.profile={id:'user2',name:'User2'};
          showNoInventory(routeH1('receipt'));
          assert.equal(state.crumb.href,'#/library');assert(!main.textContent.includes('Shopping'));
          location.hash='#/shopping';state.crumb=null;showNoInventory(routeH1('shopping'));assert.equal(state.crumb,null);
        """
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")
