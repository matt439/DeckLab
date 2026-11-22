/* Who sees what: the viewer's own Public/Private switches. The server offers only categories whose
complete public readers are ready, and enforces ownership and readiness again on every flip. */
"use strict";

const VISIBILITY_WORDS = {
  collection: ["Collection and tokens", "Shows your collection and physical token cards. Purchases, deliveries and raw imports stay private."],
  decks: ["Decks", "Shows each deck's lists and write-up as written. The alternative list and notes can reveal cards you own or ordered."],
  games: ["Game log", "Shows games involving your space. Hidden opponent decks stay anonymous, and sideboard plans stay private."],
  accessories: ["Sleeves, deck boxes and playmats", "Shows these accessories and their pictures. A private holder deck stays anonymous."],
};

const PUBLIC_AUDIENCE = "Public gives read-only access to everyone signed in to Deck Lab and to visitors on the home network, even without a chosen profile. Away from home, sign-in is required.";
const PREVIEW_UNKNOWN = "Deck Lab couldn't work out what this would show just now. You can still make it Public.";

/** What Public readers would get, in the owner's own counts (GET /api/visibility/preview). */
function visibilityPreviewLines(thing, data) {
  const counts = data && data.available && data.counts;
  if (!counts) return [(data && data.message) || PREVIEW_UNKNOWN];
  const n = (key) => (Number.isInteger(counts[key]) ? counts[key] : 0);
  if (thing === "collection") {
    return [`${plural(n("collection_rows"), "collection row")} (${plural(n("collection_cards"), "card")}) and ` +
      `${plural(n("token_rows"), "token card row")} (${plural(n("token_cards"), "token card")}).`];
  }
  if (thing === "games") return [`${plural(n("games"), "game")} involving your decks.`];
  if (thing === "accessories") {
    return [`${plural(n("kit_rows"), "sleeve, deck box or playmat row", "sleeve, deck box and playmat rows")}, ` +
      `${num(n("kit_pictures"))} with pictures.`];
  }
  const lines = [`${plural(n("decks"), "deck")}, each write-up as written.`];
  const mentions = Array.isArray(data.mentions) ? data.mentions : [];
  if (mentions.length) {
    const more = Number.isInteger(data.more_mentions) && data.more_mentions > 0 ? ` and ${num(data.more_mentions)} more` : "";
    lines.push(`These write-ups mention orders or purchases: ${mentions.map((d) => d.title).join(", ")}${more}.`);
  } else {
    lines.push("No deck's write-up mentions orders or purchases.");
  }
  return lines;
}

/** The confirm sheet before a switch turns Public; true only on Confirm. A failed preview still offers it. */
async function confirmPublic(row, label, stillOnSwitch) {
  let data = null;
  try {
    data = await api(`/api/visibility/preview?owner=${encodeURIComponent(row.owner)}&thing=${encodeURIComponent(row.thing)}`);
  } catch (error) {
    data = null;
  }
  if (!stillOnSwitch()) return false;
  const words = VISIBILITY_WORDS[row.thing];
  const previewKnown = !!(data && data.available && data.counts);
  const choice = await new Promise((resolve) => {
    const sheet = openSheet(`Make ${label.toLowerCase()} Public?`, {
      onClose: (result) => resolve(result == null ? null : result),
    });
    sheet.body.append(el("p", {}, el("strong", { text: PUBLIC_AUDIENCE })));
    if (previewKnown) sheet.body.append(...visibilityPreviewLines(row.thing, data).map((text) => el("p", { text })));
    if (words) sheet.body.append(el("p", { text: words[1] }));
    sheet.body.append(el("p", { text: "Choose Private to remove this read access later." }));
    if (!previewKnown) sheet.body.append(el("div", { class: "note note-warn", role: "alert" },
      el("strong", { text: "Preview unavailable. " }),
      ...visibilityPreviewLines(row.thing, data).map((text) => el("p", { text }))));
    sheetActions(sheet, [
      { text: "Keep private", value: "cancel", onclick: () => sheet.close("cancel") },
      { text: previewKnown ? "Make public" : "Make public without preview", kind: "primary", value: "confirm",
        onclick: () => sheet.close("confirm") },
    ]);
    sheet.foot.querySelector('[data-action="cancel"]')?.focus();
  });
  return choice === "confirm";
}

