"""What CI's test jobs print after a run: why tests skipped (and how many), the slowest modules,
and timings for balancing the shards. Shared by scripts/test_shard.py and scripts/test_db.py.

Standard library only, and it imports nothing from decklab: test_shard.py imports it before the
fixture guards are installed.
"""
import json
import os
import re
import time
import unittest
from collections import Counter
from pathlib import Path

WEIGHTS = Path(__file__).resolve().parent / "test_weights.json"
_HOLDER = re.compile(r"^(setUpClass|setUpModule) \((.+)\)$")
DEFAULT_SECONDS_PER_TEST = 0.05


def platform_key():
    return "windows" if os.name == "nt" else "linux"


def tests_of(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from tests_of(test)
        else:
            yield test


class TimedSuite(unittest.TestSuite):
    """One module's tests, timing how long they take (its class fixtures included)."""
    def __init__(self, name, tests):
        super().__init__(tests)
        self.name, self.seconds = name, 0.0

    def run(self, result, debug=False):
        start = time.perf_counter()
        try:
            return super().run(result, debug)
        finally:
            self.seconds += time.perf_counter() - start


def load_weights(path=WEIGHTS):
    """{module: seconds} for this OS (the other OS's when it has none), else {}."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    for key in (platform_key(), "windows", "linux"):
        if isinstance(data.get(key), dict) and data[key]:
            return {m: float(s) for m, s in data[key].items() if isinstance(s, (int, float))}
    return {}


def balance(sizes, count, weights):
    """Deal modules into count shards, heaviest first onto the lightest shard (greedy LPT).

    sizes is {module: number of tests}. A module without a recorded weight is estimated from
    its test count at the recorded modules' mean seconds per test, so a new module only costs
    balance, never coverage. Deterministic: every shard works out the same plan."""
    known = {m: weights[m] for m in sizes if m in weights}
    known_tests = sum(sizes[m] for m in known)
    per_test = (sum(known.values()) / known_tests) if known_tests and sum(known.values()) > 0 \
        else DEFAULT_SECONDS_PER_TEST
    weight = {m: known.get(m, sizes[m] * per_test) for m in sizes}
    loads, bins = [0.0] * count, [[] for _ in range(count)]
    for module in sorted(sizes, key=lambda m: (-weight[m], m)):
        target = min(range(count), key=lambda i: (loads[i], i))
        bins[target].append(module)
        loads[target] += weight[module]
    return [sorted(b) for b in bins], loads


def sizes(suite):
    """(tests per class, tests per module): count them before the run, which empties the suite."""
    by_class, by_module = Counter(), Counter()
    for test in tests_of(suite):
        cls = type(test)
        by_class[f"{cls.__module__}.{cls.__qualname__}"] += 1
        by_module[cls.__module__] += 1
    return by_class, by_module


def skip_ledger(result, counted):
    """[(reason, tests)], most tests first. A setUpClass or setUpModule skip counts every test
    of its class or module (counted by sizes() before the run), which unittest otherwise
    reports as one skip, not in Ran."""
    by_class, by_module = counted
    ledger = Counter()
    for test, reason in result.skipped:
        size = 1
        match = _HOLDER.match(str(test))
        if match:
            size = (by_class if match.group(1) == "setUpClass" else by_module).get(match.group(2), 1)
        ledger[" ".join(str(reason).split())[:160]] += size
    return sorted(ledger.items(), key=lambda item: (-item[1], item[0]))


def report(title, result, counted, timed, timings_out=None):
    """Print the skip ledger and slowest modules; add them to the job summary on GitHub Actions;
    optionally write {module: seconds} as JSON for scripts/test_weights.json."""
    ledger = skip_ledger(result, counted)
    slowest = sorted(timed, key=lambda s: -s.seconds)[:15]
    lines = [f"Skipped, by reason ({sum(n for _, n in ledger)} tests):"]
    lines += [f"{n:6}  {reason}" for reason, n in ledger] or ["     0"]
    lines += ["Slowest modules:"] + [f"{s.seconds:8.1f}s  {s.name}" for s in slowest]
    print("\n".join(lines), flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        md = [f"### {title}", "", f"Ran {result.testsRun} tests: {len(result.failures)} failures, "
              f"{len(result.errors)} errors, {len(result.skipped)} skip results.", "",
              "| Tests skipped | Reason |", "|---:|---|"]
        md += [f"| {n} | {reason.replace('|', '/')} |" for reason, n in ledger]
        md += ["", "| Seconds | Slowest modules |", "|---:|---|"]
        md += [f"| {s.seconds:.1f} | {s.name} |" for s in slowest]
        try:
            with open(summary, "a", encoding="utf-8") as out:
                out.write("\n".join(md) + "\n\n")
        except OSError:
            pass
    if timings_out:
        Path(timings_out).write_text(json.dumps(
            {s.name: round(s.seconds, 2) for s in sorted(timed, key=lambda s: s.name)}, indent=1) + "\n",
            encoding="utf-8")


def merge_timings(folder, out=WEIGHTS):
    """Merge CI's timing artifacts (timings-<windows|linux>-<n>.json under folder) into out."""
    merged = {"windows": {}, "linux": {}}
    for path in sorted(Path(folder).rglob("timings-*.json")):
        key = "windows" if "windows" in path.name else "linux"
        merged[key].update(json.loads(path.read_text(encoding="utf-8")))
    merged = {k: dict(sorted(v.items())) for k, v in merged.items() if v}
    Path(out).write_text(json.dumps(merged, indent=1) + "\n", encoding="utf-8")
    return {k: len(v) for k, v in merged.items()}
