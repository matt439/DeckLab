/* Private, name-only checklists. Each row is one physical copy. */
"use strict";

const UPGRADE_CHOICES = { check: "Check at home", set_aside: "Set aside", buy: "Buy" };
const UPGRADE_MAX_COPIES = 200;

function upgradeSingleLine(text) {
  return [...text].length <= 150 && !/[\u0000-\u001f\u007f-\u009f\u2028\u2029\ud800-\udfff]/u.test(text);
}

function upgradeBuyText(rows) {
  const purchases = new Map();
  for (const row of rows) {
    if (row.choice !== "buy") continue;
    const key = row.name.normalize("NFC").toLowerCase();
    const entry = purchases.get(key);
    if (entry) entry.quantity++;
    else purchases.set(key, { name: row.name, quantity: 1 });
  }
  return Array.from(purchases.values(), entry => `${entry.quantity} ${entry.name}`).join("\n");
}

function deckUpgradeChecklistOffered(data) {
  const deck = data.summary, space = deck.space || deckSpaceOf(deck.id);
  return Boolean(state.profile?.id) && /^(casual|commander)$/.test(deck.kind)
    && !/^(product|pairing)\//.test(deck.id) && ownSpace() === space;
}

function openDeckUpgradeChecklist(data, seed = []) {
  if (!deckUpgradeChecklistOffered(data) || deckScreen?.data !== data) return null;
  const screen = deckScreen;
  return openUpgradeChecklist(() => deckScreen === screen, data, seed);
}

function deckUpgradeChecklistButton(screen) {
  if (!deckUpgradeChecklistOffered(screen.data)) return null;
  return el("button", { type: "button", class: "btn", text: "Card checklist", onclick: event => {
    if (event.currentTarget.isConnected && deckScreen === screen && screen.view.tab === "cards") {
      openDeckUpgradeChecklist(screen.data);
    }
  } });
}

async function openUpgradeChecklist(currentPage = () => true, deck = null, seed = []) {
  const profile = state.profile, token = routeToken, hash = location.hash;
  if (!profile?.id || parseHash().path !== (deck ? "deck" : "library") || !currentPage()) return null;
  const sheet = colOpenSheet(deck ? "Card checklist" : "Check cards for a deck");
  const query = deck ? `?deck=${encodeURIComponent(deck.summary.id)}` : "";
  const path = `/api/profiles/${encodeURIComponent(profile.id)}/deck-checklist${query}`;
  const current = () => !sheet.closed && sheet.dialog.isConnected && state.profile === profile
    && routeToken === token && location.hash === hash && currentPage();
  const view = { sheet, path, current, deck, busy: false };
  async function loadChecklist() {
    if (view.busy || !current()) return;
    view.busy = true;
    clear(sheet.body).append(loadingBox("Loading your checklist…"));
    try {
      const saved = await api(path);
      if (current()) {
        view.busy = false;
        drawUpgradeChecklist(view, saved, seed);
      }
    } catch (error) {
      if (current()) {
        const retry = el("button", { type: "button", class: "btn", text: "Try again", onclick: event => {
          if (sheet.body.contains(event.currentTarget)) loadChecklist();
        } });
        clear(sheet.body).append(loadFailed("Your checklist", error), retry);
      }
    } finally { view.busy = false; }
  }
  await loadChecklist();
  return sheet;
}

