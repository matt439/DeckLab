"""Saved nonfoil shop evidence on combined missing cards, over the real UI and a disposable DOM.

Run with python scripts/test_fixtures.py decklab.tests.test_shopping_missing_snapshot_ui.
No live browser, shop, server, snapshot, configuration or database is accessed.
"""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MissingSnapshotUiTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_missing_js(self, scenario):
        self.run_js("""
          state.may={admin:true,orders:true,see_inventory:['home']};
          const reads=[],writes=[];
          api=async path=>{reads.push(path);throw new Error('Unexpected read');};
          apiWrite=async(...args)=>{writes.push(args);throw new Error('Unexpected write');};
          const snap=(extra={})=>({shop:'MTGMate',scope:'nonfoil',status:'in_stock',
            fetched_at:'2025-10-12T03:05:00+11:00',price_aud:'0.25',stock:7,set:'fdn',collector_number:'100',
            finish:'nonfoil',url:'https://www.mtgmate.com.au/cards/Alpha/FDN/100',in_stock_printings:99,
            error:null,back_in_stock:false,newly_in_stock:false,carried:true,...extra});
          const missing=(extra={})=>({name:'Alpha',missing:5,card:null,
            decks:[{id:'casual/a',title:'Deck A',missing:2},{id:'casual/b',title:'Deck B',missing:3}],
            queue:[],shop_snapshot:snap(),...extra});
          const data=(rows=[missing()],queue=[],extra={})=>({...empty,queue_revision:'q1',queue_decks:[],
            to_buy:queue,missing_cards:{ready:true,rows,errors:[],warnings:[],totals:{}},
            shop_snapshot:{shop:'MTGMate',fetched_at:'2026-10-28T03:40:00+11:00'},...extra});
          const draw=packet=>{clear(main);return drawShopping(packet);};
          const article=()=>main.querySelector('.shop-missing-card');
          const line=()=>article().querySelector('.shop-missing-snapshot');
          const noEffects=()=>{assert.equal(reads.length,0);assert.equal(writes.length,0);};
          toast=()=>{};
        """ + scenario)

    def test_combined_shortfall_shows_unit_evidence_and_selected_printing_stock_only(self):
        self.run_missing_js("""
          const packet=data(),before=JSON.stringify(packet);draw(packet);
          assert(article().textContent.includes('5 copies missing across 2 decks'));
          assert(line().textContent.includes('Cheapest nonfoil in saved snapshot'));
          assert(line().textContent.includes('MTGMate: A$0.25 each; 7 copies of this printing in stock when fetched.'));
          assert(!line().textContent.includes('99'));assert(!line().textContent.includes('A$1.25'));
          assert(line().textContent.includes('FDN 100 nonfoil'));
          assert.equal(line().querySelector('a').getAttribute('href'),'https://www.mtgmate.com.au/cards/Alpha/FDN/100');
          assert.equal(line().querySelector('a').getAttribute('target'),'_blank');
          assert.equal(line().querySelector('a').getAttribute('rel'),'noopener noreferrer');
          assert.equal(line().querySelectorAll('button').length,0);assert.equal(line().querySelectorAll('input').length,0);
          assert.equal(JSON.stringify(packet),before);noEffects();
        """)

    def test_carried_entry_keeps_its_old_fetch_date_and_visible_year_not_the_file_date(self):
        self.run_missing_js("""
          draw(data());const time=line().querySelector('time');
          assert.equal(time.getAttribute('datetime'),'2025-10-12T03:05:00+11:00');
          assert.equal(time.getAttribute('title'),'2025-10-12T03:05:00+11:00');
          assert(time.textContent.includes('2025'));assert(!time.textContent.includes('2026'));
          assert(!line().textContent.includes('today'));assert(!line().textContent.includes('current price'));
          noEffects();
        """)

    def test_exact_foil_queue_intent_and_recorded_research_stay_independent_of_generic_nonfoil_evidence(self):
        self.run_missing_js("""
          const queued=row('Alpha',{queue_row:1,quantity:9,for:'Exact deck',printing:'exact',set:'old',
            collector_number:'9',finish:'foil',listed_at:'Recorded shop',listed_aud:'40.00',checked:'2026-10-01',
            in_stock:'no',notes:'Keep exact request',state:'waiting_for_stock',
            shop_snapshot:{...snap(),scope:undefined,price_aud:'12.00',stock:1,set:'old',collector_number:'9',finish:'foil'}});
          const packet=data([missing({queue:[{...queued}]})],[queued]),before=JSON.stringify(packet);
          draw(packet);
          const intent=article().querySelector('.shop-missing-queue');
          assert(intent.textContent.includes('9 queued'));assert(intent.textContent.includes('Exact: OLD 9 foil'));
          assert(intent.textContent.includes('Reference price A$40.00 at Recorded shop'));
          assert(intent.textContent.includes('Checked 2026-10-01'));assert(intent.textContent.includes('Out of stock when checked'));
          assert(line().textContent.includes('A$0.25 each'));assert(!line().textContent.includes('A$12.00'));
          const queueNodes=main.querySelectorAll('[data-shop-queue]');
          assert(queueNodes.some(node=>node.textContent.includes('MTGMate: A$12.00, 1 in stock')));
          assert.equal(JSON.stringify(packet),before);assert.equal(queued.quantity,9);noEffects();
        """)

    def test_missing_row_with_no_queue_never_borrows_an_unrelated_or_stale_queue_snapshot(self):
        self.run_missing_js("""
          const queued=row('Beta',{queue_row:1,quantity:8,shop_snapshot:snap({price_aud:'9.00'})});
          const item=missing({shop_snapshot:null,queue:[row('Alpha',{shop_snapshot:snap({price_aud:'4.00'})})]});
          draw(data([item],[queued]));
          assert(article().textContent.includes('Not in the purchase queue.'));
          assert.equal(line().getAttribute('data-shop-missing-snapshot'),'not_checked');
          assert(line().textContent.includes('no saved nonfoil check for this card'));
          assert(!line().textContent.includes('A$'));assert.equal(line().querySelector('time'),null);noEffects();
        """)

    def test_out_of_stock_zero_and_one_physical_copy_have_distinct_fixed_words(self):
        self.run_missing_js("""
          draw(data([missing({shop_snapshot:snap({status:'out_of_stock',stock:0})})]));
          assert(line().textContent.includes('nonfoil out of stock in the saved check (listed at A$0.25 each)'));
          assert(!line().textContent.includes('Cheapest'));assert(!line().textContent.includes('99'));
          assert.equal(line().querySelectorAll('time').length,1);
          draw(data([missing({missing:0,shop_snapshot:snap({stock:1})})]));
          assert(article().textContent.includes('0 copies missing'));
          assert(line().textContent.includes('1 copy of this printing in stock when fetched'));
          assert(!line().textContent.includes('1 copies'));noEffects();
        """)

    def test_not_listed_means_no_nonfoil_printing_and_unknown_never_quotes_raw_errors(self):
        self.run_missing_js("""
          draw(data([missing({shop_snapshot:snap({status:'not_listed',price_aud:null,stock:null,
            set:null,collector_number:null,finish:null,url:null})})]));
          assert(line().textContent.includes('no nonfoil printing listed in the saved check'));
          assert(!line().textContent.includes('A$'));assert.equal(line().querySelector('a'),null);
          assert.equal(line().querySelector('time').getAttribute('datetime'),'2025-10-12T03:05:00+11:00');
          draw(data([missing({shop_snapshot:snap({status:'unknown',error:'SECRET private cache path',
            price_aud:'999.00',stock:888,back_in_stock:true,newly_in_stock:true})})]));
          assert(line().textContent.includes('nonfoil price unknown in the saved snapshot'));
          assert(!line().textContent.includes('A$'));assert(!line().textContent.includes('SECRET'));
          assert.equal(line().getAttribute('title'),null);
          assert(!line().querySelector('a'));assert(!line().textContent.includes('Back in stock'));
          assert(!line().textContent.includes('Newly in stock'));noEffects();
        """)

    def test_absent_and_not_checked_packets_never_inherit_the_global_snapshot_time(self):
        self.run_missing_js("""
          for(const value of [undefined,null,snap({status:'not_checked',fetched_at:'2026-10-28T03:40:00+11:00'})]){
            draw(data([missing({shop_snapshot:value})]));
            assert.equal(line().getAttribute('data-shop-missing-snapshot'),'not_checked');
            assert.equal(line().querySelector('time'),null);assert(!line().textContent.includes('A$'));
            assert(line().textContent.includes('no saved nonfoil check'));
          }
          assert(main.querySelector('#shop-missing-cards').closest('section').textContent
            .includes('Saved shop checks cover only names already in the snapshot'));noEffects();
        """)

    def test_malformed_price_or_stock_never_becomes_a_free_price_or_a_physical_quantity(self):
        self.run_missing_js("""
          const badPrices=[0,0.25,true,null,'','0.00','-1.00','NaN','Infinity','1e3','00.25','1.001','1000000000.00'];
          const badStocks=[true,false,null,'7',-1,.5,1000000001,NaN,Infinity];
          for(const extra of [...badPrices.map(price_aud=>({price_aud})),...badStocks.map(stock=>({stock})),
              {status:'in_stock',stock:0},{status:'out_of_stock',stock:7}]){
            draw(data([missing({shop_snapshot:snap(extra)})]));
            assert.equal(line().getAttribute('data-shop-missing-snapshot'),'unknown');
            assert(!line().textContent.includes('A$'));assert(!line().textContent.includes('in stock when fetched'));
            assert.equal(line().querySelector('time'),null);assert.equal(line().querySelector('a'),null);
          }
          noEffects();
        """)

    def test_impossible_or_timezone_free_timestamps_do_not_date_any_price_claim(self):
        self.run_missing_js("""
          for(const fetched_at of [null,123,'','not a date','2026-10-28','2026-10-28T03:05:00',
              '2026-02-30T03:05:00Z','2025-02-29T03:05:00Z','2026-13-01T03:05:00Z',
              '2026-10-28T24:05:00Z','2026-10-28T03:60:00Z','2026-10-28T03:05:60Z',
              '2026-10-28T03:05:00+24:00','2026-10-28T03:05:00+11:60']){
            draw(data([missing({shop_snapshot:snap({fetched_at})})]));
            assert.equal(line().getAttribute('data-shop-missing-snapshot'),'unknown');
            assert(!line().textContent.includes('A$'));assert.equal(line().querySelector('time'),null);
          }
          const date='2024-02-29T03:05:00.123456+11:00';
          draw(data([missing({shop_snapshot:snap({fetched_at:date})})]));
          assert.equal(line().querySelector('time').getAttribute('datetime'),date);noEffects();
        """)

    def test_wrong_scope_finish_shop_status_or_printing_uses_only_fixed_unknown_text(self):
        self.run_missing_js("""
          for(const extra of [{scope:undefined},{scope:'exact'},{scope:'foil'},{finish:'foil'},
              {shop:'SECRET shop'},{status:'SECRET status'},{set:'BAD'}, {set:'a'.repeat(13)},
              {collector_number:' 12'},{collector_number:'x/y'},{collector_number:'x?y'},
              {collector_number:'x#y'},{collector_number:'x\\u0000y'},
              {collector_number:'\\ud800'},{collector_number:'x\\udfffy'}]){
            draw(data([missing({shop_snapshot:snap({...extra,error:'SECRET raw error'})})]));
            assert.equal(line().getAttribute('data-shop-missing-snapshot'),'unknown');
            assert(!line().textContent.includes('SECRET'));assert(!line().textContent.includes('A$'));
            assert.equal(line().getAttribute('title'),null);assert.equal(line().querySelector('a'),null);
          }
          for(const value of [3,'SECRET packet',[],{}]){
            const node=shopMissingSnapshotLine({shop_snapshot:value});
            assert.equal(node.getAttribute('data-shop-missing-snapshot'),'unknown');assert(!node.textContent.includes('SECRET'));
          }
          noEffects();
        """)

    def test_only_safe_mtgmate_card_links_are_exposed_and_unsafe_links_do_not_echo(self):
        self.run_missing_js("""
          for(const url of ['https://www.mtgmate.com.au:443/cards/Alpha/FDN/100',
              'HTTPS://WWW.MTGMATE.COM.AU/cards/Alpha/FDN/100']){
            draw(data([missing({shop_snapshot:snap({url})})]));
            assert.equal(line().querySelector('a').getAttribute('href'),new URL(url).href);
          }
          for(const url of ['javascript:alert(1)','http://www.mtgmate.com.au/cards/Alpha',
              'https://example.com/cards/Alpha','https://www.mtgmate.com.au.evil.example/cards/Alpha',
              'https://user:SECRET@www.mtgmate.com.au/cards/Alpha','https://www.mtgmate.com.au:8443/cards/Alpha',
              'https://www.mtgmate.com.au:444/cards/Alpha',
              'https://www.mtgmate.com.au/cards/Alpha?SECRET=1','https://www.mtgmate.com.au/cards/Alpha#SECRET',
              'https://www.mtgmate.com.au/not-cards/Alpha','https://www.mtgmate.com.au/cards/',
              'https://www.mtgmate.com.au/cards/Alpha\\nSECRET','https://www.mtgmate.com.au/cards/Alpha\\\\SECRET',
              'https://www.mtgmate.com.au/cards/\\ud800','https://www.mtgmate.com.au/cards/\\udfff',
              'https://www.mtgmate.com.au/cards/%ED%A0%80','https://www.mtgmate.com.au/cards/%FF',
              'https://www.mtgmate.com.au/cards/%00SECRET']){
            draw(data([missing({shop_snapshot:snap({url})})]));
            assert.equal(line().querySelector('a'),null);assert(!line().textContent.includes('SECRET'));
            assert(line().textContent.includes('A$0.25 each'));
          }
          noEffects();
        """)

    def test_literal_printing_names_and_all_error_fields_cannot_create_markup_or_stock_chips(self):
        self.run_missing_js("""
          const bad='<img src=x onerror=secret>';
          draw(data([missing({name:bad,shop_snapshot:snap({collector_number:bad,error:'SECRET error',
            back_in_stock:true,newly_in_stock:true,carried:'SECRET flag'})})]));
          assert(article().textContent.includes(bad));assert(line().textContent.includes(bad));
          assert.equal(article().querySelectorAll('img').length,0);assert.equal(article().querySelectorAll('script').length,0);
          assert(!line().textContent.includes('SECRET'));assert(!line().textContent.includes('Back in stock'));
          assert(!line().textContent.includes('Newly in stock'));assert.equal(line().getAttribute('title'),null);noEffects();
          const astral='12\\ud83c\\udf08',url='https://www.mtgmate.com.au/cards/Alpha_\\ud83c\\udf08/FDN/100';
          draw(data([missing({shop_snapshot:snap({collector_number:astral,url})})]));
          assert(line().textContent.includes(astral));assert(line().textContent.includes('A$0.25 each'));
          assert.equal(line().querySelector('a').getAttribute('href'),new URL(url).href);noEffects();
        """)

    def test_reprint_sources_deck_links_and_counts_survive_snapshot_enrichment_and_redraw(self):
        self.run_missing_js("""
          const reprints={ready:true,as_of:'2026-10-16',data_date:'2026-10-15',coverage:'Cached printings may be incomplete.',
            upcoming:[{set:'new',set_name:'New Set',released_at:'2026-11-10',source_url:'https://scryfall.com/card/new/7/alpha'}],
            upcoming_more:0,released:[],released_more:0,price_check:{offered:false},notes:[]};
          const packet=data([missing({reprints})]),before=JSON.stringify(packet),view=draw(packet);
          const deckLinks=article().querySelector('.shop-missing-decks').querySelectorAll('a').map(a=>a.getAttribute('href'));
          assert(article().querySelector('.reprint-info').textContent.includes('New Set (NEW)'));
          assert(article().querySelector('.reprint-info').textContent.includes('scheduled 2026-11-10'));
          view.redraw();assert.equal(article().querySelectorAll('.shop-missing-snapshot').length,1);
          assert.equal(JSON.stringify(article().querySelector('.shop-missing-decks').querySelectorAll('a').map(a=>a.getAttribute('href'))),
            JSON.stringify(deckLinks));
          assert(article().textContent.includes('5 copies missing across 2 decks'));
          assert.equal(JSON.stringify(packet),before);noEffects();
        """)

    def test_existing_page_load_adds_no_read_or_write_beyond_shopping_and_the_existing_visit_beacon(self):
        self.run_missing_js("""
          api=async path=>{reads.push(path);return data();};
          await route();same(reads,['/api/shopping']);same(writes,[['/api/visit',{route:'shopping'}]]);
          assert(line().textContent.includes('Cheapest nonfoil in saved snapshot'));
          assert.equal(line().querySelectorAll('button').length,0);
          assert.equal(line().querySelectorAll('input').length,0);
        """)
