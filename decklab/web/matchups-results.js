/* Finished-matchup verdicts, trust labels, scores and details of the engine that played them.
Loaded after matchups.js, matchups-overview.js and matchups-detail.js, before matchups-cards.js.
Shared helpers and per-card panels are called only once all deferred scripts have loaded. */
"use strict";

// --------------------------------------------------------------- the result

// The lead's verdicts (forge.views._lead), worded as on the command line (views.VERDICT_WORDS):
// ahead, about even (within 5 points of an even split, the owner's margin), both, or not settled.
const LEAD_WORDS = {
  ahead: (leader) => `${leader} is ahead in these AI games: its win rate is higher after allowing for uncertainty.`,
  slightly_ahead: (leader) => `${leader} is slightly ahead (by under 5 points) in these AI games: its win rate ` +
    "is higher after allowing for uncertainty, and within 5 points of an even split.",
  about_even: () => "About even in these AI games: after allowing for uncertainty, the two win rates are within " +
    "5 points of an even split.",
  not_settled: () => "Not settled yet: the range still allows either deck to be ahead, perhaps by more than " +
    "5 points. More games would narrow it.",
};

/** Which deck is ahead, from the result's lead (forge.views._lead: side 0 is ta's deck). When every game
 * has a winner it's judged on the headline range; draws, timeouts and errors count against both decks, so
 * then it compares both win rates instead, and one deck's range below 50% doesn't by itself put the other
 * ahead. */
function matchupVerdict(result, ta, tb) {
  if (result.not_meaningful) return "It doesn't say which deck is ahead: see the box above.";
  const lead = result.lead;
  if (!lead || !LEAD_WORDS[lead.verdict]) return "No comparison is available yet.";
  return LEAD_WORDS[lead.verdict](lead.side === 1 ? tb : ta);
}

/** What the headline's range is for, under it: the lead is judged on it when every game had a winner;
 * otherwise (draws, timeouts or errors, which count against both decks) on a comparison of both. */
function rangeNote(r) {
  const games = thousands(r.games);
  const base = "This approximate 95% confidence range describes sampling uncertainty in the win rate of " +
    `Forge's AI playing these lists, from ${games} games.`;
  if (r.lead && r.lead.basis === "comparison") {
    return `${base} Some games had no winner (draws, timeouts or errors), which count against both decks, so the ` +
      "lead compares both decks' win rates with a conservative uncertainty range instead; 50% is just a " +
      "reference mark here.";
  }
  return `${base} Every game had a winner, so the lead is judged on this range: a deck is ahead when it leaves ` +
    "out 50%, and the two are about even when it stays between 45% and 55%.";
}

/** "Two results of 1,600 games like this one can differ by about 3-4 points by chance alone..." from the
 * result's noise_points (forge.views._noise_points), or null. */
function noiseWords(points, games) {
  if (points == null) return null;
  let size;
  if (points < 1) size = "under 1 point";
  else {
    const low = Math.floor(points), high = Math.ceil(points);
    size = low === high ? `about ${low} points` : `about ${low}-${high} points`;
  }
  return `Two results of ${thousands(games)} games like this one can differ by ${size} by chance alone, so ` +
    "treat smaller differences as noise.";
}

const TEMPO_WORDS = "Forge likely understates going first in tempo and counterspell mirrors: in Deck Lab's " +
  "tests going first helped much less in a tempo mirror than in a ramp mirror.";
const COMMANDER_WORDS = "Commander results are indicative only: Forge plays Commander decks one against one " +
  "here, and its Commander games haven't been checked as closely as its 60-card games.";
// Why Forge's AI misplays a card (forge.ai.WEAK_KINDS), for the pilot box's list; as on the command line.
const WEAK_WORDS = {
  remove_all: "never cast: its card script tells the AI to leave it out",
  etb: "not cast while its enters ability would do nothing useful",
  flash: "a flash creature with no enters ability: cast only at the end of the opponent's turn",
  team_pump: "pumps the whole team, which the AI judges one creature at a time",
  strict_targets: "the AI only aims it at {targets}",
  counterspell: "a counterspell: the AI never keeps mana open for it",
};

