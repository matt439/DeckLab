"""State admission during member departure, in a disposable database only."""
import copy
import threading
import unittest
import uuid
from unittest import mock

from decklab.db import conn as db, space_apply
from decklab.lib import profiles
from decklab.lib.state import Actor, Invalid, pg, rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support
from decklab.tests.test_state_contract import game, plan

CLAUDE = Actor("claude", "Claude", source="cli")
GUEST = Actor("guest", "Guest", "tunnel")
USER2 = Actor("user2", "User2", "tunnel")
ENTRY = {"name": "Opt", "set": "", "number": ""}


class OrphanWishlistOptionTests(unittest.TestCase):
    def test_web_and_nonboolean_options_refuse_before_either_store_connects_or_writes(self):
        for store in (MemoryStore(), pg.PgStore(dbname="must-not-connect")):
            for option in (True, 1, "true", None):
                actor = GUEST if option is True else CLAUDE
                calls = [lambda: store.wishlist_add("guest", ENTRY, actor, "Save", allow_orphan=option),
                         lambda: store.wishlist_set("guest", "Opt", actor, "Save", allow_orphan=option),
                         lambda: store.wishlist_remove("guest", "Opt", actor, "Save", allow_orphan=option)]
                for index, save in enumerate(calls):
                    with self.subTest(store=type(store).__name__, option=option, method=index), \
                            mock.patch.object(db, "connect", side_effect=AssertionError("unexpected DB connection")), \
                            self.assertRaises(Invalid):
                        save()


