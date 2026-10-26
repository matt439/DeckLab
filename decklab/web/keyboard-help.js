/* Current-page keyboard help and a local, reversible single-character preference.
 * Existing page handlers remain the action owners; this file dispatches no new key binding.
 * Context registrations hold only retained controls and current-owner predicates. Nothing runs at load. */
"use strict";

const keyboardCharacterChoices = new Map();
const keyboardHelpScopes = new Map();
let keyboardHelpNow = null, keyboardHelpWired = false;

function keyboardProfileId(profile = state.profile) { return typeof profile === "string" ? profile : profile?.id; }

/** A browser/person convenience. An absent choice preserves the existing shortcuts. */
function keyboardCharactersEnabled(profile = state.profile) {
  const id = keyboardProfileId(profile);
  if (!id || id !== state.profile?.id) return false;
  if (!keyboardCharacterChoices.has(id)) keyboardCharacterChoices.set(id, local.get(`keyboard.characters.${id}`) !== "off");
  return keyboardCharacterChoices.get(id);
}

/** The session choice remains effective when this browser refuses local storage. No settings API is used. */
function setKeyboardCharactersEnabled(enabled, profile = state.profile) {
  const id = keyboardProfileId(profile);
  if (!id || id !== state.profile?.id) return {applied: false, persisted: false};
  keyboardCharacterChoices.set(id, Boolean(enabled));
  const persisted = local.set(`keyboard.characters.${id}`, enabled ? "on" : "off");
  refreshKeyboardHints();
  return {applied: true, persisted};
}

function pruneKeyboardHelp() {
  for (const [root, scope] of keyboardHelpScopes)
    if (!root.isConnected || scope.profile !== state.profile?.id || scope.token !== routeToken) keyboardHelpScopes.delete(root);
}

/** Controllers register only after mount; inactive or casual controls never get initial key metadata. */
function registerKeyboardHelp(root, commands, {profile = state.profile, current = () => true, refresh = null} = {}) {
  pruneKeyboardHelp();
  if (!root?.isConnected) return root;
  const scope = {root, profile: keyboardProfileId(profile), token: routeToken, commands, current, refresh};
  keyboardHelpScopes.set(root, scope);
  if (refresh) refresh(keyboardCharactersEnabled(scope.profile) && keyboardHelpCurrent(scope));
  return root;
}

function keyboardHelpCurrent(scope) {
  return scope.root.isConnected && scope.token === routeToken && scope.profile === state.profile?.id && scope.current();
}

/** Return current-page facts for help; its own modal is intentionally not part of a page's ownership test. */
function keyboardHelpCommands() {
  pruneKeyboardHelp();
  const rows = [], seen = new Set(), enabled = keyboardCharactersEnabled();
  for (const [root, scope] of keyboardHelpScopes) {
    if (!root.isConnected || scope.profile !== state.profile?.id) { keyboardHelpScopes.delete(root); continue; }
    if (!keyboardHelpCurrent(scope)) continue;
    for (const command of (typeof scope.commands === "function" ? scope.commands() : scope.commands) || []) {
      const ready = typeof command.available === "function" ? command.available() : command.available !== false;
      const available = (!command.characters || enabled) && ready;
      const why = command.characters && !enabled ? "Single-character shortcuts are off."
        : available ? "" : command.unavailable || "Not available in the current page state.";
      const key = [command.keys.join(" "), command.label, command.scope, why].join("\n");
      if (seen.has(key)) continue;
      seen.add(key); rows.push({...command, available, why});
    }
  }
  return rows;
}

/** Toggle only the named metadata on original nodes; unrelated keys and descriptions are retained. */
function keyboardCharacterKeys(node, characters, enabled) {
  if (!node) return;
  const other = (node.getAttribute("aria-keyshortcuts") || "").split(/\s+/).filter(key => key && !characters.includes(key));
  const value = (enabled ? [...characters, ...other] : other).join(" ");
  if (value) { if (node.getAttribute("aria-keyshortcuts") !== value) node.setAttribute("aria-keyshortcuts", value); }
  else node.removeAttribute("aria-keyshortcuts");
}

