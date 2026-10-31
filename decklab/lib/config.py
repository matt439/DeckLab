"""Paths and settings shared by the Deck Lab modules.

Settings come from decklab/config.json when it exists, on top of DEFAULTS. The combined run's
harness can merge one more JSON file over them: the file the environment variable
DECKLAB_CONFIG_EXTRA names (forge-trial/sim-wave3-contract.md section 17; one log line names it).
"""
import json
import os
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKOUT = REPO                  # this checkout, even while a test points REPO at a temporary one
DECKLAB = REPO / "decklab"
DATA = DECKLAB / "data"          # gitignored cache
MAGIC = REPO / "magic"
CONFIG_FILE = DECKLAB / "config.json"

# Sent with every Scryfall / Frankfurter request (Scryfall requires one).
USER_AGENT = "DeckLab/0.1 (personal deck tool)"

# The Forge numbers are the ones Milestone 0 measured (PLAN.md part 6): 16
# workers (12 while the PC is in use for other things), each Forge process
# capped at 1 GB of Java heap, and Forge's own 120-second clock per game.
# forge_batch_games no longer changes anything: since 2026-10-03 forge/lists.py
# splits a run among the workers itself (_batch_count), and the Forge set-up
# no longer checks it. It's kept so older config.json files still load, and
# the server still sends it to the page as "batch_games" (which the page
# ignores), so it keeps its default here. forge_java is the JDK's java.exe; None finds the newest
# Java 21+ in the JDK installers' Program Files folders (forge/install.py's find_java; never the
# small launcher on the PATH, which starts the real one as a second process).
# The practice-hand simulation (lib/goldfish/) uses one process per core, up
# to 16 (the PC's physical cores).
# The warm pool (forge/pool.py, simulation wave 2): forge_pool_idle_s is how long its warm Forge
# workers stay up with nothing to play (900: 15 minutes, the owner's choice of 2026-10-03), and
# forge_pin pins each worker to one physical core while it plays (the V-Cache cores first);
# false leaves Windows to place them (for comparing the two).
# Simulation wave 3 (forge-trial/sim-wave3-contract.md section 17): forge_field_inflight is how many
# pair runs a field run or a variant test plays at once; forge_variant_margin and
# forge_variant_margin_one are a variant test's "makes little difference" margins against the field
# and against one deck (the owner's choice of 2026-10-03); forge_performance_mode and
# forge_game_patches are battery knobs for the combined run (both true for every real run).
# forge_decision_log (AI round 1) lists the card names whose AI decisions Forge prints as DLAI| lines
# (forge/decisionlog.py); empty (the default) prints none.
FORGE_WORKERS_MAX = 16          # the measured default (above); a smaller PC's is less (_forge_workers)
WORKER_RAM_GB = 1.5             # one Forge worker: its 1 GB heap (forge_xmx) and the JVM's own
RESERVED_RAM_GB = 6             # left for Windows, the server, PostgreSQL and a browser


def _ram_gb():
    """The PC's physical memory in GB, or None when it can't be read."""
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong), ("virtual_avail", ctypes.c_ulonglong),
                            ("extended", ctypes.c_ulonglong)]
            status = _Status(length=ctypes.sizeof(_Status))
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.total / 2 ** 30
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2 ** 30
    except (AttributeError, OSError, ValueError):
        return None


def _forge_workers(cpus=None, ram_gb=None):
    """forge_workers' default (E11-S48): FORGE_WORKERS_MAX, or fewer on a PC without one physical
    core (about half the logical ones) and WORKER_RAM_GB each after RESERVED_RAM_GB; at least 1.
    This PC (32 logical, 64 GB) gets 16."""
    cpus = cpus or os.cpu_count() or 2
    ram_gb = _ram_gb() if ram_gb is None else ram_gb
    workers = min(FORGE_WORKERS_MAX, cpus // 2)
    if ram_gb is not None:
        workers = min(workers, int((ram_gb - RESERVED_RAM_GB) // WORKER_RAM_GB))
    return max(1, workers)


DEFAULTS = {
    "port": 8642,
    "forge_dir": r"C:\Tools\forge-decklab",     # Deck Lab's build of its fork of Forge (forge/simjar.py)
    "forge_java": None,
    "forge_workers": _forge_workers(),
    "forge_batch_games": 200,
    "forge_clock_s": 120,
    "forge_xmx": "1024m",
    "forge_pool_idle_s": 900,
    "forge_pin": True,
    "forge_field_inflight": 4,
    "forge_variant_margin": 0.02,
    "forge_variant_margin_one": 0.03,
    "forge_performance_mode": True,
    "forge_game_patches": True,
    "forge_decision_log": [],
    "goldfish_workers": min(16, os.cpu_count() or 1),
}


# The environment variable naming a JSON file merged over config.json (the combined run's battery
# knobs, harness only: forge-trial/sim-wave3-contract.md section 17).
EXTRA_ENV = "DECKLAB_CONFIG_EXTRA"

_said = set()                   # the extra files already logged (each once a process)
_said_lock = threading.Lock()


def load():
    """Return DEFAULTS overlaid with decklab/config.json, if present, and then with the JSON
    file DECKLAB_CONFIG_EXTRA names, if set (_extra)."""
    settings = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        settings.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    extra = os.environ.get(EXTRA_ENV)
    if extra:
        settings.update(_extra(extra))
    return settings


def records_dir(root=None):
    """Where the repo-relative research files that sources name (magic/buylists/..., magic/reports/...)
    are looked for: config.json's records_repo, the household's own private repo, when root is this
    checkout (or None); otherwise root itself, so a test's temporary repo never reads the real one."""
    root = Path(REPO if root is None else root)
    if root.resolve() == CHECKOUT.resolve():
        setting = load().get("records_repo")
        if isinstance(setting, str) and setting.strip():
            return Path(setting.strip())
    return root


def _extra(path):
    """The settings in the file DECKLAB_CONFIG_EXTRA names: a JSON object. One log line a
    process says it's merged; a file that can't be read as one is left out, and the line says
    why (so the harness sees a knob that didn't apply)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("it isn't a JSON object")
    except (OSError, ValueError) as e:
        _say_once((path, "bad"), f"{EXTRA_ENV} names {path}, which can't be read as settings ({e}), so only "
                                 f"config.json's are used.")
        return {}
    _say_once((path, "ok"), f"Settings from {path} ({EXTRA_ENV}) are merged over config.json's: "
                            f"{', '.join(sorted(data)) or 'none'}.")
    return data


def _say_once(what, text):
    """A line on stderr (the server window's, as forge's common._log writes), the first time
    what comes up in this process."""
    with _said_lock:
        if what in _said:
            return
        _said.add(what)
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()
