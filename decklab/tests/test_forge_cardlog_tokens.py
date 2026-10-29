"""Tests for the card log's token peaks (E7-S08, decklab/lib/forge/cardlog.py): per game,
side and token name, the most of that token on the battlefield at once, tallied into the
batch record's "tokens" as counts of games by peak; what isn't a token (an effect, a card
from outside the game, a copied spell); moves after the end lines; games whose card data
doesn't count; the cap; and merging and the warm pool's per-game parts.

Hand-written games use test_forge_cardlog's Script. fixtures/forge/cardlog-tokens-s1001.log
is one real Forge game with Rabbit and Cat tokens (cardlog-README.md beside it). No Java is
needed, and nothing here reads Deck Lab's card data.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_cardlog_tokens
"""
import json
import unittest
from copy import deepcopy

from decklab.lib.forge import cardlog
from decklab.lib.forge import pool_models
from decklab.tests import test_forge
from decklab.tests.test_forge_cardlog import Script, dl, plain_game, read, read_file


def token(s, card_id, frm, to, name, seat):
    """A token's move as DeckLabSim logs it, owned by seat (Script.move takes a token's
    owner to be the active seat)."""
    active = s.active if s.turn else "-"
    s.lines.append(dl("zone", s.turn, active, "MAIN1" if s.turn else "-", frm, to, seat, card_id, name))
    return s


def soldiers_game():
    """plain_game, with seat 1 making Soldier tokens: 3 on turn 1, one dies on turn 2, two
    more on turn 3 (4 at once), and seat 2 one Soldier of its own on turn 4."""
    s = Script().keep([1, 2, 3, 5], [21, 23, 24])
    s.at(1).land(3).cast(1, to="Battlefield")
    for card_id in (500, 501, 502):
        token(s, card_id, "-", "Battlefield", "Soldier Token", 1)
    s.at(2).draw(22).land(21).cast(23)
    token(s, 501, "Battlefield", "Graveyard", "Soldier Token", 1)
    s.at(3).draw(4).land(4).cast(2, to="Battlefield")
    for card_id in (503, 504):
        token(s, card_id, "-", "Battlefield", "Soldier Token", 1)
    s.at(4).draw(26)
    return token(s, 600, "-", "Battlefield", "Soldier Token", 2)


