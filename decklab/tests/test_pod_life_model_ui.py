"""Pure pod-counter transitions and strict local packets in Node, without a DOM or I/O model."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
RUN = """const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const [sources,scenario]=JSON.parse(fs.readFileSync(0,'utf8'));
vm.runInNewContext(sources+'\\n'+scenario,{assert},{timeout:5000});process.stdout.write('ok');"""
SETUP = """
const NOW=Date.UTC(2026,9,29,12), owner={profile:'matt',space:'home'};
const copy=value=>JSON.parse(JSON.stringify(value));
const input=(count=3)=>({profile:'matt',space:'home',session_id:'a'.repeat(32),date:'2026-10-29',notes:'',
  seats:Array.from({length:count},(_,i)=>i===0 ? {seat_id:'s1',type:'deck',player:'Player 1',
    deck:{id:'commander/alpha',version:'target',sha256:'b'.repeat(64)},title:'Alpha',
    sources:[{source_id:'c1',label:'Front // Back, the Commander'}]}
    : {seat_id:`s${i+1}`,type:'external',player:`Player ${i+1}`,commander:'Private commander label',
      sources:[{source_id:'c1',label:''}]})});
const fresh=(count=3)=>podLifeNew(input(count),NOW);
const seat=(game,id)=>game.seats.find(s=>s.seat_id===id);
const damage=(game,target,source,commander='c1')=>seat(game,target).damage.find(d=>d.seat_id===source&&d.source_id===commander);
const valid=game=>assert.ok(podLifeValid(game,owner,NOW+1000));
const change=(game,id,field,delta,source=null)=>podLifeChange(game,id,field,delta,source,NOW+10);
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class PodLifeModelTests(unittest.TestCase):
    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8")
                            for name in ("play-pods.js", "pod-life-model.js"))
        result = subprocess.run([NODE, "-e", RUN], input=json.dumps([sources, SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ok")

    def test_three_or_four_players_start_at_forty_and_have_every_source_including_own(self):
        self.run_js("""
          for(const n of [3,4]) {
            const original=input(n),before=copy(original),game=podLifeNew(original,NOW);
            assert.deepEqual(game.seats.map(s=>s.life),Array(n).fill(40));
            assert.deepEqual(game.seats.map(s=>s.poison),Array(n).fill(0));
            assert.ok(game.seats.every(s=>s.damage.length===n && s.damage.every(d=>d.value===0)));
            assert.ok(game.seats.every(s=>damage(game,s.seat_id,s.seat_id)));
            assert.equal(game.poison,false); assert.equal(game.ended,null); valid(game);
            assert.deepEqual(original,before); original.seats[0].deck.id='changed';
            assert.equal(game.seats[0].deck.id,'commander/alpha');
          }
        """)

    def test_commander_names_remain_literal_and_blank_external_sources_are_numbered(self):
        self.run_js("""
          const choices=input();choices.seats[1].sources.push({source_id:'c2',label:'Partner, One // Other Face'});
          const game=podLifeNew(choices,NOW); valid(game);
          assert.equal(seat(game,'s1').sources.length,1);
          assert.equal(seat(game,'s1').sources[0].label,'Front // Back, the Commander');
          assert.equal(seat(game,'s2').sources[0].label,'Commander 1');
          assert.equal(seat(game,'s2').sources[1].label,'Partner, One // Other Face');
          assert.equal(choices.seats[1].sources[0].label,'');
          assert.equal(seat(game,'s1').damage.length,4);
        """)

    def test_partner_and_other_opponent_damage_never_combine_for_twenty_one(self):
        self.run_js("""
          const choices=input(); choices.seats[1].sources.push({source_id:'c2',label:'Second partner'});
          const game=podLifeNew(choices,NOW);
          assert.ok(change(game,'s1','commander',10,{seat_id:'s2',source_id:'c1'}));
          assert.ok(change(game,'s1','commander',10,{seat_id:'s2',source_id:'c2'}));
          assert.ok(change(game,'s1','commander',1,{seat_id:'s3',source_id:'c1'}));
          assert.equal(seat(game,'s1').life,19);assert.equal(podLifeOut(game,'s1'),'');assert.equal(game.ended,null);
          assert.ok(change(game,'s1','commander',11,{seat_id:'s2',source_id:'c1'}));
          assert.equal(podLifeOut(game,'s1'),'commander');assert.equal(game.ended,null);
          assert.equal(damage(game,'s1','s2','c1').value,21);assert.equal(damage(game,'s1','s2','c2').value,10);
          assert.ok(change(game,'s2','life',-1));valid(game);
        """)

    def test_own_commander_can_eliminate_and_identity_survives_controller_label_changes(self):
        self.run_js("""
          const game=fresh();assert.ok(change(game,'s1','commander',20,{seat_id:'s1',source_id:'c1'}));
          assert.equal(podLifeOut(game,'s1'),'');seat(game,'s2').player='Controller changed';
          assert.ok(change(game,'s1','commander',1,{seat_id:'s1',source_id:'c1'}));
          assert.equal(podLifeOut(game,'s1'),'commander');assert.equal(damage(game,'s1','s1').value,21);
          assert.equal(damage(game,'s1','s2').value,0);assert.equal(game.ended,null);valid(game);
        """)

    def test_commander_life_uses_actual_bounded_damage_delta_and_corrections(self):
        self.run_js("""
          const game=fresh();change(game,'s1','life',1000000);assert.equal(seat(game,'s1').life,999);
          assert.equal(change(game,'s1','commander',-50,{seat_id:'s2',source_id:'c1'}),false);
          assert.equal(seat(game,'s1').life,999);
          change(game,'s1','commander',10,{seat_id:'s2',source_id:'c1'});assert.equal(seat(game,'s1').life,989);
          change(game,'s1','commander',-500,{seat_id:'s2',source_id:'c1'});
          assert.equal(damage(game,'s1','s2').value,0);assert.equal(seat(game,'s1').life,999);
          change(game,'s1','commander',1000000,{seat_id:'s2',source_id:'c1'});
          assert.equal(damage(game,'s1','s2').value,99);assert.equal(seat(game,'s1').life,900);valid(game);
        """)

    def test_life_bounds_and_first_elimination_leave_other_seats_playable(self):
        self.run_js("""
          const game=fresh(4);change(game,'s1','life',-1000000);
          assert.equal(seat(game,'s1').life,-999);assert.equal(podLifeOut(game,'s1'),'life');assert.equal(game.ended,null);
          assert.equal(change(game,'s1','life',5),false);assert.ok(change(game,'s2','life',-1));
          change(game,'s2','life',1000000);assert.equal(seat(game,'s2').life,999);valid(game);
        """)

    def test_poison_is_optional_and_enabling_it_marks_each_affected_seat_out(self):
        self.run_js("""
          const game=fresh(4);change(game,'s1','poison',10);change(game,'s2','poison',99);
          assert.equal(game.ended,null);assert.equal(podLifeOut(game,'s1'),'');
          assert.ok(podLifePoison(game,true,NOW+20));assert.equal(podLifeOut(game,'s1'),'poison');
          assert.equal(podLifeOut(game,'s2'),'poison');assert.equal(game.ended,null);valid(game);
          assert.ok(podLifePoison(game,false,NOW+30));assert.equal(podLifeOut(game,'s1'),'poison');valid(game);
          assert.ok(podLifeConcede(game,'s3',NOW+40));assert.equal(game.ended.result,'s4');valid(game);
        """)

    def test_simultaneous_poison_elimination_can_end_in_a_draw(self):
        self.run_js("""
          const game=fresh();for(const player of game.seats) change(game,player.seat_id,'poison',10);
          podLifePoison(game,true,NOW+20);assert.equal(game.ended.result,'draw');valid(game);
        """)

    def test_concession_and_last_active_winner_use_stable_seat_ids(self):
        self.run_js("""
          const choices=input(4);choices.seats.reverse();const game=podLifeNew(choices,NOW);
          for(const id of ['s1','s3']) {assert.ok(podLifeConcede(game,id,NOW+20));assert.equal(game.ended,null);}
          assert.ok(podLifeConcede(game,'s2',NOW+30));assert.deepEqual(game.ended,{result:'s4',why:'last',at:NOW+30});
          assert.equal(podLifeConcede(game,'s4',NOW+40),false);valid(game);
        """)

    def test_explicit_end_accepts_only_present_active_winner_or_draw_and_keeps_end(self):
        self.run_js("""
          for(const result of ['s1','s2','s3','draw']) {
            const game=fresh();assert.ok(podLifeEnd(game,result,NOW+10));
            assert.deepEqual(podLifeEnded(game),{result,why:'chosen',at:NOW+10});
            assert.equal(podLifeEnd(game,'draw',NOW+20),false);assert.equal(change(game,'s1','life',-1),false);valid(game);
          }
          const game=fresh();podLifeConcede(game,'s2',NOW+10);
          for(const result of ['s2','s4','a','__proto__',null]) assert.equal(podLifeEnd(game,result,NOW+20),false);
        """)

    def test_explicit_second_external_source_is_stable_and_added_to_every_recipient(self):
        self.run_js("""
          const game=fresh();assert.ok(podLifeAddSource(game,'s2','',NOW+10));
          assert.deepEqual(seat(game,'s2').sources,[{source_id:'c1',label:'Commander 1'},{source_id:'c2',label:'Commander 2'}]);
          assert.ok(game.seats.every(s=>damage(game,s.seat_id,'s2','c2').value===0));
          assert.equal(podLifeAddSource(game,'s2','Third',NOW+20),false);
          assert.equal(podLifeAddSource(game,'s1','Invented saved commander',NOW+20),false);valid(game);
          const blank=fresh();assert.ok(podLifeAddSource(blank,'s2','   ',NOW+10));valid(blank);
          assert.equal(seat(blank,'s2').sources[1].label,'Commander 2');
        """)

    def test_undo_restores_elimination_and_source_topology_with_exact_session_binding(self):
        self.run_js("""
          const game=fresh(),before=copy(game);change(game,'s1','life',-40);
          assert.equal(podLifeOut(game,'s1'),'life');assert.ok(podLifeUndo(game,before,NOW+20));
          assert.equal(seat(game,'s1').life,40);assert.equal(podLifeOut(game,'s1'),'');assert.equal(game.updated,NOW+20);
          const prior=copy(game);podLifeAddSource(game,'s2','Partner',NOW+30);
          assert.ok(podLifeUndo(game,prior,NOW+40));assert.equal(seat(game,'s2').sources.length,1);valid(game);
          for(const edit of [p=>p.session_id='c'.repeat(32),p=>p.profile='user1',p=>p.seats[0].deck.sha256='d'.repeat(64)]) {
            const foreign=copy(prior);edit(foreign);assert.equal(podLifeUndo(game,foreign,NOW+50),false);
          }
          const renamed=copy(prior);renamed.seats[1].sources[0].label='Different commander';
          assert.equal(podLifeUndo(game,renamed,NOW+50),false);
        """)

    def test_reset_is_a_new_local_session_without_silently_replacing_selectors(self):
        self.run_js("""
          const game=fresh();podLifeAddSource(game,'s2','Partner',NOW+10);podLifeConcede(game,'s1',NOW+20);
          const next=podLifeReset(game,'c'.repeat(32),NOW+30);valid(next);
          assert.equal(next.session_id,'c'.repeat(32));assert.equal(next.started,NOW+30);
          assert.ok(next.seats.every(s=>s.life===40&&s.poison===0&&s.out===null&&s.damage.every(d=>d.value===0)));
          assert.equal(next.poison,false);assert.equal(next.ended,null);assert.equal(next.seats[1].sources.length,2);
          assert.deepEqual(next.seats[0].deck,game.seats[0].deck);assert.notEqual(next.seats[0].deck,game.seats[0].deck);
          assert.equal(podLifeReset(game,game.session_id,NOW+40),null);
        """)

    def test_invalid_mutation_fields_sources_deltas_or_times_change_nothing(self):
        self.run_js("""
          const game=fresh(),before=JSON.stringify(game);
          for(const delta of [NaN,Infinity,-Infinity,1.5,true,'1',0,Number.MAX_SAFE_INTEGER+1])
            assert.equal(change(game,'s1','life',delta),false);
          for(const field of ['__proto__','constructor','out','unknown']) assert.equal(change(game,'s1',field,1),false);
          for(const source of [{seat_id:'s4',source_id:'c1'},{seat_id:'s2',source_id:'c2'},
            {seat_id:'s2',source_id:'__proto__'},{seat_id:'s2',source_id:'c1',hidden:true}])
            assert.equal(change(game,'s1','commander',1,source),false);
          assert.equal(podLifeChange(game,'s1','life',1,null,NOW-1),false);
          assert.equal(JSON.stringify(game),before);assert.equal({}.polluted,undefined);
        """)

    def test_storage_ttl_future_and_nonfinite_timestamps_fail_closed(self):
        self.run_js("""
          const game=fresh();assert.ok(podLifeValid(game,owner,NOW+POD_LIFE_KEEP_MS-1));
          assert.equal(podLifeValid(game,owner,NOW+POD_LIFE_KEEP_MS),false);
          for(const edit of [p=>p.started=NOW+1,p=>p.updated=NOW+1,p=>p.started=NaN,p=>p.updated=Infinity,
            p=>p.updated=NOW-1,p=>p.started='now']) {const bad=copy(game);edit(bad);assert.equal(podLifeValid(bad,owner,NOW),false);}
          assert.equal(podLifeValid(game,owner,NaN),false);
          podLifeConcede(game,'s1',NOW+10);const bad=copy(game);bad.seats[0].out.at=NOW+20;
          assert.equal(podLifeValid(bad,owner,NOW+100),false);
        """)

    def test_strict_packet_and_selector_fields_never_accept_full_snapshots_or_hidden_metadata(self):
        self.run_js("""
          const changes=[p=>p.v=2,p=>p.hidden_ids=['secret'],p=>p.session_id='not-a-session',
            p=>p.seats[0].deck.sections={Commander:[]},p=>p.seats[0].deck.hidden=true,p=>p.seats[0].life=NaN,
            p=>p.seats[0].life=1000,p=>p.seats[0].poison=100,p=>p.seats[1].commander=null,
            p=>p.seats[1].sources[0].source_id='constructor',p=>p.seats[1].seat_id='s1'];
          for(const edit of changes) {const bad=fresh();edit(bad);assert.equal(podLifeValid(bad,owner,NOW+100),false);}
          const bad=fresh();Object.defineProperty(bad.seats[0].deck,'hidden',{value:true,enumerable:false});
          assert.equal(podLifeValid(bad,owner,NOW),false);
          const injected=JSON.parse(JSON.stringify(fresh()).replace('"v":1','"v":1,"__proto__":{"polluted":true}'));
          assert.equal(podLifeValid(injected,owner,NOW),false);assert.equal({}.polluted,undefined);
        """)

    def test_damage_matrix_is_complete_unique_bounded_and_source_specific(self):
        self.run_js("""
          for(const edit of [p=>p.seats[0].damage.pop(),p=>p.seats[0].damage.push(copy(p.seats[0].damage[0])),
            p=>p.seats[0].damage[0].value=-1,p=>p.seats[0].damage[0].value=100,
            p=>p.seats[0].damage[0].value=1.5,p=>p.seats[0].damage[0].seat_id='s4',
            p=>p.seats[0].damage[0].source_id='__proto__']) {
            const bad=fresh();edit(bad);assert.equal(podLifeValid(bad,owner,NOW+100),false);
          }
        """)

    def test_profile_space_and_own_deck_selector_scope_are_required_without_catalog_substitution(self):
        self.run_js("""
          const game=fresh();assert.equal(podLifeValid(game,{profile:'user1',space:'home'},NOW),false);
          assert.equal(podLifeValid(game,{profile:'matt',space:'user2'},NOW),false);
          const choices=input();choices.profile='user2';choices.space='user2';choices.seats[0].deck.id='user2/commander/alpha';
          const member=podLifeNew(choices,NOW);assert.ok(podLifeValid(member,{profile:'user2',space:'user2'},NOW));
          choices.seats[0].deck.id='commander/alpha';assert.equal(podLifeNew(choices,NOW),null);
          for(const id of ['home/commander/alpha','user2/commander/alpha','product/a/b/c','pairing/a/b',
            'product//b','product/a/.hidden','casual/a:b','commander/a\\\\b']) {
            const bad=input();bad.seats[0].deck.id=id;assert.equal(podLifeNew(bad,NOW),null);
          }
          for(const id of ['casual/alpha','product/precon','product/precon/deck','pairing/first+second']) {
            const good=input();good.seats[0].deck.id=id;assert.ok(podLifeNew(good,NOW));
          }
          choices.seats[0].deck.id='user2/casual/alpha';assert.ok(podLifeNew(choices,NOW));
          for(const id of ['user2/product/precon','user2/pairing/a+b','user2/casual/a/b']) {
            choices.seats[0].deck.id=id;assert.equal(podLifeNew(choices,NOW),null);
          }
          const stale=fresh();stale.seats[0].deck.sha256='c'.repeat(64);valid(stale);
          assert.equal(stale.seats[0].deck.sha256,'c'.repeat(64));
        """)

    def test_constructor_rejects_excess_sources_malformed_text_and_future_date(self):
        self.run_js("""
          const three=input();three.seats[1].sources.push({source_id:'c2',label:'Two'},{source_id:'c3',label:'Three'});
          assert.match(podLifeNewError(three,NOW),/at most two/);assert.equal(podLifeNew(three,NOW),null);
          for(const edit of [p=>p.seats[0].player='p'.repeat(81),p=>p.seats[0].player='bad\\nname',
            p=>p.seats[0].player='\\ud800',p=>p.seats[0].title='t'.repeat(501),p=>p.notes='n'.repeat(2001),
            p=>p.seats[0].sources[0].label='c'.repeat(301),p=>p.date='2026-02-29',p=>p.date='0000-01-01',
            p=>p.date='2027-01-01',p=>p.seats[0].sources=[],p=>p.seats[0].deck.id='commander/../hidden']) {
            const bad=input();edit(bad);assert.equal(podLifeNew(bad,NOW),null);
          }
          const good=input();good.notes='Literal notes\\nwith\\ttabs';good.seats[0].player='🐉'.repeat(80);
          assert.ok(podLifeNew(good,NOW));
        """)

    def test_model_does_not_touch_dom_storage_network_or_current_catalog(self):
        self.run_js("""
          for(const name of ['document','window','localStorage','fetch','local','state'])
            Object.defineProperty(globalThis,name,{get(){throw Error(`model touched ${name}`);}});
          const game=fresh();assert.ok(change(game,'s1','life',-1));assert.ok(podLifeConcede(game,'s2',NOW+20));
          assert.ok(podLifeEnd(game,'draw',NOW+30));valid(game);
        """)

    def test_sparse_arrays_and_array_metadata_never_hide_missing_or_unknown_sources(self):
        self.run_js("""
          const choices=input();choices.seats[0].sources=Array(1);assert.equal(podLifeNew(choices,NOW),null);
          for(const edit of [p=>delete p.seats[0],p=>delete p.seats[0].sources[0],
            p=>delete p.seats[0].damage[0],p=>p.seats.hidden_ids=['secret'],
            p=>p.seats[0].sources.hidden_ids=['secret'],p=>p.seats[0].damage.hidden_ids=['secret']]) {
            const bad=fresh();edit(bad);assert.equal(podLifeValid(bad,owner,NOW),false);
          }
        """)
