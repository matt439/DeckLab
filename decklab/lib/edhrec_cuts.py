"""Cache-only cut evidence. Inclusion, role counts and saved card-log facts never choose a cut."""
import copy
import math
from collections import Counter

from decklab.lib import cards, edhrec
from decklab.lib.forge.cardstats import MIN_CARD_GAMES, MIN_SPLIT_GAMES
from decklab.lib.stats.cardtext import Entry, is_land
from decklab.lib.stats.role_targets import SOURCE, role_targets

STUCK_MIN_COPIES = 20
STUCK_SHARE = .2


def cached_page(commanders, page=None):
    """Read local reduced pages and bounded local redirects; never call fetch or write a cache."""
    if not 1 <= len(commanders) <= 2:
        return None
    base = None
    with edhrec._lock:
        for slug in edhrec.commander_slugs(commanders):
            seen = set()
            while slug not in seen and len(seen) < 3:
                seen.add(slug)
                kept = edhrec._read(slug)
                if not kept or kept.get("missing"):
                    break
                if kept.get("redirect"):
                    target = kept["redirect"]
                    if not isinstance(target, str) or not edhrec._SLUG.fullmatch(target):
                        break
                    slug = target
                    continue
                base = kept
                break
            if base:
                break
        if base and page:
            themes = base.get("themes") or []
            if not isinstance(themes, list) or any(not isinstance(item, dict) or not isinstance(item.get("slug"), str)
                                                 or not isinstance(item.get("name"), str) for item in themes):
                return None
            if page not in {item["page"] for item in edhrec.page_choices(base.get("themes"))}:
                raise edhrec.UnknownPage("That page isn't offered by the cached commander page.")
            kept = edhrec._read(f"{base['slug']}/{page}")
            base = None if not kept or kept.get("missing") or kept.get("redirect") else dict(kept, themes=base.get("themes"))
    if not base or not isinstance(base.get("lists"), list) or not base["lists"]:
        return None
    if base.get("url") != edhrec.SITE_URL.format(slug=base["slug"]):
        return None
    themes = base.get("themes") or []
    if not isinstance(themes, list) or any(not isinstance(theme, dict) or not isinstance(theme.get("slug"), str)
                                         or not edhrec._SLUG.fullmatch(theme["slug"]) or not isinstance(theme.get("name"), str) for theme in themes):
        return None
    for group in base["lists"]:
        if not isinstance(group, dict) or not isinstance(group.get("cards"), list):
            return None
        if any(not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"].strip()
               for row in group["cards"]):
            return None
    return copy.deepcopy(base)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _inclusions(source):
    out = {}
    for group in source["lists"] if source else []:
        for row in group["cards"]:
            name = cards.resolve(row["name"]) or row["name"]
            share = None
            if _number(row.get("decks")) and _number(row.get("of")) and row["of"] > 0 and row["decks"] <= row["of"]:
                share = round(100 * row["decks"] / row["of"], 2)
            if name not in out or share is not None and (out[name] is None or share > out[name]):
                out[name] = share
    return out


def _role_reasons(card, targets):
    roles = set(card.get("roles") or [])
    return [{"kind": "role", "category": item["category"], "count": item["count"], "target": item["target"],
             "text": f"{item['label']}: {item['count']} cards against the Command Zone starting target of {item['target']}.",
             "measure": item["measure"]}
            for item in targets["categories"] if item["status"] == "above" and item["roles"]
            and roles.intersection(item["roles"]) and not roles.intersection(item["except"])]


