"""Opening-hand state transitions and real-game form interactions in Node."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
RUNNER = Path(__file__).resolve().parent / "fixtures/workspace_ui_runner.js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class PlayUiTests(unittest.TestCase):
    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("hands.js", "play.js"))
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), sources + "\n" + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_london_mulligan_draws_seven_and_bottoms_exactly_once(self):
        self.run_js("""
          const model = new OpeningHand([{name:'Forest',qty:20}], {random:()=>0.99});
          assert.equal(model.draw(), null);
          model.deal(); assert.equal(model.hand.length, 7); assert.equal(model.library.length, 13);
          assert.equal(model.keep([0]), false);
          model.mulligan(); model.mulligan();
          assert.equal(model.hand.length, 7); assert.equal(model.bottomCount, 2);
          assert.equal(model.keep([0,0]), false);
          assert.equal(model.keep([0,7]), false);
          assert.equal(model.keep([1]), false);
          const bottom = [model.hand[3].copy, model.hand[1].copy];
          assert.equal(model.keep([3,1]), true);
          assert.equal(model.hand.length, 5); assert.equal(model.library.length, 15);
          same(model.library.slice(-2).map(c=>c.copy), bottom);
          assert.equal(model.keep([3,1]), false); assert.equal(model.mulligan(), false);
          const next=model.library[0]; assert.equal(model.draw(),next); assert.equal(model.hand.length,6);
          assert.equal(new Set([...model.hand,...model.library].map(c=>c.copy)).size,20);
        """)

    def test_free_multiplayer_mulligan_reset_and_empty_library(self):
        self.run_js("""
          let randomCalls=0;
          const model = new OpeningHand([{name:'Forest',qty:7}], {freeFirst:true,random:()=>{randomCalls++;return .2;}});
          model.deal(); model.mulligan(); assert.equal(model.bottomCount,0);
          model.mulligan(); assert.equal(model.bottomCount,1);
          assert.equal(model.keep([0]),true); assert.equal(model.draw().name,'Forest');
          assert.equal(model.draw(),null); assert.equal(model.draws,1);
          model.deal(); assert.equal(model.mulligans,0); assert.equal(model.phase,'opening');
          assert.equal(model.draws,0); assert.equal(model.hand.length,7); assert.ok(randomCalls>=24);
          for(let i=0;i<8;i++) assert.equal(model.mulligan(),true);
          assert.equal(model.bottomCount,7); assert.equal(model.mulligan(),false);
          assert.equal(model.keep([0,1,2,3,4,5,6]),true); assert.equal(model.hand.length,0);
        """)

    def test_small_decks_and_invalid_quantities_are_clear_errors(self):
        self.run_js("""
          assert.throws(()=>new OpeningHand([]),/At least seven/);
          assert.throws(()=>new OpeningHand([{name:'Forest',qty:6}]),/At least seven/);
          assert.throws(()=>new OpeningHand([{name:'Forest',qty:-1}]),/Invalid/);
          assert.throws(()=>new OpeningHand([{name:'Forest',qty:1.5}]),/Invalid/);
        """)

    def test_hand_ui_uses_main_deck_only_and_requires_bottom_selection(self):
        self.run_js("""
          const data={summary:{id:'commander/test'},versions:['target'],version:'target',sections:{
            Commander:[{name:'Commander',qty:1}],Deck:[{name:'Forest',qty:10}],Sideboard:[{name:'Outside',qty:1}]}};
          const section=manualHandsSection(data); main.append(section);
          const button = text=>section.querySelectorAll('button').find(b=>b.textContent===text);
          button('Deal seven').click();
          assert.equal(section.querySelector('.hands-cards').children.length,7);
          assert.ok(!section.querySelector('.hands-cards').textContent.includes('Commander'));
          assert.match(section.textContent,/Opening seven[.] Keep or mulligan[?]/);
          assert.match(section.querySelector('.hands-counts').textContent,/0 lands · 7 spells/);
          button('Mulligan').click();
          assert.match(section.textContent,/Mulligan 1: choose 1 card to put on the bottom/);
          assert.ok(!section.textContent.includes('0 mulligans'));
          assert.equal(button('Keep hand').disabled,true);
          button('To bottom').click(); assert.equal(button('Keep hand').disabled,false);
          button('Keep hand').click(); assert.equal(section.querySelector('.hands-cards').children.length,6);
          assert.equal(button('Keep hand'),undefined);
          button('Draw next card').click(); assert.equal(section.querySelector('.hands-cards').children.length,7);
          assert.equal(data.sections.Deck[0].qty,10);
        """)

    def test_play_page_empty_state_has_no_fake_games_or_null_text(self):
        self.run_js("""
          clear(main); state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile];
          drawPlay({lists:[],games:[],sideboards:[],warnings:[],today:'2026-10-08'},'');
          assert.match(main.textContent,/No games have been recorded/);
          assert.match(main.textContent,/no decks to record a game with/);
          assert.equal(main.querySelector('.play-quick'),null);
          assert.ok(!main.textContent.includes('null')); assert.ok(!main.textContent.includes('[object Object]'));
          assert.equal(main.querySelectorAll('button').filter(b=>b.disabled).length,1);
          // A member is sent only the games with their own decks, and the words say so.
          clear(main); state.profile={id:'user2',name:'User2',space:'user2'}; state.profiles=[state.profile];
          drawPlay({lists:[],games:[],sideboards:[],warnings:[],today:'2026-10-08'},'');
          assert.match(main.textContent,/No games with your decks have been recorded yet[.]/);
          assert.ok(!main.textContent.includes('No games have been recorded'));
        """)

    def test_quick_record_defaults_to_each_players_last_deck_and_saves_after_its_undo_time(self):
        self.run_js("""
          state.profile={id:'user1',name:'User1',space:'home'};
          state.profiles=[{id:'matt',name:'Matt',space:'home'},state.profile,{id:'user2',name:'User2',space:'user2'}];
          const list=(id,title,version='target')=>({id,version,sha256:id+version,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const lists=[list('casual/a','Alpha'),list('casual/b','Beta'),list('casual/c','Gamma'),list('casual/c','Gamma','owned')];
          const game={record:{date:'2026-10-07',result:'a',sides:[{...list('casual/c','Gamma','owned'),sha256:'old',player:'Matt',mulligans:0},
            {...list('casual/b','Beta'),player:'User1',mulligans:0}]},sha256:'s'};
          const data={lists,games:[game],sideboards:[],warnings:[],today:'2026-10-08'};
          const requests=[], toasts=[], said=[]; let routes=0; route=()=>{routes++;}; location.hash='#/play';
          showToast=(text,opts)=>{toasts.push([text,opts]); return {close(){}};};
          toast=(text)=>{said.push(text);};
          apiWrite=async(endpoint,payload)=>{
            requests.push({endpoint,payload});
            return payload.preview ? {id:'new-record',record:{...payload,sides:payload.sides.map(s=>({...s,title:lists.find(l=>l.id===s.id).title}))},review_sha256:'review-token'}
              : {saved:true,record:{id:'new-record',revision:1,...payload},sha256:'f'.repeat(64)};
          };
          clear(main); drawPlay(data,'');
          // User1 first (the visitor), then Matt: each on the deck they last played, its current list.
          const decks=main.querySelectorAll('select').filter(s=>/^play-quick-deck/.test(s.id||''));
          same(decks.map(s=>lists[Number(s.value)].title+' '+lists[Number(s.value)].version),['Beta target','Gamma owned']);
          // The result buttons name the players; nothing like "Player 1 won", and More details' headings are the names.
          const outcomes=main.querySelectorAll('.play-outcome');
          same(outcomes.map(b=>b.textContent),['User1 won','Matt won','Draw']);
          assert.ok(!main.querySelector('.play-quick').textContent.includes('Player 1'));
          same(main.querySelector('.play-quick').querySelectorAll('legend').map(l=>l.textContent),['User1','Matt']);
          // One tap: the review at once, shown in a toast with Undo; nothing saved yet, and no second game meanwhile.
          outcomes[0].click(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,1); assert.equal(requests[0].payload.preview,true);
          assert.equal(requests[0].payload.result,'a'); assert.equal(requests[0].payload.date,'2026-10-08');
          same(requests[0].payload.sides.map(s=>[s.id,s.version,s.player,s.mulligans]),
            [['casual/b','target','User1',0],['casual/c','owned','Matt',0]]);
          assert.equal(toasts[0][0],'Saving the game: User1 won: Beta vs Gamma.');
          assert.equal(typeof toasts[0][1].undo,'function'); assert.equal(toasts[0][1].undoText,undefined);
          assert.ok(outcomes.every(b=>b.disabled));
          // The toast's time up: the save with the review's token; no review sheet.
          flushTimers(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,2);
          assert.equal(requests[1].payload.preview,false);
          assert.equal(requests[1].payload.id,'new-record'); assert.equal(requests[1].payload.review_sha256,'review-token');
          assert.equal(routes,1); same(said,['Game saved.']);
          assert.equal(document.body.querySelectorAll('button').filter(b=>b.textContent==='Save this record').length,0);
        """)

    def test_quick_record_undo_saves_nothing_and_hiding_the_page_saves_at_once(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile];
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const data={lists:[list('casual/a','Alpha'),list('casual/b','Beta')],games:[],sideboards:[],warnings:[],today:'2026-10-08'};
          const requests=[]; let undo=null; location.hash='#/play'; route=()=>{}; toast=()=>{};
          showToast=(text,opts)=>{undo=opts.undo; return {close(){}};};
          apiWrite=async(endpoint,payload)=>{requests.push(payload); return {id:'r',record:{...payload},review_sha256:'t'};};
          clear(main); drawPlay(data,'');
          const outcomes=main.querySelectorAll('.play-outcome');
          outcomes[1].click(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,1);
          undo(); flushTimers(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,1);
          assert.ok(outcomes.every(b=>!b.disabled));
          same(outcomes.map(b=>b.textContent),['Matt won','Opponent won','Draw']);
          assert.equal(document.activeElement,outcomes[1]);
          // Hiding the page saves a waiting game at once, and only once.
          outcomes[2].click(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,2);
          saveDraft=()=>{};   // editor.js's own visibilitychange listener is not this test's
          document.visibilityState='hidden'; document.fire('visibilitychange'); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,3); assert.equal(requests[2].preview,false);
          flushTimers(); document.fire('visibilitychange'); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,3);
          delete document.visibilityState;
        """)

    def test_quick_record_details_and_a_refusal(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile];
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const data={lists:[list('casual/a','Alpha'),list('casual/b','Beta')],games:[],sideboards:[],warnings:[],today:'2026-10-08'};
          const requests=[]; apiWrite=async(endpoint,payload)=>{requests.push(payload); throw new ApiError(403,'Not your deck.');};
          clear(main); drawPlay(data,'casual/b');
          // From a deck's page, the visitor's deck is that one; with no one else at home, the other is "Opponent".
          const decks=main.querySelectorAll('select').filter(s=>/^play-quick-deck/.test(s.id||''));
          same(decks.map(s=>s.value),['1','0']);
          const outcomes=main.querySelectorAll('.play-outcome');
          same(outcomes.map(b=>b.textContent),['Matt won','Opponent won','Draw']);
          // More details: a name typed renames its button; the date and mulligans go with the record.
          const name=main.querySelector('#play-quick-name-1'); name.value='Sam'; name.fire('input');
          assert.equal(outcomes[1].textContent,'Sam won');
          same(main.querySelector('.play-quick').querySelectorAll('legend').map(l=>l.textContent),['Matt','Sam']);
          main.querySelector('#play-quick-date').value='2026-10-01';
          main.querySelector('#play-quick-mull-0').value='2';
          outcomes[2].click(); for(let i=0;i<6;i++) await null;
          assert.equal(requests.length,1);
          assert.equal(requests[0].result,'draw'); assert.equal(requests[0].date,'2026-10-01');
          same(requests[0].sides.map(s=>[s.player,s.mulligans]),[['Matt',2],['Sam',0]]);
          assert.match(main.querySelector('.play-quick').textContent,/Not your deck./);
          assert.ok(outcomes.every(b=>!b.disabled));
        """)

    def test_game_cards_say_who_won_and_hide_zero_mulligans(self):
        self.run_js("""
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const record={id:'r',revision:2,updated_by:'Matt',date:'2026-10-08',result:'b',notes:'',
            sides:[{...list('casual/a','Alpha'),player:'Matt',mulligans:0},{...list('casual/b','Beta'),player:'User1',mulligans:1}]};
          const card=playGameCard({record,sha256:'s'},{lists:[],sideboards:[]});
          assert.equal(card.querySelector('h3').textContent,'User1 won');
          assert.ok(card.textContent.includes('Alpha (Matt) vs Beta (User1)'));
          assert.ok(card.textContent.includes('User1 took 1 mulligan'));
          assert.ok(!card.textContent.includes('Matt took'));
        """)

    def test_failed_hand_version_load_cannot_deal_old_list_under_new_label(self):
        self.run_js("""
          const data={summary:{id:'commander/test',kind:'commander'},versions:['target','owned'],version:'target',
            sections:{Deck:[{name:'Target card',qty:10}]}};
          const section=manualHandsSection(data); main.append(section);
          const version=section.querySelector('select'), free=section.querySelector('input');
          let reject, resolve; api=()=>new Promise((done,fail)=>{resolve=done;reject=fail;});
          version.value='owned'; version.fire('change');
          assert.equal(free.disabled,true); free.checked=true; free.fire('change');
          assert.match(section.querySelector('.hands-body').textContent,/Loading that list/);
          assert.equal(free.checked,false);
          reject(new Error('Connection failed')); await Promise.resolve(); await Promise.resolve();
          assert.equal(version.value,'target'); assert.equal(free.disabled,false);
          assert.match(section.textContent,/still the planned list/);
          free.checked=true; free.fire('change');
          section.querySelectorAll('button').find(b=>b.textContent==='Deal seven').click();
          assert.match(section.querySelector('.hands-cards').textContent,/Target card/);
          version.value='owned'; version.fire('change');
          resolve({...data,version:'owned',sections:{Deck:[{name:'Substitute card',qty:10}]}});
          await Promise.resolve(); await Promise.resolve();
          assert.equal(version.value,'owned'); assert.equal(free.disabled,false);
          section.querySelectorAll('button').find(b=>b.textContent==='Deal seven').click();
          assert.match(section.querySelector('.hands-cards').textContent,/Substitute card/);
        """)

    def test_game_form_reviews_before_save_and_uses_preview_record_id(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile,{id:'user1',name:'User1'}];
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const data={lists:[list('casual/a','Alpha'),list('casual/b','Beta')],sideboards:[],today:'2026-10-08'};
          const requests=[], toasts=[]; let routes=0; route=()=>{routes++;}; toast=text=>toasts.push(text); location.hash='#/play';
          apiWrite=async(endpoint,payload)=>{
            requests.push({endpoint,payload});
            return payload.preview ? {id:'new-record',record:{date:payload.date,result:payload.result,notes:payload.notes,
              sides:payload.sides.map((side,i)=>({...data.lists[i],...side}))},review_sha256:'review-token'}
              : {saved:true,record:{id:'new-record',revision:1},sha256:'f'.repeat(64)};
          };
          playGameForm(data,'');
          const form=document.body.querySelector('.play-form');
          const fields=form.querySelectorAll('select'); fields[0].value='0'; fields[2].value='1'; fields[4].value='a';
          form.querySelector('textarea').value='Real note';
          form.fire('submit'); await Promise.resolve(); await Promise.resolve();
          assert.equal(requests.length,1); assert.equal(requests[0].payload.preview,true);
          assert.equal(requests[0].payload.result,'a');
          assert.ok(!document.body.textContent.includes('[object Object]'));
          const save=document.body.querySelectorAll('button').find(b=>b.textContent==='Save this record');
          save.click(); await Promise.resolve(); await Promise.resolve();
          assert.equal(requests.length,2); assert.equal(requests[1].payload.preview,false);
          assert.equal(requests[1].payload.id,'new-record'); assert.equal(requests[1].payload.review_sha256,'review-token');
          assert.equal(routes,1); assert.deepEqual(toasts,['Record saved.']);
        """)

    def test_saved_records_offer_no_commit_retry(self):
        self.run_js("""
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const data={lists:[list('casual/a','Alpha'),list('casual/b','Beta')],sideboards:[],today:'2026-10-08'};
          const record={id:'r',revision:2,updated_by:'Matt',date:'2026-10-08',result:'a',notes:'',
            sides:[{...list('casual/a','Alpha'),player:'Matt',mulligans:0},{...list('casual/b','Beta'),player:'User1',mulligans:1}]};
          // An "uncommitted" flag from an older server is ignored: the database keeps every save.
          const card=playGameCard({record,sha256:'s',uncommitted:true},data);
          assert.ok(!card.textContent.includes('uncommitted'));
          assert.ok(!card.querySelectorAll('button').some(b=>/Commit/.test(b.textContent)));
          const plan={id:'p',revision:1,updated_by:'Matt',notes:'',deck:data.lists[0],opponent:data.lists[1],
            out:[{name:'Forest',qty:1}],in:[{name:'Forest',qty:1}],after:data.lists[0].sections};
          const planCard=playPlanCard({record:plan,sha256:'s',uncommitted:true},data);
          assert.ok(!planCard.querySelectorAll('button').some(b=>/Commit/.test(b.textContent)));
        """)

    def test_sideboard_form_uses_finite_source_quantities_and_reviews(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile];
          const own={id:'casual/a',version:'target',sha256:'a',title:'Alpha',sections:{
            Deck:[{name:'Forest',qty:56},{name:'Llanowar Elves',qty:4}],Sideboard:[{name:'Pick Your Poison',qty:2}]}};
          const other={...own,id:'casual/b',sha256:'b',title:'Beta'};
          const requests=[]; apiWrite=async(endpoint,payload)=>{requests.push({endpoint,payload});throw new Error('Preview stopped for test');};
          playPlanForm({lists:[own,other]},'casual/a');
          const form=document.body.querySelector('.play-form'); const selects=form.querySelectorAll('select');
          selects[0].value='0'; selects[1].value='1'; form.querySelector('textarea').value='Use after game one';
          const inputs=form.querySelectorAll('input');
          assert.equal(inputs[0].getAttribute('max'),'56'); assert.equal(inputs[2].getAttribute('max'),'2');
          inputs[1].value='2'; inputs[2].value='2'; form.fire('submit'); await Promise.resolve(); await Promise.resolve();
          assert.equal(requests.length,1); assert.equal(requests[0].payload.preview,true);
          same(requests[0].payload.out,[{name:'Llanowar Elves',qty:2}]);
          same(requests[0].payload.in,[{name:'Pick Your Poison',qty:2}]);
          assert.match(form.textContent,/Preview stopped for test/);
        """)

    def test_session_summary_balances_seats_and_keeps_list_revisions_separate(self):
        self.run_js("""
          const a={id:'casual/a',title:'A',sha256:'a'}, b={id:'casual/b',title:'B',sha256:'b'};
          const game=(sides,result,date='2026-10-08')=>({record:{sides,result,date}});
          const summaries=playMatchupSummaries([game([a,b],'a'),game([b,a],'b'),game([a,b],'draw'),
            game([{...a,sha256:'a-new'},b],'a'),game([a,a],'b')]);
          assert.equal(summaries.length,3);
          assert.equal(summaries[0].games,3); same(summaries[0].wins,[2,0]); assert.equal(summaries[0].draws,1);
          assert.equal(summaries[1].games,1); assert.equal(summaries[2].mirror,true);
        """)

    def test_preview_after_navigation_or_form_changes_cannot_open_save_sheet(self):
        self.run_js("""
          let resolve; apiWrite=()=>new Promise(done=>{resolve=done;});
          const parent=openSheet('Form');
          const pending=playReview('/api/play/game',{},parent);
          routeToken++;
          resolve({record:{},review_sha256:'old'}); await pending;
          assert.equal(parent.closed,true);
          assert.equal(document.body.querySelectorAll('button').filter(b=>b.textContent==='Save this record').length,0);
          const fresh=openSheet('Another form'); let current=true;
          const changed=playReview('/api/play/game',{},fresh,()=>current);
          current=false; resolve({record:{},review_sha256:'old'}); await changed;
          assert.equal(fresh.closed,false);
          assert.equal(document.body.querySelectorAll('button').filter(b=>b.textContent==='Save this record').length,0);
        """)

    def test_old_game_and_plan_forms_refuse_submit_after_navigation_or_profile_switch(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt'}; state.profiles=[state.profile,{id:'user1',name:'User1'}];
          const list={id:'casual/a',version:'target',sha256:'a',title:'Alpha',sections:{Deck:[{name:'Forest',qty:60}],Sideboard:[]}};
          const data={lists:[list],sideboards:[],today:'2026-10-08'};
          let requests=0; apiWrite=()=>{requests++;throw new Error('Stale form made a request');};
          playGameForm(data,'casual/a'); const game=document.body.querySelector('.play-form');
          routeToken++; game.fire('submit'); await Promise.resolve();
          assert.equal(game.isConnected,false); assert.equal(requests,0);
          playPlanForm(data,'casual/a'); const plan=document.body.querySelector('.play-form');
          state.profile={id:'user1',name:'User1'}; plan.fire('submit'); await Promise.resolve();
          assert.equal(plan.isConnected,false); assert.equal(requests,0);
        """)

    def test_quick_record_starts_each_player_on_a_deck_they_play(self):
        self.run_js("""
          state.profile={id:'user1',name:'User1',plays_as:'wife'};
          state.profiles=[{id:'matt',name:'Matt',plays_as:'user'},state.profile];
          const list=(id,title,version='target')=>({id,version,sha256:id+version,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const lists=[list('casual/gruul','Gruul'),list('casual/idea','Idea'),list('casual/tfp','TFP'),list('casual/otters','Otters'),
            list('casual/tfp','TFP','owned')];
          const decks={'casual/gruul':{player:'user',status:'idea'},'casual/idea':{player:'wife',status:'idea'},
            'casual/tfp':{player:'wife',status:'building'},'casual/otters':{player:'user',status:'building'}};
          clear(main); drawPlay({lists,games:[],sideboards:[],warnings:[],today:'2026-10-08',decks},'');
          const chosen=main.querySelectorAll('select').filter(s=>/^play-quick-deck/.test(s.id||'')).map(s=>lists[Number(s.value)].title);
          same(chosen,['TFP','Otters']);
        """)

    def test_quick_record_from_a_deck_page_puts_it_on_its_players_side(self):
        self.run_js("""
          state.profile={id:'matt',name:'Matt',plays_as:'user'};
          state.profiles=[state.profile,{id:'user1',name:'User1',plays_as:'wife'}];
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const lists=[list('casual/gruul','Gruul'),list('casual/tfp','TFP'),list('casual/stardew','Stardew')];
          const decks={'casual/gruul':{player:'user',status:'building'},'casual/tfp':{player:'wife',status:'building'},
            'casual/stardew':{player:'wife',status:'idea'}};
          const chosen=()=>main.querySelectorAll('select').filter(s=>/^play-quick-deck/.test(s.id||'')).map(s=>lists[Number(s.value)].title);
          // User1's deck, opened by Matt: it's User1's side, and Matt starts on his own.
          clear(main); drawPlay({lists,games:[],sideboards:[],warnings:[],today:'2026-10-08',decks},'casual/tfp');
          same(chosen(),['Gruul','TFP']);
          // Matt's deck, which both last played (a mirror): User1 moves to a deck of hers.
          const game={record:{date:'2026-10-07',result:'a',sides:[{...lists[0],player:'Matt',mulligans:0},{...lists[0],player:'User1',mulligans:0}]},sha256:'s'};
          clear(main); drawPlay({lists,games:[game],sideboards:[],warnings:[],today:'2026-10-08',decks},'casual/gruul');
          same(chosen(),['Gruul','TFP']);
        """)

    def test_a_person_starts_on_a_deck_of_their_own_space(self):
        self.run_js("""
          state.profile={id:'user2',name:'User2',space:'user2'};
          state.profiles=[{id:'matt',name:'Matt',plays_as:'user'},state.profile];
          state.may={admin:false,deck_spaces:['user2']};
          const list=(id,title)=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}]}});
          const lists=[list('casual/gruul','Gruul'),list('casual/otters','Otters'),list('user2/commander/lathliss','Lathliss')];
          const decks={'casual/gruul':{player:'user',status:'building'},'casual/otters':{player:'user',status:'building'},
            'user2/commander/lathliss':{player:null,status:'idea'}};
          clear(main); drawPlay({lists,games:[],sideboards:[],warnings:[],today:'2026-10-08',decks},'');
          const chosen=main.querySelectorAll('select').filter(s=>/^play-quick-deck/.test(s.id||'')).map(s=>lists[Number(s.value)].title);
          same(chosen,['Lathliss','Gruul']);
          same(main.querySelectorAll('.play-outcome').map(b=>b.textContent),['User2 won','Opponent won','Draw']);
          // No games yet: no filter over an empty list.
          assert.equal(main.querySelector('#play-filter'),null);
          state.may=null;
        """)

    def test_a_hidden_side_shows_its_words_only_and_goes_back_unchanged(self):
        # E10-S32: a game against another space's private deck. Its side has no list, can't be changed, and the
        # date, result and notes are the recording space's.
        self.run_js("""
          state.profile={id:'user2',name:'User2',space:'user2'}; state.profiles=[state.profile];
          const mine={id:'user2/casual/elves',version:'target',sha256:'e',title:'Elves',sections:{Deck:[{name:'Forest',qty:60}]}};
          const hidden={hidden:true,title:'one of the home decks',player:'Matt',mulligans:1};
          const record={id:'r',revision:1,updated_by:'someone',date:'2026-10-08',result:'b',notes:'',
            sides:[{...mine,player:'User2',mulligans:0},hidden]};
          const entry={record,sha256:'s',can:{sides:[true,false],result:false}};
          const data={lists:[mine],sideboards:[],today:'2026-10-08'};
          const card=playGameCard(entry,data);
          assert.ok(card.textContent.includes('Elves (User2) vs one of the home decks (Matt)'));
          assert.equal(card.querySelectorAll('h4').length,1);
          assert.equal(playMatchupSummaries([entry]).length,1);
          const requests=[]; apiWrite=async(endpoint,payload)=>{requests.push(payload);throw new Error('Preview stopped for test');};
          playGameForm(data,'',entry);
          const form=document.body.querySelector('.play-form');
          assert.ok(form.textContent.includes('Only that deck'));
          assert.equal(form.querySelector('textarea').disabled,true);
          form.querySelectorAll('input').filter(i=>i.getAttribute('type')==='number')[0].value='2';
          form.fire('submit'); await Promise.resolve(); await Promise.resolve();
          assert.equal(requests.length,1);
          same(requests[0].sides[1],{hidden:true});
          assert.equal(requests[0].sides[0].mulligans,2); assert.equal(requests[0].notes,'');
          assert.equal(requests[0].result,'b');
          // Nothing to change at all: no Correct button.
          assert.equal(playGameCard({...entry,can:{sides:[false,false],result:false}},data)
            .querySelectorAll('button').length,0);
        """)

    def test_a_plan_against_a_hidden_opponent_keeps_it(self):
        self.run_js("""
          state.profile={id:'user2',name:'User2',space:'user2'}; state.profiles=[state.profile];
          const own={id:'user2/casual/elves',version:'target',sha256:'e',title:'Elves',sections:{
            Deck:[{name:'Forest',qty:56},{name:'Llanowar Elves',qty:4}],Sideboard:[{name:'Pick Your Poison',qty:2}]}};
          const plan={id:'p',revision:1,updated_by:'User2',notes:'',deck:own,opponent:{hidden:true,title:'one of the home decks'},
            out:[{name:'Llanowar Elves',qty:1}],in:[{name:'Pick Your Poison',qty:1}],after:own.sections};
          const data={lists:[own],sideboards:[]};
          const card=playPlanCard({record:plan,sha256:'s',editable:true},data);
          assert.ok(card.textContent.includes('against one of the home decks'));
          assert.ok(!card.textContent.includes('A decklist has changed'));
          const requests=[]; apiWrite=async(endpoint,payload)=>{requests.push(payload);throw new Error('Preview stopped for test');};
          playPlanForm(data,'',{record:plan,sha256:'s'});
          const form=document.body.querySelector('.play-form');
          assert.equal(form.querySelectorAll('select').length,1);
          form.fire('submit'); await Promise.resolve(); await Promise.resolve();
          same(requests[0].opponent,{hidden:true});
        """)
