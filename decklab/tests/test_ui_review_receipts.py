"""Larger review parcels use the ordinary read path and never authorize recording."""
import tempfile
import unittest

from decklab.tests import test_ui_review as review_tests


class ReceiptReviewFixtureTests(unittest.TestCase):
    request = review_tests.ReviewFixtureTests.request
    runtime = review_tests.ReviewFixtureTests.runtime

    def test_larger_and_multipart_parcels_read_through_the_guarded_fixture(self):
        from decklab.ui_review.fixture import review_fixture
        from decklab.ui_review import receipt_data

        with tempfile.TemporaryDirectory() as parent:
            runtime = self.runtime(parent)
            with review_fixture(runtime, "unit-review-test-token") as fixture:
                for order_id, count in ((receipt_data.LARGE, 1), (receipt_data.SPLIT, 2)):
                    with self.subTest(order=order_id):
                        before = self.request(fixture, f"/api/receipt?order={order_id}")
                        self.assertEqual(len(before["components"]), count)
                        self.assertEqual(sum(int(row["quantity"]) for part in before["components"]
                                             for row in part["rows"]), 24)
                        self.assertTrue(all(part["status"] == "pending" for part in before["components"]))
                        self.assertTrue(all(pic and pic["exact"] for part in before["components"]
                                            for pic in part["pictures"]))
                        self.request(fixture, "/api/receipt/apply", method="POST", payload={}, status=403)
                        self.assertEqual(self.request(fixture, f"/api/receipt?order={order_id}"), before)
