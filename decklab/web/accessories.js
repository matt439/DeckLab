/* The Accessories page (#/accessories): the sleeves, deck boxes and playmats saved in Deck Lab,
 * with their pictures, which built deck or intact product uses each, and the sleeves and deck box of
 * each product kept intact. Works on phones as well as desktops.
 *
 * Also the pieces other pages use (deck.js, library.js, assembly.js and the editor):
 *     openAccessorySheet({kind, onSaved})   add an accessory (or, with row, edit one) in a sheet
 *     accessoryThumb(ref, px)               a row's or Ref's picture (only its crop, if any), with a text fallback
 *     kitPicker({holder, field, need, current, holderSha, onPicked})   choose a holder's sleeves or deck box
 *     kitChip(kit, field)                   "75 needed · 100 owned · 25 spare", "15 sleeves short" or "Too small: holds 80"
 *
 * Every write goes to /api/accessories/... (lib/api/accessories.py), which checks the list's sha256 (of
 * the rows this person sees): a list changed meanwhile answers 409 with the latest list, and the sheet offers to
 * put the changes back on top of it. Writes stay tied to the person and page that started them. */
"use strict";

const ACC_KINDS = {
  sleeves: { title: "Sleeves", one: "Sleeves", unit: ["sleeve", "sleeves"], add: "+ Add new sleeves" },
  deck_box: { title: "Deck boxes", one: "Deck box", unit: ["box", "boxes"], add: "+ Add a new deck box" },
  playmat: { title: "Playmats", one: "Playmat", unit: ["playmat", "playmats"], add: "+ Add a new playmat" },
};
const ACC_FILTERS = [["all", "All"], ["sleeves", "Sleeves"], ["deck_box", "Deck boxes"], ["playmat", "Playmats"]];
const ACC_ROW_KEYS = ["kind", "owner", "brand", "name", "colour", "quantity", "capacity", "crop", "link", "image_source", "notes"];
const ACC_FIELD_WORDS = { kind: "Kind", owner: "Whose", brand: "Brand", name: "Name", colour: "Colour", quantity: "Quantity", capacity: "Holds", crop: "Crop",
  link: "Link", image_source: "Picture address", notes: "Notes" };
const ACC_LIMITS = { brand: 40, name: 80, colour: 40, notes: 300, link: 500 };     // the server's limits
const ACC_SLEEVE_PACKS = [50, 60, 100];
const ACC_MIN_CROP = 0.02;          // the server's smallest crop width or height (a fraction of the picture)


// ------------------------------------------------------------ shared pieces

/** A holder id as the server keeps it: a product deck ("product/<stem>/<deck>") is its whole product. */
function accHolder(id) {
  return id && id.startsWith("product/") ? id.split("/").slice(0, 2).join("/") : id;
}

function accQuantity(kind, quantity) {
  const unit = (ACC_KINDS[kind] || ACC_KINDS.playmat).unit;
  return plural(quantity, unit[0], unit[1]);
}

/** The crop an image_url carries ("...#crop=x,y,w,h", lib/accessories.image_url) as [x, y, w, h]
 * fractions of the picture, or null for the whole picture. */
function accCropOf(url) {
  const at = typeof url === "string" ? url.indexOf("#crop=") : -1;
  if (at < 0) return null;
  const parts = url.slice(at + 6).split(",").map(Number);
  return parts.length === 4 && parts.every((n) => Number.isFinite(n) && n >= 0 && n <= 1) && parts[2] > 0 && parts[3] > 0
    ? parts : null;
}

/** url without its crop, or with crop ("x,y,w,h"; blank: none) instead. */
function accWithCrop(url, crop = "") {
  const bare = String(url || "").split("#")[0];
  return crop ? `${bare}#crop=${crop}` : bare;
}

/** The address an <img> loads an /accessory-img/ picture from: url without its crop, and on the home network
 * with the profile chosen as &viewer=<id>. An <img> sends no X-Deck-Lab-Viewer header, so this is how the
 * server knows whose pictures to show (a person with their own space none, a home member their own and the shared ones); an address per
 * viewer also keeps a shared iPad's browser cache from showing one profile's picture to another. Through the
 * tunnel the login decides, so nothing is added. Comparisons of two pictures use accWithCrop, not this. */
function accImgSrc(url) {
  const bare = accWithCrop(url);
  if (state.remote || !state.profile || !bare.startsWith("/accessory-img/")) return bare;
  return `${bare}${bare.includes("?") ? "&" : "?"}viewer=${encodeURIComponent(state.profile.id)}`;
}

// Stroke icons for a deck box or playmat with no picture (24 px, drawn in currentColor).
const ACC_PLACEHOLDER_ICONS = {
  deck_box: "M5 8h14v12H5zM5 8l2-4h10l2 4M10 12h4",
  playmat: "M3 7h18v10H3zM7 11h4",
};

/** What stands in a picture's place (no picture, or one that won't load): sleeves a card-shaped swatch of their
 * colour (when it's one the browser knows), a deck box or playmat its stroke icon, anything else of unknown kind
 * its name's first letter in a small box and "No picture" in a large one. */
function accThumbPlaceholder(ref, label, small) {
  const kind = ref && ref.kind;
  const words = small ? null : el("span", { class: "sr-only", text: "No picture" });
  if (kind === "sleeves") {
    const colour = String(ref.colour || "").trim();
    const known = colour && typeof CSS !== "undefined" && CSS.supports && CSS.supports("color", colour);
    return el("span", { class: "acc-thumb-fallback acc-thumb-swatch", style: known ? `--acc-swatch: ${colour}` : null },
      words);
  }
  if (ACC_PLACEHOLDER_ICONS[kind]) {
    return el("span", { class: "acc-thumb-fallback acc-thumb-icon" },
      svgEl("svg", { viewBox: "0 0 24 24", width: 24, height: 24, "aria-hidden": "true", focusable: "false" },
        svgEl("path", { d: ACC_PLACEHOLDER_ICONS[kind] })), words);
  }
  return el("span", { class: "acc-thumb-fallback", "aria-hidden": small ? "true" : null,
    text: small ? (label.trim()[0] || "?").toUpperCase() : "No picture" });
}

/** A row's (or a Ref's) picture in a square box of px (none: as wide as its container), only its crop
 * when it has one. The name is always shown beside it as text, so the picture is decorative; a picture
 * that won't load shows "No picture" (or, in a small box, the name's first letter) instead. */
