/* Receipt checking workflow: selection, preview, recording and profile-bound drafts. */
"use strict";

const receiptSheets = new Set();

function closeReceiptSheets() {
  for (const sheet of [...receiptSheets]) sheet.close();
  receiptSheets.clear();
}

function openReceiptSheet(view, options) {
  const sheet = openSheet({ ...options, onClose: result => {
    receiptSheets.delete(sheet);
    if (options.onClose) options.onClose(result);
  } });
  receiptSheets.add(sheet);
  return sheet;
}

function askReceiptChoice(view, title, paragraphs, choices) {
  return new Promise(resolve => {
    const sheet = openReceiptSheet(view, { title, onClose: result => resolve(result == null ? null : result) });
    sheet.body.append(...paragraphs.map(text => el("p", { text })));
    sheetActions(sheet, choices.map(choice => ({ ...choice, onclick: () => {
      if (receiptEditable(view)) sheet.close(choice.value);
    } })));
  });
}

function receiptEditable(view) { return receiptActive(view) && !view.busy && !view.done && !view.reloadRequired && mayDo("receipts"); }

/** Freeze what was reviewed; a pending response must never report later board edits as received. */
function rcptReceived(view) {
  return view.comps.filter(c => c.selected).map(comp => ({ ...comp,
    rows: comp.rows.filter(row => comp.kind === "product" || row.ticked)
      .map(row => ({ ...row, values: { ...row.values } })) }));
}

function rcptAssignments(answer, recorded = false) {
  if (!answer.assignments?.some(a => a.pending)) return null;
  return el("div", { class: "rcpt-partial" }, el("h3", { text: "Arriving now and still on the way" }),
    el("ul", {}, answer.assignments.map(a => el("li", { text:
      `${a.source}: ${plural(a.received_quantity, "card")} ${recorded ? "received" : "to record"} as ${a.received}.`
      + (a.pending ? ` ${plural(a.pending_quantity, "card")} ${a.pending_quantity === 1 ? "stays" : "stay"} pending as ${a.pending}.` : "") }))));
}

// ------------------------------------------------------------------ the action bar

function rcptToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function rcptBuildBar(view) {
  const today = view.data.today || rcptToday();
  view.dateInput = el("input", { type: "date", "aria-label": "Arrival date", max: today, min: view.data.ordered_on || null,
    hidden: true, onchange: (e) => {
      if (!receiptEditable(view)) return;
      view.date = { mode: "other", value: e.currentTarget.value }; view.dateSelect.value = "other"; rcptChanged(view);
    } });
  view.dateSelect = el("select", { "aria-label": "When it arrived", onchange: (e) => {
    if (!receiptEditable(view)) return;
    view.date.mode = e.currentTarget.value;
    view.dateInput.hidden = view.date.mode !== "other";
    if (view.date.mode === "today") view.date.value = today;
    else if (view.date.mode === "yesterday") view.date.value = rcptDayBefore(today);
    else { view.dateInput.value = view.date.value; view.dateInput.focus(); }
    rcptChanged(view);
  } }, el("option", { value: "today", text: "Today" }), el("option", { value: "yesterday", text: "Yesterday" }),
  el("option", { value: "other", text: "Another date…" }));
  view.progress = el("span", { class: "rcpt-progress" });
  view.stale = el("span", { class: "rcpt-stale" });
  view.blanks = el("button", { type: "button", class: "rcpt-blanks", hidden: true, onclick: () => {
    rcptSetFilter(view, "attention");
    const first = view.comps.find((c) => c.selected && c.kind === "cards");
    if (first && first.section) first.section.scrollIntoView({ block: "start", behavior: "smooth" });
  } });
  view.recordReason = el("span", { id: "rcpt-record-reason", class: "rcpt-record-reason", "aria-live": "polite" });
  view.primary = el("button", { type: "button", class: "btn btn-primary", text: "Record arrival",
    "aria-describedby": "rcpt-record-reason", onclick: () => rcptRecord(view) });
  // One row on a phone too: the progress over the date on the left, the main button on the right.
  view.bar = actionBar({ status: [el("span", { class: "rcpt-status-line" }, view.progress, view.stale), view.recordReason, view.blanks,
    el("label", { class: "rcpt-date" }, el("span", { text: "Arrived" }), view.dateSelect, view.dateInput)],
  actions: [view.primary] });
  view.bar.node.classList.add("rcpt-bar");
}

/** Copies and checks: {copies, ticked, checks, checksLeft, blanks, ready} over the selected cards and tokens.
 * blanks: selected copies still without a condition or language (they will be recorded blank). */
