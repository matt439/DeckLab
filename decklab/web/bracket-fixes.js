/* Minimum cuts change counted facts, not a deck's actual bracket. Selection stays in this view. */
"use strict";

function bracketFixesPart(data, level = 3) {
  const target = data.summary?.target_bracket, bracket = data.stats?.commander?.bracket;
  if (!Number.isInteger(target) || !bracket) return null;
  const fixes = bracket.fixes;
  if (fixes?.checked && !fixes.cuts) return null;
  const root = el("section", { class: "bracket-fixes" }, el(`h${level}`, { text: `To fit Bracket ${target}` }));
  if (!fixes?.checked || !Array.isArray(fixes.plans) || !fixes.plans.length) {
    root.append(el("p", { class: "sub", text: fixes?.reason || "The fewest cuts can't be checked from this answer. The tag and combo counts may be incomplete." }));
    return root;
  }
  const token = routeToken, profile = state.profile, profileId = profile?.id, profileSpace = profile?.space || HOME_SPACE;
  const summary = data.summary, id = summary.id, version = data.version || "target", main = document.getElementById("main");
  const title = summary.title, space = summary.space || deckSpaceOf(id);
  const ownsAddress = () => { const here = parseHash(); return here.path === "deck" && sameDeckId(addressDeckId(here.params.get("id"))) === sameDeckId(id)
    && (here.params.get("v") === "owned" ? "owned" : "target") === version; };
  const current = (control = null) => routeToken === token && ownsAddress() && state.profile === profile
    && state.profile?.id === profileId && (state.profile?.space || HOME_SPACE) === profileSpace
    && data.summary === summary && summary.id === id && summary.title === title && summary.target_bracket === target
    && (data.version || "target") === version && data.stats?.commander?.bracket?.fixes === fixes
    && root.isConnected && document.getElementById("main") === main && main.contains(root)
    && (!control || control.isConnected && root.contains(control) && !document.querySelector("dialog[open]") && keyboardShown(control));
  const editable = () => Boolean(profile && fixes.receipt && seesInventory(space) && canEditDeck(summary));
  let index = 0, selected = new Set(), sequence = 0;
  const content = el("div", { class: "bracket-fix-options" }), output = el("div", { class: "bracket-fix-replacements" });
  const select = el("select", { "aria-label": "Minimum-cut option", onchange: () => {
    if (!current(select)) return;
    const next = Number(select.value);
    if (!Number.isInteger(next) || next < 0 || next >= fixes.plans.length) return;
    index = next; sequence++; clear(output); draw();
  } }, fixes.plans.map((plan, i) => el("option", { value: String(i), text: `Option ${i + 1}: counted minimum ${plan.after_minimum}` })));
  add(root, [el("p", { text: `Fewest cards to cut from these counts: ${num(fixes.cuts)}. Remove all copies of each chosen card.` }),
    el("p", { class: "sub", text: fixes.note }), fixes.plans.length > 1 ? el("label", { class: "field" }, "Minimum options (examples)", select) : null, content, output]);
  const chosen = () => [...selected].sort();
  const choiceValid = () => { const plan = fixes.plans[index]; return selected.size === fixes.cuts
    && plan.fixed.every(name => selected.has(name)) && (!plan.choose || chosen().filter(name => !plan.fixed.includes(name)).length === plan.choose.count); };
  const askReplacements = async (name, button) => {
    if (!current(button) || !editable() || !choiceValid() || !selected.has(name) || button.disabled) return;
    const own = ++sequence, cutKey = JSON.stringify(chosen()); button.disabled = true;
    clear(output).append(loadingBox("Checking free replacements against these cuts…", { small: true }));
    try {
      const answer = await apiWrite("/api/deck/bracket-replacements", { id, version, sha256: fixes.receipt, target, cuts: chosen(), card: name });
      if (!current() || own !== sequence || cutKey !== JSON.stringify(chosen()) || !editable()) return;
      clear(output).append(el(`h${level + 1}`, { text: `Free replacements for ${name}` }), el("p", { class: "sub", text: answer.note }),
        answer.candidates?.length ? el("ul", { class: "swap-list" }, answer.candidates.map(candidate => {
          const safe = candidate.fit === "safe", legal = candidate.one_swap_legal === true;
          const button = el("button", { type: "button", class: "btn", text: "Test this swap", disabled: !safe || !legal || null, onclick: () => {
            if (!current(button) || !editable() || own !== sequence || cutKey !== JSON.stringify(chosen())) return;
            testReplacementSwap(data, { name }, { ...candidate, expected_sha256: fixes.receipt }, button,
              () => current(button) && editable() && own === sequence && cutKey === JSON.stringify(chosen()));
          } });
          return el("li", {}, cardRow(candidate.card, { name: candidate.name, meta: swapCandidateMeta(candidate), viewerGroup: "bracket-replacements" }),
            el("p", { class: "sub", text: candidate.fit_note }),
            !safe ? status(candidate.fit === "unsafe" ? "warn" : "info", candidate.fit === "unsafe" ? "Would raise the counted minimum again" : "Counted minimum unknown") : null,
            !legal ? el("p", { class: "sub", text: "Check the commander and deck rules before testing this slot." }) : null, button);
        })) : el("p", { class: "sub", text: "No free replacement fits this slot. Choose one in the editor and check the full list." }));
      if (answer.more) output.append(el("p", { class: "sub", text: `${plural(answer.more, "more card fits", "more cards fit")}; the closest replacements are shown.` }));
    } catch (error) {
      if (current() && own === sequence && cutKey === JSON.stringify(chosen())) {
        if (error.status === 409) {
          const refresh = el("button", { type: "button", class: "btn", text: "Reload deck counts", onclick: () => {
            if (current(refresh) && editable()) route();
          } });
          clear(output).append(el("p", { text: "The deck or its checked counts changed. Reload the deck counts before choosing replacements." }), refresh);
        } else clear(output).append(loadFailed("Bracket-safe replacements", error, () => askReplacements(name, button)));
      }
    } finally { if (current() && button.isConnected && editable() && choiceValid() && selected.has(name)) button.disabled = false; }
  };
  function draw() {
    const plan = fixes.plans[index]; selected = new Set(plan.fixed);
    const buttons = [], statusLine = el("p", { class: "sub", "aria-live": "polite" });
    const sync = () => { for (const { button, name } of buttons) button.disabled = !choiceValid() || !selected.has(name);
      statusLine.textContent = plan.choose && !choiceValid() ? `Choose exactly ${plan.choose.count} of these ${plan.choose.names.length} Game Changers for this cut option.`
        : `With these cuts, the counted minimum would be Bracket ${plan.after_minimum}, within the target. This does not name the deck's bracket.`; };
    const row = (name, choice) => {
      const check = choice ? el("input", { type: "checkbox", "aria-label": `Cut ${name}`, onchange: () => {
        if (!current(check)) { check.checked = selected.has(name); return; }
        if (check.checked) selected.add(name); else selected.delete(name);
        sequence++; clear(output); sync();
      } }) : null;
      const button = editable() ? el("button", { type: "button", class: "btn btn-quiet", text: "Free replacements", onclick: () => askReplacements(name, button) }) : null;
      if (button) buttons.push({ button, name });
      return el("li", { class: "bracket-cut-row" }, check ? el("label", { class: "bracket-cut-check" }, check) : null,
        el("span", {}, cardLink({ name }, "bracket-fixes", { inline: true })), button);
    };
    add(clear(content), [plan.fixed.length ? el("p", { text: "Cut these cards in this option:" }) : null,
      plan.fixed.length ? el("ul", { class: "bracket-cut-list" }, plan.fixed.map(name => row(name, false))) : null,
      plan.choose ? el("p", { text: `Any ${plan.choose.count} of these ${plan.choose.names.length} Game Changers:` }) : null,
      plan.choose ? el("ul", { class: "bracket-cut-list" }, plan.choose.names.map(name => row(name, true))) : null, statusLine]);
    sync();
  }
  draw(); return root;
}
