"""Exact read-only field explanations over disposable lists and fake readers.

Run with python scripts/test_fixtures.py decklab.tests.test_field_membership.
No configured inventory, engine discovery, saved evidence or games are used.
"""
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from decklab.lib import decks, inventory, spaces
from decklab.lib.forge import engine, field, field_membership as membership, runner, saved
from decklab.lib.inventory.files import FileInventory
from decklab.tests import test_forge_field as fixtures


class MembershipInventoryTests(fixtures.FieldTestCase):
    def setUp(self):
        super().setUp()
        for owner, name in ((runner, "run"), (saved, "load"), (saved, "_stored"),
                            (engine, "today"), (engine, "read_only_today")):
            patcher = mock.patch.object(owner, name, side_effect=AssertionError("Membership is read-only"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def view(self, deck_id="casual/alpha", **kwargs):
        return membership.view(self.entry(deck_id), **kwargs)

    def by_list(self, answer):
        self.assertTrue(answer["complete"], answer)
        self.assertIsNone(answer["error"])
        return {(row["id"], row["version"]): row for row in answer["rows"]}

    def test_real_rules_have_exact_versions_products_and_self_membership(self):
        answer = self.view()
        rows = self.by_list(answer)
        included = {key for key, row in rows.items() if row["in_field"]}
        self.assertEqual(included, {("casual/alpha", "target"), ("casual/beta", "owned"),
                                    ("casual/gamma", "target"), ("product/aggro", "target")})
        self.assertEqual(answer["counts"], {"included": 4, "opponents": 3, "manual_excluded": 0})
        self.assertFalse(rows[("casual/alpha", "target")]["opponent"])
        self.assertEqual(rows[("casual/beta", "target")]["reason"], "other_version")
        self.assertEqual(rows[("product/blank", "target")]["reason"], "product_not_intact")
        self.assertEqual(rows[("product/broken-up", "target")]["reason"], "product_not_intact")
        self.assertEqual(rows[("casual/broken", "target")]["reason"], "unreadable")
        self.assertEqual(rows[("product/fdn-beginner-box/cats", "target")]["reason"], "beginner_half")
        self.assertEqual(rows[("pairing/cats+elves", "target")]["reason"], "pairing")
        self.assertNotIn("product/precon", {row["id"] for row in answer["rows"]})
        self.assertTrue(all(row["card_sha"] is None for row in answer["rows"] if not row["in_field"]))

    def test_trace_preserves_legacy_entries_notes_and_actual_removals(self):
        fixtures._write(self.simulation, json.dumps({"field": {"Constructed": {
            "add": ["product/blank", "pairing/elves+cats", "commander/cmdr", "casual/missing"],
            "remove": ["casual/alpha", "casual/alpha", "casual/beta@target", "casual/missing"]}}}))
        before = field._field("Constructed")
        trace = membership._Trace(None, True)
        traced = field._field("Constructed", trace=trace)
        self.assertEqual(before, traced)
        answer = self.view()
        rows = self.by_list(answer)
        self.assertEqual(answer["counts"], {"included": 5, "opponents": 5, "manual_excluded": 1})
        self.assertEqual(rows[("casual/alpha", "target")]["reason"], "configured_remove")
        self.assertEqual(rows[("pairing/cats+elves", "target")]["reason"], "configured_add")
        self.assertEqual(rows[("product/blank", "target")]["reason"], "configured_add")
        text = json.dumps(answer)
        self.assertNotIn("casual/missing", text)
        self.assertNotIn("simulation.json", text)
        self.assertNotIn("isn't a Constructed", text)

    def test_explicit_alternative_list_replaces_default_and_versions_are_not_hash_collapsed(self):
        fixtures._write(self.simulation, json.dumps({"field": {"Constructed": {
            "add": ["casual/beta@target"], "remove": []}}}))
        rows = self.by_list(self.view())
        self.assertTrue(rows[("casual/beta", "target")]["in_field"])
        self.assertEqual(rows[("casual/beta", "target")]["reason"], "configured_add")
        self.assertFalse(rows[("casual/beta", "owned")]["in_field"])
        # Gamma's two versions have identical simulation cards but remain exact lists.
        self.assertIn(("casual/gamma", "target"), rows)
        self.assertIn(("casual/gamma", "owned"), rows)
        self.assertEqual(rows[("casual/gamma", "owned")]["reason"], "other_version")

    def test_one_inventory_snapshot_and_one_configuration_read_supply_the_whole_answer(self):
        entry = self.entry("casual/alpha")
        original = FileInventory.load
        with mock.patch.object(FileInventory, "load", autospec=True, side_effect=original) as load, \
                mock.patch.object(field, "_simulation_edits", wraps=field._simulation_edits) as config:
            answer = membership.view(entry)
        self.assertTrue(answer["complete"])
        load.assert_called_once()
        config.assert_called_once()
        self.assertIsNotNone(config.call_args.kwargs["trace"])

    def test_unreadable_selected_list_is_static_exclusion_without_raw_error(self):
        original = field._entry
        def checked(summary, version):
            if summary["id"] == "casual/alpha":
                raise ValueError("fixture-private-path-and-card")
            return original(summary, version)
        entry = self.entry("casual/alpha")
        with mock.patch.object(field, "_entry", side_effect=checked):
            answer = membership.view(entry)
        row = self.by_list(answer)[("casual/alpha", "target")]
        self.assertEqual((row["in_field"], row["reason"]), (False, "unreadable"))
        self.assertEqual(answer["counts"]["included"], 3)
        self.assertNotIn("fixture-private", json.dumps(answer))

    def test_missing_config_uses_defaults_but_malformed_config_is_explicitly_incomplete(self):
        self.assertTrue(self.view()["complete"])
        for text in ("{bad", "[]", '{"field": []}', '{"field":{"Constructed":{"add":"casual/alpha"}}}'):
            with self.subTest(text=text):
                fixtures._write(self.simulation, text)
                answer = self.view()
                self.assertEqual((answer["complete"], answer["rows"], answer["counts"]), (False, [], None))
                self.assertEqual(answer["error"], membership.UNAVAILABLE)
        # The existing malformed-JSON fallback remains unchanged for ordinary callers.
        fixtures._write(self.simulation, "{bad")
        self.assertEqual(len(field.field_lists("Constructed")), 4)

    def test_commander_does_not_enumerate_pairings_and_has_no_simulation_dependency(self):
        with mock.patch.object(decks, "beginner_box_pairings", side_effect=AssertionError("Wrong format")):
            answer = self.view("commander/cmdr")
        self.assertEqual(answer["format"], "Commander")
        self.assertEqual({row["id"] for row in answer["rows"] if row["in_field"]},
                         {"commander/cmdr", "product/precon"})


class MembershipVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.summaries = [self.summary(deck_id) for deck_id in (
            "sample/casual/base", "sample/casual/second", "private/casual/secret",
            "casual/public", "product/owned", "product/ordered", "product/blank")]
        self.visible = {row["id"] for row in self.summaries if row["id"].startswith("sample/")}
        self.public = set()
        self.add, self.remove = [], []
        self.statuses = {"owned.csv": SimpleNamespace(status="owned", intact=True),
                         "ordered.csv": SimpleNamespace(status="ordered", intact=True),
                         "blank.csv": SimpleNamespace(status="owned", intact=False)}
        patches = [mock.patch.object(inventory, "is_pinned", return_value=True),
                   mock.patch.object(decks, "list_decks", side_effect=lambda: self.summaries),
                   mock.patch.object(decks, "find_summary", side_effect=self.find),
                   mock.patch.object(decks, "beginner_box_pairings", return_value=[]),
                   mock.patch.object(field.card_pool, "read_status", side_effect=lambda: self.statuses),
                   mock.patch.object(field, "_entry", side_effect=self.entry),
                   mock.patch.object(field, "_simulation_edits", side_effect=lambda *a, **k: (self.add, self.remove)),
                   mock.patch.object(field, "_same_id", side_effect=lambda a, b: a == b),
                   mock.patch.object(field.deck_identity, "canonical", side_effect=lambda deck_id: deck_id),
                   mock.patch.object(field.common, "_log")]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def summary(self, deck_id):
        return {"id": deck_id, "space": spaces.space_of(deck_id), "title": deck_id,
                "kind": "product" if deck_id.startswith("product/") else "casual",
                "versions": ["target"], "status": "building"}

    def find(self, deck_id):
        return next((row for row in self.summaries if row["id"] == deck_id), None)

    def entry(self, summary, version="target"):
        return {"id": summary["id"], "title": summary["title"], "kind": "constructed", "version": version,
                "card_sha": hashlib.sha256(summary["id"].encode()).hexdigest()}

    def options(self, space="sample", product_notes=False):
        return {"space": space, "visible": lambda deck_id: deck_id in self.visible,
                "public": lambda owner: owner in self.public, "product_notes": product_notes}

    def view(self, **kwargs):
        return membership.view(self.entry(self.summaries[0]), **self.options(**kwargs))

    def test_hidden_configuration_refs_change_neither_rows_counts_nor_reader_calls(self):
        before = self.view()
        self.add = ["private/casual/secret", "missing/casual/no-list"]
        self.remove = ["private/casual/secret", "missing/casual/no-list", "private/casual/secret@owned"]
        with mock.patch.object(decks, "find_summary", side_effect=AssertionError("Hidden alias lookup")), \
                mock.patch.object(decks, "beginner_box_pairings", side_effect=AssertionError("Hidden home")):
            after = self.view()
        self.assertEqual(before, after)
        self.assertEqual(after["counts"], {"included": 2, "opponents": 1, "manual_excluded": 0})

    def test_public_to_private_removes_rows_and_counts_on_the_next_read(self):
        self.public = {"home"}
        self.visible |= {"casual/public", "product/owned", "product/blank"}
        public = self.view()
        self.assertEqual(public["counts"]["included"], 4)
        blank = next(row for row in public["rows"] if row["id"] == "product/blank")
        self.assertEqual(blank["reason"], "product_not_selected")
        self.assertNotIn("product/ordered", {row["id"] for row in public["rows"]})
        self.public.clear()
        self.visible = {row["id"] for row in self.summaries if row["id"].startswith("sample/")}
        private = self.view()
        self.assertEqual(private["counts"]["included"], 2)
        self.assertNotIn("product/", json.dumps(private))

    def test_visible_raw_alias_cannot_publish_a_hidden_canonical_summary(self):
        self.visible.add("sample/casual/former")
        self.add = ["sample/casual/former"]
        with mock.patch.object(decks, "find_summary", return_value=self.summaries[2]):
            answer = self.view()
        self.assertNotIn("secret", json.dumps(answer))
        self.assertEqual(answer["counts"]["included"], 2)

    def test_visible_and_hidden_alias_removals_preserve_authoritative_legacy_selection(self):
        aliases = {"sample/casual/old": "sample/casual/second",
                   "private/casual/former": "sample/casual/second"}
        canonical = lambda deck_id: aliases.get(deck_id, deck_id)
        for alias in aliases:
            with self.subTest(alias=alias):
                self.remove = [alias, alias, alias + "@owned"]
                if alias.startswith("sample/"):
                    self.visible.add(alias)
                with mock.patch.object(field, "_same_id", side_effect=lambda a, b: canonical(a) == canonical(b)), \
                        mock.patch.object(field.deck_identity, "canonical", side_effect=canonical):
                    before = field._field("Constructed", **self.options())
                    trace = membership._Trace(self.options()["visible"], False)
                    traced = field._field("Constructed", **self.options(), trace=trace)
                    answer = self.view()
                self.assertEqual(before, traced)
                self.assertEqual(answer["counts"]["included"], 1)
                self.assertEqual(answer["counts"]["manual_excluded"], int(alias.startswith("sample/")))
                second = next(row for row in answer["rows"] if row["id"] == "sample/casual/second")
                self.assertEqual(second["reason"], "configured_remove" if alias.startswith("sample/") else "not_selected")

    def test_status_failure_only_invalidates_a_field_with_visible_relevant_products(self):
        with mock.patch.object(field.card_pool, "read_status", side_effect=ValueError("private-provenance")):
            self.assertTrue(self.view()["complete"])
            self.public = {"home"}
            self.visible.add("product/owned")
            answer = self.view()
        self.assertEqual((answer["complete"], answer["rows"], answer["counts"]), (False, [], None))
        self.assertNotIn("private-provenance", json.dumps(answer))

    def test_visible_row_cap_fails_without_partial_totals_but_hidden_rows_do_not_consume_it(self):
        with mock.patch.object(membership, "MAX_ROWS", 2):
            self.assertTrue(self.view()["complete"])
            self.summaries.append(self.summary("sample/casual/third"))
            self.visible.add("sample/casual/third")
            answer = self.view()
        self.assertEqual((answer["complete"], answer["rows"], answer["counts"]), (False, [], None))
        self.assertEqual(answer["error"], membership.TOO_LARGE)

    def test_pairing_cap_runs_before_enumerating_all_recipes(self):
        self.summaries = [self.summary("product/fdn-beginner-box/" + name) for name in ("a", "b", "c", "d")]
        self.visible = {summary["id"] for summary in self.summaries}
        with mock.patch.object(membership, "MAX_ROWS", 5), \
                mock.patch.object(decks, "beginner_box_pairings", side_effect=AssertionError("Quadratic reader")):
            answer = self.view(space="home")
        self.assertEqual(answer["error"], membership.TOO_LARGE)
        self.assertIsNone(answer["counts"])
