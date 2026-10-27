/* Rename a saved deck's title and address, with a reviewed write and explicit old-address draft recovery. */
"use strict";

function canRenameDeck(data) {
  const s = data?.summary;
  return !!s && !s.read_only && !s.error && canEditDeck(s)
    && /^(?:[^/]+\/)?(?:casual|commander)\/[a-z0-9]+(?:-[a-z0-9]+)*$/.test(s.id);
}

/** Replace only the deck id, preserving list, tab, filter and historical revision parameters. */
function renamedDeckAddress(id, hash = location.hash) {
  const [path, query = ""] = hash.split("?", 2), params = new URLSearchParams(query);
  params.set("id", id);
  return `${path}?${params}`;
}

function canonicalDeckAddress(id) {
  const here = parseHash();
  if (!["deck", "edit", "history"].includes(here.path) || !id || addressDeckId(here.params.get("id")) === id) return;
  history.replaceState(history.state, "", renamedDeckAddress(id));
}

function renameTitle(value) { return String(value || "").replace(/\p{Cf}/gu, "").trim().replace(/\s+/g, " "); }

function openRenameDeck(data) {
  if (!canRenameDeck(data) || !state.profile) return null;
  const existing = [...deckRetirementSheets].map(s => s.renameContext)
    .find(ctx => ctx && ctx.id === data.summary.id && retirementHere(ctx));
  if (existing) return existing;
  const sheet = openDeckRetirementSheet({ title: `Rename ${data.summary.title}` });
  const ctx = { id: data.summary.id, data, sheet, token: routeToken, profile: state.profile.id,
    hash: location.hash, generation: 0, sending: false, done: false, titleText: null, review: null };
  sheet.renameContext = ctx;
  loadRenameDeck(ctx);
  return ctx;
}

