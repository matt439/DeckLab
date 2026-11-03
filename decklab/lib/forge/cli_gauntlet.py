"""Forge CLI gauntlet commands (decklab/design/gauntlet.md sections 3, 5 and 6): build the
catalogue, list and show its decks, draw a sample, and plan, play and view a house deck against
it. Building fetches from EDHREC and MTGJSON politely and only from here, never from a page."""
from . import cli_evaluate as evaluate
from . import cli_output as output
from . import cli_shared as shared

GAUNTLET_REPORT_S = 5           # seconds between a gauntlet run's progress lines
SOURCES = ("edhrec", "precons", "forge")
VIEW_BY = ("colour", "identity_size", "style", "tier", "opponent")
GROUP_TITLES = {"colour": "By colour", "identity_size": "By number of colours", "style": "By style",
                "tier": "By tier"}


def _g():
    from . import gauntlet          # imported when used, as the field's commands do
    return gauntlet


def _budget(text):
    """argparse's type for --budget: fixed:N, or N meaning fixed:N (N 1 or more)."""
    found = text[6:] if text.startswith("fixed:") else text
    if found.isascii() and found.isdigit() and int(found) >= 1:
        return f"fixed:{int(found)}"
    raise shared.argparse.ArgumentTypeError(f"must be fixed:<games> or a number of games, not {text!r}")


def _size(text):
    """argparse's type for --size: a number of opponents (1 or more), or "all" (every deck the
    filters allow)."""
    if text.strip().lower() == "all":
        return "all"
    return shared._positive(text)


def _words(text):
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()] or None


def _sample_args(parser):
    """--sample or --standard, or the filters and seed of a sample drawn now (and saved)."""
    parser.add_argument("--sample", help="a saved sample's id (sample:<12 hex>); otherwise one is drawn and saved")
    parser.add_argument("--standard", action="store_true",
                        help="the standard sample, the deck page's default (20 core and upgraded Commander decks, "
                             "24 medium and hard constructed ones); no other sample option goes with it")
    parser.add_argument("--size", type=_size, help="opponents in the sample, or all (default 20 Commander, "
                                                   "24 constructed)")
    parser.add_argument("--colours", help="only decks whose colour identity is within these letters, such as WUB")
    parser.add_argument("--styles", help="only these styles, comma-separated: aggro, midrange, control, combo, "
                                         "ramp")
    parser.add_argument("--tier", help="only these tiers, comma-separated (default core and upgraded for "
                                       "Commander, medium and hard for constructed)")
    parser.add_argument("--seed", default="", help="the sample's seed (default none)")


def _gauntlet_args(sub):
    """gauntlet build|list|show|sample|plan|play|view."""
    top = sub.add_parser("gauntlet", help="a deck against outside sparring decks, by colour and style")
    actions = top.add_subparsers(dest="action", required=True)
    build = actions.add_parser("build", help="fetch the sources and write the catalogue (slow, polite)")
    build.add_argument("--format", choices=("commander", "constructed", "all"), default="all")
    build.add_argument("--source", default=",".join(SOURCES), help="comma-separated: edhrec, precons, forge")
    build.add_argument("--top", type=shared._positive, default=100, help="EDHREC's top commanders (default 100)")
    build.add_argument("--refresh", action="store_true", help="fetch EDHREC's pages again unless fetched in the last hour (MTGJSON's precons keep "
                            "their own cache)")
    build.add_argument("--dry-run", action="store_true", help="work it out, but write no catalogue")
    listed = actions.add_parser("list", help="the catalogue's decks")
    listed.add_argument("--format", choices=("commander", "constructed"), default="commander")
    listed.add_argument("--tier", help="only these tiers, comma-separated")
    listed.add_argument("--colours", help="only decks whose identity is within these letters")
    listed.add_argument("--styles", help="only these primary styles, comma-separated")
    listed.add_argument("--all", action="store_true", help="the decks that can't be played too")
    listed.add_argument("--json", action="store_true")
    show = actions.add_parser("show", help="one catalogue deck")
    show.add_argument("id", help="its id, such as gauntlet:forge/duels/<slug>")
    show.add_argument("--json", action="store_true")
    drawn = actions.add_parser("sample", help="draw and save a balanced sample")
    drawn.add_argument("--format", choices=("commander", "constructed"), default="commander")
    _sample_args(drawn)
    drawn.add_argument("--json", action="store_true")
    for name, about in (("plan", "what a run would play, and its time"), ("play", "play a deck against a sample"),
                        ("view", "a deck's results against a sample")):
        part = actions.add_parser(name, help=about)
        part.add_argument("deck", help="deck id")
        part.add_argument("--owned", action="store_true", help="the deck's owned-only list")
        _sample_args(part)
        if name != "view":
            part.add_argument("--budget", type=_budget, default="fixed:100", help="fixed:N games an opponent "
                                                                                  "(default fixed:100)")
        if name == "play":
            part.add_argument("--inflight", type=shared._positive, help="pair runs at once")
            part.add_argument("--local", action="store_true",
                              help="play in a pool of this command's own, not the running server's")
            part.add_argument("--seed-base", type=int)
            part.add_argument("--by", default="command line")
            shared._log_args(part)
        if name == "view":
            part.add_argument("--by", choices=VIEW_BY, help="only this grouping (default every group)")
        part.add_argument("--json", action="store_true")


