/* Receive delivery's shortcuts for a delivery that came as ordered (E6-S27): every part and card at once, a token
part's blank backs, and all of a part's checks, each behind one confirmation. They set the same working state the
by-hand ticks set (the "This arrived" box, each tile's tick, the sheet's "Back is blank" box, each check's tick),
so the preview and apply requests are identical; the server's rules are unchanged. */
"use strict";

/** A token row whose only open question is a blank reverse not yet marked single-sided. A row with an unresolved
 * pairing note (RCPT_UNVERIFIED) is never answered in bulk: its back is said in its own sheet. A recorded back
 * isn't open unless such a note says so (rcptBackOpen). */
function rcptBlankBackOpen(row) {
  const v = row.values;
  return !v.back && rcptBackOpen(row) && !RCPT_UNVERIFIED.test(v.notes || "");
}

/** Marks a token row's back blank, exactly as the sheet's "Back is blank (a single-sided card)" box does. */
function rcptMarkSingleSided(v) {
  const notes = rcptNotesWithout(v.notes, (p) => RCPT_UNVERIFIED.test(p) || RCPT_ARRIVAL_NOTE.test(p) || RCPT_LISTING_NOTE.test(p));
  Object.assign(v, { back: "", back_collector_number: "", back_details: "", notes: [notes, RCPT_SINGLE].filter(Boolean).join("; ") });
}

/** The delivery-level action, above the parts. */
function rcptEverythingBar(view) {
  view.everything = el("button", { type: "button", class: "btn rcpt-everything", text: "Everything arrived as ordered",
    onclick: () => rcptEverythingArrived(view) });
  view.everythingBar = el("div", { class: "actions rcpt-everything-bar" }, view.everything);
  return view.everythingBar;
}

/** A part's own shortcuts, beside its checks: All checks done, and (tokens) blank backs. */
function rcptPartActions(view, comp) {
  comp.checksDone = comp.c.checks.length > 1 ? el("button", { type: "button", class: "btn rcpt-checks-done", text: "All checks done",
    onclick: () => rcptAllChecksDone(view, comp) }) : null;
  comp.backsBlank = comp.kind === "tokens" ? el("button", { type: "button", class: "btn rcpt-backs-blank", "aria-haspopup": "dialog",
    onclick: () => rcptBacksBlank(view, comp) }) : null;
  comp.partActions = el("div", { class: "actions rcpt-part-actions" }, comp.checksDone, comp.backsBlank);
  return comp.partActions;
}

/** What "Everything arrived" would still do: the parts not chosen and the copies not ticked. */
function rcptEverythingLeft(view) {
  const parts = view.comps.filter((comp) => !comp.selected);
  const rows = view.comps.flatMap((comp) => comp.kind === "product" ? [] : comp.rows.filter((row) => !row.ticked).map((row) => ({ comp, row })));
  return { parts, rows };
}

/** Shows each shortcut only while it has something to do (Record arrival stays the bar's one primary). */
function rcptSyncBulk(view) {
  const editable = receiptEditable(view);
  if (view.everythingBar) {
    const left = rcptEverythingLeft(view);
    view.everythingBar.hidden = !editable || (!left.parts.length && !left.rows.length);
  }
  for (const comp of view.comps) {
    if (!comp.partActions) continue;
    const checks = comp.checks.filter((done) => !done).length;
    const backs = comp.kind === "tokens" ? comp.rows.filter((row) => row.ticked && rcptBlankBackOpen(row)).length : 0;
    if (comp.checksDone) {
      comp.checksDone.hidden = !comp.selected || !checks;
      comp.checksDone.textContent = `All ${plural(checks, "check")} done`;
    }
    if (comp.backsBlank) {
      comp.backsBlank.hidden = !comp.selected || !backs;
      comp.backsBlank.textContent = `Backs as recorded or blank (${backs})…`;
    }
    comp.partActions.hidden = !editable || [comp.checksDone, comp.backsBlank].every((button) => !button || button.hidden);
  }
}

/** Chooses every pending part and ticks every card and token card in it, after one confirmation. Checks, token
 * backs and a product's storage choice keep their own answers. */
async function rcptEverythingArrived(view) {
  if (!receiptEditable(view)) return;
  const left = rcptEverythingLeft(view);
  if (!left.parts.length && !left.rows.length) return;    // hidden then: nothing left to tick
  const copies = (kind) => view.comps.filter((comp) => comp.kind === kind)
    .reduce((n, comp) => n + comp.rows.reduce((sum, row) => sum + rcptQty(row), 0), 0);
  const what = [copies("cards") ? plural(copies("cards"), "card") : null, copies("tokens") ? plural(copies("tokens"), "token card") : null]
    .filter(Boolean).join(" and ");
  const products = view.comps.filter((comp) => comp.kind === "product" && !["yes", "no"].includes(comp.intact));
  const answer = await askReceiptChoice(view, "Everything arrived as ordered?", [
    `This marks ${view.comps.length > 1 ? `all ${view.comps.length} parts` : "the delivery"} as arrived${what ? ` and ticks all ${what}` : ""}.`,
    "Only do this once you've checked everything in your hands against its picture.",
    products.length ? `You'll still choose what to do with ${products.map((comp) => rcptTitle(comp.c, view.data)).join(" and ")}.` : null,
  ].filter(Boolean), [{ text: "Cancel", value: null }, { text: "Tick everything", kind: "primary", value: "yes" }]);
  if (answer !== "yes" || !receiptEditable(view)) return;
  for (const comp of view.comps) {
    comp.selected = true;
    if (comp.kind === "product") continue;
    for (const row of comp.rows) if (!row.ticked) { row.ticked = true; rcptTidyNotes(view, comp, row); }
  }
  rcptDrawBoard(view);
  rcptChanged(view);
  rcptFocusAfterBulk(view, null);
}

