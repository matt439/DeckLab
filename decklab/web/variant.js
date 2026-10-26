/* Deck Lab's page: tests of changes (simulation wave 3's R15, forge-trial/sim-wave3-contract.md
section 11.6): the test page (#/variant?test=<id>), the editor's "Test this change" row and sheet,
and the deck page's "Tests of changes" list. Every class here starts with "vt-".

A test plays a changed version of a list on its saved list's own games (the same shuffles), so only
games where the change mattered differ, and says whether the change is better, worse or makes little
difference: against one deck, or against the field (every other deck of the format). The server works
everything out (GET /api/variant, /api/variants, /api/variant/estimate); the page shows it.

- The test page: while the test plays, its progress, the next check, a bar per opponent, the time left,
  the live difference range (dashed: wider while games are still being played) and Stop, but no verdict
  words; once it's over, the verdict sentence, each opponent's difference bar, "How this test works",
  and Play more, Back to the editor and Save this change (which asks before replacing another draft).
  It asks again every POLL_MS while the test waits or plays, and stops asking once its page is left.
- The editor (editor-screen.js drawBar calls vtTestRow and vtSyncTestRow): "Test this change" while the
  deck or its commander differs from the saved list and the size is the same; disabled, with the reason,
  for a size change or a sideboard-only change. Below 700 px it's a second row of the bottom bar, full
  width; from 700 px it sits before Save. It opens a sheet: the change as chips, what to test against
  (the field by default), how long (Until it's clear, or a quick look; Quick first for a Commander deck
  or when the worst case passes 30 minutes), each with its time, and Start.
- The deck page (deck.js calls variantTestsSection): the tests of the list, newest first; running ones
  with their progress; finished ones as a swap-test result (sim-ui.js swapResult: the change, the difference,
  a verdict pill and its range) with how long ago they played; "saved" when the list today is the tested
  change. */
"use strict";

const VT_KINDS = { better: "good", slightly_better: "good", little_difference: "info", not_settled: "info",
  slightly_worse: "warn", worse: "crit", stopped: "warn", error: "crit" };
const VT_MINUS = "−";
const VT_LIVE = ["queued", "running"];
const VT_SIDEBOARD = "Sideboard changes aren't tested (games are best of one)";
const VT_SIZE = "Keep the same number of cards to test a change";


// ------------------------------------------------------------------ shared words and parts

/** "+2.4", "−0.6" (points of win rate, from a share). */
function vtPoints(x) {
  const v = Math.round(x * 1000) / 10;
  if (v === 0) return "0.0";
  return (v > 0 ? "+" : VT_MINUS) + Math.abs(v).toFixed(1);
}

/** ["−1 Fiery Annihilation", "+1 Rabid Gnaw"] from {"remove": [[qty, name]], "add": [...]}. */
function vtChangeWords(changes) {
  const c = changes || {};
  return [...(c.remove || []).map(([q, n]) => `${VT_MINUS}${q} ${n}`), ...(c.add || []).map(([q, n]) => `+${q} ${n}`)];
}

function vtChips(changes) {
  const words = vtChangeWords(changes);
  return el("ul", { class: "vt-chips", "aria-label": "The change" },
    words.map((w) => el("li", { class: `vt-chip ${w.startsWith("+") ? "vt-chip-add" : "vt-chip-remove"}`, text: w })));
}

