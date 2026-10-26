"""Collection keyboard ownership and native-control focus over isolated fixtures.

The DOM double normally retains removed focus. Focus tests explicitly model the
browser's BODY fallback so restoring a detached button cannot satisfy them.
"""
import unittest

from decklab.tests import test_collection_find_layout_ui, test_collection_layout_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionKeyboardConflictsUiTests(unittest.TestCase):
    run_js = test_collection_layout_ui.CollectionLayoutUiTests.run_js

    def test_native_sort_enter_restores_the_fresh_header_after_body_fallback(self):
        self.run_js("""
          const cv=draw(), sha=cv.sha256, selected='fdn|1|foil'; colSelectRow(cv,selected);
          const originalClear=clear;
          clear=node=>{const owns=node.contains(document.activeElement), result=originalClear(node);
            if(owns) document.activeElement=document.body; return result;};
          const header=key=>main.querySelector('[data-col-sort="'+key+'"]');
          for(const key of ['price','price','quantity','name']) {
            const before=header(key); before.focus();
            const region=main.querySelector('.col-row-lab').querySelector('.table-wrap');
            assert(!region.fire('keydown',{key:'Enter',target:before}).defaultPrevented,
              'header Enter remains a native button activation');
            before.click(); const fresh=header(key);
            assert.notEqual(fresh,before); assert(!before.isConnected); assert(fresh.isConnected);
            assert.equal(document.activeElement,fresh); assert.equal(fresh.focusOptions.preventScroll,true);
            assert.equal(cv.sort.key,key); assert.equal(cv.selectedKey,selected); assert.equal(cv.sha256,sha);
            assert.equal(main.querySelectorAll('[aria-sort]').filter(node=>node.getAttribute('aria-sort')!=='none').length,1);
          }
          assert.equal(inspections.length,0);
        """)

    def test_pager_keeps_its_side_and_action_then_uses_the_table_when_disabled(self):
        self.run_js("""
          const many=Array.from({length:205},(_,i)=>row('Card '+String(i).padStart(3,'0'),i));
          const cv=draw({rows:many,pictures:{}}), originalClear=clear;
          clear=node=>{const owns=node.contains(document.activeElement), result=originalClear(node);
            if(owns) document.activeElement=document.body; return result;};
          const pager=label=>main.querySelectorAll('.col-pager').find(node=>node.getAttribute('aria-label')===label);
          const action=(label,text)=>pager(label).querySelectorAll('button').find(node=>node.getAttribute('aria-label')===text);
          const next=action('Pages, top','Next page'); next.focus(); next.click();
          assert.equal(cv.page,2); assert(!next.isConnected);
          assert.equal(document.activeElement,action('Pages, top','Next page'));
          const last=action('Pages, bottom','Last page'); last.focus(); last.click();
          assert.equal(cv.page,3); assert(action('Pages, bottom','Last page').disabled);
          assert.equal(document.activeElement,main.querySelector('.col-row-lab').querySelector('.table-wrap'));
          assert.equal(tableRows().length,5); assert.equal(inspections.length,0);
        """)

    def test_redraw_never_reclaims_unrelated_focus_or_uses_old_sort_and_pager_controls(self):
        self.run_js("""
          const many=Array.from({length:105},(_,i)=>row('Card '+String(i).padStart(3,'0'),i));
          const cv=draw({rows:many,pictures:{}}), oldSort=main.querySelector('[data-col-sort="price"]');
          const oldNext=main.querySelector('.col-pager').querySelectorAll('button').find(node=>node.getAttribute('aria-label')==='Next page');
          const outside=el('button'); document.body.append(outside); outside.focus();
          drawColRowList(cv); oldSort.click(); oldNext.click();
          assert.equal(cv.sort.key,'name'); assert.equal(cv.page,1); assert.equal(document.activeElement,outside);
          const current=main.querySelector('[data-col-sort="price"]'); current.focus();
          const originalClear=clear;
          clear=node=>{const result=originalClear(node); if(node===cv.list) outside.focus(); return result;};
          current.click(); assert.equal(cv.sort.key,'price'); assert.equal(document.activeElement,outside);
          const profile=state.profile;
          for(const [change,restore] of [[()=>{cv.busy=true;},()=>{cv.busy=false;}],
              [()=>{routeToken++;},()=>{routeToken--;}],[()=>{state.profile={id:'other'};},()=>{state.profile=profile;}]]) {
            change(); const saved=cv.sort.key; main.querySelector('[data-col-sort="quantity"]').click();
            assert.equal(cv.sort.key,saved); assert.equal(document.activeElement,outside); restore();
          }
        """)

    def test_exact_modifiers_composition_and_cancelled_events_never_move_or_open(self):
        self.run_js("""
          const cv=draw(); colSelectRow(cv,'fdn|1|foil'); const selected=cv.selectedKey;
          for(const key of ['j','k','Enter']) for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},
              {shiftKey:true},{isComposing:true},{keyCode:229},{defaultPrevented:true}]) {
            const region=main.querySelector('.col-row-lab').querySelector('.table-wrap');
            const target=tableRow(selected).querySelector('.col-open');
            const before=document.activeElement;
            const event=region.fire('keydown',{key,target,...extra});
            assert.equal(event.defaultPrevented,Boolean(extra.defaultPrevented));
            assert.equal(cv.selectedKey,selected); assert.equal(document.activeElement,before);
          }
          assert.equal(inspections.length,0);
        """)

    def test_held_navigation_repeats_but_owned_enter_activation_does_not(self):
        self.run_js("""
          const cv=draw(), sorted=colShownRows(cv);
          const region=()=>main.querySelector('.col-row-lab').querySelector('.table-wrap');
          assert(region().fire('keydown',{key:'j',repeat:true}).defaultPrevented);
          assert.equal(cv.selectedKey,colKey(sorted[0]));
          region().fire('keydown',{key:'j',repeat:true}); assert.equal(cv.selectedKey,colKey(sorted[1]));
          const choice=tableRow(cv.selectedKey).querySelector('.col-open');
          assert(region().fire('keydown',{key:'Enter',target:choice,repeat:true}).defaultPrevented);
          assert.equal(inspections.length,0,'prevented repeated Enter must not become a native click');
          assert(region().fire('keydown',{key:'Enter',target:choice}).defaultPrevented);
          assert.equal(inspections.length,1); assert(inspections[0].trigger.isConnected);
        """)

    def test_typing_modal_menu_and_reparented_targets_keep_their_own_context(self):
        self.run_js("""
          const cv=draw(), region=()=>main.querySelector('.col-row-lab').querySelector('.table-wrap');
          for(const tag of ['input','textarea','select']) {
            const target=el(tag); region().append(target); target.focus();
            assert(!region().fire('keydown',{key:'j',target}).defaultPrevented); assert.equal(cv.selectedKey,null);
          }
          const editing=el('div',{contenteditable:'true'}), text=el('span'); editing.append(text); region().append(editing);
          assert(!region().fire('keydown',{key:'j',target:text}).defaultPrevented);
          const boundary=el('div',{contenteditable:'false'}), ordinary=el('span'); boundary.append(ordinary); editing.append(boundary);
          assert(region().fire('keydown',{key:'j',target:ordinary}).defaultPrevented,
            'nearest contenteditable=false preserves ordinary navigation');
          const selected=cv.selectedKey, current=region(), outside=el('button'); document.body.append(outside); outside.focus();
          let menu=true; keyboardMenuOpen=()=>menu;
          assert(!current.fire('keydown',{key:'j'}).defaultPrevented); menu=false;
          const dialog=el('dialog',{open:true}); document.body.append(dialog);
          assert(!current.fire('keydown',{key:'j'}).defaultPrevented); dialog.remove();
          assert(!current.fire('keydown',{key:'j',target:outside}).defaultPrevented);
          current.remove(); document.body.append(current);
          assert(!current.fire('keydown',{key:'j'}).defaultPrevented);
          assert.equal(cv.selectedKey,selected); assert.equal(document.activeElement,outside); assert.equal(inspections.length,0);
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionSearchKeyboardConflictsUiTests(unittest.TestCase):
    run_js = test_collection_find_layout_ui.CollectionFindLayoutUiTests.run_js

    def test_search_enter_requires_an_exact_owned_uncomposed_activation_and_clears_debounce(self):
        self.run_js("""
          const cv=drawFind(), input=main.querySelector('#collection-q'), calls=[];
          colFilter=(...args)=>calls.push(args); input.focus(); input.value='  Alpha  ';
          for(const extra of [{ctrlKey:true},{metaKey:true},{altKey:true},{shiftKey:true},
              {isComposing:true},{keyCode:229},{defaultPrevented:true}]) {
            const event=input.fire('keydown',{key:'Enter',...extra});
            assert.equal(event.defaultPrevented,Boolean(extra.defaultPrevented)); assert.equal(calls.length,0);
          }
          assert(input.fire('keydown',{key:'Enter',repeat:true}).defaultPrevented); assert.equal(calls.length,0);
          input.fire('input'); assert(input.fire('keydown',{key:'Enter'}).defaultPrevented); flushTimers();
          assert.equal(calls.length,1); assert.equal(calls[0][0],cv); same(calls[0].slice(1),['q','Alpha']);
        """)

    def test_search_yields_to_modal_menu_stale_view_reparenting_and_unrelated_focus(self):
        self.run_js("""
          const cv=drawFind(), input=main.querySelector('#collection-q'), calls=[];
          colFilter=(...args)=>calls.push(args); input.value='Alpha'; input.focus();
          let menu=true; keyboardMenuOpen=()=>menu;
          assert(!input.fire('keydown',{key:'Enter'}).defaultPrevented); menu=false;
          const dialog=el('dialog',{open:true}); document.body.append(dialog);
          assert(!input.fire('keydown',{key:'Enter'}).defaultPrevented); dialog.remove();
          const outside=el('button'); document.body.append(outside); outside.focus();
          assert(!input.fire('keydown',{key:'Enter'}).defaultPrevented); input.focus();
          assert(!input.fire('keydown',{key:'Enter',target:outside}).defaultPrevented);
          cv.busy=true; input.fire('keydown',{key:'Enter'}); cv.busy=false;
          routeToken++; input.fire('keydown',{key:'Enter'}); routeToken--;
          const profile=state.profile; state.profile={id:'other'}; input.fire('keydown',{key:'Enter'}); state.profile=profile;
          input.remove(); document.body.append(input); input.fire('keydown',{key:'Enter'});
          assert.equal(calls.length,0); assert.equal(document.activeElement,input);
        """)
