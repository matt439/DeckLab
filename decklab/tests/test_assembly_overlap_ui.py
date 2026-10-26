"""Informational selected-playable competition never changes the physical plan or controls."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB

SETUP = """
  const demand=(need,extra={})=>({name:'Alpha',need,keep:0,storage:0,transfers:[],waiting:0,missing:0,resolved:true,...extra});
  const participant=(id,steps,version='target')=>({...item(id,version),steps,standins:{rows:[]}});
  const response=decks=>{const data=plan(decks),byName=new Map();
    for(const deck of decks)for(const step of deck.steps){if(!byName.has(step.name))byName.set(step.name,
      {name:step.name,need:0,kept:0,from_storage:0,transfers:[],waiting:0,missing:0,held_elsewhere:[]});
      const row=byName.get(step.name);row.need+=step.need;row.kept+=step.keep;row.from_storage+=step.storage;
      row.transfers.push(...step.transfers);row.waiting+=step.waiting;row.missing+=step.missing;}
    data.rows=[...byName.values()];data.totals.waiting=data.rows.reduce((n,r)=>n+r.waiting,0);data.totals.missing=data.rows.reduce((n,r)=>n+r.missing,0);
    data.ready=!data.totals.waiting&&!data.totals.missing;data.completion.can_mark_built=data.ready;return data;};
  const competition=()=>response([participant('casual/a',[demand(4,{storage:4})]),
    participant('casual/b',[demand(4,{missing:4})],'owned')]);
  const clone=data=>JSON.parse(JSON.stringify(data));
