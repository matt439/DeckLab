"""What every part of the API shares: ApiError, the server log, keeping
absolute paths out of answers, reading request bodies as strict JSON, the
limits and patterns that more than one part checks requests against, and
state_errors(), which turns the state store's errors into answers.

The other parts all log through common._log, never a copy of their own, so
a test that patches it here hears every one of them.
"""
import dataclasses
import json
import math
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from decklab.lib import config

MAX_BODY = 4096                             # bytes: the largest settings body accepted
MAX_EDIT_BODY = 256 * 1024                  # bytes: the largest editor body (two 100-card lists fit easily)

# Printings in image URLs: Scryfall's set codes are lowercase letters and
# digits, and collector numbers use letters, digits, "-" and a few symbols
# ("1★", "12†", "Φ3"); checked against the bulk data on 2026-09-29.
SET_RE = re.compile(r"[a-z0-9]{2,8}")
NUMBER_RE = re.compile(r"[\w★†-]{1,16}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# An absolute path left in a message (C:\..., C:/..., \\server\share\...), as
# it is or as repr() writes it with doubled backslashes; see _strip_paths.
_ABS_PATH_RE = re.compile(r"(?<![\w/])(?:[A-Za-z]:(?:\\{1,2}|/)|\\{2,4}[^\s'\"\\/]+\\{1,2})[^\s'\"]*")
# The same written the Unix way, as a hook run by Git for Windows' sh prints
# them (/c/Users/..., its temp folder as /tmp/...), WSL (/mnt/c/...), Cygwin
# (/cygdrive/c/...), Linux and macOS (/home/..., /Users/...). Only paths
# under these top folders count, so an API path in a message ("/api/deck/edit")
# stays as it is.
_POSIX_PATH_RE = re.compile(r"(?<![\w.~-])/(?:[A-Za-z]|mnt|cygdrive|home|Users|tmp|var|usr|opt|private|root|etc|srv"
                            r"|run|media|Volumes|nix|snap)(?=/[^\s'\"/])[^\s'\"]*")

MAX_QTY = 99                    # copies on one line
MAX_NAME = 150                  # characters in a card name
LINE_FINISHES = ("nonfoil", "foil", "etched")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class ApiError(Exception):
    """A request that can't be answered: status is the HTTP status to send.
    extra keys go into the answer next to "error" (e.g. blocks=[...])."""

    def __init__(self, status, message, **extra):
        message = _strip_paths(message)
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


DATABASE_DOWN = "Deck Lab's database isn't reachable right now. Try again in a minute."


@contextmanager
def state_errors():
    """Turn decklab.lib.state's errors raised in the block into answers: Unavailable into
    503 with reason "database" (the page shows an error box with Try again, never the card
    data's wait), Invalid into 400 and Conflict into 409, each with the store's words."""
    from decklab.lib import state
    try:
        yield
    except state.Unavailable:
        raise ApiError(503, DATABASE_DOWN, reason="database") from None
    except state.Invalid as e:
        raise ApiError(400, str(e)) from None
    except state.Conflict as e:
        raise ApiError(409, str(e)) from None


def _log(text):
    """Write a line to the server log (stderr, which pythonw doesn't have)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


def _strip_paths(text):
    """text with no absolute paths: one inside the repo becomes relative to
    it (magic/collection.csv), and any other is cut to its last part (the file
    name), so an answer never shows the Windows user name or folder layout."""
    if not isinstance(text, str):
        return text
    root = str(config.REPO)
    posix = config.REPO.as_posix()
    forms = {root, root.replace("\\", "\\\\"), posix}
    if re.match(r"[A-Za-z]:/", posix):          # C:/VSProjects/... as /c/..., /mnt/c/..., /cygdrive/c/...
        forms |= {f"{prefix}/{posix[0].lower()}{posix[2:]}" for prefix in ("", "/mnt", "/cygdrive")}
    for form in sorted(forms, key=len, reverse=True):
        text = re.sub(re.escape(form) + r"(?:\\{1,2}|/)", "", text, flags=re.IGNORECASE)
    last_part = lambda m: re.split(r"[\\/]+", m.group().rstrip("\\/"))[-1]      # noqa: E731
    return _POSIX_PATH_RE.sub(last_part, _ABS_PATH_RE.sub(last_part, text))


def _public(error):
    """An exception as text for an answer: an OSError as "<file>: <reason>",
    and no absolute path in either (see _strip_paths)."""
    if isinstance(error, OSError) and error.filename and error.strerror:
        return _strip_paths(f"{error.filename}: {error.strerror}")
    return _strip_paths(str(error) or type(error).__name__)


def _scrub(items):
    """A list of warnings with the paths taken out."""
    return [_strip_paths(item) for item in items]


def _unique_keys(pairs):
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        repeated = next(k for k in keys if keys.count(k) > 1)
        raise ValueError(f"{repeated!r} is given twice")
    return dict(pairs)


def _no_constants(name):
    raise ValueError(f"{name} isn't allowed")


JSON_DEPTH = 200                    # far more than any request needs; deeper is refused


def _depth_over(data, limit):
    """True when data's lists and objects nest more than limit deep (counted without recursion)."""
    stack = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (list, dict)):
            if depth > limit:
                return True
            stack.extend((v, depth + 1) for v in (value.values() if isinstance(value, dict) else value))
    return False


