"""Product kit CLI: real shared operations over isolated files and a disposable database."""
import contextlib
import io
import json
import unittest
from unittest import mock

from decklab.db import __main__ as cli
from decklab.lib import inventory, state
from decklab.lib.inventory import kit
from decklab.tests import db_support
from decklab.tests.test_accessories import AccessoriesTestCase, BLACK, BOX


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, out.getvalue(), err.getvalue()


class _Fixture(AccessoriesTestCase):
    def setUp(self):
        super().setUp()
        self.product()
        self.status("test-product.csv,owned,yes,old red,old box,Keep this note\n")
        self.inventory(BLACK.format(qty=100),
                       "hers,sleeves,user1,DS,Matte,pink,100,,,,,,\n",
                       "mine,sleeves,matt,DS,Matte,red,100,,,,,,\n",
                       "empty-box,deck_box,shared,UG,Empty,grey,0,100,,,,,\n", BOX.format(qty=1))
        self.deck("unchanged", "Unchanged", status="idea")
        self.backend = inventory.backend()

    def sha(self):
        return kit.status_sha256(inventory.current())

    def fields(self):
        row = inventory.current().status.rows[0]
        return tuple(row.text(key) for key in ("sleeves", "deck_box", "notes"))

    def change(self, *args, expect=None, message="Choose product kit"):
        return run_cli("product", "set-kit", "test-product", "--expect", expect or self.sha(),
                       "-m", message, *args)

    def success(self, *args, **kwargs):
        code, out, err = self.change(*args, **kwargs)
        self.assertEqual(code, 0, f"{err}\n{out}")
        return out


