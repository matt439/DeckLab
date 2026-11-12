"""The gauntlet's runs (decklab/design/gauntlet.md section 6): a house deck against a sample of
outside sparring decks (EDHREC's average decks, Wizards precons, Forge's bundled decks), read by
colour, colour count, style and tier.

A gauntlet run is a field run (field.run_field) whose opponents are the sample's decks
(opponent_entries) instead of the house field, saved in a results folder of its own
(RESULTS_DIR), so Rankings, the Bradley-Terry ratings (field._bt_data), per-card stats and the
AI limits never see its games. The view has no rating: each group is the equal-weight average
of its opponents (seqstats.field_average), with its range and the spread across them, and the
range covers those sampled opponents only.

    RESULTS_DIR             <data>/forge/gauntlet/results
    catalogue(fmt)          the format's catalogue (lib/gauntlet/catalogue.load), or ForgeError
    entries(fmt, ids)       the catalogue decks with those ids as Forge entries (lists.entry_from_cards)
    draw(fmt, ...)          a sample chosen and saved (lib/gauntlet/sample); size "all" is every
                            playable deck the filters allow (sample.every)
    same_commander(fmt, commanders, save=True)
                            every playable deck of these commanders (lib/gauntlet/sample.same_commander,
                            E3-S49), saved unless save is False
    standard(fmt, save=False)
                            the format's standard sample (lib/gauntlet/sample.STANDARD, E3-S33): the
                            default draw, the one every deck's headline figure is against
    plan(deck_entry, sample, budget="fixed:100")
                            what a run would play now (field.plan over the sample)
    run(deck_entry, sample, budget="fixed:100", inflight=None, progress=None, stop=None, ...)
                            the run (field.run_field over the sample); its note
    view(deck_entry, sample, keep=None)
                            the deck against the sample: per opponent, per group and overall
    compare(deck_entry, before_entry, sample, keep_now, keep_before)
                            two lists' figures over the opponents both have rates against (E3-S34)
    has_notes(deck_entry, space), notes_keys(deck_entry, space, limit)
                            whether a list has run notes in the space, and the keys its runs played
    stamps(deck_entry, sample, cat, space), noted(fmt, space)
                            what the board's caches go by (E3-S35): each opponent's saved result
                            file and the list's run notes, as (mtime, size); the lists with run
                            notes in the space
    older(deck_entry, sample, keep, today_keys, space)
                            the list's results under an older engine, pilot or catalogue (E3-S34):
                            why they aren't shown, and the newest single-engine group's figure

The catalogue and sample modules (decklab/lib/gauntlet) are reached only through the small
wrappers below, which the tests replace."""
import json
from pathlib import Path

from decklab.lib.gauntlet import without

from . import common, engine, field, lists, saved, seqstats, reliability, views
from .common import ForgeError

RESULTS_DIR = common.DATA_DIR / "gauntlet" / "results"
FORMATS = ("commander", "constructed")          # lib/gauntlet's FORMATS
DEFAULT_BUDGET = "fixed:100"
DEFAULT_TIERS = {"commander": ("core", "upgraded"), "constructed": ("medium", "hard")}    # sample.STANDARD's
GROUPS = ("colour", "identity_size", "style", "tier")
COLOURS = (("W", "White"), ("U", "Blue"), ("B", "Black"), ("R", "Red"), ("G", "Green"))
SIZES = (("colourless", "Colourless"), ("mono", "Mono-colour"), ("two", "Two colours"),
         ("three", "Three colours"), ("four", "Four colours"), ("five", "Five colours"))
STYLES = ("aggro", "midrange", "control", "combo", "ramp")      # lib/gauntlet/tags' STYLES
TIERS = ("core", "upgraded", "precon", "easy", "medium", "hard", "very hard")
NO_CATALOGUE = ("There's no {fmt} gauntlet yet: build it on the PC with "
                "python -m decklab.lib.forge gauntlet build --format {fmt}.")
