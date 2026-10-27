"""The files backend: the inventory as today's files under magic/ (decklab/PLAN.md phase 3).

    inv = FileInventory(config.REPO).load()            # a working tree (CRLF files are fine)
    inv = FileInventory.from_git("HEAD")                # git's blobs at a revision, never the tree
    files = render(inv)                                 # {path: bytes}: today's files, from a snapshot

FileInventory is the tests' backend (test_api's Sandbox and test_pool's PoolTestCase install
FileInventory(<their temp root>)); this module's parsing and rendering are shared with the
database backend, the nightly export and the check's files round trip. Deck Lab reads only the
database (pg.PgInventory). Phase 4 deleted the git mode the files backend had until then, phase
5a its cross-process lock and write journal, and phase 5b the rollback to the files
(restore-files, the imports and the gates).

Writing (apply) settles the operation's result with changes.prepare (so it refuses what the
database backend refuses, and normalises in the same one place), then writes each changed source
whole, deletes the files of sources that are gone and adds the operation's raw imports, as plain
atomic files under the backend's in-process lock. Before writing anything it checks that every
file is still what the load read (state.Conflict otherwise, nothing written), so a change saved
meanwhile (a test editing a deck file) refuses the whole change. Nothing is committed to git.

Loading never raises for what's in a file, or for a file the OS won't let it read (a file
another program has locked: error is the OSError's text, and only that source is unreadable):
each source keeps its raw rows plus what today's readers would say about it, and a file is
fatal only to the readers it's fatal to today (see model.py). For each source:
- a collection (and a cards payload, and a product read as cards): problems are pool's
  read_card_csv texts ("magic/collection.csv line 3: bad quantity 'x'", "... line 4: no card
  name", lines counted as records from 2, as pool counts them); strict_error is
  merge_cards.read's first complaint (existing=True for a collection), naming the path;
- tokens.csv: rows, lines, problems and sorted exactly as tokens.read() gives them (bad rows are
  left out of rows; each row has every tokens.csv column, "" where an older header lacks one, as
  tokens.read() fills them); strict_error is tokens.read(strict=True)'s TokensError text;
- a tokens payload: every row as read; strict_error is the receipts' strict token read's first
  complaint (rules.parse_csv, then rules.validate_token_row per line);
- status.csv: problems are pool.read_status's warnings (the missing-file one included);
  strict_error is rules.parse_status's;
- a record: data is its JSON as purchases.read_records decodes it (UTF-8, duplicate keys
  refused), or error says why it couldn't be;
- the watchlist: rows as read; strict_error a strict CSV parse's error, if any.
A file that can't be decoded or parsed at all has error set (str of the exception, as today's
readers show it) and no rows. Every CSV source also has csv_error: what a strict csv parse
(csv.DictReader(strict=True), as purchases reads payloads, products and status.csv) raises.
Products, records and payloads are listed in model.name_order (case-insensitive, as today's
readers sort Paths on Windows).

Rendering (render()) is canonical: UTF-8 without a BOM, LF line endings, each source's own
header (a legacy 4-column status.csv stays 4 columns until an operation rewrites it), records as
rules.json_bytes. So a canonical file (every file git holds today) comes back byte for byte; a
fixture with a BOM or CRLF comes back canonical. A space with no collection or tokens file has no
rendered file. Sources that couldn't be read are never rendered.

The revision is the sha256 of every inventory file (paths.is_inventory) by path, with CRLF read as
LF, so a working tree and git's blobs of the same data have the same revision. A raw import
counts by its path and size only (imports are written once and never edited). The tests' file
backend streams their content hashes for repeat-import checks without retaining their bytes.

Phase 4's deck parts (paths.DECK_PARTS: the deck files of every space, accessories.csv and its
pictures) are read and written here too, as ordinary parts of the snapshot (the phase 4 design's
R1), but never count in the inventory's revision: decks_revision is the sha256 of their bytes
by path, raw (a CRLF deck file differs from its LF twin, since its text and so its page sha256
do; a picture is never CRLF-normalised: decks_revision_of). A deck file is its exact text (the
bytes decoded as UTF-8, nothing translated: a CRLF file stays CRLF and renders back byte for
byte); accessories.csv a Sheet of AccessoryRow, its problems and strict_error lib/accessories'
lenient and strict reads' (so accessories.read() can come from the snapshot); a picture its
ImageMeta (size, sha256), its bytes read only on demand (FileInventory.image(name, sha256)). A load
hashes a picture only when its size or modification time changed since the last load (a
process-wide stat cache). git_files(rev, decks=True) and from_git(rev, decks=True) take them
from git's blobs too; render(inv) stays the inventory's files unless decks=True (pictures are
rendered only from bytes an operation holds).
"""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path, PurePosixPath