class PeakTests(unittest.TestCase):

    def test_the_most_on_the_battlefield_at_once_per_side(self):
        r = read(soldiers_game().finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        # 3, then 2, then 4 at once: one game whose peak was 4. Seat 2's Soldier is its own.
        self.assertEqual(r.cards["tokens"], [{"Soldier Token": [0, 0, 0, 1]}, {"Soldier Token": [1]}])
        self.assertNotIn("Soldier Token", r.cards["rows"][0])     # still never a card row

    def test_sides_follow_the_deck_order(self):
        r = read(soldiers_game().finish(winner=1), deck1=1)
        self.assertEqual(r.cards["tokens"], [{"Soldier Token": [1]}, {"Soldier Token": [0, 0, 0, 1]}])

    def test_every_way_off_the_battlefield_lowers_the_count(self):
        s = plain_game()
        for card_id in (700, 701, 702):
            token(s, card_id, "-", "Battlefield", "Treasure Token", 1)
        token(s, 700, "Battlefield", "Graveyard", "Treasure Token", 1)
        token(s, 701, "Battlefield", "Exile", "Treasure Token", 1)
        token(s, 702, "Battlefield", "Hand", "Treasure Token", 1)      # bounced
        token(s, 703, "-", "Battlefield", "Treasure Token", 1)
        token(s, 704, "-", "Battlefield", "Treasure Token", 1)
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["tokens"][0], {"Treasure Token": [0, 0, 1]})     # 3, down to 0, then 2

    def test_names_are_counted_apart(self):
        s = plain_game()
        token(s, 700, "-", "Battlefield", "Beast Token", 1)
        token(s, 701, "-", "Battlefield", "Faerie Token", 1)
        token(s, 702, "-", "Battlefield", "Faerie Token", 1)
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["tokens"][0], {"Beast Token": [1], "Faerie Token": [0, 1]})

    def test_a_token_copy_of_a_spell_counts_once_it_resolves_onto_the_battlefield(self):
        s = plain_game()
        token(s, 700, "-", "Stack", "Grizzly Bears", 1)                # a copy of a creature spell
        token(s, 701, "-", "Stack", "Lightning Bolt", 2)               # a copy of an instant
        token(s, 701, "Stack", "Graveyard", "Lightning Bolt", 2)
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["tokens"], [{}, {}])                  # still on the Stack: none yet
        s = plain_game()
        token(s, 700, "-", "Stack", "Grizzly Bears", 1)
        token(s, 700, "Stack", "Battlefield", "Grizzly Bears", 1)
        self.assertEqual(read(s.finish(winner=1)).cards["tokens"][0], {"Grizzly Bears": [1]})

    def test_effects_and_cards_from_outside_the_game_arent_tokens(self):
        s = plain_game()
        token(s, 800, "-", "Command", "Lightning Bolt's Effect", 2)
        token(s, 801, "Sideboard", "Hand", "Grizzly Bears", 1)         # a wish's card
        token(s, 801, "Hand", "Battlefield", "Grizzly Bears", 1)
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["tokens"]), (1, [{}, {}]))

    def test_an_id_forge_reuses_is_a_new_token(self):
        s = plain_game()
        token(s, 700, "-", "Battlefield", "Beast Token", 1)
        token(s, 701, "-", "Battlefield", "Beast Token", 1)
        token(s, 700, "Battlefield", "Graveyard", "Beast Token", 1)
        token(s, 700, "-", "Battlefield", "Elf Token", 1)              # the same id made again
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["tokens"][0], {"Beast Token": [0, 1], "Elf Token": [1]})

    def test_a_token_without_a_known_owner_has_no_side(self):
        s = plain_game()
        token(s, 700, "-", "Battlefield", "Beast Token", "-")
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["tokens"]), (1, [{}, {}]))

    def test_moves_after_the_end_lines_arent_counted(self):
        s = plain_game()
        token(s, 700, "-", "Battlefield", "Beast Token", 1)
        lines = s.finish(winner=1)
        late = dl("zone", 4, 2, "MAIN1", "-", "Battlefield", 1, 701, "Beast Token")
        lines.insert(len(lines) - 1, late)          # after the end lines, before Game Result
        r = read(lines)
        self.assertEqual((r.cards["games"], r.cards["tokens"][0]), (1, {"Beast Token": [1]}))

    def test_a_game_whose_card_data_doesnt_count_adds_no_peaks(self):
        s = soldiers_game()
        r = read(s.finish(winner=1, library={1: 99}), soldiers_game().finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 1))
        self.assertEqual(r.cards["tokens"][0], {"Soldier Token": [0, 0, 0, 1]})   # the good game's only

    def test_counts_of_games_by_peak(self):
        one = plain_game()
        token(one, 700, "-", "Battlefield", "Beast Token", 1)
        two = plain_game()
        token(two, 700, "-", "Battlefield", "Beast Token", 1)
        token(two, 701, "-", "Battlefield", "Beast Token", 1)
        r = read(two.finish(winner=1), one.finish(winner=1), plain_game().finish(winner=2),
                 deepcopy(two.lines))
        # peaks 2, 1, none and 2: games 4, and the one without a Beast is 4 less their sum
        self.assertEqual((r.cards["games"], r.cards["tokens"][0]), (4, {"Beast Token": [1, 2]}))

    def test_a_peak_over_the_cap_counts_as_the_cap(self):
        s = plain_game()
        for card_id in range(700, 700 + cardlog.PEAK_CAP + 5):
            token(s, card_id, "-", "Battlefield", "Saproling Token", 1)
        peaks = read(s.finish(winner=1)).cards["tokens"][0]["Saproling Token"]
        self.assertEqual((len(peaks), peaks[-1], sum(peaks)), (cardlog.PEAK_CAP, 1, 1))

    def test_the_record_is_plain_json(self):
        r = read(soldiers_game().finish(winner=1))
        self.assertEqual(json.loads(json.dumps(r.cards)), r.cards)

    def test_without_the_card_log_there_is_no_record(self):
        self.assertIsNone(read(soldiers_game().finish(winner=1), card_log=False).cards)

    def test_a_real_game(self):
        # cardlog-README.md: Selesnya's Rabbits went 1, 4, 3, 6, 7, then 6 (one blocked a
        # deathtouch creature), and one Cat came on turn 13; Orzhov made none.
        r = read_file(test_forge.HERE / "cardlog-tokens-s1001.log")
        self.assertEqual((r.cards["games"], r.cards["bad"], r.card_problems), (1, 0, []))
        self.assertEqual(r.cards["tokens"], [{"Rabbit Token": [0, 0, 0, 0, 0, 0, 1], "Cat Token": [1]}, {}])
        self.assertNotIn("Rabbit Token", r.cards["rows"][0])


