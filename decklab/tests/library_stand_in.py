"""A test's stand-in for the deck library (E11-S90): the summaries list_decks() and
beginner_box_pairings() return and the ones decks.find_summary() looks a deck up in.

find_summary() reads the library's one kept reading (decks._kept_summaries and
decks._kept_pairing_summaries), not list_decks(), so a test standing in for the library patches
all four, each with its own copy of the given summaries.
"""
import copy
from unittest import mock

from decklab.lib import decks


def patches(summaries, pairings=(), module=decks):
    """The mock patchers that make the library hold exactly summaries and pairings."""
    summaries, pairings = list(summaries), list(pairings)

    def index():
        found = {}
        for summary in summaries:
            found.setdefault(summary["id"], summary)
        return found
    return [mock.patch.object(module, "list_decks", side_effect=lambda only_space=None: copy.deepcopy(summaries)),
            mock.patch.object(module, "beginner_box_pairings", side_effect=lambda: copy.deepcopy(pairings)),
            mock.patch.object(module, "_kept_summaries", side_effect=index),
            mock.patch.object(module, "_kept_pairing_summaries", side_effect=lambda: pairings)]


def start(test, summaries, pairings=(), module=decks):
    """Start patches() for the rest of a test (each stopped in its cleanup)."""
    for patcher in patches(summaries, pairings, module):
        patcher.start()
        test.addCleanup(patcher.stop)