from . import paths, rules
from .model import (AccessoryRow, CardRow, Deck, ImageMeta, ImportInfo, Inventory, Order, Product, ProductItem,
                    Sheet, StatusRow, TokenRow, WatchRow, name_order)

_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
PRODUCT_STATUSES = ("owned", "preordered", "ordered", "cancelled")     # pool.PRODUCT_STATUSES
TOKEN_LEGACY_FIELDS = ("front", "back", "quantity", "front_details", "back_details", "notes")
# apply's refusal when the inventory moved on since the preview a caller names (both backends).
MOVED_MESSAGE = "The inventory has changed since this was previewed; look at it again and retry."


def atomic_write(path, data):
    """Replace path with data (bytes) through a synced temporary file in the same folder, or
    remove it when data is None; a failed write leaves the old file as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        path.unlink(missing_ok=True)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".",
                                         suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


# ------------------------------------------------------------------ the files

class ImportSize(int):
    """A raw import's size and optional digest, standing in for its bytes in tree_files()."""

    def __new__(cls, size, sha256=None):
        found = super().__new__(cls, size)
        found.sha256 = sha256
        return found


def tree_files(root, import_bytes=False):
    """{repo-relative path: bytes} of every inventory file under root/magic (paths.classify).
    A raw import gives its ImportSize with its streamed hash unless import_bytes (the export
    and tests need the content). A file the OS refuses to read gives the OSError instead of
    bytes (build() makes that source unreadable); one removed while we look is left out."""
    root = Path(root)
    magic = root / "magic"
    candidates = [magic / "collection.csv", magic / "tokens.csv", magic / "watchlist.csv"]
    for pattern in ("imports/*", "people/*/collection.csv", "people/*/tokens.csv", "people/*/imports/*",
                    "products/*.[cC][sS][vV]", "orders/records/*.json"):
        candidates += sorted(magic.glob(pattern))
    for folder in paths.PAYLOAD_FOLDERS:
        candidates += sorted((root / folder).glob("*.[cC][sS][vV]"))   # X.CSV too on a case-sensitive file system
    out = {}
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        found = paths.classify(rel)
        if found is None:
            # X.CSV: the globs find it (Windows' ignores case anyway) and today's readers counted it, but only a lower-case
            # .csv is inventory. Unreadable (with what to do) rather than silently left out; a
            # real X.csv beside it (a case-sensitive file system) wins.
            if path.suffix.lower() == ".csv" and paths.classify(rel[:-4] + ".csv") is not None:
                out.setdefault(rel[:-4] + ".csv", OSError(
                    f"{rel} has an upper-case extension: rename it to {path.stem}.csv"))
            continue
        try:
            if not path.is_file():
                continue
            if found[0] == "import" and not import_bytes:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    out[rel] = ImportSize(os.fstat(stream.fileno()).st_size, digest)
            else:
                out[rel] = path.read_bytes()
        except FileNotFoundError:               # removed while we looked
            continue
        except OSError as e:                    # locked by another program, no permission, ...
            out[rel] = e
    return out


_image_shas = {}                    # (path, size, mtime_ns) -> sha256: the pictures hashed already
_image_lock = threading.Lock()


