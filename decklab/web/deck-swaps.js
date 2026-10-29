/* The deck page's side of stand-ins for missing cards (E2-S07): owned cards that could play a missing
 * card's slot, and the swaps the Play-now list already makes, with their Substitutes notes.
 *
 * deckSwapFinder: on the Cards tab under the Missing filter (either list), for a visitor who may see the
 * deck's space's collection (GET /api/deck/swaps, asked for once per list on screen). One row per missing
 * card, in the order worth buying (no stand-in first); "See them" lists the stand-ins, and a visitor who
 * may change the deck gets "Swap into the Play-now list", which opens the editor there with that card's
 * stand-ins (editor-swaps.js, #/edit?…&v=owned&swap=<name>).
 *
 * deckSwapsSection: on the Play-now list's Overview and Cards tab, each swap the list makes (/api/deck's
 * "swaps", worked out from the two lists and the Substitutes write-up, which every viewer of the deck
 * sees), with its note or "No note yet", and "Edit notes" (the editor's Notes tab) for whoever may change
 * the deck. Not the Packing plan's physical stand-ins (deck-standins.js), which never change a list.
 *
 * neverCastReplacements (the Matchups tab) and shortColourLands (the Stats tab's colour sources, E3-S25): free
 * pool cards for a card never cast, and free dual lands for a colour short of sources, each with Test this swap.
 */
"use strict";

const SWAP_FINDER_ROWS = 5;      // missing cards the box shows before "Show all" (a phone's screen)

/** True when the deck on screen is an ordinary deck whose collection the visitor may see. */
function deckSwapsOffered(data) {
  const s = data.summary;
  return !/^(product|pairing)\//.test(s.id) && Boolean(data.owned) && seesInventory(s.space || deckSpaceOf(s.id));
}

/** The Missing filter's "Owned stand-ins" box, or null. */
function deckSwapFinder(screen) {
  const data = screen.data;
  if (screen.view.filter !== "missing" || !deckSwapsOffered(data)) return null;
  const box = el("section", { class: "box deck-swap-finder", "aria-labelledby": "h-swap-finder" },
    el("h3", { id: "h-swap-finder", text: "Owned stand-ins" }));
  const body = el("div", {}, loadingBox("Looking for stand-ins…", { small: true }));
  box.append(body);
  if (!screen.swapFinder || screen.swapFinder.version !== data.version) {
    screen.swapFinder = { version: data.version,
      answer: api(`/api/deck/swaps?id=${encodeURIComponent(data.summary.id)}&version=${data.version}`) };
  }
  const asked = screen.swapFinder;
  asked.answer.then((answer) => {
    if (deckScreen !== screen || !body.isConnected) return;
    drawSwapFinder(body, data, answer);
  }, (e) => {
    // A failure isn't kept: Try again (or the next redraw) asks again.
    if (screen.swapFinder === asked) screen.swapFinder = null;
    if (deckScreen === screen && body.isConnected) clear(body).append(loadFailed("Stand-ins", e, () => {
      if (deckScreen === screen) redrawCards(screen);
    }));
  });
  return box;
}

function drawSwapFinder(body, data, answer) {
  if (!answer || !Array.isArray(answer.cards)) {        // not an answer this page can read: say nothing
    const box = body.closest(".deck-swap-finder");
    if (box) box.remove();
    return;
  }
  if (!answer.cards.length) {
    clear(body).append(el("p", { class: "sub", text: "Nothing missing can be swapped (commanders and basic lands never are)." }));
    return;
  }
  const row = (entry) => {
    const n = entry.candidates.length + entry.more;
    return el("li", { class: "swap-finder-row" },
      el("span", { class: "swap-finder-name" }, entry.name,
        el("small", { text: n ? `${entry.missing} missing · ${n} could stand in`
          : `${entry.missing} missing · no close stand-in: worth buying first` })),
      n ? el("button", { type: "button", class: "btn", text: "See them",
        "aria-label": `See the stand-ins for ${entry.name}`, onclick: () => openDeckSwapSheet(data, entry, answer) }) : null);
  };
  // The first few, with the rest behind "Show all", so a long list doesn't push the missing cards off a phone's screen.
  const list = el("ul", { class: "swap-finder-list" }, answer.cards.slice(0, SWAP_FINDER_ROWS).map(row));
  const rest = answer.cards.slice(SWAP_FINDER_ROWS);
  const more = rest.length ? el("button", { type: "button", class: "btn btn-quiet", text: `Show all ${answer.cards.length}`,
    onclick: () => { list.append(...rest.map(row)); more.remove(); } }) : null;
  add(clear(body), [
    el("p", { class: "sub", text: "Cards you have that could play these slots tonight, the most worth buying first." }),
    list, more]);
}

