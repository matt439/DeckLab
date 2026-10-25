"""Missing across home decks: real card-index/pool reads, guarded HTTP and disposable PostgreSQL."""
import contextlib
import csv
import dataclasses
import http.client
import io
import json
import threading
import unittest
from unittest import mock

from decklab.lib import access, cards, config, decks, inventory, pool, server_http
from decklab.lib.api import common, shopping, shopping_missing, shopping_queue
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files, rules
from decklab.lib.inventory.model import Component, Order, QUEUE_FIELDS
from decklab.tests import db_support, test_inventory_contract as contract, test_pool

RIDER = "Murderous Rider // Swift End"


def queue_row(name, purpose, state="ready", **fields):
    return {**dict.fromkeys(QUEUE_FIELDS, ""), "name": name, "quantity": "1", "for": purpose,
            "printing": "any", "state": state, **fields}


def missing_tree(case):
    case.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                   (RIDER, "eld", "97", "nonfoil", 1),
                   ("Llanowar Elves", "fdn", "227", "nonfoil", 3),
                   ("Ghalta, Primal Hunger", "rix", "130", "nonfoil", 1))
    case.product("fdn-beginner-box.csv", ("Elves", "Llanowar Elves", 1), ("Cats", "Llanowar Elves", 1))
    case.product("reference-only.csv", ("deck", "Sol Ring", 1), column="section")
    case.status(("fdn-beginner-box.csv", "owned", "yes"), ("reference-only.csv", "preordered", ""))
    records = [
        Order.build("beginner-box", components=[Component.build("box", "product", "fdn-beginner-box.csv", "received")]),
        Order.build("reference", components=[Component.build("precon", "product", "reference-only.csv")]),
        Order.build("incoming", components=[Component.build("cards", "cards", "incoming.csv")],
                    audit_notes="Extra copies of owned printings: cards."),
    ]
    for record in records:
        case.write(f"orders/records/{record.file}", rules.json_bytes(record.data).decode("utf-8"))
    case.cards_csv("orders/incoming.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 1),
                   ("Llanowar Elves", "fdn", "227", "nonfoil", 1))
    case.deck("alpha", "Alpha", "building",
              "Deck\n4 Llanowar Elves\n3 Elvish Mystic\n2 Murderous Rider\n1 Murderous Rider // Swift End\n20 Forest\n"
              "Sideboard\n1 Llanowar Elves\n", owned="Deck\n20 Forest\n")
    case.deck("beta", "Beta", "idea", f"Deck\n3 Llanowar Elves\n1 Elvish Mystic\n1 {RIDER}\n20 Forest\n")
    case.deck("gamma", "Gamma", "idea",
              "Commander\n1 Ghalta, Primal Hunger\nDeck\n1 Llanowar Elves\n1 Pick Your Poison\n", kind="commander")
    case.deck("holding", "Holding", "built", "Deck\n1 Llanowar Elves\n", built_version="target")
    person = case.magic / "people/user2/decks/casual"
    person.mkdir(parents=True, exist_ok=True)
    text = test_pool.deck_md("User2 secret", "idea", "Deck\n4 Black Lotus\n")
    (person / "private.md").write_text(text.replace("- **Played by:** either\n", ""), encoding="utf-8", newline="\n")
    rows = []
    for purpose, state in (("Alpha", "ready"), ("Later", "waiting_for_stock"), ("Reprint", "waiting_for_reprint"),
                           ("Someday", "deferred"), ("Long term", "long_term")):
        rows.append(queue_row("Llanowar Elves", purpose, state, quantity="7"))
    rows[0].update(source="magic/decks/casual/alpha.md", listed_aud="0.50", listed_at="Fixture shop",
                   in_stock="yes", checked="2026-10-15", notes="Reference listing")
    rows[1].update(printing="exact", set="fdn", collector_number="227", finish="nonfoil")
    rows += [queue_row("Murderous Rider", "Beta", "deferred", source="magic/decks/casual/beta.md"),
             queue_row(RIDER, "Future", "waiting_for_reprint"),
             queue_row("Elvish Mystic", "Alpha", quantity="10"),
             queue_row("Pick Your Poison", "Gamma", "deferred", printing="exact", set="mkm",
                       collector_number="170", finish="nonfoil"), queue_row("Opt", "Unrelated"),
             queue_row("Llanowar Elves", "Token marker", printing="exact", set="ttsr", collector_number="12",
                       finish="nonfoil")]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, QUEUE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    case.write("watchlist.csv", stream.getvalue())