def _load_json(body, what):
    """body (bytes) as JSON, or ApiError 400 saying why not, with what
    ("The settings", "The request") as the subject. Besides bad UTF-8, bad
    JSON and a key given twice, it refuses JSON nested too deeply for Python
    to read and text holding a lone surrogate ("\\ud800" is valid JSON but
    not a character, so it could never be sent back or written to a file)."""
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_keys, parse_constant=_no_constants)
    except ValueError as e:          # bad UTF-8, bad JSON or a repeated key
        raise ApiError(400, f"{what} isn't valid JSON: {e}") from None
    except RecursionError:
        raise ApiError(400, f"{what} isn't valid JSON: it's nested too deeply") from None
    if _depth_over(data, JSON_DEPTH):
        # The same answer whatever stack this Python has: Linux's reads 20,000 deep where Windows' can't.
        raise ApiError(400, f"{what} isn't valid JSON: it's nested too deeply")
    try:
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, f"{what} has text that isn't valid Unicode (a lone surrogate such as \\ud800)") from None
    except RecursionError:
        raise ApiError(400, f"{what} isn't valid JSON: it's nested too deeply") from None
    return data


def _jsonable(value):
    """value with tuples as lists, sets as sorted lists and dataclasses as dicts."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(v) for v in value), key=str)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _unique(items):
    return list(dict.fromkeys(items))


def _lazy(fn):
    """A function that calls fn once, when first asked, and remembers the answer."""
    kept = []

    def get():
        if not kept:
            kept.append(fn())
        return kept[0]
    return get


def _parse_body(body, limit=MAX_EDIT_BODY):
    """A request body as a JSON object; ApiError 413 or 400 otherwise."""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if len(body) > limit:
        raise ApiError(413, f"The request body is limited to {limit} bytes")
    data = _load_json(body, "The request")
    if not isinstance(data, dict):
        raise ApiError(400, "The request must be a JSON object")
    return data


def _keys(data, required, optional=()):
    """ApiError 400 unless data has every required key and nothing else but optional ones."""
    missing = [key for key in required if key not in data]
    if missing:
        raise ApiError(400, f"The request needs {', '.join(missing)}")
    unknown = sorted(set(data) - set(required) - set(optional))
    if unknown:
        raise ApiError(400, f"Unknown key {unknown[0]!r}; this request takes: "
                            f"{', '.join([*required, *optional])}")


def _sha(value):
    if not (isinstance(value, str) and _SHA_RE.fullmatch(value)):
        raise ApiError(400, "sha256 must be the 64-character hash /api/deck/edit gave")
    return value


def _flag(data, key):
    """An optional true/false in a request (False when it's left out); ApiError 400 for anything else."""
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise ApiError(400, f"{key} must be true or false")
    return value
