"""Ordinary-import filing advice over actual JSON deltas and disposable saved snapshots.

The guarded fixture runner installs protection before these imports. No PostgreSQL, native
runtime, service or real household records are involved.
"""
import json
from collections import Counter
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import collection_edit as ce, collection_filing as filing
from decklab.lib.inventory import files, ops_collection as ops, paths, rules
from decklab.tests import test_collection_edit as support
from decklab.tests.test_api import _write
from decklab.tests.test_collection_import_groups import DECKBOX_SHARED, MIXED

ELVES = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil"}
MYSTIC = {"name": "Elvish Mystic", "set": "cmm", "collector_number": "648", "finish": "nonfoil"}


def deck_text(title, need=2, status="building", owned=None, name="Llanowar Elves"):
    text = f"# {title}\n\n- **Format:** Casual 60-card\n- **Status:** {status}\n"
    if owned is not None:
        text += "- **Built version:** owned-only\n"
    text += f"\n## Decklist\n\n```\nDeck\n{need} {name}\n```\n"
    if owned is not None:
        text += f"\n### Owned-only version\n\n```\nDeck\n{owned} {name}\n```\n"
    return text


class FilingTests(support.CollectionEditTestCase):

    def profile(self, space="home"):
        return next(dict(p) for p in support.ROLES["profiles"] if p["id"] == ("matt" if space == "home" else space))

    def snapshot(self, quantity=4, decks=(), space="home", extra_rows=(), other=None):
        rows = [{**ELVES, "quantity": str(quantity), "condition": "", "language": "", "notes": ""}, *extra_rows]
        source = {paths.collection(space): rules.collection_csv_bytes(rows),
                  paths.STATUS: (",".join(rules.STATUS_FIELDS) + "\n").encode()}
        for ident, text in decks:
            source[f"{paths.decks_dir(space)}/casual/{ident}.md"] = text.encode()
        source.update(other or {})
        return files.build(source)

    def facts(self, before=2, added=2, row=None):
        return [{**(row or ELVES), "quantity": added, "before_quantity": before, "after_quantity": before + added}]

    def advice(self, snapshot=None, facts=None, space="home", total=None, profile=None):
        snapshot = snapshot or self.snapshot(decks=[("a", deck_text("A")), ("b", deck_text("B"))])
        facts = self.facts() if facts is None else facts
        total = sum(row["quantity"] for row in facts) if total is None else total
        return filing.after_import(snapshot, space, profile or self.profile(space), facts, total)

    def assert_conserved(self, answer):
        counts = Counter()
        for destination in answer["destinations"]:
            self.assertGreater(destination["quantity"], 0)
            self.assertIn(destination["kind"], ("deck", "storage", "unknown"))
            counts[destination["row"]] += destination["quantity"]
        self.assertEqual([counts[i] for i in range(len(answer["added"]))],
                         [row["quantity"] for row in answer["added"]])
        json.dumps(answer, allow_nan=False)

    def test_prior_free_copies_are_consumed_globally_before_new_copies(self):
        answer = self.advice()
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "deck", "row": 0, "quantity": 2,
                         "deck": {"id": "casual/b", "title": "B", "status": "building"}}])
        self.assert_conserved(answer)

    def test_one_new_copy_is_never_suggested_to_multiple_competing_decks(self):
        snapshot = self.snapshot(1, [("b", deck_text("B", 1)), ("a", deck_text("A", 1)),
                                     ("c", deck_text("C", 1))])
        answer = self.advice(snapshot, self.facts(0, 1))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual([(d["deck"]["id"], d["quantity"]) for d in answer["destinations"]], [("casual/a", 1)])
        self.assert_conserved(answer)

    def test_existing_stock_satisfies_all_waiting_decks_then_new_copies_are_storage(self):
        answer = self.advice(self.snapshot(6, [("a", deck_text("A")), ("b", deck_text("B"))]), self.facts(4, 2))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "storage", "row": 0, "quantity": 2}])
        self.assert_conserved(answer)

    def test_built_own_holds_are_reserved_and_priority_is_built_building_then_id(self):
        snapshot = self.snapshot(5, [("idea", deck_text("Idea", 3, "idea")),
                                     ("z-built", deck_text("Built", 3, "built", owned=2)),
                                     ("b-building", deck_text("Second", 2)),
                                     ("a-building", deck_text("First", 2))])
        answer = self.advice(snapshot, self.facts(2, 3))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual([(d["deck"]["id"], d["quantity"]) for d in answer["destinations"]],
                         [("casual/z-built", 1), ("casual/a-building", 2)])
        self.assert_conserved(answer)

    def test_intact_holds_and_incoming_copies_are_not_prior_free_stock(self):
        snapshot = self.snapshot(3, [("a", deck_text("A", 1)), ("b", deck_text("B", 2))])
        found = pool.Pool(Counter({"Llanowar Elves": 10}), {"Llanowar Elves": [("order fixture", 7)]},
                          [pool.InUse("product/fixture", "Fixture product", "intact product",
                                      Counter({"Llanowar Elves": 2}))])
        with mock.patch.object(filing.pool, "load_pool", return_value=found) as load:
            answer = self.advice(snapshot, self.facts(2, 1))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"][0]["deck"]["id"], "casual/a")
        self.assertEqual(answer["destinations"][0]["quantity"], 1)
        load.assert_called_once_with("home")
        self.assert_conserved(answer)

    def test_multiple_printings_spend_one_global_physical_budget(self):
        foil = {**ELVES, "finish": "foil", "quantity": "2", "condition": "", "language": "", "notes": ""}
        snapshot = self.snapshot(2, [("a", deck_text("A", 3)), ("b", deck_text("B", 3))], extra_rows=[foil])
        facts = self.facts(0, 2) + self.facts(0, 2, {**ELVES, "finish": "foil"})
        answer = self.advice(snapshot, facts)
        self.assertEqual(answer["status"], "ready")
        self.assertEqual([(d["row"], d["quantity"], d["deck"]["id"]) for d in answer["destinations"]],
                         [(0, 2, "casual/a"), (1, 1, "casual/a"), (1, 1, "casual/b")])
        self.assert_conserved(answer)

    def test_unreadable_candidate_pool_or_stock_mismatch_is_unknown_not_storage(self):
        bad = self.snapshot(decks=[("broken", "not a deck list")])
        cases = [(bad, None), (self.snapshot(2, [("built", deck_text("Held", 3, "built"))]), None)]
        for snapshot, _ in cases:
            with self.subTest(snapshot=snapshot):
                answer = self.advice(snapshot, self.facts(0 if snapshot.collection().rows[0].qty == 2 else 2, 2))
                self.assertEqual(answer["status"], "unknown")
                self.assertTrue(all(d["kind"] == "unknown" for d in answer["destinations"]))
                self.assert_conserved(answer)
        for found in (pool.Pool(Counter({"Llanowar Elves": 4}), {}, [], warnings=["private fixture detail"]),
                      pool.Pool(Counter({"Llanowar Elves": 4}), {}, [], unresolved={"Unknown": {"secret"}})):
            with mock.patch.object(filing.pool, "load_pool", return_value=found):
                answer = self.advice()
            self.assertEqual(answer["status"], "unknown")
            self.assertNotIn("private fixture detail", json.dumps(answer))
            self.assert_conserved(answer)

    def test_saved_snapshot_is_pinned_without_any_later_backend_load(self):
        snapshot = self.snapshot(decks=[("a", deck_text("A")), ("b", deck_text("B"))])
        with inventory.pinned(self.backend.load()), mock.patch.object(self.backend, "load", side_effect=AssertionError("later load")):
            answer = self.advice(snapshot)
        self.assertEqual(answer["status"], "ready")
        self.assert_conserved(answer)

    def test_member_advice_uses_only_own_space_even_when_other_decks_are_public(self):
        snapshot = self.snapshot(2, [("a", deck_text("Member"))], space="user2", other={
            "magic/decks/casual/private-home.md": deck_text("Hidden home", 4).encode(),
            "magic/people/user3/decks/casual/private-other.md": b"unreadable hidden deck"})
        with self.as_("user2"), mock.patch.object(filing.guard, "public_deck_spaces", return_value={"home", "user3"}):
            answer = self.advice(snapshot, self.facts(0, 2), space="user2")
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["profile"], "user2")
        self.assertEqual(answer["destinations"][0]["deck"]["id"], "user2/casual/a")
        self.assertNotIn("Hidden home", json.dumps(answer))
        self.assertNotIn("private-other", json.dumps(answer))
        self.assert_conserved(answer)

    def test_unauthorized_helper_call_reveals_no_addition_or_deck_facts(self):
        answer = self.advice(profile=self.profile("user2"))
        self.assertEqual((answer["status"], answer["added"], answer["destinations"], answer["cards"]),
                         ("unknown", [], [], 0))

    def test_permission_check_failure_is_closed_before_any_import_facts_are_returned(self):
        with mock.patch.object(filing.guard, "sees_inventory", side_effect=RuntimeError("unavailable permission")):
            answer = self.advice()
        self.assertEqual((answer["status"], answer["added"], answer["destinations"], answer["cards"]),
                         ("unknown", [], [], 0))

    def test_assembled_snapshot_reservations_are_independent_of_changed_planned_demand(self):
        text = deck_text("Built", 1, "built")
        assembled = json.dumps({"version": "target", "sections": {"Deck": ["2 Elvish Mystic"]}})
        text = text.replace("\n\n## Decklist", f"\n- **Assembled:** {assembled}\n\n## Decklist")
        mystics = {**MYSTIC, "quantity": "2", "condition": "", "language": "", "notes": ""}
        snapshot = self.snapshot(1, [("built", text)], extra_rows=[mystics])
        answer = self.advice(snapshot, self.facts(0, 1))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "deck", "row": 0, "quantity": 1,
                         "deck": {"id": "casual/built", "title": "Built", "status": "built"}}])
        self.assert_conserved(answer)

    def test_considering_is_not_waiting_deck_demand(self):
        text = deck_text("Considering only", 1, name="Elvish Mystic")
        text += "\n## Considering\n\n```\n4 Llanowar Elves\n```\n"
        answer = self.advice(self.snapshot(1, [("ideas", text)]), self.facts(0, 1))
        self.assertEqual(answer["status"], "ready")
        self.assertEqual(answer["destinations"], [{"kind": "storage", "row": 0, "quantity": 1}])
        self.assert_conserved(answer)

    def test_tracked_special_basic_additions_have_unknown_physical_destinations(self):
        basic = {"name": "Forest", "set": "fdn", "collector_number": "280", "finish": "foil"}
        snapshot = self.snapshot(extra_rows=[{**basic, "quantity": "2", "condition": "", "language": "",
                                              "notes": "full art"}])
        answer = self.advice(snapshot, self.facts(0, 2, basic))
        self.assertEqual(answer["status"], "unknown")
        self.assertEqual(answer["added"], [{**basic, "quantity": 2}])
        self.assertEqual(answer["destinations"], [{"kind": "unknown", "row": 0, "quantity": 2}])
        self.assert_conserved(answer)

    def test_installed_marker_holds_are_kept_and_inconsistent_version_is_unknown(self):
        mapping = {"for": "Llanowar Elves", "using": "Elvish Mystic", "qty": 1}
        mystic = {**MYSTIC, "quantity": "1", "condition": "", "language": "", "notes": ""}
        for version in ("target", "owned"):
            with self.subTest(version=version):
                installed = json.dumps({"target": [mapping], "built": {"version": version, "cards": [mapping]}})
                text = deck_text("Marker", 1, "built").replace(
                    "\n\n## Decklist", f"\n- **Stand-ins:** {installed}\n\n## Decklist")
                answer = self.advice(self.snapshot(1, [("marker", text)], extra_rows=[mystic]), self.facts(0, 1))
                self.assertEqual(answer["status"], "ready" if version == "target" else "unknown")
                self.assertEqual(answer["destinations"][0]["kind"], "deck" if version == "target" else "unknown")
                self.assert_conserved(answer)

    def test_caps_and_calculation_errors_never_infer_storage(self):
        snapshot = self.snapshot(decks=[("a", deck_text("A", 1)), ("b", deck_text("B", 1))])
        for key, limit in (("MAX_DECKS", 1), ("MAX_WORK", 1), ("MAX_DESTINATIONS", 1)):
            with self.subTest(key=key), mock.patch.object(filing, key, limit):
                answer = self.advice(snapshot, self.facts(0, 4))
                self.assertEqual(answer["status"], "unknown")
                self.assertTrue(all(d["kind"] == "unknown" for d in answer["destinations"]))
                self.assert_conserved(answer)
        with mock.patch.object(filing.pool, "load_pool", side_effect=RuntimeError("sensitive fixture exception")):
            answer = self.advice()
        self.assertEqual(answer["status"], "unknown")
        self.assertNotIn("sensitive", json.dumps(answer))
        self.assert_conserved(answer)

    def test_manifest_must_match_saved_exact_printing_totals_and_counts(self):
        for facts, total in ((self.facts(2, 2), 3), (self.facts(0, 2), 2),
                             (self.facts(2, 2) * 2, 4), (self.facts(2, 2, MYSTIC), 2)):
            with self.subTest(facts=facts, total=total):
                answer = self.advice(self.snapshot(), facts, total=total)
                self.assertEqual(answer["status"], "unknown")
                self.assertFalse(any(d["kind"] == "storage" for d in answer["destinations"]))
        with mock.patch.object(filing, "MAX_ADDED_ROWS", 0):
            answer = self.advice()
        self.assertEqual((answer["status"], answer["added"]), ("unknown", []))


