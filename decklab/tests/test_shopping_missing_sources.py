"""Shopping carries on when a research file isn't on this PC's disk (E5-S32): the page's
non-strict overview warns, and every strict check still refuses."""
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import inventory, purchases, tokens
from decklab.lib.api import shopping
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import orders
from decklab.tests import test_purchases

BUYLIST = "magic/buylists/research.md"
REPORT = "magic/reports/gone.md"
WEB = Path(__file__).resolve().parent.parent / "web"


class MissingSourceTests(unittest.TestCase):
    setUp = test_purchases.PurchasesTests.setUp
    component = test_purchases.PurchasesTests.component
    write = test_purchases.PurchasesTests.write
    write_csv = test_purchases.PurchasesTests.write_csv
    save = test_purchases.PurchasesTests.save

    def queue(self, *rows):
        blank = dict.fromkeys(purchases.QUEUE_FIELDS, "") | {"quantity": "1", "printing": "any", "state": "ready"}
        self.write_csv("magic/watchlist.csv", purchases.QUEUE_FIELDS, [blank | row for row in rows])

    def drift(self):
        """An order and three queue rows whose research files left the disk after they were saved."""
        self.record["sources"] = [BUYLIST, REPORT]
        self.save()
        self.queue({"name": "Sol Ring", "source": BUYLIST}, {"name": "Arcane Signet", "source": BUYLIST},
                   {"name": "Forest", "source": REPORT}, {"name": "Island"})
        (self.root / BUYLIST).unlink()

    def page(self):
        with inventory.pinned(), mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping, "_home_decks", return_value=[]), \
                mock.patch.object(shopping.common, "_log"):
            return shopping.shopping_overview()

    def test_non_strict_overview_lists_everything_and_names_each_missing_path(self):
        self.drift()
        data = purchases.overview(strict=False)
        self.assertEqual([row["name"] for row in data["to_buy"]], ["Sol Ring", "Arcane Signet", "Forest", "Island"])
        self.assertEqual([order["id"] for order in data["orders"]], ["test-order"])
        self.assertEqual(data["orders"][0]["sources"], [BUYLIST, REPORT])
        self.assertEqual(len(data["checks"]), 1)
        self.assertEqual(data["warnings"], [
            f"Order test-order: source {BUYLIST} isn't on this PC",
            f"Order test-order: source {REPORT} isn't on this PC",
            f"Purchase queue rows Sol Ring, Arcane Signet: source {BUYLIST} isn't on this PC",
            f"Purchase queue row Forest: source {REPORT} isn't on this PC"])

    def test_nothing_missing_means_no_warnings_either_way(self):
        self.queue({"name": "Sol Ring", "source": BUYLIST})
        self.assertEqual(purchases.overview(strict=False), purchases.overview())
        self.assertEqual(purchases.overview(strict=False)["warnings"], [])

    def test_the_page_answers_with_the_warnings(self):
        self.drift()
        answer = self.page()
        self.assertEqual(len(answer["to_buy"]), 4)
        self.assertEqual(len(answer["orders"]), 1)
        self.assertEqual(len(answer["warnings"]), 4)
        self.assertIn(f"Order test-order: source {BUYLIST} isn't on this PC", answer["warnings"])
        # The top bar's delivery notice counts the pending parts of this same answer.
        self.assertEqual(answer["orders"][0]["components"][0]["status"], "pending")

    def test_strict_readers_still_refuse_a_missing_source(self):
        self.drift()
        with self.assertRaisesRegex(ValueError, f"Order test-order: source {BUYLIST} does not exist"):
            purchases.overview()
        with self.assertRaisesRegex(ValueError, "does not exist"):
            purchases.read_records()
        with self.assertRaisesRegex(ValueError, "watchlist: Sol Ring: source file does not exist"):
            purchases.read_queue()
        found, problems = tokens.incoming()             # the tokens check's reader
        self.assertEqual(found, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("does not exist", problems[0])
        row = dict.fromkeys(purchases.QUEUE_FIELDS, "") | {"name": "Sol Ring", "quantity": "1", "printing": "any",
                                                            "state": "ready", "source": BUYLIST}
        with self.assertRaisesRegex(inventory.Invalid, "source file does not exist"):
            orders.queue_row(row, str(self.root), inventory.current())      # a watchlist write

    def test_the_command_and_the_nightly_check_are_strict(self):
        from decklab.db import check
        with mock.patch.object(purchases, "overview", return_value={"orders": [], "to_buy": []}) as overview, \
                mock.patch.object(purchases.entry, "command"), mock.patch("builtins.print"):
            self.assertEqual(purchases.main(["--check"]), 0)
            check._orders()
        self.assertEqual(overview.call_args_list, [mock.call(), mock.call()])

    def test_a_deck_source_that_is_not_a_deck_still_refuses(self):
        self.record["sources"] = ["magic/decks/casual/nope.md"]
        self.save()
        with self.assertRaisesRegex(ValueError, "source magic/decks/casual/nope.md does not exist"):
            purchases.overview(strict=False)
        self.record["sources"] = []
        self.save()
        self.queue({"name": "Sol Ring", "source": "magic/decks/casual/nope.md"})
        with self.assertRaisesRegex(ValueError, "watchlist: Sol Ring: source file does not exist"):
            purchases.overview(strict=False)

    def test_structural_and_coverage_problems_still_refuse_the_page(self):
        self.drift()
        cases = [
            (lambda: self.write("magic/orders/records/test-order.json", "{not json"), None),
            (lambda: (self.root / "magic/orders/test.csv").unlink(), "aren't in the inventory"),
            (lambda: self.record["components"][0].update(kind="bundle"), "invalid kind or status"),
            (lambda: self.record["components"][0].update(status="lost"), "invalid kind or status"),
            (lambda: self.record.update(sources=["../outside.md"]), "relative repository path"),
            (lambda: self.write_csv("magic/orders/unrecorded.csv", ["name", "quantity"],
                                    [{"name": "Forest", "quantity": "1"}]), "missing order record"),
        ]
        for number, (change, message) in enumerate(cases):
            with self.subTest(case=number):
                test_purchases.PurchasesTests.setUp(self)
                self.drift()
                change()
                if number in (2, 3, 4):
                    self.save()
                with self.assertRaises((ValueError, OSError)) as raised:
                    purchases.overview(strict=False)
                if message:
                    self.assertIn(message, str(raised.exception))
                with self.assertRaises(ApiError) as refused:
                    self.page()
                self.assertEqual(refused.exception.status, 500)
                self.assertIn("shopping records couldn't be read", refused.exception.message)

    def test_the_page_draws_the_warnings_in_a_needs_attention_box(self):
        source = (WEB / "shopping.js").read_text(encoding="utf-8")
        self.assertIn('warningsBox(data.warnings, "Some shopping records need attention")', source)
        core = (WEB / "core.js").read_text(encoding="utf-8")
        self.assertIn('class: "box box-warn"', core)


if __name__ == "__main__":
    unittest.main()
