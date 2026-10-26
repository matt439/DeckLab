"""In-place Editor quantities keep current captions on the original viewer entries."""
import re
import unittest

from decklab.tests import test_editor_ui as editor_ui
from decklab.tests import test_editor_unsaved_rows_ui as rows
from decklab.tests import test_quick_editor_ui as quick


REAL_OPEN = re.search(r'(?ms)^function openCard\(.*?^\}',
    (editor_ui.WEB / 'card-viewer.js').read_text(encoding='utf-8')).group(0)


@unittest.skipUnless(editor_ui.NODE, 'Node.js is not installed')
class EditorLineCaptionTests(unittest.TestCase):
    def run_js(self, scenario):
        editor_ui.EditorPageTests.run_js(self, rows.SETUP + '\nopenCard = ' + REAL_OPEN + ';\n' + scenario)

    def test_in_place_list_quick_picture_new_and_trial_counts_reach_actual_group_open(self):
        self.run_js(r'''
          let reads=0,writes=0,opened=null;api=async()=>{reads++;throw Error('unexpected read');};
          apiWrite=async()=>{writes++;throw Error('unexpected write');};
          openCardViewer=(items,index,options)=>{opened={items,index,options};return opened;};
          for(const kind of ['list','quick','visual','new','copy','trial']) {
            const ed=edit();ed.quick=kind==='quick';ed.look=kind==='visual'?'visual':'list';
            if(kind==='new'||kind==='copy') {ed.mode='new';ed.fields.kind='casual';ed.hasFileList=false;}
            if(kind==='copy')ed.from='product/illustrative';if(kind==='trial')ed.readOnly=true;
            mountRows(ed);const line=ed.lists.Deck[0],row=rowFor(ed,line),trigger=row.editorChange.trigger;
            const entry=viewerCards.get(trigger),card=entry.card,status=()=>[];entry.status=status;
            const group=trigger.getAttribute('data-viewer'),input=row.querySelector('.qty-input');
            opened=null;input.focus();row.querySelector('.step-plus').click();
            assert.equal(line.qty,5);assert.equal(entry.caption,lineCaption(line,'Deck'));
            assert.equal(opened,null,'quantity sync does not open or redraw the viewer');
            assert(viewerCards.get(trigger)===entry&&entry.card===card&&entry.status===status);
            assert(rowFor(ed,line)===row&&row.editorChange.trigger===trigger&&document.activeElement===input);
            assert.equal(trigger.getAttribute('data-viewer'),group);trigger.click();
            assert(opened&&opened.items[opened.index]===entry);assert(opened.options.trigger===trigger);
            assert.equal(opened.items[opened.index].caption,lineCaption(line,'Deck'));
            row.querySelector('.step-minus').click();assert.equal(entry.caption,lineCaption(line,'Deck'));
            assert.equal(entry.caption.startsWith('4 copies'),true);
          }
          assert.equal(reads,0);assert.equal(writes,0);
        ''')

    def test_same_name_printing_and_commander_sections_keep_independent_current_captions(self):
        self.run_js(r'''
          const ed=edit();ed.kind='commander';ed.sections=['Commander','Deck','Sideboard'];
          ed.lists=copyList({Commander:[{qty:1,name:elves.name,set:'fdn',number:'227',card:elves}],
            Deck:[{qty:4,name:elves.name,set:'fdn',number:'227',card:elves},
              {qty:2,name:elves.name,set:'m19',number:'314',finish:'foil',card:elves}],
            Sideboard:[{qty:3,name:elves.name,set:'fdn',number:'227',card:elves}]});mountRows(ed);
          const entries=new Map();for(const [section,lines] of Object.entries(ed.lists))for(const line of lines) {
            const trigger=rowFor(ed,line).editorChange.trigger;entries.set(line.uid,{entry:viewerCards.get(trigger),trigger,section});
          }
          const foil=ed.lists.Deck[1];setQty(foil.uid,7);
          const changedEntry=entries.get(foil.uid).entry;assert.equal(changedEntry.caption,lineCaption(foil,'Deck'));
          assert(changedEntry.caption.includes('7 copies')&&changedEntry.caption.includes('The 99')&&changedEntry.caption.includes('M19 314'));
          for(const [section,lines] of Object.entries(ed.lists))for(const line of lines) {
            const kept=entries.get(line.uid);assert(viewerCards.get(kept.trigger)===kept.entry);
            assert.equal(kept.entry.caption,lineCaption(line,section));
          }
          setQty(ed.lists.Commander[0].uid,2);
          assert.equal(entries.get(ed.lists.Commander[0].uid).entry.caption,lineCaption(ed.lists.Commander[0],'Commander'));
          assert.equal(entries.get(ed.lists.Sideboard[0].uid).entry.caption,lineCaption(ed.lists.Sideboard[0],'Sideboard'));
        ''')

    def test_search_quantity_updates_the_same_list_entry_without_requests_or_list_redraw(self):
        quick.QuickEditorUiTests.run_js(self, '\nchanged = ' + rows.REAL_CHANGED + r''';
          const ed=begin({}, {restoreDraft:false});let reads=0,writes=0;
          api=async()=>{reads++;throw Error('unexpected read');};apiWrite=async()=>{writes++;throw Error('unexpected write');};
          const line=ed.lists.Deck[0],row=ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`),trigger=row.editorChange.trigger;
          const entry=viewerCards.get(trigger),status=()=>[];entry.status=status;openAddSheet();
          const ac=ed.ac,card={...elves,default:{set:'fdn',number:'227',finish:'nonfoil'}};
          ac.input.value=elves.name;ac.query=elves.name;ac.items=[card];ac.active=0;ac.resultScope=editorSearchScope(ac);drawOptions(ac);
          const record=ac.list.querySelector('.ac-actions').searchQuantity;record.plus.focus();record.plus.click();
          assert.equal(line.qty,5);assert.equal(entry.caption,lineCaption(line,'Deck'));
          assert(ed.dom.lines.querySelector(`[data-uid="${line.uid}"]`)===row&&row.editorChange.trigger===trigger);
          assert(viewerCards.get(trigger)===entry&&entry.status===status&&entry.card===line.card);
          assert(document.activeElement===record.plus);assert.equal(reads,0);assert.equal(writes,0);
        ''')

    def test_merged_original_undo_refreshes_the_surviving_entry_in_place(self):
        self.run_js(r'''
          const ed=edit();mountRows(ed);const removed=ed.lists.Deck[0],saved=JSON.stringify(ed.base);
          removeLine(removed.uid);
          const surviving=addCard({...elves,default:{set:'fdn',number:'227',finish:'nonfoil'}},'Deck',2);
          const row=rowFor(ed,surviving),trigger=row.editorChange.trigger,entry=viewerCards.get(trigger);
          const input=row.querySelector('.qty-input'),status=()=>[];entry.status=status;input.focus();
          assert.equal(entry.caption,lineCaption(surviving,'Deck'));undoRemove(removed.uid);
          assert.equal(surviving.qty,6);assert.equal(ed.removed.length,0);
          assert(rowFor(ed,surviving)===row&&row.editorChange.trigger===trigger);
          assert(viewerCards.get(trigger)===entry&&entry.status===status&&entry.card===surviving.card);
          assert.equal(entry.caption,lineCaption(surviving,'Deck'));assert(document.activeElement===input);
          assert.equal(JSON.stringify(ed.base),saved);
        ''')

    def test_unknown_stale_wrong_section_group_trigger_card_and_view_cannot_refresh_entries(self):
        self.run_js(r'''
          const ed=edit();mountRows(ed);const line=ed.lists.Deck[0],row=rowFor(ed,line),p=row.editorChange,trigger=p.trigger;
          const entry=viewerCards.get(trigger),original=entry.caption,originalViewerCard=entry.card;
          syncEditorLineCaption({...line,qty:77});assert.equal(entry.caption,original);
          line.qty=8;p.section='Sideboard';syncEditorLineCaption(line);assert.equal(entry.caption,original);p.section='Deck';
          p.line={...line};syncEditorLineCaption(line);assert.equal(entry.caption,original);p.line=line;
          trigger.setAttribute('data-viewer','another-group');syncEditorLineCaption(line);assert.equal(entry.caption,original);
          trigger.setAttribute('data-viewer','editor');const other=rowFor(ed,ed.lists.Deck[1]).editorChange.trigger;
          p.trigger=other;syncEditorLineCaption(line);assert.equal(entry.caption,original);p.trigger=trigger;
          entry.card=bolt;syncEditorLineCaption(line);assert.equal(entry.caption,original);entry.card=originalViewerCard;
          state.profile={id:'another-person'};syncEditorLineCaption(line);assert.equal(entry.caption,original);state.profile={id:ed.profile};
          ed.lists.Deck.shift();syncEditorLineCaption(line);assert.equal(entry.caption,original);ed.lists.Deck.unshift(line);
          ed.dom.lines.remove();syncEditorLineCaption(line);assert.equal(entry.caption,original);main.append(ed.dom.lines);
          const replacement=edit();mountRows(replacement);syncEditorLineCaption(line);assert.equal(entry.caption,original);
          const raw={qty:2,name:'Invented Unindexed Fixture Card',card:null};replacement.lists=copyList({Deck:[raw]});
          drawLines();const unknown=replacement.lists.Deck[0],unknownTrigger=rowFor(replacement,unknown).editorChange.trigger;
          setQty(unknown.uid,3);assert.equal(viewerCards.get(unknownTrigger),undefined);
          assert.equal(unknownTrigger.getAttribute('data-viewer'),null);
        ''')
