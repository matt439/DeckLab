"""Page shortcut ownership over the existing synthetic event/DOM fixtures.

Loads real Library, deck tab and viewer handlers. Viewer transitions alone are
recorded instead of animated; no keyboard guard/helper is replaced. The fixture
disables fetch, and these scenarios reject unexpected data writes. This file was
prepared by source review only: no Node/Python test process was run.

After integration, from the repo root:
    python scripts/test_fixtures.py decklab.tests.test_page_keyboard_ownership_ui
"""
import unittest

from decklab.tests import test_deck_page_ui as deck_ui
from decklab.tests import test_library_ui as library_ui
from decklab.tests import test_workspace_ui as workspace_ui


LIBRARY_KEYS = r"""
  as('matt', MAY.admin);
  window.matchMedia(LIB_LAB_QUERY).matches = true;
  const addresses = [];
  history.replaceState = (value, title, hash) => { addresses.push(hash); location.hash = hash; };
  let writes = 0;
  apiWrite = async () => { writes++; throw Error('unexpected data write'); };
  const selected = (root = main) => root.querySelector('.lib-detail')?.getAttribute('data-id');
  const rows = () => main.querySelectorAll('.deck-row');
  function mountLibrary() {
    closeMenus();
    clear(main);
    state.profile = PROFILES[0]; state.may = MAY.admin;
    location.hash = '#/library?all=1&deck=commander%2Fgiada';
    state.library = DATA;
    drawLibrary(DATA, libraryFilters(parseHash().params));
    const root = main.querySelector('.results');
    assert(root?.isConnected); assert(rows().length > 2);
    main.focus();
    return root;
  }
  function blockedLibrary(props = {}, target = main, label = 'owned key') {
    const before = {selected: selected(), hash: location.hash, focus: document.activeElement,
      addresses: addresses.length, writes};
    let prevented = 0;
    const event = document.fire('keydown', {key: 'j', target, ...props,
      preventDefault() { prevented++; this.defaultPrevented = true; }});
    assert.equal(prevented, 0, label + ' leaves browser/default handling alone');
    assert.equal(selected(), before.selected, label + ' keeps deck selection');
    assert.equal(location.hash, before.hash, label + ' keeps the address');
    assert.equal(addresses.length, before.addresses, label + ' writes no history');
    assert.equal(document.activeElement, before.focus, label + ' keeps focus');
    assert.equal(writes, before.writes, label + ' performs no data write');
    return event;
  }
"""


