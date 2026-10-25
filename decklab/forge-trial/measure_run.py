"""Milestone 0 measurement harness: run one Forge sim process and time/measure it.

    python measure_run.py --tag NAME [--java PATH] [--xmx 4096m|none] [--jvm=-XX:...] -- <forge sim args after "sim">

Writes logs/<tag>.out (stdout, each line prefixed with seconds since launch), logs/<tag>.err
and logs/<tag>.json with:
  t_header     seconds from launch to the "Ai(1)-... vs Ai(2)-..." line (cards loaded, decks
               loaded, first game about to start)
  t_exit       seconds from launch to process exit
  games        per game: Forge's own "ended in N ms", and wall time between result lines
  mem          peak working set / peak private bytes of the java process (Win32
               GetProcessMemoryInfo, sampled every 0.2 s and once more at exit via the kept handle)
  cpu_s        user+kernel CPU seconds of the process (GetProcessTimes)
Standard library only (ctypes for the Win32 calls).
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

FORGE_DIR = Path("C:/Tools/forge")
JAR = "forge-gui-desktop-2.0.15-jar-with-dependencies.jar"
DEFAULT_JAVA = "C:/Program Files/Java/jdk-26.0.1/bin/java.exe"
HERE = Path(__file__).resolve().parent


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
k32.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def mem_info(h):
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    if not psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
        return None
    return pmc


def cpu_seconds(h):
    c, e, k, u = (wt.FILETIME() for _ in range(4))
    if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
        return None
    f = lambda ft: ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7
    return f(k) + f(u)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--java", default=DEFAULT_JAVA)
    ap.add_argument("--xmx", default="4096m", help="heap limit, or 'none' to leave -Xmx out")
    ap.add_argument("--jvm", action="append", default=[], help="extra JVM flag (repeatable), e.g. --jvm=-XX:+UseSerialGC")
    ap.add_argument("sim_args", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    sim_args = a.sim_args[1:] if a.sim_args[:1] == ["--"] else a.sim_args
    jvm = ([f"-Xmx{a.xmx}"] if a.xmx != "none" else []) + [
        "-Dio.netty.tryReflectionSetAccessible=true", "-Dfile.encoding=UTF-8"] + a.jvm
    cmd = [a.java, *jvm, "-jar", JAR, "sim", *sim_args]
    logs = HERE / "logs"
    logs.mkdir(exist_ok=True)
    out_path, err_path = logs / f"{a.tag}.out", logs / f"{a.tag}.err"

    t0 = time.perf_counter()
    p = subprocess.Popen(cmd, cwd=FORGE_DIR, stdout=subprocess.PIPE, stderr=open(err_path, "wb"),
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, p.pid)
    samples = []
    stop = threading.Event()

    def sampler():
        while not stop.is_set():
            m = mem_info(h)
            if m:
                samples.append((round(time.perf_counter() - t0, 2), m.WorkingSetSize, m.PagefileUsage))
            stop.wait(0.2)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()
    t_header = None
    results = []
    header_re = re.compile(r"^Ai\(1\)-.* vs Ai\(2\)-.* - .* of \w+")
    result_re = re.compile(r"^Game Result: Game (\d+) (?:ended in (\d+) ms\. (.*) has won!|ended in a Draw! Took (\d+) ms\.)")
    with open(out_path, "w", encoding="utf-8") as out:
        for line in p.stdout:
            t = time.perf_counter() - t0
            line = line.rstrip("\n")
            out.write(f"{t:9.3f} {line}\n")
            if t_header is None and header_re.match(line):
                t_header = t
            m = result_re.match(line)
            if m:
                results.append({"game": int(m[1]), "t": round(t, 3),
                                "forge_ms": int(m[2] or m[4]), "winner": m[3] or "draw"})
    p.wait()
    t_exit = time.perf_counter() - t0
    stop.set()
    th.join()
    final = mem_info(h)
    cpu = cpu_seconds(h)
    peak_ws = final.PeakWorkingSetSize if final else max(s[1] for s in samples)
    peak_priv = final.PeakPagefileUsage if final else max(s[2] for s in samples)
    prev = t_header
    for r in results:
        r["wall_s"] = round(r["t"] - prev, 3) if prev is not None else None
        prev = r["t"]
    fms = [r["forge_ms"] for r in results]
    summary = {
        "cmd": cmd, "cwd": str(FORGE_DIR), "exit_code": p.returncode,
        "t_header": round(t_header, 3) if t_header else None, "t_exit": round(t_exit, 3),
        "n_games": len(results),
        "forge_ms": {"mean": round(sum(fms) / len(fms), 1), "min": min(fms), "max": max(fms)} if fms else None,
        "games_wall_s": round(results[-1]["t"] - t_header, 3) if results and t_header else None,
        "mem": {"peak_working_set_mb": round(peak_ws / 2**20, 1),
                "peak_private_mb": round(peak_priv / 2**20, 1),
                "sampled_max_ws_mb": round(max((s[1] for s in samples), default=0) / 2**20, 1),
                "n_samples": len(samples)},
        "cpu_s": round(cpu, 2) if cpu is not None else None,
        "wins": {w: sum(1 for r in results if r["winner"] == w) for w in sorted({r["winner"] for r in results})},
        "games": results,
        "ws_timeline_mb": [(s[0], round(s[1] / 2**20)) for s in samples[:: max(1, len(samples) // 40)]],
    }
    (logs / f"{a.tag}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    brief = {k: v for k, v in summary.items() if k not in ("games", "ws_timeline_mb", "cmd")}
    print(json.dumps(brief, indent=1))


if __name__ == "__main__":
    main()
