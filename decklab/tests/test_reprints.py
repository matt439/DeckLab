"""Reprint follow-ups use isolated, fictional release dates; no network or inventory.

The card objects are based on the existing trimmed Scryfall fixture. Every added
set/date is made up to exercise time boundaries, not a real announcement.
"""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

from decklab.lib import cards, reprints


FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 16)
NAME = "Llanowar Elves"
CHECKED = "2026-10-01"
DATA_STAMP = "2026-10-02T09:05:45+00:00"


class ReprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.objects = [json.loads(line) for line in (FIXTURES / "default_cards.jsonl").read_text(
            encoding="utf-8").splitlines() if line.strip()]
        self.template = next(obj for obj in self.objects if obj["name"] == NAME and obj["set"] == "fdn")
        self.old = self.printing("old", "2020-01-01", set_name="Old Fixture Set")
        self.loaded = mock.patch.object(cards, "_index", None)
        self.loaded.start()
        self.addCleanup(self.loaded.stop)

    def printing(self, set_code, released_at, **values):
        obj = copy.deepcopy(self.template)
        obj.update({"set": set_code, "set_name": f"Fixture {set_code.upper()}", "collector_number": "1",
                    "released_at": released_at, **values})
        return obj

    def load(self, *extra, objects=None, stamp=DATA_STAMP):
        path = self.folder / "cards.jsonl"
        path.write_text("\n".join(json.dumps(obj) for obj in (
            [self.old, *extra] if objects is None else objects)), encoding="utf-8")
        built = cards.build_index(path, FIXTURES / "oracle_tags.jsonl",
                                  {"default_cards": stamp}, log=lambda _: None)
        cards._index = cards._prepare(built)
        return built

    def describe(self, name=NAME, **kwargs):
        return reprints.for_card(name, today=TODAY, **kwargs)

    def test_upcoming_set_and_date_from_existing_index_without_network(self):
        future = self.printing("fut", "2026-11-20", set_name="Future Fixture Set")
        self.load(future)
        with mock.patch.object(cards, "_get_json", side_effect=AssertionError("network used")), \
                mock.patch.object(cards, "usd_to_aud", side_effect=AssertionError("price fetched")):
            answer = self.describe()
        self.assertTrue(answer["ready"])
        self.assertEqual(answer["upcoming"], [{"set": "fut", "set_name": "Future Fixture Set",
                                              "released_at": "2026-11-20",
                                              "source_url": "https://scryfall.com/card/fut/1"}])
        self.assertEqual(answer["data_date"], "2026-10-02")
        self.assertEqual(answer["as_of"], "2026-10-16")
        self.assertIn("other announcements may be missing", answer["coverage"])
        self.assertIn("lower prices or shop stock", " ".join(answer["notes"]))
        self.assertFalse(answer["price_check"]["offered"])

    def test_reprint_filter_uses_physical_cards_without_a_format_filter(self):
        digital = self.printing("dig", "2026-11-20", digital=True)
        arena = self.printing("arn", "2026-11-21", games=["arena", "mtgo"])
        oversized = self.printing("big", "2026-11-22", oversized=True)
        memorabilia = self.printing("mem", "2026-11-23", set_type="memorabilia")
        funny = self.printing("fun", "2026-11-24", set_type="funny", legalities={"commander": "banned"})
        self.load(digital, arena, oversized, memorabilia, funny)
        self.assertEqual([row["set"] for row in self.describe()["upcoming"]], ["fun"])

    def test_earlier_digital_or_memorabilia_does_not_prove_a_reprint(self):
        for old in (self.printing("dig", "2020-01-01", digital=True),
                    self.printing("mem", "2020-01-01", set_type="memorabilia")):
            with self.subTest(set=old["set"]):
                self.load(objects=[old, self.printing("fut", "2026-11-20")])
                self.assertEqual(self.describe()["upcoming"], [])

    def test_first_printing_variants_and_two_previews_are_not_existing_card_reprints(self):
        self.load(objects=[self.printing("new", "2026-11-20"),
                           self.printing("alt", "2026-11-20"),
                           self.printing("lat", "2026-12-01")])
        self.assertEqual(self.describe()["upcoming"], [])
        self.load(self.printing("alt", "2020-01-01"))
        self.assertEqual(self.describe(checked="2019-01-01", waiting=True)["released"], [])

    def test_deduplicates_alternate_arts_with_stable_source_link(self):
        self.load(self.printing("fut", "2026-11-20", collector_number="99"),
                  self.printing("fut", "2026-11-20", collector_number="2"),
                  self.printing("fut", "2026-11-20", collector_number="10"))
        answer = self.describe()
        self.assertEqual(len(answer["upcoming"]), 1)
        self.assertEqual(answer["upcoming"][0]["source_url"], "https://scryfall.com/card/fut/2")
        self.assertNotIn("collector_number", answer["upcoming"][0])

    def test_dates_sort_groups_not_input_order_and_preserve_distinct_set_dates(self):
        self.load(self.printing("bbb", "2026-12-01"), self.printing("aaa", "2026-11-20"),
                  self.printing("bbb", "2026-11-20", collector_number="2"))
        self.assertEqual([(row["set"], row["released_at"]) for row in self.describe()["upcoming"]],
                         [("aaa", "2026-11-20"), ("bbb", "2026-11-20"), ("bbb", "2026-12-01")])

    def test_release_day_offers_check_and_check_on_release_day_clears_offer(self):
        self.load(self.printing("now", "2026-10-16"))
        answer = self.describe(waiting=True, checked=CHECKED)
        self.assertEqual(answer["upcoming"], [])
        self.assertEqual([row["set"] for row in answer["released"]], ["now"])
        self.assertEqual(answer["price_check"], {"offered": True, "reason": "release_due", "checked": CHECKED})
        for checked in ("2026-10-16", "2026-10-17"):
            with self.subTest(checked=checked):
                same_day = self.describe(waiting=True, checked=checked)
                self.assertEqual(same_day["released"], [])
                # A genuinely future observation is unknown, not a fresh check.
                self.assertEqual(same_day["price_check"]["offered"], checked > TODAY.isoformat())

    def test_only_releases_after_saved_check_are_offered_without_changing_date(self):
        self.load(self.printing("ago", "2026-09-30"), self.printing("day", CHECKED),
                  self.printing("new", "2026-10-02"), self.printing("fut", "2026-10-17"))
        answer = self.describe(waiting=True, checked=CHECKED)
        self.assertEqual([row["set"] for row in answer["released"]], ["new"])
        self.assertEqual([row["set"] for row in answer["upcoming"]], ["fut"])
        self.assertEqual(answer["price_check"]["checked"], CHECKED)
        self.assertEqual(self.describe(checked=CHECKED)["released"], [])
        self.assertFalse(self.describe(checked=CHECKED)["price_check"]["offered"])

    def test_waiting_row_with_unknown_or_future_check_gets_manual_review_not_old_release_claim(self):
        self.load(self.printing("ago", "2024-01-01"))
        for checked in (None, "", "unknown", "2026-02-30", "20261001", " 2026-10-01 ", "2026-10-17"):
            with self.subTest(checked=checked):
                answer = self.describe(waiting=True, checked=checked)
                self.assertEqual(answer["released"], [])
                self.assertEqual(answer["price_check"],
                                 {"offered": True, "reason": "check_date_unknown", "checked": checked})
                self.assertGreater(len(answer["notes"]), 1)

    def test_known_check_without_a_new_release_does_not_offer_followup(self):
        self.load(self.printing("ago", "2026-09-30"))
        answer = self.describe(waiting=True, checked=CHECKED)
        self.assertEqual(answer["price_check"], {"offered": False, "reason": None, "checked": CHECKED})
        self.assertEqual(answer["released"], [])

    def test_cache_predating_release_keeps_its_date_and_offers_only_a_review(self):
        self.load(self.printing("now", "2026-10-16"), stamp="2026-10-01T00:00:00Z")
        answer = self.describe(waiting=True, checked="2026-09-30")
        self.assertEqual(answer["data_date"], "2026-10-01")
        self.assertEqual(answer["price_check"]["reason"], "release_due")
        self.assertIn("Listed release dates may change", " ".join(answer["notes"]))

    def test_bad_or_missing_release_dates_are_reported_and_never_invented(self):
        self.load(self.printing("nil", None), self.printing("bad", "2026-02-30"),
                  self.printing("par", "2026-11"), self.printing("fut", "2026-11-20"))
        answer = self.describe()
        self.assertEqual(answer["undated_printings"], 3)
        self.assertEqual([row["set"] for row in answer["upcoming"]], ["fut"])
        self.assertIn("3 paper printing(s) have no usable release date", " ".join(answer["notes"]))

    def test_unknown_cache_date_and_missing_set_name_stay_explicit(self):
        obj = self.printing("fut", "2026-11-20")
        obj.pop("set_name")
        self.load(obj, stamp="unknown")
        answer = self.describe()
        self.assertIsNone(answer["data_date"])
        self.assertEqual(answer["upcoming"][0]["set_name"], "FUT")
        self.assertIn("date of the cached Scryfall card data is unknown", " ".join(answer["notes"]))

    def test_unknown_name_and_unreadable_cache_do_not_claim_no_announcements(self):
        self.load()
        for side_effect in (None, FileNotFoundError("private/cache/path")):
            with self.subTest(error=side_effect), mock.patch.object(cards, "resolve", return_value=None,
                                                                    side_effect=side_effect):
                answer = self.describe(waiting=True)
                self.assertFalse(answer["ready"])
                self.assertEqual(answer["upcoming"], [])
                self.assertEqual(answer["released"], [])
                self.assertIsNone(answer["data_date"])
                self.assertTrue(answer["price_check"]["offered"])
                self.assertIn("unavailable", " ".join(answer["notes"]))
                self.assertNotIn("private/cache/path", " ".join(answer["notes"]))

    def test_waiting_known_check_with_unavailable_catalog_offers_manual_review_without_release_claim(self):
        self.load()
        with mock.patch.object(cards, "resolve", side_effect=FileNotFoundError()):
            answer = self.describe(waiting=True, checked=CHECKED)
            ordinary = self.describe(checked=CHECKED)
        self.assertFalse(answer["ready"])
        self.assertEqual(answer["released"], [])
        self.assertEqual(answer["price_check"], {"offered": True, "reason": "data_unavailable", "checked": CHECKED})
        self.assertFalse(ordinary["price_check"]["offered"])

    def test_multiface_front_name_and_shared_name_variant_follow_the_canonical_oracle(self):
        split = next(obj for obj in self.objects if obj["name"] == "Fire // Ice")
        split_future = dict(copy.deepcopy(split), set="fut", set_name="Future Fixture",
                            released_at="2026-11-20")
        poison = [obj for obj in self.objects if obj["name"] == "Pick Your Poison"]
        wrong = dict(copy.deepcopy(next(obj for obj in poison if obj["set"] == "cmb2")),
                     set="bad", released_at="2026-11-20")
        self.load(objects=[split, split_future, *poison, wrong])
        answer = self.describe("fire")
        self.assertEqual([row["set"] for row in answer["upcoming"]], ["fut"])
        query = parse_qs(urlparse(answer["source_url"]).query)
        self.assertEqual(query["q"], ['!"Fire // Ice" game:paper'])
        self.assertEqual(self.describe("Pick Your Poison")["upcoming"], [])

    def test_caps_groups_and_counts_overflow_independently(self):
        extra = [self.printing(f"f{n}", f"2026-11-{n:02d}") for n in range(1, 12)]
        extra += [self.printing(f"p{n}", f"2026-10-{n:02d}") for n in range(1, 13)]
        self.load(*extra)
        answer = self.describe(waiting=True, checked="2026-09-30")
        self.assertEqual(len(answer["upcoming"]), reprints.MAX_GROUPS)
        self.assertEqual(len(answer["released"]), reprints.MAX_GROUPS)
        self.assertEqual(answer["upcoming_more"], 3)
        self.assertEqual(answer["released_more"], 4)
        self.assertEqual([row["released_at"] for row in answer["upcoming"]],
                         [f"2026-11-{day:02d}" for day in range(1, 9)])
        self.assertEqual([row["released_at"] for row in answer["released"]],
                         [f"2026-10-{day:02d}" for day in range(12, 4, -1)])

    def test_source_links_are_fixed_host_and_escape_printing_paths_and_search_text(self):
        self.load(self.printing("fut", "2026-11-20", collector_number="1?x=#/"))
        answer = self.describe()
        self.assertEqual(answer["upcoming"][0]["source_url"], "https://scryfall.com/card/fut/1%3Fx%3D%23%2F")
        unknown = self.describe('X" OR * \\ Y')
        query = parse_qs(urlparse(unknown["source_url"]).query)
        self.assertEqual(query["q"], ['!"X\\" OR * \\\\ Y" game:paper'])
        self.assertEqual(urlparse(unknown["source_url"]).netloc, "scryfall.com")

    def test_pure_lookup_does_not_mutate_the_loaded_index(self):
        self.load(self.printing("fut", "2026-11-20"), self.printing("new", "2026-10-15"))
        before = copy.deepcopy(cards._get().data)
        self.describe(waiting=True, checked=CHECKED)
        self.assertEqual(cards._get().data, before)

    def test_today_is_explicit_and_rejects_partial_or_invalid_dates(self):
        self.load()
        self.assertEqual(reprints.for_card(NAME, today=TODAY.isoformat())["as_of"], TODAY.isoformat())
        for today in ("2026-11", "2026-02-30", 1):
            with self.subTest(today=today), self.assertRaisesRegex(ValueError, "calendar date"):
                reprints.for_card(NAME, today=today)


if __name__ == "__main__":
    unittest.main()
