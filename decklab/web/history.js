/* A deck's History page (#/history?id=): every saved revision, newest first, each with what it changed against
 * the revision before it, worked out by the server (GET /api/deck/history, lib/api/history.py): the cards
 * each list gained and lost ("+2 Rabid Gnaw, −1 Shock", "1 Second Breakfast → sideboard") with their pictures,
 * which open the card viewer, and the header fields. Saves that changed neither the cards nor the header (the
 * write-up, the owned-vs-needed table) are folded into one line. Tapping a revision opens a sheet with all of
 * it, a comparison with the deck as it is now, and, for someone who may save the deck, the way to restore its
 * list, which opens as an ordinary draft in the editor. */
"use strict";

const HISTORY_INLINE = 8;           // card changes written out in a revision's line before "and N more"
const HISTORY_PICTURES = 12;        // card pictures shown in a revision's strip (a tablet or computer)
const HISTORY_PHONE_PICTURES = 8;   // ... and on a phone (history.css hides the rest), a "+N" tile in the 8th place
const HISTORY_SHORT = 40;           // header values longer than this are said to have changed, not quoted
const HISTORY_MONTH = { day: "numeric", month: "short", year: "numeric" };
// A section as a revision's words name it ("→ sideboard") and as a picture's badge marks it ("+1 SB").
const HISTORY_SECTIONS = { Deck: ["main deck", ""], Sideboard: ["sideboard", "SB"], Commander: ["commander", "Cmdr"],
  Companion: ["companion", "Comp"] };

function showHistory(params, token) {
  const id = addressDeckId(params.get("id"));
  const version = params.get("v") === "owned" ? "owned" : "target";
  load(`/api/deck/history?id=${encodeURIComponent(id)}`, token, (data) => {
    canonicalDeckAddress(data.id || id);
    historyDraw(data, data.id || id, version, token);
  },
    { title: "This deck's history couldn't be loaded", back: [deckHref(id, version), "Back to the deck"] });
}

/** The page: the head, then the revisions newest first, with runs of saves that didn't change the cards or the
 * header folded into one line. */
function historyDraw(data, id, version, token) {
  setTitle(`${data.title}: history`);
  const profile = state.profile?.id; data._historyProfile = profile;
  const revisions = data.revisions || [];
  const list = el("ol", { class: "history-revs" });
  let fold = null;
  for (const rev of revisions) {
    if (rev.change && rev.change.kind === "none") {
      if (!fold) {
        fold = { items: el("ol", { class: "history-folded" }), count: 0, summary: el("summary") };
        list.append(el("li", { class: "history-fold" }, el("details", {}, fold.summary, fold.items)));
      }
      fold.count += 1;
      fold.summary.textContent = `${plural(fold.count, "save")} without card changes`;
      fold.items.append(el("li", {}, historyFolded(rev, data, id, version, token)));
    } else {
      fold = null;
      list.append(el("li", {}, historyItem(rev, data, id, version, token)));
    }
  }
  add($("#main"), [
    pageHead({ crumb: data.retired ? ["#/library", "Decks"] : [deckHref(id, version), data.title], title: routeH1("history"),
      description: revisions.length ? `Every save of ${data.title}, newest first.` : null }),
    data.retired ? el("div", { class: "box box-info" }, el("h2", { class: "box-head", text: "Retired deck" }),
      el("p", { text: `${data.title} is no longer in the library. Its saved revisions and matchup results are kept.` }),
      data.may_restore ? el("button", { type: "button", class: "btn btn-primary", text: "Restore deck", onclick: () => {
        if (token === routeToken && profile === state.profile?.id) openRestoreDeck(data);
      } }) : null) : null,
    revisions.length ? list : el("div", { class: "empty" }, el("p", { text: "No saved changes yet." }),
      el("a", { class: "btn", href: data.retired ? "#/library" : deckHref(id, version), text: data.retired ? "Back to Decks" : "Back to the deck" })),
    data.truncated ? el("p", { class: "history-more", text: `Showing the latest ${revisions.length} saves.` }) : null,
  ]);
}

/** "12 Oct 2026, 7:20 pm" for a revision's date (its own offset, shown in this device's time). */
function historyWhen(rev) {
  const when = new Date(rev.date);
  if (Number.isNaN(when.getTime())) return rev.date.slice(0, 10);
  const time = when.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, " ");
  return `${when.toLocaleDateString("en-AU", HISTORY_MONTH)}, ${time}`;
}

