"""Fetch an accessory's picture from a link the user pasted, safely.

The Accessories page's "Find picture" sends a shop's product page or a
picture's own address here. Deck Lab then downloads at most two things from
the internet: the link itself and, when that's a web page, the picture the
page names for sharing (og:image and friends). Nothing is written to the repo:
the picture is staged in decklab/data/accessories/staged/ until a save moves
it into magic/accessories/images/.

Usage:

    from decklab.lib import accessory_fetch
    found = accessory_fetch.fetch("https://shop.example/p/1")
    found["token"], found["ext"]        # the staged picture: STAGED/<token>.<ext>
    found["width"], found["height"]     # its size in pixels
    found["final_url"]                  # the link after redirects
    found["image_source"]               # where the picture was downloaded from
    found["guess"]                      # {name, brand, kind, quantity}, all editable
    accessory_fetch.staged_file(token)  # the staged Path, or None when gone or stale

Safety rules (the page runs on a home network, so a link must never reach it):
- only http and https, no user:password@, port 80, 443 or none, at most 500
  characters;
- the host is resolved first and every address must be a global internet
  address: private, loopback, link-local, multicast, reserved and unspecified
  ones are refused. Every redirect (at most 5) is checked the same way, and
  ftp is never followed;
- no proxies (an environment proxy would hide where the request goes);
- 10 s per socket operation and 20 s in all: a timer shuts every socket the
  fetch opened when the 20 s are up, so a server that trickles its headers,
  redirects or body a byte at a time can't hold the request longer; pages up
  to 2 MB and pictures
  up to 4 MB, refused early on a larger Content-Length and cut off at the cap
  otherwise;
- only JPEG, PNG and WebP are kept, recognised by their first bytes (never by
  the name or Content-Type), 16 to 6000 pixels a side. GIF, AVIF, SVG and
  HTML are refused.

Accepted risk: urllib resolves the host again when it connects, so a DNS
server that answers differently the second time (DNS rebinding) could still
point a request at the home network. For a page on a home network that only
its own people use, that window is accepted rather than pinning addresses.

This doesn't use cards._open_url: that one spaces requests for Scryfall.
"""
import http.client
import ipaddress
import json
import os
import re
import secrets
import socket
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from decklab.lib import config
from decklab.lib.api.common import ApiError

USER_AGENT = config.USER_AGENT + " product image fetch"
MAX_URL = 500                       # characters in a pasted link
MAX_REDIRECTS = 5                   # hops followed for one download
SOCKET_TIMEOUT = 10                 # seconds for each connect or read
TOTAL_TIMEOUT = 20                  # seconds for the whole fetch, both downloads
MAX_PAGE = 2 * 1024 * 1024          # bytes of a product page
MAX_IMAGE = 4 * 1024 * 1024         # bytes of a picture
MIN_SIDE, MAX_SIDE = 16, 6000       # pixels on each side of a picture
CHUNK = 64 * 1024

STAGED = config.DATA / "accessories" / "staged"
STAGE_MAX_AGE = 3600                # seconds a staged picture stays usable
EXTS = ("jpg", "png", "webp")
TOKEN_RE = re.compile(r"[0-9a-f]{32}")
STAGED_NAME_RE = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|webp)")

PAGE_ACCEPT = "text/html,application/xhtml+xml,image/webp,image/png,image/jpeg;q=0.9,*/*;q=0.5"
IMAGE_ACCEPT = "image/webp,image/png,image/jpeg;q=0.9,*/*;q=0.5"

BLOCKED = "That shop didn't let Deck Lab download the page. Open the picture itself, copy its address, and paste that, or save without a picture."
HOME_NETWORK = "Deck Lab only fetches from the internet, not your home network."
BAD_LINK = "Paste a link that starts with http:// or https://."
TOO_SLOW = "That shop took too long to answer. Try again, or paste the picture's own address."
NO_PICTURE = "Deck Lab couldn't find a picture on that page. Open the picture itself, copy its address, and paste that, or save without a picture."
WRONG_TYPE = "Deck Lab keeps only JPEG, PNG and WebP pictures, and that one is {what}. Try a different picture, or save without one."

