"""Read-only busy preview for the local updater, with no private deck/actor names relayed."""
import http.client
import json
import re

from decklab.lib import config, profiles

TIMEOUT = 5
MAX_BYTES = 32 * 1024
UNVERIFIED = "Running work cannot be checked safely. Let runs finish, or use --force if interrupting them is intended."
PATTERNS = (
    (re.compile(r"([0-9]+) Forge matchups? playing or waiting\Z"), "Forge matchup"),
    (re.compile(r"([0-9]+) field runs? or variant tests?\Z"), "field run or variant test"),
    (re.compile(r"([0-9]+) practice-hand runs?\Z"), "practice-hand run"),
    (re.compile(r"([0-9]+) simulator checks? playing or waiting\Z"), "simulator check"),
)


class BusyUnverified(ValueError):
    def __init__(self):
        super().__init__(UNVERIFIED)


def busy_work(*, connection=None):
    """Use the existing named home-admin restart preview, not an anonymous privilege bypass."""
    conn = None
    try:
        settings = config.load()
        admin = next((person for person in profiles.read(settings) if person.get("role") == "admin"
                      and person.get("space", "home") == "home"), None)
        if admin is None:
            raise BusyUnverified()
        conn = (connection or http.client.HTTPConnection)("127.0.0.1", int(settings.get("port", 8642)), timeout=TIMEOUT)
        conn.request("GET", "/api/server/restart", headers={"Accept": "application/json", "X-Deck-Lab-Poll": "1",
                                                          "X-Deck-Lab-Viewer": admin["id"]})
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_BYTES:
            raise BusyUnverified()
        found = json.loads(raw)
        rows = found.get("busy") if isinstance(found, dict) else None
        if not isinstance(rows, list) or len(rows) > 4:
            raise BusyUnverified()
        out = []
        for row in rows:
            if not isinstance(row, str) or len(row) > 160:
                raise BusyUnverified()
            for pattern, label in PATTERNS:
                match = pattern.fullmatch(row)
                if match and 1 <= int(match[1]) <= 1_000_000:
                    count = int(match[1])
                    words = label if count == 1 else "field runs or variant tests" if label == "field run or variant test" else label + "s"
                    out.append(f"{count} {words}")
                    break
            else:
                raise BusyUnverified()
        return out
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        raise BusyUnverified() from None
    finally:
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
