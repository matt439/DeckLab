"""Private existing-member email replacement with exact review and save receipts.

Real page functions over deterministic DOM/API promises; no server or data writes.
"""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELL + r'''
  const hashA='a'.repeat(64), hashB='b'.repeat(64), hashC='c'.repeat(64), hashD='d'.repeat(64);
  const memberList=()=>({editable:true,config_sha256:hashA,membership_sha256:hashB,members:[
    {id:'user2',name:'User2',emails:['old@example.com','alias@example.com']},
    {id:'user3',name:'User3',emails:['other@example.com']} ]});
  let list=memberList(), reads=[], writes=[];
  api=async(path)=>{reads.push(path);if(path==='/api/settings/members')return list;throw Error('Other panel omitted');};
  const confirmed=(body)=>({saved:body.old_email!==body.new_email,noop:body.old_email===body.new_email,
    member:{id:body.member_id,name:body.member_id==='user2'?'User2':'User3',emails:
      list.members.find(row=>row.id===body.member_id).emails.map(email=>email===body.old_email?body.new_email:email)},
    replaced:{old_email:body.old_email,new_email:body.new_email},
    config_sha256:body.old_email===body.new_email?hashA:hashC,membership_sha256:body.old_email===body.new_email?hashB:hashD,
    change_set_id:body.old_email===body.new_email?null:42,access_policy_required:true});
  apiWrite=async(path,body,method)=>{writes.push({path,body,method});return confirmed(body);};
  showFooter=()=>{};loadServerRestart=()=>{};loadSimulations=()=>{};loadCommanderNightSettings=()=>{};loadVisits=()=>{};loadSettingsMaintenance=()=>{};
  const openMembers=async()=>{as('matt',false);location.hash='#/settings';showSettings(new URLSearchParams(),routeToken);await flush();return byId('settings-members-content');};
  const memberButton=text=>main.querySelectorAll('button').find(node=>node.textContent===text);
  const enterEmail=value=>{const input=byId('settings-member-new-email');input.value=value;input.fire('input');return input;};
  const reviewEmail=(value='new@example.com')=>{enterEmail(value);memberButton('Review email change').click();};
  const saveEmail=()=>memberButton('Save email change').click();
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsMembersUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_explicit_home_admin_panel_has_labelled_local_member_alias_and_blank_new_email(self):
        self.run_js(r'''
          await openMembers();same(reads,['/api/settings/members']);assert(byId('settings-members'));
          for(const id of ['settings-member-id','settings-member-old-email','settings-member-new-email'])
            assert(main.querySelectorAll('label').some(node=>node.getAttribute('for')===id),id);
          assert.equal(byId('settings-member-id').value,'user2');assert.equal(byId('settings-member-old-email').value,'old@example.com');
          assert.equal(byId('settings-member-new-email').value,'');assert(memberButton('Save email change').hidden);
          assert.equal(writes.length,0);assert(!JSON.stringify(state).includes('old@example.com'));
          assert(!JSON.stringify(window.localStorage.data).includes('@'));assert(!JSON.stringify(window.sessionStorage.data).includes('@'));
          assert.equal(location.hash,'#/settings');
        ''')

    def test_member_other_space_admin_legacy_and_anonymous_never_request_or_draw_addresses(self):
        self.run_js(r'''
          for(const profile of [PROFILES[1],{...PROFILES[2],role:'admin'},{id:'legacy',space:'home'},null]){
            clear(main);state.profile=profile;state.may={admin:true};location.hash='#/settings';
            showSettings(new URLSearchParams(),routeToken);await flush();assert.equal(byId('settings-members'),null);
          }
          assert.equal(reads.length,0);assert.equal(writes.length,0);
        ''')

    def test_review_is_local_exact_normalized_replacement_and_does_not_save_on_enter(self):
        self.run_js(r'''
          await openMembers();reviewEmail('  NEW@EXAMPLE.COM  ');const preview=main.querySelector('.settings-member-review');
          assert(!preview.hidden);assert(preview.textContent.includes('Replace: old@example.com'));
          assert(preview.textContent.includes('With: new@example.com'));assert(!memberButton('Save email change').hidden);
          main.querySelector('.settings-members-form').fire('submit');await flush();assert.equal(writes.length,0);same(reads,['/api/settings/members']);
        ''')

    def test_explicit_save_sends_only_exact_observed_receipts_and_preserves_other_aliases(self):
        self.run_js(r'''
          await openMembers();reviewEmail();saveEmail();await flush();
          same(writes,[{path:'/api/settings/member-email',method:'POST',body:{profile:'matt',member_id:'user2',old_email:'old@example.com',
            new_email:'new@example.com',config_sha256:hashA,membership_sha256:hashB}}]);
          assert(main.textContent.includes('Member email change saved.'));assert(main.textContent.includes('Add new@example.com to the Cloudflare Access policy'));
          assert(main.textContent.includes("hasn't verified the Access policy or the member's sign-in"));
          assert(memberButton('Save email change').hidden);assert(memberButton('Review email change').hidden);assert(!memberButton('Reload member emails').hidden);
          assert.equal(list.members[0].emails[0],'old@example.com');assert(!JSON.stringify(state).includes('new@example.com'));
        ''')

    def test_alias_and_member_changes_invalidate_review_and_reset_new_input(self):
        self.run_js(r'''
          await openMembers();reviewEmail();const old=byId('settings-member-old-email');old.value='alias@example.com';old.fire('change');
          assert(memberButton('Save email change').hidden);assert(main.querySelector('.settings-member-review').hidden);
          reviewEmail();saveEmail();await flush();assert.equal(writes[0].body.old_email,'alias@example.com');
          await openMembers();reviewEmail();const person=byId('settings-member-id');person.value='user3';person.fire('change');
          assert.equal(byId('settings-member-old-email').value,'other@example.com');assert.equal(byId('settings-member-new-email').value,'');assert(memberButton('Save email change').hidden);
        ''')

    def test_input_change_requires_another_review_even_without_input_event(self):
        self.run_js(r'''
          await openMembers();reviewEmail();byId('settings-member-new-email').value='different@example.com';saveEmail();await flush();
          assert.equal(writes.length,0);assert(main.textContent.includes('Review the replacement again'));assert(memberButton('Save email change').hidden);
          reviewEmail('different@example.com');saveEmail();await flush();assert.equal(writes[0].body.new_email,'different@example.com');
        ''')

    def test_invalid_unicode_missing_domain_and_duplicate_alias_never_write(self):
        self.run_js(r'''
          await openMembers();for(const value of ['', 'missing', 'a@b', 'ü@example.com', 'K@example.com', 'a b@example.com', 'a@@example.com',
            '.a@example.com','a.@example.com','a..b@example.com','a@-example.com','a@example..com','a@exam_ple.com','a'.repeat(65)+'@example.com','a'.repeat(255)+'@example.com']){
            reviewEmail(value);assert(memberButton('Save email change').hidden,value);assert(main.textContent.includes('valid new email address'));
          }
          for(const value of ['alias@example.com','other@example.com']){reviewEmail(value);assert(memberButton('Save email change').hidden);assert(main.textContent.includes('already listed'));}
          assert.equal(writes.length,0);
        ''')

    def test_pending_clicks_inputs_and_submit_cannot_duplicate_or_replace_the_review(self):
        self.run_js(r'''
          await openMembers();let resolve;apiWrite=async(path,body)=>{writes.push(body);return new Promise(done=>{resolve=done;});};
          reviewEmail();saveEmail();saveEmail();main.querySelector('.settings-members-form').fire('submit');
          assert.equal(writes.length,1);assert(byId('settings-member-new-email').disabled);assert(memberButton('Save email change').disabled);
          resolve(confirmed(writes[0]));await flush();assert(main.textContent.includes('Member email change saved.'));
        ''')

    def test_noop_requires_same_address_unchanged_hashes_and_no_change_set(self):
        self.run_js(r'''
          await openMembers();reviewEmail('OLD@EXAMPLE.COM');saveEmail();await flush();
          assert(main.textContent.includes('No change was saved'));assert(!main.textContent.includes('Member email change saved.'));
          assert(main.textContent.includes('Add old@example.com to the Cloudflare Access policy'));
        ''')

    def test_stale_refusal_retains_entries_disables_retry_and_requires_reload(self):
        self.run_js(r'''
          await openMembers();apiWrite=async(path,body)=>{writes.push(body);throw Object.assign(Error('stale'),{status:409});};
          reviewEmail();saveEmail();await flush();assert.equal(byId('settings-member-new-email').value,'new@example.com');
          assert(main.textContent.includes('saved member settings changed'));assert(!main.textContent.includes('change saved.'));
          saveEmail();main.querySelector('.settings-members-form').fire('submit');assert.equal(writes.length,1);
          memberButton('Reload member emails').click();await flush();assert.equal(reads.length,2);assert.equal(byId('settings-member-new-email').value,'');
        ''')

    def test_uncertain_network_failure_never_automatically_retries_or_claims_success(self):
        self.run_js(r'''
          await openMembers();apiWrite=async(path,body)=>{writes.push(body);throw Error('lost connection');};reviewEmail();saveEmail();await flush();
          assert(main.textContent.includes("save couldn't be confirmed"));assert(memberButton('Save email change').hidden);assert.equal(reads.length,1);
          main.querySelector('.settings-members-form').fire('submit');assert.equal(writes.length,1);assert(!main.textContent.includes('change saved.'));
        ''')

    def test_email_validation_refusal_shows_static_reason_without_reopening_save(self):
        self.run_js(r'''
          await openMembers();apiWrite=async(path,body)=>{writes.push(body);throw Object.assign(Error('That email is already listed. Choose an address that belongs to only this member.'),{status:400});};
          reviewEmail();saveEmail();await flush();assert(main.textContent.includes('That email is already listed. Choose an address that belongs to only this member.'));
          assert(main.textContent.includes('Reload member emails before reviewing another change'));assert.equal(byId('settings-member-new-email').value,'new@example.com');
          memberButton('Add member').fire('click');saveEmail();main.querySelector('.settings-members-form').fire('submit');
          assert.equal(writes.length,1);assert.equal(main.querySelector('.settings-member-add-form'),null);assert(memberButton('Save email change').hidden);
          assert(!memberButton('Reload member emails').hidden);assert(!main.textContent.includes('change saved.'));
        ''')

    def test_email_unknown_server_details_and_unbounded_refusals_are_not_exposed(self):
        self.run_js(r'''
          for(const failure of [Error('private-detail-marker'),Object.assign(Error('private-detail-marker'),{status:500}),
            Object.assign(Error('private-detail-marker'),{status:503}),{status:400,message:''},{status:400,message:null},
            {status:400,message:'private-detail-marker'+'x'.repeat(501)}]){
            await openMembers();apiWrite=async()=>{throw failure;};reviewEmail();saveEmail();await flush();
            assert(main.textContent.includes("save couldn't be confirmed"));assert(!main.textContent.includes('private-detail-marker'));
            assert(!main.textContent.includes('change saved.'));assert(!memberButton('Reload member emails').hidden);
          }
        ''')

    def test_malformed_or_mismatched_receipts_fail_closed(self):
        self.run_js(r'''
          const changes=[reply=>({...reply,saved:false}),reply=>({...reply,noop:true}),reply=>({...reply,change_set_id:null}),
            reply=>({...reply,config_sha256:hashA}),reply=>({...reply,membership_sha256:hashB}),reply=>({...reply,access_policy_required:false}),
            reply=>({...reply,replaced:{...reply.replaced,old_email:'alias@example.com'}}),reply=>({...reply,replaced:{...reply.replaced,new_email:'wrong@example.com'}}),
            reply=>({...reply,member:{...reply.member,id:'user3'}}),reply=>({...reply,member:{...reply.member,name:'Wrong'}}),
            reply=>({...reply,member:{...reply.member,emails:['new@example.com']}}),reply=>({...reply,member:{...reply.member,emails:['new@example.com','new@example.com']}}),
            reply=>({...reply,config_sha256:'bad'}),()=>null];
          for(const alter of changes){await openMembers();apiWrite=async(path,body)=>alter(confirmed(body));reviewEmail();saveEmail();await flush();
            assert(main.textContent.includes("save couldn't be confirmed"));assert(!main.textContent.includes('change saved.'));assert(!memberButton('Reload member emails').hidden);}
        ''')

    def test_malformed_list_exposes_no_partial_emails_and_allows_read_only_reload(self):
        self.run_js(r'''
          for(const alter of [value=>({...value,editable:false}),value=>({...value,config_sha256:'bad'}),value=>({...value,membership_sha256:null}),
            value=>({...value,members:[value.members[0],value.members[0]]}),value=>({...value,members:[{...value.members[0],id:'home'}]}),
            value=>({...value,members:[{...value.members[0],emails:['Old@example.com']}]}),value=>({...value,members:[{...value.members[0],emails:[]}]}),
            value=>({...value,members:[{...value.members[0],emails:['old@example.com','old@example.com']}]}),value=>({...value,members:null})]){
            list=alter(memberList());await openMembers();assert.equal(byId('settings-member-new-email'),null);assert(!main.textContent.includes('old@example.com'));
            assert(main.textContent.includes("Member emails couldn't be loaded"));assert(memberButton('Reload member emails'));}
          assert.equal(writes.length,0);
        ''')

    def test_empty_list_is_quiet_without_inventing_a_profile_or_add_member_action(self):
        self.run_js(r'''
          list={...memberList(),members:[]};await openMembers();assert(main.textContent.includes('No members have their own space and an email yet'));
          assert.equal(byId('settings-member-new-email'),null);assert.equal(writes.length,0);
        ''')

    def test_late_reads_after_route_profile_or_host_replacement_do_not_leak_addresses(self):
        self.run_js(r'''
          for(const mode of ['route','hash','profile','host']){
            let resolve;api=async()=>new Promise(done=>{resolve=done;});as('matt',false);location.hash='#/settings';showSettings(new URLSearchParams(),routeToken);
            const host=byId('settings-members-content');if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='host')host.replaceWith(el('div',{id:'settings-members-content'}));
            resolve(memberList());await flush();assert.equal(byId('settings-member-new-email'),null);assert(!main.textContent.includes('old@example.com'));
          }
        ''')

    def test_newer_reload_wins_over_an_older_pending_read(self):
        self.run_js(r'''
          let resolves=[];api=async()=>new Promise(done=>resolves.push(done));as('matt',false);location.hash='#/settings';showSettings(new URLSearchParams(),routeToken);
          loadSettingsMembers(routeToken);resolves[1]({...memberList(),members:[{id:'user3',name:'User3',emails:['other@example.com']}]});await flush();
          resolves[0](memberList());await flush();assert.equal(byId('settings-member-id').value,'user3');assert(!main.textContent.includes('old@example.com'));
        ''')

    def test_late_success_or_error_cannot_replace_a_different_viewer_or_page(self):
        self.run_js(r'''
          for(const fail of [false,true]){
            api=async()=>memberList();await openMembers();let finish;apiWrite=async()=>new Promise((resolve,reject)=>{finish=fail?reject:resolve;});
            reviewEmail();saveEmail();const request={member_id:'user2',old_email:'old@example.com',new_email:'new@example.com'};
            as('user1',false);location.hash='#/library';routeToken++;main.append(el('p',{text:'Current member page'}));
            finish(fail?Error('late'):confirmed(request));await flush();assert.equal(main.textContent,'Current member page');
          }
        ''')

    def test_emails_and_member_names_are_text_not_markup_and_never_added_to_roster(self):
        self.run_js(r'''
          list={...memberList(),members:[{id:'user2',name:'<img src=x>',emails:['old@example.com']}]};await openMembers();
          assert.equal(main.querySelector('img'),null);reviewEmail();assert(main.textContent.includes('<img src=x>'));assert.equal(main.querySelector('img'),null);
          assert(!JSON.stringify(PROFILES).includes('old@example.com'));assert(!JSON.stringify(state).includes('old@example.com'));assert.equal(writes.length,0);
        ''')


if __name__ == "__main__":
    unittest.main()