# Words in a page's title or link that say what kind of accessory it is,
# checked in this order (a deck box's title may mention the sleeves it holds).
KIND_WORDS = (("deck_box", ("deck box", "deckbox", "deck case", "boulder")),
              ("playmat", ("playmat", "play mat", "playmats")),
              ("sleeves", ("sleeve",)))
QUANTITY_RE = re.compile(r"\b(\d{2,3})[\s-]*(?:ct|count|pack|sleeves)\b", re.IGNORECASE)
TITLE_SEPARATORS = (" | ", " - ", " – ", " — ", " : ", " :: ")
MAX_GUESS_NAME = 80
MAX_GUESS_BRAND = 40
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _now():
    return time.monotonic()


# --- Links and addresses -----------------------------------------------------

def check_url(url):
    """Refuse a link Deck Lab won't fetch (ApiError 400); return its host."""
    if not isinstance(url, str) or not url.strip():
        raise ApiError(400, BAD_LINK)
    if len(url) > MAX_URL:
        raise ApiError(400, f"That link is longer than {MAX_URL} characters. Paste a shorter one, such as the picture's own address.")
    if _CONTROL_RE.search(url) or " " in url:
        raise ApiError(400, BAD_LINK)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ApiError(400, BAD_LINK) from None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ApiError(400, BAD_LINK)
    if "@" in parts.netloc:
        raise ApiError(400, "Paste the link without a user name or password in it.")
    if port not in (None, 80, 443):
        raise ApiError(400, "Deck Lab only fetches from ordinary web addresses (no port number).")
    check_host(parts.hostname, port or (443 if parts.scheme.lower() == "https" else 80))
    return parts.hostname


def _public(address):
    """True when address (a string from getaddrinfo) is a global internet address."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                                 or ip.is_reserved or ip.is_unspecified)


def check_host(host, port):
    """Resolve host and refuse it unless every address is on the internet."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise ApiError(400, "Deck Lab couldn't find that website. Check the link.") from None
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(_public(a) for a in addresses):
        raise ApiError(400, HOME_NETWORK)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow at most MAX_REDIRECTS hops, re-checking scheme and host on each."""
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            check_url(newurl)
        except ApiError:
            fp.close()
            raise
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _Watch:
    """The fetch's deadline, enforced on its sockets: once it passes, a timer
    shuts every socket opened so far (and any opened later) so whatever read
    is blocked on one ends at once, whether it's the connect, the headers, a
    redirect or the body."""

    def __init__(self, deadline):
        self.deadline = deadline
        self.expired = False
        self._sockets = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(0.0, deadline - _now()), self.expire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self):
        return self.deadline - _now()

    def socket_timeout(self):
        """SOCKET_TIMEOUT, or less when the deadline is nearer; TOO_SLOW once it's past."""
        left = self.remaining()
        if self.expired or left <= 0:
            raise ApiError(502, TOO_SLOW)
        return min(SOCKET_TIMEOUT, left)

    def add(self, sock):
        with self._lock:
            self._sockets.append(sock)
            expired = self.expired
        if expired:
            _shut(sock)
        return sock

    def expire(self):
        with self._lock:
            self.expired = True
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            _shut(sock)

    def stop(self):
        self._timer.cancel()


