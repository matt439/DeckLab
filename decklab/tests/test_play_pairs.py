"""Tonight's pairs (E1-S28): lib/play_pairs.py's suggest() over plain fixtures (ordering, evenness from the
real record, else Forge, else unknown, readiness, seats and reasons), then GET /api/play/pairs over the
sandbox's decks and Game log (home's players only; a member, or a request naming nobody, gets nothing).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_play_pairs
"""
import json
import unittest
import uuid
from unittest import mock

from decklab.lib import access, play_pairs, state
from decklab.lib.api import library_forge, play_tonight
from decklab.lib.api import play_records as play
from decklab.tests import test_server as support
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES

TODAY = "2026-10-29"


def deck(deck_id, title, player, **extra):
    return {"id": deck_id, "title": title, "player": player, "status": "built", "kind": "casual", "ready": True,
            "version": "target", **extra}


def games(a, b, wins_a, wins_b, draws=0, day="2026-10-01"):
    found = [{"date": day, "sides": [a, b], "result": "a"} for _ in range(wins_a)]
    found += [{"date": day, "sides": [b, a], "result": "a"} for _ in range(wins_b)]
    return found + [{"date": day, "sides": [a, b], "result": "draw"} for _ in range(draws)]


def ids(pairs):
    return [tuple(side["id"] for side in pair["sides"]) for pair in pairs]


