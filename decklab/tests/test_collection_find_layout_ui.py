"""Find cards' casual rows and lab tiles over the shared DOM/API double.

Loads the complete real script order. No browser, server or inventory writes.
"""
import json
import re
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_device_layout_ui import _matches
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = SETUP + r"""
  // The runner exposes window.matchMedia; browsers also expose its global alias.
  globalThis.matchMedia = query => window.matchMedia(query);
  const picture = (name, extra = {}) => ({name, type_line: 'Creature - Elf', mana_cost: '{G}', cmc: 1,
    oracle_text: '', colors: ['R'], color_identity: ['U', 'G'], img: '/img/fdn/1/normal',
    img_small: '/img/fdn/1/small', ...extra});
  const record = (name, extra = {}) => ({name, owned: 4, incoming: 2, held: 1, free_now: 3, basic: false,
    holders: [{id: 'casual/a', title: 'Visible deck', quantity: 1}], card: picture(name), ...extra});
  const found = [
    record('Alpha'),
    record('Incoming only', {owned: 0, incoming: 2, held: 0, free_now: 0, holders: [],
      card: picture('Incoming only', {img: null, img_small: null})}),
    record('All held', {owned: 2, incoming: 0, held: 2, free_now: 0,
      holders: [{id: 'casual/a', title: 'Visible deck', quantity: 2}]}),
    record('Forest', {owned: 3, incoming: 0, basic: true, held: null, free_now: null, holders: [],
      card: picture('Forest', {colors: [], color_identity: ['G'], type_line: 'Basic Land - Forest'})}),
    record('Unmatched name', {owned: 1, incoming: 1, held: null, free_now: null, holders: [], card: null}),
    record('Unknown counts', {owned: 3, incoming: 0, held: null, free_now: null, holders: []}),
    record('Colourless', {incoming: 0, card: picture('Colourless', {colors: [], color_identity: []})}),
    record('Identity unknown', {incoming: 0, card: picture('Identity unknown', {color_identity: undefined})})
  ];
  const answer = (cards = found, extra = {}) => ({space: 'home', editable: true, types: ['Creature', 'Land'],
    roles: ['ramp'], cards, total: cards.length, page: 1, pages: 1, warnings: [], note: '', ...extra});
  const drawFind = (data = {}, query = '', space = 'home') => {
    as('matt', MAY.admin);
    return drawCollection(answer(found, {space, ...data}), new URLSearchParams(query), space);
  };
  const casualRows = () => main.querySelectorAll('.col-find-row');
  const opener = index => casualRows()[index].querySelector('.col-find-open');
  const captionFor = node => { const group = viewerGroup(node); assert(group); return group.items[group.index].caption; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CollectionFindLayoutUiTests(unittest.TestCase):
    def run_js(self, scenario):
        done = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                              capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "ok")

    def test_casual_cards_form_a_semantic_list_and_keep_the_lab_tile_grid(self):
        self.run_js(r"""
          const before = JSON.stringify(found), cv = drawFind();
          const list = main.querySelector('.col-find-rows'), lab = main.querySelector('.col-find-lab');
          assert.equal(list.tag, 'ul'); assert.equal(list.querySelector('table'), null);
          assert.equal(casualRows().length, found.length);
          assert(casualRows().every(node => node.tag === 'li' && !['row', 'cell'].includes(node.getAttribute('role'))));
          assert(lab); const grid = lab.querySelector('.col-tiles');
          assert(grid.getAttribute('class').split(/\s+/).includes('card-tiles'));
          assert.equal(grid.querySelectorAll('.card-tile').length, found.length);
          assert.equal(main.querySelector('.col-table'), null);
          assert.equal(main.querySelector('.col-row-layout'), null);
          assert.equal(JSON.stringify(found), before); assert.equal(cv.kind, 'find');
          const image = opener(0).querySelector('img');
          assert(image); assert.equal(image.getAttribute('alt'), '');
          assert.equal(image.getAttribute('loading'), 'lazy');
          assert(opener(0).getAttribute('aria-label').includes('Alpha'));
          assert(opener(0).getAttribute('aria-label').length < 180);
        """)

    def test_full_availability_facts_do_not_invent_basic_or_unknown_counts_or_prices(self):
        self.run_js(r"""
          drawFind({prices: {rows: {'fdn|1|nonfoil': {aud: 123.45}}}});
          const words = casualRows().map(node => node.textContent);
          for (const fact of ['4 owned', '3 free', '2 on the way', '1 in decks']) assert(words[0].includes(fact), fact);
          assert(/(?:0 owned|None owned yet)/.test(words[1])); assert(words[1].includes('2 on the way'));
          assert(words[2].includes('all in decks')); assert(!words[2].includes('2 in decks'));
          assert(words[3].includes('3 owned')); assert(/not tracked/i.test(words[3]));
          assert(!/0 free|0 in decks|3 free/i.test(words[3]));
          assert(words[4].includes('Name not matched')); assert(words[4].includes('1 owned'));
          assert(words[4].includes('1 on the way')); assert(!/0 free|0 in decks/i.test(words[4]));
          assert(words[5].includes('3 owned')); assert(!/0 free|0 in decks|3 free/i.test(words[5]));
          for (const text of words) assert(!/123[.]45|A\$|No price|\$0[.]00/.test(text));
        """)

    def test_held_count_is_only_omitted_when_the_free_summary_already_says_all_in_decks(self):
        self.run_js(r"""
          drawFind({cards: [
            record('All held', {owned: 2, incoming: 1, held: 2, free_now: 0}),
            record('Part held', {owned: 4, incoming: 2, held: 1, free_now: 3}),
            record('Free unknown', {owned: 4, incoming: 2, held: 2, free_now: null}),
            record('Overallocated', {owned: 2, incoming: 0, held: 3, free_now: 0})
          ]});
          same(casualRows().map(node => node.querySelector('.col-find-meta').textContent), [
            '2 owned \u00b7 all in decks \u00b7 1 on the way',
            '4 owned \u00b7 3 free \u00b7 2 on the way \u00b7 1 in decks',
            '4 owned \u00b7 2 on the way \u00b7 2 in decks',
            '2 owned \u00b7 all in decks \u00b7 3 in decks'
          ]);
        """)

    def test_identity_pips_use_loaded_identity_and_keep_unknown_distinct_from_colourless(self):
        self.run_js(r"""
          drawFind();
          const multi = casualRows()[0].querySelector('.id-pips'); assert(multi);
          same(multi.querySelectorAll('.id-pip').map(node => node.textContent), ['U', 'G']);
          assert.equal(multi.getAttribute('role'), 'img');
          assert(/blue/.test(multi.getAttribute('aria-label'))); assert(/green/.test(multi.getAttribute('aria-label')));
          assert(!/red/.test(multi.getAttribute('aria-label')));
          const colourless = casualRows()[6].querySelector('.id-pips');
          same(colourless.querySelectorAll('.id-pip').map(node => node.textContent), ['C']);
          assert(/Colourless/.test(colourless.getAttribute('aria-label')));
          assert.equal(casualRows()[4].querySelector('.id-pips'), null);
          assert.equal(casualRows()[7].querySelector('.id-pips'), null);
          const tiles = main.querySelector('.col-find-lab').querySelectorAll('.card-tile');
          same(tiles[0].querySelector('.id-pips').querySelectorAll('.id-pip').map(node => node.textContent), ['U', 'G']);
          assert(tiles[0].querySelector('.id-pips').getAttribute('class').includes('id-pips-sm'));
          assert(multi.getAttribute('class').includes('id-pips-md'));
        """)

    def test_known_cards_with_and_without_images_open_the_read_only_viewer(self):
        self.run_js(r"""
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('rendering must not fetch'); };
          apiWrite = async () => { writes++; throw new Error('finding must not write'); };
          drawFind({editable: false});
          for (const index of [0, 1]) {
            const open = opener(index); assert.equal(open.tag, 'button');
            assert.equal(open.getAttribute('aria-haspopup'), 'dialog');
            open.click(); assert.equal(inspections.at(-1).card.name, found[index].name);
            assert.equal(inspections.at(-1).trigger, open);
            assert(!captionFor(open).textContent.includes('Edit copies'));
          }
          assert.equal(opener(1).querySelector('img'), null);
          const unknown = opener(4); assert.equal(unknown.tag, 'div');
          assert.equal(unknown.getAttribute('data-viewer'), null);
          assert.equal(casualRows()[4].querySelector('button'), null);
          assert.equal(reads, 0); assert.equal(writes, 0); assert.equal(changes, 0);
        """)

    def test_casual_viewer_navigation_and_captions_share_the_existing_copy_action(self):
        self.run_js(r"""
          const cv = drawFind(), open = opener(0), group = viewerGroup(open), opened = [];
          assert(group); assert.notEqual(open.getAttribute('data-viewer'), 'collection');
          same(group.items.map(item => item.card.name), found.filter(row => row.card).map(row => row.card.name));
          const caption = captionFor(open);
          for (const text of ['4 owned', '3 free now', '2 on the way', '1 in ', 'Visible deck']) assert(caption.textContent.includes(text), text);
          assert.equal(caption.querySelector('a').getAttribute('href'), deckHref('casual/a'));
          assert.equal(caption.textContent, colFindCaption(cv, found[0]).textContent);
          const lab = main.querySelector('.col-find-lab').querySelector('.card-tile-open');
          assert.equal(captionFor(lab).textContent, caption.textContent);
          openCopiesSheet = (view, name) => opened.push([view, name]);
          caption.querySelector('.col-viewer-edit').click();
          assert.equal(opened.length, 1); assert.equal(opened[0][0], cv); assert.equal(opened[0][1], 'Alpha');
          assert.equal(captionFor(opener(1)).querySelector('.col-viewer-edit'), null);
          assert(/which deck uses it isn't tracked/.test(captionFor(opener(3)).textContent));
          assert.equal(opener(4).tag, 'button'); opener(4).click();
          assert.equal(opened.length, 2); assert.equal(opened[1][1], 'Unmatched name');
          assert.equal(changes, 0);
        """)

    def test_matched_card_without_type_keeps_its_viewer_and_does_not_warn_about_its_name(self):
        self.run_js(r"""
          const known = record('Matched without type', {card: picture('Matched without type', {type_line: ''})});
          drawFind({cards: [known], editable: false});
          const item = casualRows()[0], open = opener(0);
          assert(item.textContent.includes('Type not recorded'));
          assert(!item.textContent.includes('Name not matched'));
          assert.equal(open.tag, 'button'); assert.equal(open.getAttribute('aria-haspopup'), 'dialog');
          open.click(); assert.equal(inspections.length, 1); assert.equal(inspections[0].card.name, known.name);
          assert.equal(inspections[0].trigger, open);
          assert.equal(captionFor(open).querySelector('.col-viewer-edit'), null);
          assert.equal(button(main, 'Add card'), null); assert.equal(changes, 0);
        """)

    def test_existing_edit_and_active_page_guards_apply_to_casual_actions(self):
        self.run_js(r"""
          const cv = drawFind(), known = opener(0), unknown = opener(4), edit = captionFor(known).querySelector('.col-viewer-edit');
          let reads = 0, writes = 0;
          api = async () => { reads++; throw new Error('blocked edit must not read'); };
          apiWrite = async () => { writes++; throw new Error('blocked edit must not write'); };
          cv.busy = true; unknown.click(); edit.click(); assert.equal(colSheets.size, 0);
          cv.busy = false; cv.editable = false; unknown.click(); edit.click(); assert.equal(colSheets.size, 0);
          cv.editable = true; state.profile = PROFILES.find(profile => profile.id === 'user2');
          known.click(); unknown.click(); edit.click(); assert.equal(colSheets.size, 0); assert.equal(inspections.length, 0);
          state.profile = PROFILES[0]; routeToken++;
          known.click(); unknown.click(); edit.click(); assert.equal(colSheets.size, 0); assert.equal(inspections.length, 0);
          cv.token = routeToken; cv.root.remove();
          known.click(); unknown.click(); edit.click(); assert.equal(colSheets.size, 0); assert.equal(inspections.length, 0);
          assert.equal(reads, 0); assert.equal(writes, 0); assert.equal(changes, 0);
        """)

    def test_filters_keep_query_keys_replace_history_reset_page_and_update_active_count(self):
        self.run_js(r"""
          const cv = drawFind({}, 'q=elf&color=G&type=Creature&role=ramp&mv=2&availability=held&page=3', 'user2');
          const paths = [], replaced = [];
          api = path => { paths.push(path); return new Promise(() => {}); };
          history.replaceState = (saved, title, hash) => replaced.push(hash);
          same(COL_FILTER_KEYS, ['q', 'color', 'type', 'role', 'mv', 'availability', 'page']);
          const search = main.querySelector('#collection-q'), mv = main.querySelector('#collection-mv');
          const form = main.querySelector('.col-filters'), extra = main.querySelector('#col-filter-extra');
          assert(form.contains(search)); assert(form.contains(extra));
          assert.equal(form.fire('submit').defaultPrevented, true);
          // Match the browser return value omitted by the shared classList double.
          const changeClass = form.classList.toggle;
          form.classList.toggle = (name, force) => { changeClass(name, force); return form.classList.contains(name); };
          const toggle = cv.filterToggle; assert(toggle); assert.equal(cv.filterCount.textContent, '4');
          assert(toggle.getAttribute('aria-label').includes('4 active'));
          assert.equal(toggle.getAttribute('aria-controls'), extra.id);
          toggle.click(); assert.equal(toggle.getAttribute('aria-expanded'), 'true');
          toggle.click(); assert.equal(toggle.getAttribute('aria-expanded'), 'false');
          const colour = main.querySelector('#collection-color');
          assert(colour.closest('label').textContent.includes('Card colour'));
          colour.value = ''; colour.fire('change');
          assert.equal(cv.filterCount.textContent, '3'); assert(toggle.getAttribute('aria-label').includes('3 active'));
          const query = new URLSearchParams(paths.at(-1).split('?')[1]);
          same([query.get('q'), query.get('color'), query.get('type'), query.get('role'), query.get('mv'),
            query.get('availability'), query.get('page'), query.get('space'), query.get('limit')],
            ['elf', null, 'Creature', 'ramp', '2', 'held', null, 'user2', '24']);
          assert.equal(replaced.length, 1); assert(replaced[0].startsWith('#/collection?'));
          assert.equal(new URLSearchParams(replaced[0].split('?')[1]).get('space'), 'user2');
          // Each typed filter has its own debounce, and Enter commits the trimmed search.
          search.value = '  new query  '; search.fire('input'); mv.value = '4'; mv.fire('input'); flushTimers();
          assert.equal(cv.query.get('q'), 'new query'); assert.equal(cv.query.get('mv'), '4');
          search.value = 'exact'; search.fire('input'); search.fire('keydown', {key: 'Enter'});
          assert.equal(cv.query.get('q'), 'exact'); const count = paths.length; flushTimers(); assert.equal(paths.length, count);
          const availability = main.querySelector('[aria-label=Show]');
          assert(availability.classList.contains('col-availability'));
          same(availability.querySelectorAll('button').map(node => node.dataset.value), ['all', 'free', 'incoming', 'held']);
          for (const [index, value] of ['all', 'free', 'incoming', 'held'].entries()) {
            const choice = availability.querySelectorAll('button')[index]; choice.click();
            assert.equal(cv.query.get('availability'), value === 'all' ? null : value);
            assert.equal(choice.getAttribute('aria-pressed'), 'true');
          }
          for (const key of ['type', 'role']) { const node = main.querySelector('#collection-' + key); node.value = ''; node.fire('change'); }
          mv.value = ''; mv.fire('input'); flushTimers();
          assert.equal(cv.filterCount.textContent, ''); assert.equal(cv.filterCount.hidden, true);
          assert.equal(toggle.getAttribute('aria-label'), 'Filter cards');
          assert.equal(main.querySelector('#collection-q'), search);
        """)

    def test_card_colour_predicate_is_sent_unchanged_while_identity_pips_still_show_green(self):
        self.run_js(r"""
          const colourlessCard = record('Green identity', {card: picture('Green identity', {colors: [], color_identity: ['G']})});
          const cv = drawFind({cards: [colourlessCard]}, 'color=C'), paths = [];
          api = async path => { paths.push(path); return answer([colourlessCard]); };
          await colLoadFind(cv, new URLSearchParams('color=C'), false);
          const query = new URLSearchParams(paths[0].split('?')[1]);
          assert.equal(query.get('color'), 'C'); assert.equal(query.get('colors'), null);
          assert.equal(query.get('color_identity'), null); assert.equal(cv.query.get('color'), 'C');
          same(casualRows()[0].querySelector('.id-pips').querySelectorAll('.id-pip').map(node => node.textContent), ['G']);
          assert.equal(main.querySelector('#collection-color').value, 'C');
        """)

    def test_paging_uses_existing_sizes_and_normalizes_server_page_without_new_history(self):
        self.run_js(r"""
          const cv = drawFind({page: 1, pages: 5}, '', 'user2'), paths = [], replaced = [];
          history.replaceState = (saved, title, hash) => replaced.push(hash);
          window.matchMedia('(min-width: 1000px)').matches = true;
          assert.equal(colPageSize(), 48);
          api = async path => { paths.push(path); return answer([found[0]], {page: 2, pages: 2, space: 'user2'}); };
          await colLoadFind(cv, new URLSearchParams('q=elf&page=99'), true);
          const query = new URLSearchParams(paths[0].split('?')[1]);
          same([query.get('q'), query.get('page'), query.get('space'), query.get('limit')], ['elf', '99', 'user2', '48']);
          assert.equal(cv.query.get('page'), '2'); assert.equal(replaced.length, 2);
          assert.equal(new URLSearchParams(replaced[1].split('?')[1]).get('page'), '2');
          assert.equal(cv.results.scrolled, 1); assert.equal(cv.results.getAttribute('aria-busy'), null);
          const nav = cv.results.querySelectorAll('.col-pager'); assert.equal(nav.length, 2);
          assert.equal(nav[0].getAttribute('aria-label'), 'Pages, top');
          assert.equal(nav[1].getAttribute('aria-label'), 'Pages, bottom');
          assert(cv.results.querySelector('.result-count').textContent.includes('match'));
          window.matchMedia('(min-width: 1000px)').matches = false; assert.equal(colPageSize(), 24);
        """)

    def test_out_of_order_route_and_profile_responses_cannot_replace_current_results(self):
        self.run_js(r"""
          const cv = drawFind(), pending = [];
          api = path => new Promise(resolve => pending.push({path, resolve}));
          const older = colLoadFind(cv, new URLSearchParams('q=old'), false);
          const newer = colLoadFind(cv, new URLSearchParams('q=new'), false);
          pending[1].resolve(answer([record('Latest')])); await newer;
          assert(casualRows()[0].textContent.includes('Latest'));
          pending[0].resolve(answer([record('Obsolete')])); await older;
          assert(casualRows()[0].textContent.includes('Latest')); assert(!cv.results.textContent.includes('Obsolete'));
          assert.equal(cv.results.getAttribute('aria-busy'), null);
          const staleRoute = colLoadFind(cv, new URLSearchParams('q=route'), false);
          routeToken++; pending[2].resolve(answer([record('Old route')])); await staleRoute;
          assert(!cv.results.textContent.includes('Old route'));
          const current = drawFind(), changedProfile = colLoadFind(current, new URLSearchParams('q=profile'), false);
          state.profile = PROFILES.find(profile => profile.id === 'user2');
          pending[3].resolve(answer([record('Old profile')])); await changedProfile;
          assert(!current.results.textContent.includes('Old profile'));
          const disconnected = drawFind(), removed = colLoadFind(disconnected, new URLSearchParams('q=removed'), false);
          disconnected.root.remove(); pending[4].resolve(answer([record('Removed page')])); await removed;
          assert(!disconnected.results.textContent.includes('Removed page'));
        """)

    def test_empty_results_preserve_clear_filters_and_first_page_actions(self):
        self.run_js(r"""
          const filtered = drawFind({cards: [], total: 0}, 'q=nothing', 'user2');
          assert(filtered.results.textContent.includes('No cards match these filters.'));
          assert.equal(filtered.results.querySelector('.col-find-rows'), null);
          const clearFilters = filtered.results.querySelector('a');
          assert.equal(clearFilters.textContent, 'Clear the filters'); assert.equal(clearFilters.getAttribute('href'), colHash('user2', 'find'));
          const beyond = drawFind({cards: [], total: 8}, 'page=9'), asked = [];
          api = path => { asked.push(path); return new Promise(() => {}); };
          button(beyond.results, 'Go to the first page').click();
          assert.equal(new URLSearchParams(asked[0].split('?')[1]).get('page'), null);
          drawFind({cards: [], total: 0, editable: false});
          assert(main.textContent.includes('No cards recorded yet.')); assert.equal(button(main, 'Add card'), null);
        """)


def _declarations_at(css, selector, width):
    """Apply exact-selector declarations in source order, including matching media blocks.

    These checks cover page layout rules; they don't emulate browser rendering or
    selector specificity. Container and forced-colour rules are outside this fixture.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    device = {"width": width, "height": 1000, "pointer": "coarse" if width < 1000 else "fine",
              "hover": "none" if width < 1000 else "hover"}

    def rules(text):
        cursor = 0
        while (start := text.find("{", cursor)) >= 0:
            header, depth, end = text[cursor:start].strip(), 1, start + 1
            while depth and end < len(text):
                depth += (text[end] == "{") - (text[end] == "}")
                end += 1
            if depth:
                raise AssertionError("Unclosed CSS rule")
            body = text[start + 1:end - 1]
            if header.startswith("@media"):
                query = header.removeprefix("@media").strip()
                if "forced-colors" not in query and "prefers-" not in query and _matches(query, device):
                    yield from rules(body)
            elif not header.startswith("@"):
                yield header, body
            cursor = end

    values = {}
    for selectors, body in rules(css):
        if selector in [item.strip() for item in selectors.split(",")]:
            values.update({name: value.strip() for name, value in
                           re.findall(r"([\w-]+)\s*:\s*([^;]+)(?:;|$)", body)})
    return values


class CollectionFindDensityTests(unittest.TestCase):
    def setUp(self):
        self.css = (WEB / "collection.css").read_text(encoding="utf-8")

    def style(self, selector, width):
        return _declarations_at(self.css, selector, width)

    def test_casual_widths_keep_rows_sticky_search_and_folded_extra_filters(self):
        for width in [393, 820, 852, 900, 999]:
            with self.subTest(width=width):
                self.assertEqual(self.style(".col-find-lab", width)["display"], "none")
                self.assertEqual(self.style(".col-find-casual", width).get("display", "block"), "block")
                form = self.style(".col-filters", width)
                self.assertEqual(form["position"], "sticky")
                self.assertEqual(form["top"], "var(--shell-top)")
                self.assertEqual(self.style(".col-filter-q input", width)["min-height"], "48px")
                toggle = self.style(".col-filter-toggle", width)
                self.assertNotEqual(toggle.get("display"), "none")
                self.assertEqual((toggle["width"], toggle["height"]), ("50px", "50px"))
                self.assertEqual(self.style(".col-filter-extra", width)["display"], "none")
                self.assertEqual(self.style(".col-filters.is-open .col-filter-extra", width)["display"], "grid")
                self.assertEqual(self.style(".col-find-colour-note", width)["display"], "none")
                self.assertEqual(self.style(".col-filters.is-open .col-find-colour-note", width)["display"], "block")

    def test_lab_widths_show_original_tiles_and_all_filters_at_normal_density(self):
        for width in [1000, 1180, 1470, 2560]:
            with self.subTest(width=width):
                self.assertEqual(self.style(".col-find-lab", width)["display"], "block")
                self.assertEqual(self.style(".col-find-casual", width)["display"], "none")
                self.assertEqual(self.style(".col-filters", width)["position"], "static")
                self.assertEqual(self.style(".col-filter-toggle", width)["display"], "none")
                self.assertEqual(self.style(".col-filter-extra", width)["display"], "grid")
                self.assertEqual(self.style(".col-filter-q input", width)["min-height"], "var(--input-h)")
                self.assertEqual(self.style(".col-find-colour-note", width)["display"], "block")

    def test_row_geometry_keeps_56px_art_count_and_wrappable_names(self):
        row = self.style(".col-find-open", 393)
        self.assertEqual(row["grid-template-columns"], "56px minmax(0, 1fr) auto")
        self.assertEqual(row["min-height"], "var(--tap)")
        art = self.style(".col-find-picture", 393)
        self.assertEqual((art["width"], art["height"]), ("56px", "78px"))
        self.assertEqual(self.style(".col-find-name", 393)["overflow-wrap"], "anywhere")
        count = self.style(".col-find-count", 393)
        self.assertEqual(count["grid-column"], "3")
        self.assertEqual(count["white-space"], "nowrap")
        self.assertEqual(count["font-variant-numeric"], "tabular-nums")

    def test_availability_stays_horizontal_with_nonshrinking_choices(self):
        for width in [393, 820, 999, 1180]:
            with self.subTest(width=width):
                group = self.style(".col-availability", width)
                self.assertEqual(group["overflow-x"], "auto")
                self.assertEqual(group.get("flex-wrap"), "nowrap")
                choice = self.style(".col-availability > button", width)
                self.assertEqual(choice["white-space"], "nowrap")
                self.assertTrue(choice.get("flex") == "none" or choice.get("flex-shrink") == "0")
