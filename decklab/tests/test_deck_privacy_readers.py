"""E10-S30, phase 2's half (b): a deck is seen only in its own space (guard.sees_deck, until
E10-S28's switches), and every reader that doesn't go through the library's _find_summary, every
write route and the Forge answers ask it, so a deck someone may not see answers exactly as a
missing one (404 "No deck <id>"), checked before any 403 or 409.

- RuleTests: guard.sees_deck's targets and deck_reader (test_deck_visibility.py has the pure rule).
- ReaderTests: history and revisions (a retired deck's too, by its former space), opponents, the
  rename and retirement previews and the variant tests of a hidden deck answer as a missing one.
- WriteOracleTests: save, cover, check, tables/update, rename, retire, restore and the opponents
  save of a hidden deck, existing, retired or never there: the same 404 with nothing else, and
  without its revisions being read.
- StaleTablesTests: the "Tables out of date" list and a save's stale_tables hold only decks the
  viewer sees, so an admin's Update all never posts (and 404s on) another space's deck.
- ForgeFilterTests: GET /api/matchups (and ?running=1) and /api/matchup only with results and runs
  whose every side the viewer sees, names from other spaces as "someone", an admin's anonymous
  items, only an admin stopping a run, and a field run or test of another space's deck with the
  same list (its job, last run and budgets, and the via of a matchup it plays) never shown.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_deck_privacy_readers
"""
import json
import types
from unittest import mock

from decklab.lib import access, api, inventory, jobs, permissions, state
from decklab.lib.api import commits, cover, field_page, forge_runs, guard, history, opponents, rename, retirement
from decklab.lib.api import variant_page
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api import GRUUL, _write
from decklab.tests.test_api_permissions import R_DECK, PermissionTestCase
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_history import WHEN, install, revision
from decklab.tests.test_matchups_api import GRUUL_ID, MatchupTestCase, body

