/* Shopping's "Build decks together" (E5-S28, first slice): choose two or more home decks, then see what
 * to buy so all of them can be built at once (GET /api/shopping/combined). Read-only: no queue writes.
 * The choice and its answer live on Shopping's view, so a local queue redraw keeps them; navigation
 * and reload start again. A late answer checks its original view, route and profile before drawing. */
"use strict";

const SHOP_COMBINED_MIN = 2, SHOP_COMBINED_MAX = 12;

/** The decks offered: Shopping's visible home decks, each with its own shortfall when it has one. */
function shopCombinedChoices(view) {
  const missing = new Map((view.data.decks_missing || []).map(deck => [deck.id, deck]));
  return (view.data.queue_decks || []).map(deck => ({...deck, missing: missing.get(deck.id)?.missing || 0,
    status: missing.get(deck.id)?.status || null}));
}

function shopCombinedState(view) {
  if (!view.combined) view.combined = {chosen: [], result: null, error: null, busy: false};
  return view.combined;
}

/** The section under Missing cards across decks; absent with fewer than two decks to choose from. */
function shopCombinedSection(view) {
  const choices = shopCombinedChoices(view);
  if (choices.length < SHOP_COMBINED_MIN) return null;
  const combined = shopCombinedState(view);
  const content = el("div", {class: "shop-combined-content"});
  const choose = el("button", {type: "button", class: "btn shop-combined-choose",
    text: combined.chosen.length ? "Change decks…" : "Choose decks…", onclick: () => shopCombinedSheet(view)});
  content.append(el("div", {class: "actions"}, choose));
  if (combined.busy) content.append(loadingBox("Working out what to buy…", {small: true}));
  else if (combined.error) content.append(loadFailed("What to buy for these decks", combined.error,
    () => shopCombinedLoad(view, combined.chosen)));
  else if (combined.result) add(content, [shopCombinedResult(combined.result)]);
  return shopSection("shop-combined", "Build decks together", 0,
    "Choose decks to build at the same time: each free copy counts once, and cards on the way count as yours.", content);
}

/** Tick two or more decks, then Show what to buy. */
function shopCombinedSheet(view) {
  if (!shopQueueActive(view)) return null;
  const combined = shopCombinedState(view);
  const chosen = new Set(combined.chosen);
  const sheet = openSheet({title: "Build decks together"});
  sheet.body.append(el("p", {text: `Tick ${SHOP_COMBINED_MIN} to ${SHOP_COMBINED_MAX} decks to build at the same time.`}));
  const count = el("p", {class: "field-hint shop-combined-count", role: "status"});
  const list = el("div", {class: "shop-combined-choices"});
  const show = () => {
    const ids = [...chosen];
    if (ids.length < SHOP_COMBINED_MIN || ids.length > SHOP_COMBINED_MAX) {
      // A primary that can't act yet moves focus to what's in the way: the first deck left to tick.
      const box = Array.from(list.querySelectorAll("input")).find(input => input.checked === (ids.length > SHOP_COMBINED_MAX));
      if (box) box.focus();
      return;
    }
    sheet.close();
    shopCombinedLoad(view, ids);
  };
  const sync = () => {
    const n = chosen.size, ready = n >= SHOP_COMBINED_MIN && n <= SHOP_COMBINED_MAX;
    count.textContent = n < SHOP_COMBINED_MIN ? `${plural(n, "deck")} ticked: tick at least ${SHOP_COMBINED_MIN}.`
      : n > SHOP_COMBINED_MAX ? `${plural(n, "deck")} ticked: at most ${SHOP_COMBINED_MAX}.` : `${plural(n, "deck")} ticked.`;
    sheetActions(sheet, [{text: "Cancel", onclick: () => sheet.close()},
      {text: "Show what to buy", kind: "primary", value: "show", onclick: show}]);
    const primary = sheet.foot.querySelector(".btn-primary");
    if (!ready) primary.setAttribute("aria-disabled", "true");
  };
  for (const deck of shopCombinedChoices(view)) {
    const input = el("input", {type: "checkbox", value: deck.id, "data-combined-deck": deck.id});
    input.checked = chosen.has(deck.id);
    input.addEventListener("change", () => {
      if (input.checked) chosen.add(deck.id); else chosen.delete(deck.id);
      sync();
    });
    list.append(el("label", {class: "choice"}, input, el("span", {text: deck.title}),
      deck.missing ? el("small", {text: ` · ${plural(deck.missing, "card")} missing on its own`}) : null));
  }
  sheet.body.append(list, count);
  sync();
  return sheet;
}

