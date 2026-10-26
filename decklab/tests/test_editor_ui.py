"""The editor's page under Node (UI-REVIEW.md WP11): undo history, the write-up in a draft and a save, saving
in place versus the review sheet, the row badges, Stats, Paste's Add and Replace, and the Quick edit's bar.

Runs the real page scripts in tests/fixtures/workspace_ui_runner.js (a small DOM double); nothing is
sent to a server and nothing is saved.
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "workspace_ui_runner.js"
NODE = shutil.which("node")

SETUP = """
  const card = (name, type_line, cmc, extra = {}) => ({name, type_line, cmc, mana_cost: "", color_identity: [],
    oracle_text: "", img: null, img_small: null, ...extra});
  const elves = card("Llanowar Elves", "Creature — Elf Druid", 1, {color_identity: ["G"], oracle_text: "{T}: Add {G}."});
  const bolt = card("Lightning Bolt", "Instant", 1, {color_identity: ["R"]});
  const forest = card("Forest", "Basic Land — Forest", 0);
  const giant = card("Ravenous Giant", "Creature — Giant", 9, {color_identity: ["R"]});
  function edit(extra = {}) {
    const view = {id: "casual/gruul", kind: "casual", title: "Gruul", sha256: "a".repeat(64), sections: ["Deck", "Sideboard"],
      fields: {status: "idea", player: "user"}, field_text: {}, changed_on: "2026-10-05", lists: {target: {Deck: [
        {qty: 4, name: "Llanowar Elves", set: "fdn", number: "227", card: elves},
        {qty: 2, name: "Lightning Bolt", card: bolt},
        {qty: 9, name: "Forest", card: forest}]}, owned: null},
      prose: {notes: "### Plan\\n\\nAttack.", substitutes: ""}, ...extra};
    editor = {mode: "edit", version: "target", profile: "matt", id: view.id, kind: "casual", title: view.title, view,
      sha256: view.sha256, sections: ["Deck", "Sideboard"], hasFileList: true, starting: false, removed: [],
      addSection: "Deck", dom: {}, checkSeq: 0, history: [], snap: null, look: "list", tab: "cards",
      base: {lists: copyList(view.lists.target), fields: pickFields(view.fields), prose: proseOf(view)}};
    editor.lists = copyList(editor.base.lists);
    editor.fields = {...editor.base.fields};
    editor.prose = {...editor.base.prose};
    editor.snap = snapshot(editor);
    return editor;
  }
  state.profile = {id: "matt", plays_as: "user"};
  const real = {drawBar, changed: (typeof changedOriginal === "function") ? changedOriginal : null};
  drawStats = () => {}; drawBar = () => {}; drawDetailsSummary = () => {}; scheduleCheck = () => {};
  queueDraft = () => {}; drawKitNeeds = () => {}; toast = () => {};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EditorPageTests(unittest.TestCase):
    def run_js(self, scenario, viewport=None):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, False, viewport]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_keyboard_pan_keeps_save_above_the_visible_bottom(self):
        self.run_js("""
          edit();
          const style = document.documentElement.style, vv = window.visualViewport;
          const bottom = () => parseFloat(style['--editor-keyboard-bottom']);
          assert.equal(style['--vvh'], '695px');
          assert.equal(bottom(), 0);
          // A quantity field, rather than the Add search, owns the keyboard.
          const quantity = el('input'); document.body.append(quantity); quantity.focus();
          Object.assign(vv, {height: 391, offsetTop: 304}); vv.fire('resize');
          assert.equal(style['--vvh'], '391px');
          assert.equal(bottom(), 0);
          assert.equal(document.body.classList.contains('keyboard-up'), false);
          // Safari pans without resizing after the real 52 -> 53 input. The
          // measured Save bottom was 461.65625px with 391px actually visible.
          vv.offsetTop = 225.34375; vv.fire('scroll');
          assert.equal(bottom(), 78.65625);
          assert.equal(461.65625 - bottom(), 383);
          assert.equal(style['--vvh'], '391px');
          // Search keeps its existing keyboard-only hiding behavior.
          editor.ac = {input: quantity};
          vv.fire('resize');
          assert.equal(document.body.classList.contains('keyboard-up'), true);
          Object.assign(vv, {height: 695, offsetTop: 0}); vv.fire('resize');
          assert.equal(style['--vvh'], '695px');
          assert.equal(bottom(), 0);
          assert.equal(document.body.classList.contains('keyboard-up'), false);
        """, viewport={"innerWidth": 393, "innerHeight": 695, "coarse": True,
                      "visual": {"width": 393, "height": 695}})

    def test_pinch_zoom_and_a_desktop_resize_do_not_lift_the_editor_bar(self):
        self.run_js("""
          edit();
          const style = document.documentElement.style, vv = window.visualViewport;
          Object.assign(vv, {width: 196.5, height: 347.5, scale: 2, offsetTop: 100});
          vv.fire('resize'); vv.fire('scroll');
          assert.equal(style['--vvh'], '695px');
          assert.equal(style['--editor-keyboard-bottom'], '0px');
          // A fine-pointer desktop window can be short without having a keyboard.
          window.matchMedia('(pointer: coarse)').matches = false;
          Object.assign(vv, {width: 393, height: 391, scale: 1, offsetTop: 225.34375});
          vv.fire('resize'); vv.fire('scroll');
          assert.equal(style['--vvh'], '391px');
          assert.equal(style['--editor-keyboard-bottom'], '0px');
        """, viewport={"innerWidth": 393, "innerHeight": 695, "coarse": True,
                      "visual": {"width": 393, "height": 695}})

    def test_the_side_panel_folds_on_a_tablet_once_the_deck_has_cards(self):
        # UI review round 2: below 1,000 px the Add/Stats/Checks panel came before the list, so the deck began
        # under the fold. With cards it starts folded to its tabs; a tab or Add cards opens it, Hide folds it.
        self.run_js("""
          addPart = () => el("div");
          edit(); editor.ac = null; editor.dom.check = el("section");
          const panel = sidePanel();
          editor.dom.page = el("div", {}, panel); main.append(editor.dom.page); mountEditorPanes();
          assert(panel.classList.contains("is-folded"));
          assert.equal(editor.dom.sideFold.textContent, "Show");
          assert.equal(editor.dom.sideFold.getAttribute("aria-expanded"), "false");
          setSide("stats");
          assert(!panel.classList.contains("is-folded"));
          assert.equal(editor.dom.sideFold.textContent, "Hide");
          editor.dom.sideFold.click();
          assert(panel.classList.contains("is-folded"));
          focusSearch();
          assert(!panel.classList.contains("is-folded"));
          assert.equal(editor.side, "add");
          // An empty deck starts open: adding cards is the first thing to do.
          edit(); editor.lists = {Deck: []}; editor.dom.check = el("section");
          assert(!sidePanel().classList.contains("is-folded"));
        """)

    def test_ctrl_z_takes_back_each_change(self):
        self.run_js("""
          edit();
          drawEditor = () => {}; drawLines = () => {};
          changed = (opts) => { editor.dirty = isDirty(); if (!opts || opts.history !== false) recordHistory(editor); };
          editor.lists.Deck[0].qty = 3; changed({list: false});
          editor.fields.status = "building"; changed({list: false});
          assert.equal(editor.history.length, 2);
          assert.equal(undoLast(), true);
          assert.equal(editor.fields.status, "idea");
          assert.equal(editor.lists.Deck.find(l => l.name === "Llanowar Elves").qty, 3);
          assert.equal(undoLast(), true);
          assert.equal(editor.lists.Deck.find(l => l.name === "Llanowar Elves").qty, 4);
          assert.equal(undoLast(), false);
          assert.equal(isDirty(), false);
          // Ctrl+Z in a text box is the box's own; elsewhere it's the editor's.
          editor.lists.Deck[0].qty = 1; changed({list: false});
          const typed = document.fire("keydown", {key: "z", ctrlKey: true, target: {tagName: "TEXTAREA"}});
          assert.equal(typed.defaultPrevented, false);
          editor.dom = {x: 1};
          const event = document.fire("keydown", {key: "z", ctrlKey: true, target: document.body});
          assert.equal(event.defaultPrevented, true);
          assert.equal(editor.lists.Deck.find(l => l.name === "Llanowar Elves").qty, 4);
        """)

    def test_the_write_up_goes_in_the_draft_and_the_save(self):
        self.run_js("""
          edit();
          assert.equal(isDirty(), false);
          same(changedProse(), {});
          editor.prose.notes = "### Plan\\n\\nAttack early.\\n\\n";
          same(changedProse(), {notes: "### Plan\\n\\nAttack early."});
          assert.equal(isDirty(), true);
          editor.markCurrent = true;
          const body = draftBody();
          same(body.prose, {notes: "### Plan\\n\\nAttack early."});
          assert.equal(body.mark_current, true);
          assert.equal(body.lists, undefined);                 // the list didn't change
          // A draft keeps them, and a newer deck keeps this write-up with a note when it changed there too.
          const mine = {lists: keepList(editor.lists), fields: editor.fields, prose: editor.prose, markCurrent: true};
          const latest = {...editor.view, sha256: "b".repeat(64), prose: {notes: "Theirs.", substitutes: ""}};
          const notes = rebase(editor, latest, mine, editor.base);
          assert.equal(editor.prose.notes, "### Plan\\n\\nAttack early.\\n\\n");
          assert.ok(notes.some(n => n.includes("Notes write-up changed")));
          assert.equal(editor.markCurrent, true);
        """)

    def test_save_saves_in_place_unless_something_blocks_it(self):
        self.run_js("""
          edit();
          const did = [];
          doSave = async (sheet, button, opts) => { did.push(["save", sheet, !!opts.viewAfter]); };
          reviewSave = (answer) => { did.push(["review", answer ? answer.blocks.length : null]); };
          const ok = {blocks: [], warnings: [], file_changed: false, changes: {decklist: true, fields: [], prose: [], marker: false}};
          runCheck = async () => ok;
          await saveNow();
          same(did.pop(), ["save", null, false]);
          await saveNow({viewAfter: true});
          same(did.pop(), ["save", null, true]);
          runCheck = async () => ({...ok, blocks: [{problem: "x"}]});
          await saveNow();
          same(did.pop(), ["review", 1]);
          runCheck = async () => ({...ok, file_changed: true});
          await saveNow();
          same(did.pop(), ["review", 0]);
          runCheck = async () => null;
          await saveNow();
          same(did.pop(), ["review", null]);
          const toasts = []; toast = (t) => toasts.push(t);
          runCheck = async () => ({...ok, changes: {decklist: false, fields: [], prose: [], marker: false}});
          await saveNow();
          assert.equal(did.length, 0);
          assert.ok(toasts[0].startsWith("Nothing to save"));
          editor.readOnly = true;
          runCheck = async () => ok;
          await saveNow();
          assert.equal(did.length, 0);                          // someone else's deck is never saved
        """)

    def test_one_badge_only_when_a_card_isnt_simply_here(self):
        self.run_js("""
          edit();
          editor.dom.lines = el("div");
          for (const line of editor.lists.Deck) editor.dom.lines.append(lineRow(line, "Deck"));
          const rows = editor.dom.lines.querySelectorAll(".edit-row");
          const supply = (name, extra) => ({name, need: 1, owned: 4, on_the_way: 0, on_the_way_from: [], in_use_elsewhere: [],
            missing: 0, ...extra});
          showRowAvailability({rows: [
            supply("Llanowar Elves", {need: 4, owned: 2, missing: 2, in_use_elsewhere: [["Elf Ball", 2]]}),
            supply("Lightning Bolt", {need: 2, owned: 2})]});
          const badge = (row) => row.querySelector(".edit-availability");
          assert.equal(badge(rows[0]).textContent, "2 in other decks");
          assert.ok(badge(rows[0]).title.includes("2 in use in Elf Ball"));
          assert.equal(badge(rows[1]), null);                   // owned and free: nothing
          assert.equal(badge(rows[2]), null);                   // basics aren't counted
          showRowAvailability({rows: [supply("Lightning Bolt", {need: 2, owned: 2, on_the_way: 1,
            on_the_way_from: [["order x", 1]]})]});
          assert.equal(badge(rows[1]).textContent, "On the way");
          assert.equal(badge(rows[0]), null);
          showRowAvailability(null);
          assert.equal(editor.dom.lines.querySelectorAll(".edit-availability").length, 0);
          // "−" on a line of 1 removes it, where it was, with Undo.
          const boltLine = editor.lists.Deck.find(l => l.name === "Lightning Bolt");
          boltLine.qty = 1;
          changed = () => {};
          stepQty(boltLine.uid, -1);
          assert.equal(editor.lists.Deck.some(l => l.name === "Lightning Bolt"), false);
          assert.equal(editor.removed.length, 1);
          assert.ok(editor.dom.lines.textContent.includes("Removed"));
          undoRemove(boltLine.uid);
          assert.equal(editor.lists.Deck.find(l => l.name === "Lightning Bolt").qty, 1);
        """)

    def test_stats_count_the_curve_lands_and_sources(self):
        self.run_js("""
          edit();
          editor.lists.Deck.push(newLine({qty: 1, name: "Ravenous Giant", card: giant}));
          const s = listStats();
          same(s.curve, [0, 6, 0, 0, 0, 0, 0, 1]);              // 7+ is the last column
          assert.equal(s.lands, 9);
          assert.equal(s.spells, 7);
          assert.equal(s.sources.get("G"), 13);                 // 9 Forests and 4 Llanowar Elves
          same(s.colours, ["R", "G"]);
          same([...manaSources(card("Signet", "Artifact", 2, {oracle_text: "{1}, {T}: Add {R}{G}."}))], ["R", "G"]);
          same([...manaSources(card("Prism", "Artifact", 2, {oracle_text: "{T}: Add one mana of any color."}))].length, 5);
        """)

    def test_paste_adds_or_replaces_and_shows_the_difference(self):
        self.run_js("""
          edit();
          const pasted = {Deck: [{qty: 2, name: "Lightning Bolt", card: bolt}, {qty: 1, name: "Ravenous Giant", card: giant}]};
          const added = mergedLists(editor.lists, pasted);
          assert.equal(added.Deck.find(l => l.name === "Lightning Bolt").qty, 4);
          assert.equal(added.Deck.length, 4);
          same(listChanges(editor.lists, added).map(changeWords), ["Lightning Bolt: 2 → 4", "Added 1 Ravenous Giant"]);
          const replaced = replacedLists(pasted);
          same(listChanges(editor.lists, replaced).map(changeKind).sort(), ["added", "removed", "removed"]);
          changed = () => {};
          replaceLines(pasted);
          same(editor.lists.Deck.map(l => l.name).sort(), ["Lightning Bolt", "Ravenous Giant"]);
          // A casual deck's pasted commander goes into the Deck.
          same(Object.keys(mergedLists({}, {Commander: [{qty: 1, name: "Ravenous Giant", card: giant}]})), ["Deck"]);
        """)

    def test_the_quick_edit_bar_has_add_cards_and_one_save(self):
        self.run_js("""
          edit();
          drawSideTabs = () => {};
          editor.quick = true;
          editor.dom.bar = el("div");
          real.drawBar();
          const bar = editor.dom.bar;
          assert.ok(bar.querySelector(".bar-add"));
          assert.equal(bar.querySelectorAll(".bar-save").length, 1);
          assert.equal(bar.querySelector(".bar-save-more"), null);   // no "Save & view deck" menu on a phone
          assert.equal(bar.querySelector(".vt-test-row"), null);
          edit();
          editor.dom.bar = el("div");
          real.drawBar();
          assert.ok(editor.dom.bar.querySelector(".bar-add-jump"));        // a jump to the Add panel (hidden from 1,100 px)
          assert.ok(editor.dom.bar.querySelector(".bar-save-more"));
          editor.readOnly = true; editor.dom.bar = el("div"); real.drawBar();
          assert.equal(editor.dom.bar.querySelector(".bar-save"), null);
        """)

    def test_save_waits_for_a_superseded_check_and_blocks_a_second_save(self):
        self.run_js("""
          edit();
          const did = [];
          let release;
          doSave = (sheet, button, opts) => new Promise((resolve) => { did.push("save"); release = resolve; });
          reviewSave = (answer) => { did.push("review"); };
          const ok = {blocks: [], warnings: [], file_changed: false, changes: {decklist: true, fields: [], prose: [], marker: false}};
          // The first check is replaced by a newer one (a quantity typed meanwhile): check again, then save.
          let calls = 0;
          runCheck = async (ed, info) => { calls += 1; if (calls === 1) { info.superseded = true; return null; } return ok; };
          const first = saveNow();
          for (let i = 0; i < 10; i += 1) await Promise.resolve();
          same(did, ["save"]);
          assert.equal(calls, 2);
          assert.equal(editor.saving, true);                    // still saving while the POST is out
          await saveNow();                                      // a second Ctrl+S meanwhile does nothing
          same(did, ["save"]);
          release();
          await first;
          assert.equal(editor.saving, false);
          // A failed check (not superseded) goes to the review, without asking again.
          calls = 0;
          runCheck = async () => { calls += 1; return null; };
          await saveNow();
          same(did, ["save", "review"]);
          assert.equal(calls, 1);
        """)

    def test_busy_buttons_keep_what_they_held(self):
        self.run_js("""
          const dot = el("span", {class: "dot"});
          const button = el("button", {}, "Save", dot);
          button.childNodes = button.children;                  // the DOM double's children are its nodes
          busy(button, "Saving…");
          busy(button, "Saving…");                              // busy again: the first contents still come back
          assert.equal(button.dataset.busy, "1");
          unbusy(button);
          assert.ok(button.querySelector(".dot"));
          assert.equal(button.textContent, "Save");
          assert.equal(button.dataset.busy, undefined);
        """)

    def test_ctrl_s_never_reaches_the_browser_while_a_sheet_is_open(self):
        self.run_js("""
          edit();
          editor.dom = {x: 1};
          let saves = 0; saveNow = () => { saves += 1; };
          const sheet = el("dialog", {open: ""}); document.body.append(sheet);
          const e = document.fire("keydown", {key: "s", ctrlKey: true, target: document.body});
          assert.equal(e.defaultPrevented, true);
          assert.equal(saves, 0);
          sheet.remove();
          document.fire("keydown", {key: "s", ctrlKey: true, target: document.body});
          assert.equal(saves, 1);
        """)

    def test_added_belongs_to_its_search_and_shift_enter_counts_before_results(self):
        self.run_js("""
          edit();
          drawAddTo = () => {}; changed = () => {}; syncSections = () => {};
          editor.dom.lines = null;
          main.append(cardSearch()); const ac = editor.ac;
          const found = (name) => ({...card(name, "Instant", 1), default: null, have: {owned: 0, on_the_way: 0}, aud: null});
          ac.items = [found("Lightning Bolt"), found("Bolt Bend")]; ac.query = "bolt"; ac.input.value = "bolt"; ac.active = 0;
          pick(ac, 0);
          assert.ok(ac.list.textContent.includes("Added ✓ (now 3)"));
          // The next search's first result isn't "Added".
          ac.input.value = "elv"; ac.input.fire("input");
          ac.items = [found("Elvish Mystic")]; ac.query = "elv"; drawOptions(ac);
          assert.equal(ac.list.textContent.includes("Added"), false);
          // Shift+Enter typed before the answer adds 4.
          ac.items = []; ac.query = ""; ac.input.value = "ravenous giant";
          let url = null;
          api = async (u) => { url = u; return {cards: [found("Ravenous Giant")], did_you_mean: [], pages: 1}; };
          ac.input.fire("keydown", {key: "Enter", shiftKey: true});
          for (let i = 0; i < 10; i += 1) await Promise.resolve();
          assert.ok(url.startsWith("/api/deck/find?"));
          assert.equal(editor.lists.Deck.find(l => l.name === "Ravenous Giant").qty, 4);
        """)

    def test_the_paste_toasts_undo_takes_back_only_the_paste(self):
        self.run_js("""
          edit();
          drawEditor = () => {}; drawLines = () => {}; syncSections = () => {};
          changed = (opts) => { editor.dirty = isDirty(); if (!opts || opts.history !== false) recordHistory(editor); };
          let undo = null;
          showToast = (message, opts) => { undo = opts.undo; return {close() {}}; };
          const toasts = []; toast = (t) => toasts.push(t);
          // As openPaste's apply does it.
          const paste = () => {
            mergeLines({Deck: [{qty: 1, name: "Ravenous Giant", card: giant}]});
            const ed = editor, before = ed.history[ed.history.length - 1], after = ed.snap;
            showToast("Added 1 card.", {undo: () => {
              if (editor === ed && ed.snap === after && ed.history[ed.history.length - 1] === before) undoLast();
              else toast("Other changes came after the paste");
            }});
          };
          paste();
          editor.fields.status = "building"; changed({list: false});      // a later change
          undo();
          assert.ok(toasts.pop().startsWith("Other changes"));
          assert.ok(editor.lists.Deck.some(l => l.name === "Ravenous Giant"));
          assert.equal(editor.fields.status, "building");
          undoLast(); undoLast();                               // the later change, then the paste
          assert.equal(editor.lists.Deck.some(l => l.name === "Ravenous Giant"), false);
          paste();
          undo();
          assert.equal(editor.lists.Deck.some(l => l.name === "Ravenous Giant"), false);
        """)

    def test_my_collection_uses_the_spells_colours_not_any_colour_lands(self):
        self.run_js("""
          edit();
          editor.lists.Deck.push(newLine({qty: 1, name: "Command Tower",
            card: card("Command Tower", "Land", 0, {oracle_text: "{T}: Add one mana of any color in your commander's color identity."})}));
          same(listStats().colours.length, 5);                  // sources: any colour
          same(listStats().identity, ["R", "G"]);               // the deck's colours: its spells'
          same(deckColours(), ["R", "G"]);
        """)

    def test_an_empty_section_hides_its_zero_and_offers_its_one_action(self):
        self.run_js("""
          edit();
          assert.equal(countWords(0), "");
          assert.equal(countWords(3), "3");
          editor.kind = "commander";
          const part = emptyPart("Commander");
          assert.ok(part.textContent.includes("No commander yet"));
          assert.ok(part.querySelector("button"));
        """)

    def test_a_new_deck_has_no_size_warning_until_it_has_cards(self):
        self.run_js("""
          editor = {mode: "new", fields: {kind: "casual", title: "", status: "idea"}, lists: {Deck: []}, sections: ["Deck", "Sideboard"],
            addSection: "Deck", dom: {}, checkSeq: 0, base: {lists: {}, fields: {}}, removed: []};
          assert.equal(emptyList(), true);
          editor.lists.Deck.push(newLine({qty: 4, name: "Lightning Bolt", card: bolt}));
          assert.equal(emptyList(), false);
        """)


if __name__ == "__main__":
    unittest.main()
