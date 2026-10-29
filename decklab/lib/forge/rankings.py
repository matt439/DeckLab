"""Read saved field evidence once and rank comparable current lists together.

Each connected graph is fitted once with the field's existing Bradley-Terry
model. Ranks are local to that graph; disconnected graphs are never compared.
No games are started and no result, inventory or deck is changed.
"""
from collections import Counter

from decklab.lib import decks

from . import common, engine, field, field_exclusions, lists, saved, seqstats

FORMATS = ("Constructed", "Commander")
LABELS = {"target": "Planned", "owned": "Play now"}
RATING_KEYS = ("value", "low", "high", "rank", "rank_low", "rank_high", "of", "h_points")


def _excluded(summary, version, selected, removed):
    for name in removed:
        deck_id, chosen = field._split_name(name)
        if field._same_id(deck_id, summary["id"]) and chosen in (None, version):
            return "Left out by the field configuration."
    if selected:
        return f"The field uses the {LABELS.get(selected[0]['version'], selected[0]['version'])} list."
    if summary["id"].startswith(f"product/{decks.BEGINNER_BOX}/"):
        return "A Beginner Box half is played in a pairing, rather than on its own."
    if summary.get("space", "home") != "home":
        return "The current field uses home's decks."
    return "This list is not selected for the current field."


def _catalog(fmt, visible=None, eng=None, field_options=None, *, exclusions=None):
    """All visible current lists, plus exact existing-field membership and reasons."""
    visible = visible or (lambda deck_id: True)
    exclusions = exclusions if exclusions is not None else field_exclusions.observation(visible)
    selected, field_notes = field._field(fmt, **{**(field_options or {}), "exclusions": exclusions})
    selected = [item for item in selected if visible(item["id"])]
    removed = field_exclusions.removals(exclusions)
    eng = engine.read_only_today() if eng is None else eng
    rows, notes = [], []
    if field_notes:
        notes.append("Some field lists could not be loaded; unavailable lists have no rating.")
    summaries = [*decks.list_decks(), *decks.beginner_box_pairings()]
    for summary in summaries:
        if not visible(summary["id"]) or lists.fmt_for(decks.engine_kind(summary)) != fmt:
            continue
        chosen = [item for item in selected if field._same_id(item["id"], summary["id"])]
        chosen_ids = {field._side_id(item, eng) for item in chosen}
        aliases = {}
        for version in summary.get("versions") or ["target"]:
            if version not in LABELS:
                continue
            entry, side = None, None
            try:
                if summary.get("error"):
                    raise ValueError("Unreadable deck")
                entry = field._entry(summary, version)
                side = field._side_id(entry, eng)
            except (decks.DeckNotFound, decks.DeckFileError, OSError, ValueError, common.ForgeError):
                pass
            if side is not None and side in aliases:
                aliases[side]["versions"].append(version)
                continue
            included = side is not None and side in chosen_ids
            row = {"id": summary["id"], "title": summary.get("title") or summary["id"],
                   "kind": summary.get("kind") or summary["id"].split("/")[0], "version": version,
                   "versions": [version], "card_sha": entry["card_sha"] if entry else None,
                   "in_field": included,
                   "exclusion": None if included else (_excluded(summary, version, chosen, removed)
                                                       if entry else "This current list cannot be read."),
                   "_entry": entry}
            rows.append(row)
            if side is not None:
                aliases[side] = row
    return rows, notes


def _seen_result(visible):
    """keep(result) using visible historical aliases or identical current lists (E10-S31)."""
    if visible is None:
        return None
    from decklab.lib.simulation_visibility import VisibleLists
    return VisibleLists(visible, lists.card_sha).result


def _historical(rows, fmt, results_dir, eng, keep=None):
    """Flag old/unknown engine or changed-list evidence without using it as current."""
    stale = Counter()
    for result in saved._stored(results_dir):
        if result.get("format") != fmt or result.get("kind"):
            continue
        if keep is not None and not keep(result):
            continue
        try:
            current = bool(eng.get("complete")) and engine.stored_key(result, eng) == result["key"]
        except Exception:
            current = False
        for side in result.get("sides", []):
            aliases = list(side.get("seen_as") or [])
            if side.get("id"):
                aliases.append(side)
            for row in rows:
                named = any(field._same_id(alias.get("id"), row["id"]) and
                            alias.get("version") in row["versions"] for alias in aliases)
                if named and (
                        not current or side.get("card_sha") != row["card_sha"] or row.get("_entry") is None
                        or side.get("engine_id") != field._side_id(row["_entry"], eng)):
                    stale[(row["id"], row["version"])] += len(field._games(result))
    return stale


