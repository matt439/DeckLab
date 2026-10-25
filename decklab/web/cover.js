/* Deck Lab's page: choosing a deck's picture, its cover card (owner decision 4 of decklab/UI-REVIEW.md). By
default the library shows the commander's art, else the most-copied card's (lib/decks/cover.py); this
picker writes the deck text's "Cover card" line instead, or takes it away (Automatic), through POST
/api/deck/cover (lib/api/cover.py: one change, as a save of the deck).

openCoverPicker(deckId, onDone) reads GET /api/deck/cards (the deck's cards once each, the automatic cover,
and the cover and revision now: a light read, not the whole deck page) and opens a sheet with "Automatic"
and the deck's cards as art tiles, a search, and "Different printing…" (cards-ui.js pickPrinting) for the
art of another printing. Each card tile's magnifier opens the card viewer over all the cards (viewer group
"cover"); Automatic's opens it at its card's own tile, so the group never shows a card twice. Saving shows a
toast with Undo, which writes back the line as it was (no Undo when the line was one Deck Lab couldn't use: it
can't be written back as it was, and stays in the deck's history); onDone(cover, revision) gets the deck's cover and
text revision afterwards. The library's "Choose deck pictures" uses it, and the deck page may too.

Loaded after library.js; uses core.js, ui.js, cards-ui.js, card-viewer.js and editor.js's sheet helpers once
the page is running. Nothing here runs at load.
*/
"use strict";

/** The art crop of a card's picture: "/img/fdn/227/art_crop" for "/img/fdn/227/normal"; null for anything else. */
function coverArt(url) {
  return typeof url === "string" && /^\/img\/[^/]+\/[^/]+\/normal$/.test(url) ? url.replace(/\/normal$/, "/art_crop") : null;
}

/** The art crop of a printing by its set and number. */
function coverArtOf(set, number) {
  return set && number ? `/img/${encodeURIComponent(set)}/${encodeURIComponent(number)}/art_crop` : null;
}

/** Same card name? (Scryfall's names, compared without case.) */
function coverSameName(a, b) {
  return Boolean(a && b) && String(a).toLowerCase() === String(b).toLowerCase();
}

/** Same cover? (both automatic, or the same card and printing). */
function coverSame(a, b) {
  if (!a || !b) return !a && !b;
  return coverSameName(a.name, b.name) && (a.set || null) === (b.set || null) && (a.number || null) === (b.number || null);
}

/** Saves a cover ({name, set?, number?} or null for automatic) for a deck at revision expect: the API's answer. */
function saveCover(deckId, cover, expect) {
  const body = { id: deckId, expect, cover: cover ? { name: cover.name, ...(cover.set && cover.number
    ? { set: cover.set, number: cover.number } : {}) } : null };
  return apiWrite("/api/deck/cover", body);
}

/** Opens the picture picker for a deck (see the file's comment). */
function openCoverPicker(deckId, onDone) {
  const sheet = openSheet({ title: "Deck picture", wide: true });
  const body = el("div", { class: "cover-picker" }, loadingBox("Getting the deck's cards…"));
  sheet.body.append(body);
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  api(`/api/deck/cards?id=${encodeURIComponent(deckId)}`).then((data) => {
    if (!sheet.closed) drawCoverPicker(sheet, body, deckId, data, onDone);
  }).catch((e) => {
    if (!(e instanceof ApiError)) throw e;
    if (!sheet.closed) add(clear(body), [el("div", { class: "box box-crit" }, el("p", { text: e.message }))]);
  });
  return sheet;
}

