"""Accessory visibility and inventory-reader permission cases.
PermissionTestCase, its fixture globals and patch owners remain in test_api_permissions.
Only the concrete reader groups live here, without re-exporting them from their support module.
"""
from decklab.tests import test_api_permissions as permission_tests


class AccessoryVisibilityTests(permission_tests.PermissionTestCase):
    """Private accessories follow their owners: User1's black sleeves (on her Elf Commander) are
    seen by her and unnamed-viewer script fixtures, never by Matt (an admin) or User2. The shared
    grey sleeves (on the "either" Gruul Test) are seen by every home profile."""

    SEE = {"user1", "local", "script"}           # direct no-viewer script fixtures see all
    SEE_SHARED = {"matt", "user1", "local", "script"}

    def setUp(self):
        super().setUp()
        from decklab.tests.test_accessory_fetch import png
        images = self.box.magic / "accessories" / "images"
        for name, value in (("PATH", self.box.magic / "accessories.csv"), ("IMAGES", images)):
            patcher = permission_tests.mock.patch.object(permission_tests.lib_accessories, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # One sleeve for a deck of three cards: too few, so User1's draft check warns about it.
        permission_tests._write(self.box.magic / "accessories.csv", ",".join(permission_tests.lib_accessories.FIELDS) + "\n"
               "black-sleeves,sleeves,user1,Dragon Shield,Matte,black,1,,black-sleeves.png,,,,\n"
               "grey-sleeves,sleeves,shared,KMC,Hyper Matte,grey,100,,grey-sleeves.png,,,,\n")
        images.mkdir(parents=True, exist_ok=True)
        (images / "black-sleeves.png").write_bytes(png())
        (images / "grey-sleeves.png").write_bytes(png())
        gruul = self.box.magic / "decks" / "casual" / "gruul-test.md"
        permission_tests._write(gruul, gruul.read_text(encoding="utf-8").replace(
            "- **Status:** building\n",
            "- **Status:** built\n- **Built version:** target\n- **Sleeves:** grey-sleeves\n"))
        path = self.box.magic / "decks" / "commander" / "elf-commander.md"
        permission_tests._write(path, path.read_text(encoding="utf-8").replace(
            "- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** black-sleeves\n- **Deck box:** blue box\n"))

    def answer(self, who, call):
        identity = None if who in permission_tests.HOME_WRITERS else {"profile": who, "email": "", "remote": True}
        with permission_tests.access.using(identity):
            return call()

    def test_the_accessories_list_and_pictures(self):
        self.check(lambda p: permission_tests.accessories.accessories_view(), self.SEE_SHARED)
        from decklab.tests.test_accessory_fetch import png
        from decklab.tests.test_api_accessories import image_version
        version = image_version(png())                      # both pictures' bytes
        self.check(lambda p: permission_tests.accessories.image_file("grey-sleeves.png", version), self.SEE_SHARED)
        self.check(lambda p: permission_tests.accessories.staged_image("0" * 32 + ".png"), self.SEE_SHARED)
        with permission_tests.access.using({"profile": "user2", "email": "", "remote": True}):
            # Its words name no space (E10-S38).
            self.assertApiError(403, permission_tests.accessories.accessories_view, contains="are private")
            with self.assertRaises(permission_tests.api.ApiError) as hidden:
                permission_tests.accessories.accessories_view()
            self.assertNotIn("home", hidden.exception.message)
        # User1's picture: as if it weren't there for Matt.
        with permission_tests.access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(404, permission_tests.accessories.image_file, "black-sleeves.png", version)
        with permission_tests.access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertEqual(permission_tests.accessories.image_file("black-sleeves.png", version)[1], "image/png")

    def test_each_sees_only_their_own_and_the_shared_rows(self):
        for who, ids in (("matt", ["grey-sleeves"]), ("user1", ["black-sleeves", "grey-sleeves"]),
                         ("local", ["black-sleeves", "grey-sleeves"])):
            view = self.answer(who, permission_tests.accessories.accessories_view)
            self.assertEqual([i["id"] for i in view["items"]], ids, who)
            holders = sorted(o["id"] for o in view["holders_options"])
            self.assertEqual("commander/elf-commander" in holders, who != "matt", who)
            self.assertIn("casual/gruul-test", holders, who)
            if who == "matt":
                self.assertNotIn("black-sleeves", permission_tests.json.dumps(view))
                self.assertNotIn("Elf Commander", permission_tests.json.dumps(view))
                self.assertEqual(view["owners"], [{"id": "matt", "name": "Matt"},
                                                  {"id": "shared", "name": "shared"}])

    def test_the_home_network_answers_for_the_profile_its_chooser_names(self):
        from decklab.tests.test_accessory_fetch import png
        from decklab.tests.test_api_accessories import image_version
        version = image_version(png())
        with permission_tests.access.viewing("matt"):
            view = permission_tests.accessories.accessories_view()
            self.assertEqual([i["id"] for i in view["items"]], ["grey-sleeves"])
            self.assertApiError(404, permission_tests.accessories.image_file, "black-sleeves.png", version)
            elf = next(d for d in permission_tests.api.decks_index()["decks"] if d["id"] == "commander/elf-commander")
            self.assertIsNone(elf["kit"])
        with permission_tests.access.viewing("user1"):
            self.assertEqual([i["id"] for i in permission_tests.accessories.accessories_view()["items"]],
                             ["black-sleeves", "grey-sleeves"])
        with permission_tests.access.viewing("user2"):
            self.assertApiError(403, permission_tests.accessories.accessories_view)
        with permission_tests.access.viewing("nobody-known"):          # not in config.json: as if nobody were named
            self.assertEqual(len(permission_tests.accessories.accessories_view()["items"]), 2)

    def test_a_shared_rows_holders_the_viewer_cant_see_are_anonymous(self):
        # User1's deck takes the shared grey sleeves in place of hers: Matt sees the row is used,
        # but only by "one of User1's decks".
        for path, old, new in (
                (self.box.magic / "decks" / "casual" / "gruul-test.md", "- **Sleeves:** grey-sleeves\n", ""),
                (self.box.magic / "decks" / "commander" / "elf-commander.md", "black-sleeves", "grey-sleeves")):
            permission_tests._write(path, path.read_text(encoding="utf-8").replace(old, new))
        view = self.answer("matt", permission_tests.accessories.accessories_view)
        grey = next(i for i in view["items"] if i["id"] == "grey-sleeves")
        self.assertEqual(grey["used_by"], [{"holder": None, "title": "one of User1's decks", "kind": "deck",
                                            "need": 3}])
        self.assertNotIn("Elf Commander", permission_tests.json.dumps(view))
        grey = next(i for i in self.answer("user1", permission_tests.accessories.accessories_view)["items"]
                    if i["id"] == "grey-sleeves")
        self.assertEqual(grey["used_by"][0]["holder"], "commander/elf-commander")

    def test_a_shared_deck_shows_its_kit_to_every_home_profile(self):
        for who in permission_tests.WHO:
            sees = who in self.SEE_SHARED
            index = self.answer(who, permission_tests.api.decks_index)
            if who == "user2":        # a home deck isn't his to see: not listed, its page a missing deck's (E10-S30)
                self.assertNotIn("casual/gruul-test", [d["id"] for d in index["decks"]])
                self.assertNotIn("grey-sleeves", permission_tests.json.dumps(index))
                with permission_tests.access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, permission_tests.api.deck_view, "casual/gruul-test")
                continue
            gruul = next(d for d in index["decks"] if d["id"] == "casual/gruul-test")
            self.assertEqual(gruul["sleeves"], "grey-sleeves" if sees else None, who)
            self.assertEqual(gruul["kit"] is not None, sees, who)
            page = self.answer(who, lambda: permission_tests.api.deck_view("casual/gruul-test"))
            self.assertEqual(page["summary"]["kit"] is not None, sees, who)

    def test_the_library_and_deck_page(self):
        for who in permission_tests.WHO:
            sees = who in self.SEE
            index = self.answer(who, permission_tests.api.decks_index)
            if who == "user2":        # a home deck isn't his to see at all (E10-S30)
                self.assertNotIn("commander/elf-commander", [d["id"] for d in index["decks"]])
                self.assertNotIn("black-sleeves", permission_tests.json.dumps(index))
                with permission_tests.access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, permission_tests.api.deck_view, "commander/elf-commander")
                continue
            elf = next(d for d in index["decks"] if d["id"] == "commander/elf-commander")
            self.assertEqual(elf["sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(elf["deck_box"], "blue box" if sees else None, who)
            self.assertEqual(elf["kit"] is not None, sees, who)
            page = self.answer(who, lambda: permission_tests.api.deck_view("commander/elf-commander"))
            s = page["summary"]
            self.assertEqual((s["kit"] is not None, s["holder_sha256"] is not None, s["sleeves"] is not None),
                             (sees, sees, sees), who)
            self.assertEqual(any("sleeve" in w.lower() for w in page["warnings"]), sees, who)
            if not sees:
                self.assertNotIn("black-sleeves", permission_tests.json.dumps(page))
                self.assertNotIn("black-sleeves", permission_tests.json.dumps(index))

    def test_the_editor_and_a_draft_check(self):
        for who in permission_tests.WHO:
            sees = who in self.SEE
            if who == "user2":        # a home deck is hidden from him: as a missing one (E10-S30)
                with permission_tests.access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, permission_tests.api.edit_view, "commander/elf-commander")
                    self.assertApiError(404, permission_tests.api.check_draft, self.body(who, id="commander/elf-commander"))
                continue
            view = self.answer(who, lambda: permission_tests.api.edit_view("commander/elf-commander"))
            self.assertEqual(view["fields"]["sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(view["field_text"]["Deck box"], "blue box" if sees else None, who)
            self.assertEqual("sleeves" in view["editable_fields"], sees, who)
            self.assertEqual(bool(view["accessories"]["sleeves"]), sees, who)
            if not sees:
                self.assertNotIn("black-sleeves", permission_tests.json.dumps(view))
            check = self.answer(who, lambda: permission_tests.api.check_draft(self.body(
                permission_tests.HOME_WRITERS.get(who, who), id="commander/elf-commander")))
            self.assertEqual(any("sleeve" in w["text"].lower() if isinstance(w, dict) else "sleeve" in w.lower()
                                 for w in check["warnings"]), sees, who)

    def test_a_draft_s_played_by_doesnt_show_another_s_kit(self):
        # Matt's draft says Played by: user, but the deck's stored Sleeves are still User1's.
        check = self.answer("matt", lambda: permission_tests.api.check_draft(self.body(
            "matt", id="commander/elf-commander", fields={"player": "user"})))
        shown = permission_tests.json.dumps(check["warnings"])
        for hidden in ("black-sleeves", "Dragon Shield", "black", "User1", "sleeve"):
            self.assertNotIn(hidden, shown)
        # Her own check still has them.
        check = self.answer("user1", lambda: permission_tests.api.check_draft(self.body("user1", id="commander/elf-commander")))
        self.assertIn("sleeve", permission_tests.json.dumps(check["warnings"]).lower())

    def test_handing_on_a_deck_with_kit_is_an_accessories_change(self):
        deck = "commander/elf-commander"
        path = self.box.magic / "decks" / "commander" / "elf-commander.md"
        before = path.read_bytes()
        # Matt, an admin, may give a deck to someone else, but not one holding User1's sleeves.
        with permission_tests.access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(403, permission_tests.api.save_deck, self.body("matt", id=deck, sha256=self.sha(deck),
                                                               fields={"player": "user"}), contains="sleeves")
        self.assertEqual(path.read_bytes(), before)
        # The shared grey sleeves on the "either" Gruul Test may go with it to Matt.
        gruul = "casual/gruul-test"
        with permission_tests.access.using({"profile": "matt", "email": "", "remote": True}):
            saved = permission_tests.api.save_deck(self.body("matt", id=gruul, sha256=self.sha(gruul), fields={"player": "user"}))
        self.assertTrue(saved["changed"])
        # Taking a deck apart as it changes hands frees its kit: nothing to choose.
        with permission_tests.access.using({"profile": "matt", "email": "", "remote": True}):
            saved = permission_tests.api.save_deck(self.body("matt", id=deck, sha256=self.sha(deck),
                                            fields={"player": "user", "status": "building"}))
        self.assertNotIn("black-sleeves", path.read_text(encoding="utf-8"))

    def test_a_revision_and_the_packing_plan(self):
        from decklab.tests.test_deck_history import install, revision as saved
        deck_id = "commander/elf-commander"
        text = (self.box.magic / "decks" / "commander" / "elf-commander.md").read_text(encoding="utf-8")
        install(self.box, {deck_id: [saved(deck_id, 1, text, op="A", actor="user1", kit=True,
                                           message="Sleeve it in black-sleeves")]})
        revision = "1"
        for who in permission_tests.WHO:
            if who == "user2":        # a home deck's history is as a missing deck's (E10-S30)
                with permission_tests.access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, permission_tests.history.deck_history, deck_id)
                    self.assertApiError(404, permission_tests.history.deck_revision, deck_id, revision)
                    self.assertApiError(403, permission_tests.assembly.assembly_view, "commander/elf-commander")
                continue
            subject = self.answer(who, lambda: permission_tests.history.deck_history(deck_id))["revisions"][0]["subject"]
            self.assertEqual(subject, "Sleeve it in black-sleeves" if who in self.SEE else None, who)
            sees = who in self.SEE
            old = self.answer(who, lambda: permission_tests.history.deck_revision("commander/elf-commander", revision))
            self.assertEqual(old["fields"]["Sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(old["current"]["fields"]["sleeves"], "black-sleeves" if sees else None, who)
            if who == "user2":        # the packing plan is the home pool's (InventoryReadTests)
                with permission_tests.access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(403, permission_tests.assembly.assembly_view, "commander/elf-commander")
                continue
            plan = self.answer(who, lambda: permission_tests.assembly.assembly_view("commander/elf-commander"))
            deck = plan["decks"][0]
            self.assertEqual((deck["kit"] is not None, deck["sleeves"] is not None, deck["sleeves_need"] is not None),
                             (sees, sees, sees), who)
            plan = self.answer(who, lambda: permission_tests.assembly.assembly_preview(self.body(
                permission_tests.HOME_WRITERS.get(who, who), decks=[{"id": "commander/elf-commander", "version": "target"}])))
            self.assertEqual(plan["decks"][0]["kit"] is not None, sees, who)

    def test_a_deck_save_chooses_only_what_the_deck_may_take(self):
        csv_path = self.box.magic / "accessories.csv"
        permission_tests._write(csv_path, csv_path.read_text(encoding="utf-8")
               + "white-sleeves,sleeves,matt,KMC,Hyper Matte,white,100,,,,,,\n")
        deck = "commander/elf-commander"
        # User1: Matt's sleeves aren't hers to use (she doesn't see them), the shared ones are.
        with permission_tests.access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertApiError(400, permission_tests.api.save_deck, self.body("user1", id=deck, sha256=self.sha(deck),
                                                               fields={"sleeves": "white-sleeves"}))
            self.assertTrue(permission_tests.api.save_deck(self.body("user1", id=deck, sha256=self.sha(deck),
                                                    fields={"sleeves": "grey-sleeves"}))["saved"])
        self.assertIn("- **Sleeves:** grey-sleeves", (self.box.magic / "decks" / "commander" /
                                                      "elf-commander.md").read_text(encoding="utf-8"))
        # Matt: his own sleeves don't go on the house's "either" deck, which takes shared ones only.
        gruul = "casual/gruul-test"
        with permission_tests.access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(400, permission_tests.api.save_deck, self.body("matt", id=gruul, sha256=self.sha(gruul),
                                                               fields={"sleeves": "white-sleeves"}),
                                contains="shared ones")
            self.assertApiError(400, permission_tests.api.save_deck, self.body("matt", id=gruul, sha256=self.sha(gruul),
                                                               fields={"sleeves": "black-sleeves"}))

    def test_me_says_who_sees_them(self):
        for who in ("matt", "user1", "user2"):
            may = permission_tests.access.me({"profile": who, "email": "", "remote": True})["may"]
            self.assertEqual(may["see_accessories"], who != "user2", who)
        self.assertTrue(permission_tests.access.me(None)["may"]["see_accessories"])

    def test_hiding_them_never_clears_a_files_lines(self):
        # A Sleeves line written by hand in User2's own deck: hidden from him, but his save keeps it.
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        permission_tests._write(path, path.read_text(encoding="utf-8").replace(
            "- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** red\n"))
        with permission_tests.access.using({"profile": "user2", "email": "", "remote": True}):
            view = permission_tests.api.edit_view("user2/casual/r-elves")
            self.assertIsNone(view["fields"]["sleeves"])
            answer = permission_tests.api.save_deck(self.body("user2", id="user2/casual/r-elves", sha256=view["sha256"],
                                             fields={"archetype": "Elves"}))
        self.assertTrue(answer["saved"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("- **Sleeves:** red", text)
        self.assertIn("- **Archetype:** Elves", text)

class InventoryReadTests(permission_tests.PermissionTestCase):
    """Who may read the inventory (permissions.sees_inventory, guard.require_sees_inventory): home's
    collection and tokens, shopping list, receipts and packing plan only the home profiles; User2's
    collection and tokens only User2 (E10-S29: an admin's role opens no other space). Each route
    is asked as Matt (admin), User1 (a home member) and User2 (his own space) through the tunnel, a tunnel login that isn't set up, the home
    network naming nobody (everything, as for accessories; a body naming User1) and the home network naming
    User1 or User2 (the chooser's viewer, whose reads and changes follow that profile, E10-S03)."""

    READERS = ("matt", "user1", "user2", "stranger", "local", "local:user1", "local:user2")
    HOME = {"matt", "user1", "local", "local:user1"}
    USER2 = {"user2", "local", "local:user2"}

    def as_(self, who):
        """(the context the request runs in, the profile a body names) for who."""
        stack = permission_tests.contextlib.ExitStack()
        if who.startswith("local"):
            named = who.partition(":")[2] or None
            stack.enter_context(permission_tests.access.using(None))
            stack.enter_context(permission_tests.access.viewing(named))
            return stack, named or "user1"
        stack.enter_context(permission_tests.access.using({"profile": who, "email": "", "remote": True}))
        return stack, who

    def read_status(self, who, call):
        context, profile = self.as_(who)
        with context:
            try:
                call(profile)
            except permission_tests.api.ApiError as e:
                return e.status
        return 200

    def readable(self, call, allowed):
        """call(profile) is refused (403) exactly for the readers not in allowed."""
        got = {who: self.read_status(who, call) != 403 for who in self.READERS}
        self.assertEqual(got, {who: who in allowed for who in self.READERS})

    def test_shopping_is_homes(self):
        self.readable(lambda p: permission_tests.shopping.shopping_overview(), self.HOME)

    def test_receipts_are_homes(self):
        self.readable(lambda p: permission_tests.receipts.receipt_view("2026-10-01-x"), self.HOME)
        full = {"order": "x", "fingerprint": "0", "received_on": "2026-10-01", "components": []}
        # The previews and applies are an admin's too, by role on the home network as well (E10-S03).
        admins = {"matt"}
        self.readable(lambda p: permission_tests.receipts.preview_receipt(self.body(p, **full)), admins)
        self.readable(lambda p: permission_tests.receipts.apply_receipt(self.body(p, preview="0")), admins)
        check = {"order": "x", "component": "cards", "check": "Look at it"}
        self.readable(lambda p: permission_tests.shopping.resolve_check(self.body(p, **check)), admins)
        change = {"row": 1, "state": "long_term", "expect": permission_tests.inventory.current().revision}
        self.readable(lambda p: permission_tests.shopping_queue.save_queue_state(self.body(p, **change)), admins)
        self.readable(lambda p: permission_tests.shopping_orders.preview_order(self.body(
            p, expect="stale", record={"id": "x"})), admins)
        self.readable(lambda p: permission_tests.shopping_orders.apply_order(self.body(p, preview="0")), admins)
        self.readable(lambda p: permission_tests.shopping_order_changes.preview_order_change(self.body(
            p, expect="stale", order="x", action="record", values={"seller": "Shop"})), admins)
        self.readable(lambda p: permission_tests.shopping_order_changes.apply_order_change(self.body(p, preview="0")), admins)
        context, _ = self.as_("user2")
        with context:
            self.assertApiError(403, permission_tests.receipts.receipt_view, "2026-10-01-x", contains="are private")
            with self.assertRaises(permission_tests.api.ApiError) as hidden:
                permission_tests.receipts.receipt_view("2026-10-01-x")
            self.assertEqual(hidden.exception.message, permission_tests.guard.INVENTORY_HIDDEN)
            self.assertNotIn("home", hidden.exception.message)          # it names no space (E10-S38)

    def test_the_collection_and_its_rows(self):
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: permission_tests.collection.collection_view(space=space), allowed)
            self.readable(lambda p: permission_tests.collection_edit.rows_view(space), allowed)
        # No space is home's.
        self.readable(lambda p: permission_tests.collection_edit.rows_view(), self.HOME)
        # The 403 names no one, and is the same for a space that doesn't exist (E10-S29).
        for who in ("user1", "matt", "local:user1"):
            context, _ = self.as_(who)
            with context:
                for space in ("user2", "nobody"):
                    error = self.assertApiError(403, permission_tests.collection_edit.rows_view, space)
                    self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}), who)

    def test_the_tokens(self):
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: permission_tests.api_tokens.tokens_view(space), allowed)
        self.readable(lambda p: permission_tests.api_tokens.tokens_view(), self.HOME)

    def test_the_packing_plan(self):
        self.readable(lambda p: permission_tests.assembly.assembly_view(), self.HOME)
        self.readable(lambda p: permission_tests.assembly.assembly_preview(self.body(p, decks=[])), self.HOME)

    def test_a_precons_preview(self):
        # Only where it may add one (collection.edit, E10-S29): Matt is refused User2's before any deck
        # id there is looked up; User1 may preview home's (E10-S43).
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: permission_tests.precons.precon_preview(file="nothing.json", space=space), allowed)

    def test_the_collections_spaces_are_only_those_it_sees(self):
        everyone = ["home", "user2", "user3"]
        for who, ids in (("matt", ["home"]), ("user1", ["home"]), ("user2", ["user2"]), ("stranger", []),
                         ("local", everyone), ("local:user1", ["home"]), ("local:user2", ["user2"])):
            context, _ = self.as_(who)
            with context:
                self.assertEqual([s["id"] for s in permission_tests.collection.space_choices()], ids, who)

    def test_the_printing_pickers_counts(self):
        # Home's pool for whoever sees it, else the viewer's own space's, else none.
        for who, space in (("matt", "home"), ("user1", "home"), ("user2", "user2"), ("stranger", None),
                           ("local", "home"), ("local:user1", "home"), ("local:user2", "user2")):
            context, _ = self.as_(who)
            with context, permission_tests.mock.patch.object(permission_tests.pool, "printing_counts",
                                            side_effect=lambda space="home": {space: True}) as counts:
                self.assertEqual(permission_tests.card_lookup._pool_counts(), {space: True} if space else {}, who)
                self.assertEqual(counts.called, space is not None, who)

    def test_paste_a_list_defaults_from_the_same_pool_as_the_picker(self):
        # "Paste a list" picks a line's printing from card_lookup._pool_counts, as search and the
        # printing picker do: never home's counts for someone outside the home.
        for who, space in (("matt", "home"), ("user2", "user2"), ("local:user2", "user2"),
                           ("local:user1", "home")):
            context, profile = self.as_(who)
            with context, permission_tests.mock.patch.object(permission_tests.pool, "printing_counts",
                                            side_effect=lambda space="home": {}) as counts:
                permission_tests.api.parse_list(self.body(profile, text="1 Llanowar Elves"))
            self.assertEqual([c.args[0] if c.args else "home" for c in counts.call_args_list], [space], who)

    def test_a_drafts_counts_come_only_from_a_pool_it_sees(self):
        # "Try a change" compares the page's own list with a pool: only one the visitor may see,
        # else owned and availability are None (no counting another space's cards by pasting).
        cases = ((dict(id="casual/gruul-test"), self.HOME), (dict(kind="casual", space="home"), self.HOME),
                 (dict(id="user2/casual/r-elves"), self.USER2),
                 (dict(kind="casual", space="user2"), self.USER2))
        for data, allowed in cases:
            for who in ("matt", "user1", "user2", "local", "local:user1", "local:user2"):
                context, profile = self.as_(who)
                with context:
                    try:
                        answer = permission_tests.api.check_draft(self.body(profile, **data))
                    except permission_tests.api.ApiError as e:
                        if "id" in data:            # a saved deck of a space the writer isn't in: 404
                            # as a missing one (E10-S30), Matt the admin included
                            self.assertEqual(e.status, 404, (data, who))
                            self.assertNotEqual(permission_tests.spaces.space_of(data["id"]),
                                                "user2" if profile == "user2" else "home", (data, who))
                            continue
                        # a new deck in a space it may not make one in
                        self.assertEqual(e.status, 403, (data, who))
                        self.assertNotIn(who, allowed, (data, who))
                        continue
                seen = who in allowed
                self.assertEqual(answer["owned"] is not None, seen, (data, who))
                self.assertEqual(answer["availability"]["target"] is not None, seen, (data, who))

    def test_user2_picked_at_home_is_refused_homes_writes_with_nothing_of_homes(self):
        # At this lower-level API boundary, a named User2 cannot write home's data. The HTTP home
        # listener separately refuses non-home profile selection (E10-S35). A refusal carries only
        # the reason, never a list, conflict or rows, even when the submitted sha256 is stale.
        with permission_tests.access.using(None):
            sha = permission_tests.api_tokens.tokens_view()["sha256"]
            deck_sha = self.sha("casual/gruul-test")
        context, profile = self.as_("local:user2")
        row = {"front": "Treasure", "back": "", "quantity": 1, "notes": "single-sided verified"}
        card = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                "quantity": 1}
        full = {"order": "x", "fingerprint": "0", "received_on": "2026-10-01", "components": []}
        calls = (
            lambda: permission_tests.api_tokens.save_token(self.body(profile, space="home", action="add", sha256="0" * 64, row=row)),
            lambda: permission_tests.api_tokens.save_token(self.body(profile, space="home", action="add", sha256=sha, row=row)),
            lambda: permission_tests.collection_edit.save_card(self.body(profile, space="home", action="add", sha256="0" * 64,
                                                        row=card)),
            lambda: permission_tests.collection_edit.import_preview(self.body(profile, space="home", filename="x.csv", text="")),
            lambda: permission_tests.precons.add_precon(self.body(profile, space="home", file="x.json", title="X",
                                                 sha256="0" * 64)),
            lambda: permission_tests.receipts.preview_receipt(self.body(profile, **full)),
            lambda: permission_tests.receipts.apply_receipt(self.body(profile, preview="0")),
            lambda: permission_tests.shopping.resolve_check(self.body(profile, order="x", component="cards", check="Look")),
            lambda: permission_tests.shopping_queue.save_queue_state(self.body(profile, row=1, state="long_term", expect="stale")),
        )
        decks = (       # a home deck is hidden from him: 404 as a missing one, before any 403 or 409 (E10-S30)
            lambda: permission_tests.api.save_deck(self.body(profile, id="casual/gruul-test", sha256="0" * 64)),
            lambda: permission_tests.api.save_deck(self.body(profile, id="casual/gruul-test", sha256=deck_sha)),
        )
        names = permission_tests.mock.patch.object(permission_tests.lib_tokens, "check_names", lambda row: (row, []))   # no token names here
        with context, names:
            for i, call in enumerate(calls):
                with self.subTest(call=i), self.assertRaises(permission_tests.api.ApiError) as caught:
                    call()
                self.assertEqual((caught.exception.status, caught.exception.extra), (403, {}), i)
            for i, call in enumerate(decks):
                with self.subTest(deck_call=i), self.assertRaises(permission_tests.api.ApiError) as caught:
                    call()
                self.assertEqual((caught.exception.status, caught.exception.message, caught.exception.extra),
                                 (404, "No deck 'casual/gruul-test'", {}), i)
            self.assertApiError(403, permission_tests.api_tokens.tokens_view, "home")
        with permission_tests.access.using(None):
            self.assertEqual(permission_tests.api_tokens.tokens_view()["sha256"], sha)        # nothing was saved

    def test_a_write_names_the_same_profile_as_the_viewer_header(self):
        # The home page names its viewer in X-Deck-Lab-Viewer and the writer in the body: they must agree,
        # as a login and its body must through the tunnel. A script sending no header names itself.
        with permission_tests.access.using(None):
            with permission_tests.access.viewing("user1"):
                self.assertApiError(403, permission_tests.api.parse_list, self.body("matt", text="1 Opt"),
                                    contains="only make changes as yourself")
                with permission_tests.mock.patch.object(permission_tests.pool, "printing_counts", side_effect=lambda space="home": {}):
                    permission_tests.api.parse_list(self.body("user1", text="1 Llanowar Elves"))
            with permission_tests.mock.patch.object(permission_tests.pool, "printing_counts", side_effect=lambda space="home": {}):
                permission_tests.api.parse_list(self.body("matt", text="1 Llanowar Elves"))

    def test_me_says_which_spaces_it_sees(self):
        for who, seen in (("matt", ["home"]), ("user1", ["home"]), ("user2", ["user2"])):
            may = permission_tests.access.me({"profile": who, "email": "", "remote": True})["may"]
            self.assertEqual(may["see_inventory"], seen, who)
        self.assertIsNone(permission_tests.access.me(None)["may"]["see_inventory"])

    def test_the_rule(self):
        matt, user1 = {"id": "matt", "role": "admin", "space": "home"}, {"id": "user1", "role": "member"}
        user2 = {"id": "user2", "role": "member", "space": "user2"}
        for profile, local, home, user2s in ((matt, False, True, False), (matt, True, True, False),
                                               (user1, False, True, False),
                                               (user2, False, False, True), (user1, True, True, False),
                                               (user2, True, False, True), (None, True, True, True),
                                               (None, False, False, False)):
            self.assertEqual((permission_tests.permissions.sees_inventory(profile, "home", script=local),
                              permission_tests.permissions.sees_inventory(profile, "user2", script=local)),
                             (home, user2s), (profile, local))
