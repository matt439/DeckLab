/* Deck Lab's page: the Decks page's "Tables out of date" list (E7-S09), and the notes that point at it.

The list (libTablesPanel, drawn by library.js's drawLibrary between the warnings and the filters) comes from
GET /api/tables/stale, fetched after the shelf is drawn so it never holds the shelf up: the decks whose
owned-vs-needed tables no longer match the collection, with Update all (editor-deckpage.js's staleTablesPart:
one POST /api/tables/update of every deck the visitor may change, one change in Deck Lab), the decks whose
tables can't be updated and why (an unknown card name, no table), and the spaces whose tables wait (Update all,
receipts and orders leave them) until their collection is fixed. A visitor who may not see a space's collection gets none of
its decks (the server leaves them out). #/library?tables=1 (TABLES_HREF) scrolls to it once.

The Collection page's note after a save (staleTablesNote) and Receive delivery's note about tables it left
(tablesLaterNote) link here. Loaded after library.js; nothing here runs at load.
*/
"use strict";

const TABLES_HREF = "#/library?tables=1";

/** The "Tables out of date" panel: hidden until GET /api/tables/stale has something to show. A failure leaves it
 * hidden on a normal visit (the shelf is what matters), but when the address asked for it (?tables=1) the panel
 * says so with Try again. scrolled: the address asked for it, so it's scrolled to once it's filled (or failed),
 * and then called (the address drops the ask). onUpdated: after Update all. */
function libTablesPanel(scrolled, onUpdated) {
  const host = el("section", { class: "box box-stale lib-tables", id: "stale-tables", tabindex: "-1",
    "aria-label": "Tables out of date", hidden: true });
  const asked = Boolean(scrolled);
  const show = () => { host.hidden = false; host.removeAttribute("hidden"); };
  // Failed or loading again, the panel is only its crit note or spinner line: not inside the stale box's
  // colours and refresh icon (a failure never looks like a notice of out-of-date tables).
  const boxed = (on) => { host.classList.toggle("box", on); host.classList.toggle("box-stale", on); };
  const fill = async () => {
    let data;
    try {
      data = await api("/api/tables/stale");
    } catch (e) {
      if (!host.isConnected) return;
      if (asked) {
        boxed(false);
        clear(host).append(loadFailed("The out-of-date tables", e, () => {
          clear(host).append(loadingBox("Loading the out-of-date tables…", { small: true }));
          fill();
        }));
        show();
      }
      if (scrolled) { host.scrollIntoView({ block: "start" }); scrolled(); scrolled = null; }
      return;
    }
    if (!host.isConnected) return;
    clear(host);
    boxed(true);
    host.hidden = true;
    const stale = data.stale || [];
    const blocked = data.blocked || [];
    const held = data.held || [];
    if (stale.length || blocked.length || held.length) {
      host.append(staleTablesPart(stale, { standalone: true, blocked, held, after: blockedTablesPart, onUpdated }));
      show();
      if (scrolled) host.scrollIntoView({ block: "start" });
    }
    if (scrolled) { scrolled(); scrolled = null; }
  };
  fill();
  return host;
}

/** The library's decks fetched again after Update all (their missing-card counts follow the tables), and the
 * shelf redrawn by refresh() (drawLibrary's: false once the library has been left). On a failure a toast says
 * the tables were updated but the shelf's counts are as they were. */
async function libReloadShelf(data, refresh) {
  try {
    const fresh = await api("/api/decks");
    Object.assign(data, fresh);
    if (refresh()) state.library = data;
  } catch (e) {
    toast("Tables updated. Reload Decks to see the new counts.");
  }
}

/** What a blocked deck's problem is, in words: "it has no owned-vs-needed table". */
function blockedReasonWords(b) {
  const cards = (b.cards || []).join(", ");
  if (b.reason === "no_table") return "it has no owned-vs-needed table";
  if (b.reason === "no_decklist") return "it has no decklist";
  if (b.reason === "unknown_cards") return `card names Deck Lab doesn't know in its ${listName(b.version, true)}: ${cards}`;
  if (b.reason === "unreadable") return "its text can't be read";
  return b.why || "it can't be worked out";
}

/** Why a space's tables are held (its pool is incomplete), in words. */
function heldWords(h) {
  const parts = [];
  const unknown = h.unknown || [];
  if (unknown.length) {
    parts.push(`card names Deck Lab doesn't know: ${unknown.map((u) =>
      (u.where && u.where.length ? `${u.name} (in ${u.where.join(", ")})` : u.name)).join(", ")}`);
  }
  parts.push(...(h.warnings || []));
  return parts.length ? parts.join("; ") : h.why;
}

/** Under the list (staleTablesPart's opts.after): the decks whose tables can't be updated, one line each
 * with every reason, and the spaces whose tables wait until their collection is fixed. alone: nothing is out of
 * date above it, so this part has the panel's heading. */
function blockedTablesPart({ blocked, held, alone }) {
  const out = [];
  if (blocked.length) {
    const byDeck = new Map();
    for (const b of blocked) {
      if (!byDeck.has(b.id)) byDeck.set(b.id, { title: b.title, reasons: [] });
      byDeck.get(b.id).reasons.push(blockedReasonWords(b));
    }
    const one = byDeck.size === 1;
    out.push(alone ? el("h2", { text: one ? "A deck's owned-vs-needed table can't be updated"
      : `${byDeck.size} decks' owned-vs-needed tables can't be updated` }) : el("h3", { text: "Can't be updated" }),
    el("p", { class: "sub", text: `Update all leaves ${one ? "it" : "them"} out until ${one ? "it's" : "they're"} fixed in the deck's editor.` }),
    el("ul", { class: "sources-list" }, [...byDeck].map(([id, d]) => el("li", {},
      el("a", { href: deckHref(id), text: d.title }), `: ${d.reasons.join("; ")}.`))));
  }
  for (const h of held) {
    const whose = h.space === HOME_SPACE ? "the home decks'" : `${spaceName(h.space)}'s decks'`;
    out.push(el("p", { class: "note note-warn", text: `Update all, receipts and orders leave ${whose} tables as they are until this is fixed: ${heldWords(h)}.` }));
  }
  return out;
}

/** The Collection page's line after a save that left decks' tables out of date (the answer's stale_tables),
 * with a link to the list; null when it left none. */
function staleTablesNote(stale) {
  if (!stale || !stale.length) return null;
  const one = stale.length === 1;
  return el("p", { class: "stale-note" },
    one ? "1 deck's owned-vs-needed table is now out of date. " : `${num(stale.length)} decks' owned-vs-needed tables are now out of date. `,
    el("a", { href: TABLES_HREF, text: "See them on Decks" }));
}

/** Receive delivery's warning about tables it didn't update (lead: what happened), pointing at the list. The
 * words are one span: a .note is a flex row, which would set a bare link apart from its sentence. */
function tablesLaterNote(lead) {
  return el("p", { class: "note note-warn" }, el("span", {}, `${lead} They're on the Decks page's `,
    el("a", { href: TABLES_HREF, text: "Tables out of date" }), " list, where Update all refreshes them."));
}
