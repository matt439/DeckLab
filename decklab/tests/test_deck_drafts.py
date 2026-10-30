"""Editor drafts kept for later (E2-S16): GET/POST /api/deck/draft as two simulated devices of
one profile, its privacy edges and a database without migration 0018, and pg_deck_drafts.py's
statements over a fake connection. The stores' revision rules are StoreContract's
(test_state_contract.py), on MemoryStore and, given a throwaway database, on PostgreSQL.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_deck_drafts
"""
import unittest
from unittest import mock

from decklab.db import migrate
from decklab.lib import access, feature_routes, state
from decklab.lib.api import deck_drafts, guard
from decklab.lib.state import Conflict, deck_drafts as rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api_permissions import PermissionTestCase

DECK = "casual/gruul-test"              # Played by either: Matt's to edit
WIFE_DECK = "commander/elf-commander"   # Played by wife: User1's to edit too
MEMBER_DECK = "user2/casual/r-elves"


def draft(n=1, **more):
    """An editor draft object (editor-drafts.js saveDraft's shape) with n Forests."""
    return {"v": 1, "saved": 1, "sha256": None, "starting": False,
            "base": {"lists": {"Deck": []}, "fields": {}, "prose": None},
            "lists": {"Deck": [{"name": "Forest", "qty": n}]}, "fields": {"archetype": f"draft {n}"}, **more}


def tunnel(profile):
    return access.using({"profile": profile, "email": "", "remote": True})


class StoreTests(unittest.TestCase):

    def test_without_the_migration_every_call_says_so(self):
        store = MemoryStore(drafts_missing=True)
        for call in (lambda: store.deck_draft("matt", DECK, "target"),
                     lambda: store.deck_draft_put("matt", DECK, "target", draft(), 0)):
            with self.assertRaises(rules.MissingSchema) as caught:
                call()
            self.assertTrue(rules.missing_schema(caught.exception))
            self.assertIsInstance(caught.exception, state.Unavailable)


class MigrationTests(unittest.TestCase):

    def test_the_table_is_private_scratch_with_a_tombstone_and_cascades(self):
        sql = (migrate.MIGRATIONS / "0018_deck_drafts.sql").read_text(encoding="utf-8")
        self.assertIn("primary key (profile_id, deck_id, version)", sql)
        self.assertIn("references profile (id) on delete cascade", sql)
        self.assertIn("references deck (id) on update cascade on delete cascade", sql)
        self.assertIn("content jsonb null", sql)
        self.assertNotIn("audit_row", sql)          # no audit rows: a draft's lists never reach Activity

    def test_it_follows_field_policy(self):
        files = migrate.available()
        self.assertEqual([(f["version"], f["name"]) for f in files[16:18]], [(17, "field_policy"), (18, "deck_drafts")])

    def test_drafts_are_not_exported(self):
        from decklab.db import export
        self.assertNotIn("public.deck_draft", {name for name, _ in export.TABLES})
        self.assertNotIn("public.new_deck_draft", {name for name, _ in export.TABLES})

    def test_a_new_decks_drafts_have_their_own_table_after_0018(self):
        files = migrate.available()
        self.assertEqual((files[18]["version"], files[18]["name"]), (19, "new_deck_drafts"))
        sql = (migrate.MIGRATIONS / "0019_new_deck_drafts.sql").read_text(encoding="utf-8")
        self.assertIn("primary key (profile_id, space_id, source)", sql)
        self.assertIn("references profile (id) on delete cascade", sql)
        self.assertIn("references space (id) on delete cascade", sql)
        self.assertNotIn("references deck", sql)        # a new deck has no deck row yet
        self.assertNotIn("audit_row", sql)