def _image_meta(path, name):
    """The ImageMeta of the picture at path (hashed again only when its size or mtime changed)."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _image_lock:
        digest = _image_shas.get(key)
    if digest is None:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) == stat.st_size:
            with _image_lock:
                if len(_image_shas) > 4096:
                    _image_shas.clear()
                _image_shas[key] = digest
        return ImageMeta(name, len(content), digest)
    return ImageMeta(name, stat.st_size, digest)


class Folders:
    """Where a FileInventory keeps its deck parts: root/magic/decks, root/magic/people and
    root/magic/accessories.csv with its pictures in root/magic/accessories/images, unless
    decks_dir names another home decks folder (a path, or a callable giving one at each use: a
    test's patched decks.DECKS_DIR), whose people folder is then beside it (as
    lib/spaces.people_dir() says) unless people_dir names one; accessories and images likewise
    name another accessories.csv and pictures folder (a test's patched accessories.PATH and
    IMAGES). path(rel) is the file a repo-relative deck-part path is kept in."""

    def __init__(self, root, decks_dir=None, people_dir=None, accessories=None, images=None):
        self.root = Path(root)
        self._decks = decks_dir
        self._people = people_dir
        self._accessories = accessories
        self._images = images

    @property
    def moved(self):
        return any(x is not None for x in (self._decks, self._people, self._accessories, self._images))

    @staticmethod
    def _at(found):
        found = found() if callable(found) else found
        return None if found is None else Path(found)

    def accessories(self):
        return self._at(self._accessories) or self.root / paths.ACCESSORIES

    def images(self):
        return self._at(self._images) or self.root / paths.IMAGES

    def decks(self):
        found = self._decks() if callable(self._decks) else self._decks
        return Path(found) if found is not None else self.root / paths.DECKS

    def people(self):
        found = self._people() if callable(self._people) else self._people
        if found is not None:
            return Path(found)
        return self.decks().parent / "people" if self._decks is not None else self.root / paths.PEOPLE

    def path(self, rel):
        if rel == paths.ACCESSORIES:
            return self.accessories()
        if rel.startswith(paths.IMAGES + "/"):
            return self.images() / rel[len(paths.IMAGES) + 1:]
        parts = rel.split("/")
        if parts[:2] == ["magic", "decks"]:
            return self.decks().joinpath(*parts[2:])
        if parts[:2] == ["magic", "people"] and len(parts) > 3 and parts[3] == "decks":
            return self.people().joinpath(*parts[2:])
        return self.root / rel

    def candidates(self):
        """[(repo-relative path, file)] of every file that may be a deck part."""
        out = [(paths.ACCESSORIES, self.accessories())]
        for kind in paths.DECK_KINDS:
            out += [(f"{paths.DECKS}/{kind}/{p.name}", p) for p in sorted(self.decks().joinpath(kind).glob("*.md"))]
        for folder in sorted(p for p in self.people().glob("*") if p.is_dir()):
            for kind in paths.DECK_KINDS:
                out += [(f"{paths.PEOPLE}/{folder.name}/decks/{kind}/{p.name}", p)
                        for p in sorted(folder.joinpath("decks", kind).glob("*.md"))]
        out += [(f"{paths.IMAGES}/{p.name}", p) for p in sorted(self.images().glob("*"))]
        return out


def deck_tree_files(root, folders=None):
    """{repo-relative path: bytes, or ImageMeta for a picture} of every deck part under
    root/magic (paths.is_deck_part): every space's deck files, accessories.csv and its pictures
    (folders: a Folders saying where they are, when not under root/magic). A file the OS
    refuses to read gives the OSError instead; one removed while we look is left out."""
    folders = folders or Folders(root)
    out = {}
    for rel, path in folders.candidates():
        found = paths.classify(rel)
        if found is None or found[0] not in paths.DECK_PARTS:
            continue
        try:
            if not path.is_file():
                continue
            out[rel] = _image_meta(path, found[1]) if found[0] == "image" else path.read_bytes()
        except FileNotFoundError:               # removed while we looked
            continue
        except OSError as e:                    # locked by another program, no permission, ...
            out[rel] = e
    return out


def _git(args, repo, input=None):
    done = subprocess.run(["git", *args], cwd=repo, input=input, capture_output=True, **_SPAWN)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def git_files(rev="HEAD", repo=None, decks=False):
    """(commit sha, {path: bytes}) of every inventory file in git's blobs at rev (LF as git
    keeps them, whatever core.autocrlf does to a checkout); with decks, every deck part too
    (deck files, accessories.csv and its pictures, as git keeps them)."""
    from decklab.lib import config
    repo = Path(repo or config.REPO)
    sha = _git(["rev-parse", "--verify", f"{rev}^{{commit}}"], repo).decode().strip()
    listing = _git(["ls-tree", "-r", "-z", "--full-tree", sha, "--", "magic"], repo).split(b"\0")
    blobs = []
    for entry in listing:
        if not entry:
            continue
        info, path = entry.split(b"\t", 1)
        mode, kind, blob = info.decode().split()
        rel = path.decode("utf-8")
        if kind == "blob" and mode != "120000" and (paths.is_inventory(rel) or (decks and paths.is_deck_part(rel))):
            blobs.append((blob, rel))
    out = {}
    if blobs:
        data = _git(["cat-file", "--batch"], repo, input="".join(f"{blob}\n" for blob, _ in blobs).encode())
        pos = 0
        for _, rel in blobs:
            end = data.index(b"\n", pos)
            size = int(data[pos:end].split()[2])
            out[rel] = data[end + 1:end + 1 + size]
            pos = end + 1 + size + 1
    return sha, out


def revision_of(files):
    """The revision of a set of inventory files: sha256 over (path, bytes with CRLF as LF), by
    path; a raw import by its size alone, and a file that couldn't be read by its error. Deck
    parts among them don't count (decks_revision_of)."""
    digest = hashlib.sha256()
    for rel in sorted(files):
        if not paths.is_inventory(rel):
            continue
        data = files[rel]
        if isinstance(data, OSError):
            data = b"\1unreadable " + str(data).encode("utf-8", "replace")
        elif paths.classify(rel)[0] == "import":
            data = b"\1size " + str(len(data) if isinstance(data, bytes) else int(data)).encode()
        else:
            data = data.replace(b"\r\n", b"\n")
        digest.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


