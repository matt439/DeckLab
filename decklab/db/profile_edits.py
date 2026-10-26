"""Guarded Settings email replacement and exact-audit config publication recovery.

Only an existing explicit non-home member is editable. Membership/config parity,
all aliases and the full raw config are bound by receipts. A pending journal is
durable before SQL; only its immutable audited outcome authorizes publication.
"""
import base64
import copy
import hashlib
import json
import re
import uuid
from types import SimpleNamespace

from decklab.db import conn as db, profiles_sync, space_members
from decklab.lib import config, profile_config as files, profiles
from decklab.lib.profile_config import InvalidProfileEdit, PendingProfileEdit, StaleProfileEdit

OPTIONS = "-c lock_timeout=2000 -c statement_timeout=15000"
STALE = "Member settings changed. Reload and review the change again."
MISMATCH = "Member configuration and database differ. Run python -m decklab.db sync-profiles locally before editing."


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _receipt(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise InvalidProfileEdit("Full configuration and membership receipts are required. Reload this panel.")
    return value


def _email(value):
    email = profiles.email_key(value)
    if email is None or len(email) > 254 or email.count("@") != 1:
        raise InvalidProfileEdit("Enter a valid email address using ASCII characters.")
    local, domain = email.split("@")
    if not 1 <= len(local) <= 64 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) \
            or local.startswith(".") or local.endswith(".") or ".." in local \
            or len(domain) > 253 or "." not in domain \
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                   for label in domain.split(".")):
        raise InvalidProfileEdit("Enter a valid email address using ASCII characters.")
    return email


def _listed(raw):
    try:
        listed = profiles.read_checked(raw)
    except profiles.InvalidProfiles:
        raise InvalidProfileEdit("Fix invalid profile entries locally before editing member settings.") from None
    if not listed or profiles.legacy(raw.get("profiles")):
        raise InvalidProfileEdit("Set explicit profile roles locally before editing member settings.")
    seen = set()
    for profile in listed:
        for email in profile["emails"]:
            if email in seen:
                raise InvalidProfileEdit("An email belongs to more than one profile. Fix the configuration locally first.")
            seen.add(email)
    return listed


def _database(dbname):
    settings = db.settings()
    return {"host": str(settings["host"]), "port": int(settings["port"]),
            "name": dbname or settings["name"]}


def _locks(cur):
    space_members.shared(cur)
    # Same order as profiles_sync; the shared claim excludes member departure.
    cur.execute("lock table profile, profile_email, space in share row exclusive mode")


def _current(cur):
    have = profiles_sync.current(cur)
    departed = []
    if space_members.installed(cur):
        departed = [row[0] for row in cur.execute("select space_id from space_departure order by space_id")]
    serial = {"spaces": sorted(have[0]), "profiles": sorted(have[1].items()), "departed": departed}
    return have, _sha(serial), set(departed)


def _check(cur, listed, expected=None):
    if hasattr(cur, "cursor"):
        with cur.cursor() as cursor:
            return _check(cursor, listed, expected)
    have, receipt, departed = _current(cur)
    want = profiles_sync.wanted(listed)
    if departed & (want[0] | set(want[1])):
        raise InvalidProfileEdit("That member is no longer active. Nothing was saved.")
    if expected is not None and receipt != expected:
        raise StaleProfileEdit(STALE)
    if have != want:
        raise StaleProfileEdit(MISMATCH)
    return receipt


def _members(raw, listed):
    explicit = {p["id"] for p in raw["profiles"] if p.get("role") == "member" and p.get("space") == p["id"]}
    return [{"id": p["id"], "name": p["name"], "emails": list(p["emails"])}
            for p in listed if p["id"] in explicit and p["space"] != profiles.HOME and p["emails"]]


def _actor(actor, listed):
    found = next((p for p in listed if p["id"] == getattr(actor, "id", None)), None)
    if not found or found["space"] != profiles.HOME or found["role"] != "admin" \
            or actor.source != "web" or actor.via not in db.VIAS:
        raise InvalidProfileEdit("Only a signed-in home admin can change member settings.")


