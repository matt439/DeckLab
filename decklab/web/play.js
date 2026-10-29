/* The Game log (UI-REVIEW.md WP10, INV-17): games played at home, and sideboard plans for a particular
opponent, separate from Forge's simulations. A game is recorded in one tap: two deck pickers (each player's
last deck to start with) and big "Alex won / Sam won / Draw" buttons, with the date, names, mulligans,
sideboard plans and notes under More details. The server still checks every save: a quick record asks for its
review (preview) at once, shows it in a toast with Undo for 8 seconds, and saves it with that review's token
when the time is up (or at once when the page is hidden). Correcting a game and sideboard plans keep their
review step. Results read "<name> won". */
"use strict";

function showPlay(params, token) {
  const id = params.get("id") || "";
  load(`/api/play${id ? `?id=${encodeURIComponent(id)}` : ""}`, token, data => drawPlay(data, id));
}

/** A list's words; a side or opponent the server sent hidden (another space's private deck, E10-S32) has only
 * its space's words ("one of the home decks"): no id, list or version. */
function playListWords(list) { return list.hidden || list.removed ? list.title : `${list.title} · ${listName(list.version, true)}`; }
/** What groups games of the same two lists: a list's hash, or a hidden side's words. */
function playSideKey(side) { return side.removed ? "removed" : side.hidden ? `hidden:${side.title}` : side.sha256; }
function playChoice(list) { return list.removed ? { removed: true, title: "a removed deck" }
  : { id: list.id, version: list.version, sha256: list.sha256 }; }
function playNames(moves) { return moves.map(line => `${line.qty} ${line.name}`).join(", ") || "None"; }
function playResult(record) {
  if (!playLegacyGame(record)) return "Result unavailable";
  const winner = record.sides[record.result === "a" ? 0 : 1];
  return record.result === "draw" ? "Draw" : `${winner.player || winner.title} won`;
}

/** Only the original two-seat schema contributes to 1v1 totals and quick-record defaults. */
function playLegacyGame(record) {
  return !!record && !Object.hasOwn(record, "mode") && !Object.hasOwn(record, "game_version") &&
    Array.isArray(record.sides) && record.sides.length === 2;
}

function playMatchupSummaries(games) {
  const groups = new Map();
  for (const { record } of games) {
    if (!playLegacyGame(record)) continue;
    const sides = [...record.sides].sort((a, b) => playSideKey(a).localeCompare(playSideKey(b)));
    const key = sides.map(playSideKey).join(":");
    if (!groups.has(key)) groups.set(key, { sides, games: 0, wins: [0, 0], draws: 0,
      mirror: playSideKey(sides[0]) === playSideKey(sides[1]), first: record.date, last: record.date });
    const group = groups.get(key); group.games++;
    group.first = [group.first, record.date].sort()[0]; group.last = [group.last, record.date].sort().at(-1);
    if (record.result === "draw") group.draws++;
    else group.wins[sides.findIndex(side => playSideKey(side) === playSideKey(record.sides[record.result === "a" ? 0 : 1]))]++;
  }
  return [...groups.values()];
}

function playSummarySection(games) {
  games = games.filter(entry => playLegacyGame(entry?.record));
  if (!games.length) return null;
  return el("section", { class: "play-section", "aria-labelledby": "play-summary-title" },
    el("h2", { id: "play-summary-title", text: "Head to head" }),
    el("p", { class: "sub", text: "Games with the same two decklists. A revised or sideboarded list starts a new group." }),
    el("div", { class: "play-records" }, playMatchupSummaries(games).map(group => el("article", { class: "panel play-record" },
      el("h3", { text: group.sides.map(side => playListWords(side) + (side.plan_id ? " (sideboarded)" : "")).join(" vs ") }),
      el("p", { text: (group.mirror ? `${plural(group.games, "game")}, both with the same list`
        : `${plural(group.games, "game")}: ${group.sides[0].title} ${plural(group.wins[0], "win")}, ${group.sides[1].title} ${plural(group.wins[1], "win")}`)
        + (group.draws ? `, ${plural(group.draws, "draw")}` : "") + "." }),
      el("p", { class: "sub", text: group.first === group.last ? `Played ${group.first}` : `Played ${group.first} to ${group.last}` }),
      playSnapshotDetails(group.sides)))));
}

/** The Game log's words with no games: a member (a profile of a person's own space) is sent only the games
 * with their own decks (lib/permissions.py's sees_play_record), so theirs say so. */
function playNoGamesWords() {
  const space = state.profile && (state.profile.space || HOME_SPACE);
  return space && space !== HOME_SPACE ? "No games with your decks have been recorded yet."
    : "No games have been recorded yet.";
}

function drawPlay(data, deckId) {
  const games = data.games.filter(entry => playLegacyGame(entry?.record));
  const main = $("#main");
  const filter = el("select", { id: "play-filter", onchange: event => {
    location.hash = `#/play${event.target.value ? `?id=${encodeURIComponent(event.target.value)}` : ""}`;
  } }, el("option", { value: "", text: "Every deck" }));
  const seen = new Set();
  for (const list of data.lists) if (!seen.has(list.id)) {
    seen.add(list.id); filter.append(el("option", { value: list.id, text: list.title, selected: list.id === deckId }));
  }
  const fromDeck = deckId && data.lists.find((list) => list.id === deckId);
  // While there are no plans, the empty state holds this one action instead of the section head.
  const planButton = el("button", { class: "btn", type: "button", text: "New sideboard plan", disabled: !data.lists.length || null,
    hidden: !data.sideboards.length || null, onclick: () => playPlanForm(data, deckId) });
  const recordButton = data.lists.length ? el("button", { type: "button", class: "btn btn-quiet", text: "Record a game",
    onclick: () => { const first = document.getElementById("play-quick-deck-0"); if (first) first.focus(); } }) : null;
  add(main, [
    pageHead({ crumb: fromDeck ? [deckHref(fromDeck.id, fromDeck.version), fromDeck.title] : null, title: routeH1("play"),
      description: "Played games, Commander pods and sideboard plans. Separate from Forge's simulations." }),
    warningsBox(data.warnings, "Some play records or deck lists could not be loaded"),
    data.lists.length ? playQuickRecord(data, deckId) : playWithoutDecks(data),
    el("section", { class: "play-section", "aria-labelledby": "play-games-title" },
      el("div", { class: "play-section-head" }, el("h2", { id: "play-games-title", text: data.pods?.length ? "Played 1v1 games" : "Played games" }),
        data.lists.length && (data.games.length || deckId) ? el("label", { class: "field play-filter", for: "play-filter" },
          el("span", { class: "sr-only", text: "Show games with" }), filter) : null),
      games.length ? el("div", { class: "play-records" }, games.map(entry => playGameCard(entry, data)))
        : emptyBox(data.pods?.length ? "No 1v1 games have been recorded here yet."
          : deckId ? "No games with this deck yet." : playNoGamesWords(), recordButton)),
    playSummarySection(games),
    typeof playPodSection === "function" ? playPodSection(data, deckId) : null,
    el("section", { class: "play-section", "aria-labelledby": "play-plans-title" },
      el("div", { class: "play-section-head" }, el("h2", { id: "play-plans-title", text: "Sideboard plans" }), planButton),
      el("p", { class: "sub", text: "A plan says which cards to swap in against one opponent. It never changes your deck." }),
      data.sideboards.length ? el("div", { class: "play-records" }, data.sideboards.map(entry => playPlanCard(entry, data)))
        : emptyBox("No sideboard plans yet.", data.lists.length ? el("button", { class: "btn", type: "button",
          text: "New sideboard plan", onclick: () => playPlanForm(data, deckId) }) : null))]);
}

