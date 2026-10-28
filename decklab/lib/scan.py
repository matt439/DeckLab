"""Proposing printings from a photo of a card (E7-S32's recognition spike).

A modern card (2015 onwards) prints its collector number, rarity, set code and
language in the bottom-left corner: "R 0107" over "FDN • EN" since Foundations,
"0227 C" before it and "002/274 C" before 2023. Read that line, and the name at
the top, with an OCR engine the PC already has, and the card index turns them
into printings: the set code and number name one printing, and the name says
whether it's the right card. A card printed before the set code (2015) gives
only its name, so every paper printing of it is offered.

OCR: Windows' own engine (Windows.Media.Ocr, part of Windows 10 and 11, through
PowerShell; nothing to install), else Tesseract when it's on the PATH. Neither
is a Python package and nothing is fetched. Without one, OcrUnavailable says so
in plain words; propose() works on any text, so a phone's own text reading or a
typed line can feed it too. The findings are in decklab/design/scanning-spike.md.

    python -m decklab.lib.scan PHOTO [PHOTO ...] [--json] [--engine auto|windows|tesseract]
    python -m decklab.lib.scan --text FILE      # lines already read, one per line
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

from decklab.lib import cards

OCR_TIMEOUT = 60            # seconds; Windows' engine takes about one on a phone photo
MAX_NAME_ONLY = 12          # printings offered when only the name could be read
NAME_LINES = 2              # the card's name is one of the first lines read (a type line may come first)

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
_SET_LINE = re.compile(r"^([A-Z0-9]{3,5})\s*(?:[•·*★☆.,]\s*)?([A-Z]{2})\b")
_STARS = "★☆*"


class OcrUnavailable(Exception):
    """No OCR engine could read the photo; the message says why in plain words."""


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
    card whose name was read),
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


def _message(read, name, proposals):
    if not proposals:
        if read["numbers"] or read["sets"]:
            return "The bottom line was read but names no printing Deck Lab knows: type the card's name instead."
        return "No card name or set code could be read: try a sharper photo, or type the card's name."
    if proposals[0]["how"] == "name and number":
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


def _run(command, env=None):
    try:
        done = subprocess.run(command, capture_output=True, timeout=OCR_TIMEOUT, env=env,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise OcrUnavailable("Reading the photo took too long.") from None
    except OSError as e:
        raise OcrUnavailable(f"The OCR engine couldn't start ({e.strerror or e}).") from None
    if done.returncode != 0:
        # Only plain lines: PowerShell's CLIXML records (a "#< CLIXML" line, then
        # one "<Objs ...>" line) are never shown.
        error = [line.strip() for line in done.stderr.decode("utf-8", "replace").splitlines()
                 if line.strip() and not line.lstrip().startswith(("#< CLIXML", "<Objs", "<"))]
        raise OcrUnavailable("The OCR engine couldn't read the photo"
                             + (f": {error[-1]}." if error else "."))
    return [line for line in done.stdout.decode("utf-8-sig", "replace").splitlines() if line.strip()]


def windows_ocr(path):
    """The lines Windows' OCR engine reads in the photo at path."""
    shell = _powershell()
    if shell is None:
        raise OcrUnavailable("Windows' OCR engine is only on Windows.")
    encoded = base64.b64encode(_WINDOWS_OCR.encode("utf-16-le")).decode("ascii")
    env = dict(os.environ, DECKLAB_SCAN_IMAGE=str(Path(path).resolve()) if path else "")
    return _run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", encoded], env=env)


def tesseract_ocr(path):
    """The lines Tesseract reads in the photo at path, when it's installed."""
    exe = shutil.which("tesseract")
    if exe is None:
        raise OcrUnavailable("Tesseract isn't installed.")
    return _run([exe, str(path), "stdout", "--psm", "11"])


ENGINES = {"windows": windows_ocr, "tesseract": tesseract_ocr}


def ocr(path, engine="auto"):
    """The lines read in the photo at path, by the engine named or the first one
    that works. Raises OcrUnavailable, naming each engine's problem."""
    if not Path(path).is_file():
        raise OcrUnavailable(f"No photo at {path}.")
    names = list(ENGINES) if engine == "auto" else [engine]
    problems = []
    for name in names:
        try:
            return ENGINES[name](path)
        except OcrUnavailable as e:
            problems.append(str(e))
    raise OcrUnavailable(" ".join(problems) + " Type the card's name instead.")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m decklab.lib.scan",
                                     description="Propose printings from photos of cards (a spike, E7-S32).")
    parser.add_argument("photos", nargs="*", help="photos of single cards (JPEG or PNG)")
    parser.add_argument("--text", help="a file of lines already read off one card, instead of a photo")
    parser.add_argument("--engine", choices=("auto", *ENGINES), default="auto")
    parser.add_argument("--json", action="store_true", help="print the answers as JSON")
    args = parser.parse_args(argv)
    if not args.photos and not args.text:
        parser.error("give a photo or --text FILE")
    jobs = [(args.text, None)] if args.text else [(photo, args.engine) for photo in args.photos]
    answers, status = [], 0
    for source, engine in jobs:
        try:
            lines = (Path(source).read_text(encoding="utf-8-sig").splitlines() if engine is None
                     else ocr(source, engine))
        except (OcrUnavailable, OSError) as e:
            answers.append({"source": source, "error": str(e)})
            status = 1
            continue
        try:
            answers.append(dict(propose(lines), source=source, lines=lines))
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
            continue
        print(f"  read: {' | '.join(answer['lines']) or '(nothing)'}")
        print(f"  {answer['message']}")
        for p in answer["proposals"]:
            print(f"  - {p['name']} ({p['set'].upper()}) {p['collector_number']} {p['finish']}"
                  f"{' ' + p['language'] if p['language'] else ''}  [{p['how']}]")
    return status


if __name__ == "__main__":
    sys.exit(main())
