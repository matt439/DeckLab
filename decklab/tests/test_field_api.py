"""Tests for the field view's API (simulation wave 3's R13, forge-trial/sim-wave3-contract.md
section 10.5): GET /api/field, POST /api/field/run and /stop (api/field_page.py), the field
run's job in api.forge_runs.COORD_JOBS, and what a matchup answer says while a field run's pair
plays it (api.forge_runs._job_for_key: status "running", the pair's record with "via", and a 409
for a Stop on the matchup page).

They run in test_api's Sandbox, whose FakeForge stands in for decklab.lib.forge; FakeFieldPart
stands in for its field part (forge.field) and a one-line estimate part for forge.estimate. A field
run reports one pair record per opponent and keeps reporting until its gate opens, so a test can
look at it while it plays. Each test gets a fresh COORD_JOBS runner.

Run from the repo root: python scripts/test_fixtures.py
"""
import json
import threading
import types
from unittest import mock

from decklab.lib import api, decks, jobs
from decklab.tests.test_api import ApiTestCase

ELVES, PRECON, GRUUL = "commander/elf-commander", "product/fdc-test-precon", "casual/gruul-test"
WAIT = 5


def body(**data):
    return json.dumps(data).encode("utf-8")


class FakeFieldPart:
    """forge.field's stand-in: the Commander field is the sandbox's precon, the Constructed one
    Gruul Test. run_field reports a pair record per opponent (50 of 200 games, 30 wins and 2
    without a winner, playing) until self.gate is set, then "plays" 200 games a pair."""

    BUDGETS = ("quick", "standard", "thorough")
    NO_OPPONENTS = "There's no other deck in the {fmt} field for it to play."

    def __init__(self, forge):
        self.forge = forge
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()
        self.runs, self.games = [], 0

    def _entry(self, deck_id):
        summary = decks.find_summary(deck_id)
        return self.forge.entry(summary["id"], "target", summary["title"], decks.engine_kind(summary),
                                decks.load_deck(summary["id"], "target"))

    def field_lists(self, fmt, **options):
        entries = [self._entry(PRECON if fmt == "Commander" else GRUUL)]
        return [entry for entry in entries if options.get("visible", lambda _: True)(entry["id"])]

    def opponents(self, entry, opponents=None, **options):
        return [e for e in self.field_lists(self.forge.fmt_for(entry["kind"]), **options) if e["id"] != entry["id"]]

    def plan(self, entry, budget, results_dir=None, opponents=None, **options):
        per = {"quick": 200, "standard": 400, "thorough": 800}[budget]
        opps = self.opponents(entry, **options)
        return {"budget": budget, "per_opponent": per, "floor": 0, "allocate": 0, "new_games": per * len(opps),
                "pairs": [{"opponent": o, "key": self.forge.matchup_key(entry, o), "have": 0, "floor": per,
                           "games": per} for o in opps]}

    def view(self, entry, results_dir=None, **options):
        opps = self.opponents(entry, **options)
        return {"deck": {k: entry[k] for k in ("id", "version", "title", "card_sha")},
                "format": self.forge.fmt_for(entry["kind"]),
                "opponents": [{"id": o["id"], "version": o["version"], "title": o["title"], "kind": "product",
                               "card_sha": o["card_sha"], "key": self.forge.matchup_key(entry, o),
                               "games": self.games, "rate": None, "lead": None, "pred": None, "residual": None,
                               "not_meaningful": False, "problem": None} for o in opps],
                "average": None, "rating": None, "coverage": {"with_floor": 0, "of": len(opps)},
                "last_run": None, "notes": []}

    def run_field(self, entry, budget, *, by, progress=None, **kwargs):
        self.runs.append((entry["id"], budget, by))
        pairs = {self.forge.matchup_key(entry, o): {"opponent": {"id": o["id"], "version": o["version"],
                                                                 "title": o["title"]},
                                                    "done": 50, "total": 200, "wins": 30, "other": 2, "playing": True}
                 for o in self.opponents(entry)}
        detail = {"budget": budget, "phase": "floor", "deck": {k: entry[k] for k in ("id", "version", "title")},
                  "pairs": pairs}
        progress(50, 200, detail)
        self.started.set()
        while not self.gate.wait(0.005):
            progress(50, 200, detail)
        self.games = 200
        return {"played": 200}


class FieldApiTestCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.forge = self.box.forge
        self.field = FakeFieldPart(self.forge)
        self.forge.field = self.field
        self.forge.estimate = types.SimpleNamespace(minutes=lambda pairs: (12.0, 20.0) if pairs else None)
        runner = jobs.Runner(max_running=2, max_queued=4, log=lambda text: None,
                             describe=api.forge_runs._matchup_error, name="coordinator")
        patcher = mock.patch.object(api.forge_runs, "COORD_JOBS", runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.finish)

    def finish(self):
        self.field.gate.set()
        for job in list(api.forge_runs.COORD_JOBS._jobs.values()):
            if not job.wait(WAIT):
                raise AssertionError(f"job {job.key} didn't finish")

    def playing(self):
        self.field.gate.clear()
        self.field.started.clear()

    def play(self, deck_id=ELVES, profile="matt", **extra):
        return api.run_field(body(profile=profile, id=deck_id, **extra))

    def key(self, a=ELVES, b=PRECON):
        return self.forge.matchup_key(self.field._entry(a), self.field._entry(b))


class FieldViewTests(FieldApiTestCase):

    def test_before_any_run(self):
        answer = api.field_view(ELVES, "target", "user1")
        self.assertEqual(set(answer) - {"deck", "format", "opponents", "average", "rating", "coverage", "last_run",
                                        "notes"},
                         {"status", "job", "notice", "error", "budgets", "default_budget", "field_lists", "forge"})
        self.assertEqual((answer["status"], answer["job"], answer["notice"], answer["error"]), ("none", None, None, None))
        self.assertEqual(answer["budgets"], {"quick": {"games": 200, "new_games": 200, "minutes": [12.0, 20.0]},
                                             "standard": {"games": 400, "new_games": 400, "minutes": [12.0, 20.0]},
                                             "thorough": {"games": 800, "new_games": 800, "minutes": [12.0, 20.0]}})
        self.assertEqual(answer["default_budget"], "standard")
        self.assertEqual([(e["id"], e["kind"]) for e in answer["field_lists"]], [(PRECON, "product")])
        self.assertEqual(answer["forge"]["ready"], True)
        json.dumps(answer, allow_nan=False)
        self.assertEqual(self.field.runs, [])

    def test_refusals(self):
        self.assertApiError(404, api.field_view, "casual/nope", "target")
        self.assertApiError(400, api.field_view, "product/fdn-beginner-box/elves", "target", contains="half")
        self.assertApiError(404, api.field_view, ELVES, "target", "nobody")
        self.assertApiError(403, api.run_field, body(profile="nobody", id=ELVES))
        self.assertApiError(400, api.run_field, body(profile="matt", id=ELVES, budget="lots"), contains="budget")
        self.assertApiError(400, api.run_field, body(profile="matt"), contains="needs id")
        # Gruul Test is the whole Constructed field: nothing for it to play.
        self.assertApiError(400, api.run_field, body(profile="matt", id=GRUUL), contains="no other deck")
        self.forge.ready = False
        self.assertApiError(503, api.run_field, body(profile="matt", id=ELVES))
        self.assertEqual(self.field.runs, [])


class FieldPilotTests(FieldApiTestCase):
    """?pilot=1 (the deck page's Overview, E1-S12): the list's poor-AI evidence, as Matchups judges it."""

    def test_pilot_only_when_asked_for(self):
        self.assertNotIn("pilot", api.field_view(ELVES, "target", "user1"))
        self.assertNotIn("pilot", api.field_view(ELVES, "target", "user1", pilot=False))

    def test_poor_and_normal_pilots_for_the_list_shown(self):
        asked = []
        poor = {"poor": True, "why": "commander", "cards": [{"name": "Elf", "qty": 1, "commander": True}]}

        fixed = {"profile": "Default", "switches": ["team-pump-1"]}
        entry = self.forge.entry

        def list_ai(sections, kind, results_dir=None, pilot=None, *, keep=None):
            asked.append((kind, sorted(sections), pilot, keep is not None))
            return {"pilot": poor if kind == "commander" else {"poor": False, "why": None, "cards": []}}

        def piloted(deck_id, *rest):
            return dict(entry(deck_id, *rest), pilot=fixed if deck_id == ELVES else None)
        with mock.patch.object(self.forge, "list_ai", list_ai), mock.patch.object(self.forge, "entry", piloted):
            self.assertEqual(api.field_view(ELVES, "target", "user1", pilot=True)["pilot"], poor)
            self.assertEqual(api.field_view(GRUUL, "target", "user1", pilot=True)["pilot"]["poor"], False)
        # Each list's own sections and the pilot its field games play with (the team-pump fix's side
        # ids count), with saved results kept to what the viewer may see.
        self.assertEqual([(kind, pilot, keep) for kind, _, pilot, keep in asked],
                         [("commander", fixed, True), ("constructed", None, True)])
        self.assertEqual(self.field.runs, [])

    def test_unknown_pilot_is_none(self):
        # FakeForge's AiLimits have no "pilot" (Forge's scripts unread); a failure is logged, not raised.
        self.assertIsNone(api.field_view(ELVES, "target", "user1", pilot=True)["pilot"])
        with mock.patch.object(self.forge, "list_ai", side_effect=RuntimeError("scripts")), \
                mock.patch.object(api.common, "_log") as log:
            answer = api.field_view(ELVES, "target", "user1", pilot=True)
        self.assertIsNone(answer["pilot"])
        self.assertEqual(answer["status"], "none")
        self.assertIn("can't be worked out", log.call_args[0][0])


