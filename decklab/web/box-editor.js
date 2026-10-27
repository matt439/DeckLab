/* One named physical observation accompanies an explicitly chosen existing editor version. */
"use strict";

let boxEditorHandoff = null;

function boxEditorScope() {
  return Boolean(state.profile?.id) && ownSpace() === HOME_SPACE && seesHomeInventory(state.may);
}

function boxEditorObservation(deck, evidence, row, direction) {
  const named = value => typeof value === "string" && value === value.trim() && value.length > 0 && value.length <= 200
    && !/[\u0000-\u001f\u007f]/.test(value);
  if (!boxEditorScope() || !deck || !/^(casual|commander)\/[^/]+$/.test(deck.id) || !named(deck.title)
      || evidence?.meta?.editable !== true || !/^[a-f0-9]{64}$/.test(evidence.meta.expect || "") || !/^[a-f0-9]{64}$/.test(evidence.meta.recipe_sha256 || "")
      || !row || !BOX_CHECK_SECTIONS.includes(row.section) || !["missing", "extra"].includes(direction)
      || !["card", "marker"].includes(row.kind) || !named(row.name) || !Number.isSafeInteger(row.quantity) || row.quantity < 1 || row.quantity > 9999
      || row.kind === "marker" && !named(row.for) || row.kind === "card" && row.for !== null) return null;
  return Object.freeze({ id: deck.id, title: deck.title, deck_sha256: evidence.meta.expect, recipe_sha256: evidence.meta.recipe_sha256,
    section: row.section, kind: row.kind, name: row.name, for: row.for, direction, quantity: row.quantity });
}

function boxEditorViewAllowed(view, observation) {
  return boxEditorScope() && view?.id === observation.id && view.sha256 === observation.deck_sha256 && view.editable === true
    && (view.may_save === undefined || view.may_save === true) && view.title === observation.title && ["casual", "commander"].includes(view.kind)
    && observation.id.startsWith(view.kind + "/") && (view.space || deckSpaceOf(view.id)) === HOME_SPACE
    && canEditDeck({ id: view.id, space: HOME_SPACE, player: view.fields?.player }) && view.lists && typeof view.lists === "object" && !Array.isArray(view.lists);
}

function boxEditorExistingVersion(view, version) {
  return ["target", "owned"].includes(version) && view?.lists?.[version] !== null && typeof view?.lists?.[version] === "object" && !Array.isArray(view.lists[version]);
}

/** The source check leaves the original counts open; only an explicit version choice leaves them. */
async function boxEditorChoices(deck, evidence, row, direction, options) {
  const observation = boxEditorObservation(deck, evidence, row, direction), profile = state.profile, token = routeToken, hash = location.hash;
  const here = () => observation && options.here() && profile === state.profile && token === routeToken && hash === location.hash
    && options.sourceSha() === observation.deck_sha256 && boxEditorScope();
  if (!here()) return;
  options.busy(true); clear(options.host).append(loadingBox("Checking the saved deck lists."));
  try {
    const view = await api(`/api/deck/edit?id=${encodeURIComponent(observation.id)}`);
    if (!here()) return;
    if (!boxEditorViewAllowed(view, observation)) throw new Error("The saved deck or your editing permission changed. Reload the plan before choosing a list.");
    const versions = ["target", "owned"].filter(version => boxEditorExistingVersion(view, version));
    if (!versions.length) throw new Error("No existing editable list could be checked. Reload the plan before choosing a list.");
    let chosen = false;
    clear(options.host).append(el("h4", { text: "Choose the intended list to review" }),
      el("p", { text: observation.section + ": " + direction + " " + observation.quantity + " x " + packBoxRowWords(observation) + "." }),
      el("p", { class: "sub", text: "Opening a list closes this box review and discards its local counts and extras. A check date is saved only with Save check date. You will make any list changes yourself." }),
      el("div", { class: "actions" }, versions.map(version => el("button", { type: "button", class: "btn btn-secondary box-editor-version",
        "data-version": version, text: "Open " + listName(version), onclick: event => {
          if (chosen || !here() || !event.currentTarget.isConnected || !options.host.contains(event.currentTarget)) return;
          chosen = true;
          options.leave(() => boxEditorNavigate(observation, version));
        } }))));
  } catch (failure) {
    if (here()) clear(options.host).append(el("p", { class: "form-error", role: "alert", text: failure.status
      ? "The saved deck lists couldn't be checked. Reload the plan before choosing a list."
      : failure.message || "The saved deck lists couldn't be checked." }));
  } finally { options.busy(false); } // The caller updates controls only while it still owns the original sheet.
}