function drawUpgradeChecklist(view, saved, seed = []) {
  const { sheet, path, current, deck } = view;
  const root = el("div", { class: "upgrade-checklist" });
  const here = () => current() && sheet.body.contains(root);
  const active = node => here() && !view.busy && !confirming && sheet.dialog.contains(node);
  let baseline = saved, rows = saved.rows.map(row => ({ ...row })), conflict = false, confirming = false;
  const title = el("input", { type: "text", value: saved.title, maxlength: 300, autocomplete: "off" });
  const names = el("textarea", { rows: 3, placeholder: "Arcane Signet", spellcheck: "false" });
  const list = el("ul", { class: "upgrade-checklist-rows", "aria-label": "Cards to check" });
  const totals = el("p", { class: "sub", role: "status" });
  const progress = el("p", { class: "sub", role: "status" });
  const message = el("div", { role: "status" });
  const buyList = el("textarea", { readonly: true, rows: 3, spellcheck: "false" });
  const field = (label, control) => el("label", { class: "field" }, el("span", { text: label }), control);
  const buyField = field("Buy list", buyList);
  const addButton = el("button", { type: "button", class: "btn", text: "Add cards", onclick: event => {
    if (active(event.currentTarget) && addNames()) names.focus();
  } });
  const deckPicker = deck ? upgradeDeckCards(deck, active, addCopies) : null;
  const reload = el("button", { type: "button", class: "btn", text: "Reload saved checklist", hidden: true,
    onclick: event => { if (active(event.currentTarget) && conflict) reloadSaved(); } });
  const copy = el("button", { type: "button", class: "btn", text: "Copy buy list", onclick: copyBuys });
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save checklist", onclick: saveChanges });
  const close = el("button", { type: "button", class: "btn", text: "Close", onclick: event => {
    if (active(event.currentTarget)) sheet.dismiss();
  } });

  function dirty() {
    return Boolean(names.value.trim()) || title.value.trim() !== baseline.title ||
      rows.length !== baseline.rows.length || rows.some((row, i) =>
        row.name !== baseline.rows[i].name || row.choice !== baseline.rows[i].choice);
  }
  function sync() {
    const counts = { check: 0, set_aside: 0, buy: 0 };
    for (const row of rows) counts[row.choice]++;
    totals.textContent = rows.length
      ? `${counts.check} to check · ${counts.set_aside} set aside · ${counts.buy} to buy` : "";
    buyList.value = upgradeBuyText(rows);
    buyField.hidden = copy.hidden = !counts.buy;
    reload.hidden = !conflict;
    title.disabled = names.disabled = addButton.disabled = view.busy;
    if (deckPicker) deckPicker.disabled = view.busy;
    for (const control of list.querySelectorAll("select,button")) control.disabled = view.busy;
    save.disabled = view.busy || conflict || !dirty();
    reload.disabled = copy.disabled = close.disabled = view.busy;
    progress.textContent = view.busy ? "Working…" : conflict ? "The saved checklist changed on another device. Reloading replaces your edits."
      : dirty() ? "Unsaved changes" : baseline.revision ? "Checklist saved" : "";
  }
  function drawRows() {
    clear(list);
    for (const [index, row] of rows.entries()) {
      const select = el("select", { "aria-label": `Plan for ${row.name}, copy on line ${index + 1}`,
        onchange: event => {
          if (!active(event.currentTarget)) return;
          row.choice = select.value;
          clear(message); sync();
        } }, Object.entries(UPGRADE_CHOICES).map(([value, text]) => el("option", { value, text })));
      select.value = row.choice;
      const remove = el("button", { type: "button", class: "btn btn-quiet", text: "Remove",
        "aria-label": `Remove ${row.name}, line ${index + 1}`, onclick: event => {
          if (!active(event.currentTarget)) return;
          rows.splice(index, 1);
          clear(message); drawRows(); sync();
          (list.children[Math.min(index, rows.length - 1)]?.querySelector("button") || names).focus();
        } });
      list.append(el("li", {}, el("strong", { text: row.name }), select, remove));
    }
  }
  function addNames() {
    const batch = names.value.split(/\r\n?|\n/).map(name => name.trim()).filter(Boolean);
    if (!addCopies(batch)) {
      names.focus();
      return false;
    }
    names.value = "";
    sync();
    return true;
  }
  function addCopies(batch) {
    if (!batch.length || rows.length + batch.length > UPGRADE_MAX_COPIES) {
      message.textContent = "Choose cards to add, up to 200 copies across the checklist.";
      return false;
    }
    if (batch.some(name => !name || !upgradeSingleLine(name))) {
      message.textContent = "Use one name per line, up to 150 characters each, with no tabs or control characters.";
      return false;
    }
    rows.push(...batch.map(name => ({ name, choice: "check" })));
    clear(message); drawRows(); sync();
    return true;
  }
  async function saveChanges(event) {
    if (!active(event.currentTarget) || conflict || !dirty()) return;
    if (!upgradeSingleLine(title.value.trim())) {
      message.textContent = "Use a deck name of up to 150 characters. Remove any tabs or control characters.";
      title.focus();
      return;
    }
    if (names.value.trim() && !addNames()) return;
    view.busy = true;
    clear(message); sync();
    try {
      const result = await apiWrite(path, { expect: baseline.revision, title: title.value.trim(), rows });
      if (!here()) return;
      baseline = result;
      title.value = result.title; rows = result.rows.map(row => ({ ...row }));
      drawRows();
    } catch (error) {
      if (!here()) return;
      if (error.status === 409) conflict = true;
      else message.textContent = `Your checklist couldn't be saved. ${pageFailure(error).message}`;
    } finally {
      view.busy = false;
      if (here()) sync();
    }
  }
  async function reloadSaved() {
    view.busy = true;
    clear(message); sync();
    try {
      const result = await api(path);
      if (here()) {
        view.busy = false;
        drawUpgradeChecklist(view, result);
      }
    } catch (error) {
      if (here()) clear(message).append(loadFailed("Your saved checklist", error));
    } finally {
      view.busy = false;
      if (here()) sync();
    }
  }
  async function copyBuys(event) {
    if (!active(event.currentTarget) || !buyList.value) return;
    const text = buyList.value;
    try {
      await navigator.clipboard.writeText(text);
      if (here() && !confirming && buyList.value === text) message.textContent = "Buy list copied.";
    } catch (_) {
      if (!here() || confirming || buyList.value !== text) return;
      buyList.focus(); buyList.select();
      message.textContent = "Buy list selected. Use your device’s Copy action.";
    }
  }
  function edit() { if (here()) { clear(message); sync(); } }
  title.addEventListener("input", edit);
  names.addEventListener("input", edit);
  add(root, [deck ? el("p", { text: deck.summary.title }) : null,
    el("p", { class: "sub", text: "Your private checklist works with just card names. Save it to pick up on another device." }),
    deckPicker, deck ? null : field("Deck name (optional)", title), field("Card names, one copy per line", names),
    el("div", { class: "actions" }, addButton), progress, message, reload, totals, buyField, list]);
  clear(sheet.body).append(root);
  clear(sheet.foot).append(close, copy, save);
  const discardPanel = el("div", { class: "sheet-body", hidden: true },
    el("p", { text: "Close without saving your checklist changes?" }));
  const keep = el("button", { type: "button", class: "btn btn-primary", text: "Keep editing", onclick: () => {
    if (!here() || !confirming) return;
    confirming = false; discardPanel.hidden = true; root.hidden = sheet.foot.hidden = false;
    (deck ? names : title).focus();
  } });
  discardPanel.append(el("div", { class: "actions" }, keep,
    el("button", { type: "button", class: "btn btn-discard", text: "Discard changes", onclick: event => {
      if (here() && confirming && discardPanel.contains(event.currentTarget)) sheet.close();
    } })));
  sheet.body.append(discardPanel);
  sheet.beforeDismiss = () => {
    if (!here()) return true;
    if (view.busy) return false;
    if (!dirty()) return true;
    confirming = true; root.hidden = sheet.foot.hidden = true; discardPanel.hidden = false;
    keep.focus(); return false;
  };
  drawRows(); sync();
  if (seed.length) addCopies(seed);
}

