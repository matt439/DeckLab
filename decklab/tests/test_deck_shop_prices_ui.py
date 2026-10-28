"""Saved unit evidence on deck Prices, in real script order over a disposable DOM.

Run: python scripts/test_fixtures.py decklab.tests.test_deck_shop_prices_ui
No server, shop, saved cache, real collection or browser is used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_deck_prices_ui import PRICES
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SHOP = r"""
  routeToken=71;location.hash='#/deck?id=casual%2Ftest&tab=cards';state.profile.space='home';
  const reads=[],writes=[];api=(...args)=>{reads.push(args);throw Error('No requests');};
  apiWrite=(...args)=>{writes.push(args);throw Error('No writes');};
  const savedShop=(extra={})=>({shop:'MTGMate',scope:'nonfoil',status:'in_stock',price_aud:'9.75',stock:1,
    set:'cmm',collector_number:'648',finish:'nonfoil',url:'https://www.mtgmate.com.au/cards/Alpha/CMM/648',
    fetched_at:'2025-10-20T12:34:56+00:00',carried:true,error:null,...extra});
  const withShop=(value=savedShop())=>{const owned=makePrices();owned.rows=owned.rows.map(row=>({...row,labels:{...row.labels}}));
    owned.rows.find(row=>row.name==='Alpha').shop_snapshot=value;return owned;};
  const evidence=table=>table.querySelector('.deck-shop-row');
  const facts=table=>evidence(table)?.querySelector('.shop-missing-snapshot');
  const noEffects=()=>{same(reads,[]);same(writes,[]);};
  const actualPage=owned=>{const page=makePage();page.owned=owned;
    deckSwapFinder=()=>{}; // unrelated Missing-filter suggestions have their own API fixtures
    deckOverviewSwap=()=>null; // the Overview's independent swap request is outside cached Prices
    deckNeighbours=()=>null;deckOverviewForge=()=>null;deckSideboardSection=()=>null;
    page.sections={Deck:owned.rows.map(row=>({name:row.name,qty:row.need,set:null,number:null,finish:'nonfoil',
      card:card(row.name,'Creature',1)}))};clear(main);location.hash='#/deck?id=casual%2Ftest&tab=cards';
    drawDeck(page,deckViewOf(parseHash().params));return{page,table:main.querySelector('.owned-table')};};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckShopPricesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + PRICES + SHOP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_unit_evidence_is_separate_from_estimates_totals_and_missing_quantity(self):
        self.run_js(r"""
          const owned=withShop(),before=JSON.stringify(owned),table=showPrices(owned),priceBody=bodies(table).get('Alpha');
          assert.equal(table.querySelector('colgroup').children.length,5);
          assert.equal(evidence(table).querySelector('td').getAttribute('colspan'),'5');
          assert.equal(priceBody.querySelectorAll('.deck-shop-row').length,1);
          assert(facts(table).textContent.includes('A$9.75 each; 1 copy of this printing in stock when fetched.'));
          assert(facts(table).textContent.includes('Cheapest nonfoil in saved snapshot'));
          assert(facts(table).textContent.includes('CMM 648 nonfoil'));
          assert(evidence(table).textContent.includes('It may differ from the printing or finish in your list.'));
          assert(evidence(table).textContent.includes('Price is per card'));assert(!table.textContent.includes('A$39.00'));
          assert(priceBody.textContent.includes('A$2.00 each (estimate)'));assert.equal(priceBody.querySelectorAll('td')[3].textContent,'8.00');
          assert(table.querySelector('tfoot').textContent.includes('A$28.00'));assert(main.textContent.includes('1.43 AUD'));
          assert.equal(JSON.stringify(owned),before);noEffects();
        """)

    def test_original_carried_timestamp_keeps_visible_year_and_safe_printing_link(self):
        self.run_js(r"""
          const table=showPrices(withShop()),line=facts(table),time=line.querySelector('time'),link=line.querySelector('a');
          assert.equal(time.getAttribute('datetime'),'2025-10-20T12:34:56+00:00');assert(time.textContent.includes('2025'));
          assert(!time.textContent.includes('2026'));assert(!line.textContent.includes('today'));
          assert.equal(link.getAttribute('href'),'https://www.mtgmate.com.au/cards/Alpha/CMM/648');
          assert.equal(link.getAttribute('rel'),'noopener noreferrer');assert.equal(link.getAttribute('target'),'_blank');noEffects();
        """)

    def test_failed_conversion_keeps_dated_shop_evidence_and_does_not_invent_an_estimate(self):
        self.run_js(r"""
          const owned=withShop();owned.price_error='Rate unavailable';const table=showPrices(owned),priceBody=bodies(table).get('Alpha');
          assert(priceBody.textContent.includes('No estimate'));assert.equal(priceBody.querySelectorAll('td')[3].textContent,'-');
          assert(facts(table).textContent.includes('A$9.75 each'));assert(main.textContent.includes('No A$ estimates: Rate unavailable'));
          assert(!table.querySelector('tfoot').textContent.includes('A$9.75'));noEffects();
        """)

    def test_statuses_do_not_borrow_scryfall_estimates_or_raw_errors(self):
        self.run_js(r"""
          for(const [value,expected] of [[savedShop({status:'out_of_stock',stock:0}),'nonfoil out of stock'],
              [savedShop({status:'not_listed'}),'no nonfoil printing listed'],
              [savedShop({status:'unknown',error:'PRIVATE cache path'}),'price unknown'],[null,'no saved nonfoil check']]){
            const table=showPrices(withShop(value)),line=facts(table);assert(line.textContent.includes(expected));
            assert(!line.textContent.includes('PRIVATE'));assert.equal(line.getAttribute('title'),null);
            if(value?.status!=='out_of_stock')assert(!line.textContent.includes('A$2.00'));
            assert.equal(line.querySelectorAll('button').length,0);assert.equal(line.querySelectorAll('input').length,0);}
          noEffects();
        """)

    def test_missing_fields_public_inventory_and_failed_inventory_keep_distinct_no_evidence_states(self):
        self.run_js(r"""
          assert.equal(ownedSection({}),null);const failed=ownedSection({owned:null});assert.equal(failed.querySelector('.deck-shop-row'),null);
          const table=showPrices(makePrices());assert.equal(evidence(table),null);
          for(const row of priceRows)assert(!Object.hasOwn(row,'shop_snapshot'));
          const owned=withShop();owned.rows[0].missing=0;assert.equal(evidence(showPrices(owned)),null);
          const fractional=withShop();fractional.rows[0].missing=.5;assert.equal(evidence(showPrices(fractional)),null);
          noEffects();
        """)

    def test_malformed_scope_price_stock_and_time_use_fixed_unknown_words(self):
        self.run_js(r"""
          for(const extra of [{scope:'exact'},{shop:'PRIVATE shop'},{price_aud:'NaN'},{price_aud:'0.00'},
              {price_aud:9.75},{stock:true},{stock:-1},{stock:'1'},{finish:'foil'},
              {fetched_at:'2026-02-30T01:00:00Z'},{fetched_at:'2026-10-28T01:00:00'},
              {collector_number:'bad\ud800'}, {status:'PRIVATE status'}]){
            const table=showPrices(withShop(savedShop(extra))),line=facts(table);
            assert.equal(line.getAttribute('data-shop-missing-snapshot'),'unknown');assert(!line.textContent.includes('A$'));
            assert(!line.textContent.includes('PRIVATE'));assert.equal(line.querySelector('time'),null);assert.equal(line.querySelector('a'),null);}
          noEffects();
        """)

    def test_literal_card_printing_and_error_text_cannot_create_markup(self):
        self.run_js(r"""
          const owned=withShop(savedShop({collector_number:'<img src=x onerror=secret>',error:'PRIVATE raw detail'}));
          owned.rows[0].name='<script>secret</script>';const table=showPrices(owned);
          assert(table.textContent.includes('<script>secret</script>'));assert(facts(table).textContent.includes('<img src=x onerror=secret>'));
          assert.equal(table.querySelectorAll('script').length,0);assert.equal(facts(table).querySelectorAll('img').length,0);
          assert(!facts(table).textContent.includes('PRIVATE'));noEffects();
        """)

    def test_unsafe_link_loses_only_link_while_validated_unit_evidence_remains(self):
        self.run_js(r"""
          for(const url of ['javascript:secret','https://example.com/cards/Alpha','https://user:secret@www.mtgmate.com.au/cards/Alpha',
              'https://www.mtgmate.com.au/cards/Alpha?secret=1','https://www.mtgmate.com.au/cards/%FF']){
            const table=showPrices(withShop(savedShop({url})));assert(facts(table).textContent.includes('A$9.75 each'));
            assert.equal(facts(table).querySelector('a'),null);assert(!facts(table).textContent.includes('secret'));}
          noEffects();
        """)

    def test_exact_foil_price_label_stays_separate_from_generic_nonfoil_check(self):
        self.run_js(r"""
          const owned=withShop();owned.rows[0].priced_finish='foil';owned.rows[0].priced_printing='FDN 227 foil';
          const before=JSON.stringify(owned),table=showPrices(owned),priceBody=bodies(table).get('Alpha');
          assert(priceBody.textContent.includes('foil price'));assert(facts(table).textContent.includes('CMM 648 nonfoil'));
          assert(evidence(table).textContent.includes('any nonfoil printing'));assert.equal(JSON.stringify(owned),before);noEffects();
        """)

    def test_all_sorts_move_one_complete_card_body_with_its_evidence_and_keep_totals(self):
        self.run_js(r"""
          const owned=withShop(),before=JSON.stringify(owned),table=showPrices(owned),original=bodies(table),line=facts(table),foot=table.querySelector('tfoot');
          const total=foot.textContent;for(const key of ['cost','name','missing','cost']){sortButton(table,key).click();
            assert.equal(facts(table),line);assert.equal(evidence(table).parentNode,original.get('Alpha'));
            assert.equal(table.querySelectorAll('.deck-shop-row').length,1);assert.equal(table.querySelector('tfoot'),foot);
            assert.equal(foot.textContent,total);for(const [name,body] of bodies(table))assert.equal(body,original.get(name));}
          assert.equal(JSON.stringify(owned),before);noEffects();
        """)

    def test_cards_filter_picture_and_tab_changes_keep_evidence_and_allow_current_table_sort(self):
        self.run_js(r"""
          const {table}=actualPage(withShop()),line=facts(table);sortButton(table,'cost').click();
          main.querySelector('.deck-filter').querySelectorAll('button').find(button=>button.textContent.startsWith('Missing')).click();
          buttonText(main.querySelector('.deck-cards-bar'),'Pictures').click();tab('overview').click();tab('cards').click();
          assert.equal(main.querySelector('.owned-table'),table);assert.equal(facts(table),line);
          sortButton(table,'name').click();assert.equal(sortButton(table,'name').parentNode.getAttribute('aria-sort'),'ascending');noEffects();
        """)

    def test_stale_profile_object_id_space_route_and_source_rows_cannot_sort(self):
        self.run_js(r"""
          const mutations=[()=>state.profile={...state.profile},()=>state.profile.id='user1',()=>state.profile.space='user2',
            ()=>state.profile=null,()=>routeToken++,()=>location.hash='#/deck?id=casual%2Fother&tab=cards',
            (table,owned)=>owned.rows=[...owned.rows],table=>table.remove()];
          for(const mutate of mutations){state.profile={id:'matt',name:'Matt',space:'home'};location.hash='#/deck?id=casual%2Ftest&tab=cards';
            const owned=withShop(),table=showPrices(owned),before=names(table);mutate(table,owned);sortButton(table,'cost').click();
            assert.equal(JSON.stringify(names(table)),JSON.stringify(before));assert.equal(sortedHeading(table).length,0);}
          noEffects();
        """)

    def test_detached_moved_or_replaced_header_controls_and_original_frame_cannot_sort(self):
        self.run_js(r"""
          const mutations=[(table,button)=>{const holder=el('div');main.append(holder);holder.append(button);},
            (table,button)=>button.parentNode.replaceChildren(el('button',{text:'Replacement'})),
            table=>{const holder=el('div');main.append(holder);holder.append(table.parentNode);},
            table=>{const head=table.querySelector('thead');head.remove();table.append(el('thead'));}];
          for(const mutate of mutations){const table=showPrices(withShop()),button=sortButton(table,'cost'),before=names(table);
            mutate(table,button);button.click();assert.equal(JSON.stringify(names(table)),JSON.stringify(before));assert.equal(sortedHeading(table).length,0);}
          noEffects();
        """)

    def test_original_deck_screen_data_and_current_list_route_own_sorting(self):
        self.run_js(r"""
          for(const mutate of [()=>deckScreen={...deckScreen},()=>deckScreen.data={...deckScreen.data},
              ()=>deckScreen.data.owned={...deckScreen.data.owned},
              ()=>location.hash='#/deck?id=casual%2Ftest&v=owned&tab=cards',()=>tab('overview').click()]){
            const {table}=actualPage(withShop()),before=names(table);mutate();sortButton(table,'cost').click();
            assert.equal(JSON.stringify(names(table)),JSON.stringify(before));assert.equal(sortedHeading(table).length,0);}
          noEffects();
        """)
