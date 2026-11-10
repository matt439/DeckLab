"""Fixed precon bonus cards stay collection-only, reviewed and atomic (E7-S39)."""
import copy
import unittest
from unittest import mock

from decklab.lib import inventory, precons, sealed
from decklab.lib.api import precons as api
from decklab.lib.inventory import ops_decks
from decklab.tests import test_precon_cli, test_precon_tokens_ui
from decklab.tests.test_precons import PreconTestCase


CONTENTS = {"products": ["Fixture box"], "fixed": [
    {"name": "Pick Your Poison", "set": "mkm", "number": "170", "finish": "foil", "count": 2},
    {"name": "Llanowar Elves", "set": "fdn", "number": "227", "finish": "nonfoil", "count": 1}],
    "varies": [], "random": ["a 2-card sample pack"], "other": ["Deck box"]}
READ_CONTENTS = sealed.contents


class BonusTests(PreconTestCase):
    def setUp(self):
        super().setUp()
        self.contents = copy.deepcopy(CONTENTS)
        sealed.contents.return_value = self.contents

    def reviewed(self, choices=(1,), **extra):
        view = api.precon_preview("TestDinos_TST", "user2")
        return self.add(bonus_choices=list(choices), bonus_source_sha256=view["bonus_import"]["source_sha256"], **extra)

    def test_preview_defaults_by_exact_printing_in_its_own_space_and_names_random_contents(self):
        view = api.precon_preview("TestDinos_TST", "user2")
        first, second = view["bonus_import"]["rows"]
        self.assertEqual((first["selected"], first["owned"], first["qty"], first["finish"]), (True, 0, 2, "foil"))
        self.assertEqual((second["selected"], second["owned"]), (False, 2))
        self.assertEqual(view["adds"]["cards"], 7)
        self.assertEqual(view["counts"], {"Commander": 1, "Deck": 24})
        self.assertTrue(any("a 2-card sample pack (random, not added)" in note for note in view["notes"]))
        self.assertNotIn(api.precons.RANDOM_NOTE, view["notes"])
        self.assertEqual(api.precon_preview("TestDinos_TST", "user3")["bonus_import"]["rows"][1]["owned"], 0)
        self.assertTrue(all(call.kwargs["fetch"] for call in sealed.contents.call_args_list))

    def test_bonus_cards_save_with_raw_import_and_deck_in_one_change_without_becoming_deck_lines(self):
        before = self.writes_made()
        with self.as_("user2"):
            answer = self.reviewed()
        self.assertEqual(self.writes_made(), before + 1)
        self.assertEqual(answer["collection"]["added"]["cards"], 7)
        row = next(row for row in self.rows("user2")["rows"] if row["name"] == "Pick Your Poison")
        self.assertEqual((row["set"], row["collector_number"], row["finish"], row["quantity"]), ("mkm", "170", "foil", "2"))
        self.assertEqual((row["condition"], row["language"], row["notes"]), ("", "", "bonus card in Test Dinos"))
        folder = self.box.magic / "people" / "user2"
        raw = (folder / "imports" / "2026-10-10-tst-test-dinos.csv").read_text(encoding="utf-8")
        self.assertIn("Pick Your Poison,mkm,170,foil,2,,,bonus card in Test Dinos", raw)
        text = (folder / "decks" / "commander" / "ghalta-test-dinos.md").read_text(encoding="utf-8")
        self.assertNotIn("Pick Your Poison", text)
        self.assertNotIn("sample pack", raw)
        self.assertFalse(sealed.contents.call_args.kwargs["fetch"])

    def test_explicit_skip_adds_only_the_deck_and_ordinary_precon_cards(self):
        answer = self.reviewed(choices=())
        self.assertEqual(answer["collection"]["added"]["cards"], 5)
        self.assertFalse(any(row["name"] == "Pick Your Poison" for row in self.rows("user2")["rows"]))

    def test_real_sealed_reader_uses_kept_extract_in_preview_and_save_without_network(self):
        product = "00000001-0000-0000-0000-000000000000"
        self.seed("sealed/TST.json", {"version": sealed.VERSION, "code": "TST", "date": "2026-11-10",
            "products": {product: {"name": "Fixture box", "decks": ["Test Dinos"],
                                   "fixed": self.contents["fixed"], "random": self.contents["random"], "other": []}},
            "decks": [{"name": "Test Dinos", "products": [product], "printings": []}]})
        precons._fetch.reset_mock()
        with mock.patch.object(sealed, "contents", side_effect=READ_CONTENTS):
            answer = self.reviewed()
        self.assertEqual(answer["collection"]["added"]["cards"], 7)
        precons._fetch.assert_not_called()

    def test_deck_failure_after_bonus_merge_rolls_back_collection_raw_import_and_deck(self):
        before = self.magic_files()
        with mock.patch.object(ops_decks, "create", side_effect=inventory.Invalid("Fixture final deck failure")) as create:
            self.assertApiError(400, self.reviewed, contains="Fixture final deck failure")
        create.assert_called_once()
        merged = create.call_args.args[0]
        self.assertTrue(any(row["name"] == "Pick Your Poison" for row in merged.collection("user2").rows))
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes_made(), 0)

    def test_missing_changed_or_unavailable_source_never_adds_anything(self):
        before = self.magic_files()
        self.assertApiError(400, self.add, contains="Choose the bonus cards")
        view = api.precon_preview("TestDinos_TST", "user2")
        receipt = view["bonus_import"]["source_sha256"]
        self.contents["fixed"][0]["count"] = 3
        error = self.assertApiError(409, self.add, bonus_choices=[1], bonus_source_sha256=receipt)
        self.assertTrue(error.extra["bonus_conflict"])
        sealed.contents.return_value = None
        self.assertApiError(409, self.add, title="An explicit title", bonus_choices=[], bonus_source_sha256=receipt)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes_made(), 0)

    def test_bad_selection_or_receipt_is_refused_without_a_partial_import(self):
        receipt = api.precon_preview("TestDinos_TST", "user2")["bonus_import"]["source_sha256"]
        for choices in ([1, 1], [0], [3], [True], "include"):
            with self.subTest(choices=choices):
                self.assertApiError(400, self.add, bonus_choices=choices, bonus_source_sha256=receipt)
        self.assertApiError(400, self.add, bonus_choices=[1])
        self.assertEqual(self.writes_made(), 0)

    def test_collection_change_at_apply_preserves_atomic_refusal(self):
        view = api.precon_preview("TestDinos_TST", "user2")
        original = self.backend.apply
        def changed(op, *args, **kwargs):
            path = self.box.magic / "people" / "user2" / "collection.csv"
            path.write_text(path.read_text(encoding="utf-8").replace(",2,NM,en,", ",3,NM,en,"), encoding="utf-8")
            return original(op, *args, **kwargs)
        self.backend.apply = changed
        self.assertApiError(409, self.add, sha256=view["sha256"], bonus_choices=[1],
                            bonus_source_sha256=view["bonus_import"]["source_sha256"])
        folder = self.box.magic / "people" / "user2"
        self.assertFalse((folder / "imports").exists())
        self.assertFalse((folder / "decks").exists())
        self.assertEqual(self.writes_made(), 0)

    def test_invalid_optional_printing_can_be_skipped_but_is_never_substituted(self):
        self.contents["fixed"][0]["number"] = "999"
        view = api.precon_preview("TestDinos_TST", "user2")
        self.assertTrue(view["ready"])
        self.assertFalse(view["bonus_import"]["rows"][0]["selected"])
        self.assertIn("printing unknown", view["bonus_import"]["rows"][0]["problem"])
        self.assertApiError(400, self.add, bonus_choices=[1], bonus_source_sha256=view["bonus_import"]["source_sha256"])
        self.assertEqual(self.writes_made(), 0)

    def run_cli(self, *args):
        return test_precon_cli.CommandLineTests.run_cli(self, *args)

    def test_cli_previews_separately_and_requires_explicit_include_or_skip_to_save(self):
        args = ("add-precon", "TestDinos_TST", "--space", "user2", "-m", "Add fixture precon")
        code, out, err = self.run_cli(*args, "--dry-run")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("Fixed bonus cards (collection only, not deck lines):", out)
        self.assertIn("[x] 2 Pick Your Poison (MKM 170, foil)", out)
        self.assertIn("[ ] 1 Llanowar Elves (FDN 227) (2 already owned)", out)
        self.assertIn("a 2-card sample pack (random, not added)", out)
        self.assertEqual(self.run_cli(*args)[0], 1)
        self.assertEqual(self.writes_made(), 0)
        sealed.contents.reset_mock()
        code, out, err = self.run_cli(*args, "--bonus-cards", "include")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 8 cards", out)
        self.assertFalse(sealed.contents.call_args.kwargs["fetch"])

    def test_cli_skip_explicitly_omits_bonus_cards(self):
        code, out, err = self.run_cli("add-precon", "TestDinos_TST", "--space", "user2", "-m", "Skip missing bonus",
                                      "--bonus-cards", "skip")
        self.assertEqual((code, err), (0, ""), out)
        self.assertIn("Added 5 cards", out)
        self.assertFalse(any(row["name"] == "Pick Your Poison" for row in self.rows("user2")["rows"]))


