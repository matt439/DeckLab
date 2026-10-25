"""Overnight harness process ownership, Windows jobs and service lifecycle helpers."""
import overnight_common as common


# ============================================================ Windows: jobs, keep-awake, processes

if common.sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("a", "b", "c", "d", "e", "f")]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    PROCESS_TERMINATE, PROCESS_SET_QUOTA, PROCESS_SUSPEND_RESUME = 0x0001, 0x0100, 0x0800
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SUSPENDED, _NO_WINDOW, _BELOW_NORMAL = 0x4, 0x08000000, 0x4000
    _NEW_GROUP = 0x200


class Job:
    """A Windows Job Object that kills everything in it when its last handle closes (no-op elsewhere)."""

    def __init__(self):
        self.handle = None
        if common.sys.platform != "win32":
            return
        handle = _k32.CreateJobObjectW(None, None)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000          # KILL_ON_JOB_CLOSE
        _k32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
        self.handle = handle

    def assign(self, pid):
        if not self.handle:
            return False
        h = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME, False, pid)
        if not h:
            return False
        try:
            return bool(_k32.AssignProcessToJobObject(self.handle, h))
        finally:
            _k32.CloseHandle(h)

    def assign_self(self):
        if self.handle:
            return bool(_k32.AssignProcessToJobObject(self.handle, _k32.GetCurrentProcess()))
        return False

    def pids(self):
        """The processes in the job now (QueryInformationJobObject's JobObjectBasicProcessIdList)."""
        if not self.handle:
            return []
        size = 4096

        class _LIST(ctypes.Structure):
            _fields_ = [("Assigned", wintypes.DWORD), ("InList", wintypes.DWORD), ("Ids", ctypes.c_size_t * size)]
        found = _LIST()
        if not _k32.QueryInformationJobObject(self.handle, 3, ctypes.byref(found), ctypes.sizeof(found), None):
            return []
        return [int(found.Ids[i]) for i in range(found.InList)]

    def contains(self, pid):
        if not self.handle:
            return False
        h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            result = wintypes.BOOL()
            return bool(_k32.IsProcessInJob(h, self.handle, ctypes.byref(result))) and bool(result.value)
        finally:
            _k32.CloseHandle(h)

    def terminate(self):
        if self.handle:
            _k32.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


def creation_time(pid):
    """A process's creation time (100-ns ticks), or None when it can't be read (gone)."""
    if common.sys.platform != "win32":
        return None
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        _k32.CloseHandle(h)


def running(pid, created):
    """Is process pid still running, and the same process (its creation time)? An exited process kept
    by someone's handle (a zombie) isn't."""
    if common.sys.platform != "win32":
        return False
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _k32.GetProcessTimes(h, *(ctypes.byref(t) for t in times)):
            return False
        if ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) != created:
            return False
        code = wintypes.DWORD()
        return bool(_k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
    finally:
        _k32.CloseHandle(h)


def _names():
    try:
        common.sys.path.insert(0, str(common.HERE))
        import overnight_monitor
        return {pid: exe for pid, _, exe in overnight_monitor.snapshot()}
    except Exception:
        return {}


def job_leftovers(job, wait_s=5.0):
    """The processes still in an item's job after its child ended (conhost.exe left out: it ends with
    its process), after up to wait_s for them to go."""
    until = common.time.monotonic() + wait_s
    while True:
        names = _names()
        found = [pid for pid in job.pids() if names.get(pid) not in (None, "conhost.exe")]
        if not found or common.time.monotonic() >= until:
            return [{"pid": pid, "exe": names.get(pid)} for pid in found]
        common.time.sleep(0.5)


def keep_awake():
    """SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED): no sleep while the controller runs."""
    if common.sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def start_child(argv, cwd, env, out_file, job=None):
    """Start argv with its output in out_file, below normal priority, in job (started suspended,
    assigned, then resumed, so it can't escape the job even for an instant)."""
    flags = 0
    if common.sys.platform == "win32":
        flags = _NO_WINDOW | _BELOW_NORMAL | (_SUSPENDED if job is not None and job.handle else 0)
    out = open(out_file, "ab")
    try:
        proc = common.subprocess.Popen(argv, cwd=cwd, env=env, stdin=common.subprocess.DEVNULL, stdout=out,
                                stderr=common.subprocess.STDOUT, creationflags=flags)
    finally:
        out.close()
    if common.sys.platform == "win32" and job is not None and job.handle:
        job.assign(proc.pid)
        h = _k32.OpenProcess(PROCESS_SUSPEND_RESUME, False, proc.pid)
        if h:
            _ntdll.NtResumeProcess(h)
            _k32.CloseHandle(h)
    return proc


def kill_pid(pid):
    """taskkill /PID pid /T /F (a recorded run-owned process only)."""
    common.subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def processes_named(name):
    """[(pid, ppid)] of the processes whose image is name (Toolhelp snapshot)."""
    try:
        common.sys.path.insert(0, str(common.HERE))
        import overnight_monitor
        return [(pid, ppid) for pid, ppid, exe in overnight_monitor.snapshot() if exe == name.lower()]
    except Exception:
        return []


def command_line(pid):
    """A process's command line (PowerShell's CIM), or None."""
    try:
        done = common.subprocess.run(["powershell", "-NoProfile", "-Command",
                               f"(Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\").CommandLine"],
                              capture_output=True, text=True, timeout=30)
        return done.stdout.strip() or None
    except (OSError, common.subprocess.SubprocessError):
        return None


class Lock:
    """$OUT/.lock, held with an OS lock while a controller runs (a second one refuses)."""

    def __init__(self, out):
        self.path = common.Path(out) / ".lock"
        self.f = None

    def acquire(self):
        import msvcrt
        self.f = open(self.path, "a+")
        try:
            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.f.close()
            self.f = None
            return False
        return True

    def release(self):
        if self.f:
            import msvcrt
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self.f.close()
            self.f = None


def _listener_pid(port):
    """The pid listening on a local TCP port (netstat -ano), or None."""
    try:
        done = common.subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=60)
    except (OSError, common.subprocess.SubprocessError):
        return None
    for line in (done.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].rsplit(":", 1)[-1] == str(port):
            try:
                return int(parts[4])
            except ValueError:
                continue
    return None


