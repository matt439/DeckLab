"""The database backend's deck parts (migration 0006: the phase 4 design's D3 with amendments
R1-R6 and the design review): every space's deck texts with their history, accessories.csv's rows
and its pictures, read into the snapshot's decks part and written back. pg.py calls these inside
its own transactions; nothing here opens a connection.

    key = decks_key(c, dbname)               # None: no 0006 tables, or the decks never imported
    part = deck_part(select(c), key[2])      # {decks, accessories, accessory_images, decks_revision}
    count = write_diff(cur, old, new, after, change_set_id, actor, message)
    write_all(cur, t, images, change_set_id, actor, message, history=None, replace=False)

- Reading: the decks part is read on its own and cached by pg.py under decks_revision's row,
  apart from the inventory (so a deck save never reloads the inventory, and an inventory write
  that changed no deck never reloads the deck texts). Picture bytes are never read with it
  (image() fetches one by name). accessories.csv is written out as Deck Lab writes it (its
  standard header, rows by kind, then id) and read back by files.accessories_sheet, so its
  problems and line numbers are the files backend's; with no rows there's no file (the database
  can't tell a header-only file from a missing one: the import refuses a header-only file).
  A Deck's revision is its stored text's number.
- Writing: every deck write goes through put_decks(), which writes the audited deck row (title,
  status and played_by read from the text by decks.parse_deck; kit_version bumped when its
  Sleeves or Deck box change; never their values), the text and the derived deck_line rows in
  one go, so no writer can leave deck_line behind its text. A save that changes a text adds a
  revision (numbered after the deck's last, a deleted one's 'D' included) naming the change set;
  a deletion adds a 'D'. A revision's kit flag says it changed the deck's (Sleeves, Deck box)
  from the revision before it (a new deck's from none; a 'D' of a deck holding them counts): its
  message is then its actor's alone (model.DeckRevision.message_for; the foundation review's H4).
  accessory rows are keyed by id; a picture is written from the bytes the operation's ImageMeta
  holds.
- The import (write_all): every deck, accessory and picture under one change set; each current
  deck's history either one 'A' revision naming that change set, or the revisions git gives
  (history: change_set_id NULL, git's commit, time, author and message; the last one of a
  current deck must be its text, and a deck with no current text must end with a 'D').
  replace=True puts a new set in place of the current one and keeps the history: a deck whose
  text differs from its last revision gets a new one, a deck no longer there a 'D'. Its
  kit_version starts again from 0 or 1 (whether the text has kit lines), so Activity shows every
  kit-holding deck of a replacing import as a kit change (its message then the importer's alone):
  harmless, since an import's message names no accessory. The history's kit flags compare each
  revision's text with the one before it, or are an item's own kit (its commit changed an
  accessory, as phase 4's import of the decks' git history worked out).
- Reading the history: revisions(c, deck_id) newest first without texts, revision(c, deck_id, n)
  with its text, last(c, deck_id): model.DeckRevision each.
"""
import csv
import io
from collections import defaultdict

from . import files, paths, rules, pg_aliases
from .model import Deck, DeckRevision, ImageMeta, Sheet
from .table_rows import ACCESSORY_COLUMNS

CR_TEXT = "the deck's text has carriage returns (the database keeps LF text)"


def migrated(c):
    """True when the database has migration 0006's tables."""
    return bool(c.execute("select to_regclass('public.decks_revision') is not null").fetchone()[0])


def decks_key(c, dbname):
    """(dbname, imported_at, revision, aliases-ready) the connection sees now, or None when the
    database has no 0006 tables or no decks_revision row (the decks were never imported)."""
    if not migrated(c):
        return None
    row = c.execute("select revision, imported_at from decks_revision").fetchone()
    return None if row is None else (dbname, row[1], row[0], pg_aliases.ready(c))


