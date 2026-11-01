"""Deck Lab's wake gate: a tiny always-on web server for the NAS that wakes the Deck Lab PC.

The Deck Lab PC sleeps when nobody uses it. This script runs on an always-on box on the same
network (the NAS, in a python:3-alpine container; see compose.yaml and README.md beside it) and
sends the PC a Wake-on-LAN magic packet whenever someone opens Deck Lab:

    GET  /__status   200 {"awake": bool, "waking": bool, "since": seconds or null,
                          "pc": "http://PC_HOST:PC_PORT"}, with Access-Control-Allow-Origin set
                     to exactly that origin, so only Deck Lab's own page on the PC can read it
    POST /__wake     202 {"sent": bool, "retry_after": seconds}  (at most one packet per
                     WAKE_MIN_INTERVAL seconds)
    GET  /<anything> the PC answers: 302 to http://PC_HOST:PC_PORT/<anything>; asleep: sends the
                     packet and shows a "Deck Lab is waking up" page that moves on by itself

A request that came through Cloudflare (Cf-Ray, Cf-Connecting-Ip or Cf-Access-Jwt-Assertion)
may only POST /__wake: everything else is 404, so the public wake hostname tells nobody about
the home network.

Settings are environment variables: DECKLAB_PC_MAC (required), DECKLAB_PC_HOST (required),
DECKLAB_PC_PORT (8642), GATE_PORT (8650), WOL_BROADCAST (255.255.255.255), WOL_PORT (9),
WAKE_MIN_INTERVAL (30), WAKE_TIMEOUT (180).

Standard library only, Python 3.9 or later; it imports nothing from Deck Lab.
"""
import json
import math
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLOUDFLARE_HEADERS = ("cf-ray", "cf-connecting-ip", "cf-access-jwt-assertion")
CHECK_TIMEOUT = 2.0
CHECK_CACHE = 1.0
MAX_BODY = 64 * 1024
# The MAC .env.example and the README use as an example: refused, so a copied example never
# leaves the gate broadcasting to nobody.
PLACEHOLDER_MAC = bytes.fromhex("aabbccddeeff")

_MAC = re.compile(r"^[0-9A-Fa-f]{2}([:-])[0-9A-Fa-f]{2}(\1[0-9A-Fa-f]{2}){4}$")


class ConfigError(ValueError):
    """A setting the gate can't start with."""


def log(message):
    print("wakegate: " + message, flush=True)


# ---------------------------------------------------------------- pure pieces

def parse_mac(text):
    """The 6 bytes of a MAC address written aa:bb:cc:dd:ee:ff or aa-bb-cc-dd-ee-ff."""
    text = (text or "").strip()
    if not _MAC.match(text):
        raise ConfigError("DECKLAB_PC_MAC must look like aa:bb:cc:dd:ee:ff (or with -), not %r" % text)
    return bytes(int(part, 16) for part in re.split("[:-]", text))


def magic_packet(mac):
    """Wake-on-LAN's magic packet: six 0xFF bytes, then the MAC sixteen times."""
    if len(mac) != 6:
        raise ValueError("a MAC address is 6 bytes")
    return b"\xff" * 6 + bytes(mac) * 16


def is_cloudflare(headers):
    """Whether a request came through Cloudflare (it carries one of Cloudflare's own headers)."""
    names = {str(name).lower() for name in headers.keys()}
    return any(name in names for name in CLOUDFLARE_HEADERS)


def split_target(target):
    """(path, query) of a request target, or None for one that isn't a plain "/path" (an
    absolute URL such as http://elsewhere/, "*", or anything with spaces or control characters)."""
    if not isinstance(target, str) or not target.startswith("/"):
        return None
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in target):
        return None
    path, _, query = target.partition("?")
    return path, query


def pc_url(host, port, target):
    """The Deck Lab PC's address for the same path and query, built only from the configured host
    and port (never the request's Host header); None when the target isn't a plain "/path"."""
    parts = split_target(target)
    if parts is None:
        return None
    path, query = parts
    if path.startswith("//"):
        path = "/" + path.lstrip("/")
    host_part = "[%s]" % host if ":" in host else host
    return "http://%s:%d%s%s" % (host_part, port, path, ("?" + query) if query else "")


