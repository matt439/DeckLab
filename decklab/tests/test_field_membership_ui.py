"""Current field membership with real UI functions, disposable DOM and deterministic read-only answers."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  routeToken=9;
  const calls=[], writes=[];
  apiWrite=async (...args)=>{writes.push(args);throw new Error('Unexpected write');};
  const memberRow=(id,title,version='target',reason='default',in_field=true,opponent=true)=>
    ({id,title,version,reason,in_field,opponent,kind:'casual',card_sha:in_field?'sha-'+id:null});
  const answer=(extra={})=>({deck:{id:'casual/test',version:'target',card_sha:'base-sha'},format:'Constructed',
    rows:[memberRow('casual/test','Test Deck','target','default',true,false),
      memberRow('casual/other','Other Deck'),memberRow('casual/manual','Manual Deck','owned','configured_add'),
      memberRow('casual/removed','Removed Deck','target','configured_remove',false,false),
      memberRow('casual/other','Other Deck','owned','other_version',false,false)],
    counts:{included:3,opponents:2,manual_excluded:1},complete:true,error:null,...extra});
  api=async path=>{calls.push(path);return answer();};
  const mount=(data=makePage())=>{
    clear(main);location.hash=deckHref(data.summary.id,data.version)+'&tab=matchups';
    deckScreen={data,view:{tab:'matchups'}};
    const details=fieldMembership(data);main.append(details);return details;
  };
  const expand=details=>{details.open=true;details.fire('toggle');};
  const refresh=details=>details.querySelector('[data-field-membership-refresh]');
  const largeAnswer=(included=70,excluded=45)=>answer({
    rows:Array.from({length:included+excluded},(_,i)=>memberRow('casual/x'+i,'Deck '+i,'target',
      i<included?'default':'not_selected',i<included,i<included)),
    counts:{included,opponents:included,manual_excluded:0}});
  const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
  const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});
    return {promise,resolve,reject};};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class FieldMembershipUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_lazy_read_shows_current_included_excluded_versions_and_canonical_links(self):
        self.run_js("""
          const details=mount();assert.equal(calls.length,0);expand(details);await settle();
          same(calls,['/api/field/membership?id=casual%2Ftest&version=target']);
          assert(details.textContent.includes('3 lists included; 2 opponents'));
          assert(details.textContent.includes('1 list left out by hand'));
          assert(details.textContent.includes('Included (3)'));assert(details.textContent.includes('Left out (2)'));
          assert(details.textContent.includes('Current membership only'));
          assert(details.textContent.includes('Added to the field by hand'));
          assert(details.textContent.includes('Left out of the field by hand'));
          assert(details.textContent.includes("The field rules choose this deck's other version"));
          const links=details.querySelectorAll('a');
          assert(links.some(link=>link.getAttribute('href')===deckHref('casual/manual','owned')
            &&link.textContent.includes('Play-now list')));
          assert(links.some(link=>link.getAttribute('href')===deckHref('casual/other','target')
            &&link.textContent.includes('Planned list')));
          assert(details.textContent.includes('This deck is included, but never plays itself'));
          assert(!details.textContent.includes('sha-'));assert.equal(writes.length,0);
        """)

    def test_base_other_version_is_a_member_without_becoming_its_own_opponent(self):
        self.run_js("""
          const data=makePage();data.version='owned';
          api=async path=>{calls.push(path);return answer({deck:{id:'casual/test',version:'owned',card_sha:'new'},
            rows:[memberRow('casual/test','Test Deck','target','default',true,false),
              memberRow('casual/test','Test Deck','owned','other_version',false,false)],
            counts:{included:1,opponents:0,manual_excluded:0}});};
          const details=mount(data);expand(details);await settle();
          assert(calls[0].endsWith('version=owned'));
          assert(details.textContent.includes('1 list included; 0 opponents for this play-now list'));
          assert(details.textContent.includes('This deck is included, but never plays itself'));
          assert(details.textContent.includes("This is the list you're viewing"));
          assert.equal(details.querySelectorAll('a').length,2);
        """)

    def test_base_excluded_does_not_reduce_opponents_or_collapse_same_sha_lists(self):
        self.run_js("""
          const rows=[memberRow('casual/test','Test Deck','target','configured_remove',false,false),
            memberRow('casual/a','Duplicate'),memberRow('casual/b','Duplicate')];rows[1].card_sha=rows[2].card_sha='same';
          api=async()=>answer({rows,counts:{included:2,opponents:2,manual_excluded:1}});
          const details=mount();expand(details);await settle();
          assert(details.textContent.includes('2 lists included; 2 opponents'));
          same(details.querySelectorAll('a').map(link=>link.getAttribute('href')),
            [deckHref('casual/a','target'),deckHref('casual/b','target'),deckHref('casual/test','target')]);
        """)

    def test_real_field_section_keeps_panel_in_no_opponent_and_no_game_states(self):
        self.run_js("""
          let ctx;const original=fvDraw;fvDraw=(owner,a)=>{ctx=owner;original(owner,a);};
          api=async path=>{calls.push(path);return path.startsWith('/api/field/membership')?answer():
            {format:'Constructed',opponents:[]};};
          const data=makePage();location.hash=deckHref(data.summary.id)+'&tab=matchups';
          deckScreen={data,view:{tab:'matchups'}};
          const section=fieldSection(data);main.append(section);await settle();
          const details=section.querySelector('.fv-membership');assert(details);
          assert(section.textContent.includes("There's no other Constructed deck"));
          assert.equal(calls.length,1);expand(details);await settle();
          const button=refresh(details);button.focus();
          fvDraw(ctx,{format:'Constructed',opponents:[{id:'casual/other',title:'Other'}],forge:{ready:false}});
          assert(section.textContent.includes('No games against the field yet'));
          assert.equal(section.querySelector('.fv-membership'),details);assert(details.open);
          assert.equal(document.activeElement,button);assert.equal(calls.length,2);
          assert.equal(writes.length,0);
        """)

    def test_empty_visible_membership_and_member_page_need_no_edit_controls(self):
        self.run_js("""
          state.profile={id:'user2',role:'member',space:'user2'};
          const data=makePage();data.summary.id='user2/casual/test';
          api=async()=>answer({deck:{id:data.summary.id,version:'target',card_sha:'member'},rows:[],
            counts:{included:0,opponents:0,manual_excluded:0}});
          const details=mount(data);expand(details);await settle();
          assert(details.textContent.includes('No lists are included'));
          assert(details.textContent.includes('No visible lists are left out'));
          same(details.querySelectorAll('button').map(b=>b.textContent),['Refresh membership']);
          assert.equal(writes.length,0);
        """)

    def test_reason_copy_uses_only_static_codes_and_text_nodes(self):
        self.run_js("""
          const reasons=['unreadable','beginner_half','pairing','not_selected','product_not_selected','product_not_intact',
            'product_status','product_status_missing','unknown_private_note','constructor'];
          const rows=reasons.map((reason,i)=>memberRow('casual/x'+i,i===0?'<img onerror=secret>':'Deck '+i,
            'target',reason,false,false));
          api=async()=>answer({rows,counts:{included:0,opponents:0,manual_excluded:0},
            notes:['RAW PRIVATE NOTE'],error_detail:'RAW CONFIG'});
          const details=mount();expand(details);await settle();
          assert(details.textContent.includes('<img onerror=secret>'));
          assert.equal(details.querySelectorAll('img').length,0);
          assert(details.textContent.includes("This list couldn't be read"));
          assert(details.textContent.includes('Not selected for this field'));
          assert(details.textContent.includes('Not recorded as kept intact'));
          assert(!details.textContent.includes('function Object'));
          for(const forbidden of ['unknown_private_note','RAW PRIVATE NOTE','RAW CONFIG'])
            assert(!details.textContent.includes(forbidden));
        """)

    def test_failed_fetch_and_retry_keep_disclosure_control_and_focus(self):
        self.run_js("""
          let fail=true;api=async path=>{calls.push(path);if(fail)throw new Error('SECRET database/config');return answer();};
          const details=mount(),button=refresh(details);expand(details);await settle();
          assert(details.textContent.includes("Who's in the field couldn't be loaded. Try again."));
          assert(!details.textContent.includes('SECRET'));assert.equal(details.querySelectorAll('a').length,0);
          assert.equal(button.textContent,'Try again');button.focus();fail=false;button.click();await settle();
          assert.equal(refresh(details),button);assert.equal(document.activeElement,button);assert(details.open);
          assert.equal(button.textContent,'Refresh membership');assert.equal(calls.length,2);
        """)

    def test_partial_capped_malformed_and_wrong_identity_answers_show_no_counts_or_rows(self):
        self.run_js("""
          const bad=[answer({complete:false,error:'SECRET failure'}),answer({counts:null}),
            answer({deck:{id:'casual/other',version:'target'}}),answer({deck:{id:'casual/test',version:'owned'}}),
            answer({rows:Array.from({length:1001},(_,i)=>memberRow('casual/x'+i,'SECRET'))}),
            answer({counts:{included:99,opponents:2,manual_excluded:1}}),
            answer({counts:{included:3,opponents:-1,manual_excluded:1}}),
            answer({counts:{included:3,opponents:2,manual_excluded:0.5}}),
            answer({rows:[memberRow('casual/a','SECRET'),memberRow('casual/a','SECRET')]}),
            answer({rows:[memberRow('casual/a','SECRET','target','other_version',false,true)]}),
            answer({rows:[memberRow('casual/test','SECRET')],counts:{included:1,opponents:1,manual_excluded:0}}),
            answer({rows:[{...memberRow('casual/a','SECRET'),version:'other'}]})];
          for(const value of bad){api=async()=>value;const details=mount();expand(details);await settle();
            assert(details.textContent.includes("couldn't be loaded"));
            assert(!details.textContent.includes('SECRET'));assert(!details.textContent.includes('lists included'));
            assert.equal(details.querySelectorAll('a').length,0);}
        """)

    def test_pending_duplicate_refresh_and_close_do_not_start_extra_reads_or_reopen(self):
        self.run_js("""
          const pending=deferred();api=path=>{calls.push(path);return pending.promise;};
          const details=mount();expand(details);refresh(details).click();details.fire('toggle');
          assert.equal(calls.length,1);assert(refresh(details).disabled);
          details.open=false;details.fire('toggle');pending.resolve(answer());await settle();
          assert.equal(details.open,false);assert(!refresh(details).disabled);
          expand(details);await settle();assert.equal(calls.length,1);assert.equal(writes.length,0);
          details.open=false;details.fire('toggle');refresh(details).click();await settle();assert.equal(calls.length,1);
        """)

    def test_refresh_replaces_old_rows_without_losing_summary_expansion_or_focus(self):
        self.run_js("""
          const details=mount();expand(details);await settle();
          const button=refresh(details),summary=details.querySelector('summary');button.focus();
          const pending=deferred();api=path=>{calls.push(path);return pending.promise;};button.click();
          assert.equal(details.querySelectorAll('a').length,0);assert(details.textContent.includes('Loading current'));
          pending.resolve(answer({rows:[memberRow('casual/new','New Deck')],counts:{included:1,opponents:1,manual_excluded:0}}));
          await settle();assert(details.open);assert.equal(details.querySelector('summary'),summary);
          assert.equal(document.activeElement,button);assert(details.textContent.includes('New Deck'));
          assert(!details.textContent.includes('Removed Deck'));assert.equal(writes.length,0);
        """)

    def test_late_success_and_failure_cannot_cross_page_profile_route_or_list_identity(self):
        self.run_js("""
          for(const failure of [false,true])for(const change of ['profile','same-id-profile','profile-id','route',
            'hash-id','hash-version','screen','view','data','summary','version','detached']){
            state.profile={id:'matt'};const pending=deferred();api=path=>{calls.push(path);return pending.promise;};
            const details=mount();expand(details);const before=details.textContent;
            if(change==='profile')state.profile={id:'user1'};
            if(change==='same-id-profile')state.profile={id:'matt'};
            if(change==='profile-id')state.profile.id='user1';
            if(change==='route')routeToken++;
            if(change==='hash-id')location.hash=deckHref('casual/other');
            if(change==='hash-version')location.hash=deckHref('casual/test','owned');
            if(change==='screen')deckScreen={...deckScreen};
            if(change==='view')deckScreen.view={...deckScreen.view};
            if(change==='data')deckScreen.data={...deckScreen.data};
            if(change==='summary')deckScreen.data.summary={...deckScreen.data.summary};
            if(change==='version')deckScreen.data.version='owned';
            if(change==='detached')clear(main);
            if(failure)pending.reject(new Error('SECRET'));else pending.resolve(answer());
            await settle();assert.equal(details.textContent,before,change+' '+failure);
            const reads=calls.length;refresh(details).disabled=false;refresh(details).click();
            await settle();assert.equal(calls.length,reads,'stale retry '+change);
          }
        """)

    def test_detached_refresh_control_rejects_pending_answer_and_stale_click(self):
        self.run_js("""
          const pending=deferred();api=path=>{calls.push(path);return pending.promise;};
          const details=mount(),button=refresh(details);expand(details);const before=details.textContent;
          button.remove();pending.resolve(answer());await settle();
          assert.equal(details.querySelectorAll('a').length,0);assert(!details.textContent.includes('lists included'));
          button.disabled=false;button.click();await settle();assert.equal(calls.length,1);
        """)

    def test_display_string_bounds_reject_whole_answer_and_keep_legacy_id_families(self):
        self.run_js("""
          const accepted=[memberRow('casual/'+ 'a'.repeat(505),'a'.repeat(200)),
            memberRow('user2/commander/Old_Name','😀'.repeat(200)),
            memberRow('product/stem','Whole product'),memberRow('product/stem/half','Subdeck'),
            memberRow('pairing/half-one+half-two','Pairing'),
            memberRow('casual/legacy','Reason boundary','target','a'.repeat(64))];
          api=async()=>answer({rows:accepted,counts:{included:6,opponents:6,manual_excluded:0}});
          let details=mount();expand(details);await settle();assert.equal(details.querySelectorAll('a').length,6);
          assert(details.textContent.includes('😀'.repeat(200)));
          const invalid=[memberRow('casual/'+ 'a'.repeat(506),'SECRET'),
            memberRow('casual/a','SECRET'+'a'.repeat(195)),memberRow('casual/a','😀'.repeat(201)),
            memberRow('casual/a','SECRET','target','a'.repeat(65)),
            memberRow('casual/a','SECRET','target','invalid-reason'),
            memberRow('casual/a','SECRET','target','default'+String.fromCharCode(10)),
            memberRow('casual/a'+String.fromCharCode(10)+'secret','SECRET'),memberRow('casual/a/b','SECRET'),
            memberRow('pairing/a+b+c','SECRET'),memberRow('unknown/type/a','SECRET'),
            memberRow('product/../a','SECRET')];
          for(const bad of invalid){api=async()=>answer({rows:[bad],counts:{included:1,opponents:1,manual_excluded:0}});
            details=mount();expand(details);await settle();assert(details.textContent.includes("couldn't be loaded"));
            assert.equal(details.querySelectorAll('a').length,0);assert(!details.textContent.includes('SECRET'));}
        """)

    def test_large_membership_paints_forty_rows_and_expands_locally_without_replacing_focus(self):
        self.run_js("""
          api=async path=>{calls.push(path);return largeAnswer(700,300);};
          const details=mount();expand(details);await settle();
          const groups=details.querySelectorAll('.fv-membership-group');
          const included=groups[0],excluded=groups[1],more=included.querySelector('button');
          const first=included.querySelector('a'),summary=details.querySelector('summary'),refreshButton=refresh(details);
          assert.equal(details.querySelectorAll('a').length,40);assert.equal(details.querySelectorAll('li').length,40);
          assert(included.textContent.includes('Showing 20 of 700 included lists'));
          assert(excluded.textContent.includes('Showing 20 of 300 left out lists'));
          assert(details.textContent.includes('700 lists included; 700 opponents'));
          more.focus();more.click();assert.equal(included.querySelectorAll('a').length,40);
          assert.equal(details.querySelectorAll('a').length,60);assert.equal(document.activeElement,more);
          assert.equal(included.querySelector('a'),first);assert.equal(details.querySelector('summary'),summary);
          assert.equal(refresh(details),refreshButton);assert(details.open);
          for(let i=0;i<40;i++)more.click();
          assert.equal(included.querySelectorAll('a').length,700);
          assert(included.textContent.includes('Showing 700 of 700 included lists'));
          assert.equal(more.getAttribute('aria-disabled'),'true');assert.equal(document.activeElement,more);
          more.click();assert.equal(included.querySelectorAll('a').length,700);
          const otherMore=excluded.querySelector('button');otherMore.focus();otherMore.click();
          assert.equal(excluded.querySelectorAll('a').length,40);assert.equal(document.activeElement,otherMore);
          assert.equal(calls.length,1);assert.equal(writes.length,0);
        """)

    def test_expansion_rejects_closed_disclosure_dialog_menu_and_detached_group(self):
        self.run_js("""
          api=async path=>{calls.push(path);return largeAnswer();};
          const details=mount();expand(details);await settle();
          const group=details.querySelector('.fv-membership-group'),more=group.querySelector('button');
          const count=()=>group.querySelectorAll('a').length;
          details.open=false;more.click();assert.equal(count(),20);details.open=true;
          const hiddenPanel=el('div',{hidden:true});main.append(hiddenPanel);hiddenPanel.append(details);
          more.click();assert.equal(count(),20);main.append(details);hiddenPanel.remove();
          const rows=details.querySelector('.fv-membership-rows');main.append(rows);
          more.click();refresh(details).click();assert.equal(count(),20);assert.equal(calls.length,1);
          details.querySelector('.fv-membership-body').append(rows);
          const dialog=el('dialog',{open:true});document.body.append(dialog);more.click();assert.equal(count(),20);
          dialog.remove();const oldMenu=keyboardMenuOpen;keyboardMenuOpen=()=>true;more.click();assert.equal(count(),20);
          keyboardMenuOpen=oldMenu;group.remove();more.click();assert.equal(count(),20);
          details.querySelector('.fv-membership-rows').append(group);more.focus();more.click();assert.equal(count(),40);
          assert.equal(document.activeElement,more);assert.equal(calls.length,1);assert.equal(writes.length,0);
        """)

    def test_moved_rows_or_status_host_reject_late_membership_answers(self):
        self.run_js("""
          for(const selector of ['.fv-membership-rows','[role=status]']){
            const pending=deferred();api=path=>{calls.push(path);return pending.promise;};
            const details=mount();expand(details);const rows=details.querySelector('.fv-membership-rows');
            const status=details.querySelector('[role=status]'),before=status.textContent;
            main.append(details.querySelector(selector));pending.resolve(largeAnswer());await settle();
            assert.equal(rows.querySelectorAll('a').length,0);assert.equal(status.textContent,before);
          }
        """)

    def test_retired_expansion_controls_cannot_repopulate_pending_failed_or_fresh_refresh(self):
        self.run_js("""
          api=async path=>{calls.push(path);return largeAnswer();};
          const details=mount();expand(details);await settle();
          const oldGroup=details.querySelector('.fv-membership-group'),oldMore=oldGroup.querySelector('button');
          const rows=details.querySelector('.fv-membership-rows'),pending=deferred();
          api=path=>{calls.push(path);return pending.promise;};refresh(details).click();
          rows.append(oldGroup);oldMore.click();assert.equal(oldGroup.querySelectorAll('a').length,20);
          pending.reject(new Error('SECRET'));await settle();oldMore.click();
          assert.equal(oldGroup.querySelectorAll('a').length,20);
          api=async path=>{calls.push(path);return largeAnswer(55,0);};refresh(details).click();await settle();
          rows.append(oldGroup);oldMore.click();assert.equal(oldGroup.querySelectorAll('a').length,20);
          const fresh=details.querySelector('.fv-membership-group').querySelector('button');fresh.focus();fresh.click();
          assert.equal(details.querySelector('.fv-membership-group').querySelectorAll('a').length,40);
          assert.equal(document.activeElement,fresh);assert.equal(calls.length,3);assert.equal(writes.length,0);
        """)

    def test_expansion_controls_cannot_cross_profile_route_view_or_data_changes(self):
        self.run_js("""
          for(const change of ['profile','same-id-profile','profile-id','route','hash','screen','view','data','summary','version']){
            state.profile={id:'matt'};api=async path=>{calls.push(path);return largeAnswer();};
            const details=mount();expand(details);await settle();
            const group=details.querySelector('.fv-membership-group'),more=group.querySelector('button'),reads=calls.length;
            if(change==='profile')state.profile={id:'user1'};
            if(change==='same-id-profile')state.profile={id:'matt'};
            if(change==='profile-id')state.profile.id='user1';
            if(change==='route')routeToken++;
            if(change==='hash')location.hash=deckHref('casual/other');
            if(change==='screen')deckScreen={...deckScreen};
            if(change==='view')deckScreen.view={...deckScreen.view};
            if(change==='data')deckScreen.data={...deckScreen.data};
            if(change==='summary')deckScreen.data.summary={...deckScreen.data.summary};
            if(change==='version')deckScreen.data.version='owned';
            more.click();assert.equal(group.querySelectorAll('a').length,20,change);
            assert.equal(calls.length,reads,change);assert.equal(writes.length,0);
          }
        """)
