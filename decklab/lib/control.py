"""Finding and stopping a running Deck Lab server, and its log file when it
has no window.

In the background, Task Scheduler starts Deck Lab's server (decklab/server.py)
with pythonw.exe (lib/homenet/ sets that up), so it has no console window to
press Ctrl+C in or to close, and nowhere to print. This module is how other
programs find it and stop it gracefully, and where its output goes.

Usage (other programs):

    from decklab.lib import control
    control.read_state()        # the running server: {"version": 1, "pid", "host", "port",
                                #  "started", "python", "log", "background"}, or None
    control.request_stop(8642)  # "stopped" | "not running" | "timeout" | "unsupported"
    control.process_alive(pid)
    control.mark_stopped(8642, "homenet stop")      # stopped on purpose: the watchdog leaves it off
    control.read_stopped(8642)  # that marker, while it counts, or None
    control.clear_stopped(8642)

The server's side (server.py main()):

    sys.stdout = sys.stderr = control.open_log()    # with no console (pythonw), or --log
    # Once it is listening (never before: see listen_for_stop), and before the state file:
    stop = control.listen_for_stop(port, on_stop)   # on_stop(): stop as Ctrl+C would
    session = control.watch_session_end(on_end, on_close=on_stop)
                                                    # on_end(): Windows is logging off;
                                                    # on_close(): taskkill /PID without /F
    control.write_state({...})                      # now whoever finds it can stop the server
    ...
    control.clear_state(os.getpid()); stop.close(); session.close()

- The state file (STATE_FILE, decklab/data/server.json) says which server is
  running. The server writes it atomically (a temp file, then os.replace), so
  a reader sees the old file or the new one, never half of one, and removes
  it on a clean exit only if it still names the server's own process. A
  server that ended without cleaning up (a hard kill, a power cut) leaves it
  behind; read_state() then returns None, because its process is gone, or
  its process id now belongs to a process that started after the server did
  (Windows reuses process ids quickly). read_state() never deletes the file.
  The environment variable DECKLAB_STATE_FILE moves it, for tests only: the
  end-to-end tests run real servers, which must never touch the real file.
- Stopping: every server creates a named Windows event,
  Local\\DeckLab-stop-<port> (stop_event_name; "Local\\" keeps it to this
  logon session, and one name per port means a test server on another port
  never touches the real one). request_stop() sets it; the server then stops
  the way Ctrl+C stops it (a Forge matchup saves the games it finished), and
  request_stop() waits until its process has ended (or, with no state file
  to name the process, until the server has closed the event), up to
  STOP_WAIT seconds. On Linux there's no named event: request_stop() sends
  SIGTERM to the process the state file names (systemctl stop sends the
  same), and the server's SIGTERM handler stops it the same way.
- The stop marker (stop_marker_path: stopped-<port>.json beside the state
  file, so DECKLAB_STATE_FILE moves it too, and one per port) says the
  server on that port was stopped on purpose, so homenet's watchdog task
  (lib/homenet/watchdog.py, E11-S26) leaves it off. homenet stop and
  server.py --stop write it (mark_stopped) before they signal, and a server
  stopped on request (a stop request, taskkill without /F, Ctrl+C) writes it
  as it exits unless one is there already (keep). homenet start, restart and
  install clear it (clear_stopped), and so does a server once it's listening,
  so the logon trigger's start ends it too. It holds the session's logon time
  (logon_time), and read_stopped() ignores a marker from another logon. A
  hard kill, an exception, or Windows logging off writes none.
- Logging off or shutting down: Windows tells every top-level window, even a
  hidden one (but never a message-only window), with WM_QUERYENDSESSION and
  then WM_ENDSESSION. watch_session_end() makes such a hidden window, of the
  class WINDOW_CLASS, and calls on_end() when the session really ends.
  Windows ends the process soon after (about 5 seconds), so on_end() must be
  quick: the server's waits at most CLOSE_WAIT (4) seconds.
- Being asked to close: that window also makes the process a target for
  taskkill /PID (or /IM) without /F, which sends WM_CLOSE to its windows.
  The window stays (it would otherwise be destroyed, and the server would
  run on without hearing of the session's end) and calls on_close(): the
  server stops as for request_stop(). The window's own close() uses a
  message of its own (WM_DESTROY_WATCHER), never WM_CLOSE.
- The log: open_log() is a text stream for sys.stderr and sys.stdout that
  appends to LOG_FILE (decklab/data/logs/server.log), and when it reaches
  LOG_MAX_BYTES renames it to server.log.1 (older ones to .2 and .3, keeping
  LOG_BACKUPS) and starts a new one. If another program has the log open,
  so it can't be renamed, nothing is renamed and it tries again later.
  Every write goes straight to the file, and a write that fails (a full
  disk, a locked file) is dropped rather than raised, so logging can never
  break a request.

Off Windows, listen_for_stop() and watch_session_end() do nothing and
request_stop() answers "unsupported" (stop the server with Ctrl+C there).
"""
import io
import itertools
import json
import os
import signal
import sys
import threading
import time
import traceback
import types
from datetime import datetime, timezone
from pathlib import Path

