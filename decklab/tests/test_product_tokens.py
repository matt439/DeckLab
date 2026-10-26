"""Product packing records: isolated files, syntax and lock-time source receipts."""
from decklab.lib import inventory
from decklab.lib.inventory import files, kit, ops_products as ops, paths, rules, table_rows
from decklab.lib.state import Actor
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401

STEM = "fixture-token-box"
PACKED = "2 Zombie // Zombie Knight"
ACTOR = Actor("claude", "Claude", source="cli")
TOKEN_ROWS = ("Zombie,Zombie Knight,,,,,3,,,\nAngel,The Monarch,,,,,1,,,\n")


class ProductTokensCase(PreparationCase):
    def setUp(self):
        super().setUp()
        self.product(f"{STEM}.csv", ("deck", "Llanowar Elves", 1), ("deck", "Forest", 20), column="section")
        self.write("products/status.csv", ",".join(rules.KIT_STATUS_FIELDS) + "\n"
                   + f"{STEM}.csv,owned,yes,old sleeves,old box,Keep this note\n")
        self.write("tokens.csv", ",".join(rules.TOKEN_FIELDS) + "\n" + TOKEN_ROWS)

    def row(self, snapshot=None):
        return ops.product_row(snapshot or inventory.current(), STEM)

    def op(self, value=PACKED, snapshot=None, **changes):
        snapshot = snapshot or inventory.current()
        return inventory.Op(ops.KIND, {"stem": STEM, "sha256": kit.status_sha256(snapshot),
                            "tokens_sha256": ops.token_sha256(snapshot), "token_cards": value, **changes})

    def apply(self, value=PACKED, **changes):
        return inventory.apply(self.op(value, **changes), ACTOR, "Record disposable product token packing")


class ProductTokenOperationTests(ProductTokensCase):
    def test_record_and_clear_preserve_kit_notes_and_every_other_source(self):
        before = inventory.current()
        after, summary = self.apply("2 Zombie // Zombie Knight; 1 Angel // The Monarch")
        self.assertEqual(summary.counts, {"token_cards": 3})
        self.assertEqual(self.row(after).text("token_cards"), "2 Zombie // Zombie Knight; 1 Angel // The Monarch")
        self.assertEqual(tuple(self.row(after).text(k) for k in ("sleeves", "deck_box", "notes")),
                         ("old sleeves", "old box", "Keep this note"))
        self.assertEqual(inventory.changed_paths(before, after), [paths.STATUS])
        self.assertEqual(after.tokens, before.tokens)
        self.assertEqual(after.products, before.products)
        untouched, summary = self.apply(self.row(after).text("token_cards"))
        self.assertFalse(summary.changed)
        self.assertEqual(untouched, after)
        cleared, _ = self.apply("")
        self.assertEqual(self.row(cleared).text("token_cards"), "")
        self.assertEqual(self.row(cleared).text("sleeves"), "old sleeves")

    def test_four_six_and_seven_column_formats_have_consistent_new_fields(self):
        for fields, values in ((rules.LEGACY_STATUS_FIELDS, [f"{STEM}.csv", "owned", "yes", "Note"]),
                               (rules.KIT_STATUS_FIELDS, [f"{STEM}.csv", "owned", "yes", "red", "box", "Note"]),
                               (rules.STATUS_FIELDS, [f"{STEM}.csv", "owned", "yes", "red", "box", "Note", PACKED])):
            text = rules.csv_bytes([dict(zip(fields, values))], fields).decode()
            with self.subTest(fields=fields):
                row = rules.parse_status(text, "fixture")[0]
                self.assertEqual(row["notes"], "Note")
                self.assertEqual(row["token_cards"], PACKED if fields == rules.STATUS_FIELDS else "")
        after, _ = self.apply()
        rendered = files.render(after)
        self.assertEqual(files.build(rendered).status, after.status)
        self.assertEqual(table_rows.tables(after)["product_status"][f"{STEM}.csv"],
                         (0, "owned", "yes", "old sleeves", "old box", "Keep this note", PACKED))

    def test_breakup_clears_token_record_and_kit_together(self):
        self.apply()
        after, _ = inventory.apply(inventory.Op("product.set_intact", {"stem": STEM, "intact": "no"}),
                                   ACTOR, "Break up disposable product", refresh=False)
        row = self.row(after)
        self.assertEqual(tuple(row.text(k) for k in ("intact", "sleeves", "deck_box", "token_cards", "notes")),
                         ("no", "", "", "", "Keep this note"))

    def test_bad_record_and_source_tokens_refuse_without_writing(self):
        before = files.render(inventory.current())
        for value in (None, False, "0 Zombie", "2 Zombie\nOther", "not a token line", "10000 Zombie"):
            with self.subTest(value=value), self.assertRaises(inventory.Invalid):
                self.apply(value)
        for key, value in (("sha256", "a" * 64), ("tokens_sha256", "b" * 64)):
            with self.subTest(key=key), self.assertRaises(inventory.Conflict):
                self.apply(**{key: value})
        self.assertEqual(files.render(inventory.current()), before)

    def test_only_actual_owned_intact_unambiguous_product_can_be_changed(self):
        for status, intact in (("owned", "no"), ("ordered", "yes"), ("preordered", "")):
            self.status((f"{STEM}.csv", status, intact))
            with self.subTest(status=status, intact=intact), self.assertRaises(inventory.Invalid):
                self.apply()
        self.status((f"{STEM}.csv", "owned", "yes"), (f"{STEM}.csv", "owned", "yes"))
        with self.assertRaises(inventory.Invalid):
            self.apply()
        self.status((f"{STEM}.csv", "owned", "yes"))
        for stem in ("absent", "../outside", "status"):
            with self.subTest(stem=stem), self.assertRaises(inventory.Invalid):
                self.apply(stem=stem)

    def test_product_and_token_changes_after_receipt_are_checked_inside_operation(self):
        for target in ("status", "tokens"):
            old = inventory.current()
            op = self.op(snapshot=old)
            if target == "status":
                self.write("products/status.csv", files.render(old)[paths.STATUS].decode().replace("Keep this note", "Concurrent"))
            else:
                self.write("tokens.csv", files.render(old)[paths.tokens("home")].decode().replace(",3,,,", ",2,,,"))
            with self.subTest(target=target), self.assertRaises(inventory.Conflict):
                inventory.apply(op, ACTOR, "Refuse stale disposable packing")
            self.assertEqual(self.row().text("token_cards"), "")

    def test_absent_tokens_allow_only_matching_null_receipt_for_clear(self):
        self.apply()
        (self.magic / "tokens.csv").unlink()
        self.assertIsNone(ops.token_sha256(inventory.current()))
        after, _ = self.apply("")
        self.assertEqual(self.row(after).text("token_cards"), "")
        with self.assertRaises(inventory.Conflict):
            self.apply("", tokens_sha256="a" * 64)

    def test_malformed_saved_record_is_reported_without_inventing_cards(self):
        self.apply()
        sheet = self.row().replace(token_cards="Broken record")
        snapshot = inventory.current().with_status_rows([sheet])
        read = files.status_sheet(files.render(snapshot)[paths.STATUS])
        self.assertTrue(any("packed token cards can't be read" in p for p in read.problems))
