"""Current buying evidence for a saved home variant; never starts games or changes intent.

The saved Commander/Main recipe supplies demand. Current Sideboard/Companion are
preserved only when today's playable list matches the saved base or variant. Queue
intent annotates missing additions; it is never subtracted from physical supply.
"""
import contextlib
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

from decklab.lib import cards, decks, inventory, pool, purchases
from decklab.lib.forge import lists

from . import carddata, common, guard, shopping_missing

MAX_ROWS = 80
MAX_QUEUE = 20
MAX_REFERENCES = 20
MAX_RECIPE_LINES = 500
MAX_COPIES = 50_000
MAX_TEXT = 500
SHA = re.compile(r"[a-f0-9]{64}\Z")
HOME_DECK = re.compile(r"(casual|commander)/[a-z0-9]+(?:-[a-z0-9]+)*\Z")
AVAILABILITY_UNKNOWN = "Availability could not be confirmed for this saved recipe."
QUEUE_UNKNOWN = "The current purchase queue could not be read."
_LIMITED = object()


class _AvailabilityUnknown(ValueError):
    """An explicit safe explanation, without record paths or private holder names."""


def unavailable(reason):
    """An optional failure must not turn a saved verdict into a failed page."""
    return {"ready": False, "reason": reason, "availability_ready": False,
            "availability_problem": reason, "queue_ready": False, "queue_problem": QUEUE_UNKNOWN,
            "rows": [], "basic_added": [], "basis": "Saved test; current buying information unavailable.",
            "omitted": {"rows": 0, "queued": 0, "references": 0, "basic_added": 0}}


def _canonical(name):
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_TEXT:
        raise ValueError("Invalid saved card name")
    found = cards.resolve(name)
    if found is None:
        raise ValueError("Unknown saved card name")
    return found


def _pairs(raw):
    if not isinstance(raw, list) or len(raw) > MAX_RECIPE_LINES:
        raise ValueError("Invalid saved card lines")
    out = []
    for line in raw:
        if not isinstance(line, (list, tuple)) or len(line) != 2:
            raise ValueError("Invalid saved card line")
        quantity, name = line
        if type(quantity) is not int or not 1 <= quantity <= MAX_COPIES:
            raise ValueError("Invalid saved card quantity")
        out.append((quantity, _canonical(name)))
    if sum(quantity for quantity, _ in out) > MAX_COPIES:
        raise ValueError("Saved recipe is too large")
    return out


def _counts(lines):
    out = Counter()
    for quantity, name in lines:
        out[name] += quantity
    return out


def _additions(test):
    changes = test["variant"]["changes"]
    added, removed = _pairs(changes["add"]), _pairs(changes["remove"])
    if sum(q for q, _ in added) != sum(q for q, _ in removed):
        raise ValueError("Saved change does not preserve size")
    return _counts(added) - _counts(removed)


def _recipe(test, added):
    base, variant = test["base"], test["variant"]
    deck_id, version = base["id"], base["version"]
    match = HOME_DECK.fullmatch(deck_id) if isinstance(deck_id, str) else None
    if match is None or version not in ("target", "owned"):
        raise ValueError("Not a saved home deck")
    kind = "commander" if match[1] == "commander" else "constructed"
    if base.get("kind") not in (kind, "casual" if kind == "constructed" else kind):
        raise ValueError("Invalid saved kind")
    if not SHA.fullmatch(str(base.get("card_sha", ""))) or not SHA.fullmatch(str(variant.get("card_sha", ""))):
        raise ValueError("Missing saved recipe identity")
    raw = variant["cards"]
    if not isinstance(raw, dict) or set(raw) != {"Commander", "Main"}:
        raise ValueError("Missing saved full recipe")
    commander, main = _pairs(raw["Commander"]), _pairs(raw["Main"])
    if lists._list_text({"Commander": commander, "Main": main}, kind)[1] != variant["card_sha"]:
        raise ValueError("Saved recipe does not match its identity")
    demand = _counts(commander + main)
    if any(quantity > demand[name] for name, quantity in added.items()):
        raise ValueError("Saved additions exceed recipe")
    current_id = inventory.resolve_deck_id(deck_id)
    current_match = HOME_DECK.fullmatch(current_id) if isinstance(current_id, str) else None
    if current_match is None or current_match[1] != match[1]:
        raise ValueError("Deck identity no longer matches")
    try:
        current = decks.load_deck(current_id, version)
    except decks.DeckNotFound:
        raise _AvailabilityUnknown("The deck or tested version is no longer available; availability is unknown.") from None
    current_sha = lists.card_sha(current, kind)
    if current_sha not in (base["card_sha"], variant["card_sha"]):
        raise _AvailabilityUnknown("The deck's playable list has changed since this test; availability is unknown.")
    if current_sha == base["card_sha"]:
        # A matching base lets us check the saved change without treating today's
        # changed Main as the historical recipe or guessing old Commander sections.
        before = _counts([(line.quantity, _canonical(line.name)) for section in ("Commander", "Deck")
                          for line in current.get(section, [])])
        expected = before.copy()
        expected.subtract(_counts(_pairs(variant["changes"]["remove"])))
        if any(quantity < 0 for quantity in expected.values()):
            raise ValueError("Saved change removes copies the base did not hold")
        expected.update(_counts(_pairs(variant["changes"]["add"])))
        if +expected != demand:
            raise ValueError("Saved change does not match the base and recipe")
    sections = {"Commander": [decks.DeckLine(q, n) for q, n in commander],
                "Deck": [decks.DeckLine(q, n) for q, n in main]}
    # These sections were never recorded by Forge. They are today's preserved
    # recipe, not a claim about what the historical test played.
    sections.update({name: list(current[name]) for name in ("Sideboard", "Companion") if current.get(name)})
    return sections, current_id


