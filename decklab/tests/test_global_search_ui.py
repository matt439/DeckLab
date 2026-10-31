"""The top bar's global search (global-search.js, E11-S31): the groups in order, See all, the card viewer,
the `/` key (not in the Editor), stale and other-person answers dropped, and the phone's sheet.

Real page functions over the event/DOM double (fixtures/workspace_ui_runner.js) with the API stubbed: no
browser, server, database write or Forge run.
"""
import json
import subprocess
import unittest

from decklab.tests.test_shell_ui import SETUP as SHELL
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = SHELL + r'''
  document.body.append(el("div", { id: "global-search", hidden: true }));
  const ELVES = { name: "Llanowar Elves", type_line: "Creature — Elf Druid" };
  const MYSTIC = { name: "Elvish Mystic", type_line: "Creature — Elf Druid" };
  const ANSWER = { q: "elv", groups: [
    { id: "decks", label: "Decks", items: [{ id: "user2/casual/r-elves", title: "Elves", kind: "casual", format: "casual",
      status: "built" }], total: 7, capped: false, more: true },
    { id: "collection", label: "In your collection", space: "user2", items: [{ name: "Llanowar Elves", owned: 2, incoming: 1,
      in_use: 2, free: 0, basic: false, card: ELVES }], total: 1, capped: false, more: false },
    { id: "cards", label: "Other cards", items: [{ name: "Elvish Mystic", card: MYSTIC }], total: 240, capped: true, more: true }] };
  let searches = [], pending = [];
  const realApi = api;
  api = async (path) => {
    if (path.startsWith("/api/search")) {
      searches.push(path);
      return new Promise((resolve) => pending.push(resolve));
    }
    return realApi(path);
  };
  const viewed = [];
  openCardViewer = (items, start, opts) => { viewed.push(items); };
  const box = () => gsBar;
  async function type(text) {
    box().input.value = text; box().input.fire("input"); flushTimers(); await flush();
  }
  async function answer(data = ANSWER, at = pending.length - 1) { pending[at](structuredClone(data)); await flush(); }
  function start(id = "user2") {
    as(id); setUpShell(); drawShell(); location.hash = "#/library"; syncShell("library");
    byId("avatar-menu").hidden = true;          // closed, as index.html has it
    window.matchMedia(GS_FIELD_QUERY).matches = true;     // 600 px and up: the field in the top bar
  }
'''


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GlobalSearchUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_groups_in_order_with_counts_links_and_see_all(self):
        self.run_js(r'''
          start();
          assert.equal(byId("global-search").hidden, false);
          box().input.focus();
          await type("elv");
          same(searches, ["/api/search?q=elv"]);
          await answer();
          const results = box().results;
          assert.equal(results.hidden, false);
          assert.equal(box().input.getAttribute("aria-expanded"), "true");
          same(results.querySelectorAll("h3").map((h) => h.textContent), ["Decks", "In your collection", "Other cards"]);
          const deck = results.querySelector("a");
          assert.equal(deck.getAttribute("href"), "#/deck?id=user2%2Fcasual%2Fr-elves&v=target");
          assert(deck.textContent.includes("casual · built"));
          const items = results.querySelectorAll(".gs-item");
          assert(items[1].textContent.includes("0 free · 2 in decks · 1 on the way"));
          items[1].click();
          assert.equal(inspections.at(-1).card.name, "Llanowar Elves");
          const all = results.querySelectorAll(".gs-all");
          same(all.map((a) => a.textContent), ["See all 7", "See all 240+"]);
          assert.equal(all[0].getAttribute("href"), "#/library?all=1&q=elv");
          all[1].click(); await flush();
          assert.equal(searches.at(-1), "/api/search?q=elv&group=cards&limit=50");
          await answer({ q: "elv", groups: [{ id: "cards", items: [{ name: "A", card: MYSTIC }, { name: "B", card: ELVES }] }] });
          same(viewed[0].map((c) => c.name), ["Elvish Mystic", "Llanowar Elves"]);
          assert(box().status.textContent.includes("3 results"));
        ''')

    def test_collection_see_all_goes_to_the_collection_search(self):
        self.run_js(r'''
          start("matt"); box().input.focus(); await type("sol");
          const data = structuredClone(ANSWER);
          data.q = "sol"; data.groups[1].more = true; data.groups[1].total = 9; data.groups[1].space = "home";
          await answer(data);
          const link = box().results.querySelectorAll(".gs-all")[1];
          assert.equal(link.getAttribute("href"), "#/collection?q=sol");
        ''')

    def test_nothing_found_and_an_error_say_so(self):
        self.run_js(r'''
          start(); box().input.focus(); await type("zzz");
          await answer({ q: "zzz", groups: [{ id: "cards", label: "Other cards", items: [], total: 0, more: false }] });
          assert(box().results.textContent.includes("Nothing matches “zzz”."));
          await type("x"); pending.at(-1);
          const failing = pending.length - 1;
          pending[failing] = null;
          api = async () => { throw new ApiError(503, "Deck Lab's database can't be reached."); };
          await type("y");
          assert(box().results.textContent.includes("database can't be reached"));
        ''')

    def test_older_text_and_another_persons_answers_are_dropped(self):
        self.run_js(r'''
          start(); box().input.focus();
          await type("el"); await type("elv");
          assert.equal(pending.length, 2);
          await answer(ANSWER, 0);                      // the answer to "el" arrives after "elv" was typed
          assert.equal(box().results.querySelectorAll("h3").length, 0);
          await answer(ANSWER, 1);
          assert.equal(box().results.querySelectorAll("h3").length, 3);
          await type("elf");
          as("user1"); drawShell();                     // another person chose before the answer came
          assert.equal(box().input.value, "");
          await answer(ANSWER, 2);
          assert.equal(box().results.querySelectorAll("h3").length, 0);
        ''')

    def test_slash_focuses_the_search_but_not_in_the_editor_or_a_field(self):
        self.run_js(r'''
          start();
          let event = document.fire("keydown", { key: "/", target: main });
          assert(event.defaultPrevented); assert.equal(document.activeElement, box().input);
          assert.equal(box().input.getAttribute("aria-keyshortcuts"), "/");
          document.activeElement = null;
          const field = el("input"); main.append(field);
          assert(!document.fire("keydown", { key: "/", target: field }).defaultPrevented);
          assert(!document.fire("keydown", { key: "/", target: main, ctrlKey: true }).defaultPrevented);
          location.hash = "#/edit?id=casual%2Fa"; syncShell("edit");
          assert.equal(box().input.getAttribute("aria-keyshortcuts"), null);
          event = { key: "/", target: main, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
          gsSlash(event);
          assert(!event.defaultPrevented); assert.notEqual(document.activeElement, box().input);
          location.hash = "#/library"; syncShell("library");
          setKeyboardCharactersEnabled(false);
          event = { key: "/", target: main, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
          gsSlash(event);
          assert(!event.defaultPrevented);
        ''')

    def test_keys_move_through_results_and_escape_closes_them(self):
        self.run_js(r'''
          start(); box().input.focus(); await type("elv"); await answer();
          const picks = box().results.querySelectorAll(".gs-pick");
          box().input.fire("keydown", { key: "ArrowDown", preventDefault() {} });
          assert.equal(document.activeElement, picks[0]);
          box().results.fire("keydown", { key: "ArrowDown", preventDefault() {} });
          assert.equal(document.activeElement, picks[1]);
          box().results.fire("keydown", { key: "ArrowUp", preventDefault() {} });
          box().results.fire("keydown", { key: "ArrowUp", preventDefault() {} });
          assert.equal(document.activeElement, box().input);
          box().input.fire("keydown", { key: "Escape", preventDefault() {} });
          assert.equal(box().results.hidden, true);
          let followed = 0; picks[0].addEventListener("click", () => { followed += 1; });
          box().form.fire("submit", { preventDefault() {} });
          assert.equal(followed, 1);
        ''')

    def test_a_phone_gets_the_search_in_a_sheet(self):
        self.run_js(r'''
          start();
          window.matchMedia(GS_FIELD_QUERY).matches = false;   // a phone
          document.fire("keydown", { key: "/", target: main });
          assert(gsSheet && !gsSheet.closed);
          const input = gsSheet.box.input;
          assert.equal(document.activeElement, input);
          input.value = "elv"; input.fire("input"); flushTimers(); await flush();
          await answer();
          assert.equal(gsSheet.box.results.hidden, false);
          assert.equal(gsSheet.box.results.querySelectorAll("h3").length, 3);
          gsSheet.close();
          assert.equal(gsSheet, null);
        ''')

    def test_the_who_are_you_screen_hides_it(self):
        self.run_js(r'''
          start(); hideShell();
          assert.equal(byId("global-search").hidden, true);
          assert(!document.fire("keydown", { key: "/", target: main }).defaultPrevented);
        ''')


if __name__ == "__main__":
    unittest.main()
