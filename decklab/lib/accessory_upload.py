"""Bounded local accessory pictures, decoded only as part of an atomic row save.

The browser keeps the preview locally. These bytes are never staged, fetched
from another service, or written until accessory.add/edit saves the row too.
"""
import base64
import binascii
import struct
import zlib

from decklab.lib import accessory_fetch
from decklab.lib.api.common import ApiError

MAX_BASE64 = 4 * ((accessory_fetch.MAX_IMAGE + 2) // 3)
TOO_BIG = "Choose a smaller picture: JPEG, PNG and WebP pictures can be at most 4 MiB."
INVALID = "That picture is incomplete or damaged. Choose a JPEG, PNG or WebP picture."


def _png(data):
    offset, first, pixels = 8, True, False
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        end = offset + length + 12
        if end > len(data):
            return False
        kind, payload = data[offset + 4:offset + 8], data[offset + 8:end - 4]
        if zlib.crc32(kind + payload) != struct.unpack_from(">I", data, end - 4)[0]:
            return False
        if first and (kind != b"IHDR" or length != 13):
            return False
        if not first and kind == b"IHDR":
            return False
        first = False
        pixels |= kind == b"IDAT" and bool(length)
        if kind == b"IEND":
            return not length and pixels and end == len(data)
        offset = end
    return False


def _jpeg(data):
    if not data.endswith(b"\xff\xd9"):
        return False
    offset = 2
    while offset < len(data) - 2:
        if data[offset] != 0xFF:
            return False
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            return False
        marker = data[offset]
        offset += 1
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data) or marker in (0xD8, 0xD9):
            return False
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data) - 2:
            return False
        if marker == 0xDA:
            return offset + length < len(data) - 2
        offset += length
    return False


def _webp_chunks(data, offset, frame=False):
    pixels = False
    while offset + 8 <= len(data):
        kind = data[offset:offset + 4]
        length = struct.unpack_from("<I", data, offset + 4)[0]
        end = offset + 8 + length
        following = end + (length % 2)
        if following > len(data):
            return False
        if kind == b"VP8X" and length != 10:
            return False
        if kind in (b"VP8 ", b"VP8L"):
            if length < (10 if kind == b"VP8 " else 5):
                return False
            pixels = True
        if kind == b"ANMF":
            if frame or length < 16 or not _webp_chunks(data[offset + 24:end], 0, frame=True):
                return False
            pixels = True
        offset = following
    return pixels and offset == len(data)


def decode(value):
    """Strict base64 to checked JPEG/PNG/WebP bytes; user errors never persist anything."""
    if not isinstance(value, str) or not value:
        raise ApiError(400, "upload must be the picture's base64 bytes.")
    if len(value) > MAX_BASE64:
        raise ApiError(413, TOO_BIG)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError(400, "The picture upload isn't valid base64. Choose the picture again.") from None
    if base64.b64encode(data).decode("ascii") != value:
        raise ApiError(400, "The picture upload isn't valid base64. Choose the picture again.")
    if len(data) > accessory_fetch.MAX_IMAGE:
        raise ApiError(413, TOO_BIG)
    try:
        ext, _, _ = accessory_fetch.check_image(data)
    except ApiError as error:
        raise ApiError(400, error.message) from None
    complete = _png(data) if ext == "png" else _jpeg(data) if ext == "jpg" else (
        len(data) >= 12 and struct.unpack_from("<I", data, 4)[0] + 8 == len(data) and _webp_chunks(data, 12))
    if not complete:
        raise ApiError(400, INVALID)
    return data
