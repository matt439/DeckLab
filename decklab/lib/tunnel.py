"""The Cloudflare tunnel that lets Deck Lab be opened from outside the home
(https://decklab.example.com), behind Cloudflare Access's login.

The server starts cloudflared itself when "tunnel" in config.json says so,
and only when it listens on its configured port (so a test server on another
port never opens the tunnel). On Windows cloudflared runs with no window
inside the server's Job Object (forge/processes.py), so it stops with the
server, even when the server is killed or crashes. On Linux it runs in a
session of its own: the server ends it when it stops, and when the server is
killed or crashes, systemd's service (homenet install: KillMode=mixed ends
whatever is left in the service's cgroup) does; a server run by hand in a
terminal that's killed outright can leave it running. homenet start, stop
and restart need nothing more. If cloudflared exits on its own, the server starts it again
after RESTART_WAIT seconds. When the PC wakes from sleep (wake-on-request,
lib/keepawake.py) the server restarts it at once (Tunnel.restart_now): its
connections to Cloudflare are stale after a sleep.

    "tunnel": {"config": "~/.cloudflared/config.yml", "hostname": "decklab.example.com"}

"config" is cloudflared's own config file (outside the repo, beside the
tunnel's credentials); "hostname" is what homenet status checks. "cloudflared"
(optional) is the program's path; otherwise it's found on the PATH or where
its installer puts it (install_places: Program Files on Windows; /usr/bin,
/usr/local/bin and the like elsewhere). The hostnames are listed in
"allowed_hosts" too. The credentials file the config names
(credentials-file:) must be there, as a path of this system: a config moved
from Windows still naming C:\\Users\\... is refused loudly
(credentials_problem), as is one whose file is missing.

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
with no login (check_listener).

cloudflared runs with --no-autoupdate, so it never updates itself, and Cloudflare supports only
versions within SUPPORT_DAYS of its newest release (E11-S88). version_check asks the installed
cloudflared for its version (cloudflared_version, parse_version) and judges its age against that
limit (judge_version); homenet status shows the answer and warns, with the platform's upgrade
command (upgrade_hint), and the smoke test notes it, never failing for it. The limit is a reviewed
fact (lib/stats/reviewed.py's "cloudflared-support"): change SUPPORT_POLICY_CHECKED when it's
compared with Cloudflare's page again."""
import http.client
import ipaddress
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import urllib.parse
from datetime import date
from pathlib import Path

from decklab.lib import access

RESTART_WAIT = 30           # seconds before cloudflared is started again after it exits
CHECK_TIMEOUT = 10          # seconds for status's request to the public address
INSTALL_PLACES = (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                  r"C:\Program Files\cloudflared\cloudflared.exe")
# Where Cloudflare's packages (pkg.cloudflare.com), a release binary or snap put it on Linux.
POSIX_INSTALL_PLACES = ("/usr/bin/cloudflared", "/usr/local/bin/cloudflared", "~/.local/bin/cloudflared",
                        "/snap/bin/cloudflared", "/opt/cloudflared/cloudflared")
WINDOWS_HINT = "winget install Cloudflare.cloudflared"
# Cloudflare's support policy for cloudflared, from SUPPORT_SOURCE (the "Updates" part of its downloads
# page), as read on SUPPORT_POLICY_CHECKED: "Cloudflare supports versions of cloudflared that are within
# one year of the most recent release." The newest release isn't known without a fetch, so a version is
# judged against today, which warns at most a release's gap early. Proposed until Matt confirms it.
SUPPORT_DAYS = 365
SUPPORT_POLICY_CHECKED = "2026-11-12"
SUPPORT_SOURCE = "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
VERSION_TIMEOUT = 10        # seconds for `cloudflared --version`
_SPAWN = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
POSIX_HINT = ("install Cloudflare's cloudflared package (pkg.cloudflare.com), or set \"cloudflared\" in "
              "config.json to its path")


def install_places():
    """Where cloudflared's installers put it on this system."""
    if sys.platform == "win32":
        return INSTALL_PLACES
    return tuple(os.path.expanduser(p) for p in POSIX_INSTALL_PLACES)


