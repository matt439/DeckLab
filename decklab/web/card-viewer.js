/* Deck Lab's page: the card viewer, a card shown big (decklab/UI-REVIEW.md DK-7 and the owner's request:
"make it easier to view large cards and swipe between them on mobile").

openCardViewer(items, start, opts) shows a list of cards one at a time: on a phone the picture fills the
screen on a dark background, and a swipe left or right (it follows the finger, then snaps: past a fifth
of the width, or a flick) goes to the next or previous card, with "3 / 15" under it. On a wider screen the
card is in the middle with Previous and Next beside it, and the arrow keys (Home and End too) do the same;
Escape closes. A double-faced card has Flip, which shows its back's picture. The card's rules text is a
panel: beside the picture from 1,000 px, behind the Text button on smaller screens.
On portrait touch screens Text overlays the picture instead of shrinking it; each new opening starts closed. The cards either side
are already drawn, and the next two are fetched ahead, so a swipe never waits for its picture.

It's a modal <dialog> (the page behind it can't be reached), focus goes to Close and back to whatever
opened it, and it adds a history entry while it's open, so a phone's Back button closes it (the entry
carries its place, history.state.pos, as app.js's entryPos() wants). prefers-reduced-motion: cards change
without sliding.

openCard(card, trigger) is the one-card case every page uses: when trigger was marked with cards-ui.js
viewerItem (cardTile and cardRow do it with opts.viewerGroup), the viewer opens over the trigger's whole
group instead, in page order (the deck page's decklist is the reference: deck.js deckCardRow).

Loaded after core.js; it uses symbols.js, cards-ui.js's viewerGroup, deck.js's manaCost and app.js's
entryPos at run time. app.js's start() calls setUpDialog(). Nothing runs at load.
*/
"use strict";

const VIEWER_SHARE = 0.2;       // a drag past this share of the width turns the card
const VIEWER_FLICK = 0.45;      // px per ms: a flick turns it even when shorter
const VIEWER_SLOP = 10;         // px a press moves before it's a drag
const VIEWER_MS = 240;          // how long a card takes to slide in (the CSS transition's time)
// The card's picture is drawn up to 976 px wide (cards-ui.css .viewer-frame): the large image (672 px wide) for
// most screens, the normal one (488 px) where that's enough.
const VIEWER_SIZES = "(max-width: 599px) 100vw, min(976px, 72vh)";
let viewerDom = null;           // the viewer's elements, made the first time it opens
let viewerState = null;         // the open viewer: its items, the card shown, the drag going on, ...
let viewerTextOpen = false;     // Text stays open from card to card within this opening
let viewerSeq = 0;              // each opening's own mark on its history entry (history.state.cardViewer)


/** The card overlay every page uses: card big, or card's viewer group (cards-ui.js viewerItem) when trigger
 * belongs to one. trigger gets the focus back afterwards. */
function openCard(card, trigger) {
  if (!card) return null;
  const group = viewerGroup(trigger && typeof trigger.closest === "function" ? trigger.closest("[data-viewer]") : null);
  if (group && group.items[group.index].card === card) return openCardViewer(group.items, group.index, { trigger });
  return openCardViewer([card], 0, { trigger });
}

/** Shows items (cards, or {card, caption}) in the viewer, starting at items[start]. opts: trigger (what gets
 * the focus back; default the focused element), caption(card, index) (a line for the text panel, for items
 * without their own). Opening it while it's open shows the new list in the same viewer. */
function openCardViewer(items, start = 0, opts = {}) {
  const list = (items || []).map((item) => (item && item.card ? item : item ? { card: item, caption: null } : null))
    .filter((item) => item && item.card);
  if (!list.length) return null;
  const dom = viewerDom || (viewerDom = buildViewer());
  const open = Boolean(viewerState && dom.dialog.open);
  if (!open) viewerTextOpen = false; // A newly opened list starts with the full picture.
  viewerState = {
    items: list, index: Math.max(0, Math.min(list.length - 1, Number(start) || 0)), face: 0,
    caption: typeof opts.caption === "function" ? opts.caption : null,
    trigger: open ? viewerState.trigger : opts.trigger || document.activeElement,
    history: open ? viewerState.history : false, token: open ? viewerState.token : 0,
    fromHistory: false, drag: null, settling: false, dragEnded: 0, pressTarget: null,
  };
  dom.dialog.classList.toggle("show-text", viewerTextOpen);
  dom.textBtn.setAttribute("aria-pressed", String(viewerTextOpen));
  drawViewer();
  if (!dom.dialog.open) {
    if (typeof dom.dialog.showModal === "function") dom.dialog.showModal();
    else dom.dialog.setAttribute("open", "");
    document.body.classList.add("has-card-dialog");
    pushViewerEntry();
  }
  dom.close.focus({ preventScroll: true });
  return viewerState;
}

