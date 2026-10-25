"""Retained intended cards describe fixture builds without editing lists or queues."""
import contextlib
import json
from unittest import mock

from decklab.lib import access, api, decks, inventory, pool
from decklab.lib.api import assembly_intent, guard
from decklab.lib.decks import assembled, standins
from decklab.lib.inventory import ops_decks
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import setUpModule, tearDownModule  # noqa: F401


class AssemblyIntentTests(PreparationCase):
    def parsed(self, slug="a"):
        return ops_decks.parsed_deck(inventory.current().deck(f"casual/{slug}"))

    def install(self, sections, version="target", markers=None):
        deck = self.parsed()
        assembled.install(deck, version, decks.parse_decklist(sections))
        if markers is not None:
            standins.install_stand_ins(deck, version, markers)
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        return self.parsed()

    def project(self, **kwargs):
        return assembly_intent.project(self.parsed(), pool.load_pool(), **kwargs)

    def test_main_only_retains_owned_waiting_and_missing_sideboard_separately(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n20 Forest\n"
                  "Sideboard\n2 Elvish Mystic\n2 Pick Your Poison\n")
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 2))
        self.cards_csv("orders/arrival.csv", ("Pick Your Poison", "mkm", "170", "nonfoil", 1))
        self.install("Deck\n4 Llanowar Elves\n20 Forest\n")
        projected = self.project()
        self.assertEqual((projected["main_count"], projected["sideboard_count"],
                          projected["sideboard_intended"], projected["remaining_count"]), (24, 0, 4, 4))
        rows = {row["name"]: row for row in projected["remaining"]}
        self.assertEqual((rows["Elvish Mystic"]["remaining"], rows["Elvish Mystic"]["missing"],
                          rows["Elvish Mystic"]["on_the_way"]), (2, 0, 0))
        self.assertEqual((rows["Pick Your Poison"]["remaining"], rows["Pick Your Poison"]["missing"],
                          rows["Pick Your Poison"]["on_the_way"]), (2, 1, 1))
        self.assertTrue(projected["changed"])

    def test_play_now_build_retains_planned_replacements_without_rewriting_either_list(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n20 Forest\n",
                  owned="Deck\n4 Elvish Mystic\n20 Forest\n", built_version="owned-only")
        self.cards_csv("collection.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        before = self.install("Deck\n4 Elvish Mystic\n20 Forest\n", "owned")
        with mock.patch.object(self.inventory, "apply", wraps=self.inventory.apply) as apply:
            result = self.project()
        self.assertEqual((result["version"], result["intended_version"], result["main_count"]),
                         ("owned", "target", 24))
        self.assertEqual([(row["name"], row["remaining"], row["missing"]) for row in result["remaining"]],
                         [("Llanowar Elves", 4, 4)])
        self.assertEqual((self.parsed().target, self.parsed().owned, self.parsed().text),
                         (before.target, before.owned, before.text))
        apply.assert_not_called()

    def test_same_name_in_main_and_sideboard_consumes_availability_only_once(self):
        self.deck("a", "A", "built", "Deck\n2 Llanowar Elves\nSideboard\n2 Llanowar Elves\n")
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        self.cards_csv("orders/arrival.csv", ("Llanowar Elves", "m19", "314", "nonfoil", 1))
        self.install("Deck\n1 Llanowar Elves\n")
        result = self.project()
        self.assertEqual(sum(row["missing"] for row in result["remaining"]), 1)
        self.assertEqual(sum(row["on_the_way"] for row in result["remaining"]), 1)
        self.assertEqual(sum(row["remaining"] for row in result["remaining"]), 3)

    def test_installed_markers_keep_real_cards_in_intent_after_they_arrive(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n20 Forest\n")
        markers = [{"for": "Llanowar Elves", "using": None, "qty": 2}]
        self.install("Deck\n4 Llanowar Elves\n20 Forest\n", markers=markers)
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 2))
        result = self.project()
        row = result["remaining"][0]
        self.assertEqual((result["main_count"], row["assembled"], row["represented"],
                          row["remaining"], row["missing"]), (24, 2, 2, 2, 2))
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        row = self.project()["remaining"][0]
        self.assertEqual((row["remaining"], row["missing"], row["on_the_way"]), (2, 0, 0))

    def test_preview_uses_proposed_sections_instead_of_old_build(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\nSideboard\n2 Elvish Mystic\n")
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 2))
        self.install("Deck\n4 Llanowar Elves\nSideboard\n2 Elvish Mystic\n")
        result = self.project(sections=decks.parse_decklist("Deck\n4 Llanowar Elves\n"), standins=[])
        self.assertEqual((result["sideboard_count"], result["remaining_count"]), (0, 2))
        self.assertEqual(self.project()["remaining_count"], 0)

    def test_building_preview_keeps_chosen_list_intent_and_actual_page_has_no_build(self):
        self.deck("a", "A", "building", "Deck\n4 Llanowar Elves\n",
                  owned="Deck\n4 Elvish Mystic\nSideboard\n1 Pick Your Poison\n")
        self.assertIsNone(assembly_intent.project(self.parsed()))
        result = assembly_intent.project(self.parsed(), version="owned",
                                         sections=decks.parse_decklist("Deck\n4 Elvish Mystic\n"))
        self.assertEqual((result["version"], result["intended_version"], result["remaining_count"]),
                         ("owned", "owned", 1))
        self.assertEqual(result["remaining"][0]["name"], "Pick Your Poison")

    def test_unavailable_or_unconfirmed_inventory_never_claims_nothing_to_buy(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\nSideboard\n2 Elvish Mystic\n")
        self.install("Deck\n4 Llanowar Elves\n")
        for result in (None, {"warnings": ["Unconfirmed"], "unresolved": [], "rows": []},
                       {"warnings": [], "unresolved": [["Unknown", "inventory"]], "rows": []}):
            with self.subTest(result=result):
                row = assembly_intent.project(self.parsed(), result=result)["remaining"][0]
                self.assertIsNone(row["missing"])
                self.assertIsNone(row["on_the_way"])

    def test_list_edits_preserve_saved_physical_counts_and_show_changes(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\nSideboard\n2 Elvish Mystic\n")
        self.install("Deck\n4 Llanowar Elves\nSideboard\n2 Elvish Mystic\n")
        deck = self.parsed()
        deck.target = decks.parse_decklist("Deck\n4 Llanowar Elves\n")
        self.write("decks/casual/a.md", decks.render_deck_file(deck))
        result = self.project()
        self.assertEqual((result["main_count"], result["sideboard_count"], result["sideboard_intended"]), (4, 2, 0))
        self.assertEqual(result["remaining"], [])
        self.assertTrue(result["changed"])

    def test_legacy_build_uses_whole_built_list_without_inventing_a_snapshot(self):
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n",
                  owned="Deck\n4 Elvish Mystic\nSideboard\n2 Pick Your Poison\n", built_version="owned-only")
        result = self.project()
        self.assertEqual((result["version"], result["main_count"], result["sideboard_count"]), ("owned", 4, 2))
        self.assertIsNone(assembled.get(self.parsed()))
        json.dumps(result, allow_nan=False)


class AssemblyIntentPrivacyTests(PermissionTestCase):
    """The physical build goes only to who sees the deck's space's inventory, for a home deck made
    public (as E10-S28's switches will; until then it's seen only at home, E10-S30)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"}))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.box.magic / "decks/casual/assembled.md"
        self.path.write_text("# Assembled\n\n- **Format:** Casual 60-card, 1v1\n"
                             "- **Status:** built\n\n## Decklist\n\n```\nDeck\n4 Llanowar Elves\n"
                             "Sideboard\n2 Pick Your Poison\n```\n", encoding="utf-8")
        deck = ops_decks.parsed_deck(inventory.current().deck("casual/assembled"))
        assembled.install(deck, "target", decks.parse_decklist("Deck\n4 Llanowar Elves\n"))
        self.path.write_text(decks.render_deck_file(deck), encoding="utf-8")

    def test_only_inventory_viewers_receive_actual_build_and_retained_intent(self):
        with access.using({"profile": "stranger", "email": "", "remote": True}):
            # A login that isn't set up sees no deck at all, public or not.
            self.assertApiError(404, api.deck_view, "casual/assembled")
        for profile, remote, sees in (("matt", True, True), ("user1", True, True),
                                     ("user2", True, False),
                                     ("user1", False, True), ("user2", False, False), (None, False, True)):
            with self.subTest(profile=profile, remote=remote), contextlib.ExitStack() as stack:
                stack.enter_context(access.using({"profile": profile, "email": "", "remote": True}
                                                 if remote else None))
                if not remote:
                    stack.enter_context(access.viewing(profile))
                view = api.deck_view("casual/assembled", omit={"matchups"})
                summary = next(row for row in api.decks_index()["decks"] if row["id"] == "casual/assembled")
                self.assertEqual("assembled" in view, sees)
                self.assertEqual("assembled" in summary, sees)
                self.assertEqual(sum(row["qty"] for row in view["sections"]["Sideboard"]), 2)
                if sees:
                    self.assertEqual(view["assembled"], summary["assembled"])
                    self.assertEqual(view["assembled"]["sideboard_count"], 0)
                    self.assertEqual(view["assembled"]["remaining_count"], 2)

    def test_hidden_projection_is_not_computed_even_when_its_snapshot_is_broken(self):
        with access.using(None), access.viewing("user2"), \
                mock.patch.object(assembly_intent, "project", side_effect=AssertionError("private build read")):
            self.assertNotIn("assembled", api.deck_view("casual/assembled", omit={"matchups"}))
            summaries = api.decks_index()["decks"]
            self.assertNotIn("assembled", next(row for row in summaries if row["id"] == "casual/assembled"))
