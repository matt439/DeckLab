"""Saved packing-list hints remain separate from physical allocation and visibility guesses."""
import json
import subprocess
import unittest

from decklab.tests.test_collection_layout_ui import FIXTURE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


HINTS = FIXTURE + r"""
  const key = 'fdn|1|nonfoil';
  const hint = (id = 'casual/saved', version = 'target', extra = {}) =>
    ({id, title: 'Saved deck', quantity: 2, version, ...extra});
  const entry = (extra = {}) => ({held: 3, guess: true, listed_holders: [hint()], unattributed: 1, ...extra});
  const drawHints = (saved = entry(), extra = {}) => draw({storage: {rows: {[key]: saved}, error: null}, ...extra});
  const caption = (chosen = key) => {
    const open = casualRows().find(node => node.getAttribute('data-key') === chosen).querySelector('.col-casual-open');
    const group = viewerGroup(open); return group.items[group.index].caption;
  };
  const surfaces = (cv, chosen = key) => {
    colSelectRow(cv, chosen);
    return [tableRow(chosen).querySelector('.col-td-held'), preview(), caption(chosen)];
  };
  const mountedCaption = () => { const words = caption(); document.body.append(words); return words; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionHintsUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), HINTS + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_lab_marker_is_static_and_full_hints_keep_aggregate_counts_and_their_limits(self):
        self.run_js(r"""
          const cv = drawHints(), [cell, selected, words] = surfaces(cv);
          assert(cell.textContent.includes('3 in decks?')); assert(cell.textContent.includes('1 free'));
          assert(cell.querySelector('.sr-only').textContent.includes('Printing allocation uncertain'));
          const marker = cell.querySelector('.col-packing-marker');
          assert.equal(marker.textContent, 'Saved list hints'); assert(marker.getAttribute('title').includes('may differ from the boxes'));
          assert.equal(marker.getAttribute('tabindex'), null); assert.equal(marker.querySelector('a'), null);
          assert.equal(cell.querySelector('a'), null); assert.equal(cell.querySelector('button'), null);
          for (const root of [selected, words]) {
            assert(root.textContent.includes('Saved packing-list hints:'));
            assert(root.textContent.includes('2 \u00d7 Saved deck (Planned list)'));
            assert(root.textContent.includes('1 held copy without a named hint.'));
            assert(root.textContent.includes('Saved packing lists may differ from the boxes and current deck lists.'));
            assert(root.textContent.includes('Links open current lists.'));
            assert.equal(root.querySelector('.col-packing-hints').querySelector('.deck-swatch'), null);
          }
          assert.equal(selected.querySelector('a').getAttribute('href'), deckHref('casual/saved', 'target'));
          assert.equal(words.querySelector('a').getAttribute('href'), deckHref('casual/saved', 'target'));
          const open = casualRows()[0].querySelector('.col-casual-open');
          assert.equal(open.querySelector('a'), null); assert(!open.textContent.includes('Saved deck'));
        """)

    def test_exact_versions_and_all_supported_route_kinds_are_preserved(self):
        self.run_js(r"""
          const ids = ['casual/planned', 'commander/play-now', 'user2/casual/personal',
            'product/fdn-beginner-box/cats', 'pairing/cats+vampires'];
          const versions = ['target', 'owned', 'owned', 'target', 'target'];
          const names = ids.map((id, i) => hint(id, versions[i], {title: 'Deck ' + i, quantity: 1}));
          const cv = drawHints(entry({held: 5, guess: false, listed_holders: names, unattributed: 0}),
            {rows: [{...rows[0], quantity: 8}], editable: false});
          for (const root of surfaces(cv).slice(1)) {
            const links = root.querySelector('.col-packing-hints').querySelectorAll('a');
            same(links.map(node => node.getAttribute('href')), ids.map((id, i) => deckHref(id, versions[i])));
            same(links.map(node => node.textContent), ['1 \u00d7 Deck 0 (Planned list)', '1 \u00d7 Deck 1 (Play-now list)',
              '1 \u00d7 Deck 2 (Play-now list)', '1 \u00d7 Deck 3 (Planned list)', '1 \u00d7 Deck 4 (Planned list)']);
            assert(!root.textContent.includes('without a named hint'));
            assert(!root.textContent.includes('Edit copies'));
          }
          assert(caption().querySelectorAll('a').at(-1).getAttribute('href').includes('cats%2Bvampires'));
        """)

    def test_attribution_is_keyed_to_the_exact_printing_and_finish(self):
        self.run_js(r"""
          const cv = drawHints();
          let [cell, selected, words] = surfaces(cv, 'fdn|1|foil');
          for (const root of [cell, selected, words]) {
            assert.equal(root.querySelector('.col-packing-hints'), null);
            assert.equal(root.querySelector('.col-packing-marker'), null);
            assert(!root.textContent.includes('Saved deck'));
          }
          [cell, selected, words] = surfaces(cv);
          assert(cell.querySelector('.col-packing-marker')); assert(selected.querySelector('a')); assert(words.querySelector('a'));
          assert.equal(cv.selectedKey, key); assert.equal(document.activeElement, tableRow(key).querySelector('.col-open'));
        """)

    def test_read_only_legacy_file_names_remain_valid_encoded_deck_links(self):
        self.run_js(r"""
          const ids = ['casual/Gruul_Ramp', 'user2/casual/Gruul Ramp & more'];
          const cv = drawHints(entry({listed_holders: ids.map(id => hint(id, 'owned', {quantity: 1}))}), {editable: false});
          for (const root of surfaces(cv).slice(1)) {
            same(root.querySelectorAll('a').map(node => node.getAttribute('href')), ids.map(id => deckHref(id, 'owned')));
            assert(!root.textContent.includes('Edit copies'));
          }
          assert(caption().querySelectorAll('a')[1].getAttribute('href').includes('Gruul%20Ramp%20%26%20more'));
        """)

    def test_old_missing_failed_and_anonymous_answers_never_recover_names_from_other_sources(self):
        self.run_js(r"""
          state.library = {decks: [{id: 'user2/casual/private', title: 'Private library title'}]};
          const old = {held: 3, guess: true, holders: [hint('user2/casual/private', 'owned', {title: 'Private old title'})]};
          const cases = [
            {storage: undefined}, {storage: {rows: {}, error: null}},
            {storage: {rows: {[key]: old}, error: null}},
            {storage: {rows: {[key]: entry({listed_holders: [], unattributed: 3})}, error: null}},
            {storage: {rows: {[key]: entry()}, error: 'Counts unavailable.'}},
            {storage: {rows: {[key]: entry({held: null, unattributed: null})}, error: null}},
            {space: undefined, storage: {rows: {[key]: entry()}, error: null}},
            {space: 'user2', storage: {rows: {[key]: entry()}, error: null}}
          ];
          for (const data of cases) {
            const cv = draw(data);
            for (const root of surfaces(cv)) {
              assert.equal(root.querySelector('.col-packing-hints'), null);
              assert.equal(root.querySelector('.col-packing-marker'), null);
              assert.equal(root.querySelector('a'), null);
              for (const hidden of ['Private library title', 'Private old title', 'user2/casual/private', 'Saved deck'])
                assert(!root.textContent.includes(hidden), hidden);
            }
          }
        """)

    def test_invalid_identity_quantity_version_or_checksum_rejects_all_names(self):
        self.run_js(r"""
          const bad = [
            {listed_holders: null}, {listed_holders: {}}, {listed_holders: [null]}, {listed_holders: [[]]},
            ...[null, '', '../private', '#/deck?id=private', 'javascript:alert(1)', 'casual/a/b', 'pairing/cats',
              'casual/..', 'casual/a\\b', 'casual/hidden\nname', 'product/../private', 'pairing/cats+..'].map(id =>
              ({listed_holders: [hint(id)]})),
            ...[null, '', '   ', 12, 'Hidden\nname'].map(title => ({listed_holders: [hint(undefined, undefined, {title})]})),
            ...[null, '', 'play-now', 'owned&v=target'].map(version => ({listed_holders: [hint(undefined, version)]})),
            ...[0, -1, 1.5, '2', Number.MAX_SAFE_INTEGER + 1].map(quantity =>
              ({listed_holders: [hint(undefined, undefined, {quantity})]})),
            ...[undefined, null, -1, 1.5, '1', 2].map(unattributed => ({unattributed})),
            {held: '3'}, {listed_holders: [hint(), hint()]},
            {listed_holders: [hint(), hint('casual/other', 'target', {quantity: 1, title: 'Other visible'})], unattributed: 1},
            {listed_holders: [hint(undefined, undefined, {quantity: 5})], held: 5, unattributed: 0}
          ];
          for (const value of bad) {
            const cv = drawHints(entry(value));
            for (const root of surfaces(cv)) {
              assert.equal(root.querySelector('.col-packing-hints'), null, JSON.stringify(value));
              assert.equal(root.querySelector('.col-packing-marker'), null, JSON.stringify(value));
              assert.equal(root.querySelector('a'), null, JSON.stringify(value));
              assert(!root.textContent.includes('Saved deck')); assert(!root.textContent.includes('Other visible'));
            }
          }
        """)

    def test_names_are_plain_text_and_rendering_does_not_read_or_change_records(self):
        self.run_js(r"""
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('hints must not read'); };
          apiWrite = async () => { writes++; throw new Error('hints must not write'); };
          const title = '<script>private()</script> & "cards"', saved = entry({listed_holders: [hint('casual/saved', 'owned', {title})]});
          const original = JSON.stringify({rows, saved}), cv = drawHints(saved, {editable: false});
          const roots = surfaces(cv);
          for (const root of roots.slice(1)) {
            assert(root.textContent.includes(title)); assert.equal(root.querySelector('script'), null);
            assert.equal(root.querySelector('a').getAttribute('href'), deckHref('casual/saved', 'owned'));
          }
          main.querySelector('.col-th-price').querySelector('button').click();
          assert.equal(JSON.stringify({rows: cv.rows, saved}), original); assert.equal(cv.sha256, 's1');
          assert.equal(reads, 0); assert.equal(writes, 0); assert.equal(changes, 0);
        """)

    def test_save_and_conflict_answers_replace_hints_without_merging_old_names(self):
        self.run_js(r"""
          const cv = drawHints(); colSelectRow(cv, key);
          colChanged(cv, {sha256: 's2', rows, storage: {rows: {[key]: entry({listed_holders:
            [hint('casual/latest', 'owned', {title: 'Latest saved deck'})]})}, error: null}}, '');
          for (const root of surfaces(cv).slice(1)) {
            assert(root.textContent.includes('Latest saved deck')); assert(!root.textContent.includes('Saved deck'));
            assert.equal(root.querySelector('a').getAttribute('href'), deckHref('casual/latest', 'owned'));
          }
          colTakeRows(cv, {rows, storage: {rows: {[key]: {held: 3, guess: true}}, error: null}});
          drawColRowList(cv);
          for (const root of surfaces(cv)) {
            assert.equal(root.querySelector('a'), null); assert(!root.textContent.includes('Latest saved deck'));
            assert.equal(root.querySelector('.col-packing-marker'), null);
          }
        """)

    def test_older_save_same_hash_and_conflict_answers_clear_only_retained_hint_metadata(self):
        self.run_js(r"""
          for (const action of ['save', 'same hash', 'conflict']) {
            const originalStorage = {rows: {[key]: entry()}, error: null}, original = JSON.stringify(originalStorage);
            const cv = draw({storage: originalStorage, editable: false}), previousRows = cv.rows, previousPrices = cv.prices;
            colSelectRow(cv, key); assert(preview().querySelector('.col-packing-hints'));
            if (action === 'save') colChanged(cv, {sha256: 's2', rows: [...rows]}, '');
            if (action === 'same hash') colChanged(cv, {sha256: 's1'}, '');
            if (action === 'conflict') { cv.sha256 = 's2'; colTakeRows(cv, {rows: [...rows]}); drawColRowList(cv); }
            assert.equal(cv.storage.rows[key].held, 3); assert.equal(cv.storage.rows[key].guess, true);
            assert.equal(cv.storage.rows[key].listed_holders, undefined); assert.equal(cv.storage.rows[key].unattributed, undefined);
            assert.notEqual(cv.storage.rows, originalStorage.rows); assert.notEqual(cv.storage.rows[key], originalStorage.rows[key]);
            assert.equal(cv.prices, previousPrices); assert.equal(JSON.stringify(originalStorage), original);
            if (action === 'same hash') assert.equal(cv.rows, previousRows);
            for (const root of surfaces(cv)) {
              assert.equal(root.querySelector('.col-packing-hints'), null);
              assert.equal(root.querySelector('.col-packing-marker'), null); assert.equal(root.querySelector('a'), null);
              assert(!root.textContent.includes('Saved deck')); assert(!root.textContent.includes('Edit copies'));
            }
            colChanged(cv, {sha256: 's3', rows, storage: originalStorage}, '');
            assert(preview().querySelector('.col-packing-hints')); assert(preview().querySelector('a'));
          }
        """)

    def test_older_inactive_refresh_clears_retained_hints_without_updating_the_page_or_following_old_links(self):
        self.run_js(r"""
          const originalStorage = {rows: {[key]: entry()}, error: null}, original = JSON.stringify(originalStorage);
          const cv = draw({storage: originalStorage}), words = mountedCaption(), link = words.querySelector('a');
          let called = 0; colAfterViewer = () => { called++; };
          state.profile = PROFILES[2];
          const currentPage = main.textContent;
          colChanged(cv, {sha256: 's2', rows: [...rows]}, '');
          assert.equal(main.textContent, currentPage); assert.equal(cv.storage.rows[key].listed_holders, undefined);
          assert.equal(cv.storage.rows[key].held, 3); assert.equal(cv.storage.rows[key].guess, true);
          assert.equal(JSON.stringify(originalStorage), original); link.click(); assert.equal(called, 0);
          words.remove();
        """)

    def test_link_enter_remains_native_and_viewer_close_returns_to_the_same_row_trigger(self):
        self.run_js(r"""
          const cv = drawHints(); colSelectRow(cv, key);
          const target = preview().querySelector('a'); target.focus();
          assert.equal(document.activeElement, target);
          const region = main.querySelector('.col-row-lab').querySelector('.table-wrap');
          assert(!region.fire('keydown', {key: 'Enter', target}).defaultPrevented);
          const trigger = casualRows()[0].querySelector('.col-casual-open'); trigger.click();
          assert.equal(inspections[0].trigger, trigger); assert(trigger.isConnected);
          const words = mountedCaption(); assert.equal(trigger.querySelector('a'), null);
          assert(!trigger.contains(words));
          viewerDom = {track: el('div'), slides: []}; viewerState = {history: false, trigger};
          words.querySelector('a').focus(); viewerClosed();
          assert.equal(document.activeElement, trigger); assert.equal(trigger.isConnected, true);
          words.remove();
        """)

    def test_lab_enter_viewer_exposes_exact_version_hints_from_a_fresh_trigger_with_close_focus(self):
        self.run_js(r"""
          const cv = drawHints(entry({listed_holders: [hint('casual/saved', 'owned')]}));
          colSelectRow(cv, key);
          const before = tableRow(key).querySelector('.col-open');
          const region = main.querySelector('.col-row-lab').querySelector('.table-wrap');
          assert(region.fire('keydown', {key: 'Enter', target: before}).defaultPrevented);
          assert.equal(inspections.length, 1);
          const trigger = inspections[0].trigger;
          assert(trigger.isConnected); assert.notEqual(trigger, before);
          assert.equal(trigger.getAttribute('data-viewer'), 'collection-lab-rows');
          const group = viewerGroup(trigger), words = group.items[group.index].caption;
          assert(words.textContent.includes('Saved packing-list hints:'));
          assert(words.textContent.includes('Play-now list')); assert(words.textContent.includes('may differ from the boxes and current deck lists'));
          const link = words.querySelector('a'); assert.equal(link.getAttribute('href'), deckHref('casual/saved', 'owned'));
          document.body.append(words);
          let afterClose; colAfterViewer = go => { afterClose = go; };
          const previous = location.hash; link.click(); assert(afterClose); assert.equal(location.hash, previous);
          viewerDom = {track: el('div'), slides: []}; viewerState = {history: false, trigger};
          link.focus(); viewerClosed(); assert.equal(document.activeElement, trigger);
          afterClose(); assert.equal(location.hash, deckHref('casual/saved', 'owned'));
          const latest = location.hash; afterClose = null; link.click(); assert(afterClose);
          cv.storage.rows[key].listed_holders[0].version = 'target';
          afterClose(); assert.equal(location.hash, latest, 'retained lab links recheck the current hint after close');
          const thumbnail = tableRow(key).querySelector('.col-thumb');
          assert.equal(typeof viewerGroup(thumbnail).items[0].caption, 'string');
          const noHints = draw(); colSelectRow(noHints, key);
          assert.equal(typeof viewerGroup(tableRow(key).querySelector('.col-open')).items[0].caption, 'string');
          words.remove();
        """)

    def test_invalid_canonical_row_quantity_keeps_named_hints_anonymous(self):
        self.run_js(r"""
          for (const quantity of [undefined, 'not a count', -1, 1.5, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
            const cv = drawHints(entry(), {rows: [{...rows[0], quantity}]});
            for (const root of surfaces(cv)) {
              assert.equal(root.querySelector('.col-packing-marker'), null);
              assert.equal(root.querySelector('.col-packing-hints'), null);
              assert.equal(root.querySelector('a'), null); assert(!root.textContent.includes('Saved deck'));
            }
            const open = tableRow(key).querySelector('.col-open');
            assert.equal(typeof viewerGroup(open).items[0].caption, 'string');
          }
        """)

    def test_caption_link_closes_the_viewer_before_using_the_exact_current_list_route(self):
        self.run_js(r"""
          drawHints(entry({listed_holders: [hint('casual/saved', 'owned')]}), {editable: false});
          const words = mountedCaption(), link = words.querySelector('a'), before = location.hash;
          let afterClose; colAfterViewer = go => { afterClose = go; };
          assert(link.fire('click').defaultPrevented); assert(afterClose); assert.equal(location.hash, before);
          afterClose(); assert.equal(location.hash, deckHref('casual/saved', 'owned'));
          words.remove();
        """)

    def test_links_reject_stale_profile_route_detached_row_or_replaced_attribution(self):
        self.run_js(r"""
          const changes = ['profile', 'route', 'detach', 'hint', 'error', 'row'];
          for (const change of changes) {
            const cv = drawHints(), words = mountedCaption(), link = words.querySelector('a');
            let afterClose; colAfterViewer = go => { afterClose = go; };
            const before = location.hash; link.click(); assert(afterClose, change);
            if (change === 'profile') state.profile = PROFILES[2];
            if (change === 'route') routeToken++;
            if (change === 'detach') cv.root.remove();
            if (change === 'hint') cv.storage.rows[key].listed_holders[0].id = 'casual/replaced';
            if (change === 'error') cv.storage.error = 'Unavailable';
            if (change === 'row') cv.rows = cv.rows.filter(row => colKey(row) !== key);
            afterClose(); assert.equal(location.hash, before, change);
            afterClose = null; link.click(); assert.equal(afterClose, null, change);
            words.remove();
          }
          const cv = drawHints(), words = mountedCaption(), link = words.querySelector('a'); words.remove();
          let called = 0; colAfterViewer = () => { called++; }; link.click(); assert.equal(called, 0);
        """)


class CollectionHintsLayoutTests(unittest.TestCase):
    def test_hint_names_wrap_and_reuse_the_existing_link_target_floor(self):
        css = (WEB / "collection.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.col-packing-hints\s*\{[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;")
        self.assertRegex(css, r"\.col-packing-hints a\s*\{[^}]*max-width:\s*100%;[^}]*white-space:\s*normal;[^}]*overflow-wrap:\s*anywhere;")
        self.assertRegex(css, r"\.col-viewer-decks a\s*\{[^}]*min-height:\s*var\(--tap\)")
        self.assertRegex(css, r"\.col-packing-marker\s*\{[^}]*display:\s*block;[^}]*font-size:\s*var\(--fs-meta\)")