def select(c):
    """The decks part's rows ({table: rows}), texts included but no picture bytes."""
    identity = pg_aliases.select(c)
    rename_version = "d.rename_version" if identity["aliases_ready"] else "0"
    return {
        "identity": identity,
        "deck": c.execute(f"select d.id, d.space_id, d.kind, d.slug, d.revision, t.text, {rename_version} from deck d "
                          "join deck_text t on t.deck_id = d.id").fetchall(),
        "accessory": c.execute(f"select id, {', '.join(ACCESSORY_COLUMNS)} from accessory").fetchall(),
        "accessory_image": c.execute("select file_name, size, sha256 from accessory_image").fetchall(),
    }


def accessories_bytes(rows):
    """accessories.csv's bytes for these rows (each a sequence in rules.ACCESSORY_FIELDS' order),
    as Deck Lab writes it (its standard header, LF, rows by kind, then id); None for no rows."""
    if not rows:
        return None
    dicts = sorted((dict(zip(rules.ACCESSORY_FIELDS, row)) for row in rows), key=rules.accessory_sort_key)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(rules.ACCESSORY_FIELDS)
    for row in dicts:
        writer.writerow([row[k] for k in rules.ACCESSORY_FIELDS])
    return out.getvalue().encode("utf-8")


def deck_part(data, revision):
    """{decks, accessories, accessory_images, decks_revision}: the snapshot fields the decks
    part's rows hold (data as select() reads them)."""
    decks = {}
    for row in data["deck"]:
        _, space, kind, slug, number, text = row[:6]
        deck = Deck(space, kind, slug, text, revision=number, rename_version=row[6] if len(row) > 6 else 0)
        decks[deck.id] = deck
    images = {name: ImageMeta(name, size, sha) for name, size, sha in data["accessory_image"]}
    return {"decks": dict(sorted(decks.items())), **data.get("identity", {}),
            "accessories": files.accessories_sheet(accessories_bytes(data["accessory"])),
            "accessory_images": dict(sorted(images.items())), "decks_revision": str(revision)}


def image(c, name):
    """(bytes, sha256) of the picture with this file name, or None."""
    row = c.execute("select content, sha256 from accessory_image where file_name = %s", (name,)).fetchone()
    return None if row is None else (bytes(row[0]), row[1])


REVISION_COLUMNS = "deck_id, revision, at, actor, message, op, kit, git_commit, change_set_id"


def _revision(row, text=None):
    return DeckRevision(*row, text=text)


def revisions(c, deck_id):
    """[DeckRevision] of a deck's history, newest first, without texts."""
    return [_revision(r) for r in c.execute(f"select {REVISION_COLUMNS} from deck_revision where deck_id = any(%s) "
                                            "order by revision desc", (pg_aliases.lineage(c, deck_id),)).fetchall()]


def revision(c, deck_id, number):
    """The DeckRevision number of a deck with its text, or None."""
    row = c.execute(f"select {REVISION_COLUMNS}, text from deck_revision where deck_id = any(%s) and revision = %s",
                    (pg_aliases.lineage(c, deck_id), number)).fetchone()
    return None if row is None else _revision(row[:-1], row[-1])


def revisions_with_text(c, deck_id, limit):
    """The newest limit DeckRevisions of a deck with their texts, newest first, in one query."""
    return [_revision(r[:-1], r[-1]) for r in c.execute(
        f"select {REVISION_COLUMNS}, text from deck_revision where deck_id = any(%s) order by revision desc limit %s",
        (pg_aliases.lineage(c, deck_id), limit)).fetchall()]


def last(c, deck_id):
    """The newest DeckRevision of a deck, without its text, or None."""
    row = c.execute(f"select {REVISION_COLUMNS} from deck_revision where deck_id = any(%s) order by revision desc "
                    "limit 1", (pg_aliases.lineage(c, deck_id),)).fetchone()
    return None if row is None else _revision(row)


