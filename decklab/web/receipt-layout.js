/* Receive delivery's header and loaded-data guidance. Checking, preview and recording stay in their existing modules. */
"use strict";

/** The order's sub-page head; notes retain their existing More/Less control. */
function rcptHead(data, title, view = null) {
  const notes = data.notes ? el("p", { class: "rcpt-notes", text: data.notes }) : null;
  const more = notes && data.notes.length > 140 ? el("button", { type: "button", class: "btn btn-quiet btn-inline rcpt-more",
    "aria-expanded": "false", text: "More", onclick: (e) => {
      const open = notes.classList.contains("is-open");
      notes.classList.toggle("is-open", !open);
      e.currentTarget.setAttribute("aria-expanded", String(!open));
      e.currentTarget.textContent = open ? "More" : "Less";
    } }) : null;
  const head = pageHead({ crumb: ["#/shopping", routeFor("shopping").label], title: title || routeH1("receipt"),
    description: data.seller || "Seller not recorded" });
  const progress = view ? el("div", { class: "rcpt-head-progress" }) : null;
  if (view) { view.headProgress = progress; rcptHeadProgress(view); }
  return [el("header", { class: "rcpt-page-head" }, head[0],
    el("div", { class: "rcpt-head-grid" }, el("div", { class: "rcpt-head-details" }, head[1],
      el("p", { class: "rcpt-order-meta" }, el("span", { text: `Order ${data.order || "not recorded"}` }),
        data.ordered_on ? el("time", { datetime: data.ordered_on, text: `Ordered ${rcptDate(data.ordered_on)}` })
          : el("span", { text: "Order date not recorded" }))), progress)), notes, more];
}

/** Copy counts use the same working-state unit as rcptProgress; whole products stay separate. */
function rcptHeadProgress(view, progress = null) {
  if (!view.headProgress) return;
  const pending = (view.data.components || []).filter((comp) => comp.status === "pending");
  if (view.readOnly) {
    const copies = (view.data.components || []).filter((comp) => comp.kind !== "product")
      .reduce((n, comp) => n + (comp.rows || []).reduce((sum, row) => sum + (parseInt(row.quantity, 10) || 0), 0), 0);
    const products = (view.data.components || []).filter((comp) => comp.kind === "product").length;
    add(clear(view.headProgress), [el("span", { class: "rcpt-head-count", text: `${plural(copies, "card copy", "card copies")} in this order` }),
      products ? el("span", { class: "sub", text: plural(products, "whole product") }) : null]);
    return;
  }
  const p = progress || rcptProgress(view), selected = view.comps.filter((comp) => comp.selected);
  const products = selected.filter((comp) => comp.kind === "product").length;
  add(clear(view.headProgress), [el("span", { class: "rcpt-head-count", text: !pending.length ? "No pending parts"
    : !selected.length ? "Select the parts that arrived" : p.copies ? `${p.ticked} of ${p.copies} card copies checked`
      : "Whole products are checked separately" }),
    p.copies ? ownedBar(p.ticked, 0, p.copies) : null,
    products ? el("span", { class: "sub", text: `${plural(products, "whole product")} selected separately` }) : null]);
}

/** Mount one board plus a guidance pane; the existing Record bar stays its only action surface. */
function rcptBuildLayout(view) {
  view.guidance = el("aside", { class: "panel rcpt-guidance", tabindex: "0", "aria-labelledby": "rcpt-guidance-title" },
    el("h2", { id: "rcpt-guidance-title", text: "Delivery guidance" }));
  view.guidanceBody = el("div", { class: "rcpt-guidance-body" });
  view.selectedFacts = el("div", { class: "rcpt-selected-facts", id: "rcpt-selected-facts" });
  view.selectedInspect = el("button", { type: "button", class: "btn", text: "Edit details…",
    "aria-haspopup": "dialog", "aria-describedby": "rcpt-selected-facts", onclick: () => {
      if (!receiptEditable(view)) return;
      const current = rcptCurrentRow(view, view.selectedRow);
      if (current) rcptGoTo(view, current);
    } });
  view.selectedSummary = el("section", { class: "rcpt-selected-summary", "aria-labelledby": "rcpt-selected-title" },
    el("h3", { id: "rcpt-selected-title", text: "Selected row" }), view.selectedFacts, view.selectedInspect);
  view.guidance.append(view.selectedSummary, view.guidanceBody);
  view.frame = el("div", { class: "rcpt-layout-frame" }, view.board, view.guidance);
  view.root.append(view.frame);
}

