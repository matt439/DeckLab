"""Check box's wide sheet and its "Which printing?" choices, over fixture APIs only."""
import unittest

from decklab.tests import test_box_check_ui as box_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class BoxCheckPrintingsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        box_ui.BoxCheckUiTests.run_js(self, r'''
          const option=(set,number,free,recorded=0,finish='nonfoil')=>({set,collector_number:number,finish,
            label:set.toUpperCase()+' '+number+(finish==='nonfoil'?'':' '+finish),set_name:'',free,recorded});
          const offers=extra=>({'Recorded Elf':{held:2,recorded:1,options:[option('fdn','227',2,1),option('m19','314',1)]},
            'Recorded commander':{held:1,recorded:0,options:[option('sld','1',1),option('sld','2',0)]},...extra});
          const openPrintings=async(printings=offers())=>openBox(contents(),boxMeta({printings}));
          const labelled=(sheet,label)=>[...sheet.body.querySelectorAll('input'),...sheet.body.querySelectorAll('select')].find(node=>node.getAttribute('aria-label')===label);
          const elfCount=(sheet,label)=>labelled(sheet,'Recorded Elf: copies of '+label+' in the box');
          const commander=sheet=>labelled(sheet,'Recorded commander: which printing is in the box');
          const pick=(node,value)=>{node.value=value;node.fire('input');node.fire('change');};
        ''' + scenario)

    def test_sheet_is_wide_and_only_offered_cards_get_a_picker(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();
          assert(sheet.dialog.getAttribute('class').includes('sheet-wide'));assert(sheet.dialog.classList.contains('box-check-sheet'));
          assert.equal(sheet.body.querySelectorAll('.box-check-printing').length,2);
          assert(commander(sheet));assert.equal(commander(sheet).value,'');
          assert.equal(elfCount(sheet,'FDN 227').value,'1');assert.equal(elfCount(sheet,'M19 314').value,'0');
          assert(sheet.body.textContent.includes('Which printing?'));assert(sheet.body.textContent.includes('Printings in box with the check date'));
          assert(sheet.body.textContent.includes('SLD 2 (all in other boxes)'));
        ''')

    def test_no_offers_or_malformed_offers_show_no_picker(self):
        self.run_js(r'''
          for(const printings of [null,{},[],{'Recorded Elf':{held:2,recorded:0,options:[option('fdn','227',2)]}},
              {'Recorded Elf':{held:2,recorded:5,options:[option('fdn','227',2),option('m19','314',1)]}},
              {'Recorded Elf':{held:2,recorded:0,options:[option('fdn','227',2),option('fdn','227',2)]}}]){
            const {sheet}=await openPrintings(printings);assert.equal(sheet.body.querySelectorAll('.box-check-printing').length,0,JSON.stringify(printings));
            assert(!sheet.body.textContent.includes('Which printing?'));
          }
        ''')

    def test_unchanged_choices_send_no_printings(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();reviewed(sheet);assert(!sheet.body.textContent.includes('Printings to record'));
          let body;apiWrite=async(path,payload)=>{body=payload;return boxAnswer();};dateButton(sheet).click();await settle();
          assert(!('printings' in body));assert(button(sheet.dialog,'Done'));
        ''')

    def test_changed_choices_are_reviewed_then_sent_with_the_date(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();pick(commander(sheet),'0');pick(elfCount(sheet,'FDN 227'),'1');pick(elfCount(sheet,'M19 314'),'1');
          reviewed(sheet);const text=sheet.body.textContent;
          assert(text.includes('Printings to record'));assert(text.includes('Recorded commander: SLD 1'));assert(text.includes('Recorded Elf: FDN 227, M19 314'));
          let body;apiWrite=async(path,payload)=>{body=payload;return boxAnswer({printings_changed:true});};dateButton(sheet).click();await settle();
          same(body.printings,{'Recorded commander':[{set:'sld',collector_number:'1',finish:'nonfoil',quantity:1}],
            'Recorded Elf':[{set:'fdn',collector_number:'227',finish:'nonfoil',quantity:1},{set:'m19',collector_number:'314',finish:'nonfoil',quantity:1}]});
          assert(button(sheet.dialog,'Done'));assert(sheet.body.textContent.includes('the printings chosen were saved'));
        ''')

    def test_clearing_a_recorded_choice_sends_an_empty_list(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();pick(elfCount(sheet,'FDN 227'),'0');reviewed(sheet);
          assert(sheet.body.textContent.includes('Recorded Elf: not recorded'));
          let body;apiWrite=async(path,payload)=>{body=payload;return boxAnswer({printings_changed:true});};dateButton(sheet).click();await settle();
          same(body.printings,{'Recorded Elf':[]});
        ''')

    def test_out_of_range_choices_block_review(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();allFound(sheet);assert(!reviewButton(sheet).disabled);
          pick(elfCount(sheet,'M19 314'),'2');assert(reviewButton(sheet).disabled);
          pick(elfCount(sheet,'M19 314'),'1');pick(elfCount(sheet,'FDN 227'),'2');assert(reviewButton(sheet).disabled);
          pick(elfCount(sheet,'FDN 227'),'1');assert(!reviewButton(sheet).disabled);
          pick(elfCount(sheet,'FDN 227'),'1.5');assert(reviewButton(sheet).disabled);
        ''')

    def test_receipt_must_agree_about_printings(self):
        self.run_js(r'''
          for(const [change,answer,ok] of [[true,{printings_changed:false,saved:true},false],[false,{printings_changed:true},false],
              [true,{printings_changed:'yes'},false],[true,{printings_changed:true,saved:true,checked_on:'2026-10-27'},true]]){
            const meta=boxMeta({printings:offers(),checked_on:'2026-10-27'}),current=await openBox(contents(),meta);
            if(change)pick(commander(current.sheet),'0');reviewed(current.sheet);
            apiWrite=async()=>boxAnswer(answer);dateButton(current.sheet).click();await settle();
            assert.equal(Boolean(button(current.sheet.dialog,'Done')),ok,JSON.stringify([change,answer]));
          }
        ''')

    def test_reviewed_choices_lock_until_back_to_counts(self):
        self.run_js(r'''
          const {sheet}=await openPrintings();reviewed(sheet);assert(commander(sheet).disabled);assert(elfCount(sheet,'FDN 227').disabled);
          button(sheet.dialog,'Back to counts').click();assert(!commander(sheet).disabled);
        ''')

    def test_a_recorded_single_copy_choice_is_what_the_guards_restore(self):
        self.run_js(r'''
          const {sheet}=await openPrintings(offers({'Recorded commander':{held:1,recorded:1,options:[option('sld','1',0,1),option('sld','2',1)]}}));
          const select=commander(sheet);assert.equal(select.value,'0');reviewed(sheet);
          select.value='';select.fire('change');assert.equal(select.value,'0');
          button(sheet.dialog,'Back to counts').click();pick(select,'');reviewButton(sheet).click();
          assert(sheet.body.textContent.includes('Recorded commander: not recorded'));
        ''')
