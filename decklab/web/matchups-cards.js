/* Deck Lab's matchup screens: their per-card numbers, the matchup page's "How each deck's cards
played" and the deck page's "How its cards played". The other matchup scripts hold the screens.

Loaded after matchups-results.js and before the page's other scripts (core.js, library.js, deck.js,
stats.js, practice.js and app.js). It holds the thresholds its words follow, the matchup page's
per-card part (cardStatsPart) and where its numbers come from (cardStatsCoverage), the key to the
figures, each list's tables (commander, spells, lands) and the words under each card (winSplitWords),
and the deck page's part (deckCardStats) with its lead of what stands out (standOutParts). Nothing
here runs at load but its constants. Once the page is running it uses core.js's el, status, plural,
thousands, capitalise and pctShort, deck.js's cardLink(), and matchups.js's gamesWords() and
sideTitles(). matchups-results.js calls castsPart (cardStatsPart, cardStatsCoverage) on the matchup
page; the deck page's Matchups tab (deck-tools.js drawDeckMatchups) calls deckCardStats.

Per-card numbers (Milestone 8) come from Deck Lab's card log, which follows every card through Forge's
games (DeckLabSim, in lib/forge/java/; forge/cardlog.py reads it): how often each card was drawn, cast
once drawn, stuck in hand at the end, the turn it was cast, and the deck's win rate when it was drawn and
when not. The matchup page shows each side's (castsPart), the deck page pools every saved matchup of the
list (deckCardStats). All of it is counted, none of it judged by an AI: a win-rate difference gets a
verdict in words only once a card has CARD_SPLIT_GAMES games each way (with it and without), and never for a
land (the games without one were mostly short of lands, or of its colour); the numbers say they're early until
CARD_STATS_GAMES games the verdicts are on have card data. The server (cardstats.py) compares a card's
games matchup by matchup on the deck page, pulls each difference toward 0 by how noisy it is (its
"best estimate", row.shrunk), and says "won more" or "won less" only for a card that stands out among
the list's cards compared (a Benjamini-Hochberg discovery, row.discovery); a range clear of 0 that doesn't
stand out is said to be within chance. Rows from an older server, without those, read as before.
Since card log version 3 (wave 2) the verdicts are on whether a copy was in hand by the deck's own turn 3
(stats.basis "early": the kept hand, or drawn by then), which every game reaches with about as many cards
seen, so it doesn't lean with game length as "drawn at any point" does; the drawn rates stay beside it.
Games kept before that (stats.basis "drawn") keep their drawn verdicts, said to lean with game length
(cardStatsBasis says which, once). The tables keep to four narrow number columns, with the rest of a
card's numbers across the row under it, so they fit a 390 px phone.
*/
"use strict";

const CARD_STATS_GAMES = 800;           // games the verdicts are on before per-card numbers stop being early (cardstats.MIN_CARD_GAMES)
const CARD_SPLIT_GAMES = 30;            // games drawn, and not drawn, before a card's win-rate difference gets a verdict (MIN_SPLIT_GAMES)
const NEARLY_EVERY_GAME = 0.95;         // drawn in this share of games or more: too few games without the card to compare with
const STUCK_NOTED = 0.2;                // the deck page calls out a spell still in hand at the end in this share of its drawn copies...
const STUCK_MIN_COPIES = 20;            // ... once this many copies were drawn (with fewer, one stuck copy is a big share)
const STUCK_SHOWN = 3;                  // ... and at most this many of them, the most often stuck first
const CLEAR_SHOWN = 3;                  // the deck page's clearest win-rate differences: this many each way
const EARLY_ACT = "in hand by turn 3";  // what a row of basis "early" is judged on (cardstats.py, cli.EARLY)


// ------------------------------------------------------- per-card numbers
// A CardStats (forge's cardstats.py): {games, bad, old, of, matchups, enough, min_games, min_split, basis,
// early_of, rows, commander}. games: the games with card data; of: all the counted games of the results it
// comes from; bad: games whose card log failed its checks (that every card move adds up), left out; old:
// games an earlier version of the card log kept (it counted a cast Forge's AI couldn't finish as a cast),
// left out too. basis: "early" when the verdicts are on "in hand by turn 3" (a row's early_games,
// early_share, wr_early and wr_not_early, out of the early_of games that counted it), "drawn" when the
// games were kept before that was counted; an older server sends none. enough: the games the verdicts are on
// (early_of with basis "early", else games) reach min_games. compared: the rows judged together
// (their verdicts' family); spread: how far real card effects spread from 0, what a row's best estimate is
// pulled toward 0 by. other_engine_games (the deck page's only): games of the list played with another engine
// than today's, left out. Shares are 0 to 1, or null when there's nothing to divide by.