function rcptProgress(view) {
  let copies = 0, ticked = 0, checks = 0, checksLeft = 0, blanks = 0, empty = false;
  for (const comp of view.comps) {
    if (!comp.selected || comp.kind === "product") continue;
    if (!comp.rows.some(row => row.ticked)) empty = true;
    for (const row of comp.rows) {
      copies += rcptQty(row);
      if (row.ticked) { ticked += rcptQty(row); if (rcptBlank(comp, row)) blanks += rcptQty(row); }
    }
    checks += comp.checks.length; checksLeft += comp.checks.filter(t => !t).length;
  }
  return { copies, ticked, checks, checksLeft, blanks, ready: ticked > 0 && !empty && !checksLeft && !blanks };
}

/** The bar uses the same blockers as preview; blank details and unticked remainder never block recording. */
function rcptSync(view) {
  if (!view.bar) return;
  const p = rcptProgress(view);
  const any = view.comps.some((c) => c.selected);
  const undecided = view.comps.filter((c) => c.selected && c.kind === "product" && !["yes", "no"].includes(c.intact));
  add(clear(view.progress), [!any ? "Tick “This arrived” on what came." : p.copies
    ? `${p.ticked}/${p.copies} ✓${p.checksLeft ? ` · ${plural(p.checksLeft, "check")} left` : ""}`
    : undecided.length ? `Choose what to do with ${undecided.map((c) => (c.c.product && c.c.product.name) || c.c.id).join(" and ")}.`
      : "Ready to review."]);
  const blockers = rcptClientBlockers(view);
  view.primary.setAttribute("aria-disabled", String(blockers.length > 0));
  view.recordReason.textContent = view.reloadRequired ? "The delivery changed. Reload it before recording."
    : blockers.length ? `${blockers[0].text}${blockers.length > 1 ? ` (${blockers.length} things to check.)` : ""}`
      : "Review the exact changes before recording.";
  // Warn only about the copies being received; unticked copies remain pending.
  const showBlanks = any && p.blanks > 0 && p.ticked > 0 && !p.checksLeft;
  view.blanks.hidden = !showBlanks;
  view.blanks.textContent = showBlanks ? `${p.blanks} with no condition or language` : "";
  view.primary.disabled = !receiptEditable(view);
  const changed = view.preview && view.preview.key !== rcptRequestKey(view);
  view.stale.textContent = changed ? " · Changed since preview, preview again" : "";
  rcptSyncBulk(view);
  rcptSyncLayout(view, p);
}

/** A blocked primary stays reachable and takes focus to the first actionable blocker. */
function rcptRecord(view) {
  if (!receiptEditable(view)) return;
  const blockers = rcptClientBlockers(view);
  if (blockers.length) { rcptGoTo(view, blockers[0]); return; }
  return previewDelivery(view);
}

/** After any change: the bar, the draft, and the preview marked out of date. */
function rcptChanged(view) {
  if (!receiptEditable(view)) return;
  view.drafting = true;
  if (view.resume) clear(view.resume);
  rcptSaveDraft(view);
  rcptSync(view);
  for (const comp of view.comps) if (comp.grid && comp.kind !== "product") rcptToolbarCounts(view, comp);
}


// ------------------------------------------------------------------ preview and apply

/** What the preview sends: the arrival date and each selected component {id, verified, rows | intact}. */
function rcptRequest(view) {
  const components = view.comps.filter(comp => comp.selected).map(comp => {
    const selected = comp.rows.flatMap((row, i) => row.ticked ? [{ row: i + 1 }] : []);
    const chosen = { id: comp.c.id, verified: comp.kind !== "product" && selected.length > 0 && comp.checks.every(Boolean) };
    if (comp.kind === "product") { if (comp.intact) chosen.intact = comp.intact; }
    else {
      chosen.rows = comp.rows.map(row => Object.fromEntries(comp.c.fields.map(f => [f, String(row.values[f] == null ? "" : row.values[f])])));
      if (selected.length !== comp.rows.length) chosen.take = selected;
    }
    return chosen;
  });
  return { received_on: view.date.value, components };
}

function rcptRequestKey(view) { return JSON.stringify(rcptRequest(view)); }

/** What stops a receipt: an empty selected part, unchecked component checks, a selected token's back,
 * a product with no storage choice, or a bad date. Unticked rows remain pending. */