/** The stand-ins for one missing card, read-only, with the way into the editor for whoever may edit. */
function openDeckSwapSheet(data, entry, answer) {
  const s = data.summary;
  const editable = canEditDeck(s);
  // Only when the Play-now list is short of it too: else the editor would have nothing to swap.
  const out = !(entry.list_missing > 0);
  const sheet = openSheet({ title: `Stand-ins for ${entry.name}`, side: true });
  sheet.dialog.classList.add("swap-sheet");
  add(sheet.body, [
    el("p", { class: "sub swap-head", text: `${plural(entry.missing, "copy", "copies")} missing · ${swapLooksFor(entry)}` }),
    out ? el("p", { class: "note", text: `The ${listName("owned", true)} isn't short of it: it plays the copies you have, or something else instead.` }) : null,
    el("ul", { class: "swap-list" }, entry.candidates.map((c) => el("li", { class: "swap-row" },
      cardRow(c.card, { name: c.name, meta: swapCandidateMeta(c), viewerGroup: "deck-swaps",
        chips: !c.basic && !c.here ? [status("info", "On the way")] : [], caption: `${c.name} for ${entry.name}` }),
      el("p", { class: "sub swap-note", text: c.note.text })))),
    entry.more ? el("p", { class: "sub", text: `${plural(entry.more, "more card fits", "more cards fit")}; these are the closest.` }) : null]);
  if (editable && !out) {
    sheet.foot.append(el("a", { class: "btn", href: `${editHref(s.id, "owned")}&swap=${encodeURIComponent(entry.name)}`,
      text: `Swap into the ${listName("owned", true)}` }));
  }
}

/** "Swaps from the Planned list": the Play-now list's swaps and their notes, or null. */
function deckSwapsSection(data) {
  const found = data.swaps;
  if (data.version !== "owned" || !found || (!found.swaps.length && !found.unpaired.length)) return null;
  const s = data.summary;
  const rows = new Map(((data.owned && data.owned.rows) || []).map((r) => [r.name, r]));
  const coming = (name) => (rows.get(name) && rows.get(name).on_the_way > 0 ? [status("info", "On the way")] : []);
  const words = (swap) => (swap.using.length
    ? `${swap.using.map((u) => `${u.qty} ${u.name}`).join(" + ")} for ${swap.out_qty} ${swap.for}`
    : `${swap.out_qty} ${swap.for} out`);
  return el("section", { class: "deck-section deck-swaps", "aria-labelledby": "h-swaps" },
    el("h2", { id: "h-swaps", text: `Swaps from the ${listName("target", true)}` }),
    el("div", {}, found.swaps.map((swap) => {
      const card = (swap.using[0] && swap.using[0].card) || swap.card;
      return cardRow(card, { name: words(swap), meta: swap.note || "No note yet in Substitutes",
        chips: swap.using.flatMap((u) => coming(u.name)), viewerGroup: "deck-swaps", caption: words(swap) });
    })),
    found.unpaired.length ? el("p", { class: "sub",
      text: `Also in the ${listName("owned", true)}: ${found.unpaired.map((u) => `${u.qty} ${u.name}`).join(", ")}.` }) : null,
    canEditDeck(s) ? el("a", { class: "btn btn-quiet", href: `${editHref(s.id, "owned")}&tab=notes`, text: "Edit notes" }) : null);
}


// ------------------------------------------------- free replacements for cards never cast (E3-S25)

const replacementAsks = new WeakMap();   // a deck page's answer -> Map("viewer|version|card" -> the asked promise)

/** The Matchups tab's "Free replacements" under a spell its saved games drew and never cast (matchups-cards.js
 * standOutParts), or null: only an ordinary deck whose collection the visitor may see (as the stand-ins),
 * never a land. It asks GET /api/deck/replacements once per card and list on screen; a refusal (403, 404,
 * 400) shows nothing, any other failure says so with Try again. */
