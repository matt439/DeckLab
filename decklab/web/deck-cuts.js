/* Cached evidence for choosing Commander cuts; mutations stay in the editor's ordinary draft. */
"use strict";

function edhrecCutsContext(ctx) {
  ctx.owner = { token: routeToken, hash: location.hash, profile: state.profile, id: ctx.id,
    profileId: state.profile?.id, space: state.profile?.space || HOME_SPACE, summaryId: ctx.data?.summary.id,
    data: ctx.data, summary: ctx.data?.summary, version: ctx.data?.version,
    main: document.getElementById("main"), body: ctx.sheet.body, foot: ctx.sheet.foot };
}
function edhrecCutsHere(ctx, control = null) {
  const own = ctx.owner;
  return own && !ctx.sheet.closed && !ctx.closingForRoute && routeToken === own.token && location.hash === own.hash && state.profile === own.profile
    && state.profile?.id === own.profileId && (state.profile?.space || HOME_SPACE) === own.space && ctx.data?.summary.id === own.summaryId
    && ctx.id === own.id && ctx.data === own.data && ctx.data?.summary === own.summary && ctx.data?.version === own.version
    && document.getElementById("main") === own.main && own.main.isConnected && ctx.sheet.body === own.body
    && ctx.sheet.foot === own.foot && ctx.sheet.dialog.isConnected
    && (!control || control.isConnected && own.body.contains(control) && keyboardDialog() === ctx.sheet.dialog);
}
function openDeckCuts(data) { return openEdhrecSheet(data, null, { cuts: true }); }
function editorCutsSections(ed) {
  const planned = ed.version === "owned" ? ed.planned || ed.view?.lists?.target : ed.lists;
  if (!planned) return null;
  return Object.fromEntries(["Commander", "Deck", "Companion"].filter(section => planned[section])
    .map(section => [section, (planned[section] || []).map(sendLine)]));
}
function editorCutsOwner(ed) {
  return editor === ed && ed.profile === state.profile?.id && !ed.leaving && !ed.saving && !ed.readOnly && ed.dom.page?.isConnected;
}
function openEditorCuts(ed = editor) {
  if (!editorCutsOwner(ed) || currentKind() !== "commander") return null;
  const data = ed.mode === "new" ? null : { summary: { id: ed.id, title: ed.view?.title || "This deck" }, version: "target" };
  return openEdhrecSheet(data, null, { cuts: true, editor: ed });
}
function editorCutsLink(ed, n) {
  return el("button", { type: "button", class: "btn btn-quiet editor-cuts-link", text: "Review cuts",
    "aria-label": `Review cuts: ${n - 100} over 100`, onclick: () => {
      if (editorCutsOwner(ed) && !document.querySelector("dialog[open]")) openEditorCuts(ed);
    } });
}
async function loadEdhrecCuts(ctx) {
  const seq = ++ctx.seq;
  clear(ctx.area); clear(ctx.message).append(loadingBox("Reading cached cut evidence…"));
  try {
    const ed = ctx.cutEditor;
    if (ed && (!editorCutsOwner(ed) || editorCutsSections(ed) === null)) return;
    ctx.draftSignature = ed ? snapshot(ed) : null;
    const sections = ed ? editorCutsSections(ed) : null;
    const answer = ed ? await apiWrite("/api/deck/cuts", { ...(ed.mode === "edit" ? { id: ed.id } : { space: ed.space || ownSpace() }),
      sections, ...(ctx.page ? { page: ctx.page } : {}) })
      : await api(`/api/deck/edhrec?${new URLSearchParams({ id: ctx.id, view: "cuts", ...(ctx.page ? { page: ctx.page } : {}) })}`);
    if (!edhrecCutsHere(ctx) || seq !== ctx.seq || ed && (!editorCutsOwner(ed) || snapshot(ed) !== ctx.draftSignature)) return;
    ctx.answer = answer; ctx.pages = Array.isArray(answer.pages) ? answer.pages : [];
    clear(ctx.message); drawEdhrecPicker(ctx); drawEdhrecCuts(ctx);
  } catch (error) {
    if (edhrecCutsHere(ctx) && seq === ctx.seq) {
      drawEdhrecPicker(ctx); clear(ctx.message).append(loadFailed("Cut evidence", error, () => loadEdhrecCuts(ctx)));
    }
  }
}
function drawEdhrecCuts(ctx) {
  const a = ctx.answer, src = a.source || {}, ed = ctx.cutEditor;
  ctx.sheet.heading.textContent = "Commander cuts";
  const choices = !ed ? el("div", { class: "segmented", role: "group", "aria-label": "Show" },
    el("button", { type: "button", text: "Ideas", "aria-pressed": "false", onclick: () => {
      if (!edhrecCutsHere(ctx)) return; ctx.filter = "new"; loadEdhrec(ctx);
    } }), el("button", { type: "button", text: "Cuts", "aria-pressed": "true" })) : null;
  add(clear(ctx.area), [choices,
    el("p", { class: "sub", text: "Planned list · non-land cards outside the Commander section" }),
    el("p", { class: "sub edhrec-source" }, src.available
      ? `Cached EDHREC page for ${(a.commanders || []).join(" & ")}${src.fetched ? `, fetched ${String(src.fetched).slice(0, 10)}` : ""}. `
      : "No readable cached EDHREC page is available. Inclusion is unknown. ",
    src.url ? el("a", { href: src.url, target: "_blank", rel: "noopener noreferrer", text: "Open on EDHREC" }) : null),
    el("details", { class: "more cut-method" }, el("summary", { text: "About this evidence" }), el("p", { class: "sub", text: a.note }),
      a.role_source ? el("p", { class: "sub" }, "Role-count starting points: ",
        el("a", { href: a.role_source.url, target: "_blank", rel: "noopener noreferrer", text: a.role_source.title }),
        `. ${a.role_source.date}. Categories overlap; a surplus is evidence to review, not a requirement to cut.`) : null,
      !a.forge?.available || !a.forge.enough || a.forge.games < a.forge.min_games ? el("p", { class: "sub", text:
        `Forge cut reasons need at least ${a.forge?.min_games || 800} current-list card-log games. No missing or early numbers count as a cut reason.` }) : null),
    a.unknown?.length ? el("p", { class: "box box-warn", text: `${plural(a.unknown.length, "card")} cannot be assessed from the current card data.` }) : null,
    !a.may_edit ? el("p", { class: "sub", text: ed?.mode === "new" ? "Save the deck first to move cards to Considering or test a swap." : "This view is read-only." }) : null,
    (a.groups || []).length ? a.groups.map(group => el("section", { class: "edhrec-group" },
      el("h3", { text: group.header }), group.cards.map(row => edhrecCutRow(ctx, row)))) : emptyBox("There are no known non-land cards to review.")]);
}
function edhrecCutRow(ctx, row) {
  const share = Number.isFinite(row.inclusion) ? `${num(row.inclusion, 2)}% of EDHREC decks` : "Inclusion unknown";
  const actions = el("div", { class: "actions" });
  const replacements = el("div", { class: "cut-replacements" });
  const fold = el("details", { class: "edhrec-cut" }, el("summary", { text: `${row.name} · ${share}` }),
    cardRow(row.card, { name: row.name, meta: plural(row.qty, "copy", "copies"), viewerGroup: "edhrec-cuts" }),
    row.reasons?.length ? el("ul", { class: "cut-reasons" }, row.reasons.map(reason => el("li", {},
      el("p", { text: reason.text }), reason.measure ? el("p", { class: "sub", text: reason.measure }) : null)))
      : el("p", { class: "sub", text: "No role surplus or qualifying Forge reason is recorded for this card." }), actions, replacements);
  if (ctx.answer.may_edit) {
    const local = ctx.cutEditor && ctx.cutEditor.version !== "owned";
    const move = local ? el("button", { type: "button", class: "btn", text: "Move to Considering", onclick: () => {
      if (edhrecCutsHere(ctx, move) && snapshot(ctx.cutEditor) === ctx.draftSignature && editorDemoteCut(ctx.cutEditor, row.name)) ctx.sheet.close();
    } }) : el("a", { class: "btn", text: "Move to Considering", href: `${editHref(ctx.id, "target")}&cut=${encodeURIComponent(row.name)}` });
    if (!local) move.addEventListener("click", event => { if (!edhrecCutsHere(ctx, move)) event.preventDefault(); });
    const test = el("button", { type: "button", class: "btn", text: "Test this swap", onclick: () => {
      if (edhrecCutsHere(ctx, test)) loadCutReplacements(ctx, row, replacements, test);
    } });
    actions.append(move, test);
  }
  return fold;
}
async function loadCutReplacements(ctx, row, host, trigger) {
  if (trigger.disabled) return;
  trigger.disabled = true; clear(host).append(loadingBox("Looking for free replacements…", { small: true }));
  try {
    const answer = await api(`/api/deck/replacements?${new URLSearchParams({ id: ctx.id, version: "target", card: row.name })}`);
    if (!edhrecCutsHere(ctx) || !trigger.isConnected || !host.isConnected || !ctx.owner.body.contains(host)) return;
    clear(host).append(answer.candidates?.length ? el("ul", { class: "swap-list" }, answer.candidates.map(candidate => {
      const button = el("button", { type: "button", class: "btn", text: `Test ${candidate.name} for ${row.name}`, onclick: () => {
        if (!edhrecCutsHere(ctx, button)) return;
        if (ctx.cutEditor?.version === "target") editorCutSwap(ctx, row, candidate);
        else testReplacementSwap({ summary: { id: ctx.id, title: ctx.data?.summary.title || "This deck" }, version: "target" },
          { name: row.name }, candidate, button, () => edhrecCutsHere(ctx, button));
      } });
      return el("li", {}, cardRow(candidate.card, { name: candidate.name, meta: swapCandidateMeta(candidate), viewerGroup: "cut-replacements" }), button);
    })) : el("p", { class: "sub", text: "No free replacement fits this slot. Choose a replacement in the editor before testing a change." }));
  } catch (error) {
    if (edhrecCutsHere(ctx) && host.isConnected) clear(host).append(el("p", { class: "sub", text: "Free replacements couldn't load. The cut evidence and your draft are unchanged." }));
  } finally { if (edhrecCutsHere(ctx) && trigger.isConnected) trigger.disabled = false; }
}
function editorDemoteCut(ed, name) {
  if (!editorCutsOwner(ed) || ed.version !== "target" || !editorConsideringSupported(ed)) return false;
  const selected = (ed.lists.Deck || []).filter(line => (line.card?.name || line.name) === name);
  if (!selected.length) { toast("That card isn't in the Planned list now."); return false; }
  const commanders = new Set((ed.lists.Commander || []).map(line => line.card?.name || line.name));
  if (commanders.has(name) || selected.some(line => !line.card || /\bLand\b/.test(String(line.card.type_line || "").split(" // ")[0]))) {
    toast("Cuts reviews known non-land cards outside the Commander section."); return false;
  }
  ed.lists.Deck = ed.lists.Deck.filter(line => !selected.includes(line));
  ed.considering.push(...selected.map(line => newLine({ ...sendLine(line), card: line.card })));
  syncSections(); drawEditor(); changed(); toast(`Moved ${name} to the Considering draft.`); return true;
}
function editorCutSwap(ctx, row, candidate) {
  const ed = ctx.cutEditor;
  if (!editorCutsOwner(ed) || snapshot(ed) !== ctx.draftSignature) return;
  const swapped = replacementSwapList(ed.lists, row.name, candidate);
  if (!swapped) { toast("That card isn't in the draft now."); return; }
  ed.lists = copyList(swapped); syncSections(); drawEditor(); changed();
  const token = routeToken, hash = location.hash, profile = state.profile, after = snapshot(ed);
  ctx.afterClose = () => { if (editorCutsOwner(ed) && routeToken === token && location.hash === hash
    && state.profile === profile && snapshot(ed) === after) vtOpenTestSheet(); };
  ctx.sheet.close();
}
async function editorCutFromRoute(params) {
  const name = params.get("cut");
  if (!name || !editor || editor.version !== "target") return;
  const ed = editor, previousHash = location.hash;
  params.delete("cut"); const canonicalHash = `#/edit?${params}`;
  history.replaceState(history.state, "", canonicalHash); canonicalEditorPaneHash(ed, previousHash, canonicalHash);
  const profile = state.profile, hash = location.hash, token = routeToken, before = snapshot(ed);
  const lines = (ed.lists.Deck || []).filter(line => (line.card?.name || line.name) === name);
  if (!lines.length) { toast("That card isn't in the Planned draft now."); return; }
  const answer = await ask("Move to Considering?", [`Move ${plural(lines.reduce((sum, line) => sum + line.qty, 0), "copy", "copies")} of ${name} out of the Planned draft? Printing and categories stay with the lines. Check and Save when ready.`],
    [{ text: "Keep editing", value: "keep" }, { text: "Move to Considering", value: "move", kind: "primary" }]);
  if (answer === "move" && editorCutsOwner(ed) && state.profile === profile && routeToken === token && location.hash === hash && snapshot(ed) === before)
    editorDemoteCut(ed, name);
}
