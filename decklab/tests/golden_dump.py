"""The reader dumps the inventory contract tests compare with their committed goldens
(decklab/tests/fixtures/inventory_goldens): what the readers say, as JSON. This was phase 3's and
phase 4's gate (decklab/db/gate.py) until phase 5b retired the gates; the tests keep its dump
and compare.

What a dump holds (each item is the reader's own function, called as the server or the CLI calls it):
- per space: load_pool (owned, on_the_way in order, in_use, unresolved names with their places
  sorted, warnings) and printing_counts;
- every summary in list_decks() and beginner_box_pairings(), with each of its versions'
  owned_vs_needed, without prices and with prices under a fixed USD->AUD rate (FIXED_RATE; the
  card prices themselves come from the local card index as they are);
- every deck file's deck_table (prices off and on), stale_tables(), and inventory/refresh.py's
  plan_refresh() as {deck file: sha256 of the bytes it would write};
- purchases.overview(), read_records(), read_queue() and _coverage()'s warnings;
- list_decks(), load_deck for every product and pairing id, and pool.read_status();
- forge.field.field_lists and field_notes for Constructed and Commander (lists._source stubbed,
  since it asks git about files in the real repo);
- accessories.holders() and _scan() (deck and product holders), and tokens' holders per space;
- api/collection's _special_basics and every page of the collection view, per space;
- per space, tokens.read() (rows, problems, sorted, lines, sha256), tokens.check(), row_uses
  and gaps; and the pending token orders (tokens.incoming()) as the Tokens page shows them;
- the pages that show inventory numbers: the library index (decks_index, with its chips), every
  deck page (deck_view for each deck and version, without "practice" and "matchups", which are
  saved Forge results and analysis rather than inventory), the assembly view (empty and with each home deck chosen), the
  editor's printing picker (printings) and each profile's wishlist view (wishlists._view) for a
  fixed sample of names (the first 40 owned, and every name on the way, in the profile's space).

Phase 4 moves the deck files, accessories.csv and its pictures into the database; dump(decks=True)
adds every deck- and accessory-reading output to the items above, keyed by deck id (never by a
file path, which the ported code won't have), each asked as today's server or CLI asks it:
- "deck_files": per deck file, read_deck_file's parse (header fields as written, unowned keys
  included, the target and owned-only lists, the table's rows and total, the price stamp,
  changed_on, newline, spans, the owned header values) without the text, with the sha256 of the
  blob's bytes and of the text, and the repo path;
- per viewer (VIEWERS: each a tunnel login, access.using, and a local request naming nobody,
  golden_p4.LOCAL): decks_index, deck_view of every deck file and product deck and each version
  (without practice and matchups), the editor's edit_view and a check_draft that sends the lists
  back unchanged (the drafts dry run), drafts.built_sleeves, and the assembly view with each home
  deck chosen;
- "accessories": read() (rows, sha256, problems), image_url per row, status_sha256(), check()'s
  messages, and per viewer: the row ids it sees, the Accessories page (accessories_view), kit()
  of every deck and product holder, and what its /accessory-img/ route gives for every picture a
  row names or the pictures folder holds (type, size and sha256, or the refusal);
- "forge_entries": variants.base_entry (lists.entry: the .dck text, card_sha, pilot; source
  stubbed) for every deck, product deck and pairing and each version;
- "practice": per deck and version, goldfish's _deck_key, the engine kind and the cache key
  (practice's saved results aren't compared: they're the PC's runs);
- "stats": stats.headline of every deck file's and product deck's versions; "guide":
  playing_guide of every deck file; "refresh_plan": {deck id: sha256 of the bytes plan_refresh
  would write}; "receipt_refresh_plan": the same after a pinned preview of receiving every pending
  component (golden_p4.receipt_refresh_plan).
Deck history isn't part of it: the database numbers revisions itself. GATE_READERS has an adapter for every deck and accessory read whose
signature or storage phase 4 changes.

Prices everywhere use FIXED_RATE (cards.usd_to_aud is fixed for the whole dump), so the card
prices themselves come from the card index.

An item that raises is recorded as {"__error__": "<Type>: <message>"}, so a reader failing the
same way is part of what's compared. Values are made plain JSON (see _plain): dataclasses become
dicts, tuples lists, sets sorted lists, tuple dict keys "a|b|c", paths repo-relative, and the
temp root's absolute path inside any text becomes <ROOT>. List order is kept; compare() treats
dict keys as unordered.

The tree is read from git blobs, never the working tree (core.autocrlf=true leaves many files
CRLF on disk while every blob is LF): materialize() writes a revision's magic/ files into a
folder, and dump() points the modules' path constants at it (pointed(): a constant a ported
module no longer has is skipped) and installs FileInventory(that folder) as the inventory backend
in one pinned snapshot (or the backend it's given: dump(root, backend=PgInventory(...)) with the
inventory files gone from root is the database half of a contract test). config.json (which profiles
and spaces there are) and decklab/simulation.json are this checkout's.
"""
import contextlib
import dataclasses
import hashlib
import importlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from unittest import mock

