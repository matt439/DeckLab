/* The Tokens page (#/tokens): the physical token and reminder cards (a space's token cards), which deck needs
 * each, the kinds of token the decks need and nobody owns, and the token cards on the way. Works on
 * phones as well as desktops. A double-sided card counts once and shows one face at a time.
 *
 * Also the pieces other pages use (deck.js, library.js and assembly.js):
 *     tokenThumb(url, px, pt)         a token's small picture from Deck Lab's /img/ route, with a fallback
 *     tokenStateChip(state, words)    a need's state as a chip: "Have it: 8 cards", "None owned", ...
 *     tokenNeedList(needs, faces)     a deck's needs as a list (lib/tokens deck_tokens's "needs")
 *     tokFacesUsed(needs)             the faces of each token card a deck uses, for tokSides
 *     tokSides(card, faces)           "Zombie side only, can be sleeved" or "both sides used"
 *
 * Every write goes to /api/tokens/... (lib/api/tokens.py), which checks the list's sha256. The rows have
 * no ids, so a row is named by its ten values as the page loaded them ("base"): a list changed by
 * someone else meanwhile answers 409 with the latest list, and the sheet offers to put the changes back
 * on top of it. Writes stay tied to the person and page that started them. The page never merges rows
 * by itself: adding a card that's already listed asks first. Deck token needs come from Scryfall's links
 * between cards and tokens, so they're approximate, and Deck Lab never says how many a game needs.
 *
 * Each space (lib/spaces.py) has its own tokens: #/tokens?space=<id> shows one (the visitor's own by
 * default), every GET and write names it (?space= and "space"; home's leaves it out), and the add, edit
 * and remove controls show only where the visitor may change the tokens (canEditSpace). */
"use strict";

const TOK_FIELDS = ["front", "back", "set", "front_collector_number", "back_collector_number", "finish",
  "quantity", "front_details", "back_details", "notes"];
const TOK_FIELD_WORDS = { front: "Front", back: "Back", set: "Set", front_collector_number: "Front number",
  back_collector_number: "Back number", finish: "Finish", quantity: "Quantity", front_details: "Front details",
  back_details: "Back details", notes: "Notes" };
const TOK_LIMITS = { front: 80, back: 80, set: 8, front_collector_number: 16, back_collector_number: 16,
  front_details: 300, back_details: 300, notes: 500 };      // the server's limits
// Short words, so the four fit one row of a phone; "To check" gains its count when there are any.
const TOK_FILTERS = [["all", "All"], ["used", "In decks"], ["check", "To check"], ["unused", "Not used"]];
const TOK_SINGLE = "single-sided verified";
// A need's state: the chip's kind and its short words (when the server's words aren't to hand).
const TOK_STATES = {
  ready: ["good", "Have it"], check: ["info", "Details to check"], differs: ["warn", "Different token"],
  incoming: ["info", "On the way"], none: ["warn", "None owned"], in_use: ["warn", "Packed in other decks"],
};


// ------------------------------------------------------------ shared pieces

/** A token's picture, px wide (the whole card shown), from Deck Lab's own /img/ route; anything else, or a
 * picture that won't load, shows the token placeholder (4.10): a disc with its P/T ("2/2") when known, else
 * a target glyph. The name is always beside it as text. */
function tokenThumb(url, px, pt = "") {
  const words = String(pt || "").trim();
  const fallback = el("span", { class: words ? "tok-thumb-fallback" : "tok-thumb-fallback tok-thumb-target",
    "aria-hidden": "true", text: words || null });
  const box = el("span", { class: "tok-thumb", style: `--tok-thumb: ${px}px` }, fallback);
  if (typeof url === "string" && url.startsWith("/img/")) {
    const img = el("img", { src: url, alt: "", loading: "lazy", decoding: "async", width: px,
      height: Math.round(px * 680 / 488), onerror: () => { img.hidden = true; fallback.hidden = false; } });
    fallback.hidden = true;
    box.append(img);
  }
  return box;
}

/** A need's state as a chip: the server's words when given, else short ones ("None owned"). */
function tokenStateChip(state, words) {
  const [kind, short] = TOK_STATES[state] || ["plain", state || "Unknown"];
  return status(kind, words || short);
}

/** "Zombie / Zombie Knight" or, for a single-sided card, "The Monarch". */
function tokLabel(row) { return row.back ? `${row.front} / ${row.back}` : row.front; }

/** The key tokFacesUsed files a token card under: its row and faces (a row index alone could name another
 * card once the list has changed). */
function tokFacesKey(card) { return JSON.stringify([card.row, tokFold(card.front), tokFold(card.back || "")]); }

/** Map of tokFacesKey -> Map(folded face -> face): the faces of each token card a deck uses, from its
 * deck_tokens needs: the cards it grabs for a need it has, and the stand-in it uses for one that differs.
 * A card whose two faces both show up there is needed both ways up; one used for a single face (Rabbit /
 * Rabbit counts as one) can go in a sleeve. */
function tokFacesUsed(needs) {
  const faces = new Map();
  for (const need of needs || []) {
    const used = (need.cards || []).length ? need.cards
      : need.state === "differs" && (need.stand_ins || []).length ? [need.stand_ins[0]] : [];
    for (const card of used) {
      const face = card.side === "back" ? card.back : card.front;
      if (!face) continue;
      const key = tokFacesKey(card);
      if (!faces.has(key)) faces.set(key, new Map());
      faces.get(key).set(tokFold(face), face);
    }
  }
  return faces;
}

/** How much of a double-sided token card a deck uses: "both sides used", or "Zombie side only, can be
 * sleeved" when the deck needs just one face (so the card can go in a sleeve that hides the other).
 * null for a single-sided card or one the deck doesn't use. faces: tokFacesUsed. */
function tokSides(card, faces) {
  if (!card.back || !faces) return null;
  const used = faces.get(tokFacesKey(card));
  if (!used || !used.size) return null;
  return used.size > 1 ? "both sides used" : `${[...used.values()][0]} side only, can be sleeved`;
}

/** "Zombie / Zombie Knight ×8, Zombie side" (no side for a single-sided card), with tokSides's words when
 * faces is given: "…, Zombie side only, can be sleeved" or "…, Zombie side (both sides used)". */
function tokCardWords(card, faces = null) {
  const face = card.side === "back" ? card.back : card.front;
  const sides = tokSides(card, faces);
  const side = !card.back || !face ? ""
    : sides && sides !== "both sides used" ? `, ${face} side only, can be sleeved`
    : `, ${face} side` + (sides ? ` (${sides})` : "");
  return `${tokLabel(card)} ×${card.quantity}${side}`;
}

/** A need's characteristics in words: "2/2 black creature with flying". */
function tokNeedWords(need) {
  const colours = Array.isArray(need.colors)
    ? need.colors.length ? need.colors.map((c) => COLOUR_WORDS[c] || c).join(" and ") : "colourless" : "";
  const type = String(need.type_line || "").split(" // ")[0].replace(/^Token\b\s*/, "").split(/\s+[—-]\s+/)[0];
  const what = need.kind === "reminder" ? "reminder card" : need.kind === "emblem" ? "emblem" : (type || "token").toLowerCase();
  const keywords = (need.keywords || []).map((k) => String(k).toLowerCase());
  const parts = [need.pt, need.kind === "token" || need.kind == null ? colours : "", what].filter(Boolean);
  return parts.join(" ") + (keywords.length ? ` with ${keywords.join(", ")}` : "");
}

