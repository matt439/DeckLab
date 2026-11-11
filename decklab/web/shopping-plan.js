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
  const unpriced = plan.unpriced ? `, plus ${plural(plan.unpriced, "row")} without a price` : "";
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

/** One shop of the recommended plan: its rows, postage and the add-ons that would reach free postage. */
function shopPlanShop(view, shop, basket) {
  const rows = shop.rows || [];
  const lifts = new Set(shop.postage?.reach?.reaches ? shop.postage.reach.rows : []);
  const addOns = ((basket && basket.add_ons) || []).filter(row => lifts.has(row.queue_row));
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
      text: `Free postage if you bring forward ${addOns.map(row => row.name).join(", ")} (${shopBasketAud(shop.postage.reach.total_aud)}).`}) : null,
    shopBasketActions(copy, shopBasketOrderButton(view, shop, basket)));
}

/** The plan part of Baskets, or null without a plan (no ready row in stock at a read shop). */
function shopBasketPlan(view) {
  const plan = view.data.baskets?.plan;
  if (!plan || !plan.recommended || !Array.isArray(plan.recommended.shops)) return null;
  const best = plan.recommended, cheapest = plan.by_price;
  const baskets = new Map((view.data.baskets.shops || []).filter(Boolean).map(basket => [basket.key, basket]));
  const same = cheapest && (cheapest.keys || []).join() === (best.keys || []).join();
  const lines = [el("div", {class: "shop-plan-best", "data-plan-total": best.total_aud || ""},
    el("p", {class: "shop-plan-destination", text: `Buy from ${shopPlanNames(best.shops)}`}), shopPlanFigures(best),
    el("p", {class: "shop-plan-coverage", text: `${best.cards} of ${plural(plan.wanted, "card")} in stock.`}))];
  if (cheapest && !same) lines.push(el("div", {class: "shop-plan-comparison", "data-plan-by-price": cheapest.total_aud || ""},
    el("h4", {text: "Each card where it's cheapest"}), el("p", {class: "sub", text: shopPlanNames(cheapest.shops)}),
    shopPlanFigures(cheapest), plan.saves_aud ? el("p", {class: "shop-plan-savings",
      text: `The fewest-shops plan is ${shopBasketAud(plan.saves_aud)} less.`}) : null));
  else if (same && best.shops.length > 1 && plan.weighed) lines.push(el("p", {class: "sub",
    text: "Splitting the order costs less than any fewer shops, postage included."}));
  if (!plan.weighed) lines.push(el("p", {class: "note", "data-plan-unweighed": "true",
    text: "Some shops' postage isn't set, so this takes the fewest shops without weighing postage. Set each shop's postage in Settings."}));
  if ((best.uncovered || []).length) lines.push(el("details", {class: "shop-plan-uncovered"},
    el("summary", {text: `Not in stock at these shops together · ${plural(best.uncovered.length, "row")}`}),
    el("ul", {}, best.uncovered.map(row => el("li", {text: row.name})))));
  const others = (plan.options || []).filter(option => (option.keys || []).join() !== (best.keys || []).join());
  return el("div", {class: "shop-plan", "data-plan": (best.keys || []).join(",")},
    el("h3", {text: "Fewest shops"}), lines,
    el("div", {class: "shop-plan-shops"}, best.shops.map(shop => shopPlanShop(view, shop, baskets.get(shop.key)))),
    others.length ? el("details", {class: "more shop-plan-others"}, el("summary", {text: `Other ways (${others.length})`}),
      el("ul", {class: "shop-basket-rows"}, others.map(option => el("li", {class: "shop-plan-option", "data-plan-option": (option.keys || []).join(",")},
        el("strong", {text: shopPlanNames(option.shops)}), shopPlanFigures(option),
        el("span", {class: "sub", text: `${option.cards} of ${plural(plan.wanted, "card")}.`}))))) : null);
}
