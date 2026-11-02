"""Tests for the deck page's "Against popular decks" API (api/gauntlet_page.py; decklab/design/gauntlet.md
sections 6 and 8): GET /api/gauntlet and /api/gauntlet/catalogue, POST /api/gauntlet/run and /stop.

They run in test_api_permissions' sandbox (roles, and User2's own space with one deck), whose FakeForge
stands in for decklab.lib.forge; FakeGauntlet stands in for forge.gauntlet. A run reports a pair record per
opponent and keeps reporting until its gate opens. Each test gets a fresh COORD_JOBS runner. No Forge game,
network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_api
"""
import contextlib
import json
import tempfile
import threading
import types
from pathlib import Path
from unittest import mock

from decklab.lib import access, api, jobs
from decklab.lib.api import gauntlet_page, guard
from decklab.lib import feature_routes
from decklab.tests.test_api_permissions import PermissionTestCase

GRUUL, ELVES, R_ELVES = "casual/gruul-test", "commander/elf-commander", "user2/casual/r-elves"
SAMPLE = "sample:0123456789ab"
WAIT = 5
POPULAR = [("gauntlet:forge/duels/goblins", "Goblin Rush", "R", "aggro", "medium"),
           ("gauntlet:forge/duels/wall-of-ice", "Wall of Ice", "U", "control", "hard"),
           ("gauntlet:forge/precons/elf-rally", "Elf Rally", "G", "midrange", "medium")]


class FakeGauntlet:
    """forge.gauntlet's stand-in: a constructed catalogue of POPULAR and a Commander one of none (built
    unless self.built is False); run() reports 50 of 200 games a pair until self.gate is set."""

    def __init__(self, forge, results):
        self.forge, self.results = forge, results
        self.built = True
        self.gate, self.started = threading.Event(), threading.Event()
        self.gate.set()
        self.runs, self.saved, self.keeps, self.games = [], {}, [], 0

    def results_dir(self):
        return self.results

    def format_of(self, entry):
        return "commander" if entry["kind"] == "commander" else "constructed"

    def catalogue(self, fmt):
        if not self.built:
            raise self.forge.ForgeError(f"There's no {fmt} gauntlet yet: build it on the PC with "
                                        f"python -m decklab.lib.forge gauntlet build --format {fmt}.")
        decks = [{"id": i, "title": t, "kind": "constructed", "tier": tier, "identity": c, "colours": c,
                  "style": {"primary": s}, "playable": True,
                  "source": {"kind": "forge", "file": "res/quest/duels/x.dck"}}
                 for i, t, c, s, tier in POPULAR] if fmt == "constructed" else []
        return {"format": 1, "kind": fmt, "built": "2026-11-01T00:00:00", "card_data": "2026-10-30",
                "sha": "c" * 64, "decks": decks}

    def draw(self, fmt, size=None, colours=None, styles=None, tiers=None, seed="", save=True):
        decks = [d for d in self.catalogue(fmt)["decks"] if (not styles or d["style"]["primary"] in styles)
                 and (not colours or set(d["identity"]) <= set(colours))][:size]
        found = {"id": SAMPLE if not (colours or styles) else "sample:fedcba987654", "format": fmt,
                 "catalogue_sha": "c" * 64, "filters": {"colours": colours, "styles": styles,
                                                        "tiers": list(tiers or ["medium", "hard"])},
                 "size": size, "seed": seed, "decks": [d["id"] for d in decks]}
        if save:
            self.saved[found["id"]] = found
        return found

    def sample(self, sample_id):
        if sample_id not in self.saved:
            raise ValueError("no sample")
        return self.saved[sample_id]

    def entries(self, fmt, ids):
        return [{"id": i, "version": "target", "title": i} for i in ids]

    def plan(self, entry, chosen, budget):
        per = int(budget.split(":")[1])
        opps = self.entries(chosen["format"], chosen["decks"])
        return {"per_opponent": per, "new_games": per * len(opps),
                "pairs": [{"opponent": o, "games": per} for o in opps]}

    def view(self, entry, chosen, keep=None):
        self.keeps.append(keep)
        opponents = [{"id": d, "title": d.rsplit("/", 1)[1], "tier": "medium", "identity": "R", "style": "aggro",
                      "games": self.games, "rate": {"value": 0.4, "low": 0.3, "high": 0.5} if self.games else None,
                      "lead": None, "not_meaningful": False, "problem": None,
                      "source": {"kind": "edhrec", "url": "javascript:alert(1)", "file": "C:/secret"}}
                     for d in chosen["decks"]]
        return {"deck": entry["id"], "sample": chosen["id"], "format": chosen["format"], "opponents": opponents,
                "groups": {"colour": [{"key": "R", "label": "Red", "opponents": len(opponents), "games": self.games,
                                       "rate": 0.4, "low": 0.3, "high": 0.5, "spread": [0.4, 0.4], "note": ""}]},
                "games": self.games * len(opponents), "note": "Each range covers these sampled opponents only.",
                "notes": []}

    def run(self, entry, chosen, budget, progress=None, by=None, space=None):
        self.runs.append((entry["id"], chosen["id"], budget, by, space))
        pairs = {f"k{i}": {"opponent": {"id": d, "version": "target", "title": d}, "done": 50, "total": 200,
                           "playing": True} for i, d in enumerate(chosen["decks"])}
        detail = {"budget": budget, "deck": {"id": entry["id"], "title": entry["title"]}, "pairs": pairs}
        progress(50, 200, detail)
        self.started.set()
        while not self.gate.wait(0.005):
            progress(50, 200, detail)
        self.games = 200
        return {"played": 200}


