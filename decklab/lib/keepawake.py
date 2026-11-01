"""Keeping the PC awake while Deck Lab is in use (wake-on-request).

Deck Lab may run on a PC that sleeps when idle (S3) and is woken by a
Wake-on-LAN magic packet whenever someone opens the site (the wake gate on the
home NAS, and the Cloudflare Worker for visits from outside). Windows' own idle
timer doesn't see web requests, so without this the PC could fall asleep in the
middle of someone's visit or a Forge run. KeepAwake holds a power request (the
PC stays awake; the screen may still turn off) while Deck Lab is busy:

- for config.json's "wake" "idle_minutes" (default 20) after the last real
  request (note_activity: page loads and API calls; never HEAD, GET
  /api/status, the page's timer polls marked X-Deck-Lab-Poll: 1, or the
  page's static files: counts_as_activity), and
- while any registered provider gives a reason (a Forge run, practice hands,
  the card data's update): each is a callable returning a short reason or None.

One daemon thread checks every INTERVAL seconds. When the PC slept for more
than RESUME_GAP seconds since the last check, the on_resume callbacks run (the
server restarts the tunnel at once, its connections being stale). On Windows
that's read without the wall clock (which a time sync or a manual change can
move): GetTickCount64 counts on through sleep, QueryUnbiasedInterruptTime
stops while asleep, so the gap between them grows only by the time spent
asleep (sleep_counter). Elsewhere the wall clock jumping much further than
INTERVAL means a sleep, and a backwards jump is ignored.

On Windows the request is PowerCreateRequest / PowerSetRequest
(PowerRequestSystemRequired) / PowerClearRequest with the reason "Deck Lab is
in use" (powercfg /requests lists it); if those aren't available,
SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED), which belongs to
the thread that set it, so it's set and cleared on the controller's own thread.
Elsewhere nothing is held: Linux would use systemd-inhibit (not implemented).

hold_while() is the same primitive for a command line's process (the nightly
database run, a command-line Forge run), released when it ends.

    "wake": {"idle_minutes": 20, "gate": "http://<nas address>:8650"}
"""
import contextlib
import sys
import threading
import time

INTERVAL = 15                   # seconds between checks
RESUME_GAP = 60                 # seconds asleep (or, by the wall clock, past INTERVAL) that mean the PC slept
DEFAULT_IDLE_MINUTES = 20
REASON = "Deck Lab is in use"
POLL_HEADER = "X-Deck-Lab-Poll"
# The page's own files: loading them is part of a page load (counted by "/"), and a
# cached page's revalidations aren't use.
STATIC_SUFFIXES = (".js", ".css", ".woff2", ".png", ".ico", ".svg", ".jpg", ".webp", ".webmanifest", ".json")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
POWER_REQUEST_SYSTEM_REQUIRED = 1       # POWER_REQUEST_TYPE's PowerRequestSystemRequired
POWER_REQUEST_CONTEXT_VERSION = 0
POWER_REQUEST_CONTEXT_SIMPLE_STRING = 0x1