/** "Made by Hornet Queen and Mitotic Slime", the rest folded away after two ("and 3 more"). */
function tokMadeBy(madeBy) {
  const names = (madeBy || []).map((m) => m.section === "Sideboard" ? `${m.name} (sideboard)` : m.name);
  if (!names.length) return null;
  if (names.length <= 2) return el("p", { class: "token-need-made", text: `Made by ${names.join(" and ")}` });
  return el("div", { class: "token-need-made" }, el("span", { text: `Made by ${names.slice(0, 2).join(", ")} ` }),
    el("details", {}, el("summary", { text: `and ${names.length - 2} more` }),
      el("p", { text: names.slice(2).join(", ") })));
}

/** One need of a deck: picture, name and characteristics, who makes it, its state, the cards to grab and
 * the stand-ins, with why each stand-in differs. faces (tokFacesUsed of all the deck's needs) adds whether
 * a double-sided card to grab is needed both ways up. */
function tokenNeed(need, faces = null) {
  const cards = need.cards || [], standIns = need.stand_ins || [], incoming = need.incoming || [];
  const desc = need.key && String(need.key).startsWith("name:") ? "" : tokNeedWords(need);
  // A token without a picture of its own shows example art of a token with its name, labelled as such.
  const example = !need.image && need.example ? need.example : null;
  return el("li", { class: `token-need token-need-${need.state}` },
    example ? el("span", { class: "token-need-pic" }, tokenThumb(example, 64, need.pt),
      el("small", { class: "token-need-example", text: "Example art" })) : tokenThumb(need.image, 64, need.pt),
    el("div", { class: "token-need-body" },
      el("p", { class: "token-need-name" }, el("b", { text: need.name }), desc ? ` ${desc}` : null),
      tokMadeBy(need.made_by),
      // Whose side it lands on, read from the cards' text (E7-S23): said only when it may be the opponent's.
      need.side_words ? el("p", { class: `token-need-side token-need-side-${need.side}`, text: need.side_words }) : null,
      el("p", { class: "token-need-state" }, tokenStateChip(need.state, need.words)),
      cards.length ? el("ul", { class: "token-grab", "aria-label": "Grab" }, cards.map((card) => el("li", {},
        `Grab ${tokCardWords(card, faces)}`,
        card.also_for && card.also_for.length ? ` (same card as for ${card.also_for.join(" and ")})` : null,
        card.shared && card.shared.length ? el("small", { class: "tok-shared",
          text: `Also used by ${card.shared.map((h) => h.title).join(" and ")}, with too few cards for all of them` }) : null,
        card.verdict === "check" && card.why && card.why.length ? el("small", { text: card.why.join("; ") }) : null))) : null,
      (need.in_use || []).length ? el("ul", { class: "token-grab", "aria-label": "In use" }, need.in_use.map((item) =>
        el("li", { text: `In use: ${tokLabel(item)} ×${item.quantity}, packed in ${item.decks.join(" and ")}` }))) : null,
      incoming.length ? el("ul", { class: "token-grab", "aria-label": "On the way" }, incoming.map((item) => el("li", {
        text: `On the way: ${tokLabel(item)} ×${item.quantity} (order ${item.order})` }))) : null,
      standIns.length ? el("div", { class: "token-stand-ins" }, el("p", { class: "sub", text: "Stand-ins" }),
        el("ul", { class: "token-grab" }, standIns.map((card) => el("li", {}, tokCardWords(card),
          card.why && card.why.length ? el("small", { text: card.why.join("; ") }) : null)))) : null));
}

/** A deck's token needs (deck_tokens's "needs") as a list, in the server's order. faces: tokFacesUsed of
 * all the deck's needs (tokenNeed). */
function tokenNeedList(needs, faces = null) {
  return el("ul", { class: "token-needs" }, (needs || []).map((need) => tokenNeed(need, faces)));
}

/** "4 ready · 1 to check · 1 you don't have" from a deck_tokens result's counts. */
function tokCountWords(counts) {
  const c = counts || {};
  return [[c.ready, "ready"], [c.check, "to check"], [c.differs, "different"], [c.incoming, "on the way"],
    [c.none, "you don't have"]].filter(([n]) => n > 0).map(([n, words]) => `${n} ${words}`).join(" · ");
}

/** Text to compare names by: no accents, no case, no space at the ends (like cards.fold on the server). */
function tokFold(text) {
  return String(text || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

/** The number of one-letter changes between a and b (for "Did you mean …?"). */
function tokDistance(a, b) {
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) {
      row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = row;
  }
  return prev[b.length];
}

/** The Scryfall face name a typed name probably means, or null: the same name in another case or without
 * its accents, else the nearest name a letter or two away. null when it's already exact or nothing's near. */
function tokSuggest(value, names) {
  const typed = String(value || "").trim();
  if (!typed || !names || !names.length || names.includes(typed)) return null;
  const folded = tokFold(typed);
  const same = names.find((name) => tokFold(name) === folded);
  if (same) return same;
  const most = Math.max(1, Math.floor(folded.length / 4));
  let best = null, bestDistance = most + 1;
  for (const name of names) {
    const f = tokFold(name);
    if (Math.abs(f.length - folded.length) > most) continue;
    const d = tokDistance(folded, f);
    if (d < bestDistance) { best = name; bestDistance = d; }
  }
  return best;
}

const TOK_COLOURS = ["white", "blue", "black", "red", "green"];
// The keywords details may list (the server's KEYWORDS in lib/tokens/details.py), longest first.
const TOK_KEYWORDS = ["first strike", "double strike", "indestructible", "deathtouch", "vigilance", "hexproof",
  "lifelink", "trample", "defender", "decayed", "flying", "prowess", "menace", "reach", "haste", "toxic", "ward"];

/** A face name typed with its traits ("White Angel 4/4 flying"), split into the Scryfall name and the
 * details the row keeps them in: { name: "Angel", details: "4/4; white; flying" }. null unless the text
 * had a P/T, colour or keyword in it and what's left is (or is a letter or two from) a face name. */
function tokSplitDescription(value, names) {
  let rest = ` ${String(value || "").toLowerCase().replace(/[,;()]/g, " ")} `;
  if (!names || !names.length || !rest.trim() || names.includes(String(value).trim())) return null;
  let pt = "";
  rest = rest.replace(/\s(\d+|\*|x)\/(\d+|\*|x)(?=\s)/i, (m, p, t) => { pt = `${p}/${t}`.toUpperCase(); return " "; });
  const keywords = [];
  for (const k of TOK_KEYWORDS) {
    rest = rest.replace(new RegExp(`\\s${k}(?=\\s)`), () => { keywords.push(k); return " "; });
  }
  const colours = new Set();
  const whole = rest.trim().replace(/\s+/g, " ");       // a name with a colour in it, such as "Blue Dog"
  const named = (pt || keywords.length) && names.find((n) => tokFold(n) === tokFold(whole));
  if (named) return { name: named, details: [pt, keywords.join(", ")].filter(Boolean).join("; ") };
  rest = rest.replace(/\S+/g, (word) => {
    const parts = word.split("-");
    if (word === "colourless" || word === "colorless") { colours.add("colourless"); return ""; }
    if (!parts.every((p) => TOK_COLOURS.includes(p))) return word;
    parts.forEach((p) => colours.add(p));
    return "";
  });
  const typed = rest.trim().replace(/\s+/g, " ");
  if (!typed || !(pt || keywords.length || colours.size)) return null;
  const name = names.find((n) => tokFold(n) === tokFold(typed)) || tokSuggest(typed, names);
  if (!name) return null;
  const colourText = colours.has("colourless") ? "colourless" : TOK_COLOURS.filter((c) => colours.has(c)).join(" and ");
  return { name, details: [pt, colourText, keywords.join(", ")].filter(Boolean).join("; ") };
}

// ------------------------------------------------------- reading a details field

const TOK_PT = /^(\d+|\*|x)\/(\d+|\*|x)$/i;
const TOK_UNKNOWN = /\b(?:unconfirmed|unknown|unspecified)\b/i;

/** The keyword an item names ("ward {2}" -> "ward"), or null (the server's _keyword). */
function tokKeyword(item, words) {
  const text = item.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  if (words.includes(text)) return text;
  const m = /^(.+?)\s+(?:\d+|x|\{[^}]*\})+$/.exec(text);
  return m && words.includes(m[1]) ? m[1] : null;
}

