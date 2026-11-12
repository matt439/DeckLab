"""A Commander night line-up (E9-S34): GET /api/commander-night/lineup over the sandbox's decks, the recorded
night and the Game log (home's profiles only; a member, a member admin or a request naming nobody is refused
before anything is read), built decks judged on their built list, trials and other kinds left out, hidden
decks never listed, stand-ins and box dates only to their readers, checks that fail or run out of time listed
as unknown, and the route over HTTP.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_commander_lineup_api
"""
import copy
import json
import unittest
import uuid
from unittest import mock

from decklab.lib import access, decks, state, stats
from decklab.lib.stats import commander as stats_commander
from decklab.lib.api import commander_lineup, guard
from decklab.lib.api import play_records as play
from decklab.tests import test_server as support
from decklab.tests.test_api import FIXTURES, _write
from decklab.tests.test_api_permissions import PermissionTestCase

TODAY = "2026-11-12"
NIGHT = {"name": "Fixture night", "venue": "Fictional venue", "target_bracket": 2,
         "published_min": 1, "published_max": 4, "house_rules": "", "checked_on": ""}
ACTOR = state.Actor("matt", "Matt", "home")

DECK = """# {title}

- **Format:** Commander
- **Played by:** {player}
- **Status:** {status}
- **Target bracket:** 2
{extra}
## Decklist

```
Commander
1 Ghalta, Primal Hunger (RIX) 130

Deck
1 {card}
```
{owned}"""
OWNED = """
### Substitute version (owned and incoming cards)

```
Commander
1 Ghalta, Primal Hunger (RIX) 130

Deck
1 {card}
```
"""
INSTALLED = {"target": [], "owned": [], "built": {"version": "target",
                                                  "cards": [{"for": "Llanowar Elves", "using": None, "qty": 1}]}}


def fake_bracket(sections):
    """A bracket from the list's one Deck card: Sol Ring is a Game Changer here, Llanowar Elves nothing."""
    names = [line.name for line in sections.get("Deck", [])]
    gc = [{"name": "Sol Ring"}] if "Sol Ring" in names else []
    return {"minimum": 3 if gc else 1, "game_changers": gc, "mass_land_denial": [], "extra_turns": [],
            "combos": {"checked": True, "matches": []}, "unknown_cards": []}


class LineupViewTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.box.stack.enter_context(mock.patch.object(play, "_play_today", return_value=TODAY))
        folder = self.box.magic / "decks" / "commander"
        self.deck(folder, "built-one", "Built One", "built", card="Llanowar Elves",
                  extra="- **Stand-ins:** " + json.dumps(INSTALLED) + "\n- **Box checked:** 2026-11-01\n")
        # Built from its Play-now list: judged on that list (Llanowar Elves), not its Planned one (Sol Ring).
        self.deck(folder, "play-now", "Play Now", "built", card="Sol Ring",
                  extra="- **Built version:** owned-only\n", owned=OWNED.format(card="Llanowar Elves"))
        self.deck(folder, "strong", "Strong", "building", card="Sol Ring")
        self.deck(folder, "trial", "Trial", "idea", card="Llanowar Elves", extra="- **Trial:** precon BigElves_TST\n")
        self.bracket = self.box.stack.enter_context(
            mock.patch.object(commander_lineup, "_bracket", side_effect=fake_bracket))

    def deck(self, folder, slug, title, status, *, card, extra="", owned="", player="user"):
        _write(folder / f"{slug}.md", DECK.format(title=title, player=player, status=status, extra=extra,
                                                  card=card, owned=owned))

    def save_night(self, night=NIGHT):
        self.box.state.commander_night_put(copy.deepcopy(night), 0, ACTOR, "Fixture night")

    def game(self, a, b, day):
        sides = [{**play._snapshot(deck_id, "target"), "player": player, "mulligans": 0}
                 for deck_id, player in ((a, "Matt"), (b, "User1"))]
        record = {"version": 1, "id": uuid.uuid4().hex, "kind": "games", "revision": 1,
                  "created_on": "2026-11-01T01:00:00+00:00", "updated_on": "2026-11-01T01:00:00+00:00",
                  "updated_by": "Matt", "date": day, "result": "a", "notes": "", "sides": sides, "space": "home"}
        self.box.state.play_put("games", record, None, state.Actor("test", "a test"), "Seed a record")

    def view(self, who="user1"):
        with access.viewing(who):
            return commander_lineup.lineup_view()

    @staticmethod
    def ids(answer, group):
        return [row["id"] for row in answer["groups"][group]]

    def test_home_players_see_their_commander_decks_grouped_against_the_night(self):
        self.save_night()
        self.game("commander/built-one", "commander/strong", "2026-11-02")
        answer = self.view()
        self.assertEqual((answer["available"], answer["limit"], answer["night_error"], answer["played_error"],
                          answer["timed_out"], answer["today"]), (True, 2, None, None, 0, TODAY))
        self.assertEqual(self.ids(answer, "fits"), ["commander/built-one", "commander/play-now"])
        # The sandbox's Elf Commander (an idea) holds Sol Ring too.
        self.assertEqual(self.ids(answer, "above"), ["commander/elf-commander", "commander/strong"])
        self.assertEqual(self.ids(answer, "unknown"), [])
        text = json.dumps(answer)
        self.assertNotIn("commander/trial", text)
        self.assertNotIn("casual/", text)
        built, play_now = answer["groups"]["fits"]
        idea, strong = answer["groups"]["above"]
        self.assertEqual((built["built"], built["version"], built["box_checked_on"], built["last_played"],
                          built["days_since_played"]), (True, "target", "2026-11-01", "2026-11-02", 10))
        self.assertEqual(built["stand_ins"], [{"for": "Llanowar Elves", "using": None, "qty": 1}])
        self.assertEqual((play_now["version"], play_now["minimum"]), ("owned", 1))
        self.assertEqual((idea["built"], idea["box_checked_on"], idea["stand_ins"], idea["last_played"]),
                         (False, None, [], None))
        self.assertEqual(strong["deciding"], [{"reason": "1 Game Changer (none in Brackets 1-2)", "cards": ["Sol Ring"]}])
        self.assertEqual(strong["last_played"], "2026-11-02")

    def test_no_recorded_night_or_an_unreadable_one_leaves_every_deck_unknown(self):
        answer = self.view("matt")
        self.assertEqual((answer["night"], answer["limit"], answer["counts"]["fits"]), (None, None, 0))
        self.assertEqual(len(answer["groups"]["unknown"]), 4)
        self.save_night()
        with mock.patch.object(self.box.state, "commander_night", side_effect=state.Unavailable("down")):
            answer = self.view("matt")
        self.assertEqual((answer["night_error"], answer["basis"], answer["counts"]["fits"]),
                         (commander_lineup.NO_NIGHT, commander_lineup.NO_NIGHT, 0))

    def test_members_member_admins_and_requests_naming_nobody_are_refused_before_any_read(self):
        self.save_night()
        contexts = (("member", access.using({"profile": "user2", "email": "user2@example.com", "remote": True})),
                    ("nobody", access.answering(False)))
        for name, context in contexts:
            with self.subTest(name), context, \
                    mock.patch.object(self.box.state, "commander_night", side_effect=AssertionError("private read")), \
                    mock.patch.object(commander_lineup, "_summaries", side_effect=AssertionError("deck read")):
                self.assertApiError(403, commander_lineup.lineup_view)
        with mock.patch.object(guard, "viewer", return_value={"id": "user2", "space": "user2", "role": "admin"}), \
                mock.patch.object(guard, "script", return_value=False):
            self.assertApiError(403, commander_lineup.lineup_view)
        # A script naming nobody (the PC's own) sees the line-up.
        self.assertEqual(len(commander_lineup.lineup_view()["groups"]["fits"]), 2)

    def test_only_visible_decks_and_stand_ins_and_box_dates_only_to_their_readers(self):
        self.save_night()
        hidden = lambda profile=False: (lambda item: (item if isinstance(item, str) else item["id"]) != "commander/strong")
        with access.viewing("user1"), mock.patch.object(guard, "deck_reader", side_effect=hidden), \
                mock.patch.object(guard, "sees_inventory", return_value=False), \
                mock.patch.object(guard, "sees_home_records", return_value=False):
            answer = commander_lineup.lineup_view()
        self.assertNotIn("commander/strong", json.dumps(answer))
        for group in answer["groups"].values():
            for row in group:
                self.assertNotIn("stand_ins", row)
                self.assertNotIn("box_checked_on", row)

    def test_checks_that_fail_or_run_out_of_time_are_unknown(self):
        self.save_night()
        with mock.patch.object(commander_lineup, "TIME_BUDGET", -1.0):
            answer = self.view()
        self.assertEqual((answer["counts"], answer["timed_out"]), ({"fits": 0, "above": 0, "unknown": 4}, 4))
        self.assertTrue(all(row["unknown_reason"] == commander_lineup.NOT_IN_TIME for row in answer["groups"]["unknown"]))
        self.bracket.side_effect = OSError("no card index")
        with mock.patch.object(commander_lineup.common, "_log"):
            answer = self.view()
        self.assertEqual(answer["counts"]["unknown"], 4)
        self.assertTrue(all(row["unknown_reason"] == commander_lineup.NO_CARDS for row in answer["groups"]["unknown"]))

    def test_a_check_that_ends_after_the_budget_is_unknown(self):
        self.save_night()
        clock = [1000.0]

        def slow(sections):
            clock[0] += commander_lineup.TIME_BUDGET + 1     # this one check runs past the budget
            return fake_bracket(sections)
        self.bracket.side_effect = slow
        with mock.patch.object(commander_lineup.time, "monotonic", side_effect=lambda: clock[0]):
            answer = self.view()
        self.assertEqual((answer["counts"]["fits"], answer["counts"]["above"]), (0, 0))
        self.assertEqual(answer["timed_out"], answer["counts"]["unknown"])
        self.assertTrue(all(row["unknown_reason"] == commander_lineup.NOT_IN_TIME
                            for row in answer["groups"]["unknown"]))
        self.assertEqual(self.bracket.call_count, 1)        # nothing more is checked once the budget is spent

    def test_a_game_log_that_can_t_be_read_shows_no_dates(self):
        self.save_night()
        with mock.patch.object(self.box.state, "play_list", side_effect=state.Unavailable("down")):
            answer = self.view()
        self.assertEqual(answer["played_error"], commander_lineup.NO_GAMES)
        self.assertTrue(all(not row["played_known"] for group in answer["groups"].values() for row in group))

    def test_the_real_bracket_check_matches_the_deck_page_s_minimum(self):
        """The sandbox's own card data, combo list and a tag file with both bracket tags: no stand-in bracket."""
        self.save_night({**NIGHT, "target_bracket": 4})
        with mock.patch.object(stats_commander, "TAG_FILE", FIXTURES / "stats_tags.jsonl"),                 mock.patch.object(commander_lineup, "_bracket", wraps=_real_bracket):
            answer = self.view()
            expected = stats.deck_rules(decks.load_deck("commander/elf-commander"), "commander")["commander"]["bracket"]
        self.assertEqual((expected["unknown_cards"], expected["combos"]["checked"], expected["mass_land_denial"]),
                         ([], True, []))
        row = next(r for r in answer["groups"]["fits"] if r["id"] == "commander/elf-commander")
        self.assertEqual((row["minimum"], row["unknown_reason"]), (expected["minimum"], None))
        # Without the bracket tags (the sandbox's tag file has neither), the same deck is unknown, never fitting.
        with mock.patch.object(commander_lineup, "_bracket", wraps=_real_bracket):
            answer = self.view()
        row = next(r for r in answer["groups"]["unknown"] if r["id"] == "commander/elf-commander")
        self.assertIn("oracle tags couldn't be read", row["unknown_reason"])


_real_bracket = commander_lineup._bracket


class LineupHttpTests(support.ServerTestCase):

    def test_get_routes_to_the_line_up_and_takes_no_parameters(self):
        answer = {"available": True, "groups": {}}
        with mock.patch.object(commander_lineup, "lineup_view", return_value=answer) as view:
            self.assertEqual(self.get_json("/api/commander-night/lineup"), answer)
            view.assert_called_once_with()
            self.assertError("/api/commander-night/lineup?x=1", 400)
            code, headers, _ = self.request("POST", "/api/commander-night/lineup", b"{}")
            self.assertEqual(code, 405)


if __name__ == "__main__":
    unittest.main()
