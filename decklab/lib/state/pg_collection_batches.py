"""Private resumable batches: transaction participant, NOT a public API.

The caller supplies an already-open READ COMMITTED transaction and an authenticated
profile, never a body-supplied owner. No connections, commits or inventory writes
are opened here. complete's trusted inventory adapter MUST write inventory, raw
source and audit using the supplied cursor, not call inventory.apply separately.
The typed inventory adapter claims before effects and finishes after SQL readback
in PgInventory.apply. No route is exposed. SQL remains staged pending migration
promotion and full lifecycle qualification.
"""
import hashlib
import json
import uuid

from decklab.db import space_members
from decklab.lib.state import Conflict, Invalid, Unavailable

DRAFT_CONTRACT_VERSION = 3  # Optional bounded evidence; older payloads remain byte-for-byte valid.
CHANGED = "This batch changed. Reload and review it again."
DENIED = "This collection batch is not available."
_FIELDS = {"name", "set", "collector_number", "finish", "condition", "language", "quantity"}


class MissingSchema(Unavailable):
    """Staged capability absent, distinct from an unconfirmed database outcome."""


def content(value):
    """Only card metadata; never photos, OCR blobs, prices or arbitrary properties."""
    if not isinstance(value, dict) or set(value) not in ({"label", "rows", "unresolved"}, {"label", "rows", "unresolved", "evidence"}):
        raise Invalid("Invalid collection batch.")
    label, rows, unresolved = value["label"], value["rows"], value["unresolved"]
    if not isinstance(label, str) or len(label) > 80:
        raise Invalid("Use a batch label of at most 80 characters.")
    if not isinstance(rows, list) or len(rows) > 200:
        raise Invalid("Keep a batch to at most 200 card groups.")
    if not isinstance(unresolved, list) or len(unresolved) > 30 or any(
            not isinstance(x, str) or len(x) > 160 for x in unresolved):
        raise Invalid("Keep at most 30 short unresolved-card labels.")
    keys = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != _FIELDS:
            raise Invalid("Invalid collection batch row.")
        if any(not isinstance(row[k], str) or len(row[k]) > 160 for k in _FIELDS - {"quantity"}):
            raise Invalid("Invalid printing metadata.")
        if type(row["quantity"]) is not int or not 1 <= row["quantity"] <= 9999:
            raise Invalid("Count between 1 and 9999 copies.")
        if not all(row[k].strip() for k in ("name", "set", "collector_number")):
            raise Invalid("Choose an exact printing.")
        if row["finish"] not in {"nonfoil", "foil", "etched"}:
            raise Invalid("Choose a finish.")
        key = row["set"], row["collector_number"], row["finish"], row["condition"], row["language"]
        if key in keys:
            raise Invalid("Count repeated copies with the same printing, condition and language in one row.")
        keys.add(key)
    if "evidence" in value:
        from .collection_batch_evidence import validate
        validate(value["evidence"], rows, unresolved)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(raw.encode()) > 262144:
        raise Invalid("The collection batch is too large.")
    return json.loads(raw)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _identity(batch_id):
    try:
        return str(uuid.UUID(str(batch_id)))
    except (ValueError, TypeError, AttributeError):
        raise Invalid("Invalid batch identity.") from None


def _lock(cur, profile, space):
    from psycopg.pq import TransactionStatus
    if cur.connection.info.transaction_status != TransactionStatus.INTRANS:
        raise Invalid("Collection batches require an existing transaction.")
    # Same first lock as inventory writers/removal; no lock upgrades or reverse order.
    cur.execute("select pg_advisory_xact_lock(hashtext(%s))", ("inventory",))
    space_members.admit(cur, profile_ids=[profile], space_ids=[space], lock=False)
    row = cur.execute("select space_id from profile where id=%s for share", (profile,)).fetchone()
    if row != (space,):
        raise Invalid(DENIED)
    if not cur.execute("select to_regclass('public.collection_batch') is not null").fetchone()[0]:
        raise MissingSchema("Resumable collection batches are not installed.")


def _get(cur, profile, space, batch_id):
    row = cur.execute("select revision, status, content, review, receipt from collection_batch "
                      "where profile_id=%s and space_id=%s and batch_id=%s for update",
                      (profile, space, _identity(batch_id))).fetchone()
    if row is None:
        raise Invalid(DENIED)
    return dict(zip(("revision", "status", "content", "review", "receipt"), row))


def _revision(cur):
    row = cur.execute("select revision from inventory_revision").fetchone()
    if row is None:
        raise Unavailable("The inventory has not been initialized.")
    return str(row[0])


def read(cur, profile, space, batch_id):
    _lock(cur, profile, space)
    return _get(cur, profile, space, batch_id)


def create(cur, profile, space, batch_id, value):
    from psycopg.types.json import Jsonb
    value, batch_id = content(value), _identity(batch_id)
    _lock(cur, profile, space)
    prior = cur.execute("select initial_digest from collection_batch where profile_id=%s "
                        "and space_id=%s and batch_id=%s", (profile, space, batch_id)).fetchone()
    if prior:
        if prior[0] != _digest(value):
            raise Conflict(CHANGED)
        # Retry returns the current state, including a consumed identity, never a new draft.
        return _get(cur, profile, space, batch_id)
    if cur.execute("select 1 from collection_batch where profile_id=%s and space_id=%s "
                   "and status='draft'", (profile, space)).fetchone():
        raise Conflict("Resume or discard your existing batch first.")
    cur.execute("insert into collection_batch (profile_id,space_id,batch_id,initial_digest,content) "
                "values (%s,%s,%s,%s,%s)", (profile, space, batch_id, _digest(value), Jsonb(value)))
    return _get(cur, profile, space, batch_id)