def _availability(test, added, rows):
    try:
        sections, current_id = _recipe(test, added)
        supply = pool.load_pool()
        if supply.warnings or supply.unresolved:
            raise _AvailabilityUnknown("The home card pool is incomplete; availability cannot be confirmed.")
        compared = pool.compare(sections, supply, pool.self_ids(current_id), prices=False)
        if compared.get("warnings") or compared.get("unresolved"):
            raise ValueError("The saved recipe could not be fully counted")
        by_name = {row["name"]: row for row in compared["rows"]}
        for row in rows:
            counted = by_name[row["name"]]
            need, available = counted["need"], counted["available"]
            held = sum(quantity for _, quantity in counted["in_use_elsewhere"])
            arrived = max(counted["owned"] - counted["on_the_way"] - held, 0)
            baseline = need - row["added"]
            if baseline < 0:
                raise ValueError("Inconsistent saved recipe demand")
            ready = min(row["added"], max(arrived - baseline, 0))
            covered = min(row["added"], max(available - baseline, 0))
            row.update(need=need, free_now=arrived, free_including_incoming=available,
                       ready_added=ready, incoming_added=max(covered - ready, 0), missing_added=row["added"] - covered)
        return None
    except Exception as error:
        common._log(f"Variant buying availability unavailable: {type(error).__name__}")
        # No partially calculated row may masquerade as a complete allocation.
        for row in rows:
            for field in ("need", "free_now", "free_including_incoming", "ready_added", "incoming_added", "missing_added"):
                row[field] = None
        return str(error) if isinstance(error, _AvailabilityUnknown) else AVAILABILITY_UNKNOWN


def _date(value):
    return isinstance(value, str) and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)) and date.fromisoformat(value).isoformat() == value


def _reference(queued):
    if queued.get("finish", "") not in ("", "nonfoil") or not queued.get("listed_aud"):
        return None
    try:
        if len(queued["listed_aud"]) > MAX_TEXT:
            return _LIMITED
        aud = Decimal(queued["listed_aud"])
        if not aud.is_finite() or aud < 0 or not _date(queued.get("checked")) or not queued.get("listed_at"):
            return None
        value = float(aud)
        if not math.isfinite(value):
            return None
        ref = {"aud": value, "shop": queued["listed_at"], "checked": queued["checked"],
               **{key: queued.get(key, "") for key in ("printing", "set", "collector_number", "finish")}}
        return ref if all(not isinstance(item, str) or len(item) <= MAX_TEXT for item in ref.values()) else _LIMITED
    except (InvalidOperation, ValueError, TypeError):
        return None