/** Runtime keys distinguish split parts. An original payload index cannot identify the working row. */
function rcptCurrentRow(view, selected) {
  if (!selected || !receiptActive(view) || view.done || view.readOnly || view.reloadRequired || !mayDo("receipts")) return null;
  const comp = view.comps.find(c => c.c.id === selected.comp && c.selected && ["cards", "tokens"].includes(c.kind));
  const row = comp?.rows.find(r => r.key === selected.key);
  return row ? { comp, row } : null;
}

/** Inspection follows the current working part; it never checks a row or creates a receipt draft. */
function rcptSelectRow(view, comp, row) {
  const selected = { comp: comp.c.id, key: row.key };
  const current = rcptCurrentRow(view, selected);
  if (!current || current.comp !== comp || current.row !== row) return;
  view.selectedRow = selected;
  rcptSyncSelected(view);
}

function rcptSelectedValue(code, words, unknown) {
  return code ? el("span", {}, el("span", { class: "rcpt-selected-code", text: code }),
    el("span", { class: "rcpt-selected-words", text: words || code }))
    : el("span", {}, el("span", { "aria-hidden": "true", text: "—" }), el("span", { class: "sr-only", text: unknown }));
}

/** Reuse loaded facts and one retained action; the inspector remains the only row editor/viewer entry. */
function rcptSyncSelected(view) {
  if (!view.selectedSummary) return;
  const allowed = receiptActive(view) && !view.done && !view.readOnly && !view.reloadRequired && mayDo("receipts");
  let current = allowed ? rcptCurrentRow(view, view.selectedRow) : null;
  if (allowed && !current) {
    // A first visible row is context only, not a claim that it arrived or was inspected.
    for (const comp of view.comps) {
      if (!comp.selected || !["cards", "tokens"].includes(comp.kind)) continue;
      const row = comp.rows.find(r => r.tile && !r.tile.hidden);
      if (row) { current = { comp, row }; break; }
    }
    view.selectedRow = current ? { comp: current.comp.c.id, key: current.row.key } : null;
  }
  if (!allowed) view.selectedRow = null;
  for (const comp of view.comps) for (const row of comp.rows) {
    if (current?.comp === comp && current.row === row) row.open?.setAttribute("aria-current", "true");
    else row.open?.removeAttribute("aria-current");
  }
  view.selectedSummary.hidden = !allowed;
  view.selectedInspect.hidden = !current;
  view.selectedInspect.disabled = !receiptEditable(view);
  const facts = clear(view.selectedFacts);
  if (!allowed) return;
  if (!current) {
    facts.append(el("p", { class: "sub", text: "Choose an arrived card or token part, then inspect a visible row. Whole products keep their own choices." }));
    return;
  }
  const { comp, row } = current, v = row.values;
  const name = comp.kind === "tokens" ? [v.front, v.back].filter(Boolean).join(" // ") : v.name;
  const parts = comp.rows.filter(r => r.orig === row.orig), hidden = Boolean(row.tile?.hidden);
  facts.append(el("strong", { class: "rcpt-selected-name", text: name }),
    el("p", { class: "sub", text: `${plural(rcptQty(row), comp.kind === "tokens" ? "token card copy" : "card copy", comp.kind === "tokens" ? "token card copies" : "card copies")} · ${row.ticked ? "Checked" : "Not checked"}` }),
    el("p", { class: "rcpt-mono", text: rcptMeta(comp, row) }));
  if (comp.kind === "cards") {
    const conditions = { NM: "Near mint", LP: "Lightly played", MP: "Moderately played", HP: "Heavily played", DMG: "Damaged" };
    facts.append(el("dl", { class: "rcpt-selected-details" }, el("dt", { text: "Condition" }),
      el("dd", {}, rcptSelectedValue(v.condition, conditions[v.condition], "Condition not recorded")),
      el("dt", { text: "Language" }), el("dd", {}, rcptSelectedValue(v.language, RCPT_LANGUAGE_WORDS[v.language], "Language not recorded"))));
  } else facts.append(el("p", { class: "sub", text: rcptBackOpen(row) ? "Reverse not confirmed" : v.back ? "Reverse recorded" : "Single-sided verified" }));
  if (parts.length > 1) facts.append(el("p", { class: "sub", text: `Part ${parts.indexOf(row) + 1} of ${parts.length}${row.ticked ? "" : "; still pending"}.` }));
  if (v.notes) facts.append(el("p", { class: "sub", text: `Notes: ${v.notes}` }));
  facts.append(el("p", { class: "sub", text: hidden ? "Hidden by the current view. Editing shows this row first." : "Details from this delivery; inspect to confirm what arrived." }));
  view.selectedInspect.textContent = hidden ? "Show row and edit details…" : "Edit details…";
  view.selectedInspect.setAttribute("aria-label", `${hidden ? "Show row and edit" : "Edit"} details for ${name}`);
}