# The lines of a deck's text that Deck Lab writes for itself, left out when edited() compares two revisions:
# the owned-vs-needed table's (and any table's) rows, its price stamp, the substitute list's availability note,
# and the Cover card, Sleeves and Deck box header lines (a picture or a kit chosen isn't an edit of the deck).
NOT_EDITS_RE = (r"(^|\n)(\|[^\n]*|- \*\*(Cover card|Sleeves|Deck box):\*\*[^\n]*"
                r"|[^\n]*1 USD = [0-9.]+ AUD \(ECB rate of[^\n]*"
                r"|<!-- decklab:substitute-availability -->[^\n]*)(?=\n|$)")


def edited(c):
    """{deck id: datetime} of each existing deck's newest edit (inventory.deck_edited): a
    revision whose change set (if any) changed no other deck, and whose text differs from the
    one before it outside the parts NOT_EDITS_RE names (a deck's first revision always does)."""
    aliases = pg_aliases.ready(c)
    identity = "coalesce(a.deck_id, d.deck_id)" if aliases else "d.deck_id"
    joined = " left join deck_alias a on a.alias_id = d.deck_id" if aliases else ""
    rows = c.execute(f"with r as (select {identity} as deck_id, d.revision, d.at, d.change_set_id, "
                     "regexp_replace(coalesce(d.text, ''), %s, '', 'g') as body from deck_revision d"
                     f"{joined}), "
                     "l as (select *, lag(body) over (partition by deck_id order by revision) as before from r) "
                     "select distinct on (l.deck_id) l.deck_id, l.at from l join deck d on d.id = l.deck_id "
                     "where l.body is distinct from l.before "
                     "and (l.change_set_id is null or not exists (select 1 from r o "
                     "where o.change_set_id = l.change_set_id and o.deck_id <> l.deck_id)) "
                     "order by l.deck_id, l.revision desc", (NOT_EDITS_RE,)).fetchall()
    return {deck_id: at for deck_id, at in rows}


# ------------------------------------------------------------------ what a text says

def parsed(deck_id, text):
    """decks.parse_deck's DeckFile of a deck's text, or None when it can't be parsed."""
    from decklab.lib import decks
    space, kind, slug = split_id(deck_id)
    try:
        return decks.parse_deck(text.encode("utf-8"), slug, kind, None, space)
    except decks.DeckFileError:
        return None


def split_id(deck_id):
    """(space, kind, slug) of a deck id."""
    parts = deck_id.split("/")
    return (paths.HOME, *parts) if len(parts) == 2 else tuple(parts)


def summary(deck_file):
    """(title, status, played_by, kit) the deck row keeps of a parsed text (kit: its Sleeves and
    Deck box values, compared only, never stored)."""
    if deck_file is None:
        return "", "", "", (None, None)
    return (deck_file.title or "", deck_file.status or "", deck_file.player or "",
            (deck_file.sleeves, deck_file.deck_box))


def lines(deck_id, deck_file):
    """The deck_line rows of a parsed text (none when it couldn't be parsed)."""
    if deck_file is None:
        return []
    out = []
    for version, sections in (("target", deck_file.target), ("owned", deck_file.owned)):
        for section, found in (sections or {}).items():
            for position, line in enumerate(found):
                out.append((deck_id, version, section, position, line.quantity, line.name, line.set or "",
                            line.number or "", line.finish or "nonfoil"))
    return out


# ------------------------------------------------------------------ writing

