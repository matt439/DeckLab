/* Correct a deck's recorded physical build from a reviewed box check: preview, then one confirmed save. */
"use strict";

function boxRepairCounts(rows) {
  return Array.isArray(rows) && rows.every(row => row && typeof row.name === "string" && Number.isSafeInteger(row.quantity) && row.quantity > 0);
}

/** A preview answer about exactly this review, or null. */
function boxRepairPreviewValid(answer, deck, evidence, review) {
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  return answer?.preview === true && answer.id === deck.id && answer.recipe_sha256 === evidence.meta.recipe_sha256
    && hash(answer.result_sha256) && answer.sections && typeof answer.sections === "object"
    && Object.keys(answer.sections).every(section => BOX_CHECK_SECTIONS.includes(section) && Array.isArray(answer.sections[section]))
    && Number.isSafeInteger(answer.card_count) && answer.card_count === review.found_cards
    && boxRepairCounts(answer.freed) && boxRepairCounts(answer.held)
    && answer.tokens && Array.isArray(answer.tokens.cards) ? answer : null;
}

function boxRepairPreviewParts(answer) {
  const parts = [el("h4", { text: "The corrected box record" }),
    el("p", { text: plural(answer.card_count, "card") + " in " + (answer.version === "owned" ? "the Play-now list's" : "the Planned list's") + " recorded build." })];
  for (const section of BOX_CHECK_SECTIONS) {
    const rows = answer.sections[section]; if (!rows?.length) continue;
    parts.push(el("section", {}, el("h5", { text: section }),
      el("ul", { class: "box-repair-rows" }, rows.map(row => el("li", { text: row.quantity + " x " + packBoxRowWords(row) })))));
  }
  const freed = answer.freed.map(row => row.quantity + " " + row.name).join(", ");
  const held = answer.held.map(row => row.quantity + " " + row.name).join(", ");
  parts.push(el("p", { text: freed ? "Free for other decks again: " + freed + "." : "No cards are freed for other decks." }),
    el("p", { text: held ? "Now held by this deck: " + held + "." : "No more cards are held by this deck." }));
  const short = answer.held.filter(row => row.short > 0);
  if (short.length) parts.push(el("p", { class: "note note-warn", text: "The collection records fewer copies than the built decks would now hold: "
    + short.map(row => row.short + " more " + row.name).join(", ") + ". Review collection copies after saving if these cards are yours." }));
  if (answer.pool_unknown) parts.push(el("p", { class: "note note-warn", text: "The collection couldn't be read, so these cards weren't checked against it." }));
  const tokens = answer.tokens;
  parts.push(el("p", { class: "sub", text: (tokens.cards.length ? "Packed token cards stay as recorded: " + tokens.cards.join("; ") + "."
    : tokens.recorded ? "This deck records no packed token cards; that stays as it is." : "This deck has no packed token cards recorded; that stays as it is.")
    + " Change them on the deck page if the box holds different ones." }));
  if (tokens.no_longer_made?.length) parts.push(el("p", { class: "sub", text: "The corrected cards no longer make: " + tokens.no_longer_made.join(", ") + "." }));
  if (tokens.newly_made?.length) parts.push(el("p", { class: "sub", text: "The corrected cards now also make: " + tokens.newly_made.join(", ") + "." }));
  parts.push(el("p", { class: "sub", text: "Saving changes only the recorded box and its check date. The Planned and Play-now lists, the collection, sleeves, deck box and token cards stay as they are." }));
  return parts;
}

/** The offer inside the difference review. options: host, here(), busy(value), payload(), saved(answer). */
function boxRepairOffer(deck, evidence, review, options) {
  let preview = null, pending = false;
  const error = el("p", { class: "form-error", role: "alert", tabindex: "-1" }), body = el("div");
  const live = event => options.here() && !pending && event?.currentTarget?.isConnected && options.host.contains(event.currentTarget);
  const busy = value => { pending = value; options.busy(value); draw(); };
  function draw() {
    const buttons = [];
    if (!preview) buttons.push(el("button", { type: "button", class: "btn btn-secondary box-repair-preview", disabled: pending,
      text: pending ? "Working out the corrected box…" : "Preview corrected box", onclick: ask }));
    else buttons.push(el("button", { type: "button", class: "btn btn-primary box-repair-save", disabled: pending,
      text: pending ? "Saving the corrected box…" : "Save corrected box", onclick: save }),
    el("button", { type: "button", class: "btn btn-quiet", disabled: pending, text: "Don't correct", onclick: event => {
      if (!live(event)) return; preview = null; clear(body); error.textContent = ""; draw();
    } }));
    clear(options.host).append(el("h4", { text: "Correct the recorded box" }),
      el("p", { class: "sub", text: "If the box really holds these cards now, record them as this deck's build, so the cards it reserves match the box. You see the change before anything is saved." }),
      body, el("div", { class: "actions" }, buttons), error);
  }
  async function ask(event) {
    if (!live(event)) return;
    error.textContent = ""; busy(true);
    try {
      const answer = boxRepairPreviewValid(await apiWrite("/api/deck/box-repair", options.payload()), deck, evidence, review);
      if (!answer) throw new Error("The corrected box couldn't be worked out. Reload the plan and check again.");
      if (!options.here()) return;
      preview = answer; clear(body).append(...boxRepairPreviewParts(answer));
    } catch (failure) {
      if (options.here()) error.textContent = failure.message || "The corrected box couldn't be worked out.";
    } finally {
      busy(false);
    }
  }
  async function save(event) {
    if (!live(event) || !preview) return;
    error.textContent = ""; busy(true);
    try {
      const answer = await apiWrite("/api/deck/box-repair", { ...options.payload(), confirm: true, result_sha256: preview.result_sha256 });
      state.library = null;
      if (answer?.saved !== true || answer.id !== deck.id || answer.result_sha256 !== preview.result_sha256
          || typeof answer.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(answer.sha256) || boxCheckDate(answer.checked_on) === null)
        throw new Error("The corrected box couldn't be confirmed. Reload the plan to see what was saved.");
      pending = false; options.busy(false);
      clear(options.host).append(el("p", { role: "status", tabindex: "-1", class: "box-repair-saved",
        text: "The recorded box now matches this check, and the check date is " + answer.checked_on + "." }),
        answer.stale_tables?.length ? tablesLaterNote("Other decks' availability tables need updating.") : "");
      options.saved(answer);
      return;
    } catch (failure) {
      state.library = null;
      if (options.here()) error.textContent = (failure.message || "The corrected box couldn't be saved.")
        + (failure.status === 409 ? " Reload the plan before checking again." : "");
      if (failure.status === 409) options.stale?.();
    }
    busy(false);
  }
  draw();
}