class ProductKitCliTests(_Fixture):
    def test_read_shows_legacy_values_and_status_list_token_without_writing(self):
        before = inventory.current()
        code, out, err = run_cli("product", "kit", "test-product", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"id": "product/test-product", "stem": "test-product",
                         "name": "test-product", "status": "owned", "intact": "yes",
                         "sleeves": "old red", "deck_box": "old box", "sha256": self.sha()})
        code, out, err = run_cli("product", "kit", "test-product")
        self.assertEqual(code, 0, err)
        for text in ("product/test-product", "sleeves: old red", "deck box: old box", self.sha()):
            self.assertIn(text, out)
        self.assertEqual(inventory.current(), before)

    def test_sleeves_a_deck_already_has_are_chosen_with_a_warning(self):
        # Matt, 2026-10-19: sharing is allowed, but the command says who else has them.
        self.deck("otters", "Izzet Otters", sleeves="dragon-shield-matte-black")
        out = self.success("--sleeves", "dragon-shield-matte-black")
        self.assertIn("Warning: Izzet Otters uses Dragon Shield Matte (black) already.", out)
        self.assertEqual(self.fields()[0], "dragon-shield-matte-black")
        self.assertNotIn("Warning:", self.success("--deck-box", "ultimate-guard-boulder-100-black"))

    def test_set_both_then_clear_one_preserves_omitted_field_and_other_data(self):
        before = inventory.current()
        self.success("--sleeves", "dragon-shield-matte-black", "--deck-box", "ultimate-guard-boulder-100-black")
        self.assertEqual(self.fields(), ("dragon-shield-matte-black", "ultimate-guard-boulder-100-black", "Keep this note"))
        self.success("--sleeves", "none")
        self.assertEqual(self.fields(), ("", "ultimate-guard-boulder-100-black", "Keep this note"))
        after = inventory.current()
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(after.accessories, before.accessories)
        self.assertEqual(after.products, before.products)

    def test_omitting_a_legacy_field_keeps_it_verbatim(self):
        self.success("--deck-box", "none")
        self.assertEqual(self.fields(), ("old red", "", "Keep this note"))

    def test_dry_run_checks_choices_but_saves_nothing(self):
        before = inventory.current()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            out = self.success("--sleeves", "dragon-shield-matte-black", "--dry-run")
        self.assertIn("Dry run: nothing saved", out)
        apply.assert_not_called()
        self.assertEqual(inventory.current(), before)
        code, _, err = self.change("--deck-box", "empty-box", "--dry-run")
        self.assertEqual(code, 1)
        self.assertIn("quantity is 0", err)
        self.assertEqual(inventory.current(), before)

    def test_short_prefix_and_uppercase_work_but_stale_or_malformed_tokens_do_not(self):
        old = self.sha()
        self.success("--sleeves", "none", expect=old[:12].upper())
        for token in (old, old[:12], "none", "a" * 11, "g" * 64, "a" * 65, ""):
            with self.subTest(token=token):
                before = inventory.current()
                code, _, err = run_cli("product", "set-kit", "test-product", "--expect", token,
                                       "--sleeves", "none", "-m", "Refuse stale token")
                self.assertEqual(code, 1, err)
                self.assertEqual(inventory.current(), before)

    def test_flags_and_nonblank_message_are_required_including_dry_run(self):
        before = inventory.current()
        for args, message in (((), "Choose kit"), (("--sleeves", "none"), "  "),
                              (("--sleeves", "none", "--dry-run"), "\t")):
            with self.subTest(args=args), mock.patch.object(inventory, "apply") as apply:
                code, _, err = self.change(*args, message=message)
                self.assertEqual(code, 1, err)
                apply.assert_not_called()
        self.assertEqual(inventory.current(), before)
        with contextlib.redirect_stderr(io.StringIO()):
            for args in (("product", "set-kit", "test-product", "-m", "Choose"),
                         ("product", "set-kit", "test-product", "--expect", self.sha())):
                with self.subTest(args=args), self.assertRaises(SystemExit) as raised:
                    cli.parser().parse_args(args)
                self.assertEqual(raised.exception.code, 2)

    def test_new_choices_are_ids_of_the_right_kind_and_shared_owner(self):
        before = inventory.current()
        for field, value in (("--sleeves", "old red"), ("--sleeves", "absent"),
                             ("--sleeves", "ultimate-guard-boulder-100-black"),
                             ("--deck-box", "dragon-shield-matte-black"),
                             ("--sleeves", "mine"), ("--sleeves", "hers"),
                             ("--sleeves", ""), ("--sleeves", "../mine")):
            with self.subTest(field=field, value=value):
                code, _, err = self.change(field, value)
                self.assertEqual(code, 1, err)
                self.assertEqual(inventory.current(), before)

    def test_box_unavailable_refuses_both_fields_without_partial_save(self):
        self.deck("taken", "Taken", deck_box="ultimate-guard-boulder-100-black")
        before = inventory.current()
        code, _, err = self.change("--sleeves", "dragon-shield-matte-black", "--deck-box", "ultimate-guard-boulder-100-black")
        self.assertEqual(code, 1, err)
        self.assertIn("every deck box", err)
        self.assertEqual(inventory.current(), before)

    def test_non_intact_or_unowned_product_cannot_even_clear_a_field(self):
        for status, intact in (("owned", "no"), ("ordered", ""), ("preordered", "")):
            with self.subTest(status=status):
                self.status(f"test-product.csv,{status},{intact},old red,old box,\n")
                before = inventory.current()
                code, _, err = self.change("--sleeves", "none")
                self.assertEqual(code, 1, err)
                self.assertIn("owned product kept intact", err)
                self.assertEqual(inventory.current(), before)

    def test_actor_is_forwarded_and_unknown_actor_refuses_before_reading(self):
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            self.success("--sleeves", "none", "--actor", "matt")
        self.assertEqual(apply.call_count, 1)
        self.assertEqual(apply.call_args.args[0].kind, "kit.set")
        self.assertEqual(apply.call_args.args[1], state.Actor("matt", "Matt", None, "cli"))
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            self.success("--deck-box", "none")
        self.assertEqual(apply.call_args.args[1], state.Actor("claude", "Claude", None, "cli"))
        with mock.patch.object(inventory, "current", side_effect=AssertionError("must not read")), \
                mock.patch.object(inventory, "apply") as apply:
            code, _, err = run_cli("product", "set-kit", "test-product", "--expect", "a" * 12,
                                   "--sleeves", "none", "-m", "Unknown actor", "--actor", "nobody")
        self.assertEqual(code, 1, err)
        self.assertIn("nobody", err)
        apply.assert_not_called()

    def test_product_changed_after_initial_read_is_rechecked_inside_apply(self):
        apply = inventory.apply

        def changed(op, *args, **kwargs):
            self.status("test-product.csv,owned,yes,old red,old box,Concurrent edit\n")
            return apply(op, *args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=changed):
            code, _, err = self.change("--sleeves", "none")
        self.assertEqual(code, 1, err)
        self.assertIn("changed after", err)
        self.assertEqual(self.fields(), ("old red", "old box", "Concurrent edit"))

    def test_product_broken_up_after_initial_read_cannot_be_cleared(self):
        apply = inventory.apply

        def changed(op, *args, **kwargs):
            self.status("test-product.csv,owned,no,old red,old box,Concurrent edit\n")
            return apply(op, *args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=changed):
            code, _, err = self.change("--sleeves", "none")
        self.assertEqual(code, 1, err)
        self.assertIn("owned product kept intact", err)
        self.assertEqual(self.fields(), ("old red", "old box", "Concurrent edit"))

    def test_missing_product_and_invalid_stem_refuse_reads_and_writes(self):
        for stem in ("missing", "../test-product", "status"):
            with self.subTest(stem=stem):
                for args in (("product", "kit", stem),
                             ("product", "set-kit", stem, "--expect", self.sha(), "--sleeves", "none", "-m", "Refuse")):
                    code, _, err = run_cli(*args)
                    self.assertEqual(code, 1, err)


