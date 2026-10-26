"""Focused delivery shortcuts navigate only the current readable receipt; they never record it."""
import unittest
from decklab.tests import test_shopping_ui
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  state.may = {admin: false, orders: true, receipts: true, see_inventory: ['home']};
  state.profile = state.profiles[1];
  let reads=0, writes=0;
  api = async () => {reads++; throw new Error('Shortcut must not read');};
  apiWrite = async () => {writes++; throw new Error('Shortcut must not write');};
  const make = (extra={}) => {
    clear(main); location.hash='#/shopping';
    const current=order(extra), view=drawShopping({...empty,orders:[current]});
    const summary=main.querySelector('.shop-delivery-summary');
    summary.focus();
    return {current,view,summary};
  };
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShoppingReceiveKeysUiTests(unittest.TestCase):
    def run_js(self, scenario):
        test_shopping_ui.ShoppingInteractionTests.run_js(self, SETUP+scenario)

    def test_r_opens_only_the_focused_current_delivery_without_reading_or_recording(self):
        self.run_js(r'''
          const first=order({id:'first / +&?'}), second=order({id:'second'});
          const view=drawShopping({...empty,orders:[first,second]});
          const summaries=main.querySelectorAll('.shop-delivery-summary');
          for(const [index,key] of [[0,'r'],[1,'R']]) {
            const summary=summaries[index], delivery=summary.closest('.shop-delivery');
            summary.focus(); const before=delivery.getAttribute('open');
            assert(summary.fire('keydown',{key}).defaultPrevented);
            assert.equal(location.hash,'#/receipt?order='+encodeURIComponent(index?second.id:first.id));
            assert.equal(document.activeElement,summary); assert.equal(delivery.getAttribute('open'),before);
            location.hash='#/shopping';
          }
          assert.equal(reads,0); assert.equal(writes,0);
        ''')

    def test_native_disclosure_keys_modifiers_and_repeated_or_composed_input_are_untouched(self):
        self.run_js(r'''
          const {summary}=make();
          for(const props of [{key:'Enter'},{key:' '},{key:'Escape'},{key:'x'},
              {key:'r',ctrlKey:true},{key:'r',metaKey:true},{key:'r',altKey:true},
              {key:'r',isComposing:true},{key:'r',repeat:true}]) {
            assert(!summary.fire('keydown',props).defaultPrevented);
            assert.equal(location.hash,'#/shopping');
          }
          summary.fire('keydown',{key:'r',defaultPrevented:true});
          assert.equal(location.hash,'#/shopping'); assert.equal(reads,0); assert.equal(writes,0);
        ''')

    def test_stale_detached_busy_and_changed_permission_or_order_context_cannot_navigate(self):
        self.run_js(r'''
          for(const [index,mutate] of [
              x=>{x.view.busy=true;},x=>{x.view.stale=true;},x=>{x.view.token=routeToken-1;},
              x=>{state.profile=state.profiles[0];},x=>{state.may.receipts=false;},
              x=>{x.view.data.orders=[];},x=>{x.view.data.orders=[{...x.current}];},
              x=>{x.current.components[0].status='received';},x=>{x.view.root.remove();},
              x=>{x.summary.remove();main.append(x.summary);},x=>{document.activeElement=main;}].entries()) {
            state.profile=state.profiles[1]; state.may.receipts=true;
            const x=make(); mutate(x);
            assert(!x.summary.fire('keydown',{key:'r'}).defaultPrevented,'blocked context '+index);
            assert.equal(location.hash,'#/shopping');
          }
          assert.equal(reads,0); assert.equal(writes,0);
        ''')

    def test_child_controls_and_read_only_delivery_rows_keep_their_own_actions(self):
        self.run_js(r'''
          const {summary}=make();
          for(const tag of ['input','textarea','select','button','a','span']) {
            const child=el(tag); summary.append(child); child.focus();
            assert(!summary.fire('keydown',{key:'r',target:child}).defaultPrevented);
            assert.equal(location.hash,'#/shopping'); child.remove();
          }
          assert.equal(summary.getAttribute('aria-keyshortcuts'),'R');
          const description=main.querySelector('#'+summary.getAttribute('aria-describedby'));
          assert(description); assert(description.textContent.includes('Press R from this delivery row to open Receive delivery.'));
          assert(description.textContent.includes('Enter or Space expands or collapses the row.'));
          assert.equal(main.querySelector('.shop-receive-hint').textContent,'R');
          clear(main); state.may.receipts=false;
          const readOnly=make();
          assert.equal(readOnly.summary.getAttribute('aria-keyshortcuts'),null);
          assert.equal(readOnly.summary.getAttribute('aria-describedby'),null);
          assert.equal(main.querySelector('.shop-receive-hint'),null);
          assert(!readOnly.summary.fire('keydown',{key:'r'}).defaultPrevented);
          assert.equal(location.hash,'#/shopping'); assert.equal(reads,0); assert.equal(writes,0);
        ''')