function refreshKeyboardHints() {
  pruneKeyboardHelp();
  for (const [root, scope] of keyboardHelpScopes) {
    if (!root.isConnected || scope.profile !== state.profile?.id) { keyboardHelpScopes.delete(root); continue; }
    if (scope.refresh) scope.refresh(keyboardCharactersEnabled(scope.profile) && keyboardHelpCurrent(scope));
  }
}

/** Native focus must return to a currently visible control, not a menu item hidden before help opened. */
function keyboardHelpVisible(node) {
  if (!node || !keyboardShown(node)) return false;
  for (let at = node; at; at = at.parentNode) if (at.getAttribute && at.getAttribute("inert") !== null) return false;
  if (typeof getComputedStyle === "function") {
    const style = getComputedStyle(node);
    if (style.display === "none" || style.visibility === "hidden") return false;
  }
  return !node.getClientRects || node.getClientRects().length > 0;
}

function keyboardHelpOwned(context) {
  return keyboardHelpNow === context && !context.sheet.closed && context.sheet.dialog.isConnected
    && context.profile === state.profile?.id && context.token === routeToken && context.hash === location.hash
    && keyboardDialog() === context.sheet.dialog;
}

function drawKeyboardHelp(context) {
  if (!keyboardHelpOwned(context)) return;
  const commands = keyboardHelpCommands();
  clear(context.list);
  if (!commands.length) context.list.append(el("li", {class: "keyboard-help-empty", text: "No page-specific shortcuts are available here."}));
  for (const command of commands) context.list.append(el("li", {class: "keyboard-help-row"},
    el("span", {class: "keyboard-help-keys", text: command.keys.join(" / ")}),
    el("span", {class: "keyboard-help-action"}, el("b", {text: command.label}),
      el("span", {class: "keyboard-help-scope", text: command.scope}),
      command.why ? el("span", {class: "keyboard-help-unavailable", text: command.why}) : null)));
}

/** All people reach this through the avatar menu. New bindings belong to a later, separate patch. */
function showKeyboardHelp(anchor) {
  if (!state.profile || keyboardDialog() || keyboardHelpNow) return null;
  const profile = state.profile.id, token = routeToken, hash = location.hash;
  closeMenus();
  if (keyboardHelpVisible(anchor)) anchor.focus({preventScroll: true});
  let context;
  const sheet = openSheet("Keyboard shortcuts", {onClose: () => {
    context?.observer?.disconnect();
    window.removeEventListener("resize", resized);
    if (keyboardHelpNow === context) keyboardHelpNow = null;
    if (profile === state.profile?.id && token === routeToken && hash === location.hash && !keyboardDialog()
        && keyboardHelpVisible(anchor)) anchor.focus({preventScroll: true});
  }});
  const choice = el("input", {type: "checkbox", checked: keyboardCharactersEnabled(profile) || null});
  const notice = el("p", {class: "keyboard-save-notice", role: "status", hidden: true});
  const list = el("ul", {class: "keyboard-help-list"});
  context = {sheet, profile, token, hash, list, choice, notice};
  keyboardHelpNow = context;
  choice.addEventListener("change", () => {
    if (!keyboardHelpOwned(context)) return;
    const result = setKeyboardCharactersEnabled(choice.checked, profile);
    if (!result.applied) return;
    notice.hidden = result.persisted;
    notice.textContent = result.persisted ? "" : "This works for this visit, but this browser couldn't save your shortcut preference.";
    drawKeyboardHelp(context);
  });
  sheet.body.append(
    el("p", {class: "keyboard-help-intro", text: "These commands apply to the current page after you close help. Single-character page shortcuts leave text fields alone. Page commands do not act behind menus or other dialogs."}),
    el("label", {class: "keyboard-character-choice"}, choice, el("span", {text: "Single-character shortcuts"})),
    el("p", {class: "sub", text: "Turn off letters and / used as shortcuts. Tab, Enter, Space, arrows and Ctrl/Cmd shortcuts keep working."}),
    notice, list,
    el("p", {class: "sub", text: "Use Tab to reach controls, Enter or Space to activate a focused button, and Escape to close a menu or dialog. Up/Down moves between menu actions; overflow menus also support Home/End."}));
  const resized = () => { refreshKeyboardHints(); drawKeyboardHelp(context); };
  window.addEventListener("resize", resized);
  const page = document.getElementById("main");
  if (page && typeof MutationObserver === "function") {
    context.observer = new MutationObserver(() => drawKeyboardHelp(context));
    context.observer.observe(page, {childList: true, subtree: true, attributes: true,
      attributeFilter: ["disabled", "hidden", "aria-disabled", "aria-busy", "data-busy"]});
  }
  drawKeyboardHelp(context);
  sheet.heading.setAttribute("tabindex", "-1"); sheet.heading.focus({preventScroll: true});
  return sheet;
}