@unittest.skipUnless(workspace_ui.NODE, "Node.js isn't installed")
class LibraryKeyboardOwnershipTests(unittest.TestCase):
    def run_js(self, scenario):
        library_ui._Shelf.run_js(self, LIBRARY_KEYS + scenario)

    def test_real_more_menu_and_modal_own_j_and_k_without_focus_or_selection_leak(self):
        self.run_js(r"""
          mountLibrary();
          const more = main.querySelector('.page-head').querySelector('.menu-button');
          assert(more, 'use the Library actual More trigger');
          more.click();
          const menu = document.getElementById(more.getAttribute('aria-controls'));
          const item = menu.querySelector('[role=menuitem]');
          assert(!menu.hidden); assert.equal(document.activeElement, item);
          for (const key of ['j', 'k']) {
            blockedLibrary({key}, item, 'actual More item ' + key);
            blockedLibrary({key}, document.body, 'open More with body target ' + key);
          }
          assert(!menu.hidden); assert.equal(more.getAttribute('aria-expanded'), 'true');
          closeMenus(); main.focus();
          const before = selected();
          const accepted = document.fire('keydown', {key: 'j', target: main});
          assert(accepted.defaultPrevented); assert.notEqual(selected(), before);

          const dialog = el('dialog', {open: true}); dialog.open = true;
          const control = el('button', {text: 'Modal action'}); dialog.append(control);
          document.body.append(dialog); control.focus();
          for (const key of ['j', 'k']) {
            blockedLibrary({key}, control, 'current modal control ' + key);
            blockedLibrary({key}, document.body, 'modal fallback body target ' + key);
          }
          dialog.open = false; dialog.removeAttribute('open'); dialog.remove(); main.focus();
          const after = document.fire('keydown', {key: 'k', target: main});
          assert(after.defaultPrevented); assert.equal(writes, 0);
        """)

    def test_avatar_shaped_popover_owns_letters_and_preserves_native_theme_controls(self):
        self.run_js(r"""
          mountLibrary();
          const anchor=el('button',{'aria-controls':'fixture-avatar-menu','aria-expanded':'false'});
          const theme=el('div',{role:'group'}),auto=el('button',{text:'Auto'}),light=el('button',{text:'Light'});
          let choices=0;auto.addEventListener('click',()=>choices++);theme.append(auto,light);
          const menu=el('div',{class:'menu avatar-menu',id:'fixture-avatar-menu',hidden:true},theme,
            el('button',{text:'Switch person'}),el('a',{href:'#/settings',text:'Settings',hidden:true}));
          document.body.append(anchor,menu);wireMenu(anchor,menu);anchor.click();
          assert.equal(menu.getAttribute('role'),null,'the real avatar is a popover with a native theme group');
          assert.equal(document.activeElement,auto,'first eligible native button remains the opening focus');
          assert(keyboardMenuOpen());blockedLibrary({key:'j'},auto,'avatar theme control');
          blockedLibrary({key:'k'},document.body,'avatar with body fallback target');
          const arrow=menu.fire('keydown',{key:'ArrowDown',target:auto});
          assert(!arrow.defaultPrevented);assert.equal(document.activeElement,auto,'no new theme-group arrow binding');
          auto.click();assert.equal(choices,1);assert(!menu.hidden,'native theme action keeps popover open');
          const escape=menu.fire('keydown',{key:'Escape',target:auto});assert(escape.defaultPrevented);
          assert(menu.hidden);assert.equal(document.activeElement,anchor);assert(!keyboardMenuOpen());
          const accepted=document.fire('keydown',{key:'j',target:main});assert(accepted.defaultPrevented);assert.equal(writes,0);
        """)

    def test_native_editors_and_editable_descendants_keep_j_and_k(self):
        self.run_js(r"""
          mountLibrary();
          const controls = ['input', 'textarea', 'select'].map(tag => el(tag));
          const editable = el('div', {contenteditable: 'true'}, el('span', {text: 'Editable child'}));
          const inherited = editable.querySelector('span');
          const effective = el('span', {text: 'Native effective editable'}); effective.isContentEditable = true;
          main.append(...controls, editable, effective);
          for (const target of [...controls, editable, inherited, effective]) {
            target.focus();
            for (const key of ['j', 'k']) blockedLibrary({key}, target, target.tag + ' editor ' + key);
          }
          // A native input still owns keys inside a contenteditable=false island.
          const island = el('div', {contenteditable: 'false'}, el('input'));
          editable.append(island); const input = island.querySelector('input'); input.focus();
          blockedLibrary({}, input, 'input inside noneditable island');
          assert.equal(writes, 0);
        """)

    def test_composition_consumed_and_modified_keys_are_inert_but_repeat_navigation_works(self):
        self.run_js(r"""
          mountLibrary();
          const blockers = [{isComposing: true}, {keyCode: 229}, {defaultPrevented: true},
            {shiftKey: true}, {ctrlKey: true}, {altKey: true}, {metaKey: true}];
          for (const props of blockers) for (const key of ['j', 'k'])
            blockedLibrary({key, ...props}, main, JSON.stringify(props) + ' ' + key);
          const ids = rows().map(row => row.getAttribute('data-id'));
          for (const [key, expected, repeat] of [['j', ids[1], false], ['j', ids[2], true], ['k', ids[1], true]]) {
            const event = document.fire('keydown', {key, target: main, repeat});
            assert(event.defaultPrevented, 'unmodified repeated navigation is allowed');
            assert.equal(selected(), expected);
            assert.equal(document.activeElement.getAttribute('data-id'), expected);
          }
          assert.equal(writes, 0);
        """)

    def test_old_route_profile_detached_targets_and_results_cannot_retarget_library(self):
        self.run_js(r"""
          for (const mode of ['route', 'profile', 'target', 'results']) {
            const root = mountLibrary(), original = selected(root), currentHash = location.hash;
            let target = main;
            if (mode === 'route') routeToken++;
            if (mode === 'profile') state.profile = {...state.profile, id: 'different-fixture-profile'};
            if (mode === 'target') { target = el('button'); main.append(target); target.remove(); }
            if (mode === 'results') root.remove();
            blockedLibrary({key: 'j'}, target, mode + ' stale owner');
            assert.equal(selected(root), original, mode + ' never updates its old result tree');
            assert.equal(location.hash, currentHash);
          }
          // Replacing results leaves exactly one active listener: one J advances once.
          mountLibrary(); const old = main.querySelector('.results');
          mountLibrary(); assert(!old.isConnected);
          const ids = rows().map(row => row.getAttribute('data-id')), count = addresses.length;
          document.fire('keydown', {key: 'j', target: main});
          assert.equal(selected(), ids[1]); assert.equal(addresses.length, count + 1);
          assert.equal(writes, 0);
        """)


