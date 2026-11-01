"""Proposing printings from a photo of a card (E7-S32's recognition spike).

A modern card (2015 onwards) prints its collector number, rarity, set code and
language in the bottom-left corner: "R 0107" over "FDN • EN" since Foundations,
"0227 C" before it and "002/274 C" before 2023. Read that line, and the name at
the top, with an OCR engine the PC already has, and the card index turns them
into printings: the set code and number name one printing, and the name says
whether it's the right card. A card printed before the set code (2015) gives
only its name, so every paper printing of it is offered.

OCR: on Windows, Windows' own engine (Windows.Media.Ocr, part of Windows 10 and
11, through PowerShell; nothing to install), else Tesseract when it's on the
PATH; on Linux and macOS, Tesseract only (Debian and Ubuntu's tesseract-ocr
package, which brings its English data). Neither is a Python package and
nothing is fetched. Tesseract's TSV output is regrouped into lines in reading
order (_tsv_lines), as Windows' engine gives them. When no engine is on this
host, OcrUnavailable says so in one fixed sentence (NOT_SET_UP) and
engine_status() says why; propose() works on any text, so a phone's own text
reading or a typed line can feed it too. The findings are in
decklab/design/scanning-spike.md.

    python -m decklab.lib.scan PHOTO [PHOTO ...] [--json] [--engine auto|windows|tesseract]
    python -m decklab.lib.scan --text FILE      # lines already read, one per line
    python -m decklab.lib.scan PHOTO --tokens   # a token card: propose token, emblem and reminder faces
    python -m decklab.lib.scan --status [--json] # whether this PC has an engine (exit 1 if not)
"""
import argparse
import base64
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

from decklab.lib import cards

OCR_TIMEOUT = 60            # seconds; Windows' engine takes about one on a phone photo
MAX_NAME_ONLY = 12          # printings offered when only the name could be read
NAME_LINES = 2              # the card's name is one of the first lines read (a type line may come first)
TOKEN_CUTOFF = 0.8          # how close a misread token name must be to a face name to be proposed

# Rarity letters on the bottom line: common, uncommon, rare, mythic, special,
# land (basic), token, promo.
RARITIES = "CURMSLTP"
# The language as printed (JP, not JA; CS and CT for Chinese) -> Scryfall's code.
LANGUAGES = {"EN": "en", "DE": "de", "FR": "fr", "IT": "it", "ES": "es", "SP": "es", "PT": "pt",
             "JP": "ja", "JA": "ja", "KO": "ko", "KR": "ko", "RU": "ru", "CS": "zhs", "CT": "zht"}
# Letters OCR reads for digits in a collector number, and the reverse in a set code.
_DIGIT_FOR = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1", "i": "1"})
_SET_SWAPS = {"0": "OD", "O": "0D", "D": "O0", "1": "IL", "I": "1L", "L": "I1", "5": "S", "S": "5",
              "8": "B", "B": "8", "2": "Z", "Z": "2"}

_NUM = r"[0-9OoDQIl|i]{1,4}"
_RARITY_FIRST = re.compile(rf"^([{RARITIES}])\s+({_NUM}[a-z]?)\b", re.IGNORECASE)
_NUMBER_FIRST = re.compile(rf"^({_NUM}[a-z]?)(?:\s*/\s*({_NUM}))?(?:\s+([{RARITIES}]))?\b", re.IGNORECASE)
# Between the set code and the language: a dot, which OCR may read as another mark ("-", "+", "°",
# "»"), as a lone "e" or "o" (only with spaces round it) or not at all. Only a star makes the card foil.
_SET_LINE = re.compile(r"^([A-Z0-9]{3,5})(?:\s*[•·*★☆.,+°»\-]\s*|\s+[eo]\s+|\s*)([A-Z]{2})\b")
_STARS = "★☆*"
NOT_SET_UP = "Scanning isn't set up on this server. Type the card's name instead."


class OcrUnavailable(Exception):
    """No OCR engine could read the photo; the message says why in plain words. detail, when
    given, is fix-it text for the PC's command line and doctor, never sent to a page."""

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = detail


