"""Two independent acknowledgements bind exact recorded facts and both current-photo crops."""
import unittest

from decklab.tests import test_activity_accessory_crop_undo_ui as crop_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryPhotoRecordUndoUiTests(unittest.TestCase):
    def run_js(self, code):
        crop_ui.AccessoryCropUndoUiTests.run_js(self, r'''
          const combinedPreview=(extra={})=>{const p=cropPreview();p.action='accessory_photo_record_update';p.record_confirmation_required=true;
            p.restored={...p.restored,owner:'shared',kind:'sleeves',capacity:'',quantity:'125',notes:'Historical <img src=x> literal',link:'https://example.com/old'};
            p.fields=ACTIVITY_UNDO_PHOTO_RECORD_FIELDS.filter(field=>p.current[field]!==p.restored[field]).map(field=>({field,before:p.current[field],after:p.restored[field]}));return {...p,...extra};};
          const combinedSaved=(p,extra={})=>({...cropSaved(p),action:p.action,summary:'Restored the recorded facts and crop on the current photo.',...extra});
          const recordConsent=sheet=>sheet.body.querySelectorAll('input[type=checkbox]')[1];
          const confirmRecord=(sheet,on=true)=>{const input=recordConsent(sheet);input.checked=on;input.fire('change');return input;};
          const readyBoth=sheet=>{confirmPhoto(sheet);confirmRecord(sheet);};
        ''' + code)

    def test_whole_rows_side_units_literal_links_and_two_unchecked_confirmations_are_reviewable(self):
        self.run_js(r'''
          const p=combinedPreview(),before=JSON.stringify(p),{sheet}=await openCrop(p);assert(save(sheet));assert(save(sheet).disabled);
          assert.equal(sheet.body.querySelectorAll('img').length,2);assert.equal(sheet.body.querySelectorAll('input[type=checkbox]').length,2);
          assert(!photoConsent(sheet).checked);assert(!recordConsent(sheet).checked);assert(!photoConsent(sheet).disabled);
          for(const text of ['Current record and crop','Restored record and crop','125 individual sleeves','2 items','Shared','Historical <img src=x> literal',
            'https://example.com/old','cannot recover an earlier photo','count replaces','Public/Private'])assert(sheet.body.textContent.includes(text),text);
          assert.equal(sheet.body.querySelectorAll('a').length,0);assert.equal(JSON.stringify(p),before);
          confirmPhoto(sheet);assert(save(sheet).disabled);confirmRecord(sheet);assert(!save(sheet).disabled);
          confirmPhoto(sheet,false);assert(save(sheet).disabled);confirmPhoto(sheet);confirmRecord(sheet,false);assert(save(sheet).disabled);
        ''')

    def test_both_decodes_are_required_and_setting_checked_without_change_event_never_authorizes_save(self):
        self.run_js(r'''
          photoMock.modes.push('ok','pending');const {sheet,p}=await openCrop(combinedPreview());confirmRecord(sheet);
          photoConsent(sheet).checked=true;save(sheet).fire('click');await photoSettle();assert(save(sheet).disabled);
          sheet.body.querySelectorAll('img')[1].finishPhoto();await photoSettle();assert(!photoConsent(sheet).checked);assert(save(sheet).disabled);
          photoConsent(sheet).checked=true;let writes=0;apiWrite=async()=>{writes++;return combinedSaved(p);};save(sheet).fire('click');await photoSettle();assert.equal(writes,0);
          confirmPhoto(sheet);assert(!save(sheet).disabled);
        ''')

    def test_both_flags_send_once_exact_receipt_finishes_and_cancel_resets_acknowledgements(self):
        self.run_js(r'''
          let made=await openCrop(combinedPreview());readyBoth(made.sheet);button(made.sheet.dialog,'Cancel').click();
          made=await openCrop(combinedPreview());assert(!photoConsent(made.sheet).checked);assert(!recordConsent(made.sheet).checked);readyBoth(made.sheet);
          let finish;const sent=[];apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(made.sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_photo:true,confirm_record:true}]]);
          assert(photoConsent(made.sheet).disabled);assert(recordConsent(made.sheet).disabled);finish(combinedSaved(made.p));await photoSettle();
          assert(button(made.sheet.dialog,'Done'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_exact_raw_source_flags_and_fields_are_required_before_photo_fetch(self):
        self.run_js(r'''
          const p=combinedPreview(),bad=[{record_confirmation_required:false},{photo_confirmation_required:false},{stock_confirmation_required:true},
            {action:'accessory_crop_update'},{action:'accessory_record_update'},{fields:[]},{fields:p.fields.slice(1)},
            {fields:[...p.fields,p.fields[0]]},{restored:{...p.restored,image:'other.jpg'}},{restored:{...p.restored,id:'different'}},
            {restored:{...p.restored,owner:state.profiles[1].id}},{photo:{...p.photo,size:25,url:'/unexpected'}}];
          for(const extra of bad){const count=photoMock.fetches.length,{sheet}=await openCrop(combinedPreview(extra));
            assert(!save(sheet),JSON.stringify(extra));assert.equal(photoMock.fetches.length,count,JSON.stringify(extra));closePhoto(sheet);}
          const onlyCrop=cropPreview({action:'accessory_photo_record_update',record_confirmation_required:true});
          assert.equal(activityUndoEvidence(onlyCrop,42,'home',state.profiles[0].id),null);
        ''')

    def test_changed_record_photo_context_detached_consent_or_stale_footer_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['facts','photo','profile','same-profile','route','filter','consent','image','src','crop','modal']){
            state.profile=state.profiles[0];location.hash='#/activity';let writes=0;
            const {sheet,p,view}=await openCrop(combinedPreview());readyBoth(sheet);const old=save(sheet);let top;
            apiWrite=async()=>{writes++;return combinedSaved(p);};
            if(mode==='facts')p.restored.quantity='124';if(mode==='photo')p.photo.sha256='f'.repeat(64);if(mode==='profile')state.profile=state.profiles[1];
            if(mode==='same-profile')state.profile={...state.profile};if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='consent')recordConsent(sheet).remove();if(mode==='image')sheet.body.querySelector('img').remove();
            if(mode==='src')sheet.body.querySelector('img').src='blob:http://localhost/other';if(mode==='crop')p.restored.crop='0,0,1,1';
            if(mode==='modal')top=openSheet('Another task');old.fire('click');await photoSettle();assert.equal(writes,0,mode);top?.close();closePhoto(sheet);
          }
        ''')

    def test_failed_or_unknown_save_requires_reload_and_never_repeats_post(self):
        self.run_js(r'''
          for(const mode of ['error','private-status','bad-row','bad-photo']){state.profile=state.profiles[0];const {sheet,p}=await openCrop(combinedPreview());readyBoth(sheet);let writes=0;
            apiWrite=async()=>{writes++;if(mode==='error')throw new ApiError(409,'Facts changed');
              if(mode==='private-status')throw Object.assign(Error('PRIVATE unexpected diagnostic'),{status:503});
              return mode==='bad-row'?combinedSaved(p,{restored:{...p.restored,notes:'Wrong'}}):combinedSaved(p,{photo:{...p.photo,sha256:'0'.repeat(64)}});};
            const old=save(sheet);old.click();await photoSettle();assert(!button(sheet.dialog,'Done'));assert(button(sheet.dialog,'Reload Activity'));
            assert(!sheet.body.textContent.includes('PRIVATE'));if(mode==='error')assert(sheet.body.textContent.includes('Facts changed'));
            old.fire('click');assert.equal(writes,1);closePhoto(sheet);}
        ''')

    def test_photo_failure_and_close_abort_release_without_authorizing_the_whole_record(self):
        self.run_js(r'''
          const bad=await openCrop(combinedPreview(),{etag:'"wrong"'});assert(!photoConsent(bad.sheet).checked);assert(save(bad.sheet)?.disabled||!save(bad.sheet));closePhoto(bad.sheet);
          const before=photoMock.blobs.length,made=await openCrop(combinedPreview(),{pending:true});confirmRecord(made.sheet);
          const request=photoMock.fetches.at(-1);button(made.sheet.dialog,'Cancel').click();assert(request.options.signal.aborted);
          photoMock.pending.shift()();await photoSettle();assert.equal(photoMock.blobs.length,before);
          const ready=await openCrop(combinedPreview());readyBoth(ready.sheet);const revoked=photoMock.revoked.length;closePhoto(ready.sheet);closePhoto(ready.sheet);
          assert.equal(photoMock.revoked.length,revoked+1);assert(ready.sheet.body.querySelectorAll('img').every(img=>!img.src));
        ''')