class FieldRunTests(FieldApiTestCase):

    def test_a_run_waits_plays_and_is_joined(self):
        self.playing()
        first = self.play()
        self.assertIn(first["status"], ("queued", "running"))
        self.assertTrue(self.field.started.wait(WAIT))
        answer = api.field_view(ELVES, "target")
        self.assertEqual(answer["status"], "running")
        job = answer["job"]
        self.assertEqual((job["done"], job["total"], job["by"], job["budget"], job["phase"]),
                         (50, 200, "Matt", "standard", "floor"))
        self.assertEqual(list(job["pairs"]), [self.key()])
        self.assertIsNotNone(job["started"])
        self.play(profile="user1")                         # joins the run playing
        self.finish()
        self.assertEqual(self.field.runs, [(ELVES, "standard", "Matt")])
        done = api.field_view(ELVES, "target")
        self.assertEqual((done["status"], done["job"]), ("done", None))
        self.assertIn(api.forge_runs.COORD_JOBS.get(f"field:home:{self.field._entry(ELVES)['card_sha']}:Commander").key,
                      api.forge_runs.COORD_JOBS._jobs)

    def test_the_budget_follows_the_profile(self):
        api.put_settings("user1", b'{"field_budget": "quick"}')
        self.assertEqual(api.field_view(ELVES, "target", "user1")["default_budget"], "quick")
        self.box.state.down = True                  # the last known setting, else the default
        self.assertEqual(api.field_view(ELVES, "target", "user1")["default_budget"], "quick")
        self.assertEqual(api.field_view(ELVES, "target", "matt")["default_budget"], "standard")
        self.box.state.down = False
        self.play(profile="user1")
        self.finish()
        self.play(profile="matt", budget="thorough")
        self.finish()
        self.assertEqual(self.field.runs, [(ELVES, "quick", "User1"), (ELVES, "thorough", "Matt")])

    def test_stop(self):
        self.playing()
        self.play()
        self.assertTrue(self.field.started.wait(WAIT))
        answer = api.stop_field(body(profile="user1", id=ELVES))
        self.assertEqual(answer["status"], "none")
        self.assertEqual(answer["notice"], "The field run was stopped by User1; every game that finished is kept.")
        # Stopping with nothing playing changes nothing.
        self.assertEqual(api.stop_field(body(profile="user1", id=ELVES))["status"], "none")


class MatchupWhileFieldPlaysTests(FieldApiTestCase):

    def test_the_matchup_page_follows_the_pair(self):
        self.playing()
        self.play()
        self.assertTrue(self.field.started.wait(WAIT))
        key = self.key()
        # Nothing saved yet: asked for by key, the sides are the field run's two lists.
        answer = api.matchup(key=key)
        self.assertEqual(answer["status"], "running")
        self.assertEqual([s["id"] for s in answer["sides"]], [ELVES, PRECON])
        job = answer["job"]
        self.assertEqual((job["done"], job["total"], job["wins"], job["other"], job["by"]), (50, 200, [30, 18], 2, "Matt"))
        self.assertEqual(job["range"]["value"], 0.6)
        self.assertLess(job["range"]["low"], 0.6)
        self.assertGreater(job["range"]["high"], 0.6)
        self.assertEqual(job["via"], {"kind": "field", "job": f"field:home:{self.field._entry(ELVES)['card_sha']}:Commander",
                                      "title": "Field run of Elf Commander",
                                      "link": "#/deck?id=commander%2Felf-commander&v=target&part=field", "by": "Matt"})
        # From the opponent's side, the wins turn round.
        other = api.matchup(PRECON, "target", ELVES, "target")
        self.assertEqual((other["status"], other["job"]["wins"]), ("running", [18, 30]))
        self.assertEqual(other["job"]["range"]["value"], 0.36)
        # The matchup page's Stop is refused: it's stopped on the deck page.
        error = self.assertApiError(409, api.stop_matchup, body(profile="user1", key=key))
        self.assertIn("Field run of Elf Commander: stop it there", error.message)
        self.finish()
        self.assertEqual(api.matchup(ELVES, "target", PRECON, "target")["status"], "none")

    def test_a_key_no_one_plays_is_unchanged(self):
        self.assertIsNone(api.forge_runs._job_for_key(self.key()))
        self.assertApiError(404, lambda: api.matchup(key=self.key()))
