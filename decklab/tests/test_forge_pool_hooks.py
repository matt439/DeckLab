"""Forge pool hooks tests; shared fixtures remain in test_forge_pool."""
import unittest
import io
import json
import os
import threading
import time
from pathlib import Path
from unittest import mock
from decklab.lib import forge
from decklab.lib.forge import pool, runner, seeds
from decklab.tests.test_forge import CARD_LOG, GREEN, RED, entry, load_json
from decklab.tests.test_forge_pool import (
    RunHookCase, _gz_lines, _pilot, _w2_request_args, setUpModule,
    tearDownModule,
)


class NumbersTests(RunHookCase):

    def test_numbers_with_gaps_play_only_those_games_the_same_as_ever(self):
        sent = self.requests()
        numbers = list(range(3, 9)) + list(range(20, 30)) + [61]
        result = self.run_matchup(len(numbers), numbers=numbers)
        self.assertEqual([g["g"] for g in self.games_of(result)], numbers)
        for first, games, _ in sent:               # a request covers consecutive numbers of one block
            self.assertTrue(set(range(first, first + games)) <= set(numbers))
            self.assertEqual(seeds.block_of(first), seeds.block_of(first + games - 1))
        self.assertEqual(result["next_game"], 62)
        run = result["runs"][0]
        self.assertEqual((run["asked"], run["played"], run["games_from"], run["games_to"]), (17, 17, 3, 62))
        self.assertEqual(run["ranges"], [[3, 9], [20, 25], [25, 30], [61, 62]])
        # The same games as a run of every number plays.
        whole = self.run_matchup(62, exact=True, results_dir=self.tmp / "whole")
        strip = lambda games: [{k: v for k, v in g.items() if k != "ms"} for g in games]  # noqa: E731
        self.assertEqual(strip(self.games_of(result)), strip(g for g in self.games_of(whole) if g["g"] in numbers))
        # A matchup plays on from next_game: no number below it, none it holds.
        with self.assertRaises(ValueError):
            self.run_matchup(1, numbers=[30])
        with self.assertRaises(ValueError):
            self.run_matchup(1, numbers=[61])
        more = self.run_matchup(2, numbers=[62, 70])
        self.assertEqual(more["next_game"], 71)

    def test_numbers_must_be_sorted_distinct_and_counted(self):
        for numbers, games in (([3, 1], 2), ([1, 1], 2), ([-1], 1), ([1.0], 1), ([], 0), ([1, 2], 3), ([True], 1)):
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                self.run_matchup(games, numbers=numbers)
        self.assertFalse(self.results.exists() and list(self.results.glob("*.json")))

    def test_paired_and_experiment_results_may_fill_holes_below_next_game(self):
        key = "e" * 64
        first = self.run_matchup(10, numbers=list(range(0, 5)) + list(range(25, 30)), key=key, kind="experiment")
        self.assertEqual((first["next_game"], first["kind"]), (30, "experiment"))
        holes = self.run_matchup(3, numbers=[5, 6, 26 + 4], key=key, kind="experiment")
        self.assertEqual(sorted(g["g"] for g in self.games_of(holes)),
                         [0, 1, 2, 3, 4, 5, 6, 25, 26, 27, 28, 29, 30])
        with self.assertRaises(ValueError):             # numbers it holds
            self.run_matchup(1, numbers=[6], key=key, kind="experiment")
        paired = self.run_matchup(5, numbers=[30, 31, 32, 33, 34], key=key, kind="paired", extra=self.paired_extra())
        fill = self.run_matchup(2, numbers=[0, 1], key=key, kind="paired", extra=self.paired_extra())
        self.assertEqual(sorted(g["g"] for g in self.games_of(fill)), [0, 1, 30, 31, 32, 33, 34])
        self.assertEqual(paired["key"], fill["key"])



