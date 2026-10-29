/* Pure Commander-pod counter model. Depends only on play-pods.js's text/date/SHA helpers.
 * No DOM, storage or requests: callers own persistence, undo snapshots and current-catalog proof. */
"use strict";

const POD_LIFE_KEEP_MS = 2 * 24 * 60 * 60 * 1000;
const POD_LIFE_PACKET_KEYS = ["v", "profile", "space", "session_id", "started", "updated", "date", "notes", "poison", "ended", "seats"];

function podLifeObject(value, keys) {
  return !!value && typeof value === "object" && !Array.isArray(value) &&
    [Object.prototype, null].includes(Object.getPrototypeOf(value)) &&
    Reflect.ownKeys(value).length === keys.length && Reflect.ownKeys(value).every(key => keys.includes(key));
}
function podLifeInteger(value, low, high) { return Number.isSafeInteger(value) && value >= low && value <= high; }
function podLifeArray(value, low, high) {
  return Array.isArray(value) && value.length >= low && value.length <= high &&
    Reflect.ownKeys(value).length === value.length + 1 &&
    Array.from({ length: value.length }, (_, index) => String(index)).every(key => Object.hasOwn(value, key));
}
function podLifeProfile(value) { return typeof value === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value) && value.length <= 40; }
function podLifeSession(value) { return typeof value === "string" && /^[a-f0-9]{32}$/.test(value); }
function podLifeTime(value, now) { return podLifeInteger(value, 0, now); }
function podLifeDate(value, now) {
  return podDate(value) && value <= new Date(now + 14 * 60 * 60 * 1000).toISOString().slice(0, 10);
}
function podLifeDeck(value, space) {
  if (!podLifeObject(value, ["id", "version", "sha256"]) || !podText(value.id, 200) ||
      !["target", "owned"].includes(value.version) || !podSha(value.sha256)) return false;
  const parts = value.id.split("/"), home = ["casual", "commander", "product", "pairing"].includes(parts[0]);
  const owner = home ? "home" : parts[0], kind = home ? parts[0] : parts[1], names = parts.slice(home ? 1 : 2);
  return owner === space && (home || space !== "home" && podLifeProfile(owner) && ["casual", "commander"].includes(kind)) &&
    names.length >= 1 && names.length <= (home && kind === "product" ? 2 : 1) &&
    names.every(name => !!name && !name.startsWith(".") && !/[\\:\u0000-\u001f\u007f]/.test(name));
}
function podLifeSources(sources) {
  return podLifeArray(sources, 1, 2) &&
    sources.every((source, index) => podLifeObject(source, ["source_id", "label"]) &&
      source.source_id === `c${index + 1}` && podText(source.label, 300));
}
function podLifeSeatChoice(seat, space) {
  const keys = ["seat_id", "type", "player", "sources", ...(seat?.type === "deck" ? ["deck", "title"] : ["commander"])];
  return podLifeObject(seat, keys) && typeof seat.seat_id === "string" && /^s[1-4]$/.test(seat.seat_id) &&
    podText(seat.player, 80) && podLifeSources(seat.sources) &&
    (seat.type === "deck" ? podLifeDeck(seat.deck, space) && podText(seat.title, 500)
      : seat.type === "external" && podText(seat.commander, 300, true));
}
function podLifeChoice(seat) {
  return { seat_id: seat.seat_id, type: seat.type, player: seat.player,
    ...(seat.type === "deck" ? { deck: { ...seat.deck }, title: seat.title } : { commander: seat.commander }),
    sources: seat.sources.map(source => ({ ...source })) };
}
function podLifeClone(value) { return JSON.parse(JSON.stringify(value)); }

/** Fixed constructor error, never an echoed packet value. Blank source labels get numbered names. */
function podLifeNewError(input, now = Date.now()) {
  try {
    if (!podLifeObject(input, ["profile", "space", "session_id", "date", "notes", "seats"]) ||
        !podLifeInteger(now, 0, Number.MAX_SAFE_INTEGER - 86400000) || !podLifeProfile(input.profile) ||
        !(input.space === "home" || input.space === input.profile) || !podLifeSession(input.session_id) ||
        !podLifeDate(input.date, now) || !podNotes(input.notes) ||
        !podLifeArray(input.seats, 3, 4)) return "Check the pod counter's players, date and local session.";
    if (input.seats.some(seat => Array.isArray(seat?.sources) && seat.sources.length > 2))
      return "A seat can track at most two commander sources.";
    if (!input.seats.every(seat => podLifeObject(seat, ["seat_id", "type", "player", "sources",
      ...(seat?.type === "deck" ? ["deck", "title"] : ["commander"])]) &&
      (seat.type !== "deck" || podLifeDeck(seat.deck, input.space)) && podLifeArray(seat.sources, 1, 2) &&
      seat.sources.every(source => podLifeObject(source, ["source_id", "label"]))))
      return "Choose valid pod players and commander sources.";
    const choices = input.seats.map(seat => ({ ...seat, sources: seat.sources?.map((source, i) =>
      ({ ...source, label: source.label === "" ? `Commander ${i + 1}` : source.label })) }));
    if (new Set(choices.map(seat => seat.seat_id)).size !== choices.length ||
        !choices.every(seat => podLifeSeatChoice(seat, input.space)) || !choices.some(seat => seat.type === "deck"))
      return "Choose three or four players, with a saved deck from your collection and one or two commander sources each.";
    return null;
  } catch (_) { return "Check the pod counter's players, date and local session."; }
}