function playWithoutDecks(data) {
  const empty = emptyBox("There are no decks to record a game with yet.", createTargets().length && typeof newDeckHref === "function"
    ? el("a", { class: "btn", href: newDeckHref(), text: "New deck" })
    : el("a", { class: "btn", href: "#/library", text: routeFor("library").label }));
  const resume = typeof lifeV2EmptyLauncher === "function" ? lifeV2EmptyLauncher(data) : null;
  if (!resume) return empty;
  const panel = el("div", {}, empty, resume);
  if (typeof lifeV2BindLauncher === "function") lifeV2BindLauncher(panel);
  return panel;
}

/** The two players a quick record is for: the visitor, and the other person of their space (the two home
 * profiles at home), else "Opponent". */
function playPlayers() {
  const me = state.profile || { name: "Player 1" };
  const space = me.space || HOME_SPACE;
  const other = (state.profiles || []).find((p) => p.id !== me.id && (p.space || HOME_SPACE) === space);
  return [me.name, other ? other.name : "Opponent"];
}

/** The index in lists of the list a player last played (newest game first), on its current saved list;
 * -1 when they haven't played one that still exists. skip: a deck id not to choose (the other side's). */
function playLastList(lists, games, player, skip = null) {
  for (const { record } of games) {
    if (!playLegacyGame(record)) continue;
    const side = (record.sides || []).find((s) => s.player === player);
    if (!side || side.id === skip) continue;
    const at = lists.findIndex((l) => l.id === side.id && l.version === side.version);
    if (at >= 0) return at;
  }
  return -1;
}

/** The index in lists of a deck the profile plays, a built one first, then one being built; -1 when there's
 * none. At home that's Played by its plays_as, or "either"; a person's own space (no plays_as) its own decks
 * (ids "<space>/..."). decks: /api/play's {id: {player, status}}. skip: a deck id not to choose. */
function playOwnList(lists, decks, profile, skip = null) {
  if (!profile) return -1;
  const space = profile.space || HOME_SPACE;
  if (!profile.plays_as && space === HOME_SPACE) return -1;
  const rank = (list) => {
    const about = (decks || {})[list.id] || {};
    if (list.version !== "target" || list.id === skip) return 9;
    const whose = profile.plays_as
      ? (about.player === profile.plays_as ? 0 : about.player === "either" ? 3 : 9)
      : (String(list.id).startsWith(`${space}/`) ? 0 : 9);
    return whose + (about.status === "built" ? 0 : about.status === "building" ? 1 : 2);
  };
  let best = -1;
  lists.forEach((list, n) => { if (rank(list) < 9 && (best < 0 || rank(list) < rank(lists[best]))) best = n; });
  return best;
}

/** The decks a quick record starts on, [side 0, side 1] as indexes in data.lists: each player's last deck,
 * else one they play; never the same deck on both sides while there's another. From a deck's page (deckId)
 * that deck goes on the side of the player who plays it (else the visitor's), and the other side moves off it.
 * The visitor's side falls back to a deck they may record a game with (canEditDeck) before any other. */
function playStarts(data, deckId, people, names) {
  const lists = data.lists, games = data.games || [], decks = data.decks || {};
  const strong = (i, skip) => {
    const last = playLastList(lists, games, names[i], skip);
    return last >= 0 ? last : playOwnList(lists, decks, people[i], skip);
  };
  const weak = (i, skip) => {
    const mine = (l) => typeof canEditDeck !== "function"
      || canEditDeck({ id: l.id, player: (decks[l.id] || {}).player });
    let n = i === 0 ? lists.findIndex((l) => l.id !== skip && mine(l)) : -1;
    if (n < 0) n = lists.findIndex((l) => l.id !== skip);
    return n;
  };
  const idOf = (n) => (n >= 0 ? lists[n].id : null);
  const from = deckId ? lists.findIndex((l) => l.id === deckId && l.version === "target") : -1;
  const starts = [-1, -1];
  if (from >= 0) {
    const owner = (decks[deckId] || {}).player;
    const side = people[1] && people[1].plays_as && owner === people[1].plays_as ? 1 : 0;
    starts[side] = from;
    const other = 1 - side;
    starts[other] = strong(other, deckId);
    if (starts[other] < 0) starts[other] = weak(other, deckId);
  } else {
    starts[0] = strong(0, null);
    starts[1] = strong(1, idOf(starts[0]));
    if (starts[0] < 0) starts[0] = weak(0, idOf(starts[1]));
    if (starts[1] < 0) starts[1] = weak(1, idOf(starts[0]));
  }
  return starts.map((n) => (n < 0 ? 0 : n));
}

/** The quick record: each player's deck, More details, and one button per result. */
function playQuickRecord(data, deckId) {
  const lists = data.lists;
  const names = playPlayers();
  const me = state.profile, space = (me && me.space) || HOME_SPACE;
  const people = [me, (state.profiles || []).find((p) => me && p.id !== me.id && (p.space || HOME_SPACE) === space)];
  const starts = playStarts(data, deckId, people, names);
  const error = el("p", { class: "form-error", role: "alert" });
  const date = el("input", { type: "date", id: "play-quick-date", required: true, max: data.today, value: data.today });
  const notes = el("textarea", { id: "play-quick-notes", maxlength: 2000, rows: 2 });
  const sides = names.map((name, i) => {
    const select = el("select", { id: `play-quick-deck-${i}` }, lists.map((list, n) => el("option", { value: String(n),
      selected: n === starts[i], text: playListWords(list) })));
    select.value = String(starts[i]);
    const label = el("span", { text: `${name}'s deck` });
    const legend = el("legend", { text: name });
    const player = el("input", { type: "text", id: `play-quick-name-${i}`, maxlength: 80, required: true, value: name });
    const mulligans = el("input", { type: "number", id: `play-quick-mull-${i}`, min: 0, max: 20, step: 1, value: 0, inputmode: "numeric" });
    const plan = el("select", { id: `play-quick-plan-${i}` });
    return { select, label, legend, player, mulligans, plan, plans: [], get: () => lists[Number(select.value)] };
  });
  const outcomes = [
    el("button", { type: "button", class: "btn play-outcome", "data-result": "a" }),
    el("button", { type: "button", class: "btn play-outcome", "data-result": "b" }),
    el("button", { type: "button", class: "btn play-outcome", "data-result": "draw", text: "Draw" })];
  const relabel = () => sides.forEach((side, i) => {
    const name = side.player.value.trim() || names[i];
    side.label.textContent = `${name}'s deck`;
    side.legend.textContent = name;
    outcomes[i].textContent = `${name} won`;
  });
  const refreshPlans = () => sides.forEach((side, i) => {
    const list = side.get(), opponent = sides[1 - i].get();
    const chosen = side.plan.value;
    side.plans = (data.sideboards || []).filter((item) => list && opponent && item.record.deck.sha256 === list.sha256
      && item.record.opponent.sha256 === opponent.sha256);
    clear(side.plan).append(el("option", { value: "", text: "None: the deck as it is" }));
    side.plans.forEach((item) => side.plan.append(el("option", { value: item.record.id,
      text: `In ${playNames(item.record.in)}; out ${playNames(item.record.out)}` })));
    if (side.plans.some((item) => item.record.id === chosen)) side.plan.value = chosen;
    side.plan.disabled = !side.plans.length;
  });
  sides.forEach((side) => {
    side.select.addEventListener("change", refreshPlans);
    side.player.addEventListener("input", relabel);
  });
  relabel(); refreshPlans();
  const panel = el("section", { class: "panel play-quick", "aria-labelledby": "play-quick-title" },
    el("h2", { id: "play-quick-title", text: "Record a game" }),
    el("div", { class: "play-quick-decks" }, sides.map((side, i) =>
      el("label", { class: "field", for: `play-quick-deck-${i}` }, side.label, side.select))),
    // The life counter (life-counter.js, E4-S26) for these two decks and names.
    typeof lifeCounterLauncher === "function" ? lifeCounterLauncher(data, () => sides.map((side, i) =>
      ({ list: side.get(), name: side.player.value.trim() || names[i] }))) : null,
    el("details", { class: "play-more" }, el("summary", { text: "More details" }),
      el("div", { class: "play-more-body" },
        el("label", { class: "field", for: "play-quick-date" }, el("span", { text: "Date played" }), date),
        el("div", { class: "play-sides" }, sides.map((side, i) => el("fieldset", { class: "play-side" },
          side.legend,
          el("label", { class: "field", for: `play-quick-name-${i}` }, el("span", { text: "Name" }), side.player),
          el("label", { class: "field", for: `play-quick-mull-${i}` }, el("span", { text: "Mulligans" }), side.mulligans),
          el("label", { class: "field", for: `play-quick-plan-${i}` }, el("span", { text: "Sideboard plan" }), side.plan)))),
        el("label", { class: "field", for: "play-quick-notes" }, el("span", { text: "Notes" }), notes))),
    el("div", { class: "play-outcomes", role: "group", "aria-label": "Who won?" }, outcomes),
    error);
  for (const button of outcomes) {
    button.addEventListener("click", () => playQuickSave({ data, sides, date, notes, outcomes, error, button,
      result: button.getAttribute("data-result") }));
  }
  if (typeof lifeV2BindLauncher === "function") lifeV2BindLauncher(panel);
  return panel;
}

