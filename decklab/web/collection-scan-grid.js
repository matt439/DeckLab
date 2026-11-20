/* Extract aligned pockets from one upright image. Only individual card crops reach the scan API. */
"use strict";

const SCAN_GRIDS = {
  "2x2": [2, 2], "3x3": [3, 3], "4x3": [4, 3], "3x4": [3, 4], "1x1": [1, 1],
};

/** Pixel boundaries are shared by adjacent slots, including on odd-sized originals. Bounds are percentages. */
function gridCropRect(width, height, columns, rows, index, bounds = {left: 0, top: 0, right: 100, bottom: 100}) {
  const col = index % columns, row = Math.floor(index / columns);
  const edge = (step, count, size, start, end) => Math.round(size * (start + (end - start) * step / count) / 100);
  const x = edge(col, columns, width, bounds.left, bounds.right);
  const y = edge(row, rows, height, bounds.top, bounds.bottom);
  return {x, y, width: edge(col + 1, columns, width, bounds.left, bounds.right) - x,
    height: edge(row + 1, rows, height, bounds.top, bounds.bottom) - y};
}

async function gridCropJpeg(picture, rect) {
  const canvas = document.createElement("canvas");
  const scale = Math.min(1, COL_SCAN_SIDE / Math.max(rect.width, rect.height));
  canvas.width = Math.max(1, Math.round(rect.width * scale));
  canvas.height = Math.max(1, Math.round(rect.height * scale));
  try {
    canvas.getContext("2d").drawImage(picture, rect.x, rect.y, rect.width, rect.height, 0, 0, canvas.width, canvas.height);
    return await colScanEncodeCanvas(canvas);
  } finally { canvas.width = canvas.height = 1; }
}

async function openScanBitmap(source) {
  if (source.size > 40 * 1024 * 1024) throw new Error("Choose an image of 40 MiB or less.");
  let bitmap;
  try { bitmap = await createImageBitmap(source, {imageOrientation: "from-image"}); }
  catch (_) { throw new Error("This image couldn't be opened. Try a JPEG or PNG photo or scanner image."); }
  if (bitmap.width < 40 || bitmap.height < 40 || bitmap.width * bitmap.height > 64000000) {
    bitmap.close();
    throw new Error("Choose an image of up to 64 megapixels, with at least 40 pixels on each side.");
  }
  return bitmap;
}

