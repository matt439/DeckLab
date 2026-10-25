/* Deck Lab's page: the shared pieces Forge's results are drawn with (design/visual-design.md 4.9; E11-S30 slice 6),
styled once in components.css: a win rate as a figure (winRateFigure), its 95% range on the fixed 20-80% scale
(rangeBar), how old a result or any other dated check is (freshnessBadge), "strong against" and "weak against"
(forgeFlag) and a test of a change (swapResult). Every Forge number is set in mono, and none is coloured good or
bad: the flags and the verdict pills say that, in words, in Forge's strong and weak colours. Each piece with a
number has its words spoken from an element with a role, never an aria-label on a plain span.

Loaded first of the matchup scripts (index.html): the matchup pages, the deck page's field part (field.js), its
tests of changes (variant.js) and the run activity (runs-pill.js) use them. Uses core.js's el, thousands and
capitalise when called; nothing runs at load. */
"use strict";

const RANGE_FROM = 0.2;          // every range bar runs from 20% ...
const RANGE_TO = 0.8;            // ... to 80%, so bars compare across pages (a value outside clamps to an end)
const FRESH_DAYS = 7;            // a result up to a week old is fresh,
const AGING_DAYS = 30;           // up to a month aging, then stale (as is one whose list has changed since)
const SIM_DAY_MS = 86400000;
const SIM_MINUS = "−";           // the real minus, never a hyphen
// A test of a change's verdict pills (4.9), worked out from its range (swapVerdict).
const SWAP_VERDICTS = { better: "better", "likely-better": "probably better, not proven", even: "no clear difference",
  "likely-worse": "probably worse, not proven", worse: "worse" };


// ------------------------------------------------------------------ numbers and words

/** 0.613 -> "61": a share in whole points of win rate, as every figure shows it. */
function simPoints(x) { return String(Math.round(x * 100)); }

/** A rate's range in whole points with an en dash ("59–63"), or null. */
function simRange(rate) {
  return rate && rate.low != null && rate.high != null ? `${simPoints(rate.low)}–${simPoints(rate.high)}` : null;
}

/** "+3.1", "−0.4", "0.0": a difference in points of win rate, from a share. */
function simDelta(x) {
  const v = Math.round(x * 1000) / 10;
  if (v === 0) return "0.0";
  return (v > 0 ? "+" : SIM_MINUS) + Math.abs(v).toFixed(1);
}

/** Text with its numbers in mono and its words in the body font (2.3: words are never mono): "3,400 games · rank
 * 3 of 11" -> [<span class="sim-num">3,400</span>, " games · rank ", ...]. */
function simNumbers(text) {
  return String(text).split(/([−+~]?\d[\d,.]*%?(?:–\d[\d,.]*%?)?)/)
    .map((part, i) => (i % 2 ? el("span", { class: "sim-num", text: part }) : part)).filter((part) => part !== "");
}

/** A figure's or a bar's spoken words: "Forge field win rate 61 percent, range 59 to 63, tested 3 days ago". what
 * names the rate; more: further facts, in order (null ones are left out). */
function winRateWords(rate, what = "Win rate", more = []) {
  const known = rate && rate.value != null;
  const parts = [known ? `${what} ${simPoints(rate.value)} percent` : `${what} not known yet`];
  if (known && rate.low != null && rate.high != null) parts.push(`range ${simPoints(rate.low)} to ${simPoints(rate.high)}`);
  return [...parts, ...more.filter(Boolean)].join(", ");
}


// ------------------------------------------------------------------ the win-rate figure

/** A win rate as a figure (4.9), in ink and never coloured. size: "inline" (a row: "61% 59–63"), "tile" (61% and a
 * caption, "Forge field") or "hero" (the big number with "59–63% 95% range" and the games, and the rank, under
 * it). rate: {value, low, high}; what: the rate's name in the spoken words; games, rank ({rank, of}) and tested
 * (words such as "tested 3 days ago") go into them too, and the games and rank under a hero; barred: it stands
 * beside a decorative range bar, so its words also say when that bar clamps the rate (rangeBeyond). role="img", so
 * its words are what's read. */