function setUpKeyboardHelp() {
  if (keyboardHelpWired) return;
  keyboardHelpWired = true;
  window.addEventListener("resize", refreshKeyboardHints);
}

function registerLibraryKeyboardHelp(results, token, profile) {
  registerKeyboardHelp(results, [
    {keys: ["J", "K"], label: "Select the next or previous deck", characters: true,
      scope: "In the lab, outside text fields."},
    {keys: ["Enter"], label: "Open a deck", scope: "With its deck row focused."},
  ], {profile, current: () => token === routeToken && libIsLab() && Boolean(results.querySelector(".deck-row")),
    refresh: enabled => { for (const row of results.querySelectorAll(".deck-row")) keyboardCharacterKeys(row, ["J", "K"], enabled); }});
}

function registerCollectionKeyboardHelp(cv) {
  const region = () => cv.list?.querySelector(".table-wrap");
  registerKeyboardHelp(cv.list, () => !keyboardHelpVisible(region()) ? [] : [
    {keys: ["J", "K"], label: "Select the next or previous card", characters: true,
      scope: "With the lab Card list focused.", available: () => !cv.busy,
      unavailable: "Wait for the current collection change to finish."},
    {keys: ["Enter"], label: "Open the current card or its details", scope: "With the Card list or its card-name button focused.",
      available: () => !cv.busy, unavailable: "Wait for the current collection change to finish."},
  ], {current: () => colActive(cv) && cv.root?.contains(cv.list), refresh: enabled => {
    const target = region(), hint = target?.querySelector(".keyboard-character-hint");
    const on = enabled && keyboardHelpVisible(target) && !cv.busy;
    if (hint && hint.hidden === on) hint.hidden = !on;
    keyboardCharacterKeys(target, ["J", "K"], on);
  }});
}

