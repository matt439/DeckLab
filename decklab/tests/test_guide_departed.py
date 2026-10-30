"""How to play names the cards its guide mentions that have left the deck (E2-S27, guide.departed_cards):
judged from the deck's own former revisions only, whole words, for the deck's own space only, and drawn
as a note on the page.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_guide_departed
"""
import json
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import common, deck_page, guard
from decklab.lib.api import guide as guide_module
from decklab.lib.inventory.model import DeckRevision
from decklab.tests.test_api import ApiTestCase
from decklab.tests.test_play_records import DECK, MixedFixture
from decklab.tests.test_web import NODE_RUNNER


WEB = Path(__file__).resolve().parents[2] / "decklab" / "web"

GUIDE = """
## Notes

### Game plan
Ramp with Llanowar Elves into Giant Growth. Optimal starts don't need Opt; never Shock yourself.

### Mulligans
Keep a hand with Fire or Sol Ring.
"""

# A former list: Giant Growth, Opt and Fire // Ice have since left; Shock was never in the deck.
FORMER = DECK.replace("4 Elvish Mystic\n", "4 Elvish Mystic\n2 Giant Growth\n1 Opt\n").replace(
    "2 Sol Ring (ECC) 57\n", "2 Sol Ring (ECC) 57\n1 Fire // Ice\n")


def revision(number, text, op="M", deck_id="casual/gruul-test"):
    return DeckRevision(deck_id=deck_id, revision=number, at=datetime(2026, 10, number, tzinfo=timezone.utc),
                        actor="matt", message="Save", op=op, text=text)


