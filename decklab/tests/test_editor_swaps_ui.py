"""The editor's stand-ins for a missing card (E2-S07, editor-swaps.js) under Node: when a line offers them,
the sheet and "Use n", the swap into the Play-now list with its Substitutes note (once), one Undo for both,
a late answer dropped, and the deck page's swap= and tab=notes links.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js (a small DOM double); nothing is sent
to a server and nothing is saved.
"""
import json
import subprocess
import unittest

from decklab.tests.test_editor_ui import NODE, RUNNER, SETUP as EDITOR, WEB

SETUP = EDITOR + """
  const shock = card("Shock", "Instant", 1, {color_identity: ["R"]});
  const note = (text) => ({severity: 0, words: "Close to even", text});
  const shockOption = {name: "Shock", card: shock, default: {set: "m21", number: "159", finish: "nonfoil"},
    free: 3, here: 2, max_qty: 2, note: note("Close to even: the same job at the same cost."), basic: false, aud: 0.2};
  const answer = {deck_id: "casual/gruul", version: "owned", kind: "casual", colours: ["G", "R"],
    rate: 1.5, rate_date: "2026-10-19", price_date: "2026-10-19", warnings: [],
    cards: [{name: "Lightning Bolt", section: "Deck", missing: 2, aud_each: 1.5, card: bolt, type: "instant",
      colours: ["R"], mv: 1, in_list: 2, candidates: [shockOption], more: 0}]};
  function playNow(substitutes = "") {
    edit();
    editor.version = "owned";
    editor.lists = copyList({Deck: [{qty: 2, name: "Lightning Bolt", card: bolt}, {qty: 9, name: "Forest", card: forest}],
      Sideboard: [{qty: 1, name: "Ravenous Giant", card: giant}]});
    editor.prose = {notes: "", substitutes};
    editor.snap = snapshot(editor);
    editor.check = {availability: {owned: {rows: [{name: "Lightning Bolt", missing: 2}, {name: "Ravenous Giant", missing: 1},
      {name: "Llanowar Elves", missing: 0}]}}};
    editor.checkError = null;
    return editor;
  }
  const line = (name) => Object.values(editor.lists).flat().find((l) => l.name === name);
  drawEditor = () => {}; drawLines = () => {}; drawMain = () => {};
  changed = (opts) => { editor.dirty = isDirty(); if (!opts || opts.history !== false) recordHistory(editor); };
  let toastUndo = null; const toasts = [];
  showToast = (message, opts) => { toasts.push(message); toastUndo = opts && opts.undo; return {close() {}}; };
  toast = (t) => toasts.push(t);
  const posts = [];
  apiWrite = async (path, body) => { posts.push([path, body]); return answer; };
  const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
  const dialogs = () => document.body.querySelectorAll("dialog");
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorSwapsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, False, None]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_only_short_deck_and_sideboard_lines_of_the_play_now_list(self):
        self.run_js("""
          playNow();
          assert.equal(swapsAvailableFor(line("Lightning Bolt")), true);
          assert.equal(swapsAvailableFor(line("Ravenous Giant")), true);
          assert.equal(swapsAvailableFor(line("Forest")), false);
          editor.lists.Commander = copyList({Commander: [{qty: 1, name: "Lightning Bolt", card: bolt}]}).Commander;
          assert.equal(swapsAvailableFor(editor.lists.Commander[0]), false);
          // The ⋯ menu has the item only then.
          let items = null; openMenu = (anchor, list) => { items = list; };
          rowMenuButton(line("Lightning Bolt")).click();
          assert(items.some((i) => i && i.text === "Stand-ins…"));
          rowMenuButton(line("Forest")).click();
          assert(!items.some((i) => i && i.text === "Stand-ins…"));
          // Not on the Planned list, nor while the check hasn't answered, nor without the collection.
          editor.version = "target";
          assert.equal(swapsAvailableFor(line("Lightning Bolt")), false);
          playNow(); editor.check = null;
          assert.equal(swapsAvailableFor(line("Lightning Bolt")), false);
          playNow(); state.may = {see_inventory: ["user2"]};
          assert.equal(swapsAvailableFor(line("Lightning Bolt")), false);
          state.may = null;
        """)

    def test_the_sheet_and_use(self):
        self.run_js("""
          playNow();
          await openSwapSheet(line("Lightning Bolt").uid);
          assert.equal(posts.length, 1);
          assert.equal(posts[0][0], "/api/deck/swaps");
          same(posts[0][1].card, "Lightning Bolt");
          same(posts[0][1].list.Deck.map((l) => [l.qty, l.name]), [[2, "Lightning Bolt"], [9, "Forest"]]);
          const [sheet] = dialogs();
          assert(sheet.textContent.includes("2 copies missing · Instant, red, mana value 0–2"));
          assert(sheet.textContent.includes("Buying it: about A$1.50 each (prices of 2026-10-19)."));
          assert(sheet.textContent.includes("1 mana · 2 here, 1 on the way"));
          assert(sheet.textContent.includes("Close to even: the same job at the same cost."));
          const use = sheet.querySelectorAll("button").find((b) => b.textContent === "Use 2");
          assert.equal(use.getAttribute("class"), "btn swap-use");        // no primary: one per view
          use.click();
          assert.equal(dialogs().length, 0);
          assert.equal(line("Lightning Bolt"), undefined);
          same([line("Shock").qty, line("Shock").set, line("Shock").number], [2, "m21", "159"]);
          assert(editor.lists.Deck.includes(line("Shock")));
          assert.equal(editor.prose.substitutes, "| Buy (Planned list) | Play now | What the swap costs |\\n|---|---|---|\\n" +
            "| 2 Lightning Bolt | 2 Shock | Close to even: the same job at the same cost. |");
          assert.equal(toasts.pop(), "Shock is in for 2 Lightning Bolt. Note added to Substitutes.");
          // One step: the toast's Undo takes back the list and the note together.
          toastUndo();
          assert.equal(line("Lightning Bolt").qty, 2);
          assert.equal(line("Shock"), undefined);
          assert.equal(editor.prose.substitutes, "");
        """)

    def test_fewer_copies_and_a_line_already_there(self):
        self.run_js("""
          playNow("Some words first.");
          editor.lists.Deck.push(newLine({qty: 1, name: "Shock", set: "m21", number: "159", card: shock}));
          applySwap(line("Lightning Bolt").uid, answer.cards[0], shockOption, 1);
          same([line("Lightning Bolt").qty, line("Shock").qty], [1, 2]);
          assert.equal(editor.prose.substitutes, "Some words first.\\n\\n- **1 Lightning Bolt → 1 Shock:** Close to even: the same job at the same cost.");
          // The second pick for the same card adds no second note, and says so.
          applySwap(line("Lightning Bolt").uid, answer.cards[0], {...shockOption, name: "Spark", card: shock, default: null}, 1);
          assert.equal(line("Lightning Bolt"), undefined);
          assert.equal(editor.prose.substitutes.split("Lightning Bolt").length, 2);
          assert(toasts.pop().endsWith("already has a note in Substitutes; check it still fits (it doesn't name Spark)."));
          // After another change, the toast's Undo leaves things as they are (Ctrl+Z steps back).
          editor.fields.status = "building"; changed({list: false});
          toastUndo();
          assert.equal(line("Spark").qty, 1);
        """)

    def test_the_note_goes_in_the_sections_own_style(self):
        self.run_js("""
          const swap = {outQty: 2, outName: "Glorybringer", inQty: 2, inName: "Savage Ventmaw", note: "Weaker."};
          const table = "| Buy | Play | Note |\\n|---|---|---|\\n| 2 A | 2 B | ok |\\n\\nMore text.";
          assert.equal(withSwapNote(table, swap),
            "| Buy | Play | Note |\\n|---|---|---|\\n| 2 A | 2 B | ok |\\n| 2 Glorybringer | 2 Savage Ventmaw | Weaker. |\\n\\nMore text.");
          // A table's headings say where each part goes (Gandalf and the Valley's four columns).
          const four = "| Buy (target list) | ~A$ est. | Stand-in | What the swap costs |\\n|---|---|---|---|";
          assert.equal(withSwapNote(four, swap), four + "\\n| 2 Glorybringer |   | 2 Savage Ventmaw | Weaker. |");
          // No heading says where the stand-in goes: a bullet, never cells under the wrong headings.
          const unknown = "| A | B | C | D |\\n|---|---|---|---|";
          assert.equal(withSwapNote(unknown, swap), unknown + "\\n\\n- **2 Glorybringer → 2 Savage Ventmaw:** Weaker.");
          assert.equal(withSwapNote("- **1 X → 1 Y:** fine.", swap),
            "- **1 X → 1 Y:** fine.\\n- **2 Glorybringer → 2 Savage Ventmaw:** Weaker.");
          assert.equal(withSwapNote("  \\n", swap).split("\\n")[0], "| Buy (Planned list) | Play now | What the swap costs |");
          // The same whole-word rule as the server's find_note.
          assert.equal(noteNaming("Boltwing Marauder is not it.", "Bolt"), null);
          assert.equal(noteNaming("|---|---|\\n| 2 Bolt | 2 Shock | x |", "Bolt"), "| 2 Bolt | 2 Shock | x |");
          assert.equal(noteNaming("Fire is fine.", "Fire // Ice"), "Fire is fine.");
          // A longer card name of the lists that names it ("Anger of the Gods" for Anger) doesn't count.
          const prose = "- **2 Anger of the Gods → 2 Pyroclasm:** old\\n- **2 Anger → 2 Slagstorm:** x";
          assert.equal(noteNaming(prose, "Anger", ["Anger", "Anger of the Gods"]), "- **2 Anger → 2 Slagstorm:** x");
          assert.equal(noteNaming(prose, "Anger"), "- **2 Anger of the Gods → 2 Pyroclasm:** old");
        """)

    def test_a_late_answer_is_dropped(self):
        self.run_js("""
          playNow();
          let reply; apiWrite = () => new Promise((resolve) => { reply = resolve; });
          const opening = openSwapSheet(line("Lightning Bolt").uid);
          const [sheet] = dialogs();
          playNow();                                  // another editor (a reload, another person)
          reply(answer); await opening;
          assert(!sheet.textContent.includes("Use 2"));
          assert(sheet.textContent.includes("Looking through your cards"));
        """)

    def test_no_stand_in_offers_my_collection(self):
        self.run_js("""
          playNow();
          apiWrite = async () => ({...answer, cards: [{...answer.cards[0], candidates: []}]});
          let searched = 0; focusSearch = () => { searched += 1; editor.ac = {colors: new Set(), mode: "search"}; };
          refilter = (ac) => { ac.refiltered = true; }; drawAddTo = () => {};
          await openSwapSheet(line("Lightning Bolt").uid);
          const [sheet] = dialogs();
          assert(sheet.textContent.includes("No free card fits"));
          sheet.querySelectorAll("button").find((b) => b.textContent === "Search My collection").click();
          same([searched, editor.ac.mode, [...editor.ac.colors], editor.ac.type, editor.ac.refiltered], [1, "collection", ["R"], "instant", true]);
        """)

    def test_the_deck_pages_links(self):
        self.run_js("""
          playNow(); editor.hasFileList = false; editor.starting = false;
          editor.view.lists.target = {Deck: [{qty: 2, name: "Lightning Bolt", card: bolt}]};
          let opened = []; openSwapSheet = (uid) => opened.push(uid);
          openSwapsFromRoute(new URLSearchParams("id=casual/gruul&v=owned&swap=Lightning Bolt"), "casual/gruul");
          assert.equal(editor.starting, true);                  // the Play-now list started from the Planned list
          same(opened, [line("Lightning Bolt").uid]);
          playNow();
          openSwapsFromRoute(new URLSearchParams("id=casual/gruul&v=owned&tab=notes"), "casual/gruul");
          same([editor.tab, opened.length], ["notes", 1]);
          openSwapsFromRoute(new URLSearchParams("id=casual/gruul&v=owned&swap=Nothing"), "casual/gruul");
          assert(toasts.pop().startsWith("Nothing isn't in the"));
          openSwapsFromRoute(new URLSearchParams("id=casual/other&swap=Lightning Bolt"), "casual/other");
          same(opened.length, 1);
        """)