/** "about 25-40 minutes", "up to about 1 h 50 min" (worst: the high end only), or null. */
function vtMinutes(range, worst) {
  if (!range) return null;
  const words = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${Math.round(m % 60)} min` : `${Math.max(1, Math.round(m))} minutes`);
  if (worst) return `up to about ${words(range[1])}`;
  const [lo, hi] = range.map((m) => Math.max(1, Math.round(m)));
  return lo === hi || hi >= 60 ? `about ${words(range[1])}` : `about ${lo}-${hi} minutes`;
}

/** The span either side of 0 that every difference bar on a test page shares (MU-10), so bars can be compared:
 * the widest range end of the field's and every opponent's difference, rounded up to 5 points (at least 5). */
function vtSpan(data) {
  const ends = [];
  const add2 = (x) => { if (x && x.delta != null) ends.push(Math.abs(x.low || 0), Math.abs(x.high || 0), Math.abs(x.delta)); };
  add2(data.field);
  for (const o of data.opponents || []) add2(o.paired);
  if (data.job && data.job.range) add2(data.job.range);
  const widest = Math.max(0.05, ...ends);
  return Math.ceil(widest * 20 - 1e-9) / 20;
}

/** A difference's verdict colour: "good" when its whole range is above 0 (the change helps), "crit" below,
 * "even" across 0. */
function vtDiffKind(low, high) {
  if (low != null && low > 0) return "good";
  if (high != null && high < 0) return "crit";
  return "even";
}

/** The shared scale under the difference bars: "Worse" on the left (red), 0, "Better" on the right (green),
 * with the span's points at each end. */
function vtAxis(span) {
  const points = Math.round(span * 100);
  return el("div", { class: "vt-axis", "aria-hidden": "true" },
    el("span", { class: "vt-axis-worse", text: `${VT_MINUS}${points} · worse` }),
    el("span", { class: "vt-axis-zero", text: "0" }),
    el("span", { class: "vt-axis-better", text: `better · +${points}` }));
}

/** A difference bar centred on 0: the range as a band, the estimate as a tick (dashed: a live range), on the
 * page's shared span (vtSpan), coloured by its verdict (vtDiffKind). */
function vtDiffBar(delta, low, high, { dashed = false, label = "Difference in win rate", span = null } = {}) {
  span = span || Math.max(0.05, Math.abs(low || 0), Math.abs(high || 0));
  const at = (x) => `${50 + (50 * Math.max(-span, Math.min(span, x))) / span}%`;
  const kind = delta == null ? "even" : vtDiffKind(low, high);
  const bar = el("div", { class: `vt-diff vt-diff-${kind}${dashed ? " vt-diff-live" : ""}`, role: "img",
    "aria-label": delta == null ? `${label}: not known yet`
      : `${label}: ${vtPoints(delta)} points (${vtPoints(low)} to ${vtPoints(high)})` },
  el("span", { class: "vt-diff-zero" }));
  if (delta != null && low != null && high != null) {
    bar.append(el("span", { class: "vt-diff-band", style: `left: ${at(low)}; width: calc(${at(high)} - ${at(low)})` }),
      el("span", { class: "vt-diff-tick", style: `left: ${at(delta)}` }));
  }
  return bar;
}

function vtAgainst(test) {
  const a = test && test.against;
  if (typeof a === "string") return "the field";
  return (a && (a.title || a.id)) || "another deck";
}

function vtListWords(version) { return listName(version === "owned" ? "owned" : "target", true); }


// ------------------------------------------------------------------ the test page

/** #/variant?test=<id>: one test of a change. */
function showVariant(params, token) {
  const test = (params.get("test") || "").toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(test)) {
    clear($("#main")).append(errorBox("This test couldn't be shown",
      new ApiError(0, "That link isn't a test's address: part of it may be missing."), null));
    afterRender();
    return;
  }
  const page = { token, test, host: null, timer: 0, data: null };
  load(`/api/variant?test=${test}`, token, (data) => {
    page.host = el("div", { class: "vt-page" });
    $("#main").append(page.host);
    vtDraw(page, data);
  }, { title: "This test couldn't be shown" });
}

function vtLive(data) { return Boolean(data && VT_LIVE.includes(data.status)); }

function vtDraw(page, data) {
  page.data = data;
  if (page.token !== routeToken || !page.host || !page.host.isConnected) return;
  const t = data.test || {};
  const base = t.base || {};
  setTitle(`Test of a change to ${base.title || "a deck"}`);
  const started = t.created ? new Date(t.created) : null;
  const when = started && !Number.isNaN(started.getTime())
    ? started.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false }) : null;
  clear(page.host);
  add(page.host, [
    crumb(deckHref(base.id, base.version), base.title || "The deck"),
    el("h1", { class: "vt-title", text: `Your change to ${base.title || "the deck"} (${vtListWords(base.version)})` }),
    vtChips((t.variant || {}).changes),
    el("p", { class: "sub vt-by", text: [`Against ${vtAgainst(t)}`, t.by ? `started by ${t.by}${when ? `, ${when}` : ""}` : null]
      .filter(Boolean).join(" · ") }),
    el("div", { class: "vt-grid" },
      vtLive(data) ? vtLivePanel(page, data) : vtVerdictPanel(page, data),
      vtRows(data, vtSpan(data))),
  ]);
  afterRender();
  clearTimeout(page.timer);
  if (vtLive(data)) page.timer = setTimeout(() => vtRefresh(page), POLL_MS);
}

async function vtRefresh(page) {
  if (page.token !== routeToken || !page.host || !page.host.isConnected) return;
  try {
    vtDraw(page, await api(`/api/variant?test=${page.test}`));
  } catch (e) {
    if (page.token !== routeToken) return;
    page.timer = setTimeout(() => vtRefresh(page), POLL_MS * 3);      // the PC didn't answer: try again later
  }
}

function vtLivePanel(page, data) {
  const job = data.job || {};
  const bar = progressBar("Games played");
  const total = job.total || 0;
  bar.set(total ? (job.done || 0) / total : 0);
  let left = null;
  if (job.done && job.seconds && total > job.done) {
    const minutes = (job.seconds / job.done) * (total - job.done) / 60;
    left = `At most about ${minutes >= 60 ? `${Math.floor(minutes / 60)} h ${Math.round(minutes % 60)} min`
      : `${Math.max(1, Math.round(minutes))} min`} left`;
  }
  const pairs = Object.values(job.pairs || {});
  const live = job.range;
  return el("section", { class: "vt-panel vt-live", "aria-live": "polite" },
    el("h2", { text: data.status === "queued" ? "Waiting to start" : "Playing" }),
    data.status === "queued" ? el("p", { text: job.ahead ? `${plural(job.ahead, "test or field run")} ahead of it.`
      : "It starts in a moment." }) : null,
    bar.node,
    el("p", { class: "vt-count", text: `${thousands(job.done || 0)} of up to ${thousands(total)} games` }),
    job.next_look ? el("p", { text: `Next check at ${thousands(job.next_look)} games a deck` }) : null,
    left ? el("p", { class: "sub", text: left }) : null,
    pairs.length ? el("ul", { class: "vt-minis", "aria-label": "Each opponent" }, pairs.map((p) => {
      const mini = progressBar(`${(p.opponent && (p.opponent.title || p.opponent.id)) || "Opponent"}: games played`);
      mini.set(p.total ? p.done / p.total : 0);
      return el("li", { class: "vt-mini" },
        el("span", { class: "vt-mini-name", text: (p.opponent && (p.opponent.title || p.opponent.id)) || "Opponent" }),
        mini.node, el("span", { class: "vt-mini-n", text: `${thousands(p.done || 0)} / ${thousands(p.total || 0)}` }));
    })) : null,
    live && live.delta != null ? el("div", { class: "vt-live-range" },
      vtDiffBar(live.delta, live.low, live.high, { dashed: true, span: vtSpan(data) }), vtAxis(vtSpan(data)),
      el("p", { class: "sub", text: `Live range: ${vtPoints(live.low)} to ${vtPoints(live.high)} points, wider while games are still being played` }))
      : null,
    mayStopRuns(job) ? el("div", { class: "actions" },
      el("button", { type: "button", class: "btn btn-danger vt-stop", text: "Stop", onclick: () => vtStop(page) })) : null);
}

async function vtStop(page) {
  if (page.token !== routeToken || !vtLive(page.data) || !mayStopRuns(page.data?.job)) return;
  const profile = state.profile?.id;
  const answer = await ask("Stop this test?",
    ["The games already played are kept, and the result shows them (\"Stopped early\")."],
    [{ text: "Stop the test", kind: "danger", value: "stop" }, { text: "Keep playing", value: "keep" }]);
  if (answer !== "stop" || page.token !== routeToken || state.profile?.id !== profile || !vtLive(page.data) ||
      !mayStopRuns(page.data?.job)) return;
  try {
    const data = await apiWrite("/api/variant/stop", { test: page.test });
    if (page.token !== routeToken || state.profile?.id !== profile) return;
    vtDraw(page, data);
  } catch (e) {
    if (page.token !== routeToken || state.profile?.id !== profile) return;
    toast(e.message);
  }
}

function vtHowItWorks(data) {
  const t = data.test || {};
  const looks = t.looks || [];
  const last = looks[looks.length - 1];
  const items = [el("li", { text: "Both versions get the same shuffles (Deck Lab's deck-order patch), so only games where the change mattered differ." })];
  if (t.outcome === "stopped") items.push(el("li", { text: "It was stopped before its next check: the result shows the games played so far." }));
  else if (last && last.decision === "not_settled") items.push(el("li", { text: `It played the most games it plays (${thousands(last.games_per_opponent)} a deck) without a clear answer.` }));
  else if (last) items.push(el("li", { text: `It stopped at a planned check (${thousands(last.games_per_opponent)} games a deck).` }));
  const shares = (data.opponents || []).map((o) => o.paired && o.paired.saved_share).filter((x) => x != null);
  if (shares.length) {
    const share = shares.reduce((a, b) => a + b, 0) / shares.length;
    items.push(el("li", { text: share > 0
      ? `Pairing the games saved about ${pctShort(share)} of the games a test of two separate runs would need.`
      : "Pairing the games saved nothing here: the change made the games go differently from the start." }));
  } else {
    items.push(el("li", { text: "How much pairing the games saved can't be told yet." }));
  }
  const m = t.starter_mismatch || {};
  if (m.of && m.games > 0.01 * m.of) {
    items.push(el("li", { class: "vt-warn", text: `The two versions didn't get the same games (${thousands(m.games)} of ${thousands(m.of)} had another starter); the comparison is weaker than it should be.` }));
  }
  return el("details", { class: "vt-how" }, el("summary", { text: "How this test works" }), el("ul", {}, items));
}

