/* Accessory picture choices, local device photos and crop controls.
 * The add/edit sheet keeps its draft until an explicit atomic row-and-picture Save. */
"use strict";

const accessorySheets = new Set();
const accessoryDialogs = new Set();
const ACC_PHOTO_MAX = 4 * 1024 * 1024;
const ACC_PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

function closeAccessorySheets() {
  for (const ctx of [...accessorySheets]) accDisposeSheet(ctx);
  for (const sheet of [...accessoryDialogs]) sheet.close();
}

/** Track the picker, its Add/Edit child, details and confirmation dialogs together. */
function openAccessoryDialog(title, options = {}) {
  if (title && typeof title === "object") { options = title; title = options.title || ""; }
  const sheet = openSheet(title, { ...options, onClose: result => {
    accessoryDialogs.delete(sheet);
    if (options.onClose) options.onClose(result);
  } });
  sheet.accessoryProfile = state.profile?.id;
  sheet.accessoryToken = routeToken;
  const close = sheet.close.bind(sheet);
  sheet.close = result => { sheet.accessoryClosing = true; close(result); };
  accessoryDialogs.add(sheet);
  return sheet;
}

function accDialogHere(sheet) {
  return !sheet.closed && !sheet.accessoryClosing && sheet.dialog.isConnected
    && sheet.accessoryProfile === state.profile?.id && sheet.accessoryToken === routeToken;
}

function askAccessoryChoice(title, paragraphs, choices) {
  return new Promise(resolve => {
    const sheet = openAccessoryDialog(title, { onClose: result => resolve(result == null ? null : result) });
    sheet.body.append(...paragraphs.map(text => el("p", { text })));
    sheetActions(sheet, choices.map(choice => ({ ...choice, onclick: () => {
      if (accDialogHere(sheet)) sheet.close(choice.value);
    } })));
    sheet.foot.querySelector(".btn-primary")?.focus();
  });
}

function accSheetHere(ctx) {
  return !ctx.cancelled && accDialogHere(ctx.sheet)
    && ctx.profile === state.profile?.id && ctx.token === routeToken && mayDo("accessories");
}

function accDisposeSheet(ctx) {
  if (!ctx || ctx.cancelled) return;
  ctx.cancelled = true;
  ctx.photoSeq = (ctx.photoSeq || 0) + 1;
  const reader = ctx.photoReader;
  ctx.photoReader = null;
  if (reader) { try { reader.abort(); } catch (_) {} }
  ctx.pic = null;
  if (ctx.photoInput) ctx.photoInput.value = "";
  accessorySheets.delete(ctx);
}

function accPhotoControls(ctx) {
  const input = ctx.photoInput = el("input", { type: "file", class: "acc-sheet-mutate",
    accept: "image/jpeg,image/png,image/webp", "aria-label": "Photo from this device",
    onchange: event => accReadPhoto(ctx, event.currentTarget.files?.[0]) });
  return el("label", { class: "field" }, el("span", { text: "Photo from this device" }), input,
    el("small", { class: "field-hint", text: "Choose from photos or your camera. JPG, PNG or WebP, up to 4 MiB. Saved when you choose Save." }));
}