class OcrMissing(OcrUnavailable):
    """The engine isn't on this host at all (rather than there and failing on the photo)."""


def _clean(line):
    return " ".join(unicodedata.normalize("NFKC", str(line)).split())


def _number(token):
    """A collector number as Scryfall writes it: confusions fixed, leading zeros dropped."""
    fixed = token.translate(_DIGIT_FOR)
    digits = fixed.rstrip("abcdefghijklmnopqrstuvwxyz")
    if not digits.isdigit():
        return None
    return (digits.lstrip("0") or "0") + fixed[len(digits):]


def read_lines(lines):
    """What the text read off a card says: the lines that may be its name, the
    collector numbers and set codes found, a foil star and the language.
    Nothing is checked against the card index here."""
    found = {"names": [], "numbers": [], "sets": [], "foil": False, "language": ""}
    for raw in lines:
        line = _clean(raw)
        if not line:
            continue
        m = _RARITY_FIRST.match(line) or _NUMBER_FIRST.match(line)
        # A rarity makes it a number line; a total too, from three digits ("002/274"),
        # so that power and toughness ("2/4") and "Old Man of the Sea" aren't.
        if m and (m.re is _RARITY_FIRST or m.group(3) or (m.group(2) and len(m.group(1)) >= 3)):
            number = _number(m.group(2) if m.re is _RARITY_FIRST else m.group(1))
            if number:
                if number not in found["numbers"]:
                    found["numbers"].append(number)
                continue
        m = _SET_LINE.match(line)
        if m and m.group(2) in LANGUAGES:
            if m.group(1) not in found["sets"]:
                found["sets"].append(m.group(1))
            found["language"] = found["language"] or LANGUAGES[m.group(2)]
            found["foil"] = found["foil"] or any(star in line[:12] for star in _STARS)
            continue
        if any(ch.isalpha() for ch in line) and len(line) <= 60:
            found["names"].append(line)
    return found


def _set_variants(code):
    """The set code read, then each spelling one OCR confusion away, lowercase."""
    code = code.lower()
    seen = [code]
    for i, ch in enumerate(code.upper()):
        for swap in _SET_SWAPS.get(ch, ""):
            variant = (code[:i] + swap + code[i + 1:]).lower()
            if variant not in seen:
                seen.append(variant)
    return seen


def _finish(printing, foil):
    finishes = printing.get("finishes") or []
    if foil and "foil" in finishes:
        return "foil"
    if "nonfoil" in finishes:
        return "nonfoil"
    return finishes[0] if finishes else ""


def _proposal(printing, how, read):
    return {"name": printing["name"], "set": printing["set"], "collector_number": printing["collector_number"],
            "set_name": printing.get("set_name") or printing["set"].upper(),
            "finish": _finish(printing, read["foil"]), "language": read["language"], "how": how}


def _paper(printing):
    return (printing is not None and not printing.get("digital")
            and "paper" in (printing.get("games") or ("paper",)))


