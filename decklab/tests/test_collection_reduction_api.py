"""Collection reduction review through the API, using temporary files and throwaway PostgreSQL."""
import copy
import json
from unittest import mock

from decklab.lib import config, inventory
from decklab.lib.api import collection_edit as ce
from decklab.lib.inventory import ops_collection
from decklab.tests import db_support
from decklab.tests import test_collection_edit as collection_tests
from decklab.tests import test_pool as pool_tests
from decklab.tests.test_api import Sandbox, _write
from decklab.tests.test_inventory_contract import CLAUDE, FIXTURE_PROFILES, MATT, adapt, import_contents


ORIGINAL = {"set": "fdn", "collector_number": "227", "finish": "nonfoil"}


def row(quantity=3, **extra):
    return {"name": "Llanowar Elves", **ORIGINAL, "quantity": quantity,
            "condition": "NM", "language": "en", "notes": "", **extra}


def held_text(quantity=4):
    table = ("| Llanowar Elves | 4 | 4 | **0** | | | |\n"
             "| **Total to buy** | | | **0** | | | |\n")
    return pool_tests.deck_md("Held", "built", f"Deck\n{quantity} Llanowar Elves (FDN) 227\n", table=table)


def prepare(box):
    """Replace only this test's synthetic fixture files; no live inventory is opened."""
    _write(box.magic / "collection.csv", collection_tests.HEADER
           + "Llanowar Elves,fdn,227,nonfoil,4,NM,en,\n")
    _write(box.magic / "decks" / "casual" / "gruul-test.md", held_text())
    _write(box.magic / "decks" / "casual" / "broken.md",
           pool_tests.deck_md("Unused", "idea", "Deck\n1 Black Lotus\n"))
    _write(box.magic / "decks" / "commander" / "elf-commander.md",
           pool_tests.deck_md("Unbuilt commander", "idea", "Deck\n1 Elvish Mystic\n"))
    _write(box.magic / "products" / "status.csv", "file,status,intact,notes\n"
           "fdn-beginner-box.csv,owned,no,\nfdc-test-precon.csv,owned,no,\n")