from decklab.lib import config

FIXED_RATE = (1.5, "2000-01-01")     # the (rate, ECB date) cards.usd_to_aud gives throughout a dump
FORMATS = ("Constructed", "Commander")
ERROR = "__error__"
META = "_meta"
# The golden commit: its magic/ tree is the golden's data, and today's readers (unchanged from it
# to the phase 3 foundation) made the golden.
GOLDEN_REV = "dc258a6612edea01427aa53e1875588b1d5e9347"
SAMPLE = 40                          # owned names per space the printing picker and wishlists are asked about
# Phase 4 (decks and accessories): its golden is main's code at the phase 3 cutover (GOLDEN_REV_P4,
# whose deck and accessory readers read files) over GOLDEN_REV_P4's deck files, accessories.csv
# and pictures and INVENTORY_REV_P4's inventory files (tag pre-db-inventory: the cutover deleted
# them; they and the deck files are the same at both commits). Made with dump(decks=True).
GOLDEN_REV_P4 = "83d61e6e4b241c8292ef17b63c5831cf6e8ede17"
INVENTORY_REV_P4 = "5a2d86f5386e06d0d5759da9d69e9850dd734abf"
# Who phase 4's per-viewer items are asked for: as a login through the tunnel, a home admin, a home
# member (whose accessories are hers alone) and a person with their own space; and a request on the
# home network naming nobody ("(local)", golden_p4.LOCAL: it sees every accessory).
VIEWERS = ("matt", "user1", "user2", "(local)")


def _lib(name):
    return importlib.import_module(f"decklab.lib.{name}")


# How dump() calls each reader phase 3 changes, as name: fn(root, ...). An area that changes a
# reader's signature (purchases and tokens lose their root argument, for instance) updates its
# entry here in the same change, so the dump keeps running on both today's and the new code.
GATE_READERS = {
    "pool.load_pool": lambda root, space: _lib("pool").load_pool(space),
    "pool.printing_counts": lambda root, space: _lib("pool").printing_counts(space),
    "pool.read_status": lambda root, warnings: _lib("pool").read_status(warnings),
    "purchases.overview": lambda root: _lib("purchases").overview(),
    "purchases.read_records": lambda root: _lib("purchases").read_records(),
    "purchases.read_queue": lambda root: _lib("purchases").read_queue(),
    "purchases.coverage": lambda root: _lib("purchases")._coverage(_lib("purchases").read_records()),
    "tokens.incoming": lambda root: _lib("tokens").incoming(),
    "tokens.read": lambda root, space: _lib("tokens").read(space=space),
    "tokens.check": lambda root, space: _lib("tokens").check(space=space),
    "tokens.holders": lambda root, warnings, space: _lib("tokens")._holders(warnings, space),
    "tokens.row_uses": lambda root, inv, incoming, warnings, space: _lib("tokens").row_uses(inv, incoming, warnings,
                                                                                            space),
    "tokens.gaps": lambda root, inv, incoming, warnings, space: _lib("tokens").gaps(inv, incoming, warnings, space),
    "accessories.scan": lambda root, warnings: _lib("accessories")._scan(warnings),
    "accessories.holders": lambda root, warnings: _lib("accessories").holders(warnings=warnings),
    "collection.special_basics": lambda root, space: _lib("api.collection")._special_basics(space),
    # Phase 4's: the deck files and accessories, read from files today.
    "decks.files": lambda root: _deck_files(root),
    "decks.refresh_plan": lambda root: [(_rel(path, root), new)
                                        for path, _, new in _lib("inventory.refresh").plan_refresh()],
    "accessories.read": lambda root: _lib("accessories").read(),
    "accessories.check": lambda root: _lib("accessories").check(root),
    "accessories.image_url": lambda root, row: _lib("accessories").image_url(row),
    "accessories.status_sha256": lambda root: _lib("accessories").status_sha256(),
    "accessories.kit": lambda root, holder_id, owners: _lib("accessories").kit(holder_id, owners=owners),
    "accessories.view": lambda root: _lib("api.accessories").accessories_view(),
    "guide.playing_guide": lambda root, deck: _lib("api.guide").playing_guide(deck),
    "forge.base_entry": lambda root, deck_id, version: _lib("forge.variants").base_entry(deck_id, version),
    "accessories.image_file": lambda root, name: importlib.import_module("decklab.tests.golden_p4").image_answer(name),
    "inventory.preview": lambda root, op: importlib.import_module("decklab.tests.golden_p4").preview_snapshot(op),
}


