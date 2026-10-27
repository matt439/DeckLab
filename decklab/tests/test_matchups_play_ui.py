"""Static human/Forge comparisons over authorized summary fixtures, with no game-record reads."""
import unittest

from decklab.tests import test_feature_ui as feature_ui
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js is not installed")
class MatchupsPlayUiTests(unittest.TestCase):
    def run_js(self, scenario):
        feature_ui.FeatureUiTests.run_js(self, r'''
          const real=extra=>({status:'ready',games:9,wins:[4,3],draws:2,first_date:'2026-10-01',last_date:'2026-10-20',minimum_games:10,...extra});
          const match=extra=>({sides:[{id:'casual/alpha',title:'Alpha',version:'target'},{id:'casual/beta',title:'Beta',version:'target'}],
            result:{games:1000,wins:[650,350],draws:0,winrate:{value:.65,low:.62,high:.68,balanced:true}},real_games:real(),...extra});
          const panel=summary=>matchupRealGames(match({real_games:summary}));
        ''' + scenario)

    def test_plain_human_denominator_includes_draws_and_differs_from_balanced_forge_headline(self):
        self.run_js(r'''
          const node=panel(real()),text=node.textContent;
          for(const words of ['Real games','9 recorded human games','Alpha: 4 wins','Beta: 3 wins','2 draws',
            "Alpha's plain human win share: 4 / 9 = 44.4%",'with draws in the denominator',
            "Forge's simulated headline for Alpha: 65.0%, balanced for going first and second"])
            assert(text.includes(words),words);
          assert(!text.includes('57.1%'));assert(!text.includes('650 wins'));assert.equal(node.querySelector('h3').textContent,'Real games');
          assert.equal(node.getAttribute('aria-label'),'Recorded human games for these lists');
        ''')

    def test_matching_scope_describes_same_played_cards_and_excluded_unused_sections(self):
        self.run_js(r'''
          const text=panel(real()).textContent;
          assert(text.includes('this pair of decks with the same main-deck and commander cards as Forge'));
          assert(text.includes('Printing choices, unused sideboards and Companion sections are not compared'));
          assert(!text.includes('same physical printings'));assert(!text.includes('fingerprint'));
        ''')

    def test_delivered_side_order_is_preserved_without_guessing_reverse_seats(self):
        self.run_js(r'''
          const data=match({sides:[{id:'casual/beta',title:'Beta',version:'target'},{id:'casual/alpha',title:'Alpha',version:'target'}],
            real_games:real({wins:[3,4]})});const text=matchupRealGames(data).textContent;
          assert(text.includes('Beta: 3 wins; Alpha: 4 wins'));assert(text.includes("Beta's plain human win share: 3 / 9 = 33.3%"));
          assert(!text.includes("Beta's plain human win share: 4 / 9"));
        ''')

    def test_zero_matching_games_is_honest_with_no_zero_over_zero_or_human_percentage(self):
        self.run_js(r'''
          const text=panel(real({games:0,wins:[0,0],draws:0,first_date:null,last_date:null})).textContent;
          assert(text.includes('0 recorded human games'));assert(text.includes('0 draws'));assert(text.includes('no human win percentage is available'));
          assert(text.includes('Too few real games'));assert(!text.includes('0 / 0'));assert(!text.includes('NaN'));assert(!text.includes('Recorded dates'));
        ''')

    def test_draw_only_record_uses_all_games_and_never_turns_draws_into_half_wins(self):
        self.run_js(r'''
          const text=panel(real({games:10,wins:[0,0],draws:10})).textContent;
          assert(text.includes('10 draws'));assert(text.includes('0 / 10 = 0.0%'));assert(!text.includes('50.0%'));
          assert(text.includes('observational human record'));assert(!text.includes('Too few real games'));
        ''')

    def test_nine_and_ten_game_thresholds_are_explicit_without_claiming_certification(self):
        self.run_js(r'''
          const nine=panel(real()).textContent,ten=panel(real({games:10,wins:[5,3],draws:2})).textContent;
          assert(nine.includes('Too few real games to confirm or contradict Forge yet'));
          assert(ten.includes('observational human record'));assert(ten.includes('does not confirm or contradict Forge by itself'));
          assert(ten.includes('players, choices and chance'));assert(!ten.includes('Too few real games'));
        ''')

    def test_positive_dates_are_safe_calendar_days_and_same_day_is_shown_once(self):
        self.run_js(r'''
          const node=panel(real()),dates=node.querySelectorAll('time');same(dates.map(date=>date.getAttribute('datetime')),['2026-10-01','2026-10-20']);
          assert(node.textContent.includes('2026-10-01 to 2026-10-20'));
          const one=panel(real({first_date:'2024-02-29',last_date:'2024-02-29'}));assert.equal(one.querySelectorAll('time').length,1);
          assert(!one.textContent.includes('2024-02-29 to 2024-02-29'));
        ''')

    def test_malformed_counts_totals_threshold_and_date_contract_fail_closed(self):
        self.run_js(r'''
          const bad=[null,[],{status:undefined},{games:-1},{games:9.5},{games:'9'},{games:true},{games:NaN},{games:Infinity},
            {games:Number.MAX_SAFE_INTEGER+1},{wins:[4]},{wins:[4,3,0]},{wins:[true,6]},{wins:['4',3]},{wins:[-1,8]},
            {draws:-1},{draws:1.5},{draws:3},{minimum_games:9},{minimum_games:'10'},{first_date:null},{last_date:null},
            {first_date:'2026-02-29'},{last_date:'2026-02-30'},{first_date:'2026-10-21'},
            {first_date:'2026-1-01'},{first_date:'2026-10-01T00:00:00Z'},
            {games:0,wins:[0,0],draws:0,first_date:'2026-10-01',last_date:'2026-10-01'}];
          for(const extra of bad){const summary=extra===null?null:Array.isArray(extra)?extra:real(extra);const text=panel(summary).textContent;
            assert(text.includes('could not be checked'),JSON.stringify(extra));assert(!text.includes('recorded human games:'));
            assert(!text.includes('plain human win share'));assert(!text.includes('Recorded dates'));}
        ''')

    def test_unavailable_never_becomes_zero_or_exposes_error_reasons_or_accidental_counts(self):
        self.run_js(r'''
          const text=panel({status:'unavailable',minimum_games:10,reason:'private-player-note-id',games:999,wins:[999,0],draws:0}).textContent;
          assert(text.includes('could not be checked'));assert(!text.includes('0 recorded'));assert(!text.includes('999'));
          assert(!text.includes('private-player'));assert(!text.includes('Too few'));
        ''')

    def test_unsupported_is_a_plain_note_and_older_absent_field_omits_panel(self):
        self.run_js(r'''
          const text=panel({status:'unsupported',minimum_games:10,reason:'hidden-data'}).textContent;
          assert(text.includes('not supported for this result'));assert(!text.includes('hidden-data'));assert(!text.includes('0 recorded'));
          const older=match();delete older.real_games;assert.equal(matchupRealGames(older),null);assert.equal(matchupRealGames(null),null);
        ''')

    def test_malformed_side_metadata_does_not_guess_a_name_or_render_ready_counts(self):
        self.run_js(r'''
          for(const sides of [null,[],[{title:'Alpha'}],[{title:'Alpha'},{title:3}],[{title:'Alpha'},{title:''}],
            [{title:'Alpha'},{title:'Bad'+String.fromCharCode(10)+'Title'}]]){
            const text=matchupRealGames(match({sides})).textContent;assert(text.includes('could not be checked'));assert(!text.includes('44.4%'));
          }
        ''')

    def test_mirror_titles_and_play_now_suffix_use_existing_side_labels(self):
        self.run_js(r'''
          const mirrored=matchupRealGames(match({sides:[{title:'Same',version:'target'},{title:'Same',version:'target'}]})).textContent;
          assert(mirrored.includes('Same (deck 1): 4 wins; Same (deck 2): 3 wins'));
          const owned=matchupRealGames(match({sides:[{title:'Alpha',version:'owned'},{title:'Beta',version:'target'}]})).textContent;
          assert(owned.includes('Alpha (play-now list)'));assert(owned.includes('4 / 9 = 44.4%'));
        ''')

    def test_plain_forge_fallback_is_labelled_and_malformed_forge_rate_is_not_invented(self):
        self.run_js(r'''
          const plain=matchupRealGames(match({result:{winrate:{value:.6,balanced:false}}})).textContent;
          assert(plain.includes('60.0%, the plain simulated share'));assert(plain.includes('could not be balanced'));
          for(const rate of [{value:NaN,balanced:true},{value:Infinity,balanced:true},{value:-.1,balanced:true},{value:1.1,balanced:true},
            {value:'0.65',balanced:true},{value:.65}]){
            const text=matchupRealGames(match({result:{winrate:rate}})).textContent;assert(text.includes('44.4%'));assert(!text.includes("Forge's simulated headline"));
          }
        ''')

    def test_titles_are_text_and_private_record_fields_are_never_rendered(self):
        self.run_js(r'''
          const dangerous='<img src=x onerror=alert(1)> & <script>bad()</script>';
          const node=matchupRealGames(match({sides:[{title:dangerous},{title:'Beta'}],real_games:real({players:['secret-player'],
            notes:'secret-note',records:[{id:'secret-record'}]})}));assert(node.textContent.includes(dangerous));
          assert.equal(node.querySelectorAll('img').length,0);assert.equal(node.querySelectorAll('script').length,0);
          for(const words of ['secret-player','secret-note','secret-record'])assert(!node.textContent.includes(words));
        ''')

    def test_static_panel_adds_no_controls_requests_writes_or_focus_changes_and_leaves_input_unchanged(self):
        self.run_js(r'''
          const data=match(),before=JSON.stringify(data);let reads=0,writes=0;api=async()=>{reads++;};apiWrite=async()=>{writes++;};
          const focus=el('button',{text:'Existing action'});main.append(focus);focus.focus();const node=matchupRealGames(data);main.append(node);
          assert.equal(document.activeElement,focus);assert.equal(reads,0);assert.equal(writes,0);assert.equal(JSON.stringify(data),before);
          assert.equal(node.querySelectorAll('button').length,0);assert.equal(node.querySelectorAll('input').length,0);assert.equal(node.querySelectorAll('a').length,0);
        ''')

    def test_long_titles_are_retained_as_plain_wrappable_text_without_inline_sizing(self):
        self.run_js(r'''
          const title='Long named deck '.repeat(30),node=matchupRealGames(match({sides:[{title},{title:'Other long title '.repeat(25)}]}));
          assert(node.textContent.includes(title));assert.equal(node.getAttribute('style'),null);assert.equal(node.getAttribute('class'),'panel mu-real-games');
          assert(!node.querySelector('table'));assert(!node.querySelector('input'));
        ''')

    def test_result_part_mounts_panel_in_retained_reading_without_replacing_verdict_or_actions(self):
        self.run_js(r'''
          winRateFigure=()=>el('span',{text:'Forge headline'});freshnessBadge=()=>null;rangeBar=()=>null;caveatLine=()=>null;
          actionsPart=()=>el('button',{text:'Existing Play action'});trustPart=()=>null;scorePanel=()=>null;playDrawPanel=()=>null;otherPanel=()=>null;
          aiLimitsParts=()=>[];castsPart=()=>null;howPart=()=>null;
          const data=match();data.sides.forEach(side=>side.ai={});const node=resultPart(data,'matchup');
          const reading=node.querySelector('.mu-reading');assert(reading);assert.equal(reading.children[0].getAttribute('class'),'panel mu-real-games');
          assert(node.textContent.includes('Forge headline'));assert(node.textContent.includes('Existing Play action'));assert(node.querySelector('.mu-why'));
        ''')


if __name__ == "__main__":
    unittest.main()