/** The colour words a part is made of (in WUBRG order; [] is colourless), or null if it isn't one. */
function tokColourWords(part) {
  const words = part.toLowerCase().split(/\s*,\s*|\s+and\s+|\s+/).filter(Boolean);
  if (words.length === 1 && (words[0] === "colourless" || words[0] === "colorless")) return [];
  if (words.length && words.every((w) => TOK_COLOURS.includes(w))) return TOK_COLOURS.filter((c) => words.includes(c));
  return null;
}

/** What a details string records, read as the server reads it (parse_details in lib/tokens/details.py):
 * { pt, colours (null: not recorded; []: colourless), has, lacks, unknown ("pt", "colors", "keywords"),
 * extra (the parts kept but never compared) }. keywords: the ones a part may list, lower case. */
function tokReadDetails(text, keywords = TOK_KEYWORDS) {
  const facts = { pt: null, colours: null, has: [], lacks: [], unknown: [], extra: [] };
  const addTo = (list, items) => items.forEach((i) => { if (!list.includes(i)) list.push(i); });
  for (const part of String(text || "").split(";").map((s) => s.trim())) {
    if (!part) continue;
    const low = part.toLowerCase();
    if (TOK_PT.test(part)) { facts.pt = part.toUpperCase(); continue; }
    if (TOK_UNKNOWN.test(part)) {
      const aspects = [];
      if (/power|toughness|\bp\/t\b/.test(low)) aspects.push("pt");
      if (/colou?r/.test(low)) aspects.push("colors");
      if (/abilit|keyword/.test(low)) aspects.push("keywords");
      if (!aspects.length && /printing|set|art/.test(low)) { facts.extra.push(part); continue; }
      addTo(facts.unknown, aspects.length ? aspects : ["pt", "colors", "keywords"]);
      continue;
    }
    const colours = tokColourWords(part);
    if (colours) { facts.colours = colours; continue; }
    const items = part.split(",").map((i) => i.trim()).filter(Boolean);
    const has = [], lacks = [];
    const read = items.length && items.every((item) => {
      const m = /^no\s+(.+)$/i.exec(item);
      const keyword = tokKeyword(m ? m[1] : item, keywords);
      if (keyword) (m ? lacks : has).push(keyword);
      return keyword;
    });
    if (read) { addTo(facts.has, has); addTo(facts.lacks, lacks); continue; }
    facts.extra.push(part);
  }
  return facts;
}

// Words that are never a typo for a colour or keyword: the words of type lines and notes ("card" is one
// letter from ward, "blank" from black). The words of the token face names are added (tokPlainWords):
// "Clue" isn't blue. The server's _PLAIN_WORDS in lib/tokens/details.py.
const TOK_PLAIN_WORDS = ["card", "token", "emblem", "creature", "artifact", "enchantment", "land", "legendary",
  "equipment", "vehicle", "printed", "side", "front", "back", "word", "words", "hard", "glue", "clue", "blank",
  "while", "write", "waste", "each", "warm"];
const TOK_PUNCT = ".:;()\"'";

/** A word without the punctuation at its ends, in lower case (the server's strip(_PUNCT).lower()). */
function tokBareWord(word) {
  let start = 0, end = word.length;
  while (start < end && TOK_PUNCT.includes(word[start])) start++;
  while (end > start && TOK_PUNCT.includes(word[end - 1])) end--;
  return word.slice(start, end).toLowerCase();
}

/** A part's words, bare (tokBareWord), without "and" and dashes: "4/4 white and blue." -> 4/4, white, blue. */
function tokWords(part) {
  return (part.match(/[^\s,]+/g) || []).map(tokBareWord).filter((w) => w && !["and", "—", "-", "–"].includes(w));
}

/** TOK_PLAIN_WORDS and every word of the face names given. */
function tokPlainWords(names) {
  return new Set([...TOK_PLAIN_WORDS, ...(names || []).flatMap((n) => n.split(/\s+/).map(tokBareWord))]);
}

