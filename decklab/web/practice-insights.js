/* Optional goldfish detail and bounded one-basic trials; no deck or inventory writes. */
"use strict";

function practiceInsightsOwner(root, data) {
  const token = routeToken, profile = state.profile, profileId = profile?.id, space = profile?.space || HOME_SPACE;
  const summary = data.summary, id = summary.id, version = data.version || "target", main = document.getElementById("main");
  return (control = null) => {
    const here = parseHash();
    return token === routeToken && state.profile === profile && state.profile?.id === profileId
      && (state.profile?.space || HOME_SPACE) === space && data.summary === summary && summary.id === id
      && (data.version || "target") === version && here.path === "deck"
      && sameDeckId(addressDeckId(here.params.get("id"))) === sameDeckId(id)
      && (here.params.get("v") === "owned" ? "owned" : "target") === version
      && document.getElementById("main") === main && root.isConnected && main?.contains(root)
      && (!control || control.isConnected && root.contains(control) && !document.querySelector("dialog[open]"));
  };
}

function practiceCommanderPanel(result, r) {
  if (result.kind !== "commander") return null;
  const root = el("section", { class: "panel", "aria-labelledby": "h-practice-commanders" },
    el("h3", { id: "h-practice-commanders", text: "Commander timing" }),
    el("p", { class: "sub", text: "Simulation estimate: the earliest affordable first cast under the model's fixed casting choices. This isn't advice about when to play a commander; no opponent, commander tax or recasts are modelled." }));
  if (!r.commanders?.length) {
    root.append(el("p", { text: "Commander timing couldn't be checked for this list." }));
    return root;
  }
  for (const row of r.commanders) root.append(el("h4", {}, cardLink({ name: row.name })),
    el("div", { class: "tiles" }, tile("Average first turn", num(row.average_turn, 2), "among games with a cast"),
      tile(`Not by turn ${result.turns}`, pct(row.never), "of all simulated games")),
    numbersTable("First cast by turn", ["Turn", "Cast by then"], (row.by_turn || []).map(turn => [String(turn.turn), pct(turn.chance)])));
  return root;
}

function practiceCastability(r) {
  const rows = (r.castability || []).filter(row => row.blocked_turns > 0).slice(0, 5);
  return el("details", { class: "more practice-castability" }, el("summary", { text: "Spells the mana fails most" }),
    el("p", { class: "sub", text: "Simulation estimate, highest colour-wait share first. Each spell name counts once per turn held with enough total mana; only unpayable colours count as a wait. Average wait counts blocked turns in games with a wait. Commanders waiting in the command zone are separate." }),
    rows.length ? el("ul", { class: "sources-list" }, rows.map(row => el("li", {}, cardLink({ name: row.name }),
      `: ${pct(row.blocked_share)} — ${thousands(row.blocked_turns)} of ${thousands(row.enough_mana_turns)} turns held with enough mana; ` +
      `${num(row.average_wait, 2)} blocked turns on average in ${plural(row.games_waited, "game")} with a wait.`)))
      : el("p", { text: r.castability ? "No held spell had a measured colour wait in these games." : "Per-spell colour waits weren't measured in this result." }));
}

function practiceCategoryPanel(result, r, data) {
  if (!r.categories?.length) return null;
  const root = el("section", { class: "panel practice-category" }, el("h3", { text: "Category casts" }));
  const current = practiceInsightsOwner(root, data);
  const output = el("p", { role: "status", "aria-live": "polite" });
  const category = el("select", { "aria-label": "Cast category" }, r.categories.map((row, i) =>
    el("option", { value: String(i), text: row.name })));
  const count = el("select", { "aria-label": "Category cards cast" });
  const turn = el("select", { "aria-label": "Category cast by turn" }, Array.from({ length: result.turns }, (_, i) =>
    el("option", { value: String(i + 1), text: `Turn ${i + 1}` })));
  category.value = "0"; turn.value = String(Math.min(4, result.turns));
  const selected = () => r.categories[Number(category.value)];
  const show = () => {
    const row = selected(), n = Number(count.value), t = Number(turn.value);
    if (!row || !Number.isInteger(n) || n < 1 || n > row.cards || !Number.isInteger(t) || t < 1 || t > result.turns) return;
    if (!row.checked || !row.by_turn) { output.textContent = "This category contains unreadable cards, so its cast rate wasn't checked."; return; }
    const chance = row.by_turn.find(value => value.turn === t)?.at_least?.[n - 1];
    output.textContent = chance == null ? "That category cast rate wasn't measured." :
      `${pct(chance)} of games cast at least ${n} ${row.name} ${n === 1 ? "card" : "cards"} by turn ${t}. ${row.spells} of its ${row.cards} cards are modelled spells.`;
  };
  const counts = () => {
    clear(count).append(...Array.from({ length: selected()?.cards || 0 }, (_, i) =>
      el("option", { value: String(i + 1), text: `At least ${i + 1}` })));
    count.value = "1"; show();
  };
  category.addEventListener("change", () => { if (current(category)) counts(); });
  for (const control of [count, turn]) control.addEventListener("change", () => { if (current(control)) show(); });
  root.append(el("p", { class: "sub", text: "Simulation estimate using this list's categories. Counts physical cards cast from Commander and Deck only. Playing a land isn't casting a spell. These controls reuse the saved games." }),
    el("div", { class: "field-grid" }, el("label", { class: "field" }, "Category", category),
      el("label", { class: "field" }, "Count", count), el("label", { class: "field" }, "By turn", turn)), output);
  counts();
  return root;
}

