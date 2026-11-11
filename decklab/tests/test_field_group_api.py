"""Tests for the deck page's group run API (E3-S31, closing E3-S19's criterion 2; api/field_group.py):
GET /api/field/group, POST /api/field/group/run and /stop, the group run's job in
api.forge_runs.COORD_JOBS (a field-run key, titled "Group run of" in the Running list) and the
privacy rules: a chosen deck the viewer can't see answers exactly as a missing deck, before any 403,
and the choices offer only visible decks (another space's only when its decks are Public).

They run in test_api_permissions' sandbox (roles, and User2's own space with one deck), with two
more home casual decks and a trial; its FakeForge stands in for decklab.lib.forge, FakeGroup for
forge.group and a one-line field part for forge.field's budgets. A run reports a pair record per
chosen deck and keeps reporting until its gate opens. No Forge game, network or database is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_field_group_api
"""
import contextlib
import json
import threading
import types
from unittest import mock

from decklab.lib import access, api, jobs
from decklab.lib import feature_routes
from decklab.lib.api import field_group, field_page, guard
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase

GRUUL, MONO, BLUE, TRIAL = "casual/gruul-test", "casual/mono-test", "casual/blue-test", "casual/trial-test"
R_ELVES, ELVES = "user2/casual/r-elves", "commander/elf-commander"
WAIT = 5
DECK = """# {title}

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** {status}
{extra}
## Decklist

```
Deck
4 {card}
20 Forest
```
"""


class FakeGroup:
    """forge.group's stand-in: check refuses the deck itself, view gives a row per chosen deck, run
    reports 50 of 200 games a pair until self.gate is set."""

    MAX_OPPONENTS = 3

    def __init__(self):
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()
        self.runs, self.keeps, self.games = [], [], 0

    def check(self, entry, chosen):
        if any(o["id"] == entry["id"] for o in chosen):
            raise ValueError(f"{entry['title']} can't be in its own group.")
        return list(chosen)

    def view(self, entry, chosen, keep=None):
        self.keeps.append(keep)
        opponents = [{"id": o["id"], "version": o["version"], "title": o["title"], "games": self.games,
                      "rate": {"value": 0.4, "low": 0.3, "high": 0.5} if self.games else None, "by": "Matt"}
                     for o in chosen]
        return {"opponents": opponents, "overall": {"key": "all", "rate": 0.4 if self.games else None},
                "played": len(chosen) if self.games else 0, "of": len(chosen), "tally": {}, "updated": None,
                "games": self.games * len(chosen), "note": f"These {len(chosen)} chosen decks only."}

    def run(self, entry, chosen, budget, *, by, progress, space, keep):
        self.runs.append((entry["id"], [o["id"] for o in chosen], budget, by, space))
        pairs = {f"k{i}": {"opponent": {"id": o["id"], "version": o["version"], "title": o["title"]},
                           "done": 50, "total": 200, "playing": True} for i, o in enumerate(chosen)}
        detail = {"budget": budget, "deck": {"id": entry["id"], "title": entry["title"]}, "pairs": pairs}
        progress(50, 200, detail)
        self.started.set()
        while not self.gate.wait(0.005):
            progress(50, 200, detail)
        self.games = 200
        return {"played": 200}


def body(profile, **data):
    return json.dumps({"profile": profile, **data}).encode("utf-8")