function accessoryThumb(ref, px, localPreview = false) {
  // Nothing chosen (no ref, or only words for the slot such as {label: "Sleeves"}): a dashed empty slot.
  if (!ref || !(ref.value || ref.id || ref.name || ref.image_url)) {
    return el("span", { class: px ? "acc-thumb acc-slot-none" : "acc-thumb acc-thumb-fill acc-slot-none",
      style: px ? `--acc-thumb: ${px}px` : null, title: "None chosen" },
    el("span", { class: "sr-only", text: "None chosen" }));
  }
  const label = String((ref && (ref.label || ref.name || ref.value)) || "");
  const small = Boolean(px) && px < 80;
  const fallback = accThumbPlaceholder(ref, label, small);
  const box = el("span", { class: px ? "acc-thumb" : "acc-thumb acc-thumb-fill",
    style: px ? `--acc-thumb: ${px}px` : null }, fallback);
  const url = ref && ref.image_url;
  if (typeof url === "string" && (url.startsWith("/accessory-img/")
      || localPreview && /^data:image\/(?:jpeg|png|webp);base64,/.test(accWithCrop(url)))) {
    const crop = accCropOf(url);
    const img = el("img", { src: accImgSrc(url), alt: "", loading: "lazy", decoding: "async", width: px || 240,
      height: px || 240, onerror: () => { (frame || img).hidden = true; fallback.hidden = false; } });
    fallback.hidden = true;
    let frame = null;
    if (crop) {
      // The frame has the crop's shape; the picture inside is scaled and moved so only the crop shows.
      const [x, y, w, h] = crop;
      Object.assign(img.style, { width: `${100 / w}%`, height: `${100 / h}%`, left: `${(-100 * x) / w}%`,
        top: `${(-100 * y) / h}%` });
      frame = el("span", { class: "acc-crop", style: "visibility: hidden" }, img);
      const fit = () => {
        if (!img.naturalWidth || !img.naturalHeight) return;
        const ratio = (w * img.naturalWidth) / (h * img.naturalHeight);
        frame.style.aspectRatio = String(ratio);
        frame.classList.toggle("acc-crop-tall", ratio < 1);
        frame.style.visibility = "";
      };
      img.addEventListener("load", fit);
      if (img.complete) fit();
    }
    box.append(frame || img);
  }
  return box;
}

/** A status chip for a kit's sleeves (or, with field "deck_box", its deck box): "75 needed · 100 owned ·
 * 25 spare", "15 sleeves short", or why it can't be checked. null when there's nothing to say. */
function kitChip(kit, field = "sleeves") {
  const ref = kit && kit[field];
  if (!ref) return null;
  if (ref.state === "kind_mismatch") return status("warn", field === "sleeves" ? "Not sleeves" : "Not a deck box");
  if (ref.state === "text") return status("plain", "Not in the accessories list");
  if (field !== "sleeves") {
    if (ref.quantity == null) return null;
    if (ref.capacity != null && kit.need != null && kit.need > ref.capacity) {
      return status("warn", `Too small: holds ${ref.capacity}, ${plural(kit.need, "card")} here`);
    }
    const holds = ref.capacity != null ? `Holds ${ref.capacity} · ` : "";
    return status("plain", `${holds}${accQuantity("deck_box", ref.quantity)} owned`);
  }
  if (kit.short) return status("warn", `${plural(kit.short, "sleeve")} short`);
  if (kit.need == null || ref.quantity == null) return null;
  return status("good", `${kit.need} needed · ${ref.quantity} owned · ${kit.spare || 0} spare`);
}

/** The safe link of a row: only http(s), shown as a link and never fetched by the page. "Shop page", or
 * "Picture" when the link pasted was the picture itself (a shop that blocks downloads). */
