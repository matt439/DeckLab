"""Profile settings and the simulations setting end to end through PostgreSQL (lib/api/settings.py
and lib/api/simulations.py over decklab.lib.state's PgStore), and what they do while the
database can't be reached: the matchup and field pages' settings fall back to the last known
values or the defaults, and the simulations mode to the last one known (else "admins").

Each test runs in test_api's Sandbox with a PgStore on the class's throwaway database installed
over the Sandbox's in-memory store, and its own circuit breaker, so tripping it stands in for a
stopped PostgreSQL without touching the process-wide one. They skip without a database
(db_support).

Run from the repo root: python -m unittest decklab.tests.test_db_settings
"""
import json
from unittest import mock

from decklab.lib import access, api, state
from decklab.lib.forge import slots
from decklab.lib.state import pg
from decklab.tests import db_support
from decklab.tests.test_api import W3_SETTINGS, Sandbox

DEFAULTS = {"theme": "system", "matchup_games": "800", **W3_SETTINGS}
TUNNEL_USER1 = {"profile": "user1", "email": "", "remote": True}


class PgApiTestCase(db_support.DbTestCase):

    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        self.breaker = pg.Breaker()
        self.store = self.fresh_store()
        self.addCleanup(state.use(self.store))
        self.addCleanup(slots.set_limit, None)      # the test package's own slots folder

    def fresh_store(self):
        """A PgStore on this class's database with nothing cached (as a restarted server)."""
        return pg.PgStore(dbname=self.dbname, breaker=self.breaker)

    def rows(self, sql):
        with self.connect() as c:
            return c.execute(sql).fetchall()

    def trail(self):
        """(actor, via, source, message) of each change set, oldest first."""
        return [(c["actor"], c["via"], c["source"], c["message"])
                for c in reversed(self.store.activity(limit=100)["changes"])]

    def assert503(self, call, *args):
        with self.assertRaises(api.ApiError) as caught:
            call(*args)
        self.assertEqual((caught.exception.status, caught.exception.extra), (503, {"reason": "database"}))


class SettingsTests(PgApiTestCase):

    def test_round_trip(self):
        self.assertEqual(api.get_settings("user1"), DEFAULTS)
        dark = dict(DEFAULTS, theme="dark", matchup_games="1600")
        self.assertEqual(api.put_settings("user1", b'{"theme": "dark", "matchup_games": "1600"}'), dark)
        self.assertEqual(api.get_settings("user1"), dark)
        self.assertEqual(api.get_settings("matt"), DEFAULTS)                # each person's own
        self.assertEqual(self.rows("select profile_id, key, value from profile_setting order by key"),
                         [("user1", "matchup_games", "1600"), ("user1", "theme", "dark")])
        # A server started afresh reads the same.
        with state.use(self.fresh_store()):
            self.assertEqual(api.get_settings("user1"), dark)
        self.assertEqual(self.trail(), [("home", "home", "web", "Change User1's settings: theme, matchup_games")])

    def test_nothing_is_written_when_nothing_changes(self):
        api.put_settings("matt", b'{"theme": "dark"}')
        api.put_settings("matt", b'{"theme": "dark"}')
        api.put_settings("matt", b"{}")
        self.assertEqual(len(self.trail()), 1)

    def test_who_changed_it(self):
        with access.viewing("matt"):                                        # at home, the chooser names Matt
            api.put_settings("user1", b'{"theme": "light"}')
        with access.viewing("nobody"):                                      # a name that isn't a profile
            api.put_settings("user1", b'{"theme": "dark"}')
        with access.using(TUNNEL_USER1):
            api.put_settings("user1", b'{"field_budget": "quick"}')
        self.assertEqual(self.trail(), [("matt", "home", "web", "Change User1's settings: theme"),
                                        ("home", "home", "web", "Change User1's settings: theme"),
                                        ("user1", "tunnel", "web", "Change User1's settings: field_budget")])

    def test_the_database_down(self):
        api.put_settings("user1", b'{"matchup_games": "3200", "field_budget": "thorough"}')
        self.breaker.trip("a test")
        self.assert503(api.get_settings, "user1")
        self.assert503(api.put_settings, "user1", b'{"theme": "dark"}')
        # The matchup and field pages' defaults: the values last known, else the defaults; never a 503.
        self.assertEqual(api.forge_runs._matchup_games("user1"), 3200)
        self.assertEqual(api.field_page._field_budget("user1"), "thorough")
        self.assertEqual(api.forge_runs._matchup_games("matt"), 800)
        self.assertEqual(api.forge_runs._matchup_mode("matt"), "assess")
        with state.use(self.fresh_store()):                                 # nothing known yet
            self.assertEqual(api.forge_runs._matchup_games("user1"), 800)
            self.assertEqual(api.field_page._field_budget("user1"), "standard")
        self.breaker.reset()
        self.assertEqual(api.get_settings("user1")["theme"], "system")     # the refused save wrote nothing

    def test_a_value_saved_elsewhere_isnt_skipped(self):
        # This server's cached read says dark; an import meanwhile saved light. Asking for dark again
        # saves it: the store compares inside its write, not this server's cache.
        api.put_settings("user1", b'{"theme": "dark"}')
        self.fresh_store().settings_put("user1", {"theme": "light"}, state.Actor("system", "an import", source="cli"),
                                        "Import User1's settings")
        self.assertEqual(api.put_settings("user1", b'{"theme": "dark"}')["theme"], "dark")
        self.assertEqual(self.rows("select value from profile_setting where key = 'theme'"), [("dark",)])
        self.assertEqual(self.trail()[-1], ("home", "home", "web", "Change User1's settings: theme"))

    def test_an_error_the_store_doesnt_name(self):
        # A raw database error (here a RuntimeError) is handled like the database being down by the
        # readers that must always answer: the last values known.
        api.put_settings("user1", b'{"matchup_games": "3200"}')
        api.change_simulations(json.dumps({"profile": "matt", "mode": "paused"}).encode())
        odd = RuntimeError("an internal error")
        with mock.patch.object(self.store, "settings", side_effect=odd), \
                mock.patch.object(self.store, "simulation_mode", side_effect=odd), \
                mock.patch.object(api.common, "_log"):
            self.assertEqual(api.forge_runs._matchup_games("user1"), 3200)
            self.assertEqual(api.simulations.mode(), "paused")
            self.assertTrue(api.simulations_view(None)["unavailable"])


