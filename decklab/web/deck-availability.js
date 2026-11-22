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
  if (![...sources.keys()].some(Boolean)) return null;
  return el("details", { class: "more deck-arrival-details" }, el("summary", { text: "Arrival details" }),
    el("p", { class: "sub deck-avail-sources", text: "On the way: " +
      [...sources].map(([words, quantity]) => `${quantity}${words ? ` from ${words}` : ""}`).join("; ") }));
}

// ------------------------------------------------------------- availability

/** "2 Y'shtola (FIC 207 foil) about A$1,120.00": one listed printing that costs materially more (E5-S31). */
function asListedWords(d, owned) {
  return `${d.missing > 1 ? `${d.missing} ` : ""}${d.name} (${d.printing}) about ${ansMoney(d.aud_missing, owned)}`;
}

/** The banner's second line, only when the list's own printings would cost materially more than the
 * cheapest ones (totals.as_listed, lib/listed_prices.py): the dearest 3 cards, then "and N more". */
function asListedLine(owned) {
  if (owned?.price_error) return null;
  const listed = owned && owned.totals && Array.isArray(owned.totals.as_listed) ? owned.totals.as_listed
    .filter((d) => d && typeof d.name === "string" && typeof d.printing === "string" && Number.isFinite(d.aud_missing)) : [];
  if (!listed.length) return null;
  const shown = listed.slice(0, 3).map((d) => asListedWords(d, owned)).join("; ");
  const rest = listed.length > 3 ? ` and ${listed.length - 3} more` : "";
  const total = Number.isFinite(owned.totals.aud_missing_as_listed) && listed.length > 1
    ? `. About ${ansMoney(owned.totals.aud_missing_as_listed, owned)} in all as listed` : "";
  return el("p", { class: "sub deck-avail-listed", text: `As listed: ${shown}${rest}${total}.` });
}

/** The quiet note on a card whose list names one printing (E2-S30, lib/listed_prices.py annotate_owned):
 * "Own another printing (FDN 227)" when the space has the card only in other printings, or, with both,
 * "Own the listed printing (FIC 207 foil)" when it has the one named. A note, never a warning: it changes no
 * count and doesn't say which deck holds a copy or whether one is free. null for a row without the fields
 * (no named printing, no copies, a card the deck's Printings in box record names, or a viewer who may not
 * see the collection, whose answer has no owned rows at all). */
function ownPrintingWords(r, both = true) {
  if (!r || typeof r.own_printing_label !== "string" || !r.own_printing_label) return null;
  const coming = r.own_printing_on_the_way === true;
  if (r.own_printing === "listed") {
    return both ? `${coming ? "Listed printing on the way" : "Own the listed printing"} (${r.own_printing_label})` : null;
  }
  if (r.own_printing !== "other") return null;
  const more = Number.isSafeInteger(r.own_printing_more) && r.own_printing_more > 0 ? ` and ${r.own_printing_more} more` : "";
  return `${coming ? "Another printing on the way" : "Own another printing"} (${r.own_printing_label}${more})`;
}

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

/** The server checks before redacting private warnings. Older answers have only the visible warnings. */
function deckAvailabilityConfirmed(owned) {
  return Boolean(owned && owned.availability_confirmed !== false && !owned.unresolved?.length && !owned.warnings?.length);
}

/** Copies this list needs from the inventory; basic lands are excluded by the pool. */
function deckAvailability(owned) {
  if (!owned) return null;
  let here = 0, coming = 0, held = 0, lent = 0;
  for (const r of owned.rows) {
    const labels = rowLabels(r);
    const waiting = labels.on_the_way.reduce((n, [, qty]) => n + qty, 0);
    here += Math.max(r.need - r.missing - waiting, 0);
    coming += waiting;
    if (r.missing) {
      held += labels.in_use.reduce((n, [, qty]) => n + qty, 0);
      lent += labels.lent_out || 0;
    }
  }
  const t = owned.totals;
  const confirmed = deckAvailabilityConfirmed(owned);
  return { missing: t.missing, aud: owned.price_error ? null : t.aud_missing, confirmed, here, coming, held, lent,
    priced: !owned.price_error && !(t.unpriced && t.unpriced.length) };
}