function accLink(row) {
  const link = row && row.link;
  if (typeof link !== "string" || !/^https?:\/\//i.test(link)) return null;
  return sourceLink({ link: { url: link, title: accLinkIsPicture(row) ? "Picture" : "Shop page" } }, "link");
}

/** True when a row's link is a picture rather than a page: the address its picture came from, or one
 * whose path ends in a picture's extension. */
function accLinkIsPicture(row) {
  if (row.image_source && row.link === row.image_source) return true;
  try {
    return /\.(jpe?g|png|webp|gif|avif)$/i.test(new URL(row.link).pathname);
  } catch (error) {
    return false;
  }
}

/** What a holder needs as a kit (for kitChip), from the GET answer's product entry. */
function accProductKit(product) {
  const ref = product.sleeves;
  const linked = ref && ref.state === "linked";
  return { sleeves: ref, deck_box: product.deck_box, need: product.need,
    short: linked ? Math.max(0, product.need - ref.quantity) : 0,
    spare: linked ? Math.max(0, ref.quantity - product.need) : 0 };
}

/** The words for whose an accessory is, from a GET item or {owner}: "Shared", or null for the viewer's own
 * (the only other kind it's shown). */
function accOwnerWords(item) {
  return item.owner === "shared" ? "Shared" : state.profile && item.owner === state.profile.id ? null
    : item.owner_name || item.owner || null;
}

/** The owners a new or edited row may have ([{id, name}], GET's "owners"): the viewer and Shared. */
function accOwnerChoices(data) {
  const listed = data && Array.isArray(data.owners) ? data.owners : [];
  if (listed.length) return listed;
  return [...(state.profile ? [{ id: state.profile.id, name: state.profile.name }] : []), { id: "shared", name: "shared" }];
}

/** The other holders of a row ([{holder, title}]; holder null for one the viewer can't see) and whether that
 * makes it taken. Sleeves are never taken: one design may sleeve several decks and products, and it's up to
 * the players not to play two of them at once. A deck box is taken once as many holders as there are boxes
 * have it. none: a deck box whose quantity is 0, which can't be chosen whoever holds it (nothing to move). */
function accTaken(item, holder) {
  const others = (item.used_by || []).filter((h) => accHolder(h.holder) !== holder);
  const none = item.kind === "deck_box" && Number(item.quantity) === 0;
  return { others, none, taken: item.kind === "sleeves" ? false : none || others.length >= item.quantity };
}

/** A picker tile's words for a row others have: "None left (quantity 0)", "Also used by Boros Burn, one of
 * Sam's decks" (sleeves, which can be shared) or "In use: Boros Burn" (a deck box with none free). */
function accTakenWords({ others, none, taken }) {
  if (none) return "None left (quantity 0)";
  const names = others.map((h) => h.title).join(", ");
  return taken ? `In use: ${names}` : `Also used by ${names}`;
}

/** "Sam changed the accessories list 7:42 pm today." from a 409's conflict. */
function accConflictTitle(conflict) {
  const when = conflict && conflict.when ? Date.parse(conflict.when) : NaN;
  if (conflict && conflict.by && !Number.isNaN(when)) {
    return `${conflict.by} changed the accessories list ${timeWords(when)}`;
  }
  return "The accessories list changed after you opened it";
}


// --------------------------------------------------------------- the page

function showAccessories(token) {
  return load("/api/accessories", token, (data) => drawAccessories(data, token),
    { title: "The accessories list couldn't be loaded" });
}

function accessoriesActive(view) {
  return view.token === routeToken && view.root.isConnected && state.profile && state.profile.id === view.profile;
}

function drawAccessories(data, token) {
  const root = el("div", { class: "acc-page" });
  // Each home profile sees and changes its own accessories and the shared ones (lib/permissions.py).
  const view = { root, token, profile: state.profile.id, seq: 0, data, busy: false, canEdit: mayDo("accessories"),
    filter: local.get("accessories.filter") || "all" };
  if (!ACC_FILTERS.some(([key]) => key === view.filter)) view.filter = "all";
  view.message = el("div", { class: "acc-message", role: "status", "aria-live": "polite" });
  view.notices = el("div");
  view.products = el("div", { class: "acc-panels" });
  view.lists = el("div");
  view.filterButtons = ACC_FILTERS.map(([key, text]) => el("button", { type: "button", "data-filter": key,
    "aria-pressed": String(view.filter === key), text,
    onclick: () => { view.filter = key; local.set("accessories.filter", key); updateAccessories(view); } }));
  add(root, [
    ...pageHead({ title: routeH1("accessories"), description: "Sleeves, deck boxes and playmats, and which deck uses each.",
      primary: view.canEdit ? el("button", { type: "button", class: "btn btn-primary acc-mutate", text: "Add",
        "data-focus": "add", onclick: () => addAccessory(view) }) : null,
      more: [{ label: "Refresh", onclick: () => refreshAccessories(view) }] }),
    view.canEdit ? null : el("p", { class: "sub acc-read-only", text: "Read only: you can change only your own and shared accessories." }),
    view.notices, view.message, view.products,
    el("div", { class: "segmented acc-filter", role: "group", "aria-label": "Show" }, view.filterButtons),
    view.lists,
  ]);
  $("#main").append(root);
  updateAccessories(view);
  return view;
}

/** Draw everything below the head again from view.data, keeping the scroll place and the focus. */
function updateAccessories(view) {
  const focused = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.focus : null;
  const y = window.scrollY;
  const data = view.data;
  for (const button of view.filterButtons) button.setAttribute("aria-pressed", String(button.dataset.filter === view.filter));
  clear(view.notices);
  add(view.notices, [warningsBox(data.problems, "Some accessory rows can't be read")]);
  clear(view.products);
  add(view.products, [accUnsleevedPanel(view), accProductsPanel(view)]);
  clear(view.lists);
  const items = data.items || [];
  // The head's Add is the page's one primary button.
  const addButton = () => view.canEdit
    ? el("button", { type: "button", class: "btn acc-mutate", text: "Add", onclick: () => addAccessory(view) }) : null;
  if (!items.length) view.lists.append(emptyBox("No sleeves, deck boxes or playmats yet.", addButton()));
  const owners = [...new Set(items.map((item) => item.owner || "shared"))];
  for (const owner of owners) {
    const owned = items.filter((item) => (item.owner || "shared") === owner);
    if (!owned.some((item) => view.filter === "all" || item.kind === view.filter)) continue;
    view.lists.append(el("h2", { class: "acc-owner-title", text: owned[0].owner_name || capitalise(owner) }));
    for (const [kind, words] of Object.entries(ACC_KINDS)) {
    if (view.filter !== "all" && view.filter !== kind) continue;
    const mine = owned.filter((item) => item.kind === kind);
    if (!mine.length) continue;
    const id = `acc-${owner}-${kind}-title`;
    view.lists.append(el("section", { class: "acc-section", "aria-labelledby": id },
      el("h2", { id, text: `${words.title} (${mine.length})` }),
      el("ul", { class: "acc-grid" }, mine.map((item) => accCard(view, item)))));
    }
  }
  // Rows, but none of the kind the filter shows.
  if (items.length && !view.lists.children.length) {
    view.lists.append(emptyBox(`No ${ACC_KINDS[view.filter].title.toLowerCase()} yet.`, addButton(), { live: true }));
  }
  setAccessoriesBusy(view, view.busy);
  window.scrollTo(0, y);
  const again = focused && view.root.querySelector(`[data-focus="${focused}"]`);
  if (again) again.focus({ preventScroll: true });
}

/** One line about a row: "200 sleeves · black", "2 boxes · hold 100 cards", "Playmat · blue". */
function accMetaWords(item) {
  const amount = item.kind === "playmat" && Number(item.quantity) === 1 ? null : accQuantity(item.kind, item.quantity);
  const holds = item.capacity != null ? `${item.quantity === 1 ? "holds" : "hold"} ${plural(item.capacity, "card")}` : null;
  return [amount, holds, item.colour || null].filter(Boolean).join(" · ");
}

/** One accessory as a tile: its picture, name and one line, then chips only for what's worth noticing
 * (whose it is when it isn't the viewer's, too few) and the decks that use it; an unused one stays plain. A
 * tap opens its sheet, where Remove sits at the bottom, or for a read-only visitor its details. */
function accCard(view, item) {
  const users = item.used_by || [];
  const name = [item.brand, item.name].filter(Boolean).join(" ");
  const owner = accOwnerWords(item);
  const chips = [
    owner ? status("plain", owner) : null,       // whose it is: a plain tag, not the on-the-way arrow
    item.short ? status("warn", item.kind === "sleeves" ? `${plural(item.short, "sleeve")} short` : `${plural(item.short, "box", "boxes")} short`) : null,
    ...users.map((h) => {
      const over = item.kind === "deck_box" && item.capacity != null && h.need > item.capacity;
      // A deck of someone else's (holder null) is named only as "one of Sam's decks", with no link.
      return h.holder ? el("a", { class: `chip ${over ? "chip-warn" : "chip-plain"} acc-user-chip`,
        href: h.kind === "product" ? "#/library?format=product" : deckHref(h.holder),
        title: over ? `${h.title}: ${plural(h.need, "card")}, more than it holds` : h.title,
        text: over ? `${h.title} · too many to fit` : h.title })
        : status("plain", capitalise(h.title));
    })].filter(Boolean);
  const body = [accessoryThumb(item, null),
    el("span", { class: "acc-tile-words" },
      el("span", { class: "acc-tile-name", title: name, text: name }),
      el("span", { class: "acc-tile-meta", text: accMetaWords(item) }))];
  return el("li", { class: "acc-card", "data-id": item.id },
    view.canEdit && item.editable !== false ? el("button", { type: "button", class: "acc-tile acc-mutate", "data-focus": `edit-${item.id}`,
      "aria-label": `Edit ${name}`, onclick: () => editAccessory(view, item) }, body)
      : el("button", { type: "button", class: "acc-tile", "aria-haspopup": "dialog", "data-focus": `see-${item.id}`,
        "aria-label": `${name}: details`, onclick: () => accDetails(view, item) }, body),
    chips.length ? el("div", { class: "chips acc-chips" }, chips) : null);
}

/** "Built decks without sleeves (N)": each built deck the viewer sees with no sleeves chosen, with Choose…. */
function accUnsleevedPanel(view) {
  const decks = (view.data.holders_options || []).filter((o) => o.kind !== "product" && !o.sleeves);
  if (!decks.length) return null;
  return el("section", { class: "panel acc-unsleeved", "aria-labelledby": "acc-unsleeved-title" },
    el("h2", { id: "acc-unsleeved-title", text: `Built decks without sleeves (${decks.length})` }),
    el("ul", { class: "acc-holder-list" }, decks.map((deck) => el("li", { class: "acc-holder" },
      accessoryThumb(null, 48),
      el("span", { class: "acc-holder-words" },
        el("a", { href: deckHref(deck.id), text: deck.title }),
        el("small", { text: [plural(deck.need, "sleeve") + " needed", deck.deck_box ? null : "no deck box either"].filter(Boolean).join(" · ") })),
      view.canEdit && canEditDeckId(deck.id) ? el("button", { type: "button", class: "btn acc-mutate", text: "Choose…",
        "aria-label": `Choose sleeves for ${deck.title}`, "data-focus": `sleeve-${deck.id}`,
        onclick: () => accChoose(view, { holder: deck.id, title: deck.title, need: deck.need, holder_sha256: deck.holder_sha256 }, "sleeves", null) }) : null))));
}

/** The products kept intact: one sleeve design and one deck box each, chosen with Choose… (the kit picker,
 * which asks before moving a design from another deck). */
function accProductsPanel(view) {
  const products = view.data.products || [];
  if (!products.length) return null;
  return el("section", { class: "panel acc-products", "aria-labelledby": "acc-products-title" },
    el("h2", { id: "acc-products-title", text: "Products kept intact" }),
    el("ul", { class: "acc-product-list" }, products.map((product) => {
      const kit = accProductKit(product);
      return el("li", { class: "acc-product" },
        el("p", { class: "acc-product-head" }, el("b", { text: product.title }), el("small", { text: `${plural(product.need, "sleeve")} needed` })),
        el("div", { class: "acc-product-picks" }, ["sleeves", "deck_box"].map((field) => {
          const ref = product[field];
          const words = ref ? ref.label || ref.name || ref.value || "" : "None chosen";
          return el("div", { class: "acc-product-pick" },
            accessoryThumb(ref, 56),
            el("span", { class: "acc-holder-words" },
              el("small", { text: ACC_KINDS[field].one }),
              el("span", { class: ref ? null : "acc-none-words", text: words }),
              kitChip(kit, field)),
            view.canEdit ? el("button", { type: "button", class: "btn acc-mutate", text: "Choose…",
              "data-focus": `${field}-${product.holder}`,
              "aria-label": `Choose ${field === "sleeves" ? "sleeves" : "a deck box"} for ${product.title}`,
              onclick: () => accChoose(view, product, field, ref) }) : null);
        })));
    })));
}

/** Open the kit picker for a holder (a built deck or an intact product); its save shows the list again. */
function accChoose(view, holder, field, current) {
  if (!accessoriesActive(view) || view.busy) return;
  kitPicker({ holder: holder.holder, field, need: holder.need, current, holderSha: holder.holder_sha256, title: holder.title,
    onPicked: (answer) => {
      if (!accessoriesActive(view)) return;
      if (answer && answer.data) accShow(view, answer.data, null, answer.warnings);
      else refreshAccessories(view);
    } });
}

function setAccessoriesBusy(view, busy) {
  view.busy = busy;
  view.root.setAttribute("aria-busy", String(busy));
  for (const control of view.root.querySelectorAll(".acc-mutate")) {
    control.disabled = busy || control.dataset.blocked === "true";
  }
}

/** Show a new answer's list: the page drawn again, and what happened said (and toasted). */
function accShow(view, data, message, warnings) {
  view.data = data;
  view.busy = false;
  state.library = null;               // the library shows each deck's sleeves
  updateAccessories(view);
  clear(view.message);
  if (message) {
    view.message.append(el("p", { text: message }));
    toast(message);
  }
  add(view.message, [warningsBox(warnings, "Worth checking")]);
}

async function refreshAccessories(view) {
  if (!accessoriesActive(view) || view.busy) return;
  const seq = ++view.seq;
  setAccessoriesBusy(view, true);
  clear(view.message).append(loadingBox("Refreshing the list…", { small: true }));
  try {
    const data = await api("/api/accessories");
    if (!accessoriesActive(view) || seq !== view.seq) return;
    accShow(view, data, "The accessories list is up to date.");
  } catch (error) {
    if (accessoriesActive(view)) clear(view.message).append(errorBox("The list couldn't be refreshed", error, () => refreshAccessories(view), null));
  } finally {
    if (accessoriesActive(view)) setAccessoriesBusy(view, false);
  }
}

function addAccessory(view) {
  if (!accessoriesActive(view) || view.busy) return;
  const kind = view.filter !== "all" ? view.filter : "sleeves";
  openAccessorySheet({ kind, sha256: view.data.sha256, owners: accOwnerChoices(view.data), ...accSheetHooks(view) });
}

function editAccessory(view, item) {
  if (!accessoriesActive(view) || view.busy || item.editable === false) return;
  const users = item.used_by || [];
  const words = ACC_KINDS[item.kind] || ACC_KINDS.playmat;
  openAccessorySheet({ kind: item.kind, row: item, sha256: view.data.sha256, owners: accOwnerChoices(view.data),
    ...accSheetHooks(view), onRemove: () => removeAccessory(view, item),
    removeBlocked: users.length ? `In use, so it can't be removed. Choose ${item.kind === "sleeves" ? "other sleeves"
      : `another ${words.one.toLowerCase()}`} for ${users.map((h) => h.title).join(" and ")} first.` : null });
}

/** A read-only visitor's sheet for one accessory: its picture, what it is, its notes and shop link, and the
 * decks that use it. Nothing in it changes anything. */
function accDetails(view, item) {
  if (!accessoriesActive(view)) return null;
  const name = [item.brand, item.name].filter(Boolean).join(" ");
  const sheet = openAccessoryDialog({ title: name || item.label || item.id, wide: true });
  const users = item.used_by || [];
  const link = accLink(item);
  const owner = accOwnerWords(item);
  add(sheet.body, [el("div", { class: "acc-details" },
    accessoryThumb(item, null),
    el("div", { class: "acc-details-words" },
      el("p", { text: [accMetaWords(item), owner].filter(Boolean).join(" · ") || (ACC_KINDS[item.kind] || ACC_KINDS.playmat).one }),
      item.notes ? el("p", { class: "acc-details-notes", text: item.notes }) : null,
      link ? el("p", {}, link) : null,
      el("h3", { text: users.length ? "Used by" : "Not used by a deck" }),
      users.length ? el("ul", {}, users.map((h) => el("li", {}, h.holder
        ? el("a", { href: h.kind === "product" ? "#/library?format=product" : deckHref(h.holder), text: h.title,
          onclick: () => sheet.close() })
        : capitalise(h.title)))) : null))]);
  sheetActions(sheet, [{ text: "Close", value: "close", onclick: () => sheet.close() }]);
  return sheet;
}

/** What a sheet opened from the page does with its answer, or with the latest list after a conflict. */
function accSheetHooks(view) {
  return {
    onSaved: (answer, words) => { if (accessoriesActive(view)) accShow(view, answer.data, words, answer.warnings); },
    onLatest: (latest) => { if (accessoriesActive(view)) accShow(view, latest, "This is the accessories list as it is now."); },
  };
}

async function removeAccessory(view, item) {
  if (!accessoriesActive(view) || view.busy || item.editable === false) return;
  const choice = await askAccessoryChoice(`Remove ${item.label}?`,
    ["It comes off the accessories list, with its picture."],
    [{ text: "Remove", kind: "danger", value: "remove" }, { text: "Keep it", value: null }]);
  if (choice !== "remove" || !accessoriesActive(view) || view.busy) return;
  let sha = view.data.sha256;
  for (;;) {
    const seq = ++view.seq;
    setAccessoriesBusy(view, true);
    clear(view.message).append(loadingBox(`Removing ${item.label}…`));
    try {
      const answer = await apiWrite("/api/accessories/save", { sha256: sha, action: "remove", id: item.id,
        base: accBase(item) });
      if (!accessoriesActive(view) || seq !== view.seq) return;
      accShow(view, answer.data, `${item.label} removed.`, answer.warnings);
      return;
    } catch (error) {
      if (!accessoriesActive(view) || seq !== view.seq) return;
      setAccessoriesBusy(view, false);
      const latest = error.data && error.data.latest;
      if (error.status !== 409 || !latest) {
        clear(view.message).append(el("div", { class: "box box-crit" }, el("p", { text: error.message })));
        toast(error.message);
        return;
      }
      if (!(latest.items || []).some((row) => row.id === item.id)) {
        accShow(view, latest, "Already removed.");
        return;
      }
      clear(view.message);
      const again = await askAccessoryChoice(accConflictTitle(error.data.conflict), [error.message, "Nothing was removed yet."],
        [{ text: "Remove it from the latest list", kind: "primary", value: "again" }, { text: "Keep it", value: null }]);
      if (!accessoriesActive(view)) return;
      if (again !== "again") { accShow(view, latest, ""); return; }
      view.data = latest;
      sha = latest.sha256;
    }
  }
}

// ----------------------------------------------------- the add and edit sheet

/** The row as the page loaded it, as save's "base" (and for re-applying after a conflict). */
function accBase(row) {
  return Object.fromEntries(ACC_ROW_KEYS.map((key) => [key, row[key] == null ? "" : row[key]]));
}

/** The sheet's picture as saved: {mode: "keep", crop} for a row with a picture, else {mode: "none", crop: ""}. */
function accKeptPicture(row) {
  return row && row.image_url ? { mode: "keep", crop: row.crop || "" } : { mode: "none", crop: "" };
}

/** Add an accessory ({kind}: the kind to start with), or edit one ({row}: a GET item). sha256: the list's,
 * as the caller loaded it (left out: it's fetched first). onSaved(answer, words) gets the save's answer;
 * onLatest(latest) the list as it is now, when a conflict's changes are discarded. lockKind: a page's
 * guess never changes the kind (a picker for one kind opened it). owners: who it may belong to ([{id,
 * name}]: the viewer and shared), owner the one a new row starts with (the viewer's own by default).
 * Returns the sheet. */
function openAccessorySheet({ kind = "sleeves", onSaved, onLatest, row = null, sha256, lockKind = false,
  owners = null, owner = null, onRemove = null, removeBlocked = null } = {}) {
  const editing = Boolean(row);
  let ctx;
  const sheet = openAccessoryDialog(editing ? `Edit ${row.label || row.name}` : "Add accessory",
    { wide: true, onClose: () => accDisposeSheet(ctx) });
  ctx = { sheet, row, editing, lockKind, sha256, onSaved, onLatest, busy: false, touched: new Set(), inputs: {},
    profile: state.profile?.id, token: routeToken,
    owners: owners || accOwnerChoices(null), owner,
    base: row ? accBase(row) : null,
    pic: accKeptPicture(row) };
  accessorySheets.add(ctx);
  ctx.form = el("form", { class: "acc-form", novalidate: true,
    onsubmit: (event) => { event.preventDefault(); saveFromSheet(ctx); } });
  ctx.message = el("div", { class: "acc-sheet-message", role: "status", "aria-live": "polite" });
  ctx.picture = el("div", { class: "acc-picture" });
  const link = el("input", { id: `acc-link-${sheet.heading.id}`, type: "url", inputmode: "url", autocomplete: "off",
    autocapitalize: "none", spellcheck: "false", maxlength: ACC_LIMITS.link, placeholder: "Product or picture link",
    value: row ? row.link || "" : "" });
  ctx.inputs.link = link;
  ctx.find = el("button", { type: "button", class: "btn acc-sheet-mutate", text: "Find picture",
    onclick: () => findPicture(ctx) });
  link.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); findPicture(ctx); }
  });
  ctx.linkField = el("div", { class: "acc-link-field" },
    el("label", { class: "field", for: link.id }, el("span", { text: "Link to the product or its picture" }), link),
    ctx.find);
  add(ctx.form, [
    !editing ? el("p", { class: "sub", text: "Add sleeves, a deck box or a playmat. Paste a shop link and Deck Lab finds its picture." }) : null,
    ctx.linkField, accPhotoControls(ctx), ctx.message, ctx.picture, accFields(ctx, row, row ? row.kind : kind),
    editing && removeBlocked ? el("p", { id: `acc-why-${sheet.heading.id}`, class: "field-hint acc-why", text: removeBlocked }) : null]);
  sheet.body.append(ctx.form);
  ctx.onRemove = editing ? onRemove : null;
  ctx.removeBlocked = removeBlocked;
  accSheetFoot(ctx);
  drawPicture(ctx);
  accSheetFocus(ctx, link);
  return sheet;
}