/** Records a quick game: the server's review of it (preview) at once, then a toast saying what will be saved,
 * with Undo for 8 seconds (UNDO_MS). The save, with that review's token, goes when the time is up, or at once
 * if the page is hidden first (a phone locked or the tab closed), so a mis-tap can be taken back and nothing
 * is written until then. The result buttons stay disabled while a game waits, so one tap is one game. */
async function playQuickSave({ data, sides, date, notes, outcomes, error, button, result }) {
  const token = routeToken, profile = state.profile && state.profile.id;
  error.textContent = "";
  const payload = { id: null, sha256: null, date: date.value || data.today, result, notes: notes.value,
    sides: sides.map((side) => {
      const value = { ...playChoice(side.get()), player: side.player.value.trim(), mulligans: Number(side.mulligans.value) || 0 };
      const plan = side.plans.find((item) => item.record.id === side.plan.value);
      if (plan) { value.plan_id = plan.record.id; value.plan_sha256 = plan.sha256; }
      return value;
    }) };
  outcomes.forEach((b) => { b.disabled = true; });
  busy(button, "Checking…");
  const current = () => token === routeToken && (state.profile && state.profile.id) === profile;
  const release = () => {
    if (button.isConnected) unbusy(button);
    outcomes.forEach((b) => { b.disabled = false; });
  };
  let review;
  try {
    review = await apiWrite("/api/play/game", { ...payload, preview: true });
  } catch (failure) {
    if (current()) error.textContent = failure.message;
    release();
    return;
  }
  if (!current()) { release(); return; }
  const record = review.record || payload;
  const titles = (record.sides || []).map((side) => side.title).filter(Boolean);
  const words = `${playResult(record)}${titles.length === 2 ? `: ${titles.join(" vs ")}` : ""}.`;
  if (button.isConnected) {                 // "Saving…" until the toast's time is up; Undo puts the words back
    const words = button.dataset.text;
    busy(button, "Saving…");
    button.dataset.text = words;
  }
  let phase = "waiting", timer = null;
  const onHide = () => { if (document.visibilityState === "hidden") save(); };
  const settle = () => {
    clearTimeout(timer);
    document.removeEventListener("visibilitychange", onHide);
  };
  async function save() {
    if (phase !== "waiting") return;
    phase = "saving"; settle();
    if ((state.profile && state.profile.id) !== profile) {        // the chooser moved to someone else
      release();
      toast("The game wasn't saved: the profile changed. Record it again.");
      return;
    }
    try {
      await apiWrite("/api/play/game", { ...payload, id: review.id, preview: false, review_sha256: review.review_sha256 });
      if (token === routeToken && location.hash.startsWith("#/play")) route();
      else release();
      toast("Game saved.");
    } catch (failure) {
      release();
      if (current() && error.isConnected) error.textContent = failure.message;
      else toast(`The game couldn't be saved: ${failure.message}`);
    }
  }
  const undo = () => {
    if (phase !== "waiting") return;
    phase = "cancelled"; settle(); release();
    if (button.isConnected) button.focus();
  };
  timer = setTimeout(save, UNDO_MS);
  document.addEventListener("visibilitychange", onHide);
  showToast(`Saving the game: ${words}`, { undo });
}

function playSnapshotDetails(snapshots) {
  const lineText = line => `${line.qty} ${line.name}`
    + (line.set ? ` (${line.set.toUpperCase()})${line.number ? ` ${line.number}` : ""}` : "")
    + (line.finish === "foil" ? " *F*" : line.finish === "etched" ? " *E*" : "");
  const shown = snapshots.filter(list => !list.hidden && !list.removed && list.sections);
  if (!shown.length) return null;
  return el("details", { class: "play-snapshots" }, el("summary", { text: "Recorded decklists" }),
    shown.map(list => el("div", {}, el("h4", { text: playListWords(list) }),
      el("pre", { text: Object.entries(list.sections).map(([section, lines]) => section + "\n"
        + lines.map(lineText).join("\n")).join("\n\n") }))));
}

function playGameCard(entry, data) {
  const record = entry.record;
  const mulligans = record.sides.filter((side) => side.mulligans)
    .map((side) => `${side.player} took ${plural(side.mulligans, "mulligan")}`);
  return el("article", { class: "panel play-record" },
    el("div", { class: "play-record-head" }, el("h3", { text: playResult(record) }),
      el("span", { class: "sub", text: playDay(record.date) })),
    el("p", {}, record.sides.map((side, i) => [i ? " vs " : "", el("strong", { text: side.title }), side.player ? ` (${side.player})` : "",
      side.version === "owned" ? `, ${listName("owned", true)}` : "", side.plan_id ? ", sideboarded" : ""])),
    mulligans.length ? el("p", { class: "sub", text: mulligans.join("; ") + "." }) : null,
    record.notes ? el("p", { class: "play-note", text: record.notes }) : null,
    playSnapshotDetails(record.sides),
    playMayCorrect(entry) ? el("button", { class: "btn btn-quiet", type: "button", text: "Correct this game",
      onclick: () => playGameForm(data, "", entry) }) : null);
}

