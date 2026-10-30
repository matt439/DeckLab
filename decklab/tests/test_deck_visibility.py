"""A deck is seen only in its own space (E10-S30, phase 2 of the member template's order: no
switches yet), with no admin override, and a hidden deck answers exactly as a missing one.

- RuleTests: permissions.sees_deck and deck_spaces (pure), and guard.sees_deck's targets.
- LibraryTests: GET /api/decks (decks_index) for each viewer, with halves, usual opponents,
  aliases and decks_revision over the visible decks only.
- PageTests: GET /api/deck, /api/deck/edit, /api/deck/cards, /api/deck/opponents and practice
  hands answer a hidden id with the missing deck's 404, word for word.
- StaleTablesTests: the Tables out of date list and a save's stale_tables.
- PlayAndVisitsTests: GET /api/play's decks and lists, and Visits' beacon and panel.

test_api_permissions' sandbox: Matt (admin) and User1 at home, User2 and User3 with their own
spaces, User2 with one deck. Run from the repo root:
python scripts/test_fixtures.py decklab.tests.test_deck_visibility
"""
import json
from unittest import mock

from decklab.lib import access, api, decks, permissions, pool, visits
from decklab.lib.api import cover, guard, opponents, practice
from decklab.lib.api import visits as visits_api
from decklab.tests.test_api_permissions import PermissionTestCase

