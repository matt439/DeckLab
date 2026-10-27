/* Saved Forge evidence matches the loaded playable baseline. A separate unchecked choice can request
   one guarded field run after a confirmed save; reading summaries alone never starts games. */
"use strict";

function editorSavedForgeFingerprint(ed) {
  const sha = ed?.view?.forge_lists?.[ed.version];
  return ed?.mode === "edit" && !ed.quick && ed.hasFileList && !ed.starting
    && ed.view?.lists?.[ed.version] != null && typeof ed.view.sha256 === "string"
    && /^[a-f0-9]{64}$/.test(ed.view.sha256) && typeof sha === "string" && /^[a-f0-9]{64}$/.test(sha) ? sha : null;
}

function editorForgeBaseline(ed) {
  return ed?.kind === "casual" ? editorSavedForgeFingerprint(ed) : null;
}

function editorForgeSummaryCurrent(context) {
  const ed = context?.ed;
  return !!(ed && editorKeyboardCurrent(ed) && !ed.leaving && ed.dom.forgeSummary === context
    && context.page === ed.dom.page && context.panel === ed.dom.forge && context.root.isConnected
    && context.panel.contains(context.root) && context.id === ed.id && context.version === ed.version
    && context.frame === keyboardEditorFrame(ed)
    && context.view === ed.view && context.sha === ed.view.sha256 && context.baseline === editorSavedForgeFingerprint(ed));
}

/** One read per actual Editor draw; all asynchronous work belongs to that original page and baseline. */
function mountEditorForgeSummary(ed = editor) {
  const baseline = editorSavedForgeFingerprint(ed);
  if (!baseline || !ed.dom.forge || !editorKeyboardCurrent(ed)) return;
  const root = el("div", { class: "edit-forge-summary stat-block", hidden: true });
  const context = ed.dom.forgeSummary = { ed, root, page: ed.dom.page, panel: ed.dom.forge,
    id: ed.id, version: ed.version, frame: keyboardEditorFrame(ed), view: ed.view, sha: ed.view.sha256, baseline, numbers: null };
  context.panel.insertBefore(root, ed.dom.forgeTest);
  if (!ed.readOnly) {
    context.input = el("input", { type: "checkbox", "aria-describedby": "editor-retest-reason" });
    context.reason = el("p", { id: "editor-retest-reason", class: "sub", hidden: true });
    context.choice = el("div", { class: "edit-retest", hidden: true },
      el("label", {}, context.input, el("span", { text: "Re-test against the field after saving" })), context.reason);
    context.input.addEventListener("change", () => {
      if (editorForgeSummaryCurrent(context) && !context.choice.hidden && !context.input.disabled
          && !ed.saving && !ed.asking && !ed.readOnly && mayStartRuns())
        ed.retestAfterSave = context.input.checked;
      syncEditorForgeSummary(ed);
    });
    context.panel.append(context.choice);
  }
  syncEditorForgeSummary(ed);
  if (!editorForgeBaseline(ed)) return; // Commander can re-test, but has no Constructed-field summary.
  api("/api/library/forge").then(answer => {
    if (!editorForgeSummaryCurrent(context) || !answer || answer.error) return;
    const numbers = answer.decks?.[context.id];
    if (!numbers || numbers.version !== context.version || numbers.card_sha !== baseline) return;
    const rate = numbers.rate;
    // Treat incomplete or malformed optional evidence as unavailable, never as an untested zero.
    if (!rate || ![rate.value, rate.low, rate.high].every(value => typeof value === "number" && Number.isFinite(value)
      && value >= 0 && value <= 1) || rate.low > rate.value || rate.value > rate.high
      || !Number.isSafeInteger(numbers.games) || numbers.games <= 0) return;
    context.numbers = numbers;
    syncEditorForgeSummary(ed);
  }).catch(() => {});
}