function closeViewer() {
  if (viewerDom && viewerDom.dialog.open) viewerDom.dialog.close();
}

/** app.js's start(): Back on a phone closes the viewer (its history entry, pushViewerEntry). Only the open
 * viewer's own entry keeps it open: an entry an earlier opening left behind (closed with Close or Escape,
 * then Forward; or a reload or a restored tab on it) loses its mark when the page lands on it, so it can
 * never stop Back from closing a later viewer. */
function setUpDialog() {
  forgetViewerEntry();
  window.addEventListener("popstate", () => {
    if (!viewerState || !viewerDom || !viewerDom.dialog.open) { forgetViewerEntry(); return; }
    if (history.state && history.state.cardViewer === viewerState.token) return;
    viewerState.fromHistory = true;
    viewerDom.dialog.close();
  });
}

/** Takes the viewer's mark off this history entry (its place, pos, stays). */
function forgetViewerEntry() {
  const now = typeof history !== "undefined" ? history.state : null;
  if (!now || typeof now !== "object" || !now.cardViewer || typeof history.replaceState !== "function") return;
  const { cardViewer, ...rest } = now;
  history.replaceState(rest, "");
}

/** A history entry for the open viewer, at the next place (app.js entryPos), so Back closes it. */
function pushViewerEntry() {
  if (pushHistoryEntry({ cardViewer: viewerSeq + 1 }) == null) return;     // core.js
  viewerState.token = ++viewerSeq;
  viewerState.history = true;
}


// ------------------------------------------------------------------ drawing