/** The edits (insert, delete, change, swap two neighbours) that turn a into b (the server's _distance). */
function tokEdits(a, b) {
  const rows = [Array.from({ length: b.length + 1 }, (_, j) => j)];
  for (let i = 1; i <= a.length; i++) {
    const row = [i];
    for (let j = 1; j <= b.length; j++) {
      row[j] = Math.min(rows[i - 1][j] + 1, row[j - 1] + 1, rows[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) row[j] = Math.min(row[j], rows[i - 2][j - 2] + 1);
    }
    rows.push(row);
  }
  return rows[a.length][b.length];
}

// The words of the keywords ("first", "strike", ...), sorted.
const TOK_KEYWORD_WORDS = [...new Set(TOK_KEYWORDS.flatMap((k) => k.split(" ")))].sort();

/** The colour or keyword word a word is a likely typo of ("whte" -> "white"), or null: one edit for words
 * of 4-5 letters, two for longer ones. */
function tokNear(word, plain) {
  if (word.length < 4 || plain.has(word) || !/^\p{L}+$/u.test(word)) return null;
  const limit = word.length <= 5 ? 1 : 2;
  let best = null, bestDistance = Infinity;
  for (const option of [...TOK_COLOURS, "colourless", ...TOK_KEYWORD_WORDS]) {
    const d = tokEdits(word, option);
    if (d < bestDistance) { best = option; bestDistance = d; }
  }
  return bestDistance > 0 && bestDistance <= limit ? best : null;
}

/** What a run of words says, one item at a time: [kind, text] with kind "pt", "colour", "keyword",
 * "lacks" or null (not understood). */
function tokReadWords(words, keywords) {
  const out = [];
  let i = 0;
  while (i < words.length) {
    const word = words[i];
    if (TOK_PT.test(word)) { out.push(["pt", word.toUpperCase()]); i++; continue; }
    if (word === "colourless" || word === "colorless") { out.push(["colour", "colourless"]); i++; continue; }
    if (word.split("-").every((w) => TOK_COLOURS.includes(w))) {           // "white-blue"
      word.split("-").forEach((w) => out.push(["colour", w])); i++; continue;
    }
    const lacks = word === "no" && i + 1 < words.length;
    const start = lacks ? i + 1 : i;
    let found = false;
    for (const size of [3, 2, 1]) {          // the longest keyword first: "first strike", "ward {2}"
      if (start + size > words.length) continue;
      const text = words.slice(start, start + size).join(" ");
      if (tokKeyword(text, keywords)) { out.push([lacks ? "lacks" : "keyword", text]); i = start + size; found = true; break; }
    }
    if (!found) { out.push([null, word]); i++; }
  }
  return out;
}

/** The details understood items are written as: P/T, then colours joined with "and" in WUBRG order, then
 * keywords comma-joined (tokSplitDescription's order); null when they can't be one face's details (two
 * P/Ts, colourless with a colour). */
function tokCanonical(items) {
  const pts = items.filter(([kind]) => kind === "pt").map(([, text]) => text);
  const colours = new Set(items.filter(([kind]) => kind === "colour").map(([, text]) => text));
  if (pts.length > 1 || (colours.has("colourless") && colours.size > 1)) return null;
  const keywords = [...new Set(items.filter(([kind]) => kind === "keyword" || kind === "lacks")
    .map(([kind, text]) => (kind === "lacks" ? "no " : "") + text))];
  const colourText = ["colourless", ...TOK_COLOURS].filter((c) => colours.has(c)).join(" and ");
  return [pts[0] || "", colourText, keywords.join(", ")].filter(Boolean).join("; ");
}

/** The parts of a details string that aren't read and look like mistakes rather than notes, as
 * { part, message, rewrite } (the server's details_mistakes, kept to the same rules):
 * - a part whose words are mostly a P/T, colours or keywords, missing its ";" ("4/4 white flying",
 *   "white, flying"): "separate them with ';'";
 * - a part whose every word is understood or a letter or two off a colour or keyword ("whte", "4/4
 *   flyng"): "did you mean white?".
 * Type lines, rules text and notes such as "printed pink" are left alone: most of their words are neither.
 * rewrite is what the part most likely meant ("4/4; white; flying"), or null. names: the token face names. */
function tokDetailsMistakes(text, keywords = TOK_KEYWORDS, names = []) {
  const plain = tokPlainWords(names);
  const found = [];
  for (const part of String(text || "").split(";").map((s) => s.trim())) {
    if (!part || TOK_UNKNOWN.test(part) || !tokReadDetails(part, keywords).extra.length) continue;
    const items = tokReadWords(tokWords(part), keywords);
    // Each word not understood: its likely fix, itself when it's part of a keyword ("strike" in "frist
    // strike"), or null.
    const near = items.map(([kind, word]) => kind ? null
      : tokNear(word, plain) || (TOK_KEYWORD_WORDS.includes(word) ? word : null));
    // A "no" before a keyword's typo ("no flyng") is understood: it's "no flying".
    const fixes = near.map((fix, k) => !items[k][0] && items[k][1] === "no" && k + 1 < items.length
      && TOK_KEYWORD_WORDS.includes(near[k + 1]) ? "no" : fix);
    const typos = items.map(([, word], k) => fixes[k] && fixes[k] !== word ? fixes[k] : null).filter(Boolean);
    const known = items.filter(([kind]) => kind).length;
    const unknown = items.filter(([kind], k) => !kind && !fixes[k]).length;
    const again = tokReadWords(items.map(([, word], k) => fixes[k] || word).join(" ").split(" "), keywords);
    if (typos.length && !unknown && again.every(([kind]) => kind)) {
      // Only when the fixes make colours and keywords ("frist" alone isn't one).
      const rewrite = tokCanonical(again);
      found.push({ part, message: `did you mean ${rewrite || typos.join(" and ")}?`, rewrite });
    } else if (known && known > items.length - known) {
      const rewrite = known === items.length ? tokCanonical(items) : null;
      found.push({ part, message: tokSeparate(rewrite), rewrite });
    }
  }
  return found;
}

/** What a part missing its separators is told: "separate them with ';' (4/4; white)", "list them with
 * commas (flying, trample)" or "write it as 4/4" (the server's _separate). */
function tokSeparate(rewrite) {
  if (rewrite === null || rewrite.includes(";")) return "separate them with ';'" + (rewrite ? ` (${rewrite})` : "");
  return rewrite.includes(",") ? `list them with commas (${rewrite})` : `write it as ${rewrite}`;
}

/** A details string's reading for the line under its field (null when it's blank): read, the facts as
 * words ("4/4", "white", "no deathtouch", "colour unknown"); notes, one per unread part, a likely mistake
 * (tokDetailsMistakes) with what's wrong, or kept but not compared; and fix, the whole text with each
 * mistake put right, when that's clear. names: the token face names, whose words are never typos. */
function tokDetailsAdvice(text, keywords = TOK_KEYWORDS, names = []) {
  const parts = String(text || "").split(";").map((s) => s.trim()).filter(Boolean);
  if (!parts.length) return null;
  const facts = tokReadDetails(text, keywords);
  const read = [facts.pt,
    facts.colours && (facts.colours.length ? facts.colours.join(" and ") : "colourless"),
    ...facts.has, ...facts.lacks.map((k) => `no ${k}`),
    ...facts.unknown.map((a) => ({ pt: "power/toughness unknown", colors: "colour unknown", keywords: "abilities unknown" })[a])]
    .filter(Boolean);
  const mistakes = new Map(tokDetailsMistakes(text, keywords, names).map((m) => [m.part, m]));
  const notes = facts.extra.map((part) => {
    const mistake = mistakes.get(part);
    return mistake ? { part, mistake: true, message: `'${part}' isn't read: ${mistake.message}${mistake.message.endsWith("?") ? "" : "."}` }
      : { part, mistake: false, message: `'${part}' is kept but not compared.` };
  });
  return { read, notes, fix: tokDetailsFix(parts, mistakes, keywords) };
}

/** The whole details text with each mistake put right, or null. The facts already read and the rewrites
 * are written once together (tokCanonical), where the first of them was, so a rewrite's colour joins the
 * ones already there rather than replacing them; null when they can't be one face's (two P/Ts, colourless
 * with a colour, a keyword it both has and lacks). Unread notes and unknowns stay as typed. */
function tokDetailsFix(parts, mistakes, keywords) {
  if (![...mistakes.values()].some((m) => m.rewrite)) return null;
  const items = [], kept = [];
  let at = null;
  for (const part of parts) {
    const mistake = mistakes.get(part);
    const text = mistake ? mistake.rewrite : part;
    const read = !text || TOK_UNKNOWN.test(text) || tokReadDetails(text, keywords).extra.length ? null
      : tokReadWords(tokWords(text), keywords);
    if (!read || !read.every(([kind]) => kind)) { kept.push(part); continue; }
    if (at === null) at = kept.length;
    // The same P/T twice is one ("4/4; 4/4 whte").
    items.push(...read.filter(([kind, t]) => kind !== "pt" || !items.some(([k, u]) => k === "pt" && u === t)));
  }
  const has = items.filter(([kind]) => kind === "keyword").map(([, t]) => tokKeyword(t, keywords));
  if (items.some(([kind, t]) => kind === "lacks" && has.includes(tokKeyword(t, keywords)))) return null;
  const written = tokCanonical(items);
  if (!written) return null;
  kept.splice(at, 0, written);
  return kept.join("; ");
}

/** The line under a details field: "Read as: 4/4 · white · flying", a warning for each likely mistake
 * with a one-tap fix when the right text is clear, and a quiet note for parts kept but not compared.
 * line.refresh(text) redraws only the line, so typing keeps the field's focus and caret; use(text) puts
 * a fix in. It never stops a save. names: the token face names (or a function giving them, as they load). */
function tokReadingLine(use, keywords = TOK_KEYWORDS, names = []) {
  const line = el("div", { class: "tok-reading" });
  line.refresh = (text) => {
    clear(line);
    const advice = tokDetailsAdvice(text, keywords, typeof names === "function" ? names() : names);
    if (!advice) return;
    line.append(el("p", { class: "field-hint tok-reading-read",
      text: advice.read.length ? `Read as: ${advice.read.join(" · ")}` : "Nothing here is read yet." }));
    const mistakes = advice.notes.filter((n) => n.mistake);
    if (mistakes.length) {
      line.append(el("div", { class: "note note-warn tok-reading-warn", role: "status" }, el("div", {},
        mistakes.map((n) => el("p", { text: n.message })),
        advice.fix ? el("button", { type: "button", class: "btn btn-quiet tok-reading-fix tok-sheet-mutate",
          text: `Use ${advice.fix}`, onclick: () => use(advice.fix) }) : null)));
    }
    for (const n of advice.notes.filter((n) => !n.mistake)) {
      line.append(el("p", { class: "field-hint tok-reading-kept", text: n.message }));
    }
  };
  return line;
}

/** The uncertainty test receipts use (inventory rules.token_uncertain): the notes or details say unknown. */
function tokUncertain(row) {
  return /\b(?:unconfirmed|unknown|unspecified)\b/i.test([row.notes, row.front_details, row.back_details].join(" "));
}

/** Whether the printing and both faces are known (inventory rules.token_known): only such equal rows are
 * the same card for sure, so only they can't be kept apart. */
function tokKnown(row) {
  return Boolean(row.set && row.front_collector_number && row.finish && (!row.back || row.back_collector_number))
    && !tokUncertain(row);
}

/** The row as the page loaded it, every value as text: a save's "base", and how a row is found again. */
function tokBase(row) {
  return Object.fromEntries(TOK_FIELDS.map((key) => [key, row[key] == null ? "" : String(row[key])]));
}

function tokSameRow(a, b) { return TOK_FIELDS.every((key) => String(a[key] ?? "") === String(b[key] ?? "")); }

/** A token card's identity as receipts compare it (receipt.token_identity): every column but the quantity
 * and the notes. */
function tokIdentity(row) {
  return TOK_FIELDS.filter((key) => key !== "quantity" && key !== "notes").map((key) => String(row[key] ?? "")).join("\u0000");
}

/** Where the row a write named (base) is in a 409's latest list. "same": still there as it was; "changed":
 * one row is it with other values (row); "unsure": it was changed, but which row it is now can't be told;
 * "gone": removed. Rows have no ids, so a changed row is looked for among the rows that weren't in
 * the list as the page had it (before, when known): the server's pick (conflict.base_state "changed" and
 * conflict.current), then by receipts' identity, then by its face names (a printing filled in meanwhile).
 * A "changed" from the server with no row found here is "unsure", never "gone". */
function tokLocate(latestRows, base, conflict, before) {
  const rows = latestRows || [];
  const same = rows.find((r) => tokSameRow(tokBase(r), base));
  if (same) return { state: "same", row: same };
  const fresh = Array.isArray(before) ? rows.filter((r) => !before.some((b) => tokSameRow(tokBase(b), tokBase(r)))) : rows;
  const current = conflict && conflict.base_state === "changed" && conflict.current && conflict.current.row;
  if (current) {
    // The server's pick, unless it is a row the page already had as it is (then it isn't the changed one).
    const theirs = fresh.find((r) => tokSameRow(tokBase(r), tokBase(current)));
    if (theirs) return { state: "changed", row: theirs };
  }
  const tests = [(r) => tokIdentity(r) === tokIdentity(base),
    (r) => String(r.front ?? "") === String(base.front ?? "") && String(r.back ?? "") === String(base.back ?? "")];
  for (const test of tests) {
    const found = fresh.filter(test);
    if (found.length === 1) return { state: "changed", row: found[0] };
    if (found.length > 1) return { state: "unsure" };
  }
  const changed = conflict && (conflict.base_state === "changed" || conflict.reason === "changed");
  return { state: changed ? "unsure" : "gone" };
}

/** What someone else changed on a row: "Quantity 8 → 7; Notes (blank) → lost one". */
function tokChangedWords(base, row) {
  const shown = (value) => value === "" ? "(blank)" : value;
  return TOK_FIELDS.filter((key) => String(base[key] ?? "") !== String(row[key] ?? ""))
    .map((key) => `${TOK_FIELD_WORDS[key]} ${shown(String(base[key] ?? ""))} → ${shown(String(row[key] ?? ""))}`).join("; ");
}

/** Where a holder's link goes. link (lib/tokens _holders): the deck id to open, or null for a product
 * kept intact whose decks are named (its "product/<stem>" is no deck), which opens the library's products.
 * Without a link field, a whole product's id is taken as no deck. */
function tokHolderHref(id, link) {
  if (typeof link === "string" && link) return deckHref(link);
  if (link === null || /^product\/[^/]+$/.test(String(id || ""))) return "#/library?format=product";
  return deckHref(id);
}

/** "Sam changed the tokens list 7:42 pm today." from a 409's conflict. */
function tokConflictTitle(conflict) {
  const when = conflict && conflict.when ? Date.parse(conflict.when) : NaN;
  if (conflict && conflict.by && !Number.isNaN(when)) return `${conflict.by} changed the tokens list ${timeWords(when)}`;
  return "The tokens list changed after you opened it";
}


// --------------------------------------------------------------- the page

/** The tokens list's address for a space: home's has no ?space=. */
function tokPath(space) {
  return !space || space === HOME_SPACE ? "/api/tokens" : `/api/tokens?space=${encodeURIComponent(space)}`;
}

/** A write's body with the space it's for (home's leaves it out). */
function tokBody(view, body) {
  return view.space && view.space !== HOME_SPACE ? { ...body, space: view.space } : body;
}

function showTokens(token, params) {
  const wanted = params && params.get("space");
  const space = wanted && seenSpaces().some((s) => s.id === wanted) ? wanted : ownSpace();
  return load(tokPath(space), token, (data) => drawTokens(data, token, space),
    { title: "The tokens list couldn't be loaded" });
}

/** Links to token lists in seenSpaces(): only visible spaces, omitted with fewer than two choices. */
function tokSpacePicker(space) {
  const spaces = seenSpaces();
  if (spaces.length < 2) return null;
  return el("nav", { class: "segmented tok-spaces", "aria-label": "Whose tokens" }, spaces.map((s) => el("a", {
    href: s.id === HOME_SPACE ? "#/tokens?space=home" : `#/tokens?space=${encodeURIComponent(s.id)}`,
    "aria-current": s.id === space ? "page" : null, text: s.name })));
}

function tokensActive(view) {
  return view.token === routeToken && view.root.isConnected && state.profile && state.profile.id === view.profile;
}

function drawTokens(data, token, space = HOME_SPACE) {
  const root = el("div", { class: "tok-page" });
  // A server that doesn't know spaces yet answers with home's list and no "space": a person's isn't shown.
  const unsupported = space !== HOME_SPACE && data.space === undefined;
  const view = { root, token, profile: state.profile.id, seq: 0, data: unsupported ? { ...data, rows: [], missing: [], incoming: [] } : data,
    busy: false, space, canEdit: canEditSpace(space) && !unsupported,
    filter: local.get("tokens.filter") || "all", search: local.get("tokens.search") || "" };
  if (!TOK_FILTERS.some(([key]) => key === view.filter)) view.filter = "all";
  view.message = el("div", { class: "tok-message", role: "status", "aria-live": "polite" });
  view.notices = el("div");
  view.panels = el("div", { class: "tok-panels" });
  view.lists = el("div");
  view.count = el("p", { class: "result-count tok-count", role: "status" });
  view.filterButtons = TOK_FILTERS.map(([key, text]) => el("button", { type: "button", "data-filter": key,
    "aria-pressed": String(view.filter === key), text,
    onclick: () => { view.filter = key; local.set("tokens.filter", key); updateTokens(view); } }));
  const search = el("input", { id: "tok-search", type: "search", autocomplete: "off", spellcheck: "false",
    placeholder: "Search: Zombie, Treasure…", value: view.search,
    oninput: () => { view.search = search.value; local.set("tokens.search", search.value); drawTokenList(view); } });
  view.searchInput = search;
  add(root, [
    ...pageHead({ title: space === HOME_SPACE ? routeH1("tokens") : `${spaceName(space)}'s tokens`,
      description: "Token and reminder cards. A double-sided card counts once.",
      primary: view.canEdit ? el("button", { type: "button", class: "btn btn-primary tok-mutate", text: "Add a token card",
        "data-focus": "add", onclick: () => addToken(view) }) : null,
      more: [view.canEdit ? { label: "Plan packed token cards…", onclick: () => openTokenPlan(view) } : null,
        { label: "Refresh", onclick: () => refreshTokens(view) }] }),
    tokSpacePicker(space),
    unsupported ? el("p", { class: "box box-info", text: `${spaceName(space)}'s tokens can't be shown until Deck Lab's server is updated.` })
      : !view.canEdit ? el("p", { class: "sub tok-read-only", text: space === HOME_SPACE
        ? "Read only: only the people of the home collection can change these." : `Read only: only ${spaceName(space)} can change these.` }) : null,
    view.notices, view.message, view.panels,
    view.tools = el("div", { class: "toolbar tok-tools" },
      el("label", { class: "field tok-search", for: search.id }, el("span", { class: "sr-only", text: "Search by face name" }), search),
      el("div", { class: "segmented tok-filter", role: "group", "aria-label": "Show" }, view.filterButtons),
      view.count),
    view.lists,
  ]);
  $("#main").append(root);
  updateTokens(view);
  return view;
}

/** Draw everything below the head again from view.data, keeping the scroll place and the focus (or moving
 * it to the control whose data-focus is focus, when given; null: nowhere). */
function updateTokens(view, focus) {
  const focused = focus !== undefined ? focus : document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.focus : null;
  const y = window.scrollY;
  const data = view.data;
  const toCheck = (data.rows || []).filter(tokToCheck).length;
  for (const button of view.filterButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.filter === view.filter));
    const words = TOK_FILTERS.find(([key]) => key === button.dataset.filter)[1];
    button.textContent = button.dataset.filter === "check" && toCheck ? `${words} (${num(toCheck)})` : words;
  }
  clear(view.notices);
  add(view.notices, [warningsBox(data.problems, "Some token rows can't be read"),
    data.info && data.info.length ? note(...data.info) : null]);
  if (data.exists && data.sorted === false) {
    view.notices.append(el("p", { class: "box box-info", text: "Not in the standard order; the next save sorts it." }));
  }
  if (data.index_ready === false) {
    view.notices.append(el("p", { class: "box box-info", text: "Name checks are off until the card data is rebuilt." }));
  }
  clear(view.panels);
  add(view.panels, [tokMissingPanel(data, view.space), tokIncomingPanel(data)]);
  drawTokenList(view);
  setTokensBusy(view, view.busy);
  window.scrollTo(0, y);
  const again = focused && view.root.querySelector(`[data-focus="${focused}"]`);
  if (again) again.focus({ preventScroll: true });
}

