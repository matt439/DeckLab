/* Deck Lab's page: the deck view's "Against popular decks" part (the gauntlet, decklab/design/gauntlet.md
section 6), from GET /api/gauntlet: the list against a balanced sample of decks from outside the house (EDHREC's
average Commander decks, Wizards precons, Forge's bundled 60-card decks), read by colour, number of colours, style
and tier, then one row per opponent, hardest first. Its choices (how many opponents, their colours, styles and
tiers) and the games a deck sit in the play box with the time estimate, then Play; while a run waits or plays it
shows its progress and Stop, asking again every GT_POLL_MS as field.js does (it stops when the page is left).
Before a catalogue is built on the PC it shows the command that builds it.
E3-S33: with no choices it's the format's standard sample (the same opponents for every deck of the format), and
its headline (gtHeadline, also the Overview's panel, deck-overview.js) is the equal-weight average over them and
how many it's ahead of, even with and behind. Once there are games the results come before the play box. Another
sample stays in the address as &gsample=<id> (deck.js's deckAddress keeps it), with Back to the standard sample.
E3-S38: up to every playable deck of the chosen tiers ("All", Commander only), the run's time said plainly above
Play, and over the server's overnight_minutes that it's an overnight run that keeps the PC awake.
E3-S34: results are never deleted. When the list changed since its last test, its figure before the change
(gtBeforeLine, muted), then once re-tested both over the same opponents, an opponent marked Moved only when its two
ranges don't overlap; saved results an older Forge, other settings, another pilot or a rebuilt catalogue played
are said plainly (gtOlderLine). Play stays the usual button: nothing plays by itself.
E3-S51: the typical turn the list wins in and loses in (median and middle half), overall under the headline (gtClock,
with what was left out and, for Commander, that the gauntlet isn't a four-player pod) and on each group and opponent.
Every class this file and gauntlet.css add starts with "gt-"; it also uses the page's shared ones (deck-section,
segmented, filter-chips, box, btn, sub, empty, more). Uses core.js's helpers, sim-ui.js's winRateFigure and
rangeBar, matchups.js's runChoiceControl, runsAllowed, metaWords and gamesWords, editor.js's ask() and app.js's
jumpTo (a link with part=gauntlet scrolls here). */
"use strict";

const GT_POLL_MS = 1500;          // how often a gauntlet run's progress is asked for while it waits or plays
const GT_BUDGETS = [["fixed:50", "Quick look"], ["fixed:100", "Settle it"], ["fixed:200", "Precise"]];
const GT_BUDGET_SUB = { "fixed:50": "A first idea: 50 games against each deck.",
  "fixed:100": "100 games against each deck: each one's rate to about ±10 points.",
  "fixed:200": "200 games against each deck, so the groups are closer." };
const GT_STYLES = { aggro: "Aggro", midrange: "Midrange", control: "Control", combo: "Combo", ramp: "Ramp" };
const GT_TIERS = { core: "Core", upgraded: "Upgraded", precon: "Precons", easy: "Easy", medium: "Medium",
  hard: "Hard", "very hard": "Very hard" };
const GT_SAMPLE_RE = /^sample:[0-9a-f]{12}$/;
const GT_FORMATS = { commander: "Commander", constructed: "60-card" };
const GT_GROUPS = [["colour", "Colour"], ["identity_size", "Colours"], ["style", "Style"], ["tier", "Tier"]];

/** The deck page's "Against popular decks" part (id "sec-gauntlet"), or null for a Beginner Box half. */
function gauntletSection(data) {
  const s = data.summary;
  if (s.id.startsWith(BOX_PREFIX)) return null;
  const content = el("div", { class: "gt-content" }, loadingBox("Loading how this list does against popular decks…"));
  const section = el("section", { class: "deck-section gt-section", id: "sec-gauntlet", "aria-labelledby": "h-gauntlet" },
    el("h2", { id: "h-gauntlet", text: "Against popular decks" }), content);
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const named = params.get("gsample");
  // sample: a saved sample the address names (&gsample=), asked for by its id until a choice changes.
  const ctx = { section, content, token: routeToken, id: s.id, version: data.version, answer: null, choice: null,
    sample: named && GT_SAMPLE_RE.test(named) ? named : null, lost: false, budget: null, by: "colour", open: false,
    timer: 0, busy: false, asked: 0 };
  gtRefresh(ctx);
  const part = params.get("part");
  if (part === "gauntlet") setTimeout(() => { if (ctx.token === routeToken) jumpTo("sec-gauntlet"); }, 0);
  return section;
}

function gtHere(ctx) { return ctx.token === routeToken; }
function gtPlaying(a) { return !!a && (a.status === "queued" || a.status === "running"); }

