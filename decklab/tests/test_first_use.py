"""First-use wording, aliases and guarded recovery stay independent of real installs."""
import copy
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib import profiles
from decklab.lib.api import carddata, common
from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


class FirstUseBackendTests(unittest.TestCase):
    def test_neutral_profile_aliases_normalize_without_mutating_config_or_roles(self):
        raw = [{"id": "first-player", "name": "First", "role": "admin", "plays_as": "first"},
               {"id": "second-player", "name": "Second", "role": "member", "plays_as": "second"},
               {"id": "shared-player", "name": "Shared", "role": "member", "plays_as": "either"},
               {"id": "user2", "name": "User2", "space": "user2", "role": "member", "plays_as": "second"}]
        before = copy.deepcopy(raw)
        parsed = profiles.read_checked({"profiles": raw})
        self.assertEqual([(p["plays_as"], p["role"]) for p in parsed],
                         [("user", "admin"), ("wife", "member"), ("either", "member"), (None, "member")])
        self.assertEqual(raw, before)
        old = copy.deepcopy(raw)
        old[0]["plays_as"], old[1]["plays_as"] = "user", "wife"
        self.assertEqual(profiles.read_checked({"profiles": old}), parsed)

    def test_missing_card_data_only_gives_named_admin_fixed_recovery(self):
        from decklab.lib.api import guard
        for viewer in (None, {"role": "member"}, {"role": "admin"}):
            with self.subTest(viewer=viewer), mock.patch.object(carddata, "_index_info", return_value=(None, "No card data")), \
                    mock.patch.object(guard, "viewer", return_value=viewer), \
                    mock.patch.dict(carddata.UPDATE, running=False, error="private raw failure"):
                with self.assertRaises(common.ApiError) as caught:
                    carddata._require_cards()
                message = caught.exception.message
                self.assertNotIn("private raw failure", message)
                self.assertEqual("python -m decklab.lib.cards update" in message, bool(viewer and viewer["role"] == "admin"))
                if viewer and viewer["role"] == "admin":
                    self.assertIn("decklab/data/logs/server.log", message)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class FirstUseUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_player_choices_follow_configured_profiles_and_member_permission(self):
        self.run_js("""
          as('matt',MAY.admin);state.profiles=[PROFILES[0]];
          same(allowedPlayers(),[['user','Matt']]);assert.equal(playerWords('wife'),'Second player');
          state.profiles=PROFILES;same(allowedPlayers().map(p=>p[0]),['user','wife','either']);
          as('user1',MAY.user1);same(allowedPlayers(),[['wife','User1']]);
          state.profiles=[{id:'shared',name:'Shared',plays_as:'either',space:'home',role:'member'}];
          state.profile=state.profiles[0];state.may={home_player:'either',create:[{space:'home',player:'either'}]};
          same(allowedPlayers(),[['either','Shared']]);assert.equal(newDeckPlayer('home'),'either');
        """)

    def test_empty_collection_has_four_reviewed_starts_and_stale_controls_do_nothing(self):
        self.run_js("""
          as('matt',MAY.admin);const cv={token:routeToken,profile:'matt',space:'home',editable:true};
          const calls=[];openImportSheet=()=>calls.push('import');openPreconSheet=()=>calls.push('precon');
          openScanSheet=()=>calls.push('scan');openCollectionSheet=()=>calls.push('one');
          const node=colFindEmpty(cv,false);main.append(node);
          for(const label of ['Import cards','Add a precon','Scan cards','Add one card'])button(node,label).click();
          same(calls,['import','precon','scan','one']);
          state.profile=PROFILES[1];button(node,'Import cards').click();assert.equal(calls.length,4);
          assert.equal(colFindEmpty({...cv,editable:false},false).querySelectorAll('button').length,0);
          assert.equal(colFindEmpty(cv,true).querySelectorAll('button').length,0);
        """)

    def test_import_help_names_formats_printing_requirement_and_blank_template(self):
        self.run_js("""
          as('matt',MAY.admin);const cv={token:routeToken,profile:'matt',space:'home',editable:true};
          const ctx=openImportSheet(cv),text=ctx.sheet.body.textContent;
          for(const app of ['ManaBox','Moxfield','Deckbox','Archidekt','Dragon Shield','Delver Lens','TCGplayer'])assert(text.includes(app));
          assert(text.includes('name-only list'));assert(text.includes('set and number first'));
          assert(button(ctx.sheet.body,'Download blank collection CSV'));
          for(const a of ctx.sheet.body.querySelectorAll('a'))assert.equal(a.getAttribute('rel'),'noopener noreferrer');
        """)

    def test_help_is_static_and_optional_forge_is_distinct_from_broken(self):
        self.run_js("""
          as('user2',MAY.user2);api=()=>{throw new Error('Help must not read records');};showTerminology();
          for(const word of ['Idea','Building','Built','Planned list','Play-now list','Owned vs needed','Tables out of date'])assert(main.textContent.includes(word));
          const missing=forgeBox({ready:false,installed:false,problem:'private local error'}).textContent;
          assert(missing.includes('Simulations are optional'));assert(missing.includes('SELF-HOSTING.md step 8'));
          assert(!missing.includes('private local error'));assert(!missing.includes("until it's fixed"));
          assert(forgeBox({ready:false,installed:true,problem:'Java unavailable'}).textContent.includes('Java unavailable'));
          assert(forgeBox({ready:false,problem:'Older server'}).textContent.includes('Older server'));
        """)