function showVisibility(params, token) {
  setTitle("Who sees what");
  return load("/api/visibility", token, (data) => drawVisibility(data, token), { title: "Who sees what couldn't be loaded" });
}

function drawVisibility(data, token) {
  const main = clear($("#main"));
  add(main, [pageHead({ title: "Who sees what" }),
    el("p", { class: "sub", id: "public-audience", text: PUBLIC_AUDIENCE }),
    el("p", { class: "sub", text: "Everything starts Private. Only the owner can change a switch. Either home profile can change the home and shared switches." })]);
  const switches = Array.isArray(data && data.switches) ? data.switches : [];
  if (!switches.length) {
    main.append(emptyBox("No Public switches yet. Everything stays Private."));
    return;
  }
  for (const row of switches) {
    const words = VISIBILITY_WORDS[row.thing];
    if (!words) continue;
    const label = row.thing === "accessories" && row.owner === "shared" ? `Shared ${words[0].toLowerCase()}` : words[0];
    const id = `visibility-${row.owner}-${row.thing}`;
    const scope = `${id}-scope`;
    const status = el("p", { class: "sub", role: "status", "aria-live": "polite" });
    const group = el("div", { class: "segmented", role: "group", "aria-labelledby": id, "aria-describedby": `${scope} public-audience` });
    for (const [value, text] of [[false, "Private"], [true, "Public"]]) {
      group.append(el("button", { type: "button", text, "data-public": String(value),
        "aria-pressed": String(Boolean(row.public) === value), onclick: async () => {
          if (Boolean(row.public) === value) return;
          const profile = state.profile, hash = location.hash, buttons = group.querySelectorAll("button");
          const stillOnPage = () => token === routeToken && state.profile === profile && location.hash === hash;
          const stillOnSwitch = () => stillOnPage() && group.isConnected;
          // Public asks first with what it would show (E10-S46); Private stays one tap.
          if (value) {
            for (const button of buttons) button.disabled = true;
            status.textContent = "Working out what this would show...";
            let confirmed = false;
            try {
              confirmed = await confirmPublic(row, label, stillOnSwitch);
            } finally {
              for (const button of buttons) button.disabled = false;
              status.textContent = "";
            }
            if (!confirmed || !stillOnSwitch()) return;
          }
          for (const button of buttons) button.disabled = true;
          status.textContent = "Saving...";
          try {
            const saved = await apiWrite("/api/visibility", { profile: profile && profile.id,
              owner: row.owner, thing: row.thing, public: value }, "PUT");
            if (!stillOnPage()) return;
            drawVisibility(saved, token);
            toast(`Saved as ${value ? "Public" : "Private"}.`);
            invalidateLibrary();
            // Refresh permissions and the roster after the committed flip. A refresh failure
            // does not misreport a successful save as a failed save.
            const [me, roster] = await Promise.allSettled([loadMe(), api("/api/profiles")]);
            if (!stillOnPage()) return;
            if (me.status === "fulfilled" && me.value.profile === profile.id && me.value.may) state.may = me.value.may;
            if (roster.status === "fulfilled") keepRoster(roster.value);
            drawShell();
          } catch (error) {
            if (!stillOnSwitch()) return;
            status.textContent = `Couldn't save: ${error.message}`;
          } finally {
            for (const button of buttons) button.disabled = false;
          }
        } }));
    }
    main.append(el("section", { class: "panel settings-part", "data-visibility-owner": row.owner,
      "data-visibility-thing": row.thing }, el("h2", { id, text: label }),
      el("p", { class: "sub", id: scope, text: words[1] }), group, status));
  }
}