def _rel(path, root):
    """path (absolute, under root) as a repo path."""
    return Path(path).resolve().relative_to(root).as_posix()


def _deck_files(root):
    """[(deck id, repo path, DeckFile or the exception reading it raised)] of every deck file, in
    every space, as decks._space_files() lists them."""
    from decklab.lib import decks
    found = []
    for space, path in decks._space_files():
        try:
            deck = decks.read_deck_file(path, space=space)
        except Exception as e:      # a file that can't be read is part of what's compared
            deck = e
        deck_id = deck.deck_id if not isinstance(deck, Exception) else decks.deck_id_of(path)
        found.append((deck_id, _rel(path, root), deck))
    return found


def reader(name, root, *args, **kwargs):
    """GATE_READERS[name] called with root and the rest."""
    return GATE_READERS[name](root, *args, **kwargs)
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


# ------------------------------------------------------------------ the tree

def _git(args, repo, input=None):
    done = subprocess.run(["git", *args], cwd=repo, input=input, capture_output=True, **_SPAWN)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def golden_rev_available(rev=GOLDEN_REV, repo=None):
    """True when this checkout has the commit rev (GOLDEN_REV by default). The golden commits are
    the original private repo's: a clone without that history skips the tests that read them."""
    done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"],
                          cwd=Path(repo or config.REPO), capture_output=True, **_SPAWN)
    return done.returncode == 0


def is_deck_part(rel):
    """True for a repo path phase 4 moves into the database: a deck file (magic/decks/... or a
    person's magic/people/<id>/decks/...), magic/accessories.csv or one of its pictures."""
    if rel == "magic/accessories.csv" or rel.startswith(("magic/decks/", "magic/accessories/images/")):
        return True
    parts = rel.split("/")
    return len(parts) > 4 and parts[:2] == ["magic", "people"] and parts[3] == "decks"


def _blobs(rev, repo):
    """(rev's full commit sha, [(blob id, path)] of every file under magic/ at rev)."""
    sha = _git(["rev-parse", "--verify", f"{rev}^{{commit}}"], repo).decode().strip()
    listing = _git(["ls-tree", "-r", "-z", "--full-tree", sha, "--", "magic"], repo).split(b"\0")
    blobs = []
    for entry in listing:
        if not entry:
            continue
        info, path = entry.split(b"\t", 1)
        mode, kind, blob = info.decode().split()
        if kind == "blob" and mode != "120000":      # symbolic links aren't inventory
            blobs.append((blob, path.decode("utf-8")))
    return sha, blobs


def _write_blobs(blobs, dest, repo):
    """Write each (blob id, path) into dest/path as git keeps it (raw bytes: LF text, pictures as they are)."""
    if not blobs:
        return
    out = _git(["cat-file", "--batch"], repo, input="".join(f"{blob}\n" for blob, _ in blobs).encode())
    pos = 0
    for blob, path in blobs:
        end = out.index(b"\n", pos)
        size = int(out[pos:end].split()[2])
        content = out[end + 1:end + 1 + size]
        pos = end + 1 + size + 1                     # the content, then a newline
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def materialize(rev, dest, repo=None, decks_rev=None):
    """Write every file under magic/ at rev (deck files, products, orders, collections, tokens,
    accessories and their pictures, ...) into dest/magic, as git's blobs hold them (LF text,
    pictures byte for byte), and return the commit's full sha. With decks_rev, the deck files
    (home's and every person's), accessories.csv and its pictures (is_deck_part) come from
    decks_rev's blobs instead, and rev's own are left out: phase 4's golden takes its decks from
    one commit and the inventory files from another (the phase 3 cutover deleted those).
    dest/magic must not exist yet, so nothing stale mixes in."""
    repo = Path(repo or config.REPO)
    dest = Path(dest)
    if (dest / "magic").exists():
        raise ValueError(f"{dest / 'magic'} already exists")
    sha, blobs = _blobs(rev, repo)
    if decks_rev is not None:
        _, deck_blobs = _blobs(decks_rev, repo)
        blobs = [b for b in blobs if not is_deck_part(b[1])] + [b for b in deck_blobs if is_deck_part(b[1])]
    _write_blobs(blobs, dest, repo)
    return sha


