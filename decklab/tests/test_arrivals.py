"""Arrival notices (E6-S19, lib/arrivals.py and lib/api/arrivals.py): a receipt, from the Receipts page
or `python -m decklab.db receive`, keeps a notice for each home player whose decks it brought missing
cards for; that player alone sees it (GET /api/arrivals) until they dismiss it. Disposable trees, the
files backend, the fixture card data and an in-memory state store: nothing live is read or written."""
import json
from unittest import mock

from decklab.lib import access, arrivals, state
from decklab.lib.api import arrivals as arrivals_api, receipts
from decklab.lib.api.activity_summaries import _setting_summary
from decklab.lib.api.common import ApiError
from decklab.lib.state.memory import MemoryStore
from decklab.tests import household_config, test_receipts_api as base

setUpModule = base.setUpModule
tearDownModule = base.tearDownModule


def as_login(profile_id):
    """The block's requests come through the tunnel as profile_id's login (None: the home network, nobody named)."""
    return access.using(None if profile_id is None else {"profile": profile_id, "email": None, "remote": True})


class ArrivalCase(base.FilesReceiptCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.store = MemoryStore()
        self.addCleanup(state.use(self.store))

    def played_by(self, player, slug="test"):
        path = self.magic / f"decks/casual/{slug}.md"
        path.write_text(path.read_text(encoding="utf-8").replace("**Played by:** either", f"**Played by:** {player}"),
                        encoding="utf-8", newline="\n")

    def receive_web(self, components=("cards",)):
        data = base.WebReceiptTests.request_data(self, components)
        preview = receipts.preview_receipt(json.dumps(data))
        return receipts.apply_receipt(json.dumps({"profile": "matt", "preview": preview["preview"]}))

    def stored(self, profile_id):
        return arrivals.notices(profile_id)


class ReceiptRecordsNoticesTests(ArrivalCase):
    def test_the_page_receipt_tells_only_the_decks_player_how_many_cards_came(self):
        self.played_by("wife")
        answer = self.receive_web()
        self.assertTrue(answer["received"])
        notices = self.stored("user1")
        self.assertEqual([(n["order"], n["received_on"], n["decks"], n["more"]) for n in notices],
                         [("test", "2026-10-08", [["casual/test", 2]], 0)])
        self.assertEqual(self.stored("matt"), [])
        for person in ("user2", "user5"):
            self.assertEqual(self.store.settings(person), {})
        # The settings page never sees the notice's key.
        self.assertTrue(all(key.startswith("arrival_") for key in self.store.settings("user1")))

    def test_an_either_deck_tells_both_home_players(self):
        self.receive_web()
        self.assertEqual([n["decks"] for n in self.stored("matt")], [[["casual/test", 2]]])
        self.assertEqual([n["decks"] for n in self.stored("user1")], [[["casual/test", 2]]])

    def test_a_receipt_that_supplies_no_deck_tells_nobody(self):
        self.played_by("wife")
        self.receive_web(("kit",))          # Pick Your Poison and basics: no deck wants them
        self.assertEqual(self.stored("user1"), [])
        self.assertEqual(self.stored("matt"), [])

    def test_a_deck_with_its_cards_already_here_isnt_told_again(self):
        self.played_by("wife")
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                       ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.receive_web()                  # extra copies: the deck had what it needs
        self.assertEqual(self.stored("user1"), [])

    def test_the_command_line_receipt_records_and_says_who_is_told(self):
        self.played_by("wife")
        code, out, err = base.CommandLineReceiptTests.run_cli(
            self, "--order", "test", "--component", "cards", "--verified", "cards", "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 0, err)
        self.assertIn("User1 will see an arrival notice: 2 cards for 1 deck.", out)
        self.assertEqual([n["decks"] for n in self.stored("user1")], [[["casual/test", 2]]])
        self.assertEqual(self.stored("matt"), [])

    def test_a_store_that_cant_keep_it_never_fails_the_receipt(self):
        self.played_by("wife")
        logged = []
        with mock.patch.object(self.store, "settings_put", side_effect=state.Unavailable("down")), \
                mock.patch.object(receipts.common, "_log", logged.append):
            answer = self.receive_web()
        self.assertTrue(answer["received"])
        self.assertTrue(any("User1's arrival notice wasn't kept" in line for line in logged))

    def test_without_profiles_nothing_is_worked_out(self):
        with mock.patch.object(arrivals, "_players", side_effect=OSError("no config")), \
                mock.patch.object(arrivals, "supplied") as work:
            self.assertEqual(arrivals.record(None, None, "test", "2026-10-08", base.support.TESTER), {})
        work.assert_not_called()

    def test_a_full_set_of_slots_drops_the_oldest(self):
        actor = base.support.TESTER
        for i, slot in enumerate(arrivals.SLOTS):
            self.store.settings_put("user1", {slot: json.dumps({"o": f"old-{i}", "on": "", "d": [["casual/test", 1]],
                                                                "x": 0, "t": 100 + i})}, actor, "seed")
        self.played_by("wife")
        self.receive_web()
        orders = [n["order"] for n in self.stored("user1")]
        self.assertEqual(len(orders), len(arrivals.SLOTS))
        self.assertEqual(orders[0], "test")
        self.assertNotIn("old-0", orders)

    def test_a_long_list_keeps_within_a_settings_length(self):
        value = arrivals._value("2026-10-07-order", "2026-10-09",
                                [[f"commander/a-rather-long-deck-name-{i}", i + 1] for i in range(9)], 1)
        self.assertLessEqual(len(value), arrivals.MAX_VALUE)
        found = arrivals._parse(value)
        self.assertEqual(found["d"][0], ["commander/a-rather-long-deck-name-8", 9])     # most cards first
        self.assertEqual(len(found["d"]) + found["x"], 9)


class NoticeApiTests(ArrivalCase):
    def setUp(self):
        super().setUp()
        self.played_by("wife")
        self.receive_web()

    def test_the_player_sees_the_deck_by_title_with_its_count(self):
        with as_login("user1"):
            answer = arrivals_api.arrivals_view()
        [notice] = answer["notices"]
        self.assertEqual(notice["decks"], [{"id": "casual/test", "title": "Test", "cards": 2}])
        self.assertEqual((notice["order"], notice["received_on"], notice["cards"], notice["more"]),
                         ("test", "2026-10-08", 2, 0))

    def test_nobody_else_sees_it(self):
        for who in ("matt", "user2", "user5", None):
            with self.subTest(who=who), as_login(who):
                self.assertEqual(arrivals_api.arrivals_view(), {"notices": []})
        # A script naming nobody isn't anyone's visit either.
        self.assertEqual(arrivals_api.arrivals_view(), {"notices": []})

    def test_a_deck_the_viewer_may_not_see_or_that_is_gone_is_left_out(self):
        with as_login("user1"), mock.patch.object(arrivals_api.guard, "deck_reader", return_value=lambda deck: False):
            self.assertEqual(arrivals_api.arrivals_view(), {"notices": []})
        (self.magic / "decks/casual/test.md").unlink()
        with as_login("user1"):
            self.assertEqual(arrivals_api.arrivals_view(), {"notices": []})

    def test_dismissing_removes_it_for_good_and_only_the_one_shown(self):
        with as_login("user1"):
            [notice] = arrivals_api.arrivals_view()["notices"]
            # Someone else's dismissal can't name this one: the body must be the login's own.
            with self.assertRaises(ApiError) as caught:
                arrivals_api.dismiss_arrivals(json.dumps({"profile": "matt", "ids": [notice["id"]]}))
            self.assertEqual(caught.exception.status, 403)
            stale = notice["id"].split(":")[0] + ":" + "0" * 16
            self.assertEqual(len(arrivals_api.dismiss_arrivals(
                json.dumps({"profile": "user1", "ids": [stale]}))["notices"]), 1)
            self.assertEqual(arrivals_api.dismiss_arrivals(
                json.dumps({"profile": "user1", "ids": [notice["id"]]})), {"notices": []})
            self.assertEqual(arrivals_api.arrivals_view(), {"notices": []})
        self.assertEqual(self.stored("user1"), [])
        last = self.store.changes()[-1]
        self.assertIn("dismissed 1 arrival notice", last["message"])
        self.assertEqual(last["actor"], "user1")

    def test_a_bad_dismissal_is_refused(self):
        with as_login("user1"):
            for ids in ([], "x", [1], ["x"] * (arrivals_api.MAX_IDS + 1)):
                with self.subTest(ids=ids), self.assertRaises(ApiError) as caught:
                    arrivals_api.dismiss_arrivals(json.dumps({"profile": "user1", "ids": ids}))
                self.assertEqual(caught.exception.status, 400)

    def test_activity_words_name_no_stored_json(self):
        value = self.store.settings("user1")["arrival_a"]
        words = _setting_summary("INSERT", None, {"key": "arrival_a", "value": value}, "your")
        self.assertEqual(words, "Your arrival notice for order test")
        self.assertEqual(_setting_summary("DELETE", {"key": "arrival_a", "value": value}, None, "User1's"),
                         "User1's arrival notice dismissed")