NOT_A_FORMAT = "A gauntlet's format is commander or constructed, not {fmt!r}."
WRONG_FORMAT = "That sample is of {sample} decks, but this deck plays {deck}."
MISSING = ("{n} of the sample's decks aren't playable in the {fmt} catalogue now (it was rebuilt?): "
           "draw a new sample.")
ONE = "one opponent, not a group"
OVERLAP = "overlapping: a deck of several colours counts in each"
CAVEAT = ("Each range covers these {m} sampled opponents only, not every deck of that colour, style or "
          "tier.")


# ============================================================ lib/gauntlet, through wrappers

def _load_catalogue(fmt):
    from decklab.lib.gauntlet import catalogue
    return catalogue.load(fmt)


def _build_catalogue(fmt, **options):
    from decklab.lib.gauntlet import catalogue
    return catalogue.build(fmt, **options)


def _choose(decks, size, **filters):
    from decklab.lib.gauntlet import sample
    return sample.choose(decks, size, **filters)


def _sample_id(catalogue_sha, filters, size, seed, **every):
    from decklab.lib.gauntlet import sample
    return sample.sample_id(catalogue_sha, filters, size, seed, **every)      # every= or commander=


def _save_sample(fmt, found):
    from decklab.lib.gauntlet import sample
    sample.save_sample(fmt, found)


def _load_sample(sample_id):
    from decklab.lib.gauntlet import sample
    return sample.load_sample(sample_id)


def _every(decks, **filters):
    from decklab.lib.gauntlet import sample
    return sample.every(decks, **filters)


def _same_commander(decks, commanders, **options):
    from decklab.lib.gauntlet import sample
    return sample.same_commander(decks, commanders, **options), sample.commander_key(commanders)


def _default_size(fmt):
    try:
        from decklab.lib.gauntlet import sample
        return int(sample.DEFAULT_SIZE[fmt])
    except (ImportError, AttributeError, KeyError, TypeError, ValueError):
        return {"commander": 20, "constructed": 24}[fmt]


# ============================================================ the catalogue and samples

def results_dir():
    """The gauntlet's results folder (RESULTS_DIR, read when called)."""
    return Path(RESULTS_DIR)


def format_of(deck_entry):
    """The gauntlet format a Forge entry plays: "commander" or "constructed"."""
    return "commander" if deck_entry["kind"] == "commander" else "constructed"


def _fmt(fmt):
    if fmt not in FORMATS:
        raise ValueError(NOT_A_FORMAT.format(fmt=fmt))
    return fmt


def catalogue(fmt):
    """The format's catalogue (the contract's dict); ForgeError when none has been built."""
    found = _load_catalogue(_fmt(fmt))
    if not found:
        raise ForgeError(NO_CATALOGUE.format(fmt=fmt))
    return found


def find(deck_id):
    """(format, catalogue entry) of a gauntlet deck id in either catalogue, or None."""
    for fmt in FORMATS:
        found = _load_catalogue(fmt)
        for deck in (found or {}).get("decks") or []:
            if deck.get("id") == deck_id:
                return fmt, deck
    return None


def _to_entry(deck):
    """A catalogue entry as a Forge entry (its source kept beside the list)."""
    return lists.entry_from_cards(deck["id"], deck["title"], deck["kind"], deck["cards"],
                                  {"gauntlet": dict(deck.get("source") or {})})


def _picked(cat, ids):
    """([(catalogue entry, Forge entry)] in ids' order, [ids not playable in cat])."""
    by_id = {d.get("id"): d for d in cat.get("decks") or []}
    pairs, missing = [], []
    for deck_id in ids:
        deck = by_id.get(deck_id)
        if deck is None or not deck.get("playable"):
            missing.append(deck_id)
        else:
            pairs.append((deck, _to_entry(deck)))
    return pairs, missing


