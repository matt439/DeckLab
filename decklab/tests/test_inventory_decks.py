"""Tests for phase 4's foundation (decklab/PLAN.md phase 4; the phase 4 design's R1-R4): the deck
files, accessories.csv and its pictures as parts of the inventory's snapshot (paths, model,
files.py's reading, rendering and writing, changes.prepare), the decks package reading them from
the snapshot, the deck operations (inventory/ops_decks.py), and the deck-table refresh inside an
operation (register(kind, refresh=True), refresh.in_op).

The round trip reads the deck parts of the phase 4 golden commit (gate.GOLDEN_REV_P4) from git's
blobs; it skips in a clone without that commit.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inventory_decks
"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import config, decks, inventory
from decklab.lib.inventory import Op, Summary, changes, files, ops_decks, paths, refresh, register
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import Deck, ImageMeta
from decklab.lib.state import Actor, Conflict, Invalid
from decklab.tests import db_support, deck_files, household_config
from decklab.tests import test_pool as support

setUpModule = support.setUpModule          # the fixture card index, not decklab/data's
tearDownModule = support.tearDownModule

TESTER = Actor("test", "Tester", None, "test")
DECK = support.deck_md("Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n")
ACCESSORIES = ("id,kind,owner,brand,name,colour,quantity,capacity,image,crop,link,image_source,notes\n"
               "b-box,deck_box,shared,UG,Boulder,black,2,100,,,,,\n"
               "a-sleeves,sleeves,matt,DS,Matte,red,100,,a-sleeves.jpg,,,,\n")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _has_commit(rev):
    done = subprocess.run(["git", "cat-file", "-e", f"{rev}^{{commit}}"], cwd=config.REPO, capture_output=True)
    return done.returncode == 0


class RoundTripTests(unittest.TestCase):
    """Every deck file, accessories.csv and picture at the phase 4 golden commit loads and renders
    back byte for byte, from git's blobs and from a tree of them on disk."""

    @classmethod
    def setUpClass(cls):
        from decklab.tests import golden_dump as gate
        if not _has_commit(gate.GOLDEN_REV_P4):
            raise unittest.SkipTest(f"the repo has no commit {gate.GOLDEN_REV_P4[:7]}")
        _, found = files.git_files(gate.GOLDEN_REV_P4, decks=True)
        cls.blobs = {rel: data for rel, data in found.items() if paths.is_deck_part(rel)}

    def test_the_blobs_render_back(self):
        inv = files.build(self.blobs)
        self.assertEqual(len(inv.decks), 19)
        self.assertEqual(len(inv.accessory_images), 23)
        rendered = files.render(inv, decks=True)
        for rel, data in self.blobs.items():
            with self.subTest(rel):
                what = paths.classify(rel)[0]
                if what == "image":
                    meta = inv.accessory_images[paths.classify(rel)[1]]
                    self.assertEqual((meta.size, meta.sha256), (len(data), _sha(data)))
                    self.assertNotIn(rel, rendered)         # no bytes in a loaded snapshot
                else:
                    self.assertEqual(rendered[rel], data)
                if what == "deck":
                    deck = inv.decks[Deck(*paths.classify(rel)[1]).id]
                    self.assertEqual((deck.path, deck.sha256), (rel, _sha(data)))
        self.assertEqual(inv.accessories.problems, ())
        self.assertIsNone(inv.accessories.strict_error)
        self.assertEqual(files.render(inv), {})             # the inventory's files: none of these
        self.assertEqual(changes.reread(inv, inv), inv)

    def test_a_tree_on_disk_renders_back_and_the_revisions_part(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        for rel, data in self.blobs.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        backend = FileInventory(root)
        inv = backend.load()
        self.assertEqual(inv, files.build(self.blobs).replace(root=str(root)))
        for name, meta in inv.accessory_images.items():
            self.assertEqual(_sha(backend.image(name)), meta.sha256)
        self.assertEqual(inv.decks_revision, files.decks_revision_of(self.blobs))
        self.assertEqual(inv.revision, files.revision_of({}))     # the deck parts aren't inventory


class _Tree(unittest.TestCase):
    """A temp magic/ tree with two decks (one CRLF), accessories.csv and a picture, installed as
    the inventory backend (FileInventory, plain writes)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        household_config.use(self)
        self.magic = self.root / "magic"
        self.put("decks/casual/test.md", DECK.encode())
        self.put("decks/commander/crlf.md", DECK.replace("\n", "\r\n").replace("# Test", "# Crlf").encode())
        self.put("accessories.csv", ACCESSORIES.encode())
        self.picture = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        self.put("accessories/images/a-sleeves.jpg", self.picture)
        patcher = mock.patch.object(decks, "DECKS_DIR", self.magic / "decks")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = FileInventory(self.root)
        self.addCleanup(inventory.use(self.backend))

    def put(self, rel, data):
        (self.magic / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.magic / rel).write_bytes(data)

    def apply(self, op_kind, **params):
        return inventory.apply(Op(op_kind, params), TESTER, f"test {op_kind}")


class SnapshotTests(_Tree):

    def test_the_parts_as_read(self):
        inv = inventory.current()
        self.assertEqual(sorted(inv.decks), ["casual/test", "commander/crlf"])
        crlf = inv.deck("commander/crlf")
        self.assertIn("\r\n", crlf.text)                        # nothing translated
        self.assertEqual(crlf.sha256, _sha((self.magic / "decks/commander/crlf.md").read_bytes()))
        self.assertEqual([d.id for d in inv.space_decks()], ["casual/test", "commander/crlf"])
        self.assertEqual([r.text("id") for r in inv.accessories.rows], ["b-box", "a-sleeves"])   # as written
        self.assertEqual(inv.image_meta("a-sleeves.jpg"), ImageMeta("a-sleeves.jpg", len(self.picture),
                                                                    _sha(self.picture)))

    def test_an_unreadable_deck_has_an_error(self):
        self.put("decks/casual/bad.md", b"# Bad\n\xff\n")
        deck = inventory.current().deck("casual/bad")
        self.assertIsNone(deck.text)
        self.assertTrue(deck.error.startswith("not UTF-8"))
        with self.assertRaises(decks.DeckFileError):
            decks.read_deck_file(self.magic / "decks/casual/bad.md")
        listed = {s["id"]: s for s in decks.list_decks()}
        self.assertIn("error", listed["casual/bad"])

    def test_the_decks_come_from_the_pinned_snapshot(self):
        path = self.magic / "decks/casual/test.md"
        with inventory.pinned():
            before = decks.read_deck_file(path)
            path.write_bytes(DECK.replace("# Test", "# Changed").encode())
            self.assertEqual(decks.read_deck_file(path).title, before.title)     # the snapshot's
            self.assertEqual(decks.find_summary("casual/test")["title"], "Test")
            (self.magic / "decks/casual/new.md").write_bytes(DECK.encode())
            with self.assertRaises(decks.DeckNotFound):
                decks.find_deck_file("casual", "new")
            with self.assertRaises(FileNotFoundError):
                decks.read_deck_file(self.magic / "decks/casual/new.md")
            deck_files.write_deck_file(path, DECK.replace("# Test", "# Written").encode(), _sha(path.read_bytes()))
            self.assertEqual(decks.read_deck_file(path).title, "Written")       # a write drops the pin
            self.assertEqual(decks.find_deck_file("casual", "new"), self.magic / "decks/casual/new.md")
        outside = self.root / "draft.md"
        outside.write_bytes(DECK.encode())
        self.assertEqual(decks.read_deck_file(outside, kind="casual").title, "Test")   # a file, not a deck

    def test_the_inventory_revision_ignores_the_deck_parts(self):
        inv = inventory.current()
        self.put("decks/casual/test.md", DECK.replace("# Test", "# Other").encode())
        self.put("accessories/images/a-sleeves.jpg", self.picture + b"x")
        again = inventory.current()
        self.assertEqual(again.revision, inv.revision)
        self.assertNotEqual(again.decks_revision, inv.decks_revision)


class DeckOpTests(_Tree):

    def sha(self, deck_id):
        return inventory.current().deck(deck_id).sha256

    def test_save_keeps_the_text_byte_for_byte(self):
        text = DECK.replace("\n", "\r\n").replace("# Crlf", "# Crlf").replace("2 Llanowar", "3 Llanowar")
        text = text.replace("# Test", "# Crlf")
        after, summary = self.apply("deck.save", deck_id="commander/crlf", text=text,
                                    base_sha256=self.sha("commander/crlf"))
        self.assertEqual((self.magic / "decks/commander/crlf.md").read_bytes(), text.encode())
        self.assertEqual(after.deck("commander/crlf").text, text)
        self.assertEqual(summary.extra["deck"], "commander/crlf")
        with self.assertRaises(ops_decks.DeckRefused) as refused:
            self.apply("deck.save", deck_id="commander/crlf", text=DECK, base_sha256="0" * 64)
        self.assertEqual((refused.exception.code, refused.exception.reason), (409, "changed"))
        with self.assertRaises(Invalid):
            self.apply("deck.save", deck_id="casual/test", text="no title\n", base_sha256=self.sha("casual/test"))
        before = inventory.current()
        after, summary = self.apply("deck.save", deck_id="casual/test", text=DECK, base_sha256=self.sha("casual/test"))
        self.assertEqual((summary.text, after.decks_revision), ("Nothing to change", before.decks_revision))

    def test_a_deck_save_moves_only_the_decks_revision(self):
        before = inventory.current()
        after, _ = self.apply("deck.save", deck_id="casual/test", text=DECK.replace("# Test", "# Renamed"),
                              base_sha256=self.sha("casual/test"))
        self.assertEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)

    def test_create_and_its_refusals(self):
        after, _ = self.apply("deck.create", space="home", kind="casual", slug="fresh", text=DECK)
        self.assertEqual((self.magic / "decks/casual/fresh.md").read_bytes(), DECK.encode())
        self.assertEqual(after.deck("casual/fresh").text, DECK)
        self.put("decks/casual/Odd.md", DECK.encode())                 # a hand-named file
        for slug, kind, words in (("test", "commander", "already exists"), ("crlf", "casual", "already exists"),
                                  ("odd", "commander", "already exists"),
                                  ("Bad_Slug", "casual", "bad deck slug"), ("x", "draft", "kind must be")):
            with self.subTest(slug), self.assertRaisesRegex((Invalid, Conflict), words):
                self.apply("deck.create", space="home", kind=kind, slug=slug, text=DECK)
        with self.assertRaises(ops_decks.DeckRefused):
            self.apply("deck.create", space="nobody", kind="casual", slug="x", text=DECK)

    def test_update_tables_is_all_or_nothing(self):
        items = [{"id": "casual/test", "text": DECK + "\nMore.\n", "base_sha256": self.sha("casual/test")},
                 {"id": "commander/crlf", "text": "# Crlf\r\n\r\n## Decklist\r\n\r\n```\r\n1 Opt\r\n```\r\n",
                  "base_sha256": "0" * 64}]
        with self.assertRaises(ops_decks.DeckRefused) as refused:
            self.apply("deck.update_tables", items=items)
        self.assertEqual(refused.exception.ids, ["commander/crlf"])
        self.assertEqual((self.magic / "decks/casual/test.md").read_bytes(), DECK.encode())
        items[1]["base_sha256"] = self.sha("commander/crlf")
        after, summary = self.apply("deck.update_tables", items=items)
        self.assertEqual(summary.counts, {"decks": 2})
        self.assertEqual(after.deck("casual/test").text, DECK + "\nMore.\n")

    def test_delete_refuses_a_built_deck_with_a_kit(self):
        built = support.deck_md("Kit", "built", "Deck\n1 Opt\n").replace(
            "- **Status:** built\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n")
        self.put("decks/casual/kit.md", built.encode())
        with self.assertRaises(ops_decks.DeckRefused) as refused:
            self.apply("deck.delete", deck_id="casual/kit", base_sha256=self.sha("casual/kit"))
        self.assertEqual(refused.exception.reason, "kit")
        after, _ = self.apply("deck.delete", deck_id="casual/test", base_sha256=self.sha("casual/test"))
        self.assertIsNone(after.deck("casual/test"))
        self.assertFalse((self.magic / "decks/casual/test.md").exists())

    def test_precon_add_is_one_change(self):
        row = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
               "quantity": "2"}
        collection = {"space": "home", "sources": [["the precon", [row]]]}
        after, summary = self.apply("precon.add", space="home", kind="casual", slug="precon", text=DECK,
                                    collection=collection)
        self.assertEqual([r.text("name") for r in after.collection().rows], ["Llanowar Elves"])
        self.assertEqual(after.deck("casual/precon").text, DECK)
        self.assertTrue((self.magic / "collection.csv").exists())

    def test_a_sha256_is_required_and_a_deck_named_once(self):
        with self.assertRaisesRegex(Invalid, "must be given"):
            self.apply("deck.save", deck_id="casual/test", text=DECK + "\n", base_sha256=None)
        with self.assertRaisesRegex(Invalid, "must be given"):
            self.apply("deck.delete", deck_id="casual/test", base_sha256=None)
        item = {"id": "casual/test", "text": DECK + "\n", "base_sha256": self.sha("casual/test")}
        with self.assertRaisesRegex(Invalid, "more than once"):
            self.apply("deck.update_tables", items=[item, dict(item)])

    def test_only_kit_set_changes_the_sleeves_and_deck_box(self):
        built = support.deck_md("Kit", "built", "Deck\n1 Opt\n").replace(
            "- **Status:** built\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n")
        self.put("decks/casual/kit.md", built.encode())
        for text in (built.replace("a-sleeves", "other"),                          # another value
                     built.replace("- **Sleeves:** a-sleeves\n", ""),               # cleared
                     built.replace("- **Status:** built", "- **Status:** building"),  # taken apart
                     built.replace("- **Status:** built\n", "- **Status:** built\n- **Deck box:** b-box\n")):
            with self.subTest(text=text[:120]), self.assertRaises(ops_decks.DeckRefused) as refused:
                self.apply("deck.save", deck_id="casual/kit", text=text, base_sha256=self.sha("casual/kit"))
            self.assertEqual((refused.exception.code, refused.exception.reason), (409, "kit"))
        with self.assertRaises(ops_decks.DeckRefused) as refused:
            self.apply("deck.update_tables", items=[{"id": "casual/kit", "text": built.replace("a-sleeves", "x"),
                                                     "base_sha256": self.sha("casual/kit")}])
        self.assertEqual(refused.exception.reason, "kit")
        after, _ = self.apply("deck.save", deck_id="casual/kit", text=built + "\nProse.\n",
                              base_sha256=self.sha("casual/kit"))
        self.assertTrue(after.deck("casual/kit").text.endswith("Prose.\n"))      # the rest saves as ever

    def test_a_person_deck_gets_no_home_only_fields(self):
        person = DECK.replace("- **Played by:** either\n", "")
        self.assertNotIn("Played by", person)
        self.put("people/user2/decks/casual/mine.md", person.encode())
        sha = self.sha("user2/casual/mine")
        for line in ("- **Played by:** user\n", "- **Sleeves:** red\n", "- **Deck box:** box\n"):
            with self.subTest(line), self.assertRaisesRegex(Invalid, "own space|home decks"):
                self.apply("deck.save", deck_id="user2/casual/mine",
                           text=person.replace("- **Status:**", line + "- **Status:**"), base_sha256=sha)
        with self.assertRaisesRegex(Invalid, "Played by"):
            self.apply("deck.create", space="user2", kind="casual", slug="new", text=DECK)
        held = person.replace("- **Status:**", "- **Played by:** user\n- **Status:**")
        self.put("people/user2/decks/casual/held.md", held.encode())            # already in the file: it may stay
        after, _ = self.apply("deck.save", deck_id="user2/casual/held", text=held + "\nMore.\n",
                              base_sha256=self.sha("user2/casual/held"))
        self.assertTrue(after.deck("user2/casual/held").text.endswith("More.\n"))

    def test_create_checks_a_new_deck_kit_like_a_choice(self):
        built = support.deck_md("Kit", "built", "Deck\n1 Opt\n").replace("- **Played by:** either", "- **Played by:** user")
        mine = built.replace("- **Status:** built\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n"
                                                       "- **Deck box:** b-box\n")
        cases = ((mine, frozenset({"user1", "shared"}), 403), (mine, frozenset(), 403),
                 (mine.replace("a-sleeves", "b-box"), frozenset({"matt", "shared"}), None),   # shared: anyone's deck
                 (built.replace("Played by:** user", "Played by:** wife").replace(
                     "- **Status:** built\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n"),
                  frozenset({"user1", "shared"}), 400),                                  # Matt's, on User1's deck
                 (built.replace("Played by:** user", "Played by:** wife").replace(
                     "- **Status:** built\n", "- **Status:** built\n- **Sleeves:** a-sleeves\n"), None, 400))
        for n, (text, owners, code) in enumerate(cases):
            with self.subTest(n=n):
                if code is None:
                    self.apply("deck.create", space="home", kind="casual", slug=f"ok-{n}", text=text, owners=owners)
                    continue
                with self.assertRaises(ops_decks.DeckRefused) as refused:
                    self.apply("deck.create", space="home", kind="casual", slug=f"no-{n}", text=text, owners=owners)
                self.assertEqual((refused.exception.code, refused.exception.reason), (code, "kit"))
        after, _ = self.apply("deck.create", space="home", kind="casual", slug="mine", text=mine,
                              owners=frozenset({"matt", "shared"}))
        self.assertEqual(after.deck("casual/mine").text, mine)
        free = built.replace("- **Status:** built\n", "- **Status:** built\n- **Sleeves:** red\n")
        self.apply("deck.create", space="home", kind="casual", slug="free", text=free, owners=None)  # free text

    def test_every_kind_is_registered(self):
        # kit.set, accessory.* and image.* are ops_accessories.py's (test_inventory_accessories.py).
        for kind in ops_decks.KINDS:
            self.assertIn(kind, inventory.kinds())


class AccessoryAndImageWriteTests(_Tree):
    """The write helpers through test operations (the accessories area registers the real ones)."""

    def setUp(self):
        super().setUp()

        def put(inv, content):
            rows = [r.as_dict() for r in inv.accessories.rows] + [
                {"id": "c-mat", "kind": "playmat", "owner": "user1", "name": "Mat", "quantity": "1"}]
            return inv.with_accessories(rows).with_image("c-mat.png", content), Summary("put")

        def drop(inv):
            return inv.without_image("a-sleeves.jpg"), Summary("drop")

        for kind, fn in (("test.put", put), ("test.drop", drop)):
            register(kind)(fn)
            self.addCleanup(inventory.unregister, kind)

    def test_rows_get_the_standard_columns_and_order_and_pictures_their_bytes(self):
        content = b"raw\r\nbytes\r\n"
        before = inventory.current()
        preview, _ = inventory.preview(Op("test.put", {"content": content}))
        self.assertTrue(preview.decks_revision.endswith("~preview"))
        self.assertFalse((self.magic / "accessories/images/c-mat.png").exists())
        after, _ = self.apply("test.put", content=content)
        self.assertEqual((self.magic / "accessories/images/c-mat.png").read_bytes(), content)   # never CRLF'd
        self.assertEqual(after.image_meta("c-mat.png"), ImageMeta.of("c-mat.png", content))
        written = (self.magic / "accessories.csv").read_text(encoding="utf-8")
        self.assertEqual([line.split(",")[0] for line in written.splitlines()], ["id", "a-sleeves", "b-box", "c-mat"])
        self.assertEqual(after.revision, before.revision)
        self.apply("test.drop")
        self.assertFalse((self.magic / "accessories/images/a-sleeves.jpg").exists())

    def test_a_changed_picture_needs_its_bytes(self):
        def bad(inv):
            images = dict(inv.accessory_images)
            images["x.jpg"] = ImageMeta("x.jpg", 1, "0" * 64)
            return inv.replace(accessory_images=images), Summary("bad")
        register("test.bad")(bad)
        self.addCleanup(inventory.unregister, "test.bad")
        with self.assertRaisesRegex(ValueError, "needs its bytes"):
            self.apply("test.bad")


class BackendReadTests(_Tree):
    """The decks part's other reads and the plain writes on the files backend."""

    def test_image_history_and_saves(self):
        sha = _sha(self.picture)
        self.assertEqual(inventory.image("a-sleeves.jpg"), self.picture)
        self.assertEqual(inventory.image("a-sleeves.jpg", sha), self.picture)
        self.assertIsNone(inventory.image("a-sleeves.jpg", "0" * 64))     # another picture than the page read
        self.assertIsNone(inventory.image("none.jpg"))
        self.assertIsNone(inventory.image("../accessories.csv"))
        self.assertEqual(inventory.deck_revisions("casual/test"), [])
        self.assertIsNone(inventory.deck_revision("casual/test", 1))
        self.assertIsNone(inventory.last_revision("casual/test"))
        self.assertTrue(self.backend.saves_decks())

    def test_removing_every_accessory_leaves_no_file(self):
        def none(inv):
            return inv.with_accessories([]), Summary("none")
        register("test.none")(none)
        self.addCleanup(inventory.unregister, "test.none")
        after, _ = self.apply("test.none")
        self.assertFalse(after.accessories.exists)
        self.assertFalse((self.magic / "accessories.csv").exists())

    def test_a_write_of_several_files_writes_them_all(self):
        items = [{"id": "casual/test", "text": DECK + "\nMore.\n", "base_sha256": self.sha256("casual/test")},
                 {"id": "commander/crlf", "text": "# Crlf\n\n## Decklist\n\n```\n1 Opt\n```\n",
                  "base_sha256": self.sha256("commander/crlf")}]
        self.apply("deck.update_tables", items=items)
        self.assertEqual((self.magic / "decks/casual/test.md").read_bytes(), (DECK + "\nMore.\n").encode())
        self.assertIn(b"# Crlf", (self.magic / "decks/commander/crlf.md").read_bytes())
        self.assertFalse((self.root / "decklab/data/receipts").exists())       # no journal, no lock

    def sha256(self, deck_id):
        return inventory.current().deck(deck_id).sha256


class FollowingFolderTests(unittest.TestCase):
    """FileInventory(root, decks_dir=...) keeps the deck files in another folder, and writes there."""

    def test_reads_and_writes_the_other_folder(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "elsewhere/casual").mkdir(parents=True)
        (root / "elsewhere/casual/x.md").write_bytes(DECK.encode())
        (root / "people/user2/decks/commander").mkdir(parents=True)
        (root / "people/user2/decks/commander/y.md").write_bytes(DECK.encode())
        backend = FileInventory(root, decks_dir=root / "elsewhere")
        inv = backend.load()
        self.assertEqual(sorted(inv.decks), ["casual/x", "user2/commander/y"])
        with inventory.use(backend):
            inventory.apply(Op("deck.save", {"deck_id": "casual/x", "text": DECK + "\n",
                                             "base_sha256": inv.deck("casual/x").sha256}), TESTER, "save")
        self.assertEqual((root / "elsewhere/casual/x.md").read_bytes(), (DECK + "\n").encode())

    def test_accessories_and_pictures_can_follow_another_folder(self):
        from decklab.lib import accessories
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "kit/images").mkdir(parents=True)
        (root / "kit/accessories.csv").write_bytes(ACCESSORIES.encode())
        (root / "kit/images/a-sleeves.jpg").write_bytes(b"picture")
        with mock.patch.object(accessories, "PATH", root / "kit/accessories.csv"), \
                mock.patch.object(accessories, "IMAGES", root / "kit/images"):
            from decklab.tests import pre_db
            backend = pre_db.following(root, accessories=True)
            inv = backend.load()
            self.assertEqual([r.text("id") for r in inv.accessories.rows], ["b-box", "a-sleeves"])
            self.assertEqual(backend.image("a-sleeves.jpg"), b"picture")

            def put(inv):
                return inv.with_image("c.png", b"new"), Summary("put")
            register("test.put_elsewhere")(put)
            self.addCleanup(inventory.unregister, "test.put_elsewhere")
            with inventory.use(backend):
                inventory.apply(Op("test.put_elsewhere"), TESTER, "put")
        self.assertEqual((root / "kit/images/c.png").read_bytes(), b"new")
        self.assertFalse((root / "magic").exists())