class StateDepartureTests(db_support.DbTestCase):
    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())

    def retire(self, cur, change_id):
        """The apply transaction's identity/state slice; no Forge or live files."""
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", ("inventory",))
        cur.execute("insert into space_departure (space_id,operation,change_set_id) values (%s,%s,%s)",
                    ("guest", uuid.uuid4(), change_id))
        rows = cur.execute("select to_jsonb(r) from play_record r where content->>'space'='guest' "
                           "or exists (select 1 from unnest(r.deck_ids) d where split_part(d,'/',1)='guest')").fetchall()
        space_apply._write_records(cur, {"space": [{"id": "guest"}], "play_records": [row[0] for row in rows]}, CLAUDE)
        for table, column in (("wishlist_entry", "profile_id"), ("profile_setting", "profile_id"),
                              ("visibility", "owner"), ("profile_email", "profile_id"),
                              ("profile", "id"), ("space", "id")):
            cur.execute(f"delete from {table} where {column}=%s", ("guest",))

    def remove(self):
        with self.connect("owner") as c:
            with db.change("claude", "cli", "Disposable departure fixture", conn=c) as (cur, change_id):
                self.retire(cur, change_id)

    def guest_game(self, identifier="a" * 32):
        record = game(identifier)
        record["sides"][0]["id"] = "guest/casual/old"
        record["space"] = "guest"
        return record

    def test_fresh_writes_refuse_while_config_still_lists_the_member(self):
        self.remove()
        listed = [{"id": "guest", "name": "Guest", "space": "guest", "role": "member"}]
        calls = [lambda: self.store.settings_put("guest", {"theme": "dark"}, CLAUDE, "Save"),
                 lambda: self.store.wishlist_add("guest", {"name": "Opt", "set": "", "number": ""}, CLAUDE, "Save"),
                 lambda: self.store.visibility_set("guest", "decks", True, CLAUDE, "Save"),
                 lambda: self.store.play_put("games", self.guest_game(), None, USER2, "Save"),
                 lambda: self.store.settings_put("user2", {"theme": "dark"}, GUEST, "Save"),
                 lambda: self.store.simulation_mode_set("everyone", GUEST, "Save")]
        with mock.patch.object(profiles, "read", return_value=listed):
            self.assertEqual(profiles.read()[0]["id"], "guest")
            for index, save in enumerate(calls):
                with self.subTest(write=index), self.assertRaisesRegex(Invalid, "no longer active"):
                    save()
        with self.connect() as c:
            for table in ("wishlist_entry", "profile_setting", "visibility", "play_record", "simulation_mode"):
                self.assertEqual(c.execute(f"select count(*) from {table}").fetchone()[0], 0)

    def test_departure_marker_refuses_even_if_identity_rows_were_reintroduced(self):
        self.remove()
        with self.connect("owner") as c:
            with db.change("test", "test", "Reintroduced identity fixture", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('guest')")
                cur.execute("insert into profile (id,name,role,space_id,position) "
                            "values ('guest','Guest','member','guest',4)")
        with self.assertRaisesRegex(Invalid, "no longer active"):
            self.store.settings_put("guest", {"theme": "dark"}, GUEST, "Save")
        with self.assertRaisesRegex(Invalid, "no longer active"):
            self.store.play_put("games", self.guest_game(), None, USER2, "Save")

    def test_unknown_concrete_targets_refuse_without_any_state_or_audit_write(self):
        for save in (lambda: self.store.settings_put("unknown", {"theme": "dark"}, CLAUDE, "Save"),
                     lambda: self.store.wishlist_add("unknown", {"name": "Opt", "set": "", "number": ""}, CLAUDE, "Save"),
                     lambda: self.store.visibility_set("unknown", "games", True, CLAUDE, "Save")):
            with self.assertRaisesRegex(Invalid, "no longer active"):
                save()
        self.assertEqual(self.store.activity()["changes"], [])

    def test_cli_orphan_upkeep_survives_ordinary_profile_removal_and_actor_stays_strict(self):
        self.store.wishlist_add("guest", ENTRY, GUEST, "Wishlist fixture")
        with self.connect("owner") as c:
            with db.change("test", "test", "Ordinary profile-sync removal fixture", conn=c) as (cur, _):
                cur.execute("delete from profile_email where profile_id='guest'")
                cur.execute("delete from profile where id='guest'")
                cur.execute("delete from space where id='guest'")
        with self.assertRaisesRegex(Invalid, "no longer active"):
            self.store.wishlist_set("guest", "Opt", CLAUDE, "Save", notes="x")
        self.store.wishlist_set("guest", "Opt", CLAUDE, "Save", notes="retained", allow_orphan=True)
        self.store.wishlist_add("guest", {**ENTRY, "name": "Forest"}, CLAUDE, "Save", allow_orphan=True)
        missing_actor = Actor("guest", "Guest", source="cli")
        with self.assertRaisesRegex(Invalid, "no longer active"):
            self.store.wishlist_remove("guest", "Opt", missing_actor, "Save", allow_orphan=True)
        changed, rows = self.store.wishlist_remove("guest", "Opt", CLAUDE, "Save", allow_orphan=True)
        self.assertTrue(changed)
        self.assertEqual([row["name"] for row in rows], ["Forest"])

    def test_cli_orphan_flag_never_bypasses_departure(self):
        self.remove()
        calls = [lambda: self.store.wishlist_add("guest", ENTRY, CLAUDE, "Save", allow_orphan=True),
                 lambda: self.store.wishlist_set("guest", "Opt", CLAUDE, "Save", allow_orphan=True),
                 lambda: self.store.wishlist_remove("guest", "Opt", CLAUDE, "Save", allow_orphan=True)]
        for index, save in enumerate(calls):
            with self.subTest(method=index), self.assertRaisesRegex(Invalid, "no longer active"):
                save()

    def test_survivor_can_update_retained_game_and_plan_without_restoring_removed_ids(self):
        original = self.guest_game()
        self.store.play_put("games", original, None, GUEST, "Game fixture")
        sideboard = plan("b" * 32)
        sideboard["deck"]["id"] = "user2/casual/current"
        sideboard["opponent"]["id"] = "guest/casual/old"
        self.store.play_put("sideboards", sideboard, None, USER2, "Plan fixture")
        self.remove()
        for kind, identifier in (("games", original["id"]), ("sideboards", sideboard["id"])):
            with self.subTest(kind=kind):
                retained = self.store.play_get(kind, identifier)
                updated = copy.deepcopy(retained)
                updated["revision"] += 1
                updated["updated_by"] = "User2"
                if kind == "games":
                    updated["sides"][1]["mulligans"] = 2
                    removed = updated["sides"][0]
                else:
                    updated["notes"] = "My retained plan"
                    removed = updated["opponent"]
                saved = self.store.play_put(kind, updated, rules.record_sha(retained), USER2, "Own-side edit")
                self.assertEqual(removed, {"removed": True, "title": "a removed deck"})
                self.assertNotIn("guest/", rules.record_bytes(saved).decode())
        stale = dict(original, revision=4)
        with self.assertRaisesRegex(Invalid, "no longer active"):
            self.store.play_put("games", stale, rules.record_sha(retained), USER2, "Restore stale sides")

    def test_queued_save_rechecks_membership_after_removal_commits(self):
        started, finished = threading.Event(), threading.Event()
        outcome = []

        def save():
            started.set()
            try:
                self.store.settings_put("guest", {"theme": "dark"}, GUEST, "Queued save")
            except Exception as error:
                outcome.append(error)
            finally:
                finished.set()
        with self.connect("owner") as c:
            with db.change("claude", "cli", "Queued departure fixture", conn=c) as (cur, change_id):
                self.retire(cur, change_id)
                worker = threading.Thread(target=save, daemon=True)
                worker.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.wait(0.15))
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertIsInstance(outcome[0], Invalid)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from profile_setting where profile_id='guest'").fetchone()[0], 0)

    def test_pre_admitted_batch_finishes_before_removal_and_is_removed_with_it(self):
        admitted, release, removing, removed = (threading.Event() for _ in range(4))
        errors = []

        def save():
            try:
                with self.store.batch(GUEST, "Admitted save"):
                    self.store.settings_put("guest", {"theme": "dark"}, GUEST, "Save")
                    admitted.set()
                    if not release.wait(5):
                        raise RuntimeError("Test did not release the admitted save")
            except Exception as error:
                errors.append(error)

        def remove():
            try:
                removing.set()
                self.remove()
                removed.set()
            except Exception as error:
                errors.append(error)
        writer = threading.Thread(target=save, daemon=True)
        remover = threading.Thread(target=remove, daemon=True)
        writer.start()
        try:
            self.assertTrue(admitted.wait(3))
            remover.start()
            self.assertTrue(removing.wait(2))
            self.assertFalse(removed.wait(0.15))
        finally:
            release.set()
            writer.join(5)
            if remover.ident is not None:
                remover.join(5)
        self.assertFalse(writer.is_alive())
        self.assertFalse(remover.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(removed.is_set())
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from profile_setting where profile_id='guest'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