def pc_origin(host, port):
    """The Deck Lab PC's origin, "http://host:port" (port always included), the exact address the
    gate redirects to; Deck Lab's page compares it with its own location.origin."""
    return pc_url(host, port, "/")[:-1]


def route(method, target, from_cloudflare):
    """What to do with a request: "wake", "status", "page", "not_found" or "bad_request"."""
    parts = split_target(target)
    if parts is None:
        return "bad_request"
    path = parts[0]
    if from_cloudflare:
        return "wake" if method == "POST" and path == "/__wake" else "not_found"
    if path == "/__wake":
        return "wake" if method == "POST" else "not_found"
    if method != "GET":
        return "not_found"
    if path == "/__status":
        return "status"
    return "page"


def _int_setting(env, name, default, low, high):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError("%s must be a whole number, not %r" % (name, raw))
    if not low <= value <= high:
        raise ConfigError("%s must be between %d and %d, not %d" % (name, low, high, value))
    return value


class Config:
    def __init__(self, mac, pc_host, pc_port=8642, gate_port=8650, broadcast="255.255.255.255",
                 wol_port=9, min_interval=30, timeout=180):
        self.mac = mac
        self.pc_host = pc_host
        self.pc_port = pc_port
        self.gate_port = gate_port
        self.broadcast = broadcast
        self.wol_port = wol_port
        self.min_interval = min_interval
        self.timeout = timeout

    @classmethod
    def from_env(cls, env):
        mac = parse_mac(env.get("DECKLAB_PC_MAC"))
        if mac == PLACEHOLDER_MAC:
            raise ConfigError("DECKLAB_PC_MAC is still the example aa:bb:cc:dd:ee:ff: set it to the "
                              "Deck Lab PC's own wired network card")
        host = (env.get("DECKLAB_PC_HOST") or "").strip()
        if not host:
            raise ConfigError("DECKLAB_PC_HOST must be the Deck Lab PC's address, such as 192.168.1.20")
        if not re.match(r"^[0-9A-Za-z.:\-]+$", host) or host.startswith(("-", ".")):
            raise ConfigError("DECKLAB_PC_HOST must be an IP address or a host name, not %r" % host)
        broadcast = (env.get("WOL_BROADCAST") or "").strip() or "255.255.255.255"
        try:
            socket.inet_aton(broadcast)
            if broadcast.count(".") != 3:
                raise OSError
        except OSError:
            raise ConfigError("WOL_BROADCAST must be an IPv4 address, not %r" % broadcast)
        return cls(
            mac=mac, pc_host=host,
            pc_port=_int_setting(env, "DECKLAB_PC_PORT", 8642, 1, 65535),
            gate_port=_int_setting(env, "GATE_PORT", 8650, 1, 65535),
            broadcast=broadcast,
            wol_port=_int_setting(env, "WOL_PORT", 9, 1, 65535),
            min_interval=_int_setting(env, "WAKE_MIN_INTERVAL", 30, 1, 3600),
            timeout=_int_setting(env, "WAKE_TIMEOUT", 180, 10, 3600))


# ---------------------------------------------------------------- the real network

