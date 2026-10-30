"""Tests for the card log (decklab/lib/forge/cardlog.py) and LogReader's reading of it:
what each card did in a game (drawn, used, stuck, discarded, other casts, in hand by turn
3, the commander's casts, and failed casts, which aren't casts), the five checks that drop
a game's card data, the batch record, and that the DL lines change nothing else LogReader
reads. A Script's games mostly end before either side's 3rd own turn (seat 1's begins at
turn 5, seat 2's at 6), so every drawn copy there is in hand by turn 3 too: the last two
numbers of a row repeat drawn_games and drawn_wins. test_forge_cardlog3 tests the cut-off
itself.

Hand-written games (Script) cover each definition and check. fixtures/forge/cardlog-s7.log
is DeckLabSim's real output for one Forge 2.0.15 game (Gruul Ramp vs Izzet Prowess, seed
7), cardlog-opening-s2.log for one with opening-hand actions (a Leyline and Gemstone
Caverns), and cardlog-failed-cast-s5.log for one with a failed cast (see cardlog-README.md
beside them). fixtures/fake_forge.py --card-log is run as a process for whole batches.
No Java is needed.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_forge_cardlog
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import forge
from decklab.lib.forge import cardlog, logreader
from decklab.tests import test_forge

HEADER = "Ai(1)-aaa [Default] vs Ai(2)-bbb [Default] - one game of Constructed seed 1"
GREEN = {1: "Llanowar Elves", 2: "Llanowar Elves", 3: "Forest", 4: "Forest", 5: "Giant Growth",
         6: "Murderous Rider", 7: "Grizzly Bears", 8: "Overrun", 9: "Forest", 10: "Grizzly Bears"}
RED = {21: "Mountain", 22: "Mountain", 23: "Lightning Bolt", 24: "Lightning Bolt", 25: "Fire // Ice",
       26: "Mountain", 27: "Swamp", 28: "Devout Decree", 29: "Mountain", 30: "Lightning Bolt"}
# the rest of Forge's line for a failed cast, after "Add To Stack: <name> (<id>) - "
FAILED = "[Couldn't add to stack, failed to target] - Target creature gets +3/+3 until end of turn."


def dl(*fields):
    return cardlog.PREFIX + "|".join(str(f) for f in fields)


def listed(ids, names):
    return ";".join(f"{i}={names[i]}" for i in ids)


class Script:
    """A hand-written game as DeckLabSim prints it: DL lines and the Forge lines LogReader
    reads, in order. It keeps track of where each card is, so its end lines are right
    unless a test makes them wrong (finish's end_hand and library)."""

    def __init__(self, decks=None, commanders=None, log_line=True):
        self.decks = decks or {1: GREEN, 2: RED}
        self.commanders = commanders or {}
        self.names, self.seat, self.zone = {}, {}, {}
        for seat in (1, 2):
            for zone, cards in (("Library", self.decks[seat]), ("Command", self.commanders.get(seat, {}))):
                for card_id, name in cards.items():
                    self.names[card_id], self.seat[card_id], self.zone[card_id] = name, seat, zone
        self.turn, self.active = 0, 1
        self.lines = [dl("log", 1)] if log_line else []
        for seat in (1, 2):
            self.lines.append(dl("deck", seat, listed(sorted(self.decks[seat]), self.names)))
            if seat in self.commanders:
                self.lines.append(dl("commander", seat, listed(sorted(self.commanders[seat]), self.names)))

    def move(self, card_id, frm, to, name=None):
        active = self.active if self.turn else "-"
        phase = "MAIN1" if self.turn else "-"
        seat = self.seat.get(card_id, self.active)
        self.lines.append(dl("zone", self.turn, active, phase, frm, to, seat, card_id,
                             name or self.names[card_id]))
        if card_id in self.zone:
            self.zone[card_id] = to
        return self

    def ids(self, seat, zone):
        return [i for i in sorted(self.decks[seat]) + sorted(self.commanders.get(seat, {})) if self.zone[i] == zone]

    def keep(self, hand1, hand2, kept=None, bottom=(), opening=()):
        """Draw the opening hands (turn 0), put the cards in bottom back (a London
        mulligan), Forge's Mulligan lines (kept: {seat: size} to say otherwise), the
        opening-hand actions' moves (opening: [(id, to)], still at turn 0), and the
        DL|hand start lines as turn 1 begins."""
        for seat, hand in ((1, hand1), (2, hand2)):
            for card_id in hand:
                self.move(card_id, "Library", "Hand")
        for card_id in bottom:
            self.move(card_id, "Hand", "Library")
        for seat in (1, 2):
            size = (kept or {}).get(seat, len(self.ids(seat, "Hand")))
            self.lines.append(f"Mulligan: Ai({seat})-x has kept a hand of {size} cards")
        for card_id, to in opening:
            self.move(card_id, "Hand", to)
        for seat in (1, 2):
            self.lines.append(dl("hand", 1, "start", seat, listed(self.ids(seat, "Hand"), self.names)))
        return self

    def at(self, turn):
        """Forge's Turn line: seat 1 has the odd turns."""
        self.turn, self.active = turn, 1 if turn % 2 else 2
        self.lines.append(f"Turn: Turn {turn} (Ai({self.active})-x)")
        return self

    def draw(self, card_id):
        return self.move(card_id, "Library", "Hand")

    def land(self, card_id, frm="Hand"):
        self.move(card_id, frm, "Battlefield")
        self.lines.append(f"Land: Ai({self.active})-x played {self.names[card_id]} ({card_id})")
        return self

    def cast(self, card_id, frm="Hand", to="Graveyard"):
        self.move(card_id, frm, "Stack")
        self.lines.append(f"Add To Stack: Ai({self.active})-x cast {self.names[card_id]}")
        return self.move(card_id, "Stack", to)

    def fail(self, card_id, frm="Hand"):
        """A failed cast as Forge 2.0.15 logs it: the card moves to the Stack, Forge can't
        target and says so, and the card stays on the Stack."""
        self.move(card_id, frm, "Stack")
        self.lines.append(f"Add To Stack: {self.names[card_id]} ({card_id}) - " + FAILED)
        return self

    def finish(self, winner=1, end_hand=None, library=None, timeout=False):
        """The game's end: outcome lines, the DL end lines (end_hand / library {seat: ...}
        replace what the moves left) and Game Result."""
        if timeout:
            self.lines += ["Stopping slow match as draw",
                           "Game Outcome: Ai(1)-x has won because all opponents have lost",
                           "Game Outcome: Ai(2)-x has won because all opponents have lost"]
        elif winner:
            self.lines += [f"Game Outcome: Ai({winner})-x has won because all opponents have lost",
                           f"Game Outcome: Ai({3 - winner})-x has lost because life total reached 0"]
        for seat in (1, 2):
            hand = (end_hand or {}).get(seat, self.ids(seat, "Hand"))
            self.lines.append(dl("hand", self.turn, "end", seat, listed(hand, self.names)))
        for seat in (1, 2):
            self.lines.append(dl("library", self.turn, "end", seat,
                                 (library or {}).get(seat, len(self.ids(seat, "Library")))))
        if winner and not timeout:
            self.lines.append(f"Game Result: Game 1 ended in 100 ms. Ai({winner})-x has won!")
        else:
            self.lines.append("Game Result: Game 1 ended in a Draw! Took 100 ms.")
        return self.lines


def read(*games, deck1=0, names=None, card_log=True):
    """A LogReader (card log on) fed the header and each game's lines."""
    reader = forge.LogReader(deck1, names, card_log=card_log)
    reader.feed(HEADER)
    for lines in games:
        for line in lines:
            reader.feed(line + "\n")
    return reader


def read_file(path, deck1=0, card_log=True):
    reader = forge.LogReader(deck1, card_log=card_log)
    with open(path, encoding="utf-8") as f:
        for line in f:
            reader.feed(line)
    return reader


def plain_game():
    """A short valid game: seat 1 keeps Elves, Elves, Forest, Giant Growth; seat 2 Mountain,
    Bolt, Bolt. Seat 1 plays Forest and casts an Elves on turn 1, draws a Forest on turn 3
    and plays it, and wins on turn 4 with Giant Growth still in hand."""
    s = Script().keep([1, 2, 3, 5], [21, 23, 24])
    s.at(1).land(3).cast(1, to="Battlefield")
    s.at(2).draw(22).land(21).cast(23)
    s.at(3).draw(4).land(4).cast(2, to="Battlefield")
    s.at(4).draw(26)
    return s


# ============================================================ what each card did

class DefinitionTests(unittest.TestCase):

    def test_drawn_used_stuck_and_rounds(self):
        r = read(plain_game().finish(winner=1))
        c = r.cards
        self.assertEqual({k: c[k] for k in ("v", "games", "bad", "wins", "first")},
                         {"v": cardlog.RECORD_VERSION, "games": 1, "bad": 0, "wins": [1, 0], "first": [1, 0]})
        # [drawn_games, drawn_wins, copies_drawn, used, stuck, used_round_sum, other_casts, discarded,
        #  early_games, early_wins]: the game ends on turn 4, before either side's 3rd own turn
        self.assertEqual(c["rows"][0], {
            "Llanowar Elves": [1, 1, 2, 2, 0, 1 + 2, 0, 0, 1, 1],     # cast turns 1 and 3: rounds 1 and 2
            "Forest": [1, 1, 2, 2, 0, 1 + 2, 0, 0, 1, 1],             # one kept, one drawn on turn 3
            "Giant Growth": [1, 1, 1, 0, 1, 0, 0, 0, 1, 1]})          # held to the end: stuck
        self.assertEqual(c["rows"][1], {
            "Mountain": [1, 0, 3, 1, 2, 1, 0, 0, 1, 0],               # 21 played on turn 2 (round 1); 22, 26 held
            "Lightning Bolt": [1, 0, 2, 1, 1, 1, 0, 0, 1, 0]})
        self.assertEqual(c["commander"], [{}, {}])
        self.assertEqual(r.card_problems, [])

    def test_sides_follow_the_deck_order(self):
        r = read(plain_game().finish(winner=1), deck1=1)
        self.assertEqual((r.cards["wins"], r.cards["first"]), ([0, 1], [0, 1]))
        self.assertEqual(r.cards["rows"][1]["Llanowar Elves"], [1, 1, 2, 2, 0, 3, 0, 0, 1, 1])
        self.assertIn("Lightning Bolt", r.cards["rows"][0])

    def test_a_mulligan_to_six_counts_only_the_kept_cards(self):
        s = Script()
        for card_id in (1, 2, 3, 4, 5, 6, 7):           # the first seven, shuffled back
            s.move(card_id, "Library", "Hand")
        for card_id in (1, 2, 3, 4, 5, 6, 7):
            s.move(card_id, "Hand", "Library")
        # the second seven, one of them (Murderous Rider) put on the bottom, still at turn 0
        s.keep([8, 9, 10, 1, 3, 5, 6], [21, 22, 23, 24, 25, 26, 27], bottom=[6])
        self.assertIn("Mulligan: Ai(1)-x has kept a hand of 6 cards", s.lines)
        r = read(s.at(1).land(3).finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        rows = r.cards["rows"][0]
        self.assertNotIn("Murderous Rider", rows)          # drawn for the mulligan, not kept
        self.assertEqual(rows["Llanowar Elves"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])     # 1 kept, 2 went back
        self.assertEqual(rows["Grizzly Bears"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])     # 10 kept; 7 went back
        self.assertEqual(rows["Forest"], [1, 0, 2, 1, 1, 1, 0, 0, 1, 0])
        self.assertEqual(sum(v[2] for v in rows.values()), 6)

    def test_opening_hand_actions_count_as_drawn_and_used_in_round_1(self):
        # Forge 2.0.15 puts a Leyline (and Gemstone Caverns, which exiles a card from the
        # hand) onto the battlefield at turn 0, after the keep and before the start hands.
        deck = {**GREEN, 11: "Leyline of the Void", 13: "Leyline of the Void"}
        s = Script(decks={1: deck, 2: RED})
        s.keep([3, 5, 11, 13, 1], [21, 23, 24, 22], opening=[(11, "Battlefield"), (13, "Battlefield")])
        self.assertIn("Mulligan: Ai(1)-x has kept a hand of 5 cards", s.lines)
        self.assertIn(dl("hand", 1, "start", 1, "1=Llanowar Elves;3=Forest;5=Giant Growth"), s.lines)
        s.at(1).land(3)
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Leyline of the Void"], [1, 1, 2, 2, 0, 1 + 1, 0, 0, 1, 1])
        self.assertEqual(sum(v[2] for v in r.cards["rows"][0].values()), 5)

    def test_gemstone_caverns_and_the_card_it_exiles(self):
        deck = {**RED, 31: "Gemstone Caverns"}
        s = Script(decks={1: GREEN, 2: deck})
        s.keep([3, 4], [31, 23, 21], opening=[(31, "Battlefield"), (23, "Exile")])
        s.at(1).land(3)
        s.at(2).land(21)
        r = read(s.finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        red = r.cards["rows"][1]
        self.assertEqual(red["Gemstone Caverns"], [1, 1, 1, 1, 0, 1, 0, 0, 1, 1])  # put onto the battlefield in round 1
        self.assertEqual(red["Lightning Bolt"], [1, 1, 1, 0, 0, 0, 0, 0, 1, 1])    # exiled: drawn, not used
        self.assertEqual(sum(v[2] for v in red.values()), 3)

    def test_a_tutor_and_a_return_count_as_drawn(self):
        s = Script().keep([3, 4], [21])
        s.at(1).land(3)
        s.at(2).land(21)
        s.at(3).move(7, "Library", "Hand").cast(7, to="Battlefield")       # tutored and cast
        s.move(7, "Battlefield", "Graveyard")
        s.at(5).move(7, "Graveyard", "Hand")                                # returned, held
        s.move(1, "Library", "Graveyard")                                   # milled: never drawn
        r = read(s.finish(winner=1))
        # tutored on turn 3, seat 1's 2nd own turn: in hand by its 3rd (turn 5)
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 1, 1, 1, 1, 2, 0, 0, 1, 1])
        self.assertNotIn("Llanowar Elves", r.cards["rows"][0])

    def test_a_card_cast_bounced_and_held_is_used_and_stuck(self):
        s = Script().keep([3, 7], [21])
        s.at(1).land(3)
        s.at(3).cast(7, to="Battlefield")
        s.at(4).move(7, "Battlefield", "Hand")                  # bounced
        s.at(5).cast(7, to="Battlefield")                       # recast: still one use, round 2 counts
        s.at(6).move(7, "Battlefield", "Hand")                  # bounced again, and held
        r = read(s.finish(winner=2))
        self.assertEqual(r.cards["rows"][0]["Grizzly Bears"], [1, 0, 1, 1, 1, 2, 0, 0, 1, 0])

    def test_a_discard_is_neither_used_nor_stuck(self):
        s = Script().keep([3, 5, 8], [21])
        s.at(1).land(3)
        s.at(2).move(8, "Hand", "Graveyard")                    # discarded
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["rows"][0]["Overrun"], [1, 1, 1, 0, 0, 0, 0, 1, 1, 1])

    def test_casts_from_other_zones(self):
        # Murderous Rider: Swift End from the hand (exiled as it resolves), then the creature
        # from exile. Fire // Ice milled, then cast from the graveyard: never drawn.
        s = Script().keep([3, 6], [21])
        s.at(1).land(3)
        s.at(3).cast(6, to="Exile")
        s.at(5).cast(6, frm="Exile", to="Battlefield")
        s.at(6).move(25, "Library", "Graveyard").cast(25, frm="Graveyard", to="Exile")
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["rows"][0]["Murderous Rider"], [1, 1, 1, 1, 0, 2, 1, 0, 1, 1])
        self.assertEqual(r.cards["rows"][1]["Fire // Ice"], [0, 0, 0, 0, 0, 0, 1, 0, 0, 0])     # never in hand

    def test_a_commander(self):
        s = Script(commanders={1: {50: "Ghoulcaller Gisa"}, 2: {60: "Giada, Font of Hope"}})
        s.keep([3, 4, 9], [21])
        s.at(1).land(3)
        s.at(3).land(4)
        s.at(5).land(9).cast(50, frm="Command", to="Battlefield")          # round 3
        s.at(7).move(50, "Battlefield", "Command")                          # it died
        s.at(9).cast(50, frm="Command", to="Battlefield")
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["commander"], [{"Ghoulcaller Gisa": [1, 1, 2, 3]}, {}])
        self.assertNotIn("Ghoulcaller Gisa", r.cards["rows"][0])
        self.assertEqual(r.cards["rows"][0]["Forest"], [1, 1, 3, 3, 0, 1 + 2 + 3, 0, 0, 1, 1])

    def test_a_commander_from_the_hand_still_counts_as_a_commander_cast(self):
        s = Script(commanders={1: {50: "Ghoulcaller Gisa"}})
        s.keep([3], [21])
        s.at(1).land(3)
        s.at(3).move(50, "Command", "Hand").cast(50, to="Battlefield")
        r = read(s.finish(winner=2))
        self.assertEqual(r.cards["commander"][0], {"Ghoulcaller Gisa": [1, 0, 1, 2]})
        self.assertNotIn("Ghoulcaller Gisa", r.cards["rows"][0])

    def test_tokens_and_other_ids_are_left_out(self):
        s = plain_game()
        s.move(900, "-", "Battlefield", "Saproling Token").move(901, "-", "Command", "Bolt's Effect")
        s.move(900, "Battlefield", "Stack", "Saproling Token")
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0))
        self.assertNotIn("Saproling Token", r.cards["rows"][0])

    def test_logged_names_map_to_the_list_names(self):
        names = {forge.norm("Lim-Dûl's Vault"): "Lim-Dûl's Vault"}
        deck = {**GREEN, 5: "Lim-Dul's Vault"}
        s = Script(decks={1: deck, 2: RED}).keep([3, 5], [21])
        s.at(1).land(3).cast(5)
        r = read(s.finish(winner=1), names=[names, {}])
        self.assertEqual(r.cards["rows"][0]["Lim-Dûl's Vault"], [1, 1, 1, 1, 0, 1, 0, 0, 1, 1])

    def test_a_timeout_is_nobodys_win(self):
        r = read(plain_game().finish(timeout=True))
        self.assertEqual(r.games[0]["r"], "timeout")
        self.assertEqual((r.cards["games"], r.cards["wins"], r.cards["first"]), (1, [0, 0], [1, 0]))
        self.assertEqual(r.cards["rows"][0]["Llanowar Elves"][:2], [1, 0])

    def test_games_add_up(self):
        r = read(plain_game().finish(winner=1), plain_game().finish(winner=2))
        c = r.cards
        self.assertEqual((c["games"], c["wins"], c["first"]), (2, [1, 1], [2, 0]))
        self.assertEqual(c["rows"][0]["Llanowar Elves"], [2, 1, 4, 4, 0, 6, 0, 0, 2, 1])
        self.assertEqual(c["rows"][1]["Mountain"], [2, 1, 6, 2, 4, 2, 0, 0, 2, 1])

    def test_round_of(self):
        self.assertEqual([cardlog.round_of(t) for t in (1, 2, 3, 4, 13)], [1, 1, 2, 2, 7])


