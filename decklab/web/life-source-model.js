/* New two-player counters only: v2 separates actual commander sources and retains selectors.
 * Depends on play-pods.js and pod-life-model.js pure primitives. Never converts a kept v1 game. */
"use strict";

function lifeSourceIsCommander(list) {
  return !!list && (Array.isArray(list.sections?.Commander) && list.sections.Commander.length > 0 ||
    typeof list.id === "string" && /(^|\/)commander\//.test(list.id));
}
function lifeSourceSelector(list) {
  if (!podLifeObject(list, ["id", "version", "sha256", "title"]) || !podText(list.title, 500)) return false;
  const first = typeof list.id === "string" ? list.id.split("/")[0] : null;
  const space = ["casual", "commander", "product", "pairing"].includes(first) ? "home" : first;
  return podLifeDeck({ id: list.id, version: list.version, sha256: list.sha256 }, space);
}
/** Commander names are literal lines, never split on a comma or a double-face separator. */
function lifeSourceSources(list) {
  if (!list || list.sections != null && (typeof list.sections !== "object" || Array.isArray(list.sections))) return null;
  const lines = list.sections?.Commander;
  if (lines !== undefined && !podLifeArray(lines, 0, 2)) return null;
  if (lines?.length) {
    if (!lines.every(line => line && typeof line === "object" && !Array.isArray(line) &&
      podText(line.name, 300) && (line.qty === undefined || line.qty === 1))) return null;
    return lines.map((line, index) => ({ source_id: `c${index + 1}`, label: line.name }));
  }
  return lifeSourceIsCommander(list) ? [{ source_id: "c1", label: "Commander 1" }] : [];
}
function lifeSourceStoredSources(sources) {
  return podLifeArray(sources, 0, 2) && sources.every((source, index) =>
    podLifeObject(source, ["source_id", "label"]) && source.source_id === `c${index + 1}` && podText(source.label, 300));
}
function lifeSourceNewError(input, now = Date.now()) {
  try {
    if (!podLifeObject(input, ["profile", "space", "session_id", "date", "choices"]) ||
        !podLifeInteger(now, 0, Number.MAX_SAFE_INTEGER - 86400000) || !podLifeProfile(input.profile) ||
        !(input.space === "home" || input.space === input.profile) || !podLifeSession(input.session_id) ||
        !podLifeDate(input.date, now) || !podLifeArray(input.choices, 2, 2))
      return "Check the two-player counter's people, date and local session.";
    for (const choice of input.choices) {
      if (!podLifeObject(choice, ["list", "name"]) || !podText(choice.name, 80) || !choice.list ||
          !lifeSourceSelector({ id: choice.list.id, version: choice.list.version, sha256: choice.list.sha256, title: choice.list.title }))
        return "Choose two valid saved lists and player names.";
      if (Array.isArray(choice.list.sections?.Commander) && choice.list.sections.Commander.length > 2)
        return "A list can track at most two commander sources.";
      if (lifeSourceSources(choice.list) === null) return "Choose at most two named, single-card commander sources per list.";
    }
    return null;
  } catch (_) { return "Check the two-player counter's people, date and local session."; }
}
function lifeSourceNewGame(input, now = Date.now()) {
  if (lifeSourceNewError(input, now)) return null;
  const players = input.choices.map((choice, index) => ({ seat_id: index ? "b" : "a", name: choice.name,
    list: { id: choice.list.id, version: choice.list.version, sha256: choice.list.sha256, title: choice.list.title },
    sources: lifeSourceSources(choice.list) }));
  const commander = players.some(player => player.sources.length > 0);
  return { v: 2, profile: input.profile, space: input.space, session_id: input.session_id,
    started: now, updated: now, date: input.date, commander, poison: false, ended: null,
    players: players.map(player => ({ ...player, life: commander ? 40 : 20, poison: 0,
      damage: players.flatMap(source => source.sources.map(card =>
        ({ seat_id: source.seat_id, source_id: card.source_id, value: 0 }))) })) };
}
function lifeSourceOutWhy(game, seatId) {
  const player = game?.players?.find(row => row.seat_id === seatId);
  if (!player) return "";
  if (player.life <= 0) return "life";
  if (game.poison && player.poison >= 10) return "poison";
  if (player.damage.some(entry => entry.value >= 21)) return "commander";
  return "";
}
function lifeSourceValid(game, owner, now = Date.now()) {
  try {
    if (!podLifeObject(game, ["v", "profile", "space", "session_id", "started", "updated", "date", "commander", "poison", "ended", "players"]) ||
        game.v !== 2 || !podLifeProfile(game.profile) || game.profile !== owner?.profile || game.space !== owner?.space ||
        !(game.space === "home" || game.space === game.profile) || !podLifeSession(game.session_id) ||
        !podLifeInteger(now, 0, Number.MAX_SAFE_INTEGER - 86400000) || !podLifeTime(game.started, now) ||
        !podLifeTime(game.updated, now) || game.updated < game.started || now - game.started >= POD_LIFE_KEEP_MS ||
        !podLifeDate(game.date, now) || typeof game.commander !== "boolean" || typeof game.poison !== "boolean" ||
        !podLifeArray(game.players, 2, 2)) return false;
    for (const [index, player] of game.players.entries()) {
      if (!podLifeObject(player, ["seat_id", "name", "life", "poison", "list", "sources", "damage"]) ||
          player.seat_id !== (index ? "b" : "a") || !podText(player.name, 80) || !lifeSourceSelector(player.list) ||
          !lifeSourceStoredSources(player.sources) || !podLifeInteger(player.life, -999, 999) ||
          !podLifeInteger(player.poison, 0, 99) || !podLifeArray(player.damage, 0, 4)) return false;
      const expected = game.players.flatMap(source => source.sources.map(card => `${source.seat_id}/${card.source_id}`));
      if (player.damage.length !== expected.length || new Set(player.damage.map(entry => `${entry?.seat_id}/${entry?.source_id}`)).size !== expected.length ||
          !player.damage.every(entry => podLifeObject(entry, ["seat_id", "source_id", "value"]) &&
            expected.includes(`${entry.seat_id}/${entry.source_id}`) && podLifeInteger(entry.value, 0, 99))) return false;
    }
    if (game.commander !== game.players.some(player => player.sources.length > 0)) return false;
    const out = game.players.map(player => lifeSourceOutWhy(game, player.seat_id));
    if (game.ended === null) return out.every(why => !why);
    if (!podLifeObject(game.ended, ["result", "why", "at"]) || !["a", "b", "draw"].includes(game.ended.result) ||
        !["life", "poison", "commander", "conceded", "chosen"].includes(game.ended.why) ||
        !podLifeTime(game.ended.at, game.updated) || game.ended.at < game.started) return false;
    if (["chosen", "conceded"].includes(game.ended.why))
      return out.every(why => !why) && (game.ended.why !== "conceded" || game.ended.result !== "draw");
    // A single-seat change cannot eliminate both players. Enabling poison can.
    if (game.ended.result === "draw") return game.ended.why === "poison" && out.every(why => why === "poison");
    const loser = game.ended.result === "a" ? 1 : 0;
    return out[loser] === game.ended.why && !out[1 - loser];
  } catch (_) { return false; }
}
function lifeSourceMutable(game, now) {
  return lifeSourceValid(game, { profile: game?.profile, space: game?.space }, now) && now >= game.updated && !game.ended;
}
function lifeSourceFinish(game, now) {
  game.updated = now;
  const out = game.players.map(player => lifeSourceOutWhy(game, player.seat_id));
  if (out.some(Boolean)) game.ended = { result: out.every(Boolean) ? "draw" : out[0] ? "b" : "a",
    why: out.find(Boolean), at: now };
}
function lifeSourceChange(game, seatId, field, delta, source = null, now = Date.now()) {
  if (!lifeSourceMutable(game, now) || !Number.isSafeInteger(delta) || !delta) return false;
  const player = game.players.find(row => row.seat_id === seatId);
  if (!player) return false;
  if (["life", "poison"].includes(field) && source === null) {
    const next = Math.max(field === "life" ? -999 : 0, Math.min(field === "life" ? 999 : 99, player[field] + delta));
    if (next === player[field]) return false;
    player[field] = next;
  } else if (field === "commander" && podLifeObject(source, ["seat_id", "source_id"])) {
    const entry = player.damage.find(row => row.seat_id === source.seat_id && row.source_id === source.source_id);
    if (!entry) return false;
    const before = entry.value, next = Math.max(0, Math.min(99, before + delta));
    if (before === next) return false;
    entry.value = next;
    player.life = Math.max(-999, Math.min(999, player.life - (next - before)));
  } else return false;
  lifeSourceFinish(game, now);
  return true;
}
function lifeSourceEnd(game, result, now = Date.now()) {
  if (!lifeSourceMutable(game, now) || !["a", "b", "draw"].includes(result)) return false;
  game.updated = now;
  game.ended = { result, why: "chosen", at: now };
  return true;
}
function lifeSourceConcede(game, seatId, now = Date.now()) {
  if (!lifeSourceMutable(game, now) || !["a", "b"].includes(seatId)) return false;
  game.updated = now;
  game.ended = { result: seatId === "a" ? "b" : "a", why: "conceded", at: now };
  return true;
}
function lifeSourcePoison(game, enabled, now = Date.now()) {
  if (!lifeSourceMutable(game, now) || typeof enabled !== "boolean" || enabled === game.poison) return false;
  game.poison = enabled;
  lifeSourceFinish(game, now);
  return true;
}
/** Same selectors and literal sources again; never reconstruct from today's lists or a v1 aggregate. */
function lifeSourceAgain(game, sessionId, now = Date.now()) {
  if (!lifeSourceValid(game, { profile: game?.profile, space: game?.space }, now) || !podLifeSession(sessionId) || sessionId === game.session_id) return null;
  const next = podLifeClone(game);
  Object.assign(next, { session_id: sessionId, started: now, updated: now, poison: false, ended: null });
  for (const player of next.players) {
    player.life = next.commander ? 40 : 20;
    player.poison = 0;
    for (const entry of player.damage) entry.value = 0;
  }
  return next;
}
function lifeSourceUndo(game, previous, now = Date.now()) {
  const owner = { profile: game?.profile, space: game?.space };
  if (!lifeSourceValid(game, owner, now) || !lifeSourceValid(previous, owner, now) || game.session_id !== previous.session_id ||
      game.started !== previous.started || game.date !== previous.date || game.commander !== previous.commander ||
      previous.updated > game.updated || now < game.updated) return false;
  const binding = packet => JSON.stringify(packet.players.map(player =>
    ({ seat_id: player.seat_id, name: player.name, list: player.list, sources: player.sources })));
  if (binding(game) !== binding(previous)) return false;
  Object.assign(game, podLifeClone(previous), { updated: now });
  return true;
}