/** The matchup page's per-card part: one panel per side (side by side when there's room), each with its
 * commander, spells and lands. A side without card data (null) says so. */
function cardStatsPart(r, sides) {
  const stats = r.cards.find(Boolean);
  const commander = r.cards.some((side) => side && (side.commander || []).length);
  return el("details", { class: "more mu-cards" },
    el("summary", { text: "How each deck's cards played" }),
    cardStatsCoverage(stats),
    stats.games ? [cardStatsBasis(stats), cardStatsKey(commander),
      el("div", { class: "panels" }, sideTitles(sides).map((title, i) => el("section", { class: "panel" },
        el("h3", { text: title }),
        r.cards[i] ? cardStatsGroups(r.cards[i], { links: true, group: `matchup-cards-${i}` })
          : el("p", { class: "sub", text: "No card data for this deck." }))))]
      : null);
}

/** Where the numbers come from: "From 600 of the 1,400 games: ..." (the rest played without the card
 * log, logged by an earlier version of it, or with a card log that failed its checks), and "Early numbers"
 * until min_games games the verdicts are on have card data (with basis "early" beside an earlier card log's
 * games, those that counted in hand by turn 3, early_of). With no counted games, why there are none.
 * deckPage: pooled over every saved matchup of the list. */
function cardStatsCoverage(stats, deckPage = false, { otherSaid = false } = {}) {
  const games = stats.games || 0, of = Math.max(stats.of || 0, games), bad = stats.bad || 0, old = stats.old || 0;
  const without = Math.max(0, of - games - bad - old);
  const across = deckPage ? `, across ${plural(stats.matchups || 0, "matchup")}` : "";
  // What the checks are for, said once: only one of the two sentences that name them is shown.
  const checks = "(which make sure every card move adds up)";
  // Games an earlier card log kept (its runs say "Card log on."): its tallies counted a cast Forge's AI
  // started and couldn't finish as a cast, so they're left out, but those games weren't played without it.
  const earlier = `${old === 1 ? "was" : "were"} logged by an earlier version of the card log, which counted casts ` +
    "differently";
  // The deck page's games of this list played with another engine than today's (list_cards' other_engine_games:
  // before the engine changes, or plain Forge's): the numbers pool only today's engine's games, so they're left
  // out, though they may well have card data of their own (each such result's page shows it).
  // otherSaid: the deck page already says, once, that this list's games were all an earlier engine's.
  const other = otherSaid ? 0 : stats.other_engine_games || 0;
  const otherEngine = "played with an earlier engine, or without the card log";
  const parts = [];
  if (!games) {
    const whose = old >= of ? `${deckPage ? "This list's" : "The"} ${gamesWords(old)}`
      : `${thousands(old)} of ${deckPage ? "this list's" : "the"} ${gamesWords(of)}`;
    const badWords = `${bad === 1 ? "it" : "each game's log"} failed its checks ${checks}`;
    const left = other ? ` ${thousands(other)} more ${other === 1 ? "was" : "were"} ${otherEngine}, so ` +
      `${other === 1 ? "it's" : "they're"} left out.` : "";
    // One short line, then why (none when nothing was counted at all).
    const why = old
      ? `${whose} ${earlier}${bad ? `, and the card log was kept for ${thousands(bad)} more ` +
          `game${bad === 1 ? "" : "s"}, but ${badWords}` : ""}. Play more games to get some.` + left
      : bad ? `The card log was kept for ${gamesWords(bad)}, but ${badWords}.` + left
        : other ? `This list's ${gamesWords(other)} ${other === 1 ? "was" : "were"} ${otherEngine}, and these ` +
            "numbers count only today's engine's games. Play more games, or replay those matchups with today's " +
            "engine, to get some."
          : "";
    parts.push(emptyBox("No per-card numbers yet."), why ? el("p", { class: "sub", text: why }) : null);
    return parts;
  }
  const why = [];
  if (without) {
    why.push(`${thousands(without)} ${without === 1 ? "was" : "were"} played without the card log (before ` +
      "Deck Lab kept one, or while it was off)");
  }
  if (old) why.push(`${thousands(old)} ${earlier}, so ${old === 1 ? "it's" : "they're"} left out`);
  if (bad) why.push(`${thousands(bad)} ${bad === 1 ? "game's card log failed its" : "games' card logs failed their"} ` +
    `checks ${checks}, so ${bad === 1 ? "it's" : "they're"} left out`);
  parts.push(el("p", { class: "sub", text: (of > games
    ? `From ${thousands(games)} of ${deckPage ? "this list's" : "the"} ${gamesWords(of)}${across}: ${why.join("; ")}.`
    : `From ${deckPage ? "this list's" : "the"} ${gamesWords(games)}${across}, every one with card data.`) +
    (other ? ` ${thousands(other)} more of this list's games ${other === 1 ? "was" : "were"} ${otherEngine}, so ` +
      `${other === 1 ? "it's" : "they're"} left out: replaying those matchups with today's engine plays them again.`
      : "") }));
  if (!stats.enough) {
    const settled = stats.min_games || CARD_STATS_GAMES;
    // Below settled games a card's 95% range is wider than about ±7 points (cardstats.MIN_CARD_GAMES says
    // why); the words give no number, so they hold if the threshold moves. The server counts the games the
    // verdicts are on: beside games an earlier card log kept, only those that counted in hand by turn 3.
    const early = stats.basis === "early" ? Math.min(stats.early_of || 0, games) : games;
    const sofar = early < games ? `${thousands(early)} of the ${gamesWords(games)} counted in hand by turn 3, ` +
      "which the verdicts are on" : `${gamesWords(games)} so far`;
    parts.push(el("p", { class: "card-early" }, status("warn", "Early numbers"),
      ` Only ${sofar}: read these as rough until there are ${thousands(settled)} or more ` +
      "(with fewer, chance alone can move a card's win-rate difference by many points)."));
  }
  return parts;
}

