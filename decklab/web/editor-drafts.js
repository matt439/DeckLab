/* The editor's drafts (split from editor.js, E11-S46): re-applying an edit's changes onto a newer
version of the deck (reapplyList, reapplyFields, rebase), and keeping the edit on this device as a
draft (draftKey, queueDraft, saveDraft, draftStored, readDraft, removeDraft), with timeWords for the
banner that brings one back. Loaded right after editor.js, in the same global scope: these functions
use its constants and helpers (copyList, tally, lineKey, norm, `editor`, ...) when they're called. */
"use strict";

// --------------------------------------------------------------- re-applying

/** latest with the changes from base to mine on top: each printing's copies go up or down by what
 * changed here (a card added here that the latest version lacks is added). A printing the latest
 * version changed too gets a note, as does a take-out that can't be made in full. {lists, notes}. */
function reapplyList(base, mine, latest) {
  const result = copyList(latest);
  const before = tally(base);
  const after = tally(mine);
  const theirs = tally(latest);
  const notes = [];
  for (const key of new Set([...before.keys(), ...after.keys()])) {
    const b = before.get(key);
    const a = after.get(key);
    const delta = (a ? a.qty : 0) - (b ? b.qty : 0);
    if (!delta) continue;
    const { section, line } = a || b;
    const was = b ? b.qty : 0;
    const now = theirs.has(key) ? theirs.get(key).qty : 0;
    const lines = result[section] || (result[section] = []);
    const same = lines.filter((l) => lineKey(l) === lineKey(line));
    const where = `${line.name} (${printingText(line)}${section === "Deck" ? "" : `, ${sectionWords(section)}`})`;
    let take = 0;
    if (delta > 0) {
      if (same.length) same[0].qty = Math.min(MAX_COPIES, same[0].qty + delta);
      else placeLine(lines, newLine({ ...line, qty: Math.min(MAX_COPIES, delta) }));
    } else {
      take = -delta;
      for (const l of same) {
        const n = Math.min(take, l.qty);
        l.qty -= n;
        take -= n;
      }
      if (take > 0) {
        notes.push(`${where}: you took out ${-delta}, but the latest version had ` +
          `${-delta - take === 0 ? "none" : `only ${-delta - take}`} of it.`);
      }
      result[section] = lines.filter((l) => l.qty > 0);
    }
    if (!take && now !== was) {
      // Both changed this printing: say what the sum came to, so it isn't a surprise in the review.
      const total = copies((result[section] || []).filter((l) => lineKey(l) === lineKey(line)));
      notes.push(`${where}: the latest version has ${now} (${was || "none"} when you opened it); with your ` +
        `${delta > 0 ? "+" : "−"}${Math.abs(delta)} it's ${total ? total : "taken out"} now.`);
    }
  }
  for (const name of Object.keys(result)) if (!result[name].length) delete result[name];
  return { lists: result, notes };
}

/** latest's fields with the ones changed here (from base to mine) put back. {fields, notes}. */
function reapplyFields(base, mine, latest) {
  const fields = { ...latest };
  const notes = [];
  for (const key of EDIT_FIELDS) {
    if (norm(key, mine[key]) === norm(key, base[key])) continue;
    if (norm(key, latest[key]) !== norm(key, base[key]) && norm(key, latest[key]) !== norm(key, mine[key])) {
      notes.push(`${FIELD_WORDS[key]}: the latest version says ${fieldValueWords(key, latest[key])}; ` +
        `yours, ${fieldValueWords(key, mine[key])}, is kept.`);
    }
    fields[key] = mine[key];
  }
  return { fields, notes };
}

/** Make view (the latest /api/deck/edit answer) the editor's file, with mine's changes from base
 * re-applied on top. Returns notes about anything that couldn't be re-applied exactly. */