class SimulationsTests(PgApiTestCase):

    def test_the_default_with_nothing_saved(self):
        seen = api.simulations_view(None)
        self.assertEqual((seen["mode"], seen["by"], seen["since"]), ("admins", None, None))
        self.assertNotIn("unavailable", seen)

    def test_change_and_view(self):
        with access.using({"profile": "matt", "email": "", "remote": True}):
            seen = api.change_simulations(json.dumps({"profile": "matt", "mode": "paused", "workers": 2}).encode())
        self.assertEqual((seen["mode"], seen["by"], seen["workers"]), ("paused", "Matt", 2))
        self.assertRegex(seen["since"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual(self.rows("select mode, set_by, set_by_name from simulation_mode"), [("paused", "matt", "Matt")])
        self.assertEqual(self.trail(), [("matt", "tunnel", "web", "Set simulations to paused")])
        with state.use(self.fresh_store()):                                 # a server started afresh
            self.assertEqual(api.simulations.mode(), "paused")
            self.assertEqual(api.simulations_view(None)["since"], seen["since"])
        # The worker limit alone writes nothing to the database.
        api.change_simulations(json.dumps({"profile": "matt", "workers": None}).encode())
        self.assertEqual(len(self.trail()), 1)

    def test_the_database_down(self):
        api.change_simulations(json.dumps({"profile": "matt", "mode": "paused"}).encode())
        self.breaker.trip("a test")
        # The last mode known holds, so a pause isn't lifted by an outage; the answer says it's unavailable.
        seen = api.simulations_view(None)
        self.assertEqual((seen["mode"], seen["by"], seen["unavailable"]), ("paused", "Matt", True))
        self.assertEqual(api.simulations.mode(), "paused")
        # A change is refused before the worker limit is touched.
        self.assert503(api.change_simulations, json.dumps({"profile": "matt", "mode": "everyone", "workers": 2}).encode())
        self.assertIsNone(slots.limit())
        # A server that never read it goes by the default.
        with state.use(self.fresh_store()):
            seen = api.simulations_view(None)
            self.assertEqual((seen["mode"], seen["unavailable"]), ("admins", True))
        self.breaker.reset()
        self.assertEqual(api.simulations_view(None)["mode"], "paused")
        self.assertNotIn("unavailable", api.simulations_view(None))