/** Where the sheet starts: Add on the link field; Edit on Name, except on a touch screen, where focusing an input
 * pops the keyboard up and scrolls the sheet past its picture: there the heading takes focus and the sheet opens
 * at its top. */
function accSheetFocus(ctx, link) {
  if (!ctx.editing) { link.focus(); return; }
  if (!coarsePointer()) { ctx.inputs.name.focus(); return; }
  const heading = ctx.sheet.heading;
  heading.setAttribute("tabindex", "-1");
  heading.classList.add("acc-sheet-title");
  heading.focus({ preventScroll: true });
  ctx.sheet.body.scrollTop = 0;
}

function accFields(ctx, row, kind) {
  const grid = el("div", { class: "acc-fields" });
  const id = (key) => `acc-${key}-${ctx.sheet.heading.id}`;
  const text = (key, extra = {}) => el("input", { id: id(key), type: "text", maxlength: ACC_LIMITS[key],
    value: row ? row[key] || "" : "", autocomplete: "off", ...extra });
  const kindSelect = el("select", { id: id("kind") }, Object.entries(ACC_KINDS).map(([value, w]) =>
    el("option", { value, text: w.one })));
  kindSelect.value = kind;
  const mine = state.profile ? state.profile.id : null;
  const ownerSelect = el("select", { id: id("owner"), "aria-describedby": id("owner-hint") },
    ctx.owners.map((o) => el("option", { value: o.id, text: o.id === "shared" ? "Shared (both of us)"
      : o.id === mine ? `Mine (${o.name})` : o.name })));
  const start = row ? row.owner : ctx.owner || mine;
  ownerSelect.value = ctx.owners.some((o) => o.id === start) ? start : "shared";
  const quantity = el("input", { id: id("quantity"), type: "number", inputmode: "numeric", min: 0, max: 9999, step: 1,
    value: row ? String(row.quantity) : "", "aria-describedby": id("quantity-hint") });
  const capacity = el("input", { id: id("capacity"), type: "number", inputmode: "numeric", min: 1, max: 9999, step: 1,
    value: row && row.capacity != null ? String(row.capacity) : "", placeholder: "Not known",
    "aria-describedby": id("capacity-hint") });
  ctx.inputs = { ...ctx.inputs, kind: kindSelect, owner: ownerSelect, brand: text("brand"), name: text("name", { required: true }),
    colour: text("colour", { placeholder: "The colour or design of the backs" }), quantity, capacity, notes: text("notes") };
  for (const [key, input] of Object.entries(ctx.inputs)) {
    if (key === "link") continue;
    input.addEventListener("input", () => ctx.touched.add(key));
    input.addEventListener("change", () => { ctx.touched.add(key); if (key === "kind") accKindChanged(ctx); });
  }
  ctx.packs = el("div", { class: "chips acc-packs", role: "group", "aria-label": "Add a pack" },
    ACC_SLEEVE_PACKS.map((n) => el("button", { type: "button", class: "btn acc-pack", text: `+${n}`,
      "aria-label": `Add ${n} sleeves`, onclick: () => {
        quantity.value = String(Math.min(9999, (parseInt(quantity.value, 10) || 0) + n));
        ctx.touched.add("quantity");
      } })));
  ctx.quantityHint = el("span", { id: id("quantity-hint"), class: "field-hint" });
  const field = (key, label, input, ...after) => el("label", { class: `field acc-field-${key}`, for: input.id },
    el("span", { text: label }), input, ...after);
  add(grid, [
    field("kind", "Kind", kindSelect),
    field("owner", "Whose", ownerSelect,
      el("span", { id: id("owner-hint"), class: "field-hint", text: "Only its owner sees it; shared ones are seen by both of you. A deck uses its player's or shared ones; an “either” deck or a product only shared ones." })),
    field("brand", "Brand", ctx.inputs.brand),
    field("name", "Name", ctx.inputs.name),
    field("colour", "Colour", ctx.inputs.colour),
    el("div", { class: "field acc-field-quantity" },
      el("label", { for: quantity.id, text: "Quantity" }), quantity, ctx.packs, ctx.quantityHint),
    ctx.capacityField = field("capacity", "Holds (sleeved cards)", capacity,
      el("span", { id: id("capacity-hint"), class: "field-hint", text: "How many sleeved cards one box takes, like 80 or 100. Leave it blank if you don't know." })),
    field("notes", "Notes", ctx.inputs.notes),
  ]);
  accKindChanged(ctx);
  return grid;
}

