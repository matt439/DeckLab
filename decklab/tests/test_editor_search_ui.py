"""Native search actions and exact-owner asynchronous editor boundaries.

Runs the real scripts in the existing Node DOM fixture with invented cards.
No server, card download, database or household records are used.
"""
import unittest

from decklab.tests import test_workspace_ui as workspace_ui, test_quick_editor_ui as quick_ui


@unittest.skipUnless(workspace_ui.NODE, "Node.js isn't installed")
class EditorSearchUiTests(unittest.TestCase):
    def run_js(self, scenario):
        workspace_ui.WorkspaceInteractionTests().run_js(scenario)

    def run_quick(self, scenario):
        quick_ui.QuickEditorUiTests().run_js(scenario)

    def test_plain_list_native_siblings_and_current_action_descriptions(self):
        self.run_js(r"""
          results('a', [{...alpha,img_small:'/img/a/small',aud:0.25,free:2,oracle_text:'A fixture rule.'}, beta]);
          assert.equal(ac.list.tag, 'ul');
          assert.equal(ac.list.getAttribute('aria-label'), 'Cards found');
          for (const attr of ['role','aria-autocomplete','aria-expanded','aria-activedescendant'])
            assert.equal(ac.input.getAttribute(attr), null);
          assert.equal(ac.list.getAttribute('role'), null);
          assert.equal(ac.list.querySelectorAll('[role="option"]').length, 0);
          const row = ac.list.querySelector('.ac-option');
          const add = row.querySelector('.ac-add'), inspect = row.querySelector('.ac-thumb-btn');
          assert.equal(add.tag, 'button'); assert.equal(inspect.tag, 'button');
          assert.equal(add.parentNode.parentNode, row); assert.equal(inspect.parentNode, row);
          assert.equal(add.contains(inspect), false); assert.equal(inspect.contains(add), false);
          assert.equal(row.getAttribute('aria-current'), 'true');
          assert.equal(add.getAttribute('aria-label'), 'Add Alpha');
          for (const id of add.getAttribute('aria-describedby').split(' '))
            assert(document.getElementById(id), 'action metadata is described by connected nodes');
          assert(document.getElementById('ac-type-0').textContent.includes('A fixture rule.'));
          assert.equal(ac.list.querySelectorAll('.ac-add')[1].getAttribute('aria-current'), null);
          inspect.fire('click', {stopPropagation(){}}); assert.equal(inspections.length, 1); assert.equal(changes, 0);
          add.click(); assert.equal(changes, 1); assert.equal(editor.lists.Deck[0].qty, 1);
        """)
        css = (workspace_ui.WEB / 'editor.css').read_text(encoding='utf-8')
        self.assertIn('dialog.sheet-search .ac-option { grid-template-columns: 44px minmax(0, 1fr) auto; }', css,
                      'Quick search keeps native actions outside facts and its 44px Inspect target')

    def test_arrow_live_selection_preserves_added_confirmation_and_old_count_rules(self):
        self.run_js(r"""
          results('a'); ac.input.focus();
          ac.input.fire('keydown', {key:'ArrowUp'});
          assert.equal(ac.active, 1); assert.equal(document.activeElement, ac.input);
          assert.equal(ac.live.textContent, 'Result 2 of 2: Beta.');
          ac.input.fire('keydown', {key:'Enter',shiftKey:true});
          assert.equal(editor.lists.Deck[0].qty, 4);
          const confirmation = ac.live.textContent; assert(confirmation.includes('added, 4 copies'));
          drawOptions(ac); assert.equal(ac.live.textContent, confirmation);
          ac.input.value = '3 a'; ac.input.fire('keydown', {key:'Enter'});
          assert.equal(editor.lists.Deck[0].qty, 7);
          ac.input.fire('keydown', {key:'Enter',altKey:true});
          assert.equal(inspections.length, 1); assert.equal(changes, 2);
          assert.equal(inspections[0].trigger, ac.list.querySelectorAll('.ac-actions')[1].searchQuantity.qty);
        """)

    def test_native_add_keeps_default_printing_and_selected_section_matching(self):
        self.run_js(r"""
          const card = {...alpha,default:{set:'new',number:'7'}};
          editor.lists.Deck = [{uid:'old',name:'Alpha',qty:2,set:'old',number:'1',card},
            {uid:'new',name:'Alpha',qty:3,set:'new',number:'7',card}];
          editor.lists.Sideboard = [{uid:'side',name:'Alpha',qty:9,set:'new',number:'7',card}];
          results('Alpha', [card]); ac.input.fire('keydown', {key:'Enter'});
          same(editor.lists.Deck.map(line => line.qty), [2,4]);
          assert.equal(editor.lists.Sideboard[0].qty, 9);
          editor.addSection = 'Sideboard';
          ac.input.fire('keydown', {key:'Enter',shiftKey:true});
          same(editor.lists.Deck.map(line => line.qty), [2,4]);
          assert.equal(editor.lists.Sideboard[0].qty, 13);
        """)

    def test_added_expiry_retains_focused_actions_and_viewer_return_trigger(self):
        self.run_js(r"""
          results('Alpha', [{...alpha,img_small:'/img/a/small'}]);
          const row = ac.list.querySelector('.ac-option'), add = row.querySelector('.ac-add');
          const inspect = row.querySelector('.ac-thumb-btn');
          add.click(); const addedTimer = ac.addedTimer;
          inspect.focus(); inspect.fire('click', {stopPropagation(){}});
          viewerDom = buildViewer();
          viewerState = {trigger:inspect,history:false};
          viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open',''); viewerDom.close.focus();
          flushTimers();
          assert.equal(ac.addedAt, null); assert.equal(inspect.isConnected, true);
          assert.equal(ac.list.querySelector('.ac-option'), row);
          assert.equal(row.querySelector('.ac-add'), add);
          assert.equal(row.querySelector('.ac-thumb-btn'), inspect);
          assert.equal(document.activeElement, viewerDom.close);
          viewerDom.dialog.open = false; viewerDom.dialog.removeAttribute('open'); viewerClosed();
          assert.equal(document.activeElement, inspect); assert.equal(changes, 1);
          assert(addedTimer); assert.equal(ac.live.textContent.includes('added'), true);
          const qty=row.querySelector('.qty-input');qty.focus();drawOptions(ac);assert.equal(document.activeElement,qty);
        """)

    def test_more_retains_native_focus_and_viewer_return_then_appends(self):
        self.run_js(r"""
          results('a', [{...alpha,img_small:'/img/a/small'}]); ac.pages = 2;
          drawOptions(ac); const row = ac.list.querySelector('.ac-option');
          const inspect = row.querySelector('.ac-thumb-btn'), add = row.querySelector('.ac-add');
          let resolve, requests = 0;
          api = () => { requests++; return new Promise(done => { resolve=done; }); };
          ac.more.click(); ac.more.click(); assert.equal(requests, 1);
          assert.equal(ac.more.getAttribute('aria-disabled'), 'true');
          inspect.focus(); inspect.fire('click', {stopPropagation(){}});
          viewerDom = buildViewer(); viewerState = {trigger:inspect,history:false};
          viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open',''); viewerDom.close.focus();
          resolve({cards:[beta],pages:2}); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.items.length, 2); assert.equal(ac.active, 0);
          assert.equal(ac.list.querySelector('.ac-option'), row);
          assert.equal(row.querySelector('.ac-add'), add); assert.equal(inspect.isConnected, true);
          assert.equal(document.activeElement, viewerDom.close);
          assert.equal(ac.morePending, false); assert.equal(ac.more.getAttribute('aria-disabled'), null);
          viewerDom.dialog.open = false; viewerDom.dialog.removeAttribute('open'); viewerClosed();
          assert.equal(document.activeElement, inspect); assert.equal(changes, 0);
        """)

    def test_more_failure_retains_controls_and_retries_the_failed_page(self):
        self.run_js(r"""
          results('a', [{...alpha,img_small:'/img/a/small'}]); ac.pages = 3; drawOptions(ac);
          const row = ac.list.querySelector('.ac-option'), inspect = row.querySelector('.ac-thumb-btn');
          const pending = [], urls = [];
          api = url => { urls.push(url); return new Promise((resolve,reject) => pending.push({resolve,reject})); };
          ac.more.click(); inspect.focus(); inspect.fire('click', {stopPropagation(){}});
          viewerDom = buildViewer(); viewerState = {trigger:inspect,history:false};
          viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open',''); viewerDom.close.focus();
          pending[0].reject(new Error('invented unavailable page')); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.items.length, 1); assert.equal(ac.page, 1);
          assert.equal(ac.list.querySelector('.ac-option'), row); assert.equal(inspect.isConnected, true);
          assert.equal(ac.moreError.hidden, false); assert(ac.moreError.textContent.includes('invented unavailable page'));
          assert.equal(ac.more.textContent, 'Retry more'); assert.equal(ac.morePending, false);
          assert.equal(document.activeElement, viewerDom.close);
          viewerDom.dialog.open = false; viewerDom.dialog.removeAttribute('open'); viewerClosed();
          assert.equal(document.activeElement, inspect);
          ac.more.click(); assert.equal(urls.length, 2);
          assert.equal(new URLSearchParams(urls[0].split('?')[1]).get('page'), '2');
          assert.equal(urls[1], urls[0]);
          pending[1].resolve({cards:[beta],pages:3}); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.items.length, 2); assert.equal(ac.page, 2);
          assert.equal(ac.moreError.hidden, true); assert.equal(changes, 0);
        """)

    def test_final_more_response_returns_focus_only_from_its_own_button(self):
        self.run_js(r"""
          results('a', [alpha]); ac.pages = 2; drawOptions(ac);
          let resolve; api = () => new Promise(done => {resolve=done;});
          ac.more.focus(); ac.more.click();
          resolve({cards:[beta],pages:2}); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.more.hidden, true); assert.equal(document.activeElement, ac.input);
          assert.equal(ac.active, 0); assert.equal(changes, 0);
        """)

    def test_old_more_cannot_release_new_query_or_filter_request(self):
        self.run_js(r"""
          results('a', [alpha]); ac.pages = 3; drawOptions(ac);
          const pending = [], urls = [];
          api = url => { urls.push(url); return new Promise((resolve,reject) => pending.push({resolve,reject})); };
          ac.more.click(); assert.equal(ac.morePending, true);
          ac.input.value = 'be'; ac.input.fire('input');
          assert.equal(ac.morePending, false); assert.equal(ac.more.getAttribute('aria-disabled'), null);
          const query = lookUp(ac, 'be'); pending[1].resolve({cards:[beta],pages:3}); await query;
          ac.more.click(); assert.equal(ac.morePending, true);
          pending[0].resolve({cards:[alpha],pages:3}); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.morePending, true); assert.equal(ac.more.getAttribute('aria-disabled'), 'true');
          same(ac.items.map(card => card.name), ['Beta']);
          ac.colors.add('G'); refilter(ac);
          assert.equal(ac.morePending, false); assert.equal(ac.more.getAttribute('aria-disabled'), null);
          pending[2].reject(new Error('stale More error')); await Promise.resolve(); await Promise.resolve();
          assert.equal(ac.moreError.hidden, true); assert.equal(ac.items.length, 0);
          assert.equal(changes, 0);
        """)

    def test_result_actions_and_pending_enter_require_exact_owner_scope_and_attachment(self):
        self.run_js(r"""
          const pending = []; api = () => new Promise(resolve => pending.push(resolve));
          for (const field of ['id','version','space']) {
            ac.input.value='Alpha'; ac.input.fire('input');
            ac.input.fire('keydown',{key:'Enter'}); const original=editor[field]; editor[field]='changed';
            pending.at(-1)({cards:[alpha]}); await Promise.resolve(); await Promise.resolve();
            assert.equal(editor.lists.Deck.length, 0); editor[field]=original;
          }
          results('Alpha', [{...alpha,img_small:'/img/a/small'}]);
          const add=ac.list.querySelector('.ac-add'), inspect=ac.list.querySelector('.ac-thumb-btn');
          const originalToken=routeToken; routeToken++;
          add.click(); inspect.fire('click', {stopPropagation(){}}); assert.equal(changes,0); assert.equal(inspections.length,0);
          routeToken=originalToken; const originalProfile=state.profile; state.profile={id:'other'};
          add.click(); inspect.fire('click', {stopPropagation(){}}); assert.equal(changes,0); assert.equal(inspections.length,0);
          state.profile=originalProfile; ac.wrap.remove();
          add.click(); inspect.fire('click', {stopPropagation(){}}); assert.equal(changes,0); assert.equal(inspections.length,0);
        """)

    def test_quick_dismiss_cancels_early_enter_and_replacement_close_keeps_new_search(self):
        self.run_quick(r"""
          begin(); let sheet;
          const makeSheet=openSheet; openSheet=options => (sheet=makeSheet(options));
          openAddSheet(); const old=editor.ac, ed=editor, before=listSignature(ed.lists);
          const pending=[]; api=() => new Promise(resolve => pending.push(resolve));
          old.input.value=elves.name; old.input.fire('input'); old.input.fire('keydown',{key:'Enter',shiftKey:true});
          assert.equal(old.pickFirst,true); sheet.close();
          assert.equal(old.cancelled,true); assert.equal(old.pickFirst,false); assert.equal(ed.ac,null);
          pending[0]({cards:[elves]}); await settle();
          assert.equal(listSignature(ed.lists),before);
          openAddSheet(); const prior=editor.ac, priorSheet=sheet;
          const replacement=cardSearch(); sheet.body.append(replacement); const current=editor.ac;
          document.body.classList.add('is-searching'); priorSheet.close();
          assert.equal(editor.ac,current); assert.equal(current.cancelled,false);
          assert.equal(document.body.classList.contains('is-searching'),true);
          assert.equal(prior.cancelled,true);
        """)

    def test_close_editor_or_replacing_search_drops_late_exact_enter(self):
        self.run_quick(r"""
          const old=begin(); openAddSheet(); const oldAc=old.ac, before=listSignature(old.lists);
          const pending=[]; api=() => new Promise(resolve => pending.push(resolve));
          oldAc.input.value=elves.name; oldAc.input.fire('input'); oldAc.input.fire('keydown',{key:'Enter'});
          closeEditor();for(const dialog of document.querySelectorAll('dialog'))dialog.remove();
          const next=begin(); const nextBefore=listSignature(next.lists);
          pending[0]({cards:[elves]}); await settle();
          assert.equal(listSignature(old.lists),before); assert.equal(listSignature(next.lists),nextBefore);
          assert.equal(oldAc.cancelled,true);
          openAddSheet(); const first=next.ac;
          first.input.value=elves.name; first.input.fire('input'); first.input.fire('keydown',{key:'Enter'});
          main.append(cardSearch()); const replacement=next.ac;
          pending[1]({cards:[elves]}); await settle();
          assert.equal(first.cancelled,true); assert.equal(next.ac,replacement);
          assert.equal(listSignature(next.lists),nextBefore);
        """)

    def test_real_quick_search_mount_and_owned_browse_keep_existing_request_scope(self):
        self.run_quick(r"""
          begin(); openAddSheet(); const search=editor.ac;
          assert(search.wrap.isConnected); assert.equal(search.initializing,false);
          assert(search.input); assert.equal(search.list.hidden,true);
          const urls=[]; api=async url => {urls.push(url);return {cards:[elves],pages:1};};
          search.mode='collection'; search.colors.add('G'); search.type='creature'; search.mv='1';
          refilter(search); flushTimers(); await settle();
          const params=new URLSearchParams(urls[0].split('?')[1]);
          same([params.get('id'),params.get('scope'),params.get('colors'),params.get('type'),params.get('mv')],
            ['casual/sample','owned','G','creature','1']);
          assert.equal(search.items[0].name,elves.name);
          const before=editor.lists.Deck[0].qty; search.list.querySelector('.step-plus').click();
          assert.equal(editor.lists.Deck[0].qty,before+1);
        """)