def _queue(rows, omitted):
    try:
        queued = purchases.read_queue()
        by_name = {row["name"]: row for row in rows}
        references = {name: set() for name in by_name}
        for item in queued:
            if shopping_missing.is_token(item):
                continue
            name = cards.resolve(item["name"])
            row = by_name.get(name)
            if row is None:
                continue
            context = {"quantity": item["quantity"], "state": item["state"], "purpose": item.get("for", ""),
                       **{key: item.get(key, "") for key in ("printing", "set", "collector_number", "finish")}}
            if len(row["queued"]) < MAX_QUEUE and all(not isinstance(v, str) or len(v) <= MAX_TEXT for v in context.values()):
                row["queued"].append(context)
            else:
                omitted["queued"] += 1
            ref = _reference(item)
            if ref is _LIMITED:
                omitted["references"] += 1
                continue
            if ref is None:
                continue
            identity = tuple(ref.items())
            if identity in references[name]:
                continue
            references[name].add(identity)
            if len(row["references"]) < MAX_REFERENCES:
                row["references"].append(ref)
            else:
                omitted["references"] += 1
        return None
    except Exception as error:
        common._log(f"Variant buying queue unavailable: {type(error).__name__}")
        for row in rows:
            row["queued"], row["references"] = [], []
        omitted["queued"], omitted["references"] = 0, 0
        return QUEUE_UNKNOWN


def _estimates(rows):
    """Only existing cached evidence: the usual price_aud helper may refresh FX."""
    try:
        rate = carddata._cached_rate()
        price_date = cards.price_date()
        if not isinstance(rate, dict) or type(rate.get("rate")) not in (int, float) \
                or not math.isfinite(rate["rate"]) or rate["rate"] <= 0 or not _date(rate.get("date")) or not _date(price_date):
            return
    except Exception:
        return
    for row in rows:
        if row["references"]:
            continue
        try:
            cheapest = cards.cheapest_usd(row["name"])
            if cheapest is None:
                continue
            usd, set_code, number, finish = cheapest
            aud = usd * rate["rate"]
            if type(usd) not in (int, float) or not math.isfinite(aud) or usd < 0 \
                    or finish not in ("nonfoil", "foil", "etched") \
                    or not all(isinstance(value, str) and 0 < len(value) <= MAX_TEXT for value in (set_code, number)):
                continue
            row["estimate"] = {"aud": round(aud, 2), "set": set_code, "collector_number": number, "finish": finish,
                               "price_date": price_date, "rate": rate["rate"], "rate_date": rate["date"]}
        except Exception:
            continue


def build(test):
    """Optional evidence for an already-visible saved test; no raw test discovery here.

    Home records must be authorized before inventory, queue or cached price reads.
    Direct fixture callers receive the same guard and one-snapshot semantics.
    """
    guard.require_sees_home_records()
    try:
        with contextlib.nullcontext() if inventory.is_pinned() else inventory.pinned():
            if not isinstance(test, dict) or not HOME_DECK.fullmatch(str(test.get("base", {}).get("id", ""))):
                return unavailable("Buying information is only available for a saved home deck.")
            added = _additions(test)
            ordered = sorted(added, key=lambda name: (name.casefold(), name))
            basic = [{"name": name, "added": added[name]} for name in ordered if decks.is_basic_land(name)]
            names = [name for name in ordered if not decks.is_basic_land(name)]
            rows = [{"name": name, "added": added[name], "need": None, "free_now": None,
                     "free_including_incoming": None, "ready_added": None, "incoming_added": None,
                     "missing_added": None, "queued": [], "references": [], "estimate": None} for name in names[:MAX_ROWS]]
            omitted = {"rows": max(len(names) - MAX_ROWS, 0), "queued": 0, "references": 0,
                       "basic_added": max(len(basic) - MAX_ROWS, 0)}
            problem = _availability(test, added, rows)
            queue_problem = _queue(rows, omitted)
            _estimates(rows)
            out = {"ready": problem is None and queue_problem is None,
                   "availability_ready": problem is None, "availability_problem": problem,
                   "queue_ready": queue_problem is None, "queue_problem": queue_problem,
                   "rows": rows, "basic_added": basic[:MAX_ROWS], "omitted": omitted,
                   "basis": ("Saved tested list with today's preserved sideboard and Companion; current home supply and queue."
                             if problem is None else "Saved test additions; availability of the complete recipe is unknown.")}
            if not out["ready"]:
                out["reason"] = " ".join(value for value in (problem, queue_problem) if value)
            return out
    except Exception as error:
        common._log(f"Variant buying summary unavailable: {type(error).__name__}")
        return unavailable("The saved additions or current inventory could not be read safely.")