MATT = {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"}
USER1 = {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"}
USER2 = {"id": "user2", "name": "User2", "role": "member", "space": "user2"}
RETIRED = "casual/retired-test"
MISSING = "casual/never-was"
R_DECK_ID = "user2/casual/r-elves"


def _as(who):
    return access.using({"profile": who, "email": "", "remote": True})


class RuleTests(PermissionTestCase):

    def test_own_space_only_whatever_the_role(self):
        cases = ((MATT, "casual/gruul-test", True), (MATT, R_DECK_ID, False),     # no admin override
                 (USER1, "commander/elf-commander", True), (USER1, "product/fdc-test-precon", True),
                 (USER1, "pairing/cats+elves", True), (USER2, R_DECK_ID, True),
                 (USER2, "casual/gruul-test", False), (USER2, "product/fdc-test-precon", False),
                 (USER2, "pairing/cats+elves", False), (USER2, "user2/commander/gone", True),
                 (MATT, "not a deck id", False), (MATT, None, False))
        for profile, target, sees in cases:
            with self.subTest(profile=profile["id"], target=target):
                self.assertEqual(guard.sees_deck(target, profile), sees)
        # A deck (a library summary or a DeckFile) by its id's space, else its "space".
        self.assertTrue(guard.sees_deck({"id": "user2/casual/x", "space": "user2"}, USER2))
        self.assertTrue(guard.sees_deck({"space": "user2"}, USER2))
        self.assertFalse(guard.sees_deck({"id": "casual/x"}, USER2))
        self.assertTrue(guard.sees_deck(types.SimpleNamespace(space=None, deck_id=R_DECK_ID), USER2))
        # Naming nobody: a script sees every deck, anything else none.
        self.assertTrue(permissions.sees_deck(None, "user2", script=True))
        self.assertFalse(permissions.sees_deck(None, "home", script=False))

    def test_the_request_s_viewer(self):
        with _as("user2"):
            self.assertTrue(guard.sees_deck(R_DECK_ID))
            self.assertFalse(guard.sees_deck("casual/gruul-test"))
            sees = guard.deck_reader()
            self.assertEqual([sees(d) for d in (R_DECK_ID, "casual/gruul-test")], [True, False])
            self.assertTrue(guard.sees_deck("casual/gruul-test", MATT))     # for another profile
        with _as("nobody-set-up"):                  # a login config.json doesn't list sees none
            self.assertFalse(guard.sees_deck(R_DECK_ID))
        with access.using(None), access.viewing("matt"):
            self.assertFalse(guard.sees_deck(R_DECK_ID))
        self.assertTrue(guard.sees_deck(R_DECK_ID))         # a script (a test) sees every deck
        error = guard.no_deck("casual/x")
        self.assertEqual((error.status, error.message, error.extra), (404, "No deck 'casual/x'", {}))


class _Hidden(PermissionTestCase):
    """The sandbox with a retired home deck (its history kept) besides the live ones."""

    def setUp(self):
        super().setUp()
        text = GRUUL.replace("# Gruul Test", "# Retired Test")
        self.backend = install(self.box, {RETIRED: [
            revision(RETIRED, 1, text, op="A", actor="user1", message="Add it"),
            revision(RETIRED, 2, None, op="D", actor="user1", message="Retire it", at=WHEN)]})

    def error(self, who, call, *args):
        """(status, message with the deck id as <id>, extra) of call(*args) as who; None for no error."""
        with _as(who):
            try:
                call(*args)
            except api.ApiError as e:
                message = e.message
                for deck_id in sorted((a for a in args if isinstance(a, str) and "/" in a), key=len, reverse=True):
                    message = message.replace(deck_id, "<id>")
                return e.status, message, e.extra
        return None

    def same_as_missing(self, who, call, hidden, missing, *rest):
        got = self.error(who, call, hidden, *rest)
        self.assertEqual(got, (404, "No deck '<id>'", {}), (who, hidden))
        self.assertEqual(got, self.error(who, call, missing, *rest), (who, hidden, missing))


class ReaderTests(_Hidden):

    def setUp(self):
        super().setUp()
        # The sandbox has no variant tests (501); with them the deck is asked about before anything else.
        built = mock.patch.object(variant_page, "_forge", return_value=types.SimpleNamespace())
        built.start()
        self.addCleanup(built.stop)

    def readers(self):
        return ((history.deck_history,), (history.deck_revision, "1"), (history.deck_revision, "999"),
                (history.deck_revision, "1", "owned"), (history.retired_record,), (opponents.opponents_view,),
                (rename.rename_view,), (retirement.retirement_view,), (api.variant_tests,), (api.goldfish,),
                (api.field_view,), (cover.cover_cards,))

    def test_a_home_deck_is_a_missing_one_to_user2(self):
        for call, *rest in self.readers():
            for hidden in ("casual/gruul-test", RETIRED):
                if call in (history.retired_record,) and hidden != RETIRED:
                    continue
                with self.subTest(call=call.__name__, deck=hidden, rest=rest):
                    self.same_as_missing("user2", call, hidden, MISSING, *rest)

    def test_user2_s_deck_is_a_missing_one_to_matt_the_admin(self):
        for call, *rest in self.readers():
            if call is history.retired_record:
                continue
            with self.subTest(call=call.__name__, rest=rest):
                self.same_as_missing("matt", call, R_DECK_ID, "user2/casual/never-was", *rest)

    def test_who_may_see_it_still_reads_it(self):
        with _as("user1"):
            self.assertTrue(history.deck_history(RETIRED)["retired"])
            self.assertEqual(history.deck_revision(RETIRED, "1")["title"], "Retired Test")
            self.assertEqual(rename.rename_view("casual/gruul-test")["id"], "casual/gruul-test")
            self.assertEqual(retirement.retirement_view("casual/gruul-test")["id"], "casual/gruul-test")
            self.assertEqual(opponents.opponents_view("casual/gruul-test")["id"], "casual/gruul-test")
        with _as("user2"):
            self.assertEqual(history.deck_history(R_DECK_ID)["id"], R_DECK_ID)

    def test_the_revision_isnt_looked_up_for_a_deck_it_may_not_see(self):
        with mock.patch.object(inventory, "deck_revision", side_effect=AssertionError("looked up")), \
                mock.patch.object(inventory, "deck_revisions", side_effect=AssertionError("looked up")), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("looked up")):
            for number in ("1", "999", "a" * 40):
                self.same_as_missing("user2", history.deck_revision, RETIRED, MISSING, number)

    def test_a_hidden_variant_test_is_no_test(self):
        found = {"test": {"base": {"id": "casual/gruul-test"}, "against": {"id": R_DECK_ID}, "opponents": []}}
        seen = forge_runs._Seen(USER1)
        self.assertFalse(variant_page._sees_test(found["test"], seen))
        self.assertTrue(variant_page._sees_test(dict(found["test"], against="field:Constructed"), seen))
        self.assertTrue(variant_page._sees_test(dict(found["test"], against="field:Constructed",
                                                      opponents=[{"id": R_DECK_ID}]), seen))
        self.assertTrue(variant_page._sees_test(found["test"], forge_runs._Seen(None)))     # a script


class WriteOracleTests(_Hidden):

    def body(self, profile, **data):
        return json.dumps({"profile": profile, **data}).encode("utf-8")

    def writes(self, profile):
        sha = "0" * 64
        return (
            ("save", lambda d: api.save_deck(self.body(profile, id=d, sha256=sha))),
            ("cover", lambda d: cover.save_cover(self.body(profile, id=d, expect=sha, cover={"name": "Forest"}))),
            ("check", lambda d: api.check_draft(self.body(profile, id=d))),
            ("check with a sha", lambda d: api.check_draft(self.body(profile, id=d, sha256=sha))),
            ("tables", lambda d: api.update_tables(self.body(profile, decks=[{"id": d, "sha256": sha}]))),
            ("rename", lambda d: rename.preview_rename(self.body(profile, id=d, title="New Name", sha256=sha,
                                                                 revision=1))),
            ("retire", lambda d: retirement.retire_deck(self.body(profile, id=d, sha256=sha, revision=1,
                                                                  reason="Done with it"))),
            ("restore", lambda d: retirement.restore_deck(self.body(profile, id=d, retired_revision=2))),
            ("opponents", lambda d: opponents.save_opponents(self.body(profile, id=d, sha256=sha, opponents=[]))),
        )

    def test_a_home_deck_is_a_missing_one_whatever_user2_writes(self):
        # Never a 403, a 409 or a title: and the deck's revisions (who changed it, when) aren't read.
        with mock.patch.object(commits, "_last_revision", side_effect=AssertionError("revisions read")), \
                mock.patch.object(inventory, "apply", side_effect=AssertionError("written")):
            for name, call in self.writes("user2"):
                for hidden in ("casual/gruul-test", "commander/elf-commander", RETIRED, MISSING):
                    with self.subTest(write=name, deck=hidden):
                        self.assertEqual(self.error("user2", call, hidden), (404, "No deck '<id>'", {}))

    def test_user2_s_deck_is_a_missing_one_to_matt(self):
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("written")):
            for name, call in self.writes("matt"):
                with self.subTest(write=name):
                    self.assertEqual(self.error("matt", call, R_DECK_ID), (404, "No deck '<id>'", {}))

    def test_a_missing_deck_answers_the_same_to_who_sees_its_space(self):
        with mock.patch.object(inventory, "apply", side_effect=AssertionError("written")):
            for name, call in self.writes("user1"):
                with self.subTest(write=name):
                    self.assertEqual(self.error("user1", call, MISSING), (404, "No deck '<id>'", {}))

    def test_a_visible_deck_still_gets_its_403(self):
        with _as("user1"):
            self.assertApiError(403, api.save_deck, self.body("user1", id="casual/gruul-test", sha256="0" * 64))


