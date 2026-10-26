"""Casual grouping reparents the same guarded purchase intent and single Add control."""
import unittest

from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingCasualControlsInteractionTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js

    def run_queue_js(self, scenario):
        self.run_js("""
          state.may={admin:true,orders:true,see_inventory:['home']};
          api=()=>{throw new Error('Grouping must not read')};
          apiWrite=()=>{throw new Error('Grouping must not write')}; toast=()=>{};
          const cardData=name=>({name,type_line:'Creature',mana_cost:'',img:'/img/test/1/normal',img_small:'/img/test/1/small'});
          const qrow=(name,n,extra={})=>row(name,{queue_row:n,source:'',card:cardData(name),...extra});
          const queueData=queue=>({...empty,queue_revision:'q1',to_buy:queue,queue_decks:[]});
          const density=lab=>{const query=window.matchMedia(SHOP_QUEUE_LAB);query.matches=lab;query.fire('change')};
          const immediate=()=>main.querySelector('#shop-to-buy')?.closest('section');
          const entries=()=>main.querySelectorAll('[data-shop-queue]');
          const entry=n=>entries().find(node=>Number(node.getAttribute('data-shop-queue'))===n);
          const immediateIds=()=>immediate().querySelectorAll('[data-shop-queue]').map(node=>Number(node.getAttribute('data-shop-queue')));
          const trigger=n=>entry(n).querySelector('.card-row');
          const edit=n=>entry(n).querySelector('.shop-queue-edit');
          const move=n=>entry(n).querySelector('.shop-category-move');
          const control=value=>main.querySelectorAll('[data-queue-order]').find(node=>node.getAttribute('data-queue-order')===value);
          const group=(value,focus=true)=>{const button=control(value);assert(button);if(focus)button.focus();button.click();return button};
          const choose=value=>{const radios=main.querySelectorAll('.shop-store-radio'),radio=radios.find(node=>node.value===value);assert(radio);
            radios.forEach(node=>{node.checked=node===radio});radio.focus();radio.fire('change');return radio};
          const sameNodes=(actual,expected)=>{assert.equal(actual.length,expected.length);actual.forEach((node,index)=>assert(node===expected[index]))};
          const action=(sheet,text)=>{const button=sheet.foot.querySelectorAll('button').find(node=>node.textContent===text);assert(button);return button};
          const field=(sheet,key)=>{const input=sheet.body.querySelector('[data-queue-field='+key+']');assert(input);return input};
          const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve()};
          const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
          const goMove=(n,label)=>{move(n).click();entry(n).querySelectorAll('[role=menuitem]').find(node=>node.textContent===label).click()};
          const dueInfo=()=>({ready:true,upcoming:[],data_date:'2026-10-24',as_of:'2026-10-25',
            price_check:{offered:true,reason:'unknown'},notes:['Saved source coverage']});
        """ + scenario)

    def test_grouping_reorders_existing_rows_and_viewer_order_without_changing_exact_intent(self):
        self.run_queue_js("""
          const queue=[qrow('Repeated',1,{state:'deferred',listed_at:' B ',printing:'exact',set:'fdn',collector_number:'2'}),
            qrow('Repeated',2,{listed_at:'A',quantity:3}),qrow('Third',3,{state:'waiting_for_stock',listed_at:'B'}),qrow('Fourth',4)];
          const before=JSON.stringify(queue),view=drawShopping(queueData(queue));
          const rows=new Map(entries().map(node=>[Number(node.getAttribute('data-shop-queue')),node])),
            viewers=new Map(queue.map(item=>[item.queue_row,trigger(item.queue_row)])),
            writers=new Map(queue.map(item=>[item.queue_row,entry(item.queue_row).querySelector('.shop-queue-actions')]));
          same(immediateIds(),[2,4,3,1]);const selected=group('shop');
          same(immediateIds(),[2,1,3,4]);assert(document.activeElement===selected);
          assert.equal(selected.getAttribute('aria-pressed'),'true');assert.equal(control('state').getAttribute('aria-pressed'),'false');
          for(const item of queue){assert(entry(item.queue_row)===rows.get(item.queue_row));assert(trigger(item.queue_row)===viewers.get(item.queue_row));
            assert(entry(item.queue_row).querySelector('.shop-queue-actions')===writers.get(item.queue_row))}
          sameNodes(viewerGroup(trigger(2)).items.map(item=>item.card),[queue[1].card,queue[0].card,queue[2].card,queue[3].card]);
          assert.equal(main.querySelectorAll('[data-viewer]').length,4);assert.equal(main.querySelectorAll('.shop-queue-edit').length,4);
          group('state');same(immediateIds(),[2,4,3,1]);assert.equal(JSON.stringify(queue),before);assert.equal(view.data.queue_revision,'q1');
        """)

    def test_by_shop_keeps_every_state_meaning_and_explicit_unchecked_group_visible(self):
        self.run_queue_js("""
          const queue=[qrow('Ready',1,{listed_at:'Store'}),qrow('Stock',2,{state:'waiting_for_stock',listed_at:'Store'}),
            qrow('Reprint',3,{state:'waiting_for_reprint',listed_at:'Store'}),qrow('Deferred',4,{state:'deferred',listed_at:'Store'}),
            qrow('Older',5,{state:'older_state',listed_at:'   ',card:null})];
          drawShopping(queueData(queue));group('shop');
          same(immediate().querySelectorAll('[data-queue-shop]').map(node=>node.getAttribute('data-queue-shop')),['Store','']);
          const expected=['Ready to buy','Waiting for stock','Waiting for reprint','Deferred','State: older_state'];
          for(let i=1;i<=5;i++){const words=entry(i).querySelector('.shop-queue-category');assert(!words.hidden);assert.equal(words.textContent,expected[i-1])}
          const unchecked=immediate().querySelectorAll('[data-queue-shop]').find(node=>node.getAttribute('data-queue-shop')==='');
          assert(unchecked.querySelector('h3').textContent.includes('Not checked at any shop'));assert(unchecked.contains(entry(5)));
          assert.equal(entry(5).querySelector('.card-row').getAttribute('tabindex'),'-1');
          group('state');assert(immediate().querySelectorAll('.shop-queue-category').every(node=>node.hidden));
          assert.equal(immediate().querySelectorAll('.shop-queue-row').length,5);
        """)

    def test_grouping_and_shop_marks_are_independent_and_leave_longterm_nodes_and_expansion_alone(self):
        self.run_queue_js("""
          const later=Array.from({length:14},(_,i)=>qrow('Later '+i,i+3,{state:'long_term',for:'Later deck',listed_at:i===13?'Match':'Other'}));
          const view=drawShopping(queueData([qrow('Now',1,{listed_at:'Match'}),qrow('Other',2,{listed_at:'Other'}),...later]));
          const long=main.querySelector('#shop-long-term').closest('section'),first=entry(3),firstViewer=trigger(3),firstMove=move(3);
          group('shop');assert(main.querySelector('#shop-long-term').closest('section')===long);
          assert.equal(long.querySelectorAll('[data-shop-queue]').length,12);assert.equal(long.querySelector('.shop-queue-by-shop'),null);
          choose('shop:Match');assert.equal(long.querySelectorAll('[data-shop-queue]').length,14);assert(view.expanded.has('Later deck'));
          assert(entry(3)===first && trigger(3)===firstViewer && move(3)===firstMove);
          assert.equal(main.querySelectorAll('[data-shop-match=true]').length,2);
          group('state');assert.equal(view.shopChoice,'shop:Match');assert.equal(main.querySelectorAll('[data-shop-match=true]').length,2);
          group('shop');main.querySelector('.shop-clear-match').click();assert.equal(view.queueOrder,'shop');
          assert.equal(view.shopChoice,'all');assert.equal(main.querySelectorAll('[data-shop-match=true]').length,0);
          assert.equal(long.querySelectorAll('[data-shop-queue]').length,14);assert.equal(long.querySelector('.shop-long-more'),null);
          assert(main.querySelector('#shop-long-term').closest('section')===long);
        """)

    def test_regrouping_preserves_open_reprint_provenance_and_sheet_clipboard_context(self):
        self.run_queue_js("""
          drawShopping(queueData([qrow('Alpha',1,{state:'waiting_for_reprint',listed_at:'Shop',reprints:dueInfo()})]));
          const wrapper=entry(1),viewer=trigger(1),writers=entry(1).querySelector('.shop-queue-actions'),
            research=entry(1).querySelector('.reprint-info'),provenance=research.querySelector('details'),check=research.querySelector('.reprint-check');
          provenance.open=true;check.focus();check.click();const sheet=[...reprintSheets][0];assert(sheet);
          const pending=deferred();navigator.clipboard={writeText:name=>{assert.equal(name,'Alpha');return pending.promise}};
          const copyButton=sheet.body.querySelectorAll('button').find(node=>node.textContent==='Copy card name');copyButton.click();assert(copyButton.disabled);
          group('shop');assert(entry(1)===wrapper && trigger(1)===viewer);assert(entry(1).querySelector('.shop-queue-actions')===writers);
          assert(entry(1).querySelector('.reprint-info')===research);assert(research.querySelector('details')===provenance && provenance.open);
          assert(check.isConnected);assert(check.closest('.shop-queue-by-shop'));assert(!sheet.closed);
          pending.resolve();await settle();assert(!copyButton.disabled);assert(sheet.body.textContent.includes('Card name copied.'));
          sheet.close();assert(check.isConnected);assert.equal(main.querySelectorAll('.reprint-check').length,1);
          group('state');assert(research.querySelector('details')===provenance && provenance.open);
        """)

    def test_regrouping_closes_an_open_row_menu_and_preserves_its_same_focus_trigger(self):
        self.run_queue_js("""
          drawShopping(queueData([qrow('Alpha',1,{listed_at:'Shop'}),qrow('Beta',2)]));
          const button=move(1),menu=entry(1).querySelector('.menu'),writer=entry(1).querySelector('.shop-queue-actions');
          button.click();assert(!menu.hidden);assert(document.activeElement.closest('.menu')===menu);
          group('shop',false);assert(menu.hidden);assert(document.activeElement===button);
          assert(move(1)===button && entry(1).querySelector('.shop-queue-actions')===writer);
          assert.equal(button.getAttribute('aria-expanded'),'false');button.click();assert(!menu.hidden);
          group('state',false);assert(menu.hidden);assert(document.activeElement===button);
        """)

    def test_lab_keeps_state_groups_and_hidden_controls_inert_then_restores_the_casual_choice(self):
        self.run_queue_js("""
          const view=drawShopping(queueData([qrow('Deferred',1,{state:'deferred',listed_at:'A'}),qrow('Ready',2,{listed_at:'B'})]));
          const viewer=trigger(1),button=edit(1);group('shop');density(true);
          assert(view.queueControls.hidden);assert(document.activeElement===main.querySelector('#shop-to-buy'));
          assert(main.querySelector('.shop-queue-table'));assert.equal(main.querySelector('.shop-queue-by-shop'),null);
          same(main.querySelectorAll('.group-row').map(node=>node.getAttribute('data-queue-group')),['ready','deferred']);
          assert.equal(view.queueOrder,'shop');control('state').click();assert.equal(view.queueOrder,'shop');
          density(false);assert(!view.queueControls.hidden);assert(main.querySelector('.shop-queue-by-shop'));
          assert.equal(control('shop').getAttribute('aria-pressed'),'true');assert(trigger(1)===viewer && edit(1)===button);
          clear(main);const next=drawShopping(queueData([qrow('Fresh view',1)]));assert.equal(next.queueOrder,'state');
        """)

    def test_single_add_node_moves_between_band_and_header_with_original_role_and_open_sheet(self):
        self.run_queue_js("""
          for(const admin of [false,true]){
            clear(main);state.may={admin,orders:true,see_inventory:['home']};density(false);
            const view=drawShopping(queueData([qrow('Alpha',1)])),add=view.addButton;
            assert.equal(main.querySelectorAll('.shop-queue-add').length,1);assert(add.closest('.shop-add-casual'));
            assert(add.classList.contains('shop-queue-add-round'));assert.equal(add.getAttribute('aria-label'),'Add card to the purchase queue');
            assert(add.querySelector('.shop-queue-add-label').classList.contains('sr-only'));
            assert.equal(main.querySelectorAll('.btn-primary').length,1);
            assert.equal(Boolean(main.querySelector('.shop-order-add')),admin);
            if(admin)assert(main.querySelector('.shop-order-add').closest('.page-head-buttons'));
            add.focus();add.click();const sheet=[...shopQueueSheets][0];assert(sheet);
            density(true);assert(view.addButton===add);assert(add.closest('.shop-add-home'));
            assert(!add.classList.contains('shop-queue-add-round'));assert(!add.querySelector('.shop-queue-add-label').classList.contains('sr-only'));assert(!sheet.closed);
            density(false);assert(add.closest('.shop-add-casual'));assert(!sheet.closed);sheet.close();
            assert.equal(main.querySelectorAll('.shop-queue-add').length,1);
          }
          clear(main);state.may={admin:false,orders:false,see_inventory:['home']};
          drawShopping(queueData([qrow('Read only',1)]));assert(control('shop'));assert.equal(main.querySelector('.shop-queue-add'),null);
          assert.equal(main.querySelectorAll('.shop-queue-write').length,0);group('shop');assert.equal(main.querySelectorAll('.shop-queue-write').length,0);
        """)

    def test_focused_add_is_refocused_after_native_style_reparent_blur_and_write_redraw(self):
        self.run_queue_js("""
          const view=drawShopping(queueData([qrow('Alpha',1)])),add=view.addButton,remove=add.remove.bind(add);
          // Model the native focus loss when a focused element is removed; the small DOM double retains it.
          add.remove=()=>{if(document.activeElement===add)document.activeElement=document.body;remove()};
          add.focus();density(true);assert(document.activeElement===add && add.closest('.shop-add-home'));
          density(false);assert(document.activeElement===add && add.closest('.shop-add-casual'));
          add.focus();view.redraw();assert(document.activeElement===add && add.closest('.shop-add-casual'));
          assert.equal(main.querySelectorAll('.shop-queue-add').length,1);
        """)

    def test_first_successful_add_mounts_the_band_and_focuses_the_original_enabled_add_node(self):
        self.run_queue_js("""
          const writes=[];apiWrite=async(path,body)=>{writes.push([path,body]);return {revision:'q2',item:qrow('Alpha',1,{...body.values,name:'Alpha'})}};
          const view=drawShopping(queueData([])),add=view.addButton;
          assert(add.closest('.shop-add-home'));assert.equal(main.querySelector('.shop-queue-controls'),null);
          add.focus();add.click();const sheet=[...shopQueueSheets][0];field(sheet,'name').value='Alpha';field(sheet,'quantity').value='2';
          action(sheet,'Add card').click();await settle();
          assert(sheet.closed);assert(view.addButton===add);assert(add.closest('.shop-add-casual'));assert(!add.disabled);
          assert(document.activeElement===add);assert.equal(main.querySelectorAll('.shop-queue-add').length,1);
          assert.equal(view.data.queue_revision,'q2');assert.equal(entry(1).getAttribute('data-shop-queue'),'1');
          assert.equal(writes.length,1);assert.equal(writes[0][0],'/api/shopping/queue');assert.equal(writes[0][1].expect,'q1');
          assert.equal(writes[0][1].values.quantity,2);assert(main.querySelector('.shop-layout'));
        """)

    def test_last_immediate_move_returns_original_add_home_then_restores_band_on_move_back(self):
        self.run_queue_js("""
          const writes=[];apiWrite=async(path,body)=>{writes.push(body);return {revision:'q'+(writes.length+1)}};
          const queued=qrow('Alpha',1),view=drawShopping(queueData([queued])),add=view.addButton;
          group('shop');goMove(1,'Long-term plan');await settle();
          assert(add.isConnected && add.closest('.shop-add-home'));assert(!add.classList.contains('shop-queue-add-round'));
          assert.equal(main.querySelector('.shop-queue-controls'),null);assert(document.activeElement===move(1));
          assert.equal(view.queueOrder,'shop');assert.equal(queued.state,'long_term');assert.equal(main.querySelectorAll('.shop-queue-add').length,1);
          goMove(1,'Ready to buy');await settle();assert(add.closest('.shop-add-casual'));assert(add.classList.contains('shop-queue-add-round'));
          assert.equal(control('shop').getAttribute('aria-pressed'),'true');assert(document.activeElement===move(1));
          same(writes.map(body=>[body.row,body.expect]),[[1,'q1'],[1,'q2']]);
        """)

    def test_last_immediate_remove_restores_header_add_before_layout_is_detached_and_keeps_focus(self):
        self.run_queue_js("""
          const writes=[];apiWrite=async(path,body)=>{writes.push(body);return {revision:'q2'}};
          const view=drawShopping(queueData([qrow('Alpha',1)])),add=view.addButton;group('shop');
          edit(1).click();const parent=[...shopQueueSheets][0];action(parent,'Remove\u2026').click();
          const confirm=[...shopQueueSheets].at(-1);field(confirm,'reason').value='Changed purchase plan';
          action(confirm,'Remove card').click();await settle();
          assert(parent.closed && confirm.closed);assert.equal(view.data.to_buy.length,0);assert.equal(view.data.queue_revision,'q2');
          assert(add.isConnected && add.closest('.shop-add-home'));assert(document.activeElement===add);assert(!add.disabled);
          assert(!add.classList.contains('shop-queue-add-round'));assert.equal(main.querySelector('.shop-layout'),null);
          assert.equal(main.querySelectorAll('.shop-queue-add').length,1);assert.equal(main.querySelector('.shop-queue-controls'),null);
          same(writes,[{action:'remove',row:1,reason:'Changed purchase plan',expect:'q1'}]);
        """)

    def test_pending_and_conflicted_writes_keep_original_add_disabled_through_regroup_and_density_changes(self):
        self.run_queue_js("""
          for(const conflict of [false,true]){
            clear(main);density(false);const pending=deferred(),writes=[];apiWrite=(path,body)=>{writes.push(body);return pending.promise};
            const view=drawShopping(queueData([qrow('Alpha',1,{listed_at:'A'}),qrow('Beta',2,{listed_at:'B'})])),add=view.addButton;
            goMove(1,'Deferred');const error=entry(1).querySelector('.form-error');group('shop');density(true);density(false);
            assert(view.addButton===add && add.disabled);assert(main.querySelectorAll('.shop-queue-write').every(node=>node.disabled));
            assert.equal(view.queueOrder,'shop');assert.equal(writes.length,1);assert.equal(shopQueueSheet(view),null);
            if(conflict)pending.reject(new ApiError(409,'Saved queue changed'));else pending.resolve({revision:'q2'});await settle();
            group('state');group('shop');assert(view.addButton===add);assert.equal(writes.length,1);
            if(conflict){assert(view.stale && add.disabled);assert(error.isConnected && !error.hidden);assert(error.textContent.includes('Saved queue changed'));
              assert(main.querySelectorAll('.shop-queue-write').every(node=>node.disabled));assert.equal(shopQueueSheet(view),null);assert.equal(view.data.queue_revision,'q1')}
            else{assert(!add.disabled);assert.equal(view.data.queue_revision,'q2');assert.equal(entry(1).querySelector('.shop-queue-category').textContent,'Deferred')}
          }
        """)

    def test_replaced_detached_profile_and_route_controls_cannot_change_grouping_or_open_add_sheets(self):
        self.run_queue_js("""
          let view=drawShopping(queueData([qrow('Alpha',1,{listed_at:'A'})]));const old=control('shop');view.redraw();
          assert(!old.isConnected);old.click();assert.equal(view.queueOrder,'state');assert.equal(control('state').getAttribute('aria-pressed'),'true');
          for(const departure of ['profile','route','detached']){
            clear(main);state.profile=state.profiles[0];density(false);view=drawShopping(queueData([qrow('Current',1,{listed_at:'Shop'})]));
            const button=control('shop'),add=view.addButton,before=entries(),source=JSON.stringify(view.data.to_buy);
            if(departure==='profile')state.profile=state.profiles[1];else if(departure==='route')routeToken++;else clear(main);
            button.click();add.click();assert.equal(view.queueOrder,'state');assert.equal(shopQueueSheets.size,0);
            assert.equal(JSON.stringify(view.data.to_buy),source);assert.equal(view.data.queue_revision,'q1');
            if(departure!=='detached')sameNodes(entries(),before);else assert.equal(main.children.length,0);
          }
        """)
