"""The combined run's monitor (forge-trial/sim-combined-run.md section 5.2; wave 3's package H): a
thread of the controller that samples the PC once a second into cpu.csv.

Columns: t (monotonic seconds since the monitor started), unix, own_pct, system_pct, other_pct,
total_pct (each a share of all logical CPUs), idle_s (seconds since the last keyboard or mouse input,
GetLastInputInfo), java_n and java_ws_mb (the run's java.exe processes and their working set).
- own: every process in the run's job (IsProcessInJob, which covers nested jobs);
- system: Defender, Windows Update and maintenance, the search indexer, telemetry (SYSTEM_NAMES);
- other: the rest.
A gap of more than 5 s in the unix column is a sleep or a suspension (the report flags it).

The same Toolhelp and process-time calls as sim-investigation/tools/cpusampler.py (stdlib ctypes),
written here so the run doesn't depend on that gitignored folder."""
import collections
import csv
import sys
import threading
import time

SYSTEM_NAMES = frozenset(("msmpeng.exe", "mpdefendercoreservice.exe", "tiworker.exe", "trustedinstaller.exe",
                          "mousocoreworker.exe", "searchindexer.exe", "compattelrunner.exe"))
FIELDS = ("t", "unix", "own_pct", "system_pct", "other_pct", "total_pct", "idle_s", "java_n", "java_ws_mb")
KEEP_S = 3 * 3600               # samples kept in memory for the controller's questions

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32")
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t), ("d", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    QUERY = 0x1000 | 0x0010         # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ
    STILL_ACTIVE = 259


def snapshot():
    """[(pid, ppid, exe in lower case)] of every process."""
    if sys.platform != "win32":
        return []
    h = _k32.CreateToolhelp32Snapshot(2, 0)
    out, e = [], PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = _k32.Process32FirstW(h, ctypes.byref(e))
    while ok:
        out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile.lower()))
        ok = _k32.Process32NextW(h, ctypes.byref(e))
    _k32.CloseHandle(h)
    return out


def idle_seconds():
    """Seconds since the last keyboard or mouse input."""
    if sys.platform != "win32":
        return 0.0
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _u32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return max(0.0, ((_k32.GetTickCount() & 0xFFFFFFFF) - info.dwTime) & 0xFFFFFFFF) / 1000.0


def _ft(t):
    return (t.dwHighDateTime << 32) | t.dwLowDateTime


def system_times():
    """(idle, total) 100-ns ticks of the whole machine."""
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    return _ft(idle), _ft(kernel) + _ft(user)


def classify(exe, own):
    """A process's class: "own" (in the run's job), "system" (SYSTEM_NAMES) or "other"."""
    if own:
        return "own"
    return "system" if exe in SYSTEM_NAMES else "other"


class _Procs:
    """Open handles to processes, giving each one's CPU (100-ns) since the last look."""

    def __init__(self, job):
        self.job = job
        self.h = {}             # pid -> [handle, last cpu, exe, own]

    def _open(self, pid, exe):
        h = _k32.OpenProcess(QUERY, False, pid) or _k32.OpenProcess(0x1000, False, pid)
        if not h:
            return None
        own = False
        if self.job is not None and getattr(self.job, "handle", None):
            result = wintypes.BOOL()
            own = bool(_k32.IsProcessInJob(h, self.job.handle, ctypes.byref(result))) and bool(result.value)
        entry = [h, self._cpu(h) or 0, exe, own]
        self.h[pid] = entry
        return entry

    @staticmethod
    def _cpu(h):
        c, x, k, u = (wintypes.FILETIME() for _ in range(4))
        if not _k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(x), ctypes.byref(k), ctypes.byref(u)):
            return None
        return _ft(k) + _ft(u)

    def sample(self):
        """{class: cpu ticks since the last sample}, java count, java working set (bytes) of own java."""
        seen = set()
        by_class = {"own": 0, "system": 0, "other": 0}
        java_n, java_ws = 0, 0
        for pid, _, exe in snapshot():
            if pid == 0:
                continue
            seen.add(pid)
            entry = self.h.get(pid)
            if entry is None or entry[2] != exe:
                if entry is not None:
                    _k32.CloseHandle(entry[0])
                entry = self._open(pid, exe)
                if entry is None:
                    continue
                if self.job is not None and entry[3]:
                    pass
            now = self._cpu(entry[0])
            if now is not None:
                by_class[classify(exe, entry[3])] += max(0, now - entry[1])
                entry[1] = now
            if exe == "java.exe" and entry[3]:
                java_n += 1
                pmc = PMC()
                pmc.cb = ctypes.sizeof(pmc)
                if _k32.K32GetProcessMemoryInfo(entry[0], ctypes.byref(pmc), pmc.cb):
                    java_ws += pmc.WorkingSetSize
        for pid in [p for p in self.h if p not in seen]:
            _k32.CloseHandle(self.h.pop(pid)[0])
        return by_class, java_n, java_ws

    def close(self):
        for entry in self.h.values():
            _k32.CloseHandle(entry[0])
        self.h.clear()


