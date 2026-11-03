/* Saved Forge evidence matches the loaded playable baseline. Separate unchecked choices can request one
   guarded field run, and one standard-sample popular-decks run (E3-S37, the Planned list only, its tick
   remembered per profile on this device), after a confirmed save; reading summaries alone never starts games. */
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
    if (ed.version === "target") mountEditorPopularChoice(ed, context);
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
    const popular = context.popular;
    if (popular) {
      // Offered only once the catalogue answered with a standard sample, read once the list is first
      // changed (no read for a page only looked at); the gate's reason line is shared.
      if (!context.choice.hidden && !popular.asked) editorPopularCatalogue(ed, context);
      popular.choice.hidden = context.choice.hidden || !popular.size;
      popular.input.checked = !!popular.checked;
      popular.input.disabled = context.input.disabled;
    }
  }
  context.panel.hidden = !numbers && !!ed.dom.forgeTest?.hidden && (!context.choice || context.choice.hidden);
}

/** Capture one explicit choice before the save request; the choice is transient, outside the draft. */
function editorRetestIntent(ed) {
  const context = ed?.dom?.forgeSummary;
  if (!editorForgeSummaryCurrent(context) || !context.input || ed.readOnly || !ed.dirty) return null;
  const field = !!ed.retestAfterSave, popular = editorPopularTicked(context);
  return field || popular ? { context, profile: ed.profile, used: false, field, popular, popularUsed: false,
    size: popular ? context.popular.size : null } : null;
}

/** Only a confirmed successful save can submit. A queue failure never retries or changes that save. */
async function queueEditorRetest(intent, answer) {
  if (!intent || intent.used || intent.field === false) return null;
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
    return { kind: "info", text: "Field re-test requested for the saved list. See Testing for progress." };
  } catch (error) {
    // A lost response may follow a successful submission. Do not turn a queue retry into a second save/run.
    return refused(`The deck was saved; its field re-test could not be confirmed. ${error.message || "The server did not answer."} Check Testing before starting another run.`);
  }
}

function editorRetestNotice(ed) {
  const notice = ed.afterSaveTest, popular = ed.afterSavePopular;
  if (!notice && !popular) return null;
  const warn = [notice, popular].some(n => n?.kind === "warn");
  const root = el("div", { class: `box box-${warn ? "warn" : "info"} banner`, role: "status" },
    el("h2", { text: "Deck saved" }));
  if (notice) {
    const text = el("p", { text: notice.text });
    root.append(text);
    ed.dom.afterSaveTestNotice = { root, text };
  }
  if (popular) {
    const line = editorPopularLine(popular);
    root.append(line.root);
    ed.dom.afterSavePopularNotice = { root, text: line.text, link: line.link };
  }
  return root;
}

/** A field response changes only its confirmation. The saved UI and later edits never wait for it. */
function observeEditorRetest(task, answer, owner, slot = "test") {
  if (!task) return;
  const profile = state.profile?.id, ed = owner.ed, saved = owner.saved;
  const view = ed?.view, frame = ed && keyboardEditorFrame(ed);
  const popular = slot === "popular";
  const publish = notice => {
    if (popular) answer.after_save_popular = notice; else answer.after_save_test = notice;
    if (!notice || state.profile?.id !== profile) return;
    if (saved) {
      const node = popular ? saved.popularNotice : saved.testNotice;
      if (state.saved === saved && saved.hash === location.hash && node?.isConnected) node.textContent = notice.text;
      return;
    }
    if (!editorKeyboardCurrent(ed) || ed.leaving || ed.view !== view || keyboardEditorFrame(ed) !== frame) return;
    if (popular) ed.afterSavePopular = notice; else ed.afterSaveTest = notice;
    const nodes = popular ? ed.dom.afterSavePopularNotice : ed.dom.afterSaveTestNotice;
    if (nodes?.root.isConnected && ed.dom.page.contains(nodes.root)) {
      nodes.text.textContent = notice.text;
      if (nodes.link) {
        nodes.link.hidden = !notice.link;
        if (notice.link) nodes.link.setAttribute("href", notice.link);
      }
      const warn = [ed.afterSaveTest, ed.afterSavePopular].some(n => n?.kind === "warn");
      nodes.root.classList.toggle("box-info", !warn);
      nodes.root.classList.toggle("box-warn", warn);
    }
  };
  task.then(publish, () => publish(popular ? editorPopularUnconfirmed(answer.id) : { kind: "warn",
    text: "The deck was saved; its field re-test could not be confirmed. Check Testing before starting another run." }));
}

// ============================================================ E3-S37: popular decks after saving

/** This device's remembered tick, one per profile; never part of the draft, its history or another profile's. */
function editorPopularKey(profile) { return `editor.testPopular.${profile}`; }