def entries(fmt, ids):
    """The catalogue decks with these ids, as Forge entries in ids' order. ForgeError when there's
    no catalogue, or an id isn't a playable deck of it now."""
    cat = catalogue(fmt)
    pairs, missing = _picked(cat, list(ids))
    if missing:
        raise ForgeError(MISSING.format(n=len(missing), fmt=fmt))
    return [e for _, e in pairs]


def filters(fmt, colours=None, styles=None, tiers=None):
    """The sample filters with the format's default tiers: {"colours", "styles", "tiers"}."""
    colours = "".join(c for c in "WUBRG" if c in (colours or "").upper()) or None
    styles = sorted(set(styles)) if styles else None
    tiers = sorted(set(tiers or DEFAULT_TIERS[_fmt(fmt)]))
    return {"colours": colours, "styles": styles, "tiers": tiers}


def draw(fmt, size=None, colours=None, styles=None, tiers=None, seed="", save=True, cat=None):
    """A sample of the format's catalogue (lib/gauntlet/sample.choose with these filters; the
    default tiers and size when not given), saved unless save is False: the contract's sample
    dict. size "all" is every playable deck the filters allow, near-duplicates included
    (sample.every; the dict's size their number, and "all": True). cat, the format's catalogue
    already loaded, saves reading it again. ForgeError when there's no catalogue."""
    cat = cat if cat is not None else catalogue(fmt)
    chosen_filters = filters(fmt, colours, styles, tiers)
    every = size == "all"
    if every:
        chosen = _every(cat.get("decks") or [], seed=seed or "", **chosen_filters)
        size = len(chosen)
    else:
        size = int(size) if size else _default_size(fmt)
        chosen = _choose(cat.get("decks") or [], size, seed=seed or "", **chosen_filters)
    sid = _sample_id(cat.get("sha"), chosen_filters, size, seed or "", **({"every": True} if every else {}))
    found = {"id": sid, "format": fmt, "catalogue_sha": cat.get("sha"), "filters": chosen_filters, "size": size,
             "seed": seed or "",
             "decks": [d["id"] for d in chosen]}
    if every:
        found["all"] = True
    if save:
        _save_sample(fmt, found)
    return found


def same_commander(fmt, commanders, save=True, cat=None):
    """"Same commander" (E3-S49): every playable Commander deck of the catalogue whose commanders are
    commanders (a partner pair in either order), core, upgraded and precon alike, most popular first,
    as the contract's sample dict with "commander": the names, sorted. Its id hashes the commanders,
    so it's never a balanced or All sample's. Saved unless save is False (an empty one never is);
    cat as draw's. ValueError for a format other than commander or no commander; ForgeError when
    there's no catalogue."""
    if _fmt(fmt) != "commander":
        raise ValueError("Same commander is only for Commander decks.")
    names = sorted({str(n).strip() for n in commanders or () if str(n).strip()})
    if not names:
        raise ValueError("This deck has no commander yet, so there's none to match.")
    cat = cat if cat is not None else catalogue(fmt)
    chosen, key = _same_commander(cat.get("decks") or [], names)
    chosen_filters = {"colours": None, "styles": None, "tiers": None}
    found = {"id": _sample_id(cat.get("sha"), chosen_filters, len(chosen), "", commander=key), "format": fmt,
             "catalogue_sha": cat.get("sha"), "filters": chosen_filters, "size": len(chosen), "seed": "",
             "decks": [d["id"] for d in chosen], "commander": names}
    if save and chosen:
        _save_sample(fmt, found)
    return found


def standard(fmt, save=False, cat=None):
    """The format's standard sample: the default draw (DEFAULT_TIERS, the default size, no colour or
    style filter, seed ""), the same deck set as lib/gauntlet/sample.standard_sample. Not saved
    unless save; cat as draw's. ForgeError when there's no catalogue."""
    return draw(fmt, seed="", save=save, cat=cat)


def sample(sample_id):
    """A saved sample by id; ValueError when there's none."""
    found = _load_sample(sample_id)
    if not found:
        raise ValueError(f"There's no saved gauntlet sample {sample_id}.")
    return found


