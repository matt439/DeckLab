"""Tests for decklab.lib.goldfish, the practice-hand simulation. No network:
the card index is built from fixtures/goldfish_cards.jsonl, 81 real Scryfall
cards trimmed to the fields the index uses (basics, tapped, check, battle,
reveal, fast and slow lands, Evolving Wilds, true fetch lands, Fabled
Passage, Myriad Landscape, bounce lands (Azorius Chancery, Coral Atoll),
Lotus Field, Temple of the False God, Cryptic Caves, a Triome, Command
Tower, Uncharted Haven, a Pathway, River of Tears, Murmuring Bosk, spell //
land cards, mana creatures and rocks (a
Signet, Basalt Monolith, Everflowing Chalice, Heraldic Banner, Selvala,
Bloom Tender), mana abilities with other costs (Lotus Petal, Springleaf
Drum) or given to other permanents (Goldspan Dragon), land ramp spells and
abilities, Ordeal of Nylea, a tutor, convoke, split, adventure, hybrid,
{2/W}, Phyrexian and X costs, and a few commanders), with stats_tags.jsonl
for roles.

Scripted games use NoShuffle, a random generator that always returns 0, so the
deck keeps the order the test gives it: the first 7 cards are the opening hand
and the rest are drawn in order. Statistical tests compare simulated chances
with exact hypergeometric values, with a tolerance of about 5 standard errors.

These are the card-reading and game-loop tests (goldfish's model.py and
engine.py). simulate(), the saved results, the command line and the worker
processes are tested in test_goldfish_runs.py, with this file's card index
(setUpModule) and helpers.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
"""
import math
import random
import shutil
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from decklab.lib import cards, decks, goldfish, stats

FIXTURES = Path(__file__).parent / "fixtures"
CARDS_FILE = FIXTURES / "goldfish_cards.jsonl"
TAGS_FILE = FIXTURES / "stats_tags.jsonl"

_tmp = None

G, W, U, B, R, C = 16, 1, 2, 4, 8, 32


def setUpModule():
    global _tmp
    _tmp = Path(tempfile.mkdtemp())
    index = cards.build_index(CARDS_FILE, TAGS_FILE, {"default_cards": "2026-09-28"}, log=lambda *a: None)
    cards.write_index(index, _tmp / "index.json.gz")
    cards.load(_tmp / "index.json.gz")


def tearDownModule():
    cards._index = None
    cards._tag_cache.clear()
    shutil.rmtree(_tmp, ignore_errors=True)


def parse(text):
    return decks.parse_decklist(text)


def deck_text(counts, commander=None):
    text = f"Commander\n1 {commander}\n\n" if commander else ""
    return text + "Deck\n" + "".join(f"{q} {n}\n" for n, q in counts.items())


class NoShuffle:
    """random() is always 0, so the deck keeps its order and searches take the first copy."""

    def random(self):
        return 0.0


def script(order, turns=4, setup="play", kind="constructed", commander=None, mulligans=False):
    """Play one game with the deck in exactly this order; (trace, counts)."""
    sections = parse(deck_text(Counter(order), commander))
    model, _ = goldfish.compile_deck(sections, kind)
    ids = {c["name"]: i for i, c in enumerate(model["cards"]) if "variant_of" not in c}
    model["deck"] = [ids[cards.resolve(n)] for n in order]
    engine = goldfish._Engine(model)
    trace = []
    counts = goldfish._play_games(engine, setup, turns, 1, NoShuffle(), mulligans, trace)
    return trace, counts


def engine_for(counts, kind="constructed", commander=None):
    model, _ = goldfish.compile_deck(parse(deck_text(counts, commander)), kind)
    return goldfish._Engine(model), {c["name"]: i for i, c in enumerate(model["cards"]) if "variant_of" not in c}


def hypergeometric_at_least(k, drawn, successes, population):
    """P(at least k successes in drawn cards)."""
    total = math.comb(population, drawn)
    return sum(math.comb(successes, i) * math.comb(population - successes, drawn - i)
               for i in range(k, min(drawn, successes) + 1)) / total


def hypergeometric_between(low, high, drawn, successes, population):
    return (hypergeometric_at_least(low, drawn, successes, population)
            - hypergeometric_at_least(high + 1, drawn, successes, population))


def tolerance(p, n):
    """About 5 standard errors of a simulated chance p from n games."""
    return 5 * math.sqrt(p * (1 - p) / n) + 1e-9


def walk(value):
    yield value
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


# ------------------------------------------------------------------ payment

class TestPayment(unittest.TestCase):

    def payable(self, pool, cost):
        """Can pool (colour masks) pay a mana cost written like "{1}{G}{W}"?"""
        return any(goldfish._payable(list(pool), o[1], tuple(o[2]), {})
                   for o in goldfish._cost_options(cost, 0))

    def test_each_coloured_symbol_needs_its_own_source(self):
        self.assertTrue(self.payable([G, W], "{G}{W}"))
        self.assertFalse(self.payable([G, G], "{G}{W}"))
        self.assertTrue(self.payable([G | W, G], "{G}{W}"))      # the dual pays the white
        self.assertFalse(self.payable([G | W], "{G}{W}"))        # one source can't pay two symbols
        self.assertTrue(self.payable([W | U, W | U], "{W}{U}"))
        self.assertFalse(self.payable([W | U, W | U, R], "{W}{W}{U}"))   # Hall: three symbols, two sources
        self.assertTrue(self.payable([W | U, W | U, W], "{W}{W}{U}"))

    def test_generic_is_paid_by_anything_left(self):
        self.assertTrue(self.payable([G, C, R], "{2}{G}"))
        self.assertFalse(self.payable([G, C], "{2}{G}"))
        self.assertFalse(self.payable([R, R, R], "{2}{G}"))
        self.assertTrue(self.payable([C, C], "{2}"))
        self.assertTrue(self.payable([], "{0}"))

    def test_hybrid_symbols_take_either_colour(self):
        self.assertTrue(self.payable([G, W, R], "{1}{G/W}{G/W}"))
        self.assertTrue(self.payable([G, G, R], "{1}{G/W}{G/W}"))
        self.assertFalse(self.payable([G, R, R], "{1}{G/W}{G/W}"))
        self.assertEqual(goldfish._cost_options("{1}{G/W}{G/W}", 0), [[3, 1, [G | W, G | W], 3]])

    def test_colourless_symbol_needs_colourless_mana(self):
        self.assertTrue(self.payable([C, G], "{C}{G}"))
        self.assertFalse(self.payable([G, G], "{C}{G}"))

    def test_two_generic_hybrid_and_phyrexian(self):
        # {2/W}: one white or two generic; the cheapest way is tried first.
        options = goldfish._cost_options("{2/W}{2/W}", 0)
        self.assertEqual(options[0], [4, 0, [W, W], 2])
        self.assertEqual(options[-1], [4, 4, [], 4])
        self.assertTrue(self.payable([W, R, R], "{2/W}{2/W}"))      # W + two generic
        self.assertFalse(self.payable([R, R, R], "{2/W}{2/W}"))
        # Phyrexian symbols are paid with 2 life: no mana at all.
        self.assertEqual(goldfish._cost_options("{U/P}", 0), [[1, 0, [], 0]])

    def test_x_costs(self):
        self.assertEqual(goldfish._cost_options("{X}{R}", 0), [[1, 0, [R], 1]])
        self.assertEqual(goldfish._cost_options("{X}{R}", 1), [[2, 1, [R], 2]])
        self.assertEqual(goldfish._x_minimum(cards.card("Fireball")), 1)            # "deals X damage"
        self.assertEqual(goldfish._x_minimum(cards.card("Wildwood Scourge")), 1)    # X +1/+1 counters
        self.assertEqual(goldfish._x_minimum(cards.card("Mockingbird")), 0)         # a 1/1 flyer for {U}

    def test_leftover_keeps_the_flexible_sources(self):
        # Paying {1}{G} from a Forest, a Mountain and a dual keeps the dual.
        left = goldfish._leftover([G, R, G | R], 1, (G,))
        self.assertEqual(left, [G | R])

    def test_leftovers_lists_every_way_to_pay(self):
        E, _ = engine_for({"Forest": 10})
        self.assertEqual(list(goldfish._leftovers(E, [W, G], 1, ())), [[W], [G]])
        # {1}{G} from a Forest, a Mountain and a dual can leave any one of them; _leftover's choice first.
        options = list(goldfish._leftovers(E, [G, R, G | R], 1, (G,)))
        self.assertEqual(options[0], goldfish._leftover([G, R, G | R], 1, (G,)))
        self.assertEqual(sorted(map(tuple, options)), [(R,), (G,), (G | R,)])
        # {R}{G} from a Forest and a Mountain leaves nothing, one way only.
        self.assertEqual(list(goldfish._leftovers(E, [G, R], 0, (R, G))), [[]])

    def test_a_rock_cast_mid_turn_is_paid_for_so_the_next_spell_still_fits(self):
        # Review finding: Sol Ring paid with the Forest left Plains + {C}{C}, stranding Beast Within
        # ({2}{G}). Paying with the Plains casts both.
        E, ids = engine_for({"Forest": 10, "Plains": 10, "Sol Ring": 1, "Beast Within": 1})
        cands = sorted([ids["Sol Ring"], ids["Beast Within"]], key=E.RANK.__getitem__)
        casts, used, spent, added = goldfish._plan(E, [W, G], cands, [], 2)
        self.assertEqual([E.NAMES[c] for c, _ in casts], ["Sol Ring", "Beast Within"])
        self.assertEqual((spent, added), (4, 2))

    def test_two_colour_spell_in_a_game(self):
        order = ["Plains", "Island", "Teferi, Time Raveler", "Island", "Craw Wurm", "Craw Wurm", "Craw Wurm",
                 "Craw Wurm", "Craw Wurm", "Craw Wurm", "Craw Wurm"]
        trace, _ = script(order, turns=3)
        self.assertEqual([t["cast"] for t in trace], [[], [], ["Teferi, Time Raveler"]])


