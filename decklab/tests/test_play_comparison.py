"""Historical human results match only the visible deck pair and Forge's executed cards.

Every record, config, deck and visibility switch belongs to Sandbox/MemoryStore.
No database, real user records, Forge process, network or Git write is used.
"""
import copy
from dataclasses import replace
import uuid
from unittest import mock

from decklab.lib import access, api, decks, inventory, spaces, state
from decklab.lib.api import play_comparison as comparison
from decklab.lib.api import play_records as play
from decklab.lib.forge import lists as forge_lists
from decklab.tests import household_config
from decklab.tests.test_api import ApiTestCase, _write

ACTOR = state.Actor("test", "Fixture")
WHEN = "2026-10-26T01:00:00+00:00"
DECK = """# Fixture A

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** building

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
56 Forest

Sideboard
2 Pick Your Poison (MKM) 170
```
"""


class PlayComparisonTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        household_config.use(self)
        self.active = access.using({"profile": "matt", "email": "matt@example.com", "remote": True})
        self.active.__enter__()
        self.addCleanup(self.active.__exit__, None, None, None)
        for deck_id, name in (("casual/a", "Fixture A"), ("casual/b", "Fixture B"), ("casual/c", "Fixture C"),
                              ("user2/casual/a", "Member A"), ("user2/casual/b", "Member B")):
            self.put_deck(deck_id, DECK.replace("Fixture A", name).replace("Llanowar Elves", "Elvish Mystic")
                          if deck_id.endswith("/b") else DECK.replace("Fixture A", name))

    def put_deck(self, deck_id, text):
        space, kind, slug = spaces.split_deck_id(deck_id)
        folder = self.box.magic / "decks" if space == "home" else self.box.magic / "people" / space / "decks"
        _write(folder / kind / (slug + ".md"), text)

    def snapshot(self, deck_id):
        with access.using(None), access.viewing(None):
            return play._snapshot(deck_id, "target")

    def pair(self, a="casual/a", b="casual/b", *, sections=None, fmt="Constructed"):
        answer = []
        kind = "commander" if fmt == "Commander" else "constructed"
        for index, deck_id in enumerate((a, b)):
            source = sections[index] if sections else decks.load_deck(deck_id, "target")
            answer.append({"id": deck_id, "version": "target", "kind": spaces.split_deck_id(deck_id)[1],
                           "title": "Fixture side " + str(index), "card_sha": forge_lists.card_sha(source, kind)})
        return answer

    def record(self, a="casual/a", b="casual/b", *, result="a", day="2026-10-25", snapshots=None):
        sides = copy.deepcopy(snapshots or [self.snapshot(a), self.snapshot(b)])
        for side in sides:
            side.update(player="Fixture player", mulligans=0)
        record_id = uuid.uuid4().hex
        record = {"version": 1, "id": record_id, "kind": "games", "revision": 1,
                  "created_on": WHEN, "updated_on": WHEN, "updated_by": "Fixture",
                  "notes": "Fixture private note", "space": spaces.split_deck_id(a)[0],
                  "date": day, "result": result, "sides": sides}
        self.box.state.play_put("games", record, None, ACTOR, "Seed fixture game")
        return record_id

    def summary(self, sides=None, fmt="Constructed"):
        return comparison.summarize(sides or self.pair(), fmt)

    def stored(self, record_id):
        return self.box.state._play["games", record_id]["content"]

    def rehash(self, side):
        side["sha256"] = play._hash(play._bytes({key: side[key] for key in ("id", "version", "sections")}))

    def assert_unavailable(self, answer):
        self.assertEqual(answer, {"status": "unavailable", "reason": comparison.UNAVAILABLE, "minimum_games": 10})

    def test_zero_games_has_explicit_empty_dates_and_no_writes(self):
        before = self.box.state.changes()
        with mock.patch.object(self.box.state, "play_put", side_effect=AssertionError("Read wrote records")):
            answer = self.summary()
        self.assertEqual(answer, {"status": "ready", "games": 0, "wins": [0, 0], "draws": 0,
                                  "first_date": None, "last_date": None, "minimum_games": 10})
        self.assertEqual(self.box.state.changes(), before)

    def test_reversed_seats_draws_and_date_range_keep_the_requested_orientation(self):
        self.record(result="a", day="2026-10-21")
        self.record("casual/b", "casual/a", result="a", day="2026-10-24")
        self.record(result="draw", day="2026-10-25")
        before = copy.deepcopy(self.box.state._play)
        answer = self.summary()
        self.assertEqual((answer["games"], answer["wins"], answer["draws"]), (3, [1, 1], 1))
        self.assertEqual((answer["first_date"], answer["last_date"]), ("2026-10-21", "2026-10-25"))
        self.assertEqual(self.summary(list(reversed(self.pair())))["wins"], [1, 1])
        self.assertEqual(self.box.state._play, before)

    def test_an_unrelated_deck_with_identical_cards_is_not_this_pair(self):
        self.record("casual/c", "casual/b")
        self.assertEqual(self.summary()["games"], 0)

    def test_old_lists_remain_separate_after_current_decks_change(self):
        pair = self.pair()
        self.record()
        self.put_deck("casual/a", DECK.replace("56 Forest", "55 Forest"))
        self.assertEqual(self.summary()["games"], 0)
        self.assertEqual(self.summary(pair)["wins"], [1, 0])

    def test_version_printing_order_and_unused_sideboard_changes_do_not_change_executed_cards(self):
        record_id = self.record()
        side = self.stored(record_id)["sides"][0]
        side["version"] = "owned"
        side["sections"]["Deck"].reverse()
        side["sections"]["Deck"][1].update(set="m19", number="314", finish="foil")
        side["sections"]["Sideboard"][0]["qty"] = 3
        self.rehash(side)
        self.assertEqual(self.summary()["wins"], [1, 0])

    def test_actual_sideboarded_sections_match_the_played_main_not_the_base_or_current_plan(self):
        base = self.snapshot("casual/a")
        after = play._plan_moves(base, [{"name": "Llanowar Elves", "qty": 2}], [{"name": "Pick Your Poison", "qty": 2}])["after"]
        played = copy.deepcopy(base)
        played.update(base_sha256=base["sha256"], sections=after, plan_id="f" * 32, plan_sha256="e" * 64)
        self.rehash(played)
        self.record(snapshots=[played, self.snapshot("casual/b")])
        self.assertEqual(self.summary()["games"], 0)
        sections = {section: [decks.DeckLine(line["qty"], line["name"]) for line in rows] for section, rows in after.items()}
        pair = self.pair(sections=[sections, decks.load_deck("casual/b")])
        with mock.patch.object(self.box.state, "play_get", side_effect=AssertionError("No current plan lookup")):
            self.assertEqual(self.summary(pair)["wins"], [1, 0])

    def test_renamed_and_retired_identity_aliases_match_without_mutating_saved_snapshots(self):
        self.record()
        pair = self.pair()
        pair[0]["id"] = "casual/renamed"
        snapshot = replace(inventory.current(), deck_aliases={"casual/a": "casual/renamed"})
        before = copy.deepcopy(self.box.state._play)
        with mock.patch.object(inventory, "current", return_value=snapshot):
            self.assertEqual(self.summary(pair)["wins"], [1, 0])
        self.assertEqual(self.box.state._play, before)

    def test_same_cards_distinct_id_is_unambiguous_but_same_identity_mirror_is_unsupported(self):
        self.record("casual/a", "casual/c", result="b")
        self.assertEqual(self.summary(self.pair("casual/a", "casual/c"))["wins"], [0, 1])
        with mock.patch.object(self.box.state, "play_list", side_effect=AssertionError("Unsupported must not read")):
            answer = self.summary(self.pair("casual/a", "casual/a"))
        self.assertEqual(answer, {"status": "unsupported", "reason": comparison.UNSUPPORTED, "minimum_games": 10})

    def test_same_identity_different_executed_lists_has_an_unambiguous_orientation(self):
        one = self.snapshot("casual/a")
        other = copy.deepcopy(one)
        other["sections"]["Deck"][0]["qty"] -= 1
        other["version"] = "owned"
        self.rehash(other)
        self.record(snapshots=[other, one], result="a")
        sections = {section: [decks.DeckLine(line["qty"], line["name"]) for line in rows]
                    for section, rows in other["sections"].items()}
        pair = self.pair("casual/a", "casual/a", sections=[decks.load_deck("casual/a"), sections])
        self.assertEqual(self.summary(pair)["wins"], [0, 1])

    def test_beginner_pairings_keep_the_same_identity_when_half_order_is_reversed(self):
        self.record("pairing/elves+cats", "casual/b")
        pair = self.pair("pairing/cats+elves", "casual/b")
        self.assertEqual(self.summary(pair)["wins"], [1, 0])

    def test_commander_fingerprint_preserves_the_commander_separate_from_the_main(self):
        source = DECK.replace("Casual 60-card, 1v1", "Commander").replace("Deck\n", "Commander\n1 Ghalta, Primal Hunger\n\nDeck\n", 1)
        self.put_deck("commander/a", source)
        self.put_deck("commander/b", source.replace("Llanowar Elves", "Elvish Mystic"))
        self.record("commander/a", "commander/b", result="b")
        pair = self.pair("commander/a", "commander/b", fmt="Commander")
        self.assertEqual(self.summary(pair, "Commander")["wins"], [0, 1])

    def test_public_decks_do_not_publish_private_real_games(self):
        self.record("user2/casual/a", "user2/casual/b")
        self.box.state.visibility_set("user2", "decks", True, ACTOR, "Publish fixture decks")
        pair = self.pair("user2/casual/a", "user2/casual/b")
        with mock.patch.object(play, "_checked", side_effect=AssertionError("Private game validated")):
            self.assertEqual(self.summary(pair)["games"], 0)
        self.box.state.visibility_set("user2", "games", True, ACTOR, "Publish fixture games")
        self.assertEqual(self.summary(pair)["wins"], [1, 0])

    def test_hidden_and_removed_game_sides_are_not_hashed_or_validated(self):
        self.record("casual/a", "user2/casual/b")
        record_id = self.record()
        self.stored(record_id)["sides"][1] = {"removed": True, "title": "a removed deck", "space": "home"}
        with mock.patch.object(play, "_checked", side_effect=AssertionError("Hidden or removed side validated")), \
                mock.patch.object(comparison, "_fingerprint", side_effect=AssertionError("Hidden side hashed")):
            self.assertEqual(self.summary()["games"], 0)

    def test_visible_matching_corruption_is_unavailable_without_partial_counts_or_private_detail(self):
        self.record()
        record_id = self.record()
        self.stored(record_id)["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        self.assert_unavailable(self.summary())

    def test_corrupt_unrelated_game_does_not_poison_this_pair(self):
        record_id = self.record("casual/c", "casual/b")
        self.stored(record_id)["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        self.record()
        self.assertEqual(self.summary()["games"], 1)

    def test_basic_format_dates_and_unknown_sections_are_unavailable_for_candidates(self):
        for corruption in ("date", "section"):
            with self.subTest(corruption=corruption):
                self.box.state._play.clear()
                record_id = self.record()
                content = self.stored(record_id)
                if corruption == "date":
                    content["date"] = "20261025"
                else:
                    side = content["sides"][0]
                    side["sections"]["Unexpected section"] = []
                    self.rehash(side)
                self.assert_unavailable(self.summary())

    def test_read_failure_never_exposes_exception_or_claims_zero_games(self):
        with mock.patch.object(self.box.state, "play_list", side_effect=state.Unavailable("Fixture private details")):
            self.assert_unavailable(self.summary())

    def test_file_unknown_identity_and_kind_mismatch_are_unsupported_without_record_reads(self):
        for change, fmt in (({"id": "file:fixture.dck"}, "Constructed"), ({"kind": "unknown"}, "Constructed"),
                            ({}, "Commander"), ({"card_sha": "bad"}, "Constructed")):
            pair = self.pair()
            pair[0].update(change)
            with self.subTest(change=change, fmt=fmt), \
                    mock.patch.object(self.box.state, "play_list", side_effect=AssertionError("Unsupported read")):
                self.assertEqual(self.summary(pair, fmt)["status"], "unsupported")

    def test_matchup_hook_keeps_forge_answer_when_real_records_are_unavailable(self):
        with mock.patch.object(self.box.state, "play_list", side_effect=state.Unavailable("Private fixture error")):
            answer = api.matchup("casual/a", "target", "casual/b", "target")
        self.assertEqual(answer["status"], "none")
        self.assert_unavailable(answer["real_games"])

    def test_matchup_hook_aggregates_visible_games_and_flips_wins_with_requested_sides(self):
        self.record(result="a")
        original = self.box.forge.entry
        def canonical_entry(deck_id, version, title, kind, sections):
            answer = original(deck_id, version, title, kind, sections)
            answer["card_sha"] = forge_lists.card_sha(sections, kind)
            return answer
        with mock.patch.object(self.box.forge, "entry", side_effect=canonical_entry):
            answer = api.matchup("casual/a", "target", "casual/b", "target")
            reverse = api.matchup("casual/b", "target", "casual/a", "target")
        self.assertEqual((answer["real_games"]["status"], answer["real_games"]["games"], answer["real_games"]["wins"]),
                         ("ready", 1, [1, 0]))
        self.assertEqual((reverse["real_games"]["games"], reverse["real_games"]["wins"]), (1, [0, 1]))
        self.assertEqual(answer["sides"][0]["id"], "casual/a")
        self.assertEqual(reverse["sides"][0]["id"], "casual/b")