def _check(deck_entry, chosen):
    if chosen.get("format") != format_of(deck_entry):
        raise ValueError(WRONG_FORMAT.format(sample=chosen.get("format"), deck=format_of(deck_entry)))


# ============================================================ planning and running

def plan(deck_entry, chosen, budget=DEFAULT_BUDGET, exclude_ids=()):
    """What a gauntlet run of deck_entry against the sample would play now (nothing plays):
    field.plan's answer over the sample's decks and the gauntlet's results, with "sample".
    exclude_ids: sample decks left out (a trial deck's own precon, gauntlet.trial_excluded)."""
    _check(deck_entry, chosen)
    chosen = without(chosen, exclude_ids)
    opponents = entries(chosen["format"], chosen["decks"])
    found = field.plan(deck_entry, budget, results_dir=results_dir(), opponent_entries=opponents)
    found["sample"] = chosen["id"]
    return found


def run(deck_entry, chosen, budget=DEFAULT_BUDGET, inflight=None, progress=None, stop=None, *,
        by="command line", local=False, pool=None, seed_base=None, log_dir=None, log_every=1, space="home",
        exclude_ids=()):
    """Play deck_entry against the sample (field.run_field with the sample's decks as its
    opponents and the gauntlet's results folder): its note. stop, an Event, stops it at the next
    progress report as the page's Stop does (common.Stopped, raised again once every pair run has
    saved its games). ValueError for a budget or a sample of the other format, ForgeError as
    run_field's and entries'. exclude_ids as plan's."""
    _check(deck_entry, chosen)
    chosen = without(chosen, exclude_ids)
    opponents = entries(chosen["format"], chosen["decks"])
    folder = results_dir()
    folder.mkdir(parents=True, exist_ok=True)

    def watched(done, total, detail):
        if stop is not None and stop.is_set():
            raise common.Stopped("Stopped")
        if progress is not None:
            progress(done, total, detail)
    # Which sample the run played (E3-S34): nothing reads it yet; a later slice can tell a rebuilt
    # standard sample's runs apart.
    extra = {"sample": chosen.get("id"), "catalogue_sha": chosen.get("catalogue_sha"),
             "standard": chosen.get("id") == standard(chosen["format"])["id"]}
    return field.run_field(deck_entry, budget, by=by, progress=watched, results_dir=folder, pool=pool,
                           local=local, seed_base=seed_base, log_dir=log_dir, log_every=log_every,
                           inflight=inflight, space=space, opponent_entries=opponents, note_extra=extra)


# ============================================================ the view

def _rate(numbers):
    if not numbers or numbers.get("value") is None:
        return None
    return {"value": field._r(numbers["value"]), "low": field._r(numbers.get("low")),
            "high": field._r(numbers.get("high"))}


def _opponent(deck, row):
    """One sampled opponent's row of the view: "verdict" its lead in words (verdict()), "updated"
    when its games were last added to."""
    return {"id": deck["id"], "title": deck["title"], "tier": deck.get("tier"),
            "identity": deck.get("identity") or "", "colours": deck.get("colours") or "",
            "style": (deck.get("style") or {}).get("primary"), "key": row["key"], "games": row["n"],
            "rate": _rate(row["numbers"]), "lead": row["lead"], "verdict": verdict(row["lead"]),
            "not_meaningful": row["not_meaningful"], "problem": row["problem"], "updated": row.get("updated"),
            **({"stalled": row["stalled_all"]} if row.get("stalled_all", {}).get("caution") else {}),
            "clock": views.clock_of(None if row["not_meaningful"] else row.get("turns")),
            "source": deck.get("source")}


TALLY = {"ahead": "ahead", "slightly ahead": "ahead", "about even": "even", "behind": "behind",
         "slightly behind": "behind", "not settled": "unsettled"}