function buildViewer() {
  const d = {};
  const arrow = (points) => svgEl("svg", { viewBox: "0 0 24 24", width: 28, height: 28, "aria-hidden": "true" },
    svgEl("path", { d: points, fill: "none", stroke: "currentColor", "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round" }));
  d.title = el("h2", { id: "viewer-title", class: "viewer-title" });
  d.flip = el("button", { type: "button", class: "viewer-btn viewer-flip", "aria-pressed": "false", hidden: true,
    onclick: () => flipViewer() }, "Flip");
  d.textBtn = el("button", { type: "button", class: "viewer-btn viewer-text-btn", "aria-pressed": "false",
    "aria-controls": "viewer-text", onclick: () => toggleViewerText() }, "Text");
  d.close = el("button", { type: "button", class: "viewer-btn viewer-close", "aria-label": "Close", onclick: () => closeViewer() },
    arrow("M6 6l12 12M18 6L6 18"));
  d.prev = el("button", { type: "button", class: "viewer-nav viewer-prev", "aria-label": "Previous card",
    onclick: () => stepViewer(-1) }, arrow("M15 5l-7 7 7 7"));
  d.next = el("button", { type: "button", class: "viewer-nav viewer-next", "aria-label": "Next card",
    onclick: () => stepViewer(1) }, arrow("M9 5l7 7-7 7"));
  d.count = el("p", { class: "viewer-count" });
  // What the list's tile said about the card (deck.js: "Missing", "1 on the way"), always in sight under the
  // counter, so a missing card doesn't look owned once it's big.
  d.marks = el("div", { class: "viewer-marks" });
  d.hint = el("p", { class: "viewer-swipe-hint", text: "Swipe left or right" });
  d.foot = el("div", { class: "viewer-foot" }, d.count, d.hint, d.marks);
  d.live = el("p", { class: "sr-only", "aria-live": "polite" });
  d.slides = [-1, 0, 1].map((at) => el("figure", { class: "viewer-slide", "data-at": String(at) }));
  d.track = el("div", { class: "viewer-track" }, d.slides);
  d.stage = el("div", { class: "viewer-stage" }, d.track);
  d.text = el("section", { id: "viewer-text", class: "viewer-text", "aria-label": "Card text", tabindex: "-1" });
  d.dialog = el("dialog", { class: "viewer", "aria-labelledby": "viewer-title" },
    el("header", { class: "viewer-head" }, d.title, d.flip, d.textBtn, d.close),
    d.stage, d.prev, d.next, d.foot, d.text, d.live);
  document.body.append(d.dialog);

  d.dialog.addEventListener("cancel", (e) => { e.preventDefault(); closeViewer(); });    // Escape
  d.dialog.addEventListener("close", viewerClosed);
  d.dialog.addEventListener("keydown", viewerKey);
  // Should the focus ever leave the dialog (to the page's body), the keys still move the cards.
  document.addEventListener("keydown", (e) => {
    if (d.dialog.open && !(e.target && typeof d.dialog.contains === "function" && d.dialog.contains(e.target))) viewerKey(e);
  });
  // A tap on the dark space around the card closes it; on the card, or just after a swipe, it doesn't.
  d.dialog.addEventListener("click", (e) => {
    if (!viewerState) return;
    const target = viewerState.pressTarget || e.target;
    viewerState.pressTarget = null;
    if (Date.now() - viewerState.dragEnded < 400) return;
    if (target === d.dialog || target === d.stage || target === d.track || d.slides.includes(target)) closeViewer();
  });
  // A swipe may start anywhere but a button or a link: on the card, on its words (beside it on a wide screen,
  // under it on a phone) or on the dark space around them, which is most of a wide screen. The dialog takes the
  // pointer once it moves sideways, and a press that moves up or down scrolls the words as before.
  d.dialog.addEventListener("pointerdown", viewerPointerDown);
  d.dialog.addEventListener("pointermove", viewerPointerMove);
  d.dialog.addEventListener("pointerup", viewerPointerUp);
  d.dialog.addEventListener("pointercancel", viewerPointerUp);
  d.dialog.addEventListener("lostpointercapture", viewerPointerUp);
  return d;
}

function drawViewer() {
  const s = viewerState, d = viewerDom, n = s.items.length, item = s.items[s.index], card = item.card;
  d.dialog.classList.toggle("is-single", n < 2);
  d.title.textContent = card.name;
  d.count.textContent = n > 1 ? `${s.index + 1} / ${n}` : "";
  // A button about to be disabled hands its focus on first (to the other one, else Close), so the focus
  // never falls to the page and the arrow keys keep working.
  const atStart = s.index === 0, atEnd = s.index === n - 1;
  for (const [button, off, other] of [[d.prev, atStart, atEnd ? d.close : d.next], [d.next, atEnd, atStart ? d.close : d.prev]]) {
    if (off && document.activeElement === button) other.focus({ preventScroll: true });
  }
  d.prev.disabled = atStart;
  d.next.disabled = atEnd;
  const back = hasBackPicture(card);
  d.flip.hidden = !back;
  if (!back) s.face = 0;
  d.flip.setAttribute("aria-pressed", String(s.face === 1));
  d.flip.setAttribute("aria-label", s.face === 1 ? "Show the front" : "Show the back");
  [-1, 0, 1].forEach((at, k) => fillSlide(d.slides[k], s.items[s.index + at], at === 0 ? s.face : 0, at === 0));
  add(clear(d.text), cardTextParts(card, s.face, item.caption || (s.caption ? s.caption(card, s.index) : null)));
  const marks = typeof item.status === "function" ? item.status() || [] : [];
  add(clear(d.marks), marks);
  d.marks.hidden = !marks.length;
  d.text.scrollTop = 0;
  d.live.textContent = n > 1 ? `Card ${s.index + 1} of ${n}: ${card.name}` : "";
  // The cards two away too, so a quick run of swipes never waits.
  if (typeof Image === "function") {
    for (const at of [2, -2]) {
      const ahead = s.items[s.index + at];
      const url = ahead && facePicture(ahead.card, 0);
      if (url) {
        const img = new Image(); img.decoding = "async";
        const set = viewerSrcset(url);
        if (set) { img.sizes = VIEWER_SIZES; img.srcset = set; }
        img.src = url;
      }
    }
  }
}

