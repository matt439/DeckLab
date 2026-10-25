"""The saved-editor frame changes presentation without changing its draft or controls."""
import re
import unittest

from decklab.tests import test_quick_editor_ui as quick
from decklab.tests.test_workspace_ui import NODE, WEB


SETUP = """
  toast=()=>{};
  const colour=()=>editor.dom.headerColour.node;
  const stripe=()=>colour().querySelector('.deck-stripe');
  const one=(card,qty=1)=>({qty,name:card?.name||'Unknown fixture',card});
  const identity=lists=>editorDraftIdentity({lists});
  const savedFold=()=>main.querySelector('.edit-details-fold');
"""

# The shared runner substitutes a counting changed(); these cases need the actual refresh/history path.
REAL_CHANGED = re.search(r'(?ms)^function changed\(.*?^\}', (WEB/'editor-screen.js').read_text(encoding='utf-8')).group(0)


@unittest.skipUnless(NODE,"Node.js isn't installed")
class EditorHeaderUiTests(unittest.TestCase):
    def run_js(self,scenario):
        quick.QuickEditorUiTests.run_js(self,'changed = '+REAL_CHANGED+';\n'+SETUP+scenario)

    def test_saved_header_retains_title_versions_none_yet_read_only_and_save_gates(self):
        self.run_js("""
          const title='A saved deck name long enough to wrap safely in a narrow header';
          begin({title,lists:{target:structuredClone(list),owned:null}});
          const head=main.querySelector('.edit-head');assert(head.classList.contains('edit-head-saved'));
          assert.equal(head.querySelector('h1').textContent,title);assert.equal(head.querySelector('.edit-kicker').textContent,'Editing');
          const links=head.querySelectorAll('a');assert.equal(links.length,2);assert.equal(links[0].getAttribute('href'),editHref(editor.id,'target'));
          assert.equal(links[1].getAttribute('href'),editHref(editor.id,'owned'));assert(links[1].textContent.includes('(none yet)'));
          const payload=JSON.stringify(draftBody());drawEditorHeaderIdentity();assert.equal(JSON.stringify(draftBody()),payload);
          begin({title,may_save:false});assert(editor.readOnly);assert(main.querySelector('.edit-head').textContent.includes('Trying a change'));
          assert(!main.querySelector('.bar-save'));let writes=0;apiWrite=async()=>{writes++;throw new Error('read-only');};
          await saveNow();assert.equal(writes,0);
        """)

    def test_draft_identity_matches_commander_companion_and_sideboard_policy(self):
        self.run_js("""
          const white={...elves,name:'White fixture',color_identity:['W']},colourless={...elves,name:'Colourless fixture',color_identity:[]};
          same(identity({Deck:[one(elves)],Sideboard:[one(bolt)]}),['G']);
          same(identity({Companion:[one(white)],Deck:[one(elves)],Sideboard:[one(bolt)]}),['W','G']);
          same(identity({Commander:[one(bolt)],Companion:[one(white)],Deck:[one(elves)]}),['R']);
          same(identity({Commander:[one(colourless)],Deck:[one(elves)]}),[]);
          same(identity({Commander:[one(null)],Companion:[one(white)],Deck:[one(elves)]}),['W','G']);
          same(identity({Deck:[one(null),one(elves)]}),['G']);same(identity({Deck:[one(null),one(colourless)]}),[]);
          same(identity({Commander:[one(elves)],Deck:[one({...bolt,color_identity:null})]}),['G']);
          assert.equal(identity({Commander:[one(null)],Deck:[one(null)],Sideboard:[one(bolt)]}),null);
        """)

    def test_unknown_neutral_is_distinct_from_true_colourless_and_malformed_loaded_identity(self):
        self.run_js("""
          for(const bad of [undefined,null,['bad'],['g'],['G','G'],Array(1),['G',null],['W','U','B','R','G','G']]){
            assert.equal(identity({Deck:[one({...elves,color_identity:bad})]}),null);}
          assert.equal(identity({Commander:[one({...elves,color_identity:undefined})],Deck:[one(bolt)]}),null);
          assert.equal(identity({Deck:[one(elves,0)]}),null);assert.equal(identity({Deck:[one(null)]}),null);
          begin({lists:{target:{Deck:[one(null)]},owned:null}});assert(stripe().matches('.is-unknown'));
          assert(colour().textContent.includes('Not known'));assert(!colour().textContent.includes('Colourless'));
          begin({lists:{target:{Deck:[one({...elves,color_identity:[]})]},owned:null}});
          assert(!stripe().matches('.is-unknown'));assert(stripe().getAttribute('style').includes('--stripe-c'));
          assert(colour().textContent.includes('Colourless'));
        """)

    def test_metadata_and_quantity_updates_keep_stripe_details_fields_and_focus_when_identity_is_unchanged(self):
        self.run_js("""
          begin();const node=stripe(),fold=savedFold(),field=document.getElementById('f-archetype'),status=document.getElementById('f-status');
          fold.open=true;fold.fire('toggle');assert(editor.detailsOpen);field.focus();input('f-archetype','New words');
          assert(stripe()===node);assert(savedFold()===fold);assert(document.getElementById('f-status')===status);
          assert(document.activeElement===field);const uid=editor.lists.Deck[0].uid;setQty(uid,5);
          assert(stripe()===node&&savedFold()===fold&&document.activeElement===field);assert(editor.detailsOpen&&fold.open);
          const history=editor.history.length,payload=JSON.stringify(draftBody()),calls=[];
          apiWrite=async(p,b)=>{calls.push([p,b]);throw new Error('presentation only');};
          fold.open=false;fold.fire('toggle');assert.equal(editor.detailsOpen,false);
          window.matchMedia('(min-width: 1000px)').matches=true;window.matchMedia('(min-width: 1000px)').fire('change');
          assert(savedFold()===fold&&stripe()===node);assert.equal(editor.history.length,history);assert.equal(JSON.stringify(draftBody()),payload);same(calls,[]);
        """)

    def test_real_remove_undo_and_draft_restore_refresh_only_current_list_identity(self):
        self.run_js("""
          const source={Deck:[one(elves)]};begin({lists:{target:source,owned:null}});assert(stripe().getAttribute('style').includes('--stripe-g'));
          const uid=editor.lists.Deck[0].uid;removeLine(uid);assert(stripe().matches('.is-unknown'));
          assert(undoLast());assert(stripe().getAttribute('style').includes('--stripe-g'));
          removeLine(editor.lists.Deck[0].uid);addCard(bolt,'Deck');assert(stripe().getAttribute('style').includes('--stripe-r'));
          const body=JSON.stringify(draftBody());saveDraft(editor);closeEditor();begin({lists:{target:source,owned:null}});
          assert(stripe().getAttribute('style').includes('--stripe-r'));assert.equal(JSON.stringify(draftBody()),body);
        """)

    def test_full_saved_editor_keeps_one_existing_fold_and_field_tree_across_identity_and_width_updates(self):
        self.run_js("""
          window.matchMedia('(min-width: 600px)').matches=true;startEditor({mode:'edit',view:view(),version:'target'});
          assert(!editor.quick);const fold=savedFold(),field=document.getElementById('f-archetype'),host=editor.dom.details;
          assert.equal(fold.tag,'details');assert(fold.contains(host));assert(!editor.dom.more);assert.equal(main.querySelectorAll('.edit-details-fold').length,1);
          fold.open=true;fold.fire('toggle');field.focus();input('f-archetype','Full editor keeps current fields');
          const before=JSON.stringify(draftBody());window.matchMedia('(min-width: 1000px)').matches=false;
          window.matchMedia('(min-width: 1000px)').fire('change');drawEditorHeaderIdentity();
          assert(savedFold()===fold&&editor.dom.details===host&&document.getElementById('f-archetype')===field);
          assert(document.activeElement===field&&fold.open&&editor.detailsOpen);assert.equal(JSON.stringify(draftBody()),before);
        """)

    def test_new_and_copy_title_modes_and_original_new_details_remain_unchanged(self):
        self.run_js("""
          startEditor({mode:'new',kind:'casual'});assert.equal(main.querySelector('h1').textContent,'New deck');
          assert(!main.querySelector('.edit-kicker'));assert(!main.querySelector('.edit-head-colour'));assert(!savedFold());
          assert(document.getElementById('f-title'));assert(main.querySelector('.edit-details-new'));
          const source=view({id:'product/fixture',title:'Published fixture',editable:false,
            new_deck:{kind:'casual',title:'My copy',from:'product/fixture'}});
          startEditor({mode:'new',view:source,from:'product/fixture'});assert.equal(main.querySelector('h1').textContent,'Save as a new deck');
          assert(main.querySelector('.deck-format').textContent.includes('Published fixture'));
          assert(!main.querySelector('.edit-kicker'));assert(!savedFold());assert.equal(draftBody().from,'product/fixture');
        """)

    def test_unstarted_play_now_uses_neutral_then_existing_start_action_reveals_loaded_identity(self):
        self.run_js("""
          begin({lists:{target:structuredClone(list),owned:null}},{version:'owned'});assert(stripe().matches('.is-unknown'));
          const version=editor.version;assert(noOwnedList());const title=main.querySelector('h1').textContent;
          startOwned();assert.equal(editor.version,version);assert(!noOwnedList());assert.equal(main.querySelector('h1').textContent,title);
          assert(stripe().getAttribute('style').includes('--stripe-g'));assert(main.querySelector('.none-yet'));
        """)

    def test_only_current_check_hydration_refreshes_unknown_stripe_without_touching_fields_or_payload(self):
        self.run_js("""
          begin({lists:{target:{Deck:[{qty:1,name:elves.name,card:null}]},owned:null}});assert(stripe().matches('.is-unknown'));
          setQty(editor.lists.Deck[0].uid,2);const ed=editor,fold=savedFold(),field=document.getElementById('f-archetype');
          fold.open=true;fold.fire('toggle');field.focus();const before=JSON.stringify(draftBody()),history=ed.history.length,replies=[],calls=[];
          apiWrite=(path,body)=>new Promise(resolve=>{calls.push([path,body]);replies.push(resolve);});
          const first=runCheck(),second=runCheck();const answer={blocks:[],warnings:[],lists:{target:{Deck:[{qty:2,name:elves.name,card:elves}]}}};
          replies[0](answer);await first;assert(stripe().matches('.is-unknown'));assert.equal(ed.lists.Deck[0].card,null);
          replies[1](answer);await second;assert(stripe().getAttribute('style').includes('--stripe-g'));
          assert.equal(calls.length,2);assert(calls.every(([path])=>path==='/api/deck/check'));
          assert.equal(JSON.stringify(draftBody()),before);assert.equal(ed.history.length,history);
          assert(savedFold()===fold&&fold.open&&document.getElementById('f-archetype')===field&&document.activeElement===field);
        """)

    def test_retained_decorative_context_rejects_route_profile_version_id_detachment_and_old_editor(self):
        self.run_js("""
          for(const mode of ['route','profile','version','id','detached','leaving','old-editor']){
            state.profile=state.profiles[1];const ed=begin(),host=colour(),before=host.children.slice();
            ed.lists={Deck:[newLine(one(bolt))]};if(mode==='route')++routeToken;
            if(mode==='profile')state.profile=state.profiles[2];if(mode==='version')ed.version='owned';if(mode==='id')ed.id='casual/other';
            if(mode==='detached')host.remove();if(mode==='leaving')ed.leaving=true;if(mode==='old-editor')editor={...ed,dom:{}};
            drawEditorHeaderIdentity(ed);assert(host.children.every((node,i)=>node===before[i]),mode);assert.equal(host.children.length,before.length,mode);
          }
        """)


    def test_saved_details_resize_reveals_same_field_without_refocus_or_draft_mutation(self):
        self.run_js("""
          window.matchMedia('(min-width: 600px)').matches=true;startEditor({mode:'edit',view:view(),version:'target'});
          const ed=editor,fold=savedFold(),field=document.getElementById('f-archetype'),host=ed.dom.details;
          fold.open=true;fold.fire('toggle');field.focus();input('f-archetype','Keep these exact field words');
          const payload=JSON.stringify(draftBody()),history=JSON.stringify(ed.history),dirty=ed.dirty,storage=JSON.stringify(saved);
          let top=399,focusCalls=0;const calls=[],frames=[],focus=field.focus.bind(field);
          field.focus=opts=>{focusCalls++;focus(opts);};requestAnimationFrame=fn=>frames.push(fn);
          field.getBoundingClientRect=()=>({left:30,right:500,top,bottom:top+32,width:470,height:32});
          const header=el('header',{class:'topbar'});document.body.append(header);
          header.getBoundingClientRect=()=>({left:0,right:1000,top:0,bottom:56,width:1000,height:56});
          ed.dom.bar.getBoundingClientRect=()=>({left:0,right:1000,top:269,bottom:330,width:1000,height:61});
          window.innerHeight=330;Object.assign(window.visualViewport,{offsetTop:0,width:1000,height:330});
          window.scrollBy=options=>{calls.push(options);top-=options.top;};let writes=0;apiWrite=async()=>{writes++;throw new Error('resize only');};
          window.fire('resize');assert.equal(top,229);assert.equal(calls.length,1);assert.equal(calls[0].behavior,'auto');
          frames.splice(0).forEach(fn=>fn());window.visualViewport.fire('resize');frames.splice(0).forEach(fn=>fn());
          assert.equal(calls.length,1);assert.equal(focusCalls,0);assert(document.activeElement===field);
          assert(savedFold()===fold&&ed.dom.details===host&&document.getElementById('f-archetype')===field&&fold.open&&ed.detailsOpen);
          assert.equal(field.value,'Keep these exact field words');assert.equal(JSON.stringify(draftBody()),payload);
          assert.equal(JSON.stringify(ed.history),history);assert.equal(ed.dirty,dirty);assert.equal(JSON.stringify(saved),storage);assert.equal(writes,0);
        """)

    def test_details_reveal_uses_visual_viewport_and_only_horizontally_overlapping_chrome(self):
        self.run_js("""
          window.matchMedia('(min-width: 600px)').matches=true;startEditor({mode:'edit',view:view(),version:'target'});
          const ed=editor,fold=savedFold(),field=document.getElementById('f-archetype');fold.open=true;field.focus();
          let top=20,headerLeft=0,barLeft=600;const calls=[];requestAnimationFrame=()=>{};
          field.getBoundingClientRect=()=>({left:30,right:400,top,bottom:top+32,width:370,height:32});
          const header=el('header',{class:'topbar'});document.body.append(header);
          header.getBoundingClientRect=()=>({left:headerLeft,right:headerLeft+400,top:0,bottom:72,width:400,height:72});
          ed.dom.bar.getBoundingClientRect=()=>({left:barLeft,right:barLeft+400,top:270,bottom:330,width:400,height:60});
          Object.assign(window.visualViewport,{offsetTop:24,height:300,width:600});
          window.scrollBy=options=>{calls.push(options.top);top-=options.top;};revealEditorDetailsFocus();assert.equal(top,80);
          headerLeft=600;top=280;calls.length=0;revealEditorDetailsFocus();assert.equal(calls.length,0); // Bottom312 is inside visual bottom324.
          barLeft=0;revealEditorDetailsFocus();assert.equal(top,230);assert.equal(calls.length,1);
          top=25;barLeft=600;calls.length=0;revealEditorDetailsFocus();assert.equal(calls.length,0); // Already visible: no comfort-margin scroll.
        """)

    def test_tall_details_target_aligns_once_and_closed_summary_can_be_revealed(self):
        self.run_js("""
          begin();const ed=editor,fold=savedFold(),field=document.getElementById('f-archetype');fold.open=true;field.focus();
          let top=-50,height=400;const calls=[],frames=[];requestAnimationFrame=fn=>frames.push(fn);
          field.getBoundingClientRect=()=>({left:30,right:400,top,bottom:top+height,width:370,height});
          const header=el('header',{class:'topbar'});document.body.append(header);
          header.getBoundingClientRect=()=>({left:0,right:500,top:0,bottom:56,width:500,height:56});
          ed.dom.bar.getBoundingClientRect=()=>({left:0,right:500,top:90,bottom:100,width:500,height:10});
          Object.assign(window.visualViewport,{offsetTop:0,height:100,width:393});
          window.scrollBy=options=>{calls.push(options.top);top-=options.top;};revealEditorDetailsFocus();assert.equal(top,64);
          frames.splice(0).forEach(fn=>fn());revealEditorDetailsFocus();frames.splice(0).forEach(fn=>fn());assert.equal(calls.length,1);
          top=140;height=32;revealEditorDetailsFocus();assert(top>=56&&top+height<=90);
          frames.splice(0).forEach(fn=>fn());assert.equal(calls.length,2); // Fits34px actual space, even with less padding.
          fold.open=false;const summary=fold.querySelector('summary');summary.focus();top=140;height=44;
          summary.getBoundingClientRect=field.getBoundingClientRect;revealEditorDetailsFocus();assert.equal(top,64);assert(document.activeElement===summary);
          header.getBoundingClientRect=()=>({left:0,right:500,top:0,bottom:200,width:500,height:200});
          const before=calls.length;top=250;revealEditorDetailsFocus();assert.equal(calls.length,before); // No usable region.
        """)

    def test_saved_details_reveal_refuses_invalid_context_busy_modal_hidden_or_disabled_target(self):
        self.run_js("""
          for(const mode of ['closed','disabled','aria-disabled','hidden','asking','leaving','saving','dialog','profile','editor-profile','id','version','route','header','detached','page']){
            state.profile=state.profiles[1];const ed=begin(),fold=savedFold(),field=document.getElementById('f-archetype');fold.open=true;field.focus();
            field.getBoundingClientRect=()=>({left:30,right:400,top:999,bottom:1031,width:370,height:32});
            let scrolls=0;window.scrollBy=()=>{scrolls++;};let modal;requestAnimationFrame=()=>{throw new Error('invalid context must not schedule');};
            if(mode==='closed')fold.open=false;if(mode==='disabled')field.disabled=true;if(mode==='aria-disabled')field.setAttribute('aria-disabled','true');
            if(mode==='hidden')fold.setAttribute('hidden','');if(['asking','leaving','saving'].includes(mode))ed[mode]=true;
            if(mode==='dialog'){modal=el('dialog',{open:true});document.body.append(modal);}if(mode==='profile')state.profile=state.profiles[2];
            if(mode==='editor-profile')ed.profile='other';if(mode==='id')ed.id='casual/other';if(mode==='version')ed.version='owned';
            if(mode==='route')++routeToken;if(mode==='header')ed.dom.headerColour.node.remove();if(mode==='detached')field.remove();if(mode==='page')ed.dom.page.remove();
            const active=document.activeElement;revealEditorDetailsFocus();assert.equal(scrolls,0,mode);assert(document.activeElement===active,mode);modal?.remove();
          }
        """)

    def test_deferred_details_reveal_rechecks_exact_editor_header_fold_and_focus(self):
        self.run_js("""
          for(const mode of ['focus','dialog','asking','leaving','saving','profile','editor-profile','id','version','route','header-context','redraw','fold','disabled','closed','old-editor','page-record']){
            state.profile=state.profiles[1];const ed=begin(),fold=savedFold(),field=document.getElementById('f-archetype');fold.open=true;field.focus();
            let top=999,scrolls=0;const frames=[];requestAnimationFrame=fn=>frames.push(fn);
            field.getBoundingClientRect=()=>({left:30,right:400,top,bottom:top+32,width:370,height:32});
            ed.dom.bar.getBoundingClientRect=()=>({left:0,right:500,top:760,bottom:852,width:500,height:92});
            window.scrollBy=options=>{scrolls++;top-=options.top;};revealEditorDetailsFocus();assert.equal(frames.length,1);assert.equal(scrolls,1);top=999;
            let modal;if(mode==='focus'){const outside=el('input');main.append(outside);outside.focus();}
            if(mode==='dialog'){modal=el('dialog',{open:true});document.body.append(modal);}if(['asking','leaving','saving'].includes(mode))ed[mode]=true;
            if(mode==='profile')state.profile=state.profiles[2];if(mode==='editor-profile')ed.profile='other';if(mode==='id')ed.id='casual/other';
            if(mode==='version')ed.version='owned';if(mode==='route')++routeToken;if(mode==='header-context')ed.dom.headerColour={...ed.dom.headerColour};
            if(mode==='redraw')drawEditor();if(mode==='fold')fold.remove();if(mode==='disabled')field.disabled=true;if(mode==='closed')fold.open=false;
            if(mode==='old-editor')editor={...ed,dom:{}};if(mode==='page-record')ed.dom.page=el('div');
            const active=document.activeElement;frames.forEach(fn=>fn());assert.equal(scrolls,1,mode);assert(document.activeElement===active,mode);modal?.remove();
          }
        """)

    def test_new_copy_and_outside_fold_focus_remain_untouched_with_one_global_hook(self):
        self.run_js("""
          const count=()=>[(window.events.get('resize')||[]).filter(fn=>fn===revealEditorDetailsFocus).length,
            (window.visualViewport.events.get('resize')||[]).filter(fn=>fn===revealEditorDetailsFocus).length];same(count(),[1,1]);
          for(const mode of ['new','copy','outside']){
            state.profile=state.profiles[1];if(mode==='new')startEditor({mode:'new',kind:'casual'});
            if(mode==='copy')startEditor({mode:'new',view:view({id:'product/fixture',editable:false,
              new_deck:{kind:'casual',title:'Copy',from:'product/fixture'}}),from:'product/fixture'});
            if(mode==='outside')begin();const field=mode==='outside'?el('input'):document.getElementById('f-title');
            if(mode==='outside')main.append(field);field.focus();let scrolls=0;window.scrollBy=()=>{scrolls++;};
            requestAnimationFrame=()=>{throw new Error('not a saved fold');};const payload=JSON.stringify(draftBody());
            revealEditorDetailsFocus();assert.equal(scrolls,0);assert(document.activeElement===field);assert.equal(JSON.stringify(draftBody()),payload);same(count(),[1,1]);
          }
        """)