class GroupApiTestCase(PermissionTestCase):

    def setUp(self):
        super().setUp()
        decks_dir = self.box.magic / "decks" / "casual"
        _write(decks_dir / "mono-test.md", DECK.format(title="Mono Test", status="building", extra="",
                                                       card="Llanowar Elves"))
        _write(decks_dir / "blue-test.md", DECK.format(title="Blue Test", status="idea", extra="", card="Opt"))
        _write(decks_dir / "trial-test.md", DECK.format(title="Trial Test", status="idea",
                                                        extra="- **Trial:** precon BigElves_TST\n", card="Shock"))
        self.forge = self.box.forge
        self.g = FakeGroup()
        self.forge.group = self.g
        self.addCleanup(lambda: delattr(self.forge, "group"))
        plans = []
        self.plans = plans

        def plan(entry, budget, **options):
            plans.append(options)
            opps = options.get("opponent_entries") or []
            return {"per_opponent": 200, "new_games": 200 * len(opps),
                    "pairs": [{"opponent": o, "key": self.forge.matchup_key(entry, o), "games": 200} for o in opps]}
        old_field = getattr(self.forge, "field", None)
        self.forge.field = types.SimpleNamespace(BUDGETS=("quick", "standard", "thorough"), plan=plan)
        self.addCleanup(lambda: setattr(self.forge, "field", old_field) if old_field is not None
                        else delattr(self.forge, "field"))
        old_estimate = getattr(self.forge, "estimate", None)
        self.forge.estimate = types.SimpleNamespace(minutes=lambda pairs: (3.0, 5.0))
        self.addCleanup(lambda: setattr(self.forge, "estimate", old_estimate) if old_estimate is not None
                        else delattr(self.forge, "estimate"))
        runner = jobs.Runner(max_running=2, max_queued=4, log=lambda text: None,
                             describe=api.forge_runs._matchup_error, name="coordinator")
        patcher = mock.patch.object(api.forge_runs, "COORD_JOBS", runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.g.gate.set()
        for job in list(api.forge_runs.COORD_JOBS._jobs.values()):
            if not job.wait(WAIT):
                raise AssertionError(f"job {job.key} didn't finish")

    @contextlib.contextmanager
    def as_(self, who):
        with access.using({"profile": who, "email": "", "remote": True}):
            yield

    def call(self, who, function, *args, **kwargs):
        with self.as_(who):
            try:
                return function(*args, **kwargs)
            except api.ApiError as e:
                return e.status

    def error(self, who, function, *args):
        with self.as_(who), self.assertRaises(api.ApiError) as caught:
            function(*args)
        return caught.exception

    def set_mode(self, mode):
        with self.as_("matt"):
            return api.change_simulations(body("matt", mode=mode))

    def playing(self):
        self.g.gate.clear()
        self.g.started.clear()


class GroupViewTests(GroupApiTestCase):

    def test_choices_are_visible_decks_of_the_format(self):
        answer = self.call("matt", field_group.group_view, GRUUL, "target")
        ids = [c["id"] for c in answer["choices"]]
        # Not the deck itself, a trial, a broken deck, another format or another space's private deck.
        self.assertEqual(ids, [BLUE, MONO])
        self.assertEqual((answer["status"], answer["opponents"], answer["chosen"], answer["budgets"]),
                         ("none", [], [], {}))
        self.assertEqual(answer["max_opponents"], 3)
        self.assertFalse(any(c["public"] for c in answer["choices"]))
        member = self.call("user2", field_group.group_view, R_ELVES, "target")
        self.assertEqual(member["choices"], [])
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            member = self.call("user2", field_group.group_view, R_ELVES, "target")
        self.assertEqual([(c["id"], c["public"]) for c in member["choices"]],
                         [(BLUE, True), (GRUUL, True), (MONO, True)])

    def test_the_view_of_a_chosen_group(self):
        answer = self.call("matt", field_group.group_view, GRUUL, "target", f"{MONO},{BLUE}@target")
        self.assertEqual([o["id"] for o in answer["opponents"]], [MONO, BLUE])
        self.assertEqual(answer["chosen"], [{"id": MONO, "version": "target"}, {"id": BLUE, "version": "target"}])
        self.assertEqual(answer["budgets"]["standard"], {"games": 200, "new_games": 400, "minutes": [3.0, 5.0]})
        self.assertTrue(all(p.get("opponent_entries") for p in self.plans))
        self.assertIsNotNone(self.g.keeps[-1])          # the viewer's saved-result filter
        json.dumps(answer, allow_nan=False)

    def test_bad_choices(self):
        for opponents, status, words in (("casual/nope", 404, "No deck"), (TRIAL, 400, "trial of a precon"),
                                         (f"{MONO},{BLUE},{GRUUL},{TRIAL}", 400, "at most 3"),
                                         (f"{MONO}@built", 400, "version"), (GRUUL, 400, "its own group")):
            with self.subTest(opponents=opponents):
                e = self.error("matt", field_group.group_view, GRUUL, "target", opponents)
                self.assertEqual(e.status, status)
                self.assertIn(words, e.message)

    def test_a_hidden_deck_answers_as_a_missing_one(self):
        hidden = self.error("matt", field_group.group_view, GRUUL, "target", R_ELVES)
        missing = self.error("matt", field_group.group_view, GRUUL, "target", "user2/casual/nope")
        self.assertEqual((hidden.status, hidden.message.replace(R_ELVES, "X")),
                         (missing.status, missing.message.replace("user2/casual/nope", "X")))
        self.assertNotIn("User2 Elves", hidden.message)
        self.assertEqual(self.call("user2", field_group.group_view, GRUUL, "target"), 404)
        # Before the simulations setting's 403, as for a missing deck.
        e = self.error("user1", field_group.run_group, body("user1", id=GRUUL, opponents=[R_ELVES]))
        self.assertEqual(e.status, 404)
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            answer = self.call("matt", field_group.group_view, GRUUL, "target", R_ELVES)
        self.assertEqual([o["id"] for o in answer["opponents"]], [R_ELVES])

    def test_routes_are_lazy_and_answer_202_while_playing(self):
        self.assertEqual(feature_routes._status(("field", "group"), {"status": "running"}), 202)
        self.assertEqual(feature_routes._status(("field", "group", "run"), {"status": "done"}), 200)


class GroupRunTests(GroupApiTestCase):

    def test_run_plays_the_group_and_joins(self):
        self.playing()
        answer = self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO, BLUE]))
        self.assertTrue(self.g.started.wait(WAIT))
        self.assertIn(answer["status"], ("queued", "running"))
        again = self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[BLUE, MONO],
                                                              budget="quick"))
        self.assertEqual(again["status"], "running")
        self.assertEqual(len(self.g.runs), 1)
        self.assertEqual(self.g.runs[0][:2], (GRUUL, [MONO, BLUE]))
        self.assertEqual(self.g.runs[0][4], "home")
        # The page reloaded without opponents still shows the playing group.
        shown = self.call("matt", field_group.group_view, GRUUL, "target")
        self.assertEqual((shown["status"], [c["id"] for c in shown["chosen"]]), ("running", [MONO, BLUE]))
        self.assertEqual(sorted(p["opponent"]["id"] for p in shown["job"]["pairs"].values()), [BLUE, MONO])
        # Another group of the same list waits for this one.
        self.assertEqual(self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO])), 409)
        # The Running list names it a group run, linking to its part.
        job = api.forge_runs.COORD_JOBS.active()[0]
        self.assertTrue(job.key.startswith("field:home:") and ":group:" in job.key)
        self.assertEqual(api.forge_runs._coord_title(job, {"deck": {"title": "Gruul Test"}}), "Group run of Gruul Test")
        self.assertIn("part=group", api.forge_runs._coord_link(job, {}))
        self.g.gate.set()
        self.finish()
        done = self.call("matt", field_group.group_view, GRUUL, "target", f"{MONO},{BLUE}")
        self.assertEqual((done["status"], done["games"]), ("done", 400))

    def test_stop(self):
        self.playing()
        self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO]))
        self.assertTrue(self.g.started.wait(WAIT))
        self.assertEqual(self.call("user2", field_group.stop_group, body("user2", id=GRUUL)), 404)
        answer = self.call("matt", field_group.stop_group, body("matt", id=GRUUL))
        self.assertIn("stopped by Matt", answer["notice"])
        self.assertEqual(answer["chosen"], [{"id": MONO, "version": "target"}])

    def test_refusals(self):
        self.assertEqual(self.call("user1", field_group.run_group, body("user1", id=GRUUL, opponents=[MONO])), 403)
        self.assertEqual(self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[])), 400)
        self.assertEqual(self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO],
                                                                       budget="fixed:5")), 400)
        e = self.error("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO], expected_card_sha="0" * 64))
        self.assertEqual(e.status, 409)
        self.forge.ready = False
        self.assertEqual(self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO])), 503)
        self.assertEqual(self.g.runs, [])

    def test_a_group_not_yet_reporting_names_no_hidden_deck(self):
        # User2 plays home's Public deck against his own private one; until its first report the job
        # has no pairs, so only its chosen decks keep it from Matt.
        hold, real_run = threading.Event(), self.g.run
        self.addCleanup(hold.set)

        def held(*args, **kwargs):
            hold.wait(WAIT)
            return real_run(*args, **kwargs)
        self.g.run = held
        self.set_mode("everyone")
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            self.call("user2", field_group.run_group, body("user2", id=GRUUL, opponents=[R_ELVES]))
            own = self.call("user2", field_group.group_view, GRUUL, "target")
            self.assertEqual(own["chosen"], [{"id": R_ELVES, "version": "target"}])
            shown = self.call("matt", field_group.group_view, GRUUL, "target")
            self.assertEqual((shown["status"], shown["chosen"], shown["opponents"]), ("none", [], []))
            self.assertNotIn("r-elves", json.dumps(shown))
            self.assertNotIn("User2 Elves", json.dumps(shown))
            stopped = self.call("matt", field_group.stop_group, body("matt", id=GRUUL))
            self.assertEqual(stopped["chosen"], [])
            self.assertNotIn("r-elves", json.dumps(stopped))
            self.assertNotIn("User2 Elves", json.dumps(stopped))
        hold.set()

    def test_a_field_run_waits_for_a_group_of_the_list(self):
        self.playing()
        self.call("matt", field_group.run_group, body("matt", id=GRUUL, opponents=[MONO]))
        self.assertTrue(self.g.started.wait(WAIT))
        self.forge.field.opponents = lambda entry, **options: [{"id": MONO}]
        e = self.error("matt", field_page.run_field, body("matt", id=GRUUL))
        self.assertEqual((e.status, e.message), (409, field_page.GROUP_PLAYING))
        self.assertEqual(len(api.forge_runs.COORD_JOBS.active()), 1)
