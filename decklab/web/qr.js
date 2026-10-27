/* Deck Lab's page: a QR code drawn on the page (E8-S21), with no outside service.

qrMatrix(text) encodes text (as UTF-8 bytes, byte mode) at error correction level M in the smallest of
versions 1 to 10 that holds it (up to 213 bytes), with the mask the standard's penalty rules choose
(ISO/IEC 18004), and returns its modules; qrSvg draws them as one SVG path with the 4-module quiet zone.
Written for Deck Lab after Project Nayuki's QR Code generator (MIT), whose layout steps it follows.
*/
"use strict";

const QR_MAX_VERSION = 10;
// Level M per version: [error correction codewords per block, [[blocks, data codewords per block], ...]].
const QR_BLOCKS_M = [null,
  [10, [[1, 16]]], [16, [[1, 28]]], [26, [[1, 44]]], [18, [[2, 32]]], [24, [[2, 43]]],
  [16, [[4, 27]]], [18, [[4, 31]]], [22, [[2, 38], [2, 39]]], [22, [[3, 36], [2, 37]]],
  [26, [[4, 43], [1, 44]]]];
const QR_ALIGNMENT = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34],
  [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];
const QR_MASKS = [
  (x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
  (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => (x * y) % 2 + (x * y) % 3 === 0,
  (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0, (x, y) => ((x + y) % 2 + (x * y) % 3) % 2 === 0];

/** a × b in GF(256) with the QR code's polynomial (0x11D). */
function qrMultiply(a, b) {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11D);
    z ^= ((b >>> i) & 1) * a;
  }
  return z;
}

/** The Reed-Solomon error correction codewords (ecLength of them) for data (codeword numbers). */
function qrReedSolomon(data, ecLength) {
  const divisor = new Array(ecLength).fill(0);
  divisor[ecLength - 1] = 1;
  let root = 1;
  for (let i = 0; i < ecLength; i++) {
    for (let j = 0; j < ecLength; j++) {
      divisor[j] = qrMultiply(divisor[j], root);
      if (j + 1 < ecLength) divisor[j] ^= divisor[j + 1];
    }
    root = qrMultiply(root, 0x02);
  }
  const result = new Array(ecLength).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift();
    result.push(0);
    divisor.forEach((d, i) => { result[i] ^= qrMultiply(d, factor); });
  }
  return result;
}

/** text's UTF-8 bytes (a lone surrogate as U+FFFD, as TextEncoder does). */
function qrUtf8(text) {
  const bytes = [];
  for (const ch of text) {
    let c = ch.codePointAt(0);
    if (c >= 0xD800 && c <= 0xDFFF) c = 0xFFFD;
    if (c < 0x80) bytes.push(c);
    else if (c < 0x800) bytes.push(0xC0 | (c >> 6), 0x80 | (c & 63));
    else if (c < 0x10000) bytes.push(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    else bytes.push(0xF0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return bytes;
}

function qrDataCodewords(version) {
  return QR_BLOCKS_M[version][1].reduce((n, [blocks, size]) => n + blocks * size, 0);
}

/** The smallest version (1 to QR_MAX_VERSION) whose level M holds bytes in byte mode, or null. */
function qrVersionFor(bytes) {
  for (let v = 1; v <= QR_MAX_VERSION; v++) {
    if (4 + (v < 10 ? 8 : 16) + bytes.length * 8 <= qrDataCodewords(v) * 8) return v;
  }
  return null;
}

/** The codewords of bytes at version: mode, count, the bytes, the terminator and padding, split into the
 * level's blocks with their error correction, interleaved. */
function qrCodewords(bytes, version) {
  const bits = [];
  const put = (value, length) => { for (let i = length - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
  put(0b0100, 4);
  put(bytes.length, version < 10 ? 8 : 16);
  for (const b of bytes) put(b, 8);
  const capacity = qrDataCodewords(version) * 8;
  put(0, Math.min(4, capacity - bits.length));
  put(0, (8 - bits.length % 8) % 8);
  for (let pad = 0xEC; bits.length < capacity; pad ^= 0xEC ^ 0x11) put(pad, 8);
  const data = [];
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((n, b) => (n << 1) | b, 0));
  const [ecLength, groups] = QR_BLOCKS_M[version];
  const blocks = [];
  let at = 0;
  for (const [count, size] of groups) {
    for (let i = 0; i < count; i++, at += size) {
      const part = data.slice(at, at + size);
      blocks.push({data: part, ec: qrReedSolomon(part, ecLength)});
    }
  }
  const out = [];
  const longest = Math.max(...blocks.map((b) => b.data.length));
  for (let i = 0; i < longest; i++) for (const b of blocks) if (i < b.data.length) out.push(b.data[i]);
  for (let i = 0; i < ecLength; i++) for (const b of blocks) out.push(b.ec[i]);
  return out;
}

/** The function patterns of a version: {size, modules, fixed}, rows of booleans (dark) and of whether the
 * module is a function module (finders, timing, alignment, format and version areas). */
function qrFunctionPatterns(version) {
  const size = version * 4 + 17;
  const modules = Array.from({length: size}, () => new Array(size).fill(false));
  const fixed = Array.from({length: size}, () => new Array(size).fill(false));
  const set = (x, y, dark) => { modules[y][x] = dark; fixed[y][x] = true; };
  for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
  for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy, d = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, d !== 2 && d !== 4);
      }
    }
  }
  const places = QR_ALIGNMENT[version], last = places.length - 1;
  places.forEach((cx, i) => places.forEach((cy, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
    for (let dy = -2; dy <= 2; dy++) {
      for (let dx = -2; dx <= 2; dx++) set(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
  }));
  qrFormatBits(modules, fixed, 0);           // reserved now, written again once the mask is chosen
  if (version >= 7) {
    let rem = version;
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
    const bits = (version << 12) | rem;
    for (let i = 0; i < 18; i++) {
      const dark = ((bits >>> i) & 1) === 1, a = size - 11 + i % 3, b = Math.floor(i / 3);
      set(a, b, dark); set(b, a, dark);
    }
  }
  return {size, modules, fixed};
}

/** Write level M's format information for mask (both copies) and the dark module. */
function qrFormatBits(modules, fixed, mask) {
  const size = modules.length;
  const set = (x, y, dark) => { modules[y][x] = dark; fixed[y][x] = true; };
  const data = mask;                         // level M's two bits are 00
  let rem = data;
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
  const bits = ((data << 10) | rem) ^ 0x5412;
  const bit = (i) => ((bits >>> i) & 1) === 1;
  for (let i = 0; i <= 5; i++) set(8, i, bit(i));
  set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
  for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
  for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
  for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
  set(8, size - 8, true);
}

/** Place codewords in the zigzag order over the modules that aren't function modules. */
function qrPlace(modules, fixed, codewords) {
  const size = modules.length;
  let i = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    const upward = ((right + 1) & 2) === 0;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j, y = upward ? size - 1 - vert : vert;
        if (fixed[y][x] || i >= codewords.length * 8) continue;
        modules[y][x] = ((codewords[i >>> 3] >>> (7 - (i & 7))) & 1) === 1;
        i++;
      }
    }
  }
}