def propose(lines):
    """Printings the text read off one card may be, best first, from the card index.

    Each proposal has name, set, collector_number, set_name, finish (foil only
    when a star was read), language ("" when unread) and how: "name and number"
    (the number read, and the set code when one was, name a printing of the
    card whose name was read; several of them when reprints share the number
    and no set code agreed, so none is certain),
    "number" (they name a printing, but the name wasn't read or differs) or
    "name" (only the name was read: every paper printing, newest first).
    Raises FileNotFoundError or RuntimeError without a usable card index."""
    read = read_lines(lines)
    name = None
    for line in read["names"][:NAME_LINES]:     # lower down, "Vigilance" is a keyword, not the card
        name = cards.resolve(line)
        if name:
            break
    if name is None and read["names"]:
        # The name is the card's first line; OCR may misread a letter ("Éowynt Lady of Rohan").
        close = cards.close_names(read["names"][0], limit=1)
        name = close[0] if close else None
    confirmed, numbered = [], []
    for code in read["sets"]:
        for variant in _set_variants(code):
            for number in read["numbers"]:
                printing = cards.printing(variant, number)
                if not _paper(printing):
                    continue
                exact = cards.resolve(printing["name"])
                (confirmed if name and exact == name else numbered).append(
                    _proposal(printing, "name and number" if name and exact == name else "number", read))
            if confirmed:
                break       # this spelling named the card read: its look-alikes aren't wanted
    if name and not confirmed:
        # No set code agreed with the name (or none was read): the name's printings,
        # those with a number read first ("322" alone picks Path of Ancestry's BLC printing).
        shown = {(p["set"], p["collector_number"]) for p in numbered}
        others = [p for p in cards.printings(name) if _paper(p) and (p["set"], p["collector_number"]) not in shown]
        confirmed = [_proposal(p, "name and number", read) for p in others if p["collector_number"] in read["numbers"]]
        rest = [p for p in others if p["collector_number"] not in read["numbers"]]
        numbered += [_proposal(p, "name", read) for p in rest[:MAX_NAME_ONLY]]
    proposals = confirmed + numbered
    return {"read": dict(read, name=name), "proposals": proposals, "message": _message(read, name, proposals)}


def _token_name(read):
    """The token, emblem or reminder face name read at the top of a token card, or None: one of its
    first lines exactly (a double-faced token's full name gives its first face), else one close to
    the first line (OCR may misread a letter)."""
    name = None
    for line in read["names"][:NAME_LINES]:
        name = cards.token_face(line)
        if name:
            break
    if name is None and read["names"]:
        names = {cards.fold(n): n for n in cards.token_face_names()}
        close = difflib.get_close_matches(cards.fold(read["names"][0]), list(names), n=1, cutoff=TOKEN_CUTOFF)
        name = names[close[0]] if close else None
    return name.split(" // ")[0] if name else None


def _token_printing(code, number):
    """(set code, face names) of the token printing the set code and number read name: a token card
    prints its main set's code ("BLB"), which Scryfall files under "t" + the code ("tblb")."""
    for candidate in (f"t{code}", code):
        found = cards.token_faces_at(candidate, number)
        if found is not None:
            return candidate, found[1]
    return None, None


def propose_tokens(lines):
    """The token cards the text read off one card may be, best first, from the card index's token,
    emblem and reminder faces (the Tokens page's Scan token cards).

    Each proposal has front (a face name), faces (the printing's face names, or [front] without
    one), set and collector_number ("" when no printing was read), set_name and how: "name and
    number" (the set code and number read name a token printing with the face read), "number"
    (they name a token printing, but the face read isn't on it, or none was read) or "name" (only
    the face was read: no printing is proposed, never one guessed from the name). Nothing about
    the back of the card is proposed: a double-faced printing's faces are only offered. Raises
    FileNotFoundError or RuntimeError without a usable card index."""
    read = read_lines(lines)
    name = _token_name(read)
    confirmed, numbered, seen = [], [], set()
    for code in read["sets"]:
        for variant in _set_variants(code):
            for number in read["numbers"]:
                set_code, faces = _token_printing(variant, number)
                if set_code is None or (set_code, number) in seen:
                    continue
                seen.add((set_code, number))
                folded = [cards.fold(face) for face in faces]
                matches = name is not None and cards.fold(name) in folded
                front = faces[folded.index(cards.fold(name))] if matches else faces[0]
                printing = cards.printing(set_code, number) or {}
                (confirmed if matches else numbered).append(
                    {"front": front, "faces": list(faces), "set": set_code, "collector_number": number,
                     "set_name": printing.get("set_name") or set_code.upper(),
                     "how": "name and number" if matches else "number"})
            if confirmed:
                break
    proposals = confirmed + numbered
    if name and not confirmed:
        proposals.insert(0, {"front": name, "faces": [name], "set": "", "collector_number": "", "set_name": "",
                             "how": "name"})
    return {"read": dict(read, name=name), "proposals": proposals, "message": _token_message(read, name, proposals)}


