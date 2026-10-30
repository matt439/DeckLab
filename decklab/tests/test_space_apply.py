"""Audited removal/crash recovery in disposable DBs and temporary Forge roots only."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from decklab.db import conn as db, space_apply, space_export, space_journal
from decklab.lib.forge import lifecycle, lists
from decklab.lib.state import Actor
from decklab.lib.state import Invalid
from decklab.lib.state import rules
from decklab.tests import db_support
from decklab.tests.test_space_remove_preview import forge_result

ACTOR = Actor("claude", "Claude", None, "cli")
LOCAL_TEMP = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "Temp" if os.name == "nt" else None


class Crash(BaseException):
    pass


def deck_text(title, land):
    return f"# {title}\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n60 {land}\n```\n"


def snapshot(deck_id, land):
    sections = {"Deck": [{"qty": 60, "name": land, "set": None, "number": None, "finish": "nonfoil"}]}
    payload = {"id": deck_id, "version": "target", "sections": sections}
    return {**payload, "title": deck_id, "sha256": rules.record_sha(payload), "player": "Player", "mulligans": 0}


class RemovalApplyTests(db_support.DbTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-removal-apply-", dir=LOCAL_TEMP)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "results"
        self.root.mkdir()
        self.dest = Path(self.tmp.name) / "export"
        patcher = mock.patch.object(space_apply, "_runtime")
        patcher.start()
        self.addCleanup(patcher.stop)
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES + db_support.STATE_TABLES + ("visibility",))
        self.other_side = snapshot("other/casual/keep", "Island")
        with self.connect("owner") as c:
            with db.change("test", "test", "Removal fixture", conn=c) as (cur, _):
                for space in ("home", "sample", "other"):
                    cur.execute("insert into space (id) values (%s) on conflict do nothing", (space,))
                for space, position in (("sample", 1), ("other", 2)):
                    cur.execute("insert into profile (id, name, role, space_id, position) "
                                "values (%s, %s, 'member', %s, %s) on conflict do nothing",
                                (space, space, space, position))
                    cur.execute("insert into profile_email (profile_id, email) values (%s, %s) on conflict do nothing",
                                (space, f"{space}@example.invalid"))
                cur.execute("insert into inventory_revision (revision) values (1)")
                cur.execute("insert into decks_revision (revision) values (1)")
                for space in ("sample", "other"):
                    cur.execute("insert into collection_card (space_id, set_code, collector_number, finish, name, quantity) "
                                "values (%s, 'fdn', '227', 'nonfoil', 'Llanowar Elves', 2)", (space,))
                    cur.execute("insert into wishlist_entry (profile_id, position, name, notes) values (%s,0,'Opt',%s)",
                                (space, f"{space} wishlist"))
                    cur.execute("insert into profile_setting (profile_id,key,value) values (%s,'theme','dark')", (space,))
                cur.execute("insert into token_card (space_id,position,front,quantity) values ('sample',0,'Elf',1)")
                for deck_id, space, slug, land in (("sample/casual/own", "sample", "own", "Forest"),
                                                  ("sample/casual/second", "sample", "second", "Mountain"),
                                                  ("other/casual/keep", "other", "keep", "Island")):
                    text = deck_text(deck_id, land)
                    cur.execute("insert into deck (id,space_id,kind,slug,revision) values (%s,%s,'casual',%s,1)",
                                (deck_id, space, slug))
                    cur.execute("insert into deck_text (deck_id,text) values (%s,%s)", (deck_id, text))
                    cur.execute("insert into deck_line (deck_id,version,section,position,quantity,name) "
                                "values (%s,'target','Deck',0,60,%s)", (deck_id, land))
                    cur.execute("insert into deck_revision (deck_id,revision,at,actor,message,op,text) "
                                "values (%s,1,now(),'test','Fixture','A',%s)", (deck_id, text))
                cur.execute("insert into visibility (owner,thing,set_by,set_by_name) values ('sample','decks','sample','Member')")
                from psycopg.types.json import Jsonb
                for identifier, sides in (("a" * 32, [snapshot("sample/casual/own", "Forest"), self.other_side]),
                                          ("b" * 32, [snapshot("sample/casual/own", "Forest"),
                                                      snapshot("sample/casual/second", "Mountain")])):
                    content = {"date": "2026-10-18", "sides": sides, "space": "sample",
                               "result": "a", "notes": "Member private notes"}
                    cur.execute("insert into play_record (kind,id,revision,created_on,updated_on,updated_by,deck_ids,content) "
                                "values ('games',%s,1,'2026-10-18T00:00:00Z','2026-10-18T00:00:00Z',"
                                "'Member',%s,%s)", (identifier, [s["id"] for s in sides], Jsonb(content)))
        with self.connect("owner") as c:      # a draft kept for later (E2-S16): not audited, so no change set
            c.execute("insert into deck_draft (profile_id, deck_id, version, revision, saved_at, content) "
                      "values ('sample', 'sample/casual/own', 'target', 1, now(), '{\"v\": 1}')")
            c.execute("delete from new_deck_draft")       # migration 0019's: no deck to cascade from
            for space in ("sample", "other"):
                c.execute("insert into new_deck_draft (profile_id, space_id, source, revision, saved_at, content) "
                          "values (%s, %s, '', 1, now(), '{\"v\": 1}')", (space, space))
        own = forge_result("a" * 64, "sample/casual/own", "sample/casual/second")
        for side, land in zip(own["sides"], ("Forest", "Mountain")):
            side["card_sha"] = lists._list_text({"Main": [[60, land]]}, "constructed")[1]
        mixed = forge_result("b" * 64, "sample/casual/own", "other/casual/keep")
        self.own_file = self.root / ("a" * 64 + ".json")
        self.mixed_file = self.root / ("b" * 64 + ".json")
        self.own_file.write_text(json.dumps(own))
        self.mixed_file.write_text(json.dumps(mixed))
        self.note = self.root / "field" / ("c" * 64 + "-Constructed-sample.json")
        self.note.parent.mkdir()
        self.note.write_text(json.dumps({"runs": [{"deck": {"id": "sample/casual/own"},
                                                 "per_opponent": {"a" * 64: 5}}]}))
        self.originals = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.manifest = space_export.export_to("sample", self.dest, self.dbname, self.root)
        with self.connect() as c:
            self.changes_before = c.execute("select count(*) from audit.change_set").fetchone()[0]

    def apply(self, fault=None):
        return space_apply.apply("sample", self.dest, self.manifest["snapshot_sha256"], ACTOR,
                                 "Remove the member fixture", "Member requested", dbname=self.dbname,
                                 results_dir=self.root, fault=fault)

    def recover(self, operation, fault=None):
        return space_apply.recover(operation, dbname=self.dbname, results_dir=self.root, fault=fault)

    def pending(self):
        with lifecycle.maintenance(self.root) as claim:
            return space_journal.pending(claim)

    @staticmethod
    def crash_at(stage):
        def inject(label, index):
            if label == stage:
                raise Crash(stage)
        return inject

    def assert_restored(self):
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from space where id='sample'").fetchone()[0], 1)
            self.assertEqual(c.execute("select count(*) from new_deck_draft where space_id='sample'").fetchone()[0], 1)
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], self.changes_before)
        self.assertEqual(self.pending(), [])
        for relative, raw in self.originals.items():
            self.assertEqual((self.root / relative).read_bytes(), raw)

    def test_apply_is_one_change_keeps_other_space_and_mixed_side_and_invalidates_caches(self):
        result = self.apply()
        self.assertEqual((result["state"], result["files"]), ("committed", 2))
        self.assertFalse(self.own_file.exists())
        self.assertFalse(self.note.exists())
        self.assertEqual(self.mixed_file.read_bytes(), self.originals[self.mixed_file.relative_to(self.root)])
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], self.changes_before + 1)
            self.assertEqual(c.execute("select count(*) from collection_card where space_id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from collection_card where space_id='other'").fetchone()[0], 1)
            self.assertEqual(c.execute("select count(*) from profile where space_id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from space where id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from deck_revision where split_part(deck_id,'/',1)='sample'")
                             .fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from deck_draft").fetchone()[0], 0)
            self.assertEqual(c.execute("select space_id from new_deck_draft").fetchall(), [("other",)])
            revision, updated, by, ids, content = c.execute("select revision,updated_on,updated_by,deck_ids,content "
                                                           "from play_record where id=%s", ("a" * 32,)).fetchone()
            self.assertEqual(revision, 2)
            self.assertNotEqual(updated, "2026-10-18T00:00:00Z")
            self.assertEqual(by, "Claude")
            self.assertEqual(ids, ["other/casual/keep"])
            self.assertEqual(content["sides"][0], {"removed": True, "title": "a removed deck"})
            self.assertEqual(content["sides"][1], self.other_side)
            self.assertEqual((content["notes"], content["space"]), ("", ""))
            self.assertEqual(c.execute("select count(*) from play_record where id=%s", ("b" * 32,)).fetchone()[0], 0)
            self.assertEqual(c.execute("select revision from inventory_revision").fetchone()[0], 2)
            self.assertEqual(c.execute("select revision from decks_revision").fetchone()[0], 2)
        with self.assertRaises(lifecycle.LifecycleError):
            with lifecycle.writer(self.root, deck_ids=["sample/casual/own"]):
                self.fail("removed member writer was allowed")
        with lifecycle.writer(self.root, deck_ids=["other/casual/keep"]):
            pass
        self.assertEqual(self.recover(result["operation"])["state"], "committed")

    def test_crashes_before_or_between_moves_and_after_sql_restore_without_audited_change(self):
        for stage in ("prepared", "staged", "sql_done"):
            with self.subTest(stage=stage):
                with self.assertRaises(Crash):
                    self.apply(self.crash_at(stage))
                operation, = self.pending()
                self.assertEqual(self.recover(operation)["state"], "rolled_back")
                self.assert_restored()

    def test_crash_after_commit_and_during_cleanup_finishes_without_new_db_change(self):
        with self.assertRaises(Crash):
            self.apply(self.crash_at("committed"))
        operation, = self.pending()
        with self.assertRaises(lifecycle.LifecycleError):
            with lifecycle.writer(self.root, deck_ids=["other/casual/keep"]):
                self.fail("pending journal writer was allowed")
        with self.assertRaises(Crash):
            self.recover(operation, self.crash_at("cleaned"))
        self.assertEqual(self.recover(operation)["state"], "committed")
        self.assertEqual(self.pending(), [])
        self.assertFalse(self.own_file.exists())
        self.assertFalse(self.note.exists())
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], self.changes_before + 1)

    def test_uncertain_commit_acknowledgement_is_confirmed_by_immutable_audit_identity(self):
        def lose_ack(label, index):
            if label == "committed":
                raise RuntimeError("lost commit acknowledgement")
        result = self.apply(lose_ack)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["state"], "committed")
        self.assertEqual(self.pending(), [])

    def test_database_unavailable_during_recovery_keeps_pending_and_quarantine(self):
        with self.assertRaises(Crash):
            self.apply(self.crash_at("staged"))
        operation, = self.pending()
        with mock.patch.object(db, "connect", side_effect=db.DbUnavailable("fixture unavailable")):
            with self.assertRaises(db.DbUnavailable):
                self.recover(operation)
        self.assertEqual(self.pending(), [operation])
        self.assertEqual(self.recover(operation)["state"], "rolled_back")
        self.assert_restored()

    def test_contradictory_journal_outcome_refuses_without_guessing_or_deleting_files(self):
        with self.assertRaises(Crash):
            self.apply(self.crash_at("staged"))
        operation, = self.pending()
        with lifecycle.maintenance(self.root) as claim:
            path = claim.control_dir / "pending" / f"{operation}.json"
            value = json.loads(path.read_bytes())
            value["state"] = "committed"
            path.write_text(json.dumps(value))
            staged = [p for p in (claim.control_dir / "quarantine").rglob("*") if p.is_file()]
            before = {p: p.read_bytes() for p in staged}
        with self.assertRaisesRegex(ValueError, "contradicts"):
            self.recover(operation)
        self.assertEqual({p: p.read_bytes() for p in staged}, before)
        self.assertEqual(self.pending(), [operation])

    def test_recovery_refuses_to_overwrite_a_new_original(self):
        with self.assertRaises(Crash):
            self.apply(self.crash_at("staged"))
        operation, = self.pending()
        self.own_file.write_bytes(b"an unrelated replacement")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            self.recover(operation)
        self.assertEqual(self.own_file.read_bytes(), b"an unrelated replacement")
        self.assertEqual(self.pending(), [operation])

    def test_stale_export_refuses_before_file_moves_and_audit_commit(self):
        with self.connect() as c:
            with db.change("test", "test", "Changed fixture", conn=c) as (cur, _):
                cur.execute("update collection_card set quantity=3 where space_id='sample'")
        self.changes_before += 1
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            self.apply()
        self.assert_restored()

    def test_writer_or_runtime_refusal_does_not_start_database_or_journal_work(self):
        with mock.patch.object(space_apply, "_runtime", side_effect=ValueError("fixture old runtime")):
            with self.assertRaisesRegex(ValueError, "old runtime"):
                self.apply()
        # A claim from another thread/process conflicts; the same thread is
        # reentrant, so use the low-level independent OS claim from the tests.
        from threading import Thread
        from queue import Queue
        answer = Queue()
        with lifecycle.writer(self.root):
            def attempt():
                try:
                    self.apply()
                except Exception as exc:
                    answer.put(exc)
            worker = Thread(target=attempt)
            worker.start()
            worker.join(5)
            self.assertFalse(worker.is_alive())
        self.assertIsInstance(answer.get_nowait(), lifecycle.LifecycleError)
        self.assert_restored()

    @staticmethod
    def collection_op():
        from decklab.lib.inventory import Summary, model, paths, rules

        def run(before):
            row = model.CardRow.make(name="Opt", set="dom", collector_number="60",
                                     finish="nonfoil", quantity="1")
            sheet = model.Sheet(paths.collection("sample"), tuple(rules.FIELDS), (row,), exists=True)
            return before.replace(collections={**before.collections, "sample": sheet}), Summary("Fixture queued save")
        return SimpleNamespace(run=run)

    def test_departure_refuses_fresh_inventory_saves_and_config_resync(self):
        from decklab.db import profiles_sync
        from decklab.lib.inventory import pg
        self.apply()
        backend = pg.PgInventory(dbname=self.dbname)
        for actor in (ACTOR, Actor("sample", "Member", "home")):
            with self.subTest(actor=actor.id), self.assertRaisesRegex(Invalid, "no longer active"):
                backend.apply(self.collection_op(), actor, "Fixture stale configured member")
        listed = [{"id": "sample", "name": "Member", "role": "member", "space": "sample",
                   "plays_as": None, "emails": ["sample@example.invalid"]}]
        with self.assertRaisesRegex(ValueError, "departed member is still configured"):
            profiles_sync.sync(listed=listed, dbname=self.dbname)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from space where id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from collection_card where space_id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from space_departure where space_id='sample'").fetchone()[0], 1)
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], self.changes_before + 1)

    def test_inventory_save_already_queued_before_removal_cannot_restore_member_rows(self):
        from decklab.lib.inventory import pg
        from threading import Event, Thread
        from queue import Queue
        entered, resume = Event(), Event()
        answer = Queue()
        real_lock = pg._take_lock

        def queued_lock(cur):
            entered.set()
            if not resume.wait(8):
                raise RuntimeError("fixture queued writer did not resume")
            return real_lock(cur)

        def worker():
            try:
                with mock.patch.object(pg, "_take_lock", queued_lock):
                    pg.PgInventory(dbname=self.dbname).apply(self.collection_op(), ACTOR, "Queued before removal")
            except Exception as exc:
                answer.put(exc)

        thread = Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            self.apply()
        finally:
            resume.set()
            thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(answer.get_nowait(), Invalid)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from collection_card where space_id='sample'").fetchone()[0], 0)
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone()[0], self.changes_before + 1)

    def test_apply_and_recovery_force_fresh_post_lock_reads_under_repeatable_database_default(self):
        from psycopg import sql
        with self.connect("owner") as c:
            c.execute(sql.SQL("alter database {} set default_transaction_isolation = 'repeatable read'")
                      .format(sql.Identifier(self.dbname)))
        seen = []
        original = space_apply._locks

        def locks(c):
            seen.append(c.execute("show transaction_isolation").fetchone()[0])
            return original(c)

        try:
            with mock.patch.object(space_apply, "_locks", locks):
                with self.assertRaises(Crash):
                    self.apply(self.crash_at("staged"))
                operation, = self.pending()
                self.assertEqual(self.recover(operation)["state"], "rolled_back")
            self.assertEqual(seen, ["read committed", "read committed"])
            self.assert_restored()
        finally:
            with self.connect("owner") as c:
                c.execute(sql.SQL("alter database {} reset default_transaction_isolation")
                          .format(sql.Identifier(self.dbname)))

    def test_recovery_waits_for_old_commit_before_deciding_outcome_under_repeatable_default(self):
        from psycopg import IsolationLevel, sql
        from decklab.db import space_remove
        from queue import Queue
        from threading import Event, Thread
        with self.connect("owner") as c:
            c.execute(sql.SQL("alter database {} set default_transaction_isolation = 'repeatable read'")
                      .format(sql.Identifier(self.dbname)))
        worker = None
        try:
            with self.assertRaises(Crash):
                self.apply(self.crash_at("prepared"))
            operation, = self.pending()
            result, entered = Queue(), Queue()
            original = space_apply._locks

            def recovery_locks(c):
                entered.put(c.info.backend_pid)
                return original(c)

            def recover():
                try:
                    with mock.patch.object(space_apply, "_locks", recovery_locks):
                        result.put(self.recover(operation))
                except Exception as exc:
                    result.put(exc)

            with self.connect("owner") as c:
                c.isolation_level = IsolationLevel.READ_COMMITTED
                message = f"Remove the member fixture\nMember removal operation: {operation}"
                with db.change(ACTOR.id, "cli", message, reason="Member requested", conn=c) as (cur, change_id):
                    original(c)
                    _, _, data = space_export.snapshot(c, "sample", details=True)
                    rows, _ = space_remove.row_plan("sample", data)
                    with lifecycle.maintenance(self.root) as claim:
                        journal = space_journal.load(claim, operation)
                        journal["change_set_id"] = change_id
                        space_journal._write(claim.control_dir / "pending" / f"{operation}.json", journal)
                        space_journal.stage(claim, journal)
                    space_apply._mutate(cur, data, rows, ACTOR, operation, change_id)
                    worker = Thread(target=recover)
                    worker.start()
                    pid = entered.get(timeout=5)
                    blocked = False
                    pause = Event()
                    for _ in range(40):
                        wait = c.execute("select wait_event_type from pg_stat_activity where pid=%s", (pid,)).fetchone()
                        if wait and wait[0] == "Lock":
                            blocked = True
                            break
                        pause.wait(.02)
                    self.assertTrue(blocked, "recovery must wait for the older transaction's inventory claim")
                # Recovery's post-lock snapshot must include this committed audit
                # and marker even though the database default is REPEATABLE READ.
            worker.join(5)
            self.assertFalse(worker.is_alive())
            outcome = result.get_nowait()
            if isinstance(outcome, Exception):
                raise outcome
            self.assertEqual(outcome["state"], "committed")
            self.assertFalse(self.own_file.exists())
            self.assertEqual(self.pending(), [])
        finally:
            if worker is not None:
                worker.join(5)
            with self.connect("owner") as c:
                c.execute(sql.SQL("alter database {} reset default_transaction_isolation")
                          .format(sql.Identifier(self.dbname)))


if __name__ == "__main__":
    unittest.main()