def _tally(opponents):
    """{"ahead", "even", "behind", "unsettled"}: how many opponents' verdicts are each (none counted
    without games)."""
    out = {"ahead": 0, "even": 0, "behind": 0, "unsettled": 0}
    for o in opponents:
        key = TALLY.get(o.get("verdict"))
        if key:
            out[key] += 1
    return out


def _group(key, label, members, extra=None):
    """One group's row: {"key", "label", "opponents", "games", "rate", "low", "high", "spread",
    "note", "clock"} over members [(catalogue entry, field._rows row)]. "clock" (E3-S51) is
    views.clock_of over the members' games pooled (never their medians averaged), leaving out the
    opponents whose results don't mean something, as the rate does."""
    counted = [r["numbers"] for _, r in members if r["numbers"] and not r["not_meaningful"]]
    of = sum(1 for _, r in members if not r["not_meaningful"])
    try:
        average = seqstats.field_average(counted, of=of) if counted else None
    except NotImplementedError:
        average = None
    values = [n["value"] for n in counted if n.get("value") is not None]
    notes = [extra] if extra else []
    played = sum(1 for _, row in members if row.get("n") and not row["not_meaningful"])
    games = sum(row["n"] for _, row in members if not row["not_meaningful"])
    thin = played < reliability.MIN_GROUP_OPPONENTS or games < reliability.MIN_GROUP_GAMES
    if thin:
        notes.append(f"Too few compared opponents/games: need at least {reliability.MIN_GROUP_OPPONENTS} opponents and {reliability.MIN_GROUP_GAMES} games.")
    stalled = reliability.merge_stalled([row for _, row in members])
    if stalled["caution"]:
        notes.append(stalled["words"])
    if len(members) < 2:
        notes.insert(0, ONE)
    elif average and average.get("partial"):
        notes.append(f"based on {average['counted']} of {of} opponents with games on the play and on the draw")
    return {"key": key, "label": label, "opponents": len(members), "games": sum(r["n"] for _, r in members),
            **({"thin": True} if thin else {}),
            "rate": field._r((average or {}).get("value")), "low": field._r((average or {}).get("low")),
            "high": field._r((average or {}).get("high")),
            "spread": [field._r(min(values)), field._r(max(values))] if values else None,
            "note": "; ".join(notes),
            "clock": views.clock_of(views.pool_turns(row.get("turns") for _, row in members
                                                     if not row["not_meaningful"]))}


def _in_order(found, order):
    return [k for k in order if k in found] + sorted(k for k in found if k not in order)


def _groups(members):
    """The view's groups: {"colour", "identity_size", "style", "tier": [group rows]}, only the
    groups with opponents in them."""
    colour = []
    for letter, label in COLOURS:
        inside = [m for m in members if letter in (m[0].get("identity") or "")]
        if inside:
            colour.append(_group(letter, label, inside, OVERLAP))
    colourless = [m for m in members if not m[0].get("identity")]
    if colourless:
        colour.append(_group("C", "Colourless", colourless))
    size = []
    for count, (key, label) in enumerate(SIZES):
        inside = [m for m in members if len(m[0].get("identity") or "") == count]
        if inside:
            size.append(_group(key, label, inside))
    out = {"colour": colour, "identity_size": size}
    for name, order, read in (("style", STYLES, lambda d: (d.get("style") or {}).get("primary") or "unknown"),
                              ("tier", TIERS, lambda d: d.get("tier") or "unknown")):
        found = {}
        for m in members:
            found.setdefault(read(m[0]), []).append(m)
        out[name] = [_group(k, k[:1].upper() + k[1:], found[k]) for k in _in_order(found, order)]
    return out


