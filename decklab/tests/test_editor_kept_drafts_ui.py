"""The editor's drafts kept for later (E2-S16, editor-kept-drafts.js): two simulated devices of one
profile share one fake /api/deck/draft, so a draft kept on one is offered, resumed and discarded on the
other, and a stale revision asks before replacing; the Quick edit's ▾ offers Save draft for later too, and
a never-saved new deck keeps its draft per space (and deck it copies) at /api/deck/new-draft. The real
page scripts run under the workspace DOM double; nothing reaches a server.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_editor_kept_drafts_ui
"""
import unittest

from decklab.tests import test_editor_keyboard_ui as keyboard, test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE

SERVER = r'''
  const server={rev:0,draft:null,available:true,reads:[],posts:[]};
  const answer=()=>server.available?{available:true,id:'casual/sample',version:'target',deck_revision:4,
    revision:server.rev,draft:server.draft}:{available:false,id:'casual/sample',version:'target'};
  api=async path=>{
    if(!path.startsWith('/api/deck/draft?'))throw new ApiError(0,'network is disabled in this test');
    server.reads.push(path);return structuredClone(answer());
  };
  apiWrite=async(path,body)=>{
    assert.equal(path,'/api/deck/draft');server.posts.push(structuredClone(body));
    if(body.expect!==server.rev)throw new ApiError(409,'This draft was saved or discarded on another device');
    server.rev+=1;
    server.draft=body.draft?{saved_at:'2026-10-29T01:00:00+00:00',device:body.device,content:body.draft,
      started:{revision:4,current:body.draft.sha256==='a'.repeat(64)}}:null;
    return structuredClone(answer());
  };
  navigator.userAgent='Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)';
  const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
  const device=()=>{for(const key of Object.keys(saved))delete saved[key];editor=null;};
  const text=()=>main.textContent;
  function startQuick(extra={}) {
    window.matchMedia('(min-width: 600px)').matches=false;
    startEditor({mode:'edit',view:view(extra),version:'target'});assert(editor.quick);return editor;
  }
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class KeptDraftUiTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, keyboard.FIXTURE + SERVER + scenario)

    def test_kept_on_one_device_resumed_on_the_other_and_published_by_saving(self):
        self.run_js(r'''
          let ed=full();await flush();
          assert.equal(server.reads.length,1);assert(server.reads[0].includes('id=casual%2Fsample&version=target'));
          const {at,...kept}=ed.kept;same(kept,{revision:0,draft:null,deckRevision:4,ours:null,resumed:false});
          same(at.body,{id:'casual/sample',version:'target'});
          same(keptDraftMenu(ed),[]);                     // nothing to keep until something changes
          setQty(ed.lists.Deck[0].uid,6);
          const items=keptDraftMenu(ed);assert.equal(items.length,1);assert.equal(items[0].text,'Save draft for later');
          ed.dom.barParts.saveMore.click();assert(document.body.textContent.includes('Save draft for later'),'in the ▾ menu');
          await keepDraftForLater(ed);
          assert.equal(server.rev,1);same(server.posts[0].expect,0);assert.equal(server.posts[0].draft.lists.Deck[0].qty,6);
          assert.equal(server.posts[0].draft.v,1);assert.equal(ed.kept.ours,1);assert.equal(keptDraftBanner(ed),null);
          assert(local.get(draftKey(ed)),'this device keeps it too');

          device();ed=full();await flush();               // the other device, same profile
          assert(text().includes('A draft kept for later'));assert(text().includes('Kept on iPad at'));assert.equal(server.posts[0].device,'iPad');
          assert(text().includes('as it\'s saved now (revision 4)'));
          button(main,'Resume it').click();await flush();
          ed=editor;assert.equal(ed.lists.Deck[0].qty,6);assert(ed.dirty);
          same([ed.kept.ours,ed.kept.resumed,ed.kept.revision],[1,true,1]);
          assert(text().includes('You picked up the draft kept for later'));
          assert.equal(JSON.parse(local.get(draftKey(ed))).lists.Deck[0].qty,6);
          // Saving the deck publishes it: the resumed draft goes from every device.
          await discardKeptAfterSave(ed);
          same(server.posts.at(-1),{id:'casual/sample',version:'target',expect:1,draft:null});
          assert.equal(server.draft,null);assert.equal(server.rev,2);
        ''')

    def test_a_changed_deck_rebases_the_resumed_draft_and_says_where_it_started(self):
        self.run_js(r'''
          server.rev=3;server.draft={saved_at:'2026-10-29T01:00:00+00:00',device:'iPad',started:{revision:2,current:false},
            content:{...JSON.parse(JSON.stringify(draftRecord(full()))),sha256:'b'.repeat(64)}};
          server.draft.content.lists.Deck[0].qty=7;
          device();let ed=full();await flush();
          assert(text().includes('Kept on iPad'));assert(text().includes('started from revision 2 of the deck, which is at revision 4 now'));
          button(main,'Resume it').click();await flush();
          ed=editor;assert.equal(ed.notice.kind,'draft-changed');assert.equal(ed.lists.Deck[0].qty,7);assert.equal(ed.sha256,'a'.repeat(64));
        ''')

    def test_two_devices_never_silently_overwrite_each_others_draft(self):
        self.run_js(r'''
          let ed=full();await flush();setQty(ed.lists.Deck[0].uid,6);
          server.rev=5;server.draft={saved_at:'2026-10-29T02:00:00+00:00',device:'Windows PC',content:draftRecord(ed),
            started:{revision:4,current:true}};
          const asked=[];ask=async(title,paragraphs)=>{asked.push([title,...paragraphs]);return 'keep';};
          await keepDraftForLater(ed);
          assert.equal(server.posts.length,1);assert.equal(server.posts[0].expect,0);assert.equal(server.rev,5);
          assert.equal(asked[0][0],'Another draft was kept for later');assert(asked[0][1].includes('on Windows PC'));
          same([ed.kept.revision,ed.kept.ours],[5,null]);assert(text().includes('A draft kept for later'));
          ask=async()=>'replace';await keepDraftForLater(ed);
          same(server.posts.map(post=>post.expect),[0,5]);
          assert.equal(server.rev,6);assert.equal(ed.kept.ours,6);
        ''')

    def test_which_is_newer_and_discarding_it_everywhere(self):
        self.run_js(r'''
          server.rev=2;server.draft={saved_at:'2026-10-29T01:00:00+00:00',device:'iPad',started:{revision:4,current:true},
            content:draftRecord(full())};
          device();let ed=full();await flush();
          ed.notice={kind:'draft',saved:Date.parse('2026-10-29T03:00:00+00:00')};drawBanners();
          assert(text().includes('The unsaved changes on this device, from'));assert(text().includes('are newer'));
          ed.notice={kind:'draft',saved:Date.parse('2026-10-28T03:00:00+00:00')};drawBanners();
          assert(text().includes('It\'s newer than the unsaved changes on this device'));
          ask=async()=>'discard';await discardKeptDraft(ed);
          same(server.posts.at(-1),{id:'casual/sample',version:'target',expect:2,draft:null});
          same([ed.kept.revision,ed.kept.draft],[3,null]);assert(!text().includes('A draft kept for later'));
          // A later save that never resumed it leaves the other device's drafts alone.
          const posts=server.posts.length;await discardKeptAfterSave(ed);assert.equal(server.posts.length,posts);
        ''')

    def test_saving_the_deck_clears_the_resumed_draft_without_waiting_for_it(self):
        self.run_js(r'''
          server.rev=1;server.draft={saved_at:'2026-10-29T01:00:00+00:00',device:'iPad',started:{revision:4,current:true},
            content:{...draftRecord(full()),lists:{Deck:[{...draftRecord(full()).lists.Deck[0],qty:6}]}}};
          device();let ed=full();await flush();button(main,'Resume it').click();await flush();ed=editor;
          assert.equal(ed.kept.ours,1);
          const draftWrite=apiWrite,saves=[],sent=[];let release;
          apiWrite=async(path,body)=>{
            if(path==='/api/deck/save'){saves.push(body);return {id:ed.id,title:ed.title,changed:true,deck:view()};}
            sent.push(body);await new Promise(resolve=>release=resolve);return draftWrite(path,body);   // a slow discard
          };
          const reads=server.reads.length;
          await doSave(null,ed.dom.barParts.save);
          assert.equal(saves.length,1);assert(editor!==ed,'the saved deck is open again at once');
          same(sent,[{id:'casual/sample',version:'target',expect:1,draft:null}]);
          assert.equal(server.rev,1,'still being sent');assert(editor.kept.loading);
          assert.equal(server.reads.length,reads,'its kept draft is read only once the discard has settled');
          release();await flush();await flush();
          assert.equal(server.rev,2);assert.equal(server.draft,null);assert.equal(server.reads.length,reads+1);
          same([editor.kept.revision,editor.kept.draft],[2,null]);assert(!text().includes('kept for later'));

          // A refused discard never fails the save: the draft is offered again, to discard by hand.
          server.rev=3;server.draft={...server.draft||{},saved_at:'2026-10-29T01:00:00+00:00',device:'iPad',
            started:{revision:4,current:true},content:draftRecord(editor)};
          device();ed=full();await flush();button(main,'Resume it').click();await flush();ed=editor;
          apiWrite=async(path,body)=>{
            if(path==='/api/deck/save')return {id:ed.id,title:ed.title,changed:true,deck:view()};
            server.posts.push(body);throw new ApiError(503,'down');
          };
          await doSave(null,ed.dom.barParts.save);await flush();await flush();
          assert(editor!==ed);same(server.posts.at(-1),{id:'casual/sample',version:'target',expect:3,draft:null});
          assert(text().includes('A draft kept for later'));

          // A save with no kept draft of its own makes no draft write.
          device();ed=full();await flush();const posts=server.posts.length;
          await doSave(null,ed.dom.barParts.save);await flush();assert.equal(server.posts.length,posts);
        ''')

    def test_this_devices_draft_remembers_the_kept_one_after_the_editor_is_closed(self):
        self.run_js(r'''
          let ed=full();await flush();setQty(ed.lists.Deck[0].uid,6);await keepDraftForLater(ed);
          same(JSON.parse(local.get(draftKey(ed))).kept,{revision:1,resumed:false});
          assert.equal(server.posts[0].draft.kept,undefined,'the mark stays on this device');
          editor=null;startEditor({mode:'edit',view:view(),version:'target'});ed=editor;   // the tab reopened
          assert.equal(ed.notice.kind,'draft');same([ed.kept.loading,ed.kept.mark],[true,{revision:1,resumed:false}]);
          await flush();same([ed.kept.ours,ed.kept.revision],[1,1]);assert(!text().includes('A draft kept for later'));
          await discardKeptAfterSave(ed);same(server.posts.at(-1),{id:'casual/sample',version:'target',expect:1,draft:null});
          // Kept again elsewhere since: the mark no longer matches, so it's offered, and a save leaves it alone.
          server.rev=5;server.draft={saved_at:'2026-10-29T02:00:00+00:00',device:'Windows PC',started:{revision:4,current:true},
            content:draftRecord(ed)};
          editor=null;startEditor({mode:'edit',view:view(),version:'target'});ed=editor;await flush();
          assert.equal(ed.kept.ours,null);assert(text().includes('A draft kept for later'));
          assert.equal(discardKeptAfterSave(ed),null);
        ''')

    def test_a_renamed_deck_says_so_instead_of_another_draft(self):
        self.run_js(r'''
          let ed=full();await flush();setQty(ed.lists.Deck[0].uid,6);
          const asked=[];ask=async(title)=>{asked.push(title);return 'keep';};
          apiWrite=async()=>{throw new ApiError(409,'This deck was renamed. Reload its current page before making changes.',
            {canonical_id:'casual/renamed',conflict:{reason:'renamed',canonical_id:'casual/renamed'}});};
          await keepDraftForLater(ed);
          same(asked,[]);assert.equal(server.reads.length,1,'no reload of the kept draft');
          const sheet=document.querySelector('dialog');assert(sheet.textContent.includes('This deck has been renamed'));
          assert(local.get(draftKey(ed)),'the changes are kept on this device');
        ''')

    def test_without_the_migration_or_the_right_to_save_nothing_shows(self):
        self.run_js(r'''
          server.available=false;let ed=full();await flush();
          assert.equal(ed.kept,null);setQty(ed.lists.Deck[0].uid,6);same(keptDraftMenu(ed),[]);assert(!text().includes('kept for later'));
          device();server.available=true;const reads=server.reads.length;ed=full({may_save:false});await flush();
          assert.equal(server.reads.length,reads);assert.equal(ed.kept,null);
          device();api=async()=>{throw new ApiError(503,'down');};ed=full();await flush();assert.equal(ed.kept,null);
        ''')

    def test_the_quick_edit_has_save_draft_for_later_while_there_is_one_to_keep(self):
        self.run_js(r"""
          let ed=startQuick();await flush();
          const more=ed.dom.barParts.saveMore;assert(more,'the Quick edit has a ▾');assert(more.hidden,'nothing to keep yet');
          setQty(ed.lists.Deck[0].uid,6);drawBar();assert(!more.hidden);
          more.click();assert(document.body.textContent.includes('Save draft for later'));
          assert(!document.body.textContent.includes('Save & view deck'),'only the draft, as before');
          await keepDraftForLater(ed);
          assert.equal(server.rev,1);assert.equal(server.posts[0].draft.lists.Deck[0].qty,6);assert.equal(ed.kept.ours,1);

          device();ed=startQuick();await flush();             // another phone, the same profile
          assert(text().includes('A draft kept for later'));button(main,'Resume it').click();await flush();
          ed=editor;assert(ed.quick);assert.equal(ed.lists.Deck[0].qty,6);assert(!ed.dom.barParts.saveMore.hidden);

          // A server without the migration: the ▾ never shows, as before.
          device();server.available=false;ed=startQuick();await flush();
          setQty(ed.lists.Deck[0].uid,5);drawBar();assert(ed.dom.barParts.saveMore.hidden);
          // Read-only: no Save, so no ▾ at all.
          device();server.available=true;ed=startQuick({may_save:false});await flush();
          assert(!ed.dom.barParts.saveMore);
        """)

    def test_a_new_decks_draft_is_kept_per_space_resumed_elsewhere_and_published_by_creating_it(self):
        self.run_js(r"""
          const kept={},reads=[],posts=[];
          const where=body=>`${body.space}|${body.source||''}`;
          api=async path=>{
            if(path.startsWith('/api/deck/draft?'))return {available:true,id:'casual/sample',version:'target',revision:0,draft:null};
            if(!path.startsWith('/api/deck/new-draft?'))throw new ApiError(0,'network is disabled in this test');
            reads.push(path);const q=new URLSearchParams(path.split('?')[1]);
            const k=kept[`${q.get('space')}|${q.get('source')||''}`]||{revision:0,draft:null};
            return structuredClone({available:true,space:q.get('space'),source:q.get('source'),...k});
          };
          apiWrite=async(path,body)=>{
            if(path==='/api/decks')return {id:'casual/sample',title:'New Elves',created:true,deck:view()};
            assert.equal(path,'/api/deck/new-draft');posts.push(structuredClone(body));
            const k=kept[where(body)]||{revision:0,draft:null};
            if(body.expect!==k.revision)throw new ApiError(409,'This draft was saved or discarded on another device');
            kept[where(body)]={revision:k.revision+1,draft:body.draft?{saved_at:'2026-10-29T01:00:00+00:00',
              device:body.device,content:body.draft}:null};
            return structuredClone({available:true,space:body.space,source:body.source||null,...kept[where(body)]});
          };
          startEditor({mode:'new',kind:'casual',restoreDraft:false});let ed=editor;await flush();
          same(reads,['/api/deck/new-draft?space=home']);same(keptDraftMenu(ed),[]);
          ed.fields.title='New Elves';ed.lists.Deck=[{...structuredClone(list.Deck[0]),uid:'n1'}];changed();
          assert(ed.dirty);assert.equal(keptDraftMenu(ed).length,1);
          await keepDraftForLater(ed);
          same([posts[0].space,'source' in posts[0],posts[0].expect],['home',false,0]);
          assert.equal(posts[0].draft.fields.title,'New Elves');assert.equal(ed.kept.ours,1);

          device();startEditor({mode:'new',kind:'casual'});ed=editor;await flush();     // the other device
          assert(text().includes('A new deck kept for later'));assert(text().includes("It hasn't been created yet."));
          button(main,'Resume it').click();await flush();ed=editor;
          assert.equal(ed.mode,'new');assert.equal(ed.fields.title,'New Elves');assert.equal(ed.lists.Deck[0].qty,4);
          same([ed.kept.ours,ed.kept.resumed],[1,true]);assert(text().includes('Creating the deck publishes it'));

          // A copy of a deck is kept apart from one started from nothing.
          device();startEditor({mode:'new',view:view({new_deck:{kind:'casual',title:'Copied'}}),from:'casual/source',
            restoreDraft:false});await flush();
          assert.equal(reads.at(-1),'/api/deck/new-draft?space=home&source=casual%2Fsource');
          assert(!text().includes('kept for later'));

          // Creating the resumed deck clears it from every device.
          device();startEditor({mode:'new',kind:'casual'});await flush();button(main,'Resume it').click();await flush();
          ed=editor;await doSave(null,ed.dom.barParts.save);await flush();await flush();
          same(posts.at(-1),{space:'home',expect:1,draft:null});same(kept['home|'],{revision:2,draft:null});
          assert.equal(editor.mode,'edit');
        """)

    def test_a_new_decks_draft_follows_the_space_chosen(self):
        self.run_js(r"""
          const reads=[];
          api=async path=>{reads.push(path);return {available:true,space:'x',source:null,revision:0,draft:null};};
          state.may={...state.may,create:[{space:'home',player:'wife'},{space:'other',player:null}]};
          startEditor({mode:'new',kind:'casual',restoreDraft:false});await flush();
          assert.equal(reads.at(-1),'/api/deck/new-draft?space=home');
          main.querySelectorAll('button').find(node=>node.dataset&&node.dataset.space==='other').click();await flush();
          assert.equal(reads.at(-1),'/api/deck/new-draft?space=other');same(editor.kept.at.body,{space:'other'});
        """)


if __name__ == '__main__':
    unittest.main()