class _Fixture:
    def setUp(self):
        super().setUp()
        self.case = contract.build_tree(missing_tree, adapted=False)
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.inventory.root
        self.backend = self.case.inventory
        self.logs = []
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(contract.fixture_world())
        source = self.root / "cards-with-tokens.jsonl"
        source.write_bytes((test_pool.FIXTURES / "default_cards.jsonl").read_bytes() + b"\n"
                           + (test_pool.FIXTURES / "tokens_cards.jsonl").read_bytes())
        index = cards.build_index(source, test_pool.FIXTURES / "oracle_tags.jsonl", {}, log=lambda *args: None)
        index_file = self.root / "fixture-index.json.gz"
        cards.write_index(index, index_file)
        stack.enter_context(mock.patch.object(cards, "INDEX_FILE", index_file))
        stack.enter_context(mock.patch.object(cards, "_index", None))
        stack.enter_context(mock.patch.object(config, "REPO", self.root))
        stack.enter_context(mock.patch.object(common, "_log", self.logs.append))
        stack.enter_context(inventory.use(self.backend))
        stack.enter_context(access.using({"profile": "matt", "email": "", "remote": True}))

    def overview(self, profile="matt"):
        with access.using({"profile": profile, "email": "", "remote": True}):
            return shopping.shopping_overview()

    def expected_baseline(self, answer):
        result = answer["missing_cards"]
        self.assertEqual((result["ready"], result["warnings"], result["errors"]), (True, [], []))
        self.assertEqual(result["totals"], {"cards": 4, "copies": 10})
        by_name = {row["name"]: row for row in result["rows"]}
        self.assertEqual({name: row["missing"] for name, row in by_name.items()},
                         {"Llanowar Elves": 6, "Elvish Mystic": 1, RIDER: 2, "Pick Your Poison": 1})
        elves = by_name["Llanowar Elves"]
        self.assertEqual([(deck["id"], deck["title"], deck["status"], deck["missing"]) for deck in elves["decks"]],
                         [("casual/alpha", "Alpha", "building", 4), ("casual/beta", "Beta", "idea", 2)])
        poison = by_name["Pick Your Poison"]["decks"]
        self.assertEqual([(deck["id"], deck["kind"], deck["missing"]) for deck in poison],
                         [("commander/gamma", "commander", 1)])
        for row in result["rows"]:
            self.assertEqual(row["card"]["name"], row["name"])
        return by_name


