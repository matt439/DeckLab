"""Runtime checks for the page's hop to the wake gate (wake-on-request).

Runs the real api() and openWakeGate() from core.js under Node with a fake fetch, storage and location.
No browser, server or external request is started.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


WEB = Path(__file__).resolve().parents[1] / "web"
NODE = shutil.which("node")
ORIGIN = "http://192.168.1.20:8642"
GATE = "http://192.168.1.30:8650"

RUNNER = r"""
const fs = require("fs"), vm = require("vm");
const [core, scenario] = JSON.parse(fs.readFileSync(0, "utf8"));
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return key in this.attrs ? this.attrs[key] : null; }
  addEventListener() {}
  append(...items) { for (const item of items) this.children.push(item); }
  replaceChildren(...items) { this.children = []; this.append(...items); }
}
const quiet = { addEventListener() {}, removeEventListener() {} };
const store = () => { const m = new Map();
  return { getItem: (k) => m.has(k) ? m.get(k) : null, setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) }; };
const document = Object.assign({ createElement: (tag) => new Node(tag), createElementNS: (ns, tag) => new Node(tag),
  createTextNode: (data) => ({ data }), querySelector: () => null, querySelectorAll: () => [],
  documentElement: new Node("html"), body: new Node("body") }, quiet);
const assigned = [], fetched = [];
const location = { origin: "ORIGIN", pathname: "/", search: "", hash: "#/library",
  assign(url) { assigned.push(url); } };
const context = { document, Node, console, setTimeout, clearTimeout, URL, AbortController,
  navigator: {}, location, history: {}, assigned, fetched,
  window: Object.assign({ location, localStorage: store(), sessionStorage: store(),
    matchMedia: () => Object.assign({ matches: false }, quiet) }, quiet) };
context.globalThis = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(core, "utf8"), context, { filename: core });
(async () => {
  const result = await vm.runInContext(`(async () => { ${scenario} })()`, context);
  process.stdout.write(JSON.stringify({ result, assigned, fetched }));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
""".replace("ORIGIN", ORIGIN)

# A fetch that fails for the PC and answers the gate's /__status with GATE_ANSWER.
SETUP = """
const gateReply = (GATE_ANSWER);
const down = (path, opts = {}) => {
  fetched.push({ path, mode: opts.mode || null, poll: (opts.headers || {})["X-Deck-Lab-Poll"] || null });
  if (String(path).endsWith("/__status")) {
    if (gateReply === "fail") return Promise.reject(new TypeError("Failed to fetch"));
    return Promise.resolve({ ok: true, json: async () => gateReply });
  }
  if (opts.signal && opts.signal.aborted) {
    const e = new Error("The operation was aborted."); e.name = "AbortError"; return Promise.reject(e);
  }
  return Promise.reject(new TypeError("Failed to fetch"));
};
globalThis.fetch = down;
rememberWakeGate("GATE");
const attempt = async (call) => { try { await call(); return "ok"; } catch (e) { return [e.status, e.message]; } };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class WakeHopTests(unittest.TestCase):
    def run_scenario(self, body, gate_answer=None):
        answer = {"pc": ORIGIN} if gate_answer is None else gate_answer
        script = SETUP.replace("GATE_ANSWER", json.dumps(answer)).replace("GATE", GATE) + body
        done = subprocess.run([NODE, "-e", RUNNER], input=json.dumps([str(WEB / "core.js"), script]),
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        if done.returncode:
            raise AssertionError(f"node failed: {done.stderr[-2000:]}")
        return json.loads(done.stdout)

    def statuses(self, out):
        return [f["path"] for f in out["fetched"] if f["path"].endswith("/__status")]

    def test_a_read_hops_when_the_gate_names_this_origin(self):
        out = self.run_scenario('return await attempt(() => api("/api/decks"));')
        self.assertEqual(out["assigned"], [GATE + "/#/library"])
        self.assertIn("waking up", out["result"][1])
        self.assertEqual(self.statuses(out), [GATE + "/__status"])
        self.assertEqual([f["mode"] for f in out["fetched"] if f["path"].endswith("/__status")], ["cors"])

    def test_only_once_a_minute(self):
        out = self.run_scenario('await attempt(() => api("/api/decks"));'
                                'return await attempt(() => api("/api/decks"));')
        self.assertEqual(len(out["assigned"]), 1)
        self.assertIn("can't be reached", out["result"][1])

    def test_a_gate_naming_another_pc_never_hops(self):
        for answer in ({"pc": "http://192.168.1.99:8642"}, {"pc": "http://192.168.1.20"}, {}, "fail"):
            with self.subTest(answer=answer):
                out = self.run_scenario('return await attempt(() => api("/api/decks"));', answer)
                self.assertEqual(out["assigned"], [])
                self.assertEqual(out["result"][0], 0)
                self.assertIn("can't be reached", out["result"][1])

    def test_a_failed_check_leaves_the_next_try_free(self):
        # The once-a-minute guard is set only by an actual hop.
        out = self.run_scenario('await attempt(() => api("/api/decks"));'
                                'return session.get("wakeGateTried");', {"pc": "http://elsewhere:1"})
        self.assertIsNone(out["result"])

    def test_writes_polls_aborts_and_watched_runs_never_hop(self):
        cases = {
            "write": 'return await attempt(() => apiWrite("/api/assembly/ticks", { ids: ["a"] }));',
            "put": 'return await attempt(() => api("/x", { method: "PUT" }));',
            "poll": 'return await attempt(() => api("/api/status", { poll: true }));',
            "watched": 'return await attempt(() => api("/api/variant?test=1", { wakeHop: false }));',
            "aborted": 'const c = new AbortController(); c.abort();'
                       'return await attempt(() => api("/api/decks", { signal: c.signal }));',
        }
        for name, body in cases.items():
            with self.subTest(case=name):
                out = self.run_scenario(body)
                self.assertEqual(out["assigned"], [])
                self.assertEqual(self.statuses(out), [])
                self.assertEqual(out["result"][0], 0)
                self.assertIn("can't be reached", out["result"][1])

    def test_options_are_passed_through_and_stripped(self):
        out = self.run_scenario("""
          const seen = [];
          globalThis.fetch = (path, opts) => { seen.push(opts); return Promise.resolve({ ok: true, json: async () => ({}) }); };
          await apiWrite("/api/assembly/ticks", { ids: [] }, "POST", { poll: true, wakeHop: false });
          await api("/api/decks", { wakeHop: false });
          return seen.map((o) => [o.headers["X-Deck-Lab-Poll"] || null, "poll" in o, "wakeHop" in o]);
        """)
        self.assertEqual(out["result"], [["1", False, False], [None, False, False]])

    def test_a_status_answer_without_a_gate_forgets_it(self):
        out = self.run_scenario('rememberWakeGate(undefined); const gone = local.get("wakeGate");'
                                'rememberWakeGate("javascript:alert(1)");'
                                'return [gone, local.get("wakeGate"), await attempt(() => api("/api/decks"))];')
        self.assertIsNone(out["result"][0])
        self.assertIsNone(out["result"][1])
        self.assertEqual(out["assigned"], [])


if __name__ == "__main__":
    unittest.main()
