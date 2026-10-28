"""The decks' commands, Claude's way to read and change a deck's text now that the decks are kept
by Deck Lab's inventory (the database; decklab/PLAN.md phase 4, the phase 4 design's R7) instead
of files in magic/decks:

  python -m decklab.db deck list [--space S] [--json]
  python -m decklab.db deck show ID [--version target|owned] [--json]
  python -m decklab.db deck pull ID [-o FILE]          (or --all -o DIR)
  python -m decklab.db deck push ID FILE --expect N -m MSG [--dry-run]
  python -m decklab.db deck new KIND SLUG --from FILE [--space S] -m MSG
  python -m decklab.db deck delete ID --expect N -m MSG --reason R
  python -m decklab.db deck history ID
  python -m decklab.db deck revision ID N [-o FILE]
  python -m decklab.db deck tables [ID ...] [--reprice] [--check | --apply]

ID is a deck id as the library has it (casual/gruul-ramp, commander/x, user2/casual/elves).

list prints every deck of a space (every space without --space): id, title, kind, status, who
plays it, its revision, the date of its "Decklist changed in Deck Lab" line when it has one, and
whether its owned-vs-needed table is out of date. show prints a deck's list (the target list, or
the substitute list with --version owned).

pull writes a deck's text, byte for byte as Deck Lab keeps it (LF), to FILE (or stdout), and
prints "revision N" and its sha256: give either to push's --expect, so a push never writes over a
save made since the pull (the database numbers every saved text; the files backend keeps none, so
there the sha256, at least its first 12 characters, is the token). --all -o DIR writes every deck
as DIR/<id>.md. A FILE or DIR inside a deck folder of the repo (magic/decks, magic/people/<id>/
decks) is refused: deck files are never brought back into the repo.

push saves FILE as the deck's text, as one change by "claude" (or --actor PROFILE) from the command line with the -m
message. The file is read as UTF-8 (a byte-order mark is dropped, CRLF and CR become LF), at
most 1 MiB, and must parse as a deck with a "## Decklist" block; a person's deck can't gain
Played by, Sleeves or Deck box lines (deck.save's rules). A text the deck already has writes
nothing. Changed Sleeves or Deck box lines are chosen as the deck page's picker chooses them
(kit.set, in the same change: the ids must be accessories the deck's player may use; older free
text is kept as written). Deck Lab's own parts (the owned-vs-needed table, its labels and prices)
are written as given: push re-renders nothing, and says afterwards when the table is out of date
(deck tables --apply refreshes it), the token cards the deck makes, any unknown card names and
what accessories --check reports about the deck.

The "Decklist changed in Deck Lab on <date>" workflow: deck pull, update the prose to match the
decklist and remove that line, deck push.

new makes a deck from FILE (read as push reads it) in the space (home by default): the slug must
be a valid one, not taken in that space by a deck of either kind (compared without case). delete
removes a deck (its history stays; a built deck holding sleeves or a deck box must be taken apart
first). A deck can't be renamed: make the new one and delete the old.

history lists a deck's saved revisions, newest first (a deleted deck's too), with who saved each,
when (in this PC's time zone) and its whole message; revision prints (or writes to FILE) one
revision's text. The files backend keeps no history.

tables works out the owned-vs-needed tables (and the substitute lists' notes) again from the
inventory, as the receipts do, for the decks named (every deck without IDs): without --check or
--apply it lists the decks whose tables would change; --check does the same and exits 1 when any
would; --apply saves them as one change (deck.update_tables: all of them, or none when one
changed meanwhile). --reprice also prices the tables again with today's card prices and exchange
rate, as Deck Lab's "Update the table" and the Decks page's "Update all" do (a table whose rate
is worded some other way keeps its prices). It refuses while any space's card pool is incomplete
(unknown cards, warnings) or a deck can't be worked out (no table, unknown card names), as the
refresh does, and then lists every one of those problems (refresh.table_blockers), not only the
first.

push and new also name the other decks of the deck's space whose tables are now out of date (a
built deck's list, status or built version changes what they can use), with the deck tables
command that updates them, or what would stop it (stale_notes; collection merge says the same).

Exit codes as the other commands: 0 done, 1 refused or something to fix (--check: a table is out
of date), 2 the database can't be reached.
"""
import difflib
import json
import re
import sys
from pathlib import Path

from decklab.db import cli_actor

MAX_TEXT = 1024 * 1024              # ops_decks.MAX_TEXT: a deck text's most bytes
MIN_SHA = 12                        # characters of a sha256 --expect needs at least
MAX_TITLE = 100                     # characters in a deck's title (the editor's limit)
PUSH_KIND = "deck.push"             # push's operation when the kit lines change too (kit.set, then deck.save)


