/* Commander pod records: three or four seats, reviewed explicitly before one save.
 * Opponents are private text labels; only the server captures saved decklists. */
"use strict";

function podUtf8(value) { return !/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/u.test(value); }
/** Python's stored text trims Unicode whitespace, including NEL but excluding the BOM. */
function podTrim(value) {
  return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");
}
function podText(value, limit, blank = false) {
  return typeof value === "string" && Array.from(value).length <= limit && (blank || podTrim(value).length > 0) &&
    !/[\u0000-\u001f\u007f]/.test(value) && podUtf8(value);
}
function podNotes(value) {
  return typeof value === "string" && Array.from(value).length <= 2000 && !/[\u0000-\u0008\u000b-\u001f\u007f]/.test(value) && podUtf8(value);
}
function podDate(value) {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && !value.startsWith("0000") &&
    Number.isFinite(new Date(`${value}T00:00:00Z`).getTime()) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
function podSha(value) { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }
function podMode(record) { return !!record && record.mode === "pod" && record.game_version === 2; }
function podList(list) {
  return !!list && podText(list.id, 200) && ["target", "owned"].includes(list.version) &&
    podSha(list.sha256) && podText(list.title, 500);
}
function podSnapshot(list) {
  return podList(list) && Object.keys(list).every(key => ["id", "version", "sha256", "title", "sections"].includes(key)) &&
    list.sections && typeof list.sections === "object" && !Array.isArray(list.sections) &&
    Array.isArray(list.sections.Deck) && list.sections.Deck.length > 0 && Object.keys(list.sections).length <= 12 &&
    Object.entries(list.sections).every(([name, lines]) => podText(name, 80) && Array.isArray(lines) && lines.length <= 500 &&
      lines.every(line => line && Number.isSafeInteger(line.qty) && line.qty > 0 && line.qty <= 10000 &&
        podText(line.name, 300) && ["nonfoil", "foil", "etched"].includes(line.finish) &&
        [line.set, line.number].every(value => value == null || podText(value, 80, true))));
}
function podKey(list) { return JSON.stringify([list.id, list.version, list.sha256]); }
function podSeatName(seat, index) { return podText(seat.player, 80) ? seat.player : `Player ${index + 1}`; }
function podResult(record) {
  if (record.result === "draw") return "Draw";
  const at = record.seats.findIndex(seat => seat.seat_id === record.result);
  return at < 0 ? "Result unavailable" : `${podSeatName(record.seats[at], at)} won`;
}
function podShownRecord(record) {
  return podMode(record) && !("sides" in record) && podDate(record.date) &&
    (record.notes === undefined || podNotes(record.notes)) &&
    (record.space === undefined || podText(record.space, 80)) &&
    Array.isArray(record.seats) && [3, 4].includes(record.seats.length) &&
    new Set(record.seats.map(seat => seat?.seat_id)).size === record.seats.length &&
    record.seats.every(seat => seat && /^s[1-4]$/.test(seat.seat_id) && ["deck", "external"].includes(seat.type) &&
      (seat.player === undefined || podText(seat.player, 80)) &&
      Object.keys(seat).every(key => (seat.type === "deck" ? ["seat_id", "type", "player", "deck"]
        : ["seat_id", "type", "player", "commander"]).includes(key)) &&
      (seat.type === "external" ? seat.commander === undefined || podText(seat.commander, 300, true)
        : podSnapshot(seat.deck) || seat.deck?.hidden === true && podText(seat.deck.title, 500) &&
          Object.keys(seat.deck).length === 2)) &&
    record.seats.some(seat => seat.type === "deck") &&
    (record.result === "draw" || record.seats.some(seat => seat.seat_id === record.result));
}

function podCard(entry, data, editable = true) {
  const record = entry.record;
  const card = el("article", { class: "panel play-record play-pod-record" },
    el("div", { class: "play-record-head" }, el("h3", { text: podResult(record) }),
      el("span", { class: "sub", text: playDay(record.date) })),
    el("p", { class: "sub", text: `${record.seats.length}-player Commander pod` }),
    el("ul", { class: "play-pod-seats" }, record.seats.map((seat, i) => el("li", {},
      el("strong", { text: podSeatName(seat, i) }), ": ",
      seat.type === "deck" ? (podList(seat.deck) ? playListWords(seat.deck) : seat.deck?.title || "A deck")
        : seat.commander || "External opponent"))),
    record.notes ? el("p", { class: "play-note", text: record.notes }) : null,
    playSnapshotDetails(record.seats.filter(seat => seat.type === "deck").map(seat => seat.deck).filter(Boolean)));
  if (editable && entry.can?.edit === true && podSha(entry.sha256)) {
    const button = el("button", { type: "button", class: "btn btn-quiet", text: "Correct this pod game" });
    card.append(button);
    const owner = podOwnerContext(data, button, card, entry);
    button.addEventListener("click", () => { if (podOwner(owner) && !button.disabled) podForm(owner); });
  }
  return card;
}

function playPodSection(data, deckId = "") {
  if (!Array.isArray(data.pods) || !Array.isArray(data.pod_lists)) return null;
  const entries = data.pods.filter(entry => podShownRecord(entry?.record));
  const section = el("section", { class: "play-section", "aria-labelledby": "play-pods-title" });
  const heading = el("div", { class: "play-section-head" }, el("h2", { id: "play-pods-title", text: "Commander pods" }));
  if (state.profile && data.pod_lists.some(list => podList(list) && list.can_record === true)) {
    const button = el("button", { type: "button", class: "btn", text: "Record a pod game" });
    heading.append(button);
    const owner = podOwnerContext(data, button, heading, null, deckId);
    button.addEventListener("click", () => { if (podOwner(owner) && !button.disabled) podForm(owner); });
  }
  section.append(heading);
  const resume = podCounterResumeAction(data, section);
  if (resume) section.append(resume);
  section.append(el("p", { class: "sub", text: "Three or four players. Pod results stay separate from 1v1 Head to head." }),
    entries.length ? el("div", { class: "play-records" }, entries.map(entry => podCard(entry, data)))
      : emptyBox(deckId ? "No pod games with this deck yet." : "No pod games have been recorded yet."));
  if (entries.length) section.append(el("p", { class: "sub play-pod-count", text: `${plural(entries.length, "pod game")} recorded.` }));
  return section;
}

function podOwnerContext(data, button, host, entry = null, deckId = "") {
  return { data, lists: data.pod_lists, pods: data.pods, button, host, entry, record: entry?.record,
    sha256: entry?.sha256, recordBytes: entry ? JSON.stringify(entry.record) : null,
    main: $("#main"), profile: state.profile, profileId: state.profile?.id,
    space: state.profile?.space || HOME_SPACE, token: routeToken, hash: location.hash, deckId };
}
function podContextOwner(ctx) {
  return !!ctx.profile && ctx.profile === state.profile && ctx.profileId === state.profile?.id &&
    ctx.space === (state.profile?.space || HOME_SPACE) && ctx.token === routeToken && ctx.hash === location.hash &&
    ctx.main === $("#main") && ctx.main.isConnected && ctx.host.isConnected && ctx.main.contains(ctx.host) &&
    ctx.button.isConnected && ctx.button.parentNode === ctx.host && ctx.host.contains(ctx.button) &&
    ctx.data.pod_lists === ctx.lists && ctx.data.pods === ctx.pods &&
    (!ctx.frame || ctx.host.parentNode === ctx.frame && ctx.frame.parentNode === ctx.frameParent && ctx.main.contains(ctx.frame));
}
function podOwner(ctx) {
  return podContextOwner(ctx) && (ctx.entry ? ctx.entry.record === ctx.record && ctx.entry.sha256 === ctx.sha256 &&
      JSON.stringify(ctx.record) === ctx.recordBytes && ctx.entry.can?.edit === true
      : ctx.lists.some(list => podList(list) && list.can_record === true));
}
function podTop(sheet) {
  return Array.from(document.querySelectorAll("dialog")).filter(node => node.isConnected &&
    (node.open || node.getAttribute("open") !== null)).at(-1) === sheet.dialog;
}
function podFrame(sheet) {
  return { sheet, dialog: sheet.dialog, body: sheet.body, foot: sheet.foot, parent: sheet.dialog.parentNode,
    bodyParent: sheet.body.parentNode, footParent: sheet.foot.parentNode };
}
function podFrameHere(frame) {
  const { sheet, dialog, body, foot, parent, bodyParent, footParent } = frame;
  return !sheet.closed && sheet.dialog === dialog && sheet.body === body && sheet.foot === foot &&
    dialog.isConnected && dialog.parentNode === parent && body.parentNode === bodyParent && foot.parentNode === footParent &&
    dialog.contains(body) && dialog.contains(foot);
}
function podFormHere(ctx) {
  return (podOwner(ctx) || ctx.counterPreset && podContextOwner(ctx)) &&
    (!ctx.counterPreset || ctx.counterPreset.isCurrent()) && podFrameHere(ctx.editFrame) && ctx.form.parentNode === ctx.editFrame.body &&
    ctx.reviewButton.parentNode === ctx.editFrame.foot && ctx.reviewButton.isConnected &&
    ctx.form.contains(ctx.seatsBox) && ctx.form.contains(ctx.count) && ctx.form.contains(ctx.date) &&
    ctx.form.contains(ctx.result) && ctx.form.contains(ctx.notes) && ctx.controls.every(row =>
      ctx.seatsBox.contains(row.box) && [row.player, row.type, row.list, row.commander].every(node => row.box.contains(node)));
}
function podDraft(ctx) {
  return { profile: ctx.profileId, id: ctx.previewId || ctx.record?.id || null, sha256: ctx.sha256 || null,
    mode: "pod", game_version: 2, date: ctx.date.value, result: ctx.result.value, notes: ctx.notes.value,
    seats: ctx.controls.map(row => row.type.value === "deck"
      ? { seat_id: row.seat.seat_id, type: "deck", player: row.player.value, deck: playChoice(podSelectedList(row)) }
      : { seat_id: row.seat.seat_id, type: "external", player: row.player.value, commander: row.commander.value }) };
}
function podSelectedList(row) {
  return /^\d+$/.test(row.list.value) ? row.lists[Number(row.list.value)] : null;
}
function podDraftStamp(ctx) { try { return JSON.stringify(podDraft(ctx)); } catch (_) { return null; } }
function podDraftError(payload, today) {
  if (!podDate(payload.date) || payload.date > today) return "Choose a valid date on or before today.";
  if (!payload.seats.some(seat => seat.type === "deck")) return "Choose at least one saved Commander deck from your collection.";
  if (payload.seats.some(seat => !podText(seat.player, 80))) return "Give each player a label of at most 80 characters, on one line.";
  if (payload.seats.some(seat => seat.type === "external" && !podText(seat.commander, 300, true)))
    return "Keep each commander label to at most 300 characters, on one line.";
  if (!podNotes(payload.notes)) return "Keep notes to at most 2,000 characters, without unsupported control characters.";
  if (payload.result !== "draw" && !payload.seats.some(seat => seat.seat_id === payload.result)) return "Choose a winner or draw.";
  return null;
}

function podForm(owner, preset = null, onSaved = null) {
  if ((!podOwner(owner) && !(preset && podContextOwner(owner))) || preset && !preset.isCurrent() ||
      owner.sheet && !owner.sheet.closed) return;
  const ctx = { ...owner, generation: 0, previewId: null, pending: false, counterPreset: preset, onSaved };
  owner.sheet = ctx.sheet = openSheet(ctx.record ? "Correct a pod game" : "Record a pod game", { wide: true });
  ctx.editFrame = podFrame(ctx.sheet);
  ctx.frame = owner.host.parentNode; ctx.frameParent = ctx.frame.parentNode;
  const currentLists = ctx.lists.filter(podList);
  const start = currentLists.find(list => list.id === ctx.deckId && list.can_record === true)
    || currentLists.find(list => list.can_record === true);
  ctx.seats = new Map([1, 2, 3, 4].map(n => [`s${n}`, { seat_id: `s${n}`, type: n === 1 ? "deck" : "external",
    player: n === 1 ? ctx.profile.name : `Opponent ${n - 1}`, commander: "", selected: start && podKey(start) }]));
  const seeded = ctx.record?.seats || preset?.seats;
  ctx.active = seeded ? seeded.map(seat => seat.seat_id) : ["s1", "s2", "s3"];
  for (const seat of seeded || []) ctx.seats.set(seat.seat_id, { ...seat,
    selected: seat.type === "deck" ? podKey(seat.deck) : start && podKey(start) });
  ctx.count = el("select", { id: "pod-count" }, [3, 4].map(n => el("option", { value: String(n), text: `${n} players` })));
  ctx.count.value = String(ctx.active.length);
  ctx.date = el("input", { id: "pod-date", type: "date", required: true, max: ctx.data.today, value: ctx.record?.date || preset?.date || ctx.data.today });
  ctx.result = el("select", { id: "pod-result", required: true });
  ctx.notes = el("textarea", { id: "pod-notes", maxlength: 4000, rows: 3 }, ctx.record?.notes || preset?.notes || "");
  ctx.notes.value = ctx.record?.notes || preset?.notes || "";
  ctx.seatsBox = el("div", { class: "play-pod-form-seats" });
  ctx.form = el("form", { class: "play-form play-pod-form" });
  ctx.error = el("p", { class: "form-error", role: "alert" });
  ctx.reviewButton = el("button", { type: "button", class: "btn btn-primary", text: "Review pod game" });
  const change = () => { ctx.generation++; ctx.error.textContent = ""; };
  const remember = () => { for (const row of ctx.controls || []) Object.assign(row.seat, {
    type: row.type.value, player: row.player.value, commander: row.commander.value,
    selected: podSelectedList(row) && podKey(podSelectedList(row)) }); };
  const results = (preferred = ctx.result.value) => {
    clear(ctx.result).append(el("option", { value: "", text: "Choose a result" }),
      ...ctx.controls.map((row, i) => el("option", { value: row.seat.seat_id, text: `${podTrim(row.player.value) || `Player ${i + 1}`} won` })),
      el("option", { value: "draw", text: "Draw" }));
    ctx.result.value = preferred === "draw" || ctx.active.includes(preferred) ? preferred : "";
  };
  const render = () => {
    clear(ctx.seatsBox); ctx.controls = [];
    for (const [i, id] of ctx.active.entries()) {
      const seat = ctx.seats.get(id), lists = [...currentLists];
      if (ctx.record && seat.deck && !lists.some(list => podKey(list) === podKey(seat.deck))) lists.unshift({ ...seat.deck, historical: true });
      const selected = lists.findIndex(value => podKey(value) === seat.selected);
      const needsReplacement = !!preset && !!seat.deck && selected < 0;
      const player = el("input", { type: "text", maxlength: 160, required: true, value: seat.player, "data-pod-player": id });
      const type = el("select", { "data-pod-type": id }, el("option", { value: "deck", text: "Saved Commander deck" }),
        el("option", { value: "external", text: "External opponent" })); type.value = seat.type;
      const list = el("select", { "data-pod-list": id }, lists.map((value, index) => el("option", { value: String(index),
        text: playListWords(value) + (value.historical ? " (recorded historical list)" : " (current saved list)") })));
      if (needsReplacement) list.insertBefore(el("option", { value: "", text: "Choose a current replacement list" }), list.children[0] || null);
      list.value = needsReplacement ? "" : String(Math.max(0, selected));
      const commander = el("input", { type: "text", maxlength: 600, value: seat.commander || "", "data-pod-commander": id });
      const deckField = playField("Deck and list", list), commanderField = playField("Commander (optional)", commander);
      const toggle = () => { deckField.hidden = type.value !== "deck"; commanderField.hidden = type.value !== "external";
        list.required = type.value === "deck"; };
      const replacement = needsReplacement ? el("p", { class: "box box-warn", text:
        "The list chosen for the counter has changed or is unavailable. Choose a current list explicitly before review. The game record will capture that current list; you can keep counting without recording." }) : null;
      const box = el("fieldset", { class: "play-side" }, el("legend", { text: `Player ${i + 1}` }),
        playField("Player label", player), playField("Playing", type), deckField, commanderField, replacement);
      const row = { seat, player, type, list, commander, lists, box }; ctx.controls.push(row); ctx.seatsBox.append(box);
      for (const node of [player, type, list, commander]) for (const event of ["input", "change"]) node.addEventListener(event, change);
      type.addEventListener("change", toggle); player.addEventListener("input", () => results()); toggle();
    }
    results(!ctx.result.value ? ctx.record?.result || preset?.result || "" : ctx.result.value);
  };
  ctx.count.addEventListener("change", () => {
    remember(); const result = ctx.result.value;
    if (ctx.count.value === "4" && ctx.active.length === 3) ctx.active.push(["s1", "s2", "s3", "s4"].find(id => !ctx.active.includes(id)));
    else if (ctx.count.value === "3" && ctx.active.length === 4) ctx.active.pop();
    render(); results(result); change();
  });
  for (const node of [ctx.date, ctx.result, ctx.notes]) for (const event of ["input", "change"]) node.addEventListener(event, change);
  render();
  ctx.form.append(el("p", { class: "sub", text: "Choose at least one of your collection's Commander decks. External opponent and commander labels stay private to your collection." }),
    playField("Players", ctx.count), playField("Date played", ctx.date), ctx.seatsBox, playField("Result", ctx.result),
    playField("Notes (optional)", ctx.notes), ctx.error);
  ctx.editFrame.body.append(ctx.form);
  ctx.editFrame.foot.append(el("button", { type: "button", class: "btn", text: "Cancel", onclick: () => {
    if (podFormHere(ctx) && podTop(ctx.sheet) && !ctx.pending) ctx.sheet.close();
  } }), ctx.reviewButton);
  if (!ctx.record && !preset && podCounterAvailable()) {
    ctx.counterStart = el("button", { type: "button", class: "btn", text: "Start pod counter", onclick: () => podCounterStart(ctx, owner) });
    ctx.editFrame.foot.append(ctx.counterStart);
  }
  ctx.reviewButton.addEventListener("click", () => podPreview(ctx));
  ctx.form.addEventListener("submit", event => { event.preventDefault(); podPreview(ctx); });
  if (podFormHere(ctx) && podTop(ctx.sheet)) ctx.controls[0].player.focus();
}

function podCounterAvailable() {
  return typeof podLifeNew === "function" && typeof podLifeNewError === "function" &&
    typeof podLifeSaved === "function" && typeof podLifeOpen === "function" && typeof podLifeSessionId === "function";
}

/** Resume controls belong to the original Game log; a close never refreshes another profile's page. */
function podCounterResumeAction(data, section) {
  if (!podCounterAvailable() || !state.profile) return null;
  const host = el("div", { class: "play-counter pod-counter-launcher", "data-pod-counter-resume": "" });
  const profile = state.profile, profileId = profile.id, space = profile.space || HOME_SPACE;
  const token = routeToken, hash = location.hash, main = $("#main"), lists = data.pod_lists, pods = data.pods;
  const here = () => profile === state.profile && profileId === state.profile?.id && space === (state.profile?.space || HOME_SPACE) &&
    token === routeToken && hash === location.hash && main === $("#main") && main.isConnected &&
    host.isConnected && host.parentNode === section && section.parentNode === main && main.contains(host) &&
    data.pod_lists === lists && data.pods === pods;
  const draw = (initial = false) => {
    if (!initial && !here()) return;
    const packet = podLifeSaved(data);
    clear(host); host.hidden = !packet;
    if (!packet) return;
    const button = el("button", { type: "button", class: "btn", text: "Resume pod counter" });
    host.append(button);
    const owner = podOwnerContext(data, button, host);
    owner.frame = section; owner.frameParent = main;
    button.addEventListener("click", () => {
      if (!here() || !podContextOwner(owner) || !podCounterControlVisible(button) ||
          document.visibilityState === "hidden" || keyboardDialog()) return;
      if (!podCounterOpen(owner, packet, false)) {
        const error = el("p", { class: "form-error", role: "alert", text: "That counter changed or is unavailable. Refresh the Game log before resuming it." });
        if (here() && host.contains(button)) host.append(error);
      }
    });
  };
  host.podCounterRefresh = wanted => { if (wanted === data) draw(); };
  draw(true);
  return host;
}

function podCounterControlVisible(control) {
  if (!control?.isConnected || control.disabled) return false;
  for (let node = control; node; node = node.parentNode) {
    if (node.hidden || node.getAttribute?.("aria-hidden") === "true") return false;
    if (node.matches?.("details") && !node.open && node.getAttribute("open") === null) {
      const summary = node.querySelector("summary");
      if (!summary || !summary.contains(control)) return false;
    }
  }
  return true;
}

function podCounterRefresh(data) {
  for (const host of document.querySelectorAll("[data-pod-counter-resume]")) {
    if (host.podCounterRefresh && host.isConnected) host.podCounterRefresh(data);
  }
}

function podCounterOpen(owner, packet, replace) {
  if (!podCounterAvailable() || !podContextOwner(owner) || document.visibilityState === "hidden") return false;
  return podLifeOpen(owner.data, packet, { source: owner.button, replace,
    isCurrent: () => podContextOwner(owner) && packet.profile === owner.profileId && packet.space === owner.space &&
      document.visibilityState !== "hidden",
    onRecord: (ended, bridge) => podCounterRecord(owner, ended, bridge),
    onClose: () => { if (podContextOwner(owner)) podCounterRefresh(owner.data); } });
}

/** Counter input keeps selectors and labels only. External names are never split into guessed commanders. */
function podCounterInput(ctx) {
  const draft = podDraft(ctx);
  const problem = podDraftError({ ...draft, result: "draw" }, ctx.data.today);
  if (problem) return { problem };
  const seats = draft.seats.map((seat, i) => {
    if (seat.type === "external") return { ...seat, sources: [{ source_id: "c1", label: seat.commander }] };
    const list = podSelectedList(ctx.controls[i]);
    const lines = list?.sections?.Commander || [];
    if (!Array.isArray(lines) || lines.some(line => !podText(line?.name, 300))) throw Error("Invalid commander labels");
    const labels = [...new Set(lines.map(line => line.name))];
    return { ...seat, title: list.title, sources: (labels.length ? labels : [""]).map((label, index) =>
      ({ source_id: `c${index + 1}`, label })) };
  });
  return { input: { profile: ctx.profileId, space: ctx.space, session_id: podLifeSessionId(),
    date: draft.date, notes: draft.notes, seats } };
}

function podCounterStart(ctx, owner) {
  if (!podCounterAvailable() || !podFormHere(ctx) || !podTop(ctx.sheet) || ctx.pending ||
      document.visibilityState === "hidden" || ctx.counterStart?.parentNode !== ctx.editFrame.foot ||
      !podCounterControlVisible(ctx.counterStart)) return;
  let checked;
  try {
    checked = podCounterInput(ctx);
    if (!checked.problem) checked.problem = podLifeNewError(checked.input);
    if (checked.problem) { ctx.error.textContent = checked.problem; return; }
    const packet = podLifeNew(checked.input);
    const anchor = { ...owner, frame: owner.host.parentNode, frameParent: owner.host.parentNode.parentNode };
    if (!packet || !podCounterOpen(anchor, packet, true)) {
      ctx.error.textContent = "The counter couldn't be started. Your pod choices are still here.";
      return;
    }
    ctx.sheet.close();
  } catch (_) { ctx.error.textContent = "Choose valid saved Commander lists and player labels before starting the counter."; }
}

/** A counter result enters the ordinary explicit review. Counter-only totals never enter the API body. */
function podCounterRecord(owner, packet, bridge) {
  if (!podContextOwner(owner) || document.visibilityState === "hidden" || !bridge?.isCurrent?.() ||
      packet.profile !== owner.profileId || packet.space !== owner.space || !packet.ended ||
      typeof podLifeValid !== "function" || !podLifeValid(packet, { profile: owner.profileId, space: owner.space })) return;
  const result = packet.ended.result;
  if (result !== "draw" && !packet.seats.some(seat => seat.seat_id === result)) return;
  const seats = packet.seats.map(seat => seat.type === "external"
    ? { seat_id: seat.seat_id, type: "external", player: seat.player, commander: seat.commander }
    : { seat_id: seat.seat_id, type: "deck", player: seat.player, deck: { ...seat.deck } });
  const session = packet.session_id;
  const isCurrent = () => podContextOwner(owner) && document.visibilityState !== "hidden" && bridge.isCurrent() &&
    packet.session_id === session && packet.profile === owner.profileId && packet.space === owner.space;
  const preset = { date: packet.date, notes: packet.notes, result, seats, isCurrent };
  podForm(owner, preset, () => isCurrent() ? bridge.onSaved() : false);
}

function podReviewed(answer, payload, space, saved = false) {
  const record = answer?.record;
  if (answer?.error || !podShownRecord(record) || !/^[a-f0-9]{32}$/.test(answer.id || record?.id || "") ||
      !podSha(saved ? answer.sha256 : answer.review_sha256) || (saved ? answer.saved !== true : answer.preview !== true) ||
      saved && (record.version !== 1 || record.kind !== "games" || !Number.isSafeInteger(record.revision) || record.revision < 1) ||
      payload.id && (saved ? record.id : answer.id) !== payload.id || record.space !== space || record.date !== payload.date ||
      record.result !== payload.result || record.notes !== podTrim(payload.notes) || record.seats.length !== payload.seats.length) return null;
  for (let i = 0; i < payload.seats.length; i++) {
    const seat = record.seats[i], wanted = payload.seats[i];
    if (seat.seat_id !== wanted.seat_id || seat.type !== wanted.type || seat.player !== podTrim(wanted.player)) return null;
    if (seat.type === "external") {
      if ((seat.commander || "") !== podTrim(wanted.commander) || "deck" in seat || "id" in seat) return null;
    } else if (!podSnapshot(seat.deck) || ["id", "version", "sha256"].some(key => seat.deck[key] !== wanted.deck[key])) return null;
  }
  return { id: saved ? record.id : answer.id, token: answer.review_sha256, record: structuredClone(record) };
}
async function podPreview(ctx) {
  if (!podFormHere(ctx) || !podTop(ctx.sheet) || ctx.pending || ctx.reviewButton.disabled) return;
  let payload;
  try { payload = podDraft(ctx); }
  catch (_) { ctx.error.textContent = "Choose a saved Commander deck for each deck seat."; return; }
  if (ctx.counterPreset && !ctx.controls.some(row => row.type.value === "deck" && podSelectedList(row)?.can_record === true)) {
    ctx.error.textContent = "Choose a current deck you may record before review. You can keep counting without recording.";
    return;
  }
  const localError = podDraftError(payload, ctx.data.today);
  if (localError) { ctx.error.textContent = localError; return; }
  const generation = ctx.generation, stamp = JSON.stringify(payload);
  const current = () => podFormHere(ctx) && ctx.generation === generation && podDraftStamp(ctx) === stamp;
  ctx.pending = true; ctx.error.textContent = ""; busy(ctx.reviewButton, "Checking.");
  try {
    const answer = await apiWrite("/api/play/pod", { ...payload, preview: true });
    if (!current() || !podTop(ctx.sheet)) return;
    const checked = podReviewed(answer, payload, ctx.space);
    if (!checked) { ctx.error.textContent = "The pod preview couldn't be checked. Your draft is still here."; return; }
    // A new record retains the server's preview identity, without changing any typed fields.
    ctx.previewId = checked.id; payload = { ...payload, id: checked.id };
    podReviewSheet(ctx, payload, checked, generation);
  } catch (_) { if (current() && podTop(ctx.sheet)) ctx.error.textContent = "The pod game couldn't be reviewed. Your draft is still here; try Review again."; }
  finally { ctx.pending = false; if (podFormHere(ctx)) unbusy(ctx.reviewButton); }
}

function podReviewSheet(ctx, payload, checked, generation) {
  const stamp = JSON.stringify(payload), review = openSheet("Review pod game", { wide: true });
  const frame = podFrame(review), error = el("p", { class: "form-error", role: "alert" });
  const summary = podCard({ record: checked.record }, ctx.data, false);
  frame.body.append(summary, error);
  let pending = false, saved = false;
  const back = el("button", { type: "button", class: "btn", text: "Back to editing" });
  const save = el("button", { type: "button", class: "btn btn-primary", text: "Save pod game" });
  frame.foot.append(back, save);
  const current = () => podFormHere(ctx) && podFrameHere(frame) && podTop(review) &&
    summary.parentNode === frame.body && error.parentNode === frame.body && back.parentNode === frame.foot && save.parentNode === frame.foot &&
    back.isConnected && save.isConnected && ctx.generation === generation && podDraftStamp(ctx) === stamp;
  back.addEventListener("click", () => { if (current() && !pending) { review.close(); if (podFormHere(ctx) && podTop(ctx.sheet)) ctx.reviewButton.focus(); } });
  save.addEventListener("click", async () => {
    if (!current() || pending || saved || save.disabled) return;
    pending = true; busy(save, "Saving."); error.textContent = "";
    try {
      const answer = await apiWrite("/api/play/pod", { ...payload, preview: false, review_sha256: checked.token });
      if (!current()) return;
      if (!podReviewed(answer, payload, ctx.space, true)) { error.textContent = "The save response couldn't be checked. Keep this draft and refresh the Game log before trying again."; return; }
      saved = true; review.close(); ctx.sheet.close();
      if (podContextOwner(ctx)) {
        const cleaned = ctx.onSaved ? ctx.onSaved() : true;
        toast("Pod game saved.");
        if (cleaned !== false) route();
      }
    } catch (_) { if (current()) error.textContent = "The pod game couldn't be saved. Your draft is still here. Go back to review it again; a changed record may need a fresh Game log."; }
    finally { pending = false; if (current()) unbusy(save); }
  });
  if (current()) back.focus();
}
