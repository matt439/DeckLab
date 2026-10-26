"""Mixed whole-product/deck token plans over fixture APIs, with no real inventory writes."""
import unittest

from decklab.tests import test_feature_ui_tokens as tokens_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ProductTokenPlanUiTests(unittest.TestCase):
    def run_js(self, scenario):
        tokens_ui.TokensUiTests.run_js(self, tokens_ui.TokensUiTests.TOKENS + r'''
          local.get=()=>null;local.set=()=>true;
          const demand=(id,title,extra={})=>({id,title,spares:0,short:[],
            packs:[{token:'Zombie',card:'Zombie / Zombie Knight',side:'front',verdict:'check'}],...extra});
          const ordinary=extra=>({...demand('casual/ordinary','Ordinary Deck'),before:null,after:'1 Zombie // Zombie Knight',
            changed:true,editable:true,lines:[{text:'1 Zombie // Zombie Knight',sides:['Zombie side only, can be sleeved']}],...extra});
          const product=extra=>({stem:'verified-starter',holder:'product:verified-starter',title:'Verified Starter',
            link:'product/actual-source/blue',before:'',after:'2 Zombie // Zombie Knight',changed:true,editable:true,
            lines:[{text:'2 Zombie // Zombie Knight',sides:[]}],decks:[demand('product/actual-source/blue','Blue Deck'),
              demand('product/actual-source/green','Green Deck',{spares:1,short:['Spirit']})],...extra});
          const preview=extra=>({space:'home',sha256:'c'.repeat(64),tokens_sha256:'a'.repeat(64),changes:1,
            decks:[ordinary()],products:[product()],product_changes:1,warnings:[],...extra});
          const receipt=extra=>({saved:1,decks:['casual/ordinary'],saved_products:1,products:['verified-starter'],...extra});
          let refreshed=0;refreshTokens=()=>{refreshed++;};
          const mount=(space='home')=>{
            closeTokenPlanSheets();clear(main);state.may=null;state.profile={id:'matt',name:'Matt',space:'home'};
            location.hash='#/tokens'+(space==='home'?'':'?space='+space);
            if(space!=='home')state.profile={id:space,name:'Member',space};
            return drawTokens({...tokensData,space},routeToken,space);
          };
          const review=async(plan=preview())=>{const view=mount();api=async()=>plan;const sheet=openTokenPlan(view);await settle();return{view,sheet,plan};};
          const act=(sheet,text)=>button(sheet.dialog,text);
          const applyButton=sheet=>sheet.foot.querySelector('[data-action="apply"]');
        ''' + scenario)

    def test_product_counts_physical_record_once_and_shows_actual_subdeck_demands(self):
        self.run_js(r'''
          const {sheet}=await review();const text=sheet.body.textContent;
          for(const words of ['Whole product packs: 2 Zombie // Zombie Knight','Blue Deck','Green Deck',
            'One physical record covers the whole box','a paired card counts once','No card left for Spirit',
            'Now: quantities not recorded (unknown)','1 spare card allocated within the whole product'])assert(text.includes(words),words);
          const group=sheet.body.querySelector('.tok-plan-product');assert(group);
          assert(!group.textContent.includes('can be sleeved'));assert(!group.textContent.includes('side only'));
          assert.equal(sheet.body.querySelectorAll('.tok-plan-product').length,1);
          assert.equal(group.querySelector('a').getAttribute('href'),deckHref('product/actual-source/blue'));
          assert(act(sheet,'Apply to 1 deck and 1 product'));
        ''')

    def test_null_product_link_uses_library_and_blank_remains_unknown(self):
        self.run_js(r'''
          const {sheet}=await review(preview({changes:0,decks:[],products:[product({link:null,after:'',lines:[],changed:false})],product_changes:0}));
          const group=sheet.body.querySelector('.tok-plan-product');
          assert.equal(group.querySelector('a').getAttribute('href'),'#/library?format=product');
          assert(group.textContent.includes('quantities not recorded (unknown)'));assert(!group.textContent.includes('no token cards'));
          assert(applyButton(sheet).disabled);assert.equal(applyButton(sheet).textContent,'Nothing to change');
        ''')

    def test_older_ordinary_only_preview_and_receipt_preserve_payload_and_words(self):
        self.run_js(r'''
          const plan=preview();delete plan.products;delete plan.product_changes;const {sheet}=await review(plan);const calls=[];
          assert(sheet.body.textContent.includes('Zombie side only, can be sleeved'));assert(sheet.body.textContent.includes('Now: not recorded'));
          apiWrite=async(path,body)=>{calls.push([path,body]);return{saved:1,decks:['casual/ordinary']};};
          act(sheet,'Apply to 1 deck').click();await settle();assert(sheet.closed);assert.equal(refreshed,1);
          same(calls,[['/api/tokens/plan',{sha256:'c'.repeat(64)}]]);
        ''')

    def test_product_only_plan_applies_one_whole_holder_with_exact_receipt(self):
        self.run_js(r'''
          const {sheet}=await review(preview({decks:[],changes:0}));const calls=[];
          apiWrite=async(path,body)=>{calls.push([path,body]);return receipt({saved:0,decks:[]});};
          act(sheet,'Apply to 1 product').click();await settle();assert(sheet.closed);assert.equal(refreshed,1);
          same(calls,[['/api/tokens/plan',{sha256:'c'.repeat(64)}]]);
          assert(document.querySelector('#toast').textContent.includes('saved for 1 product'));
        ''')

    def test_mixed_receipt_counts_changed_participants_only_and_accepts_id_order(self):
        self.run_js(r'''
          const plan=preview({changes:2,decks:[ordinary(),ordinary({id:'commander/other',title:'Other',changed:true}),
            ordinary({id:'casual/same',title:'Unchanged',changed:false})],products:[product(),product({stem:'same-box',
              holder:'product:same-box',title:'Same Box',changed:false,decks:[demand('product/same','Same Deck')]})]});
          const {sheet}=await review(plan);apiWrite=async()=>receipt({saved:2,decks:['commander/other','casual/ordinary']});
          act(sheet,'Apply to 2 decks and 1 product').click();await settle();assert(sheet.closed);assert.equal(refreshed,1);
          assert(document.querySelector('#toast').textContent.includes('2 decks and 1 product'));
        ''')

    def test_permissions_include_every_changed_product_and_deck_and_current_product_permission(self):
        self.run_js(r'''
          for(const kind of ['deck','product']){
            const plan=preview();(kind==='deck'?plan.decks[0]:plan.products[0]).editable=false;
            const {sheet}=await review(plan);assert(applyButton(sheet).disabled);assert(sheet.body.textContent.includes("You can't change"));
            let writes=0;apiWrite=async()=>{writes++;};applyButton(sheet).fire('click');assert.equal(writes,0);
          }
          const {sheet}=await review();let writes=0;apiWrite=async()=>{writes++;};
          state.may={spaces:['home'],products:false};applyButton(sheet).fire('click');assert.equal(writes,0);
        ''')

    def test_unchanged_uneditable_product_does_not_block_ordinary_change(self):
        self.run_js(r'''
          const {sheet}=await review(preview({products:[product({changed:false,editable:false})],product_changes:0}));
          state.may={spaces:['home'],products:false};let writes=0;apiWrite=async()=>{writes++;return{saved:1,decks:['casual/ordinary']};};
          act(sheet,'Apply to 1 deck').click();await settle();assert.equal(writes,1);assert(sheet.closed);
        ''')

    def test_malformed_or_ambiguous_preview_never_offers_apply_or_claims_empty(self):
        self.run_js(r'''
          const cases=[p=>p.changes=0,p=>p.product_changes=0,p=>p.sha256='short',p=>p.products=null,
            p=>p.products[0].before=null,p=>p.products[0].decks=[],p=>p.products[0].link=undefined,
            p=>p.products[0].lines=[{text:'',sides:[]}],p=>p.products[0].decks[1].id=p.products[0].decks[0].id,
            p=>p.products.push({...p.products[0]}),p=>p.products[0].decks[0].id=p.decks[0].id,p=>p.decks[0].short=null,
            p=>p.products[0].editable='yes',p=>p.products[0].decks[0].spares=-1];
          for(const mutate of cases){const plan=preview();mutate(plan);const {sheet}=await review(plan);
            assert(!applyButton(sheet));assert(act(sheet,'Reload plan'));assert(sheet.body.textContent.includes("couldn't be worked out"));
            assert(!sheet.body.textContent.includes('There are no built decks'));}
        ''')

    def test_member_plan_keeps_own_space_in_read_and_write_and_refuses_product_projection(self):
        self.run_js(r'''
          const view=mount('user2'),asked=[],sent=[];const plan=preview({space:'user2',products:[],product_changes:0});
          api=async path=>{asked.push(path);return plan;};apiWrite=async(path,body)=>{sent.push([path,body]);return{saved:1,decks:['casual/ordinary']};};
          const sheet=openTokenPlan(view);await settle();act(sheet,'Apply to 1 deck').click();await settle();
          same(asked,['/api/tokens/plan?space=user2']);same(sent,[['/api/tokens/plan',{sha256:'c'.repeat(64),space:'user2'}]]);
          assert.equal(tokPlanEvidence(preview({space:'user2'}),'user2'),null);
        ''')

    def test_duplicate_clicks_and_detached_old_apply_never_repeat_a_pending_write(self):
        self.run_js(r'''
          const {sheet,view}=await review();let calls=0,resolve;apiWrite=()=>{calls++;return new Promise(r=>resolve=r);};
          const old=applyButton(sheet);old.click();assert(view.busy);old.fire('click');assert.equal(calls,1);assert(!openTokenPlan(view));
          assert(applyButton(sheet).disabled);resolve(receipt());await settle();old.fire('click');assert.equal(calls,1);assert(!view.busy);
        ''')

    def test_stale_activation_checks_profile_route_root_data_revision_scope_plan_and_top_modal(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','data','dataSha','seq','space','plan','permission','top']){
            const {view,sheet,plan}=await review();let calls=0;apiWrite=async()=>{calls++;return receipt();};let other;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.root.remove();if(mode==='data')view.data={...view.data};if(mode==='dataSha')view.data.sha256='f'.repeat(64);
            if(mode==='seq')view.seq++;if(mode==='space')view.space='user2';if(mode==='plan')plan.products[0].after='99 Dog';
            if(mode==='permission')state.may={spaces:[]};if(mode==='top')other=openSheet('Other review');
            applyButton(sheet).fire('click');await settle();assert.equal(calls,0,mode);if(other)other.close();
          }
        ''')

    def test_late_preview_cannot_reveal_private_plan_after_profile_page_or_controller_change(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','data','cleanup']){
            const view=mount();let resolve;api=()=>new Promise(r=>resolve=r);const sheet=openTokenPlan(view);
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.root.remove();if(mode==='data')view.data={...view.data};if(mode==='cleanup')closeTokenPlanSheets();
            resolve(preview());await settle();assert(!sheet.body.textContent.includes('Verified Starter'),mode);assert(!applyButton(sheet));
          }
        ''')

    def test_conflict_and_network_failure_require_explicit_reload_and_fresh_review(self):
        self.run_js(r'''
          for(const failure of [new ApiError(409,'The saved packing changed',{}),Error('Response lost')]){
            const {sheet}=await review();let writes=0,reads=0;const old=applyButton(sheet);apiWrite=async()=>{writes++;throw failure;};
            api=async()=>{reads++;return preview({sha256:'d'.repeat(64)});};old.focus();old.click();await settle();
            assert.equal(writes,1);assert.equal(reads,0);assert(!applyButton(sheet));assert(act(sheet,'Reload plan'));
            assert(sheet.body.textContent.includes('review it before applying again'));assert.equal(document.activeElement.getAttribute('role'),'alert');
            old.fire('click');assert.equal(writes,1);act(sheet,'Reload plan').click();await settle();assert.equal(reads,1);
            old.fire('click');assert.equal(writes,1);const sent=[];apiWrite=async(path,body)=>{sent.push(body);return receipt();};
            applyButton(sheet).click();await settle();same(sent,[{sha256:'d'.repeat(64)}]);
          }
        ''')

    def test_invalid_receipt_never_confirms_or_retries_a_potentially_committed_write(self):
        self.run_js(r'''
          const bad=[{saved:2},{decks:['casual/wrong']},{saved:true},{saved_products:0},{products:['different-box']},
            {products:['verified-starter','verified-starter']},{saved_products:undefined,products:undefined},{decks:[]}];
          for(const extra of bad){const {sheet}=await review();let writes=0;apiWrite=async()=>{writes++;return receipt(extra);};
            const old=applyButton(sheet);old.click();await settle();assert(!sheet.closed);assert(!applyButton(sheet));
            assert(act(sheet,'Reload plan'));assert(sheet.body.textContent.includes('could not be confirmed'));
            old.fire('click');assert.equal(writes,1);}
        ''')

    def test_late_apply_results_do_not_confirm_refresh_or_steal_focus_on_another_page_or_profile(self):
        self.run_js(r'''
          for(const mode of ['profile','route','hash','root','data','cleanup']){
            const {view,sheet}=await review();let resolve;apiWrite=()=>new Promise(r=>resolve=r);applyButton(sheet).click();
            if(mode==='profile')state.profile={id:'user1'};if(mode==='route')routeToken++;if(mode==='hash')location.hash='#/library';
            if(mode==='root')view.root.remove();if(mode==='data')view.data={...view.data};if(mode==='cleanup')closeTokenPlanSheets();
            const next=el('button',{text:'New page'});document.body.append(next);next.focus();const before=refreshed;
            resolve(receipt());await settle();assert.equal(refreshed,before,mode);assert.equal(document.activeElement,next);
            assert(!sheet.body.textContent.includes('saved for'),mode);
          }
        ''')

    def test_closed_pending_success_refreshes_only_after_original_history_entry_lands_once(self):
        self.run_js(r'''
          const {sheet}=await review();sheet.entry={token:800,pos:3,done:false,fromHistory:false};history.state={sheet:800,pos:3};
          let resolve;apiWrite=()=>new Promise(r=>resolve=r);applyButton(sheet).click();sheet.close();resolve(receipt());await settle();
          assert.equal(refreshed,0);history.state={pos:2};window.fire('popstate');await settle();assert.equal(refreshed,1);
          window.fire('popstate');assert.equal(refreshed,1);
        ''')

    def test_pending_unknown_closed_review_refreshes_original_view_without_any_retry(self):
        self.run_js(r'''
          const {sheet}=await review();let reject,calls=0;apiWrite=()=>{calls++;return new Promise((_,r)=>reject=r);};
          applyButton(sheet).click();sheet.close();reject(Error('Lost response'));await settle();assert.equal(calls,1);assert.equal(refreshed,1);
          assert.equal(tokenPlanSheets.size,0);
        ''')

    def test_navigation_cleanup_closes_only_plan_sheets_and_never_refreshes_old_owner(self):
        self.run_js(r'''
          const {sheet}=await review();const unrelated=openSheet('Unrelated');closeTokenPlanSheets();
          assert(sheet.closed);assert(!unrelated.closed);assert.equal(tokenPlanSheets.size,0);assert.equal(refreshed,0);
        ''')

    def test_error_preserves_user_moved_focus_and_retains_review_details(self):
        self.run_js(r'''
          const {sheet}=await review();let reject;apiWrite=()=>new Promise((_,r)=>reject=r);applyButton(sheet).focus();applyButton(sheet).click();
          const close=sheet.dialog.querySelector('.sheet-close');close.focus();reject(new ApiError(403,'Products are read only',{}));await settle();
          assert.equal(document.activeElement,close);assert(sheet.body.textContent.includes('Blue Deck'));
          assert(sheet.body.textContent.includes('Products are read only'));assert(!applyButton(sheet));
        ''')

    def test_closed_review_never_refreshes_after_wrong_history_position_or_changed_profile(self):
        self.run_js(r'''
          for(const mode of ['position','profile','hash']){
            const {sheet}=await review();sheet.entry={token:900,pos:4,done:false,fromHistory:false};history.state={sheet:900,pos:4};
            apiWrite=async()=>receipt();applyButton(sheet).click();await settle();assert(sheet.closed);const before=refreshed;
            if(mode==='profile')state.profile={id:'user1'};if(mode==='hash')location.hash='#/library';
            history.state={pos:mode==='position'?1:3};window.fire('popstate');await settle();assert.equal(refreshed,before,mode);
          }
        ''')

    def test_read_failure_is_caught_and_reloading_is_an_explicit_read_only_action(self):
        self.run_js(r'''
          const view=mount();let reads=0,writes=0;api=async()=>{reads++;throw Error('Unavailable');};apiWrite=async()=>{writes++;};
          const sheet=openTokenPlan(view);await settle();assert.equal(reads,1);assert.equal(writes,0);assert(act(sheet,'Reload plan'));
          api=async()=>{reads++;return preview();};act(sheet,'Reload plan').click();await settle();assert.equal(reads,2);assert(applyButton(sheet));
          assert.equal(writes,0);
        ''')


if __name__ == "__main__":
    unittest.main()