/** Crop one page or read separate card files sequentially into the ordinary batch review. */
function colScanGrid({isCurrent, canScan, submit, onStart, onChange}) {
  const element = el("section", {class: "col-scan-grid", "aria-label": "Scan a grid of cards"});
  const field = (text, control) => el("label", {class: "field"}, el("span", {text}), control);
  const file = el("input", {type: "file", accept: "image/*", multiple: true, class: "col-file"});
  const fileField = el("div", {class: "col-grid-panel"}, field("Choose grid or scanner images", file),
    el("p", {class: "sub", text: "One photo for a grid, or select up to 100 images with one card per file."}));
  const layouts = el("select", {"aria-label": "Grid layout"}, Object.entries(SCAN_GRIDS).map(([value, [cols, rows]]) =>
    el("option", {value, text: cols === 1 ? "Single card (1 × 1)" : `${cols} columns × ${rows} rows`})));
  layouts.value = "2x2";
  const margins = {};
  const marginFields = el("div", {class: "col-grid-margins"});
  for (const side of ["Left", "Top", "Right", "Bottom"]) {
    const label = side + " margin (%)";
    const input = el("input", {type: "number", inputmode: "numeric", value: "0", step: "1", min: "0", max: "45",
      "aria-label": label});
    margins[side] = input;
    marginFields.append(field(label, input));
  }
  const preview = el("canvas", {"aria-hidden": "true"});
  const overlay = el("div", {class: "col-grid-slots", role: "group", "aria-label": "Select the occupied slots"});
  const fileRows = el("ol", {class: "col-scan-files", "aria-label": "Scanner files in filename order", hidden: true});
  const run = el("button", {type: "button", class: "btn btn-primary", "data-grid-run": "", text: "Scan selected slots"});
  const pause = el("button", {type: "button", class: "btn", hidden: true, text: "Stop after this slot"});
  const discard = el("button", {type: "button", class: "btn", text: "Discard image"});
  const alignment = el("div", {class: "col-grid-panel"},
    el("p", {class: "sub", text: "Use upright cards in even rows. Match the outlines to the pockets, then untick empty slots."}),
    field("Grid layout", layouts), el("details", {}, el("summary", {text: "Adjust page margins"}), marginFields),
    el("div", {class: "col-grid-image"}, preview, overlay),
    el("p", {class: "sub", text: "✓ Added to the pending list · ? Sent to Check these · ! Retry this slot"}));
  const panel = el("div", {class: "col-grid-panel", hidden: true}, alignment,
    el("div", {class: "actions"}, run, pause, discard), fileRows);
  const message = el("p", {class: "sub", role: "status"});
  element.append(fileField, panel, message);

  let generation = 0, page = 0, picture = null, decoding = false, scanning = false, pausing = false;
  let cols = 2, rows = 2, slots = [], separateFiles = false;
  function here() { return element.isConnected && isCurrent(); }
  function owns(stamp) { return stamp === generation && here(); }
  function slotName(index) {
    if (separateFiles) return `Batch ${page}, file ${index + 1}`;
    return `Page ${page}, row ${Math.floor(index / cols) + 1}, column ${index % cols + 1}`;
  }
  function bounds() {
    return {left: Number(margins.Left.value), top: Number(margins.Top.value),
      right: 100 - Number(margins.Right.value), bottom: 100 - Number(margins.Bottom.value)};
  }
  function rect(index) { return gridCropRect(picture.width, picture.height, cols, rows, index, bounds()); }
  function queued(slot) { return slot.input.checked && (slot.state === "ready" || slot.state === "failed"); }
  function sync() {
    const worked = slots.some(slot => slot.state === "added" || slot.state === "review");
    layouts.disabled = scanning || worked;
    for (const input of Object.values(margins)) input.disabled = layouts.disabled;
    for (const [i, slot] of slots.entries()) {
      slot.node.dataset.state = slot.state;
      slot.input.disabled = scanning || slot.state === "added" || slot.state === "review";
      const symbol = {added: "✓", review: "?", failed: "!", reading: "…"}[slot.state];
      const words = {added: "added to the pending list", review: "sent to Check these", failed: slot.error || "retry needed",
        reading: "reading", ready: separateFiles ? "ready" : "include this slot"}[slot.state];
      slot.caption.textContent = separateFiles ? words : symbol ? `${i + 1} ${symbol}` : String(i + 1);
      const label = separateFiles ? slotName(i) + ", " + slot.filename : slotName(i);
      slot.input.setAttribute("aria-label", label + ", " + words);
    }
    const left = slots.some(queued), complete = worked && !left;
    run.hidden = scanning || complete;
    run.disabled = !left;
    pause.hidden = !scanning;
    pause.disabled = pausing;
    discard.disabled = scanning;
    discard.textContent = separateFiles ? (complete ? "Finish batch" : "Discard images") : (complete ? "Finish page" : "Discard image");
    discard.classList.toggle("btn-primary", complete);
    run.textContent = separateFiles ? "Scan selected files" : "Scan selected slots";
    pause.textContent = separateFiles ? "Stop after this file" : "Stop after this slot";
  }
  function positionSlots() {
    slots.forEach(({node}, i) => {
      const r = rect(i);
      node.style.left = (100 * r.x / picture.width) + "%";
      node.style.top = (100 * r.y / picture.height) + "%";
      node.style.width = (100 * r.width / picture.width) + "%";
      node.style.height = (100 * r.height / picture.height) + "%";
    });
  }
  function makeSlot(i, source = null) {
    const input = el("input", {type: "checkbox", checked: true});
    const caption = el("span", {class: source ? "sub" : "", "aria-hidden": "true"});
    const node = el("label", {"data-slot": String(i + 1), class: source ? "col-scan-file" : "col-grid-slot"});
    if (source) {
      node.append(input, el("span", {text: source.name}), caption);
      fileRows.append(el("li", {}, node));
    } else {
      node.append(el("span", {class: "col-grid-slot-caption"}, input, caption));
      overlay.append(node);
    }
    input.addEventListener("change", () => { if (here() && panel.contains(input) && !scanning) sync(); });
    return {input, node, caption, source, filename: source?.name, state: "ready"};
  }
  function makeSlots() {
    [cols, rows] = SCAN_GRIDS[layouts.value];
    clear(overlay);
    slots = Array.from({length: cols * rows}, (_, i) => makeSlot(i));
    positionSlots(); sync();
  }
  function stop() {
    generation++;
    picture?.close(); picture = null;
    scanning = pausing = decoding = separateFiles = false;
    slots = []; clear(overlay); clear(fileRows);
    preview.width = preview.height = 1;
    fileField.hidden = false; file.disabled = false; file.value = "";
    panel.hidden = true; message.textContent = "";
    onChange?.();
  }
  async function openImage() {
    if (!here() || picture || separateFiles || decoding || !canScan()) return;
    const count = file.files?.length || 0;
    if (count > 100) {
      file.value = ""; message.textContent = "Choose up to 100 scanner files at a time.";
      return;
    }
    const sources = Array.from(file.files || []);
    file.value = "";
    if (!sources.length) return;
    const stamp = ++generation;
    decoding = true; file.disabled = true; onStart(); onChange?.();
    separateFiles = sources.length > 1;
    alignment.hidden = separateFiles; fileRows.hidden = !separateFiles;
    if (separateFiles) {
      const names = new Intl.Collator(undefined, {numeric: true, sensitivity: "base"});
      sources.sort((a, b) => names.compare(a.name, b.name));
      page++; fileField.hidden = true; panel.hidden = false;
      slots = sources.map((source, i) => makeSlot(i, source));
      decoding = false; sync(); onChange?.();
      message.textContent = `Batch ${page}. ${count} images in filename order. Each selected file counts as one copy.`;
      run.focus();
      return;
    }
    message.textContent = "Opening the grid image…";
    let decoded;
    try {
      decoded = await openScanBitmap(sources[0]);
      if (!owns(stamp)) return;
      const scale = Math.min(1, 960 / Math.max(decoded.width, decoded.height));
      preview.width = Math.max(1, Math.round(decoded.width * scale));
      preview.height = Math.max(1, Math.round(decoded.height * scale));
      preview.getContext("2d").drawImage(decoded, 0, 0, preview.width, preview.height);
      picture = decoded; decoded = null;
      page++; fileField.hidden = true; panel.hidden = false;
      makeSlots();
      message.textContent = `Page ${page}. Select the slots you want to scan.`;
      layouts.focus();
    } catch (error) {
      if (owns(stamp)) {
        stop();
        message.textContent = error.message || "This image couldn't be opened. Try a JPEG or PNG photo or scanner image.";
      }
    } finally {
      decoded?.close();
      if (stamp === generation) { decoding = false; file.disabled = false; onChange?.(); }
    }
  }
  layouts.addEventListener("change", () => {
    if (here() && picture && !layouts.disabled) makeSlots();
  });
  for (const input of Object.values(margins)) input.addEventListener("input", () => {
    if (!here() || !picture || input.disabled) return;
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < 0 || value > 45) input.value = String(Math.max(0, Math.min(45, value || 0)));
    positionSlots();
  });
  async function processSlots() {
    if (!here() || (!picture && !separateFiles) || scanning || !slots.some(queued)) return;
    if (!canScan()) { message.textContent = "Finish the current read or resolve queued cards, then try again."; return; }
    const stamp = generation;
    scanning = true; pausing = false; sync();
    let notice = "", interrupted = false;
    const currentRead = () => !interrupted && owns(stamp);
    const visibility = () => {
      if (document.hidden && stamp === generation) { interrupted = true; pausing = true; }
    };
    document.addEventListener("visibilitychange", visibility);
    try {
      for (const [i, slot] of slots.entries()) {
        if (!owns(stamp) || pausing) break;
        if (!queued(slot)) continue;
        if (!canScan()) { notice = "Paused. Resolve queued cards before continuing this page."; break; }
        slot.state = "reading"; slot.error = ""; sync();
        message.textContent = `Reading ${slotName(i).toLowerCase()}…`;
        let photo, next;
        try {
          if (separateFiles) {
            next = await openScanBitmap(slot.source);
            if (!currentRead()) break;
            photo = await gridCropJpeg(next, {x: 0, y: 0, width: next.width, height: next.height});
          } else photo = await gridCropJpeg(picture, rect(i));
        } catch (error) {
          slot.state = "failed"; slot.error = error.message || "Image couldn't be read";
          if (separateFiles) continue;  // One corrupt scanner file must not strand the rest.
        } finally { next?.close(); }
        if (!currentRead()) break;
        try {
          const result = photo ? await submit(photo, currentRead, slotName(i)) : "failed";
          if (stamp !== generation) break;
          if (result === "added" || result === "review") {
            // The shared sheet already staged it, even if the tab is now hidden.
            slot.state = result; slot.source = null;
          } else {
            if (!currentRead()) break;
            slot.state = "failed";
          }
        } catch (_) { slot.state = "failed"; }
        if (slot.state === "failed") {
          notice = `${slotName(i)} couldn't be read. Use ${run.textContent} to retry, or untick it to continue.`;
          break;
        }
      }
    } finally {
      document.removeEventListener("visibilitychange", visibility);
      if (stamp === generation) {
        scanning = pausing = false;
        for (const slot of slots) if (slot.state === "reading") slot.state = "ready";
        sync();
        const staged = slots.filter(slot => slot.state === "added").length;
        const review = slots.filter(slot => slot.state === "review").length;
        const left = slots.filter(queued).length;
        const unit = separateFiles ? "files" : "slots";
        if (interrupted) notice = `Scan paused when you left the tab. Scan the remaining selected ${unit} to continue.`;
        message.textContent = notice || `${separateFiles ? "Batch" : "Page"} ${page}: ${staged} added to the pending list, ${review} sent to Check these, ${left} selected ${unit} left.`
          + (left ? "" : ` Choose ${discard.textContent} to review the batch or scan another image.`);
        onChange?.();
      }
    }
  }
  file.addEventListener("change", openImage);
  run.addEventListener("click", processSlots);
  pause.addEventListener("click", () => {
    if (here() && scanning) { pausing = true; sync(); message.textContent = "Stopping after the current card…"; }
  });
  discard.addEventListener("click", () => {
    if (!here() || scanning || (!picture && !separateFiles)) return;
    stop(); message.textContent = "Previously scanned copies remain in this batch.";
    file.focus();
  });
  function refresh() {
    file.disabled = decoding || !canScan();
  }
  return {element, stop, refresh, get active() { return decoding || Boolean(picture) || separateFiles; }};
}