class Monitor:
    """The sampling thread, and the controller's questions about the recent samples."""

    def __init__(self, csv_path, job=None, until=None, interval=1.0):
        self.path = csv_path
        self.job = job
        self.until = until
        self.interval = interval
        self.samples = collections.deque()
        self.lock = threading.Lock()
        self._stop = threading.Event()
        self.thread = None
        self.t0 = time.monotonic()
        self.gaps = []

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="overnight-monitor", daemon=True)
        self.thread.start()

    def stop(self):
        self._stop.set()
        if self.thread is not None:
            self.thread.join(10)

    def alive(self):
        return self.thread is not None and self.thread.is_alive()

    def add(self, row):
        """Keep a sample (tests feed rows directly)."""
        with self.lock:
            self.samples.append(row)
            while self.samples and row["t"] - self.samples[0]["t"] > KEEP_S:
                self.samples.popleft()

    def _loop(self):
        if sys.platform != "win32":
            return
        import os
        new = not os.path.exists(self.path)
        procs = _Procs(self.job)
        n = os.cpu_count() or 1
        last_idle, last_total = system_times()
        last_unix = time.time()
        with open(self.path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                writer.writeheader()
            procs.sample()
            while not self._stop.wait(self.interval):
                if self.until is not None and time.time() > self.until:
                    break
                try:
                    by_class, java_n, java_ws = procs.sample()
                    idle, total = system_times()
                    span = max(1, total - last_total)
                    busy = 100.0 * (1 - (idle - last_idle) / span)
                    wall = max(1e-3, (time.time() - last_unix)) * 1e7 * n
                    unix = time.time()
                    if unix - last_unix > 5:
                        self.gaps.append((last_unix, unix))
                    last_idle, last_total, last_unix = idle, total, unix
                    row = {"t": round(time.monotonic() - self.t0, 1), "unix": round(unix, 1),
                           "own_pct": round(100.0 * by_class["own"] / wall, 2),
                           "system_pct": round(100.0 * by_class["system"] / wall, 2),
                           "other_pct": round(100.0 * by_class["other"] / wall, 2),
                           "total_pct": round(busy, 2), "idle_s": round(idle_seconds(), 1), "java_n": java_n,
                           "java_ws_mb": round(java_ws / 1048576)}
                    writer.writerow(row)
                    f.flush()
                    self.add(row)
                except Exception:       # one bad sample is skipped
                    continue
        procs.close()

    # ---------------------------------------------------------------- questions

    def _since(self, seconds):
        now = time.monotonic() - self.t0
        with self.lock:
            return [r for r in self.samples if now - r["t"] <= seconds]

    def _from(self, since_mono):
        start = since_mono - self.t0
        with self.lock:
            return [r for r in self.samples if r["t"] >= start]

    def free_for(self, seconds, other_max=5.0, other_window=None):
        """No input for seconds, and other_pct under other_max on average over other_window (default:
        seconds) — the start's idle gate (600 s, 5 %, 60 s) and the resume rule (300 s, 5 %)."""
        rows = self._since(other_window or seconds)
        if not rows:
            return False
        if rows[-1]["idle_s"] < seconds:
            return False
        return sum(r["other_pct"] for r in rows) / len(rows) < other_max

    def in_use(self):
        """Input in the last 60 s, or other_pct (system excluded) above 15 % for 120 s."""
        rows = self._since(120)
        if not rows:
            return False
        if rows[-1]["idle_s"] < 60:
            return True
        return len(rows) >= 100 and all(r["other_pct"] > 15 for r in rows)

    def in_use_for(self, seconds, other_over=30.0):
        """Input continuing for seconds (every sample with input in the minute before it), or other_pct
        over other_over for all of them."""
        rows = self._since(seconds)
        if len(rows) < seconds * 0.8:
            return False
        return all(r["idle_s"] < 60 for r in rows) or all(r["other_pct"] > other_over for r in rows)

    def noisy(self, since_mono):
        """Was a timing leg since since_mono noisy: any input during it, other + system averaging over
        3 %, or a 30-s window over 10 %?"""
        rows = self._from(since_mono)
        return noisy_rows(rows, since_mono - self.t0)

    def busy_share(self, since_mono):
        """The share of samples since since_mono with the run's Forge workers busy (java_n >= 1)."""
        rows = self._from(since_mono)
        if not rows:
            return 1.0
        return sum(1 for r in rows if r["java_n"] >= 1) / len(rows)


def noisy_rows(rows, start_t):
    if not rows:
        return False
    if any(r["idle_s"] < r["t"] - start_t for r in rows):
        return True
    load = [r["other_pct"] + r["system_pct"] for r in rows]
    if sum(load) / len(load) > 3.0:
        return True
    for i in range(0, max(1, len(load) - 29)):
        window = load[i:i + 30]
        if len(window) == 30 and sum(window) / 30 > 10.0:
            return True
    return False
