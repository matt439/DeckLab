"""The gauntlet's Forge source (design section 3): the 60-card decks Forge bundles in res/quest,
its duels (duels/, each with a Difficulty) and its precons (precons/), plus res/quest/
commanderprecons, the offline stand-in for MTGJSON's Commander precons (precon_source.py).

A .dck file is read as lists.entry_from_dck reads one: only its [Commander] and [Main] sections
count (any case), "|SET|art" and Forge's foil mark "+" ("Kalamax, the Stormsire+|C20") are
stripped from a line, and a name repeated (basics of several arts) is added up where it first
appears. Its [metadata] Name, Title, Difficulty and Set are kept.
Names are played exactly as Forge writes them.

Forge's folder is config's forge_dir (C:/Tools/forge-decklab on the dev PC), as the rest of
lib/forge finds it; the tests hand a fixture folder in as root.
"""
import re
from pathlib import Path

from . import slug

DIFFICULTIES = ("easy", "medium", "hard", "very hard")
PREFERRED = "medium"                # one version per duel Title: the closest to this, ties to the harder
MIN_MAIN = 60                       # a constructed gauntlet deck's main deck
MAX_FILE_BYTES = 256 * 1024
SECTIONS = {"[commander]": "Commander", "[main]": "Main"}
LINE_RE = re.compile(r"^(\d{1,3})\s+(.+?)\s*$")


def quest_dir(root=None):
    """Forge's res/quest folder: root's when given (a fixture folder holding duels/, precons/ and
    commanderprecons/), else the configured Forge install's."""
    if root is not None:
        return Path(root)
    from decklab.lib.forge import common      # lazily: lib/forge reads config.json
    return Path(common._settings()["forge_dir"]) / "res" / "quest"


def parse_dck(text):
    """{"meta": {key: value} of [metadata], "cards": {"Commander": [[qty, name]], "Main": [...]}}."""
    meta, listed, section, order = {}, {"Commander": [], "Main": []}, None, {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.lower()
            continue
        if section == "[metadata]":
            key, sep, value = line.partition("=")
            if sep and key.strip():
                meta[key.strip()] = value.strip()
            continue
        part = SECTIONS.get(section)
        found = LINE_RE.match(line) if part else None
        if not found or int(found[1]) < 1:
            continue
        name = found[2].split("|", 1)[0].strip().removesuffix("+").rstrip()    # "+": Forge's foil mark
        key = (part, name)
        if key in order:
            order[key][0] += int(found[1])
        else:
            order[key] = [int(found[1]), name]
            listed[part].append(order[key])
    return {"meta": meta, "cards": listed}


def read_dck(path):
    """parse_dck of a file, refusing one too big to be a deck."""
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise OSError(f"{path.name} is too big to be a deck")
    return parse_dck(path.read_text(encoding="utf-8", errors="replace"))


def _rel(path, root):
    """A file's path as "res/quest/<folder>/<file>"."""
    return "res/quest/" + Path(path).relative_to(root).as_posix()


def _main_count(cards):
    return sum(q for q, _ in cards["Commander"] + cards["Main"])


def _record(folder, path, root, parsed, tier):
    meta = parsed["meta"]
    title = meta.get("Title") or meta.get("Name") or path.stem
    problems = []
    count = _main_count(parsed["cards"])
    if count < MIN_MAIN:
        problems.append(f"Its main deck has {count} cards; a 60-card gauntlet deck needs at least {MIN_MAIN}.")
    return {"id": f"gauntlet:forge/{folder}/{slug(path.stem)}", "title": meta.get("Name") or path.stem,
            "kind": "constructed", "tier": tier, "duel_title": title,
            "source": {"kind": "forge", "file": _rel(path, root), "fetched": None, "rank": None, "decks": None},
            "set": meta.get("Set", ""), "commanders": [],
            "cards": parsed["cards"]["Commander"] + parsed["cards"]["Main"], "themes": [], "problems": problems}


def _distance(tier):
    """How far a duel's difficulty is from PREFERRED, a tie going to the harder."""
    at, want = DIFFICULTIES.index(tier), DIFFICULTIES.index(PREFERRED)
    return (abs(at - want), -at)


def _files(folder):
    return sorted(p for p in folder.glob("*.dck") if p.is_file()) if folder.is_dir() else []


def constructed_decks(root=None, log=print):
    """(records, excluded): Forge's duels, one per Title (_distance), and its quest precons."""
    root = quest_dir(root)
    records, excluded, by_title = [], [], {}
    for path in _files(root / "duels"):
        deck_id = f"gauntlet:forge/duels/{slug(path.stem)}"
        try:
            parsed = read_dck(path)
        except (OSError, UnicodeError) as e:
            excluded.append((deck_id, f"its file couldn't be read ({e})"))
            continue
        tier = parsed["meta"].get("Difficulty", "").strip().lower()
        if tier not in DIFFICULTIES:
            excluded.append((deck_id, f"its Difficulty {tier or '(none)'!r} isn't one Deck Lab knows"))
            continue
        record = _record("duels", path, root, parsed, tier)
        by_title.setdefault(record["duel_title"].casefold(), []).append(record)
    for versions in by_title.values():
        versions.sort(key=lambda r: (_distance(r["tier"]), r["id"]))
        records.append(versions[0])
        for other in versions[1:]:
            excluded.append((other["id"], f"another version of {versions[0]['duel_title']} "
                                          f"({versions[0]['tier']}) is kept"))
    for path in _files(root / "precons"):
        deck_id = f"gauntlet:forge/precons/{slug(path.stem)}"
        try:
            parsed = read_dck(path)
        except (OSError, UnicodeError) as e:
            excluded.append((deck_id, f"its file couldn't be read ({e})"))
            continue
        records.append(_record("precons", path, root, parsed, "precon"))
    records.sort(key=lambda r: r["id"])
    log(f"Forge: {len(records)} 60-card decks ({len(excluded)} left out)")
    return records, excluded


NAME_RE = re.compile(r"^(.*?)\s*\[([A-Za-z0-9]{2,8})\]\s*\[(\d{4})\]\s*$")


def commander_precons(root=None):
    """Forge's commanderprecons: [{"stem", "title", "set" (upper case, or ""), "year" (int or 0),
    "file", "cards"}], for precon_source's offline stand-in."""
    root = quest_dir(root)
    out = []
    for path in _files(root / "commanderprecons"):
        parsed = read_dck(path)
        name = parsed["meta"].get("Name") or path.stem
        found = NAME_RE.match(name)
        title = found[1] if found else name
        code = (found[2] if found else parsed["meta"].get("Set", "")).upper()
        if not parsed["cards"]["Commander"]:
            continue
        out.append({"stem": path.stem, "title": title, "set": code, "year": int(found[3]) if found else 0,
                    "file": _rel(path, root), "cards": parsed["cards"]})
    return out