class DraftApiTests(PermissionTestCase):

    def post(self, profile, deck_id=DECK, *, expect=0, content=None, version="target", **more):
        return deck_drafts.save_draft(self.body(profile, id=deck_id, version=version, expect=expect,
                                                draft=content, **more))

    def test_two_devices_of_one_profile_see_save_and_discard_one_draft(self):
        ipad, pc = (lambda: tunnel("matt")), (lambda: access.viewing("matt"))
        with ipad():
            first = deck_drafts.draft_view(DECK)
            self.assertEqual(first, {"available": True, "id": DECK, "version": "target", "deck_revision": None,
                                     "revision": 0, "draft": None})
            saved = self.post("matt", content=draft(1), device="iPad")
        self.assertEqual(saved["revision"], 1)
        with pc():
            shown = deck_drafts.draft_view(DECK, "target")
            self.assertEqual((shown["revision"], shown["draft"]["device"], shown["draft"]["content"]), (1, "iPad", draft(1)))
            self.assertEqual(self.post("matt", expect=1, content=draft(2), device="PC")["revision"], 2)
        with ipad():
            # The iPad's revision is old: its save is refused, nothing changes, and a read shows the PC's.
            self.assertApiError(409, lambda: self.post("matt", expect=1, content=draft(9)))
            self.assertApiError(409, lambda: self.post("matt", expect=1))
            newer = deck_drafts.draft_view(DECK)
            self.assertEqual((newer["revision"], newer["draft"]["device"], newer["draft"]["content"]), (2, "PC", draft(2)))
            self.assertEqual(self.post("matt", expect=2), {"available": True, "id": DECK, "version": "target",
                                                           "deck_revision": None, "revision": 3, "draft": None})
        with pc():
            self.assertEqual(deck_drafts.draft_view(DECK)["draft"], None)
            self.assertApiError(409, lambda: self.post("matt", expect=2, content=draft(2)))
        self.assertEqual(self.box.state.changes(), [])

    def test_a_draft_says_which_saved_revision_it_started_from(self):
        sha = self.sha(DECK)
        now = mock.patch.object(deck_drafts, "_deck_now", return_value=(sha, 7))
        with tunnel("matt"), now:
            # The page's own deck_revision is never kept: only the server's, for the deck text it opened.
            saved = self.post("matt", content=draft(1, sha256=sha, deck_revision=99))
            self.assertEqual(saved["deck_revision"], 7)
            self.assertEqual(saved["draft"]["content"]["deck_revision"], 7)
            self.assertEqual(saved["draft"]["started"], {"revision": 7, "current": True})
            older = self.post("matt", expect=1, content=draft(2, sha256="0" * 64, deck_revision=99))
            self.assertNotIn("deck_revision", older["draft"]["content"])
            self.assertEqual(older["draft"]["started"], {"revision": None, "current": False})
        with tunnel("matt"), now, mock.patch.object(deck_drafts, "_deck_now", return_value=(sha, 8)):
            self.post("matt", expect=2, content=draft(3, sha256=sha))
        with tunnel("matt"), mock.patch.object(deck_drafts, "_deck_now", return_value=("1" * 64, 9)):
            shown = deck_drafts.draft_view(DECK)
            self.assertEqual((shown["deck_revision"], shown["draft"]["started"]), (9, {"revision": 8, "current": False}))

    def test_a_draft_is_only_its_own_profiles(self):
        with tunnel("matt"):
            self.post("matt", WIFE_DECK, content=draft(1))
        for remote in (False, True):
            with self.subTest(remote=remote), (tunnel("user1") if remote else access.viewing("user1")):
                # User1 sees the deck and may edit it, but Matt's draft of it isn't hers.
                self.assertEqual(deck_drafts.draft_view(WIFE_DECK)["draft"], None)
                self.assertApiError(403, lambda: self.post("matt", WIFE_DECK, expect=1))
                self.assertApiError(403, lambda: self.post("matt", WIFE_DECK, expect=1, content=draft(5)))
        with tunnel("user1"):
            self.assertEqual(self.post("user1", WIFE_DECK, content=draft(7))["revision"], 1)
        with tunnel("matt"):
            self.assertEqual(deck_drafts.draft_view(WIFE_DECK)["draft"]["content"], draft(1))
        with access.viewing("user1"):
            self.assertEqual(deck_drafts.draft_view(WIFE_DECK)["draft"]["content"], draft(7))

    def test_naming_nobody_has_no_drafts(self):
        # The home page before "Who are you?" and a script naming nobody: no profile, no draft.
        with access.using(None):
            self.assertApiError(403, lambda: deck_drafts.draft_view(DECK))
            self.assertApiError(403, lambda: self.post("matt", content=draft()))
        self.assertEqual(self.box.state.deck_draft("matt", DECK, "target"), {"revision": 0, "draft": None})

    def test_deck_privacy_applies_before_any_draft_is_read(self):
        with tunnel("user2"):
            self.assertEqual(self.post("user2", MEMBER_DECK, content=draft(1))["revision"], 1)
        refused = mock.patch.object(self.box.state, "deck_draft", side_effect=AssertionError("private read"))
        unwritten = mock.patch.object(self.box.state, "deck_draft_put", side_effect=AssertionError("private write"))
        with refused, unwritten:
            for who, deck_id in (("matt", MEMBER_DECK), ("user1", MEMBER_DECK), ("user2", DECK), ("user2", WIFE_DECK)):
                for remote in (False, True) if who != "user2" else (True,):
                    with self.subTest(who=who, deck=deck_id, remote=remote), \
                            (tunnel(who) if remote else access.viewing(who)):
                        # A deck of another space answers as a missing one; no admin override.
                        self.assertApiError(404, lambda: deck_drafts.draft_view(deck_id))
                        self.assertApiError(404, lambda: self.post(who, deck_id, content=draft()))
                        self.assertApiError(404, lambda: self.post(who, deck_id))
            with tunnel("matt"):
                self.assertApiError(404, lambda: deck_drafts.draft_view("casual/no-such-deck"))

    def test_keeping_a_draft_needs_the_right_to_save_the_deck(self):
        with tunnel("user1"):
            # Gruul Test is played by either, which only Matt edits: User1 may read and discard, not keep.
            self.assertEqual(deck_drafts.draft_view(DECK)["revision"], 0)
            self.assertApiError(403, lambda: self.post("user1", content=draft()))
            self.assertEqual(self.post("user1")["revision"], 0)
        self.assertEqual(self.box.state.deck_draft("user1", DECK, "target"), {"revision": 0, "draft": None})

    def test_no_one_writes_as_someone_else(self):
        with access.viewing("user1"):
            self.assertApiError(403, lambda: self.post("matt", WIFE_DECK, content=draft()))
        with tunnel("user1"):
            self.assertApiError(403, lambda: self.post("matt", WIFE_DECK, content=draft()))
        self.assertEqual(self.box.state.deck_draft("matt", WIFE_DECK, "target")["revision"], 0)

    def test_bad_requests_write_nothing(self):
        with tunnel("matt"):
            for body in (b"[]", self.body("matt", id=DECK, version="target", expect=0),
                         self.body("matt", id=DECK, version="both", expect=0, draft=draft()),
                         self.body("matt", id=DECK, version="target", expect="0", draft=draft()),
                         self.body("matt", id=DECK, version="target", expect=0, draft={"v": 1}),
                         self.body("matt", id=DECK, version="target", expect=0, draft=draft(), extra=1)):
                with self.subTest(body=body[:80]):
                    self.assertApiError(400, deck_drafts.save_draft, body)
            self.assertApiError(413, deck_drafts.save_draft, b" " * (deck_drafts.MAX_BODY + 1))
            self.assertApiError(400, lambda: deck_drafts.draft_view(DECK, "both"))
            self.assertApiError(400, lambda: deck_drafts.draft_view(None))
        self.assertEqual(self.box.state.deck_draft("matt", DECK, "target"), {"revision": 0, "draft": None})

    def test_without_the_migration_the_editor_carries_on_as_before(self):
        self.box.state.deck_drafts_ready = False
        with tunnel("matt"):
            self.assertEqual(deck_drafts.draft_view(DECK), {"available": False, "id": DECK, "version": "target"})
            refused = self.assertApiError(503, lambda: self.post("matt", content=draft()))
            self.assertEqual(refused.message, rules.MIGRATE)
        self.box.state.down = True
        with tunnel("matt"):
            self.assertApiError(503, lambda: deck_drafts.draft_view(DECK))

    def test_the_routes_are_registered(self):
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"id": DECK, "version": "owned"}
        handler._deck_id.return_value = DECK
        with mock.patch.object(deck_drafts, "draft_view", return_value={"fixture": True}) as view:
            self.assertTrue(feature_routes.dispatch(handler, ["deck", "draft"], {}))
        view.assert_called_once_with(deck_id=DECK, version="owned")
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = b"{}"
        with mock.patch.object(deck_drafts, "save_draft", return_value={"fixture": True}) as save:
            self.assertTrue(feature_routes.dispatch(handler, ["deck", "draft"], {}))
        save.assert_called_once_with(b"{}")
        handler._write_body.assert_called_once_with(deck_drafts.MAX_BODY)