class FileShoppingMissingTests(_Fixture, unittest.TestCase):
    def test_target_shortfalls_include_sideboards_and_incoming_after_built_and_product_reservations(self):
        before = self.backend.load()
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("read only")):
            answer = self.overview()
        self.expected_baseline(answer)
        self.assertEqual([(row["id"], row["missing"]) for row in answer["decks_missing"]],
                         [("casual/alpha", 7), ("commander/gamma", 1), ("casual/beta", 2)])
        self.assertEqual(files.render(self.backend.load(), decks=True), files.render(before, decks=True))

    def test_canonical_aliases_share_one_row_and_every_matching_queue_purpose_and_state_is_preserved(self):
        answer = self.overview()
        rows = self.expected_baseline(answer)
        for name, row in rows.items():
            expected = [queued for queued in answer["to_buy"] if cards.resolve(queued["name"]) == name
                        and not cards.token_faces_at(queued.get("set"), queued.get("collector_number"))]
            self.assertEqual(row["queue"], expected)
        self.assertEqual({row["state"] for row in rows["Llanowar Elves"]["queue"]},
                         {"ready", "waiting_for_stock", "waiting_for_reprint", "deferred", "long_term"})
        self.assertEqual(len(rows[RIDER]["queue"]), 2)
        self.assertIsNotNone(cards.token_faces_at("ttsr", "12"))
        token_row = next(row for row in answer["to_buy"] if row["set"] == "ttsr")
        self.assertIs(token_row["is_token"], True)
        self.assertTrue(all("is_token" not in row for row in answer["to_buy"] if row is not token_row))
        self.assertEqual(len(rows["Llanowar Elves"]["queue"]), 5)
        linked = rows["Llanowar Elves"]["queue"][0]
        self.assertEqual((linked["queue_row"], linked["deck"], linked["listed_aud"], linked["listed_at"],
                          linked["checked"], linked["in_stock"], linked["notes"]),
                         (1, {"id": "casual/alpha", "title": "Alpha", "colors": ["B", "G"]}, "0.50", "Fixture shop",
                          "2026-10-15", "yes", "Reference listing"))
        self.assertEqual(rows["Elvish Mystic"]["missing"], 1)  # queued ten copies do not reduce it again

    def test_token_classification_needs_positive_evidence_and_playable_printings_take_priority(self):
        self.assertIsNone(cards.resolve("The Monarch"))
        self.assertIsNotNone(cards.token_face("The Monarch"))
        for row, expected in (({"name": "The Monarch"}, True),
                              ({"name": "Llanowar Elves", "set": "ttsr", "collector_number": "12"}, True),
                              ({"name": "Llanowar Elves"}, False),
                              ({"name": "Unknown fixture name"}, False),
                              ({"name": "The Monarch", "set": "fdn", "collector_number": "227"}, False)):
            with self.subTest(row=row):
                self.assertIs(shopping_missing.is_token(row), expected)

    def test_unavailable_card_cache_never_marks_unknown_queue_rows_as_tokens(self):
        with mock.patch.object(cards, "INDEX_FILE", self.root / "missing-index.json.gz"), \
                mock.patch.object(cards, "_index", None):
            answer = self.overview()
        self.assertFalse(answer["missing_cards"]["ready"])
        self.assertTrue(all("is_token" not in row for row in answer["to_buy"]))

    def test_queue_add_and_identity_edits_return_token_markers_only_for_the_current_printing(self):
        def change(action, **fields):
            return shopping_queue.save_queue_state(json.dumps({"profile": "matt", "action": action,
                         "expect": self.backend.load().revision, **fields}))

        added = change("add", values={"name": "The Monarch", "for": "Reminder"})
        self.assertIs(added["item"]["is_token"], True)
        edited = change("edit", row=added["row"], values={"name": "Llanowar Elves", "set": "fdn",
                        "collector_number": "227", "printing": "exact"})
        self.assertNotIn("is_token", edited["item"])
        edited = change("edit", row=added["row"], values={"set": "ttsr", "collector_number": "12"})
        self.assertIs(edited["item"]["is_token"], True)

    def test_only_home_saved_decks_contribute_and_the_home_pool_is_reused_once_without_pricing(self):
        real = pool.owned_vs_needed
        with mock.patch.object(shopping, "_cards_ready", wraps=shopping._cards_ready) as ready, \
                mock.patch.object(pool, "load_pool", wraps=pool.load_pool) as load, \
                mock.patch.object(pool, "owned_vs_needed", wraps=real) as compare, \
                mock.patch.object(cards, "price_aud", side_effect=AssertionError("no prices needed")):
            answer = self.overview()
        self.expected_baseline(answer)
        ready.assert_called_once()
        load.assert_called_once()
        self.assertEqual({call.args[0] for call in compare.call_args_list},
                         {"casual/alpha", "casual/beta", "commander/gamma", "casual/holding"})
        supplied = [call.kwargs["pool"] for call in compare.call_args_list]
        self.assertTrue(all(item is supplied[0] for item in supplied))
        self.assertTrue(all(call.args[1] == "target" and call.kwargs["prices"] is False for call in compare.call_args_list))
        self.assertNotIn("User2 secret", json.dumps(answer))
        self.assertNotIn("Sol Ring", [row["name"] for row in answer["missing_cards"]["rows"]])

    def test_overview_loads_one_pinned_inventory_snapshot(self):
        with mock.patch.object(self.backend, "load", wraps=self.backend.load) as load:
            self.expected_baseline(self.overview())
        load.assert_called_once()

    def test_built_decks_are_counted_against_their_planned_list_too(self):
        self.case.deck("holding", "Holding", "built", "Deck\n1 Llanowar Elves\n1 Black Lotus\n", built_version="target")
        result = self.overview()["missing_cards"]
        self.assertTrue(result["ready"], result)
        lotus = next(row for row in result["rows"] if row["name"] == "Black Lotus")
        self.assertEqual((lotus["missing"], lotus["decks"][0]["id"], lotus["decks"][0]["status"]),
                         (1, "casual/holding", "built"))

    def test_missing_card_data_is_explicitly_unavailable_while_orders_and_queue_still_show(self):
        with mock.patch.object(shopping, "_cards_ready", return_value=False), \
                mock.patch.object(shopping_missing, "gather", side_effect=AssertionError("no index")):
            answer = self.overview()
        self.assertFalse(answer["missing_cards"]["ready"])
        self.assertTrue(answer["missing_cards"]["errors"])
        self.assertEqual(answer["missing_cards"]["rows"], [])
        self.assertEqual(answer["decks_missing"], [])
        self.assertTrue(answer["orders"] and answer["to_buy"])

    def test_failed_or_incomplete_home_pool_does_not_claim_a_successful_empty_result(self):
        supply = pool.load_pool()
        for change in (OSError("Fixture pool read failed"), dataclasses.replace(supply, warnings=["Fixture warning"]),
                       dataclasses.replace(supply, unresolved={"Unknown fixture card": {"collection.csv"}})):
            with self.subTest(change=type(change).__name__):
                patch = mock.patch.object(pool, "load_pool", side_effect=change) if isinstance(change, Exception) else \
                    mock.patch.object(pool, "load_pool", return_value=change)
                with patch:
                    answer = self.overview()
                result = answer["missing_cards"]
                self.assertFalse(result["ready"])
                self.assertEqual(result["rows"], [])
                self.assertTrue(result["errors"])
                if not isinstance(change, Exception):
                    self.assertTrue(result["warnings"])

    def test_one_deck_failure_keeps_good_partial_rows_with_a_named_error(self):
        compare = pool.owned_vs_needed

        def fail_one(deck_id, *args, **kwargs):
            if deck_id == "casual/alpha":
                raise ValueError("Fixture planned list failed")
            return compare(deck_id, *args, **kwargs)

        with mock.patch.object(pool, "owned_vs_needed", side_effect=fail_one):
            result = self.overview()["missing_cards"]
        self.assertFalse(result["ready"])
        self.assertEqual({row["name"]: row["missing"] for row in result["rows"]},
                         {"Llanowar Elves": 2, "Pick Your Poison": 1})
        self.assertTrue(any(error.get("id") == "casual/alpha" and error.get("title") == "Alpha"
                            and "Fixture planned list failed" in error["message"] for error in result["errors"]))

    def test_unresolved_planned_card_is_named_without_hiding_good_rows(self):
        self.case.deck("unknown", "Unknown list", "idea", "Deck\n1 Uncatalogued fixture card\n")
        result = self.overview()["missing_cards"]
        self.assertFalse(result["ready"])
        self.assertEqual(result["totals"], {"cards": 4, "copies": 10})
        self.assertEqual({error.get("id") for error in result["errors"]}, {"casual/unknown"})
        self.assertIn("Uncatalogued fixture card", json.dumps(result["errors"]))

    def test_unreadable_deck_has_a_named_error_and_blocks_uncertain_pool_reservations(self):
        self.case.write("decks/casual/broken.md", "# Broken list\n\nNo decklist here.\n")
        result = self.overview()["missing_cards"]
        self.assertFalse(result["ready"])
        self.assertEqual(result["rows"], [])
        self.assertTrue(result["warnings"])
        self.assertTrue(any(error.get("id") == "casual/broken" for error in result["errors"]))

    def test_home_deck_enumeration_failure_is_explicit(self):
        with mock.patch.object(decks, "list_decks", side_effect=OSError("Fixture deck listing failed")):
            result = self.overview()["missing_cards"]
        self.assertFalse(result["ready"])
        self.assertEqual(result["rows"], [])
        self.assertTrue(result["errors"])
        self.assertNotIn("Fixture deck listing failed", json.dumps(result["errors"]))
        self.assertTrue(any("Fixture deck listing failed" in line for line in self.logs))

    def test_global_deck_listing_failure_keeps_private_details_only_in_the_log(self):
        title, deck_id = "User2 Private Hydra", "user2/casual/secret"
        detail = f"{title} ({deck_id}): private list could not be read"
        with mock.patch.object(decks, "list_decks", side_effect=OSError(detail)):
            answer = self.overview()
        result = answer["missing_cards"]
        self.assertFalse(result["ready"])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["errors"], [{"message": "The home decks could not be listed. Try reloading Shopping."}])
        self.assertTrue(answer["orders"] and answer["to_buy"])
        for secret in (title, deck_id, "private list could not be read"):
            self.assertNotIn(secret, json.dumps(answer))
        self.assertTrue(any(detail in line for line in self.logs))

    def test_foreign_deck_ids_are_excluded_even_when_space_metadata_is_missing_or_wrong(self):
        found, supply = decks.list_decks(), pool.load_pool()
        deck_id, title, detail = "user2/casual/secret", "User2 Private Hydra", "Secret private inventory detail"
        for metadata in ({}, {"space": "home"}):
            foreign = {"id": deck_id, "title": title, "kind": "casual", "status": "idea",
                       "source": "magic/people/user2/decks/casual/secret.md", "versions": ["target"],
                       "error": detail, **metadata}
            with self.subTest(metadata=metadata), mock.patch.object(decks, "list_decks", return_value=[*found, foreign]), \
                    mock.patch.object(pool, "load_pool", return_value=supply), \
                    mock.patch.object(pool, "owned_vs_needed", wraps=pool.owned_vs_needed) as compare:
                answer = self.overview()
            self.expected_baseline(answer)
            self.assertNotIn(deck_id, [call.args[0] for call in compare.call_args_list])
            self.assertNotIn(deck_id, [row["id"] for row in answer["queue_decks"]])
            for secret in (deck_id, title, detail):
                self.assertNotIn(secret, json.dumps(answer))

    def test_empty_home_library_is_a_successful_empty_result(self):
        before = self.backend.load()
        empty = before.replace(decks={}).with_watchlist([{**row.as_dict(), "source": ""} for row in before.watchlist.rows])
        with inventory.pinned(empty):
            result = self.overview()["missing_cards"]
        self.assertEqual(result, {"ready": True, "rows": [], "warnings": [], "errors": [],
                                  "totals": {"cards": 0, "copies": 0}})

    def test_picture_absence_does_not_erase_valid_missing_counts(self):
        with mock.patch.object(shopping, "_card_for", return_value=None):
            result = self.overview()["missing_cards"]
        self.assertTrue(result["ready"], result)
        self.assertEqual(result["totals"], {"cards": 4, "copies": 10})
        self.assertTrue(all(row["card"] is None for row in result["rows"]))

    def test_home_members_can_read_and_person_space_members_are_refused_before_inventory_data(self):
        self.assertEqual(self.overview("matt")["missing_cards"], self.overview("user1")["missing_cards"])
        for profile in ("user2", "user3", "user4"):
            with self.subTest(profile=profile), mock.patch.object(inventory, "current", side_effect=AssertionError("guard first")), \
                    mock.patch.object(shopping_missing, "gather", side_effect=AssertionError("guard first")):
                with self.assertRaises(ApiError) as caught:
                    self.overview(profile)
                self.assertEqual(caught.exception.status, 403)


