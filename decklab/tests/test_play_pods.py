"""Commander pods use disposable snapshots and MemoryStore, never configured data.

These fixtures exercise explicit review, permission ordering, historical lists and
the private/public projection. Pod results remain separate from every 1v1 list.
"""
import copy
import json
import unittest
from unittest import mock

from decklab.lib import access, inventory, state
from decklab.lib.api import play_pods as pods, play_records as play
from decklab.lib.state import rules
from decklab.tests import household_config
from decklab.tests.test_api import ApiTestCase, ELF_COMMANDER, _write

ACTOR = state.Actor("test", "Fixture")


def encoded(data):
    return json.dumps(data).encode("utf-8")


def selector(snapshot):
    return {key: snapshot[key] for key in ("id", "version", "sha256")}


class PodApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        active = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        active.__enter__()
        self.addCleanup(active.__exit__, None, None, None)
        self.box.stack.enter_context(mock.patch.object(play, "_play_today", return_value="2026-10-28"))
        self.a = self.box.magic / "decks/commander/pod-a.md"
        self.b = self.box.magic / "decks/commander/pod-b.md"
        _write(self.a, ELF_COMMANDER.replace("Elf Commander", "Pod fixture A").replace("wife", "user"))
        _write(self.b, ELF_COMMANDER.replace("Elf Commander", "Pod fixture B"))
        _write(self.box.magic / "people/user2/decks/commander/pod-a.md",
               ELF_COMMANDER.replace("Elf Commander", "Member fixture").replace("- **Played by:** wife\n", ""))

    def pod(self, count=3, *, deck_id="commander/pod-a", profile="matt"):
        with access.using(None), access.viewing(None):
            snapshot = play._snapshot(deck_id, "target")
        seats = [{"seat_id": "s1", "type": "deck", "player": "Private player", "deck": selector(snapshot)},
                 {"seat_id": "s2", "type": "external", "player": "Guest A", "commander": "Private commander A"},
                 {"seat_id": "s3", "type": "external", "player": "Guest B", "commander": "Private commander B"}]
        if count == 4:
            seats.append({"seat_id": "s4", "type": "external", "player": "Guest C", "commander": ""})
        return {"profile": profile, "id": None, "sha256": None, "preview": True,
                "mode": "pod", "game_version": 2, "date": "2026-10-27", "result": "s1",
                "notes": "Private pod notes", "seats": seats}

    def save(self, data):
        preview = pods.save_pod(encoded(data))
        return pods.save_pod(encoded({**data, "id": preview["id"], "preview": False,
                                     "review_sha256": preview["review_sha256"]}))

    def correction(self, saved):
        record = saved["record"]
        seats = copy.deepcopy(record["seats"])
        for seat in seats:
            if seat["type"] == "deck":
                seat["deck"] = selector(seat["deck"])
        return {"profile": "matt", "id": record["id"], "sha256": saved["sha256"], "preview": True,
                **{key: record[key] for key in ("mode", "game_version", "date", "result", "notes")}, "seats": seats}

    def publish(self, thing):
        self.box.state.visibility_set("home", thing, True, ACTOR, "Publish fixture")

    def test_three_and_four_seat_previews_are_read_only_then_save_one_change(self):
        for count in (3, 4):
            data = self.pod(count)
            preview = pods.save_pod(encoded(data))
            self.assertTrue(preview["preview"])
            self.assertNotIn("version", preview["record"])
            before = len(self.box.state.changes())
            saved = pods.save_pod(encoded({**data, "id": preview["id"], "preview": False,
                                         "review_sha256": preview["review_sha256"]}))
            record = saved["record"]
            self.assertEqual((record["version"], record["game_version"], record["kind"]), (1, 2, "games"))
            self.assertEqual(len(record["seats"]), count)
            self.assertEqual(len(self.box.state.changes()), before + 1)
            self.assertEqual(saved["sha256"], rules.record_sha(record))
            self.assertEqual(self.box.state.play_get("games", record["id"]), record)
            change = self.box.state.changes()[-1]
            self.assertEqual(change["message"], f"Save {count}-player pod game")
            self.assertEqual(change["rows"][0]["after"]["deck_ids"], ["commander/pod-a"])

    def test_explicit_confirmation_is_required_and_binds_every_label_and_result(self):
        data = self.pod()
        preview = pods.save_pod(encoded(data))
        self.assertApiError(409, pods.save_pod, encoded({**data, "id": preview["id"], "preview": False}))
        for field, value in (("result", "draw"), ("notes", "Changed"), ("date", "2026-10-26")):
            self.assertApiError(409, pods.save_pod, encoded({**data, field: value, "id": preview["id"],
                                "preview": False, "review_sha256": preview["review_sha256"]}))
        changed = copy.deepcopy(data)
        changed["seats"][1]["commander"] = "Another commander"
        self.assertApiError(409, pods.save_pod, encoded({**changed, "id": preview["id"], "preview": False,
                            "review_sha256": preview["review_sha256"]}))
        self.assertEqual(self.box.state.play_list("games"), [])

    def test_duplicate_confirmation_does_not_duplicate_the_record(self):
        data = self.pod()
        preview = pods.save_pod(encoded(data))
        confirmed = {**data, "id": preview["id"], "preview": False, "review_sha256": preview["review_sha256"]}
        pods.save_pod(encoded(confirmed))
        self.assertApiError(409, pods.save_pod, encoded(confirmed))
        self.assertEqual(len(self.box.state.play_list("games")), 1)

    def test_historical_snapshot_reused_in_same_stable_seat_after_current_deck_changes(self):
        saved = self.save(self.pod())
        old = copy.deepcopy(saved["record"]["seats"][0]["deck"])
        self.a.write_text(ELF_COMMANDER.replace("Elf Commander", "Changed current title")
                          .replace("Commander\n", "Casual 60-card, 1v1\n", 1), encoding="utf-8")
        data = self.correction(saved)
        data["result"] = "s2"
        with mock.patch.object(play, "_snapshot", side_effect=AssertionError("Historical correction read current list")):
            corrected = self.save(data)
        self.assertEqual(corrected["record"]["seats"][0]["deck"], old)
        self.assertEqual(corrected["record"]["revision"], 2)
        self.assertEqual(corrected["record"]["created_on"], saved["record"]["created_on"])

    def test_old_snapshot_cannot_be_moved_to_another_stable_seat(self):
        saved = self.save(self.pod())
        data = self.correction(saved)
        self.a.write_text(ELF_COMMANDER.replace("Elf Commander", "New title").replace("1 Llanowar Elves", "2 Llanowar Elves"),
                          encoding="utf-8")
        data["seats"][0]["seat_id"], data["seats"][1]["seat_id"] = "s2", "s1"
        self.assertApiError(409, pods.save_pod, encoded(data))

    def test_changed_list_between_preview_and_save_is_refused(self):
        data = self.pod()
        preview = pods.save_pod(encoded(data))
        self.a.write_text(ELF_COMMANDER.replace("1 Llanowar Elves", "2 Llanowar Elves"), encoding="utf-8")
        self.assertApiError(409, pods.save_pod, encoded({**data, "id": preview["id"], "preview": False,
                            "review_sha256": preview["review_sha256"]}))
        self.assertEqual(self.box.state.play_list("games"), [])

    def test_store_compare_and_swap_conflict_is_409_and_keeps_old_record(self):
        saved = self.save(self.pod())
        data = self.correction(saved)
        data["result"] = "draw"
        preview = pods.save_pod(encoded(data))
        with mock.patch.object(self.box.state, "play_put", side_effect=state.Conflict(rules.CHANGED_MESSAGE)):
            self.assertApiError(409, pods.save_pod, encoded({**data, "preview": False,
                                "review_sha256": preview["review_sha256"]}))
        self.assertEqual(self.box.state.play_get("games", saved["record"]["id"]), saved["record"])

    def test_stale_record_hash_refuses_without_replacing_data(self):
        saved = self.save(self.pod())
        data = self.correction(saved)
        self.save({**data, "result": "draw"})
        self.assertApiError(409, pods.save_pod, encoded(data), contains=rules.CHANGED_MESSAGE)

    def test_external_seats_never_get_snapshots_and_all_external_is_refused(self):
        data = self.pod()
        data["seats"][0] = {"seat_id": "s1", "type": "external", "player": "Another guest", "commander": ""}
        self.assertApiError(400, pods.save_pod, encoded(data))
        data = self.pod()
        data["seats"][1]["deck"] = data["seats"][0]["deck"]
        self.assertApiError(400, pods.save_pod, encoded(data))

    def test_payload_cannot_supply_a_snapshot_or_a_sideboard_plan(self):
        for extra in ({"sections": {}}, {"title": "Invented"}, {"plan_id": "0" * 32}, {"hidden": True}):
            data = self.pod()
            data["seats"][0]["deck"].update(extra)
            self.assertApiError(400, pods.save_pod, encoded(data))

    def test_current_decks_must_be_commander_before_snapshot_is_read(self):
        data = self.pod()
        _write(self.box.magic / "decks/casual/pod-casual.md",
               ELF_COMMANDER.replace("- **Format:** Commander", "- **Format:** Casual 60-card, 1v1"))
        snapshot = play._snapshot("casual/pod-casual", "target")
        data["seats"][0]["deck"] = selector(snapshot)
        with mock.patch.object(play, "_snapshot", side_effect=AssertionError("Wrong format captured")):
            self.assertApiError(400, pods.save_pod, encoded(data), contains="Commander")

    def test_hidden_raw_deck_is_404_before_stale_hash_or_snapshot(self):
        data = self.pod(deck_id="user2/commander/pod-a")
        data.update(id="a" * 32, sha256="0" * 64)
        with mock.patch.object(inventory, "current", side_effect=AssertionError("Inventory snapshot read")), \
                mock.patch.object(play.decks, "find_summary", side_effect=AssertionError("Private summary read")), \
                mock.patch.object(play, "_snapshot", side_effect=AssertionError("Private list read")):
            error = self.assertApiError(404, pods.save_pod, encoded(data))
        self.assertEqual(error.message, "No deck 'user2/commander/pod-a'")

    def test_hidden_canonical_deck_is_404_before_stale_hash_or_snapshot(self):
        data = self.pod()
        data.update(id="a" * 32, sha256="0" * 64)
        with mock.patch.object(inventory, "resolve_deck_id", return_value="user2/commander/pod-a"), \
                mock.patch.object(play, "_snapshot", side_effect=AssertionError("Private list read")):
            error = self.assertApiError(404, pods.save_pod, encoded(data))
        self.assertEqual(error.message, "No deck 'commander/pod-a'")

    def test_public_other_space_deck_is_readable_but_never_a_recording_seat(self):
        self.box.state.visibility_set("user2", "decks", True, ACTOR, "Publish fixture decks")
        data = self.pod(deck_id="user2/commander/pod-a")
        with mock.patch.object(play, "_snapshot", side_effect=AssertionError("Other space captured")):
            self.assertApiError(403, pods.save_pod, encoded(data), contains="own collection")

    def test_home_member_needs_one_editable_deck_not_every_deck_seat(self):
        data = self.pod(profile="user1")
        own = play._snapshot("commander/pod-b", "target")
        data["seats"][1] = {"seat_id": "s2", "type": "deck", "player": "Second player", "deck": selector(own)}
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            saved = self.save(data)
        self.assertEqual(len(saved["record"]["seats"]), 3)

    def test_home_member_cannot_record_when_none_of_the_decks_is_editable(self):
        data = self.pod(profile="user1")
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            self.assertApiError(403, pods.save_pod, encoded(data))

    def test_pods_and_two_player_records_cannot_change_mode(self):
        from decklab.tests.test_play_records import PlayFixture
        saved = self.save(self.pod())
        fixture = PlayFixture()
        fixture.box = self.box
        fixture.write_decks()
        old = fixture.save(fixture.game())
        data = self.pod()
        data["date"] = "2026-10-08"
        data.update(id=old["record"]["id"], sha256=old["sha256"])
        self.assertApiError(400, pods.save_pod, encoded(data), contains="cannot replace")
        data = fixture.game()
        data.update(id=saved["record"]["id"], sha256=saved["sha256"])
        self.assertApiError(400, play.save_game, encoded(data), contains="cannot replace")

    def test_pod_overview_has_separate_buckets_and_positive_own_space_choices(self):
        saved = self.save(self.pod())
        overview = play.play_overview()
        self.assertEqual(overview["games"], [])
        self.assertEqual(overview["pods"], [{"record": saved["record"], "sha256": saved["sha256"], "can": {"edit": True}}])
        self.assertTrue(overview["pod_lists"])
        self.assertTrue(all(play._deck_space(item["id"]) == "home" and type(item["can_record"]) is bool
                            for item in overview["pod_lists"]))
        self.assertEqual(play.play_overview("commander/pod-a")["pods"], overview["pods"])
        self.assertEqual(play.play_overview("casual/gruul-test")["pods"], [])

    def test_private_pod_is_hidden_outside_its_space_even_when_decks_public(self):
        self.save(self.pod())
        self.publish("decks")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            answer = play.play_overview()
        self.assertEqual(answer["pods"], [])
        self.assertTrue(all(item["id"].startswith("user2/") for item in answer["pod_lists"]))

    def test_public_game_redacts_all_external_labels_and_private_deck_data(self):
        saved = self.save(self.pod())
        self.publish("games")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            entry = play.play_overview()["pods"][0]
        record = entry["record"]
        self.assertEqual(record["result"], "s1")
        self.assertEqual(record["date"], "2026-10-27")
        self.assertEqual(entry["can"], {"edit": False})
        self.assertEqual([seat["player"] for seat in record["seats"]], ["Player 1", "Player 2", "Player 3"])
        self.assertTrue(record["seats"][0]["deck"]["hidden"])
        self.assertEqual(record["seats"][1]["commander"], "")
        self.assertNotIn("space", record)
        self.assertEqual((record["notes"], record["updated_by"]), ("", "someone"))
        for value in ("Guest", "Private", "Pod fixture", "commander/pod-a", "Llanowar Elves"):
            self.assertNotIn(value, json.dumps(entry))
        self.assertEqual(self.box.state.play_get("games", saved["record"]["id"]), saved["record"])

    def test_public_game_and_decks_may_show_list_but_never_external_labels(self):
        self.save(self.pod())
        self.publish("games")
        self.publish("decks")
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            record = play.play_overview()["pods"][0]["record"]
        self.assertEqual(record["seats"][0]["deck"]["id"], "commander/pod-a")
        self.assertNotIn("Guest", json.dumps(record))
        self.assertNotIn("Private", json.dumps(record))

    def test_public_game_cannot_be_changed_even_with_stale_token(self):
        saved = self.save(self.pod())
        self.publish("games")
        data = self.correction(saved)
        data.update(profile="user2", sha256="0" * 64)
        data["seats"][0]["deck"] = self.pod(deck_id="user2/commander/pod-a")["seats"][0]["deck"]
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertApiError(403, pods.save_pod, encoded(data))

    def test_anonymous_script_read_keeps_private_labels_but_browser_does_not(self):
        saved = self.save(self.pod())
        self.assertEqual(play._view("games", saved["record"], None, True), saved["record"])
        self.assertNotIn("Private", json.dumps(play._view("games", saved["record"], None, False)))

    def test_unavailable_store_refuses_without_inventory_reads(self):
        data = self.pod()
        with mock.patch.object(state, "reachable", return_value=False), \
                mock.patch.object(inventory, "resolve_deck_id", side_effect=AssertionError("Inventory read")):
            self.assertApiError(503, pods.save_pod, encoded(data))

    def test_body_limit_is_bounded_before_any_profile_or_state_read(self):
        with mock.patch.object(pods, "_writer", side_effect=AssertionError("Profile read")):
            self.assertApiError(413, pods.save_pod, b" " * (pods.MAX_BODY + 1))

    def test_malformed_shapes_dates_markers_seats_and_text_are_refused_without_writes(self):
        for change in ({"mode": "legacy"}, {"game_version": True}, {"game_version": 3}, {"result": "s4"},
                       {"date": "2026-10-29"}, {"date": "2026-02-30"}, {"date": "20261027"},
                       {"preview": 1}, {"seats": []}, {"notes": "x" * 2001}, {"sides": []}):
            with self.subTest(change=change):
                self.assertApiError(400, pods.save_pod, encoded({**self.pod(), **change}))
        for change in ({"id": 0}, {"id": False}, {"id": ""}, {"sha256": 0}, {"sha256": "bad"}):
            with self.subTest(change=change):
                self.assertApiError(400, pods.save_pod, encoded({**self.pod(), **change}))
        for index, key, value in ((0, "seat_id", []), (0, "seat_id", "s2"), (0, "player", ""),
                                   (1, "player", "a\nb"), (1, "player", "x" * 81),
                                   (1, "commander", "x\tlabel"), (1, "commander", "x" * 301)):
            with self.subTest(index=index, key=key, value=value):
                data = self.pod()
                data["seats"][index][key] = value
                self.assertApiError(400, pods.save_pod, encoded(data))
        data = self.pod()
        data["seats"][1]["player"] = "\ud800"
        self.assertApiError(400, pods.save_pod, encoded(data))
        self.assertEqual(self.box.state.play_list("games"), [])

    def test_three_seats_need_not_be_contiguous_and_a_removed_winner_is_invalid(self):
        data = self.pod()
        data["seats"][2]["seat_id"] = "s4"
        data["result"] = "s4"
        self.assertEqual(self.save(data)["record"]["result"], "s4")
        data["result"] = "s3"
        self.assertApiError(400, pods.save_pod, encoded(data))

    def test_damaged_pod_hash_and_snapshot_are_not_presented_as_a_game(self):
        saved = self.save(self.pod())
        damaged = copy.deepcopy(saved["record"])
        damaged["seats"][0]["deck"]["sha256"] = "0" * 64
        self.assertApiError(500, play._checked, "games", damaged["id"], damaged)
        damaged = copy.deepcopy(saved["record"])
        damaged["version"] = True
        self.assertApiError(500, play._checked, "games", damaged["id"], damaged)

    def test_pods_and_partial_markers_are_excluded_before_any_pair_comparison(self):
        from decklab.lib.api import play_comparison
        saved = self.save(self.pod())
        rows = [saved["record"], {"mode": "pod", "sides": [{}, {}]},
                {"game_version": 2, "sides": [{}, {}]}, {"mode": "other", "game_version": 2}, None]
        with mock.patch.object(play_comparison, "_pair", return_value=(object(), "commander")), \
                mock.patch.object(self.box.state, "play_list", return_value=rows), \
                mock.patch.object(play, "_sees_record", side_effect=AssertionError("Non-1v1 candidate")), \
                mock.patch.object(play_comparison, "_fingerprint", side_effect=AssertionError("Pod fingerprint")):
            answer = play_comparison._summary([], "Commander", {"id": "matt"}, False)
        self.assertEqual((answer["games"], answer["wins"], answer["draws"]), (0, [0, 0], 0))


class PodRouteTests(unittest.TestCase):
    def test_route_uses_explicit_bounded_body_and_original_write_guards(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = b'{"fixture":true}'
        with mock.patch.object(pods, "save_pod", return_value={"preview": True}) as save:
            self.assertTrue(feature_routes.dispatch(handler, ["play", "pod"], {}))
        handler._allow.assert_called_once_with("POST")
        handler._no_query.assert_called_once_with({})
        handler._write_body.assert_called_once_with(16 * 1024)
        save.assert_called_once_with(b'{"fixture":true}')
        handler._send_json.assert_called_once_with(200, {"preview": True})
