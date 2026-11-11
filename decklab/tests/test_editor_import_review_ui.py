"""Explicit tickable imports conserve printings/categories and remain in their original editor."""
import unittest

from decklab.tests import test_editor_ui as fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorImportReviewUiTests(unittest.TestCase):
    run_js = fixture.EditorPageTests.run_js

    def import_js(self, scenario):
        self.run_js("""
          location.hash = '#/edit?id=casual/gruul'; edit(); editor.space = 'home'; drawEditor();
          const ed = editor, tick = async () => {for (let n = 0; n < 8; n++) await null;};
          const writes = []; apiWrite = async (...args) => {writes.push(args); throw Error('No write');};
        """ + scenario)

    def test_commander_duplicates_off_identity_and_unknown_metadata_start_unchecked(self):
        self.import_js("""
          ed.kind = 'commander'; ed.lists.Commander = [newLine({qty: 1, name: 'Green commander', card: {color_identity: ['G']}})];
          const source = {Deck: [{qty: 1, name: 'Llanowar Elves', card: elves}, {qty: 1, name: 'Blue card', card: {color_identity: ['U']}},
            {qty: 1, name: 'Elvish Mystic', set: 'cmm', number: '648', finish: 'etched', category: 'Ramp', card: {color_identity: ['G']}},
            {qty: 1, name: 'Unknown card', card: null}]};
          const choices = editorImportChoices(ed, source);
          same(choices.rows.map(item => item.selected), [false, false, true, false]);
          assert(choices.rows[0].reason.includes('Already')); assert(choices.rows[1].reason.includes('Outside'));
          const selected = editorImportSections(choices); same(selected.Deck, [source.Deck[2]]);
          choices.rows[1].selected = true; assert.equal(editorImportSections(choices).Deck.length, 2);
          ed.lists.Commander[0].card.color_identity = ['RG'];
          assert.equal(editorImportChoices(ed, {Deck: [source.Deck[2]]}).rows[0].selected, false);
        """)

    def test_availability_is_read_only_name_level_facts_and_absent_marks_never_claim_zero_free(self):
        self.import_js("""
          const line = {qty: 3, name: 'Elvish Mystic', card: elves};
          const answer = {marks: true, availability: {rows: [{name: line.name, owned: 5, on_the_way: 1,
            in_use_elsewhere: [['one of the home decks', 3]], available: 2, missing: 1}]}};
          const marks = editorImportMarks(line, answer).textContent;
          assert(marks.includes('1 free')); assert(marks.includes('3 in use (one of the home decks)'));
          assert(marks.includes('1 on the way')); assert(marks.includes('1 to buy'));
          assert.equal(editorImportMarks(line, {marks: false}), null);
          const host = el('div'); main.append(host); const choices = editorImportChoices(ed, {Deck: [line]}, {marks: false});
          drawEditorImportChoices(host, choices, () => {});
          assert(host.textContent.includes("no availability is shown")); assert(!host.textContent.includes('0 free'));
          assert.equal(writes.length, 0);
        """)

    def test_picker_offers_only_same_space_other_decks_and_handoff_keeps_finish_and_category(self):
        self.import_js(r"""
          const reads = [], opened = []; openPaste = seed => opened.push(seed);
          api = async path => {reads.push(path); return path === '/api/decks' ? {decks: [
            {id: ed.id, space: 'home', kind: 'casual', title: 'Current'}, {id: 'casual/source', space: 'home', kind: 'casual', title: 'Own source'},
            {id: 'user2/casual/public', space: 'user2', kind: 'casual', title: 'Other space'},
            {id: 'product/precon', space: 'home', kind: 'product', title: 'Product'}]} : {id: 'casual/source', space: 'home', lists: {target: {
              Deck: [{qty: 2, name: 'Elvish Mystic', set: 'cmm', number: '648', finish: 'foil', category: 'Ramp'}]}}};};
          const sheet = openDeckImport(); await tick();
          const choices = sheet.body.querySelectorAll('.choice-item'); assert.equal(choices.length, 1); assert.equal(choices[0].textContent, 'Own source');
          choices[0].click(); await tick(); assert.equal(sheet.closed, true); assert.equal(opened.length, 1);
          assert.equal(opened[0].text, 'Deck\n2 Elvish Mystic (CMM) 648 *F* #Ramp\n'); assert.equal(opened[0].check, true);
          same(reads, ['/api/decks', '/api/deck/edit?id=casual%2Fsource']); assert.equal(writes.length, 0);
        """)

    def test_late_picker_reads_and_detached_or_changed_editor_callbacks_do_not_open_an_import(self):
        self.import_js("""
          let finish; const opened = []; openPaste = seed => opened.push(seed);
          api = () => new Promise(resolve => {finish = resolve;});
          const sheet = openDeckImport(); state.profile = {id: 'user1'};
          finish({decks: [{id: 'casual/source', space: 'home', kind: 'casual', title: 'Source'}]}); await tick();
          assert.equal(sheet.body.querySelectorAll('.choice-item').length, 0); sheet.close(); state.profile = {id: 'matt'};
          api = async () => ({decks: [{id: 'casual/source', space: 'home', kind: 'casual', title: 'Source'}]});
          const active = openDeckImport(); await tick(); const button = active.body.querySelector('.choice-item');
          let sourceAnswer; api = () => new Promise(resolve => {sourceAnswer = resolve;}); button.click();
          ed.lists.Deck[0].qty += 1; sourceAnswer({id: 'casual/source', space: 'home', lists: {target: {Deck: []}}}); await tick();
          assert.equal(opened.length, 0); assert.equal(writes.length, 0);
        """)

    def test_paste_has_tickable_commander_defaults_and_applies_only_choices_in_one_undo_without_save(self):
        self.import_js("""
          ed.kind = 'commander'; ed.lists.Commander = [newLine({qty: 1, name: 'Green commander', card: {...elves,name:'Green commander',color_identity: ['G']}})];
          ed.sections = ['Commander','Deck','Sideboard']; ed.snap = snapshot(ed);
          changed = options => {ed.dirty = isDirty(); if (!options || options.history !== false) recordHistory(ed);};
          const source = {Deck: [{qty: 1, name: 'Llanowar Elves', card: elves},
            {qty: 1, name: 'Blue card', card: {...bolt,name:'Blue card',color_identity: ['U']}},
            {qty: 1, name: 'Elvish Mystic', set: 'cmm', number: '648', finish: 'etched', category: 'Ramp', card: {...elves,name:'Elvish Mystic',color_identity: ['G']}}]};
          apiWrite = async (path, body) => {writes.push([path,body]); return {sections:source,unknown:[],errors:[],warnings:[],count:{cards:3,lines:3},marks:false};};
          const before = keepList(ed.lists), sheet = openPaste({text:'fixture',check:true}); await tick();
          same(writes, [['/api/decklist/parse',{text:'fixture',context:{id:'casual/gruul'}}]]);
          const checks = sheet.body.querySelectorAll('input'); same(checks.map(box=>box.checked),[false,false,true]);
          assert(sheet.body.textContent.includes('Outside the commander')); assert(sheet.body.textContent.includes('Already in this draft'));
          const add = sheet.foot.querySelectorAll('button').find(button=>button.textContent==='Add 1 card'); assert(add); add.click();
          assert.equal(ed.history.length,1); assert.equal(writes.length,1); assert.equal(sheet.closed,true);
          const added = ed.lists.Deck.find(line=>line.name==='Elvish Mystic');
          assert.equal(added.category,'Ramp'); assert.equal(added.finish,'etched'); assert.equal(added.number,'648');
          assert(!ed.lists.Deck.some(line=>line.name==='Blue card')); assert.equal(undoLast(),true); same(keepList(ed.lists),before);
        """)

    def test_paste_ignores_late_answers_for_changed_text_or_person_and_does_not_apply_detached_control(self):
        self.import_js("""
          let finish; apiWrite = (path,body)=>{writes.push([path,body]);return new Promise(resolve=>{finish=resolve;});};
          const answer={sections:{Deck:[{qty:1,name:'Elvish Mystic',card:elves}]},unknown:[],errors:[],warnings:[],count:{cards:1,lines:1},marks:false};
          const before=keepList(ed.lists), sheet=openPaste({text:'old text',check:true}), area=sheet.body.querySelector('textarea');
          area.value='new text';area.fire('input');finish(answer);await tick();
          assert.equal(sheet.body.querySelectorAll('.import-choice').length,0);same(keepList(ed.lists),before);
          apiWrite=async()=>answer;sheet.foot.querySelectorAll('button').find(button=>button.textContent==='Check the list').click();await tick();
          const apply=sheet.foot.querySelectorAll('button').find(button=>button.textContent==='Add 1 card');assert(apply);
          apply.remove();apply.click();same(keepList(ed.lists),before);sheet.close();
          apiWrite=(path,body)=>new Promise(resolve=>{finish=resolve;});
          const late=openPaste({text:'later',check:true});state.profile={id:'user1'};finish(answer);await tick();
          assert.equal(late.body.querySelectorAll('.import-choice').length,0);same(keepList(ed.lists),before);
        """)

    def test_source_picker_opens_normal_review_and_requires_explicit_add_after_reading_marks(self):
        self.import_js("""
          const source={id:'casual/source',space:'home',lists:{target:{Deck:[{qty:2,name:'Elvish Mystic',set:'cmm',number:'648',finish:'foil',category:'Ramp',card:elves}]}}};
          api=async path=>path==='/api/decks'?{decks:[{id:source.id,space:'home',kind:'casual',title:'Source'}]}:source;
          apiWrite=async(path,body)=>{writes.push([path,body]);return{sections:source.lists.target,unknown:[],errors:[],warnings:[],count:{cards:2,lines:1},marks:true,
            availability:{rows:[{name:'Elvish Mystic',owned:2,on_the_way:0,in_use_elsewhere:[],available:2,missing:0}]}};};
          changed=options=>{ed.dirty=isDirty();if(!options||options.history!==false)recordHistory(ed);};
          const picker=openDeckImport();await tick();picker.body.querySelector('.choice-item').click();await tick();
          const review=document.querySelectorAll('dialog[open]').at(-1);assert(review);assert(review.textContent.includes('2 free'));
          assert(!ed.lists.Deck.some(line=>line.name==='Elvish Mystic'));assert.equal(writes.length,1);
          assert(writes[0][1].text.includes('CMM) 648 *F* #Ramp'));
          review.querySelectorAll('button').find(button=>button.textContent==='Add 2 cards').click();
          assert.equal(ed.lists.Deck.find(line=>line.name==='Elvish Mystic').qty,2);assert.equal(ed.history.length,1);assert.equal(writes.length,1);
        """)

    def test_add_demand_consumes_current_stock_and_unchecked_rows_consume_nothing_while_replace_is_separate(self):
        self.import_js("""
          const source={Deck:[{qty:4,name:'Llanowar Elves',set:'fdn',number:'227',card:elves},
            {qty:4,name:'Llanowar Elves',set:'m19',number:'314',card:elves}]};
          const answer={sections:source,unknown:[],errors:[],warnings:[],count:{cards:8,lines:2},marks:true,
            availability:{rows:[{name:'Llanowar Elves',owned:8,on_the_way:0,in_use_elsewhere:[],available:8,missing:0}]}};
          apiWrite=async()=>answer;const sheet=openPaste({text:'fixture',check:true});await tick();
          const checks=sheet.body.querySelectorAll('input'),marks=()=>sheet.body.querySelectorAll('.import-availability').map(node=>node.textContent);
          same(marks(),['4 free','4 to buy']);
          checks[0].checked=false;checks[0].fire('change');assert.equal(marks()[1],'4 free');
          const replace=()=>sheet.body.querySelectorAll('button').find(button=>button.textContent==='Replace the list');
          replace().click();assert.equal(marks()[0],'Unticked; if added: 4 free');assert.equal(marks()[1],'4 free');
          checks[0].checked=true;checks[0].fire('change');same(marks(),['4 free','4 free']);
          sheet.body.querySelectorAll('button').find(button=>button.textContent==='Add to the list').click();same(marks(),['4 free','4 to buy']);
          answer.availability.rows[0].owned=4;answer.availability.rows[0].available=4;
          updateEditorImportMarks({rows:[],answer,base:new Map()},'add');
          const choices=editorImportChoices(ed,{Deck:[source.Deck[0]]},answer),host=el('div');main.append(host);
          drawEditorImportChoices(host,choices,()=>{});assert.equal(host.querySelector('.import-availability').textContent,'4 to buy');
        """)

    def test_readonly_transition_ignores_pending_result_but_initial_public_try_change_keeps_local_paste(self):
        self.import_js("""
          const answer={sections:{Deck:[{qty:1,name:'Elvish Mystic',card:{...elves,name:'Elvish Mystic'}}]},unknown:[],errors:[],warnings:[],count:{cards:1,lines:1},marks:false};
          let finish;apiWrite=()=>new Promise(resolve=>{finish=resolve;});const sheet=openPaste({text:'fixture',check:true});
          ed.readOnly=true;finish(answer);await tick();assert.equal(sheet.body.querySelectorAll('.import-choice').length,0);sheet.close();
          apiWrite=async()=>answer;changed=options=>{ed.dirty=isDirty();if(!options||options.history!==false)recordHistory(ed);};
          const trying=openPaste({text:'public local experiment',check:true});await tick();
          assert.equal(trying.body.querySelectorAll('.import-choice').length,1);
          trying.foot.querySelectorAll('button').find(button=>button.textContent==='Add 1 card').click();
          assert(ed.lists.Deck.some(line=>line.name==='Elvish Mystic'));assert.equal(ed.readOnly,true);assert.equal(ed.history.length,1);
        """)

    def test_commander_basic_lands_and_own_text_copy_exceptions_are_not_singleton_duplicates(self):
        self.import_js("""
          ed.kind='commander';ed.lists.Commander=[newLine({qty:1,name:'Green commander',card:{...elves,name:'Green commander'}})];
          const repeat={...elves,name:'Fixture repeat',oracle_text:'A deck can have any number of cards named Fixture repeat.'};
          const seven={...elves,name:'Fixture seven',oracle_text:'A deck can have up to seven cards named Fixture seven.'};
          ed.lists.Deck.push(newLine({qty:2,name:repeat.name,card:repeat}),newLine({qty:2,name:seven.name,card:seven}));
          const choices=editorImportChoices(ed,{Deck:[{qty:10,name:'Forest',card:forest},{qty:2,name:repeat.name,card:repeat},
            {qty:3,name:seven.name,card:seven},{qty:1,name:'Llanowar Elves',card:elves}]});
          same(choices.rows.map(row=>row.selected),[true,true,true,false]);
          seven.commander_copies=7;assert.equal(editorImportCopyLimit(seven),7);repeat.commander_copies=null;assert.equal(editorImportCopyLimit(repeat),Infinity);
        """)

    def test_existing_draft_consumes_incoming_copies_and_other_holders_limit_usable_incoming(self):
        self.import_js("""
          ed.lists.Deck[0].qty=5;
          const line={qty:2,name:'Llanowar Elves',card:elves},answer={marks:true,availability:{rows:[
            {name:line.name,owned:6,on_the_way:2,in_use_elsewhere:[],available:6,missing:0}]}};
          const choices=editorImportChoices(ed,{Deck:[line]},answer),host=el('div');main.append(host);
          drawEditorImportChoices(host,choices,()=>{});assert.equal(host.querySelector('.import-availability').textContent,'1 on the way · 1 to buy');
          line.qty=3;Object.assign(answer.availability.rows[0],{owned:4,on_the_way:3,in_use_elsewhere:[['one of the home decks',2]],available:2});
          updateEditorImportMarks(choices,'replace');const words=host.querySelector('.import-availability').textContent;
          assert(words.includes('2 on the way'));assert(words.includes('1 to buy'));assert(!words.includes('3 on the way'));
        """)
