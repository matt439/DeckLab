/* A fixed phone or webcam samples a small guide locally. Only a settled card's
 * cropped still goes through Collection's ordinary one-photo review flow. */
"use strict";

const COL_LIVE_WIDTH = 40, COL_LIVE_HEIGHT = 56;

function colScanLiveCrop(width, height) {
  // Keep the whole upright card and a small clear margin in view, in either orientation.
  const h = Math.max(1, Math.round(0.88 * Math.min(height, width * 88 / 63)));
  const w = Math.max(1, Math.round(h * 63 / 88));
  return {x: Math.round((width - w) / 2), y: Math.round((height - h) / 2), width: w, height: h};
}

/** Pixel differences after allowing a small overall shift from camera auto-exposure. */
function colLiveDifference(a, b) {
  let shift = 0;
  for (let i = 0; i < a.length; i++) shift += a[i] - b[i];
  shift = Math.max(-32, Math.min(32, shift / a.length));
  let sum = 0, changed = 0;
  for (let i = 0; i < a.length; i++) {
    const delta = Math.abs(a[i] - b[i] - shift);
    sum += delta;
    if (delta > 17) changed++;
  }
  return {mean: sum / a.length, fraction: changed / a.length};
}

function colLiveDetail(frame) {
  let edges = 0;
  for (let y = 1; y < COL_LIVE_HEIGHT; y++) {
    for (let x = 1; x < COL_LIVE_WIDTH; x++) {
      const i = y * COL_LIVE_WIDTH + x;
      edges += Math.abs(frame[i] - frame[i - 1]) + Math.abs(frame[i] - frame[i - COL_LIVE_WIDTH]);
    }
  }
  return edges / (2 * (COL_LIVE_HEIGHT - 1) * (COL_LIVE_WIDTH - 1));
}

class ColScanLiveDetector {
  reset(emptyLuma) {
    this.empty = emptyLuma.slice();
    this.latched = false;
    this.clearSince = null;
    this.anchor = null;
    this.keepFrame = false;
  }

  advance(frame, now) {
    this.keepFrame = false;
    const background = colLiveDifference(frame, this.empty);
    const empty = background.fraction <= 0.10 && background.mean < 10;
    if (this.latched) {
      if (!empty) this.clearSince = null;
      else if (this.clearSince === null) this.clearSince = now;
      else if (now - this.clearSince >= 180) this.latched = false;
      return this.latched ? "clear" : "waiting";
    }
    const detail = colLiveDetail(frame);
    if (empty || background.fraction < 0.20 || detail < 2.5) {
      this.anchor = null;
      return "waiting";
    }
    const movement = this.anchor && colLiveDifference(frame, this.anchor);
    if (!movement || movement.mean > 6 || movement.fraction > 0.12) {
      this.anchor = frame.slice();
      this.stableSince = now;
      this.samples = 0;
      this.bestDetail = -1;
    }
    this.samples++;
    if (detail > this.bestDetail) {
      this.keepFrame = true;
      this.bestDetail = detail;
    }
    if (this.samples >= 3 && now - this.stableSince >= 280) {
      this.latched = true;
      this.clearSince = this.anchor = null;
      return "capture";
    }
    return "steady";
  }
}

function colLiveSample(sample, video, crop) {
  const context = sample.getContext("2d", {willReadFrequently: true});
  context.drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, sample.width, sample.height);
  const rgba = context.getImageData(0, 0, sample.width, sample.height).data;
  const luma = new Uint8Array(sample.width * sample.height);
  for (let i = 0; i < luma.length; i++) {
    const k = i * 4;
    luma[i] = (77 * rgba[k] + 150 * rgba[k + 1] + 29 * rgba[k + 2]) >> 8;
  }
  return luma;
}

function colLiveKeepStill(canvas, video, crop) {
  const scale = Math.min(1, COL_SCAN_SIDE / Math.max(crop.width, crop.height));
  const width = Math.max(1, Math.round(crop.width * scale)), height = Math.max(1, Math.round(crop.height * scale));
  if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  canvas.getContext("2d").drawImage(video, crop.x, crop.y, crop.width, crop.height, 0, 0, width, height);
}

function colLiveRelease(stream) {
  for (const track of stream?.getTracks() || []) track.stop();
}

function colLiveSound(audio, review) {
  if (!audio || audio.state !== "running") return;
  try {
    const tone = audio.createOscillator(), level = audio.createGain();
    const time = audio.currentTime;
    tone.frequency.value = review ? 370 : 780;
    level.gain.setValueAtTime(0.09, time);
    level.gain.exponentialRampToValueAtTime(0.001, time + 0.12);
    tone.connect(level); level.connect(audio.destination);
    tone.onended = () => { tone.disconnect(); level.disconnect(); };
    tone.start(time); tone.stop(time + 0.12);
  } catch (_) { /* The same result is always visible. */ }
}

