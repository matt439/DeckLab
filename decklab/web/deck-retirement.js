/* Retire an unbuilt saved deck, retaining its history and games; restore its last saved text from History. */
"use strict";

const deckRetirementSheets = new Set();

function closeDeckRetirementSheets() {
  for (const sheet of [...deckRetirementSheets]) sheet.close();
}

/** History's revision sheets share this cleanup: none may remain visible after switching people. */
function openDeckRetirementSheet(options) {
  const sheet = openSheet({ ...options, onClose: result => {
    deckRetirementSheets.delete(sheet);
    if (options.onClose) options.onClose(result);
  } });
  deckRetirementSheets.add(sheet);
  return sheet;
}

function deckHistoryHref(id, version = "target") {
  return `#/history?id=${encodeURIComponent(id)}&v=${version === "owned" ? "owned" : "target"}`;
}

function canRetireDeck(data) {
  const s = data?.summary;
  return !!s && !s.read_only && !s.error && s.status !== "built" && canEditDeck(s)
    && /^(?:[^/]+\/)?(?:casual|commander)\/[^/]+$/.test(s.id);
}

function retirementPageHere(ctx) { return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.hash === location.hash; }
function retirementHere(ctx) { return retirementPageHere(ctx) && !ctx.sheet.closed && ctx.sheet.dialog.isConnected; }

function retirementContext(kind, id, title) {
  const existing = [...deckRetirementSheets].map(s => s.retirementContext)
    .find(ctx => ctx && ctx.kind === kind && ctx.id === id && retirementHere(ctx));
  if (existing) return existing;
  const sheet = openDeckRetirementSheet({ title: kind === "restore" ? `Restore ${title}?` : `Retire ${title}?` });
  const ctx = { kind, id, title, sheet, token: routeToken, profile: state.profile?.id, hash: location.hash, sending: false, done: false,
    generation: 0, reasonText: "", conflict: false };
  sheet.retirementContext = ctx;
  return ctx;
}

function openRetireDeck(data) {
  if (!canRetireDeck(data) || !state.profile) return null;
  const ctx = retirementContext("retire", data.summary.id, data.summary.title);
  if (ctx.data) return ctx;
  ctx.data = data; loadRetireDeck(ctx);
  return ctx;
}