class NewDeckDraftApiTests(PermissionTestCase):
    """A never-saved new deck's draft (/api/deck/new-draft): per profile, space and source."""

    def post(self, profile, space="home", *, expect=0, content=None, **more):
        return deck_drafts.save_new_draft(self.body(profile, space=space, expect=expect, draft=content, **more))

    def test_two_devices_of_one_profile_keep_resume_and_discard_a_new_decks_draft(self):
        with tunnel("matt"):
            self.assertEqual(deck_drafts.new_draft_view("home"), {"available": True, "space": "home", "source": None,
                                                                  "revision": 0, "draft": None})
            saved = self.post("matt", content=draft(1), device="iPad")
            self.assertEqual((saved["revision"], saved["source"]), (1, None))
        with access.viewing("matt"):
            shown = deck_drafts.new_draft_view()            # no space given: the profile's own
            self.assertEqual((shown["space"], shown["draft"]["device"], shown["draft"]["content"]), ("home", "iPad", draft(1)))
            self.assertApiError(409, lambda: self.post("matt", expect=0, content=draft(2)))
            self.assertEqual(self.post("matt", expect=1)["draft"], None)
        with tunnel("matt"):
            self.assertEqual(deck_drafts.new_draft_view("home")["revision"], 2)
            # A copy of a deck is kept apart from one started from nothing, and from that deck's own drafts.
            copied = self.post("matt", content=draft(3), source=DECK)
            self.assertEqual((copied["source"], copied["revision"]), (DECK, 1))
            self.assertEqual(deck_drafts.new_draft_view("home", DECK)["draft"]["content"], draft(3))
            self.assertEqual(deck_drafts.draft_view(DECK)["draft"], None)
        self.assertEqual(self.box.state.changes(), [])

    def test_a_new_decks_draft_is_only_its_own_profiles(self):
        with tunnel("matt"):
            self.post("matt", content=draft(1))
        with tunnel("user1"):
            # User1 may add home decks too, but Matt's draft isn't hers, and she can't write it.
            self.assertEqual(deck_drafts.new_draft_view("home")["draft"], None)
            self.assertApiError(403, lambda: self.post("matt", expect=1))
            self.assertEqual(self.post("user1", content=draft(7))["revision"], 1)
        with access.viewing("user1"):
            self.assertApiError(403, lambda: self.post("matt", expect=1, content=draft(2)))
        with access.using(None):
            self.assertApiError(403, lambda: deck_drafts.new_draft_view("home"))
            self.assertApiError(403, lambda: self.post("matt", expect=1))
        self.assertEqual(self.box.state.new_deck_draft("matt", "home", "")["draft"]["content"], draft(1))
        self.assertEqual(self.box.state.new_deck_draft("user1", "home", "")["draft"]["content"], draft(7))

    def test_spaces_the_viewer_cant_add_decks_to_are_refused_before_any_draft_is_read(self):
        with tunnel("user2"):
            self.assertEqual(self.post("user2", "user2", content=draft(1))["revision"], 1)
            self.assertEqual(deck_drafts.new_draft_view()["space"], "user2")      # their own by default
        refused = mock.patch.object(self.box.state, "new_deck_draft", side_effect=AssertionError("private read"))
        unwritten = mock.patch.object(self.box.state, "new_deck_draft_put", side_effect=AssertionError("private write"))
        with refused, unwritten:
            # An admin has no override in a member's space; a member none at home or in another's; a
            # space that doesn't exist answers as a hidden one.
            for who, space in (("matt", "user2"), ("user1", "user2"), ("user2", "home"), ("user2", "user3"),
                               ("user2", "nobody"), ("matt", "nobody")):
                for remote in (False, True) if who != "user2" else (True,):
                    with self.subTest(who=who, space=space, remote=remote), \
                            (tunnel(who) if remote else access.viewing(who)):
                        for call in (lambda: deck_drafts.new_draft_view(space),
                                     lambda: self.post(who, space, content=draft()), lambda: self.post(who, space)):
                            self.assertEqual(self.assertApiError(403, call).message, guard.HIDDEN_SPACE)
            with tunnel("user2"):
                # A deck to copy that the viewer can't see answers as a missing one.
                self.assertApiError(404, lambda: deck_drafts.new_draft_view("user2", DECK))
                self.assertApiError(404, lambda: self.post("user2", "user2", content=draft(), source=DECK))
        with tunnel("user2"):
            self.assertEqual(deck_drafts.new_draft_view("user2", MEMBER_DECK)["revision"], 0)

    def test_bad_requests_write_nothing(self):
        with tunnel("matt"):
            for body in (self.body("matt", space="home", expect=0), self.body("matt", expect=0, draft=draft()),
                         self.body("matt", space="home", expect=-1, draft=draft()),
                         self.body("matt", space="home", expect=0, draft={"v": 1}),
                         self.body("matt", space="home", expect=0, draft=draft(), source=7),
                         self.body("matt", space="home", expect=0, draft=draft(), source="x"),
                         self.body("matt", space="home", expect=0, draft=draft(), id=DECK)):
                with self.subTest(body=body[:80]):
                    self.assertApiError(400, deck_drafts.save_new_draft, body)
            self.assertApiError(413, deck_drafts.save_new_draft, b" " * (deck_drafts.MAX_BODY + 1))
        self.assertEqual(self.box.state.new_deck_draft("matt", "home", ""), {"revision": 0, "draft": None})

    def test_without_the_migration_the_new_deck_editor_carries_on_as_before(self):
        self.box.state.deck_drafts_ready = False
        with tunnel("matt"):
            self.assertEqual(deck_drafts.new_draft_view("home"), {"available": False, "space": "home", "source": None})
            self.assertEqual(self.assertApiError(503, lambda: self.post("matt", content=draft())).message, rules.MIGRATE)

    def test_the_routes_are_registered(self):
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"space": "home", "source": DECK}
        with mock.patch.object(deck_drafts, "new_draft_view", return_value={"fixture": True}) as view:
            self.assertTrue(feature_routes.dispatch(handler, ["deck", "new-draft"], {}))
        view.assert_called_once_with(space="home", source=DECK)
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = b"{}"
        with mock.patch.object(deck_drafts, "save_new_draft", return_value={"fixture": True}) as save:
            self.assertTrue(feature_routes.dispatch(handler, ["deck", "new-draft"], {}))
        save.assert_called_once_with(b"{}")
        handler._write_body.assert_called_once_with(deck_drafts.MAX_BODY)


