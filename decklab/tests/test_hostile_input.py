"""Damaged input for the hand-written readers (E11-S66): valid pictures and
sign-in tokens changed by a seeded run of bit flips, truncation, length edits
and repeated chunks, then given to the PNG, JPEG and WebP readers and to
access.Verifier.

A picture reader may accept a changed picture or refuse it with its usual
ApiError, never anything else. A changed token is never accepted unless it's
byte-equal to the original. Every run is random.Random(SEED), so a failure
names a mutant number that fails again the same way, and each loop is bounded
by a count, not by time.

The pictures and tokens come from the builders of test_accessory_fetch.py,
test_api_accessory_upload.py and test_access.py (imported as modules, so
their test classes aren't collected here a second time).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_hostile_input
"""
import base64
import json
import random
import struct
import unittest
import zlib

from decklab.lib import access, accessory_fetch, accessory_upload
from decklab.lib import profiles as profile_list
from decklab.lib.api import collection_scan
from decklab.lib.api.common import ApiError
from decklab.tests import test_access as access_tests
from decklab.tests import test_accessory_fetch as fetch_tests
from decklab.tests import test_api_accessory_upload as upload_tests

SEED = 0
PICTURE_MUTANTS = 1000      # of each sample picture
TOKEN_MUTANTS = 5000
CLAIM_MUTANTS = 150         # each is signed with the test key, the slow part
SIGNATURE_MUTANTS = 600
EXTS = ("png", "jpg", "webp")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# --- Where a picture's chunks and length fields are --------------------------
# Each answers (cuts, lengths) for a valid picture: cuts are the offsets where a
# chunk or segment starts (and the end of the data), lengths are (offset, size
# in bytes, struct byte order) of each length field.

def png_layout(data):
    cuts, lengths, offset = [8], [], 8
    while offset + 12 <= len(data):
        lengths.append((offset, 4, ">"))
        offset += struct.unpack_from(">I", data, offset)[0] + 12
        cuts.append(offset)
    return cuts, lengths


def jpeg_layout(data):
    cuts, lengths, offset = [2], [], 2
    while offset + 4 <= len(data) and data[offset] == 0xFF:
        start = offset
        while data[offset] == 0xFF:                 # fill bytes
            offset += 1
        marker = data[offset]
        offset += 1
        if marker in (0xD9, 0xDA) or 0xD0 <= marker <= 0xD7:
            if marker == 0xDA:
                lengths.append((offset, 2, ">"))
            offset = start
            break
        lengths.append((offset, 2, ">"))
        offset += struct.unpack_from(">H", data, offset)[0]
        cuts.append(offset)
    return sorted(set(cuts + [offset, len(data)])), lengths


def webp_layout(data):
    cuts, lengths, offset = [12], [(4, 4, "<")], 12
    while offset + 8 <= len(data):
        lengths.append((offset + 4, 4, "<"))
        size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8 + size + size % 2
        cuts.append(offset)
    return cuts, lengths


LAYOUTS = {"png": png_layout, "jpg": jpeg_layout, "webp": webp_layout}


def png_with_crcs(data):
    """data with each PNG chunk's CRC worked out again, as far as its chunks
    can be followed, so a change inside a chunk reaches the checks after the CRC."""
    out, offset = bytearray(data), 8
    while offset + 12 <= len(out):
        end = offset + struct.unpack_from(">I", out, offset)[0] + 12
        if end > len(out):
            break
        struct.pack_into(">I", out, end - 4, zlib.crc32(bytes(out[offset + 4:end - 4])))
        offset = end
    return bytes(out)


def webp_with_size(data):
    """data with the RIFF size made to fit it, so repeated chunks are read."""
    if len(data) < 8:
        return data
    return data[:4] + struct.pack("<I", (len(data) - 8) & 0xFFFFFFFF) + data[8:]


# --- The changes -------------------------------------------------------------

def flip_bits(rng, data, _layout):
    out = bytearray(data)
    for _ in range(rng.randint(1, 4)):
        if out:
            out[rng.randrange(len(out))] ^= 1 << rng.randrange(8)
    return bytes(out)


def truncate(rng, data, layout):
    cuts = layout[0]
    if rng.random() < 0.3:                          # at a chunk's edge, or just beside one
        return data[:max(0, rng.choice(cuts) + rng.choice((-1, 0, 1)))]
    return data[:rng.randrange(len(data) + 1)]