function winRateFigure(rate, { size = "inline", what = "Win rate", games = null, rank = null, tested = null,
  caption = "Forge field", label = null, barred = false } = {}) {
  const known = rate && rate.value != null;
  const value = known ? simPoints(rate.value) : "?";
  const range = simRange(rate);
  const facts = [games != null ? `${thousands(games)} game${games === 1 ? "" : "s"}` : null,
    rank && rank.rank != null && rank.of != null ? `rank ${rank.rank} of ${rank.of}` : null].filter(Boolean);
  const props = { class: `wr wr-${size}`, role: "img",
    "aria-label": label || winRateWords(rate, what, [...facts, tested, barred ? rangeBeyond(rate) : null]) };
  if (size === "hero") {
    return el("div", props,
      el("span", { class: "wr-value" }, value, known ? el("span", { class: "wr-unit", text: "%" }) : null),
      el("span", { class: "wr-lines" },
        range ? el("span", { class: "wr-line" }, el("span", { class: "sim-num", text: `${range}%` }), " 95% range") : null,
        facts.length ? el("span", { class: "wr-line" }, simNumbers(facts.join(" · "))) : null));
  }
  if (size === "tile") {
    return el("span", props, el("span", { class: "wr-value", text: known ? `${value}%` : value }),
      caption ? el("span", { class: "wr-caption", text: caption }) : null);
  }
  return el("span", props, el("span", { class: "wr-value", text: known ? `${value}%` : value }),
    range ? el("span", { class: "wr-range", text: range }) : null);
}


// ------------------------------------------------------------------ the range bar

/** Where x sits on a range bar, 0 to 1: (x − 20%) / 60%, clamped to the ends. */
function rangeAt(x) { return Math.max(0, Math.min(1, (x - RANGE_FROM) / (RANGE_TO - RANGE_FROM))); }

function rangePct(share) { return `${Number((100 * share).toFixed(2))}%`; }

/** A win rate's range on the fixed 20-80% scale (4.9): a round track, a dashed tick at 50%, the 95% band from
 * low to high and the win rate as a short ink bar. compact: 6 px (a Matchups row) rather than 12 (10 in the lab);
 * axis: "20 / 50 / 80" under it; live: a run's range so far (its band dashed: wider while games are still being
 * played); muted: a result that means nothing (no band, the point faded). A value outside 20-80% sits at that end,
 * and the spoken words (role="img") give the real one. decorative: beside a win-rate figure that already says it
 * (rangeBeyond gives the figure the clamped value's words), the bar is aria-hidden and says nothing. */
function rangeBar(rate, { compact = false, axis = false, what = "Win rate", label = null, live = false, muted = false,
  decorative = false } = {}) {
  const known = rate && rate.value != null;
  const outside = !!rangeBeyond(rate);
  const words = label || winRateWords(rate, what, [rangeBeyond(rate)]);
  const track = el("span", { class: "range-track" }, el("span", { class: "range-even" }));
  if (known && !muted && rate.low != null && rate.high != null) {
    const from = rangeAt(rate.low), to = rangeAt(rate.high);
    track.append(el("span", { class: "range-band", style: `left: ${rangePct(from)}; width: ${rangePct(to - from)}` }));
  }
  if (known) track.append(el("span", { class: "range-point", style: `left: ${rangePct(rangeAt(rate.value))}` }));
  const cls = ["range-bar", compact && "range-bar-compact", live && "is-live", muted && "is-muted", outside && "is-clamped"];
  const spoken = decorative ? { "aria-hidden": "true" } : { role: "img", "aria-label": words };
  return el("div", { class: cls.filter(Boolean).join(" "), ...spoken }, track,
    axis ? el("span", { class: "range-axis", "aria-hidden": "true" },
      el("span", { text: "20" }), el("span", { text: "50" }), el("span", { text: "80" })) : null);
}

/** "beyond the bar's 20 to 80 percent scale" for a rate a range bar clamps to an end, or null: the words a figure
 * beside a decorative bar adds (winRateFigure's more). */
function rangeBeyond(rate) {
  const ends = rate && rate.value != null ? [rate.value, rate.low, rate.high].filter((x) => x != null) : [];
  return ends.some((x) => x < RANGE_FROM || x > RANGE_TO) ? "beyond the bar's 20 to 80 percent scale" : null;
}