function practiceLandTrialTable(answer, setup) {
  const root = el("div", { class: "practice-land-result" });
  const labels = { stuck: "Stuck games", colour_screw: "Colour-screw turns", colour_waste: "Colour screw with mana left", flood: "Flood turns", mana_used: "Mana used" };
  const delta = value => value == null ? "Not measured" : `${value > 0 ? "+" : ""}${num(value * 100, 2)} pp`;
  const baseline = answer.baseline?.[setup], best = answer.variants?.find(row => row.id === answer.best?.[setup]);
  if (!baseline) return el("p", { text: "These land trials don't include this game setup." });
  root.append(el("p", { text: `${thousands(answer.settings.games)} games per setup and list, ${answer.settings.turns} turns, seed ${answer.settings.seed}. Deltas below are percentage points against the replayed baseline. Lower stuck, colour screw and flood are preferable; mana used has no single preferred direction.` }),
    el("p", { text: answer.note }),
    el("p", { class: "sub", text: best ? `Best change for this setup under the displayed screen: ${best.cut} → ${best.add}.` : "No best change: no fully measured option clears the displayed improvement screen for this setup." }),
    el("p", { class: "sub", text: "Scroll the delta table sideways to compare every measure on a narrow screen." }),
    numbersTable("Replayed baseline", ["Measure", "Baseline"], Object.entries(labels).map(([key, label]) => [label, pct(baseline[key])])),
    el("div", { class: "chance-scroll", role: "region", tabindex: "0", "aria-label": "One-basic land trial deltas" },
      el("table", { class: "data practice-table" }, el("thead", {}, el("tr", {},
        ["One-copy change", ...Object.values(labels)].map(label => el("th", { scope: "col", text: label })))),
      el("tbody", {}, (answer.variants || []).map(row => el("tr", {},
        el("th", { scope: "row", text: `${row.cut} → ${row.add}${row.tapped_land ? " (always-tapped cut)" : ""}` }),
        Object.keys(labels).map(key => el("td", { class: "num", text: delta(row.deltas?.[setup]?.[key]) }))))))));
  add(root, [warningsBox(answer.warnings, "About these land trials")]);
  return root;
}

function practiceLandTrials(result, data, setup) {
  const choices = result.land_trials;
  if (!choices?.cuts?.length || !result.cache_key) return null;
  const root = el("section", { class: "panel practice-land-trials" }, el("h3", { text: "Try one basic land" }));
  const current = practiceInsightsOwner(root, data);
  const output = el("div", { class: "practice-land-output", "aria-live": "polite" });
  let sequence = 0, retry = false;
  const cut = el("select", { "aria-label": "One-basic trial cut" }, choices.cuts.map(name => el("option", { value: name, text: name })));
  cut.value = choices.cuts[0];
  const button = el("button", { type: "button", class: "btn", text: "Run land trials" });
  cut.addEventListener("change", () => { if (!current(cut)) return; sequence++; retry = false; button.disabled = false; clear(output); });
  button.addEventListener("click", async () => {
    if (!current(button) || button.disabled || !choices.cuts.includes(cut.value)) return;
    const own = ++sequence, name = cut.value;
    const active = () => current() && own === sequence && cut.value === name;
    button.disabled = true;
    const progress = practiceProgress(true); clear(output).append(progress.node);
    let first = true;
    try {
      for (;;) {
        const answer = await apiWrite("/api/goldfish/what-if", { id: data.summary.id, version: data.version || "target", cut: name,
          cache_key: result.cache_key, ...(first && retry ? { retry: true } : {}) }, "POST", { poll: !first });
        if (!active()) return;
        if (answer.status === "done") { clear(output).append(practiceLandTrialTable(answer.result, setup)); retry = false; break; }
        if (answer.status === "error") { retry = true; throw new ApiError(0, answer.error); }
        progress.update(answer); first = false;
        await sleep(POLL_MS);
        if (!active()) return;
      }
    } catch (error) {
      if (active()) clear(output).append(el("p", { class: "box box-crit", role: "alert", text: error.message + (error.status === 409 ? " Reload this deck's Practice tab to use its current result." : " You can try again.") }));
    } finally { if (active()) { button.disabled = false; button.textContent = retry ? "Retry land trials" : "Run land trials"; } }
  });
  root.append(el("p", { class: "sub", text: `Choose a named cut: replace one copy with each basic in ${choices.colours.map(colour => ({ W: "white", U: "blue", B: "black", R: "red", G: "green", C: "colourless" })[colour]).join(", ")}. ` +
    (choices.tapped_cut ? `Also compare those basics replacing one ${choices.tapped_cut}, an always-tapped land. ` : "No known always-tapped land is available for the extra comparison. ") +
    `This explicitly replays the baseline and changes on seed ${result.seed}, at up to ${thousands(choices.max_games)} games per setup and list. The deck stays as it is.` }),
    el("label", { class: "field" }, "Replace one copy of", cut), button, output);
  return root;
}
