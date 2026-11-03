/* Deck Lab's page: the library's popular-decks line (E3-S36, design/visual-design.md 4.1 and 4.2). Each deck's
Planned list against its format's standard sample of popular decks (GET /api/library/gauntlet: the Testing page's
board rows, worked out on the PC from the saved games and cached there; nothing plays), fetched once the shelf
is drawn and drawn in when it comes.

A Commander deck's tile shows it as its Forge line, its lab row in the empty Forge cell ("—" when untested,
blank while the numbers load) and its detail pane as the hero figure; a 60-card deck's detail pane has it as a
second block under its Forge field figure. A figure from before the list's last change is muted and says
"before the last change". The detail pane links to the deck's Testing tab at its popular-decks part (tiles and
rows are links already). The "Strongest vs popular decks" sort ranks by it (libGauntletRank), untested last.
Until the numbers come, or when they can't be worked out, or the format has no catalogue, nothing is shown
(never "not tested").

Loaded after library.js (deckRowForge, deckCard, libDetail and sortDecks call these), gauntlet.js
(gtBeforeLine, gtOlderLine) and sim-ui.js (winRateFigure, rangeBar, freshnessBadge). Nothing here runs at load.
*/
"use strict";

const LIB_GT_CAPTION = "vs popular decks";
const LIB_GT_WHAT = "Win rate against popular decks";
const LIB_GT_STALE = "before the last change";

/** Fetch the popular-decks numbers once for this draw (only when some deck could have them). */
function libLoadGauntlet(data, refresh) {
  if (!data.decks.some((d) => libGauntletFormat(d))) return;
  const profile = state.profile ? state.profile.id : null;
  api("/api/library/gauntlet").then((answer) => {
    if (!answer || typeof answer !== "object" || !answer.decks || !answer.formats) return;
    state.libraryGauntlet = { profile, decks: answer.decks, formats: answer.formats };
    refresh();
  }).catch(() => {});
}

/** The gauntlet format of a deck kind: "commander", "constructed" (a 60-card deck) or null. */
function libGauntletFormat(d) {
  return d.kind === "commander" ? "commander" : d.kind === "casual" ? "constructed" : null;
}

/** A deck's standing ({format, state, overall, played, of, games, updated, before, older}), null when the answer
 * has none for it (untested), or undefined while it isn't known (loading, another profile's answer, its format
 * without a catalogue or numbers, a deck that can't be read). */
function libGauntlet(d) {
  const known = state.libraryGauntlet, fmt = libGauntletFormat(d);
  if (!known || known.profile !== (state.profile ? state.profile.id : null) || !fmt || d.error) return undefined;
  if (!known.formats[fmt] || known.formats[fmt].state !== "ok") return undefined;
  const entry = known.decks[d.id];
  return entry && entry.format === fmt ? entry : null;
}

/** The figure a standing shows: {rate, updated, stale}: today's list's (done or partial), its list's before the last
 * change (stale_list, muted), else null. */
function libGauntletFigure(n) {
  if (!n) return null;
  if ((n.state === "done" || n.state === "partial") && n.overall && n.overall.rate != null) {
    return { rate: libGauntletRate(n.overall), updated: n.updated, stale: false };
  }
  if (n.state === "stale_list" && n.before && n.before.rate != null) {
    return { rate: libGauntletRate(n.before), updated: n.before.updated, stale: true };
  }
  return null;
}

function libGauntletRate(f) { return { value: f.rate, low: f.low, high: f.high }; }

function libGauntletFresh(f, opts) {
  return f.stale ? freshnessBadge(f.updated, { ...opts, changed: true, staleWords: LIB_GT_STALE })
    : freshnessBadge(f.updated, opts);
}

function libGauntletWords(f) { return f.stale ? `${LIB_GT_WHAT} ${LIB_GT_STALE}` : LIB_GT_WHAT; }

