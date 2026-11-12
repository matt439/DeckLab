"""Where these go's To storage lines name each card's recorded storage location (E8-S27), on the
receipt's Arrival recorded page and the Collection page's filing advice, from the saved answer only.

Real UI scripts over deterministic fixture replies; nothing is fetched or written.
Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_where_these_go_locations_ui
"""
import json
import subprocess
import unittest

from decklab.tests import test_collection_filing_ui as filing_ui, test_receipts_ui as board


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptStorageLocationTests(unittest.TestCase):
    run_js = board.ReceiptBoardTests.run_js

    def test_each_to_storage_line_says_where_its_copies_are(self):
        self.run_js("""
          const d=delivery();d.components[0].rows=d.components[0].rows.slice(0,1);d.components[0].decks=[[]];
          const v=drawReceipt(d,routeToken);rcptTick(v,v.comps[0],v.comps[0].rows[0],true);const received=rcptReceived(v);
          const show=found=>add(el('div',{}),rcptWhereTheyGo(v,received,{},storageAdviceLocations(found)));
          let post=show({ready:true,cards:{Alpha:{places:['Row 2, B','Binder'],more:0}}});
          assert(post.textContent.includes('2 × Alpha · Usually in Row 2, B · Binder'),post.textContent);
          post=show({ready:true,cards:{Alpha:{places:['Row 1','Row 2','Row 3'],more:2}}});
          assert(post.textContent.includes('Usually in Row 1 · Row 2 · Row 3 and 2 more'),post.textContent);
          post=show({ready:true,cards:{Alpha:{places:[],more:0}}});
          assert(post.textContent.includes('2 × Alpha · No location recorded yet'),post.textContent);
          post=show({ready:false,cards:{}});
          assert(post.textContent.includes(STORAGE_LOCATIONS_OFF));assert(!post.textContent.includes('Usually in'));
          assert(!post.textContent.includes('No location recorded'));
          for(const bad of [null,undefined,{},{ready:true},{ready:true,cards:[]},
              {ready:true,cards:{Alpha:{places:['a','b','c','d'],more:0}}},{ready:true,cards:{Alpha:{places:[7],more:0}}},
              {ready:true,cards:{Alpha:{places:['x'.repeat(41)],more:0}}},{ready:true,cards:{Alpha:{places:['a'],more:-1}}},
              {ready:true,cards:{Alpha:{places:['a'],more:2}}}]){
            post=show(bad);assert(post.textContent.includes('To storage'));assert(post.textContent.includes('2 × Alpha'));
            assert(!/Usually in|No location recorded|aren't available/.test(post.textContent),JSON.stringify(bad));
          }
          // An older call without places still draws the lines (the pre-E8-S27 signature).
          post=add(el('div',{}),rcptWhereTheyGo(v,received));assert(post.textContent.includes('2 × Alpha'));
        """, draw=False)

    def test_deck_lines_never_get_place_words_and_the_arrival_page_uses_the_applys_answer(self):
        self.run_js("""
          tickAll(view);
          const answer={...ready,received:true,order:'test',assignments:[],remaining:[],fingerprint:'c'.repeat(64),readiness:{},
            storage_locations:{ready:true,cards:{Alpha:{places:['Row 4'],more:0},Beta:{places:[],more:0}}}};
          rcptSuccess(view,answer);
          const panels=[...main.querySelectorAll('.rcpt-where')];
          const storage=panels.find(p=>p.querySelector('h3').textContent==='To storage');
          assert(storage.textContent.includes('1 × Alpha · Usually in Row 4'),storage.textContent);
          assert(storage.textContent.includes('1 × Beta · No location recorded yet'),storage.textContent);
          const deck=panels.find(p=>p.querySelector('a')?.textContent==='Alpha Deck');
          assert(deck.textContent.includes('1 × Alpha'));assert(!deck.textContent.includes('Row 4'));
          answer.storage_locations.cards.Alpha.places[0]='Changed later';
          assert(!main.textContent.includes('Changed later'));
        """)


SETUP = filing_ui.SETUP + r"""
  const located = (found) => { const answer = reply(); if (found !== undefined) answer.filing.storage_locations = found; return answer; };
"""


@unittest.skipUnless(filing_ui.NODE, "Node.js isn't installed")
class FilingStorageLocationTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([filing_ui.NODE, str(filing_ui.RUNNER)],
                                input=json.dumps([str(filing_ui.WEB), SETUP + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_to_storage_lines_name_places_or_say_none_and_deck_lines_never_do(self):
        self.run_js(r"""
          const cv = view(), answer = located({ready: true, cards: {'Llanowar Elves': {places: ['Row 2, B'], more: 0},
            'Aerie Mystics': {places: [], more: 0}}});
          const data = colFilingSnapshot(answer, cv);
          answer.filing.storage_locations.cards['Llanowar Elves'].places[0] = 'Changed server object';
          cv.message.append(colFilingGuide(cv, data));
          const text = guide().textContent;
          assert(text.includes('1 × Llanowar Elves (FDN 227) · Usually in Row 2, B'), text);
          assert(text.includes('1 × Aerie Mystics (CON 1 · Foil) · No location recorded yet'), text);
          assert(!text.includes('Changed server object'));
          const deck = guide().querySelectorAll('.col-filing-panel').find(p => p.textContent.includes('Waiting Deck'));
          assert(deck.textContent.includes('2 × Llanowar Elves')); assert(!deck.textContent.includes('Row 2'));
          assert(!deck.textContent.includes('No location'));
        """)

    def test_unavailable_missing_or_malformed_locations(self):
        self.run_js(r"""
          let cv = view(); cv.message.append(colFilingGuide(cv, colFilingSnapshot(located({ready: false, cards: {}}), cv)));
          assert(guide().textContent.includes(STORAGE_LOCATIONS_OFF)); assert(!guide().textContent.includes('Usually in'));
          for (const found of [undefined, null, {ready: true, cards: {'Llanowar Elves': {places: ['a', 'b', 'c', 'd'], more: 0}}}]) {
            cv = view(); const data = colFilingSnapshot(located(found), cv);
            assert.equal(data.status, 'ready'); assert.equal(data.places, null);
            cv.message.append(colFilingGuide(cv, data)); const text = guide().textContent;
            assert(text.includes('To storage')); assert(text.includes('1 × Llanowar Elves (FDN 227)'));
            assert(!/Usually in|No location recorded|aren't available/.test(text), text);
          }
          cv = view(); const unknown = located({ready: true, cards: {'Llanowar Elves': {places: ['Row 2, B'], more: 0}}});
          unknown.filing.status = 'unknown'; unknown.filing.destinations = [];
          cv.message.append(colFilingGuide(cv, colFilingSnapshot(unknown, cv)));
          assert(!guide().textContent.includes('Row 2, B'));
        """)


if __name__ == "__main__":
    unittest.main()