class SuggestTests(unittest.TestCase):

    def test_only_ready_built_casual_decks_are_paired_one_for_each_player(self):
        decks = [deck("u", "Usual", "user"), deck("w", "Wifes", "wife"),
                 deck("u2", "Unready", "user", ready=False), deck("w2", "Building", "wife", status="building"),
                 deck("c", "Commander", "wife", kind="commander"), deck("u3", "Also user", "user")]
        pairs = play_pairs.suggest(decks, [], {}, TODAY)
        # Two user decks never make a pair; the not ready, unbuilt and Commander decks take no part.
        self.assertEqual(sorted(ids(pairs)), [("u", "w"), ("u3", "w")])
        for pair in pairs:
            self.assertEqual([side["seat"] for side in pair["sides"]], ["user", "wife"])
            self.assertEqual(pair["evenness"], {"band": "unknown", "source": None, "share": None, "games": 0,
                                                "forge_games": None})
            self.assertEqual(pair["reasons"], ["How even it is isn't known yet: no real games or Forge result.",
                                               "Not played against each other yet."])

    def test_an_either_deck_takes_the_seat_its_partner_leaves(self):
        decks = [deck("e", "Either", "either"), deck("w", "Wifes", "wife"), deck("u", "Usual", "user")]
        found = {frozenset(pair): pair for pair in ids(play_pairs.suggest(decks, [], {}, TODAY, limit=9))}
        self.assertEqual(found[frozenset("ew")], ("e", "w"))
        self.assertEqual(found[frozenset("eu")], ("u", "e"))
        self.assertEqual(found[frozenset("uw")], ("u", "w"))
        # Two "either" decks still make one pair, not two.
        both = play_pairs.suggest([deck("x", "Ex", "either"), deck("y", "Why", "either")], [], {}, TODAY)
        self.assertEqual(ids(both), [("x", "y")])

    def test_ten_real_games_decide_over_forge_and_fewer_leave_it_to_forge(self):
        decks = [deck("u", "Usual", "user"), deck("w", "Wifes", "wife")]
        forge = {("w", "u"): {"value": 0.8, "games": 200}}      # the other order is enough
        [pair] = play_pairs.suggest(decks, games("u", "w", 5, 4, 1), forge, TODAY)
        self.assertEqual(pair["evenness"], {"band": "even", "source": "real", "share": 0.55, "games": 10,
                                            "forge_games": 200})
        self.assertEqual(pair["reasons"][0], "Evenly matched in 10 real games: Usual 5 wins, Wifes 4 wins, 1 draw.")
        [pair] = play_pairs.suggest(decks, games("u", "w", 2, 1), forge, TODAY)
        self.assertEqual(pair["evenness"], {"band": "uneven", "source": "forge", "share": 0.2, "games": 3,
                                            "forge_games": 200})
        self.assertEqual(pair["reasons"][:2], ["One-sided by Forge: Usual wins 20% of 200 simulated games.",
                                               "Only 3 real games so far, too few to go by."])
        # A Forge result whose rate can't be told yet is no result.
        [pair] = play_pairs.suggest(decks, games("u", "w", 1, 0), {("u", "w"): {"value": None, "games": 4}}, TODAY)
        self.assertEqual(pair["evenness"]["band"], "unknown")
        self.assertEqual(pair["reasons"][0], "How even it is isn't known yet: only 1 real game and no Forge result.")

    def test_evenness_ranks_first_then_the_pair_met_longest_ago(self):
        decks = [deck("u1", "A", "user"), deck("u2", "B", "user"), deck("u3", "C", "user"),
                 deck("w1", "D", "wife"), deck("w2", "E", "wife"), deck("w3", "F", "wife")]
        forge = {("u1", "w1"): {"value": 0.5, "games": 100}, ("u2", "w2"): {"value": 0.52, "games": 100},
                 ("u3", "w3"): {"value": 0.65, "games": 100}, ("u1", "w2"): {"value": 0.9, "games": 100},
                 ("u2", "w1"): {"value": 0.9, "games": 100}, ("u3", "w1"): {"value": 0.1, "games": 100},
                 ("u1", "w3"): {"value": 0.9, "games": 100}, ("u2", "w3"): {"value": 0.9, "games": 100},
                 ("u3", "w2"): {"value": 0.9, "games": 100}}
        played = [{"date": "2026-10-28", "sides": ["u1", "w1"], "result": "a"},
                  {"date": "2026-10-01", "sides": ["w2", "u2"], "result": "draw"}]
        pairs = play_pairs.suggest(decks, played, forge, TODAY)
        # Both even pairs before the fairly even one; of the even two, the one met longest ago first.
        self.assertEqual(ids(pairs), [("u2", "w2"), ("u1", "w1"), ("u3", "w3")])
        self.assertEqual([p["evenness"]["band"] for p in pairs], ["even", "even", "fair"])
        self.assertEqual([(p["last_played"], p["days"]) for p in pairs],
                         [("2026-10-01", 28), ("2026-10-28", 1), (None, None)])
        self.assertEqual(pairs[0]["reasons"][-1], "Last played against each other 28 days ago.")
        self.assertEqual(pairs[1]["reasons"][-1], "Last played against each other 1 day ago.")
        self.assertEqual(pairs[0]["evenness"]["games"], 1)

    def test_unknown_evenness_sits_between_fairly_even_and_one_sided(self):
        decks = [deck("u1", "A", "user"), deck("u2", "B", "user"), deck("u3", "C", "user"), deck("w", "W", "wife")]
        forge = {("u1", "w"): {"value": 0.95, "games": 50}, ("u2", "w"): {"value": 0.32, "games": 50}}
        self.assertEqual(ids(play_pairs.suggest(decks, [], forge, TODAY)), [("u2", "w"), ("u3", "w"), ("u1", "w")])

    def test_three_suggestions_spread_over_the_decks_while_they_can(self):
        decks = [deck("u1", "A", "user"), deck("u2", "B", "user"), deck("w1", "C", "wife"), deck("w2", "D", "wife")]
        forge = {("u1", "w1"): {"value": 0.5, "games": 9}, ("u1", "w2"): {"value": 0.5, "games": 9},
                 ("u2", "w2"): {"value": 0.5, "games": 9}, ("u2", "w1"): {"value": 0.99, "games": 9}}
        played = [{"date": "2026-10-20", "sides": ["u2", "w2"], "result": "a"}]
        pairs = play_pairs.suggest(decks, played, forge, TODAY)
        # u1-w1 first; u1-w2 is next by rank but repeats u1, so u2-w2 is chosen before it.
        self.assertEqual(ids(pairs), [("u1", "w1"), ("u1", "w2"), ("u2", "w2")])
        self.assertEqual(len(play_pairs.suggest(decks, played, forge, TODAY, limit=2)), 2)
        self.assertEqual(ids(play_pairs.suggest(decks, played, forge, TODAY, limit=2)), [("u1", "w1"), ("u2", "w2")])

    def test_a_mirror_and_games_with_other_decks_never_count(self):
        decks = [deck("u", "Usual", "user"), deck("w", "Wifes", "wife")]
        played = [{"date": "2026-10-20", "sides": ["u", "u"], "result": "a"},
                  {"date": "2026-10-21", "sides": ["u", "hidden"], "result": "a"},
                  {"date": "2026-10-22", "sides": ["w"], "result": "a"}]
        [pair] = play_pairs.suggest(decks, played, {}, TODAY)
        self.assertEqual((pair["evenness"]["games"], pair["last_played"]), (0, None))
        self.assertEqual(play_pairs.suggest([], played, {}, TODAY), [])
        json.dumps(pair, allow_nan=False)


