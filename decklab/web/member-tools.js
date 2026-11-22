/* Personal member downloads and stateless card needs. No home scope, queue or saved plan. */
"use strict";

function memberOwnSpace() {
  const who = state.profile, space = ownSpace();
  return Boolean(who && space !== HOME_SPACE && who.id === space && seesInventory(space));
}

async function downloadMemberSpace(cv) {
  if (!memberOwnSpace() || cv.space !== ownSpace() || !colActive(cv) || cv.personalBusy) return;
  const profile = state.profile, hash = location.hash;
  const current = () => state.profile === profile && location.hash === hash && colActive(cv)
    && memberOwnSpace() && cv.space === ownSpace();
  cv.personalBusy = true;
  clear(cv.message).append(el("p", {text: "Preparing your personal copy…"}));
  try {
    const data = await api(colPath("/api/space/download", cv.space), {binary: true, headers: {Accept: "application/zip"}});
    if (!current()) return;
    const url = URL.createObjectURL(data);
    const link = el("a", {href: url, download: `decklab-${cv.space}-personal.zip`});
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    clear(cv.message).append(el("p", {text: "Your personal copy was downloaded. It is not a departure export."}));
  } catch(error) {
    if (current()) clear(cv.message).append(loadFailed("Your personal copy", error));
  } finally {
    cv.personalBusy = false;
  }
}

async function openMemberNeeds() {
  if (!memberOwnSpace()) return null;
  const profile = state.profile, token = routeToken, hash = location.hash;
  const sheet = colOpenSheet("Combined shortages");
  const current = () => !sheet.closed && state.profile === profile && token === routeToken
    && hash === location.hash && memberOwnSpace();
  const close = {text: "Close", onclick: () => sheet.close()};
  const retry = {text: "Try again", onclick: event => {
    if (event.currentTarget.isConnected && current()) count();
  }};
  async function count() {
    sheetActions(sheet, [close]);
    clear(sheet.body).append(loadingBox("Counting your saved Planned decks together…"));
    let data;
    try {
      data = await api(colPath("/api/space/needed", ownSpace()));
    } catch (error) {
      if (current()) {
        clear(sheet.body).append(loadFailed("Your combined shortages", error));
        sheetActions(sheet, [close, retry]);
      }
      return;
    }
    if (!current()) return;
    clear(sheet.body).append(el("p", {class: "sub", text: "From your recorded collection and saved Planned lists, excluding trials. Each available copy counts once across the decks. The calculation excludes lent-out copies."}));
    if (!data.ready) {
      sheet.body.append(el("p", {class: "box box-warn", text: data.reason || "Your missing cards couldn't be counted completely."}));
      if (data.check_collection) sheet.body.append(el("a", {href: colHash(ownSpace(), "rows"), text: "Check my collection"}));
      if (data.check_decks?.length) sheet.body.append(el("ul", {}, data.check_decks.map(deck =>
        el("li", {}, el("a", {href: deckHref(deck.id, "target"), text: deck.title})))));
      sheetActions(sheet, [close, retry]);
      return;
    }
    const rows = data.rows || [];
    if (!rows.length) sheet.body.append(el("p", {text: data.decks?.length ? "No cards are missing from these Planned lists." : "There are no saved Planned decks to count yet."}));
    else sheet.body.append(el("ul", {}, rows.map(row => el("li", {},
      el("strong", {text: `${row.quantity} ${row.name}`}),
      el("span", {class: "sub", text: " — "}), (row.decks || []).map((deck, index) => [index ? ", " : "",
        el("a", {href: deckHref(deck.id), text: deck.title})])))));
    const text = rows.map(row => `${row.quantity} ${row.name}`).join("\n");
    if (text) sheetActions(sheet, [close,
      {text: "Copy combined shortages", kind: "primary", onclick: async event => {
        if (!current() || !event.currentTarget.isConnected) return;
        try {
          if (!navigator.clipboard?.writeText) throw Error("Clipboard unavailable");
          await navigator.clipboard.writeText(text);
          if (current()) toast("Combined shortages copied.");
        } catch (_) {
          if (!current()) return;
          const area = el("textarea", {readonly: true, rows: 12, class: "export-copy", "aria-label": "Cards list to copy"});
          area.value = text;
          sheet.body.append(area);area.focus();area.select();
        }
      }}]);
  }
  await count();
  return sheet;
}