# ------------------------------------------------------------ mulligans

class TestKeepAndBottom(unittest.TestCase):

    def setUp(self):
        self.E, self.id = engine_for({"Forest": 20, "Mountain": 2, "Temple of Abandon": 2, "Grizzly Bears": 10,
                                      "Craw Wurm": 10, "Hill Giant": 10, "Lightning Bolt": 6,
                                      "Kazandu Mammoth // Kazandu Valley": 2})

    def hand(self, *names):
        return [self.id[n] for n in names]

    def names(self, ids):
        return sorted(self.E.NAMES[i] for i in ids)

    def test_seven_card_hands_keep_two_to_five_lands(self):
        spell = "Grizzly Bears"
        for lands, keep in ((0, False), (1, False), (2, True), (5, True), (6, False), (7, False)):
            hand = self.hand(*(["Forest"] * lands + [spell] * (7 - lands)))
            self.assertEqual(goldfish._keeps(self.E, hand, free=False), keep, lands)

    def test_smaller_hands_keep_two_to_four_lands_and_four_cards_always(self):
        self.assertTrue(goldfish._keeps(self.E, self.hand("Forest", "Forest", "Forest", "Forest", "Craw Wurm",
                                                          "Craw Wurm"), free=False))
        self.assertFalse(goldfish._keeps(self.E, self.hand("Forest", "Forest", "Forest", "Forest", "Forest",
                                                           "Craw Wurm"), free=False))
        self.assertFalse(goldfish._keeps(self.E, self.hand("Forest", "Craw Wurm", "Craw Wurm", "Craw Wurm",
                                                           "Craw Wurm"), free=False))
        self.assertTrue(goldfish._keeps(self.E, self.hand("Craw Wurm", "Craw Wurm", "Craw Wurm", "Craw Wurm"),
                                        free=False))

    def test_free_seven_keeps_only_three_to_five_lands(self):
        two = self.hand("Forest", "Forest", "Craw Wurm", "Craw Wurm", "Craw Wurm", "Craw Wurm", "Craw Wurm")
        three = self.hand("Forest", "Forest", "Forest", "Craw Wurm", "Craw Wurm", "Craw Wurm", "Craw Wurm")
        self.assertFalse(goldfish._keeps(self.E, two, free=True))
        self.assertTrue(goldfish._keeps(self.E, two, free=False))
        self.assertTrue(goldfish._keeps(self.E, three, free=True))

    def test_spell_land_cards_count_as_lands_for_keeping(self):
        hand = self.hand("Forest", "Kazandu Mammoth // Kazandu Valley", "Craw Wurm", "Craw Wurm", "Craw Wurm",
                         "Craw Wurm", "Craw Wurm")
        self.assertTrue(goldfish._keeps(self.E, hand, free=False))

    def test_bottoming_lands_down_to_three_off_colour_first(self):
        # Five lands and green spells: the Mountain (makes no green) goes first, then a Forest, since the
        # Temple is now the hand's only red source and the deck has red spells.
        hand = self.hand("Forest", "Forest", "Mountain", "Temple of Abandon", "Forest", "Grizzly Bears",
                         "Craw Wurm")
        kept, out = goldfish._bottom(self.E, hand, 2)
        self.assertEqual(self.names(out), ["Forest", "Mountain"])
        self.assertEqual(len(kept), 5)
        # With two Temples, neither is the only red source: a tapped one goes before a Forest.
        hand = self.hand("Forest", "Forest", "Temple of Abandon", "Temple of Abandon", "Forest", "Grizzly Bears",
                         "Craw Wurm")
        _, out = goldfish._bottom(self.E, hand, 1)
        self.assertEqual(self.names(out), ["Temple of Abandon"])

    def test_bottoming_keeps_the_hands_only_source_of_a_splash_colour(self):
        # Review finding: with only green spells in hand, 4 Forests and a Mountain bottomed the Mountain,
        # the only red source, although the deck has red spells.
        hand = self.hand("Forest", "Forest", "Forest", "Forest", "Mountain", "Grizzly Bears", "Craw Wurm")
        kept, out = goldfish._bottom(self.E, hand, 1)
        self.assertEqual(self.names(out), ["Forest"])
        self.assertIn(self.id["Mountain"], kept)

    def test_bottoming_spells_most_expensive_first(self):
        hand = self.hand("Forest", "Forest", "Mountain", "Craw Wurm", "Hill Giant", "Grizzly Bears",
                         "Lightning Bolt")
        _, out = goldfish._bottom(self.E, hand, 2)
        self.assertEqual(self.names(out), ["Craw Wurm", "Hill Giant"])

    def test_bottoming_a_land_then_a_spell(self):
        # Karsten: 4 lands and 3 spells down to 5 cards is a land and a spell.
        hand = self.hand("Forest", "Forest", "Forest", "Forest", "Craw Wurm", "Grizzly Bears", "Lightning Bolt")
        kept, out = goldfish._bottom(self.E, hand, 2)
        self.assertEqual(self.names(out), ["Craw Wurm", "Forest"])
        self.assertEqual(sum(self.E.KEEPLAND[c] for c in kept), 3)

    def test_bottoming_ties_go_by_the_order_of_the_hand_not_by_card(self):
        # Recheck (a nearby case of Uncharted Haven's colour): a tie went to the card later in name order, so
        # the Swamp went and the Island stayed, and a deck of blue and black cards in equal numbers showed
        # blue sources more often. The hand's order is random, so a tie is too.
        E, ids = engine_for({"Island": 9, "Swamp": 9, "Opt": 11, "Tormented Soul": 11})
        island, swamp, opt, soul = ids["Island"], ids["Swamp"], ids["Opt"], ids["Tormented Soul"]
        for a, b in ((island, swamp), (swamp, island)):
            self.assertEqual(goldfish._bottom(E, [a, b, a, b, opt, soul], 1)[1], [a])
        for a, b in ((opt, soul), (soul, opt)):
            self.assertEqual(goldfish._bottom(E, [island, swamp, island, a, b], 1)[1], [a])


