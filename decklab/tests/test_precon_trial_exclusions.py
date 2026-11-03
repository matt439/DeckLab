"""Tests for E3-S39's exclusions: a trial deck (a precon the space doesn't own, decks/trial.py) is
kept out of other decks' field, the Rankings, Shopping's missing cards, the nightly shop
snapshot's names, arrival notices, Tables out of date (and the refresh and its blockers), the Game
log's lists, Build decks, usual opponents, the card viewer's decks, the wishlist's short decks and
"Where these go", while an ordinary idea deck made from a precon stays in each as before.

Runs in test_precon_trial's sandbox (test_precons' fixture MTGJSON lists, the sandbox's files as
the inventory; never the real database or Forge).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_precon_trial_exclusions
"""
from unittest import mock

from decklab.lib import arrivals, decks, inventory, pool, shop_needs
from decklab.lib.api import (assembly, card_decks, collection_filing, opponents, play_records, precon_coverage,
                             shopping, wishlist_short)
from decklab.lib.forge import engine, field, lists, rankings
from decklab.lib.inventory import refresh
from decklab.tests.test_precon_trial import TrialApiTestCase

MATT = {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"}


class ExclusionTestCase(TrialApiTestCase):

    def setUp(self):
        super().setUp()
        # Home's trial of the 60-card precon, and an ordinary idea deck started from a precon.
        self.trial = self.start("matt", "home")["id"]
        with self.as_("matt"):
            self.idea = self.call(precon_coverage.start_deck, "matt", space="home", file="BigElves_TST",
                                  title="Elves Idea")["id"]
        self.assertEqual((self.trial, self.idea), ("casual/big-elves", "casual/elves-idea"))

    def ids(self, items, key="id"):
        return {item[key] if isinstance(item, dict) else item for item in items}

    def assertOnlyIdea(self, found):
        found = set(found)
        self.assertIn(self.idea, found)
        self.assertNotIn(self.trial, found)


class ForgeTests(ExclusionTestCase):

    def test_never_in_another_decks_field(self):
        with mock.patch.object(lists, "_source", lambda deck_id, path=None: None):
            entries, _ = field._field("Constructed")
        self.assertOnlyIdea(self.ids(entries))

    def test_no_rankings_node(self):
        with mock.patch.object(lists, "_source", lambda deck_id, path=None: None),                 mock.patch.object(field, "_side_id", lambda entry, eng: entry["card_sha"]):
            rows, _ = rankings._catalog("Constructed", eng={"kind": engine.KIND_DECKLAB})
        self.assertOnlyIdea(self.ids(rows))

    def test_the_rankings_drop_games_of_a_trial_list(self):
        keep = rankings._without_trials(lambda result: True, {"t" * 64})
        self.assertFalse(keep({"sides": [{"card_sha": "t" * 64}, {"card_sha": "a" * 64}]}))
        self.assertTrue(keep({"sides": [{"card_sha": "b" * 64}, {"card_sha": "a" * 64}]}))
        self.assertIsNone(rankings._without_trials(None, set()))

    def test_a_hidden_trial_never_changes_the_rankings(self):
        # Another space's trial of a list home once played: home's games of that list stay.
        trials, trial_ids = set(), set()
        with mock.patch.object(lists, "_source", lambda deck_id, path=None: None), \
                mock.patch.object(field, "_side_id", lambda entry, eng: entry["card_sha"]):
            rankings._catalog("Constructed", lambda deck_id: deck_id != self.trial,
                              eng={"kind": engine.KIND_DECKLAB}, trials=trials, trial_ids=trial_ids)
            self.assertEqual((trials, trial_ids), (set(), set()))
            rankings._catalog("Constructed", eng={"kind": engine.KIND_DECKLAB}, trials=trials,
                              trial_ids=trial_ids)
        self.assertEqual(len(trials), 1)
        self.assertEqual(trial_ids, {self.trial})
        keep = rankings._without_trials(lambda result: True, set(), set(), set())
        self.assertTrue(keep({"sides": [{"card_sha": trials.pop()}, {"card_sha": "a" * 64}]}))

    def test_the_rankings_drop_a_trials_earlier_list_but_not_the_bought_deck(self):
        keep = rankings._without_trials(lambda result: True, set(), {self.trial}, {"b" * 64})
        other = {"id": "casual/gruul-test", "card_sha": "a" * 64}
        self.assertFalse(keep({"sides": [{"id": self.trial, "card_sha": "o" * 64}, other]}))
        self.assertFalse(keep({"sides": [{"card_sha": "o" * 64, "seen_as": [{"id": self.trial}]}, other]}))
        self.assertTrue(keep({"sides": [{"id": self.trial, "card_sha": "b" * 64}, other]}))     # a ranked list now
        self.assertTrue(keep({"sides": [{"id": "casual/elves-idea", "card_sha": "o" * 64}, other]}))


class InventoryTests(ExclusionTestCase):

    def test_no_shopping_missing_cards(self):
        given = []

        def gather(summaries, *args, **kwargs):
            given.extend(s["id"] for s in summaries)
            return {"rows": []}, []
        records = {"to_buy": [], "orders": [], "warnings": []}
        with self.as_("matt"), mock.patch.object(shopping.shopping_missing, "gather", gather),                 mock.patch.object(shopping.purchases, "overview", return_value=records):
            answer = shopping._overview()
        self.assertOnlyIdea(given)
        self.assertIn(self.trial, self.ids(answer["queue_decks"]))      # still a deck the queue can name

    def test_no_shop_snapshot_names(self):
        found, _ = shop_needs._summaries(inventory.current())
        self.assertOnlyIdea(self.ids(found))

    def test_no_arrival_notices(self):
        self.assertOnlyIdea(arrivals._home_decks())

    def test_no_tables_out_of_date_and_no_blockers(self):
        # Every deck's table goes out of date once the pool changes.
        with mock.patch.object(pool, "table_changes", return_value=["changed"]):
            self.assertOnlyIdea(self.ids(pool.stale_tables(only={"home"})))
        with mock.patch.object(refresh, "_list_problems", side_effect=lambda deck_id, deck: [
                refresh._Problem("no_table", ValueError(deck_id))]):
            self.assertOnlyIdea(self.ids(refresh.table_blockers(only={"home"})["decks"]))

    def test_an_inventory_change_never_refreshes_it(self):
        planned = []

        def deck_table(deck, supply, prices=False):
            planned.append(deck.slug)
            raise refresh.decks.DeckFileError("stop here")
        with mock.patch.object(refresh, "_supply", return_value=None), \
                mock.patch.object(refresh, "_list_problems", return_value=[]), \
                mock.patch.object(refresh.pool, "deck_table", deck_table), \
                mock.patch.object(refresh.decks, "_space_files", return_value=[
                    ("home", decks.deck_path("casual", slug)) for slug in ("big-elves", "elves-idea")]):
            with self.assertRaises(refresh.decks.DeckFileError):
                refresh.plan_texts(only={"home"})
            self.assertEqual(planned, ["elves-idea"])
            # ...but `deck tables <trial id>` (which push advises) works its table out.
            with self.assertRaises(refresh.decks.DeckFileError):
                refresh.plan_texts(only={"home"}, include={self.trial})
        self.assertEqual(planned, ["elves-idea", "big-elves"])

    def test_deck_tables_naming_a_trial_plans_it(self):
        from decklab.db import inv_decks
        seen = []

        def plan_texts(only=None, include=()):
            seen.append(set(include))
            return []
        with mock.patch.object(refresh, "plan_texts", plan_texts):
            self.assertEqual(inv_decks.plan_tables((self.trial,)), [])
            inv_decks.plan_tables()
        self.assertEqual(seen, [{self.trial}, set()])

    def test_not_a_deck_the_card_viewer_says_wants_it(self):
        p = pool.load_pool()
        wants = card_decks.deck_use(p, decks.list_decks(), ["Llanowar Elves"], "home",
                                    sees=lambda summary: True, records=True)["Llanowar Elves"]["wants"]
        self.assertOnlyIdea(self.ids(wants))

    def test_never_short_of_a_wished_card(self):
        found, _ = wishlist_short._own_decks("home", MATT)
        self.assertOnlyIdea(self.ids(found))

    def test_no_card_is_filed_into_it(self):
        snapshot = inventory.current()
        records = [snapshot.deck(deck_id) for deck_id in (self.trial, self.idea)]      # not the broken fixture
        after = mock.Mock(space_decks=lambda space: records)
        with self.as_("matt"):
            found = collection_filing._candidate_decks(after, "home", MATT, [0])
        self.assertOnlyIdea(self.ids(deck for deck, _ in found))


class PlayTests(ExclusionTestCase):

    def test_not_in_the_game_logs_lists(self):
        with self.as_("matt"):
            answer = play_records.play_overview()
        self.assertOnlyIdea(answer["decks"])
        self.assertNotIn(self.trial, {item["id"] for item in answer["lists"]})

    def test_not_a_deck_to_build(self):
        with self.as_("matt"):
            choices = assembly.assembly_view()["choices"]
        self.assertOnlyIdea(self.ids(choices))

    def test_not_a_usual_opponent(self):
        with self.as_("matt"):
            choices = opponents.opponents_view("casual/gruul-test")["choices"]
            self.assertOnlyIdea(self.ids(choices))
            # Its own page still answers, read-only: a trial isn't played at the table.
            view = opponents.opponents_view(self.trial)
            self.assertEqual((view["id"], view["editable"]), (self.trial, False))
            self.assertEqual(view["why_not"], opponents.NOT_AT_THE_TABLE)
            self.assertTrue(opponents.opponents_view(self.idea)["editable"])
            with self.assertRaises(opponents.ApiError) as raised:
                self.call(opponents.save_opponents, "matt", id=self.trial, sha256=view["sha256"],
                          opponents=["casual/gruul-test"])
        self.assertEqual(raised.exception.status, 400)


class StaysTests(ExclusionTestCase):

    def test_still_in_the_library_and_global_search(self):
        from decklab.lib.api import deck_page, global_search
        with self.as_("matt"):
            index = {d["id"]: d for d in deck_page.decks_index()["decks"]}
            self.assertEqual(index[self.trial]["trial"], "BigElves_TST")
            self.assertIsNone(index[self.idea]["trial"])
            found = global_search.search_view(q="big elves")
        self.assertIn(self.trial, str(found))

    def test_built_after_a_status_change_it_is_an_ordinary_deck(self):
        stored = inventory.current().deck(self.trial)
        deck = decks.parse_deck(stored.data, stored.slug, stored.kind)
        decks.set_status(deck, "building")
        self.assertIsNone(decks.trial_of(deck))
