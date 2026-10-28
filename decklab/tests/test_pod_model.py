"""Pod identity and text checks, using pure records with no configured resources."""
import copy
import unittest
from unittest import mock

from decklab.lib import config, profiles, state
from decklab.lib.state import pods, rules
from decklab.lib.state.play import record_deck_ids


def selection(deck_id="commander/fixture"):
    return {"id": deck_id, "version": "target", "sha256": "a" * 64}


def pod(*, space="home", count=3):
    deck_id = "commander/fixture" if space == "home" else f"{space}/commander/fixture"
    seats = [{"seat_id": "s1", "type": "deck", "player": "Player", "deck": selection(deck_id)}]
    seats += [{"seat_id": f"s{i}", "type": "external", "player": f"Opponent {i}",
               "commander": ""} for i in range(2, count + 1)]
    return {"mode": "pod", "game_version": 2, "space": space, "date": "2026-10-28",
            "result": "s1", "notes": "", "seats": seats}


def full_record(content=None):
    return {"version": 1, "id": "b" * 32, "kind": "games", "revision": 1,
            "created_on": "2026-10-28T01:02:03+00:00", "updated_on": "2026-10-28T01:02:03+00:00",
            "updated_by": "Test", **(pod() if content is None else content)}


class PodModeTests(unittest.TestCase):
    def test_only_unmarked_content_is_legacy(self):
        for value in ({}, {"sides": []}, {"notes": "old content"}):
            self.assertEqual(pods.mode(value), "legacy")
        self.assertEqual(pods.mode(pod()), "pod")

    def test_partial_unknown_or_python_equal_markers_are_refused(self):
        values = [None, [], "pod", {"mode": "pod"}, {"game_version": 2},
                  {"mode": "legacy", "game_version": 1}, {"mode": "pod", "game_version": 2.0},
                  {"mode": "pod", "game_version": True}, {"mode": "pod", "game_version": "2"},
                  {"mode": "pod", "game_version": 3}, {"mode": None, "game_version": None}]
        for value in values:
            with self.subTest(value=value), self.assertRaises(state.Invalid):
                pods.mode(value)

    def test_marked_damage_cannot_fall_back_to_legacy_deck_ids(self):
        for marker in ({"mode": "pod"}, {"game_version": 2}, {"mode": "other", "game_version": 2}):
            with self.subTest(marker=marker), self.assertRaises(state.Invalid):
                record_deck_ids("games", {"sides": [{"id": "casual/a"}, {"id": "casual/b"}], **marker})


