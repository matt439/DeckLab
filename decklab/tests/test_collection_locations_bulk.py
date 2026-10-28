"""Reviewed exact-printing storage batches (E8-S23), entirely in disposable files fixtures.

Run with scripts/test_fixtures.py so private config, configured PostgreSQL and native child
qualification remain guarded before these imports. PostgreSQL/audit integration is separate.
"""
import hashlib
from unittest import mock

from decklab.lib import feature_routes, inventory
from decklab.lib.api import collection_edit as ce, collection_locations as places
from decklab.lib.inventory import files, ops_collection as ops, paths, rules
from decklab.lib.state import Conflict, Invalid
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import CollectionEditTestCase

ELVES = {"set": "fdn", "collector_number": "227", "finish": "nonfoil"}
MYSTIC = {"set": "cmm", "collector_number": "648", "finish": "nonfoil"}
LOTUS = {"set": "lea", "collector_number": "232", "finish": "nonfoil"}
LOCATION_HEADER = ",".join(rules.LOCATION_FIELDS) + "\n"


class BulkLocationsTests(CollectionEditTestCase):

    def body(self, space="home", **changes):
        view = self.rows(space)
        return {"space": space, "keys": [ELVES, MYSTIC], "sha256": view["sha256"],
                "locations_sha256": view["locations"]["sha256"], "location": "Row 2, B", **changes}

    def bulk(self, space="home", profile="matt", **changes):
        return self.call(places.bulk_set, profile, **self.body(space, **changes))

    def seed_locations(self, text, space="home"):
        path = self.box.root / paths.locations(space)
        _write(path, LOCATION_HEADER + text)

    def params(self, snapshot, **changes):
        return {"space": "home", "keys": [list(rules.ident(ELVES)), list(rules.ident(MYSTIC))],
                "sha256": ops.sha256_of(snapshot.collection()),
                "locations_sha256": ops.locations_sha256_of(snapshot, "home"),
                "location": "Row 2, B", **changes}

    def test_assign_changes_only_locations_with_exact_rows_and_one_write(self):
        self.seed_locations("lea,232,nonfoil,Binder\nfdn,227,nonfoil,Row 1\n")
        before = self.backend.load()
        before_files = self.magic_files()
        with mock.patch.object(self.backend, "_write_plain", wraps=self.backend._write_plain) as write:
            answer = self.bulk(location="  Row 2,   B ")
        self.assertEqual(answer["changed"], 2)
        self.assertEqual(answer["sha256"], ops.sha256_of(before.collection()))
        self.assertEqual(answer["locations"]["rows"], {
            "fdn|227|nonfoil": "Row 2, B", "cmm|648|nonfoil": "Row 2, B", "lea|232|nonfoil": "Binder"})
        self.assertEqual(answer["locations"]["sha256"], hashlib.sha256(
            (self.box.magic / "locations.csv").read_bytes()).hexdigest())
        self.assertEqual(write.call_count, 1)
        self.assertEqual(set(write.call_args.args[1]), {"magic/locations.csv"})
        after_files = self.magic_files()
        self.assertEqual({k: v for k, v in after_files.items() if k != "magic/locations.csv"},
                         {k: v for k, v in before_files.items() if k != "magic/locations.csv"})
        after = self.backend.load()
        for field in ("collections", "tokens", "orders", "products", "watchlist", "decks", "accessories"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)
        self.assertEqual(after.decks_revision, before.decks_revision)
        self.assertFalse(inventory.refreshes("collection.locations"))
        self.assertEqual(answer["stale_tables"], [])
        self.assertEqual(self.last_write(), ("set storage locations in the home collection", "Matt"))
        self.assertIn("Row 1 -> Row 2, B", "\n".join(self.extra()))
        self.assertIn("[nonfoil]", "\n".join(self.extra()))

    def test_explicit_clear_removes_last_locations_without_rewriting_collection(self):
        self.seed_locations("fdn,227,nonfoil,Row 1\ncmm,648,nonfoil,Binder\n")
        original = (self.box.magic / "collection.csv").read_bytes()
        answer = self.bulk(location="")
        self.assertEqual((answer["changed"], answer["locations"]["rows"]), (2, {}))
        self.assertEqual(answer["locations"]["sha256"], ce.EMPTY_SHA)
        self.assertFalse((self.box.magic / "locations.csv").exists())
        self.assertEqual((self.box.magic / "collection.csv").read_bytes(), original)

    def test_noop_still_runs_under_lock_without_a_physical_write(self):
        self.seed_locations('fdn,227,nonfoil,"Row 2, B"\ncmm,648,nonfoil,"Row 2, B"\n')
        before = self.magic_files()
        with mock.patch.object(self.backend, "_write_plain", wraps=self.backend._write_plain) as write:
            answer = self.bulk()
        self.assertEqual(answer["changed"], 0)
        self.assertEqual(len(self.writes), 1)       # apply ran; this is not a durable audit count
        write.assert_not_called()
        self.assertEqual(self.magic_files(), before)

    def test_location_hash_changes_when_collection_hash_does_not(self):
        before = self.rows()
        self.seed_locations("fdn,227,nonfoil,Binder\n")
        after = self.rows()
        self.assertEqual(before["sha256"], after["sha256"])
        self.assertNotEqual(before["locations"]["sha256"], after["locations"]["sha256"])
        saved = self.magic_files()
        self.assertApiError(409, self.bulk, locations_sha256=before["locations"]["sha256"])
        self.assertEqual(self.magic_files(), saved)

    def test_location_only_race_is_checked_inside_apply_and_conflict_uses_fresh_snapshot(self):
        self.seed_locations("fdn,227,nonfoil,Row 1\n")
        before = self.backend.load()
        request = self.body()
        apply = self.backend.apply

        def race(*args, **kwargs):
            self.seed_locations("fdn,227,nonfoil,Binder\n")
            return apply(*args, **kwargs)

        with inventory.pinned(before), mock.patch.object(self.backend, "apply", side_effect=race):
            error = self.assertApiError(409, self.call, places.bulk_set, **request)
        self.assertEqual(error.extra["sha256"], request["sha256"])
        self.assertEqual(error.extra["locations"]["rows"], {"fdn|227|nonfoil": "Binder"})
        self.assertEqual(error.extra["locations"]["sha256"], self.rows()["locations"]["sha256"])
        self.assertNotEqual(error.extra["locations"]["sha256"], request["locations_sha256"])
        self.assertEqual(self.rows()["locations"]["rows"], {"fdn|227|nonfoil": "Binder"})
        self.assertEqual(self.writes, [])

    def test_collection_race_returns_rows_and_locations_from_the_same_fresh_snapshot(self):
        before = self.backend.load()
        request = self.body()
        row_text = (self.box.magic / "collection.csv").read_text(encoding="utf-8")
        quantity = next(row["quantity"] for row in self.rows()["rows"] if rules.ident(row) == rules.ident(ELVES))
        _write(self.box.magic / "collection.csv", row_text.replace(
            f"Llanowar Elves,fdn,227,nonfoil,{quantity},", "Llanowar Elves,fdn,227,nonfoil,8,"))
        self.seed_locations("fdn,227,nonfoil,Binder\n")
        with inventory.pinned(before):
            error = self.assertApiError(409, self.call, places.bulk_set, **request)
        fresh = self.rows()
        self.assertEqual(error.extra["sha256"], fresh["sha256"])
        self.assertEqual(error.extra["rows"], fresh["rows"])
        self.assertEqual(error.extra["locations"], fresh["locations"])
        self.assertEqual(error.extra["storage_box"], fresh["storage_box"])
        self.assertEqual(self.writes, [])

    def test_old_request_pin_cannot_overstate_audit_count_when_new_receipts_match_current(self):
        old = self.backend.load()
        self.seed_locations('fdn,227,nonfoil,"Row 2, B"\n')
        current = self.body()
        with inventory.pinned(old):
            answer = self.call(places.bulk_set, **current)
        self.assertEqual(answer["changed"], 1)
        self.assertEqual(self.last_write(), ("set storage locations in the home collection", "Matt"))
        summary = self.writes[-1][3]
        self.assertEqual(summary.counts["changed"], 1)
        self.assertEqual(len(self.extra()), 1)
        self.assertIn("Elvish Mystic", self.extra()[0])
        self.assertNotIn("Llanowar Elves", self.extra()[0])

    def test_noop_does_not_bypass_stale_receipts_or_missing_keys(self):
        before = self.magic_files()
        for changes in ({"sha256": "0" * 64}, {"locations_sha256": "0" * 64},
                        {"keys": [{**ELVES, "finish": "etched"}]}):
            with self.subTest(changes=changes):
                self.assertApiError(409, self.bulk, location="", **changes)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_only_the_named_finish_changes(self):
        source = (self.box.magic / "collection.csv").read_text(encoding="utf-8")
        _write(self.box.magic / "collection.csv", source + "Llanowar Elves,fdn,227,foil,1,,,\n")
        answer = self.bulk(keys=[{**ELVES, "finish": "foil"}])
        self.assertEqual(answer["locations"]["rows"], {"fdn|227|foil": "Row 2, B"})
        self.assertNotIn("fdn|227|nonfoil", answer["locations"]["rows"])

    def test_home_member_and_person_owner_can_edit_but_admin_has_no_cross_space_override(self):
        with self.as_("user1"):
            self.assertEqual(self.bulk(profile="user1")["changed"], 2)
        with self.as_("user2"):
            self.assertEqual(self.bulk("user2", "user2", keys=[ELVES])["changed"], 1)
            self.assertApiError(403, self.call, places.bulk_set, profile="user2", space="home",
                                keys=None, sha256=None, locations_sha256=None, location=None)
        self.assertApiError(403, self.call, places.bulk_set, space="user2", keys=None,
                            sha256=None, locations_sha256=None, location=None)

    def test_bad_values_duplicate_keys_and_overflow_refuse_without_writing(self):
        before = self.magic_files()
        for changes in ({"location": None}, {"location": 2}, {"location": "x" * 41},
                        {"location": "Row\n2"}, {"location": " @formula"},
                        {"locations_sha256": "bad"}, {"sha256": None}, {"keys": []},
                        {"keys": [ELVES, {**ELVES, "set": "FDN"}]},
                        {"keys": [{**ELVES, "finish": "glossy"}]}):
            with self.subTest(changes=changes):
                self.assertApiError(400, self.bulk, **changes)
        with mock.patch.object(ce, "MAX_BULK_KEYS", 1):
            self.assertApiError(400, self.bulk)
        with mock.patch.object(ce, "MAX_BULK_BODY", 100):
            self.assertApiError(413, self.bulk)
        data = self.body()
        del data["location"]
        self.assertApiError(400, self.call, places.bulk_set, **data)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_missing_migration_blocks_assignment_clear_and_noop_inside_operation(self):
        old = self.backend.load().replace(locations_ready=False)
        for location in ("Row 2", ""):
            with self.subTest(location=location):
                with self.assertRaisesRegex(Conflict, "migration 0016"):
                    ops.bulk_locations(old, **self.params(old, location=location))
        with mock.patch.object(self.backend, "load", return_value=old), \
                mock.patch.object(self.backend, "apply", side_effect=Conflict(rules.LOCATION_REQUIRED)):
            error = self.assertApiError(409, self.bulk, location="", contains="migration 0016")
        self.assertFalse(error.extra["locations"]["ready"])

    def test_operation_checks_keys_and_location_without_trusting_api_validation(self):
        snapshot = self.backend.load()
        for changes in ({"keys": []}, {"keys": [["fdn", "227"]]}, {"keys": [["fdn", 227, "nonfoil"]]},
                        {"keys": [list(rules.ident(ELVES))] * 2}, {"location": None},
                        {"sha256": None}, {"locations_sha256": "bad"}):
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                ops.bulk_locations(snapshot, **self.params(snapshot, **changes))

    def test_bad_or_orphan_location_source_has_no_writable_receipt_and_is_never_rebuilt(self):
        for data in (b"\xff", (LOCATION_HEADER + "fdn,227,nonfoil,=bad\n").encode(),
                     (LOCATION_HEADER + "fdn,227,nonfoil,Row 1\nfdn,227,nonfoil,Row 2\n").encode(),
                     (LOCATION_HEADER + "fdn,227,nonfoil,Row 1\nxxx,9,nonfoil,Unknown box\n").encode()):
            with self.subTest(data=data):
                (self.box.magic / "locations.csv").write_bytes(data)
                before = self.magic_files()
                view = self.rows()
                self.assertIsNone(view["locations"]["sha256"])
                self.assertTrue(view["locations"]["error"])
                error = self.assertApiError(409, self.bulk, locations_sha256=ce.EMPTY_SHA)
                self.assertIsNone(error.extra["locations"]["sha256"])
                self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_location_receipt_is_space_scoped_and_does_not_expose_another_space(self):
        self.seed_locations("fdn,227,nonfoil,Binder\n", "user2")
        home = self.rows()
        self.assertEqual(home["locations"]["sha256"], ce.EMPTY_SHA)
        answer = self.bulk()
        self.assertEqual(answer["locations"]["sha256"], files.rendered_sha256(
                         self.backend.load().location_sheet("home")))
        self.assertEqual(self.backend.load().locations_of("user2"), {("fdn", "227", "nonfoil"): "Binder"})

    def test_route_uses_existing_bulk_body_limit(self):
        handler = mock.Mock(command="POST")
        with mock.patch.object(places, "bulk_set", return_value={"ok": True}) as call:
            feature_routes.dispatch(handler, ("collection", "locations", "bulk"), {})
        call.assert_called_once()
        handler._write_body.assert_called_once_with(ce.MAX_BULK_BODY)
