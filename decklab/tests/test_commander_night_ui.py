"""Dated home Commander-night notes and their guarded Settings form.

Real page scripts over deterministic DOM/events; no browser, server or data writes.
"""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELL + r"""
  const recorded = () => ({name:'Tuesday social',venue:'Fixture venue',target_bracket:2,
    published_min:1,published_max:4,house_rules:'Ask the table first.\nKeep notes short.',checked_on:'2026-10-13'});
  const savedNight = (night = recorded(), revision = 3) => ({night,revision,can_edit:true});
  const deckNight = (night = recorded(), target = 2) => ({summary:{id:'commander/fixture',kind:'commander',target_bracket:target},
    stats:null,commander_night:savedNight(night)});
  const plainApi = api;
  let nightReply = savedNight(), sent = [];
  api = async (path) => path === '/api/commander-night' ? nightReply : plainApi(path);
  apiWrite = async (path, body, method) => {sent.push({path,body,method}); return savedNight(body.night,body.expect+1);};
  showFooter = () => {};
  const openNightSettings = async (night = recorded(), revision = 3) => {
    as('matt',false); location.hash = '#/settings'; nightReply = savedNight(night,revision);
    showSettings(new URLSearchParams(),routeToken); await flush();
    return main.querySelector('.commander-night-form');
  };
  const nightButton = (text) => main.querySelectorAll('button').find((node) => node.textContent === text);
  const fieldValue = (id,value) => { const input = byId(id); input.value = value; input.fire('input'); return input; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CommanderNightUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_home_deck_notes_compare_household_target_and_keep_published_range_separate(self):
        self.run_js(r"""
          as('user1',false);
          const data = deckNight(), note = commanderNightPart(data);
          assert(note.textContent.includes('Tuesday social'));
          assert(note.textContent.includes('Venue: Fixture venue'));
          assert(note.textContent.includes('Household aim: Bracket 2'));
          assert(note.textContent.includes('Published venue range: Brackets 1–4'));
          assert(note.textContent.includes("target matches the household's Bracket 2 aim"));
          assert(note.textContent.includes('Last checked: 2026-10-13'));
          assert(note.textContent.includes('does not enforce house rules'));
          assert(note.textContent.includes("does not enforce house rules or establish that the deck meets the night's expectations"));
          data.summary.target_bracket = 4;
          assert(commanderNightPart(data).textContent.includes('This deck targets Bracket 4; the household aims for Bracket 2'));
          const readiness = commanderReadiness(data);
          assert(readiness.querySelector('.commander-night'));
          assert(readiness.textContent.includes('Commander checks are unavailable'));
          assert.equal(sent.length,0);
        """)

    def test_range_only_unknowns_and_plain_text_never_invent_an_aim_or_rules(self):
        self.run_js(r"""
          as('matt',false);
          const night = {...recorded(),target_bracket:null,house_rules:'<img src=x onerror=alert(1)>\nSecond line',checked_on:''};
          const data = deckNight(night,3), note = commanderNightPart(data);
          assert(note.textContent.includes('No household target recorded'));
          assert(note.textContent.includes('target Bracket 3 is within the recorded venue range'));
          assert(note.textContent.includes('Checked date unknown'));
          assert.equal(note.querySelector('img'),null);
          assert.equal(note.querySelector('.commander-night-rules').textContent,night.house_rules);
          data.summary.target_bracket = 5;
          assert(commanderNightPart(data).textContent.includes('outside the recorded venue range'));
          delete data.summary.target_bracket;
          assert(commanderNightPart(data).textContent.includes('This deck has no target bracket recorded'));
          Object.assign(night,{published_min:null,published_max:null,venue:'',house_rules:''});
          const unknown = commanderNightPart(data);
          assert(unknown.textContent.includes('No published bracket range recorded'));
          assert.equal(unknown.querySelector('.commander-night-rules'),null);
          Object.assign(night,{published_min:2,published_max:2});
          assert(commanderNightPart(data).textContent.includes('Published venue bracket: 2'));
        """)

    def test_projection_is_quiet_when_absent_and_defends_home_boundaries(self):
        self.run_js(r"""
          as('matt',false);
          const data = deckNight(); delete data.commander_night;
          assert.equal(commanderNightPart(data),null);
          data.commander_night = savedNight(null);
          assert.equal(commanderNightPart(data),null);
          data.commander_night = {unavailable:true};
          assert(commanderNightPart(data).textContent.includes("recorded Commander night couldn't be loaded"));
          data.commander_night = savedNight(); data.summary.kind = 'casual';
          assert.equal(commanderNightPart(data),null);
          data.summary.kind = 'commander'; data.summary.id = 'user2/commander/fixture';
          assert.equal(commanderNightPart(data),null);
          data.summary.id = 'commander/fixture'; as('user2');
          assert.equal(commanderNightPart(data),null);
          assert.equal(commanderNightSettings(),null);
          as('user1',false); assert.equal(commanderNightSettings(),null);
          assert.equal(sent.length,0);
        """)

    def test_settings_has_labelled_blank_fields_and_never_defaults_target_or_check_date(self):
        self.run_js(r"""
          const form = await openNightSettings(null,0);
          assert(form);
          for (const id of ['night-name','night-venue','night-target','night-published-min','night-published-max','night-rules','night-checked']) {
            assert.equal(byId(id).value,'',id);
            assert(main.querySelectorAll('label').some((label) => label.getAttribute('for') === id),id);
          }
          assert.equal(byId('night-name').getAttribute('required'),'');
          assert.equal(byId('night-name').getAttribute('maxlength'),'240');
          assert.equal(byId('night-rules').getAttribute('maxlength'),'3000');
          assert(main.textContent.includes("Saving doesn't mark these notes as checked today"));
          assert.equal(nightButton('Remove recorded night'),undefined);
          as('user1',false); showSettings(new URLSearchParams(),routeToken);
          assert.equal(main.querySelector('#settings-commander-night'),null);
        """)

    def test_save_sends_only_entered_values_and_observed_revision(self):
        self.run_js(r"""
          const form = await openNightSettings(null,0);
          fieldValue('night-name','  Fixture social  '); fieldValue('night-venue','Fixture table');
          fieldValue('night-target','2'); fieldValue('night-published-min','1'); fieldValue('night-published-max','4');
          fieldValue('night-rules','Ask first.\nNo automatic rules.'); fieldValue('night-checked','2026-10-12');
          form.fire('submit'); await flush();
          same(sent,[{path:'/api/commander-night',method:'PUT',body:{profile:'matt',expect:0,night:{
            name:'Fixture social',venue:'Fixture table',target_bracket:2,published_min:1,published_max:4,
            house_rules:'Ask first.\nNo automatic rules.',checked_on:'2026-10-12'}}}]);
          assert(main.textContent.includes('Commander night saved.'));
          assert.equal(byId('night-checked').value,'2026-10-12');
          assert(nightButton('Remove recorded night'));
          const next = main.querySelector('.commander-night-form');
          fieldValue('night-target',''); fieldValue('night-published-min',''); fieldValue('night-published-max','');
          fieldValue('night-checked',''); next.fire('submit'); await flush();
          assert.equal(sent[1].body.expect,1);
          same([sent[1].body.night.target_bracket,sent[1].body.night.published_min,sent[1].body.night.published_max,
            sent[1].body.night.checked_on],[null,null,null,'']);
        """)

    def test_validation_and_failed_save_keep_edits_without_a_success_claim(self):
        self.run_js(r"""
          const form = await openNightSettings(null,0);
          form.fire('submit'); await flush(); assert.equal(sent.length,0);
          assert(form.textContent.includes('Enter a night name'));
          fieldValue('night-name','Local fixture'); fieldValue('night-published-min','2');
          form.fire('submit'); await flush(); assert.equal(sent.length,0);
          assert(form.textContent.includes('Choose both ends'));
          fieldValue('night-published-max','1'); form.fire('submit'); await flush(); assert.equal(sent.length,0);
          fieldValue('night-published-max','3'); fieldValue('night-target','6');
          form.fire('submit'); await flush(); assert.equal(sent.length,0);
          fieldValue('night-target','2'); fieldValue('night-rules','x'.repeat(1501));
          form.fire('submit'); await flush(); assert.equal(sent.length,0);
          fieldValue('night-rules','Kept draft');
          apiWrite = async () => { throw new ApiError(503,'Database unavailable'); };
          form.fire('submit'); await flush();
          assert.equal(byId('night-rules').value,'Kept draft');
          assert(form.textContent.includes("couldn't be saved: Database unavailable"));
          assert(!form.textContent.includes('Commander night saved.'));
          assert.equal(nightButton('Save Commander night').disabled,false);
        """)

    def test_unicode_notes_and_labels_round_trip_without_changing_unknown_fields(self):
        self.run_js(r"""
          const form = await openNightSettings(null,0);
          const name = '\u{1f331}'.repeat(120), venue = '\u00e9'.repeat(120), rules = '\u{1f331}'.repeat(1500);
          fieldValue('night-name',name); fieldValue('night-venue',venue); fieldValue('night-rules',rules);
          form.fire('submit'); await flush();
          assert.equal(sent.length,1);
          assert.equal(sent[0].body.night.name,name);
          assert.equal(sent[0].body.night.venue,venue);
          assert.equal(sent[0].body.night.house_rules,rules);
          assert.equal(byId('night-rules').value,rules);
          same([sent[0].body.night.target_bracket,sent[0].body.night.published_min,sent[0].body.night.published_max,
            sent[0].body.night.checked_on],[null,null,null,'']);
        """)

    def test_concurrent_save_preserves_inputs_and_requires_explicit_reload(self):
        self.run_js(r"""
          const form = await openNightSettings(); fieldValue('night-rules','Unsaved draft');
          apiWrite = async () => {throw new ApiError(409,'Changed elsewhere');};
          form.fire('submit'); await flush();
          assert.equal(byId('night-rules').value,'Unsaved draft');
          assert(main.textContent.includes('Your edits are still here'));
          assert.equal(nightButton('Save Commander night').disabled,true);
          assert.equal(nightButton('Remove recorded night').disabled,true);
          const reload = nightButton('Load current saved note'); assert.equal(reload.hidden,false);
          nightReply = savedNight({...recorded(),house_rules:'Saved elsewhere'},4);
          reload.click(); await flush();
          assert.equal(byId('night-rules').value,'Saved elsewhere');
          assert.equal(nightButton('Save Commander night').disabled,false);
        """)

    def test_removal_requires_reason_and_confirmation_then_clears_the_saved_night(self):
        self.run_js(r"""
          await openNightSettings(); const remove = nightButton('Remove recorded night');
          remove.click(); await flush(); assert.equal(sent.length,0);
          fieldValue('night-remove-reason','No longer our usual night'); remove.click(); await flush();
          assert.equal(sent.length,0);
          const confirm = main.querySelector('.commander-night-form').querySelector('[type=checkbox]');
          confirm.checked = true; remove.click(); await flush();
          same(sent,[{path:'/api/commander-night',method:'PUT',body:{profile:'matt',expect:3,night:null,
            reason:'No longer our usual night'}}]);
          assert(main.textContent.includes('Recorded Commander night removed.'));
          assert.equal(byId('night-name').value,''); assert.equal(nightButton('Remove recorded night'),undefined);
        """)

    def test_pending_save_blocks_duplicate_requests_and_does_not_redraw_after_route_or_profile_change(self):
        self.run_js(r"""
          for (const move of ['route','profile','detached']) {
            const form = await openNightSettings(); let resolve, count = 0;
            apiWrite = () => {count += 1; return new Promise((done) => {resolve = done;});};
            form.fire('submit'); form.fire('submit'); await flush();
            assert.equal(count,1); assert.equal(byId('night-name').disabled,true);
            assert.equal(nightButton('Remove recorded night').disabled,true);
            if (move === 'route') routeToken += 1;
            if (move === 'profile') state.profile = PROFILES[2];
            if (move === 'detached') clear(main);
            resolve(savedNight({...recorded(),house_rules:'Late private reply'},4)); await flush();
            assert(!main.textContent.includes('Late private reply'),move);
            assert(!main.textContent.includes('Commander night saved.'),move);
            form.fire('submit'); await flush(); assert.equal(count,1,move);
          }
        """)

    def test_late_load_and_replaced_request_cannot_overwrite_the_current_form(self):
        self.run_js(r"""
          as('matt',false); location.hash = '#/settings';
          const loads = []; api = (path) => path === '/api/commander-night' ? new Promise((resolve) => loads.push(resolve)) : plainApi(path);
          showSettings(new URLSearchParams(),routeToken); await flush();
          const oldHost = byId('commander-night-settings');
          const second = loadCommanderNightSettings(routeToken); await flush();
          loads[1](savedNight({...recorded(),house_rules:'Current note'},5)); await second;
          fieldValue('night-rules','Current unsaved edit');
          loads[0](savedNight({...recorded(),house_rules:'Old note'},3)); await flush();
          assert.equal(byId('night-rules').value,'Current unsaved edit');
          const later = loadCommanderNightSettings(routeToken); await flush();
          as('user2'); loads[2](savedNight({...recorded(),house_rules:'Private late note'},6)); await later;
          assert(!oldHost.textContent.includes('Private late note'));
          assert(!main.textContent.includes('Private late note'));
        """)

    def test_load_error_can_retry_and_server_permission_denial_offers_no_form(self):
        self.run_js(r"""
          as('matt',false); location.hash = '#/settings';
          api = async (path) => {if (path === '/api/commander-night') throw new ApiError(503,'Database unavailable'); return plainApi(path);};
          showSettings(new URLSearchParams(),routeToken); await flush();
          assert(main.textContent.includes("couldn't be loaded: Database unavailable"));
          assert.equal(main.querySelector('.commander-night-form'),null);
          api = async (path) => path === '/api/commander-night' ? {night:null,revision:0,can_edit:false} : plainApi(path);
          nightButton('Try again').click(); await flush();
          assert(main.textContent.includes("can't be edited here"));
          assert.equal(main.querySelector('.commander-night-form'),null);
        """)


if __name__ == "__main__":
    unittest.main()