function vtVerdictPanel(page, data) {
  const t = data.test || {};
  const base = t.base || {};
  const looks = t.looks || [];
  const last = looks[looks.length - 1];
  const kind = VT_KINDS[data.verdict] || "info";
  const field = data.field;
  const one = !field && (data.opponents || []).length === 1 ? (data.opponents[0].paired || null) : null;
  const numbers = field || one;
  // Play more: to the next check, from a stopped test too, until the last check a test makes.
  const planned = Math.max(0, ...looks.filter((l) => !l.stopped).map((l) => l.games_per_opponent));
  const canMore = !data.error && t.outcome !== "error" && (t.outcome === "stopped" || looks.length > 0)
    && planned < (typeof t.against === "string" ? 1600 : 3200);
  return el("section", { class: `vt-panel vt-verdict vt-${kind}` },
    el("h2", { class: "vt-words", text: data.words || (data.status === "none" ? "This test hasn't played yet" : "No verdict yet") }),
    data.error ? el("p", { class: "vt-error", text: data.error }) : null,
    numbers && numbers.delta != null ? [vtDiffBar(numbers.delta, numbers.low, numbers.high, { span: vtSpan(data) }),
      vtAxis(vtSpan(data))] : null,
    data.margin ? el("p", { class: "sub", text: `"Makes little difference" means within ${Math.round(data.margin * 100)} points of win rate` +
      (typeof t.against === "string" ? " against the field." : " against one deck.") }) : null,
    vtHowItWorks(data),
    el("div", { class: "actions vt-actions" },
      canMore ? el("button", { type: "button", class: "btn btn-primary", text: "Play more", "data-run": true,
        onclick: () => vtMore(page) }) : null,
      base.id && /^(casual|commander)\//.test(base.id)
        ? el("a", { class: "btn", href: editHref(base.id, base.version), text: "Back to the editor" }) : null,
      base.id && /^(casual|commander)\//.test(base.id)
        ? el("button", { type: "button", class: "btn", text: "Save this change", onclick: () => vtSaveChange(data) }) : null));
}