function rcptClientBlockers(view) {
  const out = [];
  if (!view.comps.some(comp => comp.selected)) {
    const first = view.comps[0]?.section;
    out.push({ text: 'Tick "This arrived" on what came.', target: first?.querySelector("input") || first });
  }
  for (const comp of view.comps) {
    if (!comp.selected) continue;
    if (comp.kind === "product") {
      if (!["yes", "no"].includes(comp.intact)) out.push({ text: `${rcptTitle(comp.c, view.data)}: choose whether to keep it as its own deck(s) or break it up.`,
        target: comp.choice });
      continue;
    }
    const selected = comp.rows.filter(row => row.ticked);
    if (!selected.length) out.push({ text: `${rcptTitle(comp.c, view.data)}: tick at least one card that arrived.`, comp, selection: true });
    // Once per part, not once per row or check (E6-S27): each links to its first open row or check.
    const backs = comp.kind === "tokens" ? selected.filter(row => rcptBackOpen(row)) : [];
    if (backs.length === 1) out.push({ text: `${rcptRowName(comp, backs[0])}: say what its back is, or that it's blank.`, comp, row: backs[0] });
    else if (backs.length) out.push({ text: `${rcptTitle(comp.c, view.data)}: say what ${backs.length} backs are, or that they're blank `
      + `(${backs.map(row => rcptRowName(comp, row)).join(", ")}).`, comp, row: backs[0] });
    const open = comp.c.checks.flatMap((text, i) => comp.checks[i] ? [] : [i]);
    if (open.length) out.push({ text: open.length === 1 ? `Check not ticked: ${comp.c.checks[open[0]]}`
      : `${rcptTitle(comp.c, view.data)}: ${open.length} checks not ticked: ${open.map(i => comp.c.checks[i]).join("; ")}`,
    target: comp.checkBoxes ? comp.checkBoxes[open[0]] : null });
  }
  const today = view.data.today || rcptToday();
  if (!rcptValidDay(view.date.value)) out.push({ text: "Choose a valid arrival date.", date: true });
  else if (view.date.value > today) out.push({ text: "The arrival date can't be in the future.", date: true });
  else if (view.data.ordered_on && view.date.value < view.data.ordered_on) {
    out.push({ text: `It can't have arrived before it was ordered (${rcptDate(view.data.ordered_on)}).`, date: true });
  }
  return out;
}

/** Match the native date input's real calendar days without normalising an invalid saved value. */
function rcptValidDay(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) return false;
  const day = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value;
}

/** A row's name for a list of blockers: a token with its printing ("Ooze (TM11 5)"), so twins can be told apart. */
function rcptRowName(comp, row) {
  const v = row.values;
  if (comp.kind !== "tokens") return v.name;
  const where = v.set ? ` (${v.set.toUpperCase()} ${v.front_collector_number})`.replace(" )", ")") : "";
  return `${v.back ? `${v.front} // ${v.back}` : v.front}${where}`;
}

/** Takes the person to what a blocker names: the tile (its sheet), a check, the product's choice or the date. */
function rcptGoTo(view, item) {
  if (!receiptEditable(view)) return;
  if (item.selection) {
    if (view.filter !== "all") rcptSetFilter(view, "all");
    const target = item.comp.rows[0]?.tile?.querySelector(".rcpt-tick") || item.comp.section;
    if (target) {
      if (target === item.comp.section) target.setAttribute("tabindex", "-1");
      target.scrollIntoView({ block: "center", behavior: "smooth" }); target.focus();
    }
    return;
  }
  if (item.comp && item.row) {
    if (view.filter !== "all") rcptSetFilter(view, "all");
    const tile = item.row.tile;
    if (tile) tile.scrollIntoView({ block: "center", behavior: "smooth" });
    rcptOpenSheet(view, item.comp, item.row);
    return;
  }
  if (item.date) {
    // "Another date…", showing the date being sent, so the select, the draft and the request agree.
    view.date = { mode: "other", value: view.date.value };
    view.dateSelect.value = "other";
    view.dateInput.value = view.date.value || "";
    view.dateInput.hidden = false;
    rcptChanged(view);
    view.dateInput.scrollIntoView({ block: "center", behavior: "smooth" });
    view.dateInput.focus();
    return;
  }
  if (item.target) {
    const target = item.target.getAttribute("role") === "group"
      ? [...item.target.querySelectorAll("button")].find(button => !button.disabled) || item.target : item.target;
    // A section isn't focusable by itself: tabindex -1 lets the focus land on it.
    if (/^(section|div)$/i.test(target.tagName || target.tag || "") && !target.getAttribute("tabindex")) {
      target.setAttribute("tabindex", "-1");
    }
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.focus();
  }
}

/** The blockers in a sheet, each a link to what it names. */
function rcptBlockerSheet(view, items, title = "Not ready to record yet") {
  const shown = items.slice(0, 12);
  const sheet = openReceiptSheet(view, { title });
  add(sheet.body, [el("ul", { class: "rcpt-blockers" }, shown.map((item) => el("li", {},
    item.comp || item.target || item.date ? el("button", { type: "button", class: "rcpt-blocker", text: item.text,
      onclick: () => { sheet.close(); rcptGoTo(view, item); } }) : item.text))),
  items.length > shown.length ? el("p", { class: "sub", text: `And ${items.length - shown.length} more.` }) : null]);
  sheetActions(sheet, [{ text: "Back to checking", kind: "primary", onclick: () => sheet.close() }]);
  return sheet;
}