class _Cursor:
    """Just enough of a psycopg cursor for pg_deck_drafts' statements, over one dict table."""

    def __init__(self, conn):
        self.conn = conn
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.conn.calls.append(sql)
        if sql.startswith(("select to_regclass('public.deck_draft')", "select to_regclass('public.new_deck_draft')")):
            self.result = (self.conn.ready,)
        elif sql.startswith("select pg_advisory_xact_lock"):
            self.conn.locks.append(params[0])
        elif sql.startswith(("select revision, saved_at, device, content from deck_draft where profile_id = %s and "
                             "deck_id = %s and version = %s",
                             "select revision, saved_at, device, content from new_deck_draft where profile_id = %s "
                             "and space_id = %s and source = %s")):
            row = self.conn.rows.get(tuple(params))
            self.result = None if row is None else tuple(row)
        elif sql.startswith(("insert into deck_draft (profile_id, deck_id, version,",
                             "insert into new_deck_draft (profile_id, space_id, source,")):
            *key, revision, device, content, expected = params
            row = self.conn.rows.get(tuple(key))
            if row is None or row[0] == expected:
                from datetime import datetime, timezone
                self.conn.rows[tuple(key)] = [revision, datetime(2026, 10, 29, 1, 2, 3, tzinfo=timezone.utc), device,
                                              None if content is None else content.obj]
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.result


