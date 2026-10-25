"""Packing completion chooses kit in the same revision-checked deck transaction."""
import json
from unittest import mock

from decklab.lib import accessories, config, decks, inventory, pool
from decklab.lib.api import assembly, assembly_completion as completion, settings
from decklab.lib.api.common import ApiError
from decklab.lib.decks import standins
from decklab.lib.inventory import ops_decks
from decklab.tests import db_support
from decklab.tests.test_assembly_completion import PROFILES, TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_inventory_contract import CLAUDE, adapt
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


ACCESSORIES = (",".join(accessories.FIELDS) + "\n"
               "mine,sleeves,matt,DS,Matte,red,100,,,,,,\n"
               "shared,sleeves,shared,DS,Matte,blue,100,,,,,,\n"
               "hers,sleeves,user1,DS,Matte,pink,100,,,,,,\n"
               "box,deck_box,shared,UG,Boulder,black,1,100,,,,,\n"
               "empty,deck_box,shared,UG,Empty,grey,0,100,,,,,\n")


class _KitFixtures:
    def setUp(self):
        super().setUp()
        for target, name, value in ((settings, "_config_profiles", mock.Mock(return_value=PROFILES)),
                                    (config, "CONFIG_FILE", self.magic.parent / "config.json")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        config.CONFIG_FILE.write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        self.write("accessories.csv", ACCESSORIES)
        self.make_deck("a", count=2)
        self.make_deck("b", count=2)

    def make_deck(self, slug, *, count=2, status="building", player="user", owned=None, kit=None):
        self.deck(slug, slug.upper(), status, f"Deck\n{count} Llanowar Elves\n20 Forest\n",
                  owned=owned, table=TABLE)
        path = self.magic / f"decks/casual/{slug}.md"
        text = path.read_text(encoding="utf-8").replace("**Played by:** either", f"**Played by:** {player}")
        if kit:
            text = text.replace(f"- **Status:** {status}", f"- **Status:** {status}\n"
                                + "\n".join(f"- **{key}:** {value}" for key, value in kit.items()))
        path.write_text(text + "\n## Notes\n\nKeep the game plan.\n", encoding="utf-8", newline="\n")

    def request(self, *slugs, profile="matt", version="target"):
        selected = [{"id": f"casual/{slug}", "version": version} for slug in slugs or ("a",)]
        plan = assembly.assembly_preview(json.dumps({"profile": profile, "decks": selected}))
        return plan, {"profile": profile, "decks": selected, "confirmed": True,
                      "fingerprint": plan["completion"]["fingerprint"]}

    def mark(self, body):
        return completion.mark_built(json.dumps(body))

    def parsed(self, slug):
        return ops_decks.parsed_deck(inventory.current().deck(f"casual/{slug}"))

    def choices(self, sleeves="mine", box="box"):
        return {"sleeves": sleeves, "deck_box": box}


class AssemblyKitTests(_KitFixtures, PreparationCase):
    def test_review_uses_chosen_list_count_and_current_values(self):
        self.make_deck("a", owned="Deck\n4 Elvish Mystic\n20 Forest\nSideboard\n1 Forest\n",
                       kit={"Sleeves": "old red", "Deck box": "old box"})
        plan, _ = self.request(version="owned")
        review = plan["completion"]
        self.assertTrue(review["review"])
        self.assertEqual(review["decks"][0], {"id": "casual/a", "title": "A", "version": "owned",
                         "versions": ["target", "owned"], "owner": "matt", "kit_why_not": None,
                         "build_scope": {"mode": "all", "label": "Main deck + whole sideboard",
                                         "main_count": 24, "sideboard_count": 1,
                                         "sideboard_intended": 1, "return_count": 0}, "returns": [],
                         "kit": {"sleeves": "old red", "deck_box": "old box", "need": 25, "editable": True}})

    def test_build_and_kit_and_tables_use_one_apply_preserving_lists_and_prose(self):
        before = self.parsed("a")
        _, body = self.request()
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            answer = self.mark({**body, "kit": {"casual/a": self.choices()}})
        self.assertEqual(apply.call_count, 1)
        after = self.parsed("a")
        self.assertEqual((after.status, after.sleeves, after.deck_box), ("built", "mine", "box"))
        self.assertEqual(after.target, before.target)
        self.assertIn("Keep the game plan.", after.text)
        self.assertIsNone(after.changed_on)
        self.assertIsNone(answer["tables"]["error"])
        self.assertEqual(self.parsed("b").status, "building")

    def test_omitted_kit_preserves_legacy_values_and_explicit_null_clears(self):
        for change in (False, True):
            with self.subTest(clear=change):
                self.make_deck("a", kit={"Sleeves": "old red", "Deck box": "old box"})
                _, body = self.request()
                if change:
                    body["kit"] = {"casual/a": self.choices(None, None)}
                self.mark(body)
                after = self.parsed("a")
                self.assertEqual((after.sleeves, after.deck_box), (None, None) if change else ("old red", "old box"))

    def test_unchanged_legacy_values_may_be_reviewed_but_new_free_text_is_refused(self):
        self.make_deck("a", kit={"Sleeves": "old red", "Deck box": "old box"})
        _, body = self.request()
        with self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices("new red", "old box")}})
        self.assertEqual(caught.exception.status, 400)
        self.mark({**body, "kit": {"casual/a": self.choices("old red", "old box")}})
        self.assertEqual(self.parsed("a").sleeves, "old red")

    def test_wrong_kind_unknown_and_zero_quantity_choices_save_nothing(self):
        _, body = self.request()
        before = inventory.current()
        for fields, code in ((self.choices("box", None), 400), (self.choices("absent", None), 400),
                             (self.choices("mine", "empty"), 409), (self.choices("hers", None), 400)):
            with self.subTest(fields=fields), self.assertRaises(ApiError) as caught:
                self.mark({**body, "kit": {"casual/a": fields}})
            self.assertEqual(caught.exception.status, code)
            self.assertEqual(inventory.current(), before)

    def test_invalid_map_fields_and_nonparticipants_are_refused(self):
        _, body = self.request()
        bad = (None, [], {"casual/b": self.choices()}, {"casual/a": {}},
               {"casual/a": {**self.choices(), "extra": None}},
               {"casual/a": self.choices(3)}, {"casual/a": self.choices("")})
        for kit in bad:
            with self.subTest(kit=kit), self.assertRaises(ApiError) as caught:
                self.mark({**body, "kit": kit})
            self.assertEqual(caught.exception.status, 400)
        self.assertEqual(self.parsed("a").status, "building")

    def test_other_owners_kit_is_hidden_and_admin_cannot_choose_it(self):
        self.make_deck("a", player="wife", kit={"Sleeves": "hers", "Deck box": "old secret box"})
        plan, body = self.request()
        review = plan["completion"]["decks"][0]
        self.assertIsNone(review["owner"])
        self.assertIsNone(review["kit"])
        self.assertNotIn("old secret box", json.dumps(review))
        with self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices(None, None)}})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(self.parsed("a").status, "building")
        self.mark(body)                         # building without touching her kit remains allowed
        self.assertEqual(self.parsed("a").sleeves, "hers")

    def test_member_can_build_own_deck_with_own_or_shared_kit(self):
        self.make_deck("a", player="wife")
        plan, body = self.request(profile="user1")
        self.assertEqual(plan["completion"]["decks"][0]["owner"], "user1")
        self.mark({**body, "kit": {"casual/a": self.choices("hers")}})
        self.assertEqual((self.parsed("a").sleeves, self.parsed("a").deck_box), ("hers", "box"))

    def test_two_decks_cannot_take_the_single_box_and_all_changes_roll_back(self):
        _, body = self.request("a", "b")
        before = inventory.current()
        with self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices(), "casual/b": self.choices()}})
        self.assertEqual(caught.exception.status, 409)
        self.assertIn("taken_by", caught.exception.extra)
        self.assertEqual(inventory.current(), before)

    def test_explicit_box_handoff_is_independent_of_selected_deck_order(self):
        for order in (("a", "b"), ("b", "a")):
            with self.subTest(order=order):
                self.make_deck("a", status="built", owned="Deck\n2 Elvish Mystic\n20 Forest\n",
                               kit={"Built version": "owned-only", "Sleeves": "mine", "Deck box": "box"})
                self.make_deck("b")
                _, body = self.request(*order)
                self.mark({**body, "kit": {"casual/a": self.choices("mine", None),
                                           "casual/b": self.choices("shared", "box")}})
                self.assertEqual((self.parsed("a").deck_box, self.parsed("b").deck_box), (None, "box"))
                self.assertEqual((self.parsed("a").built_version, self.parsed("b").status), ("target", "built"))

    def test_two_built_decks_can_swap_their_boxes_in_one_completion(self):
        self.write("accessories.csv", ACCESSORIES + "other,deck_box,shared,UG,Other,grey,1,100,,,,,\n")
        for slug, box in (("a", "box"), ("b", "other")):
            self.make_deck(slug, status="built", owned="Deck\n2 Elvish Mystic\n20 Forest\n",
                           kit={"Built version": "owned-only", "Sleeves": "shared", "Deck box": box})
        _, body = self.request("b", "a")
        self.mark({**body, "kit": {"casual/a": self.choices("shared", "other"),
                                   "casual/b": self.choices("shared", "box")}})
        self.assertEqual((self.parsed("a").deck_box, self.parsed("b").deck_box), ("other", "box"))

    def test_shared_sleeves_can_be_chosen_for_both_decks(self):
        _, body = self.request("a", "b")
        self.mark({**body, "kit": {f"casual/{slug}": self.choices("shared", None) for slug in ("a", "b")}})
        self.assertEqual([(self.parsed(slug).status, self.parsed(slug).sleeves) for slug in ("a", "b")],
                         [("built", "shared"), ("built", "shared")])

    def test_built_deck_switches_version_and_kit_together(self):
        self.make_deck("a", status="built", owned="Deck\n4 Elvish Mystic\n20 Forest\n",
                       kit={"Built version": "owned-only", "Sleeves": "mine", "Deck box": "box"})
        _, body = self.request()
        self.mark({**body, "kit": {"casual/a": self.choices("shared", None)}})
        parsed = self.parsed("a")
        self.assertEqual((parsed.status, parsed.built_version, parsed.sleeves, parsed.deck_box),
                         ("built", "target", "shared", None))
        held = next(holder for holder in pool.load_pool().in_use if holder.id == "casual/a")
        self.assertEqual((held.cards["Elvish Mystic"], held.cards["Llanowar Elves"]), (0, 2))

    def test_accessory_change_before_or_inside_apply_refuses_without_building(self):
        _, body = self.request()
        self.write("accessories.csv", ACCESSORIES.replace("red,100", "red,99"))
        with self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices()}})
        self.assertEqual(caught.exception.status, 409)
        _, body = self.request()
        apply = self.inventory.apply

        def race(*args, **kwargs):
            self.write("accessories.csv", ACCESSORIES.replace("red,100", "red,98"))
            return apply(*args, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=race), self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices()}})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual((self.parsed("a").status, self.parsed("a").sleeves), ("building", None))

    def test_install_with_kit_then_explicit_repack_on_real_arrival_preserves_kit(self):
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        rows = [{"for": "Llanowar Elves", "using": "Elvish Mystic", "qty": 2}]
        parsed = self.parsed("a")
        standins.set_choices(parsed, "target", rows)
        self.write("decks/casual/a.md", decks.render_deck_file(parsed))
        plan, body = self.request()
        self.assertTrue(plan["ready"])
        self.assertEqual(plan["logical_totals"]["missing"], 2)
        self.mark({**body, "kit": {"casual/a": self.choices()}})
        self.assertEqual(standins.installed_for(self.parsed("a")), {"version": "target", "cards": rows})
        held = next(holder for holder in pool.load_pool().in_use if holder.id == "casual/a")
        self.assertEqual((held.cards["Elvish Mystic"], held.cards["Llanowar Elves"]), (2, 0))
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        plan, body = self.request()
        self.assertTrue(plan["completion"]["can_mark_built"])
        self.assertTrue(plan["decks"][0]["completion"]["already_built"])
        self.assertTrue(plan["decks"][0]["completion"]["repack"])
        self.mark(body)
        parsed = self.parsed("a")
        self.assertIsNone(standins.installed_for(parsed))
        self.assertEqual((parsed.sleeves, parsed.deck_box), ("mine", "box"))
        held = next(holder for holder in pool.load_pool().in_use if holder.id == "casual/a")
        self.assertEqual((held.cards["Elvish Mystic"], held.cards["Llanowar Elves"]), (0, 2))


