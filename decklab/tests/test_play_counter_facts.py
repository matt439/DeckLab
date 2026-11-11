"""Optional counter facts stay with their recording space and never alter captured card lists."""
import copy
import unittest

from decklab.lib import access
from decklab.lib.api import play_counter_facts as facts, play_records as play
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_play_records import MixedFixture, PlayFixture, encoded, selector


def details(ids=("a", "b")):
    return {"duration_seconds": 1234, "seats": [{"seat_id": seat_id, "final_life": 18 + index,
            "out_reason": "conceded" if index == 0 else None, "out_order": 1 if index == 0 else None}
            for index, seat_id in enumerate(ids)]}


class CounterFactRulesTests(unittest.TestCase):
    def test_optional_blank_values_and_simultaneous_outs_have_no_invented_order(self):
        value = details()
        value["seats"][1].update(out_reason="poison", out_order=1)
        self.assertEqual(facts.normalise(value, ["a", "b"]), value)
        empty = {"duration_seconds": None, "seats": [{"seat_id": seat_id, "final_life": None,
                 "out_reason": None, "out_order": None} for seat_id in ("a", "b")]}
        self.assertIsNone(facts.normalise(empty, ["a", "b"]))

    def test_invalid_types_bounds_or_seat_binding_are_refused(self):
        for change in (lambda value: value.update(duration_seconds=True), lambda value: value.update(duration_seconds=1.5),
                       lambda value: value.update(duration_seconds=172801), lambda value: value["seats"][0].update(final_life=-1000),
                       lambda value: value["seats"][0].update(final_life=False), lambda value: value["seats"][0].update(out_reason="other"),
                       lambda value: value["seats"][0].update(out_order=3), lambda value: value["seats"][0].update(seat_id="s1")):
            value = details(); change(value)
            with self.subTest(value=value), self.assertRaises(play.ApiError):
                facts.normalise(value, ["a", "b"])


class CounterFactApiTests(PlayFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.write_decks()

    def test_counter_facts_are_reviewed_saved_preserved_and_explicitly_clearable(self):
        payload = {**self.game(), "counter": details()}
        before = play._snapshot("casual/gruul-test", "target")
        reviewed = play.save_game(encoded(payload))
        changed = copy.deepcopy(payload); changed["counter"]["duration_seconds"] += 1
        self.assertApiError(409, play.save_game, encoded({**changed, "id": reviewed["id"], "preview": False,
                                                        "review_sha256": reviewed["review_sha256"]}))
        saved = self.save(payload)
        self.assertEqual(saved["record"]["counter"], details())
        self.assertEqual(play._snapshot("casual/gruul-test", "target"), before)
        correction = {**self.game(), "id": saved["record"]["id"], "sha256": saved["sha256"], "notes": "Corrected note"}
        preserved = self.save(correction)
        self.assertEqual(preserved["record"]["counter"], details())
        cleared = self.save({**correction, "sha256": preserved["sha256"], "counter": None})
        self.assertNotIn("counter", cleared["record"])


class MixedCounterFactPrivacyTests(MixedFixture, ApiTestCase):
    def test_other_space_can_edit_its_side_but_cannot_read_or_change_private_facts(self):
        old = self.box.state.play_get("games", self.mixed)
        updated = {**old, "counter": details(), "revision": old["revision"] + 1}
        from decklab.lib import state
        from decklab.lib.state import rules
        self.box.state.play_put("games", updated, rules.record_sha(old), state.Actor("matt", "Matt"), "Add fixture counter details")
        with access.viewing("user2"):
            profile = play.guard.viewer()
            visible = play._view("games", updated, profile)
            self.assertNotIn("counter", visible)
            payload = {"profile": "user2", "id": updated["id"], "sha256": rules.record_sha(updated), "preview": True,
                       "date": updated["date"], "result": updated["result"], "notes": "",
                       "sides": [{**selector(visible["sides"][0]), "player": "User2 corrected", "mulligans": 1}, {"hidden": True}]}
            checked = play.save_game(encoded(payload))
            self.assertNotIn("counter", checked["record"])
            self.assertApiError(403, play.save_game, encoded({**payload, "counter": None}))
            self.assertApiError(403, play.save_game, encoded({**payload, "counter": {"invalid": True}}))
        self.assertEqual(self.box.state.play_get("games", self.mixed)["counter"], details())
