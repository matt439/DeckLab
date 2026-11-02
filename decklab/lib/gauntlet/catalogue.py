"""The gauntlet's catalogue (design sections 2 and 3): every sparring deck of one format,
normalised, fixed, measured, screened and tagged, in catalogue_path(fmt).

    from decklab.lib.gauntlet import catalogue
    catalogue.load("commander")             # the saved catalogue, or None
    catalogue.build("constructed")          # fetch, check and save a new one (command line only)

The file is {"format": 1, "kind", "built", "card_data" (the card data's date, or None), "sha" (of
every deck's id and card_sha: the catalogue version a sample names), "decks": [entry],
"excluded": [{"id", "reason"}]}; an entry is the design's schema (its section 2). build() never
runs from a page request: the command line calls it (forge/cli_gauntlet.py), and only it fetches.
"""
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone

from decklab.lib import cards

from . import CATALOGUE_FORMAT, FORMATS, catalogue_path, edhrec_source, fixing, forge_source, precon_source, tags

SOURCES = ("edhrec", "precons", "forge")
FORMAT_SOURCES = {"commander": ("edhrec", "precons"), "constructed": ("forge",)}
LIMITS = None           # None: forge.ai.ai_limits; the tests hand in a fake script table's
FORGE_ROOT = None       # None: the configured Forge's res/quest; the tests point it at fixture files


class GauntletError(RuntimeError):
    """The catalogue can't be built (no card data, an unknown format or source)."""


# ------------------------------------------------------------ the file