/** True when the card's back has a picture of its own (a transform or modal double-faced card). */
function hasBackPicture(card) {
  const faces = card && card.faces;
  return Boolean(faces && faces.length > 1 && faces[1].img && faces[1].img !== faces[0].img);
}

/** The large image of a Deck Lab picture address ("/img/fdn/227/normal" -> ".../large"; the back's too), or
 * null for any other address. */
function viewerLargeUrl(url) {
  return typeof url === "string" && /^\/img\/[^/]+\/[^/]+\/normal(-back)?$/.test(url)
    ? url.replace(/\/normal(-back)?$/, "/large$1") : null;
}

/** The srcset that offers the large image beside the normal one, or "" when there's no large one. */
function viewerSrcset(url) {
  const large = viewerLargeUrl(url);
  return large ? `${url} 488w, ${large} 672w` : "";
}

/** The picture of face (0 the front, 1 the back when it has its own), or null. */
function facePicture(card, face) {
  const faces = card.faces || [];
  if (face === 1 && hasBackPicture(card)) return faces[1].img;
  return card.img || (faces[0] && faces[0].img) || null;
}

/** One of the three slides: item's picture (the small one shows at once, the normal one over it when it
 * comes), or its words when it has no picture. Only the middle one (current) is read out. */
function fillSlide(slide, item, face, current) {
  clear(slide);
  if (current) slide.removeAttribute("aria-hidden");
  else slide.setAttribute("aria-hidden", "true");
  if (!item) return;
  const card = item.card;
  const url = facePicture(card, face);
  if (!url) {
    add(slide, [el("div", { class: "viewer-frame viewer-wordcard" }, cardTextParts(card, face, null)),
      current ? el("p", { class: "viewer-status", role: "status", text: "No image is available. You can still read the card text." }) : null]);
    return;
  }
  const f = face === 1 ? card.faces[1] : card.faces && card.faces.length ? card.faces[0] : card;
  const small = face === 1 ? f.img_small : card.img_small || (card.faces && card.faces[0] && card.faces[0].img_small);
  const img = el("img", { class: "viewer-img", alt: current ? `${f.name || card.name}: ${f.type_line || card.type_line || "card"}` : "",
    width: 488, height: 680, decoding: "async", draggable: "false" });
  const frame = el("div", { class: "viewer-frame is-loading",
    style: small ? `background-image: url(${JSON.stringify(small)})` : null }, img);
  const status = el("p", { class: "viewer-status", role: current ? "status" : null });
  const retry = el("button", { type: "button", class: "btn viewer-retry", hidden: true, text: "Retry image" });
  add(slide, [frame, status, retry]);
  loadViewerImage({ img, frame, status, retry }, url);
}

/** Loads url into a slide's picture. A newer load of the same picture makes this one's answer count for
 * nothing, so an old failure never covers a new face. */
function loadViewerImage(parts, url) {
  const { img, frame, status, retry } = parts;
  const request = {};
  img.viewerRequest = request;
  frame.classList.add("is-loading");
  frame.classList.remove("is-failed");
  status.textContent = "";
  retry.hidden = true;
  img.onload = () => {
    if (img.viewerRequest !== request) return;
    frame.classList.remove("is-loading");
  };
  img.onerror = () => {
    if (img.viewerRequest !== request) return;
    frame.classList.add("is-failed");
    status.textContent = "The image couldn't load. You can still read the card text.";
    retry.hidden = false;
  };
  retry.onclick = () => loadViewerImage(parts, url);
  // The large picture where the screen can show it (srcset), the normal one otherwise. A retry sets both again.
  const set = viewerSrcset(url);
  img.srcset = "";
  if (set) { img.sizes = VIEWER_SIZES; img.srcset = set; }
  img.src = url;
}

/** The card's words: its caption, then each face's name and cost (a one-face card's name is the viewer's
 * title already, so its cost ends the type line), type line, rules text with its symbols, and power and
 * toughness, loyalty or defense. */
