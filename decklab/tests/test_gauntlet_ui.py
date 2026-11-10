"""The deck page's "Against popular decks" part (web/gauntlet.js) through its real renderers over an isolated
Node DOM: the missing catalogue's command, the empty state's Play, the choices, the groups and opponents, and a
run's poll and Stop. Every answer is a fixture; no live server, network, configuration, database or simulation
is used.

Run with python scripts/test_fixtures.py decklab.tests.test_gauntlet_ui.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

# A fixed 2 Nov of this year at noon UTC: 2 Nov in every time zone the PC and CI run in, and no year shown.
DAY = "const day=`${new Date().getFullYear()}-11-02T12:00:00Z`;const hasClass=(n,c)=>!!n&&(n.getAttribute('class')||'').split(' ').includes(c);"


SETUP = PAGE + """
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
  const calls=[],writes=[];let answers=[];
  api=async path=>{calls.push(path);const next=answers.length>1?answers.shift():answers[0];
    if(next instanceof Error)throw next;return structuredClone(next);};
  apiWrite=async(path,body)=>{writes.push({path,body});return structuredClone(answers[0]);};
  toast=()=>{};
  const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
  const sha='a'.repeat(64);
  const base=(extra={})=>({deck:{id:'casual/test',version:'target',title:'Test Deck',card_sha:sha},format:'constructed',
    build_command:'python -m decklab.lib.forge gauntlet build --format constructed',credit:'Average decks from EDHREC.',
    options:{sizes:[12,24,36],colours:'WUBRG',styles:['aggro','midrange','control','combo','ramp'],
      tiers:['precon','easy','medium','hard','very hard'],budgets:['fixed:50','fixed:100','fixed:200']},
    default_budget:'fixed:100',default_size:24,forge:{ready:true},catalogue:{playable:3},
    sample:{id:'sample:0123456789ab',size:24,filters:{colours:null,styles:null,tiers:['hard','medium']},decks:3},
    opponents:[],groups:{},games:0,note:null,notes:[],status:'none',job:null,notice:null,error:null,
    budgets:{'fixed:100':{games:100,new_games:300,minutes:[3,5]}},...extra});
  const rate=(value)=>({value,low:value-.1,high:value+.1});
  const opponent=(id,title,value,source)=>({id,title,tier:'medium',identity:'R',style:'aggro',games:100,rate:rate(value),
    lead:null,not_meaningful:false,problem:null,source});
  const played=()=>base({games:300,note:'Each range covers these 3 sampled opponents only, not every deck of that colour.',
    opponents:[opponent('gauntlet:edhrec/krenko-core','Krenko, Mob Boss',.3,{kind:'edhrec',url:'https://edhrec.com/average-decks/krenko/core',rank:4,decks:12000}),
      opponent('gauntlet:precon/x','Some Precon',.5,{kind:'mtgjson',url:null}),
      opponent('gauntlet:forge/duels/y','Some Duel',.7,{kind:'forge'})],
    groups:{colour:[{key:'R',label:'Red',opponents:3,games:300,rate:.5,low:.4,high:.6,spread:[.3,.7],note:'overlapping'}],
      style:[{key:'aggro',label:'Aggro',opponents:1,games:100,rate:.3,low:.2,high:.4,spread:[.3,.3],note:'one opponent, not a group'}],
      identity_size:[],tier:[]}});
  const draw=async()=>{const node=gauntletSection({summary:{id:'casual/test',title:'Test Deck'},version:'target'});
    main.append(node);await settle();return node;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GauntletUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_running_lists_link_opens_matchups_at_the_gauntlet(self):
        self.run_js("""
          answers=[base()];const jumps=[];jumpTo=(id)=>jumps.push(id);
          open('#/deck?id=casual%2Ftest&v=target&part=gauntlet');await settle();
          flushTimers();
          assert.equal(panel('matchups').hidden,false);assert.equal(panel('overview').hidden,true);
          assert(panel('matchups').querySelector('#sec-gauntlet'));
          same(jumps,['sec-gauntlet']);
          assert(!location.hash.includes('part='));assert(location.hash.includes('tab=matchups'));
        """)

    def test_no_tier_ticked_asks_for_every_tier(self):
        self.run_js("""
          const c={size:24,colours:'',styles:[],tiers:[]};
          same(gtTiersAsked(c,base()),['precon','easy','medium','hard','very hard']);
          same(gtTiersAsked({...c,tiers:['hard']},base()),['hard']);
          assert(gtChoiceWords(c,base()).includes('every tier'));
          answers=[base()];const node=await draw();
          const ctx={answer:base(),choice:c,budget:'fixed:100',id:'casual/test',version:'target'};
          assert(gtUrl(ctx).includes('tiers=precon%2Ceasy%2Cmedium%2Chard%2Cvery+hard'),gtUrl(ctx));
        """)

    def test_a_missing_catalogue_shows_the_command_and_no_play(self):
        self.run_js("""
          answers=[base({catalogue:null,sample:null,budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('There are no popular 60-card decks on the PC yet.'));
          assert.equal(node.querySelector('code').textContent,'python -m decklab.lib.forge gauntlet build --format constructed');
          assert(!buttonText(node,'Play them'));
          assert.equal(calls.length,1);assert(calls[0].startsWith('/api/gauntlet?id=casual%2Ftest&version=target'));
          assert.equal(writes.length,0);
          // Anyone but an admin gets no command (the server gives none).
          answers=[base({catalogue:null,sample:null,budgets:{},build_command:null})];
          const member=await draw();
          assert(member.textContent.includes('An admin builds them once on the PC.'));
          assert(!member.querySelector('code'));
        """)

    def test_a_playing_other_sample_has_no_back_to_the_standard_sample(self):
        self.run_js("""
          answers=[base({standard:{id:'sample:ffffffffffff',size:24,tiers:['hard','medium']},is_standard:false,
            status:'running',job:{status:'running',done:0,total:100,ahead:0,pairs:{}},budgets:{}})];
          const node=await draw();
          assert(!buttonText(node,'Back to the standard sample'));
          assert(node.textContent.includes('Not the standard sample. The standard sample shows again when this run ends.'));
        """)

    def test_the_empty_state_plays_its_choices_with_the_saved_list(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          assert(node.textContent.includes('No games against popular decks yet.'));
          assert(node.textContent.includes('About 100 games a deck, about 3–5 minutes.'));
          const play=buttonText(node,'Play them');assert(play&&!play.disabled);
          play.click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/gauntlet/run');
          same(writes[0].body,{id:'casual/test',version:'target',budget:'fixed:100',size:24,colours:'',styles:'',
            tiers:'hard,medium',expected_card_sha:sha});
        """)

    def test_choices_draw_the_sample_again_without_playing(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          const summary=node.querySelector('.gt-choices').querySelector('summary');
          assert.equal(summary.textContent,'3 opponents · Hard, Medium · any colours · any style');
          buttonText(node,'Control').click();await settle();
          assert(calls.at(-1).includes('styles=control'));assert(calls.at(-1).includes('size=24'));
          buttonText(node,'Red').click();await settle();
          assert(calls.at(-1).includes('colours=R'));
          buttonText(node,'12').click();await settle();
          assert(calls.at(-1).includes('size=12'));
          assert.equal(writes.length,0);
        """)

    def test_results_by_group_with_the_caveat_and_each_opponent_hardest_first(self):
        self.run_js("""
          answers=[played()];
          const node=await draw();
          const groups=node.querySelector('.gt-groups');
          assert(groups.textContent.includes('Red'));assert(groups.textContent.includes('3 opponents · 300 games'));
          assert(groups.textContent.includes('from 30% to 70% by opponent'));
          assert(node.textContent.includes('Each range covers these 3 sampled opponents only'));
          buttonText(node,'Style').click();
          assert(node.querySelector('.gt-groups').textContent.includes('one opponent, not a group'));
          assert.equal(node.querySelector('.gt-groups').querySelector('.gt-muted').querySelector('.gt-name').textContent,'Aggro');
          const names=node.querySelector('.gt-rows').querySelectorAll('.gt-name').map(n=>n.textContent);
          same(names,['Krenko, Mob Boss','Some Precon','Some Duel']);
          const link=node.querySelector('.gt-rows').querySelector('a');
          assert.equal(link.getAttribute('href'),'https://edhrec.com/average-decks/krenko/core');
          assert.equal(link.getAttribute('rel'),'noopener noreferrer');
          assert(node.textContent.includes('Average deck from EDHREC (rank 4, 12,000 decks)'));
          assert(node.textContent.includes('Wizards precon, from MTGJSON'));
          assert(node.textContent.includes('A deck bundled with Forge'));
          assert(node.textContent.includes('Average decks from EDHREC.'));
        """)

    def test_a_run_polls_and_stops_after_asking(self):
        self.run_js("""
          const job={status:'running',done:50,total:200,by:'someone',may_stop:true,ahead:0,
            pairs:{k:{opponent:{id:'gauntlet:forge/duels/y',title:'Some Duel'},done:50,total:200,playing:true}}};
          answers=[base({status:'running',job,budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('Playing: Some Duel'));assert(node.textContent.includes('Started by someone'));
          const before=calls.length;flushTimers();await settle();assert.equal(calls.length,before+1);
          let asked=0;ask=async()=>{asked++;return 'stop';};
          answers=[base()];
          buttonText(node,'Stop').click();await settle();
          assert.equal(asked,1);assert.equal(writes.at(-1).path,'/api/gauntlet/stop');
          same(writes.at(-1).body,{id:'casual/test',version:'target'});
          assert(buttonText(node,'Play them'));
        """)

    def test_no_stop_without_the_right_and_late_answers_leave_another_page_alone(self):
        self.run_js("""
          answers=[base({status:'queued',job:{status:'queued',done:0,total:300,ahead:2,may_stop:false,pairs:{}},budgets:{}})];
          const node=await draw();
          assert(node.textContent.includes('Waiting: 2 runs ahead of it'));assert(!buttonText(node,'Stop'));
          let release;api=()=>new Promise(r=>{release=r;});
          flushTimers();routeToken++;release(played());await settle();
          assert(node.textContent.includes('Waiting: 2 runs ahead of it'));
        """)

    # ------------------------------------------------------------------ E3-S33: the standard sample and headline

    def test_a_commander_decks_matchups_tab_leads_with_popular_decks(self):
        self.run_js("""
          answers=[base()];
          const ids=()=>panel('matchups').children.map(n=>n.getAttribute('id'));
          open('#/deck?id=casual%2Ftest&v=target&tab=matchups');await settle();
          same(ids(),['sec-matchups','sec-field','sec-group','sec-gauntlet','sec-tests','sec-crosscheck']);
          clear(main);location.hash='#/deck?id=commander%2Ftest&v=target&tab=matchups';
          const page=makePage();page.summary={...page.summary,id:'commander/test',kind:'commander'};
          drawDeck(page,deckViewOf(parseHash().params));await settle();
          same(ids(),['sec-gauntlet','sec-matchups','sec-field','sec-group','sec-tests','sec-crosscheck']);
        """)

    def test_the_headline_and_verdicts_come_before_the_play_box(self):
        self.run_js("""
          const a=played();
          a.opponents[0].verdict='behind';a.opponents[0].updated=new Date().toISOString();
          a.opponents[1].verdict='about even';a.opponents[2].verdict='slightly ahead';
          Object.assign(a,{overall:{key:'all',label:'All these opponents',opponents:3,games:300,rate:.47,low:.39,high:.55},
            played:3,of:3,tally:{ahead:1,even:1,behind:1,unsettled:0},updated:new Date().toISOString(),
            standard:{id:'sample:0123456789ab',size:24,tiers:['hard','medium']},is_standard:true});
          answers=[a];
          const node=await draw();
          const layout=node.querySelector('.gt-layout');
          same(layout.children.map(n=>n.getAttribute('class')),['gt-main','gt-side']);
          const head=node.querySelector('.gt-headline');
          assert.equal(layout.querySelector('.gt-main').children[0],head);
          assert(head.textContent.includes('Against 3 popular 60-card decks:'),head.textContent);
          assert(head.textContent.includes('47'));assert(head.textContent.includes('300 games'));
          assert.equal(head.querySelector('.gt-tally').textContent,'Ahead of 1 · even with 1 · behind 1');
          assert(head.querySelector('.fresh'));assert(!head.textContent.includes('tested so far'));
          const rows=node.querySelector('.gt-rows').querySelectorAll('.gt-row');
          assert(rows[0].textContent.includes('Behind · Aggro · Medium · 100 games'),rows[0].textContent);
          assert(rows[0].querySelector('.fresh'));assert(!rows[1].querySelector('.fresh'));
          assert(rows[2].textContent.includes('Slightly ahead'));
          assert(node.textContent.includes('The standard sample: the same 24 hard and medium opponents for every 60-card deck, so their results compare.'));
          assert(!buttonText(node,'Back to the standard sample'));
          // Some opponents still untested: the headline says how many so far.
          answers=[{...a,played:2,tally:{ahead:1,even:0,behind:1,unsettled:1}}];
          const again=await draw();
          assert(again.querySelector('.gt-headline').textContent.includes('2 of 3 opponents tested so far.'));
          assert.equal(again.querySelector('.gt-tally').textContent,'Ahead of 1 · behind 1 · not settled against 1');
        """)

    def test_a_run_before_any_games_shows_only_the_play_box(self):
        self.run_js("""
          answers=[base({status:'running',job:{status:'running',done:0,total:100,ahead:0,pairs:{}},budgets:{}})];
          const node=await draw();
          same(node.querySelector('.gt-layout').children.map(n=>n.getAttribute('class')),['gt-side']);
          assert(!node.querySelector('.gt-headline'));
        """)

    def test_another_sample_stays_in_the_address_and_back_to_the_standard_sample(self):
        self.run_js("""
          const std={id:'sample:ffffffffffff',size:24,tiers:['hard','medium']};
          const saved={...base().sample,saved:true};
          const other=base({standard:std,is_standard:false,sample:saved});
          answers=[other];
          open('#/deck?id=casual%2Ftest&v=target&tab=matchups&gsample=sample:0123456789ab');await settle();
          const asked=calls.filter(c=>c.startsWith('/api/gauntlet?'));
          assert(asked[0].includes('sample=sample%3A0123456789ab'),asked[0]);
          assert(!asked[0].includes('size='));
          assert(location.hash.includes('gsample=sample%3A0123456789ab'),location.hash);
          // The tabs' address keeps it (deckAddress), so a reload asks for the same sample.
          tab('overview').click();assert(location.hash.includes('gsample=sample%3A0123456789ab'),location.hash);
          tab('matchups').click();
          const node=main.querySelector('#sec-gauntlet');
          assert(node.textContent.includes('Not the standard sample.'));
          // Playing it plays the saved sample by its id.
          buttonText(node,'Play them').click();await settle();
          same(writes.at(-1).body,{id:'casual/test',version:'target',budget:'fixed:100',sample:'sample:0123456789ab',
            expected_card_sha:sha});
          // A choice draws again from the filters; that sample isn't saved, so the address doesn't keep its id.
          answers=[base({standard:std,is_standard:false,sample:{id:'sample:aaaaaaaaaaaa',size:24,
            filters:{colours:null,styles:['control'],tiers:['hard','medium']},decks:3,saved:false}})];
          buttonText(node,'Control').click();await settle();
          assert(!calls.at(-1).includes('sample='));assert(calls.at(-1).includes('styles=control'));
          assert(!location.hash.includes('gsample'),location.hash);
          // Once played (saved), it does.
          answers=[base({standard:std,is_standard:false,sample:{id:'sample:aaaaaaaaaaaa',size:24,
            filters:{colours:null,styles:['control'],tiers:['hard','medium']},decks:3,saved:true}})];
          buttonText(node,'Control').click();await settle();buttonText(node,'Control').click();await settle();
          assert(location.hash.includes('gsample=sample%3Aaaaaaaaaaaaa'),location.hash);
          // Back to the standard sample: no choices, so the server's standard sample, and none in the address.
          answers=[base({standard:{...std,id:'sample:0123456789ab'},is_standard:true})];
          buttonText(node,'Back to the standard sample').click();await settle();
          same([...new URLSearchParams(calls.at(-1).split('?')[1]).keys()],['id','version','profile']);
          assert(!location.hash.includes('gsample'),location.hash);
          assert(node.textContent.includes('The standard sample: the same 24'));
        """)

    def test_a_sample_that_isnt_saved_falls_back_to_the_standard_sample(self):
        self.run_js("""
          location.hash='#/deck?id=casual%2Ftest&v=target&tab=matchups&gsample=sample:0123456789ab';
          answers=[new ApiError(404,"There's no saved gauntlet sample with that id."),
            base({standard:{id:'sample:0123456789ab',size:24,tiers:['hard','medium']},is_standard:true})];
          const node=await draw();
          assert(calls[0].includes('sample=sample%3A0123456789ab'));assert(!calls[1].includes('sample='));
          assert(!node.textContent.includes("couldn't be loaded"));
          assert(!location.hash.includes('gsample'),location.hash);
          assert(node.textContent.includes("That sample isn't saved on the PC. The standard sample: the same 24"),
            node.textContent);
          // A bad id in the address isn't asked for at all.
          calls.length=0;location.hash='#/deck?id=casual%2Ftest&v=target&gsample=nonsense';
          answers=[base()];await draw();
          assert(!calls[0].includes('sample='));
        """)

    # ------------------------------------------------------------------ E3-S38: larger runs

    def test_commander_sizes_include_all_and_play_it(self):
        self.run_js("""
          const cmd=(extra={})=>base({format:'commander',default_size:20,options:{...base().options,
            sizes:[6,12,20,40,'all'],tiers:['core','upgraded','precon'],overnight_minutes:120},
            sample:{id:'sample:0123456789ab',size:20,filters:{colours:null,styles:null,tiers:['core','upgraded']},decks:20},
            ...extra});
          answers=[cmd()];
          const node=await draw();
          const sizes=node.querySelector('.gt-choices').querySelector('.segmented').querySelectorAll('button').map(b=>b.textContent);
          same(sizes,['6','12','20','40','All']);
          answers=[cmd({sample:{id:'sample:bbbbbbbbbbbb',size:169,all:true,
            filters:{colours:null,styles:null,tiers:['core','upgraded']},decks:169}})];
          buttonText(node,'All').click();await settle();
          assert(calls.at(-1).includes('size=all'),calls.at(-1));
          assert(node.querySelector('.gt-choices').querySelector('summary').textContent.startsWith('169 opponents'));
          assert(node.textContent.includes('All: every playable deck of the chosen tiers'));
          buttonText(node,'Play them').click();await settle();
          assert.equal(writes.at(-1).body.size,'all');
          assert.equal(gtChoiceOf(cmd()).size,20);
        """)

    def test_the_run_time_is_plain_and_says_when_its_an_overnight_run(self):
        self.run_js("""
          answers=[base({budgets:{'fixed:50':{games:50,new_games:1200,minutes:[20,40],overnight:false},
            'fixed:100':{games:100,new_games:2400,minutes:[180,300],overnight:true},
            'fixed:200':{games:200,new_games:0,minutes:[0,0],overnight:false}}})];
          const node=await draw();
          const time=()=>node.querySelector('.gt-time-part');
          assert.equal(time().querySelector('.gt-time').textContent,'This run: 3 opponents · 2,400 new games · about 3–5 hours.');
          const night=time().querySelector('.gt-overnight');
          assert(night);assert(night.getAttribute('class').split(' ').includes('note'));
          assert.equal(night.textContent,"That's an overnight run: start it in the evening and leave the PC on. Deck Lab keeps the PC awake while it plays.");
          assert(node.textContent.includes('About 100 games a deck, about 3–5 hours.'));
          // The run's time follows the budget chosen, without asking the server again.
          const before=calls.length;
          buttonText(node,'Quick look').click();
          assert.equal(calls.length,before);
          assert.equal(time().textContent,'This run: 3 opponents · 1,200 new games · about 20–40 minutes.');
          buttonText(node,'Precise').click();
          assert.equal(time().textContent,'Nothing new to play: every opponent has these games.');
          // Without the server's overnight flag, the minutes over overnight_minutes still say it.
          same(gtRunTime({budgets:{x:{games:1,new_games:5,minutes:[100,121]}},options:{overnight_minutes:120},
            sample:{decks:1}},'x').filter(Boolean).length,2);
          assert.equal(gtMinutesWords([0,0.5]),'under a minute');
          assert.equal(gtMinutesWords([60,60]),'about 60 minutes');
          assert.equal(gtMinutesWords([300,600]),'about 5–10 hours');
        """)

    def test_no_run_time_when_runs_arent_allowed(self):
        self.run_js("""
          mayStartRuns=()=>false;
          answers=[base({budgets:{'fixed:100':{games:100,new_games:2400,minutes:[180,300],overnight:true}}})];
          const node=await draw();
          assert.equal(node.querySelector('.gt-time-part').hidden,true);
        """)

    # ------------------------------------------------------------------ E3-S34: kept through a change

    def test_a_changed_list_shows_its_figure_before_the_change_muted_and_plays_only_when_asked(self):
        self.run_js(DAY + """
          const std={id:'sample:0123456789ab',size:24,tiers:['hard','medium']};
          answers=[base({standard:std,is_standard:true,before:{rate:.41,low:.33,high:.49,played:3,of:3,games:300,
            updated:day},compare:null,older:null})];
          const node=await draw();
          const before=node.querySelector('.gt-stale').querySelector('.gt-before');
          assert.equal(before.querySelector('p').textContent,'The list changed since its last test (2 Nov). Before: 41% (33–49).');
          const bar=before.querySelector('.range-bar');assert(bar.getAttribute('class').split(' ').includes('is-muted'));
          assert(!bar.querySelector('.range-band'));
          assert(hasClass(before.querySelector('.fresh'),'is-stale'));
          assert(!node.textContent.includes('No games against popular decks yet.'));
          assert(node.textContent.includes("Play 3 popular decks to test this list with today's Forge."));
          // Figures in ink: no strong or weak colours.
          assert(!node.querySelector('.flag'));assert(!node.querySelector('.is-good'));
          // Nothing plays by itself; Play is the usual button.
          flushTimers();await settle();assert.equal(writes.length,0);
          buttonText(node,'Play them').click();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0].path,'/api/gauntlet/run');
        """)

    def test_after_a_retest_both_lists_over_the_same_opponents_and_moved_only_when_set(self):
        self.run_js(DAY + """
          const a=played();
          Object.assign(a,{overall:{key:'all',opponents:3,games:300,rate:.47,low:.39,high:.55},played:3,of:3,
            tally:{ahead:1,even:1,behind:1,unsettled:0},updated:new Date().toISOString(),is_standard:true,
            standard:{id:'sample:0123456789ab',size:24,tiers:['hard','medium']},
            before:{rate:.41,low:.33,high:.49,played:3,of:3,games:300,updated:day},
            compare:{same:3,before:{rate:.41,low:.33,high:.49},now:{rate:.47,low:.39,high:.55},moved:1}});
          a.opponents[0].before={rate:.6,low:.52,high:.68};a.opponents[0].moved=true;
          a.opponents[1].before={rate:.48,low:.4,high:.56};a.opponents[1].moved=false;
          answers=[a];
          const node=await draw();
          const results=node.querySelector('.gt-main');
          const line=results.querySelector('.gt-before');
          assert.equal(results.children[1],line);
          assert.equal(line.querySelector('p').textContent,'Before this change 41% (33–49) · Now 47% (39–55), same 3 opponents.');
          assert(line.textContent.includes("1 opponent moved: the two ranges don't overlap."));
          assert(!/significan|better|worse/i.test(line.textContent),line.textContent);
          const rows=node.querySelector('.gt-rows').querySelectorAll('.gt-row');
          assert(rows[0].textContent.includes('Moved'));assert(rows[0].textContent.includes('Before: 60% (52–68)'));
          assert(!rows[1].textContent.includes('Moved'));assert(rows[1].textContent.includes('Before: 48% (40–56)'));
          assert(!rows[2].textContent.includes('Before:'));
          assert.equal(rows[0].querySelector('.status-info').textContent,'Moved');
          // Fewer opponents compared than tested: the sentence says how many.
          answers=[{...a,played:2,compare:{...a.compare,same:2,moved:0}}];
          const again=await draw();
          assert(again.textContent.includes('same 2 opponents.'));assert(again.textContent.includes('2 of 3 opponents tested so far.'));
          assert(!again.querySelector('.gt-before').textContent.includes('moved'));
        """)

    def test_older_results_are_said_plainly_for_each_reason(self):
        self.run_js(DAY + """
          const older=(reason,extra={})=>base({is_standard:true,before:null,compare:null,
            older:{reason,opponents:18,of:20,updated:day,overall:{rate:.41,low:.33,high:.49},...extra}});
          answers=[older('forge')];let node=await draw();
          let part=node.querySelector('.gt-older');
          assert.equal(part.querySelectorAll('p')[0].textContent,"Results from an older Forge aren't shown.");
          assert.equal(part.querySelectorAll('p')[1].textContent,'With the older Forge: 41% (33–49), 18 of 20 opponents (2 Nov).');
          assert(hasClass(part.querySelector('.range-bar'),'is-muted'));
          answers=[older('forge',{overall:null})];node=await draw();
          assert.equal(node.querySelector('.gt-older').textContent,"Results from an older Forge aren't shown.");
          answers=[older('settings',{overall:null})];node=await draw();
          assert(node.textContent.includes("Results played with other Forge settings aren't shown."));
          answers=[older('pilot',{overall:null})];node=await draw();
          assert(node.textContent.includes("Results played with another AI pilot aren't shown."));
          answers=[older('catalogue',{opponents:3})];node=await draw();
          assert.equal(node.querySelector('.gt-older').textContent,
            "3 opponents' lists changed when popular decks were rebuilt, so their results aren't shown.");
          answers=[older('unknown',{opponents:null,overall:null})];node=await draw();
          assert.equal(node.querySelector('.gt-older').textContent,
            "Forge's version on the PC can't be confirmed now, so older results can't be matched.");
          // An earlier list's older results (the list and Forge both changed) say the list changed first.
          answers=[older('forge',{earlier:true})];node=await draw();
          part=node.querySelector('.gt-older');
          assert.equal(part.querySelectorAll('p')[0].textContent,
            "The list changed since its last test. Results from an older Forge aren't shown.");
          assert.equal(part.querySelectorAll('p')[1].textContent,
            'Before the change, with the older Forge: 41% (33–49), 18 of 20 opponents (2 Nov).');
          assert.equal(writes.length,0);
          // With games for this list, the sentence is a small note under the headline, without the old figure.
          const a=played();
          Object.assign(a,{overall:{key:'all',opponents:3,games:300,rate:.47,low:.39,high:.55},played:3,of:3,
            older:{reason:'forge',opponents:3,of:3,updated:null,overall:{rate:.41,low:.33,high:.49}}});
          answers=[a];node=await draw();
          const note=node.querySelector('.gt-main').querySelector('.gt-older');
          assert.equal(note.textContent,"Results from an older Forge aren't shown.");
          assert(!node.textContent.includes('With the older Forge'));
        """)

    def test_no_before_fields_draw_nothing_new(self):
        self.run_js(DAY + """
          answers=[played()];const node=await draw();
          assert(!node.querySelector('.gt-before'));assert(!node.textContent.includes('Moved'));
          assert(!node.textContent.includes('Before:'));
          assert.equal(gtBeforeLine({}),null);assert.equal(gtOlderLine({older:{reason:'nonsense'}}),null);
        """)

    def test_the_part_says_when_the_popular_decks_list_was_built(self):
        self.run_js(DAY + """
          const year=new Date().getFullYear();
          answers=[played()];let node=await draw();
          assert(!node.querySelector('.gt-built'));           // the fixture's catalogue has no build time
          clear(main);
          answers=[{...played(),catalogue:{playable:3,built:day,sha:'1a2b3c4d',age_days:3,old:false}}];
          node=await draw();
          let line=node.querySelector('.gt-built');
          assert.equal(line.textContent,`Popular decks list built 2 November ${year} (1a2b3c4d).`);
          assert(hasClass(line,'gt-small'));
          // Before any games too, and with its age once it's old.
          clear(main);
          answers=[base({catalogue:{playable:3,built:day,sha:'1a2b3c4d',age_days:200,old:true}})];
          node=await draw();
          assert.equal(node.querySelector('.gt-built').textContent,
            `Popular decks list built 2 November ${year} (1a2b3c4d), 6 months ago.`);
          // No catalogue: the build command only.
          clear(main);answers=[base({catalogue:null})];node=await draw();
          assert(!node.querySelector('.gt-built'));
        """)