/** Classify only the supplied copies, from loaded metadata; shared before and after recording. */
function rcptDestinationAdvice(view, received) {
  const out = [];
  for (const comp of received) {
    if (comp.kind === "product") {
      out.push({ kind: "product", comp, title: rcptTitle(comp.c, view.data) });
      continue;
    }
    const checked = comp.rows;
    if (!checked.length) continue;
    if (comp.kind === "tokens") {
      out.push({ kind: "tokens", quantity: checked.reduce((n, row) => n + rcptQty(row), 0) });
      continue;
    }
    const names = new Map();
    for (const row of checked) {
      if (!names.has(row.values.name)) names.set(row.values.name, []);
      names.get(row.values.name).push(row);
    }
    for (const [name, rows] of names) {
      let left = rows.reduce((n, row) => n + rcptQty(row), 0);
      if (rcptIsBasic(name)) {
        out.push({ kind: "unknown", name, quantity: left, why: "basic" });
        continue;
      }
      const candidates = new Map();
      const known = Array.isArray(comp.decks) && rows.every((row) => Array.isArray(comp.decks[row.orig])
        && comp.decks[row.orig].every((deck) => deck && typeof deck.id === "string" && typeof deck.title === "string"
          && Number.isSafeInteger(deck.waiting) && deck.waiting >= 0));
      if (!known) {
        out.push({ kind: "unknown", name, quantity: left, why: "unavailable" });
        continue;
      }
      // Split rows repeat the source row's waiting count: cap by checked copies, never add those hints twice.
      for (const row of rows) for (const deck of comp.decks[row.orig]) {
        const previous = candidates.get(deck.id);
        if (!previous || previous.waiting < deck.waiting) candidates.set(deck.id, deck);
      }
      const rank = (deck) => deck.status === "built" ? 0 : deck.status === "building" ? 1 : 2;
      const decks = [...candidates.values()].sort((a, b) => rank(a) - rank(b) || a.title.localeCompare(b.title));
      for (const deck of decks) {
        const give = Math.min(left, deck.waiting);
        if (!give) continue;
        left -= give;
        out.push({ kind: "deck", name, quantity: give, deck });
      }
      if (left) out.push({ kind: "storage", name, quantity: left });
    }
  }
  return out;
}

/** Optional canonical Planned/library decoration; malformed/absent data never becomes colourless. */
function rcptDeckSwatch(deck) {
  const colors = deck?.colors;
  if (!Array.isArray(colors) || colors.length > 5 || new Set(colors).size !== colors.length
      || !Array.from(colors).every((color) => typeof color === "string" && /^[WUBRG]$/.test(color))) return null;
  return deckColourPieces(colors).swatch();
}

function rcptDeckLink(deck) {
  return el("a", { class: "rcpt-deck-link", href: deckHref(deck.id, "target") }, rcptDeckSwatch(deck),
    el("span", { class: "rcpt-deck-title", text: deck.title }));
}

