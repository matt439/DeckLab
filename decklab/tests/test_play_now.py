"""E2-S34 physical allocation, privacy and existing Play-now saves."""
from collections import Counter
from copy import deepcopy
import json
import unittest
from unittest import mock

from decklab.lib import api, decks, pool
from decklab.lib.api import play_now as play_now_api
from decklab.lib.decks import play_now
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_privacy_readers import _as
from decklab.tests.test_editor import EditorTestCase
from decklab.tests.test_swaps_api import deck_text

DECK_ID = "commander/play-now"
COMMANDER = "Ghalta, Primal Hunger"
LIST = "Commander\n1 Ghalta, Primal Hunger (RIX) 130\n\nDeck\n1 Elvish Mystic (CMM) 648 #Ramp\n1 Sol Ring (ECC) 57\n97 Forest"


class PlayNowAllocationTests(unittest.TestCase):
    def test_a_flexible_greedy_pick_moves_aside_to_fill_all_three_slots(self):
        def creature(name, mv, roles=()):
            return {"name": name, "type_line": "Creature", "colors": ["G"], "color_identity": ["G"],
                    "commander_legality": "legal", "cmc": mv, "roles": roles}

        card_index = {name: creature(name, mv, roles) for name, mv, roles in (
            ("Commander", 5, ()), ("Missing A", 1, ("ramp",)), ("Missing B", 3, ()), ("Missing C", 3, ()),
            ("Candidate X", 2, ("ramp",)), ("Candidate Y", 1, ()), ("Candidate Z", 3, ()),
        )}
        sections = {"Commander": [decks.DeckLine(1, "Commander")], "Deck": [
            decks.DeckLine(1, name) for name in ("Missing A", "Missing B", "Missing C")]}
        physical = Counter({"Commander": 1, "Candidate X": 2, "Candidate Y": 1, "Candidate Z": 1})
        rows, proposed = play_now.propose(sections, physical, card_index.get, set(),
                                          lambda _: {"set": "abc", "number": "1", "finish": "nonfoil"})
        self.assertEqual(set(line.name for line in proposed["Deck"]), {"Candidate X", "Candidate Y", "Candidate Z"})
        self.assertEqual(rows[0]["adds"][0][0].name, "Candidate Y")
        self.assertTrue(all(len(row["adds"]) == 1 for row in rows))
        self.assertEqual(proposed["Commander"], sections["Commander"])
        self.assertEqual(physical["Candidate X"], 2)


class PlayNowApiTests(EditorTestCase):
    def setUp(self):
        super().setUp()
        _write(self.path(DECK_ID), deck_text(LIST, fmt="Commander"))
        self.source = api.edit_view(DECK_ID)["lists"]["target"]
        self.p = pool.Pool(Counter({COMMANDER: 1, "Sol Ring": 1, "Llanowar Elves": 5, "Black Lotus": 1}),
                           {"Llanowar Elves": [("private source", 1)], "Sol Ring": [("private source", 1)]},
                           [pool.InUse("casual/holder", "Hidden deck", "built", Counter({"Llanowar Elves": 1})),
                            pool.InUse("product/holder", "Hidden product", "intact product", Counter({"Llanowar Elves": 1})),
                            pool.InUse("loans/home", "Hidden loan", "lent out", Counter({"Llanowar Elves": 1}))])
        patcher = mock.patch.object(play_now_api, "_space_pool", return_value=self.p)
        patcher.start()
        self.addCleanup(patcher.stop)

    def request(self, profile="matt", **extra):
        data = {"id": DECK_ID, "sha256": self.sha(DECK_ID), "list": self.source}
        return self.body(profile, **{**data, **extra})

    def test_preview_is_read_only_then_regular_save_changes_only_play_now(self):
        original = self.text(DECK_ID)
        answer = play_now_api.preview(self.request())
        self.assertEqual(self.text(DECK_ID), original)
        self.assertEqual(answer["sha256"], self.sha(DECK_ID))
        first, second = answer["rows"]
        self.assertEqual((first["name"], first["unfilled"]), ("Elvish Mystic", 0))
        [addition] = first["adds"]
        self.assertEqual((addition["line"]["name"], addition["line"].get("category")), ("Llanowar Elves", "Ramp"))
        self.assertTrue(addition["note"])
        self.assertEqual((second["name"], second["unfilled"], second["adds"]), ("Sol Ring", 1, []))
        self.assertIsInstance(answer["bracket"]["minimum"], int)
        proposed = deepcopy(self.source)
        proposed["Deck"][first["index"]] = addition["line"]
        self.save(DECK_ID, {"owned": proposed})
        saved = api.edit_view(DECK_ID)["lists"]
        self.assertEqual(saved["target"], self.source)
        self.assertEqual(saved["owned"]["Commander"], self.source["Commander"])
        self.assertEqual(saved["owned"]["Deck"][first["index"]]["category"], "Ramp")

    def test_held_lent_and_incoming_excluded_and_missing_commander_kept(self):
        self.p.owned["Llanowar Elves"] -= 1
        self.p.owned[COMMANDER] = 0
        answer = play_now_api.preview(self.request())
        self.assertEqual([(row["name"], row["unfilled"], row["replaceable"]) for row in answer["rows"]],
                         [(COMMANDER, 1, False), ("Elvish Mystic", 1, True), ("Sol Ring", 1, True)])
        self.assertTrue(all(not row["adds"] for row in answer["rows"]))
        serial = json.dumps(answer)
        self.assertNotIn("Hidden", serial)
        self.assertNotIn("private source", serial)

    def test_lock_incomplete_and_stale_list(self):
        first = play_now_api.preview(self.request(locked=["elvish mystic"]))["rows"][0]
        self.assertTrue(first["locked"])
        self.assertEqual(first["unfilled"], 1)
        self.assertEqual(first["adds"], [])
        self.assertApiError(400, play_now_api.preview, self.request(locked=["Llanowar Elves"]))
        self.assertApiError(409, play_now_api.preview, self.request(sha256="f" * 64), contains="saved deck changed")
        self.p.warnings = ["Hidden deck warning"]
        error = self.assertApiError(409, play_now_api.preview, self.request(), contains="records need checking")
        self.assertNotIn("Hidden", error.message)

    def test_reports_commander_checks_for_the_proposed_list(self):
        shorter = deepcopy(self.source)
        shorter["Deck"][-1]["qty"] -= 1
        answer = play_now_api.preview(self.request(list=shorter))
        self.assertTrue(any("99 cards" in issue for issue in answer["checks"]))

    def test_preview_route(self):
        from decklab.lib import feature_routes
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = self.request()
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "play-now", "preview"], ""))
        handler._write_body.assert_called_once_with(play_now_api.MAX_BODY)
        code, answer = handler._send_json.call_args.args
        self.assertEqual((code, answer["deck_id"]), (200, DECK_ID))

    def test_hidden_deck_and_uneditable_deck_refused(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        with _as("user2"):
            self.assertApiError(404, play_now_api.preview, self.request("user2"))
        with _as("user1"):
            self.assertApiError(403, play_now_api.preview, self.request("user1"))