def _forge_reasons(name, evidence):
    if not isinstance(evidence, dict) or not evidence.get("enough") or evidence.get("games", 0) < MIN_CARD_GAMES:
        return []
    row = next((row for row in evidence.get("rows", []) if row.get("name") == name), None)
    if not row or row.get("land") is not False:
        return []
    drawn = row.get("drawn_games", 0)
    drawn = drawn if _number(drawn) else 0
    if drawn >= MIN_SPLIT_GAMES and row.get("cast") == 0 and row.get("other_casts") == 0:
        return [{"kind": "forge-never", "games": evidence["games"], "drawn_games": drawn,
                 "text": f"Forge never cast it in {drawn} games where it was drawn ({evidence['games']} card-log games)."}]
    copies, stuck = row.get("copies_drawn", 0), row.get("stuck_share")
    copies = copies if _number(copies) else 0
    if copies >= STUCK_MIN_COPIES and _number(stuck) and STUCK_SHARE <= stuck <= 1:
        return [{"kind": "forge-stuck", "games": evidence["games"], "copies_drawn": copies, "stuck_share": stuck,
                 "text": f"Forge left {stuck * 100:g}% of {copies} drawn copies in hand at the end ({evidence['games']} card-log games)."}]
    return []


def project(sections, commanders, *, forge_stats=None, page=None):
    """Planned nonlands outside Commander; all evidence is countable and no worst card is named."""
    if not isinstance(forge_stats, dict) or not _number(forge_stats.get("games")) or not isinstance(forge_stats.get("rows"), list) or any(not isinstance(row, dict) for row in forge_stats["rows"]):
        forge_stats = None
    base = cached_page(commanders) if page else None
    source = cached_page(commanders, page)
    inclusion = _inclusions(source)
    main, unknown = [], []
    for section in ("Commander", "Deck", "Companion"):
        for line in sections.get(section, []):
            name = cards.resolve(line.name) or line.name
            card = cards.card(name)
            if card is None:
                unknown.append(name)
            else:
                main.append(Entry(line.quantity, name, section, card))
    targets = role_targets(main, sum(entry.qty for entry in main if is_land(entry.card)))
    commander_names = set(commanders) | {entry.name for entry in main if entry.section == "Commander"}
    quantities = Counter()
    for entry in main:
        if entry.section == "Deck" and entry.name not in commander_names and not is_land(entry.card):
            quantities[entry.name] += entry.qty
    groups = {key: [] for key in ("ranked", "unquantified", "absent", "uncached")}
    for name, qty in quantities.items():
        card = cards.card(name)
        status = "uncached" if source is None else "absent" if name not in inclusion else "unquantified" if inclusion[name] is None else "ranked"
        groups[status].append({"name": name, "qty": qty, "inclusion": inclusion.get(name), "edhrec_status": status,
                               "reasons": _role_reasons(card, targets) + _forge_reasons(name, forge_stats)})
    for rows in groups.values():
        rows.sort(key=lambda row: (row["inclusion"] if row["inclusion"] is not None else 0, row["name"].casefold()))
    headers = {"ranked": "On EDHREC's page, lowest inclusion first", "unquantified": "On EDHREC's page, inclusion unavailable",
               "absent": "Not on EDHREC's page for this commander", "uncached": "No cached EDHREC page available"}
    return {"commanders": list(commanders), "page": page or "", "cuts": True,
            "groups": [{"key": key, "header": headers[key], "cards": rows} for key, rows in groups.items() if rows],
            "source": {**{key: source.get(key) if source else None for key in ("url", "commander", "decks", "fetched")},
                       "cached": True, "available": source is not None},
            "pages": edhrec.page_choices((source or base).get("themes")) if source or base else [], "role_targets": targets,
            "role_source": copy.deepcopy(SOURCE),
            "unknown": sorted(set(unknown)), "total": sum(quantities.values()),
            "forge": {"available": isinstance(forge_stats, dict), "games": forge_stats.get("games", 0) if isinstance(forge_stats, dict) else 0,
                      "enough": bool(forge_stats.get("enough")) if isinstance(forge_stats, dict) else False,
                      "min_games": MIN_CARD_GAMES, "min_drawn_games": MIN_SPLIT_GAMES, "min_stuck_copies": STUCK_MIN_COPIES},
            "note": "Inclusion is from the cached EDHREC page, not a measure of a card's strength. Role targets are starting points. Forge describes its AI's games. Choose cuts yourself."}
