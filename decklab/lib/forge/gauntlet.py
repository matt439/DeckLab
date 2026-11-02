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
    draw(fmt, ...)          a sample chosen and saved (lib/gauntlet/sample)
    plan(deck_entry, sample, budget="fixed:100")
                            what a run would play now (field.plan over the sample)
    run(deck_entry, sample, budget="fixed:100", inflight=None, progress=None, stop=None, ...)
                            the run (field.run_field over the sample); its note
    view(deck_entry, sample, keep=None)
                            the deck against the sample: per opponent and per group

The catalogue and sample modules (decklab/lib/gauntlet) are reached only through the small
wrappers below, which the tests replace."""
from pathlib import Path

from . import common, field, lists, seqstats
from .common import ForgeError

RESULTS_DIR = common.DATA_DIR / "gauntlet" / "results"
FORMATS = ("commander", "constructed")          # lib/gauntlet's FORMATS
DEFAULT_BUDGET = "fixed:100"
DEFAULT_TIERS = {"commander": ("core",), "constructed": ("medium", "hard")}
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


def _sample_id(catalogue_sha, filters, size, seed):
    from decklab.lib.gauntlet import sample
    return sample.sample_id(catalogue_sha, filters, size, seed)


def _save_sample(fmt, found):
    from decklab.lib.gauntlet import sample
    sample.save_sample(fmt, found)


def _load_sample(sample_id):
    from decklab.lib.gauntlet import sample
    return sample.load_sample(sample_id)


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


def draw(fmt, size=None, colours=None, styles=None, tiers=None, seed="", save=True):
    """A sample of the format's catalogue (lib/gauntlet/sample.choose with these filters; the
    default tiers and size when not given), saved unless save is False: the contract's sample
    dict. ForgeError when there's no catalogue."""
    cat = catalogue(fmt)
    size = int(size) if size else _default_size(fmt)
    chosen_filters = filters(fmt, colours, styles, tiers)
    chosen = _choose(cat.get("decks") or [], size, seed=seed or "", **chosen_filters)
    found = {"id": _sample_id(cat.get("sha"), chosen_filters, size, seed or ""), "format": fmt,
             "catalogue_sha": cat.get("sha"), "filters": chosen_filters, "size": size, "seed": seed or "",
             "decks": [d["id"] for d in chosen]}
    if save:
        _save_sample(fmt, found)
    return found


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

def plan(deck_entry, chosen, budget=DEFAULT_BUDGET):
    """What a gauntlet run of deck_entry against the sample would play now (nothing plays):
    field.plan's answer over the sample's decks and the gauntlet's results, with "sample"."""
    _check(deck_entry, chosen)
    opponents = entries(chosen["format"], chosen["decks"])
    found = field.plan(deck_entry, budget, results_dir=results_dir(), opponent_entries=opponents)
    found["sample"] = chosen["id"]
    return found


def run(deck_entry, chosen, budget=DEFAULT_BUDGET, inflight=None, progress=None, stop=None, *,
        by="command line", local=False, pool=None, seed_base=None, log_dir=None, log_every=1, space="home"):
    """Play deck_entry against the sample (field.run_field with the sample's decks as its
    opponents and the gauntlet's results folder): its note. stop, an Event, stops it at the next
    progress report as the page's Stop does (common.Stopped, raised again once every pair run has
    saved its games). ValueError for a budget or a sample of the other format, ForgeError as
    run_field's and entries'."""
    _check(deck_entry, chosen)
    opponents = entries(chosen["format"], chosen["decks"])
    folder = results_dir()
    folder.mkdir(parents=True, exist_ok=True)

    def watched(done, total, detail):
        if stop is not None and stop.is_set():
            raise common.Stopped("Stopped")
        if progress is not None:
            progress(done, total, detail)
    return field.run_field(deck_entry, budget, by=by, progress=watched, results_dir=folder, pool=pool,
                           local=local, seed_base=seed_base, log_dir=log_dir, log_every=log_every,
                           inflight=inflight, space=space, opponent_entries=opponents)