def _token_message(read, name, proposals):
    if not proposals:
        if read["numbers"] or read["sets"]:
            return "The bottom line was read but names no token printing Deck Lab knows: type the token's name instead."
        return "No token name or set code could be read: try a sharper photo, or type the token's name."
    first = proposals[0]
    if first["how"] == "name and number":
        return f"Read {first['front']}, {first['set'].upper()} {first['collector_number']}."
    if first["how"] == "number":
        return "The set code and number name a token printing, but not the name read: check it's this card."
    if len(proposals) > 1:
        return f"Read {name}, but the set code and number name another token: choose which this card is."
    return f"Read {name}; its printing wasn't read, so none is recorded unless you choose one."


def _message(read, name, proposals):
    if not proposals:
        if read["numbers"] or read["sets"]:
            return "The bottom line was read but names no printing Deck Lab knows: type the card's name instead."
        return "No card name or set code could be read: try a sharper photo, or type the card's name."
    if proposals[0]["how"] == "name and number":
        if len(proposals) > 1 and proposals[1]["how"] == "name and number":
            # Reprints often share a number: without the set code read, which one isn't known.
            return f"Read {name}, but more than one printing has that number: choose the printing."
        return f"Read {name}, {proposals[0]['set'].upper()} {proposals[0]['collector_number']}."
    if proposals[0]["how"] == "number":
        return "The set code and number name a printing, but the name didn't match: check it's this card."
    return f"Read {name}, but not its set code: choose the printing."


# --- OCR engines -----------------------------------------------------------

# Windows.Media.Ocr through Windows PowerShell 5.1, whose WinRT bridge needs no
# install. The photo's path comes in an environment variable, not the command
# line, so no quoting can break it; each line read is printed on its own. With
# stderr redirected, PowerShell writes progress and error records as one line of
# CLIXML, so progress is silenced and every failure is caught and told as one
# plain sentence instead.
_WINDOWS_OCR = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $null = $task.Wait(-1); $task.Result }
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { [Console]::Error.WriteLine('no OCR language installed'); exit 3 }
if (-not $env:DECKLAB_SCAN_IMAGE) { exit 0 }
try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($env:DECKLAB_SCAN_IMAGE)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
} catch { [Console]::Error.WriteLine("the photo couldn't be opened"); exit 4 }
try {
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
} catch { [Console]::Error.WriteLine("it isn't a picture Windows can open (JPEG or PNG)"); exit 5 }
try {
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
} catch { [Console]::Error.WriteLine('the OCR engine failed on it (a picture over 10,000 pixels across is too big)'); exit 6 }
foreach ($line in $result.Lines) { [Console]::Out.WriteLine($line.Text) }
"""


def _powershell():
    if sys.platform != "win32":
        return None
    return shutil.which("powershell") or shutil.which("powershell.exe")


def _run(command, env=None, explain=None):
    """The engine's stdout as text. explain(stderr) gives the plain reason a failed run names
    (None for none); without it, the last plain stderr line is the reason."""
    try:
        done = subprocess.run(command, capture_output=True, timeout=OCR_TIMEOUT, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise OcrUnavailable("Reading the photo took too long.") from None
    except OSError as e:
        raise OcrUnavailable(f"The OCR engine couldn't start ({e.strerror or e}).") from None
    if done.returncode != 0:
        stderr = done.stderr.decode("utf-8", "replace")
        if explain is not None:
            reason = explain(stderr)
        else:
            # Only plain lines: PowerShell's CLIXML records (a "#< CLIXML" line, then
            # one "<Objs ...>" line) are never shown.
            error = [line.strip() for line in stderr.splitlines()
                     if line.strip() and not line.lstrip().startswith(("#< CLIXML", "<Objs", "<"))]
            reason = error[-1] if error else None
        reason = (reason or "").rstrip(". ")
        raise OcrUnavailable("The OCR engine couldn't read the photo" + (f": {reason}." if reason else "."))
    return done.stdout.decode("utf-8-sig", "replace")


def windows_ocr(path):
    """The lines Windows' OCR engine reads in the photo at path."""
    shell = _powershell()
    if shell is None:
        raise OcrMissing("Windows' OCR engine is only on Windows.")
    encoded = base64.b64encode(_WINDOWS_OCR.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, DECKLAB_SCAN_IMAGE=str(Path(path).resolve()) if path else "")
    output = _run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-EncodedCommand", encoded], env=env)
    return [line for line in output.splitlines() if line.strip()]


