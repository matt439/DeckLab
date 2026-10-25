"""Runtime checks for matchup updates across devices; no server or Forge run is started."""
import json
import shutil
import subprocess
import unittest

from decklab.tests.test_web import MATCHUP_SCRIPTS, WEB


NODE = shutil.which("node")
SCRIPTS = [str(WEB / name) for name in MATCHUP_SCRIPTS]

RUNNER = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, fn) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(fn);
  }
  removeEventListener(name, fn) { this.listeners.get(name)?.delete(fn); }
  fire(name) { for (const fn of [...(this.listeners.get(name) || [])]) fn({ type: name }); }
  count() { return [...this.listeners.values()].reduce((sum, set) => sum + set.size, 0); }
}
let clock = 0, sequence = 0;
const timers = new Map();
const later = (fn, ms) => { const id = ++sequence; timers.set(id, { at: clock + ms, fn }); return id; };
const flush = async () => { for (let n = 0; n < 8; n++) await Promise.resolve(); };
async function advance(ms) {
  const until = clock + ms;
  for (;;) {
    await flush();
    const due = [...timers].filter(([id, timer]) => timer.at <= until).sort((a, b) => a[1].at - b[1].at)[0];
    if (!due) break;
    clock = due[1].at; timers.delete(due[0]); due[1].fn();
  }
  clock = until; await flush();
}
const requests = [];
const document = Object.assign(new Events(), { visibilityState: "visible" });
const window = new Events();
const context = { console, Date, Error, AbortController, document, window, POLL_MS: 1000, routeToken: 1,
  setTimeout: later, clearTimeout: (id) => timers.delete(id),
  api: (url, options) => new Promise((resolve, reject) => {
    // Deliberately permit an aborted read to resolve: it must never apply stale data.
    requests.push({ url, signal: options.signal, resolve, reject });
  }) };
vm.createContext(context);
const [paths, test] = JSON.parse(fs.readFileSync(0, "utf8"));
for (const path of paths) vm.runInContext(fs.readFileSync(path, "utf8"), context, { filename: path });
const host = { isConnected: true };
const received = [], errors = [], busy = [];
let fresh = 0, active = false;
const view = { busy: (on) => busy.push(on),
  fresh: () => fresh++, lost: (error) => errors.push(error.message) };
const start = () => context.watchMatchupUpdates({ token: context.routeToken, host: () => host,
  url: "/api/matchups", active: () => active, view,
  onFresh: (data) => { received.push(data); active = !!data.running?.length; } });
const tests = {
  async idle_discovery_and_completion() {
    const drawn = [], changes = [];
    context.replaceMatchupContent = (target, draw) => draw();
    context.followList(host, 1, { running: [], results: [] }, view, (data) => changes.push(data),
      (data) => drawn.push(data));
    await advance(14999); assert.equal(requests.length, 0);
    await advance(1); assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "/api/matchups");
    const run = { running: [{ key: "other-device", status: "running" }], results: [] };
    requests[0].resolve(run); await flush();
    assert.equal(drawn.length, 1); assert.equal(changes[0].running[0].key, "other-device");
    await advance(2000); assert.equal(requests.length, 2);
    requests[1].resolve(run); await flush();
    assert.equal(drawn.length, 1, "unchanged data must not rebuild focused links");
    await advance(2000); assert.equal(requests.length, 3);
    requests[2].resolve({ running: [], results: [{ key: "finished" }] }); await flush();
    assert.equal(drawn.length, 2);
    await advance(14999); assert.equal(requests.length, 3);
    await advance(1); assert.equal(requests.length, 4, "completion must not stop discovery");
  },
  async background_and_foreground() {
    start(); await advance(0);
    document.visibilityState = "hidden"; document.fire("visibilitychange");
    await advance(60000); assert.equal(requests.length, 0);
    document.visibilityState = "visible"; document.fire("visibilitychange"); window.fire("focus");
    assert.equal(requests.length, 1, "focus and visibility must share one request");
    window.fire("pagehide"); assert.equal(requests[0].signal.aborted, true);
    window.fire("pageshow");
    requests[0].resolve({ stale: true }); await flush();
    assert.equal(received.length, 0); assert.equal(requests.length, 2, "restoration checks immediately after abort settles");
    requests[1].resolve({ running: [] }); await flush();
    assert.equal(received.length, 1); assert.deepEqual(errors, []);
    window.fire("online"); assert.equal(requests.length, 3);
  },
  async leaving_and_replacement() {
    start(); await advance(15000);
    context.stopMatchupRefresh();
    assert.equal(requests[0].signal.aborted, true);
    assert.equal(window.count() + document.count(), 0);
    requests[0].resolve({ stale: true }); await flush();
    await advance(60000); assert.equal(requests.length, 1); assert.equal(received.length, 0);
    start(); start(); await advance(15000);
    assert.equal(requests.length, 2, "replacing a watcher must not duplicate requests");
    context.routeToken++;
    requests[1].resolve({ stale: true }); await flush();
    assert.equal(received.length, 0); assert.equal(window.count() + document.count(), 0);
  },
  async write_race() {
    const watcher = start(); await advance(15000);
    watcher.hold(); assert.equal(requests[0].signal.aborted, true);
    window.fire("focus"); await advance(20000);
    assert.equal(requests.length, 1, "no reads while Start or Stop is pending");
    requests[0].resolve({ running: [{ obsolete: true }] }); await flush();
    assert.equal(received.length, 0);
    active = true; watcher.release(); await advance(2000);
    assert.equal(requests.length, 2);
    requests[1].resolve({ running: [{ current: true }] }); await flush();
    assert.equal(received[0].running[0].current, true);
    assert.deepEqual(errors, [], "intentional aborts must not report a network failure");
  },
  async failure_recovery_and_timeout() {
    start(); await advance(15000);
    requests[0].reject(new Error("PC offline")); await flush();
    assert.deepEqual(errors, ["PC offline"]); assert.equal(fresh, 0);
    await advance(30000); assert.equal(requests.length, 2);
    requests[1].resolve({ running: [] }); await flush(); assert.equal(fresh, 1);
    // No Refresh button any more (MU-13): coming back to the window asks at once.
    window.fire("focus"); assert.equal(requests.length, 3);
    await advance(12000); assert.equal(requests[2].signal.aborted, true);
    requests[2].reject(new Error("aborted")); await flush();
    assert.match(errors[1], /took too long/);
    assert.equal(busy.at(-1), false);
  },
};
(async () => { await tests[test](); context.stopMatchupRefresh(); process.stdout.write("ok"); })()
  .catch((error) => { console.error(error); process.exitCode = 1; });
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MatchupRefreshTests(unittest.TestCase):
    def test_cross_device_refresh_lifecycle(self):
        for scenario in (
            "idle_discovery_and_completion", "background_and_foreground", "leaving_and_replacement",
            "write_race", "failure_recovery_and_timeout",
        ):
            with self.subTest(scenario=scenario):
                result = subprocess.run(
                    [NODE, "-e", RUNNER], input=json.dumps([SCRIPTS, scenario]),
                    capture_output=True, text=True, encoding="utf-8", timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "ok")


if __name__ == "__main__":
    unittest.main()
