"""The selected physical recipe; intended lists remain unchanged.

An omitted sideboard selection retains the whole-list legacy behavior. An
explicit map picks zero or more sideboard copies alongside the complete main.
"""
from collections import Counter
from dataclasses import replace
import hashlib
import json

from decklab.lib import decks, inventory
from decklab.lib.decks import assembled
from .common import ApiError


def sideboard_choices(sections):
    counts = Counter()
    for line in sections.get("Sideboard", []):
        counts[line.name] += line.quantity
    return [{"name": name, "quantity": qty} for name, qty in sorted(counts.items())]


def recipe(choice, summary, intended):
    if "sideboard" not in choice:
        return intended
    if summary["id"].startswith(("product/", "pairing/")):
        raise ApiError(400, "Product decks keep their complete published list.")
    selected = choice["sideboard"]
    if not isinstance(selected, dict) or len(selected) > 1000:
        raise ApiError(400, "sideboard must map intended card names to quantities.")
    available = {row["name"]: row["quantity"] for row in sideboard_choices(intended)}
    for name, qty in selected.items():
        if (not isinstance(name, str) or name not in available or type(qty) is not int
                or not 0 <= qty <= available[name]):
            raise ApiError(400, "Choose whole sideboard quantities within the intended list.")
    remaining = Counter(selected)
    lines = []
    for line in intended.get("Sideboard", []):
        qty = min(line.quantity, remaining[line.name])
        if qty:
            lines.append(replace(line, quantity=qty))
            remaining[line.name] -= qty
    result = {key: list(lines) for key, lines in intended.items() if key != "Sideboard"}
    if lines:
        result["Sideboard"] = lines
    return result


def scope(sections, intended):
    main = sum(line.quantity for key, lines in sections.items() if key != "Sideboard" for line in lines)
    selected = sum(line.quantity for line in sections.get("Sideboard", []))
    full = sum(line.quantity for line in intended.get("Sideboard", []))
    mode = "all" if selected == full else "main" if not selected else "partial"
    label = "Main deck + whole sideboard" if mode == "all" and full else "Main deck only" if not selected else "Main deck + selected sideboard"
    return {"mode": mode, "label": label, "main_count": main, "sideboard_count": selected,
            "sideboard_intended": full, "return_count": 0}


def task_key(parsed, choice, sections):
    current = assembled.key(parsed) if parsed is not None else None
    if current is None and "sideboard" not in choice:
        return None
    selected = {key: [decks.format_line(line) for line in lines] for key, lines in sections.items()}
    return hashlib.sha256(json.dumps([current, choice["version"], selected], sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def selected_sections(plan, deck_id):
    """Recompute from the verified plan's selection, never trust browser card lines."""
    choice = next(choice for choice in plan["selections"] if choice["id"] == deck_id)
    stored = inventory.current().deck(deck_id)
    parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
    intended = parsed.owned if choice["version"] == "owned" else parsed.target
    return recipe(choice, {"id": deck_id}, intended)
