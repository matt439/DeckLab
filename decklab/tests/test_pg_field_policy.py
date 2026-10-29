"""Real policy-store/epoch/list checks over explicit fake SQL and inventory.

Use scripts/test_fixtures.py. No PostgreSQL, private configuration, card cache,
Forge runtime or default inventory connector is used by these fixtures.
"""
import copy
from contextlib import contextmanager
import hashlib
import sys
import types
import unittest
from unittest import mock

from decklab.lib.inventory.model import Deck, Inventory
from decklab.lib.inventory.pg import PgInventory
from decklab.lib.state import Actor, Conflict, Invalid, Unavailable
from decklab.lib.state import field_policy, pg_field_policy
from decklab.lib.state.pg import PgStore

ID = "casual/fixture"
TEXT = "# Fixture\n\n## Decklist\n```text\nDeck\n60 Forest\n```\n"
ACTOR = Actor("test", "Fixture", None, "test")


class ForbiddenBoundary(BaseException):
    pass


class Jsonb:
    def __init__(self, obj):
        self.obj = copy.deepcopy(obj)


class Connection:
    def __init__(self):
        self.info = types.SimpleNamespace(transaction_status=0, dbname="fixture-active")
        self.policy = {}
        self.audit = []
        self.audit_rows = []
        self.events = []
        self.schema = True
        self.claim = False
        self.return_revision = True
        self.on_claim = None
        self.on_format_lock = None
        self.snapshot = Inventory("7", backend="db", aliases_ready=True, decks_revision="11",
                                  decks={ID: Deck("home", "casual", "fixture", TEXT, revision=1)})
        self.history = [(ID, 1, "A", 7)]
        self.latest = (ID, 1, TEXT)
        self.rows = []
        self.isolation = "repeatable read"  # Explicit RC must override this per transaction.
        self.frozen = None

    def bundle(self):
        return self.snapshot, self.history, self.latest

    def visible(self):
        return self.frozen if self.isolation == "repeatable read" and self.frozen is not None else self.bundle()

    def change_text(self, text):
        self.snapshot = self.snapshot.replace(decks_revision="12",
                                              decks={ID: self.snapshot.decks[ID].replace(text=text, revision=2)})
        self.history = [(ID, 1, "A", 7), (ID, 2, "M", 8)]
        self.latest = (ID, 2, text)

    @contextmanager
    def transaction(self):
        if self.info.transaction_status != 0:
            raise ForbiddenBoundary("Nested transaction")
        saved = copy.deepcopy((self.policy, self.audit, self.audit_rows))
        self.info.transaction_status = 2
        self.isolation, self.claim, self.frozen = "repeatable read", False, None
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.policy, self.audit, self.audit_rows = saved
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.info.transaction_status = 0
            self.claim = False

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        self.events.append((sql, params))
        self.rows = []
        if sql == "set transaction isolation level read committed":
            if self.audit and self.frozen is not None:
                raise ForbiddenBoundary("Isolation changed after snapshot")
            self.isolation = "read committed"
        elif sql.startswith("insert into audit.change_set"):
            self.frozen = self.bundle()
            self.audit.append(params)
            self.rows = [(len(self.audit),)]
        elif sql.startswith("select set_config('decklab.change_set'"):
            pass
        elif sql.startswith("select pg_advisory_xact_lock_shared"):
            self.claim = True
            if self.on_claim:
                self.on_claim()
        elif sql.startswith("select id from space where id = any"):
            self.rows = [("home",)]
        elif sql.startswith("select pg_advisory_xact_lock(hashtext"):
            if not self.claim:
                raise ForbiddenBoundary("Format lock before inventory claim")
            if self.on_format_lock:
                self.on_format_lock()
        elif sql == "select to_regclass('public.field_policy') is not null":
            self.rows = [(self.schema,)]
        elif sql.startswith("select revision, content from field_policy"):
            row = self.policy.get(params[0])
            self.rows = [] if row is None else [copy.deepcopy(row)]
        elif sql.startswith("select exists (") and "from pg_locks" in sql:
            self.rows = [(self.claim,)]
        elif sql.startswith("select d.id, d.revision, t.text from deck d"):
            deck = self.visible()[0].decks.get(params[0])
            self.rows = [] if deck is None else [(deck.id, deck.revision, deck.text)]
        elif sql.startswith("select deck_id, revision, op, change_set_id from deck_revision"):
            self.rows = self.visible()[1]
        elif sql.startswith("select deck_id, revision, text from deck_revision"):
            self.rows = [self.visible()[2]]
        elif sql.startswith("insert into field_policy"):
            fmt, revision, wrapped, expected = params
            old = self.policy.get(fmt)
            if self.return_revision and (old is None or old[0] == expected):
                after = (revision, copy.deepcopy(wrapped.obj))
                self.policy[fmt] = after
                self.audit_rows.append((fmt, old, after))
                self.rows = [(revision,)]
        else:
            raise ForbiddenBoundary(f"Unsupported SQL: {sql}")
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class PgFieldPolicyTests(unittest.TestCase):
    def setUp(self):
        self.conn = Connection()
        self.store = PgStore(dbname="must-not-select-this-db")
        self.store._call = mock.Mock(side_effect=lambda work: work(self.conn))
        self.backend = object.__new__(PgInventory)
        self.backend.load = mock.Mock(side_effect=self.load)
        self.backend._call = mock.Mock(side_effect=ForbiddenBoundary("Independent inventory connection"))
        self.factory = mock.Mock(return_value=self.backend)
        patcher = mock.patch.object(pg_field_policy, "PgInventory", self.factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        pg = types.ModuleType("psycopg")
        pq = types.ModuleType("psycopg.pq")
        pq.TransactionStatus = types.SimpleNamespace(IDLE=0)
        pg_types = types.ModuleType("psycopg.types")
        pg_json = types.ModuleType("psycopg.types.json")
        pg_json.Jsonb = Jsonb
        pg.pq, pg.types, pg_types.json = pq, pg_types, pg_json
        patcher = mock.patch.dict(sys.modules, {"psycopg": pg, "psycopg.pq": pq,
                                               "psycopg.types": pg_types, "psycopg.types.json": pg_json})
        patcher.start()
        self.addCleanup(patcher.stop)
        for target in ("decklab.db.conn.connect", "decklab.lib.inventory.backend", "decklab.lib.inventory.current",
                       "decklab.lib.inventory.deck_revisions", "decklab.lib.config.load"):
            patcher = mock.patch(target, side_effect=ForbiddenBoundary("Configured/default boundary"))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.expected = self.proof()
        self.rule = {"epoch": self.expected["epoch"], "mode": "include", "version": "target"}

    def load(self, *, conn):
        self.assertIs(conn, self.conn)
        self.assertEqual(conn.info.transaction_status, 2)
        self.assertTrue(conn.claim)
        conn.events.append("fresh inventory")
        return conn.visible()[0]

    def proof(self, version="target", text=TEXT, revision=1, name="Forest"):
        return {"epoch": {"kind": "creation", "deck_id": ID, "revision": 1},
                "receipt": {"deck_id": ID, "revision": revision,
                            "sha256": hashlib.sha256(text.encode()).hexdigest()},
                "version": version, "card_sha": hashlib.sha256(f"[Main]\n60 {name}\n".encode()).hexdigest()}

    def apply(self, revision=0, proof=None, rule=None, reason=None):
        return self.store.field_policy_apply("Constructed", revision, proof or self.expected,
                                              rule or self.rule, ACTOR, "Review field choice", reason)

    def seed(self, revision=1):
        self.conn.policy["Constructed"] = (revision, {"v": 1, "rules": [copy.deepcopy(self.rule)]})

    def test_schema_ready_absence_is_the_only_empty_policy(self):
        self.assertEqual(self.store.field_policy("Constructed"), field_policy.empty("Constructed"))
        self.assertEqual(self.conn.audit, [])
        self.factory.assert_not_called()

    def test_missing_schema_is_unavailable_and_does_not_trip_breaker(self):
        trips = self.store.breaker.trips
        self.conn.schema = False
        with self.assertRaisesRegex(Unavailable, "migration"):
            self.store.field_policy("Constructed")
        self.assertEqual(self.store.breaker.trips, trips)

    def test_corrupt_or_noncanonical_rows_never_become_empty(self):
        for row in ((0, {"v": 1, "rules": []}), (1, None), (1, {"v": 1, "rules": [], "private": "fixture"}),
                    (1, {"v": True, "rules": []})):
            with self.subTest(row=row):
                self.conn.policy["Constructed"] = row
                with self.assertRaises(Unavailable) as caught:
                    self.store.field_policy("Constructed")
                self.assertEqual(str(caught.exception), pg_field_policy.UNAVAILABLE)

    def test_changed_policy_has_one_audit_and_one_cas_upsert(self):
        result = self.apply()
        self.assertTrue(result["changed"])
        self.assertEqual(result["snapshot"]["revision"], 1)
        self.assertEqual(len(self.conn.audit), 1)
        self.assertEqual(len(self.conn.audit_rows), 1)
        statements = [e[0] for e in self.conn.events if isinstance(e, tuple)]
        self.assertEqual(sum(s.startswith("insert into field_policy") for s in statements), 1)
        self.assertIn("where field_policy.revision = %s returning revision", statements[-1])
        self.assertEqual(self.conn.policy["Constructed"], (1, {"v": 1, "rules": [self.rule]}))

    def test_exact_connection_and_claim_lock_cas_source_order(self):
        self.apply()
        events = self.conn.events
        sql = [e[0] for e in events if isinstance(e, tuple)]
        self.assertEqual(sql[0], "set transaction isolation level read committed")
        self.assertTrue(sql[1].startswith("insert into audit.change_set"))
        shared = next(i for i, e in enumerate(events) if isinstance(e, tuple) and "lock_shared" in e[0])
        fmt = next(i for i, e in enumerate(events) if isinstance(e, tuple) and e[1] == ("field-policy:home:Constructed",))
        self.assertLess(shared, fmt)
        self.assertLess(fmt, events.index("fresh inventory"))
        self.factory.assert_called_once_with(dbname="fixture-active", timeout=self.store.timeout,
                                             breaker=self.store.breaker)
        self.backend.load.assert_called_once_with(conn=self.conn)
        self.backend._call.assert_not_called()
        self.assertFalse(any("default_transaction" in s or s.startswith("alter ") for s in sql))

    def test_stale_policy_conflicts_before_fresh_source_even_for_identical_intent(self):
        self.seed()
        with self.assertRaises(Conflict):
            self.apply(revision=0)
        self.factory.assert_not_called()
        self.assertEqual(self.conn.audit, [])
        self.assertEqual(self.conn.events[-1], "rollback")

    def test_noop_still_checks_list_and_rolls_back_empty_audit(self):
        self.seed()
        result = self.apply(revision=1)
        self.assertFalse(result["changed"])
        self.backend.load.assert_called_once_with(conn=self.conn)
        self.assertEqual(self.conn.audit, [])
        self.assertEqual(self.conn.audit_rows, [])
        self.assertEqual(self.conn.events[-1], "rollback")

    def test_source_change_during_claim_wait_cannot_be_hidden_by_old_rr_snapshot(self):
        self.seed()
        self.conn.on_claim = lambda: self.conn.change_text(TEXT + "\nChanged fixture note.\n")
        with self.assertRaises(Conflict):
            self.apply(revision=1)
        self.assertEqual(self.conn.audit, [])
        self.assertEqual(self.conn.snapshot.decks[ID].revision, 2)

    def test_wrong_fingerprint_blocks_write_and_noop(self):
        for revision in (0, 1):
            with self.subTest(revision=revision):
                if revision:
                    self.seed()
                bad = copy.deepcopy(self.expected)
                bad["card_sha"] = "0" * 64
                with self.assertRaises(Conflict):
                    self.apply(revision=revision, proof=bad)
                self.assertEqual(self.conn.audit, [])

    def test_include_version_must_equal_explicit_review_before_io(self):
        rule = {**self.rule, "version": "owned"}
        with self.assertRaises(Invalid):
            self.apply(rule=rule)
        self.store._call.assert_not_called()

    def test_missing_owned_version_is_not_invented_from_target_or_pool(self):
        proof = self.proof(version="owned")
        rule = {**self.rule, "version": "owned"}
        with self.assertRaises(Unavailable):
            self.apply(proof=proof, rule=rule)
        self.assertEqual(self.conn.audit, [])

    def test_owned_version_is_verified_from_persisted_text(self):
        text = TEXT + "\n## Substitutes\n\n### Owned-only version\n```text\nDeck\n60 Island\n```\n"
        self.conn.snapshot = self.conn.snapshot.replace(decks={ID: self.conn.snapshot.decks[ID].replace(text=text)})
        self.conn.latest = (ID, 1, text)
        result = self.apply(proof=self.proof("owned", text, name="Island"),
                            rule={**self.rule, "version": "owned"})
        self.assertTrue(result["changed"])

    def test_exclude_requires_reason_and_keeps_it_only_in_private_audit(self):
        rule = {"epoch": self.expected["epoch"], "mode": "exclude"}
        with self.assertRaises(Invalid):
            self.apply(rule=rule)
        self.store._call.assert_not_called()
        result = self.apply(rule=rule, reason="  Fixture exclusion reason  ")
        self.assertEqual(result["snapshot"]["rules"], [rule])
        self.assertNotIn("Fixture exclusion reason", repr(self.conn.policy))
        self.assertEqual(self.conn.audit[0][3], "Fixture exclusion reason")

    def test_use_rules_is_a_retained_revisioned_entry(self):
        rule = {"epoch": self.expected["epoch"], "mode": "rules"}
        first = self.apply(rule=rule)
        second = self.apply(revision=1, rule=rule)
        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(self.store.field_policy("Constructed")["rules"], [rule])
        self.assertEqual(len(self.conn.audit), 1)

    def test_sql_cas_failure_rolls_back_every_audit_and_policy_row(self):
        self.conn.return_revision = False
        with self.assertRaises(Conflict):
            self.apply()
        self.assertEqual(self.conn.policy, {})
        self.assertEqual(self.conn.audit, [])
        self.assertEqual(self.conn.audit_rows, [])

    def test_missing_inventory_claim_prevents_source_load(self):
        self.conn.on_format_lock = lambda: setattr(self.conn, "claim", False)
        with self.assertRaises(Unavailable):
            self.apply()
        self.backend.load.assert_not_called()
        self.assertEqual(self.conn.audit, [])

    def test_batch_and_nonidle_connection_are_refused_without_nested_transaction(self):
        self.store._local.batch = object()
        with self.assertRaises(Invalid):
            self.apply()
        self.store._call.assert_not_called()
        self.store._local.batch = None
        self.conn.info.transaction_status = 2
        with self.assertRaises(Invalid):
            self.apply()
        self.assertEqual(self.conn.events, [])

    def test_unavailable_error_does_not_relay_private_diagnostic_or_fallback(self):
        self.store._call.side_effect = Unavailable("Fixture private database diagnostic")
        with self.assertRaises(Unavailable) as caught:
            self.store.field_policy("Constructed")
        self.assertEqual(str(caught.exception), pg_field_policy.UNAVAILABLE)
        self.backend.load.assert_not_called()

    def test_noop_at_bigint_max_still_rechecks_source(self):
        self.seed(field_policy.MAX_REVISION)
        result = self.apply(revision=field_policy.MAX_REVISION)
        self.assertFalse(result["changed"])
        self.backend.load.assert_called_once()
        changed = {"epoch": self.expected["epoch"], "mode": "rules"}
        with self.assertRaises(Invalid):
            self.apply(revision=field_policy.MAX_REVISION, rule=changed)
        self.assertEqual(self.conn.audit, [])

    def test_recreated_source_cannot_reuse_old_epoch_even_with_current_receipt(self):
        self.conn.snapshot = self.conn.snapshot.replace(decks={ID: self.conn.snapshot.decks[ID].replace(revision=3)})
        self.conn.history = [(ID, 1, "A", 7), (ID, 2, "D", 8), (ID, 3, "A", 9)]
        self.conn.latest = (ID, 3, TEXT)
        with self.assertRaises(Conflict):
            self.apply(proof=self.proof(revision=3))
        self.assertEqual(self.conn.audit, [])


if __name__ == "__main__":
    raise SystemExit("Use scripts/test_fixtures.py for protected fixture checks.")