/** What the verdicts are on, said once: "in hand by turn 3" (basis "early", with how many of the games
 * counted it when an earlier card log kept some), or, for games kept before that was counted (basis
 * "drawn"), "drawn at any point", which leans with game length. Nothing from an older server (no basis). */
function cardStatsBasis(stats) {
  if (stats.basis === "early") {
    const early = stats.early_of || 0, games = stats.games || 0;
    return el("p", { class: "sub card-basis", text: "Won more or less is judged on the games a copy was in hand " +
      "by the deck's own turn 3 (the opening hand, or drawn by then) against the rest. By turn 3 every game has " +
      "seen about as many cards, so this doesn't lean with game length as \"drawn at any point\" does (long " +
      "games draw more cards); each card's win rates when drawn follow its verdict." +
      (early < games ? ` In hand by turn 3 was counted in ${thousands(early)} of the ${gamesWords(games)}: an ` +
        "earlier card log kept the rest." : "") });
  }
  if (stats.basis === "drawn") {
    return el("p", { class: "sub card-basis", text: "These games were kept before Deck Lab counted whether a copy " +
      "was in hand by turn 3, so won more or less is judged on the games a card was drawn in at any point. That " +
      "leans with game length: long games draw more cards, so a deck that wins its long games has cards that " +
      "look good for it." });
  }
  return null;
}

/** What each figure means, said once above the tables. commander: the commander's figures too. */
function cardStatsKey(commander = false) {
  const items = [
    commander ? ["Commander", "Cast in is the share of games it was cast at least once; casts counts every " +
      "cast, recasts too; turn is the average turn it was first cast."] : null,
    ["Drawn", "The share of games a copy reached the hand, the opening hand included."],
    ["Cast", "The share of the copies drawn that were cast (for a land, played)."],
    ["Stuck", "The share of the copies drawn still in hand when the game ended: spells too costly or with " +
      "nothing to do, or lands beyond the turns to play them. A copy cast, returned to hand and kept counts " +
      "as both cast and stuck."],
    ["Turn", "The average turn a copy was first cast or played, counting each player's own turns."],
    // It holds for both bases (cardStatsBasis, just above it, says which the verdicts are on).
    ["Won ... when", "The deck's win rate in games where a copy was in hand by its own turn 3 (the opening " +
      "hand, or drawn by then) and where none was, or, for games kept before Deck Lab counted that, where a " +
      "copy was drawn at any point and where none was; and the difference in percentage points with its " +
      "95% range in brackets. Over several matchups the difference is worked out matchup by matchup, so a " +
      "card in hand more often against an easy opponent isn't given that opponent's wins. " +
      "Long games draw more cards, so game length alone can make a card drawn at any point look better or " +
      "worse; by turn 3 every game has seen about as many cards. These are plain shares of games won, " +
      "not balanced for play and draw."],
    ["Best estimate", "The difference pulled toward 0, the more so the fewer the games: most cards move a " +
      "deck's win rate by a few points at most, so a big difference from few games is mostly chance."],
    ["Verdict", `"Won more" or "won less" needs ${CARD_SPLIT_GAMES} games each way and a difference that ` +
      "stands out among the cards compared: among 20 or more cards a few ranges miss 0 by chance alone, so " +
      "a verdict is kept for those that stand out from them (at most 1 in 10 verdicts is chance, on average)."],
    ["Lands", "No win-rate verdict, only the two win rates, when a copy was drawn at any point and when not: " +
      "the games without a copy of a land were mostly games short of lands, or of its colour, so they say how " +
      "those games went, not what the land did."],
  ].filter(Boolean);
  return el("dl", { class: "card-key" }, items.map(([term, words]) => el("div", {},
    el("dt", { text: term }), el("dd", { text: words }))));
}

