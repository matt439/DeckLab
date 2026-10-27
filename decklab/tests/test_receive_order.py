"""Receipts: lib/inventory/receive.py's operation on the files backend and on the database
backend (the same receipt gives the same inventory on both) and the token rules receipts
share. Disposable trees and the fixture card data only; the database tests run in a throwaway
database (they skip without one)."""
import io
import json
import unittest

from decklab.lib import inventory
from decklab.lib.inventory import files, receive, rules
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state import Actor, Conflict, Invalid
from decklab.tests import db_support, test_pool as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule

TESTER = Actor("test", "Tester", None, "test")
TOKEN_ROW = dict(front="Rabbit", back="Rabbit", set="tblb", front_collector_number="8", back_collector_number="8",
                 finish="nonfoil", quantity="2", front_details="1/1", back_details="1/1", notes="")


def cards_in(path, existing=False):
    return rules.parse_cards(io.StringIO(path.read_text(encoding="utf-8"), newline=""), path.name, existing=existing)


def write_record(t, components, ordered_on="2026-10-01", order_id="test"):
    record = {"version": 1, "id": order_id, "seller": "Fixture shop", "ordered_on": ordered_on,
              "sources": ["magic/buylists/test.md"], "notes": "", "components": components}
    (t.magic / f"orders/records/{order_id}.json").write_bytes(rules.json_bytes(record))
    return record


def write_tokens(t, rel, **changes):
    row = dict(TOKEN_ROW, **changes)
    (t.magic / rel).parent.mkdir(parents=True, exist_ok=True)
    (t.magic / rel).write_bytes(rules.csv_bytes([row], rules.TOKEN_FIELDS))


