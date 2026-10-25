/* Receive delivery row/tile presentation; checks and recording remain in their guarded workflow. */
"use strict";

/** Compact List keeps every attention reason under the name; details never decide whether a row is checked. */
function rcptListName(view, comp, row, name) {
  const labels = { "condition or language not set": "Condition or language ?", "back not confirmed": "Back not said yet",
    "a note": "Check note", "default picture": "Check printing", edited: "Edited" };
  const attention = rcptAttention(view, comp, row).map((why) => el("span", { class: "status status-warn",
    title: why === "a note" ? rcptFlag(comp, row) : why === "default picture" ? rcptUnrecorded(comp, row) : null,
    text: labels[why] || why }));
  const parts = comp.rows.filter((r) => r.orig === row.orig);
  return el("span", { class: "rcpt-row-name" }, name,
    attention.length ? el("span", { class: "rcpt-row-attention" }, attention) : null,
    parts.length > 1 ? el("span", { class: "rcpt-row-part", id: `rcpt-row-part-${row.key}` },
      !row.ticked ? el("span", { class: "rcpt-pending-swatch", "aria-hidden": "true" }) : null,
      `Part ${parts.indexOf(row) + 1} of ${parts.length}${row.ticked ? "" : " · still pending"}`) : null);
}

function rcptListDetails(comp, row) {
  const v = row.values;
  const detail = (value, unknown) => value || el("span", {},
    el("span", { "aria-hidden": "true", text: "—" }), el("span", { class: "sr-only", text: unknown }));
  return el("span", { class: "rcpt-row-details", id: `rcpt-row-details-${row.key}` }, el("span", { text: rcptMeta(comp, row) }),
    comp.kind === "cards" ? el("span", {}, detail(v.condition, "Condition not recorded"), " · ",
      detail(v.language && v.language.toUpperCase(), "Language not recorded")) : null);
}

/** One native check label and one separate inspection action; no interactive content is nested in the label. */
function rcptPictureTile(view, comp, row, card, chips) {
  const name = comp.kind === "tokens" ? card.name : row.values.name;
  const parts = comp.rows.filter((r) => r.orig === row.orig), pending = parts.length > 1 && !row.ticked;
  const details = rcptListDetails(comp, row);
  details.setAttribute("class", "sr-only");
  const why = rcptAttention(view, comp, row);
  const extra = el("span", { class: "sr-only", id: `rcpt-picture-description-${row.key}` },
    why.length ? `Needs attention: ${why.join(", ")}. ` : "",
    parts.length > 1 ? `Part ${parts.indexOf(row) + 1} of ${parts.length}${pending ? ", still pending" : ""}.` : "");
  const described = `rcpt-row-details-${row.key} ${extra.id}`;
  const check = el("input", { type: "checkbox", class: "rcpt-tick rcpt-picture-tick", checked: row.ticked,
    "aria-label": `Check off ${plural(rcptQty(row), "copy", "copies")} of ${name}`, "aria-describedby": described,
    onchange: (e) => { if (comp.selected) rcptTick(view, comp, row, e.currentTarget.checked); e.currentTarget.checked = row.ticked; } });
  const pendingChip = pending ? el("span", { class: "chip chip-plain rcpt-picture-pending" },
    el("span", { class: "rcpt-pending-swatch", "aria-hidden": "true" }), "Still pending") : null;
  const common = { qty: rcptQty(row), meta: rcptMeta(comp, row, true), check, ticked: row.ticked,
    unrecorded: rcptUnrecorded(comp, row), chips: [...chips, pendingChip].filter(Boolean) };
  const label = comp.kind === "tokens"
    ? tokenTile({ front: row.values.front, back: row.values.back, img: card.img_small,
      back_img: card.faces ? card.faces[1].img_small : null }, { ...common, name: card.name })
    : cardTile(card, { ...common, finish: row.values.finish, name: frontName(row.values.name) });
  label.classList.add("rcpt-picture-label");
  const pictured = label.querySelector(".card-tile-img") || label.querySelector(".card-tile-back");
  if (row.ticked && pictured) label.querySelector(".card-tile-pic").append(
    el("span", { class: "card-tile-tick rcpt-picture-done", "aria-hidden": "true" }));
  const open = el("button", { type: "button", class: "btn btn-quiet rcpt-picture-inspect", text: "Inspect",
    "aria-label": `Inspect ${name}`, "aria-describedby": described, "aria-haspopup": "dialog",
    onclick: () => { if (comp.selected) rcptOpenSheet(view, comp, row); } });
  return { tile: el("div", { class: "rcpt-check-tile" + (pending ? " is-pending-split" : "") }, label, open, details, extra), open };
}

