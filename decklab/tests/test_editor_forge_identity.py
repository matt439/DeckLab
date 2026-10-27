"""Optional saved-list evidence identifies the exact parsed edit snapshot, without games."""
from types import SimpleNamespace
import unittest
from unittest import mock

from decklab.lib.api import editor
from decklab.lib.forge import lists
from decklab.tests.test_editor import EditorTestCase


class EditorForgeIdentityTests(EditorTestCase):
    def test_edit_view_fingerprints_match_both_loaded_versions(self):
        from decklab.lib import api, decks
        answer = api.edit_view('casual/gruul-test')
        deck = decks.read_deck_file(self.path('casual/gruul-test'))
        self.assertEqual(answer['forge_lists'], {
            'target': lists.card_sha(deck.target, 'constructed'),
            'owned': lists.card_sha(deck.owned, 'constructed')})
        self.assertIsNone(api.edit_view('casual/table-test')['forge_lists']['owned'])
        self.assertNotIn('forge_lists', api.edit_view('product/fdc-test-precon'))

    def test_optional_identity_failure_preserves_the_editable_deck_and_its_lists(self):
        from decklab.lib import api
        with mock.patch.object(lists, 'card_sha', side_effect=RuntimeError('optional fixture fault')), \
                mock.patch.object(editor.common, '_log') as log:
            answer = api.edit_view('casual/gruul-test')
        self.assertTrue(answer['editable'])
        self.assertTrue(answer['lists']['target']['Deck'])
        self.assertEqual(answer['sha256'], self.sha('casual/gruul-test'))
        self.assertEqual(answer['forge_lists'], {})
        log.assert_called_once()


class PlayableIdentityTests(unittest.TestCase):
    def test_printing_order_sideboard_and_companion_do_not_change_playable_identity(self):
        line = lambda name, qty=1: SimpleNamespace(name=name, quantity=qty)
        a, b = line('Llanowar Elves'), line('Elvish Mystic', 3)
        deck = SimpleNamespace(kind='casual', target={'Deck': [a, b]}, owned=None)
        before = editor._forge_lists(deck)
        a.set, a.finish = 'fixture', 'foil'
        deck.target = {'Deck': [b, a], 'Sideboard': [line('Opt')], 'Companion': [line('Forest')]}
        self.assertEqual(editor._forge_lists(deck), before)
        b.quantity += 1
        self.assertNotEqual(editor._forge_lists(deck)['target'], before['target'])
        self.assertIsNone(editor._forge_lists(deck)['owned'])

    def test_commander_role_and_constructed_main_use_the_engines_exact_semantics(self):
        a = SimpleNamespace(name='Synthetic Commander', quantity=1)
        deck = SimpleNamespace(kind='commander', target={'Commander': [a], 'Deck': []}, owned={})
        commander = editor._forge_lists(deck)['target']
        deck.kind = 'casual'
        folded = editor._forge_lists(deck)
        deck.target = {'Deck': [a]}
        self.assertEqual(folded, editor._forge_lists(deck))
        self.assertNotEqual(commander, folded['target'])
        self.assertIsNone(folded['owned'])
