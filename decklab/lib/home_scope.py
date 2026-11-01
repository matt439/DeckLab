"""Who the home listener answers: where a visit may come from, and whose a
script's loopback connection is.

The home listener (0.0.0.0:8642) gives whoever reaches it the "Who are you?"
chooser and a home profile's rights with no login, so it answers only
addresses on a home network: loopback, the private IPv4 ranges (10/8,
172.16/12, 192.168/16), link-local (169.254/16, fe80::/10) and IPv6's unique
local addresses (fc00::/7), plus the networks config.json's optional
"home_networks" lists (CIDR strings, such as "100.64.0.0/10" for a VPN).
An IPv4 address mapped into IPv6 (::ffff:192.168.1.20) counts as the IPv4
address. Anything else gets 403 naming nobody (server_http.Handler), and
each refused address is logged once (Refusals). On Windows this sits behind
network-setup.ps1's firewall rule for the local subnet; on Linux, where a
firewall is often off, it's the boundary itself. The tunnel's listener is
on 127.0.0.1 and checks Cloudflare Access logins instead, so this doesn't
apply to it.

A script's request (X-Deck-Lab-Script: 1 from loopback, access.script())
sees and changes everything. On Linux other users of the PC (and their
services) reach 127.0.0.1 too, so there it counts only when the connection
is this user's: same_user() finds the client's socket in /proc/net/tcp (or
tcp6) by its two ends and compares its owner with os.getuid(). Elsewhere
(Windows) the header from loopback is enough, as before.

Tests point PROC at canned files and pass byteorder: /proc/net/tcp writes
each 32-bit word of an address in the machine's byte order.
"""
import ipaddress
import os
import sys
import threading
from pathlib import Path

PROC = Path("/proc")
REMEMBERED = 1000                   # refused addresses remembered (each logged once)
BUILT_IN = tuple(ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10"))
REFUSED = "This address only takes visits from the home network."


def address(text):
    """A client address ("192.168.1.20", "::ffff:192.168.1.20", "fe80::1%eth0") as an
    ip_address, IPv4-mapped ones as IPv4; None when it isn't one."""
    try:
        found = ipaddress.ip_address(str(text).split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(found, "ipv4_mapped", None)
    return mapped or found


def networks(settings, log=None):
    """The networks the home listener answers: BUILT_IN plus config.json's "home_networks".
    An entry that isn't a network (or a list that isn't a list) is left out, with a line to
    log saying so."""
    extra = (settings or {}).get("home_networks")
    if extra is None:
        return BUILT_IN
    if not isinstance(extra, list):
        if log:
            log('config.json\'s "home_networks" isn\'t a list of networks such as "100.64.0.0/10", so it\'s '
                "left out: only the built-in home networks are answered.")
        return BUILT_IN
    found = []
    for entry in extra:
        try:
            found.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError:
            if log:
                log(f'config.json\'s "home_networks" entry {str(entry)[:60]!r} isn\'t a network such as '
                    '"100.64.0.0/10", so it\'s left out.')
    return BUILT_IN + tuple(found)


def allowed(client, nets=BUILT_IN):
    """True when the client address is on one of nets (networks())."""
    found = address(client)
    if found is None:
        return False
    return any(found.version == net.version and found in net for net in nets)


class Refusals:
    """The refused addresses already logged, so each is logged once (up to REMEMBERED)."""

    def __init__(self):
        self._seen, self._lock = set(), threading.Lock()

    def first(self, client):
        """True the first time client is refused."""
        with self._lock:
            if client in self._seen or len(self._seen) >= REMEMBERED:
                return False
            self._seen.add(client)
            return True


def _hex_address(text, byteorder):
    raw = bytes.fromhex(text)
    if byteorder == "little":
        raw = b"".join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return address(ipaddress.ip_address(raw))


def _end(text, byteorder):
    host, _, port = text.partition(":")
    return _hex_address(host, byteorder), int(port, 16)


def peer_uid(client, server, proc=None, byteorder=sys.byteorder):
    """The uid owning the client's end of a TCP connection on this PC, from Linux's
    /proc/net/tcp and tcp6: the row whose local end is client (address, port) and whose
    remote end is server (address, port). None when it isn't found or can't be read."""
    try:
        want = ((address(client[0]), int(client[1])), (address(server[0]), int(server[1])))
    except (TypeError, ValueError, IndexError):
        return None
    for name in ("tcp", "tcp6"):
        try:
            rows = (Path(proc or PROC) / "net" / name).read_text(encoding="ascii", errors="replace").splitlines()
        except OSError:
            continue
        for row in rows[1:]:
            fields = row.split()
            if len(fields) < 8:
                continue
            try:
                if (_end(fields[1], byteorder), _end(fields[2], byteorder)) == want:
                    return int(fields[7])
            except ValueError:
                continue
    return None


def same_user(client, server, proc=None, byteorder=sys.byteorder, uid=None):
    """True when a loopback connection from client (address, port) to server (address,
    port) may count as this user's script: on Linux only when its socket is this user's
    (peer_uid == os.getuid()); elsewhere always."""
    if not sys.platform.startswith("linux"):
        return True
    owner = peer_uid(client, server, proc, byteorder)
    return owner is not None and owner == (os.getuid() if uid is None else uid)
