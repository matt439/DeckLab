"""The in-memory store: the same interface and rules as pg.PgStore, kept in dicts, for the tests
(test_api's Sandbox installs one per test) and anything else that runs without PostgreSQL.

It keeps an audit trail too: one change set per write that changes something, each with rows
shaped exactly as audit.row_change records them (to_jsonb of the table rows of migration 0003:
wishlist_entry's set_code and collector_number None for no printing, and so on), so the
Activity page's filtering can be tested without a database. tests/test_state_contract.py runs
the same tests on both stores, including that the same writes give the same activity().

One lock makes it thread-safe. Set `down = True` to make every call raise state.Unavailable,
as PgStore does with PostgreSQL stopped (settings_cached() and simulation_mode_cached() still
answer, with what's saved: the last good values PgStore would keep).
"""
import copy
import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import Conflict, Invalid, Unavailable, rules, visibility

DOWN_MESSAGE = "the database isn't reachable (MemoryStore.down is set)"


def _copy(value):
    return copy.deepcopy(value)


def _jsonb(value):
    """value as jsonb would give it back (tuples as lists and so on)."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _entry_row(profile_id, position, entry):
    return {"profile_id": profile_id, "position": position, "name": entry["name"],
            "set_code": entry["set"] or None, "collector_number": entry["number"] or None,
            "notes": entry["notes"], "source": entry["source"]}


def _entry(row):
    return {"name": row["name"], "set": row["set_code"] or "", "number": row["collector_number"] or "",
            "notes": row["notes"], "source": row["source"]}


class MemoryStore:
    """The state store in memory (see the module docstring, and decklab.lib.state for the
    interface; pg.PgStore's docstrings say what each method does).

    mode: the simulations mode it starts with ("everyone" by default, which the tests want so
    any profile may start runs), set without a change set and by nobody (by and since None);
    None starts with none set, so the real default applies."""

    def __init__(self, mode="everyone"):
        self._lock = threading.RLock()
        self.down = False
        self._wishlists = {}        # profile id -> [wishlist_entry rows] in position order
        self._settings = {}         # profile id -> {key: value}
        self._mode = None           # the simulation_mode row, or None
        self._seeded_mode = None    # MemoryStore(mode=...)'s, shown until a write replaces it
        self._play = {}             # (kind, id) -> play_record row
        self._packing = set()       # checked physical-task hashes, shared by the home
        self._commander_night = None  # singleton row, kept with a revision when notes are cleared
        self._visibility = {}       # (owner, thing) -> Public row; no row means Private
        self._visibility_last = {}
        self._visibility_when = None
        self._clock = time.monotonic
        self._changes = []          # the audit trail, oldest first
        self._batch = None          # the open batch()'s rows, or None
        if mode is not None:
            self._seeded_mode = {"mode": rules.mode(mode), "by": None, "by_id": None, "since": None}

    # ------------------------------------------------------------------ plumbing

    def reachable(self):
        return not self.down

    def _check(self):
        if self.down:
            raise Unavailable(DOWN_MESSAGE)

    def _log(self, actor, message, reason, rows):
        """Record one change set (rows: [(table, op, key columns, before, after)]), or add the
        rows to the open batch's."""
        actor_id, message, reason = rules.check_write(actor, message, reason)
        out = []
        for table, op, key_columns, before, after in rows:
            record = after if after is not None else before
            out.append({"table": table, "op": op, "key": {k: record[k] for k in key_columns},
                        "before": _copy(before), "after": _copy(after)})
        if self._batch is not None:
            self._batch.extend(out)
        else:
            self._append(actor, actor_id, message, reason, out)

    def _append(self, actor, actor_id, message, reason, rows):
        self._changes.append({"id": len(self._changes) + 1, "at": datetime.now(timezone.utc).isoformat(),
                              "actor": actor_id, "source": actor.source, "via": actor.via,
                              "message": message, "reason": reason, "rows": rows})

    @contextmanager
    def batch(self, actor, message, reason=None):
        """PgStore.batch(): one change set for every write in the with block, all kept or (when
        it raises) all undone; none when nothing changed. The store's lock is held throughout,
        so other threads wait."""
        actor_id, message, reason = rules.check_write(actor, message, reason)
        with self._lock:
            self._check()
            if self._batch is not None:
                raise ValueError("a batch is already open in this thread (batches don't nest)")
            saved = _copy((self._wishlists, self._settings, self._mode, self._seeded_mode, self._play,
                           self._packing, self._commander_night, self._visibility,
                           self._visibility_last, self._visibility_when))
            self._batch = rows = []
            try:
                yield self
            except BaseException:
                (self._wishlists, self._settings, self._mode, self._seeded_mode, self._play,
                 self._packing, self._commander_night, self._visibility,
                 self._visibility_last, self._visibility_when) = saved
                raise
            finally:
                self._batch = None
            if rows:
                self._append(actor, actor_id, message, reason, rows)

    # ------------------------------------------------------------------ wishlists

    def seed_wishlist(self, profile_id, entries):
        """Replace the profile's wishlist with entries (checked like added ones, names unique by
        casefold), without a change set: a test's starting data."""
        pid = rules.profile_id(profile_id)
        checked = [rules.entry(e) for e in entries]
        if len({e["name"].casefold() for e in checked}) != len(checked):
            raise Invalid("card names must be unique")
        if len(checked) > rules.MAX_ENTRIES:
            raise Invalid(rules.FULL_MESSAGE)
        with self._lock:
            self._wishlists[pid] = [_entry_row(pid, i, e) for i, e in enumerate(checked)]

    def _entries(self, pid):
        return [_entry(row) for row in self._wishlists.get(pid, [])]

    def wishlist(self, profile_id):
        pid = rules.profile_id(profile_id)
        with self._lock:
            self._check()
            return self._entries(pid)

    def wishlist_add(self, profile_id, entry, actor, message, *, at=None, allow_orphan=False):
        pid = rules.profile_id(profile_id)
        new = rules.entry(entry)
        rules.check_write(actor, message)
        rules.wishlist_orphan(allow_orphan, actor)
        rules.insert_slot([], at)           # at's form, before anything is read
        with self._lock:
            self._check()
            rows = self._wishlists.setdefault(pid, [])
            if rules.add_plan(self._entries(pid), new) == "exists":
                return False, self._entries(pid)
            position, moves = rules.insert_slot([r["position"] for r in rows], at)
            changes = []
            for old, moved in moves:
                i = next(i for i, r in enumerate(rows) if r["position"] == old)
                before = rows[i]
                rows[i] = dict(before, position=moved)
                changes.append(("wishlist_entry", "UPDATE", ("profile_id", "position"), before, rows[i]))
            row = _entry_row(pid, position, new)
            rows.append(row)
            rows.sort(key=lambda r: r["position"])
            changes.append(("wishlist_entry", "INSERT", ("profile_id", "position"), None, row))
            self._log(actor, message, None, changes)
            return True, self._entries(pid)

    def wishlist_remove(self, profile_id, name, actor, message, reason=None, *, allow_orphan=False):
        pid = rules.profile_id(profile_id)
        rules.check_write(actor, message, reason)
        rules.wishlist_orphan(allow_orphan, actor)
        with self._lock:
            self._check()
            rows = self._wishlists.get(pid, [])
            i = rules.find(self._entries(pid), name)
            if i is None:
                return False, self._entries(pid)
            row = rows.pop(i)
            self._log(actor, message, reason, [("wishlist_entry", "DELETE", ("profile_id", "position"), row, None)])
            return True, self._entries(pid)

    def wishlist_set(self, profile_id, name, actor, message, *, notes=None, source=None, set=None,
                     number=None, allow_orphan=False):
        pid = rules.profile_id(profile_id)
        rules.check_write(actor, message)
        rules.wishlist_orphan(allow_orphan, actor)
        with self._lock:
            self._check()
            rows = self._wishlists.get(pid, [])
            entries = self._entries(pid)
            i = rules.find(entries, name)
            if i is None:
                raise Invalid(f"{name} isn't on the wishlist")
            new = rules.edited(entries[i], notes=notes, source=source, set=set, number=number)
            if new == entries[i]:
                return False, entries
            before = rows[i]
            rows[i] = _entry_row(pid, before["position"], dict(new, name=before["name"]))
            self._log(actor, message, None, [("wishlist_entry", "UPDATE", ("profile_id", "position"),
                                              before, rows[i])])
            return True, self._entries(pid)

    # ------------------------------------------------------------------ settings

    def settings(self, profile_id):
        pid = rules.profile_id(profile_id)
        with self._lock:
            self._check()
            return dict(sorted(self._settings.get(pid, {}).items()))

    def settings_cached(self, profile_id):
        pid = rules.profile_id(profile_id)
        with self._lock:
            return dict(sorted(self._settings.get(pid, {}).items()))

    def settings_put(self, profile_id, values, actor, message):
        pid = rules.profile_id(profile_id)
        values = rules.setting_values(values)
        rules.check_write(actor, message)
        with self._lock:
            self._check()
            saved = dict(self._settings.get(pid, {}))
            rows = []
            for key, value in values.items():
                row = {"profile_id": pid, "key": key}
                if value is None:
                    if key in saved:
                        rows.append(("profile_setting", "DELETE", ("profile_id", "key"),
                                     dict(row, value=saved.pop(key)), None))
                elif key not in saved:
                    saved[key] = value
                    rows.append(("profile_setting", "INSERT", ("profile_id", "key"), None, dict(row, value=value)))
                elif saved[key] != value:
                    rows.append(("profile_setting", "UPDATE", ("profile_id", "key"),
                                 dict(row, value=saved[key]), dict(row, value=value)))
                    saved[key] = value
            if rows:
                self._settings[pid] = saved
                self._log(actor, message, None, rows)
            return dict(sorted(saved.items()))

    # ------------------------------------------------------------------ shared packing progress

    def packing_ticks(self, ids):
        ids = rules.packing_ids(ids)
        with self._lock:
            self._check()
            return [key for key in ids if key in self._packing]

    def packing_ticks_put(self, changes, actor, message, *, ids=None):
        changes = rules.packing_changes(changes)
        ids = rules.packing_ids(list(changes) if ids is None else ids)
        if not set(changes) <= set(ids):
            raise Invalid("Packing changes must name tasks in the requested scope")
        rules.check_write(actor, message)
        with self._lock:
            self._check()
            rows = []
            for key, done in changes.items():
                if done and key not in self._packing:
                    self._packing.add(key)
                    rows.append(("packing_tick", "INSERT", ("id",), None, {"id": key}))
                elif not done and key in self._packing:
                    self._packing.remove(key)
                    rows.append(("packing_tick", "DELETE", ("id",), {"id": key}, None))
            if rows:
                self._log(actor, message, None, rows)
            return [key for key in ids if key in self._packing]

    # ------------------------------------------------------------------ the household's Commander night

    def commander_night(self):
        """The optional household note and its revision, including a cleared tombstone."""
        with self._lock:
            self._check()
            row = self._commander_night
            return {"revision": row["revision"], "night": _copy(row["content"])} if row else {"revision": 0, "night": None}

    def commander_night_put(self, night, expected_revision, actor, message, *, reason=None):
        from . import commander_night as notes
        night, expected_revision = notes.normalize(night), notes.expectation(expected_revision)
        if night is None:
            reason = notes.clear_reason(reason)
        rules.check_write(actor, message, reason)
        with self._lock:
            self._check()
            before = self._commander_night
            revision = before["revision"] if before else 0
            if revision != expected_revision:
                raise Conflict(notes.CHANGED)
            if (before["content"] if before else None) == night:
                return self.commander_night()
            after = {"id": True, "revision": revision + 1, "content": _copy(night)}
            self._commander_night = after
            self._log(actor, message, reason, [("commander_night", "UPDATE" if before else "INSERT",
                                               ("id",), before, after)])
            return self.commander_night()

    # ------------------------------------------------------------------ the simulations mode

    @staticmethod
    def _mode_view(row):
        return {"mode": row["mode"], "by": row["set_by_name"], "by_id": row["set_by"],
                "since": row["_since"].astimezone().isoformat(timespec="seconds")}

    def simulation_mode(self):
        with self._lock:
            self._check()
            if self._mode is not None:
                return self._mode_view(self._mode)
            return _copy(self._seeded_mode)

    def simulation_mode_cached(self):
        with self._lock:
            return self._mode_view(self._mode) if self._mode is not None else _copy(self._seeded_mode)

    def simulation_mode_set(self, mode, actor, message, *, since=None, by_name=None):
        mode = rules.mode(mode)
        rules.check_write(actor, message)
        when = rules.since(since) or datetime.now(timezone.utc)
        set_by, set_by_name = (None, rules.by_name(by_name)) if by_name is not None else (actor.id.strip(), actor.name)
        with self._lock:
            self._check()
            before = self._mode
            row = {"id": True, "mode": mode, "set_by": set_by, "set_by_name": set_by_name,
                   "since": rules.jsonb_time(when), "_since": when}
            self._mode = row
            public = lambda r: {k: v for k, v in r.items() if not k.startswith("_")} if r else None   # noqa: E731
            self._log(actor, message, None, [("simulation_mode", "UPDATE" if before else "INSERT", ("id",),
                                              public(before), public(row))])
            return self._mode_view(row)

    # ------------------------------------------------------------------ visibility switches

    def _visibility_view(self):
        return visibility.view((r["owner"], r["thing"], r["set_by"], r["set_by_name"],
                                r["_since"].astimezone().isoformat(timespec="seconds"))
                               for _, r in sorted(self._visibility.items()))

    def _visibility_keep(self):
        value = self._visibility_view()
        self._visibility_last = _copy(value)
        self._visibility_when = self._clock()
        return value

    def visibility(self):
        with self._lock:
            self._check()
            return self._visibility_keep()

    def visibility_cached(self):
        from .pg import CACHE_SECONDS
        with self._lock:
            if self._visibility_when is None or self._clock() - self._visibility_when >= CACHE_SECONDS:
                return {}
            return _copy(self._visibility_last)

    def visibility_set(self, owner, thing, on, actor, message):
        pair = visibility.switch(owner, thing, on)
        rules.check_write(actor, message)
        with self._lock:
            self._check()
            before = self._visibility.get(pair)
            if bool(before) == on:
                return self._visibility_keep()
            when = datetime.now(timezone.utc)
            row = {"owner": owner, "thing": thing, "set_by": actor.id.strip(), "set_by_name": actor.name,
                   "since": rules.jsonb_time(when), "_since": when} if on else None
            if on:
                self._visibility[pair] = row
            else:
                del self._visibility[pair]
            public = lambda r: {k: v for k, v in r.items() if not k.startswith("_")} if r else None
            self._log(actor, message, None, [("visibility", "INSERT" if on else "DELETE", ("owner", "thing"),
                                              public(before), public(row))])
            return self._visibility_keep()

    # ------------------------------------------------------------------ play records

    @staticmethod
    def _record(row):
        return rules.rebuild({"version": 1, "id": row["id"], "kind": row["kind"], "revision": row["revision"],
                              "created_on": row["created_on"], "updated_on": row["updated_on"],
                              "updated_by": row["updated_by"]}, _copy(row["content"]))

    def play_get(self, kind, record_id):
        kind, record_id = rules.play_kind(kind), rules.play_id(record_id)
        with self._lock:
            self._check()
            row = self._play.get((kind, record_id))
            return self._record(row) if row else None

    def play_list(self, kind):
        kind = rules.play_kind(kind)
        with self._lock:
            self._check()
            return [self._record(self._play[key]) for key in sorted(k for k in self._play if k[0] == kind)]

    def play_put(self, kind, record, expected_sha, actor, message):
        kind = rules.play_kind(kind)
        header, content, deck_ids = rules.split_record(kind, record)
        rules.check_write(actor, message)
        with self._lock:
            self._check()
            key = (kind, header["id"])
            before = self._play.get(key)
            stored = rules.record_sha(self._record(before)) if before else None
            if stored != expected_sha:
                raise Conflict(rules.CHANGED_MESSAGE)
            row = {"kind": kind, "id": header["id"], "revision": header["revision"],
                   "created_on": header["created_on"], "updated_on": header["updated_on"],
                   "updated_by": header["updated_by"], "deck_ids": list(deck_ids), "content": _jsonb(content)}
            self._play[key] = row
            self._log(actor, message, None, [("play_record", "UPDATE" if before else "INSERT", ("kind", "id"),
                                              before, row)])
            return self._record(row)

    # ------------------------------------------------------------------ the audit trail

    def activity(self, before=None, limit=50, *, visible=None, inventory=None):
        before, limit = rules.page_args(before, limit)
        spec = rules.inventory_scope(inventory)

        def fetch(cursor, n):
            newer = [c for c in reversed(self._changes) if cursor is None or c["id"] < cursor]
            found = [_copy(c) for c in newer[:n]]
            return found if spec is None else [rules.inventory_rows(c, spec) for c in found]
        with self._lock:
            self._check()
            return rules.activity_page(fetch, before, limit, visible)

    def changes(self):
        """The whole audit trail, oldest first (copies): for tests."""
        with self._lock:
            return _copy(self._changes)
