/* The life counter (E4-S26, first slice): a two-player counter for a phone at the table, started from the Game
log's quick record for the two decks and names chosen there. Each player has half the screen (the top half turned
to face the player across the table on a phone held upright): life (20, or 40 when either deck has a Commander)
with big − and + buttons (a tap is 1; held, 5 at a time) and −5 and +5, poison when it's switched on (10 ends the
game) and, in a Commander game, the commander damage taken from the other player (21 ends it; each point is a life
lost too). The bar has the game's time, Poison, End game and Close.

Nothing goes to the server while counting: the game is kept in memory and in localStorage (core.js's local, which
never throws), with the profile that started it, so a refresh or a locked phone doesn't lose it; the Game log
offers Resume. When a player is out, or End game names the winner, the Game log's Record a played game sheet opens
over it with the decks, names and winner filled in, for its usual review and save (only when the viewer may record
a game with one of the decks: /api/play's decks[id].can_record). Saving it ends the counter. */
"use strict";

const LIFE_KEY = "play.lifeCounter";            // localStorage (core.js's local adds the prefix): the game
const LIFE_KEEP_MS = 2 * 24 * 60 * 60 * 1000;   // a counter older than this isn't offered again
const LIFE_HOLD_MS = 500;                       // a − or + held this long changes life by 5, and again each time
const LIFE_OUT = { life: 0, poison: 10, commander: 21 };
let lifeOpen = null;                            // the counter on screen: {dialog, game, data, seats, ...}
let lifeV2Open = null;
const LIFE_SOURCE_KEY = "play.lifeCounter.sources"; // separate from every legacy v1 byte
const lifeV2Completed = new Set();

