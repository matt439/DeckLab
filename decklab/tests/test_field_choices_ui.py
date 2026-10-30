"""Change the field (E3-S23) with the real membership UI, a disposable DOM and deterministic answers."""
import json
import subprocess
import unittest

from decklab.tests.test_field_membership_ui import SETUP as MEMBERSHIP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = MEMBERSHIP + """
  state.profile={id:'matt',role:'admin',space:'home'};
  const editable=(extra={})=>answer({can_edit:true,...extra});
  const proof={epoch:{kind:'creation',deck_id:'casual/other',revision:1},receipt:{deck_id:'casual/other',revision:3,
    sha256:'a'.repeat(64)},version:'target',card_sha:'b'.repeat(64)};
  const reviewed=(body,extra={})=>({format:'Constructed',deck:{id:body.id,version:body.version},
    current:{mode:'legacy'},proposed:body.mode==='include'?{mode:'include',version:body.version}:{mode:body.mode},
    changed:true,reason_required:body.mode==='exclude',ready:true,message:null,
    expect:{revision:'9007199254740993',proof},...extra});
  let previews=[],saves=[],onPreview=null,onSave=null;
  apiWrite=async(path,body)=>{writes.push([path,body]);
    if(path==='/api/field/policy/preview'){previews.push(body);return onPreview?onPreview(body):reviewed(body);}
    if(path==='/api/field/policy'){saves.push(body);return onSave?onSave(body):{changed:true,format:'Constructed',revision:'1'};}
    throw new Error('Unexpected write '+path);};
  api=async path=>{calls.push(path);return editable();};
  const choices=details=>details.querySelector('[data-field-choices]');
  const pick=(details,index,mode)=>{const p=choices(details);
    const list=p.querySelector('[data-field-choice-list]'),choice=p.querySelector('[data-field-choice-mode]');
    list.value=String(index);list.fire('change');choice.value=mode;choice.fire('change');return p;};
  const button=(details,name)=>choices(details).querySelector(`[data-field-choice-${name}]`);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class FieldChoicesUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_admin_previews_then_saves_exactly_that_preview_and_membership_is_read_again(self):
        self.run_js("""
          const details=mount();expand(details);await settle();
          const p=choices(details);assert(p);assert(p.textContent.includes('Change the field'));
          const options=p.querySelector('[data-field-choice-list]').querySelectorAll('option');
          same(options.map(o=>o.textContent),['Test Deck: Planned list','Other Deck: Planned list',
            'Manual Deck: Play-now list','Removed Deck: Planned list','Other Deck: Play-now list']);
          assert.equal(p.querySelector('[data-field-choice-list]').value,'0');
          assert(button(details,'save').disabled);
          pick(details,1,'include');button(details,'preview').click();await settle();
          same(previews,[{id:'casual/other',version:'target',mode:'include'}]);
          assert(p.textContent.includes('Other Deck follows the field rules and any older hand edits now; '+
            'after saving it is included by hand (Planned list).'));
          assert(!button(details,'save').disabled);assert.equal(saves.length,0);
          button(details,'save').click();await settle();
          same(saves,[{format:'Constructed',revision:'9007199254740993',proof,mode:'include'}]);
          assert.equal(calls.length,2);
          assert(choices(details).textContent.includes('Saved: Other Deck is included by hand (Planned list).'));
          assert.notEqual(choices(details),p);
        """)

    def test_exclude_needs_a_reason_and_a_changed_choice_needs_a_new_preview(self):
        self.run_js("""
          const details=mount();expand(details);await settle();
          pick(details,1,'exclude');button(details,'preview').click();await settle();
          assert(choices(details).textContent.includes('Say why before saving'));
          button(details,'save').click();await settle();assert.equal(saves.length,0);
          assert(choices(details).textContent.includes('Say why the deck is left out before saving.'));
          choices(details).querySelector('[data-field-choice-reason]').value='  Forge pilots it badly  ';
          pick(details,1,'rules');assert(button(details,'save').disabled);button(details,'save').click();
          await settle();assert.equal(saves.length,0);
          pick(details,1,'exclude');button(details,'preview').click();await settle();
          choices(details).querySelector('[data-field-choice-reason]').value='  Forge pilots it badly  ';
          button(details,'save').click();await settle();
          same(saves,[{format:'Constructed',revision:'9007199254740993',proof,mode:'exclude',reason:'Forge pilots it badly'}]);
        """)

    def test_no_change_missing_migration_conflict_and_malformed_previews_never_save(self):
        self.run_js("""
          const details=mount();expand(details);await settle();
          onPreview=body=>reviewed(body,{changed:false,current:{mode:'include',version:'target'}});
          pick(details,1,'include');button(details,'preview').click();await settle();
          assert(choices(details).textContent.includes('Other Deck is included by hand (Planned list) already'));
          assert(button(details,'save').disabled);
          onPreview=body=>reviewed(body,{ready:false,
            message:'Field choices need the database migration: python -m decklab.db migrate'});
          button(details,'preview').click();await settle();
          assert(choices(details).textContent.includes('python -m decklab.db migrate'));assert(button(details,'save').disabled);
          onPreview=null;onSave=async()=>{throw new ApiError(409,'The field policy changed. Reload it before saving.');};
          button(details,'preview').click();await settle();button(details,'save').click();await settle();
          assert(choices(details).textContent.includes('The field policy changed. Reload it before saving.'));
          assert(button(details,'save').disabled);assert.equal(calls.length,1);
          for(const bad of [{deck:{id:'casual/test',version:'target'}},{proposed:{mode:'exclude'}},
            {expect:{revision:9,proof}},{expect:{revision:'01',proof}},{expect:{revision:'1',proof:null}},
            {format:'Commander'},{message:'x'.repeat(400),ready:false}]){
            onPreview=body=>reviewed(body,bad);button(details,'preview').click();await settle();
            assert(choices(details).textContent.includes("The change couldn't be checked. Try again."),JSON.stringify(bad));
            assert(button(details,'save').disabled);}
          onPreview=async()=>{throw new Error('SECRET database detail');};button(details,'preview').click();await settle();
          assert(!choices(details).textContent.includes('SECRET'));assert.equal(saves.length,1);
        """)

    def test_changing_the_list_or_choice_during_a_save_never_drops_its_answer(self):
        self.run_js("""
          for(const outcome of ['saved','conflict']){
            const pending=deferred();onSave=()=>pending.promise;
            const details=mount();expand(details);await settle();
            pick(details,1,'include');button(details,'preview').click();await settle();
            button(details,'save').click();await settle();
            const p=choices(details),list=p.querySelector('[data-field-choice-list]'),mode=p.querySelector('[data-field-choice-mode]');
            assert(list.disabled&&mode.disabled&&p.querySelector('[data-field-choice-reason]').disabled,outcome);
            assert(button(details,'preview').disabled&&button(details,'save').disabled,outcome);
            list.value='2';list.fire('change');mode.value='rules';mode.fire('change');
            assert(button(details,'preview').disabled,outcome);assert(p.textContent.includes('Saving the change.'),outcome);
            button(details,'preview').click();await settle();assert.equal(previews.length,1,outcome);
            if(outcome==='saved'){pending.resolve({changed:true,format:'Constructed',revision:'1'});await settle();
              assert(choices(details).textContent.includes('Saved: Other Deck is included by hand (Planned list).'));}
            else{pending.reject(new ApiError(409,'The field policy changed. Reload it before saving.'));await settle();
              assert(p.textContent.includes('The field policy changed. Reload it before saving.'));
              assert(!list.disabled&&!mode.disabled&&!button(details,'preview').disabled);
              assert(button(details,'save').disabled);}
            previews=[];onSave=null;
          }
        """)

    def test_members_and_answers_without_can_edit_get_no_controls(self):
        self.run_js("""
          api=async path=>{calls.push(path);return answer();};
          let details=mount();expand(details);await settle();assert.equal(choices(details),null);
          api=async path=>{calls.push(path);return answer({can_edit:'yes'});};
          details=mount();expand(details);await settle();assert.equal(choices(details),null);
          api=async path=>{calls.push(path);return editable({format:'Commander',
            rows:[memberRow('product/box','Box','target','default',true,true)],counts:{included:1,opponents:1,manual_excluded:0}});};
          details=mount();expand(details);await settle();assert.equal(choices(details),null);
          assert.equal(writes.length,0);
        """)

    def test_late_preview_after_profile_or_route_change_is_dropped(self):
        self.run_js("""
          for(const change of ['profile','route','refresh']){
            const pending=deferred();onPreview=()=>pending.promise;
            const details=mount();expand(details);await settle();const p=choices(details);
            pick(details,1,'include');button(details,'preview').click();
            if(change==='profile')state.profile={id:'user1',role:'member',space:'home'};
            if(change==='route')routeToken++;
            if(change==='refresh')refresh(details).click();
            pending.resolve(reviewed({id:'casual/other',version:'target',mode:'include'}));await settle();
            assert(!p.textContent.includes('after saving'),change);
            p.querySelector('[data-field-choice-save]').click();await settle();assert.equal(saves.length,0,change);
            state.profile={id:'matt',role:'admin',space:'home'};routeToken=9;
          }
        """)
