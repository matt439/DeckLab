"""Saved physical stand-in choices, separate from the deck's logical card lists."""
from collections import Counter
import csv
from dataclasses import replace

from decklab.lib import cards, decks, inventory, pool, spaces
from decklab.lib.decks import standins

from . import common, guard
from .card_lookup import _line_json
from .carddata import _require_cards
from .commits import _conflict, _deck_file, _parse_file, _stored
from .common import ApiError, _keys, _parse_body, _public, _scrub
from .library import _find_summary
from .saving import _deck_refused, apply_op
from .settings import _writer


def project(deck, version):
    """Presentation-only mappings and desired-card pictures; never alter the logical list."""
    answer = standins.project(deck, version)
    sections = deck.target if version == "target" else deck.owned
    pictured = {}
    for section, lines in (sections or {}).items():
        for line in lines:
            pictured.setdefault(line.name, (section, line))
    rows = []
    for row in answer["rows"]:
        shown = dict(row, card=None)
        match = pictured.get(row["for"])
        if match is not None:
            section, line = match
            try:
                shown["card"] = _line_json(replace(line, quantity=row["qty"]), section, [])["card"]
            except Exception:       # a missing picture must not hide a valid saved mapping
                pass
        rows.append(shown)
    return dict(answer, rows=rows, warnings=_scrub(answer["warnings"]))


def _canonical(rows):
    """Names sent by a picker must still be exact names from the current card index."""
    for row in rows:
        for key in ("for", "using"):
            name = row[key]
            if name is not None and cards.resolve(name) != name:
                raise ApiError(400, f"Choose the exact card name for {name!r}.")


def _available(deck, rows):
    needed = Counter()
    for row in rows:
        if row["using"] is not None:
            needed[row["using"]] += row["qty"]
    if not needed:
        return
    try:
        p = pool.load_pool(deck.space)
    except (ValueError, OSError) as error:
        raise ApiError(409, f"The stand-in cards can't be checked: {_public(error)}") from None
    own = pool.self_ids(deck.deck_id)
    for name, qty in needed.items():
        incoming = sum(count for _, count in p.on_the_way.get(name, []))
        elsewhere = sum(holder.cards[name] for holder in p.in_use if holder.id not in own)
        free = max(0, p.owned[name] - incoming - elsewhere)
        if qty > free:
            raise ApiError(409, f"{name} has only {free} physically owned copies free for this deck; "
                                f"choose another stand-in or Any spare card.")


def _plan_available(deck, version, rows, selected, fingerprint, profile):
    """Check against a reviewed packing plan's real-card allocation, including selected returns."""
    from . import assembly
    from .assembly_completion import CHANGED

    if deck.space != spaces.HOME:
        raise ApiError(400, "A packing-plan context is only for the home decks.")
    guard.require_sees_home_records(profile)
    try:
        plan = assembly._preview(selected, profile=profile)
    except (ValueError, OSError, csv.Error) as error:
        raise ApiError(409, f"The assembly plan couldn't be read: {_public(error)}") from None
    if fingerprint != plan["completion"]["fingerprint"]:
        raise ApiError(409, CHANGED)
    matching = [item for item in plan["decks"] if item["id"] == deck.deck_id and item["version"] == version]
    if len(matching) != 1:
        raise ApiError(400, "Select this deck and list version exactly once in the packing plan.")
    target = matching[0]
    free = Counter({item["name"]: item["free"] for item in target["standins"]["candidates"]})
    for item in plan["decks"]:
        if item is target:
            continue
        for row in item["standins"]["rows"]:
            if row["using"] is not None:
                free[row["using"]] -= row["qty"]
    needed = Counter()
    for row in rows:
        if row["using"] is not None:
            needed[row["using"]] += row["qty"]
    for name, qty in needed.items():
        available = max(0, free[name])
        if qty > available:
            raise ApiError(409, f"{name} has only {available} physically owned copies free in this packing plan; "
                                f"choose another stand-in or Any spare card.")
    snapshot = inventory.current()
    return snapshot.revision, snapshot.decks_revision


class _ContextSave:
    """A metadata-only deck.save whose reviewed whole-plan context must still be current."""
    kind = "deck.save"

    def __init__(self, operation, revision):
        self.params, self.revision = operation.params, revision

    def run(self, snapshot):
        from .assembly_completion import CHANGED
        if (snapshot.revision, snapshot.decks_revision) != self.revision:
            raise inventory.Conflict(CHANGED)
        return inventory.Op(self.kind, self.params).run(snapshot)


def save_standins(body):
    """Save one version's choices; optional decks+fingerprint validate selected packing returns."""
    data = _parse_body(body)
    profile = _writer(data)
    _keys(data, ("profile", "id", "version", "sha256", "rows"), ("decks", "fingerprint"))
    with common.state_errors(), inventory.pinned():
        from .deck_aliases import reject_alias
        reject_alias(data["id"], profile)
        kind, slug, path = _deck_file(data["id"])
        summary = _find_summary(data["id"])
        guard.require_sees_deck(summary, profile, deck_id=data["id"])
        stored = _stored(summary["id"], viewer=profile)
        deck = _parse_file(stored.data, kind, slug, path, summary["id"])
        guard.require(profile, "deck.edit", deck)
        guard.require_sees_inventory(deck.space, profile)
        contextual = "decks" in data
        if contextual != ("fingerprint" in data):
            raise ApiError(400, "Send decks and fingerprint together for a packing-plan context.")
        if not isinstance(data["sha256"], str) or not common._SHA_RE.fullmatch(data["sha256"]):
            raise ApiError(400, "sha256 must be the deck's 64-character text hash")
        if data["sha256"] != stored.sha256:
            raise _conflict(summary["id"], deck.title, viewer=profile)
        version = data["version"]
        if version not in standins.VERSIONS:
            raise ApiError(400, "version must be target or owned")
        sections = deck.target if version == "target" else deck.owned
        if sections is None or (version == "target" and not deck.has_decklist):
            raise ApiError(404, f"{deck.title} has no {version} list")
        try:
            rows = standins.validate_rows(data["rows"], sections)
        except ValueError as error:
            raise ApiError(400, _public(error)) from None
        _require_cards()
        _canonical(rows)
        revision = _plan_available(deck, version, rows, data["decks"], data["fingerprint"], profile) \
            if contextual else None
        if not contextual:
            _available(deck, rows)
        try:
            standins.set_choices(deck, version, rows)
            text = decks.render_deck_file(deck)
        except ValueError as error:
            raise ApiError(400, f"The stand-ins can't be written: {_public(error)}") from None
        saved = text != stored.text
        if saved:
            operation = inventory.Op("deck.save", {"deck_id": summary["id"], "text": text,
                                                   "base_sha256": stored.sha256})
            if contextual:
                operation = _ContextSave(operation, revision)
            after, _ = apply_op(operation, profile, f"choose the stand-ins for {deck.title}",
                                _deck_refused(summary["id"], deck.title, profile))
            held = after.deck(summary["id"])
        else:
            held = stored
        return {"ok": True, "saved": saved, "sha256": held.sha256, "standins": project(deck, version)}