def put_decks(cur, items):
    """Write decks: the one writer of deck, deck_text and deck_line (see the module docstring).
    items: [(id, text, revision, kit_version, new)] (new: insert, else update).
    Recreating a historical deck starts a fresh packing epoch at its next revision:
    every earlier rename_version is at most its saved revision, so old checks cannot revive.
    Ordinary first creations start at zero; updates retain the existing epoch."""
    inserts, updates, texts_new, texts_old, ids, derived = [], [], [], [], [], []
    for deck_id, text, revision, kit_version, new in items:
        space, kind, slug = split_id(deck_id)
        deck_file = parsed(deck_id, text)
        title, status, played_by, _ = summary(deck_file)
        if new:
            inserts.append((deck_id, space, kind, slug, title, status, played_by, kit_version, revision))
            texts_new.append((deck_id, text))
        else:
            updates.append((title, status, played_by, kit_version, revision, deck_id))
            texts_old.append((text, deck_id))
        ids.append((deck_id,))
        derived += lines(deck_id, deck_file)
    if ids:
        cur.executemany("delete from deck_line where deck_id = %s", ids)
    if inserts:
        renamed = pg_aliases.ready(cur.connection)
        column = ", rename_version" if renamed else ""
        values = inserts if not renamed else [(*row, row[-1] if row[-1] > 1 else 0) for row in inserts]
        slots = ", ".join(["%s"] * (10 if renamed else 9))
        cur.executemany("insert into deck (id, space_id, kind, slug, title, status, played_by, kit_version, revision"
                        f"{column}) values ({slots})", values)
        cur.executemany("insert into deck_text (deck_id, text) values (%s, %s)", texts_new)
    if updates:
        cur.executemany("update deck set title = %s, status = %s, played_by = %s, kit_version = %s, revision = %s, "
                        "updated_at = now() where id = %s", updates)
        cur.executemany("update deck_text set text = %s where deck_id = %s", texts_old)
    if derived:
        cur.executemany("insert into deck_line (deck_id, version, section, position, quantity, name, set_code, "
                        "collector_number, finish) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)", derived)


def _last_revisions(cur, ids):
    """{deck id: (its last revision number, op, text)} for those of ids with revisions."""
    if not ids:
        return {}
    if pg_aliases.ready(cur.connection):
        cur.execute("select distinct on (coalesce(a.deck_id, r.deck_id)) coalesce(a.deck_id, r.deck_id), "
                    "r.revision, r.op, r.text from deck_revision r left join deck_alias a on a.alias_id = r.deck_id "
                    "where coalesce(a.deck_id, r.deck_id) = any(%s) "
                    "order by coalesce(a.deck_id, r.deck_id), r.revision desc", (list(ids),))
    else:
        cur.execute("select distinct on (deck_id) deck_id, revision, op, text from deck_revision "
                    "where deck_id = any(%s) order by deck_id, revision desc", (list(ids),))
    return {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}


def _add_revisions(cur, rows):
    """Insert deck_revision rows [(deck_id, revision, change_set_id, actor, message, op, text,
    kit)] dated now (the change set's time)."""
    if rows:
        cur.executemany("insert into deck_revision (deck_id, revision, change_set_id, at, actor, message, op, text, "
                        "kit) values (%s, %s, %s, now(), %s, %s, %s, %s, %s)", rows)


def kit_of_text(deck_id, text):
    """(Sleeves, Deck box) a stored text writes ((None, None) for no text or no parse)."""
    return (None, None) if text is None else summary(parsed(deck_id, text))[3]


def _check_lf(deck_id, text):
    if text is not None and "\r" in text:
        raise ValueError(f"{deck_id}: {CR_TEXT}")


def _write_images(cur, names, images):
    """Insert or update the pictures names ({name: ImageMeta with its bytes})."""
    rows = []
    for name in names:
        meta = images.get(name)
        content = None if meta is None else meta.content
        if content is None or ImageMeta.of(name, content) != meta:
            raise ValueError(f"{paths.image(name)} needs its bytes to be saved")
        rows.append((name, bytes(content), len(content), meta.sha256))
    if rows:
        cur.executemany("insert into accessory_image (file_name, content, size, sha256) values (%s, %s, %s, %s) "
                        "on conflict (file_name) do update set content = excluded.content, size = excluded.size, "
                        "sha256 = excluded.sha256", rows)