/** A device photo stays in this sheet until Save; no filename, path or photo goes to a server here. */
async function accReadPhoto(ctx, file) {
  if (!accSheetHere(ctx) || ctx.busy || !file) return;
  const extension = String(file.name || "").split(".").at(-1).toLowerCase();
  const inferred = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp" }[extension];
  const type = String(file.type || inferred || "").toLowerCase();
  const problem = !Number.isFinite(file.size) || file.size <= 0 ? "Choose a picture that isn't empty."
    : file.size > ACC_PHOTO_MAX ? "That photo is larger than 4 MiB. Choose a smaller JPG, PNG or WebP picture."
      : !ACC_PHOTO_TYPES.has(type) ? "Choose a JPG, PNG or WebP picture." : null;
  if (problem) {
    ctx.photoInput.value = "";
    clear(ctx.message).append(el("p", { class: "form-error", role: "alert", text: problem }));
    return;
  }
  const sequence = ctx.photoSeq = (ctx.photoSeq || 0) + 1;
  accSheetBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Reading the photo on this device…"));
  let reader;
  try {
    const result = await new Promise((resolve, reject) => {
      reader = ctx.photoReader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("The photo couldn't be read. Choose it again or try another picture."));
      reader.onabort = () => reject(new Error("Reading the photo was cancelled."));
      reader.readAsDataURL(file);
    });
    if (!accSheetHere(ctx) || sequence !== ctx.photoSeq) return;
    const match = typeof result === "string" && /^data:[^,]*;base64,([A-Za-z0-9+/]+={0,2})$/.exec(result);
    if (!match || match[1].length > Math.ceil(ACC_PHOTO_MAX / 3) * 4) {
      throw new Error("The photo couldn't be read as a picture of at most 4 MiB. Choose it again or try another picture.");
    }
    ctx.pic = { mode: "upload", crop: "", upload: match[1], preview_url: `data:${type};base64,${match[1]}` };
    ctx.touched.add("crop");
    clear(ctx.message).append(el("p", { text: "Photo chosen. You can crop it before saving." }));
  } catch (error) {
    if (accSheetHere(ctx) && sequence === ctx.photoSeq) {
      clear(ctx.message).append(el("p", { class: "form-error", role: "alert", text: error.message }));
    }
  } finally {
    if (ctx.photoReader === reader) ctx.photoReader = null;
    if (sequence === ctx.photoSeq) ctx.photoInput.value = "";
    if (accSheetHere(ctx) && sequence === ctx.photoSeq) { accSheetBusy(ctx, false); drawPicture(ctx); }
  }
}

function drawPicture(ctx) {
  if (!accSheetHere(ctx)) return;
  const pic = ctx.pic;
  const row = ctx.row;
  clear(ctx.picture);
  const action = (text, onclick) => el("button", { type: "button", class: "btn btn-quiet acc-sheet-mutate", text,
    onclick: () => { if (accSheetHere(ctx) && !ctx.busy) onclick(); } });
  if (pic.mode === "staged" || pic.mode === "upload") {
    ctx.picture.append(el("figure", { class: "acc-preview" },
      accessoryThumb({ image_url: accWithCrop(pic.preview_url, pic.crop), label: "" }, null, pic.mode === "upload"),
      el("figcaption", { class: "sub", text: (pic.mode === "upload" ? "The photo chosen on this device"
        : `The picture found (${pic.width} × ${pic.height})`) + (pic.crop ? ", cropped" : "") })),
    el("div", { class: "acc-picture-actions" },
      ...accCropActions(ctx, action, pic.preview_url),
      action("Use a different picture", () => {
        ctx.pic = accKeptPicture(row);
        drawPicture(ctx);
        ctx.inputs.link.focus();
      }),
      action("Save without a picture", () => { ctx.pic = accKeptPicture(null); drawPicture(ctx); saveFromSheet(ctx); })));
  } else if (pic.mode === "keep") {
    ctx.picture.append(el("figure", { class: "acc-preview" },
      accessoryThumb({ ...row, image_url: accWithCrop(row.image_url, pic.crop) }, null),
      add(el("figcaption", { class: "sub" }, `The picture saved now${pic.crop ? ", cropped" : ""}`),
        [accLink(row) ? [" · ", accLink(row)] : null])),
    el("div", { class: "acc-picture-actions" },
      ...accCropActions(ctx, action, row.image_url),
      action("Replace picture", () => {
        ctx.message.textContent = "Choose a photo from this device, or paste a link above and Find picture.";
        ctx.inputs.link.focus();
      }),
      action("Remove picture", () => { ctx.pic = accKeptPicture(null); drawPicture(ctx); })));
  } else {
    add(ctx.picture, [el("p", { class: "sub acc-no-picture", text: "Choose a photo from this device, paste a link and tap Find picture, or save without a picture." }),
      row && row.image_url ? action("Keep the saved picture", () => { ctx.pic = accKeptPicture(row); drawPicture(ctx); }) : null]);
  }
  accSheetBusy(ctx, ctx.busy);
}

