"""Finite mana conservation, independently for each supported resource class."""
import json
import itertools
import unittest
from unittest import mock

from decklab.lib import cards, goldfish
from decklab.lib.goldfish import resources
from decklab.tests import test_goldfish as base


def setUpModule():
    base.setUpModule()
    rows = [json.loads(line) for line in base.CARDS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    template = next(row for row in rows if row["name"] == "Lotus Petal")
    extra = [
        ("Synthetic charge rock", "{2}", "Artifact", "This artifact enters tapped with three charge counters on it.\n{T}, Remove a charge counter from this artifact: Add one mana of any color."),
        ("Synthetic sunburst rock", "{2}", "Artifact", "Sunburst\n{T}, Remove a charge counter from this artifact: Add one mana of any color."),
        ("Synthetic bank rock", "{3}", "Artifact", "{T}: Add one mana of any color.\n{T}: Put a charge counter on this artifact.\nAt the beginning of your precombat main phase, remove all charge counters from this artifact. Add one mana of any color for each charge counter removed this way."),
        ("Synthetic single colour lotus", "{0}", "Artifact", "{T}, Sacrifice this artifact: Add three mana of any one color."),
        ("Synthetic other-body elf", "{G}", "Creature — Elf", "Tap another untapped creature you control: Add one mana of any color."),
    ]
    for i, (name, cost, types, text) in enumerate(extra):
        rows.append({**template, "name": name, "mana_cost": cost, "type_line": types, "oracle_text": text,
                     "oracle_id": f"00000000-0000-0000-0000-{i:012d}", "collector_number": str(i), "set": "sft"})
    source = base._tmp / "finite-cards.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    index = cards.build_index(source, base.TAGS_FILE, {}, log=lambda *args: None)
    path = base._tmp / "finite-index.json.gz"
    cards.write_index(index, path)
    cards.load(path)


tearDownModule = base.tearDownModule


class ResourceTests(unittest.TestCase):
    def test_noncreature_front_does_not_invent_a_back_face_assistant(self):
        card = dict(cards.card("Lightning Bolt"), type_line="Instant // Creature", layout="modal_dfc",
                    faces=[{"name": "Synthetic front", "type_line": "Instant", "mana_cost": "{R}", "oracle_text": ""},
                           {"name": "Synthetic back", "type_line": "Creature", "mana_cost": "{3}",
                            "oracle_text": "This creature enters tapped."}])
        model, _, _ = goldfish._card_model(card, 0)
        self.assertFalse(model["creature"])
        self.assertFalse(model["creature_tapped"])

    def context(self, names, turn=1):
        engine, ids = base.engine_for({**dict.fromkeys(names, 1), "Forest": 10})
        return engine, ids, resources.Context(engine, [], [], turn)

    def pay(self, context, pool, cost, card=None):
        option = goldfish._cost_options(cost, 0)[0]
        return context.supply(pool, 0, (), (option[0], option[1], tuple(option[2]), option[3]), card)

    def test_sacrifice_source_leaves_and_cannot_make_mana_again(self):
        engine, ids, context = self.context(["Lotus Petal"])
        context.spawn(ids["Lotus Petal"], [])
        self.assertIsNotNone(self.pay(context, [], "{R}"))
        self.assertEqual((context.sources, context.capacity([])), ([], 0))
        self.assertIsNone(self.pay(context, [], "{R}"))
        trace, _ = base.script(["Forest", "Lotus Petal", "Grizzly Bears"] + base.BLANKS, turns=2)
        self.assertEqual(trace[0]["cast"], ["Lotus Petal", "Grizzly Bears"])
        self.assertEqual(trace[1]["usable"], 1)
        self.assertEqual(engine.RESOURCE[ids["Lotus Petal"]]["classes"], ["sacrifice"])

    def test_charge_source_enters_tapped_and_each_counter_is_spent_once(self):
        engine, ids, context = self.context(["Synthetic charge rock"])
        context.spawn(ids["Synthetic charge rock"], [])
        self.assertIsNone(self.pay(context, [], "{R}"))
        for turn in (2, 3, 4):
            resources.begin_turn(engine, context.sources, context.creatures, turn)
            context.turn = turn
            self.assertIsNotNone(self.pay(context, [], "{R}"))
            self.assertIsNone(self.pay(context, [], "{G}"))
        resources.begin_turn(engine, context.sources, context.creatures, 5)
        context.turn = 5
        self.assertEqual(context.sources[0]["charges"], 0)
        self.assertIsNone(self.pay(context, [], "{R}"))

    def test_assistants_tap_once_new_bodies_can_help_and_own_body_is_excluded(self):
        engine, ids, context = self.context(["Springleaf Drum", "Grizzly Bears", "Synthetic other-body elf"])
        context.spawn(ids["Springleaf Drum"], [])
        self.assertIsNone(self.pay(context, [], "{R}"))
        context.spawn(ids["Grizzly Bears"], [])
        context.spawn(ids["Springleaf Drum"], [])
        self.assertEqual(context.capacity([]), 1)
        self.assertIsNotNone(self.pay(context, [], "{R}"))
        self.assertIsNone(self.pay(context, [], "{G}"))
        other = resources.Context(engine, [], [], 1)
        other.spawn(ids["Synthetic other-body elf"], [])
        self.assertIsNone(self.pay(other, [], "{R}"))
        other.spawn(ids["Grizzly Bears"], [])
        self.assertIsNotNone(self.pay(other, [], "{R}"))

    def test_ready_mana_dork_cannot_also_be_used_by_drum(self):
        engine, ids, context = self.context(["Springleaf Drum", "Llanowar Elves"])
        context.spawn(ids["Springleaf Drum"], [])
        context.spawn(ids["Llanowar Elves"], [])
        context.turn = 2
        resources.begin_turn(engine, context.sources, context.creatures, 2)
        self.assertEqual(context.capacity([base.G]), 1)
        self.assertIsNone(self.pay(context, [base.G], "{G}{R}"))

    def test_no_untap_resource_waits_until_spare_mana_pays_untap(self):
        engine, ids, context = self.context(["Basalt Monolith"])
        context.spawn(ids["Basalt Monolith"], [])
        self.assertIsNotNone(self.pay(context, [], "{3}"))
        context.turn = 2
        resources.begin_turn(engine, context.sources, context.creatures, 2)
        self.assertIsNone(self.pay(context, [], "{1}"))
        context.finish([base.G] * 3, 0, ())
        self.assertEqual(context.spent, 3)
        self.assertIsNotNone(self.pay(context, [], "{3}"))

    def test_single_colour_batch_cannot_pay_mixed_pips_and_cannot_self_fund_cast(self):
        _engine, ids, context = self.context(["Synthetic single colour lotus", "Basalt Monolith"])
        context.spawn(ids["Synthetic single colour lotus"], [])
        self.assertIsNone(self.pay(context, [], "{G}{W}"))
        self.assertIsNotNone(self.pay(context, [], "{G}{G}{G}"))
        engine, ids = base.engine_for({"Basalt Monolith": 1, "Craw Wurm": 1, "Forest": 10})
        plan = goldfish._plan(engine, [base.G] * 2, [ids["Craw Wurm"], ids["Basalt Monolith"]], [], 1)
        self.assertEqual(plan[0], [])

    def test_chalice_smallest_producing_form_and_sunburst_actual_colours(self):
        engine, ids, context = self.context(["Everflowing Chalice", "Synthetic sunburst rock"])
        self.assertEqual(engine.OPTS[ids["Everflowing Chalice"]][0], (0, 2, (), 2))
        self.assertEqual(goldfish._plan(engine, [base.G], [ids["Everflowing Chalice"]], [], 1)[0], [])
        card = ids["Synthetic sunburst rock"]
        option = engine.OPTS[card][0]
        for pool, expected in (([base.G, base.G], 1), ([base.G, base.W], 2), ([base.C, base.C], 0)):
            left, payment = resources.pay(pool, 0, (), option, True)
            context.spawn(card, payment)
            self.assertEqual((left, context.sources[-1]["charges"]), ([], expected))

    def test_sunburst_repeated_masks_preserve_exhaustive_payment_and_bound_search(self):
        def exhaustive(pool, generic):
            sources = sorted(pool, key=lambda mask: (goldfish.POP[mask], -mask))
            best, score = None, -1
            for picked in itertools.combinations(range(len(sources)), generic):
                value = resources._sunburst([sources[i] for i in picked])
                if value > score:
                    best, score = picked, value
            return ([mask for i, mask in enumerate(sources) if i not in best], [sources[i] for i in best])

        # Exhaustive matching on small adversarial palettes also checks the first-best tie rule.
        for pool in ([base.G] * 7 + [base.C] * 2, [base.G] * 6 + [base.W, base.U],
                     [base.G | base.W] * 5 + [base.G] * 4, [base.C] * 5):
            for generic in (1, 2, 3):
                self.assertEqual(resources.pay(pool, 0, (), (generic, generic, (), generic), True), exhaustive(pool, generic))

        pool = [base.G] * 20_000 + [base.C] * 20_000 + [base.W]
        examined = []
        def bounded(values, count):
            self.assertLessEqual(len(values), count * len(set(pool)))
            for picked in itertools.combinations(values, count):
                examined.append(1)
                yield picked
        with mock.patch.object(resources, "combinations", bounded):
            left, payment = resources.pay(pool, 0, (), (3, 3, (), 3), True)
        self.assertLessEqual(len(examined), 35)  # C(3G + 3C + 1W, 3), independent of physical pool size
        self.assertEqual(resources._sunburst(payment), 2)
        self.assertEqual(base.Counter(left + payment), base.Counter(pool))
        self.assertEqual(payment, exhaustive([base.G] * 3 + [base.C] * 3 + [base.W], 3)[1])

    def test_bank_release_is_classified_and_counters_release_once_next_turn(self):
        engine, ids, context = self.context(["Synthetic bank rock"])
        config = engine.RESOURCE[ids["Synthetic bank rock"]]
        self.assertIn("charge", config["classes"])
        context.spawn(ids["Synthetic bank rock"], [])
        context.finish([], 0, ())
        self.assertEqual(context.sources[0]["charges"], 1)
        released = resources.begin_turn(engine, context.sources, context.creatures, 2)
        self.assertEqual((len(released), context.sources[0]["charges"]), (1, 0))
        self.assertEqual(resources.begin_turn(engine, context.sources, context.creatures, 3), [])

    def test_special_rules_replace_skipped_class_notes_and_parallel_counts_are_identical(self):
        text = "Deck\n12 Forest\n8 Mountain\n3 Lotus Petal #Ramp\n3 Springleaf Drum #Ramp\n3 Everflowing Chalice #Ramp\n2 Basalt Monolith #Ramp\n5 Grizzly Bears #Bodies\n4 Lightning Bolt #Removal\n8 Craw Wurm #Plan\n"
        sections = base.parse(text)
        _, info = goldfish.compile_deck(sections, "constructed")
        self.assertFalse(any(row["name"] in ("Lotus Petal", "Springleaf Drum", "Everflowing Chalice", "Basalt Monolith") for row in info["not_modelled"]))
        with mock.patch.object(goldfish.runs, "CHUNK_GAMES", 8):
            a = goldfish.simulate(sections, "constructed", games=24, turns=4, seed=91, workers=1)
            b = goldfish.simulate(sections, "constructed", games=24, turns=4, seed=91, workers=2)
        self.assertEqual(a["results"], b["results"])

    def test_many_finite_sources_keep_spent_mana_and_category_counts_bounded(self):
        text = "Deck\n12 Forest\n8 Mountain\n4 Lotus Petal #Ramp\n4 Springleaf Drum #Ramp\n4 Everflowing Chalice #Ramp\n4 Basalt Monolith #Ramp\n8 Grizzly Bears #Bodies\n4 Lightning Bolt #Removal\n12 Craw Wurm #Plan\n"
        value = goldfish.simulate(base.parse(text), "constructed", games=200, turns=8, seed=19, workers=1)
        for result in value["results"].values():
            self.assertLessEqual(result["mana_used"]["share"], 1)
            for category in result["categories"]:
                for turn in category["by_turn"]:
                    rates = turn["at_least"]
                    self.assertEqual(rates, sorted(rates, reverse=True))
                    self.assertTrue(all(0 <= rate <= 1 for rate in rates))
        json.dumps(value, allow_nan=False)
