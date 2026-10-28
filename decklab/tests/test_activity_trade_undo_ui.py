"""A trade's whole-change Undo on Activity (E7-S22): both sides reviewed, one reason, no selection."""
import unittest

from decklab.tests import test_activity_mixed_undo_ui as mixed
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class ActivityTradeUndoUiTests(unittest.TestCase):
    def run_js(self, scenario):
        mixed.ActivityMixedUndoUiTests.run_js(self, r'''
          const tradePreview=(extra={})=>mixedPreview({action:'trade_undo',label:'Trade: gave 2 cards, got 3 cards',uploads:[],cards:3,
            collection:{removed:[collectionRow({name:'Sol Ring',set:'ecc',collector_number:'57',quantity:1})],
                        reduced:[{current:collectionRow({set:'m19',collector_number:'314',quantity:3}),restored:collectionRow({set:'m19',collector_number:'314',quantity:1})}]},
            returned:{added:[collectionRow({name:'Elvish Mystic',set:'cmm',collector_number:'648',quantity:1,notes:'Reign <i>precon</i>'})],
                      raised:[{current:collectionRow({quantity:1}),restored:collectionRow({quantity:2})}]},
            returned_cards:2,...extra});
          const tradeSaved=(p,extra={})=>mixedSaved(p,{returned_rows:p.returned.added.length+p.returned.raised.length,
            returned_cards:p.returned_cards,...extra});
        ''' + scenario)

    def test_trade_review_lists_both_sides(self):
        self.run_js(r'''
          const {sheet,asked}=await openMixed(tradePreview()),text=sheet.body.textContent;
          same(asked,['/api/activity/mixed-undo?id=42']);
          for(const words of ['Trade: gave 2 cards, got 3 cards','reverses this trade','takes the 3 copies that came in','puts back the 2 copies that left',
            'Cards that left, coming back','Elvish Mystic (CMM 648, nonfoil) × 1','Collection rows going back to more copies','1 → 2',
            'Cards that came in, to remove','Sol Ring (ECC 57, nonfoil) × 1','Collection rows going back to fewer copies','3 → 1',
            'Reign <i>precon</i>','Why undo this trade?','no partial selection'])assert(text.includes(words),words);
          assert(!text.includes('Upload kept'));assert.equal(sheet.body.querySelector('i'),null);assert(save(sheet).disabled);
        ''')

    def test_trade_save_checks_both_sides_of_the_answer(self):
        self.run_js(r'''
          const {sheet,p}=await openMixed(tradePreview());const sent=[];apiWrite=async(path,body)=>{sent.push([path,body]);return tradeSaved(p);};
          giveReason(sheet,'Traded the wrong card');save(sheet).click();await settle();
          same(sent,[['/api/activity/mixed-undo',{id:42,expect:'a'.repeat(64),reason:'Traded the wrong card'}]]);
          assert(sheet.body.textContent.includes('Undo saved as a new change.'));
          for(const extra of [{returned_rows:1},{returned_cards:1},{returned_rows:undefined}]){
            const {sheet,p}=await openMixed(tradePreview());apiWrite=async()=>tradeSaved(p,extra);giveReason(sheet);save(sheet).click();await settle();
            assert(button(sheet.dialog,'Reload Activity'),JSON.stringify(extra));assert(!sheet.body.textContent.includes('Undo saved'));
          }
        ''')

    def test_malformed_trade_previews_never_offer_save(self):
        self.run_js(r'''
          const bad=[{returned:{added:[],raised:[]}},{returned:{added:[]}},{returned_cards:0},{uploads:['x.csv']},
            {returned:{added:[],raised:[{current:collectionRow({quantity:2}),restored:collectionRow({quantity:2})}]}},
            {tokens:{removed:[tokenRow()],reduced:[]}},{products:[{product:'x',status:'ordered',intact:'no'}]}];
          for(const extra of bad){const {sheet}=await openMixed(tradePreview(extra));assert(!save(sheet),JSON.stringify(extra));}
          const {sheet}=await openMixed(mixedPreview({returned:{added:[],raised:[]}}));assert(!save(sheet),'an import with trade keys');
          const {returned,returned_cards,...plain}=tradePreview();const second=await openMixed(plain);assert(!save(second.sheet),'a trade without its keys');
        ''')


if __name__ == "__main__":
    unittest.main()