function accKindChanged(ctx) {
  const sleeves = ctx.inputs.kind.value === "sleeves";
  ctx.packs.hidden = !sleeves;
  if (ctx.capacityField) ctx.capacityField.hidden = ctx.inputs.kind.value !== "deck_box";
  ctx.quantityHint.textContent = sleeves ? "Count every sleeve of this design, loose ones too"
    : ctx.inputs.kind.value === "deck_box" ? "How many boxes of this kind" : "";
}

/** The sheet's foot: Cancel and Save when adding; Save and, at the bottom, Remove when editing (disabled, with
 * the reason under the fields, while a deck or product uses it). */
function accSheetFoot(ctx) {
  sheetActions(ctx.sheet, [
    ctx.editing ? null : { text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: () => saveFromSheet(ctx) },
    ctx.onRemove ? { text: "Remove…", kind: "danger btn-quiet", value: "remove", disabled: Boolean(ctx.removeBlocked),
      onclick: () => { const remove = ctx.onRemove; ctx.sheet.close(); remove(); } } : null]);
  const remove = ctx.sheet.foot.querySelector('[data-action="remove"]');
  if (remove && ctx.removeBlocked) {
    remove.setAttribute("aria-describedby", `acc-why-${ctx.sheet.heading.id}`);
    remove.dataset.blocked = "true";
  }
}