function boxEditorNavigate(observation, version) {
  const hash = editHref(observation.id, version);
  boxEditorHandoff = { observation, version, hash, profile: state.profile, token: null, view: null };
  location.hash = hash;
}

function boxEditorRoute(path, token) {
  const handoff = boxEditorHandoff;
  if (!handoff) return;
  if (!boxEditorScope() || handoff.profile !== state.profile || path !== "edit" || location.hash !== handoff.hash || handoff.token !== null) {
    boxEditorHandoff = null; return;
  }
  handoff.token = token;
}

/** Normal Editor loading remains authoritative and must still offer its normal draft choices. */
function boxEditorGuardView(view, version, token) {
  const handoff = boxEditorHandoff;
  if (!handoff) return true;
  const owned = handoff.profile === state.profile && token === routeToken && token === handoff.token && location.hash === handoff.hash && boxEditorScope();
  if (!owned || version !== handoff.version || !boxEditorViewAllowed(view, handoff.observation) || !boxEditorExistingVersion(view, version)) {
    boxEditorHandoff = null;
    if (owned) $("#main").append(el("div", { class: "box box-warn" },
      el("p", { text: "The saved deck or this existing list changed after the box review. Open a fresh box check before using its observation." }),
      el("a", { class: "btn", href: "#/assembly", text: "Back to Build decks" })));
    return false;
  }
  handoff.view = view;
  return true;
}

/** Called only after startEditor's ordinary current/alias draft restore or rebase has finished. */
function attachBoxEditorContext(ed) {
  const handoff = boxEditorHandoff;
  if (!handoff) return;
  boxEditorHandoff = null;
  if (editor !== ed || handoff.profile !== state.profile || handoff.token !== routeToken || location.hash !== handoff.hash || !boxEditorScope()
      || ed.mode !== "edit" || ed.id !== handoff.observation.id || ed.version !== handoff.version || ed.readOnly || ed.view !== handoff.view
      || ed.sha256 !== handoff.observation.deck_sha256 || !boxEditorViewAllowed(ed.view, handoff.observation) || !boxEditorExistingVersion(ed.view, ed.version)) return;
  ed.boxObservation = Object.freeze({ observation: handoff.observation, profile: handoff.profile, token: handoff.token, hash: handoff.hash, version: handoff.version });
}

function boxEditorContextBanner(ed) {
  const context = ed.boxObservation;
  if (!context) return null;
  const here = () => editor === ed && context.profile === state.profile && context.token === routeToken && location.hash === context.hash
    && ed.mode === "edit" && ed.id === context.observation.id && ed.version === context.version && !ed.readOnly && !ed.gone && !ed.check?.file_changed
    && ed.sha256 === context.observation.deck_sha256 && boxEditorViewAllowed(ed.view, context.observation);
  if (!here()) return null;
  const observation = context.observation;
  return el("section", { class: "box box-info banner box-editor-note", role: "status" },
    el("h2", { text: "Box review observation" }),
    el("p", { text: observation.title + ": " + observation.section + "; " + observation.direction + " " + observation.quantity + " x " + packBoxRowWords(observation) + "." }),
    el("p", { text: "You chose the " + listName(context.version) + ". The observation is context only; decide any list changes yourself." }),
    el("p", { text: "Editing an intended list keeps the saved Assembled contents as recorded. Use Build decks to repack or take the deck apart when you physically change it." }),
    el("button", { type: "button", class: "btn btn-quiet", text: "Dismiss box observation", onclick: event => {
      if (here() && event.currentTarget.isConnected) { ed.boxObservation = null; drawBanners(); }
    } }));
}
