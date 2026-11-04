"""Build decks' big view: the shared tick and "Which printing?" beside the card, and the tile's printing select."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB

SETUP = """
  const option=(set,number,free,set_name='',finish='nonfoil')=>({set,set_name,collector_number:number,finish,
    label:`${set.toUpperCase()} ${number}${finish==='nonfoil'?'':' '+finish}`,free});
  const offers={Alpha:{options:[option('fdn','1',2,'Foundations'),option('m19','2',5),option('mh1','3',1,'Horizons','foil')],only:null},
    Beta:{options:[option('cmm','9',1,'Masters')],only:option('cmm','9',1,'Masters')}};
  const bigData=()=>{const a=item();
    a.steps=[{name:'Alpha',need:3,keep:0,storage:3,transfers:[],waiting:0,missing:0},{name:'Beta',need:2,keep:0,storage:2,transfers:[],waiting:0,missing:0}];
    a.basics=[{name:'Gamma',quantity:1}];a.printing_choices=offers;
    const data=plan([a]);data.cards.Beta={...beta,img:'/img/b/1/normal',img_small:'/img/b/1/small'};
    data.cards.Gamma={...alpha,name:'Gamma',img:'/img/g/1/normal',img_small:'/img/g/1/small'};return data;};
  const openPlan=async(data=bigData())=>{viewerState=null;drawAssembly(data,routeToken);await settle();return packingProgressView;};
  const openBig=(v,index=0)=>{v.packViewerEntries[index].trigger.click();viewerDom.dialog.open=true;viewerDom.dialog.setAttribute('open','');return v.viewerPanel;};
  const shut=()=>{viewerDom.dialog.open=false;viewerDom.dialog.removeAttribute('open');viewerClosed();};
  const tileTick=(v,task)=>v.ticks.find(t=>t.node.getAttribute('data-pack-tick')===task);
  const select=(v,name='Alpha')=>v.printingControls.find(c=>c.name===name).select;
  const choose=(node,value)=>{node.value=value;node.fire('change');};
  const alphaRows=v=>(packPrintingsBody(v,v.data)['casual/a']||[]).filter(r=>r.name==='Alpha');
  const openDialog=(wanted=()=>true)=>document.querySelectorAll('dialog').filter(wanted).pop();
  const button=(root,text)=>root.querySelectorAll('button').find(b=>b.textContent===text);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyBigViewUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_the_big_view_toggles_the_same_tick_as_the_tile(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),tick=tileTick(v,'pull|Alpha');
          assert(viewerDom.marks.contains(panel.tick));assert(!viewerDom.marks.hidden);
          assert.equal(panel.tick.textContent,'Tick off ×3');assert.equal(panel.tick.getAttribute('aria-pressed'),'false');
          assert.equal(panel.tick.getAttribute('aria-label'),'Tick off ×3: 3 × Alpha','the visible words start its name');
          panel.tick.click();await settle();
          assert(tick.done);assert.equal(tick.node.getAttribute('aria-pressed'),'true');assert(tick.tile.classList.contains('is-ticked'));
          assert.equal(panel.tick.textContent,'Ticked ×3');assert.equal(panel.tick.getAttribute('aria-pressed'),'true');
          assert(serverTicks.has(tick.id));
          assert.equal(viewerState.index,0,'a tick never moves on to the next card');
          tick.node.click();await settle();
          assert.equal(panel.tick.textContent,'Tick off ×3');assert(!serverTicks.has(tick.id));
          panel.tick.click();await settle();panel.tick.click();await settle();assert(!tick.done);
        """)

    def test_swiping_shows_each_cards_own_state_and_a_single_copy_has_no_count(self):
        self.run_js("""
          const v=await openPlan();tileTick(v,'pull|Beta').node.click();await settle();
          const panel=openBig(v);assert.equal(panel.tick.textContent,'Tick off ×3');
          goViewer(1);assert.equal(panel.tick.textContent,'Ticked ×2');
          assert(viewerDom.marks.contains(panel.tick));
          goViewer(2);assert.equal(panel.tick.textContent,'Tick off');assert(panel.slot.hidden);
          panel.tick.click();await settle();assert(tileTick(v,'basic|Gamma').done);assert(!tileTick(v,'pull|Alpha').done);
          goViewer(0);assert.equal(panel.tick.textContent,'Tick off ×3');
        """)

    def test_focus_stays_on_the_big_tick_from_card_to_card(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v);panel.tick.focus();goViewer(1);
          assert(document.activeElement===panel.tick);
          const old=panel.printing.node;goViewer(0);assert(!old.isConnected);
          panel.printing.select.focus();goViewer(2);assert(document.activeElement===viewerDom.close);
        """)

    def test_another_device_and_clear_and_undo_reach_the_open_view(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),tick=tileTick(v,'pull|Alpha');
          serverTicks.add(tick.id);await packSync(v,{resync:true});await settle();
          assert.equal(panel.tick.getAttribute('aria-pressed'),'true');assert.equal(panel.tick.textContent,'Ticked ×3');
          let undo;showToast=(text,opts)=>{undo=opts?.undo;};packClearTicks(v);await settle();
          assert.equal(panel.tick.getAttribute('aria-pressed'),'false');undo();await settle();
          assert.equal(panel.tick.getAttribute('aria-pressed'),'true');
          serverTicks.delete(tick.id);await packSync(v,{resync:true});await settle();
          assert.equal(panel.tick.getAttribute('aria-pressed'),'false');
        """)

    def test_a_rerender_under_the_view_acts_on_the_new_tile_not_the_stale_one(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),stale=tileTick(v,'pull|Alpha');
          choose(panel.printing.select,'1');
          renderAssemblyPlan(v,v.data);await settle();
          const fresh=tileTick(v,'pull|Alpha');assert(fresh.node!==stale.node);assert(!stale.node.isConnected);
          assert(!panel.tick.disabled);assert.equal(panel.printing.select.value,'1');
          panel.tick.click();await settle();
          assert(fresh.done);assert(fresh.tile.classList.contains('is-ticked'));assert(!stale.tile.classList.contains('is-ticked'));
          choose(panel.printing.select,'0');assert.equal(select(v).value,'0');
          const smaller=bigData();smaller.decks[0].steps=smaller.decks[0].steps.slice(1);
          renderAssemblyPlan(v,smaller);await settle();
          assert(panel.tick.disabled);assert.equal(panel.tick.textContent,'Not in this plan');assert(panel.slot.hidden);
          assert(panel.note.textContent.includes('no longer in the plan'));
          const before=[...serverTicks];panel.tick.click();await settle();same([...serverTicks],before);
        """)

    def test_the_view_refuses_while_saving_or_previewing_and_says_so(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),tick=tileTick(v,'pull|Alpha');
          panel.tick.focus();
          v.previewing=true;packProgress(v);assert(panel.tick.disabled);assert(panel.printing.select.disabled);
          assert(document.activeElement===viewerDom.close);assert(panel.note.textContent.includes('Working out'));
          panel.tick.click();await settle();assert(!tick.done);
          v.previewing=false;packProgress(v);assert(!panel.tick.disabled);assert(panel.note.hidden);
          packSaving(v,true);assert(panel.tick.disabled);assert(panel.note.textContent.includes('Saving'));
          panel.tick.click();await settle();assert(!tick.done);
          packSaving(v,false);assert(!panel.tick.disabled);
        """)

    def test_failed_progress_is_said_and_a_press_still_takes_the_shared_path(self):
        self.run_js("""
          const data=bigData();drawAssembly(data,routeToken);const v=packingProgressView;
          const panel=openBig(v);assert(panel.note.textContent.includes('Loading shared ticks'));
          await settle();assert(panel.note.hidden);
          const real=apiWrite;apiWrite=async()=>{throw new Error('The server went away.');};
          v.progress.loaded=false;await packSync(v,{resync:true});await settle();
          assert(panel.note.textContent.includes('may be ticked already'));assert(!panel.tick.disabled);
          panel.tick.click();await settle();const tick=tileTick(v,'pull|Alpha');
          assert(tick.done,'the local tick shows, as on the tile');assert(panel.note.textContent.includes("haven't been saved"));
          apiWrite=real;await packSync(v);await settle();assert(panel.note.hidden);assert(serverTicks.has(tick.id));
        """)

    def test_closing_the_view_stops_it_following_the_plan(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),tick=tileTick(v,'pull|Alpha');
          v.packingViewer.capture();shut();v.packingViewer?.close();assert(!v.viewerPanel);
          panel.tick.click();await settle();assert(!tick.done);
        """)

    def test_a_select_lists_printings_with_their_set_and_free_copies_and_keeps_the_plan_in_place(self):
        self.run_js("""
          const v=await openPlan(),node=select(v),tile=tileTick(v,'pull|Alpha').tile,cards=v.results.querySelector('.pack-tick');
          assert.equal(node.tag,'select');assert(tile.contains(node));assert(!tile.querySelector('.card-tile-open').contains(node));
          same(node.children.map(o=>o.textContent),['Which printing?','FDN 1 · Foundations (2 free)','M19 2 (5 free)',
            'MH1 3 foil · Horizons (1 free)','Split between printings…']);
          assert.equal(node.value,'');same(alphaRows(v),[]);
          let draws=0;const real=renderAssemblyPlan;renderAssemblyPlan=(...a)=>{draws++;return real(...a);};
          node.focus();choose(node,'1');
          assert.equal(draws,0);assert(document.activeElement===node);assert(node.isConnected);assert(cards.isConnected);
          same(alphaRows(v),[{name:'Alpha',set:'m19',collector_number:'2',finish:'nonfoil',quantity:3}]);
          assert(node.parentNode.querySelector('.pack-printing-note').hidden);
          choose(node,'0');assert.equal(node.value,'0');
          const note=node.parentNode.querySelector('.pack-printing-note');assert(!note.hidden);assert.equal(note.textContent,'1 not recorded');
          assert.equal(node.getAttribute('aria-describedby'),note.getAttribute('id'));assert(note.getAttribute('id'));
          same(alphaRows(v).map(r=>r.quantity),[2]);
          choose(node,'');assert(note.hidden);same(alphaRows(v),[]);assert.equal(draws,0);
        """)

    def test_a_split_is_a_read_only_choice_and_the_sheet_keeps_the_plan_in_place(self):
        self.run_js("""
          const v=await openPlan(),node=select(v);let draws=0;
          const real=renderAssemblyPlan;renderAssemblyPlan=(...a)=>{draws++;return real(...a);};
          choose(node,'split');assert.equal(node.value,'','an unfinished split leaves the choice as it was');
          const sheet=openDialog();assert(sheet);const inputs=[...sheet.querySelectorAll('input')];
          inputs[0].value='2';inputs[1].value='1';button(sheet,'Done').click();await settle();
          assert.equal(draws,0);assert.equal(node.value,'made');
          const made=node.children.find(o=>o.getAttribute('value')==='made');
          assert.equal(made.textContent,'FDN 1 ×2 · M19 2 ×1');assert.equal(made.getAttribute('disabled'),'');
          same(alphaRows(v).map(r=>[r.set,r.quantity]),[['fdn',2],['m19',1]]);
          choose(node,'1');assert(!node.children.some(o=>o.getAttribute('value')==='made'));
        """)

    def test_a_single_copy_has_no_split_and_one_printing_stays_plain_words(self):
        self.run_js("""
          const data=bigData();data.decks[0].steps[0].storage=1;const v=await openPlan(data);
          assert(!select(v).children.some(o=>o.getAttribute('value')==='split'));
          const only=v.printingControls.find(c=>c.name==='Beta');assert.equal(only.select,null);assert.equal(only.node.tag,'p');
          assert.equal(only.node.textContent,'CMM 9 ×1 · 1 not recorded');
          assert(packPrintingsBody(v,v.data)['casual/a'].some(r=>r.name==='Beta'&&r.set==='cmm'&&r.quantity===1));
          const full=bigData();full.decks[0].steps[1].storage=1;const w=await openPlan(full);
          assert.equal(w.printingControls.find(c=>c.name==='Beta').node.textContent,'CMM 9 · Masters (only printing in storage)');
        """)

    def test_the_big_view_and_the_tile_share_one_printing_choice(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),tile=select(v);
          assert(panel.printing.select!==tile);assert.equal(panel.printing.select.tag,'select');
          choose(panel.printing.select,'2');assert.equal(tile.value,'2');
          assert.equal(tile.parentNode.querySelector('.pack-printing-note').textContent,'2 not recorded');
          choose(tile,'1');assert.equal(panel.printing.select.value,'1');
          same(packPrintingsBody(v,v.data)['casual/a'].filter(r=>r.name==='Alpha').map(r=>r.set),['m19']);
          choose(panel.printing.select,'split');assert.equal(panel.printing.select.value,'1');
          const sheet=openDialog(d=>!d.matches('.viewer'));assert(sheet,'the sheet opens over the big view');
          const inputs=[...sheet.querySelectorAll('input')];inputs[1].value='2';inputs[0].value='1';
          button(sheet,'Done').click();await settle();
          assert.equal(tile.value,'made');assert.equal(panel.printing.select.value,'made');
        """)

    def test_a_poll_never_rebuilds_a_picker_in_use(self):
        self.run_js("""
          const v=await openPlan(),panel=openBig(v),before=panel.printing.select.children[1];
          await packSync(v,{resync:true});await settle();packProgress(v);
          assert(panel.printing.select.children[1]===before);
        """)

    def test_a_shrunken_plan_trims_a_pick_to_what_it_pulls(self):
        self.run_js("""
          const v=await openPlan();choose(select(v),'1');
          const next=bigData();next.decks[0].steps[0].storage=2;renderAssemblyPlan(v,next);await settle();
          assert.equal(select(v).value,'1');
          same(packPrintingsBody(v,v.data)['casual/a'].filter(r=>r.name==='Alpha').map(r=>r.quantity),[2]);
        """)

    def test_two_decks_share_a_printings_free_copies_so_finishing_is_never_refused(self):
        self.run_js("""
          const two=()=>{const data=bigData(),b={...structuredClone(data.decks[0]),id:'casual/b',title:'B'};
            const fdn=option('fdn','1',2,'Foundations'),m19=option('m19','2',2);
            for(const deck of [data.decks[0],b]){deck.steps=[{name:'Alpha',need:2,keep:0,storage:2,transfers:[],waiting:0,missing:0}];deck.basics=[];
              deck.printing_choices={Alpha:{options:[fdn,m19],only:null}};}
            data.decks.push(b);data.completion.decks.push({id:'casual/b',version:'target'});return data;};
          const v=await openPlan(two()),[a,b]=v.printingControls,body=()=>packPrintingsBody(v,v.data);
          same(b.select.children.slice(1,3).map(o=>o.textContent),['FDN 1 · Foundations (2 free)','M19 2 (2 free)']);
          choose(a.select,'0');
          // The other deck's list follows at once, in place, and can't reach for the same copies.
          same(b.select.children.slice(1,3).map(o=>o.textContent),['FDN 1 · Foundations (0 free)','M19 2 (2 free)']);
          assert.equal(b.select.children[1].getAttribute('disabled'),'');
          same(a.select.children.slice(1,3).map(o=>o.textContent),['FDN 1 · Foundations (2 free)','M19 2 (2 free)']);
          choose(b.select,'0');assert.equal(b.select.value,'');assert.equal(body()['casual/b'],undefined);
          choose(a.select,'');assert.equal(b.select.children[1].getAttribute('disabled'),null);
          // Half each is fine, and the rest shows on both.
          choose(a.select,'split');let sheet=openDialog();let inputs=[...sheet.querySelectorAll('input')];
          inputs[0].value='1';inputs[1].value='1';button(sheet,'Done').click();await settle();
          choose(b.select,'0');same(body()['casual/b'].map(r=>[r.set,r.quantity]),[['fdn',1]]);
          assert.equal(b.select.parentNode.querySelector('.pack-printing-note').textContent,'1 not recorded');
          choose(b.select,'split');sheet=openDialog();inputs=[...sheet.querySelectorAll('input')];
          assert.equal(inputs[0].getAttribute('max'),'1');assert(sheet.textContent.includes('FDN 1 (1 free)'));
          button(sheet,'Cancel').click();await settle();
          // Picks already over (a plan the free copies fell under) trim on the next draw, so Refresh clears them.
          v.boxPrintings['casual/a'].Alpha=[{...option('fdn','1',2),quantity:2}];
          v.boxPrintings['casual/b'].Alpha=[{...option('fdn','1',2),quantity:2}];
          renderAssemblyPlan(v,two());await settle();
          const total=Object.values(packPrintingsBody(v,v.data)).flat().filter(r=>r.set==='fdn').reduce((n,r)=>n+r.quantity,0);
          assert.equal(total,2);
        """)

    def test_an_only_printing_goes_when_another_is_offered_as_nobody_chose_it(self):
        self.run_js("""
          const v=await openPlan(),betaRows=()=>packPrintingsBody(v,v.data)['casual/a'].filter(r=>r.name==='Beta');
          same(betaRows().map(r=>r.set),['cmm']);
          const next=bigData();next.decks[0].printing_choices={...offers,Beta:{options:[option('cmm','9',1,'Masters'),option('m19','2',1)],only:null}};
          choose(select(v),'1');renderAssemblyPlan(v,next);await settle();
          assert.equal(select(v,'Beta').value,'');same(betaRows(),[]);
          // One the person did choose stays.
          assert.equal(select(v).value,'1');
        """)

    def test_the_big_view_says_what_a_tick_means_and_for_which_deck(self):
        self.run_js("""
          const data=bigData();data.decks[0].steps[0].transfers=[{from:'casual/b',from_title:'B',quantity:1}];
          data.decks[0].standins={rows:[{for:'Gamma',qty:1,using:false}]};
          const v=await openPlan(data),panel=openBig(v);
          assert(viewerDom.marks.contains(panel.task));
          assert.equal(panel.task.textContent,'Pull 3 from storage for Elves');
          const words=v.packViewerEntries.map((_,i)=>{goViewer(i);return panel.task.textContent;});
          assert(words.includes('Move 1 from B to Elves; change sleeves'));assert(words.includes('1 for Elves'));
          assert(words.includes('Elves: Use or keep 1 spare cards to stand for Gamma'),'a caption without the deck gets it');
        """)

    def test_nothing_about_printings_blocks_finishing(self):
        self.run_js("""
          const v=await openPlan();v.ticks.forEach(t=>t.node.click());await settle();
          assert.equal(select(v).value,'');assert(packCanFinish(v));
        """)


class AssemblyBigViewSourceTests(unittest.TestCase):
    def test_the_task_line_only_shows_where_the_words_are_hidden_and_wide_controls_clear_them(self):
        css = (WEB / 'assembly-overlap.css').read_text(encoding='utf-8')
        self.assertIn('.viewer.show-text .pack-viewer-task { display: none; }', css)
        wide = css.split('@media (min-width: 1000px) and (orientation: landscape), (min-width: 1200px) {')[1].split('\n}')[0]
        self.assertIn('.pack-viewer-task { display: none; }', wide)
        self.assertIn('width: min(560px, calc(var(--viewer-card-w) + 2 * 84px));', wide)

    def test_select_text_stops_ios_zooming_and_the_big_controls_are_large(self):
        css = (WEB / 'assembly-overlap.css').read_text(encoding='utf-8')
        self.assertRegex(css, r"\.pack-printing-select \{[^}]*font-size: max\(16px, 1rem\)")
        self.assertRegex(css, r"\.viewer-btn\.pack-viewer-tick \{[^}]*min-height: 56px")

    def test_a_phone_on_its_side_keeps_the_card_full_height(self):
        css = (WEB / 'assembly-overlap.css').read_text(encoding='utf-8')
        self.assertIn('"prev stage head next" "prev stage text next" "prev stage count next"', css)
