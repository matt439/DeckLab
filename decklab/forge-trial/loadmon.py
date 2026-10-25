"""Sample machine load while Forge runs: system CPU % and how many java.exe processes exist.

    python loadmon.py OUT.csv [--interval 2] [--duration SECONDS]

Writes one CSV row per interval: unix time, local time, system CPU busy % over the interval
(Win32 GetSystemTimes; 100 % = all 32 logical CPUs busy), and the number of running java.exe
processes (tasklist). Used by the formats trial (formats.md) so each timing can be read against
what else (other agents' Forge runs) was using the PC at the time. Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import subprocess
import time
from ctypes import wintypes


def _sys_times() -> tuple[int, int]:
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
    f = lambda t: (t.dwHighDateTime << 32) | t.dwLowDateTime
    return f(idle), f(kernel) + f(user)  # kernel time includes idle time


def java_count() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    return sum(1 for l in out.splitlines() if l.startswith('"java.exe"'))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--duration", type=float, default=6 * 3600)
    a = ap.parse_args()
    t_end = time.time() + a.duration
    idle0, tot0 = _sys_times()
    with open(a.out, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if fh.tell() == 0:
            w.writerow(["unix", "local", "cpu_busy_pct", "java_procs"])
        while time.time() < t_end:
            time.sleep(a.interval)
            idle1, tot1 = _sys_times()
            busy = 100.0 * (1 - (idle1 - idle0) / max(1, tot1 - tot0))
            idle0, tot0 = idle1, tot1
            w.writerow([f"{time.time():.1f}", time.strftime("%H:%M:%S"), f"{busy:.1f}", java_count()])
            fh.flush()


if __name__ == "__main__":
    main()
