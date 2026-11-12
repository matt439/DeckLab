"""Tests for the popular-decks figure across a deck's saved versions (E3-S50): GET /api/gauntlet/history
(api/gauntlet_history.py) over gauntlet_before's revision walk, with its dates.

They run in test_gauntlet_before's ApiCase: test_gauntlet_api's sandbox with ByListGauntlet (games by
list, card_sha) and deck revisions from test_deck_history's WithHistory. No Forge game, network,
database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_history
"""
import json
import types
from datetime import datetime, timedelta, timezone
from unittest import mock

from decklab.lib import decks, feature_routes, inventory
from decklab.lib.api import gauntlet_before, gauntlet_history
from decklab.tests.test_deck_history import revision
from decklab.tests.test_gauntlet_api import ELVES, GRUUL, R_ELVES
from decklab.tests.test_gauntlet_before import ApiCase, _text

DAY = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def _at(n):
    return DAY + timedelta(days=n)


def _swap(text, old, new):
    assert old in text
    return text.replace(old, new)


class HistoryCase(ApiCase):

    def timeline(self, who="matt", deck_id=GRUUL, version="target"):
        return self.call(who, gauntlet_history.history_view, deck_id, version)

    def lists(self, forests, start=1):
        """Revisions of the given Forest counts, oldest first, one a day; the last one is today's (9)."""
        return [revision(GRUUL, n, _text(f), op="A" if n == start else "M", at=_at(n), actor="user1",
                         message="Secret words") for n, f in enumerate(forests, start)]


