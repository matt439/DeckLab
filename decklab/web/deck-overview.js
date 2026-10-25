"use strict";

/* P1's deck Overview panels. Field and swap-test summaries use the same result components as Matchups,
   with their own ids and one read per panel. Nothing here starts a simulation or polls in the background.
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
  const body = el("div", { class: "deck-overview-forge-body" }, loadingBox("Loading the Forge field..."));
  const section = el("section", { class: "deck-section deck-overview-forge", "aria-labelledby": "h-overview-forge" },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-forge", text: "Forge field" }),
      el("button", { type: "button", class: "btn", text: "Field view",
        onclick: () => openDeckTab("matchups", { to: "sec-field" }) })), body);
  const context = deckOverviewContext();
  const profile = context.profile ? `&profile=${encodeURIComponent(context.profile)}` : "";
  const load = async () => {
    try {
      const answer = await api(`/api/field?id=${encodeURIComponent(data.summary.id)}&version=${data.version}${profile}`);
      if (!deckOverviewHere(section, context)) return;
      clear(body);
      const opponents = answer.opponents || [];
      if (!opponents.length) {
        body.append(el("p", { class: "empty", text: "No other decks in this field yet." }));
        return;
      }
      add(body, [fvHeadline(answer, { panel: false }), fvChips(answer),
        answer.rating?.h_points != null ? el("p", { class: "sub", text:
          `Going first is worth about ${Math.round(answer.rating.h_points)} points of win rate in these games.` }) : null,
        fvPlaying(answer) ? el("p", { class: "sub", text: "A field run is in progress. Open Field view for its latest progress." }) : null,
        el("p", { class: "sub", text: "Forge's AI, best of one. The field view has each matchup and the limits of these estimates." })]);
    } catch (error) {
      if (!deckOverviewHere(section, context)) return;
      clear(body).append(el("p", { class: "sub", text: "The Forge field couldn't be loaded." }),
        el("button", { type: "button", class: "btn", text: "Try again", onclick: () => {
          if (!deckOverviewHere(section, context)) return;
          clear(body).append(loadingBox("Loading the Forge field..."));
          load();
        } }));
    }
  };
  load();
  return section;
}

/** The newest test the server returns, preserving running and inconclusive states through vtTestItem. */
function deckOverviewSwap(data) {
  if (data.summary.read_only) return null;
  const body = el("div", {}, loadingBox("Loading the latest test..."));
  const section = el("section", { class: "deck-section deck-overview-swap", "aria-labelledby": "h-overview-swap" },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-swap", text: "Latest swap test" }),
      el("button", { type: "button", class: "btn btn-quiet deck-more-link", text: "All tests",
        onclick: () => openDeckTab("matchups", { to: "sec-tests" }) })), body);
  const context = deckOverviewContext();
  api(`/api/variants?id=${encodeURIComponent(data.summary.id)}&version=${data.version}`).then((answer) => {
    if (!deckOverviewHere(section, context)) return;
    clear(body);
    const latest = (answer.tests || [])[0];
    body.append(latest ? el("ul", { class: "vt-test-list" }, vtTestItem(latest))
      : el("p", { class: "sub", text: "No tests yet. In the editor, change some cards and choose Test this change." }));
  }).catch((error) => {
    if (!deckOverviewHere(section, context)) return;
    if (error.status === 501) section.remove();
    else clear(body).append(el("p", { class: "sub", text: "The latest test couldn't be loaded. Open All tests to try again." }));
  });
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