BUILT = """# {title}

- **Format:** Casual 60-card, 1v1
- **Played by:** {player}
- **Status:** built

## Decklist

```
Deck
{cards}
59 Forest
```
"""


class PairsViewTests(ApiTestCase):
    """GET /api/play/pairs over the sandbox: its collection has five Llanowar Elves and one Elvish Mystic."""

    def setUp(self):
        super().setUp()
        (self.box.root / "config.json").write_text(json.dumps(ROLES), encoding="utf-8")
        self.box.stack.enter_context(mock.patch.object(play, "_play_today", return_value=TODAY))
        # The sandbox's unreadable deck is a pool warning, which leaves every deck's availability unconfirmed.
        self.broken = self.box.magic / "decks" / "casual" / "broken.md"
        self.broken_text = self.broken.read_text(encoding="utf-8")
        self.broken.unlink()
        for slug, title, player, cards in (("alpha", "Alpha", "user", "1 Llanowar Elves (FDN) 227"),
                                           ("beta", "Beta", "wife", "1 Llanowar Elves (FDN) 227"),
                                           ("gamma", "Gamma", "either", "1 Llanowar Elves (FDN) 227"),
                                           ("short", "Short", "wife", "4 Elvish Mystic")):
            _write(self.box.magic / "decks" / "casual" / f"{slug}.md",
                   BUILT.format(title=title, player=player, cards=cards))
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md",
               BUILT.format(title="User2 Elves", player="user", cards="1 Llanowar Elves (FDN) 227")
               .replace("- **Played by:** user\n", ""))
        rate = {"value": 0.5, "games": 120, "versions": ("target", "target")}
        self.forge = self.box.stack.enter_context(mock.patch.object(
            library_forge, "pair_rates", return_value=({("casual/alpha", "casual/beta"): rate}, None)))

    def game(self, a, b, result, day="2026-10-20", space="home"):
        sides = [{**play._snapshot(deck_id, "target"), "player": player, "mulligans": 0}
                 for deck_id, player in ((a, "Matt"), (b, "User1"))]
        record = {"version": 1, "id": uuid.uuid4().hex, "kind": "games", "revision": 1,
                  "created_on": "2026-10-20T01:00:00+00:00", "updated_on": "2026-10-20T01:00:00+00:00",
                  "updated_by": "Matt", "date": day, "result": result, "notes": "", "sides": sides, "space": space}
        self.box.state.play_put("games", record, None, state.Actor("test", "a test"), "Seed a record")

    def test_home_players_get_ready_pairs_with_reasons(self):
        self.game("casual/gamma", "casual/beta", "a", day="2026-10-27")
        with access.viewing("user1"):
            answer = play_tonight.pairs_view()
        self.assertEqual((answer["available"], answer["ready"], answer["error"], answer["forge_error"]),
                         (True, 3, None, None))
        # Short is missing three Elvish Mystic, so it's never suggested.
        self.assertNotIn("casual/short", json.dumps(answer))
        self.assertEqual(ids(answer["pairs"]), [("casual/alpha", "casual/beta"), ("casual/alpha", "casual/gamma"),
                                                ("casual/gamma", "casual/beta")])
        first = answer["pairs"][0]
        self.assertEqual(first["evenness"]["source"], "forge")
        self.assertEqual(first["reasons"], ["Evenly matched by Forge: Alpha wins 50% of 120 simulated games.",
                                            "Not played against each other yet."])
        self.assertEqual(answer["pairs"][2]["reasons"],
                         ["How even it is isn't known yet: only 1 real game and no Forge result.",
                          "Last played against each other 2 days ago."])
        self.assertEqual([s["version"] for s in first["sides"]], ["target", "target"])

    def test_a_member_and_a_request_naming_nobody_get_nothing_about_home(self):
        self.game("casual/alpha", "casual/beta", "a")
        for name, context in (("member", access.using({"profile": "user2", "email": "user2@example.com",
                                                        "remote": True})),
                              ("nobody", access.answering(False))):
            with self.subTest(name), context:
                answer = play_tonight.pairs_view()
                self.assertEqual({k: answer[k] for k in ("available", "pairs", "ready")},
                                 {"available": False, "pairs": [], "ready": 0})
                self.assertNotIn("casual/", json.dumps(answer))
        self.forge.assert_not_called()
        # A script naming nobody (the PC's own) sees home's pairs.
        self.assertTrue(play_tonight.pairs_view()["pairs"])

    def test_without_two_ready_decks_or_the_game_log_nothing_is_suggested(self):
        for slug in ("beta", "gamma"):
            (self.box.magic / "decks" / "casual" / f"{slug}.md").unlink()
        with access.viewing("matt"):
            answer = play_tonight.pairs_view()
        self.assertEqual((answer["available"], answer["ready"], answer["pairs"]), (True, 1, []))
        self.forge.assert_not_called()
        _write(self.box.magic / "decks" / "casual" / "beta.md",
               BUILT.format(title="Beta", player="wife", cards="1 Llanowar Elves (FDN) 227"))
        self.box.state.down = True
        with access.viewing("matt"):
            answer = play_tonight.pairs_view()
        self.assertEqual((answer["error"], answer["pairs"]), (play_tonight.NO_GAMES, []))

    def test_decks_whose_availability_can_t_be_confirmed_are_never_suggested(self):
        _write(self.broken, self.broken_text)
        with access.viewing("matt"):
            answer = play_tonight.pairs_view()
        self.assertEqual((answer["ready"], answer["unconfirmed"], answer["pairs"]), (0, 4, []))

    def test_a_forge_result_of_another_list_than_the_built_one_is_left_out(self):
        # A field addition can put Beta's Play-now list in the field: its share isn't the built list's.
        for versions in (("target", "owned"), ("owned", "target"), None):
            with self.subTest(versions):
                rate = {"value": 0.5, "games": 120}
                if versions:
                    rate["versions"] = versions
                self.forge.return_value = ({("casual/alpha", "casual/beta"): rate}, None)
                with access.viewing("matt"):
                    answer = play_tonight.pairs_view()
                pair = next(p for p in answer["pairs"] if ids([p]) == [("casual/alpha", "casual/beta")])
                self.assertEqual((pair["evenness"]["source"], pair["evenness"]["band"]), (None, "unknown"))
        # Either order of the key is checked against its own versions.
        self.forge.return_value = ({("casual/beta", "casual/alpha"): {"value": 0.5, "games": 120,
                                                                      "versions": ("target", "target")}}, None)
        with access.viewing("matt"):
            answer = play_tonight.pairs_view()
        self.assertEqual(answer["pairs"][0]["evenness"]["source"], "forge")

    def test_forge_s_numbers_failing_leaves_the_real_record(self):
        self.forge.return_value = ({}, library_forge.NO_NUMBERS)
        with access.viewing("matt"):
            answer = play_tonight.pairs_view()
        self.assertEqual(answer["forge_error"], library_forge.NO_NUMBERS)
        self.assertTrue(all(p["evenness"]["band"] == "unknown" for p in answer["pairs"]))


class PairsHttpTests(support.ServerTestCase):

    def test_get_routes_to_the_pairs_and_takes_no_parameters(self):
        answer = {"available": False, "pairs": []}
        with mock.patch.object(play_tonight, "pairs_view", return_value=answer) as view:
            self.assertEqual(self.get_json("/api/play/pairs"), answer)
            view.assert_called_once_with()
            self.assertError("/api/play/pairs?x=1", 400)
            code, headers, _ = self.request("POST", "/api/play/pairs", b"{}")
            self.assertEqual(code, 405)
        self.assertFalse(self.box.forge.runs)


if __name__ == "__main__":
    unittest.main()
