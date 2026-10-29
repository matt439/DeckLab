"""CLI merge filing over disposable files and the protected fixture entry point only."""
import contextlib
import io
from unittest import mock

from decklab.db import __main__ as cli, inv_collection, inv_decks
from decklab.lib import inventory, pool
from decklab.lib.api import collection_filing as filing, guard
from decklab.lib.inventory import ops_collection as ops
from decklab.tests import test_cli_write_previews as support
from decklab.tests.test_cli_write_previews import HEADER, _PreviewTree
from decklab.tests.test_collection_filing import deck_text

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule


class MergeFilingCliTests(_PreviewTree):
    def gift(self, quantity=2, *, text=None):
        return self.source("filing-gift.csv", text if text is not None else
                           HEADER + f"Llanowar Elves,fdn,227,nonfoil,{quantity},,,\n")

    def merge(self, source=None, *extra, preview=False):
        return self.run_cli("collection", "merge", source or self.gift(), "-m", "Fixture gift", *extra, preview=preview)

    def test_saved_merge_prints_only_new_copies_once_with_prior_free_stock_consumed_first(self):
        for slug in ("a", "b"):
            self.write(f"decks/casual/{slug}.md", deck_text(slug.upper(), 2))
        before = inventory.current()
        real, writes = inventory.apply, []

        def save(*args, **kwargs):
            result = real(*args, **kwargs)
            writes.append((args, result))
            return result

        with mock.patch.object(inventory, "apply", side_effect=save):
            code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertIn("2 cards merged: 0 new rows, 1 existing rows increased", out)
        guide = out.split("Where these go", 1)[1]
        self.assertIn("Deck casual/b (B)", guide)
        self.assertIn("2 x Llanowar Elves (FDN 227, nonfoil)", guide)
        self.assertNotIn("Deck casual/a", guide)
        self.assertNotIn("Storage:", guide)
        self.assertIn("at this saved merge", guide)
        self.assertIn("no cards were packed or reserved", guide)
        self.assertEqual(len(writes), 1)
        self.assertTrue(writes[0][0][0].params["capture_additions"])
        self.assertEqual(writes[0][1][1].extra["added_printings"][0]["quantity"], 2)
        self.assertEqual(inventory.current().decks, before.decks)

    def test_bom_crlf_and_repeated_source_bytes_stay_exact_while_deltas_are_combined(self):
        raw = "\ufeff" + HEADER.replace("\n", "\r\n") + "Llanowar Elves,fdn,227,nonfoil,1,LP,ja,gift\r\n"
        source = self.gift(text=raw)
        code, out, err = self.run_cli("collection", "merge", source, source, "-m", "Two physical gifts", preview=False)
        self.assertEqual(code, 0, err)
        self.assertIn("more than once", err)
        self.assertIn("2 cards merged", out)
        self.assertIn("2 x Llanowar Elves", out)
        saved = list((self.magic / "imports").glob("*.csv"))
        self.assertEqual(len(saved), 2)
        self.assertTrue(all(path.read_bytes() == raw.encode("utf-8") for path in saved))
        self.assertEqual(source.read_bytes(), raw.encode("utf-8"))

    def test_actor_is_only_attribution_and_member_space_cli_never_asks_web_permissions(self):
        (self.magic / "people/user2/decks/casual").mkdir(parents=True)
        self.write("people/user2/decks/casual/private.md", deck_text("Member fixture", 2))
        real, actors = inventory.apply, []

        def save(op, actor, *args, **kwargs):
            actors.append(actor)
            return real(op, actor, *args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=save), \
                mock.patch.object(guard, "deck_reader", side_effect=AssertionError("web viewer")), \
                mock.patch.object(guard, "sees_inventory", side_effect=AssertionError("web inventory")):
            code, out, err = self.merge(None, "--space", "user2", "--actor", "matt")
        self.assertEqual(code, 0, err)
        self.assertEqual(actors[0].id, "matt")
        guide = out.split("Where these go", 1)[1]
        self.assertIn("Deck user2/casual/private (Member fixture)", guide)
        self.assertNotIn("Preview", guide)
        self.assertNotIn("Deck casual/", guide)

    def test_dry_run_keeps_original_would_output_and_never_calls_saved_advice(self):
        with mock.patch.object(filing, "after_cli_merge", side_effect=AssertionError("preview advice")) as advice:
            code, out, err = self.merge(preview=True)
        self.assertEqual(code, 0, err)
        self.assertIn("Would merge 2 cards", out)
        self.assertIn("Would keep unchanged raw import", out)
        self.assertIn("Nothing saved (--dry-run)", out)
        self.assertNotIn("Where these go", out)
        advice.assert_not_called()

    def test_zero_tracked_copies_is_success_without_attempting_an_allocation(self):
        source = self.gift(text=HEADER + "Forest,fdn,280,nonfoil,12,,,\n")
        with mock.patch.object(filing, "_allocate", side_effect=AssertionError("zero allocation")), \
                mock.patch.object(inv_decks, "stale_notes"):
            code, out, err = self.merge(source)
        self.assertEqual(code, 0, err)
        self.assertIn("0 cards merged", out)
        self.assertIn("12 ordinary basic lands omitted", out)
        self.assertIn("No tracked copies were added, so there is nothing to file", out)
        self.assertIn("Kept magic/imports/", out)

    def test_stale_notes_and_guide_use_actual_after_without_any_later_backend_load(self):
        real, patchers, snapshots = inventory.apply, [], []

        def save(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            snapshots.append(after)
            patcher = mock.patch.object(self.inventory, "load", side_effect=AssertionError("later snapshot"))
            patcher.start()
            patchers.append(patcher)
            return after, summary

        def note(space):
            self.assertIs(inventory.current(), snapshots[0])
            print("Existing stale-table note.")

        try:
            with mock.patch.object(inventory, "apply", side_effect=save), mock.patch.object(inv_decks, "stale_notes", side_effect=note):
                code, out, err = self.merge()
            self.assertEqual(code, 0, err)
            self.assertIn("Existing stale-table note.", out)
            self.assertIn("Where these go", out)
            self.assertNotIn("Destination unknown", out)
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_missing_post_save_index_or_ambiguous_pool_is_unknown_without_failed_merge(self):
        for mode in ("index", "pool"):
            source = self.gift()
            real, patchers = inventory.apply, []

            def save(*args, **kwargs):
                result = real(*args, **kwargs)
                patcher = mock.patch.object(filing.cards, "resolve", side_effect=FileNotFoundError("private index detail")) \
                    if mode == "index" else mock.patch.object(filing.pool, "load_pool", return_value=pool.Pool(
                        {}, {}, [], warnings=["private pool detail"]))
                patcher.start()
                patchers.append(patcher)
                return result

            try:
                with mock.patch.object(inventory, "apply", side_effect=save), mock.patch.object(inv_decks, "stale_notes"):
                    code, out, err = self.merge(source)
                self.assertEqual(code, 0, err)
                guide = out.split("Where these go", 1)[1]
                self.assertIn("Destination unknown", guide)
                self.assertIn("merge is saved", guide)
                self.assertNotIn("Storage:", guide)
                self.assertNotIn("private", guide)
            finally:
                for patcher in patchers:
                    patcher.stop()

    def test_advice_or_formatting_failure_keeps_success_raw_upload_and_exit_code(self):
        for failure in (RuntimeError("private advice detail"), {"status": "ready", "cards": 2,
                        "added": [], "destinations": [{"kind": "storage", "row": 9, "quantity": 2}]}):
            patcher = mock.patch.object(filing, "after_cli_merge", side_effect=failure) if isinstance(failure, Exception) \
                else mock.patch.object(filing, "after_cli_merge", return_value=failure)
            with patcher, mock.patch.object(inv_decks, "stale_notes"):
                code, out, err = self.merge()
            self.assertEqual(code, 0, err)
            self.assertIn("2 cards merged", out)
            self.assertIn("Kept magic/imports/", out)
            self.assertIn("Destination unknown. The merge is saved", out)
            self.assertNotIn("Storage:", out)
            self.assertNotIn("private advice detail", out + err)

    def test_large_guide_labels_omitted_printing_lines_without_truncating_the_merge(self):
        source = self.gift(text=HEADER + "".join(f"Llanowar Elves,fdn,{i},nonfoil,1,,,\n" for i in range(1, 102)))
        code, out, err = self.merge(source)
        self.assertEqual(code, 0, err)
        guide = out.split("Where these go", 1)[1]
        self.assertEqual(sum(line.startswith("    1 x ") for line in guide.splitlines()), 100)
        self.assertIn("Showing 100 of 101 printing lines; 1 not shown", guide)
        self.assertEqual(sum(row.qty for row in inventory.current().collection().rows), 103)

    def test_allocation_cap_is_unknown_and_success_never_suggests_repeating_the_merge(self):
        with mock.patch.object(filing, "MAX_DECKS", 0), mock.patch.object(inv_decks, "stale_notes"):
            code, out, err = self.merge()
        self.assertEqual(code, 0, err)
        self.assertIn("Destination unknown", out)
        self.assertNotIn("Storage:", out)
        self.assertNotIn("run the merge again", out + err)

    def test_stale_and_unavailable_writes_keep_existing_refusal_exit_codes_without_advice(self):
        for failure, expected in ((ops.Stale("home", "The home collection"), 1),
                                  (inventory.Unavailable("fixture unavailable"), 2)):
            with mock.patch.object(inventory, "apply", side_effect=failure), \
                    mock.patch.object(filing, "after_cli_merge", side_effect=AssertionError("refused advice")) as advice:
                code, out, err = self.merge()
            self.assertEqual(code, expected, err)
            self.assertNotIn("Where these go", out)
            advice.assert_not_called()

    def test_advice_print_encoding_error_cannot_turn_a_saved_merge_into_failure(self):
        class LimitedConsole(io.StringIO):
            def write(self, text):
                if text.startswith("Where these go"):
                    raise UnicodeError("fixture console cannot print advice")
                return super().write(text)

        source = self.gift()
        out, err = LimitedConsole(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["collection", "merge", str(source), "-m", "Fixture gift"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("2 cards merged", out.getvalue())
        self.assertIn("Filing advice could not be printed. The merge is saved", err.getvalue())
        self.assertEqual(sum(row.qty for row in inventory.current().collection().rows), 4)

    def test_failed_optional_stdout_and_stderr_reports_still_leave_saved_merge_successful(self):
        class LimitedConsole(io.StringIO):
            def write(self, text):
                if text.startswith(("Where these go", "Filing advice could not be printed")):
                    raise OSError("fixture optional report stream is closed")
                return super().write(text)

        source = self.gift()
        out, err = LimitedConsole(), LimitedConsole()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["collection", "merge", str(source), "-m", "Fixture gift"])
        self.assertEqual(code, 0)
        self.assertIn("2 cards merged", out.getvalue())
        self.assertIn("Kept magic/imports/", out.getvalue())
        self.assertEqual(sum(row.qty for row in inventory.current().collection().rows), 4)

    def test_optional_closed_text_stream_value_errors_do_not_fail_the_saved_merge(self):
        class ClosedDuringAdvice(io.StringIO):
            def write(self, text):
                if text.startswith(("Where these go", "Filing advice could not be printed")):
                    raise ValueError("I/O operation on closed file")
                return super().write(text)

        source = self.gift()
        out, err = ClosedDuringAdvice(), ClosedDuringAdvice()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["collection", "merge", str(source), "-m", "Fixture gift"])
        self.assertEqual(code, 0)
        self.assertIn("2 cards merged", out.getvalue())
        self.assertIn("Kept magic/imports/", out.getvalue())
        self.assertEqual(sum(row.qty for row in inventory.current().collection().rows), 4)
