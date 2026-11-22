"""Shopping's Baskets with postage (E5-S27): each shop's postage rules, the add-ons that reach its
free-postage threshold, and the fewest-shops plan.

Run: python scripts/test_fixtures.py decklab.tests.test_shop_plan
Every snapshot and rule is supplied here; no shop, snapshot file or configured database is read.
"""
import unittest
from unittest import mock

from decklab.lib import access, shops, state
from decklab.lib.api import shop_baskets, shop_plan, shop_postage
from decklab.lib.state import Actor, Conflict, Invalid, memory
from decklab.lib.state import shop_postage as rules_postage
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_shop_baskets import entry, games_portal, listing, mtgmate, row

MATT = Actor("matt", "Matt")


def rules(mtg=(None, None), gp=(None, None)):
    return {"mtgmate": {"postage_aud": mtg[0], "free_over_aud": mtg[1]},
            "gamesportal": {"postage_aud": gp[0], "free_over_aud": gp[1]}}


def build(rows, mtg=None, gp=None, postage=None):
    captured = {key: value for key, value in (("mtgmate", mtg), ("gamesportal", gp)) if value}
    return shop_baskets.build(rows, captured or None, "rev-1", postage, adapters=shops.SNAPSHOT_ADAPTERS)


def basket(built, key):
    return next(item for item in built["shops"] if item["key"] == key)


class PostageTests(unittest.TestCase):
    def test_flat_postage_free_threshold_and_unknown(self):
        D = shop_plan.Decimal
        paid = shop_plan.postage({"postage_aud": "8.50", "free_over_aud": "100.00"}, D("40"))
        self.assertEqual((paid["charged_aud"], paid["free"], paid["short_by_aud"], paid["known"]), ("8.50", False, "60.00", True))
        free = shop_plan.postage({"postage_aud": "8.50", "free_over_aud": "100.00"}, D("100"))
        self.assertEqual((free["charged_aud"], free["free"], free["short_by_aud"]), ("0.00", True, None))
        unknown = shop_plan.postage({}, D("5"))
        self.assertEqual((unknown["charged_aud"], unknown["known"], unknown["short_by_aud"]), (None, False, None))
        # Over the threshold is free even when the flat postage isn't known; under it stays unknown.
        self.assertTrue(shop_plan.postage({"free_over_aud": "50.00"}, D("60"))["free"])
        under = shop_plan.postage({"free_over_aud": "50.00"}, D("20"), unpriced=1)
        self.assertEqual((under["charged_aud"], under["short_by_aud"], under["at_least"]), (None, "30.00", True))
        self.assertTrue(shop_plan.postage({"postage_aud": "0"}, D("1"))["free"])

    def test_reach_takes_the_smallest_total_over_the_gap(self):
        add_ons = [{"queue_row": 1, "line_aud": "6.00"}, {"queue_row": 2, "line_aud": "4.00"},
                   {"queue_row": 3, "line_aud": "3.50"}, {"queue_row": 4, "line_aud": None}]
        found = shop_plan.reach(add_ons, "7.00")
        self.assertEqual((sorted(found["rows"]), found["total_aud"], found["reaches"]), ([2, 3], "7.50", True))
        short = shop_plan.reach(add_ons, "20.00")
        self.assertEqual((short["reaches"], short["total_aud"]), (False, "13.50"))
        self.assertIsNone(shop_plan.reach(add_ons, None))
        self.assertIsNone(shop_plan.reach([{"queue_row": 4, "line_aud": None}], "1.00"))

    def test_reach_falls_back_to_cheapest_first_for_a_large_gap(self):
        add_ons = [{"queue_row": n, "line_aud": f"{n * 100}.00"} for n in range(1, 30)]
        found = shop_plan.reach(add_ons, "2500.00")
        self.assertTrue(found["reaches"])
        self.assertGreaterEqual(shop_plan.Decimal(found["total_aud"]), shop_plan.Decimal("2500"))