/** Which rows the filter and the search show. */
function tokShown(view) {
  const search = tokFold(view.search);
  return (view.data.rows || []).filter((row) => {
    const uses = row.uses || [];
    if (search && !tokFold(row.front).includes(search) && !tokFold(row.back).includes(search)) return false;
    if (view.filter === "used") return uses.length > 0;
    if (view.filter === "unused") return uses.length === 0;
    if (view.filter === "check") return tokToCheck(row);
    return true;
  });
}

/** Whether a row has something to check (the "To check" filter): its details or printing are unconfirmed, or
 * a deck's use of it says to check it, or it only stands in for a different token, or more built decks use it
 * than it has cards. */
function tokToCheck(row) {
  return Boolean(row.unconfirmed || (row.shared || []).length
    || (row.uses || []).some((u) => u.state === "check" || u.state === "differs"));
}

/** Whether a tile carries the "Details to check" chip: only when a deck relies on the card and its details
 * aren't recorded well enough to say it fits. Most rows were reported without their details, so an unused
 * or merely unconfirmed row stays plain (the "To check" filter and the sheet still find it). */
function tokNeedsCheckChip(row) {
  return (row.uses || []).some((u) => u.state === "check");
}

function drawTokenList(view) {
  const rows = view.data.rows || [];
  const shown = tokShown(view);
  const cards = shown.reduce((n, row) => n + Number(row.quantity || 0), 0);
  view.count.textContent = !rows.length ? "" : rows.length === shown.length
    ? `${plural(rows.length, "kind")}, ${plural(view.data.cards != null ? view.data.cards : cards, "physical card")}`
    : `${num(shown.length)} of ${plural(rows.length, "kind")} (${plural(cards, "physical card")})`;
  clear(view.lists);
  // With no token cards there's nothing to search or filter, and no count to give.
  if (view.tools) view.tools.hidden = !rows.length;
  if (!rows.length) {
    // The head's Add a token card is the page's one primary button.
    view.lists.append(el("div", { class: "empty" }, el("p", { text: "No token cards recorded yet." }),
      view.canEdit ? el("button", { type: "button", class: "btn tok-mutate", text: "Add a token card",
        onclick: () => addToken(view) }) : null));
  } else if (!shown.length) {
    // Emptied by the search or the filter: the one way back is to clear them.
    view.lists.append(emptyBox("No token cards match the search and filter.", el("button", { type: "button", class: "btn",
      text: "Clear the search and filter", onclick: () => {
        if (!tokensActive(view)) return;
        view.search = ""; view.filter = "all";
        local.set("tokens.search", ""); local.set("tokens.filter", "all");
        if (view.searchInput) view.searchInput.value = "";
        updateTokens(view);
        if (view.searchInput) view.searchInput.focus();
      } }), { live: true }));
  } else {
    view.lists.append(el("div", { class: "card-tiles tok-grid" }, shown.map((row) => tokCard(view, row))));
  }
  setTokensBusy(view, view.busy);
}

