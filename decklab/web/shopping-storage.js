/* Shopping's storage fill (E8-S25 slice 7): under On the way, how full each of home's containers with
 * a capacity is now and would be once the pending orders arrive. GET /api/shopping's "storage_fill"
 * (lib/api/shopping_storage.py) is the Card list's own count and pending-delivery scenario, so this
 * file only checks and words it. A read-only estimate: it writes, reserves and places nothing. */
"use strict";

const SHOP_STORAGE_MAX = 1000000000;
const SHOP_STORAGE_CONTAINERS = 20;

/** The checked facts, or null: left out, malformed, or a viewer who isn't one of home's record readers. */
function shopStorageFillFacts(view) {
  const fill = view?.data?.storage_fill;
  if (!fill || typeof fill !== "object" || !seesHomeInventory(state.may)) return null;
  const count = (value) => Number.isSafeInteger(value) && value >= 0 && value <= SHOP_STORAGE_MAX;
  const name = (value) => typeof value === "string" && value.trim().length > 0 && value.length <= 40
    && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
  if (!["ready", "partial"].includes(fill.status) || !Array.isArray(fill.containers) || !fill.containers.length
      || fill.containers.length > SHOP_STORAGE_CONTAINERS || !count(fill.unknown_sources) || !count(fill.pending_products)
      || typeof fill.tokens_excluded !== "boolean" || fill.default !== null && !name(fill.default)) return null;
  const containers = [];
  for (const c of fill.containers) {
    if (!c || !name(c.name) || !count(c.capacity) || c.capacity < 1 || !count(c.now) || !count(c.incoming)
        || c.after !== c.now + c.incoming || !count(c.after)) return null;
    containers.push(Object.freeze({ name: c.name, capacity: c.capacity, now: c.now, incoming: c.incoming, after: c.after,
      over: c.after > c.capacity }));
  }
  return Object.freeze({ containers: Object.freeze(containers), default: fill.default, unknown: fill.unknown_sources,
    products: fill.pending_products, tokens: fill.tokens_excluded });
}

/** The note's caveats, as the Card list's scenario words them: an estimate, and what it leaves out. */
function shopStorageCaveats(facts) {
  const parts = [`An estimate: each pending card goes where copies of its printing are kept${facts.default
    ? `, else ${storagePlaceNamed({ name: facts.default })}` : ""}, as if every order arrived in full. Basic lands aren't counted${facts.tokens ? ", and nor are token cards" : ""}.`];
  if (facts.products) parts.push(`${plural(facts.products, "pending product")} ${facts.products === 1 ? "isn't" : "aren't"} counted: `
    + `whether ${facts.products === 1 ? "it stays" : "they stay"} intact is chosen when ${facts.products === 1 ? "it arrives" : "they arrive"}.`);
  if (facts.unknown) parts.push(`${plural(facts.unknown, "pending delivery", "pending deliveries")} couldn't be checked, `
    + "so their cards aren't counted.");
  return parts.join(" ");
}

/** The note, or null when there's nothing to show. */
function shopStorageFill(view) {
  const facts = shopStorageFillFacts(view);
  if (!facts) return null;
  const line = (c) => c.over
    ? `${c.name} would be over capacity: about ${num(c.after)} cards for about ${num(c.capacity)} places (about ${num(c.now)} now).`
    : `${c.name}: about ${num(c.now)} of ${num(c.capacity)} cards now, about ${num(c.after)} once these arrive.`;
  const over = facts.containers.some((c) => c.over);
  return el("div", { class: over ? "box box-warn shop-storage-fill" : "shop-storage-fill", "data-storage-fill": "" },
    el("h3", { text: "Storage once these arrive" }),
    el("ul", { class: "shop-storage-lines" }, facts.containers.map((c) => el("li", { "data-storage-container": c.name, text: line(c) }))),
    el("p", { class: "sub", text: shopStorageCaveats(facts) }));
}