/** Fill a fetch's guesses into the sheet's fields; returns the words for the fields filled. Adding, a
 * guess fills any field not typed into (a later Find picture replaces an earlier guess). Editing, the
 * saved values stay: a guess fills only a field left blank, and never the kind; nor does it change the
 * kind of a sheet opened from a picker for one kind (lockKind). */
function accApplyGuess(ctx, guess) {
  const filled = [];
  for (const key of ["kind", "brand", "name", "quantity"]) {
    const value = guess[key];
    if (value == null || value === "" || ctx.touched.has(key)) continue;
    if (key === "kind" && (!ACC_KINDS[value] || ctx.editing || ctx.lockKind)) continue;
    if (ctx.editing && String(ctx.inputs[key].value).trim() !== "") continue;
    ctx.inputs[key].value = String(value);
    filled.push(ACC_FIELD_WORDS[key].toLowerCase());
    if (key === "kind") accKindChanged(ctx);
  }
  return filled;
}

/** ["name", "brand"] -> "name and brand". */
function saidList(words) {
  return words.length < 2 ? words.join("") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
}

/** The form as a save's row, or null (with the problem said) when it can't be saved. */
function accFormRow(ctx) {
  const value = (key) => ctx.inputs[key].value.trim();
  const quantityText = value("quantity");
  const quantity = Number(quantityText);
  const isBox = ctx.inputs.kind.value === "deck_box";
  const capacityText = isBox ? value("capacity") : "";
  const capacity = Number(capacityText);
  const problem = !value("name") ? ["name", "Give it a name, like “Matte” or “Boulder 100+”."]
    : quantityText === "" || !Number.isInteger(quantity) || quantity < 0 || quantity > 9999
      ? ["quantity", "The quantity is a whole number from 0 to 9999."]
      : capacityText !== "" && (!Number.isInteger(capacity) || capacity < 1 || capacity > 9999)
        ? ["capacity", "How many it holds is a whole number from 1 to 9999 (or leave the box blank)."]
      : value("link") && !/^https?:\/\//i.test(value("link"))
        ? ["link", "The link must be a web address (or leave the box blank)."] : null;
  if (problem) {
    clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: problem[1] })));
    ctx.inputs[problem[0]].focus();
    return null;
  }
  const pic = ctx.pic;
  return { kind: ctx.inputs.kind.value, owner: ctx.inputs.owner.value, brand: value("brand"), name: value("name"), colour: value("colour"), quantity,
    capacity: capacityText === "" ? null : capacity, link: value("link"), notes: value("notes"),
    image_source: pic.mode === "staged" ? pic.image_source : pic.mode === "keep" ? (ctx.row.image_source || "") : "",
    crop: pic.mode === "none" ? "" : pic.crop || "" };
}

function accImageBody(ctx) {
  const pic = ctx.pic;
  return pic.mode === "upload" ? { upload: pic.upload }
    : pic.mode === "staged" ? { token: pic.token } : pic.mode === "keep" ? "keep" : null;
}

async function saveFromSheet(ctx) {
  if (ctx.busy || !accSheetHere(ctx)) return;
  const row = accFormRow(ctx);
  if (!row) return;
  const body = { action: ctx.editing ? "edit" : "add", row, image: accImageBody(ctx) };
  if (ctx.editing) { body.id = ctx.row.id; body.base = ctx.base; }
  accSheetBusy(ctx, true);
  try {
    if (ctx.sha256 === undefined) ctx.sha256 = (await api("/api/accessories")).sha256;
    if (!accSheetHere(ctx)) return;
    await accSend(ctx, { ...body, sha256: ctx.sha256 });
  } catch (error) {
    if (accSheetHere(ctx)) clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  } finally {
    if (accSheetHere(ctx)) accSheetBusy(ctx, false);
  }
}

/** Send a save; on success close the sheet and hand on the answer, on a conflict offer to re-apply. */
async function accSend(ctx, body) {
  if (!accSheetHere(ctx)) return;
  clear(ctx.message).append(loadingBox("Saving…"));
  try {
    const answer = await apiWrite("/api/accessories/save", body);
    if (!accSheetHere(ctx)) return;
    const label = [body.row.brand, body.row.name].filter(Boolean).join(" ");
    const words = `${label} ${body.action === "add" ? "added" : "saved"}.`;
    state.library = null;
    ctx.sheet.close();
    if (!ctx.onSaved) toast(words);
    else ctx.onSaved(answer, words);
  } catch (error) {
    if (!accSheetHere(ctx)) return;
    if (error.status === 409 && error.data && error.data.latest) { showAccessoryConflict(ctx, error, body); return; }
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  }
}

/** Put my changes (mine, from base) on top of theirs, field by field (core.js's rebaseFields). */
function rebaseAccessory(mine, base, theirs) {
  return rebaseFields(mine, base, theirs, ACC_ROW_KEYS);
}

