"""One current packing chooser: responsive mounting, exact controls, focus and guarded previews."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB


SETUP = """
  const media=window.matchMedia('(min-width: 1000px)');
  const width = narrow => { media.matches=!narrow;media.fire('change'); };
  const chooserData = (count=1) => {
    const data=plan();data.choices=Array.from({length:14},(_,i)=>({id:i?'casual/d'+i:'casual/a',title:'Fixture '+i,
      status:i<3?'built':i<5?'building':'idea',versions:['target','owned'],usual_opponents:i===0?['casual/d1']:[],
      sideboards:{target:[{name:'Beta',quantity:3}],owned:[{name:'Beta',quantity:1}]}}));
    data.choices.push({id:'casual/broken',title:'Not available',error:'fixture parse error',versions:['target']},
      {id:'casual/no-version',title:'No list',versions:[]});
    data.selections=data.choices.slice(0,count).map(c=>({id:c.id,version:'target'}));return data;
  };
  const current = () => packingProgressView;
  const control = (view,id,kind) => view.chooser.querySelectorAll('[data-pack-control]').find(n=>
    n.getAttribute('data-pack-id')===id&&n.getAttribute('data-pack-control')===kind);
  const selectBox = (view,id,value) => {const box=control(view,id,'choose');box.focus();box.checked=value;box.fire('change');};
  const railGeometry = (view, options={}) => {
    window.innerHeight=420;window.visualViewport=null;window.scrollY=0;
    const f={top:176,height:388,base:428,barLeft:324,headerBottom:0,frames:[],focuses:0,...options};
    requestAnimationFrame=fn=>{f.frames.push(fn);return f.frames.length;};
    const target=control(view,'casual/a','scope'),focus=target.focus.bind(target);
    target.focus=opts=>{f.focuses++;focus(opts);};view.chooser.scrollTop=0;
    view.chooser.getBoundingClientRect=()=>({left:24,right:324,top:f.top,bottom:f.top+f.height,width:300,height:f.height});
    target.getBoundingClientRect=()=>({left:56,right:304,top:f.base-view.chooser.scrollTop,
      bottom:f.base-view.chooser.scrollTop+32,width:248,height:32});
    view.bar.node.getBoundingClientRect=()=>({left:f.barLeft,right:984,top:360,bottom:420,width:984-f.barLeft,height:60});
    const header=document.querySelector('.topbar')||el('header',{class:'topbar'});if(!header.isConnected)document.body.append(header);
    header.getBoundingClientRect=()=>({left:0,right:1000,top:0,bottom:f.headerBottom,width:1000,height:f.headerBottom});
    f.target=target;return f;
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyChooserTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_same_launcher_is_first_plan_child_and_hidden_slot_preserves_resize_focus(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current(),launcher=v.chooserLaunch,rail=v.chooserRail;
          const assertMount=narrow=>{assert(v.planMain.children[0]===launcher);assert(launcher.isConnected);
            assert.equal(v.root.querySelectorAll('.pack-chooser-launcher').length,1);assert.equal(launcher.hidden,!narrow);
            assert.equal(v.chooserSlot.hidden,narrow);assert.equal(rail.hidden,narrow);
            assert.equal(v.chooserSlot.children.length,1);assert(v.chooserSlot.children[0]===rail);};
          assertMount(true);launcher.focus();width(false);assertMount(false);assert(document.activeElement===v.chooserHeading);
          const scope=control(v,'casual/a','scope');scope.focus();width(true);assertMount(true);assert(document.activeElement===launcher);
          launcher.click();const sheet=v.chooserState.sheet;assert(sheet);assert(sheet.body.contains(v.chooser));
          sheet.close();assertMount(true);assert(document.activeElement===launcher);assert(!v.chooser.isConnected);
          width(false);assertMount(false);assert(rail.contains(v.chooser));width(true);assertMount(true);
          const outside=el('button',{text:'Current route'});main.append(outside);outside.focus();v.root.remove();
          const count=v.seq;media.matches=true;media.fire('change');launcher.click();
          assert(v.chooserState.disposed);assert(!v.chooserState.sheet);assert(document.activeElement===outside);assert.equal(v.seq,count);
          width(false);drawAssembly(chooserData(),routeToken);await settle();const fresh=current();
          assert(!fresh.chooserSlot.hidden);assert(!fresh.chooserRail.hidden);assert(fresh.chooserLaunch.hidden);
          assert(fresh.planMain.children[0]===fresh.chooserLaunch);assert(fresh.chooserRail.contains(fresh.chooser));
        """)

    def test_partial_rail_reveals_control_with_eight_pixel_gap_and_ignores_adjacent_plan_bar(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current(),f=railGeometry(v);
          packChooserFocus(v,{id:'casual/a',control:'scope'});
          assert(document.activeElement===f.target);assert.equal(v.chooser.scrollTop,48);
          assert.equal(f.target.getBoundingClientRect().bottom,412);assert.equal(window.scrollY,0);
          assert(!v.chooser.scrolled);assert.equal(f.frames.length,1);f.frames.shift()();
          assert.equal(v.chooser.scrollTop,48);assert.equal(f.focuses,1);
        """)

    def test_reveal_respects_only_actual_horizontal_header_and_bar_occlusion(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current(),f=railGeometry(v,{barLeft:24});
          packChooserFocus(v,{id:'casual/a',control:'scope'});assert.equal(v.chooser.scrollTop,108);
          assert.equal(f.target.getBoundingClientRect().bottom,352);
          f.top=68;f.base=150;f.headerBottom=100;v.chooser.scrollTop=100;
          packChooserFocus(v,{id:'casual/a',control:'scope'});assert.equal(v.chooser.scrollTop,42);
          assert.equal(f.target.getBoundingClientRect().top,108);assert.equal(f.focuses,2);
        """)

    def test_post_render_frame_rechecks_current_geometry_and_only_scrolls(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current(),f=railGeometry(v);
          packChooserFocus(v,{id:'casual/a',control:'scope'});assert.equal(v.chooser.scrollTop,48);
          f.base=550;assert(f.target.getBoundingClientRect().bottom>420);f.frames.shift()();
          assert.equal(v.chooser.scrollTop,170);assert.equal(f.target.getBoundingClientRect().bottom,412);
          assert(document.activeElement===f.target);assert.equal(f.focuses,1);assert.equal(f.frames.length,0);
        """)

    def test_offscreen_rail_aligns_once_before_revealing_its_owned_control(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current(),f=railGeometry(v,{top:600,base:850});
          let aligns=0;v.chooser.scrollIntoView=()=>{aligns++;f.top=12;f.base=262;};
          packChooserFocus(v,{id:'casual/a',control:'scope'});assert.equal(aligns,1);
          const rect=f.target.getBoundingClientRect();assert(rect.top>=20&&rect.bottom<=412);
          f.frames.shift()();assert.equal(aligns,1);assert.equal(f.focuses,1);
        """)

    def test_deferred_reveal_ignores_stale_view_route_person_focus_identity_and_resizes(self):
        self.run_js("""
          for(const mode of ['route','profile','detached','disposed','disabled','saving','reviewing','focus','identity','replaced','resize','sheet','dialog','viewer']){
            state.profile={id:'matt',role:'admin',space:'home'};state.may=null;media.matches=true;clear(main);
            drawAssembly(chooserData(),routeToken);await settle();const v=current(),f=railGeometry(v);
            packChooserFocus(v,{id:'casual/a',control:'scope'});const callback=f.frames.shift();f.base=550;
            let overlay=null;if(mode==='route')++routeToken;if(mode==='profile')state.profile={id:'other'};
            if(mode==='detached')v.root.remove();if(mode==='disposed')packDisposeChooser(v);
            if(mode==='disabled'){v.saving=true;packChooserSync(v);}
            if(mode==='saving'||mode==='reviewing'){v[mode]=true;assert(!f.target.disabled);}
            if(mode==='focus'){const outside=el('button',{text:'Other control'});v.root.append(outside);outside.focus();}
            if(mode==='identity')f.target.setAttribute('data-pack-control','old-scope');
            if(mode==='replaced')drawPackPicks(v);
            if(mode==='resize'||mode==='sheet')width(true);
            if(mode==='sheet'){packRevealChooser(v);f.target.focus();}
            if(mode==='dialog'){overlay=openSheet('Unrelated modal');assert(document.activeElement===f.target);}
            if(mode==='viewer'){overlay=el('dialog',{class:'viewer',open:''});document.body.append(overlay);assert(document.activeElement===f.target);}
            const scroll=v.chooser.scrollTop,focused=document.activeElement,focuses=f.focuses;
            callback();assert.equal(v.chooser.scrollTop,scroll,mode);assert(document.activeElement===focused,mode);
            assert.equal(f.focuses,focuses,mode);
            if(overlay?.close)overlay.close();else overlay?.remove();
          }
        """)

    def test_clamped_local_scroll_remeasures_and_aligns_a_short_rail_once(self):
        self.run_js("""
          for(const above of [false,true]){
            clear(main);drawAssembly(chooserData(),routeToken);await settle();const v=current();
            const f=railGeometry(v,above?{top:0,height:300,base:20,headerBottom:56}:{top:300,height:300,base:520});
            const attempts=[];Object.defineProperty(v.chooser,'scrollTop',{get:()=>0,set:n=>attempts.push(n)});
            let aligns=0;v.chooser.scrollIntoView=()=>{aligns++;f.top=above?68:12;f.base=above?88:232;};
            packChooserFocus(v,{id:'casual/a',control:'scope'});assert.equal(aligns,1);assert.equal(v.chooser.scrollTop,0);
            assert.equal(attempts.length,1);assert.equal(attempts[0],above?0:140);
            const rect=f.target.getBoundingClientRect();assert(rect.top>=Math.max(f.top,f.headerBottom)+8&&rect.bottom<=412);
            f.frames.shift()();assert.equal(aligns,1);assert.equal(attempts.length,1);assert.equal(f.focuses,1);
          }
        """)

    def test_fractional_css_gap_uses_the_same_minimum_query_as_the_rail(self):
        self.run_js("""
          // innerWidth may round a fractional CSS viewport: neither legacy endpoint query need match.
          window.innerWidth=999;window.matchMedia('(max-width: 999px)').matches=false;media.matches=false;
          drawAssembly(chooserData(),routeToken);await settle();const v=current();
          assert(v.chooserState.media===window.matchMedia('(min-width: 1000px)'));
          assert(!v.chooserState.wide);assert(!v.chooserLaunch.hidden);assert(v.chooserRail.hidden);assert(!v.chooser.isConnected);
          v.chooserLaunch.click();assert(v.chooserState.sheet.body.contains(v.chooser));
          const scope=control(v,'casual/a','scope');scope.focus();media.matches=true;media.fire('change');
          assert(v.chooserState.wide);assert(v.chooserLaunch.hidden);assert(!v.chooserRail.hidden);
          assert(v.chooserRail.contains(v.chooser));assert(document.activeElement===scope);
          media.matches=false;media.fire('change');assert(!v.chooserLaunch.hidden);assert(document.activeElement===v.chooserLaunch);
          assert(!v.chooser.isConnected);assert.equal(v.selected[0].version,'target');
        """)

    def test_same_nodes_open_close_without_requests_and_one_status_region_moves(self):
        self.run_js("""
          width(true);const data=chooserData();drawAssembly(data,routeToken);await settle();const v=current();
          const original=v.chooser,picks=v.picks,box=control(v,'casual/a','choose'),message=v.message;
          let calls=[];mockApi((p,b)=>{calls.push([p,b]);throw new Error('no calculation on dismiss');});
          const selections=JSON.stringify(v.selected),seq=v.seq;assert(!original.isConnected);assert(v.chooserLaunch.isConnected);
          v.chooserLaunch.click();let sheet=v.chooserState.sheet;assert(sheet);assert(sheet.body.contains(original));
          assert(v.picks===picks);assert(control(v,'casual/a','choose')===box);assert(sheet.body.contains(message));
          assert.equal(sheet.body.querySelectorAll('.pack-message').length,1);assert(!v.messageSlot.contains(message));
          assert.equal(assemblySheets.size,0);assert.equal(v.chooserLaunch.getAttribute('aria-expanded'),'true');
          sheet.body.scrollTop=122;v.chooserDismiss.click();assert(!sheet.dialog.isConnected);assert(!original.isConnected);
          assert(v.messageSlot.contains(message));assert(document.activeElement===v.chooserLaunch);
          v.chooserLaunch.click();sheet=v.chooserState.sheet;assert.equal(sheet.body.scrollTop,122);
          assert(control(v,'casual/a','choose')===box);sheet.close();assert(!original.isConnected);
          same(calls,[]);assert.equal(JSON.stringify(v.selected),selections);assert.equal(v.seq,seq);
        """)

    def test_presets_keep_sheet_open_and_review_sheets_close_while_exact_preview_is_unchanged(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);
          const sheet=v.chooserState.sheet;const review=openAssemblySheet(v,'Fixture review');assert.equal(assemblySheets.size,1);
          const calls=[];mockApi(async(p,b)=>{calls.push([p,b]);return {...chooserData(5),selections:b.decks};});
          control(v,'','preset').click();assert(v.chooserState.sheet===sheet);assert(!review.sheet.dialog.isConnected);
          assert.equal(assemblySheets.size,0);assert.equal(v.selected.length,5);assert(v.chooserDismiss.textContent==='Show the plan');
          flushTimers();await settle();same(calls,[['/api/assembly/preview',{decks:chooserData().choices.slice(0,5).map(c=>({id:c.id,version:'target'}))}]]);
          assert(v.chooserState.sheet===sheet);assert(sheet.body.contains(v.chooser));control(v,'','clear').click();
          assert(v.chooserState.sheet===sheet);assert.equal(v.selected.length,0);assert.equal(v.chooserDismiss.textContent,'Close');
        """)

    def test_available_choices_are_not_capped_and_thirteenth_selection_is_refused_with_rollback(self):
        self.run_js("""
          drawAssembly(chooserData(12),routeToken);await settle();const v=current();assert.equal(v.choices.length,14);
          const boxes=()=>v.chooser.querySelectorAll('[data-pack-control]').filter(n=>n.getAttribute('data-pack-control')==='choose');
          assert.equal(boxes().length,14);assert(!v.chooser.textContent.includes('Not available'));assert(!v.chooser.textContent.includes('No list'));
          const extra=control(v,'casual/d12','choose'),seq=v.seq;assert(extra.disabled);extra.checked=true;extra.fire('change');
          assert.equal(extra.checked,false);assert.equal(v.selected.length,12);assert.equal(v.seq,seq);
          selectBox(v,'casual/a',false);assert.equal(v.selected.length,11);const fresh=control(v,'casual/d12','choose');assert(!fresh.disabled);
          extra.checked=true;extra.fire('change');assert.equal(extra.checked,false);assert.equal(v.selected.length,11);
          fresh.checked=true;fresh.fire('change');assert.equal(v.selected.length,12);fresh.fire('change');assert.equal(v.selected.length,12);
          assert.equal(new Set(v.selected.map(s=>s.id)).size,12);assert.equal(boxes().length,14);
        """)

    def test_synchronous_redraw_restores_fresh_control_and_group_expansion_and_scroll(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current();
          const ideas=v.picks.querySelectorAll('details').find(n=>n.getAttribute('data-pack-group')==='idea');ideas.open=true;
          v.chooser.scrollTop=88;const old=control(v,'casual/a','choose');old.focus();old.checked=false;old.fire('change');
          const fresh=control(v,'casual/a','choose');assert(fresh!==old);assert(document.activeElement===fresh);assert(fresh.isConnected);
          assert.equal(v.chooser.scrollTop,88);assert(v.picks.querySelectorAll('details').find(n=>n.getAttribute('data-pack-group')==='idea').open);
          const preset=control(v,'','preset');preset.focus();preset.click();assert(document.activeElement===control(v,'','preset'));
        """)

    def test_late_normalization_uses_current_focus_and_does_not_reclaim_focus_from_outside(self):
        self.run_js("""
          drawAssembly(chooserData(),routeToken);await settle();const v=current();let resolve;
          mockApi((p,b)=>new Promise(r=>{resolve=()=>r({...chooserData(),selections:b.decks});}));
          const pending=packRun(v);await settle();const old=control(v,'casual/a','scope');old.focus();resolve();await pending;await settle();
          const fresh=control(v,'casual/a','scope');assert(fresh!==old);assert(document.activeElement===fresh);
          const next=packRun(v);await settle();const outside=el('button',{text:'Outside chooser'});v.root.append(outside);outside.focus();
          resolve();await next;await settle();assert(document.activeElement===outside);assert(outside.isConnected);
        """)

    def test_recipe_redraw_focus_and_validation_keep_exact_selected_object_guards(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);
          const scope=control(v,'casual/a','scope');scope.focus();scope.value='custom';scope.fire('change');
          assert(document.activeElement===control(v,'casual/a','scope'));same(v.selected[0].sideboard,{Beta:3});
          const qty=control(v,'casual/a','quantity:Beta');qty.focus();qty.value='1';qty.fire('change');
          const fresh=control(v,'casual/a','quantity:Beta');assert(fresh!==qty);assert(document.activeElement===fresh);same(v.selected[0].sideboard,{Beta:1});
          fresh.value='4';fresh.fire('change');assert.equal(fresh.value,'1');assert(v.chooser.textContent.includes('whole number from 0 to 3'));
          const play=control(v,'casual/a','version:owned');play.focus();play.click();assert.equal(v.selected[0].version,'owned');
          assert(!('sideboard'in v.selected[0]));assert(document.activeElement===control(v,'casual/a','version:owned'));
          qty.value='0';qty.fire('change');assert(!('sideboard'in v.selected[0]));
          assert.equal(control(v,'casual/a','scope').value,'all');
        """)

    def test_resize_rescues_original_tree_and_restores_only_visible_focus(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);
          const sheet=v.chooserState.sheet,tree=v.chooser,scope=control(v,'casual/a','scope');scope.focus();sheet.body.scrollTop=90;
          width(false);assert(!v.chooserState.sheet);assert(!sheet.dialog.isConnected);assert(v.chooser===tree);
          assert(v.chooserRail.contains(tree));assert(document.activeElement===scope);assert(!v.chooserRail.hidden);assert(v.chooserLaunch.hidden);
          assert.equal(v.chooser.scrollTop,90);width(true);assert(!tree.isConnected);assert(document.activeElement===v.chooserLaunch);
          assert(!v.chooserState.sheet);assert(!v.chooserLaunch.hidden);
          width(false);assert(document.activeElement===v.chooserHeading);assert(v.chooserLaunch.hidden);
          width(true);assert(document.activeElement===v.chooserLaunch);v.chooserLaunch.click();assert(v.chooserState.sheet.body.contains(tree));
          assert.equal(v.chooserState.sheet.body.scrollTop,90);assert.equal(document.body.querySelectorAll('.pack-choose').length,1);
          packChooserClose(v);const outside=el('button',{text:'Unrelated'});v.root.append(outside);outside.focus();width(false);width(true);
          assert(document.activeElement===outside);
        """)

    def test_deferred_old_native_close_cannot_detach_a_new_sheet_or_steal_focus(self):
        self.run_js("""
          width(true);const original=openSheet,pending=[];openSheet=(title,opts)=>original(title,{...opts,onClose:()=>pending.push(opts.onClose)});
          drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);const old=v.chooserState.sheet;
          control(v,'casual/a','scope').focus();width(false);assert(old.closed);assert.equal(pending.length,1);
          width(true);packRevealChooser(v);const fresh=v.chooserState.sheet,focused=control(v,'casual/a','scope');focused.focus();
          pending.shift()();assert(v.chooserState.sheet===fresh);assert(fresh.body.contains(v.chooser));assert(document.activeElement===focused);
          assert.equal(document.body.querySelectorAll('.pack-choose').length,1);
        """)

    def test_cleanup_before_profile_or_route_changes_removes_listener_and_never_refocuses_old_launcher(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);
          const outside=el('button',{text:'Navigation'});main.append(outside);outside.focus();const ctx=v.chooserState;
          closeAssemblySheets();assert(ctx.disposed);assert(!ctx.sheet);assert(!v.chooser.isConnected);assert(document.activeElement===outside);
          assert(!(media.events.get('change')||[]).includes(ctx.change));state.profile={id:'user1'};++routeToken;
          media.matches=false;media.fire('change');ctx.change();v.chooserLaunch.click();assert(!ctx.sheet);assert(!v.chooser.isConnected);
          assert(document.activeElement===outside);assert.equal(packingChoosers.size,0);
        """)

    def test_stale_closed_and_permission_busy_reviewing_controls_refuse_changes_and_restore_checkbox_state(self):
        self.run_js("""
          width(true);drawAssembly(chooserData(),routeToken);await settle();const v=current();packRevealChooser(v);
          let calls=0;mockApi(()=>{calls++;throw new Error('refused');});const box=control(v,'casual/d2','choose');
          const preset=control(v,'','preset'),clearControl=control(v,'','clear'),initial=JSON.stringify(v.selected),seq=v.seq;
          for(const mode of ['saving','reviewing','permission','profile','route','closed']){
            v.saving=false;v.reviewing=false;state.may=null;state.profile={id:'matt',role:'admin',space:'home'};v.token=routeToken;
            if(mode==='saving'||mode==='reviewing')v[mode]=true;
            if(mode==='permission')state.may={see_home_records:false};if(mode==='profile')state.profile={id:'other'};
            if(mode==='route')++routeToken;if(mode==='closed')packChooserClose(v,false);
            box.checked=true;box.fire('change');preset.fire('click');clearControl.fire('click');
            assert.equal(box.checked,false);assert.equal(JSON.stringify(v.selected),initial);assert.equal(v.seq,seq);assert.equal(calls,0);
          }
        """)

    def test_sheet_and_rail_freeze_restore_selects_numbers_and_limit_disabled_choices(self):
        self.run_js("""
          for(const narrow of [false,true]){
            width(narrow);clear(main);drawAssembly(chooserData(12),routeToken);await settle();const v=current();if(narrow)packRevealChooser(v);
            const scope=control(v,'casual/a','scope');scope.value='custom';scope.fire('change');
            const original=JSON.stringify(v.selected),select=control(v,'casual/a','scope'),number=control(v,'casual/a','quantity:Beta');
            const checked=control(v,'casual/a','choose'),capped=control(v,'casual/d12','choose');assert(capped.disabled);
            packSaving(v,true);for(const n of [select,number,checked,capped,control(v,'','clear')])assert(n.disabled);
            select.value='main';select.fire('change');number.value='0';number.fire('change');checked.checked=false;checked.fire('change');
            assert.equal(JSON.stringify(v.selected),original);assert.equal(checked.checked,true);
            packSaving(v,false);assert(!select.disabled);assert(!number.disabled);assert(!checked.disabled);assert(capped.disabled);
            if(narrow){assert(!v.chooserDismiss.disabled);packChooserClose(v);packRevealChooser(v);assert(!select.disabled);}
          }
        """)

    def test_actual_completion_while_sheet_open_keeps_request_and_recovers_fresh_choice_controls(self):
        self.run_js("""
          width(true);const data=chooserData();drawAssembly(data,routeToken);await settle();checkCards();await settle();const v=current();
          packRevealChooser(v);const old=control(v,'casual/a','choose'),scope=control(v,'casual/a','scope');scope.focus();
          let finish;const calls=[];mockApi((p,b)=>{calls.push([p,b]);return new Promise(r=>finish=r);});
          const saving=packMarkBuilt(v);assert(v.saving);assert(old.disabled);assert(scope.disabled);
          finish({built:data.completion.decks,plan:completed(data),warnings:[],tables:{}});await saving;await settle();
          assert(!v.saving);assert(v.chooserState.sheet);const fresh=control(v,'casual/a','choose');assert(fresh!==old);assert(!fresh.disabled);
          assert(document.activeElement===control(v,'casual/a','scope'));old.checked=false;old.fire('change');assert.equal(v.selected.length,1);
          same(calls,[['/api/assembly/built',{decks:[{id:'casual/a',version:'target'}],fingerprint:'first-plan',confirmed:true}]]);
        """)

    def test_empty_reveal_and_error_status_use_current_controller_without_duplicate_announcements(self):
        self.run_js("""
          width(true);const data=chooserData(0);data.decks=[];drawAssembly(data,routeToken);await settle();const v=current();
          v.results.querySelector('button').click();assert(v.chooserState.sheet);assert.equal(v.chooserDismiss.textContent,'Close');
          assert(!v.chooserState.sheet.foot.querySelector('.pack-show-plan'));assert.equal(v.chooser.querySelectorAll('[data-pack-control]').filter(n=>n.getAttribute('data-pack-control')==='choose').length,14);
          mockApi(()=>Promise.reject(new Error('Fixture preview unavailable')));await packRun(v);await settle();
          assert(v.chooserState.sheet.body.contains(v.message));assert(v.message.textContent.includes('Fixture preview unavailable'));
          assert.equal(document.body.querySelectorAll('.pack-message').filter(n=>n.isConnected).length,1);assert(!v.messageSlot.contains(v.message));
          v.chooserDismiss.click();assert(v.messageSlot.contains(v.message));assert(v.message.textContent.includes('Fixture preview unavailable'));
          closeAssemblySheets();clear(main);const none=chooserData(0);none.choices=[];none.decks=[];drawAssembly(none,routeToken);await settle();
          packRevealChooser(current());assert(!current().chooserEmpty.hidden);assert(current().chooser.textContent.includes('No decks to choose yet'));
        """)

    def test_finish_review_list_change_reveals_phone_chooser_after_review_flag_clears(self):
        self.run_js("""
          width(true);const data=chooserData();data.completion.review=true;
          data.completion.decks.forEach(d=>Object.assign(d,{versions:['target','owned'],kit:{editable:false}}));
          drawAssembly(data,routeToken);await settle();checkCards();await settle();const v=current();
          const calls=[];mockApi(async(p,b)=>{calls.push([p,b]);return {...data,selections:b.decks};});
          const pending=packMarkBuilt(v);await settle();assert(v.reviewing);assert.equal(assemblySheets.size,1);
          const review=[...assemblySheets][0];const list=review.body.querySelectorAll('select').find(n=>n.getAttribute('aria-label')==='Elves: built list');
          assert(list);list.value='owned';list.fire('change');await pending;await settle();
          assert(!v.reviewing);assert.equal(assemblySheets.size,0);assert(v.chooserState.sheet);assert(!review.dialog.isConnected);
          assert.equal(v.selected[0].version,'owned');assert(!control(v,'casual/a','scope').disabled);
          flushTimers();await settle();same(calls,[['/api/assembly/preview',{decks:[{id:'casual/a',version:'owned'}]}]]);
        """)


class AssemblyChooserSourceTests(unittest.TestCase):
    def test_helper_registration_and_short_sheet_geometry_keep_shared_modal_and_touch_floor(self):
        index=(WEB/'index.html').read_text(encoding='utf-8');css=(WEB/'assembly.css').read_text(encoding='utf-8')
        self.assertLess(index.index('/assembly.js'),index.index('/assembly-chooser.js'))
        self.assertLess(index.index('/assembly-chooser.js'),index.index('/assembly-sheets.js'))
        self.assertRegex(css,r'\.pack-decks-sheet \.sheet-head, \.pack-decks-sheet \.sheet-foot\s*\{\s*flex:\s*none')
        self.assertRegex(css,r'\.pack-decks-sheet \.sheet-body\s*\{\s*min-height:\s*0')
        self.assertRegex(css,r'\.pack-decks-sheet \.choice\s*\{\s*min-height:\s*52px')
        self.assertIn('grid-template-columns: 300px minmax(0, 1fr)',css)
        helper=(WEB/'assembly-chooser.js').read_text(encoding='utf-8')
        self.assertIn('window.matchMedia("(min-width: 1000px)")',helper)
        self.assertNotIn('max-width: 999px',helper)