/** A shortcut hides itself once it's done, so the closing dialog would hand focus back to a hidden button: move
 * it to the next shortcut still showing (this part's first), else to Record arrival. */
function rcptFocusAfterBulk(view, comp) {
  const parts = comp ? [comp, ...view.comps.filter((c) => c !== comp)] : view.comps;
  const next = [...parts.flatMap((c) => [c.checksDone, c.backsBlank]), view.everything]
    .find((button) => button && !button.hidden && !button.parentNode?.hidden);
  if (next || view.primary) (next || view.primary).focus({ preventScroll: false });
}

/** Ticks every check of a part still open, after one confirmation naming them. */
async function rcptAllChecksDone(view, comp) {
  if (!receiptEditable(view) || !comp.selected || !view.comps.includes(comp)) return;
  const open = comp.c.checks.flatMap((text, i) => comp.checks[i] ? [] : [i]);
  if (!open.length) return;
  const answer = await askReceiptChoice(view, `All ${plural(open.length, "check")} done?`,
    ["Tick them only once you've done each one:", ...open.map((i) => `• ${comp.c.checks[i]}`)],
    [{ text: "Cancel", value: null }, { text: `Tick ${open.length === 1 ? "it" : `all ${open.length}`}`, kind: "primary", value: "yes" }]);
  if (answer !== "yes" || !receiptEditable(view) || !comp.selected || !view.comps.includes(comp)) return;
  for (const i of open) comp.checks[i] = true;
  rcptDrawGrid(view, comp);
  rcptChanged(view);
  rcptFocusAfterBulk(view, comp);
}

/** Answers a token part's open blank backs in one confirmation: each listed row has its own box, so
 * "single-sided verified" goes only on the rows left ticked. Rows with an unconfirmed pairing are named, not
 * listed: they still need their own sheet. */
async function rcptBacksBlank(view, comp) {
  if (!receiptEditable(view) || !comp.selected || comp.kind !== "tokens" || !view.comps.includes(comp)) return;
  const rows = comp.rows.filter((row) => row.ticked && rcptBlankBackOpen(row));
  if (!rows.length) return;
  const flagged = comp.rows.filter((row) => row.ticked && rcptBackOpen(row) && !rcptBlankBackOpen(row));
  const chosen = await rcptAskBacks(view, comp, rows, flagged);
  if (!chosen || !chosen.length || !receiptEditable(view) || !comp.selected || !view.comps.includes(comp)) return;
  for (const row of chosen) if (comp.rows.includes(row) && row.ticked && rcptBlankBackOpen(row)) rcptMarkSingleSided(row.values);
  rcptDrawGrid(view, comp);
  rcptChanged(view);
  rcptFocusAfterBulk(view, comp);
}

/** The blank-backs confirmation: resolves with the rows left ticked, or null. */
function rcptAskBacks(view, comp, rows, flagged) {
  return new Promise((resolve) => {
    const picked = new Set(rows);
    const sheet = openReceiptSheet(view, { title: "Are these backs blank?", onClose: (result) => resolve(result === "yes" ? [...picked] : null) });
    // A primary that can't act yet keeps its reason beside it, and its click goes to the first box (UI-KIT).
    const reason = el("p", { id: `${sheet.heading.id}-reason`, class: "sub rcpt-backs-reason", "aria-live": "polite" });
    const confirm = () => {
      const button = sheet.foot.querySelector("[data-action=yes]");
      if (!button) return;
      button.textContent = picked.size ? `Mark ${plural(picked.size, "back")} blank` : "Mark backs blank";
      button.setAttribute("aria-disabled", String(!picked.size));
      button.setAttribute("aria-describedby", reason.id);
      reason.textContent = picked.size ? "" : "Tick at least one card.";
    };
    add(sheet.body, [el("p", { text: "These token cards have no back recorded. Untick any that isn't a single-sided card, then say what its back is in its sheet." }),
      el("ul", { class: "rcpt-backs-list" }, rows.map((row) => el("li", {}, el("label", { class: "choice rcpt-backs-list-label" },
        el("input", { type: "checkbox", class: "rcpt-backs-list-box", checked: true, onchange: (e) => {
          if (e.currentTarget.checked) picked.add(row); else picked.delete(row);
          confirm();
        } }), el("span", { text: `${rcptRowName(comp, row)} × ${rcptQty(row)}` }))))),
      el("p", { class: "sub", text: "Backs already recorded need no answer here." }),
      flagged.length ? el("p", { class: "note note-warn", text: `Still to say one by one, as their pairing isn't confirmed: ${flagged.map((row) => rcptRowName(comp, row)).join(", ")}.` }) : null, reason]);
    sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
      { text: "", kind: "primary", value: "yes", onclick: () => {
        if (!picked.size) { sheet.body.querySelector(".rcpt-backs-list-box")?.focus(); return; }
        if (receiptEditable(view)) sheet.close("yes");
      } }]);
    confirm();
  });
}