def body(profile, **data):
    return json.dumps({"profile": profile, **data}).encode("utf-8")


class GauntletApiTestCase(PermissionTestCase):

    def setUp(self):
        super().setUp()
        self.forge = self.box.forge
        tmp = tempfile.TemporaryDirectory(prefix="decklab-gauntlet-api-")
        self.addCleanup(tmp.cleanup)
        self.g = FakeGauntlet(self.forge, Path(tmp.name))
        self.forge.gauntlet = self.g
        self.estimated = []
        self.forge.estimate = types.SimpleNamespace(minutes=self.minutes)
        self.addCleanup(lambda: delattr(self.forge, "gauntlet"))
        runner = jobs.Runner(max_running=2, max_queued=4, log=lambda text: None,
                             describe=api.forge_runs._matchup_error, name="coordinator")
        patcher = mock.patch.object(api.forge_runs, "COORD_JOBS", runner)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.finish)

    def minutes(self, pairs, results_dir=None):
        self.estimated.append(results_dir)
        return (3.0, 5.0) if pairs else None

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
        """function's answer as who, or its ApiError's status."""
        with self.as_(who):
            try:
                return function(*args, **kwargs)
            except api.ApiError as e:
                return e.status

    def run_as(self, who, deck_id, **extra):
        return self.call(who, api_run, body(who, id=deck_id, **extra))

    def set_mode(self, mode):
        with self.as_("matt"):
            return api.change_simulations(body("matt", mode=mode))

    def playing(self):
        self.g.gate.clear()
        self.g.started.clear()


def api_run(data):
    return gauntlet_page.run_gauntlet(data)


def api_stop(data):
    return gauntlet_page.stop_gauntlet(data)