// The team pump measurement as the command line words it (cli_output). It names no deck, so the box never reads
// as if another deck's numbers were its own (MU-m3).
const PUMPS_MEASURED = "Holding the spells back put a go-wide deck 12 to 15 points too low in Deck Lab's tests.";

/** What Forge's AI does wrong with a card of forge.ai._pilot's "cards": its first kind's words. */
function weakWords(card) {
  const kind = card.why[0];
  const detail = (card.detail || {})[kind] || "";
  if (kind === "etb" && detail === "no_target") {
    return "held until its enters ability has a target, unless the AI is in danger";
  }
  if (kind === "strict_targets") {
    const min = /^Card\.cmcGE(\d+)$/.exec(detail);
    return WEAK_WORDS[kind].replace("{targets}", min ? `mana value ${min[1]} or more` : `its card script's targets (${detail})`);
  }
  return WEAK_WORDS[kind];
}

/** A list's team pumps (forge.ai._pilot) split into spells and permanents' abilities: "3 spells, 3
 * permanents' abilities" ("4 spells" when there are only spells); as on the command line. */
function pumpSplit(pilot) {
  const spells = pilot.team_pump_spells || 0;
  const abilities = (pilot.team_pumps || 0) - spells;
  const parts = [];
  if (spells) parts.push(`${spells} spell${spells === 1 ? "" : "s"}`);
  if (abilities) parts.push(abilities === 1 ? "1 permanent's ability" : `${abilities} permanents' abilities`);
  // With the team-pump fix forge.ai._pilot counts no team pumps, so its "team_pumps" reason never
  // comes up and this gives counts only; pilotReason says the fix with the reason that stands.
  return parts.join(", ");
}

/** Why Forge pilots a list poorly (forge.ai._pilot's "why"), or null when it doesn't; as on the command
 * line, after "Forge pilots <deck> poorly: ". Team pump spells and permanents' team pump abilities go
 * through the same test in Forge's AI, but only the spells were measured (a go-wide deck's 12 to 15
 * points), so that figure is given only when the list has some. */
function pilotReason(pilot) {
  if (!pilot || !pilot.poor) return null;
  const lower = "Its win rates here are probably lower than the real deck's.";
  if (pilot.why === "commander") return `Forge's AI never casts its commander or holds it back. ${lower}`;
  if (pilot.why === "team_pumps") {
    const measured = pilot.team_pump_spells ? ` ${PUMPS_MEASURED}` : "";
    return `${pilot.team_pumps} of its cards pump the whole team (${pumpSplit(pilot)}), which Forge's AI ` +
      `judges one creature at a time, so it uses them too rarely and attacks too little.${measured} ${lower}`;
  }
  const copies = (pilot.cards || []).reduce((sum, c) => sum + (c.qty || 0), 0);
  // With the team-pump fix (wave 3's pilot switch) its team pumps aren't counted: say the flag stands with it.
  const fix = pilot.team_pump_fix ? " (with Deck Lab's team-pump fix)" : "";
  return `${copies} of its cards are kinds Forge's AI misplays${fix}. ${lower}`;
}

/** The trust label for a list Forge pilots poorly (ai: its AiLimits, whose "pilot" is forge.ai._pilot's):
 * a box saying why, with the cards behind it and what the AI does wrong with each; null otherwise. On the
 * deck page (deckPage) its heading says "this deck". */
function pilotFlag(ai, title, { deckPage = false } = {}) {
  const reason = pilotReason(ai && ai.pilot);
  if (!reason) return null;
  const cards = ai.pilot.cards || [];
  return el("div", { class: "pilot-flag" }, markedBox("warn", deckPage ? "h3" : "h4",
    deckPage ? "Forge pilots this deck poorly" : `Forge pilots ${title} poorly`, [
      el("p", { text: reason }),
      cards.length ? el("ul", { class: "card-names pilot-cards" }, cards.map((c) => el("li", {},
        cardLink({ name: c.name, qty: c.qty }),
        el("span", { class: "pilot-why", text: (c.commander ? "the commander: " : "") + weakWords(c) })))) : null]));
}

/** "How far to trust these numbers" (R19), for "Why we're confident": the noise between results this size, the
 * tempo caveat when both decks hold counterspells, that Commander results are indicative only, a box for each
 * deck Forge pilots poorly, and what Forge's AI is like. */