from decklab.lib import config

STATE_VERSION = 1
MARKER_VERSION = 1                  # the stop marker's format
LOGON_SLACK = 2                     # seconds two logon times may differ by and still be one logon
# DECKLAB_STATE_FILE is for tests only (see the module docstring).
STATE_FILE = (Path(os.environ["DECKLAB_STATE_FILE"]) if os.environ.get("DECKLAB_STATE_FILE")
              else config.DATA / "server.json")
LOG_FILE = config.DATA / "logs" / "server.log"
LOG_MAX_BYTES = 2_000_000           # rotate the log at this size...
LOG_BACKUPS = 3                     # ... keeping server.log.1 .. server.log.3
LOG_RETRY = 100_000                 # bytes to write before trying a rotation that failed again
STOP_WAIT = 30                      # seconds request_stop() waits; the server waits up to 15 s for a matchup
STARTED_SLACK = 5                   # seconds: "started" is cut to the second, and a clock may be adjusted
WINDOW_CLASS = "DeckLabServer"      # the hidden session-end window's class (tests find it by this)
CLOSE_JOIN = 5                      # seconds close() waits for a listener's thread
REPLACE_TRIES = 20                  # os.replace/unlink attempts while another program reads the file

# Windows constants.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
STILL_ACTIVE = 259
ERROR_FILE_NOT_FOUND = 2
ERROR_ACCESS_DENIED = 5
ERROR_ALREADY_EXISTS = 183
ERROR_CLASS_ALREADY_EXISTS = 1410
WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_APP = 0x8000
WM_DESTROY_WATCHER = WM_APP + 1     # the session-end window's own close(): never another program's WM_CLOSE
_EPOCH_AS_FILETIME = 11644473600    # seconds from 1601-01-01 (FILETIME's start) to 1970-01-01


