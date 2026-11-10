"""Settings' price settings (E11-S53, third slice): the saved currency and price-check shops laid over
config.json's, the store's record and GET/PUT /api/pricing-setting.

Run: python scripts/test_fixtures.py decklab.tests.test_pricing_setting
Every setting is supplied here; no database, rate or config.json of the PC is read or written.
"""
import contextlib
import io
import json
import unittest
from unittest import mock

from decklab.lib import access, config, currency, pricing_setting, shops, state
from decklab.lib.api import activity_headlines, activity_home, carddata
from decklab.lib.api import pricing_setting as pricing_api
from decklab.lib.state import Actor, Conflict, Invalid, Unavailable, memory
from decklab.lib.state import pricing as rules_pricing
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_collection_edit import ROLES

MATT = Actor("matt", "Matt")


def configured(**values):
    return mock.patch.object(config, "load", return_value=dict(config.DEFAULTS, **values))


class _Fresh(unittest.TestCase):
    def setUp(self):
        pricing_setting.forget()
        self.addCleanup(pricing_setting.forget)
        for said in (currency._said, shops._said, pricing_setting._said):
            said.clear()
            self.addCleanup(said.clear)

    def install(self, store=None):
        store = store or memory.MemoryStore()
        self.addCleanup(state.use(store))
        return store


class RulesTests(_Fresh):
    def test_normalize_matches_the_readers_rules(self):
        self.assertEqual(rules_pricing.normalize({}), rules_pricing.EMPTY)
        self.assertEqual(rules_pricing.normalize({"currency": " eur ", "shops": ["GamesPortal", "mtgmate", "mtgmate"]}),
                         {"v": 1, "currency": "EUR", "shops": ["mtgmate", "gamesportal"]})
        self.assertEqual(rules_pricing.normalize({"v": 1, "currency": None, "shops": []})["shops"], [])
        for code in currency.ECB_CODES:
            self.assertEqual(rules_pricing.normalize({"currency": code})["currency"], currency.valid(code))
        for bad in ({"currency": "XYZ"}, {"currency": 5}, {"shops": ["nowhere"]}, {"shops": "mtgmate"},
                    {"shops": [1]}, {"other": 1}, {"v": 2}, {"v": None}, {"v": True}, {"v": "1"}, {"v": "2"}, []):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                rules_pricing.normalize(bad)
        self.assertIsNone(shops.normalize_keys(["mtgmate", "nowhere"]))
        self.assertEqual(shops.normalize_keys([" MTGMate "]), ("mtgmate",))
        self.assertIsNone(currency.valid("xyz"))

    def test_memory_store_saves_whole_with_a_revision(self):
        store = memory.MemoryStore()
        self.assertEqual(store.pricing_setting(), {"revision": 0, "pricing": rules_pricing.EMPTY})
        self.assertIsNotNone(store.pricing_setting_cached())
        self.assertEqual(store.pricing_setting_put({"currency": None, "shops": None}, 0, MATT, "Nothing"),
                         {"revision": 0, "pricing": rules_pricing.EMPTY})          # unchanged: no change set
        saved = store.pricing_setting_put({"currency": "eur", "shops": []}, 0, MATT, "Set")
        self.assertEqual(saved, {"revision": 1, "pricing": {"v": 1, "currency": "EUR", "shops": []}})
        self.assertEqual(store.pricing_setting_put(saved["pricing"], 1, MATT, "Again")["revision"], 1)
        self.assertEqual(len(store.changes()), 1)
        self.assertEqual(store.changes()[0]["rows"][0]["table"], "pricing_setting")
        with self.assertRaises(Conflict):
            store.pricing_setting_put({"currency": "GBP"}, 0, MATT, "Stale")
        store.pricing_ready = False
        with self.assertRaises(Unavailable) as caught:
            store.pricing_setting()
        self.assertEqual(str(caught.exception), rules_pricing.MIGRATE)
        self.assertEqual(store.pricing_setting_cached()["revision"], 1)