class BasketPostageTests(unittest.TestCase):
    def test_basket_says_its_postage_and_marks_the_add_ons_that_reach_free_postage(self):
        rows = [row("Sol Ring", 1), row("Arcane Signet", 2, state="long_term"), row("Command Tower", 3, state="waiting_for_stock"),
                row("Swords to Plowshares", 4, state="long_term")]
        built = build(rows, mtgmate({"Sol Ring": entry(listing("40.00", 5)), "Arcane Signet": entry(listing("6.00", 2)),
                                     "Command Tower": entry(listing("5.00", 2)), "Swords to Plowshares": entry(listing("12.00", 1))}),
                      postage=rules(mtg=("8.50", "50.00")))
        mtg = basket(built, "mtgmate")
        self.assertEqual((mtg["postage"]["charged_aud"], mtg["postage"]["short_by_aud"]), ("8.50", "10.00"))
        self.assertEqual(mtg["reach"], {"rows": [2, 3], "total_aud": "11.00", "reaches": True})
        self.assertEqual({item["name"]: item["lifts"] for item in mtg["add_ons"]},
                         {"Arcane Signet": True, "Command Tower": True, "Swords to Plowshares": False})
        self.assertTrue(built["postage_read"])

    def test_unreadable_rules_leave_every_postage_unknown(self):
        built = build([row("Sol Ring", 1)], mtgmate({"Sol Ring": entry(listing("1.00", 5))}), postage=None)
        self.assertFalse(built["postage_read"])
        self.assertFalse(basket(built, "mtgmate")["postage"]["known"])
        self.assertIsNone(basket(built, "gamesportal")["postage"])     # no snapshot there


