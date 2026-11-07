"""The accessory sheet saves its currently visible crop as one atomic request.

Real scripts, invented pictures and event doubles; no browser, files or live writes.
"""
import unittest

from decklab.tests import test_accessory_upload_ui as upload_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AccessoryActiveCropTests(unittest.TestCase):
    run_js = upload_ui.AccessoryUploadInteractionTests.run_js

    def test_direct_save_matches_done_for_kept_uploaded_and_staged_pictures(self):
        self.run_js(r"""
          for (const mode of ['keep', 'upload', 'staged']) {
            const crops = [];
            for (const doneFirst of [false, true]) {
              const {sheet, ctx} = opened({row: existing});
              if (mode === 'upload') {choose(ctx); readers.at(-1).finish(); await flush();}
              if (mode === 'staged') {
                ctx.pic = {mode, crop: '', token: 'chosen', preview_url: '/accessory-img/staged/chosen',
                  width: 100, height: 100, image_source: 'https://shop.example/new.png'};
                drawPicture(ctx);
              }
              button(ctx.picture, /Crop|Change crop/).click();
              ctx.picture.querySelector('.acc-crop-stage').querySelector('img').fire('load');
              const area = ctx.picture.querySelector('.acc-crop-box');
              area.fire('keydown', {key: 'ArrowLeft', shiftKey: true});
              if (doneFirst) button(ctx.picture, 'Done').click();
              const before = posts().length;
              button(sheet.foot, 'Save').click(); await flush();
              assert.equal(posts().length, before + 1);
              const body = posts().at(-1).body;
              assert.equal(body.sha256, 's1'); assert.equal(body.id, existing.id);
              assert(body.row.crop && body.row.crop !== existing.crop);
              same(body.image, mode === 'keep' ? 'keep' : mode === 'upload' ? {upload: 'AQID'} : {token: 'chosen'});
              crops.push(body.row.crop); assert(sheet.closed); assert.equal(ctx.activeCrop, null);
            }
            same(crops[0], crops[1]);
          }
        """)

    def test_pointer_crop_saves_without_done_and_cancel_keeps_prior_geometry(self):
        self.run_js(r"""
          for (const cancel of [false, true]) {
            const {sheet, ctx} = opened({row: existing});
            button(ctx.picture, 'Change crop').click();
            ctx.picture.querySelector('.acc-crop-stage').querySelector('img').fire('load');
            const area = ctx.picture.querySelector('.acc-crop-box');
            area.setPointerCapture = () => {};
            area.fire('pointerdown', {button: 0, pointerId: 5, clientX: 0, clientY: 0});
            area.fire('pointermove', {pointerId: 5, clientX: 5, clientY: 0});
            area.fire('pointerup', {pointerId: 5});
            if (cancel) {button(ctx.picture, 'Cancel').click(); assert.equal(ctx.activeCrop, null);}
            button(sheet.foot, 'Save').click(); await flush();
            assert.equal(posts().at(-1).body.row.crop, cancel ? existing.crop : '0.15,0.1,0.8,0.8');
          }
        """)

    def test_loading_and_failed_crop_keep_the_draft_and_block_unknown_geometry(self):
        self.run_js(r"""
          const {sheet, ctx} = opened({row: existing});
          ctx.inputs.notes.value = 'Keep this draft';
          button(ctx.picture, 'Change crop').click();
          const image = ctx.picture.querySelector('.acc-crop-stage').querySelector('img');
          button(sheet.foot, 'Save').click(); await flush();
          assert.equal(posts().length, 0); assert(ctx.message.textContent.includes('Wait for the picture'));
          assert.equal(ctx.pic.crop, existing.crop); assert(!sheet.closed);
          image.fire('error'); button(sheet.foot, 'Save').click(); await flush();
          assert.equal(posts().length, 0); assert(ctx.message.textContent.includes("couldn't be loaded"));
          button(ctx.picture, 'Back').click(); assert.equal(ctx.activeCrop, null);
          button(ctx.picture, 'Change crop').click();
          ctx.picture.querySelector('.acc-crop-stage').querySelector('img').fire('load');
          ctx.picture.querySelector('.acc-crop-box').fire('keydown', {key: 'ArrowLeft', shiftKey: true});
          button(sheet.foot, 'Save').click(); await flush();
          assert.equal(posts().length, 1); assert.equal(posts()[0].body.row.notes, 'Keep this draft');
          assert.notEqual(posts()[0].body.row.crop, existing.crop);
        """)

    def test_direct_save_failure_retains_crop_for_retry_and_conflict_reapply(self):
        self.run_js(r"""
          for (const conflict of [false, true]) {
            const {sheet, ctx} = opened({row: existing});
            choose(ctx); readers.at(-1).finish(); await flush();
            button(ctx.picture, /^Crop/).click();
            ctx.picture.querySelector('.acc-crop-stage').querySelector('img').fire('load');
            ctx.picture.querySelector('.acc-crop-box').fire('keydown', {key: 'ArrowLeft', shiftKey: true});
            respond = async () => {const error = new Error('Synthetic save failure');
              if (conflict) {error.status = 409; error.data = {latest: {sha256: 's2', items: [{...existing, quantity: 200}]}};}
              throw error;};
            const before = posts().length;
            button(sheet.foot, 'Save').click(); await flush();
            const first = posts().at(-1).body; assert(first.row.crop); assert(!sheet.closed);
            assert.equal(ctx.activeCrop, null); assert.equal(ctx.pic.crop, first.row.crop);
            respond = async () => ({ok: true, data: {items: []}});
            button(sheet.foot, conflict ? /re-apply my changes/ : 'Save').click(); await flush();
            assert.equal(posts().length, before + 2);
            const retry = posts().at(-1).body;
            same(retry.image, first.image); assert.equal(retry.row.crop, first.row.crop);
            assert.equal(retry.sha256, conflict ? 's2' : 's1'); assert(sheet.closed);
          }
        """)

    def test_replaced_redrawn_and_disposed_crop_handlers_cannot_change_the_draft(self):
        self.run_js(r"""
          for (const change of ['redraw', 'photo', 'find', 'close', 'profile', 'route']) {
            state.profile = matt;
            const {sheet, ctx} = opened({row: existing});
            button(ctx.picture, 'Change crop').click();
            const image = ctx.picture.querySelector('.acc-crop-stage').querySelector('img');
            image.fire('load');
            const area = ctx.picture.querySelector('.acc-crop-box'), done = button(ctx.picture, 'Done');
            const active = ctx.activeCrop;
            area.fire('keydown', {key: 'ArrowLeft', shiftKey: true});
            if (change === 'redraw') drawPicture(ctx);
            if (change === 'photo') {choose(ctx); readers.at(-1).finish(); await flush();}
            if (change === 'find') {
              ctx.inputs.link.value = 'https://shop.example/picture';
              respond = async () => ({token: 'replacement', preview_url: '/accessory-img/staged/replacement', width: 40, height: 60});
              await findPicture(ctx);
            }
            if (change === 'close') sheet.close();
            if (change === 'profile') state.profile = user1;
            if (change === 'route') routeToken += 1;
            const before = JSON.stringify(ctx.pic), sent = posts().length;
            done.click(); image.fire('load'); image.fire('error');
            area.fire('keydown', {key: 'ArrowLeft', shiftKey: true});
            assert.equal(active.commit(), false); await saveFromSheet(ctx); await flush();
            if (change === 'profile' || change === 'route' || change === 'close') assert.equal(posts().length, sent);
            // The direct current Save may complete; stale crop callbacks cannot supply their old rectangle.
            if (posts().length > sent) assert.equal(posts().at(-1).body.row.crop, JSON.parse(before).crop || '');
            else assert.equal(JSON.stringify(ctx.pic), before);
            sheet.close(); assert.equal(ctx.activeCrop, null);
          }
        """)

    def test_failed_picture_replacements_leave_a_matching_prior_preview_and_crop(self):
        self.run_js(r"""
          for (const replacement of ['photo', 'find']) {
            const {sheet, ctx} = opened({row: existing});
            button(ctx.picture, 'Change crop').click();
            ctx.picture.querySelector('.acc-crop-stage').querySelector('img').fire('load');
            ctx.picture.querySelector('.acc-crop-box').fire('keydown', {key: 'ArrowLeft', shiftKey: true});
            const active = ctx.activeCrop;
            ctx.inputs.notes.value = 'Retain these notes';
            let pending;
            if (replacement === 'photo') {
              choose(ctx);
            } else {
              ctx.inputs.link.value = 'https://shop.example/picture';
              const answer = held();
              respond = () => answer.promise;
              pending = findPicture(ctx);
              answer.reject(new Error('Synthetic find failure'));
            }
            assert.equal(ctx.activeCrop, null);
            assert.equal(ctx.picture.querySelector('.acc-crop-stage'), null,
              'starting a replacement visibly cancels its uncommitted crop');
            assert.equal(active.commit(), false);
            assert(button(sheet.foot, 'Save').disabled);
            if (replacement === 'photo') readers.at(-1).fail();
            if (pending) await pending;
            await flush();
            assert.equal(ctx.pic.crop, existing.crop);
            assert.equal(ctx.picture.querySelector('.acc-crop-stage'), null);
            assert.equal(ctx.inputs.notes.value, 'Retain these notes');
            assert(!button(sheet.foot, 'Save').disabled);
            respond = async () => ({ok: true, data: {items: []}});
            button(sheet.foot, 'Save').click(); await flush();
            assert.equal(posts().at(-1).body.row.crop, existing.crop);
            assert.equal(posts().at(-1).body.row.notes, 'Retain these notes');
            assert.equal(posts().at(-1).body.image, 'keep');
          }
        """)