@contextlib.contextmanager
def pointed(root):
    """Point every module-level path the readers use at root's magic/ tree (as the test
    Sandbox does), and stub Forge's git provenance. A constant a module no longer has is
    skipped."""
    from decklab.lib import accessories, decks, pool, tokens
    root = Path(root).resolve()
    magic = root / "magic"
    changes = [(config, "REPO", root), (config, "MAGIC", magic),
               (pool, "REPO", root),
               (decks, "REPO", root), (decks, "MAGIC", magic), (decks, "DECKS_DIR", magic / "decks"),
               (accessories, "PATH", magic / "accessories.csv"),
               (accessories, "IMAGES", magic / "accessories" / "images")]
    # The records of saves waiting for their commit live in this checkout's data folder: point
    # them at root's (empty), so a dump never depends on what this PC has pending.
    from decklab.lib.api import accessories as api_accessories
    from decklab.lib.api import commits
    changes += [(commits, "PENDING_FILE", root / "data" / "uncommitted-saves.json"),
                (api_accessories, "ACCESSORIES_PENDING", root / "data" / "accessories-pending.json")]
    try:
        from decklab.lib.forge import lists
    except ImportError:         # a test that stands a fake in for the forge package
        pass
    else:
        changes.append((lists, "_source", lambda deck_id, path=None: None))
    with contextlib.ExitStack() as stack:
        for module, name, value in changes:
            if hasattr(module, name):
                stack.enter_context(mock.patch.object(module, name, value))
        tokens.clear_cache()
        stack.callback(tokens.clear_cache)
        yield root


# ------------------------------------------------------------------ plain JSON

# Dataclass fields the recorded goldens predate and that only index what they already hold:
# pool.Pool.warning_decks (E10-S29), which deck each of its warnings is about, and pool.InUse.printings
# (E7-S28), the printings a holder's list names for the copies its cards already count;
# standin_names, printing_version and planned_colors index recipe/list facts captured by deck projections.
_NOT_RECORDED = frozenset({"warning_decks", "printings", "standin_names", "printing_version", "planned_colors"})

_UNDER_ROOT = re.compile(r"<ROOT>[^'\"\s]*")


def _plain(value, root):
    """value as JSON-able data (see the module docstring)."""
    if isinstance(value, str):      # the root as written, as a repr writes it (an OSError's text) and with /
        text = value.replace(str(root), "<ROOT>").replace(repr(str(root))[1:-1], "<ROOT>")
        text = text.replace(root.as_posix(), "<ROOT>")
        # A path under the root with / on every system, so goldens recorded on Windows hold on Linux.
        return _UNDER_ROOT.sub(lambda m: re.sub(r"\\+", "/", m.group()), text)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        path = Path(value)
        return path.relative_to(root).as_posix() if path.is_relative_to(root) else _plain(path.as_posix(), root)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name), root) for f in dataclasses.fields(value)
                if f.name not in _NOT_RECORDED}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):
        return {k: _plain(v, root) for k, v in value._asdict().items()}
    if isinstance(value, Mapping):
        return {_key(k, root): _plain(v, root) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v, root) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [_plain(v, root) for v in value]
    raise TypeError(f"can't make a {type(value).__name__} plain")


def _key(key, root):
    if isinstance(key, tuple):
        return "|".join("" if k is None else str(_plain(k, root)) for k in key)
    return str(_plain(key, root)) if not isinstance(key, str) else _plain(key, root)


def _capture(root, work):
    """work()'s result made plain, or {ERROR: what it raised}."""
    try:
        return _plain(work(), root)
    except Exception as e:      # a reader failing is part of what's compared
        return {ERROR: _plain(f"{type(e).__name__}: {e}", root)}


# ------------------------------------------------------------------ the dump

