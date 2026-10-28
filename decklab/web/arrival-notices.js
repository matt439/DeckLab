/* Arrival notices (E6-S19): when a recorded delivery brought cards for a home player's decks, that player sees
a notice above the page on their next visit (GET /api/arrivals, lib/api/arrivals.py), naming each deck and how
many cards came for it. Dismiss hides it at once with an Undo toast; the dismissal is saved when the toast's time
is up (POST /api/arrivals/dismiss), so it doesn't come back for that receipt. Only home profiles are asked: the
notices are kept with a home player's own settings, and the server answers none to anyone else. */
"use strict";

let arrivalSeq = 0;                 // a newer load or a profile switch makes an older answer stale
let arrivalPending = null;          // {timer, works}: dismissals waiting for their Undo time

/** The notices' place above the page (index.html's #arrival-notices). */
function arrivalBox() { return document.getElementById("arrival-notices"); }

/** Take the notices away (a profile switch, "Who are you?"); a dismissal still waiting is saved only if the
 * same person is still chosen when its time is up. */
function clearArrivalNotices() {
  arrivalSeq += 1;
  const box = arrivalBox();
  if (box) { clear(box); box.hidden = true; }
}

/** Ask for this profile's notices and show them. Never fails the page: a refusal or an older server shows none. */
async function loadArrivalNotices(profile) {
  clearArrivalNotices();
  const seq = arrivalSeq;
  if (!profile || (profile.space || HOME_SPACE) !== HOME_SPACE) return;
  let answer;
  try {
    answer = await api("/api/arrivals");
  } catch (e) {
    return;                         // a notice is a courtesy: nothing to show
  }
  if (seq !== arrivalSeq || state.profile !== profile) return;
  drawArrivalNotices(Array.isArray(answer && answer.notices) ? answer.notices : []);
}

function drawArrivalNotices(notices) {
  const box = arrivalBox();
  if (!box) return;
  clear(box);
  // A dismissal still waiting (the same person picked again within its Undo time) keeps its notice hidden, and
  // its save, Undo or refusal acts on the notice drawn now, not the one taken away.
  const batch = arrivalPending && arrivalPending.profile === state.profile ? arrivalPending : null;
  notices.forEach((notice) => {
    const node = arrivalNotice(notice);
    const work = batch && batch.works.find((item) => item.notice.id === notice.id);
    if (work) { work.node = node; node.hidden = true; }
    box.append(node);
  });
  box.hidden = ![...box.children].some((child) => !child.hidden);
}

/** "3 cards for Deck A, 1 card for Deck B and 2 other decks". */
function arrivalParts(notice) {
  const parts = [];
  const decks = notice.decks || [];
  decks.forEach((deck, i) => {
    if (i) parts.push(i === decks.length - 1 && !notice.more ? " and " : ", ");
    parts.push(`${plural(deck.cards, "card")} for `,
      el("a", { href: `#/deck?id=${encodeURIComponent(deck.id)}`, text: deck.title }));
  });
  if (notice.more) parts.push(decks.length ? " and " : "", plural(notice.more, decks.length ? "other deck" : "deck"));
  return parts;
}

function arrivalNotice(notice) {
  const many = (notice.decks || []).length + (notice.more || 0) > 1;
  const when = notice.received_on ? ` on ${shopDay(notice.received_on)}` : "";
  const node = el("section", { class: "box box-info arrival-notice", role: "status", "aria-live": "polite" },
    el("div", { class: "box-head" }, el("h2", { text: `Cards arrived for your ${many ? "decks" : "deck"}` })),
    el("p", {}, `A delivery recorded${when} brought `, ...arrivalParts(notice), "."));
  node.append(el("button", { type: "button", class: "btn btn-secondary", text: "Dismiss",
    onclick: () => dismissArrival(notice, node) }));
  return node;
}

/** Hide one notice now and save its dismissal after the Undo toast's time (several in a row are saved
 * together); Undo puts every one of that batch back and saves nothing. A refusal puts it back and says why. */
function dismissArrival(notice, node) {
  const box = arrivalBox();
  node.hidden = true;
  if (box) box.hidden = ![...box.children].some((child) => !child.hidden);
  const batch = arrivalPending && arrivalPending.profile === state.profile ? arrivalPending
    : { works: [], timer: null, profile: state.profile };
  arrivalPending = batch;
  batch.works.push({ notice, node });
  clearTimeout(batch.timer);
  const restore = () => {
    batch.works.forEach((work) => { work.node.hidden = false; });
    if (box) box.hidden = !batch.works.some((work) => work.node.isConnected);
  };
  batch.timer = setTimeout(async () => {
    if (arrivalPending === batch) arrivalPending = null;
    // Someone else picked meanwhile (the shared iPad): never dismiss as them; it shows again next visit.
    if (state.profile !== batch.profile) return;
    try {
      await apiWrite("/api/arrivals/dismiss", { ids: batch.works.map((work) => work.notice.id) });
      batch.works.forEach((work) => work.node.remove());
    } catch (error) {
      restore();
      toast(`That notice couldn't be dismissed: ${error.message}`);
    }
  }, UNDO_MS);
  showToast(batch.works.length > 1 ? `${batch.works.length} notices dismissed.` : "Notice dismissed.", { undo: () => {
    clearTimeout(batch.timer);
    if (arrivalPending === batch) arrivalPending = null;
    restore();
  } });
}
