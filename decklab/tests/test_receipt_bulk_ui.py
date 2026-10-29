"""E6-S27: a mixed cards-and-tokens delivery that came as ordered reaches Preview in three actions (Everything
arrived as ordered, All checks done, Backs as recorded or blank), each behind one confirmation, and sends exactly
the request ticking every row by hand sends; blank backs are written only on rows the person confirms, rows with
an unconfirmed pairing still ask, and blockers are listed once per part (receipt-bulk.js)."""
import unittest

from decklab.tests import test_receipts_ui as board

MIXED = """
  const mixed = () => {
    const d = delivery();
    d.components[0].checks = ['Verify actual condition', 'Check the foil Beta'];
    d.components.push({id:'tokens',kind:'tokens',status:'pending',checks:[],fields:""" + board.TOKEN_FIELDS + """,
      rows:[{front:'Treasure',back:'',set:'tfdn',front_collector_number:'12',back_collector_number:'',finish:'nonfoil',quantity:'2',
             front_details:'',back_details:'',notes:''},
            {front:'Ooze',back:'',set:'tm11',front_collector_number:'5',back_collector_number:'',finish:'nonfoil',quantity:'1',
             front_details:'2/2; green',back_details:'',notes:'listed as Ooze Token (A); check on arrival'},
            {front:'Bird',back:'Golem',set:'teoc',front_collector_number:'3',back_collector_number:'12',finish:'nonfoil',quantity:'1',
             front_details:'2/2; blue',back_details:'3/3',notes:'listing shows this pairing'}],
      pictures:null,decks:null});
    return d;
  };
  const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  let confirmations = 0;
  const confirm = async () => {
    const yes = document.body.querySelector('[data-action=yes]');assert(yes, 'a confirmation is open');
    confirmations++;yes.click();await settle();
    assert(!document.body.querySelector('dialog'), 'one confirmation per action');
  };
  const fresh = (d = mixed()) => { window.localStorage.clear?.(); for (let i = window.localStorage.length - 1; i >= 0; i--)
    window.localStorage.removeItem(window.localStorage.key(i)); clear(main); return drawReceipt(d, routeToken); };
  const previewBody = async (v) => {
    const calls = [];apiWrite = async (path, b) => { calls.push([path, b]); return ready; };
    await previewDelivery(v);closeSheets();
    assert.equal(calls.length, 1);assert.equal(calls[0][0], '/api/receipt/preview');return calls[0][1];
  };
"""


