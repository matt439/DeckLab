"""Read-only selection of a member's own-only Forge artifacts.

Mixed results and files with unknown provenance are preserved, never exported.
No file is removed or rewritten here. Apply will need a cooperative lifecycle
lock and a durable recovery journal before it may use this selection.
"""
import hashlib
import json
import re
from pathlib import Path

from decklab.lib import decks, spaces

KEY = re.compile(r"[0-9a-f]{64}\Z")


def _owner(deck_id):
    if not isinstance(deck_id, str):
        return None
    if deck_id.startswith("variant:"):
        deck_id = deck_id[len("variant:"):]
    try:
        return spaces.split_deck_id(deck_id)[0]
    except ValueError:
        return None


def _owners(items):
    if not isinstance(items, list) or not items:
        return {None}
    return {_owner(item.get("id")) if isinstance(item, dict) else None for item in items}


def _result_owners(value):
    sides = value.get("sides")
    if not isinstance(sides, list) or len(sides) != 2:
        return {None}
    return set().union(*(_owners(side.get("seen_as")) if isinstance(side, dict) else {None} for side in sides))


def _read(path):
    before = path.stat()
    content = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(content) != after.st_size:
        raise ValueError("Forge results changed during the snapshot; retry the export")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return content, None
    return content, value if isinstance(value, dict) else None


def other_list_hashes(c, space):
    """Current lists another space can use, returned only as anonymous hashes.

    Read derived deck lines and product card cells, never another deck's prose,
    title or history. SQL groups identities internally; no other deck id is
    returned. These hashes are transient exclusion checks, never manifest data.
    """
    from decklab.lib.forge import lists
    hashes = set()
    for kind, lines in c.execute(
            "select d.kind, jsonb_agg(jsonb_build_array(l.section, l.quantity, l.name) "
            "order by l.section, l.position) from deck d join deck_line l on l.deck_id = d.id "
            "where d.space_id <> %s and l.section in ('Commander', 'Deck') "
            "group by d.id, l.version, d.kind", (space,)):
        sections = {"Commander": [], "Main": []}
        for section, quantity, name in lines:
            sections["Commander" if section == "Commander" else "Main"].append([quantity, name])
        hashes.add(lists._list_text(sections, kind)[1])
    # Products belong to home, hence to another space for every member export.
    # Their card cells also cover a current precon with an identical list. Include
    # all referenced product lists conservatively, independent of storage state.
    for columns, rows, beginner in c.execute(
            "select p.columns, jsonb_agg(i.cells order by i.position), p.stem = 'fdn-beginner-box' "
            "from product p join product_item i on i.product_stem = p.stem group by p.stem, p.columns"):
        groups = {}
        for cells in rows:
            row = dict(zip(columns, cells))
            section = decks._section_name(row.get("section") or "deck")
            if section not in ("Deck", "Commander"):
                continue
            try:
                quantity = int(row.get("quantity", ""))
                name = row["name"]
                if quantity < 1 or not name:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            group = groups.setdefault(row.get("deck", ""), {"Commander": [], "Main": []})
            group["Commander" if section == "Commander" else "Main"].append([quantity, name])
        candidates = list(groups.values())
        if beginner:
            candidates += [{"Commander": [], "Main": a["Main"] + b["Main"]}
                           for i, a in enumerate(groups.values()) for j, b in enumerate(groups.values()) if i < j]
        for sections in candidates:
            hashes.add(lists._list_text(sections, "commander" if sections["Commander"] else "constructed")[1])
    return frozenset(hashes)


def snapshot(space, results_dir, *, other_hashes=()):
    """({results-relative path: bytes}, metadata) for files wholly of space.

    Metadata carries only selected hashes, plus generic preservation counts.
    Neither a mixed result's bytes nor its hash enters the member artifact.
    Field notes qualify only when each recorded pair is an own-only result;
    variants need an own base and own opponents, including their against value.
    """
    from decklab.lib.forge import saved, variants
    root = Path(results_dir)
    if not root.exists():
        return {}, {"selected": {}, "preserved_related": 0, "unknown": 0}
    if not root.is_dir() or root.is_symlink() or root.is_junction():
        raise ValueError("Forge results must be an ordinary directory")
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Forge results contain a linked path; snapshot refused")
    out, owners_by_key, stored = {}, {}, {}
    related = unknown = 0
    for folder in (root, root / "paired"):
        for path in sorted(folder.glob("*.json")):
            if not KEY.fullmatch(path.stem):
                continue
            content, value = _read(path)
            owners = _result_owners(value) if saved._is_result(value, path.stem) else {None}
            if owners == {space} and any(side.get("card_sha") in other_hashes for side in value["sides"]):
                owners.add("shared-current-list")
            owners_by_key[path.stem] = owners
            rel = path.relative_to(root).as_posix()
            stored[rel] = (content, owners)
    for folder, kind in ((root / "paired" / "tests", "variant"), (root / "field", "field")):
        for path in sorted(folder.glob("*.json")):
            content, value = _read(path)
            owners = {None}
            if value is not None and kind == "variant" and KEY.fullmatch(path.stem) \
                    and value.get("test") == path.stem and value.get("version") == variants.SUMMARY_VERSION:
                owners = _owners([value.get("base")]) | _owners(value.get("opponents"))
                if owners == {space} and any(item.get("card_sha") in other_hashes
                                             for item in [value.get("base"), value.get("variant") or {},
                                                          *value.get("opponents", [])]):
                    owners.add("shared-current-list")
                against = value.get("against")
                if isinstance(against, dict):
                    owners |= _owners([against])
                elif not isinstance(against, str) or against not in (
                        "field:Constructed", "field:Commander", f"field:{space}:Constructed", f"field:{space}:Commander"):
                    owners.add(None)
            elif value is not None and kind == "field" and isinstance(value.get("runs"), list) and value["runs"]:
                owners = set()
                for run in value["runs"]:
                    if not isinstance(run, dict):
                        owners.add(None)
                        continue
                    owners |= _owners([run.get("deck")])
                    pairs = run.get("per_opponent")
                    if not isinstance(pairs, dict):
                        owners.add(None)
                    else:
                        for key in pairs:
                            owners |= owners_by_key.get(key, {None})
                # An old unscoped note is home's even when its content was shared.
                if not path.stem.endswith(f"-{space}"):
                    owners.add("home")
            stored[path.relative_to(root).as_posix()] = (content, owners)
    for rel, (content, owners) in sorted(stored.items()):
        if owners == {space}:
            out[rel] = content
        elif space in owners:
            related += 1
        if None in owners:
            unknown += 1
    return out, {"selected": {rel: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                               for rel, content in out.items()},
                 "preserved_related": related, "unknown": unknown}
