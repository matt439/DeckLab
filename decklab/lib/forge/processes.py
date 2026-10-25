"""Starting and killing Forge's processes so that none can outlive Deck Lab: on Windows
in Job Objects (one for this process, and one of its own for each Forge process),
elsewhere in process groups. The package docstring's "Running Forge" says why. On
Windows they also run below normal priority (BELOW_NORMAL_PRIORITY_CLASS, which the
processes they start get too), so the PC, and Deck Lab's practice hands at normal
priority, stay quick while Forge plays (slots.py)."""
import errno
import os
import signal
import subprocess
import sys
import threading
import weakref

from . import common


# ============================================================ process safety (Windows)

_job = None
_job_lock = threading.Lock()
_job_warned = False

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.restype = wintypes.BOOL
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.AssignProcessToJobObject.restype = wintypes.BOOL
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.IsProcessInJob.restype = wintypes.BOOL
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.TerminateJobObject.restype = wintypes.BOOL
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _ntdll.NtResumeProcess.restype = ctypes.c_long
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    PROCESS_TERMINATE, PROCESS_SET_QUOTA = 0x0001, 0x0100
    PROCESS_SUSPEND_RESUME, PROCESS_QUERY_LIMITED_INFORMATION = 0x0800, 0x1000
    SYNCHRONIZE, WAIT_TIMEOUT = 0x00100000, 0x102
    # No console window, and below normal priority: Windows runs every normal-priority thread
    # (the PC's other programs, practice hands' workers) ahead of Forge's game threads.
    _SPAWN_FLAGS = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    _SUSPENDED = 0x00000004     # CREATE_SUSPENDED


def _new_job():
    """A new Job Object that kills everything in it when its last handle closes."""
    handle = _k32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
    info = _EXTENDED_LIMIT()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _k32.SetInformationJobObject(handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                        ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.get_last_error()
        _k32.CloseHandle(handle)
        raise OSError(error, "SetInformationJobObject failed")
    return handle


def _job_handle():
    """This process's Job Object (made once, never closed: Windows closes it, and kills
    everything in it, when this process ends), or None where there's none."""
    global _job
    if sys.platform != "win32":
        return None
    with _job_lock:
        if _job is None:
            _job = _new_job()
        return _job


def _own_job(proc, handle):
    """Put proc (still suspended, already in this process's job) in a job of its own,
    nested in that one, so kill_process() ends it with every process it started: a
    java.exe that's only a launcher (the one on the PATH) runs the real one as its child."""
    try:
        inner = _new_job()
    except OSError:
        return
    if not _k32.AssignProcessToJobObject(inner, handle):
        _k32.CloseHandle(inner)
        return
    holder = [inner]
    proc._forge_job = holder
    weakref.finalize(proc, _close_job, holder)


def _close_job(holder):
    if holder:
        _k32.CloseHandle(holder.pop())


def kill_process(proc):
    """Kill a process start_process() started, with every process it started in turn
    (on Windows its own job; elsewhere its process group)."""
    holder = getattr(proc, "_forge_job", None)
    if holder is not None:
        for job in list(holder):        # empty once _end_process() closed it
            _k32.TerminateJobObject(job, 1)
    elif sys.platform != "win32":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        if proc.poll() is None:
            proc.kill()
    except OSError:
        pass


def _end_process(proc):
    """Done with a process that has ended: close its own job (which kills anything
    it left running)."""
    holder = getattr(proc, "_forge_job", None)
    if holder:
        _close_job(holder)


def in_job(pid):
    """Is process pid in this process's Job Object? (False off Windows.)"""
    if sys.platform != "win32" or _job is None:
        return False
    handle = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        result = wintypes.BOOL()
        return bool(_k32.IsProcessInJob(handle, _job, ctypes.byref(result))) and bool(result.value)
    finally:
        _k32.CloseHandle(handle)


def start_process(argv, cwd=None, env=None, stdin=False):
    """Popen argv with its output (stdout and stderr together, as text) on a pipe, and with
    stdin (a warm worker's: pool.py) its input on one too (UTF-8 text, a line at a time),
    else none. On Windows it starts suspended, goes into the Job Object, and only then runs,
    so it can't outlive this process even for an instant; it also gets a job of its own
    (nested in that one), so kill_process() kills everything it starts. It runs with
    no window, below normal priority (_SPAWN_FLAGS)."""
    global _job_warned
    kwargs = dict(cwd=cwd, env=env, stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    if sys.platform != "win32":
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    try:
        job = _job_handle()
    except OSError as e:
        job = None
        if not _job_warned:
            _job_warned = True
            common._log(f"Forge's processes can't be tied to Deck Lab's ({e}); a hard kill may leave some running.")
    proc = subprocess.Popen(argv, creationflags=_SPAWN_FLAGS | (_SUSPENDED if job else 0), **kwargs)
    if not job:
        return proc
    handle = _k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_SUSPEND_RESUME, False, proc.pid)
    try:
        if not handle or not _k32.AssignProcessToJobObject(job, handle):
            if not _job_warned:
                _job_warned = True
                common._log(f"A Forge process couldn't join Deck Lab's job (error {ctypes.get_last_error()}); "
                     "a hard kill may leave it running.")
        if handle:
            _own_job(proc, handle)
        if not handle or _ntdll.NtResumeProcess(handle) != 0:
            kill_process(proc)
            proc.wait()
            proc.stdout.close()
            if proc.stdin is not None:
                proc.stdin.close()
            _end_process(proc)
            raise OSError(errno.EPERM, "Windows wouldn't let it run")
    finally:
        if handle:
            _k32.CloseHandle(handle)
    return proc


def alive(pid):
    """Is process pid running? (A pid of 0 or less, or one that can't be looked at, isn't.)"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        handle = _k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return _k32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            _k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True             # someone else's: running all the same
    except OSError:
        return False
    return True