def load(fmt):
    """The saved catalogue of one format, or None when there's none (or it can't be read)."""
    try:
        data = json.loads(catalogue_path(fmt).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != CATALOGUE_FORMAT or data.get("kind") != fmt \
            or not isinstance(data.get("decks"), list):
        return None
    return data


def save(fmt, catalogue):
    """Write a catalogue atomically (a reader sees the old file or the new one, never half)."""
    path = catalogue_path(fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(catalogue, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def catalogue_sha(decks):
    """The sha256 of the decks' ids and card_shas, in id order."""
    pairs = sorted([d["id"], d["card_sha"]] for d in decks)
    return hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ tagging

def _tag(kind, listed, themes):
    """tags.tag's identity, colours, style and metrics (themes already cut to the 25% share)."""
    return tags.tag(kind, listed, themes)


# ------------------------------------------------------------ one deck

def _card_sha(listed, kind):
    from decklab.lib.forge.lists import _list_text      # lazily: lib/forge reads config.json
    return _list_text(listed, kind)[1]


def _entry(record, listed, tagged, fixes, problems, playable, tier, measured):
    made = {"id": record["id"], "title": record["title"], "kind": record["kind"],
            "card_sha": _card_sha(listed, record["kind"]), "source": dict(record["source"]),
            "tier": tier, "bracket": measured,
            "identity": tagged["identity"], "colours": tagged["colours"], "style": tagged["style"],
            "metrics": tagged["metrics"], "fixes": fixes, "problems": problems, "playable": playable,
            "cards": listed}
    if record.get("duel_title"):
        made["duel_title"] = record["duel_title"]     # a Forge duel's Title: a sample takes one version of it
    return made


def _commander_entry(record, limits):
    problems = list(record.get("problems") or [])
    commanders, unknown = fixing.resolve([[1, n] for n in record["commanders"]])
    main, unknown_main = fixing.resolve(record["cards"])
    unknown += unknown_main
    if unknown:
        problems.append("Not Scryfall cards: " + ", ".join(sorted(set(unknown))) + ".")
        listed = {"Commander": [[1, n] for n in record["commanders"]], "Main": [list(x) for x in record["cards"]]}
        return _entry(record, listed, _tag("commander", {"Commander": commanders, "Main": main},
                                           record.get("themes") or []),
                      [], problems, False, record["tier"], None)
    fixed = fixing.fix_commander([n for _, n in commanders], main)
    listed, fixes = fixed["cards"], fixed["fixes"]
    problems += fixed["problems"]
    playable = fixed["playable"] and not record.get("problems")
    tier, measured = record["tier"], None
    try:
        measured, _, _ = fixing.bracket(listed)
        tier, moved = fixing.retier(tier, measured)
        if moved:
            fixes.append(moved)
    except (cards.INDEX_ERRORS + (TypeError,)) as e:
        problems.append(f"Its bracket couldn't be measured ({e}).")
    if playable:
        playable = _screen(listed, "commander", limits, problems)
    return _entry(record, listed, _tag("commander", listed, record.get("themes") or []),
                  fixes, problems, playable, tier, measured)


def _constructed_entry(record, limits):
    problems = list(record.get("problems") or [])
    listed = {"Commander": [], "Main": [list(x) for x in record["cards"]]}
    resolved, unknown = fixing.resolve(listed["Main"])
    if unknown:
        problems.append("Not Scryfall cards: " + ", ".join(sorted(set(unknown))) + ".")
    playable = not problems
    if playable:
        playable = _screen(listed, "constructed", limits, problems)
    return _entry(record, listed, _tag("constructed", {"Commander": [], "Main": resolved}, ()),
                  [], problems, playable, record["tier"], None)


def _screen(listed, kind, limits, problems):
    """True when Forge's AI can play the list (fixing.screen), its notes added to problems."""
    reason, notes = fixing.screen(listed, kind, limits)
    problems.extend(notes)
    if reason:
        problems.append(reason)
    return reason is None


def entry(record, limits=None):
    """A catalogue entry from a source's raw record."""
    if record["kind"] == "commander":
        return _commander_entry(record, limits)
    return _constructed_entry(record, limits)


# ------------------------------------------------------------ the build

SOURCE_PREFIX = {"edhrec": "gauntlet:edhrec/", "precons": "gauntlet:precon/", "forge": "gauntlet:forge/"}


def applicable(fmt, sources):
    """The sources of sources that serve the format, in sources' order."""
    return tuple(s for s in sources if s in FORMAT_SOURCES[fmt])


def _source_of(deck_id):
    return next((s for s, prefix in SOURCE_PREFIX.items() if str(deck_id).startswith(prefix)), None)


def _records(fmt, sources, top, refresh, offline, log):
    """(records, excluded, [sources that gave no deck but left some out: a failed fetch])."""
    records, excluded, failed = [], [], []
    for source in applicable(fmt, sources):
        if source == "edhrec":
            found = edhrec_source.decks(top, refresh, offline, log)
        elif source == "precons":
            found = precon_source.decks(offline=offline, root=FORGE_ROOT, log=log)
        else:
            try:
                found = forge_source.constructed_decks(FORGE_ROOT, log)
            except (OSError, KeyError) as e:
                found = [], [("gauntlet:forge", f"Forge's decks couldn't be read ({e})")]
        if not found[0] and found[1]:
            failed.append(source)
        records += found[0]
        excluded += found[1]
    return records, excluded, failed


def _kept(fmt, sources, log):
    """(decks, excluded) of the saved catalogue from the format's sources not being rebuilt, so a
    build of one source keeps the others' decks."""
    others = [s for s in FORMAT_SOURCES[fmt] if s not in sources]
    old = load(fmt) if others else None
    if not old:
        return [], []
    decks = [d for d in old["decks"] if _source_of(d.get("id")) in others]
    excluded = [(e["id"], e["reason"]) for e in old.get("excluded") or []
                if isinstance(e, dict) and _source_of(e.get("id")) in others]
    if decks:
        log(f"Kept {len(decks)} decks of the saved catalogue's {', '.join(others)} (not rebuilt).")
    return decks, excluded


def _card_data(fmt, log):
    """The card data's date, warning when it's older than Wizards' last announcement."""
    try:
        bulk = cards.info().get("bulk") or {}
    except cards.INDEX_ERRORS as e:
        raise GauntletError(f"The card data can't be read ({e}). Run: python -m decklab.lib.cards update") from None
    when = bulk.get("default_cards") if isinstance(bulk.get("default_cards"), str) else None
    if fmt == "commander":
        try:
            from decklab.lib.stats import commander
            dates = commander._data_dates()
            if dates["cards_older_than_announcement"]:
                log("Warning: the card data is older than Wizards' last Commander announcement, so Game "
                    "Changers and brackets may be out of date. Run: python -m decklab.lib.cards update")
        except (OSError, ValueError, KeyError, TypeError):
            log("Warning: Wizards' last Commander announcement couldn't be compared with the card data.")
    return when[:10] if when else None


def summary(catalogue):
    """Lines of counts by tier, colour identity and style, then each excluded deck and why."""
    playable = [d for d in catalogue["decks"] if d["playable"]]
    lines = [f"{len(playable)} playable of {len(catalogue['decks'])} {catalogue['kind']} decks."]
    for label, key in (("tier", lambda d: d["tier"]), ("identity", lambda d: d["identity"] or "C"),
                       ("style", lambda d: d["style"]["primary"])):
        counts = Counter(key(d) for d in playable)
        lines.append(f"By {label}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())))
    for d in catalogue["decks"]:
        if not d["playable"]:
            lines.append(f"Not playable: {d['id']}: {' '.join(d['problems']) or 'no reason recorded'}")
    for item in catalogue.get("excluded", []):
        lines.append(f"Left out: {item['id']}: {item['reason']}")
    return lines


def build(fmt, sources=SOURCES, top=100, refresh=False, dry_run=False, log=print):
    """Build a format's catalogue from its sources (edhrec and precons for Commander, forge for
    60-card) and save it, unless dry_run, which fetches nothing (cached copies only) and saves
    nothing. Prints the summary. Returns the catalogue. The decks of the format's sources not
    asked for are kept from the saved catalogue. GauntletError (and nothing saved) when none of
    sources serves the format, or a source gave no deck at all (a failed fetch with no cached
    copy): the saved catalogue stays as it was."""
    if fmt not in FORMATS:
        raise GauntletError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        raise GauntletError(f"Unknown source {unknown[0]!r}: choose from {', '.join(SOURCES)}")
    if not applicable(fmt, sources):
        raise GauntletError(f"None of {', '.join(sources)} is a source of the {fmt} gauntlet "
                            f"(its sources are {', '.join(FORMAT_SOURCES[fmt])}).")
    card_data = _card_data(fmt, log)
    records, left_out, failed = _records(fmt, sources, top, refresh, dry_run, log)
    kept, kept_out = _kept(fmt, sources, log)
    decks, seen = [], set()
    for record in records:
        if record["id"] in seen:
            left_out.append((record["id"], "another deck has the same id"))
            continue
        seen.add(record["id"])
        decks.append(entry(record, LIMITS))
    decks += [d for d in kept if d["id"] not in seen]
    left_out += kept_out
    decks.sort(key=lambda d: d["id"])
    catalogue = {"format": CATALOGUE_FORMAT, "kind": fmt,
                 "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "card_data": card_data,
                 "sha": catalogue_sha(decks), "decks": decks,
                 "excluded": [{"id": i, "reason": r} for i, r in left_out]}
    for line in summary(catalogue):
        log(line)
    if failed:
        raise GauntletError(f"{', '.join(failed)} gave no {fmt} decks (see above), so nothing was saved: "
                            f"{catalogue_path(fmt)} is kept as it was.")
    if dry_run:
        log(f"Dry run: nothing saved (the catalogue would be {catalogue_path(fmt)}).")
    else:
        save(fmt, catalogue)
        log(f"Saved {catalogue_path(fmt)}.")
    return catalogue
