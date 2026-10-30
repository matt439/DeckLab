/* Tonight's pairs (E1-S28) on the Game log: up to three ready pairs of home's built casual decks, one for
each home player, evenest and least lately played first, each with its plain reasons (GET /api/play/pairs,
lib/play_pairs.py). Only home's profiles are shown it; the server answers anyone else with nothing.
Use this pair puts the two lists in the quick record's pickers (playQuickChoose); nothing is saved. */
"use strict";

/** True for a home profile who plays at home (Matt or User1): the only viewers the pairs are for. */
function playTonightFor(profile) {
  return !!profile && (profile.space || HOME_SPACE) === HOME_SPACE && !!profile.plays_as;
}

/** The home player who takes a seat ("user" or "wife"): their name, else the seat's plain words. */
function playTonightPlayer(seat) {
  const found = (state.profiles || []).find((p) => (p.space || HOME_SPACE) === HOME_SPACE && p.plays_as === seat);
  return found ? found.name : seat === "user" ? "Player 1" : "Player 2";
}

/** The section, drawn at once with a loading line, filled when the answer comes (null for anyone else). */
function playTonightSection(data) {
  if (!playTonightFor(state.profile)) return null;
  const body = el("div", { class: "play-tonight-body" }, loadingBox("Working out tonight's pairs…", { small: true }));
  const section = el("section", { class: "play-section play-tonight", "aria-labelledby": "play-tonight-title" },
    el("h2", { id: "play-tonight-title", text: "Tonight's pairs" }),
    el("p", { class: "sub", text: "Ready decks, one each, the evenest and least lately played first." }), body);
  const token = routeToken;
  const fill = (answer) => { if (token === routeToken) clear(body).append(...playTonightBody(answer, data)); };
  api("/api/play/pairs").then(fill, (error) => {
    if (token === routeToken) clear(body).append(loadFailed("Tonight's pairs", error));
  });
  return section;
}

/** What the section holds for an answer: the pairs, or why there are none. */
function playTonightBody(answer, data) {
  if (!answer || !answer.available) return [emptyBox("Tonight's pairs are for home's players.")];
  const notes = [answer.error, answer.forge_error ? `${answer.forge_error} The pairs go by real games only.` : null]
    .filter(Boolean).map((text) => el("p", { class: "note note-warn", text }));
  if (answer.error) return notes;
  if (!answer.pairs.length) {
    const why = answer.ready >= 2 ? "No pair is ready yet: the ready decks are all for the same player."
      : answer.unconfirmed ? `No pair can be suggested yet: whether ${plural(answer.unconfirmed, "built deck has", "built decks have")} every card here needs checking.`
        : "No pair is ready yet: it takes two built casual decks with every card here, one for each of you.";
    return [...notes, emptyBox(why, el("a", { class: "btn btn-quiet", href: "#/library", text: routeFor("library").label }))];
  }
  return [...notes, el("div", { class: "play-records" }, answer.pairs.map((pair) => playTonightCard(pair, data)))];
}

function playTonightCard(pair, data) {
  const [first, second] = pair.sides;
  return el("article", { class: "panel play-record play-tonight-pair" },
    el("h3", { text: `${first.title} vs ${second.title}` }),
    el("p", { class: "sub", text: pair.sides.map((side) => `${playTonightPlayer(side.seat)}: ${side.title}`).join(" · ") }),
    el("ul", { class: "play-tonight-reasons" }, pair.reasons.map((reason) => el("li", { text: reason }))),
    el("button", { type: "button", class: "btn btn-quiet", text: "Use this pair", onclick: () => playTonightUse(pair, data) }));
}

/** Puts the pair's lists in the quick record: each deck on the side of the player whose seat it is (side 0 is
 * the visitor). A list that isn't in the pickers any more leaves that side as it was. */
function playTonightUse(pair, data) {
  if (typeof playQuickChoose !== "function") return;
  const plays = state.profile && state.profile.plays_as;
  const mine = pair.sides.some((side) => side.seat === plays) ? plays : "user";
  const choices = [-1, -1];
  for (const side of pair.sides) {
    const at = data.lists.findIndex((list) => list.id === side.id && list.version === (side.version || "target"));
    choices[side.seat === mine ? 0 : 1] = at;
  }
  playQuickChoose(choices);
}
