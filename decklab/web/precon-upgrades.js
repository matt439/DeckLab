/* A published precon is the baseline. The preview and draft use the current saved Planned list. */
"use strict";

function preconUpgradePanel(sides) {
  const deck = sides.find(side => side.version === "target" && side.may_upgrade_precon);
  const stock = sides.find(side => side.comparison?.kind === "precon" && side.summary.kind === "commander");
  if (!deck || !stock || !state.profile?.id) return null;
  const token = routeToken, hash = location.hash, profile = state.profile;
  return comparePart("h-precon-upgrades", "Upgrade this precon",
    el("p", { class: "sub", text: "Look for a low-cost answer you can add from your free copies. Each idea swaps one card in today's Planned list." }),
    el("button", { type: "button", class: "btn", text: "Find early interaction…", onclick: event => {
      if (token === routeToken && hash === location.hash && profile === state.profile && event.currentTarget.isConnected) {
        openPreconUpgradeReview(deck, stock);
      }
    } }));
}

function openPreconUpgradeReview(deck, stock) {
  const sheet = openSheet({ title: "More early interaction", side: true });
  const token = routeToken, hash = location.hash, profile = state.profile, main = $("#main");
  const id = deck.summary.id, file = stock.comparison.file;
  const here = () => !sheet.closed && sheet.dialog.isConnected && sheet.dialog.getAttribute("open") !== null
    && token === routeToken && hash === location.hash && profile === state.profile && main.isConnected && $("#main") === main;
  const active = control => here() && control.isConnected && sheet.body.contains(control) && keyboardDialog() === sheet.dialog;
  const results = el("div", { class: "small-swap-results" });
  const message = el("p", { class: "sub", role: "status", "aria-live": "polite" });
  let reviewing = false;
  async function review(response, proposal, button, test) {
    if (!active(button) || reviewing) return;
    reviewing = true;
    button.disabled = true;
    try {
      const view = await api(`/api/deck/edit?id=${encodeURIComponent(id)}`);
      if (!active(button)) return;
      if (view.id !== id || view.may_save === false || view.sha256 !== response.sha256) {
        message.textContent = "The deck changed or can no longer be edited. Ask for fresh ideas.";
        return;
      }
      const draft = preconUpgradeDraft(view, proposal);
      if (!draft) {
        message.textContent = "This swap no longer fits the Planned list. Ask for fresh ideas.";
        return;
      }
      const key = draftKey({ mode: "edit", profile: profile.id, id, version: "target" });
      const previous = local.get(key);
      if (previous) {
        const choice = await ask("Replace your unsaved changes?", ["Replace the unsaved Planned draft with this upgrade idea?"],
          [{ text: "Keep my changes", value: "keep" }, { text: "Replace them", kind: "primary", value: "replace" }]);
        if (choice !== "replace" || !active(button) || local.get(key) !== previous) return;
      }
      if (!local.set(key, JSON.stringify(draft))) {
        message.textContent = "The idea couldn't be kept on this device. Make the swap in the editor instead.";
        return;
      }
      sheet.close();
      location.hash = `${editHref(id, "target")}${test ? "&test=change" : ""}`;
    } catch (error) {
      if (active(button)) message.textContent = "The deck couldn't load for review. Try again.";
    } finally {
      reviewing = false;
      if (here()) button.disabled = false;
    }
  }
  async function loadIdeas() {
    if (!here()) return;
    clear(results).append(loadingBox("Checking free copies and the Planned list…", { small: true }));
    try {
      const response = await apiWrite("/api/deck/precon-upgrades", { id, file, goal: "early-interaction" });
      if (!here()) return;
      clear(results);
      if (response.deck_id !== id || response.file !== file) {
        results.append(emptyBox("The deck or precon selection changed. Open the upgrade ideas again."));
      } else if (response.proposals.length) {
        response.proposals.forEach((proposal, index) => {
          const actions = [["Review in editor", false], ["Test this change", true]].map(([label, test]) =>
            el("button", { type: "button", class: "btn", text: label,
              onclick: event => review(response, proposal, event.currentTarget, test) }));
          const heading = `${sheet.heading.id}-idea-${index}`;
          results.append(el("section", { class: "box small-swap-proposal", "aria-labelledby": heading },
            el("h3", { id: heading, text: `Try ${proposal.add.name} for ${proposal.cut.name}` }),
            cardRow(proposal.cut.card, { qty: 1, name: proposal.cut.name,
              meta: proposal.stock_cut ? "Cut from the stock precon" : "Cut from the current Planned list", viewerGroup: "precon-upgrades" }),
            cardRow(proposal.add.card, { qty: 1, name: proposal.add.name,
              meta: `Add 1 · ${plural(proposal.free, "free copy", "free copies")} on hand`, viewerGroup: "precon-upgrades" }),
            el("p", { text: proposal.reason }), el("p", { text: proposal.trade_off }),
            el("p", { class: "sub", text: preconUpgradeBracket(response, proposal) }),
            el("div", { class: "small-swap-actions" }, actions)));
        });
      } else {
        results.append(emptyBox(response.reason || "There are no upgrade ideas for this list."));
      }
    } catch (error) {
      if (here()) clear(results).append(loadFailed("Upgrade ideas", error, loadIdeas));
    }
  }
  sheet.body.append(el("p", { class: "sub", text: `${stock.summary.title} · Published precon` }), message, results);
  sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }]);
  loadIdeas();
  return sheet;
}

function preconUpgradeBracket(response, proposal) {
  const before = response.before_minimum, after = proposal.after_minimum, target = response.target_bracket;
  const start = "The swapped list passes Deck Lab's Commander rules checks.";
  if (after == null) return `${start} The bracket floor couldn't be checked from the available data.`;
  const comparison = before == null ? `The new bracket floor is ${after}.`
    : before === after ? `The bracket floor stays at ${after}.` : `The bracket floor changes from ${before} to ${after}.`;
  return `${start} ${comparison}${target != null ? ` Your target is Bracket ${target}.` : ""}`;
}

function preconUpgradeDraft(view, proposal) {
  const lists = view.lists?.target, considering = view.lists?.considering;
  if (proposal.add?.qty !== 1 || proposal.cut?.qty !== 1 || !Array.isArray(lists?.Deck) || !Array.isArray(considering)) return null;
  const index = lists.Deck.findIndex(line => line.qty > 0 && smallSwapSameLine(line, proposal.cut));
  const name = proposal.add.card?.name || proposal.add.name;
  if (index < 0 || Object.values(lists).some(lines => lines.some(line => (line.card?.name || line.name) === name))) return null;
  const changed = [...lists.Deck], cut = changed[index];
  if (cut.qty === 1) changed.splice(index, 1);
  else changed[index] = { ...cut, qty: cut.qty - 1 };
  changed.push(proposal.add);
  const fields = pickFields(view.fields), prose = proseOf(view);
  return { v: 1, saved: Date.now(), sha256: view.sha256, starting: false,
    base: { lists, fields, prose, considering }, lists: { ...lists, Deck: changed }, fields, prose, considering, addSection: "Deck" };
}
