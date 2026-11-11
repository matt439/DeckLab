"""Bounded connection-failure categories, never raw exception text for a page or doctor.

SQLSTATEs are preferred. libpq may supply no SQLSTATE during connection startup,
so only recognized authentication/refusal/timeout phrases classify those errors.
Unknown failures stay unknown; they do not prove PostgreSQL is down.
"""
import errno
import sys

REASONS = frozenset({"network", "authentication", "setup", "driver", "unknown"})


def connection_reason(error):
    """A fixed category from a driver error or its bounded exception chain."""
    seen = set()
    for _ in range(4):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        try:
            reason = getattr(error, "reason", None)
            if isinstance(reason, str) and reason in REASONS and reason != "unknown":
                return reason
            state = getattr(error, "sqlstate", None)
            if state in ("28P01", "28000"):
                return "authentication"
            if state == "3D000":
                return "setup"
            if isinstance(error, (ConnectionRefusedError, TimeoutError)) or getattr(error, "errno", None) in (
                    errno.ECONNREFUSED, errno.ETIMEDOUT, 10060, 10061):
                return "network"
            text = str(error)[:8192].casefold()
            if any(part in text for part in ("password authentication failed", "no password supplied",
                    "peer authentication failed", "ident authentication failed", "no pg_hba.conf entry")):
                return "authentication"
            if "does not exist" in text and ("database " in text or "role " in text):
                return "setup"
            if any(part in text for part in ("connection refused", "connection timeout expired",
                                             "timeout expired", "actively refused")):
                return "network"
            error = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
        except Exception:
            break
    return "unknown"


def runtime_problem(version=None):
    major, minor = (sys.version_info if version is None else version)[:2]
    if (major, minor) != (3, 14):
        return f"Python {major}.{minor} is running; Deck Lab requires Python 3.14. Use SELF-HOSTING.md step 1."
    return None
