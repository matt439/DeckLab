"""PostgreSQL inventory contract cases; shared adapters, scenarios and goldens stay in test_inventory_contract.
These tests use a throwaway database and skip when db_support cannot provide one.
Fixture globals and patch owners are read through the original support module.
"""
from decklab.tests import test_inventory_contract as contract


@contract.unittest.skipIf(contract.db_support.unavailable(), contract.db_support.unavailable() or "")
class PgInventoryTests(contract.db_support.DbTestCase):
    """PgInventory and write_model in a throwaway database (the fixture profiles synced once)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        self.pg = pg
        contract.db_support.reset(self.dbname, contract.db_support.INVENTORY_TABLES)
        self.breaker = state_pg.Breaker()
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        for kind, fn in contract.OPS.items():
            contract.inventory.register(kind)(fn)
            self.addCleanup(contract.inventory.unregister, kind)

    def trail(self):
        with self.connect() as c:
            sets = c.execute("select id, actor, source, message, reason from audit.change_set order by id").fetchall()
            rows = c.execute("select change_set_id, table_name, op, row_key, before, after from audit.row_change "
                             "order by id").fetchall()
        return [{"actor": s[1], "source": s[2], "message": s[3], "reason": s[4],
                 "rows": [r[1:] for r in rows if r[0] == s[0]]} for s in sets]

    def import_tree(self, builder):
        inv, contents = contract.build_scenario(builder)
        adapted = contract.adapt(inv)
        self.pg.write_model(adapted, contract.CLAUDE, "Import the inventory", contents=contents, dbname=self.dbname,
                            decks=True)
        return adapted

    def assertSameModel(self, db_inv, file_inv):
        self.assertEqual(db_inv.backend, "db")
        self.assertEqual(db_inv.replace(revision=file_inv.revision, backend=file_inv.backend,
                                        decks_revision=file_inv.decks_revision), file_inv)
        self.assertEqual(contract.files.render(db_inv, decks=True), contract.files.render(file_inv, decks=True))
        # render() leaves out pictures whose bytes a loaded snapshot doesn't hold: compare their metas.
        self.assertEqual({n: (m.name, m.size, m.sha256) for n, m in db_inv.accessory_images.items()},
                         {n: (m.name, m.size, m.sha256) for n, m in file_inv.accessory_images.items()})
        self.assertEqual(db_inv.accessories.exists, file_inv.accessories.exists)

    # -------------------------------------------------------- backend equality

    def test_every_scenario_loads_back_the_same(self):
        for name, builder in contract.SCENARIOS.items():
            if name in contract.FILE_ONLY:
                continue
            with self.subTest(scenario=name):
                contract.db_support.reset(self.dbname, contract.db_support.INVENTORY_TABLES)
                adapted = self.import_tree(builder)
                self.assertSameModel(self.backend.load(), adapted)

    def test_the_real_repo_at_the_golden_commit(self):
        if not contract.gate.golden_rev_available():
            self.skipTest(f"the repo has no commit {contract.gate.GOLDEN_REV[:7]} (the private repo's golden commit)")
        sha, blobs = contract.files.git_files(contract.gate.GOLDEN_REV)
        inv = contract.files.build(blobs)
        self.assertEqual(self.pg.representable(inv), [])
        contents = {contract.paths.classify(rel)[1]: data for rel, data in blobs.items() if contract.paths.classify(rel)[0] == "import"}
        revision = self.pg.write_model(inv, contract.CLAUDE, f"Import the inventory files at {sha[:7]}", contents=contents,
                                       dbname=self.dbname)
        self.assertEqual(revision, "1")
        loaded = self.backend.load()
        self.assertSameModel(loaded, inv)
        expected = {rel: data for rel, data in blobs.items() if contract.paths.classify(rel)[0] != "import"}
        self.assertEqual(sorted(contract.files.render(loaded)), sorted(expected))
        for rel, data in contract.files.render(loaded).items():
            with self.subTest(rel=rel):
                self.assertEqual(data, expected[rel])
        with self.connect() as c:
            kept = {(r[0], r[1]): bytes(r[2]) for r in c.execute(
                "select i.space_id, i.file_name, c.content from collection_import i "
                "join collection_import_content c on c.import_id = i.id").fetchall()}
            audited = c.execute("select count(*) from audit.row_change where table_name = 'collection_import' "
                                "and after ? 'content'").fetchone()[0]
        self.assertEqual(kept, contents)
        self.assertEqual(audited, 0)

    def test_the_real_repo_deck_parts_at_the_phase_4_golden_commit(self):
        """Phase 4: every deck file, accessories.csv and picture at gate.GOLDEN_REV_P4 (git's
        blobs) imported: the File model's deck parts equal the Pg model's, and the database gives
        back every file byte for byte (the pictures raw, through image())."""
        if contract.subprocess_rev(contract.gate.GOLDEN_REV_P4) is None:
            self.skipTest(f"the repo has no commit {contract.gate.GOLDEN_REV_P4[:7]}")
        self.import_tree(contract.seed_tree)
        sha, blobs = contract.files.git_files(contract.gate.GOLDEN_REV_P4, decks=True)
        parts = {rel: data for rel, data in blobs.items() if contract.paths.is_deck_part(rel)}
        inv = contract.files.build(parts)
        self.assertEqual(self.pg.deck_tables(inv, strict=True)[1], [])
        images = {contract.paths.classify(rel)[1]: data for rel, data in parts.items() if contract.paths.classify(rel)[0] == "image"}
        self.pg.write_decks(inv, contract.CLAUDE, f"Import the decks at {sha[:7]}", images=images, replace=True,
                            dbname=self.dbname)
        loaded = self.backend.load()
        self.assertEqual((len(loaded.decks), len(loaded.accessory_images)), (19, 23))
        for field in ("decks", "accessories", "accessory_images"):
            self.assertEqual(getattr(loaded, field), getattr(inv, field), field)
        rendered = {rel: data for rel, data in contract.files.render(loaded, decks=True).items() if contract.paths.is_deck_part(rel)}
        for rel, data in parts.items():
            with self.subTest(rel=rel):
                what, detail = contract.paths.classify(rel)
                if what == "image":
                    self.assertEqual(self.backend.image(detail), data)
                    self.assertEqual(self.backend.image(detail, loaded.image_meta(detail).sha256), data)
                else:
                    self.assertEqual(rendered[rel], data)
        self.assertEqual(sorted(rendered), sorted(rel for rel in parts if contract.paths.classify(rel)[0] != "image"))
        self.assertTrue(all(d.revision == 1 for d in loaded.decks.values()))
        with self.connect() as c:
            audited = c.execute("select table_name, count(*) from audit.row_change where table_name in "
                                "('deck', 'deck_text', 'deck_revision', 'deck_line', 'accessory', 'accessory_image') "
                                "group by 1 order by 1").fetchall()
        self.assertEqual(audited, [("accessory", len(inv.accessories.rows)), ("deck", 19)])

    # -------------------------------------------------------- importing

    def test_nothing_is_there_until_the_import(self):
        with self.assertRaisesRegex(self.pg.NotImported, "holds no inventory: on a new install, run python -m decklab.db setup.*restore the newest backup"):
            self.backend.load()
        with self.assertRaises(self.pg.NotImported):
            self.backend.apply(contract.inventory.Op("test.nothing"), contract.CLAUDE, "Nothing")
        self.assertTrue(self.backend.reachable())
        self.assertEqual(self.trail(), [])

    def test_write_model_refuses_a_second_import_unless_replacing(self):
        adapted = self.import_tree(contract.seed_tree)
        first = self.backend.load()
        with self.assertRaisesRegex(ValueError, "replace-inventory"):
            self.pg.write_model(adapted, contract.CLAUDE, "Again", dbname=self.dbname)
        smaller = adapted.replace(watchlist=contract.dataclasses.replace(adapted.watchlist, rows=adapted.watchlist.rows[:1]))
        smaller = contract.files.build(contract.files.render(smaller)).replace(imports=adapted.imports)
        self.assertEqual(self.pg.write_model(smaller, contract.CLAUDE, "Import again", replace=True, dbname=self.dbname), "2")
        again = self.backend.load()
        self.assertEqual(len(again.watchlist.rows), 1)
        self.assertSameModel(again, smaller)
        self.assertNotEqual(again.revision, first.revision)
        self.assertEqual([c["message"] for c in self.trail()], ["Import the inventory", "Import again"])

    def test_write_model_refusals(self):
        inv, contents = contract.build_scenario(contract.person_spaces)
        adapted = contract.adapt(inv)
        with self.assertRaisesRegex(ValueError, "content wasn't given"):
            self.pg.write_model(adapted, contract.CLAUDE, "Import", dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "line 2: quantity 'lots'"):
            self.pg.write_model(contract.build_scenario(contract.malformed_rows)[0], contract.CLAUDE, "Import", dbname=self.dbname)
        with self.assertRaisesRegex(self.pg.Unrepresentable, "no order record names it"):
            self.pg.write_model(contract.build_scenario(contract.loose_orders)[0], contract.CLAUDE, "Import", dbname=self.dbname)
        stranger = adapted.replace(collections={**adapted.collections, "zoe": adapted.collection("user2")})
        stranger = contract.files.build({**contract.files.render(stranger), "magic/people/zoe/collection.csv":
                               contract.files.render_sheet(adapted.collection("user2"))}).replace(imports=adapted.imports)
        with self.assertRaisesRegex(ValueError, "space zoe"):
            self.pg.write_model(stranger, contract.CLAUDE, "Import", contents=contents, dbname=self.dbname)
        self.assertEqual(self.trail(), [])

    # -------------------------------------------------------- applying

    def test_apply_writes_one_change_set_with_only_what_changed(self):
        self.import_tree(contract.seed_tree)
        before = self.backend.load()
        after, summary = self.backend.apply(contract.inventory.Op("test.set_quantity", {"index": 0}), contract.MATT, "Set Opt to 3")
        self.assertEqual(summary.counts, {"rows": 1})
        self.assertEqual(int(after.revision), int(before.revision) + 1)
        self.assertEqual((after.collection().rows[0].name, after.collection().rows[0].quantity), ("Opt", "3"))
        self.assertIs(self.backend.load(), after)                 # cached by revision
        change = self.trail()[-1]
        self.assertEqual((change["actor"], change["source"], change["message"]), ("matt", "web", "Set Opt to 3"))
        self.assertEqual([(r[0], r[1]) for r in change["rows"]], [("collection_card", "UPDATE")])
        self.assertEqual(change["rows"][0][2], {"space_id": "home", "set_code": "dom", "collector_number": "60",
                                                "finish": "nonfoil"})

    def test_an_op_that_changes_nothing_writes_nothing(self):
        self.import_tree(contract.seed_tree)
        before = self.backend.load()
        after, summary = self.backend.apply(contract.inventory.Op("test.nothing"), contract.MATT, "Nothing")
        self.assertEqual((after.revision, summary.text), (before.revision, "Nothing"))
        self.assertEqual(len(self.trail()), 1)

    def test_expected_revision_is_checked_only_when_given(self):
        self.import_tree(contract.seed_tree)
        before = self.backend.load()
        self.backend.apply(contract.inventory.Op("test.set_quantity"), contract.MATT, "Set", expected_revision=before.revision)
        with self.assertRaisesRegex(contract.Conflict, "changed since this was previewed"):
            self.backend.apply(contract.inventory.Op("test.set_quantity", {"quantity": "4"}), contract.MATT, "Set",
                               expected_revision=before.revision)
        self.assertEqual(self.backend.load().collection().rows[0].quantity, "3")

    def test_token_and_watchlist_rows_keep_their_ids_and_places(self):
        self.import_tree(contract.seed_tree)
        before = self.backend.load()
        ids = [r.id for r in before.token_set().rows]
        self.assertTrue(all(ids) and len(set(ids)) == 3)
        after, _ = self.backend.apply(contract.inventory.Op("test.edit_tokens", {"remove": 0}), contract.MATT, "Remove Treasure")
        self.assertEqual([r.id for r in after.token_set().rows], ids[1:])
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("token_card", "DELETE")])
        add = ("Elf", "", "tltc", "25", "", "nonfoil", "1", "", "", "")
        after, _ = self.backend.apply(contract.inventory.Op("test.edit_tokens", {"add": add, "at": 1, "edit": 0}), contract.MATT,
                                      "Add an Elf")
        self.assertEqual([r.front for r in after.token_set().rows], ["Zombie", "Elf", "Goblin"])
        self.assertEqual([r.id for r in after.token_set().rows][::2], ids[1:])
        self.assertEqual(after.token_set().rows[0].notes, "edited")
        self.assertEqual(sorted((r[0], r[1]) for r in self.trail()[-1]["rows"]),
                         [("token_card", "INSERT"), ("token_card", "UPDATE")])
        watch = [r.id for r in after.watchlist.rows]
        after, _ = self.backend.apply(contract.inventory.Op("test.drop_watch", {"index": 1}), contract.MATT, "Ordered Shock")
        self.assertEqual([r.id for r in after.watchlist.rows], watch[:1] + watch[2:])
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("watchlist_item", "DELETE")])
        self.assertSameModel(after, contract.files.build(contract.files.render(after)).replace(imports=after.imports))

    def test_positions_make_room_or_start_again(self):
        positions = self.pg._positions
        self.assertEqual(positions([1, 2, 3], {1: 1024, 2: 2048, 3: 3072}), [1024, 2048, 3072])
        self.assertEqual(positions([1, 0, 3], {1: 1024, 3: 3072}), [1024, 2048, 3072])
        self.assertEqual(positions([3, 1], {1: 1024, 3: 3072}), [512, 1024])      # one moves, not both
        self.assertEqual(positions([0, 1], {1: 1}), [1024, 2048])          # no room before 1
        self.assertEqual(positions([0, 0], {}), [1024, 2048])

    def test_a_receipt_moves_the_component_without_rewriting_its_rows(self):
        self.import_tree(contract.seed_tree)
        after, _ = self.backend.apply(contract.inventory.Op("test.receive", {"order_id": "2026-10-07-shop-a",
                                                                    "component_id": "cards", "date": "2026-10-12"}),
                                      contract.CLAUDE, "Receive 2026-10-07-shop-a (cards)")
        self.assertIn("magic/orders/received/2026-10-07-shop-a.csv", after.payloads)
        self.assertNotIn("magic/orders/2026-10-07-shop-a.csv", after.payloads)
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("order_component", "UPDATE")])
        self.assertSameModel(after, contract.files.build(contract.files.render(after)).replace(imports=after.imports))

    def test_imports_are_kept_with_their_change_and_never_twice(self):
        self.import_tree(contract.seed_tree)
        after, _ = self.backend.apply(contract.inventory.Op("test.keep_import", {"name": "a.csv"}), contract.MATT, "Import a.csv")
        self.assertEqual(after.imports["user2"], (contract.model.ImportInfo("a.csv", 20),))
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("collection_import", "INSERT")])
        self.assertNotIn("content", self.trail()[-1]["rows"][0][4])
        with self.assertRaisesRegex(ValueError, "magic/people/user2/imports/a.csv already exists"):
            self.backend.apply(contract.inventory.Op("test.keep_import", {"name": "a.csv"}), contract.MATT, "Import a.csv")

    def test_a_snapshot_the_database_cant_hold_is_invalid(self):
        self.import_tree(contract.seed_tree)
        with self.assertRaisesRegex(contract.Invalid, "can't be saved like that: Row 1 of the home collection: .*'x'"):
            self.backend.apply(contract.inventory.Op("test.set_quantity", {"quantity": "x"}), contract.MATT, "Set")
        self.assertEqual(len(self.trail()), 1)

    def test_the_last_good_snapshot_is_served_while_the_database_is_down(self):
        self.import_tree(contract.seed_tree)
        good = self.backend.load()
        self.breaker.trip("stopped")
        self.assertFalse(self.backend.reachable())
        stale = self.backend.load()
        self.assertRegex(stale.stale, r"^inventory as of \d{4}-\d\d-\d\d \d\d:\d\d: the database isn't reachable$")
        self.assertEqual(stale.replace(stale=None), good)
        with self.assertRaises(contract.Unavailable):
            self.backend.apply(contract.inventory.Op("test.set_quantity"), contract.MATT, "Set")
        self.breaker.reset()
        self.assertIsNone(self.backend.load().stale)
        fresh = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker)
        self.breaker.trip("stopped")
        with self.assertRaises(contract.Unavailable):
            fresh.load()                                    # nothing good to fall back on
        self.breaker.reset()

    def test_two_writers_at_once_both_land(self):
        self.import_tree(contract.seed_tree)
        errors = []

        def write(space, quantity):
            try:
                self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).apply(
                    contract.inventory.Op("test.set_quantity", {"space": space, "quantity": quantity}), contract.MATT, f"Set {space}")
            except Exception as e:                          # noqa: BLE001 (reported below)
                errors.append(e)
        threads = [contract.threading.Thread(target=write, args=args) for args in (("home", "5"), ("user2", "7"))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        inv = self.backend.load()
        self.assertEqual((inv.collection().rows[0].quantity, inv.collection("user2").rows[0].quantity), ("5", "7"))

    def test_the_package_api_runs_on_the_database_backend(self):
        self.import_tree(contract.seed_tree)
        with contract.inventory.use(self.backend):
            with contract.inventory.pinned():
                first = contract.inventory.current()
                after, _ = contract.inventory.apply(contract.inventory.Op("test.set_quantity"), contract.MATT, "Set")
                self.assertIs(contract.inventory.current(), after)
            self.assertNotEqual(first.revision, after.revision)
            self.assertEqual(contract.inventory.current().revision, after.revision)

    # -------------------------------------------------------- the foundation review's fixes

    def test_an_op_changing_a_record_in_place_is_saved_and_the_cache_kept(self):
        self.import_tree(contract.seed_tree)
        before = self.backend.load()
        after, _ = self.backend.apply(contract.inventory.Op("test.mutate_record"), contract.MATT, "Notes in place")
        self.assertEqual(after.order("2026-09-29-seller2").notes, "changed in place")
        self.assertEqual(before.order("2026-09-29-seller2").notes, "")       # the cached snapshot is untouched
        self.assertEqual([(r[0], r[1]) for r in self.trail()[-1]["rows"]], [("purchase_order", "UPDATE")])
        fresh = self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load()
        self.assertEqual(fresh.order("2026-09-29-seller2").notes, "changed in place")

    def test_both_backends_settle_and_refuse_the_same(self):
        """The same ops on the database and on the same tree as files give the same files, and
        the same refusals."""
        self.import_tree(contract.seed_tree)
        tree = contract.build_tree(contract.seed_tree)
        self.addCleanup(tree.doCleanups)
        on_files = contract.FileInventory(tree.inventory.root)
        steps = [("test.rows", {"rows": [("Shock", "m19", "156", "nonfoil", "1"), ("Opt", "dom", "60", "nonfoil", "2")]}),
                 ("test.rows", {"space": "user2", "rows": []}),
                 ("test.receive", {"order_id": "2026-10-07-shop-a", "component_id": "cards", "date": "2026-10-12"})]
        for kind, params in steps:
            with self.subTest(kind=kind, params=params):
                db_after, _ = self.backend.apply(contract.inventory.Op(kind, params), contract.MATT, kind)
                file_after, _ = on_files.apply(contract.inventory.Op(kind, params), contract.MATT, kind)
                self.assertEqual(contract.files.render(db_after), contract.files.render(file_after))
        self.assertNotIn("user2", db_after.collections)
        self.assertEqual([r.set for r in db_after.collection().rows], ["dom", "m19"])
        for kind, params, error in (("test.set_quantity", {"quantity": "x"}, contract.Invalid),
                                    ("test.loose_payload", {}, contract.Invalid),
                                    ("test.tokens_raw", {}, None)):
            with self.subTest(kind=kind):
                outcomes = []
                for backend in (self.backend, on_files):
                    try:
                        backend.apply(contract.inventory.Op(kind, params), contract.MATT, kind)
                        outcomes.append(None)
                    except (contract.Invalid, contract.Conflict) as e:
                        outcomes.append((type(e), str(e)))
                self.assertEqual(outcomes[0], outcomes[1])
                if error:
                    self.assertEqual(outcomes[0][0], error)

    def test_removing_the_last_accessory_leaves_both_backends_the_same(self):
        self.import_tree(contract.built_decks_and_kits)
        tree = contract.build_tree(contract.built_decks_and_kits)
        self.addCleanup(tree.doCleanups)
        on_files = contract.FileInventory(tree.inventory.root)
        db_after, _ = self.backend.apply(contract.inventory.Op("test.no_accessories"), contract.MATT, "remove every accessory")
        file_after, _ = on_files.apply(contract.inventory.Op("test.no_accessories"), contract.MATT, "remove every accessory")
        self.assertFalse(db_after.accessories.exists)
        self.assertFalse((tree.inventory.root / contract.paths.ACCESSORIES).exists())
        self.assertSameModel(db_after, file_after)
        self.assertSameModel(self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load(), on_files.load())

    def test_a_large_import_is_one_quick_change(self):
        self.import_tree(contract.seed_tree)
        rows = [(f"Card {n}", "tst", str(n), "nonfoil", "1") for n in range(1, 20001)]
        started = contract.time.monotonic()
        after, _ = self.backend.apply(contract.inventory.Op("test.rows", {"rows": rows}), contract.MATT, "Import 20,000 cards")
        took = contract.time.monotonic() - started
        self.assertEqual(len(after.collection().rows), 20000)
        self.assertEqual(len(self.trail()), 2)
        self.assertLess(took, 60, f"a 20,000-row write took {took:.1f}s")

    def test_the_database_backend_gives_the_goldens_of_ported_readers(self):
        for name, builder in contract.SCENARIOS.items():
            if name in contract.FILE_ONLY:
                continue
            with self.subTest(scenario=name):
                contract.db_support.reset(self.dbname, contract.db_support.INVENTORY_TABLES)
                with contract.scenario(builder, adapted=True) as case:
                    root = case.inventory.root
                    self.pg.write_model(case.inventory.load(), contract.CLAUDE, "Import", contents=contract.import_contents(root),
                                        dbname=self.dbname, decks=True)
                    # Nothing may read the inventory files now. The snapshot's deck parts are the
                    # database's (imported with decks=True); the files stay, the same bytes, for the
                    # readers phase 4's areas haven't ported yet (the deck page's holder sha256,
                    # lib/accessories), and go here once they're all ported.
                    for rel in contract.files.tree_files(root):
                        (root / rel).unlink()
                    got = contract.expected_p4(contract.run_readers(self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker), root))
                golden = contract.load_golden(name, adapted=True)
                self.assertEqual(set(got), set(golden))
                for key in sorted(contract.PORTED):
                    found = contract.gate.first_difference(golden[key], got[key], f"$[{key!r}]")
                    self.assertIsNone(found, found)

    def test_incoming_source_identity_status_and_allocation_from_database(self):
        # E6-S03's new fields have direct PostgreSQL coverage: the old reader goldens deliberately
        # ignore these additions, while continuing to compare all previous labels and counts.
        from decklab.lib import pool
        from decklab.lib.api.card_lookup import _owned_json

        def incoming(t):
            t.cards_csv("orders/parcel.csv", ("Sol Ring", "ecc", "57", "nonfoil", 2))
            t.product("incoming-precon.csv", ("Main", "Sol Ring", 3), column="section")
            t.status(("incoming-precon.csv", "preordered", ""))
            contract._records(t, contract.Order.build("2026-10-14-shop", components=[
                contract.Component.build("cards", "cards", "parcel.csv"),
                contract.Component.build("precon", "product", "incoming-precon.csv")]))
            t.deck("incoming", "Incoming", "building", "Deck\n4 Sol Ring\n")

        self.import_tree(incoming)
        snapshot = self.backend.load()
        self.assertEqual(snapshot.backend, "db")
        with contract.fixture_world(), contract.inventory.pinned(snapshot):
            answer = _owned_json(pool.owned_vs_needed("casual/incoming", prices=False))
        self.assertEqual(answer["totals"]["missing"], 0)
        self.assertEqual(answer["rows"][0]["labels"]["incoming_sources"], [
            {"source": "order 2026-10-14-shop", "quantity": 2, "order_id": "2026-10-14-shop",
             "component_id": "cards", "product_id": None, "status": "ordered"},
            {"source": "Incoming Precon", "quantity": 2, "order_id": "2026-10-14-shop",
             "component_id": "precon", "product_id": "incoming-precon", "status": "preordered"}])

    def test_reset_empties_the_inventory(self):
        self.import_tree(contract.seed_tree)
        contract.db_support.reset(self.dbname, contract.db_support.INVENTORY_TABLES)
        with self.assertRaises(self.pg.NotImported):
            self.pg.PgInventory(dbname=self.dbname, breaker=self.breaker).load()
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from collection_import_content").fetchone()[0], 0)