def decks_revision_of(files):
    """The decks_revision of a set of files: sha256 over (path, raw bytes) of each deck part
    among them, by path (a picture by its sha256, given as bytes or an ImageMeta; a file that
    couldn't be read by its error). Nothing is CRLF-normalised: a deck's page sha256 is over its
    exact bytes, and a picture is binary."""
    digest = hashlib.sha256()
    for rel in sorted(files):
        if not paths.is_deck_part(rel):
            continue
        data = files[rel]
        if isinstance(data, OSError):
            data = b"\1unreadable " + str(data).encode("utf-8", "replace")
        elif isinstance(data, ImageMeta):
            data = b"\1sha256 " + data.sha256.encode()
        elif paths.classify(rel)[0] == "image":
            data = b"\1sha256 " + hashlib.sha256(data).hexdigest().encode()
        digest.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


# ------------------------------------------------------------------ parsing

def _decode(data, encoding="utf-8-sig"):
    """(text, None), or (None, why) when data isn't valid in encoding."""
    try:
        return data.decode(encoding), None
    except UnicodeDecodeError as e:
        return None, str(e)


def _dict_rows(text):
    """(header, [(values, overflow, line)]) as csv.DictReader reads text: the first row is the
    header, empty rows are skipped, a short row's missing cells are None, cells past the header
    are overflow; line is where each row starts. Raises csv.Error as DictReader does."""
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader, None)
    if header is None:
        return None, []
    rows = []
    start = reader.line_num + 1
    for cells in reader:
        line, start = start, reader.line_num + 1
        if cells == []:
            continue
        values = tuple(zip(header, cells)) + tuple((c, None) for c in header[len(cells):])
        rows.append((values, tuple(cells[len(header):]), line))
    return tuple(header), rows


def _strict_csv(text):
    """The error a strict csv parse of text raises, or None."""
    try:
        for _ in csv.reader(io.StringIO(text, newline=""), strict=True):
            pass
    except csv.Error as e:
        return str(e)
    return None


def _card_problems(rel, rows):
    """pool.read_card_csv's texts for the rows it leaves out (bad quantity, no name), lines
    counted from 2 by record as it counts them."""
    out = []
    for n, row in enumerate(rows, 2):
        name = (row.get("name") or "").strip()
        try:
            qty = int(row["quantity"])
            if qty <= 0:
                raise ValueError("quantity must be positive")
        except (KeyError, TypeError, ValueError):
            out.append(f"{rel} line {n}: bad quantity {row.get('quantity')!r}")
        else:
            if not name:
                out.append(f"{rel} line {n}: no card name")
    return tuple(out)


def _lenient(rel, data, row_class):
    """(text, header, rows, error): data read as csv.DictReader would, rows as row_class."""
    if isinstance(data, OSError):
        return None, None, (), str(data)
    text, error = _decode(data)
    if error is not None:
        return None, None, (), error
    try:
        header, raw = _dict_rows(text)
    except csv.Error as e:
        return text, None, (), str(e)
    rows = tuple(row_class(values, overflow, line) for values, overflow, line in raw)
    return text, header, rows, None


def _cards_sheet(rel, data, existing):
    text, header, rows, error = _lenient(rel, data, CardRow)
    if error is not None:
        return Sheet(rel, exists=True, error=error)
    try:
        rules.parse_cards(io.StringIO(text, newline=""), rel, existing=existing)
        strict = None
    except (rules.InvalidCards, csv.Error) as e:
        strict = str(e)
    return Sheet(rel, header, rows, True, None, _card_problems(rel, rows), strict, csv_error=_strict_csv(text))


class _Strict(Exception):
    pass


