"""Tests for decklab/lib/access.py: Cloudflare Access tokens checked with a
fixed 2048-bit test key pair (made once, offline, from two primes found with
Python's random module: never a real key), the email-to-profile lookup, the
request's identity and GET /api/me's answer. Nothing here reaches the internet.

Run from the repo root: python scripts/test_fixtures.py
"""
import base64
import hashlib
import hmac
import json
import threading
import unittest
from email.message import Message

from decklab.lib import access

N = int(
    "e329d088aca4e710c37708b18ca5101857eab86c94ee9f0c7aff42d99450c5461e57e23a6ed6a15ec0e4a01ca1441773"
    "6c4ce5f4510ac92bcf987051136e1ee7428b6adc83d74f52f27aacc1d999b3025028a0209bfaff2de9bf90bb609c3689"
    "e19684ec616f5f602ddc282407b6a71c621fbbb6e066254e0ab974c9c29d2df5e6884ab63a921697e8d212ff7f088e70"
    "5d08598e2a9483388c656a4f5f06f7f1d8c97ad77702dfab3fece601c128011998fb7c0f2c198c00e2afb5fe7a3afd9c"
    "0bb1830ddee18da550f27cee470b292d3b3f281262e03e113db56856ed5f425e07c8d9d012678d035617ba0a1a19473d"
    "4dbdb6fff6b205d9c8c5469abcafbbbf", 16)
D = int(
    "70da1f1d2717ad2b28d003e3a0c987db7021cd8933dbefebd556e6b10cfbab6590417cc426b83de6c2d151b1a7741a6a"
    "5f0d3cd84942a07a4161abbabb7a63a3e3ed3b235de42326440c29b30c154d5702d78be5675824597cdc8c5c6a3c70e3"
    "c2cc7230b49f0db4cc53a9256d2792918935d69d9d91614b0a0ce4362f96c2738d5fb50a60b183373c8794959cb3ad0a"
    "58adf092b3e82aeb917d78109b631b3efe656cb0030477d188c33b6a73deff84d0abe1348d48489a978d4d71d83cda2e"
    "8e1d983095e30b52e9149075c5320ed5c291a48b638f8f5de25319221fb1732d098f80a70cb092cdae916d230bc7b73b"
    "521a90962ed966f1851a6d3b975d9971", 16)