async function previewDelivery(view) {
  if (!receiptEditable(view)) return;
  if (!view.comps.some((comp) => comp.selected)) {
    clear(view.message).append(el("p", { class: "form-error", text: "Tick “This arrived” on what came." }));
    return;
  }
  const blockers = rcptClientBlockers(view);
  if (blockers.length) { rcptBlockerSheet(view, blockers); return; }
  const request = rcptRequest(view), key = JSON.stringify(request);
  const received = rcptReceived(view);
  const seq = ++view.seq;
  view.preview = null; clear(view.message); receiptBusy(view, true);
  busy(view.primary, "Preparing…");
  try {
    const answer = await apiWrite("/api/receipt/preview", { profile: view.profile, order: view.data.order,
      fingerprint: view.data.fingerprint, ...request });
    if (!receiptActive(view) || seq !== view.seq || key !== rcptRequestKey(view)) return;
    if (!answer.ready) {
      rcptBlockerSheet(view, (answer.blockers || []).map((text) => rcptServerBlocker(view, text)));
      return;
    }
    view.preview = { token: answer.preview, key, answer, received };
    rcptPreviewSheet(view, answer);
  } catch (error) {
    if (receiptActive(view) && seq === view.seq) {
      // A changed delivery (409) needs a reload; anything else may work on a second try, as Record arrival offers.
      const changed = error.status === 409;
      clear(view.message).append(rcptError("The preview couldn't be prepared", error),
        el("button", { type: "button", class: "btn", text: changed ? "Reload the delivery" : "Try again", onclick: () => {
          if (!receiptActive(view) || view.busy) return;
          if (changed) route(); else previewDelivery(view);
        } }));
    }
  } finally {
    if (receiptActive(view)) { unbusy(view.primary); receiptBusy(view, false); rcptSync(view); }
  }
}

/** A blocker from the server ("cards: inspect it, ...") in plain words, linked to its component's section. */
function rcptServerBlocker(view, text) {
  const [id, ...rest] = String(text).split(": ");
  const comp = view.comps.find((c) => c.c.id === id);
  if (!comp) return { text };
  return { text: `${rcptTitle(comp.c, view.data)}: ${rest.join(": ")}`, target: comp.section };
}

/** The outcome in plain words, the decks whose tables update, then Record arrival. */
function rcptPreviewSheet(view, answer) {
  const sheet = openReceiptSheet(view, { title: "Record this arrival?", wide: true, onClose: () => { if (view.previewSheet === sheet) view.previewSheet = null; } });
  view.previewSheet = sheet;
  const p = rcptProgress(view);
  add(sheet.body, [el("p", { class: "rcpt-outcome", text: `Arrived ${rcptDate(answer.received_on)}.` }),
    rcptOutcome(answer.totals), rcptAssignments(answer),
    p.blanks ? el("div", { class: "box box-warn rcpt-blank-warn" }, el("p", { class: "box-head",
      text: `${plural(p.blanks, "card")} ${p.blanks === 1 ? "goes" : "go"} in with no condition or language recorded: they stay blank.` })) : null,
    receiptPlannedTables(answer.tables),
    el("details", { class: "rcpt-changes" }, el("summary", { text: `What this changes (${(answer.changes || []).length})` }),
      el("ul", {}, (answer.changes || []).map((text) => el("li", { text })))),
    el("p", { class: "sub", text: rcptFootnote(view, answer) })]);
  view.applyButton = null;
  sheetActions(sheet, [
    { text: "Record arrival", kind: "primary", value: "apply", onclick: () => applyDelivery(view) },
    { text: "Back to checking", onclick: () => sheet.close() }]);
  view.applyButton = sheet.foot.querySelector("[data-action=apply]");
  view.sheetError = el("div", { role: "alert" });
  sheet.body.append(view.sheetError);
}

/** The preview's last line, from what it will do: "Recording it adds these to your collection, marks them
 * arrived and updates those decks' tables, all in one change." */
function rcptFootnote(view, answer) {
  const kinds = new Set(view.comps.filter((c) => c.selected).map((c) => c.kind));
  const where = [kinds.has("cards") || kinds.has("product") ? "your collection" : null, kinds.has("tokens") ? "your token cards" : null]
    .filter(Boolean).join(" and ");
  const tables = answer.tables && answer.tables.written && answer.tables.written.length ? " and updates those decks' tables" : "";
  return `Recording it adds these to ${where || "the inventory"}, marks them arrived${tables}, all in one change.`;
}