def _write_accessories(cur, old, new):
    """The difference between two {id: ACCESSORY_COLUMNS} maps; returns how many rows it wrote."""
    gone = [(key,) for key in old.keys() - new.keys()]
    added = [(key, *value) for key, value in new.items() if key not in old]
    changed = [(*value, key) for key, value in new.items() if key in old and old[key] != value]
    if gone:
        cur.executemany("delete from accessory where id = %s", gone)
    if added:
        cur.executemany(f"insert into accessory (id, {', '.join(ACCESSORY_COLUMNS)}) "
                        f"values ({', '.join(['%s'] * (len(ACCESSORY_COLUMNS) + 1))})", added)
    if changed:
        cur.executemany(f"update accessory set {', '.join(f'{c} = %s' for c in ACCESSORY_COLUMNS)} where id = %s",
                        changed)
    return len(gone) + len(added) + len(changed)


def write_diff(cur, old, new, after, change_set_id, actor, message, *, before=None, renamed=None):
    """Write the decks part's difference between two table_rows.tables() results (after: the
    snapshot new came from, whose ImageMeta hold the bytes of the pictures it changed); returns
    how many rows it wrote. ValueError for a text with carriage returns or a changed picture
    without its bytes."""
    old_texts, new_texts = dict(old["deck_text"]), dict(new["deck_text"])
    renamed_rows = 0
    if renamed:
        renamed_rows = pg_aliases.rename(cur, before, after, renamed, change_set_id, actor, message)
        old_texts.pop(renamed["from"], None)
        new_texts.pop(renamed["to"], None)
    made = [i for i in new_texts if i not in old_texts]
    changed = [i for i in new_texts if i in old_texts and old_texts[i] != new_texts[i]]
    gone = [i for i in old_texts if i not in new_texts]
    for deck_id in made + changed:
        _check_lf(deck_id, new_texts[deck_id])
    last = _last_revisions(cur, made + changed + gone)
    kits = {}
    if changed:
        cur.execute("select id, kit_version from deck where id = any(%s)", (changed,))
        kits = dict(cur.fetchall())
    items, revisions = [], []
    for deck_id in made + changed:
        number = last.get(deck_id, (0,))[0] + 1
        text = new_texts[deck_id]
        kit = kit_of_text(deck_id, text)
        moved = kit != kit_of_text(deck_id, old_texts.get(deck_id))
        kit_version = kits.get(deck_id, 0) + moved if deck_id in old_texts else int(moved)
        items.append((deck_id, text, number, kit_version, deck_id not in old_texts))
        revisions.append((deck_id, number, change_set_id, actor, message, "M" if deck_id in old_texts else "A", text,
                          moved))
    if gone:
        # (A deck whose kit_version isn't 0 is a kit change as it goes: missing counts as 0.)
        cur.executemany("delete from deck where id = %s", [(i,) for i in gone])
        revisions += [(i, last.get(i, (0,))[0] + 1, change_set_id, actor, message, "D", None,
                       kit_of_text(i, old_texts[i]) != (None, None)) for i in gone]
    put_decks(cur, items)
    _add_revisions(cur, revisions)
    count = len(items) + len(gone)
    count += _write_accessories(cur, old["accessory"], new["accessory"])
    old_images, new_images = old["accessory_image"], new["accessory_image"]
    put = [name for name, meta in new_images.items() if old_images.get(name) != meta]
    dropped = [(name,) for name in old_images.keys() - new_images.keys()]
    _write_images(cur, put, after.accessory_images)
    if dropped:
        cur.executemany("delete from accessory_image where file_name = %s", dropped)
    return renamed_rows + count + len(put) + len(dropped)


