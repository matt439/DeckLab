"""The pregame summary uses the shown list and never certifies a bracket.

Real page scripts over the event/DOM double; fixture cards only, no writes.
"""
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


SETUP = PAGE + """
  const announced = {date:'2026-02-09', url:'https://magic.wizards.com/en/news/announcements/commander-brackets-beta-update-february-9-2026'};
  const officialData = {official_announcement:announced, official_checked:'2026-10-14', official_unknown:false,
    rules_date:'2026-02-09', cards_older_than_announcement:false, rules_older_than_announcement:false};
  const readinessPage = (changes = {}) => {
    const data = makePage();
    data.summary = {...data.summary, id:'commander/test', kind:'commander', target_bracket:2};
    data.stats = {commander:{ok:true, bracket:{minimum:1, label:'Bracket 1 or 2 (theme and intent decide)',
      game_changers:[], mass_land_denial:[], extra_turns:[], unknown_cards:[],
      combos:{checked:true, list_date:'2026-10-14T03:14:00+00:00', version:'7.3.0', matches:[]},
      data:{cards_date:'2026-10-14', tags_date:'2026-10-13', combos_date:'2026-10-14', stale:false, dates_stale:false,
        max_age_days:7, ...officialData},
      ...changes}}};
    return data;
  };
  const showReadiness = (data) => {
    clear(main); location.hash = '#/deck?id=commander/test'; drawDeck(data);
    return panel('overview').querySelector('.commander-readiness');
  };
  const summaryText = (node) => node.querySelector('.commander-table-summary').textContent;
  const combo = (names, changes = {}) => ({names, results:['Infinite damage','Infinite lifegain','Infinite storm count'],
    class:'infinite', standalone:true, raises_floor:true, floor:3, url:'https://commanderspellbook.com/combo/1-2/', ...changes});
  const listed = (minimum, matches, changes = {}) => readinessPage({minimum, cards_minimum:1,
    combos:{checked:true, list_date:'2026-10-14T03:14:00+00:00', version:'7.3.0', matches}, ...changes});
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CommanderReadinessUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_clean_summary_is_first_and_distinguishes_aim_from_certification(self):
        self.run_js("""
          const node = showReadiness(readinessPage());
          assert.equal(panel('overview').children[0], node);
          assert.equal(summaryText(node), 'Aims for Bracket 2: no Game Changers, extra turns, mass land denial or two-card combos found.');
          assert(node.textContent.includes("Combos of three or more cards, combos needing a card that isn't named, chained or repeated extra turns"));
          assert(node.textContent.includes("Only two-card combos from Commander Spellbook's list are checked, and the list can miss some."));
          assert(node.textContent.includes("Two-card combos: none found in Commander Spellbook's two-card combos (list of 2026-10-14)."));
          assert(node.textContent.includes("Commander Spellbook's two-card combos: 2026-10-14."));
          assert(node.textContent.includes("these card checks alone don't establish a bracket"));
          assert(node.textContent.includes('at least eight turns'));
          assert(node.textContent.includes('A few extra-turn cards can fit'));
          assert.equal(node.querySelector('details').querySelector('summary').textContent, 'What opponents will face');
          assert(!node.querySelector('details').open);
          assert(node.textContent.includes('Scryfall card data (Game Changers and ban list): 2026-10-14'));
          assert(node.textContent.includes('Community effect tags: 2026-10-13'));
          assert(!node.textContent.includes('may be out of date'));
        """)

    def test_named_raising_cards_and_effects_open_the_existing_viewer(self):
        self.run_js("""
          const node = showReadiness(readinessPage({minimum:4, game_changers:[{name:'Elf',qty:1}],
            mass_land_denial:[{name:'Bolt',qty:1}], extra_turns:[{name:'Elf',qty:1}]}));
          assert(summaryText(node).includes('Aims for Bracket 2; the cards found require at least Bracket 4.'));
          assert(summaryText(node).includes('Game Changers: Elf. Mass land denial: Bolt. Extra turns: Elf.'));
          assert.equal(node.querySelector('details').open, true);
          let opened;
          openCardViewer = (items, start) => { opened = [items.map(i => i.card.name), start]; };
          const link = node.querySelector('[role=button]');
          assert.equal(link.getAttribute('data-viewer'),'commander-readiness');
          link.click();
          same(opened, [['Elf','Bolt'],0]);
        """)

    def test_single_extra_turn_is_disclosed_without_raising_bracket_two(self):
        self.run_js("""
          const node = showReadiness(readinessPage({minimum:2,extra_turns:[{name:'Elf',qty:1}]}));
          assert(summaryText(node).includes('Aims for Bracket 2. Extra turns: Elf.'));
          assert(!summaryText(node).includes('require at least'));
          assert(node.textContent.includes('chaining them cannot'));
        """)

    def test_missing_tags_and_unknown_names_never_get_an_all_clear_sentence(self):
        self.run_js("""
          const noTags = showReadiness(readinessPage({mass_land_denial:null,extra_turns:null}));
          assert.equal(summaryText(noTags), 'Aims for Bracket 2: the card checks are incomplete.');
          assert(noTags.textContent.includes('Mass land denial: not checked'));
          assert(noTags.textContent.includes('Extra turns: not checked'));
          const data = readinessPage({unknown_cards:['Mystery Card']});
          data.stats.commander.ok = false;
          const unknown = showReadiness(data);
          assert(summaryText(unknown).includes('incomplete'));
          assert(unknown.textContent.includes('Cards without data: Mystery Card'));
          assert(unknown.textContent.includes('Deck rules need attention'));
          const missing = readinessPage(); missing.stats = null;
          assert(showReadiness(missing).textContent.includes('Commander checks are unavailable'));
        """)

    def test_a_raising_combo_is_named_in_the_lead_and_listed_with_its_link(self):
        self.run_js("""
          const node = showReadiness(listed(3, [combo(['Elf','Bolt'])]));
          // Holding both pieces is never called a requirement: intent isn't checked.
          assert.equal(summaryText(node), "Aims for Bracket 2; a two-card combo it holds puts it at Bracket 3 or higher, " +
            "unless the combo isn't intended. Holds both pieces of a two-card combo: Elf + Bolt.");
          assert(!summaryText(node).includes('require'));
          const effects = node.querySelector('details');
          assert.equal(effects.open, true);
          assert(effects.textContent.includes('Two-card combos: the list holds both pieces of this combo ' +
            "(Commander Spellbook's two-card combos, list of 2026-10-14)."));
          const item = effects.querySelector('.commander-combos').children[0];
          assert.equal(item.textContent, 'Elf + Bolt: Infinite damage, Infinite lifegain, …. None in Brackets 1-2. Commander Spellbook');
          const link = item.querySelector('a');
          same([link.getAttribute('href'), link.getAttribute('target'), link.getAttribute('rel')],
            ['https://commanderspellbook.com/combo/1-2/','_blank','noopener']);
          assert(!node.textContent.includes('breach'));
          const two = showReadiness(listed(4, [combo(['Elf','Bolt']), combo(['Bolt','Wurm'], {floor:4, class:'mass_land_denial'})]));
          assert(summaryText(two).startsWith("Aims for Bracket 2; the two-card combos it holds put it at Bracket 4 or higher, " +
            "unless they aren't intended."));
          assert(summaryText(two).includes('Holds both pieces of two-card combos: Elf + Bolt, Bolt + Wurm.'));
          assert(two.textContent.includes('Counts as mass land denial.'));
          // A Game Changer requires Bracket 3; the combo alone takes it further.
          const mixed = showReadiness(listed(4, [combo(['Bolt','Wurm'], {floor:4, class:'mass_land_denial', standalone:false})],
            {cards_minimum:3, game_changers:[{name:'Elf',qty:1}]}));
          assert(summaryText(mixed).startsWith("Aims for Bracket 2; the cards found require at least Bracket 3, and a two-card " +
            "combo it holds puts it at Bracket 4 or higher, unless the combo isn't intended."));
          assert(!mixed.textContent.includes('Needs a payoff.'));
          // A combo at the cards' own floor adds nothing to the lead, but is still named.
          const same3 = showReadiness(listed(3, [combo(['Elf','Bolt'])], {cards_minimum:3, game_changers:[{name:'Elf',qty:1}]}));
          assert(summaryText(same3).startsWith('Aims for Bracket 2; the cards found require at least Bracket 3. Game Changers: Elf.'));
          assert(!summaryText(same3).includes('unless'));
          assert(summaryText(same3).includes('Holds both pieces of a two-card combo: Elf + Bolt.'));
        """)

    def test_combos_that_raise_nothing_are_listed_in_softer_words(self):
        self.run_js("""
          const node = showReadiness(listed(1, [combo(['Elf','Bolt'], {standalone:false, raises_floor:false, floor:1}),
            combo(['Wurm','Elf'], {class:'lock', results:['Lock'], raises_floor:false, floor:1, standalone:false})]));
          assert.equal(summaryText(node), "Aims for Bracket 2: no Game Changers, extra turns or mass land denial found; " +
            "the two-card combos it holds don't raise the bracket.");
          const items = node.querySelector('.commander-combos').children.map((li) => li.textContent);
          // A lock needs nothing more, though Spellbook calls its "Lock" a helper result.
          same(items, ['Elf + Bolt: Infinite damage, Infinite lifegain, …. Needs a payoff. Commander Spellbook',
            'Wurm + Elf: Lock. Commander Spellbook']);
          assert(node.textContent.includes('the list holds both pieces of these 2 combos'));
          assert.equal(node.querySelector('details').open, true);
        """)

    def test_an_unreadable_combo_list_is_not_checked_and_incomplete(self):
        self.run_js("""
          for (const combos of [{checked:false, reason:'no list'}, undefined]) {
            const node = showReadiness(readinessPage({combos}));
            assert.equal(summaryText(node), 'Aims for Bracket 2: the card checks are incomplete.');
            assert(node.textContent.includes('Two-card combos: not checked (combo list unavailable).'));
            assert(!node.textContent.includes('none found in Commander Spellbook'));
          }
          const note = commanderDataNote({data:{cards_date:'2026-10-14',tags_date:'2026-10-13',combos_date:null,stale:true}});
          assert(note.textContent.includes("Commander Spellbook's two-card combos: date unknown."));
          assert(note.textContent.includes('may be out of date'));
        """)

    def test_the_stats_panel_lists_combos_too(self):
        self.run_js("""
          const panelFor = (data) => {
            Object.assign(data.stats.commander, {size:{cards:100,expected:100,ok:true}, commanders:['Elf'],
              eligibility:{ok:true,problems:[]}, singleton:{ok:true,duplicates:[],allowed:[]},
              identity:{checked:true,ok:true,outside:[]}, colour_identity:'G',
              legality:{ok:true,banned:[],banned_as_companion:[],not_legal:[]}, problems:[]});
            return commanderPanel(data.stats, data.summary);
          };
          const found = panelFor(listed(3, [combo(['Elf','Bolt'])]));
          assert(found.textContent.includes('Two-card combos: 1'));
          assert(found.textContent.includes('The list holds both pieces of this combo'));
          assert(found.querySelector('.commander-combos').querySelector('a'));
          const none = panelFor(readinessPage());
          assert(none.textContent.includes("Two-card combos: 0None found in Commander Spellbook's two-card combos (list of 2026-10-14)."));
          const unread = panelFor(readinessPage({combos:{checked:false, reason:'no list'}}));
          assert(unread.textContent.includes('Two-card combos: not checked'));
          assert(unread.textContent.includes('Not checked (combo list unavailable).'));
        """)

    def test_wizards_latest_announcement_is_shown_and_never_called_current_unless_checked(self):
        self.run_js(r"""
          const data = (changes) => ({cards_date:'2026-10-14', tags_date:'2026-10-13', combos_date:'2026-10-14',
            dates_stale:false, max_age_days:7, ...officialData, stale:true, ...changes});
          const text = (changes) => commanderDataNote({data:data(changes)}).textContent;
          const fine = commanderDataNote({data:{...data({}), stale:false}});
          assert(fine.textContent.includes("Wizards' latest Commander announcement: 2026-02-09 (last checked 2026-10-14)."));
          assert.equal(fine.querySelector('a').getAttribute('href'), announced.url);
          for (const words of ['may be out of date', 'update the card data', 'older than', 'unknown']) assert(!fine.textContent.includes(words), words);

          const later = {date:'2026-10-15', url:'https://magic.wizards.com/en/news/announcements/x'};
          const both = commanderDataNote({data:data({official_announcement:later, cards_older_than_announcement:true,
            rules_older_than_announcement:true})});
          assert(both.textContent.includes('Wizards announced a Commander change on 2026-10-15, after this card data (2026-10-14); update the card data.'));
          assert(both.textContent.includes("Deck Lab's bracket rules are older than Wizards' 2026-10-15 announcement, so they may be out of date."));
          assert(!both.textContent.includes('more than 7 days old'), 'fresh dates are not called old');
          assert.equal(JSON.stringify([...both.querySelectorAll('a')].map((a) => a.getAttribute('href'))), JSON.stringify([later.url, later.url, later.url]));
          const rules = text({official_announcement:later, rules_older_than_announcement:true});
          assert(rules.includes('bracket rules are older') && !rules.includes('update the card data'));

          assert(text({official_unknown:true, official_checked:'2026-10-01'}).includes(
            "The date of Wizards' latest Commander announcement is unknown (last checked 2026-10-01), so these checks can't say they're current."));
          assert(!text({official_unknown:true, official_checked:'2026-10-01'}).includes('latest Commander announcement: '));
          const never = {official_unknown:true, official_checked:null, official_announcement:null};
          assert(text(never).includes('is unknown (never checked)'));
          // An older server without the check: unknown, never current.
          const old = commanderDataNote({data:{cards_date:'2026-10-14', tags_date:'2026-10-13', stale:false, max_age_days:7}});
          assert(old.textContent.includes('is unknown (never checked)'));
          assert(!old.textContent.includes('may be out of date'));
          assert(commanderDataNote({}).textContent.includes('is unknown (never checked)'));
        """)

    def test_the_stats_panel_shows_the_announcement_warning_too(self):
        self.run_js("""
          const data = readinessPage({data:{cards_date:'2026-10-14', tags_date:'2026-10-13', combos_date:'2026-10-14',
            stale:true, dates_stale:false, max_age_days:7, ...officialData, rules_older_than_announcement:true,
            official_announcement:{date:'2026-10-15', url:'https://magic.wizards.com/en/news/announcements/x'}}});
          Object.assign(data.stats.commander, {size:{cards:100,expected:100,ok:true}, commanders:['Elf'],
            eligibility:{ok:true,problems:[]}, singleton:{ok:true,duplicates:[],allowed:[]},
            identity:{checked:true,ok:true,outside:[]}, colour_identity:'G',
            legality:{ok:true,banned:[],banned_as_companion:[],not_legal:[]}, problems:[]});
          const note = commanderPanel(data.stats, data.summary).querySelector('.commander-data');
          assert(note.textContent.includes("older than Wizards' 2026-10-15 announcement"));
          assert(showReadiness(data).querySelector('.commander-data').textContent.includes("older than Wizards' 2026-10-15 announcement"));
        """)

    def test_no_target_and_cedh_aim_are_not_invented_classifications(self):
        self.run_js("""
          const data = readinessPage(); delete data.summary.target_bracket;
          assert(summaryText(showReadiness(data)).startsWith('No target bracket set:'));
          data.stats.commander.bracket.minimum = 3;
          assert(summaryText(showReadiness(data)).includes('require at least Bracket 3'));
          data.summary.target_bracket = 5;
          const text = summaryText(showReadiness(data));
          assert(text.startsWith('Aims for Bracket 5:'));
          assert(!text.includes('require at least Bracket 5'));
        """)

    def test_data_freshness_and_unknown_dates_are_visible_in_both_panels(self):
        self.run_js("""
          const br = {data:{cards_date:'2026-01-01',tags_date:null,stale:true,max_age_days:7}};
          const note = commanderDataNote(br);
          assert(note.textContent.includes('2026-01-01'));
          assert(note.textContent.includes('Community effect tags: date unknown'));
          assert(note.textContent.includes('more than 7 days old'));
          assert(commanderDataNote({}).textContent.includes('may be out of date'));
          const data = readinessPage(br), k = data.stats.commander;
          Object.assign(k, {size:{cards:100,expected:100,ok:true}, commanders:['Elf'],
            eligibility:{ok:true,problems:[]}, singleton:{ok:true,duplicates:[],allowed:[]},
            identity:{checked:true,ok:true,outside:[]}, colour_identity:'G',
            legality:{ok:true,banned:[],banned_as_companion:[],not_legal:[]}, problems:[]});
          const statsPanel = commanderPanel(data.stats,data.summary);
          assert(statsPanel.querySelector('.commander-data').textContent.includes('2026-01-01'));
        """)

    def test_current_list_not_inventory_controls_the_summary_and_casual_has_none(self):
        self.run_js("""
          const planned = readinessPage({minimum:3,game_changers:[{name:'Bolt',qty:1}]});
          planned.owned = null;  // the list's checks remain visible without inventory permission
          assert(summaryText(showReadiness(planned)).includes('Game Changers: Bolt'));
          const now = readinessPage(); now.version = 'owned';
          assert(summaryText(showReadiness(now)).includes('no Game Changers'));
          assert.equal(commanderReadiness(makePage()),null);
          assert.equal(overviewParts(makePage()).filter(Boolean).some(n => n.classList.contains('commander-readiness')),false);
        """)