def register(sub):
    """Add the deck command and its own subcommands to python -m decklab.db's parser."""
    p = sub.add_parser("deck", help="Read or change a deck (list, show, pull, push, new, delete, history, revision, "
                                    "tables).",
                       description="Read or change a deck's text, kept by Deck Lab. Writes need -m saying what they "
                                   "do; a deletion also --reason.")
    p.set_defaults(func=run)
    actions = p.add_subparsers(dest="action", required=True, metavar="action")

    sp = actions.add_parser("list", help="List the decks: id, title, status, revision, stale tables.")
    sp.add_argument("--space", help="one space's decks (default every space's)")
    sp.add_argument("--json", action="store_true", help="print them as JSON")
    sp = actions.add_parser("show", help="Print a deck's list.")
    sp.add_argument("id", help="the deck's id")
    sp.add_argument("--version", choices=("target", "owned"), default="target",
                    help="the target list (default) or the substitute list")
    sp.add_argument("--json", action="store_true", help="print the sections as JSON")
    sp = actions.add_parser("pull", help="Write a deck's text to a file (or stdout), and print its revision.")
    sp.add_argument("id", nargs="?", help="the deck's id")
    sp.add_argument("--all", action="store_true", help="every deck, as DIR/<id>.md (needs -o DIR)")
    sp.add_argument("-o", "--output", metavar="FILE", help="the file (with --all, the folder) to write")
    sp = actions.add_parser("push", help="Save a file as a deck's text.")
    sp.add_argument("id", help="the deck's id")
    sp.add_argument("file", help="the text to save (UTF-8)")
    _write_options(sp, expect=True)
    sp.add_argument("--dry-run", action="store_true", help="show the text diff and checks; save nothing")
    sp = actions.add_parser("new", help="Make a new deck from a file.")
    sp.add_argument("kind", choices=("casual", "commander"))
    sp.add_argument("slug", help="the deck's slug: lowercase letters, digits and single hyphens")
    sp.add_argument("--from", dest="file", required=True, metavar="FILE", help="its text (UTF-8)")
    sp.add_argument("--space", default="home", help="whose deck (default home)")
    _write_options(sp)
    sp = actions.add_parser("delete", help="Delete a deck (its history stays).")
    sp.add_argument("id", help="the deck's id")
    _write_options(sp, expect=True)
    sp.add_argument("--reason", required=True, help="why it's deleted, for the history")
    sp = actions.add_parser("history", help="List a deck's saved revisions, newest first.")
    sp.add_argument("id", help="the deck's id (a deleted one's too)")
    sp = actions.add_parser("revision", help="Print (or write) one saved revision's text.")
    sp.add_argument("id", help="the deck's id")
    sp.add_argument("number", type=int, help="the revision, as deck history numbers it")
    sp.add_argument("-o", "--output", metavar="FILE", help="write it to FILE instead of stdout")
    sp = actions.add_parser("tables", help="Work out the owned-vs-needed tables again (--check, --apply).")
    sp.add_argument("ids", nargs="*", metavar="ID", help="the decks (default every deck)")
    sp.add_argument("--reprice", action="store_true", help="price them again with today's prices and rate")
    mode = sp.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when a table is out of date; write nothing")
    mode.add_argument("--apply", action="store_true", help="save the new tables (one change)")
    sp.add_argument("-m", "--message", help="what the change does, for the history (--apply; a default is given)")
    cli_actor.add_argument(sp)


def _write_options(sp, expect=False):
    sp.add_argument("-m", "--message", required=True, help="what this change does, for the history")
    cli_actor.add_argument(sp)
    if expect:
        sp.add_argument("--expect", required=True, metavar="N",
                        help="the revision (or sha256, at least its first 12 characters) deck pull printed: "
                             "refused if the deck was saved since")


def _say(text):
    print(text, file=sys.stderr)


def _actor(args=None):
    return cli_actor.resolve(args)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


# ------------------------------------------------------------------ reading

def _deck(deck_id, *, resolve=False):
    """The snapshot's Deck with this id, or None (a message said why)."""
    from decklab.lib import inventory
    snapshot = inventory.current()
    current_id = inventory.resolve_deck_id(deck_id, snapshot)
    deck = snapshot.deck(current_id if resolve else deck_id)
    if deck is None:
        _say(f"{deck_id} was renamed to {current_id}; use its current id before changing it." if current_id != deck_id
             else f"There's no deck {deck_id!r} (python -m decklab.db deck list lists them).")
    elif deck.error is not None:
        _say(f"{deck_id} can't be read ({deck.error}).")
        return None
    return deck


def parsed(deck):
    """The DeckFile a Deck's text holds (DeckFileError when it can't be parsed)."""
    from decklab.lib import decks
    return decks.parse_deck(deck.data, deck.slug, deck.kind, None, deck.space)


