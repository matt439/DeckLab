"""Selected packing participants carry existing Planned colours as optional decoration only."""
import copy
import json
from unittest import mock

from decklab.lib import decks, inventory, pool
from decklab.lib.api import assembly, assembly_completion, common, library
from decklab.lib.api.common import ApiError
from decklab.lib.decks.identity import CardIdentityError
from decklab.lib.inventory import files
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


class AssemblyColorsTests(PreparationCase):
    def plan(self, *choices):
        return assembly.assembly_preview(json.dumps({'decks': list(choices)}))

    def choice(self, slug, version='target', **extra):
        return {'id': f'casual/{slug}', 'version': version, **extra}

    def test_planned_identity_is_independent_of_owned_and_sideboard_recipe(self):
        self.deck('a', 'A', 'building', 'Deck\n1 Rhystic Study\n\nSideboard\n1 Elvish Mystic\n',
                  owned='Deck\n1 Llanowar Elves\n\nSideboard\n1 Wrath of God\n')
        self.cards_csv('collection.csv', ('Rhystic Study', 'tst', '1', 'nonfoil', 1),
                       ('Elvish Mystic', 'tst', '1', 'nonfoil', 1), ('Llanowar Elves', 'tst', '1', 'nonfoil', 1))
        for version, recipe in [('target', {}), ('owned', {}), ('owned', {'Wrath of God': 1})]:
            selected = self.choice('a', version, sideboard=recipe)
            with self.subTest(version=version, sideboard=recipe):
                result = self.plan(selected)
                self.assertEqual(result['decks'][0]['colors'], ['U'])
                self.assertEqual(result['decks'][0]['version'], version)
                self.assertEqual(result['selections'], [selected])
                self.assertEqual(result['decks'][0]['build_scope']['sideboard_count'], sum(recipe.values()))
        self.assertEqual(self.plan(self.choice('a', 'owned', sideboard={}))['decks'][0]['finishes'],
                         {'Llanowar Elves': [{'finish': 'nonfoil', 'quantity': 1}]})

    def test_commander_known_colourless_and_unknown_are_not_replaced_by_card_colours(self):
        self.deck('leader', 'Leader', 'idea', 'Commander\n1 Ghalta, Primal Hunger\n\nDeck\n1 Rhystic Study\n', kind='commander')
        self.deck('colorless', 'Colourless', 'idea', 'Deck\n1 Sol Ring\n')
        self.deck('unknown', 'Unknown', 'idea', 'Deck\n1 Unknown fixture card\n')
        selected = [{'id': 'commander/leader', 'version': 'target'}, self.choice('colorless'), self.choice('unknown')]
        result = self.plan(*selected)
        self.assertEqual([item['colors'] for item in result['decks']], [['G'], [], None])
        self.assertEqual(result['selections'], selected)
        self.assertIn('Unknown fixture card', result['unresolved'])

    def test_summary_color_arrays_are_copied_without_mutating_the_loaded_summary(self):
        self.deck('a', 'A', 'idea', 'Deck\n1 Llanowar Elves\n')
        source = assembly._deck_sections
        captured = []

        def read(*args):
            summary, sections = source(*args)
            captured.append((summary, copy.deepcopy(summary)))
            return summary, sections

        with mock.patch.object(assembly, '_deck_sections', side_effect=read) as loaded:
            result = self.plan(self.choice('a'))
        loaded.assert_called_once_with('casual/a', 'target')
        summary, before = captured[0]
        self.assertEqual(summary, before)
        self.assertEqual(result['decks'][0]['colors'], ['G'])
        self.assertIsNot(result['decks'][0]['colors'], summary['colors'])
        result['decks'][0]['colors'].append('R')
        self.assertEqual(summary['colors'], ['G'])

    def test_identity_failure_keeps_the_existing_unknown_fallback_and_valid_plan(self):
        self.deck('a', 'A', 'idea', 'Deck\n1 Llanowar Elves\n')
        with mock.patch.object(library, 'deck_colors', side_effect=CardIdentityError('Fixture bad identity')), \
                mock.patch.object(common, '_log') as logged:
            result = self.plan(self.choice('a'))
        self.assertIsNone(result['decks'][0]['colors'])
        self.assertEqual(result['decks'][0]['title'], 'A')
        self.assertEqual(result['selections'], [self.choice('a')])
        self.assertEqual(result['rows'][0]['name'], 'Llanowar Elves')
        logged.assert_called_once()                # Existing library shelf fallback, unchanged here.

    def test_decoration_adds_no_reads_or_changes_to_allocation_completion_or_tick_context(self):
        self.deck('a', 'A', 'building', 'Deck\n2 Llanowar Elves\n', owned='Deck\n1 Elvish Mystic\n')
        self.cards_csv('collection.csv', ('Llanowar Elves', 'fdn', '227', 'nonfoil', 3),
                       ('Elvish Mystic', 'cmm', '648', 'nonfoil', 1))
        selected = self.choice('a', 'owned', sideboard={})
        original = copy.deepcopy(selected)
        source = assembly._deck_sections
        plans, reads = [], []
        before = files.tree_files(self.magic.parent)

        def without_colors(*args):
            summary, sections = source(*args)
            summary = dict(summary)
            summary.pop('colors', None)
            return summary, sections

        for decorated in (False, True):
            with mock.patch.object(inventory, 'current', wraps=inventory.current) as inv, \
                    mock.patch.object(pool, 'load_pool', wraps=pool.load_pool) as pooled, \
                    mock.patch.object(decks, 'load_deck', wraps=decks.load_deck) as loaded:
                if decorated:
                    plan = self.plan(selected)
                else:
                    with mock.patch.object(assembly, '_deck_sections', side_effect=without_colors):
                        plan = self.plan(selected)
                reads.append((inv.call_count, pooled.call_count, loaded.call_args_list))
            plans.append(plan)
        self.assertEqual(reads[0], reads[1])
        self.assertEqual(plans[0]['decks'][0].pop('colors'), None)
        self.assertEqual(plans[1]['decks'][0].pop('colors'), ['G'])
        self.assertEqual(plans[0], plans[1])        # Includes completion fingerprint, assembly keys and rows.
        self.assertEqual(selected, original)
        self.assertEqual(files.tree_files(self.magic.parent), before)
        self.assertEqual(assembly_completion._fingerprint(inventory.current(), [selected]),
                         plans[1]['completion']['fingerprint'])
        with self.assertRaises(ApiError) as caught:
            self.plan(dict(selected, colors=['R']))
        self.assertEqual(caught.exception.status, 400)  # Decoration remains absent from accepted requests.

    def test_only_selected_participants_gain_colors_and_all_twelve_remain_available(self):
        for index in range(13):
            self.deck(f'd{index}', f'Deck {index}', 'idea', 'Deck\n1 Llanowar Elves\n')
        selected = [self.choice(f'd{index}') for index in range(12)]
        result = self.plan(*selected)
        self.assertEqual(len(result['decks']), 12)
        self.assertEqual(result['selections'], selected)
        self.assertEqual([item['colors'] for item in result['decks']], [['G']] * 12)
        self.assertEqual(len({id(item['colors']) for item in result['decks']}), 12)
        view = assembly.assembly_view(deck='casual/d0')
        self.assertTrue(all('colors' not in choice for choice in view['choices']))
        self.assertEqual(view['decks'][0]['colors'], ['G'])
        with mock.patch.object(assembly, '_deck_sections') as read, self.assertRaises(ApiError) as caught:
            self.plan(*selected, self.choice('d12'))
        self.assertEqual(caught.exception.status, 400)
        read.assert_not_called()
