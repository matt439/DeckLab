"""CLI receipts bind a non-writing preview to the exact later receipt intent."""
import contextlib
import io
import re
from unittest import mock

from decklab.db import __main__ as cli
from decklab.lib import inventory
from decklab.lib.inventory import files
from decklab.tests import test_pool as support
from decklab.tests.test_receive_order import receipt_tree

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


class ReceiptPreviewTests(support.PoolTestCase):
    def setUp(self):
        super().setUp()
        receipt_tree(self)

    def run_cli(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["receive", "--order", "test", *map(str, flags)])
        return code, out.getvalue(), err.getvalue()

    def preview(self, *flags):
        code, out, err = self.run_cli(*flags)
        self.assertEqual(code, 0, err)
        found = re.search(r"^Preview token: ([a-f0-9]{64})$", out, re.M)
        self.assertIsNotNone(found, out)
        return found[1]

    def tree(self):
        return files.tree_files(self.magic.parent)

    def unchanged_refusal(self, token, *flags):
        before = self.tree()
        revision = inventory.current().revision
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, _, err = self.run_cli(*flags, "--apply", "--expect", token)
        self.assertEqual(code, 1, err)
        self.assertIn("Preview again", err)
        apply.assert_not_called()
        self.assertEqual(self.tree(), before)
        self.assertEqual(inventory.current().revision, revision)

    def test_unchanged_preview_applies_once_and_refreshes_its_deck(self):
        flags = ("--component", "cards", "--verified", "cards", "--date", "2026-10-08")
        before = self.tree()
        token = self.preview(*flags)
        self.assertEqual(self.tree(), before)
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, out, err = self.run_cli(*flags, "--apply", "--expect", token)
        self.assertEqual(code, 0, err)
        self.assertIn("Received.", out)
        self.assertIn("Refreshed: casual/test", out)
        self.assertEqual(apply.call_args.args[2], "receive test: cards")
        self.assertEqual(inventory.current().collection().rows[-1].quantity, "2")
        saved = self.tree()
        code, _, _ = self.run_cli(*flags, "--apply", "--expect", token)
        self.assertEqual(code, 1)
        self.assertEqual(self.tree(), saved)

    def test_any_inventory_change_refuses_before_receipt_audit_or_deck_changes(self):
        flags = ("--component", "cards", "--verified", "cards", "--date", "2026-10-08")
        token = self.preview(*flags)
        self.write("tokens.csv", "front,back,set,front_collector_number,back_collector_number,finish,quantity,"
                   "front_details,back_details,notes\nDog,Beast,,,,,1,,,\n")
        self.unchanged_refusal(token, *flags)

    def test_changed_date_checks_selection_and_received_facts_need_a_new_preview(self):
        flags = ("--component", "cards", "--verified", "cards", "--date", "2026-10-08")
        token = self.preview(*flags)
        alternatives = [
            ("--component", "cards", "--verified", "cards", "--date", "2026-10-09"),
            ("--component", "cards", "--date", "2026-10-08"),
            ("--component", "kit", "--intact", "no", "--date", "2026-10-08"),
        ]
        rows = self.magic.parent / "received.csv"
        rows.write_text((self.magic / "orders/test.csv").read_text().replace(",NM,en,", ",LP,en,"), encoding="utf-8")
        alternatives.append((*flags, "--rows", f"cards={rows}"))
        for changed in alternatives:
            with self.subTest(flags=changed):
                self.unchanged_refusal(token, *changed)

    def test_product_intact_choice_is_bound_but_component_flag_order_is_irrelevant(self):
        flags = ("--component", "cards", "--component", "kit", "--verified", "cards",
                 "--intact", "no", "--date", "2026-10-08")
        token = self.preview(*flags)
        self.unchanged_refusal(token, *flags, "--intact", "yes")
        self.assertEqual(self.preview("--component", "kit", "--component", "cards", "--verified", "cards",
                                      "--intact", "no", "--date", "2026-10-08"), token)

    def test_invalid_preview_has_no_token_and_legacy_apply_still_revalidates(self):
        code, out, _ = self.run_cli("--component", "cards", "--date", "2026-10-08")
        self.assertEqual(code, 0)
        self.assertIn("Required:", out)
        self.assertNotIn("Preview token:", out)
        code, _, _ = self.run_cli("--component", "cards", "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 1)
        code, _, err = self.run_cli("--component", "cards", "--verified", "cards", "--date", "2026-10-08", "--apply")
        self.assertEqual(code, 0, err)

    def test_backend_conflict_after_token_validation_keeps_everything_unchanged(self):
        flags = ("--component", "cards", "--verified", "cards", "--date", "2026-10-08")
        token = self.preview(*flags)
        before = self.tree()
        original = inventory.preview

        def concurrent_change(operation, *args, **kwargs):
            result = original(operation, *args, **kwargs)
            self.write("tokens.csv", "front,back,set,front_collector_number,back_collector_number,finish,quantity,"
                       "front_details,back_details,notes\nDog,Beast,,,,,1,,,\n")
            return result

        with mock.patch.object(inventory, "preview", side_effect=concurrent_change):
            code, _, err = self.run_cli(*flags, "--apply", "--expect", token)
        self.assertEqual(code, 1, err)
        after = self.tree()
        after.pop("magic/tokens.csv")
        self.assertEqual(after, before)
