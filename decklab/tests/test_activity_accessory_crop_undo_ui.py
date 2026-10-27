"""Current-photo crop recovery verifies bytes and both previews before consent."""
import unittest

from decklab.tests import test_activity_accessory_undo_ui as accessories
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryCropUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accessories.AccessoryUndoUiTests.run_js(self, r'''
          const cropPreview=(extra={})=>{const current={...accRow(),quantity:'2',capacity:'100',image:'fixture-box.jpg',crop:'0,0,0.5,1'},
            restored={...current,crop:'0.1,0.1,0.8,0.8'};
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_crop_update',label:current.name,current,restored,
              fields:[{field:'crop',before:current.crop,after:restored.crop}],photo:{name:current.image,size:24,sha256:'c'.repeat(64),version:'e'.repeat(8)},
              photo_confirmation_required:true,...extra};};
          const cropSaved=(p=cropPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_crop_update',
            restored:{...p.restored},photo:{...p.photo},sha256:'b'.repeat(64),revision:'4321',summary:'Restored the recorded crop on the current photo.',...extra});
          const photoMock={fetches:[],blobs:[],revoked:[],images:[],modes:[],options:{},pending:[],reads:0,cancels:0};
          globalThis.Blob=class{constructor(parts,options={}){this.parts=parts;this.type=options.type||'';this.size=parts.reduce((sum,part)=>sum+(part.byteLength??part.size??part.length??0),0);}};
          URL.createObjectURL=blob=>{const url='blob:http://localhost/crop-'+(photoMock.blobs.length+1);photoMock.blobs.push({url,blob});return url;};
          URL.revokeObjectURL=url=>photoMock.revoked.push(url);
          const photoResponse=(p,options={})=>{const bodySize=options.bodySize??p.photo.size;
            const chunks=options.chunks??[new Uint8Array(bodySize)],headers=new Map([
              ['etag',options.etag===undefined?'"'+p.photo.sha256+'"':options.etag],
              ['content-type',options.type===undefined?'image/jpeg':options.type],
              ['content-length',options.length===undefined?String(p.photo.size):options.length]]);
            let index=0;return{status:options.status??200,ok:options.ok??true,redirected:options.redirected??false,
              headers:{get:name=>headers.get(name.toLowerCase())??null},
              body:options.noBody?null:{getReader:()=>({read:async()=>{photoMock.reads++;if(options.readError)throw Error('Broken photo stream');
                return index<chunks.length?{done:false,value:chunks[index++]}:{done:true,value:undefined};},
                cancel:async()=>{photoMock.cancels++;},releaseLock:()=>{}})}};};
          fetch=(url,options)=>{const request={url,options,aborts:0};photoMock.fetches.push(request);
            options.signal?.addEventListener('abort',()=>request.aborts++);const settings={...photoMock.options};
            if(settings.failure)return Promise.reject(settings.failure);
            const response=()=>photoResponse(photoMock.preview,settings);
            return settings.pending?new Promise(resolve=>photoMock.pending.push(()=>resolve(response()))):Promise.resolve(response());};
          const createPhotoElement=document.createElement;
          document.createElement=tag=>{const node=createPhotoElement(tag);if(tag!=='img')return node;
            const mode=photoMock.modes.shift()||'ok';photoMock.images.push(node);node.photoMode=mode;node.complete=false;node.naturalWidth=0;node.naturalHeight=0;
            const set=node.setAttribute.bind(node),remove=node.removeAttribute.bind(node);let source='';
            const loaded=()=>{if(!source)return;if(mode==='loadError'){node.complete=true;node.fire('error');node.onerror?.({target:node});return;}
              node.complete=mode!=='incomplete';node.naturalWidth=mode==='zero'?0:320;node.naturalHeight=mode==='zero'?0:240;
              node.fire('load');node.onload?.({target:node});};
            const assign=value=>{source=String(value||'');set('src',source);node.complete=false;node.naturalWidth=0;node.naturalHeight=0;
              if(source&&mode!=='pending')Promise.resolve().then(loaded);};
            Object.defineProperty(node,'src',{get:()=>source,set:assign});Object.defineProperty(node,'currentSrc',{get:()=>source});
            node.setAttribute=(key,value)=>{if(key==='src')assign(value);else set(key,value);};
            node.removeAttribute=key=>{if(key==='src'){source='';node.complete=false;node.naturalWidth=0;node.naturalHeight=0;}remove(key);};
            node.finishPhoto=()=>{loaded();node.resolvePhoto?.();};
            if(mode!=='loadOnly')node.decode=()=>mode==='decodeError'?Promise.reject(Error('Photo decode failed')):
              mode==='pending'?new Promise(resolve=>node.resolvePhoto=resolve):Promise.resolve();
            return node;};
          const photoSettle=async()=>{for(let i=0;i<8;i++)await settle();};
          const openCrop=async(p=cropPreview(),options={})=>{photoMock.preview=p;photoMock.options=options;
            const made=mount([accChange()],null,{kind:'sleeves',actor:null});api=async()=>p;made.trigger.click();await photoSettle();
            return{...made,sheet:[...colSheets].at(-1),p};};
          const photoConsent=sheet=>sheet.body.querySelector('input[type=checkbox]');
          const confirmPhoto=(sheet,value=true)=>{const input=photoConsent(sheet);input.checked=value;input.fire('change');return input;};
          const blockedPhoto=sheet=>{const action=save(sheet);assert(!action||action.disabled);const input=photoConsent(sheet);if(input)assert(input.disabled);};
          const closePhoto=sheet=>{sheet.close();};
        ''' + scenario)

    def test_crop_only_raw13_and_exact_photo_envelope_are_required_before_fetch(self):
        self.run_js(r'''
          const p=cropPreview(),bad=[{photo_confirmation_required:false},{photo_confirmation_required:undefined},{photo_confirmation_required:1},
            {stock_confirmation_required:true},{owner_confirmation_required:true},{kind_confirmation_required:true},{record_confirmation_required:true},
            {confirmation_required:true},{reason_required:true},{space:'home'},{profile:state.profiles[0].id},{action:'accessory_update'},
            {action:'accessory_record_update'},{current:accRow()},{restored:accRow()},{fields:[]},{fields:[...p.fields,...p.fields]},
            {restored:{...p.restored,name:'Other name'}},{restored:{...p.restored,quantity:'3'}},{restored:{...p.restored,kind:'playmat',capacity:''}},
            {restored:{...p.restored,owner:'shared'}},{restored:{...p.restored,image:'another.jpg'}},{restored:{...p.restored,crop:p.current.crop}},
            {photo:{...p.photo,url:'https://example.com/unused'}},{photo:{...p.photo,name:'other.jpg'}},{photo:{...p.photo,size:true}},
            {photo:{...p.photo,size:0}},{photo:{...p.photo,size:4194305}},{photo:{...p.photo,sha256:'c'.repeat(63)}},
            {photo:{...p.photo,sha256:'c'.repeat(64)+'\n'}},{photo:{...p.photo,version:'e'.repeat(8)+'\n'}}];
          for(const extra of bad){const before=photoMock.fetches.length,{sheet}=await openCrop(cropPreview(extra));
            assert(!save(sheet),JSON.stringify(extra));assert.equal(photoConsent(sheet),null);assert.equal(photoMock.fetches.length,before);}
          for(const side of ['current','restored'])for(const crop of ['0,0,0.01,1','0,0,1.1,1','-0.1,0,1,1','0.2,0,0.9,1','0.00001,0,0.5,1','0, 0,1,1','00,0,1,1','0.0,0,1,1']){
            const q=cropPreview();q[side].crop=crop;q.fields=[{field:'crop',before:q.current.crop,after:q.restored.crop}];
            assert.equal(activityUndoEvidence(q,42,'home',state.profiles[0].id),null,side+crop);}
        ''')

    def test_current_photo_is_fetched_once_and_both_readonly_views_share_one_verified_blob(self):
        self.run_js(r'''
          const {sheet,p}=await openCrop(),text=sheet.body.textContent.toLowerCase(),images=sheet.body.querySelectorAll('img');
          assert(text.includes('current photo'));assert(text.includes('crop'));assert.equal(images.length,2);assert.equal(photoMock.fetches.length,1);assert.equal(photoMock.blobs.length,1);
          const request=photoMock.fetches[0],blob=photoMock.blobs[0];assert.equal(request.url,'/accessory-img/fixture-box.jpg?v=eeeeeeee&viewer='+state.profile.id);
          for(const [key,value]of Object.entries({method:'GET',credentials:'same-origin',cache:'no-store',redirect:'error',mode:'same-origin'}))assert.equal(request.options[key],value,key);
          assert.equal(request.options.headers.Accept,'image/jpeg');assert.equal(request.options.headers['X-Deck-Lab-Viewer'],state.profile.id);
          assert.equal(blob.blob.size,p.photo.size);assert.equal(blob.blob.type,'image/jpeg');
          for(const image of images){assert.equal(image.src,blob.url);assert(image.complete&&image.naturalWidth>0&&image.naturalHeight>0);}
          assert.notEqual(images[0].style.width,images[1].style.width);assert.equal(sheet.body.querySelectorAll('input').length,1);
          for(const selector of ['input[type=number]','input[type=text]','textarea','select','a'])assert.equal(sheet.body.querySelectorAll(selector).length,0,selector);
          assert.equal(photoConsent(sheet).checked,false);assert(!photoConsent(sheet).disabled);assert(save(sheet).disabled);assert.equal(typeof globalThis.crypto,'undefined');
        ''')

    def test_pending_fetch_cannot_be_acknowledged_or_saved_and_ready_does_not_auto_consent(self):
        self.run_js(r'''
          const {sheet,p}=await openCrop(cropPreview(),{pending:true});blockedPhoto(sheet);let writes=0;apiWrite=async()=>{writes++;return cropSaved(p);};
          const input=photoConsent(sheet);if(input){input.checked=true;input.fire('change');}save(sheet)?.fire('click');await photoSettle();assert.equal(writes,0);
          photoMock.pending.shift()();await photoSettle();assert.equal(photoMock.blobs.length,1);assert.equal(photoConsent(sheet).checked,false);assert(save(sheet).disabled);
          confirmPhoto(sheet);assert(!save(sheet).disabled);
        ''')

    def test_all_supported_picture_types_and_whole_photo_crop_directions_can_be_reviewed(self):
        self.run_js(r'''
          for(const [ext,type] of [['jpg','image/jpeg'],['png','image/png'],['webp','image/webp']])for(const whole of ['current','restored']){
            const p=cropPreview();p.current.image=p.restored.image=p.photo.name='fixture-box.'+ext;p[whole].crop='';
            p.fields=[{field:'crop',before:p.current.crop,after:p.restored.crop}];const {sheet}=await openCrop(p,{type});
            assert.equal(photoMock.fetches.at(-1).options.headers.Accept,type);assert.equal(photoMock.blobs.at(-1).blob.type,type);
            assert.equal(sheet.body.querySelectorAll('img').length,2);assert(!photoConsent(sheet).disabled);assert(save(sheet).disabled);
            assert.equal(photoConsent(sheet).checked,false);closePhoto(sheet);
          }
        ''')

    def test_both_decodes_and_natural_dimensions_are_needed_before_acknowledgement(self):
        self.run_js(r'''
          photoMock.modes.push('ok','pending');const {sheet}=await openCrop();blockedPhoto(sheet);const images=sheet.body.querySelectorAll('img');assert.equal(images.length,2);
          assert(images[0].complete);assert(!images[1].complete);if(photoConsent(sheet)){photoConsent(sheet).checked=true;photoConsent(sheet).fire('change');}
          images[1].finishPhoto();await photoSettle();assert(!photoConsent(sheet).disabled);assert.equal(photoConsent(sheet).checked,false);assert(save(sheet).disabled);
          photoMock.modes.push('loadOnly','loadOnly');const fallback=await openCrop();assert(!photoConsent(fallback.sheet).disabled);assert.equal(fallback.sheet.body.querySelectorAll('img').length,2);
        ''')

    def test_status_redirect_etag_type_and_exact_length_failures_never_create_a_blob_or_save(self):
        self.run_js(r'''
          const p=cropPreview(),bad=[{status:403,ok:false},{status:304},{ok:false},{redirected:true},{etag:null},{etag:'W/"'+p.photo.sha256+'"'},
            {etag:'"'+'d'.repeat(64)+'"'},{etag:p.photo.sha256},{type:'image/png'},{type:'text/html'},{length:null},{length:'024'},{length:'23'},{length:'4194305'}];
          for(const options of bad){const blobs=photoMock.blobs.length,before=photoMock.fetches.length,{sheet}=await openCrop(p,options);blockedPhoto(sheet);
            assert.equal(photoMock.blobs.length,blobs,JSON.stringify(options));let writes=0;apiWrite=async()=>{writes++;return cropSaved(p);};save(sheet)?.fire('click');await photoSettle();
            assert.equal(writes,0);assert.equal(photoMock.fetches.length,before+1);closePhoto(sheet);}
        ''')

    def test_stream_overflow_truncation_errors_and_network_failure_do_not_confirm_photo(self):
        self.run_js(r'''
          const bad=[{bodySize:25},{bodySize:23},{noBody:true},{chunks:[new Uint8Array(10),new Uint8Array(15)]},
            {chunks:[[1,2,3]]},{readError:true},{failure:Error('Photo network unavailable')}];
          for(const options of bad){const blobs=photoMock.blobs.length,{sheet}=await openCrop(cropPreview(),options);blockedPhoto(sheet);assert.equal(photoMock.blobs.length,blobs);
            let writes=0;apiWrite=async()=>{writes++;return cropSaved();};save(sheet)?.fire('click');await photoSettle();assert.equal(writes,0);closePhoto(sheet);}
        ''')

    def test_each_decode_failure_zero_size_or_incomplete_image_blocks_and_releases_on_close(self):
        self.run_js(r'''
          for(const mode of ['decodeError','loadError','zero','incomplete'])for(const at of [0,1]){const before=photoMock.revoked.length;
            photoMock.modes.push(...(at===0?[mode,'ok']:['ok',mode]));const {sheet}=await openCrop();blockedPhoto(sheet);
            let writes=0;apiWrite=async()=>{writes++;return cropSaved();};save(sheet)?.fire('click');await photoSettle();assert.equal(writes,0);
            closePhoto(sheet);await photoSettle();assert.equal(photoMock.revoked.length,before+1,mode+at);}
        ''')

    def test_cancel_before_fetch_aborts_and_ignores_late_result_without_creating_object_url(self):
        self.run_js(r'''
          const before=photoMock.blobs.length,{sheet}=await openCrop(cropPreview(),{pending:true}),request=photoMock.fetches.at(-1);
          button(sheet.dialog,'Cancel').click();assert(request.options.signal.aborted);assert.equal(request.aborts,1);
          photoMock.pending.shift()();await photoSettle();assert.equal(photoMock.blobs.length,before);assert.equal(sheet.body.querySelectorAll('img').filter(img=>img.src).length,0);
        ''')

    def test_close_after_blob_or_owner_change_releases_exactly_once_and_clears_image_sources(self):
        self.run_js(r'''
          for(const mode of ['cancel','close','owner','route']){const before=photoMock.revoked.length,{sheet}=await openCrop(),images=sheet.body.querySelectorAll('img'),request=photoMock.fetches.at(-1);
            if(mode==='owner')state.profile=state.profiles[1];if(mode==='route')routeToken++;
            if(mode==='cancel')button(sheet.dialog,'Cancel').click();else closePhoto(sheet);closePhoto(sheet);await photoSettle();
            assert.equal(photoMock.revoked.length,before+1,mode);assert(request.options.signal.aborted);assert.equal(request.aborts,1);
            for(const image of images){assert(!image.src);assert.equal(image.onload,null);assert.equal(image.onerror,null);}}
        ''')

    def test_owner_or_route_change_while_fetch_pending_never_renders_late_photo(self):
        self.run_js(r'''
          for(const mode of ['owner','route']){const before=photoMock.blobs.length,{sheet}=await openCrop(cropPreview(),{pending:true});
            if(mode==='owner')state.profile=state.profiles[1];else routeToken++;photoMock.pending.shift()();await photoSettle();
            assert.equal(photoMock.blobs.length,before,mode);assert.equal(sheet.body.querySelectorAll('img').filter(img=>img.src).length,0);closePhoto(sheet);}
        ''')

    def test_pending_post_close_cleans_photo_without_cancelling_or_repeating_the_write(self):
        self.run_js(r'''
          const before=photoMock.revoked.length,{sheet,p}=await openCrop(),request=photoMock.fetches.at(-1);confirmPhoto(sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();
          closePhoto(sheet);assert.equal(photoMock.revoked.length,before+1);assert(request.options.signal.aborted);
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_photo:true}]]);
          api=async()=>freshPage();finish(cropSaved(p));await photoSettle();assert.equal(sent.length,1);old.fire('click');await photoSettle();assert.equal(sent.length,1);
          assert.equal(photoMock.revoked.length,before+1);
        ''')

    def test_photo_ack_is_explicit_resets_on_uncheck_and_cancel_and_sends_only_one_source_flag(self):
        self.run_js(r'''
          const {sheet,p}=await openCrop();let writes=0;apiWrite=async()=>{writes++;return cropSaved(p);};save(sheet).fire('click');await photoSettle();assert.equal(writes,0);
          photoConsent(sheet).checked=true;save(sheet).fire('click');await photoSettle();assert.equal(writes,0);confirmPhoto(sheet);assert(!save(sheet).disabled);
          confirmPhoto(sheet,false);assert(save(sheet).disabled);confirmPhoto(sheet);button(sheet.dialog,'Cancel').click();const fresh=await openCrop();
          assert.equal(photoConsent(fresh.sheet).checked,false);assert(save(fresh.sheet).disabled);confirmPhoto(fresh.sheet);let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(fresh.sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64),confirm_photo:true}]]);assert(photoConsent(fresh.sheet).disabled);
          finish(cropSaved(fresh.p));await photoSettle();assert(button(fresh.sheet.dialog,'Done'));old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_restored_raw13_and_all_four_photo_facts_must_match_the_exact_receipt(self):
        self.run_js(r'''
          const p=cropPreview(),bad=[{restored:null},{restored:accRow()},{photo:undefined},{photo:{...p.photo,url:'/unexpected'}},
            ...ACTIVITY_UNDO_ACCESSORY_STOCK_FIELDS.map(field=>({restored:{...p.restored,[field]:'Wrong'}})),
            ...Object.keys(p.photo).map(field=>({photo:{...p.photo,[field]:field==='size'?25:'Wrong'}})),
            {action:'accessory_update'},{action:'accessory_record_update'},{added_id:p.current.id},{removed_id:p.current.id},
            {photo_confirmation_required:true},{profile:state.profiles[0].id},{space:'home'},{saved:false},{source_id:43},
            {expect:'f'.repeat(64)},{sha256:'bad'},{revision:'0'},{revision:'9223372036854775808'},{summary:''}];
          for(const extra of bad){const {sheet}=await openCrop(p);confirmPhoto(sheet);let writes=0;apiWrite=async()=>{writes++;return cropSaved(p,extra);};
            const old=save(sheet);old.click();await photoSettle();assert(!button(sheet.dialog,'Done'),JSON.stringify(extra));assert(button(sheet.dialog,'Reload Activity'));
            old.fire('click');assert.equal(writes,1);closePhoto(sheet);}
        ''')

    def test_stale_context_preview_photo_or_detached_changed_images_cannot_save(self):
        self.run_js(r'''
          for(const mode of ['crop','photo','owner','profile','route','filter','detached','src','zero','unchecked','modal']){
            const {sheet,p,view}=await openCrop();confirmPhoto(sheet);const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return cropSaved(p);};
            if(mode==='crop')p.restored.crop='0,0,1,1';if(mode==='photo')p.photo.sha256='f'.repeat(64);if(mode==='owner')p.restored.owner='shared';
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            const image=sheet.body.querySelector('img');if(mode==='detached')image.remove();if(mode==='src')image.src='blob:http://localhost/other';
            if(mode==='zero')image.naturalWidth=0;if(mode==='unchecked')photoConsent(sheet).checked=false;if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await photoSettle();assert.equal(writes,0,mode);top?.close();closePhoto(sheet);}
        ''')

    def test_other_protocols_foreign_owner_and_endpoint_cannot_reuse_photo_consent_or_fetch(self):
        self.run_js(r'''
          assert.equal(activityUndoReceipt(cropSaved(),accPreview()),false);assert.equal(activityUndoReceipt(accSaved(),cropPreview()),false);
          assert.equal(activityUndoEvidence(accPreview({photo_confirmation_required:true}),42,'home',state.profiles[0].id),null);
          const foreign=cropPreview();foreign.current.owner=foreign.restored.owner=state.profiles[1].id;const before=photoMock.fetches.length,hidden=await openCrop(foreign);
          assert(!save(hidden.sheet));assert.equal(photoConsent(hidden.sheet),null);assert.equal(photoMock.fetches.length,before);
          const wrong=await open(cropPreview());assert(!save(wrong.sheet));assert.equal(photoMock.fetches.length,before);
          const made=await openCrop();confirmPhoto(made.sheet);made.view.undoCtx.endpoint='/api/activity/undo';let writes=0;
          apiWrite=async()=>{writes++;return cropSaved();};save(made.sheet).fire('click');await photoSettle();assert.equal(writes,0);closePhoto(made.sheet);
        ''')

    def test_existing_metadata_undo_never_reads_photos_or_requires_new_photo_controls(self):
        self.run_js(r'''
          const before=photoMock.fetches.length,{sheet,p}=await openAcc();assert.equal(photoMock.fetches.length,before);assert.equal(sheet.body.querySelectorAll('img').length,0);
          assert.equal(photoConsent(sheet),null);let sent;apiWrite=async(path,body)=>{sent=[path,body];return accSaved(p);};save(sheet).click();await photoSettle();
          same(sent,['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64)}]);assert(button(sheet.dialog,'Done'));assert.equal(photoMock.blobs.length,0);
        ''')

    def test_unknown_post_reply_blocks_retry_until_reload_and_done_releases_blob_with_depth_kept(self):
        self.run_js(r'''
          for(const failure of [Error('Lost reply'),new ApiError(409,'The current photo changed.',{})]){const {sheet}=await openCrop();confirmPhoto(sheet);let writes=0;
            apiWrite=async()=>{writes++;throw failure;};const old=save(sheet);old.click();await photoSettle();assert(button(sheet.dialog,'Reload Activity'));assert(!button(sheet.dialog,'Done'));
            old.fire('click');assert.equal(writes,1);closePhoto(sheet);}
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=cropPreview();photoMock.preview=p;photoMock.options={};api=async()=>p;trigger.click();await photoSettle();
          const sheet=[...colSheets].at(-1),before=photoMock.revoked.length;confirmPhoto(sheet);apiWrite=async()=>cropSaved(p);save(sheet).click();await photoSettle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await photoSettle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(photoMock.revoked.length,before+1);assert.equal(view.loadedPages,2);assert(view.days.querySelector('[data-activity-id="42"]'));assert.equal(location.hash,activityHref(filter));
        ''')
