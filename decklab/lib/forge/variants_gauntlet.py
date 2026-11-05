"""A variant test against a saved gauntlet sample (E3-S30, decklab/design/gauntlet.md section 6,
"Fit with other work"): the changed list plays the base list's own gauntlet games (the same
seeds and seats, variants._play_pair) read from the gauntlet's results folder, so neither the
base top-ups nor the paired results ever join the field, Rankings or the ratings.

A gauntlet test's against is the string "gauntlet:<sample id>" (against_for). It plays as a field
test does (the field's looks and margin, seqstats.paired_field over the opponents), and its view
adds the difference by group (colour, number of colours, style, tier) with the caveat that every
range covers those sampled opponents only.

    PREFIX                  "gauntlet:"
    is_gauntlet(against)    whether a test's against (or a summary's) is a gauntlet sample
    against_for(sample_id)  "gauntlet:<sample id>"
    sample_of(against)      the sample id of a gauntlet against
    results_dir()           the gauntlet's results folder (forge/gauntlet.results_dir)
    opponents(base_entry, against, exclude_ids=())
                            the sample's playable decks as Forge entries, without a mirror of the base
    opponents_of(base_entry, chosen, exclude_ids=())
                            the same over a sample dict (an unsaved standard draw, the page's estimate)
    tag(summary)            each opponent record's {"identity", "style", "tier"} from the catalogue
    groups(rows)            the paired difference by group over [(record, paired_diff())]
    note(m)                 the caveat: these m sampled opponents only
"""
from . import seqstats
from .common import ForgeError

PREFIX = "gauntlet:"
NO_OPPONENTS = "The gauntlet sample has no deck to test this change against."
TITLE = "the sampled popular decks"
CAVEAT = ("Each difference covers these {m} sampled opponents only, not every deck of that colour, style or "
          "tier.")


def _g():
    from . import gauntlet          # imported when used, as the gauntlet's commands do
    return gauntlet


def is_gauntlet(against):
    return isinstance(against, str) and against.startswith(PREFIX) and len(against) > len(PREFIX)


def against_for(sample_id):
    return PREFIX + str(sample_id)


def sample_of(against):
    return against[len(PREFIX):] if is_gauntlet(against) else None


def results_dir():
    return _g().results_dir()


def opponents(base_entry, against, exclude_ids=()):
    """The sample's decks as Forge entries in its order, without one whose list is the base's own
    (a mirror) or exclude_ids (a trial deck's own precon). ForgeError (a plain sentence) for an
    unknown sample, one of the other format, a catalogue without its decks, or no opponent left."""
    try:
        chosen = _g().sample(sample_of(against))
    except ValueError as e:
        raise ForgeError(str(e)) from None
    return opponents_of(base_entry, chosen, exclude_ids)


def opponents_of(base_entry, chosen, exclude_ids=()):
    """opponents() over a sample dict itself (one drawn and not saved, as the page's estimate of the
    standard sample is): the same entries, the same ForgeError sentences."""
    from decklab.lib.gauntlet import without
    g = _g()
    try:
        g._check(base_entry, chosen)
    except ValueError as e:
        raise ForgeError(str(e)) from None
    chosen = without(chosen, exclude_ids)
    found = [e for e in g.entries(chosen["format"], chosen["decks"]) if e["card_sha"] != base_entry["card_sha"]]
    if not found:
        raise ForgeError(NO_OPPONENTS)
    return found


def tag(summary):
    """Each opponent record's "group": {"identity", "style", "tier"} from the format's catalogue, kept
    in the summary so its groups still read after a rebuild. A catalogue that can't be read leaves
    them out (the groups then say unknown)."""
    try:
        cat = _g().catalogue("commander" if summary["base"]["kind"] == "commander" else "constructed")
    except (ForgeError, ValueError):
        return summary
    by_id = {d.get("id"): d for d in cat.get("decks") or []}
    for record in summary.get("opponents") or []:
        deck = by_id.get(record.get("id"))
        if deck is None:
            continue                # not in the catalogue: its groups say unknown, never colourless
        identity = deck.get("identity")
        record["group"] = {"identity": identity if isinstance(identity, str) else None,
                           "style": (deck.get("style") or {}).get("primary"), "tier": deck.get("tier")}
    return summary


def _row(key, label, members, extra=None):
    """One group's paired difference: {"key", "label", "opponents", "delta", "low", "high", "note"}."""
    diffs = [d for _, d in members if d is not None]
    try:
        found = seqstats.paired_field(diffs) if diffs else None
    except NotImplementedError:
        found = None
    notes = [extra] if extra else []
    if len(members) < 2:
        notes.insert(0, _g().ONE)
    return {"key": key, "label": label, "opponents": len(members),
            "delta": (found or {}).get("delta"), "low": (found or {}).get("low"), "high": (found or {}).get("high"),
            "note": "; ".join(notes)}


def groups(rows):
    """The difference by group over rows [(opponent record, paired_diff() or None)], in the gauntlet
    view's groups and order: {"colour", "identity_size", "style", "tier": [group rows]}, only groups
    with opponents in them. Colours overlap (a deck of several counts in each)."""
    g = _g()

    def read(record):
        return record.get("group") or {}

    def identity(m):
        """The opponent's colour identity ("" colourless), or None when no tag recorded it."""
        found = read(m[0]).get("identity")
        return found if isinstance(found, str) else None

    known = [m for m in rows if identity(m) is not None]
    unknown = [m for m in rows if identity(m) is None]
    colour = []
    for letter, label in g.COLOURS:
        inside = [m for m in known if letter in identity(m)]
        if inside:
            colour.append(_row(letter, label, inside, g.OVERLAP))
    colourless = [m for m in known if not identity(m)]
    if colourless:
        colour.append(_row("C", "Colourless", colourless))
    size = []
    for count, (key, label) in enumerate(g.SIZES):
        inside = [m for m in known if len(identity(m)) == count]
        if inside:
            size.append(_row(key, label, inside))
    if unknown:
        colour.append(_row("unknown", "Unknown", unknown))
        size.append(_row("unknown", "Unknown", unknown))
    out = {"colour": colour, "identity_size": size}
    for name, order in (("style", g.STYLES), ("tier", g.TIERS)):
        found = {}
        for m in rows:
            found.setdefault(read(m[0]).get(name) or "unknown", []).append(m)
        keys = [k for k in order if k in found] + sorted(k for k in found if k not in order)
        out[name] = [_row(k, k[:1].upper() + k[1:], found[k]) for k in keys]
    return out


def note(m):
    return CAVEAT.format(m=m)