def _token_read(label, text, strict):
    """tokens.read()'s reading of text (decoded), as (header, rows, lines, problems); in strict
    mode the first problem raises _Strict with the TokensError text."""
    rows, lines, problems = [], [], []

    def problem(message):
        if strict:
            raise _Strict(f"{message}{rules.UNTIL_PUT_RIGHT}")
        problems.append(message)

    reader = csv.reader(io.StringIO(text, newline=""), strict=strict)
    header = []
    try:
        header = next(reader, None) or []
        if header != rules.TOKEN_FIELDS:
            fixable = "line 1: the header must be " + ",".join(rules.TOKEN_FIELDS)
            if strict or len(set(header)) != len(header):
                problem(f"{label} {fixable}")
                return header, rows, lines, problems
            if set(header) == set(TOKEN_LEGACY_FIELDS):
                problems.append(f"{label} lacks the printing columns; fix the header by hand "
                                f"before the Tokens page can save")
            elif set(header) == set(rules.TOKEN_FIELDS):
                problems.append(f"{label}'s columns aren't in the standard order; fix the header "
                                f"by hand before the Tokens page can save")
            else:
                problem(f"{label} {fixable}")
                return header, rows, lines, problems
        start = reader.line_num + 1
        for values in reader:
            n, start = start, reader.line_num + 1
            if not any(v.strip() for v in values):
                continue
            where = f"{label} line {n}"
            if len(values) != len(header):
                problem(f"{where}: {len(values)} values, not {len(header)}")
                continue
            row = {key: "" for key in rules.TOKEN_FIELDS}
            row.update((k, v) for k, v in zip(header, values) if k in row)
            try:
                rules.token_rules(row, where)
            except ValueError as e:
                problem(str(e))
                continue
            rows.append(row)
            lines.append(n)
    except csv.Error as e:
        problem(f"{label} line {reader.line_num}: {e}")
    return header, rows, lines, problems


def _tokens_sheet(rel, data):
    if isinstance(data, OSError):
        return Sheet(rel, exists=True, error=str(data), problems=(f"{rel} can't be read ({data})",),
                     strict_error=f"{rel} can't be read ({data}){rules.UNTIL_PUT_RIGHT}")
    text, error = _decode(data)
    if error is not None:
        return Sheet(rel, exists=True, error=error, problems=(f"{rel} isn't UTF-8 text",),
                     strict_error=f"{rel} isn't UTF-8 text{rules.UNTIL_PUT_RIGHT}")
    header, rows, lines, problems = _token_read(rel, text, strict=False)
    try:
        _token_read(rel, text, strict=True)
        strict = None
    except _Strict as e:
        strict = str(e)
    columns = tuple(header) if header else None
    # Each row has every column, as tokens.read() fills them; the header is the file's own, so a
    # legacy or reordered file still renders as it was read.
    made = tuple(TokenRow(tuple((k, row[k]) for k in rules.TOKEN_FIELDS), (), line, n)
                 for n, (row, line) in enumerate(zip(rows, lines), 1))
    in_order = rows == sorted(rows, key=rules.token_sort_key)
    return Sheet(rel, columns, made, True, None, tuple(problems), strict, in_order, _strict_csv(text))


def _token_payload_sheet(rel, data):
    text, header, rows, error = _lenient(rel, data, TokenRow)
    if error is not None:
        return Sheet(rel, exists=True, error=error)
    strict = None
    try:
        found = rules.parse_csv(io.StringIO(text, newline=""), rules.TOKEN_FIELDS, rel)
        for line, row in zip(rules.record_lines(io.StringIO(text, newline="")), found):
            rules.validate_token_row(row, f"{rel} line {line}")
    except (ValueError, csv.Error) as e:
        strict = str(e)
    return Sheet(rel, header, rows, True, None, (), strict, csv_error=_strict_csv(text))


def _status_problems(rows):
    """pool.read_status's warnings for status.csv's rows."""
    name = paths.STATUS_NAME
    out = []
    for n, row in enumerate(rows, 2):
        file = (row.get("file") or "").strip()
        status = (row.get("status") or "").strip().lower()
        intact = (row.get("intact") or "").strip().lower()
        if intact not in ("yes", "no", ""):
            out.append(f"{name} line {n}: {file} has intact {intact!r}, not yes or no; treated as no")
        if status not in PRODUCT_STATUSES:
            out.append(f"{name} line {n}: {file} has status {status!r}, not one of "
                       f"{', '.join(PRODUCT_STATUSES)}; it is left out of every count")
            status, intact = "owned", "no"
        sleeves = (row.get("sleeves") or "").strip()
        deck_box = (row.get("deck_box") or "").strip()
        if (sleeves or deck_box) and not (status == "owned" and intact == "yes"):
            out.append(f"{name} line {n}: {file} has sleeves or a deck box but isn't "
                       f"owned and kept intact; clear them, since its cards are stored unsleeved")
        packed = (row.get("token_cards") or "").strip()
        if packed:
            if not (status == "owned" and intact == "yes"):
                out.append(f"{name} line {n}: {file} has packed token cards but isn't owned and kept intact; clear them")
            try:
                from decklab.lib.decks.tokencards import parse_token_cards
                parse_token_cards(packed)
            except ValueError as error:
                out.append(f"{name} line {n}: {file}'s packed token cards can't be read: {error}")
    return tuple(out)