/** The totals in plain words: "15 cards go into your collection (13 new to it, 2 added to ones you had)". */
function rcptOutcome(totals) {
  return (totals || []).map(([kind, count]) => {
    const tokens = kind === "physical tokens";
    const noun = tokens ? plural(count.cards, "token card") : plural(count.cards, "card");
    const where = tokens ? "your token cards" : "your collection";
    const parts = [count.added_rows ? `${count.added_rows} new to it` : null,
      count.bumped_rows ? `${count.bumped_rows} added to ones you had` : null].filter(Boolean).join(", ");
    return el("p", { class: "rcpt-outcome", text: `${noun} ${count.cards === 1 ? "goes" : "go"} into ${where}${parts ? ` (${parts})` : ""}.`
      + (count.skipped_basics ? ` ${plural(count.skipped_basics, "plain basic land")} ${count.skipped_basics === 1 ? "isn't" : "aren't"} tracked.` : "") });
  });
}

async function applyDelivery(view) {
  if (!receiptEditable(view) || !view.preview) return;
  if (view.preview.key !== rcptRequestKey(view)) {
    view.preview = null; rcptSync(view);
    if (view.previewSheet) view.previewSheet.close();
    clear(view.message).append(el("p", { class: "form-error", text: "Changed since preview, preview again." }));
    return;
  }
  const preview = view.preview.token, received = view.preview.received; receiptBusy(view, true);
  if (view.applyButton) busy(view.applyButton, "Recording…");
  try {
    const answer = await apiWrite("/api/receipt/apply", { profile: view.profile, preview });
    state.library = null;
    rcptDropDraft(view);
    if (!receiptActive(view)) return;
    view.received = received;
    view.preview = null; view.done = true;
    if (view.previewSheet) view.previewSheet.close();
    rcptSuccess(view, answer);
  } catch (error) {
    if (receiptActive(view)) {
      const retry = error.status === 503;
      if (!retry) view.preview = null;
      view.reloadRequired = error.status === 409;
      const where = view.previewSheet && !view.previewSheet.closed ? clear(view.sheetError) : clear(view.message);
      where.append(rcptError("The arrival couldn't be recorded", error),
        el("button", { type: "button", class: "btn", text: "Reload the delivery", onclick: () => { if (receiptActive(view)) route(); } }));
      if (view.previewSheet && !view.previewSheet.closed) sheetActions(view.previewSheet, [
        { text: retry ? "Retry recording arrival" : view.reloadRequired ? "Reload the delivery" : "Preview again", kind: "primary", value: "apply", onclick: () => {
          if (!receiptActive(view) || view.busy) return;
          if (retry) { applyDelivery(view); return; }
          view.previewSheet.close();
          if (view.reloadRequired) route(); else previewDelivery(view);
        } }, { text: "Back to checking", onclick: () => view.previewSheet.close() }]);
      view.applyButton = view.previewSheet?.foot.querySelector("[data-action=apply]");
    }
  } finally {
    if (receiptActive(view)) { if (view.applyButton && view.applyButton.isConnected) unbusy(view.applyButton); receiptBusy(view, false); rcptSync(view); }
  }
}

/** An error beside the button that caused it (the page keeps its one main action). */
function rcptError(title, error) {
  return el("div", { class: "box box-crit", role: "alert" }, el("h2", { class: "box-head", text: title }),
    el("p", { text: error && error.message ? error.message : String(error) }));
}

function receiptActive(view) {
  return view.token === routeToken && view.root.isConnected && state.profile?.id === view.profile;
}

function receiptBusy(view, on) {
  view.busy = on;
  view.root.setAttribute("aria-busy", String(on));
  if (on) {
    view.frozenControls = ["input", "select", "textarea", "button"].flatMap(tag => [...view.root.querySelectorAll(tag)]).map(control => [control, control.disabled]);
    for (const [control] of view.frozenControls) control.disabled = true;
  } else {
    for (const [control, disabled] of view.frozenControls || []) if (control.isConnected) control.disabled = disabled;
    view.frozenControls = null;
  }
  if (view.primary) view.primary.disabled = on || view.reloadRequired;
}


// ------------------------------------------------------------------ after it's recorded

/** The page after a receipt: what was recorded, where each card goes (the decks counting on it, by their
 * sleeves; the rest to storage), what became of the deck tables, and the ways on. */
