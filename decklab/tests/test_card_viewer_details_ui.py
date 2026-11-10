"""Read-only reference links, lazy own copies and card-address ownership."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r'''
  state.profile={id:'matt',space:'home'};state.may={see_inventory:['home']};
  location.hash='#/deck?id=commander/test';
  const card={name:'Llanowar Elves',type_line:'Creature',img:'/img/fdn/227/normal',
    scryfall_url:'https://scryfall.com/card/fdn/227',edhrec_url:'https://edhrec.com/cards/llanowar-elves'};
  const flush=async()=>{for(let i=0;i<20;i++)await null;};
  const reads=[];let copies={printings:[{set:'fdn',number:'227',finish:'foil',quantity:2,location:'Top shelf'}],note:'Storage location only.'};
  api=async path=>{reads.push(path);if(path.startsWith('/api/cards/copies'))return copies;
    if(path.startsWith('/api/cards/lookup'))return {card};
    if(path.startsWith('/api/cards/decks'))return {basic:true};return {available:true,rulings:[]};};
  const show=()=>{openCardViewer([card]);viewerDom.dialog.open=true;};
  const unfold=async()=>{const fold=viewerDom.text.querySelector('.viewer-copies');fold.open=true;fold.fire('toggle');await flush();return fold;};
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CardViewerDetailsUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_references_are_native_outbound_links_and_commander_only_edhrec(self):
        self.run_js(r'''
          show();await flush();let links=viewerDom.text.querySelector('.viewer-reference').querySelectorAll('a');
          assert.equal(links[0].getAttribute('href'),card.scryfall_url);
          for(const link of links.slice(0,2)){assert.equal(link.getAttribute('target'),'_blank');assert.equal(link.getAttribute('rel'),'noopener noreferrer');}
          assert.equal(links[1].textContent,'Open on EDHREC');assert(links[2].getAttribute('href').includes('set=fdn'));
          assert(!reads.some(path=>path.includes('scryfall')||path.includes('edhrec')));
          location.hash='#/collection';show();assert(!viewerDom.text.textContent.includes('Open on EDHREC'));
        ''')

    def test_copies_are_lazy_show_recorded_printing_and_location_and_hide_for_a_private_other_space(self):
        self.run_js(r'''
          show();await flush();assert(!reads.some(path=>path.startsWith('/api/cards/copies')));
          const fold=await unfold();assert(fold.textContent.includes('FDN 227 · foil · 2 copies'));assert(fold.textContent.includes('Top shelf'));
          fold.fire('toggle');await flush();assert.equal(reads.filter(path=>path.startsWith('/api/cards/copies')).length,1);
          location.hash='#/deck?id=user2/commander/test';show();assert.equal(viewerDom.text.querySelector('.viewer-copies'),null);
        ''')

    def test_late_private_copy_responses_cannot_fill_after_profile_or_card_changes(self):
        self.run_js(r'''
          show();let done;api=()=>new Promise(resolve=>done=resolve);const fold=viewerDom.text.querySelector('.viewer-copies');
          fold.open=true;fold.fire('toggle');state.profile={...state.profile};done(copies);await flush();assert(!fold.textContent.includes('Top shelf'));
        ''')

    def test_copy_failure_is_retryable_and_never_claims_the_collection_is_empty(self):
        self.run_js(r'''
          show();const normal=api;api=async path=>{if(path.startsWith('/api/cards/copies'))throw Error('private server detail');return normal(path);};
          const fold=await unfold();assert(fold.textContent.includes("Your copies couldn't load"));assert(!fold.textContent.includes('No copies'));
          assert(!fold.textContent.includes('private server detail'));api=normal;fold.querySelector('button').click();await flush();assert(fold.textContent.includes('Top shelf'));
        ''')

    def test_card_address_keeps_the_current_page_and_does_nothing_before_a_profile_pick(self):
        self.run_js(r'''
          main.append(el('h1',{text:'Current page'}));rememberCardUnderlay();
          location.hash='#/card?name=Llanowar+Elves';const token=++routeToken;
          await showCardAddress(new URLSearchParams({name:'Llanowar Elves'}),token);
          assert.equal(main.querySelector('h1').textContent,'Current page');assert.equal(viewerState.address.base,'#/deck?id=commander/test');
          assert.equal(viewerState.history,false);assert(reads.some(path=>path==='/api/cards/lookup?name=Llanowar+Elves'));
          const before=reads.length;state.profile=null;await showCardAddress(new URLSearchParams({name:'Black Lotus'}),++routeToken);assert.equal(reads.length,before);
        ''')

    def test_card_address_reply_is_ignored_after_navigation_and_public_lookup_never_calls_collection_autocomplete(self):
        self.run_js(r'''
          rememberCardUnderlay();location.hash='#/card?name=Llanowar+Elves';let done;api=()=>new Promise(resolve=>done=resolve);
          const token=++routeToken;const pending=showCardAddress(new URLSearchParams({name:'Llanowar Elves'}),token);
          location.hash='#/collection';++routeToken;done({card});await pending;assert.equal(viewerState,null);
        ''')

    def test_address_router_waits_for_a_profile_and_close_returns_to_its_underlay(self):
        self.run_js(r'''
          location.hash='#/card?name=Llanowar+Elves';state.profile=null;let picked=0,opened=0;
          drawWho=()=>picked++;const original=showCardAddress;showCardAddress=()=>opened++;route();assert.equal(picked,1);assert.equal(opened,0);
          showCardAddress=original;state.profile={id:'matt',space:'home'};location.hash='#/collection';rememberCardUnderlay();
          location.hash='#/card?name=Llanowar+Elves';await showCardAddress(new URLSearchParams({name:'Llanowar Elves'}),++routeToken);
          let replaced=null;location.replace=href=>replaced=href;viewerDom.dialog.open=false;viewerClosed();assert.equal(replaced,'#/collection');
        ''')

    def test_profile_departure_closes_a_viewer_containing_private_copy_facts(self):
        self.run_js(r'''
          show();await unfold();assert(viewerDom.text.textContent.includes('Top shelf'));
          viewerDom.dialog.close=()=>{viewerDom.dialog.open=false;viewerClosed();};
          state.profile=null;closeCardAddress();assert.equal(viewerState,null);assert.equal(viewerDom.dialog.open,false);
        ''')