/** The server sends only the subject this viewer may read, or a plain summary for an outside reader. */
function historySubject(rev) {
  const subject = rev.subject == null ? "" : String(rev.subject).trim();
  return subject || null;
}

/** What a revision did, in a few words: "Changed the planned list", "Marked it built", "Created the deck". */
function historyHeadline(rev) {
  const change = rev.change || { kind: rev.op === "D" ? "deleted" : "none", fields: [], lists: [] };
  if (change.kind === "deleted") return "Deleted the deck";
  if (change.kind === "created") return change.restored ? "Made the deck again" : "Created the deck";
  if (change.kind === "unreadable") return "Saved a text that can't be read";
  if (change.kind === "unreadable_before") return "Saved the deck (the save before it can't be read)";
  const status = change.fields.find((f) => f.key === "Status");
  const title = change.fields.find((f) => f.key === "Title");
  const statusWords = status && historyLeading(status.after) ? `marked it ${historyLeading(status.after)}` : null;
  if (change.kind === "cards") {
    const lists = change.lists.length === 2 ? "both lists" : `the ${listName(change.lists[0] || "target", true)}`;
    return `Changed ${lists}` + (statusWords ? ` and ${statusWords}` : "");
  }
  if (change.kind === "details") {
    if (title) return `Renamed it ${title.after}`;
    if (statusWords) return capitalise(statusWords);
    return `Changed ${change.fields.map((f) => f.key.toLowerCase()).join(", ")}`;
  }
  return "Saved without card changes";
}

