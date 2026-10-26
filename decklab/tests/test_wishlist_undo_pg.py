"""Wishlist Undo lock, audit and rollback proofs in guarded disposable PostgreSQL."""
import copy
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, space_members
from decklab.lib import access, cards, config, inventory, state
from decklab.lib.api import wishlist_undo as api
from decklab.lib.api.common import ApiError
from decklab.lib.state import pg, pg_wishlist_undo as adapter, wishlist_undo as undo
from decklab.tests import db_support, test_collection_edit as roles

MATT = state.Actor("matt", "Matt", via="tunnel")


class WishlistUndoPgTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None
        folder = tempfile.TemporaryDirectory(prefix="decklab-wishlist-undo-pg-", dir=root)
        cls.addClassCleanup(folder.cleanup)
        path = Path(folder.name) / "config.json"
        path.write_text(json.dumps(roles.ROLES), encoding="utf-8")
        for patcher in (mock.patch.object(config, "CONFIG_FILE", path), mock.patch.dict(os.environ, {config.EXTRA_ENV: ""})):
            patcher.start()
            cls.addClassCleanup(patcher.stop)
        super().setUpClass()
        if not cls.dbname.startswith(db_support.PREFIX):
            raise AssertionError("Wishlist Undo requires a disposable database")

    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname, roles.ROLES["profiles"])
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.addCleanup(state.use(self.store))

    def sql(self, text, args=()):
        with self.connect("ro") as connection:
            return connection.execute(text, args).fetchall()

    def persisted(self):
        tables = (*db_support.STATE_TABLES, "space_departure", "inventory_revision", "decks_revision", "collection_card", "token_card", "deck",
                  "audit.change_set", "audit.row_change")
        with self.connect("ro") as connection:
            return {table: connection.execute("select row_to_json(t)::text from " + table + " t order by 1").fetchall() for table in tables}

    def seed(self, pid="matt"):
        actor = state.Actor(pid, "Matt" if pid == "matt" else pid.title(), via="tunnel")
        entry = {"name": "Opt", "set": "", "number": "", "notes": "  Former café note\r\nsecond line\t  ",
                 "source": "  magic/reports/example.md  "}
        self.store.wishlist_add(pid, entry, actor, "Fixture old wishlist entry")
        self.store.wishlist_add(pid, {"name": "Forest", "set": "", "number": "", "notes": "Other", "source": ""}, actor, "Fixture other entry")
        self.store.wishlist_set(pid, "Opt", actor, "Fixture metadata change", notes="Changed note", source="magic/new.md")
        source = self.sql("select change_set_id from audit.row_change where table_name='wishlist_entry' order by id desc limit 1")[0][0]
        return source, entry, actor

    def apply(self, source, pid="matt", *, plan=None, actor=None):
        plan = self.store.wishlist_undo_review(source, pid) if plan is None else plan
        return self.store.wishlist_undo_apply(source, pid, plan["expect"], actor or MATT, "Undo fixture wishlist metadata")

    def test_preview_has_no_audit_or_other_data_writes_and_actual_api_inverse_is_one_exact_update(self):
        source, entry, _ = self.seed()
        before = self.persisted()
        history = self.sql("select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,))
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            shown = api.wishlist_undo_view(id=str(source))
            self.assertEqual(self.persisted(), before)
            saved = api.apply_wishlist_undo(json.dumps({"profile": "matt", "id": source, "expect": shown["expect"]}).encode())
        self.assertEqual(saved["restored"], entry)
        self.assertEqual((saved["kind"], saved["action"], saved["profile"]), ("wishlist", "wishlist_update", "matt"))
        self.assertNotIn("space", saved)
        with self.connect("ro") as connection:
            actual = adapter.entries(connection.cursor(), "matt")
        self.assertEqual(saved["sha256"], undo.list_sha(actual))
        written = self.persisted()
        self.assertEqual(len(written["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(written["audit.row_change"]), len(before["audit.row_change"]) + 1)
        self.assertEqual(self.sql("select id,table_name,op,row_key,before,after from audit.row_change where change_set_id=%s", (source,)), history)
        self.assertEqual(saved["revision"], str(self.sql("select max(id) from audit.row_change where table_name='wishlist_entry'")[0][0]))
        self.assertEqual(self.sql("select actor,source,via from audit.change_set order by id desc limit 1"), [("matt", "web", "tunnel")])
        for table in before.keys() - {"wishlist_entry", "audit.change_set", "audit.row_change"}:
            self.assertEqual(written[table], before[table], table)

    def test_both_read_and_apply_are_owner_profile_only_before_private_source_details(self):
        source, _, _ = self.seed()
        before = self.persisted()
        for pid in ("user1", "user2"):
            with self.subTest(pid=pid), self.assertRaises(undo.UndoMissing):
                self.store.wishlist_undo_review(source, pid)
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            with self.assertRaises(ApiError) as caught:
                api.apply_wishlist_undo(json.dumps({"profile": "user1", "id": source, "expect": "bad"}).encode())
            self.assertEqual(caught.exception.status, 404)
            self.assertEqual(caught.exception.message, api.NO_CHANGE)
        self.assertEqual(self.persisted(), before)

    def test_mixed_sources_stay_unavailable_and_valid_printing_preferences_can_be_reviewed(self):
        source, _, _ = self.seed()
        with self.store.batch(MATT, "Fixture mixed state source"):
            self.store.wishlist_set("matt", "Opt", MATT, "Fixture", notes="Mixed note")
            self.store.settings_put("matt", {"theme": "dark"}, MATT, "Fixture")
        mixed = self.sql("select max(id) from audit.change_set")[0][0]
        before = self.persisted()
        with self.assertRaises(undo.UndoMissing):
            self.store.wishlist_undo_review(mixed, "matt")
        self.assertEqual(self.persisted(), before)
        self.store.wishlist_set("matt", "Opt", MATT, "Fixture printing update", set="fdn", number="227")
        printing = self.sql("select max(id) from audit.change_set")[0][0]
        before = self.persisted()
        plan = self.store.wishlist_undo_review(printing, "matt")
        self.assertEqual([field["field"] for field in plan["fields"]], ["set", "number"])
        self.assertEqual(self.persisted(), before)

    def printing_source(self, original, current, *, mixed=False):
        self.seed()
        self.store.wishlist_set("matt", "Opt", MATT, "Fixture historical preference", set=original[0], number=original[1],
                                **({"notes": "  Historical café\r\nsecond\t  ", "source": "  magic/old.md  "} if mixed else {}))
        restored = copy.deepcopy(self.store.wishlist("matt")[0])
        self.store.wishlist_set("matt", "Opt", MATT, "Fixture current preference", set=current[0], number=current[1],
                                **({"notes": "Current note", "source": "magic/current.md"} if mixed else {}))
        source = self.sql("select max(change_set_id) from audit.row_change where table_name='wishlist_entry'")[0][0]
        return source, restored

    def test_historical_nullable_and_paired_printing_preferences_restore_without_index(self):
        for old, current in ((("", ""), ("zzz", "9x")), (("zzz", "9x"), ("", "")), (("zzz", "9x"), ("yyy", "8y"))):
            source, restored = self.printing_source(old, current)
            before = self.persisted()
            with self.subTest(old=old, current=current), \
                    mock.patch.object(cards, "resolve", side_effect=AssertionError("No card index")), \
                    mock.patch.object(cards, "printing", side_effect=AssertionError("No printing index")), \
                    mock.patch.object(cards, "printing_card", side_effect=AssertionError("No printing index")), \
                    mock.patch.object(inventory, "current", side_effect=AssertionError("No inventory")):
                plan = self.store.wishlist_undo_review(source, "matt")
                self.assertEqual(self.persisted(), before)
                result = self.apply(source, plan=plan)
            self.assertEqual(result["restored"], restored)
            self.assertEqual(self.store.wishlist("matt")[0], restored)
            self.assertEqual(self.sql("select set_code,collector_number from wishlist_entry where profile_id='matt' and name='Opt'"),
                             [(old[0] or None, old[1] or None)])
            self.assertEqual(len(self.persisted()["audit.row_change"]), len(before["audit.row_change"]) + 1)

    def test_combined_printing_and_text_api_inverse_has_exact_raw_list_and_one_audit(self):
        source, restored = self.printing_source(("zzz", "9x"), ("yyy", "8y"), mixed=True)
        before = self.persisted()
        original = self.sql("select id,op,before,after from audit.row_change where change_set_id=%s", (source,))
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}):
            shown = api.wishlist_undo_view(id=str(source))
            self.assertEqual([field["field"] for field in shown["fields"]], ["set", "number", "notes", "source"])
            result = api.apply_wishlist_undo(json.dumps({"profile": "matt", "id": source, "expect": shown["expect"]}).encode())
        self.assertEqual(result["restored"], restored)
        self.assertEqual(self.sql("select id,op,before,after from audit.row_change where change_set_id=%s", (source,)), original)
        after = self.persisted()
        self.assertEqual(len(after["audit.change_set"]), len(before["audit.change_set"]) + 1)
        self.assertEqual(len(after["audit.row_change"]), len(before["audit.row_change"]) + 1)
        for table in before.keys() - {"wishlist_entry", "audit.change_set", "audit.row_change"}:
            self.assertEqual(after[table], before[table], table)

    def test_printing_receipt_validation_failure_rolls_back_both_printing_fields_and_audit(self):
        source, _ = self.printing_source(("zzz", "9x"), ("yyy", "8y"))
        plan, before = self.store.wishlist_undo_review(source, "matt"), self.persisted()
        with mock.patch.object(undo, "receipt", side_effect=undo.UndoConflict()), self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)

    def test_later_printing_edit_away_and_back_refuses_original_source_without_any_write(self):
        source, _ = self.printing_source(("zzz", "9x"), ("yyy", "8y"))
        plan = self.store.wishlist_undo_review(source, "matt")
        self.store.wishlist_set("matt", "Opt", MATT, "Fixture later printing", set="tmp", number="1")
        self.store.wishlist_set("matt", "Opt", MATT, "Fixture printing ABA", set="yyy", number="8y")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)

    def test_own_list_changes_and_target_aba_refuse_but_other_profile_changes_do_not(self):
        source, _, _ = self.seed()
        plan = self.store.wishlist_undo_review(source, "matt")
        other_source, _, other = self.seed("user1")
        self.assertEqual(self.store.wishlist_undo_review(source, "matt")["expect"], plan["expect"])
        self.store.wishlist_set("user1", "Opt", other, "Other private update", notes="Only other list")
        self.assertEqual(self.store.wishlist_undo_review(source, "matt")["expect"], plan["expect"])
        self.store.wishlist_set("matt", "Forest", MATT, "Own list touch", notes="Changed")
        self.store.wishlist_set("matt", "Forest", MATT, "Own list ABA", notes="Other")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)
        self.store.wishlist_set("matt", "Opt", MATT, "Target touch", notes="Away")
        self.store.wishlist_set("matt", "Opt", MATT, "Target ABA", notes="Changed note")
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.store.wishlist_undo_review(source, "matt")
        self.assertEqual(self.persisted(), before)

    def test_latest_owner_version_uses_row_change_id_when_change_set_started_before_other_writes(self):
        source, _, _ = self.seed()
        with self.connect("app") as connection:
            with db.change("matt", "web", "Slow fixture transaction", conn=connection) as (cur, slow_change):
                space_members.admit(cur, profile_ids=("matt",), actor=MATT)
                self.store.wishlist_set("matt", "Forest", MATT, "Later fixture one", notes="Temporary")
                self.store.wishlist_set("matt", "Forest", MATT, "Later fixture two", notes="Other")
                plan = self.store.wishlist_undo_review(source, "matt")
                latest_change = self.sql("select max(id) from audit.change_set")[0][0]
                self.assertLess(slow_change, latest_change)
                self.store._lock(cur, "wishlist:matt")
                for note in ("Temporary again", "Other"):
                    entries, positions = self.store._entries(cur, "matt")
                    self.store._wishlist_set_at(cur, "matt", entries, positions, "Forest", notes=note)
        before = self.persisted()
        fresh = self.store.wishlist_undo_review(source, "matt")
        self.assertEqual(fresh["raw_after"], plan["raw_after"])
        self.assertEqual(self.sql("select max(id) from audit.change_set")[0][0], latest_change)
        self.assertGreater(fresh["latest_owner"], plan["latest_owner"])
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)

    def test_receipt_failure_after_update_rolls_back_entry_and_entire_audit(self):
        source, _, _ = self.seed()
        plan, before = self.store.wishlist_undo_review(source, "matt"), self.persisted()
        with mock.patch.object(undo, "receipt", side_effect=undo.UndoConflict()), self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)

    def test_one_connection_cursor_setter_no_nested_public_call_and_repeat_refuses(self):
        source, _, _ = self.seed()
        plan = self.store.wishlist_undo_review(source, "matt")
        with mock.patch.object(self.store, "_connect", wraps=self.store._connect) as connections, \
                mock.patch.object(self.store, "wishlist_set", side_effect=AssertionError("Nested public setter")), \
                mock.patch.object(self.store, "_wishlist_set_at", wraps=self.store._wishlist_set_at) as setter:
            self.apply(source, plan=plan)
        self.assertEqual(connections.call_count, 1)
        self.assertEqual(setter.call_count, 1)
        before = self.persisted()
        with self.assertRaises(undo.UndoConflict):
            self.apply(source, plan=plan)
        self.assertEqual(self.persisted(), before)

    def test_enclosing_batch_wrong_actor_and_departed_members_refuse_without_new_audit(self):
        source, _, _ = self.seed()
        plan, before = self.store.wishlist_undo_review(source, "matt"), self.persisted()
        with self.store.batch(MATT, "Empty surrounding fixture batch"):
            with self.assertRaises(undo.UndoUnsupported):
                self.store.wishlist_undo_review(source, "matt")
            with self.assertRaises(undo.UndoUnsupported):
                self.apply(source, plan=plan)
        for actor in (state.Actor("user1", "User1"), state.Actor("matt", "Matt", source="cli")):
            with self.subTest(actor=actor), self.assertRaises(undo.UndoMissing):
                self.apply(source, plan=plan, actor=actor)
        self.assertEqual(self.persisted(), before)
        source, _, actor = self.seed("user2")
        with self.connect("owner") as connection:
            with db.change("test", "test", "Fixture departure marker", conn=connection) as (cur, change):
                cur.execute("insert into space_departure(space_id,operation,change_set_id) values(%s,%s,%s)", ("user2", uuid.uuid4(), change))
        before = self.persisted()
        with self.assertRaises(undo.UndoMissing):
            self.store.wishlist_undo_review(source, "user2")
        with self.assertRaises(undo.UndoMissing):
            self.store.wishlist_undo_apply(source, "user2", "0" * 64, actor, "Stale member fixture")
        self.assertEqual(self.persisted(), before)

    def test_orphan_admission_fails_before_audit_source_is_read(self):
        with mock.patch.object(adapter, "source", side_effect=AssertionError("Private audit read")), self.assertRaises(undo.UndoMissing):
            self.store.wishlist_undo_review(1, "missing")

    def test_lost_reply_after_commit_is_not_retried_or_reported_saved(self):
        source, entry, _ = self.seed()
        plan, before = self.store.wishlist_undo_review(source, "matt"), self.persisted()
        original = self.store._call
        def lost(work):
            original(work)
            raise state.Unavailable("Synthetic reply loss after commit")
        with access.using({"profile": "matt", "email": "matt@example.com", "remote": True}), \
                mock.patch.object(self.store, "_call", side_effect=lost) as calls, self.assertRaises(ApiError) as caught:
            api.apply_wishlist_undo(json.dumps({"profile": "matt", "id": source, "expect": plan["expect"]}).encode())
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(self.store.wishlist("matt")[0], entry)
        self.assertEqual(len(self.persisted()["audit.change_set"]), len(before["audit.change_set"]) + 1)

    def _locked_writer_case(self, during):
        source, _, _ = self.seed()
        plan = self.store.wishlist_undo_review(source, "matt")
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        errors, results = [], []
        original = getattr(undo, during)
        def paused(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Fixture lock release timed out")
            return original(*args, **kwargs)
        def operation():
            try:
                results.append(self.apply(source, plan=plan) if during == "receipt" else self.store.wishlist_undo_review(source, "matt"))
            except Exception as error:
                errors.append(error)
        def writer():
            try:
                self.store.wishlist_set("matt", "Forest", MATT, "Queued normal wishlist writer", notes="Queued")
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
        with mock.patch.object(undo, during, side_effect=paused):
            first = threading.Thread(target=operation)
            second = threading.Thread(target=writer)
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                with self.connect("app") as connection, connection.transaction():
                    self.assertIs(connection.execute("select pg_try_advisory_xact_lock(hashtext('inventory'))").fetchone()[0], False,
                                  "Membership admission was released before the evidence/receipt")
                second.start()
                self.assertFalse(finished.wait(.15), "Normal writer passed the held wishlist lock")
            finally:
                release.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertTrue(finished.is_set())

    def test_preview_holds_admission_and_wishlist_lock_through_all_read_evidence(self):
        self._locked_writer_case("review")

    def test_apply_keeps_normal_wishlist_writer_queued_through_receipt_validation(self):
        self._locked_writer_case("receipt")