class DatabaseProductKitCliTests(_Fixture, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        from decklab.tests.test_inventory_contract import CLAUDE, adapt
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(adapt(self.backend.load()), CLAUDE, "Import fixture", contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))

    def audit_count(self):
        with self.connect() as conn:
            return conn.execute("select count(*) from audit.change_set").fetchone()[0]

    def test_both_choices_are_one_audit_and_no_deck_revision(self):
        count = self.audit_count()
        before = inventory.current()
        self.success("--sleeves", "dragon-shield-matte-black", "--deck-box", "ultimate-guard-boulder-100-black", "--actor", "matt")
        self.assertEqual(self.audit_count(), count + 1)
        after = inventory.current()
        self.assertNotEqual(after.revision, before.revision)
        self.assertEqual(after.decks_revision, before.decks_revision)
        self.assertEqual(after.decks, before.decks)
        self.assertEqual(self.fields()[:2], ("dragon-shield-matte-black", "ultimate-guard-boulder-100-black"))
        with self.connect() as conn:
            self.assertEqual(conn.execute("select actor, source, message from audit.change_set order by id desc limit 1").fetchone(),
                             ("matt", "cli", "Choose product kit"))
        self.success("--sleeves", "dragon-shield-matte-black", "--deck-box", "ultimate-guard-boulder-100-black")
        self.assertEqual(self.audit_count(), count + 1)  # the same fields are a no-op

    def test_second_invalid_choice_rolls_back_fields_revision_and_audit(self):
        count = self.audit_count()
        before = inventory.current()
        code, _, err = self.change("--sleeves", "dragon-shield-matte-black", "--deck-box", "empty-box")
        self.assertEqual(code, 1, err)
        self.assertEqual(inventory.current(), before)
        self.assertEqual(self.audit_count(), count)

    def test_concurrent_status_change_is_rejected_in_the_database_transaction(self):
        count = self.audit_count()
        apply = self.backend.apply

        def changed(op, actor, message, **kwargs):
            other = inventory.Op("kit.set", {"holders": [{"id": "product/test-product", "expected": self.sha()}],
                                 "changes": [{"holder": "product/test-product", "field": "deck_box", "value": None}],
                                 "owners": None})
            apply(other, state.Actor("claude", "Claude", None, "cli"), "Concurrent fixture edit")
            return apply(op, actor, message, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed):
            code, _, err = self.change("--sleeves", "none")
        self.assertEqual(code, 1, err)
        self.assertIn("changed after", err)
        self.assertEqual(self.fields(), ("old red", "", "Keep this note"))
        self.assertEqual(self.audit_count(), count + 1)
