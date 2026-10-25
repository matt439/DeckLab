/* Deck Lab's page: card symbols ({G}, {2/W}, {T}, ...) as Scryfall's own pictures, served and cached by
Deck Lab's /sym/<code>.svg route (lib/api/symbols.py). Used by mana costs (deck.js manaCost), rules text
and prose (renderSymbols), and the card viewer (card-viewer.js).

Every picture keeps words for screen readers: in a cost, the cost's own aria-label says them; in text, each
symbol's alt does ("{T}" reads "tap"). When a symbol's picture can't load (offline before it was ever
cached), it's swapped for deck.js's lettered circle (pip), so a cost never goes blank.

Loaded after core.js; nothing runs at load.
*/
"use strict";

// What a symbol is called, for those that aren't mana of a colour or a number (deck.js symbolWords does those).
const SYMBOL_WORDS = {
  T: "tap", Q: "untap", E: "energy", P: "Phyrexian", S: "snow", X: "X", Y: "Y", Z: "Z", A: "acorn",
  TK: "ticket", PW: "planeswalker", CHAOS: "chaos", HALF: "half a generic mana", INFINITY: "infinite generic mana",
};
// Codes whose file name isn't the symbol's own characters.
const SYMBOL_FILES = { "½": "HALF", "∞": "INFINITY" };

/** The name of Scryfall's file for a symbol written without braces ("W/U" -> "WU", "2/W" -> "2W", "T" ->
 * "T", "½" -> "HALF"), or null for something that can't be one. */
function symbolCode(symbol) {
  const raw = String(symbol || "").trim().toUpperCase();
  const code = SYMBOL_FILES[raw] || raw.replace(/\//g, "");
  return /^[A-Z0-9]{1,12}$/.test(code) ? code : null;
}

/** A symbol's words for a screen reader: "tap", "green", "2 generic", "white or blue". */
function symbolAlt(symbol) {
  const code = symbolCode(symbol);
  return (code && SYMBOL_WORDS[code]) || symbolWords(String(symbol));
}

/** One symbol's picture. small: the smaller size, for tight rows. alt: its words, or "" when something
 * around it already says them (a cost's aria-label). A picture that fails to load becomes a lettered circle. */
function symbolImg(symbol, { small = false, alt = null } = {}) {
  const code = symbolCode(symbol);
  if (!code) return pip(symbol, small);
  const words = alt == null ? symbolAlt(symbol) : alt;
  const img = el("img", { class: "sym" + (small ? " sym-small" : ""), src: `/sym/${code}.svg`, alt: words,
    "aria-hidden": words ? null : "true", decoding: "async", draggable: "false",
    onerror: () => {
      const stand = pip(symbol, small);
      if (words) { stand.removeAttribute("aria-hidden"); stand.setAttribute("role", "img"); stand.setAttribute("aria-label", words); }
      img.replaceWith(stand);
    } });
  return img;
}

/** Text with {…} symbols in it (rules text, guide prose, a cost) as a list of parts for add() or el():
 * strings as they are, and each symbol as its picture with its words as alt. "{T}: Add {G}." -> ["",
 * <img alt="tap">, ": Add ", <img alt="green">, "."]. Braces that don't hold a symbol stay as written. */
function renderSymbols(text, opts = {}) {
  const parts = [];
  const source = String(text == null ? "" : text);
  let last = 0;
  for (const match of source.matchAll(/\{([^{}]{1,12})\}/g)) {
    if (!symbolCode(match[1])) continue;
    parts.push(source.slice(last, match.index), symbolImg(match[1], opts));
    last = match.index + match[0].length;
  }
  parts.push(source.slice(last));
  return parts.filter((p) => p !== "");
}

/** Rules text as paragraphs (one per line), its symbols drawn and its reminder text (in brackets) in italics. */
function oracleParagraphs(text, cls = "oracle") {
  return String(text || "").split("\n").filter((line) => line.trim()).map((line) => el("p", { class: cls },
    line.split(/(\([^()]*\))/).map((piece) => (/^\(.*\)$/.test(piece)
      ? el("i", { class: "reminder" }, renderSymbols(piece)) : renderSymbols(piece)))));
}
