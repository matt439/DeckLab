"""Deck Lab's HTTP layer: one request in, one answer out.

The Handler routes each request (the API, the page's files, card images and
accessory pictures), checks its host, query, body and writes, and logs it;
Server is the threaded listener and make_server binds one. decklab/server.py
is the script that runs them: its docstring has the table of URLs and the
security rules these follow, and lib/server_run.py starts and stops them.
"""
import gzip
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import socketserver
import sys
import time
import traceback
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from decklab.lib import (access, api, build, config, dbstatus, home_scope, inventory, keepawake, permissions, state,
                         visibility, visits)

WEB_DIR = config.DECKLAB / "web"
IMAGE_MAX_AGE = 7 * 24 * 60 * 60    # a printing's image never changes
# Domains home routers and mDNS give a PC's name (homepc.local, homepc.lan).
HOME_SUFFIXES = ("local", "lan", "home", "localdomain", "home.arpa", "internal")

# Content types of the files the page may load; anything else in web/ isn't served.
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}
STATIC_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9]+)+")
STATIC_FOLDERS = ("", "icons", "fonts")      # web/ itself, web/icons/ and web/fonts/
PAGE_PARAMS = ("v", "profile", "theme")     # query parameters index.html accepts

# The page's text files are sent gzipped to a client that accepts it; fonts and pictures are
# compressed already (E11-S64).
GZIP_SUFFIXES = (".html", ".js", ".css", ".webmanifest", ".json", ".svg")
# A script or stylesheet asked for with the current web revision's ?v= stamp (index.html
# stamps them) never changes under that address, so the browser keeps it without asking again.
# private, never public: Cloudflare keeps nothing outside the login.
STAMPED_SUFFIXES = (".js", ".css")
STAMP_LENGTH = 16                   # characters of the web revision in a stamped address
IMMUTABLE = "private, max-age=31536000, immutable"
STATIC_CACHE_FILES = 2048           # the in-memory copies are dropped past this many files

JSON_TYPE = "application/json; charset=utf-8"
# A request body refused unread (413, 403, 415) is read and dropped before the
# connection closes, up to this many bytes within this many seconds: closing a
# socket with unread data resets the connection, and the client (Windows,
# a phone's browser) can then lose the answer it hadn't read yet and show a
# network error instead of the 413's message.
DRAIN_BYTES = 4 * api.MAX_EDIT_BODY
DRAIN_SECONDS = 2
GET = ("GET", "HEAD")
COORD_WAITING = ("queued", "running")      # a field run's or variant test's statuses answered with 202
WRITE_HEADER = ("X-Deck-Lab", "1")      # every POST and PUT must carry it (check_write)
# On every answer (_send), so the off page's Worker (decklab/cloudflare/) tells Deck Lab's own
# 502s and 503s from Cloudflare's "can't reach the PC" errors and never replaces them.
ORIGIN_HEADER = ("X-Deck-Lab-Origin", "1")
# Clickjacking defence in depth (E11-S63): no answer may be shown in another site's frame, where
# the cross-site write check (check_write) can't see that a signed-in person's clicks are borrowed.
# X-Frame-Options is for browsers that ignore the policy's frame-ancestors.
FRAME_HEADER = ("X-Frame-Options", "DENY")
NO_FRAMES = "frame-ancestors 'none'"
# An HTML answer (index.html, a refusal's page): everything from Deck Lab's own files, pictures also
# from data: (the stylesheets' icons, a chosen photo's preview) and blob: (a photo preview). So no
# inline script and no style="" attribute: index.html has neither, and core.js's el() sets a style
# through the element's style object, which the policy allows.
PAGE_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; "
               "img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; form-action 'self'; " + NO_FRAMES)
# The one address outside Deck Lab the page reads: the wake gate's /__status (core.js's openWakeGate),
# on the home listener only, where config.json's "wake" names one. Only a plain origin is ever written
# into the policy, so nothing in config.json can add a directive.
_GATE_HOST = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?\Z")