def _log(text):
    """One line to stderr (pythonw has none, unless the server gave it a log file)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


# ------------------------------------------------------------ Windows API

_WIN = None
_WIN_LOCK = threading.Lock()


def _win():
    """kernel32 and user32, with every function this module calls declared
    (handles are 64-bit, so the defaults would cut them to 32). Private
    WinDLL objects, so other modules' declarations can't clash with these."""
    global _WIN
    with _WIN_LOCK:
        if _WIN is None:
            _WIN = _load_win()
        return _WIN


def _load_win():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    LRESULT, WPARAM, LPARAM = ctypes.c_ssize_t, ctypes.c_size_t, ctypes.c_ssize_t
    H, DW, B, HWND, UINT = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.HWND, wintypes.UINT
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", H), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR)]

    MSG_P = ctypes.POINTER(wintypes.MSG)
    for dll, name, restype, argtypes in (
            (k32, "OpenProcess", H, [DW, B, DW]),
            (k32, "GetExitCodeProcess", B, [H, ctypes.POINTER(DW)]),
            (k32, "GetProcessTimes", B, [H] + [ctypes.POINTER(wintypes.FILETIME)] * 4),
            (k32, "CloseHandle", B, [H]),
            (k32, "CreateEventW", H, [wintypes.LPVOID, B, B, wintypes.LPCWSTR]),
            (k32, "OpenEventW", H, [DW, B, wintypes.LPCWSTR]),
            (k32, "SetEvent", B, [H]),
            (k32, "ResetEvent", B, [H]),
            (k32, "WaitForSingleObject", DW, [H, DW]),
            (k32, "WaitForMultipleObjects", DW, [DW, ctypes.POINTER(H), B, DW]),
            (k32, "GetModuleHandleW", wintypes.HMODULE, [wintypes.LPCWSTR]),
            (u32, "RegisterClassW", wintypes.ATOM, [ctypes.POINTER(WNDCLASSW)]),
            (u32, "CreateWindowExW", HWND, [DW, wintypes.LPCWSTR, wintypes.LPCWSTR, DW, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, wintypes.HMENU,
                                            wintypes.HINSTANCE, wintypes.LPVOID]),
            (u32, "DefWindowProcW", LRESULT, [HWND, UINT, WPARAM, LPARAM]),
            (u32, "GetMessageW", B, [MSG_P, HWND, UINT, UINT]),
            (u32, "TranslateMessage", B, [MSG_P]),
            (u32, "DispatchMessageW", LRESULT, [MSG_P]),
            (u32, "PostMessageW", B, [HWND, UINT, WPARAM, LPARAM]),
            (u32, "DestroyWindow", B, [HWND]),
            (u32, "PostQuitMessage", None, [ctypes.c_int])):
        function = getattr(dll, name)
        function.restype, function.argtypes = restype, argtypes
    return types.SimpleNamespace(ctypes=ctypes, wintypes=wintypes, k32=k32, u32=u32,
                                 WNDPROC=WNDPROC, WNDCLASSW=WNDCLASSW)


def _last_error():
    return _win().ctypes.get_last_error()


# ------------------------------------------------------------- the state file

def _state_path(path):
    return Path(path) if path is not None else STATE_FILE


def _retry(action):
    """action(), tried again for about a second while it fails with
    PermissionError: on Windows a file another program has open (homenet
    reading the state file, say) can't be replaced or deleted."""
    for attempt in range(REPLACE_TRIES):
        try:
            return action()
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(0.05)


def write_state(state, path=None):
    """Write state (a dict) to the state file, atomically: a temp file in the
    same folder, then os.replace. Creates the folder. Raises OSError."""
    path = _state_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        _retry(lambda: os.replace(temp, path))
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _load(path):
    """The file's JSON object, or None: missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):           # UnicodeDecodeError is a ValueError
        return None
    return data if isinstance(data, dict) else None


def _valid_pid(pid):
    return isinstance(pid, int) and not isinstance(pid, bool) and 0 < pid < 2 ** 32


def _timestamp(text):
    """An ISO time ("2026-10-01T09:12:33+10:00"; one with no offset is local)
    as seconds since 1970, or None."""
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def read_state(path=None):
    """The running server's state (see the module docstring), or None when
    the file is missing or unreadable, or names a process that has ended (or
    a process id Windows has since given to a newer process, or to a system
    process this user can't look into). Never deletes."""
    state = _load(_state_path(path))
    if state is None:
        return None
    pid = state.get("pid")
    if not process_alive(pid):
        return None
    started, created = _timestamp(state.get("started")), process_started(pid)
    if sys.platform == "win32" and created is None:
        return None                         # not a process this user started, so not a server of theirs
    if started is not None and created is not None and created > started + STARTED_SLACK:
        return None                         # the server's process id, reused by a newer process
    return state


def clear_state(pid=None, path=None):
    """Remove the state file; with pid, only if it names that process (so a
    server that ends never removes a newer server's file). True if removed.
    Never raises."""
    path = _state_path(path)
    if pid is not None:
        state = _load(path)
        if state is None or state.get("pid") != pid:
            return False
    try:
        _retry(path.unlink)
        return True
    except OSError:                          # already gone, or held open for too long
        return False


# ------------------------------------------------------------- the stop marker

def stop_marker_path(port, path=None):
    """The stop marker for the server on port: stopped-<port>.json beside the
    state file (path, default STATE_FILE)."""
    return _state_path(path).with_name(f"stopped-{int(port)}.json")


def mark_stopped(port, by, path=None, keep=False, restart=False):
    """Record that the server on port was stopped on purpose, by by ("homenet
    stop", "server.py --stop", "stop request", "taskkill", "Ctrl+C", "window
    closed", "install --no-start"), in this logon. With keep, a marker already
    there stays as it is (the stop that asked first is the one named). With
    restart, it was the stop of a restart that didn't finish ("restart":
    true): the server was meant to run again, so the watchdog starts it once
    it's down (and a server stopping later keeps this marker, with keep).
    True when written. Raises OSError."""
    marker = stop_marker_path(port, path)
    if keep and marker.exists():
        return False
    data = {"version": MARKER_VERSION, "port": int(port),
            "at": datetime.now().astimezone().isoformat(timespec="seconds"), "by": by, "logon": logon_time()}
    if restart:
        data["restart"] = True
    write_state(data, path=marker)
    return True


def clear_stopped(port, path=None):
    """Remove the stop marker for port. True if removed. Never raises."""
    try:
        _retry(stop_marker_path(port, path).unlink)
        return True
    except OSError:
        return False


def read_stopped(port, path=None, logon=None):
    """The stop marker for port while it counts: its dict, or {"by":
    "unreadable"} for a file that's there but can't be read (which counts
    too: staying off is the safe side). None when there's none, or it was
    written in another logon (logon: the current one, default logon_time()).
    When either logon time isn't known, the marker counts."""
    marker = stop_marker_path(port, path)
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"by": "unreadable"}
    if not isinstance(data, dict):
        return {"by": "unreadable"}
    then, now = _timestamp(data.get("logon")), _timestamp(logon if logon is not None else logon_time())
    if then is not None and now is not None and abs(then - now) > LOGON_SLACK:
        return None                         # from an earlier logon: its logon trigger has started it since
    return data