def _sample(p):
    """The names the printing picker and the wishlists are asked about for a pool: the first
    SAMPLE owned names (casefold order) and every name on the way, sorted."""
    if p is None:
        return []
    owned = sorted(p.owned, key=lambda n: (n.casefold(), n))[:SAMPLE]
    return sorted(set(owned) | set(p.on_the_way), key=lambda n: (n.casefold(), n))


def dump(root=None, backend=None, decks=False):
    """Every gate item (see the module docstring) computed by this checkout's code over root's
    magic/ tree (the repo's own by default), as a JSON-able dict. backend: the inventory backend
    the readers see (FileInventory(root) by default), in one pinned snapshot. decks: add phase
    4's deck and accessory items (deck_items)."""
    want_decks = decks
    from decklab.lib import accessories, cards, decks, inventory, pool, spaces, tokens
    from decklab.lib.api import assembly as api_assembly
    from decklab.lib.api import card_lookup, deck_page
    from decklab.lib.api import collection as api_collection
    from decklab.lib.api import tokens as api_tokens
    from decklab.lib.api import wishlists as api_wishlists
    from decklab.lib.inventory.files import FileInventory

    root = Path(root or config.REPO).resolve()
    with pointed(root), inventory.use(backend or FileInventory(root)), inventory.pinned(), \
            mock.patch.object(cards, "usd_to_aud", lambda: FIXED_RATE):
        c = lambda work: _capture(root, work)      # noqa: E731
        out = {}
        space_ids = spaces.space_ids()
        out["spaces"] = space_ids

        pools = {}
        out["pools"], out["printing_counts"] = {}, {}
        for space in space_ids:
            try:
                pools[space] = reader("pool.load_pool", root, space)
            except Exception:
                pools[space] = None
            out["pools"][space] = c(lambda: reader("pool.load_pool", root, space))
            out["printing_counts"][space] = c(lambda: reader("pool.printing_counts", root, space))

        status_warnings = []
        out["read_status"] = c(lambda: {"status": reader("pool.read_status", root, status_warnings),
                                        "warnings": status_warnings})
        summaries = decks.list_decks()
        pairings = decks.beginner_box_pairings()
        out["list_decks"] = c(lambda: summaries)
        out["beginner_box_pairings"] = c(lambda: pairings)
        out["load_deck"] = {s["id"]: c(lambda: decks.load_deck(s["id"]))
                            for s in summaries + pairings if s["id"].startswith(("product/", "pairing/"))}

        def every_version(prices):
            found = {}
            for s in summaries + pairings:
                for version in s["versions"] or ["target"]:
                    found[f"{s['id']}@{version}"] = c(lambda: pool.owned_vs_needed(
                        s["id"], version, pool=pools.get(s.get("space", spaces.HOME)), prices=prices))
            return found

        def every_table(prices):
            found = {}
            for space, path in decks._space_files():
                rel = path.relative_to(root).as_posix()
                found[rel] = c(lambda: pool.deck_table(decks.read_deck_file(path, space=space),
                                                       pools.get(space), prices=prices))
            return found

        out["owned_vs_needed"] = every_version(False)
        out["deck_table"] = every_table(False)
        out["owned_vs_needed_priced"] = every_version(True)
        out["deck_table_priced"] = every_table(True)
        out["stale_tables"] = c(pool.stale_tables)
        out["plan_refresh"] = c(lambda: {path: hashlib.sha256(new).hexdigest()
                                         for path, new in reader("decks.refresh_plan", root)})

        out["purchases"] = {
            "overview": c(lambda: reader("purchases.overview", root)),
            "read_records": c(lambda: reader("purchases.read_records", root)),
            "read_queue": c(lambda: reader("purchases.read_queue", root)),
            "coverage": c(lambda: reader("purchases.coverage", root)),
        }

        def forge_field(fmt, part):
            from decklab.lib.forge import field
            return field.field_lists(fmt) if part == "lists" else field.field_notes(fmt)

        out["field"] = {fmt: {part: c(lambda: forge_field(fmt, part)) for part in ("lists", "notes")}
                        for fmt in FORMATS}

        def scan():
            warnings = []
            found, strays = reader("accessories.scan", root, warnings)
            return {"found": found, "strays": strays, "warnings": warnings}

        def holders():
            warnings = []
            return {"holders": reader("accessories.holders", root, warnings), "warnings": warnings}

        out["accessories"] = {"scan": c(scan), "holders": c(holders)}

        def token_holders(space):
            warnings = []
            return {"holders": reader("tokens.holders", root, warnings, space), "warnings": warnings}

        found, problems = [], []
        try:
            found, problems = reader("tokens.incoming", root)
        except Exception:
            pass
        incoming = lambda space: found if space == spaces.HOME else []      # noqa: E731

        def token_uses(space, which):
            warnings = []
            inv = reader("tokens.read", root, space)
            return {which: reader(f"tokens.{which}", root, inv, incoming(space), warnings, space),
                    "warnings": warnings}

        out["tokens"] = {
            "incoming": c(lambda: reader("tokens.incoming", root)),
            "incoming_view": c(lambda: {"incoming": api_tokens._incoming_json(found), "problems": problems}),
            "spaces": {space: {"read": c(lambda: reader("tokens.read", root, space)),
                               "check": c(lambda: reader("tokens.check", root, space)),
                               "holders": c(lambda: token_holders(space)),
                               "row_uses": c(lambda: token_uses(space, "row_uses")),
                               "gaps": c(lambda: token_uses(space, "gaps"))}
                       for space in space_ids},
        }

        def collection_pages(space):
            special, special_incoming = reader("collection.special_basics", root, space)
            p = pools[space] if pools.get(space) is not None else reader("pool.load_pool", root, space)
            pages, page = [], 1
            while True:
                answer = api_collection._collection(p, special, special_incoming, "", "", "", "", None, "all",
                                                    page, 24)
                pages.append(answer)
                if page >= answer["pages"]:
                    return pages
                page += 1

        out["collection"] = {space: {"special_basics": c(lambda: reader("collection.special_basics", root, space)),
                                     "pages": c(lambda: collection_pages(space))}
                             for space in space_ids}

        # The pages that show inventory numbers.
        out["decks_index"] = c(deck_page.decks_index)

        def page(deck_id, version):
            answer = dict(deck_page.deck_view(deck_id, version))
            answer.pop("practice", None)            # saved Forge results and analysis, not inventory
            answer.pop("matchups", None)
            return answer

        out["deck_view"] = {f"{s['id']}@{version}": c(lambda: page(s["id"], version))
                            for s in summaries + pairings for version in s["versions"] or ["target"]}
        home = [s for s in summaries if s.get("space", spaces.HOME) == spaces.HOME]
        out["assembly"] = {"": c(api_assembly.assembly_view),
                           **{s["id"]: c(lambda: api_assembly.assembly_view(s["id"], "target")) for s in home}}
        out["printings"] = {name: c(lambda: card_lookup.printings(name)) for name in _sample(pools.get(spaces.HOME))}

        def wishlist(profile):
            entries = [api_wishlists.validated_entry(name, check_cards=False)
                       for name in _sample(pools.get(profile.get("space") or spaces.HOME))]
            return api_wishlists._view(profile["id"], entries, [])

        from decklab.lib.api.settings import _config_profiles
        out["wishlist_view"] = {profile["id"]: c(lambda: wishlist(profile)) for profile in _config_profiles()}
        if want_decks:
            out.update(deck_items(root, summaries, pairings))
    return out


