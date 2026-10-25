"""Purchase queue saves over fixture files and a disposable PostgreSQL copy.

No test reads or writes the live inventory. Permissions and HTTP guards are also
covered by test_api_permissions and test_feature_routes.
"""
import contextlib
import csv
import io
import json
import unittest
from unittest import mock

from decklab.lib import access, config, inventory, purchases
from decklab.lib.api import shopping, shopping_queue
from decklab.lib.api import reprints as reprint_api
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.lib.inventory.files import FileInventory
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.tests import db_support, test_inventory_contract as contract
from decklab.tests.test_inventory_orders import CLAUDE, orders_tree


def queue_tree(case):
    orders_tree(case)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS, lineterminator="\n")
    writer.writeheader()
    for finish, state in (("nonfoil", "waiting_for_stock"), ("foil", "waiting_for_reprint")):
        row = {key: "" for key in QUEUE_FIELDS}
        row.update(name="Pick Your Poison", set="mkm", collector_number="170", finish=finish,
                   quantity="2", printing="exact", state=state, **{"for": "Cats"},
                   listed_aud="0.50", listed_at="Fixture shop", in_stock="no", checked="2026-10-05",
                   notes="Keep this printing and note", source="magic/buylists/2026-10-12-plan.md")
        writer.writerow(row)
    case.write("watchlist.csv", stream.getvalue())