def _view(fmt, results_dir, visible, field_options=None, keep=None):
    eng = engine.read_only_today()
    exclusions = field_exclusions.observation(visible)
    rows, notes = _catalog(fmt, visible, eng, field_options, exclusions=exclusions)
    keep = _seen_result(visible) if keep is None else keep
    data = field._bt_data(fmt, results_dir, current_engine=eng, keep=keep)
    stale = _historical(rows, fmt, results_dir, eng, keep)
    if eng.get("kind") != engine.KIND_DECKLAB or not eng.get("complete"):
        notes.append("The current Deck Lab field engine cannot be confirmed; earlier results are not treated as current.")
        if eng.get("identity_problem"):
            notes.append(eng["identity_problem"])
    eligible = {}
    for row in rows:
        row.update(group=None, rating=None, games=0, unsettled=True, reasons=[])
        entry = row.get("_entry")
        if row["in_field"] and entry is not None:
            side = field._side_id(entry, eng)
            eligible.setdefault(side, []).append(row)
        if row.get("exclusion"):
            row["reasons"].append(row["exclusion"])
        if stale[(row["id"], row["version"])]:
            row["reasons"].append("Earlier-engine, changed-list or different-pilot games are not current evidence "
                                  "for this list.")
    unseen, groups = set(eligible), []
    while unseen:
        first = sorted(unseen)[0]
        component = seqstats.bt_component(data, first)
        current = sorted(component & set(eligible))
        unseen.difference_update(current)
        for side in current:
            games = sum(value[1] for key, value in data.items() if side in key[:2])
            for row in eligible[side]:
                row["games"] = games
        if len(component) < 2:
            for row in eligible[first]:
                row["reasons"].append("No current-engine games link this list to the field yet.")
            continue
        cells = {key: value for key, value in data.items() if key[0] in component and key[1] in component}
        fit = seqstats.bt_fit(cells)
        if not fit or not fit.get("converged") or fit.get("cov") is None:
            for side in current:
                for row in eligible[side]:
                    row["reasons"].append("The saved games do not support a stable rating yet.")
            continue
        group = f"group-{len(groups) + 1}"
        groups.append({"id": group, "lists": sum(len(eligible[side]) for side in current), "players": len(current)})
        for side in current:
            rating = seqstats.bt_rating(fit, side, current)
            games = eligible[side][0]["games"]
            pair_games = Counter()
            for (left, right, _), (_, count) in cells.items():
                if left == side:
                    pair_games[right] += count
                elif right == side:
                    pair_games[left] += count
            floor = all(pair_games[other] >= seqstats.FIELD_FLOOR for other in current if other != side)
            unsettled = len(current) < 2 or not floor or games < seqstats.FIELD_FLOOR or rating is None or (
                rating["rank_low"] != rating["rank_high"])
            for row in eligible[side]:
                row.update(group=group, games=games, rating={key: rating[key] for key in RATING_KEYS} if rating else None,
                           unsettled=unsettled)
                if len(current) < 2:
                    row["reasons"].append("Only one current field list is in this connected group; "
                                          "it cannot be compared with other current lists.")
                if not floor or games < seqstats.FIELD_FLOOR:
                    row["reasons"].append("Too few current decided games against the field; this rating is unsettled.")
                elif rating and rating["rank_low"] != rating["rank_high"]:
                    row["reasons"].append("The likely rank range is not settled yet.")
    if len(groups) > 1:
        notes.append("Disconnected groups have separate ranks and cannot be compared with each other.")
    notes.append("Ratings reuse the field's current-engine model, including historical list nodes that link its graph. "
                 "Only current field lists count in each group's rank range; identical simulation lists share a rank.")
    notes.append("Games counts decided games; draws and games without a result do not enter the rating.")
    rows.sort(key=lambda row: (row["group"] is None, row["group"] or "", row["rating"] is None,
                               -(row["rating"] or {}).get("value", 0), row["title"].casefold(), row["version"]))
    return {"format": fmt, "rows": [{key: value for key, value in row.items() if not key.startswith("_")}
                                   for row in rows], "groups": groups, "notes": notes, "error": None,
            "manual_excluded": field_exclusions.count(exclusions)}


def view(fmt="Constructed", results_dir=None, visible=None, *, field_options=None, keep=None):
    """One inventory/engine snapshot, no simulation, format mixing or result writes."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of: {', '.join(FORMATS)}")
    with lists.one_snapshot(), engine.held():
        return _view(fmt, results_dir, visible, field_options, keep)
