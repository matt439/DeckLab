"use strict";

/* P1's deck Overview panels. Field and swap-test summaries use the same result components as Matchups,
   with their own ids and one read per panel; the Played at home part comes with /api/deck itself. Nothing here starts a simulation or polls in the background.
   Late reads belong to the original screen, route and person, and never redraw a replacement page. */

function deckOverviewHere(section, context) {
  return section.isConnected && context.screen === deckScreen && context.token === routeToken
    && context.profile === state.profile?.id;
}

function deckOverviewContext() {
  return { screen: deckScreen, token: routeToken, profile: state.profile?.id };
}

/** A read-only field summary; the Matchups tab keeps the full table and the explicit run controls. */
function deckOverviewForge(data) {
  if (data.summary.id.startsWith(BOX_PREFIX)) return null;
  const body = el("div", { class: "deck-overview-forge-body" }, loadingBox("Loading the Forge field…", { small: true }));
  const section = el("section", { class: "deck-section deck-overview-forge", "aria-labelledby": "h-overview-forge" },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-forge", text: "Forge field" }),
      el("button", { type: "button", class: "btn", text: "Field view",
        onclick: () => openDeckTab("matchups", { to: "sec-field" }) })), body);
  const context = deckOverviewContext();
  const profile = context.profile ? `&profile=${encodeURIComponent(context.profile)}` : "";
  const load = async () => {
    try {
      // pilot=1: the same answer says whether Forge pilots this list poorly (no second read, no games).
      const answer = await api(`/api/field?id=${encodeURIComponent(data.summary.id)}&version=${data.version}` +
        `${profile}&pilot=1`);
      if (!deckOverviewHere(section, context)) return;
      clear(body);
      const opponents = answer.opponents || [];
      if (!opponents.length) {
        body.append(el("p", { class: "empty", text: "No other decks in this field yet." }));
        return;
      }
      add(body, [fvHeadline(answer, { panel: false }), deckOverviewPilot(answer.pilot), fvChips(answer),
        answer.rating?.h_points != null ? el("p", { class: "sub", text:
          `Going first is worth about ${Math.round(answer.rating.h_points)} points of win rate in these games.` }) : null,
        fvPlaying(answer) ? el("p", { class: "sub", text: "A field run is in progress. Open Field view for its latest progress." }) : null,
        el("p", { class: "sub", text: "Forge's AI, best of one. The field view has each matchup and the limits of these estimates." })]);
    } catch (error) {
      if (!deckOverviewHere(section, context)) return;
      clear(body).append(loadFailed("The Forge field", error, () => {
        if (!deckOverviewHere(section, context)) return;
        clear(body).append(loadingBox("Loading the Forge field…", { small: true }));
        load();
      }));
    }
  };
  load();
  return section;
}

/** Matchups' poor-AI caveat (matchups-results.js pilotReason) for the list the field line is about; null
   for a list Forge pilots normally, or when how it pilots it isn't known (no claim either way). */
function deckOverviewPilot(pilot) {
  const reason = pilotReason(pilot);
  return reason ? el("p", { class: "sub deck-overview-pilot" },
    status("warn", "Forge pilots this deck poorly"), " ", reason) : null;
}

/** The newest test the server returns, preserving running and inconclusive states through vtTestItem. */
function deckOverviewSwap(data) {
  if (data.summary.read_only) return null;
  const body = el("div", {}, loadingBox("Loading the latest test…", { small: true }));
  const section = el("section", { class: "deck-section deck-overview-swap", "aria-labelledby": "h-overview-swap" },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-swap", text: "Latest swap test" }),
      el("button", { type: "button", class: "btn btn-quiet deck-more-link", text: "All tests",
        onclick: () => openDeckTab("matchups", { to: "sec-tests" }) })), body);
  const context = deckOverviewContext();
  const load = () => api(`/api/variants?id=${encodeURIComponent(data.summary.id)}&version=${data.version}`).then((answer) => {
    if (!deckOverviewHere(section, context)) return;
    clear(body);
    const latest = (answer.tests || [])[0];
    // None yet: the editor is where a change is tested (Test this change), for whoever may edit the deck.
    body.append(latest ? el("ul", { class: "vt-test-list" }, vtTestItem(latest))
      : emptyBox("No swap tests yet.", canEditDeck(data.summary)
        ? el("a", { class: "btn", href: editHref(data.summary.id, data.version), text: "Try a change in the editor" }) : null));
  }).catch((error) => {
    if (!deckOverviewHere(section, context)) return;
    if (error.status === 501) section.remove();
    else clear(body).append(loadFailed("The latest test", error, () => {
      if (!deckOverviewHere(section, context)) return;
      clear(body).append(loadingBox("Loading the latest test…", { small: true }));
      load();
    }));
  });
  load();
  return section;
}

