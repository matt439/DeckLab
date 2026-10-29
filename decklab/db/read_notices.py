"""Advisory CLI privacy labels; access, actors and stdout stay unchanged.

Each Reporter belongs to one command. Its new PgStore has no earlier Public
cache, and a failed read never falls back to a shared or cached snapshot.
"""
import sys

from decklab.lib.state import pg, visibility as rules


def _owner(value):
    return value if isinstance(value, str) and rules.OWNER.fullmatch(value) else "unknown"


def _say(text):
    stream = sys.stderr
    if stream is None:
        return                          # print(file=None) would contaminate stdout
    try:
        print("Privacy: " + text, file=stream)
    except (OSError, UnicodeError, ValueError):
        pass                            # a best-effort notice cannot fail a successful read


def wishlist(owner):
    _say(f"wishlist is Private to owner {_owner(owner)}. Do not relay its contents outside that owner.")


class Reporter:
    def __init__(self, dbname=None):
        self.dbname = dbname
        self._loaded = False
        self._public = None

    def _read(self):
        if not self._loaded:
            self._loaded = True
            try:
                found = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker()).visibility()
                self._public = found if isinstance(found, dict) else None
            except Exception:           # noqa: BLE001 - fixed conservative wording only
                self._public = None
        return self._public

    def _status(self, owner, thing):
        try:
            pair = rules.key(owner, thing)
            from decklab.lib import spaces, visibility
            if thing not in visibility.READY_THINGS:
                return "unknown"
            found = self._read()
            if found is None:
                return "unknown"
            if pair not in found:
                return "private"
            # A stored orphan switch cannot publish a removed space.
            if thing in rules.SPACE_THINGS and not spaces.exists(owner):
                return "unknown"
            return "public"
        except Exception:               # noqa: BLE001 - no raw configuration or DB errors
            return "unknown"

    def space(self, thing, owner, *, label=None):
        subject = f"{label or thing} in space {_owner(owner)}"
        status = self._status(owner, thing)
        if status == "public":
            _say(f"{subject}: {thing} Public switch enabled for signed-in profiles, read-only, "
                 "when checked for this command.")
        elif status == "private":
            _say(f"{subject} is Private to that space. Do not relay it outside that space.")
        else:
            _say(f"{subject}: visibility could not be verified; treat this data as Private to that space.")

    def decks(self, owners):
        for owner in sorted(set(owners)):
            self.space("decks", owner)
        _say("the decks switch does not publish inventory-derived table status/errors or kit shown by a CLI read; "
             "keep those Private to their space or accessory owner.")

    def accessories(self, rows):
        for number, row in enumerate(rows, 1):
            owner = row.get("owner")
            subject = f"accessory row {number}, " + ("shared home kit" if owner == "shared"
                                                    else f"owner {_owner(owner)}")
            status = self._status(owner, "accessories")
            if status == "public":
                _say(f"{subject}: kit Public to signed-in profiles, read-only, when checked for this command.")
            elif status == "private":
                scope = "the shared home kit" if owner == "shared" else "that owner"
                _say(f"{subject}: Private to {scope}. Do not relay it outside that scope.")
            else:
                _say(f"{subject}: visibility could not be verified; treat this row as Private.")
