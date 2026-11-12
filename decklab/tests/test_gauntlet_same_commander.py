"""Tests for E3-S49's "Same commander": a Commander deck against every popular deck of its own commander
(lib/gauntlet/sample.same_commander, forge.gauntlet.same_commander, the deck page's commander=same choice in
api/gauntlet_page.py, the command line's --same-commander and web/gauntlet.js's choice).

- the matching (a partner pair in either order, a double-faced commander's front face, case), every tier and
  only playable Commander decks, most popular first, and a sample id of its own;
- the API: the commanders come from the deck itself (never the request), every matching deck is played (not one
  per commander), a 60-card deck is refused, a trial never meets its own precon, and none there says so
  instead of starting an empty run;
- the page's choice through its real renderers over an isolated Node DOM.

The API tests run in test_gauntlet_api's sandbox (FakeForge, FakeGauntlet with a small Commander catalogue, a
fresh COORD_JOBS runner); no Forge game, network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_same_commander
"""
import json
import subprocess
import unittest
from unittest import mock

from decklab.lib.api import gauntlet_page
from decklab.lib.forge import gauntlet as forge_gauntlet
from decklab.lib.gauntlet import sample
from decklab.tests.test_api import ELF_COMMANDER, _write
from decklab.tests.test_gauntlet_api import ELVES, GRUUL, FakeGauntlet, GauntletApiTestCase, body, api_run

GHALTA = "Ghalta, Primal Hunger"
PRECON = "gauntlet:precon/GhaltaTrial_TST"
TRIAL = "commander/ghalta-trial"
TRIAL_TEXT = (ELF_COMMANDER.replace("# Elf Commander", "# Ghalta Trial")
              .replace("- **Status:** idea", "- **Status:** idea\n- **Trial:** precon GhaltaTrial_TST"))
KODAMA = "commander/kodama-deck"
KODAMA_TEXT = ELF_COMMANDER.replace("# Elf Commander", "# Kodama Deck").replace(
    "1 Ghalta, Primal Hunger (RIX) 130", "1 Kodama of the East Tree (CMR) 239")
NO_COMMANDER = "commander/no-commander"
NO_COMMANDER_TEXT = ELF_COMMANDER.replace("# Elf Commander", "# No Commander").replace(
    "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\n", "")


def deck(deck_id, commanders, tier="core", rank=None, playable=True, kind="commander", identity="G"):
    """A catalogue entry with the fields same_commander reads."""
    return {"id": deck_id, "title": deck_id.rsplit("/", 1)[1], "kind": kind, "tier": tier, "identity": identity,
            "colours": identity, "playable": playable, "style": {"primary": "ramp"},
            "source": {"kind": "edhrec", "rank": rank, "decks": None},
            "cards": {"Commander": [[1, n] for n in commanders], "Main": [[99, "Forest"]]}}


CATALOGUE = [
    deck("gauntlet:edhrec/ghalta-core", [GHALTA], "core", rank=7),
    deck("gauntlet:edhrec/ghalta-upgraded", [GHALTA], "upgraded", rank=7),
    deck(PRECON, [GHALTA], "precon"),
    deck("gauntlet:edhrec/ghalta-broken", [GHALTA], "core", rank=7, playable=False),
    deck("gauntlet:edhrec/kodama-core", ["Kodama of the East Tree"], "core", rank=3),
    deck("gauntlet:edhrec/pair-core", ["Thrasios, Triton Hero", "Tymna the Weaver"], "core", rank=9,
         identity="WUBG"),
    deck("gauntlet:edhrec/esika-core", ["Esika, God of the Tree // The Prismatic Bridge"], "core", rank=11),
]