def _pools():
    """A space -> pool getter (each loaded once; None when it can't be read)."""
    from decklab.lib import pool
    found = {}

    def get(space):
        if space not in found:
            try:
                found[space] = pool.for_space(space)
            except Exception:           # noqa: BLE001 - a pool that can't be read is shown as "?"
                found[space] = None
        return found[space]
    return get


def _stale(deck_file, pool_of):
    """True when the deck's table no longer matches its space's pool, False when it does (or it
    has no table), None when that can't be worked out."""
    from decklab.lib import pool
    supply = pool_of(deck_file.space)
    if supply is None:
        return None
    try:
        return bool(pool.table_changes(deck_file, supply))
    except Exception:                   # noqa: BLE001 - unknown cards, no card index: "?"
        return None


def deck_rows(space=None):
    """[{id, title, kind, space, status, player, revision, sha256, marker, stale, error}] of every
    deck (of space), in the library's order."""
    from decklab.lib import inventory, spaces
    inv = inventory.current()
    pool_of = _pools()
    wanted = [space] if space else spaces.space_ids()
    out = []
    for space_id in wanted:
        for deck in sorted((d for d in inv.decks.values() if d.space == space_id),
                           key=lambda d: (("casual", "commander").index(d.kind), d.slug)):
            row = {"id": deck.id, "title": deck.slug, "kind": deck.kind, "space": deck.space, "status": None,
                   "player": None, "revision": deck.revision or None, "sha256": None, "marker": None,
                   "stale": None, "error": deck.error}
            if deck.error is None:
                row["sha256"] = deck.sha256
                try:
                    found = parsed(deck)
                except Exception as e:  # noqa: BLE001 - listed with its error
                    row["error"] = str(e)
                else:
                    row.update(title=found.title, status=found.status, player=found.player,
                               marker=found.changed_on, stale=_stale(found, pool_of))
            out.append(row)
    return out


def _list(args):
    from decklab.lib import spaces
    if args.space and args.space != spaces.HOME and not spaces.exists(args.space):
        _say(f"There's no space {args.space!r} in decklab/config.json.")
        return 1
    rows = deck_rows(args.space)
    from decklab.db import read_notices
    read_notices.Reporter(getattr(args, "dbname", None)).decks(
        [args.space] if args.space else [row["space"] for row in rows])
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print(f"{_plural(len(rows), 'deck')}{' in ' + args.space if args.space else ''}.")
    for row in rows:
        if row["error"]:
            print(f"  {row['id']}  ! {row['error']}")
            continue
        stale = {True: "table out of date", False: "", None: "table ?"}[row["stale"]]
        bits = [row["kind"], row["status"] or "no status", f"played by {row['player']}" if row["player"] else "",
                f"revision {row['revision']}" if row["revision"] else "", stale,
                f"decklist changed {row['marker']}" if row["marker"] else ""]
        print(f"  {row['id']}  {row['title']}  ({', '.join(b for b in bits if b)})")
    return 0


def _show(args):
    from decklab.lib import decks
    deck = _deck(args.id, resolve=True)
    if deck is None:
        return 1
    found = parsed(deck)
    sections = found.target if args.version == "target" else found.owned
    if args.version == "target" and not found.has_decklist:
        _say(f"{args.id}: {decks.NO_DECKLIST}")
        return 1
    if sections is None:
        _say(f"{args.id} has no substitute list.")
        return 1
    if args.json:
        print(json.dumps({name: [{"quantity": line.quantity, "name": line.name, "set": line.set,
                                  "number": line.number, "finish": line.finish} for line in lines]
                          for name, lines in sections.items()}, ensure_ascii=False, indent=2))
        return 0
    print(f"{found.title} ({deck.id}, {'substitute list' if args.version == 'owned' else 'target list'}"
          f"{', revision ' + str(deck.revision) if deck.revision else ''})")
    print(decks.format_decklist(sections).rstrip("\n"))
    return 0


# ------------------------------------------------------------------ pull and revisions

def refused_output(path):
    """Why path can't be written to (text), or None: it's inside one of the repo's deck folders
    (magic/decks, or a person's magic/people/<id>/decks, in any case), so a pull never brings a deck
    file back."""
    from decklab.lib import config
    try:
        rel = Path(path).resolve().relative_to(Path(config.REPO).resolve()).as_posix()
    except ValueError:
        return None
    parts = rel.lower().split("/")     # resolve() can't fix the case of a folder that isn't there
    if parts[:2] == ["magic", "decks"] or (parts[:2] == ["magic", "people"] and len(parts) > 3 and parts[3] == "decks"):
        return (f"{rel} is in the repo's deck folders, which Deck Lab no longer reads: write it somewhere else "
                "(your scratchpad, say)")
    return None


