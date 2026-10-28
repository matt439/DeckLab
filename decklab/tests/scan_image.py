"""A synthetic card bottom line as a PNG, drawn with the standard library only.

test_scan's end-to-end test reads it with Windows' OCR engine, so no card scan
(copyrighted art) is committed: these are 5x7 block letters, white on black like
a modern card's frame, scaled up as a phone photo would show them.
"""
import struct
import zlib

GLYPHS = {
    "0": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    " ": ["00000"] * 7,
}


def png(lines, scale=6, margin=4):
    """PNG bytes of lines of text in GLYPHS' letters, one 8-bit grey pixel per dot."""
    width = max(len(line) for line in lines) * 6 + margin * 2
    height = len(lines) * 10 + margin * 2
    dots = [[0] * width for _ in range(height)]
    for row, line in enumerate(lines):
        for col, ch in enumerate(line):
            for y, bits in enumerate(GLYPHS[ch]):
                for x, bit in enumerate(bits):
                    if bit == "1":
                        dots[margin + row * 10 + y][margin + col * 6 + x] = 235
    # Each dot widened: repeat every pixel scale times across, every row scale times down.
    raw = b"".join(b"\0" + bytes(v for v in dots[y // scale] for _ in range(scale)) for y in range(height * scale))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