# ============================================================ failed casts

class FailedCastTests(unittest.TestCase):
    """A cast Forge's AI began and couldn't finish ("[Couldn't add to stack, failed to
    target]"): the card moved to the Stack and stays there, and it isn't a cast."""

    def test_a_failed_cast_alone_is_drawn_and_neither_used_nor_stuck(self):
        s = Script().keep([3, 5], [21])
        s.at(1).land(3)
        s.at(3).fail(5)
        r = read(s.finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [1, 0, 1, 0, 0, 0, 0, 0, 1, 0])
        self.assertEqual(r.casts[0], {})                # nor is it among LogReader's casts

    def test_failed_then_cast_later_counts_the_later_cast(self):
        # Forge 2.0.15 leaves the card on the Stack; should it come back to the hand, the
        # cast that goes through is its first use
        s = Script().keep([3, 5], [21])
        s.at(1).land(3)
        s.at(3).fail(5)
        s.at(4).move(5, "Stack", "Hand")
        s.at(5).cast(5)                                 # round 3
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [1, 1, 1, 1, 0, 3, 0, 0, 1, 1])

    def test_a_failed_cast_after_a_real_one_keeps_it(self):
        s = Script().keep([3, 5], [21])
        s.at(1).land(3)
        s.at(3).cast(5)                                 # round 2, to the graveyard
        s.at(4).move(5, "Graveyard", "Hand")            # returned
        s.at(5).fail(5)
        r = read(s.finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [1, 0, 1, 1, 0, 2, 0, 0, 1, 0])

    def test_failed_in_one_game_and_cast_in_another(self):
        failed = Script().keep([3, 5], [21])
        failed.at(1).land(3)
        failed.at(3).fail(5)
        cast = Script().keep([3, 5], [21])
        cast.at(1).land(3).cast(5)                      # round 1
        r = read(failed.finish(winner=2), cast.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (2, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [2, 1, 2, 1, 0, 1, 0, 0, 2, 1])
        r = read(cast.lines, failed.lines)              # the other way round
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [2, 1, 2, 1, 0, 1, 0, 0, 2, 1])

    def test_a_failed_line_after_the_cast_line_takes_nothing_back(self):
        # e.g. a trigger of the spell on the Stack that can't target: its cast went through
        s = Script().keep([3, 5], [21])
        s.at(1).land(3)
        s.at(3).move(5, "Hand", "Stack")
        s.lines += ["Add To Stack: Ai(1)-x cast Giant Growth", "Add To Stack: Giant Growth (5) - " + FAILED]
        s.move(5, "Stack", "Graveyard")
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["rows"][0]["Giant Growth"], [1, 1, 1, 1, 0, 2, 0, 0, 1, 1])

    def test_a_failed_cast_from_another_zone_or_the_command_zone(self):
        s = Script(commanders={1: {50: "Ghoulcaller Gisa"}}).keep([3], [21])
        s.at(1).land(3)
        s.at(3).move(6, "Library", "Graveyard").fail(6, frm="Graveyard")    # not an other cast
        s.at(5).fail(50, frm="Command")                                    # not the commander's cast
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertNotIn("Murderous Rider", r.cards["rows"][0])
        self.assertEqual(r.cards["commander"], [{}, {}])
        s = Script(commanders={1: {50: "Ghoulcaller Gisa"}}).keep([3, 4], [21])
        s.at(1).land(3)
        s.at(3).land(4)
        s.at(5).cast(50, frm="Command", to="Battlefield")                  # round 3
        s.at(7).move(50, "Battlefield", "Command")                          # it died
        s.at(9).fail(50, frm="Command")
        r = read(s.finish(winner=1))
        self.assertEqual(r.cards["commander"], [{"Ghoulcaller Gisa": [1, 1, 1, 3]}, {}])

    def test_only_forges_game_log_line_is_a_failed_cast(self):
        line = ("Add To Stack: Felling Blow (11) - [Couldn't add to stack, failed to target] - "
                "Put a +1/+1 counter on target creature you control.")
        self.assertEqual(logreader.RE_NOT_CAST.match(line)[1], "11")
        self.assertIsNone(logreader.RE_CAST.match(line))
        # Forge's copy on its error stream, printed while the game is played
        self.assertIsNone(logreader.RE_NOT_CAST.match(line[len("Add To Stack: "):] + "[[Druid (51)], []]"))
        self.assertIsNone(logreader.RE_NOT_CAST.match(
            "Add To Stack: Ai(1)-x cast Felling Blow targeting [Druid of the Spade (51)] [Vampire Nighthawk (89)]"))