def view(deck_entry, chosen, keep=None, cat=None, exclude_ids=()):
    """deck_entry against the sample (it never plays a game): {"deck": id, "sample": id, "format",
    "opponents": [rows, hardest first (lowest range low)], "groups" (_groups), "overall" (a group
    row over every opponent: the equal-weight average), "played" (opponents with games), "of" (the
    sample's opponents in the catalogue now), "tally" (_tally), "updated" (the newest opponent's
    "updated", or None), "games", "note" (the caveat: these sampled opponents only), "notes" (decks
    gone from the catalogue, a rebuilt catalogue), "clock_label" and "clock_note" (E3-S51: what
    the opponents', groups' and overall "clock" (views.clock_of) count, and for Commander that the
    gauntlet isn't a pod, else None)}. cat as draw's (the sample's format's). ValueError
    for a sample of the other format, ForgeError with no catalogue. exclude_ids as plan's; a sample
    deck with deck_entry's own list (a mirror) is left out too (_members)."""
    _check(deck_entry, chosen)
    chosen = without(chosen, exclude_ids)
    fmt = chosen["format"]
    cat = cat if cat is not None else catalogue(fmt)
    missing, members = _members(deck_entry, chosen, keep, cat)
    notes = []
    if missing:
        notes.append(f"{len(missing)} of the sample's decks aren't playable in the catalogue now, so they're "
                     "left out.")
    if chosen.get("catalogue_sha") != cat.get("sha"):
        notes.append("The catalogue was rebuilt after this sample was drawn.")
    rows = [row for _, row in members]
    opponents = [_opponent(deck, row) for deck, row in members]
    opponents.sort(key=lambda o: (o["rate"] is None, (o["rate"] or {}).get("low") or 0, o["title"].casefold()))
    dates = [o["updated"] for o in opponents if isinstance(o.get("updated"), str)]
    return {"deck": deck_entry["id"], "sample": chosen["id"], "format": fmt, "opponents": opponents,
            "groups": _groups(members), "overall": _group("all", "All these opponents", members),
            "played": sum(1 for r in rows if r["n"]), "of": len(members), "tally": _tally(opponents),
            "updated": max(dates) if dates else None, "games": sum(r["n"] for r in rows),
            "note": CAVEAT.format(m=len(members)), "notes": notes,
            "clock_label": views.CLOCK_LABEL[fmt],
            "clock_note": views.CLOCK_POD_NOTE if fmt == "commander" else None}


def _unmirrored(deck_entry, pairs):
    """pairs ([(catalogue deck, entry)]) without one whose list is deck_entry's own (a mirror):
    the opponents view, older and stamps count."""
    sha = deck_entry.get("card_sha")
    return [(deck, e) for deck, e in pairs if not (sha and e.get("card_sha") == sha)]


def _members(deck_entry, chosen, keep, cat):
    """([sample ids not playable in cat], [(catalogue entry, field._rows row)] in the sample's order),
    without a sample deck whose list is deck_entry's own (the same card_sha: a mirror, as
    field._opponents leaves out of a run)."""
    pairs, missing = _picked(cat, chosen.get("decks") or [])
    pairs = _unmirrored(deck_entry, pairs)
    rows = field._rows(deck_entry, [e for _, e in pairs], results_dir(), keep)
    return missing, [(deck, row) for (deck, _), row in zip(pairs, rows)]


# ============================================================ before and after (E3-S34)

def _figure(group):
    return {"rate": group["rate"], "low": group["low"], "high": group["high"]}


def _rated(row):
    return not row["not_meaningful"] and _rate(row["numbers"]) is not None


def compare(deck_entry, before_entry, chosen, keep_now=None, keep_before=None, cat=None):
    """Two lists of a deck against the same sample: {"same": N, "ids": [the N opponents' ids],
    "before": {"rate", "low", "high"}, "now": {...}}, each figure the equal-weight average over
    those N opponents only (the ones both lists have rates against); None when there are none.
    No claim is made about the difference."""
    _check(deck_entry, chosen)
    cat = cat if cat is not None else catalogue(chosen["format"])
    _, now = _members(deck_entry, chosen, keep_now, cat)
    _, before = _members(before_entry, chosen, keep_before, cat)
    rated = {deck["id"] for deck, row in before if _rated(row)}
    common_ids = [deck["id"] for deck, row in now if _rated(row) and deck["id"] in rated]
    if not common_ids:
        return None
    pick = set(common_ids)
    return {"same": len(common_ids), "ids": common_ids,
            "before": _figure(_group("all", "", [m for m in before if m[0]["id"] in pick])),
            "now": _figure(_group("all", "", [m for m in now if m[0]["id"] in pick]))}


