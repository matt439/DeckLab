"""Spare reasons and snapshot-owned, price-free copy controls in the existing Collection UI."""
import unittest

from decklab.tests import test_collection_find_layout_ui as collection_ui


@unittest.skipUnless(collection_ui.NODE, "Node.js is not installed")
class SpareUiTests(unittest.TestCase):
    def run_js(self, scenario):
        collection_ui.CollectionFindLayoutUiTests.run_js(self, r'''
          const copyText='2 Alpha (FDN) 1\n1 Another card (CMM) 2 *F*\n';
          const spareFacts={spare:2,planned:1,considering:0,wishlist:0,printing_uncertain:false,
            reason:'4 owned, 1 in built decks or intact products, 1 wanted by building or idea decks: 2 spare'};
          const spareData=extra=>answer([record('Alpha',{spares:spareFacts})],{total:2,pages:2,
            spares:{ready:true,message:null,note:'Spare copies protect saved plans.',copy:{text:copyText,printing_uncertain:false}},...extra});
          const showSpares=extra=>{const data=spareData(extra);return {data,cv:drawFind(data,'availability=spare')};};
        ''' + scenario)

    def test_reason_and_copy_use_all_server_matching_lines_without_prices_or_writes(self):
        self.run_js(r'''
          const {data,cv}=showSpares(),copied=[];navigator.clipboard={writeText:async text=>copied.push(text)};
          apiWrite=async()=>{throw Error('Copy must not write inventory');};
          assert(main.textContent.includes(spareFacts.reason));assert(main.textContent.includes('2 spare'));
          const copyButton=main.querySelector('.col-spare-copy');assert(copyButton);assert.equal(copyButton.textContent,'Copy list');
          await colCopySpares(cv,data,copyButton);same(copied,[copyText]);
          assert(copied[0].includes('Another card'));for(const words of ['$','AUD','Total'])assert(!copied[0].includes(words));
        ''')

    def test_uncertain_printing_fallback_is_shown_verbatim_when_clipboard_is_unavailable(self):
        self.run_js(r'''
          const text='# Printing allocation is unconfirmed for untagged lines. Check the physical cards before trading.\n2 Alpha\n';
          const {data,cv}=showSpares({spares:{ready:true,message:null,note:'Check physical printings.',copy:{text,printing_uncertain:true}}});
          navigator.clipboard={writeText:async()=>{throw Error('Unavailable');}};
          await colCopySpares(cv,data,main.querySelector('.col-spare-copy'));
          const sheet=[...colSheets].at(-1),area=sheet.body.querySelector('.col-spare-copy-text');assert(area);
          assert.equal(area.value,text);assert(sheet.body.textContent.includes('price-free list'));
        ''')

    def test_unavailable_is_never_presented_as_a_confirmed_empty_spare_list(self):
        self.run_js(r'''
          showSpares({cards:[],total:0,spares:{ready:false,message:'Spare copies depend on private plans.',copy:null}});
          assert.equal(main.querySelector('.col-spare-copy'),null);assert(main.textContent.includes('Spare copies unavailable'));
          assert(main.textContent.includes('depend on private plans'));assert(!main.textContent.includes('0 card names match'));
          assert(!main.textContent.includes('No cards match these filters'));
        ''')

    def test_late_clipboard_failure_cannot_show_private_copy_in_a_new_profile_route_or_query(self):
        self.run_js(r'''
          for(const change of ['profile','route','query','removed','text']){
            colCloseSheets();const {data,cv}=showSpares();let fail;
            navigator.clipboard={writeText:()=>new Promise((resolve,reject)=>fail=reject)};
            const button=main.querySelector('.col-spare-copy'),pending=colCopySpares(cv,data,button);
            if(change==='profile')state.profile=PROFILES[1];if(change==='route')routeToken++;
            if(change==='query')cv.findSeq++;if(change==='removed')cv.root.remove();if(change==='text')data.spares.copy.text='Changed';
            fail(Error('Unavailable'));await pending;assert.equal(colSheets.size,0,change);
          }
        ''')

    def test_copy_requires_the_owned_spare_view_and_current_connected_controls(self):
        self.run_js(r'''
          for(const change of ['busy','loading','filter','detached','private']){
            colCloseSheets();const {data,cv}=showSpares();let copies=0;navigator.clipboard={writeText:async()=>copies++};
            const button=main.querySelector('.col-spare-copy');
            if(change==='busy')cv.busy=true;if(change==='loading')cv.results.setAttribute('aria-busy','true');
            if(change==='filter')cv.query.set('availability','all');if(change==='detached')button.remove();
            if(change==='private')state.may={...state.may,see_inventory:[]};
            await colCopySpares(cv,data,button);assert.equal(copies,0,change);assert.equal(colSheets.size,0,change);
          }
        ''')