function rebase(ed, view, mine, base) {
  const latest = view.lists[ed.version];
  let lists;
  let notes = [];
  let starting = false;
  if (mine.starting) {
    // An owned-only version started here: it's all new, so it stays as it is.
    lists = copyList(mine.lists);
    starting = latest == null;
    if (!starting) notes.push(`The latest version already has a ${listName("owned", true)}: saving replaces it with this one.`);
  } else if (ed.version === "target" && typeof editorHasLinkedPromotion === "function" && editorHasLinkedPromotion(ed, mine, base)) {
    lists = copyList(mine.lists); // The linked pair is reconciled together below, without quantity deltas.
  } else {
    ({ lists, notes } = reapplyList(base.lists, mine.lists, latest || {}));
  }
  const latestFields = pickFields(view.fields);
  const f = reapplyFields(pickFields(base.fields), { ...latestFields, ...mine.fields }, latestFields);
  // The write-up: a section changed here keeps this text (the latest version's change to it is named).
  const latestProse = proseOf(view);
  const prose = { ...latestProse };
  for (const key of PROSE_KEYS) {
    const was = (base.prose || {})[key] || "";
    const now = (mine.prose || {})[key];
    if (now == null || now === was) continue;
    if (latestProse[key] !== was && latestProse[key] !== now) {
      notes.push(`The ${key === "notes" ? "Notes" : "Substitutes"} write-up changed in the latest version too; yours is kept.`);
    }
    prose[key] = now;
  }
  Object.assign(ed, {
    view, sha256: view.sha256, title: view.title, kind: view.kind, sections: view.sections,
    brackets: view.brackets || [], hasFileList: latest != null, starting,
    base: { lists: copyList(latest || {}), fields: latestFields, prose: latestProse },
    lists, fields: f.fields, removed: [], accRows: null, prose, markCurrent: !!(mine.markCurrent && view.changed_on), ...editorPlayerKitSnapshot(mine),
  });
  if (typeof rebaseEditorConsidering === "function") rebaseEditorConsidering(ed, view, mine, base, notes);
  return [...notes, ...f.notes];
}


// ------------------------------------------------------------------ drafts

function draftKey(ed) {
  const where = ed.space && ed.space !== HOME_SPACE ? `${ed.space}.` : "";
  return ed.mode === "new" ? `draft.${ed.profile}.new.${where}${ed.from || "scratch"}` : `draft.${ed.profile}.${ed.id}.${ed.version}`;
}

function queueDraft() {
  clearTimeout(editor.draftTimer);
  const ed = editor;
  // Undoing the final change must clear its earlier draft before clean navigation can proceed.
  if (!isDirty()) { saveDraft(ed); return; }
  editor.draftTimer = setTimeout(() => saveDraft(ed), DRAFT_DELAY);
}

/** Keep the changes on this device; false means the current work is only safe in this open editor. */
function saveDraft(ed) {
  if (!ed || ed !== editor) return false;
  if (ed.leaving) return true;
  clearTimeout(ed.draftTimer);
  if (ed.pendingDraftKey && !removeDraft(ed)) return false;
  if (!isDirty()) {
    const removed = removeDraft(ed);
    if (removed) draftStored(ed, true);
    return removed;
  }
  const saved = local.set(draftKey(ed), JSON.stringify({
    v: 1, saved: Date.now(), sha256: ed.sha256 || null, starting: !!ed.starting,
    base: { lists: sendList(ed.base.lists), fields: ed.base.fields, prose: ed.base.prose || null, ...editorConsideringBase(ed) },
    lists: keepList(ed.lists), fields: ed.fields, addSection: ed.addSection, ...editorConsideringSnapshot(ed), ...editorPlayerKitSnapshot(ed),
    prose: ed.prose || null, markCurrent: !!ed.markCurrent }));
  draftStored(ed, saved);
  return saved;
}

function draftStored(ed, saved) {
  const failed = !saved;
  if (!!ed.draftFailed === failed && !(saved && ed.draftRemoveFailed)) return;
  ed.draftFailed = failed;
  if (saved) ed.draftRemoveFailed = false;
  if (ed === editor && ed.dom && ed.dom.banners) drawBanners();
}

function readDraft(ed) {
  try {
    const draft = JSON.parse(local.get(draftKey(ed)) || "null");
    return draft && draft.v === 1 && draft.lists && draft.fields && draft.base ? draft : null;
  } catch (e) {
    return null;
  }
}

function removeDraft(ed) {
  const keys = new Set([draftKey(ed), ed.pendingDraftKey].filter(Boolean));
  const removed = [...keys].map(key => local.remove(key)).every(Boolean);
  if (removed) ed.pendingDraftKey = null;
  if (!!ed.draftRemoveFailed !== !removed) {
    ed.draftRemoveFailed = !removed;
    if (ed === editor && ed.dom && ed.dom.banners) drawBanners();
  }
  return removed;
}

/** "2:31 pm today", "9:05 am yesterday" or "28 Sep, 2:31 pm". */
function timeWords(ms) {
  const d = new Date(ms);
  const clock = d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, " ");
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(new Date()) - day(d)) / 86400000);
  if (days === 0) return `${clock} today`;
  if (days === 1) return `${clock} yesterday`;
  return `${d.getDate()} ${d.toLocaleDateString("en-AU", { month: "short" })}, ${clock}`;
}