class EditorHeaderSourceTests(unittest.TestCase):
    def test_casual_saved_frame_and_border_inclusive_fold_have_minimum_query_lab_reset(self):
        css=(WEB/'editor.css').read_text(encoding='utf-8').split('/* Saved editor only:',1)[1].split('/*',1)[0]
        self.assertIn('font-size: var(--fs-eyebrow); font-weight: var(--fw-semibold)',css)
        self.assertIn('font-size: var(--fs-lg); font-weight: var(--fw-heavy)',css)
        self.assertIn('height: var(--stripe-h)',css)
        self.assertIn('min-height: 60px; box-sizing: border-box; padding: 0',css)
        self.assertIn('min-height: calc(60px - 2px)',css)
        self.assertIn('@media (min-width: 1000px)',css)
        self.assertNotIn('max-width: 999',css)
        self.assertNotIn('.edit-details-new',css)

    def test_details_reveal_has_single_global_hooks_and_no_focus_model_or_write_calls(self):
        source=(WEB/'editor-screen.js').read_text(encoding='utf-8')
        helper=re.search(r'(?ms)^function revealEditorDetailsFocus\(.*?^\}',source).group(0)
        for forbidden in ('.focus(', 'scrollIntoView', 'changed(', 'drawEditor(', 'queueDraft(', 'apiWrite(', 'saveNow('):
            self.assertNotIn(forbidden,helper)
        self.assertEqual(source.count('window.addEventListener("resize", revealEditorDetailsFocus)'),1)
        self.assertEqual(source.count('window.visualViewport.addEventListener("resize", revealEditorDetailsFocus)'),1)
        self.assertIn('Math.abs(delta) > .5',helper)
