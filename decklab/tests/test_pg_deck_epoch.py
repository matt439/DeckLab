"""Same-connection deck epoch reader using only explicit fake PostgreSQL objects.

Run with scripts/test_fixtures.py so protections precede module imports. No test
constructs a configured backend, connects to PostgreSQL, or reads card/user data.
"""

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import types
import unittest
from unittest import mock

from decklab.lib.inventory import pg_deck_epoch as reader
from decklab.lib.inventory.model import Deck, Inventory
from decklab.lib.inventory.pg import PgInventory


TEXT = "# Fixture deck\n\nDeck\n60 Forest\n"
ID = "casual/fixture"


class ForbiddenBoundary(BaseException):
    """A wrong connector/history boundary must escape ordinary failure handling."""


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self):
        self.info = types.SimpleNamespace(transaction_status=0)
        self.events = []
        self.queries = []
        self.isolation = "repeatable read"
        self.readonly = "on"
        self.claim = True
        self.current = (ID, 1, TEXT)
        self.history = [(ID, 1, "A", 7)]
        self.latest = (ID, 1, TEXT)
        self.fail = None

    @contextmanager
    def transaction(self):
        if self.info.transaction_status != 0:
            raise ForbiddenBoundary("Nested transaction")
        self.events.append("begin")
        self.info.transaction_status = 2
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("end")
        finally:
            self.info.transaction_status = 0

    def execute(self, sql, params=None):
        if self.info.transaction_status != 2:
            raise ForbiddenBoundary("Query outside owned transaction")
        sql = " ".join(sql.split())
        self.queries.append((sql, params))
        if self.fail and self.fail in sql:
            raise RuntimeError("Fixture private error must not be relayed")
        if sql == "set transaction isolation level repeatable read, read only":
            return Result([])
        if sql == "show transaction_isolation":
            return Result([(self.isolation,)])
        if sql == "show transaction_read_only":
            return Result([(self.readonly,)])
        if sql.startswith("select exists (") and "from pg_locks" in sql:
            return Result([(self.claim,)])
        if sql.startswith("select d.id, d.revision, t.text from deck d "):
            return Result([] if self.current is None else [self.current])
        if sql.startswith("select deck_id, revision, op, change_set_id from deck_revision "):
            return Result(self.history)
        if sql.startswith("select deck_id, revision, text from deck_revision "):
            return Result([] if self.latest is None else [self.latest])
        raise ForbiddenBoundary(f"Unsupported query: {sql}")


class PgDeckEpochTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection()
        self.snapshot = Inventory("7", backend="db", decks_revision="11", aliases_ready=True,
                                  decks={ID: Deck("home", "casual", "fixture", TEXT, revision=1)})
        # Bypass __init__ entirely: no .venv/default settings or configured connector.
        self.backend = object.__new__(PgInventory)
        self.backend._call = mock.Mock(side_effect=self.call)
        self.backend.load = mock.Mock(side_effect=self.load)
        for target in ("decklab.db.conn.connect", "decklab.lib.inventory.backend",
                       "decklab.lib.inventory.current", "decklab.lib.inventory.deck_revisions",
                       "decklab.lib.inventory.deck_revisions_with_text"):
            patcher = mock.patch(target, side_effect=ForbiddenBoundary("Forbidden default/history reader"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def call(self, work):
        self.assertEqual(self.conn.info.transaction_status, 0)
        return work(self.conn)

    def load(self, *, conn):
        self.assertIs(conn, self.conn)
        self.assertEqual(conn.info.transaction_status, 2)
        self.assertEqual(conn.queries[0][0], "set transaction isolation level repeatable read, read only")
        return self.snapshot

    def read(self, deck_id=ID):
        return reader.read(self.backend, deck_id)

    def assertUnavailable(self, result):
        self.assertEqual(asdict(result), {"status": "unavailable", "epoch": None, "receipt": None})

    def test_one_explicit_connection_and_readonly_repeatable_read(self):
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(asdict(result.epoch), {"kind": "creation", "deck_id": ID, "revision": 1})
        self.assertEqual(asdict(result.receipt), {"deck_id": ID, "revision": 1,
                                                "sha256": hashlib.sha256(TEXT.encode()).hexdigest()})
        self.backend._call.assert_called_once()
        self.backend.load.assert_called_once_with(conn=self.conn)
        self.assertEqual(self.conn.events, ["begin", "end"])
        self.assertEqual(self.conn.info.transaction_status, 0)
        self.assertNotIn(TEXT, repr(result))

    def test_minimal_bounded_history_has_no_actor_message_or_old_text(self):
        self.assertEqual(self.read().status, "ready")
        history = [query for query in self.conn.queries if "op, change_set_id" in query[0]]
        self.assertEqual(len(history), 1)
        sql, params = history[0]
        self.assertEqual(params, ([ID], reader.deck_epoch.MAX_HISTORY + 1))
        for private in ("actor", "message", "kit", "git_commit", "join audit"):
            self.assertNotIn(private, sql)
        self.assertNotIn("text", sql)
        self.assertEqual(sum("select deck_id, revision, text" in q[0] for q in self.conn.queries), 1)
        self.assertTrue(all(q[0].startswith(("select ", "show ", "set transaction ")) for q in self.conn.queries))

    def test_imported_m_start_supplies_database_baseline(self):
        self.conn.history = [(ID, 1, "M", None)]
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.epoch.kind, "baseline")

    def test_rename_preserves_creation_anchor_through_captured_aliases(self):
        new = "casual/renamed"
        self.snapshot = self.snapshot.replace(decks={new: Deck("home", "casual", "renamed", TEXT, revision=2)},
                                              deck_aliases={ID: new})
        self.conn.current = (new, 2, TEXT)
        self.conn.history = [(ID, 1, "A", 7), (new, 2, "M", 8)]
        self.conn.latest = (new, 2, TEXT)
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.epoch.deck_id, ID)
        self.assertEqual(result.receipt.deck_id, new)
        self.assertEqual(self.conn.queries[3][1], (new,))

    def test_recreation_selects_new_creation_instead_of_old_baseline(self):
        self.snapshot = self.snapshot.replace(decks={ID: self.snapshot.decks[ID].replace(revision=3)})
        self.conn.current = (ID, 3, TEXT)
        self.conn.history = [(ID, 1, "M", None), (ID, 2, "D", 8), (ID, 3, "A", 9)]
        self.conn.latest = (ID, 3, TEXT)
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(asdict(result.epoch), {"kind": "creation", "deck_id": ID, "revision": 3})

    def test_rename_delete_recreate_retains_alias_prefix_but_changes_epoch(self):
        new = "casual/renamed"
        self.snapshot = self.snapshot.replace(decks={new: Deck("home", "casual", "renamed", TEXT, revision=4)},
                                              deck_aliases={ID: new})
        self.conn.current = (new, 4, TEXT)
        self.conn.history = [(ID, 1, "A", 7), (new, 2, "M", 8), (new, 3, "D", 9), (new, 4, "A", 10)]
        self.conn.latest = (new, 4, TEXT)
        result = self.read()
        self.assertEqual(result.status, "ready")
        self.assertEqual(asdict(result.epoch), {"kind": "creation", "deck_id": new, "revision": 4})

    def test_lost_retired_alias_prefix_refuses_incomplete_lineage(self):
        self.snapshot = self.snapshot.replace(decks={ID: self.snapshot.decks[ID].replace(revision=3)})
        self.conn.current = (ID, 3, TEXT)
        self.conn.history = [(ID, 2, "D", 8), (ID, 3, "A", 9)]
        self.conn.latest = (ID, 3, TEXT)
        self.assertUnavailable(self.read())

    def test_unrelated_member_metadata_does_not_enter_home_capture(self):
        self.snapshot = self.snapshot.replace(
            decks={**self.snapshot.decks, "user2/casual/member": Deck("user2", "casual", "member", "Private fixture")},
            deck_aliases={"user2/casual/old": "user2/casual/member"})
        self.assertEqual(self.read().status, "ready")
        for sql, params in self.conn.queries:
            self.assertNotIn("user2", repr(params))

    def test_unsupported_backends_never_open_any_connection(self):
        for backend in (None, object(), types.SimpleNamespace(name="db", load=self.backend.load,
                                                             _call=self.backend._call)):
            with self.subTest(backend=type(backend).__name__):
                self.assertUnavailable(reader.read(backend, ID))
        self.backend._call.assert_not_called()
        self.backend.load.assert_not_called()

    def test_nonhome_or_malformed_requests_are_rejected_before_io(self):
        for value in (None, "user2/casual/member", "product/box", "casual/../bad", "home/casual/a", True):
            with self.subTest(value=value):
                self.assertUnavailable(self.read(value))
        self.backend._call.assert_not_called()

    def test_bad_snapshot_capability_never_reads_target_history(self):
        for changes in ({"backend": "files"}, {"root": "fixture"}, {"stale": "Fixture unavailable"},
                        {"revision": "7~preview"}, {"decks_revision": "11~preview"},
                        {"aliases_ready": False}, {"decks_revision": ""}, {"revision": "0"}):
            with self.subTest(changes=changes):
                self.snapshot = self.snapshot.replace(**changes)
                self.assertUnavailable(self.read())
                self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))
                self.snapshot = Inventory("7", backend="db", decks_revision="11", aliases_ready=True,
                                          decks={ID: Deck("home", "casual", "fixture", TEXT, revision=1)})
                self.conn.queries.clear()

    def test_invalid_home_aliases_fail_before_current_or_history_queries(self):
        for aliases in ({ID: "user2/casual/member"}, {"user2/casual/member": ID},
                        {"casual/old": "casual/../bad"}, {ID: ID},
                        {"casual/first": "casual/second", "casual/second": ID}):
            with self.subTest(aliases=aliases):
                self.snapshot = self.snapshot.replace(deck_aliases=aliases)
                self.assertUnavailable(self.read())
                self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))
                self.conn.queries.clear()

    def test_nonstring_alias_metadata_cannot_be_silently_projected_away(self):
        self.snapshot = self.snapshot.replace(deck_aliases={7: None})
        self.assertUnavailable(self.read())
        self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))

    def test_retired_home_and_member_aliases_do_not_poison_current_proof(self):
        self.snapshot = self.snapshot.replace(deck_aliases={"casual/retired": None,
                                                          "user2/casual/retired": None})
        self.assertEqual(self.read().status, "ready")
        self.conn.queries.clear()
        self.assertUnavailable(self.read("casual/retired"))
        self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))

    def test_unrelated_retirement_keeps_nonnull_target_without_current_row(self):
        self.snapshot = self.snapshot.replace(deck_aliases={"casual/former": "casual/retired"})
        self.assertEqual(self.read().status, "ready")
        self.conn.queries.clear()
        self.assertUnavailable(self.read("casual/former"))
        self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))

    def test_invalid_held_deck_is_unavailable_before_target_query_even_in_internal_capture(self):
        self.backend.load.side_effect = lambda *, conn: self.snapshot
        self.conn.info.transaction_status = 2
        for held in (object(), {}, self.snapshot.decks[ID].replace(revision=True),
                     self.snapshot.decks[ID].replace(text=None), self.snapshot.decks[ID].replace(space="user2")):
            with self.subTest(held=type(held).__name__):
                self.snapshot = self.snapshot.replace(decks={ID: held})
                self.assertIsNone(reader.capture_on_connection(self.backend, self.conn, ID,
                                                              coherence="inventory-locked"))
                self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))
                self.conn.queries.clear()

    def test_metadata_caps_refuse_instead_of_truncating(self):
        valid = self.snapshot
        self.snapshot = valid.replace(deck_aliases={f"casual/old-{number}": ID
                                                   for number in range(reader.deck_epoch.MAX_ALIASES + 1)})
        self.assertUnavailable(self.read())
        self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))
        self.conn.queries.clear()
        self.snapshot = valid.replace(decks={f"casual/deck-{number}": Deck("home", "casual", f"deck-{number}")
                                             for number in range(reader.deck_epoch.MAX_CURRENT_IDS + 1)})
        self.assertUnavailable(self.read())
        self.assertFalse(any("from deck d" in q[0] for q in self.conn.queries))

    def test_current_row_must_match_same_connection_snapshot(self):
        for row in (None, (ID, 1, TEXT + "Changed"), (ID, 2, TEXT), ("casual/other", 1, TEXT)):
            with self.subTest(row=row):
                self.conn.current = row
                self.assertUnavailable(self.read())
                self.assertFalse(any("from deck_revision" in q[0] for q in self.conn.queries))
                self.conn.queries.clear()

    def test_current_revision_over_cap_stops_before_history_query(self):
        self.conn.current = (ID, reader.deck_epoch.MAX_HISTORY + 1, TEXT)
        self.assertUnavailable(self.read())
        self.assertFalse(any("from deck_revision" in q[0] for q in self.conn.queries))

    def test_full_history_cap_never_accepts_a_truncated_proof(self):
        self.conn.history *= reader.deck_epoch.MAX_HISTORY + 1
        self.assertUnavailable(self.read())
        self.assertFalse(any("select deck_id, revision, text" in q[0] for q in self.conn.queries))

    def test_history_gap_duplicate_or_changed_latest_are_unavailable(self):
        for history in ([], [(ID, 2, "A", 7)], [(ID, 1, "A", 7), (ID, 1, "M", 8)]):
            with self.subTest(history=history):
                self.conn.history = history
                self.assertUnavailable(self.read())
        self.conn.history = [(ID, 1, "A", 7)]
        self.conn.latest = (ID, 1, TEXT + "Not current")
        self.assertUnavailable(self.read())

    def test_text_cap_and_invalid_unicode_fail_without_history(self):
        for text in ("x" * (reader.deck_epoch.MAX_TEXT_BYTES + 1), "\ud800"):
            with self.subTest(size=len(text)):
                self.conn.current = (ID, 1, text)
                self.assertUnavailable(self.read())
                self.assertFalse(any("from deck_revision" in q[0] for q in self.conn.queries))
                self.conn.queries.clear()

    def test_database_failure_unwinds_transaction_without_stale_retry_or_error_relay(self):
        self.conn.fail = "from deck_revision"
        self.assertUnavailable(self.read())
        self.assertEqual(self.conn.events, ["begin", "rollback"])
        self.backend._call.assert_called_once()
        self.backend.load.assert_called_once_with(conn=self.conn)

    def test_unavailable_backend_never_uses_cached_load_fallback(self):
        self.backend._call.side_effect = RuntimeError("Fixture configured-server failure")
        self.assertUnavailable(self.read())
        self.backend.load.assert_not_called()

    def test_internal_capture_requires_explicit_verified_coherence(self):
        with self.assertRaises(TypeError):
            reader.capture_on_connection(self.backend, self.conn, ID)
        self.assertIsNone(reader.capture_on_connection(self.backend, self.conn, ID, coherence="reader"))
        self.backend.load.assert_not_called()
        self.assertEqual(self.conn.queries, [])

    def test_reader_mode_rejects_read_committed_or_writable_transactions(self):
        for isolation, readonly in (("read committed", "on"), ("repeatable read", "off")):
            with self.subTest(isolation=isolation, readonly=readonly):
                self.conn.isolation, self.conn.readonly = isolation, readonly
                self.assertUnavailable(self.read())
                self.backend.load.assert_not_called()

    def test_internal_capture_keeps_existing_transaction_and_checks_exact_inventory_claim(self):
        self.conn.info.transaction_status = 2
        self.backend.load.side_effect = lambda *, conn: self.snapshot
        capture = reader.capture_on_connection(self.backend, self.conn, ID, coherence="inventory-locked")
        self.assertEqual(reader.deck_epoch.resolve(capture).status, "ready")
        self.assertEqual(self.conn.events, [])
        self.assertEqual(self.conn.info.transaction_status, 2)
        self.backend._call.assert_not_called()
        sql, params = self.conn.queries[0]
        self.assertIsNone(params)
        for expected in ("pg_backend_pid()", "current_database()", "granted", "objsubid = 1",
                         "'ShareLock', 'ExclusiveLock'", "classid::bigint", "objid::bigint",
                         "hashtext('inventory')::bigint >> 32", "& 4294967295"):
            self.assertIn(expected, sql)
        self.assertNotIn("pg_advisory_xact_lock(", sql)

    def test_missing_inventory_claim_cannot_be_manufactured(self):
        self.conn.info.transaction_status = 2
        self.conn.claim = False
        self.assertIsNone(reader.capture_on_connection(self.backend, self.conn, ID, coherence="inventory-locked"))
        self.backend.load.assert_not_called()
        self.backend._call.assert_not_called()
        self.assertEqual(len(self.conn.queries), 1)
        self.assertEqual(self.conn.events, [])


if __name__ == "__main__":
    raise SystemExit("Use scripts/test_fixtures.py for protected fixture checks.")