def send_packet(packet, address, port):
    """Broadcast one magic packet over UDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (address, port))
    finally:
        sock.close()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def check_pc(host, port, timeout=CHECK_TIMEOUT):
    """Whether Deck Lab answers on the PC: a 200, or any answer with its X-Deck-Lab-Origin header."""
    url = pc_url(host, port, "/api/status")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "X-Deck-Lab-Poll": "1"})
    try:
        with _opener.open(request, timeout=timeout) as answer:
            return answer.status == 200 or answer.headers.get("X-Deck-Lab-Origin") is not None
    except urllib.error.HTTPError as error:
        return error.code == 200 or error.headers.get("X-Deck-Lab-Origin") is not None
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------- the gate

class Gate:
    """The wake state: when the last packet went, when this wake attempt began, and the PC's
    last answer. send(packet), check() and clock() can be replaced (the tests do)."""

    def __init__(self, config, send=None, check=None, clock=time.monotonic):
        self.config = config
        self._send = send or (lambda packet: send_packet(packet, config.broadcast, config.wol_port))
        self._check = check or (lambda: check_pc(config.pc_host, config.pc_port))
        self._clock = clock
        self._packet = magic_packet(config.mac)
        self._lock = threading.Lock()
        self._check_lock = threading.Lock()
        self._last_sent = None
        self._since = None
        self._checked_at = None
        self._awake = False

    def awake(self):
        """Whether the PC answers, asked at most once a second."""
        with self._check_lock:
            now = self._clock()
            if self._checked_at is None or now - self._checked_at >= CHECK_CACHE:
                try:
                    self._awake = bool(self._check())
                except Exception as error:  # a broken check must not stop the gate
                    log("checking the PC failed: %s" % error)
                    self._awake = False
                self._checked_at = self._clock()
            awake = self._awake
        if awake:
            with self._lock:
                self._since = None
        return awake

    def wake(self):
        """Send the magic packet unless one went in the last WAKE_MIN_INTERVAL seconds.
        Returns (sent, retry_after)."""
        interval = self.config.min_interval
        with self._lock:
            now = self._clock()
            if self._last_sent is not None and now - self._last_sent < interval:
                return False, max(1, int(math.ceil(interval - (now - self._last_sent))))
            self._last_sent = now
            if self._since is None or now - self._since >= self.config.timeout:
                self._since = now
        try:
            self._send(self._packet)
        except Exception as error:
            log("sending the wake packet failed: %s" % error)
            return False, interval
        log("wake packet sent to %s:%d" % (self.config.broadcast, self.config.wol_port))
        return True, interval

    def status(self):
        awake = self.awake()
        with self._lock:
            since = self._since
            now = self._clock()
        if awake or since is None:
            return {"awake": awake, "waking": False, "since": None}
        elapsed = max(0, int(now - since))
        return {"awake": False, "waking": elapsed < self.config.timeout, "since": elapsed}

    def origin(self):
        return pc_origin(self.config.pc_host, self.config.pc_port)

    def target(self, request_target):
        return pc_url(self.config.pc_host, self.config.pc_port, request_target)


# ---------------------------------------------------------------- the waking page

def waking_page(target, timeout):
    """The page shown while the PC wakes. It loads nothing from anywhere else, asks /__status
    every 2 seconds and opens `target` once the PC answers; after `timeout` seconds it says it
    couldn't wake it, with Try again."""
    target_js = json.dumps(target).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return """<!doctype html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="color-scheme" content="light dark">
<title>Deck Lab is waking up</title>
<style>
:root { --page: #f1f0ec; --surface: #ffffff; --ink: #161616; --ink-2: #46453f; --border: rgb(0 0 0 / .12);
  --accent: #0f6e6a; --accent-ink: #ffffff; color-scheme: light dark; }
@media (prefers-color-scheme: dark) {
  :root { --page: #111113; --surface: #1b1b1e; --ink: #f2f2ef; --ink-2: #c4c3bd; --border: rgb(255 255 255 / .12);
    --accent: #4cc2b8; --accent-ink: #0b1f1d; }
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; background: var(--page); color: var(--ink);
  font: 17px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 32rem; margin: 14vh auto 0; padding: 0 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-top: 4px solid var(--accent);
  border-radius: 12px; padding: 24px 20px; }
h1 { font-size: 1.5rem; line-height: 1.25; margin: 0 0 12px; }
p { margin: 0 0 16px; }
.wait { color: var(--ink-2); font-size: .95rem; }
a.button { display: inline-flex; align-items: center; font-weight: 600; min-height: 44px; padding: 0 20px;
  border-radius: 8px; background: var(--accent); color: var(--accent-ink); text-decoration: none; }
a.button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
[hidden] { display: none !important; }
</style>
</head>
<body>
<main>
<div class="card" id="waking">
<h1>Deck Lab is waking up</h1>
<p>The computer at home was asleep, so it's starting up. This usually takes under a minute.</p>
<p>Deck Lab opens by itself when it's ready.</p>
<p class="wait" id="elapsed" role="status">Waiting&hellip;</p>
</div>
<div class="card" id="failed" hidden>
<h1>Deck Lab couldn't be woken</h1>
<p>The computer at home didn't answer. It may be turned off or unplugged, or not connected to the network.</p>
<a class="button" href="" id="again">Try again</a>
</div>
</main>
<script>
(() => {
  const target = %(target)s;
  const limit = %(timeout)d * 1000;
  const started = Date.now();
  const elapsed = document.getElementById("elapsed");
  let timer = 0;
  function giveUp() {
    clearTimeout(timer);
    document.getElementById("waking").hidden = true;
    document.getElementById("failed").hidden = false;
  }
  async function check() {
    clearTimeout(timer);
    const spent = Date.now() - started;
    if (spent >= limit) { giveUp(); return; }
    const s = Math.floor(spent / 1000);
    elapsed.textContent = s < 1 ? "Waiting\\u2026" : "Waiting\\u2026 " + s + (s === 1 ? " second" : " seconds") + " so far.";
    try {
      const r = await fetch("/__status", { cache: "no-store", headers: { Accept: "application/json" } });
      if (r.ok && (await r.json()).awake) { location.replace(target + location.hash); return; }
    } catch (e) { /* the gate didn't answer this time; ask again */ }
    timer = setTimeout(check, 2000);
  }
  document.getElementById("again").addEventListener("click", (event) => {
    event.preventDefault();
    location.reload();
  });
  check();
})();
</script>
</body>
</html>
""" % {"target": target_js, "timeout": timeout}


