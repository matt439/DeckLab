"""Compare the public shopping plan with every feasible purchase for small saved baskets."""
import unittest
from collections import Counter, defaultdict
from decimal import Decimal
from itertools import product
from typing import NamedTuple
from unittest import mock

from decklab.lib import shops
from decklab.lib.api import shop_baskets, shop_delivery, shop_plan
from decklab.tests.test_shop_baskets import entry, games_portal, listing, mtgmate, row
from decklab.tests.test_shop_plan import rules

SHOPS = ("mtgmate", "gamesportal")


class Offer(NamedTuple):
    shop: int
    name: str
    printing: str
    cents: int | None
    copies: int


def dollars(cents):
    return f"{Decimal(cents) / 100:.2f}"


def basket_plan(rows, offers, postage):
    snapshots = []
    for i, snapshot in enumerate((mtgmate, games_portal)):
        cards = defaultdict(list)
        for offer in offers:
            if offer.shop == i:
                price = dollars(offer.cents) if offer.cents is not None else None
                cards[offer.name].append(listing(price, offer.copies, set_code=offer.printing))
        snapshots.append(snapshot({name: entry(*items) for name, items in cards.items()}))
    rates = [tuple(dollars(amount) if amount is not None else None for amount in rule) for rule in postage]
    adapters = [shops.ADAPTERS[key] for key in SHOPS]
    with mock.patch.object(adapters[1], "counts_stock", True):
        return shop_baskets.build(rows, dict(zip(SHOPS, snapshots)), "fixture", rules(*rates), adapters)["plan"]


def exhaustive_score(rows, offers, postage):
    """Try skipping or buying each requested physical copy, rejecting ineligible and oversold listings."""
    wants = [item for item in rows for _ in range(int(item["quantity"]))]
    choices = [[None] + [offer for offer in offers if offer.name == item["name"]
                          and (item["printing"] != "exact" or offer.printing == item["set"])] for item in wants]
    best = None
    for purchase in product(*choices):
        counts = Counter(offer for offer in purchase if offer is not None)
        if any(copies > offer.copies for offer, copies in counts.items()):
            continue
        spend = Counter()
        for offer, copies in counts.items():
            spend[offer.shop] += offer.cents * copies
        delivered = sum(spend.values())
        for shop, subtotal in spend.items():
            flat, threshold = postage[shop]
            if threshold is None or subtotal < threshold:
                delivered += flat
        exact = sum(item["printing"] == "exact" for item, offer in zip(wants, purchase) if offer is not None)
        score = -sum(counts.values()), -exact, delivered, len(spend)
        if best is None or score < best:
            best = score
    return best