def _shut(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _watched(base, watch):
    """An http.client connection class whose sockets the watch can shut."""
    class Connection(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            create = self._create_connection
            self._create_connection = lambda *a, **k: watch.add(create(*a, **k))

        def connect(self):
            self.timeout = watch.socket_timeout()
            super().connect()
    return Connection


class _WatchedHttp(urllib.request.HTTPHandler):
    def __init__(self, watch):
        super().__init__()
        self.watch = watch

    def http_open(self, req):
        return self.do_open(_watched(http.client.HTTPConnection, self.watch), req)


class _WatchedHttps(urllib.request.HTTPSHandler):
    def __init__(self, watch):
        super().__init__()
        self.watch = watch

    def https_open(self, req):
        return self.do_open(_watched(http.client.HTTPSConnection, self.watch), req, context=self._context)


def _opener(watch=None):
    handlers = [urllib.request.ProxyHandler({}), SafeRedirect()]
    if watch is not None:
        handlers += [_WatchedHttp(watch), _WatchedHttps(watch)]
    return urllib.request.build_opener(*handlers)


# --- Downloading -------------------------------------------------------------

def _download(url, accept, deadline, image_only):
    """Download url (already checked): (body, content_type, final_url).
    Everything, from connecting to the last byte, ends by deadline."""
    watch = _Watch(deadline)
    try:
        return _download_watched(url, accept, watch, image_only)
    except ApiError as error:
        if watch.expired and error.message != TOO_SLOW:
            raise ApiError(502, TOO_SLOW) from None
        raise
    finally:
        watch.stop()


def _download_watched(url, accept, watch, image_only):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        response = _opener(watch).open(request, timeout=watch.socket_timeout())
    except ApiError:
        raise
    except urllib.error.HTTPError as error:
        error.close()
        raise ApiError(502, TOO_SLOW if watch.expired else BLOCKED) from None
    except (TimeoutError, socket.timeout):
        raise ApiError(502, TOO_SLOW) from None
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        raise ApiError(502, TOO_SLOW if watch.expired else BLOCKED) from None
    deadline = watch.deadline
    with response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        cap = MAX_IMAGE if image_only or content_type.startswith("image/") else MAX_PAGE
        declared = response.headers.get("Content-Length")
        try:
            declared = int(declared) if declared is not None else None
        except ValueError:
            declared = None
        if declared is not None and declared > cap:
            raise ApiError(502, _too_big(cap))
        body = _read(response, cap, deadline)
        if watch.expired:               # a shut socket reads as the end of the body
            raise ApiError(502, TOO_SLOW)
        return body, content_type, response.geturl() or url


def _read(response, cap, deadline):
    """Read at most cap + 1 bytes, refusing past cap or past the deadline.
    read1 returns what one receive brings, so the deadline is checked between
    receives rather than between whole chunks (a plain read waits for CHUNK
    bytes, however slowly they come)."""
    chunks, size = [], 0
    read = getattr(response, "read1", None) or response.read
    while True:
        if _now() > deadline:
            raise ApiError(502, TOO_SLOW)
        try:
            chunk = read(min(CHUNK, cap + 1 - size))
        except (TimeoutError, socket.timeout):
            raise ApiError(502, TOO_SLOW) from None
        except (OSError, http.client.HTTPException):
            raise ApiError(502, BLOCKED) from None
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > cap:
            raise ApiError(502, _too_big(cap))


def _too_big(cap):
    return f"That download is larger than {cap // (1024 * 1024)} MB. Paste the picture's own address, or save without a picture."


# --- Pictures ----------------------------------------------------------------

def sniff(data):
    """The extension for data's first bytes: "jpg", "png", "webp" or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _what(data, content_type):
    """A word for a refused download, for WRONG_TYPE."""
    if data[:4] == b"GIF8":
        return "a GIF"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "an AVIF"
    head = data[:256].lstrip().lower()
    if "svg" in content_type or head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048].lower()):
        return "an SVG"
    if _looks_like_html(data, content_type):
        return "a web page"
    return "not a picture"


def _looks_like_html(data, content_type):
    if "html" in content_type:
        return True
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html")) or b"<head" in head


def dimensions(data, ext):
    """(width, height) from a JPEG, PNG or WebP header, or None."""
    try:
        if ext == "png":
            return _png_size(data)
        if ext == "jpg":
            return _jpeg_size(data)
        if ext == "webp":
            return _webp_size(data)
    except (struct.error, IndexError):
        return None
    return None


def _png_size(data):
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_size(data):
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            return None
        while i < len(data) and data[i] == 0xFF:      # fill bytes
            i += 1
        marker = data[i]
        i += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # no length
            continue
        if marker in (0xD9, 0xDA):                    # end, or scan data before any frame
            return None
        length = struct.unpack(">H", data[i:i + 2])[0]
        if marker in _SOF:
            height, width = struct.unpack(">HH", data[i + 3:i + 7])
            return width, height
        if length < 2:
            return None
        i += length
    return None


def _webp_size(data):
    chunk = data[12:16]
    if chunk == b"VP8 ":
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        if data[20] != 0x2F:
            return None
        bits = struct.unpack("<I", data[21:25])[0]
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None


def check_image(data, content_type=""):
    """(ext, width, height) for a picture Deck Lab keeps; ApiError 502 otherwise."""
    ext = sniff(data)
    if ext is None:
        raise ApiError(502, WRONG_TYPE.format(what=_what(data, content_type)))
    size = dimensions(data, ext)
    if size is None:
        raise ApiError(502, "Deck Lab couldn't read that picture's size; it may be damaged. Try a different picture, or save without one.")
    width, height = size
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        raise ApiError(502, f"That picture is {width} by {height} pixels; Deck Lab keeps pictures {MIN_SIDE} to {MAX_SIDE} pixels a side.")
    return ext, width, height


# --- Product pages -----------------------------------------------------------

IMAGE_META = ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src")


class _PageParser(HTMLParser):
    """Collects the sharing picture, title, site name and brand of a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}              # first content for each lowercased property/name
        self.image_src = None       # <link rel="image_src">
        self.title = ""
        self.ld_image = None        # the first JSON-LD image
        self.ld_brand = None
        self._in_title = False
        self._ld = None             # text of the JSON-LD script being read

    def handle_starttag(self, tag, attrs):
        attrs = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").strip().lower()
            content = attrs.get("content", "").strip()
            if key and content:
                self.meta.setdefault(key, content)
        elif tag == "link":
            rels = attrs.get("rel", "").lower().split()
            if "image_src" in rels and attrs.get("href") and self.image_src is None:
                self.image_src = attrs["href"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self._ld = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._ld is not None:
            text, self._ld = "".join(self._ld), None
            try:
                data = json.loads(text)
            except ValueError:
                return
            if self.ld_image is None:
                self.ld_image = _ld_find(data, "image", _ld_image)
            if self.ld_brand is None:
                self.ld_brand = _ld_find(data, "brand", _ld_name)

    def handle_data(self, data):
        if self._ld is not None:
            self._ld.append(data)
        elif self._in_title:
            self.title += data

    def picture(self):
        """The first picture the page names, in the order the plan gives."""
        for key in IMAGE_META:
            if self.meta.get(key):
                return self.meta[key]
        return self.image_src or self.ld_image


def _ld_find(data, key, value_of, depth=0):
    """The first usable value of key anywhere in a JSON-LD document."""
    if depth > 8:
        return None
    if isinstance(data, dict):
        if key in data:
            value = value_of(data[key])
            if value:
                return value
        items = data.values()
    elif isinstance(data, list):
        items = data
    else:
        return None
    for item in items:
        value = _ld_find(item, key, value_of, depth + 1)
        if value:
            return value
    return None


def _ld_image(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            found = _ld_image(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        return _ld_image(value.get("url") or value.get("contentUrl"))
    return None


def _ld_name(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        return _ld_name(value.get("name"))
    if isinstance(value, list) and value:
        return _ld_name(value[0])
    return None


def _charset(content_type):
    match = re.search(r"charset=[\"']?([\w.:-]+)", content_type)
    return match.group(1) if match else "utf-8"


def parse_page(body, content_type=""):
    """A parsed page from its bytes (page text that can't be read is replaced)."""
    try:
        text = body.decode(_charset(content_type), errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    parser = _PageParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:       # HTMLParser is lenient; a page it still chokes on just gives fewer guesses
        pass
    return parser


# --- Guesses -----------------------------------------------------------------

def _clean(text, limit):
    text = " ".join(_CONTROL_RE.sub(" ", text or "").split())
    return text[:limit].rstrip()


def _strip_affix(title, affix):
    """title without affix and its separator at either end."""
    low, affix_low = title.lower(), affix.lower()
    for sep in TITLE_SEPARATORS:
        if low.endswith(sep + affix_low):
            return title[:-len(sep + affix)]
        if low.startswith(affix_low + sep):
            return title[len(affix + sep):]
    return title


def guess(page, url=""):
    """Editable guesses from a parsed page: {name, brand, kind, quantity}."""
    brand = _clean(page.meta.get("product:brand") or page.meta.get("og:brand") or page.ld_brand or "", MAX_GUESS_BRAND)
    title = _clean(page.meta.get("og:title") or page.meta.get("twitter:title") or page.title, 300)
    site = _clean(page.meta.get("og:site_name", ""), 300)
    name = title
    if site:
        name = _strip_affix(name, site)
    elif " | " in name:
        name = name.split(" | ", 1)[0]
    if brand and name.lower().startswith(brand.lower() + " "):
        name = name[len(brand):].lstrip(" -–—:|")
    name = _clean(name, MAX_GUESS_NAME)
    return {"name": name, "brand": brand, **_kind_quantity(title + " " + url)}


def _kind_quantity(text):
    low = text.lower()
    kind = next((k for k, words in KIND_WORDS if any(w in low for w in words)), "")
    quantity = None
    if kind == "sleeves":
        match = QUANTITY_RE.search(text)
        if match:
            quantity = int(match.group(1))
    return {"kind": kind, "quantity": quantity}


# --- Staging -----------------------------------------------------------------

def prune_staged(max_age=STAGE_MAX_AGE):
    """Delete staged pictures (and leftover temp files) older than max_age."""
    try:
        entries = list(STAGED.iterdir())
    except OSError:
        return
    cutoff = time.time() - max_age
    for path in entries:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def stage(data, ext):
    """Write a checked picture to STAGED; return its token (32 hex digits)."""
    if ext not in EXTS:
        raise ValueError(f"not a picture extension: {ext!r}")
    STAGED.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    fd, tmp = tempfile.mkstemp(dir=STAGED, prefix=".", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(tmp, STAGED / f"{token}.{ext}")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return token


def staged_file(token, max_age=STAGE_MAX_AGE):
    """The staged picture for token, or None when the token is malformed,
    the picture is gone, or it's older than max_age."""
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        return None
    for ext in EXTS:
        path = STAGED / f"{token}.{ext}"
        try:
            if path.is_file() and not path.is_symlink() and time.time() - path.stat().st_mtime < max_age:
                return path
        except OSError:
            return None
    return None


# --- The whole fetch ---------------------------------------------------------

def fetch(url):
    """Download the picture behind url (a picture, or a page naming one),
    stage it and return {token, bytes, ext, width, height, final_url,
    image_source, guess}. Raises ApiError with wording for the page."""
    prune_staged()
    url = url.strip() if isinstance(url, str) else url
    check_url(url)
    deadline = _now() + TOTAL_TIMEOUT
    body, content_type, final_url = _download(url, PAGE_ACCEPT, deadline, image_only=False)
    if sniff(body):
        data, image_source, picture_type = body, final_url, content_type
        found = {"name": "", "brand": "", **_kind_quantity(final_url)}
    elif _looks_like_html(body, content_type):
        page = parse_page(body, content_type)
        found = guess(page, final_url)
        picture = page.picture()
        if not picture:
            raise ApiError(502, NO_PICTURE)
        image_url = urljoin(final_url, picture)
        check_url(image_url)
        data, picture_type, image_source = _download(image_url, IMAGE_ACCEPT, deadline, image_only=True)
    else:
        raise ApiError(502, WRONG_TYPE.format(what=_what(body, content_type)))
    ext, width, height = check_image(data, picture_type)
    token = stage(data, ext)
    return {"token": token, "bytes": data, "ext": ext, "width": width, "height": height,
            "final_url": final_url, "image_source": image_source, "guess": found}
