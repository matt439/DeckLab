/* The filing rules shared by the Collection card list and Build decks. */
"use strict";

const STORAGE_COLOURS = ["White", "Blue", "Black", "Red", "Green", "Multicolour", "Colourless"];
const STORAGE_NUMBERS = new Intl.Collator(LOCALE, { numeric: true });

function storageFilingGuide() {
  return el("details", { class: "storage-filing-guide" },
    el("summary", { text: "Colour order and where artifacts go" }),
    el("p", { text: `Pick the card group first. Within Creatures, Spells and Lands, the colour dividers go ${STORAGE_COLOURS.join(" → ")}.` }),
    el("ul", {},
      el("li", { text: "Artifact lands go in Lands. Artifact creatures go after Colourless in Creatures, and all remaining artifacts go after Colourless in Spells. Coloured artifacts use the same dividers." }),
      el("li", { text: "Creatures and spells use the front face’s colours. Lands use the colours of mana they produce, falling back to colour identity when no coloured mana is listed." }),
      el("li", { text: "The Token cards section includes creature tokens." })),
    el("p", { text: "Within a divider, sort by mana value, then card name. A recorded storage section takes precedence over the card group." }));
}

/** The front face's type and actual colours determine its divider. Lands use the mana they produce. */
function storageCardGroup(card) {
  const face = card?.faces?.[0] || card;
  const type = (face?.type_line || card?.type_line || "").split(" // ")[0].split(/\s[—–-]\s/)[0];
  if (!type) return [23, "Other cards"];
  const coloured = values => (values || []).filter(c => "WUBRG".includes(c));
  const rank = colours => colours.length > 1 ? 5 : colours.length ? "WUBRG".indexOf(colours[0]) : 6;
  if (/\bLand\b/.test(type)) {
    const produces = coloured(card.produced_mana);
    const colour = rank(produces.length ? produces : coloured(card.color_identity));
    return [16 + colour, `Lands · ${STORAGE_COLOURS[colour]}`];
  }
  const creature = /\bCreature\b/.test(type);
  if (/\bArtifact\b/.test(type)) return creature ? [7, "Artifact creatures"] : [15, "Artifacts"];
  const colour = rank(coloured(face.colors ?? card.colors));
  return [colour + (creature ? 0 : 8), `${creature ? "Creatures" : "Spells"} · ${STORAGE_COLOURS[colour]}`];
}

function storageGroupKind(rank) {
  return rank < 8 ? "creatures" : rank < 16 ? "spells" : rank < 23 ? "lands" : null;
}

/** Sections without a match follow the named sections in the user's order. */
function storageSectionRank(sectionOrder, section) {
  const index = sectionOrder?.indexOf(section) ?? -1;
  return index < 0 ? Infinity : index;
}

function storageManaValue(card) {
  return Number.isFinite(card?.cmc) ? card.cmc : Infinity;
}

function storageCollectorCompare(a, b) {
  return STORAGE_NUMBERS.compare(String(a ?? ""), String(b ?? ""));
}

/** An older or unavailable location/setup answer cannot establish a physical order. */
function colHasStorageOrder(cv) {
  const setup = cv.storageSetup;
  if (!cv.locations?.ready || cv.locations.error || !setup?.placements || !setup.containers.length) return false;
  const [only] = setup.containers;
  if (setup.containers.length > 1 || only.sections.length || only.order !== "none") return true;
  // Even a single unordered box can have cards filed elsewhere.
  return Object.values(setup.placements).some(([id]) => id !== setup.default);
}

/** Sort displayed rows using the exact printing and finish's location. Decorate once per row so
 * each comparison can use its known container, section and divider without classifying the card again. */
function colStorageSortedRows(cv, rows) {
  const setup = cv.storageSetup;
  const containers = new Map(setup.containers.map((c, index) => [c.id, { ...c, index,
    groupSections: Object.fromEntries(Object.entries(c.holds).map(([section, group]) => [group, section])) }]));
  const entries = rows.map(row => {
    const key = colKey(row);
    const location = colLocationOf(cv, row);
    const [id, recordedSection] = location
      ? (Object.hasOwn(setup.placements, location) ? setup.placements[location] : []) : [setup.default];
    const container = containers.get(id);
    let group = 0, value = 0, section = recordedSection;
    if (container?.order === "colour-type") {
      const card = cv.pictures[key];
      [group] = storageCardGroup(card);
      value = storageManaValue(card);
      section = section ?? container.groupSections[storageGroupKind(group)];
    }
    return { row, container: container?.index ?? Infinity, section: storageSectionRank(container?.sections, section),
      order: container?.order, group, value };
  });
  entries.sort((a, b) => {
    const physical = a.container - b.container || a.section - b.section || a.group - b.group || a.value - b.value;
    if (physical) return physical;
    if (a.order === "set") {
      if (Boolean(a.row.set) !== Boolean(b.row.set)) return a.row.set ? -1 : 1;
      const printing = String(a.row.set || "").localeCompare(String(b.row.set || ""))
        || storageCollectorCompare(a.row.collector_number, b.row.collector_number);
      if (printing) return printing;
    }
    return a.row.name.localeCompare(b.row.name);
  });
  return entries.map(entry => entry.row);
}
