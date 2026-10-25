/* The deck's play guide on its Overview tab: the existing playing notes from the deck's Notes, one folding
 * topic each (the first open). Markdown is rendered with DOM text nodes: no HTML injection, external images,
 * scripts, or invented strategy. The deck's card names are text links that open the viewer (deck-tools.js
 * guideCardText), and mana symbols ({T}, {G}) are drawn. */
"use strict";

function guideSection(data) {
  const guide = data.guide;
  const parts = guide && guide.sections || [];
  const section = el("section", { class: "deck-section deck-guide", id: "sec-guide", "aria-labelledby": "h-guide" },
    el("h2", { id: "h-guide", text: "How to play" }));
  if (guide && guide.changed_on) section.append(el("div", { class: "note note-warn guide-stale", role: "note" },
    el("p", { text: `The list changed on ${guide.changed_on}, so this guide may be out of date. Check its cards against the list.` })));
  if (!parts.length) {
    section.append(el("p", { class: "empty", text: data.summary.read_only
      ? "No play guide is recorded for this deck yet."
      : "No play guide yet. Game plan, mulligan and sideboard notes show here once they're in the deck's Notes." }));
    return section;
  }
  section.append(el("div", { class: "guide-topics" }, parts.map((part, i) => el("details", { class: "guide-topic", open: i === 0 },
      el("summary", {}, el("h3", { text: part.title })), guideMarkdown(part.markdown)))));
  return section;
}

/** The notes use emphasis, code and links. Links with other schemes (or local
 * repository paths) stay readable text; no file content is treated as HTML. */
function guideInline(text) {
  const parts = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;
  let from = 0;
  for (const match of text.matchAll(pattern)) {
    parts.push(...guideCardText(text.slice(from, match.index)));
    if (match[1]) parts.push(el("strong", {}, guideInline(match[1])));
    else if (match[2]) parts.push(el("em", {}, guideCardText(match[2])));
    else if (match[3]) parts.push(el("code", { text: match[3] }));
    else if (/^https?:\/\//i.test(match[5])) parts.push(el("a", {
      href: match[5], target: "_blank", rel: "noopener noreferrer", text: match[4] }));
    else parts.push(match[4]);
    from = match.index + match[0].length;
  }
  parts.push(...guideCardText(text.slice(from)));
  return parts;
}

/** Paragraphs and nested lists cover the handwritten gameplay notes. Headings
 * within a topic retain their hierarchy; unrecognised Markdown stays text. */
function guideMarkdown(markdown) {
  const root = el("div", { class: "guide-prose" });
  const stack = [];
  let paragraph = null;
  let blank = false;
  for (const raw of (markdown || "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) { paragraph = null; blank = true; continue; }
    const item = /^(\s*)([-+*]|\d+[.)])\s+(.+)$/.exec(raw);
    if (item) {
      const indent = item[1].replace(/\t/g, "    ").length;
      const tag = /^\d/.test(item[2]) ? "ol" : "ul";
      while (stack.length && stack[stack.length - 1].indent > indent) stack.pop();
      let top = stack[stack.length - 1];
      if (top && top.indent === indent && top.tag !== tag) { stack.pop(); top = stack[stack.length - 1]; }
      if (!top || top.indent < indent) {
        const list = el(tag, tag === "ol" ? { start: parseInt(item[2], 10) } : {});
        (top && top.last || root).append(list);
        top = { indent, tag, list, last: null };
        stack.push(top);
      }
      top.last = el("li", {}, guideInline(item[3]));
      top.list.append(top.last);
      paragraph = null;
    } else {
      const heading = /^#{1,6}\s+(.+)$/.exec(line);
      const indent = raw.length - raw.trimStart().length;
      const top = stack[stack.length - 1];
      // Indented continuation belongs to its list item, not a detached paragraph.
      const parent = !heading && top && indent > top.indent ? top.last : root;
      if (parent === root) stack.length = 0;
      if (heading) {
        root.append(el("h4", {}, guideInline(heading[1])));
        paragraph = null;
      } else if (paragraph && !blank) {
        add(paragraph, [" ", guideInline(line)]);
      } else {
        paragraph = el("p", {}, guideInline(line));
        parent.append(paragraph);
      }
    }
    blank = false;
  }
  return root;
}
