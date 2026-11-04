"""Tokens are always optional on Build decks: nothing about them may stop a plan or its save."""
import json
from unittest import mock

from decklab.lib import cards, decks, inventory, tokens
from decklab.lib.api import assembly, assembly_completion as completion, assembly_tokens, settings
from decklab.lib.inventory import ops_decks
from decklab.tests.test_collection_assembly import FIXTURES, PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401
from decklab.tests.test_tokens import HEADER, REAL_TOKENS


PROFILES = [{"id": "matt", "name": "Matt", "role": "admin", "space": "home", "plays_as": "user"}]
LIST = "Deck\n1 Hornet Queen\n1 Court of Grace\n"
TABLE = "| Hornet Queen | 1 | 0 | 1 | | | |\n| Court of Grace | 1 | 0 | 1 | | | |\n"


class OptionalTokenCase(PreparationCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(cards, "_index", self.loaded),
                        mock.patch.object(settings, "_config_profiles", return_value=PROFILES)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cards_csv("collection.csv", ("Court of Grace", "cmr", "12", "nonfoil", 1),
                       ("Hornet Queen", "m15", "184", "nonfoil", 1))
        self.deck("a", "A", "building", LIST, table=TABLE)

    def plan(self):
        choices = [{"id": "casual/a", "version": "target"}]
        plan = assembly.assembly_preview(json.dumps({"profile": "matt", "decks": choices}))
        return plan, {"profile": "matt", "decks": choices, "confirmed": True,
                      "fingerprint": plan["completion"]["fingerprint"]}

    def assert_builds(self):
        """The plan can be marked built, and is: tokens or no tokens. Returns the plan and the deck."""
        plan, body = self.plan()
        self.assertTrue(plan["completion"]["can_mark_built"], plan["completion"]["reason"])
        answer = completion.mark_built(json.dumps(body))
        self.assertEqual([deck["id"] for deck in answer["built"]], ["casual/a"])
        deck = ops_decks.parsed_deck(inventory.current().deck("casual/a"))
        self.assertEqual(deck.status, "built")
        return plan, deck


class TokensNeverStopTheBuildTests(OptionalTokenCase):
    def test_tokens_owned_and_unticked_still_build_and_fill_the_token_cards_line(self):
        self.write("tokens.csv", REAL_TOKENS)
        plan, deck = self.assert_builds()
        self.assertTrue(plan["decks"][0]["tokens"]["needs"])
        self.assertTrue(decks.has_token_cards(deck))

    def test_a_token_with_no_card_at_all_still_builds(self):
        plan, deck = self.assert_builds()
        self.assertEqual({need["state"] for need in plan["decks"][0]["tokens"]["needs"]}, {"none"})
        self.assertFalse(decks.has_token_cards(deck))

    def test_an_unreadable_token_source_still_builds(self):
        for target in ("read", "incoming"):
            with self.subTest(target=target):
                self.deck("a", "A", "building", LIST, table=TABLE)
                with mock.patch.object(tokens, target, side_effect=OSError("gone")), \
                        mock.patch.object(assembly.common, "_log") as log:
                    plan, deck = self.assert_builds()
                self.assertEqual(plan["decks"][0]["tokens"], {"error": assembly.TOKEN_FAILED})
                self.assertEqual(plan["token_problems"], [assembly.TOKEN_SOURCE_FAILED])
                self.assertEqual((plan["tokens"], plan["token_plan"]), ([], []))
                self.assertFalse(decks.has_token_cards(deck))
                self.assertIn("gone", log.call_args.args[0])

    def test_tokens_that_cant_be_worked_out_or_written_still_build(self):
        self.write("tokens.csv", REAL_TOKENS)
        for name, patcher in (("deck_tokens", mock.patch.object(tokens, "deck_tokens", side_effect=KeyError("oops"))),
                              ("holds", mock.patch.object(tokens.reserve, "held_elsewhere", side_effect=KeyError("oops"))),
                              ("line", mock.patch.object(decks, "set_token_cards", side_effect=ValueError("oops")))):
            with self.subTest(name), patcher, mock.patch.object(assembly.common, "_log"):
                self.deck("a", "A", "building", LIST, table=TABLE)
                _, deck = self.assert_builds()
                self.assertFalse(decks.has_token_cards(deck))

    def test_a_token_list_that_cant_be_summarised_still_plans(self):
        self.write("tokens.csv", REAL_TOKENS)
        with mock.patch.object(assembly, "_token_plan", side_effect=ValueError("oops")), \
                mock.patch.object(assembly.common, "_log"):
            plan, _ = self.plan()
        self.assertTrue(plan["completion"]["can_mark_built"])
        self.assertEqual(plan["token_problems"], [assembly.TOKEN_SOURCE_FAILED])


class TokenPictureTests(OptionalTokenCase):
    def test_the_tile_a_need_shows_has_its_pictures_without_changing_its_tick(self):
        self.write("tokens.csv", REAL_TOKENS)
        plan, _ = self.plan()
        shown = [candidate for need in plan["decks"][0]["tokens"]["needs"]
                 for candidate in need["cards"][:1] + need["stand_ins"][:1]]
        self.assertTrue(shown)
        self.assertTrue(all({"img", "back_img", "example_art"} <= set(candidate) for candidate in shown))
        self.assertTrue(all(key in row for row in plan["tokens"] for key in ("img", "back_img", "example_art")))
        bare = assembly.token_packing_keys(
            tokens.deck_tokens(decks.load_deck("casual/a", "target"), tokens.read(), []), tokens.read().rows)
        self.assertEqual([need["packing_key"] for need in plan["decks"][0]["tokens"]["needs"]],
                         [need["packing_key"] for need in bare["needs"]])

    def test_a_row_with_no_printing_gets_example_art_and_says_so(self):
        self.write("tokens.csv", HEADER + "Insect,,,,,,1,1/1,,single-sided verified\n")
        row = tokens.read().rows[0]
        pictures = assembly_tokens.row_pictures(row)
        self.assertTrue(pictures["img"].startswith("/img/"))
        self.assertTrue(pictures["example_art"])

    def test_a_picture_that_cant_be_worked_out_is_left_out(self):
        with mock.patch.object(cards, "token_face", side_effect=RuntimeError("no index")):
            self.assertEqual(assembly_tokens.row_pictures({"front": "Elf", "back": "", "set": "", "front_collector_number": "",
                                                           "back_collector_number": "", "front_details": "", "back_details": ""}),
                             {"img": None, "back_img": None, "example_art": False})