/** What the viewer may change of a game (the server's "can": its own space's sides, and the date, result and
 * notes when its space recorded the game); everything when an older server sent none. */
function playRights(entry) {
  return (entry && entry.can) || { sides: [true, true], result: true };
}

function playMayCorrect(entry) {
  const can = playRights(entry);
  return can.result || can.sides.some(Boolean);
}

const PLAY_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "5 Oct" ("5 Oct 2025" in another year) for a game's YYYY-MM-DD date; the text as it is otherwise. */
function playDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso || "";
  const year = Number(m[1]);
  return `${Number(m[3])} ${PLAY_MONTHS[Number(m[2]) - 1]}${year === new Date().getFullYear() ? "" : ` ${year}`}`;
}

function playPlanCard(entry, data) {
  const plan = entry.record;
  // A hidden opponent (another space's private deck) can't be checked against its current list.
  const current = data.lists.some(list => list.id === plan.deck.id && list.version === plan.deck.version && list.sha256 === plan.deck.sha256)
    && (plan.opponent.hidden || plan.opponent.removed || data.lists.some(list => list.id === plan.opponent.id && list.version === plan.opponent.version
      && list.sha256 === plan.opponent.sha256));
  return el("article", { class: "panel play-record" },
    el("h3", { text: `${playListWords(plan.deck)} against ${playListWords(plan.opponent)}` }),
    current ? null : el("p", { class: "box box-warn", text: "A decklist has changed since this plan was saved. Review a new revision before using it with the current lists." }),
    el("p", {}, el("strong", { text: "Out: " }), playNames(plan.out)),
    el("p", {}, el("strong", { text: "In: " }), playNames(plan.in)),
    plan.notes ? el("p", { class: "play-note", text: plan.notes }) : null,
    el("p", { class: "sub", text: `Revision ${plan.revision}; last saved by ${plan.updated_by}.` }),
    playSnapshotDetails([{ ...plan.deck, sections: plan.after }]),
    typeof sideboardPreviewAction === "function" ? sideboardPreviewAction(entry) : null,
    el("button", { class: "btn", type: "button", text: "Revise this plan", disabled: !data.lists.length || null,
      onclick: () => playPlanForm(data, "", entry) }));
}

function playField(label, control) {
  return el("label", { class: "field" }, el("span", { text: label }), control);
}

function playListSelect(lists, preferred) {
  const index = Math.max(0, lists.findIndex(list => preferred && list.id === preferred.id && list.version === preferred.version
    && (!preferred.sha256 || preferred.sha256 === list.sha256)));
  const select = el("select", {}, lists.map((list, i) => el("option", { value: String(i), selected: i === index,
    text: playListWords(list) + (list.historical ? " (recorded historical list)" : "") })));
  select.value = String(index);
  return { select, get: () => lists[Number(select.value)] };
}

function playFormActive(sheet, token, profile) {
  return !sheet.closed && sheet.dialog.isConnected && routeToken === token && state.profile?.id === profile;
}

/** preset (a new game only): {sides: [{id, version, player}, ...], result, onSaved}, the life counter's decks,
 * names and winner (life-counter.js); onSaved runs once the record is saved. */
function playGameForm(data, deckId, entry = null, preset = null) {
  if (!entry && preset?.source_counter) return lifeSourceGameForm(data, preset);
  const old = entry && entry.record;
  const originToken = routeToken, originProfile = state.profile.id;
  const sheet = openSheet(old ? "Correct a played game" : "Record a played game", { wide: true });
  const form = el("form", { class: "play-form" });
  let generation = 0;
  form.addEventListener("input", () => generation++);
  form.addEventListener("change", () => generation++);
  // A game naming another space's deck: only the viewer's own side, and the date, result and notes only when
  // their space recorded it (E10-S32); the rest shows as it is and goes back unchanged.
  const can = old ? playRights(entry) : { sides: [true, true], result: true };
  const date = el("input", { type: "date", required: true, max: data.today, value: old ? old.date : data.today,
    disabled: !can.result || null });
  const notes = el("textarea", { maxlength: 2000, rows: 3, disabled: !can.result || null }, old ? old.notes : "");
  if (old) preset = null;
  const players = old ? old.sides.map(side => side.player || side.title)
    : preset ? playPlayers().map((name, i) => preset.sides[i].player || name) : playPlayers();
  const chosen = old ? old.result : preset ? preset.result : "";
  const result = el("select", { required: true, disabled: !can.result || null }, [["", "Choose the result"], ["a", `${players[0]} won`], ["b", `${players[1]} won`], ["draw", "Draw"]]
    .map(([value, text]) => el("option", { value, text, selected: chosen === value })));
  if (chosen) result.value = chosen;
  const sides = [0, 1].map(i => {
    const prior = old && old.sides[i];
    if (prior && (prior.hidden || prior.removed || !can.sides[i])) {
      // Another space's side: its words only, sent back as it was shown.
      const legend = el("legend", { text: prior.player || `Player ${i + 1}` });
      const row = el("fieldset", { class: "play-side" }, legend,
        el("p", { text: prior.removed ? playListWords(prior) : `${playListWords(prior)}; ${plural(prior.mulligans || 0, "mulligan")}` }),
        el("p", { class: "sub", text: prior.removed ? "This deck was removed. Its recorded side stays unchanged."
          : "Only that deck's own collection can change this side." }));
      const value = () => prior.removed ? playChoice(prior) : prior.hidden ? { hidden: true }
        : { ...playChoice(prior), player: prior.player, mulligans: prior.mulligans };
      return { fixed: true, prior, row, legend, plans: [], get: () => prior, value };
    }
    const lists = [...data.lists];
    if (prior && !lists.some(list => list.sha256 === prior.sha256)) lists.push({ ...prior, historical: true });
    const picker = playListSelect(lists, prior || (preset && preset.sides[i])
      || (i === 0 && deckId ? { id: deckId, version: "target" } : lists[i]));
    const name = el("input", { type: "text", maxlength: 80, required: true, value: prior ? prior.player : players[i] });
    const mulligans = el("input", { type: "number", min: 0, max: 20, step: 1, required: true, value: prior ? prior.mulligans : 0 });
    const plan = el("select", {});
    const legend = el("legend", { text: name.value.trim() || `Player ${i + 1}` });
    const row = el("fieldset", { class: "play-side" }, legend,
      playField("Name", name), playField("Deck and list", picker.select), playField("Mulligans taken", mulligans), playField("Sideboard plan used", plan));
    return { ...picker, name, mulligans, plan, row, prior, legend, plans: [] };
  });
  const refreshPlans = () => sides.forEach((side, i) => {
    if (side.fixed) return;
    const list = side.get(), opponent = sides[1 - i].get();
    const selected = side.plan.value;
    side.plans = data.sideboards.filter(item => !opponent.hidden && !opponent.removed && item.record.deck.sha256 === list.sha256
      && item.record.opponent.sha256 === opponent.sha256);
    clear(side.plan).append(el("option", { value: "", text: "None — base list" }));
    side.plans.forEach(item => side.plan.append(el("option", { value: item.record.id,
      text: `Plan: in ${playNames(item.record.in)}; out ${playNames(item.record.out)}` })));
    if (side.prior && side.prior.sha256 === list.sha256 && side.prior.plan_id) {
      side.plan.append(el("option", { value: side.prior.plan_id, text: "Recorded sideboard plan (historical)" }));
      side.plan.value = side.prior.plan_id;
    } else if (side.plans.some(item => item.record.id === selected)) side.plan.value = selected;
  });
  sides.forEach(side => side.fixed || side.select.addEventListener("change", refreshPlans));
  // The result's words and each side's heading follow the names typed.
  sides.forEach((side, i) => side.fixed || side.name.addEventListener("input", () => {
    const name = side.name.value.trim() || `Player ${i + 1}`;
    result.querySelectorAll("option")[i + 1].textContent = `${name} won`;
    side.legend.textContent = name;
  }));
  refreshPlans();
  const error = el("p", { class: "form-error", role: "alert" });
  const submit = el("button", { class: "btn btn-primary", type: "submit", text: "Review game" });
  form.append(el("p", { class: "sub", text: "Choose the lists you actually played. New records snapshot the current saved lists; a correction keeps its historical lists unless you choose replacements." }),
    playField("Date played", date), el("div", { class: "play-sides" }, sides.map(side => side.row)),
    playField("Result", result), playField("Notes (optional)", notes), error, submit);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!playFormActive(sheet, originToken, originProfile)) { sheet.close(); return; }
    error.textContent = ""; busy(submit, "Checking…");
    const requestGeneration = generation;
    const payload = { id: old ? old.id : null, sha256: entry ? entry.sha256 : null, date: date.value,
      result: result.value, notes: can.result ? notes.value : "", sides: sides.map(side => {
        if (side.fixed) return side.value();
        const value = { ...playChoice(side.get()), player: side.name.value, mulligans: Number(side.mulligans.value) };
        if (side.plan.value) {
          const current = side.plans.find(item => item.record.id === side.plan.value);
          value.plan_id = side.plan.value;
          value.plan_sha256 = current ? current.sha256 : side.prior.plan_sha256;
        }
        return value;
      }) };
    try { await playReview("/api/play/game", payload, sheet,
      () => generation === requestGeneration && playFormActive(sheet, originToken, originProfile), preset && preset.onSaved); }
    catch (failure) { error.textContent = failure.message; }
    finally { if (submit.isConnected) unbusy(submit); }
  });
  sheet.body.append(form);
}