def _cmd_gauntlet(args):
    run = {"build": _build_catalogues, "list": _list, "show": _show, "sample": _sample, "plan": _plan, "play": _play,
           "view": _view}[args.action]
    try:
        return run(args)
    except ValueError as e:
        raise shared._CliError(str(e)) from None


# ------------------------------------------------------------ build, list, show, sample

def _build_catalogues(args):
    sources = tuple(_words(args.source) or ())
    unknown = [s for s in sources if s not in SOURCES]
    if unknown or not sources:
        raise shared._CliError(f"A source is one of {', '.join(SOURCES)}, not {', '.join(unknown) or 'none'}.")
    from decklab.lib.gauntlet.catalogue import GauntletError, applicable
    if args.format == "all":
        # only the formats one of the sources serves: --source edhrec leaves the 60-card catalogue alone
        formats = [fmt for fmt in _g().FORMATS if applicable(fmt, sources)]
    else:
        formats = [args.format]
    failed = []
    for fmt in formats:
        try:
            _g()._build_catalogue(fmt, sources=sources, top=args.top, refresh=args.refresh,
                                  dry_run=args.dry_run, log=print)
        except GauntletError as e:
            if len(formats) == 1:
                raise shared._CliError(str(e)) from None
            print(e, file=shared.sys.stderr)
            failed.append(fmt)
        # catalogue.build logs its own summary: counts by tier, identity and style, and what was left out
    return 1 if failed else 0


def _within(deck, colours):
    return not colours or set(deck.get("identity") or "") <= set(colours.upper())


def _list(args):
    cat = _g().catalogue(args.format)
    tiers, styles = _words(args.tier), _words(args.styles)
    decks = [d for d in cat.get("decks") or [] if (args.all or d.get("playable")) and _within(d, args.colours)
             and (not tiers or d.get("tier") in tiers)
             and (not styles or (d.get("style") or {}).get("primary") in styles)]
    if args.json:
        print(shared.json.dumps([{k: v for k, v in d.items() if k != "cards"} for d in decks], ensure_ascii=False))
        return 0
    print(f"The {args.format} gauntlet, built {cat.get('built')}: {len(decks)} decks")
    for d in decks:
        mark = "" if d.get("playable") else "  (can't be played)"
        print(f"  {d['id']}: {d.get('title')}; {d.get('tier')}, {d.get('identity') or 'colourless'}, "
              f"{(d.get('style') or {}).get('primary')}{mark}")
    return 0


