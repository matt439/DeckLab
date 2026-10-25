"""Who is asking, for visits through the tunnel: Cloudflare Access's signed login.

Cloudflare Access (config.json's "access": the Zero Trust team, the Deck Lab
application's AUD tag, and the port of the tunnel's listener) logs a visitor in
by email and sends each of their requests on with a JSON Web Token, in the
header Cf-Access-Jwt-Assertion and the cookie CF_Authorization. The server's
second listener (127.0.0.1:<access port>, for the tunnel only) takes no request
without one that Verifier.identify() accepts:

- signed with RS256 by one of the team's keys, published at
  https://<team>.cloudflareaccess.com/cdn-cgi/access/certs (kept in memory,
  fetched again for a key id not seen yet, at most once a minute; a known
  key is used without waiting for that fetch, and requests waiting for the
  same fetch share it);
- JSON without NaN or Infinity; "aud" (a string or a list) containing the AUD
  tag, "iss" the team's address, "exp" (required) not passed and "nbf" (when
  given) reached, each with a minute's leeway, and "exp", "nbf" and "iat"
  (when given) finite numbers;
- an "email", all ASCII, that belongs to exactly one profile in config.json
  (its "emails", compared after ASCII lowercasing: profiles.email_key);
- and a config.json whose profiles name their roles: while no profile has
  one (profiles.legacy, an older config where everyone is an admin), no one
  can sign in through the tunnel.

The answer is the visitor's identity, {"profile": <profile id>, "email",
"remote": True}; anything else raises AccessError (403). Verification uses
only the standard library: the signature is checked as RSASSA-PKCS1-v1_5 with
SHA-256 (RFC 8017 section 8.2.2) by comparing pow(signature, e, n) with the
exact encoding expected, in constant time.

The identity of the request being answered is also kept for its thread:
current() returns it (None for a request on the home listener), so code
below the server can ask who a request is from without trusting anything in
the request's body. The server sets it before routing and clears it after
(using()); work handed to another thread (a job runner) doesn't see it.

me(identity) is GET /api/me's answer.
"""
import base64
import contextlib
import hashlib
import hmac
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

from decklab.lib import config
from decklab.lib import profiles as profile_list

LEEWAY = 60                 # seconds of clock difference allowed for exp and nbf
REFETCH_EVERY = 60          # seconds at least between fetches of the team's keys
FETCH_TIMEOUT = 10          # seconds for that fetch
MAX_CERTS = 256 * 1024      # bytes of the keys' answer read at most
MAX_TOKEN = 16 * 1024       # characters of a token looked at at most
MIN_KEY_BITS = 2048
TOKEN_HEADER = "Cf-Access-Jwt-Assertion"
TOKEN_COOKIE = "CF_Authorization"
# Headers Cloudflare adds to every request it sends through a tunnel: the home
# listener refuses a request carrying any of them (a tunnel pointed at it).
CLOUDFLARE_HEADERS = (TOKEN_HEADER, "Cf-Ray", "Cf-Connecting-Ip", "Cf-Access-Authenticated-User-Email")
TEAM_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
AUD_RE = re.compile(r"[0-9a-f]{16,128}")
NOT_SET_UP = "This email isn't set up in Deck Lab"
NO_ROLES = ("Deck Lab's config.json gives no profile a role (admin or member), so no one can sign in from "
            "outside the home until it does")
# EMSA-PKCS1-v1_5's DigestInfo for SHA-256 (RFC 8017 section 9.2, note 1).
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class AccessError(Exception):
    """A request the tunnel's listener refuses (403), with the reason to show."""

    def __init__(self, message, status=403):
        super().__init__(message)
        self.message, self.status = message, status


def settings_of(settings):
    """config.json's "access" as {"team", "aud", "port"}, or None when there's
    none. ValueError for one that's there but wrong (a typo mustn't quietly
    leave the tunnel without its check)."""
    block = (settings or {}).get("access")
    if block is None:
        return None
    if not isinstance(block, dict):
        raise ValueError('"access" in config.json must be an object')
    team = str(block.get("team") or "").strip().lower()
    aud = str(block.get("aud") or "").strip().lower()
    port = block.get("port")
    if not TEAM_RE.fullmatch(team):
        raise ValueError('"access" needs "team": the Zero Trust team name (your-team, say)')
    if not AUD_RE.fullmatch(aud):
        raise ValueError('"access" needs "aud": the Access application\'s AUD tag (hex)')
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError('"access" needs "port": the port of the tunnel\'s listener (8644, say)')
    if port == (settings or {}).get("port", 8642):
        raise ValueError('"access" "port" must differ from Deck Lab\'s own "port"')
    return {"team": team, "aud": aud, "port": port}


