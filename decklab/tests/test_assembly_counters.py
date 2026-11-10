"""Optional counter kinds use one home-inventory coverage estimate for the whole plan."""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import assembly, assembly_counters as counters
from decklab.lib.api.common import ApiError
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_assembly_tokens import OptionalTokenCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


def participant(deck_id, *kinds):
    return {"id": deck_id, "title": deck_id.rsplit("/", 1)[-1].title(), "tokens": {"needs": [],
            "counters": {"needs": [{"key": key, "name": key if group == "die" else f"{key} counters",
                                     "group": group} for key, group in kinds]}}}


GENERIC = {"type": "counter", "kind": "", "quantity": "1", "design": "", "notes": ""}


class CounterPlanSummaryTests(unittest.TestCase):
    def test_historical_goldens_ignore_only_exact_empty_additive_defaults(self):
        from decklab.tests import golden_p4
        empty = counters.summary([], counters.Sources((), True))
        bare = {"needs": [], "note": counters.counters.NOTE}
        dump = {"assembly": {"empty": {"counters": empty, "decks": [{"tokens": {"counters": bare}}]}}}
        golden_p4.counter_defaults(dump)
        self.assertEqual(dump, {"assembly": {"empty": {"decks": [{"tokens": {}}]}}})
        for changed in ({**empty, "error": "Keep the error"}, {**empty, "note": "Changed note"},
                        {**empty, "needs": [{"key": "poison"}]},
                        counters.summary([], counters.Sources((GENERIC,), True))):
            dump = {"assembly": {"a": {"counters": changed, "decks": []}}}
            before = copy.deepcopy(dump)
            golden_p4.counter_defaults(dump)
            self.assertEqual(dump, before)

    def test_shared_kind_uses_one_generic_item_and_other_kinds_are_not_double_covered(self):
        a = participant("casual/a", ("poison", "player"), ("energy", "player"))
        b = participant("casual/b", ("energy", "player"), ("loyalty", "permanent"))
        before = copy.deepcopy([a, b])
        found = counters.summary([a, b], counters.Sources((GENERIC,), True))
        self.assertEqual([need["key"] for need in found["needs"]], ["loyalty", "energy", "poison"])
        self.assertEqual([need["cover"]["state"] for need in found["needs"]], ["generic", "none", "none"])
        self.assertEqual([deck["id"] for deck in found["needs"][1]["decks"]], ["casual/a", "casual/b"])
        self.assertEqual([a, b], before)
        other_order = counters.summary([b, a], counters.Sources((GENERIC,), True))
        self.assertEqual([need["cover"] for need in other_order["needs"]],
                         [need["cover"] for need in found["needs"]])
        # A shared kind consumes its generic cover once, leaving another kind a second item.
        found = counters.summary([a, b], counters.Sources(({**GENERIC, "quantity": "2"},), True))
        self.assertEqual([need["cover"]["state"] for need in found["needs"]], ["generic", "generic", "none"])

    def test_named_counter_and_die_coverage_and_sideboard_sources(self):
        a = participant("casual/a", ("poison", "player"), ("d20", "die"))
        b = participant("casual/b", ("poison", "player"), ("d6", "die"))
        b["tokens"]["counters"]["needs"][0]["sideboard_only"] = True
        rows = ({"type": "counter", "kind": "poison", "quantity": "4"},
                {"type": "die", "size": "spindown", "quantity": "1"})
        found = counters.summary([a, b], counters.Sources(rows, True))
        self.assertEqual([need["key"] for need in found["needs"]], ["poison", "d6", "d20"])
        self.assertEqual([need["cover"]["state"] for need in found["needs"]], ["named", "none", "named"])
        self.assertEqual([deck["sideboard_only"] for deck in found["needs"][0]["decks"]], [False, True])
        self.assertTrue(all("quantity" not in need for need in found["needs"]))

    def test_failed_or_unmigrated_inventory_never_claims_nothing_owned(self):
        a = participant("casual/a", ("energy", "player"))
        for source in (counters.Sources(failed=True), counters.Sources(ready=False)):
            with self.subTest(source=source):
                found = counters.summary([a], source)
                self.assertNotIn("cover", found["needs"][0])
                if source.failed:
                    self.assertEqual(found["error"], counters.FAILED)
                    self.assertNotIn("owned", found)
                else:
                    self.assertFalse(found["owned"]["ready"])

    def test_dice_sources_read_only_home_from_the_pinned_snapshot(self):
        snapshot = mock.Mock(dice_ready=True)
        snapshot.dice_set.return_value = mock.Mock(rows=[mock.Mock(as_dict=lambda: GENERIC)], error=None)
        with mock.patch.object(inventory, "current", return_value=snapshot) as current:
            found = counters.read_sources()
        current.assert_called_once_with()
        snapshot.dice_set.assert_called_once_with()
        self.assertEqual(found, counters.Sources((GENERIC,), True))
        snapshot.dice_set.return_value.error = "private malformed row"
        with mock.patch.object(inventory, "current", return_value=snapshot), mock.patch.object(counters.common, "_log"):
            self.assertEqual(counters.read_sources(), counters.Sources(failed=True))


class CountersNeverStopTheBuildTests(OptionalTokenCase):
    def test_read_only_counter_needs_and_failed_coverage_do_not_change_completion(self):
        bare = participant("casual/a", ("poison", "player"))["tokens"]
        for source in (counters.Sources((), True), counters.Sources(failed=True)):
            with self.subTest(source=source):
                self.deck("a", "A", "building", "Deck\n1 Hornet Queen\n1 Court of Grace\n",
                          table="| Hornet Queen | 1 | 0 | 1 | | | |\n| Court of Grace | 1 | 0 | 1 | | | |\n")
                with mock.patch.object(assembly, "_deck_tokens", return_value=bare), \
                        mock.patch.object(counters, "read_sources", return_value=source):
                    plan, deck = self.assert_builds()
                self.assertEqual(deck.status, "built")
                self.assertEqual(plan["decks"][0]["tokens"]["counters"], bare["counters"])
                self.assertEqual(plan["counters"]["needs"][0]["decks"][0]["id"], "casual/a")
                self.assertNotIn("cover", bare["counters"]["needs"][0])

    def test_a_coverage_calculation_failure_still_allows_the_build(self):
        bare = participant("casual/a", ("poison", "player"))["tokens"]
        with mock.patch.object(assembly, "_deck_tokens", return_value=bare), \
                mock.patch.object(counters.dice_cover, "cover", side_effect=ValueError("private details")), \
                mock.patch.object(counters.common, "_log"):
            plan, _ = self.assert_builds()
        self.assertEqual(plan["counters"], {"needs": [], "error": counters.FAILED})
        self.assertNotIn("private details", json.dumps(plan))


class CounterPlanPrivacyTests(PermissionTestCase):
    def test_other_spaces_and_anonymous_browsers_are_refused_before_reading_dice(self):
        for identity in ({"profile": "user2", "email": "", "remote": True}, None):
            with self.subTest(identity=identity), access.using(identity), access.answering(False), \
                    access.viewing(None), mock.patch.object(counters, "read_sources") as read:
                for call in (assembly.assembly_view, lambda: assembly.assembly_preview(json.dumps({"decks": []}))):
                    with self.assertRaises(ApiError) as refused:
                        call()
                    self.assertEqual(refused.exception.status, 403)
                read.assert_not_called()