def logon_time():
    """When this Windows session's user logged on, as UTC ISO text
    ("2026-10-17T01:15:13+00:00"), or None (not Windows, or it can't be read).
    It's the session's (WTSQuerySessionInformation's LogonTime), so an
    elevated PowerShell and a normal one agree, as a token's logon id
    wouldn't. Never raises."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class WTSINFOW(ctypes.Structure):
            _fields_ = ([("State", ctypes.c_int), ("SessionId", wintypes.DWORD)]
                        + [(f"counter{i}", wintypes.DWORD) for i in range(6)]
                        + [("WinStationName", wintypes.WCHAR * 32), ("Domain", wintypes.WCHAR * 17),
                           ("UserName", wintypes.WCHAR * 21)]
                        + [(name, ctypes.c_longlong) for name in ("ConnectTime", "DisconnectTime",
                                                                  "LastInputTime", "LogonTime", "CurrentTime")])

        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        query, free = wts.WTSQuerySessionInformationW, wts.WTSFreeMemory
        query.restype = wintypes.BOOL
        query.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                          ctypes.POINTER(wintypes.DWORD)]
        free.restype, free.argtypes = None, [ctypes.c_void_p]
        buffer, size = ctypes.c_void_p(), wintypes.DWORD()
        # The current server (NULL), the current session, WTSSessionInfo (24).
        if not query(None, 0xFFFFFFFF, 24, ctypes.byref(buffer), ctypes.byref(size)) or not buffer:
            return None
        try:
            if size.value < ctypes.sizeof(WTSINFOW):
                return None
            ticks = ctypes.cast(buffer, ctypes.POINTER(WTSINFOW)).contents.LogonTime     # 100 ns since 1601, UTC
        finally:
            free(buffer)
        if ticks <= 0:
            return None
        return datetime.fromtimestamp(ticks / 10_000_000 - _EPOCH_AS_FILETIME, timezone.utc).isoformat(
            timespec="seconds")
    except Exception:                       # noqa: BLE001 (no logon time is an answer too)
        return None


# ------------------------------------------------------------- processes

def process_alive(pid):
    """True while process pid is running (one this user can't look into
    counts as running)."""
    if not _valid_pid(pid):
        return False
    if sys.platform == "win32":
        win = _win()
        handle = win.k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return _last_error() == ERROR_ACCESS_DENIED     # it exists, but isn't ours to look at
        try:
            code = win.wintypes.DWORD()
            if not win.k32.GetExitCodeProcess(handle, win.ctypes.byref(code)):
                return True
            # An ended process whose handle someone still holds stays openable.
            return code.value == STILL_ACTIVE
        finally:
            win.k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)                     # (on Windows this would end the process)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def process_started(pid):
    """When process pid started, in seconds since 1970, or None (not Windows,
    no such process, or not ours to look at)."""
    if sys.platform != "win32" or not _valid_pid(pid):
        return None
    win = _win()
    handle = win.k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        times = [win.wintypes.FILETIME() for _ in range(4)]
        if not win.k32.GetProcessTimes(handle, *(win.ctypes.byref(t) for t in times)):
            return None
        created = times[0]
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime      # 100 ns since 1601
        return ticks / 10_000_000 - _EPOCH_AS_FILETIME
    finally:
        win.k32.CloseHandle(handle)


# ------------------------------------------------------------- stopping

def stop_event_name(port):
    """The named event that stops the server on port (one per port, this logon session only)."""
    return f"Local\\DeckLab-stop-{int(port)}"


class _NoListener:
    """listen_for_stop() and watch_session_end() off Windows: nothing to close."""

    hwnd = None
    title = None

    def close(self):
        pass


class _StopListener:
    """listen_for_stop()'s answer on Windows: the named event and the thread
    waiting on it."""

    def __init__(self, port, on_stop):
        win = _win()
        self._k32, self._on_stop, self.name = win.k32, on_stop, stop_event_name(port)
        self._lock, self._closed = threading.Lock(), False
        self._closing = self._k32.CreateEventW(None, True, False, None)     # close() sets it
        if not self._closing:
            raise win.ctypes.WinError(_last_error())
        # Auto-reset, so one SetEvent wakes one wait and doesn't stay set; and
        # should the name still exist (an earlier server on this port, still
        # saving a matchup's games), a stop meant for that one is cleared.
        win.ctypes.set_last_error(0)
        self._event = self._k32.CreateEventW(None, False, False, self.name)
        error = _last_error()
        if not self._event:
            self._k32.CloseHandle(self._closing)
            raise win.ctypes.WinError(error)
        if error == ERROR_ALREADY_EXISTS:
            self._k32.ResetEvent(self._event)
        self._thread = threading.Thread(target=self._wait, name=f"stop-listener-{port}", daemon=True)
        self._thread.start()

    def _wait(self):
        handles = (_win().wintypes.HANDLE * 2)(self._event, self._closing)
        result = self._k32.WaitForMultipleObjects(2, handles, False, INFINITE)
        if result != WAIT_OBJECT_0:
            if result != WAIT_OBJECT_0 + 1:
                _log(f"Waiting for a stop request failed (error {_last_error()}).")
            return
        try:
            self._on_stop()
        except Exception:
            _log(f"Stopping failed:\n{traceback.format_exc()}")

    def close(self):
        """Stop listening. The event's name lasts until its last handle closes,
        so request_stop() can tell the server has gone."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._k32.SetEvent(self._closing)
        if self._thread is not threading.current_thread():
            self._thread.join(CLOSE_JOIN)
        if self._thread.is_alive():
            return                  # on_stop() is still running: the process's end closes the handles
        self._k32.CloseHandle(self._event)
        self._k32.CloseHandle(self._closing)