/** The scoped source-aware counter uses the ordinary two-side record API, with exact current-list proof. */
function lifeSourceReview(data, packet, bridge) {
  const profile = state.profile, space = profile?.space || HOME_SPACE;
  if (!profile || typeof lifeSourceValid !== "function" || !packet?.ended ||
      !lifeSourceValid(packet, { profile: profile.id, space }) || !bridge?.isCurrent?.() ||
      typeof bridge.onSaved !== "function" || !podCounterControlVisible(bridge.source)) return false;
  const source = bridge.source, main = $("#main");
  if (!main?.contains(source)) return false;
  const ctx = { data, lists: data.lists, decks: data.decks, plans: data.sideboards, games: data.games,
    profile, profileId: profile.id, space, token: routeToken, hash: location.hash, main, source,
    sourceParent: source.parentNode, sourceFrame: source.parentNode.parentNode,
    bridge, check: bridge.isCurrent, cleanup: bridge.onSaved, packet,
    packetStamp: lifeSourceStable(packet), session: packet.session_id, previewId: null };
  if (!lifeSourceOwner(ctx)) return false;
  playGameForm(data, "", null, { source_counter: ctx, date: packet.date, result: packet.ended.result,
    sides: packet.players.map(player => ({ id: player.list.id, version: player.list.version,
      sha256: player.list.sha256, player: player.name })) });
  return true;
}