class PlanTests(unittest.TestCase):
    def snapshots(self):
        rows = [row("Sol Ring", 1), row("Llanowar Elves", 2), row("Counterspell", 3)]
        mtg = mtgmate({"Sol Ring": entry(listing("2.00", 5)), "Llanowar Elves": entry(listing("0.50", 5)),
                       "Counterspell": entry(listing("1.20", 5))})
        gp = games_portal({"Sol Ring": entry(listing("1.80", 1), at="2026-11-01T02:30:00+11:00"),
                           "Llanowar Elves": entry(listing("0.40", 1), at="2026-11-01T02:30:00+11:00")})
        return rows, mtg, gp

    def test_fewer_shops_win_when_the_postage_saved_outweighs_the_price_difference(self):
        rows, mtg, gp = self.snapshots()
        plan = build(rows, mtg, gp, rules(mtg=("8.00", None), gp=("7.00", None)))["plan"]
        self.assertTrue(plan["weighed"])
        self.assertEqual(plan["recommended"]["keys"], ["mtgmate"])
        self.assertEqual((plan["recommended"]["cards_aud"], plan["recommended"]["total_aud"]), ("3.70", "11.70"))
        self.assertEqual(plan["by_price"]["keys"], ["mtgmate", "gamesportal"])
        self.assertEqual((plan["by_price"]["cards_aud"], plan["by_price"]["total_aud"]), ("3.40", "18.40"))
        self.assertEqual(plan["saves_aud"], "6.70")
        self.assertEqual((plan["wanted"], plan["recommended"]["cards"]), (3, 3))

    def test_a_shop_that_cant_cover_everything_is_never_recommended(self):
        rows, mtg, gp = self.snapshots()
        plan = build(rows, mtg, gp, rules(mtg=("50.00", None), gp=("0.00", None)))["plan"]
        # Games Portal posts free but lacks Counterspell: both shops, each card where it's cheapest.
        self.assertEqual(plan["recommended"]["keys"], ["mtgmate", "gamesportal"])
        gp_only = next(option for option in plan["options"] if option["keys"] == ["gamesportal"])
        self.assertEqual((gp_only["cards"], [item["name"] for item in gp_only["uncovered"]]), (2, ["Counterspell"]))

    def test_unknown_postage_recommends_the_fewest_shops_without_weighing(self):
        rows, mtg, gp = self.snapshots()
        plan = build(rows, mtg, gp, rules(mtg=("8.00", None)))["plan"]
        self.assertFalse(plan["weighed"])
        self.assertEqual(plan["recommended"]["keys"], ["mtgmate"])
        self.assertIsNone(plan["saves_aud"])
        self.assertEqual(plan["by_price"]["postage_unknown"], ["Games Portal"])

    def test_a_short_shop_fills_the_rest_at_the_next(self):
        rows = [row("Sol Ring", 1, quantity="3")]
        built = build(rows, mtgmate({"Sol Ring": entry(listing("1.00", 1))}),
                      games_portal({"Sol Ring": entry(listing("2.00", 1), at="2026-11-01T02:30:00+11:00")}),
                      rules(mtg=("0.00", None), gp=("5.00", None)))
        plan = built["plan"]
        self.assertEqual(plan["recommended"]["keys"], ["mtgmate", "gamesportal"])
        lines = {shop["key"]: shop["rows"][0] for shop in plan["recommended"]["shops"]}
        self.assertEqual((lines["mtgmate"]["copies"], lines["gamesportal"]["copies"], lines["gamesportal"]["line_aud"]),
                         (1, 2, "4.00"))

    def test_each_price_tier_competes_across_counted_shops_and_postage_changes_recommendation(self):
        rows = [row("Sol Ring", 1, quantity="2")]
        snapshots = {
            "mtgmate": mtgmate({"Sol Ring": entry(listing("1.00", 1), listing("20.00", 1, set_code="cmm"))}),
            "gamesportal": games_portal({"Sol Ring": entry(listing("5.00", 2, set_code="m19"))}),
        }
        counted = [mock.patch.object(shops.ADAPTERS[key], "counts_stock", True) for key in snapshots]
        adapters = shops.SNAPSHOT_ADAPTERS
        with counted[0], counted[1]:
            free = shop_baskets.build(rows, snapshots, "q1", rules(mtg=("0", None), gp=("0", None)), adapters)["plan"]
            paid = shop_baskets.build(rows, snapshots, "q1", rules(mtg=("6", None), gp=("0", None)), adapters)["plan"]
        for plan in (free["by_price"], free["recommended"], paid["by_price"]):
            self.assertEqual(plan["cards_aud"], "6.00")
            self.assertEqual([(shop["key"], shop["rows"][0]["listing"]["set"], shop["cards"])
                              for shop in plan["shops"]], [("mtgmate", "fdn", 1), ("gamesportal", "m19", 1)])
        self.assertEqual((free["recommended"]["total_aud"], paid["by_price"]["total_aud"],
                          paid["recommended"]["keys"], paid["recommended"]["total_aud"]),
                         ("6.00", "12.00", ["gamesportal"], "10.00"))

    def test_plan_can_reassign_a_counted_shop_copy_and_recalculate_optional_supply(self):
        rows = [row("Sol Ring", 1), row("Sol Ring", 2, printing="exact", set="fdn", collector_number="227"),
                row("Sol Ring", 3, state="long_term"), row("Giant Growth", 4)]
        mtg = mtgmate({"Sol Ring": entry(listing("1.00", 1), listing("7.00", 1, set_code="cmm")),
                       "Giant Growth": entry(listing("1.00", 1))})
        gp = games_portal({"Sol Ring": entry(listing("2.00", 1)), "Giant Growth": entry()})
        with mock.patch.object(shops.ADAPTERS["gamesportal"], "counts_stock", True):
            built = build(rows, mtg, gp, rules(mtg=("1.00", "8.00"), gp=("1.00", "8.00")))
        self.assertEqual([item["queue_row"] for item in basket(built, "gamesportal")["rows"]], [2])
        self.assertEqual(basket(built, "mtgmate")["add_ons"], [])
        best = built["plan"]["recommended"]
        self.assertEqual((best["cards"], best["total_aud"]), (3, "6.00"))
        first, second = best["shops"]
        self.assertEqual([item["queue_row"] for item in first["rows"]], [2, 4])
        self.assertEqual([(item["queue_row"], item["listing"]["set"]) for item in second["rows"]], [(1, "fdn")])
        self.assertEqual([(item["queue_row"], item["copies"]) for item in first["add_ons"]], [(3, 1)])
        self.assertEqual(first["postage"]["reach"], {"rows": [3], "reaches": True, "total_aud": "7.00"})
        self.assertEqual(second["add_ons"], [])

    def test_unknown_price_retains_known_partial_charges_and_full_coverage_wins(self):
        rows = [row("Sol Ring", 1, quantity="2")]
        mtg = mtgmate({"Sol Ring": entry(listing("1.00", 1), listing(None, 1, set_code="cmm"))})
        gp = games_portal({"Sol Ring": entry()})
        plan = build(rows, mtg, gp, rules(mtg=("3", None), gp=("0", None)))["plan"]["recommended"]
        self.assertEqual((plan["cards"], plan["cards_aud"], plan["unpriced_copies"], plan["total_aud"]), (2, "1.00", 1, "4.00"))
        self.assertEqual(plan["shops"][0]["rows"][0]["known_aud"], "1.00")

    def test_add_ons_in_the_plan_reach_the_threshold_of_the_shop_it_uses(self):
        rows = [row("Sol Ring", 1), row("Arcane Signet", 2, state="long_term")]
        built = build(rows, mtgmate({"Sol Ring": entry(listing("40.00", 5)), "Arcane Signet": entry(listing("15.00", 2))}),
                      postage=rules(mtg=("8.00", "50.00")))
        shop, = built["plan"]["recommended"]["shops"]
        self.assertEqual(shop["postage"]["reach"], {"rows": [2], "total_aud": "15.00", "reaches": True})

    def test_all_unavailable_still_has_a_plan_with_reasons_and_no_shops(self):
        built = build([row("Gone", 1)], mtgmate({"Gone": entry(listing(stock=0))}), postage=rules())
        plan = built["plan"]
        self.assertEqual((plan["wanted"], plan["recommended"]["cards"], plan["recommended"]["shops"], plan["options"]), (1, 0, [], []))
        self.assertEqual([fact["status"] for fact in plan["recommended"]["uncovered"][0]["shops"]], ["out_of_stock", "unread"])

    def test_all_ready_demand_counts_and_failed_shop_check_stays_distinct(self):
        rows = [row("Sol Ring", 1), row("Gone", 2, quantity="2"), row("Later", 3, quantity="4", state="long_term")]
        mtg = mtgmate({"Sol Ring": entry(listing(stock=1)), "Gone": entry(listing(stock=0)), "Later": entry(listing(stock=4))})
        gp = games_portal({"Gone": entry(status="error", at="2026-11-01T02:30:00+11:00")})
        plan = build(rows, mtg, gp)["plan"]
        self.assertEqual((plan["wanted"], plan["recommended"]["cards"]), (3, 1))
        missing, = plan["recommended"]["uncovered"]
        self.assertEqual((missing["name"], missing["copies"], [fact["status"] for fact in missing["shops"]]),
                         ("Gone", 2, ["out_of_stock", "unknown"]))

    def test_optional_rows_alone_do_not_create_a_plan(self):
        built = build([row("Later", 1, state="long_term")], mtgmate({"Later": entry(listing())}))
        self.assertIsNone(built["plan"])