def tunnel_hosts(settings):
    """The host names visits through the tunnel come with: "allowed_hosts" and
    the tunnel's "hostname", lowercase."""
    settings = settings or {}
    names = {str(h).strip().lower().rstrip(".") for h in settings.get("allowed_hosts") or []}
    tunnel = settings.get("tunnel")
    if isinstance(tunnel, dict) and tunnel.get("hostname"):
        names.add(str(tunnel["hostname"]).strip().lower().rstrip("."))
    return frozenset(name for name in names if name)


def home_refused_hosts(settings):
    """The host names the home listener refuses (421), whatever "access" says:
    with a valid "access", every tunnel host (tunnel_hosts); otherwise still
    the tunnel's own "hostname" and each "allowed_hosts" entry that is it or
    a name under it (www.<hostname>), so a tunnel pointed at the home
    listener while "access" is missing or wrong fails closed."""
    settings = settings or {}
    try:
        if settings_of(settings) is not None:
            return tunnel_hosts(settings)
    except ValueError:
        pass
    tunnel = settings.get("tunnel")
    hostname = str(tunnel.get("hostname") or "").strip().lower().rstrip(".") if isinstance(tunnel, dict) else ""
    if not hostname:
        return frozenset()
    return frozenset(h for h in tunnel_hosts(settings) if h == hostname or h.endswith("." + hostname))


def profile_for_email(email, listed):
    """The one profile whose "emails" has email, any case: profile_list.for_email,
    the one lookup Deck Lab has, over listed (config.json's "profiles" as
    written, read through profile_list.parse, so an entry the page couldn't
    use never signs in). AccessError when none does or more than one does."""
    usable = profile_list.parse(listed, access=True)
    found = profile_list.for_email(email, usable)
    if found is not None:
        return found
    wanted = profile_list.email_key(email)
    if wanted and sum(wanted in p["emails"] for p in usable) > 1:
        raise AccessError("This email is set up for more than one profile in Deck Lab's config.json")
    raise AccessError(NOT_SET_UP)


def _config_profiles():
    return config.load().get("profiles") or []


def fetch_keys(team):
    """The team's signing keys from Cloudflare: {kid: (n, e)}. OSError or
    ValueError when they can't be fetched or read."""
    url = f"https://{team}.cloudflareaccess.com/cdn-cgi/access/certs"
    request = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        body = response.read(MAX_CERTS + 1)
    if len(body) > MAX_CERTS:
        raise ValueError("the keys' answer is too long")
    return parse_keys(json.loads(body.decode("utf-8")))


def parse_keys(data):
    """{kid: (n, e)} from a JWK set ({"keys": [{"kid", "kty": "RSA", "n", "e"}, ...]}),
    keeping only RSA keys of at least MIN_KEY_BITS bits."""
    keys = {}
    listed = data.get("keys") if isinstance(data, dict) else None
    for key in listed if isinstance(listed, list) else []:
        if not isinstance(key, dict) or key.get("kty") != "RSA" or not isinstance(key.get("kid"), str):
            continue
        if key.get("alg") not in (None, "RS256") or key.get("use") not in (None, "sig"):
            continue
        try:
            n = int.from_bytes(_b64(key["n"]), "big")
            e = int.from_bytes(_b64(key["e"]), "big")
        except (KeyError, TypeError, ValueError):
            continue
        if n.bit_length() >= MIN_KEY_BITS and e >= 3 and e % 2 == 1:
            keys[key["kid"]] = (n, e)
    return keys


def _b64(text):
    """base64url without padding (as JWTs and JWKs write it) as bytes; ValueError otherwise."""
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", text) or len(text) % 4 == 1:
        raise ValueError("not base64url")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _no_constant(name):
    raise ValueError(f"{name} isn't allowed in a token")


def _json_part(text):
    data = json.loads(_b64(text).decode("utf-8"), parse_constant=_no_constant)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def rsa_sha256_valid(message, signature, n, e):
    """True when signature (bytes) is an RSASSA-PKCS1-v1_5 SHA-256 signature
    of message (bytes) by the key (n, e)."""
    size = (n.bit_length() + 7) // 8
    if len(signature) != size:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    encoded = pow(s, e, n).to_bytes(size, "big")
    digest = SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (size - 3 - len(digest)) + b"\x00" + digest
    return hmac.compare_digest(encoded, expected)