/** The view's address: the deck and, once chosen, the sample's choices (the server's defaults until then). */
function gtUrl(ctx) {
  const q = new URLSearchParams({ id: ctx.id, version: ctx.version });
  const c = ctx.choice;
  if (ctx.sample) q.set("sample", ctx.sample);
  else if (c) {
    q.set("size", String(c.size));
    if (c.colours) q.set("colours", c.colours);
    if (c.styles.length) q.set("styles", c.styles.join(","));
    const tiers = gtTiersAsked(c, ctx.answer);
    if (tiers.length) q.set("tiers", tiers.join(","));
  }
  if (state.profile) q.set("profile", state.profile.id);
  return `/api/gauntlet?${q}`;
}

/** timer: the poll while a run plays, which counts as use but never leaves the page for the wake gate. */
async function gtRefresh(ctx, { timer = false } = {}) {
  clearTimeout(ctx.timer);
  if (!gtHere(ctx) || ctx.busy) return;
  const asked = ++ctx.asked;
  try {
    const answer = await api(gtUrl(ctx), timer ? { wakeHop: false } : {});
    if (!gtHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    gtKeepPlace(() => gtDraw(ctx, answer));
  } catch (e) {
    if (!gtHere(ctx) || ctx.busy || asked !== ctx.asked) return;
    if (ctx.sample && e && e.status === 404) {
      // The address names a sample that isn't saved (drawn but never played): the standard sample instead.
      Object.assign(ctx, { sample: null, choice: null, lost: true });
      gtRefresh(ctx);
      return;
    }
    gtKeepPlace(() => clear(ctx.content).append(loadFailed("How this list does against popular decks", e,
      () => gtRefresh(ctx))));
    return;
  }
  gtSchedule(ctx);
}

function gtKeepPlace(change) { return typeof keepPlace === "function" ? keepPlace(change) : change(); }

function gtSchedule(ctx) {
  clearTimeout(ctx.timer);
  if (!gtHere(ctx) || !gtPlaying(ctx.answer)) return;
  ctx.timer = setTimeout(() => {
    if (gtHere(ctx) && ctx.section.isConnected) gtRefresh(ctx, { timer: true });
  }, GT_POLL_MS);
}

/** The sample in the address: &gsample=<id> for a saved one that isn't the standard sample, nothing otherwise (a
 * sample drawn from the choices isn't saved until it's played, so its id wouldn't come back). */
function gtAddress(ctx, a) {
  if (!gtHere(ctx) || typeof parseHash !== "function") return;
  const { path, params } = parseHash();
  if (path !== "deck" || params.get("id") !== ctx.id) return;
  const id = a.catalogue && a.sample && a.sample.saved && !a.is_standard ? a.sample.id : null;
  if (id) params.set("gsample", id); else params.delete("gsample");
  const hash = `#/deck?${params.toString()}`;
  if (hash !== location.hash) history.replaceState(history.state, "", hash);
}

function gtDraw(ctx, a) {
  ctx.answer = a;
  gtAnnounce(ctx, a);
  gtAddress(ctx, a);
  clear(ctx.content);
  if (!a.catalogue) {
    ctx.content.append(el("div", { class: "empty gt-empty" },
      el("p", { text: `There are no popular ${a.format === "commander" ? "Commander" : "60-card"} decks on the PC yet.` }),
      a.build_command
        ? el("p", { class: "sub", text: "Build them once on the PC (it takes a few minutes):" })
        : el("p", { class: "sub", text: "An admin builds them once on the PC." }),
      a.build_command ? el("pre", { class: "gt-command" }, el("code", { text: a.build_command })) : null));
    return;
  }
  if (!ctx.choice) ctx.choice = gtChoiceOf(a);
  if (!ctx.budget) ctx.budget = a.default_budget || "fixed:100";
  const played = (a.games || 0) > 0;
  const stale = !played && (a.before || a.older);
  add(ctx.content, [
    el("p", { class: "sub", text: "How this list does against popular decks from outside the house, from Forge's AI " +
      "playing them (best of one). They never count in Rankings." }),
    gtStandardLine(ctx, a),
    // Results first at every width (E3-S33); from 1,600 px the play box sits to their right.
    played || gtPlaying(a)
      ? el("div", { class: "gt-layout" },
        played ? el("div", { class: "gt-main" }, gtHeadline(a), gtClock(a), gtBeforeLine(a),
          gtOlderLine(a, { note: true }), gtGroups(ctx, a), gtRows(a)) : null,
        el("div", { class: "gt-side" }, stale ? [gtBeforeLine(a), gtOlderLine(a)] : null, gtPlayBox(ctx, a)))
      // E3-S34: the list changed, or its results are from an older Forge: the old figure muted, then Play as usual.
      : stale ? el("div", { class: "gt-empty gt-stale" }, gtBeforeLine(a), gtOlderLine(a),
        el("p", { class: "sub", text: `Play ${plural((a.sample || {}).decks || 0, "popular deck")} to test this list ` +
          "with today's Forge." }),
        gtPlayBox(ctx, a, { inEmpty: true }))
      : el("div", { class: "empty gt-empty" },
        el("p", { text: "No games against popular decks yet." }),
        el("p", { class: "sub", text: `Play ${plural((a.sample || {}).decks || 0, "popular deck")} to see how this ` +
          "list does by colour and by style." }),
        gtPlayBox(ctx, a, { inEmpty: true })),
    gtCredit(a), gtBuiltLine(a.catalogue), gtScreening(a.catalogue?.screening)]);
}

/** The choices the server drew its sample from, as the controls hold them. */
/** The tiers to ask for: the chips ticked, or with none ticked every tier the format has ("every tier", as the
 * summary says; asking for none would give the server's default tiers). */
function gtTiersAsked(c, a) {
  return c.tiers.length ? c.tiers : [...(((a || {}).options || {}).tiers || [])];
}

function gtChoiceOf(a) {
  const f = (a.sample || {}).filters || {};
  const size = (a.sample || {}).all ? "all" : (a.sample || {}).size || a.default_size || 20;
  return { size, colours: f.colours || "",
    styles: Array.isArray(f.styles) ? [...f.styles] : [], tiers: Array.isArray(f.tiers) ? [...f.tiers] : [] };
}

/** Whether this is the standard sample: a line saying so (after "That sample isn't saved on the PC." when the
 * address named one that isn't), or for another sample Back to the standard sample (not while it plays: a list
 * shows its playing run's sample until the run ends). */
function gtStandardLine(ctx, a) {
  const std = a.standard;
  if (!std) return null;
  if (a.is_standard) {
    const tiers = (std.tiers || []).map((t) => (GT_TIERS[t] || t).toLowerCase()).join(" and ");
    return el("p", { class: "gt-small gt-standard", text: `${ctx.lost ? "That sample isn't saved on the PC. " : ""}` +
      `The standard sample: the same ${std.size} ` +
      `${tiers ? `${tiers} ` : ""}opponents for every ${GT_FORMATS[a.format] || ""} deck, so their results compare.` });
  }
  if (gtPlaying(a)) {
    return el("p", { class: "gt-small gt-standard",
      text: "Not the standard sample. The standard sample shows again when this run ends." });
  }
  return el("p", { class: "gt-small gt-standard" }, "Not the standard sample. ",
    el("button", { type: "button", class: "btn btn-quiet btn-inline", text: "Back to the standard sample",
      onclick: () => { Object.assign(ctx, { sample: null, choice: null, lost: false }); gtRefresh(ctx); } }));
}

/** "Ahead of 3 · even with 6 · behind 3 · not settled against 2" (a count of 0 left out), or null. */
function gtTallyWords(t) {
  const n = t || {};
  const parts = [n.ahead ? `ahead of ${n.ahead}` : null, n.even ? `even with ${n.even}` : null,
    n.behind ? `behind ${n.behind}` : null, n.unsettled ? `not settled against ${n.unsettled}` : null].filter(Boolean);
  return parts.length ? capitalise(parts.join(" · ")) : null;
}

/** "20 popular Commander decks". */
function gtDecksWords(a) { return plural(a.of || 0, `popular ${GT_FORMATS[a.format] || "Forge"} deck`); }

/** The headline over the sample's opponents (the view's or the summary's overall, played, of, games, tally and
 * updated): the equal-weight win rate as a hero figure in ink with its range bar and age, how many it's ahead of,
 * even with and behind, and how many are tested so far. Null before any opponent has games. */
function gtHeadline(a, { cls = "gt-headline" } = {}) {
  const o = a.overall;
  if (!o || o.rate == null || !a.played) return null;
  const rate = gtRate(o.rate, o.low, o.high);
  const tally = gtTallyWords(a.tally);
  return el("div", { class: cls },
    el("p", { class: "gt-headline-what", text: `Against ${gtDecksWords(a)}:` }),
    el("div", { class: "gt-figure" },
      winRateFigure(rate, { size: "hero", what: `Win rate against these ${gtDecksWords(a)}`, games: a.games || null,
        barred: true }),
      freshnessBadge(a.updated)),
    rangeBar(rate, { axis: true, decorative: true }),
    tally ? el("p", { class: "gt-tally", text: tally }) : null,
    a.played < a.of ? el("p", { class: "gt-small", text: `${a.played} of ${a.of} opponents tested so far.` }) : null);
}

// ------------------------------------------------------------------ E3-S51: the clock

/** A turn as said: 8, or 8.5 for a median between two. */
function gtTurn(n) { return Number.isInteger(n) ? String(n) : n.toFixed(1); }

/** One side of a clock ({games, median, low, high}): "wins on turn 8 (7–10)", the middle half in brackets; with
 * fewer games than the server's minimum (median null) its count only, "3 wins, too few for a typical turn". */
function gtClockSide(side, verb, one, many) {
  if (!side || !side.games) return null;
  if (side.median == null) return `${plural(side.games, one, many)}, too few for a typical turn`;
  const middle = side.low != null && side.high != null && side.low !== side.high
    ? ` (${gtTurn(side.low)}–${gtTurn(side.high)})` : "";
  return `${verb} on turn ${gtTurn(side.median)}${middle}`;
}

/** A clock ({won, lost, left_out}) in words: "Wins on turn 8 (7–10), loses on turn 11 (9–12)"; null without a
 * game won or lost. */
function gtClockWords(c) {
  if (!c) return null;
  const parts = [gtClockSide(c.won, "wins", "win"), gtClockSide(c.lost, "loses", "loss", "losses")].filter(Boolean);
  return parts.length ? capitalise(parts.join(", ")) : null;
}

/** What a clock left out: "Left out: 2 draws, 1 timeout and 3 games without a round count."; null for none. */
function gtLeftOutWords(c) {
  const n = (c && c.left_out) || {};
  const parts = [n.draws ? plural(n.draws, "draw") : null, n.timeouts ? plural(n.timeouts, "timeout") : null,
    n.errors ? plural(n.errors, "error") : null,
    n.no_rounds ? `${plural(n.no_rounds, "game")} without a round count` : null].filter(Boolean);
  if (!parts.length) return null;
  const last = parts.pop();
  return `Left out: ${parts.length ? `${parts.join(", ")} and ${last}` : last}.`;
}

/** A clock's line under a group or an opponent, or null. */
function gtClockLine(c) {
  const words = gtClockWords(c);
  return words ? el("span", { class: "gt-small gt-clock-line", text: words }) : null;
}

/** The overall clock under the headline (E3-S51): the typical turn of games won and of games lost against every
 * sampled opponent, what it counts (the answer's clock_label: "simulated Forge games, 1v1, turns each" for
 * Commander), what was left out and, for Commander, that the gauntlet isn't a four-player pod (clock_note). Null
 * without a game won or lost. */
function gtClock(a) {
  const c = (a.overall || {}).clock;
  const words = gtClockWords(c);
  if (!words) return null;
  const about = [a.clock_label ? `Median and middle half: ${a.clock_label}.` : null, gtLeftOutWords(c)];
  return el("div", { class: "gt-clock" },
    el("p", { class: "gt-clock-what", text: `${words}.` }),
    el("p", { class: "gt-small", text: about.filter(Boolean).join(" ") }),
    a.clock_note ? el("p", { class: "gt-small", text: a.clock_note }) : null);
}

// ------------------------------------------------------------------ E3-S34: kept through a change

// The older results today's keys don't find (the answer's older.reason), in words; catalogue's names a count.
const GT_OLDER = { forge: "Results from an older Forge aren't shown.",
  settings: "Results played with other Forge settings aren't shown.",
  pilot: "Results played with another AI pilot aren't shown.",
  unknown: "Forge's version on the PC can't be confirmed now, so older results can't be matched." };
const GT_OLDER_WITH = { forge: "With the older Forge", settings: "With the other settings", pilot: "With the other pilot" };

/** {rate, low, high} -> "41% (33–49)", or null without a rate. */
function gtFigureWords(f) {
  if (!f || f.rate == null) return null;
  const range = simRange(f);
  return range ? `${simPoints(f.rate)}% (${range})` : `${simPoints(f.rate)}%`;
}

/** A result's time as "2 Nov", or null. */
function gtWhen(when) {
  const d = when ? new Date(when) : null;
  return d && !Number.isNaN(d.getTime()) ? simDay(d) : null;
}

/** A muted range bar (no band: the figure is out of date), beside a badge when given. */
function gtBeforeBar(f, badge = null) {
  const rate = gtRate(f.rate, f.low, f.high);
  return el("div", { class: "gt-before-bar" }, rangeBar(rate, { compact: true, muted: true, decorative: true }), badge);
}

/** The list's figure before its last change (E3-S34), muted and in words: after a re-test "Before this change 41%
 * (33–49) · Now 47% (39–55), same 20 opponents." (and how many moved: ranges that don't overlap); with no games
 * for the new list yet "The list changed since its last test (2 Nov). Before: 41% (33–49)." Null without a before. */
function gtBeforeLine(a) {
  const c = a.compare, b = a.before;
  const then = c && gtFigureWords(c.before), now = c && gtFigureWords(c.now);
  if (c && c.same && then && now) {
    return el("div", { class: "gt-before" },
      el("p", {}, simNumbers(`Before this change ${then} · Now ${now}, same ${plural(c.same, "opponent")}.`)),
      c.moved ? el("p", { class: "gt-small" }, simNumbers(`${plural(c.moved, "opponent")} moved: the two ranges ` +
        "don't overlap.")) : null);
  }
  if (!b) return null;
  const figure = gtFigureWords(b), when = gtWhen(b.updated);
  if ((a.games || 0) > 0 || a.played) {
    return figure ? el("div", { class: "gt-before" },
      el("p", {}, simNumbers(`Before this change ${figure}${when ? ` (${when})` : ""}.`))) : null;
  }
  return el("div", { class: "gt-before" },
    el("p", {}, simNumbers(`The list changed since its last test${when ? ` (${when})` : ""}.` +
      (figure ? ` Before: ${figure}.` : ""))),
    figure ? gtBeforeBar(b, freshnessBadge(b.updated, { changed: true })) : null);
}

/** The list's saved results today's keys don't find (an older Forge, other settings, another pilot, opponents
 * rebuilt), said plainly, with the newest single-engine group's figure muted when there is one; an earlier list's
 * (older.earlier: the list changed too) says the list changed first. note: only the sentence, small, under a
 * headline. Null without any. */
function gtOlderLine(a, { note = false } = {}) {
  const o = a.older;
  if (!o || !o.reason) return null;
  const n = Number(o.opponents) || 0;
  const text = o.reason === "catalogue"
    ? `${n ? (n === 1 ? "1 opponent's list" : `${thousands(n)} opponents' lists`) : "Some opponents' lists"} changed ` +
      "when popular decks were rebuilt, so their results aren't shown."
    : GT_OLDER[o.reason];
  if (!text) return null;
  // earlier: an earlier list's results, which today's list has none of yet (the list and Forge both changed).
  const said = o.earlier ? `The list changed since its last test. ${text}` : text;
  if (note) return el("p", { class: "gt-small gt-older" }, simNumbers(said));
  const figure = GT_OLDER_WITH[o.reason] ? gtFigureWords(o.overall) : null, when = gtWhen(o.updated);
  const label = o.earlier && GT_OLDER_WITH[o.reason]
    ? `Before the change, ${GT_OLDER_WITH[o.reason].charAt(0).toLowerCase()}${GT_OLDER_WITH[o.reason].slice(1)}`
    : GT_OLDER_WITH[o.reason];
  return el("div", { class: "gt-before gt-older" }, el("p", {}, simNumbers(said)),
    figure ? el("p", {}, simNumbers(`${label}: ${figure}, ${n} of ${o.of || n} opponents` +
      `${when ? ` (${when})` : ""}.`)) : null,
    figure ? gtBeforeBar(o.overall) : null);
}

// ------------------------------------------------------------------ the results

/** One group kind at a time (Colour, Colours, Style or Tier), each group's equal-weight rate over its opponents,
 * its range, its opponents and games, and the spread between them; then the caveat. */
function gtGroups(ctx, a) {
  const groups = a.groups || {};
  const kinds = GT_GROUPS.filter(([key]) => (groups[key] || []).length);
  if (!kinds.length) return null;
  if (!kinds.some(([key]) => key === ctx.by)) ctx.by = kinds[0][0];
  const list = el("ul", { class: "gt-groups" });
  const draw = () => clear(list).append(...(groups[ctx.by] || []).map((g) => gtGroupRow(g)));
  const buttons = kinds.map(([key, title]) => el("button", { type: "button", text: title, "aria-pressed": String(key === ctx.by),
    onclick: () => { ctx.by = key; buttons.forEach((b, i) => b.setAttribute("aria-pressed", String(kinds[i][0] === key))); draw(); } }));
  draw();
  return el("div", { class: "gt-groups-part" },
    el("h3", { id: "h-gauntlet-groups", text: "By group" }),
    el("div", { class: "segmented", role: "group", "aria-labelledby": "h-gauntlet-groups" }, buttons),
    list,
    el("p", { class: "sub gt-caveat", text: a.note || "Each range covers these sampled opponents only." }),
    ...(a.notes || []).map((text) => el("p", { class: "gt-small", text })));
}

function gtRate(value, low, high) { return value == null ? null : { value, low, high }; }

function gtScreening(screen) {
  if (!screen) return null;
  const counts = rows => Object.entries(rows || {}).map(([name,n])=>`${name}: ${n}`).join(", ") || "none recorded";
  return el("p", {class:"gt-small",text:`Known AI-screen exclusions: ${screen.ai_excluded}. By colour (overlapping): ${counts(screen.colour)}. ` +
    `By style: ${counts(screen.style)}. Other checks excluded ${screen.other_excluded || 0}; ${screen.unclassified || 0} exclusions have unclassified provenance. These samples reflect what the AI can play.`});
}

function gtGroupRow(g) {
  const rate = gtRate(g.rate, g.low, g.high);
  const what = `Win rate against ${g.label}`;
  const spread = Array.isArray(g.spread) && g.spread[0] != null
    ? `from ${Math.round(g.spread[0] * 100)}% to ${Math.round(g.spread[1] * 100)}% by opponent` : null;
  const thin = g.thin || g.opponents < 2;
  return el("li", { class: thin ? "gt-group gt-muted" : "gt-group" },
    el("span", { class: "gt-name", text: g.label }),
    el("span", { class: "gt-barline" },
      rangeBar(rate, { compact: true, muted: thin, decorative: true }),
      el("span", { class: "gt-pct" }, winRateFigure(rate, { what, barred: true }))),
    el("span", { class: "gt-meta", text: metaWords(plural(g.opponents, "opponent"), gamesWords(g.games), spread, g.note) }),
    gtClockLine(g.clock));
}

/** One row per sampled opponent, hardest first (the server's order: the lowest range first), with where it's from. */
function gtRows(a) {
  const played = (a.opponents || []).filter((o) => o.games && o.rate && o.rate.value != null);
  const waiting = (a.opponents || []).filter((o) => !played.includes(o));
  return [
    el("h3", { text: "Against each deck, lowest observed first" }),
    el("ul", { class: "gt-rows" }, played.map((o) => {
      const what = `Win rate against ${o.title}`;
      const chips = [o.not_meaningful ? status("crit", "Not meaningful") : null,
        o.stalled?.words ? el("span", {class:"note note-warn",text:o.stalled.words}) : null,
        o.moved ? status("info", "Moved") : null].filter(Boolean);
      const before = gtFigureWords(o.before);
      return el("li", { class: o.not_meaningful ? "gt-row gt-muted" : "gt-row" },
        el("span", { class: "gt-name", text: o.title }),
        el("span", { class: "gt-barline" },
          rangeBar(o.rate, { compact: true, muted: o.not_meaningful, decorative: true }),
          el("span", { class: "gt-pct" }, winRateFigure(o.rate, { what, barred: true }))),
        el("span", { class: "gt-meta" },
          deckColourPieces((o.identity || "").split("")).pips(16),
          el("span", { text: metaWords(o.verdict ? capitalise(o.verdict) : null, GT_STYLES[o.style] || o.style,
            GT_TIERS[o.tier] || o.tier, gamesWords(o.games), before ? `Before: ${before}` : null, o.problem) }), chips,
          freshnessBadge(o.updated, { size: "row" })),
        gtClockLine(o.clock), gtSource(o.source));
    })),
    waiting.length ? el("p", { class: "gt-small", text: `Not played yet: ${waiting.slice(0, 12).map((o) => o.title)
      .join(", ")}${waiting.length > 12 ? ` and ${thousands(waiting.length - 12)} more` : ""}.` }) : null];
}

/** Where a sparring deck is from: EDHREC's average deck (linked, with its rank and deck count), a Wizards precon
 * from MTGJSON, or a deck bundled with Forge. */
function gtSource(src) {
  const s = src || {};
  if (s.kind === "edhrec") {
    const facts = [s.rank != null ? `rank ${thousands(s.rank)}` : null,
      s.decks != null ? `${thousands(s.decks)} decks` : null].filter(Boolean).join(", ");
    return el("span", { class: "gt-source" }, "Average deck from ",
      s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", text: "EDHREC" }) : "EDHREC",
      facts ? ` (${facts})` : "");
  }
  if (s.kind === "mtgjson") return el("span", { class: "gt-source", text: "Wizards precon, from MTGJSON" });
  if (s.kind === "forge") return el("span", { class: "gt-source", text: "A deck bundled with Forge" });
  return null;
}

function gtCredit(a) {
  return el("p", { class: "gt-small gt-credit", text: a.credit || "" });
}

/** When the popular decks list was built (E3-S43; c: the answer's catalogue, gauntlet_page.catalogue_stamp):
 * "Popular decks list built 3 November 2026 (1a2b3c4d).", one muted line, with how long ago once it's old. It
 * never asks for a rebuild. Null without a build time. The board (gauntlet-board.js) draws it too. */
function gtBuiltLine(c, cls = "gt-built") {
  const d = c && c.built ? new Date(c.built) : null;
  if (!d || Number.isNaN(d.getTime())) return null;
  const age = c.old && Number.isInteger(c.age_days) ? `, ${ageWords(c.age_days)}` : "";
  return el("p", { class: `gt-small ${cls}`,
    text: `Popular decks list built ${simDay(d, true)}${c.sha ? ` (${c.sha})` : ""}${age}.` });
}

// ------------------------------------------------------------------ choices and play

/** inEmpty: inside the empty state, whose lines already say what to do, so no heading. */
function gtPlayBox(ctx, a, { inEmpty = false } = {}) {
  const box = el("div", { class: "gt-play" });
  if (a.notice) box.append(el("p", { class: "gt-small", text: a.notice }));
  if (a.error) box.append(el("div", { class: "box box-crit" }, el("p", { text: a.error })));
  if (gtPlaying(a)) {
    add(box, gtLive(ctx, a));
    return box;
  }
  const ready = !a.forge || a.forge.ready;
  const options = GT_BUDGETS.map(([id, title]) => ({ id, title, sub: GT_BUDGET_SUB[id],
    time: gtBudgetWords((a.budgets || {})[id]) || null }));
  const time = el("div", { class: "gt-time-part", "aria-live": "polite" });
  const showTime = () => clear(time).append(...gtRunTime(a, ctx.budget).filter(Boolean));
  const choice = runChoiceControl(options, ctx.budget, (budget) => { ctx.budget = budget; showTime(); },
    { label: "Games a deck" });
  const allowed = runsAllowed();
  choice.node.hidden = !allowed;
  time.hidden = !allowed;
  const none = !((a.sample || {}).decks);
  showTime();
  add(box, [inEmpty ? null : el("h3", { text: "Play popular decks" }),
    gtChoices(ctx, a), choice.node,
    none ? el("p", { class: "gt-small", text: "No popular deck matches these choices: choose fewer." }) : time,
    ready ? null : el("p", { class: "gt-small", text: (a.forge && a.forge.problem) || "Forge isn't ready on the PC." }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Play them",
      disabled: !ready || !state.profile || none, "data-run": true, onclick: () => gtPlay(ctx) }))]);
  return box;
}