E = 65537
TEAM = "test-team"
AUD = "ab" * 32
NOW = 1_800_000_000
PROFILES = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "emails": ["matt@example.com"]},
            {"id": "user1", "name": "User1", "plays_as": "wife", "emails": ["User1@Example.com", "c2@example.com"]},
            {"id": "user2", "name": "User2", "space": "user2", "emails": ["shared@example.com"]},
            {"id": "user3", "name": "User3", "space": "user3", "emails": ["shared@example.com"]}]


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwk(kid="k1", n=N, e=E):
    return {"kid": kid, "kty": "RSA", "alg": "RS256", "use": "sig",
            "n": b64(n.to_bytes((n.bit_length() + 7) // 8, "big")), "e": b64(e.to_bytes(3, "big"))}


def sign(message, d=D, n=N):
    size = (n.bit_length() + 7) // 8
    digest = access.SHA256_PREFIX + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + b"\xff" * (size - 3 - len(digest)) + b"\x00" + digest
    return pow(int.from_bytes(encoded, "big"), d, n).to_bytes(size, "big")


def claims(**changes):
    base = {"aud": [AUD], "iss": f"https://{TEAM}.cloudflareaccess.com", "email": "matt@example.com",
            "exp": NOW + 3600, "iat": NOW - 10, "nbf": NOW - 10, "type": "app", "sub": "x"}
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def token(payload=None, header=None, signature=None):
    head = b64(json.dumps(header or {"alg": "RS256", "kid": "k1", "typ": "JWT"}).encode())
    body = b64(json.dumps(claims() if payload is None else payload).encode())
    signed = f"{head}.{body}".encode("ascii")
    return f"{head}.{body}.{b64(sign(signed) if signature is None else signature)}"


class Fetcher:
    """Stands in for fetch_keys: counts calls, answers the keys given."""

    def __init__(self, keys=None):
        self.keys = {"keys": [jwk()]} if keys is None else keys
        self.calls = 0

    def __call__(self, team):
        assert team == TEAM
        self.calls += 1
        if isinstance(self.keys, Exception):
            raise self.keys
        return access.parse_keys(self.keys)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.fetch, self.clock = Fetcher(), Clock()
        self.verifier = access.Verifier(TEAM, AUD, fetch=self.fetch, clock=self.clock, profiles=lambda: PROFILES)

    def refused(self, text, contains="isn't valid"):
        with self.assertRaises(access.AccessError) as caught:
            self.verifier.identify(text)
        self.assertEqual(caught.exception.status, 403)
        self.assertIn(contains, caught.exception.message)
        return caught.exception

    def test_a_good_token(self):
        self.assertEqual(self.verifier.identify(token()),
                         {"profile": "matt", "email": "matt@example.com", "remote": True})
        self.assertEqual(self.fetch.calls, 1)
        self.verifier.identify(token())
        self.assertEqual(self.fetch.calls, 1)           # the key is kept

    def test_aud_as_a_string_and_email_in_any_case(self):
        identity = self.verifier.identify(token(claims(aud=AUD, email=" C2@EXAMPLE.com")))
        self.assertEqual(identity["profile"], "user1")
        self.assertEqual(identity["email"], "c2@example.com")
        self.assertEqual(self.verifier.identify(token(claims(email="user1@example.com")))["profile"], "user1")

    def test_wrong_aud(self):
        self.refused(token(claims(aud=["cd" * 32])), "another application")
        self.refused(token(claims(aud=None)), "another application")
        self.refused(token(claims(aud=[AUD + "0"])), "another application")

    def test_wrong_issuer(self):
        self.refused(token(claims(iss="https://other.cloudflareaccess.com")), "another team")
        self.refused(token(claims(iss=None)), "another team")

    def test_expired(self):
        self.verifier.identify(token(claims(exp=NOW - 59)))           # within the leeway
        self.refused(token(claims(exp=NOW - 61)), "expired")
        self.refused(token(claims(exp=None)), "expired")
        self.refused(token(claims(exp="soon")), "expired")

    def test_not_valid_yet(self):
        self.verifier.identify(token(claims(nbf=NOW + 59)))
        self.refused(token(claims(nbf=NOW + 61)), "isn't valid yet")
        self.verifier.identify(token(claims(nbf=None)))                # nbf is optional

    def test_bad_signature(self):
        good = token()
        head, body, sig = good.split(".")
        flipped = bytearray(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
        flipped[-1] ^= 1
        self.refused(f"{head}.{body}.{b64(bytes(flipped))}")
        # The claims changed after signing: the signature no longer fits them.
        other = b64(json.dumps(claims(email="user1@example.com")).encode())
        self.refused(f"{head}.{other}.{sig}")
        self.refused(token(signature=b"\x00" * 256))
        self.refused(token(signature=N.to_bytes(256, "big")))          # s >= n
        self.refused(token(signature=b"\x01" * 255))                   # wrong length

    def test_alg_none_and_hs256_are_refused(self):
        for alg in ("none", "HS256", "RS512", None):
            head = b64(json.dumps({"alg": alg, "kid": "k1"}).encode())
            body = b64(json.dumps(claims()).encode())
            mac = hmac.new(b"k1", f"{head}.{body}".encode(), hashlib.sha256).digest()
            self.refused(f"{head}.{body}.")
            self.refused(f"{head}.{body}.{b64(mac)}")
            self.refused(f"{head}.{body}.{b64(sign(f'{head}.{body}'.encode()))}")
        self.assertEqual(self.fetch.calls, 0)           # refused before any key is fetched

    def test_malformed_tokens(self):
        for text in ("", "a.b", "a.b.c.d", "!!.!!.!!", token() + "x" * access.MAX_TOKEN, None, 7):
            self.refused(text)

    def test_unknown_kid_refetches_at_most_once_a_minute(self):
        self.verifier.identify(token())
        self.assertEqual(self.fetch.calls, 1)
        rotated = token(header={"alg": "RS256", "kid": "k2"})
        self.clock.now += 30
        self.refused(rotated)                           # not within a minute of the first fetch
        self.assertEqual(self.fetch.calls, 1)
        self.clock.now += 31
        self.refused(rotated)                           # fetched again: still not there
        self.assertEqual(self.fetch.calls, 2)
        self.refused(rotated)
        self.refused(rotated)
        self.assertEqual(self.fetch.calls, 2)           # not within the minute
        self.clock.now += 61
        self.fetch.keys = {"keys": [jwk("k1"), jwk("k2")]}
        self.assertEqual(self.verifier.identify(rotated)["profile"], "matt")
        self.assertEqual(self.fetch.calls, 3)
        self.verifier.identify(token())
        self.assertEqual(self.fetch.calls, 3)

    def test_keys_that_cant_be_fetched(self):
        self.fetch.keys = OSError("offline")
        self.refused(token(), "couldn't be fetched")
        self.refused(token(), "isn't valid")            # not asked again within the minute
        self.assertEqual(self.fetch.calls, 1)

    def test_weak_or_odd_keys_are_ignored(self):
        small = 0xC5B1 * 0xD3A7
        keys = access.parse_keys({"keys": [jwk("small", n=small), {"kid": "ec", "kty": "EC"}, "x",
                                           {**jwk("hs"), "alg": "HS256"}, {**jwk("bad"), "n": "!!"}, jwk()]})
        self.assertEqual(list(keys), ["k1"])
        self.assertEqual(access.parse_keys({"keys": "x"}), {})
        self.assertEqual(access.parse_keys([]), {})

    def test_no_email(self):
        self.refused(token(claims(email=None)), "no email")
        self.refused(token(claims(email="  ")), "no email")

    def test_an_email_no_profile_has(self):
        error = self.refused(token(claims(email="stranger@example.com")), "isn't set up in Deck Lab")
        self.assertEqual(error.message, access.NOT_SET_UP)

    def test_an_email_two_profiles_have(self):
        self.refused(token(claims(email="shared@example.com")), "more than one profile")

    def raw_token(self, body):
        """A token signed over body, the claims' JSON exactly as given."""
        head = b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
        payload = b64(body.encode())
        return f"{head}.{payload}.{b64(sign(f'{head}.{payload}'.encode('ascii')))}"

    def test_nan_and_infinity_are_refused(self):
        base = json.dumps(claims())[:-1]            # without its closing brace
        self.verifier.identify(self.raw_token(base + "}"))
        for extra in (', "exp": NaN', ', "exp": Infinity', ', "nbf": -Infinity', ', "iat": NaN',
                      ', "exp": 1e400', ', "nbf": 1e400', ', "iat": -1e400'):
            self.refused(self.raw_token(base + extra + "}"), "")
        self.refused(token(claims(iat="yesterday")))
        self.refused(token(claims(nbf="later")), "isn't valid yet")
        self.verifier.identify(token(claims(exp=float(NOW + 10), iat=None)))    # floats and no iat are fine

    def test_emails_must_be_ascii(self):
        listed = PROFILES + [{"id": "kim", "name": "Kim", "space": "kim", "emails": ["kim@example.com"]}]
        self.verifier = access.Verifier(TEAM, AUD, fetch=self.fetch, clock=self.clock, profiles=lambda: listed)
        self.assertEqual(self.verifier.identify(token(claims(email="KIM@example.com")))["profile"], "kim")
        for email in ("Kim@example.com", "matt@exаmple.com", "mätt@example.com"):
            error = self.refused(token(claims(email=email)), "isn't set up")
            self.assertEqual(error.message, access.NOT_SET_UP)

    def test_no_logins_while_no_profile_has_a_role(self):
        legacy = [{k: v for k, v in p.items() if k != "role"} for p in PROFILES]
        self.verifier = access.Verifier(TEAM, AUD, fetch=self.fetch, clock=self.clock, profiles=lambda: legacy)
        error = self.refused(token(), "no profile a role")
        self.assertEqual(error.message, access.NO_ROLES)
        # With "access" set, a profile without a role is a member, whoever else has one.
        self.assertEqual(access.profile_for_email("user1@example.com", PROFILES)["role"], "member")

    def test_known_keys_dont_wait_for_a_fetch(self):
        self.verifier.identify(token())                 # k1 known
        self.clock.now += 61
        started, release = threading.Event(), threading.Event()
        real = self.fetch

        def slow(team):
            started.set()
            release.wait(10)
            return real(team)
        self.verifier._fetch = slow
        rotated = token(header={"alg": "RS256", "kid": "k2"})
        results = []
        waiters = [threading.Thread(target=lambda: results.append(self.answer(rotated))) for _ in range(3)]
        for thread in waiters:
            thread.start()
        self.assertTrue(started.wait(5))
        # A request with a known key is answered while the fetch hangs.
        done = []
        known = threading.Thread(target=lambda: done.append(self.verifier.identify(token())["profile"]))
        known.start()
        known.join(5)
        self.assertEqual(done, ["matt"])
        self.fetch.keys = {"keys": [jwk("k1"), jwk("k2")]}
        release.set()
        for thread in waiters:
            thread.join(5)
        self.assertEqual(results, ["matt"] * 3)
        self.assertEqual(self.fetch.calls, 2)           # one fetch for all three (single flight)

    def test_a_failed_fetch_is_shared_too(self):
        self.verifier.identify(token())
        self.clock.now += 61
        started, release = threading.Event(), threading.Event()

        def failing(team):
            started.set()
            release.wait(10)
            raise OSError("offline")
        self.verifier._fetch = failing
        rotated = token(header={"alg": "RS256", "kid": "k2"})
        results = []
        waiters = [threading.Thread(target=lambda: results.append(self.answer(rotated))) for _ in range(2)]
        for thread in waiters:
            thread.start()
        self.assertTrue(started.wait(5))
        release.set()
        for thread in waiters:
            thread.join(5)
        self.assertEqual(len(results), 2)
        self.assertTrue(all("couldn't be fetched" in r for r in results), results)
        self.assertIsNone(self.verifier._flight)

    def answer(self, text):
        try:
            return self.verifier.identify(text)["profile"]
        except access.AccessError as e:
            return e.message


class SettingsTests(unittest.TestCase):
    def test_settings(self):
        self.assertIsNone(access.settings_of({}))
        self.assertEqual(access.settings_of({"access": {"team": "your-team", "aud": AUD.upper(), "port": 8644}}),
                         {"team": "your-team", "aud": AUD, "port": 8644})
        for wrong in ("x", {"team": "a/b", "aud": AUD, "port": 8644}, {"team": "t", "aud": "zz", "port": 8644},
                      {"team": "t", "aud": AUD, "port": "8644"}, {"team": "t", "aud": AUD, "port": 8642},
                      {"team": "t", "aud": AUD, "port": 70000}):
            with self.assertRaises(ValueError):
                access.settings_of({"access": wrong})

    def test_tunnel_hosts(self):
        self.assertEqual(access.tunnel_hosts({"allowed_hosts": ["DeckLab.Example.com.", "www.decklab.example.com"],
                                              "tunnel": {"hostname": "x.example"}}),
                         {"decklab.example.com", "www.decklab.example.com", "x.example"})
        self.assertEqual(access.tunnel_hosts({}), frozenset())

    def test_from_settings(self):
        self.assertIsNone(access.Verifier.from_settings({}))
        verifier = access.Verifier.from_settings({"access": {"team": TEAM, "aud": AUD, "port": 8644}})
        self.assertEqual(verifier.issuer, f"https://{TEAM}.cloudflareaccess.com")


class TokenOfTests(unittest.TestCase):
    def headers(self, *pairs):
        message = Message()
        for name, value in pairs:
            message[name] = value
        return message

    def test_header_then_cookie(self):
        self.assertEqual(access.token_of(self.headers(("Cf-Access-Jwt-Assertion", " a.b.c "))), "a.b.c")
        self.assertEqual(access.token_of(self.headers(("Cookie", "x=1; CF_Authorization=d.e.f; y=2"))), "d.e.f")
        self.assertEqual(access.token_of(self.headers(("Cf-Access-Jwt-Assertion", "a.b.c"),
                                                      ("Cookie", "CF_Authorization=d.e.f"))), "a.b.c")
        self.assertIsNone(access.token_of(self.headers(("Cookie", "CF_Authorization="))))
        self.assertIsNone(access.token_of(self.headers()))
        self.assertIsNone(access.token_of(self.headers(("Cf-Access-Jwt-Assertion", "a"),
                                                       ("Cf-Access-Jwt-Assertion", "b"))))


class IdentityTests(unittest.TestCase):
    def test_current_is_per_thread_and_restored(self):
        identity = {"profile": "matt", "email": "m", "remote": True}
        seen = []
        with access.using(identity):
            self.assertIs(access.current(), identity)
            other = threading.Thread(target=lambda: seen.append(access.current()))
            other.start()
            other.join()
        self.assertEqual(seen, [None])
        self.assertIsNone(access.current())

    def test_me(self):
        local = access.me(None, PROFILES)
        self.assertEqual({k: local[k] for k in ("profile", "name", "remote")},
                         {"profile": None, "name": None, "remote": False})
        self.assertTrue(local["may"]["admin"])                      # the home network edits everything
        self.assertEqual(local["may"]["spaces"], ["home", "user2", "user3"])
        user1 = access.me({"profile": "user1", "email": "c", "remote": True}, PROFILES)
        self.assertEqual({k: user1[k] for k in ("profile", "name", "remote")},
                         {"profile": "user1", "name": "User1", "remote": True})

    def test_me_for_a_member(self):
        listed = [dict(p, role="admin" if p["id"] == "matt" else "member") for p in PROFILES]
        may = access.me({"profile": "user2", "email": "r", "remote": True}, listed)["may"]
        self.assertEqual((may["admin"], may["spaces"], may["accessories"]), (False, ["user2"], False))
        may = access.me({"profile": "user1", "email": "c", "remote": True}, listed)["may"]
        self.assertEqual((may["admin"], may["spaces"], may["home_player"]), (False, ["home"], "wife"))   # E10-S43


if __name__ == "__main__":
    unittest.main()