class Verifier:
    """Checks Cloudflare Access's tokens for one team and application.

    fetch(team) returns the team's keys ({kid: (n, e)}; fetch_keys by
    default), clock() the time in seconds, profiles() config.json's profiles
    (read again for every visit, so a change to "emails" needs no restart)."""

    def __init__(self, team, aud, fetch=None, clock=None, profiles=None):
        self.team, self.aud = team, aud
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self._fetch = fetch or fetch_keys
        self._clock = clock or time.time
        self._profiles = profiles or _config_profiles
        self._keys = {}
        self._fetched = None            # the clock when the keys were last fetched (or tried)
        self._flight = None             # the fetch under way, if any (_Flight)
        self._lock = threading.Lock()   # guards _fetched and _flight; never held while fetching

    @classmethod
    def from_settings(cls, settings, **kwargs):
        setup = settings_of(settings)
        return None if setup is None else cls(setup["team"], setup["aud"], **kwargs)

    def _key(self, kid):
        """The key kid names, fetching the team's keys when it isn't known and
        they weren't fetched in the last REFETCH_EVERY seconds. A known key
        is looked up without the lock (self._keys is only ever replaced
        whole), and the fetch runs outside it: one request fetches, others
        wanting an unknown key meanwhile wait for that same fetch (single
        flight), and requests with known keys never wait."""
        key = self._keys.get(kid)
        if key is not None:
            return key
        with self._lock:
            key = self._keys.get(kid)
            if key is not None:
                return key
            flight = self._flight
            leader = flight is None
            if leader:
                now = self._clock()
                if self._fetched is not None and now - self._fetched < REFETCH_EVERY:
                    return None
                self._fetched = now
                flight = self._flight = _Flight()
        if leader:
            try:
                self._keys = self._fetch(self.team) or self._keys
            except (OSError, ValueError, urllib.error.URLError) as e:
                flight.error = (f"Cloudflare Access's keys couldn't be fetched ({type(e).__name__}); "
                                f"try again in a minute")
            except BaseException:
                flight.error = "Cloudflare Access's keys couldn't be fetched; try again in a minute"
                raise
            finally:
                with self._lock:
                    self._flight = None
                flight.done.set()
        elif not flight.done.wait(FETCH_TIMEOUT * 2):
            raise AccessError("Cloudflare Access's keys are taking too long to fetch; try again in a minute")
        if flight.error:
            raise AccessError(flight.error)
        return self._keys.get(kid)

    def claims(self, token):
        """The token's claims once its signature and claims are checked; AccessError otherwise."""
        bad = AccessError("The Cloudflare Access login isn't valid: sign in again")
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN:
            raise bad
        parts = token.split(".")
        if len(parts) != 3:
            raise bad
        try:
            header, claims, signature = _json_part(parts[0]), _json_part(parts[1]), _b64(parts[2])
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise bad from None
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise bad
        key = self._key(header["kid"])
        if key is None or not rsa_sha256_valid(f"{parts[0]}.{parts[1]}".encode("ascii"), signature, *key):
            raise bad
        aud = claims.get("aud")
        auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if self.aud not in [a.lower() for a in auds if isinstance(a, str)]:
            raise AccessError("The Cloudflare Access login is for another application")
        if claims.get("iss") != self.issuer:
            raise AccessError("The Cloudflare Access login is from another team")
        now = self._clock()
        exp, nbf = claims.get("exp"), claims.get("nbf")
        if not _number(exp) or now > exp + LEEWAY:
            raise AccessError("The Cloudflare Access login has expired: sign in again")
        if nbf is not None and (not _number(nbf) or now + LEEWAY < nbf):
            raise AccessError("The Cloudflare Access login isn't valid yet: check the PC's clock")
        if "iat" in claims and not _number(claims["iat"]):
            raise bad
        if not isinstance(claims.get("email"), str) or not claims["email"].strip():
            raise AccessError("The Cloudflare Access login has no email address")
        return claims

    def identify(self, token):
        """The identity a token is for, {"profile", "email", "remote": True}; AccessError otherwise."""
        claims = self.claims(token)
        email = profile_list.email_key(claims["email"])
        if email is None:                   # not all ASCII: never matched (profiles.email_key)
            raise AccessError(NOT_SET_UP)
        try:
            profiles = self._profiles()
        except (OSError, ValueError, TypeError):
            raise AccessError("Deck Lab's config.json can't be read, so no one can be signed in", 500) from None
        if not isinstance(profiles, list) or profile_list.legacy(profiles):
            raise AccessError(NO_ROLES)
        profile = profile_for_email(email, profiles)
        return {"profile": profile["id"], "email": email, "remote": True}


class _Flight:
    """One fetch of the team's keys under way: done is set when it ends, and
    error holds the refusal's words when it failed."""

    def __init__(self):
        self.done = threading.Event()
        self.error = None


