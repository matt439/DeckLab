"""Saved-plan previews on disposable lists and MemoryStore; no real runtime probes."""
import contextlib
import copy
import json
from unittest import mock

from decklab.lib import access, feature_routes, inventory, state
from decklab.lib.api import sideboard_preview as api, play_records as play
from decklab.lib.api.common import ApiError
from decklab.lib.state import rules
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_field_membership_api import FixtureHandler
from decklab.tests.test_play_records import DECK, MixedFixture, PlayFixture


class SideboardPreviewTests(PlayFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.write_decks()
        self.saved = self.save(self.plan(), play.save_sideboard)
        self.record = self.saved["record"]

    def preview(self):
        return api.preview_sideboard(self.record["id"], self.saved["sha256"])

    def error(self, status, message, call=None):
        with self.assertRaises(ApiError) as caught:
            (call or self.preview)()
        self.assertEqual((caught.exception.status, caught.exception.message, caught.exception.extra),
                         (status, message, {}))
        return caught.exception

    def test_exact_snapshots_moves_and_derived_digest_do_not_mutate_anything(self):
        before = copy.deepcopy(self.record)
        changes = copy.deepcopy(self.box.state.changes())
        files = {path: path.read_bytes() for path in (self.deckfile, self.deckfile.parent / "other.md")}
        answer = self.preview()
        self.assertEqual(set(answer), {"version", "plan", "base", "post_board", "opponent", "changes", "counts", "game_plan"})
        self.assertEqual(answer["plan"], {"id": self.record["id"], "sha256": self.saved["sha256"], "revision": 1})
        self.assertEqual(answer["base"], play._snapshot("casual/gruul-test", "target"))
        self.assertEqual(answer["post_board"]["sections"], self.record["after"])
        self.assertTrue(answer["post_board"]["derived"])
        self.assertEqual(answer["post_board"]["sha256"], play._hash(play._bytes(
            {key: answer["post_board"][key] for key in ("id", "version", "sections")})))
        self.assertNotEqual(answer["base"]["sha256"], answer["post_board"]["sha256"])
        self.assertEqual(answer["changes"], {key: self.record[key] for key in ("out", "in")})
        self.assertEqual(answer["counts"], {"main_before": 60, "main_after": 60, "sideboard_before": 4, "sideboard_after": 4})
        self.assertEqual(set(answer["opponent"]), {"id", "version", "title", "sha256"})
        self.assertEqual(self.record, before)
        self.assertEqual(self.box.state.play_get("sideboards", self.record["id"]), before)
        self.assertEqual(self.box.state.changes(), changes)
        self.assertEqual({path: path.read_bytes() for path in files}, files)
        self.assertNotIn("For this matchup.", json.dumps(answer))
        answer["base"]["sections"]["Deck"][0]["qty"] = 999
        self.assertEqual(self.preview()["base"], before["deck"])

    def test_split_printings_transfer_in_source_order_and_keep_other_sections(self):
        text = DECK.replace("4 Llanowar Elves (FDN) 227", "1 Llanowar Elves (FDN) 227 *F*\n3 Llanowar Elves")
        text = text.replace("2 Pick Your Poison (MKM) 170", "1 Pick Your Poison (MKM) 170\n1 Pick Your Poison")
        self.deckfile.write_text(text, encoding="utf-8")
        self.saved = self.save(self.plan(), play.save_sideboard)
        self.record = self.saved["record"]
        answer = self.preview()
        moved_elves = [row for row in answer["post_board"]["sections"]["Sideboard"] if row["name"] == "Llanowar Elves"]
        self.assertEqual([(row["qty"], row["set"], row["number"], row["finish"]) for row in moved_elves],
                         [(1, "fdn", "227", "foil"), (1, None, None, "nonfoil")])
        moved_in = [row for row in answer["post_board"]["sections"]["Deck"] if row["name"] == "Pick Your Poison"]
        self.assertEqual([(row["qty"], row["set"], row["number"]) for row in moved_in], [(1, "mkm", "170"), (1, None, None)])

    def test_proposed_budgets_follow_authoritative_constants_and_never_claim_remaining_work(self):
        with mock.patch.object(api.variants, "QUICK_GAMES", 100), \
                mock.patch.object(api.seqstats, "PAIRED_LOOKS", (200, 600)):
            budget = self.preview()["game_plan"]
        self.assertEqual(budget, {"status": "proposed", "cached_work": "not_checked", "remaining_games": None,
            "execution": "not_performed", "basis": api.BUDGET_BASIS,
            "modes": [{"id": "quick", "targets": [100], "base_games_max": 100, "post_board_games_max": 100,
                       "total_games_max": 200},
                      {"id": "ahead", "targets": [200, 600], "base_games_max": 600, "post_board_games_max": 600,
                       "total_games_max": 1200}]})

    def test_main_counts_include_commander_but_not_companion(self):
        row = {"qty": 1, "name": "Sol Ring", "set": None, "number": None, "finish": "nonfoil"}
        captured = copy.deepcopy(self.record)
        for key in ("deck", "opponent"):
            captured[key]["sections"].update(Commander=[copy.deepcopy(row)], Companion=[copy.deepcopy(row)])
            captured[key]["sha256"] = play._hash(play._bytes({field: captured[key][field]
                                                              for field in ("id", "version", "sections")}))
        captured["after"] = play._plan_moves(captured["deck"], captured["out"], captured["in"])["after"]
        with mock.patch.object(self.box.state, "play_get", return_value=captured), \
                mock.patch.object(api, "_current_snapshot", side_effect=[(copy.deepcopy(captured["deck"]), "commander"),
                                                                       (copy.deepcopy(captured["opponent"]), "commander")]):
            answer = api.preview_sideboard(captured["id"], rules.record_sha(captured))
        self.assertEqual((answer["counts"]["main_before"], answer["counts"]["main_after"]), (61, 61))
        self.assertEqual(answer["base"]["sections"]["Commander"], answer["post_board"]["sections"]["Commander"])
        self.assertEqual(answer["base"]["sections"]["Companion"], answer["post_board"]["sections"]["Companion"])

    def test_known_mixed_or_unverified_formats_keep_lists_without_numeric_game_budget(self):
        for kinds, reason in ((("constructed", "commander"), "format_mismatch"),
                               ((None, "commander"), "format_unknown"),
                               (("constructed", "unknown"), "format_unknown")):
            with self.subTest(kinds=kinds), mock.patch.object(api, "_current_snapshot", side_effect=[
                    (copy.deepcopy(self.record[key]), kind) for key, kind in zip(("deck", "opponent"), kinds)]):
                answer = self.preview()
            self.assertEqual(answer["post_board"]["sections"], self.record["after"])
            budget = answer["game_plan"]
            self.assertEqual((budget["status"], budget["reason"], budget["modes"]), ("unavailable", reason, []))
            self.assertIsNone(budget["remaining_games"])
            self.assertEqual((budget["cached_work"], budget["execution"]), ("not_checked", "not_performed"))

    def test_current_format_is_taken_from_same_summary_without_guessing_from_sections(self):
        original = play._deck_sections
        for kind, expected in (("casual", "constructed"), ("commander", "commander"), ("unrecognized", None)):
            summary, source = original(self.record["deck"]["id"], "target")
            summary = {**summary, "kind": kind}
            with self.subTest(kind=kind), mock.patch.object(play, "_deck_sections", return_value=(summary, source)):
                snapshot, mode = api._current_snapshot(self.record["deck"], lambda selected: True)
            self.assertEqual(mode, expected)
            self.assertEqual(snapshot["sha256"], self.record["deck"]["sha256"])
            self.assertNotIn("kind", snapshot)

    def test_bad_request_shapes_are_rejected_before_any_store_read(self):
        for ident, sha in ((None, None), ("x" * 32, "a" * 64), (self.record["id"], "a" * 65),
                           ("a" * 33, "a" * 64), ([], "a" * 64), (self.record["id"], True)):
            with self.subTest(ident=ident, sha=sha), mock.patch.object(state, "store") as store:
                self.error(400, "Choose a saved sideboard plan and its exact record version.",
                           lambda: api.preview_sideboard(ident, sha))
                store.assert_not_called()

    def test_changed_record_is_conflict_before_current_list_reads(self):
        with mock.patch.object(api, "_current_snapshot") as current:
            self.error(409, api.PLAN_CHANGED, lambda: api.preview_sideboard(self.record["id"], "0" * 64))
            current.assert_not_called()

    def test_deck_sideboard_printing_only_change_and_opponent_change_are_stale(self):
        for name, before, after in (("gruul-test.md", "2 Pick Your Poison (MKM) 170", "2 Pick Your Poison"),
                                    ("other.md", "52 Forest", "51 Forest"),
                                    ("gruul-test.md", "4 Llanowar Elves (FDN) 227", "4 Llanowar Elves")):
            path = self.deckfile.parent / name
            original = path.read_text(encoding="utf-8")
            with self.subTest(name=name, before=before):
                path.write_text(original.replace(before, after), encoding="utf-8")
                self.error(409, api.LISTS_CHANGED)
                path.write_text(original, encoding="utf-8")

    def test_missing_and_private_plan_have_fixed_404_even_with_stale_hash(self):
        self.error(404, api.NO_PLAN, lambda: api.preview_sideboard("0" * 32, "0" * 64))
        with mock.patch.object(play, "_sees_record", return_value=False), \
                mock.patch.object(play, "_checked") as checked, mock.patch.object(api, "_current_snapshot") as current:
            self.error(404, api.NO_PLAN, lambda: api.preview_sideboard(self.record["id"], "0" * 64))
            checked.assert_not_called()
            current.assert_not_called()

    def test_damaged_plan_moves_or_digest_fail_before_current_readers(self):
        for corrupt in (lambda record: record["in"][0].update(qty=1),
                        lambda record: record["deck"].update(sha256="0" * 64),
                        lambda record: record["after"]["Deck"][0].update(qty=99),
                        lambda record: record.update(version=True),
                        lambda record: record.update(notes="private fixture\x00note")):
            damaged = copy.deepcopy(self.record)
            corrupt(damaged)
            with self.subTest(corrupt=corrupt), mock.patch.object(self.box.state, "play_get", return_value=damaged), \
                    mock.patch.object(api, "_current_snapshot") as current:
                self.error(500, api.INVALID_PLAN)
                current.assert_not_called()

    def test_bounds_are_checked_before_record_hashing_or_current_readers(self):
        for corrupt in (lambda record: record["deck"]["sections"]["Deck"].extend(
                            [record["deck"]["sections"]["Deck"][0]] * api.MAX_ROWS),
                        lambda record: record["out"].extend([record["out"][0]] * 100),
                        lambda record: record.update(unexpected={"deep": ["private fixture"]}),
                        lambda record: record["deck"]["sections"]["Deck"][0].update(name="x" * 301),
                        lambda record: record["deck"]["sections"]["Deck"][0].update(qty=True)):
            damaged = copy.deepcopy(self.record)
            corrupt(damaged)
            with self.subTest(corrupt=corrupt), mock.patch.object(self.box.state, "play_get", return_value=damaged), \
                    mock.patch.object(play, "_checked") as checked, mock.patch.object(api, "_current_snapshot") as current:
                self.error(500, api.INVALID_PLAN)
                checked.assert_not_called()
                current.assert_not_called()

    def test_combined_rows_and_final_response_limits_are_explicit(self):
        damaged = copy.deepcopy(self.record)
        for snapshot in (damaged["deck"]["sections"], damaged["opponent"]["sections"], damaged["after"]):
            snapshot["Deck"] = [copy.deepcopy(snapshot["Deck"][0])] * 410
            snapshot.pop("Sideboard", None)
        with mock.patch.object(self.box.state, "play_get", return_value=damaged), \
                mock.patch.object(play, "_checked") as checked:
            self.error(500, api.INVALID_PLAN)
            checked.assert_not_called()
        with mock.patch.object(api, "MAX_RESPONSE", 10):
            self.error(503, api.UNAVAILABLE)

    def test_current_list_row_limit_precedes_per_card_resolution(self):
        summary, original = play._deck_sections(self.record["deck"]["id"], "target")
        def oversized(ident, version):
            source = copy.deepcopy(original)
            source["Deck"] *= api.MAX_ROWS
            return summary, source
        with mock.patch.object(play, "_deck_sections", side_effect=oversized), \
                mock.patch.object(api.cards, "resolve", side_effect=AssertionError("canonical loop must not start")):
            self.error(409, api.LISTS_CHANGED)

    def test_current_read_failures_and_store_failures_never_echo_diagnostics(self):
        for failure, status in ((ApiError(404, "private fixture deck"), 409),
                                (ApiError(503, "private fixture setup"), 503),
                                (ValueError("private fixture card"), 503)):
            with self.subTest(status=status), mock.patch.object(api, "_current_snapshot", side_effect=failure):
                self.error(status, api.UNAVAILABLE if status == 503 else api.LISTS_CHANGED)
        for failure in (state.Unavailable("private fixture credential"), RuntimeError("private fixture connection")):
            with self.subTest(failure=failure), mock.patch.object(self.box.state, "play_get", side_effect=failure):
                self.error(503, api.UNAVAILABLE)

    def test_one_existing_inventory_pin_is_reused_for_both_current_readers(self):
        original = api._current_snapshot
        pins = []
        def read(selected, reads):
            self.assertTrue(inventory.is_pinned())
            pins.append(inventory.current())
            return original(selected, reads)
        with mock.patch.object(api, "_current_snapshot", side_effect=read):
            self.preview()
        self.assertEqual(len(pins), 2)
        self.assertIs(pins[0], pins[1])
        # Keep this assertion at the preview's seam: legacy library summaries
        # legitimately create their own scoped view of the same supplied snapshot.
        with inventory.pinned(pins[0]), mock.patch.object(api, "_current_snapshot", side_effect=[
                (copy.deepcopy(self.record["deck"]), "constructed"),
                (copy.deepcopy(self.record["opponent"]), "constructed")]), \
                mock.patch.object(inventory, "pinned", side_effect=AssertionError("preview nested pin")):
            self.preview()

    def test_preview_never_writes_starts_jobs_uses_engine_or_reads_results_configuration_or_network(self):
        targets = ("decklab.lib.forge.engine.today", "decklab.lib.forge.install.status", "decklab.lib.forge.variants.run_test",
                   "decklab.lib.forge.runner.run", "decklab.lib.forge.saved.load", "decklab.lib.forge.common._settings",
                   "decklab.lib.inventory.apply", "subprocess.run", "urllib.request.urlopen")
        with contextlib.ExitStack() as stack:
            forbidden = [stack.enter_context(mock.patch(target, side_effect=AssertionError(target))) for target in targets]
            forbidden.append(stack.enter_context(mock.patch.object(self.box.state, "play_put", side_effect=AssertionError("state write"))))
            self.preview()
            for function in forbidden:
                function.assert_not_called()


class SideboardPreviewPrivacyTests(MixedFixture, ApiTestCase):
    def request(self, record_id):
        record = self.box.state.play_get("sideboards", record_id)
        return api.preview_sideboard(record_id, rules.record_sha(record))

    def assert_fixed(self, record_id, status, message):
        with self.assertRaises(ApiError) as caught:
            self.request(record_id)
        self.assertEqual((caught.exception.status, caught.exception.message, caught.exception.extra), (status, message, {}))

    def test_public_deck_or_game_does_not_publish_its_private_plan_even_to_admin(self):
        for viewer in ("matt", "user2"):
            with self.subTest(viewer=viewer), access.viewing(viewer), \
                    mock.patch.object(api.guard, "public_deck_spaces", return_value={"home", "user2", "user3"}), \
                    mock.patch.object(play, "_checked") as checked, mock.patch.object(api, "_current_snapshot") as current:
                self.assert_fixed(self.members_plan, 404, api.NO_PLAN)
                checked.assert_not_called()
                current.assert_not_called()

    def test_hidden_opponent_refusal_precedes_hash_validation_or_any_current_list_read(self):
        with access.viewing("user2"), mock.patch.object(play, "_checked") as checked, \
                mock.patch.object(api, "_current_snapshot") as current:
            self.assert_fixed(self.user2_plan, 409, api.PAIR_UNAVAILABLE)
            with self.assertRaises(ApiError) as caught:
                api.preview_sideboard(self.user2_plan, "0" * 64)
            self.assertEqual(caught.exception.message, api.PAIR_UNAVAILABLE)
            self.assertNotIn("gruul-test", str(caught.exception))
            checked.assert_not_called()
            current.assert_not_called()

    def test_removed_opponent_is_same_generic_refusal_without_lookup_or_hashing(self):
        record = self.box.state.play_get("sideboards", self.home_plan)
        record["opponent"] = copy.deepcopy(rules.REMOVED_DECK)
        with access.viewing("matt"), mock.patch.object(self.box.state, "play_get", return_value=record), \
                mock.patch.object(play, "_checked") as checked, mock.patch.object(api, "_current_snapshot") as current:
            self.assert_fixed(self.home_plan, 409, api.PAIR_UNAVAILABLE)
            checked.assert_not_called()
            current.assert_not_called()

    def test_own_plan_against_currently_public_opponent_is_read_only_and_visible(self):
        with access.viewing("user2"), mock.patch.object(api.guard, "public_deck_spaces", return_value={"home"}):
            answer = self.request(self.user2_plan)
        self.assertEqual(answer["base"]["id"], "user2/casual/r-elves")
        self.assertEqual(answer["opponent"]["id"], "casual/gruul-test")
        self.assertNotIn("notes", answer["opponent"])
        self.assertNotIn("sections", answer["opponent"])

    def test_foreign_corrupt_or_oversized_record_is_missing_before_bounds(self):
        record = self.box.state.play_get("sideboards", self.members_plan)
        record["notes"] = "private fixture" * 1000
        with access.viewing("matt"), mock.patch.object(self.box.state, "play_get", return_value=record), \
                mock.patch.object(api, "_bounded_record") as bounded, mock.patch.object(play, "_checked") as checked:
            self.assert_fixed(self.members_plan, 404, api.NO_PLAN)
            bounded.assert_not_called()
            checked.assert_not_called()


class SideboardPreviewRouteTests(ApiTestCase):
    def test_get_and_head_pass_record_id_without_deck_id_parsing(self):
        for method in ("GET", "HEAD"):
            handler = FixtureHandler(method)
            handler._deck_id = mock.Mock(side_effect=AssertionError("a plan id is not a deck id"))
            with mock.patch.object(api, "preview_sideboard", return_value={"version": 1}) as preview:
                self.assertTrue(feature_routes.dispatch(handler, ["play", "sideboard-preview"],
                                                        {"id": ["a" * 32], "sha256": ["b" * 64]}))
            preview.assert_called_once_with(id="a" * 32, sha256="b" * 64)
            self.assertEqual(handler.allowed, ("GET", "HEAD"))
            self.assertEqual(handler.sent, (200, {"version": 1}))
            handler._deck_id.assert_not_called()

    def test_write_and_repeated_or_extra_query_are_refused_before_preview(self):
        for method, query, status in (("POST", {}, 405), ("GET", {"id": ["a", "b"]}, 400),
                                      ("GET", {"profile": ["matt"]}, 400)):
            with self.subTest(method=method, query=query), mock.patch.object(api, "preview_sideboard") as preview:
                with self.assertRaises(ApiError) as caught:
                    feature_routes.dispatch(FixtureHandler(method), ["play", "sideboard-preview"], query)
                self.assertEqual(caught.exception.status, status)
                preview.assert_not_called()
