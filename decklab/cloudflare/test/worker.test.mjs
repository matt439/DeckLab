// The off page's Worker against a stand-in origin: real Request and Response objects, no network, no
// npm packages. From the repo root: node --test decklab/cloudflare/
import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { handle, offResponse, ORIGIN_HEADER, OFF_JSON } from "../worker.mjs";

const SITE = "https://decklab.example.com";
const LOGIN = { Cookie: "theme=dark; CF_Authorization=abc" };
const PAGE = { "Sec-Fetch-Mode": "navigate", Accept: "text/html,application/xhtml+xml" };
const req = (path, headers = {}, init = {}) => new Request(SITE + path, { headers: { ...LOGIN, ...headers }, ...init });

/** A stand-in origin: answers status (Cloudflare's error unless deckLab), and records what it was asked. */
function origin(status, { deckLab = false, body = "error code: 1033", headers = {} } = {}) {
  const fake = async (input, init) => {
    fake.calls.push(new Request(input, init));
    return new Response(body, { status, headers: { ...(deckLab ? { [ORIGIN_HEADER]: "1" } : {}), ...headers } });
  };
  fake.calls = [];
  return fake;
}
const deckLab = (status, body = '{"error":"Deck Lab\'s database isn\'t reachable right now.","reason":"database"}') =>
  origin(status, { deckLab: true, body, headers: { "Content-Type": "application/json; charset=utf-8" } });