/** A curve for the displayed list, independent of inventory, with a worded equivalent for its bars. */
function deckOverviewCurve(data) {
  const buckets = data.stats?.curve?.buckets;
  if (!buckets?.some((bucket) => bucket.total)) return null;
  const top = Math.max(1, ...buckets.map((bucket) => bucket.total));
  const words = buckets.filter((bucket) => bucket.total).map((bucket) => `${bucket.mv}: ${bucket.total}`).join(", ");
  const colours = deckColourPieces(deckPageColours(data));
  // Turn the identity's stripe stops into a vertical gradient for the curve; the helper owns every colour.
  const style = colours ? colours.vars().replace("linear-gradient(90deg", "linear-gradient(180deg") : "";
  return el("section", { class: "deck-section deck-overview-curve", "aria-labelledby": "h-overview-curve", style },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-curve", text: "Mana curve" }),
      el("button", { type: "button", class: "btn btn-quiet deck-more-link", text: "All the stats",
        onclick: () => openDeckTab("stats", { to: "deck-panel-stats" }) })),
    el("div", { class: "deck-overview-bars", role: "img", "aria-label": `Mana curve, cards at each mana value: ${words}` },
      buckets.map((bucket) => el("div", { class: "deck-overview-column", "aria-hidden": "true" },
        el("span", { class: "deck-overview-count", text: bucket.total ? String(bucket.total) : "" }),
        el("span", { class: "deck-overview-bar", style: `--curve-height: ${(100 * bucket.total / top).toFixed(1)}%` }),
        el("span", { class: "deck-overview-mv", text: String(bucket.mv) })))));
}

/** When the deck was last played at home (E1-S27), from the Game log's games this viewer may see (/api/deck's
 * played): "Last played 2026-10-20 · 3 games" or "Not played at home yet", then what its list changed since that
 * game (played.since, from the deck's own revisions). Nothing when the games couldn't be read (never "not
 * played"), and no change line when the list it was played with can't be found. */
function deckOverviewPlayed(data) {
  const p = data.played;
  if (!p) return null;
  const parts = [el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-played", text: "Played at home" }))];
  if (!p.games || !p.last) {
    parts.push(el("p", { class: "deck-played", text: "Not played at home yet" }));
  } else {
    parts.push(el("p", {}, factLine("deck-played", [`Last played ${p.last}`, plural(p.games, "game")])));
    parts.push(deckPlayedSince(p.since, data.summary));
  }
  return el("section", { class: "deck-section deck-overview-played", "aria-labelledby": "h-overview-played" }, parts);
}

/** played.since in words: its list unchanged, or each card it gained or lost (a sideboard's named), the History
 * holding the rest. */
function deckPlayedSince(since, summary) {
  if (!since) return null;
  const list = since.version === "owned" ? "Play-now list" : "list";
  if (!since.changes.length && !since.more) {
    return el("p", { class: "sub", text: `Its ${list} hasn't changed since that game.` });
  }
  const where = (c) => c.section === "Deck" ? "" : ` (${c.section === "Sideboard" ? "sideboard" : c.section})`;
  const words = (c) => c.delta > 0 ? `Added ${c.delta} ${c.name}${where(c)}`
    : c.delta < 0 ? `Took out ${-c.delta} ${c.name}${where(c)}` : `Changed the printing of ${c.name}${where(c)}`;
  const history = summary.read_only ? null
    : el("a", { href: `#/history?id=${encodeURIComponent(summary.id)}&v=${since.version}`, text: "History" });
  return el("div", { class: "deck-played-since" },
    el("p", { class: "sub", text: `Its ${list} has changed since that game:` }),
    el("ul", {}, since.changes.map((c) => el("li", { text: words(c) + (c.delta && c.printing ? ", another printing" : "") }))),
    since.more ? el("p", { class: "sub" }, `And ${plural(since.more, "more change")}`,
      history ? ["; its ", history, " has them all"] : null, ".") : null);
}
