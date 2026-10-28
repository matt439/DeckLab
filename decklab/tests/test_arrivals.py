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

    def test_one_copy_wanted_by_several_unbuilt_decks_is_counted_once(self):
        # One Llanowar Elves comes; three of User1's decks, none built, each want it.
        self.cards_csv("orders/test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        text = (self.magic / "decks/casual/test.md").read_text(encoding="utf-8")
        for slug in ("test-b", "test-c"):
            (self.magic / f"decks/casual/{slug}.md").write_text(text.replace("# Test", f"# {slug}"),
                                                                 encoding="utf-8", newline="\n")
        for slug in ("test", "test-b", "test-c"):
            self.played_by("wife", slug)
        self.receive_web()
        [notice] = self.stored("user1")
        self.assertEqual(notice["decks"], [["casual/test", 1]])
        self.assertEqual(sum(cards for _, cards in notice["decks"]), 1)

    def test_a_built_deck_is_dealt_the_copies_first(self):
        gains = {"casual/a": ("wife", False, {"Bolt": 1}), "casual/b": ("wife", True, {"Bolt": 1}),
                 "casual/c": ("user", False, {"Bolt": 1})}
        self.assertEqual(arrivals._deal(gains, {"Bolt": 1}, ("wife", "either")), {"casual/b": 1})
        self.assertEqual(arrivals._deal(gains, {"Bolt": 2}, ("wife", "either")), {"casual/a": 1, "casual/b": 1})
        self.assertEqual(arrivals._deal(gains, {"Bolt": 1}, ("user", "either")), {"casual/c": 1})

    def seed(self, group, order, at):
        self.store.settings_put("user1", {f"arrival_{group}_a": json.dumps(
            {"o": order, "on": "", "d": [["casual/test", 1]], "x": 0, "t": at})}, base.support.TESTER, "seed")

    def test_a_full_set_drops_the_oldest(self):
        for i in range(arrivals.MAX_NOTICES):
            self.seed("old" + "abcdefgh"[i] * 7, f"old-{i}", 100 + i)
        self.played_by("wife")
        self.receive_web()
        orders = [n["order"] for n in self.stored("user1")]
        self.assertEqual(len(orders), arrivals.MAX_NOTICES)
        self.assertEqual(orders[0], "test")
        self.assertNotIn("old-0", orders)
        self.assertFalse(any(key.startswith("arrival_oldaaaaaaa") for key in self.store.settings("user1")))

    def test_two_receipts_kept_at_once_never_write_over_each_other(self):
        # Both read the settings before either writes (the page and the command line together).
        self.played_by("wife")
        before = self.store.settings("user1")
        snapshot = self.inventory.load()
        self.receive_web()
        after = self.inventory.load()
        with mock.patch.object(self.store, "settings", return_value=before):
            arrivals.record(snapshot, after, "other-order", "2026-10-08", base.support.TESTER)
        self.assertEqual(sorted(n["order"] for n in self.stored("user1")), ["other-order", "test"])

    def test_a_long_list_is_split_over_parts_within_a_settings_length(self):
        decks = [[f"commander/a-rather-long-deck-name-{i}", i + 1] for i in range(12)]
        values = arrivals._values("2026-10-07-order", "2026-10-09", decks, 1)
        self.assertGreater(len(values), 1)
        self.assertTrue(all(len(value) <= arrivals.MAX_VALUE for value in values))
        saved = {f"arrival_abcdefghij_{part}": value for part, value in zip("abcdef", values)}
        [notice] = arrivals.notices("user1", saved)
        self.assertEqual(notice["decks"][0], ["commander/a-rather-long-deck-name-11", 12])     # most cards first
        self.assertEqual(sorted(map(tuple, notice["decks"])), sorted(map(tuple, decks)))
        self.assertEqual(notice["more"], 0)
        # Past MAX_PARTS parts the rest are counted, never dropped silently.
        many = [[f"commander/a-rather-long-deck-name-{i}", 1] for i in range(60)]
        values = arrivals._values("o", "", many, 1)
        self.assertEqual(len(values), arrivals.MAX_PARTS)
        found = arrivals.notices("user1", {f"arrival_abcdefghij_{p}": v for p, v in zip("abcdef", values)})[0]
        self.assertEqual(len(found["decks"]) + found["more"], 60)
        self.assertGreater(found["more"], 0)

    def test_a_very_long_order_id_is_cut_short_not_dropped(self):
        values = arrivals._values("x" * 300, "2026-10-09", [["casual/test", 2]], 1)
        self.assertTrue(all(len(value) <= arrivals.MAX_VALUE for value in values))
        found = arrivals._parse(values[0])
        self.assertEqual(len(found["o"]), arrivals.MAX_ORDER)
        self.assertTrue(found["o"].endswith("…"))
        self.assertEqual(found["d"], [["casual/test", 2]])


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

    def test_a_renamed_deck_is_found_under_its_new_name(self):
        path = self.magic / "decks/casual/test.md"
        path.rename(path.with_name("renamed.md"))
        load = self.inventory.load
        with as_login("user1"), mock.patch.object(
                self.inventory, "load", lambda *a, **k: load(*a, **k).replace(deck_aliases={"casual/test": "casual/renamed"})):
            [notice] = arrivals_api.arrivals_view()["notices"]
        self.assertEqual([deck["id"] for deck in notice["decks"]], ["casual/renamed"])
        self.assertEqual(notice["cards"], 2)

    def test_a_dismissal_saved_while_the_decks_cant_be_read_still_answers(self):
        with as_login("user1"):
            [notice] = arrivals_api.arrivals_view()["notices"]
            self.store.settings_put("user1", {"arrival_otherorder_a": json.dumps(
                {"o": "other", "on": "", "d": [["casual/test", 1]], "x": 0, "t": 1})}, base.support.TESTER, "seed")
            with mock.patch.object(arrivals_api, "_shown", side_effect=arrivals_api.inventory.Unavailable("down")):
                answer = arrivals_api.dismiss_arrivals(json.dumps({"profile": "user1", "ids": [notice["id"]]}))
        self.assertEqual(answer, {"notices": [], "unshown": True})
        self.assertEqual([n["order"] for n in self.stored("user1")], ["other"])

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
        [(key, value)] = self.store.settings("user1").items()
        words = _setting_summary("INSERT", None, {"key": key, "value": value}, "your")
        self.assertEqual(words, "Your arrival notice for order test")
        self.assertEqual(_setting_summary("DELETE", {"key": key, "value": value}, None, "User1's"),
                         "User1's arrival notice removed")
        self.assertIsNone(arrivals_api.arrivals.is_key("theme") or None)