@contextlib.contextmanager
def as_viewer(profile_id):
    """The block's requests come from profile_id's login through the tunnel (access.using), so
    the pages answer as they do for that person: their accessories, their spaces. "(local)": a
    request on the home network naming nobody."""
    from decklab.lib import access
    with access.using(None if profile_id == "(local)" else {"profile": profile_id, "email": None, "remote": True}):
        yield


def _parse_json(deck, root):
    """A DeckFile's parse (or the exception reading it raised) as plain data: every field but the
    text, with the owned header values, the sha256 of the text, and its repo path."""
    if isinstance(deck, Exception):
        raise deck
    parsed = _plain(deck, root)
    parsed.pop("text", None)
    parsed["text_sha256"] = hashlib.sha256(deck.text.encode("utf-8")).hexdigest()
    parsed["has_decklist"] = deck.has_decklist
    parsed["owned_fields"] = {"deck_id": deck.deck_id, "format": deck.format, "player": deck.player,
                              "status": deck.status, "built_version": deck.built_version, "sleeves": deck.sleeves,
                              "deck_box": deck.deck_box, "target_bracket": deck.target_bracket}
    return parsed


def _lines_only(lists):
    """edit_view's lists as the editor sends them back: qty, name, set, number and finish of each line."""
    keep = ("qty", "name", "set", "number", "finish")
    return {version: None if sections is None else
            {name: [{k: line.get(k) for k in keep} for line in lines] for name, lines in sections.items()}
            for version, sections in lists.items()}