/** One list's tables: its commander, then its spells, then its lands, each under a small heading.
 * links: card names open the card viewer (cardLink: a name whose card the page has), as one viewer group
 * (group: the deck page's "names"; the matchup page's one per deck), so a swipe goes through the list. */
function cardStatsGroups(stats, { links = false, group = "names" } = {}) {
  const rows = stats.rows || [];
  const commander = stats.commander || [];
  const spells = rows.filter((row) => row.land !== true);
  const lands = rows.filter((row) => row.land === true);
  return el("div", { class: "card-groups" },
    commander.length ? [el("h4", { text: commander.length > 1 ? "Commanders" : "Commander" }),
      commanderStatsTable(commander, stats, links && group)] : null,
    spells.length ? [el("h4", { text: "Spells" }), cardStatsTable(spells, stats, { links: links && group })] : null,
    lands.length ? [el("h4", { text: "Lands" }), cardStatsTable(lands, stats, { lands: true, links: links && group })] : null);
}

/** A card's name for a table: with links (its viewer group's name), a name that opens the card viewer
 * (cardLink), else plain text; ×N for its copies. */
function cardStatsName(name, qty, links) {
  if (links) return cardLink({ name, qty }, typeof links === "string" ? links : "names");
  return [name, qty > 1 ? el("span", { class: "x", text: `×${qty}` }) : null];
}

/** A share as a whole percentage for a table cell, or "-" when there's nothing to divide by. */
function shareCell(x) { return x == null ? "-" : pctShort(x); }

/** An average turn for a table cell, always with its one decimal ("3.0"), or "-" when never cast. */
function turnCell(x) { return x == null ? "-" : Number(x).toFixed(1); }

/** Spells' or lands' numbers: one <tbody> per card, its four numbers on the first row and its win rates
 * (and anything else to say) across the whole width below, so names have room on a phone. A card drawn
 * and never cast (or played) is marked in words, and tinted. */
function cardStatsTable(rows, stats, { lands = false, links = false } = {}) {
  return el("table", { class: "data card-table" },
    el("caption", { class: "sr-only", text: lands ? "Each land: drawn, played, stuck in hand, turn played"
      : "Each spell: drawn, cast, stuck in hand, turn cast" }),
    el("colgroup", {}, el("col"), el("col", { class: "c-n" }), el("col", { class: "c-n" }), el("col", { class: "c-n" }),
      el("col", { class: "c-turn" })),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: lands ? "Land" : "Card" }),
      ["Drawn", lands ? "Played" : "Cast", "Stuck", "Turn"].map((text) => el("th", { scope: "col", class: "num", text })))),
    rows.map((row) => {
      const never = row.drawn_games > 0 && !row.cast && !row.other_casts;
      return el("tbody", { class: never ? "is-missing" : null },
        el("tr", {},
          el("th", { scope: "row", class: "name-cell" }, cardStatsName(row.name, row.qty, links)),
          el("td", { class: "num", text: shareCell(row.drawn_share) }),
          el("td", { class: "num missing-n", text: shareCell(row.cast_share) }),
          el("td", { class: "num", text: shareCell(row.stuck_share) }),
          el("td", { class: "num", text: turnCell(row.avg_turn) })),
        el("tr", { class: "label-row" }, el("td", { colspan: 5 },
          el("p", { class: "card-notes" }, cardStatsNotes(row, stats, lands, never)))));
    }));
}

/** Under a card's numbers: never drawn, or drawn and never cast; its win rates when drawn and not (for a
 * spell judged on "in hand by turn 3", basis "early": those rates and its verdict first, then how often it
 * was in hand by then and its drawn rates, earlyContext); and casts from anywhere but the hand and copies
 * discarded, when there were any (counted whether or not a copy was drawn: a card milled and cast from the
 * graveyard was never drawn). A land's rates are always its drawn ones: it gets no verdict either way. */
function cardStatsNotes(row, stats, lands, never) {
  const parts = [];
  if (!row.drawn_games) {
    parts.push(`Not drawn in any of the ${gamesWords(stats.games || 0)}.`);
  } else {
    if (never) parts.push(status("warn", lands ? "Drawn, never played" : "Drawn, never cast"), " ");
    if (row.basis === "early" && row.land !== true) {
      parts.push(winSplitWords(row, stats, EARLY_ACT, row.wr_early, row.wr_not_early, row.early_games,
        stats.early_of || 0), " ", earlyContext(row));
    } else {
      parts.push(winSplitWords(row, stats, "drawn", row.wr_drawn, row.wr_not, row.drawn_games));
    }
  }
  const more = [];
  if (row.other_casts) more.push(`cast ${plural(row.other_casts, "time")} from anywhere but the hand (the ` +
    "graveyard, exile, the library...)");
  if (row.discarded) more.push(`${plural(row.discarded, "copy", "copies")} discarded or cycled from hand`);
  if (more.length) parts.push(` ${capitalise(more.join("; "))}.`);
  return parts;
}

