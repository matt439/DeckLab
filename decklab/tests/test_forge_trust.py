"""How far to trust a matchup (2026-10-03, the simulation report's R03 and R19): the starting
player's tile, the lead's verdict and the noise between results (forge.views), whether Forge
pilots a list poorly, from its cards' scripts (forge.ai), and how the page and the command line
say all of it in the same words.

fixtures/forge/pilotscripts/ holds real Forge 2.0.15 card scripts: one or more of each kind of
card Forge's AI misplays (forge.ai.WEAK_KINDS), and cards that look like them but play well
(Grasp of Fate, Journey to Nowhere, Voracious Greatshark, Terror of Mount Velus...). A made-up
Forge folder holds them as its cardsfolder.zip. The lists below are shaped like the real decks of
2026-10-03 (the same weak cards, padded with Grizzly Bears and Forests), to check the rule flags
Selesnya Rabbits, The Free Peoples, Finneas and Gisa and leaves Izzet, Gruul, Angels and
Mono-Black Midrange alone.

No Java, Forge, server, network or saved-result writes. The page checks run under Node.js, when
it's installed, with test_web's stand-in for the document.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import contextlib
import io
import json
import random
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from decklab.lib import decks, forge
from decklab.lib.forge import ai, cli, views
from decklab.lib.forge.cardstats import _merged_cards
from decklab.tests.test_forge import stored
from decklab.tests.test_web import MATCHUP_SCRIPTS, NODE, _function, _run_page, _scripts, _text

SCRIPTS = Path(__file__).parent / "fixtures" / "forge" / "pilotscripts"
PAGE = ("core.js", *MATCHUP_SCRIPTS)
# test_web's stand-in has no deck.js or stats.js: these stand in for their cardLink() and tile().
STUBS = ("globalThis.cardLink = (entry) => el('span', {}, `${entry.qty} ${entry.name}`); "
         "globalThis.tile = (label, value, hint) => el('div', {}, `${label}: `, value, ` (${hint})`); ")


def games_of(on_play, on_draw, nonwins=0):
    """Games where side 0 wins on_play[0] of on_play[1] going first and on_draw[0] of on_draw[1]
    going second (side 1 wins the rest), plus nonwins games with no winner in each."""
    games = []
    for first, (wins, n) in ((0, on_play), (1, on_draw)):
        games += [{"w": 0, "first": first}] * wins + [{"w": 1, "first": first}] * (n - wins)
        games += [{"w": None, "first": first}] * nonwins
    return games


def lead_of(games, p=0):
    winrate = views._winrate(games, p)["winrate"]
    return views._lead(games, p, winrate, views._comparison(games, p))


# ============================================================ the numbers (views)

class StarterTests(unittest.TestCase):

    def test_a_lopsided_matchup_shows_the_real_starter_advantage(self):
        # Like Fellowship v Angels (r5-stats: 13.8% shown, 50.3% balanced). The loser of each game goes first
        # in the next, so the weaker deck (side 1) started 740 of the 800 games and won only 40 of them; side 0
        # won 57 of its 60 starts. The starter's chance is the average of both decks on the play.
        games = games_of((57, 60), (700, 740))
        starter = views._starter(games)
        self.assertTrue(starter["balanced"])
        self.assertEqual(starter["value"], round((57 / 60 + 40 / 740) / 2, 4))      # 50.2%
        self.assertLess(starter["low"], starter["value"])
        self.assertGreater(starter["high"], starter["value"])
        plain = sum(g["w"] == g["first"] for g in games) / len(games)
        self.assertLess(plain, 0.13)                            # the plain share says going first is bad

    def test_without_a_deck_going_first_it_falls_back_to_the_plain_share(self):
        games = [{"w": 0, "first": 0}] * 7 + [{"w": 1, "first": 0}] * 3
        starter = views._starter(games)
        self.assertFalse(starter["balanced"])
        self.assertEqual(starter["value"], 0.7)
        self.assertLess(starter["low"], 0.7)
        self.assertIsNone(views._starter([]))
        self.assertIsNone(views._starter([{"w": 0, "first": None}]))


class LeadTests(unittest.TestCase):

    def test_with_every_game_won_the_lead_is_the_headline_range(self):
        # Then "ahead" is exactly "the headline range leaves out 50%", and "about even" is "inside 45% to 55%".
        rng = random.Random(7)
        for _ in range(200):
            n_play, n_draw = rng.randint(1, 900), rng.randint(1, 900)
            games = games_of((rng.randint(0, n_play), n_play), (rng.randint(0, n_draw), n_draw))
            wr = views._winrate(games, 0)["winrate"]
            lead = lead_of(games)
            self.assertEqual(lead["basis"], "decided")
            ahead = wr["low"] > 0.5 or wr["high"] < 0.5
            even = wr["low"] >= 0.45 and wr["high"] <= 0.55
            self.assertEqual(lead["side"] is not None, ahead)
            self.assertEqual(lead["verdict"], "slightly_ahead" if ahead and even else "ahead" if ahead
                             else "about_even" if even else "not_settled")
            if ahead:
                self.assertEqual(lead["side"], 0 if wr["low"] > 0.5 else 1)

    def test_each_verdict(self):
        self.assertEqual(lead_of(games_of((300, 400), (250, 400))), {"verdict": "ahead", "side": 0, "basis": "decided"})
        self.assertEqual(lead_of(games_of((300, 400), (250, 400)), p=1)["side"], 1)
        self.assertEqual(lead_of(games_of((400, 800), (400, 800)))["verdict"], "about_even")     # 1,600 at 50%
        self.assertEqual(lead_of(games_of((840, 1600), (840, 1600)))["verdict"], "slightly_ahead")  # 3,200 at 52.5%
        self.assertEqual(lead_of(games_of((50, 100), (50, 100)))["verdict"], "not_settled")      # 200 at 50%
        self.assertIsNone(lead_of([]))

    def test_nonwins_keep_the_comparison_of_both_win_rates(self):
        # The 2026-10-01 review's case (test_forge's test_comparison_balances_nonwin_rates_without_discarding_them):
        # judged on decided games alone, each side wins one starter stratum and it looks even; B is ahead.
        games = ([{"w": 0, "first": 0}] + [{"w": None, "first": 0}] * 999
                 + [{"w": 1, "first": 1}] * 900 + [{"w": None, "first": 1}] * 100)
        self.assertEqual(lead_of(games), {"verdict": "ahead", "side": 1, "basis": "comparison"})
        self.assertEqual(lead_of(games, p=1), {"verdict": "ahead", "side": 0, "basis": "comparison"})
        # No winner at all: nothing is decided, so it can't be about even either.
        nothing = [{"w": None, "first": 0}] * 100 + [{"w": None, "first": 1}] * 100
        self.assertEqual(lead_of(nothing)["verdict"], "not_settled")

    def test_about_even_with_nonwins_is_five_points_of_the_decided_games(self):
        # 2,000 games split evenly with 10% timeouts: each deck wins 45%, so the difference's range (about
        # +-4.2 points) is inside +-9 points (10 points of the 90% decided).
        games = games_of((900, 1800), (900, 1800), nonwins=200)
        self.assertEqual(lead_of(games), {"verdict": "about_even", "side": None, "basis": "comparison"})

    def test_the_view_has_the_lead_starter_and_noise(self):
        # test_forge's stored(): games as (winner side, result, first side).
        result = stored([(g["w"], "win", g["first"]) for g in games_of((400, 800), (400, 800))])
        with mock.patch.object(views, "_side_cards_or_none", return_value=None), \
                mock.patch.object(views, "_not_meaningful", return_value=False):
            a, b = views.view(result, "a" * 64), views.view(result, "b" * 64)
            self.assertEqual(a["lead"], {"verdict": "about_even", "side": None, "basis": "decided"})
            self.assertEqual(a["starter"], b["starter"])
            self.assertNotIn("starter_won", a)
            self.assertAlmostEqual(a["noise_points"], 3.5, delta=0.1)      # +-2.4 each at 1,600 (r5-stats)
            result["batches"] = []
            empty = views.view(result, "a" * 64)
        self.assertEqual((empty["lead"], empty["starter"], empty["noise_points"]), (None, None, None))


class NoiseTests(unittest.TestCase):

    def test_noise_follows_the_number_of_games(self):
        for games, low, high in ((800, 4.5, 5.2), (1600, 3.2, 3.7), (3200, 2.2, 2.6)):
            half = games // 4
            noise = views._noise_points(views._winrate(games_of((half, 2 * half), (half, 2 * half)), 0)["winrate"])
            with self.subTest(games=games):
                self.assertTrue(low <= noise <= high, noise)
        self.assertIsNone(views._noise_points({"value": None, "low": None, "high": None}))

    def test_noise_in_words(self):
        self.assertEqual(cli._noise_words(3.5, 1600), "Two results of 1,600 games like this one can differ by "
                                                       "about 3-4 points by chance alone, so treat smaller "
                                                       "differences as noise.")
        self.assertIn("by about 5 points", cli._noise_words(5.0, 800))
        self.assertIn("by under 1 point", cli._noise_words(0.4, 3200))
        self.assertIsNone(cli._noise_words(None, 0))


# ============================================================ how well Forge pilots a list (ai)

class ScriptTests(unittest.TestCase):

    def script(self, stem):
        return next(SCRIPTS.rglob(f"{stem}.txt")).read_text(encoding="utf-8")

    def test_each_kind_from_real_scripts(self):
        expected = {
            "warren_elder": {"team_pump": "ability"}, "lathliss_dragon_queen": {"team_pump": "ability"},
            "overrun": {"team_pump": "spell"}, "rabbit_response": {"team_pump": "spell"},
            "make_a_stand": {"team_pump": "spell"},
            "massacre_wurm": {"etb": "curse"}, "noxious_ghoul": {"etb": "curse"},
            "sunblast_angel": {"etb": "destroy_all"}, "fires_of_mount_doom": {"etb": "destroy_all"},
            "samwise_the_stouthearted": {"etb": "up_to"}, "angel_of_the_ruins": {"etb": "up_to"},
            "eowyn_fearless_knight": {"etb": "no_target"}, "palace_jailer": {"etb": "no_target"},
            "ravenous_chupacabra": {"etb": "no_target"},
            "gandalf_the_white": {"flash": ""}, "cathar_commando": {"flash": ""},
            "stroke_of_midnight": {"strict_targets": "Card.cmcGE4"},
            "beast_within": {"strict_targets": "Card.cmcGE4", "remove_all": ""},
            "devout_decree": {"remove_all": ""}, "ghoulcaller_gisa": {"remove_all": ""},
            "counterspell": {"counterspell": ""}, "essence_scatter": {"counterspell": ""},
        }
        for stem, kinds in expected.items():
            with self.subTest(card=stem):
                self.assertEqual(ai._script_weak(self.script(stem)), kinds)

    def test_cards_that_only_look_weak(self):
        # Removal enchantments held without a target (rightly), a flash creature with an enters ability, a
        # creature whose enters ability targets its own side or pumps its own team, a land, plain cards.
        for stem in ("grasp_of_fate", "journey_to_nowhere", "voracious_greatshark", "harvestrite_host",
                     "terror_of_mount_velus", "scoured_barrens", "lightning_bolt", "grizzly_bears", "giant_growth"):
            with self.subTest(card=stem):
                self.assertEqual(ai._script_weak(self.script(stem)), {})

    def test_what_the_script_says_to_do_anyway_isnt_weak(self):
        wurm = self.script("massacre_wurm")
        self.assertEqual(ai._script_weak(wurm.replace("IsCurse$ True", "IsCurse$ True | AILogic$ Always")), {})
        jailer = self.script("palace_jailer").replace("Execute$ TrigExile |", "Execute$ TrigExile | AILogic$ BadETB |")
        self.assertEqual(ai._script_weak(jailer), {})
        samwise = self.script("samwise_the_stouthearted").replace(
            "Execute$ TrigChangeZone |", "Execute$ TrigChangeZone | OptionalDecider$ You |")
        self.assertEqual(ai._script_weak(samwise), {})
        gandalf = self.script("gandalf_the_white").replace("K:Flash\n", "K:Flash\nSVar:PlayMain1:ALWAYS\n")
        self.assertEqual(ai._script_weak(gandalf), {})


class PilotTests(unittest.TestCase):
    """_pilot() on lists shaped like the real decks, with a made-up Forge holding the fixture scripts."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        folder = cls.tmp / "forge"
        (folder / "res" / "cardsfolder").mkdir(parents=True)
        (folder / "forge-gui-desktop-2.0.15-jar-with-dependencies.jar").write_bytes(b"")
        with zipfile.ZipFile(folder / forge.SCRIPTS_ZIP, "w") as z:
            for path in sorted(SCRIPTS.rglob("*.txt")):
                z.write(path, path.relative_to(SCRIPTS).as_posix())
        cls.settings = {"forge_dir": str(folder), "forge_java": sys.executable}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        for p in (mock.patch.object(forge.common, "DATA_DIR", self.tmp / "data"),
                  mock.patch.object(forge.common, "_settings", lambda: dict(self.settings))):
            p.start()
            self.addCleanup(p.stop)
        for cache in (forge.install._scripts, ai._weak):
            cache.clear()
            self.addCleanup(cache.clear)

    def pilot(self, main, commander=(), cards=60):
        """_pilot() of a list: main and commander [(qty, name)], padded with Forests to cards."""
        filler = cards - sum(q for q, _ in main) - sum(q for q, _ in commander)
        listed = {"Commander": [list(c) for c in commander],
                  "Main": [list(m) for m in main] + [[filler, "Forest"]]}
        kind = "commander" if commander else "constructed"
        return ai._pilot(_merged_cards(listed, kind), forge.install.script_index(), ai.weak_cards(), kind)

    def test_the_decks_forge_pilots_poorly(self):
        rabbits = self.pilot([(3, "Warren Elder"), (2, "Rabbit Response"), (1, "Overrun"), (20, "Grizzly Bears")])
        self.assertEqual((rabbits["poor"], rabbits["why"], rabbits["team_pumps"]), (True, "team_pumps", 6))
        self.assertEqual(rabbits["team_pump_spells"], 3)            # the rest are Warren Elder's ability
        free_peoples = self.pilot([(2, "Éowyn, Fearless Knight"), (1, "Palace Jailer"), (1, "Gandalf the White"),
                                   (1, "Fires of Mount Doom"), (20, "Grizzly Bears")])
        self.assertEqual((free_peoples["poor"], free_peoples["why"], free_peoples["copies"]), (True, "share", 5))
        self.assertEqual([c["name"] for c in free_peoples["cards"]],
                         ["Éowyn, Fearless Knight", "Palace Jailer", "Gandalf the White", "Fires of Mount Doom"])
        finneas = self.pilot([(1, "Cathar Commando"), (1, "Warren Elder"), (1, "Beast Within"), (1, "Rabbit Response"),
                              (1, "Overrun"), (30, "Grizzly Bears")], commander=[(1, "Grizzly Bears")], cards=100)
        self.assertEqual((finneas["poor"], finneas["why"]), (True, "team_pumps"))
        self.assertEqual((finneas["team_pumps"], finneas["team_pump_spells"]), (3, 2))   # 2 spells and Warren Elder
        gisa = self.pilot([(1, "Massacre Wurm"), (30, "Grizzly Bears")], commander=[(1, "Ghoulcaller Gisa")], cards=100)
        self.assertEqual((gisa["poor"], gisa["why"]), (True, "commander"))
        self.assertTrue(gisa["cards"][0]["commander"])

    def test_one_minor_card_doesnt_flag_a_deck(self):
        for main in ([(2, "Counterspell"), (1, "Essence Scatter")],          # Izzet Prowess
                     [(1, "Lathliss, Dragon Queen")],                         # Gruul Ramp
                     [(1, "Devout Decree")],                                  # Mono-White Angels
                     [(2, "Ravenous Chupacabra"), (1, "Massacre Wurm")],      # Mono-Black Midrange: 3 of 4
                     [(1, "Stroke of Midnight"), (1, "Massacre Wurm")]):      # Orzhov Removal (owned)
            with self.subTest(main=main):
                pilot = self.pilot(main + [(20, "Grizzly Bears")])
                self.assertFalse(pilot["poor"])
                self.assertIsNone(pilot["why"])
                self.assertEqual(sum(c["qty"] for c in pilot["cards"]), sum(q for q, _ in main))
        # Like Giada's owned-only list: 6 weak cards in 100 stay under 6.67; a 7th flags it.
        six = [(1, "Stroke of Midnight"), (1, "Make a Stand"), (1, "Sunblast Angel"), (1, "Angel of the Ruins"),
               (1, "Cathar Commando"), (1, "Massacre Wurm"), (30, "Grizzly Bears")]
        giada = self.pilot(six, commander=[(1, "Grizzly Bears")], cards=100)
        self.assertEqual((giada["poor"], giada["copies"], giada["needed"]), (False, 6, 6.67))
        seven = self.pilot(six + [(1, "Devout Decree")], commander=[(1, "Grizzly Bears")], cards=100)
        self.assertEqual((seven["poor"], seven["why"]), (True, "share"))

    def test_counterspells_count_half(self):
        self.assertEqual(self.pilot([(4, "Counterspell"), (3, "Essence Scatter")])["copies"], 3.5)
        eight = self.pilot([(4, "Counterspell"), (4, "Essence Scatter")])
        self.assertEqual((eight["poor"], eight["why"], eight["counterspells"]), (True, "share", 8))

    def test_a_commander_counts_by_what_stops_it_being_cast(self):
        # Gandalf has flash and no enters ability, but a commander with flash is cast in Main 1.
        gandalf = self.pilot([(30, "Grizzly Bears")], commander=[(1, "Gandalf the White")], cards=100)
        self.assertEqual((gandalf["poor"], gandalf["cards"]), (False, []))
        jailer = self.pilot([(30, "Grizzly Bears")], commander=[(1, "Palace Jailer")], cards=100)
        self.assertEqual(jailer["why"], "commander")
        # A commander never cast in the list's games (ai._limits' commander_unplayable) is flagged too.
        bears = ai._pilot(_merged_cards({"Commander": [[1, "Grizzly Bears"]], "Main": [[99, "Forest"]]}, "commander"),
                          forge.install.script_index(), ai.weak_cards(), "commander", unplayable=True)
        self.assertEqual(bears["why"], "commander")

    def test_ai_limits_has_the_pilot(self):
        sections = decks.parse_decklist("Deck\n3 Warren Elder\n2 Rabbit Response\n1 Overrun\n24 Forest\n")
        with mock.patch.object(ai.cards, "tag_members", return_value={tag: set() for tag in ai.TEAM_PUMP_TAGS}):
            limits = ai.ai_limits(sections, "constructed")
        self.assertEqual((limits["pilot"]["poor"], limits["pilot"]["team_pumps"]), (True, 6))
        # Without Forge, no pilot, and the problem says why.
        self.settings["forge_dir"] = str(self.tmp / "nowhere")
        try:
            forge.install._scripts.clear()
            with mock.patch.object(ai.cards, "tag_members", return_value={}):
                limits = ai.ai_limits(sections, "constructed")
        finally:
            self.settings["forge_dir"] = str(self.tmp / "forge")
        self.assertIsNone(limits["pilot"])
        self.assertIn("Forge", limits["problem"])

    def test_the_weak_cards_are_worked_out_once_per_forge(self):
        first = ai.weak_cards()
        self.assertIs(ai.weak_cards(), first)
        self.assertIn(forge.common.norm("Éowyn, Fearless Knight"), first)
        self.assertNotIn("grizzly bears", first)

    def test_the_audit_says_which_team_pumps_are_spells(self):
        rabbits = self.pilot([(3, "Warren Elder"), (2, "Rabbit Response"), (1, "Overrun"), (20, "Grizzly Bears")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_pilot(rabbits)
        self.assertEqual(out.getvalue().splitlines()[0], "  Forge pilots this list poorly: 6 cards pump the whole "
                                                          "team (3 spells, 3 permanents' abilities)")

    def test_the_audit_lists_the_cards(self):
        pilot = self.pilot([(2, "Éowyn, Fearless Knight"), (1, "Palace Jailer"), (1, "Gandalf the White"),
                            (1, "Fires of Mount Doom"), (1, "Stroke of Midnight")])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_pilot(pilot)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines, [
            "  Forge pilots this list poorly: 6 copies of cards Forge's AI misplays (flagged at 4)",
            "    2 Éowyn, Fearless Knight: held until its enters ability has a target, unless the AI is in danger",
            "    1 Palace Jailer: held until its enters ability has a target, unless the AI is in danger",
            "    1 Gandalf the White: a flash creature with no enters ability: cast only at the end of the opponent's turn",
            "    1 Fires of Mount Doom: not cast while its enters ability would do nothing useful",
            "    1 Stroke of Midnight: the AI only aims it at mana value 4 or more"])


# ============================================================ the page says it as the command line does

def pilot_of(why, cards=(), team_pumps=0, counterspells=0, team_pump_spells=0):
    return {"poor": why is not None, "why": why, "cards": list(cards), "copies": sum(c["qty"] for c in cards),
            "needed": 4.0, "team_pumps": team_pumps, "team_pump_spells": team_pump_spells,
            "counterspells": counterspells}


class TeamPumpWordsTests(unittest.TestCase):
    """Team pump spells and permanents' team pump abilities are judged by the same test in Forge's AI
    (PumpAllAi), but only the spells were measured: the 12 to 15 points are said of the spells alone."""

    def test_the_reason_splits_spells_and_abilities(self):
        mixed = cli._pilot_reason(pilot_of("team_pumps", team_pumps=6, team_pump_spells=3))
        self.assertIn("6 of its cards pump the whole team (3 spells, 3 permanents' abilities)", mixed)
        self.assertIn("Holding the spells back put a go-wide deck 12 to 15 points too low", mixed)
        spells = cli._pilot_reason(pilot_of("team_pumps", team_pumps=3, team_pump_spells=3))
        self.assertIn("(3 spells), which", spells)
        abilities = cli._pilot_reason(pilot_of("team_pumps", team_pumps=3))
        self.assertIn("(3 permanents' abilities)", abilities)
        self.assertNotIn("12 to 15", abilities)                 # never measured for abilities
        self.assertEqual(cli._pump_split(pilot_of("team_pumps", team_pumps=2, team_pump_spells=1)),
                         "1 spell, 1 permanent's ability")

    def test_the_audit_gives_one_team_pump_count(self):
        def audit(pilot, team_pump):
            out = io.StringIO()
            limits = {"cannot_play": [], "commander_unplayable": False, "unknown": [], "problem": None,
                      "team_pump": team_pump, "pilot": pilot}
            with contextlib.redirect_stdout(out):
                cli._print_limits("casual/finneas", limits)
            return out.getvalue().splitlines()
        # Scryfall's tags count Hare Raising (a one-creature pump in Forge's script); Forge's scripts don't.
        tagged = {"copies": 3, "cards": [{"name": "Pollen-Shield Hare // Hare Raising", "qty": 1},
                                         {"name": "Rabbit Response", "qty": 1}, {"name": "Overrun", "qty": 1}]}
        scripts = pilot_of("team_pumps", CARD_ROWS[6:7], team_pumps=4, team_pump_spells=2)
        lines = audit(scripts, tagged)
        self.assertFalse(any("team pump spells" in line for line in lines), lines)
        self.assertIn("(2 spells, 2 permanents' abilities)", lines[1])
        # Without Forge's scripts the tags' count is all there is.
        self.assertEqual(audit(None, tagged)[1], "  team pump spells: 3 copies (1 Pollen-Shield Hare // Hare Raising, "
                                                 "1 Rabbit Response, 1 Overrun)")
        # Tagged, but no card Forge's scripts call weak: nothing to flag.
        self.assertEqual(audit(pilot_of(None), tagged), ["casual/finneas:", "  nothing to flag"])


class TrustLinesTests(unittest.TestCase):

    def test_a_commander_never_cast_has_no_pilot_line_when_the_result_means_nothing(self):
        # As on the page (trustPart): the "not meaningful" line already says it.
        result = {"format": "Commander", "sides": [{"card_sha": "a" * 64}, {"card_sha": "b" * 64}]}
        sides = [{"pilot": pilot_of("commander"), "commander_unplayable": True},
                 {"pilot": pilot_of("team_pumps", team_pumps=4, team_pump_spells=2), "commander_unplayable": False}]

        def lines(not_meaningful, titles, sha):
            v = {"noise_points": 3.5, "games": 1600, "not_meaningful": not_meaningful}
            with mock.patch.object(ai, "side_ai", side_effect=lambda result, side: sides[side]):
                return cli._trust_lines(result, v, titles, sha)

        def pilots(found):
            return [line.split(":")[0] for line in found if line.startswith("Forge pilots")]

        muted = lines(True, ("Gisa", "Finneas"), "a" * 64)
        self.assertEqual(pilots(muted), ["Forge pilots Finneas poorly"])
        self.assertIn(cli.COMMANDER_WORDS, muted)
        self.assertEqual(pilots(lines(False, ("Gisa", "Finneas"), "a" * 64)),
                         ["Forge pilots Gisa poorly", "Forge pilots Finneas poorly"])
        self.assertEqual(pilots(lines(True, ("Finneas", "Gisa"), "b" * 64)), ["Forge pilots Finneas poorly"])


CARD_ROWS = [
    {"name": "Éowyn, Fearless Knight", "qty": 2, "commander": False, "why": ["etb"], "detail": {"etb": "no_target"}},
    {"name": "Fires of Mount Doom", "qty": 1, "commander": False, "why": ["etb"], "detail": {"etb": "destroy_all"}},
    {"name": "Gandalf the White", "qty": 1, "commander": False, "why": ["flash"], "detail": {}},
    {"name": "Beast Within", "qty": 1, "commander": False, "why": ["remove_all", "strict_targets"],
     "detail": {"strict_targets": "Card.cmcGE4"}},
    {"name": "Stroke of Midnight", "qty": 1, "commander": False, "why": ["strict_targets"],
     "detail": {"strict_targets": "Card.cmcGE4"}},
    {"name": "Odd Removal", "qty": 1, "commander": False, "why": ["strict_targets"],
     "detail": {"strict_targets": "Creature.powerGE3"}},
    {"name": "Overrun", "qty": 1, "commander": False, "why": ["team_pump"], "detail": {"team_pump": "spell"}},
    {"name": "Counterspell", "qty": 2, "commander": False, "why": ["counterspell"], "detail": {}},
    {"name": "Ghoulcaller Gisa", "qty": 1, "commander": True, "why": ["remove_all"], "detail": {}},
]


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageWordsTests(unittest.TestCase):

    def test_trust_words_match_the_command_line(self):
        pilots = [pilot_of("commander"), pilot_of("team_pumps", team_pumps=6),
                  pilot_of("share", CARD_ROWS[:3]), pilot_of(None, CARD_ROWS[:1])]
        noises = [(3.5, 1600), (5.0, 800), (0.4, 3200), (12.3, 200)]
        calls = ([f"pilotReason({json.dumps(p)})" for p in pilots]
                 + [f"noiseWords({points}, {games})" for points, games in noises]
                 + [f"weakWords({json.dumps(c)})" for c in CARD_ROWS]
                 + ["TEMPO_WORDS", "COMMANDER_WORDS"])
        expected = ([cli._pilot_reason(p) or "" for p in pilots]
                    + [cli._noise_words(points, games) for points, games in noises]
                    + [cli._weak_words(c) for c in CARD_ROWS]
                    + [cli.TEMPO_WORDS, cli.COMMANDER_WORDS])
        self.assertEqual(_run_page(calls, PAGE), expected)
        self.assertEqual(expected[3], "")                       # not flagged: no words
        self.assertIn("never cast", expected[11])           # Beast Within: its first kind
        self.assertIn("mana value 4 or more", expected[12])
        self.assertIn("its card script's targets (Creature.powerGE3)", expected[13])

    def test_team_pump_words_match_the_command_line(self):
        pilots = [pilot_of("team_pumps", team_pumps=6, team_pump_spells=3),
                  pilot_of("team_pumps", team_pumps=3, team_pump_spells=3),
                  pilot_of("team_pumps", team_pumps=3), pilot_of("team_pumps", team_pumps=2, team_pump_spells=1)]
        calls = [f"pilotReason({json.dumps(p)})" for p in pilots] + [f"pumpSplit({json.dumps(p)})" for p in pilots]
        expected = [cli._pilot_reason(p) for p in pilots] + [cli._pump_split(p) for p in pilots]
        self.assertEqual(_run_page(calls, PAGE), expected)

    def test_the_starter_tile(self):
        balanced = {"value": 0.524, "low": 0.488, "high": 0.551, "balanced": True}
        plain = {"value": 0.7, "low": 0.4, "high": 0.9, "balanced": False}
        both, one, none = _run_page([f"{STUBS}starterTile({json.dumps(balanced)})",
                                     f"starterTile({json.dumps(plain)})", "starterTile(null)"], PAGE)
        self.assertEqual(both, "Starting player: 52.4% (wins this share: the average of both decks going first "
                               "(95% range 48.8% to 55.1%))")
        self.assertIn("one deck never went first, so it isn't balanced (95% range 40.0% to 90.0%)", one)
        self.assertEqual(none, "Starting player: ? (no games yet)")

    def test_the_trust_part(self):
        def data(fmt="Constructed", pilots=(None, None), unplayable=(False, False)):
            return {"format": fmt, "sides": [{"title": t, "ai": {"pilot": p, "commander_unplayable": u}}
                                             for t, p, u in zip(("Izzet", "Rabbits"), pilots, unplayable)]}
        r = {"games": 1600, "noise_points": 3.5}
        izzet = pilot_of(None, CARD_ROWS[7:8], counterspells=2)
        rabbits = pilot_of("team_pumps", CARD_ROWS[6:7], team_pumps=3, team_pump_spells=3)
        calls = [f"{STUBS}trustPart({json.dumps(r)}, {json.dumps(data(pilots=(izzet, rabbits)))}, ['Izzet', 'Rabbits'])",
                 f"trustPart({json.dumps(r)}, {json.dumps(data(pilots=(izzet, izzet)))}, ['Izzet', 'Izzet (deck 2)'])",
                 f"trustPart({json.dumps(dict(r, not_meaningful=True))}, "
                 f"{json.dumps(data('Commander', (pilot_of('commander'), None), (True, False)))}, ['Gisa', 'Giada'])",
                 f"trustPart({json.dumps({'games': 0, 'noise_points': None})}, {json.dumps(data())}, ['A', 'B'])"]
        mixed, mirror, commander, empty = _run_page(calls, PAGE)
        self.assertIn(cli._noise_words(3.5, 1600), mixed)
        self.assertIn("Forge pilots Rabbits poorly", mixed)
        self.assertIn("1 Overrunpumps the whole team", mixed)
        self.assertNotIn("Forge pilots Izzet poorly", mixed)
        self.assertNotIn(cli.TEMPO_WORDS, mixed)                # only one deck holds counterspells
        self.assertIn(cli.TEMPO_WORDS, mirror)
        self.assertNotIn(cli.COMMANDER_WORDS, mirror)
        self.assertIn(cli.COMMANDER_WORDS, commander)
        self.assertNotIn("Forge pilots Gisa poorly", commander)  # the box at the top already says so
        self.assertNotIn("Noise", empty)
        self.assertIn("Treat win rates as a comparison between decks", empty)

    def test_the_pilot_flag(self):
        ai_limits = {"pilot": pilot_of("share", CARD_ROWS[:3])}
        deck, matchup, fine = _run_page([
            f"{STUBS}pilotFlag({json.dumps(ai_limits)}, 'The Free Peoples', {{ deckPage: true }})",
            f"pilotFlag({json.dumps(ai_limits)}, 'The Free Peoples')",
            f"String(pilotFlag({json.dumps({'pilot': pilot_of(None, CARD_ROWS[:1])})}, 'Izzet'))"], PAGE)
        self.assertTrue(deck.startswith("Forge pilots this deck poorly4 of its cards are kinds Forge's AI misplays. "
                                        "Its win rates here are probably lower than the real deck's."), deck)
        self.assertIn("2 Éowyn, Fearless Knightheld until its enters ability has a target", deck)
        self.assertTrue(matchup.startswith("Forge pilots The Free Peoples poorly4 of its cards"))
        self.assertEqual(fine, "null")

    def test_the_headline_says_what_the_lead_is_judged_on(self):
        decided, compared = _run_page([
            "rangeNote({games: 800, lead: {verdict: 'ahead', side: 0, basis: 'decided'}})",
            "rangeNote({games: 800, lead: {verdict: 'ahead', side: 0, basis: 'comparison'}})"], PAGE)
        self.assertIn("Every game had a winner, so the lead is judged on this range", decided)
        self.assertIn("between 45% and 55%", decided)
        self.assertIn("Some games had no winner", compared)
        self.assertIn("50% is just a reference mark", compared)


class PageFileTests(unittest.TestCase):

    def test_the_deck_page_shows_the_pilot_flag_in_its_matchups(self):
        # The deck page's Matchups tab (deck-tools.js) puts the flag above its results.
        tab = _function(_text("deck-tools.js"), "drawDeckMatchups")
        self.assertIn("pilotFlag(m.ai, s.title, {deckPage: true})", tab)
        self.assertLess(tab.index("    flag,"), tab.index('"Head to head"'))

    def test_the_result_has_the_trust_part_and_the_starter_tile(self):
        script = _scripts(MATCHUP_SCRIPTS)
        result = _function(script, "resultPart")
        self.assertIn("trustPart(r, data, [ta, tb])", result)
        self.assertIn("rangeNote(r)", result)
        self.assertNotIn("starter_won", script)
        self.assertIn("starterTile(r.starter)", _function(script, "playDrawPanel"))


if __name__ == "__main__":
    unittest.main()