function accRowNumbers(row) {
  return { ...row, quantity: Number(row.quantity),
    capacity: row.capacity === "" || row.capacity == null ? null : Number(row.capacity) };
}

function showAccessoryConflict(ctx, error, body) {
  if (!accSheetHere(ctx)) return;
  const latest = error.data.latest;
  const conflict = error.data.conflict || {};
  const sheet = ctx.sheet;
  sheet.heading.textContent = accConflictTitle(conflict);
  clear(sheet.body).append(ctx.message);
  clear(ctx.message);
  const discard = { text: "Discard my changes", kind: "discard", value: "discard", onclick: () => {
    if (!accSheetHere(ctx)) return; sheet.close(); if (ctx.onLatest) ctx.onLatest(latest);
  } };
  const resend = (next) => {
    if (!accSheetHere(ctx) || ctx.busy) return;
    accSheetBusy(ctx, true);
    ctx.sha256 = latest.sha256;
    clear(sheet.body).append(ctx.message);
    sheetActions(sheet, [{ text: "Saving…", kind: "primary", value: "saving", disabled: true }]);
    return accSend(ctx, { ...next, sha256: latest.sha256 }).then(() => {
      // Another error (not a conflict, which draws this again): its message shows; let the sheet be left.
      if (accSheetHere(ctx)) accSheetBusy(ctx, false);
      if (accSheetHere(ctx) && sheet.foot.querySelector('[data-action="saving"]')) {
        sheetActions(sheet, [{ text: "Try saving again", kind: "primary", onclick: () => resend(next) }, discard]);
      }
    });
  };
  sheet.body.append(el("div", { class: "box box-warn" }, el("p", { text: error.message })),
    el("p", { text: "Nothing was saved. Your changes are still here." }));
  if (body.action === "add") {
    sheet.body.append(el("p", { text: "Load the latest list and your new accessory is added to it." }));
    sheetActions(sheet, [{ text: "Load the latest and re-apply my changes", kind: "primary", onclick: () => resend(body) }, discard]);
    return;
  }
  const theirs = (latest.items || []).find((item) => item.id === body.id);
  if (!theirs) {
    sheet.body.append(el("p", { text: "It has been removed from the list since, so there's nothing left to change. Add it again to keep your changes." }));
    sheetActions(sheet, [{ text: "Add it again", kind: "primary", onclick: () => {
      ctx.editing = false;
      const { id, base, ...rest } = body;
      resend({ ...rest, action: "add", image: rest.image === "keep" ? null : rest.image });
    } }, discard]);
    return;
  }
  const { row, clashes } = rebaseAccessory(body.row, ctx.base, accBase(theirs));
  // My picture choice on top of theirs: a new picture or "no picture" (where there was one) is mine; otherwise theirs stays.
  const image = body.image && body.image !== "keep" ? body.image
    : body.image === null && ctx.row && ctx.row.image ? null : "keep";
  if (image === "keep") row.image_source = theirs.image_source || "";
  // A crop belongs to its picture: mine with a picture I chose (or none), theirs when they replaced the picture.
  if (image !== "keep") row.crop = body.row.crop || "";
  else if (accWithCrop(theirs.image_url) !== accWithCrop(ctx.row && ctx.row.image_url)) row.crop = theirs.crop || "";
  const next = () => ({ ...body, row: accRowNumbers({ ...row, image_source: image?.upload ? "" : row.image_source }),
    base: accBase(theirs), image });
  ctx.base = accBase(theirs);
  ctx.row = theirs;
  if (!clashes.length) {
    sheet.body.append(el("p", { text: "Load the latest and your changes are put back on top of it, field by field." }));
    sheetActions(sheet, [{ text: "Load the latest and re-apply my changes", kind: "primary", onclick: () => resend(next()) }, discard]);
    return;
  }
  sheet.body.append(el("p", { text: "You both changed these. Choose which to keep:" }));
  clashes.forEach((clash, n) => {
    const name = `acc-clash-${sheet.heading.id}-${n}`;
    const option = (which, value, checked) => el("label", { class: "acc-choice" },
      el("input", { type: "radio", name, value: which, checked, onchange: () => { row[clash.key] = value; } }),
      el("span", { text: `${which === "mine" ? "Yours" : "Theirs"}: ${value === "" ? "(blank)" : value}` }));
    sheet.body.append(el("fieldset", { class: "acc-clash" }, el("legend", { text: ACC_FIELD_WORDS[clash.key] }),
      option("mine", clash.mine, true), option("theirs", clash.theirs, false)));
  });
  sheetActions(sheet, [{ text: "Save with these choices", kind: "primary", onclick: () => resend(next()) }, discard]);
}


// ------------------------------------------------------------ the kit picker

/** Choose a holder's sleeves or deck box in a sheet (any device): holder is a built deck's id or a
 * product's ("product/<stem>"; a product deck's id works too), field "sleeves" or "deck_box", need the
 * sleeves its list needs, current its Ref (or value) now, holderSha the sha256 of its file as the page
 * loaded it (left out: the list's own). Sleeves another holder has ask whether to share them or move them
 * here; a deck box with none free asks to move one here. onPicked(answer)
 * gets assign's answer; title (optional) names the holder in the heading. Returns the sheet. */
function kitPicker({ holder, field = "sleeves", need = null, current = null, holderSha = null, onPicked, title = "" }) {
  const words = ACC_KINDS[field] || ACC_KINDS.sleeves;
  const what = field === "sleeves" ? "sleeves" : "deck box";
  const sheet = openAccessoryDialog(title ? `Choose ${what} for ${title}` : `Choose ${what}`, { wide: true });
  const ctx = { sheet, holder: accHolder(holder), field, need, holderSha, onPicked, words, what, busy: false,
    current: typeof current === "string" ? current : current ? current.value || current.id : "",
    message: el("div", { class: "acc-sheet-message", role: "status", "aria-live": "polite" }), grid: el("div") };
  sheet.body.append(ctx.message, ctx.grid);
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  loadKitPicker(ctx);
  return sheet;
}

async function loadKitPicker(ctx) {
  if (!accDialogHere(ctx.sheet)) return;
  clear(ctx.grid).append(loadingBox("Loading the accessories list…"));
  try {
    const data = await api("/api/accessories");
    // canEditDeckId reads the library: which other holders' kit this viewer may move here.
    if (!state.library) state.library = await api("/api/decks").catch(() => null);
    if (!accDialogHere(ctx.sheet)) return;
    ctx.data = data;
    const option = (data.holders_options || []).find((o) => o.id === ctx.holder);
    if (option) {
      ctx.owner = option.owner || null;
      ctx.current = option[ctx.field] || "";
      if (!ctx.holderSha) ctx.holderSha = option.holder_sha256;
      if (ctx.need == null) ctx.need = option.need;
    }
    drawKitPicker(ctx);
  } catch (error) {
    if (accDialogHere(ctx.sheet)) clear(ctx.grid).append(loadFailed("The accessories list", error, () => loadKitPicker(ctx)));
  }
}

