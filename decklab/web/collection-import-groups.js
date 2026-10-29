/* Source-set import reviews (E7-S03). Only server-owned preview groups can be left out.
 * Retained counts come from unmerged checked source contributions; original upload text and
 * row facts never enter the apply request. Legacy previews keep collection.js's flat flow. */
"use strict";

function colImportHasGroups(preview) {
  return !!preview && (Object.prototype.hasOwnProperty.call(preview, "groups")
    || Object.prototype.hasOwnProperty.call(preview, "source_rows"));
}

/** Project retained source rows, without guessing merged conditions or subtracting a merged row. */
function colImportGroupPlan(preview, selectedIds = new Set()) {
  if (!Array.isArray(preview?.groups) || !Array.isArray(preview.source_rows)
    || preview.groups.length > 20000 || preview.source_rows.length > 20000) return null;
  const groups = new Map();
  for (const group of preview.groups) {
    if (!group || typeof group.id !== "string" || !/^g[1-9]\d{0,4}$/.test(group.id) || groups.has(group.id)
      || typeof group.label !== "string" || !group.label || !Number.isInteger(group.rows) || group.rows < 1
      || !Array.isArray(group.lines) || group.lines.length !== group.rows) return null;
    groups.set(group.id, {...group, sources: []});
  }
  const selected = new Set(selectedIds), lines = new Set();
  if ([...selected].some(id => !groups.has(id))) return null;
  for (const source of preview.source_rows) {
    if (!source || !groups.has(source.group) || !Number.isInteger(source.line) || source.line < 2
      || lines.has(source.line) || !source.row || typeof source.row !== "object"
      || typeof source.dropped_basic !== "boolean" || (source.problem !== null && typeof source.problem !== "string")) return null;
    const row = source.row;
    if (!COL_FIELDS.every(key => typeof row[key] === "string" || (key === "quantity" && typeof row[key] === "number"))) return null;
    if (source.problem === null && (!Number.isSafeInteger(Number(row.quantity)) || Number(row.quantity) < 1
      || (typeof row.quantity === "string" && !/^[1-9]\d*$/.test(row.quantity)))) return null;
    if (source.dropped_basic && source.problem !== null) return null;
    lines.add(source.line); groups.get(source.group).sources.push(source);
  }
  for (const group of groups.values()) {
    if (group.sources.length !== group.rows || group.sources.some((source, index) => source.line !== group.lines[index])) return null;
    const valid = group.sources.filter(source => source.problem === null && !source.dropped_basic);
    if (group.problem_rows !== group.sources.filter(source => source.problem !== null).length
      || group.valid_rows !== valid.length || group.valid_cards !== valid.reduce((sum, source) => sum + Number(source.row.quantity), 0)
      || group.dropped_basics !== group.sources.filter(source => source.dropped_basic).reduce((sum, source) => sum + Number(source.row.quantity), 0)) return null;
  }
  const retained = preview.source_rows.filter(source => !selected.has(source.group));
  const good = retained.filter(source => source.problem === null && !source.dropped_basic);
  const excluded = preview.source_rows.filter(source => selected.has(source.group));
  // rules.ident uses the exact tuple. Collector-number case must not collapse distinct printings.
  const keys = new Set(good.map(source => JSON.stringify([source.row.set, source.row.collector_number, source.row.finish])));
  return {groups: [...groups.values()], rows: retained.filter(source => !source.dropped_basic),
    problems: retained.filter(source => source.problem !== null),
    adds: {rows: keys.size, cards: good.reduce((sum, source) => sum + Number(source.row.quantity), 0)},
    dropped_basics: retained.filter(source => source.dropped_basic).reduce((sum, source) => sum + Number(source.row.quantity), 0),
    excluded_rows: excluded, excluded_groups: [...groups.values()].filter(group => selected.has(group.id)),
    valid_excluded_cards: excluded.filter(source => source.problem === null && !source.dropped_basic)
      .reduce((sum, source) => sum + Number(source.row.quantity), 0)};
}

