/* The deck page's suggested token counts (E7-S08): what the list's saved Forge games say about how many
 * of each token a game puts on the battlefield at once (lib/api/token_peaks.py, lib/tokens/peaks.py).
 * Always labelled as an estimate from simulated games, never a purchase or a claim of what a game needs.
 * The server sends them only to viewers who see the deck's Tokens part, so these pieces show only there:
 *     tokenPeakLine(found)    one need's "forge": "Forge games peaked at 7; most games at most 4 (...)"
 *     tokenPeakShort(found)   the same, short, for a compact token row (E7-S33): "Forge est. ≤4"
 *     tokenPeaksPart(forge)   the Tokens part's "forge": why there are no counts, or where they came from */
"use strict";

/** One need's suggested count (the need's "forge"), or null when it has none. */
function tokenPeakLine(found) {
  if (!found || typeof found.words !== "string") return null;
  return el("p", { class: "token-need-forge" }, el("small", { text: `Estimate from simulated games: ${found.words}` }));
}

/** A need's suggested count in a few words ("Forge est. ≤4", or "Forge est. 10+" at the server's cap), or
 * null when no saved game made one. The row's body has the full sentence (tokenPeakLine). */
function tokenPeakShort(found) {
  if (!found || typeof found.words !== "string" || !(found.games > 0) || !(found.most > 0)) return null;
  const capped = /at most \d+ or more/.test(found.words);
  return el("small", { class: "token-row-forge", text: `Forge est. ${capped ? `${found.most}+` : `≤${found.most}`}` });
}

/** The Tokens part's word on suggested counts: why there are none ("No suggested counts: ..."), or how many
 * saved games they come from and how they're worked out. null when the part has none. */
function tokenPeaksPart(forge) {
  if (!forge || typeof forge !== "object") return null;
  if (!forge.games) return forge.why ? el("p", { class: "sub token-peaks-none", text: forge.why }) : null;
  const from = `Suggested counts from ${plural(forge.games, "simulated Forge game")}`
    + (forge.matchups ? ` in ${plural(forge.matchups, "matchup")}` : "")
    + (forge.untallied ? ` (${plural(forge.untallied, "earlier game")} didn't count tokens)` : "");
  return el("div", { class: "token-peaks" }, el("p", { class: "sub", text: `${from}: approximate` }),
    forge.note ? el("p", { class: "sub", text: forge.note }) : null);
}