/** "TLTR H13 / H13 · foil", or "Printing not recorded". */
function tokPrinting(row) {
  if (!row.set) return "Printing not recorded";
  const numbers = [row.front_collector_number, row.back_collector_number].filter(Boolean).join(" / ");
  return `${row.set.toUpperCase()}${numbers ? ` ${numbers}` : ""}${row.finish && row.finish !== "nonfoil" ? ` · ${row.finish}` : ""}`;
}

/** A row's faces as the API sends them (or, from an older server, from the row itself). */
function tokFaces(row) {
  return row.faces && row.faces.length ? row.faces
    : [{ side: "front", name: row.front, details: row.front_details, known: null, image: null },
      row.back ? { side: "back", name: row.back, details: row.back_details, known: null, image: null } : null].filter(Boolean);
}

/** What a tile shows of a row: {token (for tokenTile), example (its pictures are example art: the row records
 * no printing), meta}. The row's own printing's pictures when it records one; else example art of a token
 * with that face name (lib/api/tokens.py _example_image), labelled as such and never taken for its printing. */
function tokTileParts(row) {
  const faces = tokFaces(row);
  const front = faces.find((f) => f.side === "front") || {};
  const back = faces.find((f) => f.side === "back") || null;
  const own = front.image || (back && back.image);
  const pic = (face) => face ? face.image || (!own ? face.example : null) || null : null;
  const token = { front: row.front, back: row.back || null, img: pic(front), back_img: pic(back) };
  const example = !own && Boolean(token.img || token.back_img);
  const details = faces.map((f) => f.details).filter(Boolean).join(" / ");
  const meta = [row.set ? tokPrinting(row) : example ? "Printing not recorded" : null, details || null]
    .filter(Boolean).join(" · ") || null;
  return { token, example, meta };
}

/** The decks a row serves, as chips linking to each (one chip per deck): "stand-in" when it only stands in. */
function tokDeckChips(row) {
  const decks = [];
  for (const use of row.uses || []) {
    const same = decks.find((d) => d.deck === use.deck);
    if (same) { if (use.state !== "differs") same.standIn = false; continue; }
    if (use.state === "in_use") continue;     // the deck would use it, but other decks pack every card
    decks.push({ deck: use.deck, link: use.link, title: use.title, standIn: use.state === "differs" });
  }
  return decks.map((d) => tokDeckChip(d.deck, d.link, d.title, d.standIn));
}

