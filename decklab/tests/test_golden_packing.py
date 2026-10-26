"""Compatibility ignores only documented additive/default packing projections."""
import copy
import unittest

from decklab.tests import golden_packing


def product_summary(**changes):
    return {"id": "product/box/deck", "source": "magic/products/box.csv", "read_only": True,
            "holder_sha256": "a" * 64, "card_count": 20, "kit": {"sleeves": "keep this value"}, **changes}


def picker(**changes):
    return {"tokens_sha256": None, "expect": "a" * 64,
            "product": {"stem": "box", "status_sha256": "a" * 64}, "editable": True, "written": False,
            "lines": [], "choices": [{"row": 0, "front": "Zombie", "back": "", "set": "", "number": "",
                                        "quantity": 3, "free": 1, "packed": 0}], **changes}


class GoldenPackingTests(unittest.TestCase):
    def test_exact_api_paths_drop_projections_but_preserve_allocations_counts_and_input(self):
        base = {"assembly": {"a": {"decks": [{"id": "casual/a", "take_apart": {"card_count": 3},
                                               "steps": [{"need": 4, "keep": 1, "storage": 2, "missing": 1}]}],
                                      "rows": [{"name": "Opt", "missing": 1, "held_elsewhere": [
                                          {"id": "product/box/deck", "quantity": 2, "intact_product": {"id": "box"}}]}]}},
                "deck_view": {"product/box/deck@target": {"summary": product_summary(),
                    "tokens": {"needs": [{"name": "Zombie", "state": "none"}], "packed": picker()}}}}
        original = {**base, "by_viewer": {"matt": copy.deepcopy(base)},
                    "unrelated": {"take_apart": "keep", "intact_product": "keep", "packed": picker(),
                                  "holder_sha256": "a" * 64}}
        before = copy.deepcopy(original)
        found = golden_packing.normalise(original)
        self.assertEqual(original, before)
        self.assertEqual(found["unrelated"], before["unrelated"])
        for mine in (found, found["by_viewer"]["matt"]):
            plan = mine["assembly"]["a"]
            self.assertEqual(plan["decks"], [{"id": "casual/a", "steps": [{"need": 4, "keep": 1, "storage": 2, "missing": 1}]}])
            self.assertEqual(plan["rows"], [{"name": "Opt", "missing": 1, "held_elsewhere": [{"id": "product/box/deck", "quantity": 2}]}])
            page = mine["deck_view"]["product/box/deck@target"]
            self.assertEqual(page["summary"], {k: v for k, v in product_summary().items() if k != "holder_sha256"})
            self.assertEqual(page["tokens"], {"needs": [{"name": "Zombie", "state": "none"}]})

    def test_written_nonempty_malformed_and_unrecognised_picker_data_stays_comparable(self):
        values = [picker(written=True), picker(lines=[{"text": "1 Zombie"}]), picker(error="Cannot read"),
                  picker(unexpected="keep"), picker(expect="not a hash"), picker(editable="yes"),
                  picker(product={"stem": "other", "status_sha256": "a" * 64}), picker(tokens_sha256="bad"),
                  picker(expect="b" * 64, product={"stem": "box", "status_sha256": "b" * 64})]
        for choice_change in ({"packed": 1}, {"free": 4}, {"row": True}, {"row": -1}, {"front": ""}):
            value = picker()
            value["choices"][0].update(choice_change)
            values.append(value)
        for value in values:
            with self.subTest(value=value):
                original = {"deck_view": {"x": {"summary": product_summary(), "tokens": {"packed": value}}}}
                self.assertEqual(golden_packing.normalise(original)["deck_view"]["x"]["tokens"]["packed"], value)

    def test_unrelated_or_forged_product_summaries_keep_their_receipts_and_pickers(self):
        for summary in (product_summary(id="casual/a"), product_summary(source="magic/products/other.csv"),
                        product_summary(source="magic/decks/casual/a.md"), product_summary(read_only=False),
                        product_summary(holder_sha256="bad")):
            original = {"deck_view": {"x": {"summary": summary, "tokens": {"packed": picker()}}}}
            found = golden_packing.normalise(original)["deck_view"]["x"]
            self.assertEqual(found["summary"]["holder_sha256"], summary["holder_sha256"])
            self.assertEqual(found["tokens"]["packed"], picker())