@unittest.skipUnless(board.NODE, "Node.js isn't installed")
class ReceiptBulkTests(unittest.TestCase):
    def run_js(self, scenario):
        board.ReceiptBoardTests.run_js(self, MIXED + scenario, draw=False)

    def test_three_actions_reach_preview_with_the_same_request_as_ticking_by_hand(self):
        self.run_js("""
          // By hand: two "This arrived" boxes, five ticks, two token sheets' "Back is blank" and two checks.
          let v = fresh(), actions = 0;
          for (const comp of v.comps) { const box = comp.section.querySelector('.rcpt-arrived').querySelector('input');
            box.checked = true; box.fire('change'); actions++; }
          // Ticked and selected, the blockers are listed once per part: 4 rows and checks before E6-S27, 2 now.
          for (const comp of v.comps) for (const row of comp.rows) rcptTick(v, comp, row, true);
          actions += 5;
          const blockers = rcptClientBlockers(v);assert.equal(blockers.length, 2);
          assert(blockers[0].text.includes('2 checks not ticked: Verify actual condition; Check the foil Beta'));
          assert(blockers[1].text.includes('say what 2 backs are'));assert(blockers[1].text.includes('Treasure (TFDN 12)'));
          assert(blockers[1].text.includes('Ooze (TM11 5)'));assert(!blockers[1].text.includes('Bird'));
          const tokens = v.comps[1];
          for (const row of tokens.rows.slice(0, 2)) {
            rcptOpenSheet(v, tokens, row);actions++;
            const blank = document.body.querySelector('.rcpt-blank').querySelector('input');blank.checked = true;blank.fire('change');actions++;
            v.sheet.sheet.close();
          }
          v.comps[0].checkBoxes.forEach(box => { box.checked = true; box.fire('change'); actions++; });
          assert.equal(rcptClientBlockers(v).length, 0);assert.equal(actions, 13);
          const byHand = await previewBody(v);
          assert.equal(byHand.components[1].rows[0].notes, 'single-sided verified');
          assert.equal(byHand.components[1].rows[1].notes, 'listed as Ooze Token (A); single-sided verified');
          assert.equal(byHand.components[1].rows[2].notes, '');

          // With the shortcuts: three actions, each with one confirmation.
          v = fresh();confirmations = 0;
          assert(!v.everythingBar.hidden);assert(v.comps.every(c => c.partActions.hidden));
          assert(main.querySelector('.rcpt-everything-bar').contains(v.everything));
          v.everything.click();await confirm();
          assert(v.comps.every(c => c.selected && c.rows.every(r => r.ticked)));assert(v.everythingBar.hidden);
          assert.equal(rcptClientBlockers(v).length, 2);
          const done = v.comps[0].checksDone, backs = v.comps[1].backsBlank;
          // Each shortcut hides itself, so focus goes on to the next one still showing, then to Record arrival.
          assert.equal(document.activeElement, done);
          assert(!done.hidden);assert.equal(done.textContent, 'All 2 checks done');
          assert(v.comps[0].section.contains(done));assert(!v.comps[1].checksDone);
          assert(!backs.hidden);assert.equal(backs.textContent, 'Backs as recorded or blank (2)…');
          done.click();await confirm();
          assert(done.hidden);same(v.comps[0].checks, [true, true]);assert.equal(document.activeElement, backs);
          v.comps[0].checkBoxes.forEach(box => assert.equal(box.checked, true));
          backs.click();
          const listed = [...document.body.querySelectorAll('.rcpt-backs-list-label')].map(l => l.textContent);
          same(listed, ['Treasure (TFDN 12) × 2', 'Ooze (TM11 5) × 1']);
          assert(document.body.textContent.includes('Backs already recorded need no answer here.'));
          await confirm();
          assert(backs.hidden);assert.equal(rcptClientBlockers(v).length, 0);assert.equal(document.activeElement, v.primary);
          assert.equal(confirmations, 3);
          assert.equal(v.primary.getAttribute('aria-disabled'), 'false');
          same(await previewBody(v), byHand);
        """)

    def test_unconfirmed_pairings_still_ask_and_only_confirmed_rows_become_single_sided(self):
        self.run_js("""
          const d = mixed();
          d.components[1].rows.push({front:'Zombie',back:'',set:'',front_collector_number:'',back_collector_number:'',finish:'',quantity:'1',
            front_details:'',back_details:'',notes:'reverse face unconfirmed'});
          d.components[1].rows.push({front:'Angel',back:'Spirit',set:'',front_collector_number:'',back_collector_number:'',finish:'',quantity:'1',
            front_details:'',back_details:'',notes:'pairing unknown'});
          const v = fresh(d), tokens = v.comps[1];
          v.everything.click();await confirm();
          // A recorded back is open only when a note leaves its pairing unconfirmed.
          same(tokens.rows.map(r => rcptBackOpen(r)), [true, true, false, true, true]);
          same(tokens.rows.map(r => rcptBlankBackOpen(r)), [true, true, false, false, false]);
          assert.equal(tokens.backsBlank.textContent, 'Backs as recorded or blank (2)…');
          tokens.backsBlank.click();
          assert(document.body.textContent.includes('Still to say one by one, as their pairing isn\\'t confirmed: Zombie, Angel // Spirit.'));
          const boxes = [...document.body.querySelectorAll('.rcpt-backs-list-box')];assert.equal(boxes.length, 2);
          boxes[1].checked = false;boxes[1].fire('change');
          const yes = document.body.querySelector('[data-action=yes]');assert.equal(yes.textContent, 'Mark 1 back blank');
          boxes[0].checked = false;boxes[0].fire('change');
          assert.equal(yes.getAttribute('aria-disabled'), 'true');
          const reason = document.body.querySelector('.rcpt-backs-reason');
          assert.equal(reason.textContent, 'Tick at least one card.');assert.equal(yes.getAttribute('aria-describedby'), reason.id);
          // Clicking the inert primary keeps the sheet open and takes focus to the first box in the way.
          yes.click();assert(document.body.querySelector('dialog'));assert.equal(document.activeElement, boxes[0]);
          boxes[0].checked = true;boxes[0].fire('change');assert.equal(reason.textContent, '');await confirm();
          // The Ooze still has an open back, so focus stays on the part's backs answer.
          assert(!tokens.backsBlank.hidden);assert.equal(document.activeElement, tokens.backsBlank);
          same(tokens.rows.map(r => r.values.notes), ['single-sided verified', 'listed as Ooze Token (A)', '',
            'reverse face unconfirmed', 'pairing unknown']);
          const left = rcptClientBlockers(v).filter(b => b.comp === tokens);
          assert.equal(left.length, 1);assert(left[0].text.includes('say what 3 backs are'));
          assert(left[0].text.includes('Ooze (TM11 5), Zombie, Angel // Spirit'));assert.equal(left[0].row, tokens.rows[1]);
          // The flagged rows are never offered in bulk; the Ooze still can be.
          tokens.backsBlank.click();
          same([...document.body.querySelectorAll('.rcpt-backs-list-label')].map(l => l.textContent), ['Ooze (TM11 5) × 1']);
          closeSheets();
          let writes = 0;apiWrite = async () => { writes++; return ready; };
          await previewDelivery(v);assert.equal(writes, 0);
        """)

    def test_cancel_changes_nothing_and_unselected_or_unticked_rows_are_not_answered(self):
        self.run_js("""
          const v = fresh(), before = rcptRequestKey(v);
          v.everything.click();[...document.body.querySelectorAll('button')].find(b => b.textContent === 'Cancel').click();
          await settle();assert.equal(rcptRequestKey(v), before);assert(v.comps.every(c => !c.selected));
          assert(!document.body.querySelector('dialog'));
          // Only the tokens part arrived, one row ticked: the backs answer covers that row only, and no checks show.
          const tokens = v.comps[1], box = tokens.section.querySelector('.rcpt-arrived').querySelector('input');
          box.checked = true;box.fire('change');rcptTick(v, tokens, tokens.rows[1], true);
          assert(v.comps[0].partActions.hidden);assert.equal(tokens.backsBlank.textContent, 'Backs as recorded or blank (1)…');
          tokens.backsBlank.click();
          same([...document.body.querySelectorAll('.rcpt-backs-list-label')].map(l => l.textContent), ['Ooze (TM11 5) × 1']);
          await confirm();
          assert.equal(tokens.rows[0].values.notes, '');assert(rcptBackOpen(tokens.rows[0]));
          assert.equal(tokens.rows[1].values.notes, 'listed as Ooze Token (A); single-sided verified');
          // Everything arrived then picks up the cards part and the remaining rows, without touching the answered one.
          assert(!v.everythingBar.hidden);v.everything.click();
          assert(document.body.textContent.includes('This marks all 2 parts as arrived and ticks all 3 cards and 4 token cards.'));
          await confirm();
          assert(v.comps.every(c => c.selected && c.rows.every(r => r.ticked)));
          assert.equal(tokens.rows[1].values.notes, 'listed as Ooze Token (A); single-sided verified');
          // A view that can't record arrivals hides the shortcuts and ignores them.
          v.busy = true;rcptSyncBulk(v);assert(v.comps.every(c => c.partActions.hidden));
          await rcptAllChecksDone(v, v.comps[0]);assert(!document.body.querySelector('dialog'));same(v.comps[0].checks, [false, false]);
        """)

    def test_a_single_check_part_has_no_extra_button_and_keeps_its_one_blocker_text(self):
        self.run_js("""
          clear(main);const v = drawReceipt(delivery(), routeToken), comp = v.comps[0];
          assert.equal(comp.checksDone, null);assert.equal(comp.backsBlank, null);assert(comp.partActions.hidden);
          assert(rcptClientBlockers(v).some(b => b.text === 'Check not ticked: Verify actual condition'));
          assert(!v.everythingBar.hidden);v.everything.click();
          assert(document.body.textContent.includes('This marks the delivery as arrived and ticks all 3 cards.'));
          await confirm();assert(comp.rows.every(r => r.ticked));
          v.everything.click();assert(!document.body.querySelector('dialog'));
        """)