class DeliveredBasketTests(unittest.TestCase):
    def assert_optimal(self, rows, offers, postage):
        plan = basket_plan(rows, offers, postage)
        best = plan["recommended"]
        by_row = {item["queue_row"]: item for item in rows}
        offered_stock = {(o.shop, o.name, o.printing, o.cents): o.copies for o in offers}
        used = Counter()
        received = Counter()
        for shop in best["shops"]:
            subtotal = 0
            for line in shop["rows"]:
                want = by_row[line["queue_row"]]
                for source in [line["listing"], *line["more"]]:
                    if want["printing"] == "exact":
                        self.assertEqual(source["set"], want["set"])
                    price = int(Decimal(source["price_aud"]) * 100)
                    used[SHOPS.index(shop["key"]), want["name"], source["set"], price] += source["copies"]
                    received[line["queue_row"]] += source["copies"]
                    subtotal += price * source["copies"]
            flat, threshold = postage[SHOPS.index(shop["key"])]
            fee = 0 if threshold is not None and subtotal >= threshold else flat
            self.assertEqual(shop["subtotal_aud"], dollars(subtotal))
            self.assertEqual(shop["postage"]["charged_aud"], dollars(fee))
        self.assertEqual(Decimal(best["total_aud"]), sum(Decimal(s["subtotal_aud"]) + Decimal(s["postage"]["charged_aud"])
                                                         for s in best["shops"]))
        for key, count in used.items():
            self.assertLessEqual(count, offered_stock[key])
        for key, count in received.items():
            self.assertLessEqual(count, int(by_row[key]["quantity"]))
        self.assertEqual(sum(received.values()), best["cards"])
        exact = sum(count for key, count in received.items() if by_row[key]["printing"] == "exact")
        self.assertEqual((-best["cards"], -exact, int(Decimal(best["total_aud"]) * 100), len(best["shops"])),
                         exhaustive_score(rows, offers, postage))
        return plan

    def test_one_dollar_more_for_a_card_saves_six_dollars_postage(self):
        rows = [row("A", 1), row("B", 2), row("Either", 3)]
        offers = [Offer(0, "A", "fdn", 800, 1), Offer(1, "B", "fdn", 100, 1),
                  Offer(0, "Either", "fdn", 200, 1), Offer(1, "Either", "fdn", 100, 1)]
        plan = self.assert_optimal(rows, offers, [(600, 1000), (0, None)])
        self.assertEqual(plan["by_price"]["total_aud"], "16.00")
        self.assertEqual(plan["recommended"]["total_aud"], "11.00")
        self.assertEqual(plan["saves_aud"], "5.00")

    def test_one_shop_can_reach_free_postage_with_a_different_eligible_printing(self):
        rows = [row("Either", 1)]
        offers = [Offer(0, "Either", "fdn", 100, 1), Offer(0, "Either", "m19", 200, 1)]
        plan = self.assert_optimal(rows, offers, [(600, 200), (0, None)])
        line, = plan["recommended"]["shops"][0]["rows"]
        self.assertEqual(line["listing"]["set"], "m19")

    def test_two_reassignments_together_save_postage_when_neither_alone_does(self):
        rows = [row(name, i) for i, name in enumerate(("A", "B", "Either", "Another"), 1)]
        offers = [Offer(0, "A", "fdn", 500, 1), Offer(1, "B", "fdn", 100, 1)]
        for name in ("Either", "Another"):
            offers.extend((Offer(0, name, "fdn", 250, 1), Offer(1, name, "fdn", 150, 1)))
        plan = self.assert_optimal(rows, offers, [(600, 1000), (0, None)])
        self.assertEqual(plan["by_price"]["total_aud"], "15.00")
        self.assertEqual(plan["recommended"]["total_aud"], "11.00")

    def test_interacting_tiers_prove_a_delivered_minimum_for_fifteen_copies(self):
        rows = [row(f"Card {i}", i + 1, quantity=str(1 + i % 3)) for i in range(8)]
        offers = []
        for i, item in enumerate(rows):
            for shop in (0, 1):
                if i % 5 == (4 if shop else 3):
                    continue
                cents = 75 + (17 * i + 31 * shop) % 110
                offers.extend([Offer(shop, item["name"], "fdn", cents, 2),
                               Offer(shop, item["name"], "cmm", cents + 15, 2)])
        plan = basket_plan(rows, offers, [(790, 1160), (790, 1160)])
        # Exhaustive subtotal enumeration on this fixture gives 20,744 possible pairs.
        self.assertTrue(plan["search_complete"])
        self.assertEqual((plan["recommended"]["cards"], plan["recommended"]["total_aud"]), (15, "24.22"))

    def test_shared_capacity_and_exact_requests_at_two_postage_thresholds(self):
        rows = [row("A", 1), row("B", 2), row("Either", 3, quantity="2"),
                row("Either", 4, printing="exact", set="fdn", collector_number="227")]
        for stock, threshold_a, threshold_b in product((0, 1, 2), (None, 615, 825), (None, 260, 485)):
            offers = [Offer(0, "A", "fdn", 405, 1), Offer(1, "B", "fdn", 150, 1),
                      Offer(0, "Either", "fdn", 210, 1), Offer(0, "Either", "m19", 320, stock),
                      Offer(1, "Either", "m19", 110, stock)]
            with self.subTest(stock=stock, threshold_a=threshold_a, threshold_b=threshold_b):
                self.assert_optimal(rows, offers, [(620, threshold_a), (400, threshold_b)])

    def test_limited_search_keeps_coverage_stock_and_exact_printings(self):
        rows = [row("Either", 1), row("Either", 2, printing="exact", set="fdn", collector_number="227"),
                row("Anchor", 3)]
        offers = [Offer(0, "Either", "fdn", 100, 1), Offer(0, "Either", "m19", 200, 1),
                  Offer(0, "Either", "cmm", 300, 1), Offer(0, "Anchor", "fdn", 100, 1)]
        postage = [(600, 500), (0, None)]
        self.assertEqual(self.assert_optimal(rows, offers, postage)["recommended"]["total_aud"], "5.00")
        with mock.patch.object(shop_delivery, "MAX_STEPS", 0):
            plan = basket_plan(rows, offers, postage)
        self.assertFalse(plan["search_complete"])
        self.assertEqual(plan["recommended"], plan["by_price"])
        fallback = plan["recommended"]
        self.assertEqual((fallback["cards"], fallback["exact_copies"], fallback["total_aud"]), (3, 1, "10.00"))
        self.assertEqual({line["queue_row"]: line["listing"]["set"] for line in fallback["shops"][0]["rows"]},
                         {1: "m19", 2: "fdn", 3: "fdn"})

    def test_shop_subset_limit_keeps_all_shops_in_the_baseline(self):
        rows = [row("A", 1), row("B", 2)]
        offers = [Offer(0, "A", "fdn", 100, 1), Offer(1, "B", "fdn", 200, 1)]
        with mock.patch.object(shop_plan, "MAX_SHOPS", 1):
            plan = basket_plan(rows, offers, [(0, None), (0, None)])
        self.assertFalse(plan["search_complete"])
        for choice in (plan["by_price"], plan["recommended"]):
            self.assertEqual((choice["keys"], choice["cards"], choice["total_aud"]), (list(SHOPS), 2, "3.00"))

    def test_unpriced_copy_can_change_postage_only_below_a_known_threshold(self):
        rows = [row("Anchor", 1), row("Unpriced", 2)]
        offers = [Offer(0, "Anchor", "fdn", 600, 1), Offer(0, "Unpriced", "fdn", None, 1)]
        for threshold, expected, conditional in ((700, None, True), (600, "0.00", False), (None, "5.00", False)):
            with self.subTest(threshold=threshold):
                plan = basket_plan(rows, offers, [(500, threshold), (0, None)])
                best = plan["recommended"]
                self.assertEqual((best["cards"], best["unpriced_copies"]), (2, 1))
                postage = best["shops"][0]["postage"]
                self.assertEqual((postage["charged_aud"], postage["conditional"]), (expected, conditional))
                self.assertEqual(plan["weighed"], expected is not None)


if __name__ == "__main__":
    unittest.main()