function lifeSourceStable(value) {
  const sorted = item => Array.isArray(item) ? item.map(sorted) : item && typeof item === "object"
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, sorted(item[key])])) : item;
  return JSON.stringify(sorted(value));
}
function lifeSourceOwner(ctx) {
  return ctx.profile === state.profile && ctx.profileId === state.profile?.id && ctx.space === (state.profile?.space || HOME_SPACE) &&
    ctx.token === routeToken && ctx.hash === location.hash && document.hidden !== true && document.visibilityState !== "hidden" &&
    ctx.main === $("#main") && ctx.main.isConnected && ctx.main.contains(ctx.source) && podCounterControlVisible(ctx.source) &&
    ctx.source.parentNode === ctx.sourceParent && ctx.sourceParent.parentNode === ctx.sourceFrame &&
    ctx.data.lists === ctx.lists && ctx.data.decks === ctx.decks && ctx.data.sideboards === ctx.plans && ctx.data.games === ctx.games &&
    ctx.bridge.source === ctx.source && ctx.bridge.isCurrent === ctx.check && ctx.bridge.onSaved === ctx.cleanup && ctx.check() === true &&
    ctx.packet.session_id === ctx.session && lifeSourceStable(ctx.packet) === ctx.packetStamp;
}
function lifeSourceFormHere(ctx) {
  return lifeSourceOwner(ctx) && podFrameHere(ctx.frame) && ctx.form.parentNode === ctx.frame.body &&
    lifeSourceShown(ctx.form) &&
    ctx.submit.parentNode === ctx.form && ctx.cancel.parentNode === ctx.frame.foot &&
    ctx.form.contains(ctx.grid) && ctx.fields.every(node => node.isConnected && ctx.form.contains(node) &&
      node.parentNode === ctx.parents.get(node)) && ctx.sides.every(side => side.row.parentNode === ctx.grid &&
        [side.select, side.name, side.mulligans, side.plan].every(node => side.row.contains(node)));
}
function lifeSourceShown(control) {
  if (!control?.isConnected) return false;
  for (let node = control; node; node = node.parentNode) {
    if (node.hidden || node.getAttribute?.("aria-hidden") === "true") return false;
    if (node.matches?.("details") && !node.open && node.getAttribute("open") === null && !node.querySelector("summary")?.contains(control)) return false;
  }
  return true;
}
function lifeSourcePicker(catalog, preferred) {
  const select = el("select", { required: true });
  let choices = [];
  const render = selected => {
    choices = catalog().map(list => structuredClone(list));
    clear(select).append(...[selected < 0 ? el("option", { value: "", text: "Choose a current replacement list" }) : null,
      ...choices.map((list, n) => el("option", { value: String(n), text: playListWords(list) }))].filter(Boolean));
    select.value = selected < 0 ? "" : String(selected);
  };
  const initial = catalog().findIndex(list => list.id === preferred.id && list.version === preferred.version && list.sha256 === preferred.sha256);
  render(initial);
  const drifted = () => /^\d+$/.test(select.value) &&
    lifeSourceStable(catalog()[Number(select.value)]) !== lifeSourceStable(choices[Number(select.value)]);
  return { select, get: () => /^\d+$/.test(select.value) && !drifted() ? choices[Number(select.value)] || null : null,
    stale: initial < 0, drifted, refresh: () => render(-1) };
}
function lifeSourceGameForm(data, preset) {
  const ctx = preset.source_counter;
  if (!lifeSourceOwner(ctx)) return;
  ctx.sheet = openSheet("Record a played game", { wide: true }); ctx.frame = podFrame(ctx.sheet);
  ctx.form = el("form", { class: "play-form life-source-form" }); ctx.generation = 0; ctx.pending = false; ctx.uncertain = false;
  ctx.date = el("input", { type: "date", value: preset.date, required: true, max: data.today, "data-life-source-date": "" });
  ctx.notes = el("textarea", { maxlength: 4000, rows: 3, "data-life-source-notes": "" });
  ctx.result = el("select", { required: true, "data-life-source-result": "" },
    el("option", { value: "", text: "Choose the result" }), ...preset.sides.map((side, i) =>
      el("option", { value: i ? "b" : "a", text: `${side.player} won` })), el("option", { value: "draw", text: "Draw" }));
  ctx.result.value = preset.result;
  const catalog = () => data.lists.filter(list => podSnapshot(list));
  ctx.sides = preset.sides.map((preferred, i) => {
    const picker = lifeSourcePicker(catalog, preferred), id = i ? "b" : "a";
    const name = el("input", { type: "text", required: true, maxlength: 160, value: preferred.player, "data-life-source-name": id });
    const mulligans = el("input", { type: "number", required: true, min: 0, max: 20, step: 1, value: 0, "data-life-source-mulligans": id });
    picker.select.setAttribute("data-life-source-list", id);
    const plan = el("select", { "data-life-source-plan": id }), legend = el("legend", { text: preferred.player });
    const row = el("fieldset", { class: "play-side" }, legend, playField("Name", name), playField("Deck and list", picker.select),
      picker.stale ? el("p", { class: "box box-warn", text: "The counter's chosen list has changed or is unavailable. Choose a current replacement explicitly before review. The record will capture that current list; you can keep counting without recording." }) : null,
      playField("Mulligans taken", mulligans), playField("Sideboard plan used", plan));
    return { ...picker, row, name, mulligans, plan, legend, plans: [] };
  });
  const refreshPlans = (pending = new Set()) => ctx.sides.forEach((side, i) => {
    const list = side.get(), opponent = ctx.sides[1 - i].get(), selected = side.plan.value;
    const needsChoice = pending.has(side) || selected === "pending";
    side.plans = (data.sideboards || []).filter(item => list && opponent && /^[a-f0-9]{32}$/.test(item?.record?.id || "") && podSha(item.sha256) &&
      item.record.deck?.id === list.id && item.record.deck?.version === list.version && item.record.deck?.sha256 === list.sha256 &&
      item.record.opponent?.id === opponent.id && item.record.opponent?.version === opponent.version && item.record.opponent?.sha256 === opponent.sha256)
      .map(item => ({ sha256: item.sha256, record: structuredClone(item.record) }));
    clear(side.plan).append(...[needsChoice ? el("option", { value: "pending", text: "Choose a current plan or None" }) : null,
      el("option", { value: "", text: "None - base list" }), ...side.plans.map(item =>
      el("option", { value: item.record.id, text: `Plan: in ${playNames(item.record.in)}; out ${playNames(item.record.out)}` }))].filter(Boolean));
    side.plan.value = needsChoice ? "pending" : side.plans.some(item => item.record.id === selected) ? selected : "";
    side.plan.disabled = !side.plans.length && !needsChoice;
  });
  ctx.refreshPlans = refreshPlans;
  ctx.grid = el("div", { class: "play-sides" }, ctx.sides.map(side => side.row));
  ctx.error = el("p", { class: "form-error", role: "alert" });
  ctx.submit = el("button", { class: "btn btn-primary", type: "submit", text: "Review game" });
  ctx.cancel = el("button", { class: "btn", type: "button", text: "Back to counter", onclick: () => {
    if (lifeSourceFormHere(ctx) && podTop(ctx.sheet) && !ctx.pending) ctx.sheet.close();
  } });
  ctx.form.append(el("p", { class: "sub", text: "Review the lists and result before recording this game. Counter totals stay on this device." }),
    playField("Date played", ctx.date), ctx.grid, playField("Result", ctx.result), playField("Notes (optional)", ctx.notes), ctx.error, ctx.submit);
  ctx.frame.body.append(ctx.form); ctx.frame.foot.append(ctx.cancel);
  ctx.fields = [ctx.date, ctx.notes, ctx.result, ...ctx.sides.flatMap(side => [side.select, side.name, side.mulligans, side.plan])];
  ctx.parents = new Map(ctx.fields.map(node => [node, node.parentNode]));
  const changed = () => { if (lifeSourceFormHere(ctx)) { ctx.generation++; ctx.error.textContent = ""; } };
  for (const node of ctx.fields) for (const event of ["input", "change"]) node.addEventListener(event, changed);
  ctx.sides.forEach((side, i) => {
    side.select.addEventListener("change", () => {
      if (!lifeSourceFormHere(ctx) || !podTop(ctx.sheet) || !podCounterControlVisible(side.select)) return;
      if (!lifeSourceRefreshChoices(ctx)) refreshPlans();
    });
    side.plan.addEventListener("change", () => {
      if (!lifeSourceFormHere(ctx) || !podTop(ctx.sheet) || !podCounterControlVisible(side.plan)) return;
      if (!lifeSourceRefreshChoices(ctx)) refreshPlans();
    });
    side.name.addEventListener("input", () => {
      const name = podTrim(side.name.value) || `Player ${i + 1}`;
      side.legend.textContent = name; ctx.result.querySelectorAll("option")[i + 1].textContent = `${name} won`;
    });
  });
  refreshPlans();
  ctx.form.addEventListener("submit", event => { event.preventDefault(); lifeSourcePreview(ctx); });
  if (lifeSourceFormHere(ctx) && podTop(ctx.sheet)) ctx.submit.focus();
}
function lifeSourcePayload(ctx) {
  return { profile: ctx.profileId, id: ctx.previewId, sha256: null, date: ctx.date.value, result: ctx.result.value, notes: ctx.notes.value,
    sides: ctx.sides.map(side => {
      const list = side.get();
      if (!list) throw Error("replacement");
      const plan = lifeSourceSelectedPlan(ctx, side);
      if (side.plan.value && !plan) throw Error("plan");
      return { ...playChoice(list), player: side.name.value, mulligans: Number(side.mulligans.value),
        ...(plan ? { plan_id: plan.record.id, plan_sha256: plan.sha256 } : {}) };
    }) };
}
const lifeSourceChoiceChanged = "A list or sideboard plan changed while this form was open. Choose current replacements explicitly before review. Your draft is still here.";
function lifeSourceSelectedPlan(ctx, side) {
  if (!side.plan.value || side.plan.value === "pending") return null;
  const captured = side.plans.find(item => item.record.id === side.plan.value);
  const current = (ctx.data.sideboards || []).find(item => item?.record?.id === side.plan.value);
  return captured && current && captured.sha256 === current.sha256 &&
    lifeSourceStable(captured.record) === lifeSourceStable(current.record) ? captured : null;
}
function lifeSourceRefreshChoices(ctx) {
  const changedLists = ctx.sides.filter(side => side.drifted());
  const changedPlans = new Set(ctx.sides.filter(side => side.plan.value && side.plan.value !== "pending" &&
    !lifeSourceSelectedPlan(ctx, side)));
  if (!changedLists.length && !changedPlans.size) return false;
  if (changedLists.length) for (const side of ctx.sides) if (side.plan.value) changedPlans.add(side);
  for (const side of changedLists) {
    side.refresh();
  }
  ctx.generation++; ctx.refreshPlans(changedPlans); ctx.error.textContent = lifeSourceChoiceChanged;
  return true;
}
function lifeSourceDraftStamp(ctx) { try { return lifeSourceStable(lifeSourcePayload(ctx)); } catch (_) { return null; } }
function lifeSourceDraftError(ctx, payload) {
  if (!podDate(payload.date) || payload.date > ctx.data.today) return "Choose a valid date on or before today.";
  if (!["a", "b", "draw"].includes(payload.result)) return "Choose a winner or draw.";
  if (!podNotes(payload.notes)) return "Keep notes to at most 2,000 characters without unsupported control characters.";
  if (payload.sides.some(side => !podText(side.player, 80))) return "Give each player a name of at most 80 characters on one line.";
  if (ctx.sides.some(side => !/^\d+$/.test(side.mulligans.value) || !Number.isSafeInteger(Number(side.mulligans.value)) ||
      Number(side.mulligans.value) < 0 || Number(side.mulligans.value) > 20)) return "Mulligans must be whole numbers from 0 to 20.";
  if (!payload.sides.some(side => ctx.data.decks?.[side.id]?.can_record === true))
    return "Choose a current deck you may record before review. You can keep counting without recording.";
  return null;
}