/** A Commander deck: a Commander section, or a Commander deck's id. */
function lifeIsCommander(list) {
  return !!list && ((((list.sections || {}).Commander) || []).length > 0 || /(^|\/)commander\//.test(list.id || ""));
}

/** A new game for choices [{list, name}, {list, name}] (lists from /api/play), kept for profileId. */
function lifeNewGame(choices, profileId, now = Date.now()) {
  const commander = choices.some((choice) => lifeIsCommander(choice.list));
  const life = commander ? 40 : 20;
  return { v: 1, profile: profileId || null, started: now, commander, poison: false, ended: null,
    players: choices.map((choice) => ({ name: choice.name, life, poison: 0, commander: 0,
      list: { id: choice.list.id, version: choice.list.version, title: choice.list.title } })) };
}

/** The same players and decks again, from the start. */
function lifeAgain(game, now = Date.now()) {
  const life = game.commander ? 40 : 20;
  return { ...game, started: now, ended: null,
    players: game.players.map((p) => ({ ...p, list: { ...p.list }, life, poison: 0, commander: 0 })) };
}

/** Why a player is out ("life", "poison", "commander"), or "". */
function lifeOutWhy(game, player) {
  if (player.life <= LIFE_OUT.life) return "life";
  if (game.poison && player.poison >= LIFE_OUT.poison) return "poison";
  if (game.commander && player.commander >= LIFE_OUT.commander) return "commander";
  return "";
}

/** Changes player i's field ("life", "poison" or "commander") by delta; false once the game has ended. Commander
 * damage is life lost too. The changed player being out ends the game, the other player the winner. */
function lifeChange(game, i, field, delta, now = Date.now()) {
  if (game.ended) return false;
  const player = game.players[i];
  if (field === "life") player.life = Math.max(-999, Math.min(999, player.life + delta));
  else {
    const before = player[field];
    player[field] = Math.max(0, Math.min(99, before + delta));
    if (field === "commander") player.life = Math.max(-999, Math.min(999, player.life - (player[field] - before)));
  }
  const why = lifeOutWhy(game, player);
  if (why) game.ended = { result: i === 0 ? "b" : "a", why, at: now };
  return true;
}

/** End game's choice: result "a", "b" or "draw". */
function lifeEnd(game, result, now = Date.now()) {
  if (!game.ended) game.ended = { result, why: "chosen", at: now };
}

function lifeStore(game) {
  local.set(LIFE_KEY, JSON.stringify(game));
}

/** The kept game this profile may resume on this page, or null: one it started, still under LIFE_KEEP_MS old,
 * whose two lists are still among data.lists (a deck since removed, or one this viewer can't see, drops it). */
function lifeSaved(data, now = Date.now()) {
  let game = null;
  try { game = JSON.parse(local.get(LIFE_KEY) || "null"); } catch (e) { return null; }
  const me = (state.profile && state.profile.id) || null;
  if (!game || typeof game !== "object" || game.v !== 1 || game.profile !== me || !Array.isArray(game.players)
      || game.players.length !== 2 || !(now - game.started < LIFE_KEEP_MS)) return null;
  const sound = (p) => p && p.list && typeof p.name === "string"
    && ["life", "poison", "commander"].every((field) => Number.isFinite(p[field]))
    && (data.lists || []).some((list) => list.id === p.list.id && list.version === p.list.version);
  return game.players.every(sound) ? game : null;
}

/** Whether the viewer may record a game with these decks (the server checks it again on every save). */
function lifeMayRecord(data, game) {
  if (!state.profile) return false;
  if (!data.decks) return true;                       // an older server sent no rights
  return game.players.some((p) => (data.decks[p.list.id] || {}).can_record);
}

/** The Game log's way in: Life counter for the decks chosen (chosen(): [{list, name}, ...]), or Resume. */
function lifeCounterLauncher(data, chosen) {
  if (typeof lifeSourceNewGame === "function") return lifeV2Launcher(data, chosen);
  const box = el("div", { class: "play-counter" });
  const start = event => openLifeCounter(data, lifeNewGame(chosen(), state.profile && state.profile.id), draw,
    { source: event?.currentTarget });
  function draw() {
    const saved = lifeSaved(data);
    clear(box);
    if (!saved) {
      box.append(el("button", { type: "button", class: "btn", text: "Life counter", onclick: start }));
      return;
    }
    add(box, [el("button", { type: "button", class: "btn", text: "Resume life counter",
      onclick: event => openLifeCounter(data, lifeSaved(data) || saved, draw, { resume: true, source: event.currentTarget }) }),
    el("span", { class: "sub", text: saved.players.map((p) => `${p.name} ${p.life}`).join(" · ") }),
    el("button", { type: "button", class: "btn btn-quiet", text: "New life counter", onclick: start })]);
  }
  draw();
  return box;
}

/** "12:05" (or "1:02:05") for a time in milliseconds. */
function lifeClockWords(ms) {
  const all = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(all / 3600), m = Math.floor(all / 60) % 60, s = all % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`;
}

/** The end's words: [who won, why]. */
function lifeEndWords(game) {
  const ended = game.ended;
  if (ended.result === "draw") return ["Draw.", ""];
  const winner = game.players[ended.result === "a" ? 0 : 1], loser = game.players[ended.result === "a" ? 1 : 0];
  const why = ended.why === "life" ? `${loser.name} is at ${loser.life} life.`
    : ended.why === "poison" ? `${loser.name} has ${plural(loser.poison, "poison counter")}.`
      : ended.why === "commander" ? `${loser.name} has taken ${loser.commander} commander damage.` : "";
  return [`${winner.name} won.`, why];
}

/** A − or + button: a tap steps once (step(1)); held, step(5) each LIFE_HOLD_MS until it's let go or step
 * returns false (the game ended). */
function lifePress(button, step, allowed = () => true, revision = () => null, stops = null, open = null) {
  let timer = null, active = false, held = false, expected = null, pointer = null, terminal = null;
  const stop = () => { active = false; clearTimeout(timer); timer = null; terminal = null; pointer = null; };
  const repeat = () => {
    if (!active || !allowed() || revision() !== expected) { stop(); return; }
    held = true; const changed = step(5, false); expected = revision();
    if (changed && open?.game.ended) {
      if (pointer !== null && allowed()) terminal = { pointer, open, game: open.game, generation: open.generation,
        started: open.game.started, result: JSON.stringify(open.game.ended), raw: open.raw };
      active = false; timer = null; return; // the timer records no result; only the matching foreground release may do so
    }
    timer = changed ? setTimeout(repeat, LIFE_HOLD_MS) : null;
  };
  if (stops) stops.add(stop);
  button.addEventListener("pointerdown", event => {
    if (terminal && event.pointerId !== terminal.pointer) stop();
    if (!allowed()) return; held = false; stop(); active = true;
    pointer = Number.isInteger(event.pointerId) ? event.pointerId : null;
    expected = revision();
    try { button.setPointerCapture?.(event.pointerId); } catch (_) { /* capture is optional */ }
    timer = setTimeout(repeat, LIFE_HOLD_MS);
  });
  button.addEventListener("pointerup", event => {
    const token = terminal; stop();
    if (token && event.pointerId === token.pointer && token.open === open && token.game === open.game &&
        token.started === open.game.started && token.generation === open.generation && token.raw === open.raw &&
        token.raw === local.get(LIFE_KEY) && token.result === JSON.stringify(open.game.ended) && lifeLegacyHere(open, button, true, true))
      lifeRecord(open);
  });
  for (const type of ["pointerleave", "pointercancel", "lostpointercapture"]) button.addEventListener(type, stop);
  button.addEventListener("click", () => { if (held) held = false; else if (allowed()) step(1, true); });
  button.addEventListener("contextmenu", (event) => event.preventDefault());    // a long press isn't a menu
}

/** One player's half: name and deck, life with − and +, −5 and +5, poison and commander damage. */
function lifeSeat(open, i) {
  const game = open.game, player = game.players[i];
  const total = el("output", { class: "life-total", "aria-live": "polite", "aria-label": `${player.name}'s life` });
  const big = (sign, words) => {
    const button = el("button", { type: "button", class: "btn life-adjust", "aria-label": `${player.name}: ${words} (hold for 5)` },
      el("span", { class: "life-sign", "aria-hidden": "true", text: sign < 0 ? "−" : "+" }));
    lifePress(button, (n, foreground) => lifeStep(open, i, "life", sign * n, button, foreground), () => lifeLegacyHere(open, button),
      () => open.generation, open.holds, open);
    return button;
  };
  const counter = (field, label) => {
    const value = el("output", { class: "life-small-value", "aria-label": `${player.name}: ${label}` });
    const step = (delta, words) => lifeLegacyButton(open, delta < 0 ? "-" : "+",
      button => lifeStep(open, i, field, delta, button), { "aria-label": `${player.name}: ${words}` });
    const row = el("div", { class: "life-small", role: "group", "aria-label": `${player.name}: ${label}` },
      el("span", { class: "life-small-label", text: label }), step(-1, `1 ${label.toLowerCase()} less`), value,
      step(1, `1 more ${label.toLowerCase()}`));
    return { row, value, field };
  };
  const counters = [counter("poison", "Poison"), ...(game.commander ? [counter("commander", "Commander damage")] : [])];
  const fives = [-5, 5].map(delta => lifeLegacyButton(open, delta < 0 ? "-5" : "+5",
    button => lifeStep(open, i, "life", delta, button), { "aria-label": `${player.name}: ${delta < 0 ? "5 life less" : "5 more life"}` }));
  const node = el("section", { class: `life-seat life-seat-${i}`, "aria-label": player.name },
    el("p", { class: "life-name" }, el("strong", { text: player.name }), el("span", { class: "sub", text: player.list.title })),
    el("div", { class: "life-main" }, big(-1, "1 life less"), total, big(1, "1 more life")),
    el("div", { class: "life-extras" }, fives[0], fives[1], counters.map((c) => c.row)));
  const draw = () => {
    total.textContent = String(player.life);
    for (const c of counters) {
      c.value.textContent = String(player[c.field]);
      if (c.field === "poison") c.row.hidden = !game.poison;
    }
    node.classList.toggle("is-out", !!lifeOutWhy(game, player));
  };
  return { node, draw };
}

/** A change from a button: kept, drawn, and when it ends the game, Record result opened. */
function lifeStep(open, i, field, delta, button = null, foreground = true) {
  if (!lifeLegacyHere(open, button) || !lifeChange(open.game, i, field, delta)) return false;
  open.generation++; lifeLegacyStore(open);
  lifeDraw(open);
  if (open.game.ended && foreground) lifeRecord(open);
  return true;
}

/** Opens the Game log's Record a played game sheet over the counter, filled in from the game (when the viewer
 * may record it). Saving it ends the counter. */
function lifeRecord(open) {
  if (!lifeLegacyHere(open) || !open.mayRecord || !open.game.ended || typeof playGameForm !== "function") return;
  const game = open.game;
  const original = local.get(LIFE_KEY);
  playGameForm(open.data, "", null, { result: game.ended.result,
    sides: game.players.map((p) => ({ id: p.list.id, version: p.list.version, player: p.name })),
    onSaved: () => {
      if (!lifeLegacyHere(open, null, false) || state.profile !== open.originProfile || routeToken !== open.originToken ||
          location.hash !== open.originHash || local.get(LIFE_KEY) !== original) return false;
      local.remove(LIFE_KEY); closeLifeCounter(); return true;
    } });
}

function lifeDraw(open) {
  const game = open.game;
  open.seats.forEach((seat) => seat.draw());
  open.poison.setAttribute("aria-pressed", game.poison ? "true" : "false");
  open.endButton.disabled = !!game.ended;
  for (const button of open.end.querySelectorAll("button")) open.controls.delete(button);
  clear(open.end);
  open.end.hidden = !game.ended && !open.choosing;
  if (game.ended) {
    const [winner, why] = lifeEndWords(game);
    add(open.end, [el("h2", { text: winner }), why ? el("p", { text: why }) : null,
      open.mayRecord ? null : el("p", { class: "sub", text: "You can't record a game with these decks." }),
      el("div", { class: "life-end-actions" },
        open.mayRecord ? lifeLegacyButton(open, "Record result", () => lifeRecord(open), { class: "btn btn-primary" }) : null,
        lifeLegacyButton(open, "Back to the game", () => {
          game.ended = null; open.generation++; lifeLegacyStore(open); lifeDraw(open);
        }, { class: "btn" }),
        lifeLegacyButton(open, "New game", () => openLifeCounter(open.data, lifeAgain(game), open.onClose,
          { source: open.originSource, isCurrent: open.originOwner }))) ]);
  } else if (open.choosing) {
    const pick = (result) => () => {
      open.choosing = false; lifeEnd(game, result); open.generation++; lifeLegacyStore(open); lifeDraw(open); lifeRecord(open);
    };
    add(open.end, [el("h2", { text: "Who won?" }),
      el("div", { class: "life-end-actions" },
        game.players.map((p, i) => lifeLegacyButton(open, `${p.name} won`, pick(i ? "b" : "a"), { class: "btn" })),
        lifeLegacyButton(open, "Draw", pick("draw"), { class: "btn" }),
        lifeLegacyButton(open, "Keep playing", () => {
          open.choosing = false; lifeDraw(open);
        }))]);
  }
  lifeLegacyRegister(open, open.end);
}

function lifeTick(open) {
  clearTimeout(open.timer);
  if (!lifeLegacyHere(open, null, false) || open.blurred || document.visibilityState === "hidden") return;
  const game = open.game;
  open.clock.textContent = lifeClockWords((game.ended ? game.ended.at : Date.now()) - game.started);
  open.timer = setTimeout(() => lifeTick(open), 1000);
}

/** Keeps the phone's screen on while the counter is open, where the browser allows it. A lock that arrives after
 * the counter closed (or another opened) is let go at once, so the screen never stays on behind the Game log. */
async function lifeWake(open) {
  try {
    const generation = open.generation, request = ++open.wakeSeq;
    const current = () => lifeLegacyHere(open) && open.generation === generation && open.wakeSeq === request;
    if (!current() || !navigator.wakeLock) return;
    const wake = await navigator.wakeLock.request("screen");
    if (!current()) { wake.release(); return; }
    if (open.wake && open.wake !== wake) open.wake.release();
    open.wake = wake;
  } catch (e) { /* not allowed here, or already released */ }
}

/** Shows the counter for game, full screen. onClose: called when it closes (the Game log's Resume). */
function openLifeCounter(data, game, onClose = null, options = {}) {
  closeLifeCounter(true);
  const open = { data, game, onClose, choosing: false, mayRecord: lifeMayRecord(data, game), timer: null, wake: null,
    originProfile: state.profile, originToken: routeToken, originHash: location.hash,
    originProfileId: state.profile?.id, originSpace: state.profile?.space === undefined ? "home" : state.profile.space,
    originMain: document.getElementById("main"), originLists: data.lists, originDecks: data.decks,
    originalGame: game, originStarted: game.started, originSource: options.source || null,
    originSourceParent: options.source?.parentNode, originOwner: options.isCurrent || null,
    controls: new Map(), holds: new Set(), generation: 0, wakeSeq: 0, blurred: false };
  open.seats = game.players.map((_, i) => lifeSeat(open, i));
  open.clock = el("span", { class: "life-clock", role: "timer", "aria-label": "Game time" });
  open.poison = lifeLegacyButton(open, "Poison", () => {
    game.poison = !game.poison; open.generation++; lifeLegacyStore(open); lifeDraw(open);
  }, { "aria-pressed": "false" });
  open.endButton = lifeLegacyButton(open, "End game", () => { open.choosing = true; lifeDraw(open); }, { class: "btn" });
  open.end = el("div", { class: "life-end", role: "group", "aria-label": "The game's end", hidden: true });
  const close = lifeLegacyButton(open, "Close", () => closeLifeCounter());
  open.dialog = el("dialog", { class: "life-counter", "aria-label": "Life counter" },
    el("div", { class: "life-inner" }, open.seats[0].node,
      el("div", { class: "life-bar" }, open.clock, open.poison, open.endButton, close), open.seats[1].node),
    open.end);
  open.dialog.addEventListener("close", () => { if (lifeOpen === open) closeLifeCounter(); });
  open.inner = open.dialog.children[0]; open.bar = open.clock.parentNode;
  open.onVisible = () => {
    for (const stop of open.holds) stop();
    if (document.visibilityState === "hidden") {
      open.wakeSeq++; clearTimeout(open.timer); try { open.wake?.release(); } catch (_) { /* already released */ } open.wake = null;
    } else { lifeTick(open); lifeWake(open); }
  };
  document.addEventListener("visibilitychange", open.onVisible);
  open.onBlur = () => {
    open.blurred = true; open.wakeSeq++; clearTimeout(open.timer); for (const stop of open.holds) stop();
    try { open.wake?.release(); } catch (_) { /* already released */ } open.wake = null;
  };
  open.onFocus = () => { open.blurred = false; lifeTick(open); lifeWake(open); };
  for (const type of ["blur", "pagehide"]) window.addEventListener(type, open.onBlur);
  for (const type of ["focus", "pageshow"]) window.addEventListener(type, open.onFocus);
  document.body.append(open.dialog);
  open.dialogParent = open.dialog.parentNode;
  lifeOpen = open;
  if (!options.resume) lifeStore(game);
  open.raw = local.get(LIFE_KEY);
  lifeDraw(open);
  if (typeof open.dialog.showModal === "function") open.dialog.showModal();
  else open.dialog.setAttribute("open", "");
  lifeLegacyRegister(open, open.dialog); lifeTick(open);
  open.entry = typeof pushSheetEntry === "function" ? pushSheetEntry(() => closeLifeCounter()) : null;
  lifeWake(open);
  return open;
}

/** Closes the counter on screen (its game stays kept until it's recorded). quiet: no onClose (another opens). */
function closeLifeCounter(quiet = false) {
  if (lifeV2Open) closeLifeSourceCounter(quiet);
  const open = lifeOpen;
  if (!open) return;
  const notify = !quiet && lifeLegacyHere(open, null, false);
  lifeOpen = null;
  clearTimeout(open.timer);
  for (const stop of open.holds) stop();
  document.removeEventListener("visibilitychange", open.onVisible);
  for (const type of ["blur", "pagehide"]) window.removeEventListener(type, open.onBlur);
  for (const type of ["focus", "pageshow"]) window.removeEventListener(type, open.onFocus);
  try { if (open.wake) open.wake.release(); } catch (e) { /* already released */ }
  if (open.dialog.open) open.dialog.close();
  open.dialog.remove();
  if (typeof releaseSheetEntry === "function") releaseSheetEntry(open.entry);
  if (notify && open.onClose) open.onClose();
}

function lifeLegacyHere(open, button = null, foreground = true, allowDisabled = false) {
  const main = document.getElementById("main");
  try { if (open.originOwner && open.originOwner() !== true) return false; } catch (_) { return false; }
  if (lifeOpen !== open || state.profile !== open.originProfile || routeToken !== open.originToken || location.hash !== open.originHash ||
      state.profile?.id !== open.originProfileId || (state.profile?.space === undefined ? "home" : state.profile.space) !== open.originSpace ||
      main !== open.originMain || !main?.isConnected || open.data.lists !== open.originLists || open.data.decks !== open.originDecks ||
      open.game !== open.originalGame || open.game.started !== open.originStarted || local.get(LIFE_KEY) !== open.raw ||
      open.dialog.parentNode !== open.dialogParent || !lifeV2Visible(open.dialog) ||
      !(open.dialog.open || open.dialog.getAttribute("open") !== null) || open.inner.parentNode !== open.dialog ||
      open.end.parentNode !== open.dialog || open.bar.parentNode !== open.inner || open.clock.parentNode !== open.bar ||
      open.seats.some(seat => seat.node.parentNode !== open.inner) || open.originSource &&
        (!lifeV2Visible(open.originSource) || open.originSource.parentNode !== open.originSourceParent || !main.contains(open.originSource))) return false;
  return (!foreground || !open.blurred && lifeV2Foreground(open.dialog)) && (!button || open.controls.get(button) === button.parentNode &&
    open.dialog.contains(button) && lifeV2Visible(button, allowDisabled));
}
function lifeLegacyButton(open, text, action, attrs = {}) {
  const button = el("button", { type: "button", class: "btn btn-quiet", text, ...attrs });
  button.addEventListener("click", () => { if (lifeLegacyHere(open, button)) action(button); }); return button;
}
function lifeLegacyRegister(open, root) {
  for (const button of root.querySelectorAll("button")) open.controls.set(button, button.parentNode);
}
function lifeLegacyStore(open) { lifeStore(open.game); open.raw = local.get(LIFE_KEY); }

// New counters use the independently validated v2 model. Legacy helpers above
// remain available, and no operation below writes or deletes LIFE_KEY.
const lifeV2Launchers = new WeakMap();
function lifeV2Clone(value) { return JSON.parse(JSON.stringify(value)); }
function lifeV2Scope(profile = state.profile) {
  const space = profile?.space === undefined ? "home" : profile.space;
  return profile && typeof profile.id === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(profile.id) &&
    (space === "home" || space === profile.id) ? { profile: profile.id, space } : null;
}
function lifeV2SessionId() {
  const bytes = new Uint8Array(16);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, value => value.toString(16).padStart(2, "0")).join("");
}
function lifeV2Session(value) { return typeof value === "string" && /^[a-f0-9]{32}$/.test(value); }
function lifeV2Key(profile = state.profile, session = "active") {
  const owner = lifeV2Scope(profile);
  return owner && (session === "active" || lifeV2Session(session))
    ? `${LIFE_SOURCE_KEY}.${owner.space}.${owner.profile}.${session}` : null;
}
function lifeV2Saved(_data, now = Date.now()) {
  const key = lifeV2Key(), session = key && local.get(key), packetKey = lifeV2Key(state.profile, session);
  if (!lifeV2Session(session) || lifeV2Completed.has(packetKey)) return null;
  try {
    const raw = local.get(packetKey);
    if (typeof raw !== "string" || raw.length > 64000) return null;
    const game = JSON.parse(raw);
    return lifeSourceValid(game, lifeV2Scope(), now) && game.session_id === session ? game : null;
  } catch (_) { return null; }
}
function lifeV2Visible(node, disabled = false) {
  if (!node?.isConnected || !disabled && node.disabled) return false;
  for (let parent = node; parent; parent = parent.parentNode) {
    if (parent.hidden || parent.getAttribute?.("aria-hidden") === "true") return false;
    if ((parent.tagName?.toLowerCase() || parent.tag) === "details" && !parent.open && parent.getAttribute("open") === null) {
      const summary = Array.from(parent.children).find(child => (child.tagName?.toLowerCase() || child.tag) === "summary");
      if (!summary?.contains(node)) return false;
    }
  }
  return true;
}
function lifeV2Foreground(node) {
  if (document.hidden === true || document.visibilityState && document.visibilityState !== "visible") return false;
  const dialogs = Array.from(document.querySelectorAll("dialog")).filter(item =>
    (item.open || item.getAttribute("open") !== null) && !item.hidden);
  return !dialogs.length || dialogs.at(-1).contains(node);
}
function lifeV2LaunchHere(ctx, button) {
  const main = document.getElementById("main");
  return ctx.bound && state.profile === ctx.profile && state.profile?.id === ctx.scope?.profile &&
    lifeV2Scope()?.space === ctx.scope?.space && routeToken === ctx.token && location.hash === ctx.hash &&
    main === ctx.main && main?.isConnected && ctx.box.parentNode === ctx.parent &&
    ctx.host?.parentNode === ctx.main && ctx.host.contains(ctx.box) &&
    ctx.data.lists === ctx.lists && ctx.data.decks === ctx.decks && button.parentNode === ctx.box && lifeV2Visible(button);
}
/** Called once the quick-record panel has assembled its original launcher frame. */
function lifeV2BindLauncher(root) {
  for (const box of root.querySelectorAll(".play-counter")) {
    const ctx = lifeV2Launchers.get(box);
    if (ctx && !ctx.bound) { ctx.parent = box.parentNode; ctx.host = root; ctx.bound = true; }
  }
}
function lifeV2EmptyLauncher(data) {
  return typeof lifeSourceNewGame === "function" && lifeV2Saved(data) ? lifeV2Launcher(data, () => [], true) : null;
}
function lifeV2Launcher(data, chosen, resumeOnly = false) {
  const box = el("div", { class: "play-counter" }), error = el("p", { class: "form-error", role: "status" });
  const ctx = { box, data, lists: data.lists, decks: data.decks, profile: state.profile, scope: lifeV2Scope(),
    token: routeToken, hash: location.hash, main: document.getElementById("main"), bound: false };
  lifeV2Launchers.set(box, ctx);
  const start = button => {
    if (!lifeV2LaunchHere(ctx, button) || !lifeV2Foreground(button)) return;
    const input = { ...ctx.scope, session_id: lifeV2SessionId(), date: data.today, choices: chosen() };
    const game = lifeSourceNewGame(input);
    if (!game) { error.textContent = lifeSourceNewError(input) || "Check the selected players and commander sources."; return; }
    openLifeSourceCounter(data, game, { source: button, isCurrent: () => lifeV2LaunchHere(ctx, button), replace: true, onClose: draw });
  };
  function button(words, action) {
    const value = el("button", { type: "button", class: "btn", text: words });
    value.addEventListener("click", () => { if (lifeV2LaunchHere(ctx, value) && lifeV2Foreground(value)) action(value); });
    return value;
  }
  function draw() {
    clear(box); const saved = lifeV2Saved(data), legacy = lifeSaved(data);
    if (saved) {
      box.append(button("Resume life counter", value => {
        const current = lifeV2Saved(data);
        if (current) openLifeSourceCounter(data, current, { source: value, isCurrent: () => lifeV2LaunchHere(ctx, value), onClose: draw });
      }), el("span", { class: "sub", text: saved.players.map(player => `${player.name} ${player.life}`).join(" · ") }));
    }
    if (!resumeOnly) box.append(button(saved ? "New life counter" : "Life counter", start));
    if (legacy) box.append(button("Resume legacy life counter", value => {
      if (lifeV2LaunchHere(ctx, value)) openLifeCounter(data, lifeSaved(data) || legacy, draw,
        { resume: true, source: value, isCurrent: () => lifeV2LaunchHere(ctx, value) });
    }), el("span", { class: "sub", text: "Legacy combined commander damage. Its saved counts remain unchanged." }));
    box.append(error);
  }
  draw(); return box;
}
function lifeV2StorageCurrent(open) {
  return local.get(open.pointerKey) === open.pointerObserved && local.get(open.packetKey) === open.stored;
}
function lifeV2Here(open, foreground = false) {
  try {
    const main = document.getElementById("main");
    return lifeV2Open === open && state.profile === open.profile && lifeV2Scope()?.profile === open.scope.profile &&
      lifeV2Scope()?.space === open.scope.space && routeToken === open.token && location.hash === open.hash &&
      main === open.main && main?.isConnected && open.data.lists === open.lists && open.data.decks === open.decks &&
      open.options.source === open.source && open.options.isCurrent === open.owner && open.options.onClose === open.onClose &&
      open.owner() === true && lifeV2Visible(open.source) && open.source.parentNode === open.sourceParent && main.contains(open.source) &&
      open.dialog.parentNode === open.dialogParent && lifeV2Visible(open.dialog) &&
      (open.dialog.open || open.dialog.getAttribute("open") !== null) && open.inner.parentNode === open.dialog &&
      open.bar.parentNode === open.inner && open.end.parentNode === open.dialog && open.error.parentNode === open.bar &&
      open.clock.parentNode === open.bar && open.rows.every(row => row.node.parentNode === open.inner) &&
      open.game === open.originalGame && open.game.session_id === open.session && lifeSourceValid(open.game, open.scope) &&
      (!foreground || !open.blurred && lifeV2Foreground(open.dialog));
  } catch (_) { return false; }
}
function lifeV2Control(open, button, disabled = false) {
  return lifeV2Here(open, true) && open.controls.get(button) === button.parentNode && open.dialog.contains(button) &&
    lifeV2Visible(button, disabled) && (!open.completed || button === open.closeButton) &&
    (!open.choosing || open.end.contains(button) || button === open.closeButton);
}
function lifeV2Register(open, root) {
  for (const button of root.querySelectorAll("button")) open.controls.set(button, button.parentNode);
}
function lifeV2Button(open, words, action, attrs = {}) {
  const button = el("button", { type: "button", class: "btn btn-quiet", text: words, ...attrs });
  button.addEventListener("click", () => { if (lifeV2Control(open, button)) action(button); });
  return button;
}
function lifeV2Write(open) {
  const encoded = JSON.stringify(open.game); local.set(open.packetKey, encoded);
  const raw = local.get(open.packetKey); let pointer = local.get(open.pointerKey);
  if (raw !== open.stored && raw !== encoded || pointer !== open.pointerObserved) {
    open.error.textContent = "Another local counter changed. Close this counter and use Resume."; return;
  }
  if (pointer !== open.session) { local.set(open.pointerKey, open.session); pointer = local.get(open.pointerKey); }
  if (pointer !== open.pointerObserved && pointer !== open.session) return;
  open.stored = raw; open.pointerObserved = pointer;
  open.error.textContent = pointer === open.session && raw === encoded ? "" : "The counter is open, but its latest change could not be kept for Resume.";
  if (pointer === open.session && raw === encoded && lifeV2Session(open.previousSession) && open.previousSession !== open.session) {
    local.remove(lifeV2Key(open.profile, open.previousSession)); open.previousSession = null;
  }
}
function lifeV2Action(open, button, change, foreground = true) {
  if (!lifeV2Control(open, button) || !lifeV2StorageCurrent(open)) return false;
  const previous = lifeV2Clone(open.game);
  if (!change()) return false;
  open.previous = previous; open.generation++; open.choosing = false; lifeV2Write(open);
  const record = foreground && open.game.ended && lifeV2Control(open, button, true);
  lifeV2Draw(open); if (record) lifeV2Record(open);
  return true;
}
/** Held repeats retain the exact foreground control and generation. They never open a record form. */
function lifeV2Press(open, button, step) {
  let timer = null, active = false, held = false, generation = null, pointer = null, terminal = null;
  const stop = () => { active = false; clearTimeout(timer); timer = null; pointer = null; terminal = null; };
  const repeat = () => {
    if (!active || generation !== open.generation || !lifeV2Control(open, button) || !lifeV2StorageCurrent(open)) { stop(); return; }
    held = true;
    if (!step(5, false)) { stop(); return; }
    generation = open.generation;
    if (open.game.ended) {
      if (pointer !== null && lifeV2Control(open, button, true) && lifeV2StorageCurrent(open))
        terminal = { pointer, session: open.session, generation: open.generation, result: JSON.stringify(open.game.ended),
          raw: open.stored, observed: open.pointerObserved };
      active = false; timer = null; return; // no form opens on a timer
    }
    timer = setTimeout(repeat, LIFE_HOLD_MS);
  };
  open.holds.add(stop);
  button.addEventListener("pointerdown", event => {
    if (terminal && event.pointerId !== terminal.pointer) stop();
    if (!lifeV2Control(open, button) || !lifeV2StorageCurrent(open)) return;
    stop(); held = false; active = true; generation = open.generation;
    pointer = Number.isInteger(event.pointerId) ? event.pointerId : null;
    try { button.setPointerCapture?.(event.pointerId); } catch (_) { /* capture is optional */ }
    timer = setTimeout(repeat, LIFE_HOLD_MS);
  });
  button.addEventListener("pointerup", event => {
    const token = terminal; stop();
    if (token && event.pointerId === token.pointer && token.session === open.session && token.generation === open.generation &&
        token.result === JSON.stringify(open.game.ended) && token.raw === open.stored && token.observed === open.pointerObserved &&
        lifeV2Control(open, button, true) && lifeV2StorageCurrent(open)) lifeV2Record(open);
  });
  for (const type of ["pointerleave", "pointercancel", "lostpointercapture"]) button.addEventListener(type, stop);
  button.addEventListener("click", () => {
    if (held) { held = false; return; }
    if (lifeV2Control(open, button)) step(1, true);
  });
  button.addEventListener("contextmenu", event => { if (lifeV2Control(open, button)) event.preventDefault(); });
}
function lifeV2Seat(open, player, index) {
  const total = el("output", { class: "life-total", "aria-live": "polite", "aria-label": `${player.name}: life` });
  const change = (button, field, delta, source = null, foreground = true) => lifeV2Action(open, button,
    () => lifeSourceChange(open.game, player.seat_id, field, delta, source), foreground);
  const big = sign => {
    const button = el("button", { type: "button", class: "btn life-adjust", text: sign < 0 ? "-" : "+",
      "aria-label": `${player.name}: 1 ${sign < 0 ? "life less" : "more life"} (hold for 5)` });
    lifeV2Press(open, button, (amount, foreground) => change(button, "life", sign * amount, null, foreground)); return button;
  };
  const counters = [];
  const counter = (field, label, source = null) => {
    const value = el("output", { class: "life-small-value", "aria-label": `${player.name}: ${label}` });
    const button = delta => lifeV2Button(open, delta < 0 ? "-" : "+", control => change(control, field, delta, source),
      { "aria-label": `${player.name}: ${delta < 0 ? "1 less" : "1 more"} ${label}` });
    const row = el("div", { class: "life-small", role: "group", "aria-label": `${player.name}: ${label}` },
      el("span", { text: label }), button(-1), value, button(1));
    counters.push({ row, value, field, source }); return row;
  };
  const poison = counter("poison", "poison");
  const damage = el("details", { class: "life-source-damage" }, el("summary", { text: "Commander damage received" }));
  for (const other of open.game.players) for (const source of other.sources)
    damage.append(counter("commander", `${other.seat_id === player.seat_id ? "Own commander" : other.name}: ${source.label}`,
      { seat_id: other.seat_id, source_id: source.source_id }));
  damage.hidden = !open.game.commander;
  const status = el("p", { class: "sub", role: "status" });
  const extras = el("div", { class: "life-extras" }, ...[-5, 5].map(delta => lifeV2Button(open, delta < 0 ? "-5" : "+5",
    button => change(button, "life", delta), { "aria-label": `${player.name}: ${delta < 0 ? "5 life less" : "5 more life"}` })), poison, damage,
  lifeV2Button(open, "Concede", button => lifeV2Action(open, button, () => lifeSourceConcede(open.game, player.seat_id)),
    { "aria-label": `${player.name}: concede` }));
  const node = el("section", { class: `life-seat life-seat-${index}`, "data-life-source-seat": player.seat_id },
    el("p", { class: "life-name" }, el("strong", { text: player.name }), el("span", { class: "sub", text: player.list.title })),
    el("div", { class: "life-main" }, big(-1), total, big(1)), extras, status);
  return { node, draw() {
    total.textContent = String(player.life); status.textContent = lifeSourceOutWhy(open.game, player.seat_id) || "Still playing";
    for (const item of counters) {
      item.row.hidden = item.field === "poison" && !open.game.poison;
      item.value.textContent = String(item.field === "poison" ? player.poison : player.damage.find(entry =>
        entry.seat_id === item.source.seat_id && entry.source_id === item.source.source_id)?.value || 0);
    }
    for (const button of node.querySelectorAll("button")) button.disabled = !!open.game.ended || open.completed;
  } };
}
function lifeV2Draw(open, rebuild = false) {
  if (rebuild) {
    for (const stop of open.holds) stop(); open.holds.clear();
    for (const [button] of open.controls) if (open.rows.some(row => row.node.contains(button))) open.controls.delete(button);
    for (const row of open.rows) row.node.remove();
    open.rows = open.game.players.map((player, index) => lifeV2Seat(open, player, index));
    open.inner.insertBefore(open.rows[0].node, open.bar); open.inner.append(open.rows[1].node);
    for (const row of open.rows) lifeV2Register(open, row.node);
  }
  for (const row of open.rows) row.draw();
  open.poisonButton.setAttribute("aria-pressed", String(open.game.poison)); open.poisonButton.disabled = !!open.game.ended || open.completed;
  open.endButton.disabled = !!open.game.ended || open.completed; open.undoButton.disabled = !open.previous || open.completed;
  open.end.hidden = !open.choosing && !open.game.ended;
  open.endTitle.textContent = open.game.ended ? open.game.ended.result === "draw" ? "Draw" :
    `${open.game.players.find(player => player.seat_id === open.game.ended.result)?.name || "A player"} won` : "Who won?";
  open.recordButton.hidden = !open.game.ended || open.completed;
  open.keepButton.hidden = !!open.game.ended;
  for (const button of open.winnerButtons) button.hidden = !!open.game.ended;
}
function lifeV2Record(open) {
  if (!lifeV2Here(open, true) || !lifeV2StorageCurrent(open) || !open.game.ended || open.completed || open.handoff ||
      typeof lifeSourceReview !== "function") return false;
  const generation = open.generation;
  const isCurrent = () => lifeV2Here(open) && !open.completed && open.generation === generation && lifeV2StorageCurrent(open);
  const onSaved = () => {
    if (!isCurrent()) return false;
    open.completed = true; open.generation++; lifeV2Completed.add(open.packetKey);
    if (local.remove(open.packetKey) !== true || local.get(open.packetKey) !== null) {
      open.error.textContent = "Game saved. Its local counter could not be removed. Resume is disabled on this page; if it reappears after reload, do not record it again.";
      lifeV2Draw(open); return false;
    }
    closeLifeSourceCounter(); return true;
  };
  open.handoff = true;
  try { lifeSourceReview(open.data, lifeV2Clone(open.game), { isCurrent, onSaved, source: open.source }); }
  catch (_) { if (isCurrent()) open.error.textContent = "The result form could not be opened. Keep this counter and try again."; }
  finally { open.handoff = false; }
  return true;
}
function lifeV2Tick(open) {
  clearTimeout(open.timer);
  if (!lifeV2Here(open) || open.blurred || document.hidden === true || document.visibilityState && document.visibilityState !== "visible") return;
  open.clock.textContent = lifeClockWords((open.game.ended ? open.game.ended.at : Date.now()) - open.game.started);
  open.timer = setTimeout(() => lifeV2Tick(open), 1000);
}
async function lifeV2Wake(open) {
  if (!lifeV2Here(open, true) || !navigator.wakeLock || open.wakePending) return;
  const generation = open.generation, request = ++open.wakeSeq; open.wakePending = true;
  try {
    const wake = await navigator.wakeLock.request("screen");
    if (!lifeV2Here(open, true) || open.generation !== generation || open.wakeSeq !== request) { wake.release(); return; }
    if (open.wake && open.wake !== wake) open.wake.release(); open.wake = wake;
  } catch (_) { /* optional browser facility */ }
  finally { if (open.wakeSeq === request) open.wakePending = false; }
}
function openLifeSourceCounter(data, game, options) {
  const profile = state.profile, scope = lifeV2Scope(profile), main = document.getElementById("main");
  let current = false; try { current = options?.isCurrent?.() === true; } catch (_) { return false; }
  if (!scope || !lifeSourceValid(game, scope) || !current || !main?.contains(options.source) || !lifeV2Visible(options.source) || lifeV2Open) return false;
  const pointerKey = lifeV2Key(profile), packetKey = lifeV2Key(profile, game.session_id), encoded = JSON.stringify(game);
  const pointer = local.get(pointerKey), stored = local.get(packetKey);
  if (lifeV2Completed.has(packetKey) || options.replace !== true && (pointer !== game.session_id || stored !== encoded) ||
      pointer === game.session_id && stored !== encoded) return false;
  if (lifeOpen) closeLifeCounter(true);
  const open = { data, lists: data.lists, decks: data.decks, game: lifeV2Clone(game), profile, scope, main,
    source: options.source, sourceParent: options.source.parentNode, options, owner: options.isCurrent, onClose: options.onClose,
    token: routeToken, hash: location.hash, session: game.session_id, pointerKey, packetKey, pointerObserved: pointer,
    stored, previousSession: pointer, controls: new Map(), holds: new Set(), rows: [], generation: 0, previous: null,
    choosing: false, completed: false, handoff: false, timer: null, wake: null, wakeSeq: 0, wakePending: false, blurred: false };
  open.originalGame = open.game;
  open.clock = el("span", { class: "life-clock", role: "timer", "aria-label": "Game time" });
  open.error = el("p", { class: "form-error life-source-error", role: "status" });
  open.poisonButton = lifeV2Button(open, "Poison", button => lifeV2Action(open, button, () => lifeSourcePoison(open.game, !open.game.poison)));
  open.endButton = lifeV2Button(open, "End game", () => { open.choosing = true; lifeV2Draw(open); });
  open.undoButton = lifeV2Button(open, "Undo last change", button => {
    if (open.previous && lifeV2Control(open, button) && lifeV2StorageCurrent(open) && lifeSourceUndo(open.game, open.previous)) {
      open.previous = null; open.generation++; open.choosing = false; lifeV2Write(open); lifeV2Draw(open, true);
    }
  });
  open.closeButton = lifeV2Button(open, "Close", () => closeLifeSourceCounter());
  open.bar = el("div", { class: "life-bar" }, open.clock, open.poisonButton, open.endButton, open.undoButton, open.closeButton, open.error);
  open.endTitle = el("h2");
  open.winnerButtons = [...game.players.map(player => lifeV2Button(open, `${player.name} won`, button =>
    lifeV2Action(open, button, () => lifeSourceEnd(open.game, player.seat_id)))),
    lifeV2Button(open, "Draw", button => lifeV2Action(open, button, () => lifeSourceEnd(open.game, "draw")))];
  open.keepButton = lifeV2Button(open, "Keep playing", () => { open.choosing = false; lifeV2Draw(open); });
  open.recordButton = lifeV2Button(open, "Record result", () => lifeV2Record(open));
  open.end = el("div", { class: "life-end", role: "group", "aria-label": "The game's end", hidden: true },
    open.endTitle, ...open.winnerButtons, open.keepButton, open.recordButton);
  open.inner = el("div", { class: "life-inner" }, open.bar);
  open.dialog = el("dialog", { class: "life-counter life-source-counter", "aria-label": "Life counter" }, open.inner, open.end);
  open.visible = () => {
    for (const stop of open.holds) stop();
    if (document.hidden === true || document.visibilityState && document.visibilityState !== "visible") {
      open.wakeSeq++; open.wakePending = false;
      clearTimeout(open.timer); try { open.wake?.release(); } catch (_) { /* already released */ } open.wake = null; return;
    }
    lifeV2Tick(open); lifeV2Wake(open);
  };
  document.addEventListener("visibilitychange", open.visible);
  open.onBlur = () => {
    open.blurred = true; open.wakeSeq++; open.wakePending = false; clearTimeout(open.timer);
    for (const stop of open.holds) stop();
    try { open.wake?.release(); } catch (_) { /* already released */ } open.wake = null;
  };
  open.onFocus = () => { open.blurred = false; lifeV2Tick(open); lifeV2Wake(open); };
  for (const type of ["blur", "pagehide"]) window.addEventListener(type, open.onBlur);
  for (const type of ["focus", "pageshow"]) window.addEventListener(type, open.onFocus);
  open.dialog.addEventListener("close", () => { if (lifeV2Open === open) closeLifeSourceCounter(); });
  document.body.append(open.dialog); open.dialogParent = open.dialog.parentNode; lifeV2Open = open;
  if (typeof open.dialog.showModal === "function") open.dialog.showModal(); else open.dialog.setAttribute("open", "");
  if (options.replace === true) {
    local.set(packetKey, encoded); local.set(pointerKey, game.session_id);
    const found = local.get(pointerKey), raw = local.get(packetKey);
    if (found !== pointer && found !== game.session_id || raw !== stored && raw !== encoded) { closeLifeSourceCounter(true); return false; }
    open.pointerObserved = found; open.stored = raw;
    if (found !== game.session_id || raw !== encoded) open.error.textContent = "The counter is open, but it could not be kept for Resume.";
    else if (lifeV2Session(pointer) && pointer !== game.session_id) { local.remove(lifeV2Key(profile, pointer)); open.previousSession = null; }
  }
  lifeV2Register(open, open.bar); lifeV2Register(open, open.end); lifeV2Draw(open, true); lifeV2Tick(open);
  open.entry = typeof pushSheetEntry === "function" ? pushSheetEntry(() => { if (lifeV2Open === open) closeLifeSourceCounter(); }) : null;
  lifeV2Wake(open); return true;
}
function closeLifeSourceCounter(quiet = false) {
  const open = lifeV2Open;
  if (!open) return false;
  const notify = !quiet && lifeV2Here(open);
  lifeV2Open = null; clearTimeout(open.timer); for (const stop of open.holds) stop();
  document.removeEventListener("visibilitychange", open.visible);
  for (const type of ["blur", "pagehide"]) window.removeEventListener(type, open.onBlur);
  for (const type of ["focus", "pageshow"]) window.removeEventListener(type, open.onFocus);
  try { open.wake?.release(); } catch (_) { /* already released */ }
  if (open.dialog.open && typeof open.dialog.close === "function") open.dialog.close(); open.dialog.remove();
  if (typeof releaseSheetEntry === "function") releaseSheetEntry(open.entry);
  if (notify && typeof open.onClose === "function") open.onClose();
  return true;
}
