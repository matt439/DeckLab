"""Explicit scan-session defaults and retained unsure proposals, without camera/OCR/network."""
import unittest

from decklab.tests import test_collection_scan_ui as scan_ui


@unittest.skipUnless(scan_ui.NODE, "Node.js is not installed")
class ScanSessionTests(unittest.TestCase):
    def run_js(self, scenario):
        scan_ui.CollectionScanUiTests.run_js(self, r'''
          const keep=(ctx,values,apply=true)=>{
            ctx.sheet.body.querySelector('.col-scan-defaults').setAttribute('open','');
            for(const [key,value] of Object.entries(values))ctx.defaultControls[key].value=value;
            if(apply)button(ctx.sheet.body,'Keep for the next cards').click();
          };
          const uncertain=(ctx,id)=>ctx.checkList.querySelector(`[data-scan-photo="${id}"]`);
          const unread={ok:true,space:'home',unread:false,message:'No card could be identified.',proposals:[],read:{language:'ja'},lines:['PRIVATE OCR LINE']};
          const previewed=()=>({token:'t'.repeat(32),format:'collection',rows:[],problems:[],adds:{rows:1,cards:1},
            dropped_basics:0,sha256:'s1',repeat_imports:[]});
        ''' + scenario)

    def test_kept_values_require_explicit_action_only_apply_to_later_cards_and_respect_source_facts(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());
          keep(ctx,{condition:'LP',language:'ja',finish:'foil'},false);
          const plain=extra=>({...ELVES,proposals:[proposal('Llanowar Elves','fdn','227','name and number',
            {language:'',finishes:['nonfoil','foil'],...extra})]});
          const answers=[plain({condition:'NM'}),plain({}),plain({language:'en'}),plain({finishes:['nonfoil']})];
          apiWrite=async()=>answers.shift();await shoot(ctx);
          same(ctx.pending.map(row=>[row.condition,row.language,row.finish]),[['','','nonfoil']]);
          button(ctx.sheet.body,'Keep for the next cards').click();await shoot(ctx);await shoot(ctx);await shoot(ctx);
          same(ctx.pending.map(row=>[row.condition,row.language,row.finish]),
            [['','','nonfoil'],['LP','ja','foil'],['LP','en','foil'],['LP','ja','nonfoil']]);
          assert(ctx.defaultsStatus.textContent.includes('LP'));assert(ctx.defaultsStatus.textContent.includes('Existing cards stay as they are'));
          assert(ctx.sheet.body.querySelector('.col-scan-defaults').querySelector('summary').textContent.includes('Kept for the next cards: LP'));
          assert(ctx.pending.every(row=>!Object.hasOwn(row,'photo')));
        ''')

    def test_pending_row_edits_are_not_implicitly_kept_and_reopening_clears_session_defaults(self):
        self.run_js(r'''
          const cv=draw();let ctx=openScanSheet(cv);
          apiWrite=async()=>({...ELVES,proposals:[proposal('Llanowar Elves','fdn','227','name and number',{language:'',finishes:['nonfoil','foil']})]});
          await shoot(ctx);const condition=pick(ctx,'Condition of Llanowar Elves');condition.value='NM';condition.fire('change');
          await shoot(ctx);same(ctx.pending.map(row=>[row.quantity,row.condition]),[[1,'NM'],[1,'']]);
          keep(ctx,{condition:'LP',language:'ja',finish:'foil'});
          ctx.sheet.close();ctx=openScanSheet(cv);same(ctx.defaults,{condition:'',language:'',finish:''});
          await shoot(ctx);same(ctx.pending.map(row=>[row.condition,row.language,row.finish]),[['','','nonfoil']]);
        ''')

    def test_changing_draft_selectors_does_not_replace_kept_settings_and_clear_is_explicit(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());keep(ctx,{condition:'LP',language:'ja',finish:'foil'});
          keep(ctx,{condition:'NM',language:'en',finish:'nonfoil'},false);
          apiWrite=async()=>({...ELVES,proposals:[proposal('Llanowar Elves','fdn','227','name and number',{language:'',finishes:['nonfoil','foil']})]});
          await shoot(ctx);same(ctx.pending.map(row=>[row.condition,row.language,row.finish]),[['LP','ja','foil']]);
          button(ctx.sheet.body,'Clear kept settings').click();await shoot(ctx);
          same(ctx.pending.map(row=>[row.condition,row.language,row.finish]),[['LP','ja','foil'],['','','nonfoil']]);
          assert(ctx.defaultsStatus.textContent.includes('No values kept'));
        ''')

    def test_unsure_proposals_survive_the_next_photo_and_resolve_without_replacing_the_current_card(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());const answers=[GHALTA,ELVES];apiWrite=async()=>answers.shift();
          await shoot(ctx);assert.equal(ctx.unsure.length,1);assert.equal(ctx.pending.length,0);
          const old=ctx.result.querySelector('.col-scan-pick');await shoot(ctx);
          assert.equal(ctx.pending.length,1);assert(uncertain(ctx,1).textContent.includes('RIX 130'));
          old.click();assert.equal(ctx.pending.length,1,'detached current-photo controls cannot add again');
          button(uncertain(ctx,1),'Ghalta, Primal Hunger (RIX 130) · RIX').click();
          assert.equal(ctx.unsure.length,0);assert.equal(ctx.pending.length,2);assert(ctx.result.textContent.includes('Not that one?'));
          button(ctx.result,'Llanowar Elves (M19 314) · M19').click();
          same(ctx.pending.map(row=>[row.name,row.set,row.quantity]),[['Ghalta, Primal Hunger','rix',1],['Llanowar Elves','m19',1]]);
        ''')

    def test_review_never_sends_unresolved_photos_and_skip_is_an_explicit_local_action(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());const calls=[],answers=[ELVES,GHALTA];
          apiWrite=async(path,body)=>{calls.push([path,body]);return path==='/api/collection/scan'?answers.shift():previewed();};
          await shoot(ctx);await shoot(ctx);const before=calls.length;
          foot(ctx,'review').click();await flush();assert.equal(calls.length,before);assert(!ctx.sheet.closed);
          assert(ctx.message.textContent.includes('Nothing was sent to the import preview'));assert.equal(reviewScan(ctx),null);
          button(uncertain(ctx,1),'Skip this photo').click();assert.equal(ctx.unsure.length,0);assert.equal(calls.length,before);
          foot(ctx,'review').click();await flush();assert.equal(calls.at(-1)[0],'/api/collection/import/preview');
          assert(calls.at(-1)[1].text.includes('Llanowar Elves'));assert(!calls.at(-1)[1].text.includes('Ghalta'));
        ''')

    def test_an_unread_archived_photo_can_be_named_and_its_read_language_beats_kept_language(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());keep(ctx,{condition:'LP',language:'de',finish:'foil'});
          const answers=[unread,ELVES];apiWrite=async()=>answers.shift();await shoot(ctx);await shoot(ctx);
          assert.equal(ctx.unsure.length,1);assert(!JSON.stringify(ctx.unsure).includes('QUJD'));
          assert(!JSON.stringify(ctx.unsure).includes('PRIVATE OCR LINE'));
          button(uncertain(ctx,1),'Find by name…').click();ctx.name.value='Arcane Signet';
          api=async()=>({name:'Arcane Signet',printings:[{set:'m3c',collector_number:'283',set_name:'Commander',finishes:['nonfoil']}]});
          await findScanName(ctx);assert.equal(ctx.unsure.length,1);assert.equal(ctx.pending.length,1);
          button(ctx.result,'Arcane Signet (M3C 283) · Commander').click();
          assert.equal(ctx.unsure.length,0);const signet=ctx.pending.find(row=>row.name==='Arcane Signet');
          same([signet.condition,signet.language,signet.finish],['LP','ja','nonfoil']);
        ''')

    def test_kept_finish_is_not_assumed_when_printing_support_is_missing(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());keep(ctx,{finish:'etched'});apiWrite=async()=>ELVES;await shoot(ctx);
          assert.equal(ctx.pending[0].finish,'nonfoil');
          apiWrite=async()=>({...ELVES,proposals:[proposal('Llanowar Elves','fdn','227','name and number',{finishes:['nonfoil','etched']})]});
          await shoot(ctx);assert.equal(ctx.pending[1].finish,'etched');assert(ctx.message.textContent.includes('Etched'));
        ''')

    def test_defaults_and_stored_choices_belong_to_the_original_open_visible_sheet_and_profile(self):
        self.run_js(r'''
          for(const mode of ['closed','profile','route','space','hidden','detached','overlay','busy']){
            colCloseSheets();const ctx=openScanSheet(draw());keep(ctx,{condition:'LP'},false);
            drawScanResult(ctx,GHALTA);ctx.currentUnsure=null;drawScanUnsure(ctx);
            const keepButton=button(ctx.sheet.body,'Keep for the next cards'),choice=uncertain(ctx,1).querySelector('.col-scan-pick');
            if(mode==='closed')ctx.sheet.close();if(mode==='profile')state.profile=PROFILES[1];if(mode==='route')routeToken++;
            if(mode==='space')ctx.cv.space='user2';if(mode==='hidden')ctx.sheet.body.hidden=true;
            if(mode==='detached'){keepButton.remove();choice.remove();}if(mode==='overlay')openSheet({title:'Another review'});
            if(mode==='busy')ctx.busy=true;
            keepButton.click();choice.click();same(ctx.defaults,{condition:'',language:'',finish:''});assert.equal(ctx.pending.length,0,mode);
            assert.equal(ctx.unsure.length,1,mode);
          }
        ''')

    def test_unsure_proposals_are_bounded_and_new_photos_are_not_silently_dropped(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());for(let i=0;i<COL_SCAN_UNSURE_MAX;i++)drawScanResult(ctx,GHALTA);
          let writes=0;apiWrite=async()=>{writes++;return ELVES;};await shoot(ctx);
          assert.equal(writes,0);assert.equal(ctx.unsure.length,COL_SCAN_UNSURE_MAX);assert(ctx.message.textContent.includes('Resolve or skip some'));
          assert(ctx.input.disabled);button(uncertain(ctx,1),'Skip this photo').click();assert(!ctx.input.disabled);
          await shoot(ctx);assert.equal(writes,1);
          assert.equal(ctx.unsure.length,COL_SCAN_UNSURE_MAX-1);assert.equal(ctx.pending.length,1);
        ''')

    def test_check_these_retains_only_proposal_metadata_not_photo_or_ocr_payloads(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());const proposals=Array.from({length:20},(_,index)=>({...GHALTA.proposals[0],
            collector_number:String(index),photo:'RAW PHOTO',lines:['RAW OCR'],blob:'RAW BLOB'}));
          drawScanResult(ctx,{...GHALTA,photo:'RAW TOP PHOTO',lines:['RAW TOP OCR'],proposals});
          assert.equal(ctx.unsure[0].proposals.length,COL_SCAN_CHOICES);
          const metadata=JSON.stringify(ctx.unsure);for(const words of ['RAW PHOTO','RAW OCR','RAW BLOB','RAW TOP'])assert(!metadata.includes(words));
          assert(metadata.includes('Ghalta'));assert(metadata.includes('collector_number'));
        ''')

    def test_a_failed_later_photo_keeps_earlier_unsure_proposals_available(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());let calls=0;apiWrite=async()=>{if(++calls===1)return GHALTA;throw new ApiError(429,'Try another photo later.');};
          await shoot(ctx);await shoot(ctx);assert.equal(ctx.unsure.length,1);assert.equal(ctx.pending.length,0);
          assert(uncertain(ctx,1).textContent.includes('Ghalta'));assert(uncertain(ctx,1).textContent.includes('RIX 130'));
          button(uncertain(ctx,1),'Ghalta, Primal Hunger (RIX 130) · RIX').click();assert.equal(ctx.unsure.length,0);assert.equal(ctx.pending.length,1);
        ''')

    def test_back_from_import_keeps_resolved_card_facts_but_not_session_defaults(self):
        self.run_js(r'''
          const ctx=openScanSheet(draw());keep(ctx,{condition:'LP',language:'ja',finish:'foil'});
          apiWrite=async path=>path==='/api/collection/scan'?({...ELVES,proposals:[proposal('Llanowar Elves','fdn','227','name and number',
            {language:'',finishes:['nonfoil','foil']})]}):previewed();
          await shoot(ctx);foot(ctx,'review').click();await flush();const importing=[...colSheets].at(-1);
          importing.foot.querySelector('[data-action="back"]').click();const returned=[...colSheets].at(-1);
          assert(returned.body.querySelector('.col-scan-defaults').textContent.includes('No values kept'));
          assert.equal(returned.body.querySelector('[aria-label="Condition of Llanowar Elves"]').value,'LP');
          assert.equal(returned.body.querySelector('[aria-label="Language of Llanowar Elves"]').value,'ja');
          assert.equal(returned.body.querySelector('[aria-label="Finish of Llanowar Elves"]').value,'foil');
        ''')