/** The choice is drawn hidden and offered only once the format's catalogue answers with a standard sample. */
function mountEditorPopularChoice(ed, context) {
  const format = ed.kind === "commander" ? "commander" : "constructed";
  const input = el("input", { type: "checkbox", "aria-describedby": "editor-retest-reason" });
  const words = el("span", { text: "Test against popular decks after saving" });
  const popular = context.popular = { input, words, format, size: null, profile: ed.profile,
    checked: local.get(editorPopularKey(ed.profile)) === "1",
    choice: el("div", { class: "edit-retest edit-retest-popular", hidden: true }, el("label", {}, input, words)) };
  input.addEventListener("change", () => {
    if (editorForgeSummaryCurrent(context) && popular.size && !popular.choice.hidden && !input.disabled
        && !ed.saving && !ed.asking && !ed.readOnly && mayStartRuns() && popular.profile === state.profile?.id) {
      popular.checked = input.checked;
      local.set(editorPopularKey(popular.profile), input.checked ? "1" : "0");
    }
    syncEditorForgeSummary(ed);
  });
  context.panel.append(popular.choice);
}

/** One catalogue read per mount: its standard sample's opponents give the choice its "same N opponents". */
function editorPopularCatalogue(ed, context) {
  const popular = context.popular;
  popular.asked = true;
  Promise.resolve().then(() => api(`/api/gauntlet/catalogue?format=${popular.format}`)).then(answer => {
    if (!editorForgeSummaryCurrent(context) || context.popular !== popular || !answer?.built) return;
    const size = answer.standard?.opponents;
    if (!Number.isSafeInteger(size) || size <= 0) return;
    popular.size = size;
    popular.words.textContent = `Test against popular decks after saving (same ${plural(size, "opponent")})`;
    syncEditorForgeSummary(ed);
  }).catch(() => {});
}

function editorPopularTicked(context) {
  const popular = context?.popular;
  return !!(popular && popular.size && popular.checked && !popular.choice.hidden && context.version === "target");
}

/** The review sheet's words, or null when this save won't ask for a popular-decks run. */
function editorPopularReviewLine(ed) {
  const context = ed?.dom?.forgeSummary;
  if (!editorForgeSummaryCurrent(context) || ed.readOnly || !ed.dirty || !editorPopularTicked(context)) return null;
  const size = context.popular.size;
  return `Then tests the saved list against the same ${plural(size, "popular deck")} (about ${thousands(size * 100)} games).`;
}

function editorPopularHref(id) { return `${deckHref(id, "target")}&tab=matchups&part=gauntlet`; }

function editorPopularUnconfirmed(id) {
  return { kind: "warn", link: editorPopularHref(id),
    text: "The deck was saved; its popular-decks test couldn't be confirmed. Check its Testing tab before starting another run." };
}

/** One standard-sample run (the board's Play: no budget or sample, so fixed:100) after a confirmed save.
 *  A refusal or failure never retries, and never changes the save or the later draft. */
async function queueEditorPopularTest(intent, answer) {
  if (!intent?.popular || intent.popularUsed) return null;
  intent.popularUsed = true;
  const context = intent.context, link = editorPopularHref(answer.id);
  const refused = text => ({ kind: "warn", text, link });
  if (!editorForgeSummaryCurrent(context) || intent.profile !== state.profile?.id || answer.id !== context.id)
    return refused("The deck was saved; its popular-decks test wasn't started after the page or person changed.");
  const gate = simulationsGate();
  if (!gate.may) return refused(`The deck was saved; its popular-decks test wasn't started. ${gate.why}`);
  const expected = answer.deck?.forge_lists?.target;
  if (typeof expected !== "string" || !/^[a-f0-9]{64}$/.test(expected))
    return refused("The deck was saved, but its list couldn't be confirmed for testing. Start it from its Testing tab.");
  try {
    await apiWrite("/api/gauntlet/run", { profile: intent.profile, id: answer.id, version: "target",
      expected_card_sha: expected });
    return { kind: "info", link, text: `Popular-decks test requested for the saved list (${
      plural(intent.size, "opponent")}). Its Testing tab shows progress.` };
  } catch (error) {
    // A lost response may follow a queued run: say so rather than retry into a second run.
    if (!(error instanceof ApiError) || !error.status) return editorPopularUnconfirmed(answer.id);
    return refused(`The deck was saved; its popular-decks test wasn't started. ${error.message || "The server refused it."}`);
  }
}

/** A notice line with its Testing tab link. */
function editorPopularLine(notice) {
  const text = el("span", { text: notice.text });
  const link = el("a", { href: notice.link || "#", text: "Popular decks view", hidden: !notice.link });
  return { root: el("p", {}, text, " ", link), text, link };
}