def status_sheet(data):
    """products/status.csv's Sheet from its bytes (None: the file is missing)."""
    rel = paths.STATUS
    if data is None:
        return Sheet(rel, problems=(f"{rel} is missing, so every product counts as owned and not intact",))
    text, header, rows, error = _lenient(rel, data, StatusRow)
    if error is not None:
        return Sheet(rel, exists=True, error=error)
    try:
        rules.parse_status(text, rel)
        strict = None
    except (ValueError, csv.Error) as e:
        strict = str(e)
    return Sheet(rel, header, rows, True, None, _status_problems(rows), strict, csv_error=_strict_csv(text))


# The display names and formats a snapshot built from files gives its products, by stem: the
# product files can't carry them. Empty in Deck Lab, whose products' names are the database's
# (pg.py); the tests fill it in (decklab/tests/__init__.py) with the names the files went by
# before the database. A product with none gets each reader's own fallback (model.Product.label).
PRODUCT_NAMES = {}


def _product(stem, data):
    rel = paths.product(stem)
    name, fmt = PRODUCT_NAMES.get(stem, (None, None))
    text, header, items, error = _lenient(rel, data, ProductItem)
    if error is not None:
        return Product(stem, name=name, format=fmt, error=error)
    try:
        rules.parse_cards(io.StringIO(text, newline=""), rel)
        strict = None
    except (rules.InvalidCards, csv.Error) as e:
        strict = str(e)
    return Product(stem, header, items, name, fmt, None, _card_problems(rel, items), strict, _strict_csv(text))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _order(file_name, data):
    if isinstance(data, OSError):
        return Order(file_name, None, str(data))
    text, error = _decode(data, "utf-8")
    if error is not None:
        return Order(file_name, None, error)
    try:
        return Order(file_name, json.loads(text, object_pairs_hook=_unique))
    except ValueError as e:
        return Order(file_name, None, str(e))


def watchlist_sheet(data):
    """magic/watchlist.csv's Sheet from its bytes (None: the file is missing)."""
    rel = paths.WATCHLIST
    if data is None:
        return Sheet(rel)
    text, header, rows, error = _lenient(rel, data, WatchRow)
    if error is not None:
        return Sheet(rel, exists=True, error=error)
    rows = tuple(WatchRow(r.values, r.overflow, r.line, n) for n, r in enumerate(rows, 1))
    strict = _strict_csv(text)
    return Sheet(rel, header, rows, True, None, (), strict, csv_error=strict)


def deck_of(rel, data):
    """The Deck the deck file at rel holds (its exact text, or error when it isn't UTF-8 or the
    OS refused to read it)."""
    space, kind, slug = paths.classify(rel)[1]
    if isinstance(data, OSError):
        return Deck(space, kind, slug, error=str(data))
    text, error = _decode(data, "utf-8")
    if error is not None:
        return Deck(space, kind, slug, error=f"not UTF-8: {error}")
    return Deck(space, kind, slug, text)


def accessories_sheet(data):
    """magic/accessories.csv's Sheet from its bytes (None: the file is missing): every row as
    csv.DictReader reads it, problems the texts lib/accessories' lenient read gives for the rows
    it leaves out ("accessories.csv line 4: ..."), strict_error its strict read's (the writers')."""
    rel = paths.ACCESSORIES
    if data is None:
        return Sheet(rel)
    text, header, rows, error = _lenient(rel, data, AccessoryRow)
    if error is not None:
        return Sheet(rel, exists=True, error=error)
    from decklab.lib import accessories
    problems = tuple(accessories.parse(data).problems)
    try:
        accessories.parse(data, strict=True)
        strict = None
    except accessories.AccessoriesError as e:
        strict = str(e)
    return Sheet(rel, header, rows, True, None, problems, strict, csv_error=_strict_csv(text))


def image_meta(name, data):
    """A picture's ImageMeta from its bytes, or as given (an ImageMeta); None for an OSError."""
    if isinstance(data, ImageMeta):
        return data
    if isinstance(data, OSError):
        return None
    return ImageMeta(name, len(data), hashlib.sha256(data).hexdigest())


