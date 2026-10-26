/* The deck page's availability banner, list picker and incoming order labels.
 * Loaded before deck.js; functions run only when the deck page is drawn. */
"use strict";

/** Only the copies this deck awaits. Old answers still carry their source in the table labels. */
function rowIncomingSources(row) {
  const labels = rowLabels(row);
  return labels.incoming_sources || labels.on_the_way.map(([source, quantity]) => ({ source, quantity }));
}

function incomingSourceWords(source) {
  return [source.source, source.product_id && source.order_id ? `order ${source.order_id}` : "",
    source.status].filter(Boolean).join(" · ");
}

/** A source chip wraps even a long order id on a narrow card tile. */
function incomingSourceChip(source) {
  const words = incomingSourceWords(source);
  const chip = status("info", `${source.quantity} on the way${words ? ` · ${words}` : ""}`);
  chip.classList.add("chip-wrap");
  return chip;
}

/** Group all awaited copies by source, so one order is named once in the banner. */
function incomingBannerSources(owned) {
  const sources = new Map();
  for (const row of owned.rows) for (const source of rowIncomingSources(row)) {
    const words = incomingSourceWords(source);
    sources.set(words, (sources.get(words) || 0) + source.quantity);
  }
  if (!sources.size) return null;
  return el("p", { class: "sub deck-avail-sources", text: "On the way: " +
    [...sources].map(([words, quantity]) => `${quantity}${words ? ` from ${words}` : ""}`).join("; ") });
}

// ------------------------------------------------------------- availability

/** A historical date is displayed only as an actual calendar day; it certifies no current contents. */
function boxCheckDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1) return null;
  const date = new Date(value + "T00:00:00Z");
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : value;
}

function boxCheckDateNote(data) {
  const date = boxCheckDate(data.box_checked_on);
  return date ? el("p", { class: "sub deck-box-checked" }, "Last box check recorded: ",
    el("time", { datetime: date, text: date }), ". Contents may have changed since.") : null;
}

/** What the deck's owned rows add up to: {missing, aud, priced, coming, held} (copies missing, their
 * estimated A$, whether every missing card has a price, copies on the way, copies other decks hold that this
 * deck is short of). null when there's no answer to give. */
function deckAvailability(owned) {
  if (!owned) return null;
  let coming = 0, held = 0;
  for (const r of owned.rows) {
    const labels = rowLabels(r);
    coming += labels.on_the_way.reduce((n, [, qty]) => n + qty, 0);
    if (labels.in_use.length) held += Math.min(r.missing, labels.in_use.reduce((n, [, qty]) => n + qty, 0));
  }
  const t = owned.totals;
  return { missing: t.missing, aud: owned.price_error ? null : t.aud_missing,
    priced: !owned.price_error && !(t.unpriced && t.unpriced.length), coming, held };
}

/** The banner under the head: can this list be built now? "Ready to build", "3 cards on the way", or
 * "32 missing, about A$40 · 3 held by other decks" with Show missing. The Planned list / Play-now list picker
 * is folded into it (with its explanation behind an i). A visitor who may not see the collection gets only the
 * picker (when there are two lists). */
function availabilityBanner(data, screen) {
  const sees = "owned" in data;
  const picker = data.versions.length > 1 ? versionPicker(data, screen) : null;
  if (!sees) return picker ? el("div", { class: "deck-avail deck-avail-plain" }, picker) : null;
  const a = deckAvailability(data.owned);
  const which = data.versions.length > 1 ? ` (${listName(data.version, true)})` : "";
  let kind, head, more = [], action = null;
  if (!a) {
    kind = "warn";
    head = "Whether you have every card couldn't be worked out";
    more.push("The warnings below say why.");
  } else if (a.missing > 0) {
    kind = "warn";
    head = `${a.missing} missing` + (a.aud != null ? `, about ${aud(a.aud)}${a.priced ? "" : " and more"}` : "");
    if (a.held) more.push(`${a.held} held by other decks`);
    if (a.coming) more.push(`${plural(a.coming, "card")} on the way`);
    action = el("button", { type: "button", class: "btn deck-avail-action", text: "Show missing",
      onclick: () => openDeckTab("cards", { filter: "missing", to: "deck-panel-cards" }) });
  } else if (a.coming > 0) {
    kind = "info";
    head = `Ready once ${plural(a.coming, "card")} ${a.coming === 1 ? "arrives" : "arrive"}`;
    action = el("button", { type: "button", class: "btn deck-avail-action", text: "Show them",
      onclick: () => openDeckTab("cards", { filter: "coming", to: "deck-panel-cards" }) });
  } else {
    kind = "good";
    head = data.summary.status === "built" || data.summary.read_only ? "Every card is here" : "Ready to build: you have every card";
  }
  const assembled = data.assembled || data.summary.assembled;
  if (assembled?.remaining_count || assembled?.changed) head = `Intended list: ${head}`;
  // On the Cards tab its filter chips are right there: the banner's button would say the same again.
  const onCards = screen && screen.view && screen.view.tab === "cards";
  return el("div", { class: `deck-avail box box-${kind}${onCards ? " is-on-cards" : ""}`, role: "status" },
    el("div", { class: "deck-avail-text" },
      el("p", { class: "deck-avail-head" }, el("b", { text: head + which }),
        more.length ? el("span", { class: "deck-avail-more", text: more.join(" · ") }) : null),
      a && a.coming ? incomingBannerSources(data.owned) : null,
      boxCheckDateNote(data),
      assembled ? el("p", { class: "sub deck-avail-assembled", text: assembledStateWords(assembled) + "." }) : null),
    action, picker);
}

/** Planned list | Play-now list, as links that keep the tab, and an i that says what the two are. */
function versionPicker(data, screen) {
  const about = el("p", { class: "deck-lists-about", id: "deck-lists-about", hidden: true,
    text: `The ${listName("target", true)} is the deck as planned, cards still to buy included. The ` +
      `${listName("owned", true)} is the same idea using only cards you have or have on the way.` });
  const info = el("button", { type: "button", class: "btn btn-quiet deck-lists-info", "aria-expanded": "false",
    "aria-controls": "deck-lists-about", "aria-label": "What are the two lists?", text: "i",
    onclick: () => {
      about.hidden = !about.hidden;
      info.setAttribute("aria-expanded", String(!about.hidden));
    } });
  // Each link's address carries the tab shown (deckAddress keeps it up to date as the tab changes).
  const links = data.versions.map((v) => el("a", { href: versionHref(data, v, screen.view.tab), text: listName(v),
    "aria-current": v === data.version ? "page" : null }));
  screen.versionLinks = data.versions.map((v, i) => [v, links[i]]);
  return el("div", { class: "deck-lists" },
    el("nav", { class: "deck-lists-row", "aria-label": "Which list" },
      el("div", { class: "segmented" }, links), info),
    about);
}