class QueueStateTests:
    def start(self, case):
        self.root = case.inventory.root
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        stack.enter_context(inventory.use(self.backend))
        stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))

    def save(self, **changes):
        data = {"profile": "matt", "row": 2, "state": "long_term", "expect": self.backend.load().revision}
        data.update(changes)
        return shopping_queue.save_queue_state(json.dumps(data))

    def refused(self, status, **changes):
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.save(**changes)
        self.assertEqual(caught.exception.status, status)
        after = self.backend.load()
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(files.render(after), files.render(before))

    def change(self, action, **changes):
        data = {"profile": "matt", "action": action, "expect": self.backend.load().revision}
        data.update(changes)
        return shopping_queue.save_queue_state(json.dumps(data))

    def refused_change(self, status, action, **changes):
        before = self.backend.load()
        with self.assertRaises(ApiError) as caught:
            self.change(action, **changes)
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        after = self.backend.load()
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(files.render(after), files.render(before))

    def test_add_appends_a_validated_card_without_changing_other_data(self):
        before = self.backend.load()
        result = self.change("add", values={"name": "pick your poison", "quantity": 3,
                                            "for": "Later deck", "notes": "Try three copies"})
        after = self.backend.load()
        self.assertEqual(result["row"], 3)
        self.assertEqual(result["action"], "add")
        self.assertEqual(result["revision"], after.revision)
        item = {key: after.watchlist.rows[-1].text(key) for key in QUEUE_FIELDS}
        self.assertEqual({key: result["item"][key] for key in QUEUE_FIELDS}, {**item, "quantity": 3})
        self.assertEqual(result["item"]["card"]["name"], "Pick Your Poison")
        self.assertEqual((item["name"], item["state"], item["printing"], item["finish"]),
                         ("Pick Your Poison", "ready", "any", "nonfoil"))
        self.assertEqual(after.watchlist.rows[:2], before.watchlist.rows)
        for key, value in files.render(before).items():
            if key != "magic/watchlist.csv":
                self.assertEqual(files.render(after)[key], value)

    def test_edit_quantity_and_notes_keeps_printing_research_identity_and_other_variants(self):
        before = self.backend.load()
        evidence = {"fixture": "reprint evidence"}
        with mock.patch.object(shopping_queue, "_require_cards", side_effect=AssertionError("No lookup needed")), \
                mock.patch.object(reprint_api, "evidence", return_value=evidence):
            result = self.change("edit", row=2, values={"quantity": "4", "notes": "Buy together"})
        after = self.backend.load()
        expected = {key: before.watchlist.rows[1].text(key) for key in QUEUE_FIELDS}
        expected.update(quantity="4", notes="Buy together")
        self.assertEqual(result["item"], {**expected, "quantity": 4, "reprints": evidence})
        self.assertEqual(result["reprints"], evidence)
        self.assertEqual(after.watchlist.rows[0], before.watchlist.rows[0])
        self.assertEqual(after.watchlist.rows[1].id, before.watchlist.rows[1].id)
        self.assertEqual({key: after.watchlist.rows[1].text(key) for key in QUEUE_FIELDS}, expected)
        unchanged = self.change("edit", row=2, values={"quantity": 4, "notes": "Buy together"})
        self.assertEqual(unchanged["revision"], after.revision)

    def test_removal_is_one_numbered_variant_and_requires_a_reason(self):
        before = self.backend.load()
        for reason in ("", "  ", None, True, "two\nlines", "\x7f"):
            with self.subTest(reason=reason):
                self.refused_change(400, "remove", row=1, reason=reason)
        result = self.change("remove", row=1, reason="No longer planning this printing")
        after = self.backend.load()
        self.assertEqual(result, {"saved": True, "action": "remove", "row": 1, "revision": after.revision})
        self.assertEqual(after.watchlist.rows, (before.watchlist.rows[1],))

    def test_add_and_identity_edits_check_names_and_printings(self):
        self.refused_change(404, "add", values={"name": "Not a card name"})
        self.refused_change(404, "edit", row=2, values={"name": "Not a card name"})
        for values in ({"set": "mkm"}, {"set": "MKM", "collector_number": "170"},
                       {"set": "mkm", "collector_number": "999999"},
                       {"printing": "exact"}, {"finish": "etched", "set": "mkm", "collector_number": "170"}):
            with self.subTest(values=values):
                self.refused_change(400, "add", values={"name": "Pick Your Poison", **values})
        self.refused_change(400, "add", values={"name": "Llanowar Elves", "set": "mkm",
                                                "collector_number": "170"})
        result = self.change("add", values={"name": "Llanowar Elves", "set": "ttsr",
                                            "collector_number": "12", "printing": "exact"})
        self.assertEqual((result["item"]["name"], result["item"]["set"]), ("Llanowar Elves", "ttsr"))

    def test_add_rejects_duplicate_variant_and_edit_rejects_duplicate_identity(self):
        duplicate = {key: self.backend.load().watchlist.rows[0].text(key)
                     for key in shopping_queue.EDIT_FIELDS}
        self.refused_change(400, "add", values=duplicate)
        self.refused_change(400, "edit", row=2, values={"finish": "nonfoil"})

    def test_invalid_details_never_get_coerced_or_write(self):
        bad = [{"quantity": item} for item in (0, -1, True, 1.5, "1.5", None, [], "1" * 5000)]
        bad += [{"notes": item} for item in (None, [], 2, "two\nlines", "\0")]
        bad += [{"state": "soon"}, {"printing": "preferred"}, {"finish": "shiny"},
                {"source": "../outside.md"}, {"listed_aud": "1.00"}, {"name": ""}]
        for values in bad:
            with self.subTest(values=str(values)[:100]):
                self.refused_change(400, "edit", row=2, values=values)
        for values in ({}, [], None, "text"):
            self.refused_change(400, "add", values=values)
        self.refused_change(400, "add", values={"quantity": 1})
        self.refused_change(400, "unknown")
        self.refused_change(400, [], values={"name": "Opt"})
        self.refused_change(400, "remove", row=999, reason="No longer needed")

    def test_new_actions_check_exact_revision_before_the_card_lookup_or_row(self):
        for action, fields in (("add", {"values": {"name": "Pick Your Poison"}}),
                               ("edit", {"row": 999, "values": {"name": "Pick Your Poison"}}),
                               ("remove", {"row": 999, "reason": "No longer needed"})):
            with self.subTest(action=action), mock.patch.object(inventory, "apply") as apply, \
                    mock.patch.object(shopping_queue, "_require_cards") as lookup:
                self.refused_change(409, action, expect="stale", **fields)
                apply.assert_not_called()
                lookup.assert_not_called()

    def test_new_actions_refuse_a_concurrent_write_inside_apply(self):
        real = inventory.apply
        actions = (("add", {"values": {"name": "Pick Your Poison"}}),
                   ("edit", {"row": 2, "values": {"quantity": 5}}),
                   ("remove", {"row": 2, "reason": "No longer needed"}))
        for action, fields in actions:
            before = self.backend.load()

            def concurrent(op, actor, message, **kwargs):
                real(inventory.Op("watchlist.set", {"select": "#1", "values": {"notes": action},
                                                    "repo": str(self.root)}), CLAUDE, "Concurrent fixture change")
                return real(op, actor, message, **kwargs)

            with self.subTest(action=action), mock.patch.object(inventory, "apply", concurrent):
                with self.assertRaises(ApiError) as caught:
                    self.change(action, expect=before.revision, **fields)
                self.assertEqual(caught.exception.status, 409)
            after = self.backend.load()
            self.assertEqual(len(after.watchlist.rows), len(before.watchlist.rows))
            self.assertEqual(after.watchlist.rows[0].notes, action)
            self.assertEqual(after.watchlist.rows[1], before.watchlist.rows[1])

    def test_new_actions_are_admin_only_and_refuse_impersonation(self):
        actions = (("add", {"values": {"name": "Opt"}}),
                   ("edit", {"row": 2, "values": {"quantity": 5}}),
                   ("remove", {"row": 2, "reason": "No longer needed"}))
        for action, fields in actions:
            for remote in (False, True):
                identity = {"profile": "user2", "email": "", "remote": True} if remote else None
                with self.subTest(action=action, remote=remote), access.using(identity), access.viewing("user2"), \
                        mock.patch.object(inventory, "current") as load:
                    for profile in ("user2", "matt"):
                        with self.assertRaises(ApiError) as caught:
                            self.change(action, profile=profile, expect="unread", **fields)
                        self.assertEqual(caught.exception.status, 403)
                    load.assert_not_called()

    def test_add_needs_card_data_and_new_actions_report_database_unavailable(self):
        with mock.patch.object(shopping_queue, "_require_cards", side_effect=ApiError(503, "Card data unavailable")):
            self.refused_change(503, "add", values={"name": "Opt"})
        for action, fields in (("add", {"values": {"name": "Pick Your Poison"}}),
                               ("edit", {"row": 2, "values": {"quantity": 5}}),
                               ("remove", {"row": 2, "reason": "No longer needed"})):
            with self.subTest(action=action), mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")):
                self.refused_change(503, action, **fields)

    def test_every_state_changes_only_the_selected_variant_and_keeps_its_details(self):
        original = self.backend.load()
        expected_rows = [{key: row.text(key) for key in QUEUE_FIELDS} for row in original.watchlist.rows]
        identities = [row.id for row in original.watchlist.rows]
        for state in purchases.STATES:
            with self.subTest(state=state):
                before = self.backend.load()
                evidence = {"fixture": state}
                with mock.patch.object(reprint_api, "evidence", return_value=evidence):
                    result = self.save(state=state)
                after = self.backend.load()
                expected_rows[1]["state"] = state
                self.assertEqual(result, {"saved": True, "row": 2, "state": state,
                                          "revision": after.revision, "reprints": evidence})
                self.assertEqual([{key: row.text(key) for key in QUEUE_FIELDS} for row in after.watchlist.rows],
                                 expected_rows)
                self.assertEqual([row.id for row in after.watchlist.rows], identities)
                self.assertEqual({key: value for key, value in files.render(after).items()
                                  if key != "magic/watchlist.csv"},
                                 {key: value for key, value in files.render(before).items()
                                  if key != "magic/watchlist.csv"})

    def test_one_audited_operation_uses_the_exact_expected_revision(self):
        real, calls = inventory.apply, []
        revision = self.backend.load().revision

        def apply(op, actor, message, **kwargs):
            calls.append((op, actor, message, kwargs))
            return real(op, actor, message, **kwargs)

        with mock.patch.object(inventory, "apply", apply):
            self.save(expect=revision)
        self.assertEqual(len(calls), 1)
        op, actor, message, kwargs = calls[0]
        self.assertEqual((op.kind, dict(op.params)),
                         ("watchlist.set", {"select": "#2", "values": {"state": "long_term"},
                                            "repo": str(self.root)}))
        self.assertEqual((actor.id, actor.source, actor.via), ("matt", "web", "tunnel"))
        self.assertTrue(message.strip())
        self.assertEqual(kwargs, {"expected_revision": revision})

    def test_same_state_is_a_no_op(self):
        before = self.backend.load()
        result = self.save(state="waiting_for_reprint")
        self.assertEqual(result["revision"], before.revision)
        self.assertEqual(files.render(self.backend.load()), files.render(before))

    def test_stale_and_partial_revisions_are_refused_before_resolving_the_row(self):
        revision = self.backend.load().revision
        for expect in ("stale", revision[:-1], revision + "0", " " + revision):
            with self.subTest(expect=expect), mock.patch.object(inventory, "apply") as apply:
                self.refused(409, row=999, expect=expect or "stale")
                apply.assert_not_called()

    def test_a_write_between_the_read_and_apply_is_a_conflict(self):
        real = inventory.apply
        before = self.backend.load()

        def concurrent(op, actor, message, **kwargs):
            real(inventory.Op("watchlist.set", {"select": "#1", "values": {"state": "deferred"},
                                                "repo": str(self.root)}), CLAUDE, "Fixture concurrent change")
            return real(op, actor, message, **kwargs)

        with mock.patch.object(inventory, "apply", concurrent), self.assertRaises(ApiError) as caught:
            self.save(expect=before.revision)
        self.assertEqual(caught.exception.status, 409)
        after = self.backend.load()
        self.assertEqual(after.watchlist.rows[0].state, "deferred")
        self.assertEqual(after.watchlist.rows[1].state, before.watchlist.rows[1].state)

    def test_invalid_inputs_and_an_unknown_row_write_nothing(self):
        for row in (0, -1, True, False, 1.0, "1", None, [], 999):
            with self.subTest(row=row):
                self.refused(400, row=row)
        for state in ("immediate", "soon", "", None, [], 1):
            with self.subTest(state=state):
                self.refused(400, state=state)
        for expect in (None, 1, [], "", "  ", "x" * 257, "\0"):
            with self.subTest(expect=expect):
                self.refused(400, expect=expect)
        self.refused(400, extra="unknown")
        for body in ("{}", "[]", '{"profile":"matt","row":1,"state":"ready"}'):
            with self.subTest(body=body), self.assertRaises(ApiError) as caught:
                shopping_queue.save_queue_state(body)
            self.assertEqual(caught.exception.status, 400)

    def test_unavailable_inventory_is_a_503(self):
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")):
            self.refused(503)
        with mock.patch.object(inventory, "current", side_effect=inventory.Unavailable("down")):
            self.refused(503)

    def test_overview_identifies_rows_before_the_ui_groups_them(self):
        with mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping, "_home_decks", return_value=[]):
            answer = shopping.shopping_overview()
        self.assertEqual(answer["queue_revision"], self.backend.load().revision)
        self.assertEqual([(row["queue_row"], row["finish"]) for row in answer["to_buy"]],
                         [(1, "nonfoil"), (2, "foil")])