function lifeSourceSections(value) {
  return value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length <= 12 &&
    Array.isArray(value.Deck) && value.Deck.length > 0 && Object.entries(value).every(([name, lines]) => podText(name, 80) &&
      Array.isArray(lines) && lines.length <= 500 && lines.every(line => line && typeof line === "object" &&
        Object.keys(line).length === 5 && ["qty", "name", "set", "number", "finish"].every(key => Object.hasOwn(line, key)) &&
        Number.isSafeInteger(line.qty) && line.qty > 0 && line.qty <= 10000 && podText(line.name, 300) &&
        ["nonfoil", "foil", "etched"].includes(line.finish) && [line.set, line.number].every(text => text === null || podText(text, 80, true))));
}
function lifeSourceAnswer(ctx, answer, payload, expected, saved = false) {
  const record = answer?.record;
  if (answer?.error || !record || Object.hasOwn(record, "mode") || Object.hasOwn(record, "game_version") ||
      (saved ? answer.saved !== true || !podSha(answer.sha256) : answer.preview !== true || !podSha(answer.review_sha256)) ||
      !/^[a-f0-9]{32}$/.test(saved ? record.id || "" : answer.id || "") || payload.id && (saved ? record.id : answer.id) !== payload.id ||
      record.space !== ctx.space || record.date !== payload.date || record.result !== payload.result || record.notes !== podTrim(payload.notes) ||
      !Array.isArray(record.sides) || record.sides.length !== 2) return null;
  if (saved && (record.version !== 1 || record.kind !== "games" || record.revision !== 1 ||
      !podText(record.updated_by, 80) || [record.created_on, record.updated_on].some(value =>
        !podText(value, 80) || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))))) return null;
  for (let i = 0; i < 2; i++) {
    const side = record.sides[i], wanted = payload.sides[i], source = expected[i];
    const keys = ["id", "version", "sha256", "title", "sections", "player", "mulligans",
      ...(wanted.plan_id ? ["plan_id", "plan_sha256", "base_sha256"] : [])];
    if (!side || typeof side !== "object" || Object.keys(side).length !== keys.length || Object.keys(side).some(key => !keys.includes(key)) ||
        side.id !== wanted.id || side.version !== wanted.version || !podSha(side.sha256) || !podText(side.title, 500) ||
        side.player !== podTrim(wanted.player) || side.mulligans !== wanted.mulligans || !lifeSourceSections(side.sections) ||
        lifeSourceStable(side.sections) !== lifeSourceStable(source.sections)) return null;
    if (wanted.plan_id ? side.base_sha256 !== wanted.sha256 || side.plan_id !== wanted.plan_id || side.plan_sha256 !== wanted.plan_sha256
      : side.sha256 !== wanted.sha256) return null;
  }
  const content = { date: record.date, result: record.result, notes: record.notes, space: record.space, sides: record.sides };
  return { content: structuredClone(content), id: saved ? record.id : answer.id, token: answer.review_sha256 };
}
async function lifeSourcePreview(ctx) {
  if (!lifeSourceFormHere(ctx) || !podTop(ctx.sheet) || !podCounterControlVisible(ctx.submit) || ctx.pending || ctx.uncertain) return;
  if (lifeSourceRefreshChoices(ctx)) return;
  let payload;
  try { payload = lifeSourcePayload(ctx); }
  catch (failure) { ctx.error.textContent = failure.message === "plan" ? "Choose a current sideboard plan or None before review. Your draft is still here."
    : "Choose current replacement lists before review. You can keep counting without recording."; return; }
  const problem = lifeSourceDraftError(ctx, payload);
  if (problem) { ctx.error.textContent = problem; return; }
  const expected = ctx.sides.map(side => {
    const plan = lifeSourceSelectedPlan(ctx, side);
    return { sections: structuredClone(plan ? plan.record.after : side.get().sections) };
  });
  const generation = ctx.generation, stamp = lifeSourceStable(payload);
  const current = () => lifeSourceFormHere(ctx) && ctx.generation === generation && lifeSourceDraftStamp(ctx) === stamp;
  ctx.pending = true; ctx.error.textContent = ""; busy(ctx.submit, "Checking.");
  try {
    const answer = await apiWrite("/api/play/game", { ...payload, preview: true });
    if (!current() || !podTop(ctx.sheet)) return;
    const checked = lifeSourceAnswer(ctx, answer, payload, expected);
    if (!checked) { ctx.error.textContent = "The game preview couldn't be checked. Your counter and draft are still here."; return; }
    ctx.previewId = checked.id; payload = { ...payload, id: checked.id };
    lifeSourceReviewSheet(ctx, payload, expected, checked, generation);
  } catch (_) { if (current() && podTop(ctx.sheet)) ctx.error.textContent = "The game couldn't be reviewed. Your counter and draft are still here."; }
  finally { ctx.pending = false; if (lifeSourceFormHere(ctx)) unbusy(ctx.submit); }
}
function lifeSourceReviewSheet(ctx, payload, expected, checked, generation) {
  const review = openSheet("Review played game", { wide: true }), frame = podFrame(review), stamp = lifeSourceStable(payload);
  const summary = playGameCard({ record: checked.content, can: { sides: [false, false], result: false } }, ctx.data);
  const error = el("p", { class: "form-error", role: "alert" }); frame.body.append(summary, error);
  let pending = false, saved = false;
  const back = el("button", { type: "button", class: "btn", text: "Back to editing" });
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save this record" }); frame.foot.append(back, save);
  const current = () => lifeSourceFormHere(ctx) && podFrameHere(frame) && podTop(review) && summary.parentNode === frame.body &&
    error.parentNode === frame.body && back.parentNode === frame.foot && save.parentNode === frame.foot &&
    lifeSourceShown(summary) && lifeSourceShown(back) && lifeSourceShown(save) &&
    ctx.generation === generation && lifeSourceDraftStamp(ctx) === stamp;
  back.addEventListener("click", () => { if (current() && !pending) { review.close(); if (lifeSourceFormHere(ctx) && podTop(ctx.sheet)) ctx.submit.focus(); } });
  save.addEventListener("click", async () => {
    if (!current() || !podCounterControlVisible(save) || pending || saved || ctx.uncertain) return;
    pending = true; busy(save, "Saving."); error.textContent = "";
    try {
      const answer = await apiWrite("/api/play/game", { ...payload, preview: false, review_sha256: checked.token });
      if (!current()) return;
      const confirmed = lifeSourceAnswer(ctx, answer, payload, expected, true);
      if (!confirmed || lifeSourceStable(confirmed.content) !== lifeSourceStable(checked.content)) {
        ctx.uncertain = true;
        error.textContent = ctx.error.textContent = "The save response couldn't be checked. Keep the counter and check the Game log before recording again.";
        ctx.submit.disabled = true;
        return;
      }
      saved = true; review.close(); ctx.sheet.close();
      if (lifeSourceOwner(ctx)) { const cleaned = ctx.cleanup(); toast("Record saved."); if (cleaned !== false) route(); }
    } catch (_) { if (current()) error.textContent = "The game couldn't be saved. Your counter and draft are still here; a changed record may need a fresh Game log."; }
    finally { pending = false; if (current() && !ctx.uncertain) unbusy(save); }
  });
  if (current()) back.focus();
}

