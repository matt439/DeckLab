/* A Commander night line-up (E9-S34) on the Game log: home's Commander decks sorted against the recorded
Commander night's bracket aim and range into Fits, Above the aim (with the cards that decide it) and Unknown,
each with whether it's built, its stand-ins, when its box was last checked and when it was last played
(GET /api/commander-night/lineup, lib/commander_lineup.py). Only home's profiles are shown it; the server
refuses anyone else. Working it out reads every deck, so it waits for Show the line-up. Nothing is saved. */
"use strict";

const LINEUP_GROUPS = [
  ["fits", "Fits the night"],
  ["above", "Above the aim"],
  ["unknown", "Unknown"],
];

/** True for a home profile (Matt or User1): the only viewers the line-up is for. */
function commanderLineupFor(profile) {
  return !!profile && (profile.space || HOME_SPACE) === HOME_SPACE;
}

/** The section with its Show button (null for anyone else). */
function commanderLineupSection() {
  if (!commanderLineupFor(state.profile)) return null;
  const body = el("div", { class: "commander-lineup-body" });
  const show = el("button", { type: "button", class: "btn btn-quiet", text: "Show the line-up",
    onclick: () => commanderLineupLoad(body, show) });
  body.append(show);
  return el("section", { class: "play-section commander-lineup", "aria-labelledby": "commander-lineup-title" },
    el("h2", { id: "commander-lineup-title", text: "Commander night line-up" }),
    el("p", { class: "sub", text: "Home's Commander decks against the recorded night's bracket aim. The counted minimum covers only what the bracket rules name (Game Changers, mass land denial, extra turns and two-card combos), never a deck's real power: talk it over before the game." }),
    body);
}

/** Loads the line-up into body; a late answer after a route or profile change is dropped. */
function commanderLineupLoad(body, show) {
  const token = routeToken, profile = state.profile && state.profile.id;
  const here = () => token === routeToken && body.isConnected !== false && profile === (state.profile && state.profile.id);
  clear(body).append(loadingBox("Working out each deck's minimum bracket…", { small: true }));
  api("/api/commander-night/lineup").then((answer) => {
    if (here()) clear(body).append(...commanderLineupBody(answer), commanderLineupAgain(body, show));
  }, (error) => {
    if (here()) clear(body).append(loadFailed("The Commander night line-up", error), commanderLineupAgain(body, show));
  });
}

function commanderLineupAgain(body, show) {
  return el("button", { type: "button", class: "btn btn-quiet", text: "Check again",
    onclick: () => commanderLineupLoad(body, show) });
}

/** What the section holds for an answer. */
function commanderLineupBody(answer) {
  if (!answer || !answer.available) return [emptyBox("The Commander night line-up is for home's players.")];
  const parts = [];
  const night = answer.night;
  if (night) {
    const low = night.published_min, high = night.published_max;
    const range = low == null ? "No published bracket range recorded."
      : low === high ? `Published venue bracket: ${low}.` : `Published venue range: Brackets ${low}–${high}.`;
    parts.push(el("p", { class: "commander-lineup-night" }, el("strong", { text: night.name }),
      night.venue ? ` at ${night.venue}. ` : ". ", `${answer.basis} ${range}`));
  } else {
    parts.push(el("p", { class: "note note-warn", text: answer.basis }));
  }
  if (answer.played_error) parts.push(el("p", { class: "note note-warn", text: answer.played_error }));
  if (answer.timed_out) parts.push(el("p", { class: "note note-warn",
    text: `${plural(answer.timed_out, "deck wasn't", "decks weren't")} checked in time, so ${answer.timed_out === 1 ? "it's" : "they're"} listed as unknown. Check again, or open the deck's page.` }));
  const total = LINEUP_GROUPS.reduce((n, [key]) => n + ((answer.groups || {})[key] || []).length, 0);
  if (!total) return [...parts, emptyBox("There are no home Commander decks to line up yet.")];
  for (const [key, label] of LINEUP_GROUPS) {
    const rows = (answer.groups || {})[key] || [];
    if (!rows.length) continue;
    parts.push(el("div", { class: `commander-lineup-group commander-lineup-${key}` },
      el("h3", { text: `${label} (${rows.length})` }),
      el("div", { class: "play-records" }, rows.map((row) => commanderLineupRow(row, key)))));
  }
  return parts;
}

/** A stand-in mapping in words: "Sol Ring for Mana Crypt", or an unspecified card. */
function commanderLineupStandIn(row) {
  const what = row.using ? row.using : "a spare card";
  return `${row.qty > 1 ? `${row.qty} × ` : ""}${what} for ${row.for}`;
}

function commanderLineupRow(row, group) {
  const facts = [STATUS_WORDS[row.status] || "No status"];
  if (row.minimum != null) facts.push(`Counted minimum: Bracket ${row.minimum}`);
  else if (row.minimum_so_far != null) facts.push(`At least Bracket ${row.minimum_so_far} so far`);
  facts.push(row.target_bracket ? `Target Bracket ${row.target_bracket}` : "No target bracket");
  if (row.built && row.version === "owned") facts.push("Judged on its Play-now list");
  const lines = [el("p", { class: "sub", text: facts.join(" · ") })];
  if (group === "above" && row.deciding.length) {
    lines.push(el("ul", { class: "commander-lineup-deciding" }, row.deciding.map((d) =>
      el("li", {}, el("strong", { text: `${d.reason}: ` }), d.cards.join(", ")))));
  }
  if (row.unknown_reason) lines.push(el("p", { class: "commander-lineup-why", text: row.unknown_reason }));
  if (row.below_range) lines.push(el("p", { class: "sub", text: "Its counted minimum is below the venue's published range; check that it keeps up with the table." }));
  if (Array.isArray(row.stand_ins)) lines.push(el("p", { class: "sub commander-lineup-standins", text: row.stand_ins.length
    ? `Stand-ins: ${row.stand_ins.map(commanderLineupStandIn).join("; ")}` : "No stand-ins" }));
  if ("box_checked_on" in row) lines.push(el("p", { class: "sub commander-lineup-box",
    text: row.box_checked_on ? `Box checked ${row.box_checked_on}` : "Box not checked yet" }));
  if (row.played_known) lines.push(el("p", { class: "sub commander-lineup-played", text: row.last_played
    ? `Last played ${row.last_played}${row.days_since_played > 0 ? ` (${plural(row.days_since_played, "day")} ago)` : row.days_since_played === 0 ? " (today)" : ""}`
    : "Not played at home yet" }));
  return el("article", { class: "panel play-record commander-lineup-deck" },
    el("h4", {}, el("a", { href: deckHref(row.id, row.version), text: row.title })), ...lines);
}