/** Check the displayed list, including basic lands that the availability table omits. */
function deckNeedsMainCards(data) {
  return data.sections != null && !data.sections.Deck?.length;
}

/** Keep the selected list, its recorded availability and the actual box together. */
function availabilityBanner(data, screen) {
  const sees = "owned" in data;
  const picker = data.versions.length > 1 ? versionPicker(data, screen) : null;
  const current = listName(data.version);
  const buying = screen?.data === data ? deckFindAndBuyButton(screen) : null;
  if (!sees) return el("div", { class: "deck-avail deck-avail-plain" }, picker || el("p", { class: "sub", text: current }), buying);
  const a = deckAvailability(data.owned);
  const needsMain = deckNeedsMainCards(data);
  const assembled = data.assembled || data.summary.assembled;
  const fromBox = data.summary.status === "built" || data.summary.read_only;
  const counts = [];
  let kind, verdict, action = null;
  if (needsMain && !a?.missing && !a?.coming) {
    kind = "info";
    verdict = "No main-deck cards yet";
  } else if (!a || !a.confirmed) {
    kind = "warn";
    verdict = "To check · Availability could not be confirmed";
    action = el("button", { type: "button", class: "btn deck-avail-action", text: "Review availability",
      onclick: () => openDeckTab("cards", { to: "sec-owned" }) });
  } else {
    kind = a.missing ? "warn" : a.coming ? "info" : "good";
    const missing = `${a.missing} missing from recorded copies`;
    verdict = needsMain ? "No main-deck cards yet" : a.missing ? missing : a.coming
      ? `Ready once ${plural(a.coming, "card")} ${a.coming === 1 ? "arrives" : "arrive"}`
      : fromBox ? "All counted copies are here" : "Ready to build from recorded copies";
    if (a.here) counts.push(`${fromBox ? "Here for this list" : "Free now"} ${a.here}`);
    if (a.coming) counts.push(`On the way ${a.coming}`);
    if (needsMain && a.missing) counts.push(missing);
    if (a.held) counts.push(`Held in another deck or product ${a.held}`);
    if (a.lent) counts.push(`Lent out ${a.lent}`);
    if (a.missing || a.coming) {
      const filter = a.missing ? "missing" : "coming";
      action = el("button", { type: "button", class: "btn deck-avail-action", text: a.missing ? "Show missing" : "Show on the way",
        onclick: () => openDeckTab("cards", { filter, to: "deck-panel-cards" }) });
    }
  }
  // On the Cards tab its filter chips are right there: the banner's button would say the same again.
  const onCards = screen && screen.view && screen.view.tab === "cards";
  return el("section", { class: `deck-avail box box-${kind}${onCards ? " is-on-cards" : ""}`, "aria-label": "This list and its availability" },
    picker,
    el("div", { class: "deck-avail-text" },
      el("p", { class: "deck-avail-head", role: "status" }, el("b", { text: `${current} · ${verdict}` })),
      counts.length ? el("p", { class: "sub deck-avail-more", text: counts.join(" · ") }) : null,
      a?.confirmed && a.here + a.coming + a.missing > 0 ? el("p", { class: "sub", text: "Basic lands are outside this count." }) : null,
      assembled ? el("p", { class: "sub deck-avail-assembled", text: `${assembledStateWords(assembled)} · ${listName(assembled.version)}.` }) : null),
    buying, action, a?.confirmed && a.coming ? incomingBannerSources(data.owned) : null, staleTableBox(data));
}

/** The list links carry the current tab. */
function versionPicker(data, screen) {
  const links = data.versions.map((v) => el("a", { href: versionHref(data, v, screen.view.tab), text: listName(v),
    "aria-current": v === data.version ? "page" : null }));
  screen.versionLinks = data.versions.map((v, i) => [v, links[i]]);
  return el("div", { class: "deck-lists" },
    el("nav", { class: "deck-lists-row", "aria-label": "Which list" }, el("div", { class: "segmented" }, links)),
    el("p", { class: "sub", text: "The Alternative list can use incoming cards. Check availability before packing." }));
}
