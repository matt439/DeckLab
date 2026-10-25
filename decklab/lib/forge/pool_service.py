"""Local TCP pool service, wire validation, discovery and remote tickets.

pool.py keeps the public entry points and shared settings. Read those through
runtime so existing callers, overrides and test patches use one binding.
"""
import json
import os
import queue
import re
import secrets
import socket
import socketserver
import threading
from pathlib import Path
from decklab.lib import config
from . import common, cores, engine, install, processes, simjar, slots

from . import pool as runtime


def identity(setup, eng):
    """What a run's games depend on that the server's pool must share for a command line run
    to play there (wave 2's contract "Compatibility"): the card log's source and jar (its
    stamp's hash), Forge's version and build, the game patches built in, the engine (without
    sides), Java, the heap and forge_pin; and since wave 3 "launch", engine.launch_fields (the
    user folder and its deployed overrides, the AI profile folder, PERFORMANCE_MODE, game
    patches on), and "pin_mode" (cores.pin_mode). Worked out per request on both sides. A run
    of other override sets plays in a user folder of its own, so it never matches the server's:
    it plays in a pool of its own (the module docstring)."""
    log = setup["card_log"]
    return {"protocol": runtime.SERVICE_PROTOCOL, "source": simjar.source_sha256(), "jar": Path(log["jar"]).name,
            "forge": setup["version"], "build": simjar.forge_build(Path(setup["forge_dir"]) / setup["jar"]),
            "game_patches": sorted(log.get("game_patches") or []),
            "engine": {k: v for k, v in eng.items() if k != "sides"}, "java": str(setup["java"]),
            "xmx": str(setup["xmx"]), "forge_pin": cores.pin_setting(),
            "launch": engine.launch_fields(setup, eng), "pin_mode": cores.pin_mode()}


def _differences(mine, theirs):
    """The words for each setting that differs (IDENTITY_WORDS; for the "launch" part, each of
    its fields that differs, LAUNCH_WORDS)."""
    def same(a, b):
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    out = []
    for name in sorted(set(mine) | set(theirs)):
        a, b = mine.get(name), theirs.get(name)
        if same(a, b):
            continue
        if name == "launch" and isinstance(a, dict) and isinstance(b, dict):
            out += [runtime.LAUNCH_WORDS.get(field, field) for field in sorted(set(a) | set(b))
                    if not same(a.get(field), b.get(field))]
        else:
            out.append(runtime.IDENTITY_WORDS.get(name, name))
    return out


def _wire(job):
    """What a command line run sends the service of its job (JSON)."""
    return {"key": job.get("key"), "fmt": job["fmt"], "decks_dir": str(Path(job["setup"]["decks_dir"]).resolve()),
            "dck": list(job["dck"]), "names": job["names"], "base": int(job["base"]), "stream": job["stream"],
            "flip": int(job["flip"]), "ranges": [[int(a), int(b)] for a, b in job["ranges"]],
            "batch": job.get("batch"), "workers": int(job["workers"]), "low": bool(job.get("low")),
            "pilots": job.get("pilots"), "log": job.get("log")}


def _wire_pilot(pilot):
    """Is pilot (from a wire) a pilot: {"profile": a profile name, "switches": [switch ids]}?"""
    return (isinstance(pilot, dict) and isinstance(pilot.get("profile"), str)
            and runtime.PROFILE_RE.fullmatch(pilot["profile"]) is not None and isinstance(pilot.get("switches"), list)
            and all(isinstance(x, str) and simjar.GAME_PATCH_ID.fullmatch(x) for x in pilot["switches"]))


def _wire_log(log):
    """Is log (from a wire) a log tee's {"dir": an absolute folder's path, "every": 1 or more}?"""
    return (isinstance(log, dict) and isinstance(log.get("dir"), str) and Path(log["dir"]).is_absolute()
            and type(log.get("every")) is int and log["every"] >= 1)


