"""Counter defaults use visible card rules only; inventory and stored game snapshots stay separate."""
import unittest
from unittest import mock

from decklab.lib import cards, inventory
from decklab.lib.api import play_markers


class PlayMarkerSuggestionsTests(unittest.TestCase):
    def test_counter_kinds_reminder_links_and_faces_are_suggestions_without_inventory(self):
        index = {
            "Player counters": {"oracle_text": "An opponent gets a poison counter. You get {E}. You get an experience counter."},
            "Court": {"oracle_text": "", "faces": [{"oracle_text": "You become the monarch."}]},
            "Explorer": {"oracle_text": "When this enters, take the initiative."},
        }
        snapshot = {"sections": {"Deck": [{"name": name, "qty": 1} for name in index]}}
        with mock.patch.object(cards, "card", side_effect=lambda name: index[name]), \
                mock.patch.object(cards, "tokens_for", return_value=([], [])), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("Rules need no inventory")):
            self.assertEqual(play_markers.suggestions(snapshot), list(play_markers.KINDS))

    def test_linked_reminders_work_even_when_printing_text_omits_them(self):
        snapshot = {"sections": {"Deck": [{"name": "Linked reminders", "qty": 1}]}}
        with mock.patch.object(cards, "card", return_value={}), \
                mock.patch.object(cards, "tokens_for", return_value=([{"name": "The Monarch"}], ["The Initiative"])):
            self.assertEqual(play_markers.suggestions(snapshot), ["monarch", "initiative"])

    def test_a_missing_index_leaves_manual_marker_choices_available(self):
        with mock.patch.object(cards, "card", side_effect=RuntimeError("Index rebuilding")):
            self.assertEqual(play_markers.suggestions({"sections": {"Deck": [{"name": "A card", "qty": 1}]}}), [])