async function vtMore(page) {
  try {
    vtDraw(page, await apiWrite("/api/variant/more", { test: page.test }));
  } catch (e) {
    toast(e.message);
  }
}

function vtRows(data, span = vtSpan(data)) {
  const rows = data.opponents || [];
  if (!rows.length) return null;
  return el("section", { class: "vt-rows" },
    el("h2", { text: rows.length === 1 ? "The games" : "Against each deck" }),
    el("p", { class: "sub", text: "How much the change moves the win rate against each deck, in points: the band is " +
      "where it probably lies, and every bar uses the same scale." }),
    el("ul", { class: "vt-list" }, rows.map((o) => {
      const p = o.paired || {};
      const name = o.title || o.id || "Opponent";
      const head = o.base_key ? el("a", { href: `#/matchup?key=${o.base_key}`, text: name }) : el("span", { text: name });
      if (o.dropped) {
        return el("li", { class: "vt-row vt-row-dropped" }, el("div", { class: "vt-row-name" }, head),
          el("p", { class: "sub", text: o.dropped }));
      }
      return el("li", { class: "vt-row" },
        el("div", { class: "vt-row-name" }, head,
          el("span", { class: "vt-row-n", text: `${thousands(p.n || o.games || 0)} paired games` })),
        vtDiffBar(p.delta, p.low, p.high, { label: `${name}: difference in win rate`, span }),
        el("p", { class: "sub", text: [
          p.delta != null ? `${vtPoints(p.delta)} points (${vtPoints(p.low)} to ${vtPoints(p.high)})` : "No difference yet",
          p.same != null ? `played out the same in ${pctShort(p.same)} of games` : null].filter(Boolean).join(" · ") }));
    })), vtAxis(span));
}