def has_notes(deck_entry, space="home"):
    """True when a list ({"card_sha", "kind"} will do) has gauntlet run notes in the space."""
    return field._notes_path(deck_entry, results_dir(), space=space).exists()


def _stat(path):
    """(mtime_ns, size) of a file, or None when there's none (or it can't be read)."""
    try:
        found = path.stat()
    except OSError:
        return None
    return found.st_mtime_ns, found.st_size


def stamps(deck_entry, chosen, cat, space="home"):
    """What the list's view of the sample is worked out from, as stats (it reads no file): one
    (matchup key, (mtime_ns, size) or None) per playable sample opponent, in the sample's order,
    the keys field._pair_state reads (today's engine's: call it inside engine.held()), then
    ("notes", ...) of the list's run notes in the space. The same stamps mean the same view."""
    pairs = _unmirrored(deck_entry, _picked(cat, chosen.get("decks") or [])[0])
    folder = results_dir()
    out = []
    for _, opponent in pairs:
        try:
            key = lists.matchup_key(deck_entry, opponent)
        except ForgeError:
            out.append((None, None))
            continue
        out.append((key, _stat(folder / f"{key}.json")))
    out.append(("notes", _stat(field._notes_path(deck_entry, folder, space=space))))
    return tuple(out)


def noted(fmt, space="home"):
    """{card_sha: (mtime_ns, size)} of the lists with gauntlet run notes of the format in the
    space (their file names only: nothing is read)."""
    suffix = f"-{lists.fmt_for(_fmt(fmt))}-{space}.json"
    folder = common._results_dir(results_dir()) / field.NOTES_DIR
    out = {}
    try:
        paths = list(folder.glob(f"*{suffix}"))
    except OSError:
        return out
    for path in paths:
        sha = path.name[:-len(suffix)]
        if len(sha) == 64 and all(c in "0123456789abcdef" for c in sha):
            stat = _stat(path)
            if stat is not None:
                out[sha] = stat
    return out