class PgDeckPartsTests(db_support.DbTestCase):
    """While the database holds no decks, the database backend's decks part is empty (never read
    from files), and it refuses an operation that would change it (R10)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=[{"id": "matt", "name": "Matt", "role": "admin", "space": "home",
                                    "plays_as": "user", "emails": []}], dbname=cls.dbname)

    def test_the_part_is_empty_and_saves_are_paused(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import Unavailable
        from decklab.lib.state import pg as state_pg
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "magic/decks/casual").mkdir(parents=True)
        (root / "magic/decks/casual/test.md").write_bytes(DECK.encode())
        (root / "magic/products").mkdir()
        (root / "magic/products/status.csv").write_bytes(b"file,status,intact,sleeves,deck_box,notes,token_cards\n")
        (root / "magic/watchlist.csv").write_bytes((",".join(files.WatchRow.COLUMNS) + "\n").encode())
        inv = FileInventory(root).load()
        pg.write_model(inv, TESTER, "Import", dbname=self.dbname)
        backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        loaded = backend.load()
        self.assertEqual(dict(loaded.decks), {})                # the deck file under root isn't read
        self.assertIs(backend.load(), loaded)                   # neither part changed
        self.assertEqual(loaded.decks_revision, files.build({}).decks_revision)
        with inventory.use(backend), self.assertRaisesRegex(Unavailable, "the database holds no decks"):
            inventory.apply(Op("deck.create", {"space": "home", "kind": "casual", "slug": "test", "text": DECK}),
                            TESTER, "create")


class RefreshInOpFailureTests(_Tree):
    """The in-op refresh never stops the change it follows (R3, the foundation review's M1, M2)."""

    def setUp(self):
        super().setUp()

        def note(inv):
            deck = inv.deck("casual/test")
            return inv.with_deck(deck.replace(text=deck.text + "\nNoted.\n")), Summary("note")
        register("test.note", refresh=True)(note)
        self.addCleanup(inventory.unregister, "test.note")

    def test_any_error_from_the_plan_is_reported(self):
        for error in (KeyError("x"), TypeError("y"), AttributeError("z")):
            with self.subTest(error=error), mock.patch.object(refresh, "plan_texts", side_effect=error):
                after, summary = inventory.apply(Op("test.note"), TESTER, "note")
                self.assertTrue(summary.extra["tables"]["error"])
                self.assertTrue(after.deck("casual/test").text.endswith("Noted.\n"))

    def test_a_backend_that_cant_save_decks_leaves_them_alone(self):
        with mock.patch.object(self.backend, "saves_decks", return_value=False), \
                mock.patch.object(refresh, "plan_texts") as plan:
            _, summary = inventory.preview(Op("test.note"))
        plan.assert_not_called()
        self.assertEqual(summary.extra["tables"]["error"], inventory.DECK_SAVES_PAUSED)

    def test_a_planned_text_changing_the_kit_is_skipped(self):
        deck = inventory.current().deck("casual/test")
        kitted = deck.text.replace("- **Status:**", "- **Sleeves:** a-sleeves\n- **Status:**")
        with mock.patch.object(refresh, "plan_texts", return_value=[("casual/test", "Test", deck.text, kitted)]):
            inv = inventory.current()
            # A change to refresh after (an operation that changed nothing refreshes nothing).
            changed = inv.with_collection("home", [{"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                                    "finish": "nonfoil", "quantity": "1"}])
            after, summary = refresh.in_op(inv, changed, Summary("x"))
        self.assertEqual(summary.extra["tables"]["skipped"], [{"id": "casual/test", "title": "Test", "why": "kit"}])
        self.assertEqual(after.deck("casual/test").text, deck.text)


class RefreshInOpTests(support.PoolTestCase):
    """A kind registered with refresh=True gets its deck tables refreshed in the same change."""

    def setUp(self):
        super().setUp()
        self.text = support.deck_md(
            "Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
            table="| Llanowar Elves | 2 | 0 | **2** | ~$1.00 | ~$2.00 | keep this hand note |\n"
                  "| **Total** | | | **2** | | **~$2.00** | |\n")
        self.write("decks/casual/test.md", self.text)

        def add(inv, name="Llanowar Elves"):
            row = {"name": name, "set": "fdn", "collector_number": "227", "finish": "nonfoil", "quantity": "2"}
            return inv.with_collection("home", [row]), Summary(f"add {name}")

        register("test.add", refresh=True)(add)
        self.addCleanup(inventory.unregister, "test.add")

    def deck_text(self):
        return (self.magic / "decks/casual/test.md").read_text(encoding="utf-8")

    def test_the_tables_are_saved_with_the_change(self):
        self.assertTrue(inventory.refreshes("test.add"))
        preview, summary = inventory.preview(Op("test.add"))
        self.assertEqual(summary.extra["tables"]["written"], [{"id": "casual/test", "title": "Test"}])
        self.assertIn("magic/decks/casual/test.md", changes.changed_paths(inventory.current(), preview))
        self.assertEqual(self.deck_text(), self.text)                  # a preview writes nothing
        after, summary = inventory.apply(Op("test.add"), TESTER, "add")
        self.assertEqual(summary.extra["tables"], {"written": [{"id": "casual/test", "title": "Test"}],
                                                   "skipped": [], "error": None})
        self.assertIn("| Llanowar Elves | 2 | 2 | 0 |", self.deck_text())
        self.assertIn("keep this hand note", self.deck_text())
        self.assertEqual(after.deck("casual/test").text, self.deck_text())

    def test_refresh_false_skips_it(self):
        _, summary = inventory.apply(Op("test.add"), TESTER, "add", refresh=False)
        self.assertNotIn("tables", summary.extra)
        self.assertEqual(self.deck_text(), self.text)

    def test_a_plan_that_fails_leaves_the_decks_and_saves_the_change(self):
        after, summary = inventory.apply(Op("test.add", {"name": "Not a real card"}), TESTER, "add")
        self.assertIn("incomplete card pool", summary.extra["tables"]["error"])
        self.assertEqual(summary.extra["tables"]["written"], [])
        self.assertEqual(self.deck_text(), self.text)
        self.assertEqual([r.text("name") for r in after.collection().rows], ["Not a real card"])

    def test_a_deck_the_operation_changed_itself_is_skipped(self):
        def both(inv):
            deck = inv.deck("casual/test")
            inv = inv.with_deck(deck.replace(text=deck.text + "\nMine.\n"))
            row = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                   "quantity": "2"}
            return inv.with_collection("home", [row]), Summary("both")
        register("test.both", refresh=True)(both)
        self.addCleanup(inventory.unregister, "test.both")
        with mock.patch.object(refresh, "plan_texts",
                               return_value=[("casual/test", "Test", self.text, self.text + "x")]):
            _, summary = inventory.apply(Op("test.both"), TESTER, "both")
        self.assertEqual(summary.extra["tables"]["skipped"], [{"id": "casual/test", "title": "Test", "why": "changed"}])
        self.assertTrue(self.deck_text().endswith("\nMine.\n"))


if __name__ == "__main__":
    unittest.main()
