"""Synthetic Commander log controls. Run with
python scripts/test_fixtures.py decklab.tests.test_forge_commander_observers
"""
import unittest

from decklab.lib.forge import LogReader
from decklab.tests.test_forge_cardlog import HEADER, Script, dl


class CommanderObserverTests(unittest.TestCase):
    def test_syr_elenora_in_both_seats(self):
        name = "Syr Elenora, the Discerning"
        for seat in (1, 2):
            for control, text_cast, id_cast in (
                ("complete", True, True),
                ("missing cast text", False, True),
                ("missing roster", True, False),
                ("missing zone moves", True, False),
                ("command zone only", False, False),
                ("failed cast", False, False),
            ):
                with self.subTest(seat=seat, control=control):
                    game = Script(commanders={seat: {50: name}}).keep([3], [21])
                    game.at(5 if seat == 1 else 6)
                    if control == "failed cast":
                        game.fail(50, frm="Command")
                    elif control != "command zone only":
                        game.cast(50, frm="Command", to="Battlefield")

                    # The subject is logical side zero across seat swaps.
                    reader = LogReader(deck1=seat - 1, card_log=True)
                    reader.feed(HEADER.replace("Constructed", "Commander"))
                    for line in game.finish(winner=seat):
                        if control == "missing cast text" and line.startswith("Add To Stack:"):
                            continue
                        if control == "missing roster" and line.startswith(dl("commander", seat) + "|"):
                            continue
                        if control == "missing zone moves" and line.startswith(dl("zone") + "|") and "|50|" in line:
                            continue
                        reader.feed(line)

                    self.assertEqual((reader.cards["games"], reader.cards["bad"]), (1, 0))
                    self.assertEqual(reader.casts, [{name: [1, 1]} if text_cast else {}, {}])
                    expected = {name: [1, 1, 1, 3]} if id_cast else {}
                    self.assertEqual(reader.cards["commander"], [expected, {}])
