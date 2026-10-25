"""The intended list left outside a deck's saved physical build.

This projection never changes either playable list or the purchase queue. Callers
must first check that the viewer may see the deck's inventory. Packing previews
can pass their proposed logical sections and stand-ins without saving a build.
"""
from collections import Counter

from decklab.lib import decks, pool
from decklab.lib.decks import assembled as physical, standins as markers


def _name(name):
    return pool._canonical(name, "intended list", {})


def _counts(sections):
    result = {}
    for section, lines in sections.items():
        counts = result.setdefault(section, Counter())
        for line in lines:
            counts[_name(line.name)] += line.quantity
    return result


def _recipe(sections):
    result = Counter()
    for section, lines in sections.items():
        for line in lines:
            result[(section, _name(line.name), line.set, line.number, line.finish)] += line.quantity
    return result


def _availability(deck, version, p, result):
    if result is None and p is not None:
        result = pool.owned_vs_needed(deck.deck_id, version, pool=p, prices=False)
    if result is None or result.get("warnings") or result.get("unresolved"):
        return None
    return {row["name"]: {"missing": row["missing"],
                           "on_the_way": sum(qty for _, qty in pool.row_labels(row)["on_the_way"])}
            for row in result["rows"]}


def project(deck, p=None, result=None, *, version="target", sections=None, standins=None):
    """Describe actual/proposed assembly against the full chosen intended list.

    By default a built deck's physical snapshot (or legacy built list) is compared
    with Planned, even when its physical build uses Play-now. ``sections`` instead
    describes a packing preview's proposed build of ``version``. ``standins`` is
    that preview's selected marker mappings; actual builds use installed mappings.

    ``remaining`` counts desired real cards outside the build, including those
    currently represented by a marker. Missing and on-the-way counts come from the
    full intended list's ordinary pool comparison, capped once across sections.
    Already owned cards outside the build therefore never become purchases merely
    because they are not assembled. Unknown availability stays None.
    """
    proposed = sections is not None
    if deck is None or (not proposed and deck.status != "built"):
        return None
    if version not in ("target", "owned"):
        raise ValueError("Choose the Planned or Play-now list")
    intended = deck.target if version == "target" else deck.owned
    if intended is None:
        raise ValueError("That intended list is not available")
    if proposed:
        actual, installed_version = sections, version
    else:
        actual = physical.sections(deck)
        installed_version = physical.version(deck)
    if standins is None:
        installed_markers = markers.installed_for(deck) if not proposed else None
        standins = installed_markers["cards"] if installed_markers else []

    actual_counts, intended_counts = _counts(actual), _counts(intended)
    real_counts = {section: Counter(counts) for section, counts in actual_counts.items()}
    represented = Counter()
    for row in standins:
        represented[_name(row["for"])] += row["qty"]
    # Marker choices are per name, rather than per section. Match the packing
    # recipe's canonical order, consuming each represented copy only once.
    marker_counts = {}
    for section in decks.SECTIONS:
        for name, count in real_counts.get(section, {}).items():
            count = min(count, represented[name])
            real_counts[section][name] -= count
            represented[name] -= count
            marker_counts[(section, name)] = count

    availability = _availability(deck, version, p, result)
    remaining = []
    for section in decks.SECTIONS:
        for name, intended_count in sorted(intended_counts.get(section, {}).items()):
            assembled_count = min(intended_count, real_counts.get(section, {}).get(name, 0))
            count = intended_count - assembled_count
            if not count:
                continue
            missing = waiting = None
            if decks.is_basic_land(name):
                missing = waiting = 0
            elif availability is not None:
                found = availability.get(name)
                if found is not None:
                    missing = min(count, found["missing"])
                    found["missing"] -= missing
                    waiting = min(count - missing, found["on_the_way"])
                    found["on_the_way"] -= waiting
            remaining.append({"section": section, "name": name, "intended": intended_count,
                              "assembled": assembled_count, "represented": marker_counts.get((section, name), 0),
                              "remaining": count, "missing": missing, "on_the_way": waiting})
    return {"version": installed_version, "intended_version": version,
            "main_count": sum(count for section, counts in actual_counts.items() if section != "Sideboard"
                              for count in counts.values()),
            "sideboard_count": sum(actual_counts.get("Sideboard", {}).values()),
            "sideboard_intended": sum(intended_counts.get("Sideboard", {}).values()),
            "remaining_count": sum(row["remaining"] for row in remaining), "remaining": remaining,
            "changed": _recipe(actual) != _recipe(intended) or bool(remaining)}
