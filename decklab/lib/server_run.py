"""Starting, running and stopping one Deck Lab server process.

_serve listens on the home address (lib/server_http.py's make_server), opens
the tunnel's listener and the tunnel, keeps the card data fresh, starts the
warm pool, records the state file and answers stop requests, Ctrl+C, the
window closing and Windows logging off, until it stops. decklab/server.py's
main() calls it; that script's docstring describes how the server runs.
"""
import _thread
import errno
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime

from decklab.lib import access, api, cards, control, dbstatus, server_http, tunnel, venv, visits

UPDATE_EVERY = 24 * 60 * 60         # seconds between background card-data checks
RETRY_AFTER = 10 * 60               # ... and after one that failed (e.g. no network yet)
FORGE_STOP_WAIT = 15                # seconds a stopping server waits for its matchups to save their games
CLOSE_WAIT = 4                      # ... when its window closes (Windows ends it about 5 s after)
# Seconds the stopping server gives its warm pool's workers to quit before it kills them. Its
# runs have saved their games by then (a stopped run saves what its chunks read at once), so
# a worker still finishing a cancelled game has nothing left to give.
POOL_STOP_WAIT = 3


def _start_remote(settings, port, default_port, web_dir=None):
    """The tunnel's listener on 127.0.0.1:<"access" port>, serving in a thread
    of its own, when config.json has "access" and this is the usual server
    (as for the tunnel: tunnel.usual_server); else None. A listener that
    can't start is logged loudly (the tunnel then isn't started either)."""
    try:
        setup = access.settings_of(settings)
    except ValueError as e:
        server_http.log(f"{_stamp()} ACCESS: {e}. The tunnel's listener isn't opened, so the tunnel isn't started.")
        return None
    if setup is None or not tunnel.usual_server(port, default_port):
        return None
    try:
        remote = server_http.make_server("127.0.0.1", setup["port"], web_dir,
                             access=access.Verifier(setup["team"], setup["aud"]),
                             tunnel_hosts=access.tunnel_hosts(settings))
    except (OSError, OverflowError) as e:
        server_http.log(f"{_stamp()} ACCESS: can't listen for the tunnel on 127.0.0.1:{setup['port']}: {e}. "
            f"The tunnel isn't started.")
        return None
    threading.Thread(target=remote.serve_forever, name="tunnel-listener", daemon=True).start()
    server_http.log(f"{_stamp()} Deck Lab for the tunnel: listening on 127.0.0.1:{setup['port']} (Cloudflare Access "
        f"logins only, for {', '.join(sorted(remote.tunnel_hosts)) or 'no host names'})")
    return remote


def _update_loop():
    while True:
        api.update_cards(log=server_http.log)
        time.sleep(RETRY_AFTER if api.carddata.UPDATE["error"] else UPDATE_EVERY)


def _load_index():
    try:
        cards.info()
    except cards.INDEX_ERRORS as e:
        server_http.log(f"The card index can't be loaded: {type(e).__name__}: {e}")


def _database_check(background):
    """The database's start-up checks, without holding up the start: logs why .venv's
    packages (psycopg) aren't in use when they aren't, starts dbstatus's checker thread
    (the footer's "database" block, once a minute), and after its first check logs one line
    saying how the database is and, for the background server only, copies config.json's
    profiles into the database (profiles_sync, with the state store's timeouts). Nothing here is fatal: card pages work
    without the database. Migrations are never applied here. Returns the callable that stops
    it all; nothing is logged once that's called."""
    reason = venv.reason()
    if reason:
        server_http.log(f"{_stamp()} Database: .venv's packages aren't in use ({reason}).")
    lock = threading.Lock()
    stopped = []

    def say(text):
        with lock:
            if not stopped:
                server_http.log(f"{_stamp()} Database: {text}")

    def first(snapshot):
        say(dbstatus.describe(snapshot) + ".")
        if not background or snapshot["error"] in (dbstatus.NOT_REACHABLE, dbstatus.PSYCOPG_MISSING):
            return
        try:
            from decklab.db import profiles_sync
            from decklab.lib.state import pg
            # On dbstatus's thread: the request path's timeouts, so a lock held elsewhere
            # fails the sync (one line) rather than stalling the checks and the breaker.
            summary = profiles_sync.sync(timeout=pg.REQUEST_TIMEOUT, options=pg.REQUEST_OPTIONS)
        except Exception as e:                      # noqa: BLE001 (logged in one line, never fatal)
            detail = (str(e).strip().splitlines() or [type(e).__name__])[0]
            say(f"profiles not synced: {detail}")
            return
        say(f"profiles {profiles_sync.describe(summary)}.")

    def stop():
        with lock:
            stopped.append(True)
        dbstatus.stop()

    dbstatus.start(first)
    return stop