def listen_for_stop(port, on_stop):
    """Call on_stop() (once, in a thread of its own) when request_stop(port)
    asks this process to stop. The answer's close() stops listening. Raises
    OSError if the event can't be made. On Linux it's SIGTERM instead (what
    request_stop and systemctl stop send), heard only from the main thread;
    elsewhere, or from another thread, it does nothing.

    Call it once the server has the port, never before: a server that then
    found the port taken would already have opened (and reset) the running
    server's event. And call it before writing the state file, so whoever
    finds the server there can stop it."""
    if sys.platform != "win32":
        if sys.platform.startswith("linux") and threading.current_thread() is threading.main_thread():
            return _SignalListener(on_stop)
        return _NoListener()
    return _StopListener(port, on_stop)


class _SignalListener:
    """listen_for_stop()'s answer on Linux: SIGTERM calls on_stop() once, in a
    thread of its own (it may wait for serve_forever(), which the main thread
    runs), until close() puts the earlier handler back."""

    def __init__(self, on_stop):
        self._on_stop, self._lock, self._called = on_stop, threading.Lock(), False
        self._before = signal.signal(signal.SIGTERM, self._heard)

    def _heard(self, signum, frame):
        with self._lock:
            if self._called:
                return
            self._called = True
        threading.Thread(target=self._stop, name="stop-listener", daemon=True).start()

    def _stop(self):
        try:
            self._on_stop()
        except Exception:
            _log(f"Stopping failed:\n{traceback.format_exc()}")

    def close(self):
        if self._before is not None and threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self._before)
            self._before = None