function trustPart(r, data, titles) {
  const items = [];
  const noise = noiseWords(r.noise_points, r.games);
  if (noise) items.push(el("li", {}, status("info", "Noise"), " ", noise));
  const pilots = data.sides.map((s) => s.ai && s.ai.pilot);
  if (pilots.every((p) => p && p.counterspells)) items.push(el("li", {}, status("info", "Tempo"), " ", TEMPO_WORDS));
  if (data.format === "Commander") items.push(el("li", {}, status("info", "Commander"), " ", COMMANDER_WORDS));
  return el("div", { class: "mu-trust" },
    el("h3", { id: "h-trust", text: "How far to trust these numbers" }),
    items.length ? el("ul", { class: "trust-list" }, items) : null,
    // A commander never cast already has the caveat under the verdict saying the results mean nothing.
    data.sides.map((s, i) => (r.not_meaningful && s.ai && s.ai.commander_unplayable ? null : pilotFlag(s.ai, titles[i]))),
    el("p", { class: "sub", text: "Forge's computer players are weaker than people and handle some decks better " +
      "than others (straightforward attacking decks are easiest for it). Treat win rates as a comparison between " +
      "decks, not a prediction of real games." }));
}

/** The one caveat under the verdict (MU-04: at most one), the most important first: results that mean
 * nothing, a list that has changed since, a newer result of these lists (newer: its ListItem), a deck Forge
 * pilots poorly, Commander's rough guide. null when there's nothing to say. */
function caveatLine(r, data, titles, newer) {
  if (r.not_meaningful) {
    const which = data.sides.filter((s) => s.ai && s.ai.commander_unplayable).map((s) => s.title);
    return el("p", { class: "mu-caveat" }, status("crit", "Means nothing"), " Forge's AI never casts " +
      `${which.length ? `the commander of ${which.join(" and ")}` : "one deck's commander"}, so that deck played every ` +
      "game without it.");
  }
  const old = data.sides.filter((s) => s.current === false);
  if (old.length) {
    return el("p", { class: "mu-caveat" }, status("warn", "Older list"), ` ${old.map(sideTitle).join(" and ")} ` +
      `${old.length === 1 ? "has" : "have"} changed since these games, so this may not match ` +
      `${old.length === 1 ? "it" : "them"} any more.`);
  }
  if (newer) {
    return el("p", { class: "mu-caveat" }, status("info", "Newer result"), " These lists have played again since, " +
      "with today's engine: ", el("a", { href: itemHref(newer), text: "see the newer result" }), ".");
  }
  const poor = data.sides.findIndex((s) => s.ai && s.ai.pilot && s.ai.pilot.poor);
  if (poor >= 0) {
    return el("p", { class: "mu-caveat" }, status("warn", "Hard for Forge"), ` Forge plays ${titles[poor]} poorly, so ` +
      "its real chances are probably better than this (\"Why we're confident\" says why).");
  }
  if (data.format === "Commander") {
    return el("p", { class: "mu-caveat" }, status("info", "Rough guide"), " Commander results are a rough guide only.");
  }
  return null;
}

/** A finished matchup (MU-04): the verdict first ("Boros Burn is a big favourite: wins about 9 in 10")
 * with the first deck's win rate as a hero figure, how long ago it was played (stale once a list has changed
 * since) and its range bar with the 20 / 50 / 80 axis (sim-ui.js), at most one caveat line and Play more; then "Why we're confident" and "Details",
 * closed; then the per-card numbers and how the games were played, closed too. ctx.newer: a newer result of
 * these lists (its ListItem), when this one is an earlier engine's. */
