"""A suggested swap resumes, checks and saves through the ordinary linked Considering editor."""
import json
import subprocess
import unittest

from decklab.tests.test_editor_considering_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SWAP_SETUP = SETUP + r"""
  const swapSource={...candidates[0],qty:3};
  const swapView=consideringView({},[swapSource,candidates[1]]);
  const swapProposal={cuts:[{name:elves.name,qty:1}],adds:[{...swapSource,qty:1}],max_qty:2,
    reason:'Try an answer',trade_off:'One fewer creature'};
  function resumeSuggested() {
    const draft=smallSwapDraft(swapView,swapProposal,2);assert(draft);
    local.set(draftKey({mode:'edit',profile:state.profile.id,id:swapView.id,version:'target'}),JSON.stringify(draft));
    startEditor({mode:'edit',view:structuredClone(swapView),version:'target'});
    return editor;
  }
  function swapChecked(body) {
    return consideringCheck({changes:{decklist:true,categories:false,considering:true,fields:[],prose:[],marker:false},
      lists:structuredClone(body.lists),counts:{target:{main:60,sideboard:1}}});
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckSmallSwapsDraftUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SWAP_SETUP + scenario, True,
                                {"innerWidth": 393, "innerHeight": 852, "coarse": True}]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_restored_linked_swap_uses_normal_check_save_and_retains_undo_state(self):
        self.run_js(r"""
          const ed=resumeSuggested();assert(isDirty());assert.equal(ed.notice.kind,'draft');
          const target=sendList(ed.lists),alternatives=plainConsidering(ed),tracking=structuredClone(ed.consideringMoves);
          assert.equal(ed.lists.Deck.find(line=>line.name===elves.name).qty,2);
          const promoted=ed.lists.Deck.find(line=>line.name===bolt.name);same(sendLine(promoted),sendLine({...swapSource,qty:2}));
          same(alternatives,[sendLine({...swapSource,qty:1}),sendLine(candidates[1])]);
          same(draftBody().lists,{target,considering:alternatives});
          assert.equal(draftBody().fields,undefined);assert.equal(draftBody().prose,undefined);
          const originalSnapshot=snapshot(ed);
          quantity(ed,0,2);assert.equal(ed.history.length,1);assert(undoLast());assert.equal(snapshot(ed),originalSnapshot);
          same(ed.consideringMoves,tracking);same(draftBody().lists,{target,considering:alternatives});
          const calls=[];apiWrite=async(path,body)=>{
            calls.push([path,structuredClone(body)]);
            if(path==='/api/deck/check')return swapChecked(body);
            assert.equal(path,'/api/deck/save');
            return {id:ed.id,sha256:'b'.repeat(64),changed:true,warnings:[],stale_tables:[],
              deck:consideringView({sha256:'b'.repeat(64),lists:{target:structuredClone(ed.lists),owned:structuredClone(list)}},ed.considering)};
          };
          await saveNow();same(calls.map(([path])=>path),['/api/deck/check','/api/deck/save']);
          for(const [,body]of calls)same(body.lists,{target,considering:alternatives});
          assert(editor!==ed);assert(!isDirty());assert.equal(editor.consideringMoves.length,0);
          same(plainConsidering(editor),alternatives);same(sendList(editor.lists),target);
          assert.equal(local.get(draftKey(editor)),null);
        """)

    def test_concurrent_planned_or_considering_edit_rebases_as_complete_pair_requiring_review(self):
        self.run_js(r"""
          const ed=resumeSuggested(),target=sendList(ed.lists),alternatives=plainConsidering(ed);
          assert(saveDraft(ed));
          const latest=structuredClone(swapView);latest.sha256='b'.repeat(64);
          latest.lists.target.Deck[0].qty=3;latest.lists.target.Deck[1].qty=57;
          latest.lists.considering[0].qty=4;
          startEditor({mode:'edit',view:latest,version:'target'});
          same(sendList(editor.lists),target);same(plainConsidering(editor),alternatives);
          assert(editor.promotionReview);assert(editorPromotionReviewNeeded(editor));
          assert(editor.notice.notes.some(note=>note.includes('complete linked draft')));
          let saves=0;apiWrite=async(path,body)=>{if(path==='/api/deck/save')saves++;return swapChecked(body);};
          await saveNow();assert.equal(saves,0);
          const sheet=document.querySelector('dialog'),ack=sheet.querySelector('.editor-promotion-ack');
          assert(ack&&!ack.checked);assert(sheet.querySelector('[data-action="save"]').disabled);
        """)