async function loadRenameDeck(ctx) {
  if (!retirementHere(ctx) || ctx.sending) return;
  const generation = ++ctx.generation; ctx.valid = false; ctx.review = null;
  clear(ctx.sheet.body).append(loadingBox("Checking the deck before renaming it…"));
  sheetActions(ctx.sheet, [{ text: "Cancel", onclick: () => ctx.sheet.close() }]);
  try {
    const meta = await api(`/api/deck/rename?id=${encodeURIComponent(ctx.id)}`);
    if (!retirementHere(ctx) || generation !== ctx.generation) return;
    ctx.meta = meta; ctx.conflict = false;
    if (meta.id !== ctx.id || !meta.may_rename || !Number.isInteger(meta.revision) || meta.revision < 1
      || !/^[0-9a-f]{64}$/.test(meta.sha256 || "") || typeof meta.title !== "string" || !canRenameDeck(ctx.data)) {
      clear(ctx.sheet.body).append(el("p", { text: meta.why_not || "This deck changed. Open its current page before renaming it." }));
      if (meta.id && meta.id !== ctx.id) ctx.sheet.body.append(el("a", { class: "btn", href: deckHref(meta.id), text: "Open current deck" }));
      return;
    }
    ctx.valid = true;
    if (ctx.titleText == null) ctx.titleText = meta.title;
    drawRenameDeck(ctx);
  } catch (error) {
    if (!retirementHere(ctx) || generation !== ctx.generation) return;
    clear(ctx.sheet.body).append(el("p", { class: "form-error", role: "alert", text: error.message || String(error) }));
    sheetActions(ctx.sheet, [{ text: "Try again", onclick: () => loadRenameDeck(ctx) },
      { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  }
}

function drawRenameDeck(ctx) {
  ctx.sheet.heading.textContent = `Rename ${ctx.meta.title}`;
  ctx.input = el("input", { type: "text", maxlength: MAX_TITLE, autocomplete: "off", "aria-label": "New deck title",
    oninput: () => {
      if (!retirementHere(ctx) || ctx.sending) return;
      ctx.titleText = ctx.input.value; ctx.review = null; ctx.conflict = false;
      clear(ctx.reviewBox); ctx.error.textContent = ""; renameActions(ctx);
    } });
  ctx.input.value = ctx.titleText;
  ctx.error = el("p", { class: "form-error", role: "alert" });
  ctx.reviewBox = el("div");
  clear(ctx.sheet.body).append(el("p", { text: "Change this deck's title and address together. Its format and collection stay the same. History and saved matchup links are kept, and old deck links open the new address." }),
    el("label", { class: "field" }, el("span", { text: "New title" }), ctx.input), ctx.reviewBox, ctx.error);
  renameActions(ctx);
}

function renameActions(ctx) {
  const title = renameTitle(ctx.input.value);
  sheetActions(ctx.sheet, [{ text: "Preview rename", kind: "primary", value: "preview",
    disabled: ctx.sending || !title || title.length > MAX_TITLE || /[\x00-\x1f\x7f]/.test(ctx.input.value),
    onclick: () => previewRenameDeck(ctx) }, { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  ctx.button = ctx.sheet.foot.querySelector("[data-action=preview]");
}

function validRenameReview(ctx, review) {
  const prefix = ctx.id.slice(0, ctx.id.lastIndexOf("/") + 1);
  return review?.id === ctx.id && review.sha256 === ctx.meta.sha256 && review.revision === ctx.meta.revision
    && review.old_title === ctx.meta.title && typeof review.title === "string" && !!review.title
    && review.title === renameTitle(ctx.input.value) && review.new_id === prefix + slugOf(review.title)
    && typeof review.decks_revision === "string" && !!review.decks_revision && typeof review.changed === "boolean";
}

async function previewRenameDeck(ctx) {
  if (!retirementHere(ctx) || ctx.sending || !ctx.valid || !canRenameDeck(ctx.data)) return;
  const title = renameTitle(ctx.input.value);
  if (!title || title.length > MAX_TITLE || /[\x00-\x1f\x7f]/.test(ctx.input.value)) return;
  ctx.sending = true; ctx.review = null; ctx.titleText = ctx.input.value; ctx.input.disabled = true;
  ctx.error.textContent = ""; clear(ctx.reviewBox); busy(ctx.button, "Preparing preview.");
  try {
    const review = await apiWrite("/api/deck/rename/preview", { profile: ctx.profile, id: ctx.id, title,
      sha256: ctx.meta.sha256, revision: ctx.meta.revision });
    if (!retirementHere(ctx)) return;
    if (!validRenameReview(ctx, review)) throw new Error("The rename preview could not be verified. Review the latest deck before trying again.");
    ctx.review = review; drawRenameReview(ctx);
  } catch (error) {
    if (retirementHere(ctx)) renameFailure(ctx, error, false);
  } finally {
    ctx.sending = false;
    if (retirementHere(ctx)) {
      ctx.input.disabled = false;
      if (!ctx.review && !ctx.conflict) renameActions(ctx);
    }
  }
}

function drawRenameReview(ctx) {
  const r = ctx.review;
  clear(ctx.reviewBox).append(el("h3", { text: "Review rename" }),
    el("p", {}, el("strong", { text: "From: " }), r.old_title, el("br"), el("code", { text: r.id })),
    el("p", {}, el("strong", { text: "To: " }), r.title, el("br"), el("code", { text: r.new_id })),
    el("p", { text: "Earlier addresses stay reserved for this deck. You can rename it again later. Its saved revisions and matchup results stay readable." }));
  if (Array.isArray(r.notes) && r.notes.length) ctx.reviewBox.append(el("ul", {}, r.notes.map(note => el("li", { text: String(note) }))));
  if (!r.changed) {
    ctx.reviewBox.append(el("p", { text: "The title and address already match. Nothing needs changing." }));
    sheetActions(ctx.sheet, [{ text: "Done", kind: "primary", onclick: () => ctx.sheet.close() }]);
    return;
  }
  ctx.confirm = el("input", { type: "checkbox", onchange: () => {
    if (retirementHere(ctx) && !ctx.sending) ctx.button.disabled = !ctx.confirm.checked;
  } });
  ctx.reviewBox.append(el("label", { class: "choice" }, ctx.confirm,
    el("span", { text: "I have checked the new title and address and want to rename this deck." })));
  sheetActions(ctx.sheet, [{ text: "Rename deck", kind: "primary", value: "rename", disabled: true, onclick: () => sendRenameDeck(ctx) },
    { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  ctx.button = ctx.sheet.foot.querySelector("[data-action=rename]");
}

function renameFailure(ctx, error, uncertain) {
  ctx.error.textContent = error.message || String(error);
  if (uncertain) ctx.error.append(" If you are unsure whether it was saved, open the deck to check before trying again.");
  if (uncertain || [404, 409].includes(error.status)) {
    ctx.conflict = true;
    const canonical = error.data?.canonical_id;
    if (canonical) ctx.error.append(" ", el("a", { href: deckHref(canonical), text: "Open current deck" }));
    sheetActions(ctx.sheet, [{ text: "Review latest deck", kind: "primary", onclick: () => {
      if (retirementHere(ctx) && !ctx.sending) loadRenameDeck(ctx);
    } }, { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  }
}

async function sendRenameDeck(ctx) {
  const r = ctx.review;
  if (!retirementHere(ctx) || ctx.sending || ctx.done || ctx.conflict || !ctx.valid || !r?.changed
    || !validRenameReview(ctx, r) || !ctx.confirm?.checked || !canRenameDeck(ctx.data)) return;
  ctx.sending = true; ctx.input.disabled = true; ctx.confirm.disabled = true; ctx.error.textContent = "";
  busy(ctx.button, "Renaming.");
  try {
    const answer = await apiWrite("/api/deck/rename", { profile: ctx.profile, id: r.id, title: r.title,
      new_id: r.new_id, sha256: r.sha256, revision: r.revision, decks_revision: r.decks_revision });
    if (answer.id !== r.new_id || answer.title !== r.title) throw new Error("The saved rename could not be verified. Open the deck to check its current address.");
    state.library = null; ctx.done = true;
    if (!retirementPageHere(ctx)) return;
    if (retirementHere(ctx)) ctx.sheet.close();
    location.hash = renamedDeckAddress(answer.id, ctx.hash);
    toast(`Renamed to ${answer.title}.`);
  } catch (error) {
    state.library = null;
    if (retirementHere(ctx)) renameFailure(ctx, error, true);
  } finally {
    ctx.sending = false;
    if (retirementHere(ctx) && !ctx.done) { ctx.input.disabled = false; if (ctx.confirm) ctx.confirm.disabled = false; }
  }
}

/** Old addresses may hold another device draft. Choosing one is explicit; only a successful copy permits removal. */
function openSavedDeckEditor(view, version) {
  canonicalDeckAddress(view.id);
  const profile = state.profile?.id, token = routeToken, hash = location.hash;
  const here = () => token === routeToken && profile === state.profile?.id && hash === location.hash;
  const key = draftKey({ mode: "edit", profile, id: view.id, version });
  const aliases = [...new Set([view.requested_id, ...(view.aliases || [])])].filter(id => id && id !== view.id);
  const drafts = view.may_save === false ? [] : aliases.map(id => {
    const oldKey = draftKey({ mode: "edit", profile, id, version }), raw = local.get(oldKey);
    if (!raw) return null;
    return { id, key: oldKey, raw };
  }).filter(Boolean);
  if (!drafts.length) { startEditor({ mode: "edit", view, version }); return; }
  const current = local.get(key), error = el("p", { class: "form-error", role: "alert" });
  const open = () => { if (here()) { clear($("#main")); startEditor({ mode: "edit", view, version }); } };
  const recover = draft => {
    if (!here()) return;
    const sheet = openDeckRetirementSheet({ title: "Review an earlier-address draft?" });
    sheet.body.append(el("p", { text: `Open the draft saved under ${draft.id} against the latest saved deck? Review all reapplied changes before saving.` }),
      el("p", { text: current ? "This replaces the current-address draft on this device. The saved deck is unchanged until you save it."
        : "The draft moves to the current address on this device. The saved deck is unchanged until you save it." }));
    sheetActions(sheet, [{ text: "Use this draft", kind: "primary", onclick: () => {
      if (!here() || sheet.closed) return;
      if (local.get(draft.key) !== draft.raw || local.get(key) !== current) {
        error.textContent = "A draft changed while you were reviewing it. Reload the editor and choose again."; sheet.close(); return;
      }
      try {
        const parsed = JSON.parse(draft.raw);
        if (parsed.v !== 1 || !parsed.lists || !parsed.fields || !parsed.base) throw new Error("invalid");
      } catch (_) { error.textContent = "This older draft cannot be read. It is still kept on this device."; sheet.close(); return; }
      if (!local.set(key, draft.raw)) { error.textContent = "The draft could not be copied. Its original is still kept on this device."; sheet.close(); return; }
      const removed = local.remove(draft.key); sheet.close(); open();
      if (!removed) toast("The draft is open at the current address. Its older-address copy could not be removed from this device.");
    } }, { text: "Cancel", onclick: () => sheet.close() }]);
  };
  add(clear($("#main")), [pageHead({ crumb: [deckHref(view.id, version), view.title], title: "Choose a saved draft" }),
    el("p", { text: "This deck has been renamed. Unsaved changes from an earlier address are still on this device. Choose which draft to open; they will not be combined automatically." }),
    el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-primary",
      text: current ? "Keep current-address draft" : "Open saved deck", onclick: open })),
    el("ul", {}, drafts.map(draft => el("li", {}, el("button", { type: "button", class: "btn", text: `Review draft from ${draft.id}`, onclick: () => recover(draft) })))), error]);
}

/** A stale editor never redirects a write. Keep its draft, then let the person reopen the current address. */
function renamedEditorConflict(sheet, error) {
  const canonical = error.data?.canonical_id, ed = editor;
  if (error.status !== 409 || error.data?.conflict?.reason !== "renamed" || !canonical || !ed) return false;
  if (!deckRetirementSheets.has(sheet)) {
    sheet.close();
    sheet = openDeckRetirementSheet({ title: "This deck has been renamed" });
  }
  sheet.heading.textContent = "This deck has been renamed";
  const message = el("p", { class: "form-error", role: "alert" });
  clear(sheet.body).append(el("p", { text: error.message }),
    el("p", { text: "Nothing was saved. Keep your changes as a draft, then open the current address to review them against the latest deck." }), message);
  sheetActions(sheet, [{ text: "Keep draft and open current deck", kind: "primary", onclick: () => {
    if (editor !== ed || ed.profile !== state.profile?.id || sheet.closed) return;
    if (!saveDraft(ed)) { message.textContent = "Your draft could not be kept on this device. Keep this editor open."; return; }
    ed.leaving = true; sheet.close(); location.hash = editHref(canonical, ed.version);
  } }, { text: "Keep editing", onclick: () => sheet.close() }]);
  return true;
}