def _show(args):
    found = _g().find(args.id)
    if found is None:
        raise shared._CliError(f"There's no gauntlet deck {args.id!r} (build the catalogue first?).")
    fmt, d = found
    if args.json:
        print(shared.json.dumps(d, ensure_ascii=False))
        return 0
    style = d.get("style") or {}
    source = d.get("source") or {}
    print(f"{d.get('title')} ({d['id']}), {fmt}")
    print(f"  tier {d.get('tier')}; colour identity {d.get('identity') or 'colourless'}; style "
          f"{style.get('primary')}" + (f" ({', '.join(style.get('tags') or [])})" if style.get("tags") else ""))
    if style.get("themes"):
        print("  themes: " + ", ".join(style["themes"]))
    bracket = d.get("bracket")
    if bracket:
        print(f"  bracket {bracket.get('label')} (at least {bracket.get('minimum')})"
              + (f"; Game Changers: {', '.join(bracket['game_changers'])}" if bracket.get("game_changers") else ""))
    print(f"  from {source.get('kind')}: {source.get('url') or source.get('file')}, fetched {source.get('fetched')}")
    for line in (d.get("fixes") or []):
        print(f"  fixed: {line}")
    for line in (d.get("problems") or []):
        print(f"  ! {line}")
    for section in ("Commander", "Main"):
        cards = (d.get("cards") or {}).get(section) or []
        if cards:
            print(f"  {section}:")
            for qty, name in cards:
                print(f"    {qty} {name}")
    return 0


def _draw(args, fmt):
    """The sample a command names (--sample), the standard one (--standard), or one drawn now with its
    filters (and saved)."""
    if getattr(args, "standard", False):
        given = [flag for flag, value in (("--sample", args.sample), ("--size", args.size),
                                          ("--colours", args.colours), ("--styles", args.styles),
                                          ("--tier", args.tier), ("--seed", args.seed)) if value]
        if given:
            raise shared._CliError(f"--standard is a fixed sample: leave out {', '.join(given)}.")
        return _g().standard(fmt, save=True)
    if args.sample:
        found = _g().sample(args.sample)
        if found.get("format") != fmt:
            raise shared._CliError(f"{args.sample} is a {found.get('format')} sample, not {fmt}.")
        return found
    return _g().draw(fmt, size=args.size, colours=args.colours, styles=_words(args.styles), tiers=_words(args.tier),
                     seed=args.seed)


def _sample(args):
    found = _draw(args, args.format)
    if args.json:
        print(shared.json.dumps(found, ensure_ascii=False))
        return 0
    filters = found.get("filters") or {}
    print(f"{found['id']}: {len(found['decks'])} {found['format']} decks (tiers "
          f"{', '.join(filters.get('tiers') or ['any'])}; colours {filters.get('colours') or 'any'}; styles "
          f"{', '.join(filters.get('styles') or ['any'])}; seed {found.get('seed') or 'none'})")
    by_id = {d["id"]: d for d in (_g().catalogue(found["format"]).get("decks") or [])}
    for deck_id in found["decks"]:
        d = by_id.get(deck_id) or {"title": "(not in the catalogue now)"}
        print(f"  {deck_id}: {d.get('title')}; {d.get('identity') or 'colourless'}, "
              f"{(d.get('style') or {}).get('primary')}, {d.get('tier')}")
    return 0


# ------------------------------------------------------------ plan, play, view

def _deck(args):
    if args.deck.lower().endswith(".dck"):
        raise shared._CliError("The gauntlet plays a deck of the library: give its deck id.")
    return shared._cli_entry(args.deck, args.owned)


def _house_sample(args, a):
    """The sample args choose for the deck a, without a trial deck's own precon (E3-S39)."""
    from decklab.lib import decks
    from decklab.lib.gauntlet import trial_excluded, without
    return without(_draw(args, _g().format_of(a)), trial_excluded(decks.find_summary(a["id"])))


def _plan(args):
    from . import estimate
    a = _deck(args)
    chosen = _house_sample(args, a)
    planned = _g().plan(a, chosen, args.budget)
    minutes = evaluate._field_minutes(estimate, [(a, p["opponent"], p["games"]) for p in planned["pairs"]
                                                 if p["games"] > 0], str(_g().results_dir()))
    if args.json:
        print(shared.json.dumps({"sample": chosen["id"], "budget": planned["budget"],
                                 "new_games": planned["new_games"], "minutes": list(minutes) if minutes else None,
                                 "pairs": [{"id": p["opponent"]["id"], "title": p["opponent"]["title"],
                                            "key": p["key"], "have": p["have"], "games": p["games"]}
                                           for p in planned["pairs"]]}, ensure_ascii=False))
        return 0
    for p in planned["pairs"]:
        print(f"{p['opponent']['title']}: has {p['have']:,} games; about {p['games']:,} more")
    time_words = (f"about {minutes[0]:.0f}-{minutes[1]:.0f} minutes" if minutes and planned["new_games"]
                  else "time not yet measured" if planned["new_games"] else "nothing to play")
    print(f"{chosen['id']}: {len(planned['pairs'])} opponents, about {planned['new_games']:,} new games at "
          f"{planned['budget']}; {time_words}.")
    return 0