/** "Save this change": the editor opens with the tested list as its draft (asking first when it already
 * holds other unsaved changes to that list). */
async function vtSaveChange(data) {
  const t = data.test || {};
  const base = t.base || {};
  let view;
  try {
    view = await api(`/api/deck/edit?id=${encodeURIComponent(base.id)}`);
  } catch (e) {
    toast(e.message);
    return;
  }
  const version = base.version === "owned" ? "owned" : "target";
  const key = `draft.${state.profile.id}.${base.id}.${version}`;
  if (local.get(key)) {
    const answer = await ask("Replace your unsaved changes?",
      [`Replace your unsaved changes to ${base.title} with this tested change?`],
      [{ text: "Replace them", kind: "primary", value: "replace" }, { text: "Keep my changes", value: "keep" }]);
    if (answer !== "replace") return;
  }
  const lists = vtApplyChange(view.lists[version] || {}, (t.variant || {}).changes || {});
  local.set(key, JSON.stringify({ v: 1, saved: Date.now(), sha256: view.sha256, starting: false,
    base: { lists: view.lists[version] || {}, fields: pickFields(view.fields) },
    lists, fields: pickFields(view.fields), addSection: "Deck" }));
  location.hash = editHref(base.id, version);
}

/** The saved list's lines with a test's change made: copies taken off the lines of each removed name
 * (Commander first, then the deck), and added names put on a line of that name or a new one. */
