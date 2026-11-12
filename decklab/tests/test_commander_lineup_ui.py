"""A Commander night line-up on the Game log (E9-S34, commander-lineup.js): nothing is asked until Show the
line-up, then the night, the three groups with each deck's facts (minimum, deciding cards, stand-ins, box
checked, last played), the unknown and failed states, and no section for a member or one deck's Game log, in
the event/DOM double with the API stubbed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_commander_lineup_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_play_ui import NODE, RUNNER, WEB

SETUP = """
  const data = { lists: [], games: [], sideboards: [], warnings: [], today: '2026-11-12' };
  const matt = { id: 'matt', name: 'Matt', space: 'home', plays_as: 'user' };
  state.profiles = [matt];
  const row = (id, title, extra) => ({ id, title, status: 'built', built: true, version: 'target', target_bracket: 2,
    minimum: 1, below_range: false, deciding: [], unknown_reason: null, minimum_so_far: null, last_played: null,
    days_since_played: null, played_known: true, ...extra });
  const answer = { available: true, limit: 2, basis: 'The household aims for Bracket 2 at this night.',
    night: { name: 'Fixture night', venue: 'Fictional venue', target_bracket: 2, published_min: 1, published_max: 4 },
    night_error: null, played_error: null, timed_out: 0, today: '2026-11-12',
    groups: {
      fits: [row('commander/a', 'Alpha', { stand_ins: [{ for: 'Sol Ring', using: null, qty: 1 }, { for: 'Mana Crypt', using: 'Arcane Signet', qty: 2 }],
        box_checked_on: '2026-11-01', last_played: '2026-11-02', days_since_played: 10 }),
             row('commander/b', 'Beta', { status: 'idea', built: false, stand_ins: [], box_checked_on: null })],
      above: [row('commander/c', 'Gamma', { minimum: 3, deciding: [{ reason: '1 Game Changer (none in Brackets 1-2)', cards: ['Sol Ring'] }] })],
      unknown: [row('commander/d', 'Delta', { minimum: null, minimum_so_far: 1, version: 'owned',
        unknown_reason: "Scryfall's oracle tags couldn't be read, so mass land denial and extra turns weren't counted." })] },
    counts: { fits: 2, above: 1, unknown: 1 } };
  const asked = [];
  const answering = (value) => { api = async (path) => { asked.push(path); if (value instanceof Error) throw value; return value; }; };
  const settle = async () => { for (let i = 0; i < 6; i++) await null; };
  const button = () => main.querySelector('.commander-lineup-body').querySelector('button');
  const show = async () => { button().click(); await settle(); };
  const texts = (selector, inner) => main.querySelectorAll(selector).map((node) => node.querySelector(inner).textContent);
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class CommanderLineupUiTests(unittest.TestCase):
    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8")
                            for name in ("hands.js", "play.js", "play-tonight.js", "commander-lineup.js"))
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), sources + "\n" + SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_line_up_waits_for_show_then_lists_each_group_with_its_facts(self):
        self.run_js("""
          answering(answer); state.profile = matt;
          clear(main); drawPlay(data, ''); await settle();
          const section = main.querySelector('.commander-lineup');
          assert.equal(section.querySelector('h2').textContent, 'Commander night line-up');
          same(asked, []);
          await show();
          same(asked, ['/api/commander-night/lineup']);
          assert.match(section.querySelector('.commander-lineup-night').textContent,
            /Fixture night at Fictional venue[.] The household aims for Bracket 2 at this night[.] Published venue range: Brackets 1–4[.]/);
          same(texts('.commander-lineup-group', 'h3'), ['Fits the night (2)', 'Above the aim (1)', 'Unknown (1)']);
          same(texts('.commander-lineup-deck', 'h4'), ['Alpha', 'Beta', 'Gamma', 'Delta']);
          const [alpha, beta, gamma, delta] = main.querySelectorAll('.commander-lineup-deck');
          assert.equal(alpha.querySelector('a').getAttribute('href'), '#/deck?id=commander%2Fa&v=target');
          assert.match(alpha.textContent, /Built · Counted minimum: Bracket 1 · Target Bracket 2/);
          assert.match(alpha.textContent, /Stand-ins: a spare card for Sol Ring; 2 × Arcane Signet for Mana Crypt/);
          assert.match(alpha.textContent, /Box checked 2026-11-01/);
          assert.match(alpha.textContent, /Last played 2026-11-02 [(]10 days ago[)]/);
          assert.match(beta.textContent, /Idea · Counted minimum: Bracket 1/);
          assert.match(beta.textContent, /No stand-ins/);
          assert.match(beta.textContent, /Box not checked yet/);
          assert.match(beta.textContent, /Not played at home yet/);
          assert.match(gamma.textContent, /1 Game Changer [(]none in Brackets 1-2[)]: Sol Ring/);
          // Gamma's answer had no stand-in or box keys (a viewer who may not see them): no line at all.
          assert.ok(!/Stand-ins|stand-ins|Box/.test(gamma.textContent));
          assert.match(delta.textContent, /At least Bracket 1 so far/);
          assert.match(delta.textContent, /oracle tags couldn't be read/);
          assert.match(delta.textContent, /Judged on its Play-now list/);
          assert.equal(delta.querySelector('a').getAttribute('href'), '#/deck?id=commander%2Fd&v=owned');
          assert.ok(!main.textContent.includes('undefined') && !main.textContent.includes('null'));
        """)

    def test_no_night_warnings_empty_failed_and_member_states(self):
        self.run_js("""
          state.profile = matt;
          answering({ ...answer, night: null, limit: null, basis: 'No Commander night is recorded, so no deck can be judged against it.',
            played_error: 'The Game log can not be read now.', timed_out: 2,
            groups: { fits: [], above: [], unknown: answer.groups.unknown }, counts: { fits: 0, above: 0, unknown: 1 } });
          clear(main); drawPlay(data, ''); await settle(); await show();
          const text = main.querySelector('.commander-lineup').textContent;
          assert.match(text, /No Commander night is recorded/);
          assert.match(text, /The Game log can not be read now[.]/);
          assert.match(text, /2 decks weren't checked in time, so they're listed as unknown[.]/);
          same(texts('.commander-lineup-group', 'h3'), ['Unknown (1)']);
          answering({ ...answer, groups: { fits: [], above: [], unknown: [] }, counts: { fits: 0, above: 0, unknown: 0 } });
          button().click(); await settle();
          assert.match(main.querySelector('.commander-lineup').textContent, /There are no home Commander decks to line up yet[.]/);
          answering(new ApiError(500, 'Boom'));
          button().click(); await settle();
          assert.match(main.querySelector('.commander-lineup').textContent, /Boom/);
          assert.equal(button().textContent, 'Check again');
          // From one deck's Game log, and for a member, there's no section and nothing is asked.
          asked.length = 0;
          answering(answer); clear(main); drawPlay(data, 'commander/a'); await settle();
          assert.equal(main.querySelector('.commander-lineup'), null);
          state.profile = { id: 'user2', name: 'User2', space: 'user2' }; state.profiles = [state.profile];
          clear(main); drawPlay(data, ''); await settle();
          assert.equal(main.querySelector('.commander-lineup'), null);
          same(asked, []);
        """)

    def test_a_late_answer_after_a_profile_switch_is_dropped(self):
        self.run_js("""
          state.profile = matt;
          let release;
          api = (path) => { asked.push(path); return new Promise((resolve) => { release = () => resolve(answer); }); };
          clear(main); drawPlay(data, ''); await settle(); await show();
          state.profile = { id: 'user1', name: 'User1', space: 'home', plays_as: 'wife' };
          release(); await settle();
          assert.equal(main.querySelectorAll('.commander-lineup-deck').length, 0);
        """)


if __name__ == "__main__":
    unittest.main()