def receipt_tree(t):
    """A cards order with a pending tokens component, an ordered product, and a deck that wants
    the cards (the database tests import it; the files tests build it in setUp)."""
    for folder in ("orders/records", "orders/tokens", "buylists"):
        (t.magic / folder).mkdir(parents=True, exist_ok=True)
    t.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
    t.cards_csv("orders/test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
    write_tokens(t, "orders/tokens/test.csv")
    t.cards_csv("products/kit.csv", ("Pick Your Poison", "mkm", "170", "nonfoil", 1), ("Forest", "fdn", "", "nonfoil", 9))
    t.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\nkit.csv,ordered,,,,\n")
    write_record(t, [
        {"id": "cards", "kind": "cards", "path": "magic/orders/test.csv", "status": "pending", "received_on": "",
         "checks": ["Record the condition"]},
        {"id": "tokens", "kind": "tokens", "path": "magic/orders/tokens/test.csv", "status": "pending",
         "received_on": "", "checks": ["Check physical pairs"]},
        {"id": "kit", "kind": "product", "path": "magic/products/kit.csv", "status": "pending", "received_on": "",
         "checks": ["Record the product's tokens"]}])
    t.deck("test", "Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
           table="| Llanowar Elves | 2 | 0 | **2** | | | keep hand note |\n| **Total** | | | **2** | | | |\n")
    t.write("buylists/test.md", "[Order](../orders/test.csv)\n")


class ReceiptTests(support.PoolTestCase):
    """The operation on the files backend (PoolTestCase's FileInventory over its tree)."""

    def setUp(self):
        super().setUp()
        for folder in ("orders/records", "orders/tokens", "buylists"):
            (self.magic / folder).mkdir()
        self.cards_csv("orders/test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.components = [{"id": "cards", "kind": "cards", "path": "magic/orders/test.csv",
                            "status": "pending", "received_on": "", "checks": []}]
        self.record()
        self.deck("test", "Test", "idea", "Deck\n2 Llanowar Elves (FDN) 227\n58 Forest\n",
                  table="| Llanowar Elves | 2 | 0 | **2** | | | keep hand note |\n"
                        "| **Total** | | | **2** | | | |\n")
        self.write("buylists/test.md", "[Order](../orders/test.csv)\n")

    def record(self, ordered_on="2026-10-01"):
        self.manifest = write_record(self, self.components, ordered_on)
        self.record_path = self.magic / "orders/records/test.json"

    def op(self, *inputs, date="2026-10-08", wording="cli"):
        inputs = inputs or tuple({"id": c["id"], "verified": True} for c in self.components
                                 if c["status"] == "pending")
        return receive.op("test", list(inputs), date, wording)

    def receive(self, *inputs, date="2026-10-08"):
        return inventory.apply(self.op(*inputs, date=date), TESTER, "receive test")

    def tree(self):
        return {rel: data for rel, data in files.tree_files(self.magic.parent).items()}

    def collection(self):
        return {(r["name"], r["set"]): r for r in cards_in(self.magic / "collection.csv", existing=True)}

    def token_component(self, **changes):
        write_tokens(self, "orders/tokens/test.csv", **changes)
        self.components.append({"id": "tokens", "kind": "tokens", "path": "magic/orders/tokens/test.csv",
                                "status": "pending", "received_on": "", "checks": ["Check physical pairs"]})
        self.record()

    def test_a_preview_changes_nothing_and_the_receipt_merges_moves_and_records(self):
        before = self.tree()
        after, summary = inventory.preview(self.op())
        self.assertEqual(self.tree(), before)
        self.assertFalse(after.persisted)
        # The receipt refreshes the deck tables in the same change (registered with refresh=True),
        # so the preview names the deck file too.
        self.assertEqual(inventory.changed_paths(inventory.current(), after),
                         ["magic/collection.csv", "magic/decks/casual/test.md", "magic/orders/received/test.csv",
                          "magic/orders/records/test.json", "magic/orders/test.csv"])
        self.assertEqual(summary.extra["tables"], {"written": [{"id": "casual/test", "title": "Test"}],
                                                   "skipped": [], "error": None})
        self.assertEqual(summary.extra["totals"], [["playable cards", {"cards": 2, "added_rows": 1, "bumped_rows": 0,
                                                                         "skipped_basics": 0}]])
        unrefreshed, _ = inventory.preview(self.op(), refresh=False)
        self.assertNotIn("magic/decks/casual/test.md", inventory.changed_paths(inventory.current(), unrefreshed))
        self.receive()
        self.assertEqual(self.collection()[("Llanowar Elves", "fdn")]["quantity"], "2")
        self.assertFalse((self.magic / "orders/test.csv").exists())
        self.assertTrue((self.magic / "orders/received/test.csv").exists())
        record = json.loads(self.record_path.read_text())
        self.assertEqual(record["components"][0], {"id": "cards", "kind": "cards",
                                                   "path": "magic/orders/received/test.csv", "status": "received",
                                                   "received_on": "2026-10-08", "checks": []})
        self.assertIn("../orders/test.csv", (self.magic / "buylists/test.md").read_text())   # links aren't repaired
        with self.assertRaisesRegex(Invalid, "already received"):
            self.receive({"id": "cards", "verified": True})
        with self.assertRaisesRegex(Invalid, "No pending components selected"):
            inventory.preview(receive.op("test", [], "2026-10-08"))
        with self.assertRaisesRegex(Invalid, "No pending components selected"):
            inventory.preview(receive.op("test", [{"id": "nope", "verified": True}], "2026-10-08"))

    def test_a_partial_shipment_receives_the_cards_and_keeps_unverified_tokens_pending(self):
        self.token_component()
        before_tokens = (self.magic / "orders/tokens/test.csv").read_bytes()
        unverified = self.op({"id": "cards", "verified": True}, {"id": "tokens", "verified": False})
        self.assertEqual(receive.blockers(inventory.current(), unverified),
                         ["tokens: resolve checks/edit received facts, then --verified tokens"])
        web = receive.op("test", [{"id": "tokens", "verified": False}], "2026-10-08")
        self.assertEqual(receive.blockers(inventory.current(), web),
                         ["tokens: inspect it, record the actual received facts, then confirm you did"])
        with self.assertRaisesRegex(Invalid, "Complete these first: tokens"):
            inventory.preview(unverified)
        self.receive({"id": "cards", "verified": False})
        record = json.loads(self.record_path.read_text())
        self.assertEqual([item["status"] for item in record["components"]], ["received", "pending"])
        self.assertEqual((self.magic / "orders/tokens/test.csv").read_bytes(), before_tokens)
        self.assertFalse((self.magic / "tokens.csv").exists())

    def test_a_receipt_keeps_the_received_copy_notes_on_an_existing_printing(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
        rows = [dict(r, notes="Received copy has a small corner mark") for r in cards_in(self.magic / "orders/test.csv")]
        self.receive({"id": "cards", "verified": True, "rows": rows})
        row = self.collection()[("Llanowar Elves", "fdn")]
        self.assertEqual((row["quantity"], row["notes"]), ("3", "Received copy has a small corner mark"))

    def test_paired_tokens_count_physical_cards_once_and_move_separately(self):
        self.token_component()
        self.write("tokens.csv", ",".join(rules.TOKEN_FIELDS) + "\n" + ",".join(dict(TOKEN_ROW, quantity="1").values())
                   + "\n")
        self.receive()
        rows = list(inventory.current().token_set().rows)
        self.assertEqual([(r.front, r.back, r.quantity) for r in rows], [("Rabbit", "Rabbit", "3")])
        self.assertEqual(rows[0].id, 1)                                  # the existing row, bumped
        self.assertTrue((self.magic / "orders/tokens/received/test.csv").exists())
        item = json.loads(self.record_path.read_text())["components"][1]
        self.assertEqual((item["path"], item["checks"], item["verified_checks"]),
                         ("magic/orders/tokens/received/test.csv", [], ["Check physical pairs"]))

    def test_verifying_cant_turn_an_unknown_reverse_into_a_single_sided_card(self):
        self.token_component(back="", back_collector_number="", back_details="", notes="reverse face unconfirmed")
        before = self.tree()
        with self.assertRaisesRegex(Invalid, "edit the CSV"):
            self.receive({"id": "cards", "verified": True}, {"id": "tokens", "verified": True})
        self.assertEqual(self.tree(), before)
        row = dict(TOKEN_ROW, back="", back_collector_number="", back_details="", notes="")
        with self.assertRaisesRegex(Invalid, "single-sided verified"):
            self.receive({"id": "tokens", "verified": True, "rows": [row]})
        self.receive({"id": "tokens", "verified": True, "rows": [dict(row, notes="single-sided verified")]})
        self.assertEqual(inventory.current().token_set().rows[0].back, "")
        kept = (self.magic / "orders/tokens/received/test.csv").read_text(encoding="utf-8")
        self.assertIn("single-sided verified", kept)                   # the received facts are kept

    def test_a_face_typed_with_its_traits_is_refused_at_receipt(self):
        self.token_component()
        from unittest import mock
        from decklab.lib import cards
        from decklab.lib.tokens import names
        known = {"rabbit": "Rabbit", "angel": "Angel"}
        with mock.patch.object(names, "_ready", lambda: True), \
                mock.patch.object(cards, "token_face", lambda n: known.get(n.lower())), \
                mock.patch.object(cards, "token_face_names", lambda: sorted(known.values())), \
                mock.patch.object(names, "_printing_problem", lambda row, side: None):
            before = self.tree()
            with self.assertRaisesRegex(Invalid, "'White Angel 4/4 flying' isn't a token.*go in its details"):
                self.receive({"id": "tokens", "verified": True,
                              "rows": [dict(TOKEN_ROW, back="White Angel 4/4 flying", back_collector_number="")]})
            self.assertEqual(self.tree(), before)
            self.receive({"id": "tokens", "verified": True,
                          "rows": [dict(TOKEN_ROW, back="angel", back_collector_number="",
                                        back_details="4/4; white; flying")]})
        self.assertEqual([(r.front, r.back) for r in inventory.current().token_set().rows], [("Rabbit", "Angel")])

    def test_a_bad_token_row_is_named_by_the_line_it_starts_on_in_the_payload(self):
        self.token_component()
        header = ",".join(rules.TOKEN_FIELDS)
        good = rules.csv_bytes([dict(TOKEN_ROW, quantity="1", notes="two\nlines")], rules.TOKEN_FIELDS)
        bad = rules.csv_bytes([dict(TOKEN_ROW, quantity="1", set="BAD")], rules.TOKEN_FIELDS)
        # The header, a row whose notes span lines 2-3, two blank lines, then the bad row.
        text = good.decode("utf-8") + "\n\n" + bad.decode("utf-8").split("\n", 1)[1]
        self.assertTrue(text.startswith(header))
        (self.magic / "orders/tokens/test.csv").write_bytes(text.encode("utf-8"))
        with self.assertRaisesRegex(Invalid, r"^magic/orders/tokens/test.csv line 6: invalid lowercase token set"):
            self.receive({"id": "tokens", "verified": True})
        # Rows given at receipt have no file lines: the rendered rows' are named.
        with self.assertRaisesRegex(Invalid, r"^magic/orders/tokens/test.csv line 4: invalid lowercase token set"):
            self.receive({"id": "tokens", "verified": True,
                          "rows": [dict(TOKEN_ROW, quantity="1", notes="two\nlines"),
                                   dict(TOKEN_ROW, quantity="1", set="BAD")]})

    def test_unidentified_token_printings_dont_merge_unrelated_markers(self):
        row = dict(TOKEN_ROW, set="", front_collector_number="", back_collector_number="")
        merged, counts = rules.merge_tokens([row], [row])
        self.assertEqual((len(merged), counts["cards"]), (2, 2))

    def test_a_product_needs_an_intact_choice_and_leaves_out_plain_basics(self):
        (self.magic / "orders/test.csv").unlink()
        self.cards_csv("products/test.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2),
                       ("Forest", "fdn", "", "nonfoil", 10))
        self.status(("test.csv", "ordered", ""))
        self.components[0].update(id="product-test", kind="product", path="magic/products/test.csv",
                                  checks=["Record physical product tokens after opening"])
        self.record()
        self.assertEqual(receive.blockers(inventory.current(), self.op({"id": "product-test", "verified": False})),
                         ["product-test: specify --intact yes or --intact no"])
        _, summary = self.receive({"id": "product-test", "verified": False, "intact": "no"})
        self.assertEqual(summary.extra["totals"][0][1]["skipped_basics"], 10)
        self.assertIn("test.csv,owned,no,,,Received 2026-10-08", (self.magic / "products/status.csv").read_text())
        self.assertTrue((self.magic / "products/test.csv").exists())
        self.assertEqual(self.collection()[("Llanowar Elves", "fdn")]["quantity"], "2")
        item = json.loads(self.record_path.read_text())["components"][0]
        self.assertEqual(item["checks"], ["Record physical product tokens after opening"])
        self.assertNotIn("verified_checks", item)

    def test_a_product_receipt_upgrades_a_legacy_status_and_clears_the_kit_when_broken_up(self):
        (self.magic / "orders/test.csv").unlink()
        self.product("test.csv", ("Deck", "Llanowar Elves", 2), column="section")
        self.product("kept.csv", ("Deck", "Llanowar Elves", 1), column="section")
        self.components[0].update(id="product-test", kind="product", path="magic/products/test.csv")
        self.record()
        self.status(("kept.csv", "owned", "yes"), ("test.csv", "ordered", ""))
        after, _ = inventory.preview(self.op({"id": "product-test", "verified": False, "intact": "yes"}))
        self.assertTrue(files.render_sheet(after.status).startswith(b"file,status,intact,sleeves,deck_box,notes,token_cards\n"))
        self.write("products/status.csv", "file,status,intact,sleeves,deck_box,notes\n"
                                          "kept.csv,owned,yes,red,,\ntest.csv,ordered,,blue,blue box,\n")
        self.receive({"id": "product-test", "verified": False, "intact": "no"})
        rows = [r.as_dict() for r in inventory.current().status_rows]
        self.assertEqual([(r["file"], r["status"], r["intact"], r["sleeves"], r["deck_box"]) for r in rows],
                         [("kept.csv", "owned", "yes", "red", ""), ("test.csv", "owned", "no", "", "")])

    def test_a_product_must_be_ordered_or_preordered(self):
        (self.magic / "orders/test.csv").unlink()
        self.product("test.csv", ("Deck", "Llanowar Elves", 2), column="section")
        self.components[0].update(id="product-test", kind="product", path="magic/products/test.csv")
        self.record()
        self.status(("test.csv", "owned", "no"))
        with self.assertRaisesRegex(Invalid, "product status must be ordered or preordered"):
            self.receive({"id": "product-test", "verified": False, "intact": "no"})

    def test_edited_rows_keep_names_totals_and_real_printings(self):
        rows = cards_in(self.magic / "orders/test.csv")
        for field, value, words in (("collector_number", "99999", "printing does not match"),
                                    ("quantity", "1", "Receive a whole component"),
                                    ("name", "Elvish Mystic", "Card names and total copies"),
                                    ("finish", "etched", "finish is not available")):
            with self.subTest(field=field), self.assertRaisesRegex(Invalid, words):
                self.receive({"id": "cards", "verified": True, "rows": [dict(rows[0], **{field: value})]})
        with self.assertRaisesRegex(Invalid, "exactly the component's CSV fields"):
            self.receive({"id": "cards", "verified": True, "rows": [{"name": "Llanowar Elves", "quantity": "2"}]})
        self.assertNotIn(("Llanowar Elves", "fdn"), self.collection())
        self.receive({"id": "cards", "verified": True, "rows": [dict(rows[0], condition="", language="")]})
        row = self.collection()[("Llanowar Elves", "fdn")]
        self.assertEqual((row["condition"], row["language"]), ("", ""))     # never assumed NM or English

    def test_bad_paths_cancelled_components_and_existing_archives_are_refused(self):
        for path, words in (("../outside.csv", "file location"), ("magic/collection.csv", "file location"),
                            ("magic/orders/received/test.csv", "file location"),
                            ("magic/orders/gone.csv", "does not exist")):
            with self.subTest(path=path):
                self.components[0]["path"] = path
                self.record()
                with self.assertRaisesRegex(Invalid, words):
                    self.receive()
        (self.magic / "orders/cancelled").mkdir()
        (self.magic / "orders/test.csv").rename(self.magic / "orders/cancelled/test.csv")
        self.components[0].update(path="magic/orders/cancelled/test.csv", status="cancelled")
        self.record()
        with self.assertRaisesRegex(Invalid, "already cancelled"):
            self.receive({"id": "cards", "verified": True})
        (self.magic / "orders/cancelled/test.csv").rename(self.magic / "orders/test.csv")
        self.components[0].update(path="magic/orders/test.csv", status="pending")
        self.record()
        self.cards_csv("orders/received/test.csv", ("Opt", "dom", "60", "nonfoil", 1))
        with self.assertRaisesRegex(Invalid, "Archive already exists: magic/orders/received/test.csv"):
            self.receive()

    def test_a_payload_another_record_names_is_refused(self):
        write_record(self, [dict(self.components[0], id="other")], order_id="other")
        with self.assertRaisesRegex(Invalid, "test.json: cards: component file occurs in more than one order"):
            self.receive()
        # A product's reference list too, although a product's file never moves.
        (self.magic / "orders/records/other.json").unlink()
        self.product("test.csv", ("Deck", "Llanowar Elves", 2), column="section")
        self.status(("test.csv", "ordered", ""))
        product = {"id": "kit", "kind": "product", "path": "magic/products/test.csv", "status": "pending",
                   "received_on": "", "checks": []}
        self.components.append(product)
        self.record()
        write_record(self, [dict(product, id="other")], order_id="other")
        with self.assertRaisesRegex(Invalid, "test.json: kit: component file occurs in more than one order"):
            self.receive({"id": "kit", "verified": False, "intact": "no"})

    def test_sources_and_audit_notes_follow_the_records_rules(self):
        for changes, words in (({"sources": "magic/buylists/test.md"}, "sources: expected a list"),
                               ({"sources": ["../outside.md"]}, "sources: expected a relative repository path"),
                               ({"sources": ["magic\\buylists\\test.md"]}, "expected a relative repository path"),
                               ({"sources": [""]}, "expected a relative repository path"),
                               ({"sources": [1]}, "sources: expected single-line text"),
                               ({"audit_notes": ["x"]}, "audit_notes: expected single-line text")):
            with self.subTest(changes=changes):
                self.record_path.write_bytes(rules.json_bytes(dict(self.manifest, **changes)))
                with self.assertRaisesRegex(Invalid, words):
                    self.receive()
        self.record_path.write_bytes(rules.json_bytes(dict(self.manifest, sources=["magic/buylists/gone.md"],
                                                           audit_notes="Migrated from Git")))
        self.receive()                      # a source's file is the docs' business (purchases --check)

    def test_dates_before_the_order_and_noncanonical_dates_are_refused(self):
        for value, words in (("2026-09-30", "before the order date"), ("20261008", "YYYY-MM-DD"),
                             ("2026-02-30", "day")):
            with self.subTest(value=value), self.assertRaisesRegex(Invalid, words):
                self.receive(date=value)

    def test_records_with_duplicate_keys_or_a_boolean_version_are_refused(self):
        for text, words in (('{"version": 1, "version": 1}', "duplicate JSON key"),
                            ('{"version": true}', "expected order record version 1")):
            with self.subTest(text=text):
                self.record_path.write_text(text)
                with self.assertRaisesRegex(Invalid, words):
                    self.receive({"id": "cards", "verified": True})
        with self.assertRaisesRegex(Invalid, "No order record for nope"):
            inventory.preview(receive.op("nope", [{"id": "cards", "verified": True}], "2026-10-08"))

    def test_the_delivery_view_lists_every_component_with_its_rows(self):
        self.token_component()
        view = receive.delivery(inventory.current(), "test")
        self.assertEqual((view["order"], view["seller"], view["ordered_on"]), ("test", "Fixture shop", "2026-10-01"))
        self.assertEqual(view["components"][0]["fields"], rules.FIELDS)
        self.assertEqual(view["components"][0]["rows"][0]["name"], "Llanowar Elves")
        self.assertEqual(view["components"][1]["rows"], [TOKEN_ROW])
        self.write("orders/test.csv", "name,quantity\nLlanowar Elves,2\n")
        with self.assertRaisesRegex(Invalid, "expected columns"):
            receive.delivery(inventory.current(), "test")


def _old_merge_tokens(existing, incoming):
    """merge_tokens as it was before its rules became named helpers, kept to
    prove the refactor changed nothing."""
    import re
    rows = [dict(row) for row in existing]
    added = bumped = quantity = 0
    identity = lambda row: tuple(row[key] for key in rules.TOKEN_FIELDS if key not in ("quantity", "notes"))
    for row in incoming:
        def uncertain(candidate):
            return re.search(r"\b(?:unconfirmed|unknown|unspecified)\b", " ".join(
                candidate[key] for key in ("notes", "front_details", "back_details")), re.I)
        known = (all(row[key] for key in ("set", "front_collector_number", "finish")) and (
            not row["back"] or bool(row["back_collector_number"])) and not uncertain(row))
        old = next((old for old in rows if known and identity(old) == identity(row)
                    and not uncertain(old)), None)
        if old is None:
            rows.append(dict(row))
            added += 1
        else:
            old["quantity"] = str(int(old["quantity"]) + int(row["quantity"]))
            if row["notes"] and row["notes"] not in old["notes"]:
                old["notes"] = "; ".join(filter(None, (old["notes"], row["notes"])))
            bumped += 1
        quantity += int(row["quantity"])
    rows.sort(key=lambda row: tuple(row[key] for key in (
        "set", "front_collector_number", "back_collector_number", "front", "back",
        "front_details", "back_details", "finish")))
    return rows, {"cards": quantity, "added_rows": added, "bumped_rows": bumped}


def _token(**values):
    row = {key: "" for key in rules.TOKEN_FIELDS}
    row.update(quantity="1")
    row.update(values)
    return row


class TokenHelperTests(unittest.TestCase):
    """The tokens.csv and status.csv rules receipts and Deck Lab's Tokens page share (rules.py)."""

    ROWS = [
        _token(front="Rabbit", back="Rabbit", set="tblb", front_collector_number="8",
               back_collector_number="8", finish="nonfoil", quantity="2", front_details="1/1", back_details="1/1"),
        _token(front="Rabbit", back="Rabbit", set="tblb", front_collector_number="8",
               back_collector_number="8", finish="nonfoil", quantity="1", front_details="1/1",
               back_details="1/1", notes="second copy"),
        _token(front="Dog", back="Beast", quantity="1", back_details="3/3",
               notes="User-reported owned; unspecified characteristics and printing unconfirmed"),
        _token(front="Dog", back="Beast", quantity="2", back_details="3/3",
               notes="User-reported owned; unspecified characteristics and printing unconfirmed"),
        _token(front="Goblin", quantity="1", front_details="1/1; printed pink (not a Magic colour)",
               notes="single-sided verified (back is a manacat.com.au advertisement)"),
        _token(front="Insect", back="Goblin", set="ttdc", front_collector_number="23", finish="nonfoil",
               front_details="colour unknown"),
        _token(front="The Monarch", set="tcmm", front_collector_number="1", finish="foil"),
        _token(front="Zombie", back="Faerie", set="tclb", front_collector_number="5", finish="nonfoil"),
    ]

    def test_known_equal_rows_merge_and_uncertain_ones_stay_apart(self):
        merged, counts = rules.merge_tokens([self.ROWS[0], self.ROWS[2]], [self.ROWS[1], self.ROWS[2]])
        self.assertEqual([(r["front"], r["quantity"]) for r in merged], [("Dog", "1"), ("Dog", "1"), ("Rabbit", "3")])
        self.assertEqual(merged[2]["notes"], "second copy")
        self.assertEqual(counts, {"cards": 2, "added_rows": 1, "bumped_rows": 1})

    def test_merge_tokens_output_is_unchanged(self):
        existing = [self.ROWS[0], self.ROWS[2], self.ROWS[4], self.ROWS[5]]
        for incoming in ([], self.ROWS, self.ROWS[1:2], self.ROWS[3:4], list(reversed(self.ROWS)),
                         [dict(self.ROWS[6], notes="x")] * 2):
            with self.subTest(incoming=[r["front"] for r in incoming]):
                self.assertEqual(rules.merge_tokens(existing, incoming), _old_merge_tokens(existing, incoming))

    def test_identity_known_and_uncertain(self):
        rabbit, second = self.ROWS[0], self.ROWS[1]
        self.assertEqual(rules.token_identity(rabbit), rules.token_identity(second))
        self.assertNotIn("2", rules.token_identity(rabbit))
        self.assertTrue(rules.token_known(rabbit))
        self.assertFalse(rules.token_uncertain(rabbit))
        self.assertTrue(rules.token_uncertain(self.ROWS[2]))          # notes count
        self.assertTrue(rules.token_uncertain(self.ROWS[5]))          # details count
        self.assertFalse(rules.token_known(self.ROWS[5]))
        self.assertFalse(rules.token_known(self.ROWS[7]))             # a back without its number
        self.assertTrue(rules.token_known(self.ROWS[6]))              # single-sided
        self.assertFalse(rules.token_uncertain(_token(front="Unknownling")))    # whole words only

    def test_sort_key_orders_by_printing_then_names(self):
        rows = sorted(self.ROWS, key=rules.token_sort_key)
        self.assertEqual([r["front"] for r in rows],
                         ["Dog", "Dog", "Goblin", "Rabbit", "Rabbit", "Zombie", "The Monarch", "Insect"])

    def test_validate_token_row_rules(self):
        self.assertIsNone(rules.validate_token_row(self.ROWS[4], "here"))
        self.assertIsNone(rules.validate_token_row(self.ROWS[4], "here", incoming=True))
        bad = [({"front": ""}, "front name"), ({"quantity": "0"}, "positive"), ({"quantity": "1.5"}, "positive"),
               ({"finish": "shiny"}, "finish"), ({"set": "TBLB"}, "lowercase token set"),
               ({"back": " Rabbit"}, "invalid token back"), ({"front": "A\nB"}, "invalid token front"),
               ({"front_collector_number": "1 2"}, "collector number")]
        for change, words in bad:
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, f"^here: .*{words}"):
                rules.validate_token_row({**self.ROWS[0], **change}, "here")
        with self.assertRaisesRegex(ValueError, "single-sided verified"):
            rules.validate_token_row(self.ROWS[6], "here", incoming=True)
        rules.validate_token_row(self.ROWS[6], "here")                # only an incoming row needs the note
        with self.assertRaisesRegex(ValueError, "edit the CSV"):
            rules.validate_token_row(dict(self.ROWS[0], notes="check physical pairing"), "here", incoming=True)

    def test_record_lines_count_quoted_newlines_and_skip_blank_lines(self):
        rows = [dict(self.ROWS[0], notes="two\nlines"), self.ROWS[4], dict(self.ROWS[2], quantity="0")]
        text = rules.csv_bytes(rows, rules.TOKEN_FIELDS).decode("utf-8")      # the notes span lines 2-3
        self.assertEqual(rules.record_lines(io.StringIO(text, newline="")), [2, 4, 5])
        self.assertEqual(rules.record_lines(io.StringIO(text + "\n" + text.split("\n", 1)[1], newline="")),
                         [2, 4, 5, 7, 9, 10])

    def test_status_reader_accepts_only_the_legacy_or_current_columns(self):
        self.assertEqual(rules.parse_status("file,status,intact,sleeves,deck_box,notes\nx.csv,owned,yes,red,,n\n",
                                            "status.csv")[0]["sleeves"], "red")
        self.assertEqual(rules.parse_status("file,status,intact,notes\nx.csv,owned,yes,n\n", "status.csv"),
                         [{"file": "x.csv", "status": "owned", "intact": "yes", "notes": "n", "sleeves": "",
                           "deck_box": "", "token_cards": ""}])
        with self.assertRaisesRegex(ValueError, "expected columns file,status,intact,sleeves,deck_box,notes"):
            rules.parse_status("file,status,intact,sleeves,notes\nx.csv,owned,yes,red,n\n", "status.csv")


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class ReceiptDatabaseTests(db_support.DbTestCase):
    """The same receipt on the database backend gives the same inventory as on the files backend,
    as one change set, refusing what the files backend refuses."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests import test_inventory_contract as contract
        cls.contract = contract
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        self.case = self.contract.build_tree(receipt_tree)
        self.addCleanup(self.case.doCleanups)
        self.files = self.case.inventory
        pg.write_model(self.files.load(), self.contract.CLAUDE, "Import the inventory",
                       contents=self.contract.import_contents(self.files.root), dbname=self.dbname)
        self.db = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())

    def both(self, operation, actor=TESTER, message="receive test", **kwargs):
        """(files backend's result, database backend's result) of applying operation."""
        out = []
        for backend in (self.files, self.db):
            with inventory.use(backend):
                out.append(inventory.apply(operation, actor, message, **kwargs))
        return out

    def trail(self):
        with self.connect() as c:
            sets = c.execute("select id, actor, source, message from audit.change_set order by id").fetchall()
            rows = c.execute("select change_set_id, table_name, op from audit.row_change order by id").fetchall()
        return [{"actor": s[1], "source": s[2], "message": s[3], "rows": [r[1:] for r in rows if r[0] == s[0]]}
                for s in sets]

    def test_the_same_receipt_gives_the_same_inventory_on_both_backends(self):
        operation = receive.op("test", [{"id": "cards", "verified": True}, {"id": "tokens", "verified": True,
                                         "rows": [dict(TOKEN_ROW, notes="pairing checked")]},
                                        {"id": "kit", "verified": False, "intact": "no"}], "2026-10-08")
        (file_inv, file_summary), (db_inv, db_summary) = self.both(operation, Actor("matt", "Matt", "home", "receipt"))
        self.assertEqual(files.render(db_inv), files.render(file_inv))
        self.assertEqual(db_summary.extra["totals"], file_summary.extra["totals"])
        self.assertEqual(files.render(self.db.load()), files.render(self.files.load()))
        change = self.trail()[-1]
        self.assertEqual((change["actor"], change["source"], change["message"]), ("matt", "receipt", "receive test"))
        self.assertEqual(len(self.trail()), 2)                               # the import, then the receipt
        tables = {table for table, _ in change["rows"]}
        self.assertEqual(tables, {"collection_card", "token_card", "order_component", "order_token_item", "product_status"})

    def test_refusals_are_the_same_and_write_nothing(self):
        for inputs, words in (([{"id": "tokens", "verified": False}], "Complete these first"),
                              ([{"id": "kit", "verified": False}], "Complete these first"),
                              ([{"id": "cards", "verified": True, "rows": [{"name": "x"}]}], "CSV fields")):
            for backend in (self.files, self.db):
                with self.subTest(inputs=inputs, backend=backend.name), inventory.use(backend):
                    with self.assertRaisesRegex(Invalid, words):
                        inventory.apply(receive.op("test", inputs, "2026-10-08"), TESTER, "receive test")
        self.assertEqual(len(self.trail()), 1)

    def test_a_preview_is_refused_at_apply_once_the_inventory_moved(self):
        operation = receive.op("test", [{"id": "cards", "verified": True}], "2026-10-08")
        with inventory.use(self.db):
            seen = inventory.current().revision
            inventory.apply(receive.op("test", [{"id": "kit", "verified": False, "intact": "yes"}], "2026-10-08"),
                            TESTER, "receive the kit")
            with self.assertRaisesRegex(Conflict, "changed since this was previewed"):
                inventory.apply(operation, TESTER, "receive test", expected_revision=seen)
            inventory.apply(operation, TESTER, "receive test", expected_revision=inventory.current().revision)
        self.assertEqual([c["message"] for c in self.trail()[1:]], ["receive the kit", "receive test"])
