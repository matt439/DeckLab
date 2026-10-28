"""Current-field exclusion notes through real renderers over an isolated Node DOM.

Run with python scripts/test_fixtures.py decklab.tests.test_field_exclusion_counts_ui.
No live server, network, configuration, database or simulation is used.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  clear(main);editor=null;state.profile={id:'matt',name:'Matt'};state.may=null;
  const calls=[],writes=[];
  api=async path=>{calls.push(path);throw new Error('Unexpected read');};
  apiWrite=async(...args)=>{writes.push(args);throw new Error('Unexpected write');};
  const rated=(extra={})=>({value:.6,low:.4,high:.8,rank:2,rank_low:1,rank_high:3,of:5,...extra});
  const fieldAnswer=(extra={})=>({format:'Constructed',deck:{id:'casual/test',version:'target'},
    average:null,opponents:[],rating:rated(),...extra});
  const rankingAnswer=(extra={})=>({format:'Constructed',rows:[],groups:[],notes:[],error:null,...extra});
  const unknown='The number of lists manually excluded from the current field is unavailable.';
  const invalidCounts=[undefined,null,false,true,'0','1',NaN,Infinity,-Infinity,-1,.5,1001,{},[],
    '<img src=x onerror=secret>',{valueOf(){throw new Error('Must not coerce');},toString(){return 'SECRET';}}];
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class FieldExclusionCountsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_ranked_field_has_separate_zero_singular_plural_and_boundary_notes(self):
        self.run_js("""
          for(const count of [0,1,3,1000]){
            const node=fvHeadline(fieldAnswer({rating:rated({manual_excluded:count})}));
            assert.equal(node.querySelector('.fv-rating').textContent,
              'Ranks 2nd of 5 Constructed decks (somewhere from 1st to 3rd).');
            assert.equal(node.querySelector('.fv-manual-excluded').textContent,
              `${count} ${count===1?'list':'lists'} manually excluded from the current field.`);
            assert.equal(node.querySelectorAll('.fv-manual-excluded').length,1);
          }
          assert.equal(calls.length,0);assert.equal(writes.length,0);
        """)

    def test_field_unknown_and_invalid_values_never_coerce_or_publish_raw_values(self):
        self.run_js("""
          for(const count of invalidCounts){
            const node=fvHeadline(fieldAnswer({rating:rated({manual_excluded:count})}));
            assert.equal(node.querySelector('.fv-manual-excluded').textContent,unknown);
            assert(!node.textContent.includes('SECRET'));assert.equal(node.querySelectorAll('img').length,0);
          }
          assert.equal(calls.length,0);assert.equal(writes.length,0);
        """)

    def test_field_with_no_actual_rating_has_no_note_even_if_other_counts_are_present(self):
        self.run_js("""
          for(const rating of [undefined,null,{}, {value:null,manual_excluded:3}, {manual_excluded:0}]){
            const node=fvHeadline(fieldAnswer({rating,manual_excluded:99,
              coverage:{manual_excluded:99},membership:{counts:{manual_excluded:99}}}));
            assert.equal(node.querySelectorAll('.fv-manual-excluded').length,0);
            assert.equal(node.querySelectorAll('.fv-rating').length,0);
            assert(!node.textContent.includes('manually excluded'));
          }
        """)

    def test_field_average_coverage_and_rank_denominators_remain_independent(self):
        self.run_js("""
          const node=fvHeadline(fieldAnswer({average:{value:.6,low:.5,high:.7,partial:true,counted:2,of:4},
            coverage:{with_floor:2,of:4},rating:rated({manual_excluded:7}),
            opponents:[{games:200},{games:100},{games:50,not_meaningful:true}]}));
          assert(node.textContent.includes('Based on 2 of 4 decks; play the field to fill it in.'));
          assert(node.textContent.includes('Ranks 2nd of 5 Constructed decks'));
          assert(node.textContent.includes('7 lists manually excluded from the current field.'));
          assert.equal(node.querySelector('.wr').getAttribute('aria-label').includes('300 games'),true);
          assert.equal(node.querySelector('.fv-manual-excluded').querySelectorAll('.wr').length,0);
        """)

    def test_field_uses_its_nested_rating_count_and_dashboard_uses_its_outer_count(self):
        self.run_js("""
          const field=fvHeadline(fieldAnswer({manual_excluded:12,rating:rated({manual_excluded:4})}));
          assert.equal(field.querySelector('.fv-manual-excluded').textContent,
            '4 lists manually excluded from the current field.');
          const host=el('div');muRankingContent(host,{answer:rankingAnswer({manual_excluded:12,
            rating:rated({manual_excluded:4})})},'Constructed');
          assert.equal(host.querySelector('.mu-manual-excluded').textContent,
            '12 lists manually excluded from the current field.');
        """)

    def test_dashboard_notes_do_not_change_group_ranks_games_or_exclusion_reasons(self):
        self.run_js("""
          const rows=[{id:'casual/a',title:'Alpha',kind:'casual',version:'target',versions:['target'],
            in_field:true,group:'g',rating:rated({rank:1,of:2,rank_low:1,rank_high:2}),games:400,reasons:[]},
            {id:'casual/b',title:'Beta',kind:'casual',version:'target',versions:['target'],
              in_field:false,rating:null,exclusion:'Left out by hand.',reasons:['Left out by hand.']}];
          for(const count of [0,1,5,1000]){
            const host=el('div');muRankingContent(host,{answer:rankingAnswer({rows,
              groups:[{id:'g',lists:2}],manual_excluded:count})},'Constructed');
            assert.equal(host.querySelectorAll('.mu-manual-excluded').length,1);
            assert.equal(host.querySelector('.mu-manual-excluded').textContent,
              `${count} ${count===1?'list':'lists'} manually excluded from the current field.`);
            assert(host.textContent.includes('Rank 1 of 2'));assert(host.textContent.includes('400 games'));
            assert(host.textContent.includes('average current field list in the same group'));
            const groups=host.querySelectorAll('.mu-ranking-group');
            assert.equal(groups.length,2);assert(groups[1].textContent.includes('Outside the field'));
            assert.equal(groups[1].textContent.split('Left out by hand.').length-1,1);
            assert(groups.every(group=>!group.textContent.includes('manually excluded')));
          }
          assert.equal(calls.length,0);assert.equal(writes.length,0);
        """)

    def test_dashboard_unknown_and_invalid_counts_use_only_fixed_unavailable_words(self):
        self.run_js("""
          for(const count of invalidCounts){
            const host=el('div');muRankingContent(host,{answer:rankingAnswer({manual_excluded:count})},'Commander');
            assert.equal(host.querySelector('.mu-manual-excluded').textContent,unknown);
            assert(!host.textContent.includes('SECRET'));assert.equal(host.querySelectorAll('img').length,0);
            assert(host.textContent.includes('There are no current lists of this format to rank.'));
          }
        """)

    def test_dashboard_loading_without_an_answer_does_not_invent_a_count(self):
        self.run_js("""
          const host=el('div');muRankingContent(host,{answer:null,loading:true},'Constructed');
          assert(host.textContent.includes('Loading rankings'));assert(!host.querySelector('.mu-manual-excluded'));
          muRankingContent(host,{answer:rankingAnswer({manual_excluded:1}),loading:true,error:'Read failed'},'Constructed');
          assert(host.textContent.includes('saved display below may be out of date'));
          assert.equal(host.querySelectorAll('.mu-manual-excluded').length,1);
          assert(host.textContent.includes('1 list manually excluded from the current field.'));
        """)

    def test_existing_rankings_fetch_supplies_the_note_without_an_extra_read_or_write(self):
        self.run_js("""
          const host=el('div');main.append(host);const data={running:[],results:[]};
          const library={halves:[],decks:[]};
          const view={mode:'rankings',format:'Constructed',deck:null,token:routeToken,
            profile:state.profile.id,rankings:new Map()};
          api=async path=>{calls.push(path);return rankingAnswer({manual_excluded:0});};
          drawHome(host,data,library,view);await settle();
          same(calls,['/api/rankings?format=Constructed']);assert.equal(writes.length,0);
          assert(host.textContent.includes('0 lists manually excluded from the current field.'));
        """)

    def test_existing_field_fetch_supplies_the_note_without_loading_membership(self):
        self.run_js("""
          const data=makePage();location.hash=deckHref(data.summary.id)+'&tab=matchups';
          deckScreen={data,view:{tab:'matchups'}};
          api=async path=>{calls.push(path);return fieldAnswer({rating:rated({manual_excluded:1}),
            opponents:[{id:'casual/other',title:'Other',games:200,rate:{value:.6,low:.4,high:.8}}],
            forge:{ready:false}});};
          const section=fieldSection(data);main.append(section);await settle();
          same(calls,['/api/field?id=casual%2Ftest&version=target&profile=matt']);
          assert(section.textContent.includes('1 list manually excluded from the current field.'),section.textContent);
          assert(!section.querySelector('.fv-membership').open);assert.equal(writes.length,0);
        """)