class RecordTests(unittest.TestCase):

    def record(self, tokens=None, **rest):
        out = cardlog.new_record()
        out.update(games=2, wins=[1, 1], first=[1, 1], **rest)
        if tokens is None:
            del out["tokens"]
        else:
            out["tokens"] = tokens
        return out

    def test_a_new_record_has_no_tokens_yet(self):
        self.assertEqual(cardlog.new_record()["tokens"], [{}, {}])

    def test_merging_sums_the_counts_number_by_number(self):
        a = self.record([{"Beast Token": [1, 1]}, {}])
        b = self.record([{"Beast Token": [0, 0, 2], "Elf Token": [1]}, {"Beast Token": [2]}])
        merged = cardlog.merge_record(json.loads(json.dumps(a)), b)
        self.assertEqual(merged["tokens"], [{"Beast Token": [1, 1, 2], "Elf Token": [1]}, {"Beast Token": [2]}])
        self.assertEqual(b["tokens"][0]["Beast Token"], [0, 0, 2])                 # unchanged
        merged["tokens"][0]["Elf Token"][0] += 1
        self.assertEqual(b["tokens"][0]["Elf Token"], [1])                          # not shared

    def test_a_record_that_didnt_tally_tokens_leaves_the_merge_without_them(self):
        for into, other in ((self.record([{"Beast Token": [1]}, {}]), self.record()),
                            (self.record(), self.record([{"Beast Token": [1]}, {}]))):
            with self.subTest(into_has="tokens" in into):
                self.assertNotIn("tokens", cardlog.merge_record(into, other))
        self.assertNotIn("tokens", cardlog.merge_record(self.record(), self.record()))

    def test_each_games_part_adds_up_to_the_chunks_record(self):
        # The warm pool sends each game's part of a chunk's record (pool_models._cards_delta)
        # and the run merges them (runner_v2): the tokens must add up as the rows do.
        one = plain_game()
        token(one, 700, "-", "Battlefield", "Beast Token", 1)
        token(one, 701, "-", "Battlefield", "Beast Token", 1)
        two = plain_game()
        token(two, 700, "-", "Battlefield", "Beast Token", 1)
        token(two, 701, "-", "Battlefield", "Elf Token", 2)
        games = [one.finish(winner=1), two.finish(winner=2), plain_game().finish(winner=1)]
        reader = read()
        parts, before = [], deepcopy(reader.cards)
        for lines in games:
            for line in lines:
                reader.feed(line + "\n")
            parts.append(pool_models._cards_delta(reader.cards, before))
            before = deepcopy(reader.cards)
        self.assertEqual([p["tokens"] for p in parts],
                         [[{"Beast Token": [0, 1]}, {}], [{"Beast Token": [1]}, {"Elf Token": [1]}], [{}, {}]])
        merged = deepcopy(parts[0])
        for part in parts[1:]:
            cardlog.merge_record(merged, part)
        self.assertEqual(merged["tokens"], reader.cards["tokens"])
        self.assertEqual(merged["tokens"], [{"Beast Token": [1, 1]}, {"Elf Token": [1]}])

    def test_tokens_less(self):
        self.assertEqual(cardlog.tokens_less([{"A": [1, 2]}, {"B": [1]}], [{"A": [1, 1]}, {"B": [1]}]),
                         [{"A": [0, 1]}, {}])
        self.assertEqual(cardlog.tokens_less([{"A": [0, 1]}, {}], None), [{"A": [0, 1]}, {}])

    def test_a_part_of_a_record_without_tokens_has_none(self):
        now = self.record()
        self.assertNotIn("tokens", pool_models._cards_delta(now, self.record()))


if __name__ == "__main__":
    unittest.main()