class SeedTests(RunHookCase):

    def test_a_new_results_seeds_and_an_existing_ones(self):
        sent = self.requests()
        asked = {"base": 3, "stream": "0123456789abcdef", "flip": 1}
        result = self.run_matchup(50, exact=True, seeds=asked)
        self.assertEqual({k: result["seeds"][k] for k in asked}, asked)
        ordered = sorted([entry(GREEN, "casual/green"), entry(RED, "casual/red")], key=lambda e: e["card_sha"])
        dck = [f"{e['card_sha']}.dck" for e in ordered]
        self.assertTrue(all(deck1 == dck[seeds.deck1_side(first, 1)] for first, _, deck1 in sent))
        # The games are game_seed(3, the stream, g)'s: as a one-shot process plays them.
        strip = lambda games: [{k: v for k, v in g.items() if k != "ms"} for g in games]  # noqa: E731
        with mock.patch.object(seeds, "stream_of", return_value=int(asked["stream"], 16)):
            reference = self.oneshot(0, 25, flip=1, base=3)
        self.assertEqual(strip(self.games_of(result)[:25]), strip(reference))
        self.assertEqual(self.run_matchup(5, exact=True, seeds=asked)["seeds"]["base"], 3)      # the same: fine
        for other in ({**asked, "base": 4}, {**asked, "flip": 0}, {**asked, "stream": "f" * 16}):
            with self.subTest(other=other), self.assertRaises(ValueError):
                self.run_matchup(5, exact=True, seeds=other)
        for bad in ({"base": -1, "stream": "0" * 16, "flip": 0}, {"base": 1, "stream": "xyz", "flip": 0},
                    {"base": 1, "stream": "0" * 16, "flip": 2}, [1, 2, 3]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.run_matchup(5, exact=True, seeds=bad, results_dir=self.tmp / "bad")

    def test_decklab_seed_base_starts_new_results(self):
        os.environ[runner.SEED_BASE_ENV] = "5"
        self.assertEqual(self.run_matchup(25, exact=True)["seeds"]["base"], 5)
        self.assertEqual(self.run_matchup(25, exact=True, seed_base=7, results_dir=self.tmp / "own")["seeds"]["base"], 7)
        os.environ[runner.SEED_BASE_ENV] = "9"
        self.assertEqual(self.run_matchup(25, exact=True)["seeds"]["base"], 5)        # an existing result's stays
        logged = []
        os.environ[runner.SEED_BASE_ENV] = "minus one"
        with mock.patch.object(forge.common, "_log", logged.append):
            self.assertEqual(self.run_matchup(25, exact=True, results_dir=self.tmp / "bad")["seeds"]["base"], 1)
            self.run_matchup(25, exact=True, results_dir=self.tmp / "bad2")
        self.assertEqual(len([line for line in logged if runner.SEED_BASE_ENV in line]), 1)



class KindTests(RunHookCase):

    def test_a_paired_result_is_saved_where_listings_never_look(self):
        key = "a" * 64
        result = self.run_matchup(25, exact=True, key=key, kind="paired", extra=self.paired_extra())
        path = self.results / "paired" / f"{key}.json"
        self.assertTrue(path.exists())
        self.assertFalse((self.results / f"{key}.json").exists())
        saved = load_json(path)
        self.assertEqual((saved["kind"], saved["paired_version"], saved["paired"]),
                         ("paired", 1, self.paired_extra()["paired"]))
        self.assertTrue(forge.saved._is_result(saved, key))
        self.assertEqual(forge.load(key, self.results / "paired")["key"], key)
        self.assertEqual(forge.saved._stored(self.results), [])
        self.assertEqual(result["key"], key)
        with self.assertRaises(ValueError):                         # a paired result needs its block
            self.run_matchup(25, exact=True, key="b" * 64, kind="paired")
        for field in ("sides", "paired_version", "engine"):        # no clash with a result's own fields
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_matchup(25, exact=True, key="b" * 64, kind="paired", extra={**self.paired_extra(), field: 1})
        self.assertFalse((self.results / "paired" / f"{'b' * 64}.json").exists())

    def test_an_experiment_result_and_the_kind_a_key_holds(self):
        key = "d" * 64
        result = self.run_matchup(25, exact=True, key=key, kind="experiment",
                                  extra={"experiment": {"name": "x", "arm": "a", "control_key": "c" * 64}})
        saved = load_json(self.results / f"{key}.json")
        self.assertEqual((saved["kind"], saved["experiment"]["arm"]), ("experiment", "a"))
        self.assertTrue(forge.saved._is_result(saved, key))
        more = self.run_matchup(25, exact=True, key=key, kind="experiment", extra={"experiment": {"arm": "other"}})
        self.assertEqual(more["experiment"]["arm"], "a")            # extra goes into a new result only
        with self.assertRaises(ValueError):                         # a matchup's run of an experiment's key
            self.run_matchup(25, exact=True, key=key)
        with self.assertRaises(ValueError):
            self.run_matchup(25, exact=True, key="d" * 63)
        with self.assertRaises(ValueError):
            self.run_matchup(25, exact=True, kind="other")
        # replay never plans an experiment's arm (a matchup's result of an earlier engine, it would).
        by_id = {"casual/green": entry(GREEN, "casual/green"), "casual/red": entry(RED, "casual/red")}
        matchup = self.run_matchup(25, exact=True, results_dir=self.tmp / "matchup")
        self.assertNotEqual(result["key"], matchup["key"])
        with mock.patch.object(forge.engine, "stored_key", return_value="0" * 64), \
                mock.patch.object(forge.engine, "key", return_value="0" * 64), \
                mock.patch.object(forge.cli, "_ReplayLists") as lists_:
            lists_.return_value.entry.side_effect = lambda seen: by_id.get(seen["id"])
            eng = forge.engine.today()
            self.assertEqual(forge.cli._replay_plan(self.results, eng), [])
            self.assertEqual(len(forge.cli._replay_plan(self.tmp / "matchup", eng)), 1)

    def test_the_kinds_need_the_v2_engine(self):
        with mock.patch.object(forge.simjar, "card_log", return_value={"ready": False, "problem": "Off."}):
            for kwargs in ({"numbers": [0]}, {"seeds": {"base": 1, "stream": "0" * 16, "flip": 0}},
                           {"kind": "experiment", "key": "e" * 64}):
                with self.subTest(kwargs=kwargs), self.assertRaises(forge.ForgeError) as caught:
                    self.run_matchup(1, exact=True, **kwargs)
                self.assertEqual(str(caught.exception), runner.NEEDS_V2)

    def test_a_dck_file_is_written_and_played_under_its_own_name(self):
        import hashlib
        sent = self.asked()
        green = entry(GREEN, "casual/green")
        lines = green["dck"].splitlines()
        text = "\n".join(lines[:3] + list(reversed(lines[3:]))) + "\n"           # another line order
        name = hashlib.sha256(text.encode("utf-8")).hexdigest() + ".dck"
        variant = dict(green, dck=text, dck_file=name)
        result = forge.run(variant, entry(RED, "casual/red"), 25, by="x", results_dir=self.results, exact=True)
        decks = self.setup_()["decks_dir"]
        self.assertEqual((decks / name).read_text(encoding="utf-8"), text)
        self.assertTrue(sent)
        self.assertTrue(all(name in args[args.index("-d") + 1:args.index("-d") + 3] for *_, args in sent))
        self.assertEqual(result["runs"][0]["played"], 25)
        forge.run(green, entry(RED, "casual/red"), 25, by="x", results_dir=self.tmp / "sorted", exact=True)
        self.assertEqual((decks / f"{green['card_sha']}.dck").read_text(encoding="utf-8"), green["dck"])
        self.assertEqual((decks / name).read_text(encoding="utf-8"), text)       # neither overwrote the other
        with self.assertRaises(ValueError):
            forge.run(dict(green, dck_file="../x.dck"), entry(RED), 25, by="x", results_dir=self.results, exact=True)
        with self.assertRaises(ValueError):                         # not the SHA-256 of its text
            forge.run(dict(green, dck_file="0" * 64 + ".dck"), entry(RED), 25, by="x", results_dir=self.results,
                      exact=True)



class LogTeeTests(RunHookCase):

    def test_every_chunks_output_is_written_gzip_compressed(self):
        logs = self.tmp / "logs"
        result = self.run_matchup(60, exact=True, log_dir=logs)
        files = sorted((logs / result["key"]).glob("*.log.gz"), key=lambda p: int(p.name.split("-")[0]))
        covered = []
        for path in files:
            first, last = (int(x) for x in path.name[:-len(".log.gz")].split("-"))
            covered += range(first, last + 1)
            lines = _gz_lines(path)
            self.assertFalse([line for line in lines if line.startswith(runner.SERVE_PREFIX)])
            self.assertEqual(sum(line.startswith("DLENGINE|") for line in lines), 1)
            self.assertEqual(sum(line.startswith("Game Result:") for line in lines), last - first + 1)
        self.assertEqual(covered, list(range(60)))
        self.assertFalse(list((logs / result["key"]).glob(".*.tmp")))

    def test_the_files_are_written_off_the_pool_lock_before_the_run_ends(self):
        logs = self.tmp / "logs"
        real, held = pool._tee_write, []

        def slow(ticket, folder, path, lines):
            held.append(threading.current_thread().name)     # a thread of its own, which holds no lock
            time.sleep(0.3)
            real(ticket, folder, path, lines)

        with mock.patch.object(pool, "_tee_write", slow):
            result = self.run_matchup(50, exact=True, log_dir=logs, workers=2)
        self.assertTrue(held)
        self.assertEqual(set(held), {"pool-log-tee"})   # a thread of its own: never under the pool's lock
        covered = sorted(g for path in (logs / result["key"]).glob("*.log.gz")
                         for g in range(int(path.name.split("-")[0]),
                                        int(path.name[:-len(".log.gz")].split("-")[1]) + 1))
        self.assertEqual(len(held), len(list((logs / result["key"]).glob("*.log.gz"))))
        self.assertEqual(covered, list(range(50)))      # all written once run() returned

    def test_log_every_tees_every_nth_seat_block(self):
        logs = self.tmp / "logs"
        result = self.run_matchup(60, exact=True, log_dir=logs, log_every=2, batch=5)
        covered = sorted(g for path in (logs / result["key"]).glob("*.log.gz")
                         for g in range(int(path.name.split("-")[0]),
                                        int(path.name[:-len(".log.gz")].split("-")[1]) + 1))
        self.assertEqual(covered, list(range(0, 25)) + list(range(50, 60)))
        with self.assertRaises(ValueError):
            self.run_matchup(25, exact=True, log_dir=logs, log_every=0)

    def test_a_tainted_chunk_writes_the_games_it_kept(self):
        logs = self.tmp / "logs"
        self.fake("timeout#7")
        result = self.run_matchup(25, exact=True, log_dir=logs, batch=25, workers=1)
        names = sorted(p.name for p in (logs / result["key"]).glob("*.log.gz"))
        ranges = sorted(tuple(int(x) for x in n[:-len(".log.gz")].split("-")) for n in names)
        self.assertEqual(sorted(g for a, b in ranges for g in range(a, b + 1)), list(range(25)))
        for a, b in ranges:
            lines = _gz_lines(logs / result["key"] / f"{a}-{b}.log.gz")
            self.assertEqual(sum(line.startswith("Game Result:") for line in lines), b - a + 1)

    def test_the_replay_command_takes_the_log_options(self):
        args = forge.cli.argparse.ArgumentParser()
        forge.cli._log_args(args)
        parsed = args.parse_args(["--logs-dir", str(self.tmp / "l"), "--log-every", "10"])
        self.assertEqual(forge.cli._log_kwargs(parsed), {"log_dir": str(self.tmp / "l"), "log_every": 10})
        self.assertEqual(forge.cli._log_kwargs(args.parse_args([])), {})
        with mock.patch.object(forge.cli, "_replay", return_value={"played": [], "busy": [], "failed": []}) as replay, \
                mock.patch.object(forge.cli, "_replay_plan", return_value=[{"games": 1, "a": None}]), \
                mock.patch.object(forge.cli, "_replay_estimate", return_value=None), \
                mock.patch.object(forge.engine, "current", return_value={"kind": forge.engine.KIND_DECKLAB}), \
                mock.patch("sys.stdout", io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            parser = forge.cli.argparse.ArgumentParser()
            forge.cli._replay_args(parser.add_subparsers(dest="command"))
            forge.cli._cmd_replay(parser.parse_args(["replay", "--logs-dir", str(self.tmp / "l"), "--log-every", "10"]))
        self.assertEqual(replay.call_args.kwargs, {"log_dir": str(self.tmp / "l"), "log_every": 10})



class PilotTests(RunHookCase):

    def mirror(self):
        a = dict(entry(GREEN, "casual/green"), pilot=_pilot("Reckless"))
        b = dict(entry(GREEN, "casual/green"), pilot=_pilot())
        return a, b

    def test_a_pilot_mirror_has_one_order_and_its_pilots_keep_their_sides(self):
        sent = self.asked()
        a, b = self.mirror()
        first = forge.run(a, b, 50, by="x", results_dir=self.results, exact=True)
        again = forge.run(b, a, 50, by="x", results_dir=self.results, exact=True)
        self.assertEqual(first["key"], again["key"])
        self.assertEqual(len(self.games_of(again)), 100)
        stored = [side["pilot"] for side in again["sides"]]
        self.assertEqual(stored, [_pilot(), _pilot("Reckless")])     # sorted by side lists: Default first
        self.assertEqual(again["settings"]["ai"], ["Default", "Reckless"])
        for first_g, _, profiles, _ in sent:
            deck1 = seeds.deck1_side(first_g, again["seeds"]["flip"])
            self.assertEqual(profiles, (stored[deck1]["profile"], stored[1 - deck1]["profile"]))
        self.assertEqual({profiles for *_, profiles, _ in sent}, {("Default", "Reckless"), ("Reckless", "Default")})
        self.assertEqual(again["runs"][1]["failed"], 0)

    def test_default_pilots_keep_wave_2s_requests(self):
        sent = self.asked()
        self.run_matchup(25, exact=True)
        self.assertTrue(sent)
        self.assertTrue(all(args == _w2_request_args(
            {"decks_dir": self.setup_()["decks_dir"], "clock_s": 120}, "Constructed", args[args.index("-d") + 1],
            args[args.index("-d") + 2], n, 1, v2={"stream": args[args.index("-dlgame") + 1], "first": g})
            for g, n, _, args in sent))

    def test_a_switch_the_engine_cant_play_is_refused_before_anything_plays(self):
        a, b = self.mirror()
        with mock.patch.object(forge.pilots, "check_switches", side_effect=ValueError("No team-pump fix here.")), \
                self.assertRaises(forge.ForgeError) as caught:
            forge.run(a, b, 25, by="x", results_dir=self.results, exact=True)
        self.assertEqual(str(caught.exception), "No team-pump fix here.")
        self.assertFalse(self.procs)

    def test_the_echo_check_gets_each_seats_pilot(self):
        seen = []
        real = forge.engine.check_echo

        def check_echo(eng, echo, seat_pilots=None):
            seen.append((int(echo["first"]), seat_pilots, echo.get("ai")))
            return real(eng, echo, seat_pilots=seat_pilots)

        a, b = self.mirror()
        with mock.patch.object(forge.engine, "check_echo", check_echo):
            result = forge.run(a, b, 50, by="x", results_dir=self.results, exact=True)
        stored = [side["pilot"] for side in result["sides"]]
        self.assertTrue(seen)
        for first, pilots_, ai in seen:
            deck1 = seeds.deck1_side(first, result["seeds"]["flip"])
            self.assertEqual(pilots_, [stored[deck1], stored[1 - deck1]])
            self.assertEqual(ai, f"{pilots_[0]['profile']},{pilots_[1]['profile']}")



class OverrideTests(RunHookCase):
    """override_sets and ensure_deployed, with stand-ins for E3's user folders and deploys: each
    folder's intended files (self.intended) are what ensure_deployed puts in its custom/cards."""

    def setUp(self):
        super().setUp()
        self.intended = {}
        self.calls = []
        exp = self.tmp / "data" / "forge" / "users" / "exp-test"

        def user_dir_for(sets, *, performance_mode=True):
            self.calls.append(("user_dir_for", list(sets), performance_mode))
            # Its MANIFEST, as E3's writes it: the worker start (_prepare_user_dir) reads the
            # folder's PERFORMANCE_MODE from it.
            exp.mkdir(parents=True, exist_ok=True)
            (exp / forge.overrides.MANIFEST).write_text(json.dumps({"sets": list(sets),
                                                                  "performance_mode": bool(performance_mode)}),
                                                      encoding="utf-8")
            return exp

        def ensure_deployed(user_dir):
            self.calls.append(("ensure_deployed", str(user_dir)))
            folder = Path(user_dir) / "Forge" / "custom" / "cards"
            folder.mkdir(parents=True, exist_ok=True)
            want = self.intended.get(str(user_dir), {})
            for path in folder.rglob("*"):
                if path.is_file() and path.name not in want:
                    path.unlink()
            for name, text in want.items():
                (folder / name).write_text(text, encoding="utf-8", newline="\n")
            return {"index": forge.overrides.deployed_index(user_dir),     # E3's answer: the key's
                    "hash": forge.overrides.deployed_hash(user_dir)}           # per-list overrides read the index

        real_current = forge.engine.current

        def current(setup, card_log):
            self.calls.append(("current", str(setup["user_dir"])))
            return real_current(setup, card_log)

        for p in (mock.patch.object(forge.overrides, "user_dir_for", user_dir_for),
                  mock.patch.object(forge.overrides, "ensure_deployed", ensure_deployed),
                  mock.patch.object(forge.engine, "current", current)):
            p.start()
            self.addCleanup(p.stop)
        self.exp = exp

    def echoed(self, logs, key):
        """The overrides= of every DLENGINE line in the tee'd logs of key."""
        out = set()
        for path in (logs / key).glob("*.log.gz"):
            for line in _gz_lines(path):
                if line.startswith("DLENGINE|"):
                    out.add(forge.logreader.engine_fields(line)["overrides"])
        return out

    def test_an_override_sets_run_plays_in_its_folder_whose_workers_keep_its_files(self):
        self.intended[str(self.exp)] = {"fiery_annihilation.txt": "Name:Fiery Annihilation\nA:edited\n"}
        logs = self.tmp / "logs"
        own = self.pool_(workers=2)
        arm = self.run_matchup(25, exact=True, override_sets=["fiery"], pool=own, log_dir=logs,
                               key="1" * 64, kind="experiment")
        self.assertEqual(self.calls[:3], [("user_dir_for", ["fiery"], True), ("ensure_deployed", str(self.exp)),
                                          ("current", str(self.exp))])
        exp_hash = forge.overrides.deployed_hash(self.exp)
        self.assertNotEqual(exp_hash, "none")
        self.assertEqual(self.echoed(logs, arm["key"]), {exp_hash})
        real = self.run_matchup(25, exact=True, pool=own, log_dir=logs)
        self.assertEqual(self.echoed(logs, real["key"]), {"none"})
        # A pool worker of the arm's launch kept its files while the real folder's played: the
        # launch identity holds the user folder and its overrides.
        launches = {json.dumps(pool.launch(self.setup_(user_dir=d), forge.engine.current(self.setup_(user_dir=d),
                                                                                         dict(CARD_LOG))),
                               sort_keys=True) for d in (self.exp, forge.common._user_dir())}
        self.assertEqual(len(launches), 2)
        self.assertEqual(arm["runs"][0]["failed"] + real["runs"][0]["failed"], 0)

    def test_a_deploy_before_a_run_gives_new_workers_and_the_new_key(self):
        logs = self.tmp / "logs"
        own = self.pool_(workers=2)
        before = self.run_matchup(25, exact=True, pool=own, log_dir=logs)
        self.assertEqual(self.echoed(logs, before["key"]), {"none"})
        # sets.json changes: the next run's ensure_deployed puts a file in the real folder.
        self.intended[str(forge.common._user_dir())] = {"x.txt": "Name:Fiery Annihilation\n"}
        after = self.run_matchup(25, exact=True, pool=own, log_dir=logs)
        self.assertNotEqual(after["key"], before["key"])
        now = forge.overrides.deployed_hash(forge.common._user_dir())
        self.assertEqual(self.echoed(logs, after["key"]), {now})
        self.assertEqual((after["runs"][0]["failed"], after["runs"][0]["played"]), (0, 25))
        order = [call[0] for call in self.calls if call[0] in ("ensure_deployed", "current")]
        self.assertEqual(order[:2], ["ensure_deployed", "current"])

    def test_the_folder_gets_the_configs_performance_mode(self):
        self.settings["forge_performance_mode"] = False
        self.run_matchup(25, exact=True, override_sets=["fiery"], key="2" * 64, kind="experiment")
        self.assertEqual(self.calls[0], ("user_dir_for", ["fiery"], False))
        with self.assertRaises(ValueError):
            self.run_matchup(25, exact=True, override_sets="fiery")



class StopFileTests(RunHookCase):

    def test_the_stop_file_stops_a_run_as_stop_does(self):
        self.fake("delay=0.02")
        stop = self.tmp / "stop"
        os.environ[runner.STOP_FILE_ENV] = str(stop)

        def progress(done, total, detail):
            if done >= 20:
                stop.write_text("", encoding="utf-8")

        with self.assertRaises(forge.common.Stopped) as caught:
            self.run_matchup(200, exact=True, progress=progress)
        saved = self.saved()
        run = saved["runs"][0]
        self.assertTrue(run["stopped"])
        self.assertGreaterEqual(run["played"], 20)
        self.assertLess(run["played"], 200)
        self.assertEqual(caught.exception.saved_games, run["played"])
        # With the file there, a run stops at once: nothing sent, claimed or saved.
        sent = self.asked()
        with self.assertRaises(forge.common.Stopped) as caught:
            self.run_matchup(25, exact=True, results_dir=self.tmp / "none")
        self.assertEqual(caught.exception.saved_games, 0)
        self.assertEqual(sent, [])
        self.assertFalse((self.tmp / "none").exists() and list((self.tmp / "none").iterdir()))
        os.environ.pop(runner.STOP_FILE_ENV)
        self.assertEqual(self.run_matchup(25, exact=True, results_dir=self.tmp / "none")["runs"][-1]["played"], 25)

    def test_a_stopped_run_stops_the_replay(self):
        plan = [{"key": k * 64, "a": entry(GREEN), "b": entry(RED), "games": 25} for k in "abc"]
        calls = []

        def run(a, b, games, **kwargs):
            calls.append(kwargs)
            stopped = forge.common.Stopped("Stopped: the stop file exists")
            stopped.saved_games = 7
            raise stopped

        with mock.patch.object(runner, "run", run), mock.patch.object(forge.cli, "_replay_name", return_value="x"):
            with self.assertRaises(KeyboardInterrupt) as caught:
                forge.cli._replay(plan, self.results, True, 1)
        self.assertEqual(len(calls), 1)                 # no other matchup started
        self.assertEqual(caught.exception.saved_games, 7)



class IdentityTests(RunHookCase):

    def test_the_launch_and_compatibility_identities_hold_the_launch_fields(self):
        setup = self.setup_()
        eng = forge.engine.current(setup, setup["card_log"])
        found = pool.launch(setup, eng)
        self.assertEqual(found["fields"], forge.engine.launch_fields(setup, eng))
        self.assertNotIn("fields", pool.launch(setup))
        mine = pool.identity(setup, eng)
        self.assertEqual((mine["launch"], mine["pin_mode"]), (forge.engine.launch_fields(setup, eng), "core"))
        other = dict(mine, launch=dict(mine["launch"], user_dir="elsewhere", overrides="f" * 64))
        self.assertEqual(pool._differences(mine, other), ["the card-script overrides", "Forge's user folder"])
        os.environ[forge.cores.PIN_MODE_ENV] = "ccd"
        self.assertEqual(pool._differences(mine, pool.identity(setup, eng)), ["the pin mode (DECKLAB_PIN_MODE)"])

    def test_the_service_carries_pilots_and_the_log_tee_and_refuses_another_folder(self):
        own = self.pool_(name="server")
        own.service = pool._Service(own)
        self.addCleanup(own.service.close)
        logs = self.tmp / "logs"
        sent = self.asked()
        a, b = PilotTests.mirror(self)
        result = forge.run(a, b, 50, by="x", results_dir=self.results, exact=True, log_dir=logs)
        self.assertEqual(result["runs"][0]["pool"], "remote")
        stored = [side["pilot"] for side in result["sides"]]
        for first, _, profiles, _ in sent:
            deck1 = seeds.deck1_side(first, result["seeds"]["flip"])
            self.assertEqual(profiles, (stored[deck1]["profile"], stored[1 - deck1]["profile"]))
        self.assertTrue(list((logs / result["key"]).glob("*.log.gz")))
        # A run in another user folder (override sets) never plays in the server's pool.
        exp = self.tmp / "data" / "forge" / "users" / "exp-x"
        logged = []
        with mock.patch.object(forge.overrides, "user_dir_for", return_value=exp), \
                mock.patch.object(forge.common, "_log", logged.append):
            arm = self.run_matchup(25, exact=True, override_sets=["etb"], key="3" * 64, kind="experiment")
        self.assertEqual(arm["runs"][0]["pool"], "local")
        self.assertEqual(len(logged), 1)
        self.assertIn("Forge's user folder", logged[0])
        # The service checks the wire's pilots and log.
        job = self.job()
        for bad in ({"pilots": [{"profile": "Bad name!", "switches": []}, _pilot()]},
                    {"pilots": [_pilot()]}, {"log": {"dir": "relative", "every": 1}},
                    {"log": {"dir": str(self.tmp), "every": 0}}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pool._service_job(dict(pool._wire(job), **bad), job["setup"], job["engine"])
        good = pool._service_job(dict(pool._wire(job), pilots=[_pilot(), _pilot("Reckless", ["team-pump-1"])],
                                      log={"dir": str(self.tmp), "every": 2}), job["setup"], job["engine"])
        self.assertEqual((good["pilots"][1]["switches"], good["log"]["every"]), (["team-pump-1"], 2))



if __name__ == "__main__":
    unittest.main()
