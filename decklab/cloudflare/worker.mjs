// Deck Lab's "off" page (story E11-S02): a Cloudflare Worker on the routes decklab.example.com/* and
// www.decklab.example.com/*. Cloudflare Access runs first, so only a visitor already signed in gets here.
// Every request goes on to the PC unchanged (headers, the Access login and the body included, redirects
// not followed); only when the answer is Cloudflare's own "can't reach the PC" error (the PC, the tunnel
// or Deck Lab is off) does the visitor get a plain "Deck Lab is off" page instead, or, under /api/, a
// 503 JSON answer with reason "off" that the page waits on and retries (decklab/web/core.js, load).
// Deck Lab marks every answer it sends with ORIGIN_HEADER (decklab/lib/server_http.py, _send), so its
// own 502s and 503s (the database down, the card data loading) are never replaced.
// No dependencies; decklab/README.md, "From outside the home", says how to test, deploy and roll back.
import { offPage } from "./off-page.mjs";

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

/** The off answer, always 503 and never cached: JSON under /api/, the page for a page load, else a
 * short text (a picture, a script). A HEAD request gets the headers alone. */
export function offResponse(request, path = new URL(request.url).pathname) {
  const headers = {
    "Cache-Control": "no-store",
    "Retry-After": String(RETRY_SECONDS),
    "X-Deck-Lab-Off": "1",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
  };
  let body, type;
  const accept = request.headers.get("Accept") || "";
  if (path.startsWith("/api/")) {
    [body, type] = [JSON.stringify(OFF_JSON), "application/json; charset=utf-8"];
  } else if (request.headers.get("Sec-Fetch-Mode") === "navigate" || accept.includes("text/html")) {
    [body, type] = [offPage(RETRY_SECONDS), "text/html; charset=utf-8"];
    headers["Content-Security-Policy"] = CSP;
  } else {
    [body, type] = ["Deck Lab is off.\n", "text/plain; charset=utf-8"];
  }
  headers["Content-Type"] = type;
  return new Response(request.method === "HEAD" ? null : body, { status: 503, headers });
}

/** One request: on to the PC as it came, and the off answer only in place of Cloudflare's error.
 * originFetch is fetch in production and a stand-in in the tests. */
export async function handle(request, originFetch) {
  const path = new URL(request.url).pathname;
  // Redirects (such as Access's, once its session runs out) go back to the browser as they are.
  const pass = () => originFetch(request, { redirect: "manual" });
  if (path.startsWith("/cdn-cgi/") || !signedIn(request)) return pass();
  if (path === PREVIEW_PATH) return offResponse(request, "/");
  let response;
  try {
    response = await pass();
  } catch (e) {
    return offResponse(request);
  }
  return isOff(response) ? offResponse(request) : response;
}

export default {
  fetch(request) {
    return handle(request, (input, init) => fetch(input, init));
  },
};