DECK_KEYS = r"""
  editor = null;
  let writes = 0;
  apiWrite = async () => { writes++; throw Error('unexpected data write'); };
  function mountDeck() {
    open('#/deck?id=casual%2Ftest&v=target');
    // Unrelated lazy panel rendering has its own suite; preserve actual selection,
    // focus, panel visibility and address behavior while avoiding background reads.
    for (const [name, host] of deckScreen.panels) {
      deckScreen.built.add(name);
      if (!host.children.length) host.append(el('p', {text: 'Fixture panel ' + name}));
    }
    tab('stats').click(); tab('stats').focus();
    return main.querySelector('[role=tablist]');
  }
  function blockedDeck(strip, props = {}, target = tab('stats'), label = 'owned key') {
    const before = {tab: deckScreen.view.tab, hash: location.hash, focus: document.activeElement,
      addresses: hashes.length, writes, selected: [...main.querySelectorAll('[role=tab]').map(node => node.getAttribute('aria-selected'))]};
    let prevented = 0;
    strip.fire('keydown', {key: 'ArrowRight', target, ...props,
      preventDefault() { prevented++; this.defaultPrevented = true; }});
    assert.equal(prevented, 0, label + ' leaves native handling alone');
    assert.equal(deckScreen.view.tab, before.tab, label + ' keeps the selected tab');
    assert.equal(location.hash, before.hash); assert.equal(hashes.length, before.addresses);
    assert.equal(document.activeElement, before.focus); assert.equal(writes, before.writes);
    same(main.querySelectorAll('[role=tab]').map(node => node.getAttribute('aria-selected')), before.selected);
  }
"""


@unittest.skipUnless(workspace_ui.NODE, "Node.js isn't installed")
class DeckTabKeyboardOwnershipTests(unittest.TestCase):
    def run_js(self, scenario):
        deck_ui.DeckPageUiTests.run_js(self, DECK_KEYS + scenario)

    def test_browser_navigation_modifiers_composition_and_consumed_tab_keys_are_inert(self):
        self.run_js(r"""
          const strip = mountDeck();
          for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
            for (const props of [{altKey: true}, {ctrlKey: true}, {metaKey: true}, {shiftKey: true},
              {isComposing: true}, {keyCode: 229}, {defaultPrevented: true}])
              blockedDeck(strip, {key, ...props}, tab('stats'), key + ' ' + JSON.stringify(props));
          }
          assert.equal(writes, 0);
        """)

    def test_focused_native_arrows_repeat_home_and_end_keep_selection_focus_and_address_together(self):
        self.run_js(r"""
          const strip = mountDeck();
          for (const [key, name, repeat] of [['ArrowRight', 'practice', false], ['ArrowRight', 'matchups', true],
            ['ArrowRight', 'overview', true], ['ArrowLeft', 'matchups', true], ['Home', 'overview', false], ['End', 'matchups', false]]) {
            const target = document.activeElement;
            assert.equal(target.getAttribute('role'), 'tab');
            const event = strip.fire('keydown', {key, target, repeat});
            assert(event.defaultPrevented); assert.equal(deckScreen.view.tab, name);
            assert.equal(document.activeElement, tab(name));
            assert.equal(tab(name).getAttribute('aria-selected'), 'true');
            assert.equal(panel(name).hidden, false);
            assert.equal(parseHash().params.get('tab'), name === 'overview' ? null : name);
          }
          assert.equal(writes, 0);
        """)

    def test_only_the_focused_current_native_tab_can_activate_and_detached_strip_is_inert(self):
        self.run_js(r"""
          const strip = mountDeck(), stats = tab('stats');
          strip.focus(); blockedDeck(strip, {}, strip, 'tablist itself');
          const outside = el('button', {text: 'Outside tablist'}); main.append(outside); outside.focus();
          blockedDeck(strip, {}, stats, 'tab target without actual tab focus');
          blockedDeck(strip, {}, outside, 'outside native control');
          const oldStrip = strip, oldTab = stats;
          mountDeck(); assert(!oldStrip.isConnected); assert(!oldTab.isConnected);
          // The fixture permits detached focus: the ownership guard must still refuse it.
          oldTab.focus(); blockedDeck(oldStrip, {}, oldTab, 'detached previous strip');
          assert.equal(writes, 0);
        """)

    def test_modal_and_actual_deck_more_menu_precede_even_a_focused_tab(self):
        self.run_js(r"""
          const strip = mountDeck();
          const more = main.querySelector('.deck-page-head').querySelector('.menu-button'); more.click();
          const menu = document.getElementById(more.getAttribute('aria-controls'));
          assert(!menu.hidden); tab('stats').focus();
          blockedDeck(strip, {}, tab('stats'), 'open deck More');
          closeMenus(); tab('stats').focus();
          const dialog = el('dialog', {open: true}); dialog.open = true;
          const control = el('button', {text: 'Modal action'}); dialog.append(control); document.body.append(dialog); control.focus();
          tab('stats').focus(); // Exercise the modal boundary independently of the focus guard.
          blockedDeck(strip, {}, tab('stats'), 'newer modal');
          dialog.open = false; dialog.removeAttribute('open'); dialog.remove(); tab('stats').focus();
          const event = strip.fire('keydown', {key: 'ArrowLeft', target: tab('stats')});
          assert(event.defaultPrevented); assert.equal(deckScreen.view.tab, 'cards'); assert.equal(writes, 0);
        """)


