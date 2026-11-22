/* Saved alternatives remain outside both decklists and packing until promoted in the editor. */
"use strict";

function consideringEditHref(data, name = null) {
  const href = `${editHref(data.summary.id, data.version)}&focus=considering`;
  return name === null ? href : `${href}&consider=${encodeURIComponent(name)}`;
}

/** Show physical and incoming copies separately, for a viewer who can read the collection. */
function consideringFreeWords(line) {
  if (!("free" in line)) return null;
  if (line.free === null) return "Basic land";
  const freeNow = Math.max(0, line.free - (line.on_the_way || 0));
  const choices = [freeNow >= line.qty ? "Free now" : `${num(freeNow)} of ${num(line.qty)} free now`];
  if (line.on_the_way) choices.push(`${num(line.on_the_way)} on the way`);
  return choices.join(" · ");
}

/** The Cards tab's saved Considering list, with the usual draft editor for changes. */
function deckConsideringSection(data) {
  const info = data.considering, s = data.summary;
  if (!info || !Array.isArray(info.lines)) return null;
  const editable = !s.read_only && canEditDeck(s);
  if (!info.lines.length && !editable) return null;
  const section = el("section", { class: "deck-section deck-considering", id: "sec-considering",
    "aria-labelledby": "h-considering" }, el("h2", { id: "h-considering", text: "Considering" }));
  const edit = editable ? el("a", { class: "btn btn-quiet", href: consideringEditHref(data, info.lines.length ? null : ""),
    text: info.lines.length ? "Edit Considering" : "Add a card to consider…" }) : null;
  if (!info.lines.length) {
    section.append(emptyBox("No cards being considered.", edit));
    return section;
  }
  const token = routeToken, profile = state.profile?.id;
  if (typeof smallSwapSuggestionsOffered === "function" && smallSwapSuggestionsOffered(data)) {
    const suggest = el("button", { type: "button", class: "btn btn-quiet", text: "Suggest a small swap…",
      onclick: () => { if (token === routeToken && profile === state.profile?.id && suggest.isConnected) openSmallSwapSuggestions(data); } });
    section.append(el("div", { class: "actions" }, suggest, edit));
  } else if (edit) section.append(edit);
  section.append(el("p", { class: "sub", text: "Saved ideas for later. The editor can move them into the planned list or sideboard for review." }),
    el("div", {}, info.lines.map(line => {
      const availability = consideringFreeWords(line);
      return cardRow(line.card, { qty: line.qty, name: line.name, meta: availability || undefined,
        unknownMeta: availability || "Card details unavailable", viewerGroup: "deck-considering", caption: `${line.qty} x ${line.name}` });
    })));
  return section;
}