# Tesseract (the tesseract-ocr package): English, sparse text (a card's lines are scattered over
# its art), TSV output so the words' positions rebuild the lines. Tesseract 4 and 5 already try
# each line inverted (white on black, as a card's bottom line is). One thread, so a scan doesn't
# fight Forge's workers for every core.
TESSERACT_ARGS = ("stdout", "-l", "eng", "--psm", "11", "tsv")
MIN_CONF = 30               # Tesseract's word confidence (0-100) below which a word is art, not text
LINE_GAP = 2                # word heights apart that two pieces of one line may be
_MARKS = "•·★☆*"            # marks kept though they're no letter or digit: a set line's dot or foil star
_TSV_KEYS = ("level", "page_num", "block_num", "par_num", "line_num", "left", "top", "width", "height", "conf", "text")


def _tesseract():
    return shutil.which("tesseract")


def _tesseract_env():
    return dict(os.environ, OMP_THREAD_LIMIT="1")


def _tesseract_error(stderr):
    """The plain reason a failed Tesseract run names, or None: never its own (Leptonica's) words."""
    if "Failed loading language" in stderr or "Error opening data file" in stderr:
        return "Tesseract has no English language data (install tesseract-ocr-eng)"
    if any(word in stderr for word in ("pixRead", "Unknown format", "Unsupported image type", "image file not found")):
        return "it isn't a picture Tesseract can open (JPEG or PNG)"
    return None


def _same_line(a, b):
    """Whether two pieces of text sit on one line: their middles within half a word's height,
    and at most LINE_GAP word heights apart side by side."""
    height = max(a["bottom"] - a["top"], b["bottom"] - b["top"], 1)
    middles = abs((a["top"] + a["bottom"]) - (b["top"] + b["bottom"])) / 2
    gap = max(a["left"], b["left"]) - min(a["right"], b["right"])
    return middles <= height / 2 and gap <= LINE_GAP * height


def _tsv_lines(text):
    """The lines in Tesseract's TSV output, in reading order, as Windows' engine gives them.

    Its words (level 5) of confidence MIN_CONF or more, with a letter, digit or one of _MARKS,
    are put in Tesseract's own lines (block, paragraph and line numbers); lines side by side
    are joined again (sparse mode splits "R" from "0227" and "FDN" from "EN"), each line's
    words left to right, and the lines sorted top to bottom, then left to right, so the card's
    name comes first and its bottom line last. Raises OcrUnavailable for output that isn't TSV."""
    rows = text.splitlines()
    header = next((i for i, row in enumerate(rows) if row.split("\t")[:1] == ["level"]), None)
    if header is None:
        if any(row.strip() for row in rows):
            raise OcrUnavailable("The OCR engine couldn't read the photo.")
        return []
    at = {name: i for i, name in enumerate(rows[header].split("\t"))}
    if any(key not in at for key in _TSV_KEYS):
        raise OcrUnavailable("The OCR engine couldn't read the photo.")
    groups = {}
    for row in rows[header + 1:]:
        cells = row.split("\t")
        try:
            if cells[at["level"]] != "5":
                continue
            word = _clean(cells[at["text"]] if at["text"] < len(cells) else "")
            conf = float(cells[at["conf"]])
            left, top, width, height = (int(cells[at[key]]) for key in ("left", "top", "width", "height"))
            key = tuple(cells[at[name]] for name in ("page_num", "block_num", "par_num", "line_num"))
        except (IndexError, ValueError):
            continue
        if conf < MIN_CONF or not word or not any(ch.isalnum() or ch in _MARKS for ch in word):
            continue
        line = groups.setdefault(key, {"left": left, "top": top, "right": left + width, "bottom": top + height,
                                       "words": []})
        line.update(left=min(line["left"], left), top=min(line["top"], top),
                    right=max(line["right"], left + width), bottom=max(line["bottom"], top + height))
        line["words"].append((left, word))
    lines = []
    for piece in sorted(groups.values(), key=lambda g: (g["left"], g["top"])):
        line = next((line for line in lines if _same_line(line, piece)), None)
        if line is None:
            lines.append({**piece, "words": list(piece["words"])})
            continue
        line.update(left=min(line["left"], piece["left"]), top=min(line["top"], piece["top"]),
                    right=max(line["right"], piece["right"]), bottom=max(line["bottom"], piece["bottom"]))
        line["words"] += piece["words"]
    lines.sort(key=lambda line: (line["top"], line["left"]))
    return [" ".join(word for _, word in sorted(line["words"], key=lambda w: w[0])) for line in lines]


