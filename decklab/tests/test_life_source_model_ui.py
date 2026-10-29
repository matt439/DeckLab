"""Two-player v2 source counters and selector-only local packets, in pure Node fixtures."""
import json
import subprocess
import unittest

from decklab.tests.test_pod_life_model_ui import NODE, RUN, WEB

SETUP = """
const NOW=Date.UTC(2026,9,29,12), owner={profile:'matt',space:'home'};
const copy=value=>JSON.parse(JSON.stringify(value));
const list=(id,names=[])=>({id,version:'target',sha256:'b'.repeat(64),title:id,
  sections:{Deck:[{name:'Forest',qty:60}],...(names.length?{Commander:names.map(name=>({name,qty:1}))}:{})}});
const input=(commander=true)=>({profile:'matt',space:'home',session_id:'a'.repeat(32),date:'2026-10-29',
  choices:[{name:'Player A',list:list(commander?'commander/alpha':'casual/alpha',commander?['Commander A']:[])},
    {name:'Player B',list:list(commander?'commander/beta':'casual/beta',commander?['First Partner','Second Partner']:[])}]});
const fresh=(commander=true)=>lifeSourceNewGame(input(commander),NOW);
const player=(game,id)=>game.players.find(row=>row.seat_id===id);
const damage=(game,target,source,sourceId='c1')=>player(game,target).damage.find(row=>row.seat_id===source&&row.source_id===sourceId);
const valid=game=>assert.ok(lifeSourceValid(game,owner,NOW+1000));
const change=(game,id,field,delta,source=null)=>lifeSourceChange(game,id,field,delta,source,NOW+10);
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class LifeSourceModelTests(unittest.TestCase):
    def run_js(self, scenario):
        # Dependencies retain their production relative order; no runtime/DOM script is needed.
        sources = "\n".join((WEB / name).read_text(encoding="utf-8")
                            for name in ("play-pods.js", "pod-life-model.js", "life-source-model.js"))
        result = subprocess.run([NODE, "-e", RUN], input=json.dumps([sources, SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_new_duel_uses_twenty_or_forty_and_stores_only_selectors(self):
        self.run_js("""
          const choices=input(false),before=copy(choices),casual=lifeSourceNewGame(choices,NOW);
          assert.deepEqual(casual.players.map(p=>p.life),[20,20]);assert.equal(casual.commander,false);
          assert.ok(casual.players.every(p=>p.sources.length===0&&p.damage.length===0));valid(casual);
          const commander=fresh();assert.deepEqual(commander.players.map(p=>p.life),[40,40]);
          assert.equal(commander.commander,true);assert.equal(commander.v,2);
          assert.ok(commander.players.every(p=>p.damage.length===3));valid(commander);
          assert.deepEqual(choices,before);assert.equal(casual.players[0].list.sections,undefined);
          assert.equal(casual.players[0].commander,undefined);
          choices.choices[0].list.id='changed';assert.equal(casual.players[0].list.id,'casual/alpha');
        """)

    def test_mixed_duel_keeps_casual_seat_without_invented_sources(self):
        self.run_js("""
          const choices=input(false);choices.choices[1].list=list('commander/beta',['One']);
          const game=lifeSourceNewGame(choices,NOW);valid(game);
          assert.deepEqual(game.players.map(p=>p.life),[40,40]);
          assert.equal(player(game,'a').sources.length,0);assert.equal(player(game,'b').sources.length,1);
          assert.ok(game.players.every(p=>p.damage.length===1&&p.damage[0].seat_id==='b'));
        """)

    def test_safe_public_other_space_and_home_product_selectors_are_allowed(self):
        self.run_js("""
          for(const id of ['user2/commander/public','user2/casual/public','product/precon/deck',
            'product/precon','pairing/first+second','casual/Commander-by-section']) {
            const choices=input();choices.choices[0].list.id=id;const game=lifeSourceNewGame(choices,NOW);
            valid(game);assert.equal(game.players[0].list.id,id);
          }
          for(const id of ['home/commander/a','user2/product/a','user2/casual/a/b','product/a/b/c',
            'casual/.hidden','commander/a:b','commander/a\\\\b']) {
            const choices=input();choices.choices[0].list.id=id;assert.equal(lifeSourceNewGame(choices,NOW),null);
          }
        """)

    def test_literal_names_unknown_commander_and_excess_sources(self):
        self.run_js("""
          const choices=input();choices.choices[0].list=list('casual/front',['Front // Back, the Commander']);
          const game=lifeSourceNewGame(choices,NOW);assert.equal(player(game,'a').sources.length,1);
          assert.equal(player(game,'a').sources[0].label,'Front // Back, the Commander');
          assert.deepEqual(lifeSourceSources(list('commander/unknown')),[{source_id:'c1',label:'Commander 1'}]);
          const excessive=input();excessive.choices[0].list=list('commander/a',['One','Two','Three']);
          assert.match(lifeSourceNewError(excessive,NOW),/at most two/);assert.equal(lifeSourceNewGame(excessive,NOW),null);
          const ambiguous=input();ambiguous.choices[0].list.sections.Commander[0].qty=2;
          assert.equal(lifeSourceNewGame(ambiguous,NOW),null);valid(game);
        """)

    def test_partners_stay_separate_and_same_label_across_players_is_distinct(self):
        self.run_js("""
          const game=fresh();change(game,'a','commander',10,{seat_id:'b',source_id:'c1'});
          change(game,'a','commander',11,{seat_id:'b',source_id:'c2'});
          assert.equal(player(game,'a').life,19);assert.equal(game.ended,null);valid(game);
          change(game,'a','commander',11,{seat_id:'b',source_id:'c1'});
          assert.deepEqual(game.ended,{result:'b',why:'commander',at:NOW+10});valid(game);
          const choices=input();choices.choices[0].list=list('commander/a',['Same']);
          choices.choices[1].list=list('commander/b',['Same']);const identical=lifeSourceNewGame(choices,NOW);
          change(identical,'a','commander',10,{seat_id:'a',source_id:'c1'});
          change(identical,'a','commander',11,{seat_id:'b',source_id:'c1'});
          assert.equal(identical.ended,null);assert.equal(damage(identical,'a','a').value,10);
          assert.equal(damage(identical,'a','b').value,11);valid(identical);
        """)

    def test_own_commander_lethal_and_control_change_keep_original_source_identity(self):
        self.run_js("""
          const game=fresh();change(game,'a','commander',20,{seat_id:'a',source_id:'c1'});
          player(game,'b').name='A different controller';change(game,'a','commander',1,{seat_id:'a',source_id:'c1'});
          assert.equal(lifeSourceOutWhy(game,'a'),'commander');assert.equal(game.ended.result,'b');
          assert.equal(damage(game,'a','a').value,21);assert.equal(damage(game,'a','b').value,0);valid(game);
        """)

    def test_commander_changes_life_by_actual_bounded_delta(self):
        self.run_js("""
          const game=fresh();change(game,'a','life',1000000);assert.equal(player(game,'a').life,999);
          assert.equal(change(game,'a','commander',-99,{seat_id:'b',source_id:'c1'}),false);
          change(game,'a','commander',10,{seat_id:'b',source_id:'c1'});assert.equal(player(game,'a').life,989);
          change(game,'a','commander',-999,{seat_id:'b',source_id:'c1'});assert.equal(player(game,'a').life,999);
          change(game,'a','commander',1000000,{seat_id:'b',source_id:'c1'});
          assert.equal(damage(game,'a','b').value,99);assert.equal(player(game,'a').life,900);valid(game);
        """)

    def test_life_poison_optional_enable_and_simultaneous_draw(self):
        self.run_js("""
          const life=fresh(false);change(life,'a','life',-1000000);
          assert.equal(player(life,'a').life,-999);assert.equal(life.ended.result,'b');valid(life);
          const poison=fresh();change(poison,'a','poison',10);assert.equal(poison.ended,null);
          assert.ok(lifeSourcePoison(poison,true,NOW+20));assert.equal(poison.ended.why,'poison');valid(poison);
          const draw=fresh();change(draw,'a','poison',10);change(draw,'b','poison',99);
          lifeSourcePoison(draw,true,NOW+20);assert.equal(draw.ended.result,'draw');valid(draw);
        """)

    def test_end_and_concession_use_exact_duel_results_and_lock_mutations(self):
        self.run_js("""
          for(const result of ['a','b','draw']) {
            const game=fresh();assert.ok(lifeSourceEnd(game,result,NOW+10));
            assert.equal(game.ended.result,result);assert.equal(lifeSourceEnd(game,'draw',NOW+20),false);
            assert.equal(change(game,'a','life',-1),false);valid(game);
          }
          for(const id of ['a','b']) {const game=fresh();lifeSourceConcede(game,id,NOW+10);
            assert.equal(game.ended.result,id==='a'?'b':'a');assert.equal(game.ended.why,'conceded');valid(game);}
          const game=fresh();assert.equal(lifeSourceEnd(game,'s1',NOW+10),false);
          assert.equal(lifeSourceConcede(game,'s1',NOW+10),false);
        """)

    def test_undo_restores_an_ended_correction_and_binds_all_source_identities(self):
        self.run_js("""
          const game=fresh(),before=copy(game);change(game,'a','life',-40);
          assert.ok(game.ended);assert.ok(lifeSourceUndo(game,before,NOW+20));
          assert.equal(game.ended,null);assert.equal(player(game,'a').life,40);valid(game);
          for(const edit of [p=>p.session_id='c'.repeat(32),p=>p.players[0].list.sha256='d'.repeat(64),
            p=>p.players[0].sources[0].label='Different',p=>p.players[0].name='Different']) {
            const changed=copy(before);edit(changed);assert.equal(lifeSourceUndo(game,changed,NOW+30),false);
          }
        """)

    def test_again_retains_original_selectors_and_sources_without_today_lookup(self):
        self.run_js("""
          const choices=input();choices.choices[0].list.id='casual/commander-by-section';
          const game=lifeSourceNewGame(choices,NOW);change(game,'a','commander',21,{seat_id:'b',source_id:'c1'});
          const next=lifeSourceAgain(game,'c'.repeat(32),NOW+20);valid(next);
          assert.equal(next.commander,true);assert.equal(next.started,NOW+20);assert.equal(next.ended,null);
          assert.ok(next.players.every(p=>p.life===40&&p.poison===0&&p.damage.every(d=>d.value===0)));
          assert.deepEqual(next.players.map(p=>[p.list,p.sources]),game.players.map(p=>[p.list,p.sources]));
          assert.equal(lifeSourceAgain(game,game.session_id,NOW+30),null);
        """)

    def test_v1_aggregate_games_are_never_converted_split_reset_or_overwritten(self):
        self.run_js("""
          const old={v:1,profile:'matt',started:NOW,commander:true,poison:false,ended:null,
            players:[{name:'A',life:40,poison:0,commander:19,list:{id:'commander/a',version:'target',title:'A'}},
              {name:'B',life:40,poison:0,commander:0,list:{id:'commander/b',version:'target',title:'B'}}]};
          const before=JSON.stringify(old);assert.equal(lifeSourceValid(old,owner,NOW),false);
          assert.equal(lifeSourceAgain(old,'c'.repeat(32),NOW),null);assert.equal(change(old,'a','life',-1),false);
          assert.equal(lifeSourceUndo(old,fresh(),NOW),false);assert.equal(JSON.stringify(old),before);
        """)

    def test_strict_packet_keys_source_ledger_and_no_aggregate_or_full_snapshot_fields(self):
        self.run_js("""
          for(const edit of [p=>p.players[0].commander=10,p=>p.players[0].list.sections={Commander:[]},
            p=>p.players[0].list.hidden=true,p=>p.players[0].damage.pop(),
            p=>p.players[0].damage.push(copy(p.players[0].damage[0])),p=>p.players[0].damage[0].value=NaN,
            p=>p.players[0].damage[0].value=100,p=>p.players[0].sources[0].source_id='__proto__',
            p=>p.players[0].seat_id='b',p=>p.commander=false,p=>p.hidden_ids=['secret'],p=>delete p.players[0]]) {
            const bad=fresh();edit(bad);assert.equal(lifeSourceValid(bad,owner,NOW+100),false);
          }
          const injected=JSON.parse(JSON.stringify(fresh()).replace('"v":2','"v":2,"__proto__":{"polluted":true}'));
          assert.equal(lifeSourceValid(injected,owner,NOW),false);assert.equal({}.polluted,undefined);
        """)

    def test_scope_ttl_future_times_and_impossible_ended_states_fail_closed(self):
        self.run_js("""
          const game=fresh();assert.equal(lifeSourceValid(game,{profile:'user1',space:'home'},NOW),false);
          assert.equal(lifeSourceValid(game,{profile:'matt',space:'user2'},NOW),false);
          assert.ok(lifeSourceValid(game,owner,NOW+POD_LIFE_KEEP_MS-1));
          assert.equal(lifeSourceValid(game,owner,NOW+POD_LIFE_KEEP_MS),false);
          for(const edit of [p=>p.started=NOW+1,p=>p.updated=NOW+1,p=>p.updated=Infinity,
            p=>p.started=NaN,p=>p.date='2027-01-01',p=>p.ended={result:'b',why:'commander',at:NOW}]) {
            const bad=fresh();edit(bad);assert.equal(lifeSourceValid(bad,owner,NOW),false);
          }
        """)

    def test_saved_end_causes_must_be_reachable_from_the_models_mutations(self):
        self.run_js("""
          for(const why of ['chosen','conceded']) {
            const game=fresh();game.players[0].life=0;game.ended={result:'b',why,at:NOW};
            assert.equal(lifeSourceValid(game,owner,NOW),false);
          }
          for(const why of ['life','commander','poison']) {
            const game=fresh();game.players.forEach(p=>p.life=0);game.ended={result:'draw',why,at:NOW};
            assert.equal(lifeSourceValid(game,owner,NOW),false);
          }
          const poisoned=fresh();poisoned.poison=true;poisoned.players.forEach(p=>p.poison=10);
          poisoned.ended={result:'draw',why:'commander',at:NOW};assert.equal(lifeSourceValid(poisoned,owner,NOW),false);
          poisoned.ended.why='poison';valid(poisoned);
        """)

    def test_invalid_changes_leave_the_packet_byte_identical(self):
        self.run_js("""
          const game=fresh(),before=JSON.stringify(game);
          for(const delta of [NaN,Infinity,1.5,'1',true,0]) assert.equal(change(game,'a','life',delta),false);
          for(const field of ['__proto__','sources','damage','unknown']) assert.equal(change(game,'a',field,1),false);
          for(const source of [{seat_id:'s1',source_id:'c1'},{seat_id:'a',source_id:'c2'},
            {seat_id:'b',source_id:'c1',hidden:true}]) assert.equal(change(game,'a','commander',1,source),false);
          assert.equal(lifeSourceChange(game,'a','life',1,null,NOW-1),false);
          assert.equal(JSON.stringify(game),before);
        """)

    def test_text_and_source_input_bounds_use_valid_unicode_and_refuse_malformed_data(self):
        self.run_js("""
          for(const edit of [p=>p.choices[0].name='p'.repeat(81),p=>p.choices[0].name='bad\\nname',
            p=>p.choices[0].name='\\ud800',p=>p.choices[0].list.title='t'.repeat(501),
            p=>p.choices[0].list.sections.Commander[0].name='c'.repeat(301),
            p=>p.choices[0].list.sections.Commander={name:'Unknown'},p=>delete p.choices[0]]) {
            const bad=input();edit(bad);assert.equal(lifeSourceNewGame(bad,NOW),null);
          }
          const good=input();good.choices[0].name='🐉'.repeat(80);assert.ok(lifeSourceNewGame(good,NOW));
        """)

    def test_pure_model_performs_no_dom_storage_catalog_or_network_access(self):
        self.run_js("""
          for(const name of ['document','window','localStorage','fetch','local','state'])
            Object.defineProperty(globalThis,name,{get(){throw Error(`model touched ${name}`);}});
          const game=fresh();change(game,'a','commander',1,{seat_id:'a',source_id:'c1'});
          lifeSourceEnd(game,'draw',NOW+20);valid(game);
        """)
