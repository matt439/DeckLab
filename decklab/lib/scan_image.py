"""A synthetic card bottom line as a PNG, drawn with the standard library only.

The scan tests' end-to-end checks and the smoke test's scan step (decklab/smoke.py)
read it with the PC's OCR engine, so no card scan (copyrighted art) is committed:
these are 5x7 block letters, white on black like a modern card's frame, scaled up
as a phone photo would show them and softened at the edges as a photo's are (Tesseract
5 misreads hard-edged block letters: "FOHM EH" for "FDN EN").
"""
import struct
import zlib

GLYPHS = {
    "0": ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    "D": ["11100", "10010", "10001", "10001", "10001", "10010", "11100"],     # not to be read as O
    "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    "N": ["10001", "11001", "10101", "10011", "10001", "10001", "10001"],
    "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    " ": ["00000"] * 7,
}


def _soften(rows, radius):
    """rows (lists of 0-1 floats) box-blurred radius pixels each way, across then down."""
    def across(row):
        sums = [0.0]
        for v in row:
            sums.append(sums[-1] + v)
        n = len(row)
        return [(sums[min(n, x + radius + 1)] - sums[max(0, x - radius)]) / (min(n, x + radius + 1) - max(0, x - radius))
                for x in range(n)]
    rows = [across(row) for row in rows]
    columns = [across(list(column)) for column in zip(*rows)]
    return [list(row) for row in zip(*columns)]


def png(lines, scale=4, margin=4, soften=None):
    """PNG bytes of lines of text in GLYPHS' letters, each dot scale pixels square, 8-bit grey.
    soften: the edges' blur in pixels (default scale // 2; 0 for hard edges)."""
    width = max(len(line) for line in lines) * 6 + margin * 2
    height = len(lines) * 10 + margin * 2
    dots = [[0] * width for _ in range(height)]
    for row, line in enumerate(lines):
        for col, ch in enumerate(line):
            for y, bits in enumerate(GLYPHS[ch]):
                for x, bit in enumerate(bits):
                    if bit == "1":
                        dots[margin + row * 10 + y][margin + col * 6 + x] = 1
    # Each dot widened: repeat every pixel scale times across, every row scale times down.
    pixels = [[float(v) for v in dots[y // scale] for _ in range(scale)] for y in range(height * scale)]
    radius = scale // 2 if soften is None else soften
    if radius:
        pixels = _soften(pixels, radius)
    raw = b"".join(b"\0" + bytes(round(235 * v) for v in row) for row in pixels)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))