class PgAssemblyKitTests(_KitFixtures, db_support.DbTestCase, PreparationCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=[{"plays_as": None, **profile, "emails": []} for profile in PROFILES],
                           dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.make_deck("a", owned="Deck\n4 Elvish Mystic\n20 Forest\n")
        snapshot = adapt(self.inventory.load())
        snapshot = snapshot.with_accessories(accessories.read().rows_by_id.values())
        pg.write_model(snapshot, CLAUDE, "Import assembly kit fixtures",
                       dbname=self.dbname, decks=True)
        self.inventory = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.inventory))

    def test_build_version_kit_tables_one_audit_and_one_deck_revision(self):
        before = inventory.current()
        _, body = self.request(version="owned")
        with self.connect() as conn:
            count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        answer = self.mark({**body, "kit": {"casual/a": self.choices()}})
        after = inventory.current()
        self.assertTrue(answer["saved"])
        self.assertEqual((self.parsed("a").status, self.parsed("a").sleeves, self.parsed("a").deck_box),
                         ("built", "mine", "box"))
        self.assertEqual(self.parsed("a").built_version, "owned")
        self.assertEqual(after.deck("casual/a").revision, before.deck("casual/a").revision + 1)
        self.assertEqual(after.revision, before.revision)
        self.assertNotEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(after.collection("home"), before.collection("home"))
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], count + 1)
            self.assertEqual(conn.execute("select actor, message from audit.change_set order by id desc limit 1").fetchone(),
                             ("matt", "mark built: A"))

    def test_box_handoff_saves_one_final_revision_per_deck_and_one_audit(self):
        _, first = self.request(version="owned")
        self.mark({**first, "kit": {"casual/a": self.choices()}})
        before = inventory.current()
        with self.connect() as conn:
            audit_count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        _, body = self.request("b", "a")
        self.mark({**body, "kit": {"casual/a": self.choices("mine", None),
                                   "casual/b": self.choices("shared", "box")}})
        after = inventory.current()
        self.assertEqual((self.parsed("a").deck_box, self.parsed("b").deck_box), (None, "box"))
        for slug in ("a", "b"):
            self.assertEqual(after.deck(f"casual/{slug}").revision, before.deck(f"casual/{slug}").revision + 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], audit_count + 1)

    def test_box_swap_saves_one_final_revision_per_deck_and_one_audit(self):
        _, added = inventory.apply(inventory.Op("accessory.add", {
            "row": {"kind": "deck_box", "owner": "shared", "name": "Other", "quantity": 1, "capacity": 100},
            "sha256": accessories.view_sha256(accessories.read(), None), "owners": None}),
            CLAUDE, "Add fixture box")
        other = added.extra["id"]
        for slug in ("a", "b"):
            stored = inventory.current().deck(f"casual/{slug}")
            text = stored.text.replace("4 Elvish Mystic", "2 Elvish Mystic") if slug == "a" else (
                stored.text + "\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n2 Elvish Mystic\n20 Forest\n```\n")
            inventory.apply(inventory.Op("deck.save", {"deck_id": stored.id, "text": text,
                                                        "base_sha256": stored.sha256}), CLAUDE, "Prepare fixture list")
        _, first = self.request("a", "b", version="owned")
        self.mark({**first, "kit": {"casual/a": self.choices("shared", "box"),
                                    "casual/b": self.choices("shared", other)}})
        before = inventory.current()
        with self.connect() as conn:
            audit_count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        _, body = self.request("b", "a")
        self.mark({**body, "kit": {"casual/a": self.choices("shared", other),
                                   "casual/b": self.choices("shared", "box")}})
        after = inventory.current()
        self.assertEqual((self.parsed("a").deck_box, self.parsed("b").deck_box), (other, "box"))
        for slug in ("a", "b"):
            self.assertEqual(after.deck(f"casual/{slug}").revision, before.deck(f"casual/{slug}").revision + 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], audit_count + 1)

    def test_failure_after_first_participant_changes_rolls_back_decks_and_audit(self):
        _, body = self.request("a", "b")
        plan = assembly._preview(body["decks"], profile=PROFILES[0])
        items, _, _ = completion._texts(plan, PROFILES[0], {"casual/a": self.choices(),
                                                          "casual/b": self.choices("shared", None)})
        items[1]["kit_changes"] = [{"holder": "casual/b", "field": "deck_box", "value": "box"}]
        before = inventory.current()
        with self.connect() as conn:
            count = conn.execute("select count(*) from audit.change_set").fetchone()[0]
        with self.assertRaises(inventory.Conflict):
            inventory.apply(completion._BuildPlan(before, items), CLAUDE, "Refused fixture build")
        self.assertEqual(inventory.current(), before)
        with self.connect() as conn:
            self.assertEqual(conn.execute("select count(*) from audit.change_set").fetchone()[0], count)

    def test_concurrent_deck_save_under_transaction_refuses_status_and_kit(self):
        _, body = self.request()
        before = inventory.current()
        apply = self.inventory.apply

        def race(op, actor, message, **kwargs):
            other = inventory.current().deck("casual/b")
            concurrent = inventory.Op("deck.save", {"deck_id": other.id, "base_sha256": other.sha256,
                                                    "text": other.text + "\nConcurrent fixture note.\n"})
            apply(concurrent, CLAUDE, "Concurrent fixture edit")
            return apply(op, actor, message, **kwargs)

        with mock.patch.object(self.inventory, "apply", side_effect=race), self.assertRaises(ApiError) as caught:
            self.mark({**body, "kit": {"casual/a": self.choices()}})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(inventory.current().deck("casual/a"), before.deck("casual/a"))
        with self.connect() as conn:
            self.assertEqual(conn.execute("select message from audit.change_set order by id desc limit 1").fetchone(),
                             ("Concurrent fixture edit",))