function rcptSuccess(view, answer) {
  const received = view.received || rcptReceived(view);
  const tables = receiptTables(answer.tables);
  const written = (answer.tables && answer.tables.written) || [];
  add(clear(view.root), [pageHead({ crumb: ["#/shopping", routeFor("shopping").label], title: "Arrival recorded",
    description: `${view.data.seller || view.data.order} · arrived ${rcptDate(view.date.value)}` }),
  el("div", { class: "box box-good rcpt-recorded", role: "status" },
    el("h2", { text: rcptAddedWords(answer.totals) }), rcptOutcome(answer.totals)),
  rcptWhereTheyGo(view, received), rcptAssignments(answer, true),
  answer.remaining?.length ? el("p", { text: `Still on the way: ${answer.remaining.map(part => `${part.id} (${part.quantity})`).join(", ")}. Unticked cards are still pending.` }) : null,
  tables,
  el("div", { class: "actions rcpt-after" },
    answer.remaining?.length ? el("button", { type: "button", class: "btn btn-primary", text: "Continue pending delivery", onclick: () => {
      if (receiptActive(view)) route();
    } }) : null,
    el("a", { class: answer.remaining?.length ? "btn" : "btn btn-primary", href: "#/shopping", text: "Back to Shopping" }),
    written.slice(0, 6).map((d) => el("a", { class: "btn", href: deckHref(d.id), text: d.title })))]);
  const head = view.root.querySelector("h1");
  if (head && head.focus) { head.setAttribute("tabindex", "-1"); head.focus(); }
}

/** The success box's heading: what changed ("15 cards added.", "15 cards and 7 token cards added."). */
function rcptAddedWords(totals) {
  const parts = (totals || []).filter((item) => item[1] && item[1].cards)
    .map((item) => plural(item[1].cards, item[0] === "physical tokens" ? "token card" : "card"));
  return parts.length ? `${parts.join(" and ")} added.` : "The delivery is marked arrived.";
}

/** "Where these go": the decks that count on these cards (by deck, with its sleeves when you see them), then the
 * rest to storage; token cards to the token box; a product as its own deck(s) or into storage. */
function rcptWhereTheyGo(view, received) {
  const decks = new Map(), storage = [], unknown = [], basics = [], parts = [];
  const kits = view.data.kits || {};
  for (const item of rcptDestinationAdvice(view, received)) {
    if (item.kind === "tokens") {
      parts.push(el("div", { class: "panel rcpt-where" }, el("h3", { text: "Token cards" }),
        el("p", {}, `${plural(item.quantity, "token card")} go with your tokens. `,
          el("a", { href: "#/tokens", text: "See them on Tokens" }))));
      continue;
    }
    if (item.kind === "product") {
      const comp = item.comp;
      parts.push(el("div", { class: "panel rcpt-where" }, el("h3", { text: item.title }),
        el("p", { text: comp.intact === "yes" ? "Kept as its own deck(s): choose its sleeves and deck box on its deck page."
          : comp.intact === "no" ? "Broken up: its cards go into the storage box."
            : "Its storage choice is not known from the recorded selection." })));
      continue;
    }
    if (item.kind === "unknown") {
      (item.why === "basic" ? basics : unknown).push([item.quantity, item.name]);
      continue;
    }
    if (item.kind === "storage") { storage.push([item.quantity, item.name]); continue; }
    if (!decks.has(item.deck.id)) decks.set(item.deck.id, { deck: item.deck, cards: [] });
    decks.get(item.deck.id).cards.push([item.quantity, item.name]);
  }
  const rank = (d) => (d.status === "built" ? 0 : d.status === "building" ? 1 : 2);
  const groups = [...decks.values()].sort((a, b) => rank(a.deck) - rank(b.deck) || a.deck.title.localeCompare(b.deck.title));
  const lines = (cards) => el("ul", { class: "rcpt-where-cards" }, cards.map(([n, name]) => el("li", { text: `${n} × ${name}` })));
  const out = [];
  if (groups.length || storage.length || unknown.length || basics.length) out.push(el("h2", { class: "rcpt-where-head", text: "Where these go" }));
  if (groups.length) {
    out.push(el("div", { class: "rcpt-where-grid" }, groups.map(({ deck, cards }) => el("div", { class: "panel rcpt-where" },
      el("h3", {}, rcptDeckLink(deck)),
      kits[deck.id] && kits[deck.id].sleeves ? el("p", { class: "sub", text: `Sleeve them in ${kits[deck.id].sleeves}.` })
        : deck.status === "built" ? null : el("p", { class: "sub", text: `${STATUS_WORDS[deck.status] || "Idea"}: keep them with its cards.` }),
      lines(cards)))));
  }
  if (storage.length) {
    out.push(el("div", { class: "panel rcpt-where" }, el("h3", { text: "To storage" }),
      el("p", { class: "sub", text: "No deck is waiting for these: they go unsleeved into the storage box." }), lines(storage)));
  }
  if (unknown.length) out.push(el("div", { class: "panel rcpt-where rcpt-where-unknown" },
    el("h3", { text: "Destination not known" }),
    el("p", { class: "sub", text: "Deck destinations could not be worked out from the delivery data. Check where these copies belong." }), lines(unknown)));
  if (basics.length) out.push(el("div", { class: "panel rcpt-where rcpt-where-basics" },
    el("h3", { text: "Basic lands" }),
    el("p", { class: "sub", text: "Basic-land deck destinations are not tracked." }), lines(basics)));
  return [...out, ...parts];
}

