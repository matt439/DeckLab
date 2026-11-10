/* Operational browser failures contain a reference and enum-only metadata, never the error text or location. */
"use strict";

const PAGE_ERROR_KINDS = new Set(["library", "deck", "edit", "new", "collection", "tokens", "shopping", "activity", "play",
  "settings", "history", "compare", "matchups", "matchup", "variant", "field", "gauntlet", "other"]);
const PAGE_ERROR_TYPES = new Set(["Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "URIError", "EvalError", "AggregateError"]);
const pageFailureReferences = new WeakMap();
let pageFailureReportTimes = [];

function pageErrorKind() {
  const page = String(location.hash || "").replace(/^#\/?/, "").split(/[?\/]/, 1)[0];
  return PAGE_ERROR_KINDS.has(page) ? page : "other";
}

function pageErrorType(error) {
  try { return PAGE_ERROR_TYPES.has(error?.name) ? error.name : "Error"; } catch (_) { return "Error"; }
}

function pageErrorReference() {
  try {
    if (globalThis.crypto?.getRandomValues) {
      const data = new Uint8Array(16);
      globalThis.crypto.getRandomValues(data);
      return Array.from(data, value => value.toString(16).padStart(2, "0")).join("");
    }
  } catch (_) { /* the reference is an identifier, never an authentication secret */ }
  return Array.from({length: 32}, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

function knownPageFailure(error) {
  try {
    return Boolean(error && ((typeof ApiError === "function" && error instanceof ApiError)
      || [400, 403, 404, 409, 503].includes(error.status)));
  } catch (_) { return false; }
}

function sendPageFailure(reference, page, type) {
  const now = Date.now();
  pageFailureReportTimes = pageFailureReportTimes.filter(at => at > now - 60000);
  if (pageFailureReportTimes.length >= 6 || typeof fetch !== "function") return Promise.resolve(false);
  pageFailureReportTimes.push(now);
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), 5000) : null;
  return Promise.resolve().then(() => fetch("/api/errors/report", {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json", "X-Deck-Lab": "1", "X-Deck-Lab-Poll": "1"},
    signal: controller?.signal, body: JSON.stringify({reference, page, type})}))
    .then(response => response.ok, () => false).finally(() => { if (timer !== null) clearTimeout(timer); });
}

function pageFailure(error) {
  if (knownPageFailure(error)) return {message: error.message, reference: null, sent: Promise.resolve(true)};
  const object = error && (typeof error === "object" || typeof error === "function");
  if (object && pageFailureReferences.has(error)) return pageFailureReferences.get(error);
  const reference = pageErrorReference();
  const result = {reference, message: `Reference ${reference}. Reload the page and keep this reference if it happens again.`,
    sent: sendPageFailure(reference, pageErrorKind(), pageErrorType(error))};
  if (object) pageFailureReferences.set(error, result);
  return result;
}