/** The sample's choices in a closed disclosure whose summary says them: how many opponents, which colours
 * (identity within them), styles and tiers. Each change draws the sample again (nothing plays). */
function gtChoices(ctx, a) {
  const c = ctx.choice, opts = a.options || {};
  const pick = (change) => { change(); Object.assign(ctx, { sample: null, lost: false }); gtRefresh(ctx); };
  const toggle = (list, value) => (list.includes(value) ? list.filter((x) => x !== value) : [...list, value].sort());
  const details = el("details", { class: "more gt-choices" }, el("summary", { text: gtChoiceWords(c, a) }),
    gtSegmented("Opponents", (opts.sizes || []).map((n) => [n, n === "all" ? "All" : String(n)]), c.size,
      (n) => pick(() => { c.size = n; })),
    c.size === "all" ? el("p", { class: "gt-small", text: "All: every playable deck of the chosen tiers, colours " +
      "and styles, both of a commander's decks included. Best run overnight." }) : null,
    gtChips("Only decks within these colours", [..."WUBRG"].map((x) => [x, capitalise(COLOUR_WORDS[x])]),
      [...c.colours], (x) => pick(() => { c.colours = [..."WUBRG"].filter((y) => toggle([...c.colours], x).includes(y)).join(""); })),
    gtChips("Styles", (opts.styles || []).map((x) => [x, GT_STYLES[x] || x]), c.styles,
      (x) => pick(() => { c.styles = toggle(c.styles, x); })),
    gtChips("Tiers", (opts.tiers || []).map((x) => [x, GT_TIERS[x] || x]), c.tiers,
      (x) => pick(() => { c.tiers = toggle(c.tiers, x); })));
  details.open = ctx.open;
  details.addEventListener("toggle", () => { ctx.open = details.open; });
  return details;
}