VIEWER_KEYS = r"""
  editor = null; clear(main);
  main.append(el('p', {text: 'Underlying page stays unchanged'}));
  const ownerProfile = {id: 'viewer-fixture'}; state.profile = ownerProfile;
  let writes = 0;
  apiWrite = async () => { writes++; throw Error('unexpected data write'); };
  viewerDom = buildViewer();
  viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open', '');
  viewerState = {items: [{card: alpha}, {card: beta}, {card: {...alpha, name: 'Gamma'}}], index: 1,
    face: 0, trigger: main, history: false, settling: false};
  const ownerViewer = viewerState, moves = [];
  stepViewer = direction => { moves.push(['step', direction]); };
  goViewer = index => { moves.push(['go', index]); };
  viewerDom.close.focus();
  const pageBefore = {text: main.textContent, hash: location.hash, token: routeToken, changes};
  function unchangedPage() {
    assert.equal(main.textContent, pageBefore.text); assert.equal(location.hash, pageBefore.hash);
    assert.equal(routeToken, pageBefore.token); assert.equal(changes, pageBefore.changes);
    assert.equal(state.profile, ownerProfile); assert.equal(viewerState, ownerViewer);
    assert.equal(viewerState.index, 1); assert.equal(viewerState.face, 0); assert.equal(writes, 0);
  }
  function blockedViewer(props = {}, target = viewerDom.close, viaDocument = false, label = 'owned key') {
    const before = moves.length, focus = document.activeElement;
    let prevented = 0;
    const owner = viaDocument ? document : viewerDom.dialog;
    owner.fire('keydown', {key: 'ArrowRight', target, ...props,
      preventDefault() { prevented++; this.defaultPrevented = true; }});
    assert.equal(prevented, 0, label + ' leaves native handling alone');
    assert.equal(moves.length, before, label + ' does not navigate');
    assert.equal(document.activeElement, focus, label + ' does not steal focus');
    unchangedPage();
  }
"""


