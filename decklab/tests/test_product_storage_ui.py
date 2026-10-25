"""Product storage review through real UI scripts, without live data or network."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  clear(main);
  state.profile={id:'matt',name:'Matt',role:'admin',space:'home',plays_as:'user'};
  state.profiles=[state.profile];
  state.may={admin:true,products:true,accessories:true,see_accessories:true,see_inventory:['home']};
  const info=()=>({stem:'starter',name:'Starter',status:'owned',intact:'yes',has_decks:true,
    fingerprint:'first',can_change:true,why_not:null,kit:{sleeves:'PRIVATE UNUSED VALUE',deck_box:null}});
  const tables=()=>({written:[{id:'casual/a',title:'Elves'}],skipped:[],error:null});
  const preview=(extra={})=>({ready:true,preview:'opaque-review',stem:'starter',name:'Starter',
    before:{intact:'yes'},after:{intact:'no'},kit_cleared:true,changes:[],tables:tables(),warnings:[],...extra});
  const page=()=>{const data=makePage();Object.assign(data.summary,{id:'product/starter/green',
    title:'Green deck',read_only:true});return data;};
  const settle=async()=>{for(let i=0;i<32;i++)await null;};
  const button=(root,text)=>root.querySelectorAll('button').find(node=>node.textContent===text);
  const sheet=()=>[...productStorageSheets][0];
  const action=text=>button(sheet().foot,text);
  let routed=0; route=()=>{routed++;routeToken++;clear(main);};
  api=async path=>{assert.equal(path,'/api/product?stem=starter');return info();};
  const mount=async()=>{const part=productStorageSection(page());main.append(part);await settle();return part;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ProductStorageUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_breakup_previews_then_cancel_writes_nothing_and_hides_kit_ids(self):
        self.run_js("""
          const posts=[];apiWrite=async(path,body)=>{posts.push([path,body]);return preview();};
          const part=await mount();assert(part.textContent.includes('Kept intact'));
          assert(!part.textContent.includes('PRIVATE'));
          button(part,'Break up into storage').click();await settle();
          same(posts,[['/api/product/intact/preview',{stem:'starter',intact:'no',fingerprint:'first'}]]);
          assert(sheet().body.textContent.includes('sleeves and deck box records will be cleared'));
          assert(sheet().body.textContent.includes('Elves'));assert(!sheet().body.textContent.includes('PRIVATE'));
          action('Cancel').click();await settle();assert.equal(posts.length,1);
          assert.equal(productStorageSheets.size,0);assert(!button(part,'Break up into storage').disabled);
        """)

    def test_apply_is_explicit_single_flight_and_done_refreshes_the_deck(self):
        self.run_js("""
          const posts=[];let save;
          apiWrite=async(path,body)=>{posts.push([path,body]);return path.endsWith('preview')?preview():
            new Promise(resolve=>{save=resolve;});};
          const part=await mount();button(part,'Break up into storage').click();
          button(part,'Break up into storage').click();await settle();assert.equal(posts.length,1);
          const apply=action('Break up');apply.click();apply.click();await settle();assert.equal(posts.length,2);
          same(posts[1],['/api/product/intact/apply',{preview:'opaque-review'}]);
          state.library={private:'cached'};
          save({saved:true,name:'Starter',intact:'no',tables:tables(),warnings:[]});await settle();
          assert(sheet().body.textContent.includes('Starter is now broken up into storage'));
          assert.equal(state.library,null);assert.equal(routed,0);
          apply.click();await settle();assert.equal(posts.length,2,'old buttons cannot repeat a completed save');
          action('Done').click();flushTimers();await settle();assert.equal(routed,1);
        """)

    def test_keep_intact_and_table_failure_notes_survive_until_done(self):
        self.run_js("""
          api=async()=>({...info(),intact:'no'});const posts=[];
          apiWrite=async(path,body)=>{posts.push([path,body]);return path.endsWith('preview')?
            preview({kit_cleared:false}):{saved:true,name:'Starter',intact:'yes',warnings:['Check token cards'],
              tables:{written:[],skipped:[{id:'casual/b',title:'Burn',why:'No saved table'}],error:'Card data unavailable'}};};
          const part=await mount();assert(part.textContent.includes('Broken up'));
          button(part,'Keep intact').click();await settle();assert.equal(posts[0][1].intact,'yes');
          assert(!sheet().body.textContent.includes('records will be cleared'));
          action('Keep intact').click();await settle();
          assert(sheet().body.textContent.includes('now kept intact'));
          assert(sheet().body.textContent.includes('Check token cards'));
          assert(sheet().body.textContent.includes('Burn: No saved table'));
          assert.equal(sheet().body.querySelector('a').getAttribute('href'),TABLES_HREF);
          action('Done').click();flushTimers();await settle();assert.equal(routed,1);
        """)

    def test_unknown_storage_needs_an_explicit_choice(self):
        self.run_js("""
          api=async()=>({...info(),intact:null});const part=await mount();
          assert(part.textContent.includes('has not been recorded'));
          assert(!part.textContent.includes('Broken up:'));
          assert(button(part,'Keep intact'));assert(button(part,'Break up into storage'));
        """)

    def test_inventory_permissions_non_owned_products_and_missing_lists(self):
        self.run_js("""
          state.may.see_inventory=[];let reads=0;api=async()=>{reads++;return info();};
          assert.equal(productStorageSection(page()),null);assert.equal(reads,0);
          state.may.see_inventory=['home'];state.may.products=false;
          api=async()=>({...info(),can_change:false,why_not:'Only an admin can change products.'});
          let part=await mount();assert.equal(part.querySelectorAll('button').length,0);
          assert(part.textContent.includes('Only an admin'));clear(main);
          state.may.products=true;api=async()=>({...info(),status:'ordered',intact:null,can_change:false,why_not:'Receive it first.'});
          part=await mount();assert(part.textContent.includes('not been recorded as received'));
          assert.equal(part.querySelectorAll('button').length,0);clear(main);
          api=async()=>({...info(),intact:'no',has_decks:false});part=await mount();
          assert(button(part,'Keep intact').disabled);assert(part.textContent.includes('saved deck lists'));
          assert.equal(productStorageSection(makePage()),null);
        """)

    def test_stale_preview_refreshes_state_instead_of_applying_it(self):
        self.run_js("""
          const posts=[];let reads=0;
          api=async()=>({...info(),fingerprint:++reads===1?'first':'latest',intact:reads===1?'yes':'no'});
          apiWrite=async(path,body)=>{posts.push([path,body]);throw Object.assign(new Error('Product changed'),{status:409});};
          const part=await mount();button(part,'Break up into storage').click();await settle();
          assert(!action('Break up'));assert(sheet().body.textContent.includes('Product changed'));
          action('Refresh product').click();await settle();assert.equal(posts.length,1);
          assert(part.textContent.includes('Broken up'));assert(button(part,'Keep intact'));
        """)

    def test_stale_apply_keeps_the_review_and_requires_a_new_preview(self):
        self.run_js("""
          const posts=[];apiWrite=async(path,body)=>{posts.push([path,body]);if(path.endsWith('preview'))return preview();
            throw Object.assign(new Error('Collection changed'),{status:409});};
          const part=await mount();button(part,'Break up into storage').click();await settle();
          action('Break up').click();await settle();assert(sheet().body.textContent.includes('Collection changed'));
          assert(!action('Break up'));assert(action('Refresh product'));
          action('Refresh product').click();await settle();assert.equal(posts.length,2);assert.equal(routed,0);
        """)

    def test_noop_or_blocked_preview_never_offers_an_apply_action(self):
        self.run_js("""
          const posts=[];apiWrite=async(path,body)=>{posts.push([path,body]);return preview({ready:false,
            reason:'Already broken up.',preview:null,unchanged:true,tables:tables()});};
          const part=await mount();button(part,'Break up into storage').click();await settle();
          assert(sheet().body.textContent.includes('Already broken up.'));
          assert(!action('Break up'));assert(action('Close'));action('Close').click();await settle();
          assert.equal(posts.length,1);
        """)

    def test_read_errors_retry_and_unavailable_products_are_hidden(self):
        self.run_js("""
          let reads=0;api=async()=>{if(++reads===1)throw new Error('Connection lost');return info();};
          const part=await mount();assert(part.textContent.includes('Connection lost'));
          button(part,'Try again').click();await settle();assert(button(part,'Break up into storage'));
          clear(main);api=async()=>{throw Object.assign(new Error('No product'),{status:404});};
          const absent=await mount();assert(absent.hidden);
        """)

    def test_late_reads_previews_and_saves_never_update_another_viewer(self):
        self.run_js("""
          let receive;api=()=>new Promise(resolve=>{receive=resolve;});
          const part=productStorageSection(page());main.append(part);
          state.profile={id:'user1',space:'home'};receive({...info(),name:'PRIVATE LATE'});await settle();
          assert(!part.textContent.includes('PRIVATE LATE'));clear(main);
          state.profile={id:'matt',space:'home'};api=async()=>info();
          let respond;apiWrite=()=>new Promise(resolve=>{respond=resolve;});
          const next=await mount();button(next,'Break up into storage').click();await settle();
          const old=sheet();closeProductStorageSheets();respond(preview());await settle();
          assert(old.closed);assert.equal(productStorageSheets.size,0);
          apiWrite=async path=>path.endsWith('preview')?preview():new Promise(resolve=>{respond=resolve;});
          button(next,'Break up into storage').click();await settle();action('Break up').click();await settle();
          state.profile={id:'user1',space:'home'};closeProductStorageSheets();
          respond({saved:true,name:'PRIVATE SAVED',intact:'no',tables:tables(),warnings:[]});await settle();flushTimers();
          assert(!document.body.textContent.includes('PRIVATE SAVED'));assert.equal(routed,0);
        """)

    def test_product_overview_contains_the_storage_panel(self):
        self.run_js("""
          api=async path=>path.startsWith('/api/product?')?info():{lists:[],sideboards:[],games:[],warnings:[],decks:{}};
          drawDeck(page());await settle();assert(panel('overview').querySelector('.product-storage'));
          assert(panel('overview').textContent.includes('Kept intact'));
        """)


if __name__ == "__main__":
    unittest.main()
