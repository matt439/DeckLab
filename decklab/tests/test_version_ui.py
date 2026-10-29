"""Runtime checks for version warnings, polling and safe page refresh.

Runs the real page functions under Node with deterministic networking/time and
a small DOM double. No browser, server or external request is started.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
RUNNER = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
const [web, scenario] = JSON.parse(fs.readFileSync(0, "utf8"));
const listeners = () => ({
  events: new Map(),
  addEventListener(type, fn) {
    if (!this.events.has(type)) this.events.set(type, []);
    this.events.get(type).push(fn);
  },
  removeEventListener(type, fn) {
    this.events.set(type, (this.events.get(type) || []).filter((f) => f !== fn));
  },
  fire(type, props = {}) {
    const event = {target: this, currentTarget: this, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...props};
    for (const fn of this.events.get(type) || []) fn(event);
    return event;
  },
});
class Node {
  constructor(tag) {
    Object.assign(this, listeners());
    this.tag = tag; this.children = []; this.attrs = {}; this.hidden = false; this.dataset = {}; this.parent = null;
    const node = this;
    this.classList = {add() {}, remove() {}, toggle() {},
      contains: (name) => (node.attrs.class || "").split(/\s+/).includes(name)};
  }
  get nodeType() { return 1; }
  closest(selector) {
    for (let n = this; n; n = n.parent) if (n.matches && n.matches(selector)) return n;
    return null;
  }
  get nextElementSibling() {
    const kids = this.parent ? this.parent.children : [];
    return kids[kids.indexOf(this) + 1] || null;
  }
  after(node) { node.parent = this.parent; this.parent.children.splice(this.parent.children.indexOf(this) + 1, 0, node); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((n) => n !== this); this.parent = null; }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === "hidden") this.hidden = true;
  }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; if (key === "hidden") this.hidden = false; }
  append(...items) {
    for (const item of items) {
      const node = item instanceof Node ? item : new Text(String(item));
      node.parent = this;
      this.children.push(node);
    }
  }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  set textContent(value) { this.replaceChildren(new Text(String(value))); }
  get textContent() { return this.children.map((n) => n.textContent).join(""); }
  matches(selector) {
    for (const match of selector.matchAll(/\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]/g)) {
      if (this.getAttribute(match[1]) == null ||
          (match[2] !== undefined && this.getAttribute(match[1]) !== match[2])) return false;
    }
    const simple = selector.replace(/\[[^\]]+\]/g, "");
    if (simple.startsWith("#")) return this.getAttribute("id") === simple.slice(1);
    if (simple.startsWith(".")) return (this.attrs.class || "").split(/\s+/).includes(simple.slice(1));
    return !simple || this.tag === simple;
  }
  querySelectorAll(selector) {
    return this.children.flatMap((n) => [...(n.matches(selector) ? [n] : []), ...n.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  click() { this.fire("click"); }
}
class Text extends Node {
  constructor(text) { super("#text"); this.data = text; }
  get textContent() { return this.data; }
}
const document = Object.assign(listeners(), {
  body: new Node("body"), documentElement: new Node("html"), visibilityState: "visible",
  createElement: (tag) => new Node(tag), createElementNS: (_, tag) => new Node(tag),
  querySelector(selector) { return this.body.querySelector(selector); },
  querySelectorAll(selector) { return this.body.querySelectorAll(selector); },
  getElementById(id) { return this.body.querySelector("#" + id); },
});
const window = Object.assign(listeners(), {matchMedia: () => ({matches: true, addEventListener() {}})});
const timers = new Map(); let nextTimer = 0;
const location = {href: "http://homepc.local:8642/?theme=dark&v=old#/edit?id=casual/test", assign(url) { this.href = url; this.reload(); }, hash: "#/edit?id=casual/test", reloads: 0, reload() {
  this.reloads += 1; this.unload = window.fire("beforeunload");
}};
window.location = location;
for (const id of ["build-warning", "build-version", "build-checked", "build-check", "footer-data"]) {
  const node = new Node("div"); node.setAttribute("id", id); document.body.append(node);
}
const meta = new Node("meta");
meta.setAttribute("name", "decklab-web-revision"); meta.content = "page-at-load";
document.body.append(meta);
const context = {Node, document, window, location, console, assert, URL, URLSearchParams, AbortController,
  setTimeout: (fn, delay) => { const id = ++nextTimer; timers.set(id, {fn, delay}); return id; },
  clearTimeout: (id) => timers.delete(id),
  setInterval: (fn, delay) => { const id = ++nextTimer; timers.set(id, {fn, delay}); return id; },
  clearInterval: (id) => timers.delete(id),
  fetch: () => Promise.reject(new Error("network disabled in test")),
  flushTimer: () => { const [id, item] = timers.entries().next().value; timers.delete(id); item.fn(); },
  timerCount: () => timers.size,
};
vm.createContext(context);
for (const name of ["core.js", "editor.js", "editor-drafts.js", "version.js"]) {
  vm.runInContext(fs.readFileSync(web + "/" + name, "utf8"), context, {filename: name});
}
vm.runInContext(`
  const currentBuild = {running_commit: "a123456789abcdef", latest_commit: "a123456789abcdef",
    running_dirty: false, latest_dirty: false, restart_required: false,
    web_revision: "page-at-load", error: null};
  const answer = (build = currentBuild) => ({build, cards: {ready: true, built_at: "2026-10-01"}});
  const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
`, context);
Promise.resolve(vm.runInContext(`(async () => { ${scenario}\n })()`, context))
  .then(() => process.stdout.write("ok\n"))
  .catch((error) => { process.stderr.write(error.stack + "\n"); process.exitCode = 1; });
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VersionInteractionTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, "-e", RUNNER], input=json.dumps([str(WEB), scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_build_line_is_for_admins(self):
        # WP2: a member never sees the build hashes, Check for updates or Last checked (the warning box still
        # shows them anything they need to do).
        self.run_js("""
          const line = new Node("div"); line.setAttribute("class", "build-footer"); document.body.append(line);
          state.profile = {id: "user1", name: "User1", role: "member"};
          renderVersionStatus(answer());
          assert.equal(line.hidden, true);
          assert.equal(document.querySelector("#build-checked").hidden, true);
          state.profile = {id: "matt", name: "Matt", role: "admin"};
          renderVersionStatus(answer());
          assert.equal(line.hidden, false);
          assert.equal(document.querySelector("#build-checked").hidden, false);
          // The warning box: a member is told what to do (restart, reload), not about the PC's uncommitted code.
          const warning = document.querySelector("#build-warning");
          const dirty = {...currentBuild, running_dirty: true, latest_dirty: true};
          renderVersionStatus(answer(dirty));
          assert.match(warning.textContent, /uncommitted/);
          state.profile = {id: "user1", name: "User1", role: "member"};
          renderVersionStatus(answer(dirty));
          assert.equal(warning.hidden, true);
          renderVersionStatus(answer({...dirty, restart_required: true}));
          assert.match(warning.textContent, /Restart Deck Lab on the PC/);
          assert.doesNotMatch(warning.textContent, /uncommitted/);
        """)

    def test_why_runs_cant_start_shows_beside_each_run_control(self):
        # WP2: no page-wide notice for anyone; each Play or Start (data-run) is disabled with the reason under
        # its row, and goes back to how its page left it when runs are allowed again.
        self.run_js("""
          const settings = new Node("div"); settings.setAttribute("id", "sim-settings"); document.body.append(settings);
          for (const id of ["sim-mode", "sim-workers", "sim-since"]) {
            const node = new Node(id === "sim-since" ? "span" : "select"); node.setAttribute("id", id); document.body.append(node);
          }
          const row = el("div", {class: "actions"}, el("button", {class: "btn", "data-run": true, text: "Play"}));
          const done = el("div", {class: "actions"}, el("button", {class: "btn", "data-run": true, disabled: true, text: "Play"}));
          document.body.append(row, done);
          const [play, other] = document.querySelectorAll("[data-run]");
          play.disabled = false; other.disabled = true;
          renderSimulations({mode: "admins", may_start: false, may_edit: false,
            why_not: "Only Matt can start simulations right now. Saved results still show."});
          assert.deepEqual(simulationsGate(), {may: false, why: "Only Matt can start simulations right now. Saved results still show."});
          assert.equal(play.disabled, true);
          assert.equal(row.nextElementSibling.textContent, "Only Matt can start simulations right now. Saved results still show.");
          assert.equal(mayStartRuns(), false);
          renderSimulations({mode: "admins", may_start: false, may_edit: false, why_not: "again"});
          assert.equal(document.querySelectorAll(".run-blocked").length, 2);      // one each, not one more
          renderSimulations({mode: "everyone", may_start: true, may_edit: false, why_not: null});
          assert.equal(play.disabled, false);
          assert.equal(other.disabled, true);                 // its page had it disabled
          assert.equal(document.querySelectorAll(".run-blocked").length, 0);
          assert.deepEqual(simulationsGate(), {may: true, why: null});
          // An admin is told beside the controls too while runs are paused (the setting is on the Settings page).
          renderSimulations({mode: "paused", may_start: false, may_edit: true, why_not: "paused", max_workers: 4});
          assert.equal(document.querySelectorAll(".run-blocked").length, 2);
          assert.equal(settings.hidden, false);
          assert.equal(document.querySelector("#sim-notice"), null);
        """)

    def test_current_code_and_data_only_commit_have_no_restart_warning(self):
        self.run_js("""
          const current = versionInfo(currentBuild, "page-at-load");
          assert.match(current.label, /a1234567/);
          assert.match(current.label, /Server code current/);
          assert.equal(current.messages.length, 0);
          assert.equal(current.reload, false);
          const dataChange = versionInfo({...currentBuild, latest_commit: "b987654321abcdef"}, "page-at-load");
          assert.match(dataChange.label, /Server a1234567.*Checkout b9876543/);
          assert.match(dataChange.label, /Server code current/);
          assert.doesNotMatch(dataChange.label, /Restart needed/);
          assert.equal(dataChange.messages.length, 0);
          assert.equal(dataChange.reload, false);
        """)

    def test_dirty_start_cannot_be_identified_by_commit_alone(self):
        self.run_js("""
          const dirty = versionInfo({...currentBuild, running_dirty: true, latest_dirty: true}, "page-at-load");
          assert.match(dirty.label, /Server a1234567 \\+ local changes/);
          assert.match(dirty.label, /Checkout a1234567 \\+ local changes/);
          assert.match(dirty.messages.join(" "), /uncommitted.*commit ID alone/);
          const newEdit = versionInfo({...currentBuild, latest_dirty: true, restart_required: true}, "page-at-load");
          assert.match(newEdit.label, /Restart needed/);
          assert.match(newEdit.messages.join(" "), /server code has changed/i);
        """)

    def test_reload_bypasses_html_cache_without_losing_route_or_options(self):
        self.run_js("""
          reloadDeckLab();
          const target = new URL(location.href);
          assert.equal(target.hash, "#/edit?id=casual/test");
          assert.equal(target.searchParams.get("theme"), "dark");
          assert.notEqual(target.searchParams.get("v"), "old");
          assert.equal(target.searchParams.getAll("v").length, 1);
          assert.equal(location.reloads, 1);
        """)

    def test_server_restart_and_browser_reload_are_independent_warnings(self):
        self.run_js("""
          const build = {...currentBuild, latest_commit: "b987654321abcdef", restart_required: true,
            web_revision: "new-page"};
          const view = versionInfo(build, "page-at-load");
          assert.equal(view.reload, true);
          assert.match(view.label, /Restart needed/);
          assert.match(view.messages.join(" "), /Restart Deck Lab on the PC/);
          assert.match(view.messages.join(" "), /browser page is out of date/);
          renderVersionStatus(answer(build));
          const host = document.querySelector("#build-warning");
          assert.equal(host.hidden, false);
          const button = host.querySelector("button");
          assert.ok(button);
          renderVersionStatus(answer(build));
          assert.equal(host.querySelector("button"), button); // polling keeps focused button intact
          assert.equal(location.reloads, 0); // never reload merely because an update is available
        """)

    def test_unknown_and_error_states_do_not_claim_current_code(self):
        self.run_js("""
          for (const build of [null, {...currentBuild, restart_required: null},
              {...currentBuild, error: "Git is unavailable"}]) {
            const view = versionInfo(build, "page-at-load");
            assert.doesNotMatch(view.label, /Server code current/);
            assert.ok(view.messages.length);
          }
          for (const page of [null, "unknown", "__DECKLAB_WEB_REVISION__"]) {
            assert.equal(versionInfo(currentBuild, page).reload, false);
          }
          assert.equal(versionInfo({...currentBuild, web_revision: null}, "page-at-load").reload, false);
        """)

    def test_polling_deduplicates_start_foreground_events_and_manual_checks(self):
        self.run_js("""
          const pending = [];
          api = (path) => {
            assert.equal(path, "/api/status");
            return new Promise((resolve) => pending.push(resolve));
          };
          startVersionMonitor(); startVersionMonitor();
          const joined = showFooter();
          window.fire("focus"); window.fire("online");
          assert.equal(pending.length, 1);
          assert.equal(document.querySelector("#build-check").disabled, true);
          pending[0](answer()); await joined; await settle();
          assert.equal(document.querySelector("#build-check").disabled, false);
          assert.equal(timerCount(), 1);
          flushTimer();
          assert.equal(pending.length, 2);
          pending[1](answer()); await settle();
          assert.equal(timerCount(), 1);
          document.querySelector("#build-check").click();
          assert.equal(pending.length, 3);
          pending[2](answer()); await settle();
          assert.equal(timerCount(), 1);
        """)

    def test_background_pause_and_return_refresh(self):
        self.run_js("""
          let calls = 0;
          api = async () => { calls += 1; return answer(); };
          startVersionMonitor(); await settle();
          assert.equal(calls, 1); assert.equal(timerCount(), 1);
          document.visibilityState = "hidden"; document.fire("visibilitychange");
          assert.equal(timerCount(), 0);
          window.fire("focus"); window.fire("online"); await showFooter();
          assert.equal(calls, 1);
          document.visibilityState = "visible"; document.fire("visibilitychange"); await settle();
          assert.equal(calls, 2); assert.equal(timerCount(), 1);
          window.fire("pagehide");
          assert.equal(timerCount(), 0);
          await showFooter(); assert.equal(calls, 2);
          window.fire("pageshow", {persisted: true}); await settle();
          assert.equal(calls, 3); assert.equal(timerCount(), 1);
        """)

    def test_connection_failure_replaces_current_claim_and_later_recovers(self):
        self.run_js("""
          api = async () => answer();
          await showFooter();
          assert.match(document.querySelector("#build-version").textContent, /Server code current/);
          api = async () => { throw new Error("Offline"); };
          await showFooter();
          const label = document.querySelector("#build-version").textContent;
          assert.match(label, /unavailable/i);
          assert.doesNotMatch(label, /current/);
          const warning = document.querySelector("#build-warning");
          assert.equal(warning.hidden, false);
          assert.match(warning.textContent, /Offline/);
          assert.equal(document.querySelector("#build-check").disabled, false);
          api = async () => answer(); await showFooter();
          assert.match(document.querySelector("#build-version").textContent, /Server code current/);
          assert.equal(warning.hidden, true);
        """)

    def test_timed_out_request_releases_busy_state_and_schedules_retry(self):
        self.run_js("""
          let signal;
          api = (path, options) => new Promise((resolve, reject) => {
            signal = options.signal;
            signal.addEventListener("abort", () => reject(new Error("Timed out")));
          });
          startVersionMonitor();
          assert.equal(signal.aborted, false);
          flushTimer(); await settle();
          assert.equal(signal.aborted, true);
          assert.equal(document.querySelector("#build-check").disabled, false);
          assert.match(document.querySelector("#build-version").textContent, /unavailable/i);
          assert.equal(timerCount(), 1);
        """)

    def test_reload_button_preserves_real_editor_beforeunload_guard(self):
        self.run_js("""
          let draftSaves = 0;
          editor = {leaving: false, draft: "unsaved card edits"};
          const original = editor;
          isDirty = () => true;
          saveDraft = (ed) => { assert.equal(ed, original); draftSaves += 1; };
          renderVersionStatus(answer({...currentBuild, web_revision: "new-page"}));
          document.querySelector("#build-warning").querySelector("button").click();
          assert.equal(location.reloads, 1);
          assert.equal(location.unload.defaultPrevented, true);
          assert.equal(location.unload.returnValue, "");
          assert.equal(draftSaves, 1);
          assert.equal(editor, original);
          assert.equal(editor.leaving, false);
          assert.equal(editor.draft, "unsaved card edits");
        """)

    def test_the_database_warning_is_for_everyone_and_its_details_for_admins(self):
        self.run_js("""
          const host = document.querySelector("#build-warning");
          renderVersionStatus({...answer(), database: {ok: null, checking: true}});
          assert.equal(host.hidden, true);                    // not checked yet: nothing to say
          renderVersionStatus({...answer(), database: {ok: true}});
          assert.equal(host.hidden, true);
          renderVersionStatus({...answer(), database: {ok: false}});      // what anyone but an admin gets
          assert.equal(host.hidden, false);
          assert.match(host.textContent, /Deck Lab's database isn't reachable/);
          assert.doesNotMatch(host.textContent, /migrat|backup/);
          renderVersionStatus({...answer(), database: {ok: false, error: "migrations pending", pending_migrations: 1,
            last_backup: "2026-10-11T03:30:00+10:00", backup_stale: false, stale_hours: 36, venv: null}});
          assert.match(host.textContent, /1 migration waiting\\. Run python -m decklab\\.db migrate/);
          assert.doesNotMatch(host.textContent, /isn't reachable|backup|Until then/);
          // A migration the stores need (usable false) says what can't be done meanwhile.
          renderVersionStatus({...answer(), database: {ok: false, usable: false, error: "migrations pending",
            pending_migrations: 1, last_backup: null, backup_stale: false, stale_hours: 36, venv: null}});
          assert.match(host.textContent, /migrate on the PC .*Until then, wishlists, settings and play records can't/);
          renderVersionStatus({...answer(), database: {ok: false, usable: true, error: "check failed",
            pending_migrations: null, last_backup: null, backup_stale: null, stale_hours: 36, venv: null}});
          assert.match(host.textContent, /couldn't check its database just now/);
          assert.doesNotMatch(host.textContent, /isn't reachable/);
          renderVersionStatus({...answer(), database: {ok: false, error: "psycopg missing", pending_migrations: null,
            last_backup: null, backup_stale: null, stale_hours: 36, venv: "there's no .venv in the repo"}});
          assert.match(host.textContent, /isn't reachable.*there's no \\.venv in the repo/);
          renderVersionStatus({...answer(), database: {ok: true, error: null, pending_migrations: 0,
            last_backup: "2026-10-01T03:30:00+10:00", backup_stale: true, stale_hours: 36, venv: null}});
          assert.match(host.textContent, /last database backup that worked was on .*more than 36 hours ago/);
          renderVersionStatus({...answer(), database: {ok: true, error: null, pending_migrations: 0,
            last_backup: null, backup_stale: true, stale_hours: 36, venv: null}});
          assert.match(host.textContent, /No database backup has worked yet/);
          // The nightly checks' warning comes worded by the server (lib/dbstatus.checks_warning).
          renderVersionStatus({...answer(), database: {ok: true, error: null, pending_migrations: 0,
            last_backup: "2026-10-11T03:30:00+10:00", backup_stale: false, stale_hours: 36, venv: null,
            checks_warning: "The database check of 2026-10-12 03:35 found a problem (deck lines)."}});
          assert.equal(host.hidden, false);
          assert.match(host.textContent, /database check of 2026-10-12 03:35 found a problem \\(deck lines\\)/);
          // Beside a version warning, both are shown.
          renderVersionStatus({...answer({...currentBuild, restart_required: true}), database: {ok: false}});
          assert.match(host.textContent, /database isn't reachable.*server code has changed/);
        """)

    def test_a_database_outage_is_an_error_box_not_the_card_data_wait(self):
        self.run_js("""
          const main = new Node("main"); main.setAttribute("id", "main"); document.body.append(main);
          globalThis.route = () => {};
          globalThis.afterRender = () => {};
          let calls = 0;
          const words = "Deck Lab's database isn't reachable right now. Try again in a minute.";
          api = async () => { calls += 1; throw new ApiError(503, words, {error: words, reason: "database"}); };
          await load("/api/profiles/user1/wishlist", routeToken, () => assert.fail("nothing to draw"));
          assert.equal(calls, 1);                              // no waiting and retrying
          assert.match(main.textContent, /database isn't reachable right now.*\\(error 503\\)/);
          assert.doesNotMatch(main.textContent, /card data/);
          assert.ok(main.querySelectorAll("button").some((b) => b.textContent === "Try again"));
          // A 503 for the card data still waits for it.
          api = async () => { throw new ApiError(503, "The card data is still downloading.", {error: "x"}); };
          load("/api/library", routeToken, () => {});
          await settle();
          assert.match(main.textContent, /The card data isn't ready yet/);
          routeToken += 1;                                     // leave the page: the wait ends
        """)

    def test_the_off_pages_answer_waits_and_retries_as_deck_lab_is_off(self):
        # The off page's Worker (decklab/cloudflare/) answers /api/ with 503 and reason "off" while the PC or
        # Deck Lab isn't running: the page waits and tries again, headed "Deck Lab is off".
        self.run_js("""
          const main = new Node("main"); main.setAttribute("id", "main"); document.body.append(main);
          globalThis.route = () => {};
          globalThis.afterRender = () => {};
          const words = "Deck Lab is off at the moment: the computer at home isn't running it. Try again later.";
          api = async () => { throw new ApiError(503, words, {error: words, reason: "off"}); };
          load("/api/library", routeToken, () => {});
          await settle();
          assert.match(main.textContent, /Deck Lab is off.*computer at home isn't running it.*Trying again in/);
          assert.doesNotMatch(main.textContent, /card data/);
          routeToken += 1;                                     // leave the page: the wait ends
        """)