def edit_length(rng, data, layout):
    lengths = layout[1]
    if not lengths:
        return flip_bits(rng, data, layout)
    offset, size, order = rng.choice(lengths)
    top = (1 << (8 * size)) - 1
    old = int.from_bytes(data[offset:offset + size], "big" if order == ">" else "little")
    new = rng.choice((0, 1, 2, old - 1, old + 1, old - rng.randint(2, 16), old + rng.randint(2, 16),
                      old * 2, len(data), len(data) - offset, top, top - 1, top // 2, top // 2 + 1,
                      rng.randint(0, top))) & top
    return data[:offset] + new.to_bytes(size, "big" if order == ">" else "little") + data[offset + size:]


def repeat_chunk(rng, data, layout):
    cuts = layout[0]
    if len(cuts) < 2:
        return data + data
    first = rng.randrange(len(cuts) - 1)
    last = rng.randrange(first + 1, len(cuts))
    piece = data[cuts[first]:cuts[last]] * rng.randint(1, 3)
    at = rng.choice(cuts)
    return data[:at] + piece + data[at:]


def splice(rng, data, _layout):
    start = rng.randrange(len(data) + 1)
    end = min(len(data), start + rng.randint(0, 24))
    choice = rng.randrange(3)
    if choice == 0:                                 # bytes dropped
        return data[:start] + data[end:]
    if choice == 1:                                 # the same bytes again
        return data[:end] + data[start:end] + data[end:]
    return data[:start] + bytes(rng.randrange(256) for _ in range(rng.randint(1, 12))) + data[start:]


CHANGES = (flip_bits, truncate, edit_length, repeat_chunk, splice)


def mutant(rng, data, ext):
    """One changed copy of a valid picture: one or two changes, and half the
    time the checksums and sizes a careful forger would fix afterwards."""
    layout = LAYOUTS[ext](data)
    out = rng.choice(CHANGES)(rng, data, layout)
    if rng.random() < 0.25:
        out = rng.choice(CHANGES)(rng, out, layout)
    if rng.random() < 0.5:
        out = png_with_crcs(out) if ext == "png" else webp_with_size(out) if ext == "webp" else out
    return out


def samples():
    """(name, extension, bytes) of the valid pictures the other tests build."""
    return [
        ("png", "png", upload_tests.png()),
        ("png header", "png", fetch_tests.png()),
        ("jpeg", "jpg", upload_tests.complete_jpeg()),
        ("jpeg header", "jpg", fetch_tests.jpeg()),
        ("progressive jpeg", "jpg", upload_tests.PROGRESSIVE_JPEG),
        ("webp lossy", "webp", upload_tests.complete_webp()),
        ("webp lossless", "webp", upload_tests.complete_webp(lossless=True)),
        ("webp extended", "webp", upload_tests.EXTENDED_WEBP),
        ("webp extended header", "webp", fetch_tests.webp_vp8x()),
    ]


class LayoutTests(unittest.TestCase):
    """The helpers above find the real chunks, or the changes would miss them."""

    def test_layouts_cover_each_sample(self):
        for name, ext, data in samples():
            with self.subTest(name):
                cuts, lengths = LAYOUTS[ext](data)
                self.assertEqual(cuts, sorted(set(cuts)))
                self.assertGreaterEqual(len(cuts), 2)
                self.assertTrue(lengths)
                self.assertLessEqual(cuts[-1], len(data) + 1)
                for offset, size, _ in lengths:
                    self.assertLessEqual(offset + size, len(data))

    def test_fixing_a_valid_picture_changes_nothing(self):
        data = upload_tests.png()
        self.assertEqual(png_with_crcs(data), data)
        self.assertEqual(png_layout(data)[0][-1], len(data))
        for lossless in (False, True):
            data = upload_tests.complete_webp(lossless=lossless)
            self.assertEqual(webp_with_size(data), data)
            self.assertEqual(webp_layout(data)[0][-1], len(data))
        data = upload_tests.complete_jpeg()
        self.assertEqual(jpeg_layout(data)[0][-1], len(data))

    def test_the_run_is_seeded(self):
        data = upload_tests.png()
        first = [mutant(random.Random(SEED), data, "png") for _ in range(2)]
        self.assertEqual(first[0], first[1])
        rng = random.Random(SEED)
        self.assertGreater(len({mutant(rng, data, "png") for _ in range(50)}), 25)