# ============================================================ the view

def _rate(numbers):
    if not numbers or numbers.get("value") is None:
        return None
    return {"value": field._r(numbers["value"]), "low": field._r(numbers.get("low")),
            "high": field._r(numbers.get("high"))}


def _opponent(deck, row):
    """One sampled opponent's row of the view."""
    return {"id": deck["id"], "title": deck["title"], "tier": deck.get("tier"),
            "identity": deck.get("identity") or "", "colours": deck.get("colours") or "",
            "style": (deck.get("style") or {}).get("primary"), "key": row["key"], "games": row["n"],
            "rate": _rate(row["numbers"]), "lead": row["lead"], "not_meaningful": row["not_meaningful"],
            "problem": row["problem"], "source": deck.get("source")}


def _group(key, label, members, extra=None):
    """One group's row: {"key", "label", "opponents", "games", "rate", "low", "high", "spread",
    "note"} over members [(catalogue entry, field._rows row)]."""
    counted = [r["numbers"] for _, r in members if r["numbers"] and not r["not_meaningful"]]
    of = sum(1 for _, r in members if not r["not_meaningful"])
    try:
        average = seqstats.field_average(counted, of=of) if counted else None
    except NotImplementedError:
        average = None
    values = [n["value"] for n in counted if n.get("value") is not None]
    notes = [extra] if extra else []
    if len(members) < 2:
        notes.insert(0, ONE)
    elif average and average.get("partial"):
        notes.append(f"based on {average['counted']} of {of} opponents with games on the play and on the draw")
    return {"key": key, "label": label, "opponents": len(members), "games": sum(r["n"] for _, r in members),
            "rate": field._r((average or {}).get("value")), "low": field._r((average or {}).get("low")),
            "high": field._r((average or {}).get("high")),
            "spread": [field._r(min(values)), field._r(max(values))] if values else None,
            "note": "; ".join(notes)}


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


def view(deck_entry, chosen, keep=None):
    """deck_entry against the sample (it never plays a game): {"deck": id, "sample": id, "format",
    "opponents": [rows, hardest first (lowest range low)], "groups" (_groups), "games", "note"
    (the caveat: these sampled opponents only), "notes" (decks gone from the catalogue, a rebuilt
    catalogue)}. ValueError for a sample of the other format, ForgeError with no catalogue."""
    _check(deck_entry, chosen)
    fmt = chosen["format"]
    cat = catalogue(fmt)
    pairs, missing = _picked(cat, chosen.get("decks") or [])
    notes = []
    if missing:
        notes.append(f"{len(missing)} of the sample's decks aren't playable in the catalogue now, so they're "
                     "left out.")
    if chosen.get("catalogue_sha") != cat.get("sha"):
        notes.append("The catalogue was rebuilt after this sample was drawn.")
    rows = field._rows(deck_entry, [e for _, e in pairs], results_dir(), keep)
    members = [(deck, row) for (deck, _), row in zip(pairs, rows)]
    opponents = [_opponent(deck, row) for deck, row in members]
    opponents.sort(key=lambda o: (o["rate"] is None, (o["rate"] or {}).get("low") or 0, o["title"].casefold()))
    return {"deck": deck_entry["id"], "sample": chosen["id"], "format": fmt, "opponents": opponents,
            "groups": _groups(members), "games": sum(r["n"] for r in rows),
            "note": CAVEAT.format(m=len(members)), "notes": notes}


def verdict(lead):
    """An opponent row's lead in a word or two from the deck's side (views' words), or None."""
    if not lead:
        return None
    if lead.get("side") == 1:
        return "slightly behind" if lead.get("verdict") == "slightly_ahead" else "behind"
    return str(lead.get("verdict", "")).replace("_", " ") or None

