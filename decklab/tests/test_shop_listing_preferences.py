"""Listing metadata is explicit and minimum/English constraints never guess missing facts."""
import unittest

from decklab.lib.shops import listing_preferences as preferences


class ListingPreferencesTests(unittest.TestCase):
    def test_known_and_legacy_language_facts_are_separate_and_unreported_means_unknown(self):
        for item, expected in (({"condition": "Lightly Played", "language": "JA"}, ("LP", "ja")),
                               ({"condition": "Lightly Played, JA"}, ("LP", "ja")),
                               ({"condition": "JA"}, (None, "ja")), ({"condition": "Near Mint"}, ("NM", None)),
                               ({"condition": "Near Mint, JA", "language": "EN"}, ("NM", None)),
                               ({"condition": "not recorded", "language": "unreported"}, (None, None)),
                               ({"condition": "", "language": "English"}, (None, "en"))):
            with self.subTest(item=item):
                facts = preferences.facts(item)
                self.assertEqual((facts["condition"], facts["language"]), expected)
        self.assertEqual(preferences.words({"condition": "LP, JA"}), {"condition": "Lightly Played", "language": "Japanese"})
        self.assertEqual(preferences.words({}), {"condition": None, "language": None})

    def test_neutral_preference_preserves_every_listing_including_unknowns(self):
        self.assertIsNone(preferences.normalize({"minimum_condition": None, "english_only": False}))
        items = [{}, {"condition": "Damaged", "language": "Japanese"}, {"condition": "NM", "language": "en"}]
        self.assertEqual(preferences.filter_listings(items, None), items)

    def test_minimum_and_language_constraints_are_independent_and_unknown_facts_fail_only_active_constraints(self):
        minimum = preferences.normalize({"minimum_condition": "LP", "english_only": False})
        english = preferences.normalize({"minimum_condition": None, "english_only": True})
        both = preferences.normalize({"minimum_condition": "LP", "english_only": True})
        self.assertTrue(preferences.fits({"condition": "NM", "language": "ja"}, minimum))
        self.assertTrue(preferences.fits({"condition": "LP"}, minimum))
        self.assertFalse(preferences.fits({"condition": "MP", "language": "en"}, minimum))
        self.assertFalse(preferences.fits({"language": "en"}, minimum))
        self.assertTrue(preferences.fits({"language": "English"}, english))
        self.assertFalse(preferences.fits({"condition": "Near Mint"}, english))
        self.assertTrue(preferences.fits({"condition": "LP", "language": "en"}, both))
        self.assertFalse(preferences.fits({"condition": "LP", "language": "ja"}, both))

    def test_cheaper_copy_advice_requires_a_cheaper_normal_choice_rejected_by_the_preference(self):
        selected = {"condition": "NM", "language": "en", "price": "2.00"}
        preference = preferences.normalize({"minimum_condition": "LP", "english_only": True})
        self.assertTrue(preferences.cheaper_skipped({"condition": "DMG", "language": "en", "price": "1.00"}, selected, preference))
        self.assertFalse(preferences.cheaper_skipped({**selected, "price": "1.00"}, selected, preference))
        self.assertFalse(preferences.cheaper_skipped({"price": "NaN"}, selected, preference))
        self.assertFalse(preferences.cheaper_skipped({"condition": "DMG", "price": "3.00"}, selected, preference))

    def test_preferences_reject_unknown_extra_or_unbounded_fields(self):
        for value in ([], {}, {"minimum_condition": "excellent", "english_only": True},
                      {"minimum_condition": "LP", "english_only": "true"},
                      {"minimum_condition": "LP", "english_only": True, "notes": "not a setting"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                preferences.normalize(value)
