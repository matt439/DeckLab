/* Compare two ways to finish groups of decks from the same household pool (E5-S42). */
"use strict";

function shopCompareButton(view) {
  if (shopCombinedChoices(view).length < 3) return null;
  return el("button", {type: "button", class: "btn shop-compare-choose",
    text: view.compare ? "Change deck groups…" : "Compare which decks to finish…", onclick: () => shopCompareSheet(view)});
}

function shopCompareSheet(view) {
  if (!shopQueueActive(view)) return;
  const initial = view.compare?.ids || [shopCombinedState(view).chosen, shopCombinedState(view).chosen];
  const groups = initial.map(ids => new Set(ids));
  const sheet = shopTrackQueueSheet(openSheet({title: "Compare which decks to finish"}), view);
  sheet.body.append(el("p", {text: "Choose two alternative groups of 2 to 12 decks. The same deck may appear in both groups. Each group gets its own allocation of the collection."}));
  const hint = el("p", {class: "field-hint", role: "status"});
  const sync = () => {
    const issue = groups.findIndex(group => group.size < SHOP_COMBINED_MIN || group.size > SHOP_COMBINED_MAX);
    const same = groups[0].size === groups[1].size && [...groups[0]].every(id => groups[1].has(id));
    hint.textContent = issue >= 0 ? `Choose 2 to 12 decks in the ${issue ? "second" : "first"} group.`
      : same ? "Choose two different groups." : "";
    sheet.foot.querySelector(".btn-primary").setAttribute("aria-disabled", String(Boolean(hint.textContent)));
  };
  const lists = groups.map((chosen, i) => {
    const list = el("fieldset", {class: "shop-combined-choices"}, el("legend", {text: i ? "Second group" : "First group"}));
    shopCombinedChecklist(view, list, chosen, sync);
    return list;
  });
  const copy = el("button", {type: "button", class: "btn", text: "Copy first group to second", onclick: () => {
    groups[1].clear();
    for (const id of groups[0]) groups[1].add(id);
    for (const box of lists[1].querySelectorAll("input")) box.checked = groups[1].has(box.value);
    sync();
  }});
  sheet.body.append(lists[0], copy, lists[1], hint);
  sheetActions(sheet, [{text: "Cancel", onclick: () => sheet.close()}, {text: "Compare groups", kind: "primary", onclick: () => {
    const issue = groups.findIndex(group => group.size < SHOP_COMBINED_MIN || group.size > SHOP_COMBINED_MAX);
    if (hint.textContent) return lists[issue < 0 ? 1 : issue].querySelector("input").focus();
    sheet.close();
    shopCompareLoad(view, groups.map(group => [...group]));
  }}]);
  sync();
}

async function shopCompareLoad(view, ids) {
  if (!shopQueueActive(view)) return;
  const comparison = view.compare = {ids, busy: true};
  const redraw = focus => {
    view.redraw();
    if (focus) view.root.querySelector(".shop-combined-content")?.querySelector(".shop-compare-choose")?.focus();
  };
  redraw(true);
  const pair = decks => encodeURIComponent(decks.join(","));
  try {
    comparison.answer = await api(`/api/shopping/compare?left=${pair(ids[0])}&right=${pair(ids[1])}`);
  } catch (error) {
    comparison.error = error;
  }
  if (view.compare !== comparison || !shopQueueActive(view)) return;
  comparison.busy = false;
  redraw(Boolean(document.activeElement?.closest(".shop-compare-choose")));
}

function shopCompareContent(view) {
  const comparison = view.compare;
  if (!comparison) return null;
  if (comparison.busy) return loadingBox("Comparing deck groups…", {small: true});
  if (comparison.error) return loadFailed("Deck group comparison", comparison.error, () => shopCompareLoad(view, comparison.ids));
  const pairs = [comparison.answer.left, comparison.answer.right];
  return el("div", {}, el("p", {class: "shop-pair-summary", role: "status", text: shopCompareSummary(pairs)}),
    el("p", {class: "sub", text: "Choose one group to finish. Each group uses its Planned lists and assumes enough ordinary basic lands."}),
    el("div", {class: "shop-pair-results"}, pairs.map(pair => shopComparePair(pair, view))));
}

function shopCompareSummary(pairs) {
  const title = pair => pair.decks.map(deck => deck.title).join(" + ");
  const now = pairs.filter(pair => pair.ready && !pair.today_missing);
  if (now.length === 2) return "Either group can be built now.";
  if (now.length === 1) return `${title(now[0])} can be built now.`;
  if (pairs.some(pair => !pair.ready)) return "One or both groups could not be counted.";
  const waiting = pairs.filter(pair => !pair.buy);
  if (waiting.length === 2) return "Either group can be finished when its cards arrive.";
  if (waiting.length) return `${title(waiting[0])} only needs cards already on the way.`;
  const comparable = pairs.every(({pricing: p}) => p && shopBasketAud(p.delivered_aud) && p.weighed && p.search_complete
    && !p.partial_shops?.length && !p.carried_shops?.length && p.snapshots?.length && p.snapshots.every(check => check.read && !check.unchecked && !check.failed));
  if (!comparable) return "Both groups need purchases. The saved checks do not establish which costs less.";
  const [left, right] = pairs.map(pair => Math.round(Number(pair.pricing.delivered_aud) * 100));
  if (left === right) return "Both groups have the same estimated cost including postage.";
  return `${title(pairs[left < right ? 0 : 1])} costs ${moneyIn(Math.abs(left - right) / 100, "AUD")} less with the saved shop checks.`;
}