/** Input has selector-only seats; display titles and commander names remain literal text. */
function podLifeNew(input, now = Date.now()) {
  if (podLifeNewError(input, now)) return null;
  const seats = input.seats.map(seat => podLifeChoice({ ...seat, sources: seat.sources.map((source, i) =>
    ({ ...source, label: source.label === "" ? `Commander ${i + 1}` : source.label })) }));
  return { v: 1, profile: input.profile, space: input.space, session_id: input.session_id,
    started: now, updated: now, date: input.date, notes: input.notes, poison: false, ended: null,
    seats: seats.map(seat => ({ ...seat, life: 40, poison: 0, out: null,
      damage: seats.flatMap(other => other.sources.map(source =>
        ({ seat_id: other.seat_id, source_id: source.source_id, value: 0 }))) })) };
}

function podLifeThreshold(game, seat) {
  if (seat.life <= 0) return "life";
  if (game.poison && seat.poison >= 10) return "poison";
  if (seat.damage.some(entry => entry.value >= 21)) return "commander";
  return "";
}
/** A counted seat's explicit or automatic elimination reason, without combining damage sources. */
function podLifeOut(game, seatId) {
  const seat = game?.seats?.find(row => row.seat_id === seatId);
  return seat ? seat.out?.why || podLifeThreshold(game, seat) : "";
}
function podLifeEnded(game) { return game?.ended || null; }

/** Strict local packet validation. Stale selectors remain intact; this grants no recording permission. */
function podLifeValid(game, owner, now = Date.now()) {
  try {
    if (!podLifeObject(game, POD_LIFE_PACKET_KEYS) || game.v !== 1 || !podLifeProfile(game.profile) ||
        game.profile !== owner?.profile || game.space !== owner?.space || !(game.space === "home" || game.space === game.profile) ||
        !podLifeSession(game.session_id) || !podLifeInteger(now, 0, Number.MAX_SAFE_INTEGER - 86400000) ||
        !podLifeTime(game.started, now) || !podLifeTime(game.updated, now) || game.updated < game.started ||
        now - game.started >= POD_LIFE_KEEP_MS || !podLifeDate(game.date, now) || !podNotes(game.notes) ||
        typeof game.poison !== "boolean" || !podLifeArray(game.seats, 3, 4)) return false;
    const ids = new Set(game.seats.map(seat => seat?.seat_id));
    if (ids.size !== game.seats.length || !game.seats.some(seat => seat?.type === "deck")) return false;
    for (const seat of game.seats) {
      const choice = podLifeChoice(seat);
      if (!podLifeSeatChoice(choice, game.space) ||
          !podLifeSources(seat.sources) || seat.type === "deck" && !podLifeDeck(seat.deck, game.space) ||
          !podLifeObject(seat, [...Object.keys(choice), "life", "poison", "out", "damage"]) ||
          !podLifeInteger(seat.life, -999, 999) || !podLifeInteger(seat.poison, 0, 99) || !podLifeArray(seat.damage, 3, 8)) return false;
      const expected = game.seats.flatMap(other => other.sources.map(source => `${other.seat_id}/${source.source_id}`));
      if (seat.damage.length !== expected.length || new Set(seat.damage.map(entry => `${entry?.seat_id}/${entry?.source_id}`)).size !== expected.length ||
          !seat.damage.every(entry => podLifeObject(entry, ["seat_id", "source_id", "value"]) &&
            expected.includes(`${entry.seat_id}/${entry.source_id}`) && podLifeInteger(entry.value, 0, 99))) return false;
      const threshold = podLifeThreshold(game, seat);
      if (seat.out === null) { if (threshold) return false; }
      else if (!podLifeObject(seat.out, ["why", "at"]) || !["life", "poison", "commander", "conceded", "chosen"].includes(seat.out.why) ||
          !podLifeTime(seat.out.at, game.updated) || seat.out.at < game.started ||
          seat.out.why === "life" && seat.life > 0 || seat.out.why === "poison" && seat.poison < 10 ||
          seat.out.why === "commander" && !seat.damage.some(entry => entry.value >= 21)) return false;
    }
    const active = game.seats.filter(seat => seat.out === null);
    if (game.ended === null) return active.length >= 2;
    if (!podLifeObject(game.ended, ["result", "why", "at"]) || !["last", "chosen"].includes(game.ended.why) ||
        !podLifeTime(game.ended.at, game.updated) || game.ended.at < game.started ||
        !(game.ended.result === "draw" || active.some(seat => seat.seat_id === game.ended.result))) return false;
    return game.ended.why === "chosen" || active.length <= 1 && game.ended.result === (active[0]?.seat_id || "draw");
  } catch (_) { return false; }
}

