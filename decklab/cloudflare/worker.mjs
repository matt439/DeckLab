// Deck Lab's "off" page (story E11-S02): a Cloudflare Worker on the routes decklab.example.com/* and
// www.decklab.example.com/*. Cloudflare Access runs first, so only a visitor already signed in gets here.
// Every request goes on to the PC unchanged (headers, the Access login and the body included, redirects
// not followed); only when the answer is Cloudflare's own "can't reach the PC" error (the PC, the tunnel
// or Deck Lab is off) does the visitor get a plain "Deck Lab is off" page instead, or, under /api/, a
// 503 JSON answer with reason "off" that the page waits on and retries (decklab/web/core.js, load).
// Deck Lab marks every answer it sends with ORIGIN_HEADER (decklab/lib/server_http.py, _send), so its
// own 502s and 503s (the database down, the card data loading) are never replaced.
// Wake-on-request: when the Worker secret WAKE_URL is set, the PC sleeps when idle and a wake gate on the
// always-on NAS wakes it. Then an off answer to a signed-in visitor also asks the gate (POST WAKE_URL, with
// the Access service token WAKE_CLIENT_ID / WAKE_CLIENT_SECRET) to wake the PC, in the background, and says
// "Deck Lab is waking up" instead (reason "waking"); the gate sends at most one packet every 30 seconds.
// Without WAKE_URL everything is as before.
// No dependencies; decklab/README.md, "From outside the home", says how to test, deploy and roll back.
import { offPage } from "./off-page.mjs";
import { wakingPage } from "./waking-page.mjs";

export const ORIGIN_HEADER = "X-Deck-Lab-Origin";
// What Cloudflare or cloudflared answer with when Deck Lab can't be reached: 530 (error 1033, no tunnel
// connected), 502 (cloudflared running, Deck Lab not listening), 503, 504 and 520-523. 524 (Deck Lab took
// over 100 seconds) means it is running, so that one passes through.
export const OFF_STATUSES = new Set([502, 503, 504, 520, 521, 522, 523, 530]);
export const RETRY_SECONDS = 30;
export const PREVIEW_PATH = "/__decklab-off";      // shows the off page without asking the PC (still behind Access)
export const OFF_JSON = {
  error: "Deck Lab is off at the moment: the computer at home isn't running it. Try again later.",
  reason: "off",
};
export const WAKING_PREVIEW_PATH = "/__decklab-waking";   // the waking page, without asking the PC or the gate
export const WAKING_RETRY_SECONDS = 5;
export const WAKING_POLL_SECONDS = 3;
export const WAKING_GIVE_UP_SECONDS = 180;
export const WAKE_TIMEOUT_MS = 5000;
export const WAKING_JSON = {
  error: "Deck Lab is waking up. This usually takes under a minute.",
  reason: "waking",
};
const CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'";

/** True when the request carries Cloudflare Access's login (its header or its cookie). Without one the
 * Worker never answers itself: Access runs first, so this matters only if Access were misconfigured. */
export function signedIn(request) {
  if (request.headers.get("Cf-Access-Jwt-Assertion")) return true;
  return /(?:^|;\s*)CF_Authorization=/.test(request.headers.get("Cookie") || "");
}

/** True when an answer from the origin is Cloudflare's error in place of Deck Lab's. */
export function isOff(response) {
  return !response.headers.has(ORIGIN_HEADER) && OFF_STATUSES.has(response.status);
}

/** True when the Worker is set up to wake the PC (the WAKE_URL secret is set). */
export function wakeEnabled(env) {
  return Boolean(env && typeof env.WAKE_URL === "string" && env.WAKE_URL.trim());
}

/** Asks the wake gate to wake the PC, in the background (ctx.waitUntil when there is one). It never
 * throws and never delays the answer: a gate that's down or slow only means no packet this time. */