class ForgeFilterTests(MatchupTestCase):
    """The coarse Forge filter (E10-S30), in test_matchups_api's sandbox with test_api_permissions'
    profiles (Matt an admin, User1 a home member, User2 with his own space and deck)."""

    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        _write(box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", R_DECK)
        _write(box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n")
        self.addCleanup(inventory.use(FileInventory(box.root)))
        box.state = MemoryStore(mode="everyone")
        self.addCleanup(state.use(box.state))

    def test_a_home_result_reaches_only_home(self):
        key = self.play()["key"]
        self.finish()
        with _as("user1"):
            listed = api.matchups()
            self.assertEqual([r["key"] for r in listed["results"]], [key])
            self.assertEqual(listed["results"][0]["by"], "Matt")
            self.assertEqual(api.matchup(key=key)["key"], key)
        for who in ("user2",):
            with _as(who):
                self.assertEqual(api.matchups()["results"], [])
                self.assertApiError(404, api.matchup, None, None, None, None, key,
                                    contains=forge_runs.MATCHUP_NO_KEY)
                self.assertApiError(404, api.matchup, GRUUL_ID, "target", GRUUL_ID, "owned",
                                    contains=f"No deck {GRUUL_ID!r}")

    def test_running_items_are_filtered_and_an_admin_s_are_anonymous(self):
        self.playing()
        key = self.play(R_DECK_ID, "target", R_DECK_ID, "target", profile="user2")["key"]
        self.assertTrue(self.forge.started.wait(5))
        with _as("user2"):
            mine = api.matchups(running=True)["running"]
        self.assertEqual([(r["key"], r["by"], r["sides"][0]["id"]) for r in mine], [(key, "User2", R_DECK_ID)])
        with _as("user1"):
            self.assertEqual(api.matchups(running=True)["running"], [])
            self.assertEqual(api.matchups()["running"], [])
        with _as("matt"):
            item, = api.matchups(running=True)["running"]
            self.assertEqual(item, {"key": key, "kind": "matchup", "title": "A run of one of User2's decks", "by": "someone",
                                    "done": item["done"], "total": item["total"], "link": None,
                                    "status": item["status"], "ahead": item["ahead"], "sides": None, "hidden": True,
                                    "may_stop": True})
            self.assertNotIn(R_DECK_ID, json.dumps(item))
        # Its own space may stop it; an admin may stop an anonymous system item too.
        with _as("user2"):
            self.assertTrue(api.matchups(running=True)["running"][0]["may_stop"])
        with _as("matt"):
            answer = api.stop_matchup(body(profile="matt", key=key))
        self.assertEqual(answer, {"key": key, "stopped": True, "hidden": True})
        self.finish()
        with _as("user2"):            # who stopped it is in another space: "someone"
            notice = api.matchup(key=key)["notice"]
        self.assertIn("by someone", notice)
        self.assertNotIn("Matt", notice)

    def test_names_from_other_spaces_are_someone(self):
        with _as("user1"):
            seen = forge_runs._Seen()
        answer = {"by": "User2", "runs": [{"by": "Matt", "stopped_by": "User3"}], "job": {"cancelled_by": "User5"},
                  "title": "User2"}
        self.assertEqual(seen.mask(answer), {"by": "someone", "runs": [{"by": "Matt", "stopped_by": "someone"}],
                                             "job": {"cancelled_by": "someone"}, "title": "User2"})
        self.assertEqual(forge_runs._Seen(None).mask(answer), answer)       # a script is told every name

    def test_the_field_shows_only_the_opponents_it_sees(self):
        found = {"opponents": [{"id": GRUUL_ID, "games": 300}, {"id": R_DECK_ID, "games": 10}],
                 "average": {"value": 0.5}, "rating": {"value": 1}, "notes": ["Not rated against Elves"],
                 "coverage": {"with_floor": 1, "of": 2}}
        fields = [{"id": GRUUL_ID}, {"id": "product/fdc-test-precon"}, {"id": R_DECK_ID}]
        out, lists, whole = field_page._seen_field(found, fields, forge_runs._Seen(USER1))
        self.assertEqual([o["id"] for o in out["opponents"]], [GRUUL_ID])
        self.assertEqual((out["average"], out["rating"], out["notes"], out["coverage"], whole),
                         (None, None, [], {"with_floor": 1, "of": 1}, False))
        self.assertEqual([e["id"] for e in lists], [GRUUL_ID, "product/fdc-test-precon"])
        home = dict(found, opponents=found["opponents"][:1])
        out, lists, whole = field_page._seen_field(home, fields[:2], forge_runs._Seen(MATT))
        self.assertIs(out, home)                    # nothing left out: as it was
        self.assertTrue(whole)
        out, lists, whole = field_page._seen_field(found, fields, forge_runs._Seen(USER2))
        self.assertEqual(([o["id"] for o in out["opponents"]], [e["id"] for e in lists]), ([R_DECK_ID], [R_DECK_ID]))

    def test_a_last_run_of_another_space_s_deck_isnt_shown(self):
        # The last run's note is kept by the list's card_sha: a home deck's, for User2's copy of its list.
        last = {"deck": {"id": GRUUL_ID, "title": "Gruul Test"}, "per_opponent": {"k": 4}, "dropped": {}}
        found = {"opponents": [{"id": R_DECK_ID, "games": 4}], "last_run": last, "notes": []}
        out, _, whole = field_page._seen_field(found, [], forge_runs._Seen(USER2))
        self.assertEqual((out["last_run"], whole), (None, True))
        out, _, _ = field_page._seen_field(found, [], forge_runs._Seen(USER1))   # every opponent hidden
        self.assertIsNone(out["last_run"])
        mine = dict(found, last_run=dict(last, deck={"id": R_DECK_ID, "title": "User2 Elves"}))
        out, _, _ = field_page._seen_field(mine, [], forge_runs._Seen(USER2))
        self.assertEqual(out["last_run"]["deck"]["id"], R_DECK_ID)

    def field_answer(self, who, entry_id, opponents):
        """field_page._answer as who, for a deck entry_id whose list (card_sha) a home field run of
        Gruul Test is playing, against a field of opponents."""
        detail = {"deck": {"id": GRUUL_ID, "title": "Gruul Test"}, "pairs": {"k": {"opponent": {"id": GRUUL_ID}}}}
        job = types.SimpleNamespace(key="field:" + "a" * 64 + ":Constructed", cancelled_by=None,
                                    fn=types.SimpleNamespace(entry={"id": GRUUL_ID, "title": "Gruul Test"}, by="Matt"))
        snap = {"status": jobs.RUNNING, "detail": detail, "ahead": 0, "progress": {"done": 1, "total": 2},
                "seconds": 3, "error": None}
        found = {"deck": {"id": entry_id}, "format": "Constructed",
                 "opponents": [{"id": o, "games": 0} for o in opponents],
                 "last_run": {"deck": {"id": GRUUL_ID, "title": "Gruul Test"}}, "notes": []}
        planned = {"pairs": [], "per_opponent": 5, "new_games": 5 * len(opponents)}
        forge = types.SimpleNamespace(
            field=types.SimpleNamespace(view=lambda e, **kw: found, field_lists=lambda fmt, **kw: [], BUDGETS=("quick",),
                                        plan=lambda e, b, **kw: planned),
            estimate=types.SimpleNamespace(minutes=lambda pairs: (1, 2)), ForgeError=ValueError,
            fmt_for=lambda kind: "Constructed", page_kind=lambda deck_id: "casual", status=lambda: {"ready": True})
        entry = {"id": entry_id, "card_sha": "a" * 64, "kind": "casual", "title": "Copy", "version": "target"}
        with mock.patch.object(forge_runs.COORD_JOBS, "get", return_value=job), \
                mock.patch.object(forge_runs.COORD_JOBS, "snapshot", return_value=snap), _as(who):
            return field_page._answer(forge, {"id": entry_id}, entry)

    def test_a_field_run_of_the_same_list_in_another_space_isnt_shown(self):
        out = self.field_answer("user2", R_DECK_ID, [R_DECK_ID])
        self.assertEqual((out["status"], out["job"], out["last_run"]), ("none", None, None))
        self.assertNotIn("Gruul", json.dumps(out))
        self.assertEqual(out["budgets"]["quick"]["new_games"], 5)          # his own field: its budgets
        out = self.field_answer("user1", GRUUL_ID, [GRUUL_ID])            # home's own run: as it was
        self.assertEqual((out["status"], out["job"]["deck"]["id"]), (jobs.RUNNING, GRUUL_ID))
        self.assertEqual(out["last_run"]["deck"]["id"], GRUUL_ID)

    def test_a_hidden_field_s_budgets_arent_given(self):
        # Planned over every opponent, the budgets would tell how many decks the hidden field has.
        out = self.field_answer("user2", R_DECK_ID, [GRUUL_ID, "casual/other"])
        self.assertEqual((out["opponents"], out["budgets"]), ([], {}))

    def stop_field(self, who, deck_id, job_deck):
        """(answer or ApiError, cancels) of POST /api/field/stop as who for deck_id, while a field
        run of job_deck (the same list: one card_sha, so one key) plays."""
        cancels = []
        job = types.SimpleNamespace(key="k", cancelled_by=None, wait=lambda seconds: True,
                                    fn=types.SimpleNamespace(entry={"id": job_deck, "title": "Elves"}, by="Matt"))
        snap = {"status": jobs.RUNNING, "detail": {"deck": {"id": job_deck}, "pairs": {}}, "ahead": 0,
                "progress": {"done": 1, "total": 2}, "seconds": 3, "error": None}
        forge = types.SimpleNamespace(
            field=types.SimpleNamespace(view=lambda e, **kw: {"opponents": [], "format": "Constructed", "notes": []},
                                        field_lists=lambda fmt, **kw: [], BUDGETS=("quick",),
                                        plan=lambda e, b, **kw: {"pairs": [], "per_opponent": 5, "new_games": 0}),
            estimate=types.SimpleNamespace(minutes=lambda pairs: (1, 2)), ForgeError=ValueError,
            fmt_for=lambda kind: "Constructed", page_kind=lambda d: "casual", status=lambda: {"ready": True})
        entry = {"id": deck_id, "card_sha": "a" * 64, "kind": "casual", "title": "Elves", "version": "target"}
        with mock.patch.object(forge_runs, "_forge_module", return_value=forge),                 mock.patch.object(field_page, "_field_entry", return_value=({"id": deck_id}, entry)),                 mock.patch.object(field_page, "job_key", return_value="k"),                 mock.patch.object(forge_runs.COORD_JOBS, "get", return_value=job if guard._target_deck(deck_id)[1] == guard._target_deck(job_deck)[1] else None),                 mock.patch.object(forge_runs.COORD_JOBS, "snapshot", return_value=snap),                 mock.patch.object(forge_runs.COORD_JOBS, "cancel",
                                  side_effect=lambda key, by: cancels.append((key, by)) or True), _as(who):
            try:
                return field_page.stop_field(body(profile=who, id=deck_id)), cancels
            except api.ApiError as e:
                return e, cancels

    def test_an_admin_stops_a_field_run_by_a_deck_he_sees_only(self):
        answer, cancels = self.stop_field("matt", GRUUL_ID, GRUUL_ID)
        self.assertNotIsInstance(answer, api.ApiError)
        self.assertEqual(cancels, [("k", "Matt")])
        # User2's deck is a missing one to Matt the admin: the same 404, nothing stopped.
        error, cancels = self.stop_field("matt", R_DECK_ID, R_DECK_ID)
        missing = guard.no_deck(R_DECK_ID)
        self.assertEqual((error.status, error.message, error.extra, cancels),
                         (missing.status, missing.message, missing.extra, []))
        # His own deck, but the run playing its list is another space's: not stopped from here.
        answer, cancels = self.stop_field("matt", GRUUL_ID, R_DECK_ID)
        self.assertNotIsInstance(answer, api.ApiError)
        self.assertEqual((cancels, answer["job"], answer["status"]), ([], None, "none"))
        # A member can stop a run of its own space; a hidden deck's 404 still comes first.
        answer, cancels = self.stop_field("user1", GRUUL_ID, GRUUL_ID)
        self.assertNotIsInstance(answer, api.ApiError)
        self.assertEqual(cancels, [("k", "User1")])
        error, _ = self.stop_field("user1", R_DECK_ID, R_DECK_ID)
        self.assertEqual(error.status, 404)

    def test_a_matchup_played_by_a_hidden_coordinator_doesnt_name_it(self):
        via = {"kind": "field", "job": "field:" + "a" * 64 + ":Constructed", "title": "Field run of Gruul Test",
               "link": f"#/deck?id={GRUUL_ID}&v=target&part=field", "by": "Matt"}
        found = {"pair": {"done": 2, "wins": 1, "other": 0, "total": 4}, "snap": {"seconds": 1}, "deck_sha": None,
                 "via": via}
        shown = forge_runs._coord_progress(found, "b" * 64)
        self.assertEqual((shown["via"], shown["by"]), (via, "Matt"))
        hidden = forge_runs._coord_progress(found, "b" * 64, shown=False)
        self.assertEqual((hidden["done"], hidden["wins"], hidden["by"]), (2, [1, 1], "someone"))
        self.assertEqual(hidden["via"], {"kind": None, "job": None, "title": None, "link": None, "by": "someone"})
        self.assertNotIn("Gruul", json.dumps(hidden))


class StaleTablesTests(_Hidden):
    """User2's deck (R_DECK: no owned-vs-needed table, so deck tables can't update it) and the
    same deck with a stale table, as Matt the admin and User2 see the Tables out of date list."""

    STALE = R_DECK.rstrip() + """

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
| Llanowar Elves | 4 | 4 | 0 | | | |
"""

    def ids(self, who):
        with _as(who):
            out = api.stale_view()
        return [e["id"] for e in out["stale"]], [e["id"] for e in out["blocked"]], out

    def test_a_deck_matt_may_not_see_isnt_blocked_for_him(self):
        _, blocked, out = self.ids("matt")
        self.assertNotIn(R_DECK_ID, blocked)
        self.assertNotIn("User2 Elves", json.dumps(out))
        self.assertIn(R_DECK_ID, self.ids("user2")[1])

    def test_matt_s_update_all_leaves_out_and_doesnt_fail_on_user2_s_stale_deck(self):
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", self.STALE)
        self.assertIn(R_DECK_ID, self.ids("user2")[0])
        stale, _, out = self.ids("matt")
        self.assertNotIn(R_DECK_ID, stale)
        self.assertNotIn("User2 Elves", json.dumps(out))
        with _as("matt"):
            self.assertNotIn(R_DECK_ID, [e["id"] for e in commits._stale_list(api.library._load_pool([]))])
            posted = [{"id": e["id"], "sha256": e["sha256"]} for e in api.stale_view()["stale"] if e["may_update"]]
            if posted:              # Update all as the page posts it: no 404 for a deck he can't see
                answer = api.update_tables(json.dumps({"profile": "matt", "decks": posted}).encode("utf-8"))
                self.assertNotIn(R_DECK_ID, json.dumps(answer))

