/* Optional counter facts are reviewed with a game, never sent while counting. */
"use strict";

const PLAY_OUT_REASONS = ["life", "poison", "commander", "conceded", "chosen"];
const PLAY_OUT_WORDS = { life: "Life", poison: "Poison", commander: "Commander damage", conceded: "Conceded", chosen: "Chosen" };

function playCounterNormalise(value, ids) {
  if (value == null) return null;
  const fail = () => { throw Error("Check the optional game length, final life and elimination details."); };
  const keys = (row, names) => row && typeof row === "object" && !Array.isArray(row)
    && Object.keys(row).length === names.length && Object.keys(row).every(key => names.includes(key));
  const integer = (value, low, high) => value === null || Number.isSafeInteger(value) && value >= low && value <= high;
  if (!keys(value, ["duration_seconds", "seats"]) || !integer(value.duration_seconds, 0, 172800)
      || !Array.isArray(value.seats) || value.seats.length !== ids.length) return fail();
  for (const [index, row] of value.seats.entries()) if (!keys(row, ["seat_id", "final_life", "out_reason", "out_order"])
      || row.seat_id !== ids[index] || !integer(row.final_life, -999, 999) || !integer(row.out_order, 1, ids.length)
      || row.out_reason !== null && !PLAY_OUT_REASONS.includes(row.out_reason)) return fail();
  return value.duration_seconds !== null || value.seats.some(row => [row.final_life, row.out_reason, row.out_order].some(item => item !== null))
    ? structuredClone(value) : null;
}
function playCounterFacts(packet) {
  if (!packet?.ended) return null;
  const players = packet.seats || packet.players || [], isPod = Array.isArray(packet.seats);
  const reasons = players.map((row, index) => {
    const seat_id = row.seat_id || (index ? "b" : "a");
    const loser = packet.ended.result !== "draw" && packet.ended.result !== seat_id;
    const why = isPod ? row.out?.why : loser && PLAY_OUT_REASONS.includes(packet.ended.why) && packet.ended.why !== "chosen"
      ? packet.ended.why : packet.ended.result === "draw" && packet.ended.why === "poison" ? "poison" : null;
    return { seat_id, final_life: row.life, out_reason: why || null,
      order: isPod ? row.out?.order : why ? 1 : null, at: isPod ? row.out?.at : why ? packet.ended.at : null };
  });
  return playCounterNormalise({ duration_seconds: Math.max(0, Math.floor((packet.ended.at - packet.started) / 1000)),
    seats: reasons.map(({ at, order, ...row }) => ({ ...row,
      out_order: Number.isSafeInteger(order) ? order : at == null || reasons.filter(value => value.at === at).length > 1
        ? null : reasons.filter(value => Number.isSafeInteger(value.at) && value.at < at).length + 1 })) },
  reasons.map(row => row.seat_id));
}
function playCounterFields(facts, seats) {
  if (facts == null) return null;
  const ids = seats.map(seat => seat.id), source = playCounterNormalise(facts, ids);
  const duration = el("input", { type: "number", min: 0, max: 2880, step: "0.01", "data-counter-duration": "",
    value: source?.duration_seconds == null ? "" : (source.duration_seconds / 60).toFixed(2) });
  const rows = seats.map(seat => {
    const prior = source?.seats.find(row => row.seat_id === seat.id);
    const life = el("input", { type: "number", min: -999, max: 999, step: 1, "data-counter-life": seat.id,
      value: prior?.final_life ?? "" });
    const reason = el("select", { "data-counter-reason": seat.id }, el("option", { value: "", text: "Not recorded" }),
      PLAY_OUT_REASONS.map(value => el("option", { value, text: PLAY_OUT_WORDS[value] })));
    reason.value = prior?.out_reason || "";
    const order = el("input", { type: "number", min: 1, max: 4, step: 1, "data-counter-order": seat.id,
      value: prior?.out_order ?? "" });
    return { id: seat.id, life, reason, order, node: el("fieldset", { class: "play-counter-seat" },
      el("legend", { text: seat.name }), playField("Final life (optional)", life),
      playField("Out because (optional)", reason), playField("Out order (optional)", order)) };
  });
  const root = el("fieldset", { class: "play-counter-fields" }, el("legend", { text: "Counter details (optional)" }),
    el("p", { class: "sub", text: "Review these details or clear any you don't want to record. Simultaneous eliminations may share an order." }),
    playField("Game length, minutes (optional)", duration), ...rows.map(row => row.node));
  const fields = [duration, ...rows.flatMap(row => [row.life, row.reason, row.order])];
  const parents = new Map(fields.map(node => [node, node.parentNode]));
  return { root, fields, here: form => root.parentNode === form && fields.every(node => root.contains(node) && node.parentNode === parents.get(node)),
    read: (active = ids) => playCounterNormalise({
      duration_seconds: duration.value === "" ? null : Math.round(Number(duration.value) * 60),
      seats: active.map(id => {
        const row = rows.find(row => row.id === id);
        return { seat_id: id, final_life: !row || row.life.value === "" ? null : Number(row.life.value),
          out_reason: row?.reason.value || null, out_order: !row || row.order.value === "" ? null : Number(row.order.value) };
      }) }, active) };
}
function playCounterPart(record) {
  if (!record.counter) return null;
  const seats = record.seats || record.sides?.map((side,index) => ({ seat_id: index ? "b" : "a", player: side.player || side.title }));
  let facts; try { facts = playCounterNormalise(record.counter, seats.map(seat => seat.seat_id)); } catch (_) { return null; }
  if (!facts) return null;
  return el("details", { class: "play-counter-details" }, el("summary", { text: "Counter details" }),
    facts.duration_seconds !== null ? el("p", { text: `Game length: ${Math.floor(facts.duration_seconds / 60)} min ${facts.duration_seconds % 60} sec` }) : null,
    el("ul", {}, facts.seats.map((row,index) => el("li", { text: [seats[index].player || `Player ${index+1}`,
      row.final_life !== null ? `${row.final_life} life` : null,
      row.out_reason ? `Out: ${PLAY_OUT_WORDS[row.out_reason]}` : null,
      row.out_order !== null ? `Out order ${row.out_order}` : null].filter(Boolean).join(" · ") }))));
}