const TABLE_SKIPS = { changed: "the receipt changes it itself", kit: "its Sleeves or Deck box would change" };
const tableSkips = (items) => items.map(item => `${item.title} (${TABLE_SKIPS[item.why] || item.why})`).join(", ");

/** The decks whose tables the previewed receipt refreshes in the same change, as links. */
function receiptPlannedTables(tables) {
  if (!tables) return null;
  const parts = [tables.written.length
    ? el("p", { class: "rcpt-tables" }, "These decks' tables update: ", el("span", { class: "chips" }, tables.written.map((d) =>
      el("a", { class: "chip chip-plain", href: deckHref(d.id), text: d.title }))))
    : el("p", { text: "No deck's table needs updating." })];
  if (tables.skipped.length) parts.push(tablesLaterNote(`Not updated: ${tableSkips(tables.skipped)}.`));
  if (tables.error) parts.push(el("p", { class: "note note-warn", text: `The deck tables won't be updated: ${tables.error}` }));
  return el("div", { class: "receipt-tables" }, parts);
}

/** What became of the deck tables in the receipt's change: updated, skipped, or left for the Decks page. */
function receiptTables(tables) {
  if (!tables) return null;
  if (tables.error) return tablesLaterNote(`The deck tables weren't updated: ${tables.error}`);
  const parts = [el("p", { text: tables.written.length ? `Deck tables updated: ${tables.written.map((d) => d.title).join(", ")}.`
    : "No deck's table needed updating." })];
  if (tables.skipped.length) parts.push(tablesLaterNote(`Not updated: ${tableSkips(tables.skipped)}.`));
  return el("div", { class: "receipt-tables" }, parts);
}


// ------------------------------------------------------------------ the draft

/** localStorage's key for this order's check at this inventory revision (core.js's local adds the prefix). */
function rcptDraftKey(view) { return `receipt:${view.profile}:${view.data.order}:${view.data.fingerprint}`; }

function rcptSaveDraft(view) {
  if (!view.drafting || view.done) return;
  const draft = { v: 1, date: view.date, filter: view.filter, comps: {} };
  for (const comp of view.comps) {
    draft.comps[comp.c.id] = { selected: comp.selected, intact: comp.intact, checks: comp.checks,
      rows: comp.kind === "product" ? [] : comp.rows.map((r) => ({ orig: r.orig, values: r.values, ticked: r.ticked, before: r.before,
        pic: r.pic || null })) };
  }
  local.set(rcptDraftKey(view), JSON.stringify(draft));
}

function rcptDropDraft(view) { local.remove(rcptDraftKey(view)); }

/** This order's saved check, if it still fits the delivery as it is now; null otherwise. Drafts of the same order
 * at an older inventory revision are dropped. */
function rcptLoadDraft(view) {
  // This profile's drafts of the order at other revisions, and drafts from before the key named the profile.
  const prefixes = [`${STORE}receipt:${view.profile}:${view.data.order}:`, `${STORE}receipt:${view.data.order}:`];
  try {
    const store = window.localStorage;
    for (let i = store.length - 1; i >= 0; i -= 1) {
      const key = store.key(i);
      if (key && prefixes.some((p) => key.startsWith(p)) && key !== STORE + rcptDraftKey(view)) store.removeItem(key);
    }
  } catch (e) { /* storage blocked: nothing to tidy */ }
  let draft;
  try { draft = JSON.parse(local.get(rcptDraftKey(view)) || "null"); } catch (e) { return null; }
  if (!draft || draft.v !== 1 || typeof draft.comps !== "object") return null;
  for (const comp of view.comps) {
    const saved = draft.comps[comp.c.id];
    if (!saved || !Array.isArray(saved.rows) || !Array.isArray(saved.checks) || saved.checks.length !== comp.checks.length) return null;
    if (comp.kind === "product") continue;
    const totals = new Map();
    for (const r of saved.rows) {
      if (!r || !Number.isInteger(r.orig) || !comp.c.rows[r.orig] || typeof r.values !== "object"
        || comp.c.fields.some((f) => typeof r.values[f] !== "string") || r.values.name !== comp.c.rows[r.orig].name) return null;
      totals.set(r.orig, (totals.get(r.orig) || 0) + (parseInt(r.values.quantity, 10) || 0));
    }
    if (comp.c.rows.some((row, i) => totals.get(i) !== (parseInt(row.quantity, 10) || 0))) return null;
  }
  return draft;
}

