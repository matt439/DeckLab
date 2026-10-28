"""Player/kit transitions through real API operations over a disposable files inventory.

Run with python scripts/test_fixtures.py decklab.tests.test_editor_player_kit.
No live server, database or native process is involved; kit.set is never mocked.
"""
import csv
import io
import json
from unittest import mock

from decklab.lib import access, accessories, api, decks, inventory
from decklab.lib.api import guard, saving
from decklab.lib.inventory import files
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_editor import sandbox_accessories


DECK_ID = "casual/player-kit"
DECK = """# Player kit fixture

- **Format:** Casual 60-card, 1v1
- **Played by:** {player}
- **Status:** built
- **Built version:** target
{kit}
## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
56 Forest
```

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Llanowar Elves | 4 | 4 | 0 | | | |
| **Total to buy** | | | **0** | | | |

## Notes

Keep this fixture prose.
"""


class PlayerKitSaveTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        sandbox_accessories(self)
        self.backend = inventory.backend()
        self.deck_path = self.box.magic / "decks/casual/player-kit.md"
        self.rows = []
        for owner, prefix in (("matt", "matt"), ("shared", "shared"), ("user1", "private")):
            for kind in ("sleeves", "deck_box"):
                self.rows.append({"id": f"{prefix}-{kind.replace('_', '-')}", "kind": kind, "owner": owner,
                                  "brand": "Fixture", "name": f"{prefix} {kind}", "quantity": 120 if kind == "sleeves" else 2,
                                  "capacity": "" if kind == "sleeves" else 100})
        self.write_accessories()
        self.write_deck("user", "matt-sleeves", "matt-deck-box")

    def write_accessories(self):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=accessories.FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(self.rows)
        _write(self.box.magic / "accessories.csv", stream.getvalue())

    def write_deck(self, player, sleeves=None, deck_box=None):
        kit = "".join(f"- **{header}:** {value}\n" for header, value in
                      (("Sleeves", sleeves), ("Deck box", deck_box)) if value)
        _write(self.deck_path, DECK.format(player=player, kit=kit))

    def saved_deck(self):
        saved = self.backend.load().deck(DECK_ID)
        return decks.parse_deck(saved.data, saved.slug, saved.kind, space=saved.space)

    def save_player(self, fields, *, profile="matt", sha=None, **extra):
        if sha is None:
            sha = self.backend.load().deck(DECK_ID).sha256
        with access.using({"profile": profile, "email": "", "remote": True}), inventory.pinned():
            return api.save_deck(self.body(profile, id=DECK_ID, sha256=sha, fields=fields, **extra))

    def check_player(self, fields, *, profile="matt", sha=None, **extra):
        if sha is None:
            sha = self.backend.load().deck(DECK_ID).sha256
        with access.using({"profile": profile, "email": "", "remote": True}), inventory.pinned():
            return api.check_draft(self.body(profile, id=DECK_ID, sha256=sha, fields=fields, **extra))

    def assert_fields(self, player, sleeves, deck_box):
        deck = self.saved_deck()
        self.assertEqual((deck.player, deck.status, deck.sleeves, deck.deck_box),
                         (player, "built", sleeves, deck_box))
        self.assertIn("Keep this fixture prose.", self.deck_path.read_text(encoding="utf-8"))

    def assert_one_apply(self, applied):
        applied.assert_called_once()
        call = applied.call_args
        self.assertEqual((call.args[0].kind, call.args[1].id, call.args[1].via),
                         ("deck.save", "matt", "tunnel"))
        self.assertTrue(call.args[2].strip())

    def test_either_to_matt_can_choose_his_kit_in_the_same_real_transaction(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            answer = self.save_player({"player": "user", "sleeves": "matt-sleeves", "deck_box": "matt-deck-box"})
        self.assert_one_apply(applied)
        self.assertTrue(answer["saved"])
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")
        self.assertEqual(answer["sha256"], self.backend.load().deck(DECK_ID).sha256)
        after = files.render(self.backend.load())
        self.assertEqual({key: value for key, value in after.items() if key != "magic/decks/casual/player-kit.md"},
                         {key: value for key, value in before.items() if key != "magic/decks/casual/player-kit.md"})

    def test_matt_to_either_can_replace_both_kit_fields_with_shared_rows(self):
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            answer = self.save_player({"player": "either", "sleeves": "shared-sleeves", "deck_box": "shared-deck-box"})
        self.assert_one_apply(applied)
        self.assertTrue(answer["changed"])
        self.assert_fields("either", "shared-sleeves", "shared-deck-box")

    def test_matt_to_either_can_explicitly_clear_both_fields_without_taking_deck_apart(self):
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            self.save_player({"player": "either", "sleeves": None, "deck_box": None})
        self.assert_one_apply(applied)
        self.assert_fields("either", None, None)

    def test_a_player_change_with_compatible_shared_kit_keeps_the_same_values(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        self.save_player({"player": "user"})
        self.assert_fields("user", "shared-sleeves", "shared-deck-box")

    def test_replacing_sleeves_during_handoff_keeps_an_unchanged_shared_box(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        self.save_player({"player": "user", "sleeves": "matt-sleeves"})
        self.assert_fields("user", "matt-sleeves", "shared-deck-box")

    def test_a_built_deck_without_kit_can_choose_its_new_players_kit(self):
        self.write_deck("either")
        self.save_player({"player": "user", "sleeves": "matt-sleeves", "deck_box": "matt-deck-box"})
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def test_retaining_matt_kit_when_changing_to_either_is_400_without_any_write(self):
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            error = self.assertApiError(400, lambda: self.save_player({"player": "either"}))
        applied.assert_not_called()
        self.assertIn("Matt", error.message)
        self.assertEqual(files.render(self.backend.load()), before)

    def test_clearing_only_one_incompatible_field_does_not_silently_keep_the_other(self):
        before = files.render(self.backend.load())
        self.assertApiError(400, lambda: self.save_player({"player": "either", "sleeves": None}))
        self.assertEqual(files.render(self.backend.load()), before)

    def test_private_old_kit_is_refused_without_naming_the_owner_or_accessories(self):
        self.write_deck("wife", "private-sleeves", "private-deck-box")
        before = files.render(self.backend.load())
        error = self.assertApiError(403, lambda: self.save_player({"player": "user"}))
        self.assertEqual(error.extra, {"reason": "kit_ownership"})
        self.assertEqual(error.message, "This deck's sleeves and deck box aren't yours to hand on: only their owner can "
                                       "change who plays it while it holds them.")
        for hidden in ("User1", "private-sleeves", "private-deck-box", "Fixture"):
            self.assertNotIn(hidden, error.message)
        self.assertEqual(files.render(self.backend.load()), before)

    def test_matt_cannot_choose_the_private_destination_kit(self):
        before = files.render(self.backend.load())
        error = self.assertApiError(403, lambda: self.save_player({"player": "wife", "sleeves": "private-sleeves",
                                                                  "deck_box": "private-deck-box"}))
        self.assertEqual(error.extra, {"reason": "kit_ownership"})
        self.assertEqual(error.message, "This deck's sleeves and deck box are User1's to choose.")
        self.assertEqual(files.render(self.backend.load()), before)

    def test_stale_deck_sha_refuses_before_any_assignment(self):
        sha = self.backend.load().deck(DECK_ID).sha256
        _write(self.deck_path, self.deck_path.read_text(encoding="utf-8") + "\nAnother fixture edit.\n")
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            error = self.assertApiError(409, lambda: self.save_player({"player": "either", "sleeves": None, "deck_box": None}, sha=sha))
        self.assertNotEqual(error.extra.get("reason"), "kit_ownership")
        applied.assert_not_called()
        self.assertEqual(files.render(self.backend.load()), before)

    def test_deck_edit_between_planning_and_transaction_leaves_external_edit_and_old_kit(self):
        real = self.backend.apply
        expected = []

        def changed(op, *args, **kwargs):
            _write(self.deck_path, self.deck_path.read_text(encoding="utf-8") + "\nA concurrent fixture edit.\n")
            expected.append(self.deck_path.read_bytes())
            return real(op, *args, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed) as applied:
            self.assertApiError(409, lambda: self.save_player({"player": "either", "sleeves": "shared-sleeves",
                                                             "deck_box": "shared-deck-box"}))
        self.assert_one_apply(applied)
        self.assertEqual(self.deck_path.read_bytes(), expected[0])
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def test_accessory_owner_change_before_transaction_rolls_back_the_complete_transition(self):
        before = self.deck_path.read_bytes()
        real = self.backend.apply
        def changed(op, *args, **kwargs):
            self.rows = [{**row, "owner": "user1"} if row["id"] == "shared-deck-box" else row for row in self.rows]
            self.write_accessories()
            return real(op, *args, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed) as applied:
            self.assertApiError(400, lambda: self.save_player({"player": "either", "sleeves": "shared-sleeves",
                                                             "deck_box": "shared-deck-box"}))
        self.assert_one_apply(applied)
        self.assertEqual(self.deck_path.read_bytes(), before)
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def test_known_replacement_deleted_before_transaction_does_not_become_legacy_free_text(self):
        before = self.deck_path.read_bytes()
        real = self.backend.apply

        def changed(op, *args, **kwargs):
            self.rows = [row for row in self.rows if row["id"] != "shared-deck-box"]
            self.write_accessories()
            return real(op, *args, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed) as applied:
            self.assertApiError(409, lambda: self.save_player({"player": "either", "sleeves": "shared-sleeves",
                                                             "deck_box": "shared-deck-box"}))
        self.assert_one_apply(applied)
        self.assertEqual(self.deck_path.read_bytes(), before)
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def test_known_replacement_kind_changed_before_transaction_requires_a_new_choice(self):
        before = self.deck_path.read_bytes()
        real = self.backend.apply

        def changed(op, *args, **kwargs):
            self.rows = [{**row, "kind": "sleeves", "capacity": ""} if row["id"] == "shared-deck-box" else row
                         for row in self.rows]
            self.write_accessories()
            return real(op, *args, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed) as applied:
            self.assertApiError(409, lambda: self.save_player({"player": "either", "sleeves": "shared-sleeves",
                                                             "deck_box": "shared-deck-box"}))
        self.assert_one_apply(applied)
        self.assertEqual(self.deck_path.read_bytes(), before)
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def _retained_shared_race(self, *, deleted):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        before = self.deck_path.read_bytes()
        real = self.backend.apply

        def changed(op, *args, **kwargs):
            self.rows = ([row for row in self.rows if row["id"] != "shared-deck-box"] if deleted else
                         [{**row, "owner": "user1"} if row["id"] == "shared-deck-box" else row for row in self.rows])
            self.write_accessories()
            return real(op, *args, **kwargs)

        with mock.patch.object(self.backend, "apply", side_effect=changed) as applied:
            self.assertApiError(409 if deleted else 400, lambda: self.save_player({"player": "user"}))
        self.assert_one_apply(applied)
        self.assertEqual(self.deck_path.read_bytes(), before)
        self.assert_fields("either", "shared-sleeves", "shared-deck-box")

    def test_retaining_shared_kit_still_checks_a_row_deleted_before_transaction(self):
        self._retained_shared_race(deleted=True)

    def test_retaining_shared_kit_still_checks_an_owner_changed_before_transaction(self):
        self._retained_shared_race(deleted=False)

    def test_legacy_free_text_remains_supported_on_a_permitted_transition(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        self.save_player({"player": "user", "sleeves": "Legacy blue", "deck_box": "Legacy box"})
        self.assert_fields("user", "Legacy blue", "Legacy box")

    def test_recognized_intent_survives_check_then_saves_as_one_real_operation(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        fields = {"player": "user", "sleeves": "matt-sleeves", "deck_box": "matt-deck-box"}
        selected = [{"field": "sleeves", "id": "matt-sleeves"}, {"field": "deck_box", "id": "matt-deck-box"}]
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            checked = self.check_player(fields, kit_rows=selected)
            self.assertTrue(checked["ok"])
            applied.assert_not_called()
            self.assertEqual(files.render(self.backend.load()), before)
            self.save_player(fields, kit_rows=selected)
        self.assert_one_apply(applied)
        self.assert_fields("user", "matt-sleeves", "matt-deck-box")

    def test_recognized_selection_deleted_before_save_is_not_downgraded_to_free_text(self):
        selected = [{"field": "deck_box", "id": "shared-deck-box"}]
        self.rows = [row for row in self.rows if row["id"] != "shared-deck-box"]
        self.write_accessories()
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            self.assertApiError(409, lambda: self.save_player({"player": "either", "sleeves": None,
                                                             "deck_box": "shared-deck-box"}, kit_rows=selected))
        applied.assert_not_called()
        self.assertEqual(files.render(self.backend.load()), before)

    def test_recognized_selection_deleted_before_check_is_refused_without_write(self):
        selected = [{"field": "deck_box", "id": "shared-deck-box"}]
        self.rows = [row for row in self.rows if row["id"] != "shared-deck-box"]
        self.write_accessories()
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            self.assertApiError(409, lambda: self.check_player({"player": "either", "sleeves": None,
                                                              "deck_box": "shared-deck-box"}, kit_rows=selected))
        applied.assert_not_called()
        self.assertEqual(files.render(self.backend.load()), before)

    def test_recognized_unchanged_shared_kit_deleted_before_request_still_requires_review(self):
        self.write_deck("either", "shared-sleeves", "shared-deck-box")
        selected = [{"field": "sleeves", "id": "shared-sleeves"}, {"field": "deck_box", "id": "shared-deck-box"}]
        self.rows = [row for row in self.rows if row["id"] != "shared-deck-box"]
        self.write_accessories()
        before = files.render(self.backend.load())
        fields = {"player": "user", "sleeves": "shared-sleeves", "deck_box": "shared-deck-box"}
        for endpoint in (self.check_player, self.save_player):
            with self.subTest(endpoint=endpoint.__name__):
                self.assertApiError(409, lambda: endpoint(fields, kit_rows=selected))
                self.assertEqual(files.render(self.backend.load()), before)

    def test_recognized_kind_change_before_request_requires_review_in_check_and_save(self):
        selected = [{"field": "deck_box", "id": "shared-deck-box"}]
        self.rows = [{**row, "kind": "sleeves", "capacity": ""} if row["id"] == "shared-deck-box" else row for row in self.rows]
        self.write_accessories()
        before = files.render(self.backend.load())
        fields = {"player": "either", "sleeves": None, "deck_box": "shared-deck-box"}
        for endpoint in (self.check_player, self.save_player):
            with self.subTest(endpoint=endpoint.__name__):
                self.assertApiError(409, lambda: endpoint(fields, kit_rows=selected))
                self.assertEqual(files.render(self.backend.load()), before)

    def test_present_malformed_or_mismatched_recognized_intent_is_400_for_both_endpoints(self):
        fields = {"player": "either", "sleeves": "shared-sleeves", "deck_box": "shared-deck-box"}
        invalid = [None, {}, "shared-deck-box", [None], [{"field": "sleeves"}],
                   [{"field": "notes", "id": "shared-sleeves"}], [{"field": "sleeves", "id": 4}],
                   [{"field": "sleeves", "id": ""}], [{"field": "sleeves", "id": "x" * 501}],
                   [{"field": "sleeves", "id": "matt-sleeves"}],
                   [{"field": "sleeves", "id": "shared-sleeves", "extra": "unexpected"}],
                   [{"field": "sleeves", "id": "shared-sleeves"}] * 2,
                   [{"field": "sleeves", "id": "shared-sleeves"}] * 3]
        before = files.render(self.backend.load())
        with mock.patch.object(self.backend, "apply", wraps=self.backend.apply) as applied:
            for endpoint in (self.check_player, self.save_player):
                for metadata in invalid:
                    with self.subTest(endpoint=endpoint.__name__, metadata=metadata):
                        error = self.assertApiError(400, lambda: endpoint(fields, kit_rows=metadata))
                        self.assertNotIn("kit_rows", str(error))
                        self.assertIn("Review them together again", str(error))
                        self.assertEqual(files.render(self.backend.load()), before)
        applied.assert_not_called()

    def test_recognized_intent_requires_complete_final_fields_including_player(self):
        selected = [{"field": "sleeves", "id": "shared-sleeves"}]
        invalid_fields = [{"player": "either", "sleeves": "shared-sleeves"},
                          {"sleeves": "shared-sleeves", "deck_box": "matt-deck-box"}]
        before = files.render(self.backend.load())
        for endpoint in (self.check_player, self.save_player):
            for fields in invalid_fields:
                with self.subTest(endpoint=endpoint.__name__, fields=fields):
                    error = self.assertApiError(400, lambda: endpoint(fields, kit_rows=selected))
                    self.assertNotIn("kit_rows", str(error))
                    self.assertIn("Review them together again", str(error))
        self.assertEqual(files.render(self.backend.load()), before)

    def test_old_private_kit_refusal_precedes_recognized_evidence_read(self):
        self.write_deck("wife", "private-sleeves", "private-deck-box")
        before = files.render(self.backend.load())
        fields = {"player": "user", "sleeves": None, "deck_box": None}
        for endpoint in (self.check_player, self.save_player):
            with self.subTest(endpoint=endpoint.__name__):
                error = self.assertApiError(403, lambda: endpoint(fields, kit_rows=[]))
                self.assertEqual(error.extra, {"reason": "kit_ownership"})
                for hidden in ("User1", "private-sleeves", "private-deck-box", "Fixture"):
                    self.assertNotIn(hidden, error.message)
                self.assertEqual(files.render(self.backend.load()), before)

    def test_hidden_deck_refusal_precedes_metadata_and_does_not_confirm_any_kit(self):
        before = files.render(self.backend.load())
        fields = {"player": "either", "sleeves": None, "deck_box": None}
        for endpoint in (self.check_player, self.save_player):
            with self.subTest(endpoint=endpoint.__name__):
                error = self.assertApiError(404, lambda: endpoint(fields, profile="user2", kit_rows=None))
                self.assertNotEqual(error.extra.get("reason"), "kit_ownership")
                for hidden in ("matt-sleeves", "private-sleeves", "shared-sleeves", "Fixture"):
                    self.assertNotIn(hidden, error.message)
                self.assertEqual(files.render(self.backend.load()), before)

    def test_private_old_kit_is_authorized_before_either_accessory_reader_can_run(self):
        self.write_deck("wife", "private-sleeves", "private-deck-box")
        fields = {"player": "user", "sleeves": "matt-sleeves", "deck_box": "matt-deck-box"}
        selected = [{"field": "sleeves", "id": "matt-sleeves"}, {"field": "deck_box", "id": "matt-deck-box"}]
        before = files.render(self.backend.load())
        with mock.patch.object(accessories, "read", side_effect=AssertionError("Private kit reader ran")) as read, \
                mock.patch.object(saving, "_check_kit_rows", side_effect=AssertionError("Recognized-row reader ran")) as rows:
            for endpoint in (self.check_player, self.save_player):
                with self.subTest(endpoint=endpoint.__name__):
                    error = self.assertApiError(403, lambda: endpoint(fields, kit_rows=selected))
                    self.assertEqual(error.extra, {"reason": "kit_ownership"})
                    for hidden in ("User1", "private-sleeves", "private-deck-box", "Fixture"):
                        self.assertNotIn(hidden, error.message)
                    read.assert_not_called()
                    rows.assert_not_called()
        self.assertEqual(files.render(self.backend.load()), before)

    def test_ordinary_deck_permission_refusal_does_not_claim_a_kit_ownership_problem(self):
        before = files.render(self.backend.load())
        with mock.patch.object(accessories, "read", side_effect=AssertionError("Accessory reader ran")) as read:
            error = self.assertApiError(403, lambda: self.save_player({"player": "wife"}, profile="user1"))
        self.assertNotEqual(error.extra.get("reason"), "kit_ownership")
        read.assert_not_called()
        self.assertEqual(files.render(self.backend.load()), before)

    def test_ordinary_accessory_permission_refusal_is_not_the_private_owner_classification(self):
        profile = next(profile for profile in ROLES["profiles"] if profile["id"] == "user2")
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(accessories, "read", side_effect=AssertionError("Accessory reader ran")) as read:
            error = self.assertApiError(403, guard.require_kit_choice, profile,
                                       {"space": "home", "player": "user"}, {"sleeves": None, "deck_box": None})
        self.assertNotEqual(error.extra.get("reason"), "kit_ownership")
        read.assert_not_called()

    def test_a_person_space_without_kit_is_not_a_private_owner_refusal(self):
        profile = next(profile for profile in ROLES["profiles"] if profile["id"] == "matt")
        with access.using({"profile": "matt", "email": "", "remote": True}), \
                mock.patch.object(accessories, "read", side_effect=AssertionError("Accessory reader ran")) as read:
            error = self.assertApiError(403, guard.require_kit_choice, profile,
                                       {"space": "user2", "player": None}, {"sleeves": None, "deck_box": None})
        self.assertEqual(error.message, "A deck in a person's own collection has no sleeves or deck box.")
        self.assertNotEqual(error.extra.get("reason"), "kit_ownership")
        read.assert_not_called()

    def test_try_a_change_without_recognized_metadata_keeps_its_existing_read_only_check(self):
        self.write_deck("wife", "private-sleeves", "private-deck-box")
        before = files.render(self.backend.load())
        with mock.patch.object(saving, "_check_kit_rows", side_effect=AssertionError("Opt-in row reader ran")) as rows:
            answer = self.check_player({"player": "user", "sleeves": "matt-sleeves", "deck_box": "matt-deck-box"})
        self.assertTrue(answer["ok"])
        rows.assert_not_called()
        for hidden in ("private-sleeves", "private-deck-box", "Fixture private"):
            self.assertNotIn(hidden, json.dumps(answer))
        self.assertEqual(files.render(self.backend.load()), before)