class StoreTests(unittest.TestCase):
    def test_record_is_saved_whole_with_a_revision_and_conflicts_refused(self):
        store = memory.MemoryStore()
        self.assertEqual(store.shop_postage(), {"revision": 0, "postage": {"v": 1, "shops": {}}})
        saved = store.shop_postage_put({"mtgmate": {"postage_aud": "8.5", "free_over_aud": ""}}, 0, MATT, "Set postage")
        self.assertEqual(saved, {"revision": 1, "postage": {"v": 1, "shops": {"mtgmate": {"postage_aud": "8.50",
                                                                                          "free_over_aud": None}}}})
        self.assertEqual(store.shop_postage_put(saved["postage"], 1, MATT, "Again")["revision"], 1)   # unchanged
        self.assertEqual(len(store.changes()), 1)
        with self.assertRaises(Conflict):
            store.shop_postage_put({}, 0, MATT, "Stale")
        self.assertEqual(store.shop_postage_put({}, 1, MATT, "Clear")["postage"]["shops"], {})

    def test_amounts_and_keys_are_checked(self):
        for bad in ({"mtgmate": {"postage_aud": "-1"}}, {"mtgmate": {"postage_aud": "1.234"}},
                    {"mtgmate": {"postage_aud": True}}, {"mtgmate": {"price": "1"}}, {"Bad Key": {}},
                    {"mtgmate": {"postage_aud": "10000"}}, []):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                rules_postage.normalize(bad)
        with self.assertRaises(Invalid):
            rules_postage.normalize({"elsewhere": {"postage_aud": "1"}}, known={"mtgmate"})
        self.assertEqual(rules_postage.normalize({"mtgmate": {"postage_aud": "", "free_over_aud": None}}),
                         {"v": 1, "shops": {}})
        self.assertEqual(rules_postage.normalize({"mtgmate": {"postage_aud": 0}})["shops"]["mtgmate"]["postage_aud"], "0.00")