class TimelineTests(HistoryCase):

    def test_tested_lists_newest_first_with_date_figure_range_and_opponents(self):
        self.history({GRUUL: self.lists([12, 11, 10, 8, 9])})
        self.g.per = {self.sha(9): {self.ids[0]: 0.6, self.ids[1]: 0.5},
                      self.sha(8): {i: 0.4 for i in self.ids},
                      self.sha(11): {self.ids[0]: 0.3}}
        found = self.timeline()
        self.assertEqual((found["state"], found["complete"], found["notes"]), ("listed", True, []))
        self.assertEqual(found["sample"]["id"], "sample:0123456789ab")
        rows = found["lists"]
        self.assertEqual([r["current"] for r in rows], [True, False, False])
        self.assertEqual([r["state"] for r in rows], ["tested"] * 3)
        self.assertEqual(rows[0]["saved"], _at(5).isoformat())
        self.assertEqual(rows[1], {"current": False, "saved": _at(4).isoformat(), "state": "tested", "rate": 0.4,
                                   "low": 0.32, "high": 0.48, "played": 3, "of": 3, "games": 300,
                                   "updated": "2026-11-02T10:00:00", "older": None})
        self.assertEqual((rows[2]["saved"], rows[2]["rate"], rows[2]["played"]), (_at(2).isoformat(), 0.3, 1))
        # The untested list (10 Forests) isn't listed: its step spans both changes.
        self.assertEqual(len(found["steps"]), 2)
        self.assertEqual(found["steps"][1]["added"], [])
        self.assertEqual(found["steps"][1]["removed"], [[3, "Forest"]])

    def test_a_step_compares_only_the_shared_opponents_with_the_cards_changed(self):
        today = _text(9)                                    # the sandbox's saved deck
        before = _swap(_swap(_swap(today, "1 Sol Ring (MKM) 170\n", ""), "1 Black Lotus\n", ""),
                       "1 Opt (FDN) 512", "2 Opt (FDN) 512")
        self.history({GRUUL: [revision(GRUUL, 1, before, op="A", at=_at(1)), revision(GRUUL, 2, today, at=_at(2))]})
        parsed = decks.parse_deck(before.encode("utf-8"), "gruul-test", "casual", None, "home")
        then = self.forge.card_sha(parsed.target, "constructed")
        now = gauntlet_history.field_page._field_entry(self.forge, GRUUL, "target")[1]["card_sha"]
        self.g.per = {now: {self.ids[0]: 0.7, self.ids[1]: 0.5}, then: {self.ids[0]: 0.4, self.ids[2]: 0.5}}
        step = self.timeline()["steps"][0]
        self.assertEqual(step["added"], [[1, "Black Lotus"], [1, "Sol Ring"]])
        self.assertEqual(step["removed"], [[1, "Opt"]])
        self.assertEqual((step["more_added"], step["more_removed"]), (0, 0))
        self.assertEqual(step["compare"], {"same": 1, "before": {"rate": 0.4, "low": 0.32, "high": 0.48},
                                           "now": {"rate": 0.7, "low": 0.62, "high": 0.78}, "moved": 1})
        self.assertIsNone(step["uncompared"])

    def test_no_shared_opponents_are_left_uncompared(self):
        self.history({GRUUL: self.lists([8, 9])})
        self.g.per = {self.sha(9): {self.ids[0]: 0.6}, self.sha(8): {self.ids[1]: 0.4}}
        step = self.timeline()["steps"][0]
        self.assertEqual((step["compare"], step["uncompared"]), (None, "no_shared"))
        self.assertEqual(step["added"], [[1, "Forest"]])

    def test_todays_untested_list_heads_the_timeline_uncompared(self):
        self.history({GRUUL: self.lists([8, 9])})
        self.g.per = {self.sha(8): {self.ids[0]: 0.4}}
        found = self.timeline()
        self.assertEqual(found["state"], "listed")
        now = found["lists"][0]
        self.assertEqual((now["current"], now["state"], now["rate"], now["games"], now["updated"]),
                         (True, "untested", None, 0, None))
        self.assertEqual(found["steps"][0]["uncompared"], "no_figure")
        self.assertEqual(self.g.compared, 0)

    def test_a_list_tested_only_under_an_older_engine_is_muted(self):
        self.history({GRUUL: self.lists([7, 8, 9])})
        self.g.per = {self.sha(9): {self.ids[0]: 0.6}, self.sha(7): {self.ids[0]: 0.5}}
        self.g.has_notes = lambda entry, space: True
        self.g.older_by = {self.sha(8): {"reason": "pilot", "opponents": 2, "of": 3, "updated": "2026-10-20T10:00:00",
                                         "overall": {"rate": 0.41, "low": 0.33, "high": 0.49}}}
        found = self.timeline()
        rows = found["lists"]
        self.assertEqual([r["state"] for r in rows], ["tested", "older", "tested"])
        self.assertEqual((rows[1]["rate"], rows[1]["low"], rows[1]["high"], rows[1]["games"]), (None, None, None, 0))
        self.assertEqual(rows[1]["older"], {"reason": "pilot", "opponents": 2, "of": 3,
                                            "updated": "2026-10-20T10:00:00"})
        self.assertNotIn("0.41", json.dumps(found))           # no figure for a muted list
        self.assertEqual([s["uncompared"] for s in found["steps"]], ["no_figure", "no_figure"])

    def test_lists_without_standard_results_are_left_out(self):
        self.history({GRUUL: self.lists([6, 7, 8, 9])})
        self.g.per = {self.sha(6): {self.ids[0]: 0.5}}
        noted = {self.sha(6), self.sha(7)}               # 7 has notes of another sample only, 8 none at all
        self.g.has_notes = lambda entry, space: entry["card_sha"] in noted
        found = self.timeline()
        self.assertEqual(len(found["lists"]), 2)
        self.assertEqual(found["lists"][1]["rate"], 0.5)
        self.assertNotIn(self.sha(8), self.g.views)
        self.assertEqual(found["steps"][0]["added"], [[3, "Forest"]])
        self.assertEqual(found["steps"][0]["removed"], [])

    def test_nothing_tested(self):
        self.history({GRUUL: self.lists([8, 9])})
        found = self.timeline()
        self.assertEqual((found["state"], len(found["lists"]), found["complete"]), ("none", 1, True))

    def test_the_files_backend_has_only_todays_list(self):
        self.history({})
        self.g.per = {self.sha(9): {self.ids[0]: 0.5}}
        found = self.timeline()
        self.assertEqual((found["state"], len(found["lists"]), found["steps"]), ("listed", 1, []))
        self.assertIsNone(found["lists"][0]["saved"])

    def test_no_catalogue(self):
        self.g.built = False
        found = self.timeline()
        self.assertEqual((found["state"], found["sample"], found["lists"]), ("no_catalogue", None, []))

    def test_cards_changed_are_bounded(self):
        newer = {"Deck": [types.SimpleNamespace(quantity=1, name=f"Card {n:02d}")
                          for n in range(gauntlet_history.MAX_CHANGES + 5)]}
        step = gauntlet_history._changes(newer, {})
        self.assertEqual((len(step["added"]), step["more_added"]), (gauntlet_history.MAX_CHANGES, 5))
        self.assertEqual(step["added"][0], [1, "Card 00"])


