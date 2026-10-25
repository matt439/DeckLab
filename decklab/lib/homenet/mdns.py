"""The <pc>.local lookup: one multicast DNS question for this PC's own
name, and reading the answers. MDNS_GROUP is defined here, beside
mdns_lookup, the one function that reads it, so a test that sends the
question to a stand-in responder patches homenet.mdns.MDNS_GROUP."""
import random
import socket
import struct
import time

MDNS_GROUP = ("224.0.0.251", 5353)
MDNS_WAIT = 1.0         # seconds to wait for the PC to answer its own mDNS name


# ------------------------------------------------------------ mDNS

def mdns_query(name, query_id=0):
    """An mDNS query for name's IPv4 address (an A record), asking for the
    answer to come straight back (the "QU" bit on the class): Windows' own
    responder answers a query from an ordinary port only then (checked on
    2026-10-01)."""
    question = b"".join(bytes([len(label)]) + label
                        for label in (p.encode("utf-8") for p in name.rstrip(".").split(".")) if label)
    return struct.pack("!6H", query_id, 0, 1, 0, 0, 0) + question + b"\x00" + struct.pack("!2H", 1, 0x8001)


def _read_name(data, offset):
    """(name, offset after it) from a DNS message, following compression
    pointers (at most 32, so a looping message can't hang it)."""
    labels, end, jumps = [], None, 0
    while True:
        if offset >= len(data):
            raise ValueError("name runs past the message")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data) or jumps > 32:
                raise ValueError("bad compression pointer")
            if end is None:
                end = offset + 2
            offset = ((length & 0x3F) << 8) | data[offset + 1]
            jumps += 1
            continue
        if length == 0:
            return ".".join(labels), (end if end is not None else offset + 1)
        labels.append(data[offset + 1:offset + 1 + length].decode("utf-8", "replace"))
        offset += 1 + length


def mdns_answers(data, name):
    """The IPv4 addresses a DNS response gives name (A records in any
    section). [] for a query, another name or a message that can't be read."""
    try:
        _, flags, qd, an, ns, ar = struct.unpack_from("!6H", data, 0)
        if not flags & 0x8000:
            return []
        offset = 12
        for _ in range(qd):
            _, offset = _read_name(data, offset)
            offset += 4
        found, want = [], name.rstrip(".").lower()
        for _ in range(an + ns + ar):
            rname, offset = _read_name(data, offset)
            rtype, _, _, length = struct.unpack_from("!HHIH", data, offset)
            offset += 10
            rdata = data[offset:offset + length]
            offset += length
            if rtype == 1 and length == 4 and rname.rstrip(".").lower() == want:
                address = socket.inet_ntoa(rdata)
                if address not in found:
                    found.append(address)
        return found
    except (ValueError, struct.error, OSError):
        return []


def mdns_lookup(name, interface=None, wait=MDNS_WAIT):
    """Ask the home network's mDNS for name once (from interface's address
    when given) and wait up to wait seconds: {"answered", "addresses",
    "error"}. Windows answers for its own <pc>.local name, which is what
    iPhones and iPads use."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind((interface or "0.0.0.0", 0))
        if interface:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.sendto(mdns_query(name, random.randrange(1, 0x10000)), MDNS_GROUP)
        deadline = time.monotonic() + wait
        while (left := deadline - time.monotonic()) > 0:
            s.settimeout(left)
            try:
                data, _ = s.recvfrom(9000)
            except (TimeoutError, socket.timeout):
                break
            except ConnectionResetError:        # Windows: an ICMP "unreachable" for an earlier send
                continue
            addresses = mdns_answers(data, name)
            if addresses:
                return {"answered": True, "addresses": addresses, "error": None}
        return {"answered": False, "addresses": [], "error": None}
    except OSError as e:
        return {"answered": False, "addresses": [], "error": f"{type(e).__name__}: {e}"}
    finally:
        s.close()
