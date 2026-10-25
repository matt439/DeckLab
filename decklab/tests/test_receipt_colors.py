"""Optional receipt deck colours reuse visible Planned sections without changing receipt evidence."""
import copy
import json
import unittest
import zlib
from unittest import mock

from decklab.lib import decks, inventory, pool
from decklab.lib.api import common, guard, receipts
from decklab.lib.api.common import ApiError
from decklab.lib.decks.identity import CardIdentityError
from decklab.lib.inventory import files, receive
from decklab.tests import test_receipts_api as board

setUpModule = board.setUpModule
tearDownModule = board.tearDownModule


class ReceiptColorTests(board.FilesReceiptCase):
    def test_planned_identity_reuses_the_loaded_sections_and_never_mutates_summaries_or_shared_answers(self):
        self.deck('test', 'Test', 'built', 'Deck\n2 Llanowar Elves (FDN) 227\n1 Rhystic Study\n57 Forest\n',
                  owned='Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n', built_version='owned')
        self.cards_csv('orders/test.csv', ('Llanowar Elves', 'fdn', '227', 'nonfoil', 1),
                       ('Llanowar Elves', 'fdn', '9999', 'nonfoil', 1))
        source = next(summary for summary in decks.list_decks() if summary['id'] == 'casual/test')
        source['colors'] = ['R']            # A stale summary value must never replace the actual target.
        before = copy.deepcopy(source)
        found = pool.load_pool()
        loaded = []
        real_load = decks.load_deck

        def load(*args, **kwargs):
            sections = real_load(*args, **kwargs)
            loaded.append((args, sections))
            return sections

        with mock.patch.object(decks, 'list_decks', return_value=[source]), \
                mock.patch.object(decks, 'load_deck', side_effect=load), \
                mock.patch.object(pool, 'load_pool', return_value=found) as pooled, \
                mock.patch.object(receipts, 'deck_colors', wraps=receipts.deck_colors) as colors:
            view = receipts.receipt_view('test')
        pooled.assert_called_once_with()
        colors.assert_called_once()
        self.assertIs(colors.call_args.args[0], loaded[0][1])
        self.assertEqual(loaded[0][0], ('casual/test', 'target'))
        for args, sections in loaded:
            if args[1] == 'owned':
                self.assertIsNot(colors.call_args.args[0], sections)
        rows = view['components'][0]['decks']
        self.assertEqual([row[0]['colors'] for row in rows], [['U', 'G'], ['U', 'G']])
        self.assertEqual(source, before)
        rows[0][0]['colors'].append('B')
        self.assertEqual(rows[1][0]['colors'], ['U', 'G'])
        self.assertEqual(source['colors'], ['R'])

    def test_shared_identity_rules_keep_commander_sideboard_colourless_and_unknown_distinct(self):
        cases = [
            ('Commander\n1 Rhystic Study\n\nDeck\n1 Llanowar Elves\n', ['U']),
            ('Deck\n1 Llanowar Elves\n\nSideboard\n1 Rhystic Study\n', ['G']),
            ('Deck\n1 Sol Ring\n', []),
            ('Deck\n1 Unknown fixture card\n', None),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(receipts._planned_colors(decks.parse_decklist(text)), expected)

    def test_known_colourless_receipt_identity_stays_an_empty_array(self):
        self.deck('test', 'Colourless fixture', 'idea', 'Deck\n1 Sol Ring\n59 Forest\n')
        self.cards_csv('orders/test.csv', ('Sol Ring', 'tst', '1', 'nonfoil', 1))
        view = receipts.receipt_view('test')
        hint = view['components'][0]['decks'][0][0]
        self.assertEqual(hint['colors'], [])
        self.assertEqual(hint['title'], 'Colourless fixture')
        self.assertEqual((hint['uses'], hint['waiting']), (1, 1))

    def test_optional_index_faults_remove_only_colors_and_each_request_retries(self):
        canonical = receive.delivery(inventory.current(), 'test')['components'][0]['rows']
        before = files.tree_files(self.root)
        revision = self.inventory.revision()
        with mock.patch.object(receipts, 'deck_colors', return_value=None):
            baseline = receipts.receipt_view('test')
        errors = [CardIdentityError('Fixture bad identity'), FileNotFoundError('Fixture absent index'),
                  EOFError('Fixture truncated index'), UnicodeDecodeError('utf8', b'\xff', 0, 1, 'fixture'),
                  json.JSONDecodeError('Fixture bad index', '{', 0), zlib.error('Fixture broken gzip')]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(receipts, 'deck_colors', side_effect=error) as colors, \
                    mock.patch.object(common, '_log') as logged:
                view = receipts.receipt_view('test')
                self.assertEqual(view, baseline)
                self.assertIsNone(view['components'][0]['decks'][0][0]['colors'])
                self.assertEqual(view['components'][0]['rows'], canonical)
                self.assertEqual(view['fingerprint'], receipts.fingerprint(revision))
                self.assertNotIn(str(error), json.dumps(view))
                colors.assert_called_once()
                logged.assert_not_called()
        self.assertEqual(files.tree_files(self.root), before)
        with mock.patch.object(receipts, 'deck_colors', return_value=['G']) as retried:
            view = receipts.receipt_view('test')
        retried.assert_called_once()
        self.assertEqual(view['components'][0]['decks'][0][0]['colors'], ['G'])

    def test_programming_faults_use_the_existing_guidance_failure_boundary(self):
        for error in (KeyError('fixture bug'), TypeError('fixture bug'), ValueError('fixture bug'), RuntimeError('fixture bug')):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(receipts, 'deck_colors', side_effect=error), \
                    mock.patch.object(common, '_log') as logged:
                view = receipts.receipt_view('test')
                self.assertTrue(all(part['decks'] is None for part in view['components']))
                self.assertEqual(view['kits'], {})
                self.assertTrue(view['components'][0]['rows'])
                logged.assert_called_once()

    def test_visibility_and_home_choices_are_checked_before_any_target_or_color_read(self):
        visible = {'id': 'casual/test', 'title': 'Visible', 'status': 'idea', 'kind': 'casual', 'space': 'home'}
        hidden = dict(visible, id='casual/hidden', title='Hidden fixture title')
        summaries = [visible, hidden, dict(visible, id='user2/casual/private', title='Private fixture title'),
                     dict(visible, space='user2', title='Wrong fixture space'),
                     dict(visible, id='product/kit/deck', title='Product fixture title'),
                     dict(visible, id='pairing/a+b', title='Pairing fixture title'),
                     dict(visible, id='commander/wrong', title='Wrong fixture kind'),
                     dict(visible, id='casual/broken', error='Fixture unreadable')]
        original = copy.deepcopy(summaries)
        target = decks.parse_decklist('Deck\n2 Llanowar Elves (FDN) 227\n')
        sees = mock.Mock(side_effect=lambda summary: summary['id'] != hidden['id'])
        with mock.patch.object(guard, 'deck_reader', return_value=sees) as reader, \
                mock.patch.object(decks, 'list_decks', return_value=summaries), \
                mock.patch.object(decks, 'load_deck', return_value=target) as loaded, \
                mock.patch.object(pool, 'load_pool', return_value=object()) as pooled, \
                mock.patch.object(pool, 'owned_vs_needed', return_value={'rows': [{'name': 'Llanowar Elves', 'need': 2}]}), \
                mock.patch.object(pool, 'row_labels', return_value={'on_the_way': [('order test', 2)]}), \
                mock.patch.object(receipts, '_kits', return_value={}), \
                mock.patch.object(receipts, 'deck_colors', return_value=['G']) as colors:
            view = receipts.receipt_view('test')
        reader.assert_called_once_with()
        self.assertEqual([call.args[0]['id'] for call in sees.call_args_list], ['casual/test', 'casual/hidden'])
        loaded.assert_called_once_with('casual/test', 'target')
        pooled.assert_called_once_with()
        colors.assert_called_once_with(target)
        self.assertEqual(view['components'][0]['decks'][0], [dict(id='casual/test', title='Visible', status='idea',
                                                              colors=['G'], uses=2, waiting=2)])
        self.assertEqual(summaries, original)
        for title in ('Hidden fixture title', 'Private fixture title', 'Product fixture title', 'Pairing fixture title'):
            self.assertNotIn(title, json.dumps(view))

    def test_denied_home_and_visibility_failures_never_read_colors_or_private_targets(self):
        with mock.patch.object(guard, 'sees_home_records', return_value=False), \
                mock.patch.object(inventory, 'current') as inv, \
                mock.patch.object(receipts, '_index_info') as index, \
                mock.patch.object(receipts, 'deck_colors') as colors:
            with self.assertRaises(ApiError) as caught:
                receipts.receipt_view('test')
            self.assertEqual(caught.exception.status, 403)
            inv.assert_not_called()
            index.assert_not_called()
            colors.assert_not_called()
        with mock.patch.object(guard, 'deck_reader', side_effect=OSError('Fixture visibility unavailable')), \
                mock.patch.object(decks, 'load_deck') as target, \
                mock.patch.object(receipts, 'deck_colors') as colors, \
                mock.patch.object(common, '_log'):
            view = receipts.receipt_view('test')
        target.assert_not_called()
        colors.assert_not_called()
        self.assertIsNone(view['components'][0]['decks'])

    def test_decoration_adds_no_inventory_pool_or_target_reads_and_keeps_canonical_rows(self):
        counts = []
        before = files.tree_files(self.root)
        for decorated in (False, True):
            with mock.patch.object(inventory, 'current', wraps=inventory.current) as inv, \
                    mock.patch.object(pool, 'load_pool', wraps=pool.load_pool) as pooled, \
                    mock.patch.object(decks, 'load_deck', wraps=decks.load_deck) as loaded:
                if decorated:
                    view = receipts.receipt_view('test')
                else:
                    with mock.patch.object(receipts, '_planned_colors', return_value=None):
                        view = receipts.receipt_view('test')
                counts.append((inv.call_count, pooled.call_count, loaded.call_args_list))
            self.assertEqual(set(view['components'][0]['rows'][0]), set(view['components'][0]['fields']))
        self.assertEqual(counts[0], counts[1])
        self.assertEqual(files.tree_files(self.root), before)


if __name__ == '__main__':
    unittest.main()