function resultPart(data, page, ctx = {}) {
  const r = data.result;
  const [ta, tb] = sideTitles(data.sides);
  const wr = r.winrate || {};
  const muted = !!r.not_meaningful;
  const verdict = plainVerdict(r, data.sides.map(sideShort));
  const what = `${ta}'s win rate`;
  const section = el("section", { class: "mu-result", "aria-labelledby": "h-result" });
  section.append(el("div", { class: `panel mu-verdict mu-verdict-${verdict.kind}` },
    el("h2", { id: "h-result", text: verdict.text }),
    el("div", { class: "mu-figure" }, winRateFigure(wr, { size: "hero", what, games: r.games, barred: true }),
      freshnessBadge(r.updated, { changed: data.sides.some((s) => s.current === false) })),
    rangeBar(wr, { axis: true, muted, decorative: true }),
    caveatLine(r, data, [ta, tb], ctx.newer || null),
    actionsPart(page, data)));
  // The folded reading, in one column (beside the verdict from 1,600 px, from its top: MU-14).
  const reading = el("div", { class: "mu-reading" });
  section.append(reading);
  add(reading, [matchupRealGames(data)]);
  reading.append(el("details", { class: "more mu-why" },
    el("summary", { text: "Why we're confident" }),
    el("p", {}, el("b", { text: `${ta} won ${rateWords(wr)} of ${gamesWords(r.games)}` }),
      wr.balanced === false ? " (the plain share: too few games on the play or on the draw to balance the two). "
        : " (balanced for going first and second). ",
      `Likely between ${rangeWords(wr)}. ${matchupVerdict(r, ta, tb)}`),
    el("p", { class: "sub", text: rangeNote(r) }),
    rangeKey(),
    trustPart(r, data, [ta, tb])));
  reading.append(el("details", { class: "more mu-details" },
    el("summary", { text: "Details" }),
    el("div", { class: "panels" }, scorePanel(r, ta, tb, wr), playDrawPanel(r, ta), otherPanel(r)),
    el("div", { class: "panels mu-ai" }, data.sides.map((s, i) => el("section", { class: "panel" },
      el("h3", { text: `${[ta, tb][i]}: what Forge's AI can't play` }), aiLimitsParts(s.ai, s.title, { brief: muted }))))));
  add(reading, [castsPart(r, data.sides), howPart(r, data)]);
  return section;
}

/** The plain count. wr: the headline's win rate; when it's balanced for play and draw, a note says why
 * the first deck's share here can differ from it. */
function scorePanel(r, ta, tb, wr) {
  const wins = r.wins || [0, 0];
  const other = (r.draws || 0) + (r.timeouts || 0) + (r.errors || 0);
  const share = (n) => (r.games ? pct(n / r.games) : "?");
  const row = (label, n) => el("tr", {}, el("th", { scope: "row", text: label }),
    el("td", { class: "num", text: thousands(n) }), el("td", { class: "num", text: share(n) }));
  const kinds = [];
  if (r.draws) kinds.push(plural(r.draws, "draw"));
  if (r.timeouts) kinds.push(`${gamesWords(r.timeouts)} stopped at the time limit`);
  if (r.errors) kinds.push(`${gamesWords(r.errors)} Forge crashed in`);
  return el("section", { class: "panel mu-score-panel", "aria-labelledby": "h-score" },
    el("h3", { id: "h-score", text: "The score" }),
    el("table", { class: "data score-table" },
      el("colgroup", {}, el("col"), el("col", { class: "c-n" }), el("col", { class: "c-share" })),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Deck" }),
        el("th", { scope: "col", class: "num", text: "Wins" }), el("th", { scope: "col", class: "num", text: "Share" }))),
      el("tbody", {}, row(ta, wins[0]), row(tb, wins[1]), row("Draws and timeouts", other)),
      el("tfoot", {}, el("tr", {}, el("th", { scope: "row", text: "Games" }),
        el("td", { class: "num", text: thousands(r.games) }), el("td", {})))),
    el("p", { class: "sub", text: (kinds.length ? `${capitalise(kinds.join(", "))}. ` : "") +
      "A game that isn't won counts against both decks' win rates." }),
    wr && wr.balanced !== false ? el("p", { class: "sub", text: `Share is out of all the games. The ` +
      `headline's ${rateWords(wr)} is balanced for going first and second instead (see "Going first and ` +
      "second\"), so the two can differ a little." }) : null);
}

/** The "Starting player" tile: the starter's chance of winning (forge.views._starter), the average of both
 * decks' win rates going first, with its 95% range; when a deck never went first, the plain share of games
 * the starter won, saying so. */