def build(files, revision=None, backend="files", decks_revision=None):
    """The Inventory a set of files ({path: bytes, an ImportSize, an ImageMeta or an OSError}, as
    tree_files, deck_tree_files or git_files give) holds. Never raises for what's in a file (see
    the module docstring)."""
    collections, tokens, imports, products, orders, payloads = {}, {}, {}, [], [], {}
    status = watchlist = accessories = None
    deck_parts, images = {}, {}
    for rel in sorted(files):
        found = paths.classify(rel)
        if found is None:
            continue
        what, detail = found
        data = files[rel]
        if what == "collection":
            collections[detail] = _cards_sheet(rel, data, existing=True)
        elif what == "tokens":
            tokens[detail] = _tokens_sheet(rel, data)
        elif what == "import":
            space, name = detail
            size = len(data) if isinstance(data, bytes) else 0 if isinstance(data, OSError) else int(data)
            digest = hashlib.sha256(data).hexdigest() if isinstance(data, bytes) else getattr(data, "sha256", None)
            imports.setdefault(space, []).append(ImportInfo(name, size, digest))
        elif what == "status":
            status = data
        elif what == "watchlist":
            watchlist = data
        elif what == "product":
            products.append(_product(detail, data))
        elif what == "record":
            orders.append(_order(PurePosixPath(rel).name, data))
        elif what == "payload":
            kind = detail[0]
            payloads[rel] = _cards_sheet(rel, data, existing=False) if kind == "cards" \
                else _token_payload_sheet(rel, data)
        elif what == "deck":
            deck = deck_of(rel, data)
            deck_parts[deck.id] = deck
        elif what == "accessories":
            accessories = data
        elif what == "image":
            meta = image_meta(detail, data)
            if meta is not None:            # a picture the OS won't read: as if it weren't there
                images[detail] = meta
    products.sort(key=lambda p: name_order(p.file))
    orders.sort(key=lambda o: name_order(o.file))
    return Inventory(
        revision=revision if revision is not None else revision_of(files),
        collections=dict(sorted(collections.items())), tokens=dict(sorted(tokens.items())),
        imports={space: tuple(sorted(found, key=lambda i: i.name)) for space, found in sorted(imports.items())},
        status=status_sheet(status), products=tuple(products), orders=tuple(orders),
        payloads=dict(sorted(payloads.items())), watchlist=watchlist_sheet(watchlist), backend=backend,
        decks_revision=decks_revision if decks_revision is not None else decks_revision_of(files),
        decks=dict(sorted(deck_parts.items())), accessories=accessories_sheet(accessories),
        accessory_images=dict(sorted(images.items())))


# ------------------------------------------------------------------ rendering

