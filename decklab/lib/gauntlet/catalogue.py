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

from . import CATALOGUE_FORMAT, FORMATS, catalogue_path, edhrec_source, fixing, forge_source, precon_source

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
    """tags.tag (slice B's), or the identity-only fallback while it isn't there."""
    try:
        from . import tags
    except ImportError:
        return fallback_tag(kind, listed, themes)
    return tags.tag(kind, listed, themes)


def fallback_tag(kind, listed, themes=()):
    """FALLBACK ONLY, until lib/gauntlet/tags.py is merged: identity and colours from the card
    data, every deck "midrange", no tags or metrics."""
    names = [n for _, n in listed.get("Commander", [])] if kind == "commander" else \
        [n for _, n in listed.get("Commander", []) + listed.get("Main", [])]
    identity = fixing.identity_of(names)
    colours = set()
    for _, name in listed.get("Commander", []) + listed.get("Main", []):
        card = cards.card(name) or {}
        if not fixing.is_land(card):
            colours.update(c for c in card.get("colors", []) if c in fixing.WUBRG)
    order = lambda letters: "".join(c for c in fixing.WUBRG if c in letters)     # noqa: E731
    return {"identity": order(identity), "colours": order(colours & identity if kind == "commander" else colours),
            "style": {"primary": "midrange", "tags": [], "themes": list(themes)}, "metrics": {}}


# ------------------------------------------------------------ one deck

def _card_sha(listed, kind):
    from decklab.lib.forge.lists import _list_text      # lazily: lib/forge reads config.json
    return _list_text(listed, kind)[1]


def _entry(record, listed, tagged, fixes, problems, playable, tier, measured):
    return {"id": record["id"], "title": record["title"], "kind": record["kind"],
            "card_sha": _card_sha(listed, record["kind"]), "source": dict(record["source"]),
            "tier": tier, "bracket": measured,
            "identity": tagged["identity"], "colours": tagged["colours"], "style": tagged["style"],
            "metrics": tagged["metrics"], "fixes": fixes, "problems": problems, "playable": playable,
            "cards": listed}


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

def _records(fmt, sources, top, refresh, offline, log):
    records, excluded = [], []
    for source in sources:
        if source not in FORMAT_SOURCES[fmt]:
            continue
        if source == "edhrec":
            found = edhrec_source.decks(top, refresh, offline, log)
        elif source == "precons":
            found = precon_source.decks(offline=offline, root=FORGE_ROOT, log=log)
        else:
            try:
                found = forge_source.constructed_decks(FORGE_ROOT, log)
            except (OSError, KeyError) as e:
                found = [], [("gauntlet:forge", f"Forge's decks couldn't be read ({e})")]
        records += found[0]
        excluded += found[1]
    return records, excluded


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
    nothing. Prints the summary. Returns the catalogue."""
    if fmt not in FORMATS:
        raise GauntletError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    unknown = [s for s in sources if s not in SOURCES]
    if unknown:
        raise GauntletError(f"Unknown source {unknown[0]!r}: choose from {', '.join(SOURCES)}")
    card_data = _card_data(fmt, log)
    records, left_out = _records(fmt, sources, top, refresh, dry_run, log)
    decks, seen = [], set()
    for record in records:
        if record["id"] in seen:
            left_out.append((record["id"], "another deck has the same id"))
            continue
        seen.add(record["id"])
        decks.append(entry(record, LIMITS))
    decks.sort(key=lambda d: d["id"])
    catalogue = {"format": CATALOGUE_FORMAT, "kind": fmt,
                 "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "card_data": card_data,
                 "sha": catalogue_sha(decks), "decks": decks,
                 "excluded": [{"id": i, "reason": r} for i, r in left_out]}
    for line in summary(catalogue):
        log(line)
    if dry_run:
        log(f"Dry run: nothing saved (the catalogue would be {catalogue_path(fmt)}).")
    else:
        save(fmt, catalogue)
        log(f"Saved {catalogue_path(fmt)}.")
    return catalogue