def _event_exists(name):
    win = _win()
    handle = win.k32.OpenEventW(SYNCHRONIZE, False, name)
    if handle:
        win.k32.CloseHandle(handle)
        return True
    return _last_error() != ERROR_FILE_NOT_FOUND


def request_stop(port, wait=STOP_WAIT, path=None):
    """Ask the server on port to stop, and wait up to wait seconds for it.

    "stopped": it has (its process has ended, or with no state file naming
    it, it has closed its stop event); "not running": no server listens for
    a stop on that port; "timeout": asked, but still running; "unsupported":
    not Windows or Linux, or the server can't be signalled from here (it runs as
    administrator or as another user). path is the state file (STATE_FILE).
    On Linux it sends SIGTERM to the process the state file names, once
    /proc shows that process is still a Deck Lab server (_is_server)."""
    if sys.platform.startswith("linux"):
        return _request_stop_posix(port, wait, path)
    if sys.platform != "win32":
        return "unsupported"
    win = _win()
    k32, name = win.k32, stop_event_name(port)
    state = read_state(path)
    process = None
    if state and state.get("port") == port and state.get("pid") != os.getpid():
        # Opened before the stop, so a process id reused afterwards can't fool the wait.
        process = k32.OpenProcess(SYNCHRONIZE, False, state["pid"])
    try:
        event = k32.OpenEventW(EVENT_MODIFY_STATE | SYNCHRONIZE, False, name)
        if not event:
            return "not running" if _last_error() == ERROR_FILE_NOT_FOUND else "unsupported"
        try:
            if not k32.SetEvent(event):
                return "unsupported"
        finally:
            k32.CloseHandle(event)          # so the name goes once the server closes its own
        deadline = time.monotonic() + max(0.0, wait)
        while True:
            left = max(0.0, deadline - time.monotonic())
            if process:
                if k32.WaitForSingleObject(process, int(min(left, 0.25) * 1000)) == WAIT_OBJECT_0:
                    return "stopped"
            else:
                if not _event_exists(name):
                    return "stopped"
                time.sleep(min(left, 0.1))
            if time.monotonic() >= deadline:
                return "timeout"
    finally:
        if process:
            k32.CloseHandle(process)


def _is_server(pid):
    """True when Linux's /proc shows process pid runs decklab/server.py, so a
    process id reused since the state file was written is never signalled."""
    try:
        args = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return False
    return any(Path(os.fsdecode(a)).name == "server.py" for a in args if a)


def _request_stop_posix(port, wait, path):
    state = read_state(path)
    pid = (state or {}).get("pid")
    if not state or state.get("port") != port or pid == os.getpid() or not _is_server(pid):
        return "not running"
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "stopped"
    except PermissionError:
        return "unsupported"
    deadline = time.monotonic() + max(0.0, wait)
    while process_alive(pid) and _is_server(pid):
        if time.monotonic() >= deadline:
            return "timeout"
        time.sleep(0.1)
    return "stopped"


# ------------------------------------------------------- logging off, shutting down

_WATCHERS = {}                      # hwnd -> _SessionWatcher
_WATCHERS_LOCK = threading.Lock()
_WNDPROC = None                     # the window procedure's ctypes callback: kept for the process's life
_TITLES = itertools.count(1)


def _window_proc(hwnd, message, wparam, lparam):
    win = _win()
    with _WATCHERS_LOCK:
        watcher = _WATCHERS.get(hwnd)
    if watcher is not None:
        if message == WM_QUERYENDSESSION:
            return 1                # TRUE: the session may end
        if message == WM_ENDSESSION:
            if wparam:              # it is ending (FALSE: another program cancelled it)
                watcher._end()
            return 0
        if message == WM_CLOSE:
            # Another program asking the process to close (taskkill /PID
            # without /F sends this to its windows). DefWindowProc would
            # destroy the window and leave the server running, deaf to the
            # session's end; instead the window stays and on_close() runs.
            watcher._close_requested()
            return 0
        if message == WM_DESTROY_WATCHER:
            if watcher._closed:     # only close() destroys the window
                win.u32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            win.u32.PostQuitMessage(0)
            return 0
    return win.u32.DefWindowProcW(hwnd, message, wparam, lparam)


