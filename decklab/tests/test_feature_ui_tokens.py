"""The Tokens page, the token sheet and viewer, and the token parts of the deck page, library and
Packing plan, in the complete page's real script order.

Uses test_feature_ui's runner (its FeatureUiTests.run_js, with the packing plan's tick double)
and an event/DOM double, not a browser or real inventory writes.
"""
import unittest
from decklab.tests import test_feature_ui as feature_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class TokensUiTests(unittest.TestCase):
    run_js = feature_ui.FeatureUiTests.run_js

    # The token pieces' data: a deck's needs (lib/tokens deck_tokens) in every state, and GET /api/tokens.
    TOKENS = """
      const settle = async () => { for (let i = 0; i < 30; i++) await null; };
      const sheets = () => document.body.querySelectorAll('dialog');
      const button = (root, text) => root.querySelectorAll('button').find(b => b.textContent === text);
      const labelled = (root, label) => root.querySelectorAll('button').find(b => b.getAttribute('aria-label') === label);
      state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
      document.body.append(el('p', {id: 'toast'}));
      const card = (front, back, quantity, side, verdict, why = [], also_for = []) =>
        ({row: 0, front, back, side, quantity, verdict, why, also_for});
      const need = (name, state, words, extra = {}) => ({key: 'k-' + name, name, kind: 'token',
        type_line: 'Token Creature — ' + name, pt: '1/1', colors: ['G'], keywords: [], text: '', image: null, faces: [],
        made_by: [{name: 'Maker', quantity: 1, section: 'Deck'}], sideboard_only: false, state, words, usable: 0,
        on_the_way: 0, cards: [], stand_ins: [], incoming: [], ...extra});
      const needs = [
        need('Raccoon', 'none', 'None owned · closest: Rabbit / Rabbit ×2', {pt: '3/3', made_by:
          [{name: 'Sylvan Scavenging', quantity: 1, section: 'Deck'}, {name: 'B', quantity: 1, section: 'Deck'},
           {name: 'C', quantity: 1, section: 'Deck'}, {name: 'D', quantity: 1, section: 'Deck'}],
          stand_ins: [{row: 3, front: 'Rabbit', back: 'Rabbit', side: 'front', quantity: 2, why: ['a close name']}]}),
        need('Fish', 'incoming', 'None owned yet: 2 on the way (order 2026-10-07-shop-a)', {colors: ['U'],
          on_the_way: 2, incoming: [{order: '2026-10-07-shop-a', front: 'Fish', back: '', quantity: 2}]}),
        need('Insect', 'differs', "Different token: your card says no deathtouch; Hornet Queen's Insect has deathtouch",
          {keywords: ['Flying', 'Deathtouch'], stand_ins: [{row: 5, front: 'Insect', back: 'Goblin', side: 'front',
            quantity: 1, why: ["your card says no deathtouch; Hornet Queen's Insect has deathtouch"]}]}),
        need('Cat', 'check', 'Have 1 card with a Cat face; colour not recorded', {colors: ['W'],
          cards: [card('Elf Warrior', 'Cat', 1, 'back', 'check', ['colour not recorded'])]}),
        need('Zombie', 'ready', 'Have it: 8 cards', {pt: '2/2', colors: ['B'],
          cards: [card('Zombie', 'Zombie Knight', 8, 'front', 'agrees', [], ['The Monarch'])]}),
        need('Ooze', 'ready', 'Have it: 1 card', {sideboard_only: true,
          cards: [card('Ooze', '', 1, 'front', 'exact')]}),
      ];
      const deckTokensResult = {needs, copies: ['Gandalf, Westward Voyager'], unlisted: ['Elrond'],
        note: 'Worked out from Scryfall links.',
        counts: {kinds: 6, ready: 2, check: 1, differs: 1, incoming: 1, none: 1}};
      const row = (i, front, back, quantity, extra = {}) => {
        const r = {key: 'r' + i, index: i, front, back, set: '', front_collector_number: '', back_collector_number: '',
          finish: '', quantity, front_details: '', back_details: '', notes: 'User-reported owned; printing unconfirmed',
          single_sided: false, unconfirmed: true, uses: [], ...extra};
        r.faces = [{side: 'front', name: front, details: r.front_details, known: true, image: null}]
          .concat(back ? [{side: 'back', name: back, details: r.back_details, known: true, image: null}] : []);
        return r;
      };
      const zombie = row(0, 'Zombie', 'Zombie Knight', 8, {uses: [{deck: 'commander/gandalf',
        title: 'Gandalf and the Valley', token: 'Zombie', side: 'front', state: 'ready'}]});
      const insect = row(1, 'Insect', 'Goblin', 1, {front_details: '1/1; flying; no deathtouch', uses: [{deck:
        'commander/gandalf', title: 'Gandalf and the Valley', token: 'Insect', side: 'front', state: 'differs'}]});
      const goblin = row(2, 'Goblin', '', 1, {single_sided: true, unconfirmed: false,
        front_details: '1/1; printed pink (not a Magic colour)',
        notes: 'single-sided verified (back is an advertisement)'});
      const tokensData = {sha256: 'a'.repeat(64), exists: true, sorted: true, index_ready: true,
        rows: [zombie, insect, goblin], cards: 10,
        missing: [{key: 'x', name: 'Raccoon', kind: 'token', image: null, state: 'none',
          decks: [{id: 'commander/finneas', title: 'Finneas Rabbits'}], on_the_way: 0},
          {key: 'y', name: 'Axe', kind: 'token', image: null, state: 'incoming', decks: [], on_the_way: 5}],
        incoming: [{order: '2026-10-07-shop-a', component: 'tokens', path: 'magic/orders/tokens/x.csv', cards: 17,
          rows: [{front: 'Fish', back: '', quantity: 2, front_details: '1/1', back_details: ''}]}],
        face_names: ['Goblin', 'Insect', 'Spirit', 'The Monarch', 'Zombie', 'Zombie Knight'],
        problems: [], info: []};
    """

    def test_tokens_page_draws_and_filters(self):
        self.run_js(self.TOKENS + """
          clear(main);
          local.get = () => null; local.set = () => true;
          const view = drawTokens(tokensData, routeToken);
          const text = main.textContent;
          for (const words of ['Tokens', 'Add a token card', "Tokens your decks make that you don't have",
                               'Missing (1)', 'On the way (1)',
                               'Raccoon', 'Finneas Rabbits', 'Axe', '5 on the way', '17 cards', 'order 2026-10-07-shop-a',
                               'Receive this order', '×8', 'Gandalf and the Valley', 'To check (2)',
                               'printed pink (not a Magic colour)', 'Gandalf and the Valley · stand-in',
                               '3 kinds, 10 physical cards']) {
            assert(text.includes(words), words);
          }
          // Nothing about git: the tokens are saved in the database. No Edit/Remove pair on each card, and the
          // notes go into the sheet.
          for (const words of ['Retry saving history', 'change history', 'Commit', 'User-reported owned',
                               'Used for:']) assert(!text.includes(words), words);
          assert(labelled(main, 'Edit Zombie / Zombie Knight')); assert(labelled(main, 'Edit Goblin'));
          assert.equal(main.querySelectorAll('button').filter(b => b.textContent === 'Remove').length, 0);
          // "Details to check" is a chip only where a deck relies on a card whose details aren't recorded; rows that
          // are merely unconfirmed (most of them) stay plain, and the "To check (2)" filter finds them.
          assert.equal(main.querySelectorAll('.status-warn').filter(c => c.textContent === 'Details to check').length, 0);
          assert(tokToCheck({unconfirmed: false, uses: [{state: 'differs'}]}));     // a stand-in is to check too
          // The tiles are the "tokens" viewer group, for the sheet's Zoom.
          assert.equal(labelled(main, 'Edit Goblin').getAttribute('data-viewer'), 'tokens');
          // Busy: every write control is disabled.
          setTokensBusy(view, true);
          assert(view.root.querySelectorAll('.tok-mutate').every(c => c.disabled));
          setTokensBusy(view, false);
          // The filter: "Not used" shows only the Goblin; the search finds by either face.
          button(main, 'Not used').click();
          assert(main.textContent.includes('1 of 3 kinds')); assert(labelled(main, 'Edit Goblin'));
          assert(!labelled(main, 'Edit Zombie / Zombie Knight'));
          button(main, 'All').click();
          const search = main.querySelector('#tok-search'); search.value = 'knight'; search.fire('input');
          assert(labelled(main, 'Edit Zombie / Zombie Knight')); assert(!labelled(main, 'Edit Goblin'));
          search.value = ''; search.fire('input');
          button(main, 'To check (2)').click();
          assert(labelled(main, 'Edit Insect / Goblin')); assert(!labelled(main, 'Edit Goblin'));
          // An answer that comes after the page was left is dropped.
          let late; api = () => new Promise((resolve) => { late = resolve; });
          view.busy = false; view.message.textContent = '';
          const pending = refreshTokens(view); clear(main);
          late(tokensData); await pending;
          assert.equal(view.message.textContent, '');      // the answer was dropped
          // A deck relying on a card whose details aren't recorded: that tile has the chip.
          const relied = {...insect, uses: [{...insect.uses[0], state: 'check'}]};
          clear(main); drawTokens({...tokensData, rows: [zombie, relied, goblin]}, routeToken);
          assert.equal(main.querySelectorAll('.status-warn').filter(c => c.textContent === 'Details to check').length, 1);
          // With no token cards: no search, filters or "0 kinds" count, and the empty state's button isn't a
          // second primary.
          clear(main); const none = drawTokens({...tokensData, rows: [], cards: 0, missing: [], incoming: []}, routeToken);
          assert(none.tools.hidden);
          assert.equal(main.querySelectorAll('.btn-primary').length, 1);
          assert(!main.textContent.includes('0 kinds'));
        """)

    def test_token_viewer_shows_big_pictures_and_labels_example_art(self):
        self.run_js(self.TOKENS + """
          // The viewer gets the normal pictures (the small ones while they load), and example art says so in the
          // name the viewer shows over the picture.
          const vc = tokViewerCard({front: 'Angel', back: 'Clue', img: '/img/tm/1/small', back_img: '/img/tm/2/small'},
            'Printing not recorded', true);
          assert.equal(vc.img, '/img/tm/1/normal'); assert.equal(vc.img_small, '/img/tm/1/small');
          assert.equal(vc.faces[1].img, '/img/tm/2/normal');
          assert.equal(vc.name, 'Example art · Angel // Clue');
          assert(vc.type_line.startsWith('Example art: printing not recorded'));
          assert.equal(tokViewerCard({front: 'Bird', img: '/img/tm/3/small'}, 'TM 3').name, 'Bird');
          // Read only: a tile opens the viewer over the "tokens" group.
          clear(main); local.get = () => null; local.set = () => true;
          const realCan = canEditSpace; canEditSpace = () => false;
          drawTokens(tokensData, routeToken);
          canEditSpace = realCan;
          const open = main.querySelector('.tok-grid').querySelector('.card-tile-open');
          assert.equal(open.getAttribute('data-viewer'), 'tokens');
          open.click();
          assert.equal(inspections.length, 1);
          assert.equal(inspections[0].trigger, open);
          // The missing tokens' tiles are their own group.
          const missing = main.querySelector('.tok-missing').querySelector('.card-tile-open');
          assert.equal(missing.getAttribute('data-viewer'), 'tokens-missing');
        """)

    def test_token_sheet_suggests_names_and_marks_single_sided(self):
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          button(main, 'Add a token card').click();
          const sheet = sheets()[0]; assert(sheet); assert(sheet.textContent.includes('Add a token card'));
          const input = (key) => [...sheet.querySelectorAll('input'), ...sheet.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          const list = sheet.querySelector('datalist');
          same(list.querySelectorAll('option').map(o => o.getAttribute('value')), tokensData.face_names);
          assert.equal(input('front').getAttribute('list'), list.id);
          // A name a letter off: "Did you mean Spirit?", fixed with one tap.
          input('front').value = 'Sprit'; input('front').fire('blur');
          button(sheet, 'Did you mean Spirit?').click();
          assert.equal(input('front').value, 'Spirit');
          input('back').value = 'zombie knight'; input('back').fire('blur');
          assert(button(sheet, 'Did you mean Zombie Knight?'));
          // Single-sided (checked): the back is cleared and the notes say so; unticked, those words come off.
          const single = input('single'); single.checked = true; single.fire('change');
          assert.equal(input('back').value, ''); assert.equal(input('back').disabled, true);
          assert.equal(input('notes').value, 'single-sided verified');
          single.checked = false; single.fire('change');
          assert.equal(input('notes').value, ''); assert.equal(input('back').disabled, false);
          // Swap front and back.
          input('back').value = 'Faerie'; input('front_details').value = '2/2';
          button(sheet, 'Swap front and back').click();
          same([input('front').value, input('back').value, input('back_details').value], ['Faerie', 'Spirit', '2/2']);
          // A bad quantity is said, not sent.
          const bodies = [];
          apiWrite = async (path, body) => { bodies.push(body);
            return {saved: true, index: 0, data: tokensData,
              warnings: ['Names weren’t checked: card data is still loading']}; };
          input('quantity').value = '0';
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(bodies.length, 0); assert(sheet.textContent.includes('a whole number from 1 to 9999'));
          input('quantity').value = '2'; input('set').value = 'TLTR';
          sheet.querySelector('[data-action="save"]').click(); await settle();
          same(bodies[0], {action: 'add', sha256: 'a'.repeat(64), row: {front: 'Faerie', back: 'Spirit', set: 'tltr',
            front_collector_number: '', back_collector_number: '', finish: '', quantity: 2, front_details: '',
            back_details: '2/2', notes: ''}});
          assert.equal(sheets().length, 0);
          assert(main.textContent.includes('Faerie / Spirit added.'));
          assert(main.textContent.includes('Names weren’t checked'));
          // Editing a single-sided row starts ticked, and keeps its notes as they are.
          labelled(main, 'Edit Goblin').click();
          const edit = sheets()[0];
          const editInput = (key) => [...edit.querySelectorAll('input'), ...edit.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          assert.equal(editInput('single').checked, true);
          assert.equal(editInput('notes').value, 'single-sided verified (back is an advertisement)');
        """)

    def test_token_sheet_says_how_details_are_read(self):
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          labelled(main, 'Edit Goblin').click();
          const sheet = sheets()[0];
          const input = (key) => sheet.querySelectorAll('input').find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          const line = (n) => sheet.querySelectorAll('.tok-reading')[n];
          // The saved details, read: the P/T, and the printed colour kept but not compared.
          assert(line(0).textContent.startsWith('Read as: 1/1'));
          assert(line(0).textContent.includes("'printed pink (not a Magic colour)' is kept but not compared."));
          assert.equal(line(0).querySelectorAll('.note-warn').length, 0);
          assert.equal(line(1).textContent, '');
          // Typing redraws only the line: the field stays focused, and a likely mistake gets a fix.
          const details = input('front_details'); details.focus();
          details.value = '4/4 white flying'; details.fire('input');
          assert.equal(document.activeElement, details); assert.equal(input('front_details'), details);
          assert(line(0).textContent.includes("'4/4 white flying' isn't read: separate them with ';' (4/4; white; flying)."));
          button(line(0), 'Use 4/4; white; flying').click();
          assert.equal(details.value, '4/4; white; flying');
          assert.equal(line(0).textContent, 'Read as: 4/4 · white · flying');
          // A typo: "did you mean …?"; swapping the faces moves the lines with the text.
          input('single').checked = false; input('single').fire('change');
          input('back').value = 'Spirit';
          input('back_details').value = '2/2; deathtuch'; input('back_details').fire('input');
          assert(line(1).textContent.includes("'deathtuch' isn't read: did you mean deathtouch?"));
          button(sheet, 'Swap front and back').click();
          assert(line(0).textContent.includes("did you mean deathtouch?"));
          assert.equal(line(1).textContent, 'Read as: 4/4 · white · flying');
          // It never stops a save.
          const bodies = [];
          apiWrite = async (path, body) => { bodies.push(body); return {saved: true, index: 0, data: tokensData}; };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(bodies.length, 1); assert.equal(bodies[0].row.front_details, '2/2; deathtuch');
        """)

    def test_token_same_card_and_conflict_reapply(self):
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          const input = (root, key) => [...root.querySelectorAll('input'), ...root.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          // Adding a card that's already listed: "Add 2 to that card", or kept apart (both unconfirmed).
          button(main, 'Add a token card').click();
          let sheet = sheets()[0];
          input(sheet, 'front').value = 'Zombie'; input(sheet, 'back').value = 'Zombie Knight';
          input(sheet, 'quantity').value = '2';
          const bodies = [];
          apiWrite = async (path, body) => {
            bodies.push(body);
            if (bodies.length === 1) throw new ApiError(409,
              'That card is already listed (Zombie / Zombie Knight ×8). Add to its quantity instead?',
              {same_row: {index: 0, row: tokBase(zombie)}});
            return {saved: true, index: 0, data: tokensData, warnings: []};
          };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert(sheet.textContent.includes('already listed'));
          assert(button(sheet, 'Keep it as a separate card'));
          button(sheet, 'Add 2 to that card').click(); await settle();
          assert.equal(bodies[1].action, 'edit');
          same(bodies[1].base, tokBase(zombie));
          assert.equal(bodies[1].row.quantity, 10); assert.equal(bodies[1].row.front, 'Zombie');
          assert.equal(sheets().length, 0);
          // Two fully known cards are the same card for sure: no "separate" offer.
          const known = {...tokBase(zombie), set: 'tfdn', front_collector_number: '1', back_collector_number: '2',
            finish: 'nonfoil', notes: ''};
          assert(tokKnown(known)); assert(!tokKnown(tokBase(zombie)));
          // Editing a row while someone else changed another: my change goes back on top of the latest.
          labelled(main, 'Edit Insect / Goblin').click();
          sheet = sheets()[0];
          input(sheet, 'notes').value = 'Checked again';
          const latest = {...tokensData, sha256: 'e'.repeat(64), rows: [{...zombie, quantity: 9}, insect]};
          const sent = [];
          apiWrite = async (path, body) => {
            sent.push(body);
            if (sent.length === 1) throw new ApiError(409, 'User1 saved it in Deck Lab.',
              {conflict: {reason: 'changed', by: 'User1', when: new Date().toISOString()}, latest});
            return {saved: true, index: 1, data: latest, warnings: []};
          };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(sent[0].action, 'edit'); same(sent[0].base, tokBase(insect));
          assert(sheet.textContent.includes('User1 changed the tokens list'));
          button(sheet, 'Load the latest and re-apply my changes').click(); await settle();
          assert.equal(sent[1].sha256, 'e'.repeat(64));
          assert.equal(sent[1].row.notes, 'Checked again');
          assert.equal(sent[1].row.quantity, 1);
          assert.equal(sheets().length, 0);
          // The row removed meanwhile: adding it back is offered only as an explicit add of my values.
          labelled(main, 'Edit Insect / Goblin').click();
          sheet = sheets()[0];
          const gone = {...tokensData, sha256: 'f'.repeat(64), rows: [zombie]};
          sent.length = 0;
          apiWrite = async (path, body) => { sent.push(body);
            if (sent.length === 1) throw new ApiError(409, 'Changed.', {conflict: {reason: 'deleted'}, latest: gone});
            return {saved: true, index: 1, data: gone, warnings: []}; };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert(sheet.textContent.includes('removed from the list since you opened it'));
          assert(!button(sheet, 'Add it again'));
          button(sheet, 'Add Insect / Goblin ×1 as a new card').click(); await settle();
          assert.equal(sent[1].action, 'add'); assert.equal(sent[1].base, undefined);
          // Removing asks, with an optional reason that's sent; one removed meanwhile is "Already removed."
          clear(main);
          const view = drawTokens(tokensData, routeToken);
          sent.length = 0;
          apiWrite = async (path, body) => { sent.push(body);
            throw new ApiError(409, 'Changed.', {conflict: {reason: 'deleted'}, latest: {...tokensData, rows: [zombie, insect]}}); };
          const done = removeToken(view, goblin); await settle();
          const askSheet = sheets()[0];
          assert(askSheet.textContent.includes('For a partial loss, use Edit to lower the quantity.'));
          askSheet.querySelectorAll('input')[0].value = 'traded';
          button(askSheet, 'Remove').click(); await done;
          assert.equal(sent[0].action, 'remove'); assert.equal(sent[0].reason, 'traded');
          same(sent[0].base, tokBase(goblin));
          assert(main.textContent.includes('Already removed.'));
        """)

    def test_token_conflict_on_a_row_someone_else_changed(self):
        # Review findings 4/9 and 8: a row edited meanwhile (no exact match in the latest list) is found
        # again and rebased onto, never treated as removed or turned into an add.
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          const input = (root, key) => [...root.querySelectorAll('input'), ...root.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          // User1 lowered the Zombie to ×7 while Matt edits its quantity to ×9: a quantity clash to choose.
          const zombie7 = {...zombie, quantity: 7, notes: 'One lost'};
          const latest = {...tokensData, sha256: 'e'.repeat(64), rows: [zombie7, insect, goblin]};
          labelled(main, 'Edit Zombie / Zombie Knight').click();
          let sheet = sheets()[0];
          input(sheet, 'quantity').value = '9';
          const sent = [];
          apiWrite = async (path, body) => { sent.push(body);
            if (sent.length === 1) throw new ApiError(409, 'User1 saved it in Deck Lab.',
              {conflict: {reason: 'changed', by: 'User1', when: new Date().toISOString()}, latest});
            return {saved: true, index: 0, data: latest, warnings: []}; };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert(!button(sheet, 'Add it again'));
          assert(!sheet.textContent.includes('as a new card'));
          assert(sheet.textContent.includes('Quantity 8 → 7'));
          assert(sheet.textContent.includes('You both changed these'));
          button(sheet, 'Save with these choices').click(); await settle();
          assert.equal(sent[1].action, 'edit');
          same(sent[1].base, tokBase(zombie7));
          assert.equal(sent[1].row.quantity, 9); assert.equal(sent[1].row.notes, 'One lost');
          assert.equal(sheets().length, 0);
          // The same with the older server's reason "deleted": the changed row is still found.
          clear(main);
          drawTokens(tokensData, routeToken);
          labelled(main, 'Edit Zombie / Zombie Knight').click();
          sheet = sheets()[0];
          input(sheet, 'notes').value = 'Sleeved';
          sent.length = 0;
          apiWrite = async (path, body) => { sent.push(body);
            if (sent.length === 1) throw new ApiError(409, 'Changed.', {conflict: {reason: 'deleted'}, latest});
            return {saved: true, index: 0, data: latest, warnings: []}; };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert(!sheet.textContent.includes('as a new card'));
          assert(sheet.textContent.includes('Notes'));
          button(sheet, 'Discard my changes').click(); await settle();
          assert.equal(sheets().length, 0);
          // Two candidates for one changed row: nothing is guessed, only discard is offered.
          clear(main);
          drawTokens(tokensData, routeToken);
          labelled(main, 'Edit Zombie / Zombie Knight').click();
          sheet = sheets()[0];
          input(sheet, 'notes').value = 'Sleeved';
          const two = {...tokensData, sha256: 'd'.repeat(64), rows: [{...zombie, quantity: 3}, {...zombie, quantity: 5}, insect, goblin]};
          sent.length = 0;
          apiWrite = async (path, body) => { sent.push(body);
            throw new ApiError(409, 'Changed.', {conflict: {reason: 'changed'}, latest: two}); };
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert(sheet.textContent.includes("can't be told for sure"));
          same(sheet.querySelectorAll('button').map(b => b.textContent).filter(t => t !== '×'), ['Discard my changes']);
          // The server's base_state and current pick the changed row.
          assert.equal(tokLocate([zombie7, {...zombie, quantity: 5}], tokBase(zombie),
            {base_state: 'changed', current: {index: 0, row: tokBase(zombie7)}}, [zombie]).row, zombie7);
          // tokLocate on its own: same, changed, unsure, gone, and "changed" with nothing found is never gone.
          assert.equal(tokLocate([zombie], tokBase(zombie), null, null).state, 'same');
          assert.equal(tokLocate([zombie7], tokBase(zombie), {reason: 'deleted'}, [zombie]).state, 'changed');
          assert.equal(tokLocate([insect], tokBase(zombie), {reason: 'deleted'}, [zombie, insect]).state, 'gone');
          assert.equal(tokLocate([insect], tokBase(zombie), {reason: 'changed'}, [zombie, insect]).state, 'unsure');
          // An unchanged row with the same names that was already there isn't taken for the changed one.
          const zombieB = {...zombie, set: 'tfdn', front_collector_number: '1', back_collector_number: '2', quantity: 1};
          assert.equal(tokLocate([zombieB], tokBase(zombie), {reason: 'deleted'}, [zombie, zombieB]).state, 'gone');
        """)

    def test_token_remove_conflict_on_a_changed_row(self):
        # Review findings 4/9: removing a row someone else edited isn't "Already removed".
        self.run_js(self.TOKENS + """
          clear(main);
          const view = drawTokens(tokensData, routeToken);
          const zombie7 = {...zombie, quantity: 7};
          const latest = {...tokensData, sha256: 'e'.repeat(64), rows: [zombie7, insect, goblin]};
          const sent = [];
          apiWrite = async (path, body) => { sent.push(body);
            if (sent.length === 1) throw new ApiError(409, 'Changed.', {conflict: {reason: 'deleted'}, latest});
            return {saved: true, index: null, data: {...latest, rows: [insect, goblin]}, warnings: []}; };
          const done = removeToken(view, zombie); await settle();
          button(sheets()[0], 'Remove').click(); await settle();
          assert(!main.textContent.includes('Already removed.'));
          const confirm = sheets()[0];
          assert(confirm.textContent.includes('Quantity 8 → 7'));
          button(confirm, 'Remove Zombie / Zombie Knight ×7 as it is now').click(); await done;
          assert.equal(sent.length, 2);
          same(sent[1].base, tokBase(zombie7)); assert.equal(sent[1].sha256, 'e'.repeat(64));
          assert(main.textContent.includes('Zombie / Zombie Knight removed.'));
        """)

    def test_token_single_sided_untick_strips_existing_words(self):
        # Review finding 11: unticking a row that already said single-sided verified takes the words off.
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          labelled(main, 'Edit Goblin').click();
          const sheet = sheets()[0];
          const input = (key) => [...sheet.querySelectorAll('input'), ...sheet.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          assert.equal(input('single').checked, true);
          input('single').checked = false; input('single').fire('change');
          assert(!/single-sided verified/i.test(input('notes').value));
          assert.equal(input('notes').value, '(back is an advertisement)');
          assert.equal(tokDropSingle('printing unconfirmed; single-sided verified; checked'), 'printing unconfirmed; checked');
          assert.equal(tokDropSingle('single-sided verified'), '');
        """)

    def test_token_focus_follows_the_saved_row(self):
        # Review finding 12: after a save re-sorts the file, focus goes to the saved row's new place.
        self.run_js(self.TOKENS + """
          clear(main);
          drawTokens(tokensData, routeToken);
          labelled(main, 'Edit Goblin').click();
          const sheet = sheets()[0];
          const input = (key) => [...sheet.querySelectorAll('input'), ...sheet.querySelectorAll('textarea')].find(i => i.id && i.id.startsWith('tok-' + key + '-'));
          input('front').value = 'Angel';
          const angel = {...goblin, key: 'r0', index: 0, front: 'Angel'};
          const after = {...tokensData,
            rows: [angel, {...zombie, key: 'r1', index: 1}, {...insect, key: 'r2', index: 2}]};
          apiWrite = async () => ({saved: true, index: 0, data: after, warnings: []});
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(sheets().length, 0);
          assert.equal(document.activeElement.getAttribute('aria-label'), 'Edit Angel');
        """)

    def test_token_save_whose_list_couldnt_be_shown(self):
        # A save that answers data: null (saved, list not rebuilt) keeps the old list and says so.
        self.run_js(self.TOKENS + """
          clear(main);
          const view = drawTokens(tokensData, routeToken);
          const warn = "Saved, but the tokens list couldn't be shown again; reload the page";
          apiWrite = async () => ({saved: true, index: null, data: null, warnings: [warn]});
          const done = removeToken(view, zombie); await settle();
          button(sheets()[0], 'Remove').click(); await done;
          assert(main.textContent.includes('Zombie / Zombie Knight removed.'));
          assert(main.textContent.includes(warn));
          assert.equal(view.data.rows.length, tokensData.rows.length);
          assert.equal(view.busy, false);
          labelled(main, 'Edit Insect / Goblin').click();
          const sheet = sheets()[0];
          sheet.querySelector('[data-action="save"]').click(); await settle();
          assert.equal(sheets().length, 0);
          assert(main.textContent.includes(warn));
        """)

    def test_token_links_to_intact_products(self):
        # Review finding 5: a whole intact product's id isn't a deck id, so it links to the library's products.
        self.run_js(self.TOKENS + """
          assert.equal(tokHolderHref('product/blb-starter-kit'), '#/library?format=product');
          assert.equal(tokHolderHref('product/fdn-beginner-box/cats'), deckHref('product/fdn-beginner-box/cats'));
          assert.equal(tokHolderHref('commander/gandalf'), deckHref('commander/gandalf'));
          // The server's link: the deck id to open, or null for a product whose decks are named.
          assert.equal(tokHolderHref('product/lightning-aggro', 'product/lightning-aggro'), deckHref('product/lightning-aggro'));
          assert.equal(tokHolderHref('product/blb-starter-kit', null), '#/library?format=product');
          assert.equal(tokHolderHref('casual/otters', 'casual/otters'), deckHref('casual/otters'));
          clear(main);
          drawTokens({...tokensData, rows: [{...zombie, uses: [{deck: 'product/blb-starter-kit',
            title: 'Bloomburrow Starter Kit', token: 'Zombie', side: 'front', state: 'ready'}]}]}, routeToken);
          const link = main.querySelectorAll('a').find(a => a.textContent === 'Bloomburrow Starter Kit');
          assert.equal(link.getAttribute('href'), '#/library?format=product');
        """)

    def test_deck_page_tokens_section_and_header_chip(self):
        self.run_js(self.TOKENS + """
          clear(main);
          const section = tokensSection({tokens: deckTokensResult});
          main.append(section);
          const text = section.textContent;
          for (const words of ['Tokens and reminders', "2 ready · 1 to check · 1 different · 1 on the way · 1 you don't have",
                               'Raccoon 3/3 green creature', 'Made by Sylvan Scavenging, B ', 'and 2 more',
                               'None owned · closest: Rabbit / Rabbit ×2', 'Stand-ins', 'Rabbit / Rabbit ×2, Rabbit side',
                               'On the way: Fish ×2 (order 2026-10-07-shop-a)', 'None owned yet: 2 on the way',
                               'Insect 1/1 green creature with flying, deathtouch',
                               'Different token: your card says no deathtouch',
                               'Grab Elf Warrior / Cat ×1, Cat side', 'colour not recorded',
                               'Grab Zombie / Zombie Knight ×8, Zombie side only, can be sleeved (same card as for The Monarch)',
                               'Have it: 8 cards', 'Only for sideboard cards', 'Grab Ooze ×1', 'Makes copies: 1 card',
                               'Gandalf, Westward Voyager', "May also make things Scryfall doesn't link: 1 card", 'Elrond',
                               'Edit your tokens']) {
            assert(text.includes(words), words);
          }
          assert.equal(section.id, 'sec-tokens');
          assert(section.querySelector('.token-note'));
          assert.equal(section.querySelectorAll('.token-needs').length, 2);     // the sideboard's group apart
          // No tokens, unavailable, or an error: one line each; a pairing (null) has no part.
          for (const [tokens, words] of [[{needs: [], copies: [], unlisted: [], note: 'n', counts: {kinds: 0}},
                                          'No tokens or reminders are linked'],
                                         [{unavailable: 'Token data is being rebuilt; refresh in a minute.'}, 'being rebuilt'],
                                         [{error: 'Tokens couldn’t be worked out.'}, 'worked out']]) {
            const part = tokensSection({tokens});
            assert(part.textContent.includes(words), words);
            assert.equal(part.querySelectorAll('li').length, 0);
          }
          assert.equal(tokensSection({tokens: null}), null);
          // The Overview's chip: only when a kind has none or a different card, and a jump to the part on the
          // Cards tab. Nothing when every token is covered (WP7: chips only for problems).
          const chip = deckTokensChip({tokens: deckTokensResult});
          assert.equal(chip.textContent, 'No Raccoon token · Insect token differs');
          // A token and a reminder missing: the token names keep "tokens", the reminder is named by itself.
          assert.equal(deckTokensChip({tokens: {needs: [{name: 'Dragon', kind: 'token', state: 'none'},
            {name: 'Treasure', kind: 'token', state: 'none'}, {name: 'The Monarch', kind: 'reminder', state: 'none'}],
            counts: {kinds: 3, none: 3}}}).textContent, 'No Dragon or Treasure tokens, The Monarch');
          assert.equal(deckTokensChip({tokens: {counts: {kinds: 2, none: 2}}}).textContent, "2 tokens you don't have");
          assert(chip.querySelector('.status-warn'));
          let opened = null; openDeckTab = (tab, opts) => { opened = [tab, opts.to]; };
          chip.querySelector('button').click(); same(opened, ['cards', 'sec-tokens']);
          assert.equal(deckTokensChip({tokens: {...deckTokensResult, counts: {kinds: 0}}}), null);
          assert.equal(deckTokensChip({tokens: {...deckTokensResult, counts: {kinds: 2, ready: 2}}}), null);
          assert.equal(deckTokensChip({tokens: {...deckTokensResult, counts: {kinds: 2, ready: 1, incoming: 1}}}), null);
          assert.equal(tokenStateChip('none').textContent, 'None owned');
        """)

    def test_deck_page_packed_token_cards_and_their_sheet(self):
        self.run_js(self.TOKENS + """
          clear(main);
          const packed = {written: true, expect: 'b'.repeat(64), tokens_sha256: 'a'.repeat(64),
            lines: [{text: '2 Zombie // Zombie Knight', quantity: 2, rows: [{row: 0, front: 'Zombie', back: 'Zombie Knight', quantity: 2}]},
                    {text: '1 Treasure', quantity: 1, rows: []}],
            choices: [{row: 0, front: 'Zombie', back: 'Zombie Knight', set: '', number: '', quantity: 8, free: 6, packed: 2}]};
          const used = need('Spirit', 'none', 'All yours are packed in Other Deck', {in_use: [{row: 4, front: 'Spirit',
            back: '', side: 'front', quantity: 1, decks: ['Other Deck']}]});
          const data = {summary: {id: 'casual/zed', player: 'user'}, tokens: {...deckTokensResult, packed,
            needs: [...deckTokensResult.needs, used]}};
          const section = tokensSection(data);
          main.append(section);
          const text = section.textContent;
          for (const words of ['Packed: 2 Zombie // Zombie Knight (Zombie side only, can be sleeved); 1 Treasure (no token card matches)',
                               'In use: Spirit ×1, packed in Other Deck', 'All yours are packed in Other Deck']) {
            assert(text.includes(words), words);
          }
          const sent = [];
          apiWrite = async (path, body) => { sent.push([path, body]); return {saved: true}; };
          route = () => {};
          button(section, 'Change packed token cards…').click();
          const sheet = sheets()[sheets().length - 1];
          assert(sheet.textContent.includes('Zombie / Zombie Knight: 8 cards, 2 in other decks'));
          const input = sheet.querySelector('input');
          assert.equal(input.value, '2');
          input.value = '9';
          button(sheet, 'Save').click(); await settle();
          assert.equal(sent.length, 0);                          // more than other decks leave
          assert(sheet.textContent.includes('Choose 0 to 6 for Zombie.'));
          input.value = '3';
          button(sheet, 'Save').click(); await settle();
          same(sent, [['/api/deck/token-cards', {id: 'casual/zed', expect: 'b'.repeat(64), tokens_sha256: 'a'.repeat(64),
            cards: [{row: 0, quantity: 3}]}]]);
          // Nothing to choose from, or the line can't be read: no button.
          assert(!button(tokensSection({...data, tokens: {...data.tokens, packed: {...packed, choices: []}}}),
            'Change packed token cards…'));
          const bad = tokensSection({...data, tokens: {...data.tokens, packed: {...packed, error: 'bad part'}}});
          assert(bad.textContent.includes("The Token cards line can't be read: bad part"));
          assert(!button(bad, 'Change packed token cards…'));
          // The Tokens page: a row's packed decks and the warning's words when a deck packs several.
          const row0 = {...zombie, packed: [{deck: 'casual/a', title: 'A Deck', link: 'casual/a', quantity: 8}],
            shared: [{deck: 'casual/a', title: 'A Deck', link: 'casual/a', quantity: 8},
                     {deck: 'casual/b', title: 'B Deck', link: 'casual/b', quantity: 1}]};
          assert.equal(tokSharedWords(row0), 'Only 8 cards, but built decks pack 9: A Deck ×8 and B Deck.');
          assert.equal(tokSharedWords({...row0, quantity: 1, shared: row0.shared.map(h => ({...h, quantity: 1}))}),
            "Only 1 card, used by 2 built decks: A Deck and B Deck. They can't all have one packed.");
          assert.equal(tokenStateChip('in_use').textContent, 'Packed in other decks');
        """)

    def test_double_sided_token_cards_say_whether_both_sides_are_used(self):
        self.run_js(self.TOKENS + """
          // One row, Zombie / Zombie Knight, used for both its faces: both sides are needed, so no sleeve.
          const zk = need('Zombie Knight', 'ready', 'Have it: 8 cards', {cards: [card('Zombie', 'Zombie Knight', 8, 'back', 'agrees')]});
          const both = [needs[4], zk];
          const faces = tokFacesUsed(both);
          assert.equal(tokSides({row: 0, front: 'Zombie', back: 'Zombie Knight'}, faces), 'both sides used');
          assert.equal(tokSides({row: 0, front: 'Ooze', back: ''}, faces), null);           // single-sided
          assert.equal(tokSides({row: 7, front: 'Zombie', back: 'Zombie Knight'}, faces), null);   // not this deck's
          assert.equal(tokSides({row: 0, front: 'Zombie', back: 'Zombie Knight'}, tokFacesUsed([needs[4]])),
            'Zombie side only, can be sleeved');
          // Rabbit / Rabbit is one face, whichever side is up.
          const rabbits = [need('Rabbit', 'ready', '', {cards: [card('Rabbit', 'Rabbit', 2, 'front', 'exact')]}),
                           need('Rabbit', 'ready', '', {key: 'k-r2', cards: [card('Rabbit', 'Rabbit', 2, 'back', 'exact')]})];
          assert.equal(tokSides({row: 0, front: 'Rabbit', back: 'Rabbit'}, tokFacesUsed(rabbits)), 'Rabbit side only, can be sleeved');
          clear(main);
          const packed = {written: true, expect: 'b'.repeat(64), tokens_sha256: 'a'.repeat(64), choices: [],
            lines: [{text: '2 Zombie // Zombie Knight', quantity: 2, rows: [{row: 0, front: 'Zombie', back: 'Zombie Knight', quantity: 2}]}]};
          const section = tokensSection({summary: {id: 'casual/zed', player: 'user'}, tokens: {...deckTokensResult, needs: both, packed}});
          const text = section.textContent;
          for (const words of ['Packed: 2 Zombie // Zombie Knight (both sides used)',
                               'Grab Zombie / Zombie Knight ×8, Zombie side (both sides used)',
                               'Grab Zombie / Zombie Knight ×8, Zombie Knight side (both sides used)']) {
            assert(text.includes(words), words);
          }
          const ticks = assemblyTokenTasks({needs: both}).map(li => li.textContent);
          assert(ticks.some(t => t.includes('Grab Zombie / Zombie Knight ×8 (Zombie side; both sides used) for Zombie')), ticks);
          assert(ticks.some(t => t.includes('(Zombie Knight side; both sides used) for Zombie Knight')), ticks);
        """)

    def test_library_token_chips_only_when_something_is_wrong(self):
        self.run_js("""
          state.profile = {id:'matt',name:'Matt',plays_as:'user'}; state.profiles=[state.profile];
          assert.equal(deckTokens(null), null);
          assert.equal(deckTokens({kinds: 4, none: [], differs: [], incoming: []}), null);
          same(deckTokens({kinds: 5, none: ['Raccoon', 'Ape', 'Bird'], differs: ['Insect'], incoming: ['Fish']})
            .querySelectorAll('.status').map(s => s.textContent),
            ['No Raccoon, Ape or Bird tokens', 'Insect token differs', 'Fish token on the way']);
          clear(main);
          const base = {format:'Casual 60',kind:'casual',player:'user',status:'building',versions:['target'],
            missing:{target:0},on_the_way:{target:0},card_count:60,sideboard_count:0,kit:null};
          drawLibrary({warnings:[],halves:[],decks:[
            {...base,id:'casual/otters',title:'Otters',tokens:{kinds:2,none:['Raccoon'],differs:[],incoming:[]}},
            {...base,id:'casual/gruul',title:'Gruul',tokens:{kinds:2,none:[],differs:[],incoming:[]}},
            {...base,id:'casual/idea',title:'Idea',tokens:null}]},libraryFilters(new URLSearchParams('all=1')));
          const cards = main.querySelectorAll('.deck-card');
          assert(cards.find(c => c.textContent.includes('Otters')).textContent.includes('No Raccoon token'));
          assert.equal(cards.find(c => c.textContent.includes('Gruul')).querySelector('.deck-tokens'), null);
          assert.equal(cards.find(c => c.textContent.includes('Idea')).querySelector('.deck-tokens'), null);
        """)

    def test_assembly_token_lines_and_shared_tokens(self):
        self.run_js(self.TOKENS + """
          clear(main);
          const deck = (id, title, tokens) => ({id, title, version:'target', sleeves:'Not recorded', kit:null,
            sleeves_need:null, need:{}, current:[], basics:[], steps:[], returns:[], tokens});
          drawAssembly({choices:[],rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],note:'',
            token_note:'Packing ticks don’t reserve or change inventory.',totals:{waiting:0,missing:0},
            token_problems:['magic/tokens.csv line 4: bad'],
            tokens:[{quantity:8,front:'Zombie',back:'Zombie Knight',notes:'',key:'2'}],
            token_plan:[{row:0,front:'Zombie',back:'Zombie Knight',quantity:8,wanted_by:[
              {deck:'casual/a',title:'Otters',token:'Zombie',side:'front'},
              {deck:'casual/b',title:'Gandalf',token:'Zombie Knight',side:'back'}]}],
            token_plan_note:'Both decks can use these cards.',
            decks:[deck('casual/a','Otters',deckTokensResult), deck('casual/b','Gandalf',null),
                   deck('casual/c','Other',{unavailable:'Token data is being rebuilt; refresh in a minute.'})]},routeToken);
          const text = main.textContent;
          for (const words of ['Grab Zombie / Zombie Knight ×8 (Zombie side only, can be sleeved) for Zombie',
                               'Grab Elf Warrior / Cat ×1 (Cat side only, can be sleeved) for Cat (details not recorded)',
                               "Stand-in for Insect: Insect / Goblin ×1 (your card says no deathtouch; Hornet Queen's Insect has deathtouch; Insect side only, can be sleeved; tell your opponent)",
                               'No Raccoon token: use a stand-in (a spare token card or a die)',
                               'No Fish token yet: 2 on the way', 'Check by hand: Gandalf, Westward Voyager, Elrond',
                               'Token data is being rebuilt', 'Shared tokens', 'Both decks can use these cards.',
                               'Zombie for Otters (Zombie side); Zombie Knight for Gandalf (Zombie Knight side)',
                               'All your token cards (1)', 'magic/tokens.csv line 4: bad']) {
            assert(text.includes(words), words);
          }
          // What's missing or on the way is never a tick.
          const ticks = main.querySelectorAll('label').map(l => l.textContent);
          assert(!ticks.some(t => t.includes('Raccoon') || t.includes('Fish')));
          assert(main.querySelectorAll('a').some(a => a.getAttribute('href') === '#/tokens'));
          // No shared cards: no "Shared tokens" panel.
          clear(main);
          drawAssembly({choices:[],rows:[],ready:true,counts_confirmed:true,unresolved:[],warnings:[],note:'',
            token_note:'',totals:{waiting:0,missing:0},tokens:[],token_plan:[],decks:[deck('casual/a','Otters',null)]},routeToken);
          assert(!main.textContent.includes('Shared tokens'));
        """)
