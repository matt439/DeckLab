"""Pure fulfilment provenance tests: no database, personal data or card index is needed."""
import unittest

from decklab.lib.inventory import order_fulfilment as ledger, rules
from decklab.lib.inventory.model import Component, Inventory, Order, Product, ProductItem, QUEUE_FIELDS, WatchRow
from decklab.lib.state import Invalid


def card(name="Elvish Mystic", qty=1, set_code="cmm", number="648", **values):
    row = {k: "" for k in rules.FIELDS}
    row.update(name=name, set=set_code, collector_number=number, finish="nonfoil", quantity=str(qty))
    row.update(values)
    return row


def token(front="Rabbit", qty=1, back="Food", **values):
    row = {k: "" for k in rules.TOKEN_FIELDS}
    row.update(front=front, back=back, set="tfin", front_collector_number="1", back_collector_number="2",
               finish="nonfoil", quantity=str(qty))
    row.update(values)
    return row


def queue(name="Elvish Mystic", qty=1, **values):
    row = {k: "" for k in QUEUE_FIELDS}
    row.update(name=name, quantity=str(qty), printing="any", state="ready")
    row.update(values)
    return row


def snapshot(queued=(), cards=(), tokens=(), products=(), notes=None):
    components = []
    if cards:
        components.append(Component.build("cards", "cards", "2026-10-15-test.csv"))
    if tokens:
        components.append(Component.build("tokens", "tokens", "2026-10-15-test.csv"))
    if products:
        components.append(Component.build("product", "product", "precon.csv"))
    order = Order.build("2026-10-15-test", components=components, audit_notes=notes)
    inv = Inventory("pure-fixture").with_watchlist(queued).with_order(order)
    if cards:
        inv = inv.set_component_rows(order.id, "cards", cards)
    if tokens:
        inv = inv.set_component_rows(order.id, "tokens", tokens)
    if products:
        columns = tuple(products[0])
        product = Product("precon", columns, tuple(ProductItem.make(row, columns) for row in products))
        inv = inv.with_product(product)
    return inv, order


def recorded(queued=(), cards=(), tokens=(), products=(), fulfils=None, notes=None):
    inv, order = snapshot(queued, cards, tokens, products, notes)
    if fulfils is None:
        fulfils = [{"select": f"#{i + 1}", "quantity": None} for i in range(len(queued))]
    order = ledger.record(inv, inv, order, fulfils)
    return inv.with_order(order), order


def row_dicts(inv):
    return [{k: row.text(k) for k in QUEUE_FIELDS} for row in inv.watchlist.rows]


