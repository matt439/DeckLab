"""V2 listing preferences, older schemas and rollback use only a guarded disposable database."""
from decklab.db import migrate
from decklab.lib.state import Unavailable
from decklab.lib.state import pg
from decklab.tests import db_support
from decklab.tests import test_pricing_setting_db as pricing_fixture
from decklab.tests.test_pricing_setting_db import ACTOR
from decklab.tests.test_shop_quality_matching import PREFERENCE


class ShopQualityDbTests(pricing_fixture.PricingSettingDbTests):
    def test_v2_preference_is_audited_and_checked_without_rewriting_currency_or_shops(self):
        chosen = {"currency": "EUR", "shops": ["mtgmate"], "listing_preferences": PREFERENCE}
        saved = self.store.pricing_setting_put(chosen, 0, ACTOR, "Set synthetic listing preference")
        self.assertEqual(saved["pricing"], {"v": 2, **chosen})
        self.assertEqual(self.store.pricing_setting_put(saved["pricing"], 1, ACTOR, "Unchanged"), saved)
        self.assertTrue(self.invariant()[0])
        with self.connect("ro") as connection:
            self.assertEqual(connection.execute("select count(*) from audit.row_change where table_name='pricing_setting'").fetchone()[0], 1)

    def test_schema_downgrade_strips_only_new_synthetic_fields_and_forward_preserves_v1(self):
        saved = self.store.pricing_setting_put({"currency": "EUR", "shops": ["mtgmate"], "listing_preferences": PREFERENCE},
                                               0, ACTOR, "Set synthetic v2 preference")
        with self.connect("owner") as connection:
            db_support.roll_back_schema(connection, 24)
        old = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        expected = {"revision": 1, "pricing": {"v": 1, "currency": "EUR", "shops": ["mtgmate"]}}
        self.assertEqual(old.pricing_setting(), expected)
        with self.assertRaisesRegex(Unavailable, "migration 0025"):
            old.pricing_setting_put(saved["pricing"], 1, ACTOR, "Refuse new preference before migration")
        self.assertEqual(old.pricing_setting(), expected)
        migrate.apply(dbname=self.dbname)
        current = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.assertEqual(current.pricing_setting(), expected)
        changed = current.pricing_setting_put(saved["pricing"], 1, ACTOR, "Save after migration")
        self.assertEqual(changed["revision"], 2)
        self.assertEqual(changed["pricing"], saved["pricing"])