class BoundTests(HistoryCase):

    def test_at_most_eight_lists_and_it_says_so(self):
        forests = list(range(30, 18, -1)) + [9]          # 12 earlier lists, every one tested
        self.history({GRUUL: self.lists(forests)})
        self.g.per = {self.sha(f): {self.ids[0]: 0.5} for f in forests}
        found = self.timeline()
        self.assertEqual(len(found["lists"]), 1 + gauntlet_history.MAX_SHOWN)
        self.assertEqual([r["saved"] for r in found["lists"][1:]],
                         [_at(n).isoformat() for n in range(12, 12 - gauntlet_history.MAX_SHOWN, -1)])
        self.assertFalse(found["complete"])
        self.assertIn(gauntlet_history.NOT_EVERY, found["notes"])
        self.assertEqual(len(self.g.views), 1 + gauntlet_history.MAX_SHOWN)

    def test_exactly_eight_lists_is_every_list(self):
        forests = list(range(20, 12, -1)) + [9]
        self.history({GRUUL: self.lists(forests)})
        self.g.per = {self.sha(f): {self.ids[0]: 0.5} for f in forests}
        found = self.timeline()
        self.assertEqual((len(found["lists"]), found["complete"], found["notes"]), (9, True, []))

    def test_eight_lists_and_older_lists_without_notes_is_every_list(self):
        forests = [21] + list(range(20, 12, -1)) + [9]   # the oldest (21 Forests) has no run notes
        self.history({GRUUL: self.lists(forests)})
        tested = {self.sha(f) for f in forests if f != 21}
        self.g.per = {sha: {self.ids[0]: 0.5} for sha in tested}
        self.g.has_notes = lambda entry, space: entry["card_sha"] in tested
        found = self.timeline()
        self.assertEqual((len(found["lists"]), found["complete"], found["notes"]), (9, True, []))
        # With notes, the ninth earlier list could have been shown: then it isn't every list.
        gauntlet_before.clear_cache()
        tested.add(self.sha(21))
        found = self.timeline()
        self.assertEqual((len(found["lists"]), found["complete"]), (9, False))
        self.assertIn(gauntlet_history.NOT_EVERY, found["notes"])

    def test_the_views_are_bounded(self):
        forests = list(range(40, 20, -1)) + [9]           # 20 earlier lists with notes, none tested
        self.history({GRUUL: self.lists(forests)})
        self.g.has_notes = lambda entry, space: True
        found = self.timeline()
        self.assertEqual(len(self.g.views), 1 + gauntlet_history.MAX_VIEWED)
        self.assertFalse(found["complete"])
        self.assertIn(gauntlet_history.NOT_EVERY, found["notes"])

    def test_the_revision_walk_bound_is_said(self):
        same = [revision(GRUUL, n, _text(9) + f"\n| Table row {n} |\n", at=_at(2)) for n in range(2, 260)]
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A", at=_at(1))] + same})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}, self.sha(9): {self.ids[0]: 0.5}}
        found = self.timeline()
        self.assertEqual(len(found["lists"]), 1)
        self.assertFalse(found["complete"])
        self.assertIn(gauntlet_history.NOT_EVERY, found["notes"])

    def test_unreadable_revisions_leave_a_note(self):
        self.g.per = {self.sha(9): {self.ids[0]: 0.5}}
        with mock.patch.object(inventory, "deck_revisions_with_text", side_effect=inventory.Unavailable("down")):
            found = self.timeline()
        self.assertIn(gauntlet_before.NO_HISTORY, found["notes"])
        self.assertEqual(len(found["lists"]), 1)

    def test_the_earlier_part_is_cached(self):
        self.history({GRUUL: self.lists([8, 9])})
        self.g.per = {self.sha(8): {self.ids[0]: 0.4}, self.sha(9): {self.ids[0]: 0.6}}
        reads = []
        real = inventory.deck_revisions_with_text
        with mock.patch.object(inventory, "deck_revisions_with_text", lambda *a: reads.append(1) or real(*a)):
            first = self.timeline()
            again = self.timeline()
        self.assertEqual(len(reads), 1)
        self.assertEqual(first, again)