# ============================================================ the checks

class CheckTests(unittest.TestCase):

    def assertDropped(self, lines, reason):
        r = read(lines)
        self.assertEqual(len(r.games), 1)
        self.assertEqual((r.cards["games"], r.cards["bad"]), (0, 1))
        self.assertEqual((r.cards["rows"], r.cards["commander"], r.cards["wins"]), ([{}, {}], [{}, {}], [0, 0]))
        self.assertEqual(len(r.card_problems), 1)
        self.assertIn(reason, r.card_problems[0][1])
        return r

    def test_a_game_without_the_log_line(self):
        s = plain_game()
        s.lines.remove(dl("log", 1))
        self.assertDropped(s.finish(), "no DL|log")

    def test_an_unknown_version(self):
        s = plain_game()
        s.lines[0] = dl("log", 2)
        self.assertDropped(s.finish(), "version 2")

    def test_the_log_line_comes_first(self):
        s = plain_game()
        s.lines.append(dl("log", 1))
        self.assertDropped(s.finish(), "first")

    def test_an_error_line(self):
        s = plain_game()
        lines = s.finish()
        lines.insert(-1, dl("error", "end-of-game snapshot failed: java.lang.IllegalStateException: x"))
        self.assertDropped(lines, "snapshot failed")

    def test_every_seat_needs_every_list(self):
        for drop, reason in (("DL|deck|2|", "no DL|deck for seat 2"),
                             ("DL|hand|1|start|1|", "no start hand for seat 1"),
                             ("DL|hand|4|end|2|", "no end hand for seat 2"),
                             ("DL|library|4|end|1|", "no end library size for seat 1")):
            with self.subTest(drop=drop):
                lines = [line for line in plain_game().finish() if not line.startswith(cardlog.PRINTED + drop)]
                self.assertDropped(lines, reason)

    def test_a_list_twice(self):
        lines = plain_game().finish()
        lines.insert(-1, dl("library", 4, "end", 1, 3))
        self.assertDropped(lines, "two end library sizes")

    def test_a_third_seat(self):
        lines = plain_game().finish()
        lines.insert(3, dl("deck", 3, "99=Forest"))
        self.assertDropped(lines, "unreadable")

    def test_the_end_hand_must_be_what_the_moves_leave(self):
        self.assertDropped(plain_game().finish(end_hand={1: [5, 7]}), "seat 1's end hand")
        self.assertDropped(plain_game().finish(end_hand={2: []}), "seat 2's end hand")

    def test_the_library_size_must_be_what_the_moves_leave(self):
        self.assertDropped(plain_game().finish(library={2: 3}), "seat 2's library ends with 3 cards")

    def test_the_kept_hand_must_be_forges(self):
        s = Script().keep([1, 2, 3, 5], [21, 23, 24], kept={1: 7})
        s.at(1).land(3)
        self.assertDropped(s.finish(), "seat 1 kept 7 cards, its start hand has 4")

    def test_the_kept_hand_counts_what_opening_hand_actions_moved(self):
        deck = {**GREEN, 11: "Leyline of the Void"}
        s = Script(decks={1: deck, 2: RED}).keep([3, 11, 5], [21], kept={1: 4}, opening=[(11, "Battlefield")])
        self.assertDropped(s.at(1).land(3).finish(),
                           "seat 1 kept 4 cards, its start hand has 2 and 1 left the hand before turn 1")

    def test_a_move_out_of_the_hand_before_the_keep_is_a_mulligans(self):
        # Seat 2 puts a card back (a London mulligan) after seat 1's kept line, before its own.
        s = Script()
        for card_id in (3, 5, 21, 22, 23):
            s.move(card_id, "Library", "Hand")
        s.lines.append("Mulligan: Ai(1)-x has kept a hand of 2 cards")
        s.move(23, "Hand", "Library")
        s.lines.append("Mulligan: Ai(2)-x has kept a hand of 2 cards")
        for seat in (1, 2):
            s.lines.append(dl("hand", 1, "start", seat, listed(s.ids(seat, "Hand"), s.names)))
        r = read(s.at(1).land(3).finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertNotIn("Lightning Bolt", r.cards["rows"][1])

    def test_without_forges_mulligan_line_an_opening_hand_action_isnt_counted(self):
        deck = {**GREEN, 11: "Leyline of the Void"}
        s = Script(decks={1: deck, 2: RED}).keep([3, 11], [21], opening=[(11, "Battlefield")])
        s.lines = [line for line in s.lines if not line.startswith("Mulligan:")]
        r = read(s.at(1).land(3).finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        self.assertNotIn("Leyline of the Void", r.cards["rows"][0])

    def test_a_restarted_game(self):
        # Karn Liberated restarts the game: every card goes back to the library, the hands
        # are drawn and kept again, and turn 1 begins again, with a second start hand.
        s = plain_game()
        for zone in ("Hand", "Battlefield", "Graveyard"):
            for card_id in s.ids(1, zone):
                s.move(card_id, zone, "Library")
        s.turn = 0
        s.move(7, "Library", "Hand")
        s.lines.append(dl("hand", 1, "start", 1, listed([7], s.names)))
        self.assertDropped(s.finish(), "the game was restarted (as Karn Liberated does): seat 1 has a second start hand")
        # A second kept line says so first, when the game stops before turn 1 begins again.
        s = plain_game()
        s.lines.append("Mulligan: Ai(2)-x has kept a hand of 7 cards")
        self.assertDropped(s.finish(), "the game was restarted (as Karn Liberated does): seat 2 kept a second hand")

    def test_without_forges_mulligan_line_the_hand_isnt_checked(self):
        s = Script().keep([1, 2, 3, 5], [21, 23, 24])
        s.lines = [line for line in s.lines if not line.startswith("Mulligan:")]
        r = read(s.at(1).land(3).finish())
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0))

    def test_every_land_line_needs_its_move(self):
        s = Script().keep([3, 4], [21])
        s.at(1).land(3)
        s.lines.append("Land: Ai(1)-x played Forest (4)")      # no move of 4 to the Battlefield
        self.assertDropped(s.finish(), "no move to the Battlefield for the land played as 4 on turn 1")

    def test_the_land_move_must_be_on_that_turn(self):
        s = Script().keep([3, 4], [21])
        s.at(1).move(3, "Hand", "Battlefield")
        s.at(3).lines.append("Land: Ai(1)-x played Forest (3)")
        self.assertDropped(s.finish(), "on turn 3")

    def test_a_land_played_from_another_zone(self):
        # Forge logs a land played from exile (impulse draw), the top of the library
        # (Courser of Kruphix) or the graveyard (Crucible of Worlds) with the same Land line.
        s = Script().keep([3, 5], [21])
        s.at(1).land(3)
        s.move(3, "Battlefield", "Graveyard")                   # sacrificed
        s.at(3).move(4, "Library", "Exile").land(4, frm="Exile")
        s.at(5).land(9, frm="Library")
        s.at(7).land(3, frm="Graveyard")
        r = read(s.finish(winner=1))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        # Only Forest 3 was drawn (kept), and it was used once, on turn 1: 4 and 9 never
        # reached the hand, and a land played from elsewhere isn't a use.
        self.assertEqual(r.cards["rows"][0]["Forest"], [1, 1, 1, 1, 0, 1, 0, 0, 1, 1])

    def test_moves_after_the_end_lines_arent_replayed(self):
        # A game stopped by the clock: its game thread can go on moving cards after the
        # end-of-game snapshot, and those lines come after the snapshot's.
        lines = plain_game().finish(timeout=True)
        lines[-1:-1] = [dl("zone", 4, 2, "MAIN1", "Library", "Hand", 2, 27, "Swamp"),
                        dl("zone", 4, 2, "MAIN1", "Hand", "Battlefield", 2, 22, "Mountain"),
                        "Land: Ai(2)-x played Mountain (22)"]
        r = read(lines)
        self.assertEqual(r.games[0]["r"], "timeout")
        self.assertEqual((r.cards["games"], r.cards["bad"]), (1, 0), r.card_problems)
        rows = r.cards["rows"][1]
        self.assertNotIn("Swamp", rows)                                 # drawn after the game
        self.assertEqual(rows["Mountain"], [1, 0, 3, 1, 2, 1, 0, 0, 1, 0])    # 22 held at the end, not used

    def test_a_move_among_the_end_lines_drops_the_game(self):
        # Swamp 27 drawn after the end hands were written and before the libraries were.
        lines = plain_game().finish(timeout=True, library={2: 4})
        at = next(i for i, line in enumerate(lines) if line.startswith(cardlog.PREFIX + "library|"))
        lines.insert(at, dl("zone", 4, 2, "MAIN1", "Library", "Hand", 2, 27, "Swamp"))
        self.assertDropped(lines, "seat 2's library ends with 4 cards, its moves leave 5")

    def test_an_unreadable_line(self):
        s = plain_game()
        s.lines.append(cardlog.PREFIX + "zone|x|1|MAIN1|Hand|Stack|1|5|Giant Growth")
        r = self.assertDropped(s.finish(), "unreadable")
        self.assertEqual(r.games[0]["r"], "win")             # the game itself still counts

    def test_a_bad_game_spoils_only_itself(self):
        r = read(plain_game().finish(library={1: 0}), plain_game().finish(winner=2))
        self.assertEqual((r.cards["games"], r.cards["bad"], r.cards["wins"]), (1, 1, [0, 1]))
        self.assertEqual(r.card_problems[0][0], 1)
        self.assertEqual(r.cards["rows"][0]["Llanowar Elves"], [1, 0, 2, 2, 0, 3, 0, 0, 1, 0])

    def test_a_game_with_no_card_log(self):
        r = test_forge.read_log("full-game-s7.log")
        r2 = read_file(test_forge.HERE / "full-game-s7.log")
        self.assertEqual((r2.cards["games"], r2.cards["bad"]), (0, 1))
        self.assertEqual(r2.card_problems, [(1, "no card log")])
        self.assertEqual((r2.games, r2.casts, r2.lands), (r.games, r.casts, r.lands))

    def test_a_bug_in_the_card_log_costs_only_the_card_data(self):
        def broken(*args):
            raise RuntimeError("boom")
        logged = []
        with mock.patch.object(cardlog, "add", broken), mock.patch.object(forge.common, "_log", logged.append):
            r = read(plain_game().finish())
        self.assertEqual((len(r.games), r.cards["games"], r.cards["bad"]), (1, 0, 1))
        self.assertIn("boom", logged[0])