/** A card's picture as the draft kept it, when it still fits: only Deck Lab's /img/ addresses, for a row whose
 * printing was changed here. A changed printing without one is looked up again (its picture, set name and
 * finishes), and shows no picture meanwhile rather than the ordered printing's. */
function rcptRestorePicture(view, comp, row, saved) {
  const was = comp.c.rows[row.orig] || {}, v = row.values;
  if (v.set === was.set && v.collector_number === was.collector_number) return;
  const url = (u) => u == null || (typeof u === "string" && u.startsWith("/img/"));
  const card = saved && typeof saved === "object" && saved.card && typeof saved.card === "object" ? saved.card : null;
  if (card && card.name === v.name && url(card.img) && url(card.img_small)
    && (card.faces == null || (Array.isArray(card.faces) && card.faces.every((f) => f && url(f.img) && url(f.img_small))))) {
    row.pic = { card, exact: Boolean(saved.exact), why: typeof saved.why === "string" ? saved.why : null,
      set_name: typeof saved.set_name === "string" ? saved.set_name : null,
      finishes: Array.isArray(saved.finishes) ? saved.finishes.filter((f) => typeof f === "string") : null };
    return;
  }
  const base = (rcptPicture(comp, { ...row, pic: null }) || {}).card || { name: v.name, mana_cost: "", type_line: "", oracle_text: "" };
  row.pic = { card: { ...base, img: null, img_small: null, faces: base.faces ? base.faces.map((f) => ({ ...f, img: null, img_small: null })) : base.faces },
    exact: false, why: "no picture", set_name: null, finishes: null };
  rcptLookupPrinting(view, v.name, v.set, v.collector_number).then((found) => {
    if (!found.length || row.values.set !== v.set || row.values.collector_number !== v.collector_number || !receiptActive(view)) return;
    row.pic = { card: rcptWithPicture(base, found[0]), exact: true, why: null,
      set_name: found[0].set_name || v.set.toUpperCase(), finishes: found.map((p) => p.finish) };
    if (row.tile) rcptRefreshTile(view, comp, row);
    if (view.sheet && view.sheet.row === row) rcptFillSheet(view);
  });
}

/** "Resume your check (9 of 15 ticked)" when there's a saved check worth resuming. */
function rcptOfferDraft(view) {
  const draft = rcptLoadDraft(view);
  if (!draft) return;
  let ticked = 0, copies = 0, edits = false;
  for (const comp of view.comps) {
    for (const r of draft.comps[comp.c.id].rows) {
      const q = parseInt(r.values.quantity, 10) || 0;
      copies += q; if (r.ticked) ticked += q;
      if (JSON.stringify(r.values) !== JSON.stringify(comp.c.rows[r.orig])) edits = true;
    }
  }
  if (!ticked && !edits) return;
  add(view.resume, [el("div", { class: "box box-info rcpt-resume-box" },
    el("p", { text: `You were part way through checking this delivery (${ticked} of ${copies} ticked).` }),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn", text: "Resume your check", onclick: () => rcptApplyDraft(view, draft) }),
      el("button", { type: "button", class: "btn btn-quiet", text: "Start again", onclick: () => {
        if (!receiptEditable(view)) return;
        rcptDropDraft(view); clear(view.resume);
      } })))]);
}

function rcptApplyDraft(view, draft) {
  if (!receiptEditable(view)) return;
  view.filter = RCPT_FILTERS.includes(draft.filter) ? draft.filter : "all";
  for (const comp of view.comps) {
    const saved = draft.comps[comp.c.id];
    comp.selected = view.comps.length === 1 ? true : Boolean(saved.selected);
    comp.intact = saved.intact === "yes" || saved.intact === "no" ? saved.intact : "";
    comp.checks = saved.checks.map(Boolean);
    if (comp.kind !== "product") {
      comp.rows = saved.rows.map((r) => ({ key: ++rcptKeys, orig: r.orig, values: { ...r.values }, ticked: Boolean(r.ticked),
        before: typeof r.before === "string" ? r.before : null, pic: null }));
      if (comp.kind === "cards") comp.rows.forEach((row, i) => rcptRestorePicture(view, comp, row, saved.rows[i].pic));
    }
  }
  if (draft.date && /^\d{4}-\d{2}-\d{2}$/.test(draft.date.value || "") && ["today", "yesterday", "other"].includes(draft.date.mode)) {
    const today = view.data.today || rcptToday();
    view.date = draft.date.mode === "today" ? { mode: "today", value: today }
      : draft.date.mode === "yesterday" ? { mode: "yesterday", value: rcptDayBefore(today) } : { ...draft.date };
    view.dateSelect.value = view.date.mode;
    view.dateInput.hidden = view.date.mode !== "other";
    view.dateInput.value = view.date.value;
  }
  clear(view.resume);
  rcptDrawBoard(view);
  rcptChanged(view);
}