# Windows console events. After the last two, Windows ends the process as soon
# as the handler returns (and about 5 seconds after the window closed in any
# case). Microsoft's HandlerRoutine docs say a logoff (5) and a shutdown (6)
# only reach services, so a server in a console window never sees them; a
# shutdown is still handled like the window closing, in case it ever runs as
# one, and a logoff (anyone's, for a service) is left alone.
CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_SHUTDOWN = 0, 1, 2, 6


def ctrl_handler(stop, wait, interrupt, closed=None):
    """A Windows console control handler (it runs in a thread of its own):
    - Ctrl+C: stop(), then False, so Python goes on to raise KeyboardInterrupt
      in the main thread as usual, and main() waits for a matchup to save.
    - Ctrl+Break: stop() and interrupt() (the same KeyboardInterrupt), then
      True. Python has no Ctrl+Break handler of its own, so without this the
      C runtime would end the process at once, losing a matchup's games.
    - The window closing or a shutdown: stop(), then (for the window only)
      closed(), then wait(CLOSE_WAIT) for a matchup to stop its Forge
      processes and save every game it finished, then True (Windows then
      ends the process, so _serve's finally never runs).
    Anything else is left to the next handler (False). A step that fails
    doesn't stop the others: an exception would make ctypes return False at
    once."""
    def step(fn, *args):
        try:
            fn(*args)
        except Exception:
            pass                # nowhere to say so: the console may be going

    def handler(event):
        if event not in (CTRL_C, CTRL_BREAK, CTRL_CLOSE, CTRL_SHUTDOWN):
            return False
        step(stop)
        if event == CTRL_C:
            return False
        if event == CTRL_BREAK:
            step(interrupt)
        else:
            if event == CTRL_CLOSE and closed is not None:
                step(closed)
            step(wait, CLOSE_WAIT)
        return True
    return handler


def _console_handler(port=None):
    """ctrl_handler() for the server: stop both job runners (api.stop_jobs),
    wait for the matchups that are playing (api.forge_runs.FORGE_JOBS.join) and
    then kill the warm pool's workers at once (_stop_pool(0): Windows ends the
    process moments later), and interrupt the main thread (serve_forever) for
    Ctrl+Break. Closing the window is a stop on purpose (E11-S26), so with a
    port it leaves the stop marker the watchdog reads (a shutdown doesn't:
    the next logon starts it anyway)."""
    def wait(seconds):
        try:
            _join_runs(seconds)
        finally:
            _stop_pool(0)

    def closed():
        if port is not None:
            control.mark_stopped(port, "window closed", keep=True)

    return ctrl_handler(lambda: api.stop_jobs(), wait, lambda: _thread.interrupt_main(), closed)