/** After a basis "early" row's verdict: how often a copy was in hand by turn 3, and the deck's win rates
 * when one was drawn at any point and when not, for context (they lean with game length, so they get no
 * verdict): "In hand by turn 3 in 40% of games. Drawn at any point: won 53.1%, 49.0% when not." */
function earlyContext(row) {
  const share = row.early_share == null ? "" : `In hand by turn 3 in ${pctShort(row.early_share)} of games. `;
  const drawn = row.wr_drawn && row.wr_not
    ? `Drawn at any point: won ${ratePct(row.wr_drawn.value)}, ${ratePct(row.wr_not.value)} when not.`
    : row.wr_drawn ? `Drawn in every game, which the deck won ${ratePct(row.wr_drawn.value)} of.` : "";
  return `${share}${drawn}`.trim();
}

/** A win-rate difference's range end in percentage points: 0.0912 -> "+9", -0.031 -> "−3", 0 -> "0". An
 * end that isn't 0 never shows as "0": it gets the decimals it needs (0.004 -> "+0.4"), so a range that
 * stops short of 0 (a clear verdict) never looks as if it reached it. */
function pointsWords(x) {
  if (x == null || Number.isNaN(x)) return "?";
  const v = x * 100;
  let digits = 0;
  while (v !== 0 && digits < 4 && Number(Math.abs(v).toFixed(digits)) === 0) digits++;
  const size = Math.abs(v).toFixed(digits);
  return Number(size) === 0 ? "0" : `${v > 0 ? "+" : "−"}${size}`;
}

/** A win rate in tenths of a percentage point: 0.4449 -> 445. */
function rateTenths(x) { return Math.round(x * 1000); }

/** A win rate as the per-card notes show it, to one decimal: 0.4449 -> "44.5%". */
function ratePct(x) { return `${(rateTenths(x) / 10).toFixed(1)}%`; }

/** The difference between two win rates ({value}) as ratePct shows them: 0.4449 and 0.4512 ->
 * "−0.6 points" (44.5% and 45.1%), so it always matches the rates beside it. The deck page's lead shows
 * it too, so a card's difference reads the same there as in its table. */
function gapWords(yes, no) {
  const gap = rateTenths(yes.value) - rateTenths(no.value);
  return `${gap > 0 ? "+" : gap < 0 ? "−" : ""}${(Math.abs(gap) / 10).toFixed(1)} points`;
}

/** A difference (a share) in points to one decimal, signed: 0.1032 -> "+10.3", -0.0004 -> "0.0". */
function tenthsWords(x) {
  const tenths = Math.round(x * 1000);
  return `${tenths > 0 ? "+" : tenths < 0 ? "−" : ""}${(Math.abs(tenths) / 10).toFixed(1)}`;
}

/** Are stats pooled over more than one matchup by a server that works each card's difference out matchup by
 * matchup (it judges the rows together: compared)? Then the difference isn't the gap between the two pooled
 * rates beside it, and the server's is shown. */
function matchupByMatchup(stats) { return stats.compared != null && (stats.matchups || 0) > 1; }

/** A judged row whose range is clear of 0 but which doesn't stand out among the cards compared (not a
 * discovery), so its verdict is "unclear": a range like it can turn up by chance among that many cards.
 * Only among two or more (stats.compared): one card compared alone can still miss being a discovery, its
 * p-value being worked out a little differently from its range, but "by chance among 1 card" says nothing. */
function withinChance(row, stats) {
  return (stats.compared || 0) > 1 && row.discovery === false && row.verdict === "unclear" && !!row.diff &&
    (row.diff.low > 0 || row.diff.high < 0);
}