class DatesTests(HistoryCase):

    def test_a_list_is_dated_by_the_oldest_revision_of_its_newest_run(self):
        # 8 saved on day 1, a table refresh on day 2, 9 on day 3, 8 again on day 4 and 9 on day 5 (today's).
        revs = [revision(GRUUL, 1, _text(8), op="A", at=_at(1)),
                revision(GRUUL, 2, _text(8) + "\n| Table |\n", at=_at(2)),
                revision(GRUUL, 3, _text(7), at=_at(3)),
                revision(GRUUL, 4, _text(8), at=_at(4)),
                revision(GRUUL, 5, _text(8) + "\n| Table |\n", at=_at(5)),
                revision(GRUUL, 6, _text(9), at=_at(6)),
                revision(GRUUL, 7, _text(9) + "\n| Table |\n", at=_at(7))]
        self.history({GRUUL: revs})
        summary, entry = gauntlet_history.field_page._field_entry(self.forge, GRUUL, "target")
        dates = {}
        found, note, capped = gauntlet_before._earlier(self.forge, summary, entry, dates)
        self.assertEqual([sha for sha, _ in found], [self.sha(8), self.sha(7)])
        self.assertEqual((note, capped), (None, False))
        self.assertEqual(dates, {self.sha(9): _at(6), self.sha(8): _at(4), self.sha(7): _at(3)})

    def test_an_unparsed_list_ends_a_run(self):
        # Today's list (9) saved on day 4; days 2 and 3 hold no readable decklist; day 1 held 9 too.
        unread = "# Gruul Test\n\nNo list here.\n"
        revs = [revision(GRUUL, 1, _text(9), op="A", at=_at(1)),
                revision(GRUUL, 2, unread, at=_at(2)),
                revision(GRUUL, 3, unread + "\nMore prose.\n", at=_at(3)),
                revision(GRUUL, 4, _text(9), at=_at(4)),
                revision(GRUUL, 5, _text(9) + "\n| Table |\n", at=_at(5))]
        self.history({GRUUL: revs})
        summary, entry = gauntlet_history.field_page._field_entry(self.forge, GRUUL, "target")
        dates = {}
        found, note, capped = gauntlet_before._earlier(self.forge, summary, entry, dates)
        self.assertEqual((found, note, capped), ([], None, False))
        self.assertEqual(dates, {self.sha(9): _at(4)})

    def test_an_owned_list_missing_from_older_revisions_keeps_its_date(self):
        # Days 1 and 2 have no owned-only list; it was first saved on day 3.
        plain = _text(9).split("## Substitutes")[0]
        revs = [revision(GRUUL, 1, plain, op="A", at=_at(1)),
                revision(GRUUL, 2, plain + "\n| Table |\n", at=_at(2)),
                revision(GRUUL, 3, _text(9), at=_at(3)),
                revision(GRUUL, 4, _text(9) + "\n| Table |\n", at=_at(4))]
        self.history({GRUUL: revs})
        summary, entry = gauntlet_history.field_page._field_entry(self.forge, GRUUL, "owned")
        dates = {}
        found, _, _ = gauntlet_before._earlier(self.forge, summary, entry, dates)
        self.assertEqual(found, [])
        self.assertEqual(dates, {entry["card_sha"]: _at(3)})

    def test_the_list_bound_still_says_so(self):
        forests = list(range(40, 15, -1)) + [9]
        self.history({GRUUL: self.lists(forests)})
        summary, entry = gauntlet_history.field_page._field_entry(self.forge, GRUUL, "target")
        found, _, capped = gauntlet_before._earlier(self.forge, summary, entry)
        self.assertEqual((len(found), capped), (gauntlet_before.MAX_LISTS, True))
        exact = list(range(40, 20, -1)) + [9]            # exactly MAX_LISTS earlier lists: every one
        self.history({GRUUL: self.lists(exact)})
        found, _, capped = gauntlet_before._earlier(self.forge, summary, entry)
        self.assertEqual((len(found), capped), (gauntlet_before.MAX_LISTS, False))


class PrivacyTests(HistoryCase):

    def test_a_hidden_deck_is_missing_and_reads_no_revision(self):
        with mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("read")):
            self.assertEqual(self.timeline("user2", GRUUL), 404)
            self.assertEqual(self.timeline("matt", R_ELVES), 404)
        self.assertEqual(self.g.views, [])

    def test_no_revision_actor_message_or_other_deck_in_the_answer(self):
        self.history({GRUUL: self.lists([8, 9])})
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.6}}
        found = self.timeline()
        text = json.dumps(found)
        for hidden in ("Secret words", "user1", '"revision"', ELVES, R_ELVES, "Elf Commander", "gauntlet:"):
            self.assertNotIn(hidden, text)
        self.assertEqual(len(found["lists"]), 2)

    def test_a_member_reads_their_own_decks_timeline(self):
        found = self.timeline("user2", R_ELVES)
        self.assertEqual(found["deck"]["id"], R_ELVES)

    def test_the_request_needs_an_id(self):
        self.assertEqual(self.timeline("matt", None), 400)

    def test_the_route(self):
        self.assertEqual(feature_routes.ACCESS[("GET", "gauntlet/history")], "deck")
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": GRUUL}
        with mock.patch.object(gauntlet_history, "history_view", return_value={"state": "none"}) as called:
            self.assertTrue(feature_routes.dispatch(handler, ["gauntlet", "history"], {}))
        called.assert_called_once()
        handler._send_json.assert_called_once_with(200, {"state": "none"})


if __name__ == "__main__":
    import unittest
    unittest.main()