def _stop_jobs_on_ctrl_c(port=None):
    """Stop the job runners (practice hands and Forge matchups) the moment
    Ctrl+C or Ctrl+Break is pressed or the window is closed (_console_handler).
    Windows sends Ctrl+C to every process on the console, the practice-hand
    workers too, and each handler runs at once in a thread of its own;
    Python's KeyboardInterrupt only reaches serve_forever() at its next poll
    (up to half a second). Without this, a run whose workers died in that
    time would be logged as a failure and the next waiting run started.
    (Forge's processes have consoles of their own, so these events never
    reach them.) The callback is kept in _CTRL_C for as long as the process
    lives (Windows holds on to it). port is the server's, for the stop
    marker closing the window leaves."""
    global _CTRL_C
    if sys.platform != "win32" or _CTRL_C is not None:
        return
    import ctypes
    from ctypes import wintypes
    _CTRL_C = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)(_console_handler(port))
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_CTRL_C, True)


def _wait_for_matchup(wait=FORGE_STOP_WAIT):
    """After api.stop_jobs(): the matchups that were playing (up to 4 at once)
    stop within about a second and save every game they finished, so wait up
    to wait seconds for them before the server exits (and stops the warm
    pool). (Should it take longer, lib/forge/processes.py's Windows job object
    still kills every Forge process when the server's process ends.)"""
    if api.forge_runs.FORGE_JOBS.active() or api.forge_runs.COORD_JOBS.active():
        server_http.log("Stopping the Forge matchups that are playing...")
        if not _join_runs(wait):
            server_http.log(f"The Forge matchups didn't stop within {wait} seconds.")


def _join_runs(seconds):
    """Wait up to seconds in all for the matchups (api.forge_runs.FORGE_JOBS) and wave 3's
    field runs and variant tests (COORD_JOBS) to stop; True when both have."""
    deadline = time.monotonic() + seconds
    done = api.forge_runs.FORGE_JOBS.join(seconds)
    return api.forge_runs.COORD_JOBS.join(max(0.0, deadline - time.monotonic())) and done


_CTRL_C = None

def _start_pool():
    """Start the warm pool the server's matchups play in, and its service for command line
    runs (lib/forge/pool.py start_server_pool; its workers start with the first chunk).
    When Deck Lab's Forge code can't be loaded, the log says why and the server goes on
    (matchups then answer that they aren't available)."""
    try:
        import importlib
        forge = importlib.import_module("decklab.lib.forge")
    except Exception:
        server_http.log(f"The warm pool for Forge matchups couldn't start:\n{traceback.format_exc()}")
        return
    try:
        # Wave 3 (forge-trial/sim-wave3-contract.md section 6.2): Forge's user folder holds
        # exactly the adopted card-script overrides before any key is worked out.
        forge.overrides.ensure_deployed(forge.common._user_dir())
    except Exception:
        server_http.log(f"Deck Lab's card-script overrides couldn't be put in place:\n{traceback.format_exc()}")
    try:
        forge.pool.start_server_pool()
    except Exception:
        server_http.log(f"The warm pool for Forge matchups couldn't start:\n{traceback.format_exc()}")


def _stop_pool(wait=POOL_STOP_WAIT):
    """Stop the warm pool (after the matchups have stopped and saved): its service, then
    its workers, killing those still alive after wait seconds (0: at once). Nothing to do
    when the Forge code was never loaded."""
    forge = sys.modules.get("decklab.lib.forge")
    pool = getattr(forge, "pool", None)
    if pool is None:
        return
    try:
        pool.stop_server_pool(wait)
    except Exception:
        server_http.log(f"The warm pool didn't stop cleanly:\n{traceback.format_exc()}")


# ------------------------------------------------- running without a window

def _stamp():
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"


def _stop_handler(server, message="Stop requested.", on_purpose=None, by="stop request"):
    """What a stop request (--stop, homenet stop) does, in the stop event's
    thread (control.listen_for_stop), and taskkill /PID without /F too, in a
    thread of the session-end window's (control.watch_session_end's
    on_close): what Ctrl+C does. The job runners stop at once and
    serve_forever() returns; main() then waits for the matchups to save their
    games, stops the warm pool, and exits. message is the line logged first;
    by is added to the list on_purpose (when given), so _serve leaves a stop
    marker as it exits."""
    def on_stop():
        if on_purpose is not None:
            on_purpose.append(by)
        server_http.log(f"{_stamp()} {message}")
        api.stop_jobs()
        server.shutdown()
    return on_stop