class SameCommanderSampleTests(unittest.TestCase):

    def ids(self, commanders):
        return [d["id"] for d in sample.same_commander(CATALOGUE, commanders)]

    def test_every_playable_deck_of_the_commander_in_every_tier_most_popular_first(self):
        self.assertEqual(self.ids([GHALTA]), ["gauntlet:edhrec/ghalta-core", "gauntlet:edhrec/ghalta-upgraded", PRECON])
        self.assertEqual(self.ids(["ghalta, primal hunger "]), self.ids([GHALTA]))          # case and spacing

    def test_a_partner_pair_in_either_order_and_a_front_face(self):
        pair = ["gauntlet:edhrec/pair-core"]
        self.assertEqual(self.ids(["Thrasios, Triton Hero", "Tymna the Weaver"]), pair)
        self.assertEqual(self.ids(["Tymna the Weaver", "Thrasios, Triton Hero"]), pair)
        self.assertEqual(self.ids(["Tymna the Weaver"]), [])                       # half a pair isn't the pair
        self.assertEqual(self.ids(["Esika, God of the Tree"]), ["gauntlet:edhrec/esika-core"])
        self.assertEqual(self.ids(["Esika, God of the Tree // The Prismatic Bridge"]), ["gauntlet:edhrec/esika-core"])

    def test_none_and_60_card_decks(self):
        self.assertEqual(self.ids([]), [])
        self.assertEqual(self.ids(["Nobody In Particular"]), [])
        constructed = deck("gauntlet:forge/duels/ghalta", [GHALTA], "medium", kind="constructed")
        self.assertEqual([d["id"] for d in sample.same_commander([constructed], [GHALTA])], [])
        self.assertEqual(sample.commander_key(["B", "a // x", " "]), "a|b")
        self.assertEqual(sample.commanders_of(CATALOGUE[5]), ["Thrasios, Triton Hero", "Tymna the Weaver"])

    def test_its_own_sample_id(self):
        filters = sample.normalise_filters()
        key = sample.commander_key([GHALTA])
        sid = sample.sample_id("c" * 64, filters, 3, "", commander=key)
        self.assertRegex(sid, r"^sample:[0-9a-f]{12}$")
        self.assertNotEqual(sid, sample.sample_id("c" * 64, filters, 3, ""))
        self.assertNotEqual(sid, sample.sample_id("c" * 64, filters, 3, "", every=True))
        self.assertNotEqual(sid, sample.sample_id("c" * 64, filters, 3, "", commander=sample.commander_key(["Kodama"])))
        self.assertEqual(sid, sample.sample_id("c" * 64, filters, 3, "", commander=key))