def wake_settings(settings):
    """config.json's "wake" as {"idle_minutes", "gate"}, or None when it has none (the PC is
    taken never to sleep). idle_minutes outside 1-1440 or not a whole number gives the
    default; gate is a string or None."""
    wake = (settings or {}).get("wake")
    if not isinstance(wake, dict):
        return None
    minutes = wake.get("idle_minutes", DEFAULT_IDLE_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 1440:
        minutes = DEFAULT_IDLE_MINUTES
    gate = wake.get("gate")
    gate = gate.strip().rstrip("/") if isinstance(gate, str) and gate.strip() else None
    return {"idle_minutes": minutes, "gate": gate}


def idle_minutes_of(settings):
    """The idle minutes to hold for: the "wake" block's, else the default (holding while
    busy is harmless on a PC that never sleeps)."""
    wake = wake_settings(settings)
    return wake["idle_minutes"] if wake else DEFAULT_IDLE_MINUTES


def counts_as_activity(method, path, headers=None):
    """True for a request that is someone using Deck Lab: page loads and API calls. Not a
    HEAD, GET /api/status (the footer's check), a request marked X-Deck-Lab-Poll: 1 (the
    page's timers), nor a GET of one of the page's static files."""
    method = (method or "").upper()
    if method == "HEAD" or method == "OPTIONS":
        return False
    if headers is not None and hasattr(headers, "get") and (headers.get(POLL_HEADER) or "").strip() == "1":
        return False
    path = (path or "").split("?", 1)[0].split("#", 1)[0]
    if method == "GET":
        if path.rstrip("/") == "/api/status":
            return False
        if not path.startswith("/api/") and path.lower().endswith(STATIC_SUFFIXES):
            return False
    return True


# ------------------------------------------------------------ the power primitive

class _WindowsPower:
    """A power request on Windows: hold() and release(), idempotent. Must be used from one
    thread when it falls back to SetThreadExecutionState (KeepAwake's own thread does)."""

    def __init__(self, reason=REASON):
        self.reason = reason
        self._handle = None
        self._fallback = False
        self.held = False

    def _create(self):
        import ctypes
        from ctypes import wintypes

        class _Context(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("Flags", wintypes.DWORD),
                        ("SimpleReasonString", wintypes.LPWSTR)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create = kernel32.PowerCreateRequest
        create.restype = wintypes.HANDLE
        create.argtypes = [ctypes.POINTER(_Context)]
        self._reason_buffer = ctypes.create_unicode_buffer(self.reason)
        context = _Context(POWER_REQUEST_CONTEXT_VERSION, POWER_REQUEST_CONTEXT_SIMPLE_STRING,
                           ctypes.cast(self._reason_buffer, wintypes.LPWSTR))
        handle = create(ctypes.byref(context))
        if not handle or handle == wintypes.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "PowerCreateRequest failed")
        self._kernel32 = kernel32
        return handle

    def hold(self):
        if self.held:
            return
        import ctypes
        if not self._fallback and self._handle is None:
            try:
                self._handle = self._create()
            except (OSError, AttributeError):
                self._fallback = True
        if not self._fallback and self._kernel32.PowerSetRequest(self._handle, POWER_REQUEST_SYSTEM_REQUIRED):
            self.held = True
            return
        self._fallback = True
        if ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
            self.held = True

    def release(self):
        if not self.held:
            return
        import ctypes
        if self._fallback:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        else:
            self._kernel32.PowerClearRequest(self._handle, POWER_REQUEST_SYSTEM_REQUIRED)
        self.held = False


class _NoPower:
    """Elsewhere: nothing is held (Linux would use systemd-inhibit; not implemented)."""

    held = False

    def hold(self):
        self.held = True

    def release(self):
        self.held = False


def platform_power():
    """The power primitive for this platform: an object with hold() and release()."""
    return _WindowsPower() if sys.platform == "win32" else _NoPower()


@contextlib.contextmanager
def hold_while(power=None):
    """Keep the PC awake for the with block (a command line's process: the nightly run),
    released at its end. Never raises over the power request itself."""
    power = power or platform_power()
    try:
        power.hold()
    except Exception:                       # noqa: BLE001 (keeping awake is best effort)
        pass
    try:
        yield power
    finally:
        try:
            power.release()
        except Exception:                   # noqa: BLE001
            pass


# ------------------------------------------------------------- noticing a sleep

def _windows_sleep_counter():
    """A callable returning the seconds this Windows PC has spent asleep since it started:
    GetTickCount64 (milliseconds, counting through sleep) minus QueryUnbiasedInterruptTime
    (100-nanosecond units, stopped while asleep). Raises OSError or AttributeError when they
    can't be read."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ticks = kernel32.GetTickCount64
    ticks.restype = ctypes.c_ulonglong
    ticks.argtypes = []
    unbiased = kernel32.QueryUnbiasedInterruptTime
    unbiased.restype = ctypes.c_int
    unbiased.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]

    def counter():
        value = ctypes.c_ulonglong(0)
        if not unbiased(ctypes.byref(value)):
            raise OSError(ctypes.get_last_error(), "QueryUnbiasedInterruptTime failed")
        return ticks() / 1000.0 - value.value / 10_000_000.0
    counter()                               # fails here, not on the first tick
    return counter


def sleep_counter():
    """The platform's counter of seconds spent asleep (only Windows has one), or None: then
    KeepAwake goes by the wall clock."""
    if sys.platform != "win32":
        return None
    try:
        return _windows_sleep_counter()
    except (OSError, AttributeError, ValueError):
        return None


_PLATFORM = object()                        # KeepAwake's slept default: sleep_counter()


# ------------------------------------------------------------------ the controller

class KeepAwake:
    """Holds the PC awake while Deck Lab is in use (the module docstring says when).
    clock is the wall clock (time.time), used for noticing a sleep only when slept is None;
    slept returns the seconds spent asleep so far (default: sleep_counter(), None where there's
    none); monotonic is the idle timer's clock and power holds/releases: all injectable for
    tests."""

    def __init__(self, idle_minutes=DEFAULT_IDLE_MINUTES, *, power=None, clock=time.time,
                 monotonic=time.monotonic, interval=INTERVAL, log=None, slept=_PLATFORM):
        self.idle_minutes = idle_minutes
        self.power = power
        self.clock, self.monotonic, self.interval = clock, monotonic, interval
        self.slept = sleep_counter() if slept is _PLATFORM else slept
        self._last_slept = None
        self.log = log or (lambda text: None)
        self._providers = []
        self._on_resume = []
        self._lock = threading.Lock()
        self._last_activity = monotonic()   # starting counts as use: someone woke it to start it
        self._last_tick = None
        self._reasons = []
        self._failed = set()                # providers whose exception was logged
        self._stop = threading.Event()
        self._thread = None

    def note_activity(self):
        self._last_activity = self.monotonic()

    def add_provider(self, fn):
        self._providers.append(fn)

    def on_resume(self, fn):
        self._on_resume.append(fn)

    def _busy_reasons(self):
        reasons = []
        for fn in list(self._providers):
            try:
                reason = fn()
            except Exception as e:          # noqa: BLE001 (logged once per provider)
                if fn not in self._failed:
                    self._failed.add(fn)
                    self.log(f"Keep awake: a busy check failed ({type(e).__name__}: {e}); it's ignored.")
                continue
            if reason:
                reasons.append(str(reason))
        return reasons

    def _asleep_for(self):
        """Seconds the PC slept since the last check when that's a sleep (over RESUME_GAP), else
        None. A counter that can't be read or goes backwards counts as no sleep."""
        if self.slept is not None:
            try:
                value = float(self.slept())
            except Exception as e:          # noqa: BLE001 (logged once)
                if "slept" not in self._failed:
                    self._failed.add("slept")
                    self.log(f"Keep awake: the sleep counter failed ({type(e).__name__}: {e}).")
                return None
            last, self._last_slept = self._last_slept, value
            if last is not None and value - last > RESUME_GAP:
                return value - last
            return None
        now = self.clock()
        last, self._last_tick = self._last_tick, now
        if last is not None and now - last > self.interval + RESUME_GAP:
            return now - last               # a backwards jump (now < last) is never a sleep
        return None

    def tick(self):
        """One check: run on_resume after a sleep, then hold or release. True while holding."""
        asleep = self._asleep_for()
        if asleep is not None:
            self.log(f"Keep awake: the PC was asleep for about {round(asleep / 60)} minutes.")
            for fn in list(self._on_resume):
                try:
                    fn()
                except Exception as e:      # noqa: BLE001
                    self.log(f"Keep awake: after waking, {type(e).__name__}: {e}")
            # Being woken is a visit on its way: give it the idle time before sleeping again.
            self.note_activity()
        reasons = self._busy_reasons()
        idle = self.monotonic() - self._last_activity
        if idle < self.idle_minutes * 60:
            reasons.insert(0, "in use")
        with self._lock:
            self._reasons = reasons
        if self.power is None:
            self.power = platform_power()
        try:
            if reasons:
                self.power.hold()
            else:
                self.power.release()
        except Exception as e:              # noqa: BLE001 (best effort)
            if "power" not in self._failed:
                self._failed.add("power")
                self.log(f"Keep awake: the power request failed ({type(e).__name__}: {e}).")
        return bool(reasons)

    def holding(self):
        return bool(getattr(self.power, "held", False))

    def status(self):
        """{"holding", "reasons", "idle_minutes", "idle_seconds"} for /api/status's script view."""
        with self._lock:
            reasons = list(self._reasons)
        return {"holding": self.holding(), "reasons": reasons, "idle_minutes": self.idle_minutes,
                "idle_seconds": round(max(0.0, self.monotonic() - self._last_activity))}

    def _run(self):
        try:
            while not self._stop.is_set():
                self.tick()
                if self._stop.wait(self.interval):
                    break
        finally:
            if self.power is not None:
                try:
                    self.power.release()        # on this thread: SetThreadExecutionState's owner
                except Exception:               # noqa: BLE001
                    pass

    def start(self):
        self._thread = threading.Thread(target=self._run, name="keep-awake", daemon=True)
        self._thread.start()
        return self

    def stop(self, wait=5):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(wait)


_CURRENT = None


def install(controller):
    """Make controller the one note_activity() reaches (the server's); None removes it."""
    global _CURRENT
    _CURRENT = controller


def current():
    return _CURRENT


def note_activity():
    """Someone is using Deck Lab (server_http, for each request counts_as_activity passes)."""
    controller = _CURRENT
    if controller is not None:
        controller.note_activity()
