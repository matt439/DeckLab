"""Verified intact-product review preserves only one selected packing recipe, never allocations."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, 'Node.js is not installed')
class AssemblyProductReviewUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, r'''
          const product={id:'opaque-product-stem',title:'Verified intact product',deck_id:'product/opaque-product-stem/actual-deck'};
          const holder=(extra={})=>({id:'holder-id-is-not-a-deck-route',title:'Holding record',quantity:2,intact_product:{...product},...extra});
          const row=(extra={})=>({name:'Alpha',missing:2,waiting:0,held_elsewhere:[holder()],...extra});
          const productPlan=(extra={})=>({...plan(),rows:[row()],ready:false,totals:{missing:2,waiting:0},...extra});
          const openProductPlan=async data=>{const view=drawAssembly(data||productPlan(),routeToken);await settle();return view;};
          const reviewLink=view=>view.results.querySelector('.pack-intact-products').querySelector('a');
          const recipe=()=>[{id:'casual/a',version:'owned',sideboard:{Beta:1}},{id:'casual/b',version:'target',sideboard:{}}];
          const chosenPlan=()=>productPlan({decks:[item('casual/a','owned'),item('casual/b','target')],selections:recipe(),
            choices:[{id:'casual/a',title:'Elves',status:'building',versions:['target','owned'],sideboards:{owned:[{name:'Beta',quantity:3}]}},
              {id:'casual/b',title:'Burn',status:'building',versions:['target','owned']}]});
          const primary=(link,extra={})=>link.fire('click',{button:0,detail:1,...extra});
        ''' + scenario)

    def test_only_explicit_valid_product_payloads_supply_grouped_short_or_waiting_review_links(self):
        self.run_js(r'''
          const view=await openProductPlan(productPlan({rows:[
            row(),row({name:'Beta',missing:0,waiting:3,held_elsewhere:[holder({quantity:4})]}),
            row({name:'Ready',missing:0,waiting:0}),
            row({name:'Unverified',held_elsewhere:[holder({id:'product/guessable',intact_product:undefined})]})]}));
          const part=view.results.querySelector('.pack-intact-products');assert(part);
          assert.equal(part.querySelectorAll('a').length,1);assert(part.textContent.includes('2 x Alpha held in this product'));
          assert(part.textContent.includes('4 x Beta held in this product'));assert(!part.textContent.includes('Ready'));
          assert(!part.textContent.includes('Unverified'));assert(part.textContent.includes("browser's Back"));
          assert.equal(reviewLink(view).getAttribute('href'),deckHref(product.deck_id)+'&tab=overview');
          for(const intact_product of [null,[],{}, {...product,title:''},{...product,deck_id:'casual/guess'},
            {...product,deck_id:'product/a?extra=1'},{...product,id:12},{...product,title:'Bad\nname'}]) {
            assert.equal(packIntactProduct(holder({intact_product})),null);
          }
          assert.equal(packIntactProduct(holder({intact_product:undefined,id:'product/looks-like-one'})),null);
          assert.equal(view.results.querySelectorAll('.pack-intact-products').length,1);
        ''')

    def test_primary_review_arms_only_a_deep_copied_recipe_and_navigates_to_supplied_overview(self):
        self.run_js(r'''
          location.hash='#/assembly?deck=casual%2Fa&version=owned';const origin=location.hash;
          const data=chosenPlan(),view=await openProductPlan(data),expected=recipe(),before=JSON.stringify(data);
          const event=primary(reviewLink(view));assert(event.defaultPrevented);
          assert.equal(location.hash,deckHref(product.deck_id)+'&tab=overview');
          same(packProductReviewReturn,{profile:'matt',hash:origin,recipe:expected});
          assert.notEqual(packProductReviewReturn.recipe,view.selected);assert.notEqual(packProductReviewReturn.recipe[0].sideboard,view.selected[0].sideboard);
          view.selected[0].sideboard.Beta=3;assert.equal(packProductReviewReturn.recipe[0].sideboard.Beta,1);
          assert.equal(JSON.stringify(data),before);
        ''')

    def test_one_physical_product_groups_its_multiple_generated_deck_routes(self):
        self.run_js(r'''
          const other={...product,deck_id:'product/opaque-product-stem/second-actual-deck'};
          const view=await openProductPlan(productPlan({rows:[row({held_elsewhere:[holder(),holder({intact_product:other})]})]}));
          const part=view.results.querySelector('.pack-intact-products');assert.equal(part.querySelectorAll('a').length,1);
          assert(part.textContent.includes('4 x Alpha held in this product'));
          assert.equal(reviewLink(view).getAttribute('href'),deckHref(product.deck_id)+'&tab=overview');
        ''')

    def test_back_fetches_fresh_choices_then_preview_once_without_showing_get_default_allocations(self):
        self.run_js(r'''
          location.hash='#/assembly?deck=casual%2Fa&version=owned';const origin=location.hash;
          const view=await openProductPlan(chosenPlan());primary(reviewLink(view));routeToken++;clear(main);
          location.hash=origin;const gets=[],previews=[];let ready,resolve;
          load=(path,token,callback)=>{gets.push({path,token});ready=callback;};
          mockApi((path,body)=>{assert.equal(path,'/api/assembly/preview');previews.push(body);return new Promise(done=>resolve=done);});
          showAssembly(parseHash().params,routeToken);assert.equal(gets.length,1);assert.equal(previews.length,0);
          const initial=plan([item('casual/default')]);initial.choices=chosenPlan().choices;
          const restored=ready(initial);assert(packProductReviewReturn===null);same(restored.selected,recipe());
          assert(restored.previewing);assert.equal(restored.results.querySelector('.pack-deck'),null);assert.equal(restored.bar,undefined);
          assert(restored.message.textContent.includes('Working out'));same(previews,[{decks:recipe()}]);
          resolve({...chosenPlan(),rows:[],ready:true,totals:{waiting:0,missing:0}});await settle();
          assert(!restored.previewing);assert.equal(restored.data.rows.length,0);
          same(restored.results.querySelectorAll('.pack-deck').map(node=>node.getAttribute('data-pack-deck')),['casual/a:owned','casual/b:target']);
          clear(main);routeToken++;showAssembly(parseHash().params,routeToken);const ordinary=ready(initial);
          same(ordinary.selected,[{id:'casual/default',version:'target'}]);assert.equal(previews.length,1);
        ''')

    def test_return_recipe_invalidates_on_wrong_profile_hash_or_ordinary_chooser_change(self):
        self.run_js(r'''
          for(const alter of [()=>{state.profile={...state.profile,id:'user1'};},()=>{location.hash='#/assembly?deck=casual/elsewhere';}]) {
            state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};location.hash='#/assembly';clear(main);
            const view=await openProductPlan();primary(reviewLink(view));location.hash='#/assembly';alter();
            load=()=>{};showAssembly(parseHash().params,routeToken);assert.equal(packProductReviewReturn,null);
          }
          state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};location.hash='#/assembly';clear(main);
          const view=await openProductPlan();primary(reviewLink(view));assert(packProductReviewReturn);
          packChanged(view);assert.equal(packProductReviewReturn,null);
        ''')

    def test_modified_clicks_do_not_arm_or_take_over_native_navigation(self):
        self.run_js(r'''
          const view=await openProductPlan(),hash=location.hash;
          for(const event of [{ctrlKey:true},{metaKey:true},{shiftKey:true},{altKey:true},{button:1}]) {
            assert(!primary(reviewLink(view),event).defaultPrevented);assert.equal(packProductReviewReturn,null);assert.equal(location.hash,hash);
          }
          const keyboard=reviewLink(view).fire('click',{button:0,detail:0});assert(keyboard.defaultPrevented);assert(packProductReviewReturn);
        ''')

    def test_unsettled_progress_and_plan_work_keep_selection_in_place_with_visible_guidance(self):
        self.run_js(r'''
          const view=await openProductPlan(chosenPlan()),hash=location.hash,selected=JSON.stringify(view.selected),p=view.progress;
          for(const field of ['previewing','reviewing','saving']) {
            view[field]=true;primary(reviewLink(view));assert.equal(location.hash,hash);assert.equal(packProductReviewReturn,null);
            assert(view.message.textContent.includes('Finish the current plan change'));view[field]=false;
          }
          for(const change of [()=>{p.loaded=false;},()=>{p.busy=true;},()=>{p.pending.set('uncertain',{done:true,serial:1});},()=>{p.error='Fixture outage';}]) {
            change();primary(reviewLink(view));assert.equal(location.hash,hash);assert.equal(packProductReviewReturn,null);
            assert(view.message.textContent.includes('shared packing checks'));p.loaded=true;p.busy=false;p.pending.clear();p.error=null;
          }
          assert.equal(JSON.stringify(view.selected),selected);
        ''')

    def test_stale_node_data_recipe_profile_route_and_hash_cannot_arm_return_intent(self):
        self.run_js(r'''
          for(const alter of [view=>{view.data={...view.data};},view=>{view.selected[0].version='owned';},
            view=>{state.profile={...state.profile,id:'other'};},view=>{routeToken++;},view=>{location.hash='#/library';},view=>{view.root.remove();}]) {
            clear(main);location.hash='#/assembly';state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
            const view=await openProductPlan(),link=reviewLink(view);alter(view);const hash=location.hash;primary(link);
            assert.equal(packProductReviewReturn,null);assert.equal(location.hash,hash);
          }
        ''')

    def test_late_get_or_preview_cannot_restore_after_profile_route_or_hash_changed(self):
        self.run_js(r'''
          const view=await openProductPlan();primary(reviewLink(view));location.hash='#/assembly';routeToken++;clear(main);
          let ready;load=(path,token,callback)=>{ready=callback;};showAssembly(parseHash().params,routeToken);
          state.profile={...state.profile,id:'other'};ready(chosenPlan());assert.equal(main.children.length,0);
          state.profile={id:'matt',name:'Matt',space:'home',role:'admin',plays_as:'user'};
          location.hash='#/assembly';routeToken++;showAssembly(parseHash().params,routeToken);
          let resolve;mockApi((path,body)=>new Promise(done=>resolve=done));const restored=ready(chosenPlan());
          assert(restored.previewing);routeToken++;clear(main);main.append(el('p',{text:'New page'}));resolve(chosenPlan());await settle();
          assert.equal(main.textContent,'New page');assert.equal(restored.results.querySelector('.pack-deck'),null);
        ''')

    def test_failed_refresh_keeps_recipe_for_explicit_retry_without_replaying_old_plan(self):
        self.run_js(r'''
          const expected=recipe(),gets=[];let fail=true;const previews=[];
          mockApi((path,body)=>{assert.equal(path,'/api/assembly/preview');previews.push(body);
            if(fail)throw Error('Fixture preview unavailable');return chosenPlan();});
          const initial=chosenPlan(),view=drawAssembly(initial,routeToken,expected);await settle();
          same(view.selected,expected);assert.equal(view.data,null);assert.equal(view.results.querySelector('.pack-deck'),null);
          assert(view.results.textContent.includes('selected decks and sideboard choices are kept'));
          const retry=view.results.querySelector('button');assert.equal(retry.textContent,'Refresh plan');fail=false;retry.click();await settle();
          assert.equal(previews.length,2);same(previews[1],{decks:expected});assert(view.results.querySelector('.pack-deck'));
          assert(!view.productReturnRefresh);assert(view.progress.loaded);
          retry.disabled=false;retry.click();await settle();assert.equal(previews.length,2);
        ''')
