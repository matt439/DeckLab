"""Shared menu ownership and native editing/browser keys over the isolated event/DOM fixture."""
import unittest

from decklab.tests import test_workspace_ui

NODE = test_workspace_ui.NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SharedMenuKeyboardUiTests(unittest.TestCase):
    run_js = test_workspace_ui.WorkspaceInteractionTests.run_js

    def test_popover_owns_plain_navigation_but_not_modified_composing_or_handled_keys(self):
        self.run_js("""
          const wrap=menuButton('More',[{label:'One',onclick(){}},{label:'Two',onclick(){}}]);main.append(wrap);
          const anchor=wrap.querySelector('.menu-button'),menu=wrap.querySelector('[role=menu]');anchor.click();
          const items=menu.querySelectorAll('[role=menuitem]'),press=(key,extra={})=>menu.fire('keydown',{key,target:document.activeElement,...extra});
          assert.equal(document.activeElement,items[0]);assert(keyboardMenuOpen());
          for(const extra of [{altKey:true},{ctrlKey:true},{metaKey:true},{shiftKey:true},{isComposing:true},{keyCode:229},{defaultPrevented:true}]) {
            press('ArrowDown',extra);assert.equal(document.activeElement,items[0]);assert(!menu.hidden);
          }
          assert(press('ArrowDown',{repeat:true}).defaultPrevented);assert.equal(document.activeElement,items[1]);
          assert(press('Enter',{repeat:true}).defaultPrevented);assert(!menu.hidden);
          const edit=el('input');menu.append(edit);edit.focus();assert(!press('ArrowUp').defaultPrevented);
          assert.equal(document.activeElement,edit);items[1].focus();
          const tab=press('Tab',{shiftKey:true});assert(!tab.defaultPrevented);assert(menu.hidden);
          assert(!keyboardMenuOpen());anchor.click();press('Escape');assert(menu.hidden);assert.equal(document.activeElement,anchor);
          assert(!press('ArrowDown').defaultPrevented,'a hidden menu is inert');
        """)

    def test_overflow_skips_disabled_items_and_the_two_menu_types_are_exclusive(self):
        self.run_js("""
          const wrap=menuButton('More',[{label:'Core',onclick(){}}]);main.append(wrap);
          const core=wrap.querySelector('[role=menu]'),coreButton=wrap.querySelector('.menu-button');coreButton.click();
          const anchor=el('button',{text:'Row More'});main.append(anchor);
          const overflow=openMenu(anchor,[{text:'Disabled',disabled:true},{text:'One'},{text:'Disabled link',href:'#x',disabled:true},{text:'Two'}]);
          const menu=overflow.node,items=menu.querySelectorAll('[role=menuitem]');assert(core.hidden);
          assert.equal(document.activeElement,items[1]);assert(keyboardMenuOpen());
          const press=(key,extra={})=>menu.fire('keydown',{key,target:document.activeElement,...extra});
          assert(!press('End',{altKey:true}).defaultPrevented);assert.equal(document.activeElement,items[1]);
          assert(!press('End',{isComposing:true}).defaultPrevented);assert.equal(document.activeElement,items[1]);
          press('End',{defaultPrevented:true});assert.equal(document.activeElement,items[1]);
          assert(press('ArrowDown',{repeat:true}).defaultPrevented);assert.equal(document.activeElement,items[3]);
          press('Home');assert.equal(document.activeElement,items[1]);press('End');assert.equal(document.activeElement,items[3]);
          assert(press('Enter',{repeat:true}).defaultPrevented);assert(menu.isConnected);
          const tab=press('Tab',{shiftKey:true});assert(!tab.defaultPrevented);assert(!menu.isConnected);
          const second=openMenu(anchor,[{text:'One'}]);coreButton.click();assert(!second.node.isConnected);assert(!core.hidden);
        """)

    def test_dialog_or_consumed_escape_does_not_dismiss_a_menu_behind_it(self):
        self.run_js("""
          const wrap=menuButton('More',[{label:'One',onclick(){}}]);main.append(wrap);
          const anchor=wrap.querySelector('.menu-button'),menu=wrap.querySelector('[role=menu]');anchor.click();
          const original=menu.querySelector('[role=menuitem]');
          document.fire('keydown',{key:'Escape',target:original,defaultPrevented:true});assert(!menu.hidden);
          document.fire('keydown',{key:'Escape',target:original,isComposing:true});assert(!menu.hidden);
          const dialog=el('dialog',{open:''}),close=el('button',{text:'Close'});dialog.open=true;dialog.append(close);document.body.append(dialog);close.focus();
          assert.equal(keyboardDialog(),dialog);assert(!keyboardMenuOpen(),'the modal owns keys over the background menu');
          document.fire('keydown',{key:'Escape',target:close});assert(!menu.hidden);
          menu.fire('keydown',{key:'ArrowDown',target:original});assert.equal(document.activeElement,close);
          dialog.open=false;dialog.removeAttribute('open');dialog.remove();original.focus();
          const esc=document.fire('keydown',{key:'Escape',target:original});assert(esc.defaultPrevented);
          assert(menu.hidden);assert.equal(document.activeElement,anchor);
          anchor.click();const stale=menu.querySelector('[role=menuitem]');wrap.remove();
          assert(!menu.fire('keydown',{key:'ArrowDown',target:stale}).defaultPrevented);
        """)

    def test_effective_editing_and_hidden_menu_boundaries_are_shared(self):
        self.run_js("""
          for(const tag of ['input','select','textarea']) {const node=el(tag);main.append(node);assert(keyboardEditing(node));}
          const edit=el('div',{contenteditable:'true'}),child=el('span'),ordinary=el('div',{contenteditable:'false'}),button=el('button');
          edit.append(child,ordinary);ordinary.append(button);main.append(edit);
          assert(keyboardEditing(child));assert(!keyboardEditing(button));
          const hidden=el('section',{hidden:true}),menu=el('div',{role:'menu'});hidden.append(menu);main.append(hidden);
          assert(!keyboardMenuOpen());hidden.hidden=false;assert(keyboardMenuOpen());hidden.remove();assert(!keyboardMenuOpen());
          const dialog=el('dialog'),inside=el('div',{role:'menu'});dialog.append(inside);document.body.append(dialog);
          assert(!keyboardMenuOpen());dialog.open=true;assert(keyboardMenuOpen());
          dialog.open=false;assert(!keyboardMenuOpen());
        """)

    def test_stale_disabled_and_background_anchors_cannot_replace_a_current_overflow_menu(self):
        self.run_js("""
          const dialog=el('dialog',{open:''}),anchor=el('button');dialog.open=true;dialog.append(anchor);document.body.append(dialog);anchor.focus();
          const active=openMenu(anchor,[{text:'Keep'}]),focused=document.activeElement;
          const stale=el('button'),disabled=el('button',{disabled:true}),background=el('button');main.append(disabled,background);
          for(const wrong of [stale,disabled,background]) {
            const ignored=openMenu(wrong,[{text:'Wrong'}]);assert.equal(ignored.node,null);
            assert(active.node.isConnected);assert.equal(openMenuNow.node,active.node);assert.equal(document.activeElement,focused);
          }
        """)

    def test_held_activation_does_not_reopen_after_a_choice_returns_focus_to_its_anchor(self):
        self.run_js("""
          let chosen=0;const anchor=el('button',{onclick:()=>openMenu(anchor,[{text:'Pick',onclick:()=>chosen++}])});main.append(anchor);anchor.click();
          const menu=openMenuNow.node,item=menu.querySelector('[role=menuitem]');
          const enter=menu.fire('keydown',{key:'Enter',target:item});if(!enter.defaultPrevented)item.click();
          assert.equal(chosen,1);assert.equal(document.activeElement,anchor);assert(!menu.isConnected);
          const held=anchor.fire('keydown',{key:'Enter',repeat:true});if(!held.defaultPrevented)anchor.click();
          assert(held.defaultPrevented);assert.equal(openMenuNow,null);assert.equal(chosen,1);
          const wrap=menuButton('More',[{label:'Pick',onclick:()=>chosen++}]);main.append(wrap);
          const button=wrap.querySelector('.menu-button'),core=wrap.querySelector('[role=menu]');button.click();
          core.querySelector('[role=menuitem]').click();assert.equal(document.activeElement,button);assert(core.hidden);
          const again=button.fire('keydown',{key:' ',repeat:true});if(!again.defaultPrevented)button.click();
          assert(again.defaultPrevented);assert(core.hidden);assert.equal(chosen,2);
        """)

    def test_a_reused_dialog_retains_opening_order_when_focus_temporarily_returns_to_body(self):
        self.run_js("""
          const viewer=el('dialog'),close=el('button');viewer.append(close);document.body.append(viewer);
          viewer.open=true;close.focus();document.fire('focusin',{target:close});assert.equal(keyboardDialog(),viewer);
          viewer.open=false;
          const sheet=el('dialog'),sheetButton=el('button');sheet.append(sheetButton);document.body.append(sheet);
          sheet.open=true;sheetButton.focus();document.fire('focusin',{target:sheetButton});assert.equal(keyboardDialog(),sheet);
          viewer.open=true;close.focus();document.fire('focusin',{target:close});document.activeElement=document.body;
          assert.equal(keyboardDialog(),viewer,'the reused top-layer viewer is earlier in DOM order');
          viewer.open=false;sheetButton.focus();document.fire('focusin',{target:sheetButton});document.activeElement=document.body;
          assert.equal(keyboardDialog(),sheet);
        """)

    def test_orphan_overflow_yields_keyboard_ownership_and_route_cleanup_removes_it(self):
        self.run_js("""
          const anchor=el('button');main.append(anchor);const menu=openMenu(anchor,[{text:'One'}]);anchor.remove();
          assert(menu.node.isConnected);assert(!keyboardMenuOpen(),'detached anchor cannot own the next page');
          closeMenus();assert(!menu.node.isConnected);assert.equal(openMenuNow,null);
          const another=el('button');main.append(another);const orphan=openMenu(another,[{text:'One'}]);another.remove();
          const key=orphan.node.fire('keydown',{key:'Escape',target:orphan.node.querySelector('[role=menuitem]')});
          assert(!key.defaultPrevented);assert(!orphan.node.isConnected);assert.equal(openMenuNow,null);
        """)
