/* Public references, a Game Changer chip and known two-card combos (E9-S37), independently guarded own copies,
   and card addresses over the current page. */
"use strict";

let cardAddressUnderlay = null;
let cardAddressPending = null;

function viewerCommanderContext() {
  if (typeof parseHash !== "function") return false;
  const { path, params } = parseHash();
  return params.get("commander") === "1" || params.get("kind") === "commander"
    || [params.get("id"), params.get("a"), params.get("b")].some(id => /(?:^|\/)commander\//.test(id || ""))
    || path === "commanders";
}
function viewerCardHref(card) {
  const q = new URLSearchParams({ name: card.name });
  const shown = /^https:\/\/scryfall\.com\/card\/([^/]+)\/([^/?#]+)$/.exec(card.scryfall_url || "")
    || /^\/img\/([^/]+)\/([^/]+)\//.exec(card.img || "");
  if (shown) {
    try { q.set("set", decodeURIComponent(shown[1])); q.set("number", decodeURIComponent(shown[2])); }
    catch (error) { q.delete("set"); q.delete("number"); }
  }
  if (viewerState?.commander) q.set("commander", "1");
  return `#/card?${q}`;
}
function viewerReferencePart(card) {
  const link = (href, text) => el("a", { href, target: "_blank", rel: "noopener noreferrer", text });
  return el("div", { class: "viewer-reference" },
    /^https:\/\/scryfall\.com\/(?:card\/[^?#]+|search\?[^#]+)$/.test(card.scryfall_url || "") ? link(card.scryfall_url, "Open on Scryfall") : null,
    viewerState?.commander && /^https:\/\/edhrec\.com\/cards\/[a-z0-9-]+$/.test(card.edhrec_url || "")
      ? link(card.edhrec_url, "Open on EDHREC") : null,
    el("a", { href: viewerCardHref(card), text: "Card link" }));
}
function viewerCopiesPart(card) {
  const space = viewerUseSpace();
  if (!space || !card.name) return null;
  const owner = viewerState, profile = state.profile, profileId = profile?.id, profileSpace = profile?.space || HOME_SPACE;
  const token = routeToken, hash = location.hash;
  const content = el("div", { class: "viewer-copies-body" });
  const fold = el("details", { class: "viewer-copies" }, el("summary", { text: "Your copies" }), content);
  let pending = false, loaded = false;
  const here = () => viewerState === owner && state.profile === profile && profileId === state.profile?.id
    && profileSpace === (state.profile?.space || HOME_SPACE) && routeToken === token && location.hash === hash
    && viewerUseSpace() === space && seesInventory(space) && fold.isConnected
    && viewerDom.dialog.open && viewerDom.text.contains(fold) && owner.items[owner.index]?.card === card;
  const read = async () => {
    if (!here() || pending || loaded || !fold.open) return;
    pending = true; clear(content).append(el("p", { text: "Getting your copies…" }));
    try {
      const answer = await api(`/api/cards/copies?${new URLSearchParams({ name: card.name, space })}`);
      if (!here()) return;
      const rows = Array.isArray(answer.printings) ? answer.printings : [];
      clear(content).append(rows.length ? el("ul", {}, rows.map(row => el("li", {},
        el("span", { text: `${String(row.set || "").toUpperCase()} ${row.number || ""} · ${row.finish || "finish not recorded"} · ${plural(row.quantity, "copy", "copies")}` }),
        el("span", { class: "viewer-copy-location", text: row.location || "Location not recorded" }))))
        : el("p", { text: "No copies recorded in this collection." }));
      if (answer.note) content.append(el("p", { class: "viewer-rulings-note", text: answer.note }));
      loaded = true;
    } catch (error) {
      if (!here()) return;
      clear(content).append(el("p", { text: "Your copies couldn't load." }),
        el("button", { type: "button", class: "btn viewer-retry", text: "Try again", onclick: read }));
    } finally { pending = false; }
  };
  fold.addEventListener("toggle", read); return fold;
}
function rememberCardUnderlay() {
  if (state.profile && parseHash().path !== "card") cardAddressUnderlay = {
    profile: state.profile, hash: location.hash || "#/library", main: document.getElementById("main") };
}
function closeCardAddress() {
  cardAddressPending = null;
  if (viewerState) { viewerState.fromHistory = true; closeViewer(); }
}
function finishCardAddress(open) {
  if (open.address && !open.fromHistory && location.hash === open.address.hash && state.profile === open.address.profile)
    location.replace(open.address.base);
}
async function showCardAddress(params, token) {
  if (!state.profile) return;
  const profile = state.profile, hash = location.hash, mark = cardAddressPending = {};
  if (viewerState && viewerState.profile !== profile) { viewerState.fromHistory = true; closeViewer(); }
  const underlay = cardAddressUnderlay?.profile === profile && cardAddressUnderlay.main === document.getElementById("main")
    ? cardAddressUnderlay.hash : "#/library";
  if (underlay === "#/library" && cardAddressUnderlay?.profile !== profile) {
    syncShell("library"); showLibrary(new URLSearchParams(), token);
  }
  const here = () => cardAddressPending === mark && routeToken === token && state.profile === profile && location.hash === hash;
  const q = new URLSearchParams({ name: params.get("name") || "" });
  for (const key of ["set", "number"]) if (params.has(key)) q.set(key, params.get(key));
  try {
    const answer = await api(`/api/cards/lookup?${q}`);
    if (!here()) return;
    openCardViewer([answer.card], 0, { commander: params.get("commander") === "1", address: { profile, hash, base: underlay } });
  } catch (error) {
    if (!here()) return;
    openCardViewer([{ name: params.get("name") || "Card", no_image: "This card couldn't be opened. Close and open the link again to retry.",
      oracle_text: "This card couldn't be opened from the current card data." }], 0, { address: { profile, hash, base: underlay } });
  }
}

// ------------------------------------------------- Game Changer and combos (E9-S37)

const viewerCombos = new Map(); // card name -> the promise of its combos' answer, for one opening of the page
const VIEWER_COMBO_URL = /^https:\/\/commanderspellbook\.com\/combo\/[A-Za-z0-9-]+\/$/;
const VIEWER_COMBO_SOURCE = /^https:\/\/commanderspellbook\.com\/$/;

function viewerGameChangerChip() {
  return el("span", { class: "chip chip-outline chip-gc viewer-gc", text: "Game Changer",
    title: "Scryfall flags this card as a Commander Game Changer" });
}
/** A card's Game Changer chip and its known two-card combos (E9-S37: a commander across the table), public card
 * data from the PC (GET /api/cards/combos): no deck, space or network fetch. The chip shows at once from the card's
 * own flag, else when the answer says so; the combos are a fold, its count in its summary. Each name is asked
 * once an opening of the page (a failure is asked again next time). */
function viewerCombosPart(card) {
  const name = card && card.name;
  const slot = el("div", { class: "viewer-gc-slot" }, card && card.game_changer === true ? viewerGameChangerChip() : null);
  const body = el("div", { class: "viewer-combos-body" });
  const box = el("div", { class: "viewer-combos" }, slot, body);
  if (!name) return box;
  let answer = viewerCombos.get(name);
  if (!answer) {
    answer = api(`/api/cards/combos?${new URLSearchParams({ name })}`).catch((error) => {
      viewerCombos.delete(name);
      return { error };
    });
    viewerCombos.set(name, answer);
  }
  answer.then((data) => {
    if (!box.isConnected || !data || typeof data !== "object") return;
    if (data.game_changer === true && !slot.children.length) slot.append(viewerGameChangerChip());
    add(clear(body), [viewerCombosParts(data)]);
  });
  return box;
}
/** The words for viewerCombosPart's answer (or {error}): a list that couldn't be read says combos weren't checked,
 * never that there are none. */
function viewerCombosParts(data) {
  const note = (text) => el("p", { class: "viewer-rulings-note", text });
  if (data.error) return data.error.status === 404 ? null : note("Combos couldn't load. Open the card again to retry.");
  if (data.checked !== true || !Array.isArray(data.combos)) {
    return note(data.checked === false && typeof data.reason === "string" && data.reason
      ? data.reason : "Combos weren't checked.");
  }
  const list = data.combos;
  const total = Number.isInteger(data.total) && data.total >= list.length ? data.total : list.length;
  const floor = (n) => (Number.isInteger(n) && n > 1 ? `Bracket ${n} or higher` : "Any bracket");
  const piece = (p, i) => [i ? " and " : "", String((p && p.name) || "Unknown card"),
    p && p.must_be_commander === true ? " (must be the commander)" : ""];
  const credit = el("p", { class: "viewer-rulings-note" }, "From ",
    VIEWER_COMBO_SOURCE.test(data.source_url || "")
      ? el("a", { href: data.source_url, target: "_blank", rel: "noopener noreferrer",
        text: data.credit || "Commander Spellbook's combo list" })
      : data.credit || "Commander Spellbook's combo list",
    data.date ? `, its list of ${data.date}` : "", ".");
  return el("details", { class: "viewer-rulings-fold viewer-combos-fold" },
    el("summary", {}, `Known two-card combos with this card (${total})`),
    list.length ? el("ol", { class: "viewer-rulings-list" }, list.map((c) => el("li", { class: "viewer-ruling viewer-combo" },
      el("p", { class: "viewer-ruling-text" }, "With ", (Array.isArray(c.others) ? c.others : []).map(piece),
        c.must_be_commander === true ? "; this card must be the commander" : ""),
      el("p", { class: "viewer-ruling-meta", text: [
        ...(Array.isArray(c.results) ? c.results.map(String) : []),
        Number.isInteger(c.more_results) && c.more_results > 0 ? `${c.more_results} more` : null,
        c.standalone === false ? "needs a payoff" : null, floor(c.bracket_floor)].filter(Boolean).join(" · ") }),
      VIEWER_COMBO_URL.test(c.url || "")
        ? el("a", { href: c.url, target: "_blank", rel: "noopener noreferrer", text: "Open on Commander Spellbook" }) : null)))
      : note("None in the list."),
    list.length < total ? note(`The ${list.length} most serious shown, of ${total}.`) : null,
    credit);
}