function cardTextParts(card, face, caption) {
  const faces = card.faces && card.faces.length ? card.faces : [card];
  const many = faces.length > 1;
  const flips = hasBackPicture(card);         // a face of its own on each side: say which one the picture is
  return [
    caption ? el("p", { class: "viewer-caption" }, caption) : null,
    faces.map((f, i) => {
      const numbers = [];
      if (f.power != null && f.toughness != null) numbers.push(`Power / toughness: ${f.power} / ${f.toughness}`);
      if (f.loyalty != null) numbers.push(`Starting loyalty: ${f.loyalty}`);
      if (f.defense != null) numbers.push(`Defense: ${f.defense}`);
      const cost = manaCost(f.mana_cost);
      const shown = flips && i === face;
      // A one-face card's name is the viewer's title: its cost goes at the end of the type line.
      return el("div", { class: "viewer-face" + (shown ? " is-shown" : "") },
        many ? el("h3", { class: "viewer-face-name" },
          el("span", {}, f.name || `Face ${i + 1}`, shown ? el("span", { class: "viewer-shown-tag", text: "Shown" }) : null), cost)
          : null,
        el("p", { class: "viewer-type" }, el("span", { text: f.type_line || card.type_line || "" }), many ? null : cost),
        f.oracle_text === undefined ? null
          : f.oracle_text == null ? el("p", { class: "oracle", text: "Card text isn't available in this copy of the card data." })
            : f.oracle_text ? oracleParagraphs(f.oracle_text) : el("p", { class: "oracle", text: "No rules text." }),
        numbers.length ? el("p", { class: "viewer-numbers", text: numbers.join(" · ") }) : null);
    })];
}


// ----------------------------------------------------------------- moving

