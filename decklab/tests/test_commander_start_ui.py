"""A new Commander deck started from a commander (E9-S28's New deck from it: editor-import.js's
startFromCommander, #/new?kind=commander&commander=<name>), over the real editor scripts with invented cards.
The commander goes in as one change titled with its name; a new-deck draft already holding cards is kept;
an unknown name adds nothing."""
import unittest

from decklab.tests import test_editor_keyboard_ui as keyboard, test_editor_panes_ui as panes
from decklab.tests.test_workspace_ui import NODE

SETUP = r'''
  const ghaltaCard = {name: 'Ghalta, Primal Hunger', mana_cost: '{10}{G}{G}', type_line: 'Legendary Creature — Elder Dinosaur',
    cmc: 12, color_identity: ['G'], img_small: null, default: {set: 'rix', number: '130', finish: 'nonfoil'}};
  const searched = [];
  api = async (path) => { if (!path.startsWith('/api/cards/')) return {}; searched.push(path); return {names: ['Ghalta, Primal Hunger'], did_you_mean: [], cards: [ghaltaCard]}; };
  const toasts = []; toast = (words) => toasts.push(words);
'''


@unittest.skipUnless(NODE, 'Node.js is not installed')
class CommanderStartTests(unittest.TestCase):
    def run_js(self, scenario):
        panes.EditorPanesUiTests.run_js(self, keyboard.FIXTURE + SETUP + scenario)

    def test_the_commander_goes_in_as_one_change(self):
        self.run_js(r'''
          location.hash = '#/new?kind=commander&commander=Ghalta%2C+Primal+Hunger';
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          const ed = editor, before = ed.history.length;
          assert.equal(await startFromCommander('Ghalta, Primal Hunger'), true);
          same(searched, ['/api/cards/search?q=Ghalta%2C%20Primal%20Hunger&limit=20&detail=1']);
          same(ed.lists.Commander.map((l) => [l.qty, l.name, l.set, l.number]), [[1, 'Ghalta, Primal Hunger', 'rix', '130']]);
          assert.equal(ed.fields.title, 'Ghalta, Primal Hunger');
          assert.equal(ed.fields.kind, 'commander');
          assert.equal(ed.addSection, 'Deck');
          assert.equal(ed.history.length, before + 1);
          assert(ed.dirty);
        ''')

    def test_a_draft_with_cards_is_kept_and_an_unknown_name_adds_nothing(self):
        self.run_js(r'''
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          let ed = editor;
          ed.lists.Deck = [newLine({qty: 1, name: elves.name, card: elves})];
          assert.equal(await startFromCommander('Ghalta, Primal Hunger'), false);
          same(searched, []);
          assert(!ed.lists.Commander || !ed.lists.Commander.length);
          assert(toasts.some((t) => t.includes("Ghalta, Primal Hunger wasn't added")), toasts.join('|'));
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          ed = editor;
          assert.equal(await startFromCommander('Nobody At All'), false);
          assert(!ed.lists.Commander || !ed.lists.Commander.length);
          assert(toasts.some((t) => t.includes("Nobody At All isn't a card Deck Lab knows")), toasts.join('|'));
        ''')

    def test_tonight_preview_locks_retries_then_applies_as_one_edit(self):
        self.run_js(r'''
          state.may = {create: [{space:'home'}]};
          location.hash = '#/new?kind=commander';
          const params = new URLSearchParams({commander:ghaltaCard.name, partner:'Partner'});
          startEditor({mode:'new', kind:'commander', restoreDraft:false, tonight:params});
          const ed = editor;
          const answers = [], requests = [];
          apiWrite = (path, body) => {requests.push([path, body]); return new Promise(resolve=>answers.push(resolve));};
          const data = {names:[ghaltaCard.name,'Partner'], commanders:[{name:ghaltaCard.name,card:ghaltaCard},{name:'Partner',card:ghaltaCard}],
            target:98,picked:2,open_slots:96,open_lands:38,open_spells:58,
            picks:[{name:elves.name,quantity:1,reason:'Locked theme card',card:elves},{name:'Forest',quantity:1,reason:'Assumed plain basic supply'}],
            roles:[{label:'Ramp',count:1,target:10}],mana_sources:[{colour:'G',count:1}],incoming:[{name:'Arrival',quantity:1}]};
          const sheet = openTonightDraft(params), locks = sheet.body.querySelector('textarea'), buttons = sheet.foot.querySelectorAll('button');
          assert.equal(requests.length,1); locks.value=elves.name; locks.fire('input'); buttons[1].click();
          same(requests[1],['/api/commanders/draft',{space:'home',name:ghaltaCard.name,partner:'Partner',locked:[elves.name]}]);
          answers[0](data); await Promise.resolve(); assert(buttons[2].hidden);
          answers[1](data); await Promise.resolve(); assert(!buttons[2].hidden);
          assert(sheet.body.textContent.includes('Locked theme card')); assert(sheet.body.textContent.includes('Arrival'));
          const status = sheet.body.querySelector('[role="status"]');
          assert(status.textContent.includes('96 open slots')); assert(!status.textContent.includes(elves.name));
          assert.equal(ed.history.length,0); buttons[2].click(); assert(sheet.closed);
          assert.equal(ed.history.length,1); same(ed.lists.Commander.map(r=>r.name),data.names);
          same(ed.lists.Deck.map(r=>r.name).sort(),['Forest',elves.name].sort());
          assert.equal(openTonightDraft(params),null); undoLast(); assert.equal(ed.fields.title,'');
          assert(!Object.values(ed.lists).flat().length); assert.equal(requests.length,2);
          const reopen=ed.dom.page.querySelectorAll('button').find(b=>b.textContent==='Review collection draft');
          reopen.click(); same(requests[2],requests[1]);
        ''')

    def test_tonight_preview_keeps_title_only_drafts_and_drops_late_answers(self):
        self.run_js(r'''
          state.may = {create: [{space:'home'}]}; location.hash = '#/new?kind=commander';
          startEditor({mode:'new',kind:'commander',restoreDraft:false});
          const params = new URLSearchParams({commander:ghaltaCard.name}), ed=editor;
          setField('title','My deck'); assert.equal(openTonightDraft(params),null);
          assert.equal(ed.fields.title,'My deck');
          startEditor({mode:'new',kind:'commander',restoreDraft:false});
          let finish; apiWrite=()=>new Promise(resolve=>{finish=resolve;});
          const sheet=openTonightDraft(params);
          state.profile={id:'user1'}; finish({}); await Promise.resolve();
          assert(sheet.foot.querySelectorAll('button')[2].hidden);
          assert.equal(editor.history.length,0);
        ''')

    def test_find_from_blank_commander_editor_then_preview_and_undo_preserves_title(self):
        self.run_js(r'''
          state.may = {create: [{space:'home'}], see_inventory: ['home']};
          location.hash = '#/new?kind=commander';
          startEditor({mode:'new', kind:'commander', restoreDraft:false});
          const ed = editor, requests = [];
          setField('title', 'My Commander idea');
          const lead = {name:ghaltaCard.name, faces:[{name:ghaltaCard.name,card:ghaltaCard,free:1}],
            categories:[], of:40, covered:0, cards:1, lands:0};
          api = async path => {
            requests.push(path);
            if (path.includes('/candidate?')) return {categories:[]};
            return {total: path.includes('q=') ? 1 : 52, candidates: path.includes('q=') ? [lead] : []};
          };
          apiWrite = async (path, body) => {
            same(body, {space:'home', name:ghaltaCard.name, locked:[]});
            return {commanders:lead.faces, target:99, picked:1, open_slots:98, open_lands:38, open_spells:60,
              roles:[], mana_sources:[], incoming:[], picks:[{quantity:1,name:elves.name,card:elves,reason:'Provides ramp'}]};
          };
          const namedButton = (host, label) => host.querySelectorAll('button').find(b => b.textContent === label);
          const start = () => {
            namedButton(ed.dom.page, 'Build from my cards').click();
            const choice = [...colSheets].at(-1);
            assert(namedButton(choice.body, 'Find precons I can build'));
            namedButton(choice.body, 'Find commanders').click();
          };
          const before = ed.history.length;
          start(); await Promise.resolve();
          let sheet = [...colSheets].at(-1);
          sheet.body.querySelector('input').value = 'ghalta';
          sheet.body.querySelector('form').fire('submit'); await Promise.resolve();
          assert(requests.includes('/api/commanders/candidates?q=ghalta'));
          sheet.body.querySelector('.pcov-pick').click(); await Promise.resolve();
          namedButton(sheet.body, 'Build from cards free tonight').click(); await Promise.resolve();
          sheet = [...colSheets].at(-1);
          assert(sheet.body.textContent.includes('98 open slots') && sheet.body.textContent.includes('Provides ramp'));
          namedButton(sheet.foot, 'Use this draft').click();
          assert.equal(ed.history.length, before+1);
          assert.equal(ed.fields.title, 'My Commander idea');
          same(ed.lists.Commander.map(c=>c.name), [ghaltaCard.name]);
          same(ed.lists.Deck.map(c=>c.name), [elves.name]);
          undoLast(); assert(!Object.values(ed.lists).flat().length);
          assert.equal(ed.fields.title, 'My Commander idea');
          start(); await Promise.resolve(); sheet = [...colSheets].at(-1);
          colCloseSheets(); assert(sheet.closed); assert(!sheet.dialog.isConnected);
        ''')

    def test_a_pair_goes_in_together_as_one_change(self):
        # E9-S28's third slice: #/new?kind=commander&commander=<one>&partner=<other>.
        self.run_js(r'''
          const tymnaCard = {name: 'Tymna the Weaver', mana_cost: '{1}{W}{B}', type_line: 'Legendary Creature — Human Cleric',
            cmc: 3, color_identity: ['W', 'B'], img_small: null, default: {set: 'c16', number: '48', finish: 'nonfoil'}};
          api = async (path) => { if (!path.startsWith('/api/cards/search')) return {}; searched.push(path);
            return {cards: [path.includes('Tymna') ? tymnaCard : ghaltaCard]}; };
          startEditor({mode: 'new', kind: 'commander', restoreDraft: false});
          const ed = editor, before = ed.history.length;
          assert.equal(await startFromCommander('Ghalta, Primal Hunger', 'Tymna the Weaver'), true);
          assert.equal(searched.length, 2);
          same(ed.lists.Commander.map((l) => l.name).sort(), ['Ghalta, Primal Hunger', 'Tymna the Weaver']);
          assert.equal(ed.fields.title, 'Ghalta and Tymna the Weaver');
          assert.equal(ed.addSection, 'Deck');
          assert.equal(ed.history.length, before + 1);
          // A draft already holding both is left as it is.
          assert.equal(await startFromCommander('Ghalta, Primal Hunger', 'Tymna the Weaver'), false);
          assert.equal(ed.lists.Commander.length, 2);
        ''')

    def test_new_deck_has_one_import_review_and_contextual_precon_choices(self):
        self.run_js(r'''
          state.may = {create: [{space:'home'}], see_inventory: ['home']};
          location.hash = '#/new';
          startEditor({mode:'new', kind:'casual', restoreDraft:false});
          const path = editor.dom.page, part = path.querySelector('.edit-start');
          const namedButton = (host, label) => host.querySelectorAll('button').find(b => b.textContent === label);
          const paths = [];
          api = async path => { paths.push(path); return {decks: []}; };
          assert(namedButton(part, 'Start empty'));
          namedButton(part, 'Import a list').click();
          const importDialog = [...document.querySelectorAll('dialog[open]')].at(-1);
          assert.equal(importDialog.querySelector('h2').textContent, 'Import a list');
          assert(importDialog.querySelector('textarea'));
          assert(namedButton(importDialog, 'Import a deck link…'));
          importDialog.querySelector('.sheet-close').click();
          const other = part.querySelector('details');
          assert(namedButton(other, 'Use a published precon list'));
          assert(namedButton(other, 'Try a precon'));
          const owned = other.querySelector('a');
          assert.equal(owned.textContent, 'I own this precon');
          assert.equal(owned.getAttribute('href'), '#/collection?open=precon');
          namedButton(part, 'Build from my cards').click();
          const choice = [...colSheets].at(-1);
          assert(!namedButton(choice.body, 'Find commanders'));
          namedButton(choice.body, 'Find precons I can build').click();
          assert(paths.includes('/api/precons/coverage?'));
          assert.equal(editor.history.length, 0);
        ''')


if __name__ == '__main__':
    unittest.main()