function vtApplyChange(sections, changes) {
  const out = {};
  for (const [name, lines] of Object.entries(sections)) out[name] = lines.map((l) => ({ ...l }));
  const front = (n) => n.split(" // ")[0].trim();
  for (const [qty, name] of changes.remove || []) {
    let left = qty;
    for (const section of ["Commander", "Deck"]) {
      for (const line of out[section] || []) {
        if (left && front(line.name) === name) {
          const take = Math.min(left, line.qty);
          line.qty -= take;
          left -= take;
        }
      }
      if (out[section]) out[section] = out[section].filter((l) => l.qty > 0);
    }
  }
  for (const [qty, name] of changes.add || []) {
    const deck = out.Deck || (out.Deck = []);
    const line = deck.find((l) => front(l.name) === name);
    if (line) line.qty += qty;
    else deck.push({ qty, name });
  }
  return out;
}


// ------------------------------------------------------------------ the deck page's list

/** The deck page's "Tests of changes" list (under "Against the field"), or null for a deck that can't
 * be edited here (a product deck or pairing). It fills itself in from /api/variants. */
function variantTestsSection(data) {
  const s = data && data.summary;
  if (!s || s.read_only || !/^(?:[^/]+\/)?(?:casual|commander)\//.test(s.id)) return null;
  const version = data.version === "owned" ? "owned" : "target";
  const body = el("div", { class: "vt-tests-body" }, loadingBox("Loading tests of changes..."));
  const section = el("section", { id: "sec-tests", class: "vt-tests", "aria-labelledby": "h-tests" },
    el("h2", { id: "h-tests", text: "Tests of changes" }), body);
  const token = routeToken, viewer = state.profile?.id;
  if (new URLSearchParams(location.hash.split("?")[1] || "").get("part") === "tests") {
    setTimeout(() => {
      if (token === routeToken && viewer === state.profile?.id && section.isConnected) jumpTo("sec-tests");
    }, 0);
  }
  api(`/api/variants?id=${encodeURIComponent(s.id)}&version=${version}`).then((answer) => {
    clear(body);
    const tests = answer.tests || [];
    if (!tests.length) {
      body.append(el("p", { class: "sub", text: "No tests yet. In the editor, change some cards and tap \"Test this change\" to see whether the change helps." }));
      return;
    }
    body.append(el("ul", { class: "vt-test-list" }, tests.map(vtTestItem)));
  }).catch((e) => {
    if (e.status === 501) section.remove();
    else clear(body).append(el("p", { class: "sub", text: `The tests couldn't be loaded: ${e.message}` }));
  });
  return section;
}

/** One test in the deck page's list: while it plays, "Testing: −1 A, +1 B (40%)"; once it's over, the swap-test
 * result (the change, the difference in points, its verdict pill, its range, what it was against and how many
 * games a deck), how long ago it played, and "saved" when the list today is the tested change. */
function vtTestItem(t) {
  const href = `#/variant?test=${t.test}`;
  const saved = t.saved ? el("span", { class: "vt-saved", text: "saved" }) : null;
  if (t.running) {
    const words = `Testing: ${vtChangeWords(t.changes).join(", ")}` + (t.total ? ` (${pctShort((t.done || 0) / t.total)})` : "");
    return el("li", { class: "vt-test-item" }, el("a", { href, text: words }), saved);
  }
  const against = t.against === "field" ? "the field" : t.against;
  const how = { stopped: "stopped early", error: "couldn't finish" }[t.verdict] || (t.delta == null ? "not settled" : null);
  const facts = [`against ${against}`, t.games_per_opponent ? `${thousands(t.games_per_opponent)} games a deck` : null, how];
  return el("li", { class: "vt-test-item" },
    el("a", { href, class: "vt-test-link" }, swapResult({ changes: t.changes, delta: t.delta, low: t.low, high: t.high,
      verdict: t.verdict, gamesText: facts.filter(Boolean).join(" · ") })),
    freshnessBadge(t.when, { size: "row" }), saved);
}


// ------------------------------------------------------------------ the editor's Test row and sheet

/** {name: copies} over the sections that play (the deck and the commander), or the sideboard. */
function vtTally(sections, names) {
  const out = new Map();
  for (const name of names) {
    for (const line of (sections && sections[name]) || []) out.set(line.name, (out.get(line.name) || 0) + line.qty);
  }
  return out;
}

function vtSameTally(a, b) {
  if (a.size !== b.size) return false;
  for (const [k, v] of a) if (b.get(k) !== v) return false;
  return true;
}

/** Whether "Test this change" applies to the editor now: {show, ok, why}. */
function vtTestState(ed) {
  if (!ed || ed.mode !== "edit" || !ed.hasFileList) return { show: false };
  const plays = ["Commander", "Deck"];
  const mainChanged = !vtSameTally(vtTally(ed.lists, plays), vtTally(ed.base.lists, plays));
  const sideChanged = !vtSameTally(vtTally(ed.lists, ["Sideboard"]), vtTally(ed.base.lists, ["Sideboard"]));
  if (!mainChanged) return sideChanged ? { show: true, ok: false, why: VT_SIDEBOARD } : { show: false };
  const kind = currentKind();
  if (mainCount(ed.lists, kind) !== mainCount(ed.base.lists, kind)) return { show: true, ok: false, why: VT_SIZE };
  return { show: true, ok: true, why: null };
}

/** The editor Forge panel's Test row (made once; vtSyncTestRow updates it). */
function vtTestRow() {
  const button = el("button", { type: "button", class: "btn vt-test-btn", text: "Test this change", onclick: () => vtOpenTestSheet() });
  const why = el("span", { class: "vt-test-why" });
  const row = el("div", { class: "vt-test-row", hidden: true }, button, why);
  row.vt = { button, why };
  return row;
}

function vtSyncTestRow(row) {
  if (!row || !row.vt) return;
  const found = vtTestState(editor);
  row.hidden = !found.show;
  row.vt.button.disabled = !found.ok;
  row.vt.why.textContent = found.why || "";
  row.vt.why.hidden = !found.why;
  if (found.why) row.vt.button.setAttribute("aria-describedby", "vt-test-why");
  row.vt.why.id = "vt-test-why";
}

/** What the editor's draft changes, by name: {remove: [[qty, name]], add: [...]}. */
function vtDraftChanges(ed) {
  const plays = ["Commander", "Deck"];
  const before = vtTally(ed.base.lists, plays);
  const after = vtTally(ed.lists, plays);
  const remove = [], added = [];
  for (const [name, n] of before) if (n > (after.get(name) || 0)) remove.push([n - (after.get(name) || 0), name]);
  for (const [name, n] of after) if (n > (before.get(name) || 0)) added.push([n - (before.get(name) || 0), name]);
  return { remove, add: added };
}

async function vtOpenTestSheet() {
  const ed = editor;
  if (!ed || !vtTestState(ed).ok) return;
  const sheet = openSheet("Test this change", { wide: true });
  sheet.dialog.classList.add("vt-sheet");
  const kind = currentKind();
  const pick = { against: "field", mode: null, estimate: null };
  const againstHost = el("div", { class: "vt-sheet-part" });
  const howHost = el("div", { class: "vt-sheet-part" });
  const problem = el("p", { class: "vt-error", hidden: true });
  add(sheet.body, [vtChips(vtDraftChanges(ed)),
    el("h3", { text: "Test against" }), againstHost,
    howHost, problem, runsAllowed() ? null : el("p", { class: "run-blocked", text: runGate().why })]);
  let library = state.library;
  if (!library) {
    try { library = state.library = await api("/api/decks"); } catch (e) { library = { decks: [] }; }
  }
  const others = (library.decks || []).filter((d) => !d.error && d.id !== ed.id && (d.kind === "commander") === (kind === "commander")
    && !d.id.startsWith(BOX_PREFIX));
  const select = el("select", { id: "vt-against", "aria-label": "The deck to test against",
    onchange: () => { pick.against = select.value; refresh(); } },
  others.map((d) => el("option", { value: d.id, text: d.title })));
  const radio = (name, value, text, checked, onchange) => el("label", { class: "vt-choice" },
    el("input", { type: "radio", name, value, checked: checked || null, onchange }), el("span", {}, text));
  function drawAgainst(fieldSize, fieldOk) {
    clear(againstHost).append(
      radio("vt-against", "field", fieldOk ? `The field (${plural(fieldSize, "deck")})` : "The field (not available yet)",
        pick.against === "field", () => { pick.against = "field"; select.disabled = true; refresh(); }),
      radio("vt-against", "deck", "One deck:", pick.against !== "field", () => { pick.against = select.value; select.disabled = false; refresh(); }),
      select);
    select.disabled = pick.against === "field";
    const fieldInput = againstHost.querySelector('input[value="field"]');
    if (fieldInput && !fieldOk) fieldInput.disabled = true;
  }
  function drawHow(est) {
    const times = est || {};
    const maxAhead = (times.max && times.max.ahead) || 1600;
    if (!pick.mode) pick.mode = times.default || (kind === "commander" ? "quick" : "ahead");
    // The run vocabulary (MU-05): Quick look or Settle it, each with its one time estimate.
    const options = [
      { id: "quick", title: "Quick look", sub: `${thousands((times.max && times.max.quick) || 200)} games a deck: a first idea.`,
        time: vtMinutes(times.quick, false) },
      { id: "ahead", title: "Settle it", sub: `Plays until it's clear whether the change helps (up to ` +
        `${thousands(maxAhead)} games a deck).`, time: vtMinutes(times.ahead, true) },
    ];
    clear(howHost).append(runChoiceControl(options, pick.mode, (mode) => { pick.mode = mode; }, { label: "How long to play" }).node);
  }
  async function refresh() {
    const against = pick.against === "field" ? "field" : pick.against;
    const q = `/api/variant/estimate?id=${encodeURIComponent(ed.id)}&version=${ed.version}&against=${encodeURIComponent(against)}`;
    try {
      const est = await api(q);
      if (sheet.closed) return;
      pick.estimate = est;
      if (against === "field") {
        drawAgainst(est.opponents, est.available);
        if (!est.available) {
          if (others.length) { pick.against = others[0].id; drawAgainst(0, false); refresh(); return; }
          problem.hidden = false;
          problem.textContent = est.problem || "There's no deck to test against.";
        }
      }
      drawHow(est);
    } catch (e) {
      if (sheet.closed) return;
      drawHow(null);
    }
  }
  drawAgainst(0, true);
  drawHow(null);
  refresh();
  sheetActions(sheet, [{ text: "Start", kind: "primary", onclick: () => start(), disabled: !runsAllowed() },
    { text: "Cancel", onclick: () => sheet.close() }]);
  async function start() {
    const against = pick.against === "field" ? "field" : { id: pick.against, version: "target" };
    try {
      const answer = await apiWrite("/api/variant/run", { id: ed.id, version: ed.version, list: sendList(ed.lists),
        against, mode: pick.mode || "ahead" });
      const id = answer.test && answer.test.test;
      if (typeof syncRunsPill === "function") syncRunsPill(true);     // runs-pill.js: the top bar's run activity
      clear(sheet.body).append(el("p", { text: "The test has started. It goes on while you keep editing, and its page shows how it's going." }),
        vtChips(vtDraftChanges(ed)));
      sheetActions(sheet, [{ text: "Keep editing", kind: "primary", onclick: () => sheet.close() },
        id ? { text: "See the test", onclick: () => { sheet.close(); location.hash = `#/variant?test=${id}`; } } : null]);
    } catch (e) {
      problem.hidden = false;
      problem.textContent = e.message;
    }
  }
}