def _session_end_handler(server, finished):
    """What Windows logging off or shutting down does, in the session-end
    window's thread (control.watch_session_end): what closing the window does
    (stop the job runners, wait up to CLOSE_WAIT seconds for the matchups to
    save their games, and kill the warm pool's workers), then end
    serve_forever(). Windows ends the process soon after this returns, so it
    then waits only for what's left of CLOSE_WAIT for main() to finish
    (finished), and never for serve_forever's next poll (shutdown() runs in a
    thread of its own)."""
    def on_end():
        deadline = time.monotonic() + CLOSE_WAIT
        server_http.log(f"{_stamp()} Windows is logging off or shutting down: stopping.")
        api.stop_jobs()
        _join_runs(max(0.0, deadline - time.monotonic()))
        _stop_pool(0)               # the runs have saved: the warm workers go at once
        threading.Thread(target=server.shutdown, name="shutdown", daemon=True).start()
        finished.wait(max(0.0, deadline - time.monotonic()))
    return on_end


def _stop_command(port, default_port):
    """What stops the server on port without its window."""
    if port == default_port:
        return "python -m decklab.lib.homenet stop"
    return f"python decklab/server.py --port {port} --stop"


def _when(state):
    """A state's start time as people read it ("2026-10-01 09:12")."""
    try:
        return datetime.fromisoformat(state["started"]).strftime("%Y-%m-%d %H:%M")
    except (KeyError, TypeError, ValueError):
        return "at an unknown time"


def _port_in_use(error):
    """True when a bind failed because something else has the port: WinError
    10048 (WSAEADDRINUSE), or 10013 (WSAEACCES), which is what a port held
    with SO_EXCLUSIVEADDRUSE gives (Server.server_bind); EADDRINUSE or
    EACCES elsewhere. A bad address (10049) or anything else is not."""
    if sys.platform == "win32":
        return getattr(error, "winerror", None) in (10048, 10013)
    return getattr(error, "errno", None) in (errno.EADDRINUSE, errno.EACCES)


def _cant_listen(host, port, error, default_port):
    """Why the server can't listen on (host, port): for a port in use,
    another Deck Lab server there (when the state file says so); else what
    the error says."""
    running = control.read_state() if _port_in_use(error) else None
    if running and running.get("port") == port:
        return (f"Deck Lab is already running (process {running.get('pid')}, started {_when(running)}). "
                f"Stop it with: {_stop_command(port, default_port)}")
    return f"Can't listen on {host}:{port}: {error}"


def _record_state(host, port, log_path, background):
    """Write the state file (control.write_state), unless it names another
    Deck Lab server that's still running: that one keeps its record."""
    running = control.read_state()
    if running and running.get("pid") != os.getpid():
        server_http.log(f"Deck Lab isn't recorded in {control.STATE_FILE}: it names another server that's running "
            f"(process {running.get('pid')}, port {running.get('port')}).")
        return
    state = {"version": control.STATE_VERSION, "pid": os.getpid(), "host": host, "port": port,
             "started": datetime.now().astimezone().isoformat(timespec="seconds"),
             "python": sys.executable, "log": log_path, "background": background}
    try:
        control.write_state(state)
    except OSError as e:
        server_http.log(f"Can't write {control.STATE_FILE}: {e}")


def _start(what, fn, *args):
    """fn(*args), or None and a line in the log when it fails: the server
    still works, but can't hear of what."""
    try:
        return fn(*args)
    except OSError as e:
        server_http.log(f"Deck Lab can't listen for {what}: {e}")
        return None