class FilingImportTests(support.CollectionEditTestCase):

    def preview(self, text, space="user2"):
        return self.call(ce.import_preview, space, space=space, filename="filing.csv", text=text)

    def apply(self, preview, space="user2", **data):
        return self.call(ce.import_apply, space, space=space, token=preview["token"],
                         sha256=self.rows(space)["sha256"], **data)

    def test_actual_import_captures_only_json_addition_facts_and_keeps_raw_upload(self):
        text = support.HEADER + "Llanowar Elves,fdn,227,nonfoil,2,LP,ja,retained\n"
        before = self.backend.load()
        answer = self.apply(self.preview(text))
        summary = self.writes[-1][3]
        facts = summary.extra["added_printings"]
        self.assertEqual(facts, [{**ELVES, "quantity": 2, "before_quantity": 2, "after_quantity": 4}])
        json.dumps(facts)
        self.assertEqual((self.box.root / answer["raw"]).read_bytes(), text.encode())
        self.assertEqual(answer["filing"]["added"], [{**ELVES, "quantity": 2}])
        self.assertEqual(answer["filing"]["status"], "ready")
        self.assertEqual(answer["filing"]["destinations"], [{"kind": "storage", "row": 0, "quantity": 2}])
        self.assertEqual(self.backend.load().decks, before.decks)
        self.assertEqual(set(summary.extra), {"body", "imports", "raw", "added_printings"})
        self.assertNotIn("before_quantity", json.dumps(answer["filing"]))
        json.dumps(answer)

    def test_group_exclusions_and_converged_printings_cannot_reappear_in_filing(self):
        preview = self.preview(DECKBOX_SHARED)
        keep = next(group for group in preview["groups"] if group["code"] == "fdn")
        skip = [group["id"] for group in preview["groups"] if group["id"] != keep["id"]]
        answer = self.apply(preview, skip_groups=skip)
        self.assertEqual(answer["added"]["cards"], 2)
        self.assertEqual(answer["filing"]["added"], [{**ELVES, "quantity": 2}])
        self.assertEqual(answer["excluded_groups"][0]["valid_cards"], 3)
        self.assertEqual((self.box.root / answer["raw"]).read_bytes(), DECKBOX_SHARED.encode())

    def test_skipped_problem_rows_and_untracked_basics_never_enter_manifest(self):
        answer = self.apply(self.preview(MIXED), skip_problems=True)
        self.assertEqual(sum(row["quantity"] for row in answer["filing"]["added"]), answer["added"]["cards"])
        self.assertEqual({row["name"] for row in answer["filing"]["added"]},
                         {"Llanowar Elves", "Aerie Mystics", "Sol Ring"})

    def test_advice_failure_is_still_success_and_consumes_preview_without_reimport(self):
        text = support.HEADER + "Llanowar Elves,fdn,227,nonfoil,2,,,\n"
        preview = self.preview(text)
        with mock.patch.object(filing, "after_import", side_effect=RuntimeError("do not expose")):
            answer = self.apply(preview)
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["filing"]["status"], "unknown")
        self.assertEqual(self.rows("user2")["rows"][0]["quantity"], "4")
        self.assertEqual((self.box.root / answer["raw"]).read_bytes(), text.encode())
        self.assertApiError(410, self.apply, preview)
        self.assertNotIn("do not expose", json.dumps(answer))

    def test_nonordinary_merge_and_precon_parameters_remain_opt_out(self):
        profile = next(p for p in support.ROLES["profiles"] if p["id"] == "matt")
        record = {"filename": "scanner.csv", "text": support.OWN_COLUMNS, "format": "collection",
                  "good": [{"name": "Aerie Mystics", "set": "con", "collector_number": "1", "finish": "foil",
                            "quantity": "3", "condition": "LP", "language": "en", "notes": ""}], "problems": []}
        self.assertNotIn("capture_additions", ce.import_params("home", self.rows()["sha256"], record))
        answer = ce.merge_upload("home", profile, self.rows()["sha256"], record)
        self.assertNotIn("filing", answer)
        self.assertNotIn("added_printings", self.writes[-1][3].extra)

    def test_apply_snapshot_opt_in_is_exact_backend_result_and_default_is_sheet(self):
        snapshot = self.backend.load()
        op = inventory.Op("collection.locations", {"space": "home", "keys": [["fdn", "227", "nonfoil"]],
                          "sha256": ops.sha256_of(snapshot.collection()),
                          "locations_sha256": ops.locations_sha256_of(snapshot, "home"), "location": ""})
        actor = inventory.Actor("matt", "Matt", "home", "test")
        with mock.patch.object(inventory, "apply", return_value=(snapshot, inventory.Summary())):
            actual, _ = ce._apply("home", op, actor, message="Fixture", return_snapshot=True)
            sheet, _ = ce._apply("home", op, actor, message="Fixture")
        self.assertIs(actual, snapshot)
        self.assertIs(sheet, snapshot.collection())