class GauntletViewTests(GauntletApiTestCase):

    def test_before_any_run(self):
        answer = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertEqual((answer["status"], answer["job"], answer["format"]), ("none", None, "constructed"))
        self.assertEqual(answer["sample"]["id"], SAMPLE)
        self.assertEqual(answer["sample"]["decks"], 3)
        self.assertEqual(answer["catalogue"]["playable"], 3)
        self.assertEqual(sorted(answer["budgets"]), ["fixed:100", "fixed:200", "fixed:50"])
        self.assertEqual(answer["budgets"]["fixed:100"], {"games": 100, "new_games": 300, "minutes": [3.0, 5.0]})
        self.assertEqual(set(self.estimated), {self.g.results})       # the gauntlet's own results folder
        self.assertEqual(answer["deck"]["id"], GRUUL)
        self.assertEqual(self.g.saved, {})          # a sample drawn for the view isn't saved
        # Sources keep only safe links and never a file path on the PC.
        source = answer["opponents"][0]["source"]
        self.assertIsNone(source["url"])
        self.assertNotIn("file", source)
        json.dumps(answer, allow_nan=False)

    def test_catalogue_missing_says_how_to_build_it(self):
        self.g.built = False
        answer = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertIsNone(answer["catalogue"])
        self.assertEqual(answer["build_command"], "python -m decklab.lib.forge gauntlet build --format constructed")
        self.assertEqual((answer["status"], answer["opponents"]), ("none", []))
        self.set_mode("everyone")
        with self.as_("matt"), self.assertRaises(api.ApiError) as caught:
            api_run(body("matt", id=GRUUL))
        self.assertEqual(caught.exception.status, 503)
        self.assertIn("gauntlet build", caught.exception.message)
        self.assertEqual(self.g.runs, [])
        self.assertIsNone(gauntlet_page.catalogue_view("constructed")["built"])

    def test_catalogue_counts_are_public(self):
        found = self.call("user2", gauntlet_page.catalogue_view, "constructed")
        self.assertEqual((found["playable"], found["styles"]), (3, {"aggro": 1, "control": 1, "midrange": 1}))
        self.assertIn("EDHREC", found["credit"])
        self.assertEqual(self.call("user2", gauntlet_page.catalogue_view, "modern"), 400)

    def test_filters_are_checked(self):
        view = gauntlet_page.gauntlet_view
        for kwargs in ({"size": "0"}, {"size": "many"}, {"colours": "WX"}, {"styles": "tempo"},
                       {"tiers": "core"}, {"sample": "sample:nothex"}):
            with self.subTest(**kwargs):
                self.assertEqual(self.call("matt", view, GRUUL, "target", **kwargs), 400)
        self.assertEqual(self.call("matt", view, GRUUL, "target", sample=SAMPLE), 404)    # not saved
        narrowed = self.call("matt", view, GRUUL, "target", styles="control")
        self.assertEqual(narrowed["sample"]["decks"], 1)

    def test_a_hidden_deck_answers_as_a_missing_one_first(self):
        view = gauntlet_page.gauntlet_view
        self.assertEqual(self.call("user2", view, GRUUL, "target"), 404)
        self.assertEqual(self.call("matt", view, R_ELVES, "target"), 404)
        self.assertEqual(self.call("user2", view, GRUUL, "target", size="bad"), 404)      # before the 400
        self.assertIsInstance(self.call("user2", view, R_ELVES, "target"), dict)

    def test_results_kept_are_this_lists_against_gauntlet_decks_only(self):
        self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        keep = self.g.keeps[-1]
        entry = gauntlet_page.field_page._field_entry(self.forge, GRUUL, "target")[1]
        sha = entry["card_sha"]
        self.assertTrue(keep({"sides": [{"card_sha": sha, "id": GRUUL}, {"card_sha": "d" * 64, "id": POPULAR[0][0]}]}))
        self.assertFalse(keep({"sides": [{"card_sha": sha, "id": GRUUL}, {"card_sha": "e" * 64, "id": ELVES}]}))
        self.assertFalse(keep({"sides": [{"card_sha": "f" * 64, "id": GRUUL}, {"card_sha": "d" * 64,
                                                                              "id": POPULAR[0][0]}]}))


