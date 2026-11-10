"""The quiet "Own another printing (FDN 227)" note (E2-S30) on the deck page's Cards tab, its card marks
and the price table, through the real scripts. No network, no writes."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

OWN = r"""
  const other = {own_printing: 'other', own_printing_label: 'M19 314', own_printing_more: 0, own_printing_on_the_way: false};
  const listed = {own_printing: 'listed', own_printing_label: 'FDN 3', own_printing_more: 0, own_printing_on_the_way: false};
  const withOwn = (fields) => { const page = makePage(); page.owned.rows[1] = {...page.owned.rows[1], ...fields}; return page; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class OwnPrintingUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + OWN + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_words(self):
        self.run_js(r"""
          assert.equal(ownPrintingWords(other), 'Own another printing (M19 314)');
          assert.equal(ownPrintingWords({...other, own_printing_more: 2}), 'Own another printing (M19 314 and 2 more)');
          assert.equal(ownPrintingWords({...other, own_printing_on_the_way: true}), 'Another printing on the way (M19 314)');
          assert.equal(ownPrintingWords(listed), 'Own the listed printing (FDN 3)');
          assert.equal(ownPrintingWords({...listed, own_printing_on_the_way: true}), 'Listed printing on the way (FDN 3)');
          assert.equal(ownPrintingWords(listed, false), null);      // the list itself notes only "another"
          assert.equal(ownPrintingWords(other, false), 'Own another printing (M19 314)');
          // No fields (no named printing, a recorded box printing, an older answer) or odd ones: nothing.
          for (const row of [null, {}, {own_printing: 'other'}, {own_printing: 'other', own_printing_label: 7},
                             {own_printing: 'free', own_printing_label: 'M19 314'}, {own_printing_label: ''}]) {
            assert.equal(ownPrintingWords(row), null);
          }
          for (const row of [other, listed, {...other, own_printing_on_the_way: true}]) {
            assert(!/free|missing|warn/i.test(ownPrintingWords(row)));
          }
        """)

    def test_card_marks_and_the_price_table_show_a_plain_note(self):
        self.run_js(r"""
          const page = withOwn(other);
          const marks = cardMarks(page);
          assert.equal(marks.get('Bolt').printing, 'Own another printing (M19 314)');
          assert.equal(marks.get('Elf').printing, null);
          const groups = deckGroups(page);
          const byLine = lineMarks(groups, marks);
          const boltLine = groups.flatMap((g) => g.lines).find((l) => l.name === 'Bolt');
          const chips = markChips(byLine.get(boltLine));
          const chip = chips.find((c) => c.textContent === 'Own another printing (M19 314)');
          assert(chip, chips.map((c) => c.textContent).join('|'));
          assert(!/crit|warn/.test(chip.className), chip.className);       // a note, never a warning
          // The note alone passes no Cards filter and counts no copy.
          const quiet = {missing: 0, need: 1, coming: 0, sources: [], held: [], printing: 'Own another printing (M19 314)'};
          for (const filter of ['missing', 'coming', 'held']) {
            assert.equal(markPasses(quiet, filter), false); assert.equal(markCopies(quiet, filter, {qty: 1}), 0);
          }
          // The listed printing owned: nothing on the list, the words in the viewer's full marks.
          const have = lineMarks(deckGroups(withOwn(listed)), cardMarks(withOwn(listed)));
          const haveLine = [...have.keys()].find((l) => l.name === 'Bolt');
          assert(!markChips(have.get(haveLine)).some((c) => c.textContent.includes('printing')));
          assert(markChips(have.get(haveLine), true).some((c) => c.textContent === 'Own the listed printing (FDN 3)'));
          // Without the fields the marks and chips are as before.
          assert(!markChips(lineMarks(deckGroups(makePage()), cardMarks(makePage())).values().next().value)
            .some((c) => c.textContent.includes('printing')));
          // The price table's row labels.
          clear(main); state.cards = new Map([['Elf', elf], ['Bolt', bolt]]);
          const section = ownedSection(page); main.append(section);
          const body = section.querySelectorAll('tbody').find((b) => b.textContent.includes('Bolt'));
          assert(body.textContent.includes('Own another printing (M19 314)'), body.textContent);
          const elfBody = section.querySelectorAll('tbody').find((b) => b.textContent.includes('Elf'));
          assert(!elfBody.textContent.includes('printing ('), elfBody.textContent);
          // The banner and the totals don't change with the note.
          const plain = availabilityBanner(makePage(), {view: {tab: 'overview'}}).textContent;
          assert.equal(availabilityBanner(page, {view: {tab: 'overview'}}).textContent, plain);
        """)

    def test_a_viewer_who_may_not_see_the_collection_gets_no_note(self):
        self.run_js(r"""
          const page = withOwn(other); delete page.owned;
          assert.equal(cardMarks(page).size, 0);
          assert.equal(ownedSection(page), null);
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target&tab=cards';
          drawDeck(page, deckViewOf(parseHash().params));
          assert(!main.textContent.includes('Own another printing'), main.textContent);
        """)

    def test_the_cards_tab_draws_the_note(self):
        self.run_js(r"""
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target&tab=cards';
          drawDeck(withOwn(other), deckViewOf(parseHash().params));
          assert(panel('cards').textContent.includes('Own another printing (M19 314)'), panel('cards').textContent);
        """)


if __name__ == "__main__":
    unittest.main()