class FileQueueStateTests(QueueStateTests, unittest.TestCase):
    def setUp(self):
        case = contract.build_tree(queue_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        self.backend = FileInventory(case.inventory.root)
        self.start(case)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class PgQueueStateTests(QueueStateTests, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        case = contract.build_tree(queue_tree, adapted=True)
        self.addCleanup(case.doCleanups)
        pg.write_model(case.inventory.load(), CLAUDE, "Import fixture", dbname=self.dbname)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.start(case)

    def test_change_is_one_row_and_no_op_adds_no_audit_entry(self):
        with self.connect() as connection:
            before = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        self.save()
        with self.connect() as connection:
            changes = connection.execute("select id, actor, source from audit.change_set order by id").fetchall()
            rows = connection.execute("select table_name, op from audit.row_change where change_set_id = %s",
                                      (changes[-1][0],)).fetchall()
        self.assertEqual(len(changes), before + 1)
        self.assertEqual(changes[-1][1:], ("matt", "web"))
        self.assertEqual(rows, [("watchlist_item", "UPDATE")])
        self.save()
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], before + 1)

    def test_crud_records_the_actor_and_removal_reason_without_position_churn(self):
        actions = (("add", {"values": {"name": "Pick Your Poison"}}, "INSERT"),
                   ("edit", {"row": 3, "values": {"quantity": 2, "notes": "For later"}}, "UPDATE"),
                   ("remove", {"row": 1, "reason": "No longer planning this printing"}, "DELETE"))
        for action, fields, op in actions:
            with self.connect() as connection:
                before = connection.execute("select count(*) from audit.change_set").fetchone()[0]
            self.change(action, **fields)
            with self.connect() as connection:
                changes = connection.execute("select id, actor, source, reason from audit.change_set order by id").fetchall()
                rows = connection.execute("select table_name, op from audit.row_change where change_set_id = %s",
                                          (changes[-1][0],)).fetchall()
            self.assertEqual(len(changes), before + 1)
            self.assertEqual(changes[-1][1:3], ("matt", "web"))
            self.assertEqual(changes[-1][3], fields.get("reason"))
            self.assertEqual(rows, [("watchlist_item", op)])
