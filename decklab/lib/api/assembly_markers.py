"""Packing's two passes: allocate logical real cards first, then saved physical markers.

Suggestions use only the remaining physical pool and never change readiness until
the player saves a choice. Opening a plan never installs or removes a marker.
"""
from collections import Counter
from dataclasses import replace

from decklab.lib import cards, decks, inventory
from decklab.lib.decks import standins
from . import guard


def _copies(items):
    return [{**item, "need": Counter(item["need"]), "current": Counter(item["current"]),
             "steps": [], "returns": []} for item in items]


def _load(item, profile):
    stored = inventory.current().deck(item["id"])
    empty = {"rows": [], "installed": [], "warnings": [], "editable": False,
             "sha256": stored.sha256 if stored else None, "parsed": None}
    if stored is None:
        return empty
    try:
        parsed = decks.parse_deck(stored.data, stored.slug, stored.kind, space=stored.space)
        empty["parsed"] = parsed
        empty["editable"] = guard.allowed(profile, "deck.edit", parsed)
        data = standins.get_stand_ins(parsed)
        empty["installed"] = (data["built"] or {}).get("cards", []) if parsed.status == "built" else []
        raw = data[item["version"]]
        # A list edit can remove a represented card. Retire that choice on the next
        # explicit packing completion, without making a GET rewrite the deck.
        sections = parsed.target if item["version"] == "target" else parsed.owned
        full = Counter()
        for lines in (sections or {}).values():
            for line in lines:
                full[line.name] += line.quantity
        empty["full"] = Counter(full)
        choices = []
        for row in raw:
            qty = min(row["qty"], full[row["for"]])
            full[row["for"]] -= qty
            if qty:
                choices.append({**row, "qty": qty})
        empty["choices"] = standins.validate_rows(choices, sections or {})
        available = Counter(item["need"])
        clipped = []
        for row in choices:
            qty = min(row["qty"], available[row["for"]])
            available[row["for"]] -= qty
            if qty:
                clipped.append({**row, "qty": qty})
        empty["rows"] = standins.validate_rows(clipped, sections or {})
        empty["raw"] = clipped
    except (decks.DeckFileError, standins.StandInsError) as error:
        empty["warnings"].append(str(error))
        empty["invalid"] = True
    return empty


def _spares(p, baseline, aliases):
    """Physical copies left after every selected deck's real-card allocation."""
    used = Counter()
    for holder in p.in_use:
        if holder.id not in aliases:
            used.update(holder.cards)
    for item in baseline["decks"]:
        for step in item["steps"]:
            used[step["name"]] += step["need"] - step["waiting"] - step["missing"]
    return Counter({name: max(0, qty - sum(n for _, n in p.on_the_way.get(name, [])) - used[name])
                    for name, qty in p.owned.items() if not decks.is_basic_land(name)})


def _candidates(spare, logical):
    return [{"name": name, "free": spare[name]} for name in sorted(spare)
            if spare[name] > 0 and name not in logical and cards.card(name)]


def _retired(meta, rows, shortages, logical):
    before = Counter()
    # Config and installation can describe the same physical mapping; count it once.
    for source in (meta.get("raw", meta["rows"]), meta["installed"]):
        found = Counter()
        for row in source:
            found[(row["for"], row["using"])] += row["qty"]
        before |= found
    after = Counter()
    for row in rows:
        after[(row["for"], row["using"])] += row["qty"]
    return [{"for": target, "using": marker, "qty": qty - after[(target, marker)],
             "reason": ("not_selected" if meta.get("full", {}).get(target) else "list_changed") if not logical[target] else
                       "real_available" if not shortages[target] else "choice_changed"}
            for (target, marker), qty in before.items() if qty > after[(target, marker)]]