def tesseract_ocr(path):
    """The lines Tesseract reads in the photo at path, when it's installed."""
    exe = _tesseract()
    if exe is None:
        raise OcrMissing("Tesseract isn't installed.")
    return _tsv_lines(_run([exe, str(path), *TESSERACT_ARGS], env=_tesseract_env(), explain=_tesseract_error))


ENGINES = {"windows": windows_ocr, "tesseract": tesseract_ocr}


def platform_engines(platform=None):
    """The engines "auto" tries on this platform, in order: Windows' own, then Tesseract on
    Windows; only Tesseract elsewhere."""
    return ("windows", "tesseract") if (platform or sys.platform) == "win32" else ("tesseract",)


def ocr(path, engine="auto"):
    """The lines read in the photo at path, by the engine named or the first one
    that works. Raises OcrUnavailable naming each engine's problem when one is here
    but failed; OcrMissing with NOT_SET_UP (its detail naming each) when none is."""
    if not Path(path).is_file():
        raise OcrUnavailable(f"No photo at {path}.")
    names = platform_engines() if engine == "auto" else [engine]
    problems, failed = [], False
    for name in names:
        try:
            return ENGINES[name](path)
        except OcrMissing as e:
            problems.append(str(e))
        except OcrUnavailable as e:
            problems.append(str(e))
            failed = True
    if not failed:
        raise OcrMissing(NOT_SET_UP, detail=" ".join(problems))
    raise OcrUnavailable(" ".join(problems) + " Type the card's name instead.")


# --- Whether this server can scan ------------------------------------------

STATUS_TTL = 60             # seconds engine_status() is kept, so installing Tesseract shows without a restart
LIST_TIMEOUT = 5            # seconds `tesseract --list-langs` may take
_status = {"at": None, "value": None}
_status_lock = threading.Lock()


