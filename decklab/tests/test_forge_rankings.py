"""Current-list rankings over saved evidence; never start Forge or use live data."""
import contextlib
import copy
import json
import unittest
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import rankings as rankings_api
from decklab.lib.forge import engine, field, lists, rankings, runner, saved, seqstats
from decklab.tests import test_forge_field as fixtures


ENGINE = {"kind": engine.KIND_DECKLAB, "complete": True}


def row(name, side=None, *, included=True, exclusion=None):
    entry = {"id": "casual/" + name, "title": name.upper(), "kind": "constructed",
             "version": "target", "card_sha": "sha-" + name, "side": side or name}
    return {"id": entry["id"], "title": entry["title"], "kind": "casual", "version": "target",
            "versions": ["target"], "card_sha": entry["card_sha"], "in_field": included,
            "exclusion": exclusion, "_entry": entry}


def pair(a, b, wins=80, games=100):
    return {(a, b, True): [wins, games], (a, b, False): [wins, games]}


class RankingsGraphTests(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(lists, "one_snapshot", contextlib.nullcontext),
                   mock.patch.object(engine, "read_only_today", return_value=ENGINE),
                   mock.patch.object(field, "_side_id", side_effect=lambda entry, eng: entry["side"]),
                   mock.patch.object(saved, "_stored", return_value=[]),
                   mock.patch.object(runner, "run", side_effect=AssertionError("Rankings must not start games"))]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def view(self, rows, data, **kwargs):
        with mock.patch.object(rankings, "_catalog", return_value=(copy.deepcopy(rows), [])), \
                mock.patch.object(field, "_bt_data", return_value=data) as read:
            answer = rankings.view(**kwargs)
        read.assert_called_once()
        self.assertEqual(set(answer), {"format", "rows", "groups", "notes", "error", "manual_excluded"})
        self.assertIsNone(answer["error"])
        self.assertNotIn("_entry", json.dumps(answer, allow_nan=False))
        return answer, {item["id"].split("/")[-1]: item for item in answer["rows"]}

    def test_connected_lists_share_one_fit_and_one_comparison_population(self):
        data = {**pair("a", "b"), **pair("b", "c", 70), **pair("a", "c", 90)}
        with mock.patch.object(seqstats, "bt_fit", wraps=seqstats.bt_fit) as fit, \
                mock.patch.object(seqstats, "bt_rating", wraps=seqstats.bt_rating) as rating:
            answer, found = self.view([row("c"), row("a"), row("b")], data)
        fit.assert_called_once_with(data)
        self.assertEqual(rating.call_count, 3)
        fitted = rating.call_args_list[0].args[0]
        self.assertTrue(all(call.args[0] is fitted for call in rating.call_args_list))
        self.assertTrue(all(call.args[2] == ["a", "b", "c"] for call in rating.call_args_list))
        self.assertEqual([item["id"] for item in answer["rows"]], ["casual/a", "casual/b", "casual/c"])
        self.assertEqual([found[name]["rating"]["rank"] for name in "abc"], [1, 2, 3])
        self.assertGreater(found["a"]["rating"]["value"], found["b"]["rating"]["value"])
        self.assertGreater(found["b"]["rating"]["value"], found["c"]["rating"]["value"])
        self.assertEqual(len(answer["groups"]), 1)
        self.assertEqual(answer["groups"][0]["players"], 3)
        for item in found.values():
            self.assertEqual(item["games"], 400)
            self.assertEqual(item["rating"]["of"], 3)
            self.assertEqual(set(item["rating"]),
                             {"value", "low", "high", "rank", "rank_low", "rank_high", "of", "h_points"})
            self.assertLessEqual(item["rating"]["low"], item["rating"]["value"])
            self.assertLessEqual(item["rating"]["value"], item["rating"]["high"])

    def test_disconnected_components_have_separate_ranks_and_fits(self):
        data = {**pair("a", "b"), **pair("c", "d", 60)}
        with mock.patch.object(seqstats, "bt_fit", wraps=seqstats.bt_fit) as fit:
            answer, found = self.view([row(name) for name in "abcd"], data)
        self.assertEqual(fit.call_count, 2)
        populations = [{side for cell in call.args[0] for side in cell[:2]} for call in fit.call_args_list]
        self.assertCountEqual(populations, [{"a", "b"}, {"c", "d"}])
        self.assertEqual(found["a"]["group"], found["b"]["group"])
        self.assertEqual(found["c"]["group"], found["d"]["group"])
        self.assertNotEqual(found["a"]["group"], found["c"]["group"])
        self.assertEqual([group["players"] for group in answer["groups"]], [2, 2])
        for name in "abcd":
            self.assertEqual(found[name]["rating"]["of"], 2)
            self.assertIn(found[name]["rating"]["rank"], (1, 2))
        self.assertIn("cannot be compared", " ".join(answer["notes"]))

    def test_aliases_share_one_physical_player_and_do_not_inflate_ranks(self):
        answer, found = self.view([row("a"), row("alias", "a"), row("b")], pair("a", "b"))
        self.assertEqual(found["a"]["rating"], found["alias"]["rating"])
        self.assertEqual(found["a"]["games"], found["alias"]["games"])
        self.assertEqual(found["a"]["group"], found["alias"]["group"])
        self.assertEqual(answer["groups"][0]["lists"], 3)
        self.assertEqual(answer["groups"][0]["players"], 2)
        self.assertTrue(all(item["rating"]["of"] == 2 for item in found.values()))

    def test_historical_bridge_links_current_lists_without_entering_rank_population(self):
        data = {**pair("a", "old"), **pair("old", "b", 70)}
        with mock.patch.object(seqstats, "bt_fit", wraps=seqstats.bt_fit) as fit:
            answer, found = self.view([row("a"), row("b")], data)
        fit.assert_called_once_with(data)
        self.assertEqual(set(found), {"a", "b"})
        self.assertEqual(found["a"]["group"], found["b"]["group"])
        self.assertTrue(all(item["rating"]["of"] == 2 for item in found.values()))
        self.assertEqual(answer["groups"][0]["players"], 2)
        self.assertIn("historical list nodes", " ".join(answer["notes"]))

    def test_one_current_list_with_many_historical_games_cannot_claim_a_settled_rank(self):
        answer, found = self.view([row("a")], pair("a", "old", wins=800, games=1000))
        self.assertIsNotNone(found["a"]["rating"])
        self.assertEqual(found["a"]["rating"]["of"], 1)
        self.assertEqual(found["a"]["games"], 2000)
        self.assertTrue(found["a"]["unsettled"])
        self.assertIn("cannot be compared", " ".join(found["a"]["reasons"]))
        self.assertEqual(answer["groups"][0]["players"], 1)

    def test_no_games_is_explicitly_unrated_and_does_not_fit(self):
        with mock.patch.object(seqstats, "bt_fit", wraps=seqstats.bt_fit) as fit:
            answer, found = self.view([row("a"), row("b")], {})
        fit.assert_not_called()
        self.assertEqual(answer["groups"], [])
        for item in found.values():
            self.assertIsNone(item["rating"])
            self.assertIsNone(item["group"])
            self.assertEqual(item["games"], 0)
            self.assertTrue(item["unsettled"])
            self.assertTrue(item["reasons"])

    def test_low_game_count_retains_a_rating_with_an_unsettled_reason(self):
        _, found = self.view([row("a"), row("b")], pair("a", "b", wins=1, games=2))
        for item in found.values():
            self.assertIsNotNone(item["rating"])
            self.assertEqual(item["games"], 4)
            self.assertTrue(item["unsettled"])
            self.assertIn("Too few", " ".join(item["reasons"]))

    def test_excluded_and_changed_lists_never_inherit_old_ratings(self):
        exclusion = "Left out by the field configuration."
        rows = [row("a", "a-new"), row("b"), row("excluded", included=False, exclusion=exclusion)]
        _, found = self.view(rows, {**pair("a-old", "b"), **pair("excluded", "b")})
        self.assertIsNone(found["a"]["rating"])
        self.assertEqual(found["a"]["games"], 0)
        self.assertTrue(found["a"]["reasons"])
        self.assertIsNone(found["excluded"]["rating"])
        self.assertIsNone(found["excluded"]["group"])
        self.assertEqual(found["excluded"]["exclusion"], exclusion)
        self.assertIn(exclusion, found["excluded"]["reasons"])

    def test_failed_fit_is_unrated_with_a_reason(self):
        with mock.patch.object(seqstats, "bt_fit", return_value={"converged": False, "cov": None}):
            answer, found = self.view([row("a"), row("b")], pair("a", "b"))
        self.assertEqual(answer["groups"], [])
        self.assertTrue(all(item["rating"] is None and item["reasons"] for item in found.values()))
        self.assertTrue(all(item["games"] == 200 for item in found.values()))

    def test_formats_are_strict_and_checked_before_reading_inventory(self):
        with mock.patch.object(lists, "one_snapshot") as snapshot:
            for fmt in ("", "casual", "constructed", "Commander ", None, []):
                with self.subTest(fmt=fmt), self.assertRaises(ValueError):
                    rankings.view(fmt)
        snapshot.assert_not_called()
        answer, _ = self.view([], {}, fmt="Commander")
        self.assertEqual(answer["format"], "Commander")


