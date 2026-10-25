/* Dated paper-printing hints and an explicit manual price-check offer.
 * Opening sources and copying a name never saves a queue or price observation. */
"use strict";

const reprintSheets = new Set();

function closeReprintSheets() {
  for (const sheet of [...reprintSheets].reverse()) sheet.close();
  reprintSheets.clear();
}

/** Only catalog-generated Scryfall links can leave the page. */
function reprintSource(url, text) {
  return typeof url === "string" && /^https:\/\/scryfall\.com\//.test(url)
    ? el("a", {href: url, target: "_blank", rel: "noopener noreferrer", text})
    : el("span", {text});
}

function reprintPrinting(printing, upcoming = false) {
  const set = [printing.set_name, printing.set ? `(${String(printing.set).toUpperCase()})` : null]
    .filter(Boolean).join(" ") || "Set not recorded";
  return el("li", {}, reprintSource(printing.source_url, set),
    el("span", {text: printing.released_at
      ? ` · ${upcoming ? "scheduled " : "release date "}${printing.released_at}` : " · release date not recorded"}));
}

/** Provenance stays next to the claim, even when there is no card picture. */
function reprintProvenance(info, folded = true) {
  const content = [
    el("p", {class: "sub", text: `Card data: ${info.data_date || "date not recorded"}. ` +
      `Dates compared as of ${info.as_of || "date not recorded"}.`}),
    info.coverage ? el("p", {class: "sub", text: info.coverage}) : null,
    ...(info.notes || []).map(note => el("p", {class: "sub", text: note})),
  ];
  return folded ? el("details", {class: "reprint-provenance"},
    el("summary", {text: "Source and coverage"}), content)
    : el("div", {class: "reprint-provenance"}, content);
}

/** A compact sibling of a card viewer button, shared by Shopping and missing-price rows. */
function reprintInfo(row) {
  const info = row.reprints;
  if (!info) return null;                         // Old projections still render normally.
  const profile = state.profile?.id, token = routeToken;
  const upcoming = info.upcoming || [], offered = Boolean(info.price_check?.offered);
  // A normal row without a detected printing needs no repeated empty panel. The
  // deliberate waiting state still gets an explicit absence or unavailable answer.
  if (!upcoming.length && !offered && row.state !== "waiting_for_reprint") return null;
  const node = el("div", {class: "reprint-info"});
  if (upcoming.length) add(node, [el("p", {text: "Upcoming paper printing"}),
    el("ul", {class: "reprint-printings"}, upcoming.map(printing => reprintPrinting(printing, true))),
    info.upcoming_more > 0 ? el("p", {class: "sub", text: `${info.upcoming_more} more scheduled printings in the source.`}) : null]);
  else node.append(el("p", {text: info.ready === false
    ? "Reprint data is unavailable in this card-data snapshot."
    : "No upcoming paper printing found in this card-data snapshot."}));
  if (offered) {
    node.append(el("p", {class: "sub", text: info.price_check.reason === "release_due"
      ? "A paper printing's release date has passed since the recorded price check."
      : info.price_check.reason === "data_unavailable"
        ? "Check current sources manually while reprint data is unavailable."
        : "The last price-check date is unknown or needs review."}),
    el("button", {type: "button", class: "btn btn-quiet reprint-check", text: "Check prices again",
      "aria-label": `Check prices again for ${row.name}`,
      onclick: event => {
        if (state.profile?.id === profile && routeToken === token)
          openReprintPriceCheck(row, event.currentTarget);
      }}));
  }
  node.append(reprintProvenance(info));
  return node;
}

/** An offer to inspect sources, not a price fetch or an automatic buying decision. */
function openReprintPriceCheck(row, trigger) {
  if (!trigger?.isConnected || !state.profile) return null;
  const profile = state.profile.id, token = routeToken, info = row.reprints;
  if (!info?.price_check?.offered) return null;
  const active = () => trigger.isConnected && state.profile?.id === profile && routeToken === token;
  const sheet = openSheet({title: `Check prices for ${row.name}`});
  reprintSheets.add(sheet);
  sheet.dialog.addEventListener("close", () => reprintSheets.delete(sheet));
  const alive = () => !sheet.closed && active();
  const released = info.released || [];
  add(sheet.body, [
    el("p", {text: info.price_check.reason === "release_due"
      ? "These paper printings have a release date after the recorded price check and on or before the comparison date."
      : info.price_check.reason === "data_unavailable"
        ? "Reprint data is unavailable. Check current sources and shop listings before deciding what to buy."
        : "A reliable last price-check date is not recorded. Check current shop listings before deciding what to buy."}),
    released.length ? el("ul", {class: "reprint-printings"}, released.map(printing => reprintPrinting(printing))) : null,
    info.released_more > 0 ? el("p", {class: "sub", text: `${info.released_more} more qualifying printings in the source.`}) : null,
    el("p", {class: "sub", text: `Recorded price check: ${info.price_check.checked || "date not recorded"}.`}),
    typeof shopReference === "function" ? shopReference(row) : null,
    row.printing ? el("p", {class: "sub", text: shopPrinting(row)}) : null,
    el("p", {text: "Check a shop's current price and stock for the card and finish you want. A scheduled release does not confirm that a shop has copies."}),
    el("p", {}, reprintSource(info.source_url, "View paper printings on Scryfall (USD prices)")),
    reprintProvenance(info, false),
  ]);
  const name = el("input", {type: "text", value: row.name, readonly: "", "aria-label": "Exact card name"});
  const message = el("p", {class: "sub", role: "status", "aria-live": "polite"});
  const copy = el("button", {type: "button", class: "btn", text: "Copy card name", onclick: async () => {
    if (!alive() || copy.disabled) return;
    copy.disabled = true;
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(row.name);
      if (alive()) message.textContent = "Card name copied.";
    } catch (error) {
      if (!alive()) return;
      message.textContent = "Select and copy the card name below.";
      name.focus();
      if (name.select) name.select();
    } finally { if (alive()) copy.disabled = false; }
  }});
  sheet.body.append(el("div", {class: "reprint-copy"}, copy, name, message),
    el("p", {class: "sub", text: "The purchase-queue category and recorded price stay as they are until you choose to change them."}));
  sheetActions(sheet, [{text: "Close", onclick: () => sheet.close()}]);
  return sheet;
}