/** The key to a range bar, for a reading that explains one: the band, the win rate's mark and the 50% tick. */
function rangeKey() {
  return el("ul", { class: "legend range-key", "aria-label": "Key" },
    el("li", {}, el("span", { class: "range-key-band", "aria-hidden": "true" }), "Where the win rate probably lies (95% range)"),
    el("li", {}, el("span", { class: "range-key-point", "aria-hidden": "true" }), "The win rate"),
    el("li", {}, el("span", { class: "range-key-even", "aria-hidden": "true" }), "50% win rate"));
}


// ------------------------------------------------------------------ the freshness badge

/** Whole days from when to now, by the calendar (yesterday at 11 pm is 1 day ago), or null for a date that can't
 * be read. */
function freshDays(when, now = Date.now()) {
  const d = when instanceof Date ? when : new Date(when);
  if (Number.isNaN(d.getTime())) return null;
  const day = (t) => { const x = new Date(t); x.setHours(0, 0, 0, 0); return x.getTime(); };
  return Math.max(0, Math.round((day(now) - day(d.getTime())) / SIM_DAY_MS));
}

/** 0 -> "today", 1 -> "yesterday", 3 -> "3 days ago", 45 -> "6 weeks ago", 200 -> "6 months ago". */
function ageWords(days) {
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days <= AGING_DAYS) return `${days} days ago`;
  if (days < 90) return `${Math.floor(days / 7)} weeks ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  const years = Math.floor(days / 365);
  return years === 1 ? "a year ago" : `${years} years ago`;
}

/** "24 Oct" (with the year when it isn't now's), or long: "24 October 2026". */
function simDay(d, long = false, now = Date.now()) {
  const opts = long ? { day: "numeric", month: "long", year: "numeric" } : { day: "numeric", month: "short" };
  if (!long && d.getFullYear() !== new Date(now).getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("en-AU", opts);
}

/** How old a result is (4.9), or any other dated check ("pulled 24 Oct" for prices, "checked 3 days ago" for a
 * shop): a round badge with a clock and words, shown only when there's a date or the list has changed since
 * (null otherwise). Fresh up to FRESH_DAYS, aging up to AGING_DAYS (amber), then stale (amber with a refresh icon:
 * "retest: 6 weeks ago", or "check again" for a check that isn't a test). changed: the list has changed since ("retest: changed since");
 * unsaved: the editor's result is for the saved list, not the unsaved one ("for the saved list", no date needed).
 * verb: "tested", "pulled", "checked"; byDate: the date rather than the age ("pulled 24 Oct"); compact: the
 * words without the verb ("3 days ago"); size: "row" (17 px in the lab, where a fresh one is plain text), "panel"
 * (20 px) or "casual" (24 px; any size is 24 under 1000 px); onTint: on a deck's tint. The real date is in its
 * spoken words, on an element with role="img". */
function freshnessBadge(when, { verb = "tested", byDate = false, changed = false, unsaved = false, size = "panel",
  compact = false, onTint = false, staleWords = null, now = Date.now() } = {}) {
  const d = when ? (when instanceof Date ? when : new Date(when)) : null;
  const dated = !!d && !Number.isNaN(d.getTime());
  if (!dated && !unsaved && !changed) return null;
  const days = dated ? freshDays(d, now) : null;
  const age = dated ? ageWords(days) : null;
  const on = dated ? `on ${simDay(d, true)}` : null;
  let kind, words, spoken;
  if (unsaved) {
    kind = "unsaved";
    words = "for the saved list";
    spoken = `Result for the saved list${dated ? `, ${verb} ${on}` : ""}: the unsaved changes aren't tested`;
  } else if (changed) {
    kind = "stale";
    words = staleWords || "retest: changed since";
    const again = `so ${verb === "tested" ? "test" : "check"} it again`;
    spoken = dated ? `${capitalise(verb)} ${on}; the list has changed since, ${again}`
      : `The list has changed since it was ${verb}, ${again}`;
  } else {
    kind = days <= FRESH_DAYS ? "fresh" : days <= AGING_DAYS ? "aging" : "stale";
    const shown = byDate ? simDay(d, false, now) : age;
    words = kind === "stale" ? staleWords || (verb === "tested" ? `retest: ${age}` : "check again")
      : compact ? shown : `${verb} ${shown}`;
    spoken = `${capitalise(verb)} ${age}, ${on}` +
      (kind === "stale" ? `: worth ${verb === "tested" ? "testing" : "checking"} again` : "");
  }
  return el("span", { class: `fresh fresh-${size} is-${kind}${onTint ? " on-tint" : ""}`, role: "img", "aria-label": spoken },
    el("span", { class: "fresh-icon", "aria-hidden": "true" }), el("span", { class: "fresh-words", text: words }));
}


