/* Deck Lab's page: the deck page's tools and its Matchups tab.

The More menu's exports (copy, download and print the list shown; no deck or inventory writes), the
library's readiness filter, the play guide's card names (as viewer links, with symbols in the prose), and
the deck page's Matchups tab (deckMatchupsPart): the matchup screens' results
for this list, one row per opponent, best first, with the rest folded and "Not played yet against: …"
(matchups-overview.js deckResultParts), the runs going now, Play a matchup, what Forge's AI can't play and how
the cards played. "Against the field" (field.js) leaves an opponent met head to head out of its own
"Not played yet against" (headToHead).
*/
"use strict";

function matchesReadiness(deck, filter) {
  if (!filter) return true;
  // Its collection isn't the visitor's to see: no readiness filter matches it, "unknown" included, since
  // "unknown" is for counts that couldn't be worked out, not counts that are hidden.
  if (!("missing" in deck)) return false;
  const missing = deck.missing && deck.missing.target;
  const waiting = deck.on_the_way && deck.on_the_way.target;
  const known = !deck.error && missing != null && waiting != null && deck.availability_confirmed?.target !== false;
  return filter === "unknown" ? !known : known && (filter === "ready" ? missing === 0 && waiting === 0
    : filter === "waiting" ? missing === 0 && waiting > 0 : missing > 0);
}

function exportedDeck(data) {
  return Object.entries(data.sections).filter(([, lines]) => lines.length).map(([section, lines]) =>
    [section, ...lines.map(l => `${l.qty} ${l.name}${l.set && l.number ? ` (${l.set.toUpperCase()}) ${l.number}` : ""}`)].join("\n")).join("\n\n") + "\n";
}

function downloadDeck(data) {
  const url = URL.createObjectURL(new Blob([exportedDeck(data)], {type: "text/plain;charset=utf-8"}));
  const link = el("a", {href: url, download: `${data.summary.id.replaceAll("/", "-")}-${data.version}.txt`});
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Copy the list shown to the clipboard; where that isn't allowed, a sheet with the list selected to copy. */
async function copyDeck(data) {
  const text = exportedDeck(data);
  try {
    await navigator.clipboard.writeText(text);
    toast("Decklist copied.");
  } catch (_) {
    const area = el("textarea", {"aria-label": "Decklist to copy", readonly: true, rows: 14, class: "export-copy"});
    area.value = text;
    const sheet = openSheet({title: "Copy the decklist", body: [el("p", {class: "sub", text: "Select it and copy, or use Download decklist."}), area]});
    sheetActions(sheet, [{text: "Done", kind: "primary", onclick: () => sheet.close()}]);
    area.focus(); area.select();
  }
}

function printDeck(data) {
  document.querySelector(".print-sheet")?.remove();
  const version = listName(data.version);
  const sheet = el("article", {class: "print-sheet"}, el("h1", {text: data.summary.title}),
    el("p", {text: version}), el("pre", {text: exportedDeck(data)}));
  const standins = deckStandinsOf(data);
  if ((standins?.rows || []).length || (standins?.warnings || []).length) {
    sheet.append(el("h2", {text: "Stand-ins"}));
    if (standins.rows?.length) sheet.append(el("ul", {}, standins.rows.map(row =>
      el("li", {text: `${row.qty} x ${deckStandinWords(row)}`}))));
    for (const text of standins.warnings || []) sheet.append(el("p", {class: "print-warning", text}));
  }
  const guide = data.guide;
  if (guide?.changed_on) sheet.append(el("p", {class: "print-warning", text:
    `Guide needs review: the list changed on ${guide.changed_on}. Check its advice against this list.`}));
  sheet.append(el("p", {text: "Guide notes may discuss both lists; follow their labels."}));
  for (const part of guide?.sections || []) sheet.append(el("h2", {text: part.title}), guideMarkdown(part.markdown));
  document.body.append(sheet);
  window.addEventListener("afterprint", () => sheet.remove(), {once: true});
  window.print();
}

/** A pattern that finds the deck's card names (state.cards) in text, longest first, as whole words; null
 * when there are no cards. The guide's links and deck.js's key cards use it. */
function cardNamePattern() {
  if (typeof state === "undefined" || !state.cards || !state.cards.size) return null;
  return cardNamesPattern(state.cards.keys());
}

/** cardNamePattern's pattern for any card names (the library's detail pane, which has no state.cards). */
function cardNamesPattern(cardNames) {
  const names = [...new Set(cardNames)].sort((a, b) => b.length - a.length);
  if (!names.length) return null;
  const escape = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`(?<![\\p{L}\\p{N}])(?:${names.map(escape).join("|")})(?![\\p{L}\\p{N}])`, "gu");
}

/** Text of the play guide with the deck's card names as links that open the viewer (the "guide" group, so a
 * swipe goes through the cards the guide names, each once), drawn as text links, and mana symbols ({T}, {G})
 * drawn. */
function guideCardText(text) {
  const symbols = (part) => (typeof renderSymbols === "function" ? renderSymbols(part, {small: true}) : [part]);
  const pattern = cardNamePattern();
  if (!pattern) return symbols(text);
  const parts = []; let from = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(...symbols(text.slice(from, match.index)), cardLink({name: match[0]}, "guide", {inline: true}));
    from = match.index + match[0].length;
  }
  parts.push(...symbols(text.slice(from))); return parts.filter((p) => p !== "");
}


// ------------------------------------------------------- the Matchups tab

