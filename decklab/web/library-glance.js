"use strict";

/* The library's detail pane, past its summary (lab, 1000 px and up): the selected deck's key cards, the stats in
   brief with a small mana curve, and the start of its play guide. They come from GET /api/deck (without its
   matchups, the slow part), fetched when a deck is selected and kept per revision, so going back to a deck
   draws them at once. Each part links to the deck page's tab that has the rest. Nothing is shown while they
   load or when they can't be read: the summary above stands on its own. */

const LIB_GLANCE = new Map();          // "<id>@<revision>" -> Promise of GET /api/deck's answer (null on failure)
const LIB_GLANCE_KEEP = 24;            // decks remembered; the oldest go first

/** The pane's two later parts, filled in when the deck has loaded: {facts, cards} (empty until then). */
function libGlance(d) {
  const facts = el("div", { class: "lib-glance-facts" });
  const cards = el("div", { class: "lib-glance-cards" });
  if (d.error || !d.id) return { facts, cards };
  libGlanceData(d).then((data) => {
    if (!data || !data.sections || !facts.isConnected) return;
    add(facts, [libGlanceStats(d, data), libGlancePlan(d, data)]);
    const keys = libGlanceKeys(d, data);
    if (keys) cards.append(keys);
  }).catch(() => {});
  return { facts, cards };
}

/** The deck's GET /api/deck answer, from LIB_GLANCE or fetched (null when it can't be read). */
function libGlanceData(d) {
  const key = `${d.id}@${d.revision == null ? "" : d.revision}`;
  if (!LIB_GLANCE.has(key)) {
    LIB_GLANCE.set(key, api(`/api/deck?id=${encodeURIComponent(d.id)}&version=target&omit=matchups`)
      .then((data) => (data && !data.error ? data : null))
      .catch(() => { LIB_GLANCE.delete(key); return null; }));
    while (LIB_GLANCE.size > LIB_GLANCE_KEEP) LIB_GLANCE.delete(LIB_GLANCE.keys().next().value);
  }
  return LIB_GLANCE.get(key);
}

/** The stats in brief (the deck page's verdict strip) over a small mana curve; null without stats. */
function libGlanceStats(d, data) {
  const st = data.stats;
  if (!st) return null;
  const verdict = statsVerdict(st, data.summary || d);
  const curve = st.curve && st.curve.buckets && st.curve.buckets.some((b) => b.total) ? libGlanceCurve(st.curve) : null;
  if (!verdict && !curve) return null;
  return el("section", { class: "lib-glance-part", "aria-label": "At a glance" },
    el("div", { class: "lib-glance-head" },
      el("p", { class: "lib-detail-label", text: "At a glance" }),
      el("a", { class: "btn btn-quiet btn-inline", href: `${deckHref(d.id)}&tab=stats`, text: "All the stats" })),
    verdict, curve);
}

/** The mana curve as columns: creatures under other spells, the count over each and its mana value under. */
function libGlanceCurve(curve) {
  const top = Math.max(...curve.buckets.map((b) => b.total), 1);
  const words = curve.buckets.filter((b) => b.total).map((b) => `${b.mv}: ${b.total}`).join(", ");
  return el("div", { class: "lib-curve-wrap" },
   el("div", { class: "lib-curve", role: "img", "aria-label": `Mana curve, cards at each mana value: ${words}` },
    curve.buckets.map((b) => el("div", { class: "lib-curve-col", "aria-hidden": "true" },
      el("span", { class: "lib-curve-n", text: b.total ? String(b.total) : "" }),
      el("span", { class: "lib-curve-bar", style: `--h: ${(100 * b.total / top).toFixed(1)}%` },
        el("span", { class: "lib-curve-other", style: `flex-grow: ${b.noncreatures}` }),
        el("span", { class: "lib-curve-creatures", style: `flex-grow: ${b.creatures}` })),
      el("span", { class: "lib-curve-mv", text: String(b.mv) })))),
    el("p", { class: "lib-curve-key", "aria-hidden": "true" },
      el("span", { class: "swatch", style: "background: var(--series-1)" }), "Creatures",
      el("span", { class: "swatch", style: "background: var(--series-2)" }), "Other spells"));
}

/** The play guide's first topic, its opening words as plain text (four lines at most); null without a guide. */
function libGlancePlan(d, data) {
  const first = data.guide && data.guide.sections && data.guide.sections.find((p) => libGlanceText(p.markdown));
  if (!first) return null;
  return el("section", { class: "lib-glance-part", "aria-label": "How to play" },
    el("div", { class: "lib-glance-head" },
      el("p", { class: "lib-detail-label", text: first.title || "How to play" }),
      el("a", { class: "btn btn-quiet btn-inline", href: deckHref(d.id), text: "How to play" })),
    el("p", { class: "lib-glance-plan", text: libGlanceText(first.markdown) }));
}

/** Markdown as one line of plain text: emphasis, code and links kept as their words, list marks and headings
 * dropped, and a full stop after a line (a list item, a heading) that has no stop of its own. */
function libGlanceText(markdown) {
  return String(markdown || "").split(/\r?\n/)
    .map((line) => line.trim().replace(/^#{1,6}\s+/, "").replace(/^([-+*]|\d+[.)])\s+/, ""))
    .filter(Boolean).map((line) => (/[.!?:;,)]$/.test(line) ? line : `${line}.`)).join(" ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g, "$1$2$3")
    .replace(/\s+/g, " ").trim();
}

/** The deck page's key cards (deck.js keyCardLines), smaller: a swipe goes from one to the next. */
function libGlanceKeys(d, data) {
  const names = Object.values(data.sections).flat().map((l) => l.name).filter(Boolean);
  const { commanders, lines } = keyCardLines(data, cardNamesPattern(names));
  if (!lines.length) return null;
  const total = copies(Object.entries(data.sections).filter(([name]) => name !== "Sideboard").flatMap(([, l]) => l));
  return el("section", { class: "lib-glance-part", "aria-label": commanders.length ? "Commander and key cards" : "Key cards" },
    el("div", { class: "lib-glance-head" },
      el("p", { class: "lib-detail-label", text: commanders.length ? "Commander and key cards" : "Key cards" }),
      el("a", { class: "btn btn-quiet btn-inline", href: `${deckHref(d.id)}&tab=cards`, text: `All ${plural(total, "card")}` })),
    el("div", { class: "lib-key-cards" }, lines.map((line) => cardTile(line.card, {
      qty: line.qty, name: line.name, viewerGroup: "lib-key", sizes: "180px",
      caption: commanders.includes(line) ? "Commander" : `${plural(line.qty, "copy", "copies")} in the deck` }))));
}