class PictureMutationTests(unittest.TestCase):
    def usual(self, status, call, *args):
        """call's answer, or None when it refused with ApiError of this status
        and words to show; anything else raised is the test's failure."""
        try:
            return call(*args)
        except ApiError as error:
            self.assertEqual(error.status, status)
            self.assertIsInstance(error.message, str)
            self.assertTrue(error.message.strip())
            return None

    def read(self, data):
        """Every reader on data. True when the upload's full check accepted it."""
        for ext in EXTS:                            # whatever the first bytes say
            size = accessory_fetch.dimensions(data, ext)
            if size is not None:
                self.assertEqual(len(size), 2)
                self.assertTrue(all(isinstance(side, int) for side in size))
        self.assertIn(accessory_fetch.sniff(data), EXTS + (None,))
        for complete in (accessory_upload._png, accessory_upload._jpeg):
            self.assertIn(bool(complete(data)), (True, False))
        self.assertIn(bool(accessory_upload._webp_chunks(data, 12)), (True, False))
        checked = self.usual(502, accessory_fetch.check_image, data)
        if checked is not None:
            ext, width, height = checked
            self.assertIn(ext, EXTS)
            for side in (width, height):
                self.assertTrue(accessory_fetch.MIN_SIDE <= side <= accessory_fetch.MAX_SIDE)
        text = base64.b64encode(data).decode("ascii")
        kept = self.usual(400, accessory_upload.decode, text) if text else None
        if kept is not None:
            self.assertEqual(kept, data)
            self.assertIsNotNone(checked)           # the upload never keeps what the header check refuses
        photo = self.usual(400, collection_scan._photo, text) if text else None
        if photo is not None:
            self.assertEqual(photo[0], data)
            self.assertIn(photo[1], ("jpg", "png"))
        return kept is not None

    def test_the_samples_are_valid(self):
        for name, ext, data in samples():
            with self.subTest(name):
                self.assertEqual(accessory_fetch.check_image(data)[0], ext)
        for data in (upload_tests.png(), upload_tests.complete_jpeg(), upload_tests.PROGRESSIVE_JPEG,
                     upload_tests.complete_webp(), upload_tests.complete_webp(lossless=True),
                     upload_tests.EXTENDED_WEBP):
            self.assertTrue(self.read(data))

    def test_changed_pictures_are_accepted_or_refused_as_usual(self):
        rng = random.Random(SEED)
        refused = 0
        for name, ext, data in samples():
            for number in range(PICTURE_MUTANTS):
                changed = mutant(rng, data, ext)
                with self.subTest(picture=name, mutant=number):
                    refused += not self.read(changed)
        self.assertGreater(refused, len(samples()) * PICTURE_MUTANTS // 2)     # the changes do damage

    def test_every_truncation(self):
        """Each sample cut at every length: the cheapest change, done in full."""
        for name, _, data in samples():
            for length in range(len(data)):
                with self.subTest(picture=name, length=length):
                    self.assertFalse(self.read(data[:length]))

    def test_other_bytes(self):
        rng = random.Random(SEED)
        heads = (b"", PNG_MAGIC, b"\xff\xd8\xff", b"RIFF\0\0\0\0WEBP", b"RIFF\x10\0\0\0WEBPVP8 ",
                 b"RIFF\x10\0\0\0WEBPVP8L", b"RIFF\x10\0\0\0WEBPVP8X", PNG_MAGIC + b"\0\0\0\rIHDR")
        for number in range(PICTURE_MUTANTS):
            data = rng.choice(heads) + bytes(rng.randrange(256) for _ in range(rng.randint(0, 48)))
            with self.subTest(mutant=number):
                self.read(data)


# --- Sign-in tokens ----------------------------------------------------------

B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
ODD = ("=", ".", " ", "+", "/", "\n", "\0", "%", "é", "а")


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def changed_part(rng, part):
    """One part of a token (base64url text) with its bytes changed and encoded again."""
    data = bytearray(unb64(part))
    choice = rng.randrange(6)
    if choice == 0 and data:
        for _ in range(rng.randint(1, 3)):
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
    elif choice == 1:
        del data[rng.randrange(len(data) + 1):]
    elif choice == 2:                               # longer or shorter at either end
        data = bytearray(rng.choice((b"\0", b"\0\0", b"\xff", b" "))) + data
    elif choice == 3:
        data += bytes(rng.choice((b"\0", b"\0\0", b"\xff", b" ", b"}", b"\n")))
    elif choice == 4 and data:
        del data[rng.randrange(len(data))]
    else:                                           # the same bytes again
        start = rng.randrange(len(data) + 1)
        end = min(len(data), start + rng.randint(1, 40))
        data[end:end] = data[start:end]
    return access_tests.b64(bytes(data))


def changed_token(rng, good):
    """One changed copy of a valid token."""
    parts = good.split(".")
    choice = rng.randrange(10)
    if choice <= 2:
        which = rng.randrange(3)
        parts[which] = changed_part(rng, parts[which])
        return ".".join(parts)
    if choice == 3:                                 # one character for another the alphabet has
        at = rng.randrange(len(good))
        return good[:at] + rng.choice(B64URL) + good[at + 1:]
    if choice == 4:                                 # the spare bits of a part's last character
        which = rng.randrange(3)
        parts[which] = parts[which][:-1] + rng.choice(B64URL)
        return ".".join(parts)
    if choice == 5:
        at = rng.randrange(len(good) + 1)
        return good[:at] + rng.choice(ODD) + good[at + rng.randrange(2):]
    if choice == 6:
        return good[:rng.randrange(len(good))]
    if choice == 7:                                 # a character dropped or added
        at = rng.randrange(len(good))
        return good[:at] + (rng.choice(B64URL) if rng.random() < 0.5 else "") + good[at + rng.randrange(2):]
    if choice == 8:                                 # parts again, moved or run together
        which, other = rng.randrange(3), rng.randrange(3)
        return rng.choice((
            ".".join(parts[:which] + [parts[which]] + parts[which:]),
            ".".join(parts[:which] + [parts[which] * 2] + parts[which + 1:]),
            ".".join(parts[:which] + [parts[other]] + parts[which + 1:]),
            ".".join(parts[:2] + [parts[2] + parts[2]]),
            good + "." + parts[2], good + good, "." + good, good + ".", good.replace(".", "..", 1),
        ))
    padded = "=" * rng.randint(1, 2)
    return rng.choice((good + padded, parts[0] + padded + "." + parts[1] + "." + parts[2],
                       good.upper(), good.lower(), good[::-1], " " + good, good + "\n"))


ODD_VALUES = (None, True, False, 0, -1, 1.5, 10 ** 30, "", " ", "x", [], {}, [[]], [None], {"a": 1},
              [access_tests.AUD], access_tests.AUD.upper(), "matt@example.com", "MATT@EXAMPLE.COM",
              "stranger@example.com", access_tests.NOW, access_tests.NOW + 30, access_tests.NOW - 30,
              float(access_tests.NOW + 3600), str(access_tests.NOW + 3600), f"https://{access_tests.TEAM}.cloudflareaccess.com")


def changed_claims(rng):
    """Claims with one to three values swapped for odd ones or dropped (to be signed as they are)."""
    claims = access_tests.claims()
    for _ in range(rng.randint(1, 3)):
        key = rng.choice(sorted(claims) + ["extra"])
        if rng.random() < 0.15:
            claims.pop(key, None)
        else:
            claims[key] = rng.choice(ODD_VALUES)
    return claims


class TokenMutationTests(unittest.TestCase):
    def setUp(self):
        self.fetch, self.clock = access_tests.Fetcher(), access_tests.Clock()
        self.verifier = access.Verifier(access_tests.TEAM, access_tests.AUD, fetch=self.fetch, clock=self.clock,
                                        profiles=lambda: access_tests.PROFILES)
        self.good = access_tests.token()
        self.identity = self.verifier.identify(self.good)

    def identify(self, text):
        """The identity text signs in as, or None when it's refused as usual (403)."""
        try:
            return self.verifier.identify(text)
        except access.AccessError as error:
            self.assertEqual(error.status, 403)
            self.assertTrue(error.message.strip())
            return None

    def test_changed_tokens_are_never_accepted(self):
        rng = random.Random(SEED)
        changed = 0
        for number in range(TOKEN_MUTANTS):
            text = changed_token(rng, self.good)
            self.clock.now += access.REFETCH_EVERY + 1      # so a changed key id asks for the keys again
            with self.subTest(mutant=number, token=text[:60]):
                if text == self.good:
                    self.assertEqual(self.identify(text), self.identity)
                else:
                    changed += 1
                    self.assertIsNone(self.identify(text))
            self.clock.now = access_tests.NOW
        self.assertGreater(changed, TOKEN_MUTANTS * 9 // 10)
        self.assertEqual(self.verifier.identify(self.good), self.identity)     # and the door still opens

    def test_every_spare_bit_of_the_signature(self):
        """A 256-byte signature's last base64url character carries only two
        bits: the fifteen other characters with those bits must not sign in."""
        head, body, signature = self.good.split(".")
        same = [c for c in B64URL if unb64(signature[:-1] + c) == unb64(signature)]
        self.assertEqual(len(same), 16)
        for last in same:
            text = f"{head}.{body}.{signature[:-1]}{last}"
            with self.subTest(last=last):
                if text == self.good:
                    self.assertEqual(self.identify(text), self.identity)
                else:
                    self.assertIsNone(self.identify(text))

    def test_every_single_bit_of_the_token(self):
        """Each bit of the header and claims flipped in turn, and a spread of the signature's."""
        parts = self.good.split(".")
        for which in range(3):
            data = unb64(parts[which])
            step = 1 if which < 2 else 7
            for bit in range(0, len(data) * 8, step):
                flipped = bytearray(data)
                flipped[bit // 8] ^= 1 << (bit % 8)
                changed = list(parts)
                changed[which] = access_tests.b64(bytes(flipped))
                with self.subTest(part=which, bit=bit):
                    self.assertIsNone(self.identify(".".join(changed)))

    def test_odd_claims_under_a_good_signature(self):
        """Claims Cloudflare would never send, signed all the same: refused as
        usual or, when the checks still hold, signed in as the email's profile."""
        rng = random.Random(SEED)
        accepted = 0
        issuer = f"https://{access_tests.TEAM}.cloudflareaccess.com"
        for number in range(CLAIM_MUTANTS):
            claims = changed_claims(rng)
            with self.subTest(mutant=number, claims=claims):
                identity = self.identify(access_tests.token(claims))
                if identity is None:
                    continue
                accepted += 1
                aud = claims.get("aud")
                auds = [aud] if isinstance(aud, str) else aud
                self.assertIn(access_tests.AUD, [a.lower() for a in auds if isinstance(a, str)])
                self.assertEqual(claims.get("iss"), issuer)
                self.assertNotIsInstance(claims["exp"], (bool, str))
                self.assertGreaterEqual(claims["exp"] + access.LEEWAY, access_tests.NOW)
                self.assertEqual(identity, {"profile": "matt", "remote": True,
                                            "email": profile_list.email_key(claims["email"])})
                self.assertEqual(identity["email"], "matt@example.com")
        self.assertGreater(accepted, 0)
        self.assertLess(accepted, CLAIM_MUTANTS)

    def test_claims_json_no_token_should_carry(self):
        head = access_tests.b64(json.dumps({"alg": "RS256", "kid": "k1"}).encode())
        bodies = (b"[]", b"null", b"7", b'"x"', b"", b"{", b"\xff\xfe", b"[" * 100_000, b'{"a":' * 100_000,
                  b'{"exp": ' + b"9" * 5000 + b"}", json.dumps(access_tests.claims()).encode() * 2,
                  json.dumps(access_tests.claims()).encode() + b"\0")
        for body in bodies:
            payload = access_tests.b64(body)
            signed = f"{head}.{payload}".encode("ascii")
            text = f"{head}.{payload}.{access_tests.b64(access_tests.sign(signed))}"
            if len(text) > access.MAX_TOKEN:
                # Longer than a token may be: also given straight to the claims' reader.
                with self.assertRaises((ValueError, RecursionError)):
                    access._json_part(payload)
            with self.subTest(body=body[:20]):
                self.assertIsNone(self.identify(text))


class SignatureMutationTests(unittest.TestCase):
    def test_changed_signatures_and_messages(self):
        rng = random.Random(SEED)
        message = b"header.claims"
        good = access_tests.sign(message)
        n, e = access_tests.N, access_tests.E
        self.assertTrue(access.rsa_sha256_valid(message, good, n, e))
        for number in range(SIGNATURE_MUTANTS):
            layout = ([0, len(good)], [])
            signature = rng.choice((flip_bits, truncate, splice))(rng, good, layout)
            with self.subTest(mutant=number):
                self.assertEqual(access.rsa_sha256_valid(message, signature, n, e), signature == good)
                other = flip_bits(rng, message, layout)
                self.assertEqual(access.rsa_sha256_valid(other, good, n, e), other == message)

    def test_signatures_of_other_lengths_and_values(self):
        message = b"header.claims"
        good = access_tests.sign(message)
        n, e = access_tests.N, access_tests.E
        value = int.from_bytes(good, "big")
        size = len(good)
        for signature in (b"", b"\0", good[1:], good[:-1], b"\0" + good, good + b"\0", good + good,
                          b"\0" * size, b"\0" * (size - 1) + b"\x01", b"\xff" * size,
                          n.to_bytes(size, "big"), (n - 1).to_bytes(size, "big"),
                          (value + n).to_bytes(size + 1, "big"),           # the same number, plus the modulus
                          (n - value).to_bytes(size, "big")):
            with self.subTest(signature=signature[:8].hex(), length=len(signature)):
                self.assertFalse(access.rsa_sha256_valid(message, signature, n, e))


if __name__ == "__main__":
    unittest.main()
