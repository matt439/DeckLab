"""Correcting the recorded box from a reviewed check: preview first, then one confirmed save."""
import unittest

from decklab.tests import test_box_check_ui as boxes
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  const repairPreview=extra=>({preview:true,id:'casual/a',version:'target',recipe_sha256:'d'.repeat(64),result_sha256:'e'.repeat(64),
    sections:{Deck:[{kind:'card',name:'Recorded Elf',for:null,quantity:1,basic:false}]},card_count:28,
    freed:[{name:'Recorded Elf',quantity:1}],held:[],pool_unknown:false,tokens:{recorded:true,cards:['1 Dog // Beast'],no_longer_made:[],newly_made:[]},
    missing:[],extra:[],expected_cards:29,found_cards:28,...extra});
  const repairAnswer=extra=>({saved:true,id:'casual/a',revision:2,sha256:'c'.repeat(64),checked_on:'2026-10-27',recipe_sha256:'d'.repeat(64),
    result_sha256:'e'.repeat(64),freed:[],held:[],stale_tables:[{id:'casual/b'}],missing:[],extra:[],...extra});
  const missingOne=async()=>{const made=await openBox();allFound(made.sheet);found(made.sheet,2,'1');reviewButton(made.sheet).click();return made;};
  const previewButton=sheet=>sheet.body.querySelector('.box-repair-preview');
  const repairSave=sheet=>sheet.body.querySelector('.box-repair-save');
'''


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxRepairUiTests(unittest.TestCase):
    def run_js(self, scenario):
        boxes.BoxCheckUiTests.run_js(self, SETUP + scenario)

    def test_matching_box_or_read_only_review_offers_no_correction(self):
        self.run_js(r'''
          let made=await openBox();reviewed(made.sheet);assert.equal(previewButton(made.sheet),null);
          made=await openBox(contents(),boxMeta({editable:false,why_not:'Not yours'}));allFound(made.sheet);found(made.sheet,2,'1');
          reviewButton(made.sheet).click();assert.equal(previewButton(made.sheet),null);
        ''')

    def test_preview_writes_with_the_review_and_shows_build_tokens_and_reservations(self):
        self.run_js(r'''
          const {sheet}=await missingOne();const calls=[];apiWrite=async(path,body)=>{calls.push([path,body]);return repairPreview({
            held:[{name:'Opt',quantity:2,owned:1,elsewhere:0,short:1}]});};
          previewButton(sheet).click();await settle();
          assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/deck/box-repair');assert.equal(calls[0][1].confirm,undefined);
          assert.equal(calls[0][1].expect,'b'.repeat(64));assert.equal(calls[0][1].rows[2].quantity,1);
          for(const words of ['1 x Recorded Elf','Free for other decks again: 1 Recorded Elf','Now held by this deck: 2 Opt','1 more Opt',
            'Packed token cards stay as recorded: 1 Dog // Beast'])assert(sheet.body.textContent.includes(words),words);
          assert(repairSave(sheet));assert(dateButton(sheet));
        ''')

    def test_confirm_sends_the_previewed_result_then_offers_done_and_stale_tables(self):
        self.run_js(r'''
          const {sheet}=await missingOne();const calls=[];apiWrite=async(path,body)=>{calls.push(body);return body.confirm?repairAnswer():repairPreview();};
          previewButton(sheet).click();await settle();repairSave(sheet).click();await settle();
          assert.equal(calls.length,2);assert.equal(calls[1].confirm,true);assert.equal(calls[1].result_sha256,'e'.repeat(64));
          assert(button(sheet.dialog,'Done'));assert(!dateButton(sheet));assert(sheet.body.textContent.includes('Tables out of date'));
          assert(sheet.body.textContent.includes('The recorded box now matches this check'));
        ''')

    def test_mismatched_preview_is_refused_and_a_conflict_needs_the_plan_again(self):
        self.run_js(r'''
          const {sheet}=await missingOne();apiWrite=async()=>repairPreview({card_count:27});previewButton(sheet).click();await settle();
          assert.equal(repairSave(sheet),null);assert(sheet.body.textContent.includes("couldn't be worked out"));
          apiWrite=async(path,body)=>{if(body.confirm)throw new ApiError(409,'Changed since.');return repairPreview();};
          previewButton(sheet).click();await settle();repairSave(sheet).click();await settle();
          assert(button(sheet.dialog,'Reload plan'));assert(sheet.body.textContent.includes('Reload the plan'));
        ''')