class PodModelTests(unittest.TestCase):
    def assert_invalid(self, change):
        content = pod()
        change(content)
        with self.assertRaises(state.Invalid):
            pods.record_deck_ids(content)

    def test_three_and_four_seats_and_preview_without_headers(self):
        for count in (3, 4):
            content = pod(count=count)
            self.assertEqual(pods.record_deck_ids(content), ["commander/fixture"])
            self.assertEqual(record_deck_ids("games", content), ["commander/fixture"])

    def test_member_owner_and_validation_need_no_configuration(self):
        content = pod(space="user2")
        with mock.patch.object(config, "load", side_effect=AssertionError("read config")), \
                mock.patch.object(profiles, "read", side_effect=AssertionError("read profiles")):
            self.assertEqual(pods.record_deck_ids(content), ["user2/commander/fixture"])

    def test_actual_deck_ids_keep_seat_order_and_mirrors(self):
        content = pod(count=4)
        content["seats"][1] = {"seat_id": "s2", "type": "deck", "player": "Another player",
                               "deck": selection("commander/other")}
        content["seats"][3] = {"seat_id": "s4", "type": "deck", "player": "Mirror",
                               "deck": selection()}
        self.assertEqual(pods.record_deck_ids(content),
                         ["commander/fixture", "commander/other", "commander/fixture"])

    def test_noncontiguous_stable_ids_and_seat_reordering_preserve_winner(self):
        content = pod()
        content["seats"][1]["seat_id"] = "s4"
        content["seats"].reverse()
        content["result"] = "s4"
        self.assertEqual(pods.record_deck_ids(content), ["commander/fixture"])

    def test_draw_and_every_present_winner_are_valid(self):
        for winner in ("s1", "s2", "s3", "draw"):
            content = pod()
            content["result"] = winner
            self.assertEqual(pods.record_deck_ids(content), ["commander/fixture"])

    def test_unknown_or_removed_winner_is_refused(self):
        for value in ("s4", "a", "b", "", None, 1, [], {}):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content.update(result=value))

    def test_seat_count_and_container_are_bounded(self):
        for value in (None, {}, (), [], pod()["seats"][:2], pod(count=5)["seats"]):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content.update(seats=value))

    def test_seat_ids_are_distinct_and_from_fixed_set(self):
        for value in ("s1", "s0", "s5", "S2", 2, None, []):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content["seats"][1].update(seat_id=value))

    def test_seat_objects_and_types_are_strict(self):
        for value in (None, [], "external", {}):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content["seats"].__setitem__(1, value))
        for value in (None, "unknown", "Deck", 1):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content["seats"][1].update(type=value))

    def test_all_external_is_refused(self):
        self.assert_invalid(lambda content: content["seats"].__setitem__(
            0, {"seat_id": "s1", "type": "external", "player": "Player", "commander": "Label"}))

    def test_every_deck_must_belong_to_recording_space(self):
        for value in ("user2/commander/fixture", "user3/casual/fixture"):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content["seats"][0]["deck"].update(id=value))
        for value in ("home", "user3"):
            content = pod(space="user2")
            content["space"] = value
            with self.subTest(value=value), self.assertRaises(state.Invalid):
                pods.record_deck_ids(content)

    def test_recording_space_must_have_valid_syntax(self):
        for value in (None, "", "../user2", "User2", "user--2", "people", "casual", [], 1):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content.update(space=value))

    def test_deck_ids_use_safe_syntax_without_requiring_a_current_deck(self):
        for value in ("commander/../hidden", "commander/.hidden", "commander/a/b", "commander/a\\b",
                      "commander/a:b", "commander/", "commander/a\x7f", "commander/\ud800", "x" * 201):
            with self.subTest(value=repr(value)):
                self.assert_invalid(lambda content, value=value: content["seats"][0]["deck"].update(id=value))

    def test_selector_version_and_sha_are_required_and_strict(self):
        for key, value in (("version", "other"), ("version", None), ("version", []), ("sha256", "A" * 64),
                           ("sha256", "a" * 63), ("sha256", 1), ("sha256", None)):
            with self.subTest(key=key, value=value):
                self.assert_invalid(lambda content, key=key, value=value: content["seats"][0]["deck"].update({key: value}))
        for key in ("id", "version", "sha256"):
            with self.subTest(missing=key):
                self.assert_invalid(lambda content, key=key: content["seats"][0]["deck"].pop(key))

    def test_snapshot_keys_allow_captured_lists_but_never_removal_or_hidden_markers(self):
        content = pod()
        content["seats"][0]["deck"].update(title="Historic deck", sections={"Deck": []})
        self.assertEqual(pods.record_deck_ids(content), ["commander/fixture"])
        for key in ("removed", "hidden", "player", "commander"):
            with self.subTest(key=key):
                self.assert_invalid(lambda content, key=key: content["seats"][0]["deck"].update({key: True}))

    def test_external_seats_never_carry_snapshots_ids_or_unknown_metadata(self):
        for key, value in (("deck", selection()), ("id", "commander/fixture"), ("sha256", "a" * 64),
                           ("hidden", True), ("removed", True), ("notes", "private")):
            with self.subTest(key=key):
                self.assert_invalid(lambda content, key=key, value=value: content["seats"][1].update({key: value}))

    def test_deck_seats_reject_extra_private_labels_or_missing_fields(self):
        self.assert_invalid(lambda content: content["seats"][0].update(commander="Label"))
        for key in ("deck", "player", "type", "seat_id"):
            with self.subTest(key=key):
                self.assert_invalid(lambda content, key=key: content["seats"][0].pop(key))

    def test_label_limits_control_characters_and_lone_surrogates_are_rejected(self):
        for value in ("", " ", "p" * 81, " A", "A ", "A\nB", "A\tB", "A\x00B", "A\x7fB", "\ud800", None):
            with self.subTest(value=repr(value)):
                self.assert_invalid(lambda content, value=value: content["seats"][0].update(player=value))
        for value in ("c" * 301, " A", "A\nB", "\udfff", 1):
            with self.subTest(value=repr(value)):
                self.assert_invalid(lambda content, value=value: content["seats"][1].update(commander=value))

    def test_valid_non_ascii_labels_and_exact_limits_are_preserved(self):
        content = pod()
        content["seats"][0]["player"] = "P" * 80
        content["seats"][1].update(player="Opponént 🐉", commander="C" * 300)
        original = copy.deepcopy(content)
        pods.record_deck_ids(content)
        self.assertEqual(content, original)

    def test_notes_allow_multiline_but_are_bounded_and_valid_unicode(self):
        content = pod()
        content["notes"] = " Notes\nwith\ttabs "
        pods.record_deck_ids(content)
        for value in ("n" * 2001, "bad\rreturn", "bad\x7f", "bad\ud800", None):
            with self.subTest(value=repr(value)):
                self.assert_invalid(lambda content, value=value: content.update(notes=value))

    def test_dates_use_exact_calendar_form(self):
        for value in ("2026-02-29", "2026-13-01", "20261028", "2026-W44-3", "2026-1-2", None, 1):
            with self.subTest(value=value):
                self.assert_invalid(lambda content, value=value: content.update(date=value))
        content = pod()
        content["date"] = "2028-02-29"
        pods.record_deck_ids(content)

    def test_a_pod_cannot_also_supply_legacy_sides(self):
        self.assert_invalid(lambda content: content.update(sides=[]))

    def test_store_split_keeps_outer_version_and_content_markers_separate(self):
        record = full_record()
        header, content, ids = rules.split_record("games", record)
        self.assertEqual(header["version"], 1)
        self.assertEqual(content["game_version"], 2)
        self.assertEqual(ids, ["commander/fixture"])
        self.assertEqual(rules.rebuild(header, content), record)

    def test_legacy_bytes_and_hash_have_no_added_format_markers(self):
        record = {"version": 1, "id": "a" * 32, "kind": "games", "revision": 1,
                  "created_on": "2026-10-28T01:02:03+00:00", "updated_on": "2026-10-28T01:02:03+00:00",
                  "updated_by": "Test", "sides": [{"id": "casual/a"}, {"id": "casual/b"}],
                  "date": "2026-10-28", "result": "a", "notes": "Old record"}
        before_bytes, before_hash = rules.record_bytes(record), rules.record_sha(record)
        header, content, ids = rules.split_record("games", record)
        self.assertEqual(ids, ["casual/a", "casual/b"])
        self.assertEqual(rules.record_bytes(rules.rebuild(header, content)), before_bytes)
        self.assertEqual(rules.record_sha(record), before_hash)
        self.assertNotIn("mode", record)
        self.assertNotIn("game_version", record)
