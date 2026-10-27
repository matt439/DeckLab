/* Recorded human games for the same historical lists; never part of Forge's simulated rate. */
"use strict";

function matchupPlayDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1) return null;
  const date = new Date(value + "T00:00:00Z");
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : value;
}

function matchupPlaySummary(summary) {
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if (!summary || summary.status !== "ready" || summary.minimum_games !== 10 || !count(summary.games) || !count(summary.draws)
      || !Array.isArray(summary.wins) || summary.wins.length !== 2 || !summary.wins.every(count)
      || summary.wins[0] + summary.wins[1] + summary.draws !== summary.games) return null;
  if (!summary.games) return summary.first_date === null && summary.last_date === null ? summary : null;
  return matchupPlayDate(summary.first_date) && matchupPlayDate(summary.last_date) && summary.first_date <= summary.last_date ? summary : null;
}

/** This producer supplies counts in the displayed side order; the UI never remaps a seat or fetches records. */
function matchupRealGames(data) {
  if (!data || typeof data !== "object" || !Object.hasOwn(data, "real_games")) return null;
  const panel = el("section", { class: "panel mu-real-games", "aria-label": "Recorded human games for these lists" },
    el("h3", { text: "Real games" }));
  const summary = matchupPlaySummary(data.real_games);
  if (!summary || !Array.isArray(data.sides) || data.sides.length !== 2 || data.sides.some(side => !side || typeof side.title !== "string"
      || !side.title.trim() || /[\u0000-\u001f\u007f]/.test(side.title))) {
    panel.append(data.real_games?.status === "unsupported"
      ? el("p", { class: "sub", text: "A recorded human-game comparison is not supported for this result." })
      : note("The recorded human games could not be checked, so no comparison is shown."));
    return panel;
  }
  const [first, second] = sideTitles(data.sides), [wins, other] = summary.wins;
  panel.append(el("p", { text: plural(summary.games, "recorded human game") + ": " + first + ": " + plural(wins, "win")
    + "; " + second + ": " + plural(other, "win") + "; " + plural(summary.draws, "draw") + "." }),
    el("p", { text: summary.games ? first + "'s plain human win share: " + wins + " / " + summary.games + " = " + pct(wins / summary.games) + "."
      : "There are no matching recorded human games, so no human win percentage is available." }),
    el("p", { class: "sub", text: "Human shares use wins divided by all matching recorded games, with draws in the denominator. These observations are separate from Forge's AI games." }),
    el("p", { class: "sub", text: "Only games for this pair of decks with the same main-deck and commander cards as Forge count. Printing choices, unused sideboards and Companion sections are not compared." }));
  const rate = data.result?.winrate;
  if (Number.isFinite(rate?.value) && rate.value >= 0 && rate.value <= 1 && typeof rate.balanced === "boolean") panel.append(el("p", {
    class: "sub", text: "Forge's simulated headline for " + first + ": " + pct(rate.value) + (rate.balanced
      ? ", balanced for going first and second."
      : ", the plain simulated share because going first and second could not be balanced.") }));
  if (summary.games) panel.append(el("p", { class: "sub" }, "Recorded dates: ",
    el("time", { datetime: summary.first_date, text: summary.first_date }), summary.first_date === summary.last_date ? "" : " to ",
    summary.first_date === summary.last_date ? "" : el("time", { datetime: summary.last_date, text: summary.last_date }), "."));
  panel.append(el("p", { class: "sub", text: summary.games < summary.minimum_games
    ? "Too few real games to confirm or contradict Forge yet: fewer than 10 matching games are recorded."
    : "This is an observational human record. It does not confirm or contradict Forge by itself; players, choices and chance also affect the results." }));
  return panel;
}
