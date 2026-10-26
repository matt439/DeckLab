"""Runtime interaction tests for the desktop workspace and phone navigation.

Runs real UI functions in Node with deterministic events, API promises and a
small DOM double. No browser is driven, no server or Forge run is started.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


WEB = Path(__file__).resolve().parents[1] / "web"
RUNNER = Path(__file__).resolve().parent / "fixtures" / "workspace_ui_runner.js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js isn't installed")
class WorkspaceInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_opaque_browser_errors_do_not_claim_the_page_failed(self):
        self.run_js("""
          const messages = [], warnings = [];
          showPageError = (message) => messages.push(message);
          console.warn = (...args) => warnings.push(args);
          for (const message of ['Script error', 'Script error.']) {
            window.fire('error', {message, filename: '', lineno: 0, colno: 0, error: null});
          }
          assert.equal(messages.length, 0);
          assert.equal(warnings.length, 2);
          window.fire('error', {message: 'Script error.', filename: '/app.js', lineno: 12});
          window.fire('error', {message: 'Script error.', error: new Error('real exception')});
          window.fire('error', {message: 'Unknown app failure'});
          window.fire('unhandledrejection', {reason: new Error('failed save')});
          assert.equal(messages.length, 4, 'actionable errors and rejected operations still show');
          assert(messages[0].includes('app.js:12'));
          assert.equal(messages[3], 'failed save');
        """)

    def test_arrows_select_and_the_thumbnail_opens_the_viewer_without_adding(self):
        self.run_js("""
          const pictured = [{...alpha, img_small: "/img/a/1/small", img: "/img/a/1/normal"},
                            {...beta, img_small: "/img/b/1/small", img: "/img/b/1/normal"}];
          results("a", pictured);
          ac.input.fire("keydown", {key: "ArrowDown"});
          const options = ac.list.querySelectorAll(".ac-option");
          assert.equal(ac.active, 1);
          assert.equal(options[1].getAttribute("aria-current"), "true");
          assert.equal(ac.input.getAttribute("aria-activedescendant"), null);
          assert.equal(editor.lists.Deck.length, 0);
          const thumb = options[1].querySelector(".ac-thumb-btn");
          let stopped = false;
          thumb.fire("click", {stopPropagation() { stopped = true; }});
          assert.equal(stopped, true);
          assert.equal(inspections.length, 1);
          assert.equal(inspections[0].card.name, "Beta");
          assert.equal(inspections[0].trigger, thumb);
          assert.equal(thumb.getAttribute("data-viewer"), "editor-results");
          assert.equal(editor.lists.Deck.length, 0);
          assert.equal(changes, 0);
        """)

    def test_click_and_enter_add_with_counts_and_keep_the_results(self):
        self.run_js("""
          results("a");
          const options = ac.list.querySelectorAll(".ac-option");
          options[1].querySelector('.ac-add').click();
          same(editor.lists.Deck.map(x => [x.name, x.qty]), [["Beta", 1]]);
          assert.equal(ac.input.value, "a");                       // the results stay for the next card
          assert.equal(ac.items.length, 2);
          assert.ok(ac.list.textContent.includes("Added ✓ (now 1)"));
          assert.equal(document.activeElement, ac.input);
          ac.input.fire("keydown", {key: "Enter", shiftKey: true});
          same(editor.lists.Deck.map(x => [x.name, x.qty]), [["Beta", 5]]);  // Shift adds 4
          ac.input.fire("keydown", {key: "ArrowUp"});
          const event = ac.input.fire("keydown", {key: "Enter"});
          assert.equal(event.defaultPrevented, true);
          same(editor.lists.Deck.map(x => [x.name, x.qty]).sort(), [["Alpha", 1], ["Beta", 5]]);
          ac.input.fire("keydown", {key: "Enter", shiftKey: true});
          same(editor.lists.Deck.find(x => x.name === "Alpha").qty, 5);
          // A count typed first: "3 a" adds 3.
          ac.input.value = "3 a";
          ac.input.fire("keydown", {key: "Enter"});
          same(editor.lists.Deck.find(x => x.name === "Alpha").qty, 8);
          same(parseQuery("4x bolt"), {n: 4, q: "bolt"});
          same(parseQuery("bolt"), {n: null, q: "bolt"});
          assert.equal(changes, 5);
          assert.equal(inspections.length, 0);
        """)

    def test_typing_invalidates_selection_before_debounce(self):
        self.run_js("""
          results("al", [alpha]);
          ac.input.value = "be";
          ac.input.fire("input");
          assert.equal(ac.items.length, 0);
          assert.equal(ac.active, -1);
          assert.equal(ac.input.getAttribute("aria-activedescendant"), null);
          ac.input.fire("keydown", {key: "Enter"});
          assert.equal(editor.lists.Deck.length, 0);
          // Defense in depth: even a stale programmatic selection cannot add.
          ac.items = [alpha]; ac.active = 0; ac.query = "al";
          pick(ac, 0);
          assert.equal(editor.lists.Deck.length, 0);
        """)

    def test_late_response_cannot_replace_new_query_results(self):
        self.run_js("""
          const pending = [];
          api = () => new Promise(resolve => pending.push(resolve));
          ac.input.value = "al";
          const old = lookUp(ac, "al");
          ac.input.value = "be"; ac.input.fire("input");
          const current = lookUp(ac, "be");
          pending[1]({cards: [beta]}); await current;
          assert.equal(ac.items[0].name, "Beta");
          pending[0]({cards: [alpha]}); await old;
          assert.equal(ac.query, "be");
          assert.equal(ac.items.length, 1);
          assert.equal(ac.items[0].name, "Beta");
          assert.equal(editor.lists.Deck.length, 0);
        """)

    def test_enter_before_lookup_only_adds_an_exact_name(self):
        self.run_js("""
          const pending = [];
          api = () => new Promise(resolve => pending.push(resolve));
          ac.input.value = "Alpha"; ac.input.fire("input");
          ac.input.fire("keydown", {key: "Enter"});
          pending[0]({cards: [alpha]}); await Promise.resolve(); await Promise.resolve();
          same(editor.lists.Deck.map(x => [x.name, x.qty]), [["Alpha", 1]]);
          ac.input.value = "be"; ac.input.fire("input");
          ac.input.fire("keydown", {key: "Enter"});
          pending[1]({cards: [beta]}); await Promise.resolve(); await Promise.resolve();
          same(editor.lists.Deck.map(x => [x.name, x.qty]), [["Alpha", 1]]);
          assert.equal(ac.items[0].name, "Beta");
        """)

    def test_the_search_asks_for_the_decks_space_and_its_filters(self):
        self.run_js("""
          editor.mode = "edit"; editor.id = "casual/gruul-ramp";
          ac.colors.add("G"); ac.colors.add("R"); ac.type = "creature"; ac.mv = "7"; ac.owned = true;
          const url = findUrl(ac, "elf");
          assert.ok(url.startsWith("/api/deck/find?"));
          const q = new URLSearchParams(url.split("?")[1]);
          same([q.get("q"), q.get("scope"), q.get("colors"), q.get("type"), q.get("mv"), q.get("id")],
               ["elf", "owned", "RG", "creature", "7", "casual/gruul-ramp"]);
          editor.mode = "new"; editor.id = null; editor.space = "user2"; ac.owned = false;
          const fresh = new URLSearchParams(findUrl(ac, "elf").split("?")[1]);
          same([fresh.get("scope"), fresh.get("space"), fresh.get("id")], [null, "user2", null]);
        """)

    def test_section_jump_focus_and_manual_scroll_current_location(self):
        self.run_js("""
          const nav = el("nav", {class: "section-nav"});
          nav.box = {top: 0, bottom: 56, left: 0, right: 393};
          const ids = ["sec-cards", "sec-guide", "sec-owned"];
          const buttons = ids.map((id, i) => el("button", {"data-section": id,
            "aria-current": i === 0 ? "location" : null}));
          buttons[0].box = {left: 0, right: 80};
          buttons[1].box = {left: 80, right: 180};
          buttons[2].box = {left: 450, right: 520};
          nav.append(...buttons); main.append(nav);
          const parts = ids.map((id, i) => {
            const part = el("section", {id}); part.box = {top: i * 500, bottom: (i + 1) * 500};
            main.append(part); return part;
          });
          jumpTo("sec-guide");
          assert.equal(document.activeElement, parts[1]);
          assert.equal(parts[1].getAttribute("tabindex"), "-1");
          assert.equal(parts[1].scrolled, 1);
          assert.equal(buttons[1].getAttribute("aria-current"), "location");
          assert.equal(buttons[0].getAttribute("aria-current"), null);
          parts[0].box.top = -1200; parts[1].box.top = -600; parts[2].box.top = 70;
          window.fire("scroll"); flushTimers();
          assert.equal(buttons[2].getAttribute("aria-current"), "location");
          assert.equal(buttons[1].getAttribute("aria-current"), null);
          assert.equal(nav.scrollLeft, 127);
          assert.equal(document.activeElement, parts[1]); // manual scroll must not steal focus
        """)

    def test_phones_get_the_quick_edit_for_saved_and_new_decks(self):
        self.run_js("""
          assert.equal(canBuildDecks(), false);
          assert.equal(quickEditing(), true);
          let opened = null; showEditor = (params, token) => { opened = params.get("id"); };
          let started = null; showNewDeck = (params, token) => { started = params.get("kind"); };
          showDesktopHandoff(new URLSearchParams("id=casual/gruul-ramp&v=owned"));
          assert.equal(opened, "casual/gruul-ramp");                 // the Quick edit, not a handoff
          assert.equal(started, null);
          showDesktopHandoff(new URLSearchParams("kind=casual"));
          assert.equal(started, "casual");                           // a new deck too, in the Quick edit
          assert.equal(main.querySelector(".desktop-handoff"), null);
        """)

    def test_new_draft_clears_availability_and_rejects_old_check_answer(self):
        self.run_js("""
          const row = el("li", {class: "edit-row", "data-uid": "1"}, el("p", {class: "edit-availability", text: "0 missing"}));
          editor.dom.lines = el("div", {}, row); main.append(editor.dom.lines);
          editor.dom.check = el("section"); main.append(editor.dom.check);
          editor.check = {stamp: "old"}; editor.checkSeq = 0;
          draftBody = () => ({}); sentUids = () => ({}); drawCheckingState = () => {};
          let reply; apiWrite = () => new Promise(resolve => { reply = resolve; });
          const pending = runCheck(editor);
          scheduleCheck();
          assert.equal(row.querySelector(".edit-availability"), null);
          reply({stamp: "obsolete"});
          assert.equal(await pending, null);
          assert.equal(editor.check.stamp, "old");
          row.append(el("p", {class: "edit-availability", text: "0 missing"}));
          editor.checkError = {message: "Offline"}; drawCheck();
          assert.equal(row.querySelector(".edit-availability"), null);
          assert.ok(editor.dom.check.textContent.includes("Offline"));
        """)

    def run_draft_js(self, scenario):
        self.run_js("""
          const stored = new Map();
          let storageBlocked = false, failWrites = false;
          window.localStorage = {
            getItem(key) { if (storageBlocked) throw new Error("SecurityError"); return stored.get(key) ?? null; },
            setItem(key, value) {
              if (storageBlocked || failWrites) throw new Error("QuotaExceededError"); stored.set(key, String(value));
            },
            removeItem(key) { if (storageBlocked) throw new Error("SecurityError"); stored.delete(key); },
          };
          const messages = []; toast = text => messages.push(text);
          const fields = {title: "Draft deck", kind: "casual", player: "user", status: "idea"};
          editor = {mode: "new", version: "target", profile: "matt", from: null, leaving: false,
            fields: {...fields}, base: {fields: {...fields}, lists: {}},
            lists: {Deck: [newLine({name: "Alpha", qty: 1})]}, dom: {banners: el("div")}};
          main.append(editor.dom.banners);
        """ + scenario)

    def test_failed_draft_storage_blocks_leave_and_shows_recovery_warning(self):
        self.run_draft_js("""
          failWrites = true;
          assert.equal(saveDraft(editor), false);
          assert.equal(editor.draftFailed, true);
          assert.ok(editor.dom.banners.textContent.includes("couldn't be kept"));
          let offered;
          ask = async (title, paragraphs, choices) => {
            offered = choices;
            assert.ok(paragraphs.join(" ").includes("only in this open editor"));
            return "stay";
          };
          assert.equal(await confirmLeave(), false);
          assert.ok(!offered.some(choice => choice.value === "leave"));
          assert.equal(editor.leaving, false);
          assert.equal(editor.lists.Deck[0].qty, 1);
          failWrites = false;
          assert.equal(saveDraft(editor), true);
          assert.equal(editor.draftFailed, false);
          assert.equal(editor.dom.banners.textContent, "");
          ask = async () => "leave";
          assert.equal(await confirmLeave(), true);
          assert.equal(editor.leaving, true);
          assert.equal(JSON.parse(local.get(draftKey(editor))).lists.Deck[0].qty, 1);
        """)

    def test_blocked_storage_keeps_editor_and_profile_on_automatic_switch(self):
        self.run_draft_js("""
          storageBlocked = true;
          state.profile = {id: "matt", name: "Matt"};
          const original = editor;
          let routed = false; route = () => { routed = true; };
          await switchProfile(false);
          assert.equal(state.profile.id, "matt");
          assert.equal(editor, original);
          assert.equal(editor.leaving, false);
          assert.equal(routed, false);
          assert.ok(messages.some(text => text.includes("before switching people")));
        """)

    def test_leave_rechecks_latest_draft_and_explicit_discard_still_works(self):
        self.run_draft_js("""
          ask = async () => {
            editor.lists.Deck[0].qty = 2;
            failWrites = true;
            return "leave";
          };
          assert.equal(await confirmLeave(), false);
          assert.equal(editor.leaving, false);
          assert.equal(editor.lists.Deck[0].qty, 2);
          assert.equal(JSON.parse(local.get(draftKey(editor))).lists.Deck[0].qty, 1);
          ask = async () => "discard";
          assert.equal(await confirmLeave(), true);
          assert.equal(editor.leaving, true);
          assert.equal(local.get(draftKey(editor)), null);
        """)

    def test_unload_still_warns_and_successful_profile_switch_preserves_draft(self):
        self.run_draft_js("""
          failWrites = true;
          const unloading = window.fire("beforeunload");
          assert.equal(unloading.defaultPrevented, true);
          assert.equal(editor.leaving, false);
          failWrites = false;
          state.profile = {id: "matt", name: "Matt"};
          main.append(el("div", {id: "topbar-actions"}));
          let routed = false; route = () => { routed = true; };
          const key = draftKey(editor);
          await switchProfile(false);
          assert.equal(state.profile, null);
          assert.equal(editor.leaving, true);
          assert.equal(routed, true);
          assert.equal(JSON.parse(local.get(key)).lists.Deck[0].qty, 1);
        """)

    def test_failed_draft_removal_does_not_claim_discard_or_allow_clean_navigation(self):
        self.run_draft_js("""
          assert.equal(saveDraft(editor), true);
          const key = draftKey(editor);
          storageBlocked = true;
          ask = async () => "discard";
          assert.equal(await confirmLeave(), false);
          assert.equal(editor.leaving, false);
          assert.equal(editor.draftRemoveFailed, true);
          assert.ok(editor.dom.banners.textContent.includes("stored draft couldn't be removed"));
          // Undoing every edit also needs to remove the earlier draft before leaving.
          editor.lists = {};
          assert.equal(isDirty(), false);
          queueDraft(); // clean navigation cannot race ahead of a debounced removal
          assert.equal(editorDirty(), true);
          assert.equal(await leaveEditor(false), false);
          storageBlocked = false;
          assert.ok(local.get(key));
          assert.equal(saveDraft(editor), true);
          assert.equal(local.get(key), null);
          assert.equal(editorDirty(), false);
        """)

    def test_successful_server_save_with_failed_cleanup_preserves_saved_base_and_new_edits(self):
        self.run_draft_js("""
          state.profile = {id: "matt", plays_as: "user"};
          assert.equal(saveDraft(editor), true);
          const oldKey = draftKey(editor);
          const erase = window.localStorage.removeItem;
          let cannotErase = true;
          window.localStorage.removeItem = key => {
            if (cannotErase) throw new Error("SecurityError"); erase(key);
          };
          const view = {id: "casual/draft-deck", kind: "casual", title: "Draft deck", sha256: "saved-sha",
            sections: ["Deck", "Sideboard"], fields: {status: "idea", player: "user"},
            lists: {target: {Deck: [{name: "Alpha", qty: 1}]}, owned: null}};
          let writes = 0;
          apiWrite = async () => { writes += 1; return {id: view.id, deck: view}; };
          draftBody = () => ({});
          scheduleCheck = () => {};
          drawEditor = () => { editor.dom = {banners: el("div")}; main.append(editor.dom.banners); drawBanners(); };
          const sheet = {closed: false, close() { this.closed = true; }};
          await doSave(sheet, el("button", {text: "Save"}));
          assert.equal(writes, 1);
          assert.equal(editor.mode, "edit");
          assert.equal(editor.id, view.id);
          assert.equal(editor.sha256, "saved-sha");
          assert.equal(editor.lists.Deck[0].qty, 1); // the stale draft was not re-applied
          assert.equal(isDirty(), false);
          assert.equal(editorDirty(), true);
          assert.equal(editor.pendingDraftKey, oldKey);
          assert.ok(editor.dom.banners.textContent.includes("deck was saved"));
          editor.lists.Deck[0].qty = 2;
          assert.equal(saveDraft(editor), false);
          assert.equal(editor.lists.Deck[0].qty, 2);
          // Saving again before cleanup succeeds must retain the original new-deck draft key.
          view.sha256 = "saved-again-sha";
          view.lists.target.Deck[0].qty = 2;
          await doSave({closed: false, close() {}}, el("button", {text: "Save again"}));
          assert.equal(editor.pendingDraftKey, oldKey);
          assert.equal(editor.lists.Deck[0].qty, 2);
          editor.lists.Deck[0].qty = 3;
          cannotErase = false;
          assert.equal(saveDraft(editor), true);
          assert.equal(editor.pendingDraftKey, null);
          assert.equal(local.get(oldKey), null);
          const saved = readDraft(editor);
          assert.equal(saved.sha256, "saved-again-sha");
          assert.equal(saved.base.lists.Deck[0].qty, 2);
          assert.equal(saved.lists.Deck[0].qty, 3);
          assert.equal(writes, 2);
        """)


if __name__ == "__main__":
    unittest.main()