function reducedMotion() {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The next (dir 1) or previous (-1) card, sliding in unless motion is reduced. */
function stepViewer(dir) {
  const s = viewerState;
  if (!s || s.settling) return;
  const to = s.index + dir;
  if (to < 0 || to >= s.items.length) return;
  settleViewer(dir);
}

function goViewer(index) {
  const s = viewerState;
  if (!s || s.settling || index === s.index || index < 0 || index >= s.items.length) return;
  s.index = index;
  s.face = 0;
  drawViewer();
}

/** Ends a move: the track slides to the card dir away (0: back to this one), then the slides are drawn
 * again around the new card with the track back in place, so nothing jumps. */
function settleViewer(dir) {
  const s = viewerState, track = viewerDom.track;
  const done = () => {
    track.classList.remove("is-settling");
    track.style.transform = "";
    if (!viewerState || viewerState !== s) return;
    s.settling = false;
    if (dir) { s.index += dir; s.face = 0; drawViewer(); }
  };
  if (reducedMotion()) { done(); return; }
  s.settling = true;
  track.classList.add("is-settling");
  track.style.transform = `translateX(${-dir * 100}%)`;
  setTimeout(done, VIEWER_MS);
}

function flipViewer() {
  const s = viewerState;
  if (!s || !hasBackPicture(s.items[s.index].card)) return;
  s.face = s.face === 1 ? 0 : 1;
  drawViewer();
}

function toggleViewerText() {
  viewerTextOpen = !viewerTextOpen;
  viewerDom.dialog.classList.toggle("show-text", viewerTextOpen);
  viewerDom.textBtn.setAttribute("aria-pressed", String(viewerTextOpen));
  // Open: to the words. Closed: back to the button, as the panel's display:none would drop the focus.
  if (viewerTextOpen) viewerDom.text.focus({ preventScroll: true });
  else viewerDom.textBtn.focus({ preventScroll: true });
}

function viewerKey(e) {
  const dialog = viewerDom && viewerDom.dialog;
  if (!viewerState || !dialog || !dialog.isConnected || keyboardDialog() !== dialog || keyboardMenuOpen()
      || e.defaultPrevented || e.isComposing || e.keyCode === 229 || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey
      || (e.target && e.target.isConnected === false) || keyboardEditing(e.target)) return;
  const moves = { ArrowRight: () => stepViewer(1), ArrowLeft: () => stepViewer(-1),
    Home: () => goViewer(0), End: () => goViewer(viewerState.items.length - 1) };
  if (!moves[e.key]) return;
  e.preventDefault();
  moves[e.key]();
}

// A swipe: the track follows the finger sideways (a press that moves up or down first is left alone), with
// resistance past the first and last cards; let go, and it turns the card or springs back.
function viewerPointerDown(e) {
  const s = viewerState;
  if (!s || s.settling || s.items.length < 2 || e.button > 0 || e.isPrimary === false) return;
  s.pressTarget = null;
  // A press on a button or a link is theirs.
  for (let n = e.target; n && n !== viewerDom.dialog; n = n.parentNode) {
    if (/^(BUTTON|A|INPUT|SELECT|TEXTAREA|SUMMARY)$/.test(n.tagName || "")) return;
  }
  // With a mouse, a drag on the words selects them; only a finger or a pen turns the card from there.
  if (e.pointerType === "mouse" && typeof viewerDom.text.contains === "function" && viewerDom.text.contains(e.target)) return;
  // Remember the original hit: capture retargets a plain tap to the dialog too.
  s.pressTarget = e.target;
  // Capture touch on the whole dialog from the start, including the space beside the image.
  // Vertical gestures can still scroll the text or be cancelled by the browser.
  if (e.pointerType === "touch" || e.pointerType === "pen") {
    try { viewerDom.dialog.setPointerCapture(e.pointerId); } catch (err) { /* pointer already gone */ }
  }
  s.drag = { id: e.pointerId, x: e.clientX, y: e.clientY, dx: 0, mode: null, lastX: e.clientX, lastT: e.timeStamp, v: 0 };
}

function viewerPointerMove(e) {
  const s = viewerState, g = s && s.drag;
  if (!g || e.pointerId !== g.id) return;
  const dx = e.clientX - g.x, dy = e.clientY - g.y;
  if (!g.mode) {
    if (Math.abs(dx) < VIEWER_SLOP && Math.abs(dy) < VIEWER_SLOP) return;
    g.mode = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    if (g.mode === "x") {
      try { viewerDom.dialog.setPointerCapture(g.id); } catch (err) { /* the pointer is gone already */ }
      viewerDom.track.classList.add("is-dragging");
    }
  }
  if (g.mode !== "x") return;
  if (e.cancelable) e.preventDefault();
  const dt = e.timeStamp - g.lastT;
  if (dt > 0) g.v = 0.7 * ((e.clientX - g.lastX) / dt) + 0.3 * g.v;
  g.lastX = e.clientX;
  g.lastT = e.timeStamp;
  const edge = (dx > 0 && s.index === 0) || (dx < 0 && s.index === s.items.length - 1);
  g.dx = edge ? dx / 3 : dx;
  viewerDom.track.style.transform = `translateX(${g.dx}px)`;
}

function viewerPointerUp(e) {
  const s = viewerState, g = s && s.drag;
  if (!g || e.pointerId !== g.id) return;
  // A touch is captured by the picture under the finger at first; the dialog taking it over
  // (viewerPointerDown/viewerPointerMove) makes the picture lose it, which bubbles here and isn't the end of the drag.
  if (e.type === "lostpointercapture" && e.target !== viewerDom.dialog) return;
  s.drag = null;
  if (g.mode !== "x") return;
  viewerDom.track.classList.remove("is-dragging");
  s.dragEnded = Date.now();
  const width = viewerDom.stage.clientWidth || 1;
  const dir = g.dx < 0 ? 1 : -1;
  const to = s.index + dir;
  // A flick counts when it's fast, recent and the same way as the drag.
  const flick = Math.abs(g.v) > VIEWER_FLICK && Math.sign(g.v) === -dir && e.timeStamp - g.lastT < 100;
  const far = Math.abs(g.dx) > width * VIEWER_SHARE || flick;
  settleViewer(e.type === "pointerup" && far && to >= 0 && to < s.items.length ? dir : 0);
}

function viewerClosed() {
  const s = viewerState;
  if (!s) return;
  viewerState = null;
  document.body.classList.remove("has-card-dialog");
  viewerDom.track.classList.remove("is-settling", "is-dragging");
  viewerDom.track.style.transform = "";
  for (const slide of viewerDom.slides) clear(slide);       // stop any picture still loading
  if (s.history && !s.fromHistory && history.state && history.state.cardViewer === s.token) history.back();
  if (s.trigger && s.trigger.isConnected && typeof s.trigger.focus === "function") s.trigger.focus({ preventScroll: true });
}
