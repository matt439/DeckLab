"""Audited member-email edits/recovery use guarded disposable databases and temporary config only."""
import copy
import json
import threading
import unittest
from unittest import mock

from decklab.db import conn as db, profile_edits, profiles_sync
from decklab.lib import config, profile_config, profiles
from decklab.tests import db_support
from decklab.tests.test_profile_edits import ACTOR, TemporaryConfig


class Crash(BaseException):
    pass


class ProfileEditDatabaseTests(db_support.DbTestCase, TemporaryConfig):
    def setUp(self):
        # Keep the guarded test server's connection settings when replacing its config source.
        settings = db.settings()
        TemporaryConfig.setUp(self)
        self.raw["database"] = {"host": settings["host"], "port": settings["port"]}
        self.write(self.raw)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES + db_support.STATE_TABLES
                         + ("profile_email", "profile", "space"))
        db_support.seed_membership(self.dbname, self.raw["profiles"])

    def view(self):
        return profile_edits.preview(actor=ACTOR, dbname=self.dbname)

    def save(self, view=None, old="old@example.com", new="new@example.com", **extra):
        view = self.view() if view is None else view
        return profile_edits.apply("user2", old, new, config_sha256=view["config_sha256"],
                                   membership_sha256=view["membership_sha256"], actor=ACTOR,
                                   dbname=self.dbname, **extra)

    def emails(self):
        with self.connect("ro") as c:
            return c.execute("select email from profile_email where profile_id='user2' order by email").fetchall()

    def count(self):
        with self.connect("ro") as c:
            return c.execute("select count(*) from audit.change_set").fetchone()[0]

    def test_saved_receipt_aliases_raw_fields_and_actual_web_audit(self):
        view = self.view()
        self.assertEqual(view["members"], [{"id": "user2", "name": "User2",
                                            "emails": ["old@example.com", "alias@example.com"]}])
        result = self.save(view, old=" OLD@Example.COM ", new=" NEW@Example.com ")
        self.assertTrue(result["saved"])
        self.assertFalse(result["noop"])
        self.assertTrue(result["access_policy_required"])
        self.assertEqual(result["replaced"], {"old_email": "old@example.com", "new_email": "new@example.com"})
        expected = copy.deepcopy(self.raw)
        expected["profiles"][2]["emails"][0] = "new@example.com"
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        self.assertEqual(self.emails(), [("alias@example.com",), ("new@example.com",)])
        self.assertEqual(self.view()["config_sha256"], result["config_sha256"])
        self.assertEqual(self.view()["membership_sha256"], result["membership_sha256"])
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select actor,source,via from audit.change_set where id=%s",
                                       (result["change_set_id"],)).fetchone(), ("matt", "web", "home"))
            self.assertEqual(c.execute("select table_name,op from audit.row_change order by id").fetchall(),
                             [("profile_email", "DELETE"), ("profile_email", "INSERT")])
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.count(), 1)

    def test_noop_checks_both_receipts_and_preserves_original_bytes_without_audit(self):
        before = self.path.read_bytes()
        view = self.view()
        result = self.save(view, new=" OLD@example.com ")
        self.assertFalse(result["saved"])
        self.assertTrue(result["noop"])
        self.assertIsNone(result["change_set_id"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 0)
        for field in ("config_sha256", "membership_sha256"):
            stale = {**view, field: "0" * 64}
            with self.subTest(field=field), self.assertRaises(profile_edits.StaleProfileEdit):
                self.save(stale, new="old@example.com")
        self.assertEqual(self.count(), 0)

    def test_independent_config_change_is_stale_and_never_overwritten(self):
        view = self.view()
        self.raw["unknown"]["changed"] = True
        self.write(self.raw)
        before = self.path.read_bytes()
        with self.assertRaises(profile_edits.StaleProfileEdit):
            self.save(view)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 0)

    def test_membership_change_is_stale_and_original_config_stays(self):
        view = self.view()
        before = self.path.read_bytes()
        with self.connect() as c:
            with db.change("test", "test", "Independent fixture email", conn=c) as (cur, _):
                cur.execute("insert into profile_email values ('user2','other@example.com')")
        with self.assertRaises(profile_edits.StaleProfileEdit):
            self.save(view)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 1)

    def test_unsynced_configuration_and_departure_are_refused(self):
        self.raw["profiles"][2]["name"] = "Changed"
        self.write(self.raw)
        with self.assertRaises(profile_edits.StaleProfileEdit):
            self.view()
        self.raw["profiles"][2]["name"] = "User2"
        self.write(self.raw)
        with self.connect("owner") as c:
            with db.change("test", "test", "Fixture departure", conn=c) as (cur, cid):
                cur.execute("insert into space_departure(space_id,operation,change_set_id) values('user2',%s,%s)",
                            ("00000000-0000-0000-0000-000000000001", cid))
        with self.assertRaises(profile_edits.InvalidProfileEdit):
            self.view()

    def test_process_crash_before_commit_recovers_exact_rollback(self):
        for stage in ("prepared", "sql_done"):
            with self.subTest(stage=stage):
                before = self.path.read_bytes()
                def crash(point):
                    if point == stage:
                        raise Crash
                with self.assertRaises(Crash):
                    self.save(fault=crash)
                self.assertTrue(profile_config.pending())
                with self.assertRaises(profile_edits.PendingProfileEdit):
                    profiles.read()
                result = profile_edits.recover(dbname=self.dbname)
                self.assertFalse(result["committed"])
                self.assertFalse(profile_config.pending())
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.count(), 0)

    def test_process_crash_after_commit_publishes_and_never_replays(self):
        view = self.view()
        def crash(point):
            if point == "committed":
                raise Crash
        with self.assertRaises(Crash):
            self.save(view, fault=crash)
        self.assertIn("old@example.com", profiles.parse(json.loads(self.path.read_bytes())["profiles"])[2]["emails"])
        self.assertTrue(profile_config.pending())
        with self.assertRaises(profile_edits.StaleProfileEdit):
            self.save(view)
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.emails(), [("alias@example.com",), ("new@example.com",)])
        self.assertEqual(profiles.read()[2]["emails"], ["new@example.com", "alias@example.com"])
        self.assertEqual(self.count(), 1)

    def test_crash_after_publication_finishes_without_a_second_audit(self):
        def crash(point):
            if point == "published":
                raise Crash
        with self.assertRaises(Crash):
            self.save(fault=crash)
        self.assertTrue(profile_config.pending())
        self.assertTrue(profile_edits.recover(dbname=self.dbname)["committed"])
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.count(), 1)

    def test_lost_commit_acknowledgement_is_reconciled_as_saved(self):
        def failure(point):
            if point == "committed":
                raise OSError("synthetic lost acknowledgement")
        result = self.save(fault=failure)
        self.assertTrue(result["saved"])
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.count(), 1)

    def test_independent_file_change_after_commit_is_kept_pending(self):
        def failure(point):
            if point == "committed":
                changed = copy.deepcopy(self.raw)
                changed["unknown"]["independent"] = True
                self.write(changed)
        with self.assertRaises(profile_edits.PendingProfileEdit):
            self.save(fault=failure)
        before = self.path.read_bytes()
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profile_edits.recover(dbname=self.dbname)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(profile_config.pending())
        self.assertEqual(self.count(), 1)

    def test_recovery_checks_exact_audit_rows_and_configuration_recipe(self):
        def crash(point):
            if point == "committed":
                raise Crash
        with self.assertRaises(Crash):
            self.save(fault=crash)
        journal = profile_config.load_journal()
        journal["change_set_id"] += 1
        profile_config.write_bytes(profile_config.control() / "pending.json", profile_config.json_bytes(journal))
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profile_edits.recover(dbname=self.dbname)
        self.assertTrue(profile_config.pending())

    def test_config_backed_sync_recovers_then_reads_the_published_email(self):
        def crash(point):
            if point == "committed":
                raise Crash
        with self.assertRaises(Crash):
            self.save(fault=crash)
        self.assertEqual(profiles_sync.sync(dbname=self.dbname), {"added": [], "changed": [], "removed": []})
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.emails(), [("alias@example.com",), ("new@example.com",)])
        self.assertEqual(self.count(), 1)

    def test_queued_sync_reads_after_email_writer_releases_its_claim(self):
        ready, finish = threading.Event(), threading.Event()
        result, errors = [], []
        original = profiles_sync._sync
        def observed(listed, **kwargs):
            result.append(listed[2]["emails"])
            return original(listed, **kwargs)
        def queued():
            ready.set()
            try:
                profiles_sync.sync(dbname=self.dbname)
            except Exception as exc:
                errors.append(exc)
            finish.set()
        with mock.patch.object(profiles_sync, "_sync", side_effect=observed):
            with profile_config.claim():
                thread = threading.Thread(target=queued)
                thread.start()
                self.assertTrue(ready.wait(1))
                self.save()
            self.assertTrue(finish.wait(3))
            thread.join(1)
        self.assertEqual(errors, [])
        self.assertEqual(result, [["new@example.com", "alias@example.com"]])
        self.assertEqual(self.count(), 1)

    def test_explicit_sync_cannot_revert_an_email_during_pending_publication(self):
        old_listed = profiles.read_checked(self.raw)
        observed = []
        def attempted(point):
            if point == "committed":
                with self.assertRaises(profile_edits.PendingProfileEdit):
                    profiles_sync.sync(listed=old_listed, dbname=self.dbname)
                observed.append(True)
        result = self.save(fault=attempted)
        self.assertTrue(result["saved"])
        self.assertEqual(observed, [True])
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.emails(), [("alias@example.com",), ("new@example.com",)])

    def test_concurrent_departure_before_publication_never_gets_a_saved_receipt(self):
        before = self.path.read_bytes()
        def departure(point):
            if point == "committed":
                with self.connect("owner") as c:
                    with db.change("test", "test", "Concurrent disposable departure", conn=c) as (cur, cid):
                        cur.execute("select pg_advisory_xact_lock(hashtext('inventory'))")
                        cur.execute("delete from profile where id='user2'")
                        cur.execute("delete from space where id='user2'")
                        cur.execute("insert into space_departure(space_id,operation,change_set_id) "
                                    "values('user2',%s,%s)", ("00000000-0000-0000-0000-000000000002", cid))
        with self.assertRaises(profile_edits.PendingProfileEdit):
            self.save(fault=departure)
        self.assertTrue(profile_config.pending())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 2)

    def test_final_publication_holds_membership_and_profile_writer_locks(self):
        import psycopg
        observed = []
        original = profile_config.write_bytes
        def publishing(path, content):
            if path == config.CONFIG_FILE:
                for operation in ("select pg_advisory_xact_lock(hashtext('inventory'))",
                                  "lock table profile in share row exclusive mode"):
                    with self.subTest(operation=operation), self.connect("app") as c:
                        with self.assertRaises(psycopg.errors.LockNotAvailable):
                            with c.transaction():
                                c.execute("set local lock_timeout='100ms'")
                                c.execute(operation)
                    observed.append(True)
            return original(path, content)
        with mock.patch.object(profile_config, "write_bytes", side_effect=publishing):
            result = self.save()
        self.assertEqual(observed, [True, True])
        self.assertTrue(result["saved"])
        self.assertFalse(profile_config.pending())

    def test_preview_rechecks_reader_after_locked_configuration_has_changed(self):
        self.raw["profiles"][0]["role"] = "member"
        self.write(self.raw)
        with mock.patch.object(profile_edits.db, "connect") as connect:
            with self.assertRaises(profile_edits.InvalidProfileEdit):
                self.view()
        connect.assert_not_called()

    def test_members_without_an_address_do_not_block_existing_address_replacements(self):
        self.raw["profiles"].append({"id": "user3", "name": "User3", "role": "member", "space": "user3", "emails": []})
        self.write(self.raw)
        db_support.seed_membership(self.dbname, self.raw["profiles"])
        self.assertEqual([member["id"] for member in self.view()["members"]], ["user2"])
        self.raw["profiles"][2]["emails"] = []
        self.write(self.raw)
        db_support.seed_membership(self.dbname, self.raw["profiles"])
        self.assertEqual(self.view()["members"], [])
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
