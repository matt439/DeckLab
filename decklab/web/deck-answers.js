/* What a Commander deck can answer (E9-S35; lib/stats/answers.py): the Stats tab's panel counting what the
 * list's interaction can hit (creatures, artifacts, enchantments, planeswalkers, any nonland permanent,
 * graveyards, spells on the stack), each split into targeted and mass and by speed, from Scryfall's oracle
 * tags. A kind whose tag the card data lacks says "Not checked", never 0; with no tag file the panel says why.
 * 60-card decks get none (the server sends stats.answers as null for them). */
"use strict";

/** The kind's count for a table cell: "Not checked" when its tag couldn't be read. */
function answerCell(kind, group) {
  if (!kind.checked) return "Not checked";
  if (group === "all") return num(kind.count);
  const found = kind[group[0]] && kind[group[0]][group[1]];
  if (group[0] === "modes" && !kind.split_checked) return "Not split";
  return found ? num(found.count) : "—";
}

/** One kind folded open: its cards by targeted or mass, then by speed. */
function answerKindDetails(kind, found) {
  const parts = [];
  const groups = (labels, key) => labels.forEach((item) => {
    const group = kind[key] && kind[key][item[key === "modes" ? "mode" : "speed"]];
    if (!group || !group.count) return;
    parts.push(el("h5", { text: `${item.label}: ${num(group.count)}` }), cardNames(group.cards, "answers"));
  });
  groups(found.modes || [], "modes");
  if (kind.split_reason) parts.push(el("p", { class: "sub", text: kind.split_reason }));
  groups(found.speeds || [], "speeds");
  return el("details", { class: "more answer-kind" },
    el("summary", { text: `${kind.label}: ${num(kind.count)}` }), parts);
}

function answersPanel(found, data = null) {
  if (!found) return null;
  const panel = el("section", { class: "panel answers", "aria-labelledby": "h-answers" },
    el("h3", { id: "h-answers", text: "What it can answer" }));
  if (!found.checked) {
    panel.append(el("p", { class: "note note-warn", text: found.reason || "Scryfall's oracle tags couldn't be read, so what the deck can answer wasn't worked out." }));
    return panel;
  }
  panel.append(el("p", { class: "sub", text: "Cards that can deal with each kind of threat a pod of strangers' " +
    "decks may lean on. A card can count for several kinds (one that removes any permanent counts for each)." }));
  const kinds = found.kinds || [];
  if ((found.gaps || []).length) {
    panel.append(el("p", { class: "note note-warn answers-gaps", text: `No answer to: ${found.gaps.join(", ")}.` }));
  }
  const speedLabel = (key) => ((found.speeds || []).find((s) => s.speed === key) || { label: key }).label;
  const heads = ["Kind", "Cards", "Targeted", "Mass", speedLabel("instant"), speedLabel("sorcery"), speedLabel("permanent")];
  const columns = ["all", ["modes", "targeted"], ["modes", "mass"], ["speeds", "instant"], ["speeds", "sorcery"], ["speeds", "permanent"]];
  panel.append(el("div", { class: "table-wrap" }, el("table", { class: "data answers-table" },
    el("thead", {}, el("tr", {}, heads.map((text, i) => el("th", { scope: "col", class: i ? "num" : null, text })))),
    el("tbody", {}, kinds.map((kind) => el("tr", { class: kind.checked ? null : "answers-unchecked" },
      el("th", { scope: "row", text: kind.label }),
      columns.map((column) => el("td", { class: "num", text: answerCell(kind, column) }))))))));
  for (const kind of kinds) {
    if (!kind.checked) panel.append(el("p", { class: "sub", text: `${kind.label}: not checked. ${kind.reason || ""}`.trim() }));
    else if (kind.count) panel.append(answerKindDetails(kind, found));
  }
  const other = found.other;
  if (other && other.checked && other.count) {
    panel.append(el("details", { class: "more answer-kind" },
      el("summary", { text: `Other removal: ${num(other.count)}` }),
      el("p", { class: "sub", text: "Removal that hits none of the kinds above: lands, equipment, or a target the tags don't name." }),
      cardNames(other.cards, "answers")));
  }
  const dated = found.tags_date ? `Scryfall's oracle tags of ${found.tags_date}` : "Scryfall's oracle tags (date unknown)";
  panel.append(explain("How is this worked out?",
    `From ${dated}: Tagger's removal tags by what they hit, its graveyard-hate tags and its counterspell tags ` +
      `(the tag names were checked against the tag file on ${found.tags_checked}).`,
    "Mass is a board wipe, a one-sided wipe or an overload, a graveyard exiled or sealed whole, or a counter that " +
      "stops every such spell; targeted is spot removal or removal of a few. A card both can be counts in both; " +
      "\"Not split\" means the tags don't say.",
    "Speed is read from the card: instants and cards with flash are instant speed, sorceries sorcery speed. An " +
      "ability or an enters trigger is \"On a permanent\": its timing isn't read.",
    data && data.owned ? "To fill a gap from the pool, Free cards by role (under Card types and roles) lists the " +
      "removal and counterspells free in the collection." : null,
    "The counts only inform: they don't change the bracket."));
  return panel;
}
