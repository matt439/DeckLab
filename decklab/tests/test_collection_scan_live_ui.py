"""Exercise the live scanner with synthetic camera frames, tracks and OCR replies."""
import unittest

from decklab.tests import test_collection_scan_ui as scan_ui

CAMERA = r"""
  let now = 0, elapsedId = 0;
  const intervals = new Map();
  globalThis.setInterval = window.setInterval = fn => {
    intervals.set(++elapsedId, fn);
    return elapsedId;
  };
  globalThis.clearInterval = window.clearInterval = id => intervals.delete(id);
  globalThis.performance = { now: () => now };
  globalThis.isSecureContext = window.isSecureContext = true;
  const mat = new Uint8Array(40 * 56).fill(205);
  const card = Uint8Array.from(mat, (_, i) => (Math.floor(i / 40) + i) % 2 ? 35 : 105);
  let image = mat;
  const videos = [], encoded = [];
  globalThis.FileReader = class {
    readAsDataURL() { this.result = 'data:image/jpeg;base64,QUJD'; this.onload(); }
  };
  const create = document.createElement;
  document.createElement = tag => {
    const node = create(tag);
    if (tag === 'video') {
      node.readyState = 4;
      node.videoWidth = 1280;
      node.videoHeight = 720;
      node.play = async () => {};
      node.pause = () => {};
      videos.push(node);
    }
    if (tag === 'canvas') {
      node.getContext = () => ({
        drawImage() {},
        getImageData(_, __, w, h) {
          const rgba = new Uint8ClampedArray(w * h * 4);
          for (let i = 0; i < w * h; i++) {
            rgba.fill(image[i % image.length], i * 4, i * 4 + 3);
            rgba[i * 4 + 3] = 255;
          }
          return {data: rgba};
        },
      });
      node.toBlob = (ready, type) => { encoded.push([type, node.width, node.height]); ready({size:3}); };
    }
    return node;
  };
  function trackFixture() {
    const track = new Node('track');
    track.readyState = 'live';
    track.stops = 0;
    track.stop = () => { track.stops++; track.readyState = 'ended'; };
    const stream = {getTracks: () => [track], getVideoTracks: () => [track]};
    return {track, stream};
  }
  const hardware = trackFixture();
  navigator.mediaDevices = {getUserMedia: async () => hardware.stream};
  async function frames(scene, n) {
    image = scene;
    for (let i = 0; i < n; i++) {
      now += 120;
      for (const tick of [...intervals.values()]) tick();
      await flush();
    }
  }
  function clickText(host, label) {
    const action = button(host, label);
    assert(action, 'Missing ' + label);
    action.click();
  }
  async function start(ctx) {
    clickText(ctx.sheet.body, 'Start live camera');
    await flush();
    await frames(mat, 3);
    clickText(ctx.sheet.body, 'Set empty area');
    await frames(mat, 6);
  }
"""