def _write_bytes(path, data):
    """Write data to path as it is (no newline translation), making its folder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _token_words(deck):
    return f"revision {deck.revision}" if deck.revision else "revision unknown (this backend keeps none)"


def _pull(args):
    from decklab.lib import inventory
    if args.all:
        if not args.output or args.id:
            _say("--all needs -o DIR, and no deck id.")
            return 1
        refused = refused_output(args.output)
        if refused:
            _say(f"Not written: {refused}.")
            return 1
        folder = Path(args.output)
        decks = [d for d in inventory.current().decks.values() if d.error is None]
        for deck in decks:
            _write_bytes(folder / f"{deck.id}.md", deck.data)
            print(f"{deck.id}  {_token_words(deck)}  sha {deck.sha256}")
        print(f"Wrote {_plural(len(decks), 'deck')} into {folder}.")
        return 0
    if not args.id:
        _say("Name the deck to pull (or --all -o DIR).")
        return 1
    deck = _deck(args.id, resolve=True)
    if deck is None:
        return 1
    if args.output:
        refused = refused_output(args.output)
        if refused:
            _say(f"Not written: {refused}.")
            return 1
        _write_bytes(args.output, deck.data)
        print(_token_words(deck))
        print(f"sha {deck.sha256}")
        return 0
    sys.stdout.flush()
    sys.stdout.buffer.write(deck.data)
    sys.stdout.buffer.flush()
    _say(f"{_token_words(deck)}; sha {deck.sha256}")
    return 0


def _local(at):
    return at.astimezone().strftime("%Y-%m-%d %H:%M") if at is not None else "?"


def _history(args):
    from decklab.lib import inventory
    revisions = inventory.deck_revisions(args.id)
    if not revisions:
        if inventory.current().deck(args.id) is not None:
            print(f"{args.id} has no saved revisions here (the files backend keeps no history).")
            return 0
        _say(f"There's no deck {args.id!r}, and none was ever saved with that id.")
        return 1
    print(f"{args.id}: {_plural(len(revisions), 'revision')}, newest first.")
    for rev in revisions:
        message = rev.message_for(None, everything=True) or ""
        subject, _, body = message.partition("\n")
        what = {"A": "made", "M": "saved", "D": "deleted"}.get(rev.op, rev.op)
        git = f"  git {rev.git_commit[:10]}" if rev.git_commit else ""
        kit = "  (sleeves or deck box)" if rev.kit else ""
        print(f"  {rev.revision:>4}  {_local(rev.at)}  {what} by {rev.actor}{git}{kit}")
        print(f"        {subject}")
        for line in body.strip("\n").splitlines():
            print(f"        {line}" if line.strip() else "")
    return 0


def _revision(args):
    from decklab.lib import inventory
    rev = inventory.deck_revision(args.id, args.number)
    if rev is None:
        _say(f"{args.id} has no revision {args.number} (python -m decklab.db deck history {args.id} lists them).")
        return 1
    if rev.text is None:
        _say(f"Revision {args.number} of {args.id} deleted the deck: it has no text.")
        return 1
    data = rev.text.encode("utf-8")
    if args.output:
        refused = refused_output(args.output)
        if refused:
            _say(f"Not written: {refused}.")
            return 1
        _write_bytes(args.output, data)
        print(f"Wrote revision {args.number} of {args.id} to {args.output}.")
        return 0
    sys.stdout.flush()
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


# ------------------------------------------------------------------ push, new, delete

def read_text(path):
    """A deck text from a file as push and new take it: UTF-8, a leading byte-order mark dropped,
    CRLF and CR made LF, at most MAX_TEXT bytes. ValueError saying what's wrong."""
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        raise ValueError(f"{path} can't be read ({e.strerror or e})") from None
    if len(data) > MAX_TEXT:
        raise ValueError(f"{path} is over {MAX_TEXT // 1024} KiB")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"{path} isn't UTF-8 text ({e})") from None
    return text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def check_text(text, slug, kind, space):
    """The DeckFile text holds, refused (ValueError) when it doesn't parse, has no target list or
    a title that's too long."""
    from decklab.lib import decks
    try:
        found = decks.parse_deck(text.encode("utf-8"), slug, kind, None, space)
    except decks.DeckFileError as e:
        raise ValueError(f"the text isn't a deck Deck Lab can read: {e}") from None
    if not found.has_decklist:
        raise ValueError(f"the text has {decks.NO_DECKLIST}")
    if not found.title or len(found.title) > MAX_TITLE:
        raise ValueError(f"its title (the \"# \" line) must be 1-{MAX_TITLE} characters")
    return found


