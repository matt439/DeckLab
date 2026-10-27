/* Opponent-specific plans on the deck Overview. The play API filters records for the viewer;
 * card pictures come from each plan's historical list, independently of today's deck cards. */
"use strict";

function deckSideboardSection(data) {
  if (!state.profile || data.summary.id.startsWith(BOX_PREFIX)) return null;
  const body = el("div", { class: "deck-sideboard-body" });
  const section = el("section", { class: "deck-section deck-sideboard", id: "sec-sideboard", "aria-labelledby": "h-sideboard" },
    el("h2", { id: "h-sideboard", text: "Sideboard plan" }), body);
  const ctx = { section, body, data, token: routeToken, profile: state.profile.id, selected: null, generation: 0 };
  deckSideboardLoad(ctx);
  return section;
}

function deckSideboardHere(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.section.isConnected;
}

async function deckSideboardLoad(ctx) {
  const generation = ++ctx.generation;
  clear(ctx.body).append(loadingBox("Loading sideboard plans…"));
  try {
    const answer = await api(`/api/play?id=${encodeURIComponent(ctx.data.summary.id)}`);
    if (!deckSideboardHere(ctx) || generation !== ctx.generation) return;
    deckSideboardDraw(ctx, answer);
  } catch (failure) {
    if (!deckSideboardHere(ctx) || generation !== ctx.generation) return;
    add(clear(ctx.body), [el("div", { class: "box box-warn" },
      el("p", { text: "Sideboard plans couldn't be loaded. " + failure.message }),
      el("button", { class: "btn", type: "button", text: "Try again", onclick: () => deckSideboardLoad(ctx) })),
    deckSideboardNotes(ctx.data)]);
  }
}

/** Match direction and both list versions before preferring an exact current pair. The API sorts
 * newest first; if none matches today's hashes, keep the newest recorded plan with its warning. */
function deckSideboardMatch(answer, data, opponent) {
  // A hidden opponent (another space's private deck, E10-S32) has no id or version: it is one plan's own entry.
  if (opponent.hidden || opponent.removed) return answer.sideboards.find(({ record }) => record.id === opponent.plan) || null;
  const candidates = answer.sideboards.filter(({ record }) => record.deck.id === data.summary.id
    && record.deck.version === data.version && record.opponent.id === opponent.id && record.opponent.version === opponent.version);
  const own = answer.lists.find(list => list.id === data.summary.id && list.version === data.version);
  return candidates.find(({ record }) => record.deck.sha256 === own?.sha256 && record.opponent.sha256 === opponent.sha256)
    || candidates[0] || null;
}