function starterTile(starter) {
  if (!starter) return tile("Starting player", "?", "no games yet");
  const range = `95% range ${rangeWords(starter)}`;
  return tile("Starting player", pct(starter.value), starter.balanced === false
    ? `won this share of games, either deck: one deck never went first, so it isn't balanced (${range})`
    : `wins this share: the average of both decks going first (${range})`);
}

function playDrawPanel(r, ta) {
  const on = r.on_play || {}, off = r.on_draw || {};
  return el("section", { class: "panel", "aria-labelledby": "h-first" },
    el("h3", { id: "h-first", text: "Going first and second" }),
    el("p", { class: "sub", text: `${ta}'s win rates:` }),
    el("div", { class: "tiles" },
      tile("On the play", pct(on.value), `going first, in ${gamesWords(on.games)}`),
      tile("On the draw", pct(off.value), `going second, in ${gamesWords(off.games)}`),
      starterTile(r.starter)),
    el("p", { class: "sub", text: (r.engine || {}).kind === "decklab"
      ? "A coin flip decides who goes first in each game, so each deck goes first in about half of them. The " +
        "headline figure is still the average of the first two, and the starting player's the average of both " +
        "decks going first, so a lucky run of flips doesn't move them."
      : "In Forge the loser of each game goes first in the next one, so the two decks " +
        "don't go first equally often, and the weaker deck starts more games. That's why the headline figure is " +
        "the average of the first two, and the starting player's the average of both decks going first." }));
}

function otherPanel(r) {
  const rounds = r.rounds || {};
  const speed = r.speed || {};
  return el("section", { class: "panel", "aria-labelledby": "h-other" },
    el("h3", { id: "h-other", text: "The games" }),
    el("div", { class: "tiles" },
      tile("Game length", num(rounds.mean, 1), `turns each on average (${num(rounds.min)} to ${num(rounds.max)})`),
      tile("AI timeouts", thousands(r.ai_timeouts || 0), "decisions the AI ran out of time for"),
      tile("Speed", speed.games_per_min == null ? "?" : thousands(Math.round(speed.games_per_min)),
        speed.wall_s == null ? "games a minute" : `games a minute (${durationWords(speed.wall_s)} in all)`)),
    el("p", { class: "sub", text: "Forge gives its AI 5 seconds for each decision and skips it when time runs out; " +
      "a few of those in a big run make no real difference." }));
}

/** How each deck's cards played: the per-card numbers (cardStatsPart) when either side has counted games
 * with card data (r.cards, from the card log), else every nonland card each deck cast, how often and in
 * how many games. Card data with no counted games (every card log failed its checks, or an earlier version
 * of the card log kept them) adds why there are no
 * per-card numbers to the casts table, which counts every game; with no casts either, that's said on its
 * own. null when the result has none of these. */
function castsPart(r, sides) {
  if (r.cards && r.cards.some((side) => side && side.games)) return cardStatsPart(r, sides);
  const stats = (r.cards || []).find(Boolean);
  if (!r.casts || !r.casts.some((list) => list && list.length)) return stats ? cardStatsPart(r, sides) : null;
  return el("details", { class: "more mu-casts" },
    el("summary", { text: "What each deck cast" }),
    el("p", { class: "sub", text: `Out of ${thousands(r.games)} games. "Games" is the share of games the card ` +
      `was cast in at least once. A card never cast is flagged above once ${NEVER_CAST_GAMES} games have ` +
      "been counted." }),
    stats ? cardStatsCoverage(stats) : null,
    el("div", { class: "panels" }, sideTitles(sides).map((title, i) => {
      const list = [...(r.casts[i] || [])].sort((x, y) => y.games - x.games || x.name.localeCompare(y.name));
      return el("section", { class: "panel" }, el("h3", { text: title }),
        el("table", { class: "data casts-table" },
          el("colgroup", {}, el("col"), el("col", { class: "c-n" }), el("col", { class: "c-n" }), el("col", { class: "c-share" })),
          el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Card" }),
            el("th", { scope: "col", class: "num", text: "Copies" }), el("th", { scope: "col", class: "num", text: "Casts" }),
            el("th", { scope: "col", class: "num", text: "Games" }))),
          el("tbody", {}, list.map((c) => el("tr", { class: c.casts ? null : "is-missing" },
            el("th", { scope: "row" }, cardLink({ name: c.name }, `matchup-casts-${i}`)),
            el("td", { class: "num", text: String(c.qty) }),
            el("td", { class: "num missing-n", text: thousands(c.casts) }),
            el("td", { class: "num", text: r.games ? pctShort(c.games / r.games) : "?" }))))));
    })));
}

