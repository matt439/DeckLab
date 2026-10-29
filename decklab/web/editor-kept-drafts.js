/* Drafts kept for later on the PC (E2-S16): the full editor's ▾ menu has Save draft for later, which
sends this editor's draft (draftRecord, the one this device keeps too) to /api/deck/draft, private to
the profile. Opening the same deck and list on another device as the same profile offers it
(keptDraftBanner): who kept it and when, which saved revision of the deck it started from, whether it
or this device's unsaved changes are newer, and Resume it or Discard it. Every write sends the draft's
revision, so a device that read an older one is refused and asked again rather than overwriting it.
Saving the deck clears a kept draft this editor resumed or kept (discardKeptAfterSave), and this
device's own draft remembers which kept draft it is (keptDraftMark), so that holds after the editor is
closed and opened again.

Only a saved deck the profile may save has one (not a new deck, a product deck or a read-only one), and
a server without the drafts' migration answers that they aren't available: then nothing here shows and
the editor keeps its drafts on this device only, as before. Loaded right after editor-drafts.js; the
other editor scripts call these through typeof checks. */
"use strict";

/** Whether this editor's list can have a draft kept for later. */
function keptDraftsApply(ed) {
  return !!ed && ed.mode === "edit" && !ed.readOnly && !!ed.id && !!ed.sha256;
}

/** ed.kept, the kept draft as this editor knows it: null (none offered here), {loading: true, mark}, or
 * {revision, draft (the API's, or null), deckRevision, ours (the revision this editor kept or resumed,
 * or null), resumed}. carried: the state a resume hands to the editor it starts. mark: this device's
 * draft's keptDraftMark, when the editor brought one back. after: a save's discard still being sent,
 * read only once it has settled, so the draft it publishes is never offered again. */
function loadKeptDraft(ed, carried, { mark = null, after = null } = {}) {
  const shown = !!(ed.kept && ed.kept.draft);
  ed.kept = null;
  if (!keptDraftsApply(ed)) return null;
  if (carried) {
    ed.kept = carried;
    return null;
  }
  mark = mark && Number.isInteger(mark.revision) && mark.revision > 0 ? { revision: mark.revision, resumed: !!mark.resumed } : null;
  ed.kept = { loading: true, mark };
  // Redraw only when a banner appears or goes: with nothing kept, the editor is drawn as it was.
  const redraw = () => { if (editor === ed && ed.dom && ed.dom.banners && (shown || (ed.kept && ed.kept.draft))) drawBanners(); };
  const read = () => api(`/api/deck/draft?id=${encodeURIComponent(ed.id)}&version=${encodeURIComponent(ed.version)}`);
  return (after ? Promise.resolve(after).then(read) : read())
    .then((answer) => {
      if (editor !== ed) return;
      // Still the revision this device kept or resumed: it's this editor's own, as before it was closed.
      const ours = mark && answer.draft && answer.revision === mark.revision ? mark.revision : null;
      ed.kept = answer.available ? keptFrom(answer, ours, ours !== null && mark.resumed) : null;
      redraw();
    })
    .catch(() => {
      // A draft kept for later is extra: if it can't be read, the editor works as it did without one.
      if (editor !== ed) return;
      ed.kept = null;
      redraw();
    });
}

function keptFrom(answer, ours, resumed = false) {
  return { revision: answer.revision, draft: answer.draft || null, deckRevision: answer.deck_revision || null,
    ours, resumed };
}

/** What saveDraft adds to this device's draft: {kept: {revision, resumed}} when it is the kept draft this
 * editor kept or resumed (or the editor brought that mark back and is still reading), else nothing. */
function keptDraftMark(ed) {
  const k = ed && ed.kept;
  if (!k) return {};
  if (k.loading) return k.mark ? { kept: { ...k.mark } } : {};
  return typeof k.ours === "number" && k.ours === k.revision ? { kept: { revision: k.ours, resumed: !!k.resumed } } : {};
}