def _serve(host, port, no_update, settings, log_path, background):
    """Listen on (host, port) and answer requests until stopped; the exit code."""
    default_port = settings.get("port", 8642)
    # The tunnel's host names belong to the tunnel's listener: the home
    # listener refuses them (421) rather than accepting them, with "access"
    # or without it (missing or wrong: _start_remote says why), so a tunnel
    # pointed back at it fails closed (access.home_refused_hosts).
    hosts = access.home_refused_hosts(settings)
    home_hosts = [h for h in settings.get("allowed_hosts") or [] if str(h).strip().lower().rstrip(".") not in hosts]
    try:
        server = server_http.make_server(host, port, allowed_hosts=home_hosts, tunnel_hosts=hosts)
    except (OSError, OverflowError) as e:       # port in use, bad address, port over 65535
        server_http.log(_cant_listen(host, port, e, default_port))
        return 1
    host, port = server.server_address[:2]
    shown = socket.gethostname() if host in ("0.0.0.0", "::") else host
    how = f"stop it with: {_stop_command(port, default_port)}" if background else "Ctrl+C stops it"
    server_http.log(f"{_stamp()} Deck Lab: http://{shown}:{port}/  (listening on {host}:{port}; {how})")
    finished = threading.Event()
    on_purpose = []                 # how it was asked to stop, when it was (a stop marker as it exits)
    stop_listener = session = tunnel_proc = remote = stop_database = None
    try:
        # Listening for a stop before the state file names this server, so
        # whoever reads it can stop it; and only now the port is this
        # server's (see control.listen_for_stop). A stop that comes before
        # serve_forever() starts still stops it: serve_forever() then
        # returns at once.
        stop_listener = _start("stop requests", control.listen_for_stop, port,
                               _stop_handler(server, on_purpose=on_purpose))
        session = _start("Windows logging off", control.watch_session_end,
                         _session_end_handler(server, finished), None,
                         _stop_handler(server, "Asked to close (taskkill): stopping.", on_purpose, "taskkill"))
        _start_pool()
        _record_state(host, port, log_path, background)
        # Running again: a stop marker from before (homenet stop) no longer
        # holds, whoever started it (the logon trigger, start, a window).
        control.clear_stopped(port)
        stop_database = _database_check(background)
        remote = _start_remote(settings, port, default_port)
        tunnel_proc = tunnel.start(settings, port, default_port, server_http.log,
                                   remote.server_address[1] if remote is not None else None)
        threading.Thread(target=_load_index if no_update else _update_loop, name="card-data", daemon=True).start()
        _stop_jobs_on_ctrl_c(port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            on_purpose.append("Ctrl+C")
            server_http.log("Stopping.")
    finally:
        # The database checks first: nothing after this may start profiles_sync or log
        # a "Database:" line, however long the rest takes or whether it raises.
        if stop_database is not None:
            stop_database()
        if tunnel_proc is not None:         # outside visits stop first
            tunnel_proc.stop()
        if remote is not None:
            remote.shutdown()
            remote.server_close()
        # A practice run in progress ends at its next chunk, a matchup within
        # about a second (saving every game it finished), and none waiting starts.
        api.stop_jobs()
        server.server_close()
        visits.close()                      # the visits gathered since the last minute's write
        _wait_for_matchup()
        # Only now the warm pool: its runs have stopped and saved their games.
        _stop_pool()
        if on_purpose:
            # Stopped on request, so the watchdog leaves it off (a marker that
            # homenet stop wrote first stays, naming it).
            try:
                control.mark_stopped(port, on_purpose[0], keep=True)
            except OSError as e:
                server_http.log(f"Can't record the stop in {control.stop_marker_path(port)}: {e}")
        control.clear_state(os.getpid())
        if stop_listener is not None:
            stop_listener.close()
        finished.set()
        if session is not None:
            session.close()
    server_http.log(f"{_stamp()} Deck Lab has stopped.")
    return 0