def _replace(raw, listed, member_id, old, new):
    if member_id not in {p["id"] for p in _members(raw, listed)}:
        raise InvalidProfileEdit("Choose an existing member with their own space.")
    target = next(p for p in raw["profiles"] if p["id"] == member_id)
    values = target.get("emails")
    aliases = [values] if isinstance(values, str) else values
    if not isinstance(aliases, list) or any(not isinstance(value, str) for value in aliases):
        raise InvalidProfileEdit("Fix this member's email list locally before editing it.")
    keys = [_email(value) for value in aliases]
    if len(keys) != len(set(keys)) or keys.count(old) != 1:
        raise StaleProfileEdit("That email is no longer listed exactly once. Reload this panel.")
    if new != old and any(new in p["emails"] for p in listed):
        raise InvalidProfileEdit("That email is already listed. Choose an address that belongs to only this member.")
    changed = copy.deepcopy(raw)
    entry = next(p for p in changed["profiles"] if p["id"] == member_id)
    replaced = [new if key == old else value for key, value in zip(keys, aliases)]
    entry["emails"] = replaced[0] if isinstance(values, str) else replaced
    return changed


def _result(raw, listed, member_id, old, new, config_sha, membership_sha, change_id, *, saved):
    member = next(p for p in _members(raw, listed) if p["id"] == member_id)
    return {"saved": saved, "noop": not saved, "member": member,
            "replaced": {"old_email": old, "new_email": new}, "config_sha256": config_sha,
            "membership_sha256": membership_sha, "change_set_id": change_id,
            "access_policy_required": True}


def _audit_outcome(cur, journal):
    row = cur.execute("select actor, source, message, via from audit.change_set where id = %s",
                      (journal["change_set_id"],)).fetchone()
    if row is None:
        return False
    if row != (journal["actor"], "web", "Change member email\nMember email operation: " + journal["operation"],
               journal["via"]):
        raise PendingProfileEdit(files.PENDING)
    changes = cur.execute("select table_name, op, row_key, before, after from audit.row_change "
                          "where change_set_id = %s order by id", (journal["change_set_id"],)).fetchall()
    pid, old, new = journal["member_id"], journal["old_email"], journal["new_email"]
    old_row, new_row = {"profile_id": pid, "email": old}, {"profile_id": pid, "email": new}
    if changes != [("profile_email", "DELETE", old_row, old_row, None),
                   ("profile_email", "INSERT", new_row, None, new_row)]:
        raise PendingProfileEdit(files.PENDING)
    return True


def _recover_locked(*, dbname=None, fault=None):
    if not files.pending():
        return None
    journal = files.load_journal()
    try:
        if journal["database"] != _database(dbname):
            raise PendingProfileEdit(files.PENDING)
        before = base64.b64decode(journal["before"], validate=True)
        after = base64.b64decode(journal["after"], validate=True)
        raw = files.parse(before)
        before_list, after_list = _listed(raw), _listed(files.parse(after))
        _actor(SimpleNamespace(id=journal["actor"], source="web", via=journal["via"]), before_list)
        old, new = _email(journal["old_email"]), _email(journal["new_email"])
        if old == new or old != journal["old_email"] or new != journal["new_email"] \
                or files.json_bytes(_replace(raw, before_list, journal["member_id"], old, new)) != after:
            raise PendingProfileEdit(files.PENDING)
        with db.connect("app", dbname=dbname, autocommit=True, options=OPTIONS) as c:
            with c.transaction():
                _locks(c)
                committed = _audit_outcome(c, journal)
                expected = after_list if committed else before_list
                receipt = _check(c, expected)
                # Keep membership/departure and all profile writers excluded until
                # the matching file is published and its pending gate is cleared.
                current, _ = files.snapshot()
                if committed:
                    if files.digest(current) == journal["before_sha256"]:
                        files.write_bytes(config.CONFIG_FILE, after)
                    elif files.digest(current) != journal["after_sha256"]:
                        raise PendingProfileEdit(files.PENDING)
                elif current != before:
                    raise PendingProfileEdit(files.PENDING)
                if fault and committed:
                    fault("published")
                files.complete()
        return {"committed": committed, "change_set_id": journal["change_set_id"] if committed else None,
                "membership_sha256": receipt}
    except (KeyError, TypeError, ValueError, OSError) as exc:
        if isinstance(exc, PendingProfileEdit):
            raise
        raise PendingProfileEdit(files.PENDING) from None