def _tesseract_languages(exe):
    """The language data Tesseract has (a set of codes), or None when it didn't answer."""
    try:
        done = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=LIST_TIMEOUT,
                              env=_tesseract_env(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    # Its list ("List of available languages ..." then a code a line) is on stdout, or stderr before 4.1.
    text = (done.stdout + b"\n" + done.stderr).decode("utf-8", "replace")
    return {line.strip() for line in text.splitlines() if line.strip() and " " not in line.strip()}


def status_detail(reason, platform=None):
    """Fix-it text for engine_status's reason, for the PC's command line and doctor only."""
    windows = (platform or sys.platform) == "win32"
    return {
        "ready": None,
        "missing": ("Windows' OCR engine needs Windows PowerShell, and Tesseract isn't installed." if windows
                    else "Tesseract isn't installed: install the tesseract-ocr package (sudo apt install tesseract-ocr)."),
        "no_language": "Tesseract has no English language data: install the tesseract-ocr-eng package.",
        "unusable": "Tesseract is installed but didn't answer: check that tesseract --list-langs runs.",
    }.get(reason, "The OCR engine couldn't be checked.")


def _probe():
    problem = None
    for name in platform_engines():
        if name == "windows":
            if _powershell():
                return {"engine": "windows", "available": True, "reason": "ready"}
            continue
        exe = _tesseract()
        if exe is None:
            continue
        languages = _tesseract_languages(exe)
        if languages is None:
            problem = problem or "unusable"
        elif "eng" not in languages:
            problem = problem or "no_language"
        else:
            return {"engine": "tesseract", "available": True, "reason": "ready"}
    return {"engine": None, "available": False, "reason": problem or "missing"}


def engine_status(refresh=False):
    """{engine ("windows", "tesseract" or None), available, reason ("ready", "missing",
    "no_language" or "unusable"), detail (status_detail's, None when ready)}: whether "auto"
    has an engine to read photos with on this server. Cheap checks only (the PATH, and
    Tesseract's language list once), kept STATUS_TTL seconds; nothing is read or written.
    Only available is ever sent to a page: the rest names the PC's software."""
    now = time.monotonic()
    with _status_lock:
        if not refresh and _status["value"] is not None and now - _status["at"] < STATUS_TTL:
            return dict(_status["value"])
    try:
        value = _probe()
    except Exception:           # noqa: BLE001 - a broken check is "can't scan", never a failed page
        value = {"engine": None, "available": False, "reason": "unusable"}
    value["detail"] = status_detail(value["reason"])
    with _status_lock:
        _status.update(at=now, value=dict(value))
    return value


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.scan",
                                     description="Propose printings from photos of cards (a spike, E7-S32).")
    parser.add_argument("photos", nargs="*", help="photos of single cards (JPEG or PNG)")
    parser.add_argument("--text", help="a file of lines already read off one card, instead of a photo")
    parser.add_argument("--engine", choices=("auto", *ENGINES), default="auto")
    parser.add_argument("--json", action="store_true", help="print the answers as JSON")
    parser.add_argument("--tokens", action="store_true", help="the photos are of token cards: propose token faces")
    parser.add_argument("--status", action="store_true", help="say whether this PC has an OCR engine (exit 1 if not)")
    args = parser.parse_args(argv)
    if args.status:
        found = engine_status(refresh=True)
        if args.json:
            print(json.dumps(found, indent=1))
        else:
            engine = {"windows": "Windows' own", "tesseract": "Tesseract's"}.get(found["engine"], found["engine"])
            print(f"Photo scanning is set up: {engine} OCR engine reads the photos." if found["available"] else
                  f"Photo scanning isn't set up. {found['detail']}")
        return 0 if found["available"] else 1
    if not args.photos and not args.text:
        parser.error("give a photo or --text FILE")
    jobs = [(args.text, None)] if args.text else [(photo, args.engine) for photo in args.photos]
    answers, status = [], 0
    for source, engine in jobs:
        try:
            lines = (Path(source).read_text(encoding="utf-8-sig").splitlines() if engine is None
                     else ocr(source, engine))
        except (OcrUnavailable, OSError) as e:
            answers.append({"source": source, "error": str(e),
                            **({"detail": e.detail} if getattr(e, "detail", None) else {})})
            status = 1
            continue
        try:
            answers.append(dict((propose_tokens if args.tokens else propose)(lines), source=source, lines=lines))
        except (FileNotFoundError, RuntimeError) as e:      # no card index yet
            print(e, file=sys.stderr)
            return 1
    if args.json:
        print(json.dumps(answers, indent=1, ensure_ascii=False))
        return status
    for answer in answers:
        print(f"{answer['source']}:")
        if "error" in answer:
            print(f"  {answer['error']}")
            if answer.get("detail"):
                print(f"  {answer['detail']}")
            continue
        print(f"  read: {' | '.join(answer['lines']) or '(nothing)'}")
        print(f"  {answer['message']}")
        for p in answer["proposals"]:
            if args.tokens:
                printing = f" ({p['set'].upper()}) {p['collector_number']}" if p["set"] else ""
                print(f"  - {p['front']}{printing}  [{p['how']}]")
                continue
            print(f"  - {p['name']} ({p['set'].upper()}) {p['collector_number']} {p['finish']}"
                  f"{' ' + p['language'] if p['language'] else ''}  [{p['how']}]")
    return status


if __name__ == "__main__":
    sys.exit(main())