def gate_origin(gate):
    """The wake gate's origin as a policy source (http://nas.example:8650), or None when there's no
    gate or it isn't a plain http(s) address."""
    if not isinstance(gate, str):
        return None
    try:
        parts = urllib.parse.urlsplit(gate.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not _GATE_HOST.match(parts.netloc):
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def page_policy(gate=None):
    """PAGE_POLICY, with the wake gate's origin as one more place the page may read."""
    origin = gate_origin(gate)
    return PAGE_POLICY.replace("connect-src 'self'", f"connect-src 'self' {origin}") if origin else PAGE_POLICY


# Every other answer (JSON, a script, a stylesheet, a picture): nothing, should it ever be opened as a page.
DATA_POLICY = "default-src 'none'; " + NO_FRAMES
# /sym: Scryfall's SVG, which carries its own <style>, and is sandboxed.
SYMBOL_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox; " + NO_FRAMES
# Only on the tunnel's listener, which browsers reach over https alone; the home listener is plain
# http by the PC's name or address, where the header would mean nothing (and must never be learnt).
HSTS_HEADER = ("Strict-Transport-Security", "max-age=31536000")
# The device features the page may use: the camera, for scanning cards (E7-S32), and nothing else
# listed here. No frame gets any.
PERMISSIONS_HEADER = ("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), "
                      "accelerometer=(), gyroscope=(), magnetometer=()")
# Sec-Fetch-Site values a write may come with: the page itself, or a tool typed by hand.
WRITE_SITES = ("same-origin", "none")
# The client addresses a script's request may come from (access.SCRIPT_HEADER): this PC's loopback,
# as IPv4, IPv6 and IPv4 mapped into IPv6. Never the PC's LAN address.
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


def log(text):
    """One line to stderr (pythonw has none)."""
    if sys.stderr is not None:
        sys.stderr.write(text.rstrip("\n") + "\n")
        sys.stderr.flush()


class StaticBody:
    """One answer's bytes with their ETag and, made when first asked for, their gzipped form
    with an ETag of its own."""

    def __init__(self, body):
        self.body = body
        digest = hashlib.sha256(body).hexdigest()
        self.etag = f'"{digest}"'
        self.gzip_etag = f'"{digest}-gzip"'
        self._gzipped = None

    def gzipped(self):
        if self._gzipped is None:
            # mtime=0: the same bytes every time, so the ETag describes them.
            self._gzipped = gzip.compress(self.body, compresslevel=6, mtime=0)
        return self._gzipped


_STATIC_CACHE = {}      # {path: ((st_mtime_ns, st_size), StaticBody)}: each served file as last read


def _stat_key(path):
    info = os.stat(path)
    return info.st_mtime_ns, info.st_size


def static_body(path):
    """((st_mtime_ns, st_size), StaticBody) for a served file: the copy in memory while the
    file's size and modified time are those it was read at, else read (and remembered)
    again, so an edited or pulled file is served without a restart."""
    key = str(path)
    stat_key = _stat_key(path)
    cached = _STATIC_CACHE.get(key)
    if cached is not None and cached[0] == stat_key:
        return cached
    entry = (stat_key, StaticBody(Path(path).read_bytes()))
    if _stat_key(path) != stat_key:
        return entry        # changed while it was read: answer with what was read, remember nothing
    if len(_STATIC_CACHE) >= STATIC_CACHE_FILES:
        _STATIC_CACHE.clear()
    _STATIC_CACHE[key] = entry
    return entry


def accepts_gzip(header):
    """Whether an Accept-Encoding header takes gzip: named (or covered by *) with a q above 0."""
    named = star = None
    for part in (header or "").split(","):
        coding, _, params = part.partition(";")
        coding = coding.strip().lower()
        quality = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if coding in ("gzip", "x-gzip"):
            named = quality > 0 if named is None else named and quality > 0
        elif coding == "*":
            star = quality > 0
    return bool(star) if named is None else named


def static_files(web_dir=None):
    """{URL path: file} for the page's files: those directly in web/, web/icons/ and web/fonts/
    with a known type, and "/" for index.html. Nothing else can be served."""
    web_dir = Path(web_dir or WEB_DIR)
    files = {}
    for folder in STATIC_FOLDERS:
        try:
            entries = list(os.scandir(web_dir / folder))
        except OSError:
            continue
        for entry in entries:
            suffix = os.path.splitext(entry.name)[1].lower()
            if (entry.is_file(follow_symlinks=False) and STATIC_NAME_RE.fullmatch(entry.name)
                    and suffix in STATIC_TYPES):
                files["/" + "/".join(filter(None, (folder, entry.name)))] = Path(entry.path)
    if "/index.html" in files:
        files["/"] = files["/index.html"]
    return files


def host_name(host):
    """A Host header's name, lowercase, without its port or a final dot."""
    host = (host or "").strip().lower()
    if host.startswith("["):                        # [IPv6]:port
        name = host[1:].split("]", 1)[0]
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name.rstrip(".")


def host_allowed(host, extra=()):
    """True for a Host header naming this server the way the home network
    does: an IP address, localhost, this PC's name alone or with a home
    network suffix (homepc, HomePC.local, homepc.lan, ...), or a name in
    extra. No header (HTTP/1.0) is allowed too. A name Linux gives as a
    full name (homepc.home.arpa) counts whole and by its first label
    (homepc, homepc.local: what avahi announces)."""
    if not host:
        return True
    name = host_name(host)
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    full = socket.gethostname().lower().rstrip(".")
    names = {"localhost", full}
    for pc in {full, full.split(".", 1)[0]}:
        names |= {pc} | {f"{pc}.{suffix}" for suffix in HOME_SUFFIXES}
    return name in names or name.endswith(".localhost") or name in {h.lower() for h in extra}


class NotAllowed(api.ApiError):
    """405: the path exists, but not for this method."""

    def __init__(self, method, allowed):
        super().__init__(405, f"{method} isn't allowed here")
        self.allow = ", ".join(allowed)


class Refused(api.ApiError):
    """403 on the tunnel's listener: no valid Cloudflare Access login, or one
    for an email no profile has; or on the home listener, a request naming a
    profile outside the home (Handler._home_only). Answered in JSON under
    /api/, else as a short page."""


TUNNEL_ONLY = ("This address only takes visits from the home network: Deck Lab's tunnel has a listener of "
               "its own (\"access\" in config.json)")


class Handler(BaseHTTPRequestHandler):
    """One request: route it, answer in JSON (or the file), log it.

    self.identity is who is asking: None on the home listener (the page's
    chooser picks a profile), or, on the tunnel's listener, the identity the
    Cloudflare Access login is for (access.Verifier.identify: {"profile",
    "email", "remote": True}). access.current() gives the same to the code
    the request calls, for as long as it's being answered."""

    identity = None

    server_version = "DeckLab"
    protocol_version = "HTTP/1.1"       # keep-alive: a deck page loads dozens of images
    timeout = 60                        # seconds a quiet connection is kept
    # Headers and body go out as two writes; with Nagle's algorithm on, the
    # second waited for the client's delayed ACK (about 25 ms per image).
    disable_nagle_algorithm = True

    # ------------------------------------------------------------ plumbing

    def parse_request(self):
        self._started = time.perf_counter()
        if not super().parse_request():
            return False
        if self.request_version == "HTTP/0.9":
            # No headers at all (so no Host to check); nothing here speaks it.
            self.send_error(400, "HTTP/0.9 isn't supported")
            return False
        return True

    def version_string(self):
        return self.server_version          # no Python version in the Server header

    def handle_one_request(self):
        self._status = None
        self._body_read = False
        self._started = time.perf_counter()
        super().handle_one_request()
        if self._status is not None:
            ms = (time.perf_counter() - self._started) * 1000
            path = self.path if isinstance(getattr(self, "path", None), str) else ""
            log(f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.client_address[0]} "
                f"{self._printable(self.command or '-', 40)} {self._printable(path, 300)} "
                f"{self._status} {ms:.0f} ms")

    def _printable(self, text, limit):
        """text for the log, cut to limit, with control characters (such as a
        terminal's escape codes, which could rewrite the console) escaped."""
        return str(text)[:limit].translate(self._control_char_table)

    def log_request(self, code="-", size="-"):
        self._status = int(code) if isinstance(code, int) else code     # logged once it's sent

    def log_error(self, format, *args):
        # A phone keeping a connection open past `timeout` isn't worth a line.
        if not format.startswith("Request timed out"):
            super().log_error(format, *args)

    def log_message(self, format, *args):
        log(f"{datetime.now():%Y-%m-%d %H:%M:%S} {self.client_address[0]} "
            + (format % args).translate(self._control_char_table))

    def send_error(self, code, message=None, explain=None):
        # http.server calls this for requests it can't parse (a bad request
        # line, too many headers, an unknown method): answer in JSON too.
        if message is None:
            message = self.responses.get(code, ("Error",))[0]
        self.close_connection = True
        self._send_json(code, {"error": message})

    def _unread_body(self):
        """True when the request came with a body nothing read. The connection
        then has to close, or the body would be taken for the next request."""
        headers = getattr(self, "headers", None)
        if not hasattr(headers, "get") or self._body_read:
            return False
        return (headers.get("Content-Length", "0").strip() not in ("", "0")
                or bool(headers.get("Transfer-Encoding")))

    def finish(self):
        unread = self.close_connection and self._unread_body()
        super().finish()
        if unread:
            self._drain()

    def _drain(self):
        """After an answer to a request whose body wasn't read: say the answer
        is complete (FIN), then read and drop what the client still sends,
        until it closes, sends the whole body, DRAIN_BYTES or DRAIN_SECONDS,
        so the socket closes without a reset (see DRAIN_BYTES). A body
        declared bigger than DRAIN_BYTES isn't waited for."""
        length = (self.headers.get("Content-Length") or "").strip()
        wanted = int(length) if length.isascii() and length.isdigit() else DRAIN_BYTES
        if wanted > DRAIN_BYTES:
            return
        sock = self.connection
        deadline = time.monotonic() + DRAIN_SECONDS
        try:
            sock.shutdown(socket.SHUT_WR)
            while wanted > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                sock.settimeout(left)
                chunk = sock.recv(min(65536, wanted))
                if not chunk:
                    break
                wanted -= len(chunk)
        except OSError:         # the client reset or timed out: nothing more to do
            pass

    def _send(self, status, body, content_type, headers=(), *, stream=None, length=None):
        if self._unread_body():
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body) if stream is None else length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(*ORIGIN_HEADER)
        self.send_header(*FRAME_HEADER)
        self.send_header(*PERMISSIONS_HEADER)
        if getattr(self.server, "remote", False):
            self.send_header(*HSTS_HEADER)
        if not any(key.lower() == "content-security-policy" for key, _ in headers):
            html_answer = content_type.split(";")[0].strip().lower() == "text/html"
            self.send_header("Content-Security-Policy", self._page_policy() if html_answer else DATA_POLICY)
        for key, value in headers:
            self.send_header(key, value)
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD" and status not in (204, 304):
            if stream is None:
                self.wfile.write(body)
            else:
                remaining = length
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise ConnectionError("The temporary download ended before its declared length")
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def _page_policy(self):
        # The tunnel's page never reads the gate (it has the off page's Worker): the home page's alone may.
        if getattr(self.server, "remote", False):
            return PAGE_POLICY
        try:
            wake = keepawake.wake_settings(config.load())
        except (OSError, ValueError):       # an unreadable config.json: the page still answers
            return PAGE_POLICY
        return page_policy(wake and wake["gate"])

    def _send_json(self, status, data, headers=()):
        # The one place the stale-inventory warning is added (decklab/lib/inventory): when this
        # request read the database backend's last good snapshot while the database is down.
        stale = inventory.pinned_stale()
        if stale and isinstance(data, dict):
            data = {**data, "inventory_stale": stale}
        snapshot = inventory.pinned_committed_snapshot() or inventory.pinned_snapshot()
        if 200 <= status < 300 and snapshot is not None and self.path.split("?", 1)[0] != "/api/changes":
            from decklab.lib.api import changes
            revisions = changes.current(snapshot)
            if revisions:
                headers = (*headers, (changes.HEADER, json.dumps(revisions, separators=(",", ":"))))
                if inventory.pinned_write():
                    headers = (*headers, (changes.WRITE_HEADER, "1"))
        try:
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate (api refuses them in requests, so this is a
            # last resort): escaped as \udXXX, the answer is still valid JSON.
            body = json.dumps(data, ensure_ascii=True, allow_nan=False).encode("ascii")
        self._send(status, body, JSON_TYPE, (("Cache-Control", "no-store"), *headers))

    def _fail(self, error):
        headers = [("Allow", error.allow)] if isinstance(error, NotAllowed) else []
        path = getattr(self, "path", None)
        if isinstance(error, Refused) and not (isinstance(path, str) and path.startswith("/api/")):
            page = (f"<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width\">"
                    f"<title>Deck Lab</title><p>{html.escape(error.message)}</p>").encode("utf-8")
            return self._send(error.status, page, "text/html; charset=utf-8", [("Cache-Control", "no-store")])
        self._send_json(error.status, {"error": error.message, **getattr(error, "extra", {})}, headers)

    # ------------------------------------------------------------- routing

    def do_GET(self):
        self._handle()

    do_HEAD = do_PUT = do_POST = do_DELETE = do_PATCH = do_OPTIONS = do_GET

    def _handle(self):
        self.identity = None
        try:
            hosts = self.headers.get_all("Host") or []
            if len(hosts) > 1:
                raise api.ApiError(400, "More than one Host header")
            host = hosts[0] if hosts else None
            if not self.server.remote:
                self._home_network_only()
            if self.server.remote:
                self.identity = self._identify(host)
            else:
                self._refuse_tunnel(host)
                if not host_allowed(host, self.server.allowed_hosts):
                    raise api.ApiError(400, "Unknown Host: open Deck Lab by the PC's IP address or name")
            viewer = None if self.identity is not None else (self.headers.get(access.VIEWER_HEADER) or "").strip()
            self._home_only(viewer)
            # One inventory snapshot per request, loaded only if the request reads it.
            with access.using(self.identity), access.viewing(viewer or None), \
                    access.answering(self._is_script(viewer)), inventory.pinned(), visibility.pinned():
                self._note_visit(viewer)
                if keepawake.counts_as_activity(self.command, self.path, self.headers):
                    keepawake.note_activity()       # holds a sleeping PC awake (wake-on-request)
                self._route()
        except api.ApiError as e:
            self._fail(e)
        except state.Unavailable:
            # A safety net: the parts wrap their store calls in api.common.state_errors().
            self._fail(api.ApiError(503, api.common.DATABASE_DOWN, reason="database"))
        except state.Conflict as e:
            # Likewise: a read or write the store refused with a conflict.
            self._fail(api.ApiError(409, str(e)))
        except (ConnectionError, TimeoutError):
            self.close_connection = True        # the phone went away mid-answer
        except Exception as error:
            from decklab.lib import error_references
            reference = error_references.unexpected(error, self.path)
            log(f"Error reference {reference} answering {self._printable(self.command, 40)} {self.path[:300]!r}:\n"
                f"{traceback.format_exc()}")
            if self._status is None:            # nothing sent yet
                self._fail(api.ApiError(500, f"Something went wrong. Reference {reference}; the server log has the details.",
                                        reference=reference))
            else:
                self.close_connection = True

    def _identify(self, host):
        """On the tunnel's listener: the identity of a request for one of the
        tunnel's host names with a valid Cloudflare Access login (access.py);
        400 for another host name, 403 (Refused) otherwise."""
        if not host or host_name(host) not in self.server.tunnel_hosts:
            raise api.ApiError(400, "Unknown Host: this listener is for Deck Lab's tunnel only")
        token = access.token_of(self.headers)
        if not token:
            raise Refused(403, "Sign in through Cloudflare Access first: open Deck Lab's address again")
        try:
            return self.server.access.identify(token)
        except access.AccessError as e:
            if e.status != 403:
                raise api.ApiError(e.status, e.message) from None
            raise Refused(403, e.message) from None

    def _refuse_tunnel(self, host):
        """On the home listener: 421 for a request that came through Cloudflare
        (one of its headers, or a tunnel host name), so a tunnel pointed at the
        home listener can't hand out its no-login editing."""
        if any(self.headers.get(name) is not None for name in access.CLOUDFLARE_HEADERS):
            raise api.ApiError(421, TUNNEL_ONLY)
        if host and host_name(host) in self.server.tunnel_hosts:
            raise api.ApiError(421, TUNNEL_ONLY)

    def _home_network_only(self):
        """On the home listener: 403 naming nobody for a visit from outside the home networks
        (home_scope: loopback, private, link-local and unique local addresses, and config.json's
        "home_networks"), logged once per address."""
        client = self.client_address[0]
        if home_scope.allowed(client, self.server.home_networks):
            return
        if self.server.refusals.first(client):
            log(f"{datetime.now():%Y-%m-%d %H:%M:%S} Refused visits from {self._printable(client, 60)}: it isn't "
                'on a home network (add it to "home_networks" in config.json if it should be).')
        raise Refused(403, home_scope.REFUSED)

    def _is_script(self, viewer):
        """True for a script's request (access.script()): on the home listener, from loopback
        (127.0.0.1 or ::1; the PC asking its own LAN address isn't), with exactly one
        X-Deck-Lab-Script: 1 and no viewer named, and on Linux from this user's own socket
        (script_peer_ok). Off Linux an optional configured script_secret also needs its
        exact secret header. The tunnel's listener grants neither header anything."""
        if self.server.remote or viewer:
            return False
        if (self.headers.get_all(access.SCRIPT_HEADER) or []) != ["1"]:
            return False
        from decklab.lib import script_secret
        return (self.client_address[0] in LOOPBACK and script_peer_ok(self)
                and script_secret.accepts(self.headers, self.server.script_secret))

    def _home_only(self, profile_id):
        """On the home listener, 403 "Sign in through decklab.example.com" for a request naming a
        profile outside the home (its viewer header, ?profile=, an accessory picture's ?viewer=
        or a write body's "profile"): the chooser offers only home profiles, and everyone else
        comes in through the tunnel's login. A name config.json doesn't list is left to the
        route, as before (it names nobody known). Refused, so a page address (an old
        /?profile=user2 bookmark) gets a short page rather than bare JSON. While config.json
        can't be read nobody can be told apart, so every route but /api/status (which names
        nobody's data, and keeps the page's footer answering) gets its 500."""
        if self.server.remote or not isinstance(profile_id, str) or not profile_id.strip():
            return
        try:
            listed = api.settings._config_profiles()
        except api.ApiError:
            if urllib.parse.urlsplit(self.path).path == "/api/status":
                return
            raise
        found = next((p for p in listed if p["id"] == profile_id.strip()), None)
        if found is not None and (found.get("space") or permissions.HOME) != permissions.HOME:
            raise Refused(403, access.SIGN_IN_OUTSIDE)

    def _note_visit(self, viewer):
        """Count an API request in its profile's visits (lib/visits.py): the login's through the
        tunnel, the chooser's on the home network; one naming nobody isn't counted. The recorder
        only gathers in memory and never raises, so the request doesn't wait or fail over it."""
        if not self.path.startswith("/api/"):
            return
        if self.identity is not None:
            visits.recorder().request(self.identity["profile"], "remote")
        elif viewer:
            visits.recorder().request(viewer, "home")

    def _own_profile_only(self, profile_id):
        """403 for a visit through the tunnel that names another profile than its own in the URL."""
        if self.identity is not None and profile_id != self.identity["profile"]:
            raise api.ApiError(403, "You can only change your own profile's settings and wishlist")

    def _allow(self, *methods):
        if self.command not in methods:
            raise NotAllowed(self.command, methods)

    def _route(self):
        split = urllib.parse.urlsplit(self.path)
        if not split.path.startswith("/") or "\\" in split.path:
            raise api.ApiError(400, "Bad path")
        try:
            parts = [urllib.parse.unquote(p, errors="strict") for p in split.path.split("/")[1:]]
        except UnicodeDecodeError:
            raise api.ApiError(400, "Bad path: not UTF-8") from None
        query = split.query

        if parts[0] == "api":
            route = parts[1:]
            if route == ["status"]:
                self._allow(*GET)
                self._no_query(query)
                from decklab.lib.api import guard
                private = {}
                if guard.script():
                    from decklab.db import space_runtime
                    private["forge_lifecycle"] = space_runtime.capability()
                    if keepawake.current() is not None:
                        private["keep_awake"] = keepawake.current().status()
                if not self.server.remote:      # the home network's way back in while the PC sleeps
                    try:
                        wake = keepawake.wake_settings(config.load())
                    except (OSError, ValueError):   # an unreadable config.json: status still answers
                        wake = None
                    if wake and wake["gate"]:
                        private["wake_gate"] = wake["gate"]
                return self._send_json(200, {**api.status(), "build": build.status(),
                                             "database": self._database_status(), **private})
            if route == ["profiles"]:
                self._allow(*GET)
                self._no_query(query)
                return self._send_json(200, api.profiles())
            if route == ["me"]:
                self._allow(*GET)
                self._no_query(query)
                from decklab.lib.profile_config import PendingProfileEdit
                try:
                    identity = access.me(self.identity)
                except PendingProfileEdit:
                    raise api.ApiError(503, "Member settings need local recovery before sign-in can continue.") from None
                from decklab.lib import tunnel
                # Where a printed link (a box label's QR code) should point: the tunnel's address, or the page's own.
                return self._send_json(200, {**identity, "address": tunnel.public_address(config.load())})
            if route == ["visibility"]:
                from decklab.lib.api import visibility as visibility_api
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    return self._send_json(200, visibility_api.change(self._write_body(api.MAX_BODY)))
                return self._send_json(200, visibility_api.view())
            if route == ["visibility", "preview"]:
                from decklab.lib.api import visibility_preview
                self._allow(*GET)
                params = self._query(query, ("owner", "thing"))
                return self._send_json(200, visibility_preview.preview(params.get("owner"), params.get("thing")))
            if route == ["simulations"]:
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    return self._send_json(200, api.change_simulations(self._write_body(api.MAX_BODY)))
                return self._send_json(200, api.simulations_view())
            if route == ["shop-postage"]:
                from decklab.lib.api import shop_postage
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    return self._send_json(200, shop_postage.change(self._write_body(shop_postage.MAX_BODY)))
                return self._send_json(200, shop_postage.view())
            if route == ["storage"]:
                from decklab.lib.api import storage as storage_api
                self._allow(*GET, "PUT")
                if self.command == "PUT":
                    self._no_query(query)
                    return self._send_json(200, storage_api.change(self._write_body(storage_api.MAX_BODY)))
                return self._send_json(200, storage_api.view(**self._query(query, ("space",))))
            if route == ["storage", "preview"]:
                from decklab.lib.api import storage as storage_api
                self._allow("POST")
                self._no_query(query)
                return self._send_json(200, storage_api.preview(self._write_body(storage_api.MAX_BODY)))
            if route == ["pricing-setting"]:
                from decklab.lib.api import pricing_setting
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    return self._send_json(200, pricing_setting.change(self._write_body(pricing_setting.MAX_BODY)))
                return self._send_json(200, pricing_setting.view())
            if route == ["commander-night"]:
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    return self._send_json(200, api.change_commander_night(self._write_body(api.MAX_COMMANDER_NIGHT_BODY)))
                return self._send_json(200, api.commander_night_view())
            if route == ["settings", "members"]:
                from decklab.lib.api import members
                self._allow(*GET)
                self._no_query(query)
                return self._send_json(200, members.view())
            if route == ["settings", "member-email"]:
                from decklab.lib.api import members
                self._allow("POST")
                self._no_query(query)
                return self._send_json(200, members.change(self._write_body(members.MAX_BODY)))
            if route == ["settings", "member"]:
                from decklab.lib.api import members
                self._allow("POST")
                self._no_query(query)
                return self._send_json(200, members.create(self._write_body(members.MAX_BODY)))
            if len(route) == 3 and route[0] == "profiles" and route[2] == "settings":
                self._allow(*GET, "PUT")
                self._no_query(query)
                if self.command == "PUT":
                    self._own_profile_only(route[1])
                    return self._send_json(200, api.put_settings(route[1], self._write_body(api.MAX_BODY)))
                return self._send_json(200, api.get_settings(route[1]))
            if len(route) == 3 and route[0] == "profiles" and route[2] == "wishlist":
                self._allow(*GET, "POST")
                self._no_query(query)
                if self.command == "POST":
                    self._own_profile_only(route[1])
                    return self._send_json(200, api.change_wishlist(route[1], self._write_body(api.MAX_BODY)))
                return self._send_json(200, api.get_wishlist(route[1]))
            if route == ["shopping"]:
                self._allow(*GET)
                self._no_query(query)
                return self._send_json(200, api.shopping_overview())
            if route == ["decks"]:
                self._allow(*GET, "POST")
                self._no_query(query)
                if self.command == "POST":
                    return self._send_json(201, api.create_deck(self._write_body()))
                return self._send_json(200, api.decks_index())
            if route == ["deck"]:
                self._allow(*GET)
                params = self._query(query, ("id", "version", "omit"))
                return self._send_json(200, api.deck_view(self._deck_id(params), params.get("version", "target"),
                                                          omit=api.deck_page.parse_omit(params.get("omit"))))
            if route == ["deck", "edit"]:
                self._allow(*GET)
                return self._send_json(200, api.edit_view(self._deck_id(self._query(query, ("id",)))))
            writes = {("deck", "check"): api.check_draft, ("deck", "save"): api.save_deck,
                      ("decklist", "parse"): api.parse_list, ("tables", "update"): api.update_tables}
            if tuple(route) in writes:
                self._allow("POST")
                self._no_query(query)
                return self._send_json(200, writes[tuple(route)](self._write_body()))
            if route == ["tables", "stale"]:
                self._allow(*GET)
                self._no_query(query)
                return self._send_json(200, api.stale_view())
            if route == ["goldfish"]:
                self._allow(*GET)
                params = self._query(query, ("id", "version", "retry"))
                answer = api.goldfish(self._deck_id(params), params.get("version", "target"), params.get("retry"))
                return self._send_json(202 if answer["status"] == "running" else 200, answer)
            if route == ["matchups"]:
                self._allow(*GET)
                # ?running=1: only the runs waiting or playing (the top bar's "Forge playing" pill).
                running = self._query(query, ("running",)).get("running")
                if running not in (None, "1"):
                    raise api.ApiError(400, "running must be 1")
                return self._send_json(200, api.matchups(running=running == "1"))
            if route == ["matchup"]:
                self._allow(*GET)
                params = self._query(query, ("a", "av", "b", "bv", "key", "profile"))
                answer = api.matchup(self._pair_id(params.get("a")), params.get("av"), self._pair_id(params.get("b")),
                                     params.get("bv"), params.get("key"), params.get("profile"))
                return self._send_json(202 if answer["status"] in api.MATCHUP_WAITING else 200, answer)
            matchup_writes = {("matchup", "run"): api.run_matchup, ("matchup", "stop"): api.stop_matchup}
            if tuple(route) in matchup_writes:
                self._allow("POST")
                self._no_query(query)
                answer = matchup_writes[tuple(route)](self._write_body(api.MAX_BODY))
                return self._send_json(202 if answer["status"] in api.MATCHUP_WAITING else 200, answer)
            # Wave 3 (forge-trial/sim-wave3-contract.md sections 10.5 and 11.5): the field view and
            # paired variant tests, coordinator jobs in api.forge_runs.COORD_JOBS.
            if route == ["field"]:
                self._allow(*GET)
                params = self._query(query, ("id", "version", "profile", "pilot"))
                answer = api.field_view(self._deck_id(params), params.get("version", "target"), params.get("profile"),
                                        pilot=params.get("pilot") == "1")
                return self._send_json(202 if answer.get("status") in COORD_WAITING else 200, answer)
            if route == ["variant"]:
                self._allow(*GET)
                answer = api.variant_view(self._query(query, ("test",)).get("test", ""))
                return self._send_json(202 if answer.get("status") in COORD_WAITING else 200, answer)
            if route == ["variant", "estimate"]:
                self._allow(*GET)
                params = self._query(query, ("id", "version", "against", "av"))
                against = params.get("against")
                return self._send_json(200, api.variant_estimate(
                    self._deck_id(params), params.get("version", "target"),
                    against if against in (None, "field") else self._pair_id(against), params.get("av")))
            if route == ["variants"]:
                self._allow(*GET)
                params = self._query(query, ("id", "version"))
                return self._send_json(200, api.variant_tests(self._deck_id(params), params.get("version", "target")))
            coord_writes = {("field", "run"): (api.run_field, None), ("field", "stop"): (api.stop_field, api.MAX_BODY),
                            ("variant", "run"): (api.run_variant, None),
                            ("variant", "stop"): (api.stop_variant, api.MAX_BODY),
                            ("variant", "more"): (api.more_variant, api.MAX_BODY)}
            if tuple(route) in coord_writes:
                self._allow("POST")
                self._no_query(query)
                handler, limit = coord_writes[tuple(route)]
                answer = handler(self._write_body(limit))
                return self._send_json(202 if answer.get("status") in COORD_WAITING else 200, answer)
            if route == ["cards", "search"]:
                self._allow(*GET)
                params = self._query(query, ("q", "limit", "detail"))
                return self._send_json(200, api.search(params.get("q", ""), params.get("limit"),
                                                       params.get("detail")))
            if route == ["cards", "printings"]:
                self._allow(*GET)
                return self._send_json(200, api.printings(self._query(query, ("name",)).get("name", "")))
            if route == ["cards", "rulings"]:
                self._allow(*GET)
                from decklab.lib.api.card_rulings import card_rulings
                return self._send_json(200, card_rulings(self._query(query, ("name",)).get("name", "")))
            from decklab.lib.feature_routes import dispatch
            if dispatch(self, route, query):
                return
            raise api.ApiError(404, "No such API endpoint")

        if parts[0] == "img" and len(parts) == 4:
            self._allow(*GET)
            self._no_query(query)
            path = api.image_file(*parts[1:])
            return self._send(200, path.read_bytes(), "image/jpeg",
                              [("Cache-Control", f"public, max-age={IMAGE_MAX_AGE}")])

        if parts[0] == "sym" and len(parts) == 2:
            from decklab.lib.api import symbols
            self._allow(*GET)
            self._no_query(query)
            # Scryfall's SVG, shown with <img>, where its scripts never run; the policy covers a direct visit.
            return self._send(200, symbols.symbol_svg(parts[1]), "image/svg+xml",
                              [("Cache-Control", f"public, max-age={IMAGE_MAX_AGE}"),
                               ("Content-Security-Policy", SYMBOL_POLICY)])

        if parts[0] == "accessory-img" and len(parts) in (2, 3):
            return self._accessory_image(parts[1:], query)

        return self._static(parts, query)

    def _database_status(self):
        """/api/status's "database" block (lib/dbstatus.py) for whoever is asking: the viewer
        (guard.viewer), none for a tunnel login that isn't set up, since the footer must
        still answer."""
        from decklab.lib.api import guard
        try:
            viewer = guard.viewer()
        except api.ApiError:
            viewer = None
        return dbstatus.view(viewer, script=guard.script())

    def _accessory_image(self, parts, query):
        """An accessory's picture: /accessory-img/<id>.<ext>?v=<hash> (a
        picture accessories.csv names, from the inventory; v is required and
        must match accessories.image_version, so an address
        names one picture's bytes in the current address epoch. Every saved
        picture is private/no-cache with an ETag: authorization runs before
        revalidation, so revoking Public takes effect on the next request.
        Or /accessory-img/staged/<token>.<ext> (a fetched
        picture not saved yet, never cached). api.accessories.image_file and
        staged_image refuse everything else with 404; a visitor who may not
        see the accessories gets 403 (guard.sees_accessories).

        Both take &viewer=<profile id> too: an <img> sends no
        X-Deck-Lab-Viewer header, so on the home network the page names its
        viewer in the address, and the picture is answered for that profile
        (User2 picked there gets 403, User1 only her own and the shared
        ones). A header, when sent, wins over it; through the tunnel it's
        ignored (the login decides). The address per viewer also keeps a
        shared iPad's browser cache from showing one profile's picture to
        another."""
        from decklab.lib.api import accessories as accessories_api
        from decklab.lib.api import guard
        self._allow(*GET)
        if len(parts) == 1:
            params = self._query(query, ("v", "viewer"))
        elif parts[0] == "staged":
            params = self._query(query, ("viewer",))
        else:
            params = {}                     # 404 below, after the same 403 as for any name
        named = params.get("viewer") or None
        self._home_only(named)
        if self.identity is not None or access.viewer():
            named = access.viewer()         # the login, or the header, decides
        with access.viewing(named):
            guard.require_sees_accessories()        # before the name is looked at: 403 for any name
            if len(parts) == 1:
                if "v" not in params:
                    raise api.ApiError(404, "Not found")
                if not re.fullmatch(r"[0-9a-f]{8}", params["v"]):
                    raise api.ApiError(400, "Bad query parameter value")
                data, content_type = accessories_api.image_file(parts[0], params["v"])
                cache = "private, no-cache"
            elif parts[0] == "staged":
                data, content_type = accessories_api.staged_image(parts[1])
                cache = "no-store"
            else:
                raise api.ApiError(404, "Not found")
        headers = [("Cache-Control", cache)]
        if len(parts) == 1:
            etag = '"' + hashlib.sha256(data).hexdigest() + '"'
            headers.append(("ETag", etag))
            tags = [t.strip().removeprefix("W/") for t in self.headers.get("If-None-Match", "").split(",")]
            if etag in tags or "*" in tags:
                return self._send(304, b"", content_type, headers)
        return self._send(200, data, content_type, headers)

    def _deck_id(self, params):
        return self._pair_id(params.get("id", ""))

    def _pair_id(self, deck_id):
        if deck_id is not None and deck_id.startswith("pairing/"):
            # A "+" typed into the address bar arrives as a space.
            deck_id = deck_id.replace(" ", "+")
        return deck_id

    def _no_query(self, query):
        if query:
            raise api.ApiError(400, "This URL takes no query parameters")

    def _query(self, query, allowed):
        """{name: value} from the query string: only the allowed names, each once."""
        try:
            pairs = urllib.parse.parse_qsl(query, keep_blank_values=True, errors="strict",
                                           max_num_fields=len(allowed) + 1)
        except (ValueError, UnicodeDecodeError):
            raise api.ApiError(400, "Bad query string") from None
        params = {}
        for name, value in pairs:
            if name not in allowed:
                raise api.ApiError(400, f"Unknown query parameter {name!r}; this URL takes: "
                                        f"{', '.join(allowed)}")
            if name in params:
                raise api.ApiError(400, f"Query parameter {name!r} is given twice")
            params[name] = value
        if self.identity is not None and "profile" in allowed:
            params["profile"] = self.identity["profile"]        # a visit through the tunnel is its login's
        self._home_only(params.get("profile"))
        return params

    def check_write(self):
        """Refuse a POST or PUT that another web page could have sent (see the
        module docstring): 403 for a foreign Origin or Sec-Fetch-Site or no
        X-Deck-Lab header, 415 for a body that isn't sent as JSON. Runs
        before the body is read, so a refused body closes the connection."""
        foreign = api.ApiError(403, "Changes can only be made from Deck Lab's own page (this request came "
                                    "from another site)")
        host = (self.headers.get("Host") or "").strip().lower()
        origins = self.headers.get_all("Origin") or []
        if len(origins) > 1:
            raise foreign
        if origins and (not host or origins[0].strip().lower() not in (f"http://{host}", f"https://{host}")):
            raise foreign           # includes "null" (sandboxed frames, file:// pages)
        sites = self.headers.get_all("Sec-Fetch-Site") or []
        if any(site.strip().lower() not in WRITE_SITES for site in sites):
            raise foreign
        name, value = WRITE_HEADER
        if (self.headers.get_all(name) or []) != [value]:
            raise api.ApiError(403, f"Changes need the header \"{name}: {value}\", which Deck Lab's page sends: "
                                    f"reload the page and try again")
        content_type = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            raise api.ApiError(415, "Send the body as JSON (Content-Type: application/json)")

    def _write_body(self, limit=None):
        """check_write(), then the body (at most limit bytes, api.MAX_EDIT_BODY
        by default), with its "profile" made the login's on the tunnel's listener."""
        self.check_write()
        return self._own_profile(self._read_body(api.MAX_EDIT_BODY if limit is None else limit))

    def _own_profile(self, body):
        """body as given on the home listener (403 when its "profile" is outside the home:
        _home_only). Through the tunnel, a JSON
        object's "profile" (when it has one) is replaced by the login's
        profile id, whatever the visitor sent, so nobody can act as someone
        else; a body that isn't a JSON object is left for api to refuse."""
        if self.identity is None:
            try:
                data = api._load_json(body, "The request")
            except api.ApiError:
                return body             # api refuses it, in its own words, as before
            if isinstance(data, dict):
                self._home_only(data.get("profile"))
            return body
        data = api._load_json(body, "The request")
        if not isinstance(data, dict) or "profile" not in data:
            return body
        data["profile"] = self.identity["profile"]
        return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _read_body(self, limit=None):
        """The request body, at most limit bytes (api.MAX_BODY by default;
        one Content-Length required)."""
        limit = api.MAX_BODY if limit is None else limit
        if self.headers.get("Transfer-Encoding"):
            raise api.ApiError(411, "Send the body with a Content-Length, not chunked")
        lengths = self.headers.get_all("Content-Length") or []
        if not lengths:
            raise api.ApiError(411, "A Content-Length header is required")
        if len(lengths) > 1:
            raise api.ApiError(400, "More than one Content-Length header")
        length = lengths[0].strip()
        if not (length.isascii() and length.isdigit()):      # isdigit() is true for "²" too
            raise api.ApiError(400, "Bad Content-Length")
        if int(length) > limit:
            raise api.ApiError(413, f"The request body is limited to {limit} bytes")
        body = self.rfile.read(int(length))
        if len(body) != int(length):
            self.close_connection = True
            raise api.ApiError(400, "The request body was cut off")
        self._body_read = True
        return body

    def _static(self, parts, query):
        """A file from the allow-list of what is in web/; everything else is 404."""
        files = static_files(self.server.web_dir)
        # An encoded "/" (%2F) inside a part never matches: parts are file names.
        path = None if any("/" in part for part in parts) else files.get("/" + "/".join(parts))
        if path is None:
            raise api.ApiError(404, "Not found")
        self._allow(*GET)
        params = {}
        if query:
            # ?v=2 to bust a cache is fine anywhere; the page itself also takes
            # ?profile=<id>&theme=light|dark, which app.js reads (for screenshots).
            params = self._query(query, PAGE_PARAMS if path == files.get("/") else ("v",))
            if not all(re.fullmatch(r"[\w.-]{1,40}", value) for value in params.values()):
                raise api.ApiError(400, "Bad query parameter value")
        try:
            stat_key, found = static_body(path)
        except OSError:         # removed since the folder was listed
            raise api.ApiError(404, "Not found") from None
        body, suffix = found.body, path.suffix.lower()
        if path == files.get("/") and b"__DECKLAB_WEB_REVISION__" in body:
            # Freeze the page's version in the HTML, not in its later status request.
            revision = build.web_revision() or "unknown"
            body = body.replace(b"__DECKLAB_WEB_REVISION__", revision.encode("ascii"))
            # Changed source gets a new URL, so a phone cannot reuse an old CSS/JS response.
            # Keep the token within the static route's 40-character query limit.
            asset_version = revision[:16].encode("ascii")
            body = re.sub(rb'((?:src|href)="/[^"?]+\.(?:js|css))"',
                          lambda match: match[1] + b"?v=" + asset_version + b'"', body)
            found = StaticBody(body)
        # Kept for good only at the address index.html gave it for exactly these bytes;
        # the page, fonts, an unstamped request and a stale ?v= are asked about each time.
        cache = "no-cache"
        if suffix in STAMPED_SUFFIXES and "v" in params and build.asset_is_current(
                self.server.web_dir or WEB_DIR, "/".join(parts), stat_key, params["v"], STAMP_LENGTH):
            cache = IMMUTABLE
        etag, encoding = found.etag, []
        if suffix in GZIP_SUFFIXES:
            encoding = [("Vary", "Accept-Encoding")]
            if accepts_gzip(self.headers.get("Accept-Encoding")):
                body, etag = found.gzipped(), found.gzip_etag
                encoding.append(("Content-Encoding", "gzip"))
        headers = [("Cache-Control", cache), ("ETag", etag), *encoding]
        content_type = STATIC_TYPES[suffix]
        # A proxy that recompresses an answer sends its ETag on as a weak one (W/"...").
        if etag in [t.strip().removeprefix("W/") for t in self.headers.get("If-None-Match", "").split(",")]:
            return self._send(304, b"", content_type, headers[:3])
        return self._send(200, body, content_type, headers)


_OTHER_USERS = set()               # uids whose script requests were refused (logged once each)


def script_peer_ok(handler):
    """True when the loopback connection handler answers may be a script's: always off Linux;
    on Linux only when the client's socket belongs to this user (home_scope.same_user), so
    another user of the PC, or their service, gets nothing from the header."""
    if not sys.platform.startswith("linux"):
        return True
    try:
        server_end = handler.connection.getsockname()[:2]
    except (AttributeError, OSError):
        return False
    client = tuple(handler.client_address[:2])
    owner = home_scope.peer_uid(client, server_end)
    if owner is not None and owner == os.getuid():
        return True
    if owner not in _OTHER_USERS and len(_OTHER_USERS) < home_scope.REMEMBERED:
        _OTHER_USERS.add(owner)
        log(f"{datetime.now():%Y-%m-%d %H:%M:%S} A script's request (X-Deck-Lab-Script) came from "
            + (f"another user's connection (uid {owner})" if owner is not None else
               "a connection whose owner couldn't be found") + ": it's answered as naming nobody.")
    return False


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # socketserver's default backlog of 5 refuses connections when a cold page
    # load (about 24 stylesheets and 41 scripts) comes from several browsers at
    # once; Windows answers the overflow with a refused connection.
    request_queue_size = 128
    # On Windows SO_REUSEADDR would let a second server take the same port
    # silently; elsewhere it only allows a quick restart.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address, web_dir=None, allowed_hosts=(), access=None, tunnel_hosts=(), home_networks=None,
                 script_secret=None):
        """access: the access.Verifier of the tunnel's listener (every request
        then needs a Cloudflare Access login, for one of tunnel_hosts), or None
        for the home listener (which refuses tunnel_hosts with 421, and
        visits from outside home_networks with 403: home_scope.networks,
        its built-in home networks by default)."""
        from decklab.lib.script_secret import validate
        self.script_secret = validate(script_secret)
        self.web_dir = Path(web_dir or WEB_DIR)
        self.home_networks = tuple(home_networks) if home_networks is not None else home_scope.BUILT_IN
        self.refusals = home_scope.Refusals()
        self.allowed_hosts = tuple(allowed_hosts)
        self.access = access
        self.remote = access is not None
        self.tunnel_hosts = frozenset(h.strip().lower().rstrip(".") for h in tunnel_hosts)
        super().__init__(address, Handler)

    def server_bind(self):
        if os.name == "nt":
            # Even without SO_REUSEADDR, Windows lets a second server bind
            # 127.0.0.1:8642 while the first holds 0.0.0.0:8642 (and the
            # other way round), and both then run. With exclusive use, the
            # second bind fails: WinError 10013 or 10048 (_port_in_use).
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind also looks up the host's full DNS name, which
        # can take seconds on Windows and isn't used.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        # A phone that closes the connection mid-answer isn't an error.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        log(f"Error with a request from {client_address[0]}:\n{traceback.format_exc()}")


def make_server(host, port, web_dir=None, allowed_hosts=(), access=None, tunnel_hosts=(), home_networks=None, script_secret=None):
    """A Server bound to (host, port); port 0 picks a free one (server.server_address).
    With access (an access.Verifier) it's the tunnel's listener (Server). home_networks:
    the home listener's networks (home_scope.networks; its built-in ones by default)."""
    return Server((host, port), web_dir, allowed_hosts, access, tunnel_hosts, home_networks, script_secret)
