"""Deal a hand's keep rule (E4-S09): the practice games' land ranges sent with the deck page,
each main-deck line's keep_land flag, and the page's pure keepVerdict and its advice beside the hand."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import api
from decklab.lib.api import keep_rule
from decklab.lib.goldfish import common as goldfish_rules
from decklab.tests.test_api import ApiTestCase, GRUUL

WEB = Path(__file__).resolve().parents[1] / "web"
RUNNER = Path(__file__).resolve().parent / "fixtures/workspace_ui_runner.js"
NODE = shutil.which("node")


def card(type_line, layout="normal", faces=None):
    return {"name": "Test", "type_line": type_line, "layout": layout, "faces": faces or []}


class KeepLandTests(unittest.TestCase):
    def test_lands_and_spell_land_cards_count_as_the_simulation_counts(self):
        self.assertTrue(keep_rule.keep_land(card("Basic Land — Forest")))
        self.assertTrue(keep_rule.keep_land(card("Artifact Land")))
        self.assertFalse(keep_rule.keep_land(card("Creature — Elf Druid")))
        mdfc = card("Instant // Land", "modal_dfc",
                    [{"type_line": "Instant"}, {"type_line": "Land"}])
        self.assertTrue(keep_rule.keep_land(mdfc))
        # An adventure or split card isn't a land; the simulation's own test for a land is the same function.
        self.assertFalse(keep_rule.keep_land(card("Instant // Instant", "split")))
        self.assertFalse(keep_rule.keep_land({}))

    def test_view_is_the_goldfish_rule_with_its_sources(self):
        view = keep_rule.view()
        self.assertEqual(view["sizes"], {str(k): list(v) for k, v in goldfish_rules.KEEP_LANDS.items()})
        self.assertEqual(list(view["sizes"]), ["7", "6", "5"])
        self.assertEqual(view["free"], list(goldfish_rules.FREE_KEEP_LANDS))
        self.assertEqual(view["always_keep"], goldfish_rules.ALWAYS_KEEP)
        self.assertEqual(view["bottom_lands_above"], goldfish_rules.BOTTOM_LANDS_ABOVE)
        self.assertEqual(view["source"]["url"], goldfish_rules.SOURCES["karsten-code"]["url"])
        self.assertEqual(view["free_source"]["title"], goldfish_rules.SOURCES["karsten-commander"]["title"])
        json.dumps(view)

    def test_a_rule_that_cannot_be_loaded_is_none_and_logged(self):
        with mock.patch.object(keep_rule.importlib, "import_module", side_effect=ImportError("gone")), \
                mock.patch.object(keep_rule.common, "_log") as log:
            self.assertIsNone(keep_rule.view())
        self.assertIn("keep rule", log.call_args[0][0])


class KeepRuleApiTests(ApiTestCase):
    def test_deck_page_sends_the_rule_and_main_deck_land_flags(self):
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        path.write_text(GRUUL.replace("9 Forest\n", "9 Forest\n1 Emeria's Call // Emeria, Shattered Skyclave\n"),
                        encoding="utf-8")
        answer = api.deck_view("casual/gruul-test")
        self.assertEqual(answer["keep_rule"], keep_rule.view())
        deck = {line["name"]: line for line in answer["sections"]["Deck"]}
        self.assertIs(deck["Emeria's Call // Emeria, Shattered Skyclave"]["keep_land"], True)   # a spell // land card
        self.assertIs(deck["Elvish Mystic"]["keep_land"], False)
        for line in answer["sections"]["Sideboard"]:
            self.assertNotIn("keep_land", line)
        # The same for the other list and for a pairing: it reads no inventory, so every viewer gets it.
        self.assertEqual(api.deck_view("casual/gruul-test", "owned")["keep_rule"], answer["keep_rule"])
        self.assertEqual(api.deck_view("pairing/cats+elves")["keep_rule"], answer["keep_rule"])

    def test_a_name_without_card_data_has_no_flag(self):
        answer = api.deck_view("casual/gruul-test")
        for line in answer["sections"]["Deck"]:
            if line["card"] is None:
                self.assertNotIn("keep_land", line)
            else:
                self.assertIsInstance(line["keep_land"], bool)


@unittest.skipUnless(NODE, "Node.js is not installed")
class KeepVerdictUiTests(unittest.TestCase):
    RULE = json.dumps(keep_rule.view())

    def run_js(self, scenario):
        sources = "\n".join((WEB / name).read_text(encoding="utf-8") for name in ("guide.js", "hands.js"))
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps(
            [str(WEB), sources + f"\nconst RULE={self.RULE};\n" + scenario]),
            capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_verdicts_ranges_borderline_free_seven_and_bottoming(self):
        self.run_js("""
          const hand=(lands,spells)=>[...Array(lands)].map(()=>({name:'L',keep_land:true}))
            .concat([...Array(spells)].map(()=>({name:'S',keep_land:false})));
          let v=keepVerdict(hand(3,4),RULE);
          assert.equal(v.verdict,'keep'); assert.equal(v.text,'Keep: 3 lands in 7 cards. The rule keeps 7 cards with 2 to 5 lands.');
          v=keepVerdict(hand(2,5),RULE); assert.equal(v.verdict,'borderline');
          assert.match(v.text,/^Borderline: 2 lands in 7 cards is the fewest the rule keeps, so it's a close call/);
          assert.match(keepVerdict(hand(5,2),RULE).text,/is the most the rule keeps/);
          v=keepVerdict(hand(1,6),RULE); assert.equal(v.verdict,'mulligan');
          assert.equal(v.text,'Mulligan: 1 land in 7 cards is too few. The rule keeps 7 cards with 2 to 5 lands.');
          assert.match(keepVerdict(hand(6,1),RULE).text,/^Mulligan: 6 lands in 7 cards is too many/);
          // Six or five cards keep with 2 to 4; four or fewer always keep.
          assert.equal(keepVerdict(hand(5,1),RULE).verdict,'mulligan');
          assert.equal(keepVerdict(hand(3,2),RULE).verdict,'keep');
          v=keepVerdict(hand(0,4),RULE); assert.equal(v.verdict,'keep');
          assert.match(v.text,/always keeps 4 cards or fewer/);
          // The free multiplayer seven has its own range: 2 lands is a mulligan there, 3 borderline.
          v=keepVerdict(hand(2,5),RULE,{free:true}); assert.equal(v.verdict,'mulligan'); assert.ok(v.free);
          assert.match(v.text,/A free first seven is kept only with 3 to 5 lands/);
          assert.equal(keepVerdict(hand(3,4),RULE,{free:true}).verdict,'borderline');
          assert.equal(keepVerdict(hand(4,3),RULE,{free:true}).verdict,'keep');
          // Judged at Mulligan with cards still to bottom: the rule bottoms lands above 3, then spells.
          v=keepVerdict(hand(6,1),RULE,{bottom:2}); assert.equal(v.size,5); assert.equal(v.lands,4);
          assert.equal(v.verdict,'borderline');
          assert.match(v.text,/after putting 2 cards on the bottom as the rule does, 4 lands in 5 cards/);
          v=keepVerdict(hand(1,6),RULE,{bottom:1}); assert.equal(v.lands,1); assert.equal(v.verdict,'mulligan');
          assert.equal(keepVerdict(hand(7,0),RULE,{bottom:3}).verdict,'keep');
          // Words name lands only; no rule, no verdict; a line without the flag falls back on its type.
          for(const t of [keepVerdict(hand(3,4),RULE).text]) assert.ok(!/drop|spell/.test(t));
          assert.equal(keepVerdict(hand(3,4),null),null);
          assert.equal(keepVerdict([{name:'X'},{name:'Y'},{name:'Z'},{name:'W'},{name:'V'},{name:'U'},{name:'T'}],RULE).lands,0);
          // A spell // land card (keep_land, though its card type isn't Land) counts as a land in the counts line too.
          const mdfc={name:"Emeria's Call // Emeria, Shattered Skyclave",card:{type_line:'Sorcery // Land'},keep_land:true};
          const mixed=[mdfc,...hand(2,4)];
          assert.equal(keepVerdict(mixed,RULE).lands,3);
          assert.equal(handCounts(mixed),'3 lands · 4 spells');
          // Agreement words.
          assert.equal(keepAgreement('keep',{verdict:'keep'}),'you kept, and the rule agrees.');
          assert.equal(keepAgreement('keep',{verdict:'mulligan'}),'you kept; the rule would have taken a mulligan.');
          assert.equal(keepAgreement('mulligan',{verdict:'keep'}),'you took a mulligan; the rule would have kept.');
          assert.equal(keepAgreement('mulligan',{verdict:'mulligan'}),'you took a mulligan, and the rule agrees.');
          assert.match(keepAgreement('keep',{verdict:'borderline'}),/borderline, so either choice is fair/);
        """)

    def test_verdict_shows_only_after_a_choice_with_source_and_mulligan_notes(self):
        self.run_js("""
          const data={summary:{id:'casual/test',kind:'casual'},versions:['target'],version:'target',keep_rule:RULE,
            guide:{changed_on:'2026-11-01',sections:[{title:'Game plan',markdown:'Attack.'},
              {title:'Mulligans',markdown:'Keep any hand with an elf.'}]},
            sections:{Deck:[{name:'Forest',qty:20,keep_land:true}]}};
          const section=manualHandsSection(data); main.append(section);
          const button=text=>section.querySelectorAll('button').find(b=>b.textContent===text);
          assert.ok(!section.textContent.includes('From this deck'));
          button('Deal seven').click();
          // Before a choice: the notes beside the hand, but no verdict.
          assert.ok(section.querySelector('.hands-notes'));
          assert.match(section.textContent,/Keep any hand with an elf/);
          assert.ok(!section.textContent.includes('Attack.'));
          assert.match(section.textContent,/may be out of date/);
          assert.equal(section.querySelector('.hands-verdict'),null);
          button('Mulligan').click();
          const verdict=section.querySelector('.hands-verdict');
          assert.match(verdict.textContent,/Your last hand: you took a mulligan, and the rule agrees/);
          assert.match(verdict.textContent,/Mulligan: 7 lands in 7 cards is too many/);
          const link=verdict.querySelector('a'); assert.equal(link.getAttribute('href'),RULE.source.url);
          assert.equal(link.getAttribute('rel'),'noopener noreferrer');
          button('To bottom').click(); button('Keep hand').click();
          assert.match(section.querySelector('.hands-verdict').textContent,
            /Your kept hand: you kept; the rule would have taken a mulligan[.].*6 lands in 6 cards/);
          button('Draw next card').click();
          assert.ok(section.querySelector('.hands-verdict'));
          button('New hand').click();
          assert.equal(section.querySelector('.hands-verdict'),null);
          assert.equal(data.sections.Deck[0].qty,20);
        """)

    def test_free_seven_uses_its_own_source_and_a_missing_rule_says_so(self):
        self.run_js("""
          const lines=[{name:'Forest',qty:2,keep_land:true},{name:'Bear',qty:20,keep_land:false}];
          const data={summary:{id:'commander/test',kind:'commander'},versions:['target'],version:'target',keep_rule:RULE,
            sections:{Deck:lines}};
          const section=manualHandsSection(data); main.append(section);
          const button=text=>section.querySelectorAll('button').find(b=>b.textContent===text);
          const free=section.querySelector('input'); free.checked=true; free.fire('change');
          button('Deal seven').click();
          assert.equal(section.querySelector('.hands-advice'),null);
          button('Keep hand').click();
          const verdict=section.querySelector('.hands-verdict');
          assert.match(verdict.textContent,/A free first seven is kept only with 3 to 5 lands/);
          assert.match(verdict.textContent,/you kept; the rule would have taken a mulligan/);
          assert.equal(verdict.querySelector('a').getAttribute('href'),RULE.free_source.url);
          const bare=manualHandsSection({...data,keep_rule:null}); main.append(bare);
          bare.querySelectorAll('button').find(b=>b.textContent==='Deal seven').click();
          bare.querySelectorAll('button').find(b=>b.textContent==='Mulligan').click();
          assert.match(bare.querySelector('.hands-verdict').textContent,/keep rule couldn't be loaded/);
        """)


if __name__ == "__main__":
    unittest.main()
