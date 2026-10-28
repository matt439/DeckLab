"""Frozen nightly needs, using supplied snapshots/indexes and disposable home fixtures."""
import copy
import unittest
from contextlib import ExitStack
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest import mock

from decklab.lib import buying_needs, cards, decks, inventory, shop_needs, shops, state
from decklab.lib.api import shop_missing_prices
from decklab.lib.inventory.model import Deck, Inventory
from decklab.tests.test_shopping_missing import RIDER, _Fixture

FRONT = "Front // Back"


def row(name, quantity=1):
    return {"name": name, "missing": quantity, "decks": []}


def snapshot():
    deck = Deck("home", "casual", "fixture", "A saved fixture")
    return Inventory("a" * 64, decks={deck.id: deck})


class ShopNeedsCaptureTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.index = SimpleNamespace(data={"cards": {name: {} for name in ("Alpha", "Beta", "Other", FRONT)}},
                                     by_key={"front": FRONT, "alpha": "Alpha", "beta": "Beta", "other": "Other"})
        self.get_index = self.stack.enter_context(mock.patch.object(cards, "_get", return_value=self.index))
        self.stack.enter_context(mock.patch.object(cards, "_index", self.index))
        self.stack.enter_context(mock.patch.object(shop_needs, "_summaries", return_value=([], [])))
        self.count = self.stack.enter_context(mock.patch.object(
            buying_needs, "count", return_value=buying_needs.CountedNeeds("counted", rows=[row("Other")])))
        self.stack.enter_context(mock.patch.object(shops, "_fetch", side_effect=AssertionError("no retailer")))
        self.original = snapshot()

    def plan(self, queue=(), source=None):
        return shop_needs.names(list(queue), self.original if source is None else source)

    def test_plan_is_frozen_and_keeps_exact_legacy_queue_spelling_and_order(self):
        queue = [{"name": " beta "}, {"name": "ALPHA"}, {"name": "Beta"}]
        before = copy.deepcopy(queue)
        plan = self.plan(queue)
        self.assertEqual(plan, shop_needs.NamesPlan(("beta", "ALPHA", "Other"), "ready"))
        self.assertEqual(queue, before)
        with self.assertRaises(FrozenInstanceError):
            plan.status = "partial"

    def test_front_only_queue_identity_prevents_an_extra_full_name_request(self):
        self.count.return_value.rows = [row(FRONT), row("Other")]
        plan = self.plan([{"name": "Front"}])
        self.assertEqual(plan.names, ("Front", "Other"))

    def test_multiple_legacy_front_and_full_spellings_remain_unchanged(self):
        self.count.return_value.rows = [row(FRONT), row("Alpha")]
        plan = self.plan([{"name": "Front"}, {"name": FRONT}, {"name": "FRONT"}])
        self.assertEqual(plan.names, ("Front", FRONT, "Alpha"))

    def test_unknown_or_token_queue_labels_do_not_block_independent_missing_names(self):
        self.assertEqual(self.plan([{"name": "Unknown token"}]).names, ("Unknown token", "Other"))
        self.index.by_key["unknown token"] = "Not a known playable card"
        self.assertEqual(self.plan([{"name": "Unknown token"}]).names, ("Unknown token", "Other"))

    def test_canonical_casefold_dedupes_new_names_without_changing_queue_evidence(self):
        self.count.return_value.rows = [row("Alpha"), row("Other"), row("Other", 2)]
        self.assertEqual(self.plan([{"name": "ALPHA"}]).names, ("ALPHA", "Other"))

    def test_one_captured_prepared_index_generation_is_required(self):
        self.plan()
        self.get_index.assert_called_once_with()
        self.count.side_effect = lambda *args, **kwargs: self.replace_index()
        self.assertEqual(self.plan([{"name": "Alpha"}]), shop_needs.NamesPlan(("Alpha",), "unavailable"))

    def replace_index(self):
        cards._index = object()
        return buying_needs.CountedNeeds("counted", rows=[row("Other")])

    def test_resolver_memoizes_names_in_its_prepared_maps(self):
        self.count.return_value.rows = [row(FRONT), row(FRONT)]
        with mock.patch.object(cards, "fold", wraps=cards.fold) as fold:
            self.assertEqual(self.plan([{"name": "Front"}]).names, ("Front",))
        self.assertEqual(fold.call_args_list, [mock.call("Front")])

    def test_missing_or_malformed_index_keeps_queue_and_fixed_notice(self):
        for value in (OSError("SECRET path"), SimpleNamespace(data={"cards": []}, by_key={}), object()):
            if isinstance(value, Exception):
                self.get_index.side_effect = value
            else:
                self.get_index.side_effect = None
                self.get_index.return_value = value
            with self.subTest(value=type(value).__name__):
                plan = self.plan([{"name": "Alpha"}])
                self.assertEqual(plan, shop_needs.NamesPlan(("Alpha",), "unavailable"))
                self.assertNotIn("SECRET", shop_needs.NOTICES[plan.status])

    def test_stale_preview_and_unsupported_snapshot_metadata_fail_before_index_or_count(self):
        values = [self.original.replace(stale="old"), self.original.replace(revision="a~preview"),
                  self.original.replace(backend="unknown"), self.original.replace(revision=""),
                  SimpleNamespace(revision="a", persisted=True, stale=None)]
        for value in values:
            with self.subTest(value=type(value).__name__):
                self.assertEqual(self.plan([{"name": "Alpha"}], value).status, "unavailable")
        self.get_index.assert_not_called()
        self.count.assert_not_called()

    def test_empty_home_needs_no_index_and_preserves_queue(self):
        self.assertEqual(self.plan([{"name": "Alpha"}], Inventory("empty")),
                         shop_needs.NamesPlan(("Alpha",), "ready"))
        self.get_index.assert_not_called()
        self.count.assert_not_called()

    def test_unavailable_counts_and_ordinary_failure_keep_exact_queue(self):
        for failure in (buying_needs.CountedNeeds("unavailable", message="SECRET"), RuntimeError("SECRET")):
            self.count.side_effect = failure if isinstance(failure, Exception) else None
            self.count.return_value = failure
            with self.subTest(failure=type(failure).__name__):
                self.assertEqual(self.plan([{"name": "Unknown"}]),
                                 shop_needs.NamesPlan(("Unknown",), "unavailable"))

    def test_per_deck_partial_result_retains_only_proven_additional_names(self):
        self.count.return_value.errors = [{"message": "SECRET deck details"}]
        plan = self.plan([{"name": "Alpha"}])
        self.assertEqual(plan, shop_needs.NamesPlan(("Alpha", "Other"), "partial"))
        self.assertNotIn("SECRET", shop_needs.NOTICES[plan.status])

    def test_malformed_quantities_or_names_never_become_requests(self):
        values = [row("Other", True), row("Other", 1.5), row("Other", float("inf")), row("Other", 0),
                  row("Other", -1), row("Unknown"), row("x" * 201), row("Bad\ud800"),
                  row(" Other"), row("Bad\nname"), row(None), [], {}]
        for value in values:
            self.count.return_value.rows = [value]
            with self.subTest(value=repr(value)):
                self.assertEqual(self.plan([{"name": "Alpha"}]),
                                 shop_needs.NamesPlan(("Alpha",), "unavailable"))

    def test_union_limit_never_truncates_queue_or_silently_adds_a_subset(self):
        with mock.patch.object(shops, "MAX_SNAPSHOT_NAMES", 2):
            self.assertEqual(self.plan([{"name": "Alpha"}, {"name": "Beta"}]),
                             shop_needs.NamesPlan(("Alpha", "Beta"), "over_limit"))
            self.assertEqual(self.plan([{"name": "Alpha"}, {"name": "Beta"}, {"name": "Unknown"}]),
                             shop_needs.NamesPlan(("Alpha", "Beta", "Unknown"), "over_limit"))

    def test_cancellation_is_not_swallowed_as_optional_data_failure(self):
        self.count.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.plan()

    def test_count_uses_nested_same_revision_home_projection_and_restores_callers_pin(self):
        member = Deck("user2", "casual", "private", "MUST NOT PARSE")
        original = self.original.replace(decks={**self.original.decks, member.id: member},
                                         deck_aliases={"casual/old": "casual/fixture"})
        seen = []
        def count(*args, **kwargs):
            projected = inventory.current()
            seen.append(projected)
            self.assertEqual(projected.revision, original.revision)
            self.assertEqual(list(projected.decks), ["casual/fixture"])
            self.assertEqual(projected.deck_aliases, {"casual/old": "casual/fixture"})
            self.assertEqual(projected.products, original.products)
            self.assertEqual(projected.orders, original.orders)
            self.assertEqual(projected.collections, original.collections)
            return buying_needs.CountedNeeds("counted", rows=[row("Other")])
        self.count.side_effect = count
        with inventory.pinned(original):
            self.assertEqual(self.plan([], original).names, ("Other",))
            self.assertIs(inventory.current(), original)
        self.assertIsNot(seen[0], original)

    def test_ambiguous_home_or_member_identity_invalidates_before_any_parser(self):
        bad = [self.original.replace(decks={"invalid": object()}),
               self.original.replace(decks={"casual/fixture": Deck("user2", "casual", "fixture", "secret")}),
               self.original.replace(decks={"user2/casual/a": Deck("home", "casual", "a", "secret")}),
               self.original.replace(decks={"user2/casual/a": object()})]
        for source in bad:
            with self.subTest(source=tuple(source.decks)):
                self.assertEqual(self.plan([{"name": "Alpha"}], source).status, "unavailable")
        self.count.assert_not_called()

    def test_home_alias_cannot_retarget_to_member_product_or_hide_a_current_identity(self):
        second = Deck("home", "casual", "other", "Another saved fixture")
        home = {**self.original.decks, second.id: second}
        for target in ("user2/casual/private", "product/precon/deck", None, "casual/other"):
            source = self.original.replace(decks=home, deck_aliases={"casual/fixture": target})
            with self.subTest(target=target):
                self.assertEqual(self.plan([{"name": "Alpha"}], source).status, "unavailable")
        self.count.assert_not_called()

    def test_fixed_callbacks_never_relay_error_content(self):
        def count(*args, **kwargs):
            self.assertEqual(kwargs["public"]("SECRET"), "A saved home count could not be confirmed.")
            self.assertIsNone(kwargs["log"]("SECRET"))
            return buying_needs.CountedNeeds("counted")
        self.count.side_effect = count
        self.assertEqual(self.plan([{"name": "Alpha"}]).status, "ready")

    def test_front_queue_key_still_matches_price_and_carried_time_and_missing_projection(self):
        self.count.return_value.rows = [row(FRONT)]
        plan = self.plan([{"name": "Front"}])
        at = "2026-10-01T03:00:00+10:00"
        listing = {"set": "abc", "number": "7", "finish": "nonfoil", "price": "1.00", "stock": 2,
                   "url": "https://www.mtgmate.com.au/cards/Front/ABC/7", "condition": "NM"}
        data = {"version": 1, "shop": shops.SHOP, "site": shops.SITE,
                "cards": {plan.names[0]: {"status": "ok", "at": at, "carried": True, "listings": [listing]}}}
        shown = shops.match({"name": "Front", "printing": "any"}, data)
        self.assertEqual((shown["price_aud"], shown["fetched_at"], shown["carried"]), ("1.00", at, True))
        rows = [{"name": FRONT}]
        shop_missing_prices.enrich(rows, data, lambda name: FRONT if name in ("Front", FRONT) else None)
        self.assertEqual((rows[0]["shop_snapshot"]["price_aud"], rows[0]["shop_snapshot"]["fetched_at"]), ("1.00", at))