/** A deck as a chip linking to it: its short name (the part before a ":", "Krenko" for "Krenko: Goblin
 * Horde") on one line, cut with an ellipsis if it still doesn't fit; the whole title is its tooltip. */
function tokDeckChip(id, link, title, standIn = false) {
  const full = String(title || "");
  const short = full.split(":")[0].trim() || full;
  return el("a", { class: "chip chip-plain tok-deck-chip", href: tokHolderHref(id, link),
    title: standIn ? `${full}: stands in for a different token` : `Used by ${full}`,
    "aria-label": standIn ? `${full}, stand-in` : full },
  el("span", { class: "tok-chip-words", text: standIn ? `${short} · stand-in` : short }));
}

/** One token card as a tile: its pictures (the row's printing, or example art with a ribbon saying so), ×N,
 * the printing or details, the decks it serves, and one "Details to check" when there's anything to check.
 * A tap opens its sheet where the visitor may change the tokens (with Zoom for the big picture), else the
 * card viewer over the page's tokens. */
function tokCard(view, row) {
  const { token, example, meta } = tokTileParts(row);
  const unknown = tokFaces(row).some((f) => f.known === false);
  const chips = [
    tokNeedsCheckChip(row) ? status("warn", "Details to check") : null,
    unknown ? status("warn", "Not a Scryfall name") : null,
    (row.shared || []).length ? status("warn", `Too few for ${plural(row.shared.length, "built deck")}`) : null,
    ...tokDeckChips(row)];
  const caption = [`×${row.quantity}`, tokPrinting(row), row.notes || null].filter(Boolean).join(" · ")
    + (example ? " (example art: printing not recorded)" : "");
  const card = tokViewerCard(token, meta, example);
  // Editable tiles open the sheet (whose Zoom opens the viewer); read-only ones open the viewer. Either way
  // the tile is the "tokens" group's member, showing the big pictures.
  const tile = tokenTile(token, { qty: row.quantity, meta, chips,
    unrecorded: example ? "Example art" : null,
    label: view.canEdit ? `Edit ${tokLabel(row)}` : `${tokLabel(row)} ×${row.quantity}`,
    onclick: view.canEdit ? () => editToken(view, row) : (e) => openCard(card, e.currentTarget) });
  tile.setAttribute("data-key", row.key);
  const open = tile.querySelector(".card-tile-open");
  if (open) {
    open.setAttribute("class", `${open.getAttribute("class")} tok-mutate`);
    open.setAttribute("data-focus", `edit-${row.key}`);
    if (!view.canEdit) open.setAttribute("aria-haspopup", "dialog");
    viewerItem(open, card, "tokens", caption);
  }
  if (example) tokRibbonOnLoad(tile);
  return tile;
}

/** The "Example art" ribbon shows only once the example picture has loaded: a tile still showing its words
 * (loading, or a picture that failed) has no art to label. */
function tokRibbonOnLoad(tile) {
  const ribbon = tile.querySelector(".card-tile-ribbon");
  const img = tile.querySelector(".card-tile-img");
  if (!ribbon) return;
  if (!img) { ribbon.remove(); return; }
  if (img.complete && img.naturalWidth > 0) return;
  ribbon.hidden = true;
  img.addEventListener("load", () => { ribbon.hidden = false; });
}

/** A token's picture at the viewer's size: the normal image of the same /img/ printing as its small one. */
function tokNormal(url) {
  return typeof url === "string" && url.startsWith("/img/") ? url.replace(/\/small$/, "/normal") : null;
}

/** The card the viewer shows for a token: the normal pictures (the small ones while they load) and, for
 * example art, "Example art · " before its name, which the viewer shows over the picture on a phone too,
 * so it is never taken for the card's own printing. */
function tokViewerCard(token, meta, example = false) {
  const local = (url) => (typeof url === "string" && url.startsWith("/img/") ? url : null);
  const front = local(token.img), back = local(token.back_img);
  const name = token.back ? `${token.front} // ${token.back}` : token.front;
  // The label goes first, so a phone's narrow title row still shows it when the name is cut short.
  const tag = example ? "Example art · " : "";
  return { name: `${tag}${name}`, mana_cost: "", oracle_text: null,
    type_line: example ? ["Example art: printing not recorded", meta].filter(Boolean).join(" · ") : meta || "Token",
    img: tokNormal(front), img_small: front,
    faces: token.back ? [{ name: `${tag}${token.front}`, type_line: "Front", img: tokNormal(front), img_small: front },
      { name: `${tag}${token.back}`, type_line: "Back", img: tokNormal(back), img_small: back }] : null };
}

/** "Tokens your decks make that you don't have": the ones nobody has (Missing) and the ones on order (On the
 * way), each a small tile with the decks that make it. At home a stand-in is fine, so these aren't for the
 * shopping list. */
function tokMissingPanel(data, space = HOME_SPACE) {
  const missing = data.missing || [];
  if (!missing.length) return null;
  const tile = (item, words) => {
    const card = tokViewerCard({ front: item.name, img: item.image }, words || "Token");
    const node = tokenTile({ front: item.name, img: item.image }, {
      meta: words, onclick: (e) => openCard(card, e.currentTarget),
      chips: (item.decks || []).map((d) => tokDeckChip(d.id, d.link, d.title)) });
    const open = node.querySelector(".card-tile-open");
    if (open) { open.setAttribute("aria-haspopup", "dialog"); viewerItem(open, card, "tokens-missing", words); }
    return node;
  };
  const group = (items, title, words) => items.length ? el("div", { class: "tok-missing-group" },
    el("h3", { text: `${title} (${items.length})` }),
    el("div", { class: "card-tiles tok-missing-tiles" }, items.map((item) => tile(item, words(item))))) : null;
  return el("section", { class: "panel tok-missing", "aria-labelledby": "tok-missing-title" },
    el("h2", { id: "tok-missing-title", text: "Tokens your decks make that you don't have" }),
    el("p", { class: "sub", text: space === HOME_SPACE
      ? "A stand-in is fine for casual games, so these aren't on the shopping list."
      : "A stand-in is fine for casual games." }),
    group(missing.filter((i) => i.state !== "incoming"), "Missing", () => null),
    group(missing.filter((i) => i.state === "incoming"), "On the way",
      (item) => item.on_the_way ? `${item.on_the_way} on the way` : "On the way"));
}

/** Token cards on order: read only here; each order is received from its receipt page. */
function tokIncomingPanel(data) {
  const incoming = data.incoming || [];
  if (!incoming.length) return null;
  // On a phone it's folded to its heading, so the token cards themselves aren't two screens down.
  const wide = !window.matchMedia || window.matchMedia("(min-width: 600px)").matches;
  return el("details", { class: "panel tok-incoming", open: wide || null },
    el("summary", {}, el("h2", { id: "tok-incoming-title", text: `Token orders on the way (${incoming.length})` })),
    el("ul", { class: "tok-incoming-list" }, incoming.map((order) => el("li", {},
      el("div", { class: "tok-incoming-head" },
        el("span", {}, el("b", { text: plural(order.cards, "card") }), ` · order ${order.order}`),
        el("a", { class: "btn", href: `#/receipt?order=${encodeURIComponent(order.order)}`,
          text: mayDo("receipts") ? "Receive this order" : "Order details" })),
      (order.rows || []).length ? el("details", {}, el("summary", { text: "What's in it" }),
        el("ul", {}, order.rows.map((row) => el("li", {
          text: `${tokLabel(row)} ×${row.quantity}` + [row.front_details, row.back_details].filter(Boolean).map((d) => ` (${d})`).join("") })))) : null))));
}

