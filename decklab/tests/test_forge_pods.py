"""Pure pod planning and fake-process qualification; never launches real Forge."""
import contextlib
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import jobs
from decklab.lib.forge import common, pods, simjar
from decklab.lib.gauntlet import pod_lineups


def entries():
    return [{"id": f"commander/pod-{i}", "version": "target", "title": f"Pod {i}",
             "kind": "commander", "card_sha": str(i + 1) * 64, "dck": f"[Main]\n{i + 1} Forest\n"}
            for i in range(4)]


def win(number, seat=1):
    return f"Game Result: Game {number} ended in 100 ms. Ai({seat})-Deck has won!\n"


def saved(chosen, eng=None):
    options = pods._options(16, 180, pods.DEFAULT_SEED)
    return {"pod_version": pods.VERSION, "kind": "pods", "key": pods.key(chosen, eng=eng),
            "sides": pods._sides(chosen), "engine": eng, "options": options, "batches": []}


class PodPureTests(unittest.TestCase):
    def test_four_commander_decks_and_only_balanced_bounded_sample_sizes(self):
        chosen = entries()
        self.assertEqual(pods.check(chosen), chosen)
        for bad in (chosen[:3], [chosen[0]] * 4, [dict(chosen[0], kind="casual"), *chosen[1:]]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pods.check(bad)
        for size in (True, 0, 4, 15, 256, "16"):
            with self.subTest(size=size), self.assertRaises(ValueError):
                pods.plan(chosen, size)

    def test_every_full_rotation_gives_each_deck_every_seat_equally(self):
        chosen = entries()
        for size in pods.GAMES:
            planned = pods.batches(chosen, size)
            self.assertEqual(sum(batch["pods"] for batch in planned), size)
            for entry in chosen:
                positions = [sum(batch["pods"] for batch in planned if batch["seats"][seat] == entry["id"])
                             for seat in range(4)]
                self.assertEqual(positions, [size // 4] * 4)

    def test_key_binds_order_snapshots_sample_options_and_actual_engine(self):
        chosen = entries()
        original = pods.key(chosen, eng={"jar_sha": "a"})
        variants = [(list(reversed(chosen)), 16, {"jar_sha": "a"}),
                    ([dict(chosen[0], card_sha="f" * 64), *chosen[1:]], 16, {"jar_sha": "a"}),
                    (chosen, 32, {"jar_sha": "a"}), (chosen, 16, {"jar_sha": "b"})]
        for decks, size, eng in variants:
            self.assertNotEqual(original, pods.key(decks, size, eng=eng))
        self.assertEqual(original, pods.key([dict(entry, title="Renamed") for entry in chosen], eng={"jar_sha": "a"}))

    def test_clock_stops_and_multiple_survivors_never_become_wins(self):
        reader = pods.PodReader()
        for line in ("Stopping slow match as draw\n", win(1, 4),
                     "Game Outcome: Ai(2)-Deck has won because survived.\n",
                     "Game Outcome: Ai(3)-Deck has won because survived.\n", win(2, 3),
                     "Game Result: Game 3 ended in a Draw! Took 50 ms.\n", win(4, 2)):
            reader.feed(line)
        self.assertEqual([game["result"] for game in reader.games], ["clock", "clock", "draw", "win"])
        self.assertEqual([game["w"] for game in reader.games], [None, None, None, 2])

    def test_reader_rejects_duplicate_game_numbers_and_out_of_range_seats(self):
        reader = pods.PodReader()
        reader.feed(win(1, 5))
        reader.feed(win(2))
        reader.feed(win(2))
        self.assertTrue(reader.invalid)
        self.assertEqual(len(reader.games), 1)

    def test_win_share_denominator_includes_draws_and_excludes_clock_stops(self):
        chosen = entries()
        reader = pods.PodReader()
        for line in (win(1), "Game Result: Game 2 ended in a Draw! Took 50 ms.\n",
                     "Stopping slow match as draw\n", win(3, 4)):
            reader.feed(line)
        nums = pods.summary([{"seats": [entry["id"] for entry in chosen], "games": reader.games}], chosen)
        self.assertEqual((nums["pods"], nums["counted"], nums["wins"], nums["draws"], nums["clock_stops"]), (3, 2, 1, 1, 1))
        first = nums["by_deck"][chosen[0]["id"]]
        self.assertEqual((first["wins"], first["pods"], first["rate"]), (1, 2, 0.5))
        self.assertEqual(first["range"], [0.0945, 0.9055])
        self.assertEqual(nums["by_deck"][chosen[3]["id"]]["wins"], 0)
        self.assertIsNone(pods.summary([], chosen)["by_deck"][chosen[0]["id"]]["range"])

    def test_published_pod_persists_sources_and_counts_the_saved_deck_in_each_rotated_seat(self):
        chosen = entries()
        for index, entry in enumerate(chosen[1:], 1):
            entry.update(id=f"gauntlet:precon/Fixture_{index}", precon_source="mtgjson")
        found = saved(chosen)
        for batch in pods.batches(chosen):
            seat = batch["seats"].index(chosen[0]["id"]) + 1
            reader = pods.PodReader()
            reader.feed(win(1, seat))
            reader.feed("Game Result: Game 2 ended in a Draw! Took 50 ms.\n")
            reader.feed("Stopping slow match as draw\n")
            reader.feed(win(3, seat))
            found["batches"].append(dict(batch, attempt=0, games=reader.games, failed=False, stopped=False))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pods._save(found, root)
            result = pods.load(found["key"], root)
        self.assertEqual(result["summary"]["clock_stops"], 4)
        main = result["summary"]["by_deck"][chosen[0]["id"]]
        self.assertEqual((main["wins"], main["pods"], main["rate"]), (4, 8, 0.5))
        self.assertEqual(main["by_seat"], {str(seat): pods._win_share(1, 2) for seat in range(1, 5)})
        self.assertEqual(pod_lineups.public_source(result["sides"][1])["source_name"], "MTGJSON")
        self.assertNotEqual(pods.key([*chosen[:3], dict(chosen[3], precon_source="forge")]), found["key"])

    def test_saved_validator_binds_provenance_and_rejects_extra_completed_games(self):
        chosen = entries()
        found = saved(chosen)
        self.assertTrue(pods.is_saved(found, found["key"]))
        changed = copy.deepcopy(found)
        changed["sides"][3]["id"] = "commander/changed"
        self.assertFalse(pods.is_saved(changed, found["key"]))
        reader = pods.PodReader()
        reader.feed(win(1))
        row = dict(pods.batches(chosen)[0], attempt=0, games=reader.games, failed=False, stopped=False)
        found["batches"] = [row]
        self.assertTrue(pods.is_saved(found, found["key"]))
        for field, value in (("ai_to", "bad"), ("ms", -1), ("first", 5), ("turns", True)):
            broken = copy.deepcopy(found)
            broken["batches"][0]["games"][0][field] = value
            self.assertFalse(pods.is_saved(broken, found["key"]))
        row["games"] = reader.games * 5
        self.assertFalse(pods.is_saved(found, found["key"]))

    def test_load_is_installation_independent_and_nested_under_ordinary_results_root(self):
        chosen = entries()
        found = saved(chosen)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pods._save(found, root)
            self.assertTrue((root / "pods" / (found["key"] + ".json")).is_file())
            with mock.patch.object(pods.install, "_setup", side_effect=AssertionError("read started setup")):
                result = pods.load(found["key"], root)
            self.assertTrue(result["statistical_only"])
            self.assertEqual(result["summary"]["counted"], 0)
            self.assertNotIn("dck", json.dumps(result))
            self.assertEqual(pods.results(root), [result])
            with mock.patch.object(pods, "MAX_SAVED_BYTES", 4), self.assertRaises(common.ForgeError):
                pods.load(found["key"], root)
            with mock.patch.object(pods.lifecycle, "_ordinary", side_effect=pods.lifecycle.LifecycleError("unsafe")), \
                    self.assertRaises(common.ForgeError):
                pods.load(found["key"], root)
            (root / "pods" / (found["key"] + ".json")).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(common.ForgeError, "cannot be read"):
                pods.load(found["key"], root)
            with self.assertRaises(ValueError):
                pods.load("../../outside", root)

    def test_engine_identity_hashes_replaced_jar_and_command_disables_fork_patches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            jar = root / "forge.jar"
            jar.write_bytes(b"engine 1")
            scripts = root / pods.install.SCRIPTS_ZIP
            scripts.parent.mkdir(parents=True)
            scripts.write_bytes(b"scripts")
            setup = {"forge_dir": root, "jar": "forge.jar", "version": "fixture", "user_dir": root,
                     "java": "java", "xmx": "1G", "decks_dir": root, "game_patches": False,
                     "card_log": {"ready": False}}
            with mock.patch.object(pods.engine, "_ai_sha", return_value="ai"), \
                    mock.patch.object(pods.engine, "_overrides", return_value="none"), \
                    mock.patch.object(pods.install, "engine_forge", return_value="fixture"):
                old = pods.engine_identity(setup)
                jar.write_bytes(b"engine 2 changed")
                new = pods.engine_identity(setup)
            self.assertNotEqual(old["jar_sha"], new["jar_sha"])
            argv = pods.command(setup, ["a.dck", "b.dck", "c.dck", "d.dck"], 4, 10, 180)
            self.assertIn(simjar.GAME_PATCHES_OFF, argv)
            self.assertEqual(argv[argv.index("-d") + 1:argv.index("-n")], ["a.dck", "b.dck", "c.dck", "d.dck"])


class Lease:
    def __init__(self, events):
        self.events = events
        self.released = False

    def release(self):
        if self.released:
            raise AssertionError("lease released twice")
        self.released = True
        self.events.append("release")


class FakeProcess:
    def __init__(self, lines, *, block=False, events=None):
        self.returncode = None
        self.killed = threading.Event()
        self.block = block
        self.events = events if events is not None else []
        self.stdout = self.Stream(self, lines) if block else io.StringIO(lines)

    class Stream:
        def __init__(self, proc, lines):
            self.proc, self.lines = proc, lines

        def __iter__(self):
            yield from self.lines.splitlines(keepends=True)
            self.proc.killed.wait(3)

        def close(self):
            pass

    def wait(self):
        self.returncode = -9 if self.killed.is_set() else 0
        self.events.append("reap")
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.events.append("kill")
        self.killed.set()


class PodRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.chosen = entries()
        self.eng = {"fixture": "engine-one"}
        self.run_key = pods.key(self.chosen, eng=self.eng)
        self.events, self.commands, self.leases = [], [], []
        self.setup = {"forge_dir": self.root, "jar": "forge.jar", "version": "fixture", "java": "java",
                      "xmx": "1G", "workers": 4, "decks_dir": self.root / "decks", "user_dir": self.root / "user"}
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for target, values in (
                (pods.install, {"_setup": mock.Mock(return_value=self.setup)}),
                (pods, {"engine_identity": mock.Mock(return_value=self.eng), "START_GAP": 0, "POLL_S": 0.001}),
                (pods.runner, {"_write_decks": mock.Mock(), "_prepare_user_dir": mock.Mock(return_value={}),
                               "_tidy_user_dir": mock.Mock()}),
                (pods.processes, {"start_process": self.start, "kill_process": lambda proc: proc.kill(),
                                  "_end_process": lambda proc: self.events.append("end")}),
                (pods.slots, {"claim": self.claim})):
            for name, value in values.items():
                self.stack.enter_context(mock.patch.object(target, name, value))
        self.want = mock.Mock()
        self.stack.enter_context(mock.patch.object(pods.slots, "want", return_value=self.want))
        self.block_first = False

    def claim(self, *args, **kwargs):
        self.assertFalse(kwargs["wait"])
        lease = Lease(self.events)
        self.leases.append(lease)
        return lease

    def start(self, argv, **options):
        self.commands.append(argv)
        count = int(argv[argv.index("-n") + 1])
        block = self.block_first and len(self.commands) == 1
        return FakeProcess("".join(win(number) for number in range(1, (1 if block else count) + 1)),
                           block=block, events=self.events)

    def run_(self, **options):
        return pods.run(self.chosen, by="Matt", results_dir=self.root, expected_key=self.run_key, **options)

    def test_run_uses_shared_budget_four_seats_and_does_not_replay_complete_results(self):
        result = self.run_()
        self.assertEqual((result["completed"], result["remaining"]), (16, 0))
        self.assertEqual(len(self.commands), 4)
        self.assertTrue(all(lease.released for lease in self.leases))
        self.assertTrue(all(simjar.GAME_PATCHES_OFF in argv for argv in self.commands))
        self.assertEqual(sorted(row["wins"] for row in result["summary"]["by_deck"].values()), [4, 4, 4, 4])
        self.run_()
        self.assertEqual(len(self.commands), 4)

    def test_stale_engine_or_list_is_refused_before_any_process_or_checkpoint(self):
        self.run_key = "a" * 64
        with self.assertRaisesRegex(common.ForgeError, "changed"):
            self.run_()
        self.assertFalse(self.commands)
        self.assertFalse((self.root / "pods").exists())

    def test_stop_while_budget_is_unavailable_launches_nothing_and_preserves_checkpoint(self):
        calls = []

        def progress(done, total, detail):
            calls.append(detail)
            if len(calls) > 1:
                raise jobs.Stopped("stopped")

        with mock.patch.object(pods.slots, "claim", return_value=[]), self.assertRaises(jobs.Stopped):
            self.run_(progress=progress)
        self.assertFalse(self.commands)
        self.assertEqual(pods.load(self.run_key, self.root)["state"], "stopped")
        self.want.release.assert_called_once_with()

    def test_cancel_blocked_output_kills_and_reaps_before_release_then_resumes_new_seed(self):
        self.block_first = True

        def progress(done, total, detail):
            if done:
                stop = jobs.Stopped("stopped")
                stop.by = "Matt"
                raise stop

        with self.assertRaises(jobs.Stopped):
            self.run_(progress=progress, procs=1)
        partial = pods.load(self.run_key, self.root)
        self.assertEqual((partial["completed"], partial["stopped_by"]), (1, "Matt"))
        self.assertLess(self.events.index("kill"), self.events.index("reap"))
        self.assertLess(self.events.index("reap"), self.events.index("release"))
        initial_seed = self.commands[0][self.commands[0].index("-s") + 1]
        self.block_first = False
        result = self.run_(procs=1)
        self.assertEqual(result["completed"], 16)
        resumed = self.commands[1]
        self.assertEqual(resumed[resumed.index("-n") + 1], "3")
        self.assertNotEqual(resumed[resumed.index("-s") + 1], initial_seed)

    def test_failed_start_is_counted_and_zero_completed_run_reports_error(self):
        with mock.patch.object(pods.processes, "start_process", side_effect=OSError("fixture")), \
                self.assertRaisesRegex(common.ForgeError, "no pod games"):
            self.run_()
        result = pods.load(self.run_key, self.root)
        self.assertEqual(result["summary"]["failed_batches"], 4)
        self.assertEqual(result["completed"], 0)
        self.assertTrue(all(lease.released for lease in self.leases))
