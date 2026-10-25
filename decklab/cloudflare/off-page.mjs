// The page shown while Deck Lab is off (worker.mjs). It names no person and no deck and loads nothing
// from anywhere else. While it's on screen it asks /api/status every `seconds` (and again when the tab
// comes back), and reloads as soon as Deck Lab itself answers (its X-Deck-Lab-Origin header), or when
// Access's session has run out (a redirect), so the reload shows the login. Colours: decklab/web/tokens.css.
export function offPage(seconds) {
  const every = Math.max(5, Number(seconds) || 30) * 1000;
  return `<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<title>Deck Lab is off</title>
<style>
:root { --page: #f1f0ec; --surface: #ffffff; --ink: #161616; --ink-2: #46453f; --border: rgb(0 0 0 / .12);
  --accent: #0f6e6a; --accent-ink: #ffffff; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --page: #111113; --surface: #1b1b1e; --ink: #f2f2ef; --ink-2: #c4c3bd; --border: rgb(255 255 255 / .12);
    --accent: #4cc2b8; --accent-ink: #0b1f1d; }
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
button { font: inherit; font-weight: 600; min-height: 44px; padding: 0 20px; border: 0; border-radius: 8px;
  background: var(--accent); color: var(--accent-ink); cursor: pointer; }
button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
</style>
</head>
<body>
<main>
<div class="card">
<h1>Deck Lab is off</h1>
<p>Deck Lab runs on the computer at home, and it isn't running right now. Nothing is lost: everything is kept safe there.</p>
<p class="wait" id="wait" role="status">This page opens Deck Lab by itself when it's back.</p>
<button type="button" id="again">Try again</button>
</div>
</main>
<script>
(() => {
  const every = ${every};
  let timer = 0;
  async function check() {
    clearTimeout(timer);
    try {
      const r = await fetch("/api/status", { cache: "no-store", redirect: "manual",
        headers: { Accept: "application/json" } });
      if (r.type === "opaqueredirect" || r.headers.has("X-Deck-Lab-Origin")) { location.reload(); return; }
    } catch (e) { /* still off, or this device has no connection */ }
    if (document.visibilityState === "visible") timer = setTimeout(check, every);
  }
  document.getElementById("again").addEventListener("click", () => location.reload());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check(); else clearTimeout(timer);
  });
  timer = setTimeout(check, every);
})();
</script>
</body>
</html>
`;
}