// ------------------------------------------------------------------ strong and weak flags

/** "Strong against" or "weak against" (4.9): a round pill in Forge's strong or weak colours with a chevron (up or
 * down), the opponent's name and the mono win rate. Without a name it says just "strong against" (after the
 * opponent's name in a list); short: "strong" or "weak" (a narrow touch cell). The words are always there for a
 * screen reader. */
function forgeFlag(kind, { name = null, rate = null, short = false } = {}) {
  const strong = kind === "strong";
  const words = strong ? "strong against" : "weak against";
  return el("span", { class: `flag flag-${strong ? "strong" : "weak"}` },
    el("span", { class: "flag-chevron", "aria-hidden": "true" }),
    name ? [el("span", { class: "sr-only", text: `${capitalise(words)} ` }), el("span", { class: "flag-name", text: name })]
      : el("span", { class: "flag-words", text: short ? (strong ? "strong" : "weak") : words }),
    rate && rate.value != null ? el("span", { class: "flag-rate", text: `${simPoints(rate.value)}%` }) : null);
}


// ------------------------------------------------------------------ a test of a change

/** A test's verdict pill (4.9) from its difference: "better" when the whole range is above 0, "worse" below,
 * "probably better (or worse), not proven" when the estimate leans one way, "no clear difference" otherwise (and
 * whenever the server found it makes little difference). A key of SWAP_VERDICTS, or null without a difference. */
function swapVerdict({ delta = null, low = null, high = null, verdict = null } = {}) {
  if (delta == null) return null;
  if (verdict === "little_difference") return "even";
  if (low != null && low > 0) return "better";
  if (high != null && high < 0) return "worse";
  if (Math.round(delta * 1000) > 0) return "likely-better";
  if (Math.round(delta * 1000) < 0) return "likely-worse";
  return "even";
}

/** A test of a change (4.9): the swap ("−1 Abrade" in Forge's weak colour, "+1 Burst Lightning" in its strong one,
 * the quantities in mono), the difference ("+3.1 points", mono), its verdict pill and "−0.4 to +6.6 · 600 paired
 * games". changes: {remove: [[qty, name]], add: [...]}; delta, low, high: the difference in shares; games: the
 * paired games (a deck), or gamesText: the words after the range in their place ("against the field · 400 games
 * a deck"); verdict: the server's (variants.py); neutral: a curve or count change, whose +1 and −1 aren't better
 * or worse (--ink-3). Each part is left out when it isn't known. */
function swapResult({ changes = null, delta = null, low = null, high = null, games = null, gamesText = null,
  verdict = null, neutral = false } = {}) {
  const c = changes || {};
  const lines = [...(c.remove || []).map(([q, n]) => ["remove", `${SIM_MINUS}${q}`, n]),
    ...(c.add || []).map(([q, n]) => ["add", `+${q}`, n])];
  const key = swapVerdict({ delta, low, high, verdict });
  const facts = [low != null && high != null ? `${simDelta(low)} to ${simDelta(high)}` : null,
    gamesText || (games != null ? `${thousands(games)} paired game${games === 1 ? "" : "s"}` : null)].filter(Boolean);
  return el("div", { class: "swap-result" },
    lines.length ? el("ul", { class: `swap-lines${neutral ? " is-neutral" : ""}`, "aria-label": "The change" },
      lines.map(([kind, qty, name]) => el("li", { class: `swap-${kind}` },
        el("span", { class: "swap-qty", text: qty }), " ", el("span", { class: "swap-card", text: name })))) : null,
    delta != null ? el("p", { class: "swap-figure" }, el("span", { class: "swap-points", text: simDelta(delta) }),
      el("span", { class: "swap-unit", text: " points" })) : null,
    key || facts.length ? el("p", { class: "swap-facts" },
      key ? el("span", { class: `swap-verdict swap-verdict-${key}`, text: SWAP_VERDICTS[key] }) : null,
      facts.length ? el("span", { class: "swap-range" }, simNumbers(facts.join(" · "))) : null) : null);
}
