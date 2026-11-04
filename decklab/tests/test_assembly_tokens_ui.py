"""Build decks' tokens as pictures: plainly optional, and never in the way of finishing."""
import unittest

from decklab.tests import test_assembly_completion_ui as completion
from decklab.tests.test_workspace_ui import NODE, WEB


SETUP = """
  window.matchMedia('(min-width: 1000px)').matches = false;
  const zombie = {key:'k-zombie', name:'Zombie', kind:'token', state:'ready', image:'/img/tfdn/1/small', packing_key:'a'.repeat(64),
    cards:[{row:0, front:'Zombie', back:'Zombie Knight', side:'front', quantity:3, img:'/img/tfdn/1/small', back_img:'/img/tfdn/2/small', example_art:false}]};
  const noCard = {key:'k-ape', name:'Ape', kind:'token', state:'none', image:'/img/tfdn/3/small', cards:[], stand_ins:[]};
  const coming = {key:'k-fish', name:'Fish', kind:'token', state:'incoming', image:null, on_the_way:2, cards:[], stand_ins:[]};
  const monarch = {key:'k-monarch', name:'The Monarch', kind:'reminder', state:'ready', image:null, packing_key:'b'.repeat(64),
    cards:[{row:1, front:'The Monarch', back:'', side:'front', quantity:1, img:null, back_img:null}]};
  const spirit = {key:'k-spirit', name:'Spirit', kind:'token', side:'opponent', state:'ready', image:null, packing_key:'c'.repeat(64),
    cards:[{row:2, front:'Spirit', back:'', side:'front', quantity:1, img:'/img/tfdn/4/small', back_img:null, example_art:true}]};
  const tokened = (needs=[zombie], extra={}) => ({...item(), tokens:{needs, copies:[], unlisted:[], ...extra}});
  const tokenTicks = () => main.querySelectorAll('.pack-tick-optional');
  const tokenStep = () => main.querySelectorAll('.pack-step').find(s => s.textContent.includes('Tokens (optional)'));
  const openPlan = (decks, extra={}) => { drawAssembly({...plan(decks), ...extra}, routeToken); return packingProgressView; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class AssemblyTokensUiTests(unittest.TestCase):
    def run_js(self, scenario):
        completion.AssemblyCompletionUiTests.run_js(self, SETUP + scenario)

    def test_a_token_is_a_picture_with_its_name_and_one_short_line(self):
        self.run_js("""
          openPlan([tokened([zombie, noCard, coming, monarch, spirit])]); await settle();
          const step = tokenStep(), tiles = step.querySelectorAll('.card-tile');
          same(tiles.map(t => t.querySelector('.card-tile-name').textContent), ['Zombie', 'Ape', 'Fish', 'The Monarch', 'Spirit']);
          same(tiles.map(t => t.querySelector('.card-tile-meta')?.textContent ?? null), ['Zombie side', 'No card', '2 on the way', null, null]);
          // Both faces, the copies, and a dimmed example where there's no card.
          assert.equal(tiles[0].querySelector('.card-tile-img').getAttribute('src'), '/img/tfdn/1/small');
          assert.equal(tiles[0].querySelector('.card-tile-back').getAttribute('src'), '/img/tfdn/2/small');
          assert.equal(tiles[0].querySelector('.card-tile-qty').textContent, '×3');
          assert.equal(tiles[1].querySelector('.card-tile-img').getAttribute('src'), '/img/tfdn/3/small');
          assert(tiles[1].classList.contains('is-missing'));
          assert(!tiles[0].classList.contains('is-missing'));
          // No card and on the way have no tick.
          assert.equal(tokenTicks().length, 3);
          // Reminders and the opponent's are told apart by a heading, not more words on each tile.
          same(step.querySelectorAll('h4').map(h => h.textContent), ['Reminders', 'For your opponent']);
          // No list of sentences: one short line for the whole step.
          assert.equal(step.querySelector('.pack-list'), null);
          same(step.querySelector('.pack-step-body').children.filter(n => n.tag === 'p').map(p => p.textContent),
            ['Anything will do: a spare token, a die or a scrap of paper.']);
        """)

    def test_longer_words_open_in_the_tokens_own_viewer_group(self):
        self.run_js("""
          openPlan([tokened([zombie, noCard, spirit])]); await settle();
          const opens = tokenStep().querySelectorAll('.card-tile-open');
          const group = viewerGroup(opens[0]);
          assert.equal(opens[0].getAttribute('data-viewer'), 'pack-tokens');
          same(group.items.map(i => i.caption), ['Grab Zombie / Zombie Knight ×3 (Zombie side only, can be sleeved) for Zombie',
            'No Ape token. Anything will do: a spare token, a die or a scrap of paper. Example art: printing not recorded.',
            'For your opponent: Grab Spirit ×1 for Spirit. Example art: printing not recorded.']);
          assert.equal(group.items[0].card.img, '/img/tfdn/1/normal');
          assert(group.items[1].card.name.startsWith('Example art'));
          assert(!group.items[0].card.name.startsWith('Example art'));
          // The cards' viewer stays the cards': no token joins it.
          assert.equal(main.querySelector('.pack-tiles').querySelector('.card-tile-open').getAttribute('data-viewer'), 'packing');
        """)

    def test_a_token_tile_offers_the_normal_picture_at_the_cards_size(self):
        self.run_js("""
          openPlan([tokened()]); await settle();
          const img = tokenStep().querySelector('.card-tile-img');
          assert.equal(img.getAttribute('srcset'), '/img/tfdn/1/small 146w, /img/tfdn/1/normal 488w');
          assert.equal(img.getAttribute('sizes'), PACK_TILE_SIZES);
        """)

    def test_a_token_ticks_from_the_big_view_as_a_card_does(self):
        self.run_js("""
          const v = openPlan([tokened([zombie, noCard, spirit])]); await settle();
          const opens = tokenStep().querySelectorAll('.card-tile-open');
          opens[0].click(); viewerDom.dialog.open = true; viewerDom.dialog.setAttribute('open', '');
          const panel = v.viewerPanel, tick = v.ticks.find(t => t.optional);
          // Only the tokens: their own group, not the cards.
          assert.equal(viewerState.items.length, 3);
          assert.equal(panel.task.textContent, 'Elves: Grab Zombie / Zombie Knight ×3 (Zombie side only, can be sleeved) for Zombie');
          assert.equal(panel.tick.textContent, 'Tick off'); assert(panel.slot.hidden);
          panel.tick.click(); await settle();
          assert(tick.done); assert.equal(tokenTicks()[0].getAttribute('aria-pressed'), 'true');
          assert.equal(panel.tick.textContent, 'Ticked');
          // Still optional: the big view's tick counts for nothing either.
          assert(v.bar.progress.other.hidden); assert.equal(tick.tile, null);
          // No card, so no tick, but its words are in sight.
          goViewer(1);
          assert(panel.tick.hidden); assert(panel.note.hidden); assert(!viewerDom.marks.hidden);
          assert(panel.task.textContent.startsWith('Elves: No Ape token.'));
          goViewer(2); assert(!panel.tick.hidden); assert.equal(panel.tick.textContent, 'Tick off');
        """)

    def test_a_token_with_no_picture_doesnt_talk_about_rules_text(self):
        self.run_js("""
          openPlan([tokened([coming, monarch])]); await settle();
          const items = viewerGroup(tokenStep().querySelector('.card-tile-open')).items;
          assert.equal(items[0].card.oracle_text, undefined);
          assert.equal(items[1].card.type_line, 'Reminder');
          tokenStep().querySelector('.card-tile-open').click();
          const words = viewerDom.dialog.textContent;
          assert(words.includes('No picture of this token.'), words);
          assert(!words.includes('read the card text')); assert(!words.includes("Card text isn't available"));
        """)

    def test_check_by_hand_and_all_your_token_cards_are_closed_and_pictures(self):
        self.run_js("""
          const rows = [{quantity:2, front:'Zombie', back:'', notes:'', key:'2', img:'/img/tfdn/1/small', back_img:null, example_art:false}];
          openPlan([tokened([zombie], {copies:['Gandalf'], unlisted:['Elrond']})], {tokens:rows, token_problems:['line 4: bad'],
            token_note:'Worked out from links, so it is approximate.'}); await settle();
          const fold = tokenStep().querySelector('.pack-fold');
          assert.equal(fold.querySelector('summary').textContent, 'Check by hand (2 cards)');
          assert(!fold.open);
          const panel = main.querySelector('.assembly-token-list');
          assert(!panel.open);
          assert.equal(panel.querySelector('summary').textContent, 'All your token cards (1)');
          assert(panel.querySelector('p').textContent.includes('approximate'), 'folded away with the list, not lost');
          assert.equal(panel.querySelector('.card-tile-img').getAttribute('src'), '/img/tfdn/1/small');
          assert.equal(panel.querySelector('.card-tile-open').getAttribute('data-viewer'), 'pack-token-cards');
          assert.equal(panel.querySelector('ul'), null);
          const problems = main.querySelector('.pack-token-problems');
          assert(!problems.open);
          assert.equal(problems.querySelector('summary').textContent, "Some token rows can't be read (1)");
        """)

    def test_a_token_ticks_identity_is_the_saved_progress_ones(self):
        self.run_js("""
          const unkeyed = {key:'k-elf', name:'Elf', kind:'token', state:'ready',
            cards:[{row:0, front:'Elf', back:'', side:'front', quantity:1}]};
          const differs = {key:'k-rat', name:'Rat', kind:'token', state:'differs', cards:[],
            stand_ins:[{row:0, front:'Elf', back:'', side:'front', quantity:1, why:['not a Rat']}]};
          const row = {front:'Elf', back:'', set:'tfdn', front_collector_number:'1', back_collector_number:'', finish:'nonfoil',
            quantity:1, front_details:'1/1', back_details:'', notes:''};
          const v = openPlan([tokened([zombie, unkeyed, differs])], {tokens:[row]}); await settle();
          const place = 'casual/a:target', facts = ['front','Elf','','tfdn','1','','nonfoil',1,'1/1',''];
          const ids = v.ticks.filter(t => t.optional).map(t => t.id);
          same(ids, [JSON.stringify([place,'token|k-zombie',1,JSON.stringify('a'.repeat(64))]),
                     JSON.stringify([place,'token|k-elf',1,JSON.stringify([facts])]),
                     JSON.stringify([place,'token|k-rat',1,JSON.stringify(facts)])]);
          // A tick saved before the pictures comes back ticked.
          serverTicks.add(ids[0]);
          clear(main); openPlan([tokened([zombie, unkeyed, differs])], {tokens:[row]}); await settle();
          assert.equal(tokenTicks()[0].getAttribute('aria-pressed'), 'true');
          assert(tokenTicks()[0].closest('.card-tile').classList.contains('is-ticked'));
        """)

    def test_a_token_tick_looks_like_a_tile_but_is_no_card_task(self):
        self.run_js("""
          const v = openPlan([tokened()]); await settle();
          const token = v.ticks.find(t => t.optional);
          assert.equal(token.tile, null);
          assert.equal(v.ticks.filter(t => t.tile).length, 1);
          const before = v.bar.progress.copies.textContent;
          assert(v.bar.progress.other.hidden);
          tokenTicks()[0].click(); await settle();
          assert.equal(tokenTicks()[0].getAttribute('aria-pressed'), 'true');
          assert.equal(v.bar.progress.copies.textContent, before);
          assert(v.bar.progress.other.hidden);
          assert.equal(v.bar.progress.state.textContent, '');
          // Tick all card checks leaves it alone, and Clear takes it off with the rest.
          tokenTicks()[0].click(); await settle();
          main.querySelector('.pack-bulk-tick').click(); await settle();
          assert.equal(tokenTicks()[0].getAttribute('aria-pressed'), 'false');
          tokenTicks()[0].click(); await settle();
          packClearTicks(v); await settle();
          assert.equal(tokenTicks()[0].getAttribute('aria-pressed'), 'false');
        """)

    def test_all_packed_and_finishing_never_wait_for_tokens(self):
        self.run_js("""
          const posts = [];
          const data = plan([tokened([zombie, noCard, spirit])]);
          mockApi(async (path, body) => { posts.push([path, body]);
            return {saved:true, built:data.completion.decks, plan:completed(data), warnings:[], tables:{}}; });
          drawAssembly(data, routeToken); await settle();
          const v = packingProgressView;
          assert(!/token/i.test(v.finish.message.textContent));
          checkCards(); await settle();
          assert(v.ticks.some(t => t.optional && !t.done));
          assert.equal(v.bar.progress.state.textContent, 'All packed.');
          assert(packCanFinish(v)); assert(!builtBlocked());
          assert(!/token/i.test(v.finish.message.textContent), v.finish.message.textContent);
          assert(!/token/i.test(main.querySelector('.pack-completion').textContent));
          builtButton().click(); await settle();
          same(posts, [['/api/assembly/built', {decks:[{id:'casual/a',version:'target'}], fingerprint:'first-plan', confirmed:true}]]);
        """)

    def test_a_plan_with_only_token_ticks_has_nothing_required(self):
        self.run_js("""
          const deck = tokened(); deck.steps = [];
          const v = openPlan([deck]); await settle();
          assert(packCanFinish(v));
          assert.equal(v.bar.progress.state.textContent, '');
          assert(v.bar.progress.other.hidden);
        """)

    def test_a_token_tick_saving_or_failing_never_holds_the_finish_back(self):
        self.run_js("""
          const v = openPlan([tokened()]); await settle();
          checkCards(); await settle();
          assert(packCanFinish(v));
          // Saving: a token tick on its way to the server.
          let release;
          apiWrite = () => new Promise((resolve, reject) => { release = reject; });
          tokenTicks()[0].click();
          assert(v.progress.pending.size); assert(packCanFinish(v));
          assert(!/saving/i.test(v.finish.message.textContent));
          // Failing: its Retry stays beside the ticks, and the finish goes on.
          release(new Error('No network')); await settle();
          assert(v.progress.error); assert(packCanFinish(v));
          assert(!/save shared progress/i.test(v.finish.message.textContent));
          assert(v.progressNote.textContent.includes('No network'));
          // A card tick that couldn't be saved still holds it.
          apiWrite = async () => { throw new Error('No network'); };
          main.querySelector('.pack-tick').click(); await settle();
          main.querySelector('.pack-tick').click(); await settle();
          assert(v.ticks.filter(t => t.tile).every(t => t.done));
          assert(v.progress.error); assert(!packCanFinish(v));
          assert(/save shared progress/i.test(v.finish.message.textContent));
        """)

    def test_tokens_step_is_outside_the_numbered_sequence(self):
        self.run_js("""
          const deck = tokened(); deck.kit = {need:1, warnings:[], deck_box:{id:'box', label:'Box', state:'linked', quantity:1}};
          openPlan([deck]); await settle();
          const step = tokenStep();
          assert(step.getAttribute('class').includes('is-optional'));
          assert.equal(step.querySelector('.pack-step-n').textContent, '');
          assert.equal(step.querySelector('.pack-step-spoken').textContent, 'Optional step. ');
          const numbers = main.querySelectorAll('.pack-step').filter(s => s !== step).map(s => s.querySelector('.pack-step-n').textContent);
          assert(numbers.length >= 2);
          assert.equal(numbers.join(), numbers.map((_, i) => i + 1).join());
        """)

    def test_tokens_that_cant_be_read_are_one_short_line(self):
        self.run_js("""
          const deck = item(); deck.tokens = {error:"Tokens couldn't be worked out; the server log has the details."};
          const v = openPlan([deck], {token_problems:["The token cards couldn't be read."]}); await settle();
          assert.equal(tokenStep().querySelectorAll('p').length, 1);
          assert.equal(tokenTicks().length, 0);
          checkCards(); await settle(); assert(packCanFinish(v));
        """)


class AssemblyTokensSourceTests(unittest.TestCase):
    def test_token_tiles_are_as_big_as_the_cards_and_a_blank_one_says_its_words_once(self):
        grid = (WEB / 'assembly.css').read_text(encoding='utf-8')
        self.assertIn('.card-tiles.pack-tiles, .card-tiles.pack-token-tiles { grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px)', grid)
        css = (WEB / 'assembly-tokens.css').read_text(encoding='utf-8')
        self.assertIn('.is-text .card-tile-name { display: none; }', css)
        self.assertIn('.is-text .tile-tick:not([aria-pressed="true"])::before { box-shadow: 0 0 0 2px var(--border-strong); }', css)