/** A header value's first word, lower case ("built" from "built (sleeved in red)"), or null. */
function historyLeading(value) {
  const found = /^[\s`*_"']*([A-Za-z-]+)/.exec(value || "");
  return found ? found[1].toLowerCase() : null;
}

/** A list's card changes with each move between sections (the same copies of a card gone from one section and
 * come to another, such as Deck → Sideboard) as one entry: {..., delta: copies, section: where they went,
 * from: where they came from}. The rest stay as they were, in the server's order. */
function historyEntries(cards) {
  const out = cards.map((c) => ({ ...c }));
  for (const gone of out) {
    if (gone.used || !(gone.delta < 0)) continue;
    const came = out.find((c) => !c.used && c !== gone && c.list === gone.list && c.name === gone.name
      && c.section !== gone.section && c.delta === -gone.delta);
    if (!came) continue;
    gone.used = true;
    came.from = gone.section;
  }
  return out.filter((c) => !c.used);
}

/** How a section is written: "sideboard", "main deck", or the section's own name. */
function historySectionWords(section) {
  return (HISTORY_SECTIONS[section] || [String(section || "").toLowerCase()])[0];
}

/** "+2 Rabid Gnaw" / "−1 Shock (sideboard)" / "1 Second Breakfast → sideboard" / "Plains: new printing". */
function historyCardWords(c) {
  if (c.from) return `${c.delta} ${c.name} → ${historySectionWords(c.section)}`;
  const where = c.section && c.section !== "Deck" ? ` (${historySectionWords(c.section)})` : "";
  if (!c.delta) return `${c.name}${where}: new printing`;
  return `${c.delta > 0 ? "+" : "−"}${Math.abs(c.delta)} ${c.name}${where}`;
}

/** A picture's badge: "+2", "−1 SB", "→SB", or "↻" for a new printing. */
function historyBadge(c) {
  const mark = (HISTORY_SECTIONS[c.section] || ["", c.section ? c.section.slice(0, 4) : ""])[1];
  if (c.from) return `→${mark || "Main"}`;
  const amount = c.delta ? `${c.delta > 0 ? "+" : "−"}${Math.abs(c.delta)}` : "↻";
  return mark ? `${amount} ${mark}` : amount;
}

/** The changes of one list as a line: "+2 Rabid Gnaw, −1 Shock and 3 more". */
function historyListLine(cards, extra = 0) {
  const shown = cards.slice(0, HISTORY_INLINE).map(historyCardWords);
  const more = cards.length - shown.length + extra;
  if (!shown.length) return more > 0 ? plural(more, "card change") : "";
  return shown.join(", ") + (more > 0 ? ` and ${more} more` : "");
}

/** How a header field changed: "Status: building → built", or "Archetype changed" for long values. */
function historyFieldWords(f) {
  const show = (v) => (v == null || v === "" ? "none" : v);
  if ((f.before || "").length > HISTORY_SHORT || (f.after || "").length > HISTORY_SHORT) return `${f.key} rewritten`;
  return `${f.key}: ${show(f.before)} → ${show(f.after)}`;
}

/** A revision's change with its defaults, and its card changes with moves joined (historyEntries). */
function historyChange(rev) {
  const change = { kind: "none", cards: [], fields: [], lists: [], more: 0, more_by_list: {}, size: null,
    ...(rev.change || {}) };
  const entries = historyEntries(change.cards || []);
  return { change, entries };
}

/** The card changes past the server's cap for a list: its own count, or (from an older server) all of them
 * on the last list that changed. */
function historyExtra(change, list) {
  if (change.more_by_list && Object.keys(change.more_by_list).length) return change.more_by_list[list] || 0;
  return change.more && list === change.lists[change.lists.length - 1] ? change.more : 0;
}

/** One revision in the list: what it did (a button that opens its sheet), who and when, its changes inline, and
 * the changed cards' pictures, which open the card viewer over this revision's cards. */
function historyItem(rev, data, id, version, token) {
  const { change, entries } = historyChange(rev);
  const showSheet = (trigger) => historySheet(rev, data, id, version, token, trigger);
  const open = rev.op === "D" ? el("span", { class: "history-headline", text: historyHeadline(rev) })
    : el("button", { type: "button", class: "history-headline history-open", "aria-haspopup": "dialog",
      text: historyHeadline(rev), onclick: (e) => showSheet(e.currentTarget) });
  const lines = [];
  for (const list of ["target", "owned"]) {
    const cards = entries.filter((c) => c.list === list);
    const extra = historyExtra(change, list);
    if (!cards.length && !extra) continue;
    const label = change.lists.length > 1 || list === "owned" ? `${listName(list)}: ` : "";
    lines.push(el("p", { class: "history-cards" }, label ? el("span", { class: "history-which", text: label }) : null,
      historyListLine(cards, extra)));
  }
  if (change.kind === "created" && change.size) lines.push(el("p", { class: "history-cards", text: historySizes(change.size) }));
  const fields = change.fields.filter((f) => change.kind !== "details" || f.key !== "Title");
  const subject = historySubject(rev);
  const pictures = rev.op === "D" ? null
    : historyPictures(entries, `history-${rev.revision}`, change.more || 0, showSheet);
  return el("article", { class: "history-rev" + (rev.op === "D" ? " history-deleted" : "") + (pictures ? " has-pictures" : "") },
    el("div", { class: "history-text" },
      open,
      el("p", { class: "history-meta" }, el("span", { text: rev.author }), el("time", { datetime: rev.date, text: historyWhen(rev) })),
      lines,
      fields.length ? el("p", { class: "history-fields", text: fields.map(historyFieldWords).join(" · ") }) : null,
      subject ? el("p", { class: "history-subject", text: subject }) : null),
    pictures);
}

/** "100 cards in the planned list · 75 in the play-now list". */
function historySizes(size) {
  const parts = [];
  if (size.target != null) parts.push(`${plural(size.target, "card")} in the ${listName("target", true)}`);
  if (size.owned != null) parts.push(`${size.owned} in the ${listName("owned", true)}`);
  return parts.join(" · ");
}

/** A strip of the changed cards' pictures, each with its badge, opening the card viewer over the strip. When the
 * strip can't show every change, a "+N" tile ends it, saying how many more there are and opening the revision's
 * sheet (onMore), which has them all. In a browser the strip is one row (historyFitStrip: as many of its
 * HISTORY_PICTURES as fit the column); without layout, the CSS's counts (a phone 7, a larger screen
 * HISTORY_PICTURES). past: the changes the server left out. */
function historyPictures(entries, group, past = 0, onMore = null) {
  const pictured = entries.filter((c) => c.card && c.card.img_small);
  if (!pictured.length) return null;
  const total = entries.length + past;
  const wide = pictured.slice(0, HISTORY_PICTURES);
  const phoneCut = total > HISTORY_PHONE_PICTURES;
  const phoneShown = phoneCut ? Math.min(pictured.length, HISTORY_PHONE_PICTURES - 1) : pictured.length;
  const items = wide.map((c) => {
    const words = historyCardWords(c);
    const button = el("button", { type: "button", class: "history-pic", "aria-label": `${words}: show the card`,
      "aria-haspopup": "dialog", onclick: (e) => openCard(c.card, e.currentTarget) },
      el("img", { src: c.card.img_small, alt: "", loading: "lazy", decoding: "async", width: 60, height: 84 }),
      el("span", { class: "history-delta" + (c.delta < 0 && !c.from ? " history-out" : ""), "aria-hidden": "true",
        text: historyBadge(c) }));
    viewerItem(button, c.card, group, `${words} (${listName(c.list)})`);
    return el("li", {}, button);
  });
  const wideMore = total - wide.length;
  const phoneMore = total - phoneShown;
  // The tile is always made when it could open the sheet: the CSS shows it where the strip is cut, and
  // historyFitStrip shows it wherever the row is too narrow for every picture.
  if (onMore) {
    const tile = el("button", { type: "button", class: "history-pic-more", "aria-haspopup": "dialog",
      onclick: (e) => onMore(e.currentTarget) },
      el("span", { class: "history-more-phone" }, `+${phoneMore}`, el("span", { class: "sr-only", text: " more changes" })),
      wideMore > 0 ? el("span", { class: "history-more-wide" }, `+${wideMore}`,
        el("span", { class: "sr-only", text: " more changes" })) : null);
    items.push(el("li", { class: "history-pic-more-item" + (phoneCut ? " on-phone" : "") + (wideMore > 0 ? " on-wide" : "") }, tile));
  }
  const strip = el("ul", { class: "history-pictures" + (phoneCut ? " history-pictures-cut" : ""), "aria-label": "Changed cards",
    "data-total": total }, items);
  if (onMore && typeof ResizeObserver === "function") {
    // Refit in the next frame, not in the observer's callback: hiding tiles changes the strip's height, which
    // inside the callback would end the observer's loop with an error.
    let width = -1, frame = 0;
    new ResizeObserver(() => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!strip.isConnected || strip.clientWidth === width) return;   // only its height changed as it refit
        width = strip.clientWidth;
        historyFitStrip(strip);
      });
    }).observe(strip);
  }
  return strip;
}

/** How a strip of tiles fits one row: width the row's, slot a tile's width, gap between tiles, pictures how many
 * pictures it has, total how many changes. Returns {shown, more}: the pictures that fit, and the "+N" ending the
 * row (0: none, every change is pictured). */
function historyStripFit(width, slot, gap, pictures, total) {
  const fit = Math.max(1, Math.floor((width + gap) / (slot + gap)));
  let shown = Math.min(pictures, fit);
  if (total > shown) shown = Math.min(pictures, fit - 1);       // room for the "+N" tile at the end
  return { shown, more: total - shown };
}

/** Lays a strip out as one row, its tiles at their CSS size: as many pictures as fit, then "+N" for the rest
 * (history.css .history-fit). Run whenever the strip's width changes. */
function historyFitStrip(strip) {
  const tileItem = strip.querySelector(".history-pic-more-item");
  if (!tileItem) return;
  const pictures = [...strip.children].filter((li) => li !== tileItem);
  strip.classList.add("history-fit");
  for (const li of strip.children) li.hidden = false;
  const slot = pictures.length ? pictures[0].getBoundingClientRect().width : 0;
  if (!slot) return;
  const gap = parseFloat(getComputedStyle(strip).columnGap) || 0;
  const { shown, more } = historyStripFit(strip.clientWidth, slot, gap, pictures.length, Number(strip.dataset.total));
  pictures.forEach((li, i) => { li.hidden = i >= shown; });
  tileItem.hidden = more <= 0;
  const tile = tileItem.querySelector("button");
  if (more > 0 && tile) clear(tile).append(`+${more}`, el("span", { class: "sr-only", text: " more changes" }));
}

/** A folded save: who, when and its subject, a button that opens its sheet. */
function historyFolded(rev, data, id, version, token) {
  const subject = historySubject(rev);
  return el("button", { type: "button", class: "history-folded-row", "aria-haspopup": "dialog",
    onclick: (e) => historySheet(rev, data, id, version, token, e.currentTarget) },
    el("span", { class: "history-meta" }, el("span", { text: rev.author }), el("time", { datetime: rev.date, text: historyWhen(rev) })),
    el("span", { class: "history-subject", text: subject || "No message" }));
}

/** Whether the page has the editor a restored list opens in: every width does (the full editor from 600 px,
 * the Quick edit on a phone, as #/edit opens), so this is only false where editor.js isn't loaded. */
function historyHasEditor() {
  return typeof showEditor === "function";
}

/** A revision's sheet: everything it changed (each card a row that opens the viewer), its message, a comparison
 * with the deck now (fetched when asked for), and Open as a draft for someone who may save the deck. */
function historySheet(rev, data, id, version, token, trigger) {
  if (token !== routeToken || (data._historyProfile != null && data._historyProfile !== state.profile?.id)) return null;
  const profile = state.profile?.id;
  const { change, entries } = historyChange(rev);
  const subject = historySubject(rev);
  const body = [
    el("p", { class: "history-meta" }, el("span", { text: rev.author }), el("time", { datetime: rev.date, text: historyWhen(rev) }),
      el("span", { text: `Revision ${rev.revision}${rev.commit ? ` (git ${rev.commit})` : ""}` })),
    subject ? el("p", { class: "history-subject", text: subject }) : null,
  ];
  if (change.kind === "created" && change.size) body.push(el("p", { text: historySizes(change.size) }));
  if (change.kind === "unreadable_before") {
    body.push(el("p", { class: "history-meta", text: "The save before this one can't be read, so its changes can't be shown." }));
  } else if (change.skipped) {
    body.push(el("p", { class: "history-meta",
      text: `Compared with the last save that can be read (${plural(change.skipped, "save")} before it can't be).` }));
  }
  for (const list of ["target", "owned"]) {
    const cards = entries.filter((c) => c.list === list);
    if (!cards.length) continue;
    body.push(el("h3", { text: `${listName(list)}: changes` }),
      el("div", { class: "history-rows" }, cards.map((c) => c.card
        ? cardRow(c.card, { qty: historyBadge(c),
          meta: c.from ? `Moved from the ${historySectionWords(c.from)} to the ${historySectionWords(c.section)}`
            : c.section !== "Deck" ? capitalise(historySectionWords(c.section)) : c.delta ? null : "New printing",
          aside: null, viewerGroup: "history-sheet", caption: `${historyCardWords(c)} (${listName(list)})` })
        : el("p", { class: "history-row-text", text: historyCardWords(c) }))));
  }
  if (change.more) body.push(el("p", { class: "history-meta", text: `And ${change.more} more card changes.` }));
  if (change.fields.length) {
    body.push(el("h3", { text: "Header" }), el("ul", { class: "history-field-list" },
      change.fields.map((f) => el("li", {}, el("strong", { text: f.key }), " ",
        el("span", { text: `${f.before || "none"} → ${f.after || "none"}` })))));
  }
  const compare = el("details", { class: "history-compare" }, el("summary", { text: data.retired ? "View saved list" : "Compare with the deck now" }));
  const answer = el("div", { "aria-live": "polite" });
  compare.append(answer);
  let asked = false;
  compare.addEventListener("toggle", () => {
    if (!compare.open || asked || token !== routeToken || profile !== state.profile?.id || !compare.isConnected) return;
    asked = true;
    historyCompare(answer, rev, id, version, token);
  });
  if (rev.op !== "D") body.push(compare);
  // Restoring is offered only to someone who may save this deck (the server's may_save, as the editor's), and
  // only where the editor opens; anyone else gets neither the action nor a note about it.
  const restorable = !data.retired && data.may_save !== false && rev.op !== "D" && change.kind !== "unreadable"
    && change.size && change.size.target != null;
  const editable = historyHasEditor();
  if (restorable && !editable) {
    body.push(el("p", { class: "history-meta", text: "Restoring a list needs the editor: open this page on a tablet or computer." }));
  }
  const sheet = openDeckRetirementSheet({ title: historyHeadline(rev), wide: true });
  add(sheet.body, body);
  const lists = restorable && editable ? [version, ...["target", "owned"].filter((v) => v !== version)]
    .filter((v) => v === "target" || change.size.owned != null) : [];
  sheetActions(sheet, lists.map((v, i) => ({ text: `Open ${listName(v, true)} as a draft`, kind: i === 0 ? "primary" : "",
    onclick: () => { sheet.close(); location.hash = `${editHref(id, v)}&revision=${rev.revision}`; } })));
  if (trigger) sheet.dialog.addEventListener("close", () => { if (trigger.isConnected) trigger.focus(); });
  return sheet;
}

/** The revision's list against the deck now (GET /api/deck/revision: its lines and the current lists). */
async function historyCompare(box, rev, id, version, token) {
  if (token !== routeToken || !box.isConnected) return;
  const profile = state.profile?.id;
  clear(box).append(loadingBox("Comparing…"));
  try {
    const old = await api(`/api/deck/revision?id=${encodeURIComponent(id)}&version=${version}&revision=${rev.revision}`);
    if (token !== routeToken || profile !== state.profile?.id || !box.isConnected) return;
    if (!old.current) {
      add(clear(box), [el("p", { class: "history-meta", text: `This retired deck's saved ${listName(version, true)}. Restore the deck from History before opening a historical list as an editable draft.` }),
        warningsBox(old.warnings, "Revision warnings"),
        Object.entries(old.sections || {}).map(([name, lines]) => el("section", {}, el("h4", { text: name }),
          el("ul", {}, lines.map(line => el("li", {}, line.card ? cardRow(line.card, { qty: line.qty, meta: null, aside: null })
            : `${line.qty} × ${line.name}`)))))]);
      return;
    }
    const changes = listChanges(old.current.lists[version] || {}, old.sections);
    add(clear(box), [
      el("p", { class: "history-meta", text: `What this revision's ${listName(version, true)} has, against the deck now.` }),
      warningsBox(old.warnings, "Revision warnings"),
      changes.length ? el("ul", { class: "history-field-list" }, changes.map((c) => el("li", { text: changeWords(c) })))
        : el("p", { text: "The cards match the deck now." })]);
  } catch (e) {
    if (token === routeToken && profile === state.profile?.id && box.isConnected) clear(box).append(errorBox("The revision couldn't be loaded", e, null));
  }
}

function showRevisionEditor(params, token) {
  let id = addressDeckId(params.get("id"));
  const version = params.get("v") === "owned" ? "owned" : "target";
  const revision = params.get("revision"), profile = state.profile?.id;
  load(`/api/deck/revision?id=${encodeURIComponent(id)}&version=${version}&revision=${encodeURIComponent(revision)}`, token, data => {
    if (profile !== state.profile?.id) return;
    id = data.id || data.current?.id || id;
    canonicalDeckAddress(id);
    if (!data.current) {
      add($("#main"), [crumb(deckHistoryHref(id, version), "History"), el("h1", { text: "This deck is retired" }),
        el("p", { text: "Its saved list is still readable in History. Restore the deck there before opening a historical list as a draft." }),
        el("a", { class: "btn btn-primary", href: deckHistoryHref(id, version), text: "View retained history" })]);
      return;
    }
    if (!data.current.editable) {
      add($("#main"), [crumb(`#/history?id=${encodeURIComponent(id)}&v=${version}`, "History"),
        el("h1", { text: "This deck cannot be edited" }), el("p", { text: data.current.why_not })]);
      return;
    }
    const key = draftKey({mode: "edit", profile: state.profile.id, id, version});
    const open = () => {
      if (token !== routeToken || profile !== state.profile?.id) return;
      history.replaceState(history.state, "", editHref(id, version));
      clear($("#main"));
      startEditor({mode: "edit", view: data.current, version, restoreDraft: false});
      editor.lists = copyList(data.sections);
      editor.starting = !editor.hasFileList;
      syncSections();
      editor.dirty = isDirty();
      drawEditor();
      saveDraft(editor);
      scheduleCheck(0);
      toast("Historical list opened as a draft. Review the changes before saving.");
    };
    if (local.get(key)) {
      add($("#main"), [crumb(`#/history?id=${encodeURIComponent(id)}&v=${version}`, "History"),
        el("h1", { text: "You already have a draft" }),
        el("p", { text: "Opening this revision replaces the unsaved draft for this list on this device." }),
        el("div", { class: "actions" },
          el("button", { class: "btn btn-primary", type: "button", text: "Replace draft with this revision", onclick: open }),
          el("a", { class: "btn", href: editHref(id, version), text: "Keep my existing draft" }))]);
    } else open();
  });
}
