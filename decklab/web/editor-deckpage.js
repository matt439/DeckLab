/* Deck Lab's editor: its parts on the deck page (Milestone 4).

Loaded last of the editor's scripts (after editor.js, editor-screen.js, editor-details.js,
editor-lines.js, editor-cards.js and editor-save.js), before matchups.js and the page's other scripts (core.js to app.js). deck.js's deck
page calls deckActions, savedBox and staleTableBox. It uses editor.js's timeWords, editHref, busy and
unbusy.

On the deck page: what the save just did (savedBox: saved in Deck Lab, nothing about git), and
out-of-date owned-vs-needed tables (staleTablesPart, staleTableBox).
*/
"use strict";

// --------------------------------------------------------- on the deck page

/** The deck page's Edit button, "Try a change" for someone else's deck, or "Save as a new deck" for a
 * read-only deck. Edit and Save as a new deck work at every width (a phone gets the Quick edit, a new deck's
 * title and format then its cards); Try a change only from a tablet up, since its point is testing the change
 * against other decks, which the Quick edit doesn't offer. */
function deckActions(data) {
  const s = data.summary;
  if (!s.read_only && canEditDeck(s)) {
    // With two lists the button names the one it edits; on a phone it says just "Edit" (the rest stays in its
    // accessible name), so the deck's title keeps the head's row.
    const which = data.versions.length > 1 ? ` the ${listName(data.version, true)}` : "";
    return el("div", { class: "deck-actions" },
      el("a", { class: "btn btn-primary", href: editHref(s.id, data.version), "aria-label": which ? `Edit${which}` : null },
        "Edit", which ? el("span", { class: "deck-edit-which", text: which }) : null));
  }
  if (!s.read_only) {
    if (!canBuildDecks()) return null;
    // Someone else's deck: changes can be tried and tested against other decks, but not saved.
    return el("div", { class: "deck-actions deck-actions-wide" },
      el("a", { class: "btn", href: editHref(s.id, data.version), text: "Try a change",
        title: "Only its owner can save it; you can try a change and test it." }));
  }
  if (!createTargets().length) return null;
  return el("div", { class: "deck-actions deck-actions-wide" },
    el("a", { class: "btn btn-primary", text: "Save as a new deck",
      title: s.id.startsWith("pairing/") ? "Pairings stay as they are" : "Product decks stay as they came",
      href: newDeckHref().replace(/^#\/new(\?|$)/, (_, q) => `#/new?from=${encodeURIComponent(s.id)}${q ? "&" : ""}`) }));
}


/** The box at the top of the deck page after a save (state.saved), once. */
function savedBox(id) {
  const saved = state.saved;
  if (!saved || saved.hash !== location.hash || saved.profile && saved.profile !== state.profile?.id) return null;
  const a = saved.answer;
  const created = !!a.created;
  const box = el("section", { class: "box box-good saved-box", "aria-labelledby": "saved-title", tabindex: "-1" });
  const dismiss = el("button", { type: "button", class: "btn btn-quiet sheet-close", "aria-label": "Close this box", text: "×",
    onclick: () => { state.saved = null; box.remove(); } });
  const table = a.table || {};
  const others = a.warnings || [];
  add(box, [
    el("div", { class: "saved-head" },
      el("h2", { id: "saved-title", text: created ? `${a.title} is created` : a.changed === false ? "Nothing needed saving" : `${a.title} is saved` }),
      dismiss),
    created ? el("p", { text: `Saved in Deck Lab as ${a.id}. Change it any time with Edit.` })
      : a.changed === false ? el("p", { text: "The deck already had these lists and details, so nothing was saved." })
        : el("p", { text: a.marked ? "Saved in Deck Lab: the deck has your changes, and the stats, practice hands and owned vs needed below follow the new list."
          : "Saved in Deck Lab: the deck has your changes to its details." }),
    a.after_save_test ? saved.testNotice = el("p", { class: "sub", role: "status", text: a.after_save_test.text }) : null,
    // Added from a precon (collection.js, addPrecon): its cards went into the collection in the same save.
    a.precon ? el("p", { text: a.precon.cards
      ? `With it, ${plural(a.precon.cards, "card")} from the ${a.precon.name} precon went into ${a.precon.whose}.`
      : `The ${a.precon.name} precon had only plain basic lands for ${a.precon.whose}, so no cards were added.` }) : null,
    a.precon && Number.isSafeInteger(a.precon.tokens) && a.precon.tokens > 0 ? el("p", { text:
      `${plural(a.precon.tokens, "token card")} also added as unconfirmed rows. Check their printings and reverse faces on the Tokens page.` }) : null,
    a.precon?.tokens_uncertain ? el("p", { class: "box box-warn", text:
      "The token addition count was not confirmed. Check the Tokens page before adding any again." }) : null,
    a.marked ? el("p", { class: "sub", text: `The deck now says “Decklist changed in Deck Lab on ${a.marked}”, so the write-up under the list can be brought up to date later.` }) : null,
    table.rewritten && table.repriced && !table.note ? el("p", { class: "sub", text: "Its owned-vs-needed table was worked out again, with today's prices." }) : null,
    table.note ? el("p", { class: "sub", text: table.note }) : null,
    others.length ? el("details", { class: "more" }, el("summary", { text: `Worth a look (${others.length})` }),
      el("ul", { class: "sources-list" }, others.map((w) => el("li", { text: w })))) : null,
    a.stale_tables && a.stale_tables.length ? staleTablesPart(a.stale_tables) : null]);
  if (a.precon?.filing) add(box, [colFilingSavedBox(saved, box)]);
  return box;
}

/** A deck in a "tables" 409 (conflict.decks), in words: who changed it and when. */
function tableConflictWords(d) {
  const when = d.when ? ` at ${timeWords(Date.parse(d.when))}` : "";
  if (d.reason === "deleted") return `${d.title} was deleted${when}`;
  if (d.deck_lab && d.by) return `${d.by} saved ${d.title} in Deck Lab${when}`;
  if (d.by) return `${d.by} changed ${d.title}${when}`;
  return `${d.title} was saved again${when}`;
}

/** Decks whose owned-vs-needed tables are out of date, with "Update their tables": after a save, the other
 * decks', only those the visitor may change (each entry's may_update, or canEditDeckId from an older server).
 * opts.standalone: the Decks page's "Tables out of date" list (library-tables.js) instead: every deck it's
 * given, "Update all" for those with may_update, and what opts.after({blocked, held, alone}) draws under it
 * (GET /api/tables/stale's blocked decks, left out of the list, and held spaces). opts.onUpdated(answer)
 * runs after an update. */
function staleTablesPart(stale, opts = {}) {
  const solo = Boolean(opts.standalone);
  let blocked = opts.blocked || [];
  let held = opts.held || [];
  const host = el("div", { class: "stale-part" });
  // Update decks' tables, then draw what's left, under what happened (before: earlier results kept above it).
  const update = async (decks, button, error, before) => {
    busy(button, "Updating...");
    error.textContent = "";
    try {
      const body = { decks: decks.map((d) => ({ id: d.id, sha256: d.sha256 })) };
      const answer = await apiWrite("/api/tables/update", body);
      draw(answer.stale_tables || [], [...before, updatedWords(answer)]);
      if (opts.onUpdated) opts.onUpdated(answer);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      unbusy(button);
      if (e.status !== 409) {
        error.textContent = `The tables couldn't be updated: ${e.message}`;
        return;
      }
      // Someone changed one of those decks since this list was worked out: say who, and list them again.
      const changed = (e.data && e.data.conflict && e.data.conflict.decks) || [];
      const why = changed.length ? `Since this list was worked out, ${changed.map(tableConflictWords).join("; ")}.` : e.message;
      try {
        const fresh = await api("/api/tables/stale");
        if (solo) { blocked = fresh.blocked || []; held = fresh.held || []; }
        draw(fresh.stale, [...before, el("p", { class: "form-error", role: "alert", text: `${why} No tables were updated. Here's the list as it is now.` })]);
      } catch (e2) {
        if (!(e2 instanceof ApiError)) throw e2;
        error.textContent = `${why} No tables were updated.`;
      }
    }
  };
  const mayUpdate = (d) => ("may_update" in d ? Boolean(d.may_update) : canEditDeckId(d.id));
  const draw = (list, before = []) => {
    clear(host);
    add(host, before);
    // A deck that can't be updated (an unknown card, no table) is named under the list instead.
    const stuck = new Set(blocked.map((b) => b.id));
    list = list.filter((d) => !stuck.has(d.id) && (solo || mayUpdate(d)));
    // A space whose collection is incomplete (held) waits too: its tables would be worked out from it.
    const waiting = new Set(solo ? held.map((h) => h.space) : []);
    const mine = list.filter((d) => mayUpdate(d) && !waiting.has(deckSpaceOf(d.id)));
    const someWait = list.some((d) => mayUpdate(d) && waiting.has(deckSpaceOf(d.id)));
    if (list.length) {
      const one = list.length === 1;
      const error = el("p", { class: "form-error", role: "alert" });
      const button = mine.length ? el("button", { type: "button", class: solo ? "btn" : "btn btn-primary",
        text: solo ? "Update all" : one ? "Update its table" : "Update their tables" }) : null;
      if (button) button.addEventListener("click", () => update(mine, button, error, []));
      const heading = solo ? (one ? "A deck's owned-vs-needed table is out of date" : `${list.length} decks' owned-vs-needed tables are out of date`)
        : one ? "Another deck's owned-vs-needed table is out of date" : `${list.length} other decks' owned-vs-needed tables are out of date`;
      add(host, [
        el(solo ? "h2" : "h3", { text: heading }),
        el("p", { class: "sub", text: "The tables written in those decks don't match what the collection gives now: cards ordered since they were written, or cards a built deck holds. Updating rewrites only those tables (with today's prices), saved together in Deck Lab." }),
        el("details", { class: "more" }, el("summary", { text: one ? "Which deck" : "Which decks" }),
          el("ul", { class: "sources-list" }, list.map((d) => el("li", {}, el("a", { href: deckHref(d.id), text: d.title }),
            d.count ? ` (${plural(d.count, "card")} changed)` : "")))),
        mine.length && mine.length < list.length
          ? el("p", { class: "sub", text: someWait
            ? `Update all updates the ${plural(mine.length, "deck")} you may change whose collection is complete; the others wait.`
            : `Update all updates the ${plural(mine.length, "deck")} you may change; the others wait for whoever plays them.` }) : null,
        button ? el("div", { class: "actions" }, button)
          : el("p", { class: "sub", text: someWait
            ? "These tables wait until the problem below is fixed."
            : "You can't change these decks, so their tables wait for whoever plays them." }),
        error]);
    }
    if (opts.after) add(host, opts.after({ blocked, held, alone: !list.length }));
  };
  draw(stale);
  return host;
}

/** What a table update did: the tables it updated (or that nothing was, when every one already matched),
 * and its notes. */
function updatedWords(a) {
  const updated = a.updated || [];
  const notes = updated.filter((u) => u.note);
  const matched = (a.unchanged || []).length;
  const others = a.warnings || [];
  return el("div", { class: "updated" },
    updated.length ? el("p", {}, status("good", "Updated"), ` ${plural(updated.length, "table")}` +
      (matched > 0 ? `; ${matched} already matched` : "") + ". Saved in Deck Lab.")
      : el("p", {}, status("plain", "No tables updated"), matched > 0 ? ` ${plural(matched, "table")} already matched.` : ""),
    notes.length || others.length ? el("ul", { class: "sources-list" }, notes.map((u) => el("li", { text: `${u.title}: ${u.note}` })),
      others.map((w) => el("li", { text: w }))) : null);
}

function tableChangeWords(c) {
  const side = (x) => `${x.missing ? `${x.missing} missing` : "none missing"}` + (x.labels.length ? ` (${x.labels.join("; ")})` : "");
  if (!c.was) return `${c.card}: not in the deck's table yet; now ${side(c.now)}.`;
  if (!c.now) return `${c.card}: in the deck's table, but not in the list any more.`;
  if (c.was.need !== c.now.need) return `${c.card}: the table says ${c.was.need} needed, ${side(c.was)}; now ${c.now.need} needed, ${side(c.now)}.`;
  return `${c.card}: the table says ${side(c.was)}; now ${side(c.now)}.`;
}

/** The deck page's note when the deck's own owned-vs-needed table is out of date, with "Update the table". */
function staleTableBox(data) {
  const t = data.table;
  if (!t || !t.has_table || !t.stale || !state.profile || !canEditDeck(data.summary)) return null;
  const n = t.changes.length;
  const deck = { id: data.summary.id, title: data.summary.title, sha256: t.sha256 };
  const error = el("p", { class: "form-error", role: "alert" });
  const button = el("button", { type: "button", class: "btn", text: "Update the table" });
  button.addEventListener("click", async () => {
    busy(button, "Updating...");
    error.textContent = "";
    try {
      await apiWrite("/api/tables/update", { decks: [{ id: deck.id, sha256: deck.sha256 }] });
      toast("The deck's table is updated and saved in Deck Lab.");
      route();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      unbusy(button);
      error.textContent = e.status === 409 ? `${e.message} Reload the page to see it.` : `The table couldn't be updated: ${e.message}`;
    }
  });
  return el("div", { class: "box box-stale stale-own" },
    el("h3", { text: "The deck's owned-vs-needed table is out of date" }),
    el("p", { text: `The numbers above are worked out now. The owned-vs-needed table written in ${data.summary.title} was worked out earlier, and ${n === 1 ? "1 card's row differs" : `${n} cards' rows differ`}: cards ordered since, or copies other decks now hold.` }),
    el("details", { class: "more" }, el("summary", { text: "What's different" }),
      el("ul", { class: "sources-list" }, t.changes.map((c) => el("li", { text: tableChangeWords(c) })))),
    el("div", { class: "stale-own-actions" }, el("div", { class: "actions" }, button), error));
}