def _service_job(wire, setup, eng):
    """A job from a command line run's wire form, played with the server's setup; ValueError
    for one that isn't well formed."""
    def count(x):
        return type(x) is int and x >= 0

    if not (isinstance(wire, dict) and wire.get("fmt") in ("Constructed", "Commander")
            and isinstance(wire.get("dck"), list) and len(wire["dck"]) == 2
            and all(isinstance(d, str) and runtime.NAME_RE.fullmatch(d) for d in wire["dck"])
            and isinstance(wire.get("decks_dir"), str) and Path(wire["decks_dir"]).is_absolute()
            and Path(wire["decks_dir"]).is_dir()
            and isinstance(wire.get("names"), list) and len(wire["names"]) == 2
            and all(isinstance(n, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in n.items())
                    for n in wire["names"])
            and count(wire.get("base")) and isinstance(wire.get("stream"), str)
            and re.fullmatch(r"[0-9a-f]{16}", wire["stream"]) and wire.get("flip") in (0, 1)
            and isinstance(wire.get("ranges"), list) and wire["ranges"]
            and all(isinstance(r, list) and len(r) == 2 and count(r[0]) and count(r[1]) and r[0] < r[1]
                    for r in wire["ranges"])
            and (wire.get("batch") is None or (type(wire["batch"]) is int and wire["batch"] >= 1))
            and type(wire.get("workers")) is int and wire["workers"] >= 1
            and isinstance(wire.get("low", False), bool) and isinstance(wire.get("key") or "", str)
            and (wire.get("pilots") is None or (isinstance(wire["pilots"], list) and len(wire["pilots"]) == 2
                                                and all(runtime._wire_pilot(pilot) for pilot in wire["pilots"])))
            and (wire.get("log") is None or runtime._wire_log(wire["log"]))):
        raise ValueError("not a job")
    return {"key": (wire.get("key") or "")[:64], "setup": dict(setup, decks_dir=Path(wire["decks_dir"])),
            "fmt": wire["fmt"], "dck": wire["dck"], "names": wire["names"], "base": wire["base"],
            "stream": wire["stream"], "flip": wire["flip"], "ranges": wire["ranges"], "batch": wire["batch"],
            "workers": wire["workers"], "low": wire.get("low", False), "engine": eng,
            "pilots": wire.get("pilots"), "log": wire.get("log")}


def _send_line(stream, data, lock=None):
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if lock is None:
        stream.write(text)
        stream.flush()
        return
    with lock:
        stream.write(text)
        stream.flush()


