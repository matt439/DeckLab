"""Matchups' "Show matchups for" deck picker (E3-S27): pictures and pips, keyboard, choosing and hidden decks."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = r"""
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};
  const stored=new Map();local.get=key=>stored.get(key)||null;local.set=(key,value)=>{stored.set(key,value);return true;};
  let writes=0;
  const deck=(id,title,extra={})=>({id,title,kind:'casual',space:'home',versions:['target'],card_count:60,...extra});
  const library=()=>({decks_revision:'r1',halves:[],decks:[
    deck('casual/alpha','Alpha Elves',{colors:['G'],cover:{art:'https://img.example/alpha.jpg'}}),
    deck('casual/beta','Beta Burn',{colors:['R']}),
    deck('casual/bogles','Bogles of the Long Swamp',{colors:['G','W'],cover:{art:'https://img.example/bogles.jpg'}}),
    deck('casual/delta','Delta Control',{colors:['U','B'],cover:{art:'https://img.example/delta.jpg'}})]});
  const side=(id,title)=>({id,title,version:'target',kind:'casual',current:true});
  const result=(a,b,n,value=.6)=>({key:String(n).repeat(64),format:'Constructed',updated:'2026-10-16T12:00:00',games:200,
    engine:{kind:'decklab',current:true},winrate:{value,low:value-.1,high:value+.1},sides:[side(...a),side(...b)]});
  // The last result names another space's deck the viewer may not see: it isn't in /api/decks, so not offered.
  const answer=()=>({decks_revision:'r1',running:[],forge:{ready:false,problem:'Fixture only'},results:[
    result(['casual/alpha','Alpha Elves'],['casual/beta','Beta Burn'],1),
    result(['casual/delta','Delta Control'],['casual/beta','Beta Burn'],2,.3),
    result(['casual/alpha','Alpha Elves'],['user2/casual/secret','Secret Deck'],3)]});
  api=async(url)=>{
    if(url.startsWith('/api/field?')){const p=new URL(url,'https://fixture.invalid').searchParams;
      return {deck:{id:p.get('id'),version:p.get('version')},format:'Constructed',opponents:[]};}
    if(url.startsWith('/api/variants?'))return {tests:[]};
    return url==='/api/decks'?library():answer();};
  apiWrite=async()=>{writes++;throw new Error('Read-only fixture');};
  runGate=()=>({may:false,why:'Fixture only'});runsAllowed=()=>false;noteRuns=()=>{};
  const open=()=>{location.hash='#/matchups';drawMatchups(library(),answer(),new URLSearchParams(),routeToken);};
  const button=()=>main.querySelector('#mu-deck-pick');
  const list=()=>main.querySelector('#mu-deck-pick-list');
  const options=()=>main.querySelectorAll('.deck-pick-option');
  const chosen=()=>options().find(o=>o.getAttribute('aria-selected')==='true')?.getAttribute('data-id');
  const active=()=>list().getAttribute('aria-activedescendant');
  const activeId=()=>options().find(o=>o.id===active())?.getAttribute('data-id');
  const key=(node,k,extra={})=>node.fire('keydown',{key:k,...extra});
  const pipsOf=node=>node.querySelector('.id-pips');
  const tinted=node=>(node.getAttribute('class')||'').split(' ').includes('deck-tint')||node.classList.contains('deck-tint');
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupDeckPickerUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_options_and_closed_control_show_pictures_pips_and_full_title_names(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/alpha');open();
          assert(!main.querySelector('select#mu-deck-pick'),'the native select is replaced');
          const label=main.querySelector('label');assert.equal(label.getAttribute('for'),'mu-deck-pick');
          assert.equal(label.textContent,'Show matchups for');
          const b=button();assert.equal(b.getAttribute('aria-haspopup'),'listbox');assert.equal(b.getAttribute('aria-expanded'),'false');
          assert.equal(b.getAttribute('aria-controls'),'mu-deck-pick-list');
          const [labelId,valueId]=b.getAttribute('aria-labelledby').split(' ');
          assert.equal(labelId,label.id);assert.equal(main.querySelector('#'+valueId).textContent,'Alpha Elves');
          assert.equal(b.querySelector('img').getAttribute('src'),'https://img.example/alpha.jpg');
          assert.equal(pipsOf(b).getAttribute('aria-label'),'Colours: green');
          assert.equal(list().getAttribute('role'),'listbox');assert(list().hidden);
          same(options().map(o=>o.getAttribute('data-id')),['casual/alpha','casual/beta','casual/bogles','casual/delta']);
          for(const o of options())assert.equal(o.getAttribute('role'),'option');
          same(options().map(o=>o.getAttribute('aria-label')),['Alpha Elves','Beta Burn','Bogles of the Long Swamp','Delta Control']);
          assert.equal(chosen(),'casual/alpha');
          const [alpha,beta,bogles,delta]=options();
          assert.equal(delta.querySelector('img').getAttribute('src'),'https://img.example/delta.jpg');
          same(pipsOf(delta).querySelectorAll('.id-pip').map(p=>p.textContent),['U','B']);
          assert.equal(pipsOf(bogles).getAttribute('aria-label'),'Colours: white, green');
          // No art: the deck's tint, with the pips beside its name.
          assert(!beta.querySelector('img'));assert(tinted(beta.querySelector('.deck-pick-art')));
          same(pipsOf(beta).querySelectorAll('.id-pip').map(p=>p.textContent),['R']);
          assert.equal(writes,0);
        """)

    def test_failed_picture_falls_back_to_the_tint_name_and_pips(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/delta');open();
          const delta=options().find(o=>o.getAttribute('data-id')==='casual/delta'),img=delta.querySelector('img');
          img.fire('error');
          assert(!delta.querySelector('img'));assert(tinted(delta.querySelector('.deck-pick-art')));
          assert.equal(delta.querySelector('.deck-pick-name').textContent,'Delta Control');assert(pipsOf(delta));
          const b=button(),own=b.querySelector('img');own.fire('error');
          assert(!b.querySelector('img'));assert.equal(b.querySelector('.deck-pick-name').textContent,'Delta Control');
          assert.equal(pipsOf(b).getAttribute('aria-label'),'Colours: blue, black');
        """)

    def test_keyboard_moves_types_ahead_chooses_and_stores(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/alpha');open();
          key(button(),'ArrowDown');assert(!list().hidden);assert.equal(button().getAttribute('aria-expanded'),'true');
          assert.equal(document.activeElement,list());assert.equal(activeId(),'casual/alpha');
          key(list(),'ArrowDown');assert.equal(activeId(),'casual/beta');
          key(list(),'End');assert.equal(activeId(),'casual/delta');key(list(),'ArrowDown');assert.equal(activeId(),'casual/delta');
          key(list(),'Home');assert.equal(activeId(),'casual/alpha');key(list(),'ArrowUp');assert.equal(activeId(),'casual/alpha');
          // Type-ahead: "b" goes to Beta, "b" again round to Bogles; "de" to Delta.
          key(list(),'b');assert.equal(activeId(),'casual/beta');key(list(),'b');assert.equal(activeId(),'casual/bogles');
          flushTimers();key(list(),'d');key(list(),'e');assert.equal(activeId(),'casual/delta');
          const typed=key(list(),'x');assert(typed.defaultPrevented,'letters are the picker\'s, not page shortcuts');
          assert.equal(activeId(),'casual/delta');
          const before=main.querySelectorAll('.mu-opponent-row').map(r=>r.textContent).join('|');
          key(list(),'Enter');
          assert.equal(stored.get(HOME_DECK_KEY),'casual/delta');assert.equal(chosen(),'casual/delta');
          assert(list().hidden);assert.equal(document.activeElement,button(),'focus returns to the new picker');
          assert.notEqual(main.querySelectorAll('.mu-opponent-row').map(r=>r.textContent).join('|'),before);
          assert.equal(main.querySelector('#mu-deck-pick-value').textContent,'Delta Control');
          // Escape closes without choosing.
          button().click();assert(!list().hidden);key(list(),'Home');key(list(),'Escape');
          assert(list().hidden);assert.equal(document.activeElement,button());assert.equal(stored.get(HOME_DECK_KEY),'casual/delta');
          // A letter on the closed button opens it at the match; Space chooses.
          key(button(),'b');assert(!list().hidden);assert.equal(activeId(),'casual/beta');key(list(),' ');
          assert.equal(stored.get(HOME_DECK_KEY),'casual/beta');assert.equal(chosen(),'casual/beta');assert.equal(writes,0);
        """)

    def test_click_chooses_through_choose_and_outside_click_closes(self):
        self.run_js(r"""
          stored.set(HOME_DECK_KEY,'casual/alpha');open();
          button().click();assert(!list().hidden);
          document.fire('click',{target:document.body});assert(list().hidden);
          assert.equal(button().getAttribute('aria-expanded'),'false');
          button().click();options().find(o=>o.getAttribute('data-id')==='casual/alpha').click();
          assert(list().hidden);assert.equal(stored.get(HOME_DECK_KEY),'casual/alpha');
          button().click();options().find(o=>o.getAttribute('data-id')==='casual/bogles').click();
          assert.equal(stored.get(HOME_DECK_KEY),'casual/bogles');assert.equal(chosen(),'casual/bogles');
          // Redrawn from the stored choice.
          clear(main);open();assert.equal(chosen(),'casual/bogles');
        """)

    def test_decks_the_viewer_may_not_see_are_not_offered(self):
        self.run_js(r"""
          open();
          assert(!options().some(o=>o.getAttribute('data-id').startsWith('user2/')));
          assert(!list().textContent.includes('Secret'));assert.equal(options().length,4);
        """)


if __name__ == "__main__":
    unittest.main()