/** The picture's Crop… (and, when cropped, Show the whole picture) buttons, for drawPicture. */
function accCropActions(ctx, action, url) {
  return [action(ctx.pic.crop ? "Change crop" : "Crop…", () => openCropper(ctx, url)),
    ctx.pic.crop ? action("Show the whole picture", () => { ctx.pic.crop = ""; ctx.touched.add("crop"); drawPicture(ctx); }) : null];
}

/** "x,y,w,h" for a crop rectangle of fractions, 4 decimals at most; "" for (about) the whole picture. */
function accCropText(r) {
  if (r.x < 0.0005 && r.y < 0.0005 && r.w > 0.9995 && r.h > 0.9995) return "";
  return [r.x, r.y, r.w, r.h].map((n) => String(Math.round(n * 10000) / 10000)).join(",");
}

/** Crop the sheet's picture in place: the whole picture with a box to drag (or its corners), on any
 * device; arrow keys move the box, Shift and arrow keys resize it. Done keeps the crop for Save. */
function openCropper(ctx, url) {
  if (!accSheetHere(ctx) || ctx.busy) return;
  const start = accCropOf(accWithCrop(url, ctx.pic.crop)) || [0, 0, 1, 1];
  const r = { x: start[0], y: start[1], w: start[2], h: start[3] };
  const img = el("img", { src: accImgSrc(url), alt: "", draggable: "false" });
  const handles = ["nw", "ne", "sw", "se"].map((corner) => el("span", { class: `acc-crop-handle acc-crop-${corner}`,
    "data-corner": corner, "aria-hidden": "true" }));
  const said = el("p", { class: "sub acc-crop-said", "aria-live": "polite" });
  const box = el("div", { class: "acc-crop-box", tabindex: "0", role: "group",
    "aria-label": "Crop area. Arrow keys move it; Shift and arrow keys resize it." }, handles);
  // The shading outside the box is clipped to the picture; the box and its handles aren't, so a corner at
  // the picture's edge can still be grabbed.
  const shade = el("div", { class: "acc-crop-shade" });
  // Until the picture loads the stage is a square of the picture placeholder's colour; a picture that won't
  // load says so instead of leaving a cropper with nothing in it.
  const stage = el("div", { class: "acc-crop-stage acc-crop-loading" }, img, el("div", { class: "acc-crop-clip", "aria-hidden": "true" }, shade), box);
  img.addEventListener("load", () => stage.classList.remove("acc-crop-loading"));
  img.addEventListener("error", () => {
    if (!accSheetHere(ctx) || !stage.isConnected) return;
    clear(ctx.picture).append(el("div", { class: "acc-cropper" },
      el("p", { class: "form-error", role: "alert", text: "The picture couldn't be loaded for cropping." }),
      el("div", { class: "acc-picture-actions" }, button("Back", close))));
  });
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const draw = () => {
    const place = { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` };
    Object.assign(box.style, place);
    Object.assign(shade.style, place);
    said.textContent = accCropText(r) ? `Showing ${Math.round(r.w * 100)}% × ${Math.round(r.h * 100)}% of the picture.`
      : "Showing the whole picture.";
  };
  /** Move (corner null) or resize from a corner by dx, dy (fractions), from the rectangle s. */
  const change = (s, corner, dx, dy) => {
    if (!corner) {
      r.x = clamp(s.x + dx, 0, 1 - s.w); r.y = clamp(s.y + dy, 0, 1 - s.h); r.w = s.w; r.h = s.h;
      return;
    }
    const right = s.x + s.w, bottom = s.y + s.h;
    if (corner.includes("w")) { r.x = clamp(s.x + dx, 0, right - ACC_MIN_CROP); r.w = right - r.x; }
    else { r.x = s.x; r.w = clamp(s.w + dx, ACC_MIN_CROP, 1 - s.x); }
    if (corner.includes("n")) { r.y = clamp(s.y + dy, 0, bottom - ACC_MIN_CROP); r.h = bottom - r.y; }
    else { r.y = s.y; r.h = clamp(s.h + dy, ACC_MIN_CROP, 1 - s.y); }
  };
  let drag = null;
  box.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const rect = stage.getBoundingClientRect();
    drag = { id: event.pointerId, corner: event.target.dataset.corner || null, from: { ...r },
      x: event.clientX, y: event.clientY, width: rect.width, height: rect.height };
    box.setPointerCapture(event.pointerId);
    box.focus({ preventScroll: true });
  });
  box.addEventListener("pointermove", (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    change(drag.from, drag.corner, (event.clientX - drag.x) / drag.width, (event.clientY - drag.y) / drag.height);
    draw();
  });
  const stop = (event) => { if (drag && event.pointerId === drag.id) drag = null; };
  box.addEventListener("pointerup", stop);
  box.addEventListener("pointercancel", stop);
  box.addEventListener("keydown", (event) => {
    const step = { ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01] }[event.key];
    if (!step) return;
    event.preventDefault();
    change({ ...r }, event.shiftKey ? "se" : null, step[0], step[1]);
    draw();
  });
  const square = () => {
    // As big a square (on screen) as fits, centred on the box as it is now.
    const aspect = img.naturalWidth && img.naturalHeight ? img.naturalWidth / img.naturalHeight : 1;
    const side = Math.min(r.w * aspect, r.h, 1, aspect);       // in picture heights
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    r.w = side / aspect; r.h = side;
    r.x = clamp(cx - r.w / 2, 0, 1 - r.w); r.y = clamp(cy - r.h / 2, 0, 1 - r.h);
    draw();
  };
  const button = (text, onclick, kind = "btn") => el("button", { type: "button", class: `${kind} acc-sheet-mutate`, text, onclick });
  const close = () => { drawPicture(ctx); };
  clear(ctx.picture).append(el("div", { class: "acc-cropper" },
    el("p", { class: "sub", text: "Drag the box to choose the part of the picture to show, or drag its corners to resize it. The picture file isn't changed." }),
    stage, said,
    el("div", { class: "acc-picture-actions" },
      button("Done", () => { if (!accSheetHere(ctx)) return; ctx.pic.crop = accCropText(r); ctx.touched.add("crop"); close(); }, "btn btn-primary"),
      button("Square", square),
      button("Whole picture", () => { Object.assign(r, { x: 0, y: 0, w: 1, h: 1 }); draw(); }),
      button("Cancel", close, "btn btn-quiet"))));
  draw();
  box.focus({ preventScroll: true });
}

function accSheetBusy(ctx, busy) {
  ctx.busy = busy;
  ctx.form.setAttribute("aria-busy", String(busy));
  for (const control of ctx.form.querySelectorAll(".acc-sheet-mutate")) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy || button.dataset.blocked === "true";
}

async function findPicture(ctx) {
  if (ctx.busy || !accSheetHere(ctx)) return;
  const url = ctx.inputs.link.value.trim();
  if (!url) {
    ctx.message.textContent = "Paste a link to the product or its picture first.";
    ctx.inputs.link.focus();
    return;
  }
  accSheetBusy(ctx, true);
  ctx.find.setAttribute("aria-busy", "true");
  clear(ctx.message).append(loadingBox("Finding the picture…"));
  try {
    const found = await apiWrite("/api/accessories/fetch", { url, ...(ctx.row?.id ? { id: ctx.row.id } : {}) });
    if (!accSheetHere(ctx)) return;
    ctx.pic = { mode: "staged", crop: "", token: found.token, preview_url: found.preview_url, width: found.width,
      height: found.height, image_source: found.image_source || "" };
    const filled = accApplyGuess(ctx, found.guess || {});
    clear(ctx.message).append(el("p", { text: filled.length
      ? `Found it. The ${saidList(filled)} came from the page: check them before saving.`
      : "Found it. Fill in the details below before saving." }));
  } catch (error) {
    if (!accSheetHere(ctx)) return;
    clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message })));
  } finally {
    ctx.find.removeAttribute("aria-busy");
    if (accSheetHere(ctx)) { accSheetBusy(ctx, false); drawPicture(ctx); }
  }
}