function drawKitPicker(ctx) {
  // Only its owner's or shared ones (lib/accessories.py's usable); the server refuses the rest.
  const items = (ctx.data.items || []).filter((item) => item.editable !== false && item.kind === ctx.field
    && (!ctx.owner || accessoryUsable(item, ctx.owner)));
  const linked = items.some((item) => item.id === ctx.current);
  const tiles = [el("li", {}, el("button", { type: "button", class: "acc-pick-tile acc-pick-mutate",
    "aria-pressed": String(!ctx.current), onclick: () => pickKit(ctx, null) },
    accessoryThumb(null, 64),
    el("span", { class: "acc-pick-text" }, el("strong", { text: "None" }))))];
  for (const item of items) {
    const takenAs = accTaken(item, ctx.holder);
    const taken = takenAs.taken;
    const chosen = item.id === ctx.current;
    const fits = ctx.field === "sleeves" && ctx.need != null
      ? item.quantity >= ctx.need ? `${ctx.need} needed · ${item.quantity} owned · ${item.quantity - ctx.need} spare`
        : `${ctx.need} needed · ${item.quantity} owned · ${plural(ctx.need - item.quantity, "sleeve")} short`
      : item.capacity != null && ctx.need != null && ctx.need > item.capacity
        ? `Too small: holds ${item.capacity}, ${plural(ctx.need, "card")} here`
        : (item.capacity != null ? `Holds ${item.capacity} · ` : "") + accQuantity(item.kind, item.quantity);
    tiles.push(el("li", {}, el("button", { type: "button", class: "acc-pick-tile acc-pick-mutate",
      "aria-pressed": String(chosen), "data-taken": taken && !chosen ? "true" : null,
      onclick: () => pickKit(ctx, item) },
      accessoryThumb(item, 64),
      el("span", { class: "acc-pick-text" },
        el("strong", { text: item.label }),
        el("small", { text: chosen ? `Chosen · ${fits}` : fits }),
        taken && !chosen ? el("small", { class: "acc-pick-taken", text: accTakenWords(takenAs) })
          : takenAs.others.length ? el("small", { class: "acc-pick-shared", text: accTakenWords(takenAs) }) : null))));
  }
  if (mayDo("accessories")) {
    tiles.push(el("li", {}, el("button", { type: "button", class: "acc-pick-tile acc-pick-add acc-pick-mutate",
      onclick: () => addFromPicker(ctx) }, el("span", { class: "acc-pick-text" }, el("strong", { text: ctx.words.add })))));
  }
  clear(ctx.grid);
  if (!items.length) {
    ctx.grid.append(noneSelected(`No ${ACC_KINDS[ctx.field].title.toLowerCase()} you can use here yet.`
      + (mayDo("accessories") ? " Add one below." : "")));
  }
  if (ctx.current && !linked) {
    add(ctx.grid, [note(`Now: “${ctx.current}” (not in the accessories list). Choose one below to link it.`)]);
  }
  ctx.grid.append(el("ul", { class: "acc-pick", "aria-label": capitalise(ctx.what) }, tiles));
}

function kitPickerBusy(ctx, busy) {
  ctx.busy = busy;
  ctx.grid.setAttribute("aria-busy", String(busy));
  for (const button of ctx.grid.querySelectorAll(".acc-pick-mutate")) button.disabled = busy;
}

async function pickKit(ctx, item) {
  if (ctx.busy || !accDialogHere(ctx.sheet)) return;
  const id = item ? item.id : null;
  if ((id || "") === ctx.current) { ctx.sheet.close(); return; }
  let moveFrom = null;
  if (item) {
    const { others, none, taken } = accTaken(item, ctx.holder);
    if (none) {
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", {
        text: `There are no ${item.label} deck boxes left (its quantity is 0). Set its quantity on the Accessories page, or choose another deck box.` })));
      return;
    }
    // A move takes the kit off its other holder, which is an edit of that deck (E10-S42): only holders
    // the viewer can see and change are offered one.
    const movable = (h) => Boolean(h.holder) && (h.holder.startsWith("product/") || canEditDeckId(h.holder));
    if (taken && !others.some(movable)) {
      // Only decks the viewer can't see ("one of Sam's decks") or change have every box: there's nothing to move here.
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", {
        text: `${capitalise(accTakenWords({ others, none, taken }))}. Choose another deck box.` })));
      return;
    }
    if (taken) {
      // A deck box with none free: only a move makes room for it.
      moveFrom = await askAccessoryChoice(`Move this deck box from ${others.map((h) => h.title).join(" or ")}?`,
        ["Every box of this kind is in use. Moving one takes it off the other deck."],
        [...others.filter(movable).map((h) => ({ text: others.length === 1 ? "Move it here"
          : `Take it from ${h.title}`, kind: "primary", value: h.holder })),
        { text: "Cancel", value: null }]);
      if (!moveFrom || !accDialogHere(ctx.sheet)) return;
    } else if (ctx.field === "sleeves" && others.length) {
      // Sleeves other decks use are warned about every time (E8-S20, 2026-10-19), then can be shared as
      // they are, or moved here (re-sleeving that deck: E8-S08). Only holders the viewer can see and
      // change are offered the move; the others just share.
      const seen = others.filter(movable);
      const choice = await askAccessoryChoice(`Use ${item.label} here too?`,
        [`${others.map((h) => h.title).join(", ")} ${others.length === 1 ? "uses" : "use"} these sleeves already. `
          + "Several decks can share one design: just don't play two of them against each other."
          + (seen.length ? ` Or move them here, which takes them off ${seen.length === 1 ? seen[0].title : "the deck you pick"}.` : "")],
        [{ text: "Use them here too", kind: "primary", value: "share" },
          ...seen.map((h) => ({ text: seen.length === 1 ? "Move them here" : `Take them from ${h.title}`, value: h.holder })),
          { text: "Cancel", value: null }]);
      if (!choice || !accDialogHere(ctx.sheet)) return;
      if (choice !== "share") moveFrom = choice;
    }
  }
  sendKit(ctx, id, moveFrom);
}

async function sendKit(ctx, id, moveFrom) {
  if (!accDialogHere(ctx.sheet)) return;
  kitPickerBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Saving…"));
  const body = { holder: ctx.holder, field: ctx.field, id, holder_sha256: ctx.holderSha };
  if (moveFrom) body.move_from = moveFrom;
  try {
    const answer = await apiWrite("/api/accessories/assign", body);
    if (!accDialogHere(ctx.sheet)) return;
    state.library = null;
    ctx.sheet.close();
    const done = id ? `${capitalise(ctx.what)} saved.` : `${capitalise(ctx.what)} cleared.`;
    toast(done);
    if (ctx.onPicked) ctx.onPicked(answer);
  } catch (error) {
    if (!accDialogHere(ctx.sheet)) return;
    kitPickerBusy(ctx, false);
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
      error.status === 409 && error.data && error.data.conflict
        ? el("button", { type: "button", class: "btn", text: "Close and load the latest",
          onclick: () => { ctx.sheet.close(); route(); } }) : null));
  }
}

/** "+ Add new sleeves": add a row, and choose it for this holder at once. */
function addFromPicker(ctx) {
  if (ctx.busy || !accDialogHere(ctx.sheet)) return;
  openAccessorySheet({ kind: ctx.field, lockKind: true, sha256: ctx.data.sha256, owners: accOwnerChoices(ctx.data),
    owner: ctx.owner,
    onSaved: (answer, words) => {
      if (!accDialogHere(ctx.sheet)) return;
      toast(words);
      ctx.data = answer.data;
      drawKitPicker(ctx);
      const row = (answer.data.items || []).find((item) => item.id === answer.changed_id);
      if (row && row.kind === ctx.field) sendKit(ctx, row.id, null);
    } });
}