function colImportGroupsHere(ctx, review) {
  return ctx.groupReview === review && ctx.preview === review.preview && !ctx.sheet.closed
    && colActive(ctx.cv) && ctx.cv.editable && canEditSpace(ctx.cv.space)
    && review.root.isConnected && ctx.area.contains(review.root);
}

/** Capture the exact reviewed ids before applyImport waits for the collection's current rows. */
function colImportGroupRequest(ctx) {
  if (!colImportHasGroups(ctx.preview)) return null;
  const review = ctx.groupReview;
  if (!review || !colImportGroupsHere(ctx, review)) return {blocked: true};
  const plan = colImportGroupPlan(ctx.preview, review.ids);
  if (!plan || plan.problems.length || !plan.adds.cards) return {blocked: true};
  return {ids: plan.groups.filter(group => review.ids.has(group.id)).map(group => group.id)};
}

function colImportGroupBusy(ctx, busy, preview = ctx.preview) {
  const review = ctx.groupReview;
  if (!review || review.preview !== preview) return;
  for (const control of review.controls.values()) control.disabled = busy;
}

function colImportSourceWords(source) {
  const row = source.row;
  return `Line ${source.line}: quantity ${String(row.quantity ?? "") || "not recorded"}, ${row.name || "name not recorded"}; `
    + `${colPrinting(row)}; ${colRowFacts(row)}`
    + (source.problem !== null ? `; problem: ${source.problem}` : source.dropped_basic ? "; plain basic land already omitted" : "; valid source row");
}

/** Static native group choices survive every projection update, retaining current focus. */
function drawImportGroups(ctx) {
  const preview = ctx.preview;
  const previous = ctx.groupReview?.preview === preview ? ctx.groupReview.ids : new Set();
  const plan = colImportGroupPlan(preview, previous);
  clear(ctx.area);
  if (!plan) {
    ctx.groupReview = null;
    ctx.area.append(el("p", {class: "box box-warn", text: "The source-set review is incomplete. Choose the file again before importing it."}));
    sheetActions(ctx.sheet, [{text: "Cancel", onclick: () => ctx.sheet.close()}]);
    return;
  }
  const review = ctx.groupReview = {preview, ids: new Set(previous), controls: new Map(),
    root: el("div", {class: "col-import-group-review"}), outcome: el("div", {class: "col-import-group-outcome"})};
  const choices = el("div", {class: "col-import-groups"});
  for (const group of plan.groups) {
    const id = `${ctx.sheet.heading.id}-import-${group.id}`, description = `${id}-scope`;
    const valid = group.sources.filter(source => source.problem === null && !source.dropped_basic);
    const problems = group.sources.filter(source => source.problem !== null);
    const cards = valid.reduce((sum, source) => sum + Number(source.row.quantity), 0);
    const input = el("input", {type: "checkbox", id, class: "col-import-group-check", "data-import-group": group.id,
      "aria-describedby": description, onchange: () => {
        if (ctx.busy || input.disabled || !colImportGroupsHere(ctx, review)) {
          input.checked = review.ids.has(group.id); return;
        }
        if (input.checked) review.ids.add(group.id); else review.ids.delete(group.id);
        drawImportGroupOutcome(ctx, review);
      }});
    input.checked = review.ids.has(group.id); review.controls.set(group.id, input);
    choices.append(el("section", {class: `box col-import-group${problems.length ? " box-warn" : ""}`},
      el("h3", {text: `${group.label}: ${plural(problems.length, "problem row")}`}),
      el("label", {class: "choice", for: id}, input,
        el("span", {text: `Leave out all ${plural(group.sources.length, "source row")} from ${group.label}`})),
      el("p", {id: description, class: "sub", text: `This includes ${plural(valid.length, "valid source row")} (${plural(cards, "card")}). `
        + "Valid copies in a selected set will also be left out. The original upload stays unchanged."}),
      problems.length ? el("details", {}, el("summary", {text: `Review ${plural(problems.length, "problem row")}`}),
        el("ul", {class: "col-import-source-list", tabindex: 0, "aria-label": `${group.label} problem rows`},
          problems.map(source => el("li", {text: colImportSourceWords(source)})))) : null));
  }
  add(review.root, [colRepeatImportWarning(preview.repeat_imports),
    el("p", {text: "Review the source sets to leave out. Every remaining problem must be resolved or explicitly excluded before Import."}),
    choices, review.outcome]);
  ctx.area.append(review.root);
  drawImportGroupOutcome(ctx, review);
}

