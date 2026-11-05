/* Check box's "Which printing?" (lib/api/box_check_printings.py): for each card the box holds that the
 * collection has in two or more printings, which of them are in this box. The choices are local until Save
 * check date, which saves them to the deck's Printings in box line in the same save as the date. A card left
 * as "Not recorded" (or at 0) records nothing; the deck page's Printings in box… changes them later too. */
"use strict";

/** The deck's validated offers, {name: {held, recorded, options}}, or {} (no picker) when they're malformed. */
function boxCheckPrintingOffers(meta) {
  const offers = meta?.printings;
  if (!offers || typeof offers !== "object" || Array.isArray(offers)) return {};
  const whole = (n, max = 9999) => Number.isSafeInteger(n) && n >= 0 && n <= max;
  const text = (s) => typeof s === "string" && s.length > 0 && s.length <= 300 && !/[\u0000-\u001f\u007f]/.test(s);
  const out = {};
  for (const [name, offer] of Object.entries(offers)) {
    if (!text(name) || !offer || !whole(offer.held) || offer.held < 1 || !whole(offer.recorded) || offer.recorded > offer.held
        || !Array.isArray(offer.options) || offer.options.length < 2 || offer.options.length > 100) continue;
    const seen = new Set();
    const good = offer.options.every((o) => o && text(o.set) && text(o.collector_number) && ["nonfoil", "foil", "etched"].includes(o.finish)
      && text(o.label) && (o.set_name === "" || text(o.set_name)) && whole(o.free) && whole(o.recorded)
      && !seen.has(o.set + "|" + o.collector_number + "|" + o.finish) && seen.add(o.set + "|" + o.collector_number + "|" + o.finish));
    if (good && offer.options.reduce((sum, o) => sum + o.recorded, 0) === offer.recorded) out[name] = offer;
  }
  return out;
}

/** One card's "Which printing?" under its tile: a drop-down for a single copy, else a count for each printing.
 * register(control) hands each input to the box check's local guards. read() gives the chosen
 * [{set, collector_number, finish, quantity}] (null when a count is out of range); changed() whether it differs
 * from the deck's record. */
function boxCheckPrintingControl(name, offer, register) {
  const roomOf = (option) => Math.min(offer.held, option.free);
  const words = (option) => packPrintingName(option)
    + (option.recorded ? " (recorded)" : option.free ? "" : " (all in other boxes)");
  const wrap = el("div", { class: "box-check-printing" });
  const legend = el("p", { class: "box-check-printing-title" }, el("strong", { text: "Which printing?" }), " ",
    el("span", { class: "sub", text: plural(offer.options.length, "printing") + " owned" }));
  wrap.append(legend);
  let read;
  if (offer.held === 1) {
    const select = el("select", { "aria-label": name + ": which printing is in the box" },
      el("option", { value: "", text: "Not recorded" }),
      offer.options.map((option, index) => el("option", { value: String(index), text: words(option),
        disabled: !option.recorded && !roomOf(option) })));
    const recorded = offer.options.findIndex((option) => option.recorded > 0);
    select.value = recorded >= 0 ? String(recorded) : "";
    register(select);   // after its value: the box check's guards restore what they first accepted
    wrap.append(select);
    read = () => {
      if (select.value === "") return [];
      const option = offer.options[Number(select.value)];
      return option && (option.recorded || roomOf(option)) ? [{ set: option.set, collector_number: option.collector_number,
        finish: option.finish, quantity: 1 }] : null;
    };
  } else {
    const inputs = offer.options.map((option) => {
      const max = Math.max(option.recorded, roomOf(option));
      const input = register(el("input", { type: "number", inputmode: "numeric", min: 0, max, step: 1,
        value: String(option.recorded), "aria-label": name + ": copies of " + option.label + " in the box" }));
      wrap.append(el("label", { class: "field box-check-printing-count" }, el("span", { text: words(option) }), input));
      return { option, input, max };
    });
    wrap.append(el("p", { class: "sub", text: "The box holds " + plural(offer.held, "copy", "copies") + ". Leave a printing at 0 when you don't know." }));
    read = () => {
      const out = [];
      let total = 0;
      for (const { option, input, max } of inputs) {
        const value = input.value.trim() === "" ? 0 : Number(input.value);
        if (!/^\d*$/.test(input.value.trim()) || !Number.isSafeInteger(value) || value < 0 || value > max) return null;
        total += value;
        if (value) out.push({ set: option.set, collector_number: option.collector_number, finish: option.finish, quantity: value });
      }
      return total <= offer.held ? out : null;
    };
  }
  const key = (picks) => JSON.stringify(picks.map((p) => [p.set, p.collector_number, p.finish, p.quantity]).sort());
  const before = key(offer.options.filter((o) => o.recorded).map((o) => ({ set: o.set, collector_number: o.collector_number,
    finish: o.finish, quantity: o.recorded })));
  return { name, node: wrap, read, changed: () => { const picks = read(); return picks !== null && key(picks) !== before; } };
}

/** The printing changes to save ({name: picks}), {} when none, or null while a choice is out of range. */
function boxCheckPrintingChanges(controls) {
  const out = {};
  for (const control of controls) {
    if (!control.node.isConnected) return null;
    const picks = control.read();
    if (picks === null) return null;
    if (control.changed()) out[control.name] = picks;
  }
  return out;
}

/** "Sol Ring: SLD 2807" lines for the review step. */
function boxCheckPrintingSummary(changes) {
  const names = Object.keys(changes || {});
  if (!names.length) return null;
  return el("section", { class: "box-check-printings-review" }, el("h4", { text: "Printings to record" }),
    el("ul", {}, names.map((name) => el("li", { text: name + ": " + (changes[name].length
      ? changes[name].map((p) => p.set.toUpperCase() + " " + p.collector_number + (p.finish === "nonfoil" ? "" : " " + p.finish)
        + (p.quantity > 1 ? " ×" + p.quantity : "")).join(", ") : "not recorded") }))),
    el("p", { class: "sub", text: "Save check date saves these to the deck's Printings in box in the same save." }));
}
