"""Pure qualification of a reviewed HOME field list from a coherent capture.

Syntax validation is not identity or freshness authority. The caller must obtain
the capture under its inventory claim and recompute before no-op and write alike.
Holding that claim alone does not refresh an older REPEATABLE READ snapshot: a
PostgreSQL writer must establish fresh visibility after any lock wait (for example
with the required READ COMMITTED capture), on the same write connection.
No configuration, inventory/store lookup, card index, Forge process or IO occurs.
"""
import re
from dataclasses import asdict

from decklab.lib import decks
from decklab.lib.forge import lists
from decklab.lib.inventory import deck_epoch

from . import Conflict, Invalid, Unavailable, field_policy

INVALID = "The reviewed field list is invalid."
CHANGED = "The reviewed field list changed. Review it again before saving."
UNAVAILABLE = "The current field list could not be confirmed."
INVALID_REASON = "The field change needs a valid reason of at most 1000 characters."
_KINDS = {"Constructed": "casual", "Commander": "commander"}
_PROOF_KEYS = frozenset({"epoch", "receipt", "version", "card_sha"})
_RECEIPT_KEYS = frozenset({"deck_id", "revision", "sha256"})


def _format_version(fmt, version):
    if (type(fmt) is not str or fmt not in _KINDS or type(version) is not str
            or version not in ("target", "owned")):
        raise Invalid(INVALID)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _rule(value, fmt):
    try:
        return field_policy.normalize({"v": 1, "format": fmt, "revision": 1,
                                       "rules": [value]})["rules"][0]
    except Invalid:
        raise Invalid(INVALID) from None


def proof(value, fmt):
    """Validate review syntax only and return a detached, minimal JSON proof."""
    if type(value) is not dict or value.keys() != _PROOF_KEYS:
        raise Invalid(INVALID)
    _format_version(fmt, value["version"])
    epoch = _rule({"epoch": value["epoch"], "mode": "rules"}, fmt)["epoch"]
    receipt = value["receipt"]
    if (type(receipt) is not dict or receipt.keys() != _RECEIPT_KEYS
            or not deck_epoch.home_id(receipt["deck_id"])
            or receipt["deck_id"].partition("/")[0] != _KINDS[fmt]
            or type(receipt["revision"]) is not int
            or not epoch["revision"] <= receipt["revision"] <= deck_epoch.MAX_HISTORY
            or not _sha(receipt["sha256"]) or not _sha(value["card_sha"])):
        raise Invalid(INVALID)
    return {"epoch": epoch,
            "receipt": {key: receipt[key] for key in ("deck_id", "revision", "sha256")},
            "version": value["version"], "card_sha": value["card_sha"]}


def intent(expected, rule, fmt):
    """Validate proof/rule consistency before IO; return two detached values.

    Exclude and Use rules still review one explicit list version, even though
    their saved policy rule intentionally contains no version or private reason.
    """
    wanted = proof(expected, fmt)
    desired = _rule(rule, fmt)
    if (desired["epoch"] != wanted["epoch"]
            or desired["mode"] == "include" and desired["version"] != wanted["version"]):
        raise Invalid(INVALID)
    return wanted, desired


def qualify(capture, version, fmt):
    """Derive a fresh epoch, exact text receipt and chosen playable-list hash.

    Unsupported or uncertain source evidence is unavailable, never a guessed
    identity. A target fenced block is required for both versions; Play-now also
    needs at least one card in a played section. Tables, pilots and prose are not
    hashed as cards, while the exact receipt binds all captured text separately.
    """
    _format_version(fmt, version)
    try:
        resolved = deck_epoch.resolve(capture)
        if resolved.status != "ready":
            raise Unavailable(UNAVAILABLE)
        deck_id = resolved.receipt.deck_id
        kind, _, slug = deck_id.partition("/")
        if kind != _KINDS[fmt]:
            raise Unavailable(UNAVAILABLE)
        parsed = decks.parse_deck(capture["current"]["text"].encode("utf-8"),
                                  slug=slug, kind=kind, space="home")
        if not parsed.has_decklist:
            raise Unavailable(UNAVAILABLE)
        sections = parsed.target if version == "target" else parsed.owned
        if version == "owned" and (not sections or not any(
                line.quantity > 0 for name in ("Commander", "Deck") for line in sections.get(name, []))):
            raise Unavailable(UNAVAILABLE)
        engine_kind = decks.engine_kind({"kind": parsed.kind})
        return proof({"epoch": asdict(resolved.epoch), "receipt": asdict(resolved.receipt),
                      "version": version, "card_sha": lists.card_sha(sections, engine_kind)}, fmt)
    except (Invalid, Unavailable, ValueError, TypeError, KeyError, AttributeError):
        # Private parse/source details are never an available qualification.
        raise Unavailable(UNAVAILABLE) from None


def recheck(capture, expected, rule, fmt):
    """Independently recompute the full reviewed proof before no-op or mutation.

    The storage caller checks its policy CAS first, then calls this even when its
    policy transition would be a no-op. No policy, source or audit is changed here.
    """
    wanted, _ = intent(expected, rule, fmt)
    fresh = qualify(capture, wanted["version"], fmt)
    if fresh != wanted:
        raise Conflict(CHANGED)
    return fresh


def exclusion_reason(value, mode):
    """Bound a private audit-only reason; Exclude requires one after stripping."""
    if type(mode) is not str or mode not in ("include", "exclude", "rules"):
        raise Invalid(INVALID_REASON)
    if value is None and mode != "exclude":
        return None
    if type(value) is not str:
        raise Invalid(INVALID_REASON)
    reason = value.strip()
    try:
        reason.encode("utf-8")
    except UnicodeError:
        raise Invalid(INVALID_REASON) from None
    if (len(reason) > 1000 or not reason and mode == "exclude"
            or any(ord(char) < 32 and char not in "\n\t" or ord(char) == 127 for char in value)):
        raise Invalid(INVALID_REASON)
    return reason or None