class FulfilmentLedgerTests(unittest.TestCase):
    def test_unknown_old_order_is_never_inferred_from_names_or_prose(self):
        inv, order = snapshot([], [card(qty=3)], notes="Fulfilled 3 Elvish Mystic for Elves")
        self.assertIsNone(ledger.read(order))
        after, same, info = ledger.restore(inv, order, ["cards"])
        self.assertEqual((after, same), (inv, order))
        self.assertFalse(info["known"])
        self.assertEqual(info["offered"], [])
        self.assertTrue(info["warnings"])

    def test_new_empty_ledger_is_known_and_single_line(self):
        inv, order = recorded([], [card()], notes="Human delivery prose")
        self.assertEqual(ledger.read(order), {"claims": [], "consumed": [], "warnings": []})
        self.assertNotIn("\n", order.audit_notes)
        self.assertTrue(order.audit_notes.endswith(" Human delivery prose"))
        self.assertEqual(ledger.write(order, ledger.read(order)), order)
        _, _, info = ledger.restore(inv, order, ["cards"])
        self.assertTrue(info["known"])

    def test_only_intent_is_captured_without_market_references(self):
        q = queue(qty=4, listed_aud="0.50", listed_at="A shop", in_stock="yes", checked="2026-10-15",
                  notes="For the next build", source="magic/buylists/old.md", **{"for": "Elves"})
        _, order = recorded([q], [card(qty=2)], fulfils=[{"select": "#1", "quantity": 2}])
        claim = ledger.read(order)["claims"][0]
        self.assertEqual(claim["quantity"], 2)
        self.assertEqual(set(claim["intent"]), set(ledger.INTENT_FIELDS))
        self.assertEqual(claim["intent"]["notes"], q["notes"])
        self.assertFalse(set(ledger.MARKET_FIELDS) & set(claim["intent"]))
        self.assertNotIn("A shop", order.audit_notes)
        self.assertNotIn("0.50", order.audit_notes)

    def test_exact_request_allocated_first_even_when_any_requested_first(self):
        exact = queue(qty=2, printing="exact", set="cmm", collector_number="648", finish="nonfoil",
                      **{"for": "Exact deck"})
        any_row = queue(qty=2, **{"for": "Any deck"})
        _, order = recorded([any_row, exact], [card(qty=2), card(qty=2, set_code="fdn", number="100")])
        claims = ledger.read(order)["claims"]
        self.assertEqual(claims[0]["intent"]["printing"], "exact")
        self.assertEqual([(c["row"]["set"], c["quantity"]) for c in claims], [("cmm", 2), ("fdn", 2)])

    def test_one_token_cannot_fulfil_front_and_paired_alias(self):
        with self.assertRaisesRegex(Invalid, "distinct physical copies"):
            recorded([queue("Rabbit"), queue("Rabbit // Food")], tokens=[token()])

    def test_two_tokens_can_fulfil_two_aliases_and_both_face_printings(self):
        requests = [queue("Rabbit", printing="exact", set="tfin", collector_number="1", finish="nonfoil"),
                    queue("Rabbit // Food", printing="exact", set="tfin", collector_number="2", finish="nonfoil")]
        _, order = recorded(requests, tokens=[token(qty=2)])
        self.assertEqual(sum(c["quantity"] for c in ledger.read(order)["claims"]), 2)

    def test_same_token_front_and_back_number_still_one_capacity(self):
        requests = [queue("Rabbit", **{"for": "One"}), queue("Rabbit // Food", **{"for": "Two"})]
        with self.assertRaises(Invalid):
            recorded(requests, tokens=[token(back_collector_number="1")])

    def test_component_rows_and_products_share_allocations_without_cross_credit(self):
        inv, order = recorded([queue(qty=3)], cards=[card(qty=1)], products=[card(qty=2)])
        claims = ledger.read(order)["claims"]
        self.assertEqual([(c["component"], c["quantity"]) for c in claims], [("cards", 1), ("product", 2)])
        inv = inv.with_watchlist([])
        _, _, info = ledger.restore(inv, order, ["cards"])
        self.assertEqual(info["restored"][0]["quantity"], "1")

    def test_duplicate_requests_never_overdraw_queue_quantity(self):
        inv, order = snapshot([queue(qty=2)], [card(qty=4)])
        with self.assertRaisesRegex(Invalid, "quantity|only"):
            ledger.record(inv, inv, order, [{"select": "#1", "quantity": 2}, {"select": "#1", "quantity": 1}])

    def test_malformed_quantity_raises_invalid(self):
        inv, order = snapshot([queue(qty="three")], [card(qty=3)])
        with self.assertRaises(Invalid):
            ledger.record(inv, inv, order, [{"select": "#1"}])

    def test_split_distributes_exact_rows_and_each_deck_intent_conservatively(self):
        queued = [queue(qty=2, **{"for": "A"}), queue(qty=3, **{"for": "B"})]
        inv, order = recorded(queued, [card(qty=5)])
        data = order.record()
        data["components"].append(Component.build("later", "cards", "later.csv").record())
        split = ledger.split(Order(order.file, data), "cards", "later", [card(qty=2)], [card(qty=3)])
        claims = ledger.read(split)["claims"]
        self.assertEqual(sum(c["quantity"] for c in claims), 5)
        self.assertEqual([(c["component"], c["intent"]["for"], c["quantity"]) for c in claims],
                         [("cards", "A", 2), ("later", "B", 3)])
        inv = inv.with_order(split).set_component_rows(order.id, "cards", [card(qty=2)])
        inv = inv.set_component_rows(order.id, "later", [card(qty=3)]).with_watchlist([])
        inv, consumed, info = ledger.restore(inv, split, ["later"])
        self.assertEqual(info["restored"][0]["for"], "B")
        inv, _, info = ledger.restore(inv, consumed, ["cards"])
        self.assertEqual(sum(int(r["quantity"]) for r in row_dicts(inv)), 5)

    def test_split_does_not_move_claim_to_a_different_printing(self):
        a, b = card(qty=2), card(qty=3, set_code="fdn", number="1")
        _, order = recorded([queue(qty=2, printing="exact", set="cmm", collector_number="648", finish="nonfoil")],
                            [a, b])
        data = order.record()
        data["components"].append(Component.build("later", "cards", "later.csv").record())
        split = ledger.split(Order(order.file, data), "cards", "later", [a], [b])
        self.assertEqual([c["component"] for c in ledger.read(split)["claims"]], ["cards"])

    def test_partial_receipt_allocates_identical_copy_claim_to_arrived_part_first(self):
        _, order = recorded([queue(qty=1)], [card(qty=2)])
        data = order.record()
        data["components"].append(Component.build("arrived", "cards", "arrived.csv", status="received").record())
        split_order = Order(order.file, data)
        default = ledger.split(split_order, "cards", "arrived", [card(qty=1)], [card(qty=1)])
        arrived_first = ledger.split(split_order, "cards", "arrived", [card(qty=1)], [card(qty=1)],
                                     moved_first=True)
        self.assertEqual([(c["component"], c["quantity"]) for c in ledger.read(default)["claims"]],
                         [("cards", 1)])
        self.assertEqual([(c["component"], c["quantity"]) for c in ledger.read(arrived_first)["claims"]],
                         [("arrived", 1)])

    def test_partial_receipt_priority_never_rebinds_an_exact_printing_claim(self):
        exact, other = card(qty=1), card(qty=1, set_code="fdn", number="1")
        _, order = recorded([queue(qty=1, printing="exact", set="cmm", collector_number="648", finish="nonfoil")],
                            [exact, other])
        data = order.record()
        data["components"].append(Component.build("arrived", "cards", "arrived.csv", status="received").record())
        split_order = Order(order.file, data)
        for moved_first in (False, True):
            for kept, moved, owner in (([exact], [other], "cards"), ([other], [exact], "arrived")):
                with self.subTest(moved_first=moved_first, owner=owner):
                    split = ledger.split(split_order, "cards", "arrived", kept, moved, moved_first=moved_first)
                    claims = ledger.read(split)["claims"]
                    self.assertEqual([(c["component"], c["quantity"]) for c in claims], [(owner, 1)])
                    self.assertEqual(claims[0]["row"]["set"], "cmm")
                    self.assertEqual(claims[0]["row"]["collector_number"], "648")

    def test_edit_printing_correction_and_reordering_preserves_intent_quantities(self):
        old = [card(qty=2), card(qty=3, set_code="fdn", number="1")]
        _, order = recorded([queue(qty=5, **{"for": "Elves"})], old)
        new = [card(qty=3, set_code="fdn", number="1"), card(qty=2, number="649", condition="NM")]
        corrected = ledger.edit(order, "cards", old, new)
        claims = ledger.read(corrected)["claims"]
        self.assertEqual(sum(c["quantity"] for c in claims), 5)
        self.assertEqual(CounterLike(claims), {"1": 3, "649": 2})

    def test_edit_reserves_all_unchanged_rows_before_corrected_rows(self):
        old = [card(qty=1), card(qty=1, number="999")]
        queued = [queue(**{"for": "A"}), queue(**{"for": "B"})]
        _, order = recorded(queued, old)
        new = [card(qty=1, number="999"), card(qty=1, number="777")]
        corrected = ledger.edit(order, "cards", old, new)
        claims = ledger.read(corrected)["claims"]
        self.assertEqual({c["intent"]["for"]: c["row"]["collector_number"] for c in claims},
                         {"A": "777", "B": "999"})

    def test_token_name_correction_preserves_original_intent_and_physical_capacity(self):
        old = [token(qty=2)]
        _, order = recorded([queue("Rabbit", qty=2)], tokens=old)
        corrected = ledger.edit(order, "tokens", old, [token(qty=2, front_details="1/1; white")])
        self.assertEqual(sum(c["quantity"] for c in ledger.read(corrected)["claims"]), 2)
        new = [token("Dog", qty=2, back="Beast")]
        corrected = ledger.edit(order, "tokens", old, new)
        claims = ledger.read(corrected)["claims"]
        self.assertEqual(sum(c["quantity"] for c in claims), 2)
        self.assertEqual(claims[0]["intent"]["name"], "Rabbit")
        self.assertEqual(claims[0]["row"]["front"], "Dog")
        self.assertTrue(ledger.read(corrected)["warnings"])
        inv, _ = snapshot([], tokens=new)
        inv, _, info = ledger.restore(inv.with_order(corrected), corrected, ["tokens"])
        self.assertEqual(row_dicts(inv)[0]["name"], "Rabbit")
        self.assertEqual(info["restored"][0]["quantity"], "2")

    def test_product_quantity_decrease_keeps_original_explicit_intent_for_whole_cancel(self):
        old = [card(qty=3)]
        _, order = recorded([queue(qty=3)], products=old)
        corrected = ledger.edit(order, "product", old, [card(qty=1)])
        self.assertEqual(sum(c["quantity"] for c in ledger.read(corrected)["claims"]), 3)
        self.assertIn("original recorded purchase intent", ledger.read(corrected)["warnings"][0])
        inv, _ = snapshot([], products=[card(qty=1)])
        inv, _, info = ledger.restore(inv.with_order(corrected), corrected, ["product"])
        self.assertEqual(row_dicts(inv)[0]["quantity"], "3")
        self.assertEqual(info["restored"][0]["quantity"], "3")
        # Another correction must not treat historical physical allocations as current copies.
        again = ledger.edit(corrected, "product", [card(qty=1)], [card("Sol Ring", qty=1)])
        self.assertEqual(sum(c["quantity"] for c in ledger.read(again)["claims"]), 3)

    def test_token_correction_can_still_split_without_duplicating_original_intent(self):
        old, new = [token(qty=3)], [token("Dog", qty=3, back="Beast")]
        _, order = recorded([queue("Rabbit", qty=3)], tokens=old)
        corrected = ledger.edit(order, "tokens", old, new)
        data = corrected.record()
        data["components"].append(Component.build("later", "tokens", "later.csv").record())
        split = ledger.split(Order(order.file, data), "tokens", "later", [token("Dog", qty=1, back="Beast")],
                             [token("Dog", qty=2, back="Beast")])
        claims = ledger.read(split)["claims"]
        self.assertEqual(sum(c["quantity"] for c in claims), 3)
        self.assertEqual([(c["component"], c["quantity"]) for c in claims], [("tokens", 1), ("later", 2)])

    def test_restore_preserves_current_matching_metadata_and_hidden_row_id(self):
        inv, order = recorded([queue(qty=2, notes="Original", state="long_term")], [card(qty=2)])
        current = queue(qty=5, notes="Current", state="deferred", listed_aud="0.99", listed_at="Current shop",
                        checked="2026-10-15", in_stock="no")
        inv = inv.with_watchlist([WatchRow.make(current, id=41)])
        inv, order, info = ledger.restore(inv, order, ["cards"])
        row = row_dicts(inv)[0]
        self.assertEqual(inv.watchlist.rows[0].id, 41)
        self.assertEqual(row["quantity"], "7")
        for k in QUEUE_FIELDS:
            if k != "quantity":
                self.assertEqual(row[k], current[k])
        self.assertEqual(info["restored"][0]["quantity"], "2")
        self.assertEqual(info["restored"][0]["notes"], "Current")
        inv, _, again = ledger.restore(inv, order, ["cards"])
        self.assertEqual(again["offered"], [])
        self.assertEqual(row_dicts(inv)[0]["quantity"], "7")

    def test_recreated_queue_has_intent_but_no_stale_market_or_missing_source(self):
        original = queue(qty=2, notes="Still wanted", state="long_term", source="magic/buylists/gone.md",
                         listed_aud="0.50", listed_at="Old shop", checked="2026-10-15", in_stock="yes")
        inv, order = recorded([original], [card(qty=2)])
        inv, _, info = ledger.restore(inv.with_watchlist([]), order, ["cards"])
        row = row_dicts(inv)[0]
        self.assertEqual(row["quantity"], "2")
        self.assertEqual(row["state"], "long_term")
        self.assertEqual(row["notes"], "Still wanted")
        self.assertEqual(row["source"], "")
        self.assertTrue(all(row[k] == "" for k in ledger.MARKET_FIELDS))
        self.assertTrue(info["warnings"])
        self.assertEqual(info["restored"][0]["source"], "")

    def test_declining_consumes_claim_and_remove_cannot_restore_it_later(self):
        inv, order = recorded([queue(qty=2)], [card(qty=2)])
        inv = inv.with_watchlist([])
        after, consumed, info = ledger.restore(inv, order, ["cards"], False)
        self.assertEqual(after, inv)
        self.assertEqual(info["offered"][0]["quantity"], "2")
        self.assertEqual(info["restored"], [])
        self.assertEqual(ledger.read(consumed)["consumed"], ["cards"])
        _, _, again = ledger.restore(inv, consumed, ["cards"], True)
        self.assertEqual(again["offered"], [])

    def test_received_and_cancelled_components_are_not_offered(self):
        for status in ("received", "cancelled"):
            with self.subTest(status=status):
                inv, order = recorded([queue(qty=2)], [card(qty=2)])
                inv = inv.update_component(order.id, "cards", status=status)
                order = inv.order(order.id)
                _, _, info = ledger.restore(inv.with_watchlist([]), order, ["cards"])
                self.assertEqual(info["offered"], [])

    def test_malformed_duplicate_unknown_version_and_forged_overdraw_fail_closed(self):
        inv, order = recorded([queue()], [card()])
        malformed = [ledger.PREFIX + "broken]]", order.audit_notes + " " + order.audit_notes,
                     order.audit_notes.replace("v1:", "v2:", 1),
                     ledger.PREFIX + '{"claims":[],"claims":[],"consumed":[],"warnings":[]}]]']
        for notes in malformed:
            with self.subTest(notes=notes):
                data = order.record()
                data["audit_notes"] = notes
                with self.assertRaises(Invalid):
                    ledger.read(Order(order.file, data))
        forged = ledger.read(order)
        forged["claims"][0]["quantity"] = 2
        forged_order = ledger.write(order, forged)
        with self.assertRaises(Invalid):
            ledger.restore(inv.with_watchlist([]), forged_order, ["cards"])

    def test_reserved_market_fields_cannot_be_injected_in_ledger(self):
        _, order = recorded([queue()], [card()])
        for field in ledger.MARKET_FIELDS:
            changed = ledger.read(order)
            changed["claims"][0]["intent"][field] = "forbidden"
            with self.assertRaises(Invalid):
                ledger.write(order, changed)

    def test_extra_copy_text_and_delimiters_inside_captured_notes_are_inert(self):
        note = 'before Extra copies of owned printings: product. after ]] [[Deck Lab fulfilment v1: fake'
        _, order = recorded([queue(notes=note)], [card()], notes="Human prose Extra copies of owned printings: cards.")
        self.assertEqual(rules.extra_copies(order.audit_notes), ("cards",))
        span = ledger.audit_span(order.audit_notes)
        original_marker = order.audit_notes[span[0]:span[1]]
        for ids in ([], ["cards", "product"], ["product"]):
            with self.subTest(ids=ids):
                text = rules.with_extra_copies(order.audit_notes, ids)
                self.assertEqual(rules.extra_copies(text), tuple(ids))
                data = order.record()
                data["audit_notes"] = text
                changed = Order(order.file, data)
                self.assertEqual(ledger.read(changed)["claims"][0]["intent"]["notes"], note)
                new_span = ledger.audit_span(text)
                self.assertEqual(text[new_span[0]:new_span[1]], original_marker)
        # With no human marker, the captured sentence must not prevent an actual one being added.
        no_human = rules.with_extra_copies(order.audit_notes, [])
        self.assertEqual(rules.extra_copies(no_human), ())
        self.assertEqual(rules.extra_copies(rules.with_extra_copies(no_human, ["cards"])), ("cards",))

    def test_rewrite_preserves_human_prose_and_appended_audit_reason(self):
        prose = "Before. Extra copies of owned printings: cards. After."
        _, order = recorded([queue()], [card()], notes=prose)
        data = order.record()
        data["audit_notes"] += " Component cards cancelled: Seller cancelled."
        order = Order(order.file, data)
        changed = ledger.read(order)
        changed["warnings"].append("A warning")
        rewritten = ledger.write(order, changed)
        self.assertTrue(rewritten.audit_notes.endswith(prose + " Component cards cancelled: Seller cancelled."))
        self.assertEqual(rules.extra_copies(rewritten.audit_notes), ("cards",))


def CounterLike(claims):
    out = {}
    for claim in claims:
        number = claim["row"]["collector_number"]
        out[number] = out.get(number, 0) + claim["quantity"]
    return out


if __name__ == "__main__":
    unittest.main()