function deckSideboardDraw(ctx, answer) {
  clear(ctx.body);
  const { data } = ctx;
  const own = answer.lists.find(list => list.id === data.summary.id && list.version === data.version);
  const opponents = answer.lists.filter(list => list.id !== data.summary.id);
  // A deleted opponent's recorded plan remains useful, but cannot be revised against a current list.
  for (const { record } of answer.sideboards) {
    if (record.deck.id !== data.summary.id || record.deck.version !== data.version) continue;
    if (record.opponent.hidden || record.opponent.removed) {
      // No id, version or hash to tell two private opponents apart: each plan is its own choice.
      opponents.push({ ...record.opponent, historical: true, plan: record.id, saved: (record.updated_on || "").slice(0, 10) });
      continue;
    }
    if (!opponents.some(list => list.id === record.opponent.id && list.version === record.opponent.version)) {
      opponents.push(answer.lists.find(list => list.id === record.opponent.id && list.version === record.opponent.version)
        || { ...record.opponent, historical: true });
    }
  }
  // No other list and no saved plan: nothing to choose, so no picker.
  if (!opponents.length) {
    add(ctx.body, [emptyBox("No other decks to plan against yet."), deckSideboardNotes(data)]);
    deckSideboardWarnings(ctx, answer);
    return;
  }
  const picker = el("select", { "aria-label": "Opponent's deck and list" },
    el("option", { value: "", text: "Choose an opponent" }),
    opponents.map((list, i) => el("option", { value: String(i),
      text: playListWords(list) + (list.hidden || list.removed ? ` (${list.removed ? "removed" : "private"} deck; plan saved ${list.saved || "earlier"})`
        : list.historical ? " (recorded list; deck unavailable)" : "") })));
  const remembered = opponents.findIndex(list => ctx.selected && (list.hidden || list.removed ? list.plan === ctx.selected.plan
    : !ctx.selected.plan && list.id === ctx.selected.id && list.version === ctx.selected.version));
  picker.value = remembered < 0 ? "" : String(remembered);
  const plan = el("div", { class: "deck-sideboard-plan", "aria-live": "polite" });
  const redraw = () => {
    clear(plan);
    const opponent = picker.value === "" ? null : opponents[Number(picker.value)];
    ctx.selected = opponent && (opponent.hidden || opponent.removed ? { plan: opponent.plan } : { id: opponent.id, version: opponent.version });
    const entry = opponent && deckSideboardMatch(answer, data, opponent);
    // A hidden opponent can't be checked against its current list (as on the Game log): only this deck's is.
    const current = entry && own && entry.record.deck.sha256 === own.sha256
      && (opponent.hidden || opponent.removed || (!opponent.historical && entry.record.opponent.sha256 === opponent.sha256));
    if (!opponent) {
      add(plan, [noneSelected("Choose an opponent to see a saved plan."), deckSideboardNotes(data)]);
      return;
    }
    const canMake = own && !opponent.historical && (answer.decks[own.id]?.can_record || answer.decks[opponent.id]?.can_record);
    const canRevise = entry && entry.editable && own && (!opponent.historical || opponent.removed);
    const action = (entry ? canRevise : canMake) ? el("button", { type: "button", class: "btn", text: entry ? "Revise this plan" : "Make a sideboard plan",
      onclick: () => {
        if (!deckSideboardHere(ctx)) return;
        playPlanForm(answer, data.summary.id, entry, { deck: own, opponent,
          onSaved: () => { if (deckSideboardHere(ctx)) deckSideboardLoad(ctx); } });
      } }) : null;
    // No plan yet: Make a sideboard plan sits in the empty state with its line, and the notes come after.
    if (entry) add(plan, [deckSideboardPlan(entry, current), action]);
    else add(plan, [emptyBox("No saved plan against this deck yet.", action), deckSideboardNotes(data)]);
  };
  picker.addEventListener("change", redraw);
  ctx.body.append(playField("Opponent's deck and list", picker), plan);
  deckSideboardWarnings(ctx, answer);
  redraw();
}

function deckSideboardWarnings(ctx, answer) {
  if (answer.warnings.length) ctx.body.append(el("details", { class: "play-snapshots" },
    el("summary", { text: "Some lists or records couldn't be shown" }),
    el("ul", {}, answer.warnings.map(text => el("li", { text })))));
}

function deckSideboardPlan(entry, current) {
  const plan = entry.record;
  const sides = ["out", "in"].map(direction => {
    const lines = entry.cards?.[direction] || plan[direction];
    return el("div", { class: "deck-sideboard-moves" }, el("h3", { text: direction === "out" ? "Out of main deck" : "In from sideboard" }),
      el("div", { class: "card-tiles" }, lines.map(line => cardTile(line.card, { name: line.name, qty: line.qty, finish: line.finish,
        meta: [line.set && line.set.toUpperCase(), line.number].filter(Boolean).join(" ") || null,
        viewerGroup: `sideboard-${plan.id}`, caption: `${line.qty} × ${line.name} · ${direction === "in" ? "In" : "Out"}` }))));
  });
  return el("div", { class: "deck-sideboard-saved" },
    current ? null : el("p", { class: "box box-warn", text: "A decklist has changed since this plan was saved. Check these swaps against the current lists before using it." }),
    el("div", { class: "play-sides" }, sides),
    plan.notes ? el("p", { class: "play-note", text: plan.notes }) : null,
    el("p", { class: "sub", text: `Revision ${plan.revision}; last saved by ${plan.updated_by}.` }));
}

function deckSideboardNotes(data) {
  const parts = (data.guide?.sections || []).filter(part => /^sideboard\b/i.test(part.title));
  if (!parts.length) return null;
  return el("div", { class: "deck-sideboard-notes" },
    data.guide.changed_on ? el("p", { class: "note note-warn", text: `The list changed on ${data.guide.changed_on}, so these notes may be out of date.` }) : null,
    parts.map(part => el("div", {}, el("h3", { text: part.title }), guideMarkdown(part.markdown))));
}