function drawCoverPicker(sheet, body, deckId, data, onDone) {
  const summary = data.summary || {};
  const title = summary.title || deckId;
  const current = summary.cover || null;
  // The line as written now (its printing only when it names one): what Undo writes back.
  const now = current && !current.auto ? { name: current.name, set: current.set || null, number: current.number || null } : null;
  // A Cover card line Deck Lab can't use (the picture fell back to automatic): the cover API can't write it back
  // as it was, so a change gets no Undo (the line stays in the deck's history), and Automatic removes it.
  const unusable = current && current.auto && current.problem && current.written ? current.written : null;
  const auto = data.auto || null;
  const cards = data.cards || [];
  // The choice: null is Automatic; a card with an optional printing otherwise.
  let chosen = now;
  const tiles = [];
  const error = el("p", { class: "form-error", role: "alert" });

  const artImg = (art) => (art ? el("img", { src: art, alt: "", loading: "lazy", decoding: "async", width: 626, height: 457,
    onerror: (e) => e.currentTarget.remove() }) : null);

  // A card's tile: a printing the deck page shows for it (item.set, item.number), in the viewer group.
  const cardTile = (item) => {
    const card = item.card;
    const art = coverArtOf(item.set, item.number) || coverArt(card && card.img);
    const pick = el("button", { type: "button", class: "cover-tile-pick", "aria-pressed": "false", "aria-label": item.name,
      onclick: () => { chosen = { name: item.name, set: item.set || null, number: item.number || null }; sync(); } },
      el("span", { class: "cover-tile-art" }, artImg(art)),
      el("span", { class: "cover-tile-name" }, item.name));
    if (card) viewerItem(pick, card, "cover");
    const zoom = card ? el("button", { type: "button", class: "cover-tile-zoom",
      "aria-label": `Show ${item.name} large`, "aria-haspopup": "dialog", text: "⤢",
      onclick: () => openCard(card, pick) }) : null;
    const node = el("div", { class: "cover-tile", "data-name": item.name.toLowerCase() }, pick, zoom);
    tiles.push({ node, pick, item, isAuto: false, art });
    return node;
  };

  // Automatic: not in the viewer group (its card has its own tile); its magnifier opens the viewer there.
  const autoTile = () => {
    const art = current && current.auto && current.art ? current.art : auto ? auto.art : null;
    const pick = el("button", { type: "button", class: "cover-tile-pick", "aria-pressed": "false",
      "aria-label": `Automatic${auto ? `: ${auto.name}` : ""}`,
      onclick: () => { chosen = null; sync(); } },
      el("span", { class: "cover-tile-art" }, artImg(art)),
      el("span", { class: "cover-tile-name" }, el("b", { text: "Automatic" }), auto ? el("small", { text: auto.name }) : null));
    const zoom = auto ? el("button", { type: "button", class: "cover-tile-zoom",
      "aria-label": `Show ${auto.name} large`, "aria-haspopup": "dialog", text: "⤢",
      onclick: (e) => {
        const own = tiles.find((t) => !t.isAuto && coverSameName(t.item.name, auto.name));
        const group = own ? viewerGroup(own.pick) : null;
        if (group) openCardViewer(group.items, group.index, { trigger: e.currentTarget });
        else if (own && own.item.card) openCardViewer([own.item.card], 0, { trigger: e.currentTarget });
      } }) : null;
    const node = el("div", { class: "cover-tile is-auto", "data-name": "" }, pick, zoom);
    tiles.push({ node, pick, item: auto, isAuto: true, art });
    return node;
  };

  const search = el("input", { type: "search", class: "cover-search", placeholder: "Find a card", "aria-label": "Find a card",
    oninput: () => {
      const q = search.value.trim().toLowerCase();
      for (const t of tiles) t.node.hidden = Boolean(q) && !t.isAuto && !t.node.dataset.name.includes(q);
    } });
  const printing = el("p", { class: "cover-printing" });
  const grid = el("div", { class: "cover-grid" }, autoTile(), cards.map(cardTile));

  function sync() {
    for (const t of tiles) {
      const on = t.isAuto ? !chosen : Boolean(chosen && coverSameName(chosen.name, t.item.name));
      t.pick.setAttribute("aria-pressed", String(on));
      t.node.classList.toggle("is-chosen", on);
      const img = t.pick.querySelector("img");
      let art = t.art;
      if (on && !t.isAuto) {
        // The chosen printing's art; the line's own picture while it names no printing.
        art = chosen.set && chosen.number ? coverArtOf(chosen.set, chosen.number)
          : now && coverSame(chosen, now) && current.art ? current.art : t.art;
      }
      if (img && art && img.getAttribute("src") !== art) img.setAttribute("src", art);
    }
    printing.textContent = chosen && chosen.set && chosen.number
      ? `${chosen.name}: the ${chosen.set.toUpperCase()} ${chosen.number} printing's art` : "";
    error.textContent = "";
    const changed = !coverSame(chosen, now) || Boolean(unusable);
    sheetActions(sheet, [
      chosen ? { text: "Different printing…", onclick: async () => {
        const p = await pickPrinting(chosen.name, { title: `${chosen.name}: which art?`,
          current: chosen.set ? { set: chosen.set, number: chosen.number, finish: "nonfoil" } : null });
        if (p && p.set && p.number) { chosen = { name: chosen.name, set: p.set, number: p.number }; sync(); }
      } } : null,
      { text: changed ? "Use this picture" : "Keep this picture", kind: changed ? "primary" : "",
        onclick: (e) => (changed ? save(e.currentTarget) : sheet.close()) }]);
  }

  async function save(button) {
    busy(button, "Saving…");
    try {
      const answer = await saveCover(deckId, chosen, summary.revision != null ? summary.revision : 0);
      sheet.close();
      const before = now;
      const words = chosen ? `${title}'s picture is now ${chosen.name}.` : `${title}'s picture is automatic again.`;
      if (unusable) {
        toast(`${words} The line it replaced ("${unusable}") is in the deck's history.`);
        if (onDone) onDone(answer.cover, answer.revision);
        return;
      }
      showToast(words, { undo: async () => {
        try {
          const back = await saveCover(deckId, before, answer.revision);
          if (onDone) onDone(back.cover, back.revision);
          toast("Picture put back.");
        } catch (e) {
          if (!(e instanceof ApiError)) throw e;
          toast(e.message);
        }
      } });
      if (onDone) onDone(answer.cover, answer.revision);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      unbusy(button);
      error.textContent = e.status === 409 ? `${e.message} Close this and open it again to see the deck as it is now.`
        : e.message;
    }
  }

  add(clear(body), [
    el("p", { class: "cover-now" }, "Shown now: ", el("b", { text: current ? current.name : "nothing yet" }),
      current && current.auto ? " (automatic: the commander, or the card with the most copies)" : null),
    current && current.problem ? el("div", { class: "note note-warn" }, el("p", { text: `${current.problem}, so the picture is automatic.` })) : null,
    cards.length > 8 ? search : null,
    grid, printing, error]);
  sync();
  const mark = tiles.find((t) => t.node.classList.contains("is-chosen"));
  if (mark) mark.pick.focus();
}