@unittest.skipUnless(scan_ui.NODE, "Node.js is not installed")
class CollectionLiveCaptureTests(unittest.TestCase):
    def run_js(self, scenario):
        scan_ui.CollectionScanUiTests.run_js(self, CAMERA + scenario)

    def test_a_stable_card_counts_once_then_an_identical_physical_replacement_counts(self):
        self.run_js(r"""
          const detector = new ColScanLiveDetector();
          detector.reset(mat);
          function presentations(scene, count) {
            let captures = 0;
            for (let i = 0; i < count; i++) {
              now += 120;
              if (detector.advance(scene, now) === 'capture') captures++;
            }
            return captures;
          }
          assert.equal(presentations(mat, 12), 0, 'The empty mat is never a card');
          assert.equal(presentations(card, 50), 1, 'A long pause represents one physical copy');
          assert.equal(presentations(mat, 1), 0);
          assert.equal(presentations(card, 12), 0, 'One bad frame must not rearm a held card');
          assert.equal(presentations(mat, 6), 0);
          assert.equal(presentations(card, 12), 1, 'The next identical copy has its own presentation');
        """)

    def test_frame_for_recognition_is_a_centered_card_in_both_camera_orientations(self):
        self.run_js(r"""
          for (const [width, height] of [[1920,1080], [1080,1920], [640,480]]) {
            const crop = colScanLiveCrop(width,height);
            assert(crop.width > 0 && crop.height > crop.width);
            assert(crop.x >= 0 && crop.y >= 0);
            assert(crop.x + crop.width <= width && crop.y + crop.height <= height);
            assert(Math.abs(crop.x * 2 + crop.width - width) <= 2);
            assert(Math.abs(crop.y * 2 + crop.height - height) <= 2);
            assert(Math.abs(crop.width / crop.height - 63 / 88) < .025);
          }
        """)

    def test_in_flight_capture_cannot_be_repeated_or_submit_privately_after_a_profile_change(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw()), calls = [];
          let answer;
          apiWrite = (path, body) => {
            calls.push([path, body]);
            return new Promise(resolve => { answer = resolve; });
          };
          await start(ctx);
          await frames(card, 14);
          assert.equal(calls.length, 1);
          same(calls[0], ['/api/collection/scan', {space:'home', photo:'QUJD'}]);
          await frames(card, 20);
          assert.equal(calls.length, 1);
          state.profile = PROFILES[1];
          answer(ELVES);
          await frames(card, 6);
          assert.equal(ctx.pending.length, 0);
          assert.equal(ctx.unsure.length, 0);
          assert(hardware.track.stops > 0, 'Private capture must stop when its viewer changes');
        """)

    def test_identical_copies_and_unsure_card_join_the_reviewed_batch_once_each(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          const replies = [ELVES, ELVES, GHALTA], calls = [];
          apiWrite = async (path, body) => { calls.push(path); return replies.shift(); };
          await start(ctx);
          for (let physical = 0; physical < 3; physical++) {
            await frames(card, 15);
            await frames(mat, 7);
            if (physical === 0) {
              assert(ctx.captureIntro.hidden && ctx.photoField.hidden && ctx.grid.element.hidden);
              assert(!ctx.captureHint.hidden && ctx.captureHint.textContent.includes('1 pending'));
              assert.equal(foot(ctx, 'review'), null);
              assert.equal(foot(ctx, 'download'), null);
            }
          }
          assert.deepEqual(calls, Array(3).fill('/api/collection/scan'));
          assert.equal(ctx.pending.length, 1);
          assert.equal(ctx.pending[0].quantity, 2);
          assert.equal(ctx.unsure.length, 1);
          assert(ctx.checkList.textContent.includes('Ghalta'));
          assert(ctx.checkList.textContent.includes('Live card 3'));
          const crop = colScanLiveCrop(1280, 720);
          same(encoded, Array(3).fill(['image/jpeg', crop.width, crop.height]));
          const stop = button(ctx.sheet.body, 'Stop camera');
          stop.focus(); stop.click();
          assert.equal(document.activeElement, button(ctx.sheet.body, 'Start live camera'));
          assert(!ctx.captureIntro.hidden && !ctx.photoField.hidden && !ctx.grid.element.hidden);
          assert(ctx.captureHint.hidden);
          assert(foot(ctx, 'review') && foot(ctx, 'download'));
          ctx.sheet.close();
          assert.equal(hardware.track.stops, 1);
        """)

    def test_rejected_scan_waits_for_the_next_physical_presentation(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          let calls = 0;
          apiWrite = async () => {
            if (++calls === 1) throw new ApiError(429, 'Scanner is busy');
            return ELVES;
          };
          await start(ctx);
          await frames(card, 35);
          assert.equal(calls, 1, 'No retry storm while the rejected card sits still');
          assert.equal(ctx.pending.length, 0);
          await frames(mat, 7);
          await frames(card, 15);
          assert.equal(calls, 2);
          assert.equal(ctx.pending[0].quantity, 1);
        """)

    def test_a_replacement_seen_during_ocr_waits_in_place_for_the_first_answer(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          let calls = 0, resolveFirst;
          apiWrite = async () => {
            calls++;
            return calls === 1 ? new Promise(resolve => { resolveFirst = resolve; }) : ELVES;
          };
          await start(ctx);
          await frames(card, 10);
          assert.equal(calls, 1);
          await frames(mat, 6);
          await frames(card, 10);
          assert.equal(calls, 1, 'The server handles only one crop at a time');
          resolveFirst(ELVES);
          await frames(card, 25);
          assert.equal(calls, 2);
          assert.equal(ctx.pending[0].quantity, 2);
        """)

    def test_permission_grant_after_sheet_closes_releases_new_tracks(self):
        self.run_js(r"""
          let grant;
          navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { grant = resolve; });
          const ctx = openScanSheet(draw());
          apiWrite = () => assert.fail('A closed sheet cannot submit a frame');
          clickText(ctx.sheet.body, 'Start live camera');
          await flush();
          assert(grant);
          ctx.sheet.close();
          grant(hardware.stream);
          await frames(card, 8);
          assert.equal(hardware.track.stops, 1);
          assert(!videos.some(video => video.srcObject));
        """)

    def test_sensor_rotation_requires_new_empty_area_and_track_end_stops_capture(self):
        self.run_js(r"""
          const ctx = openScanSheet(draw());
          let seen = 0;
          apiWrite = async () => { seen++; return ELVES; };
          await start(ctx);
          const video = videos.find(node => node.srcObject);
          assert(video);
          video.videoWidth = 720;
          video.videoHeight = 1280;
          video.fire('resize');
          await frames(card, 15);
          assert.equal(seen, 0, 'A rotated view cannot reuse the old background');
          await frames(mat, 5);
          clickText(ctx.sheet.body, 'Set empty area');
          await frames(card, 15);
          assert.equal(seen, 1);
          hardware.track.readyState = 'ended';
          hardware.track.fire('ended');
          await frames(mat, 5);
          await frames(card, 10);
          assert.equal(seen, 1);
          assert(!ctx.live.active);
          assert(!video.srcObject);
        """)

    def test_a_chosen_webcam_replaces_the_initial_stream_and_requires_calibration(self):
        self.run_js(r"""
          const next = trackFixture(), requested = [];
          hardware.track.getSettings = () => ({deviceId: 'phone'});
          next.track.getSettings = () => ({deviceId: 'webcam'});
          navigator.mediaDevices.enumerateDevices = async () => [
            {kind:'videoinput',deviceId:'phone',label:'Phone'},
            {kind:'videoinput',deviceId:'webcam',label:'USB camera'},
          ];
          navigator.mediaDevices.getUserMedia = async constraints => {
            requested.push(constraints);
            return requested.length === 1 ? hardware.stream : next.stream;
          };
          const ctx = openScanSheet(draw()), picker = ctx.live.element.querySelector('select');
          let reads = 0;
          apiWrite = async () => { reads++; return ELVES; };
          await start(ctx);
          assert.equal(picker.value,'phone');
          picker.value = 'webcam'; picker.fire('change');
          await frames(card, 10);
          assert.equal(hardware.track.stops, 1);
          assert.equal(requested[1].video.deviceId.exact, 'webcam');
          assert.equal(requested[1].audio, false);
          assert.equal(reads, 0);
          await frames(mat, 5);
          clickText(ctx.sheet.body, 'Set empty area');
          await frames(card, 10);
          assert.equal(reads, 1);
          document.hidden = true;
          document.fire('visibilitychange');
          assert.equal(next.track.stops, 1);
          assert(!ctx.live.active);
        """)

    def test_permission_refusal_keeps_still_and_typed_paths_available(self):
        self.run_js(r"""
          navigator.mediaDevices.getUserMedia = async () => {
            throw Object.assign(new Error('PRIVATE OS DETAIL'), {name:'NotAllowedError'});
          };
          const ctx = openScanSheet(draw());
          clickText(ctx.sheet.body, 'Start live camera');
          await frames(card, 4);
          assert(!ctx.live.active);
          assert(!ctx.sheet.body.textContent.includes('PRIVATE OS DETAIL'));
          assert(!ctx.input.disabled);
          assert(!ctx.name.disabled);
          assert(!videos.some(video => video.srcObject));
          apiWrite = async () => ELVES;
          await shoot(ctx);
          assert.equal(ctx.pending.length, 1);
        """)