def recover(*, dbname=None):
    """Local upkeep only; config-backed sync invokes this before admitting profiles."""
    with files.claim(allow_pending=True):
        return _recover_locked(dbname=dbname)


def preview(*, actor, dbname=None):
    """Private preview rechecks its authenticated reader under the source claim."""
    with files.claim(allow_pending=True):
        _recover_locked(dbname=dbname)
        before, raw = files.snapshot()
        listed = _listed(raw)
        _actor(actor, listed)
        with db.connect("app", dbname=dbname, autocommit=True, options=OPTIONS) as c:
            with c.transaction():
                _locks(c)
                membership = _check(c, listed)
        return {"editable": True, "config_sha256": files.digest(before), "membership_sha256": membership,
                "members": _members(raw, listed)}


def apply(member_id, old_email, new_email, *, config_sha256, membership_sha256, actor, dbname=None, fault=None):
    """Replace exactly one alias, never replay an uncertain prior operation.

    fault is a disposable-test hook. BaseException leaves durable pending state
    to simulate process death; ordinary exceptions attempt exact-outcome recovery.
    """
    expected_config, expected_members = _receipt(config_sha256), _receipt(membership_sha256)
    old, new = _email(old_email), _email(new_email)
    with files.claim(allow_pending=True):
        if files.pending():
            _recover_locked(dbname=dbname)
            raise StaleProfileEdit(STALE)
        before, raw = files.snapshot()
        listed = _listed(raw)
        _actor(actor, listed)
        if files.digest(before) != expected_config:
            raise StaleProfileEdit(STALE)
        changed = _replace(raw, listed, member_id, old, new)
        after_list = _listed(changed)
        after = before if old == new else files.json_bytes(changed)
        if len(after) > files.MAX_CONFIG:
            raise InvalidProfileEdit("Member configuration is too large to save here. Edit it locally instead.")
        journal = None
        try:
            with db.connect("app", dbname=dbname, autocommit=True, options=OPTIONS) as c:
                with c.transaction():
                    _locks(c)
                    membership = _check(c, listed, expected_members)
                if old == new:
                    return _result(raw, listed, member_id, old, new, expected_config, membership, None, saved=False)
                operation = uuid.uuid4().hex
                message = "Change member email\nMember email operation: " + operation
                with db.change(actor.id, "web", message, via=actor.via, conn=c) as (cur, change_id):
                    _locks(cur)
                    _check(cur, listed, expected_members)
                    if files.snapshot()[0] != before:
                        raise StaleProfileEdit(STALE)
                    journal = {"version": 1, "config_path": str(files.ordinary(config.CONFIG_FILE)),
                               "operation": operation, "database": _database(dbname), "actor": actor.id,
                               "via": actor.via, "member_id": member_id, "old_email": old, "new_email": new,
                               "change_set_id": change_id, "before": base64.b64encode(before).decode("ascii"),
                               "after": base64.b64encode(after).decode("ascii"),
                               "before_sha256": expected_config, "after_sha256": files.digest(after)}
                    files.prepare(journal)
                    if fault:
                        fault("prepared")
                    cur.execute("delete from profile_email where profile_id = %s and email = %s", (member_id, old))
                    if cur.rowcount != 1:
                        raise StaleProfileEdit(STALE)
                    cur.execute("insert into profile_email (profile_id,email) values (%s,%s)", (member_id, new))
                    membership = _check(cur, after_list)
                    if fault:
                        fault("sql_done")
                if fault:
                    fault("committed")
            # Re-read exact audited outcome and membership under fresh DB locks;
            # a writer in the commit/publication gap must not get a false receipt.
            outcome = _recover_locked(dbname=dbname, fault=fault)
            membership = outcome["membership_sha256"]
        except Exception:
            if journal is not None and files.pending():
                try:
                    outcome = _recover_locked(dbname=dbname)
                except Exception:
                    raise PendingProfileEdit(files.PENDING) from None
                if outcome and outcome["committed"]:
                    return _result(changed, after_list, member_id, old, new, files.digest(after),
                                   outcome["membership_sha256"], journal["change_set_id"], saved=True)
            raise
        return _result(changed, after_list, member_id, old, new, files.digest(after), membership,
                       journal["change_set_id"], saved=True)
