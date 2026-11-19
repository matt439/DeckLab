"""Borrower/notes never leave their own space, including public inventory visitors."""
import json
from collections import Counter
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import activity, collection_edit as ce, collection_loans as loans, deck_page, guard
from decklab.lib.api import card_decks, collection, global_search
from decklab.lib.inventory import ops_loans
from decklab.tests import test_collection_edit as support
from decklab.tests.test_loans import facts
from decklab.tests.test_api import _write
from decklab.tests.test_inventory_privacy import R_BUILT


class LoanApiTests(support.CollectionEditTestCase):
    def get(self, function, profile="user2", **params):
        with self.as_(profile):
            return function(**params)

    def lend(self, profile="user2", space="user2", **changes):
        return self.call(loans.lend, profile, space=space, sha256=self.rows(space)["sha256"], row=facts(**changes))

    def test_lend_and_return_are_one_write_each_and_ownership_never_moves(self):
        before = self.rows("user2")
        home = self.rows("home")
        made = self.lend()
        self.assertTrue(made["ok"])
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.rows("user2")["rows"], before["rows"])
        self.assertEqual(self.rows("user2")["sha256"], before["sha256"])
        self.assertEqual(self.rows("home"), home)
        listed = self.get(loans.loans_view, space="user2")
        self.assertEqual(listed["loans"], [made["loan"]])
        self.assertEqual(made["loan"]["borrower"], "User1")
        result = self.call(loans.return_loan, "user2", space="user2", loan_id=made["loan"]["id"], returned_on="2026-11-12")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.writes), 2)
        self.assertEqual(self.get(loans.loans_view, space="user2")["loans"], [])
        self.assertEqual(len(self.get(loans.loans_view, space="user2", include_returned="1")["loans"]), 1)
        self.assertEqual(self.rows("user2")["rows"], before["rows"])

    def test_public_inventory_does_not_publish_loans_to_another_member_or_admin(self):
        made = self.lend()
        for viewer in ("matt", "user1", "user3"):
            with self.subTest(viewer=viewer), mock.patch.object(guard, "public_spaces", return_value=frozenset({"user2"})):
                visible = self.get(ce.rows_view, viewer, space="user2")
                self.assertEqual(visible["space"], "user2")
                with mock.patch.object(ops_loans, "rows_of", side_effect=AssertionError("private loan source read")):
                    self.assertApiError(403, self.get, loans.loans_view, viewer, space="user2", contains="That collection isn't public.")
                self.assertApiError(403, self.call, loans.return_loan, viewer, space="user2",
                                    loan_id=made["loan"]["id"], returned_on="2026-11-12")
                self.assertApiError(403, self.call, loans.lend, viewer, space="user2", sha256="bad", row={})
        self.assertEqual(len(self.writes), 1)

    def test_loan_only_printing_counts_and_filters_clear_after_return(self):
        private = ("PRIVATE BORROWER", "PRIVATE NOTE")
        made = self.lend(borrower=private[0], notes=private[1])["loan"]
        key = "fdn|227|nonfoil"
        name = "Llanowar Elves"
        with self.as_("user2"):
            printing = ce.rows_view("user2")["storage"]
            counts = printing["rows"][key]
            self.assertIsNone(printing["error"])
            self.assertEqual((counts["held"], counts["lent"], counts["guess"]), (0, 1, False))
            self.assertEqual((counts["listed_holders"], counts["unattributed"]), ([], 0))
            self.assertEqual(ce.rows_view("user2")["storage_setup"]["unplaced"], 1)
            for availability in ("free", "lent"):
                row, = collection.collection_view(space="user2", availability=availability)["cards"]
                self.assertEqual((row["name"], row["owned"], row["held"], row["lent"], row["free_now"]),
                                 (name, 2, 0, 1, 1))
                self.assertEqual(row["holders"], [])
            self.assertEqual(collection.collection_view(space="user2", availability="held")["cards"], [])
            viewer = card_decks.card_decks(name, "user2")
            self.assertEqual((viewer["holds"], viewer["wants"], viewer["lent"], viewer["free"]), ([], [], 1, 1))
            found, = global_search.search_view(name, group="collection")["groups"][0]["items"]
            self.assertEqual((found["decks"], found["in_use"], found["lent"], found["free"]), (0, 0, 1, 1))
        broad = json.dumps([printing, row, viewer, found])
        for secret in (*private, made["id"], made["lent_on"]):
            self.assertNotIn(secret, broad)

        self.call(loans.return_loan, "user2", space="user2", loan_id=made["id"], returned_on="2026-11-12")
        with self.as_("user2"):
            rows = ce.rows_view("user2")
            self.assertNotIn(key, rows["storage"]["rows"])
            self.assertEqual(rows["storage_setup"]["unplaced"], 2)
            self.assertEqual(collection.collection_view(space="user2", availability="lent")["cards"], [])
            row, = collection.collection_view(space="user2", availability="free")["cards"]
            self.assertEqual(row["free_now"], 2)
            self.assertNotIn("lent", row)

    def test_mixed_printing_counts_and_storage_fill_exclude_the_loan(self):
        _write(self.box.magic / "people/user2/collection.csv", support.USER2.replace(",2,NM", ",5,NM"))
        text = R_BUILT.replace("- **Played by:** either\n", "").replace(
            "- **Status:** built", "- **Status:** built\n- **Printings in box:** 2 Llanowar Elves (FDN) 227")
        _write(self.box.magic / "people/user2/decks/casual/held.md", text)
        before = self.rows("user2")["storage_setup"]["unplaced"]
        self.lend()
        with self.as_("user2"):
            view = ce.rows_view("user2")
            printing = view["storage"]["rows"]["fdn|227|nonfoil"]
            row, = collection.collection_view(space="user2", availability="held")["cards"]
            self.assertEqual((printing["held"], printing["lent"], printing["recorded"]), (2, 1, 2))
            self.assertEqual((row["held"], row["lent"], row["free_now"]), (2, 1, 2))
            self.assertEqual(row["owned"], row["held"] + row["lent"] + row["free_now"])
            self.assertEqual(view["storage_setup"]["unplaced"], before - 1)

    def test_a_loaned_printing_has_no_room_for_an_uncertain_deck_assignment(self):
        self.lend(quantity="2")
        _write(self.box.magic / "people/user2/collection.csv", support.USER2
               + "Llanowar Elves,fdn,227,foil,2,NM,en,\n"
               + "Llanowar Elves,m19,314,nonfoil,2,NM,en,\n")
        held = pool.InUse("user2/casual/fixture", "Fixture", "built", Counter({"Llanowar Elves": 1}))
        with self.as_("user2"), mock.patch.object(ce.pool, "load_pool", return_value=pool.Pool(
                Counter({"Llanowar Elves": 6}), {}, [held, *ops_loans.holder(inventory.current(), "user2")])):
            storage = ce.rows_view("user2")["storage"]["rows"]
        exact = storage["fdn|227|nonfoil"]
        self.assertEqual((exact["held"], exact["lent"], exact["guess"]), (0, 2, False))
        fallback, = [row for key, row in storage.items() if key != "fdn|227|nonfoil"]
        self.assertEqual((fallback["held"], fallback["guess"], fallback["unattributed"]), (1, True, 1))

    def test_restricted_readers_get_only_existing_collection_permissions(self):
        made = self.lend(borrower="PRIVATE BORROWER", notes="PRIVATE NOTE")["loan"]
        with self.as_("matt"):
            self.assertApiError(403, ce.rows_view, "user2")
            self.assertApiError(403, collection.collection_view, space="user2", availability="lent")
            self.assertApiError(403, card_decks.card_decks, made["name"], "user2")
            with mock.patch.object(guard, "public_spaces", return_value=frozenset({"user2"})):
                rows = ce.rows_view("user2")
                found = collection.collection_view(space="user2", availability="lent")
                viewer = card_decks.card_decks(made["name"], "user2")
                self.assertEqual(rows["storage"]["rows"]["fdn|227|nonfoil"]["lent"], 1)
                self.assertEqual(found["cards"][0]["lent"], 1)
                self.assertEqual(viewer["lent"], 1)
                self.assertApiError(403, loans.loans_view, "user2")
        broad = json.dumps([rows, found, viewer])
        for secret in ("PRIVATE BORROWER", "PRIVATE NOTE", made["id"], made["lent_on"]):
            self.assertNotIn(secret, broad)

    def test_refused_capacity_stale_and_missing_loan_keep_records_and_collection_unchanged(self):
        made = self.lend(quantity="2")
        before = self.rows("user2")
        records = inventory.current().loans
        self.assertApiError(400, self.lend)
        self.assertApiError(409, self.call, loans.lend, "user2", space="user2", sha256="0" * 64, row=facts())
        self.assertApiError(409, self.call, loans.return_loan, "user2", space="user2", loan_id="f" * 32, returned_on="2026-11-12")
        self.assertApiError(400, self.call, loans.return_loan, "user2", space="user2", loan_id=made["loan"]["id"], returned_on="2026-11-10")
        self.assertEqual(self.rows("user2"), before)
        self.assertEqual(inventory.current().loans, records)
        self.assertEqual(len(self.writes), 1)

    def test_activity_loan_rows_are_space_private_and_never_include_borrower_or_notes(self):
        record = {"space_id": "user2", "id": "a" * 32, "name": "Llanowar Elves", "set_code": "fdn",
                  "collector_number": "227", "finish": "nonfoil", "quantity": 1, "borrower": "PRIVATE BORROWER",
                  "notes": "PRIVATE NOTE", "lent_on": "2026-11-11", "returned_on": None}
        change = {"id": 1, "at": "2026-11-11T00:00:00Z", "actor": "user2", "source": "web", "message": "Lent card copies",
                  "reason": None, "rows": [{"table": "card_loan", "op": "INSERT", "key": {"space_id": "user2", "id": "a" * 32},
                                             "before": None, "after": record}]}
        profiles = {row["id"]: row for row in support.ROLES["profiles"]}
        own = activity.visible_change(change, {"space": "user2", "profile": "user2", "system": False}, profiles)
        self.assertIsNotNone(own)
        self.assertNotIn("PRIVATE", json.dumps(own))
        self.assertIsNone(activity.visible_change(change, {"space": "home", "profile": "matt", "system": True}, profiles))

    def test_public_deck_without_inventory_access_is_invariant_under_loans_and_download_has_no_loan_fields(self):
        text = R_BUILT.replace("- **Played by:** either\n", "").replace("**Status:** built", "**Status:** idea")
        _write(self.box.magic / "people/user2/decks/casual/loan-target.md", text)
        self.box.state.visibility_set("user2", "decks", True, support.ce._web_actor({"id": "user2", "name": "User2"}), "Public fixture")
        with self.as_("matt"):
            before = deck_page.deck_view("user2/casual/loan-target")
        self.lend(borrower="PRIVATE BORROWER", notes="PRIVATE NOTE")
        with self.as_("matt"):
            after = deck_page.deck_view("user2/casual/loan-target")
        self.assertEqual(after, before)
        self.assertNotIn("PRIVATE", json.dumps(after))
        self.assertNotIn("lent_out", json.dumps(after))
        with self.as_("user2"):
            download = ce.download_view("user2")
        self.assertNotIn("PRIVATE", str(download))

    def test_home_member_can_record_a_loan_and_return_in_the_shared_space(self):
        _write(self.box.magic / "collection.csv", support.USER2)
        supply = pool.Pool(Counter({"Llanowar Elves": 2}), {}, [], space="home")
        with mock.patch.object(ops_loans.pool, "for_space", return_value=supply):
            made = self.lend(profile="user1", space="home")
        self.assertTrue(made["ok"])
        result = self.call(loans.return_loan, "user1", space="home", loan_id=made["loan"]["id"], returned_on="2026-11-12")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.writes), 2)
