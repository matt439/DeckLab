"""E10-S38 and E10-S34's phase-4 parts: the roster, settings and simulations seen per viewer,
and refusals that name no space or person the viewer can't see.

- GET /api/profiles gives a viewer their own space's profiles (home's two for Matt and User1,
  only himself for User5), plus each profile of a space with something public by name only (none
  until E10-S28's switches: the tests patch the hook), plus the admins' display names; a script
  gets everyone; the home page before a pick gets the home profiles its chooser offers.
- GET /api/profiles/<id>/settings answers only the viewer's own id (no admin override), a missing
  profile and someone else's alike; the matchup and field pages never read another's as defaults.
- GET /api/simulations gives a member only the mode and a reason naming nobody; who set it, when
  and the PC's workers only to whoever may change it.
- No refusal names a space or person the viewer can't see: the 403s outside the home, a new deck
  in a hidden or missing space, a deck id in a space that doesn't exist.

Over test_api's Sandbox with a config of Matt, User1, User2 and User5; nothing touches the
network, the real decklab/data/ or the live database.
"""
import contextlib
import json
import re
from unittest import mock

from decklab.lib import access, api, config, permissions, profiles
from decklab.lib.api import field_page, forge_runs, guard, library, settings, simulations
from decklab.lib.forge import slots
from decklab.lib.state.memory import MemoryStore
from decklab.lib import state
from decklab.tests.test_api import ApiTestCase, _write

PROFILES = [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2"},
    {"id": "user5", "name": "User5", "role": "member", "space": "user5"},
]
FULL = ("id", "name", "plays_as", "role", "space")


def tunnel(who):
    """A visit through the tunnel by who's login."""
    return access.using({"profile": who, "email": "", "remote": True})


@contextlib.contextmanager
def home(who=None):
    """A home-network request naming who (None: the page before "Who are you?"), not a script."""
    with access.using(None), access.viewing(who), access.answering(False):
        yield


class RosterTestCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps({"profiles": PROFILES}))
        self.store = MemoryStore(mode=None)
        self.addCleanup(state.use(self.store))


