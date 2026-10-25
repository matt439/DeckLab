"""The deck page (WP7 of decklab/UI-REVIEW.md) in its real script order over the event/DOM double: its tabs and
address, the availability banner, the Cards tab's marks and filters, the Overview, the Matchups tab's one row
per opponent, the stats' verdict strip and the play guide's symbols. No network, no writes."""
import json
import subprocess
import unittest
from decklab.tests.test_workspace_ui import NODE, WEB, RUNNER

# A small deck as /api/deck answers it, for a viewer who sees the collection.
PAGE = """
  const card = (name, type, cmc, ci = ['G']) => ({name, type_line: type, cmc, mana_cost: '{G}', color_identity: ci,
    oracle_text: '', img: '/img/fdn/1/normal', img_small: '/img/fdn/1/small'});
  const elf = card('Elf', 'Creature — Elf', 1), bolt = card('Bolt', 'Instant', 1, ['R']), forest = card('Forest', 'Basic Land — Forest', 0);
  const row = (name, need, missing, coming = [], held = []) => ({name, need, missing, owned: need - missing,
    available: need - missing, on_the_way: 0, on_the_way_from: coming, in_use_elsewhere: held, aud_each: 1.25,
    labels: {on_the_way: coming, in_use: held}});
  const makePage = () => ({
    summary: {id: 'casual/test', space: 'home', title: 'Test Deck', kind: 'casual', format: 'Casual 60-card, 1v1',
      player: 'user', status: 'building', read_only: false, card_count: 29, sideboard_count: 0,
      versions: ['target', 'owned'], kit: null},
    version: 'target', versions: ['target', 'owned'],
    sections: {Deck: [
      {qty: 4, name: 'Elf', set: 'fdn', number: '1', finish: 'nonfoil', card: elf},
      {qty: 2, name: 'Elf', set: 'm21', number: '2', finish: 'foil', card: elf},
      {qty: 3, name: 'Bolt', set: 'fdn', number: '3', finish: 'nonfoil', card: bolt},
      {qty: 20, name: 'Forest', set: null, number: null, finish: 'nonfoil', card: forest}]},
    stats: null, practice: null, guide: {sections: []}, warnings: [], info: [],
    owned: {rows: [row('Elf', 6, 0, [['order 2026-10-12-mtgmate', 2]]), row('Bolt', 3, 3, [], [['Gruul Ramp', 1]])],
      totals: {cards: 2, need: 9, missing: 3, aud_missing: 3.75, unpriced: []}, price_error: null, rate: 1.43,
      rate_date: '2026-10-12', price_date: '2026-10-12', conflicts: [], unresolved: [], warnings: []},
    tokens: null, table: null});
  state.profile = {id: 'matt', name: 'Matt', plays_as: 'user'}; state.profiles = [state.profile];
  const hashes = []; history.replaceState = (s, t, hash) => { hashes.push(hash); location.hash = hash; };
  const panel = (name) => main.querySelector('#deck-panel-' + name);
  const tab = (name) => main.querySelector('#deck-tab-' + name);
  const buttonText = (root, text) => root.querySelectorAll('button').find((b) => b.textContent === text);
  const open = (hash) => { clear(main); location.hash = hash; const params = parseHash().params;
    drawDeck(makePage(), deckViewOf(params)); };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckPageUiTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), PAGE + code, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_tabs_are_lazy_and_in_the_address(self):
        self.run_js("""
          open('#/deck?id=casual%2Ftest&v=target');
          same(main.querySelectorAll('[role=tab]').map((b) => b.textContent), ['Overview', 'Cards', 'Stats', 'Practice', 'Matchups']);
          assert.equal(tab('overview').getAttribute('aria-selected'), 'true');
          assert.equal(panel('overview').hidden, false);
          assert.equal(panel('cards').hidden, true);
          // Only the tab shown is drawn: Cards, Stats, Practice (the practice run) and Matchups wait.
          for (const name of ['cards', 'stats', 'practice', 'matchups']) assert.equal(panel(name).children.length, 0, name);
          assert.equal(hashes.length, 0);       // the Overview is the address without a tab
          tab('stats').click();
          assert.equal(panel('stats').hidden, false); assert.equal(panel('overview').hidden, true);
          assert(panel('stats').children.length > 0);
          assert(location.hash.endsWith('&tab=stats'));
          // The arrow keys move between the tabs.
          main.querySelector('[role=tablist]').fire('keydown', {key: 'ArrowRight'});
          assert.equal(tab('practice').getAttribute('aria-selected'), 'true');
          assert(location.hash.endsWith('&tab=practice'));
          // An old ?part=field link opens Matchups; an unknown tab the Overview.
          same(deckViewOf(new URLSearchParams('id=a&part=field')), {tab: 'matchups', filter: 'all'});
          same(deckViewOf(new URLSearchParams('id=a&tab=nope&filter=nope')), {tab: 'overview', filter: 'all'});
        """)

    def test_banner_answers_can_i_build_it(self):
        self.run_js("""
          open('#/deck?id=casual%2Ftest&v=target');
          const banner = main.querySelector('.deck-avail');
          assert(banner.textContent.includes('3 missing, about A$3.75 (planned list)'), banner.textContent);
          assert(banner.textContent.includes('1 held by other decks · 2 cards on the way'));
          assert(banner.querySelector('.segmented'));          // the two lists' picker is folded in
          const info = banner.querySelector('.deck-lists-info');
          assert.equal(banner.querySelector('#deck-lists-about').hidden, true);
          info.click(); assert.equal(banner.querySelector('#deck-lists-about').hidden, false);
          // Show missing opens the Cards tab on its Missing filter.
          buttonText(banner, 'Show missing').click();
          assert.equal(tab('cards').getAttribute('aria-selected'), 'true');
          assert(location.hash.includes('tab=cards') && location.hash.includes('filter=missing'), location.hash);
          const list = panel('cards').querySelector('.deck-cards');
          assert(list.textContent.includes('Bolt')); assert(!list.textContent.includes('Elf'));
          // Every card owned: "Ready to build"; on the way only: ready once they arrive.
          const page = makePage();
          page.owned.rows = [row('Elf', 6, 0)]; page.owned.totals = {...page.owned.totals, missing: 0};
          assert(availabilityBanner(page, {view: {tab: 'overview'}}).textContent.includes('Ready to build'));
          page.owned.rows = [row('Elf', 6, 0, [['order x', 2]])];
          assert(availabilityBanner(page, {view: {tab: 'overview'}}).textContent.includes('Ready once 2 cards arrive'));
        """)

    def test_viewer_who_may_not_see_the_collection_gets_no_marks(self):
        self.run_js("""
          const page = makePage(); delete page.owned; delete page.tokens; delete page.table;
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target&tab=cards';
          drawDeck(page, deckViewOf(parseHash().params));
          const banner = main.querySelector('.deck-avail');
          assert(banner.getAttribute('class').includes('deck-avail-plain'));      // only the list picker
          assert(!banner.textContent.includes('missing'));
          assert(!main.textContent.includes('Show missing'));
          assert.equal(main.querySelector('.deck-filter'), null);
          assert.equal(main.querySelectorAll('.status').length, 0);
          assert.equal(main.querySelector('#sec-owned'), null);
          // One list only: no banner at all.
          page.versions = ['target'];
          assert.equal(availabilityBanner(page, {view: {tab: 'cards'}}), null);
        """)

    def test_incoming_only_cards_name_each_source_in_banner_cards_and_prices(self):
        self.run_js("""
          const page = makePage();
          const sources = [
            {source: 'order 2026-10-14-singles', quantity: 1, order_id: '2026-10-14-singles', status: 'ordered'},
            {source: 'Autumn Starter', quantity: 2, product_id: 'autumn-starter',
              order_id: '2026-10-14-starter', status: 'preordered'}];
          page.owned.rows = [row('Elf', 6, 0, [['order 2026-10-14-singles', 1], ['Autumn Starter, preordered', 2]])];
          page.owned.rows[0].labels.incoming_sources = sources;
          page.owned.totals.missing = 0;
          page.sections = {Deck: page.sections.Deck.slice(0, 2)};
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target&tab=cards&filter=coming';
          drawDeck(page, deckViewOf(parseHash().params));
          const banner = main.querySelector('.deck-avail');
          assert(banner.textContent.includes('Ready once 3 cards arrive'), banner.textContent);
          const list = panel('cards').querySelector('.deck-cards');
          const prices = panel('cards').querySelector('#sec-owned');
          assert(prices.querySelector('table'), 'Incoming-only deck still has the table');
          assert(prices.textContent.includes('Price table: 3 on the way'));
          assert(prices.textContent.includes('Nothing to buy'));
          for (const node of [banner, list, prices]) {
            assert(node.textContent.includes('order 2026-10-14-singles · ordered'), node.textContent);
            assert(node.textContent.includes('Autumn Starter · order 2026-10-14-starter · preordered'), node.textContent);
          }
          const mark = cardMarks(page).get('Elf');
          for (const full of [false, true]) {
            const chips = markChips(mark, full);
            same(chips.map((chip) => chip.textContent), [
              '1 on the way · order 2026-10-14-singles · ordered',
              '2 on the way · Autumn Starter · order 2026-10-14-starter · preordered']);
            assert(chips.every((chip) => chip.classList.contains('chip-wrap')));
          }
        """)

    def test_incoming_sources_are_once_per_card_and_banner_combines_order(self):
        self.run_js("""
          const page = makePage();
          const source = {source: 'order x', quantity: 2, order_id: 'x', status: 'ordered'};
          page.owned.rows = [row('Elf', 6, 0, [['order x', 2]]), row('Bolt', 3, 1, [['order x', 1]])];
          page.owned.rows[0].labels.incoming_sources = [source];
          page.owned.rows[1].labels.incoming_sources = [{...source, quantity: 1}];
          page.owned.totals.missing = 1;
          page.sections.Sideboard = [{...page.sections.Deck[0], qty: 1}];
          const groups = deckGroups(page), marks = lineMarks(groups, cardMarks(page));
          const elves = groups.flatMap((g) => g.lines).filter((line) => line.name === 'Elf');
          assert.equal(elves.length, 2);
          same(marks.get(elves[0]).sources, [source]);
          same(marks.get(elves[1]).sources, []);
          assert.equal(marks.get(elves[1]).coming, 0);
          const banner = availabilityBanner(page, {view: {tab: 'cards'}});
          assert(banner.textContent.includes('1 missing'));
          assert.equal(banner.querySelector('.deck-avail-sources').textContent, 'On the way: 3 from order x · ordered');
          delete page.owned;
          assert.equal(cardMarks(page).size, 0);
          assert(!availabilityBanner(page, {view: {tab: 'cards'}}).textContent.includes('order x'));
        """)

    def test_cards_tab_marks_merges_and_filters(self):
        self.run_js("""
          cardsMode = () => 'list';
          open('#/deck?id=casual%2Ftest&v=target&tab=cards');
          const cards = panel('cards');
          // Two printings of Elf are one row, its printings in its subtitle; its copies on the way are marked.
          const elfRow = cards.querySelectorAll('.card-row').find((r) => r.textContent.includes('Elf'));
          assert(elfRow.textContent.includes('FDN 1 ×4 · M21 2 Foil ×2'), elfRow.textContent);
          assert(elfRow.textContent.includes('2 on the way'));
          // Bolt: every copy missing, greyed, and held by another deck.
          const boltRow = cards.querySelectorAll('.card-row').find((r) => r.textContent.includes('Bolt'));
          assert(boltRow.classList.contains('is-missing'));
          assert(boltRow.textContent.includes('Missing') && boltRow.textContent.includes('1 in Gruul Ramp'));
          // Basic lands have no marks; the filters offer only what has cards in it.
          const forestRow = cards.querySelectorAll('.card-row').find((r) => r.textContent.includes('Forest'));
          assert.equal(forestRow.querySelectorAll('.status').length, 0);
          // The filters count copies, as the banner does ("3 missing"); the line under one counts different cards.
          same(cards.querySelector('.deck-filter').querySelectorAll('button').map((b) => b.textContent),
               ['All', 'Missing3', 'On the way2', 'In other decks1']);
          buttonText(cards.querySelector('.deck-filter'), 'On the way2').click();
          assert(location.hash.endsWith('filter=coming'), location.hash);
          assert(cards.querySelector('.deck-cards').textContent.includes('1 of 3 different cards'));
          // Under a filter a group's heading counts what the filter is about.
          assert.equal(cards.querySelector('.deck-cards').querySelector('.count').textContent, '(2 on the way)');
          // Pictures: tiles in the same viewer group, remembered on the device.
          buttonText(cards, 'Pictures').click();
          assert.equal(buttonText(cards, 'Pictures').getAttribute('aria-pressed'), 'true');
          assert(cards.querySelectorAll('.card-tile').length >= 1);
          assert.equal(cards.querySelectorAll('.card-tile-open')[0].getAttribute('data-viewer'), 'deck');
          // The price table is folded, with only the cards worth a look.
          const prices = cards.querySelector('#sec-owned');
          assert(prices.textContent.includes('Price table: 3 missing, about A$3.75'));
          assert(!prices.querySelector('table').textContent.includes('Forest'));
        """)

    def test_head_and_overview(self):
        self.run_js("""
          open('#/deck?id=casual%2Ftest&v=target');
          const head = main.querySelector('.deck-page-head');
          assert.equal(head.querySelector('h1').textContent, 'Test Deck');
          assert(head.textContent.includes('Building'));
          assert(head.textContent.includes('Casual 29 · Matt · 29 cards'));
          // The deck's colour identity as P1 pips (ui.js deckColourPieces), 22 px, never cost symbols.
          const pips = head.querySelector('.deck-head-pips');
          assert.equal(pips.getAttribute('role'), 'img');
          assert.equal(pips.getAttribute('aria-label'), 'Colours: red, green');
          assert(pips.matches('.id-pips-lg'));
          assert.equal(pips.querySelectorAll('.sym').length, 0);
          // No "build on your computer" sentence; More holds the rest.
          assert(!main.textContent.includes('on your computer'));
          const more = head.querySelectorAll('[role=menuitem]').map((i) => i.textContent);
          for (const words of ['Game log', 'History', 'Copy decklist', 'Download decklist', 'Print play sheet'])
            assert(more.includes(words), words);
          // The library's cover picker (cover.js) for a deck text the viewer may change, never a product.
          assert(more.includes('Change library picture…'));
          const product = makePage();
          product.summary = { ...product.summary, id: 'product/box', read_only: true };
          assert(!deckMoreItems(product).some((i) => i && i.label === 'Change library picture…'));
          // Key cards: the most-copied spells, big, in their own viewer group.
          const key = panel('overview').querySelector('.deck-key-cards');
          same(key.querySelectorAll('.card-tile-name').map((n) => n.textContent), ['Elf', 'Bolt']);
          assert.equal(key.querySelectorAll('.card-tile-open')[0].getAttribute('data-viewer'), 'key');
        """)

    def test_library_picture_in_the_head_and_its_change_redraws_the_page(self):
        self.run_js("""
          const withCover = makePage();
          withCover.summary.cover = {name: 'Elf', art: '/img/fdn/1/art_crop', auto: true};
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target';
          drawDeck(withCover, deckViewOf(parseHash().params));
          const pic = main.querySelector('.deck-head-cover');
          assert(pic && pic.parentNode.getAttribute('class') === 'deck-title-row');
          assert(pic);
          assert.equal(pic.getAttribute('aria-hidden'), 'true');
          assert.equal(pic.querySelector('img').getAttribute('src'), '/img/fdn/1/art_crop');
          // Without a cover (or one that isn't Deck Lab's own picture) there's nothing beside the title.
          open('#/deck?id=casual%2Ftest&v=target');
          assert.equal(main.querySelector('.deck-head-cover'), null);
          // The More item opens the picker; its save draws this deck's page again (route) and forgets the library.
          let picked = null, routed = 0;
          openCoverPicker = (id, onDone) => { picked = [id, onDone]; };
          route = () => { routed += 1; };
          state.library = {decks: []};
          deckMoreItems(withCover).find((i) => i && i.label === 'Change library picture…').onclick();
          assert.equal(picked[0], 'casual/test');
          picked[1]({name: 'Bolt'}, 4);
          assert.equal(routed, 1);
          assert.equal(state.library, null);
          // Saved after the page was left: nothing is drawn again.
          location.hash = '#/library';
          picked[1]({name: 'Bolt'}, 5);
          assert.equal(routed, 1);
        """)

    def test_a_token_without_a_picture_shows_labelled_example_art(self):
        self.run_js("""
          const list = tokenNeedList([
            {key: 'a', name: 'Ooze', state: 'none', image: null, example: '/img/tx/9/small', cards: []},
            {key: 'b', name: 'Zombie', state: 'ready', image: '/img/tm/1/small', example: null, cards: []},
            {key: 'name:Mystery', name: 'Mystery', state: 'none', image: null, cards: []}]);
          const needs = list.querySelectorAll('.token-need');
          assert.equal(needs[0].querySelector('.token-need-example').textContent, 'Example art');
          assert.equal(needs[0].querySelector('img').getAttribute('src'), '/img/tx/9/small');
          assert.equal(needs[1].querySelector('.token-need-example'), null);
          assert.equal(needs[1].querySelector('img').getAttribute('src'), '/img/tm/1/small');
          // No picture and no example: the letter, unlabelled.
          assert.equal(needs[2].querySelector('.token-need-example'), null);
          assert.equal(needs[2].querySelector('.tok-thumb-fallback').textContent, 'M');
        """)

    def test_field_budget_choice_is_saved_for_the_profile_and_survives_a_failed_save(self):
        self.run_js("""
          const writes = [], messages = [];
          apiWrite = async (path, body, method) => { writes.push({path, body, method}); return {}; };
          toast = (message) => messages.push(message);
          runsAllowed = () => true;
          const ctx = {budget: 'standard'};
          const box = fvPlayBox(ctx, {status: 'none', forge: {ready: true}});
          buttonText(box, 'Quick look').fire('click');
          await ctx.budgetSave;
          assert.equal(ctx.budget, 'quick');
          same(writes, [{path: '/api/profiles/matt/settings', body: {field_budget: 'quick'}, method: 'PUT'}]);
          state.profile = {id: 'user1', name: 'User1'};
          buttonText(box, 'Precise').fire('click');
          await ctx.budgetSave;
          assert.equal(writes[1].path, '/api/profiles/user1/settings');
          same(writes[1].body, {field_budget: 'thorough'});
          apiWrite = async () => { throw new Error('Database is unavailable.'); };
          buttonText(box, 'Settle it').fire('click');
          await ctx.budgetSave;
          assert.equal(ctx.budget, 'standard');
          assert.equal(buttonText(box, 'Settle it').getAttribute('aria-pressed'), 'true');
          assert(messages[0].includes("User1's usual field run couldn't be saved"));
          assert(messages[0].includes('Database is unavailable.'));
          state.profile = null;
          messages.length = 0;
          await fvSaveBudget(ctx, 'quick');
          assert.equal(ctx.budget, 'quick');
          assert.equal(messages.length, 0, 'an unnamed visitor has no settings to save');
        """)

    def test_field_budget_saves_stay_in_order_and_queued_picks_do_not_cross_profiles(self):
        self.run_js("""
          const writes = [], releases = [];
          apiWrite = (path, body) => { writes.push({path, body}); return new Promise((resolve) => releases.push(resolve)); };
          const first = {budget: 'standard'}, nextDeck = {budget: 'standard'};
          const quick = fvSaveBudget(first, 'quick');
          await Promise.resolve();
          const precise = fvSaveBudget(nextDeck, 'thorough');
          await Promise.resolve();
          assert.equal(writes.length, 1, "the second deck waits for this profile's earlier save");
          releases.shift()({});
          await quick;
          await Promise.resolve();
          same(writes.map((w) => w.body.field_budget), ['quick', 'thorough']);
          releases.shift()({});
          await precise;
          // Changing person while a choice is queued never sends it with the new viewer's header.
          const pending = fvSaveBudget(first, 'quick');
          await Promise.resolve();
          const queued = fvSaveBudget(first, 'standard');
          state.profile = {id: 'user1', name: 'User1'};
          releases.shift()({});
          await pending;
          await queued;
          assert.equal(writes.length, 3);
          assert.equal(FV_BUDGET_SAVES.size, 0);
        """)

    def test_every_live_matchup_shows_its_range_without_a_finished_verdict(self):
        self.run_js("""
          fitWidth = (host, draw) => draw(300);
          const live = liveBox({});
          const sides = [{title: 'Elves'}, {title: 'Angels'}];
          const job = {status: 'running', done: 50, total: 200, wins: [30, 18], other: 2,
            range: {value: .6, low: .3, high: .8}, mode: 'fixed'};
          for (const via of [null, {title: 'Field run of Elves', link: '#/deck?id=casual/elves&part=field'},
                                   {title: 'Test of a change to Elves', link: '#/variant?test=abc'}]) {
            live.update({sides, job: {...job, via}});
            const range = live.node.querySelector('.mu-live-range');
            assert.equal(range.hidden, false);
            assert(range.textContent.includes('Live range: wider while games are still being played'));
            const bar = range.querySelector('.range-bar');
            assert.equal(bar.getAttribute('role'), 'img');
            assert(bar.getAttribute('aria-label').includes("Elves's live range"));
            assert(bar.getAttribute('class').includes('is-live'));
            assert(!live.node.textContent.includes('About even'));
            assert(!live.node.textContent.includes('Slightly ahead'));
            assert.equal(live.node.querySelector('.actions').hidden, !!via);
          }
          live.update({sides, job: {...job, status: 'queued'}});
          assert.equal(live.node.querySelector('.mu-live-range').hidden, true);
          live.update({sides, job: {...job, done: 0, wins: [0, 0], other: 0, range: null}});
          assert.equal(live.node.querySelector('.mu-live-range').hidden, true);
        """)

    def test_stats_verdict_strip(self):
        self.run_js("""
          const st = {curve: {average_mv: 2.5}, lands: {effective: 22, recommended: 24.7, verdict: 'low'},
            colours: {colours: [{name: 'red', ok: false}, {name: 'green', ok: true}]},
            commander: {ok: true, problems: [], bracket: {label: 'Bracket 2'}}};
          const strip = statsVerdict(st, {target_bracket: 2});
          const text = strip.textContent;
          for (const words of ['Average mana value', '2.5', 'Lands', '22', 'the formula says 24.7', 'Low', 'Red',
                               'Deck rules', 'Followed', 'Bracket 2', 'aims for Bracket 2']) assert(text.includes(words), words);
          // Chips only where something's off.
          same(strip.querySelectorAll('.status').map((s) => s.textContent), ['Low', 'Short']);
          // Advice for tuning, never a blocker: amber, not red.
          assert.equal(strip.querySelectorAll('.status-crit').length, 0);
          assert.equal(strip.querySelectorAll('.status-warn').length, 2);
          const fine = statsVerdict({curve: {average_mv: 3}, lands: {effective: 24, recommended: 24, verdict: 'ok'},
            colours: {colours: [{name: 'green', ok: true}]}}, {});
          assert.equal(fine.querySelectorAll('.status').length, 0);
          assert(fine.textContent.includes('Ok; the formula says 24'));
          assert(fine.textContent.includes('Enough'));
          const unknown = statsVerdict({lands: {effective: 24}}, {});
          assert(!unknown.textContent.includes('Ok'));
        """)

    def test_matchups_tab_one_row_per_opponent(self):
        self.run_js("""
          const side = (id, title, version = 'target') => ({id, title, version, current: true});
          const result = (b, updated, value) => ({key: b.id + updated, sides: [side('casual/test', 'Test Deck'), b],
            games: 800, winrate: {value, low: value - .02, high: value + .02, balanced: true}, updated, by: 'Matt',
            engine: {current: true}});
          const angels = side('casual/angels', 'Angels'), otters = side('casual/otters', 'Otters');
          state.library = {decks: [{id: 'casual/test', kind: 'casual', card_count: 60, title: 'Test Deck'},
            {id: 'casual/angels', kind: 'casual', card_count: 60, title: 'Angels'},
            {id: 'casual/otters', kind: 'casual', card_count: 60, title: 'Otters'},
            {id: 'casual/rabbits', kind: 'casual', card_count: 60, title: 'Rabbits'},
            {id: 'commander/gisa', kind: 'commander', card_count: 100, title: 'Gisa'},
            {id: 'product/fdn-beginner-box/cats', kind: 'casual', card_count: 20, title: 'Cats'}], halves: []};
          const page = makePage();
          page.matchups = {ai: null, running: [], forge: {ready: true}, cards: null,
            results: [result(angels, '2026-10-01T10:00:00', .4), result(otters, '2026-10-02T10:00:00', .6),
                      result(angels, '2026-10-04T10:00:00', .45)]};
          // Play a matchup only for a viewer who may start runs.
          runsAllowed = () => false;
          assert(!deckMatchupsPart(page).querySelectorAll('a').some((a) => a.textContent === 'Play a matchup'));
          runsAllowed = () => true;
          const part = deckMatchupsPart(page); main.append(part);
          // The matchup screens' rows (deckResultParts): one per opponent, best first, the newest of a pair's
          // results shown and the earlier one folded.
          const rows = part.querySelectorAll('.mu-list')[0].children;
          assert.equal(rows.length, 2);                                  // Angels once, Otters once
          assert(rows[0].textContent.includes('Otters') && rows[0].textContent.includes('60'), rows[0].textContent);
          assert(rows[1].textContent.includes('Angels') && rows[1].textContent.includes('45'), rows[1].textContent);
          assert(part.querySelector('.mu-earlier-results').textContent.includes('Earlier results (1)'));
          // The field part leaves an opponent met head to head out of its "Not played yet against".
          deckScreen = {data: page};
          assert(headToHead('casual/otters'));
          assert.equal(headToHead('casual/rabbits'), null);
          deckScreen = null;
          const unplayed = part.querySelector('.mu-not-played').textContent;
          assert.equal(unplayed, 'Not played yet against: Rabbits.');   // same format, a whole deck, not met
          assert(part.querySelectorAll('a').some((a) => a.textContent === 'Play a matchup'
            && a.getAttribute('class').includes('btn-primary')));
          // Asked for only when the tab opens: a page drawn without its matchups fetches them.
          let asked = null; api = async (path) => { asked = path; return {matchups: page.matchups}; };
          const lazy = makePage(); main.append(deckMatchupsPart(lazy));
          assert.equal(asked, '/api/deck?id=casual%2Ftest&version=target');
          for (let i = 0; i < 10; i++) await null;
          assert.equal(lazy.matchups, page.matchups);
        """)

    def test_guide_names_are_text_links_with_symbols(self):
        self.run_js("""
          state.cards = new Map([['Llanowar Elves', card('Llanowar Elves', 'Creature — Elf', 1)]]);
          const parts = guideCardText('Tap Llanowar Elves ({T}) for {G}.');
          // A span with the button role, so a long name wraps like the words around it.
          const link = parts.find((p) => p.tag === 'span' && p.getAttribute('role') === 'button');
          assert(link.getAttribute('class').includes('card-link-text'));
          assert.equal(link.getAttribute('tabindex'), '0');
          assert.equal(link.getAttribute('data-viewer'), 'guide');
          assert.equal(parts.filter((p) => p.tag === 'img').length, 2);    // {T} and {G} as symbols
          assert(!parts.some((p) => typeof p === 'string' && p.includes('{T}')));
        """)

    def test_big_tile_falls_back_from_the_large_picture(self):
        self.run_js("""
          // The large picture is offered; when it can't load, the small and normal ones are, and the picture
          // stays (cardTile's own error listener used to remove it first). A second failure leaves the words.
          const tile = bigTile(elf, {qty: 4, name: 'Elf'});
          const img = tile.querySelector('.card-tile-img');
          assert.equal(img.getAttribute('srcset'), '/img/fdn/1/small 146w, /img/fdn/1/normal 488w, /img/fdn/1/large 672w');
          img.fire('error');
          assert(tile.contains(img));
          assert.equal(img.getAttribute('srcset'), '/img/fdn/1/small 146w, /img/fdn/1/normal 488w');
          img.fire('error');
          assert(!tile.contains(img));
          assert(tile.querySelector('.card-tile-text'));
          // A tile without a large picture removes a picture that fails, as before.
          const plain = cardTile(elf, {}); const p = plain.querySelector('.card-tile-img');
          p.fire('error'); assert(!plain.contains(p));
        """)

    def test_a_card_in_the_deck_and_the_sideboard_is_marked_once(self):
        self.run_js("""
          cardsMode = () => 'list';
          const page = makePage();
          page.sections.Sideboard = [{qty: 1, name: 'Bolt', set: 'fdn', number: '3', finish: 'nonfoil', card: bolt}];
          // 4 Bolts needed, 1 missing, 1 more held by Gruul Ramp: the missing copy is the sideboard's.
          page.owned.rows = [row('Elf', 6, 0), row('Bolt', 4, 1, [], [['Gruul Ramp', 1]])];
          page.owned.totals = {...page.owned.totals, missing: 1};
          clear(main); location.hash = '#/deck?id=casual%2Ftest&v=target&tab=cards';
          drawDeck(page, deckViewOf(parseHash().params));
          const rows = panel('cards').querySelectorAll('.card-row').filter((r) => r.textContent.includes('Bolt'));
          assert.equal(rows.length, 2);
          const [first, side] = rows;
          assert(!first.textContent.includes('issing') && first.textContent.includes('1 in Gruul Ramp'), first.textContent);
          assert(side.textContent.includes('Missing') && !side.textContent.includes('Gruul Ramp'), side.textContent);
          assert(side.classList.contains('is-missing')); assert(!first.classList.contains('is-missing'));
          same(panel('cards').querySelector('.deck-filter').querySelectorAll('button').map((b) => b.textContent),
               ['All', 'Missing1', 'In other decks1']);
          // Some copies missing: "1 of 2 missing".
          const part = lineMarks([{lines: [{name: 'Bolt', qty: 2}]}], new Map([['Bolt', {need: 2, missing: 1, coming: 0, held: []}]]));
          const mark = [...part.values()][0];
          same(markChips(mark).map((c) => c.textContent), ['1 of 2 missing']);
          // Every copy missing: the greyed tile says it, so no chip (only a screen reader's word); the viewer, which
          // shows the card big in colour, says it in full under its counter.
          const gone = {need: 1, missing: 1, coming: 0, held: []};
          assert.equal(markChips(gone).filter((c) => c.classList.contains('status')).length, 0);
          same(markChips(gone).map((c) => c.textContent), ['Missing']);
          same(markChips(gone, true).map((c) => c.textContent), ['Missing · need 1, have 0']);
          same(markChips(mark, true).map((c) => c.textContent), ['1 of 2 missing · need 2, have 1']);
        """)

    def test_guide_viewer_has_each_card_once(self):
        self.run_js("""
          state.cards = new Map([['Elf', elf], ['Bolt', bolt]]);
          const p = el('p', {}, guideCardText('Elf first, then Bolt, then Elf again.'));
          main.append(p);
          const links = p.querySelectorAll('[data-viewer]');
          assert.equal(links.length, 3);
          let opened = null; openCardViewer = (items, start, opts) => { opened = {items, start, opts}; };
          links[2].click();                                   // the second "Elf"
          same(opened.items.map((i) => i.card.name), ['Elf', 'Bolt']);
          assert.equal(opened.start, 0); assert.equal(opened.opts.trigger, links[2]);
          // Enter and Space open it too (it's a span with the button role).
          opened = null; links[1].fire('keydown', {key: 'Enter'}); assert.equal(opened.start, 1);
          opened = null; links[1].fire('keydown', {key: 'a'}); assert.equal(opened, null);
          // Commander key cards follow what the guide names most, after the commander.
          const page = makePage();
          page.summary.kind = 'commander';
          const big = card('Big', 'Creature — Wurm', 7);
          page.sections = {Commander: [{qty: 1, name: 'Elf', card: elf}], Deck: [
            {qty: 1, name: 'Big', card: big}, {qty: 1, name: 'Bolt', card: bolt}]};
          state.cards = new Map([['Elf', elf], ['Big', big], ['Bolt', bolt]]);
          page.guide = {sections: [{title: 'Game plan', markdown: 'Elf, then Bolt. Bolt again.'}]};
          same(keyCardsPart(page, 3).querySelectorAll('.card-tile-name').map((n) => n.textContent), ['Elf', 'Bolt', 'Big']);
        """)

    def test_head_keeps_the_title_row_and_links_keep_the_tab(self):
        self.run_js("""
          // The editor's sentence beside a product's button goes under the facts, not into the button row.
          const real = deckActions;
          deckActions = () => el('div', {class: 'deck-actions'}, el('a', {class: 'btn btn-primary', text: 'Save as a new deck'}),
            el('span', {class: 'sub', text: 'Product decks stay as they came.'}));
          open('#/deck?id=casual%2Ftest&v=target');
          deckActions = real;
          const head = main.querySelector('.deck-page-head');
          const actions = head.querySelector('.deck-head-actions');
          assert.equal(actions.querySelector('.sub'), null);
          assert.equal(head.querySelector('.deck-head-note').textContent, 'Product decks stay as they came.');
          assert.equal(actions.querySelector('.menu-button').getAttribute('aria-label'), 'More for this deck');
          // The first draw never scrolls the window to the tab strip.
          assert.equal(tab('overview').scrolled, undefined);
          // The two lists' links carry the tab shown in their address (a new tab or a copied link keeps it).
          const links = main.querySelector('.deck-lists').querySelectorAll('a');
          same(links.map((a) => a.getAttribute('href')), ['#/deck?id=casual%2Ftest&v=target', '#/deck?id=casual%2Ftest&v=owned']);
          tab('stats').click();
          same(links.map((a) => a.getAttribute('href')), ['#/deck?id=casual%2Ftest&v=target&tab=stats',
            '#/deck?id=casual%2Ftest&v=owned&tab=stats']);
          // "Nothing to buy" is words, not a chip.
          const fine = makePage(); fine.owned.rows = [row('Elf', 6, 0)]; fine.owned.totals = {...fine.owned.totals, missing: 0};
          const prices = ownedSection(fine);
          assert(prices.textContent.includes('Nothing to buy'));
          assert.equal(prices.querySelectorAll('.status').length, 0);
        """)

    def test_commander_rules_kept_have_no_chips(self):
        self.run_js("""
          assert.equal(checkItem(true, 'One copy of each card').querySelectorAll('.status').length, 0);
          assert(checkItem(true, 'x').querySelector('.check-ok'));
          same(checkItem(false, 'x').querySelectorAll('.status').map((c) => c.textContent), ['Problem']);
          same(checkItem(null, 'x').querySelectorAll('.status').map((c) => c.textContent), ['Not checked']);
        """)

if __name__ == "__main__":
    unittest.main()