class TestMulliganStatistics(unittest.TestCase):
    GAMES = 20_000

    def test_constructed_mulligan_rate_is_the_hypergeometric_value(self):
        result = goldfish.simulate(parse("Deck\n24 Forest\n36 Grizzly Bears\n"), "constructed",
                                   games=self.GAMES, turns=1, seed=11, workers=1)
        keep7 = hypergeometric_between(2, 5, 7, 24, 60)          # 0.8439
        for setup in ("play", "draw"):
            mull = result["results"][setup]["mulligans"]
            self.assertAlmostEqual(mull["rate"], 1 - keep7, delta=tolerance(keep7, self.GAMES))
            kept = {k["cards"]: k["share"] for k in mull["kept"]}
            self.assertAlmostEqual(kept[7], keep7, delta=tolerance(keep7, self.GAMES))
            self.assertIsNone(mull["free_rate"])

    def test_commander_free_mulligan_only_in_multiplayer(self):
        sections = parse(deck_text({"Forest": 38, "Craw Wurm": 61}, commander="Finneas, Ace Archer"))
        result = goldfish.simulate(sections, "commander", games=self.GAMES, turns=1, seed=5, workers=1)
        self.assertEqual([s["id"] for s in result["setups"]], ["multiplayer", "play", "draw"])
        free_keep = hypergeometric_between(3, 5, 7, 38, 99)
        keep = hypergeometric_between(2, 5, 7, 38, 99)
        multi = result["results"]["multiplayer"]["mulligans"]
        self.assertAlmostEqual(multi["rate"], 1 - free_keep, delta=tolerance(free_keep, self.GAMES))
        self.assertEqual(multi["rate"], multi["free_rate"])
        kept = {k["cards"]: k["share"] for k in multi["kept"]}
        # The free mulligan draws 7 again with nothing on the bottom.
        seven = free_keep + (1 - free_keep) * keep
        self.assertAlmostEqual(kept[7], seven, delta=tolerance(seven, self.GAMES))
        one_v_one = result["results"]["play"]["mulligans"]
        self.assertAlmostEqual(one_v_one["rate"], 1 - keep, delta=tolerance(keep, self.GAMES))
        self.assertIsNone(one_v_one["free_rate"])


# ------------------------------------------------------ exact land maths

class TestExactLandDrops(unittest.TestCase):
    """With mulligans off, "a land on each of turns 1..N" is exactly "at least
    N lands in the cards seen by turn N": 6 + N on the play, 7 + N on the draw."""
    GAMES = 20_000

    def test_constructed_play_and_draw(self):
        result = goldfish.simulate(parse("Deck\n24 Forest\n36 Craw Wurm\n"), "constructed", games=self.GAMES,
                                   turns=4, seed=2, workers=1, mulligans=False)
        for setup, seen in (("play", 6), ("draw", 7)):
            r = result["results"][setup]
            on_time = {d["land"]: d["chance"] for d in r["land_drops"]["on_time"]}
            mana = {d["turn"]: d["chance"] for d in r["land_drops"]["mana"]}
            for n in (2, 3, 4):
                exact = hypergeometric_at_least(n, seen + n, 24, 60)
                self.assertAlmostEqual(on_time[n], exact, delta=tolerance(exact, self.GAMES), msg=(setup, n))
                self.assertEqual(mana[n], on_time[n])        # untapped Forests only: the same event
            self.assertEqual(r["mulligans"]["rate"], 0)

    def test_multiplayer_draws_on_turn_one(self):
        sections = parse(deck_text({"Forest": 40, "Craw Wurm": 59}, commander="Finneas, Ace Archer"))
        result = goldfish.simulate(sections, "commander", games=self.GAMES, turns=3, seed=4, workers=1,
                                   mulligans=False)
        multi = {d["land"]: d["chance"] for d in result["results"]["multiplayer"]["land_drops"]["on_time"]}
        play = {d["land"]: d["chance"] for d in result["results"]["play"]["land_drops"]["on_time"]}
        exact_multi = hypergeometric_at_least(3, 10, 40, 99)
        exact_play = hypergeometric_at_least(3, 9, 40, 99)
        self.assertAlmostEqual(multi[3], exact_multi, delta=tolerance(exact_multi, self.GAMES))
        self.assertAlmostEqual(play[3], exact_play, delta=tolerance(exact_play, self.GAMES))


# ------------------------------------------------------- scripted games

BLANKS = ["Craw Wurm"] * 8