/** Advice from already-loaded deck needs, never a physical allocation or a receipt confirmation. */
function rcptGuidanceDestinations(view) {
  return rcptDestinationAdvice(view, rcptReceived(view)).map((item) => {
    const comp = item.comp;
    if (item.kind === "product") return el("li", { text: `${item.title}: ${comp.intact === "yes"
      ? "keep together as its own deck(s)." : comp.intact === "no" ? "break up into storage."
        : "choose whether to keep it together or break it up."}` });
    if (item.kind === "tokens") return el("li", { text: `${plural(item.quantity, "token card copy", "token card copies")}: with your tokens.` });
    if (item.kind === "unknown") return el("li", { class: "rcpt-destination-unknown", text: `${item.quantity} \u00d7 ${item.name}: ${item.why === "basic"
      ? "basic-land deck destinations are not tracked." : "destination not known from this delivery's data."}` });
    if (item.kind === "storage") return el("li", { text: `${item.quantity} \u00d7 ${item.name}: storage; no deck is waiting in the loaded delivery data.` });
    const deck = item.deck, sleeves = view.data.kits?.[deck.id]?.sleeves;
    return el("li", {}, `${item.quantity} \u00d7 ${item.name}: `, rcptDeckLink(deck),
      sleeves ? el("span", { class: "sub", text: ` \u00b7 sleeves: ${sleeves}` })
        : deck.status === "building" ? el("span", { class: "rcpt-guidance-building", text: " \u00b7 Building: keep them with its cards" }) : null);
  });
}

/** Repaint only presentation; the original blocker predicates and preview/apply requests remain authoritative. */
function rcptSyncLayout(view, progress) {
  if (!receiptActive(view) || view.done) return;
  rcptSyncSelected(view);
  rcptHeadProgress(view, progress);
  view.measureBar?.();
  if (!view.guidanceBody) return;
  if (view.reloadRequired) {
    clear(view.guidanceBody).append(el("p", { class: "note note-warn", text: "The delivery changed. Reload it before using destination guidance." }));
    return;
  }
  const blockers = rcptClientBlockers(view), destinations = rcptGuidanceDestinations(view);
  add(clear(view.guidanceBody), [el("section", { class: "rcpt-guidance-checks" }, el("h3", { text: "To check" }),
    blockers.length ? el("ul", {}, blockers.map((item) => el("li", {}, el("button", { type: "button", class: "rcpt-blocker",
      text: item.text, onclick: () => { if (receiptEditable(view)) rcptGoTo(view, item); } }))))
      : el("p", { class: "sub", text: view.comps.some((comp) => comp.selected)
        ? "Ready for server preview." : "Select the parts that arrived." }),
    progress.blanks ? el("p", { class: "sub", text: `${plural(progress.blanks, "checked card copy", "checked card copies")} ${progress.blanks === 1 ? "still lacks" : "still lack"} condition or language; the preview states what stays blank.` }) : null),
    el("section", { class: "rcpt-guidance-where" }, el("h3", { text: "Where these go" }),
      destinations.length ? el("ul", { class: "rcpt-guidance-destinations" }, destinations)
        : el("p", { class: "sub", text: "Tick the cards that arrived to see guidance for those copies." })),
    el("p", { class: "sub rcpt-guidance-note", text: "Guidance uses the loaded deck needs. Preview still checks the exact changes; nothing is recorded before confirmation." })]);
}

/** The Record bar can grow with warnings or wrapping; keep the lab pane above its actual height. */
function rcptWatchBar(view) {
  if (!view.bar?.node || view.barObserver) return;
  const measure = () => {
    if (!receiptActive(view) || view.done) { view.barObserver?.disconnect(); return; }
    const height = Math.ceil(view.bar.node.getBoundingClientRect().height);
    if (Number.isFinite(height) && height > 0) view.root.style.setProperty("--rcpt-bar-height", `${height}px`);
  };
  view.measureBar = measure;
  if (typeof window.ResizeObserver === "function") {
    view.barObserver = new window.ResizeObserver(measure);
    view.barObserver.observe(view.bar.node);
  }
  measure();
}