/** "iPad", "Windows PC", ...: shown with a kept draft, so the other device can tell where it came from. */
function keptDeviceName() {
  const agent = (typeof navigator !== "undefined" && navigator.userAgent) || "";
  const touch = typeof navigator !== "undefined" && navigator.maxTouchPoints > 1;
  if (/iPad/.test(agent) || (/Macintosh/.test(agent) && touch)) return "iPad";
  if (/iPhone/.test(agent)) return "iPhone";
  if (/Android/.test(agent)) return "Android";
  if (/Windows/.test(agent)) return "Windows PC";
  if (/Macintosh/.test(agent)) return "Mac";
  if (/Linux/.test(agent)) return "Linux";
  return "";
}

/** Which saved revision of the deck the kept draft started from, in words. */
function keptStartedWords(started, now) {
  const at = started && started.revision ? `revision ${started.revision}` : null;
  if (started && started.current) return `It starts from the deck as it's saved now${at ? ` (${at})` : ""}.`;
  return `It started from ${at || "an earlier save"} of the deck${now ? `, which is at revision ${now} now` : ""}: ` +
    "resuming puts its changes on top of the latest version, for you to check before saving.";
}

/** Which is newer: the kept draft, or the unsaved changes this device brought back (or has open). */
function keptNewerWords(ed, savedMs) {
  const n = ed.notice;
  const local = n && (n.kind === "draft" || n.kind === "draft-changed") ? n.saved : null;
  if (local) {
    return savedMs > local ? `It's newer than the unsaved changes on this device, from ${timeWords(local)}.`
      : `The unsaved changes on this device, from ${timeWords(local)}, are newer.`;
  }
  return ed.dirty ? "This editor has unsaved changes of its own: resuming replaces them." : null;
}

/** drawBanners' part for a kept draft: an offer to resume or discard it, or what was resumed here. */
function keptDraftBanner(ed) {
  const k = ed && ed.kept;
  if (!k || k.loading || !k.draft) return null;
  const d = k.draft;
  const savedMs = Date.parse(d.saved_at);
  const kept = `Kept${d.device ? ` on ${d.device}` : ""} at ${timeWords(savedMs)}.`;
  const discard = el("button", { type: "button", class: "btn btn-discard", text: k.ours === k.revision
    ? "Discard it on every device" : "Discard it", onclick: () => discardKeptDraft(ed) });
  if (k.ours === k.revision) {
    if (!k.resumed) return null;
    return el("div", { class: "box box-info banner", role: "status" },
      el("h2", { text: "You picked up the draft kept for later" }),
      el("p", { text: `${kept} Saving the deck publishes it and clears it from your other devices.` }),
      el("div", { class: "actions" }, discard));
  }
  const newer = keptNewerWords(ed, savedMs);
  return el("div", { class: "box box-info banner", role: "status" },
    el("h2", { text: "A draft kept for later" }),
    el("p", { text: `${kept} ${keptStartedWords(d.started, k.deckRevision)}` }),
    newer ? el("p", { text: newer }) : null,
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn btn-primary", text: "Resume it", onclick: () => resumeKeptDraft(ed) }),
      discard));
}

/** The ▾ menu's item: keep this editor's unsaved changes for later, for another device. */
function keptDraftMenu(ed) {
  if (!keptDraftsApply(ed) || !ed.kept || ed.kept.loading || !ed.dirty) return [];
  return [{ text: "Save draft for later", onclick: () => keepDraftForLater(ed) }];
}