class PgShoppingMissingTests(_Fixture, db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        profiles_sync.sync(listed=contract.FIXTURE_PROFILES, dbname=cls.dbname)

    def test_postgresql_matches_the_same_file_snapshot_without_changes_or_new_audit_history(self):
        from decklab.lib.inventory import pg
        from decklab.lib.state import pg as state_pg
        expected = self.overview()["missing_cards"]
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES)
        pg.write_model(contract.adapt(self.backend.load()), contract.CLAUDE, "Import missing-card fixture",
                       contents={}, dbname=self.dbname, decks=True)
        self.backend = pg.PgInventory(dbname=self.dbname, breaker=state_pg.Breaker())
        self.addCleanup(inventory.use(self.backend))
        before = self.backend.load()
        with self.connect() as connection:
            count = connection.execute("select count(*) from audit.change_set").fetchone()[0]
        answer = self.overview("user1")
        self.expected_baseline(answer)
        self.assertEqual(answer["missing_cards"], expected)
        self.assertEqual(self.backend.load(), before)
        with self.connect() as connection:
            self.assertEqual(connection.execute("select count(*) from audit.change_set").fetchone()[0], count)


class ShoppingMissingHttpTests(_Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        web = self.root / "web"
        web.mkdir()
        patches = contextlib.ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(mock.patch.object(server_http, "log", self.logs.append))
        patches.enter_context(mock.patch.object(server_http.visits, "recorder", return_value=mock.Mock()))
        self.httpd = server_http.make_server("127.0.0.1", 0, web_dir=web)
        self.addCleanup(self.httpd.server_close)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.httpd.shutdown)

    def request(self, profile, method="GET"):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        try:
            connection.request(method, "/api/shopping", headers={access.VIEWER_HEADER: profile})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_existing_shopping_get_and_head_deliver_the_additive_summary(self):
        for profile in ("matt", "user1"):
            with self.subTest(profile=profile):
                status, body = self.request(profile)
                self.assertEqual(status, 200, body)
                self.expected_baseline(json.loads(body))
        self.assertEqual(self.request("matt", "HEAD"), (200, b""))

    def test_existing_shopping_http_read_guard_runs_before_missing_card_data(self):
        with mock.patch.object(shopping_missing, "gather", side_effect=AssertionError("guard first")):
            for method in ("GET", "HEAD"):
                with self.subTest(method=method):
                    status, body = self.request("user2", method)
                    self.assertEqual(status, 403, body)