class ForgeSameCommanderTests(unittest.TestCase):

    def setUp(self):
        self.saved = {}
        cat = {"sha": "c" * 64, "decks": CATALOGUE}
        for name, value in (("_load_catalogue", lambda fmt: cat),
                            ("_save_sample", lambda fmt, found: self.saved.__setitem__(found["id"], found))):
            patcher = mock.patch.object(forge_gauntlet, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_sample_dict(self):
        found = forge_gauntlet.same_commander("commander", [GHALTA])
        self.assertEqual(found["decks"], ["gauntlet:edhrec/ghalta-core", "gauntlet:edhrec/ghalta-upgraded", PRECON])
        self.assertEqual((found["format"], found["size"], found["seed"], found["commander"], found["catalogue_sha"]),
                         ("commander", 3, "", [GHALTA], "c" * 64))
        self.assertEqual(found["filters"], {"colours": None, "styles": None, "tiers": None})
        self.assertEqual(found["id"], sample.sample_id("c" * 64, found["filters"], 3, "",
                                                       commander=sample.commander_key([GHALTA])))
        self.assertEqual(self.saved, {found["id"]: found})
        self.assertNotIn("all", found)

    def test_unsaved_empty_and_refused(self):
        self.assertEqual(forge_gauntlet.same_commander("commander", [GHALTA], save=False)["decks"][0],
                         "gauntlet:edhrec/ghalta-core")
        empty = forge_gauntlet.same_commander("commander", ["Nobody In Particular"])
        self.assertEqual((empty["decks"], empty["size"]), ([], 0))
        self.assertEqual(self.saved, {})                    # an empty one is never saved
        with self.assertRaisesRegex(ValueError, "only for Commander"):
            forge_gauntlet.same_commander("constructed", [GHALTA])
        with self.assertRaisesRegex(ValueError, "no commander"):
            forge_gauntlet.same_commander("commander", ["", " "])


class CommanderGauntlet(FakeGauntlet):
    """FakeGauntlet with CATALOGUE as its Commander catalogue, and the real same_commander over it."""

    def catalogue(self, fmt):
        found = super().catalogue(fmt)
        return dict(found, decks=list(CATALOGUE)) if fmt == "commander" else found

    def same_commander(self, fmt, commanders, save=True, cat=None):
        self.draws.append(("same", tuple(commanders)))
        with mock.patch.object(forge_gauntlet, "_load_catalogue", self.catalogue):
            found = forge_gauntlet.same_commander(fmt, commanders, save=False, cat=cat)
        if save and found["decks"]:
            self.saved[found["id"]] = found
        return found


class SameCommanderApiTests(GauntletApiTestCase):

    def setUp(self):
        super().setUp()
        self.g = CommanderGauntlet(self.forge, self.g.results)
        self.forge.gauntlet = self.g
        _write(self.box.magic / "decks" / "commander" / "ghalta-trial.md", TRIAL_TEXT)
        _write(self.box.magic / "decks" / "commander" / "no-commander.md", NO_COMMANDER_TEXT)
        _write(self.box.magic / "decks" / "commander" / "kodama-deck.md", KODAMA_TEXT)

    def view(self, deck_id, who="matt", **choices):
        return self.call(who, gauntlet_page.gauntlet_view, deck_id, "target", **choices)

    def test_the_options_count_the_commanders_decks(self):
        answer = self.view(ELVES)
        self.assertEqual(answer["options"]["same_commander"], {"commanders": [GHALTA], "decks": 3})
        self.assertIsNone(answer["sample"]["commander"])
        self.assertIsNone(self.view(GRUUL)["options"]["same_commander"])          # a 60-card deck
        self.assertIsNone(self.view(NO_COMMANDER)["options"]["same_commander"])
        self.assertEqual(self.view(TRIAL)["options"]["same_commander"]["decks"], 2)    # its own precon left out

    def test_the_view_plays_every_deck_of_its_commander(self):
        answer = self.view(ELVES, commander="same")
        self.assertEqual((answer["sample"]["decks"], answer["sample"]["commander"], answer["is_standard"]),
                         (3, [GHALTA], False))
        self.assertEqual([o["id"] for o in answer["opponents"]],
                         ["gauntlet:edhrec/ghalta-core", "gauntlet:edhrec/ghalta-upgraded", PRECON])
        self.assertFalse(answer["sample"]["saved"])         # drawn for the view, not saved
        self.assertEqual(self.g.saved, {})
        self.assertIn(("same", (GHALTA,)), self.g.draws)
        self.assertEqual(sorted(answer["budgets"]), ["fixed:100", "fixed:200", "fixed:50"])
        self.assertEqual(answer["standard"]["size"], 24)    # the standard sample is still named
        json.dumps(answer, allow_nan=False)

    def test_the_request_never_names_the_commanders(self):
        for value in ("Kodama of the East Tree", "yes", "1", 7):
            with self.subTest(value=value):
                self.assertEqual(self.view(ELVES, commander=value), 400)
        self.assertEqual(self.view(ELVES, commander="Same")["sample"]["commander"], [GHALTA])
        for extra in ({"size": "6"}, {"colours": "G"}, {"styles": "ramp"}, {"tiers": "core"},
                      {"sample": "sample:0123456789ab"}):
            with self.subTest(**extra):
                self.assertEqual(self.view(ELVES, commander="same", **extra), 400)
        with self.as_("matt"), self.assertRaises(gauntlet_page.ApiError) as caught:
            gauntlet_page.gauntlet_view(ELVES, "target", commander="same", size="6")
        self.assertEqual(caught.exception.message, gauntlet_page.SAME_ALONE)

    def test_a_60_card_deck_and_a_deck_without_a_commander_are_refused(self):
        self.set_mode("everyone")
        for deck_id, message in ((GRUUL, gauntlet_page.NOT_COMMANDER), (NO_COMMANDER, gauntlet_page.NO_COMMANDER)):
            with self.subTest(deck=deck_id):
                with self.as_("matt"), self.assertRaises(gauntlet_page.ApiError) as caught:
                    gauntlet_page.gauntlet_view(deck_id, "target", commander="same")
                self.assertEqual((caught.exception.status, caught.exception.message), (400, message))
                self.assertEqual(self.run_as("matt", deck_id, commander="same"), 400)
        self.assertEqual(self.g.runs, [])

    def test_a_hidden_deck_answers_as_a_missing_one_first(self):
        self.assertEqual(self.view(ELVES, who="user2", commander="same"), 404)
        self.assertEqual(self.run_as("user2", ELVES, commander="bad"), 404)

    def test_a_run_plays_every_deck_and_is_found_again_by_its_saved_id(self):
        self.set_mode("everyone")
        answer = self.run_as("matt", ELVES, commander="same")
        self.assertIsInstance(answer, dict, answer)
        self.finish()
        (run,) = self.g.runs
        sid = run[1]
        self.assertEqual(self.g.saved[sid]["decks"], ["gauntlet:edhrec/ghalta-core", "gauntlet:edhrec/ghalta-upgraded",
                                                      PRECON])
        self.assertEqual(self.g.saved[sid]["commander"], [GHALTA])
        again = self.view(ELVES, sample=sid)
        self.assertEqual((again["sample"]["commander"], again["sample"]["saved"], again["status"]),
                         ([GHALTA], True, "done"))
        self.assertEqual(again["games"], 600)
        # The same choice asked again finds that run's sample by the same id.
        self.assertEqual(self.view(ELVES, commander="same")["sample"]["id"], sid)

    def test_another_commanders_saved_sample_answers_as_an_unsaved_one(self):
        self.set_mode("everyone")
        self.assertIsInstance(self.run_as("matt", ELVES, commander="same"), dict)
        self.finish()
        sid = self.g.runs[-1][1]
        self.assertEqual(self.view(ELVES, sample=sid)["sample"]["commander"], [GHALTA])   # its own deck's
        unsaved = "sample:0123456789ab"
        for deck_id in (KODAMA, NO_COMMANDER, GRUUL):           # another commander, none, a 60-card deck
            with self.subTest(deck=deck_id):
                for asked in (sid, unsaved):
                    with self.as_("matt"), self.assertRaises(gauntlet_page.ApiError) as caught:
                        gauntlet_page.gauntlet_view(deck_id, "target", sample=asked)
                    self.assertEqual((caught.exception.status, caught.exception.message),
                                     (404, gauntlet_page.NOT_SAVED))
                    with self.as_("matt"), self.assertRaises(gauntlet_page.ApiError) as caught:
                        api_run(body("matt", id=deck_id, sample=asked))
                    self.assertEqual((caught.exception.status, caught.exception.message),
                                     (404, gauntlet_page.NOT_SAVED))
        self.assertEqual(len(self.g.runs), 1)

    def test_a_trial_never_meets_its_own_precon(self):
        self.set_mode("everyone")
        answer = self.view(TRIAL, commander="same")
        self.assertEqual(answer["sample"]["decks"], 2)
        self.assertNotIn(PRECON, [o["id"] for o in answer["opponents"]])
        self.assertIsInstance(self.run_as("matt", TRIAL, commander="same"), dict)
        self.finish()
        entry = gauntlet_page.field_page._field_entry(self.forge, TRIAL, "target")[1]
        sid = self.g.runs[-1][1]
        job = gauntlet_page.forge_runs.COORD_JOBS.get(gauntlet_page.job_key(entry, sid, (PRECON,)))
        self.assertEqual(job.fn.sample["decks"], ["gauntlet:edhrec/ghalta-core", "gauntlet:edhrec/ghalta-upgraded"])

    def test_no_deck_of_the_commander_says_so_and_starts_nothing(self):
        self.set_mode("everyone")
        only = [d for d in CATALOGUE if d["id"] == PRECON]
        with mock.patch(f"{__name__}.CATALOGUE", only):
            answer = self.view(TRIAL)
            self.assertEqual(answer["options"]["same_commander"]["decks"], 0)
            empty = self.view(TRIAL, commander="same")
            self.assertEqual((empty["sample"]["decks"], empty["opponents"], empty["budgets"]), (0, [], {}))
            with self.as_("matt"), self.assertRaises(gauntlet_page.ApiError) as caught:
                api_run(body("matt", id=TRIAL, commander="same"))
        self.assertEqual((caught.exception.status, caught.exception.message),
                         (400, gauntlet_page.NO_SAME_COMMANDER))
        self.assertEqual(self.g.runs, [])
        self.assertEqual(gauntlet_page.forge_runs.COORD_JOBS.active(), [])

    def test_the_route_passes_the_choice(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": ELVES, "commander": "same"}
        with mock.patch.object(feature_routes, "_gauntlet_view", return_value={"status": "none"}) as viewed:
            self.assertTrue(feature_routes.dispatch(handler, ["gauntlet"], {}))
        self.assertEqual(viewed.call_args.kwargs.get("commander"), "same")


class SameCommanderCliTests(unittest.TestCase):
    """--same-commander on plan, play and view (cli_gauntlet._house_sample)."""

    def args(self, **given):
        from decklab.lib.forge import cli_gauntlet
        parser = cli_gauntlet.shared.argparse.ArgumentParser()
        cli_gauntlet._gauntlet_args(parser.add_subparsers(dest="command"))
        return parser.parse_args(["gauntlet", "view", ELVES, "--same-commander", *given.get("extra", ())])

    def test_it_draws_the_decks_own_commander_and_leaves_out_a_trials_precon(self):
        from decklab import lib
        from decklab.lib.forge import cli_gauntlet
        drawn = {"id": "sample:0123456789ab", "format": "commander", "decks": ["a", PRECON], "commander": [GHALTA]}
        fake = mock.Mock(format_of=mock.Mock(return_value="commander"), same_commander=mock.Mock(return_value=drawn))
        a = {"id": TRIAL, "kind": "commander", "cards": {"Commander": [[1, GHALTA]], "Main": []}}
        with mock.patch.object(cli_gauntlet, "_g", return_value=fake), \
                mock.patch.object(lib.decks, "find_summary", return_value={"trial": "GhaltaTrial_TST"}):
            self.assertEqual(cli_gauntlet._house_sample(self.args(), a)["decks"], ["a"])
            fake.same_commander.assert_called_once_with("commander", [GHALTA])
            with self.assertRaisesRegex(cli_gauntlet.shared._CliError, "leave out --size"):
                cli_gauntlet._house_sample(self.args(extra=["--size", "6"]), a)
            fake.same_commander.return_value = dict(drawn, decks=[PRECON])
            with self.assertRaisesRegex(cli_gauntlet.shared._CliError, "no other deck"):
                cli_gauntlet._house_sample(self.args(), a)
            fake.format_of.return_value = "constructed"
            with self.assertRaisesRegex(cli_gauntlet.shared._CliError, "only for Commander"):
                cli_gauntlet._house_sample(self.args(), a)

    def test_sample_refuses_another_commanders_same_commander_sample(self):
        from decklab import lib
        from decklab.lib.forge import cli_gauntlet
        saved = {"id": "sample:0123456789ab", "format": "commander", "decks": ["a"], "commander": [GHALTA]}
        fake = mock.Mock(format_of=mock.Mock(return_value="commander"), sample=mock.Mock(return_value=saved))
        parser = cli_gauntlet.shared.argparse.ArgumentParser()
        cli_gauntlet._gauntlet_args(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["gauntlet", "view", ELVES, "--sample", saved["id"]])
        own = {"id": ELVES, "kind": "commander", "cards": {"Commander": [[1, GHALTA]], "Main": []}}
        other = {"id": KODAMA, "kind": "commander", "cards": {"Commander": [[1, "Kodama of the East Tree"]], "Main": []}}
        with mock.patch.object(cli_gauntlet, "_g", return_value=fake),                 mock.patch.object(lib.decks, "find_summary", return_value=None):
            self.assertEqual(cli_gauntlet._house_sample(args, own)["decks"], ["a"])
            with self.assertRaisesRegex(cli_gauntlet.shared._CliError, "another commander"):
                cli_gauntlet._house_sample(args, other)


from decklab.tests.test_gauntlet_ui import NODE, RUNNER, SETUP, WEB  # noqa: E402  (after the API tests' imports)

UI_SETUP = SETUP + """
  const cmd=(extra={})=>base({deck:{id:'commander/test',version:'target',title:'Test Deck',card_sha:sha},
    format:'commander',default_size:20,options:{...base().options,sizes:[6,12,20,40,'all'],
      tiers:['core','upgraded','precon'],overnight_minutes:120,same_commander:{commanders:['Ghalta, Primal Hunger'],decks:3}},
    sample:{id:'sample:0123456789ab',size:20,filters:{colours:null,styles:null,tiers:['core','upgraded']},decks:20,
      commander:null},...extra});
  const sameAnswer=(n=3)=>cmd({is_standard:false,sample:{id:'sample:5a5a5a5a5a5a',size:n,
    filters:{colours:null,styles:null,tiers:null},decks:n,commander:['Ghalta, Primal Hunger'],saved:false}});
  const drawCmd=async()=>{const node=gauntletSection({summary:{id:'commander/test',title:'Test Deck'},version:'target'});
    main.append(node);await settle();return node;};
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SameCommanderUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), UI_SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_choosing_same_commander_asks_for_it_and_plays_it(self):
        self.run_js("""
          answers=[cmd()];
          const node=await drawCmd();
          const sizes=node.querySelector('.gt-choices').querySelector('.segmented').querySelectorAll('button').map(b=>b.textContent);
          same(sizes,['6','12','20','40','All']);
          const same_=buttonText(node,'Same commander');assert(same_&&!same_.disabled);
          answers=[sameAnswer()];
          same_.click();await settle();
          assert(calls.at(-1).includes('commander=same'),calls.at(-1));
          assert(!calls.at(-1).includes('size='),calls.at(-1));
          assert.equal(node.querySelector('.gt-choices').querySelector('summary').textContent,'3 opponents · same commander');
          assert(!buttonText(node,'All'));                    // the sample's own choices are gone
          assert(node.textContent.includes('all 3 popular decks with Ghalta, Primal Hunger as commander'));
          assert(node.textContent.includes('not advice'));
          buttonText(node,'Play them').click();await settle();
          same(writes.at(-1).body,{id:'commander/test',version:'target',budget:'fixed:100',commander:'same',
            expected_card_sha:sha});
        """)

    def test_back_to_a_balanced_sample_and_a_saved_same_commander_sample(self):
        self.run_js("""
          const saved=sameAnswer();saved.sample.saved=true;
          answers=[saved];
          const node=await drawCmd();
          assert.equal(gtChoiceOf(saved).commander,true);
          assert.equal(node.querySelector('.gt-choices').querySelector('summary').textContent,'3 opponents · same commander');
          answers=[cmd()];
          buttonText(node,'A balanced sample').click();await settle();
          assert(!calls.at(-1).includes('commander='),calls.at(-1));
          assert(calls.at(-1).includes('size=20'),calls.at(-1));
          assert.equal(gtChoiceOf(cmd()).commander,false);
        """)

    def test_none_with_the_commander_says_so_and_cant_be_chosen(self):
        self.run_js("""
          const none=cmd();none.options.same_commander.decks=0;
          answers=[none];
          const node=await drawCmd();
          assert(buttonText(node,'Same commander').disabled);
          assert(node.textContent.includes('The popular decks list has no other deck with Ghalta, Primal Hunger as commander.'));
          // Asked for anyway (an old address): it says so and Play is off.
          const empty=sameAnswer(0);empty.options.same_commander.decks=0;empty.budgets={};
          answers=[empty];
          const again=await drawCmd();
          assert(again.textContent.includes("no other deck with this deck's commander, so there's nothing to play"));
          assert(buttonText(again,'Play them').disabled);
        """)

    def test_a_60_card_deck_has_no_such_choice(self):
        self.run_js("""
          answers=[base()];
          const node=await draw();
          assert(!buttonText(node,'Same commander'));
          assert(!node.textContent.includes('Which decks'));
        """)


if __name__ == "__main__":
    unittest.main()