class _Handler(socketserver.StreamRequestHandler):
    """One connection to the pool service (the module docstring)."""

    def handle(self):
        service = self.server.service
        self.connection.settimeout(runtime.HEARTBEAT_TIMEOUT_S)
        try:
            first = json.loads(self.rfile.readline(1 << 22).decode("utf-8"))
        except (OSError, ValueError):
            return
        if not (isinstance(first, dict) and isinstance(first.get("token"), str)
                and secrets.compare_digest(first["token"], service.token)):
            return
        if first.get("op") == "status":
            runtime._send_line(self.wfile, {"what": "status", "status": service.pool.status(), "pid": os.getpid()})
            return
        if first.get("op") == "submit":
            self._submit(service, first)

    def _submit(self, service, first):
        answer, ticket = service.accept(first.get("identity"), first.get("job"))
        runtime._send_line(self.wfile, answer)
        if ticket is None:
            return
        lock, gone = threading.Lock(), threading.Event()

        def forward():
            try:
                while True:
                    try:
                        event = ticket.events.get(timeout=runtime.HEARTBEAT_S)
                    except queue.Empty:         # nothing to say: the command line hears the server's alive
                        runtime._send_line(self.wfile, {"what": "heartbeat"}, lock)
                        continue
                    runtime._send_line(self.wfile, {"what": "event", "event": list(event)}, lock)
                    if event[0] == "done":
                        break
            except (OSError, ValueError):
                ticket.stop()
            finally:
                gone.set()
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        thread = threading.Thread(target=forward, name="pool-service-events", daemon=True)
        thread.start()
        try:
            while not gone.is_set():
                line = self.rfile.readline(1 << 16)
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                if isinstance(message, dict) and message.get("op") == "stop":
                    break
        except (OSError, ValueError):
            pass                # no heartbeat for HEARTBEAT_TIMEOUT_S, or the connection broke
        ticket.stop()
        thread.join(5)


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class _Service:
    """The server's pool service (the module docstring)."""

    def __init__(self, pool):
        self.pool = pool
        self.token = secrets.token_hex(16)
        self.server = runtime._TCPServer(("127.0.0.1", 0), runtime._Handler)
        self.server.service = self
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.2},
                                       name="pool-service", daemon=True)
        self.thread.start()
        self.path = None
        try:
            folder = slots.folder()
            folder.mkdir(parents=True, exist_ok=True)
            runtime._tidy_services(folder)
            self.path = folder / f"forge-pool-{os.getpid()}.json"
            common._write_atomic(self.path, json.dumps({
                "pid": os.getpid(), "port": self.port, "token": self.token, "checkout": str(config.REPO),
                "protocol": runtime.SERVICE_PROTOCOL, "started": common._now(), "identity": runtime._static_identity()}))
        except OSError:
            self.close()
            raise

    def accept(self, theirs, wire):
        """A command line run's submit: ({"what": "accepted", "xmx", "pid"}, its Ticket) when it
        can play here, else ({"what": "refused", "why": [settings], "text"}, None)."""
        try:
            setup = install._setup()
            setup["card_log"] = simjar.card_log(setup["java"], setup["forge_dir"], setup["jar"], setup["version"])
        except runtime.ForgeError as e:
            return {"what": "refused", "why": [], "text": str(e)}, None
        if not setup["card_log"].get("ready"):
            return {"what": "refused", "why": [runtime.CARD_LOG_OFF], "text": runtime.CARD_LOG_OFF}, None
        eng = engine.current(setup, setup["card_log"])
        try:
            mine = runtime.identity(setup, eng)
        except OSError as e:
            return {"what": "refused", "why": [], "text": f"the server can't read its settings ({e})"}, None
        differ = runtime._differences(theirs if isinstance(theirs, dict) else {}, mine)
        if differ:
            return {"what": "refused", "why": differ, "text": ", ".join(differ)}, None
        try:
            job = runtime._service_job(wire, setup, eng)
            ticket = self.pool.submit(job)
        except runtime.PoolClosed:
            return {"what": "refused", "why": [], "text": runtime.SERVER_STOPPING}, None
        except (ValueError, KeyError, TypeError):
            return {"what": "refused", "why": [], "text": "the run's job wasn't one the server could read"}, None
        return {"what": "accepted", "xmx": setup["xmx"], "pid": os.getpid()}, ticket

    def close(self):
        try:
            self.server.shutdown()
            self.server.server_close()
        except OSError:
            pass
        if self.path is not None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("pid") == os.getpid():
                    self.path.unlink()
            except (OSError, ValueError):
                pass


def _static_identity():
    """The part of the server's identity that doesn't need Java (its state file's)."""
    try:
        settings = common._settings()
        return {"forge_dir": str(settings.get("forge_dir")), "xmx": str(settings.get("forge_xmx")),
                "forge_pin": cores.pin_setting(settings)}
    except Exception:
        return {}


def _tidy_services(folder):
    """Delete the state files of pool services whose process has ended."""
    try:
        paths = list(folder.glob(runtime.SERVICE_GLOB))
    except OSError:
        return
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            dead = not processes.alive(data.get("pid"))
        except (OSError, ValueError, AttributeError):
            dead = True
        if dead:
            try:
                path.unlink()
            except OSError:
                pass


def services():
    """The pool services running on this PC: [{"pid", "port", "token", "checkout", ...}],
    this checkout's first; a file whose process has ended is skipped."""
    found = []
    try:
        paths = sorted(slots.folder().glob(runtime.SERVICE_GLOB))
    except OSError:
        return []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (isinstance(data, dict) and type(data.get("port")) is int and isinstance(data.get("token"), str)
                and processes.alive(data.get("pid"))):
            continue
        found.append(data)
    return sorted(found, key=lambda d: (d.get("checkout") != str(config.REPO), d.get("started") or ""))


def _connect(found):
    connection = socket.create_connection(("127.0.0.1", found["port"]), timeout=runtime.CONNECT_S)
    connection.settimeout(runtime.ANSWER_S)
    return connection