/** Play more (the run vocabulary and one primary button), swap sides, the two decks. */
function actionsPart(page, data) {
  const [a, b] = data.sides;
  const current = a.current !== false && b.current !== false;
  const ready = !data.forge || data.forge.ready !== false;
  // Swap sides opens the two lists by deck, so today's engine's result: not this one when it's an earlier
  // engine's (or played with an older list), whose page is by its key.
  const links = el("p", { class: "mu-links" },
    el("a", { href: data.key && !current ? `#/matchup?key=${encodeURIComponent(data.key)}` : matchupHref(b, a),
      text: "Swap sides", hidden: !current || earlierEngine(data.result) }),
    el("a", { href: deckHref(a.id, a.version), text: `Open ${a.title}` }),
    el("a", { href: deckHref(b.id, b.version), text: `Open ${b.title}` }));
  const panel = el("div", { class: "mu-more" });
  if (isLive(data)) {
    panel.append(el("p", { class: "sub", text: "More games can be asked for once this run is over." }));
  } else if (!current) {
    panel.append(el("p", { class: "sub", text: "More games can't be added to a result of an older list. Play " +
      "today's lists instead:" }),
    el("div", { class: "actions" }, el("a", { class: "btn btn-primary", href: matchupHref(a, b), text: "Today's lists" })));
  } else {
    // A result of an earlier engine isn't added to: more games of its lists start today's engine's result.
    // The run choice is a new matchup's (runModeChoice); an adaptive run carries on from the games saved (its
    // first check is the next one past them).
    const fresh = earlierEngine(data.result);
    const words = ({ mode, games: n }) => mode === "fixed"
      ? (fresh ? `Play ${thousands(n)} games with today's engine` : `Play ${thousands(n)} more games`)
      : (fresh ? "Play with today's engine" : "Play more");
    const error = el("p", { class: "form-error", role: "alert", "data-play-error": true });
    const choice = runModeChoice(data, () => { button.textContent = words(choice.value()); });
    const button = el("button", { type: "button", class: "btn btn-primary", disabled: !ready, "data-run": true,
      text: words(choice.value()), onclick: () => play(page, choice.value(), button, error) });
    // A viewer who may not start runs sees the disabled button and why (syncRunControls), not the choice too.
    choice.node.hidden = !runsAllowed();
    // An earlier engine's result says so under the button, until the viewer has dismissed the note about the
    // earlier engine (engineNote): then the button's "with today's engine" is enough.
    add(panel, [choice.node, el("div", { class: "actions" }, button),
      fresh && !engineNoteDismissed() ? el("p", { class: "sub", text: `This result was played with an earlier engine. ${NEW_ENGINE_WORDS}` }) : null,
      error]);
  }
  panel.append(links);
  return panel;
}

/** "How these games were played"'s line about the card log (runs[].card_log): kept in every run, some or
 * none. null when there are no runs. */
function cardLogWords(runs) {
  if (!runs.length) return null;
  const on = runs.filter((run) => run.card_log === true).length;
  if (on === runs.length) {
    return "Every run kept Deck Lab's card log, which follows every card through the games for the per-card " +
      "numbers. The games are the same as plain Forge's.";
  }
  if (on) {
    return `The card log, which follows every card through the games for the per-card numbers, was kept in ${on} ` +
      `of the ${plural(runs.length, "run")}: the table says why not in the others.`;
  }
  return "No run kept the card log, which follows every card through the games, so there are no per-card " +
    "numbers: the table says why.";
}

/** How a result's games were set up, by its engine's kind (r.engine; an older server's results have
 * none, and played batches): [sentences]. The card log's engine ("decklab") counts games, not batches
 * (r.seeds counts batches, and is only a v1 or plain Forge result's). */
