/* Who sees what: the viewer's own Public/Private switches. The server offers only categories whose
complete public readers are ready, and enforces ownership and readiness again on every flip. */
"use strict";

const VISIBILITY_WORDS = {
  collection: ["Collection and tokens", "Shows your collection and physical token cards. Purchases, deliveries and raw imports stay private."],
  decks: ["Decks", "Shows each deck's write-up as written, including notes about cards you own or ordered. The Play-now list hints at what's owned."],
  games: ["Game log", "Shows games involving your space. Hidden opponent decks stay anonymous, and sideboard plans stay private."],
  accessories: ["Sleeves, deck boxes and playmats", "Shows these accessories and their pictures. A private holder deck stays anonymous."],
};

function showVisibility(params, token) {
  setTitle("Who sees what");
  return load("/api/visibility", token, (data) => drawVisibility(data, token), { title: "Who sees what couldn't be loaded" });
}

function drawVisibility(data, token) {
  const main = clear($("#main"));
  add(main, [pageHead({ title: "Who sees what",
    description: "Public means read-only to everyone signed in, including members, and visitors on the home network. Nothing becomes public on the internet." }),
    el("p", { class: "sub", text: "Everything starts Private. Only you can change your switches; either home profile can change the home and shared switches." })]);
  const switches = Array.isArray(data && data.switches) ? data.switches : [];
  if (!switches.length) {
    main.append(el("p", { class: "box box-info", text: "No Public switches are available yet. Everything stays Private." }));
    return;
  }
  for (const row of switches) {
    const words = VISIBILITY_WORDS[row.thing];
    if (!words) continue;
    const label = row.thing === "accessories" && row.owner === "shared" ? `Shared ${words[0].toLowerCase()}` : words[0];
    const id = `visibility-${row.owner}-${row.thing}`;
    const status = el("p", { class: "sub", role: "status", "aria-live": "polite" });
    const group = el("div", { class: "segmented", role: "group", "aria-labelledby": id });
    for (const [value, text] of [[false, "Private"], [true, "Public"]]) {
      group.append(el("button", { type: "button", text, "data-public": String(value),
        "aria-pressed": String(Boolean(row.public) === value), onclick: async () => {
          if (Boolean(row.public) === value) return;
          const profile = state.profile, buttons = group.querySelectorAll("button");
          for (const button of buttons) button.disabled = true;
          status.textContent = "Saving...";
          try {
            const saved = await apiWrite("/api/visibility", { profile: profile && profile.id,
              owner: row.owner, thing: row.thing, public: value }, "PUT");
            if (token !== routeToken || state.profile !== profile) return;
            drawVisibility(saved, token);
            toast(`Saved as ${value ? "Public" : "Private"}.`);
            state.library = null;
            // Refresh permissions and the roster after the committed flip. A refresh failure
            // does not misreport a successful save as a failed save.
            const [me, roster] = await Promise.allSettled([loadMe(), api("/api/profiles")]);
            if (token !== routeToken || state.profile !== profile) return;
            if (me.status === "fulfilled" && me.value.profile === profile.id && me.value.may) state.may = me.value.may;
            if (roster.status === "fulfilled") keepRoster(roster.value);
            drawShell();
          } catch (error) {
            if (token !== routeToken || state.profile !== profile) return;
            status.textContent = `Couldn't save: ${error.message}`;
          } finally {
            for (const button of buttons) button.disabled = false;
          }
        } }));
    }
    main.append(el("section", { class: "panel settings-part", "data-visibility-owner": row.owner,
      "data-visibility-thing": row.thing }, el("h2", { id, text: label }),
      el("p", { class: "sub", text: words[1] }), group, status));
  }
}
