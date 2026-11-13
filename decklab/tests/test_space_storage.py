"""A space's storage setup (E8-S25 slice 2): the record's rules, both stores' read and write with a
revision and the audit trail, permissions' storage.edit, GET/PUT /api/storage, Activity's privacy,
the per-space table lists and the storage show|set commands. The in-memory store throughout; the
database's own tests are test_space_storage_pg.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_space_storage
"""
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, permissions, state, storage_setting
from decklab.lib.api import activity, guard, storage as storage_api
from decklab.lib.state import Conflict, Invalid, Unavailable, space_storage as rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests import test_api_permissions as permission_tests
from decklab.tests.test_activity import ADMIN, ALL, BY_ID, HOME, USER2S, _change, _row

ACTOR = state.Actor("matt", "Matt", "home")
BINDER = {"name": "Binder", "kind": "binder", "capacity": "360", "sections": ["Page 1-20", "Page 21-40"],
          "order": "set", "sleeved": True}
BOX = {"name": "Storage box", "kind": "box", "capacity": 2400, "sections": ["Row 1", "Row 2", "Row 3", "Row 4"],
       "order": "colour-type"}


class RuleTests(unittest.TestCase):
    def test_ids_are_made_once_from_names_and_default_may_name_a_container(self):
        record = rules.normalize({"default": "storage box", "containers": [BOX, BINDER, dict(BINDER, name="binder 2")]})
        self.assertEqual([c["id"] for c in record["containers"]], ["storage-box", "binder", "binder-2"])
        self.assertEqual(record["default"], "storage-box")
        self.assertEqual(record["containers"][1]["capacity"], 360)
        self.assertFalse(record["containers"][0]["sleeved"])
        renamed = rules.normalize({"default": "binder", "containers": [dict(BINDER, id="binder", name="Folder")]})
        self.assertEqual((renamed["containers"][0]["id"], renamed["default"]), ("binder", "binder"))
        self.assertEqual(rules.normalize(renamed), renamed)              # saved form is a fixed point

    def test_an_explicit_id_is_never_taken_by_a_made_one(self):
        record = rules.normalize([dict(BINDER, name="Binder"), dict(BOX, id="binder", name="Box")])
        self.assertEqual([c["id"] for c in record["containers"]], ["binder-2", "binder"])

    def test_bad_records_are_refused(self):
        for bad in ({"containers": [dict(BOX, kind="crate")]},
                    {"containers": [dict(BOX, order="type-colour")]},
                    {"containers": [dict(BOX, capacity=0)]},
                    {"containers": [dict(BOX, capacity=100_001)]},
                    {"containers": [dict(BOX, sections=["Row 1", "row 1"])]},
                    {"containers": [BOX, dict(BOX)]},
                    {"containers": [dict(BOX, name="Two\nlines")]},
                    {"containers": [dict(BOX, name="x" * 41)]},
                    {"containers": [dict(BOX, sleeved="yes")]},
                    {"containers": [dict(BOX, colour="red")]},
                    {"containers": [dict(BOX, id="Bad Id")]},
                    {"containers": [BOX], "default": "binder"},
                    {"containers": [BOX] * 21},
                    {"v": 2, "containers": []},
                    {"default": None, "containers": [], "extra": 1}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                rules.normalize(bad)

    def test_matching_a_location(self):
        record = rules.normalize({"default": "storage-box", "containers": [BOX, BINDER, {"name": "Shelf", "kind": "shelf"}]})
        self.assertEqual(rules.match(record, ""), "storage-box")         # none recorded: the default
        self.assertEqual(rules.match(record, "Row 2, B"), "storage-box")
        self.assertEqual(rules.match(record, "row 4"), "storage-box")
        self.assertEqual(rules.match(record, "Binder"), "binder")         # a container's name
        self.assertEqual(rules.match(record, "Page 21-40 top"), "binder")
        self.assertEqual(rules.match(record, "Shelf, left"), "shelf")
        for elsewhere in ("Row 5", "row3", "Row 10", "Bindery", "Under the bed"):
            self.assertIsNone(rules.match(record, elsewhere), elsewhere)
        longest = rules.normalize([{"name": "A", "sections": ["Row 1"]}, {"name": "B", "sections": ["Row 1 back"]}])
        self.assertEqual(rules.match(longest, "Row 1 back, 3"), "b")
        self.assertIsNone(rules.match(longest, ""))                        # no default
        self.assertEqual(rules.suggestions(record), ["Row 1", "Row 2", "Row 3", "Row 4", "Page 1-20", "Page 21-40", "Shelf"])

    def test_effective_home_default_member_none_and_saved_wins(self):
        home, source = rules.effective("home", None, 1800)
        self.assertEqual((source, home["default"], home["containers"][0]["capacity"]), ("default", "box", 1800))
        self.assertEqual(home["containers"][0]["sections"], ["Row 1", "Row 2", "Row 3", "Row 4"])
        self.assertEqual(rules.effective("home", None, None)[0]["containers"][0]["capacity"], 2400)
        self.assertEqual(rules.normalize(home), home)
        self.assertEqual(rules.effective("user2", None), (rules.EMPTY, "none"))
        empty = rules.normalize({"containers": []})
        self.assertEqual(rules.effective("home", empty, 1800), (empty, "saved"))   # the opt-out

    def test_home_rows_record_their_groups(self):
        self.assertEqual(rules.HOME_ROW_GROUPS, {"Row 1": "creatures", "Row 2": "spells", "Row 3": "lands",
                                                 "Row 4": "tokens"})


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()

    def test_saved_whole_with_a_revision_and_one_audited_change(self):
        self.assertEqual(self.store.space_storage("home"),
                         {"space": "home", "revision": 0, "storage": None, "ready": True})
        saved = self.store.space_storage_put("home", {"default": "binder", "containers": [BINDER]}, 0, ACTOR, "Set it")
        self.assertEqual((saved["revision"], saved["storage"]["default"]), (1, "binder"))
        self.assertEqual(self.store.space_storage_put("home", saved["storage"], 1, ACTOR, "Again"), saved)
        with self.assertRaises(Conflict):
            self.store.space_storage_put("home", {"containers": []}, 0, ACTOR, "Stale")
        emptied = self.store.space_storage_put("home", {"containers": []}, 1, ACTOR, "No storage")
        self.assertEqual((emptied["revision"], emptied["storage"]), (2, rules.EMPTY))
        rows = [row for change in self.store._changes for row in change["rows"]]
        self.assertEqual([(r["table"], r["op"], r["key"]) for r in rows],
                         [("space_storage", "INSERT", {"space_id": "home"}), ("space_storage", "UPDATE", {"space_id": "home"})])
        self.assertEqual(self.store.space_storage("user2")["revision"], 0)       # per space

    def test_before_the_migration_reads_nothing_saved_and_refuses_a_save(self):
        self.store.space_storage_ready = False
        self.assertEqual(self.store.space_storage("home")["ready"], False)
        with self.assertRaises(Unavailable) as caught:
            self.store.space_storage_put("home", {"containers": []}, 0, ACTOR, "Set it")
        self.assertIn("needs updating on the PC", str(caught.exception))
        with state.use(self.store):
            view = storage_setting.read("home")
        self.assertEqual((view["source"], view["ready"]), ("default", False))

    def test_a_batch_rolls_back_a_storage_save(self):
        with self.assertRaises(RuntimeError), self.store.batch(ACTOR, "Both"):
            self.store.space_storage_put("home", [BINDER], 0, ACTOR, "Set it")
            raise RuntimeError
        self.assertIsNone(self.store.space_storage("home")["storage"])

    def test_bad_space_ids_are_refused(self):
        for space in ("", "Home", "../x", None):
            with self.subTest(space=space), self.assertRaises(Invalid):
                self.store.space_storage(space)


class SettingTests(unittest.TestCase):
    def test_current_never_raises_and_seeds_home_from_config(self):
        with mock.patch.object(storage_setting.config, "load", return_value={"storage_box_capacity": 1500}):
            with mock.patch.object(state, "store", side_effect=RuntimeError("no store")):
                view = storage_setting.current("home")
            self.assertEqual((view["source"], view["storage"]["containers"][0]["capacity"]), ("default", 1500))
            store = MemoryStore()
            store.space_storage_put("home", [BINDER], 0, ACTOR, "Set it")
            with state.use(store):
                saved = storage_setting.current("home")
            self.assertEqual((saved["source"], saved["revision"], len(saved["storage"]["containers"])), ("saved", 1, 1))
        with mock.patch.object(storage_setting.config, "load", return_value={"storage_box_capacity": True}):
            self.assertIsNone(storage_setting.capacity_seed())


class PermissionTests(unittest.TestCase):
    def test_storage_edit_is_the_spaces_own_people_only(self):
        matt, user1, user2 = BY_ID["matt"], BY_ID["user1"], BY_ID["user2"]
        self.assertTrue(permissions.can(matt, "storage.edit", "home"))
        self.assertTrue(permissions.can(user1, "storage.edit", "home"))
        self.assertTrue(permissions.can(user2, "storage.edit", "user2"))
        self.assertFalse(permissions.can(matt, "storage.edit", "user2"))     # no admin override
        self.assertEqual(permissions.reason(user2, "storage.edit", "home"), "You can only change your own storage setup.")
        self.assertTrue(permissions.can(None, "storage.edit", "user2", script=True))
        self.assertFalse(permissions.can(None, "storage.edit", "home"))


class StorageApiTests(permission_tests.PermissionTestCase):
    def put(self, profile, **body):
        return storage_api.change(self.body(profile, **body))

    def test_reading_follows_the_spaces_inventory_and_a_public_collection(self):
        def readers(space):
            got = set()
            for who in ("matt", "user1", "user2"):
                with access.using({"profile": who, "email": "", "remote": True}):
                    try:
                        storage_api.view(space)
                        got.add(who)
                    except storage_api.ApiError as e:
                        self.assertEqual((e.status, e.message), (403, "That collection isn't public."))
            return got
        self.assertEqual(readers(None), {"matt", "user1"})
        self.assertEqual(readers("user2"), {"user2"})
        with mock.patch.object(guard, "public_spaces", side_effect=lambda thing: frozenset({"user2"} if thing == "collection" else ())):
            self.assertEqual(readers("user2"), {"matt", "user1", "user2"})        # Q7: read-only
            with access.using({"profile": "matt", "email": "", "remote": True}):
                self.assertFalse(storage_api.view("user2")["can_edit"])
                self.assertApiError(403, lambda: self.put("matt", space="user2", expect=0, storage={"containers": []}))

    def test_the_answer_before_and_after_a_save(self):
        with access.using(None):
            home = storage_api.view()
            self.assertEqual((home["source"], home["revision"], home["storage"]["default"]), ("default", 0, "box"))
            self.assertEqual(home["orders"], ["colour-type", "set", "name", "none"])
            member = storage_api.view("user2")
            self.assertEqual((member["source"], member["storage"]["containers"]), ("none", []))
        with access.using({"profile": "user2", "email": "", "remote": True}):
            saved = self.put("user2", space="user2", expect=0, storage={"default": "binder", "containers": [BINDER]})
            self.assertEqual((saved["source"], saved["revision"], saved["can_edit"]), ("saved", 1, True))
            error = self.assertApiError(409, lambda: self.put("user2", space="user2", expect=0, storage={"containers": []}))
            self.assertEqual(error.extra["latest"]["revision"], 1)
            self.assertApiError(400, lambda: self.put("user2", space="user2", expect=1, storage={"containers": [dict(BINDER, kind="tin")]}))
            self.assertApiError(400, lambda: self.put("user2", space="user2", expect=1, storage={"containers": []}, extra=1))
        change = self.box.state._changes[-1]
        self.assertEqual((change["actor"], change["message"]), ("user2", "Set User2's storage setup"))

    def test_writing_needs_storage_edit_on_the_space(self):
        self.check(lambda p: self.put(p, expect=0, storage={"containers": [BOX]}), {"matt", "user1", "local", "script"})
        self.check(lambda p: self.put(p, space="user2", expect=0, storage={"containers": []}), {"user2"})

    def test_a_save_before_the_migration_is_a_409_saying_so(self):
        self.box.state.space_storage_ready = False
        with access.using(None):
            error = self.assertApiError(409, lambda: self.put("matt", expect=0, storage={"containers": []}))
            self.assertEqual(error.extra.get("reason"), "migration")
            self.assertEqual(storage_api.view()["ready"], False)


class ActivityTests(unittest.TestCase):
    def change(self, space, actor="user2", source="web"):
        record = {"space_id": space, "revision": 1, "content": {"v": 1, "default": "binder",
                  "containers": [dict(BINDER, id="binder", name="Secret binder")]}}
        return _change([_row("space_storage", "INSERT", {"space_id": space}, after=record)],
                       actor, source, "Set the storage setup")

    def test_only_the_spaces_own_people_see_it_never_its_contents(self):
        change = self.change("user2")
        self.assertIsNone(activity.visible_change(change, ADMIN, BY_ID))     # not even an admin
        self.assertIsNone(activity.visible_change(change, HOME, BY_ID))
        own = activity.visible_change(change, USER2S, BY_ID)
        self.assertEqual(own["rows"], [{"table": "space_storage", "op": "INSERT", "summary": "Storage setup updated"}])
        self.assertEqual((own["kinds"], own["message"]), (["collection"], "Set the storage setup"))
        self.assertIn("updated the storage setup", own["headline"])
        self.assertNotIn("Secret binder", json.dumps(own))
        self.assertIsNotNone(activity.visible_change(change, ALL, BY_ID))
        home = self.change("home", actor="matt")
        self.assertIsNotNone(activity.visible_change(home, ADMIN, BY_ID))
        self.assertIsNotNone(activity.visible_change(home, HOME, BY_ID))
        self.assertIsNone(activity.visible_change(home, USER2S, BY_ID))


class TableListTests(unittest.TestCase):
    def test_the_table_joins_every_per_space_list(self):
        from decklab.db import export, export_scope, profile_admission, space_apply, space_remove
        from decklab.tests import db_support
        self.assertIn(("public.space_storage", ("space_id",)), export.TABLES)
        self.assertIn("public.space_storage", export.UNTIL_MIGRATED)
        self.assertIn("public.space_storage", export_scope.SPACE_ROWS)
        self.assertIn("public.space_storage", space_apply.LOCK_TABLES)
        self.assertIn("public.space_storage", space_apply.OPTIONAL_TABLES)
        order = space_apply.DELETE_ORDER
        self.assertLess(order.index("space_storage"), order.index("space"))
        self.assertEqual(space_remove._TABLE_KEYS["storage"], ("space_storage", ("space_id",)))
        self.assertIn("space_storage", db_support.STATE_TABLES)
        self.assertIn(28, db_support.UNDO_MIGRATION)
        self.assertIn('("space_storage", "space_id")', Path(profile_admission.__file__).read_text(encoding="utf-8"))
        sql = (Path(export.__file__).parent / "migrations" / "0028_space_storage.sql").read_text(encoding="utf-8")
        self.assertIn("audit.log_row('space_id')", sql)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.folder = Path(tempfile.mkdtemp(prefix="decklab-storage-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        for patcher in (mock.patch("decklab.db.storage_cli._store", return_value=self.store),
                        mock.patch("decklab.lib.spaces.exists", side_effect=lambda s: s in ("home", "user2")),
                        mock.patch("decklab.db.read_notices.Reporter.space")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        from decklab.db import storage_cli
        parser = argparse.ArgumentParser()
        storage_cli.add_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["storage", *argv])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = args.func(args)
        return code, out.getvalue(), err.getvalue()

    def test_show_set_dry_run_and_a_stale_expect(self):
        code, out, _ = self.run_cli("show")
        self.assertEqual(code, 0)
        self.assertIn("built-in default", out)
        self.assertIn("[box] Storage box: box, holds 2,400 cards, order colour-type, unsleeved", out)
        code, out, _ = self.run_cli("show", "--json")
        shown = json.loads(out)
        shown["storage"]["containers"].append(BINDER)
        file = self.folder / "storage.json"
        file.write_text(json.dumps(shown), encoding="utf-8")
        code, out, _ = self.run_cli("set", str(file), "--expect", "0", "-m", "Add the binder", "--dry-run")
        self.assertEqual((code, self.store.space_storage("home")["revision"]), (0, 0))
        self.assertIn("[binder] Binder: binder, holds 360 cards, order set, sleeved", out)
        code, out, _ = self.run_cli("set", str(file), "--expect", "0", "-m", "Add the binder")
        self.assertEqual((code, self.store.space_storage("home")["revision"]), (0, 1))
        self.assertEqual(self.store._changes[-1]["actor"], "claude")
        code, _, err = self.run_cli("set", str(file), "--expect", "0", "-m", "Again")
        self.assertEqual(code, 1)
        self.assertIn("revision 1", err)
        code, out, _ = self.run_cli("set", str(file), "--expect", "1", "-m", "Again")
        self.assertEqual((code, len(self.store._changes)), (0, 1))
        self.assertIn("Nothing to change", out)
        code, out, _ = self.run_cli("set", str(file), "--expect", "1", "-m", "Again", "--dry-run")
        self.assertEqual((code, len(self.store._changes)), (0, 1))
        self.assertIn("Nothing to change", out)               # the preview says what the save would
        self.assertNotIn("Would save", out)

    def test_refusals(self):
        file = self.folder / "bad.json"
        file.write_text(json.dumps({"containers": [dict(BOX, kind="tin")]}), encoding="utf-8")
        self.assertEqual(self.run_cli("set", str(file), "--expect", "0", "-m", "Bad")[0], 1)
        self.assertEqual(self.run_cli("show", "--space", "nobody")[0], 1)
        file.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.run_cli("set", str(file), "--expect", "0", "-m", "Bad")[0], 1)
        file.write_text(json.dumps({"containers": []}), encoding="utf-8")
        self.store.space_storage_ready = False
        code, _, err = self.run_cli("set", str(file), "--expect", "0", "-m", "Opt out")
        self.assertEqual(code, 1)
        self.assertIn("migration 0028", err)
        code, out, err = self.run_cli("set", str(file), "--expect", "0", "-m", "Opt out", "--dry-run")
        self.assertEqual(code, 1)                             # the preview refuses as the save would
        self.assertIn("migration 0028", err)
        self.assertNotIn("Would save", out)
        self.store.down = True
        self.assertEqual(self.run_cli("show")[0], 2)


if __name__ == "__main__":
    unittest.main()