/** One row's tile (or, in List, its row): its picture with the copies, the tick, the name, the printing and the
 * chips. Active Pictures use a native check label plus Inspect; List's inspection opens the same sheet. Read only,
 * or on a part that hasn't arrived, a tap opens the viewer and there's no tick. */
function rcptTile(view, comp, row, readOnly) {
  const q = rcptQty(row);
  const active = !readOnly && comp.selected;
  const list = view.layout === "list" && !readOnly;
  const name = comp.kind === "tokens" ? row.values.front : row.values.name;
  const caption = `${plural(q, "copy", "copies")} in this delivery · ${rcptMeta(comp, row)}`;
  const card = rcptCard(comp, row);
  const chips = rcptChips(view, comp, row);
  const label = active ? `${name}: check and edit` : null;
  const onclick = active ? () => rcptOpenSheet(view, comp, row) : card ? (e) => openCard(card, e.currentTarget) : null;
  let tile, open;
  if (list) {
    const ribbon = rcptUnrecorded(comp, row);
    const rowCard = card || { name, mana_cost: "", type_line: "", img: null, img_small: null };
    open = cardRow(rowCard, { qty: q, compact: true,
      name: rcptListName(view, comp, row, comp.kind === "tokens" ? rowCard.name : name),
      meta: rcptMeta(comp, row, true), aside: rcptListDetails(comp, row),
      chips: [finishChip(row.values.finish), ribbon ? status("warn", ribbon) : null, ...chips].filter(Boolean),
      onclick: onclick || (() => {}) });
    if (label) open.setAttribute("aria-label", `${label}${rcptAttention(view, comp, row).length
      ? ". Needs attention: " + rcptAttention(view, comp, row).join(", ") : ""}`);
    const parts = comp.rows.filter((r) => r.orig === row.orig);
    const described = `rcpt-row-details-${row.key}${parts.length > 1 ? ` rcpt-row-part-${row.key}` : ""}`;
    open.setAttribute("aria-describedby", described);
    const tickCell = active ? el("label", { class: "rcpt-tick-cell" }, el("input", { type: "checkbox", class: "rcpt-tick",
      checked: row.ticked, "aria-label": `Check off ${plural(q, "copy", "copies")} of ${name}`, "aria-describedby": described,
      onchange: (e) => { rcptTick(view, comp, row, e.currentTarget.checked); e.currentTarget.checked = row.ticked; }
    })) : el("span", { class: "rcpt-tick-cell" });
    const pending = !row.ticked && parts.length > 1;
    tile = el("div", { class: "rcpt-row" + (row.ticked && active ? " is-ticked" : "")
      + (pending ? " is-pending-split" : "") }, tickCell, open);
  } else if (active) {
    ({ tile, open } = rcptPictureTile(view, comp, row, card, chips));
  } else {
    const common = { qty: q, meta: rcptMeta(comp, row, true), ticked: false,
      unrecorded: rcptUnrecorded(comp, row), chips, label, onclick };
    tile = comp.kind === "tokens"
      ? tokenTile({ front: row.values.front, back: row.values.back, img: card.img_small,
        back_img: card.faces ? card.faces[1].img_small : null }, { ...common, name: card.name })
      : cardTile(card, { ...common, finish: row.values.finish, name: frontName(row.values.name) });
    open = tile.querySelector(".card-tile-open");
  }
  if (card && card.img_small && open) viewerItem(open, card, comp.group, caption);
  row.open = open;
  tile.setAttribute("data-row", String(row.key));
  if (!readOnly) tile.hidden = !rcptShown(view, comp, row);
  return tile;
}