async function loadRetireDeck(ctx) {
  if (!retirementHere(ctx) || ctx.sending) return;
  const generation = ++ctx.generation; ctx.valid = false;
  clear(ctx.sheet.body).append(loadingBox("Checking the deck before retiring it…"));
  sheetActions(ctx.sheet, [{ text: "Cancel", onclick: () => ctx.sheet.close() }]);
  try {
    const meta = await api(`/api/deck/retire?id=${encodeURIComponent(ctx.id)}`);
    if (!retirementHere(ctx) || generation !== ctx.generation) return;
    ctx.meta = meta; ctx.conflict = false;
    if (meta.id !== ctx.id || !meta.may_retire || meta.status === "built" || !Number.isInteger(meta.revision)
      || meta.revision < 1 || !/^[0-9a-f]{64}$/.test(meta.sha256 || "") || !canRetireDeck(ctx.data)) {
      clear(ctx.sheet.body).append(el("p", { text: meta.why_not || "This deck cannot be retired. Reload it and check its status first." }));
      return;
    }
    ctx.valid = true; drawRetireDeck(ctx);
  } catch (error) {
    if (!retirementHere(ctx) || generation !== ctx.generation) return;
    clear(ctx.sheet.body).append(el("p", { class: "form-error", role: "alert", text: error.message || String(error) }));
    if ([404, 409].includes(error.status)) ctx.sheet.body.append(el("p", {}, "Inspect the retained history if the deck was retired while this page was open. ",
      el("a", { href: deckHistoryHref(ctx.id), text: "View retained history" })));
    sheetActions(ctx.sheet, [{ text: "Try again", onclick: () => loadRetireDeck(ctx) },
      { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  }
}

function drawRetireDeck(ctx) {
  const sheet = ctx.sheet;
  sheet.heading.textContent = `Retire ${ctx.meta.title}?`;
  ctx.reason = el("input", { type: "text", maxlength: 1000, autocomplete: "off", "aria-label": "Reason for retirement",
    oninput: () => { if (!retirementHere(ctx) || ctx.sending) return; ctx.reasonText = ctx.reason.value; sync(); } });
  ctx.reason.value = ctx.reasonText;
  ctx.confirm = el("input", { type: "checkbox", onchange: () => { if (retirementHere(ctx) && !ctx.sending) sync(); } });
  ctx.error = el("p", { class: "form-error", role: "alert" });
  clear(sheet.body).append(el("p", { text: "Retiring removes this deck from the library. Its saved history and matchup results are kept. You can restore its last saved text from History." }),
    el("label", { class: "field" }, el("span", { text: "Reason (required)" }), ctx.reason),
    el("label", { class: "choice" }, ctx.confirm, el("span", { text: "I understand this removes the deck from the library and keeps its history." })), ctx.error);
  sheetActions(sheet, [{ text: "Retire deck", kind: "danger", value: "retire", onclick: () => sendRetireDeck(ctx) },
    { text: "Cancel", onclick: () => sheet.close() }]);
  ctx.button = sheet.foot.querySelector("[data-action=retire]");
  function sync() { ctx.button.disabled = ctx.sending || !ctx.confirm.checked || !ctx.reason.value.trim(); }
  sync();
}

async function sendRetireDeck(ctx) {
  if (!retirementHere(ctx) || ctx.sending || ctx.done || ctx.conflict || !ctx.valid || !ctx.meta?.may_retire || !canRetireDeck(ctx.data)) return;
  const reason = ctx.reason.value.trim();
  if (!reason || reason.length > 1000 || /[\x00-\x1f\x7f]/.test(reason) || !ctx.confirm.checked) {
    ctx.error.textContent = "Enter a one-line reason of at most 1,000 characters and confirm the retirement first."; return;
  }
  ctx.sending = true; ctx.reasonText = ctx.reason.value; ctx.reason.disabled = true; ctx.confirm.disabled = true;
  ctx.error.textContent = ""; busy(ctx.button, "Retiring…");
  try {
    await apiWrite("/api/deck/retire", { profile: ctx.profile, id: ctx.id, sha256: ctx.meta.sha256,
      revision: ctx.meta.revision, reason });
    state.library = null; ctx.done = true;
    if (!retirementPageHere(ctx)) return;
    if (!retirementHere(ctx)) { location.hash = deckHistoryHref(ctx.id); return; }
    ctx.sheet.close();
    add(clear($("#main")), [pageHead({ crumb: ["#/library", "Decks"], title: "Deck retired" }),
      el("p", { text: `${ctx.meta.title} has left the library. Its history and matchup results are kept.` }),
      el("div", { class: "actions" }, el("a", { class: "btn btn-primary", href: deckHistoryHref(ctx.id), text: "View retained history" }),
        el("a", { class: "btn", href: "#/library", text: "Back to Decks" }))]);
  } catch (error) {
    state.library = null;
    if (!retirementHere(ctx)) return;
    ctx.error.textContent = error.message || String(error);
    ctx.error.append(" If you are unsure whether retirement was saved, inspect its history. ",
      el("a", { href: deckHistoryHref(ctx.id), text: "View retained history" }));
    if ([404, 409].includes(error.status)) {
      ctx.conflict = true;
      sheetActions(ctx.sheet, [{ text: "Review latest deck", kind: "primary", onclick: () => {
        if (!retirementHere(ctx) || ctx.sending) return; loadRetireDeck(ctx);
      } }, { text: "Cancel", onclick: () => ctx.sheet.close() }]);
    }
  } finally {
    ctx.sending = false;
    if (retirementHere(ctx) && !ctx.done && !ctx.conflict) {
      ctx.reason.disabled = false; ctx.confirm.disabled = false; unbusy(ctx.button);
    }
  }
}

function openRestoreDeck(data) {
  if (!data.retired || !data.may_restore || !Number.isInteger(data.retired_revision) || !state.profile
    || (data._historyProfile != null && data._historyProfile !== state.profile.id)) return null;
  const ctx = retirementContext("restore", data.id, data.title);
  if (ctx.data) return ctx;
  ctx.data = data;
  ctx.error = el("p", { class: "form-error", role: "alert" });
  add(ctx.sheet.body, [el("p", { text: "Restore the whole deck exactly as it was just before retirement, including its lists and notes? This adds a new saved revision; the earlier history stays." }), ctx.error]);
  sheetActions(ctx.sheet, [{ text: "Restore deck", kind: "primary", value: "restore", onclick: () => sendRestoreDeck(ctx) },
    { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  ctx.button = ctx.sheet.foot.querySelector("[data-action=restore]");
  return ctx;
}

async function sendRestoreDeck(ctx) {
  if (!retirementHere(ctx) || ctx.sending || ctx.done || ctx.conflict || !ctx.data.may_restore) return;
  ctx.sending = true; ctx.error.textContent = ""; busy(ctx.button, "Restoring…");
  try {
    await apiWrite("/api/deck/restore", { profile: ctx.profile, id: ctx.id, retired_revision: ctx.data.retired_revision });
    state.library = null; ctx.done = true;
    if (!retirementPageHere(ctx)) return;
    if (retirementHere(ctx)) ctx.sheet.close();
    location.hash = deckHref(ctx.id);
  } catch (error) {
    state.library = null;
    if (!retirementHere(ctx)) return;
    ctx.error.textContent = error.message || String(error);
    if ([404, 409].includes(error.status)) {
      ctx.conflict = true;
      sheetActions(ctx.sheet, [{ text: "Reload history", kind: "primary", onclick: () => { if (retirementHere(ctx)) route(); } },
        { text: "Cancel", onclick: () => ctx.sheet.close() }]);
    }
  } finally {
    ctx.sending = false;
    if (retirementHere(ctx) && !ctx.done && !ctx.conflict) unbusy(ctx.button);
  }
}