class RankingsInventoryTests(fixtures.FieldTestCase):
    def setUp(self):
        super().setUp()
        patches = [mock.patch.object(engine, "read_only_today", return_value=ENGINE),
                   mock.patch.object(field, "_side_id", side_effect=lambda entry, eng: "side-" + entry["card_sha"]),
                   mock.patch.object(runner, "run", side_effect=AssertionError("Rankings must not start games"))]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def catalog(self, fmt="Constructed", visible=None):
        with lists.one_snapshot():
            return rankings._catalog(fmt, visible, ENGINE)

    def test_real_catalog_follows_built_version_products_and_format_membership(self):
        rows, notes = self.catalog()
        by_list = {(item["id"], item["version"]): item for item in rows}
        selected = {key for key, item in by_list.items() if item["in_field"]}
        self.assertEqual(selected, {("casual/alpha", "target"), ("casual/beta", "owned"),
                                    ("casual/gamma", "target"), ("product/aggro", "target")})
        self.assertFalse(by_list[("casual/beta", "target")]["in_field"])
        self.assertIn("Play now", by_list[("casual/beta", "target")]["exclusion"])
        self.assertIsNone(by_list[("casual/broken", "target")]["_entry"])
        self.assertTrue(by_list[("casual/broken", "target")]["exclusion"])
        self.assertTrue(notes)
        self.assertFalse(any(item["kind"] == "commander" for item in rows))
        commander, _ = self.catalog("Commander")
        self.assertEqual({item["id"] for item in commander if item["in_field"]},
                         {"commander/cmdr", "product/precon"})

    def test_visibility_excludes_hidden_library_rows_and_error_details(self):
        rows, notes = self.catalog(visible=lambda deck_id: deck_id == "casual/alpha")
        self.assertEqual([item["id"] for item in rows], ["casual/alpha"])
        public = json.dumps({"rows": [{key: value for key, value in item.items() if key != "_entry"}
                                      for item in rows], "notes": notes})
        for hidden in ("casual/beta", "casual/broken", "Broken", "product/aggro"):
            self.assertNotIn(hidden, public)

    def test_identical_planned_and_play_now_versions_collapse_into_one_catalog_row(self):
        path = self.root / "magic" / "decks" / "casual" / "same.md"
        fixtures._write(path, fixtures.DECK.format(title="Same", status="built",
                        extra="- **Built version:** owned-only", cards="4 Opt\n4 Forest",
                        owned=fixtures.OWNED.format(card="Opt")))
        rows, _ = self.catalog()
        same = [item for item in rows if item["id"] == "casual/same"]
        self.assertEqual(len(same), 1)
        self.assertCountEqual(same[0]["versions"], ["target", "owned"])
        self.assertTrue(same[0]["in_field"])

    def saved_pair(self):
        a, b = self.entry("casual/alpha"), self.entry("casual/beta", "owned")
        result = self.fake.add_games(a, b, 240, rate=0.75)
        result.update(engine={"kind": engine.KIND_DECKLAB}, run_version=2)
        for side in result["sides"]:
            side["engine_id"] = "side-" + side["card_sha"]
        return result

    def test_saved_current_results_rate_actual_lists_but_changed_cards_start_unrated(self):
        result = self.saved_pair()
        with mock.patch.object(engine, "stored_key", return_value=result["key"]):
            before = rankings.view(results_dir=self.results)
            alpha = next(item for item in before["rows"] if item["id"] == "casual/alpha")
            self.assertIsNotNone(alpha["rating"])
            self.assertEqual(alpha["games"], 240)
            fixtures._write(self.root / "magic" / "decks" / "casual" / "alpha.md", fixtures.DECK.format(
                title="Alpha", status="building", extra="", cards="4 Opt\n20 Island", owned=""))
            after = rankings.view(results_dir=self.results)
        changed = next(item for item in after["rows"] if item["id"] == "casual/alpha")
        self.assertNotEqual(alpha["card_sha"], changed["card_sha"])
        self.assertIsNone(changed["rating"])
        self.assertEqual(changed["games"], 0)
        self.assertTrue(changed["unsettled"])
        self.assertIn("changed-list", " ".join(changed["reasons"]))
        self.assertEqual(self.fake.calls, [])

    def test_games_against_a_hidden_deck_never_rate_or_count_for_a_visible_list(self):
        # E10-S30: rows and ratings only over decks the viewer may see, so a visible list's
        # games, rating and rank leave out its saved games against a deck it can't see.
        result = self.saved_pair()
        with mock.patch.object(engine, "stored_key", return_value=result["key"]):
            everyone = rankings.view(results_dir=self.results)
            hidden = rankings.view(results_dir=self.results, visible=lambda deck_id: deck_id != "casual/beta")
        seen = next(item for item in everyone["rows"] if item["id"] == "casual/alpha")
        self.assertEqual(seen["games"], 240)
        alpha = next(item for item in hidden["rows"] if item["id"] == "casual/alpha")
        self.assertEqual((alpha["games"], alpha["rating"], alpha["group"]), (0, None, None))
        self.assertNotIn("casual/beta", json.dumps(hidden))
        self.assertNotIn("Earlier-engine", " ".join(alpha["reasons"]))
        keep = rankings._seen_result(lambda deck_id: deck_id != "casual/beta")
        self.assertFalse(keep(result))
        self.assertFalse(keep({"sides": []}))
        self.assertFalse(keep({"sides": [{"engine_id": "x"}]}))      # no deck named: not seen
        self.assertIsNone(rankings._seen_result(None))

    def test_earlier_or_unconfirmed_engine_results_are_not_current_evidence(self):
        self.saved_pair()
        with mock.patch.object(engine, "stored_key", return_value="different-engine-key"):
            answer = rankings.view(results_dir=self.results)
        self.assertTrue(all(item["rating"] is None and item["games"] == 0 for item in answer["rows"]))
        alpha = next(item for item in answer["rows"] if item["id"] == "casual/alpha")
        self.assertIn("Earlier-engine", " ".join(alpha["reasons"]))
        self.assertEqual(self.fake.calls, [])

    def test_same_cards_with_an_old_pilot_identity_are_explained_as_historical(self):
        result = self.saved_pair()
        old_alpha = next(side for side in result["sides"] if side["seen_as"][0]["id"] == "casual/alpha")
        old_alpha["engine_id"] = "same-cards-but-an-earlier-pilot-and-switches"
        with mock.patch.object(engine, "stored_key", return_value=result["key"]):
            answer = rankings.view(results_dir=self.results)
        alpha = next(item for item in answer["rows"] if item["id"] == "casual/alpha")
        self.assertEqual(alpha["card_sha"], old_alpha["card_sha"])
        self.assertEqual(alpha["version"], old_alpha["seen_as"][0]["version"])
        self.assertIsNone(alpha["rating"])
        self.assertEqual(alpha["games"], 0)
        self.assertIn("different-pilot", " ".join(alpha["reasons"]))

    def test_configured_field_removals_keep_current_lists_visible_but_unrated(self):
        fixtures._write(self.simulation, json.dumps({"version": 1, "field": {
            "Constructed": {"add": [], "remove": ["casual/alpha"]},
            "Commander": {"add": [], "remove": ["product/precon"]}}}))
        for fmt, deck_id in (("Constructed", "casual/alpha"), ("Commander", "product/precon")):
            with self.subTest(fmt=fmt):
                answer = rankings.view(fmt, results_dir=self.results)
                removed = next(item for item in answer["rows"] if item["id"] == deck_id)
                self.assertFalse(removed["in_field"])
                self.assertIn("field configuration", removed["exclusion"])
                self.assertIn(removed["exclusion"], removed["reasons"])
                self.assertIsNone(removed["rating"])
                self.assertIsNone(removed["group"])

    def test_custom_added_pairing_and_swapped_saved_alias_use_the_canonical_library_row(self):
        fixtures._write(self.simulation, json.dumps({"version": 1, "field": {
            "Constructed": {"add": ["pairing/elves+cats"], "remove": []}}}))
        pairing = self.entry("pairing/elves+cats")
        result = self.fake.add_games(pairing, self.entry("casual/alpha"), 240)
        result.update(engine={"kind": engine.KIND_DECKLAB}, run_version=2)
        for side in result["sides"]:
            side["engine_id"] = "side-" + side["card_sha"]
            if side["seen_as"][0]["id"].startswith("pairing/"):
                side["seen_as"][0]["id"] = "pairing/elves+cats"
                side["engine_id"] = "old-pairing-pilot"
        with mock.patch.object(engine, "stored_key", return_value=result["key"]):
            answer = rankings.view(results_dir=self.results)
        rows = [item for item in answer["rows"] if item["id"].startswith("pairing/")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "pairing/cats+elves")
        self.assertTrue(rows[0]["in_field"])
        self.assertIsNone(rows[0]["exclusion"])
        self.assertIsNone(rows[0]["rating"])
        self.assertIn("different-pilot", " ".join(rows[0]["reasons"]))

    def test_saved_owned_alias_matches_a_combined_planned_and_play_now_row(self):
        fixtures._write(self.root / "magic" / "decks" / "casual" / "same.md", fixtures.DECK.format(
            title="Same", status="built", extra="- **Built version:** owned-only", cards="4 Opt\n4 Forest",
            owned=fixtures.OWNED.format(card="Opt")))
        result = self.fake.add_games(self.entry("casual/same", "owned"), self.entry("casual/alpha"), 240)
        result.update(engine={"kind": engine.KIND_DECKLAB}, run_version=2)
        for side in result["sides"]:
            side["engine_id"] = "side-" + side["card_sha"]
            if side["seen_as"][0]["id"] == "casual/same":
                side["engine_id"] = "old-owned-list-pilot"
        with mock.patch.object(engine, "stored_key", return_value=result["key"]):
            answer = rankings.view(results_dir=self.results)
        same = next(item for item in answer["rows"] if item["id"] == "casual/same")
        self.assertEqual(same["version"], "target")
        self.assertCountEqual(same["versions"], ["target", "owned"])
        self.assertIsNone(same["rating"])
        self.assertIn("different-pilot", " ".join(same["reasons"]))

    def test_unconfirmed_engine_readiness_keeps_saved_games_unrated(self):
        result = self.saved_pair()
        with mock.patch.object(engine, "stored_key", return_value=result["key"]), \
                mock.patch.object(engine, "read_only_today", return_value={**ENGINE, "complete": False}):
            answer = rankings.view(results_dir=self.results)
        self.assertTrue(all(item["rating"] is None and item["games"] == 0 for item in answer["rows"]))
        self.assertIn("cannot be confirmed", " ".join(answer["notes"]))
        self.assertEqual(self.fake.calls, [])

    def test_api_wrapper_uses_one_snapshot_and_deck_visibility_without_writes(self):
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob("*") if path.is_file()}
        backend = inventory.backend()
        with mock.patch.object(rankings_api, "_require_cards"), \
                mock.patch.object(rankings_api.forge_runs, "_forge_module"), \
                mock.patch.object(rankings_api.guard, "sees_deck", side_effect=lambda name, profile=False: name == "casual/alpha"), \
                mock.patch.object(backend, "load", wraps=backend.load) as load, \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("Rankings cannot write")) as apply:
            answer = rankings_api.rankings_view()
        self.assertIsNone(answer["error"])
        self.assertEqual([item["id"] for item in answer["rows"]], ["casual/alpha"])
        self.assertNotIn("casual/beta", json.dumps(answer))
        load.assert_called_once()
        apply.assert_not_called()
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(self.fake.calls, [])

    def test_api_service_failure_is_explicit_and_keeps_private_details_in_the_log(self):
        secret = "C:/private/rankings-secret.json: Hidden private deck title"
        with mock.patch.object(rankings_api, "_require_cards"), \
                mock.patch.object(rankings_api.forge_runs, "_forge_module"), \
                mock.patch.object(rankings, "view", side_effect=RuntimeError(secret)), \
                mock.patch.object(rankings_api.common, "_log") as log:
            answer = rankings_api.rankings_view()
        self.assertTrue(answer["error"])
        self.assertEqual(answer["rows"], [])
        self.assertEqual(answer["groups"], [])
        self.assertNotIn(secret, json.dumps(answer))
        self.assertNotIn("Hidden private", json.dumps(answer))
        self.assertIn(secret, " ".join(str(call) for call in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
