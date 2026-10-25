"""Opponent plans on the deck Overview, using the real DOM interaction functions."""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER


FIXTURE = PAGE + """
  const list = (id, version = 'target', sha256 = id + version) => ({id, version, sha256, title: id,
    sections: {Deck: [{name: 'Elf', qty: 4}], Sideboard: [{name: 'Bolt', qty: 2}]}});
  const own = list('casual/test'), opposing = list('casual/other');
  const planEntry = (id, deck = own, opponent = opposing) => ({sha256: 'record-' + id, editable: true,
    record: {id, deck, opponent, revision: 2, updated_by: 'Matt', notes: 'Against creatures',
      out: [{name: 'Elf', qty: 2}], in: [{name: 'Bolt', qty: 2}]},
    cards: {out: [{name: 'Elf', qty: 2, set: 'old', number: '7', finish: 'foil',
      card: {...elf, img: '/img/old/7/normal', img_small: '/img/old/7/small'}}],
      in: [{name: 'Bolt', qty: 2, card: bolt}]}});
  const answer = () => ({lists: [own, opposing], sideboards: [planEntry('saved')], warnings: [],
    decks: {[own.id]: {can_record: true}, [opposing.id]: {can_record: false}}});
  const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
  const section = () => main.querySelector('#sec-sideboard');
  const choose = (value = '0') => { const picker = section().querySelector('select'); picker.value = value; picker.fire('change'); };
  const mount = async (response = answer(), page = makePage()) => {
    clear(main); location.hash = '#/deck?id=casual%2Ftest&v=' + page.version;
    api = async path => { assert.equal(path, '/api/play?id=casual%2Ftest'); return response; };
    main.append(deckSideboardSection(page)); await settle();
  };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckSideboardUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pictures_use_recorded_printing_and_open_the_viewer(self):
        self.run_js("""
          await mount(); choose();
          assert(section().textContent.includes('Out of main deck'));
          assert(section().textContent.includes('In from sideboard'));
          assert(section().textContent.includes('Against creatures'));
          assert(section().textContent.includes('Revision 2; last saved by Matt.'));
          assert(!section().querySelector('.box-warn'));
          const tiles = section().querySelectorAll('.card-tile'); assert.equal(tiles.length, 2);
          assert(tiles[0].textContent.includes('×2')); assert(tiles[0].textContent.includes('OLD 7'));
          assert.equal(tiles[0].querySelector('.card-tile-img').getAttribute('src'), '/img/old/7/small');
          tiles[0].querySelector('button').click();
          assert.equal(inspections[0].card.img, '/img/old/7/normal');
          same(viewerGroup(inspections[0].trigger).items.map(item => item.card.name), ['Elf', 'Bolt']);
          // It is an Overview feature: opening another tab does not request plans.
          let loads = 0; api = async () => { loads++; return answer(); };
          open('#/deck?id=casual%2Ftest&v=target&tab=cards'); await settle();
          assert.equal(loads, 0); tab('overview').click(); await settle(); assert.equal(loads, 1);
        """)

    def test_direction_versions_and_current_pair_take_precedence(self):
        self.run_js("""
          const a = answer(), oldOwn = {...own, sha256: 'old'};
          const stale = planEntry('stale', oldOwn); stale.record.notes = 'Old plan';
          const otherVersion = planEntry('wrong-version', list(own.id, 'owned'));
          const reversed = planEntry('reversed', opposing, own);
          a.sideboards = [reversed, otherVersion, stale, planEntry('current')];
          await mount(a); choose();
          assert(section().textContent.includes('Against creatures')); assert(!section().textContent.includes('Old plan'));
          assert(!section().querySelector('.box-warn'));
          a.sideboards.pop(); await mount(a); choose();
          assert(section().textContent.includes('Old plan')); assert(section().querySelector('.box-warn'));
          // The displayed list is Play-now: a Planned plan must never stand in for it.
          const p = makePage(); p.version = 'owned'; a.lists.push(list(own.id, 'owned'));
          await mount(a, p); choose(); assert(!section().querySelector('.box-warn'));
          a.sideboards = [reversed, stale]; await mount(a, p); choose();
          assert(section().textContent.includes('No saved plan'));
        """)

    def test_no_plan_uses_sideboard_notes_and_prefills_both_versions(self):
        self.run_js("""
          const a = answer(); a.sideboards = []; a.lists = [own, list(own.id, 'owned'), opposing, list(opposing.id, 'owned')];
          const p = makePage(); p.version = 'owned';
          p.guide = {changed_on: '2026-10-14', sections: [{title: 'Sideboard notes', markdown: 'Bring **Bolt** against creatures.'},
            {title: 'Mulligans', markdown: 'Unrelated advice'}]};
          await mount(a, p); choose('1');
          assert(section().textContent.includes('Bring Bolt against creatures.'));
          assert(section().textContent.includes('notes may be out of date'));
          assert(!section().textContent.includes('Unrelated advice'));
          buttonText(section(), 'Make a sideboard plan').click();
          const sheet = document.querySelector('.sheet');
          const pickers = sheet.querySelectorAll('select');
          assert.equal(a.lists[Number(pickers[0].value)].version, 'owned');
          assert.equal(a.lists[Number(pickers[1].value)].id, opposing.id);
          assert.equal(a.lists[Number(pickers[1].value)].version, 'owned');
          assert(sheet.textContent.includes('New sideboard plan'));
        """)

    def test_permissions_allow_read_only_plans_and_either_deck_can_grant_creation(self):
        self.run_js("""
          const a = answer(); a.sideboards[0].editable = false;
          await mount(a); choose(); assert(section().textContent.includes('Against creatures'));
          assert(!buttonText(section(), 'Revise this plan'));
          a.sideboards = []; a.decks[own.id].can_record = false;
          await mount(a); choose(); assert(!buttonText(section(), 'Make a sideboard plan'));
          a.decks[opposing.id].can_record = true;
          await mount(a); choose(); assert(buttonText(section(), 'Make a sideboard plan'));
          state.profile = null; assert.equal(deckSideboardSection(makePage()), null);
        """)

    def test_review_save_refreshes_the_plan_and_keeps_the_selected_opponent(self):
        self.run_js("""
          const a = answer(); a.sideboards = []; let loads = 0;
          await mount(a);
          api = async () => { loads++; return a; };
          const writes = [];
          apiWrite = async (endpoint, payload) => {
            assert.equal(endpoint, '/api/play/sideboard'); writes.push(payload);
            const entry = planEntry('new'); entry.record.after = own.sections;
            if (payload.preview) return {id: 'new', record: entry.record, review_sha256: 'review'};
            a.sideboards = [entry]; return {saved: true};
          };
          choose(); buttonText(section(), 'Make a sideboard plan').click();
          const form = document.querySelector('.play-form');
          for (const input of form.querySelectorAll('input')) input.value = '2';
          form.fire('submit'); await settle();
          assert.equal(writes.length, 1); assert.equal(writes[0].preview, true);
          assert.equal(writes[0].deck.version, 'target'); assert.equal(writes[0].opponent.id, opposing.id);
          const save = buttonText(document.body, 'Save this record'); assert(save);
          save.click(); await settle();
          assert.equal(writes.length, 2); assert.equal(writes[1].review_sha256, 'review');
          assert.equal(writes[1].preview, false); assert.equal(loads, 1);
          assert(section().textContent.includes('Against creatures')); assert(buttonText(section(), 'Revise this plan'));
          assert.equal(document.querySelector('.sheet'), null);
        """)

    def test_stale_deleted_opponent_and_missing_pictures_remain_readable(self):
        self.run_js("""
          const a = answer(); a.lists = [own]; a.sideboards[0].cards.out[0].card = null;
          await mount(a); choose();
          assert(section().textContent.includes('deck unavailable'));
          assert(section().querySelector('.box-warn')); assert(section().textContent.includes('Elf'));
          assert(!buttonText(section(), 'Revise this plan'));
        """)

    def test_plans_against_hidden_opponents_are_each_their_own_choice(self):
        # Another space's private deck comes as {hidden, title} only (E10-S32): two such plans
        # mustn't collapse into one choice nor show each other's swaps.
        self.run_js("""
          const hidden = title => ({hidden: true, title});
          const user2 = planEntry('vs-user2', own, hidden("one of User2's decks"));
          const user3 = planEntry('vs-user3', own, hidden("one of User3's decks"));
          user2.record.notes = 'User2 plan'; user2.record.deck = {...own, sha256: 'older'};
          user2.record.updated_on = '2026-10-01T10:00:00+10:00';
          user3.record.notes = 'User3 plan';
          const a = answer(); a.sideboards = [user3, user2];
          await mount(a);
          const options = [...section().querySelectorAll('option')].map(o => o.textContent);
          assert(options.some(t => t.startsWith("one of User2's decks (private deck; plan saved 2026-10-01")));
          assert(options.some(t => t.startsWith("one of User3's decks (private deck")));
          assert(!options.some(t => t.includes('deck unavailable')));
          const pick = name => String(options.findIndex(t => t.startsWith(name)) - 1);
          choose(pick("one of User2's decks"));
          assert(section().textContent.includes('User2 plan')); assert(!section().textContent.includes('User3 plan'));
          assert(section().querySelector('.box-warn'));       // this deck's list changed since
          assert(!buttonText(section(), 'Revise this plan'));
          choose(pick("one of User3's decks"));
          assert(section().textContent.includes('User3 plan')); assert(!section().textContent.includes('User2 plan'));
          assert(!section().querySelector('.box-warn'));      // the opponent can't be checked: not a warning
        """)

    def test_an_existing_mirror_plan_reuses_the_current_opponent_list(self):
        self.run_js("""
          const a = answer(); a.sideboards = [planEntry('mirror', own, own)];
          await mount(a); choose('1');
          assert(section().textContent.includes('Against creatures'));
          assert(!section().querySelector('.box-warn'));
          assert(!section().textContent.includes('deck unavailable'));
          assert(buttonText(section(), 'Revise this plan'));
        """)

    def test_failures_retain_notes_and_retry_and_late_replies_are_ignored(self):
        self.run_js("""
          const p = makePage(); p.guide.sections = [{title: 'Sideboard', markdown: 'Table advice'}];
          api = async () => { throw new Error('Database unavailable'); };
          clear(main); main.append(deckSideboardSection(p)); await settle();
          assert(section().textContent.includes('Database unavailable')); assert(section().textContent.includes('Table advice'));
          api = async () => answer(); buttonText(section(), 'Try again').click(); await settle(); choose();
          assert(section().textContent.includes('Against creatures'));
          for (const change of ['route', 'profile', 'node']) {
            state.profile = {id: 'matt'}; let reply;
            api = () => new Promise(resolve => { reply = resolve; });
            const node = deckSideboardSection(p); clear(main).append(node);
            if (change === 'route') routeToken++;
            if (change === 'profile') state.profile = {id: 'user2'};
            if (change === 'node') node.remove();
            reply(answer()); await settle();
            assert(!node.textContent.includes('Against creatures')); assert.equal(node.querySelector('select'), null);
          }
        """)


if __name__ == "__main__":
    unittest.main()
