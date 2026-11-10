"""Readable chosen-listing facts and preference exclusions on Shopping/Prices/history."""
import unittest

from decklab.tests import test_shopping_ui as shopping_fixture
from decklab.tests.test_workspace_ui import NODE


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ShopQualityUiTests(unittest.TestCase):
    run_js = shopping_fixture.ShoppingInteractionTests.run_js

    def test_chosen_condition_language_and_skipped_cheaper_copy_are_visible_and_spoken(self):
        self.run_js("""
          const snap = {shop: 'MTGMate', status: 'in_stock', price_aud: '3.00', stock: 1, set: 'fdn', collector_number: '227',
            finish: 'nonfoil', fetched_at: '2026-11-11T12:00:00Z', condition: 'Lightly Played', language: 'Japanese', skipped_cheaper: true};
          const chosen = shopSnapshotOne(snap);
          assert(chosen.textContent.includes('Lightly Played, Japanese'));
          assert(chosen.textContent.includes('Cheaper copy skipped by household preference'));
          assert(shopSnapshotMarker({shop_snapshots: [snap]}).getAttribute('aria-label').includes('Lightly Played, Japanese'));
          const unknown = shopSnapshotOne({...snap, condition: null, language: null, skipped_cheaper: false});
          assert(unknown.textContent.includes('Condition unknown, language unknown'));
          assert(!unknown.textContent.includes('Near Mint')); assert(!unknown.textContent.includes('English'));
        """)

    def test_no_eligible_listing_and_history_day_explain_the_preference_without_claiming_a_price(self):
        self.run_js("""
          const preference = {minimum_condition: 'LP', english_only: true};
          const item = shopSnapshotOne({shop: 'MTGMate', status: 'not_eligible', listing_preferences: preference, price_aud: '0.50'});
          assert(item.textContent.includes('no listing meets'));
          assert(item.textContent.includes('Lightly Played or better, English only'));
          assert(!item.textContent.includes('A$0.50'));
          const history = shopHistoryShop({shop: 'MTGMate', days: [
            {on: '2026-11-11', listed: false, preference_excluded: true, price: null, lowest: false},
            {on: '2026-11-10', listed: true, in_stock: true, price: '3.00', stock: 1, set: 'fdn', number: '227',
              finish: 'nonfoil', condition: 'Near Mint', language: 'English', skipped_cheaper: true, lowest: true}]});
          assert(history.textContent.includes('No listing meets household preference'));
          assert(history.textContent.includes('Near Mint, English'));
          assert(history.textContent.includes('Cheaper copy skipped by household preference'));
        """)

    def test_basket_names_each_qualifying_variant_and_deck_unit_evidence_keeps_unknowns_explicit(self):
        self.run_js("""
          const listing = {set: 'fdn', collector_number: '227', finish: 'nonfoil', price_aud: '3.00', stock: 1, copies: 1,
            condition: 'Near Mint', language: 'English'};
          const item = shopBasketLine({name: 'Llanowar Elves', copies: 3, quantity: 3, stock: 3, status: 'in_stock',
            listing, more: [{...listing, copies: 2, price_aud: '4.00', condition: 'Lightly Played'}], skipped_cheaper: true},
            {shop: 'MTGMate', counts_stock: true});
          assert(item.textContent.includes('Near Mint, English')); assert(item.textContent.includes('Lightly Played, English'));
          assert(item.textContent.includes('across 2 listings')); assert(item.textContent.includes('Cheaper copy skipped'));
          const unit = {shop: 'MTGMate', scope: 'nonfoil', status: 'in_stock', fetched_at: '2026-11-11T12:00:00Z',
            price_aud: '3.00', stock: 1, set: 'fdn', collector_number: '227', finish: 'nonfoil', condition: null, language: null,
            url: 'https://www.mtgmate.com.au/cards/Llanowar_Elves/FDN/227', preference_applied: true};
          const facts = shopMissingSnapshotOf(unit, 'MTGMate');
          const node = shopMissingSnapshotOne(facts, false);
          assert(node.textContent.includes('meeting the household preference'));
          assert(node.textContent.includes('Condition unknown, language unknown'));
        """)
