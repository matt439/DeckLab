"""Secret Lair drops use one reviewed collection/token import and never create a deck."""
import copy
import unittest
from unittest import mock

from decklab.lib import cards, inventory, sealed
from decklab.lib.api import precons as api
from decklab.lib.inventory import files, ops_decks
from decklab.lib.tokens import ops as token_ops
from decklab.tests import test_precon_cli, test_precon_tokens_ui, test_precons


DROP = {"data": {"name": "Some Drop", "code": "SLD", "type": "Secret Lair Drop",
    "mainBoard": [test_precons.card("Llanowar Elves", "FDN", "227", 2),
                  test_precons.card("Elvish Mystic", "CMM", "648")],
    "tokens": [{"name": "Dinosaur", "count": 2}]}}
CONTENT = {"products": ["Synthetic Secret Lair box"], "fixed": [
    {"name": "Pick Your Poison", "set": "mkm", "number": "170", "finish": "foil", "count": 1}],
    "random": [], "varies": [], "other": []}


class DropTests(test_precons.PreconTestCase):
    def setUp(self):
        super().setUp()
        self.seed("decks/SomeDrop_SLD.json", DROP)
        sealed.contents.return_value = copy.deepcopy(CONTENT)
        self.enterContext(mock.patch.object(cards, "token_face", side_effect=lambda name:
                          "Dinosaur" if cards.fold(name) == "dinosaur" else None))

    def preview(self, space="user2"):
        return api.precon_preview("SomeDrop_SLD", space)

    def add_drop(self, *, space="user2", profile=None, add_tokens=False, **extra):
        view = self.preview(space)
        data = {"title": view["title"], "sha256": view["sha256"], "bonus_choices": [1],
                "bonus_source_sha256": view["bonus_import"]["source_sha256"], **extra}
        if add_tokens:
            data.update(add_tokens=True, tokens_sha256=view["token_import"]["sha256"],
                        tokens_source_sha256=view["token_import"]["source_sha256"])
        return self.add("SomeDrop_SLD", space, profile=profile, **data)

    def test_product_search_and_preview_are_cards_only_without_any_deck_validation(self):
        self.assertEqual(api.precons_view("drop", products="1")["decks"][0]["file"], "SomeDrop_SLD")
        self.assertEqual(api.precons_view("drop")["decks"], [])
        with mock.patch.object(api.drafts, "_read_draft", side_effect=AssertionError("drop validated as a deck")), \
                mock.patch.object(api.decks, "existing_deck_id", side_effect=AssertionError("drop probed a deck name")):
            view = self.preview()
        self.assertTrue(view["cards_only"])
        self.assertIsNone(view["exists"])
        self.assertEqual(view["deck_problems"], [])
        self.assertEqual(view["adds"]["cards"], 4)
        self.assertEqual(self.writes_made(), 0)

    def test_drop_bonus_and_raw_import_save_in_one_change_without_a_deck_or_history(self):
        before = inventory.current()
        before_decks = before.decks
        with self.as_("user2"), mock.patch.object(ops_decks, "create", side_effect=AssertionError("drop created a deck")):
            answer = self.add_drop()
        self.assertTrue(answer["cards_only"])
        self.assertIsNone(answer["deck"])
        self.assertEqual(answer["collection"]["added"], {"cards": 4, "rows": 2})
        self.assertIn("stale_tables", answer)
        self.assertEqual(answer["trials"], [])
        self.assertEqual(self.writes_made(), 1)
        self.assertEqual(inventory.current().decks, before_decks)
        self.assertEqual(self.writes[0][3].counts["decks"], 0)
        self.assertEqual(inventory.current().collection("home"), before.collection("home"))
        rows = {row["name"]: row for row in self.rows("user2")["rows"]}
        for name in ("Elvish Mystic", "Pick Your Poison"):
            self.assertEqual((rows[name]["condition"], rows[name]["language"]), ("", ""))
        self.assertEqual(rows["Pick Your Poison"]["notes"], "bonus card in Some Drop")
        self.assertIn("Some Drop drop", rows["Elvish Mystic"]["notes"])
        raw = (self.box.magic / "people/user2/imports/2026-10-10-sld-some-drop.csv").read_text(encoding="utf-8")
        self.assertIn("Pick Your Poison,mkm,170,foil,1,,,bonus card in Some Drop", raw)
        self.assertEqual(answer["collection"]["filing"]["status"], "ready")
        self.assertEqual(sum(row["quantity"] for row in answer["collection"]["filing"]["added"]), 4)

    def test_optional_tokens_are_atomic_and_keep_physical_details_unknown(self):
        answer = self.add_drop(add_tokens=True)
        self.assertEqual(answer["tokens"], {"cards": 2, "rows": 1})
        self.assertEqual(self.writes_made(), 1)
        rows = inventory.current().token_set("user2").rows
        self.assertEqual([(row["front"], row["quantity"]) for row in rows], [("Dinosaur", "2")])
        self.assertTrue(all(not rows[0][key] for key in ("set", "finish", "back", "front_collector_number")))
        self.assertIsNone(answer["deck"])

    def test_late_token_refusal_rolls_back_cards_bonus_raw_import_and_audit(self):
        before = files.render(inventory.current())
        with mock.patch.object(token_ops, "add", side_effect=inventory.Invalid("Synthetic late token refusal")):
            self.assertApiError(400, self.add_drop, add_tokens=True)
        self.assertEqual(files.render(inventory.current()), before)
        self.assertEqual(self.writes_made(), 0)

    def test_source_receipt_binds_the_base_list_and_cards_only_type(self):
        view = self.preview()
        for change in ("cards", "type"):
            with self.subTest(change=change):
                if change == "cards":
                    changed = copy.deepcopy(DROP)
                    changed["data"]["mainBoard"][0]["count"] = 3
                    self.seed("decks/SomeDrop_SLD.json", changed)
                else:
                    self.seed("decks/SomeDrop_SLD.json", DROP)
                    listed = copy.deepcopy(test_precons.DECK_LIST)
                    next(row for row in listed["data"] if row["fileName"] == "SomeDrop_SLD")["type"] = "Theme Deck"
                    self.seed("DeckList.json", listed)
                self.assertApiError(409, self.add_drop, bonus_source_sha256=view["bonus_import"]["source_sha256"])
        self.assertEqual(self.writes_made(), 0)

    def test_card_edit_permission_suffices_and_other_spaces_still_refuse_before_source_reads(self):
        allowed = api.guard.allowed
        with self.as_("user2"), mock.patch.object(api.guard, "allowed", side_effect=lambda person, action, target=None:
                                                 False if action == "deck.create" else allowed(person, action, target)):
            self.assertTrue(self.preview()["editable"])
            self.add_drop()
        sealed.contents.reset_mock()
        with self.as_("matt"):
            self.assertApiError(403, api.precon_preview, "SomeDrop_SLD", "user2")
            self.assertApiError(403, self.call, api.add_precon, "matt", space="user2", file="SomeDrop_SLD",
                                title="ignored", sha256="0" * 64)
        sealed.contents.assert_not_called()

    def test_deck_fields_are_refused_and_empty_bonus_selection_can_explicitly_skip(self):
        self.assertApiError(400, self.add_drop, fields={"status": "built"})
        self.assertEqual(self.writes_made(), 0)
        answer = self.add_drop(bonus_choices=[])
        self.assertEqual(answer["collection"]["added"]["cards"], 3)
        self.assertIsNone(answer["deck"])

    def test_empty_source_list_is_not_offered_as_a_complete_drop_import(self):
        changed = copy.deepcopy(DROP)
        changed["data"]["mainBoard"] = []
        self.seed("decks/SomeDrop_SLD.json", changed)
        view = self.preview()
        self.assertFalse(view["ready"])
        self.assertIn("no published card list", view["problems"][0]["message"])
        self.assertApiError(400, self.add_drop)
        self.assertEqual(self.writes_made(), 0)

    def run_cli(self, *args):
        return test_precon_cli.CommandLineTests.run_cli(self, *args)

    def test_cli_previews_and_adds_cards_only_in_members_space(self):
        args = ("add-precon", "SomeDrop_SLD", "--space", "user2", "-m", "Add requested drop")
        code, out, err = self.run_cli(*args, "--dry-run")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Cards only; no deck would be created.", out)
        self.assertEqual(self.writes_made(), 0)
        code, out, err = self.run_cli(*args, "--bonus-cards", "include", "--add-tokens")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 4 cards", out)
        self.assertIn("No deck was created.", out)
        self.assertIn("Added 2 token cards", out)
        self.assertEqual(self.writes_made(), 1)

    def test_home_cli_actor_defaults_do_not_create_player_details_for_drop(self):
        code, out, err = self.run_cli("add-precon", "SomeDrop_SLD", "-m", "Add requested drop", "--actor", "matt",
                                      "--bonus-cards", "skip")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("No deck was created.", out)
        self.assertEqual(self.last_write(), ("Add requested drop", "Matt"))
        self.assertEqual(self.run_cli("add-precon", "SomeDrop_SLD", "-m", "Bad deck option", "--title", "Deck")[0], 1)