def expected(deck, expect):
    """None when expect (--expect: a revision number, or a sha256 of at least MIN_SHA hex
    characters) names the deck as it is now; otherwise why not (text)."""
    value = (expect or "").strip().lower()
    if re.fullmatch(r"\d+", value) and len(value) < MIN_SHA:
        if not deck.revision:
            return ("this backend keeps no revision numbers: give the sha256 deck pull printed "
                    f"(at least its first {MIN_SHA} characters) as --expect")
        if int(value) != deck.revision:
            return f"{deck.id} was saved since revision {value} (it's at revision {deck.revision}): pull it again"
        return None
    if not re.fullmatch(f"[0-9a-f]{{{MIN_SHA},64}}", value):
        return f"--expect needs the revision or the sha256 (at least {MIN_SHA} characters) deck pull printed"
    if not deck.sha256.startswith(value):
        return f"{deck.id} was saved since that pull: pull it again"
    return None


def _push_op(inv, *, deck_id, text, base_sha256, changes):
    """push's operation when the Sleeves or Deck box lines change: kit.set chooses them (with the
    picker's checks) and deck.save writes the rest of the text, in one change. kit.set gives kit
    only to a built deck, and deck.save keeps the kit lines as they are, so a push that makes the
    deck built first saves the text with the deck's current kit lines, then runs kit.set, then
    saves the text as pushed; any other push runs kit.set first (a deck losing its kit as it stops
    being built must be cleared while still built)."""
    from decklab.lib import decks
    from decklab.lib.inventory import Summary, ops_accessories, ops_decks
    deck = inv.deck(deck_id)
    before = ops_decks.parsed_deck(deck)
    found = decks.parse_deck(text.encode("utf-8"), deck.slug, deck.kind, None, deck.space)
    if before is not None and before.status != "built" and found.status == "built":
        old_sleeves, old_box = ops_decks.kit_of(before)
        decks.set_sleeves(found, old_sleeves or None)
        decks.set_deck_box(found, old_box or None)
        interim = decks.render_deck_file(found)
        inv, _ = ops_decks.save(inv, deck_id=deck_id, text=interim, base_sha256=base_sha256)
        base_sha256 = inv.deck(deck_id).sha256
    moved, _ = ops_accessories.set_kit(inv, holders=[{"id": deck_id, "expected": base_sha256}], changes=changes,
                                 owners=None)
    out, _ = ops_decks.save(moved, deck_id=deck_id, text=text, base_sha256=moved.deck(deck_id).sha256)
    # The whole push's summary: kit.set has often written the text already (a push changing only
    # the kit lines), so the last save's own would say "Nothing to change".
    return out, Summary(f"Saved {found.title}", {"decks": 1}, {deck.path: ["text", "kit"]}, {"deck": deck_id})


def _registered():
    """Register push's own operation (once)."""
    from decklab.lib import inventory
    if PUSH_KIND not in inventory.kinds():
        inventory.register(PUSH_KIND)(_push_op)


def _kit_changes(before, after):
    """kit.set's changes taking a deck's (Sleeves, Deck box) from before's to after's (DeckFiles)."""
    from decklab.lib.inventory import ops_decks
    old, new = ops_decks.kit_of(before), ops_decks.kit_of(after)
    return [{"holder": before.deck_id, "field": field, "value": value or None}
            for field, was, value in zip(ops_decks.KIT_FIELDS, old, new) if (was or None) != (value or None)]


def _sharing_warnings(changes):
    """accessories.sharing_warning for each sleeves line a push sets: read before the change."""
    from decklab.lib import accessories
    found = (accessories.sharing_warning(c["holder"], c["value"]) for c in changes
             if c["field"] == "sleeves" and c["value"])
    return [words for words in found if words]