class ResolverTests(_Fresh):
    def test_without_a_store_config_json_then_the_default_as_before(self):
        with configured():
            self.assertEqual((currency.code(), shops.enabled_adapters()), ("AUD", shops.SNAPSHOT_ADAPTERS))
        with configured(currency="GBP", shops=["mtgmate"]):
            self.assertEqual(currency.code(), "GBP")
            self.assertEqual([a.key for a in shops.enabled_adapters()], ["mtgmate"])
            self.assertEqual(pricing_setting.source("currency"), "config")
        with mock.patch.object(config, "load", side_effect=ValueError("broken")):
            self.assertEqual(currency.code(), "AUD")

    def test_a_saved_field_wins_and_a_null_one_falls_back(self):
        store = self.install()
        store.pricing_setting_put({"currency": "EUR", "shops": None}, 0, MATT, "Set")
        with configured(currency="GBP", shops=["mtgmate"], other="kept"):
            self.assertEqual(currency.code(), "EUR")
            self.assertEqual([a.key for a in shops.enabled_adapters()], ["mtgmate"])
            self.assertEqual(pricing_setting.settings()["other"], "kept")
            self.assertEqual((pricing_setting.source("currency"), pricing_setting.source("shops")), ("saved", "config"))
            self.assertEqual(carddata.pricing()["currency"], "EUR")
            store.pricing_setting_put({"currency": None, "shops": []}, 1, MATT, "Off")
            self.assertEqual(currency.code(), "GBP")
            self.assertEqual(shops.enabled_adapters(), ())
            self.assertEqual(carddata.pricing()["shops"], [])
        with configured():
            store.pricing_setting_put({"currency": None, "shops": None}, 2, MATT, "Back")
            self.assertEqual(pricing_setting.source("currency"), "default")

    def test_a_store_that_is_down_or_unmigrated_gives_the_last_value_else_config(self):
        store = self.install()
        store.pricing_setting_put({"currency": "EUR"}, 0, MATT, "Set")
        with configured(currency="GBP"):
            self.assertEqual(currency.code(), "EUR")
            store.down = True
            self.assertEqual(currency.code(), "EUR")              # the last value read
        fresh = self.install(memory.MemoryStore())
        fresh.pricing_ready = False
        with configured(currency="GBP"):
            self.assertEqual(currency.code(), "GBP")              # before migration 0022: config.json's
        with configured(), contextlib.redirect_stderr(io.StringIO()):
            broken = mock.Mock(spec=["pricing_setting", "pricing_setting_cached"])
            broken.pricing_setting.side_effect = AssertionError("odd")
            broken.pricing_setting_cached.return_value = {"pricing": "nonsense"}
            self.install(broken)
            self.assertEqual(currency.code(), "AUD")
            self.assertEqual(currency.code(), "AUD")
            self.assertEqual(broken.pricing_setting.call_count, 1)   # not asked again for RETRY_SECONDS

    def test_an_unreadable_config_still_answers_status_in_aud(self):
        self.install().pricing_setting_put({"currency": "EUR"}, 0, MATT, "Set")
        with mock.patch.object(config, "load", side_effect=ValueError("broken")):
            self.assertEqual(currency.code(), "AUD")
            self.assertIsNone(carddata.status()["pricing"])


class PricingApiTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        pricing_setting.forget()
        self.addCleanup(pricing_setting.forget)
        self.config_bytes = json.dumps({**ROLES, "currency": "GBP", "shops": ["mtgmate"], "kept": [1, 2]}).encode()
        (self.box.root / "config.json").write_bytes(self.config_bytes)

    def save(self, *, profile="matt", expect=0, currency_code="EUR", shops_keys=None, **other):
        return pricing_api.change(self.body(profile, expect=expect, currency=currency_code,
                                            shops=["gamesportal"] if shops_keys is None else shops_keys, **other))

    def test_home_admin_saves_and_home_member_reads(self):
        with access.viewing("matt"):
            shown = pricing_api.view()
            self.assertEqual((shown["revision"], shown["can_edit"]), (0, True))
            self.assertEqual(shown["currency"], {"saved": None, "config": "GBP", "effective": "GBP", "symbol": "£",
                                                 "source": "config"})
            self.assertEqual((shown["shops"]["config"], shown["shops"]["effective"]), (["mtgmate"], ["mtgmate"]))
            self.assertEqual([c["key"] for c in shown["shops"]["choices"]], ["mtgmate", "gamesportal"])
            self.assertEqual(len(shown["currencies"]), len(currency.ECB_CODES))
            saved = self.save()
        self.assertEqual((saved["revision"], saved["currency"]["effective"], saved["currency"]["source"]), (1, "EUR", "saved"))
        self.assertEqual(saved["shops"]["effective"], ["gamesportal"])
        self.assertEqual(currency.code(), "EUR")                  # at once: no restart
        with access.viewing("user1"):
            self.assertFalse(pricing_api.view()["can_edit"])
            self.assertApiError(403, lambda: self.save(profile="user1", expect=1))
        change, = self.box.state.changes()
        self.assertEqual((change["actor"], change["message"]), ("matt", "Set the price settings"))
        self.assertEqual((self.box.root / "config.json").read_bytes(), self.config_bytes)   # never written

    def test_outsiders_are_refused_before_storage(self):
        for remote in (False, True):
            identity = {"profile": "user2", "email": "", "remote": True} if remote else None
            with access.using(identity), access.viewing("user2"), \
                    mock.patch.object(self.box.state, "pricing_setting", side_effect=AssertionError("private read")), \
                    mock.patch.object(self.box.state, "pricing_setting_put", side_effect=AssertionError("private write")):
                self.assertApiError(403, pricing_api.view)
                self.assertApiError(403, lambda: self.save(profile="user2"))

    def test_validation_staleness_and_unchanged_saves(self):
        with access.viewing("matt"):
            self.assertApiError(400, lambda: self.save(currency_code="XYZ"))
            self.assertApiError(400, lambda: self.save(shops_keys=["nowhere"]))
            self.assertApiError(400, lambda: self.save(shops_keys="mtgmate"))
            self.assertApiError(400, lambda: self.save(extra=1))
            self.assertApiError(400, lambda: pricing_api.change(b"[]"))
            self.assertApiError(400, lambda: pricing_api.change(self.body("matt", expect=0, currency="EUR")))
            self.assertApiError(413, lambda: pricing_api.change(b"{" + b" " * 5000 + b"}"))
            self.assertEqual(self.save(currency_code="eur ")["currency"]["saved"], "EUR")
            self.assertApiError(409, lambda: self.save(expect=0))
            self.assertEqual(self.save(expect=1, currency_code="EUR")["revision"], 1)     # unchanged: nothing written
            self.assertEqual(self.save(expect=1, currency_code=None, shops_keys=[])["shops"]["effective"], [])
        self.assertEqual(len(self.box.state.changes()), 2)
        self.assertEqual((self.box.root / "config.json").read_bytes(), self.config_bytes)

    def test_down_or_unmigrated_store_answers_503(self):
        with access.viewing("matt"):
            self.box.state.pricing_ready = False
            self.assertApiError(503, pricing_api.view, contains="migration 0022")
            self.assertApiError(503, self.save, contains="migration 0022")
            self.box.state.pricing_ready = True
            self.box.state.down = True
            self.assertApiError(503, pricing_api.view)
        self.assertEqual(currency.code(), "GBP")                  # config.json's meanwhile

    def test_activity_row_shows_only_to_home_record_readers(self):
        profiles = {"matt": {"id": "matt", "role": "admin", "space": "home"},
                    "user1": {"id": "user1", "role": "member", "space": "home"},
                    "user2": {"id": "user2", "role": "member", "space": "user2"}}
        row = {"table": "pricing_setting", "op": "UPDATE", "before": {"content": {"currency": "EUR"}}}
        for me in ("matt", "user1"):
            self.assertEqual(activity_home.pricing_setting_row(row, "all", profiles, me),
                             {"table": "pricing_setting", "op": "UPDATE", "summary": "Price settings updated"})
        self.assertIsNone(activity_home.pricing_setting_row(row, "all", profiles, "user2"))
        self.assertIsNone(activity_home.pricing_setting_row(row, {"space": "user2"}, profiles, "user2"))
        self.assertEqual(activity_headlines._KIND_OF["pricing_setting"], "settings")


if __name__ == "__main__":
    unittest.main()