def service_status(found):
    """A pool service's status (pool.status() in the server), or None when it doesn't answer."""
    try:
        with runtime._connect(found) as connection:
            stream = connection.makefile("rwb")
            runtime._send_line(stream, {"token": found["token"], "op": "status"})
            answer = json.loads(stream.readline(1 << 22).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return answer.get("status") if isinstance(answer, dict) and answer.get("what") == "status" else None


def _remote(job):
    """Submit job to a running server's pool service: (a Placement, None), or (None, the line
    saying why it plays locally, or None when no server is running)."""
    found = runtime.services()
    if not found:
        return None, None
    try:
        mine = runtime.identity(job["setup"], job["engine"])
    except OSError:
        return None, None
    differ = None
    for service in found:
        try:
            connection = runtime._connect(service)
        except OSError:
            continue
        try:
            stream = connection.makefile("rwb")
            runtime._send_line(stream, {"token": service["token"], "op": "submit", "identity": mine, "job": runtime._wire(job)})
            answer = json.loads(stream.readline(1 << 22).decode("utf-8") or "null")
        except (OSError, ValueError):
            connection.close()
            continue
        if isinstance(answer, dict) and answer.get("what") == "accepted":
            ticket = runtime._RemoteTicket(connection, stream)
            return runtime.Placement(ticket, "remote", answer.get("xmx") or job["setup"]["xmx"], setup=job["setup"]), None
        connection.close()
        if isinstance(answer, dict) and answer.get("what") == "refused" and differ is None:
            differ = answer.get("text") or "unknown"
    if differ is None:
        return None, None
    return None, runtime.OTHER_SETTINGS.format(what=differ)


class _RemoteTicket:
    """A run's ticket in the server's pool, through its service: the same events as a
    Ticket's (and ("lost", why) when the connection goes before "done", or the service says
    nothing, not even its heartbeat, for HEARTBEAT_TIMEOUT_S), and stop()."""

    def __init__(self, connection, stream):
        self.events = queue.Queue()
        self._connection, self._stream = connection, stream
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._stopping = False
        self._connection.settimeout(runtime.HEARTBEAT_TIMEOUT_S)
        self._reader = threading.Thread(target=self._read, name="pool-remote-events", daemon=True)
        self._reader.start()
        threading.Thread(target=self._heartbeat, name="pool-remote-heartbeat", daemon=True).start()

    def _read(self):
        done = False
        try:
            while True:
                line = self._stream.readline(1 << 24)
                if not line:
                    break
                message = json.loads(line.decode("utf-8"))
                if isinstance(message, dict) and message.get("what") == "event":
                    event = tuple(message["event"])
                    if event == ("done", "closed"):
                        break           # the server's pool closed under the run: as lost
                    self.events.put(event)
                    if event[0] == "done":
                        done = True
                        break
        except (OSError, ValueError, KeyError, TypeError):
            pass                # (a socket timeout too: the server said nothing for HEARTBEAT_TIMEOUT_S)
        if not done and not self._closed.is_set() and not self._stopping:
            self.events.put(("lost", "the connection to the server's pool closed"))
        self._close()

    def _heartbeat(self):
        while not self._closed.wait(runtime.HEARTBEAT_S):
            try:
                runtime._send_line(self._stream, {"op": "heartbeat"}, self._lock)
            except (OSError, ValueError):
                return

    def stop(self):
        """Stop: the service stops this run's chunks and sends the games they read before it
        (then "done"); returns once those are in events, or after STOP_DRAIN_S, so the run
        keeps every game the service read."""
        if self._closed.is_set():
            return
        self._stopping = True
        try:
            runtime._send_line(self._stream, {"op": "stop"}, self._lock)
        except (OSError, ValueError):
            pass
        else:
            if threading.current_thread() is not self._reader:
                self._reader.join(runtime.STOP_DRAIN_S)
        self._close()

    def _close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        for close in (lambda: self._connection.shutdown(socket.SHUT_RDWR), self._stream.close,
                      self._connection.close):
            try:
                close()
            except (OSError, ValueError):
                pass