function setTokensBusy(view, busy) {
  view.busy = busy;
  view.root.setAttribute("aria-busy", String(busy));
  for (const control of view.root.querySelectorAll(".tok-mutate")) control.disabled = busy;
}

/** Where the focus goes when a row's Edit or Remove button had it and the list is replaced by data: the
 * same button of the same row (row keys are places in the sorted file, so they move), or the add button
 * when that row is gone. undefined when no row's button had it. */
function tokFollowFocus(view, data) {
  const active = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.focus : null;
  const match = /^(edit|remove)-(.+)$/.exec(active || "");
  if (!match) return undefined;
  const old = (view.data.rows || []).find((r) => r.key === match[2]);
  const now = old && (data.rows || []).find((r) => tokSameRow(tokBase(r), tokBase(old)));
  return now ? `${match[1]}-${now.key}` : "add";
}

/** Show a new answer's list: the page drawn again, and what happened said (and toasted). focus: the
 * data-focus to move to (left out: the focused row's button follows its row). */
function tokShow(view, data, message, warnings, focus) {
  if (!data) {                        // saved, but the list couldn't be shown again: keep the old one (its
    setTokensBusy(view, false);       // warning says to reload; a write from it meets a conflict and re-applies)
    clear(view.message);
    if (message) {
      view.message.append(el("p", { text: message }));
      toast(message);
    }
    add(view.message, [warningsBox(warnings, "Worth checking")]);
    return;
  }
  if (focus === undefined) focus = tokFollowFocus(view, data);
  view.data = data;
  view.busy = false;
  state.library = null;               // the library's token chips come from the same list
  updateTokens(view, focus);
  clear(view.message);
  if (message) {
    view.message.append(el("p", { text: message }));
    toast(message);
  }
  add(view.message, [warningsBox(warnings, "Worth checking")]);
}

async function refreshTokens(view) {
  if (!tokensActive(view) || view.busy) return;
  const seq = ++view.seq;
  setTokensBusy(view, true);
  try {
    const data = await api(tokPath(view.space));
    if (!tokensActive(view) || seq !== view.seq) return;
    tokShow(view, data, "The tokens list is up to date.");
  } catch (error) {
    if (tokensActive(view)) clear(view.message).append(loadFailed("The latest tokens list", error, () => refreshTokens(view)));
  } finally {
    if (tokensActive(view)) setTokensBusy(view, false);
  }
}

function addToken(view) {
  if (!tokensActive(view) || view.busy || !view.canEdit) return;
  openTokenSheet({ sha256: view.data.sha256, faceNames: view.data.face_names,
    keywords: view.data.keywords, space: view.space, ...tokSheetHooks(view) });
}

function editToken(view, row) {
  if (!tokensActive(view) || view.busy || !view.canEdit) return;
  openTokenSheet({ row, rows: view.data.rows, sha256: view.data.sha256, faceNames: view.data.face_names,
    keywords: view.data.keywords, space: view.space, ...tokSheetHooks(view),
    onRemove: () => removeToken(view, row),
    onZoom: () => {
      const open = view.root.querySelector(`[data-key="${row.key}"] .card-tile-open`);
      const group = open && viewerGroup(open);
      if (group) openCardViewer(group.items, group.index, { trigger: open });
    } });
}

/** What a sheet opened from the page does with its answer, or with the latest list after a conflict. */
function tokSheetHooks(view) {
  return {
    // The saved row's Edit button by its place in the new file (answer.index), not the old place.
    onSaved: (answer, words) => {
      if (!tokensActive(view)) return;
      const saved = Number.isInteger(answer.index) ? ((answer.data && answer.data.rows) || [])
        .find((r) => (r.index ?? Number(String(r.key).slice(1))) === answer.index) : null;
      tokShow(view, answer.data, words, answer.warnings, saved ? `edit-${saved.key}` : undefined);
    },
    onLatest: (latest) => { if (tokensActive(view)) tokShow(view, latest, "This is the tokens list as it is now."); },
  };
}

/** Ask before removing a row, with an optional reason (it goes into the change history). Resolves with
 * {reason} or null. */
function askRemoveToken(row, title) {
  return new Promise((resolve) => {
    const sheet = openSheet(title || `Remove ${tokLabel(row)} ×${row.quantity}?`,
      { onClose: (result) => resolve(result == null ? null : result) });
    const reason = el("input", { id: `tok-reason-${sheet.heading.id}`, type: "text", maxlength: 200, autocomplete: "off",
      placeholder: "e.g. lost, traded, damaged" });
    sheet.body.append(
      el("p", { text: `Remove ${tokLabel(row)} ×${row.quantity}? For a partial loss, use Edit to lower the quantity.` }),
      el("label", { class: "field tok-reason", for: reason.id }, el("span", { text: "Reason (optional)" }), reason));
    sheetActions(sheet, [
      { text: "Remove", kind: "danger", value: "remove", onclick: () => sheet.close({ reason: reason.value.trim() }) },
      { text: "Keep it", value: "keep", onclick: () => sheet.close(null) }]);
  });
}

async function removeToken(view, row) {
  if (!tokensActive(view) || view.busy) return;
  const choice = await askRemoveToken(row);
  if (!choice || !tokensActive(view) || view.busy) return;
  let sha = view.data.sha256;
  let current = row;
  let base = tokBase(row);
  let label = tokLabel(row);
  for (;;) {
    const seq = ++view.seq;
    setTokensBusy(view, true);
    clear(view.message).append(loadingBox(`Removing ${label}…`));
    try {
      const body = { sha256: sha, action: "remove", base };
      if (choice.reason) body.reason = choice.reason;
      const answer = await apiWrite("/api/tokens/save", tokBody(view, body));
      if (!tokensActive(view) || seq !== view.seq) return;
      tokShow(view, answer.data, `${label} removed.`, answer.warnings, "add");
      return;
    } catch (error) {
      if (!tokensActive(view) || seq !== view.seq) return;
      setTokensBusy(view, false);
      const latest = error.data && error.data.latest;
      if (error.status !== 409 || !latest) {
        clear(view.message).append(el("div", { class: "box box-crit" }, el("p", { text: error.message })));
        toast(error.message);
        return;
      }
      // Only a row that's really gone is "Already removed": one changed meanwhile is still there.
      const where = tokLocate(latest.rows, base, error.data.conflict, view.data.rows);
      if (where.state === "gone") {
        tokShow(view, latest, "Already removed.", null, "add");
        return;
      }
      if (where.state === "unsure") {
        tokShow(view, latest, `${label} was changed since you opened the list, so nothing was removed. `
          + "Find it in the list as it is now and remove it from there.", null, "add");
        return;
      }
      clear(view.message);
      const changed = where.state === "changed";
      const target = where.row;
      const again = await ask(tokConflictTitle(error.data.conflict), changed
        ? [error.message, `${label} ×${current.quantity} was changed since you opened the list: ${tokChangedWords(base, tokBase(target))}.`,
          "Nothing was removed yet."]
        : [error.message, "Nothing was removed yet."],
      [{ text: changed ? `Remove ${tokLabel(target)} ×${target.quantity} as it is now` : "Remove it from the latest list",
        kind: "primary", value: "again" }, { text: "Keep it", value: null }]);
      if (!tokensActive(view)) return;
      if (again !== "again") { tokShow(view, latest, ""); return; }
      view.data = latest;
      sha = latest.sha256;
      current = target;
      base = tokBase(target);
      label = tokLabel(target);
    }
  }
}
