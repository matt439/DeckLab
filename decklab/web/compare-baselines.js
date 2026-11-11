/* Read-only Compare baselines: historical lists and explicitly picked public precons. */
"use strict";

function compareSideParams(params, key) {
  return { id: addressDeckId(params.get(key)), version: params.get(`${key}v`) === "owned" ? "owned" : "target",
    revision: params.get(`${key}r`) || null, precon: params.get(`${key}p`) || null };
}
function compareSideOf(data) {
  return { id: data.summary.id, version: data.version, revision: data.comparison?.kind === "revision" ? data.comparison.revision : null,
    precon: data.comparison?.kind === "precon" ? data.comparison.file : null };
}
function compareAddress(left, right) {
  const q = new URLSearchParams(), sides = [["a", left], ["b", right]];
  for (const [key, side] of sides) if (!side.precon) q.set(key, side.id);
  for (const [key, side] of sides) {
    if (!side.precon && side.version === "owned") q.set(`${key}v`, "owned");
    if (side.revision) q.set(`${key}r`, String(side.revision));
    if (side.precon) q.set(`${key}p`, side.precon);
  }
  return `#/compare?${q}`;
}
function compareRevisionHref(id, revision, version = "target", current = version) {
  return compareAddress({ id, version: current }, { id, version, revision });
}
function comparePreconHref(id, precon, version = "target") {
  return compareAddress({ id, version }, { precon });
}
function compareBaseline(data) { return ["revision", "precon"].includes(data.comparison?.kind); }
function compareVersionLinks(sides, index) {
  const side = sides[index], versions = (side.versions || []).filter(version => ["target", "owned"].includes(version));
  if (!sides.some(compareBaseline) || side.comparison?.kind === "precon" || versions.length < 2) return null;
  return el("div", { class: "segmented", role: "group", "aria-label": `${compareBaselineLabel(side) || side.summary.title}: list` },
    versions.map(version => {
      const chosen = sides.map(compareSideOf); chosen[index] = { ...chosen[index], version };
      return el("a", { href: compareAddress(...chosen), "aria-current": side.version === version ? "page" : null, text: listName(version) });
    }));
}
function compareBaselineLabel(data) {
  const source = data.comparison;
  if (source?.kind === "precon") return source.label || `Published precon: ${data.summary.title}`;
  if (source?.kind !== "revision") return null;
  const when = new Date(source.date);
  return `Revision ${source.revision}, ${Number.isFinite(when.getTime())
    ? when.toLocaleDateString(LOCALE, { day: "numeric", month: "short", year: "numeric" }) : "date unknown"}`;
}
function compareSideUrl(side, intrinsic) {
  if (side.precon) return `/api/compare/precon?file=${encodeURIComponent(side.precon)}`;
  const q = new URLSearchParams({ id: side.id, version: side.version });
  if (side.revision) {
    q.set("revision", side.revision); q.set("stats", "1"); return `/api/deck/revision?${q}`;
  }
  return intrinsic ? `/api/compare/deck?${q}` : `/api/deck?${q}&omit=matchups`;
}
function compareDeltaPart(sides, labels) {
  if (!sides.some(compareBaseline)) return null;
  const title = `Change from ${labels[1]} to ${labels[0]}`;
  if (sides.some(side => !side.stats || side.stats_unknown)) return comparePart("h-compare-deltas", "Stat changes",
    el("p", { class: "sub", text: "Stat changes are unknown while either list's stats are unknown. The listed card differences remain below." }));
  const [a, b] = sides.map(side => side.stats), rows = [];
  const change = (name, first, second, digits = 0) => {
    const known = Number.isFinite(first) && Number.isFinite(second);
    const delta = known ? first - second : null;
    rows.push([name, known ? `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${num(Math.abs(delta), digits)}` : "Unknown"]);
  };
  change("Cards", compareCounts(sides[0]).main, compareCounts(sides[1]).main);
  change("Average mana value", a.curve?.average_mv, b.curve?.average_mv, 2);
  change("Effective lands", a.lands?.effective, b.lands?.effective, 2);
  const buckets = [...new Set([...(a.curve?.buckets || []), ...(b.curve?.buckets || [])].map(row => row.mv))];
  for (const mv of buckets) change(`Mana value ${mv}`, a.curve?.buckets?.find(row => row.mv === mv)?.total,
    b.curve?.buckets?.find(row => row.mv === mv)?.total);
  const colours = [...new Set([...(a.colours?.colours || []), ...(b.colours?.colours || [])].map(row => row.colours))];
  const landSources = (stats, colour) => stats.colours?.land_sources_by_colour?.[colour]
    ?? stats.colours?.colours?.find(row => row.colours === colour)?.land_sources;
  for (const colour of colours) change(`${capitalise((a.colours?.colours?.find(row => row.colours === colour)
    || b.colours?.colours?.find(row => row.colours === colour)).name)} land sources`,
  landSources(a, colour), landSources(b, colour), 2);
  const roles = [...new Set([...(a.roles || []), ...(b.roles || [])].map(row => row.role))];
  for (const role of roles) change((ROLE_WORDS[role] || [capitalise(role)])[0],
    Array.isArray(a.roles) ? a.roles.find(row => row.role === role)?.count || 0 : null,
    Array.isArray(b.roles) ? b.roles.find(row => row.role === role)?.count || 0 : null);
  const bracket = sides.map(side => side.stats?.commander?.bracket);
  if (bracket.some(Boolean)) rows.push(["Bracket (today's lists)", `${bracket[1]?.label || "Unknown"} → ${bracket[0]?.label || "Unknown"}`]);
  return comparePart("h-compare-deltas", "Stat changes", el("p", { class: "sub", text: title }),
    el("table", { class: "data compare-delta-table" }, el("caption", { class: "sr-only", text: title }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Figure" }), el("th", { scope: "col", text: "Change" }))),
      el("tbody", {}, rows.map(([name, value]) => el("tr", {}, el("th", { scope: "row", text: name }), el("td", { class: "num", text: value }))))));
}
function comparePreconChooser(data) {
  const sheet = openSheet("Compare with a published precon"), token = routeToken, profile = state.profile, hash = location.hash;
  const profileId = profile?.id, space = profile?.space || HOME_SPACE, summary = data.summary, id = summary.id, version = data.version;
  const main = document.getElementById("main"), body = sheet.body, foot = sheet.foot;
  const query = el("input", { type: "search", maxlength: 100, placeholder: "Find a published precon", "aria-label": "Find a published precon" });
  const results = el("div", { "aria-live": "polite" }); let sequence = 0, timer = null;
  const here = () => !sheet.closed && token === routeToken && profile === state.profile && hash === location.hash
    && profileId === state.profile?.id && space === (state.profile?.space || HOME_SPACE)
    && data.summary === summary && summary.id === id && data.version === version
    && document.getElementById("main") === main && main.isConnected && sheet.body === body && sheet.foot === foot
    && body.contains(query) && body.contains(results) && sheet.dialog.isConnected;
  const search = async () => {
    if (!here()) return;
    const own = ++sequence, text = query.value.trim();
    if (text.length > 100) { clear(results).append(el("p", { text: "Use at most 100 characters." })); return; }
    clear(results).append(loadingBox("Getting published precons…", { small: true }));
    try {
      const answer = await api(`/api/precons?q=${encodeURIComponent(text)}`);
      if (!here() || own !== sequence || text !== query.value.trim()) return;
      const choices = (Array.isArray(answer.decks) ? answer.decks : []).filter(row => row && typeof row.file === "string" && typeof row.name === "string");
      clear(results).append(choices.length ? el("ul", { class: "compare-choices" }, choices.map(row => {
        const href = comparePreconHref(data.summary.id, row.file, data.version);
        const link = el("a", { class: "compare-choice", href }, el("span", { class: "compare-choice-title", text: row.name }));
        link.addEventListener("click", event => {
          if (!here() || !results.contains(link) || !link.isConnected || keyboardDialog() !== sheet.dialog) { event.preventDefault(); return; }
          if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && !(event.button > 0) && location.hash === href) {
            event.preventDefault(); sheet.close(); route();
          }
        });
        return el("li", {}, link);
      }))
        : emptyBox("No published precon matches that."));
      if (answer.more) results.append(el("p", { class: "sub", text: "More match. Add a few words to narrow the list." }));
    } catch (error) { if (here() && own === sequence) clear(results).append(loadFailed("Published precons", error, search)); }
  };
  query.addEventListener("input", () => { clearTimeout(timer); sequence++; timer = setTimeout(search, 250); });
  body.append(el("p", { class: "sub", text: "Choose the published MTGJSON list. Comparing it creates no deck." }), query, results);
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  search(); if (here() && keyboardDialog() === sheet.dialog) query.focus(); return sheet;
}