function neverCastReplacements(data, row) {
  if (!data || !data.summary || !row || row.land === true || !deckSwapsOffered(data)
      || !/^(?:[^/]+\/)?(?:casual|commander)\//.test(data.summary.id)) return null;
  const box = el("div", { class: "mu-replace" }, loadingBox("Looking for free replacements…", { small: true }));
  const viewer = state.profile && state.profile.id;
  const version = data.version === "owned" ? "owned" : "target";
  const key = `${viewer || ""}|${version}|${row.name}`;
  if (!replacementAsks.has(data)) replacementAsks.set(data, new Map());
  const asks = replacementAsks.get(data);
  if (!asks.has(key)) {
    asks.set(key, api(`/api/deck/replacements?id=${encodeURIComponent(data.summary.id)}&version=${version}` +
      `&card=${encodeURIComponent(row.name)}`));
  }
  const asked = asks.get(key);
  asked.then((answer) => {
    if ((state.profile && state.profile.id) !== viewer) { box.remove(); return; }
    drawReplacements(box, data, answer);
  }, (e) => {
    if (asks.get(key) === asked) asks.delete(key);      // a failure isn't kept: Try again asks again
    if ((state.profile && state.profile.id) !== viewer || [400, 403, 404].includes(e && e.status)) {
      box.remove();
      return;
    }
    clear(box).append(loadFailed("Free replacements", e, () => {
      const again = neverCastReplacements(data, row);
      if (again) box.replaceWith(again); else box.remove();
    }));
  });
  return box;
}

function drawReplacements(box, data, answer) {
  if (!answer || !Array.isArray(answer.candidates) || !answer.card) { box.remove(); return; }
  const card = answer.card;
  if (!answer.candidates.length) {
    clear(box).append(el("p", { class: "sub", text: `No free card in the pool fits its slot (${swapLooksFor(card)}).` }));
    return;
  }
  add(clear(box), [
    el("p", { class: "sub mu-replace-head" }, el("b", { text: "Free replacements: " }),
      `cards no other built deck holds that could play its slot (${swapLooksFor(card)}).`),
    el("ul", { class: "swap-list" }, answer.candidates.map((c) => el("li", { class: "swap-row" },
      cardRow(c.card, { name: c.name, meta: swapCandidateMeta(c), viewerGroup: "deck-replacements",
        chips: !c.here ? [status("info", "On the way")] : [], caption: `${c.name} for ${card.name}` }),
      el("p", { class: "sub swap-note", text: c.note && c.note.text }),
      el("button", { type: "button", class: "btn swap-use", text: "Test this swap",
        "aria-label": `Test ${c.name} for ${card.name}`, onclick: (e) => testReplacementSwap(data, card, c, e.currentTarget) })))),
    answer.more ? el("p", { class: "sub", text: `${plural(answer.more, "more card fits", "more cards fit")}; these are the closest.` }) : null]);
}

/** "Test this swap": the editor opens with the swap as its draft (asking first when it already holds other
 * unsaved changes to that list, as the test page's Save this change does) and its Test this change sheet
 * open (variant.js vtOpenTestFromRoute). Copies the list no longer plays aren't swapped. Nothing more is done
 * once the person has left the page or switched profile, and the button waits while it works. */
async function testReplacementSwap(data, card, candidate, button) {
  if (button && button.disabled) return;
  const version = data.version === "owned" ? "owned" : "target";
  const token = routeToken, hash = location.hash, profile = state.profile && state.profile.id;
  const here = () => token === routeToken && hash === location.hash && (state.profile && state.profile.id) === profile;
  if (button) button.disabled = true;
  try {
    let view;
    try {
      view = await api(`/api/deck/edit?id=${encodeURIComponent(data.summary.id)}`);
    } catch (e) {
      if (here()) toast(e.message);
      return;
    }
    if (!here()) return;
    const id = view.id || data.summary.id;
    const sections = view.lists && view.lists[version];
    const swapped = sections ? replacementSwapList(sections, card.name, candidate) : null;
    if (!swapped) {
      toast(`${card.name} isn't in the ${listName(version, true)} any more.`);
      return;
    }
    const key = draftKey({ mode: "edit", profile, id, version });
    if (local.get(key)) {
      const answer = await ask("Replace your unsaved changes?",
        [`Replace your unsaved changes to ${view.title || data.summary.title} with this swap?`],
        [{ text: "Replace them", kind: "primary", value: "replace" }, { text: "Keep my changes", value: "keep" }]);
      if (answer !== "replace" || !here()) return;
    }
    const stored = local.set(key, JSON.stringify({ v: 1, saved: Date.now(), sha256: view.sha256, starting: false,
      base: { lists: sections, fields: pickFields(view.fields) },
      lists: swapped, fields: pickFields(view.fields), addSection: "Deck" }));
    if (!stored) {
      toast("The swap couldn't be kept on this device, so it can't be tested. Make it in the editor instead.");
      return;
    }
    location.hash = `${editHref(id, version)}&test=change`;
  } finally {
    if (button) button.disabled = false;
  }
}

/** A list's sections with up to candidate.max_qty copies of name taken off its Deck lines and as many of the
 * candidate added (on its line of the same printing, else a new line in its default printing), or null when
 * the Deck section has no copy of name. */
function replacementSwapList(sections, name, candidate) {
  const out = {};
  for (const [section, lines] of Object.entries(sections)) out[section] = (lines || []).map((l) => ({ ...l }));
  const same = (a, b) => a.toLowerCase() === b.toLowerCase();
  let left = Math.max(1, candidate.max_qty || 1), taken = 0;
  for (const line of out.Deck || []) {
    if (left && same(line.name, name)) {
      const take = Math.min(left, line.qty);
      line.qty -= take; left -= take; taken += take;
    }
  }
  if (!taken) return null;
  out.Deck = out.Deck.filter((l) => l.qty > 0);
  const printing = candidate.default || {};
  const line = { qty: taken, name: candidate.name, card: candidate.card || null };
  if (printing.set) {
    line.set = printing.set;
    if (printing.number) line.number = printing.number;
  }
  if (printing.finish && printing.finish !== "nonfoil") line.finish = printing.finish;
  const existing = out.Deck.find((l) => same(l.name, candidate.name) && (l.set || "") === (line.set || "")
    && (l.number || "") === (line.number || "") && (l.finish || "nonfoil") === (line.finish || "nonfoil"));
  if (existing) existing.qty += taken;
  else out.Deck.push(line);
  return out;
}


// ------------------------------------------------- free dual lands for a short colour (E3-S25)

/** The single colours (W, U, B, R, G) the Stats tab's colour check finds short, in its order. */
function shortColours(st) {
  const rows = (st && st.colours && st.colours.colours) || [];
  return rows.filter((r) => r && r.ok === false && /^[WUBRG]$/.test(r.colours)).map((r) => r.colours);
}

/** "Free dual lands" under the Stats tab's colour sources (stats.js colourPanel), or null: only when a colour
 * is short, on an ordinary deck whose collection the visitor may see (as the free replacements). Opening it asks
 * GET /api/deck/dual-lands once; a refusal (400, 403, 404) takes the part away, any other failure says so with
 * Try again. Each land's Test this swap swaps it for the basic it would replace (testReplacementSwap). */
function shortColourLands(data) {
  const short = shortColours(data && data.stats);
  if (!short.length || !data.summary || !deckSwapsOffered(data)
      || !/^(?:[^/]+\/)?(?:casual|commander)\//.test(data.summary.id)) return null;
  const version = data.version === "owned" ? "owned" : "target";
  const words = short.map((c) => COLOUR_WORDS[c] || c).join(" and ");
  const body = el("div", { class: "dual-lands" });
  const part = el("details", { class: "more dual-lands-part" }, el("summary", { text: `Free dual lands for ${words}` }), body);
  const viewer = state.profile && state.profile.id;
  let asked = false;
  const ask = () => {
    asked = true;
    body.replaceChildren(loadingBox("Looking through the collection…", { small: true }));
    api(`/api/deck/dual-lands?id=${encodeURIComponent(data.summary.id)}&version=${version}`).then((answer) => {
      if ((state.profile && state.profile.id) !== viewer || !answer || !Array.isArray(answer.lands)) { part.remove(); return; }
      body.replaceChildren(...dualLandsBody(data, answer));
    }, (e) => {
      if ((state.profile && state.profile.id) !== viewer || [400, 403, 404].includes(e && e.status)) { part.remove(); return; }
      body.replaceChildren(loadFailed("Free dual lands", e, ask));
    });
  };
  part.addEventListener("toggle", () => { if (part.open && !asked) ask(); });
  return part;
}

function dualLandsBody(data, answer) {
  const colourWords = (list) => (list || []).map((c) => COLOUR_WORDS[c] || c).join(" and ");
  const short = colourWords((answer.short || []).map((s) => s.colour));
  if (!answer.lands.length) {
    const text = !answer.short || !answer.short.length ? "No colour is short of sources in this list."
      : !answer.basics ? "The list has no basic lands to swap out."
      : `No free land in the collection makes ${short} and another of the deck's colours.`;
    return [el("p", { class: "sub", text })];
  }
  return [
    el("p", { class: "sub" }, el("b", { text: "Free dual lands: " }),
      `lands no other built deck holds that make ${short} and another of the deck's colours, each for the basic it would replace.`),
    el("ul", { class: "swap-list" }, answer.lands.map((c) => el("li", { class: "swap-row" },
      cardRow(c.card, { name: c.name, meta: `${swapCandidateMeta(c)} · for ${plural(c.max_qty, c.replaces.name, /s$/.test(c.replaces.name) ? c.replaces.name : undefined)}`,
        viewerGroup: "deck-dual-lands", chips: !c.here ? [status("info", "On the way")] : [],
        caption: `${c.name} for ${c.replaces.name}` }),
      el("p", { class: "sub swap-note", text: c.note && c.note.text }),
      el("button", { type: "button", class: "btn swap-use", text: "Test this swap",
        "aria-label": `Test ${c.name} for ${c.replaces.name}`,
        onclick: (e) => testReplacementSwap(data, { name: c.replaces.name }, c, e.currentTarget) })))),
    answer.more ? el("p", { class: "sub", text: `${plural(answer.more, "more land fits", "more lands fit")}; these fix the most.` }) : null];
}
