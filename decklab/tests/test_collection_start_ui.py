"""Physical-pile onboarding and explicit portable pending batches, no live data."""
import unittest

from decklab.tests import test_collection_scan_ui as scan_ui


@unittest.skipUnless(scan_ui.NODE, "Node.js is not installed")
class CollectionStartTests(unittest.TestCase):
    def run_js(self, code):
        scan_ui.CollectionScanUiTests.run_js(self, code)

    def test_guide_reuses_guarded_flows_without_writes_and_supports_no_ocr(self):
        self.run_js(r'''
          const cv=draw({scan:{available:false}}); let writes=0;
          apiWrite=async()=>{writes++;throw new Error('no writes');};
          const guide=openCollectionAddSheet(cv);
          assert(guide.body.textContent.includes('Start with a small pile'));
          assert(guide.body.textContent.includes('Photo reading is unavailable'));
          button(guide.body,'Scan').click();
          assert(guide.closed); assert.equal(writes,0);
          assert(document.body.textContent.includes('Type a card'));
          colCloseSheets(); cv.editable=false;
          assert.equal(openCollectionAddSheet(cv),null);
          cv.editable=true;cv.unsupported=true;
          assert.equal(openCollectionAddSheet(cv),null);
        ''')

    def test_guide_stale_action_does_not_reopen_for_other_profile(self):
        self.run_js(r'''
          const cv=draw(); const guide=openCollectionAddSheet(cv);
          const action=button(guide.body,'Scan');
          cv.unsupported=true; action.click(); assert(!guide.closed);
          cv.unsupported=false; routeToken++; action.click(); assert(!guide.closed);
        ''')

    def test_download_is_explicit_csv_only_and_retains_pending_list(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw()); let exported=null, click=0, writes=0;
          apiWrite=async()=>{writes++;};
          globalThis.Blob=class {constructor(parts){exported=parts.join('');}};
          URL.createObjectURL=()=> 'blob:test'; URL.revokeObjectURL=()=>{};
          const original=el; el=(tag,attrs,...children)=>{
            const node=original(tag,attrs,...children);
            if(tag==='a' && attrs.download) {node.click=()=>{click++;};}
            return node;
          };
          addScanCard(ctx,proposal('Llanowar Elves','fdn','227','name',{language:''}));
          foot(ctx,'download').click();
          assert.equal(click,1);assert.equal(writes,0);assert(!ctx.sheet.closed);
          assert.equal(ctx.pending.length,1);
          assert.equal(exported,colScanCsv(ctx.pending));
          assert(ctx.message.textContent.includes('Check that the CSV is saved'));
          assert(ctx.message.textContent.includes('Nothing was added now'));
        ''')

    def test_download_refuses_uncertain_and_stale_context_and_preserves_on_error(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw()); let downloads=0;
          globalThis.Blob=class {}; URL.createObjectURL=()=>{downloads++;throw new Error('blocked');};
          addScanCard(ctx,proposal('Llanowar Elves','fdn','227','name'));
          ctx.cv.unsupported=true;downloadScanBatch(ctx);assert.equal(downloads,0);ctx.cv.unsupported=false;
          ctx.unsure.push({id:1}); downloadScanBatch(ctx);assert.equal(downloads,0);
          ctx.unsure=[]; downloadScanBatch(ctx);assert.equal(downloads,1);
          assert.equal(ctx.pending.length,1);assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes("couldn't be downloaded"));
          routeToken++; downloadScanBatch(ctx);assert.equal(downloads,1);
        ''')

    def test_saved_batch_reopens_in_import_review_and_applies_once(self):
        self.run_js(r''' 
          const cv=draw(), ctx=openScanSheet(cv); let csv;
          globalThis.Blob=class {constructor(parts){csv=parts.join('');}};
          URL.createObjectURL=()=> 'blob:batch';URL.revokeObjectURL=()=>{};
          addScanCard(ctx,proposal('Llanowar Elves','fdn','227','name'));
          downloadScanBatch(ctx);ctx.sheet.close();
          const importing=openImportSheet(cv);let previews=0,applies=0,release;
          colReload=()=>{};
          apiWrite=async(path,body)=>{
            if(path.endsWith('/preview')){previews++;assert.equal(body.text,csv);return {
              token:'t'.repeat(32),format:'collection',rows:[],problems:[],adds:{rows:1,cards:1},dropped_basics:0,sha256:'s1',repeat_imports:[]};}
            applies++;return new Promise(resolve=>{release=resolve;});
          };
          await previewImport(importing,'pending-collection.csv',csv);
          assert.equal(previews,1);assert.equal(applies,0);
          applyImport(importing,false);applyImport(importing,false);await flush();
          assert.equal(applies,1);release({added:{rows:1,cards:1},sha256:'s2'});await flush();
          assert(importing.sheet.closed);await applyImport(importing,false);assert.equal(applies,1);
        ''')
