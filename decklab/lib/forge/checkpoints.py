"""Durable v2 progress, published under the matchup's existing OS claim.

A checkpoint is an ordinary result with one unfinished run, not a second source
of truth. Every write replaces that same run from an immutable pre-run base.
Readers can use its validated games immediately. A subsequent claimed run marks
it recovered and plans from next_game, preserving reserved ordinary-matchup holes.
"""
import json
import time

from . import common, engine

SECONDS = 5.0
GAMES = 100
INTERRUPTED = "Recovered completed games from an interrupted run."


def recover(existing, eng, ordered):
    """Validate and mark an unfinished run in memory, while its claim is held.

    Its next durable checkpoint/final save records this recovery. Refusal leaves
    the original bytes alone, including custom paired/experiment result keys.
    """
    if not existing or not any(r.get("checkpoint") for r in existing["runs"]):
        return
    expected = engine.result_fields(eng, ordered).get("engine")
    sides_match = all(
        all(side.get(k) == value for k, value in engine.side_fields(eng, entry, {}).items())
        for side, entry in zip(existing["sides"], ordered))
    if (existing.get("engine") != expected or
            not sides_match or
            [(s["card_sha"], s["dck"]) for s in existing["sides"]] !=
            [(s["card_sha"], s["dck"]) for s in ordered]):
        raise common.ForgeError("The interrupted run belongs to different lists or a different engine; "
                                "its saved games were left unchanged.")
    for run in existing["runs"]:
        if run.pop("checkpoint", False):
            run.update(recovered=True, stopped=True, recovery_note=INTERRUPTED)


def empty_stats():
    return {"wall_s": 0, "startup_s": None, "waited_s": 0, "most_running": 0,
            "chunks": 0, "played_batches": 0, "partial": 0, "batch_games": 0,
            "recycled": 0, "requeued": 0, "pool": None}


class Writer:
    """Publish the first completed chunk, then at most every 5s or 100 games.

    build(record, fails, stats) always starts from the same pre-run base. The
    initial empty snapshot reserves the complete range before any worker starts.
    OSError is fatal to the current run, which still attempts its normal final
    save; the last complete checkpoint remains readable if that also fails.
    """

    def __init__(self, path, build):
        self.path, self.build = path, build
        self.at, self.games = None, 0

    def reserve(self):
        self._write(None, [], empty_stats())

    def publish(self, games, snapshot):
        now = time.monotonic()
        if games <= self.games or (self.at is not None and now - self.at < SECONDS and games - self.games < GAMES):
            return
        record, fails, stats = snapshot()
        self._write(record, fails, stats)
        self.at, self.games = now, games

    def _write(self, record, fails, stats):
        result = self.build(record, fails, stats)
        result["runs"][-1].update(checkpoint=True, stopped=True)
        try:
            common._write_atomic(self.path, json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        except OSError as error:
            common._log(f"A matchup checkpoint couldn't be saved as {self.path}: {error}")
            raise common.ForgeError("Deck Lab couldn't checkpoint this run; its last saved games are preserved.") from None