def _register_class():
    """Register WINDOW_CLASS once per process."""
    global _WNDPROC
    win = _win()
    with _WATCHERS_LOCK:
        if _WNDPROC is not None:
            return
        callback = win.WNDPROC(_window_proc)
        window_class = win.WNDCLASSW()
        window_class.lpfnWndProc = callback
        window_class.hInstance = win.k32.GetModuleHandleW(None)
        window_class.lpszClassName = WINDOW_CLASS
        if not win.u32.RegisterClassW(win.ctypes.byref(window_class)):
            error = _last_error()
            if error != ERROR_CLASS_ALREADY_EXISTS:
                raise win.ctypes.WinError(error)
        _WNDPROC = callback


class _SessionWatcher:
    """watch_session_end()'s answer on Windows: a hidden top-level window
    (hwnd, titled title) and the thread running its message loop."""

    def __init__(self, on_end, title, on_close=None):
        self.title, self.hwnd = title, None
        self._on_end, self._ended, self._closed = on_end, False, False
        self._on_close, self._close_asked = on_close, False
        self._lock = threading.Lock()
        self._ready, self._error = threading.Event(), None
        self._thread = threading.Thread(target=self._run, name="session-end", daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            raise OSError("The session-end window wasn't made in time")
        if self._error is not None:
            raise self._error

    def _run(self):
        win = _win()
        try:
            _register_class()
            # No WS_VISIBLE and never shown; a top-level window (no parent),
            # not a message-only one, which never hears of the session ending.
            hwnd = win.u32.CreateWindowExW(0, WINDOW_CLASS, self.title, 0, 0, 0, 0, 0, None, None,
                                           win.k32.GetModuleHandleW(None), None)
            if not hwnd:
                raise win.ctypes.WinError(_last_error())
        except OSError as e:
            self._error = e
            self._ready.set()
            return
        with _WATCHERS_LOCK:
            _WATCHERS[hwnd] = self
        self.hwnd = hwnd
        self._ready.set()
        message = win.wintypes.MSG()
        try:
            while win.u32.GetMessageW(win.ctypes.byref(message), None, 0, 0) > 0:
                win.u32.TranslateMessage(win.ctypes.byref(message))
                win.u32.DispatchMessageW(win.ctypes.byref(message))
        finally:
            with _WATCHERS_LOCK:
                _WATCHERS.pop(hwnd, None)

    def _end(self):
        with self._lock:
            if self._ended:
                return
            self._ended = True
        try:
            self._on_end()
        except Exception:
            _log(f"Stopping at the session's end failed:\n{traceback.format_exc()}")

    def _close_requested(self):
        """WM_CLOSE from another program: on_close() once, in a thread of its
        own (so the window keeps answering, the session's end included)."""
        with self._lock:
            if self._closed or self._close_asked or self._on_close is None:
                return
            self._close_asked = True
        threading.Thread(target=self._call_on_close, name="close-request", daemon=True).start()

    def _call_on_close(self):
        try:
            self._on_close()
        except Exception:
            _log(f"Stopping when asked to close failed:\n{traceback.format_exc()}")

    def close(self):
        """Destroy the window and end its thread. (A message of its own, not
        WM_CLOSE, which means another program asking the server to stop.)"""
        with self._lock:
            if self._closed or not self.hwnd:
                return
            self._closed = True
        _win().u32.PostMessageW(self.hwnd, WM_DESTROY_WATCHER, 0, 0)
        if self._thread is not threading.current_thread():
            self._thread.join(CLOSE_JOIN)


def watch_session_end(on_end, title=None, on_close=None):
    """Call on_end() (once, in the window's thread) when Windows logs off or
    shuts down. It must finish within about 4 seconds: Windows ends the
    process soon after it returns. Call on_close() (once, in a thread of its
    own) when another program asks the window to close (WM_CLOSE: taskkill
    /PID or /IM without /F); without on_close that is ignored. Either way the
    window stays, still listening for the session's end. The answer has hwnd,
    title (default: "Deck Lab server (process <pid>)", numbered after the
    first) and close(). Raises OSError if the window can't be made. Does
    nothing off Windows."""
    if sys.platform != "win32":
        return _NoListener()
    if title is None:
        number = next(_TITLES)
        title = f"Deck Lab server (process {os.getpid()})" + (f" #{number}" if number > 1 else "")
    return _SessionWatcher(on_end, title, on_close)


# ------------------------------------------------------------- the log

class LogFile(io.TextIOBase):
    """open_log()'s stream: see the module docstring. Thread-safe: one write
    is one piece of the file, never mixed with another thread's.

    A write can start another one in the same thread while it holds the
    lock: anything Python reports through sys.stderr from inside it (an
    exception in a __del__ that a garbage collection ran, a warning). A
    plain Lock would then hang every thread that logs, so the lock is an
    RLock, and such a write waits in _pending until the outer one is done."""

    def __init__(self, path, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
        super().__init__()
        self.path, self.max_bytes, self.backups = Path(path), max_bytes, backups
        self._lock = threading.RLock()
        self._writing, self._pending = False, []
        self._file, self._size, self._retry_at, self._shut = None, 0, 0, False

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "backslashreplace"

    @property
    def name(self):
        return str(self.path)

    def writable(self):
        return True

    def isatty(self):
        return False

    def flush(self):
        pass                        # every write is already in the file

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        data = text.encode("utf-8", "backslashreplace")     # a lone surrogate is written escaped
        with self._lock:
            if self._writing:       # this thread is inside a write already (see the class docstring)
                self._pending.append(data)
                return len(text)
            self._writing = True
            try:
                while data:
                    if not self._shut:
                        try:
                            self._write(data)
                        except Exception:   # a full disk, a locked folder: the line is lost, not the request
                            self._drop()
                    data = self._pending.pop(0) if self._pending else b""
            finally:
                self._writing = False
                self._pending.clear()
        return len(text)

    def _write(self, data):
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "ab", buffering=0)
            self._size = self._file.seek(0, os.SEEK_END)
        if self._size and self._size + len(data) > self.max_bytes and self._size >= self._retry_at:
            self._rotate()
        view = memoryview(data)
        while view:
            written = self._file.write(view)
            view = view[written:]
        self._size += len(data)

    def _backup(self, number):
        return self.path.with_name(f"{self.path.name}.{number}")

    def _rotate(self):
        """server.log -> .1 -> .2 -> .3 (the oldest goes), then a new file.
        If another program has one of them open (an editor showing the log),
        keep appending and try again after LOG_RETRY more bytes.

        The live log moves out of the way first (to server.log.rotating),
        and the old files shift only once it has: while another program has
        it open, nothing moves, so a failed try never loses an old file. If
        an old file can't move, the live log goes back. A .rotating file
        left by a try that couldn't put it back goes to .1 at the next try
        (the live log then rotates at the write after)."""
        self._drop()
        try:
            if self.backups < 1:
                open(self.path, "wb").close()
            else:
                moving, moved = self.path.with_name(f"{self.path.name}.rotating"), False
                if not moving.exists():
                    os.replace(self.path, moving)
                    moved = True
                try:
                    for number in range(self.backups - 1, 0, -1):
                        if self._backup(number).exists():
                            os.replace(self._backup(number), self._backup(number + 1))
                    os.replace(moving, self._backup(1))
                except OSError:
                    if moved:
                        os.replace(moving, self.path)
                    raise
            self._retry_at = 0
        except OSError:
            self._retry_at = self._size + LOG_RETRY
        self._file = open(self.path, "ab", buffering=0)
        self._size = self._file.seek(0, os.SEEK_END)

    def _drop(self):
        file, self._file = self._file, None
        if file is not None:
            try:
                file.close()
            except OSError:
                pass

    def close(self):
        with self._lock:
            self._shut = True
            self._drop()
        super().close()


def open_log(path=None, max_bytes=LOG_MAX_BYTES, backups=LOG_BACKUPS):
    """A text stream appending to path (LOG_FILE by default), rotated at
    max_bytes keeping backups old files. Nothing is created until the first
    write, which makes the folder too."""
    return LogFile(LOG_FILE if path is None else path, max_bytes, backups)