def _history_rows(t, history):
    """deck_revision rows [(deck_id, revision, at, actor, message, op, git_commit, text, kit)] of
    an import's history (see the module docstring), checked against t's current texts; ValueError
    with every reason it's refused."""
    numbered, latest, rows, bad = defaultdict(int), {}, [], []
    for item in history:
        deck_id, op, text = item["deck_id"], item["op"], item.get("text")
        if op not in ("A", "M", "D") or (op == "D") != (text is None):
            bad.append(f"{deck_id}: revision {numbered[deck_id] + 1} is op {op!r} with{'out' if text is None else ''} "
                       f"a text")
            continue
        if text is not None and "\r" in text:
            bad.append(f"{deck_id} at {item.get('git_commit') or '?'}: {CR_TEXT}")
            continue
        numbered[deck_id] += 1
        kit = bool(item.get("kit")) or \
            kit_of_text(deck_id, text) != kit_of_text(deck_id, latest.get(deck_id, (None, None))[1])
        latest[deck_id] = (op, text)
        rows.append((deck_id, numbered[deck_id], item["at"], item["actor"], item["message"], op,
                     item.get("git_commit"), text, kit))
    for deck_id, text in t["deck_text"].items():
        if deck_id not in latest:
            bad.append(f"{deck_id} has no history")
        elif latest[deck_id][1] != text:
            bad.append(f"{deck_id}: its text isn't its last revision's")
    for deck_id, (op, _) in latest.items():
        if deck_id not in t["deck_text"] and op != "D":
            bad.append(f"{deck_id} has no text now, but its history doesn't end with its deletion")
    if bad:
        raise ValueError("the deck history can't be imported: " + "; ".join(bad))
    return rows, dict(numbered)


def write_all(cur, t, images, change_set_id, actor, message, history=None, replace=False):
    """Write a whole decks part (t: table_rows.tables(inv, strict=True)'s deck tables; images: the
    snapshot's {name: ImageMeta with its bytes}) into the 0006 tables, emptied first when replace
    (see the module docstring). The caller has taken the lock and bumps decks_revision."""
    if history is not None and replace:
        raise ValueError("a history is imported only into a database with no decks")
    texts = t["deck_text"]
    for deck_id, text in texts.items():
        _check_lf(deck_id, text)
    if replace:
        last = _last_revisions(cur, set(texts))
        cur.execute("select distinct on (deck_id) deck_id, revision, op from deck_revision order by deck_id, "
                    "revision desc")
        alive = [r[0] for r in cur.fetchall() if r[2] != "D" and r[0] not in texts]
        gone = _last_revisions(cur, alive)
        cur.execute("delete from deck")
        cur.execute("delete from accessory")
        cur.execute("delete from accessory_image")
        items, revisions = [], []
        for deck_id, text in texts.items():
            number, op, kept = last.get(deck_id, (0, "D", None))
            if op == "D" or kept != text:
                number += 1
                revisions.append((deck_id, number, change_set_id, actor, message, "A" if op == "D" else "M", text,
                                  kit_of_text(deck_id, text) != kit_of_text(deck_id, kept)))
            items.append((deck_id, text, number, int(kit_of_text(deck_id, text) != (None, None)), True))
        revisions += [(i, gone[i][0] + 1, change_set_id, actor, message, "D", None,
                       kit_of_text(i, gone[i][2]) != (None, None)) for i in alive]
        put_decks(cur, items)
        _add_revisions(cur, revisions)
    else:
        if history is None:
            numbers = {deck_id: 1 for deck_id in texts}
            _add_revisions(cur, [(i, 1, change_set_id, actor, message, "A", text,
                                  kit_of_text(i, text) != (None, None)) for i, text in texts.items()])
        else:
            rows, numbers = _history_rows(t, history)
            if rows:
                cur.executemany("insert into deck_revision (deck_id, revision, change_set_id, at, actor, message, "
                                "op, git_commit, text, kit) values (%s, %s, null, %s, %s, %s, %s, %s, %s, %s)", rows)
        put_decks(cur, [(i, text, numbers[i], int(kit_of_text(i, text) != (None, None)), True)
                        for i, text in texts.items()])
    _write_accessories(cur, {}, t["accessory"])
    _write_images(cur, sorted(t["accessory_image"]), images)


def without_deck_parts(inv):
    """inv with no deck parts (what the inventory's rows are worked out from while the database
    doesn't hold the decks: a deck file the database couldn't hold never stops an inventory write)."""
    return inv.replace(decks={}, accessories=Sheet(paths.ACCESSORIES), accessory_images={})