def plan_standins(p, participants, aliases, unresolved, profile, allocate):
    # A known installed marker remains reserved, but selecting its holder can
    # repair a later logical-list edit by returning it. Unselected holders and
    # unreadable metadata still block the plan as before.
    repairable = {warning for holder in p.in_use if holder.id in aliases
                  for warning in getattr(holder, "standin_warnings", ())}
    if repairable:
        p = replace(p, warnings=[warning for warning in p.warnings if warning not in repairable])
    baseline = allocate(p, _copies(participants), aliases, unresolved)
    available = _spares(p, baseline, aliases)
    original_spare = Counter(available)
    metadata = [_load(item, profile) for item in participants]
    effective, shortages = [], []
    for item in baseline["decks"]:
        shortages.append(Counter({step["name"]: step["waiting"] + step["missing"] for step in item["steps"]}))
    left = [Counter(found) for found in shortages]
    # Honour saved mappings before offering any unsaved suggestions. Each named
    # card is allocated once across all participants, including installed copies.
    for index, meta in enumerate(metadata):
        rows = []
        for row in meta["rows"]:
            wanted = min(row["qty"], left[index][row["for"]])
            qty = wanted if row["using"] is None else min(wanted, available[row["using"]])
            if qty:
                rows.append({**row, "qty": qty})
                left[index][row["for"]] -= qty
                if row["using"] is not None:
                    available[row["using"]] -= qty
            if qty < wanted:
                meta["warnings"].append(f"{row['using']}: only {qty} of {wanted} saved stand-in copies are free now")
        effective.append(rows)
    physical = _copies(participants)
    suggested_spare = Counter(available)
    for index, item in enumerate(physical):
        meta, rows = metadata[index], effective[index]
        logical = participants[index]["need"]
        candidates = _candidates(original_spare, logical)
        needs = [{"for": row["for"], "qty": row["qty"], "suggestion": row["using"]} for row in rows]
        meanings = {row["using"]: row["for"] for row in rows if row["using"] is not None}
        for target in sorted(left[index]):
            remaining = left[index][target]
            for candidate in candidates:
                marker = candidate["name"]
                if not remaining:
                    break
                if marker in meanings and meanings[marker] != target:
                    continue
                qty = min(remaining, suggested_spare[marker])
                if qty:
                    needs.append({"for": target, "qty": qty, "suggestion": marker})
                    suggested_spare[marker] -= qty
                    remaining -= qty
                    meanings[marker] = target
            if remaining:
                needs.append({"for": target, "qty": remaining, "suggestion": None})
        item["need"] = standins.physical_counts(logical, rows)
        item["logical_shortages"] = [{"name": step["name"], "waiting": step["waiting"], "missing": step["missing"]}
                                     for step in baseline["decks"][index]["steps"] if step["waiting"] or step["missing"]]
        outside = Counter(meta.get("full", {})) - Counter(logical)
        used = Counter()
        for row in rows:
            used[(row["for"], row["using"])] += row["qty"]
        preserved = []
        for row in meta.get("choices", []):
            key = row["for"], row["using"]
            consumed = min(used[key], row["qty"])
            used[key] -= consumed
            qty = min(row["qty"] - consumed, outside[row["for"]])
            outside[row["for"]] -= qty
            if qty:
                preserved.append({**row, "qty": qty})
        choices = standins._rows([*rows, *preserved])
        item["standins"] = {"version": item["version"], "rows": rows, "choices": choices,
                            "needs": needs, "candidates": candidates,
                            "retired": _retired(meta, rows, shortages[index], logical),
                            "warnings": meta["warnings"], "editable": meta["editable"], "sha256": meta["sha256"]}
    answer = allocate(p, physical, aliases, unresolved)
    for item, meta, rows in zip(answer["decks"], metadata, effective):
        installed = Counter()
        proposed = Counter()
        for row in meta["installed"]:
            if row["using"] is None:
                installed[row["for"]] += row["qty"]
        for row in rows:
            if row["using"] is None:
                proposed[row["for"]] += row["qty"]
        item["returns"].extend({"name": f"Spare stand-in for {name}", "quantity": qty, "untracked": True}
                               for name, qty in sorted((installed - proposed).items()))
    answer["logical_totals"] = baseline["totals"]
    if any(meta.get("invalid") for meta in metadata):
        answer["warnings"].extend(f"{item['title']}: {warning}" for item, meta in zip(participants, metadata)
                                  if meta.get("invalid") for warning in meta["warnings"])
        answer["counts_confirmed"] = answer["ready"] = False
    return answer