class TestManaSources(unittest.TestCase):

    def test_mana_creature_makes_mana_from_the_next_turn(self):
        order = ["Forest", "Llanowar Elves", "Forest", "Forest"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[0]["cast"], ["Llanowar Elves"])
        self.assertEqual([t["mana"] for t in trace], [1, 3, 4])

    def test_hasty_mana_creature_makes_mana_at_once(self):
        # Ruby's mana pays for the Elves the turn it's cast.
        order = ["Mountain", "Ruby, Daring Tracker", "Llanowar Elves"] + ["Craw Wurm"] * 4 + ["Forest"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[0]["cast"], [])
        self.assertEqual(trace[1]["cast"], ["Ruby, Daring Tracker", "Llanowar Elves"])
        self.assertEqual((trace[1]["added"], trace[1]["spent"]), (1, 3))

    def test_mana_rock_makes_mana_the_turn_it_is_cast(self):
        # Sol Ring's {C}{C} pays for Mind Stone, whose {C} is left over.
        order = ["Forest", "Sol Ring", "Mind Stone", "Llanowar Elves", "Forest"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[0]["cast"], ["Sol Ring", "Mind Stone"])
        self.assertEqual((trace[0]["added"], trace[0]["spent"]), (3, 3))
        self.assertEqual(trace[1]["mana"], 5)            # 2 lands + Sol Ring 2 + Mind Stone 1

    def test_rock_that_enters_tapped_waits_a_turn(self):
        order = ["Swamp", "Swamp", "Charcoal Diamond", "Swamp"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[1]["cast"], ["Charcoal Diamond"])
        self.assertEqual(trace[1]["added"], 0)
        self.assertEqual(trace[2]["mana"], 4)

    def test_temple_of_the_false_god_needs_five_lands(self):
        order = ["Temple of the False God"] + ["Craw Wurm"] * 6 + ["Forest"] * 4 + BLANKS
        trace, _ = script(order, turns=5)
        self.assertEqual([t["mana"] for t in trace], [0, 1, 2, 3, 6])

    def test_signet_counts_only_the_mana_beyond_its_cost(self):
        # "{1}, {T}: Add {W}{B}": on turn 2 the Signet takes both lands, so nothing is left to use it
        # and Gifted Aetherborn ({B}{B}) waits; from turn 3 it's one more mana.
        order = ["Plains", "Swamp", "Orzhov Signet", "Gifted Aetherborn", "Plains", "Craw Wurm", "Craw Wurm",
                 "Swamp", "Swamp"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual((trace[1]["cast"], trace[1]["spent"], trace[1]["added"]), (["Orzhov Signet"], 2, 0))
        self.assertEqual(trace[2]["mana"], 4)                   # 3 lands + 1
        self.assertEqual(trace[2]["cast"], ["Gifted Aetherborn"])
        E, ids = engine_for({"Orzhov Signet": 1, "Plains": 10})
        self.assertEqual(E.EFF[ids["Orzhov Signet"]], ("rock", W | B, 1, False, 1, 0))
        self.assertEqual(E.NOW[ids["Orzhov Signet"]], (W | B, 1, 1))
        _, info = goldfish.compile_deck(parse("Deck\n10 Plains\n1 Orzhov Signet\n"), "constructed")
        self.assertIn({"name": "Orzhov Signet", "qty": 1, "rule": (
            "mana rock ({W}{B}) whose ability costs {1}: counted as 1 more mana of either colour, which makes "
            "mana from the turn it's cast if there's mana to spare")}, info["special"])

    def test_signet_makes_mana_the_turn_it_is_cast_with_mana_to_spare(self):
        E, ids = engine_for({"Orzhov Signet": 1, "Hill Giant": 1, "Plains": 10})
        cands = sorted([ids["Orzhov Signet"], ids["Hill Giant"]], key=E.RANK.__getitem__)
        # Three lands: two pay for the Signet and the third can pay for its ability, so it adds a mana at
        # once (Hill Giant still needs red). With two lands nothing is left for the ability that turn.
        casts, _, spent, added = goldfish._plan(E, [W, W, W], cands, [], 3)
        self.assertEqual(([E.NAMES[c] for c, _ in casts], spent, added), (["Orzhov Signet"], 2, 1))
        casts, _, _, added = goldfish._plan(E, [W, W], cands, [], 2)
        self.assertEqual(added, 0)

    def test_rocks_that_do_not_untap_or_need_charge_counters_make_no_mana(self):
        order = ["Plains"] * 3 + ["Basalt Monolith", "Everflowing Chalice", "Craw Wurm", "Craw Wurm"] + \
                ["Plains"] * 3 + BLANKS
        trace, _ = script(order, turns=5)
        self.assertEqual(trace[0]["cast"], ["Everflowing Chalice"])       # {0}: no charge counters
        self.assertEqual(trace[2]["cast"], ["Basalt Monolith"])
        self.assertEqual([t["mana"] for t in trace], [1, 2, 3, 4, 5])
        _, info = goldfish.compile_deck(parse("Deck\n10 Plains\n1 Basalt Monolith\n1 Everflowing Chalice\n"
                                              "1 Wirewood Channeler\n"), "constructed")
        notes = {(c["name"], c["what"]) for c in info["not_modelled"]}
        self.assertIn(("Basalt Monolith", "it doesn't untap by itself, so its mana isn't counted"), notes)
        self.assertIn(("Everflowing Chalice", "its mana needs charge counters, which aren't modelled, so it "
                                              "makes none"), notes)
        self.assertIn(("Wirewood Channeler", "its X mana counts as one mana"), notes)

    def test_commander_colour_identity_mana(self):
        # Arcane Signet makes the commander's colours; with no commander it makes nothing.
        order = ["Forest", "Plains", "Arcane Signet", "Grizzly Bears"] + BLANKS
        trace, _ = script(order, turns=3, kind="commander", commander="Finneas, Ace Archer")
        self.assertEqual(trace[1]["cast"], ["Arcane Signet"])       # before Finneas: it makes mana at once
        self.assertEqual(trace[2]["mana"], 3)
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[1]["cast"], ["Arcane Signet"])
        self.assertEqual(trace[2]["mana"], 2)

    def test_mana_abilities_with_other_costs_make_no_mana(self):
        # Review finding: Lotus Petal ({T}, sacrifice it) made a mana every turn, and so did Springleaf Drum
        # (which needs another creature to tap).
        order = ["Plains", "Lotus Petal", "Springleaf Drum"] + ["Craw Wurm"] * 4 + ["Plains"] * 3 + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[0]["cast"], ["Springleaf Drum", "Lotus Petal"])
        self.assertEqual([(t["mana"], t["added"]) for t in trace], [(1, 0), (2, 0), (3, 0)])
        _, info = goldfish.compile_deck(parse("Deck\n10 Plains\n1 Lotus Petal\n1 Springleaf Drum\n"), "constructed")
        self.assertEqual(info["special"], [])
        notes = {(c["name"], c["what"]) for c in info["not_modelled"]}
        self.assertIn(("Lotus Petal", "its mana ability that also costs \"sacrifice this artifact\" isn't modelled, so "
                                      "it makes no mana"), notes)
        self.assertIn(("Springleaf Drum", "its mana ability that also costs \"tap an untapped creature you control\" "
                                          "isn't modelled, so it makes no mana"), notes)
        # The Stats page reads them the same way: not mana rocks.
        self.assertIsNone(stats.mana_ability(cards.card("Lotus Petal")))
        self.assertEqual(stats.mana_ability(cards.card("Sol Ring")), "rock")

    def test_mana_ability_given_to_other_permanents_is_not_the_cards_own(self):
        # Review finding: Goldspan Dragon's Treasures' "{T}, Sacrifice this artifact: Add two mana" made it a
        # hasty mana creature.
        E, ids = engine_for({"Goldspan Dragon": 1, "Mountain": 10})
        self.assertIsNone(E.EFF[ids["Goldspan Dragon"]])
        self.assertIsNone(stats.mana_ability(cards.card("Goldspan Dragon")))
        _, info = goldfish.compile_deck(parse("Deck\n10 Mountain\n1 Goldspan Dragon\n"), "constructed")
        self.assertEqual(info["special"], [])
        self.assertEqual([c["what"] for c in info["not_modelled"]], ["Treasure isn't used as mana"])

    def test_a_rock_whose_colour_is_chosen_makes_the_colour_needed(self):
        # Review finding: Heraldic Banner was read as a rock of every colour ({W}{U}{B}{R}{G}); it makes the
        # one colour chosen as it enters.
        sections = parse(deck_text({"Plains": 30, "Heraldic Banner": 1, "Serra Angel": 68},
                                   commander="Giada, Font of Hope"))
        _, info = goldfish.compile_deck(sections, "commander")
        rules = {c["name"]: c["rule"] for c in info["special"]}
        self.assertEqual(rules["Heraldic Banner"], "mana rock ({W}): makes mana from the turn it's cast")
        E, ids = engine_for({"Forest": 10, "Plains": 5, "Heraldic Banner": 1, "Serra Angel": 4, "Grizzly Bears": 4})
        banner = E.EFF[ids["Heraldic Banner"]]
        self.assertEqual(banner[5], W | U | B | R | G)
        forest, plains = [ids["Forest"], 0], [ids["Plains"], 0]
        self.assertEqual(goldfish._source_mask(E, banner, [ids["Serra Angel"]], [], [forest] * 3, [], NoShuffle()), W)
        self.assertEqual(goldfish._source_mask(E, banner, [ids["Grizzly Bears"]], [], [plains] * 3, [], NoShuffle()), G)
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 Heraldic Banner\n"), "constructed")
        self.assertEqual(info["special"][0]["rule"], "mana rock (one colour, chosen as it enters: the one you need "
                                                     "most): makes mana from the turn it's cast")

    def test_x_and_for_each_mana_creatures(self):
        # Review finding: Selvala's X is at least her own power (2), so her {G} ability adds a mana; and Bloom
        # Tender's "{T}: For each color ..., add" wasn't read as a mana ability at all.
        E, ids = engine_for({"Selvala, Heart of the Wilds": 1, "Bloom Tender": 1, "Forest": 10})
        self.assertEqual(E.EFF[ids["Selvala, Heart of the Wilds"]], ("dork", W | U | B | R | G, 1, False, 1, 0))
        self.assertEqual(E.EFF[ids["Bloom Tender"]], ("dork", G, 1, False, 0, 0))
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 Selvala, Heart of the Wilds\n1 Bloom Tender\n"),
                                        "constructed")
        notes = {(c["name"], c["what"]) for c in info["not_modelled"]}
        self.assertIn(("Selvala, Heart of the Wilds", "its X mana counts as 2, its own power"), notes)
        self.assertIn(("Bloom Tender", "its 'for each' mana counts as one mana"), notes)
        self.assertEqual(stats.mana_ability(cards.card("Bloom Tender")), "creature")


