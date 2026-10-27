"""Accessory text recovery has a dedicated owner/shared-scoped metadata protocol."""
import unittest

from decklab.tests import test_activity_undo_ui as updates
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class AccessoryUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        updates.ActivityUndoUiTests.run_js(self, r'''
          const accRow=extra=>({id:'fixture-box',kind:'deck_box',owner:state.profiles[0].id,brand:'Current brand',
            name:'Current fixture box',colour:'Blue',notes:'Current fixture note',link:'https://example.com/current-product',image_source:'https://example.com/current-image',capacity:'',...extra});
          const accPreview=(extra={})=>{const current=accRow(),restored=accRow({brand:'Original brand',name:'Original fixture box',colour:'',notes:'Historical <img src=x onerror=alert(1)>'});
            return{available:true,id:42,expect:'a'.repeat(64),kind:'accessory',action:'accessory_update',label:current.name,current,restored,
              fields:['brand','name','colour','notes'].map(field=>({field,before:current[field],after:restored[field]})),...extra};};
          const accSaved=(p=accPreview(),extra={})=>({saved:true,source_id:p.id,expect:p.expect,kind:'accessory',action:'accessory_update',
            restored:{...p.restored},sha256:'b'.repeat(64),revision:'4321',summary:'Restored accessory text details.',...extra});
          const accChange=(id=42,hint=true)=>candidate(id,{kinds:['sleeves'],undo:hint?{review:true,kind:'accessory'}:undefined,
            rows:[{table:'accessory',op:'UPDATE',summary:'Displayed accessory metadata'}]});
          const openAcc=async(p=accPreview())=>{const made=mount([accChange()],null,{kind:'sleeves',actor:null});
            api=async()=>p;made.trigger.click();await settle();return{...made,sheet:[...colSheets].at(-1),p};};
        ''' + scenario)

    def test_hint_uses_only_the_dedicated_hardcoded_endpoint(self):
        self.run_js(r'''
          const filter=activityFilter(new URLSearchParams({kind:'sleeves'}));assert.equal(filter.kind,'sleeves');const {trigger}=mount([accChange()],null,filter),asked=[];api=async path=>{asked.push(path);return accPreview();};trigger.click();await settle();
          same(asked,['/api/activity/accessory-undo?id=42']);assert(save([...colSheets].at(-1)));
        ''')

    def test_text_only_review_names_current_photo_kit_retention_and_has_no_physical_inputs(self):
        self.run_js(r'''
          const p=accPreview(),before=JSON.stringify(p),{sheet}=await openAcc(p),text=sheet.body.textContent;
          for(const word of ['Current fixture box','Original fixture box','Brand:','Name:','Colour:','Notes:','Deck box','fixture-box','Original brand',
            'Not recorded','Historical <img src=x onerror=alert(1)>','retains the current photo and kit','one new audited change'])assert(text.includes(word),word);
          for(const word of ['Quantity:','Capacity:','physically owned','Reason for removing'])assert(!text.includes(word),word);
          assert.equal(sheet.body.querySelector('input,textarea,select,img,a'),null);assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,2);
          assert(save(sheet));assert.equal(JSON.stringify(p),before);
        ''')

    def test_own_and_shared_rows_are_accepted_but_readonly_other_owner_is_not(self):
        self.run_js(r'''
          const shared=accPreview();shared.current.owner=shared.restored.owner='shared';const made=await openAcc(shared);assert(save(made.sheet));assert(made.sheet.body.textContent.includes('Shared'));
          const other=accPreview();other.current.owner=other.restored.owner=state.profiles[1].id;const refused=await openAcc(other);assert(!save(refused.sheet));assert(!refused.sheet.body.textContent.includes('Original fixture box'));
          assert.equal(activityUndoEvidence(accPreview(),42,'user2',state.profiles[0].id),null);assert.equal(activityUndoEvidence(accPreview(),42,'home',null),null);
        ''')

    def test_exact_meta10_shapes_ids_kinds_owners_and_changed_fields_are_required(self):
        self.run_js(r'''
          const p=accPreview(),bad=[{space:'home'},{profile:state.profiles[0].id},{action:'update'},{action:'wishlist_update'},{kind:'sleeves'},
            {current:{...p.current,quantity:'1'}},{restored:{...p.restored,image:'private.png'}},{restored:{...p.restored,id:'another-box'}},
            {restored:{...p.restored,kind:'playmat'}},{restored:{...p.restored,owner:'shared'}},{current:{...p.current,kind:'card'}},
            {current:{...p.current,id:''}},{restored:{...p.restored,name:''}},{fields:[]},{label:'Wrong label'},
            {fields:[...p.fields,{field:'quantity',before:1,after:2}]},{fields:[p.fields[0],p.fields[0]]},
            {fields:[{field:'brand',before:'Wrong',after:p.restored.brand}]}];
          for(const extra of bad){const {sheet}=await openAcc(accPreview(extra));assert(!save(sheet),JSON.stringify(extra));assert(!sheet.body.textContent.includes('Restored by Undo'));}
          const sparse=Array(4);sparse[0]=p.fields[0];assert.equal(activityUndoEvidence(accPreview({fields:sparse}),42,'home',state.profiles[0].id),null);
        ''')

    def test_one_metadata_field_can_restore_while_other_facts_stay_unchanged(self):
        self.run_js(r'''
          for(const field of ['brand','name','colour','notes']){const p=accPreview();for(const other of ['brand','name','colour','notes'])if(other!==field)p.restored[other]=p.current[other];
            p.fields=p.fields.filter(item=>item.field===field);const {sheet}=await openAcc(p);assert(save(sheet));assert(sheet.body.textContent.includes('fixture-box'));
          }
        ''')

    def test_recorded_links_restore_as_literal_wrapping_text_with_photo_provenance_warning(self):
        self.run_js(r'''
          const p=accPreview();p.restored.link='HTTPS://example.com/old-product?<literal>';
          p.restored.image_source='https://example.com/'+ 'x'.repeat(1800)+'/<img-src=x>';
          for(const field of ['link','image_source'])p.fields.push({field,before:p.current[field],after:p.restored[field]});
          const {sheet}=await openAcc(p),text=sheet.body.textContent;
          for(const word of ['Product link:','Recorded image source:',p.current.link,p.restored.link,p.current.image_source,p.restored.image_source,
            'A restored image-source URL is not checked against the current photo.'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelectorAll('.activity-undo-note').length,6);
          assert.equal(sheet.body.querySelector('a,img,input,textarea,select'),null);assert(save(sheet));
        ''')

    def test_each_recorded_url_can_restore_or_clear_without_other_metadata_changes(self):
        self.run_js(r'''
          for(const field of ['link','image_source'])for(const value of ['', 'HTTPS://example.com/old/'+field]){
            const p=accPreview();p.restored={...p.current,[field]:value};p.fields=[{field,before:p.current[field],after:value}];
            const {sheet}=await openAcc(p);assert(save(sheet));assert(sheet.body.textContent.includes(value||'Not recorded'));
            assert.equal(sheet.body.querySelector('a,img'),null);assert(activityUndoReceipt(accSaved(p),p));
          }
        ''')

    def test_url_forms_match_ordinary_lengths_and_unicode_without_normalizing_hostnames(self):
        self.run_js(r'''
          for(const field of ['link','image_source']){
            const limit=field==='link'?500:2000;
            const valid=['','HTTP://EXAMPLE.COM/A#Fragment','http\u017f://example.com/old','https://x/<literal>','https://x/\ufeffinside',
              'https://x/'+'😀'.repeat(limit-10)];
            const bad=['javascript:alert(1)','data:image/png;base64,x','https://',' https://example.com','https://example.com ',
              'https://x/\n','https://x/\u001c','https://x/\u0085','https://x/\0','https://x/\ud800','https://x/'+'x'.repeat(limit-9)];
            for(const value of valid){const p=accPreview();p.restored={...p.current,[field]:value};p.fields=[{field,before:p.current[field],after:value}];assert(activityUndoEvidence(p,42,'home',state.profiles[0].id),field+':'+value);[p.current,p.restored]=[p.restored,p.current];p.fields=p.fields.map(item=>({...item,before:item.after,after:item.before}));assert(activityUndoEvidence(p,42,'home',state.profiles[0].id),field+':current:'+value);}
            for(const side of ['current','restored'])for(const value of bad){const p=accPreview();p[side][field]=value;assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null,field+':'+value);}
          }
        ''')

    def test_recorded_link_receipt_and_late_changes_cannot_confirm_or_authorize_a_save(self):
        self.run_js(r'''
          for(const field of ['link','image_source']){
            const p=accPreview();p.restored={...p.current,[field]:'https://example.com/historical'};p.fields=[{field,before:p.current[field],after:p.restored[field]}];
            assert.equal(activityUndoReceipt(accSaved(p,{restored:{...p.restored,[field]:'https://example.com/wrong'}}),p),false);
            const {sheet}=await openAcc(p);const old=save(sheet);let writes=0;apiWrite=async()=>{writes++;return accSaved(p);};p.restored[field]+='/later';p.fields[0].after=p.restored[field];old.fire('click');await settle();assert.equal(writes,0);
          }
        ''')

    def test_recorded_capacity_review_uses_sleeved_cards_and_existing_fit_warning_semantics(self):
        self.run_js(r'''
          const p=accPreview();p.current.capacity='100';p.restored={...p.current,capacity:'40'};p.fields=[{field:'capacity',before:'100',after:'40'}];
          const {sheet}=await openAcc(p),text=sheet.body.textContent;
          for(const word of ['Box capacity (sleeved cards):','100','40','Recorded box capacity is in sleeved cards',
            'Fit warnings may change; kit assignments stay as they are','retains the current photo and kit'])assert(text.includes(word),word);
          assert.equal(sheet.body.querySelector('input,textarea,select,img,a'),null);assert(!text.includes('physically owned'));assert(!text.includes('Reason for removing'));assert(save(sheet));
        ''')

    def test_capacity_is_canonical_blank_or_positive_text_only_on_deck_boxes_on_both_sides(self):
        self.run_js(r'''
          for(const capacity of ['', '1','9999']){const p=accPreview();p.current.capacity='100';p.restored={...p.current,capacity};p.fields=[{field:'capacity',before:'100',after:capacity}];
            assert(activityUndoEvidence(p,42,'home',state.profiles[0].id));[p.current,p.restored]=[p.restored,p.current];p.fields=p.fields.map(item=>({...item,before:item.after,after:item.before}));assert(activityUndoEvidence(p,42,'home',state.profiles[0].id));}
          for(const side of ['current','restored'])for(const capacity of [0,null,'0','0100',' 100','100 ','1.0','10000','100\n','100\r','100\r\n','100\u2028','100\u2029']){
            const p=accPreview();p[side].capacity=capacity;p.fields.push({field:'capacity',before:p.current.capacity,after:p.restored.capacity});
            assert.equal(activityUndoEvidence(p,42,'home',state.profiles[0].id),null,side+':'+capacity);
            const row={...accRow({capacity}),quantity:'1',image:'',crop:''};assert.equal(activityUndoAccessoryStock(row),false);
            const common={available:true,id:42,expect:'a'.repeat(64),kind:'accessory',label:row.name};
            assert.equal(activityUndoEvidence({...common,action:'accessory_add',current:null,restored:row,confirmation_required:true},42,'home',state.profiles[0].id),null);
            assert.equal(activityUndoEvidence({...common,action:'accessory_remove',current:row,restored:null,reason_required:true},42,'home',state.profiles[0].id),null);}
          for(const kind of ['sleeves','playmat']){const p=accPreview();p.current.kind=p.restored.kind=kind;assert(activityUndoEvidence(p,42,'home',state.profiles[0].id));
            for(const side of ['current','restored']){const bad=structuredClone(p);bad[side].capacity='100';assert.equal(activityUndoEvidence(bad,42,'home',state.profiles[0].id),null);}}
        ''')

    def test_capacity_can_mix_with_text_but_actual_meta10_and_source_only_save_must_stay_exact(self):
        self.run_js(r'''
          const p=accPreview();p.current.capacity='100';p.restored.capacity='40';p.fields.push({field:'capacity',before:'100',after:'40'});
          const {sheet}=await openAcc(p);let sent;apiWrite=async(path,body)=>{sent=[path,body];return accSaved(p);};save(sheet).click();await settle();
          same(sent,['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64)}]);assert(button(sheet.dialog,'Done'));
          for(const capacity of ['60','',40])assert.equal(activityUndoReceipt(accSaved(p,{restored:{...p.restored,capacity}}),p),false);
          const missing=accSaved(p);delete missing.restored.capacity;assert.equal(activityUndoReceipt(missing,p),false);
          const fresh=await openAcc(p),old=save(fresh.sheet);let writes=0;apiWrite=async()=>{writes++;return accSaved(p);};p.restored.capacity='60';p.fields.at(-1).after='60';old.fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_save_is_one_source_receipt_request_without_metadata_or_physical_payload(self):
        self.run_js(r'''
          const {sheet,p}=await openAcc();state.library={old:true};let finish;const sent=[];
          apiWrite=(path,body)=>{sent.push([path,body]);return new Promise(done=>finish=done);};const old=save(sheet);old.click();old.fire('click');
          same(sent,[['/api/activity/accessory-undo',{id:42,expect:'a'.repeat(64)}]]);finish(accSaved(p));await settle();assert(button(sheet.dialog,'Done'));
          assert.equal(state.library,null);old.fire('click');assert.equal(sent.length,1);
        ''')

    def test_actual_full_metadata_digest_and_target_audit_revision_receipt_must_match(self):
        self.run_js(r'''
          const p=accPreview(),bad=[{kind:'collection'},{action:'update'},{space:'home'},{profile:state.profiles[0].id},
            {restored:{...p.restored,name:'Wrong'}},{restored:{...p.restored,notes:'Wrong'}},{restored:{...p.restored,id:'another-box'}},
            {restored:{...p.restored,owner:'shared'}},{restored:{...p.restored,capacity:'60'}},{sha256:'bad'},
            {revision:'0'},{revision:4321},{revision:'9223372036854775808'},{saved:false},{source_id:43},{expect:'c'.repeat(64)},{summary:''}];
          for(const extra of bad){const made=await openAcc();let writes=0;apiWrite=async()=>{writes++;return accSaved(made.p,extra);};const old=save(made.sheet);old.click();await settle();
            assert(!button(made.sheet.dialog,'Done'),JSON.stringify(extra));assert(button(made.sheet.dialog,'Reload Activity'));old.fire('click');assert.equal(writes,1);}
        ''')

    def test_accessory_and_inventory_endpoints_and_receipts_never_cross(self):
        self.run_js(r'''
          const wrong=await open(accPreview());assert(!save(wrong.sheet));const opposite=await openAcc(preview());assert(!save(opposite.sheet));
          assert.equal(activityUndoReceipt(accSaved(),preview()),false);assert.equal(activityUndoReceipt(accepted(),accPreview()),false);
          const made=await openAcc();let writes=0;apiWrite=async()=>{writes++;return accSaved(made.p);};made.view.undoCtx.endpoint='/api/activity/undo';save(made.sheet).fire('click');await settle();assert.equal(writes,0);
        ''')

    def test_stale_profile_route_filter_metadata_and_modal_cannot_authorize_a_save(self):
        self.run_js(r'''
          for(const mode of ['profile','route','filter','metadata','owner','modal']){const {sheet,p,view}=await openAcc();const old=save(sheet);let writes=0,top;apiWrite=async()=>{writes++;return accSaved(p);};
            if(mode==='profile')state.profile=state.profiles[1];if(mode==='route')routeToken++;if(mode==='filter')view.filter.kind='collection';
            if(mode==='metadata'){p.restored.brand='Changed';p.fields[0].after='Changed';}if(mode==='owner')p.current.owner=p.restored.owner='shared';if(mode==='modal')top=openSheet('Other task');
            old.fire('click');await settle();assert.equal(writes,0,mode);top?.close();}
        ''')

    def test_late_profile_and_lost_reply_never_reveal_or_retry(self):
        self.run_js(r'''
          const made=mount([accChange()]);let finish;api=()=>new Promise(done=>finish=done);made.trigger.click();const pending=[...colSheets].at(-1);state.profile=state.profiles[1];finish(accPreview());await settle();
          assert(!save(pending));assert(!pending.body.textContent.includes('Current fixture box'));
          const {sheet}=await openAcc();let writes=0;apiWrite=async()=>{writes++;throw Error('Lost reply');};const old=save(sheet);old.click();await settle();
          assert(button(sheet.dialog,'Reload Activity'));assert(!save(sheet));assert(sheet.body.textContent.includes('Historical'));old.fire('click');assert.equal(writes,1);
        ''')

    def test_done_keeps_accessory_filters_loaded_depth_and_original_change(self):
        self.run_js(r'''
          const filter={kind:'sleeves',actor:state.profiles[0].id},{view,trigger}=mount([accChange(42),accChange(41,false)],41,filter);
          api=async()=>page([accChange(40,false),accChange(39,false)],39);view.older.click();await settle();const p=accPreview();api=async()=>p;trigger.click();await settle();
          const sheet=[...colSheets].at(-1);apiWrite=async()=>accSaved(p);save(sheet).click();await settle();const asked=[];
          api=async path=>{asked.push(path);return asked.length===1?page([accChange(43,false),accChange(42,false)],42):page([accChange(41,false),accChange(40,false)],40);};
          button(sheet.dialog,'Done').click();await settle();same(asked,['/api/activity?kind=sleeves&actor='+filter.actor,'/api/activity?before=42&kind=sleeves&actor='+filter.actor]);
          assert.equal(view.loadedPages,2);assert.equal(view.shown,4);assert.equal(location.hash,activityHref(filter));assert(view.days.querySelector('[data-activity-id="42"]'));
        ''')


if __name__ == "__main__":
    unittest.main()