function playPlanForm(data, deckId, entry = null, preferred = {}) {
  const old = entry && entry.record;
  const originToken = routeToken, originProfile = state.profile.id;
  const sheet = openSheet(old ? "Revise sideboard plan" : "New sideboard plan", { wide: true });
  const own = playListSelect(data.lists, old ? { id: old.deck.id, version: old.deck.version } : preferred.deck || { id: deckId, version: "target" });
  // A hidden opponent (another space's private deck, E10-S32) stays as it was: its words only.
  const hiddenOpponent = old && (old.opponent.hidden || old.opponent.removed) ? old.opponent : null;
  const opposing = hiddenOpponent ? { select: el("p", { text: hiddenOpponent.title }), get: () => hiddenOpponent }
    : playListSelect(data.lists, old ? { id: old.opponent.id, version: old.opponent.version } : preferred.opponent || data.lists[1]);
  const notes = el("textarea", { maxlength: 2000, rows: 3 }, old ? old.notes : "");
  const moves = el("div", { class: "play-sides" });
  let controls = [];
  let generation = 0;
  const redraw = () => {
    controls = []; clear(moves);
    for (const [direction, section] of [["out", "Deck"], ["in", "Sideboard"]]) {
      const box = el("fieldset", { class: "play-side" }, el("legend", { text: direction === "in" ? "In from sideboard" : "Out of main deck" }));
      const counts = new Map();
      for (const line of own.get().sections[section] || []) counts.set(line.name, (counts.get(line.name) || 0) + line.qty);
      for (const [name, count] of counts) {
        const previous = old && old.deck.id === own.get().id && old.deck.version === own.get().version && old[direction].find(line => line.name === name);
        const input = el("input", { type: "number", min: 0, max: count, step: 1, value: previous ? Math.min(previous.qty, count) : 0,
          required: true, "aria-label": `${name}: copies ${direction}` });
        controls.push({ direction, name, input });
        box.append(el("label", { class: "play-move" }, el("span", { text: `${name} (${count} available)` }), input));
      }
      if (!counts.size) {
        const deck = own.get();
        box.append(section === "Sideboard" ? emptyBox("No sideboard cards yet.", canEditDeckId(deck.id)
          ? el("a", { class: "btn btn-quiet", href: editHref(deck.id, deck.version), text: "Edit deck" }) : null)
          : el("p", { class: "sub", text: "No main-deck cards." }));
      }
      moves.append(box);
    }
  };
  own.select.addEventListener("change", redraw); redraw();
  const error = el("p", { class: "form-error", role: "alert" });
  const submit = el("button", { type: "submit", class: "btn btn-primary", text: "Review sideboard plan" });
  const form = el("form", { class: "play-form", onsubmit: async event => {
    event.preventDefault();
    if (!playFormActive(sheet, originToken, originProfile)) { sheet.close(); return; }
    error.textContent = ""; busy(submit, "Checking…");
    const requestGeneration = generation;
    const payload = { id: old ? old.id : null, sha256: entry ? entry.sha256 : null, deck: playChoice(own.get()),
      opponent: hiddenOpponent ? hiddenOpponent.removed ? playChoice(hiddenOpponent) : { hidden: true }
        : playChoice(opposing.get()), notes: notes.value };
    for (const direction of ["in", "out"]) payload[direction] = controls.filter(item => item.direction === direction && Number(item.input.value) > 0)
      .map(item => ({ name: item.name, qty: Number(item.input.value) }));
    try { await playReview("/api/play/sideboard", payload, sheet,
      () => generation === requestGeneration && playFormActive(sheet, originToken, originProfile), preferred.onSaved); }
    catch (failure) { error.textContent = failure.message; }
    finally { if (submit.isConnected) unbusy(submit); }
  } }, el("p", { class: "sub", text: "Choose equal numbers in and out. Saving keeps a separate plan and the resulting list; your saved deck is unchanged." }),
    playField("Your deck and list", own.select), playField("Opponent's deck and list", opposing.select),
    moves, playField("When and why to use the plan", notes), error, submit);
  form.addEventListener("input", () => generation++);
  form.addEventListener("change", () => generation++);
  sheet.body.append(form);
}

async function playReview(endpoint, payload, parent, isCurrent = () => true, onSaved = null) {
  const token = routeToken;
  const answer = await apiWrite(endpoint, { ...payload, preview: true });
  if (token !== routeToken) { parent.close(); return; }
  if (parent.closed || !parent.dialog.isConnected || !isCurrent()) return;
  const record = answer.record;
  const review = openSheet(record.sides ? "Review played game" : "Review sideboard plan", { wide: true });
  if (record.sides) {
    add(review.body, [el("p", { text: `${record.date} · ${playResult(record)}` }),
      ...record.sides.map(side => el("p", { text: side.removed ? playListWords(side)
        : `${side.player}: ${playListWords(side)}, ${side.mulligans} mulligans${side.plan_id ? ", sideboard plan applied" : ""}` })),
      playSnapshotDetails(record.sides)]);      // null when every side is hidden: add() skips it
  } else {
    add(review.body, [el("p", { text: `${playListWords(record.deck)} against ${playListWords(record.opponent)}` }),
      el("p", { text: `Out: ${playNames(record.out)}` }), el("p", { text: `In: ${playNames(record.in)}` }),
      playSnapshotDetails([{ ...record.deck, sections: record.after }])]);
  }
  if (record.notes) review.body.append(el("p", { class: "play-note", text: record.notes }));
  const error = el("p", { class: "form-error", role: "alert" });
  review.body.append(error);
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save this record", onclick: async () => {
    if (token !== routeToken || parent.closed || !isCurrent()) { review.close(); return; }
    busy(save, "Saving…");
    try {
      await apiWrite(endpoint, { ...payload, id: answer.id, preview: false, review_sha256: answer.review_sha256 });
      review.close(); parent.close();
      if (token === routeToken && onSaved) onSaved();
      if (token === routeToken && location.hash.startsWith("#/play")) route();
      toast("Record saved.");
    } catch (failure) { error.textContent = failure.message; }
    finally { if (save.isConnected) unbusy(save); }
  } });
  review.foot.append(el("button", { type: "button", class: "btn", text: "Back to editing", onclick: () => review.close() }), save);
}
