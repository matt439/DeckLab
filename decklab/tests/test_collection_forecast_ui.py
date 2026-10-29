"""Pending storage scenarios over frozen API fixtures and the real UI scripts; no network."""
import json
import subprocess
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB
from decklab.tests import test_collection_forecast as backend_support


FIXTURE = SETUP + r'''
  let reads = [], writes = 0;
  api = async path => { reads.push(path); throw Error('Unexpected read'); };
  apiWrite = async () => { writes++; throw Error('Writes forbidden'); };
  const original = {name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:4,
    condition:'NM',language:'en',notes:''};
  const box = {cards:3,capacity:10,over:false,not_counted:0,elsewhere:0};
  const row = (quantity=5,disposition='box',changes={}) => ({name:'Llanowar Elves',set:'fdn',collector_number:'227',
    finish:'nonfoil',quantity,disposition,location:'Row 2, B',...changes});
  const source = (quantity=5,id='cards',rows=[row(quantity)]) => ({order_id:'fixture-order',component_id:id,
    kind:'cards',label:'Pending cards',known_cards:quantity,box_candidates:quantity,basic_excluded:0,
    recorded_elsewhere:0,unknown:false,problem:null,rows,omitted_rows:0});
  const forecast = (quantity=5) => ({status:'ready',basis:'known_pending_loose_cards',stale:false,
    current_cards:3,capacity:10,known_loose_cards:quantity,box_candidates:quantity,basic_excluded:0,recorded_elsewhere:0,
    possible_current_holder_shortfall:Math.min(quantity,2),cards_if_candidates_filed:3+quantity,over_if_candidates_filed:3+quantity>10,
    pending_products:{count:0,known_reference_cards:0,unknown_contents:0},tokens_excluded:{known_cards:0,unknown_components:0},
    unknown_sources:0,sources:quantity?[source(quantity)]:[],omitted_sources:0,problems:[]});
  const rich = () => {
    const value=forecast(12);value.status='partial';value.box_candidates=5;value.basic_excluded=3;value.recorded_elsewhere=4;
    value.cards_if_candidates_filed=8;value.over_if_candidates_filed=false;
    value.sources=[{...source(12),box_candidates:5,basic_excluded:3,recorded_elsewhere:4,rows:[row(5),
      row(3,'basic',{name:'Forest',collector_number:'280',finish:'foil',location:''}),
      row(4,'elsewhere',{name:'Elvish Mystic',set:'cmm',collector_number:'648',location:'Binder'})]},
      {order_id:'fixture-order',component_id:'precon',kind:'product',label:'Pending product',known_cards:60,
        box_candidates:null,basic_excluded:0,recorded_elsewhere:null,unknown:false,problem:'product_choice',rows:[],omitted_rows:0},
      {order_id:'fixture-order',component_id:'tokens',kind:'tokens',label:'Pending tokens',known_cards:2,
        box_candidates:null,basic_excluded:0,recorded_elsewhere:null,unknown:false,problem:'tokens_excluded',rows:[],omitted_rows:0},
      {order_id:'fixture-order',component_id:'bad-cards',kind:'cards',label:'Pending cards',known_cards:null,
        box_candidates:null,basic_excluded:0,recorded_elsewhere:null,unknown:true,problem:'invalid_cards',rows:[],omitted_rows:0}];
    value.pending_products={count:1,known_reference_cards:60,unknown_contents:0};
    value.tokens_excluded={known_cards:2,unknown_components:0};value.unknown_sources=1;
    value.problems=['products_undecided','tokens_excluded','source_unknown'];return value;
  };
  const data = value => ({space:'home',sha256:'s1',editable:true,rows:[original],storage:{error:null,rows:{'fdn|227|nonfoil':{held:1}}},
    locations:{ready:true,sha256:'a'.repeat(64),rows:{'fdn|227|nonfoil':'Row 2, B'}},storage_box:{...box},storage_forecast:value});
  const draw = (value=forecast(),options={}) => {
    const profile=options.profile||'matt',may=options.may||MAY.admin;
    as(profile,{...may,see_home_records:options.records??true,see_inventory:options.inventory||['home']});
    location.hash='#/collection?view=rows';routeToken++;
    return drawCollectionRows({...data(value),...options.data},options.space||'home',routeToken);
  };
  const note = () => main.querySelector('.col-storage-forecast');
  const more = () => note().querySelector('.col-forecast-more');
  const visible = () => note()&&!note().hidden;
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionForecastUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code
            + "\nassert.equal(writes,0);", True]), capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_current_box_is_unchanged_and_forecast_is_explicitly_conditional(self):
        self.run_js(r'''
          const cv=draw();assert(visible());
          assert.equal(cv.boxNote.textContent,'Storage box: about 3 of 10 cards (the copies not in built decks or products kept intact).');
          assert(note().textContent.includes('5 known pending card copies'));
          assert(note().textContent.includes('If only those candidates were filed in the box: about 8 cards against 10 places.'));
          assert(note().textContent.includes('does not predict final occupancy or guarantee'));
          assert(note().textContent.includes("same printing's recorded location"));
          assert(note().textContent.includes('Up to 2 of these known box candidates overlap current holder shortfalls'));
          assert(note().textContent.includes('none has been deducted or assigned'));
          assert.equal(note().getAttribute('aria-label'),'Pending delivery storage scenario');same(reads,[]);
          draw(forecast(20));assert(note().textContent.includes('conditional scenario exceeds capacity'));
          assert(!note().textContent.includes('will be over capacity'));
        ''')

    def test_sources_and_each_exclusion_are_inspectable_without_requests_or_writes(self):
        self.run_js(r'''
          draw(rich());const text=note().textContent;
          for(const words of ['12 known pending card copies','5 box candidates','Basic lands excluded: 3','off-box location: 4',
            'Pending products excluded: 1 product reference','60 known reference-list card copies','Tokens excluded: 2',
            'Unverified sources: 1','unknown copies are not counted as zero','fixture-order, cards','fixture-order, precon',
            'fixture-order, tokens','fixture-order, bad-cards','Forest','Foil','Binder'])assert(text.includes(words),words);
          assert(note().querySelector('details'));assert.equal(note().querySelectorAll('a').length,0);
          assert.equal(note().querySelectorAll('input').length,0);same(reads,[]);
        ''')

    def test_zero_is_a_valid_known_scenario_without_claiming_no_other_deliveries(self):
        self.run_js(r'''
          draw(forecast(0));assert(visible());assert(note().textContent.includes('0 known pending card copies'));
          assert(note().textContent.includes('about 3 cards against 10 places'));
          assert(!note().textContent.includes('No deliveries'));assert(!note().textContent.includes('Everything will fit'));
          assert.equal(more().hidden,true);
        ''')

    def test_stale_and_unavailable_baseline_never_show_a_combined_occupancy(self):
        self.run_js(r'''
          for(const stale of [true,false]){const value=forecast();value.status='partial';value.stale=stale;
            if(!stale)value.current_cards=null;value.cards_if_candidates_filed=null;value.over_if_candidates_filed=null;
            value.possible_current_holder_shortfall=null;value.problems=[stale?'snapshot_stale':'baseline_unavailable'];
            draw(value);assert(visible());assert(note().textContent.includes('No combined occupancy scenario'));
            assert(!note().textContent.includes('If only those candidates'));assert(note().textContent.includes('holder shortfalls is unknown'));
            if(stale)assert(note().textContent.includes('Last-snapshot facts'));}
        ''')

    def test_unknown_location_or_source_graph_keeps_known_quantities_without_routing(self):
        self.run_js(r'''
          for(const code of ['locations_unavailable','ambiguous_path']){const value=forecast();value.status='partial';
            value.box_candidates=value.recorded_elsewhere=value.cards_if_candidates_filed=value.over_if_candidates_filed=null;
            value.problems=[code];if(code==='locations_unavailable'){
              value.sources[0].box_candidates=value.sources[0].recorded_elsewhere=null;value.sources[0].rows[0].disposition='unknown';}
            draw(value);assert(visible());assert(note().textContent.includes('5 known pending card copies'));
            assert(note().textContent.includes('How many belong in the box could not be checked'));
            assert(note().textContent.includes('No combined occupancy scenario'));}
        ''')

    def test_unknown_product_and_token_quantities_are_separate_from_loose_cards(self):
        self.run_js(r'''
          const value=rich();value.pending_products.known_reference_cards=0;value.pending_products.unknown_contents=1;
          value.sources[1].known_cards=null;value.sources[1].unknown=true;value.unknown_sources++;
          value.tokens_excluded={known_cards:0,unknown_components:1};value.sources[2].known_cards=null;value.sources[2].unknown=true;value.unknown_sources++;
          draw(value);assert(visible());assert(note().textContent.includes('1 reference with unknown contents'));
          assert(note().textContent.includes('1 component with unknown quantity'));assert(note().textContent.includes('12 known pending card copies'));
          assert(note().textContent.includes('about 8 cards against 10 places'));
        ''')

    def test_private_public_home_and_foreign_admin_views_never_keep_forecast_facts(self):
        self.run_js(r'''
          const raw=forecast();Object.defineProperty(raw,'sources',{get(){throw Error('Private contents consumed');}});
          for(const options of [{profile:'user2',may:MAY.user2,records:false},{profile:'user2',may:{admin:true},records:true},
            {profile:'matt',records:false},{profile:'user1',records:false},{space:'user2',data:{space:'user2'}}]){
            const cv=draw(raw,options);assert.equal(cv.storageForecast,null);assert(!visible());assert(!Object.hasOwn(cv.data,'storage_forecast'));}
          const cv=draw(forecast());state.may={...state.may};delete state.may.see_home_records;
          colTakeLocations(cv,data(forecast()));assert.equal(cv.storageForecast,null);assert(!visible());
        ''')

    def test_home_member_read_only_view_can_inspect_without_edit_capability(self):
        self.run_js(r'''
          const cv=draw(forecast(),{profile:'user1',may:MAY.user1,data:{editable:false}});
          assert.equal(cv.editable,false);assert(visible());assert(note().textContent.includes('5 known pending'));
          same(reads,[]);assert.equal(note().querySelectorAll('input').length,0);
        ''')

    def test_missing_null_legacy_and_success_answers_clear_forecast_but_keep_current_box(self):
        self.run_js(r'''
          for(const answer of [{rows:[original],storage_box:{...box}},{rows:[original],storage_forecast:null,storage_box:{...box}},null]){
            const cv=draw();colTakeLocations(cv,answer);assert.equal(cv.storageForecast,null);assert(note().hidden);assert.equal(note().textContent,'');
            drawColStorageBox(cv);assert(!cv.boxNote.hidden);assert(cv.boxNote.textContent.includes('about 3 of 10'));}
          let cv=draw();colTakeRows(cv,{rows:[original]});assert(!visible());
          cv=draw();colChanged(cv,{ok:true,sha256:'s2',rows:[original],storage_box:{...box}},null);assert(!visible());
        ''')

    def test_permission_profile_object_id_and_route_loss_clear_without_reviving_old_facts(self):
        self.run_js(r'''
          for(const change of [()=>state.may.see_home_records=false,()=>state.profile={...state.profile},
            ()=>state.profile.id='another',()=>location.hash='#/collection?space=user2',()=>routeToken++]){
            const cv=draw(),profile=state.profile,oldId=profile.id;change();drawColStorageBox(cv);
            assert.equal(cv.storageForecast,null);assert(note().hidden);assert.equal(note().textContent,'');profile.id=oldId;}
          const cv=draw();state.may.see_home_records=false;drawColStorageBox(cv);state.may.see_home_records=true;
          drawColStorageBox(cv);assert(!visible());
        ''')

    def test_facts_are_deeply_frozen_whitelisted_and_independent_of_later_rows(self):
        self.run_js(r'''
          const raw=forecast();raw.secret='PRIVATE';raw.sources[0].error='PRIVATE';raw.sources[0].rows[0].notes='PRIVATE';
          const cv=draw(raw),copy=cv.storageForecast;assert(Object.isFrozen(copy));assert(Object.isFrozen(copy.sources));
          assert(Object.isFrozen(copy.sources[0]));assert(Object.isFrozen(copy.sources[0].rows[0]));
          assert(Object.isFrozen(copy.pending_products));assert(!JSON.stringify(copy).includes('PRIVATE'));
          raw.sources[0].rows[0].name='Changed response';raw.known_loose_cards=999;cv.rows[0].quantity=999;
          drawColStorageBox(cv);assert(!note().textContent.includes('Changed response'));assert(!note().textContent.includes('999'));
          assert(note().textContent.includes('5 known pending'));assert(!Object.hasOwn(cv.data,'storage_forecast'));
        ''')

    def test_malformed_and_unconserved_facts_show_static_unknown_without_private_details(self):
        self.run_js(r'''
          const changes=[x=>x.status='running',x=>x.basis='PRIVATE',x=>x.known_loose_cards++,x=>x.box_candidates++,
            x=>x.cards_if_candidates_filed++,x=>x.over_if_candidates_filed=true,x=>x.capacity=-1,x=>x.stale='true',
            x=>x.unknown_sources=1,x=>x.sources[0].known_cards++,x=>x.sources[0].rows[0].quantity++,
            x=>x.sources[0].rows[0].disposition='elsewhere',x=>x.sources[0].rows[0].name='PRIVATE\nSECRET',
            x=>x.sources[0].component_id='../PRIVATE',x=>x.sources.push({...x.sources[0]}),x=>x.problems=['PRIVATE_ERROR'],
            x=>x.sources[0].problem='PRIVATE_ERROR',x=>x.sources[0].label='PRIVATE_ERROR',x=>x.known_loose_cards=NaN,
            x=>x.known_loose_cards=1000000001,x=>x.pending_products.count=1,x=>x.tokens_excluded.known_cards=1];
          for(const change of changes){const raw=forecast();change(raw);const cv=draw(raw);assert(cv.storageForecast.unverified);
            assert(note().textContent.includes('could not be verified'));assert(!note().textContent.includes('If only those'));
            assert(!note().textContent.includes('PRIVATE'));assert(!note().querySelector('details'));}
        ''')

    def test_text_is_never_html_and_unknown_raw_errors_never_render(self):
        self.run_js(r'''
          const raw=forecast();raw.sources[0].rows[0].name='<script>Fixture</script>';raw.error='PRIVATE_PASSWORD';
          raw.sources[0].error='PRIVATE_PATH';draw(raw);assert(visible());assert(!note().querySelector('script'));
          assert(note().textContent.includes('<script>Fixture</script>'));assert(!note().textContent.includes('PRIVATE'));
        ''')

    def test_first_paint_is_bounded_and_all_returned_sources_can_be_expanded_locally(self):
        self.run_js(r'''
          const raw=forecast(101);raw.sources=Array.from({length:100},(_,i)=>source(1,'cards-'+i));raw.omitted_sources=1;
          raw.status='partial';raw.problems=['details_omitted'];const cv=draw(raw),host=note();
          const sourceList=host.querySelector('ol');assert.equal(sourceList.children.length,20);assert(!more().hidden);
          assert(host.textContent.includes('1 further source omitted'));for(let i=0;i<4;i++)more().click();
          assert.equal(sourceList.children.length,100);assert(more().hidden);assert.equal(document.activeElement,sourceList);
          assert(host.textContent.includes('100 of 100 returned sources'));same(reads,[]);
          const value=cv.storageForecast;drawColRowList(cv);assert.equal(cv.storageForecast,value);assert.equal(note(),host);
          assert.equal(sourceList.children.length,100);
        ''')

    def test_omitted_detail_rows_are_explicit_and_never_guessed_from_current_collection(self):
        self.run_js(r'''
          const raw=forecast(105);raw.sources[0].rows=Array.from({length:100},()=>row(1));raw.sources[0].omitted_rows=5;
          raw.status='partial';raw.problems=['details_omitted'];draw(raw);
          assert(note().textContent.includes('5 printing detail rows omitted'));assert(note().textContent.includes('105 known pending'));
          for(const mutate of [x=>x.sources.push(source(1,'extra')),x=>x.sources=Array(101).fill(x.sources[0])]){
            const value=forecast(105);value.sources[0].rows=raw.sources[0].rows;value.sources[0].omitted_rows=5;mutate(value);
            draw(value);assert(note().textContent.includes('could not be verified'));}
        ''')

    def test_retired_more_buttons_cannot_expand_after_refresh_route_permission_or_new_dialog(self):
        self.run_js(r'''
          const many=()=>{const raw=forecast(25);raw.sources=Array.from({length:25},(_,i)=>source(1,'cards-'+i));return raw;};
          for(const change of [(cv)=>colTakeLocations(cv,data(forecast())),()=>location.hash='#/library',
            ()=>state.may.see_home_records=false,()=>document.body.append(el('dialog',{open:true}))]){
            const cv=draw(many()),old=more(),list=note().querySelector('ol');change(cv);old.click();
            assert.equal(list.children.length,20);for(const dialog of document.querySelectorAll('dialog'))dialog.remove();}
          const cv=draw(many()),old=more(),oldList=note().querySelector('ol');draw();old.click();assert.equal(oldList.children.length,20);
          assert.equal(note().querySelector('ol').children.length,1);same(reads,[]);
        ''')

    def test_late_existing_row_read_never_publishes_forecast_into_a_new_profile_or_view(self):
        self.run_js(r'''
          const cv=draw();cv.rows=null;cv.sha256=null;let resolve;
          api=path=>{reads.push(path);return new Promise(done=>resolve=done);};const pending=colEnsureRows(cv);
          const fresh=draw(forecast(1));const text=note().textContent;resolve(data(rich()));await assert.rejects(pending,/collection view changed/);
          assert.equal(note().textContent,text);assert.equal(fresh.storageForecast.known_loose_cards,1);assert.equal(cv.storageForecast,null);
          const active=fresh;active.rows=null;active.sha256=null;const late=colEnsureRows(active);state.may.see_home_records=false;
          resolve(data(forecast()));await late;assert.equal(active.storageForecast,null);assert(note().hidden);
        ''')

    def test_ambiguous_source_graph_cannot_render_numeric_routing_or_projection(self):
        self.run_js(r'''
          for(const code of ['invalid_record','ambiguous_path','missing_order','product_status','sources_unavailable']){
            const raw=rich();raw.sources[3].problem=code;draw(raw);
            assert(note().textContent.includes('could not be verified'),code);assert(!note().textContent.includes('If only those candidates'));
            raw.box_candidates=raw.recorded_elsewhere=raw.cards_if_candidates_filed=raw.over_if_candidates_filed=null;
            const cv=draw(raw);assert(!cv.storageForecast.unverified,code);assert(note().textContent.includes('12 known pending'));
            assert(note().textContent.includes('No combined occupancy scenario'));}
        ''')

    def test_backend_shaped_product_status_provenance_does_not_invent_a_product_component(self):
        self.run_js(r'''
          for(const problem of ['product_status','missing_order']){const raw=forecast(0);raw.status='partial';
            raw.box_candidates=raw.recorded_elsewhere=raw.cards_if_candidates_filed=raw.over_if_candidates_filed=null;
            raw.unknown_sources=1;raw.problems=['source_unknown'];raw.sources=[{order_id:null,component_id:null,
              kind:'unknown',label:'Unverified source',known_cards:null,box_candidates:null,basic_excluded:0,
              recorded_elsewhere:null,unknown:true,problem,rows:[],omitted_rows:0}];
            const cv=draw(raw);assert(!cv.storageForecast.unverified);assert(note().textContent.includes('Pending products excluded: 0 product references'));
            assert(note().textContent.includes('Unverified sources: 1'));assert(!note().textContent.includes('If only those candidates'));}
        ''')

    def test_superseded_existing_reads_never_overwrite_a_newer_forecast_or_saved_answer(self):
        self.run_js(r'''
          const cv=draw();cv.rows=null;cv.sha256=null;const pending=[];
          api=()=>new Promise(done=>pending.push(done));const first=colEnsureRows(cv),second=colEnsureRows(cv);
          assert.equal(pending.length,1);pending[0](data(forecast(1)));await Promise.all([first,second]);
          assert.equal(cv.storageForecast.known_loose_cards,1);assert.equal(cv.sha256,'s1');assert(Array.isArray(cv.rows));
          cv.rows=null;cv.sha256=null;const old=colEnsureRows(cv);colChanged(cv,{...data(forecast(2)),ok:true},null);
          pending[1](data(forecast(7)));await old;assert.equal(cv.storageForecast.known_loose_cards,2);
          assert(note().textContent.includes('2 known pending'));assert(!note().textContent.includes('7 known pending'));
        ''')

    def test_concurrent_location_and_write_readers_share_one_verified_completion(self):
        self.run_js(r'''
          const cv=draw();cv.rows=null;cv.sha256=null;cv.locations=null;let resolve;
          api=path=>{reads.push(path);return new Promise(done=>resolve=done);};
          const sheet=colOpenSheet('Fixture location'),ctx={cv,sheet};
          sheet.body.append(colLocationField(ctx,original,key=>'fixture-'+key));assert(ctx.location.input.disabled);
          const first=colEnsureRows(cv),second=colEnsureRows(cv);assert.equal(reads.length,1);
          resolve(data(forecast()));await Promise.all([first,second]);await flush();
          assert.equal(cv.sha256,'s1');assert(Array.isArray(cv.rows));assert(!ctx.location.input.disabled);
          assert.equal(ctx.location.input.value,'Row 2, B');assert.equal(cv.rowsPending,null);
        ''')

    def test_find_response_without_rows_aborts_pending_read_instead_of_resolving_incomplete(self):
        self.run_js(r'''
          as('matt',{...MAY.admin,see_home_records:true,see_inventory:['home']});location.hash='#/collection';routeToken++;
          const find={space:'home',cards:[],total:0,page:1,pages:1};
          const cv=drawCollection(find,new URLSearchParams(),'home',routeToken);let resolve,caught;
          api=path=>path.startsWith('/api/collection/rows')?new Promise(done=>resolve=done):Promise.resolve(find);
          const pending=colEnsureRows(cv).catch(error=>caught=error);await colLoadFind(cv,new URLSearchParams(),false);
          resolve(data(forecast()));await pending;assert(caught.message.includes('collection view changed'));
          assert.equal(cv.rows,null);assert.equal(cv.sha256,null);assert.equal(cv.storageForecast,null);
          api=async()=>data(forecast(1));await colEnsureRows(cv);assert.equal(cv.sha256,'s1');assert(Array.isArray(cv.rows));
        ''')

    def test_unknown_capped_stale_answer_keeps_no_occupancy_and_does_not_mean_no_deliveries(self):
        self.run_js(r'''
          const raw=forecast(0);raw.status='unknown';raw.stale=true;raw.box_candidates=raw.recorded_elsewhere=null;
          raw.cards_if_candidates_filed=raw.over_if_candidates_filed=null;raw.possible_current_holder_shortfall=null;
          raw.problems=['work_limit','snapshot_stale'];const cv=draw(raw);assert(!cv.storageForecast.unverified);
          assert(note().textContent.includes('checking limit was reached'));assert(note().textContent.includes('Last-snapshot facts'));
          assert(note().textContent.includes('No combined occupancy scenario'));assert(!note().textContent.includes('No deliveries'));
        ''')

    def test_find_refresh_never_retains_unvalidated_raw_forecast_in_view_data(self):
        self.run_js(r'''
          as('matt',{...MAY.admin,see_home_records:true,see_inventory:['home']});location.hash='#/collection';routeToken++;
          const initial={space:'home',cards:[],total:0,page:1,pages:1,storage_forecast:forecast()};
          const cv=drawCollection(initial,new URLSearchParams(),'home',routeToken);assert(!Object.hasOwn(cv.data,'storage_forecast'));
          api=async()=>({...initial,storage_forecast:{PRIVATE:'not a checked answer'}});
          await colLoadFind(cv,new URLSearchParams(),false);assert(!Object.hasOwn(cv.data,'storage_forecast'));
          assert(!JSON.stringify(cv.data).includes('PRIVATE'));
        ''')

    def test_real_backend_json_roundtrip_keeps_graph_unknown_and_shortfall_overlap_truthful(self):
        support = backend_support
        inv = support.fixture()
        supply = support.pool.Pool(Counter({"Llanowar Elves": 999}), {},
            [SimpleNamespace(cards=Counter({"Llanowar Elves": 20}))])
        with mock.patch.object(support.forecast.guard, "sees_home_records", return_value=True), \
                mock.patch.object(support.cards, "resolve", side_effect=lambda name: name), \
                mock.patch.object(support.decks, "is_basic_land", return_value=False), \
                mock.patch.object(support.pool, "load_pool", return_value=supply), \
                mock.patch.object(support.config, "load", side_effect=AssertionError("Private config forbidden")), \
                mock.patch.object(support.inventory, "apply", side_effect=AssertionError("Writes forbidden")):
            with support.inventory.pinned(inv):
                valid = support.forecast.build("home", [], support.BOX)
            statuses = (support.StatusRow.make(file="duplicate.csv", status="ordered"),
                        support.StatusRow.make(file="duplicate.csv", status="ordered"),
                        support.StatusRow.make(file="orphan.csv", status="ordered"))
            graph = inv.replace(status=support.Sheet(support.paths.STATUS, tuple(support.rules.STATUS_FIELDS), statuses, True))
            with support.inventory.pinned(graph):
                ambiguous = support.forecast.build("home", [], support.BOX)
        self.assertEqual(valid["possible_current_holder_shortfall"], 4)  # shortage19, arrivals4: overlap only
        self.assertEqual(ambiguous["pending_products"]["count"], 0)
        self.assertIsNone(ambiguous["box_candidates"])
        self.assertTrue(any(item["problem"] == "product_status" for item in ambiguous["sources"]))
        self.assertTrue(any(item["problem"] == "missing_order" for item in ambiguous["sources"]))
        self.run_js("const replies=" + json.dumps([valid, ambiguous]) + ";const actualBox=" + json.dumps(support.BOX) + r''';
          let cv=draw(replies[0],{data:{storage_box:actualBox}});assert(!cv.storageForecast.unverified);
          assert(note().textContent.includes('Up to 4 of these known box candidates overlap current holder shortfalls'));
          assert(!note().textContent.includes('shortfall: 4'));assert(note().textContent.includes('about 104 cards against 110 places'));
          cv=draw(replies[1],{data:{storage_box:actualBox}});assert(!cv.storageForecast.unverified);
          assert(note().textContent.includes('4 known pending card copies'));assert(note().textContent.includes('Unverified sources: 2'));
          assert(note().textContent.includes('Pending products excluded: 0 product references'));
          assert(note().textContent.includes('No combined occupancy scenario'));assert(!note().textContent.includes('If only those candidates'));
        ''')
