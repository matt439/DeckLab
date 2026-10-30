"""The warm-worker fallback sentence on the matchup page's live box and the Playing now rows (E3-S26).

The deterministic DOM double over the real page scripts never starts Forge or touches the database.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  const FALLBACK = "Forge's warm workers couldn't start (two stopped before they were ready), " +
    "so these games play one process at a time.";
  const member = {id: 'user2', name: 'User2', role: 'member', space: 'user2'};
  const admin = {id: 'matt', name: 'Matt', role: 'admin', space: 'home'};
  state.profile = member; state.may = {admin: false, runs: false};
  const sides = [{id: 'user2/casual/a', title: 'A', version: 'target'}, {id: 'user2/casual/b', title: 'B', version: 'target'}];
  const job = (extra) => ({status: 'running', done: 50, total: 200, wins: [30, 18], other: 2, mode: 'fixed',
    waiting: null, fallback: null, range: null, by: 'User2', ...extra});
  const run = (extra) => ({key: 'opaque', kind: 'matchup', sides, title: 'A v B', link: '#/matchup?key=opaque',
    status: 'running', ahead: 0, done: 50, total: 200, wins: [30, 18], by: 'User2', waiting: null, fallback: null,
    mode: 'fixed', plan: null, eta_s: null, ...extra});
  const fallbackOf = (node) => node.querySelector('.mu-fallback');
  // Every number on a node: a worker count would show as one the progress words don't already have.
  const numbers = (text) => (text.match(/\d[\d,]*/g) || []).sort();
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupFallbackUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_live_box_shows_the_sentence_after_the_played_words_and_only_while_set(self):
        self.run_js(r"""
          const live = liveBox({});
          live.update({sides, job: job({fallback: FALLBACK})});
          const line = fallbackOf(live.node), played = live.node.querySelector('.mu-played');
          assert.equal(line.hidden, false);
          assert.equal(line.textContent, FALLBACK);
          assert.equal(played.textContent, '50 of 200 games played.');
          // Straight after the played (or waiting) words.
          assert.equal(played.nextElementSibling || played.nextSibling, line);
          // Waiting for other runs: the waiting sentence, then the fallback one.
          live.update({sides, job: job({waiting: 'Waiting for other matchups ahead in the queue.', fallback: FALLBACK})});
          assert.equal(played.textContent, 'Waiting for other matchups ahead in the queue.');
          assert.equal(line.textContent, FALLBACK);
          assert.equal(line.hidden, false);
          // An adaptive run's played words keep it too.
          live.update({sides, job: job({mode: 'ahead', plan: {mode: 'ahead', next_look: 400, max: 3200, games_before: 0},
            fallback: FALLBACK})});
          assert.equal(line.hidden, false);
          // Null, blank, not a string, or still queued: nothing extra.
          for (const extra of [{fallback: null}, {fallback: '  '}, {fallback: 3}, {fallback: {why: 'x'}}, {},
                               {status: 'queued', fallback: FALLBACK}]) {
            live.update({sides, job: job(extra)});
            assert.equal(line.hidden, true, JSON.stringify(extra));
            assert.equal(line.textContent, '');
            assert(!live.node.textContent.includes('one process at a time'));
          }
        """)

    def test_playing_now_rows_show_the_sentence_after_the_waiting_words(self):
        self.run_js(r"""
          for (const against of [false, true]) {
            const row = runningRow(run({fallback: FALLBACK}), {against});
            const meta = row.querySelector('.mu-meta'), line = fallbackOf(row);
            assert.equal(line.textContent, FALLBACK);
            assert(meta.textContent.indexOf('50 of 200 games') < meta.textContent.indexOf(FALLBACK));
            const waiting = runningRow(run({waiting: 'Waiting for other Forge runs on this PC to finish.', fallback: FALLBACK}), {against});
            const text = waiting.querySelector('.mu-meta').textContent;
            assert(text.indexOf('Waiting for other Forge runs') < text.indexOf(FALLBACK));
            for (const extra of [{fallback: null}, {fallback: ''}, {fallback: false}, {status: 'queued', fallback: FALLBACK}]) {
              const plain = runningRow(run(extra), {against});
              assert.equal(fallbackOf(plain), null, JSON.stringify(extra));
              assert(!plain.textContent.includes('one process at a time'));
            }
          }
          // A field run or a variant test's row (no sides) has no fallback of its own.
          const coord = runningRow({key: 'field:opaque', kind: 'field', title: 'Field run of A', status: 'running',
            done: 1, total: 4, link: '#/matchups', sides: null, fallback: FALLBACK});
          assert.equal(fallbackOf(coord), null);
        """)

    def test_a_members_view_adds_only_the_sentence_with_no_names_or_worker_counts(self):
        self.run_js(r"""
          for (const profile of [member, admin]) {
            state.profile = profile;
            const without = runningRow(run()), withIt = runningRow(run({fallback: FALLBACK}));
            assert.equal(withIt.textContent, without.textContent + FALLBACK);
            const line = fallbackOf(withIt).textContent;
            same(numbers(line), []);
            for (const word of ['User2', 'Matt', 'User1', 'worker 1', 'workers:', 'slot']) assert(!line.includes(word), word);
            const live = liveBox({}), plain = liveBox({});
            live.update({sides, job: job({fallback: FALLBACK})}); plain.update({sides, job: job()});
            same(numbers(live.node.textContent), numbers(plain.node.textContent));
            assert.equal(live.node.textContent, plain.node.textContent.replace('50 of 200 games played.',
              '50 of 200 games played.' + FALLBACK));
          }
        """)


if __name__ == "__main__":
    unittest.main()
