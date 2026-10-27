"""New member admission/audit recovery uses only temporary config and disposable PostgreSQL."""
import base64
import copy
import json
import unittest
from unittest import mock

from decklab.db import conn as db, profile_edits, profiles_sync
from decklab.lib import config, profile_config, profiles
from decklab.lib.forge import common
from decklab.tests import db_support, test_profile_edits_pg as email_tests
from decklab.tests.test_profile_edits import ACTOR, TemporaryConfig


class ProfileCreationDatabaseTests(db_support.DbTestCase, TemporaryConfig):
    view = email_tests.ProfileEditDatabaseTests.view
    count = email_tests.ProfileEditDatabaseTests.count

    def setUp(self):
        email_tests.ProfileEditDatabaseTests.setUp(self)
        with self.connect("owner") as c:
            c.execute("delete from ops.visit_day")
        self.results = self.path.parent / "forge" / "results"
        patcher = mock.patch.object(common, "DATA_DIR", self.results.parent)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create(self, view=None, **extra):
        view = self.view() if view is None else view
        args = {"member_id": "user3", "name": "User3", "email": "user3@example.com",
                "config_sha256": view["config_sha256"], "membership_sha256": view["membership_sha256"],
                "actor": ACTOR, "dbname": self.dbname, "results_dir": self.results, **extra}
        return profile_edits.create(**args)

    def test_creation_appends_one_private_member_and_exact_three_audit_rows(self):
        before = copy.deepcopy(self.raw)
        result = self.create(name="  User3  ", email=" User3@Example.COM ")
        self.assertTrue(result["saved"])
        self.assertFalse(result["noop"])
        self.assertTrue(result["access_policy_required"])
        self.assertEqual(result["member"], {"id": "user3", "name": "User3", "emails": ["user3@example.com"]})
        after = json.loads(self.path.read_bytes())
        self.assertEqual(after["profiles"][:-1], before["profiles"])
        self.assertEqual(after["unknown"], before["unknown"])
        self.assertEqual(after["profiles"][-1], {"id": "user3", "name": "User3", "role": "member",
                                                 "space": "user3", "emails": ["user3@example.com"]})
        self.assertEqual(self.view()["config_sha256"], result["config_sha256"])
        self.assertEqual(self.view()["membership_sha256"], result["membership_sha256"])
        with self.connect("ro") as c:
            self.assertEqual(c.execute("select actor,source,via from audit.change_set").fetchall(), [("matt", "web", "home")])
            self.assertEqual(c.execute("select table_name,op from audit.row_change order by id").fetchall(),
                             [("space", "INSERT"), ("profile", "INSERT"), ("profile_email", "INSERT")])
            self.assertEqual(c.execute("select role,space_id,plays_as,position from profile where id='user3'").fetchone(),
                             ("member", "user3", None, 3))
            for table in ("collection_card", "token_card", "deck", "wishlist_entry", "visibility", "profile_setting"):
                self.assertEqual(c.execute("select count(*) from " + table).fetchone()[0], 0)
        self.assertFalse(profile_config.pending())

    def test_invalid_inputs_and_duplicate_alias_never_write(self):
        before = self.path.read_bytes()
        cases = [{"member_id": "home"}, {"member_id": "claude"}, {"member_id": "product"},
                 {"member_id": "con"}, {"member_id": "bad/id"}, {"member_id": "user2"},
                 {"name": ""}, {"name": " "}, {"name": "x" * 121}, {"name": "User\n3"},
                 {"email": "ALIAS@example.com"}, {"email": "bad"}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(profile_edits.InvalidProfileEdit):
                self.create(**case)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(profile_config.pending())

    def test_stale_receipts_and_creation_retry_never_create_another_change(self):
        view = self.view()
        for key in ("config_sha256", "membership_sha256"):
            with self.subTest(key=key), self.assertRaises(profile_edits.StaleProfileEdit):
                self.create({**view, key: "0" * 64})
        self.create(view)
        with self.assertRaises(profile_edits.StaleProfileEdit):
            self.create(view)
        with self.assertRaises(profile_edits.InvalidProfileEdit):
            self.create()
        self.assertEqual(self.count(), 1)

    def test_crashes_before_commit_restore_original_config_without_audit(self):
        for stage in ("prepared", "sql_done"):
            with self.subTest(stage=stage):
                before = self.path.read_bytes()
                def crash(point):
                    if point == stage:
                        raise email_tests.Crash
                with self.assertRaises(email_tests.Crash):
                    self.create(fault=crash)
                self.assertTrue(profile_config.pending())
                with self.assertRaises(profile_edits.PendingProfileEdit):
                    profiles.read()
                outcome = profile_edits.recover(dbname=self.dbname, results_dir=self.results)
                self.assertFalse(outcome["committed"])
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(profile_config.pending())
                self.assertEqual(self.count(), 0)

    def test_crashes_after_commit_and_publication_recover_one_creation(self):
        for stage, member in (("committed", "user3"), ("published", "user4")):
            with self.subTest(stage=stage):
                def crash(point):
                    if point == stage:
                        raise email_tests.Crash
                with self.assertRaises(email_tests.Crash):
                    self.create(member_id=member, name=member.capitalize(), email=member + "@example.com", fault=crash)
                self.assertTrue(profile_config.pending())
                outcome = profile_edits.recover(dbname=self.dbname, results_dir=self.results)
                self.assertTrue(outcome["committed"])
                self.assertFalse(profile_config.pending())
                self.assertIsNotNone(profiles.find(member))
        self.assertEqual(self.count(), 2)

    def test_lost_commit_acknowledgement_reconciles_as_saved_once(self):
        def fail(point):
            if point == "committed":
                raise OSError("synthetic lost acknowledgement")
        result = self.create(fault=fail)
        self.assertTrue(result["saved"])
        self.assertFalse(profile_config.pending())
        self.assertEqual(self.count(), 1)

    def test_detected_independent_config_change_is_preserved_with_pending_outcome(self):
        def independent(point):
            if point == "committed":
                changed = copy.deepcopy(self.raw)
                changed["unknown"]["independent"] = True
                self.write(changed)
        with self.assertRaises(profile_edits.PendingProfileEdit):
            self.create(fault=independent)
        before = self.path.read_bytes()
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profile_edits.recover(dbname=self.dbname, results_dir=self.results)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.count(), 1)
        self.assertTrue(profile_config.pending())

    def test_session_claim_fences_orphan_writers_after_commit_before_publication(self):
        import psycopg
        observed = []
        def contender(point):
            if point == "committed":
                with self.connect("app") as c:
                    with self.assertRaises(psycopg.errors.LockNotAvailable):
                        with c.transaction():
                            c.execute("set local lock_timeout='100ms'")
                            c.execute("select pg_advisory_xact_lock_shared(hashtext('inventory'))")
                observed.append(True)
        self.assertTrue(self.create(fault=contender)["saved"])
        self.assertEqual(observed, [True])

    def test_crashed_creation_cannot_inherit_new_orphan_data_during_recovery(self):
        def crash(point):
            if point == "committed":
                raise email_tests.Crash
        with self.assertRaises(email_tests.Crash):
            self.create(fault=crash)
        before = self.path.read_bytes()
        with self.connect() as c:
            with db.change("test", "test", "Independent disposable orphan", conn=c) as (cur, _):
                cur.execute("insert into wishlist_entry(profile_id,position,name) values('user3',0,'Opt')")
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profile_edits.recover(dbname=self.dbname, results_dir=self.results)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(profile_config.pending())

    def test_config_backed_sync_recovers_creation_and_keeps_new_identity(self):
        def crash(point):
            if point == "committed":
                raise email_tests.Crash
        with self.assertRaises(email_tests.Crash):
            self.create(fault=crash)
        self.assertEqual(profiles_sync.sync(dbname=self.dbname), {"added": [], "changed": [], "removed": []})
        self.assertIsNotNone(profiles.find("user3"))
        self.assertEqual(self.count(), 1)

    def test_recovery_rejects_tampered_append_or_wrong_audit_without_publishing(self):
        def crash(point):
            if point == "committed":
                raise email_tests.Crash
        with self.assertRaises(email_tests.Crash):
            self.create(fault=crash)
        before = self.path.read_bytes()
        journal = profile_config.load_journal()
        after = json.loads(base64.b64decode(journal["after"]))
        after["profiles"][-1]["role"] = "admin"
        content = profile_config.json_bytes(after)
        journal["after"] = base64.b64encode(content).decode()
        journal["after_sha256"] = profile_config.digest(content)
        profile_config.write_bytes(profile_config.control() / "pending.json", profile_config.json_bytes(journal))
        with self.assertRaises(profile_edits.PendingProfileEdit):
            profile_edits.recover(dbname=self.dbname, results_dir=self.results)
        self.assertEqual(self.path.read_bytes(), before)

    def test_all_orphan_and_prior_identity_shapes_refuse_without_touching_them(self):
        shapes = {
            "collection": "insert into collection_card(space_id,set_code,collector_number,finish,name,quantity) "
                          "values('user3','fdn','1','nonfoil','Opt',1)",
            "tokens": "insert into token_card(space_id,position,front,quantity) values('user3',0,'Treasure',1)",
            "import": "insert into collection_import(space_id,file_name,size,sha256) values('user3','a.csv',0,repeat('a',64))",
            "deck": "insert into deck(id,space_id,kind,slug,revision) values('user3/casual/old','user3','casual','old',1)",
            "history": "insert into deck_revision(deck_id,revision,at,actor,message,op,text) "
                       "values('user3/casual/old',1,now(),'test','Fixture','A','# Private fixture')",
            "alias": "insert into deck_alias(alias_id,deck_id) values('user3/casual/old','user3/casual/new')",
            "wishlist": "insert into wishlist_entry(profile_id,position,name) values('user3',0,'Opt')",
            "settings": "insert into profile_setting values('user3','theme','dark')",
            "game_recorder": "insert into play_record values('games',repeat('a',32),1,'2026-10-26T12:00:00Z',"
                             "'2026-10-26T12:00:00Z','test',array['user2/casual/old'],'{\"space\":\"user3\"}')",
            "mixed_game": "insert into play_record values('games',repeat('a',32),1,'2026-10-26T12:00:00Z',"
                          "'2026-10-26T12:00:00Z','test',array['user3/casual/old'],'{\"space\":\"user2\"}')",
            "public_switch": "insert into visibility(owner,thing,set_by_name) values('user3','collection','Test')",
            "public_kit": "insert into visibility(owner,thing,set_by_name) values('user3','accessories','Test')",
            "accessory": "insert into accessory(id,owner) values('fixture-kit','user3')",
            "visits": "insert into ops.visit_day(profile_id,day,channel,first_at,last_at) "
                      "values('user3','2026-10-26','remote',now(),now())",
            "visited_deck": "insert into ops.visit_day(profile_id,day,channel,first_at,last_at) "
                            "values('user2','2026-10-26','remote',now(),now()); "
                            "insert into ops.visit_page(profile_id,day,channel,route,deck_id,opens,last_at) "
                            "values('user2','2026-10-26','remote','deck','user3/casual/old',1,now())",
            "setter": "insert into simulation_mode(id,mode,set_by,set_by_name) values(true,'admins','user3','Prior setter')",
            "history_actor": "insert into deck_revision(deck_id,revision,at,actor,message,op,text) "
                             "values('user2/casual/prior',1,now(),'user3','Fixture','A','# Prior actor')",
            "audit_private_only": "insert into wishlist_entry(profile_id,position,name) values('user3',0,'Opt'); "
                                  "delete from wishlist_entry where profile_id='user3'",
            "audit_member_only": "insert into space values('user3'); "
                                 "insert into profile values('user3','Prior member','member','user3',null,3); "
                                 "delete from profile where id='user3'; delete from space where id='user3'",
            "audit_setter_only": "insert into simulation_mode(id,mode,set_by,set_by_name) "
                                 "values(true,'admins','user3','Prior setter'); delete from simulation_mode",
            "audit_game_only": "insert into play_record values('games',repeat('a',32),1,'2026-10-26T12:00:00Z',"
                               "'2026-10-26T12:00:00Z','test',array['user3/casual/old'],'{\"space\":\"user2\"}'); "
                               "delete from play_record",
            "old_actor": "insert into audit.change_set(actor,source,message) values('user3','test','Prior identity')",
            "departed": "insert into space_departure(space_id,operation,change_set_id) "
                        "values('user3','00000000-0000-0000-0000-000000000003',current_setting('decklab.change_set')::bigint)",
        }
        for label, sql in shapes.items():
            with self.subTest(shape=label):
                db_support.reset(self.dbname, db_support.INVENTORY_TABLES + db_support.STATE_TABLES
                                 + ("profile_email", "profile", "space"))
                db_support.seed_membership(self.dbname, self.raw["profiles"])
                before = self.path.read_bytes()
                with self.connect("owner") as c:
                    c.execute("delete from ops.visit_day")
                    with db.change("test", "test", "Disposable admission fixture", conn=c) as (cur, _):
                        cur.execute(sql)
                count = self.count()
                with self.assertRaises(profile_edits.InvalidProfileEdit):
                    self.create()
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.count(), count)
                self.assertFalse(profile_config.pending())


if __name__ == "__main__":
    unittest.main()