@unittest.skipUnless(test_precon_tokens_ui.NODE, "Node.js is not installed")
class BonusUiTests(unittest.TestCase):
    def run_js(self, scenario):
        test_precon_tokens_ui.PreconTokensUiTests.run_js(self, r'''
          const bonus=extra=>({source_sha256:'d'.repeat(64),rows:[
            {source_row:1,qty:2,words:'Pick Your Poison (MKM 170, foil)',owned:0,selected:true,problem:null},
            {source_row:2,qty:1,words:'Llanowar Elves (FDN 227)',owned:2,selected:false,problem:null}],...extra});
          const bonusPreview=extra=>preview({token_import:undefined,adds:{cards:6,rows:2},bonus_import:bonus(),...extra});
          const openBonus=extra=>open(bonusPreview(extra));
          const tick=(ctx,index,value)=>{const input=ctx.bonusChoice.options[index].node;input.checked=value;input.fire('change');return input;};
        ''' + scenario)

    def test_native_review_defaults_and_exact_receipt_choice_in_request(self):
        self.run_js(r'''
          const ctx=await openBonus(),choice=ctx.bonusChoice;
          assert(ctx.area.textContent.includes('Fixed bonus cards'));assert(ctx.area.textContent.includes('2 already owned'));
          assert(ctx.area.textContent.includes('never the deck list'));
          assert(choice.options[0].node.checked);assert(!choice.options[1].node.checked);
          assert(choice.options.every(row=>row.node.getAttribute('type')==='checkbox'&&row.node.parentNode.tag==='label'));
          tick(ctx,0,false);assert(ctx.addSummary.textContent.includes('4 cards'));tick(ctx,1,true);
          assert(ctx.addSummary.textContent.includes('5 cards'));let body;
          apiWrite=async(path,payload)=>{body=payload;return added();};await addPrecon(ctx);
          same(body.bonus_choices,[2]);assert.equal(body.bonus_source_sha256,'d'.repeat(64));
          assert(!Object.hasOwn(body,'bonus_rows'));assert(!Object.hasOwn(body,'rows'));
        ''')

    def test_bad_or_changed_source_and_detached_controls_never_write(self):
        self.run_js(r'''
          for(const extra of [{source_sha256:'bad'},{rows:null},{rows:[{source_row:1,qty:1,words:'x',owned:0,selected:true,problem:'Unavailable'}]}]){
            const ctx=await openBonus({bonus_import:bonus(extra)});assert(ctx.bonusMalformed);assert(!addButton(ctx));
            let writes=0;apiWrite=async()=>{writes++;return added();};await addPrecon(ctx);assert.equal(writes,0);
          }
          for(const mode of ['profile','route','detached','metadata']){
            const ctx=await openBonus();if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;
            if(mode==='detached')ctx.bonusChoice.options[0].node.remove();if(mode==='metadata')ctx.preview.bonus_import.rows[0].qty=8;
            let writes=0;apiWrite=async()=>{writes++;return added();};await addPrecon(ctx);assert.equal(writes,0,mode);
          }
        ''')

    def test_stale_bonus_or_collection_requires_explicit_fresh_preview_and_keeps_title(self):
        self.run_js(r'''
          for(const data of [{bonus_conflict:true},{sha256:'collection-next',rows:[]}]){
            const ctx=await openBonus();ctx.titleInput.value='My reviewed title';const calls=[];
            apiWrite=async(path,body)=>{calls.push(body);throw new ApiError(409,'Preview changed',data);};await addPrecon(ctx);
            assert(ctx.tokenPreviewStale);assert(!addButton(ctx));assert(textButton(ctx,'Preview again'));
            await addPrecon(ctx);assert.equal(calls.length,1);let reads=0;
            api=async()=>{reads++;return bonusPreview({bonus_import:bonus({source_sha256:'e'.repeat(64)})});};
            textButton(ctx,'Preview again').click();await flush();assert.equal(reads,1);assert.equal(ctx.titleInput.value,'My reviewed title');
            apiWrite=async(path,body)=>{calls.push(body);return added();};await addPrecon(ctx);
            assert.equal(calls.length,2);assert.equal(calls[1].bonus_source_sha256,'e'.repeat(64));same(calls[1].bonus_choices,[1]);
          }
        ''')

    def test_busy_and_unknown_outcome_do_not_offer_a_second_add(self):
        self.run_js(r'''
          const ctx=await openBonus();let reject,writes=0;apiWrite=()=>{writes++;return new Promise((done,fail)=>reject=fail);};
          const pending=addPrecon(ctx);await addPrecon(ctx);assert.equal(writes,1);assert(ctx.bonusChoice.options.every(row=>row.node.disabled));
          tick(ctx,0,false);assert(ctx.bonusChoice.options[0].node.checked);reject(Error('Lost answer'));await pending;
          assert(ctx.tokenPreviewStale);assert(!addButton(ctx));await addPrecon(ctx);assert.equal(writes,1);
        ''')
