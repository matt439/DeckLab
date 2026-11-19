/* Shopping's fewest-shops plan (E5-S27), at the top of Baskets: GET /api/shopping's baskets.plan
 * (lib/api/shop_plan.py). The recommended shops with their cards, postage and total, beside buying each
 * card where it's cheapest, so both ways show; the other combinations folded away. When a used shop's
 * postage isn't set, the plan takes the fewest shops and says postage wasn't weighed. Copy this shop's
 * list copies a plan shop's rows at the copies it buys there. Read only, as the baskets. */
"use strict";

/** "MTGMate", "MTGMate and Games Portal", "A, B and C". */
function shopPlanNames(shops) {
  const names = (shops || []).map(shop => shop.shop);
  return names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** "A$3.70 cards + A$8.00 postage = A$11.70", with unknown postage and rows without a price named. The shops'
 * prices and postage are AUD, whatever the configured currency (E11-S53). */
function shopPlanAmounts(plan) {
  const cards = shopBasketAud(plan.cards_aud) || "A$0.00", postage = shopBasketAud(plan.postage_aud) || "A$0.00";
  const total = shopBasketAud(plan.total_aud) || cards;
  const unknown = (plan.postage_unknown || []).length ? `, plus postage not known at ${plan.postage_unknown.join(" and ")}` : "";
  const missingPrices = plan.unpriced_copies ? plural(plan.unpriced_copies, "copy", "copies")
    : plan.unpriced ? plural(plan.unpriced, "row") : "";
  const unpriced = missingPrices ? `, plus ${missingPrices} without a price` : "";
  return {cards, postage, total, caveats: `${unknown}${unpriced}`};
}

function shopPlanSum(plan) {
  const amounts = shopPlanAmounts(plan);
  return `${amounts.cards} cards + ${amounts.postage} postage = ${amounts.total}${amounts.caveats}`;
}

/** The same saved amounts as shopPlanSum, separated into scan-friendly figures, with uncertainty adjacent. */
function shopPlanFigures(plan) {
  const amounts = shopPlanAmounts(plan);
  const figure = (label, value, total = false) => el("div", {class: `shop-plan-figure${total ? " shop-plan-figure-total" : ""}`},
    el("span", {text: label}), el("strong", {text: value}));
  return el("div", {class: "shop-plan-cost-summary"},
    el("div", {class: "shop-plan-figures"}, figure("Cards", amounts.cards), figure("Postage counted", amounts.postage),
      figure(amounts.caveats ? "Known total" : "Total", amounts.total, true)),
    amounts.caveats ? el("p", {class: "shop-plan-caveats", text: amounts.caveats.replace(/^, /, "")}) : null);
}

function shopPlanCopyList(view, rows) {
  if (!shopBasketsCurrent(view)) return null;
  return shopCopyRows(rows.map(row => ({...row, quantity: row.copies})));
}

function shopPlanCardWords(row) {
  const printing = row.printing === "exact" && row.set
    ? ` (${[String(row.set).toUpperCase(), row.collector_number, row.finish].filter(Boolean).join(" ")})` : "";
  const copies = row.copies ?? row.quantity;
  return `${copies ? `${copies} × ` : ""}${row.name}${printing}`;
}

function shopPlanStockNote(plan) {
  return plan.stock_unknown?.length ? el("p", {class: "sub",
    text: `Stock counts weren't shown at ${plan.stock_unknown.join(" and ")}. Check those quantities before ordering.`}) : null;
}

/** Compare the actual rows and charges so identical shop names alone can't hide a distinct plan. */
function shopPlanAllocation(plan) {
  return JSON.stringify([plan.total_aud, plan.shops.map(shop => [shop.key, shop.subtotal_aud, shop.postage?.charged_aud,
    (shop.rows || []).map(row => [row.queue_row, row.copies, row.line_aud])])]);
}

function shopPlanBreakdown(plan) {
  return el("ul", {class: "shop-basket-gaps"}, plan.shops.map(shop => {
    const postage = shopBasketAud(shop.postage?.charged_aud);
    return el("li", {"data-plan-breakdown": shop.key}, el("strong", {text: shop.shop}),
      el("span", {text: (shop.rows || []).map(shopPlanCardWords).join(", ")}),
      el("span", {text: postage ? `${postage} postage` : "Postage not known"}));
  }));
}

/** One shop of the recommended plan: its rows, postage and the add-ons that would reach free postage. */
function shopPlanShop(view, shop, basket) {
  const rows = shop.rows || [];
  const lifts = new Set(shop.postage?.reach?.reaches ? shop.postage.reach.rows : []);
  const addOns = (shop.add_ons ?? basket?.add_ons ?? []).filter(row => lifts.has(row.queue_row));
  const copy = el("button", {type: "button", class: "btn btn-quiet shop-plan-copy", text: "Copy this shop's list",
    "aria-label": `Copy the plan's list for ${shop.shop}`, "data-copy-shop": shop.shop,
    onclick: event => shopCopyShop(view, shop.shop, event.currentTarget, {list: () => shopPlanCopyList(view, rows),
      note: "in this plan's list for the shop (add-ons not included)", selector: ".shop-plan-copy"})});
  if (!shopBasketsCurrent(view)) copy.disabled = true;
  return el("div", {class: "shop-plan-shop", "data-plan-shop": shop.key},
    el("div", {class: "shop-plan-shop-head"}, el("h4", {text: shop.shop}),
      el("span", {class: "sub", text: `${plural(shop.cards, "card")}, `}),
      el("strong", {text: shopBasketAud(shop.subtotal_aud) || "A$0.00"})),
    el("ul", {class: "shop-basket-rows"}, rows.map(row => el("li", {class: "shop-basket-row", "data-plan-row": row.name},
      shopBasketItemHead(row, view)))),
    shopBasketPostage(shop.postage),
    addOns.length ? el("p", {class: "shop-basket-reach", "data-plan-reach": shop.key,
      text: `Free postage if you bring forward ${addOns.map(shopPlanCardWords).join(", ")} (${shopBasketAud(shop.postage.reach.total_aud)}).`}) : null,
    shopBasketActions(copy, shopBasketOrderButton(view, shop, basket)));
}

/** The missing quantities and the shops' evidence for each queue row. */
function shopPlanUncovered(best, wanted) {
  const rows = best.uncovered || [];
  if (!rows.length) return null;
  return el("details", {class: "shop-plan-uncovered"},
    el("summary", {text: `${plural(wanted - best.cards, "card")} still needed`}),
    el("ul", {}, rows.map(row => {
      const reasons = (row.shops || []).map(shopBasketReason).join(" · ");
      return el("li", {}, el("span", {text: shopPlanCardWords(row)}),
        reasons ? el("span", {class: "shop-basket-facts", text: reasons}) : null);
    })));
}

/** The plan part of Baskets, or null when there are no ready copies to plan for. */
function shopBasketPlan(view) {
  const plan = view.data.baskets?.plan;
  if (!plan?.wanted || !Array.isArray(plan.recommended?.shops)) return null;
  const best = plan.recommended, cheapest = plan.by_price;
  const hasShops = best.shops.length > 0;
  const baskets = new Map((view.data.baskets.shops || []).filter(Boolean).map(basket => [basket.key, basket]));
  const allocation = shopPlanAllocation(best);
  const same = cheapest && shopPlanAllocation(cheapest) === allocation;
  const lines = [el("div", {class: "shop-plan-best", "data-plan-total": best.total_aud || ""},
    hasShops ? el("p", {class: "shop-plan-destination", text: `Buy from ${shopPlanNames(best.shops)}`}) : null,
    hasShops ? shopPlanFigures(best) : null,
    el("p", {class: "shop-plan-coverage", text: `${best.cards} of ${plural(plan.wanted, "card")} covered.`}),
    shopPlanStockNote(best), shopPlanUncovered(best, plan.wanted))];
  if (hasShops && cheapest && !same) lines.push(el("div", {class: "shop-plan-comparison", "data-plan-by-price": cheapest.total_aud || ""},
    el("h4", {text: "Each card where it's cheapest"}),
    shopPlanFigures(cheapest), el("p", {class: "sub", text: `${cheapest.cards} of ${plural(plan.wanted, "card")} covered.`}),
    shopPlanStockNote(cheapest), plan.saves_aud ? el("p", {class: "shop-plan-savings",
      text: `The fewest-shops plan is ${shopBasketAud(plan.saves_aud)} less.`}) : null, shopPlanBreakdown(cheapest)));
  else if (hasShops && same && best.shops.length > 1) lines.push(el("p", {class: "sub", "data-plan-by-price": cheapest.total_aud || "",
    text: "Buying each card where it's cheapest gives the same shop lists and total."}));
  if (hasShops && !plan.weighed) lines.push(el("p", {class: "note", "data-plan-unweighed": "true",
    text: "Some shops' postage isn't set, so this takes the fewest shops without weighing postage. Set each shop's postage in Settings."}));
  const others = (plan.options || []).filter(option => shopPlanAllocation(option) !== allocation);
  return el("div", {class: "shop-plan", "data-plan": (best.keys || []).join(",")},
    el("h3", {text: "Fewest shops"}), lines,
    hasShops ? el("div", {class: "shop-plan-shops"}, best.shops.map(shop => shopPlanShop(view, shop, baskets.get(shop.key)))) : null,
    others.length ? el("details", {class: "more shop-plan-others"}, el("summary", {text: `Other ways (${others.length})`}),
      el("ul", {class: "shop-basket-rows"}, others.map(option => el("li", {class: "shop-plan-option", "data-plan-option": (option.keys || []).join(",")},
        shopPlanBreakdown(option), shopPlanFigures(option), shopPlanStockNote(option),
        el("span", {class: "sub", text: `${option.cards} of ${plural(plan.wanted, "card")} covered.`}))))) : null);
}