# ============================================================ LogReader

class ReaderTests(unittest.TestCase):

    def test_a_real_game(self):
        # Seed 7 (cardlog-README.md): Gruul Ramp, deck 1, went first and won on turn 13.
        r = read_file(test_forge.HERE / "cardlog-s7.log")
        c = r.cards
        self.assertEqual(r.card_problems, [])
        self.assertEqual({k: c[k] for k in ("games", "bad", "wins", "first")},
                         {"games": 1, "bad": 0, "wins": [1, 0], "first": [1, 0]})
        gruul, izzet = c["rows"]
        # Gruul's 3rd own turn began on turn 5, Izzet's on turn 6: the cut-offs for in hand by turn 3.
        # Forests 33 (kept) and 35 (drawn turn 5) played on turns 1 and 7: rounds 1 + 4
        self.assertEqual(gruul["Forest"], [1, 1, 2, 2, 0, 5, 0, 0, 1, 1])
        # Rabid Gnaw 46 (kept) and 45 (drawn turn 9) cast on turns 9 and 11: rounds 5 + 6
        self.assertEqual(gruul["Rabid Gnaw"], [1, 1, 2, 2, 0, 11, 0, 0, 1, 1])
        # Fierce Empath fetched Terror of Mount Velus on turn 5 (Gruul's 3rd turn: in hand by it); never cast
        self.assertEqual(gruul["Terror of Mount Velus"], [1, 1, 1, 0, 1, 0, 0, 0, 1, 1])
        self.assertEqual(gruul["Aggressive Mammoth"], [1, 1, 1, 0, 1, 0, 0, 0, 1, 1])
        self.assertNotIn("Lathliss, Dragon Queen", gruul)        # never drawn
        # Firespitter Whelp: 121 drawn turn 2 and cast turn 10; 120 drawn turn 6 and held
        self.assertEqual(izzet["Firespitter Whelp"], [1, 0, 2, 1, 1, 5, 0, 0, 1, 0])
        # Temple of Epiphany came with Preordain's draw on turn 8 (after turn 6), and was played that turn
        self.assertEqual(izzet["Temple of Epiphany"], [1, 0, 1, 1, 0, 4, 0, 0, 0, 0])
        self.assertEqual(izzet["Counterspell"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])
        self.assertNotIn("Scorching Dragonfire's Effect", izzet)  # an effect, not a card
        self.assertEqual(sum(v[2] for v in gruul.values()), 7 + 7)  # kept 7, drew 6, fetched 1
        self.assertEqual(sum(v[4] for v in gruul.values()), 3)

    def test_a_real_game_with_opening_hand_actions(self):
        # cardlog-README.md: seat 1 kept 7, then Forge put Leyline of the Void 5 and Gemstone
        # Caverns 52 onto the battlefield and exiled Dread Shade 48 at turn 0, so its start
        # hand has 4. Green went first; the Leyline list won on turn 14 (round 7).
        r = read_file(test_forge.HERE / "cardlog-opening-s2.log")
        c = r.cards
        self.assertEqual(r.card_problems, [])
        self.assertEqual({k: c[k] for k in ("games", "bad", "wins", "first")},
                         {"games": 1, "bad": 0, "wins": [1, 0], "first": [0, 1]})
        rows = c["rows"][0]
        # Leyline 5 put onto the battlefield (round 1); 6 drawn on turn 8 and held. The opening-hand
        # actions' cards were kept, so they were in hand by turn 3.
        self.assertEqual(rows["Leyline of the Void"], [1, 1, 2, 1, 1, 1, 0, 0, 1, 1])
        self.assertEqual(rows["Gemstone Caverns"], [1, 1, 1, 1, 0, 1, 0, 0, 1, 1])
        self.assertEqual(rows["Dread Shade"], [1, 1, 1, 0, 0, 0, 0, 0, 1, 1])       # exiled: drawn, not used
        # Swamps 28, 33, 27 and 34 played on turns 2, 4, 6 and 14: rounds 1 + 2 + 3 + 7
        self.assertEqual(rows["Swamp"], [1, 1, 4, 4, 0, 13, 0, 0, 1, 1])
        self.assertEqual(sum(v[2] for v in rows.values()), 7 + 7)          # kept 7, drew 7

    def test_a_real_game_with_a_failed_cast(self):
        # cardlog-README.md: Selesnya Rabbits (deck 1) drew Felling Blow (11) on turn 8. On
        # turn 12 Forge's AI began casting it, couldn't target, and left it on the Stack.
        # Forge's copy of that line on its error stream comes before the game's lines.
        path = test_forge.HERE / "cardlog-failed-cast-s5.log"
        r = read_file(path)
        c = r.cards
        self.assertEqual(r.card_problems, [])
        self.assertEqual({k: c[k] for k in ("games", "bad", "wins", "first")},
                         {"games": 1, "bad": 0, "wins": [0, 1], "first": [0, 1]})
        rabbits = c["rows"][0]
        # drawn on turn 8, after Rabbits' 3rd own turn (turn 6: Rabbits drew second); not cast, not stuck
        self.assertEqual(rabbits["Felling Blow"], [1, 0, 1, 0, 0, 0, 0, 0, 0, 0])
        self.assertNotIn("Felling Blow", r.casts[0])
        # Burrowguard Mentor 27 (kept) and 26 (drawn turn 4) cast on turns 4 and 8: rounds 2 + 4
        self.assertEqual(rabbits["Burrowguard Mentor"], [1, 0, 2, 2, 0, 6, 0, 0, 1, 0])
        self.assertEqual(rabbits["Release the Dogs"], [1, 0, 1, 0, 1, 0, 0, 0, 1, 0])  # drawn turn 2, held
        self.assertEqual(sum(v[2] for v in rabbits.values()), 7 + 6)             # kept 7, drew 6
        self.assertEqual(sum(v[4] for v in rabbits.values()), 1)
        # read as a cast (version 1 records did), it was a use in round 6
        with mock.patch.object(cardlog.Game, "not_cast", lambda game, card_id: None):
            old = read_file(path)
        self.assertEqual(old.cards["rows"][0]["Felling Blow"], [1, 0, 1, 1, 0, 6, 0, 0, 0, 0])

    def test_a_real_game_from_the_other_side(self):
        r = read_file(test_forge.HERE / "cardlog-s7.log", deck1=1)
        self.assertEqual((r.cards["wins"], r.cards["first"]), ([0, 1], [0, 1]))
        self.assertEqual(r.cards["rows"][1]["Forest"], [1, 1, 2, 2, 0, 5, 0, 0, 1, 1])

    def test_without_the_card_log_the_dl_lines_change_nothing(self):
        on = read_file(test_forge.HERE / "cardlog-s7.log")
        off = read_file(test_forge.HERE / "cardlog-s7.log", card_log=False)
        self.assertIsNone(off.cards)
        self.assertEqual((off.games, off.casts, off.lands, off.unsupported, off.load_errors),
                         (on.games, on.casts, on.lands, on.unsupported, on.load_errors))
        self.assertIsNone(off.failure(1, 0))
        # and the same game read without any DL line is the same game
        plain = forge.LogReader()
        with open(test_forge.HERE / "cardlog-s7.log", encoding="utf-8") as f:
            for line in f:
                if not line.startswith(cardlog.PREFIX):
                    plain.feed(line)
        self.assertEqual((plain.games, plain.casts, plain.lands), (on.games, on.casts, on.lands))
        self.assertEqual(on.games[0]["r"], "win")

    def test_a_stopped_batch_keeps_the_games_it_finished(self):
        second = plain_game().finish(winner=2)
        r = read(plain_game().finish(winner=1), second[:len(second) // 2])
        r.close()
        r.feed(second[-1])
        self.assertEqual((len(r.games), r.cards["games"], r.cards["bad"]), (1, 1, 0))
        self.assertEqual(r.cards["wins"], [1, 0])

    def test_every_game_is_counted_once(self):
        r = read(plain_game().finish(), plain_game().finish(library={2: 9}), plain_game().finish(winner=2))
        self.assertEqual(r.cards["games"] + r.cards["bad"], len(r.games))

    def test_the_record_is_plain_json(self):
        import json
        r = read(plain_game().finish())
        self.assertEqual(json.loads(json.dumps(r.cards)), r.cards)
        for side in r.cards["rows"]:
            for numbers in side.values():
                self.assertEqual(len(numbers), len(cardlog.ROW_FIELDS))
                self.assertTrue(all(type(n) is int for n in numbers))


# ============================================================ the fake Forge

def dck(decklist, kind="constructed"):
    text, sha, _ = forge.lists._list_text(forge.lists._section_cards(test_forge.sections(decklist)), kind)
    return forge.lists._dck(text, sha)


class FakeForgeTests(unittest.TestCase):
    """fixtures/fake_forge.py --card-log, run as a process (as the runner tests run it)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        for name, decklist, kind in (("green", test_forge.GREEN, "constructed"), ("red", test_forge.RED, "constructed"),
                                     ("gisa", test_forge.GISA, "commander"),
                                     ("bolts", test_forge.MIRROR_GISA, "commander"),
                                     ("thin", "Deck\n1 Forest\n7 Grizzly Bears\n", "constructed"),
                                     ("tiny", "Deck\n1 Forest\n4 Grizzly Bears\n", "constructed"),
                                     ("leyline", "Deck\n4 Leyline of the Void\n8 Forest\n8 Grizzly Bears\n",
                                      "constructed"),
                                     ("alone", "Commander\n1 Ghoulcaller Gisa\n", "commander")):
            (cls.tmp / f"{name}.dck").write_text(dck(decklist, kind), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def output(self, a="green", b="red", games=20, seed=3, fmt="Constructed", card_log=True, modes=""):
        argv = [sys.executable, str(test_forge.FAKE), "sim", "-D", str(self.tmp), "-d", f"{a}.dck", f"{b}.dck",
                "-n", str(games), "-s", str(seed), "-f", fmt, "-c", "120", "-a", "Default", "Default"]
        env = dict(os.environ, FAKE_FORGE=modes)
        env.pop("FAKE_FORGE_LOG", None)
        out = subprocess.run(argv + (["--card-log"] if card_log else []), capture_output=True, text=True,
                             encoding="utf-8", env=env, check=True).stdout
        return out.splitlines()

    def reader(self, lines, deck1=0, card_log=True):
        r = forge.LogReader(deck1, card_log=card_log)
        for line in lines:
            r.feed(line)
        return r

    def test_the_card_log_adds_lines_and_changes_none(self):
        for args in ({}, {"seed": 11, "games": 5, "modes": "timeout#2;exception#3;aitimeout#1"},
                     {"a": "gisa", "b": "bolts", "fmt": "Commander", "games": 6}):
            with self.subTest(**args):
                plain = self.output(card_log=False, **args)
                logged = self.output(**args)
                self.assertFalse(any("DL|" in line for line in plain))
                # DeckLabSim also prints its DLENGINE line before the header (plain Forge doesn't).
                self.assertEqual([line for line in logged if not line.startswith((cardlog.PREFIX, "DLENGINE|"))],
                                 plain)
                a, b = self.reader(plain, card_log=False), self.reader(logged)
                self.assertEqual((a.games, a.casts, a.lands), (b.games, b.casts, b.lands))

    def test_every_game_passes_the_checks(self):
        r = self.reader(self.output(games=40, seed=5), deck1=1)
        c = r.cards
        self.assertEqual(r.card_problems, [])
        self.assertEqual((c["games"], c["bad"]), (40, 0))
        self.assertEqual(c["wins"], [sum(g["w"] == side for g in r.games) for side in (0, 1)])
        self.assertEqual(c["first"], [sum(g["first"] == side for g in r.games) for side in (0, 1)])
        green = c["rows"][1]                    # deck1=1: green.dck is Forge's deck 1, side 1
        self.assertEqual(set(green) - {"Llanowar Elves", "Grizzly Bears", "Overrun", "Rabbit Response",
                                       "Fiery Annihilation", "Glorious Anthem", "Giant Growth", "Forest"}, set())
        for side in c["rows"]:
            self.assertGreaterEqual(sum(v[2] for v in side.values()), 7 * 40)    # 7 kept a game, at least
            for card, (dg, dw, copies, used, stuck, rounds, other, discarded, early, early_wins) in side.items():
                with self.subTest(card=card):
                    self.assertLessEqual(dw, dg)
                    self.assertLessEqual(dg, 40)
                    self.assertLessEqual(dg, copies)
                    self.assertLessEqual(used + discarded, copies)
                    self.assertLessEqual(stuck, copies)
                    self.assertGreaterEqual(rounds, used)
                    self.assertLessEqual(early, dg)
                    self.assertLessEqual(early_wins, min(early, dw))
        # The fake AI never casts Fiery Annihilation: drawn, never used.
        self.assertGreater(green["Fiery Annihilation"][0], 0)
        self.assertEqual(green["Fiery Annihilation"][3], 0)
        # A spell picked when no copy is in the hand or library is cast from the graveyard.
        self.assertGreater(sum(v[6] for v in green.values()), 0)

    def test_a_broken_card_log_drops_that_game(self):
        r = self.reader(self.output(games=4, seed=2, modes="badcardlog#2"))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (3, 1))
        self.assertEqual(r.card_problems[0][0], 2)
        self.assertIn("library", r.card_problems[0][1])

    def test_a_commander(self):
        r = self.reader(self.output("gisa", "bolts", games=6, seed=1, fmt="Commander"))
        c = r.cards
        self.assertEqual((c["games"], c["bad"]), (6, 0))
        lines = self.output("gisa", "bolts", games=6, seed=1, fmt="Commander")
        self.assertTrue(any(line.startswith(cardlog.PREFIX + "commander|1|") for line in lines))
        for side in (0, 1):
            self.assertNotIn("Ghoulcaller Gisa", c["rows"][side])
            cast_games, cast_wins, casts, first_round_sum = c["commander"][side]["Ghoulcaller Gisa"]
            self.assertLessEqual(cast_wins, cast_games)
            self.assertLessEqual(cast_games, 6)
            self.assertGreaterEqual(casts, cast_games)
            self.assertGreaterEqual(first_round_sum, cast_games)

    def test_more_land_plays_than_copies(self):
        # thin.dck has 1 Forest, and the fake plays a Forest on each of its first 5 turns:
        # the rest are logged as cards in neither list, which don't count.
        r = self.reader(self.output("thin", "red", games=3, seed=4))
        self.assertEqual((r.cards["games"], r.cards["bad"]), (3, 0), r.card_problems)
        forest = r.cards["rows"][0]["Forest"]
        self.assertLessEqual(forest[3], 3)

    def test_a_leyline_in_the_opening_hand(self):
        # The fake puts a kept Leyline onto the battlefield at turn 0, after the Mulligan
        # lines, as Forge's opening-hand actions do: the start hand is short of the kept 7.
        plain = self.output("leyline", "red", games=10, seed=8, card_log=False)
        logged = self.output("leyline", "red", games=10, seed=8)
        self.assertEqual([line for line in logged if not line.startswith((cardlog.PREFIX, "DLENGINE|"))], plain)
        opening = [line for line in logged if line.startswith(cardlog.PREFIX + "zone|0|-|-|Hand|Battlefield|1|")]
        self.assertGreater(len(opening), 0)
        r = self.reader(logged)
        self.assertEqual((r.cards["games"], r.cards["bad"]), (10, 0), r.card_problems)
        used = r.cards["rows"][0]["Leyline of the Void"][3]
        self.assertGreaterEqual(used, len(opening))         # each one put onto the battlefield, at least

    def test_a_list_shorter_than_an_opening_hand(self):
        # tiny.dck has 5 cards, all kept: with the card log, Forge's Mulligan line says 5
        # (without it, the fake's has always said 7), and every game counts.
        def mulligans(lines, seat):
            return {line.rsplit(" has ", 1)[1] for line in lines if line.startswith(f"Mulligan: Ai({seat})-")}

        plain = self.output("tiny", "red", games=10, seed=6, card_log=False)
        logged = self.output("tiny", "red", games=10, seed=6)
        self.assertEqual((mulligans(plain, 1), mulligans(logged, 1), mulligans(logged, 2)),
                         ({"kept a hand of 7 cards"}, {"kept a hand of 5 cards"}, {"kept a hand of 7 cards"}))
        self.assertEqual([line for line in logged if not line.startswith((cardlog.PREFIX, "Mulligan: ", "DLENGINE|"))],
                         [line for line in plain if not line.startswith("Mulligan: ")])
        r = self.reader(logged)
        self.assertEqual((r.cards["games"], r.cards["bad"]), (10, 0), r.card_problems)
        self.assertEqual(sum(v[2] for v in r.cards["rows"][0].values()), 5 * 10)    # each copy, once a game
        # A Commander list with nothing but its commander: an empty DL|deck, a hand of 0.
        lines = self.output("alone", "gisa", games=4, seed=2, fmt="Commander")
        self.assertIn(cardlog.PREFIX + "deck|1|", lines)
        r = self.reader(lines)
        self.assertEqual((r.cards["games"], r.cards["bad"]), (4, 0), r.card_problems)
        self.assertEqual(r.cards["rows"][0], {})
        self.assertIn("Ghoulcaller Gisa", r.cards["commander"][0])


if __name__ == "__main__":
    unittest.main()