def _draft(row, expected):
    if type(expected) is not int or row["revision"] != expected or row["status"] != "draft":
        raise Conflict(CHANGED)


def save(cur, profile, space, batch_id, expected, value):
    from psycopg.types.json import Jsonb
    value = content(value)
    _lock(cur, profile, space)
    row = _get(cur, profile, space, batch_id)
    _draft(row, expected)
    if "evidence" in row["content"] and "evidence" not in value:
        raise Invalid("This batch includes scanner evidence. Resume with an evidence-aware editor; nothing was removed.")
    cur.execute("update collection_batch set content=%s,revision=revision+1,review=null,saved_at=now() "
                "where profile_id=%s and space_id=%s and batch_id=%s",
                (Jsonb(value), profile, space, _identity(batch_id)))
    return _get(cur, profile, space, batch_id)


def review(cur, profile, space, batch_id, expected):
    from psycopg.types.json import Jsonb
    _lock(cur, profile, space)
    row = _get(cur, profile, space, batch_id)
    _draft(row, expected)
    if not row["content"]["rows"] or row["content"]["unresolved"]:
        raise Invalid("Resolve or explicitly set aside ambiguous cards before review.")
    token = {"revision": expected, "digest": _digest(row["content"]),
             "inventory_revision": _revision(cur), "nonce": str(uuid.uuid4())}
    cur.execute("update collection_batch set review=%s where profile_id=%s and space_id=%s and batch_id=%s",
                (Jsonb(token), profile, space, _identity(batch_id)))
    return token


class Claim:
    """Internal transaction-bound claim, never serialized or accepted from a request."""
    def __init__(self, cur, profile, space, batch_id, row):
        self.connection = cur.connection
        self.transaction = cur.execute("select txid_current()").fetchone()[0]
        self.profile, self.space, self.batch_id = profile, space, _identity(batch_id)
        self.row = row


def claim(cur, profile, space, batch_id, token):
    """Return (claim, None), or (None, previous receipt), before inventory effects."""
    _lock(cur, profile, space)
    row = _get(cur, profile, space, batch_id)
    if type(token) is not dict or type(token.get("revision")) is not int or row["review"] != token:
        raise Conflict(CHANGED)
    if row["status"] == "committed":
        return None, row["receipt"]
    _draft(row, token.get("revision"))
    if token.get("digest") != _digest(row["content"]) or token.get("inventory_revision") != _revision(cur):
        raise Conflict("The collection changed. Review this batch again.")
    return Claim(cur, profile, space, batch_id, row), None


def finish(cur, pending, result):
    """Write receipt after inventory effects, on exactly the claimed transaction.

    Trusted backend only. Caller must let any exception roll back its entire change.
    The backend confirms its inventory/audit/raw-import effects before calling here.
    """
    from psycopg.types.json import Jsonb
    if not isinstance(pending, Claim) or pending.connection is not cur.connection:
        raise Invalid("A batch receipt needs its original transaction.")
    if cur.execute("select txid_current()").fetchone()[0] != pending.transaction:
        raise Invalid("A batch receipt needs its original transaction.")
    row = _get(cur, pending.profile, pending.space, pending.batch_id)
    if row != pending.row:
        raise Conflict(CHANGED)
    if not isinstance(result, dict) or len(json.dumps(result).encode()) > 16384:
        raise Invalid("Invalid collection batch receipt.")
    receipt = {"batch_id": pending.batch_id, "revision": row["revision"],
               "inventory_revision": _revision(cur), "result": result}
    cur.execute("update collection_batch set status='committed',receipt=%s,content=null,saved_at=now() "
                "where profile_id=%s and space_id=%s and batch_id=%s",
                (Jsonb(receipt), pending.profile, pending.space, pending.batch_id))
    return receipt


def complete(cur, profile, space, batch_id, token, apply):
    """Convenience participant for trusted single-cursor callers, not a public API."""
    pending, previous = claim(cur, profile, space, batch_id, token)
    if pending is None:
        return previous
    return finish(cur, pending, apply(cur, pending.row["content"]))


def discard(cur, profile, space, batch_id, expected):
    _lock(cur, profile, space)
    row = _get(cur, profile, space, batch_id)
    _draft(row, expected)
    cur.execute("update collection_batch set status='discarded',revision=revision+1,content=null,review=null, "
                "saved_at=now() where profile_id=%s and space_id=%s and batch_id=%s",
                (profile, space, _identity(batch_id)))
    return _get(cur, profile, space, batch_id)


def listing(cur, profile, space):
    """Bounded own-profile recovery index: active draft first, then recent receipts."""
    _lock(cur, profile, space)
    rows = cur.execute("select batch_id::text, revision, status, saved_at, content->>'label' "
                       "from collection_batch where profile_id=%s and space_id=%s "
                       "order by (status='draft') desc, saved_at desc, batch_id limit 11",
                       (profile, space)).fetchall()
    return {"batches": [{"batch_id": bid, "revision": rev, "status": status,
                         "saved_at": stamp.isoformat(), "label": label}
                        for bid, rev, status, stamp, label in rows[:10]], "has_more": len(rows) > 10}