def deck_items(root, summaries, pairings):
    """Phase 4's items (see the module docstring), run inside dump()'s pinned snapshot and
    pointed tree. summaries and pairings: list_decks()'s and beginner_box_pairings()'s."""
    from decklab.lib import accessories, decks, spaces
    from decklab.lib.api import assembly as api_assembly
    from decklab.lib.api import deck_page, drafts, editor, guard
    c = lambda work: _capture(root, work)      # noqa: E731
    out = {}
    try:
        files = reader("decks.files", root)
    except Exception as e:
        files = []
        out["deck_files"] = {ERROR: _plain(f"{type(e).__name__}: {e}", root)}
    if files:
        out["deck_files"] = {deck_id: {"path": rel, "parse": c(lambda: _parse_json(deck, root))}
                             for deck_id, rel, deck in files}
    versions = [(s["id"], version) for s in summaries for version in s["versions"] or ["target"]]
    home = [s["id"] for s in summaries if s.get("space", spaces.HOME) == spaces.HOME]

    def page(deck_id, version):
        answer = dict(deck_page.deck_view(deck_id, version))
        answer.pop("practice", None)            # saved Forge results and analysis, not decks
        answer.pop("matchups", None)
        return answer

    def check_draft(viewer, deck_id, edit):
        if not isinstance(edit, dict) or ERROR in edit or not edit.get("editable"):
            return None                         # nothing to send back
        body = {"profile": None if viewer == "(local)" else viewer, "id": deck_id, "sha256": edit["sha256"],
                "lists": _lines_only(edit["lists"])}
        return editor.check_draft(json.dumps(body))

    out["by_viewer"] = {}
    for viewer in VIEWERS:
        with as_viewer(viewer):
            mine = {"decks_index": c(deck_page.decks_index),
                    "deck_view": {f"{deck_id}@{version}": c(lambda: page(deck_id, version))
                                  for deck_id, version in versions},
                    "edit_view": {s["id"]: c(lambda: editor.edit_view(s["id"])) for s in summaries}}
            mine["check_draft"] = {deck_id: c(lambda: check_draft(viewer, deck_id, mine["edit_view"][deck_id]))
                                   for deck_id, _, _ in files}
            mine["built_sleeves"] = c(lambda: drafts.built_sleeves(owners=guard.accessory_owners()))
            mine["assembly"] = {deck_id: c(lambda: api_assembly.assembly_view(deck_id, "target")) for deck_id in home}
            out["by_viewer"][viewer] = mine

    def read():
        inv = reader("accessories.read", root)
        return {"read": inv, "image_url": {rid: reader("accessories.image_url", root, row)
                                           for rid, row in inv.rows_by_id.items()}}

    holder_ids = [s["id"] for s in summaries]
    holder_ids += sorted({"product/" + s["id"].split("/")[1] for s in summaries if s["id"].startswith("product/")})
    pictures = set()
    try:
        pictures = {row["image"] for row in reader("accessories.read", root).rows_by_id.values() if row.get("image")}
    except Exception:
        pass
    try:            # the snapshot's pictures too: a database dump has no files to list
        from decklab.lib import inventory
        pictures |= set(getattr(inventory.current(), "accessory_images", None) or ())
    except Exception:
        pass
    pictures = sorted(pictures | {p.name for p in (root / "magic" / "accessories" / "images").glob("*")})
    seen = {}
    for viewer in VIEWERS:
        with as_viewer(viewer):
            owners = guard.accessory_owners()

            def rows_seen():
                inv = reader("accessories.read", root)
                return sorted(rid for rid, row in inv.rows_by_id.items() if accessories.visible(row["owner"], owners))
            seen[viewer] = {"owners": c(lambda: owners), "rows": c(rows_seen),
                            "view": c(lambda: reader("accessories.view", root)),
                            "kit": {holder: c(lambda: reader("accessories.kit", root, holder, owners))
                                    for holder in holder_ids},
                            "images": {name: c(lambda: reader("accessories.image_file", root, name))
                                       for name in pictures}}
    out["accessories_p4"] = {"read": c(read), "status_sha256": c(lambda: reader("accessories.status_sha256", root)),
                             "check": c(lambda: reader("accessories.check", root)), "by_viewer": seen}

    every = versions + [(s["id"], version) for s in pairings for version in s["versions"] or ["target"]]
    out["forge_entries"] = {f"{deck_id}@{version}": c(lambda: reader("forge.base_entry", root, deck_id, version))
                            for deck_id, version in every}

    def practice(deck_id, version):
        from decklab.lib.api import library, practice as api_practice
        from decklab.lib.goldfish import runs
        summary, sections = library._deck_sections(deck_id, version)
        kind = decks.engine_kind(summary)
        answer = {"deck_key": runs._deck_key(sections), "kind": kind}
        try:
            answer["cache_key"] = runs.cache_key(sections, kind, **api_practice.GOLDFISH_SETTINGS)
        except ValueError as e:     # too few cards to deal from
            answer["cache_key"] = {ERROR: f"ValueError: {e}"}
        return answer

    out["practice"] = {f"{deck_id}@{version}": c(lambda: practice(deck_id, version)) for deck_id, version in versions}

    def stats(deck_id, version):
        from decklab.lib import stats as deck_stats
        summary = decks.find_summary(deck_id)
        return deck_stats.headline(deck_stats.deck_stats(decks.load_deck(summary["id"], version),
                                                         decks.engine_kind(summary)))

    out["stats"] = {f"{deck_id}@{version}": c(lambda: stats(deck_id, version)) for deck_id, version in versions}
    out["guide"] = {deck_id: c(lambda: reader("guide.playing_guide", root, deck)) for deck_id, _, deck in files
                    if not isinstance(deck, Exception)}

    def refresh_plan():
        ids = {rel: deck_id for deck_id, rel, _ in files}
        return {ids.get(rel, rel): hashlib.sha256(new).hexdigest() for rel, new in reader("decks.refresh_plan", root)}

    out["refresh_plan"] = c(refresh_plan)
    out["receipt_refresh_plan"] = c(lambda: importlib.import_module("decklab.tests.golden_p4").receipt_refresh_plan(root))
    return out