function podLifeMutable(game, now) {
  return podLifeValid(game, { profile: game?.profile, space: game?.space }, now) && now >= game.updated && !game.ended;
}
function podLifeFinish(game, now) {
  game.updated = now;
  for (const seat of game.seats) {
    const why = podLifeThreshold(game, seat);
    if (!seat.out && why) seat.out = { why, at: now };
  }
  const active = game.seats.filter(seat => !seat.out);
  if (active.length <= 1) game.ended = { result: active[0]?.seat_id || "draw", why: "last", at: now };
}

/** field is life/poison/commander; a commander source keeps its original identity even when control changes. */
function podLifeChange(game, seatId, field, delta, source = null, now = Date.now()) {
  if (!podLifeMutable(game, now) || !Number.isSafeInteger(delta) || !delta) return false;
  const seat = game.seats.find(row => row.seat_id === seatId);
  if (!seat || seat.out) return false;
  if (["life", "poison"].includes(field) && source === null) {
    const next = Math.max(field === "life" ? -999 : 0, Math.min(field === "life" ? 999 : 99, seat[field] + delta));
    if (next === seat[field]) return false;
    seat[field] = next;
  } else if (field === "commander" && podLifeObject(source, ["seat_id", "source_id"])) {
    const entry = seat.damage.find(row => row.seat_id === source.seat_id && row.source_id === source.source_id);
    if (!entry) return false;
    const before = entry.value, next = Math.max(0, Math.min(99, before + delta));
    if (next === before) return false;
    entry.value = next;
    seat.life = Math.max(-999, Math.min(999, seat.life - (next - before)));
  } else return false;
  podLifeFinish(game, now);
  return true;
}

function podLifeConcede(game, seatId, now = Date.now()) {
  if (!podLifeMutable(game, now)) return false;
  const seat = game.seats.find(row => row.seat_id === seatId);
  if (!seat || seat.out) return false;
  seat.out = { why: "conceded", at: now };
  podLifeFinish(game, now);
  return true;
}
function podLifeEnd(game, result, now = Date.now()) {
  if (!podLifeMutable(game, now) || !(result === "draw" || game.seats.some(seat => seat.seat_id === result && !seat.out))) return false;
  game.updated = now;
  game.ended = { result, why: "chosen", at: now };
  return true;
}
function podLifePoison(game, enabled, now = Date.now()) {
  if (!podLifeMutable(game, now) || typeof enabled !== "boolean" || enabled === game.poison) return false;
  game.poison = enabled;
  podLifeFinish(game, now);
  return true;
}
function podLifeAddSource(game, seatId, label, now = Date.now()) {
  if (!podLifeMutable(game, now) || !podText(label, 300, true)) return false;
  const seat = game.seats.find(row => row.seat_id === seatId);
  if (!seat || seat.out || seat.type !== "external" || seat.sources.length !== 1) return false;
  seat.sources.push({ source_id: "c2", label: podTrim(label) ? label : "Commander 2" });
  for (const other of game.seats) {
    other.damage.push({ seat_id: seatId, source_id: "c2", value: 0 });
  }
  game.updated = now;
  return true;
}

/** A new local session for the same selector choices; no current catalog is silently substituted. */
function podLifeReset(game, sessionId, now = Date.now()) {
  if (!podLifeValid(game, { profile: game?.profile, space: game?.space }, now) || !podLifeSession(sessionId) || sessionId === game.session_id) return null;
  return podLifeNew({ profile: game.profile, space: game.space, session_id: sessionId,
    date: game.date, notes: game.notes, seats: game.seats.map(podLifeChoice) }, now);
}
function podLifeUndo(game, previous, now = Date.now()) {
  const owner = { profile: game?.profile, space: game?.space };
  if (!podLifeValid(game, owner, now) || !podLifeValid(previous, owner, now) || game.session_id !== previous.session_id ||
      game.started !== previous.started || previous.updated > game.updated || now < game.updated) return false;
  const binding = packet => JSON.stringify(packet.seats.map(seat => ({ ...podLifeChoice(seat), sources: undefined })));
  if (binding(game) !== binding(previous) || game.date !== previous.date || game.notes !== previous.notes) return false;
  if (!previous.seats.every(seat => {
    const sources = game.seats.find(current => current.seat_id === seat.seat_id).sources;
    return seat.sources.length <= sources.length && seat.sources.every(source => sources.some(current =>
      current.source_id === source.source_id && current.label === source.label));
  })) return false;
  Object.assign(game, podLifeClone(previous), { updated: now });
  return true;
}