class _Conn:
    def __init__(self, ready=True):
        self.ready, self.rows, self.calls, self.locks, self.transactions = ready, {}, [], [], 0

    def cursor(self):
        return _Cursor(self)

    def transaction(self):
        from contextlib import nullcontext
        self.transactions += 1
        return nullcontext()


class _Store:
    def __init__(self, conn):
        self.conn = conn

    def _call(self, work):
        return work(self.conn)

    def _batch(self):
        return None

    @staticmethod
    def _lock(cur, key):
        cur.execute("select pg_advisory_xact_lock(hashtext(%s))", (key,))


class PgDraftTests(unittest.TestCase):

    def setUp(self):
        # Hosted CI has no psycopg: put_ only needs its Jsonb wrapper, faked as test_pg_field_policy does.
        import sys
        import types

        class Jsonb:
            def __init__(self, obj):
                self.obj = obj
        modules = {name: types.ModuleType(name) for name in ("psycopg", "psycopg.types", "psycopg.types.json")}
        modules["psycopg.types.json"].Jsonb = Jsonb
        patcher = mock.patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_put_checks_the_revision_under_the_drafts_lock_in_one_transaction(self):
        from decklab.lib.state import pg_deck_drafts
        conn = _Conn()
        store = _Store(conn)
        saved = pg_deck_drafts.put(store, "matt", DECK, "target", draft(1), 0, device="iPad")
        self.assertEqual(saved, {"revision": 1, "draft": {"saved_at": "2026-10-29T01:02:03+00:00", "device": "iPad",
                                                          "content": draft(1)}})
        self.assertEqual((conn.transactions, conn.locks), (1, ["deck-draft:" + "\n".join(("matt", DECK, "target"))]))
        with self.assertRaises(Conflict):
            pg_deck_drafts.put(store, "matt", DECK, "target", draft(2), 0)
        self.assertEqual(pg_deck_drafts.put(store, "matt", DECK, "target", None, 1), {"revision": 2, "draft": None})
        self.assertEqual(pg_deck_drafts.get(store, "matt", DECK, "target"), {"revision": 2, "draft": None})

    def test_a_new_decks_draft_has_its_own_table_key_and_lock(self):
        from decklab.lib.state import pg_deck_drafts
        conn = _Conn()
        store = _Store(conn)
        saved = pg_deck_drafts.new_put(store, "matt", "home", "", draft(1), 0, device="PC")
        self.assertEqual((saved["revision"], saved["draft"]["device"]), (1, "PC"))
        self.assertEqual(conn.locks, ["new-deck-draft:" + "\n".join(("matt", "home", ""))])
        self.assertTrue(any(sql.startswith("insert into new_deck_draft") for sql in conn.calls))
        self.assertFalse(any(" deck_draft " in f" {sql} " for sql in conn.calls))
        with self.assertRaises(Conflict):
            pg_deck_drafts.new_put(store, "matt", "home", "", draft(2), 0)
        self.assertEqual(pg_deck_drafts.new_get(store, "matt", "home", "")["draft"]["content"], draft(1))
        self.assertEqual(pg_deck_drafts.new_get(store, "matt", "home", DECK), {"revision": 0, "draft": None})

    def test_a_database_without_the_migration_is_found_before_any_table_is_named(self):
        from decklab.lib.state import pg_deck_drafts
        conn = _Conn(ready=False)
        for call in (lambda: pg_deck_drafts.get(_Store(conn), "matt", DECK, "target"),
                     lambda: pg_deck_drafts.put(_Store(conn), "matt", DECK, "target", draft(), 0),
                     lambda: pg_deck_drafts.new_get(_Store(conn), "matt", "home", ""),
                     lambda: pg_deck_drafts.new_put(_Store(conn), "matt", "home", "", draft(), 0)):
            with self.assertRaises(rules.MissingSchema):
                call()
        self.assertTrue(all("to_regclass" in sql for sql in conn.calls))


if __name__ == "__main__":
    unittest.main()