class TestLands(unittest.TestCase):

    def test_tapped_land_goes_first_when_it_costs_nothing(self):
        order = ["Temple of Abandon", "Forest", "Grizzly Bears", "Grizzly Bears"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"]), ("Temple of Abandon", True))
        self.assertEqual((trace[1]["land"], trace[1]["cast"]), ("Forest", ["Grizzly Bears"]))

    def test_untapped_land_when_it_casts_something(self):
        order = ["Temple of Abandon", "Forest", "Llanowar Elves"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual((trace[0]["land"], trace[0]["cast"]), ("Forest", ["Llanowar Elves"]))

    def test_check_land_enters_untapped_with_a_matching_land(self):
        order = ["Rootbound Crag", "Forest", "Grizzly Bears", "Llanowar Elves"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[0]["land"], "Forest")
        self.assertEqual((trace[1]["land"], trace[1]["land_tapped"]), ("Rootbound Crag", False))
        self.assertEqual(trace[1]["cast"], ["Grizzly Bears"])
        trace, _ = script(["Rootbound Crag", "Island"] + BLANKS, turns=1)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"]), ("Rootbound Crag", True))

    def test_battle_land_needs_two_basic_lands(self):
        order = ["Cinder Glade", "Forest", "Mountain", "Grizzly Bears"] + BLANKS
        trace, _ = script(order + ["Cinder Glade"], turns=4)
        tapped = {t["land"]: t["land_tapped"] for t in trace if t["land"] == "Cinder Glade"}
        self.assertEqual(sum(1 for t in trace if t["land"] == "Cinder Glade"), 1)
        self.assertEqual(tapped, {"Cinder Glade": True})
        E, ids = engine_for({"Cinder Glade": 1, "Forest": 10})
        forest, glade = ids["Forest"], ids["Cinder Glade"]
        self.assertFalse(goldfish._enters_untapped(E, glade, [[forest, 0]], [], 2, False))
        self.assertTrue(goldfish._enters_untapped(E, glade, [[forest, 0], [forest, 0]], [], 3, False))

    def test_fast_slow_and_reveal_lands(self):
        E, ids = engine_for({"Blooming Marsh": 1, "Deserted Beach": 1, "Fortified Village": 1, "Forest": 10,
                             "Island": 1})
        f = [ids["Forest"], 0]
        marsh, beach, village = ids["Blooming Marsh"], ids["Deserted Beach"], ids["Fortified Village"]
        self.assertTrue(goldfish._enters_untapped(E, marsh, [f, f], [], 3, False))
        self.assertFalse(goldfish._enters_untapped(E, marsh, [f, f, f], [], 4, False))
        self.assertFalse(goldfish._enters_untapped(E, beach, [f], [], 2, False))
        self.assertTrue(goldfish._enters_untapped(E, beach, [f, f], [], 3, False))
        self.assertTrue(goldfish._enters_untapped(E, village, [], [village, ids["Forest"]], 1, False))
        self.assertFalse(goldfish._enters_untapped(E, village, [], [village, ids["Island"]], 1, False))

    def test_evolving_wilds_fetches_a_basic_that_enters_tapped(self):
        order = ["Evolving Wilds", "Hill Giant", "Lightning Bolt"] + ["Hill Giant"] * 8 + ["Forest", "Mountain"]
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[0]["land"], "Evolving Wilds")
        self.assertEqual(trace[0]["lands"], ["Mountain"])        # the Bolt needs red
        self.assertEqual((trace[0]["mana"], trace[0]["usable"]), (1, 0))
        self.assertEqual(trace[1]["cast"], ["Lightning Bolt"])

    def test_true_fetch_lands_put_their_land_in_untapped(self):
        # Review finding: Polluted Delta's Swamp came in tapped, so Tormented Soul waited a turn.
        order = ["Polluted Delta", "Tormented Soul"] + ["Craw Wurm"] * 5 + ["Swamp", "Island"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"]), ("Polluted Delta", False))
        self.assertEqual((trace[0]["lands"], trace[0]["cast"]), (["Swamp"], ["Tormented Soul"]))
        order = ["Prismatic Vista", "Tormented Soul"] + ["Craw Wurm"] * 5 + ["Swamp"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual((trace[0]["lands"], trace[0]["cast"]), (["Swamp"], ["Tormented Soul"]))
        _, info = goldfish.compile_deck(parse("Deck\n10 Swamp\n1 Polluted Delta\n1 Prismatic Vista\n"
                                              "1 Evolving Wilds\n1 Fabled Passage\n"), "constructed")
        rules = {c["name"]: c["rule"] for c in info["special"]}
        self.assertEqual(rules, {
            "Polluted Delta": "sacrificed at once for an Island or Swamp card, which enters untapped",
            "Prismatic Vista": "sacrificed at once for a basic land, which enters untapped",
            "Evolving Wilds": "sacrificed at once for a basic land, which enters tapped",
            "Fabled Passage": "sacrificed at once for a basic land, which enters tapped unless you then control "
                              "4 or more lands"})

    def test_fetch_and_return_requirements_do_not_give_a_land_subtypes(self):
        E, ids = engine_for({"Polluted Delta": 2, "Coral Atoll": 1, "Island": 5})
        delta, atoll, island = (ids[n] for n in ("Polluted Delta", "Coral Atoll", "Island"))
        self.assertEqual((E.LSUB[delta], E.LSUB[atoll], E.LSUB[island]), (0, 0, U))
        spec = E.FETCH[delta][1:3]
        # Neither Delta nor Atoll is an Island or Swamp. A real Island remains a legal target.
        self.assertIsNone(goldfish.engine._pick(E, [delta, atoll], 0, spec, [], 0, 0, NoShuffle()))
        self.assertEqual(goldfish.engine._pick(E, [delta, atoll, island], 0, spec, [], 0, 0, NoShuffle()), island)
        self.assertFalse(goldfish.engine._can_enter(E, atoll, [[atoll, 0]]))
        self.assertTrue(goldfish.engine._can_enter(E, atoll, [[island, 0]]))
        # The game loop must also leave an illegal target in the library.
        order = ["Polluted Delta", "Opt"] + ["Craw Wurm"] * 5 + ["Coral Atoll"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual(trace[0]["lands"], [])
        self.assertEqual(trace[0]["cast"], [])

    def test_fabled_passage_untaps_its_land_with_four_lands(self):
        order = ["Mountain"] * 3 + ["Hill Giant"] + ["Craw Wurm"] * 5 + ["Fabled Passage", "Mountain"] + BLANKS
        trace, _ = script(order, turns=4)
        self.assertEqual((trace[3]["land"], trace[3]["land_tapped"]), ("Fabled Passage", False))
        self.assertEqual(trace[3]["cast"], ["Hill Giant"])
        # With fewer lands it's a tapped land, played first when nothing needs the mana.
        order = ["Fabled Passage", "Mountain", "Hill Giant"] + ["Craw Wurm"] * 4 + ["Mountain"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"], trace[0]["lands"]),
                         ("Fabled Passage", True, ["Mountain"]))

    def test_bounce_land_returns_a_land_and_needs_one_to_return(self):
        order = ["Azorius Chancery", "Plains"] + ["Craw Wurm"] * 5 + BLANKS
        trace, counts = script(order, turns=3)
        self.assertEqual(trace[0]["land"], "Plains")            # nothing to return yet
        self.assertEqual((trace[1]["land"], trace[1]["lands"]), ("Azorius Chancery", ["Azorius Chancery"]))
        self.assertIn("Plains", trace[1]["hand"])
        # Turn 2: the Plains' mana was used before it went back, and the Chancery's 2 replace it.
        self.assertEqual((trace[1]["mana"], trace[1]["usable"]), (2, 1))
        self.assertEqual((trace[2]["land"], trace[2]["mana"]), ("Plains", 3))
        self.assertEqual(counts["drop"][1:], [1, 1, 1])
        # With only the Chancery, there's no land to play.
        trace, counts = script(["Azorius Chancery"] + ["Craw Wurm"] * 6 + BLANKS, turns=1)
        self.assertEqual((trace[0]["land"], counts["missed"]), (None, 1))

    def test_lotus_field_sacrifices_two_lands(self):
        order = ["Forest", "Forest", "Lotus Field"] + ["Craw Wurm"] * 4 + BLANKS
        trace, _ = script(order, turns=4)
        self.assertEqual([t["land"] for t in trace], ["Forest", "Forest", "Lotus Field", None])
        self.assertEqual(trace[2]["lands"], ["Lotus Field"])
        self.assertEqual([t["mana"] for t in trace], [1, 2, 3, 3])

    def test_a_land_that_makes_mana_now_goes_before_temple_of_the_false_god(self):
        # Review finding: with nothing to cast, the Temple (no mana until 5 lands) tied with Bonders'
        # Enclave and went first, so turn 1 had no mana.
        order = ["Temple of the False God", "Bonders' Enclave"] + ["Craw Wurm"] * 5 + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual([(t["land"], t["mana"]) for t in trace],
                         [("Bonders' Enclave", 1), ("Temple of the False God", 1)])

    def test_a_colour_the_deck_needs_before_a_second_forest(self):
        # Review finding: with no red spell in hand, a second Forest tied with the first Mountain.
        order = ["Forest", "Forest", "Mountain"] + ["Craw Wurm"] * 4 + BLANKS + ["Lightning Bolt"]
        trace, _ = script(order, turns=2)
        self.assertEqual([t["land"] for t in trace], ["Forest", "Mountain"])

    def test_myriad_landscape_is_a_tapped_colourless_land(self):
        order = ["Myriad Landscape"] + ["Craw Wurm"] * 6 + ["Forest", "Forest"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual((trace[0]["lands"], trace[0]["land_tapped"]), (["Myriad Landscape"], True))
        self.assertEqual(trace[2]["lands"], ["Forest", "Forest", "Myriad Landscape"])
        self.assertEqual(trace[2]["mana"], 3)

    def test_spell_land_card_is_a_land_only_without_another_land(self):
        mammoth = "Kazandu Mammoth // Kazandu Valley"
        trace, _ = script([mammoth, "Craw Wurm", "Craw Wurm"] + BLANKS, turns=1)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"]), (mammoth, True))
        # With Forests to play, it stays a spell and is cast on turn 3 ({1}{G}{G}).
        order = [mammoth, "Forest", "Forest", "Forest"] + BLANKS
        trace, counts = script(order, turns=3)
        self.assertEqual([t["land"] for t in trace], ["Forest"] * 3)
        self.assertEqual(trace[2]["cast"], [mammoth])
        self.assertEqual(counts["drop"][1:], [1, 1, 1])

    def test_a_land_whose_colour_is_chosen_makes_one_colour(self):
        # Review finding (a nearby case of Heraldic Banner's): Uncharted Haven, in every Beginner Box pairing,
        # counted as a source of every colour. It makes the one chosen as it enters: here red, for the Bolt.
        order = ["Uncharted Haven", "Forest", "Lightning Bolt", "Grizzly Bears"] + ["Craw Wurm"] * 3 + ["Forest"] + \
            BLANKS
        trace, counts = script(order, turns=2)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"]), ("Uncharted Haven", True))
        self.assertEqual([c[1] for c in counts["colour"]], [1, 0])     # turn 1: a red source, no green one
        E, ids = engine_for({"Uncharted Haven": 1, "Forest": 10, "Lightning Bolt": 4})
        haven = ids["Uncharted Haven"]
        self.assertEqual(sorted(E.LMASK[v] for v in E.CHOICES[haven]), [W, U, B, R, G])
        self.assertEqual(E.LMASK[goldfish._choose(E, haven, [ids["Lightning Bolt"]], G, [], NoShuffle())], R)
        # Nothing missing: what the deck needs.
        self.assertEqual(E.LMASK[goldfish._choose(E, haven, [], R, [], NoShuffle())], R)
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 Uncharted Haven\n"), "constructed")
        self.assertIn("makes one colour, chosen as it enters: the one you need most",
                      [c["rule"] for c in info["special"]])

    def test_a_chosen_colour_is_one_the_lands_in_hand_do_not_make(self):
        # Recheck finding: when the hand needed blue and black, Uncharted Haven always made the colour first in
        # WUBRG order (blue), even with an Island in hand, so the two halves of a pairing, mirror images,
        # showed one colour much worse than the other.
        E, ids = engine_for({"Uncharted Haven": 1, "Island": 8, "Swamp": 8, "Opt": 4, "Gifted Aetherborn": 4,
                             "Tormented Soul": 4})
        haven, island, swamp = ids["Uncharted Haven"], ids["Island"], ids["Swamp"]
        opt, aetherborn, soul = ids["Opt"], ids["Gifted Aetherborn"], ids["Tormented Soul"]

        def choose(spells, have, hand):
            return E.LMASK[goldfish._choose(E, haven, spells, have, [haven] + hand, NoShuffle())]

        self.assertEqual(choose([opt, aetherborn], 0, [island]), B)
        self.assertEqual(choose([opt, aetherborn], 0, [swamp]), U)
        # Only blue in hand, but an Island to play next: black, which the deck needs too.
        self.assertEqual(choose([opt], 0, [island]), B)
        self.assertEqual(choose([opt], 0, []), U)
        # Another Uncharted Haven could still make either colour, so it doesn't count as a source.
        self.assertEqual(choose([opt, aetherborn], 0, [haven, island]), B)
        # With nothing else to go on, the colour more of your spells need, not the first in WUBRG order.
        self.assertEqual(choose([opt, aetherborn, soul], 0, []), B)
        self.assertEqual(choose([opt, opt, soul], 0, []), U)
        # An exact tie goes at random, either way about as often.
        rng = random.Random(3)
        picks = Counter(E.LMASK[goldfish._choose(E, haven, [opt, soul], 0, [haven], rng)] for _ in range(2000))
        self.assertEqual(set(picks), {U, B})
        self.assertLess(abs(picks[U] - picks[B]), 250)
        # A search likewise finds the Swamp when there's an Island in hand, and a tie goes at random.
        library = [island, swamp] * 4
        self.assertEqual(goldfish._pick(E, library, 0, [True, 0], [opt, soul], 0, U, NoShuffle()), swamp)
        self.assertEqual(goldfish._pick(E, library, 0, [True, 0], [opt, soul], 0, B, NoShuffle()), island)
        picks = Counter(goldfish._pick(E, library, 0, [True, 0], [opt, soul], 0, 0, rng) for _ in range(2000))
        self.assertLess(abs(picks[island] - picks[swamp]), 250)
        # Heraldic Banner likewise: green, with a Plains still in hand for Serra Angel.
        E, ids = engine_for({"Forest": 10, "Plains": 5, "Heraldic Banner": 1, "Serra Angel": 4, "Grizzly Bears": 4})
        banner = E.EFF[ids["Heraldic Banner"]]
        hand = [ids["Serra Angel"], ids["Grizzly Bears"], ids["Plains"]]
        self.assertEqual(goldfish._source_mask(E, banner, hand, [], [], [], NoShuffle()), G)
        # A bounce land returns the Haven itself to your hand, to choose again.
        E, ids = engine_for({"Uncharted Haven": 1, "Azorius Chancery": 1, "Island": 8})
        haven, chancery = ids["Uncharted Haven"], ids["Azorius Chancery"]
        hand = []
        goldfish._land_enters(E, chancery, [[E.CHOICES[haven][0], 0], [chancery, 0]], hand, 0, 2)
        self.assertEqual(hand, [haven])

    def test_a_pathway_is_played_as_the_face_you_need(self):
        # Recheck finding: a Pathway (a land on both faces) made only its front face's colour.
        pathway = "Brightclimb Pathway // Grimclimb Pathway"
        E, ids = engine_for({pathway: 1, "Plains": 10})
        self.assertEqual(sorted(E.LMASK[v] for v in E.CHOICES[ids[pathway]]), [W, B])
        _, info = goldfish.compile_deck(parse(f"Deck\n10 Plains\n1 {pathway}\n"), "constructed")
        self.assertEqual([c["rule"] for c in info["special"]],
                         ["played as either face, making {W} or {B}: the one you need most"])
        # Turn 1: Grimclimb Pathway, untapped, for Tormented Soul.
        trace, counts = script([pathway, "Tormented Soul"] + ["Craw Wurm"] * 5 + BLANKS, turns=1)
        self.assertEqual((trace[0]["land"], trace[0]["land_tapped"], trace[0]["cast"]),
                         (pathway, False, ["Tormented Soul"]))
        # Turn 2, with a Swamp out: the face that lets you spend the most (black, for Gifted Aetherborn), not the
        # colour you don't have yet (white, for Dryad Militant alone).
        order = ["Swamp", "Gifted Aetherborn", "Dryad Militant"] + ["Craw Wurm"] * 4 + [pathway] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual((trace[0]["cast"], trace[1]["land"], trace[1]["cast"]), ([], pathway, ["Gifted Aetherborn"]))

    def test_river_of_tears_and_a_land_with_a_basic_land_type(self):
        # Recheck finding (nearby cases of the Pathways'): River of Tears lost its {B} ("If you played a land
        # this turn, add {B} instead") and Murmuring Bosk, a Forest, its {G}, which it has only as reminder text.
        E, ids = engine_for({"River of Tears": 1, "Murmuring Bosk": 1, "Forest": 10})
        self.assertEqual((E.LMASK[ids["River of Tears"]], E.LAMT[ids["River of Tears"]]), (U | B, 1))
        self.assertEqual((E.LMASK[ids["Murmuring Bosk"]], E.LAMT[ids["Murmuring Bosk"]]), (W | B | G, 1))
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 River of Tears\n"), "constructed")
        self.assertEqual([c["what"] for c in info["not_modelled"]],
                         ["which colour it makes depends on whether you played a land that turn, which isn't "
                          "modelled: it counts as either"])

    def test_min_lands_belongs_to_the_mana_ability(self):
        # Review finding: Cryptic Caves' "Activate only if you control five or more lands" is its draw
        # ability's, but its {C} waited for 5 lands.
        order = ["Cryptic Caves"] + ["Craw Wurm"] * 6 + ["Forest"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual([t["mana"] for t in trace], [1, 2])
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 Cryptic Caves\n"), "constructed")
        self.assertEqual(info["special"], [])

    def test_a_fetched_land_that_enters_tapped_by_its_own_text(self):
        # Review finding: Polluted Delta put a Zagoth Triome in untapped and used its mana at once.
        order = ["Polluted Delta", "Tormented Soul"] + ["Craw Wurm"] * 5 + ["Zagoth Triome"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual((trace[0]["lands"], trace[0]["land_tapped"], trace[0]["usable"], trace[0]["cast"]),
                         (["Zagoth Triome"], True, 0, []))

    def test_a_bounce_land_that_needs_an_untapped_land_cannot_use_its_mana_first(self):
        # Review finding: Coral Atoll returns an *untapped* Island, so that Island's mana can't pay for the
        # second Opt first (Azorius Chancery's can: see above). Its text also read "an Plains" for Karoo.
        order = ["Island", "Coral Atoll", "Opt", "Opt"] + ["Craw Wurm"] * 3 + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[0]["cast"], ["Opt"])
        self.assertEqual((trace[1]["land"], trace[1]["usable"], trace[1]["cast"]), ("Coral Atoll", 0, []))
        self.assertEqual(trace[1]["lands"], ["Coral Atoll"])
        self.assertIn("Island", trace[1]["hand"])
        _, info = goldfish.compile_deck(parse("Deck\n10 Island\n1 Coral Atoll\n1 Azorius Chancery\n"), "constructed")
        rules = {(c["name"], c["rule"]) for c in info["special"]}
        self.assertIn(("Coral Atoll", "returns an untapped Island you control to your hand when it enters (your least "
                                      "useful one, so that land's mana isn't used that turn), so it's only played "
                                      "when you have one"), rules)
        self.assertIn(("Azorius Chancery", "returns a land you control to your hand when it enters (your least useful "
                                           "one, after using its mana that turn), so it's only played when you have "
                                           "one"), rules)


class TestRamp(unittest.TestCase):

    def test_rampant_growth_fetches_a_needed_colour_tapped(self):
        order = ["Forest", "Forest", "Rampant Growth", "Hill Giant", "Craw Wurm", "Craw Wurm", "Craw Wurm",
                 "Forest", "Craw Wurm", "Mountain", "Forest"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[1]["cast"], ["Rampant Growth"])
        self.assertIn("Mountain", trace[1]["lands"])            # the Hill Giant needs red
        self.assertEqual(trace[1]["mana"], 2)                   # the new land came in tapped
        self.assertEqual(trace[2]["mana"], 4)
        self.assertEqual(trace[2]["cast"], ["Hill Giant"])

    def test_sakura_tribe_elder_is_sacrificed_at_once(self):
        order = ["Forest", "Forest", "Sakura-Tribe Elder", "Forest"] + BLANKS + ["Forest"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[1]["cast"], ["Sakura-Tribe Elder"])
        self.assertEqual(len(trace[1]["lands"]), 3)
        self.assertEqual(trace[2]["mana"], 4)

    def test_cultivate_puts_one_land_in_play_and_one_in_hand(self):
        order = ["Forest", "Forest", "Forest", "Cultivate"] + BLANKS + ["Forest", "Forest"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[2]["cast"], ["Cultivate"])
        self.assertEqual(len(trace[2]["lands"]), 4)
        self.assertIn("Forest", trace[2]["hand"])

    def test_wayfarers_bauble_uses_spare_mana(self):
        order = ["Forest", "Forest", "Wayfarer's Bauble", "Forest"] + BLANKS + ["Forest"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[0]["cast"], ["Wayfarer's Bauble"])
        self.assertEqual(trace[0]["abilities"], [])            # {2} to use it: not on turn 1
        self.assertEqual(trace[1]["abilities"], ["Wayfarer's Bauble"])
        self.assertEqual(trace[2]["mana"], 4)

    def test_springbloom_druid_sacrifices_a_land_for_two(self):
        order = ["Forest", "Forest", "Forest", "Springbloom Druid"] + BLANKS + ["Forest", "Forest"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[2]["cast"], ["Springbloom Druid"])
        self.assertEqual(len(trace[2]["lands"]), 4)             # 3 - 1 + 2

    def test_a_land_search_that_another_trigger_starts_never_happens(self):
        # Review finding: Ordeal of Nylea put two lands in as it was cast; its search comes only when it's
        # sacrificed, after its creature has attacked three times.
        order = ["Forest", "Forest", "Ordeal of Nylea"] + ["Craw Wurm"] * 4 + ["Forest"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[1]["cast"], ["Ordeal of Nylea"])
        self.assertEqual(len(trace[2]["lands"]), 3)
        _, info = goldfish.compile_deck(parse("Deck\n10 Forest\n1 Ordeal of Nylea\n"), "constructed")
        self.assertEqual(info["special"], [])
        self.assertEqual([c["what"] for c in info["not_modelled"]], [
            "its land search happens only when you sacrifice this aura, which isn't modelled, so it's never used"])

    def test_claim_jumper_needs_an_opponent(self):
        order = ["Plains", "Plains", "Plains", "Claim Jumper"] + BLANKS + ["Plains"]
        trace, _ = script(order, turns=3)
        self.assertEqual(trace[2]["cast"], ["Claim Jumper"])
        self.assertEqual(len(trace[2]["lands"]), 3)


class TestSpells(unittest.TestCase):

    def test_most_expensive_spell_first_then_what_still_fits(self):
        E, ids = engine_for({"Forest": 10, "Kitchen Finks": 1, "Grizzly Bears": 1, "Llanowar Elves": 1})
        cands = sorted([ids["Grizzly Bears"], ids["Llanowar Elves"], ids["Kitchen Finks"]], key=E.RANK.__getitem__)
        casts, used, spent, added = goldfish._plan(E, [G, G, G, G], cands, [], 4)
        self.assertEqual([E.NAMES[c] for c, _ in casts], ["Kitchen Finks", "Llanowar Elves"])
        self.assertEqual((used, spent, added), ([], 4, 0))
        casts, _, spent, _ = goldfish._plan(E, [G, G, G], cands, [], 3)
        self.assertEqual(([E.NAMES[c] for c, _ in casts], spent), (["Kitchen Finks"], 3))

    def test_split_card_casts_the_half_it_can(self):
        order = ["Island", "Island", "Fire // Ice"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual(trace[1]["cast"], ["Fire // Ice"])
        self.assertEqual(trace[1]["spent"], 2)

    def test_phyrexian_mana_is_paid_with_life(self):
        order = ["Forest", "Gitaxian Probe"] + BLANKS
        trace, _ = script(order, turns=1)
        self.assertEqual((trace[0]["cast"], trace[0]["spent"]), (["Gitaxian Probe"], 0))

    def test_x_spells(self):
        # Mockingbird with X = 0 is a 1-mana spell; Fireball needs X = 1, so two mana.
        order = ["Mountain", "Island", "Fireball", "Mockingbird"] + BLANKS
        trace, _ = script(order, turns=2)
        self.assertEqual((trace[0]["land"], trace[0]["cast"]), ("Island", ["Mockingbird"]))
        self.assertEqual((trace[1]["cast"], trace[1]["spent"]), (["Fireball"], 2))

    def test_commander_is_cast_from_the_command_zone(self):
        order = ["Forest", "Plains", "Craw Wurm"] + BLANKS
        trace, _ = script(order, turns=2, kind="commander", commander="Finneas, Ace Archer")
        self.assertEqual(trace[1]["cast"], ["Finneas, Ace Archer"])
        self.assertEqual(trace[1]["hand"], ["Craw Wurm"] * 6)

    def test_card_with_no_mana_cost_is_never_cast(self):
        order = ["Island"] * 3 + ["Ancestral Vision"] + BLANKS
        trace, _ = script(order, turns=3)
        self.assertTrue(all("Ancestral Vision" in t["hand"] for t in trace))


class TestMetricsInScriptedGames(unittest.TestCase):

    def test_flood_stuck_screw_and_first_big_spell(self):
        # The last Bears goes on turn 4, so turns 5 and 6 are flood turns.
        order = ["Forest"] * 4 + ["Grizzly Bears", "Grizzly Bears", "Grizzly Bears"] + ["Forest"] * 6
        trace, counts = script(order, turns=6)
        self.assertEqual([t["flood"] for t in trace], [False] * 4 + [True] * 2)
        self.assertEqual(counts["flood_turns"], 2)
        self.assertEqual(counts["big_never"], 1)
        # One land and a 2-drop: stuck on turn 2.
        order = ["Forest", "Grizzly Bears"] + BLANKS
        _, counts = script(order, turns=3)
        self.assertEqual((counts["stuck"], counts["missed"]), (1, 2))
        # A red spell with only Forests: colour screw every turn it's affordable.
        order = ["Forest", "Forest", "Lightning Bolt"] + BLANKS
        trace, counts = script(order, turns=3)
        self.assertEqual([t["screw"] for t in trace], [True, True, True])
        self.assertEqual((counts["screw"], counts["screw_wasted"]), (3, 3))
        # With a green 1-drop to cast instead, the screw costs no mana on turn 1.
        order = ["Forest", "Forest", "Lightning Bolt", "Llanowar Elves"] + BLANKS
        trace, counts = script(order, turns=1)
        self.assertEqual((trace[0]["screw"], trace[0]["cast"]), (True, ["Llanowar Elves"]))
        self.assertEqual((counts["screw"], counts["screw_wasted"]), (1, 0))

    def test_first_big_spell_turn(self):
        order = ["Mountain", "Mountain", "Mountain", "Mountain", "Hill Giant"] + BLANKS
        _, counts = script(order, turns=5)
        self.assertEqual(counts["big"][4], 1)

    def test_mana_used(self):
        order = ["Forest", "Forest", "Grizzly Bears"] + BLANKS
        _, counts = script(order, turns=2)
        self.assertEqual((counts["spent"][1:], counts["avail"][1:]), ([0, 2], [1, 2]))
        self.assertEqual((counts["all_used"][1:], counts["had_mana"][1:]), ([0, 1], [1, 1]))

    def colours(self, text):
        model, _ = goldfish.compile_deck(parse(text), "constructed")
        return model["colours"]

    def test_hybrid_and_two_generic_symbols_need_no_colour_of_their_own(self):
        # Review finding: {G/W} and {2/W} put a White row (always 0%) in a mono-green deck's table.
        self.assertEqual(self.colours("Deck\n24 Forest\n4 Dryad Militant\n32 Grizzly Bears\n"), [G])
        self.assertEqual(self.colours("Deck\n24 Forest\n4 Spectral Procession\n32 Grizzly Bears\n"), [G])
        # Hybrid alone needs either colour, so both are listed; a split card's halves likewise.
        self.assertEqual(self.colours("Deck\n12 Forest\n12 Plains\n36 Dryad Militant\n"), [W, G])
        self.assertEqual(self.colours("Deck\n24 Island\n36 Fire // Ice\n"), [U, R])
        self.assertEqual(self.colours("Deck\n24 Island\n30 Opt\n6 Fire // Ice\n"), [U])
        # Review finding: a deck that makes white pays {2/W} with {W} (the cheapest way), and colour
        # screw counted white, but the table had no White row. Now white is needed.
        self.assertEqual(self.colours("Deck\n24 Plains\n4 Spectral Procession\n32 Craw Wurm\n"), [W, G])
        self.assertEqual(self.colours("Deck\n12 Forest\n12 Plains\n4 Spectral Procession\n32 Grizzly Bears\n"),
                         [W, G])

    def test_two_generic_spell_is_not_colour_screw_in_a_deck_without_its_colour(self):
        # Spectral Procession costs 6 in a deck with no white, so 3 Forests aren't colour screw.
        order = ["Forest"] * 3 + ["Spectral Procession"] + ["Craw Wurm"] * 3 + ["Forest"] * 3 + BLANKS
        trace, counts = script(order, turns=6)
        self.assertEqual([t["screw"] for t in trace], [False] * 6)
        self.assertEqual(counts["screw"], 0)
        # With a Plains in the deck, one white source is enough: 3 mana.
        E, ids = engine_for({"Forest": 20, "Plains": 1, "Spectral Procession": 4})
        self.assertEqual(E.MINPAID[ids["Spectral Procession"]], 3)
        E, ids = engine_for({"Forest": 20, "Spectral Procession": 4})
        self.assertEqual(E.MINPAID[ids["Spectral Procession"]], 6)


if __name__ == "__main__":
    unittest.main()
