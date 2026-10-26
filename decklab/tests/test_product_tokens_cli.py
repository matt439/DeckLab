"""Typed product token commands use real operations over isolated fixtures."""
import contextlib
import io
import json
from unittest import mock

from decklab.db import __main__ as cli
from decklab.lib import inventory
from decklab.tests.test_product_tokens import PACKED, STEM, ProductTokensCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class ProductTokensCliTests(ProductTokensCase):
    def change(self, text=PACKED, **changes):
        params = self.op().params
        args = ["product", "set-tokens", STEM, "--expect", changes.get("expect", params["sha256"]),
                "--tokens-sha256", changes.get("tokens_sha256", params["tokens_sha256"] or "none"),
                "--tokens", text, "-m", changes.get("message", "Record disposable product tokens")]
        if changes.get("dry_run"):
            args.append("--dry-run")
        return run_cli(*args)

    def test_read_reports_both_hashes_and_write_preserves_kit(self):
        code, out, err = run_cli("product", "tokens", STEM, "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertEqual(found["token_cards"], "")
        self.assertEqual(found["tokens_sha256"], self.op().params["tokens_sha256"])
        code, _, err = self.change(expect=found["sha256"][:12])
        self.assertEqual(code, 0, err)
        self.assertEqual(self.row().text("token_cards"), PACKED)
        self.assertEqual(self.row().text("sleeves"), "old sleeves")
        self.assertEqual(self.change("")[0], 0)
        self.assertEqual(self.row().text("token_cards"), "")

    def test_preview_bad_text_blank_message_and_stale_receipts(self):
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            code, out, err = self.change(dry_run=True)
            self.assertEqual(code, 0, err)
            self.assertIn("Dry run: nothing saved", out)
            apply.assert_not_called()
        for changes in ({"message": " "}, {"expect": "a" * 64}, {"tokens_sha256": "b" * 64}):
            self.assertEqual(self.change(**changes)[0], 1)
        self.assertEqual(self.change("Broken token line")[0], 1)
        self.assertEqual(self.row().text("token_cards"), "")

    def test_missing_token_sheet_uses_explicit_none_receipt(self):
        self.change()
        (self.magic / "tokens.csv").unlink()
        code, _, err = self.change("")
        self.assertEqual(code, 0, err)