/** The deck page's Matchups tab: Forge's results for this list, one row per opponent (the pair's best result,
 * best matchup first; the rest folded), the decks it hasn't met yet in one line, the runs going now, Play a
 * matchup, then what Forge's AI can't play in it and how its cards played. The deck page asks for its matchups
 * (/api/deck's slowest part) only now, unless the address opened on this tab. A Beginner Box half links to
 * its pairings instead. */
function deckMatchupsPart(data) {
  const s = data.summary;
  const section = el("section", {class: "deck-section deck-mu", id: "sec-matchups", "aria-labelledby": "h-matchups"},
    el("h2", {id: "h-matchups", class: "sr-only", text: "Matchups"}));
  if (s.id.startsWith(BOX_PREFIX)) {
    const counts = api("/api/matchups").then(resultCounts);
    section.append(note("A Beginner Box half is never played on its own, so Forge plays its pairings instead."),
      pairingLinks(s.id, "Matchups for its pairings:", counts));
    return section;
  }
  const content = el("div", {class: "mu-deck-content"});
  const url = `/api/deck?id=${encodeURIComponent(s.id)}&version=${data.version}`;
  const token = routeToken;
  const updates = matchupRefreshStatus();
  section.append(content);
  let m = data.matchups;
  const place = (change) => typeof keepPlace === "function" ? keepPlace(change) : change();
  const draw = () => place(() => drawDeckMatchups(content, data, m, load));
  let watching = false;
  const watch = () => {
    if (watching) return;
    watching = true;
    section.append(updates.node);
    watchMatchupUpdates({token, host: () => section, url, view: updates,
      active: () => (m?.running || []).length > 0,
      onFresh(fresh) {
        if (JSON.stringify(fresh.matchups) === JSON.stringify(m)) return;
        m = data.matchups = fresh.matchups;
        replaceMatchupContent(content, draw);
      }});
  };
  // Fetch the list's matchups (again, for Try again) and draw them.
  function load() {
    if (token !== routeToken) return;
    clear(content).append(loadingBox("Loading this list's matchups…"));
    api(url).then((fresh) => {
      if (token !== routeToken) return;
      m = data.matchups = fresh.matchups;
      draw();
      watch();
    }).catch((e) => {
      if (token !== routeToken) return;
      place(() => clear(content).append(loadFailed("This list's matchups", e, load)));
    });
  }
  if ("matchups" in data) {
    draw();
    watch();
  } else {
    load();
  }
  return section;
}


/** Draw the Matchups tab's content from m (/api/deck's "matchups"; null when the server couldn't load them,
 * then retry, when given, fetches them again),
 * with the matchup screens' pieces (matchups-overview.js deckResultParts, earlierEngineLine, earlierFlags;
 * matchups.js aiLimitsParts; matchups-cards.js deckCardStats; matchups-results.js pilotFlag). */
function drawDeckMatchups(host, data, m, retry = null) {
  const s = data.summary;
  clear(host);
  if (!m) {
    host.append(loadFailed("Forge's results", null, retry));
    return;
  }
  const version = data.versions.length > 1 ? listName(data.version, true) : "list";
  const running = m.running || [];
  // "Not played yet against" needs the library's decks: get it once, then draw again with them.
  if (!state.library) {
    const token = routeToken;
    api("/api/decks").then((library) => {
      if (token !== routeToken) return;           // the page was left: nothing to draw
      state.library = state.library || library;
      if (host.isConnected) {
        const redraw = () => drawDeckMatchups(host, data, m, retry);
        if (typeof keepPlace === "function") keepPlace(redraw); else redraw();
      }
    }).catch(() => {});
  }
  // The tab's one primary action, for a viewer who may start runs (the field's Play is an outlined button).
  const play = runsAllowed() ? el("div", {class: "actions mu-deck-actions"}, el("a", {class: "btn btn-primary",
    href: `#/matchups?a=${encodeURIComponent(s.id)}&av=${data.version}`, text: "Play a matchup"})) : null;
  const flag = pilotFlag(m.ai, s.title, {deckPage: true});
  const otherLine = earlierEngineLine(m);
  const earlier = earlierFlags(m);
  add(host, [
    forgeBox(m.forge),
    flag,
    running.length ? el("section", {class: "deck-mu-part", "aria-labelledby": "h-mu-running"},
      el("h2", {id: "h-mu-running", text: "Playing now"}),
      el("ul", {class: "mu-list"}, running.map((r) => runningRow(r, {against: true})))) : null,
    el("section", {class: "deck-mu-part", "aria-labelledby": "h-mu-results"},
      el("h2", {id: "h-mu-results", text: "Head to head"}),
      deckResultParts(m, s, version, state.library || null, data.version),
      play),
    otherLine,
    // Folded, unless the earlier games found something to warn about.
    m.ai ? el("details", {class: "more deck-mu-ai", open: earlier ? true : null},
      el("summary", {text: "What Forge's AI can't play"}),
      aiLimitsParts(m.ai, s.title, {deckPage: true, otherSaid: !!otherLine, earlier})) : null,
    deckCardStats(m, version, {otherSaid: !!otherLine})]);
}

/** This deck's latest head-to-head result against an opponent (any list), from the deck on screen's
 * matchups, or null. The field part leaves such an opponent out of its "Not played yet against". */
function headToHead(id) {
  const m = typeof deckScreen !== "undefined" && deckScreen && deckScreen.data.matchups;
  if (!m || !m.results) return null;
  const want = sameDeckId(id || "");
  return m.results.find((item) => sameDeckId((item.sides[1] || {}).id || "") === want) || null;
}