def install_hint():
    """How to install cloudflared on this system."""
    return WINDOWS_HINT if sys.platform == "win32" else POSIX_HINT


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
            if current is not None and indent != item_indent - 2:
                continue            # a nested list, such as originRequest.access.audTag
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
    candidates = [given] if given else [shutil.which("cloudflared"), *install_places()]
    for path in candidates:
        if path and Path(path).is_file():
            return Path(path)
    return None


# "cloudflared version 2025.8.1 (built 2025-08-21-1528 UTC)", the same on Windows (cloudflared.exe)
# and Linux; a release is numbered by the year and month it was made in.
_VERSION_RE = re.compile(r"\bcloudflared(?:\.exe)?\s+version\s+(\d{4})\.(\d{1,2})\.(\d{1,4})\b"
                         r"(?:[^\n(]*\(built\s+(\d{4}-\d{2}-\d{2}))?", re.I)


def parse_version(text):
    """`cloudflared --version`'s output as {"version": "2025.8.1", "released": date (the first of the
    version's month), "built": "2025-08-21" or None}, or None when it can't be read (a DEV build, an
    error, nothing)."""
    match = _VERSION_RE.search(text or "")
    if not match:
        return None
    year, month, patch = (int(part) for part in match.group(1, 2, 3))
    if not 1 <= month <= 12:
        return None
    return {"version": f"{year}.{month}.{patch}", "released": date(year, month, 1), "built": match.group(4)}


def cloudflared_version(program, run=None, timeout=VERSION_TIMEOUT):
    """Ask cloudflared at program for its version: ("ok", parse_version's dict) or ("unknown", why).
    run is subprocess.run (tests pass their own); a timeout, a failure to start or output that can't
    be read is unknown, never raised."""
    run = run or subprocess.run
    try:
        proc = run([str(program), "--version"], capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=timeout, stdin=subprocess.DEVNULL, **_SPAWN)
    except subprocess.TimeoutExpired:
        return "unknown", f"it didn't answer within {timeout} seconds"
    except OSError as e:
        return "unknown", f"it couldn't be run ({e})"
    found = parse_version(f"{proc.stdout or ''}\n{proc.stderr or ''}")
    if found is None:
        return "unknown", ("its answer couldn't be read" if proc.returncode == 0
                           else f"it exited with code {proc.returncode}")
    return "ok", found


def upgrade_hint(program, platform=None):
    """How to upgrade cloudflared at program on this system, then restart Deck Lab."""
    platform = platform or sys.platform
    path = str(program or "").replace("\\", "/")
    if platform == "win32":
        how = "winget upgrade Cloudflare.cloudflared (or install the newest .msi from Cloudflare's downloads page)"
    elif platform == "darwin":
        how = "brew upgrade cloudflared"
    elif path.startswith("/snap/"):
        how = "sudo snap refresh cloudflared"
    elif path in ("/usr/bin/cloudflared", "/bin/cloudflared"):
        how = ("sudo apt-get update && sudo apt-get install --only-upgrade cloudflared (Cloudflare's package, "
               "pkg.cloudflare.com)")
    else:
        how = (f"replace {path or 'cloudflared'} with the newest release from "
               "github.com/cloudflare/cloudflared/releases")
    return f"Upgrade it: {how}, then python -m decklab.lib.homenet restart."