function registerEditorKeyboardHelp(ed) {
  const page = ed.dom.page, token = routeToken;
  const searchReady = () => !noOwnedList() && !ed.saving && !ed.asking;
  registerKeyboardHelp(page, () => [
    {keys: ["/"], label: "Find a card to add", characters: true, scope: "In this Editor, outside text fields.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["ArrowUp", "ArrowDown"], label: "Choose a search result", scope: "With Add cards search focused and current results loaded.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["Enter"], label: "Add the chosen or matching card", scope: "With Add cards search focused. A typed count, such as 4 bolt, applies.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["Shift+Enter"], label: "Add four copies", scope: "With Add cards search focused; existing printing and section rules apply.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["Alt+Enter"], label: "Inspect a search result", scope: "With Add cards search focused and a current result chosen.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["Escape"], label: "Clear search text and results", scope: "With a non-empty Add cards search field focused.",
      available: searchReady, unavailable: "Start the list first, or finish the current operation."},
    {keys: ["Enter"], label: "Finish editing a quantity", scope: "With a current list quantity field focused. Zero uses the existing Remove and Undo behavior.",
      available: () => !ed.asking && !ed.leaving && Array.from(ed.dom.lines?.querySelectorAll(".qty-input") || [])
        .some(input => input.isConnected && !input.disabled && !input.matches(":disabled")),
      unavailable: "There is no editable quantity here, or the current operation must finish first."},
    {keys: ["Enter"], label: "Finish editing an Add cards quantity", scope: "With a quantity field in a current Add cards result focused.",
      available: () => searchReady() && editorSearchResultsCurrent(ed.ac)
        && Array.from(ed.ac.list.querySelectorAll(".ac-stepper")).some(group => !group.hidden && !group.querySelector(".qty-input").disabled),
      unavailable: "There is no current search-result quantity here, or the current operation must finish first."},
    !ed.readOnly ? {keys: ["Ctrl/Cmd+S"], label: ed.mode === "new" ? "Create the deck" : "Save the draft",
      scope: "In this Editor. Uses the existing checks and confirmation.",
      available: () => !noOwnedList() && !ed.saving && !ed.asking && Boolean(ed.dom.barParts?.save) && !ed.dom.barParts.save.disabled,
      unavailable: "There is no save ready, or the current operation must finish first."} : null,
    {keys: ["Ctrl/Cmd+Z"], label: "Undo the last Editor change", scope: "Outside text fields; text fields keep their own Undo.",
      available: () => !ed.saving && !ed.asking && Boolean(ed.history?.length), unavailable: "No Editor change is ready to undo."},
  ].filter(Boolean), {profile: ed.profile,
    current: () => editorKeyboardCurrent(ed) && !ed.leaving && token === routeToken && page === ed.dom.page,
    refresh: enabled => {
      keyboardCharacterKeys(ed.ac?.input, ["/"], enabled && !noOwnedList() && !ed.saving && !ed.asking);
      const save = ed.dom.barParts?.save;
      keyboardCharacterKeys(save, ["Control+S", "Meta+S"], editorKeyboardCurrent(ed) && !ed.readOnly && !noOwnedList()
        && !ed.saving && !ed.asking && !ed.leaving && save && !save.disabled && !save.matches(":disabled"));
    }});
}

function registerShoppingKeyboardHelp(view) {
  const records = () => Array.from(view.root.querySelectorAll(".shop-delivery-summary"))
    .map(summary => ({summary, ...summary.keyboardDelivery})).filter(record => record.view === view);
  const receives = record => Boolean(record.description) && mayDo("receipts")
    && (view.data.orders || []).find(item => item.id === record.order.id) === record.order
    && (record.order.components || []).some(part => part.status === "pending");
  registerKeyboardHelp(view.root, () => [
    records().some(receives) ? {keys: ["R"], label: "Receive delivery", characters: true, scope: "With a pending delivery's summary focused.",
      available: () => !view.busy && !view.stale, unavailable: "Wait for the current Shopping change, or reload stale data."} : null,
    records().length ? {keys: ["Enter", "Space"], label: "Expand or collapse a delivery", scope: "With its delivery summary focused."} : null,
  ].filter(Boolean), {profile: view.profile, current: () => shopQueueActive(view),
    refresh: enabled => {
      for (const record of records()) {
        const {summary, hint, description} = record;
        const on = enabled && receives(record) && !view.busy && !view.stale;
        keyboardCharacterKeys(summary, ["R"], on);
        if (hint && hint.hidden === on) hint.hidden = !on;
        if (!description) continue;
        const words = (on ? "Press R from this delivery row to open Receive delivery. " : "")
          + "Enter or Space expands or collapses the row.";
        if (description.textContent !== words) description.textContent = words;
      }
    }});
}
