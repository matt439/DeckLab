"""Explicit physical choices bind public source rows to one atomic, private precon save."""
import copy
from unittest import mock

from decklab.lib import cards, inventory, precon_tokens
from decklab.lib.api import precons as api
from decklab.lib.inventory import Op, files
from decklab.lib.inventory.model import Inventory
from decklab.lib.state import Actor
from decklab.lib.tokens import ops as token_ops
from decklab.tests import test_precon_tokens as fixture
from decklab.tests import test_precons as sources


CHOICES = [{"source_row": 1, "front": "Dinosaur", "quantity": 2},
           {"source_row": 2, "front": "", "quantity": 0}]


class PreconTokenChoicesTests(fixture.PreconTokensTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(cards, "token_face", side_effect=lambda name:
                                    {"dinosaur": "Dinosaur", "rabbit": "Rabbit"}.get(cards.fold(name)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def source(self, tokens):
        data = copy.deepcopy(sources.DINOS)
        data["data"]["tokens"] = tokens
        return self.seed("decks/TestDinos_TST.json", data)

    def test_unknown_quantity_is_confirmable_without_guessing_or_altering_source(self):
        path = self.source([{"name": "Dinosaur"}, {"name": "Dinosaur", "count": 1}])
        before_source = path.read_bytes()
        offer = self.offer()
        self.assertFalse(offer["ready"])
        self.assertTrue(offer["choices_ready"])
        self.assertEqual(offer["choice_problems"], [])
        self.assertEqual(offer["options"], [
            {"source_row": 1, "source_name": "Dinosaur", "fronts": ["Dinosaur"], "quantity": None},
            {"source_row": 2, "source_name": "Dinosaur", "fronts": ["Dinosaur"], "quantity": 1}])
        answer = self.add_tokens(tokens_choices=CHOICES)
        self.assertEqual(answer["tokens"], {"cards": 2, "rows": 1})
        self.assertEqual(self.writes_made(), 1)
        rows = inventory.current().token_set("user2").rows
        self.assertEqual([(row["front"], row["quantity"]) for row in rows], [("Dinosaur", "2")])
        self.assertIn("user-confirmed physical quantity 2", rows[0]["notes"])
        self.assertTrue(all(not rows[0][key] for key in ("back", "set", "finish", "front_details", "back_details")))
        text = inventory.current().deck(answer["deck"]["id"]).text
        self.assertIn("confirmed physical quantities", text)
        self.assertIn("Tokens page): 2 Dinosaur.", text)
        self.assertIn("add 2 token cards", self.last_write()[0])
        self.assertEqual(path.read_bytes(), before_source)

    def test_combined_name_selects_one_front_once_and_positive_same_front_rows_stay_separate(self):
        self.source([{"name": "Dinosaur // Rabbit"}, {"name": "Dinosaur", "count": 8}])
        choices = [{"source_row": 1, "front": "Dinosaur", "quantity": 2},
                   {"source_row": 2, "front": "Dinosaur", "quantity": 3}]
        self.assertEqual(self.offer()["options"][0]["fronts"], ["Dinosaur", "Rabbit"])
        answer = self.add_tokens(tokens_choices=choices)
        self.assertEqual(answer["tokens"], {"cards": 5, "rows": 2})
        self.assertEqual([(row["front"], row["quantity"]) for row in inventory.current().token_set("user2").rows],
                         [("Dinosaur", "2"), ("Dinosaur", "3")])
        self.assertIn("Tokens page): 2 Dinosaur, 3 Dinosaur.", inventory.current().deck(answer["deck"]["id"]).text)

    def test_malformed_incomplete_duplicate_unoffered_and_all_zero_choices_save_nothing(self):
        invalid = [None, {}, [], CHOICES[:1], CHOICES + [CHOICES[0]], [CHOICES[0], CHOICES[0]],
                   [dict(CHOICES[0], front="Rabbit"), CHOICES[1]],
                   [dict(CHOICES[0], quantity=True), CHOICES[1]],
                   [dict(CHOICES[0], quantity="2"), CHOICES[1]],
                   [dict(CHOICES[0], quantity=-1), CHOICES[1]],
                   [dict(CHOICES[0], source_row=True), CHOICES[1]],
                   [dict(CHOICES[0], back="Rabbit"), CHOICES[1]],
                   [dict(CHOICES[0], quantity=0, front=""), CHOICES[1]]]
        before = files.render(inventory.current())
        for choices in invalid:
            with self.subTest(choices=choices):
                error = self.assertApiError(400, self.add_tokens, tokens_choices=choices)
                if isinstance(choices, list) and len(choices) == 2 and all(row.get("quantity") == 0 for row in choices):
                    self.assertIn("unchecked", error.message)
                self.assertEqual(self.writes_made(), 0)
                self.assertEqual(files.render(inventory.current()), before)

    def test_choices_require_opt_in_and_both_original_hashes(self):
        self.assertApiError(400, self.add, tokens_choices=CHOICES, contains="add_tokens")
        self.assertApiError(400, self.add, add_tokens=True, tokens_choices=CHOICES)
        self.assertApiError(400, self.add, add_tokens=True, tokens_choices=CHOICES, tokens_sha256=None)
        self.assertEqual(self.writes_made(), 0)

    def test_stale_public_receipt_is_checked_before_resolver_even_when_new_source_is_unusable(self):
        offer = self.offer()
        self.source([{"name": "Unknown face"}])
        with mock.patch.object(precon_tokens, "resolve", side_effect=AssertionError("stale choices resolved")):
            error = self.assertApiError(409, self.add, add_tokens=True, tokens_choices=CHOICES,
                                       tokens_sha256=offer["sha256"], tokens_source_sha256=offer["source_sha256"])
        self.assertEqual(error.extra, {"token_conflict": True})
        self.assertEqual(self.writes_made(), 0)

    def test_source_provenance_change_without_changed_faces_requires_new_receipt(self):
        offer = self.offer()
        self.source([{"name": "Dinosaur", "count": 3, "uuid": "different-public-source"},
                     {"name": "Dinosaur", "count": 1}])
        error = self.assertApiError(409, self.add, add_tokens=True, tokens_choices=CHOICES,
                                   tokens_sha256=offer["sha256"], tokens_source_sha256=offer["source_sha256"])
        self.assertEqual(error.extra, {"token_conflict": True})

    def test_chosen_token_rows_recheck_inventory_receipt_under_atomic_save_lock(self):
        made = api.plan_add("user2", "TestDinos_TST", None, None, None, "Claude", add_tokens=True, tokens_choices=CHOICES)
        inventory.apply(Op("tokens.add", {"space": "user2", "sha256": made["op"].params["tokens_sha256"],
                                          "row": made["op"].params["token_rows"][0], "separate": True}),
                        Actor("claude", "Claude", source="cli"), "Fixture concurrent token edit")
        before = files.render(inventory.current())
        with self.assertRaises(token_ops.Stale):
            inventory.apply(made["op"], Actor("claude", "Claude", source="cli"), "Fixture stale choices")
        self.assertEqual(files.render(inventory.current()), before)
        self.assertEqual(self.writes_made(), 1)

    def test_default_notes_include_unknown_face_without_a_physical_count_or_private_token_read(self):
        self.source([{"name": "Dinosaur"}])
        with mock.patch.object(Inventory, "token_set", side_effect=AssertionError("opt-out read private token rows")):
            answer = self.add(title="Unknown quantities left alone")
        text = inventory.current().deck(answer["deck"]["id"]).text
        self.assertIn("Dinosaur (physical quantity unknown)", text)
        self.assertNotIn("1 Dinosaur", text)
        self.assertNotIn("tokens", answer)

    def test_unauthorized_choice_offer_has_no_private_receipt_and_is_not_actionable(self):
        original = api.guard.allowed
        with mock.patch.object(api.guard, "allowed", side_effect=lambda profile, action, target=None:
                               False if action == "tokens.edit" else original(profile, action, target)), \
                mock.patch.object(Inventory, "token_set", side_effect=AssertionError("private tokens read")):
            offer = self.offer()
        self.assertTrue(offer["options"])
        self.assertFalse(offer["editable"])
        self.assertFalse(offer["choices_ready"])
        self.assertNotIn("sha256", offer)

    def test_unreadable_private_token_sheet_disables_choices_without_hash_or_key_error(self):
        with mock.patch.object(api, "refuse_unreadable_tokens", side_effect=inventory.Conflict("Fixture bad token sheet")):
            offer = self.offer()
            self.assertFalse(offer["choices_ready"])
            self.assertNotIn("sha256", offer)
            self.assertIn("need fixing", offer["choice_problems"][-1]["message"])
            self.assertApiError(400, self.add, add_tokens=True, tokens_choices=CHOICES, tokens_sha256=None,
                                tokens_source_sha256=offer["source_sha256"])
        self.assertEqual(self.writes_made(), 0)

    def test_late_selected_row_failure_leaves_every_component_unchanged(self):
        choices = [dict(row, front="Dinosaur", quantity=2) for row in CHOICES]
        before = files.render(inventory.current())
        original = token_ops.add
        def fail_second(inv, **params):
            if "entry 2;" in params["row"]["notes"]:
                raise inventory.Invalid("Fixture late chosen row failure")
            return original(inv, **params)
        with mock.patch.object(token_ops, "add", side_effect=fail_second):
            self.assertApiError(400, self.add_tokens, tokens_choices=choices)
        self.assertEqual(files.render(inventory.current()), before)
        self.assertEqual(self.writes_made(), 0)
