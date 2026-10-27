"""The Cloudflare tunnel that lets Deck Lab be opened from outside the home
(https://decklab.example.com), behind Cloudflare Access's login.

The server starts cloudflared itself when "tunnel" in config.json says so,
and only when it listens on its configured port (so a test server on another
port never opens the tunnel). cloudflared runs with no window inside the
server's Job Object (forge/processes.py), so it stops with the server, even
when the server is killed or crashes; homenet start, stop and restart need
nothing more. If cloudflared exits on its own, the server starts it again
after RESTART_WAIT seconds.

    "tunnel": {"config": "~/.cloudflared/config.yml", "hostname": "decklab.example.com"}

"config" is cloudflared's own config file (outside the repo, beside the
tunnel's credentials); "hostname" is what homenet status checks. "cloudflared"
(optional) is the program's path; otherwise it's found on the PATH or where
its installer puts it. The hostnames are listed in "allowed_hosts" too.

The tunnel needs "access" in config.json as well (lib/access.py): the server
then opens a second listener on 127.0.0.1:<access port> for the tunnel only,
which checks each visit's Cloudflare Access login itself and gives it the
profile its email belongs to. The home listener refuses visits that came
through Cloudflare (421). So the tunnel is started only when that listener is
up, and only when cloudflared's config sends the tunnel's hostnames there
(ingress_problems): a config still sending them to the home port is refused
loudly in the log, rather than leaving every outside visit refused.

The login itself (who may get in) is Cloudflare Access's, set in Cloudflare's
dashboard; nothing in this repo can open the page to the internet without it.
homenet status checks that the address answers with Access's login and not
with Deck Lab (check_public), that cloudflared's config sends it to the
tunnel's listener (ingress_problems), and that the listener refuses a visit
with no login (check_listener)."""
import http.client
import ipaddress
import os
import re
import shutil
import socket
import ssl
import threading
import urllib.parse
from pathlib import Path

from decklab.lib import access

RESTART_WAIT = 30           # seconds before cloudflared is started again after it exits
CHECK_TIMEOUT = 10          # seconds for status's request to the public address
INSTALL_PLACES = (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                  r"C:\Program Files\cloudflared\cloudflared.exe")


def settings_of(settings):
    """config.json's "tunnel" as a dict with "config" (a Path) and "hostname",
    or None when there's no tunnel set up."""
    tunnel = (settings or {}).get("tunnel")
    if not isinstance(tunnel, dict) or not tunnel.get("config"):
        return None
    return {"config": Path(os.path.expanduser(str(tunnel["config"]))),
            "hostname": str(tunnel.get("hostname") or "").strip().lower()}


def public_address(settings):
    """The address the tunnel opens Deck Lab at ("https://decklab.example.com"),
    for links that must open from anywhere, such as a deck box label's QR code
    (E8-S21); None with no tunnel or no usable hostname."""
    host = (settings_of(settings) or {}).get("hostname")
    return f"https://{host}" if host and re.fullmatch(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?", host) else None


def usual_server(port, configured_port):
    """True for the server on its configured port, the one the tunnel (and its
    listener) is for; False for a test's server or one on another port."""
    if os.environ.get("DECKLAB_STATE_FILE"):        # a test's server (control's docstring)
        return False
    return port == configured_port


_LOCAL_SERVICE_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])(?::(\d+))?/?", re.I)


def ingress_rules(text):
    """The rules of a cloudflared config's "ingress:" list, as dicts with
    "hostname" and "service" where given. Only the simple YAML cloudflared's
    own examples use is read: "ingress:" at the left margin, then "- key: value"
    items, each key on its own line."""
    rules, current, inside, item_indent = [], None, False, 0
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0 and not stripped.startswith("- "):
            inside = stripped.split("#", 1)[0].strip() == "ingress:"
            current = None
            continue
        if not inside:
            continue
        if stripped.startswith("- "):
            current = {}
            rules.append(current)
            stripped = stripped[2:].strip()
            item_indent = indent + 2
        elif current is None or indent > item_indent:
            continue                # a nested setting (originRequest and the like)
        key, colon, value = stripped.partition(":")
        if colon and key.strip() in ("hostname", "service"):
            value = value.split(" #", 1)[0].strip().strip("'\"")
            current[key.strip()] = value
    return rules


def _local_port(service):
    """The port of a service on this PC by its loopback name (http://localhost:8644
    and the like), else None."""
    match = _LOCAL_SERVICE_RE.fullmatch((service or "").strip())
    if not match:
        return None
    return int(match.group(1)) if match.group(1) else (443 if service.lower().startswith("https") else 80)