def foreign_services(services, server_pid, main):
    """The live pool services (forge-pool-*.json; `pool --json`'s answer) other than the 8642
    server's: by its listening pid, else (pid unknown) by main's checkout."""
    def same_dir(a, b):
        return bool(a and b) and common.os.path.normcase(common.os.path.abspath(a)) == common.os.path.normcase(common.os.path.abspath(b))
    found = []
    for service in services or []:
        if not isinstance(service, dict):
            continue
        if server_pid is not None and service.get("pid") == server_pid:
            continue
        if server_pid is None and same_dir(service.get("checkout"), main):
            continue
        found.append(service)
    return found


def split_answering(services):
    """(answering, stale): the services whose `pool --json` status came back, and the rest. A file
    whose pid is alive but doesn't answer is most likely a stale file after a kill by PID, with its
    pid reused by another process: reported, never a reason to stop the run."""
    answering = [s for s in services if s.get("status") is not None]
    return answering, [s for s in services if s.get("status") is None]


def _http_ok(port):
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as answer:
            answer.read(1)
        return True
    except Exception:
        return False


def _own_slots(job):
    found = common._json_cmd([common.PY, "-m", "decklab.lib.forge", "slots", "--json"])
    if found is None:
        return None
    return [h for h in held_slots(found) if job is not None and h.get("pid") and job.contains(h["pid"])]


def held_slots(found):
    """The held slots of `slots --json`'s answer ({"slots": [{"held", "pid", ...}]})."""
    rows = found.get("slots") if isinstance(found, dict) else found if isinstance(found, list) else []
    return [r for r in rows or [] if isinstance(r, dict) and r.get("held")]


def _start_foreign_java(out):
    """The drill's dummy foreign java.exe: a copy of ping.exe named java.exe, started by the
    supervisor (outside the run's job). The run must report it and never kill it."""
    folder = common.Path(out) / "drill"
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "java.exe"
    try:
        common.shutil.copy2(common.Path(common.os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", exe)
        proc = common.subprocess.Popen([str(exe), "-n", "3600", "127.0.0.1"], stdout=common.subprocess.DEVNULL,
                                stderr=common.subprocess.DEVNULL, creationflags=_NO_WINDOW if common.sys.platform == "win32" else 0)
    except OSError:
        return None
    state = common.load_state(out)
    state.setdefault("drill", {})["foreign_pid"] = proc.pid
    common.save_state(out, state)
    return proc


def _end_foreign_java(out, proc):
    state = common.load_state(out)
    alive = proc.poll() is None
    state.setdefault("drill", {})["foreign_alive_at_end"] = alive
    reported = [f.get("pid") for f in state.get("foreign_java") or []]
    state["drill"]["foreign_reported"] = proc.pid in reported
    common.save_state(out, state)
    if alive:
        proc.kill()


def clean(out):
    """End the run's own leftovers (recorded pids whose creation time still matches), never another
    process's."""
    state = common.load_state(out)
    if state is None:
        return []
    ended = []
    for pid, created in state.get("own_pids", []):
        if running(pid, created) and pid != common.os.getpid():
            kill_pid(pid)
            ended.append(pid)
    return ended
