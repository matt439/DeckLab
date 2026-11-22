"""config.json's "shops" setting: which price-check shops are read and shown (E11-S53, first slice).

Run: python scripts/test_fixtures.py decklab.tests.test_shops_setting
Every setting and snapshot is supplied here; no shop, real snapshot file or configured config is read.
"""
import contextlib
import io
import unittest
from unittest import mock

from decklab.lib import config, shops
from decklab.lib.api import shop_baskets, shop_missing_prices, shop_prices
from decklab.tests.test_shop_baskets import entry, games_portal, listing, mtgmate, row


def setting(value=None, present=True):
    settings = dict(config.DEFAULTS)
    if present:
        settings["shops"] = value
    return mock.patch.object(config, "load", return_value=settings)


class EnabledAdaptersTests(unittest.TestCase):
    def setUp(self):
        shops._said.clear()
        self.addCleanup(shops._said.clear)

    def keys(self, value=None, present=True):
        with setting(value, present), contextlib.redirect_stderr(io.StringIO()) as err:
            return [adapter.key for adapter in shops.enabled_adapters()], err.getvalue()

    def test_unset_means_every_available_shop(self):
        self.assertEqual(self.keys(present=False), (["mtgmate"], ""))
        self.assertEqual(self.keys(None), (["mtgmate"], ""))

    def test_a_list_keeps_only_available_shops(self):
        self.assertEqual(self.keys(["gamesportal"])[0], [])
        self.assertEqual(self.keys(["GamesPortal", " mtgmate "])[0], ["mtgmate"])

    def test_empty_list_turns_the_check_off(self):
        self.assertEqual(self.keys([]), ([], ""))

    def test_unknown_keys_are_left_out_and_said_once(self):
        keys, said = self.keys(["mtgmate", "cardkingdom"])
        self.assertEqual(keys, ["mtgmate"])
        self.assertIn("cardkingdom", said)
        self.assertEqual(self.keys(["mtgmate", "cardkingdom"])[1], "")      # once a process

    def test_a_value_that_isnt_a_list_counts_as_unset(self):
        keys, said = self.keys("mtgmate")
        self.assertEqual(keys, ["mtgmate"])
        self.assertIn("isn't a list", said)


class NightlyTests(unittest.TestCase):
    def test_off_skips_the_shop_step_and_says_so(self):
        lines = []
        with setting([]), mock.patch.object(shops, "refresh") as refresh:
            self.assertEqual(shops.nightly(lines.append), 0)
        refresh.assert_not_called()
        self.assertEqual(len(lines), 1)
        self.assertIn("skipped", lines[0])
        self.assertIn('"shops"', lines[0])

    def test_a_disabled_shop_is_not_dispatched(self):
        with setting(["gamesportal"]), mock.patch.object(shops, "refresh") as refresh:
            self.assertEqual(shops.nightly(lambda _words: None), 0)
        refresh.assert_not_called()

    def test_nightly_reads_only_the_available_shop(self):
        for configured in (None, ["gamesportal", "mtgmate"]):
            with self.subTest(configured=configured), setting(configured), \
                    mock.patch.object(shops, "refresh", return_value=0) as refresh:
                self.assertEqual(shops.nightly(lambda _words: None), 0)
                self.assertEqual([call.kwargs["adapter"].key for call in refresh.call_args_list], ["mtgmate"])


class CommandTests(unittest.TestCase):
    def run_main(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = shops.main(list(argv))
        return code, out.getvalue()

    def test_snapshot_and_show_say_no_shop_is_set(self):
        with setting([]), mock.patch.object(shops, "refresh") as refresh, \
                mock.patch.object(shops, "load") as load:
            for command in ("snapshot", "show"):
                code, said = self.run_main(command)
                self.assertEqual(code, 0)
                self.assertIn("No available price-check shop is enabled", said)
        refresh.assert_not_called()
        load.assert_not_called()

    def test_snapshot_shop_still_asks_one_by_hand(self):
        with setting([]), mock.patch.object(shops, "refresh", return_value=0) as refresh:
            self.assertEqual(self.run_main("snapshot", "--shop", "mtgmate")[0], 0)
        self.assertEqual([call.kwargs["adapter"].key for call in refresh.call_args_list], ["mtgmate"])


class PageTests(unittest.TestCase):
    def captured(self):
        card = entry(listing("2.00", 3))
        return {"mtgmate": mtgmate({"Sol Ring": card}), "gamesportal": games_portal({"Sol Ring": card})}

    def test_capture_reads_only_enabled_shops(self):
        with setting(["mtgmate"]), mock.patch.object(shops, "load", return_value=mtgmate({})) as load:
            found = shop_prices.capture()
        self.assertEqual(list(found), ["mtgmate"])
        self.assertEqual([call.kwargs["adapter"].key for call in load.call_args_list], ["mtgmate"])

    def test_off_reads_nothing_and_shopping_says_so(self):
        with setting([]), mock.patch.object(shops, "load") as load:
            self.assertIsNone(shop_prices.capture())
            answer = {"to_buy": [row("Sol Ring", 1)]}
            shop_prices.enrich(answer, data=self.captured())
        load.assert_not_called()
        self.assertIn("No available price-check shop is enabled", answer["shops_off"])
        self.assertNotIn("shop_snapshots", answer)
        self.assertNotIn("shop_snapshots", answer["to_buy"][0])

    def test_disabled_shop_snapshot_is_not_shown_as_a_current_source(self):
        with setting(present=False):
            answer = shop_prices.enrich({"to_buy": [row("Sol Ring", 1)]}, data=self.captured())
        self.assertNotIn("shops_off", answer)
        self.assertEqual([item["shop"] for item in answer["shop_snapshots"]], ["MTGMate"])

    def test_baskets_only_for_enabled_shops(self):
        with setting(["gamesportal", "mtgmate"]):
            built = shop_baskets.build([row("Sol Ring", 1)], self.captured(), "rev-1")
        self.assertEqual([basket["key"] for basket in built["shops"]], ["mtgmate"])

    def test_missing_cards_get_no_shop_lines_when_off(self):
        rows = [{"name": "Sol Ring", "missing": 1}]
        with setting([]):
            shop_missing_prices.enrich_shops(rows, self.captured(), None)
        self.assertNotIn("shop_snapshots", rows[0])
        with setting(["mtgmate"]):
            shop_missing_prices.enrich_shops(rows, self.captured(), None)
        self.assertEqual([item["shop"] for item in rows[0]["shop_snapshots"]], ["MTGMate"])


if __name__ == "__main__":
    unittest.main()