def _csv_text(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        if row.columns() == tuple(columns):
            cells = ["" if value is None else value for _, value in row.values]
        else:
            cells = [row.text(column) for column in columns]
        writer.writerow(cells + list(row.overflow))
    return out.getvalue().encode("utf-8")


def render_sheet(sheet, columns=None):
    """A sheet's file bytes (header: its own columns, else columns, else its rows' standard
    columns); b"" for a file that was empty."""
    columns = sheet.columns if sheet.columns is not None else columns
    if columns is None and sheet.rows:
        columns = type(sheet.rows[0]).COLUMNS or sheet.rows[0].columns()
    if columns is None:
        return b""
    return _csv_text(columns, sheet.rows)


def render_product(product):
    return b"" if product.columns is None else _csv_text(product.columns, product.items)


def render_order(order):
    return rules.json_bytes(order.data)


def sources(inv):
    """{path: source} of every source of inv that has a file (exists, or a product, record,
    deck or picture), whether or not it can be rendered: the deck parts included."""
    out = {}
    for sheet in (*inv.collections.values(), *inv.tokens.values(), inv.status, inv.watchlist,
                  *inv.payloads.values(), inv.accessories):
        if sheet.exists:
            out[sheet.path] = sheet
    for product in inv.products:
        out[product.path] = product
    for order in inv.orders:
        out[order.path] = order
    for deck in inv.decks.values():
        out[deck.path] = deck
    for meta in inv.accessory_images.values():
        out[meta.path] = meta
    return dict(sorted(out.items()))


def render_source(source):
    """A source's bytes, or None when it can't be rendered (it couldn't be read; a picture
    without the bytes an operation gave it)."""
    if isinstance(source, ImageMeta):
        return source.content
    if getattr(source, "error", None) is not None:
        return None
    if isinstance(source, Deck):
        return source.data
    if isinstance(source, Product):
        return render_product(source)
    if isinstance(source, Order):
        return render_order(source)
    return render_sheet(source)


def render(inv, decks=False):
    """{path: bytes}: today's files for every readable source of inv (see the module docstring):
    the inventory's, and with decks the deck files and accessories.csv too (and any picture whose
    bytes the snapshot holds)."""
    out = {}
    for rel, source in sources(inv).items():
        if not decks and not paths.is_inventory(rel):
            continue
        data = render_source(source)
        if data is not None:
            out[rel] = data
    return out


def rendered_sha256(sheet):
    """The sha256 of a collection's or tokens' rendered file (what the pages send back to say
    which version they edited); the sha256 of no bytes when the space has no file."""
    return hashlib.sha256(render_sheet(sheet) if sheet.exists else b"").hexdigest()


# ------------------------------------------------------------------ the backend

class FileInventory:
    """The inventory as files under root/magic. Nothing is cached: every load() reads the
    files, so a test may change them between calls. decks_dir, people_dir, accessories and
    images: where the deck parts are when not under root (Folders)."""

    name = "files"

    def __init__(self, root, decks_dir=None, people_dir=None, accessories=None, images=None):
        self.root = Path(root)
        self.folders = Folders(root, decks_dir, people_dir, accessories, images)
        self._lock = threading.RLock()

    def __repr__(self):
        return f"FileInventory({str(self.root)!r})"

    def _files(self, import_bytes=False):
        """Every file the snapshot is made of: the inventory's and the deck parts."""
        return {**tree_files(self.root, import_bytes), **deck_tree_files(self.root, self.folders)}

    def load(self):
        """The files as they are now."""
        return build(self._files()).replace(root=str(self.root))

    @staticmethod
    def from_git(rev="HEAD", repo=None, decks=False):
        """The Inventory git's blobs hold at rev (in the repo, config.REPO by default); with
        decks, its deck parts too."""
        _, files = git_files(rev, repo, decks=decks)
        return build(files)

    def revision(self):
        return revision_of(tree_files(self.root))

    def decks_revision(self):
        return decks_revision_of(deck_tree_files(self.root, self.folders))

    def image(self, name, sha256=None):
        """The bytes of the picture with this file name, or None when there's none (or, given
        sha256, when its bytes aren't those: the snapshot a page read is older or newer)."""
        try:
            data = self.folders.path(paths.image(name)).read_bytes()
        except (ValueError, OSError):
            return None
        if sha256 is not None and hashlib.sha256(data).hexdigest() != sha256:
            return None
        return data

    def deck_revisions(self, deck_id):
        """A deck's saved revisions: the files keep no history ([])."""
        return []

    def deck_revision(self, deck_id, number):
        return None

    def last_revision(self, deck_id):
        return None

    def saves_decks(self):
        """Whether an operation may change the deck parts here: always (they're files)."""
        return True

    def reachable(self):
        return True

    # -------------------------------------------------------- writing

    def apply(self, op, actor, message, reason=None, expected_revision=None):
        """Run op on the files as they are now and write what it changed (inventory.apply's
        contract; see the module docstring). Returns (the snapshot after, the op's Summary)."""
        from decklab.lib.state import Conflict

        from . import changes
        with self._lock:
            raw = self._files()
            before = build(raw).replace(root=str(self.root))
            if expected_revision is not None and before.revision != expected_revision:
                raise Conflict(MOVED_MESSAGE)
            after, summary = op.run(changes.detach(before))
            after = changes.prepare(before, after)
            writes = self._writes(raw, before, after, (summary.extra or {}).get("imports", ()))
            if not writes:
                return before, summary
            self._write_plain(message, writes)
            return self.load(), summary

    def _write_plain(self, message, writes):
        """writes ({path: (bytes now, bytes after or None to delete)}) as plain atomic files,
        without a commit; message names the write (unused: the files keep no record of it).
        state.Conflict, with nothing written, when a file isn't what the load read. The caller
        holds self._lock."""
        from decklab.lib.state import Conflict
        for rel, (before, _) in writes.items():
            try:
                now = self.folders.path(rel).read_bytes()
            except FileNotFoundError:
                now = None
            if now != before:
                raise Conflict(f"Changed while preparing the write: {rel}")
        for rel, (_, data) in writes.items():
            atomic_write(self.folders.path(rel), data)

    def _writes(self, raw, before, after, imports):
        """{path: (bytes on disk now or None, bytes to write or None to delete)} for what a
        settled after changes from before, plus the raw imports ([(space, file name, bytes)];
        ValueError for one that's already there)."""
        old, new = sources(before), sources(after)
        out = {}
        for rel, source in new.items():
            if old.get(rel) == source:
                continue
            data = render_source(source)
            if data is None:
                raise ValueError(f"{rel} can't be written: it couldn't be read ({source.error})")
            had = self._had(raw, rel)
            if had != data:
                out[rel] = (had, data)
        for rel in old.keys() - new.keys():
            out[rel] = (self._had(raw, rel), None)
        for space, name, data in imports:
            rel = f"{paths.imports_dir(space)}/{name}"
            if rel in out or (self.root / rel).exists():
                raise ValueError(f"{rel} already exists")
            out[rel] = (None, bytes(data))
        return dict(sorted(out.items()))

    def _had(self, raw, rel):
        """The bytes on disk at rel as the load read them (a picture's are read now), or None."""
        found = raw.get(rel)
        if isinstance(found, ImageMeta):
            try:
                return self.folders.path(rel).read_bytes()
            except FileNotFoundError:
                return None
        return found if isinstance(found, bytes) else None