def _push(args, actor):
    from decklab.lib import inventory
    from decklab.lib.inventory import Op
    deck = _deck(args.id)
    if deck is None:
        return 1
    why = expected(deck, args.expect)
    if why:
        _say(f"Not saved: {why}.")
        return 1
    try:
        text = read_text(args.file)
        found = check_text(text, deck.slug, deck.kind, deck.space)
    except ValueError as e:
        _say(f"Not saved: {e}.")
        return 1
    dry_run = getattr(args, "dry_run", False)
    if text == deck.text and not dry_run:
        print(f"{found.title} already has this text: nothing to save.")
        return 0
    changes = _kit_changes(parsed(deck), found)
    sharing = _sharing_warnings(changes)
    if changes:
        _registered()
        op = Op(PUSH_KIND, {"deck_id": deck.id, "text": text, "base_sha256": deck.sha256, "changes": changes})
    else:
        op = Op("deck.save", {"deck_id": deck.id, "text": text, "base_sha256": deck.sha256})
    if dry_run:
        after, _ = inventory.preview(op)
        if text != deck.text and not inventory.backend().saves_decks():
            raise inventory.Unavailable(inventory.DECK_SAVES_PAUSED)
        print(f"Would save {deck.id} against {_token_words(deck)} (sha {deck.sha256}).")
        diff = list(difflib.unified_diff(deck.text.splitlines(keepends=True), text.splitlines(keepends=True),
                                        fromfile=f"{deck.id} (current)", tofile=f"{deck.id} (proposed)"))
        if not diff:
            print("No text differences.")
        for line in diff:
            sys.stdout.write(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
        with inventory.pinned(after):
            after_notes(deck.id, verbose=True)
        for words in sharing:
            print(words)
        print("Nothing saved (--dry-run).")
        return 0
    after, summary = inventory.apply(op, actor, args.message.strip())
    saved = after.deck(deck.id)
    print(f"{summary.text}" + (f" (revision {saved.revision})." if saved is not None and saved.revision else "."))
    after_notes(deck.id)
    for words in sharing:
        print(words)
    return 0


def after_notes(deck_id, verbose=False):
    """What push and new say about a deck once it's saved: an out-of-date table, unknown card
    names, the token cards it makes and what accessories --check reports about it."""
    from decklab.lib import accessories, inventory, pool, tokens
    deck = inventory.current().deck(deck_id)
    if deck is None:
        return
    found = parsed(deck)
    pool_of = _pools()
    supply = pool_of(found.space)
    if supply is not None:
        try:
            result = pool.compare(found.target, supply, pool.self_ids(deck_id), prices=False)
            unknown = sorted({name for name, _ in result["unresolved"]})
            # The Considering list (decks/considering.py) never counts, but a card moved from it into
            # the Planned list keeps its name, so its unknown names are said too.
            maybe = sorted({name for name, _ in pool.compare({"Deck": found.considering}, supply,
                                                               pool.self_ids(deck_id), prices=False)["unresolved"]}
                           - set(unknown)) if found.considering else []
            if unknown:
                print(f"Not Scryfall card names: {', '.join(unknown)}.")
            if maybe:
                print(f"Not Scryfall card names in the Considering list: {', '.join(maybe)}.")
            if not unknown and not maybe and verbose:
                print("Card names: all checked names resolve in the card index.")
        except Exception as e:          # noqa: BLE001 - notes only
            print(f"The cards couldn't be checked ({e}).")
    elif verbose:
        print("Card names: couldn't be checked because the card pool couldn't be read.")
    stale = _stale(found, pool_of)
    if stale:
        print(f"Its owned-vs-needed table is out of date: python -m decklab.db deck tables {deck_id} --apply "
              "(--reprice to price it again).")
    elif verbose:
        print("Owned-vs-needed table: " + ("couldn't be checked." if stale is None else
              "not present." if found.rows is None else "up to date."))
    try:
        inv, incoming, _ = tokens.for_space(found.space)
        counts = tokens.deck_tokens(found.target, inv, incoming)["counts"]
        if counts["kinds"]:
            print(f"Tokens: {_plural(counts['kinds'], 'kind')} · {counts['ready']} ready · {counts['check']} to check "
                  f"· {counts['differs']} different · {counts['incoming']} on the way · {counts['none']} none owned "
                  f"(python -m decklab.lib.tokens {deck_id}).")
        elif verbose:
            print("Tokens: no token kinds detected in the proposed list.")
    except Exception as e:              # noqa: BLE001 - no card index: no token note
        if verbose:
            print(f"Tokens: couldn't be checked ({e}).")
    try:
        titles = {h["title"] for entries in accessories.holders().values() for h in entries}
        # A kit line on a deck that isn't built is named by the deck's id ("casual/x has Sleeves ...").
        problems = [p for p in accessories.check()
                    if names_holder(p, found.title, titles) or p.startswith(f"{deck_id} has ")]
    except Exception as e:              # noqa: BLE001 - notes only
        problems = []
        if verbose:
            print(f"Accessories: couldn't be checked ({e}).")
    else:
        if verbose and not problems:
            print("Accessories: no problems found for this deck.")
    for problem in problems:
        print(f"Accessories: {problem}")
    stale_notes(found.space, exclude=(deck_id,), other=True)


def stale_notes(space, exclude=(), other=False):
    """Print (stdout) the decks of space, other than exclude, whose owned-vs-needed tables are now
    out of date (pool.stale_tables), then the deck tables command that updates them or, when
    deck tables --apply would refuse (refresh.table_blockers: it plans every space), every
    problem that stops it. Nothing when none is stale. other: say "other decks" (push and new,
    whose own table after_notes names). Notes only: never raises (one quiet line instead) and
    never changes an exit code."""
    try:
        from decklab.lib import pool
        supply = pool.for_space(space)
        stale = pool.stale_tables(supply, exclude=exclude, only={space})
        if not stale:
            return
        found = pool.table_blockers(supply)
        blockers = [entry["why"] for entry in found["spaces"] + found["decks"]]
    except Exception as e:              # noqa: BLE001 - notes only
        print(f"Whether other decks' tables are out of date couldn't be worked out ({e}).")
        return
    n = len(stale)
    whose = ("deck's" if n == 1 else "decks'") if not other else ("other deck's" if n == 1 else "other decks'")
    tables = "table is" if n == 1 else "tables are"
    print(f"{n} {whose} owned-vs-needed {tables} now out of date: "
          + ", ".join(f"{entry['id']} ({entry['title']})" for entry in stale) + ".")
    if blockers:
        print("deck tables --apply would refuse until this is fixed:")
        for why in dict.fromkeys(blockers):
            print(f"  {why}")
    else:
        print(f"Update {'it' if n == 1 else 'them'}: python -m decklab.db deck tables --apply -m \"...\"")


def names_holder(problem, title, titles=()):
    """Whether an accessories --check problem (text naming holders by title) names the holder
    titled title: as a whole name, not inside another holder's longer title (titles: every
    holder's)."""
    if not title:
        return False
    for other in sorted((t for t in titles if t != title and title in t), key=len, reverse=True):
        problem = problem.replace(other, "\0")
    return re.search(rf"(?<!\w){re.escape(title)}(?!\w)", problem) is not None


def _new(args, actor):
    from decklab.lib import decks, inventory, spaces
    from decklab.lib.inventory import Op
    if args.space != spaces.HOME and not spaces.exists(args.space):
        _say(f"There's no space {args.space!r} in decklab/config.json.")
        return 1
    if not decks.valid_slug(args.slug):
        _say(f"Not made: {decks._slug_problem(args.slug)}.")
        return 1
    try:
        text = read_text(args.file)
        found = check_text(text, args.slug, args.kind, args.space)
    except ValueError as e:
        _say(f"Not made: {e}.")
        return 1
    deck_id = spaces.join_deck_id(args.space, args.kind, args.slug)
    sharing = _sharing_warnings([{"holder": deck_id, "field": "sleeves", "value": found.sleeves or None}])
    _, summary = inventory.apply(Op("deck.create", {"space": args.space, "kind": args.kind, "slug": args.slug,
                                                    "text": text, "owners": None}), actor, args.message.strip())
    print(f"{summary.text} ({deck_id}).")
    after_notes(deck_id)
    for words in sharing:
        print(words)
    return 0


def _delete(args, actor):
    from decklab.lib import inventory
    from decklab.lib.inventory import Op
    deck = _deck(args.id)
    if deck is None:
        return 1
    why = expected(deck, args.expect)
    if why:
        _say(f"Not deleted: {why}.")
        return 1
    if not args.reason.strip():
        _say("--reason needs a reason saying why the deck is deleted.")
        return 1
    _, summary = inventory.apply(Op("deck.delete", {"deck_id": deck.id, "base_sha256": deck.sha256}), actor,
                                 args.message.strip(), reason=args.reason.strip())
    print(f"{summary.text} ({deck.id}); python -m decklab.db deck history {deck.id} still lists its revisions.")
    return 0


# ------------------------------------------------------------------ tables

def repriced(deck):
    """(the deck's text with its owned-vs-needed table worked out and priced again as Deck Lab's
    "Update the table" does, a note or None); the text as it is when it has no table. A table
    whose rate is worded some other way keeps the prices that still apply (no new ones). Cards the
    card data doesn't know are left out of the table and named in the note, as Deck Lab does."""
    from decklab.lib import decks, pool
    found = parsed(deck)
    if found.rows is None:
        return deck.text, "it has no owned-vs-needed table"
    other = "prices_other" in found.spans
    supply = pool.for_space(found.space)
    result = pool.compare(found.target, supply, pool.self_ids(deck.id), prices=not other)
    decks.set_table(found, *pool.table_rows(result))
    notes = []
    if other:
        notes.append("its rate is worded some other way above the table, so its prices weren't changed")
    if result["unresolved"]:
        names = sorted({name for name, _ in result["unresolved"]})
        notes.append(f"cards the card data doesn't know aren't in its table: {', '.join(names)}")
    return decks.render_deck_file(found), "; ".join(notes) or None


class NoSuchDeck(ValueError):
    """plan_tables named a deck that doesn't exist (not one of the refresh's refusals)."""


def plan_tables(ids=(), reprice=False, unchanged=None):
    """[(deck id, title, text now, text after, note)] of the decks (ids, or every deck) whose saved
    tables the inventory changes (refresh.plan_texts' rule; with reprice, also priced again).
    unchanged, a list when given, gets (deck id, title, note) for each deck named in ids whose
    text stays as it is but has a note (no table, say). ValueError (and the refresh's other
    refusals) when it can't be worked out."""
    from decklab.lib import inventory
    from decklab.lib.inventory import refresh
    inv = inventory.current()
    unknown = [i for i in ids if inv.deck(i) is None]
    if unknown:
        raise NoSuchDeck(f"there's no deck {', '.join(unknown)}")
    planned = {deck_id: (title, raw, out, None) for deck_id, title, raw, out in refresh.plan_texts()}
    if reprice:
        for deck_id in ids or sorted(inv.decks):
            deck = inv.deck(deck_id)
            if deck.error is not None:
                continue
            title, raw, out, _ = planned.get(deck_id, (parsed(deck).title, deck.text, deck.text, None))
            text, note = repriced(deck.replace(text=out))
            planned[deck_id] = (title, raw, text, note)
    wanted = set(ids) if ids else None
    if unchanged is not None and wanted:
        unchanged.extend((deck_id, title, note) for deck_id, (title, raw, out, note) in planned.items()
                         if deck_id in wanted and out == raw and note)
    return [(deck_id, title, raw, out, note) for deck_id, (title, raw, out, note) in planned.items()
            if (wanted is None or deck_id in wanted) and out != raw]


def _tables(args, actor):
    from decklab.lib import decks, inventory
    from decklab.lib.inventory import Op
    unchanged = []
    try:
        planned = plan_tables(tuple(args.ids), args.reprice, unchanged)
    except inventory.Unavailable:
        raise                           # exit 2, from decklab.db's main
    except (ValueError, OSError, RuntimeError, decks.DeckFileError, inventory.StateError) as e:
        blockers = [] if isinstance(e, NoSuchDeck) else _blockers()
        if blockers:
            _say("The tables can't be worked out until this is fixed:")
            for why in blockers:
                _say(f"  {why}")
        else:
            _say(f"The tables can't be worked out: {e}")
        return 1
    for deck_id, title, note in unchanged:
        print(f"Not changed: {deck_id} ({title}); {note}")
    if not planned:
        print("Every table is up to date." if not args.ids else "Those tables are up to date.")
        return 0
    if not args.apply:
        for deck_id, title, _, _, note in planned:
            print(f"{'Out of date' if args.check else 'Would update'}: {deck_id} ({title})"
                  + (f"; {note}" if note else ""))
        print(f"{_plural(len(planned), 'deck')} {'need' if len(planned) != 1 else 'needs'} its table updated"
              + ("" if args.check else " (--apply saves them)") + ".")
        return 1 if args.check else 0
    items = [{"id": deck_id, "text": out, "base_sha256": decks.text_sha(raw)} for deck_id, _, raw, out, _ in planned]
    message = (args.message or "").strip() or ("update and reprice owned-vs-needed tables" if args.reprice
                                                else "update owned-vs-needed tables")
    _, summary = inventory.apply(Op("deck.update_tables", {"items": items}), actor, message)
    for deck_id, title, _, _, note in planned:
        print(f"Updated: {deck_id} ({title})" + (f"; {note}" if note else ""))
    print(f"{summary.text}.")
    return 0


def _blockers():
    """Every problem that stops the tables being worked out (refresh.table_blockers' "why"s:
    the spaces' first, then the decks'), [] when none or when that can't be worked out."""
    try:
        from decklab.lib import pool
        found = pool.table_blockers()
        return list(dict.fromkeys(entry["why"] for entry in found["spaces"] + found["decks"]))
    except Exception:                   # noqa: BLE001 - the refusal's own text is said instead
        return []


# ------------------------------------------------------------------ the command

def run(args):
    """Run one deck command (python -m decklab.db deck ...); returns the exit code. The caller
    (decklab.db's main) runs it in one pinned inventory snapshot and turns the inventory's
    refusals into exit 1 and an unreachable database into exit 2."""
    from decklab.lib.inventory import ops_decks  # noqa: F401  (registers deck.*, kit.set, accessory.*, image.*)
    if args.action in ("push", "new", "delete") and not args.message.strip():
        _say("-m needs a message saying what this change does.")
        return 1
    if args.action == "list":
        return _list(args)
    if args.action == "show":
        return _show(args)
    if args.action == "pull":
        return _pull(args)
    if args.action == "history":
        return _history(args)
    if args.action == "revision":
        return _revision(args)
    actor = _actor(args)
    if args.action == "push":
        return _push(args, actor)
    if args.action == "new":
        return _new(args, actor)
    if args.action == "delete":
        return _delete(args, actor)
    return _tables(args, actor)