def judge_version(answer, today, program=None, platform=None):
    """cloudflared_version's answer judged on `today` (a date) against SUPPORT_DAYS: {"state": "current",
    "old" or "unknown", "version", "age_days", "limit_days", "text", "fix" (the upgrade command, for an
    old one, else None)}. A version from a month after today (a wrong clock) is current."""
    kind, found = answer
    where = f" (at {program})" if program else ""
    if kind != "ok":
        return {"state": "unknown", "version": None, "age_days": None, "limit_days": SUPPORT_DAYS,
                "text": f"cloudflared's version is unknown{where}: {found}.", "fix": None}
    age = (today - found["released"]).days
    facts = [f"at {program}"] * bool(program) + [f"built {found['built']}"] * bool(found["built"])
    where = f" ({'; '.join(facts)})" if facts else ""
    if age > SUPPORT_DAYS:
        return {"state": "old", "version": found["version"], "age_days": age, "limit_days": SUPPORT_DAYS,
                "text": (f"cloudflared {found['version']}{where} is from {found['released']:%B %Y}, more "
                         f"than {SUPPORT_DAYS} days ago: Cloudflare supports only versions within a year of its "
                         f"newest release, and this one never updates itself (--no-autoupdate), so the tunnel "
                         f"may stop when Cloudflare drops it."),
                "fix": upgrade_hint(program, platform)}
    return {"state": "current", "version": found["version"], "age_days": max(age, 0), "limit_days": SUPPORT_DAYS,
            "text": f"cloudflared {found['version']}{where}, within Cloudflare's {SUPPORT_DAYS}-day support.",
            "fix": None}


def version_check(settings, today=None, run=None, platform=None):
    """judge_version for the cloudflared config.json's tunnel uses, or None with no tunnel set up or
    no cloudflared found (nothing to show)."""
    if settings_of(settings) is None:
        return None
    program = find_cloudflared(settings)
    if program is None:
        return None
    return judge_version(cloudflared_version(program, run), today or date.today(), program, platform)


def top_level(text, key):
    """A key's value at the left margin of a cloudflared config ("credentials-file:
    /home/p/.cloudflared/x.json"), unquoted, or None. The same simple YAML as ingress_rules."""
    for raw in text.splitlines():
        if raw[:1].isspace() or raw.lstrip().startswith("#"):
            continue
        name, colon, value = raw.partition(":")
        if colon and name.strip() == key:
            value = value.split(" #", 1)[0].strip().strip("'\"")
            return value or None
    return None


def credentials_problem(settings, is_file=None):
    """Why the credentials file cloudflared's config names (credentials-file:) won't do, or
    None: fine, not named (cloudflared then looks beside its config) or the config can't be
    read (start and status say so on their own)."""
    setup = settings_of(settings)
    if setup is None:
        return None
    try:
        text = setup["config"].read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    named = top_level(text, "credentials-file")
    if not named:
        return None
    if sys.platform != "win32" and re.match(r"^[A-Za-z]:[\\/]|^\\\\", named):
        return (f"{setup['config']} names the tunnel's credentials file as {named}, a Windows path "
                "(the config came from a Windows PC)")
    path = Path(os.path.expanduser(named))
    if not (is_file or Path.is_file)(path):
        return f"the tunnel's credentials file {path} (credentials-file in {setup['config']}) isn't there"
    return None


class Tunnel:
    """cloudflared running for the server, started again if it exits, until stop()."""

    def __init__(self, program, config_file, log):
        self.program, self.config_file, self.log = program, config_file, log
        self.proc = None
        self._stopping = threading.Event()
        self._kick = threading.Event()      # set by restart_now (and stop): no RESTART_WAIT
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
                if not self._kick.is_set():
                    self.log(f"Tunnel: cloudflared exited with code {code}.")
            self._kick.wait(RESTART_WAIT)
            self._kick.clear()
            if self._stopping.is_set():
                return
            self.log("Tunnel: starting cloudflared again.")

    def restart_now(self):
        """End the running cloudflared so the loop starts it again at once, without
        RESTART_WAIT (after the PC wakes from sleep, its connections are stale)."""
        if self._stopping.is_set():
            return
        self.log("Tunnel: restarting cloudflared now (the PC woke from sleep).")
        self._kick.set()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            from decklab.lib.forge import processes
            processes.kill_process(proc)

    def stop(self):
        self._stopping.set()
        self._kick.set()
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
        log(f"Tunnel: not started: cloudflared isn't installed ({install_hint()}).")
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
    credentials = credentials_problem(settings)
    if credentials:
        log(f"Tunnel: NOT STARTED: {credentials}.")
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