/** The deck's win rates when a card was drawn (act "drawn"; a commander's: "cast") and when not, the
 * difference with its range, its best estimate and a verdict, once the card is judged (both have min_split
 * games). The rates have one decimal, and the difference beside them is theirs as shown ("44.5%, 45.1%:
 * −0.6 points"), so the sentence never contradicts itself; the range is the server's. Over several matchups
 * (matchupByMatchup) the difference is the server's instead, worked out matchup by matchup ("55.0%, 47.0%;
 * matchup by matchup, +3.1 points"). A range clear of 0 that isn't a discovery says why there's no verdict
 * (withinChance). A row from an older server (no best estimate) reads as before. A land is never judged
 * (cardstats.py): it gets its win rates and "No verdict for a land", and the key says why once. Before a
 * card is judged, only how many games each way there are, or, for a card in nearly every game
 * (NEARLY_EVERY_GAME), that there are too few games without it to compare with: more games barely add to
 * those. yes, no: {value, low, high, games, wins}; inGames: games it was drawn (cast; in hand by turn 3, act
 * EARLY_ACT) in, out of games (the stats' games; for EARLY_ACT, its early_of). A "won more" or "won less"
 * on when drawn from a server that also counts in hand by turn 3 (row.basis "drawn": its games were kept
 * before that was counted) says it leans with game length. */
function winSplitWords(row, stats, act, yes, no, inGames, games = stats.games || 0) {
  const outGames = Math.max(0, games - (inGames || 0));
  const split = stats.min_split || CARD_SPLIT_GAMES;
  if (row.land === true && yes) {
    const rates = no
      ? `Won ${ratePct(yes.value)} of the ${gamesWords(inGames)} it was ${act} in, ${ratePct(no.value)} of the ` +
        `${gamesWords(no.games)} without a copy.`
      : `${capitalise(act)} in every one of the ${gamesWords(games)}, which the deck won ${ratePct(yes.value)} of.`;
    return `${rates} No verdict for a land.`;
  }
  if (!row.judged || !row.diff || !yes || !no) {
    if (games && outGames < split && (inGames || 0) / games >= NEARLY_EVERY_GAME) {
      return outGames
        ? `${capitalise(act)} in nearly every game (${thousands(inGames)} of ${thousands(games)}), so there are too ` +
          `few games without it to compare with: not ${act} in ${thousands(outGames)} (it takes ${split} each way).`
        : `${capitalise(act)} in every one of the ${gamesWords(games)}, so there are no games without it to ` +
          `compare with (it takes ${split} each way).`;
    }
    return `Not enough games to tell a win-rate difference yet: ${act} in ${thousands(inGames || 0)}, not ${act} ` +
      `in ${thousands(outGames)} (it takes ${split} of each).`;
  }
  const d = row.diff;
  const leans = row.basis === "drawn" && (row.verdict === "more" || row.verdict === "less")
    ? " (leans with game length)" : "";
  const verdict = row.verdict === "more" ? `Won more when ${act}${leans}`
    : row.verdict === "less" ? `Won less when ${act}${leans}` : "No clear difference";
  if (row.shrunk == null) {
    return [`Won ${ratePct(yes.value)} when ${act}, ${ratePct(no.value)} when not: `,
      el("b", { text: gapWords(yes, no) }), " ",
      el("span", { class: "card-range", text: `(${pointsWords(d.low)} to ${pointsWords(d.high)}).` }), " ",
      el("b", { text: `${verdict}.` })];
  }
  const pooled = matchupByMatchup(stats);
  const chance = withinChance(row, stats);
  return [`Won ${ratePct(yes.value)} when ${act}, ${ratePct(no.value)} when not`,
    pooled ? "; matchup by matchup, " : ": ",
    el("b", { text: pooled ? `${tenthsWords(d.value)} points` : gapWords(yes, no) }), " ",
    el("span", { class: "card-range", text: `(${pointsWords(d.low)} to ${pointsWords(d.high)}),` }), " ",
    el("span", { class: "card-best", text: `best estimate ${tenthsWords(row.shrunk)}.` }), " ",
    el("b", { text: `${verdict}${chance ? ":" : "."}` }),
    chance ? ` among ${plural(stats.compared || 0, "card")} compared, a range this far from 0 can turn up by ` +
      "chance." : null];
}

/** The commander's numbers: games it was cast in, every cast, the turn it was first cast; its win
 * rates when cast and not across the row below. */
function commanderStatsTable(rows, stats, links) {
  return el("table", { class: "data card-table" },
    el("caption", { class: "sr-only", text: "The commander: games cast in, casts, turn first cast" }),
    el("colgroup", {}, el("col"), el("col", { class: "c-n" }), el("col", { class: "c-n" }), el("col", { class: "c-turn" })),
    el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Card" }),
      ["Cast in", "Casts", "Turn"].map((text) => el("th", { scope: "col", class: "num", text })))),
    rows.map((c) => el("tbody", { class: c.cast_games ? null : "is-missing" },
      el("tr", {},
        el("th", { scope: "row", class: "name-cell" }, cardStatsName(c.name, 1, links)),
        el("td", { class: "num missing-n", text: shareCell(c.cast_share) }),
        el("td", { class: "num", text: thousands(c.casts || 0) }),
        el("td", { class: "num", text: turnCell(c.avg_first_turn) })),
      el("tr", { class: "label-row" }, el("td", { colspan: 4 }, el("p", { class: "card-notes" }, c.cast_games
        ? winSplitWords(c, stats, "cast", c.wr_cast, c.wr_not_cast, c.cast_games)
        : [status("warn", "Never cast"), ` in any of the ${gamesWords(stats.games || 0)}.`]))))));
}

