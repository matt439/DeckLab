"""Library check dates belong only to readable ordinary home built-deck records.

All inventory, profiles and visibility switches are disposable File/Memory fixtures.
No PostgreSQL, real household records, Forge games or external calls are used.
"""
import copy
from unittest import mock

from decklab.lib import access, decks, inventory, state
from decklab.lib.api import deck_page
from decklab.lib.decks import boxcheck
from decklab.lib.inventory import files, ops_decks
from decklab.lib.state import Actor
from decklab.tests import household_config
from decklab.tests import test_box_check_api as support

setUpModule = support.setUpModule
tearDownModule = support.tearDownModule
ACTOR = Actor("matt", "Matt", source="web")
WHEN = "2026-10-26"


class LibraryBoxCheckApiTests(support.BoxCheckCase):
    def with_date(self, value=WHEN, duplicate=None):
        extra = "- **Box checked:** " + value + "\n"
        if duplicate is not None:
            extra += "- **Box checked:** " + duplicate + "\n"
        text = self.record().text
        text = text.replace("- **Status:** built\n", "- **Status:** built\n" + extra, 1)
        self.write("decks/casual/a.md", text)

    def index(self):
        return {summary["id"]: summary for summary in deck_page.decks_index()["decks"]}

    def publish(self, thing):
        state.store().visibility_set("home", thing, True, ACTOR, "Publish synthetic fixture " + thing)

    def member(self):
        path = self.magic / "people/user2/decks/casual/member.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self.record().text.replace("# A\n", "# Member fixture\n").replace("- **Played by:** either\n", "")
        path.write_text(text, encoding="utf-8")

    def test_valid_date_and_missing_date_have_exact_distinct_private_projection(self):
        self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": None})
        self.with_date()
        self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": WHEN})

    def test_malformed_or_duplicate_headers_mean_no_reliable_recorded_date(self):
        original = self.record().text
        for value, duplicate in (("2026-02-30", None), ("20261026", None), ("not a date", None),
                                 ("", None), (WHEN, WHEN), (WHEN, "2026-10-25"), ("２０２６-１０-２６", None)):
            with self.subTest(value=value, duplicate=duplicate):
                self.write("decks/casual/a.md", original)
                self.with_date(value, duplicate)
                self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": None})

    def test_only_ordinary_built_home_decks_have_the_field(self):
        self.with_date()
        self.deck("building", "Building fixture", "building", support.MAIN)
        self.deck("idea", "Idea fixture", "idea", support.MAIN)
        self.deck("commander", "Commander fixture", "built", support.MAIN, kind="commander")
        self.product("fixture-product.csv", ("deck", support.ELF, 1), column="section")
        self.status(("fixture-product.csv", "owned", "yes"))
        self.member()
        by_id = self.index()
        self.assertEqual(by_id["casual/a"]["box_check"], {"checked_on": WHEN})
        self.assertEqual(by_id["commander/commander"]["box_check"], {"checked_on": None})
        for deck_id in ("casual/building", "casual/idea", "product/fixture-product"):
            self.assertNotIn("box_check", by_id[deck_id])
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            member = self.index()["user2/casual/member"]
        self.assertNotIn("box_check", member)

    def test_unreadable_ordinary_record_omits_metadata_rather_than_claiming_no_date(self):
        self.write("decks/casual/a.md", "# A\n\n- **Status:** built\n- **Box checked:** " + WHEN + "\n\nNo recorded list.\n")
        answer = self.index()["casual/a"]
        self.assertIn("error", answer)
        self.assertNotIn("box_check", answer)

    def test_both_home_profiles_can_read_the_private_date(self):
        self.with_date()
        for profile in ("matt", "user1"):
            with self.subTest(profile=profile), access.using({"profile": profile, "email": profile + "@example.com", "remote": True}):
                self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": WHEN})

    def test_anonymous_script_reads_home_dates_but_other_spaces_stay_out_of_scope(self):
        self.with_date()
        self.member()
        with access.using(None), access.viewing(None), access.answering(True):
            by_id = self.index()
        self.assertEqual(by_id["casual/a"]["box_check"], {"checked_on": WHEN})
        self.assertNotIn("box_check", by_id["user2/casual/member"])

    def test_public_decks_or_public_collection_never_publish_the_historical_date(self):
        self.with_date()
        self.publish("decks")
        for public_collection in (False, True):
            if public_collection:
                self.publish("collection")
            with self.subTest(public_collection=public_collection), \
                    access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                    mock.patch.object(boxcheck, "checked_on", side_effect=AssertionError("Private date read")):
                self.assertNotIn("box_check", self.index()["casual/a"])

    def test_an_outside_admin_has_no_home_date_override(self):
        self.with_date()
        self.publish("decks")
        self.publish("collection")
        profiles = copy.deepcopy(household_config.PROFILES)
        next(profile for profile in profiles if profile["id"] == "user2")["role"] = "admin"
        household_config.use(self, profiles)
        with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}):
            self.assertNotIn("box_check", self.index()["casual/a"])

    def test_anonymous_http_reader_of_public_inventory_gets_no_date(self):
        self.with_date()
        self.publish("decks")
        self.publish("collection")
        with access.using(None), access.viewing(None), access.answering(False), \
                mock.patch.object(boxcheck, "checked_on", side_effect=AssertionError("Private date read")):
            self.assertNotIn("box_check", self.index()["casual/a"])

    def test_date_uses_the_pinned_request_snapshot_and_adds_no_read_side_effects(self):
        self.with_date("2026-10-25")
        snapshot = inventory.current()
        before = files.render(snapshot, decks=True)
        text = self.record().text.replace("2026-10-25", WHEN)
        self.write("decks/casual/a.md", text)
        with inventory.pinned(snapshot), mock.patch.object(self.inventory, "apply", side_effect=AssertionError("Read wrote data")):
            self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": "2026-10-25"})
            self.assertEqual(files.render(inventory.current(), decks=True), before)
        self.assertEqual(self.index()["casual/a"]["box_check"], {"checked_on": WHEN})

    def test_existing_index_metadata_is_unchanged_and_no_extra_ordinary_record_parse_is_needed(self):
        self.with_date()
        original = ops_decks.parsed_deck
        parsed = []
        def spy(stored):
            parsed.append(stored.id if stored is not None else None)
            return original(stored)
        with mock.patch.object(ops_decks, "parsed_deck", side_effect=spy):
            added = self.index()
        with mock.patch.object(boxcheck, "checked_on", return_value=None):
            existing = self.index()
        for value in (added, existing):
            for summary in value.values():
                summary.pop("box_check", None)
        self.assertEqual(added, existing)
        # Token/kit readers may parse too; the check-date read itself reuses the
        # one _assembled_view record, rather than asking for another parse.
        summary = decks.find_summary("casual/a")
        deck = original(self.record())
        with mock.patch.object(ops_decks, "parsed_deck", side_effect=AssertionError("Duplicate date parse")):
            deck_page._assembled_view(summary, None, [], deck=deck, check_date=True)
        self.assertEqual(summary["box_check"], {"checked_on": WHEN})
        self.assertTrue(parsed)

    def test_warm_owner_then_public_viewer_does_not_retain_private_metadata_in_cached_summaries(self):
        self.with_date()
        self.publish("decks")
        self.publish("collection")
        shared = decks.list_decks()
        before = copy.deepcopy(shared)
        with mock.patch.object(decks, "list_decks", return_value=shared):
            owner = self.index()
            self.assertEqual(owner["casual/a"]["box_check"], {"checked_on": WHEN})
            with access.using({"profile": "user2", "email": "user2@example.com", "remote": True}), \
                    mock.patch.object(boxcheck, "checked_on", side_effect=AssertionError("Warm private date read")):
                public = self.index()
        self.assertNotIn("box_check", public["casual/a"])
        self.assertEqual(shared, before)