class RosterTests(RosterTestCase):

    def ids(self, answer):
        return [p["id"] for p in answer["profiles"]]

    def test_a_script_gets_everyone(self):
        answer = settings.profiles()
        self.assertEqual(self.ids(answer), ["matt", "user1", "user2", "user5"])
        self.assertEqual(answer["admins"], ["Matt"])
        self.assertTrue(all(set(p) == set(FULL) for p in answer["profiles"]))
        self.assertNotIn("emails", json.dumps(answer))

    def test_a_member_gets_only_himself_and_the_admins_name(self):
        for who in ("user5", "user2"):
            with tunnel(who):
                answer = settings.profiles()
            self.assertEqual(self.ids(answer), [who], who)
            self.assertEqual(set(answer["profiles"][0]), set(FULL), who)
            # The admin's display name only, for "ask Matt" wording: no role, space or plays_as.
            self.assertEqual(answer["admins"], ["Matt"], who)
            words = json.dumps(answer)
            for hidden in ("User1", "User2" if who == "user5" else "User5", '"home"', '"admin"'):
                self.assertNotIn(hidden, words, who)

    def test_matt_and_user1_read_homes_profiles_as_today(self):
        for who in ("matt", "user1"):
            for context in (tunnel(who), home(who)):
                with context:
                    answer = settings.profiles()
                self.assertEqual(answer["profiles"], [{k: p.get(k) for k in FULL} for p in PROFILES[:2]], who)
                self.assertEqual(answer["admins"], ["Matt"])

    def test_the_home_page_before_a_pick_gets_the_chooser_profiles(self):
        with home():
            self.assertEqual(self.ids(settings.profiles()), ["matt", "user1"])

    def test_a_login_that_isnt_set_up_gets_nobody(self):
        with tunnel("stranger"):
            answer = settings.profiles()
        self.assertEqual(answer["profiles"], [])

    def test_a_space_with_something_public_is_listed_by_name(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            with tunnel("user5"):
                answer = settings.profiles()
            self.assertEqual(answer["profiles"][1:], [{"id": "user2", "name": "User2"}])
            self.assertEqual(self.ids(answer), ["user5", "user2"])
            with tunnel("matt"):                # other spaces' profiles follow the same rule for home
                self.assertEqual(self.ids(settings.profiles()), ["matt", "user1", "user2"])
            with tunnel("user2"):             # his own, in full, once
                answer = settings.profiles()
            self.assertEqual(answer["profiles"], [{k: PROFILES[2].get(k) for k in FULL}])

    def test_an_older_config_where_everyone_is_an_admin_names_no_admins(self):
        _write(self.box.root / "config.json",
               json.dumps({"profiles": [{"id": p["id"], "name": p["name"], "space": p["space"]} for p in PROFILES]}))
        self.assertTrue(profiles.legacy(config.load()["profiles"]))
        self.assertEqual(settings.profiles()["admins"], [])

    def test_the_page_keeps_the_admins_for_its_ask_wording(self):
        app = (config.DECKLAB / "web" / "app.js").read_text(encoding="utf-8")
        core = (config.DECKLAB / "web" / "core.js").read_text(encoding="utf-8")
        self.assertIn("function keepRoster(roster)", app)
        self.assertIn("function adminWords()", core)
        self.assertNotIn("Ask Matt", app)
        self.assertIn("Ask ${adminWords()}", app)


class SettingsTests(RosterTestCase):

    def test_only_ones_own_settings_are_read(self):
        for who, own in (("matt", "matt"), ("user1", "user1"), ("user5", "user5")):
            with tunnel(who):
                self.assertEqual(settings.get_settings(own)["theme"], "system")
                for other in ("matt", "user1", "user2", "user5", "nobody"):
                    if other == own:
                        continue
                    error = self.assertApiError(403, settings.get_settings, other)
                    self.assertEqual(error.message, settings.SETTINGS_HIDDEN, (who, other))
        with home("user1"):
            self.assertApiError(403, settings.get_settings, "matt")
        with home():
            self.assertApiError(403, settings.get_settings, "user1")
        # A script naming nobody reads any, and is told of a profile that doesn't exist.
        self.assertEqual(settings.get_settings("user2")["theme"], "system")
        self.assertApiError(404, settings.get_settings, "nobody")

    def test_a_change_to_a_missing_profile_is_refused_as_someone_elses(self):
        body = json.dumps({"theme": "dark"})
        with tunnel("user5"):
            missing = self.assertApiError(403, settings.put_settings, "nobody", body)
            other = self.assertApiError(403, settings.put_settings, "user2", body)
        self.assertEqual(missing.message, other.message)

    def test_a_change_to_someone_elses_settings_returns_only_what_was_sent(self):
        # Matt may change User1's settings at home (settings.edit), but the answer reads none
        # of hers beyond the keys he sent: an empty PUT gets nothing back (E10-S34).
        settings.put_settings("user1", json.dumps({"theme": "dark", "matchup_mode": "fixed"}))
        with home("matt"):
            self.assertEqual(settings.put_settings("user1", "{}"), {})
            self.assertEqual(settings.put_settings("user1", json.dumps({"theme": "light"})),
                             {"theme": "light"})
            mine = settings.put_settings("matt", json.dumps({"theme": "dark"}))
        self.assertEqual(set(mine), set(settings.SETTINGS))
        saved = settings.get_settings("user1")                              # a script
        self.assertEqual((saved["theme"], saved["matchup_mode"]), ("light", "fixed"))
        self.assertEqual(set(settings.put_settings("user1", "{}")), set(settings.SETTINGS))

    def test_the_run_pages_defaults_are_read_only_from_ones_own(self):
        with tunnel("user5"):
            self.assertEqual(settings.own_settings_id("user5"), "user5")
            self.assertIsNone(settings.own_settings_id("matt"))
            self.assertIsNone(settings.own_settings_id("nobody"))
        self.assertEqual(settings.own_settings_id("matt"), "matt")          # a script
        for module in (forge_runs, field_page):
            text = (config.DECKLAB / "lib" / "api" / f"{module.__name__.rsplit('.', 1)[1]}.py").read_text(encoding="utf-8")
            self.assertIn("own_settings_id(profile)", text, module.__name__)


class SimulationsTests(RosterTestCase):

    def setUp(self):
        super().setUp()
        self.addCleanup(slots.set_limit, None)

    def test_a_member_gets_the_mode_and_a_reason_naming_nobody(self):
        with tunnel("matt"):
            simulations.change(json.dumps({"profile": "matt", "mode": "admins"}))
            mine = simulations.view()
        self.assertEqual((mine["by"], mine["may_edit"]), ("Matt", True))
        self.assertTrue({"since", "workers", "max_workers"} <= set(mine))
        for who in ("user1", "user5"):
            with tunnel(who):
                theirs = simulations.view()
            self.assertEqual(theirs, {"mode": "admins", "may_start": False, "may_edit": False,
                                      "why_not": permissions.RUNS_ADMINS}, who)
        with tunnel("matt"):
            simulations.change(json.dumps({"profile": "matt", "mode": "paused"}))
        with tunnel("user5"):
            self.assertEqual(simulations.view()["why_not"], permissions.RUNS_PAUSED)
        for words in (permissions.RUNS_ADMINS, permissions.RUNS_PAUSED, permissions.RUNS_STOP_ADMINS):
            self.assertNotIn("Matt", words)
        self.assertFalse(hasattr(permissions, "RUNS_ADMINS_NAMED"))


class RefusalWordsTests(RosterTestCase):

    def test_the_refusals_outside_the_home_name_no_space_or_person(self):
        texts = {"collection": guard.COLLECTION_HIDDEN, "records": guard.INVENTORY_HIDDEN,
                 "accessories": guard.ACCESSORIES_HIDDEN, "new deck": guard.HIDDEN_SPACE,
                 "settings": settings.SETTINGS_HIDDEN, "wishlist": guard.WISHLIST_HIDDEN,
                 "commander night": permissions.COMMANDER_NIGHT_PRIVATE,
                 "inventory": guard.inventory_hidden("home"), "person": guard.inventory_hidden("user2")}
        names = re.compile(r"\b(home|matt|user1|user2|user5|user5|user3|user4)\b", re.I)
        for what, words in texts.items():
            self.assertIsNone(names.search(words), (what, words))
        user5 = {"id": "user5", "role": "member", "space": "user5"}
        for action, target in (("accessories.edit", None), ("commander_night.edit", None),
                               ("deck.create", {"space": "home"}), ("deck.create", {"space": "user2"}),
                               ("collection.edit", "home"), ("tokens.edit", "user2"),
                               ("settings.edit", "matt"), ("wishlist.edit", "user1"), ("orders.edit", None)):
            why = permissions.reason(user5, action, target)
            self.assertIsNotNone(why, action)
            self.assertIsNone(names.search(why), (action, why))

    def test_a_new_deck_in_a_hidden_or_missing_space_answers_alike(self):
        with tunnel("user5"):
            for space in ("user2", "home", "nobody"):
                error = self.assertApiError(403, api.check_draft,
                                            json.dumps({"profile": "user5", "kind": "casual", "space": space}))
                self.assertEqual(error.message, guard.HIDDEN_SPACE, space)

    def test_a_deck_id_in_a_space_that_doesnt_exist_is_a_missing_deck(self):
        with tunnel("user5"):
            for deck_id in ("nobody/casual/elves", "user2/casual/elves"):
                error = self.assertApiError(404, api.deck_view, deck_id)
                self.assertEqual(error.message, f"No deck {deck_id!r}")
            self.assertEqual(self.assertApiError(404, library.check_deck_id, "nobody/casual/elves").message,
                             "No deck 'nobody/casual/elves'")
            self.assertApiError(400, library.check_deck_id, "nobody/casual/../x")       # a bad shape stays 400
        error = self.assertApiError(400, library.check_deck_id, "nobody/casual/elves")    # a script is told
        self.assertIn("there's no space", error.message)

    def test_the_pages_refusals_name_no_space(self):
        app = (config.DECKLAB / "web" / "app.js").read_text(encoding="utf-8")
        for start in ("function showNoAccessories()", "function showNoInventory(title)"):
            body = app[app.index(start):]
            body = body[:body.index("\n}\n")]
            words = re.findall(r'text: "([^"]+)"', body)
            self.assertTrue(words, start)
            for text in words:
                self.assertNotIn("home", text.lower(), (start, text))