async function keepDraftForLater(ed, retried = false) {
  if (editor !== ed || !keptDraftsApply(ed) || !ed.kept || ed.kept.loading) return;
  saveDraft(ed);                      // this device keeps it too
  const k = ed.kept;
  let answer;
  try {
    answer = await apiWrite("/api/deck/draft", { id: ed.id, version: ed.version, expect: k.revision,
      draft: draftRecord(ed), device: keptDeviceName() });
  } catch (e) {
    if (editor !== ed) return;
    // Renamed since this editor opened: the editor's own sheet for that, never "another draft".
    if (e.status === 409 && e.data && e.data.conflict && e.data.conflict.reason === "renamed"
        && typeof renamedEditorConflict === "function"
        && renamedEditorConflict(openDeckRetirementSheet({ title: "This deck has been renamed" }), e)) return;
    if (e.status !== 409 || retried) return toast(e.message);
    // Another device kept or discarded one since this editor looked: show it, and ask before replacing it.
    await loadKeptDraft(ed);
    const other = ed.kept && ed.kept.draft;
    const choice = await ask("Another draft was kept for later", [
      other ? `It was kept${other.device ? ` on ${other.device}` : ""} at ${timeWords(Date.parse(other.saved_at))}. ` +
        "Saving yours replaces it on every device." : "It was discarded since. Saving yours keeps it for later again."],
    [{ value: "replace", text: "Save mine for later", kind: "danger" }, { value: "keep", text: "Leave it", kind: "primary" }]);
    if (choice === "replace" && editor === ed && ed.kept) return keepDraftForLater(ed, true);
    return;
  }
  if (editor !== ed) return;
  ed.kept = keptFrom(answer, answer.revision);
  saveDraft(ed);                      // and this device's draft remembers it's the kept one
  drawBanners();
  toast(`Kept for later. Open this deck on another device as ${state.profile.name} to pick it up.`);
}

async function resumeKeptDraft(ed) {
  const k = ed.kept;
  if (editor !== ed || !k || !k.draft) return;
  if (ed.dirty) {
    const choice = await ask("Use the draft kept for later?", [
      "The unsaved changes in this editor are replaced by it. This device's own draft is replaced too."],
    [{ value: "resume", text: "Use the kept draft", kind: "danger" }, { value: "keep", text: "Keep this device's", kind: "primary" }]);
    if (choice !== "resume" || editor !== ed) return;
  }
  clearTimeout(ed.checkTimer);
  clearTimeout(ed.draftTimer);
  ed.leaving = true;
  startEditor({ mode: "edit", view: ed.view, version: ed.version, keptDraft: k.draft.content,
    kept: { ...k, ours: k.revision, resumed: true } });
  saveDraft(editor);                  // and kept on this device, as any other unsaved change
}

async function discardKeptDraft(ed) {
  const k = ed.kept;
  if (editor !== ed || !k || !k.draft) return;
  const choice = await ask("Discard the draft kept for later?", [
    "It's removed from every device you use. The changes open in this editor stay as they are. This can't be undone."],
  [{ value: "discard", text: "Discard it", kind: "danger" }, { value: "keep", text: "Keep it", kind: "primary" }]);
  if (choice !== "discard" || editor !== ed || ed.kept !== k) return;
  try {
    const answer = await apiWrite("/api/deck/draft", { id: ed.id, version: ed.version, expect: k.revision, draft: null });
    if (editor !== ed) return;
    ed.kept = keptFrom(answer, null);
    saveDraft(ed);                    // this device's draft is no longer the kept one
    drawBanners();
    toast("The draft kept for later is discarded.");
  } catch (e) {
    if (editor !== ed) return;
    toast(e.message);
    if (e.status === 409) loadKeptDraft(ed);
  }
}

/** After a save: the kept draft this editor resumed or kept is published, so it goes from every device.
 * A newer one kept elsewhere since is left alone (its revision differs), and a failure never fails the save.
 * The save never waits for it: doSave hands it to the editor it starts, which reads its kept draft only
 * once this has settled. null when there's none to clear. */
function discardKeptAfterSave(ed) {
  const k = ed && ed.kept;
  if (!k || !k.draft || k.ours !== k.revision) return null;      // nothing to wait for
  return apiWrite("/api/deck/draft", { id: ed.id, version: ed.version, expect: k.revision, draft: null })
    .catch(() => null);           // left for the other device to offer or discard
}