def notes_keys(deck_entry, space="home", limit=300):
    """The matchup keys the list's gauntlet runs in the space played (its run notes, newest run
    first), at most limit distinct ones; [] when it has none. Only this space's notes are read."""
    try:
        found = json.loads(field._notes_path(deck_entry, results_dir(), space=space).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    runs = found.get("runs") if isinstance(found, dict) else None
    out, seen = [], set()
    for note in reversed(runs if isinstance(runs, list) else []):
        for key in (note.get("per_opponent") or {}) if isinstance(note, dict) else ():
            if isinstance(key, str) and key not in seen:
                seen.add(key)
                out.append(key)
                if len(out) >= limit:
                    return out
    return out


REASONS = ("forge", "settings", "catalogue", "pilot")   # older()'s reasons; on a tie the first


def _opponent_side(result, card_sha):
    """(a stored result's side that isn't the list's, its newest seen_as id), or (None, None)."""
    for side in result.get("sides") or []:
        if isinstance(side, dict) and side.get("card_sha") != card_sha:
            seen = [s for s in side.get("seen_as") or [] if isinstance(s, dict)]
            return side, (seen[-1].get("id") if seen else side.get("id"))
    return None, None


def _why(result, side, opponent, eng, deck_entry):
    """Why a stored result isn't under today's key: "catalogue" (the opponent's list changed in a
    rebuild), "forge" (another Forge release or engine kind), "settings" (other engine settings or
    card-script overrides) or "pilot" (the AI profile or its file changed)."""
    if side.get("card_sha") != opponent["card_sha"]:
        return "catalogue"
    stored = result.get("engine") if isinstance(result.get("engine"), dict) else {}
    now = engine._fields(eng)
    if any(stored.get(k) != now.get(k) for k in ("forge", "kind")):
        return "forge"
    if any(stored.get(k) != now.get(k) for k in engine.ENGINE_FIELDS if k != "overrides"):
        return "settings"
    try:
        overrides = engine._matchup_overrides(eng, [deck_entry, opponent])
    except Exception:           # the overrides can't be told now: they aren't the reason claimed
        overrides = stored.get("overrides")
    return "settings" if stored.get("overrides") != overrides else "pilot"


def _when(result):
    return str(result.get("updated") or "")


def older(deck_entry, chosen, keep=None, cat=None, today_keys=(), space="home", limit=300, played=()):
    """The list's saved results against the sample's decks that today's keys don't find (an older
    Forge, other settings, another pilot, or an opponent's list changed in a rebuild), from its
    run notes in the space (at most limit keys): None when there are none; {"reason": "unknown",
    ...} when today's engine can't be confirmed; else {"reason", "opponents", "of", "updated",
    "overall"} of the newest group of one engine (the newest result per opponent; "overall" its
    equal-weight figure {"rate", "low", "high"}, None without a rate). Several engines are never
    mixed into one figure. keep as view's; today_keys the view's keys, left out; played the
    opponents' ids today's keys already have games against, whose older results are replaced and
    so left out too (None once every one is)."""
    _check(deck_entry, chosen)
    cat = cat if cat is not None else catalogue(chosen["format"])
    pairs = _unmirrored(deck_entry, _picked(cat, chosen.get("decks") or [])[0])     # view's "of"
    by_id = {deck["id"]: (deck, e) for deck, e in pairs}
    skip, replaced = set(today_keys or ()), set(played or ())
    by_id = {i: pair for i, pair in by_id.items() if i not in replaced}
    stale = []
    for key in notes_keys(deck_entry, space, limit) if by_id else ():
        if key in skip:
            continue
        result = saved.load(key, results_dir())
        if result is None or (keep is not None and not keep(result)):
            continue
        side, deck_id = _opponent_side(result, deck_entry["card_sha"])
        if side is not None and deck_id in by_id:
            stale.append((result, side, deck_id))
    if not stale:
        return None
    eng = engine.today()
    if not eng.get("complete"):
        return {"reason": "unknown", "opponents": None, "of": len(pairs), "updated": None, "overall": None}
    groups = {}
    for found in stale:
        stored = found[0].get("engine") if isinstance(found[0].get("engine"), dict) else {}
        groups.setdefault(engine._canonical(stored), []).append(found)
    newest = max(groups.values(), key=lambda group: max(_when(r) for r, _, _ in group))
    picked = {}
    for result, side, deck_id in newest:
        if deck_id not in picked or _when(result) > _when(picked[deck_id][0]):
            picked[deck_id] = (result, side)
    reasons = [_why(r, s, by_id[i][1], eng, deck_entry) for i, (r, s) in picked.items()]
    reason = max(REASONS, key=lambda name: (reasons.count(name), -REASONS.index(name)))
    members = [(by_id[i][0], field._row(deck_entry, by_id[i][1],
                                        field._numbers({"key": r.get("key")}, deck_entry, r)))
               for i, (r, _) in picked.items()]
    group = _group("all", "", members)
    dates = [_when(r) for r, _ in picked.values() if r.get("updated")]
    return {"reason": reason, "opponents": len(picked), "of": len(pairs), "updated": max(dates) if dates else None,
            "overall": _figure(group) if group["rate"] is not None else None}


def verdict(lead):
    """An opponent row's lead in a word or two from the deck's side (views' words), or None."""
    if not lead:
        return None
    if lead.get("side") == 1:
        return "slightly behind" if lead.get("verdict") == "slightly_ahead" else "behind"
    return str(lead.get("verdict", "")).replace("_", " ") or None

