"""Tonight's pairs on the Game log (E1-S28, play-tonight.js): the cards and their reasons, Use this pair
filling the quick record's pickers, the empty and failed states, and no section for a member, in the
event/DOM double with the API stubbed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_play_tonight_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_play_ui import NODE, RUNNER, WEB

SETUP = """
  const sha = (id, version) => id.split('/').at(-1).padStart(63, '0') + (version === 'owned' ? 'b' : 'a');
  const list = (id, title, version = 'target') => ({ id, version, sha256: sha(id, version), title, sections: { Deck: [{ name: 'Forest', qty: 60 }] } });
  const lists = [list('casual/a', 'Alpha'), list('casual/b', 'Beta'), list('casual/c', 'Gamma'), list('casual/c', 'Gamma', 'owned')];
  const data = { lists, games: [], sideboards: [], warnings: [], today: '2026-10-29' };
  const matt = { id: 'matt', name: 'Matt', space: 'home', plays_as: 'user' };
  const user1 = { id: 'user1', name: 'User1', space: 'home', plays_as: 'wife' };
  state.profiles = [matt, user1];
  const pair = (a, av, b, bv, reasons) => ({ sides: [{ id: a, title: a, version: av, seat: 'user', sha256: sha(a, av) },
    { id: b, title: b, version: bv, seat: 'wife', sha256: sha(b, bv) }], evenness: { band: 'even' }, last_played: null, days: null, reasons });
  const answer = { available: true, ready: 3, unconfirmed: 0, error: null, forge_error: null, today: '2026-10-29',
    pairs: [pair('casual/c', 'owned', 'casual/b', 'target', ['Evenly matched by Forge: Gamma wins 50% of 120 simulated games.',
      'Not played against each other yet.']), pair('casual/a', 'target', 'casual/b', 'target', ['Fairly even.', 'Played lately.'])] };
  const asked = [];
  const answering = (value) => { api = async (path) => { asked.push(path); if (value instanceof Error) throw value; return value; }; };
  const settle = async () => { for (let i = 0; i < 6; i++) await null; };
  const openTonight = async () => {
    const disclosure = main.querySelector('.play-choose-tonight');
    disclosure.open = true; disclosure.fire('toggle'); await settle();
  };
  const pickers = () => main.querySelectorAll('select').filter((s) => /^play-quick-deck/.test(s.id || ''));
  const chosen = () => pickers().map((s) => lists[Number(s.value)].title + ' ' + lists[Number(s.value)].version);
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class PlayTonightUiTests(unittest.TestCase):
    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("hands.js", "play.js", "play-tonight.js"))
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), sources + "\n" + SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_pairs_show_their_reasons_and_fill_the_quick_record_by_seat(self):
        self.run_js("""
          answering(answer); state.profile = user1;
          clear(main); drawPlay(data, ''); await settle();
          same(asked, []);
          assert.equal(main.querySelector('.play-choose-tonight').querySelector('summary').textContent, 'Choose decks for tonight');
          await openTonight();
          same(asked, ['/api/play/pairs']);
          const section = main.querySelector('.play-tonight');
          assert.equal(section.querySelector('h2').textContent, "Tonight's pairs");
          const cards = section.querySelectorAll('.play-tonight-pair');
          same(cards.map((c) => c.querySelector('h3').textContent), ['casual/c vs casual/b', 'casual/a vs casual/b']);
          assert.equal(cards[0].querySelector('.sub').textContent,
            `Matt: casual/c (${listName('owned', true)}) · User1: casual/b (${listName('target', true)})`);
          same(cards[0].querySelectorAll('li').map((li) => li.textContent), answer.pairs[0].reasons);
          // User1 is the visitor, so her (wife seat) deck goes on side 0 and Matt's on side 1, on the right lists.
          cards[0].querySelector('button').click();
          same(chosen(), ['Beta target', 'Gamma owned']);
          state.profile = matt; clear(main); drawPlay(data, ''); await openTonight();
          main.querySelectorAll('.play-tonight-pair')[1].querySelector('button').click();
          same(chosen(), ['Alpha target', 'Beta target']);
          assert.ok(!main.textContent.includes('undefined') && !main.textContent.includes('null'));
        """)

    def test_stale_pair_changes_neither_seat_and_offers_an_explicit_refresh(self):
        self.run_js("""
          const missing = pair('casual/d', 'target', 'casual/b', 'target', []);
          const changed = structuredClone(answer.pairs[0]);
          changed.sides[0].sha256 = 'f'.repeat(64);
          answering({...answer, pairs:[missing, changed]});
          state.profile = matt;
          let refreshes = 0; route = () => refreshes++;
          clear(main); drawPlay(data, ''); await openTonight();
          pickers()[0].value = '1'; pickers()[1].value = '2';
          for (const card of main.querySelectorAll('.play-tonight-pair')) {
            const [use, refresh] = card.querySelectorAll('button');
            assert(refresh.parentNode.hidden);
            use.click();
            same(chosen(), ['Beta target', 'Gamma target']);
            assert.match(card.querySelector('[role="status"]').textContent, /Refresh the Game log/);
            assert(!refresh.parentNode.hidden);
            assert.equal(refreshes, 0);
          }
          const refresh = main.querySelector('.play-tonight-pair').querySelectorAll('button')[1];
          refresh.click(); assert.equal(refreshes, 1);
          clear(main); drawPlay(data, '');
          refresh.fire('click'); assert.equal(refreshes, 1);
        """)

    def test_empty_failed_and_member_states(self):
        self.run_js("""
          state.profile = matt;
          answering({ ...answer, pairs: [], ready: 1, unconfirmed: 2 });
          clear(main); drawPlay(data, ''); await openTonight();
          assert.match(main.querySelector('.play-tonight').textContent,
            /No pair can be suggested yet: whether 2 built decks have every card here needs checking[.]/);
          answering({ ...answer, pairs: [], ready: 1, unconfirmed: 0 });
          clear(main); drawPlay(data, ''); await openTonight();
          assert.match(main.querySelector('.play-tonight').textContent, /it takes two built casual decks/);
          answering({ ...answer, pairs: [], error: 'The Game log can not be read now.' });
          clear(main); drawPlay(data, ''); await openTonight();
          assert.match(main.querySelector('.play-tonight').textContent, /The Game log can not be read now[.]/);
          answering({ ...answer, forge_error: 'No Forge.' });
          clear(main); drawPlay(data, ''); await openTonight();
          assert.match(main.querySelector('.play-tonight').textContent, /No Forge[.] The pairs go by real games only[.]/);
          assert.equal(main.querySelectorAll('.play-tonight-pair').length, 2);
          answering(new ApiError(500, 'Boom'));
          clear(main); drawPlay(data, ''); await openTonight();
          assert.match(main.querySelector('.play-tonight').textContent, /Boom/);
          // From one deck's Game log, and for a member, there's no section and nothing is asked.
          asked.length = 0;
          answering(answer); clear(main); drawPlay(data, 'casual/a'); await settle();
          assert.equal(main.querySelector('.play-tonight'), null);
          state.profile = { id: 'user2', name: 'User2', space: 'user2' }; state.profiles = [state.profile];
          clear(main); drawPlay(data, ''); await settle();
          assert.equal(main.querySelector('.play-tonight'), null);
          same(asked, []);
        """)


if __name__ == "__main__":
    unittest.main()