MATT = {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"}
USER1 = {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"}
USER2 = {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"}
HOME_DECK = "casual/gruul-test"
R_DECK = "user2/casual/r-elves"


def _as(who):
    return access.using({"profile": who, "email": "", "remote": True})


class RuleTests(PermissionTestCase):

    def test_each_space_sees_its_own_decks_and_the_admin_role_opens_nothing(self):
        for profile, seen in ((MATT, {"home"}), (USER1, {"home"}), (USER2, {"user2"})):
            for space in ("home", "user2", "user3"):
                with self.subTest(who=profile["id"], space=space):
                    self.assertEqual(permissions.sees_deck(profile, space), space in seen)
                    self.assertEqual(permissions.sees_deck(profile, space, script=True), space in seen)
            self.assertEqual(permissions.deck_spaces(profile), sorted(seen))

    def test_a_script_sees_every_deck_and_anyone_else_naming_nobody_none(self):
        self.assertTrue(permissions.sees_deck(None, "user2", script=True))
        self.assertTrue(permissions.sees_deck(None, None, script=True))
        self.assertIsNone(permissions.deck_spaces(None, script=True))
        self.assertFalse(permissions.sees_deck(None, "home"))
        self.assertEqual(permissions.deck_spaces(None), [])
        self.assertFalse(permissions.sees_deck(MATT, None))         # a space that can't be read

    def test_the_switches_extend_it_with_one_set(self):
        # E10-S28's switches: the spaces whose decks are public. An ordered product never leaves home.
        public = frozenset({"home"})
        self.assertTrue(permissions.sees_deck(USER2, "home", public=public))
        self.assertFalse(permissions.sees_deck(USER2, "user3", public=public))
        self.assertEqual(permissions.deck_spaces(USER2, public=public), ["home", "user2"])
        self.assertEqual(permissions.deck_spaces(None, public=public), ["home"])
        self.assertFalse(permissions.sees_deck(USER2, "home", public=public, home_only=True))
        self.assertTrue(permissions.sees_deck(USER1, "home", public=public, home_only=True))
        self.assertTrue(permissions.sees_deck(None, "home", script=True, home_only=True))

    def test_guard_reads_the_space_from_an_id_a_summary_or_a_deck_file(self):
        summary = decks.find_summary(R_DECK)
        for target in (R_DECK, summary, {"space": "user2"}, {"id": R_DECK, "space": "home"}):
            with self.subTest(target=target if isinstance(target, str) else sorted(target)):
                self.assertTrue(guard.sees_deck(target, USER2))
                self.assertFalse(guard.sees_deck(target, MATT))
        for target in ("product/fdc-test-precon", "pairing/cats+vampires", HOME_DECK):
            with self.subTest(target=target):
                self.assertTrue(guard.sees_deck(target, USER1))
                self.assertFalse(guard.sees_deck(target, USER2))
        self.assertFalse(guard.sees_deck("not a deck id", MATT))
        self.assertTrue(guard.sees_deck("not a deck id", None))     # outside a request: a script
        with _as("user2"):                                        # the viewer, when left out
            self.assertTrue(guard.sees_deck(R_DECK))
            self.assertFalse(guard.sees_deck(HOME_DECK))
            self.assertFalse(guard.sees_deck(HOME_DECK, None))      # naming nobody through the tunnel
        with _as("stranger"):                                       # a login that isn't set up
            self.assertFalse(guard.sees_deck(R_DECK))

    def test_an_ordered_products_decks_stay_home_even_when_homes_are_public(self):
        # The sandbox's precon is preordered (test_api's STATUS); the Beginner Box is owned.
        self.assertIn("fdc-test-precon.csv,preordered,", (self.box.magic / "products" / "status.csv").read_text(
            encoding="utf-8"))
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            self.assertTrue(guard.sees_deck("pairing/cats+vampires", USER2))
            self.assertFalse(guard.sees_deck("product/fdc-test-precon", USER2))
            self.assertTrue(guard.sees_deck(HOME_DECK, USER2))
            self.assertTrue(guard.sees_deck("product/fdc-test-precon", USER1))

    def test_hidden_deck_names_whose_it_was(self):
        self.assertEqual(guard.hidden_deck(R_DECK), "one of User2's decks")
        self.assertEqual(guard.hidden_deck("product/fdc-test-precon"), "one of the home decks")
        self.assertEqual(guard.hidden_deck("nonsense"), "a deck")


class LibraryTests(PermissionTestCase):

    def ids(self, who):
        with _as(who):
            return [d["id"] for d in api.decks_index()["decks"]]

    def test_a_member_gets_only_his_own_decks(self):
        with _as("user2"):
            index = api.decks_index()
        self.assertEqual([d["id"] for d in index["decks"]], [R_DECK])
        self.assertEqual(index["halves"], [])                       # no product deck, no pairing
        self.assertEqual(index["usual_opponents"], {})
        shown = json.dumps(index)
        for hidden in ("Gruul", "Elf Commander", "product/", "pairing/", "fdc-test-precon"):
            self.assertNotIn(hidden, shown)

    def test_home_profiles_get_homes_decks_and_products_and_the_admin_no_more(self):
        for who in ("matt", "user1"):
            with self.subTest(who=who):
                ids = self.ids(who)
                self.assertIn(HOME_DECK, ids)
                self.assertIn("product/fdc-test-precon", ids)
                self.assertNotIn(R_DECK, ids)
                self.assertFalse([i for i in ids if i.startswith("user2/")])
        with _as("matt"):
            self.assertTrue(api.decks_index()["halves"])
        # A script still lists every space's.
        self.assertIn(R_DECK, [d["id"] for d in api.decks_index()["decks"]])

    def test_nobody_named_but_not_a_script_gets_no_deck(self):
        with access.using(None), access.viewing(None), access.answering(False):
            index = api.decks_index()
        self.assertEqual((index["decks"], index["halves"]), ([], []))

    def test_decks_revision_is_the_viewers_own(self):
        with _as("user2"):
            before = api.decks_index()["decks_revision"]
        with _as("matt"):
            home_before = api.decks_index()["decks_revision"]
        self.assertNotEqual(before, home_before)
        # A home deck saved: home's revision moves, User2's doesn't.
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        path.write_text(path.read_text(encoding="utf-8").replace("# Gruul Test", "# Gruul Test Again", 1),
                        encoding="utf-8")
        with _as("user2"):
            self.assertEqual(api.decks_index()["decks_revision"], before)
        with _as("matt"):
            self.assertNotEqual(api.decks_index()["decks_revision"], home_before)


class PageTests(PermissionTestCase):

    def missing_answer(self, call, deck_id):
        with self.assertRaises(api.ApiError) as caught:
            call(deck_id)
        return caught.exception.status, caught.exception.message, caught.exception.extra

    def test_a_hidden_deck_answers_word_for_word_as_a_missing_one(self):
        reads = {"deck": api.deck_view, "edit": api.edit_view, "cards": cover.cover_cards,
                 "opponents": opponents.opponents_view, "goldfish": lambda deck_id: practice.goldfish(deck_id)}
        cases = (("user2", HOME_DECK, "casual/no-such-deck"),
                 ("user2", "product/fdc-test-precon", "product/no-such-product"),
                 ("user2", "commander/elf-commander", "commander/no-such-deck"),
                 ("matt", R_DECK, "user2/casual/no-such-deck"),
                 ("user1", R_DECK, "user2/casual/no-such-deck"))
        for name, call in reads.items():
            for who, hidden, missing in cases:
                with self.subTest(read=name, who=who, deck=hidden), _as(who):
                    status, message, data = self.missing_answer(call, hidden)
                    self.assertEqual(status, 404)
                    self.assertEqual(message, f"No deck {hidden!r}")
                    gone = self.missing_answer(call, missing)
                    self.assertEqual((status, message.replace(hidden, missing), data), gone)

    def test_the_owner_still_reads_it(self):
        with _as("user2"):
            self.assertEqual(api.deck_view(R_DECK)["summary"]["id"], R_DECK)
            self.assertEqual(api.edit_view(R_DECK)["id"], R_DECK)
            self.assertEqual(opponents.opponents_view(R_DECK)["id"], R_DECK)
        with _as("user1"):
            self.assertEqual(api.deck_view(HOME_DECK)["summary"]["id"], HOME_DECK)
            self.assertEqual(api.deck_view("product/fdc-test-precon")["summary"]["id"], "product/fdc-test-precon")

    def test_a_visible_decks_page_names_no_hidden_deck(self):
        with _as("matt"):
            view = api.deck_view(HOME_DECK)
        self.assertNotIn("user2/", json.dumps(view["usual_opponents"]))


class StaleTablesTests(PermissionTestCase):
    """GET /api/tables/stale and a save's stale_tables (commits._stale_list) list only the
    decks the viewer sees, even where the admin sees that space's inventory."""

    LISTED = [{"id": deck_id, "title": deck_id, "sha256": "0" * 64, "count": 1, "changes": []}
              for deck_id in (HOME_DECK, R_DECK)]
    BLOCKED = {"decks": [{"id": deck_id, "title": deck_id, "space": space, "reason": "no_table",
                          "version": None, "cards": [], "why": "It has no table."}
                         for deck_id, space in (("casual/other-test", "home"), ("user2/casual/r-other", "user2"))],
               "spaces": []}

    def view(self):
        with mock.patch.object(pool, "stale_tables", return_value=[dict(e) for e in self.LISTED]),                 mock.patch.object(pool, "table_blockers", return_value=json.loads(json.dumps(self.BLOCKED))):
            return api.stale_view()

    def test_the_admin_isnt_shown_a_persons_stale_or_blocked_decks(self):
        for who, stale, blocked in (("matt", [HOME_DECK], ["casual/other-test"]),
                                    ("user2", [R_DECK], ["user2/casual/r-other"])):
            with self.subTest(who=who), _as(who):
                answer = self.view()
                self.assertEqual([e["id"] for e in answer["stale"]], stale)
                self.assertEqual([e["id"] for e in answer["blocked"]], blocked)
                self.assertNotIn("r-elves" if who == "matt" else "gruul-test", json.dumps(answer))
        with access.viewing(None):                                  # a script: every one
            answer = self.view()
        self.assertEqual([e["id"] for e in answer["stale"]], [HOME_DECK, R_DECK])
        self.assertEqual(len(answer["blocked"]), 2)

    def test_a_saves_stale_tables_follow_the_same_rule(self):
        with _as("matt"), mock.patch.object(pool, "stale_tables", return_value=[dict(e) for e in self.LISTED]):
            self.assertEqual([e["id"] for e in api.saving._stale_list(object())], [HOME_DECK])


class PlayAndVisitsTests(PermissionTestCase):

    def test_the_game_log_offers_only_visible_decks(self):
        from decklab.lib.api import play_records
        with _as("user2"):
            answer = play_records.play_overview()
        self.assertEqual(set(answer["decks"]), {R_DECK})
        self.assertEqual({item["id"] for item in answer["lists"]}, {R_DECK})
        with _as("matt"):
            answer = play_records.play_overview()
        self.assertNotIn(R_DECK, answer["decks"])
        self.assertIn(HOME_DECK, answer["decks"])

    def test_the_beacon_keeps_no_id_of_a_hidden_deck(self):
        from decklab.tests.test_visits import recorder
        rec = recorder()
        self.addCleanup(visits.use(rec))
        body = lambda deck_id: json.dumps({"route": "deck", "deck": deck_id}).encode()     # noqa: E731
        with mock.patch.object(visits_api, "deck_exists", return_value=True), _as("user2"):
            self.assertTrue(visits_api.beacon(body(HOME_DECK))["recorded"])
            self.assertTrue(visits_api.beacon(body(R_DECK))["recorded"])
        self.assertEqual({key[4] for key in rec.pending()[1]}, {"", R_DECK})

    def test_the_visits_panel_names_a_hidden_deck_only_by_whose_it_is(self):
        from datetime import date, datetime, timezone
        at = datetime(2026, 10, 18, 9, 0, tzinfo=timezone.utc)
        seen = [{"profile": "user2", "first_seen": date(2026, 10, 18), "last_seen": at, "last_channel": "remote",
                 "days": 1, "requests": 3,
                 "recent": [{"route": "deck", "deck": R_DECK, "at": at}, {"route": "deck", "deck": HOME_DECK, "at": at}],
                 "often": [{"route": "deck", "deck": R_DECK, "opens": 2}]}]
        with mock.patch.object(visits_api, "_read", return_value=seen), \
                mock.patch.object(visits.recorder(), "flush"), _as("matt"):
            answer = visits_api.visits_view()
        user2 = next(p for p in answer["people"] if p["profile"] == "user2")
        self.assertEqual([(p["deck"], p["title"]) for p in user2["recent"]],
                         [(None, "one of User2's decks"), (HOME_DECK, "Gruul Test")])
        self.assertEqual(user2["often"][0]["deck"], None)
        self.assertNotIn(R_DECK, json.dumps(answer))
        self.assertNotIn("User2 Elves", json.dumps(answer))
        # A script (the command line's view) still names it.
        with mock.patch.object(visits_api, "_read", return_value=seen), mock.patch.object(visits.recorder(), "flush"):
            answer = visits_api.visits_view()
        user2 = next(p for p in answer["people"] if p["profile"] == "user2")
        self.assertEqual(user2["recent"][0]["deck"], R_DECK)

    def test_the_visits_panel_never_counts_a_spaces_hidden_decks(self):
        # Two of User2's private decks are one "one of User2's decks" row each list: opens summed
        # and the newest time kept, so Matt can't tell how many of them User2 opened.
        from datetime import date, datetime, timezone
        early, late = (datetime(2026, 10, 18, h, 0, tzinfo=timezone.utc) for h in (8, 9))
        other = "user2/casual/r-goblins"
        seen = [{"profile": "user2", "first_seen": date(2026, 10, 18), "last_seen": late,
                 "last_channel": "remote", "days": 1, "requests": 5,
                 "recent": [{"route": "deck", "deck": R_DECK, "at": early}, {"route": "deck", "deck": other, "at": late},
                            {"route": "library", "deck": None, "at": early}],
                 "often": [{"route": "library", "deck": None, "opens": 4}, {"route": "deck", "deck": R_DECK, "opens": 3},
                           {"route": "deck", "deck": other, "opens": 2}]}]
        with mock.patch.object(visits_api, "_read", return_value=seen), \
                mock.patch.object(visits.recorder(), "flush"), _as("matt"):
            answer = visits_api.visits_view()
        user2 = next(p for p in answer["people"] if p["profile"] == "user2")
        self.assertEqual([(p["route"], p["title"], p["opens"]) for p in user2["often"]],
                         [("deck", "one of User2's decks", 5), ("library", None, 4)])
        self.assertEqual([(p["route"], p["title"]) for p in user2["recent"]],
                         [("deck", "one of User2's decks"), ("library", None)])
        self.assertEqual(user2["recent"][0]["at"], late.astimezone().isoformat(timespec="seconds"))
        self.assertNotIn("goblins", json.dumps(answer))