function shopComparePair(pair, view) {
  const card = el("article", {class: "shop-pair-card"},
    el("h3", {}, pair.decks.map((deck, i) => [i ? " + " : "", el("a", {href: deckHref(deck.id), text: deck.title})]).flat()));
  add(card, [warningsBox(pair.warnings, "Card pool needs review")]);
  if (!pair.ready) {
    card.append(el("p", {text: "Readiness and cost unknown."}),
      el("ul", {}, pair.errors.map(error => el("li", {text: error.message}))));
    return card;
  }
  card.append(el("p", {}, el("strong", {text: pair.today_missing
    ? `${plural(pair.today_missing, "copy", "copies")} missing today` : "Ready to build now"})),
    pair.required != null ? el("p", {text: `${pair.here_now} of ${pair.required} counted copies available now`}) : "",
    el("p", {text: `${pair.incoming} on the way · ${pair.buy} still to buy`}));
  if (pair.cards?.length) card.append(el("details", {}, el("summary", {text: "Cards needed"}),
    el("ul", {}, pair.cards.map(row => el("li", {}, el("strong", {text: row.name}),
      ` · ${row.incoming} on the way · ${row.buy} to buy`,
      (row.on_the_way || []).map(source => el("small", {class: "shop-basket-facts",
        text: `${source.source} ×${source.copies}` })))))));
  const price = pair.pricing;
  if (!pair.buy) {
    card.append(el("p", {text: "No purchase needed."}));
    return card;
  }
  if (!price) {
    card.append(el("p", {text: "Cost to finish unknown."}));
    return card;
  }
  const delivered = shopBasketAud(price.delivered_aud);
  const complete = delivered != null;
  card.append(el("p", {}, el("strong", {text: complete
    ? `${delivered} including postage (saved shop checks)` : "Cost to finish unknown"})));
  if (!complete) card.append(el("p", {text: `${price.covered} of ${price.wanted} copies covered.` +
    (price.covered ? ` Known items and postage: ${shopBasketAud(price.known_aud) || "unknown"}.` : "")}));
  const details = [
    price.unpriced_copies && `${plural(price.unpriced_copies, "copy", "copies")} without a price`,
    price.postage_unknown?.length && "Postage unknown at " + price.postage_unknown.join(", "),
    price.stock_unknown?.length && "Stock for the remaining copies is unconfirmed at " + price.stock_unknown.join(", "),
    ...(price.availability_only || []).filter(shop => !price.stock_unknown?.includes(shop))
      .map(shop => `${shop} showed availability without a stock count.`),
    price.weighed === false && price.covered > 0 && "Postage could not be weighed across the shop options.",
    price.partial_shops?.length && "Partial shop snapshot: " + price.partial_shops.join(", "),
    price.carried_shops?.length && "Earlier listings used from " + price.carried_shops.join(", "),
    price.search_ran && price.search_complete === false && "The planner reached its search limit. Another basket could cost less.",
  ].filter(Boolean);
  if (details.length) card.append(el("ul", {}, details.map(text => el("li", {text}))));
  add(card, [shopPlanUncovered({...price, cards: price.covered}, price.wanted)]);
  if (price.shops?.length) card.append(el("details", {}, el("summary", {text: "Shop estimate"}),
    price.shops.map(shop => el("div", {}, el("strong", {text: shop.shop}),
      el("p", {text: `${shopBasketAud(shop.cards_aud) || "Unknown"} in known card prices · ` +
        (shop.postage_aud == null ? "Postage unknown" : `${shopBasketAud(shop.postage_aud)} postage`)}),
      el("ul", {}, shop.rows.map(row => el("li", {}, shopPlanCardWords(row),
        (row.printings || []).map(item => el("span", {class: "shop-basket-facts",
          text: `${item.copies} × ${shopPlanListingWords(item)}${item.finish ? "" : " · Finish unconfirmed"}`})),
        row.carried ? " · Earlier listing" : null, row.partial ? " · Partial check" : null,
        row.fetched_at ? el("span", {class: "shop-basket-facts"}, shopSnapshotWhen(row.fetched_at)) : null)))))));
  if (price.snapshots?.length) card.append(el("details", {}, el("summary", {text: "Saved shop checks"}),
    el("ul", {}, price.snapshots.map(shop => el("li", {}, shop.shop, " · ",
      shop.read ? shopSnapshotWhen(shop.fetched_at) || "Date unknown" : "No readable check",
      shop.unchecked ? ` · ${plural(shop.unchecked, "card")} unchecked` : null,
      shop.failed ? ` · Checks failed for ${plural(shop.failed, "card")}` : null)))));
  if (isAdminProfile()) card.append(el("a", {class: "btn btn-quiet", href: "#/settings?part=prices", text: "Price settings"}));
  const canQueue = shopCombinedQueueOffered(view);
  const otherFinish = price.shops?.some(shop => shop.rows.some(row => row.printings?.some(item => item.finish !== "nonfoil")));
  if (canQueue && otherFinish) card.append(el("p", {class: "field-hint",
    text: "Queue review requests nonfoil copies. Check the finishes included in the shop estimate."}));
  if (canQueue) card.append(el("button", {type: "button", class: "btn shop-queue-write",
    text: "Review queue for this group…", disabled: view.busy || view.stale, onclick: () => {
      if (!shopQueueActive(view) || view.busy || view.stale) return;
      openQueueCombinedSheet(pair.decks, () => {
        if (!shopQueueActive(view)) return;
        shopCombinedCarry = {profile: view.profile, chosen: pair.decks.map(deck => deck.id)};
        route();
      }, view);
    }}));
  return card;
}
