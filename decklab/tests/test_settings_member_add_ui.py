"""Private own-space member creation and mode ownership in the Settings panel.

Real UI functions with deterministic DOM/API doubles; no real profiles or writes.
"""
import json
import subprocess
import unittest

from decklab.tests.test_settings_members_ui import SETUP as MEMBERS
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = MEMBERS + r'''
  const created=body=>({saved:true,noop:false,member:{id:body.member_id,name:body.name,emails:[body.email]},
    config_sha256:hashC,membership_sha256:hashD,change_set_id:71,access_policy_required:true});
  apiWrite=async(path,body,method)=>{writes.push({path,body,method});return path==='/api/settings/member'?created(body):confirmed(body);};
  const openAdd=async(empty=false)=>{list={...memberList(),members:empty?[]:memberList().members};await openMembers();memberButton('Add member').click();return main.querySelector('.settings-member-add-form');};
  const newField=(id,value,event=true)=>{const input=byId('settings-member-add-'+id);input.value=value;if(event)input.fire('input');return input;};
  const fillMember=(changes={})=>{for(const [key,value] of Object.entries({name:'User4',id:'user4',email:'member@example.com',...changes}))newField(key,value);};
  const reviewMember=(changes={})=>{fillMember(changes);memberButton('Review new member').click();};
  const saveMember=()=>memberButton('Save new member').click();
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SettingsMemberAddUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_empty_member_list_still_offers_creation_with_labelled_blank_fields(self):
        self.run_js(r'''
          const form=await openAdd(true);assert(form);assert.equal(main.querySelectorAll('.settings-members-form').length,1);
          for(const id of ['name','id','email']){const input=byId('settings-member-add-'+id);assert.equal(input.value,'');
            assert(form.querySelectorAll('label').some(label=>label.getAttribute('for')===input.id));}
          assert.equal(document.activeElement,byId('settings-member-add-name'));assert.equal(byId('settings-member-add-name').getAttribute('maxlength'),'240');
          assert(form.textContent.includes('empty space'));assert(form.textContent.includes('start Private'));assert(memberButton('Save new member').hidden);
          same(reads,['/api/settings/members']);assert.equal(writes.length,0);
        ''')

    def test_mode_switch_reuses_receipts_replaces_form_and_invalidates_old_review(self):
        self.run_js(r'''
          await openMembers();reviewEmail();const emailForm=main.querySelector('.settings-members-form'),oldSave=memberButton('Save email change');
          memberButton('Add member').click();assert(!emailForm.isConnected);assert.equal(byId('settings-member-new-email'),null);oldSave.click();await flush();assert.equal(writes.length,0);
          reviewMember();const addForm=main.querySelector('.settings-member-add-form'),addSave=memberButton('Save new member');
          memberButton('Back to email changes').click();assert(!addForm.isConnected);assert.equal(byId('settings-member-new-email').value,'');
          assert.equal(document.activeElement,byId('settings-member-id'));addSave.click();await flush();assert.equal(writes.length,0);same(reads,['/api/settings/members']);
        ''')

    def test_review_uses_exact_normalized_values_and_fixed_private_member_scope(self):
        self.run_js(r'''
          const form=await openAdd();reviewMember({name:' User4 ',id:' user4 ',email:' MEMBER@EXAMPLE.COM '});
          const preview=form.querySelector('.settings-member-review');assert(!preview.hidden);assert(preview.textContent.includes('Name: User4'));
          assert(preview.textContent.includes('Permanent id and own space: user4'));assert(preview.textContent.includes('Sign-in email: member@example.com'));
          assert(preview.textContent.includes('Role: Member'));assert(preview.textContent.includes('empty'));assert(preview.textContent.includes('Private'));
          form.fire('submit');await flush();assert.equal(writes.length,0);assert(!memberButton('Save new member').hidden);
          assert.equal(form.querySelector('select'),null);same(reads,['/api/settings/members']);
        ''')

    def test_save_posts_only_reviewed_creation_fields_and_original_receipts(self):
        self.run_js(r'''
          await openAdd();reviewMember();saveMember();await flush();
          same(writes,[{path:'/api/settings/member',method:'POST',body:{profile:'matt',member_id:'user4',name:'User4',email:'member@example.com',
            config_sha256:hashA,membership_sha256:hashB}}]);assert(main.textContent.includes('Member added.'));assert(main.textContent.includes('User4 now has the private space user4'));
          assert(main.textContent.includes('Add member@example.com to the Cloudflare Access policy'));assert(main.textContent.includes("hasn't verified the Access policy or the member's sign-in"));
          assert(memberButton('Save new member').hidden);assert(memberButton('Back to email changes').disabled);assert(!memberButton('Reload member emails').hidden);
        ''')

    def test_success_does_not_put_new_member_or_email_in_roster_storage_or_url(self):
        self.run_js(r'''
          await openAdd();const before=JSON.stringify(state);reviewMember();saveMember();await flush();
          assert.equal(JSON.stringify(state),before);assert(!JSON.stringify(PROFILES).includes('user4'));assert.equal(location.hash,'#/settings');
          assert(!JSON.stringify(window.localStorage.data).includes('member@example.com'));assert(!JSON.stringify(window.sessionStorage.data).includes('member@example.com'));
        ''')

    def test_id_validation_rejects_reserved_uppercase_non_slug_and_overlong_values(self):
        self.run_js(r'''
          await openAdd();for(const id of ['','home','system','claude','test','casual','commander','product','pairing','people','User4','user_4','user--4','-user4','user4-',
            'user/4','a'.repeat(41),'üser4']){reviewMember({id});assert(memberButton('Save new member').hidden,id);assert(main.textContent.includes('non-reserved member id'),id);}
          assert.equal(writes.length,0);
        ''')

    def test_name_validation_counts_unicode_characters_and_rejects_controls(self):
        self.run_js(r'''
          await openAdd();for(const name of ['', '   ', 'a'.repeat(121), 'Line\nBreak','Name\x00Part','Name\x7fPart']){
            reviewMember({name});assert(memberButton('Save new member').hidden);assert(main.textContent.includes('display name of up to 120 characters'));
          }
          reviewMember({name:'🦊'.repeat(120)});assert(!memberButton('Save new member').hidden);saveMember();await flush();assert.equal(writes[0].body.name,'🦊'.repeat(120));
        ''')

    def test_creation_reuses_strict_ascii_email_validation_and_blocks_listed_identity(self):
        self.run_js(r'''
          await openAdd();for(const email of ['','bad','a@b','K@example.com','ü@example.com','a..b@example.com','a@-example.com','a'.repeat(65)+'@example.com']){
            reviewMember({email});assert(memberButton('Save new member').hidden);assert(main.textContent.includes('valid sign-in email address'));}
          reviewMember({id:'user2'});assert(memberButton('Save new member').hidden);assert(main.textContent.includes('already listed'));
          reviewMember({email:'OLD@EXAMPLE.COM'});assert(memberButton('Save new member').hidden);assert(main.textContent.includes('already listed'));assert.equal(writes.length,0);
        ''')

    def test_commit_rechecks_each_field_even_without_input_events(self):
        self.run_js(r'''
          for(const [field,value] of [['name','Changed'],['id','changed'],['email','changed@example.com']]){
            await openAdd();reviewMember();newField(field,value,false);saveMember();await flush();assert.equal(writes.length,0);
            assert(main.textContent.includes('Review the member again'));assert(memberButton('Save new member').hidden);
          }
        ''')

    def test_native_input_invalidates_review_without_replacing_controls_or_focus(self):
        self.run_js(r'''
          const form=await openAdd();reviewMember();const input=byId('settings-member-add-name');input.focus();newField('name','Changed');
          assert(memberButton('Save new member').hidden);assert(form.querySelector('.settings-member-review').hidden);assert.equal(document.activeElement,input);
          assert.equal(byId('settings-member-add-name'),input);assert.equal(writes.length,0);
        ''')

    def test_pending_creation_disables_mode_switch_and_prevents_duplicate_writes(self):
        self.run_js(r'''
          await openAdd();let finish;apiWrite=async(path,body)=>{writes.push(body);return new Promise(done=>{finish=done;});};reviewMember();saveMember();
          const form=main.querySelector('.settings-member-add-form'),back=memberButton('Back to email changes');assert(back.disabled);back.fire('click');
          saveMember();form.fire('submit');assert.equal(main.querySelector('.settings-member-add-form'),form);assert.equal(writes.length,1);
          finish(created(writes[0]));await flush();back.fire('click');assert.equal(main.querySelector('.settings-member-add-form'),form);assert(main.textContent.includes('Member added.'));
        ''')

    def test_pending_email_replacement_cannot_switch_to_creation(self):
        self.run_js(r'''
          await openMembers();let finish;apiWrite=async(path,body)=>{writes.push(body);return new Promise(done=>{finish=done;});};reviewEmail();saveEmail();
          const add=memberButton('Add member');assert(add.disabled);add.fire('click');assert.equal(main.querySelector('.settings-member-add-form'),null);
          finish(confirmed(writes[0]));await flush();add.fire('click');assert.equal(main.querySelector('.settings-member-add-form'),null);assert.equal(writes.length,1);
        ''')

    def test_stale_creation_retains_entries_and_requires_reload_before_either_flow(self):
        self.run_js(r'''
          await openAdd();apiWrite=async(path,body)=>{writes.push(body);throw Object.assign(Error('stale'),{status:409});};reviewMember();saveMember();await flush();
          assert.equal(byId('settings-member-add-email').value,'member@example.com');assert(main.textContent.includes('saved member settings changed'));
          memberButton('Back to email changes').fire('click');saveMember();main.querySelector('.settings-member-add-form').fire('submit');assert.equal(writes.length,1);
          memberButton('Reload member emails').click();await flush();assert.equal(reads.length,2);assert(byId('settings-member-new-email'));assert.equal(byId('settings-member-add-email'),null);
        ''')

    def test_uncertain_creation_never_retries_or_claims_success(self):
        self.run_js(r'''
          await openAdd();apiWrite=async(path,body)=>{writes.push(body);throw Error('lost reply');};reviewMember();saveMember();await flush();
          assert(main.textContent.includes("save couldn't be confirmed"));assert(!main.textContent.includes('Member added.'));assert(memberButton('Back to email changes').disabled);
          saveMember();assert.equal(writes.length,1);assert.equal(reads.length,1);
        ''')

    def test_creation_validation_refusal_shows_static_reason_and_keeps_reload_gate(self):
        self.run_js(r'''
          await openAdd();apiWrite=async(path,body)=>{writes.push(body);throw Object.assign(Error('That member id is reserved for an existing space.'),{status:400});};
          reviewMember();saveMember();await flush();assert(main.textContent.includes('That member id is reserved for an existing space.'));
          assert(main.textContent.includes('Reload member emails before reviewing another change'));assert.equal(byId('settings-member-add-id').value,'user4');
          memberButton('Back to email changes').fire('click');saveMember();main.querySelector('.settings-member-add-form').fire('submit');
          assert.equal(writes.length,1);assert(memberButton('Save new member').hidden);assert(!memberButton('Reload member emails').hidden);assert(!main.textContent.includes('Member added.'));
        ''')

    def test_creation_unknown_server_details_and_unbounded_refusals_are_not_exposed(self):
        self.run_js(r'''
          for(const failure of [Error('private-detail-marker'),Object.assign(Error('private-detail-marker'),{status:500}),
            Object.assign(Error('private-detail-marker'),{status:503}),{status:400,message:' '},{status:400,message:7},
            {status:400,message:'private-detail-marker'+'x'.repeat(501)}]){
            await openAdd();apiWrite=async()=>{throw failure;};reviewMember();saveMember();await flush();
            assert(main.textContent.includes("save couldn't be confirmed"));assert(!main.textContent.includes('private-detail-marker'));
            assert(!main.textContent.includes('Member added.'));assert(!memberButton('Reload member emails').hidden);
          }
        ''')

    def test_malformed_creation_receipts_never_certify_a_different_or_partial_member(self):
        self.run_js(r'''
          const changes=[()=>null,reply=>({...reply,saved:false}),reply=>({...reply,noop:true}),reply=>({...reply,change_set_id:null}),reply=>({...reply,change_set_id:0}),
            reply=>({...reply,change_set_id:1.5}),reply=>({...reply,config_sha256:hashA}),reply=>({...reply,membership_sha256:hashB}),reply=>({...reply,config_sha256:'bad'}),
            reply=>({...reply,access_policy_required:false}),reply=>({...reply,member:{...reply.member,id:'wrong'}}),reply=>({...reply,member:{...reply.member,name:'Wrong'}}),
            reply=>({...reply,member:{...reply.member,emails:[]}}),reply=>({...reply,member:{...reply.member,emails:['wrong@example.com']}}),
            reply=>({...reply,member:{...reply.member,emails:['member@example.com','extra@example.com']}})];
          for(const alter of changes){await openAdd();apiWrite=async(path,body)=>alter(created(body));reviewMember();saveMember();await flush();
            assert(main.textContent.includes("save couldn't be confirmed"));assert(!main.textContent.includes('Member added.'));assert(!memberButton('Reload member emails').hidden);}
        ''')

    def test_late_creation_outcome_cannot_paint_after_profile_route_hash_or_host_changes(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','host']){
            await openAdd();let finish;apiWrite=async()=>new Promise(done=>{finish=done;});reviewMember();saveMember();const form=main.querySelector('.settings-member-add-form');
            if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='host')byId('settings-members-content').replaceWith(el('div',{id:'settings-members-content'}));
            finish(created({member_id:'user4',name:'User4',email:'member@example.com'}));await flush();assert(!form.textContent.includes('Member added.'));
            assert(!main.textContent.includes('Cloudflare Access policy, then check sign-in'));assert.equal(writes.length,0);
          }
        ''')

    def test_detached_add_mode_cannot_submit_after_return_to_email_changes(self):
        self.run_js(r'''
          const form=await openAdd();reviewMember();const save=memberButton('Save new member');memberButton('Back to email changes').click();
          save.fire('click');form.fire('submit');await flush();assert.equal(writes.length,0);assert(byId('settings-member-new-email'));assert.equal(reads.length,1);
        ''')

    def test_creation_name_is_plain_text_without_markup_or_extra_profile_fields(self):
        self.run_js(r'''
          await openAdd();reviewMember({name:'<img src=x>'});assert.equal(main.querySelector('img'),null);saveMember();await flush();
          assert.equal(main.querySelector('img'),null);assert(main.textContent.includes('<img src=x>'));assert.equal(writes[0].body.role,undefined);
          assert.equal(writes[0].body.space,undefined);assert.equal(writes[0].body.public,undefined);
        ''')


if __name__ == "__main__":
    unittest.main()