/** The page owns each accepted still. Keep permission requests, streams and callbacks local to this sheet. */
function colScanLive({isCurrent, canScan, submit, onStart, onChange, addedLabel}) {
  const start = el("button", {type: "button", class: "btn", text: "Start live camera"});
  const end = el("button", {type: "button", class: "btn", hidden: true, text: "Stop camera"});
  const calibrate = el("button", {type: "button", class: "btn", text: "Set empty area", hidden: true});
  const camera = el("select", {}, el("option", {value: "", text: "Automatic camera"}));
  const picker = el("label", {class: "field", hidden: true}, el("span", {text: "Camera"}), camera);
  const sound = el("input", {type: "checkbox"});
  const soundField = el("label", {class: "check", hidden: true}, sound, el("span", {text: "Sound cue"}));
  const video = el("video", {muted: true, autoplay: true, playsinline: true, "aria-label": "Live card preview"});
  video.muted = true;
  const guide = el("span", {class: "col-scan-live-guide", "aria-hidden": "true"});
  const preview = el("div", {class: "col-scan-live-frame", hidden: true}, video, guide);
  const status = el("p", {class: "sub", role: "status"});
  const outcome = el("p", {role: "status"});
  const root = el("section", {class: "col-scan-live", "aria-label": "Live camera"},
    el("div", {class: "actions"}, start, end, calibrate), outcome, status, preview, picker, soundField);
  const devices = navigator.mediaDevices;
  let run = null, presentation = 0;
  const here = () => root.isConnected && !document.hidden && isCurrent();
  const current = session => run === session && here();
  const say = words => { if (status.textContent !== words) status.textContent = words; };
  const unsupported = window.isSecureContext === false
    ? "Live camera needs HTTPS or localhost. You can still take a photo."
    : !devices?.getUserMedia ? "Live camera is unavailable in this browser. You can still take a photo." : "";

  function stop(reason = "Camera stopped.") {
    const session = run;
    if (!session) return;
    const restoreFocus = here() && root.contains(document.activeElement);
    run = null;
    clearInterval(session.timer);
    window.removeEventListener("pagehide", session.leave);
    document.removeEventListener("visibilitychange", session.visibility);
    for (const track of session.stream?.getTracks() || []) track.removeEventListener("ended", session.ended);
    colLiveRelease(session.stream);
    video.srcObject = null;
    session.sample.width = session.still.width = 0;
    session.audio?.close().catch(() => {});
    start.hidden = false; end.hidden = preview.hidden = calibrate.hidden = picker.hidden = soundField.hidden = true;
    say(session.reading ? reason + " Live card " + presentation + " was interrupted. Present it again." : reason);
    onChange?.();
    if (restoreFocus) start.focus();
  }

  function enableSound(session) {
    if (!sound.checked || !session || session.audio) return;
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) return;
    try {
      session.audio = new Audio();
      session.audio.resume().catch(() => {});
    } catch (_) { /* The visual cue works with sound disabled. */ }
  }

  function geometry(session) {
    const w = video.videoWidth, h = video.videoHeight;
    if (!w || !h) return null;
    if (session.w !== w || session.h !== h) {
      session.w = w; session.h = h;
      session.crop = colScanLiveCrop(w, h);
      preview.style.setProperty("--col-live-ratio", String(w / h));
      const c = session.crop;
      guide.style.left = (100 * c.x / w) + "%"; guide.style.top = (100 * c.y / h) + "%";
      guide.style.width = (100 * c.width / w) + "%"; guide.style.height = (100 * c.height / h) + "%";
      session.detector = null;
      calibrate.disabled = session.reading;
      say("Clear the outline, then choose Set empty area.");
    }
    return session.crop;
  }

  async function read(session) {
    session.reading = calibrate.disabled = true;
    const label = "Live card " + (++presentation);
    const valid = () => current(session);
    say(label + " captured. Clear the outline while it is read.");
    try {
      const photo = await colScanEncodeCanvas(session.still);
      if (!valid()) return;
      const result = await submit(photo, valid, label);
      if (!valid()) return;
      const printing = result === "added" ? addedLabel?.() : "";
      outcome.textContent = result === "added" ? (printing ? label + " · " + printing + " added to this batch." : label + " added to the pending list.")
        : result === "review" ? label + " needs checking. Put it in your review pile."
          : label + " wasn't captured in the batch. Present it again or take a photo.";
      if (sound.checked) colLiveSound(session.audio, result !== "added");
    } catch (_) {
      if (valid()) outcome.textContent = label + " couldn't be read. Clear the outline and present it again.";
    } finally {
      if (run === session) {
        session.reading = calibrate.disabled = false;
        if (valid() && session.detector) say(session.detector.latched ? "Clear the outline for the next card."
          : "Ready for the next card.");
      }
    }
  }

  function tick(session) {
    if (run !== session) return;
    if (!here()) { stop(); return; }
    if (!session.playing) return;
    try {
      const crop = geometry(session);
      if (!crop || !session.detector) return;
      // Observe removal while OCR runs, but wait for its outcome before capturing another copy.
      if (!session.detector.latched && (session.reading || !canScan())) {
        if (!session.reading) say("Finish the current scan or resolve entries in Check these to continue.");
        return;
      }
      const frame = colLiveSample(session.sample, video, crop);
      const state = session.detector.advance(frame, performance.now());
      if (session.reading) return;
      if (session.detector.keepFrame) colLiveKeepStill(session.still, video, crop);
      if (state === "capture") { read(session); return; }
      say(state === "clear" ? "Clear the outline for the next card."
        : state === "steady" ? "Hold the card still."
          : "Ready. Fill the outline with one upright card.");
    } catch (_) { stop("The video frame couldn't be read. Restart the camera or take a photo."); }
  }

  async function showDevices(session) {
    if (!devices.enumerateDevices) return;
    try {
      const cameras = (await devices.enumerateDevices()).filter(d => d.kind === "videoinput" && d.deviceId);
      if (!current(session)) return;
      const chosen = session.stream.getVideoTracks?.()[0]?.getSettings?.().deviceId;
      clear(camera).append(el("option", {value: "", text: "Automatic camera"}));
      cameras.forEach((d, i) => camera.append(el("option", {value: d.deviceId, text: d.label || ("Camera " + (i + 1))})));
      camera.value = cameras.some(d => d.deviceId === chosen) ? chosen : "";
      picker.hidden = cameras.length < 2;
    } catch (_) { /* Browsers can grant video while withholding device enumeration. */ }
  }

  async function begin() {
    if (run || !here() || !canScan() || unsupported) return;
    const session = {playing: false, reading: false, sample: document.createElement("canvas"),
      still: document.createElement("canvas"), stream: null};
    run = session;
    session.sample.width = COL_LIVE_WIDTH; session.sample.height = COL_LIVE_HEIGHT;
    session.leave = () => { if (run === session) stop(); };
    session.visibility = () => { if (document.hidden) session.leave(); };
    session.ended = () => {
      if (run !== session) return;
      camera.value = "";
      stop("The camera disconnected. Start the camera again or take a photo.");
    };
    window.addEventListener("pagehide", session.leave);
    document.addEventListener("visibilitychange", session.visibility);
    start.hidden = true; end.hidden = soundField.hidden = false;
    end.focus();
    outcome.textContent = ""; say("Opening the camera…");
    session.timer = setInterval(() => tick(session), 120);
    enableSound(session); onChange?.();
    try {
      const selection = camera.value ? {deviceId: {exact: camera.value}} : {facingMode: {ideal: "environment"}};
      // Preserve collector text on a 4K webcam or phone. The detector samples only a tiny guide.
      const stream = await devices.getUserMedia({audio: false, video: {...selection,
        width: {ideal: 3840}, height: {ideal: 2160}, frameRate: {ideal: 15}}});
      if (!current(session)) { colLiveRelease(stream); if (run === session) stop(); return; }
      session.stream = stream;
      for (const track of stream.getTracks()) track.addEventListener("ended", session.ended);
      video.srcObject = stream; preview.hidden = false;
      await video.play();
      if (!current(session)) { if (run === session) stop(); return; }
      session.playing = true;
      calibrate.hidden = false; calibrate.disabled = true;
      geometry(session);
      onStart?.(); showDevices(session);
    } catch (error) {
      if (run === session) {
        if (error?.name !== "NotAllowedError") camera.value = "";
        stop(error?.name === "NotAllowedError"
          ? "Camera access was declined. Allow it in your browser or take a photo."
          : "The camera couldn't be opened. Check that it is connected and available, or take a photo.");
      }
    }
  }

  start.addEventListener("click", begin);
  end.addEventListener("click", () => stop());
  camera.addEventListener("change", () => { if (run && here()) { stop(); begin(); } });
  sound.addEventListener("change", () => { if (here()) enableSound(run); });
  calibrate.addEventListener("click", () => {
    if (!run?.playing || run.reading || !here() || !canScan()) return;
    try {
      const crop = geometry(run);
      if (!crop) return;
      const detector = new ColScanLiveDetector();
      detector.reset(colLiveSample(run.sample, video, crop));
      run.detector = detector;
      say("Ready. Fill the outline with one upright card.");
    } catch (_) { stop("The video frame couldn't be read. Restart the camera or take a photo."); }
  });
  if (unsupported) { start.disabled = true; say(unsupported); }
  return {element: root, stop, refresh: () => { start.disabled = Boolean(unsupported) || !canScan(); },
    get active() { return Boolean(run); }};
}