/** The standard's penalty score of a finished symbol (rules N1 to N4). */
function qrPenalty(modules) {
  const size = modules.length;
  let score = 0;
  const lines = [];
  for (let i = 0; i < size; i++) lines.push(modules[i], modules.map((row) => row[i]));
  const finder = [true, false, true, true, true, false, true];
  for (const line of lines) {
    let run = 1;
    for (let i = 1; i <= size; i++) {
      if (i < size && line[i] === line[i - 1]) { run++; continue; }
      if (run >= 5) score += 3 + run - 5;
      run = 1;
    }
    for (let i = 0; i + 7 <= size; i++) {
      if (!finder.every((d, k) => line[i + k] === d)) continue;
      const lightFor = (from, to) => { for (let k = from; k < to; k++) if (k >= 0 && k < size && line[k]) return false; return true; };
      if (lightFor(i - 4, i) || lightFor(i + 7, i + 11)) score += 40;
    }
  }
  for (let y = 0; y + 1 < size; y++) {
    for (let x = 0; x + 1 < size; x++) {
      const c = modules[y][x];
      if (c === modules[y][x + 1] && c === modules[y + 1][x] && c === modules[y + 1][x + 1]) score += 3;
    }
  }
  const dark = modules.reduce((n, row) => n + row.filter(Boolean).length, 0), total = size * size;
  score += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
  return score;
}

/** text as a QR code at level M: {version, mask, size, modules} (modules[y][x], true for dark), or null
 * when it's too long for version 10. mask (0 to 7) forces one; otherwise the lowest penalty wins. */
function qrMatrix(text, mask = null) {
  const bytes = qrUtf8(String(text));
  const version = qrVersionFor(bytes);
  if (version === null) return null;
  const codewords = qrCodewords(bytes, version);
  const make = (m) => {
    const {size, modules, fixed} = qrFunctionPatterns(version);
    qrPlace(modules, fixed, codewords);
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fixed[y][x] && QR_MASKS[m](x, y)) modules[y][x] = !modules[y][x];
    qrFormatBits(modules, fixed, m);
    return {version, mask: m, size, modules};
  };
  if (mask !== null) return make(mask);
  let best = null, bestScore = Infinity;
  for (let m = 0; m < 8; m++) {
    const symbol = make(m), score = qrPenalty(symbol.modules);
    if (score < bestScore) { best = symbol; bestScore = score; }
  }
  return best;
}

/** text's QR code as an SVG (one path, black on white, a quiet zone of 4 modules), or null when it's too
 * long. label names it for a screen reader. */
function qrSvg(text, label) {
  const symbol = qrMatrix(text);
  if (!symbol) return null;
  const span = symbol.size + 8;
  const path = [];
  symbol.modules.forEach((row, y) => row.forEach((dark, x) => { if (dark) path.push(`M${x + 4} ${y + 4}h1v1h-1z`); }));
  return svgEl("svg", {class: "qr-code", viewBox: `0 0 ${span} ${span}`, "shape-rendering": "crispEdges",
    role: "img", "aria-label": label || "QR code"},
  svgEl("rect", {width: span, height: span, fill: "#fff"}),
  svgEl("path", {d: path.join(""), fill: "#000"}));
}
