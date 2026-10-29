"""CLI-only merge filing over disposable snapshots; use scripts/test_fixtures.py."""
import contextlib
import json
from collections import Counter
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import collection_filing as filing
from decklab.lib.inventory import files, ops_collection as ops, paths, rules
from decklab.tests import test_collection_edit as support
from decklab.tests.test_api import _write
from decklab.tests.test_collection_filing import ELVES, MYSTIC, deck_text


class CliMergeFilingTests(support.CollectionEditTestCase):

    def snapshot(self, quantity=4, decks=(), space="user2", extra_rows=(), other=None):
        rows = [{**ELVES, "quantity": str(quantity), "condition": "", "language": "", "notes": ""}, *extra_rows]
        source = {paths.collection(space): rules.collection_csv_bytes(rows),
                  paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n").encode()}
        for ident, text in decks:
            source[f"{paths.decks_dir(space)}/casual/{ident}.md"] = text.encode()
        source.update(other or {})
        return files.build(source)

    def facts(self, before=2, added=2, row=None):
        return [{**(row or ELVES), "quantity": added, "before_quantity": before, "after_quantity": before + added}]

    def advice(self, snapshot=None, facts=None, total=None):
        snapshot = snapshot or self.snapshot(decks=[("a", deck_text("A")), ("b", deck_text("B"))])
        facts = self.facts() if facts is None else facts
        total = sum(row["quantity"] for row in facts) if total is None else total
        return filing.after_cli_merge(snapshot, "user2", facts, total)

    def assert_conserved(self, answer):
        counted = Counter()
        for item in answer["destinations"]:
            self.assertGreater(item["quantity"], 0)
            counted[item["row"]] += item["quantity"]
        self.assertEqual([counted[i] for i in range(len(answer["added"]))],
                         [row["quantity"] for row in answer["added"]])
        self.assertNotIn("profile", answer)
        self.assertNotIn("before_quantity", json.dumps(answer))
        self.assertNotIn("revision", answer)
        json.dumps(answer, allow_nan=False)

    def test_zero_added_copies_need_no_snapshot_pool_index_or_request_context(self):
        with mock.patch.object(filing.inventory, "pinned", side_effect=AssertionError("snapshot")), \
                mock.patch.object(filing.pool, "load_pool", side_effect=AssertionError("pool")), \
                mock.patch.object(filing.cards, "resolve", side_effect=AssertionError("index")), \
                mock.patch.object(filing.guard, "sees_inventory", side_effect=AssertionError("request")):
            answer = filing.after_cli_merge(object(), "user2", [], 0)
        self.assertEqual(answer, {"space": "user2", "status": "ready", "cards": 0,
                                  "added": [], "destinations": []})

    def test_cli_selected_member_space_does_not_depend_on_webviewer_or_permission_helpers(self):
        snapshot = self.snapshot(2, [("a", deck_text("Selected member", 2))], other={
            "magic/decks/casual/private-home.md": b"unreadable private home deck",
            "magic/people/user3/decks/casual/private-other.md": b"unreadable other member deck"})
        with self.as_("matt"), contextlib.ExitStack() as stack:
            for name in ("sees_inventory", "deck_reader", "sees_deck", "script", "public_deck_spaces"):
                stack.enter_context(mock.patch.object(filing.guard, name, side_effect=AssertionError("web guard")))
            answer = self.advice(snapshot, self.facts(0, 2))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "deck", "row": 0, "quantity": 2,
                         "deck": {"id": "user2/casual/a", "title": "Selected member", "status": "building"}}])
        self.assertNotIn("private-home", json.dumps(answer))
        self.assertNotIn("private-other", json.dumps(answer))
        self.assert_conserved(answer)

    def test_actual_returned_snapshot_overrides_old_request_pin_without_later_load(self):
        before = self.snapshot(2, [("a", deck_text("A")), ("b", deck_text("B"))])
        after = self.snapshot(4, [("a", deck_text("A")), ("b", deck_text("B"))])
        with inventory.pinned(before), mock.patch.object(self.backend, "load", side_effect=AssertionError("later load")):
            answer = self.advice(after)
            self.assertIs(inventory.current(), before)
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "deck", "row": 0, "quantity": 2,
                         "deck": {"id": "user2/casual/b", "title": "B", "status": "building"}}])
        self.assert_conserved(answer)

    def test_actual_merge_deltas_with_multiple_printings_share_prior_free_stock_once(self):
        for slug in ("a", "b"):
            _write(self.box.magic / f"people/user2/decks/casual/{slug}.md", deck_text(slug.upper(), 3))
        incoming = [{**ELVES, "quantity": "1", "condition": "", "language": "", "notes": ""},
                    {**ELVES, "finish": "foil", "quantity": "2", "condition": "", "language": "", "notes": ""}]
        before = self.backend.load()
        op = inventory.Op("collection.import", {"space": "user2", "sha256": ops.sha256_of(before.collection("user2")),
                          "sources": [["fixture.csv", incoming]], "capture_additions": True})
        after, summary = inventory.apply(op, inventory.Actor("user3", "User3", None, "cli"), "fixture merge")
        with self.as_("user3"):
            answer = self.advice(after, summary.extra["added_printings"], summary.counts["cards"])
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(Counter({row["finish"]: row["quantity"] for row in answer["added"]}),
                         Counter({"nonfoil": 1, "foil": 2}))
        by_deck = Counter()
        for item in answer["destinations"]:
            by_deck[item["deck"]["id"]] += item["quantity"]
        self.assertEqual(by_deck, Counter({"user2/casual/a": 1, "user2/casual/b": 2}))
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(len(self.writes), 1)
        self.assert_conserved(answer)

    def test_built_reservations_and_priority_use_the_same_global_allocator(self):
        snapshot = self.snapshot(5, [("idea", deck_text("Idea", 3, "idea")),
                                     ("built", deck_text("Built", 3, "built", owned=2)),
                                     ("waiting", deck_text("Waiting", 2))])
        answer = self.advice(snapshot, self.facts(2, 3))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual([(item["deck"]["id"], item["quantity"]) for item in answer["destinations"]],
                         [("user2/casual/built", 1), ("user2/casual/waiting", 2)])
        self.assert_conserved(answer)

    def test_invalid_receipts_and_counts_are_unknown_with_no_inferred_storage(self):
        snapshot = self.snapshot()
        for facts, total in ((self.facts(), 3), (self.facts(0, 2), 2), (self.facts() * 2, 4),
                             (self.facts(row=MYSTIC), 2), (None, 2), ([], 0.0), ([], False),
                             ([], -1), ([], "2"), (self.facts(), 0)):
            with self.subTest(facts=facts, total=total):
                answer = filing.after_cli_merge(snapshot, "user2", facts, total)
                self.assertEqual(answer["status"], "unknown")
                self.assertEqual(answer["message"], filing.MERGE_UNKNOWN)
                self.assertFalse(any(item["kind"] == "storage" for item in answer["destinations"]))
                self.assertNotIn("profile", answer)
                self.assertIs(type(answer["cards"]), int)
                json.dumps(answer, allow_nan=False)

    def test_unreadable_selected_candidate_or_pool_is_unknown_not_storage(self):
        answer = self.advice(self.snapshot(decks=[("bad", "not a deck list")]))
        self.assertEqual(answer["status"], "unknown")
        for found in (pool.Pool(Counter({"Llanowar Elves": 4}), {}, [], space="home"),
                      pool.Pool(Counter({"Llanowar Elves": 4}), {}, [], space="user2", warnings=["private detail"]),
                      pool.Pool(Counter({"Llanowar Elves": 4}), {}, [], space="user2", unresolved={"secret": {}})):
            with self.subTest(found=found), mock.patch.object(filing.pool, "load_pool", return_value=found):
                answer = self.advice()
            self.assertEqual(answer["status"], "unknown")
            self.assertNotIn("private detail", json.dumps(answer))
            self.assertNotIn("secret", json.dumps(answer))
            self.assert_conserved(answer)

    def test_basic_or_unavailable_index_and_pool_errors_are_static_unknown(self):
        basic = {"name": "Forest", "set": "fdn", "collector_number": "280", "finish": "foil"}
        extra = [{**basic, "quantity": "2", "condition": "", "language": "", "notes": "full art"}]
        answer = self.advice(self.snapshot(extra_rows=extra), self.facts(0, 2, basic))
        self.assertEqual(answer["status"], "unknown")
        self.assert_conserved(answer)
        for module, name in ((filing.cards, "resolve"), (filing.pool, "load_pool")):
            with self.subTest(name=name), mock.patch.object(module, name, side_effect=RuntimeError("private error")):
                answer = self.advice()
            self.assertEqual(answer["status"], "unknown")
            self.assertEqual(answer["message"], filing.MERGE_UNKNOWN)
            self.assertNotIn("private error", json.dumps(answer))
            self.assert_conserved(answer)

    def test_existing_caps_fail_unknown_instead_of_silently_claiming_storage(self):
        snapshot = self.snapshot(decks=[("a", deck_text("A", 1)), ("b", deck_text("B", 1))])
        for name, cap in (("MAX_DECKS", 1), ("MAX_WORK", 1), ("MAX_DESTINATIONS", 1), ("MAX_ADDED_ROWS", 0)):
            with self.subTest(name=name), mock.patch.object(filing, name, cap):
                answer = self.advice(snapshot, self.facts(0, 4))
            self.assertEqual(answer["status"], "unknown")
            self.assertFalse(any(item["kind"] == "storage" for item in answer["destinations"]))
            self.assertEqual(answer["message"], filing.MERGE_UNKNOWN)
            self.assertNotIn("profile", answer)
        self.assertEqual(answer["added"], [])

    def test_cli_call_does_not_broaden_web_inventory_or_candidate_deck_readers(self):
        snapshot = self.snapshot(2, [("a", deck_text("Member", 2))])
        self.assertEqual(self.advice(snapshot, self.facts(0, 2))["status"], "ready")
        profile = next(p for p in support.ROLES["profiles"] if p["id"] == "matt")
        denied = filing.after_import(snapshot, "user2", profile, self.facts(0, 2), 2)
        self.assertEqual((denied["status"], denied["cards"], denied["added"]), ("unknown", 0, []))
        profile = next(p for p in support.ROLES["profiles"] if p["id"] == "user2")
        with mock.patch.object(filing.guard, "deck_reader", return_value=lambda ident: False) as reader:
            denied = filing.after_import(snapshot, "user2", profile, self.facts(0, 2), 2)
        reader.assert_called_once_with(profile)
        self.assertEqual(denied["status"], "unknown")
        self.assertFalse(any(item["kind"] == "storage" for item in denied["destinations"]))