/** Names and copy counts come from the displayed deck list, independent of collection records. */
function upgradeDeckCards(deck, active, addCopies) {
  const counts = new Map();
  for (const lines of Object.values(deck.sections)) {
    for (const { name, qty } of lines) {
      if (name && Number.isSafeInteger(qty) && qty > 0) counts.set(name, (counts.get(name) || 0) + qty);
    }
  }
  if (!counts.size) return null;
  const cards = Array.from(counts).sort(([a], [b]) => a.localeCompare(b));
  const amount = el("input", { type: "number", min: 1, max: 1, step: 1, value: "1", inputmode: "numeric" });
  const choose = el("select", { onchange: () => {
    amount.max = Math.min(counts.get(choose.value) || 1, UPGRADE_MAX_COPIES);
    amount.value = "1";
  } }, el("option", { value: "", text: "Choose a card" }),
  cards.map(([name, qty]) => el("option", { value: name, text: `${name} (${qty})` })));
  const error = el("p", { class: "sub", role: "status" });
  const add = el("button", { type: "button", class: "btn", text: "Add from list", onclick: event => {
    if (!active(event.currentTarget)) return;
    const name = choose.value, qty = Number(amount.value);
    clear(error);
    if (!counts.has(name) || !Number.isSafeInteger(qty) || qty < 1 || qty > Number(amount.max)) {
      error.textContent = "Choose a card and a quantity from its listed copies.";
      (name ? amount : choose).focus();
      return;
    }
    if (addCopies(Array(qty).fill(name))) choose.focus();
  } });
  return el("fieldset", { class: "upgrade-checklist-picker" },
    el("legend", { text: "Add cards from this list" }),
    el("label", { class: "field" }, el("span", { text: "Card" }), choose),
    el("label", { class: "field" }, el("span", { text: "Copies" }), amount),
    add, error);
}