export function sendWake(env, ctx, wakeFetch = (input, init) => fetch(input, init)) {
  const headers = {};
  if (env.WAKE_CLIENT_ID) headers["CF-Access-Client-Id"] = env.WAKE_CLIENT_ID;
  if (env.WAKE_CLIENT_SECRET) headers["CF-Access-Client-Secret"] = env.WAKE_CLIENT_SECRET;
  const init = { method: "POST", headers, redirect: "manual" };
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    init.signal = AbortSignal.timeout(WAKE_TIMEOUT_MS);
  }
  let wake;
  try {
    wake = Promise.resolve(wakeFetch(env.WAKE_URL.trim(), init)).then((r) => {
      try { r?.body?.cancel?.()?.catch?.(() => {}); } catch (e) { /* nothing to read */ }
    }, () => {});
  } catch (e) {
    wake = Promise.resolve();
  }
  try {
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(wake);
  } catch (e) { /* the answer still goes out */ }
  return wake;
}

/** The off answer, always 503 and never cached: JSON under /api/, the page for a page load, else a
 * short text (a picture, a script). A HEAD request gets the headers alone. With waking set, it says
 * Deck Lab is waking up (reason "waking", the waking page) and asks again sooner. */
export function offResponse(request, path = new URL(request.url).pathname, waking = false) {
  const headers = {
    "Cache-Control": "no-store",
    "Retry-After": String(waking ? WAKING_RETRY_SECONDS : RETRY_SECONDS),
    "X-Deck-Lab-Off": "1",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
  };
  if (waking) headers["X-Deck-Lab-Waking"] = "1";
  let body, type;
  const accept = request.headers.get("Accept") || "";
  if (path.startsWith("/api/")) {
    [body, type] = [JSON.stringify(waking ? WAKING_JSON : OFF_JSON), "application/json; charset=utf-8"];
  } else if (request.headers.get("Sec-Fetch-Mode") === "navigate" || accept.includes("text/html")) {
    body = waking ? wakingPage(WAKING_POLL_SECONDS, WAKING_GIVE_UP_SECONDS) : offPage(RETRY_SECONDS);
    type = "text/html; charset=utf-8";
    headers["Content-Security-Policy"] = CSP;
  } else {
    [body, type] = [waking ? "Deck Lab is waking up.\n" : "Deck Lab is off.\n", "text/plain; charset=utf-8"];
  }
  headers["Content-Type"] = type;
  return new Response(request.method === "HEAD" ? null : body, { status: 503, headers });
}

/** One request: on to the PC as it came, and the off answer only in place of Cloudflare's error (with
 * WAKE_URL set, also a wake sent to the gate). originFetch and wakeFetch are fetch in production and
 * stand-ins in the tests; env and ctx are the Worker's. */
export async function handle(request, originFetch, env = {}, ctx = undefined, wakeFetch = undefined) {
  const path = new URL(request.url).pathname;
  // Redirects (such as Access's, once its session runs out) go back to the browser as they are.
  const pass = () => originFetch(request, { redirect: "manual" });
  if (path.startsWith("/cdn-cgi/") || !signedIn(request)) return pass();
  if (path === PREVIEW_PATH) return offResponse(request, "/");
  if (path === WAKING_PREVIEW_PATH) return offResponse(request, "/", true);
  const waking = wakeEnabled(env);
  // A page's own timer polls (X-Deck-Lab-Poll) answer as waking but send no wake, so a tab left open
  // never keeps the PC up; the waking page's checks also say X-Deck-Lab-Waking-Check and keep waking it.
  const timerPoll = request.headers.get("X-Deck-Lab-Poll") === "1"
    && request.headers.get("X-Deck-Lab-Waking-Check") !== "1";
  const off = () => {
    if (waking && !timerPoll) sendWake(env, ctx, wakeFetch);
    return offResponse(request, path, waking);
  };
  let response;
  try {
    response = await pass();
  } catch (e) {
    return off();
  }
  return isOff(response) ? off() : response;
}

export default {
  fetch(request, env, ctx) {
    return handle(request, (input, init) => fetch(input, init), env || {}, ctx);
  },
};
