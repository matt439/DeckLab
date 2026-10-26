"""Quick edit's details, write-up and paste use the shared editor model.

Runs real page scripts with the existing DOM double and frozen cards, without a
server or household data. These are interaction regressions, not device checks.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


SETUP = r"""
  clear(main);
  const saved = {};
  window.localStorage = {getItem: key => saved[key] ?? null,
    setItem: (key, value) => { saved[key] = String(value); },
    removeItem: key => { delete saved[key]; }};
  state.profiles = [{id:'matt',name:'Matt',space:'home',plays_as:'user',role:'admin'},
    {id:'user1',name:'User1',space:'home',plays_as:'wife',role:'member'},
    {id:'other',name:'Other',space:'other',role:'member'}];
  state.profile = state.profiles[1];
  state.may = {home_player:'wife',see_accessories:true,accessories:true,see_inventory:['home']};
  window.matchMedia('(min-width: 600px)').matches = false;
  scheduleCheck = () => {};
  const elves = {name:'Llanowar Elves',type_line:'Creature',cmc:1,color_identity:['G'],mana_cost:'{G}',
    oracle_text:'',img:null,img_small:null};
  const forest = {name:'Forest',type_line:'Basic Land',cmc:0,color_identity:['G'],mana_cost:'',
    oracle_text:'',img:null,img_small:null};
  const bolt = {name:'Lightning Bolt',type_line:'Instant',cmc:1,color_identity:['R'],mana_cost:'{R}',
    oracle_text:'',img:null,img_small:null};
  const list = {Deck:[{qty:4,name:elves.name,set:'fdn',number:'227',card:elves},
    {qty:56,name:forest.name,card:forest}],Sideboard:[{qty:1,name:bolt.name,card:bolt}]};
  function view(extra = {}) {
    return {id:'casual/sample',space:'home',kind:'casual',title:'Sample',sha256:'a'.repeat(64),
      sections:['Deck','Sideboard'],editable:true,may_save:true,changed_on:'2026-10-05',
      fields:{status:'built',player:'wife',archetype:'Elves',built_version:'target',sleeves:null,deck_box:null},
      field_text:{},prose:{notes:'### Game plan\n\nMake elves.',substitutes:'Existing substitutes.'},
      lists:{target:structuredClone(list),owned:structuredClone(list)},
      accessories:{sleeves:[{id:'green',label:'Green sleeves',quantity:100,used_by:[]}],
        deck_box:[{id:'box',label:'Deck box',quantity:1,capacity:100,used_by:[]}]},...extra};
  }
  function begin(extra = {}, opts = {}) {
    startEditor({mode:'edit',view:view(extra),version:'target',...opts});
    assert.equal(editor.quick, true);
    return editor;
  }
  const button = (root, label) => {
    const found = root.querySelectorAll('button').find(node => node.textContent === label);
    assert(found, `Missing button: ${label}`); return found;
  };
  function input(id, value) {
    const area = document.getElementById(id); assert(area, `Missing field: ${id}`);
    area.value = value; area.fire('input'); return area;
  }
  const settle = async () => { await Promise.resolve(); await Promise.resolve(); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class QuickEditorUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True,
                                                  {"innerWidth": 393, "innerHeight": 852, "coarse": True,
                                                   "visual": {"width": 393, "height": 852}}]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_details_edit_the_same_fields_and_preserve_member_choices(self):
        self.run_js(r"""
          begin();
          assert(main.querySelector('.edit-details-quick'));
          assert(document.getElementById('f-status'));
          const details = main.querySelector('details');
          assert(details, 'Other details fold beneath the status');
          assert.equal(details.getAttribute('open'), null);
          input('f-archetype', 'Elves and ramp');
          const player = document.getElementById('f-player').parentNode;
          same(player.querySelectorAll('button').map(node => node.textContent), ['User1']);
          button(document.getElementById('f-built_version').parentNode, 'Play-now list').click();
          main.querySelector('[data-focus="field:sleeves:green"]').click();
          main.querySelector('[data-focus="field:deck_box:box"]').click();
          same(draftBody().fields, {archetype:'Elves and ramp',built_version:'owned',sleeves:'green',deck_box:'box'});
          assert.equal(draftBody().lists, undefined);
        """)

    def test_notes_substitutes_and_current_survive_tabs_and_draft_restore(self):
        self.run_js(r"""
          const original = view();
          begin();
          document.getElementById('edit-tab-notes').click();
          input('prose-notes', '### Game plan\n\nAttack early.');
          input('prose-substitutes', 'Use another elf.');
          button(main, 'Mark write-up as current').click();
          assert.equal(editor.markCurrent, true);
          document.getElementById('edit-tab-cards').click();
          document.getElementById('edit-tab-notes').click();
          assert.equal(document.getElementById('prose-notes').value, '### Game plan\n\nAttack early.');
          assert.equal(document.getElementById('prose-substitutes').value, 'Use another elf.');
          same(draftBody(), {id:'casual/sample',sha256:'a'.repeat(64),
            prose:{substitutes:'Use another elf.',notes:'### Game plan\n\nAttack early.'},mark_current:true});
          assert(saveDraft(editor));
          startEditor({mode:'edit',view:original,version:'target'});
          assert.equal(editor.notice.kind, 'draft');
          assert.equal(editor.prose.notes, '### Game plan\n\nAttack early.');
          assert.equal(editor.prose.substitutes, 'Use another elf.');
          assert.equal(editor.markCurrent, true);
          assert.equal(draftBody().lists, undefined);
          document.getElementById('edit-tab-notes').click();
          button(main.querySelector('.edit-marker'), 'Undo').click();
          assert.equal(draftBody().mark_current, undefined);
        """)

    def test_add_sheet_opens_one_paste_sheet_and_add_preview_preserves_other_work(self):
        self.run_js(r"""
          begin();
          input('f-archetype', 'Changed before pasting');
          const originalProse = {...editor.prose};
          const untouched = JSON.stringify(editor.view.lists.owned);
          const requests = [];
          apiWrite = async (path, body) => {
            requests.push([path,body]);
            return {sections:{Deck:[{qty:2,name:bolt.name,card:bolt}]},
              count:{lines:1,cards:2},unknown:[],errors:[],warnings:[]};
          };
          main.querySelector('.bar-add').click();
          assert.equal(document.querySelectorAll('dialog').length, 0);
          button(editor.dom.searchDock.root, 'Paste a list…').click();
          assert.equal(document.querySelectorAll('dialog').length, 1);
          assert(document.querySelector('dialog').textContent.includes('Check the list'));
          input('paste-text', '2 Lightning Bolt');
          button(document.querySelector('dialog'), 'Check the list').click(); await settle();
          same(requests, [['/api/decklist/parse',{text:'2 Lightning Bolt'}]]);
          const sheet = document.querySelector('dialog');
          button(sheet, 'Add to the list'); button(sheet, 'Replace the list');
          assert(sheet.querySelector('.paste-diff').textContent.includes('Added 2 Lightning Bolt'));
          button(sheet, 'Add 2 cards').click();
          assert.equal(document.querySelectorAll('dialog').length, 0);
          assert.equal(editor.lists.Deck.find(line => line.name === bolt.name).qty, 2);
          assert.equal(editor.lists.Deck.find(line => line.name === forest.name).qty, 56);
          assert.equal(editor.lists.Sideboard[0].qty, 1);
          assert.equal(editor.fields.archetype, 'Changed before pasting');
          same(editor.prose, originalProse); assert.equal(JSON.stringify(editor.view.lists.owned), untouched);
          assert.equal(draftBody().lists.owned, undefined);
        """)

    def test_replace_preview_removes_only_the_edited_list_and_cancel_changes_nothing(self):
        self.run_js(r"""
          begin();
          const before = listSignature(editor.lists);
          apiWrite = async () => ({sections:{Deck:[{qty:60,name:forest.name,card:forest}]},
            count:{lines:1,cards:60},unknown:[],errors:[],warnings:[]});
          main.querySelector('.bar-add').click();
          button(editor.dom.searchDock.root, 'Paste a list…').click();
          input('paste-text', '60 Forest');
          button(document.querySelector('dialog'), 'Check the list').click(); await settle();
          button(document.querySelector('dialog'), 'Cancel').click();
          assert.equal(listSignature(editor.lists), before);
          main.querySelector('.bar-add').click();
          button(editor.dom.searchDock.root, 'Paste a list…').click();
          input('paste-text', '60 Forest');
          button(document.querySelector('dialog'), 'Check the list').click(); await settle();
          const sheet = document.querySelector('dialog');
          button(sheet.querySelector('.segmented'), 'Replace the list').click();
          assert(sheet.querySelector('.paste-diff').textContent.includes('Removed 4 Llanowar Elves'));
          assert.equal(listSignature(editor.lists), before, 'Preview writes nothing');
          button(sheet.querySelector('.sheet-foot'), 'Replace the list').click();
          same(sendList(editor.lists), {Deck:[{qty:60,name:'Forest'}]});
          assert.equal(editor.view.lists.owned.Deck[0].name, 'Llanowar Elves');
          assert.equal(draftBody().fields, undefined);
        """)

    def test_paste_closes_nonmodal_dock_and_reuses_the_search_history_entry(self):
        self.run_js(r"""
          const closes = [];
          Node.prototype.showModal = function () { this.open = true; };
          Node.prototype.close = function () { this.open = false; closes.push(() => this.fire('close')); };
          let backed = 0;
          history.state = {pos:0};
          history.pushState = value => { history.state = value; };
          history.replaceState = value => { history.state = value; };
          history.back = () => { backed++; history.state = {pos:0}; };
          begin(); main.querySelector('.bar-add').click();
          const dock=editor.dom.searchDock,search=editor.ac,oldToken=history.state.sheet;
          assert.equal(sheetEntries.length,1);assert.equal(document.querySelectorAll('dialog').length,0);
          button(dock.root,'Paste a list…').click();
          assert(!dock.open&&dock.root.hidden&&search.dockSuspended);assert(search.wrap.isConnected);
          assert(document.getElementById('paste-text'));assert.equal(document.querySelectorAll('dialog').length,1);
          assert.equal(sheetEntries.length,1);assert.equal(history.state.pos,1);assert.notEqual(history.state.sheet,oldToken);
          flushTimers();assert.equal(backed,0,'Dock release cannot step off the Paste entry');
          button(document.querySelector('dialog'),'Cancel').click();closes.shift()();flushTimers();
          assert.equal(sheetEntries.length,0);assert.equal(backed,1);assert.equal(document.querySelectorAll('dialog').length,0);
          openAddSheet();assert.equal(editor.ac,search);
        """)

    def test_person_space_and_read_only_permissions_still_apply(self):
        self.run_js(r"""
          state.profile = state.profiles[2];
          state.may = {deck_spaces:['other'],see_accessories:false,accessories:false,see_inventory:['other']};
          begin({id:'other/casual/sample',space:'other',
            fields:{status:'built',archetype:'Elves',built_version:'target'}});
          assert(document.getElementById('f-archetype'));
          assert(document.getElementById('f-built_version'));
          assert.equal(document.getElementById('f-player'), null);
          assert.equal(main.querySelector('[data-kit="sleeves"]'), null);
          assert.equal(main.querySelector('[data-kit="deck_box"]'), null);
          assert(main.querySelector('.bar-save'));
          begin({may_save:false});
          assert.equal(editor.readOnly, true);
          assert.equal(main.querySelector('.bar-save'), null);
          document.getElementById('edit-tab-notes').click();
          input('prose-notes', 'Trying a change');
          let saves = 0; apiWrite = async () => { saves++; throw new Error('Read-only save'); };
          await saveNow(); assert.equal(saves, 0);
        """)

    def test_commander_bracket_and_unstarted_play_now_keep_shared_rules(self):
        self.run_js(r"""
          begin({kind:'commander',fields:{status:'idea',player:'wife',target_bracket:2}});
          assert(document.getElementById('f-target_bracket'));
          assert.equal(main.querySelector('[data-kit="sleeves"]'), null);
          const bracket = document.getElementById('f-target_bracket');
          bracket.value = '3'; bracket.fire('change');
          assert.equal(draftBody().fields.target_bracket, 3);
          begin({lists:{target:structuredClone(list),owned:null}}, {version:'owned'});
          assert.equal(noOwnedList(), true);
          assert.equal(main.querySelector('.bar-add'), null);
          document.getElementById('edit-tab-notes').click();
          input('prose-notes', 'A write-up without starting the list.');
          assert.equal(draftBody().lists, undefined);
        """)

    def test_reapplying_latest_keeps_notes_substitutes_and_current_selection(self):
        self.run_js(r"""
          begin();
          document.getElementById('edit-tab-notes').click();
          input('prose-notes', '### Game plan\n\nMy revised plan.');
          input('prose-substitutes', 'My revised substitutes.');
          button(main, 'Mark write-up as current').click();
          const latest = view({sha256:'b'.repeat(64),
            prose:{notes:'A plan saved elsewhere.',substitutes:'Existing substitutes.'}});
          const requests = [];
          api = async path => { requests.push(path); return latest; };
          await reapplyLatest(null, {message:'The deck changed after you opened it.'}, null);
          same(requests, ['/api/deck/edit?id=casual%2Fsample']);
          assert.equal(document.getElementById('prose-notes').value, '### Game plan\n\nMy revised plan.');
          assert.equal(document.getElementById('prose-substitutes').value, 'My revised substitutes.');
          assert.equal(editor.markCurrent, true);
          assert(editor.notice.notes.some(note => note.includes('Notes write-up changed') && note.includes('yours is kept')));
          same(draftBody(), {id:'casual/sample',sha256:'b'.repeat(64),
            prose:{substitutes:'My revised substitutes.',notes:'### Game plan\n\nMy revised plan.'},mark_current:true});
          assert.equal(editor.base.prose.notes, 'A plan saved elsewhere.');
        """)
