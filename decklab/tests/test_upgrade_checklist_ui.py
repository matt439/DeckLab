"""Personal checklist interactions through the real Decks entry point, with synthetic API answers."""
import json
import subprocess
import unittest

from decklab.tests.test_library_ui import SHELF
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = SHELF + r"""
  as("user2", MAY.user2);
  location.hash = "#/library";
  window.matchMedia("(min-width: 600px)").matches = false;
  const empty = {warnings: [], halves: [], decks: [], own_collection_empty: true};
  const path = "/api/profiles/user2/deck-checklist";
  let saved = {revision: 0, title: "", rows: []};
  const reads = [], writes = [];
  api = async requested => {
    assert.equal(requested, path);
    reads.push(requested);
    return structuredClone(saved);
  };
  apiWrite = async (requested, body) => {
    assert.equal(requested, path);
    writes.push(structuredClone(body));
    assert.equal(body.expect, saved.revision);
    saved = {revision: saved.revision + 1, title: body.title, rows: structuredClone(body.rows)};
    return structuredClone(saved);
  };
  function library(data = empty) {
    clear(main);
    drawLibrary(data, libraryFilters(new URLSearchParams()));
    const trigger = button(main, "Check cards for a deck");
    assert(trigger, "Missing checklist on Decks");
    return trigger;
  }
  async function openFrom(trigger) {
    trigger.click();
    await flush();
    const sheet = openDialog();
    assert(sheet?.isConnected, "Checklist did not open");
    return sheet;
  }
  function enter(control, value) {
    assert(control, "Missing input");
    control.value = value;
    control.fire("input");
  }
  function paste(sheet, lines) {
    enter(sheet.querySelector("textarea"), lines);
    button(sheet, "Add cards").click();
  }
  function choose(sheet, index, value) {
    const field = sheet.querySelectorAll("select")[index];
    assert(field, "Missing copy " + index);
    field.value = value;
    field.fire("change");
  }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class UpgradeChecklistTests(unittest.TestCase):
    def run_js(self, scenario):
        viewport = {"innerWidth": 320, "innerHeight": 640, "coarse": True}
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True, viewport]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_empty_member_library_to_shop_list_save_and_reopen(self):
        self.run_js(r"""
          const trigger = library();
          assert.deepEqual(reads, []);       // The private list is loaded only when opened.
          let sheet = await openFrom(trigger);
          same(reads, [path]);
          assert.equal(sheet.querySelectorAll("select").length, 0);
          enter(sheet.querySelector("input"), "Friday upgrades");
          paste(sheet, "  Alpha  \nBeta\nAlpha\n \nalpha\nGamma");
          same(sheet.querySelectorAll("select").map(field => field.value), Array(5).fill("check"));
          choose(sheet, 0, "buy");
          choose(sheet, 1, "set_aside");
          choose(sheet, 3, "buy");
          const copied = [];
          navigator.clipboard = {writeText: async text => copied.push(text)};
          button(sheet, "Copy buy list").click(); await flush();
          same(copied, ["2 Alpha"]);
          assert.equal(writes.length, 0, "Local checklist actions wrote before Save");
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(writes.length, 1);
          assert.equal(writes[0].expect, 0);
          assert.equal(saved.title, "Friday upgrades");
          same(saved.rows, [
            {name:"Alpha", choice:"buy"}, {name:"Beta", choice:"set_aside"},
            {name:"Alpha", choice:"check"}, {name:"alpha", choice:"buy"}, {name:"Gamma", choice:"check"},
          ]);
          colCloseSheets();
          sheet = await openFrom(trigger);
          assert.equal(sheet.querySelector("input").value, "Friday upgrades");
          same(sheet.querySelectorAll("select").map(field => field.value), ["buy", "set_aside", "check", "buy", "check"]);
          same(reads, [path, path]);
          // The browser can refuse clipboard access on a LAN. Expose a selectable Buy-only list.
          navigator.clipboard.writeText = async () => { throw new Error("No clipboard"); };
          button(sheet, "Copy buy list").click(); await flush();
          const manual = sheet.querySelectorAll("textarea").find(field => field.value === "2 Alpha");
          assert(manual && manual.selected);
        """)

    def test_late_private_reads_and_detached_controls_cannot_follow_a_profile_switch(self):
        self.run_js(r"""
          const trigger = library();
          let resolve;
          api = requested => {
            assert.equal(requested, path);
            return new Promise(done => { resolve = done; });
          };
          trigger.click(); await flush();
          const old = openDialog();
          assert(old?.isConnected);
          drawWho();
          assert(!old.isConnected);
          resolve({revision: 4, title: "Private title", rows: [{name:"Private card", choice:"buy"}]});
          await flush();
          assert(!document.body.textContent.includes("Private card"));
          assert(!old.textContent.includes("Private card"));
          trigger.click(); await flush();
          assert(!openDialog());
          assert.equal(writes.length, 0);
        """)

    def test_cold_card_catalogue_does_not_block_or_interrupt_a_members_checklist(self):
        self.run_js(r"""
          // The DOM double has manual timers. Fire the real card-data countdown while the sheet is open.
          const timers = new Map();
          let id = 0, deckReads = 0;
          globalThis.setInterval = tick => { timers.set(++id, tick); return id; };
          globalThis.clearInterval = key => timers.delete(key);
          noteVisit = () => {}; showFooter = () => {};
          const readChecklist = api;
          api = async requested => {
            if (requested !== "/api/decks") return readChecklist(requested);
            if (++deckReads === 1) throw new ApiError(503, "Card data is being downloaded.", {reason:"card_data"});
            return empty;
          };
          route(); await flush();
          assert(main.textContent.includes("The card data isn't ready yet"));
          const cold = button(main, "Check cards for a deck");
          assert(cold, "No checklist on the first-start card download screen");
          const sheet = await openFrom(cold);
          paste(sheet, "Alpha"); choose(sheet, 0, "buy");
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(deckReads, 1, "Saving a bare card name waited for a usable catalogue");
          same(saved.rows, [{name:"Alpha", choice:"buy"}]);
          enter(sheet.querySelector("textarea"), "Beta");
          for (let i = 0; i < RETRY_SECONDS; i++) for (const tick of [...timers.values()]) tick();
          await flush();
          assert.equal(deckReads, 2);
          assert(main.querySelector(".lib-start"), "The library did not recover");
          assert.equal(openDialog(), sheet);
          assert.equal(sheet.querySelector("textarea").value, "Beta");
          button(sheet, "Save checklist").click(); await flush();
          same(saved.rows, [{name:"Alpha", choice:"buy"}, {name:"Beta", choice:"check"}]);
          assert.equal(writes[1].expect, 1);
          same(reads, [path]);
        """)

    def test_retry_failed_reads_and_writes_without_losing_work(self):
        self.run_js(r"""
          const read = api, write = apiWrite;
          api = async requested => { assert.equal(requested, path); throw new ApiError(503, "Unavailable"); };
          const sheet = await openFrom(library());
          assert.equal(button(sheet, "Save checklist"), null);
          assert.equal(sheet.querySelector("input"), null);
          api = read;
          button(sheet, "Try again").click(); await flush();
          const names = sheet.querySelector("textarea");
          enter(names, Array(201).fill("Alpha").join("\n"));
          button(sheet, "Add cards").click();
          assert.equal(sheet.querySelectorAll("select").length, 0);
          assert.equal(names.value.split("\n").length, 201);
          enter(names, "  Gamma  ");
          apiWrite = async () => { throw new ApiError(503, "Unavailable"); };
          button(sheet, "Save checklist").click(); await flush();
          assert(sheet.textContent.includes("couldn't be saved"));
          assert.equal(sheet.querySelectorAll("select").length, 1, "Pending names not carried into save");
          choose(sheet, 0, "buy");
          button(sheet, "Close").click();
          assert(sheet.isConnected);
          button(sheet, "Keep editing").click();
          assert.equal(sheet.querySelector("select").value, "buy");
          apiWrite = write;
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(writes[0].expect, 0);
          same(saved.rows, [{name:"Gamma", choice:"buy"}]);
          button(sheet, "Remove").click();
          assert.equal(sheet.querySelectorAll("select").length, 0);
          button(sheet, "Close").click();
          button(sheet, "Discard changes").click();
          assert(!sheet.isConnected);
          assert.equal(writes.length, 1, "Discard wrote to the server");
        """)

    def test_conflict_preserves_choices_until_explicit_reload(self):
        self.run_js(r"""
          saved = {revision: 7, title: "Deck", rows: [{name:"Alpha", choice:"check"}]};
          const sheet = await openFrom(library());
          choose(sheet, 0, "set_aside");
          const normalWrite = apiWrite;
          let attempts = 0;
          apiWrite = async (requested, body) => {
            assert.equal(requested, path);
            assert.equal(body.expect, 7);
            attempts++;
            throw new ApiError(409, "Someone changed this checklist.");
          };
          saved = {revision: 8, title: "Other device", rows: [{name:"Beta", choice:"buy"}]};
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(attempts, 1);
          assert.equal(reads.length, 1, "Conflict discarded the draft with an automatic read");
          assert.equal(sheet.querySelector("select").value, "set_aside");
          assert.equal(sheet.querySelector("input").value, "Deck");
          const reload = button(sheet, "Reload saved checklist");
          assert(reload);
          reload.click(); await flush();
          assert.equal(reads.length, 2);
          assert.equal(sheet.querySelector("input").value, "Other device");
          assert.equal(sheet.querySelector("select").value, "buy");
          apiWrite = normalWrite;
          choose(sheet, 0, "check");
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(writes.length, 1);
          assert.equal(writes[0].expect, 8);
          same(saved.rows, [{name:"Beta", choice:"check"}]);
        """)

    def test_unusable_pasted_names_stay_editable_without_partial_writes(self):
        self.run_js(r"""
          const sheet = await openFrom(library()), names = sheet.querySelector("textarea");
          for (const invalid of ["Alpha\tBeta", "A\u2028B", "X\uD800Z", "A".repeat(151)]) {
            const batch = "First good card\n" + invalid;
            paste(sheet, batch);
            assert.equal(names.value, batch);
            assert.equal(sheet.querySelectorAll("select").length, 0);
            assert.equal(document.activeElement, names);
          }
          enter(names, "Valid pending card");
          const title = sheet.querySelector("input");
          enter(title, "Friday\tupdate");
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(document.activeElement, title);
          assert.equal(writes.length, 0);
          assert.equal(names.value, "Valid pending card");
          enter(title, "Friday");
          button(sheet, "Save checklist").click(); await flush();
          assert.equal(writes.length, 1);
          same(saved.rows, [{name:"Valid pending card", choice:"check"}]);
        """)

    def test_a_late_save_cannot_replace_the_next_profiles_open_sheet(self):
        self.run_js(r"""
          const first = await openFrom(library());
          paste(first, "First private card");
          let resolveSave;
          apiWrite = (requested, body) => {
            assert.equal(requested, path);
            writes.push(body);
            return new Promise(resolve => {resolveSave = resolve;});
          };
          const save = button(first, "Save checklist");
          save.click(); save.click(); await flush();
          assert.equal(writes.length, 1);
          colCloseSheets();
          as("user1", MAY.user1);
          api = async requested => {
            assert.equal(requested, "/api/profiles/user1/deck-checklist");
            return {revision:1, title:"Second deck", rows:[{name:"Second private card",choice:"check"}]};
          };
          const second = await openFrom(library());
          resolveSave({revision:1, title:"First deck", rows:[{name:"First private card",choice:"buy"}]});
          await flush();
          assert.equal(openDialog(), second);
          assert.equal(second.querySelector("input").value, "Second deck");
          assert(!document.body.textContent.includes("First private card"));
          save.click(); await flush();
          assert.equal(writes.length, 1);
        """)


if __name__ == "__main__":
    unittest.main()