class PostageApiTests(PermissionTestCase):
    def save(self, *, profile="matt", expect=0, shops=None, **other):
        return shop_postage.change(self.body(profile, expect=expect,
                                             shops=shops if shops is not None else {"mtgmate": {"postage_aud": "8.50",
                                                                                                "free_over_aud": "100"}},
                                             **other))

    def test_home_admin_saves_and_home_member_reads(self):
        with access.viewing("matt"):
            shown = shop_postage.view()
            self.assertEqual((shown["revision"], shown["can_edit"]), (0, True))
            self.assertEqual([item["key"] for item in shown["shops"]], ["mtgmate"])
            saved = self.save()
        self.assertEqual(saved["shops"][0]["free_over_aud"], "100.00")
        with access.viewing("user1"):
            self.assertFalse(shop_postage.view()["can_edit"])
            self.assertApiError(403, lambda: self.save(profile="user1", expect=1))
        change, = self.box.state.changes()
        self.assertEqual((change["actor"], change["message"]), ("matt", "Set the shops' postage"))
        self.assertEqual(shop_postage.rules()["mtgmate"], {"postage_aud": "8.50", "free_over_aud": "100.00"})

    def test_outsiders_are_refused_before_storage(self):
        for remote in (False, True):
            identity = {"profile": "user2", "email": "", "remote": True} if remote else None
            with access.using(identity), access.viewing("user2"), \
                    mock.patch.object(self.box.state, "shop_postage", side_effect=AssertionError("private read")), \
                    mock.patch.object(self.box.state, "shop_postage_put", side_effect=AssertionError("private write")):
                self.assertApiError(403, shop_postage.view)
                self.assertApiError(403, lambda: self.save(profile="user2"))

    def test_stale_unknown_and_malformed_requests_never_write(self):
        self.save()
        self.assertApiError(409, lambda: self.save(expect=0))
        self.assertApiError(400, lambda: self.save(expect=1, shops={"nowhere": {"postage_aud": "1"}}))
        self.assertApiError(400, lambda: self.save(expect=1, extra=1))
        self.assertApiError(400, lambda: shop_postage.change(b"[]"))
        self.assertApiError(413, lambda: shop_postage.change(b"{" + b" " * 9000 + b"}"))
        self.assertEqual(len(self.box.state.changes()), 1)

    def test_a_store_that_is_down_leaves_postage_unknown(self):
        self.box.state.down = True
        self.assertIsNone(shop_postage.rules())
        with access.viewing("matt"):
            self.assertApiError(503, shop_postage.view)


if __name__ == "__main__":
    unittest.main()
