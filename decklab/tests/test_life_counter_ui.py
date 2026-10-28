"""The life counter (E4-S26): its game model, the Game log's way in, keeping the game, and the end opening Record
result filled in, in Node with the page's real scripts."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
RUNNER = Path(__file__).resolve().parent / "fixtures/workspace_ui_runner.js"
NODE = shutil.which("node")

# Two lists, a stand-in localStorage and the page's write stubbed: every scenario starts from these.
SETUP = """
  const store=new Map();
  window.localStorage={getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)};
  state.profile={id:'matt',name:'Matt',space:'home',plays_as:'user'};
  state.profiles=[state.profile,{id:'user1',name:'User1',space:'home',plays_as:'wife'}];
  const list=(id,title,extra={})=>({id,version:'target',sha256:id,title,sections:{Deck:[{name:'Forest',qty:60}],...extra}});
  const lists=[list('casual/a','Alpha'),list('casual/b','Beta'),list('commander/c','Gamma',{Commander:[{name:'Giada',qty:1}]})];
  const decks={'casual/a':{player:'user',status:'built',can_record:true},'casual/b':{player:'wife',status:'built',can_record:true},
    'commander/c':{player:'either',status:'built',can_record:true}};
  const data={lists,games:[],sideboards:[],warnings:[],today:'2026-10-28',decks};
  const requests=[], said=[]; let routes=0; route=()=>{routes++;}; toast=t=>said.push(t); location.hash='#/play';
  apiWrite=async(endpoint,payload)=>{
    requests.push({endpoint,payload});
    return payload.preview ? {id:'new',record:{date:payload.date,result:payload.result,notes:payload.notes,
      sides:payload.sides.map(s=>({...lists.find(l=>l.id===s.id),...s}))},review_sha256:'review'}
      : {saved:true,record:{id:'new',revision:1},sha256:'f'.repeat(64)};
  };
  const counter=()=>document.body.querySelector('.life-counter');
  const press=label=>counter().querySelectorAll('button').find(b=>b.getAttribute('aria-label')===label);
  const named=(root,text)=>root.querySelectorAll('button').find(b=>b.textContent===text);
  const totals=()=>counter().querySelectorAll('.life-total').map(o=>o.textContent);
  const kept=()=>JSON.parse(store.get(STORE+LIFE_KEY)||'null');
  const tick=async()=>{ for(let n=0;n<10;n++) await Promise.resolve(); };
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class LifeCounterUiTests(unittest.TestCase):
    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("hands.js", "play.js", "life-counter.js"))
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), sources + "\n" + SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_game_model(self):
        self.run_js("""
          const game=lifeNewGame([{list:lists[0],name:'Matt'},{list:lists[1],name:'User1'}],'matt',1000);
          same(game.players.map(p=>p.life),[20,20]); assert.equal(game.commander,false);
          assert.equal(lifeNewGame([{list:lists[0],name:'A'},{list:lists[2],name:'B'}],'matt').players[0].life,40);
          assert.ok(lifeIsCommander({id:'user2/commander/x',sections:{}})); assert.ok(!lifeIsCommander(lists[0]));
          // Poison counts only once it's switched on.
          for(let n=0;n<10;n++) lifeChange(game,0,'poison',1);
          assert.equal(game.ended,null); assert.equal(game.players[0].poison,10);
          game.poison=true; lifeChange(game,0,'poison',1,5000);
          same(game.ended,{result:'b',why:'poison',at:5000});
          assert.equal(lifeChange(game,1,'life',-1),false); assert.equal(game.players[1].life,20);
          same(lifeEndWords(game),['User1 won.','Matt has 11 poison counters.']);
          // Commander damage is life lost too, and 21 ends the game.
          const big=lifeNewGame([{list:lists[2],name:'A'},{list:lists[2],name:'B'}],'matt');
          lifeChange(big,1,'commander',20); same([big.players[1].life,big.ended],[20,null]);
          lifeChange(big,1,'commander',1); same([big.players[1].life,big.ended.result,big.ended.why],[19,'a','commander']);
          same(lifeAgain(big).players.map(p=>[p.life,p.commander]),[[40,0],[40,0]]);
          assert.equal(lifeClockWords(65000),'1:05'); assert.equal(lifeClockWords(3725000),'1:02:05');
          lifeEnd(game,'draw'); assert.equal(game.ended.result,'b');     // an ended game keeps its end
        """)

    def test_counter_starts_from_the_quick_record_and_survives_a_refresh(self):
        self.run_js("""
          clear(main); drawPlay(data,'');
          const quick=main.querySelector('.play-quick');
          document.getElementById('play-quick-deck-1').value='2';           // Gamma has a Commander: 40 life
          named(quick,'Life counter').click();
          assert.ok(counter()); same(totals(),['40','40']);
          assert.match(counter().textContent,/Matt.*Alpha/); assert.match(counter().textContent,/User1.*Gamma/);
          assert.equal(counter().querySelectorAll('.life-small').filter(r=>!r.hidden).length,2);   // commander damage each
          press('User1: 1 life less (hold for 5)').click(); same(totals(),['40','39']);
          // Held, a press goes 5 at a time; letting go doesn't add the tap's 1.
          const minus=press('Matt: 1 life less (hold for 5)');
          minus.fire('pointerdown'); flushTimers(); minus.fire('pointerup'); minus.click();
          same(totals(),['35','39']);
          press('Matt: 5 more life').click(); same(totals(),['40','39']);
          named(counter(),'Poison').click(); assert.equal(named(counter(),'Poison').getAttribute('aria-pressed'),'true');
          same(kept().players.map(p=>p.life),[40,39]); assert.equal(kept().poison,true);
          // Closed (or the page reloaded), the Game log offers Resume with the kept totals.
          named(counter(),'Close').click(); assert.equal(counter(),null);
          clear(main); drawPlay(data,'');
          assert.match(main.querySelector('.play-counter').textContent,/Matt 40 · User1 39/);
          named(main,'Resume life counter').click(); same(totals(),['40','39']);
          closeLifeCounter();
          // Another profile, or a deck no longer listed, gets a fresh counter instead.
          state.profile=state.profiles[1]; assert.equal(lifeSaved(data),null);
          state.profile=state.profiles[0]; assert.ok(lifeSaved(data));
          assert.equal(lifeSaved({...data,lists:lists.slice(0,2)}),null);
          store.set(STORE+LIFE_KEY,'{not json'); assert.equal(lifeSaved(data),null);
          // Storage that throws (a private window) still counts.
          window.localStorage={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
          clear(main); drawPlay(data,''); named(main,'Life counter').click();
          press('Matt: 1 life less (hold for 5)').click(); same(totals(),['19','20']);
          closeLifeCounter();
        """)

    def test_reaching_zero_opens_record_result_filled_in_and_saving_ends_the_counter(self):
        self.run_js("""
          clear(main); drawPlay(data,'');
          document.getElementById('play-quick-name-1').value='Sam';
          named(main.querySelector('.play-quick'),'Life counter').click();
          for(let n=0;n<3;n++) press('Sam: 5 life less').click();
          press('Sam: 1 more life (hold for 5)').click(); same(totals(),['20','6']);
          for(let n=0;n<5;n++) press('Sam: 1 life less (hold for 5)').click();
          assert.equal(document.body.querySelector('.play-form'),null);
          press('Sam: 1 life less (hold for 5)').click();
          assert.match(counter().querySelector('.life-end').textContent,/Matt won[.]Sam is at 0 life[.]/);
          const form=document.body.querySelector('.play-form'); assert.ok(form);
          const selects=form.querySelectorAll('select');
          same([selects[0].value,selects[2].value,selects[4].value],['0','1','a']);
          same(form.querySelectorAll('input').filter(i=>i.getAttribute('type')==='text').map(i=>i.value),['Matt','Sam']);
          assert.ok(kept().ended);                              // kept until it's saved
          form.fire('submit'); await tick(); await tick();
          same(requests[0].payload.sides.map(s=>[s.id,s.player]),[['casual/a','Matt'],['casual/b','Sam']]);
          named(document.body,'Save this record').click(); await tick(); await tick();
          assert.equal(requests.length,2); assert.equal(requests[1].payload.preview,false);
          assert.equal(counter(),null); assert.equal(kept(),null); assert.equal(routes,1);
        """)

    def test_end_game_names_the_winner_and_back_to_the_game_carries_on(self):
        self.run_js("""
          clear(main); drawPlay(data,''); named(main,'Life counter').click();
          named(counter(),'End game').click();
          const end=counter().querySelector('.life-end'); assert.equal(end.hidden,false);
          named(end,'Keep playing').click(); assert.equal(end.hidden,true);
          named(counter(),'End game').click(); named(end,'Draw').click();
          assert.equal(document.body.querySelector('.play-form').querySelectorAll('select')[4].value,'draw');
          document.body.querySelector('.play-form').closest('.sheet').remove();
          assert.match(end.textContent,/Draw[.]/);
          named(end,'Back to the game').click(); assert.equal(kept().ended,null); assert.equal(end.hidden,true);
          press('Matt: 1 life less (hold for 5)').click(); same(totals(),['19','20']);
          named(counter(),'End game').click(); named(end,'User1 won').click();
          named(end,'New game').click(); same(totals(),['20','20']); assert.equal(kept().ended,null);
          closeLifeCounter();
        """)

    def test_a_viewer_who_may_not_record_these_decks_only_counts(self):
        self.run_js("""
          for (const id in decks) decks[id].can_record=false;
          clear(main); drawPlay(data,''); named(main,'Life counter').click();
          for(let n=0;n<4;n++) press('User1: 5 life less').click();
          assert.equal(document.body.querySelector('.play-form'),null);
          const end=counter().querySelector('.life-end');
          assert.match(end.textContent,/Matt won[.].*can't record a game with these decks/);
          assert.equal(named(end,'Record result'),undefined);
          assert.equal(requests.length,0);
          closeLifeCounter();
        """)


if __name__ == "__main__":
    unittest.main()
