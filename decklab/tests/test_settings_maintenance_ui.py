"""Admin maintenance history over mocked Node API promises; no jobs, server or database."""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELL + r'''
  showFooter=()=>{};settingsSimulations=()=>{};loadCommanderNightSettings=()=>{};loadSettingsMembers=()=>{};loadVisits=()=>{};
  state.status=null;state.simulations=null;
  let reads=[],writes=0,fetches=0;
  apiWrite=()=>{writes++;throw Error('Writes are forbidden');};
  fetch=()=>{fetches++;throw Error('Network is forbidden');};
  const succeeded=(day='28')=>({started_at:`2026-10-${day}T03:30:00Z`,finished_at:`2026-10-${day}T03:31:00Z`,outcome:'success'});
  const history=()=>({available:true,checked_at:'2026-10-28T09:00:00Z',recent_limit:5,jobs:
    ['dump','export','check','restore_check'].map(kind=>({kind,latest:succeeded(),last_success:succeeded(),recent:[succeeded()],
      health:'success',freshness:'current',interval:{value:kind==='restore_check'?28:36,unit:kind==='restore_check'?'days':'hours',
        source:kind==='restore_check'?'restore_check_days':'stale_backup_hours',basis:['dump','export'].includes(kind)?'finished_at':'started_at'}}))});
  let answer=history();
  api=async(path,options)=>{reads.push({path,options});if(path!=='/api/settings/maintenance')throw Error('Unexpected read');return structuredClone(answer);};
  const openHistory=async()=>{as('matt',false);location.hash='#/settings';routeToken++;showSettings(new URLSearchParams(),routeToken);
    await flush();return byId('settings-maintenance-content');};
  const job=kind=>main.querySelector(`[data-maintenance-job="${kind}"]`);
  const refresh=()=>byId('settings-maintenance-refresh');
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsMaintenanceUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([
            str(WEB), SETUP + scenario + "\nassert.equal(writes,0);assert.equal(fetches,0);", True]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_settings_opens_four_named_jobs_with_separate_attempt_and_success(self):
        self.run_js(r'''
          const host=await openHistory();same(reads,[{path:'/api/settings/maintenance'}]);
          same(host.querySelectorAll('[data-maintenance-job]').map(node=>node.dataset.maintenanceJob),['dump','export','check','restore_check']);
          for(const kind of ['dump','export','check','restore_check']){const row=job(kind);
            assert(row.textContent.includes('Latest status: Succeeded.'));assert(row.textContent.includes('Latest attempt: Succeeded.'));
            assert(row.textContent.includes('Last successful run: Succeeded.'));assert(row.querySelector('details'));}
          assert.equal(byId('settings-maintenance').getAttribute('aria-labelledby'),'settings-maintenance-title');
          assert(byId('settings-maintenance-title').textContent.includes('Database maintenance'));assert(!refresh().disabled);
          assert(host.textContent.includes('History checked:'));assert(main.textContent.includes('Refreshing only reads history.'));
        ''')

    def test_failed_latest_never_presents_older_success_as_current_health(self):
        self.run_js(r'''
          const failed={...succeeded(),outcome:'failure'};answer.jobs[0]={...answer.jobs[0],latest:failed,
            last_success:succeeded('26'),recent:[failed,succeeded('26')],health:'failure',freshness:'stale'};
          await openHistory();const row=job('dump');assert(row.textContent.includes('Latest status: Failed.'));
          assert(row.textContent.includes('Latest attempt: Failed.'));assert(row.textContent.includes('Last successful run: Succeeded.'));
          assert(row.textContent.includes('Last success is overdue.'));assert(!row.textContent.includes('Latest status: Succeeded.'));
          assert.equal(row.querySelectorAll('li').length,2);
        ''')

    def test_restore_check_uses_its_own_interval_and_export_names_nightly_policy(self):
        self.run_js(r'''
          answer.jobs[3]={...answer.jobs[3],latest:succeeded('10'),last_success:succeeded('10'),recent:[succeeded('10')]};
          await openHistory();assert(job('restore_check').textContent.includes('Latest status: Succeeded.'));
          assert(job('restore_check').textContent.includes('28 days, from start.'));assert(!job('restore_check').textContent.includes('overdue'));
          assert(job('export').textContent.includes('Export uses the nightly grace period: 36 hours, from finish.'));
          assert(job('check').textContent.includes('36 hours, from start.'));
        ''')

    def test_overdue_success_and_latest_failure_with_current_older_success_stay_distinct(self):
        self.run_js(r'''
          answer.jobs[3]={...answer.jobs[3],health:'stale',freshness:'stale'};
          answer.jobs[1]={...answer.jobs[1],latest:{...succeeded(),outcome:'failure'},health:'failure'};
          await openHistory();assert(job('restore_check').textContent.includes('Latest status: Overdue.'));
          assert(job('export').textContent.includes('Latest status: Failed.'));assert(job('export').textContent.includes('within its freshness interval'));
        ''')

    def test_never_run_is_explicit_for_all_jobs_and_does_not_invent_running(self):
        self.run_js(r'''
          answer.jobs=answer.jobs.map(row=>({...row,latest:null,last_success:null,recent:[],health:'never',freshness:'never'}));
          const host=await openHistory();for(const kind of ['dump','export','check','restore_check']){
            assert(job(kind).textContent.includes('Latest attempt: No recorded attempts.'));assert(job(kind).textContent.includes('Last successful run: None recorded.'));}
          assert(!host.textContent.includes('Running'));assert.equal(host.querySelectorAll('details').length,0);
        ''')

    def test_unknown_recorded_outcome_and_missing_dates_remain_unknown(self):
        self.run_js(r'''
          const unknown={started_at:null,finished_at:null,outcome:'unknown'};
          answer.jobs[0]={...answer.jobs[0],latest:unknown,recent:[unknown],health:'unknown',freshness:'unknown',interval:{...answer.jobs[0].interval,value:null}};
          await openHistory();const row=job('dump');assert(row.textContent.includes('Latest status: Outcome unavailable.'));
          assert(row.textContent.includes('Started: Date unavailable. Finished: Date unavailable.'));assert(row.textContent.includes('Freshness is unknown.'));
          assert(row.textContent.includes('Freshness interval unavailable.'));assert(!row.textContent.includes('Running'));assert(!row.textContent.includes('Invalid Date'));
        ''')

    def test_last_success_can_be_older_than_bounded_recent_failures(self):
        self.run_js(r'''
          const failed={...succeeded(),outcome:'failure'};answer.jobs[0]={...answer.jobs[0],latest:failed,
            recent:Array.from({length:5},()=>failed),last_success:succeeded('01'),health:'failure',freshness:'stale'};
          await openHistory();const row=job('dump');assert(row.textContent.includes('Last successful run: Succeeded.'));
          assert(row.textContent.includes(settingsMaintenanceWhen('2026-10-01T03:31:00Z')));assert.equal(row.querySelectorAll('li').length,5);
        ''')

    def test_initial_loading_is_announced_without_success_until_answer_arrives(self):
        self.run_js(r'''
          let resolve;api=path=>{reads.push({path});return new Promise(done=>{resolve=done;});};
          const host=await openHistory();assert(host.textContent.includes('Loading maintenance history.'));
          assert(host.querySelector('[role="status"]'));assert(refresh().disabled);assert(!host.textContent.includes('Succeeded'));
          resolve(answer);await flush();assert(host.textContent.includes('Latest status: Succeeded.'));assert(!refresh().disabled);
        ''')

    def test_manual_refresh_clears_old_health_coalesces_clicks_and_keeps_its_button(self):
        self.run_js(r'''
          const host=await openHistory(),button=refresh();button.focus();let resolve;
          api=path=>{reads.push({path});return new Promise(done=>{resolve=done;});};button.click();button.click();loadSettingsMaintenance(routeToken);
          assert.equal(reads.length,2);assert(host.textContent.includes('Loading maintenance history.'));assert(!host.textContent.includes('Succeeded'));
          assert.equal(refresh(),button);assert(button.disabled);resolve(answer);await flush();assert.equal(refresh(),button);
          assert(!button.disabled);assert.equal(document.activeElement,button);assert(host.textContent.includes('Latest status: Succeeded.'));
        ''')

    def test_failed_refresh_removes_old_claims_and_never_prints_raw_errors(self):
        self.run_js(r'''
          const host=await openHistory();api=async path=>{reads.push({path});throw new ApiError(503,'C:/private/backup.dump password=secret',{detail:'private record'});};
          refresh().click();await flush();assert(host.textContent.includes('Maintenance history is unavailable.'));
          assert(host.querySelector('[role="alert"]'));assert(!refresh().disabled);
          for(const text of ['Succeeded','private','password','secret','503'])assert(!host.textContent.includes(text),text);
          api=async path=>{reads.push({path});return answer;};refresh().click();await flush();assert(host.textContent.includes('Latest status: Succeeded.'));
        ''')

    def test_unavailable_and_malformed_answers_fail_closed_without_private_extras(self):
        self.run_js(r'''
          const original=history();const bad=[{available:false,detail:'secret'},null,{...original,checked_at:'secret'},
            {...original,jobs:original.jobs.slice(1)},{...original,jobs:[...original.jobs,original.jobs[0]]},
            {...original,recent_limit:999}, {...original,jobs:original.jobs.map((row,i)=>i?row:{...row,health:'running'})},
            {...original,jobs:original.jobs.map((row,i)=>i?row:{...row,recent:Array(6).fill(succeeded())})}];
          for(const value of bad){answer=value;const host=await openHistory();assert(host.textContent.includes('Maintenance history is unavailable.'));
            assert(!host.textContent.includes('Succeeded'));assert(!host.textContent.includes('secret'));}
        ''')

    def test_allowed_fields_render_as_text_and_private_response_extras_are_ignored(self):
        self.run_js(r'''
          answer.path='C:/private';answer.jobs[0].detail='<script>secret</script>';answer.jobs[0].latest.detail='password=secret';
          const host=await openHistory();for(const text of ['private','secret','password','<script>'])assert(!host.textContent.includes(text));
          assert(!host.querySelector('script'));assert(!JSON.stringify(state).includes('2026-10-28T09:00:00Z'));
          assert(!JSON.stringify(window.localStorage.data).includes('2026-10'));assert(!JSON.stringify(window.sessionStorage.data).includes('2026-10'));
        ''')

    def test_members_unsigned_and_legacy_denials_never_read_history(self):
        self.run_js(r'''
          for(const [profile,may] of [[PROFILES[1],MAY.user1],[PROFILES[2],MAY.user2],[null,null],[{id:'legacy',space:'home'},{admin:false}]]){
            state.profile=profile;state.may=may;location.hash='#/settings';routeToken++;showSettings(new URLSearchParams(),routeToken);await flush();
            loadSettingsMaintenance(routeToken);await flush();assert.equal(byId('settings-maintenance'),null);}
          assert.equal(reads.length,0);
        ''')

    def test_missing_role_never_uses_permissive_legacy_may_fallback_for_history(self):
        self.run_js(r'''
          state.profile={id:'legacy',space:'home'};state.may={admin:true};location.hash='#/settings';
          showSettings(new URLSearchParams(),routeToken);await flush();assert.equal(reads.length,0);assert.equal(byId('settings-maintenance'),null);
        ''')

    def test_late_reply_cannot_draw_after_route_change_or_replace_new_panel(self):
        self.run_js(r'''
          const pending=[];api=path=>{reads.push({path});return new Promise(done=>pending.push(done));};
          const old=await openHistory();location.hash='#/library';routeToken++;clear(main).append(el('p',{text:'Library'}));
          pending.shift()(answer);await flush();assert.equal(main.textContent,'Library');assert(!old.textContent.includes('Succeeded'));
          const first=await openHistory(),second=await openHistory();pending[1](answer);await flush();
          assert(second.textContent.includes('Succeeded'));const failed=history();failed.jobs[0]={...failed.jobs[0],health:'failure',latest:{...succeeded(),outcome:'failure'}};
          pending[0](failed);await flush();assert(second.textContent.includes('Latest status: Succeeded.'));assert(!first.textContent.includes('Succeeded'));
        ''')

    def test_same_token_profile_replacement_and_permission_loss_ignore_private_reply(self):
        self.run_js(r'''
          for(const change of [()=>{state.profile={...state.profile};},()=>{state.profile.role='member';}]){
            let resolve;api=()=>new Promise(done=>{resolve=done;});const host=await openHistory();change();resolve(answer);await flush();
            assert(!host.textContent.includes('Succeeded'));assert(host.textContent.includes('Loading maintenance history.'));PROFILES[0].role='admin';}
        ''')

    def test_same_token_detached_host_and_stale_request_sequence_ignore_reply(self):
        self.run_js(r'''
          let resolve;api=()=>new Promise(done=>{resolve=done;});let host=await openHistory();
          host.replaceWith(el('div',{id:'settings-maintenance-content',text:'New owner'}));resolve(answer);await flush();
          assert.equal(byId('settings-maintenance-content').textContent,'New owner');assert(!host.textContent.includes('Succeeded'));
          host=await openHistory();host.maintenanceRequest++;resolve(answer);await flush();assert(!host.textContent.includes('Succeeded'));
        ''')

    def test_returning_to_settings_fetches_again_without_retaining_old_history(self):
        self.run_js(r'''
          const first=await openHistory();assert(job('dump'));answer=history();answer.jobs=answer.jobs.map(row=>({...row,latest:null,last_success:null,recent:[],health:'never',freshness:'never'}));
          const second=await openHistory();assert.notEqual(first,second);assert.equal(reads.length,2);assert(!second.textContent.includes('Succeeded'));
          assert(second.textContent.includes('No recorded attempts.'));
        ''')

    def test_zero_interval_is_valid_and_server_freshness_is_authoritative(self):
        self.run_js(r'''
          answer.jobs=answer.jobs.map(row=>({...row,interval:{...row.interval,value:0},health:'stale',freshness:'stale'}));
          await openHistory();assert(job('dump').textContent.includes('Freshness interval: 0 hours, from finish.'));
          assert(job('restore_check').textContent.includes('Freshness interval: 0 days, from start.'));
          assert(job('restore_check').textContent.includes('Latest status: Overdue.'));
        ''')

    def test_inconsistent_success_claims_and_malformed_dates_or_policy_never_show_healthy(self):
        self.run_js(r'''
          const mutations=[row=>({...row,latest:{...succeeded(),outcome:'failure'}}),row=>({...row,latest:null}),
            row=>({...row,last_success:null}),row=>({...row,latest:{...succeeded(),finished_at:'2026-11-01T00:00:00Z'}}),
            row=>({...row,latest:{...succeeded(),started_at:'2026-10-28T04:00:00Z'}}),
            row=>({...row,interval:{...row.interval,unit:'days'}}),row=>({...row,interval:{...row.interval,value:-1}}),
            row=>({...row,interval:{...row.interval,value:null}})];
          for(const mutate of mutations){answer=history();answer.jobs[0]=mutate(answer.jobs[0]);const host=await openHistory();
            assert(host.textContent.includes('Maintenance history is unavailable.'));assert(!host.textContent.includes('Succeeded'));}
        ''')

    def test_old_refresh_control_cannot_read_into_a_new_panel_or_profile(self):
        self.run_js(r'''
          await openHistory();const old=refresh();await openHistory();assert.equal(reads.length,2);old.click();await flush();assert.equal(reads.length,2);
          const activeButton=refresh();state.profile={...state.profile};activeButton.click();await flush();assert.equal(reads.length,2);
        ''')

    def test_refresh_restores_lost_button_focus_but_never_steals_later_focus(self):
        self.run_js(r'''
          await openHistory();const button=refresh();let resolve;api=()=>new Promise(done=>{resolve=done;});
          button.focus();button.click();document.activeElement=document.body;resolve(answer);await flush();assert.equal(document.activeElement,button);
          button.click();const other=el('button',{text:'Another control'});main.append(other);other.focus();resolve(answer);await flush();
          assert.equal(document.activeElement,other);assert(!button.disabled);
        ''')

    def test_normalized_impossible_calendar_and_time_cannot_become_success(self):
        self.run_js(r'''
          for(const stamp of ['2026-02-30T03:30:00Z','2026-02-29T03:30:00Z','2026-04-31T03:30:00Z',
            '2026-10-27T24:00:00Z','2026-10-27T03:60:00Z','2026-10-27T03:30:60Z','0000-10-27T03:30:00Z']){
            answer=history();const invalid={started_at:stamp,finished_at:stamp,outcome:'success'};
            answer.jobs[0]={...answer.jobs[0],latest:invalid,last_success:invalid,recent:[invalid]};const host=await openHistory();
            assert(host.textContent.includes('Maintenance history is unavailable.'),stamp);assert(!host.textContent.includes('Succeeded'),stamp);}
          answer=history();answer.checked_at='2026-10-28T09:00:00.123456+00:00';
          const leap={started_at:'2024-02-29T03:30:00+00:00',finished_at:'2024-02-29T03:31:00.123456+00:00',outcome:'success'};
          answer.jobs[3]={...answer.jobs[3],latest:leap,last_success:leap,recent:[leap],health:'stale',freshness:'stale'};
          await openHistory();assert(job('restore_check').textContent.includes('Latest status: Overdue.'));
        ''')

    def test_in_place_selected_id_change_rejects_reply_and_retired_refresh_control(self):
        self.run_js(r'''
          let resolve;api=path=>{reads.push({path});return new Promise(done=>{resolve=done;});};
          const host=await openHistory(),button=refresh(),selected=state.profile,selectedId=selected.id;
          selected.id='other-admin';resolve(answer);await flush();assert(!host.textContent.includes('Succeeded'));
          button.disabled=false;button.click();await flush();assert.equal(reads.length,1);selected.id=selectedId;
        ''')
