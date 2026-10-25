"""Shopping's P1 frame: pane ownership without changing buying decisions or write lifecycles."""
from pathlib import Path
import re
import unittest

from decklab.tests import test_shopping_ui, test_shopping_queue_manage_ui
from decklab.tests.test_workspace_ui import NODE, WEB


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingLayoutUiTests(unittest.TestCase):
    run_js = test_shopping_ui.ShoppingInteractionTests.run_js
    run_queue_js = test_shopping_queue_manage_ui.ShoppingQueueManagementInteractionTests.run_queue_js

    def test_existing_sections_belong_to_the_two_panes_and_history_stays_below(self):
        self.run_js(r"""
          state.may={admin:true,orders:true,receipts:true};
          const pending=order(),past=order({id:'past',status:'received',components:[component({status:'received'})]});
          const queued=[row('Alpha',{queue_row:1,listed_at:'Shop'}),row('Beta',{queue_row:2,state:'long_term',listed_at:'Shop'})];
          const view=drawShopping({...empty,queue_revision:'q1',to_buy:queued,orders:[pending,past],
            checks:[{order_id:'past',component_id:'cards',status:'received',text:'Check token'}],
            decks_missing:[{id:'casual/otters',title:'Otters',kind:'casual',status:'idea',missing:2}],
            missing_cards:{ready:true,rows:[{name:'Missing',missing:2,decks:[],queue:[],card:null}],warnings:[],errors:[]}});
          const left=main.querySelector('.shop-list-pane'),right=main.querySelector('.shop-detail-pane');
          for(const id of ['shop-on-the-way','shop-follow-ups','shop-by-shop'])assert(left.contains(main.querySelector('#'+id)),id);
          for(const id of ['shop-to-buy','shop-missing-cards','shop-decks','shop-long-term'])assert(right.contains(main.querySelector('#'+id)),id);
          assert.equal(main.querySelectorAll('.shop-layout').length,1);assert.equal(right.hidden,false);
          assert(!left.contains(main.querySelector('.shop-history')));assert(!right.contains(main.querySelector('.shop-history')));
          same(right.querySelectorAll('.shop-queue-edit').map(node=>Number(node.dataset.queueRow)),[1,2]);
          assert.equal(left.querySelectorAll('.shop-queue-edit').length,0,'shop research stays read-only');
          assert(main.querySelector('.shop-jumps'));assert.equal(view.data.to_buy,queued);
        """)

    def test_stacked_jump_moves_keyboard_focus_without_changing_the_route(self):
        self.run_js(r"""
          drawShopping({...empty,to_buy:[row('Alpha',{queue_row:1})],orders:[order()]});
          const target=main.querySelector('#shop-to-buy'),nav=main.querySelector('.shop-jumps');
          const link=nav.querySelectorAll('a').find(node=>node.getAttribute('href')==='#shop-to-buy');
          link.focus();const event=link.fire('click');
          assert(event.defaultPrevented);assert.equal(location.hash,'#/shopping');
          assert.equal(document.activeElement,target);assert.equal(target.getAttribute('tabindex'),'-1');
          assert(target.scrolled);clear(main);link.fire('click');
          assert.equal(location.hash,'#/shopping','a stale jump does not route away');
        """)

    def test_initial_empty_add_last_remove_and_add_again_attach_the_same_frame(self):
        self.run_queue_js(r"""
          for(const category of ['ready','long_term']){
            clear(main);const writes=[];
            apiWrite=async(path,body)=>{writes.push(body);return saved(body,
              body.action==='add'?row('Alpha',{...body.values,name:'Alpha',quantity:1}):null,'q'+writes.length);};
            const view=drawShopping(queueData([]));assert.equal(main.querySelector('.shop-layout'),null);
            assert.equal(main.querySelector('.shop-empty').hidden,false);
            const add=async()=>{const sheet=openAdd();type(sheet,'name','Alpha');field(sheet,'state').value=category;
              action(sheet,'Add card').click();await settle();};
            await add();const layout=main.querySelector('.shop-layout'),left=main.querySelector('.shop-list-pane');
            const deliverySection=main.querySelector('#shop-on-the-way').closest('section');
            assert(layout);assert.equal(main.querySelector('.shop-empty').hidden,true);
            assert.equal(main.querySelector('.shop-detail-pane').hidden,false);
            assert(main.querySelector(category==='ready'?'#shop-to-buy':'#shop-long-term'));
            const parent=openDetails(1);action(parent,'Remove\u2026').click();const confirm=latestSheet();
            type(confirm,'reason','No longer needed');action(confirm,'Remove card').click();await settle();
            assert.equal(main.querySelector('.shop-layout'),null);assert.equal(main.querySelector('.shop-empty').hidden,false);
            assert.equal(main.querySelectorAll('.card-row').length,0);assert(main.querySelector('.shop-queue-add'));
            await add();assert.equal(main.querySelector('.shop-layout'),layout);
            assert.equal(main.querySelector('.shop-list-pane'),left);
            assert.equal(main.querySelector('#shop-on-the-way').closest('section'),deliverySection);
            assert.equal(main.querySelector('.shop-detail-pane').hidden,false);assert.equal(writes.length,3);
          }
        """)

    def test_missing_only_unavailable_only_and_long_term_shop_research_keep_detail_visible(self):
        self.run_js(r"""
          state.may={admin:false,orders:false,receipts:false};
          const cases=[
            {...empty,missing_cards:{ready:true,rows:[{name:'Alpha',missing:2,decks:[],queue:[],card:null}],warnings:[],errors:[]}},
            {...empty,missing_cards:{ready:false,rows:[],warnings:[],errors:[{message:'Card data unavailable'}]}},
            {...empty,to_buy:[row('Later',{state:'long_term',listed_at:'Recorded shop'})]},
          ];
          for(const data of cases){clear(main);drawShopping(data);
            assert(main.querySelector('.shop-layout'));assert.equal(main.querySelector('.shop-empty').hidden,true);
            assert.equal(main.querySelector('.shop-detail-pane').hidden,false);
            if(data.to_buy.length){
              assert(main.querySelector('.shop-list-pane').contains(main.querySelector('#shop-by-shop')));
              assert(main.querySelector('.shop-detail-pane').contains(main.querySelector('#shop-long-term')));
            }else assert(main.querySelector('.shop-detail-pane').contains(main.querySelector('#shop-missing-cards')));
          }
        """)

    def test_queue_edit_preserves_delivery_followup_undo_and_history_nodes_in_list_pane(self):
        self.run_queue_js(r"""
          const writes=[],card=queueRow(1);
          apiWrite=async(path,body)=>{writes.push([path,body]);return saved(body,{...card,...body.values});};
          const view=drawShopping({...queueData([card]),orders:[order(),order({id:'past',status:'received',components:[component({status:'received'})]})],
            checks:[{order_id:'past',component_id:'cards',status:'received',text:'Check token'}]});
          const layout=main.querySelector('.shop-layout'),left=main.querySelector('.shop-list-pane');
          const delivery=main.querySelector('.shop-delivery'),followup=main.querySelector('.shop-followup'),history=main.querySelector('.shop-history');
          history.setAttribute('open','');followup.querySelector('button').click();
          const undo=document.getElementById('toast-undo').querySelector('button');
          const sheet=openDetails(1);type(sheet,'quantity','2');action(sheet,'Save').click();await settle();
          assert.equal(main.querySelector('.shop-layout'),layout);assert.equal(main.querySelector('.shop-list-pane'),left);
          assert.equal(main.querySelector('.shop-delivery'),delivery);assert.equal(main.querySelector('.shop-followup'),followup);
          assert(left.contains(delivery));assert(left.contains(followup));assert.equal(followup.hidden,true);
          assert.equal(main.querySelector('.shop-history'),history);assert.equal(history.getAttribute('open'),'');
          assert.equal(document.getElementById('toast-undo').querySelector('button'),undo);
          undo.click();assert.equal(followup.hidden,false);flushTimers();await settle();
          assert.equal(writes.length,1);assert.equal(writes[0][0],'/api/shopping/queue');
          assert.equal(view.data.queue_revision,'queue-v2');
        """)

    def test_delivery_only_hides_the_detail_pane_and_keeps_read_only_delivery_details(self):
        self.run_js(r"""
          state.may={admin:false,orders:false,receipts:false};drawShopping({...empty,queue_revision:'q1',orders:[order()]});
          const left=main.querySelector('.shop-list-pane'),right=main.querySelector('.shop-detail-pane');
          assert(left.querySelector('.shop-delivery'));assert.equal(right.hidden,true);
          const link=left.querySelector('.shop-delivery').querySelector('.actions').querySelector('a');
          assert.equal(link.textContent,'Delivery details');assert(link.getAttribute('href').startsWith('#/receipt?order='));
          assert.equal(main.querySelector('.shop-order-add'),null);assert.equal(main.querySelector('.shop-queue-add'),null);
          assert.equal(main.querySelector('.shop-empty').hidden,true);
        """)

    def test_admin_new_order_and_member_add_primary_permissions_are_unchanged(self):
        self.run_js(r"""
          for(const [may,newOrder,addCard] of [[{admin:true,orders:true},true,true],[{admin:false,orders:true},false,true],
              [{admin:false,orders:false},false,false]]){
            clear(main);state.may=may;drawShopping({...empty,queue_revision:'q1'});
            const orderButton=main.querySelector('.shop-order-add'),addButton=main.querySelector('.shop-queue-add');
            assert.equal(!!orderButton,newOrder);assert.equal(!!addButton,addCard);
            if(orderButton)assert(orderButton.getAttribute('class').split(' ').includes('btn-primary'));
            if(addButton)assert.equal(addButton.getAttribute('class').split(' ').includes('btn-primary'),!newOrder);
          }
          clear(main);state.may={admin:true,orders:true};drawShopping(empty);
          assert.equal(main.querySelector('.shop-order-add'),null);assert.equal(main.querySelector('.shop-queue-add'),null);
        """)


class ShoppingLayoutStyleTests(unittest.TestCase):
    def test_fixed_list_pane_starts_after_1280_and_stacked_layout_keeps_jump_links(self):
        css=(WEB/'shopping.css').read_text(encoding='utf-8')
        initial=re.search(r'\.shop-layout \{([^}]+)\}',css).group(1)
        self.assertNotIn('grid-template-columns',initial)
        wide='\n'.join(re.findall(r'@media \(min-width: 1281px\) \{\n(.*?)\n\}',css,re.S))
        self.assertIn('grid-template-columns: 560px minmax(0, 1fr)',wide)
        self.assertIn('.shop-jumps { display: none; }',css.split('@media (min-width: 1281px)',1)[1])
        self.assertNotRegex(css,r'@media \(min-width: (?:1000|1600)px\) \{\n\s*\.shop-layout')
        self.assertIn('min-width: 0',re.search(r'\.shop-main, \.shop-side \{([^}]+)\}',css).group(1))
