/* Before the first paint: the theme last chosen on this device (or ?theme= for screenshots), with "Auto"
 * resolved from the system's, so data-theme is always light or dark and a dark page never flashes light.
 * app.js takes over (applyTheme). index.html loads this without defer, so it runs before the body is drawn;
 * it's a file, not an inline script, because the page's Content-Security-Policy allows scripts only from
 * Deck Lab's own files (E11-S63). */
(function () {
  var theme = null;
  try {
    var last = localStorage.getItem("decklab.lastProfile");
    theme = new URLSearchParams(location.search).get("theme") || (last && localStorage.getItem("decklab.theme." + last));
  } catch (e) { /* storage blocked: the system theme it is */ }
  if (theme !== "light" && theme !== "dark") theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", theme);
})();