@unittest.skipUnless(workspace_ui.NODE, "Node.js isn't installed")
class ViewerKeyboardOwnershipTests(unittest.TestCase):
    def run_js(self, scenario):
        workspace_ui.WorkspaceInteractionTests.run_js(self, VIEWER_KEYS + scenario)

    def test_native_text_select_and_editable_descendants_keep_navigation_keys(self):
        self.run_js(r"""
          const controls = ['input', 'textarea', 'select'].map(tag => el(tag));
          const editable = el('div', {contenteditable: 'true'}, el('span', {text: 'Editable descendant'}));
          viewerDom.dialog.append(...controls, editable);
          for (const target of [...controls, editable, editable.querySelector('span')]) {
            target.focus();
            for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End'])
              blockedViewer({key}, target, false, target.tag + ' editor ' + key);
          }
          // The real document fallback must preserve an editor outside the viewer too.
          const outside = el('input'); main.append(outside); outside.focus();
          const changedText = main.textContent; assert.equal(changedText, pageBefore.text);
          blockedViewer({key: 'Home'}, outside, true, 'outside input fallback');
        """)

    def test_composition_consumed_and_all_modified_navigation_keys_are_inert(self):
        self.run_js(r"""
          for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End'])
            for (const props of [{isComposing: true}, {keyCode: 229}, {defaultPrevented: true},
              {shiftKey: true}, {ctrlKey: true}, {altKey: true}, {metaKey: true}])
              blockedViewer({key, ...props}, viewerDom.close, false, key + ' ' + JSON.stringify(props));
          main.focus();
          blockedViewer({key: 'End', isComposing: true}, main, true, 'composing body fallback');
          blockedViewer({key: 'End', defaultPrevented: true}, main, true, 'consumed body fallback');
        """)

    def test_current_top_modal_and_both_real_menu_systems_own_keys_before_viewer(self):
        self.run_js(r"""
          const top = el('dialog', {open: true}); top.open = true;
          const control = el('button', {text: 'Top modal action'}); top.append(control); document.body.append(top); control.focus();
          blockedViewer({key: 'End'}, viewerDom.close, false, 'newer modal blocks old dialog event');
          blockedViewer({key: 'ArrowRight'}, control, true, 'newer modal document fallback');
          document.body.focus(); blockedViewer({key: 'Home'}, document.body, true, 'top modal body fallback');
          top.open = false; top.removeAttribute('open'); top.remove(); viewerDom.close.focus();

          const overflow = openMenu(viewerDom.close, [{text: 'Viewer fixture action', onclick: () => { throw Error('unexpected action'); }}]);
          const overflowItem = overflow.node.querySelector('[role=menuitem]');
          assert.equal(document.activeElement, overflowItem);
          blockedViewer({key: 'Home'}, overflowItem, true, 'body-mounted shared overflow');
          blockedViewer({key: 'ArrowRight'}, viewerDom.close, false, 'overflow also blocks viewer controls');
          overflow.close(); viewerDom.close.focus();

          const holder = menuButton('More fixture actions', [{label: 'Fixture item', onclick: () => { throw Error('unexpected action'); }}]);
          viewerDom.dialog.append(holder); const more = holder.querySelector('.menu-button'); more.click();
          const popover = document.getElementById(more.getAttribute('aria-controls'));
          assert(!popover.hidden);
          blockedViewer({key: 'End'}, popover.querySelector('[role=menuitem]'), false, 'core More popover');
          closeMenus(); viewerDom.close.focus();
          const event = viewerDom.dialog.fire('keydown', {key: 'ArrowRight', target: viewerDom.close});
          assert(event.defaultPrevented); same(moves, [['step', 1]]); unchangedPage();
        """)

    def test_plain_repeated_navigation_reading_pane_and_body_fallback_still_work(self):
        self.run_js(r"""
          for (const [key, repeat] of [['ArrowRight', false], ['ArrowRight', true], ['ArrowLeft', true], ['Home', false], ['End', true]]) {
            const event = viewerDom.dialog.fire('keydown', {key, target: viewerDom.close, repeat});
            assert(event.defaultPrevented);
          }
          same(moves, [['step', 1], ['step', 1], ['step', -1], ['go', 0], ['go', 2]]);
          // Reading-pane navigation remains the existing policy; it is not an editor.
          const paragraph = el('p', {text: 'Read-only card rules'}); viewerDom.text.append(paragraph); viewerDom.text.focus();
          const reading = viewerDom.dialog.fire('keydown', {key: 'Home', target: paragraph});
          assert(reading.defaultPrevented); same(moves.at(-1), ['go', 0]);
          main.focus(); const fallback = document.fire('keydown', {key: 'ArrowLeft', target: main, repeat: true});
          assert(fallback.defaultPrevented); same(moves.at(-1), ['step', -1]); unchangedPage();
        """)

    def test_closed_detached_viewer_and_detached_event_targets_are_inert(self):
        self.run_js(r"""
          const detached = el('button'); viewerDom.dialog.append(detached); detached.remove();
          blockedViewer({}, detached, false, 'detached old trigger');
          viewerDom.dialog.open = false; viewerDom.dialog.removeAttribute('open');
          blockedViewer({}, viewerDom.close, false, 'closed viewer');
          viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open', ''); viewerDom.dialog.remove();
          blockedViewer({}, viewerDom.close, false, 'detached viewer');
          main.focus(); blockedViewer({key: 'End'}, main, true, 'detached viewer fallback');
        """)


if __name__ == '__main__':
    unittest.main()
