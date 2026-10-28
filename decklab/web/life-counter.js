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
  const box = el("div", { class: "play-counter" });
  const start = () => openLifeCounter(data, lifeNewGame(chosen(), state.profile && state.profile.id), draw);
  function draw() {
    const saved = lifeSaved(data);
    clear(box);
    if (!saved) {
      box.append(el("button", { type: "button", class: "btn", text: "Life counter", onclick: start }));
      return;
    }
    add(box, [el("button", { type: "button", class: "btn", text: "Resume life counter",
      onclick: () => openLifeCounter(data, lifeSaved(data) || saved, draw) }),
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
function lifePress(button, step) {
  let timer = null, held = false;
  const stop = () => { clearTimeout(timer); timer = null; };
  const repeat = () => { held = true; timer = step(5) ? setTimeout(repeat, LIFE_HOLD_MS) : null; };
  button.addEventListener("pointerdown", () => { held = false; stop(); timer = setTimeout(repeat, LIFE_HOLD_MS); });
  for (const type of ["pointerup", "pointerleave", "pointercancel"]) button.addEventListener(type, stop);
  button.addEventListener("click", () => { if (held) held = false; else step(1); });
  button.addEventListener("contextmenu", (event) => event.preventDefault());    // a long press isn't a menu
}

/** One player's half: name and deck, life with − and +, −5 and +5, poison and commander damage. */
function lifeSeat(open, i) {
  const game = open.game, player = game.players[i];
  const total = el("output", { class: "life-total", "aria-live": "polite", "aria-label": `${player.name}'s life` });
  const big = (sign, words) => {
    const button = el("button", { type: "button", class: "btn life-adjust", "aria-label": `${player.name}: ${words} (hold for 5)` },
      el("span", { class: "life-sign", "aria-hidden": "true", text: sign < 0 ? "−" : "+" }));
    lifePress(button, (n) => lifeStep(open, i, "life", sign * n));
    return button;
  };
  const counter = (field, label) => {
    const value = el("output", { class: "life-small-value", "aria-label": `${player.name}: ${label}` });
    const step = (delta, words) => el("button", { type: "button", class: "btn btn-quiet", "aria-label": `${player.name}: ${words}`,
      text: delta < 0 ? "−" : "+", onclick: () => lifeStep(open, i, field, delta) });
    const row = el("div", { class: "life-small", role: "group", "aria-label": `${player.name}: ${label}` },
      el("span", { class: "life-small-label", text: label }), step(-1, `1 ${label.toLowerCase()} less`), value,
      step(1, `1 more ${label.toLowerCase()}`));
    return { row, value, field };
  };
  const counters = [counter("poison", "Poison"), ...(game.commander ? [counter("commander", "Commander damage")] : [])];
  const fives = [-5, 5].map((delta) => el("button", { type: "button", class: "btn btn-quiet",
    "aria-label": `${player.name}: ${delta < 0 ? "5 life less" : "5 more life"}`, text: delta < 0 ? "−5" : "+5",
    onclick: () => lifeStep(open, i, "life", delta) }));
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
function lifeStep(open, i, field, delta) {
  if (lifeOpen !== open || !lifeChange(open.game, i, field, delta)) return false;
  lifeStore(open.game);
  lifeDraw(open);
  if (open.game.ended) lifeRecord(open);
  return true;
}

/** Opens the Game log's Record a played game sheet over the counter, filled in from the game (when the viewer
 * may record it). Saving it ends the counter. */
function lifeRecord(open) {
  if (!open.mayRecord || !open.game.ended || typeof playGameForm !== "function") return;
  const game = open.game;
  playGameForm(open.data, "", null, { result: game.ended.result,
    sides: game.players.map((p) => ({ id: p.list.id, version: p.list.version, player: p.name })),
    onSaved: () => { local.remove(LIFE_KEY); closeLifeCounter(); } });
}

function lifeDraw(open) {
  const game = open.game;
  open.seats.forEach((seat) => seat.draw());
  open.poison.setAttribute("aria-pressed", game.poison ? "true" : "false");
  open.endButton.disabled = !!game.ended;
  clear(open.end);
  open.end.hidden = !game.ended && !open.choosing;
  if (game.ended) {
    const [winner, why] = lifeEndWords(game);
    add(open.end, [el("h2", { text: winner }), why ? el("p", { text: why }) : null,
      open.mayRecord ? null : el("p", { class: "sub", text: "You can't record a game with these decks." }),
      el("div", { class: "life-end-actions" },
        open.mayRecord ? el("button", { type: "button", class: "btn btn-primary", text: "Record result", onclick: () => lifeRecord(open) }) : null,
        el("button", { type: "button", class: "btn", text: "Back to the game", onclick: () => {
          game.ended = null; lifeStore(game); lifeDraw(open);
        } }),
        el("button", { type: "button", class: "btn btn-quiet", text: "New game",
          onclick: () => openLifeCounter(open.data, lifeAgain(game), open.onClose) }))]);
  } else if (open.choosing) {
    const pick = (result) => () => {
      open.choosing = false; lifeEnd(game, result); lifeStore(game); lifeDraw(open); lifeRecord(open);
    };
    add(open.end, [el("h2", { text: "Who won?" }),
      el("div", { class: "life-end-actions" },
        game.players.map((p, i) => el("button", { type: "button", class: "btn", text: `${p.name} won`, onclick: pick(i ? "b" : "a") })),
        el("button", { type: "button", class: "btn", text: "Draw", onclick: pick("draw") }),
        el("button", { type: "button", class: "btn btn-quiet", text: "Keep playing", onclick: () => {
          open.choosing = false; lifeDraw(open);
        } }))]);
  }
}

function lifeTick(open) {
  if (lifeOpen !== open) return;
  const game = open.game;
  open.clock.textContent = lifeClockWords((game.ended ? game.ended.at : Date.now()) - game.started);
  open.timer = setTimeout(() => lifeTick(open), 1000);
}

/** Keeps the phone's screen on while the counter is open, where the browser allows it. */
async function lifeWake(open) {
  try {
    if (lifeOpen === open && document.visibilityState !== "hidden" && navigator.wakeLock) {
      open.wake = await navigator.wakeLock.request("screen");
    }
  } catch (e) { open.wake = null; }
}

/** Shows the counter for game, full screen. onClose: called when it closes (the Game log's Resume). */
function openLifeCounter(data, game, onClose = null) {
  closeLifeCounter(true);
  const open = { data, game, onClose, choosing: false, mayRecord: lifeMayRecord(data, game), timer: null, wake: null };
  open.seats = game.players.map((_, i) => lifeSeat(open, i));
  open.clock = el("span", { class: "life-clock", role: "timer", "aria-label": "Game time" });
  open.poison = el("button", { type: "button", class: "btn btn-quiet", text: "Poison", "aria-pressed": "false",
    onclick: () => { game.poison = !game.poison; lifeStore(game); lifeDraw(open); } });
  open.endButton = el("button", { type: "button", class: "btn", text: "End game",
    onclick: () => { open.choosing = true; lifeDraw(open); } });
  open.end = el("div", { class: "life-end", role: "group", "aria-label": "The game's end", hidden: true });
  const close = el("button", { type: "button", class: "btn btn-quiet", text: "Close", onclick: () => closeLifeCounter() });
  open.dialog = el("dialog", { class: "life-counter", "aria-label": "Life counter" },
    el("div", { class: "life-inner" }, open.seats[0].node,
      el("div", { class: "life-bar" }, open.clock, open.poison, open.endButton, close), open.seats[1].node),
    open.end);
  open.dialog.addEventListener("close", () => { if (lifeOpen === open) closeLifeCounter(); });
  open.onVisible = () => { if (document.visibilityState === "visible") lifeWake(open); };
  document.addEventListener("visibilitychange", open.onVisible);
  document.body.append(open.dialog);
  lifeOpen = open;
  lifeStore(game);
  lifeDraw(open);
  lifeTick(open);
  if (typeof open.dialog.showModal === "function") open.dialog.showModal();
  else open.dialog.setAttribute("open", "");
  open.entry = typeof pushSheetEntry === "function" ? pushSheetEntry(() => closeLifeCounter()) : null;
  lifeWake(open);
  return open;
}

/** Closes the counter on screen (its game stays kept until it's recorded). quiet: no onClose (another opens). */
function closeLifeCounter(quiet = false) {
  const open = lifeOpen;
  if (!open) return;
  lifeOpen = null;
  clearTimeout(open.timer);
  document.removeEventListener("visibilitychange", open.onVisible);
  try { if (open.wake) open.wake.release(); } catch (e) { /* already released */ }
  if (open.dialog.open) open.dialog.close();
  open.dialog.remove();
  if (typeof releaseSheetEntry === "function") releaseSheetEntry(open.entry);
  if (!quiet && open.onClose) open.onClose();
}