def _number(value):
    """True for a finite int or float (not a bool, and not the infinity a
    large exponent such as 1e400 is read as)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)


def token_of(headers):
    """The token a request carries: the Cf-Access-Jwt-Assertion header, else
    the CF_Authorization cookie; None when neither (or the header is given twice)."""
    given = headers.get_all(TOKEN_HEADER) or []
    if len(given) > 1:
        return None
    if given:
        return given[0].strip()
    for cookie_header in headers.get_all("Cookie") or []:
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name == TOKEN_COOKIE and value:
                return value.strip().strip('"')
    return None


# ------------------------------------------------------- the request's identity

_local = threading.local()
# The header the page sends on the home network with the profile chosen there, so the answers
# about things only their owner sees (the accessories) are that profile's, and a write's body
# must name the same profile (api/settings._writer). It's who's looking, not a login: anyone on
# the home network may name anyone. An accessory picture's <img> sends no header, so its address
# names the viewer instead (server_http's _accessory_image).
VIEWER_HEADER = "X-Deck-Lab-Viewer"
# The header a script on the PC sends ("1") to be answered as a script: everything, as the
# command line reads it. It counts only on the home listener, from loopback (127.0.0.1 or ::1),
# with no viewer named (server_http decides; script() says what it decided). The tunnel's
# listener is on 127.0.0.1 too, so it never counts there.
SCRIPT_HEADER = "X-Deck-Lab-Script"
# What a home-listener request naming a profile from outside the home gets, on every route: the
# home's chooser offers only home profiles, and everyone else comes in through the tunnel's login.
# It names config.json's tunnel hostname, read once at start-up.


def _sign_in_outside():
    try:
        hostname = (config.load().get("tunnel") or {}).get("hostname")
    except Exception:
        hostname = None
    if isinstance(hostname, str) and hostname.strip():
        return f"Sign in through {hostname.strip()}"
    return "Sign in through the Deck Lab website"


SIGN_IN_OUTSIDE = _sign_in_outside()


def current():
    """The identity of the request this thread is answering: {"profile",
    "email", "remote": True} for a visit through the tunnel, None for one on
    the home network (or outside a request)."""
    return getattr(_local, "identity", None)


@contextlib.contextmanager
def using(identity):
    """current() is identity while the block runs."""
    before = getattr(_local, "identity", None)
    _local.identity = identity
    try:
        yield
    finally:
        _local.identity = before


def viewer():
    """The profile id a home-network request names in VIEWER_HEADER (the
    page's chooser), or None. Through the tunnel it's always None: the
    login says who's asking (current())."""
    return getattr(_local, "viewer", None)


@contextlib.contextmanager
def viewing(profile_id):
    """viewer() is profile_id while the block runs."""
    before = getattr(_local, "viewer", None)
    _local.viewer = profile_id
    try:
        yield
    finally:
        _local.viewer = before


def script():
    """True when this thread is answering a script's request (the home listener, from loopback,
    with SCRIPT_HEADER: 1 and naming nobody), or no request at all (a job thread, a test, the
    command line): those read everything when they name nobody. False for every other request,
    the PC's own browser before a profile is picked included (it sends no script header), and
    always a visit through the tunnel (current() isn't None)."""
    if current() is not None:
        return False
    return getattr(_local, "script", True)


@contextlib.contextmanager
def answering(is_script):
    """script() is is_script while the block runs (the server's, around each request)."""
    before = getattr(_local, "script", True)
    _local.script = bool(is_script)
    try:
        yield
    finally:
        _local.script = before


def me(identity, profiles=None):
    """GET /api/me: {"profile": <id> or None, "name": its name or None,
    "remote": whether the request came through the tunnel, "may": what the
    visitor may change (permissions.summary), so the page can hide controls
    the server would refuse}. Through the tunnel it answers for the login;
    on the home network for the profile the page's chooser picked (viewer(),
    the X-Deck-Lab-Viewer header: the server holds that profile's reads and
    writes to the same rules, lib/permissions.py), and before a pick for
    nobody: a script's everything (script()), anyone else's only what's
    open to all. A viewer config.json doesn't list is answered as nobody.
    profiles: config.json's "profiles" as written (read when not given, its
    roles then read as guard.viewer() reads them: by whether config.json has
    an "access" block)."""
    from decklab.lib import permissions, spaces, visibility
    has_access = False
    if profiles is None:
        settings = config.load()
        profiles, has_access = settings.get("profiles") or [], settings.get("access") is not None
    listed = profile_list.parse(profiles, access=identity is not None or has_access)
    space_ids = spaces.space_ids(listed)
    switches = visibility.snapshot()
    summary = lambda profile, script: permissions.summary(profile, script=script, space_ids=space_ids,
                                                          vis=switches, ready=visibility.READY_THINGS)
    if identity is None:
        profile = profile_list.find(viewer(), listed) if viewer() else None
        if profile is None:
            return {"profile": None, "name": None, "remote": False,
                    "may": summary(None, script())}
        return {"profile": profile["id"], "name": profile["name"], "remote": False,
                "may": summary(profile, False)}
    profile = profile_list.find(identity["profile"], listed)
    return {"profile": identity["profile"], "name": profile["name"] if profile else None,
            "remote": bool(identity.get("remote")),
            "may": summary(profile, False)}