/** "12 opponents · Core · any colours · any style". */
function gtChoiceWords(c, a) {
  const colours = c.colours ? [...c.colours].map((x) => COLOUR_WORDS[x]).join(", ") : "any colours";
  const styles = c.styles.length ? c.styles.map((x) => GT_STYLES[x] || x).join(", ") : "any style";
  const tiers = c.tiers.length ? c.tiers.map((x) => GT_TIERS[x] || x).join(", ") : "every tier";
  const found = (a.sample || {}).decks;
  return metaWords(plural(found != null ? found : c.size, "opponent"), tiers, colours, styles);
}

function gtSegmented(label, options, value, onPick) {
  const id = `gt-label-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return el("div", { class: "gt-control" }, el("span", { class: "games-label", id, text: label }),
    el("div", { class: "segmented", role: "group", "aria-labelledby": id }, options.map(([v, title]) =>
      el("button", { type: "button", text: title, "aria-pressed": String(v === value), onclick: () => { if (v !== value) onPick(v); } }))));
}

function gtChips(label, options, chosen, onToggle) {
  const id = `gt-label-${label.toLowerCase().replace(/[^a-z]+/g, "-")}`;
  return el("div", { class: "gt-control" }, el("span", { class: "games-label", id, text: label }),
    el("div", { class: "filter-chips", role: "group", "aria-labelledby": id }, options.map(([v, title]) =>
      el("button", { type: "button", class: "filter-chip", text: title, "aria-pressed": String(chosen.includes(v)),
        onclick: () => onToggle(v) }))));
}

/** "about 100 games a deck, about 25–40 minutes" for a budget (the answer's budgets). */
function gtBudgetWords(b) {
  if (!b) return "";
  const parts = [`about ${thousands(b.games)} games a deck`];
  if (b.new_games === 0) parts.push("nothing new to play");
  else if (b.minutes) parts.push(gtMinutesWords(b.minutes));
  else if (b.new_games) parts.push(`${thousands(b.new_games)} new games, time not yet measured`);
  return parts.join(", ");
}

/** [low, high] minutes in words: "under a minute", "about 3–5 minutes", "about 4–7 hours" (hours from 90 minutes). */
function gtMinutesWords(span) {
  const [low, high] = span.map(Number);
  if (high < 1) return "under a minute";
  if (high >= 90) {
    const a = Math.max(1, Math.round(low / 60)), b = Math.max(a, Math.round(high / 60));
    return a === b ? `about ${a} hour${a === 1 ? "" : "s"}` : `about ${a}–${b} hours`;
  }
  const a = Math.max(1, Math.round(low)), b = Math.max(a, Math.round(high));
  return a === b ? `about ${a} minute${a === 1 ? "" : "s"}` : `about ${a}–${b} minutes`;
}

/** The chosen budget's run time, said plainly above Play ("This run: 20 opponents · 2,000 new games · about 1–2
 * hours."); over the answer's overnight_minutes, that it's an overnight run and the PC is kept awake while it plays. */
function gtRunTime(a, budget) {
  const b = (a.budgets || {})[budget];
  if (!b) return [];
  const decks = plural((a.sample || {}).decks || 0, "opponent");
  if (b.new_games === 0) return [el("p", { class: "gt-time", text: "Nothing new to play: every opponent has these games." })];
  const minutes = Array.isArray(b.minutes) ? b.minutes : null;
  const games = b.new_games ? `${thousands(b.new_games)} new games` : null;
  const overnight = b.overnight || (!!minutes && minutes[1] > ((a.options || {}).overnight_minutes || 120));
  return [el("p", { class: "gt-time" }, "This run: ",
    el("strong", { text: metaWords(decks, games, minutes ? gtMinutesWords(minutes) : "time not yet measured") }), "."),
  overnight ? el("p", { class: "note gt-overnight", text: "That's an overnight run: start it in the evening and " +
    "leave the PC on. Deck Lab keeps the PC awake while it plays." }) : null];
}

/** A run waiting or playing: its progress, who's playing now and Stop. */
function gtLive(ctx, a) {
  const job = a.job || {};
  const pairs = Object.values(job.pairs || {});
  const bar = progressBar("Games against popular decks played");
  bar.set(job.total ? job.done / job.total : 0);
  const playing = pairs.filter((p) => p.playing).map((p) => (p.opponent || {}).title).filter(Boolean);
  const words = a.status === "queued"
    ? metaWords(job.ahead > 0 ? `Waiting: ${plural(job.ahead, "run")} ahead of it` : "Starting…",
      runAheadWork({ ...job, status: a.status }))
    : playing.length ? `Playing: ${playing.join(", ")}` : "Choosing the next decks to play…";
  return [
    el("h3", {}, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), " Playing popular decks"),
    bar.node,
    el("p", { class: "gt-small" }, status("info", a.status === "queued" ? "Waiting" : "Playing"), " ",
      `${thousands(job.done || 0)} of ${thousands(job.total || 0)} games · ${words}`),
    job.by ? el("p", { class: "gt-small", text: `Started by ${job.by}` }) : null,
    mayStopRuns(job) ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-danger", text: "Stop",
      onclick: () => gtStop(ctx) })) : null];
}

function gtAnnounce(ctx, a) {
  if (!ctx.announcer) {
    ctx.announcer = el("p", { class: "sr-only", role: "status" });
    ctx.section.append(ctx.announcer);
  }
  const phase = a.status === "queued" ? "Waiting to play popular decks." : a.status === "running" ? "Playing popular decks."
    : ctx.phase ? "Finished playing popular decks." : "";
  if (gtPlaying(a) || ctx.phase) ctx.phase = gtPlaying(a) ? a.status : null;
  if (phase && ctx.announcer.textContent !== phase) ctx.announcer.textContent = phase;
}

async function gtWrite(ctx, path, body) {
  const profile = state.profile?.id;
  ctx.busy = true;
  ctx.asked++;
  clearTimeout(ctx.timer);
  try {
    const answer = await apiWrite(path, { id: ctx.id, version: ctx.version, ...body });
    ctx.busy = false;
    if (gtHere(ctx) && state.profile?.id === profile) { gtDraw(ctx, answer); gtSchedule(ctx); }
    if (state.profile?.id === profile && typeof syncRunsPill === "function") syncRunsPill(true);
  } catch (e) {
    ctx.busy = false;
    if (gtHere(ctx) && state.profile?.id === profile) { toast(e.message || String(e)); gtRefresh(ctx); }
  }
}

function gtPlay(ctx) {
  const a = ctx.answer || {}, c = ctx.choice || gtChoiceOf(a);
  // A saved sample the address names plays by its id: the same decks, even if today's catalogue would draw others.
  const body = ctx.sample ? { budget: ctx.budget, sample: ctx.sample } : { budget: ctx.budget, size: c.size,
    colours: c.colours, styles: c.styles.join(","), tiers: gtTiersAsked(c, a).join(",") };
  if (a.deck && a.deck.card_sha) body.expected_card_sha = a.deck.card_sha;
  return gtWrite(ctx, "/api/gauntlet/run", body);
}

/** Stop asks first, as every Stop does; every game that finished is kept. */
async function gtStop(ctx) {
  if (!gtHere(ctx) || !gtPlaying(ctx.answer) || !mayStopRuns(ctx.answer?.job)) return null;
  const profile = state.profile?.id;
  const choice = await ask("Stop playing popular decks?", ["Every game that finished is kept."],
    [{ value: "stop", text: "Stop it", kind: "danger" }, { value: "keep", text: "Keep playing", kind: "primary" }]);
  if (choice !== "stop" || !gtHere(ctx) || state.profile?.id !== profile || !gtPlaying(ctx.answer) ||
      !mayStopRuns(ctx.answer?.job)) return null;
  return gtWrite(ctx, "/api/gauntlet/stop", {});
}
