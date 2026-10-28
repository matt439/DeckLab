"""Arrival notices on the page (E6-S19, arrival-notices.js): a home player's notices above the page after a
profile is chosen, each deck linked with its count, and Dismiss with Undo before the dismissal is saved."""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  const box = el("div", { id: "arrival-notices", hidden: true }); document.body.append(box);
  const home = { id: "user1", name: "User1", plays_as: "wife", space: "home" };
  const other = { id: "matt", name: "Matt", plays_as: "user", space: "home" };
  const member = { id: "user2", name: "User2", space: "user2" };
  const NOTICE = { id: "qwertyuiop:0123456789abcdef", order: "2026-10-07-shop-a", received_on: "2026-10-08", cards: 3,
    more: 0, decks: [{ id: "casual/deck-a", title: "Deck A", cards: 2 }, { id: "casual/deck-b", title: "Deck B", cards: 1 }] };
  const asked = [], writes = [];
  api = async (path) => { asked.push(path); return { notices: [NOTICE] }; };
  apiWrite = async (path, body) => { writes.push([path, body]); return { notices: [] }; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ArrivalNoticeUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_a_home_player_sees_each_deck_linked_with_its_count(self):
        self.run_js("""
          state.profile = home;
          await loadArrivalNotices(home);
          same(asked, ["/api/arrivals"]);
          assert.equal(box.hidden, false);
          const notice = box.querySelector(".arrival-notice");
          assert.equal(notice.querySelector("h2").textContent, "Cards arrived for your decks");
          assert(notice.textContent.includes("brought 2 cards for Deck A and 1 card for Deck B."), notice.textContent);
          same(notice.querySelectorAll("a").map((a) => a.getAttribute("href")),
               ["#/deck?id=casual%2Fdeck-a", "#/deck?id=casual%2Fdeck-b"]);
          // Someone outside the home isn't asked at all; switching profile takes the notice away.
          clearArrivalNotices();
          assert.equal(box.hidden, true);
          state.profile = member;
          await loadArrivalNotices(member);
          same(asked, ["/api/arrivals"]);
          assert.equal(box.hidden, true);
        """)

    def test_a_failed_read_shows_nothing_and_a_stale_answer_is_dropped(self):
        self.run_js("""
          api = async () => { throw new ApiError(503, "down"); };
          state.profile = home;
          await loadArrivalNotices(home);
          assert.equal(box.hidden, true);
          let finish;
          api = () => new Promise((resolve) => { finish = resolve; });
          const loading = loadArrivalNotices(home);
          state.profile = other;
          finish({ notices: [NOTICE] }); await loading;
          assert.equal(box.hidden, true);
        """)

    def test_dismiss_waits_for_undo_then_saves_only_for_the_same_person(self):
        self.run_js("""
          state.profile = home;
          await loadArrivalNotices(home);
          const notice = box.querySelector(".arrival-notice");
          notice.querySelector("button").click();
          assert.equal(notice.hidden, true);
          assert.equal(box.hidden, true);
          // Undo puts it back and writes nothing.
          document.body.querySelector("#toast-undo").querySelector("button").click();
          assert.equal(notice.hidden, false);
          flushTimers(); await null;
          same(writes, []);
          // Without Undo the dismissal is saved once the toast's time is up.
          notice.querySelector("button").click();
          flushTimers(); await null; await null;
          same(writes, [["/api/arrivals/dismiss", { ids: ["qwertyuiop:0123456789abcdef"] }]]);
          assert.equal(notice.isConnected, false);
          // Another person chosen before the time is up: nothing is dismissed as them.
          await loadArrivalNotices(home);
          box.querySelector(".arrival-notice").querySelector("button").click();
          state.profile = other;
          flushTimers(); await null; await null;
          assert.equal(writes.length, 1);
        """)

    def test_a_refused_dismissal_puts_the_notice_back_and_says_why(self):
        self.run_js("""
          state.profile = home;
          await loadArrivalNotices(home);
          apiWrite = async () => { throw new ApiError(503, "The database can't be reached."); };
          let said = ""; toast = (text) => { said = text; };
          const notice = box.querySelector(".arrival-notice");
          notice.querySelector("button").click();
          flushTimers(); await null; await null;
          assert.equal(notice.hidden, false);
          assert.equal(box.hidden, false);
          assert(said.includes("The database can't be reached."));
        """)

    def test_the_same_person_picked_again_within_undo_time_keeps_the_notice_dismissed(self):
        self.run_js("""
          state.profile = home;
          await loadArrivalNotices(home);
          box.querySelector(".arrival-notice").querySelector("button").click();
          // Switch person, then User1 again: the stored notice is drawn afresh, but stays hidden.
          clearArrivalNotices();
          await loadArrivalNotices(home);
          const again = box.querySelector(".arrival-notice");
          assert.equal(again.hidden, true);
          assert.equal(box.hidden, true);
          flushTimers(); await null; await null;
          same(writes, [["/api/arrivals/dismiss", { ids: ["qwertyuiop:0123456789abcdef"] }]]);
          assert.equal(again.isConnected, false);
          // Undo after a redraw puts back the notice now shown.
          await loadArrivalNotices(home);
          box.querySelector(".arrival-notice").querySelector("button").click();
          await loadArrivalNotices(home);
          document.body.querySelector("#toast-undo").querySelector("button").click();
          assert.equal(box.querySelector(".arrival-notice").hidden, false);
          assert.equal(box.hidden, false);
        """)