/** Show source facts rather than inventing the merged condition/language of retained copies. */
function drawImportGroupOutcome(ctx, review) {
  if (!colImportGroupsHere(ctx, review)) return;
  const plan = colImportGroupPlan(review.preview, review.ids);
  if (!plan) return;
  clear(review.outcome);
  review.outcome.append(el("p", {class: "col-import-summary", role: "status", "aria-live": "polite", text:
    `${plural(plan.adds.cards, "card")} to add, in ${plural(plan.adds.rows, "printing row")}.`
    + (plan.dropped_basics ? ` ${plural(plan.dropped_basics, "plain basic land")} left out (they aren't recorded).` : "")}));
  if (plan.excluded_rows.length) review.outcome.append(el("details", {class: "box box-warn col-import-excluded"},
    el("summary", {text: `Review ${plural(plan.excluded_rows.length, "excluded source row")} (${plural(plan.valid_excluded_cards, "valid card")} left out)`}),
    el("ul", {class: "col-import-source-list", tabindex: 0, "aria-label": "Every excluded source row"},
      plan.excluded_rows.map(source => el("li", {text: colImportSourceWords(source)})))));
  if (plan.problems.length) review.outcome.append(el("p", {class: "box box-warn", text:
    `${plural(plan.problems.length, "remaining problem row")} still block this import. Leave out their source sets above, or fix the file and choose it again.`}));
  if (plan.rows.length) review.outcome.append(el("h3", {text: "Retained source rows, before combining printings"}),
    el("div", {class: "col-import-table"}, el("table", {class: "data"},
      el("thead", {}, el("tr", {}, ["Line", "Qty", "Name", "Printing", "Condition", "Language"].map(text => el("th", {scope: "col", text})))),
      el("tbody", {}, plan.rows.map(source => {
        const row = source.row;
        return el("tr", {class: source.problem !== null ? "col-problem" : null},
          el("td", {text: String(source.line)}), el("td", {class: "num", text: String(row.quantity ?? "")}),
          el("td", {text: row.name || ""}), el("td", {text: colPrinting(row)}),
          el("td", {text: row.condition || "-"}), el("td", {text: row.language || "-"}));
      })))));
  if (!plan.adds.cards) review.outcome.append(emptyBox("Nothing remains to import with these choices.",
    el("button", {type: "button", class: "btn", text: "Choose another file", onclick: () => {
      if (!ctx.busy && colImportGroupsHere(ctx, review)) ctx.input.click();
    }})));
  sheetActions(ctx.sheet, [{text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close()},
    {text: `Import ${plural(plan.adds.cards, "card")}`, kind: "primary", value: "import",
      disabled: ctx.busy || !!plan.problems.length || !plan.adds.cards, onclick: event => {
        if (event.currentTarget?.isConnected && ctx.sheet.foot.contains(event.currentTarget)
          && !event.currentTarget.disabled && colImportGroupsHere(ctx, review)) applyImport(ctx, false);
      }}]);
}

function colImportExcludedWords(answer) {
  const groups = answer.excluded_groups;
  if (!Array.isArray(groups) || !groups.length) return "";
  const cards = groups.reduce((sum, group) => sum + (Number(group.valid_cards) || 0), 0);
  return ` ${plural(groups.length, "source set group")} left out, including ${plural(cards, "valid card")}.`;
}