/** Ask for the combined answer and draw it, unless Shopping has moved on meanwhile. */
async function shopCombinedLoad(view, ids) {
  if (!shopQueueActive(view)) return;
  const combined = shopCombinedState(view);
  combined.chosen = [...ids];
  combined.result = combined.error = null;
  combined.busy = true;
  const ask = combined.request = {};
  view.redraw();
  let result = null, error = null;
  try {
    result = await api(`/api/shopping/combined?decks=${encodeURIComponent(ids.join(","))}`);
  } catch (e) {
    error = e;
  }
  if (combined.request !== ask || !shopQueueActive(view)) return;
  combined.busy = false;
  combined.result = result;
  combined.error = error;
  view.redraw();
}

/** The chosen decks, the totals beside the single-deck sum, then one row per card still to buy. */
function shopCombinedResult(result) {
  const out = [];
  const decks = result.decks || [];
  out.push(el("p", {class: "shop-combined-decks"}, "For ", ...decks.flatMap((deck, i) => [
    i ? (i === decks.length - 1 ? " and " : ", ") : null,
    el("a", {href: `${deckHref(deck.id)}&tab=cards&filter=missing`, text: deck.title})]).filter(Boolean), "."));
  if (!result.ready) {
    out.push(el("div", {class: "note note-warn", role: "status"},
      el("p", {text: "These decks could not be counted together."}),
      el("ul", {class: "shop-count-errors"}, (result.errors || []).map(error => el("li", {},
        error.id ? el("a", {href: deckHref(error.id), text: error.title || error.id}) : null,
        el("span", {text: `${error.id ? ": " : ""}${error.message}`}))))));
    if ((result.warnings || []).length) add(out, [warningsBox(result.warnings, "The home card pool needs review")]);
    return out;
  }
  const totals = result.totals || {};
  if (!(result.rows || []).length) {
    out.push(emptyBox("Nothing to buy: these decks can all be built at the same time."));
    return out;
  }
  const extra = (totals.copies || 0) - (totals.copies_alone || 0);
  out.push(el("p", {class: "shop-combined-totals"},
    el("strong", {text: `${plural(totals.copies, "copy", "copies")} to buy`}),
    ` of ${plural(totals.cards, "card")}` + (extra > 0
      ? `, ${extra} more than the decks miss one at a time (${totals.copies_alone}), because they need the same copies.`
      : "."),
    totals.on_the_way ? el("span", {class: "chips"}, status("info", `${totals.on_the_way} on the way counted`)) : null));
  out.push(el("div", {class: "shop-missing-rows shop-combined-rows"}, result.rows.map(shopCombinedRow)));
  return out;
}

function shopCombinedRow(item) {
  const competing = item.missing - (item.missing_alone || 0);
  const row = cardRow(item.card || null, {name: item.name, qty: item.missing, aside: null,
    meta: `${plural(item.missing, "copy", "copies")} to buy · ${item.need} wanted, ${item.available} free`,
    unknownMeta: "Missing from the chosen Planned lists", viewerGroup: "shopping-combined"});
  const wants = el("ul", {class: "shop-missing-decks"}, (item.decks || []).map(deck => el("li", {},
    el("a", {href: `${deckHref(deck.id)}&tab=cards&filter=missing`, text: deck.title}),
    el("span", {class: "shop-missing-count", text: ` ×${deck.need}`}))));
  const chips = [competing > 0 ? status("warn", `${competing} more because the decks share it`) : null,
    ...(item.on_the_way || []).map(way => status("info", `${way.copies} on the way (${way.source})`))].filter(Boolean);
  const held = (item.held_elsewhere || []).length ? el("small", {class: "shop-combined-held",
    text: "Held by " + item.held_elsewhere.map(h => `${h.title} ×${h.copies}`).join(", ")}) : null;
  return el("article", {class: "shop-missing-card shop-combined-card", "data-combined-card": item.name}, row, wants,
    chips.length ? el("div", {class: "shop-missing-facts"}, chips) : null, held);
}