def _service_target(service):
    """(host, port) of an http or https service address, host lowercase and
    without brackets; None for anything else (http_status:404, a unix socket)."""
    try:
        parts = urllib.parse.urlsplit((service or "").strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    return parts.hostname.lower().rstrip("."), port


def _address(text):
    """text as an ipaddress object (an IPv6 zone such as %eth0 dropped), else None."""
    try:
        return ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return None


def this_pc():
    """(names, addresses) this PC answers to: its host name and full name
    (lowercase), and the IPv4 and IPv6 addresses they resolve to. Tests patch it."""
    names, addresses = set(), set()
    for name in (socket.gethostname(), socket.getfqdn()):
        if not name:
            continue
        names.add(name.lower().rstrip("."))
        try:
            for info in socket.getaddrinfo(name, None):
                found = _address(str(info[4][0]))
                if found is not None:
                    addresses.add(found)
        except (OSError, UnicodeError):
            pass
    return names, addresses


def _resolve(host):
    """The addresses host resolves to (an empty set when it doesn't). Tests patch it."""
    try:
        return {a for a in (_address(str(info[4][0])) for info in socket.getaddrinfo(host, None)) if a is not None}
    except (OSError, UnicodeError):
        return set()


def _on_this_pc(host, pc):
    """True when host names this PC: a localhost name, a loopback or
    unspecified address (127.x, ::1, 0.0.0.0, ::), its host name, or a name or
    address that is (or resolves to) one of its own addresses. pc: this_pc()."""
    names, addresses = pc
    if host == "localhost" or host.endswith(".localhost") or host in names:
        return True
    literal = _address(host)
    found = {literal} if literal is not None else _resolve(host)
    for address in found:
        mapped = getattr(address, "ipv4_mapped", None)
        if address.is_loopback or address.is_unspecified or address in addresses \
                or (mapped is not None and (mapped.is_loopback or mapped in addresses)):
            return True
    return False


def ingress_problems(settings, home_port=None):
    """What's wrong with where cloudflared's config sends the tunnel's
    hostnames, as plain sentences ([] when nothing): with "access" set, every
    rule for one of them must go to http://127.0.0.1:<access port> (or
    localhost), and no rule may go to the home port on any address of this
    PC (localhost names, 127.x, ::1, its host name and its own IPv4 and IPv6
    addresses: _on_this_pc). None when there's no tunnel or no "access"
    (nothing to check); a config that can't be read or an "access" that's
    wrong is a problem."""
    setup = settings_of(settings)
    if setup is None or (settings or {}).get("access") is None:
        return None
    try:
        port = access.settings_of(settings)["port"]
    except ValueError as e:
        return [str(e)]
    home_port = (settings or {}).get("port", 8642) if home_port is None else home_port
    try:
        rules = ingress_rules(setup["config"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        return [f"cloudflared's config {setup['config']} can't be read ({e})"]
    hosts = access.tunnel_hosts(settings)
    want = f"http://127.0.0.1:{port}"
    problems = []
    pc = None
    for rule in rules:
        hostname = (rule.get("hostname") or "").lower().rstrip(".")
        target = _local_port(rule.get("service"))
        named = f"{hostname}" if hostname else "the catch-all rule"
        service = _service_target(rule.get("service"))
        home = False
        if service is not None and service[1] == home_port:
            pc = this_pc() if pc is None else pc
            home = _on_this_pc(service[0], pc)
        if home:
            problems.append(f"{named} goes to {rule.get('service')}, Deck Lab's home listener (port {home_port}), "
                            f"which refuses tunnel visits: make it {want}")
        elif hostname in hosts and target != port:
            problems.append(f"{named} goes to {rule.get('service') or 'nothing'}, not {want}")
    routed = {(rule.get("hostname") or "").lower().rstrip(".") for rule in rules
              if _local_port(rule.get("service")) == port}
    catch_all = any(not rule.get("hostname") for rule in rules if _local_port(rule.get("service")) == port)
    missing = sorted(h for h in hosts if h not in routed and not catch_all)
    if missing and not problems:
        problems.append(f"no rule sends {', '.join(missing)} to {want}")
    return problems


def find_cloudflared(settings=None):
    """cloudflared's path, or None when it isn't installed."""
    given = (settings or {}).get("cloudflared")
    candidates = [given] if given else [shutil.which("cloudflared"), *INSTALL_PLACES]
    for path in candidates:
        if path and Path(path).is_file():
            return Path(path)
    return None


class Tunnel:
    """cloudflared running for the server, started again if it exits, until stop()."""

    def __init__(self, program, config_file, log):
        self.program, self.config_file, self.log = program, config_file, log
        self.proc = None
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tunnel", daemon=True)

    def start(self):
        self._thread.start()
        return self

    def _run(self):
        from decklab.lib.forge import processes
        argv = [str(self.program), "tunnel", "--config", str(self.config_file), "--no-autoupdate", "run"]
        while not self._stopping.is_set():
            try:
                self.proc = processes.start_process(argv)
            except OSError as e:
                self.log(f"Tunnel: cloudflared couldn't start ({e}).")
            else:
                for text in self.proc.stdout:
                    text = text.rstrip()
                    if text:
                        self.log(f"Tunnel: {text}")
                code = self.proc.wait()
                processes._end_process(self.proc)
                if self._stopping.is_set():
                    return
                self.log(f"Tunnel: cloudflared exited with code {code}.")
            if self._stopping.wait(RESTART_WAIT):
                return
            self.log("Tunnel: starting cloudflared again.")

    def stop(self):
        self._stopping.set()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            from decklab.lib.forge import processes
            processes.kill_process(proc)
        self._thread.join(5)


def start(settings, port, configured_port, log, listener_port=None):
    """Start the tunnel for a server on port, when config.json sets one up and
    port is the configured one; the Tunnel, or None (with a log line saying
    why, when one is set up but can't start). listener_port is the port of the
    server's listener for the tunnel (None when it has none): without one, or
    when cloudflared's config doesn't send the hostnames there, the tunnel
    isn't started (ingress_problems)."""
    tunnel = settings_of(settings)
    if tunnel is None:
        return None
    if not usual_server(port, configured_port):     # a test's server, or one on another port
        return None
    if not tunnel["config"].is_file():
        log(f"Tunnel: not started: its config file {tunnel['config']} isn't there.")
        return None
    program = find_cloudflared(settings)
    if program is None:
        log("Tunnel: not started: cloudflared isn't installed (winget install Cloudflare.cloudflared).")
        return None
    if listener_port is None:
        log('Tunnel: NOT STARTED: Deck Lab has no listener for the tunnel ("access" in config.json is missing '
            'or wrong, or its port is taken; the lines above say which), and the home listener refuses '
            'tunnel visits.')
        return None
    problems = ingress_problems(settings, port)
    if problems:
        log(f"Tunnel: NOT STARTED: {tunnel['config']} doesn't send the tunnel to Deck Lab's tunnel listener "
            f"(127.0.0.1:{listener_port}): {'; '.join(problems)}.")
        return None
    log(f"Tunnel: starting cloudflared for https://{tunnel['hostname'] or '(no hostname set)'}/")
    return Tunnel(program, tunnel["config"], log).start()


def check_public(hostname, timeout=CHECK_TIMEOUT):
    """Ask https://hostname/api/status from here, without following redirects.
    ("login", text) when Cloudflare Access answers with its login, ("open", text)
    when Deck Lab itself answers (the login is missing), ("down", text) when the
    tunnel isn't connected, ("error", text) otherwise."""
    try:
        conn = http.client.HTTPSConnection(hostname, timeout=timeout, context=ssl.create_default_context())
        try:
            conn.request("GET", "/api/status", headers={"User-Agent": "DeckLab-status"})
            response = conn.getresponse()
            location = response.getheader("Location") or ""
            body = response.read(4096).decode("utf-8", "replace")
        finally:
            conn.close()
    except (OSError, http.client.HTTPException) as e:
        return "error", f"https://{hostname} couldn't be reached: {e}"
    status = response.status
    if status in (301, 302, 303, 307, 308) and "cloudflareaccess.com" in location:
        return "login", f"https://{hostname} answers with Cloudflare Access's login"
    if status == 200 and '"ready"' in body:
        return "open", f"https://{hostname} answers with Deck Lab itself, with no login"
    if status in (502, 503, 530) or "1033" in body:
        return "down", f"https://{hostname} answers {status}: the tunnel isn't connected (is Deck Lab running?)"
    return "error", f"https://{hostname} answers {status}" + (f", redirecting to {location}" if location else "")


def check_listener(port, hostname, timeout=CHECK_TIMEOUT):
    """Ask the tunnel's listener (127.0.0.1:port) for /api/status as the
    tunnel would but with no login. ("refuses", text) for its 403,
    ("open", text) when it answers without a login, ("closed", text) when
    nothing listens, ("error", text) otherwise."""
    where = f"The tunnel's listener (127.0.0.1:{port})"
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            try:
                conn.connect()
            except TimeoutError:        # Windows retries a refused connection until the timeout
                raise ConnectionRefusedError from None
            conn.request("GET", "/api/status", headers={"Host": hostname or "localhost",
                                                        "User-Agent": "DeckLab-status"})
            response = conn.getresponse()
            response.read(4096)
        finally:
            conn.close()
    except ConnectionRefusedError:
        return "closed", f"{where} isn't listening"
    except (OSError, http.client.HTTPException) as e:
        return "error", f"{where} couldn't be asked: {e}"
    if response.status == 403:
        return "refuses", f"{where} refuses visits without a Cloudflare Access login"
    if response.status == 200:
        return "open", f"{where} answers without a Cloudflare Access login"
    return "error", f"{where} answers {response.status}"