function seedWords(r) {
  const kind = (r.engine || {}).kind;
  if (kind === "decklab") {
    return [`Each game has its own random seed and a coin flip for who starts, and the decks swap seats every ` +
      `${SEAT_BLOCK} games. The same two lists always replay the same games first, and more games carry on ` +
      "from there.", `${gamesWords(r.games)} so far.`];
  }
  const seeds = r.seeds;
  return [(kind === "plain" ? "Played with plain Forge, as the card log couldn't be used. " : "") +
    "The games are split into batches, one Forge process each; each batch has its own random seed, the " +
    "loser of each game starts the next, and deck 1 and deck 2 swap places every batch. The same two lists " +
    "always replay the same games first, and more games carry on with new seeds.",
  seeds ? `${plural(seeds, "batch", "batches")} so far.` : null];
}

/** "How these games were played": Forge's version, the engine and the runs, and how the games were set up. */
function howPart(r, data) {
  const runs = r.runs || [];
  const clock = (r.settings || {}).clock_s;
  const adaptive = r.adaptive_last ? adaptiveWords(r.adaptive_last, r.lead, sideTitles(data.sides)) : null;
  const details = r.adaptive_last ? adaptiveDetails(r.adaptive_last) : null;
  const facts = [
    adaptive ? [adaptive, details ? el("small", { class: "sub mu-z", text: ` (${details})` }) : null] : null,
    `Forge ${r.forge_version || "?"}, ${data.format === "Commander" ? "Commander" : "Constructed"} rules, one game at a time between the two decks.`,
    ...seedWords(r),
    clock ? `A game still going after ${durationWords(clock)} is stopped and counted as a timeout.` : null,
    r.failed_batches ? `${plural(r.failed_batches, "batch", "batches")} failed; their games aren't counted.` : null,
    earlierEngine(r) && r.engine.words ? r.engine.words : null,
    cardLogWords(runs),
  ].filter(Boolean);
  // Each run's card log is marked only when some run went without it (runs from before Milestone 8 have no
  // card_log at all).
  const mixed = runs.some((run) => run.card_log !== true);
  const reasons = r.loss_reasons || [];
  return el("details", { class: "more mu-how" },
    el("summary", { text: "How these games were played" }),
    el("ul", { class: "sources-list" }, facts.map((f) => Array.isArray(f) ? el("li", {}, f) : el("li", { text: f }))),
    runs.length ? el("div", { class: "table-wrap" }, el("table", { class: "data runs-table" },
      el("caption", { class: "sr-only", text: "Each run: when, who, games asked for and played" }),
      el("thead", {}, el("tr", {}, ["When", "Who", "Asked", "Played"].map((t, i) =>
        el("th", { scope: "col", class: i > 1 ? "num" : null, text: t })))),
      el("tbody", {}, runs.map((run) => [el("tr", {},
        el("td", {}, momentWords(run.when), run.stopped ? [" ", status("plain", "Stopped")] : null,
          run.checkpoint ? el("small", { class: "sub", text: "Checkpoint: completed chunks saved; run unfinished." }) : null,
          run.recovered ? el("small", { class: "sub", text: run.recovery_note || "Recovered completed games from an interrupted run." }) : null,
          run.error ? el("small", { class: "sub run-error", text: run.error }) : null),
        el("td", { text: run.by || "?" }),
        el("td", { class: "num", text: thousands(run.asked || 0) }),
        el("td", { class: "num", text: thousands(run.played || 0) })),
      // Whether the run kept the card log, across the table's width (a reason can be a long sentence, and is
      // a whole one, so it follows "Card log off." rather than a colon).
      mixed ? el("tr", { class: "label-row" }, el("td", { colspan: 4, class: "run-cardlog" },
        run.card_log === true ? "Card log on."
          : run.card_log === false ? ["Card log off.", run.card_log_problem ? ` ${run.card_log_problem}` : null]
            : "No card log: played before Deck Lab kept one.")) : null])))) : null,
    reasons.length ? [el("h4", { text: "How the games ended" }),
      el("ul", { class: "sources-list" }, reasons.map((x) => el("li", { text: `${capitalise(x.reason)}: ${gamesWords(x.games)}` })))] : null,
    r.updated ? el("p", { class: "sub", text: `Saved ${momentWords(r.updated)}.` }) : null);
}