@unittest.skipUnless(test_precon_tokens_ui.NODE, "Node.js is not installed")
class DropUiTests(unittest.TestCase):
    def run_js(self, scenario):
        test_precon_tokens_ui.PreconTokensUiTests.run_js(self, r'''
          const drop=extra=>preview({cards_only:true,title:'Fixture drop',
            deck:{file:'Drop_SLD',name:'Fixture drop',code:'sld',type:'Secret Lair Drop'},
            bonus_import:{source_sha256:'d'.repeat(64),rows:[{source_row:1,qty:1,words:'Fixture bonus (SLD 1, foil)',
              owned:0,selected:true,problem:null}]},...extra});
          const dropAnswer=extra=>({cards_only:true,deck:null,collection:{added:{rows:1,cards:4}},stale_tables:[],trials:[],...extra});
        ''' + scenario)

    def test_cards_only_preview_and_success_never_navigate_to_or_construct_a_deck(self):
        self.run_js(r'''
          const ctx=await open(drop());assert(ctx.area.textContent.includes('Cards only; no deck is created'));
          assert.equal(ctx.area.querySelectorAll('.precon-title').length,0);
          const writes=[],reloads=[];apiWrite=async(path,body)=>{writes.push(body);return dropAnswer();};
          colReload=(...args)=>reloads.push(args);await addPrecon(ctx);
          assert.equal(writes.length,1);assert.equal(writes[0].file,'Drop_SLD');same(writes[0].bonus_choices,[1]);
          assert.equal(state.saved,null);assert.equal(location.hash,'#/collection');assert.equal(reloads.length,0);
          assert(ctx.message.textContent.includes('4 cards from Fixture drop added'));
          assert(ctx.message.textContent.includes('No deck was created'));assert(!ctx.sheet.closed);
          assert(!addButton(ctx));await addPrecon(ctx);assert.equal(writes.length,1);
          textButton(ctx,'Close').click();assert(ctx.sheet.closed);assert.equal(reloads.length,1);
          assert(reloads[0][1].includes('No deck was created'));
        ''')

    def test_drop_opted_in_tokens_use_the_same_explicit_receipts_and_confirmation(self):
        self.run_js(r'''
          const ctx=await open(drop());choose(ctx);let body;
          apiWrite=async(path,payload)=>{body=payload;return dropAnswer({tokens:{cards:3,rows:2}});};await addPrecon(ctx);
          assert.equal(body.add_tokens,true);assert.equal(body.tokens_sha256,'a'.repeat(64));
          assert.equal(body.tokens_source_sha256,'c'.repeat(64));assert.equal(body.bonus_source_sha256,'d'.repeat(64));
          assert(ctx.area.textContent.includes('3 token cards also added as unconfirmed rows'));assert.equal(state.saved,null);
        ''')

    def test_unconfirmed_cards_only_answer_and_lost_reply_do_not_allow_repeated_add(self):
        self.run_js(r'''
          for(const mode of ['unconfirmed','lost']){
            const ctx=await open(drop());let writes=0;apiWrite=async()=>{writes++;if(mode==='lost')throw Error('Lost reply');return added();};
            await addPrecon(ctx);assert(ctx.tokenPreviewStale);assert(!addButton(ctx));await addPrecon(ctx);assert.equal(writes,1);
            assert(ctx.message.textContent.includes("isn't known"));assert(!ctx.message.textContent.includes('Decks page'));
            assert.equal(state.saved,null);
          }
        ''')

    def test_late_success_cannot_show_a_drop_receipt_in_another_profile_or_route(self):
        self.run_js(r'''
          for(const mode of ['profile','route']){
            const ctx=await open(drop());let resolve;apiWrite=()=>new Promise(done=>resolve=done);const pending=addPrecon(ctx);
            if(mode==='profile')state.profile=PROFILES[1];else routeToken++;
            resolve(dropAnswer());await pending;assert(!ctx.dropReceipt);assert.equal(state.saved,null);
          }
        ''')