class ForbiddenMemberParse(BaseException):
    pass


class ShopNeedsFixtureTests(_Fixture, unittest.TestCase):
    def parse_guard(self):
        real = decks.parse_deck
        def parse(data, *args, **kwargs):
            if kwargs.get("space") not in (None, "home") or b"User2 secret" in data:
                raise ForbiddenMemberParse("member deck reached a parser")
            return real(data, *args, **kwargs)
        return mock.patch.object(decks, "parse_deck", side_effect=parse)

    def test_real_target_math_includes_built_and_intact_reservations_and_incoming(self):
        original = self.backend.load()
        captured = []
        real_count = buying_needs.count
        def count(*args, **kwargs):
            out = real_count(*args, **kwargs)
            captured.append(out)
            return out
        with self.parse_guard(), mock.patch.object(buying_needs, "count", side_effect=count), \
                mock.patch.object(self.backend, "load", side_effect=AssertionError("must use captured snapshot")), \
                mock.patch.object(shops, "_fetch", side_effect=AssertionError("no retailer")), \
                mock.patch.object(cards, "update", side_effect=AssertionError("no index update")), \
                mock.patch.object(cards, "usd_to_aud", side_effect=AssertionError("no FX")):
            plan = shop_needs.names([{"name": "Opt"}], original)
        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.names[0], "Opt")
        self.assertEqual(set(plan.names[1:]), {"Llanowar Elves", "Elvish Mystic", RIDER, "Pick Your Poison"})
        self.assertEqual({row["name"]: row["missing"] for row in captured[0].rows},
                         {"Llanowar Elves": 6, "Elvish Mystic": 1, RIDER: 2, "Pick Your Poison": 1})
        self.assertNotIn("Black Lotus", plan.names)

    def test_malformed_built_home_holder_cannot_be_dropped_to_prove_other_needs(self):
        original = self.backend.load()
        holder = original.decks["casual/holding"].replace(space="user2")
        invalid = original.replace(decks={**original.decks, "casual/holding": holder})
        with self.parse_guard():
            self.assertEqual(shop_needs.names([{"name": "Opt"}], invalid),
                             shop_needs.NamesPlan(("Opt",), "unavailable"))

    def test_built_holder_alias_shadowing_another_home_record_fails_closed(self):
        original = self.backend.load()
        for target in ("casual/alpha", None, "user2/casual/private", "product/fdn-beginner-box/elves"):
            invalid = original.replace(deck_aliases={"casual/holding": target})
            with self.subTest(target=target), self.parse_guard():
                self.assertEqual(shop_needs.names([{"name": "Opt"}], invalid).status, "unavailable")

    def test_unreadable_home_holder_stays_in_projection_and_invalidates_pool_proof(self):
        original = self.backend.load()
        holder = original.decks["casual/holding"].replace(text=None, error="Fixture holder cannot be read")
        invalid = original.replace(decks={**original.decks, holder.id: holder})
        with self.parse_guard():
            self.assertEqual(shop_needs.names([{"name": "Opt"}], invalid),
                             shop_needs.NamesPlan(("Opt",), "unavailable"))

    def test_one_target_failure_keeps_other_real_proven_needs_with_partial_notice(self):
        original = self.backend.load()
        real = buying_needs.pool.owned_vs_needed
        def compare(deck_id, *args, **kwargs):
            if deck_id == "casual/beta":
                raise decks.DeckFileError("Fixture target unavailable")
            return real(deck_id, *args, **kwargs)
        with self.parse_guard(), mock.patch.object(buying_needs.pool, "owned_vs_needed", side_effect=compare):
            plan = shop_needs.names([{"name": "Opt"}], original)
        self.assertEqual(plan.status, "partial")
        self.assertEqual(set(plan.names), {"Opt", "Llanowar Elves", "Elvish Mystic", RIDER, "Pick Your Poison"})
        self.assertEqual(shop_needs.NOTICES[plan.status],
                         "Some saved home decks could not be counted; only confirmed missing names were added.")

    def test_public_member_switches_wishlists_and_profile_settings_are_never_consulted(self):
        original = self.backend.load()
        with self.parse_guard(), mock.patch.object(state, "store", side_effect=AssertionError("no personal state")):
            plan = shop_needs.names([{"name": "Opt"}], original)
        self.assertEqual(plan.status, "ready")
        self.assertNotIn("Black Lotus", plan.names)
