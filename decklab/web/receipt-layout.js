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
  view.guidance.append(view.guidanceBody);
  view.frame = el("div", { class: "rcpt-layout-frame" }, view.board, view.guidance);
  view.root.append(view.frame);
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
    return el("li", {}, `${item.quantity} \u00d7 ${item.name}: `, el("a", { href: deckHref(deck.id), text: deck.title }),
      sleeves ? el("span", { class: "sub", text: ` \u00b7 sleeves: ${sleeves}` })
        : deck.status === "building" ? el("span", { class: "rcpt-guidance-building", text: " \u00b7 Building: keep them with its cards" }) : null);
  });
}

/** Repaint only presentation; the original blocker predicates and preview/apply requests remain authoritative. */
function rcptSyncLayout(view, progress) {
  if (!receiptActive(view) || view.done) return;
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
