/* Saved Forge evidence for the full casual Editor. A result belongs to its exact loaded playable
   baseline, never merely to a deck id, a profile cache or representative artwork. No games start here. */
"use strict";

function editorForgeBaseline(ed) {
  const sha = ed?.view?.forge_lists?.[ed.version];
  return ed?.mode === "edit" && !ed.quick && ed.kind === "casual" && ed.hasFileList && !ed.starting
    && ed.view?.lists?.[ed.version] != null && typeof ed.view.sha256 === "string"
    && /^[a-f0-9]{64}$/.test(ed.view.sha256) && typeof sha === "string" && /^[a-f0-9]{64}$/.test(sha) ? sha : null;
}

function editorForgeSummaryCurrent(context) {
  const ed = context?.ed;
  return !!(ed && editorKeyboardCurrent(ed) && !ed.leaving && ed.dom.forgeSummary === context
    && context.page === ed.dom.page && context.panel === ed.dom.forge && context.root.isConnected
    && context.panel.contains(context.root) && context.id === ed.id && context.version === ed.version
    && context.frame === keyboardEditorFrame(ed)
    && context.view === ed.view && context.sha === ed.view.sha256 && context.baseline === editorForgeBaseline(ed));
}

/** One read per actual Editor draw; all asynchronous work belongs to that original page and baseline. */
function mountEditorForgeSummary(ed = editor) {
  const baseline = editorForgeBaseline(ed);
  if (!baseline || !ed.dom.forge || !editorKeyboardCurrent(ed)) return;
  const root = el("div", { class: "edit-forge-summary stat-block", hidden: true });
  const context = ed.dom.forgeSummary = { ed, root, page: ed.dom.page, panel: ed.dom.forge,
    id: ed.id, version: ed.version, frame: keyboardEditorFrame(ed), view: ed.view, sha: ed.view.sha256, baseline, numbers: null };
  context.panel.insertBefore(root, ed.dom.forgeTest);
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
  context.panel.hidden = !numbers && !!ed.dom.forgeTest?.hidden;
}