/** The retained Test row keeps its existing identity, eligibility reason and controls. */
function syncEditorForgeSummary(ed = editor) {
  const context = ed?.dom?.forgeSummary;
  if (!editorForgeSummaryCurrent(context)) return;
  const numbers = context.numbers;
  context.root.hidden = !numbers;
  if (numbers) {
    add(clear(context.root), [el("p", { class: "sub", text: `Forge field · saved ${listName(context.version, true)}` }),
      winRateFigure(numbers.rate, { size: "tile", what: "Forge field win rate for the saved list", games: numbers.games }),
      freshnessBadge(numbers.tested, { unsaved: !!ed.dirty }),
      rangeBar(numbers.rate, { compact: true }),
      numbers.partial ? el("p", { class: "sub", text: Number.isSafeInteger(numbers.counted) && Number.isSafeInteger(numbers.of)
        && numbers.counted >= 0 && numbers.of >= numbers.counted
        ? `Partial field results: ${numbers.counted} of ${numbers.of} opponents counted.`
        : "Partial field results; not every opponent has enough games." }) : null]);
  }
  if (context.input) {
    const gate = simulationsGate();
    context.choice.hidden = !ed.dirty || !!ed.readOnly;
    context.input.checked = !!ed.retestAfterSave;
    context.input.disabled = !!ed.saving || !!ed.asking || !gate.may;
    context.reason.hidden = gate.may;
    context.reason.textContent = gate.why || "";
  }
  context.panel.hidden = !numbers && !!ed.dom.forgeTest?.hidden && (!context.choice || context.choice.hidden);
}

/** Capture one explicit choice before the save request; the choice is transient, outside the draft. */
function editorRetestIntent(ed) {
  const context = ed?.dom?.forgeSummary;
  return editorForgeSummaryCurrent(context) && context.input && !ed.readOnly && ed.dirty && ed.retestAfterSave
    ? { context, profile: ed.profile, used: false } : null;
}

/** Only a confirmed successful save can submit. A queue failure never retries or changes that save. */
async function queueEditorRetest(intent, answer) {
  if (!intent || intent.used) return null;
  intent.used = true;
  const context = intent.context, ed = context.ed;
  const refused = text => ({ kind: "warn", text });
  if (!editorForgeSummaryCurrent(context) || intent.profile !== state.profile?.id || answer.id !== context.id)
    return refused("The deck was saved; its field re-test was not started after the page or person changed.");
  const gate = simulationsGate();
  if (!gate.may) return refused(`The deck was saved; its field re-test was not started. ${gate.why}`);
  const expected = answer.deck?.forge_lists?.[context.version];
  if (typeof expected !== "string" || !/^[a-f0-9]{64}$/.test(expected))
    return refused("The deck was saved, but its list could not be confirmed for re-testing. Open the deck to start a field run.");
  try {
    await apiWrite("/api/field/run", { profile: intent.profile, id: answer.id, version: context.version,
      expected_card_sha: expected });
    return { kind: "info", text: "Field re-test requested for the saved list. See Matchups for progress." };
  } catch (error) {
    // A lost response may follow a successful submission. Do not turn a queue retry into a second save/run.
    return refused(`The deck was saved; its field re-test could not be confirmed. ${error.message || "The server did not answer."} Check Matchups before starting another run.`);
  }
}

function editorRetestNotice(ed) {
  const notice = ed.afterSaveTest;
  if (!notice) return null;
  const text = el("p", { text: notice.text });
  const root = el("div", { class: `box box-${notice.kind} banner`, role: "status" },
    el("h2", { text: "Deck saved" }), text);
  ed.dom.afterSaveTestNotice = { root, text };
  return root;
}

/** A field response changes only its confirmation. The saved UI and later edits never wait for it. */
function observeEditorRetest(task, answer, owner) {
  if (!task) return;
  const profile = state.profile?.id, ed = owner.ed, saved = owner.saved;
  const view = ed?.view, frame = ed && keyboardEditorFrame(ed);
  const publish = notice => {
    answer.after_save_test = notice;
    if (!notice || state.profile?.id !== profile) return;
    if (saved) {
      if (state.saved === saved && saved.hash === location.hash && saved.testNotice?.isConnected)
        saved.testNotice.textContent = notice.text;
      return;
    }
    if (!editorKeyboardCurrent(ed) || ed.leaving || ed.view !== view || keyboardEditorFrame(ed) !== frame) return;
    ed.afterSaveTest = notice;
    const nodes = ed.dom.afterSaveTestNotice;
    if (nodes?.root.isConnected && ed.dom.page.contains(nodes.root)) {
      nodes.text.textContent = notice.text;
      nodes.root.classList.toggle("box-info", notice.kind === "info");
      nodes.root.classList.toggle("box-warn", notice.kind === "warn");
    }
  };
  task.then(publish, () => publish({ kind: "warn",
    text: "The deck was saved; its field re-test could not be confirmed. Check Matchups before starting another run." }));
}