# ------------------------------------------------------------------ comparing

def _short(value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= 300 else text[:300] + "..."


def first_difference(a, b, path="$"):
    """(path, a part, b part) of the first place a and b differ, or None when they're equal.
    Lists compare in order; dict keys are unordered (a's order first, then b's extras)."""
    if type(a) is not type(b):
        return path, a, b
    if isinstance(a, dict):
        for k in a:
            if k == META and path == "$":
                continue
            if k not in b:
                return f"{path}[{k!r}]", a[k], "(missing)"
            found = first_difference(a[k], b[k], f"{path}[{k!r}]")
            if found:
                return found
        for k in b:
            if k not in a and not (k == META and path == "$"):
                return f"{path}[{k!r}]", "(missing)", b[k]
        return None
    if isinstance(a, list):
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        if len(a) != len(b):
            n = min(len(a), len(b))
            return f"{path}[{n}]", a[n] if len(a) > n else "(missing)", b[n] if len(b) > n else "(missing)"
        return None
    return None if a == b else (path, a, b)


def compare(a, b, say=print):
    """Print the first JSON path where dumps a and b differ; return it (None when they match).
    A difference in what the dumps depend on (META) is noted first, since it can explain one;
    dumps made with different card indexes (META's card_index) don't compare at all: that's
    the first difference."""
    meta_a, meta_b = (a.get(META) or {}) if isinstance(a, dict) else {}, (b.get(META) or {}) if isinstance(b, dict) else {}
    for key in ("price_date", "fixed_rate", "config"):
        if meta_a and meta_b and meta_a.get(key) != meta_b.get(key):
            say(f"note: the dumps were made with a different {key} ({meta_a.get(key)!r} vs {meta_b.get(key)!r})")
    if meta_a and meta_b and meta_a.get("card_index") != meta_b.get("card_index"):
        say(f"The dumps were made with different card indexes ({meta_a.get('card_index')!r} vs "
            f"{meta_b.get('card_index')!r}); make both with the same one (--data).")
        return f"$[{META!r}]['card_index']"
    found = first_difference(a, b)
    if found is None:
        say("The dumps match.")
        return None
    path, x, y = found
    say(f"First difference at {path}:\n  a: {_short(x)}\n  b: {_short(y)}")
    return path