class ReductionApiTests(collection_tests.CollectionEditTestCase):
    def setUp(self):
        super().setUp()
        prepare(self.box)

    def payload(self, action="edit", **extra):
        value = {"action": action, "original": dict(ORIGINAL), "sha256": self.rows()["sha256"]}
        if action == "edit":
            value["row"] = row()
        value.update(extra)
        return value

    def challenge(self, payload, profile="matt", space="home"):
        before = self.magic_files()
        count = len(self.writes)
        error = self.assertApiError(409, self.save, space, profile, **payload)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(len(self.writes), count)
        self.assertRegex(error.extra["confirm_in_use"], r"^[0-9a-f]{64}$")
        self.assertTrue(error.extra["in_use"])
        return error.extra

    def test_reduction_warns_with_holders_and_writes_nothing(self):
        payload = self.payload()
        warning = self.challenge(payload)
        self.assertEqual(warning["sha256"], payload["sha256"])
        self.assertEqual(warning["rows"], self.rows()["rows"])
        self.assertEqual(warning["in_use"], [{"name": "Llanowar Elves", "before": 4, "after": 3,
                                              "in_use": 4, "shortage": 1, "holders": [
                                                  {"id": "casual/gruul-test", "title": "Held", "qty": 4}]}])

    def test_confirmed_quantity_reduction_keeps_its_optional_audit_reason(self):
        payload = self.payload(reason="Traded")
        warning = self.challenge(payload)
        answer = self.save(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["rows"][0]["quantity"], "3")
        self.assertEqual(self.reason(), "Traded")
        self.assertEqual(len(self.writes), 1)

    def test_confirmed_whole_row_removal_and_omitted_reason_are_allowed(self):
        payload = self.payload("remove")
        warning = self.challenge(payload)
        answer = self.save(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertEqual(answer["rows"], [])
        self.assertIsNone(self.reason())
        self.assertEqual(len(self.writes), 1)

    def test_a_token_for_a_different_row_payload_requires_a_new_review(self):
        payload = self.payload()
        first = self.challenge(payload)
        changed = {**payload, "row": row(quantity=2), "confirm_in_use": first["confirm_in_use"]}
        second = self.challenge(changed)
        self.assertNotEqual(second["confirm_in_use"], first["confirm_in_use"])
        self.assertEqual(second["in_use"][0]["shortage"], 2)

    def test_a_token_for_another_action_requires_a_new_review(self):
        first = self.challenge(self.payload())
        second = self.challenge(self.payload("remove", confirm_in_use=first["confirm_in_use"]))
        self.assertNotEqual(second["confirm_in_use"], first["confirm_in_use"])

    def test_a_token_for_another_original_printing_requires_a_new_review(self):
        _write(self.box.magic / "collection.csv", collection_tests.HEADER
               + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n"
               + "Llanowar Elves,fdn,227,foil,2,NM,en,\n")
        payload = self.payload("remove")
        first = self.challenge(payload)
        changed = {**payload, "original": {**ORIGINAL, "finish": "foil"},
                   "confirm_in_use": first["confirm_in_use"]}
        second = self.challenge(changed)
        self.assertEqual(first["in_use"], second["in_use"])
        self.assertNotEqual(first["confirm_in_use"], second["confirm_in_use"])

    def test_a_token_for_another_authorised_profile_requires_a_new_review(self):
        roles = copy.deepcopy(collection_tests.ROLES)
        roles["profiles"].append({"id": "other", "name": "Other", "role": "admin", "space": "home", "plays_as": "user"})
        _write(self.box.root / "config.json", json.dumps(roles))
        payload = self.payload()
        first = self.challenge(payload)
        second = self.challenge({**payload, "confirm_in_use": first["confirm_in_use"]}, profile="other")
        self.assertNotEqual(first["confirm_in_use"], second["confirm_in_use"])

    def test_collection_changes_invalidate_the_old_token_and_old_rows(self):
        payload = self.payload()
        first = self.challenge(payload)
        _write(self.box.magic / "collection.csv", collection_tests.HEADER
               + "Llanowar Elves,fdn,227,nonfoil,4,NM,en,corrected note\n")
        error = self.assertApiError(409, self.save, **payload, confirm_in_use=first["confirm_in_use"])
        self.assertNotEqual(error.extra["sha256"], payload["sha256"])
        self.assertNotIn("confirm_in_use", error.extra)
        second = self.challenge({**payload, "sha256": error.extra["sha256"],
                                 "confirm_in_use": first["confirm_in_use"]})
        self.assertNotEqual(first["confirm_in_use"], second["confirm_in_use"])

    def test_changed_built_deck_demand_requires_a_new_review_with_unchanged_collection_rows(self):
        payload = self.payload()
        first = self.challenge(payload)
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md", held_text(5))
        second = self.challenge({**payload, "confirm_in_use": first["confirm_in_use"]})
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["confirm_in_use"], second["confirm_in_use"])
        self.assertEqual(second["in_use"][0]["in_use"], 5)

    def test_changed_deck_revision_requires_a_new_review_even_when_the_warning_is_unchanged(self):
        payload = self.payload()
        first = self.challenge(payload)
        _write(self.box.magic / "decks" / "casual" / "gruul-test.md",
               held_text() + "\n## Notes\n\nFixture note changed.\n")
        second = self.challenge({**payload, "confirm_in_use": first["confirm_in_use"]})
        self.assertEqual(first["in_use"], second["in_use"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertNotEqual(first["confirm_in_use"], second["confirm_in_use"])

    def test_a_successful_confirmation_cannot_replay_the_old_quantity_change(self):
        payload = self.payload(reason="Sold")
        warning = self.challenge(payload)
        answer = self.save(**payload, confirm_in_use=warning["confirm_in_use"])
        error = self.assertApiError(409, self.save, **payload, confirm_in_use=warning["confirm_in_use"])
        self.assertEqual(error.extra["sha256"], answer["sha256"])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.rows()["rows"][0]["quantity"], "3")

    def test_concurrent_change_after_review_is_refused_before_collection_mutation(self):
        payload = self.payload()
        first = self.challenge(payload)
        real = self.backend.apply
        revisions = []

        def concurrent(op, actor, message, reason=None, expected_revision=None, **kwargs):
            revisions.append(expected_revision)
            _write(self.box.magic / "decks" / "casual" / "gruul-test.md", held_text(5))
            return real(op, actor, message, reason=reason, expected_revision=expected_revision, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=concurrent):
            self.assertApiError(409, self.save, **payload, confirm_in_use=first["confirm_in_use"])
        self.assertTrue(all(revisions))
        self.assertEqual(self.rows()["rows"][0]["quantity"], "4")
        self.assertEqual(self.writes, [])

    def test_reduction_that_leaves_enough_physical_copies_needs_no_confirmation(self):
        _write(self.box.magic / "collection.csv", collection_tests.HEADER
               + "Llanowar Elves,fdn,227,nonfoil,6,NM,en,\n")
        answer = self.save(**self.payload(row=row(quantity=4)), reason="Sold spare copies")
        self.assertTrue(answer["ok"])
        self.assertEqual(self.reason(), "Sold spare copies")

    def test_malformed_confirmation_is_refused_without_checking_or_writing(self):
        payload = self.payload()
        for value in ("bad", 123, True, {}, "g" * 64):
            with self.subTest(value=value):
                with mock.patch("decklab.lib.api.collection_guards.reduction_warnings") as checker:
                    self.assertApiError(400, self.save, **payload, confirm_in_use=value)
                    checker.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_permission_is_checked_before_any_held_card_warning(self):
        payload = self.payload()
        with self.as_("user2"), mock.patch("decklab.lib.api.collection_guards.reduction_warnings") as checker:
            self.assertApiError(403, self.save, "home", "user2", **payload)
            checker.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_confirmed_reduction_keeps_the_existing_manual_table_refresh_workflow(self):
        payload = self.payload()
        warning = self.challenge(payload)
        original_text = (self.box.magic / "decks" / "casual" / "gruul-test.md").read_text(encoding="utf-8")
        answer = self.save(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertEqual((self.box.magic / "decks" / "casual" / "gruul-test.md").read_text(encoding="utf-8"), original_text)
        [stale] = answer["stale_tables"]
        self.assertEqual((stale["id"], stale["changes"][0]["now"]["owned"],
                          stale["changes"][0]["now"]["missing"]), ("casual/gruul-test", 3, 1))

    def test_unknown_demand_warns_and_can_still_be_acknowledged(self):
        payload = self.payload("remove", reason="Entered twice")
        with self.box.no_index():
            warning = self.challenge(payload)
            self.assertEqual(set(warning["in_use"][0]), {"message"})
            self.assertNotIn(str(self.box.root), warning["in_use"][0]["message"])
            answer = self.save(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["rows"], [])
        self.assertEqual(self.reason(), "Entered twice")

    def test_collection_operations_compare_the_reviewed_deck_revision_before_mutation(self):
        before = self.backend.load()
        changed = before.replace(decks_revision=before.decks_revision + "-changed")
        for action in ("edit", "remove"):
            with self.subTest(action=action):
                params = {"space": "home", "original": list(ORIGINAL.values()),
                          "expect_decks_revision": before.decks_revision}
                if action == "edit":
                    params["row"] = row()
                operation = inventory.Op(f"collection.{action}", params)
                with self.assertRaises(ops_collection.DemandChanged):
                    operation.run(changed)
                after, _ = operation.run(before)
                self.assertEqual(ops_collection.rows_of(changed.collection("home")), self.rows()["rows"])
                expected = "3" if action == "edit" else None
                actual = after.collection("home").rows[0].text("quantity") if after.collection("home").rows else None
                self.assertEqual(actual, expected)


class PgReductionApiTests(db_support.DbTestCase):
    """Real transaction/audit coverage, isolated by DbTestCase's throwaway database."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        _write(self.box.root / "config.json", json.dumps(collection_tests.ROLES))
        prepare(self.box)
        patcher = mock.patch.object(config, "REPO", self.box.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        pg.write_model(adapt(self.box.inventory.load()), CLAUDE, "Import reduction fixtures",
                       contents=import_contents(self.box.root), dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def call(self, **payload):
        return ce.save_card(json.dumps({"profile": "matt", "space": "home", **payload}).encode("utf-8"))

    def payload(self):
        return {"action": "edit", "original": ORIGINAL, "row": row(),
                "sha256": ce.rows_view()["sha256"], "reason": "Traded"}

    def challenge(self, payload):
        with self.assertRaises(ce.ApiError) as caught:
            self.call(**payload)
        self.assertEqual(caught.exception.status, 409)
        return caught.exception.extra

    def trail(self):
        with self.connect() as conn:
            return conn.execute("select actor, source, message, reason from audit.change_set order by id").fetchall()

    def test_confirmed_reduction_is_one_audited_change_with_its_reason(self):
        payload = self.payload()
        count = len(self.trail())
        warning = self.challenge(payload)
        self.assertEqual(len(self.trail()), count)
        answer = self.call(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertEqual(answer["rows"][0]["quantity"], "3")
        self.assertEqual(len(self.trail()), count + 1)
        self.assertEqual(self.trail()[-1], ("matt", "web", "edit card Llanowar Elves (FDN 227) in the home collection", "Traded"))

    def test_a_deck_change_between_review_and_write_requires_another_review(self):
        payload = self.payload()
        warning = self.challenge(payload)
        real = self.backend.apply
        kind = "test.collection_reduction.deck_race"

        @inventory.register(kind)
        def change_deck(inv):
            deck = inv.deck("casual/gruul-test")
            updated = deck.replace(text=held_text(5))
            return inv.replace(decks={**inv.decks, deck.id: updated}), inventory.Summary("Change fixture deck")

        self.addCleanup(inventory.unregister, kind)

        def concurrent(op, actor, message, **kwargs):
            before = self.backend.load()
            real(inventory.Op(kind), MATT, "Change fixture deck")
            changed = self.backend.load()
            self.assertEqual(before.revision, changed.revision)
            self.assertNotEqual(before.decks_revision, changed.decks_revision)
            return real(op, actor, message, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=concurrent):
            with self.assertRaises(ce.ApiError) as caught:
                self.call(**payload, confirm_in_use=warning["confirm_in_use"])
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(ce.rows_view()["rows"][0]["quantity"], "4")