def _play(args):
    a = _deck(args)
    chosen = _house_sample(args, a)
    if args.seed_base is not None and args.seed_base < 0:
        raise shared._CliError("The seed base must be 0 or more (--seed-base).")
    shown = [0.0]

    def report(done, total, detail):
        now = shared.time.monotonic()
        if now - shown[0] >= GAUNTLET_REPORT_S or (total and done == total):
            shown[0] = now
            playing = [p["opponent"]["title"] for p in detail["pairs"].values() if p.get("playing")]
            print(f"  {done:,} of {total:,} games" + (f"; playing {', '.join(playing)}" if playing else ""),
                  file=shared.sys.stderr)

    print(f"Playing {a['title']} ({a['version']}) against {len(chosen['decks'])} gauntlet decks ({chosen['id']}), "
          f"budget {args.budget}...", file=shared.sys.stderr)
    log = {"log_dir": args.logs_dir, "log_every": args.log_every} if getattr(args, "logs_dir", None) else {}
    note = _g().run(a, chosen, args.budget, inflight=args.inflight, progress=report, by=args.by, local=args.local,
                    seed_base=args.seed_base, **log)
    found = _g().view(a, chosen)
    if args.json:
        print(shared.json.dumps({"note": note, "view": found}, ensure_ascii=False))
    else:
        print(f"Played {note['played']:,} games in {note['wall_s']:.0f} s.")
        for key, why in (note.get("dropped") or {}).items():
            print(f"  ! {why} ({key[:12]})")
        _print_view(a, found)
    return 1 if note.get("dropped") else 0


def _view(args):
    a = _deck(args)
    chosen = _house_sample(args, a)
    found = _g().view(a, chosen)
    if args.json:
        print(shared.json.dumps(found, ensure_ascii=False))
    else:
        _print_view(a, found, args.by)
    return 0


def _rate(row):
    if row.get("rate") is None:
        return "-"
    return f"{output._pct(row['rate'])} ({output._pct(row['low'], 0)}-{output._pct(row['high'], 0)})"


def _group_line(g):
    parts = [_rate(g), f"{g['opponents']} opponent{'s' if g['opponents'] != 1 else ''}", f"{g['games']:,} games"]
    if g.get("spread") and g["opponents"] > 1:
        parts.append(f"spread {output._pct(g['spread'][0], 0)}-{output._pct(g['spread'][1], 0)}")
    if g.get("note"):
        parts.append(g["note"])
    return f"    {g['label']}: " + "; ".join(parts)


def _print_view(a, found, by=None):
    """gauntlet view's lines: the groups (or one grouping), then the opponents, hardest first."""
    print(f"{a['title']} ({a['version']}) against {found['sample']}: {len(found['opponents'])} opponents, "
          f"{found['games']:,} games")
    names = list(GROUP_TITLES) if by is None else [] if by == "opponent" else [by]
    for name in names:
        print(f"  {GROUP_TITLES[name]}:")
        for g in found["groups"].get(name) or []:
            print(_group_line(g))
    if by in (None, "opponent"):
        print("  Opponents, hardest first:")
        for o in found["opponents"]:
            rate = o.get("rate")
            words = (f"{output._pct(rate['value'])} ({output._pct(rate['low'], 0)}-{output._pct(rate['high'], 0)})"
                     if rate else "-")
            extra = [f"{o['games']:,} games", f"{o.get('identity') or 'colourless'}", str(o.get("style")),
                     str(o.get("tier"))]
            if _g().verdict(o.get("lead")):
                extra.append(_g().verdict(o["lead"]))
            if o.get("not_meaningful"):
                extra.append("not meaningful")
            if o.get("problem"):
                extra.append(o["problem"])
            print(f"    {o['title']}: {words}; " + "; ".join(extra))
    for line in found.get("notes") or []:
        print(f"  ! {line}")
    print(f"  ! {found['note']}")