class GauntletRunTests(GauntletApiTestCase):

    def test_require_start_modes(self):
        # The default (admins only) goes by role, even at home; everyone; paused starts nothing.
        expected = {None: {"matt"}, "everyone": {"matt", "user1"}, "paused": set()}
        for mode, allowed in expected.items():
            with self.subTest(mode=mode):
                if mode:
                    self.set_mode(mode)
                for who in ("matt", "user1"):
                    status = self.run_as(who, GRUUL)
                    self.finish()
                    self.assertEqual(status != 403, who in allowed, (mode, who, status))
        self.set_mode("everyone")
        self.assertIsInstance(self.run_as("user2", R_ELVES), dict)       # a member's own deck
        self.finish()
        self.assertEqual({run[0] for run in self.g.runs}, {GRUUL, R_ELVES})

    def test_404_before_403_and_every_other_refusal(self):
        self.set_mode("paused")
        for extra in ({}, {"budget": "lots"}, {"expected_card_sha": "a" * 64}, {"size": 0}):
            with self.subTest(**extra):
                self.assertEqual(self.run_as("user2", GRUUL, **extra), 404)
                self.assertEqual(self.run_as("matt", R_ELVES, **extra), 404)
                self.assertEqual(self.call("user2", api_stop, body("user2", id=GRUUL)), 404)
        self.assertEqual(self.run_as("user2", R_ELVES), 403)        # its own deck: the setting's refusal
        self.assertEqual(self.g.runs, [])

    def test_a_run_waits_plays_and_is_joined(self):
        self.set_mode("everyone")
        self.playing()
        first = self.run_as("matt", GRUUL)
        self.assertIn(first["status"], ("queued", "running"))
        self.assertTrue(self.g.started.wait(WAIT))
        answer = self.call("user1", gauntlet_page.gauntlet_view, GRUUL, "target", styles="control")
        self.assertEqual(answer["status"], "running")           # the run playing, whatever filters are asked for
        self.assertEqual(answer["sample"]["id"], SAMPLE)
        job = answer["job"]
        self.assertEqual((job["done"], job["total"], job["by"], job["sample"], job["budget"]),
                         (50, 200, "Matt", SAMPLE, "fixed:100"))
        self.assertNotIn("deck", job)
        self.assertEqual(answer["budgets"], {})
        entry = gauntlet_page.field_page._field_entry(self.forge, GRUUL, "target")[1]
        key = f"gauntlet:home:{entry['card_sha']}:{SAMPLE}"
        self.assertIsNotNone(api.forge_runs.COORD_JOBS.get(key))
        self.assertEqual(api.forge_runs.COORD_JOBS.get(key).fn.via["link"],
                         "#/deck?id=casual%2Fgruul-test&v=target&part=gauntlet")
        self.run_as("user1", GRUUL)                             # joins the run playing
        self.finish()
        self.assertEqual(self.g.runs, [(GRUUL, SAMPLE, "fixed:100", "Matt", "home")])
        self.assertIn(SAMPLE, self.g.saved)                     # a played sample is saved
        done = self.call("matt", gauntlet_page.gauntlet_view, GRUUL, "target")
        self.assertEqual((done["status"], done["job"], done["games"]), ("done", None, 600))

    def test_another_samples_run_of_the_list_is_refused_and_stop_stops_it(self):
        self.set_mode("everyone")
        self.playing()
        self.assertIsInstance(self.run_as("matt", GRUUL), dict)
        self.assertTrue(self.g.started.wait(WAIT))
        self.assertEqual(self.run_as("user1", GRUUL, styles="aggro"), 409)       # another sample of the same list
        with self.as_("user1"):
            with self.assertRaises(api.ApiError) as raised:
                api_run(body("user1", id=GRUUL, styles="aggro"))
        self.assertEqual(str(raised.exception), gauntlet_page.ALREADY_PLAYING)
        self.assertIsInstance(self.run_as("user1", GRUUL), dict)                  # the same sample joins
        answer = self.call("matt", api_stop, body("matt", id=GRUUL))
        self.assertEqual(answer["status"], "none")
        self.assertEqual(api.forge_runs.COORD_JOBS.active(), [])
        self.finish()
        self.assertEqual([r[1] for r in self.g.runs], [SAMPLE])

    def test_the_saved_list_must_match(self):
        self.set_mode("everyone")
        self.forge.ready = False
        self.assertEqual(self.run_as("matt", GRUUL, expected_card_sha="a" * 64), 409)       # before Forge's 503
        self.assertEqual(self.run_as("matt", GRUUL, expected_card_sha="A" * 64), 400)
        entry = gauntlet_page.field_page._field_entry(self.forge, GRUUL, "target")[1]
        self.assertEqual(self.run_as("matt", GRUUL, expected_card_sha=entry["card_sha"]), 503)    # Forge
        self.forge.ready = True
        self.assertEqual(self.run_as("matt", GRUUL, budget="fixed:7"), 400)
        self.assertEqual(self.run_as("matt", GRUUL, styles="combo"), 400)          # no deck matches
        self.assertEqual(self.g.runs, [])
        self.assertIsInstance(self.run_as("matt", GRUUL, expected_card_sha=entry["card_sha"]), dict)
        self.finish()
        self.assertEqual(len(self.g.runs), 1)

    def test_own_space_stop(self):
        self.set_mode("everyone")
        self.playing()
        self.run_as("user2", R_ELVES)
        self.assertTrue(self.g.started.wait(WAIT))
        # Matt, an admin of another space, can't see the deck: it answers as a missing one.
        self.assertEqual(self.call("matt", api_stop, body("matt", id=R_ELVES)), 404)
        answer = self.call("user2", api_stop, body("user2", id=R_ELVES))
        self.assertEqual(answer["status"], "none")
        self.assertEqual(answer["notice"], "The gauntlet run was stopped by User2; every game that finished is kept.")
        self.assertEqual(self.call("user2", api_stop, body("user2", id=R_ELVES))["status"], "none")

    def test_a_home_run_is_stopped_by_its_space_and_named_someone_elsewhere(self):
        self.set_mode("everyone")
        self.playing()
        self.run_as("matt", GRUUL)
        self.assertTrue(self.g.started.wait(WAIT))
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})):
            seen = self.call("user2", gauntlet_page.gauntlet_view, GRUUL, "target")
            self.assertEqual((seen["status"], seen["job"]["by"], seen["job"]["may_stop"]), ("running", "someone", False))
            self.assertNotIn("Matt", json.dumps(seen))
            self.assertEqual(self.call("user2", api_stop, body("user2", id=GRUUL)), 403)
        answer = self.call("user1", api_stop, body("user1", id=GRUUL))
        self.assertIn("stopped by User1", answer["notice"])


    def test_the_running_list_shows_a_gauntlet_run(self):
        # The Running list (forge_runs) names a gauntlet run to its own space; an admin of another
        # space sees it only anonymously, and a member of none of it not at all.
        self.set_mode("everyone")
        self.playing()
        self.run_as("matt", GRUUL)
        self.assertTrue(self.g.started.wait(WAIT))
        with self.as_("user1"):
            items = api.forge_runs._running_items()
        self.assertEqual([(i["kind"], i["title"], i["link"], i.get("hidden")) for i in items],
                         [("gauntlet", "Gauntlet run of Gruul Test", "#/deck?id=casual%2Fgruul-test&v=target&part=gauntlet",
                           None)])
        self.assertTrue(items[0]["may_stop"])
        with self.as_("user2"):
            self.assertEqual(api.forge_runs._running_items(), [])
        self.finish()
        self.playing()
        self.run_as("user2", R_ELVES)
        self.assertTrue(self.g.started.wait(WAIT))
        with self.as_("matt"):
            hidden = api.forge_runs._running_items()
        self.assertEqual([(i["kind"], i["hidden"], i["link"]) for i in hidden], [("gauntlet", True, None)])
        self.assertNotIn("R Elves", json.dumps(hidden))


class GauntletRouteTests(GauntletApiTestCase):

    def test_waiting_answers_are_202(self):
        handler = mock.Mock(command="POST")
        handler._write_body.return_value = b"{}"
        with mock.patch.object(gauntlet_page, "run_gauntlet", return_value={"status": "queued"}):
            self.assertTrue(feature_routes.dispatch(handler, ["gauntlet", "run"], {}))
        handler._send_json.assert_called_once_with(202, {"status": "queued"})
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"format": "commander"}
        with mock.patch.object(gauntlet_page, "catalogue_view", return_value={"status": "running"}):
            feature_routes.dispatch(handler, ["gauntlet", "catalogue"], {})
        handler._send_json.assert_called_once_with(200, {"status": "running"})