/** A Commander tile's Forge line (4.1): the figure, "vs popular decks" and its freshness; nothing without one. */
function libGauntletLine(d) {
  if (d.kind !== "commander") return null;
  const n = libGauntlet(d), f = libGauntletFigure(n);
  if (!f) return null;
  return el("span", { class: "deck-forge lib-gauntlet" + (f.stale ? " is-stale" : "") },
    winRateFigure(f.rate, { size: "tile", caption: LIB_GT_CAPTION, what: libGauntletWords(f),
      games: f.stale ? null : n.games }),
    libGauntletFresh(f, { size: "casual", onTint: true }));
}

/** A Commander deck's lab-row Forge cell (4.2): the inline figure, its range and freshness; "—" without one;
 * blank while the numbers aren't known. */
function libGauntletRowCell(d) {
  const n = libGauntlet(d), f = libGauntletFigure(n);
  const cell = el("span", { class: "deck-row-forge lib-gauntlet" + (f && f.stale ? " is-stale" : "") });
  if (n === undefined) return cell;
  if (!f) {
    const words = n && n.state === "unreadable" ? "Forge can't read this list"
      : n && n.state === "stale_older" ? "No up-to-date result against popular decks" : "Not tested against popular decks";
    cell.append(el("span", { class: "deck-row-untested", role: "img", "aria-label": words, text: "—" }));
    return cell;
  }
  add(cell, [winRateFigure(f.rate, { what: libGauntletWords(f), games: f.stale ? null : n.games, barred: true }),
    rangeBar(f.rate, { compact: true, decorative: true }),
    libGauntletFresh(f, { size: "row", compact: true })]);
  return cell;
}

/** The detail pane's popular-decks part (5, Library): a Commander deck's hero figure, a 60-card deck's second line
 * under its field figure; the out-of-date and untested words otherwise; and the way to its Testing tab. */
function libDetailGauntlet(d) {
  const n = libGauntlet(d);
  if (n === undefined) return null;
  const hero = d.kind === "commander", f = libGauntletFigure(n);
  const link = el("a", { class: "btn btn-quiet btn-inline", text: "Popular decks view",
    href: `${deckHref(d.id, "target")}&tab=matchups&part=gauntlet` });
  const parts = [el("p", { class: "lib-detail-label", text: LIB_GT_CAPTION })];
  if (f && hero && !f.stale) {
    parts.push(el("div", { class: "lib-detail-forge-figure" },
      winRateFigure(f.rate, { size: "hero", what: LIB_GT_WHAT, games: n.games, barred: true }),
      libGauntletFresh(f, { size: "panel", onTint: true })),
    rangeBar(f.rate, { axis: true, decorative: true }));
  } else if (f && hero) {
    parts.push(gtBeforeLine(n));                                  // the board's words (gauntlet.js)
  } else if (f) {
    parts.push(el("div", { class: "lib-detail-forge-figure" + (f.stale ? " is-stale" : "") },
      winRateFigure(f.rate, { what: libGauntletWords(f), games: f.stale ? null : n.games }),
      libGauntletFresh(f, { size: "panel", onTint: true })));
  } else if (n && n.state === "stale_older") {
    parts.push(gtOlderLine(n, { note: !hero }));
  } else {
    parts.push(el("p", { class: "lib-detail-forge-note", text: n && n.state === "unreadable"
      ? "Forge can't read this list." : "Not tested against popular decks yet." }));
  }
  if (f && !f.stale && n.state === "partial" && n.of) {
    parts.push(el("p", { class: "lib-detail-forge-note",
      text: `Against ${num(n.played)} of the ${plural(n.of, "popular deck")} so far.` }));
  }
  parts.push(link);
  return el("div", { class: "lib-detail-forge lib-gauntlet" + (hero ? "" : " lib-gauntlet-second"), role: "group",
    "aria-label": "Against popular decks" }, parts);
}

/** The "Strongest vs popular decks" sort's key: [group, -rate, -low]: a current figure first (0), then a figure
 * from before the last change or older results (1), then untested or not known yet (2), then unreadable (3). */
function libGauntletRank(d) {
  const n = libGauntlet(d), f = libGauntletFigure(n);
  const group = !n ? 2 : n.state === "unreadable" ? 3 : f && !f.stale ? 0
    : n.state === "stale_list" || n.state === "stale_older" ? 1 : 2;
  return f ? [group, -f.rate.value, -(f.rate.low || 0)] : [group, 0, 0];
}