"""


@unittest.skipUnless(NODE,"Node.js isn't installed")
class AssemblyOverlapUiTests(unittest.TestCase):
    def run_js(self,scenario):
        completion.AssemblyCompletionUiTests.run_js(self,SETUP+scenario)

    def test_confirmed_competition_counts_copies_once_and_keeps_current_data_immutable(self):
        self.run_js("""
          const data=competition(),before=JSON.stringify(data),rows=packPlayableOverlap(data);
          assert.equal(rows.length,1);assert.equal(rows[0].name,'Alpha');assert.equal(rows[0].missing,4);
          same(rows[0].participants.map(p=>[p.id,p.version,p.need,p.assigned,p.waiting,p.missing]),
            [['casual/a','target',4,4,0,0],['casual/b','owned',4,0,0,4]]);
          assert.equal(JSON.stringify(data),before);data.cards={};assert.equal(packPlayableOverlap(data).length,1);
        """)

    def test_ready_keep_and_transfer_and_all_waiting_or_missing_are_not_competition(self):
        self.run_js("""
          const ready=response([participant('casual/a',[demand(2,{keep:2})]),participant('casual/b',
            [demand(2,{transfers:[{from:'casual/a',from_title:'A',quantity:2}]})])]);same(packPlayableOverlap(ready),[]);
          for(const shortage of ['waiting','missing']){const data=response([participant('casual/a',[demand(2,{[shortage]:2})]),
            participant('casual/b',[demand(2,{[shortage]:2})])]);same(packPlayableOverlap(data),[]);}
          const one=response([participant('casual/a',[demand(4,{keep:2,missing:2})]),participant('casual/b',[])]);
          same(packPlayableOverlap(one),[]);
          const kept=competition();kept.decks[0].steps[0].keep=4;kept.decks[0].steps[0].storage=0;
          kept.rows[0].kept=4;kept.rows[0].from_storage=0;assert.equal(packPlayableOverlap(kept).length,1);
        """)

    def test_effective_standins_suppress_both_represented_and_marker_names_only(self):
        self.run_js("""
          for(const row of [{for:'Alpha',using:null,qty:1},{for:'Other target',using:'Alpha',qty:1}]){
            const data=competition();data.decks[0].standins.rows=[row];same(packPlayableOverlap(data),[]);}
          const data=competition();Object.assign(data.decks[0].standins,{needs:[{for:'Alpha',qty:1}],
            candidates:[{name:'Alpha',free:1}],choices:[{for:'Alpha',using:null,qty:1}],retired:[{for:'Alpha',using:null,qty:1}]});
          assert.equal(packPlayableOverlap(data).length,1);
          const third=response([participant('casual/a',[demand(1,{keep:1})]),participant('casual/b',[demand(1,{storage:1})]),
            participant('casual/c',[demand(1,{missing:1})])]);third.decks[2].standins.rows=[{for:'Other target',using:'Alpha',qty:1}];
          same(packPlayableOverlap(third),[]);
        """)

    def test_donor_only_and_basic_rows_never_become_more_playable_participants(self):
        self.run_js("""
          const donor=participant('casual/donor',[]);donor.returns=[{name:'Alpha',quantity:1}];donor.basics=[{name:'Forest',quantity:40}];
          const data=response([donor,participant('casual/a',[demand(2,{transfers:[{from:donor.id,from_title:donor.title,quantity:2}]})]),
            participant('casual/b',[demand(2,{waiting:1,missing:1})])]);
          data.decks[1].basics=[{name:'Forest',quantity:20}];data.decks[2].basics=[{name:'Forest',quantity:20}];
          same(packPlayableOverlap(data).map(row=>[row.name,row.participants.map(p=>p.id)]),[['Alpha',['casual/a','casual/b']]]);
          const noOther=clone(data);noOther.decks=noOther.decks.slice(0,2);noOther.rows[0].need=2;noOther.rows[0].waiting=0;noOther.rows[0].missing=0;
          same(packPlayableOverlap(noOther),[]);
        """)

    def test_duplicate_names_ids_unconfirmed_unresolved_and_nonconserved_counts_fail_closed(self):
        self.run_js("""
          const mutations=[d=>d.counts_confirmed=false,d=>d.decks[1].steps[0].resolved=false,d=>delete d.decks[1].standins,
            d=>d.decks[1].id=d.decks[0].id,d=>d.decks[1].steps.push({...d.decks[1].steps[0]}),d=>d.rows.push({...d.rows[0]}),
            d=>d.decks[1].steps[0].need=5,d=>d.rows[0].missing=5,d=>d.decks[1].steps[0].missing=-1,
            d=>d.decks[1].steps[0].missing=.5,d=>d.decks[1].steps[0].missing='4',d=>d.decks[1].steps[0].need=Number.MAX_SAFE_INTEGER+1];
          for(const mutate of mutations){const data=competition();mutate(data);same(packPlayableOverlap(data),[]);}
        """)

    def test_notice_and_pull_move_pills_are_outside_hit_areas_with_original_scope_and_captions(self):
        self.run_js("""
          const donor=participant('casual/donor',[]);donor.title='Donor';donor.returns=[{name:'Alpha',quantity:1}];
          const data=response([donor,participant('casual/a',[demand(4,{storage:3,transfers:[{from:donor.id,from_title:'Donor',quantity:1}]})]),
            participant('casual/b',[demand(4,{missing:4})],'owned')]);
          data.rows[0].held_elsewhere=[{id:'private/hidden',title:'Not a participant',quantity:99}];
          window.matchMedia('(min-width: 1000px)').matches=false;drawAssembly(data,routeToken);await settle();const v=packingProgressView;
          const notice=v.results.querySelector('.pack-overlap');assert(notice);assert.equal(notice.getAttribute('role'),'note');
          assert.equal(notice.querySelectorAll('button').length,0);assert.equal(notice.querySelectorAll('a').length,0);
          assert(!notice.textContent.includes('Not a participant'));assert(notice.textContent.includes('Play-now list'));
          assert(notice.textContent.includes('4 needed; 0 assigned; 0 waiting; 4 missing'));
          const ids=v.ticks.map(t=>t.id),scope=v.progress.scope,selected=JSON.stringify(v.selected),captions=v.packViewerEntries.map(e=>e.caption);
          assert.equal(v.ticks.length,3);assert.equal(v.bar.progress.copies.textContent,'0 / 5');
          for(const tick of v.ticks){const pill=tick.tile.querySelector('.pack-overlap-pill');
            if(tick.node.getAttribute('data-pack-tick').startsWith('return|'))assert(!pill);
            else{assert(pill&&pill.parentNode===tick.tile);assert(!tick.tile.querySelector('.card-tile-open').contains(pill));
              assert(!tick.node.contains(pill));assert(pill.textContent.includes('Play-now list'));}}
          const calls=[];mockApi((path,body)=>{calls.push([path,body]);throw new Error('view only');});v.switcher.panels[1].button.click();
          same(v.ticks.map(t=>t.id),ids);assert.equal(v.progress.scope,scope);assert.equal(JSON.stringify(v.selected),selected);
          same(v.packViewerEntries.map(e=>e.caption),captions);same(calls,[]);assert(!packCanFinish(v));
        """)

    def test_compact_pill_keeps_full_long_list_context_once_for_speech_and_tooltip(self):
        self.run_js("""
          const data=competition(),other='A very long other selected deck title that must not become a tall casual capsule';
          data.decks[1].title=other;window.matchMedia('(min-width: 1000px)').matches=false;
          drawAssembly(data,routeToken);await settle();const v=packingProgressView,pill=v.ticks[0].tile.querySelector('.pack-overlap-pill');
          const short=pill.querySelector('.pack-overlap-short'),full=pill.querySelector('.pack-overlap-full');
          assert.equal(short.textContent,'Also needed');assert.equal(short.getAttribute('aria-hidden'),'true');
          assert.equal(full.textContent,'Also needed by '+other+' (Play-now list)');assert.equal(full.getAttribute('aria-hidden'),null);
          assert.equal(pill.getAttribute('title'),full.textContent);assert.equal(pill.children.filter(n=>n.getAttribute('aria-hidden')!=='true').length,1);
          assert(pill.parentNode===v.ticks[0].tile);assert(!v.ticks[0].tile.querySelector('.card-tile-open').contains(pill));
          assert(v.results.querySelector('.pack-overlap').textContent.includes(other));assert.equal(pill.querySelectorAll('button').length,0);
        """)

    def test_stale_profile_route_permission_and_replaced_data_never_render_old_notice_or_pills(self):
        self.run_js("""
          for(const mode of ['profile','route','permission','data']){clear(main);state.profile={id:'matt',role:'admin',space:'home'};state.may=null;
            drawAssembly(competition(),routeToken);await settle();const v=packingProgressView,participant=v.data.decks[0];
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')++routeToken;if(mode==='permission')state.may={see_home_records:false};
            if(mode==='data')v.data={...v.data};assert.equal(packOverlapNotice(v),null);assert.equal(packOverlapPill(v,'Alpha',participant),null);}
        """)


class AssemblyOverlapSourceTests(unittest.TestCase):
    def test_static_warning_facts_wrap_outside_controls_without_action_or_api(self):
        source=(WEB/'assembly-overlap.js').read_text(encoding='utf-8');css=(WEB/'assembly-overlap.css').read_text(encoding='utf-8')
        self.assertNotIn('apiWrite',source);self.assertNotIn('onclick',source);self.assertNotIn('addEventListener',source)
        self.assertNotIn('Give to',source);self.assertIn('white-space: normal; overflow-wrap: anywhere',css)
        self.assertIn('grid-column: 1 / -1',css);self.assertIn('scope: "row"',source);self.assertIn('All quantities are card copies',source)
        self.assertIn('.pack-overlap-number { font-family: var(--font-mono); }',css)
        self.assertNotIn('.pack-overlap-facts { font-family: var(--font-mono)',css)
        full=css.split('.pack-overlap-full {',1)[1].split('}',1)[0]
        self.assertIn('clip-path: inset(50%)',full);self.assertNotIn('display: none',full)
        self.assertIn('.pack-overlap-short { display: none; }',css)
        self.assertIn('clip-path: none; white-space: normal',css)