# ---------------------------------------------------------------- the server

def make_handler(gate):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DeckLabWakeGate"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):  # no line for every poll
            pass

        def log_error(self, format, *args):
            log("request error: " + (format % args))

        def _send(self, code, body=b"", content_type=None, headers=()):
            self.send_response(code)
            if content_type:
                self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, code, value, headers=()):
            self._send(code, json.dumps(value).encode("utf-8"), "application/json", headers)

        def _drain(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if 0 < length <= MAX_BODY:
                self.rfile.read(length)
            elif length > MAX_BODY:
                self.close_connection = True

        def _handle(self):
            if self.command == "POST":
                self._drain()
            try:
                action = route(self.command, self.path, is_cloudflare(self.headers))
                if action == "wake":
                    sent, retry_after = gate.wake()
                    self._json(202, {"sent": sent, "retry_after": retry_after},
                               headers=(("Retry-After", str(retry_after)),))
                elif action == "status":
                    # Only Deck Lab's own page on the PC may read this cross-origin (it checks
                    # "pc" against its location.origin before sending anyone to the gate).
                    origin = gate.origin()
                    self._json(200, dict(gate.status(), pc=origin),
                               headers=(("Access-Control-Allow-Origin", origin), ("Vary", "Origin")))
                elif action == "page":
                    target = gate.target(self.path)
                    if gate.awake():
                        self._send(302, b"", headers=(("Location", target),))
                    else:
                        gate.wake()
                        page = waking_page(target, gate.config.timeout).encode("utf-8")
                        self._send(200, page, "text/html; charset=utf-8",
                                   headers=(("Content-Security-Policy",
                                             "default-src 'none'; style-src 'unsafe-inline'; "
                                             "script-src 'unsafe-inline'; connect-src 'self'"),
                                            ("Referrer-Policy", "no-referrer")))
                elif action == "bad_request":
                    self._send(400, b"Bad request\n", "text/plain; charset=utf-8")
                else:
                    self._send(404, b"Not found\n", "text/plain; charset=utf-8")
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                log("answering %s failed: %s" % (self.command, error))
                try:
                    self._send(500, b"Something went wrong\n", "text/plain; charset=utf-8")
                except OSError:
                    pass

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle

    return Handler


def make_server(gate, host="0.0.0.0", port=None):
    server = ThreadingHTTPServer((host, gate.config.gate_port if port is None else port), make_handler(gate))
    server.daemon_threads = True
    return server


def main(env=None):
    try:
        config = Config.from_env(os.environ if env is None else env)
    except ConfigError as error:
        print("wakegate: " + str(error), file=sys.stderr, flush=True)
        return 2
    gate = Gate(config)
    try:
        server = make_server(gate)
    except OSError as error:
        print("wakegate: can't listen on port %d: %s" % (config.gate_port, error), file=sys.stderr, flush=True)
        return 2
    log("listening on port %d; waking the PC at %s (Deck Lab on port %d)"
        % (config.gate_port, config.pc_host, config.pc_port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
