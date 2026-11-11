"""Optional extra proof for loopback scripts off Linux; never exposed through page settings.

Linux keeps its existing same-user socket check. No setting means compatibility with the
existing loopback rule; opting in requires one exact secret header as well as the script flag.
"""
import hmac
import re
import sys

from decklab.lib.config_errors import InvalidConfig

HEADER = "X-Deck-Lab-Script-Secret"


def validate(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", value):
        raise InvalidConfig("config.json's script_secret must be null or 32-256 URL-safe letters, digits, - and _.")
    return value


def accepts(headers, expected, *, platform=None):
    """The additional header check only; callers still enforce loopback, listener and viewer."""
    if (sys.platform if platform is None else platform).startswith("linux") or expected is None:
        return True
    values = headers.get_all(HEADER) or []
    return len(values) == 1 and isinstance(values[0], str) and values[0].isascii() and hmac.compare_digest(values[0], expected)


def local_headers(base=None, *, settings=None, platform=None):
    """Headers for a trusted client's own loopback request, never an outside URL."""
    result = dict(base or {"X-Deck-Lab-Script": "1"})
    if not (sys.platform if platform is None else platform).startswith("linux"):
        if settings is None:
            from decklab.lib import config
            settings = config.load()
        secret = validate(settings.get("script_secret"))
        if secret is not None:
            result[HEADER] = secret
    return result
