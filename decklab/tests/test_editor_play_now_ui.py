"""Review Play-now stand-ins and keep all accepted changes in one editor history step."""
import json
import subprocess
import unittest

from decklab.tests.test_editor_ui import NODE, RUNNER, SETUP as EDITOR, WEB

SETUP = EDITOR + """
  const commander = card("Ghalta, Primal Hunger", "Legendary Creature", 12, {color_identity: ["G"]});
  const mystic = card("Elvish Mystic", "Creature", 1, {color_identity: ["G"]});
  const planned = { Commander: [{qty: 1, name: commander.name, set: "rix", number: "130", card: commander}],
    Deck: [{qty: 1, name: mystic.name, set: "cmm", number: "648", category: "Ramp", card: mystic},
      {qty: 98, name: forest.name, card: forest}] };
  const ed = edit({id: "commander/green", kind: "commander", sections: ["Commander", "Deck", "Sideboard"],
    lists: {target: planned, owned: null}});
  Object.assign(ed, {version: "owned", kind: "commander", space: HOME_SPACE, hasFileList: false, lists: {}});
  ed.base.lists = {}; ed.snap = snapshot(ed);
  const response = (locked) => ({deck_id: ed.id, sha256: ed.sha256,
    rows: [{name: mystic.name, index: 0, section: "Deck", missing: 1, unfilled: locked ? 1 : 0,
      replaceable: true, locked,
      adds: locked ? [] : [{line: {qty: 1, name: elves.name, set: "fdn", number: "227", category: "Ramp", card: elves},
        note: "Close to even: the same job at the same cost."}]}], checks: [], bracket: {minimum: 2, target: 2}});
  const posts = [];
  apiWrite = async (path, body) => { posts.push([path, body]); return response(body.locked.includes(mystic.name)); };
  const dialog = () => document.querySelector("dialog[open]");
  const button = (host, words) => host.querySelectorAll("button").find((n) => n.textContent === words);
  const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
  drawEditor();
  drawEditor = () => {}; drawLines = () => {};
  changed = ({history = true} = {}) => { ed.dirty = isDirty(); if (history) recordHistory(ed); };
  let undoFromToast = null;
  showToast = (_, options) => { undoFromToast = options.undo; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PlayNowUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_lock_review_apply_and_one_undo(self):
        self.run_js("""
          button(ed.dom.page, "Draft from free copies").click(); await settle();
          assert(dialog().textContent.includes("Commander checks"));
          assert(dialog().textContent.includes("the same job at the same cost"));
          same(posts[0], ["/api/deck/play-now/preview", {id: ed.id, sha256: ed.sha256, list: sendList(planned), locked: []}]);
          const lock = () => dialog().querySelector('input[type="checkbox"]');
          lock().checked = true; lock().fire("change");
          assert.equal(button(dialog(), "Use this draft").disabled, true);
          button(dialog(), "Update preview").click(); await settle();
          same(posts[1][1].locked, [mystic.name]);
          assert(dialog().textContent.includes("copy still short"));
          assert.equal(button(dialog(), "Use this draft"), undefined);
          lock().checked = false; lock().fire("change");
          button(dialog(), "Update preview").click(); await settle();
          button(dialog(), "Use this draft").click();
          assert.equal(posts.length, 3);
          assert.equal(ed.history.length, 1);
          const body = draftBody();
          same(Object.keys(body.lists), ["owned"]);
          same(body.lists.owned.Commander, sendList(planned).Commander);
          assert.equal(body.lists.owned.Deck[0].name, elves.name);
          assert.equal(body.lists.owned.Deck[0].category, "Ramp");
          assert(body.prose.substitutes.includes(mystic.name + " | 1 " + elves.name));
          assert.equal(ed.view.lists.target.Deck[0].name, mystic.name);
          undoFromToast();
          assert(noOwnedList());
          assert.equal(draftBody().lists, undefined);
          assert.equal(draftBody().prose, undefined);
        """)

    def test_stale_review_cannot_overwrite_an_editor_change(self):
        self.run_js("""
          button(ed.dom.page, "Draft from free copies").click(); await settle();
          ed.starting = true;
          ed.lists = copyList(planned);
          ed.lists.Deck[1].qty = 97;
          button(dialog(), "Use this draft").click();
          assert(dialog().textContent.includes("The draft changed"));
          assert.equal(ed.lists.Deck[1].qty, 97);
          assert.equal(ed.lists.Deck[0].name, mystic.name);
          assert.equal(ed.history.length, 0);
        """)