class DepartedTests(MixedFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.deckfile.write_text(DECK + GUIDE, encoding="utf-8")

    def revisions(self, *found, **kwargs):
        return self.box.stack.enter_context(mock.patch.object(
            inventory, "deck_revisions_with_text", return_value=list(found), **kwargs))

    def departed(self, deck_id="casual/gruul-test", viewer="matt"):
        with access.viewing(viewer):
            return deck_page.deck_view(deck_id)["guide"]["departed"]

    def test_cards_former_revisions_held_are_named_in_the_order_the_guide_names_them(self):
        reads = self.revisions(revision(3, DECK + GUIDE), revision(2, None, "D"), revision(1, FORMER))
        # Opt only in "Optimal" isn't named; Opt itself is. Fire // Ice by its front face.
        self.assertEqual(self.departed(), {"names": ["Giant Growth", "Opt", "Fire // Ice"], "count": 3})
        reads.assert_called_with("casual/gruul-test", guide_module.MAX_REVISIONS)
        with access.viewing("user1"):
            self.assertEqual(deck_page.deck_view("casual/gruul-test")["guide"]["departed"]["count"], 3)

    def test_a_common_word_never_in_the_deck_is_never_flagged(self):
        self.revisions(revision(1, FORMER))
        self.assertNotIn("Shock", self.departed()["names"])
        self.revisions(revision(1, DECK + GUIDE))
        self.assertEqual(self.departed(), {"names": [], "count": 0})

    def test_only_current_cards_named_and_whole_words_only(self):
        self.deckfile.write_text(DECK + "\n## Notes\n\n### Game plan\nCast Llanowar Elves, then Sol Ring.\n"
                                 "Opting out of Giant Growths.\n", encoding="utf-8")
        self.revisions(revision(1, FORMER))
        self.assertEqual(self.departed(), {"names": [], "count": 0})

    def test_a_departed_name_inside_a_current_card_s_longer_name_isn_t_flagged(self):
        # Forest became Snow-Covered Forest; Shock Troops replaced Shock. As the page's links, the longer
        # current name is read whole, so only Shock standing on its own counts.
        current = DECK.replace("52 Forest\n", "51 Snow-Covered Forest\n1 Shock Troops\n")
        self.deckfile.write_text(current + "\n## Notes\n\n### Game plan\nFetch a Snow-Covered Forest, then "
                                 "Shock Troops.\n", encoding="utf-8")
        self.revisions(revision(1, DECK.replace("52 Forest\n", "51 Forest\n1 Shock\n")))
        self.assertEqual(self.departed(), {"names": [], "count": 0})
        self.deckfile.write_text(current + "\n## Notes\n\n### Game plan\nShock Troops, not Shock; a Forest "
                                 "is a Snow-Covered Forest now.\n", encoding="utf-8")
        self.assertEqual(self.departed(), {"names": ["Shock", "Forest"], "count": 2})

    def test_a_card_still_in_the_play_now_list_hasn_t_left(self):
        owned = "\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n2 Giant Growth\n58 Forest\n```\n"
        self.deckfile.write_text(DECK + owned + GUIDE, encoding="utf-8")
        self.revisions(revision(1, FORMER))
        self.assertEqual(self.departed(), {"names": ["Opt", "Fire // Ice"], "count": 2})

    def test_the_names_sent_are_capped_and_counted(self):
        self.revisions(revision(1, FORMER))
        with mock.patch.object(guide_module, "MAX_DEPARTED", 1):
            self.assertEqual(self.departed(), {"names": ["Giant Growth"], "count": 3})

    def test_no_guide_or_unreadable_revisions_claim_nothing(self):
        self.deckfile.write_text(DECK, encoding="utf-8")
        reads = self.revisions(revision(1, FORMER))
        self.assertEqual(self.departed(), {"names": [], "count": 0})
        reads.assert_not_called()           # no guide text: no history read
        self.deckfile.write_text(DECK + GUIDE, encoding="utf-8")
        self.revisions(side_effect=RuntimeError)
        with mock.patch.object(common, "_log") as log:
            self.assertIsNone(self.departed())
        log.assert_called_once()
        self.assertIsNone(guide_module.departed_cards(None, None, "casual/gruul-test"))

    def test_a_member_s_own_deck_and_never_another_space_s(self):
        person = self.box.magic / "people/user2/decks/casual/r-elves.md"
        person.write_text(person.read_text(encoding="utf-8") + GUIDE, encoding="utf-8")
        reads = self.revisions(revision(1, FORMER.replace("- **Played by:** either\n", ""),
                                        deck_id="user2/casual/r-elves"))
        self.assertEqual(self.departed("user2/casual/r-elves", "user2")["names"], ["Giant Growth", "Opt", "Fire // Ice"])
        reads.reset_mock()
        # Home's deck made public: User2 reads its guide, but not what its history held.
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            with access.viewing("user2"):
                view = deck_page.deck_view("casual/gruul-test")
            self.assertTrue(view["guide"]["sections"])
            self.assertIsNone(view["guide"]["departed"])
        reads.assert_not_called()
        # Matt (an admin) doesn't see User2's deck at all.
        with access.viewing("matt"), self.assertRaises(common.ApiError) as raised:
            deck_page.deck_view("user2/casual/r-elves")
        self.assertEqual(raised.exception.status, 404)
        reads.assert_not_called()

    def test_products_and_pairings_have_no_departed_cards(self):
        self.assertIsNone(guide_module.departed_cards({"sections": []}, object(), "product/fdc-test-precon"))


@unittest.skipUnless(shutil.which("node"), "Node.js isn't installed")
class DepartedRenderingTests(unittest.TestCase):
    def render(self, departed):
        page = {"summary": {"id": "casual/test", "read_only": True}, "version": "target",
                "guide": {"changed_on": None, "departed": departed,
                          "sections": [{"title": "Game plan", "markdown": "Cast Giant Growth."}]}}
        inputs = [[str(WEB / name) for name in ("core.js", "editor.js", "editor-drafts.js", "deck-tools.js", "guide.js")],
                  [f"guideSection({json.dumps(page)})"]]
        done = subprocess.run([shutil.which("node"), "-e", NODE_RUNNER], input=json.dumps(inputs),
                              capture_output=True, text=True, encoding="utf-8", check=True)
        return json.loads(done.stdout)[0]

    def test_the_note_names_the_cards(self):
        rendered = self.render({"names": ["Giant Growth", "Opt"], "count": 2})
        self.assertIn("The guide mentions 2 cards no longer in the deck: Giant Growth, Opt.", rendered)
        self.assertIn("The guide mentions 1 card no longer in the deck: Opt.",
                      self.render({"names": ["Opt"], "count": 1}))
        self.assertIn("no longer in the deck: Opt, and 2 more.", self.render({"names": ["Opt"], "count": 3}))

    def test_no_note_without_departed_cards(self):
        for departed in (None, {"names": [], "count": 0}, {}):
            with self.subTest(departed=departed):
                self.assertNotIn("no longer in the deck", self.render(departed))


if __name__ == "__main__":
    unittest.main()
