"""Audit-shaped MemoryStore test adapter; production MemoryStore stays unchanged."""
import copy

from decklab.lib import state
from decklab.lib.state import wishlist_undo as undo
from decklab.lib.state.memory import MemoryStore


class AuditWishlistMemory(MemoryStore):
    def __init__(self):
        super().__init__()
        self._audit_ids, self._row_seq = {}, 0
        self.calls = []
        self.lose_reply = False
        self.fail_receipt = False
        self.inactive = set()

    def _append(self, actor, actor_id, message, reason, rows):
        super()._append(actor, actor_id, message, reason, rows)
        for index in range(len(rows)):
            self._row_seq += 1
            self._audit_ids[(self._changes[-1]["id"], index)] = self._row_seq

    def raw_source(self, change_id):
        found = next((change for change in self._changes if change["id"] == change_id), None)
        return [] if found is None else [{**copy.deepcopy(row), "id": self._audit_ids[(change_id, index)]}
                                        for index, row in enumerate(found["rows"][:2])]

    def latest(self, pid, position=None):
        ids = []
        for change in self._changes:
            for index, row in enumerate(change["rows"]):
                if row["table"] == "wishlist_entry" and any(isinstance(side, dict) and side.get("profile_id") == pid
                    and (position is None or side.get("position") == position) for side in (row["key"], row["before"], row["after"])):
                    ids.append(self._audit_ids[(change["id"], index)])
        return max(ids, default=None)

    def raw_entries(self, pid):
        return copy.deepcopy(self._wishlists.get(pid, []))

    def _undo_plan(self, change_id, pid):
        if self._batch is not None:
            raise undo.UndoUnsupported("Independent change required")
        if pid in self.inactive:
            raise undo.UndoMissing()
        raw = self.raw_source(change_id)
        target = (raw[0].get("after") or raw[0].get("before")) if len(raw) == 1 else None
        position = target.get("position") if isinstance(target, dict) else None
        return undo.review(change_id, pid, raw, self.raw_entries(pid), self.latest(pid, position), self.latest(pid))

    def wishlist_undo_review(self, change_id, pid):
        with self._lock:
            self._check()
            self.calls.append(("review", change_id, pid))
            return self._undo_plan(change_id, pid)

    def wishlist_undo_apply(self, change_id, pid, expect, actor, message):
        with self._lock:
            self._check()
            self.calls.append(("apply", change_id, pid, expect, actor))
            if actor.id != pid or actor.source != "web":
                raise undo.UndoMissing()
            plan = self._undo_plan(change_id, pid)
            if not isinstance(expect, str) or not undo.SHA.fullmatch(expect):
                raise undo.UndoUnsupported("Review required")
            if expect != plan["expect"]:
                raise undo.UndoConflict()
            saved = copy.deepcopy((self._wishlists, self._changes, self._audit_ids))
            try:
                if plan["action"] == "wishlist_add":
                    changed, _ = self.wishlist_add(pid, plan["restored"], actor, message, at=plan["insert_at"])
                elif plan["action"] == "wishlist_remove":
                    changed, _ = self.wishlist_remove(pid, plan["current"]["name"], actor, message)
                else:
                    changed, _ = self.wishlist_set(pid, plan["current"]["name"], actor, message,
                                                   set=plan["restored"]["set"], number=plan["restored"]["number"],
                                                   notes=plan["restored"]["notes"], source=plan["restored"]["source"])
                if not changed:
                    raise undo.UndoConflict()
                result = undo.receipt(plan, self.raw_entries(pid), self.raw_source(self._changes[-1]["id"]), self.latest(pid))
                if self.fail_receipt:
                    raise undo.UndoConflict()
            except Exception:
                self._wishlists, self._changes, self._audit_ids = saved
                raise
            if self.lose_reply:
                raise state.Unavailable("Synthetic committed reply loss")
            return {"review": plan, **result}


def seed(store, pid="matt"):
    actor = state.Actor(pid, "Matt" if pid == "matt" else pid.title(), via="tunnel")
    store.seed_wishlist(pid, [{"name": "Opt", "set": "", "number": "", "notes": "  Former note\r\nsecond line\t  ",
                                "source": "  magic/reports/example.md  "},
                               {"name": "Forest", "set": "", "number": "", "notes": "Other card", "source": ""}])
    store.wishlist_set(pid, "Opt", actor, "Fixture changed wishlist", notes="Changed note", source="magic/new.md")
    return store.changes()[-1]["id"]