function assertOffHeaders(r) {
  assert.equal(r.status, 503);
  assert.equal(r.headers.get("Cache-Control"), "no-store");
  assert.equal(r.headers.get("Retry-After"), "30");
  assert.equal(r.headers.get("X-Deck-Lab-Off"), "1");
  assert.equal(r.headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(r.headers.get("Referrer-Policy"), "no-referrer");
  assert.equal(r.headers.get(ORIGIN_HEADER), null);
}

test("a tunnel-down 530 on a page load becomes the off page", async () => {
  const r = await handle(req("/", PAGE), origin(530));
  assertOffHeaders(r);
  assert.equal(r.headers.get("Content-Type"), "text/html; charset=utf-8");
  assert.match(r.headers.get("Content-Security-Policy"), /default-src 'none'/);
  const html = await r.text();
  assert.match(html, /<title>Deck Lab is off<\/title>/);
  assert.match(html, /computer at home/);
  assert.match(html, /opens Deck Lab by itself/);
  assert.match(html, />Try again</);
  assert.match(html, /prefers-color-scheme: dark/);
  assert.doesNotMatch(html, /https?:\/\//, "nothing loaded from elsewhere");
  assert.doesNotMatch(html, /Matt|User1|User2|User3|User4/);
});

test("the off page's script checks /api/status and reloads when Deck Lab answers", async () => {
  const html = await (await handle(req("/", PAGE), origin(530))).text();
  const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
  let check = null, reloads = 0, asked = [];
  const listeners = {};
  const fakeDocument = { visibilityState: "visible",
    getElementById: () => ({ addEventListener: (type, fn) => { listeners.click = fn; } }),
    addEventListener: (type, fn) => { listeners[type] = fn; } };
  let answer = { type: "basic", headers: new Headers() };
  const run = new Function("document", "location", "fetch", "setTimeout", "clearTimeout", script);
  run(fakeDocument, { reload: () => { reloads += 1; } },
    async (url, init) => { asked.push([url, init]); return answer; },
    (fn, ms) => { check = [fn, ms]; return 1; }, () => {});
  assert.equal(check[1], 30000);
  await check[0]();                                   // still off: asks again later
  assert.deepEqual([asked[0][0], asked[0][1].cache, asked[0][1].redirect], ["/api/status", "no-store", "manual"]);
  assert.equal(reloads, 0);
  answer = { type: "basic", headers: new Headers({ [ORIGIN_HEADER]: "1" }) };
  await check[0]();
  assert.equal(reloads, 1);
  answer = { type: "opaqueredirect", headers: new Headers() };     // Access's session ran out
  await check[0]();
  assert.equal(reloads, 2);
  listeners.click();
  assert.equal(reloads, 3);
});

test("an Accept of text/html is a page load too, without Sec-Fetch-Mode", async () => {
  const r = await handle(req("/#/library", { Accept: "text/html" }), origin(530));
  assert.match(await r.text(), /<h1>Deck Lab is off<\/h1>/);
});

test("under /api/ the off answer is JSON with reason off", async () => {
  for (const status of [502, 503, 504, 520, 521, 522, 523, 530]) {
    const r = await handle(req("/api/library", { Accept: "application/json" }), origin(status));
    assertOffHeaders(r);
    assert.equal(r.headers.get("Content-Type"), "application/json; charset=utf-8");
    assert.deepEqual(await r.json(), OFF_JSON, `status ${status}`);
  }
  assert.equal(OFF_JSON.reason, "off");
});

test("a picture or a script gets a short text", async () => {
  const r = await handle(req("/img/fdn/227/small", { Accept: "image/*", "Sec-Fetch-Mode": "no-cors" }), origin(530));
  assertOffHeaders(r);
  assert.equal(r.headers.get("Content-Type"), "text/plain; charset=utf-8");
  assert.equal(await r.text(), "Deck Lab is off.\n");
});

test("a fetch that throws becomes the off answer", async () => {
  const failing = async () => { throw new TypeError("network connection lost"); };
  assert.deepEqual(await (await handle(req("/api/status"), failing)).json(), OFF_JSON);
  assert.match(await (await handle(req("/", PAGE), failing)).text(), /Deck Lab is off/);
});

for (const status of [500, 502, 503]) {
  test(`Deck Lab's own ${status} passes through unchanged`, async () => {
    const fake = deckLab(status);
    const r = await handle(req("/api/profiles/user1/settings"), fake);
    assert.equal(r.status, status);
    assert.equal(r.headers.get(ORIGIN_HEADER), "1");
    assert.equal(r.headers.get("X-Deck-Lab-Off"), null);
    assert.equal((await r.json()).reason, "database");
  });
}

test("Deck Lab's own 503 page load (the card data loading) passes through", async () => {
  const r = await handle(req("/", PAGE), origin(503, { deckLab: true, body: "<!doctype html>loading" }));
  assert.equal(r.status, 503);
  assert.equal(await r.text(), "<!doctype html>loading");
});

test("200s, 404s, a 500 from Cloudflare and a 524 timeout pass through", async () => {
  const ok = await handle(req("/api/status"), deckLab(200, '{"ok":true}'));
  assert.equal(ok.status, 200);
  assert.deepEqual(await ok.json(), { ok: true });
  assert.equal((await handle(req("/nothing"), deckLab(404))).status, 404);
  for (const status of [500, 524]) {
    const r = await handle(req("/api/forge/run"), origin(status, { body: "raw" }));
    assert.equal(r.status, status);
    assert.equal(await r.text(), "raw");
  }
});

test("a redirect isn't followed: it goes back to the browser as it came", async () => {
  const fake = origin(302, { body: "", headers: { Location: "https://example.cloudflareaccess.com/login" } });
  const r = await handle(req("/api/status"), fake);
  assert.equal(r.status, 302);
  assert.equal(r.headers.get("Location"), "https://example.cloudflareaccess.com/login");
  assert.equal(fake.calls[0].redirect, "manual");
});

test("without an Access login the Worker never answers itself", async () => {
  for (const headers of [{}, { Cookie: "theme=dark; NOT_CF_Authorization=x" }]) {
    const fake = origin(530, { body: "raw" });
    const r = await handle(new Request(SITE + "/", { headers: { ...PAGE, ...headers } }), fake);
    assert.equal(r.status, 530);
    assert.equal(await r.text(), "raw");
    assert.equal(fake.calls.length, 1);
    assert.equal(fake.calls[0].redirect, "manual");
  }
  // The JWT header alone is a login.
  const r = await handle(new Request(SITE + "/api/x", { headers: { "Cf-Access-Jwt-Assertion": "a.b.c" } }), origin(530));
  assert.equal(r.status, 503);
});

test("/cdn-cgi/ is always passed through", async () => {
  const r = await handle(req("/cdn-cgi/access/logout", PAGE), origin(530, { body: "raw" }));
  assert.equal(r.status, 530);
});

test("the preview path shows the off page without asking the PC", async () => {
  const fake = origin(200, { deckLab: true });
  const r = await handle(req("/__decklab-off", PAGE), fake);
  assert.equal(fake.calls.length, 0);
  assertOffHeaders(r);
  assert.match(await r.text(), /<title>Deck Lab is off<\/title>/);
  // ...but only behind Access: without a login it's the PC's answer.
  const bare = await handle(new Request(SITE + "/__decklab-off", { headers: PAGE }), origin(404, { deckLab: true }));
  assert.equal(bare.status, 404);
});

test("request headers, the Access login and the body reach the origin unchanged", async () => {
  const body = "y".repeat(5 * 1024 * 1024);           // as big as an accessory photo upload
  const headers = { "Cf-Access-Jwt-Assertion": "header.payload.signature", "Content-Type": "application/json",
    "X-Deck-Lab": "1", "X-Deck-Lab-Viewer": "matt", Origin: SITE, "Sec-Fetch-Site": "same-origin" };
  let seen = null;
  const fake = async (input, init) => {
    const r = new Request(input, init);
    seen = { method: r.method, url: r.url, redirect: r.redirect, headers: Object.fromEntries(r.headers),
      length: (await r.text()).length };
    return new Response("{}", { headers: { [ORIGIN_HEADER]: "1" } });
  };
  const r = await handle(req("/api/accessories/image?id=x", headers, { method: "PUT", body }), fake);
  assert.equal(r.status, 200);
  assert.equal(seen.method, "PUT");
  assert.equal(seen.url, SITE + "/api/accessories/image?id=x");
  assert.equal(seen.redirect, "manual");
  assert.equal(seen.length, body.length);
  for (const [key, value] of Object.entries({ ...LOGIN, ...headers })) {
    assert.equal(seen.headers[key.toLowerCase()], value, key);
  }
});

test("non-GET methods get the off answer too, and HEAD gets no body", async () => {
  const post = await handle(req("/api/deck/save", { "Content-Type": "application/json" },
    { method: "POST", body: "{}" }), origin(530));
  assertOffHeaders(post);
  assert.equal((await post.json()).reason, "off");
  for (const path of ["/", "/api/status", "/app.js"]) {
    const head = await handle(req(path, PAGE, { method: "HEAD" }), origin(530, { body: null }));
    assertOffHeaders(head);
    assert.equal(head.body, null, path);
  }
});

test("offResponse is never cached and the default export uses fetch", async () => {
  assertOffHeaders(offResponse(req("/api/status")));
  const real = globalThis.fetch;
  globalThis.fetch = origin(530);
  try {
    const r = await worker.fetch(req("/api/status"));
    assert.equal((await r.json()).reason, "off");
    assert.equal(globalThis.fetch.calls[0].redirect, "manual");
  } finally {
    globalThis.fetch = real;
  }
});
