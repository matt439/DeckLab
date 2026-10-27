"""Whole-change Undo of an import or receipt on Activity: every row reviewed, one reason, no selection."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityMixedUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const removedRow=extra=>collectionRow({set:'m19',collector_number:'314',quantity:3,condition:'',language:'',notes:'Literal <b>note</b>',...extra});
          const mixedPreview=(extra={})=>({available:true,id:42,expect:'a'.repeat(64),kind:'mixed',space:'home',action:'import_undo',
            label:'Import of 5 cards (1 new row, 1 row added to)',reason_required:true,cards:5,
            collection:{removed:[removedRow()],reduced:[{current:collectionRow({quantity:4}),restored:collectionRow({quantity:2})}]},
            tokens:{removed:[],reduced:[]},components:[],products:[],uploads:['upload.csv'],...extra});
          const receiptPreview=(extra={})=>mixedPreview({action:'receipt_undo',label:'Receipt of order 2026-10-20-shop (cards, tokens)',uploads:[],
            components:[{order:'2026-10-20-shop',component:'cards',kind:'cards',received_on:'2026-10-25',checks:['Confirm the Elves are near mint']},
                        {order:'2026-10-20-shop',component:'tokens',kind:'tokens',received_on:'2026-10-25',checks:[]}],
            products:[{product:'fdc-test-precon',status:'preordered',intact:'yes'}],
            tokens:{removed:[tokenRow({front:'Treasure',back:'',quantity:2})],reduced:[]},...extra});
          const mixedSaved=(p,extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'mixed',space:p.space,action:p.action,cards:p.cards,
            removed_rows:p.collection.removed.length,restored_rows:p.collection.reduced.length,components:p.components.length,products:p.products.length,
            tables_refreshed:2,tables_error:false,revision:'9',summary:'Undo change #42: '+p.label,...extra});
          const openMixed=async(p=mixedPreview())=>{const made=mount([candidate(42,{undo:{review:true,kind:'mixed'}})]);const asked=[];
            api=async path=>{asked.push(path);return p;};made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p,asked};};
          const reason=sheet=>sheet.body.querySelector('input');
          const giveReason=(sheet,value='Imported the wrong file')=>{const input=reason(sheet);input.value=value;input.fire('input');return input;};
        ''' + scenario)

    def test_import_review_lists_every_row_and_reads_the_mixed_endpoint(self):
        self.run_js(r'''
          const {sheet,asked,p}=await openMixed(),text=sheet.body.textContent,before=JSON.stringify(p);
          same(asked,['/api/activity/mixed-undo?id=42']);
          for(const words of ['Import of 5 cards','5 copies in all','uploaded file stays kept','Collection rows to remove','Llanowar Elves (M19 314, nonfoil) × 3',
            'going back to fewer copies','4 → 2','Upload kept','upload.csv','no partial selection','Literal <b>note</b>','Why undo this import?'])
            assert(text.includes(words),words);
          assert.equal(sheet.body.querySelector('b'),null);assert.equal(sheet.body.querySelectorAll('input').length,1);
          assert(save(sheet).disabled);assert.equal(JSON.stringify(p),before);
        ''')

    def test_receipt_review_names_parts_products_checks_and_tokens(self):
        self.run_js(r'''
          const {sheet}=await openMixed(receiptPreview()),text=sheet.body.textContent;
          for(const words of ['back on order','Order 2026-10-20-shop: cards (cards)','checks to do again: Confirm the Elves are near mint',
            'Products going back on order','fdc-test-precon','back to preordered (it was kept intact)','Token cards to remove','Treasure × 2',
            'Why undo this receipt?'])assert(text.includes(words),words);
          assert(!text.includes('Upload kept'));
        ''')

    def test_save_sends_only_id_receipt_and_reviewed_reason_and_checks_the_answer(self):
        self.run_js(r'''
          const {sheet,p}=await openMixed();const sent=[];apiWrite=async(path,body)=>{sent.push([path,body]);return mixedSaved(p);};
          giveReason(sheet,'  Imported\t the wrong file ');assert(sheet.body.textContent.includes('Reason to be saved: Imported the wrong file'));
          save(sheet).click();await settle();
          same(sent,[['/api/activity/mixed-undo',{id:42,expect:'a'.repeat(64),reason:'Imported the wrong file'}]]);
          assert(sheet.body.textContent.includes('Undo saved as a new change.'));assert(sheet.body.textContent.includes('2 deck tables were worked out again'));
          assert(button(sheet.dialog,'Done'));
        ''')

    def test_an_answer_that_does_not_match_the_preview_needs_a_reload(self):
        self.run_js(r'''
          for(const extra of [{removed_rows:0},{action:'receipt_undo'},{cards:4},{tables_refreshed:-1},{kind:'collection'},{saved:false}]){
            const {sheet,p}=await openMixed();apiWrite=async()=>mixedSaved(p,extra);giveReason(sheet);save(sheet).click();await settle();
            assert(button(sheet.dialog,'Reload Activity'),JSON.stringify(extra));assert(!sheet.body.textContent.includes('Undo saved'));
          }
        ''')

    def test_blank_or_long_reasons_keep_save_disabled(self):
        self.run_js(r'''
          const {sheet}=await openMixed();let writes=0;apiWrite=async()=>{writes++;};
          for(const value of ['','   ','x'.repeat(201)]){giveReason(sheet,value);assert(save(sheet).disabled,JSON.stringify(value));save(sheet).fire('click');}
          await settle();assert.equal(writes,0);
        ''')

    def test_malformed_previews_never_offer_save(self):
        self.run_js(r'''
          const bad=[{kind:'collection'},{space:'user2'},{reason_required:false},{action:'batch_remove'},{cards:-1},{uploads:[]},
            {components:[{order:'x',component:'cards',kind:'cards',received_on:'',checks:[]}]},{extra:1},
            {collection:{removed:[{...removedRow(),quantity:0}],reduced:[]}},{collection:{removed:[],reduced:[{current:collectionRow({quantity:2}),restored:collectionRow({quantity:4})}]}},
            {tokens:{removed:[tokenRow()],reduced:[]}}];
          for(const extra of bad){const {sheet}=await openMixed(mixedPreview(extra));assert(!save(sheet),JSON.stringify(extra));}
          for(const extra of [{products:[{product:'x',status:'owned',intact:'yes'}]},{components:[]},{uploads:['upload.csv']}]){
            const {sheet}=await openMixed(receiptPreview(extra));assert(!save(sheet),JSON.stringify(extra));}
        ''')


if __name__ == "__main__":
    unittest.main()
