// The page shown while Deck Lab's computer is asleep and being woken (worker.mjs, with WAKE_URL set). Like
// the off page it names no person and no deck and loads nothing from anywhere else. While it's on screen
// it asks /api/status every `seconds` (and again when the tab comes back), and reloads as soon as Deck Lab
// itself answers (its X-Deck-Lab-Origin header), or when Access's session has run out (a redirect), so the
// reload shows the login. After `limit` seconds it stops and says the computer didn't wake, with Try again
// (a reload, which asks the wake gate again). Colours: decklab/web/tokens.css.
export function wakingPage(seconds = 3, limit = 180) {
  const every = Math.max(1, Number(seconds) || 3) * 1000;
  const giveUp = Math.max(10, Number(limit) || 180) * 1000;
  return `<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<title>Deck Lab is waking up</title>
<style>
:root { --page: #f1f0ec; --surface: #ffffff; --ink: #161616; --ink-2: #46453f; --border: rgb(0 0 0 / .12);
  --accent: #0f6e6a; --accent-ink: #ffffff; --track: rgb(0 0 0 / .1); color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --page: #111113; --surface: #1b1b1e; --ink: #f2f2ef; --ink-2: #c4c3bd; --border: rgb(255 255 255 / .12);
    --accent: #4cc2b8; --accent-ink: #0b1f1d; --track: rgb(255 255 255 / .14); }
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: var(--page); color: var(--ink);
  font: 17px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 32rem; margin: 14vh auto 0; padding: 0 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-top: 4px solid var(--accent);
  border-radius: 12px; padding: 24px 20px; }
h1 { font-size: 1.5rem; line-height: 1.25; margin: 0 0 12px; }
p { margin: 0 0 16px; }
.wait { color: var(--ink-2); font-size: .95rem; }
.progress { display: flex; align-items: center; gap: 12px; margin: 0 0 16px; }
.spinner { width: 28px; height: 28px; flex: none; border-radius: 50%; border: 3px solid var(--track);
  border-top-color: var(--accent); animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 3s; } }
[hidden] { display: none !important; }
button { font: inherit; font-weight: 600; min-height: 44px; padding: 0 20px; border: 0; border-radius: 8px;
  background: var(--accent); color: var(--accent-ink); cursor: pointer; }
button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
<main>
<div class="card">
<h1 id="title">Deck Lab is waking up</h1>
<div id="waking">
<p>The computer at home was asleep, so it's being woken now. This usually takes under a minute.</p>
<div class="progress"><span class="spinner" aria-hidden="true"></span><span class="wait" id="elapsed">Waiting…</span></div>
</div>
<p class="wait" id="wait" role="status" aria-live="polite">This page opens Deck Lab by itself when it's ready.</p>
<div id="failed" hidden>
<p>The computer at home may be turned off or disconnected from the network, or still be starting.</p>
<button type="button" id="again">Try again</button>
</div>
</div>
</main>
<script>
(() => {
  const every = ${every}, giveUp = ${giveUp};
  const start = Date.now();
  const $ = (id) => document.getElementById(id);
  let timer = 0, ticker = 0, failed = false;
  function tick() {
    const s = Math.floor((Date.now() - start) / 1000);
    $("elapsed").textContent = "Waiting for " + s + (s === 1 ? " second" : " seconds");
  }
  function fail() {
    failed = true;
    clearTimeout(timer);
    clearInterval(ticker);
    document.title = "Deck Lab didn't wake up";
    $("title").textContent = "Deck Lab didn't wake up";
    $("waking").hidden = true;
    $("failed").hidden = false;
    $("wait").textContent = "Deck Lab didn't wake up after " + Math.round(giveUp / 60000) + " minutes.";
  }
  async function check() {
    clearTimeout(timer);
    if (failed) return;
    try {
      const r = await fetch("/api/status", { cache: "no-store", redirect: "manual",
        headers: { Accept: "application/json", "X-Deck-Lab-Poll": "1", "X-Deck-Lab-Waking-Check": "1" } });
      if (r.type === "opaqueredirect" || r.headers.has("X-Deck-Lab-Origin")) { location.reload(); return; }
    } catch (e) { /* still asleep, or this device has no connection */ }
    if (Date.now() - start >= giveUp) { fail(); return; }
    if (document.visibilityState === "visible") timer = setTimeout(check, every);
  }
  $("again").addEventListener("click", () => location.reload());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check(); else clearTimeout(timer);
  });
  tick();
  ticker = setInterval(tick, 1000);
  timer = setTimeout(check, every);
})();
</script>
</body>
</html>
`;
}
