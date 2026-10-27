"""Printings in box on the page (web/printings-in-box.js), over fixture data only."""
import unittest

from decklab.tests import test_accounts_ui as accounts
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class PrintingsInBoxUiTests(unittest.TestCase):
    def run_js(self, scenario):
        accounts.AccountsUiTests.run_js(self, r'''
          const settle=async()=>{for(let i=0;i<32;i++)await null;};
          const option=(set,number,free,recorded=0,finish='nonfoil')=>({set,collector_number:number,finish,
            label:`${set.toUpperCase()} ${number}${finish==='nonfoil'?'':' '+finish}`,free,recorded});
          const info=extra=>({recorded:[{name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',label:'FDN 227',quantity:2}],
            stale:[],expect:'a'.repeat(64),editable:true,
            cards:[{name:'Llanowar Elves',held:4,options:[option('fdn','227',2,2),option('m19','314',2)]}],...extra});
          const mount=(extra={})=>{clear(main);as('matt',MAY.admin);
            const data={summary:{id:'casual/a',space:'home',title:'A'},printings_in_box:info(extra)};
            const section=deckPrintingsSection(data);if(section)main.append(section);return {data,section};};
        ''' + scenario)

    def test_part_lists_the_record_and_marks_it_out_of_date(self):
        self.run_js(r'''
          const {section}=mount({stale:['2 Llanowar Elves (M19) 314: built decks record more M19 314 copies than the collection has']});
          assert(section.textContent.includes('Llanowar Elves'));assert(section.textContent.includes('FDN 227 ×2'));
          assert(section.textContent.includes('Printings in box out of date'));assert(button(section,'Printings in box…'));
          assert.equal(mount({editable:false}).section.querySelectorAll('button').length,0);
          assert(mount({recorded:[]}).section.textContent.includes('Not recorded yet'));
        ''')

    def test_sheet_saves_every_count_and_refuses_more_than_the_box_holds(self):
        self.run_js(r'''
          const {section}=mount();const calls=[];apiWrite=(path,body)=>{calls.push([path,body]);return new Promise(()=>{});};
          button(section,'Printings in box…').click();
          const sheet=openDialog();assert(sheet,'sheet');const inputs=[...sheet.querySelectorAll('input')];
          same(inputs.map(input=>input.value),['2','0']);
          inputs[1].value='3';button(sheet,'Save').click();assert.equal(calls.length,0);
          assert(sheet.textContent.includes('Choose 0 to 2'));
          inputs[1].value='2';button(sheet,'Save').click();
          same(calls,[['/api/deck/printings',{id:'casual/a',expect:'a'.repeat(64),cards:[
            {name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:2},
            {name:'Llanowar Elves',set:'m19',collector_number:'314',finish:'nonfoil',quantity:2}]}]]);
        ''')

    def test_finish_building_sends_only_offered_choices_of_decks_it_marks_built(self):
        self.run_js(r'''
          const offered={'Llanowar Elves':{options:[option('fdn','227',2)],only:option('fdn','227',2)}};
          const data={completion:{decks:[{id:'casual/a'}]},decks:[{id:'casual/a',printing_choices:offered},{id:'casual/b',printing_choices:offered}]};
          const view={boxPrintings:{'casual/a':{'Llanowar Elves':[{...option('fdn','227',2),quantity:2}],'Gone':[{...option('x','1',1),quantity:1}]},
            'casual/b':{'Llanowar Elves':[{...option('fdn','227',2),quantity:1}]}}};
          same(packPrintingsBody(view,data),{'casual/a':[{name:'Llanowar Elves',set:'fdn',collector_number:'227',finish:'nonfoil',quantity:2}]});
        ''')