/** The deck page's lead: what stands out in the list's per-card numbers, counted. The commander's
 * casts; the spells most often stuck in hand (from STUCK_MIN_COPIES drawn copies, at STUCK_NOTED or
 * more); how many lands were left in hand; cards drawn and never cast; and the clearest win-rate
 * differences, CLEAR_SHOWN each way (never a land's: lands get no verdict), each as its row shows it
 * (matchup by matchup over several matchups): on in hand by turn 3 or not when the rows are judged on it
 * (stats.basis "early"), else on drawn or not. With none, how many ranges were clear of 0 by chance. */
function standOutParts(stats) {
  const rows = stats.rows || [];
  const items = [];
  for (const c of stats.commander || []) {
    items.push(el("li", {}, el("b", { text: "Commander: " }), cardLink({ name: c.name }), c.cast_games
      ? ` cast in ${pctShort(c.cast_share)} of games, first on turn ${turnCell(c.avg_first_turn)} on average.`
      : ` never cast in any of the ${gamesWords(stats.games || 0)}.`));
  }
  const never = rows.filter((r) => r.drawn_games > 0 && !r.cast && !r.other_casts);
  // Cards never cast are stuck every time they're drawn: they're listed on their own below.
  const counted = rows.filter((r) => r.land !== true && !never.includes(r) && r.copies_drawn >= STUCK_MIN_COPIES &&
    r.stuck_share != null).sort((x, y) => y.stuck_share - x.stuck_share || x.name.localeCompare(y.name));
  // Spells drawn, but too few times to count: what's said about the counted ones isn't said about these.
  const few = rows.filter((r) => r.land !== true && !never.includes(r) && r.copies_drawn > 0 &&
    r.copies_drawn < STUCK_MIN_COPIES).length;
  const fewWords = few ? ` (${plural(few, "spell")} drawn fewer times ${few === 1 ? "isn't" : "aren't"} counted)` : "";
  const stuck = counted.filter((r) => r.stuck_share >= STUCK_NOTED).slice(0, STUCK_SHOWN);
  if (stuck.length) {
    items.push(el("li", {}, el("p", {}, el("b", { text: "Most often stuck in hand: " }),
      "the share of each one's drawn copies still in hand when the game ended, among the spells with " +
      `${STUCK_MIN_COPIES} or more copies drawn${fewWords}.`),
    standOutCards(stuck, (r) => `${pctShort(r.stuck_share)} of ${thousands(r.copies_drawn)} drawn`)));
  } else if (counted.length) {
    items.push(el("li", {}, el("b", { text: "Rarely stuck in hand: " }), `no spell with ${STUCK_MIN_COPIES} or ` +
      `more copies drawn had more than ${pctShort(counted[0].stuck_share)} of them still in hand when the game ` +
      `ended${fewWords}.`));
  } else {
    items.push(el("li", {}, el("b", { text: "Stuck in hand: " }), "too few copies drawn to say yet (a spell " +
      `needs ${STUCK_MIN_COPIES}).`));
  }
  const lands = rows.filter((r) => r.land === true);
  const landsDrawn = lands.reduce((sum, r) => sum + (r.copies_drawn || 0), 0);
  if (landsDrawn) {
    const left = lands.reduce((sum, r) => sum + (r.stuck || 0), 0);
    items.push(el("li", {}, el("b", { text: "Lands left in hand: " }), `${pctShort(left / landsDrawn)} of the ` +
      `${thousands(landsDrawn)} lands drawn were still in hand when the game ended (more lands than turns to play them).`));
  }
  if (never.length) {
    items.push(el("li", {}, el("p", {}, status("warn", "Drawn, never cast"), " Drawn, and never cast or played " +
      "in any of the games:"),
    standOutCards(never, (r) => `drawn in ${gamesWords(r.drawn_games)}`)));
  }
  // Lands are never judged (cardstats.py): a land's games without a copy were mostly short of lands.
  const early = stats.basis === "early";
  const judged = early
    ? rows.filter((r) => r.judged && r.diff && r.wr_early && r.wr_not_early && r.land !== true)
    : rows.filter((r) => r.judged && r.diff && r.wr_drawn && r.wr_not && r.land !== true);
  const act = early ? EARLY_ACT : "drawn";
  const more = judged.filter((r) => r.verdict === "more").sort((x, y) => y.diff.value - x.diff.value);
  const less = judged.filter((r) => r.verdict === "less").sort((x, y) => x.diff.value - y.diff.value);
  const shown = [...more.slice(0, CLEAR_SHOWN), ...less.slice(0, CLEAR_SHOWN)];
  const hidden = more.length + less.length - shown.length;
  const pooled = matchupByMatchup(stats);
  // From a server that judges the rows together, only those that stand out from chance get a verdict.
  const together = (stats.compared || 0) > 1
    ? `; only those that stand out among the ${plural(stats.compared, "card")} compared are listed` : "";
  // Drawn at any point leans with game length; in hand by turn 3 doesn't (cardStatsBasis says why).
  const cause = early ? "By turn 3 every game has seen about as many cards, so game length isn't what " +
    "these say." : stats.basis === "drawn" ? "These games were kept before in hand by turn 3 was counted: long " +
    "games draw more cards, so game length can be the cause rather than the card."
    : "Long games draw more cards, so game length can be the cause rather than the card.";
  if (shown.length) {
    items.push(el("li", {}, el("p", {}, el("b", { text: "Clear win-rate differences: " }),
      `the deck's win rate when each was ${early ? `${EARLY_ACT} against when none was` : "drawn against when " +
        "it wasn't"}, in percentage points, with the 95% range${pooled ? ", worked out matchup by matchup" : ""}` +
      `${together}. ${cause}`),
    standOutCards(shown, (r) => pooled
      ? `${tenthsWords(r.diff.value)} points (${pointsWords(r.diff.low)} to ${pointsWords(r.diff.high)})`
      : early ? `${gapWords(r.wr_early, r.wr_not_early)} (${pointsWords(r.diff.low)} to ${pointsWords(r.diff.high)})`
        : `${gapWords(r.wr_drawn, r.wr_not)} (${pointsWords(r.diff.low)} to ` + `${pointsWords(r.diff.high)})`),
    hidden ? el("p", { class: "sub", text: `${plural(hidden, "more card")} in the table below.` }) : null));
  } else if (judged.length) {
    const chance = judged.filter((r) => withinChance(r, stats)).length;
    items.push(el("li", {}, el("b", { text: "No clear win-rate difference: " }), "none of the " +
      `${plural(judged.length, "card")} with the games to tell won clearly more or less often when ${act}` +
      (chance ? `: ${chance} had a range clear of 0, which chance alone can do among that many cards.` : ".")));
  } else if (rows.length) {
    items.push(el("li", {}, el("b", { text: "Win-rate differences: " }), "too few games to tell yet (a card " +
      `needs ${stats.min_split || CARD_SPLIT_GAMES} games ${act} and as many not ${act}).`));
  }
  return el("ul", { class: "stand-out" }, items);
}

/** A few cards that stand out, each with its number (words(row)) beside it. */
function standOutCards(rows, words) {
  return el("ul", { class: "stand-out-cards" }, rows.map((r) => el("li", {}, cardLink({ name: r.name, qty: r.qty }),
    el("span", { class: "stand-out-n", text: words(r) }))));
}

/** The deck page's "How its cards played": the per-card numbers pooled over every saved matchup of this
 * list (forge.list_cards), leading with what stands out, then every card's numbers, collapsed. Nothing
 * from an older server (no "cards"), or while this list has no saved results of its own (results of the
 * deck's earlier lists, sides[0].current false, don't count: list_cards pools only this list's). Games
 * an earlier card log kept, or games of this list played only with another engine than today's, give
 * stats with no counted games (cards.old, cards.other_engine_games), which cardStatsCoverage explains;
 * no stats at all (null) means no saved game of this list kept a card log. */
function deckCardStats(m, version, { otherSaid = false } = {}) {
  if (!("cards" in m)) return null;
  const stats = m.cards;
  // Only an earlier engine's games, which the page has said once (earlierEngineLine): nothing more to add here.
  if (otherSaid && stats && !stats.games && !stats.old && !stats.bad) return null;
  const head = el("h3", { text: "How its cards played" });
  if (!stats) {
    if (!(m.results || []).some((r) => r.sides && r.sides[0] && r.sides[0].current !== false)) return null;
    return [head, el("p", { class: "sub", text: `None of this ${version}'s saved games was played with the card ` +
      "log, which follows every card through Forge's games, so there are no per-card numbers yet." })];
  }
  return [head, cardStatsCoverage(stats, true, { otherSaid }),
    stats.games ? [cardStatsBasis(stats), standOutParts(stats),
      el("details", { class: "more mu-cards" }, el("summary", { text: "Every card's numbers" }),
        cardStatsKey((stats.commander || []).length > 0), cardStatsGroups(stats, { links: true }))] : null];
}
